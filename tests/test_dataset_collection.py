from cyber_analyst.data.csv_loader import load_csv
from cyber_analyst.data.dataset_collection import DatasetCollection


def test_collection(tmp_path):
    collection = DatasetCollection()
    assert len(collection) == 0
    assert collection.values() == ()
    datasets = []
    for folder in ("a", "b"):
        directory = tmp_path / folder
        directory.mkdir()
        path = directory / "same.csv"
        path.write_text("id\n1\n", encoding="utf-8")
        datasets.append(load_csv(path))
    first, second = datasets
    assert collection.add(first)
    assert collection.add(second)
    assert collection.values() == (first, second)
    assert collection.get(str(first.path)) is first
    assert collection.contains(first.path.parent / "." / first.name)
    assert not collection.add(first)
    assert len(collection) == 2
    assert collection.remove(first.path) is first
    assert collection.values() == (second,)
    collection.remove(second.path)
    assert len(collection) == 0
    assert first.path.exists() and second.path.exists()
