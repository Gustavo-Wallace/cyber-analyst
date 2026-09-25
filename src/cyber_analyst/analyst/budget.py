"""Deterministic UTF-8 budget applied only to an independent projection."""
from .models import AnalystContext

MAX_CONTEXT_BYTES = 12 * 1024
# Least important first. Focus has its own independent, protected section.
PRUNING_ORDER = ('datasets', 'analyses', 'relations', 'entities', 'correlations', 'findings')


def apply_budget(context):
    payload = context.to_dict()
    budget = {'serialized_bytes': 0, 'max_bytes': MAX_CONTEXT_BYTES, 'truncated': False,
              'pruned_collections': []}
    payload['metadata']['budget'] = budget

    def measure():
        # Account for the decimal size field itself; converge to its fixed point.
        while True:
            size = len(AnalystContext(**payload).to_json().encode('utf-8'))
            if budget['serialized_bytes'] == size:
                return size
            budget['serialized_bytes'] = size

    def drop(collection):
        collection['items'].pop()
        collection['included_count'] = len(collection['items'])
        collection['truncated'] = collection['included_count'] < collection['total_count']
        budget['truncated'] = True

    for name in PRUNING_ORDER:
        collection = payload['data'][name]
        while measure() > MAX_CONTEXT_BYTES and collection['items']:
            if name not in budget['pruned_collections']:
                budget['pruned_collections'].append(name)
            drop(collection)

    def collections(node, path=()):
        if isinstance(node, dict):
            if {'items', 'total_count', 'included_count', 'truncated'} <= node.keys():
                if node['items']:
                    yield path, node
                return
            for key in sorted(node):
                yield from collections(node[key], (*path, key))

    # Retain focus identity/core fields. Bound its largest nested collection first.
    while measure() > MAX_CONTEXT_BYTES:
        candidates = list(collections(payload['data']['focus']))
        if not candidates:
            break
        _, collection = min(candidates, key=lambda pair: (
            -len(AnalystContext({}, {'value': pair[1]}).to_json().encode('utf-8')), pair[0]))
        drop(collection)

    def texts(node, path=()):
        if isinstance(node, dict):
            if {'text', 'total_count', 'included_count', 'truncated'} <= node.keys():
                if node['text']:
                    yield path, node
                return
            for key in sorted(node):
                # Identity is never shortened by the global budget.
                if key.endswith('_id') or key in ('dataset_name', 'left_dataset', 'right_dataset'):
                    continue
                yield from texts(node[key], (*path, key))

    while measure() > MAX_CONTEXT_BYTES:
        candidates = list(texts(payload['data']['focus']))
        if not candidates:
            # Never emit an oversized payload or silently discard protected metadata.
            raise ValueError('Analyst context identity/filters exceed the global byte budget')
        _, value = min(candidates, key=lambda pair: (-len(pair[1]['text'].encode('utf-8')), pair[0]))
        value['text'] = value['text'][:len(value['text']) // 2]
        value['included_count'] = len(value['text'])
        value['truncated'] = True
        budget['truncated'] = True
    measure()
    return AnalystContext(**payload)
