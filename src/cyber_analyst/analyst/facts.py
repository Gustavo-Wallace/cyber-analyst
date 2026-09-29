"""Fact projection from bounded data only; no inference or data access."""
import hashlib
import json
from dataclasses import dataclass, asdict
from .models import AnalystReference
from .budget import MAX_CONTEXT_BYTES

FIELDS = {'datasets':('dataset','dataset_name'), 'entities':('entity','entity_id'),
          'relations':('relation','relation_id'), 'correlations':('correlation','correlation_id'),
          'findings':('finding','finding_id'), 'analyses':('analysis','analysis_id')}

def encode(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',', ':'),allow_nan=False)

@dataclass(frozen=True)
class AnalystFact:
    fact_id: str
    reference: AnalystReference
    path: str
    value_json: str

    def to_dict(self):
        return {'fact_id':self.fact_id,'reference':asdict(self.reference),'path':self.path,'value':json.loads(self.value_json)}


def fact_registry(context, scope):
    data=context.to_dict()['data'];focus=data.get('focus',{})
    if scope not in ('current_focus','visible_investigation'):
        raise ValueError('Invalid analyst scope')
    if scope=='current_focus' and focus.get('kind','none')=='none':
        raise ValueError('current_focus requires an active focus')
    objects=[]
    if scope=='visible_investigation':
        for section in ('findings','correlations','entities','relations','analyses','datasets'):
            objects.extend((section,o) for o in data.get(section,{}).get('items',[]))
    else:
        section=focus['kind'];obj=focus['object'];objects.append((section,obj))
        linked={}
        if section=='entities':
            linked['relations']=obj.get('visible_relation_ids',{}).get('items',[])
            linked['entities']=obj.get('visible_neighbor_ids',{}).get('items',[])
            linked['datasets']=obj.get('dataset_names',{}).get('items',[])
        elif section=='relations':
            linked['entities']=[obj.get('entity_a_id'),obj.get('entity_b_id')]
        elif section=='correlations':
            linked['datasets']=[obj.get('left_dataset'),obj.get('right_dataset')]
        elif section=='analyses':linked['datasets']=[obj.get('dataset_name')]
        for kind,ids in linked.items():
            field=FIELDS[kind][1]
            objects.extend((kind,o) for o in data.get(kind,{}).get('items',[]) if o.get(field) in ids)
    facts={}
    def walk(value,path):
        if isinstance(value,dict):
            if 'items' in value and 'included_count' in value:
                for i,item in enumerate(value['items']):
                    if path.endswith(('rows','occurrences','preview')):
                        yield f'{path}/{i}',item
                    else:yield from walk(item,f'{path}/{i}')
                return
            if 'text' in value and value.get('truncated'):
                yield path,value;return
            for key in sorted(value):yield from walk(value[key],f'{path}/{key}' if path else key)
        elif isinstance(value,list):
            for i,item in enumerate(value):yield from walk(item,f'{path}/{i}')
        else:yield path,value
    for section,obj in objects:
        kind,field=FIELDS[section];identifier=obj.get(field)
        if not isinstance(identifier,str):continue
        reference=AnalystReference(kind,identifier,obj.get('dataset_name') if kind=='analysis' else None)
        for path,value in walk(obj,''):
            if path==field:continue
            value_json=encode(value)
            digest=hashlib.sha256(encode([asdict(reference),path,value]).encode('utf-8')).hexdigest()
            fact=AnalystFact('fact_'+digest,reference,path,value_json)
            facts.setdefault(fact.fact_id,fact)
    return tuple(facts.values())


def evidence_packet(context,scope):
    facts=fact_registry(context,scope)
    packet={'scope':scope,'focus_kind':context.data['focus']['kind'],
            'facts':[],'total_count':len(facts),'included_count':0,'truncated':False}
    focus = context.to_dict()['data'].get('focus', {})
    if scope == 'current_focus':
        kind, field = FIELDS[focus['kind']]
        obj = focus['object']
        packet['focus_reference'] = asdict(AnalystReference(kind, obj[field], obj.get('dataset_name') if kind == 'analysis' else None))
    selected=[]
    for fact in facts:
        packet['facts'].append(fact.to_dict());packet['included_count']+=1
        packet['truncated']=packet['included_count']<len(facts)
        if len(encode(packet).encode('utf-8'))>MAX_CONTEXT_BYTES:
            packet['facts'].pop();packet['included_count']-=1;packet['truncated']=True
            break
        selected.append(fact)
    return tuple(selected),packet
