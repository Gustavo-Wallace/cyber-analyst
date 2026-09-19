from copy import deepcopy
from dataclasses import replace,FrozenInstanceError
import json
from unittest.mock import Mock
import polars as pl
import pytest
from cyber_analyst.data.dataset import Dataset
from cyber_analyst.semantic.models import ColumnUnderstanding,DatasetUnderstanding
from cyber_analyst.correlation.planner import CorrelationPlanner,CorrelationPlanningError,generate_candidates
from cyber_analyst.ai import AIService


def inputs(tmp_path):
 datasets=[]; understandings=[]
 for name in ('users','events'):
  frame=pl.DataFrame({'login':['never_send_sample'],'email':['private@example.org'],'n':[1]})
  path=tmp_path/(name+'.csv')
  dataset=Dataset(path,1,frame.schema,frame,frame.lazy()); datasets.append(dataset)
  understandings.append(DatasetUnderstanding(path,dataset.name,'unknown','generic',0.5,'not sent',tuple(
   ColumnUnderstanding(col,kind,None,0.5,True) for col,kind in [('login','username'),('email','email'),('n','user_id')])))
 return dict(datasets=datasets,understandings=understandings)


def selection(candidate, **changes):
 return {'candidate_id':candidate.id,'confidence':0.8,'rationale':'Possible reference',**changes}


def test_username_candidates_stable_and_immutable(tmp_path):
 data=inputs(tmp_path); candidates=generate_candidates(**data)
 assert len(candidates)==3
 assert any(c.left_column==c.right_column=='login' for c in candidates)
 assert candidates==generate_candidates(datasets=reversed(data['datasets']),understandings=reversed(data['understandings']))
 with pytest.raises(FrozenInstanceError): candidates[0].id='changed'


def test_hostname_candidate(tmp_path):
 data=inputs(tmp_path)
 data['understandings']=[replace(u,columns=tuple(replace(c,semantic_type='hostname') if c.name=='login' else c for c in u.columns)) for u in data['understandings']]
 assert any(c.left_column==c.right_column=='login' for c in generate_candidates(**data))


def test_incompatible_excluded(tmp_path):
 data=inputs(tmp_path)
 data['datasets'][0]=replace(data['datasets'][0],schema=pl.Schema({'login':pl.Int64,'email':pl.String,'n':pl.Int64}))
 candidates=generate_candidates(**data)
 assert not any(c.left_column=='login' or c.right_column=='login' for c in candidates)
 assert not any({c.left_column,c.right_column}=={'email','n'} for c in candidates)


@pytest.mark.parametrize('kind',['unknown','generic_identifier','free_text','numeric_measure','status','severity'])
def test_unsuitable_no_ai(tmp_path,kind):
 data=inputs(tmp_path)
 data['understandings']=[replace(u,columns=tuple(replace(c,semantic_type=kind) for c in u.columns)) for u in data['understandings']]
 assert generate_candidates(**data)==()
 ai=Mock()
 assert CorrelationPlanner(ai).plan(**data).proposals==()
 ai.generate_structured.assert_not_called()


def test_non_identifier_excluded(tmp_path):
 data=inputs(tmp_path)
 data['understandings']=[replace(u,columns=tuple(replace(c,is_identifier=False) for c in u.columns)) for u in data['understandings']]
 assert generate_candidates(**data)==()


def test_valid_selection_fixed_endpoints_no_samples(tmp_path):
 data=inputs(tmp_path); candidate=generate_candidates(**data)[0]
 ai=Mock(); ai.generate_structured.return_value={'selections':[selection(candidate)]}
 result=CorrelationPlanner(ai).plan(**data)
 assert result.proposals[0].id==candidate.id
 assert result.proposals[0].left_dataset==candidate.left_dataset
 assert result.proposals[0].right_column==candidate.right_column
 messages=ai.generate_structured.call_args.kwargs['messages']
 assert 'never_send_sample' not in json.dumps(messages)
 assert 'private@example.org' not in json.dumps(messages)
 assert 'not sent' not in json.dumps(messages)
 payload=json.loads(messages[1]['content'])
 assert len(payload['candidates'])==3


def test_empty_selection(tmp_path):
 ai=Mock(); ai.generate_structured.return_value={'selections':[]}
 assert CorrelationPlanner(ai).plan(**inputs(tmp_path)).proposals==()
 assert ai.generate_structured.call_count==1


@pytest.mark.parametrize('invalid',['id','duplicate','confidence','count','endpoint'])
def test_selection_rejected(tmp_path,invalid):
 data=inputs(tmp_path); item=selection(generate_candidates(**data)[0]); items=[item]
 if invalid=='id': item['candidate_id']='invented'
 elif invalid=='duplicate': items.append(deepcopy(item))
 elif invalid=='confidence': item['confidence']=1.1
 elif invalid=='count': items=[deepcopy(item) for _ in range(9)]
 else: item['left_dataset']='invented'
 ai=Mock(); ai.generate_structured.return_value={'selections':items}
 with pytest.raises(CorrelationPlanningError): CorrelationPlanner(ai).plan(**data)
 assert ai.generate_structured.call_count==(2 if invalid=='duplicate' else 1)


def test_domain_retry_success(tmp_path):
 data=inputs(tmp_path); item=selection(generate_candidates(**data)[0])
 ai=Mock(); ai.generate_structured.side_effect=[{'selections':[item,item]},{'selections':[item]}]
 assert len(CorrelationPlanner(ai).plan(**data).proposals)==1
 assert ai.generate_structured.call_count==2
 assert 'Possible reference' not in ai.generate_structured.call_args.kwargs['messages'][-1]['content']


def test_context_mismatch(tmp_path):
 data=inputs(tmp_path); data['datasets']=[data['datasets'][0]]*2
 ai=Mock()
 with pytest.raises(CorrelationPlanningError): CorrelationPlanner(ai).plan(**data)
 ai.generate_structured.assert_not_called()


def test_ai_service_offline(tmp_path):
 data=inputs(tmp_path); candidate=generate_candidates(**data)[0]
 provider=Mock(); provider.generate_structured.return_value=json.dumps({'selections':[selection(candidate)]})
 assert CorrelationPlanner(AIService(provider)).plan(**data).proposals
