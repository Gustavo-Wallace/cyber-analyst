import pytest

from cyber_analyst.analysis.exploratory import profile_dataset
from cyber_analyst.correlation.engine import correlate
from cyber_analyst.data.csv_loader import load_csv
from cyber_analyst.data.dataset_collection import DatasetCollection
from cyber_analyst.data.session_results import SessionResults


@pytest.fixture
def datasets(tmp_path):
    collection = DatasetCollection()
    for name in ("a", "b", "c"):
        path = tmp_path / f"{name}.csv"
        path.write_text("id\n1\n2\n", encoding="utf-8")
        collection.add(load_csv(path))
    return collection


def test_register_and_replace(datasets):
    state = SessionResults()
    assert state.last_analysis is state.last_correlation is None
    a, b, c = datasets.values()
    first = profile_dataset(a)
    state.record_analysis(a, first)
    assert state.last_analysis.profile is first
    second = profile_dataset(b)
    state.record_analysis(b, second)
    assert state.last_analysis.dataset is b
    assert state.last_analysis.profile is second
    correlation = correlate(a, b, "id", "id")
    state.record_correlation(correlation)
    assert state.last_correlation is correlation
    replacement = correlate(b, c, "id", "id")
    state.record_correlation(replacement)
    assert state.last_correlation is replacement


@pytest.mark.parametrize("removed", [0, 1, 2])
def test_invalidation(datasets, removed):
    state = SessionResults()
    a, b, c = datasets.values()
    state.record_analysis(a, profile_dataset(a))
    state.record_correlation(correlate(a, b, "id", "id"))
    datasets.remove((a, b, c)[removed].path)
    state.invalidate(datasets)
    assert (state.last_analysis is None) == (removed == 0)
    assert (state.last_correlation is None) == (removed in (0, 1))


def test_reloaded_path_does_not_revive_result(datasets):
    state = SessionResults()
    a, b, _ = datasets.values()
    state.record_analysis(a, profile_dataset(a))
    state.record_correlation(correlate(a, b, "id", "id"))
    datasets.remove(a.path)
    datasets.add(load_csv(a.path))
    state.invalidate(datasets)
    assert state.last_analysis is state.last_correlation is None
