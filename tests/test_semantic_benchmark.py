from types import SimpleNamespace
from benchmarks.semantic_cases import CASES
from benchmarks.semantic_quality import aggregate, divergences, score


def test_benchmark_expectations_complete():
    assert len(CASES) == 10
    for case in CASES:
        names = set(case.csv.splitlines()[0].split(','))
        assert names == set(case.expected_column_semantics) == set(case.expected_identifier_behavior)


def test_metrics_distinguish_unknown_and_errors():
    case = CASES[-1]
    columns = [SimpleNamespace(name=name,semantic_type='unknown',is_identifier=False) for name in case.expected_column_semantics]
    result = SimpleNamespace(dataset_category='unknown',columns=columns)
    metrics = score(case,result)
    assert metrics['unknown'] == {'correct':1,'unnecessary':4,'invented_under_ambiguity':0}
    assert metrics['category_correct'] == 1
    assert metrics['identifiers_correct'] == 3
    result.dataset_category = 'security_alerts'
    assert score(case,result)['unknown']['invented_under_ambiguity'] == 1
    columns.append(SimpleNamespace(name='invented',semantic_type='unknown',is_identifier=False))
    assert score(case,result)['hallucinated_columns'] == 1
    totals = aggregate([{'expected_columns':4,'expected_identifiers':4,'metrics':metrics},
                        {'expected_columns':4,'expected_identifiers':4,'error':'invalid'}])
    assert totals['failures'] == 1
    assert totals['cases_total'] == 2
    assert totals['columns_total'] == 8
    assert totals['category_accuracy'] == 0.5
    assert totals['column_accuracy'] == 0


def test_consistency_ignores_confidence_but_detects_labels():
    first = {'case':'example','category':'unknown','columns':[
        {'name':'a','semantic_type':'unknown','is_identifier':False,'confidence':0.2}]}
    second = {'case':'example','category':'unknown','columns':[
        {'name':'a','semantic_type':'unknown','is_identifier':False,'confidence':0.3}]}
    assert divergences([first,second]) == []
    second['columns'][0]['is_identifier'] = True
    assert divergences([first,second]) == ['example']


def test_diagnostic_provider_preserves_response_and_reports_schema():
    import json
    from unittest.mock import Mock
    from benchmarks.semantic_quality import DiagnosticProvider
    from cyber_analyst.semantic.service import response_schema
    provider = Mock()
    raw = json.dumps({'dataset_name':'x', 'columns':[{'semantic_type':'invalid'}]})
    provider.generate_structured.return_value = raw
    diagnostic = DiagnosticProvider(provider)
    assert diagnostic.generate_structured([], 'test', response_schema('columns'), None) == raw
    errors = diagnostic.rejections[0]['violations']
    assert any(error['validator']=='enum' and error['path']==['columns',0,'semantic_type'] for error in errors)
    assert any(error['validator']=='required' for error in errors)
    provider.generate_structured.return_value = 'not json'
    diagnostic.generate_structured([], 'test', response_schema(), None)
    assert diagnostic.rejections[-1]['reason'] == 'invalid_json'


def test_domain_rejection_identifies_missing_column(tmp_path):
    import pytest
    from unittest.mock import Mock
    from test_semantic import make_dataset, response
    from cyber_analyst.semantic import SemanticUnderstandingService, SemanticUnderstandingError
    dataset, profile = make_dataset(tmp_path)
    value = response(dataset)
    removed = value['columns'].pop()['name']
    ai = Mock()
    ai.generate_structured.return_value = value
    with pytest.raises(SemanticUnderstandingError, match='omitidas') as error:
        SemanticUnderstandingService(ai).understand_dataset(dataset,profile)
    assert removed in str(error.value)
