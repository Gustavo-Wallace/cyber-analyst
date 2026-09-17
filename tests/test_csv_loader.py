import polars as pl
import pytest

from cyber_analyst.data.csv_loader import DatasetLoadError, load_csv


@pytest.mark.parametrize("as_string", [False, True])
def test_valid_csv(tmp_path, as_string):
    path = tmp_path / "events.csv"
    content = b"id,host,score,active\n1,alpha,1.5,true\n2,beta,2.5,false\n3,gamma,3.5,true\n"
    path.write_bytes(content)
    dataset = load_csv(str(path) if as_string else path)

    assert dataset.path == path.resolve()
    assert dataset.name == "events.csv"
    assert dataset.row_count == 3
    assert dataset.column_count == 4
    assert dataset.columns == ["id", "host", "score", "active"]
    assert dataset.schema == {
        "id": pl.Int64, "host": pl.String, "score": pl.Float64, "active": pl.Boolean,
    }
    assert dataset.preview.rows() == [
        (1, "alpha", 1.5, True), (2, "beta", 2.5, False), (3, "gamma", 3.5, True),
    ]
    assert isinstance(dataset.lazy_frame, pl.LazyFrame)
    assert dataset.lazy_frame.filter(pl.col("active")).collect().height == 2
    assert path.read_bytes() == content


def test_header_only(tmp_path):
    path = tmp_path / "header.csv"
    path.write_text("id,host\n", encoding="utf-8")
    dataset = load_csv(path)
    assert dataset.row_count == 0
    assert dataset.column_count == 2
    assert dataset.columns == ["id", "host"]
    assert dataset.preview.shape == (0, 2)
    assert dataset.preview.schema == dataset.schema


def test_preview_limit_and_literal_path(tmp_path):
    path = tmp_path / "events[1].CSV"
    path.write_text("id\n" + "\n".join(map(str, range(250))), encoding="utf-8")
    dataset = load_csv(path)
    assert dataset.row_count == 250
    assert dataset.preview["id"].to_list() == list(range(100))


def test_missing_path(tmp_path):
    with pytest.raises(DatasetLoadError, match="inexistente"):
        load_csv(tmp_path / "missing.csv")


def test_directory(tmp_path):
    with pytest.raises(DatasetLoadError, match="não é um arquivo"):
        load_csv(tmp_path)


def test_invalid_extension(tmp_path):
    path = tmp_path / "events.txt"
    path.write_text("id\n1\n", encoding="utf-8")
    with pytest.raises(DatasetLoadError, match="Somente arquivos .csv"):
        load_csv(path)


def test_empty_file(tmp_path):
    path = tmp_path / "empty.csv"
    path.touch()
    with pytest.raises(DatasetLoadError, match="vazio"):
        load_csv(path)


@pytest.mark.parametrize("content", [
    b"id,host\n1,alpha,extra\n",
    b"id,host\n1,\xff\n",
    b"id,host\n" + b"1,alpha\n" * 200 + b"invalid,beta\n",
])
def test_invalid_csv(tmp_path, content):
    path = tmp_path / "invalid.csv"
    path.write_bytes(content)
    with pytest.raises(DatasetLoadError, match="estrutura e encoding"):
        load_csv(path)
    assert path.read_bytes() == content
