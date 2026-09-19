from dataclasses import replace, FrozenInstanceError
from unittest.mock import Mock

import pytest

from cyber_analyst.correlation import engine
from cyber_analyst.correlation.execution import CorrelationExecutionService, CorrelationExecutionError
from cyber_analyst.correlation.planner import CorrelationPlan, CorrelationProposal
from cyber_analyst.data.csv_loader import load_csv


@pytest.fixture
def datasets(tmp_path):
    items = []
    for name, content in [('a.csv', 'key,other\n1,x\n2,y\n2,y\n3,z\n'),
                          ('b.csv', 'key,other\n2,y\n3,z\n4,w\n')]:
        path = tmp_path / name
        path.write_text(content, encoding='utf-8')
        items.append(load_csv(path))
    return items


def proposal(**changes):
    return replace(CorrelationProposal('p1','a.csv','key','b.csv','key','Possible shared key',0.9), **changes)


def execute(datasets, *proposals):
    return CorrelationExecutionService().execute(datasets=datasets, plan=CorrelationPlan(proposals))


def test_valid_metrics_metadata_and_source(datasets):
    before = [d.path.read_bytes() for d in datasets]
    result = execute(datasets, proposal()).results[0]
    expected = engine.correlate(*datasets, 'key', 'key')
    assert result.correlation_result.summary == expected.summary
    assert result.correlation_result.summary.common == 2
    assert result.correlation_result.summary.matched_rows == 3
    assert sorted(result.correlation_result.preview_rows) == sorted(expected.preview_rows)
    assert result.proposal_id == 'p1'
    assert (result.left_dataset,result.left_column,result.right_dataset,result.right_column) == ('a.csv','key','b.csv','key')
    assert result.confidence == 0.9
    assert result.rationale == proposal().rationale
    assert before == [d.path.read_bytes() for d in datasets]
    with pytest.raises(FrozenInstanceError):
        result.confidence = 0.1


def test_multiple(datasets):
    result = execute(datasets,proposal(),proposal(id='p2',left_column='other',right_column='other'))
    assert [r.proposal_id for r in result.results] == ['p1','p2']
    assert all(r.correlation_result.summary.matched_rows == 3 for r in result.results)


def test_empty_no_engine_or_dataset_access(monkeypatch):
    connect = Mock(side_effect=AssertionError('DuckDB accessed'))
    monkeypatch.setattr(engine.duckdb, 'connect', connect)
    def unavailable():
        raise AssertionError('datasets accessed')
        yield
    assert CorrelationExecutionService().execute(plan=CorrelationPlan(()),datasets=unavailable()).results == ()
    connect.assert_not_called()


@pytest.mark.parametrize('changes', [dict(left_dataset='missing'),dict(right_column='missing'),
                                    dict(right_dataset='a.csv'),dict(right_column='other')])
def test_preflight_failure(datasets,changes,monkeypatch):
    correlate = Mock()
    monkeypatch.setattr(engine,'correlate',correlate)
    bad = proposal(id='bad',**changes)
    with pytest.raises(CorrelationExecutionError) as error:
        execute(datasets,proposal(),bad)
    assert error.value.proposal is bad
    assert error.value.proposal_id == 'bad'
    assert error.value.__cause__ is not None
    correlate.assert_not_called()


def test_engine_failure_wrapped_without_partial_return(datasets,monkeypatch):
    original = engine.correlate(*datasets,'key','key')
    failure = engine.CorrelationError('engine failed')
    mock = Mock(side_effect=[original,failure])
    monkeypatch.setattr(engine,'correlate',mock)
    with pytest.raises(CorrelationExecutionError) as error:
        execute(datasets,proposal(),proposal(id='second'))
    assert error.value.proposal_id == 'second'
    assert error.value.__cause__ is failure
    assert mock.call_count == 2


def test_actual_engine_failure(datasets):
    datasets[1].path.unlink()
    with pytest.raises(CorrelationExecutionError) as error:
        execute(datasets,proposal())
    assert isinstance(error.value.__cause__,engine.CorrelationError)
    assert error.value.__cause__.__cause__ is not None


def test_ambiguous_name(datasets):
    with pytest.raises(CorrelationExecutionError,match='ambiguous'):
        execute([*datasets,datasets[0]],proposal())


def test_engine_result_reused_and_preview_limit(datasets,monkeypatch):
    original = engine.correlate(*datasets,'key','key',preview_limit=1)
    mock = Mock(return_value=original)
    monkeypatch.setattr(engine,'correlate',mock)
    result = CorrelationExecutionService().execute(plan=CorrelationPlan((proposal(),)),datasets=datasets,preview_limit=1)
    assert result.results[0].correlation_result is original
    assert len(original.preview_rows) == 1
    assert mock.call_args.kwargs['preview_limit'] == 1
