import math
from dataclasses import replace

import polars as pl
import pytest

from cyber_analyst.analysis.exploratory import AnalysisError, get_column_distribution, profile_dataset
from cyber_analyst.data.csv_loader import load_csv


def csv_dataset(tmp_path, content):
    path = tmp_path / "mixed.csv"
    path.write_text(content, encoding="utf-8")
    return load_csv(path)


def test_mixed_profile(tmp_path):
    dataset = csv_dataset(tmp_path, "id,score,host,active,empty\n1,1.5,a,true,\n2,2.5,a,false,\n3,,b,true,\n")
    original = dataset.path.read_bytes()
    result = profile_dataset(dataset)
    assert (result.name, result.row_count, result.column_count, result.null_count) == ("mixed.csv", 3, 5, 4)
    integer, floating, text, boolean, empty = result.columns
    assert integer.dtype == pl.Int64
    assert (integer.minimum, integer.maximum, integer.mean, integer.median, integer.std) == (1, 3, 2, 2, 1)
    assert floating.null_count == 1
    assert floating.null_percentage == pytest.approx(100 / 3)
    assert floating.unique_count == 3  # Inclui nulo.
    assert floating.mean == 2
    assert floating.std == pytest.approx(math.sqrt(0.5))
    assert text.dtype == pl.String and text.unique_count == 2 and text.mean is None
    assert boolean.dtype == pl.Boolean and boolean.minimum is None
    assert empty.null_count == 3 and empty.null_percentage == 100
    assert empty.unique_count == 1 and empty.mean is None
    assert dataset.path.read_bytes() == original


def test_empty_and_single_value(tmp_path):
    empty = profile_dataset(csv_dataset(tmp_path, "id,host\n"))
    assert empty.row_count == empty.null_count == 0
    for column in empty.columns:
        assert column.null_percentage == 0
        assert column.unique_count == 0
        assert column.mean is None
    dataset = csv_dataset(tmp_path, "id\n5\n")
    column = profile_dataset(dataset).columns[0]
    assert column.std is None
    assert column.mean == column.median == 5


@pytest.mark.parametrize("content", ["id,value\n", "id,value\n1,\n2,\n"])
def test_numeric_null_or_empty_column(tmp_path, content):
    dataset = csv_dataset(tmp_path, content)
    frame = dataset.lazy_frame.with_columns(pl.col("value").cast(pl.Float64))
    dataset = replace(dataset, lazy_frame=frame, schema=frame.collect_schema())
    column = profile_dataset(dataset).columns[1]
    assert column.null_count == dataset.row_count
    assert column.null_percentage == (100 if dataset.row_count else 0)
    assert (column.minimum, column.maximum, column.mean, column.median, column.std) == (None,) * 5


@pytest.mark.parametrize("column", ["host", "id", "active"])
def test_distribution_types_and_nulls(tmp_path, column):
    dataset = csv_dataset(tmp_path, "host,id,active\na,1,true\na,1,true\nb,2,false\n,,\n")
    result = get_column_distribution(dataset, column)
    assert [item.count for item in result.values] == [2, 1, 1]
    assert [item.percentage for item in result.values] == [50, 25, 25]
    assert result.values[-1].value is None
    expected = {"host": "a", "id": 1, "active": True}[column]
    assert result.values[0].value == expected
    assert type(result.values[0].value) is type(expected)
    assert len(get_column_distribution(dataset, column, limit=1).values) == 1


def test_distribution_empty_limit_and_errors(tmp_path):
    dataset = csv_dataset(tmp_path, "id\n")
    assert get_column_distribution(dataset, "id").values == ()
    with pytest.raises(AnalysisError, match="inexistente"):
        get_column_distribution(dataset, "unknown")
    with pytest.raises(AnalysisError, match="positivo"):
        get_column_distribution(dataset, "id", 0)
    dataset = csv_dataset(tmp_path, "id\n" + "\n".join(map(str, range(30))))
    values = get_column_distribution(dataset, "id").values
    assert len(values) == 20
    assert [value.value for value in values] == list(range(20))
    dataset.path.unlink()
    with pytest.raises(AnalysisError):
        profile_dataset(dataset)
    with pytest.raises(AnalysisError):
        get_column_distribution(dataset, "id")
