import pytest

from cyber_analyst.correlation.engine import CorrelationError, correlate
from cyber_analyst.data.csv_loader import load_csv


def pair(tmp_path, a, b):
    datasets = []
    for name, content in (("a.csv", a), ("b.csv", b)):
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        datasets.append(load_csv(path))
    return datasets


def test_intersection(tmp_path):
    a, b = pair(tmp_path, "key\n1\n2\n3\n", "key\n2\n3\n4\n")
    result = correlate(a, b, "key", "key")
    s = result.summary
    assert (s.rows_a, s.rows_b, s.unique_a, s.unique_b, s.common, s.only_a, s.only_b, s.matched_rows) == (3, 3, 3, 3, 2, 1, 1, 2)
    assert result.preview_columns == ("A.key", "B.key")
    assert set(result.preview_rows) == {(2, 2), (3, 3)}


def test_duplicates_nulls_and_trim(tmp_path):
    a, b = pair(tmp_path, 'key,info\n" a@x.com ",one\na@x.com,two\n,missing\nA@x.com,upper\n',
                "key\na@x.com\na@x.com\n\n")
    originals = [d.path.read_bytes() for d in (a, b)]
    result = correlate(a, b, "key", "key")
    s = result.summary
    assert (s.unique_a, s.unique_b, s.common, s.only_a, s.only_b, s.matched_rows) == (2, 1, 1, 1, 0, 4)
    assert s.common + s.only_a == s.unique_a
    assert s.common + s.only_b == s.unique_b
    assert any(row[0] == " a@x.com " for row in result.preview_rows)
    assert originals == [d.path.read_bytes() for d in (a, b)]


def test_empty_and_limited_preview(tmp_path):
    a, b = pair(tmp_path, "key\n", "key\n1\n")
    result = correlate(a, b, "key", "key")
    assert result.summary.common == result.summary.matched_rows == 0
    assert result.summary.only_b == 1
    assert result.preview_rows == ()
    a, b = pair(tmp_path, "key\n" + "1\n" * 20, "key\n" + "1\n" * 20)
    result = correlate(a, b, "key", "key")
    assert result.summary.common == 1
    assert result.summary.matched_rows == 400
    assert len(result.preview_rows) == 100


def test_errors(tmp_path):
    a, b = pair(tmp_path, "key\n123\n", "key\nx\n")
    with pytest.raises(CorrelationError, match="incompatíveis"):
        correlate(a, b, "key", "key")
    with pytest.raises(CorrelationError, match="inexistente"):
        correlate(a, b, "missing", "key")
    with pytest.raises(CorrelationError, match="diferentes"):
        correlate(a, a, "key", "key")
    a, b = pair(tmp_path, "key\n1\n", "key\n1\n")
    b.path.unlink()
    with pytest.raises(CorrelationError, match="arquivos originais"):
        correlate(a, b, "key", "key")


def test_quoted_empty_and_unusual_names(tmp_path):
    a, b = pair(tmp_path, '"k""ey",Key\n"",x\n,value\n', '"k""ey"\n""\n')
    result = correlate(a, b, a.columns[0], b.columns[0])
    assert result.summary.common == 1
    assert result.summary.matched_rows == 1
    assert result.preview_rows == (("", "x", ""),)


def test_literal_path_and_case_distinct_headers(tmp_path):
    a, b = pair(tmp_path, "key,KEY\nx,y\n", "key\nx\n")
    literal = tmp_path / "a[1].csv"
    literal.write_bytes(a.path.read_bytes())
    a = load_csv(literal)
    result = correlate(a, b, "key", "key")
    assert result.preview_columns == ("A.key", "A.KEY", "B.key")
    assert result.preview_rows == (("x", "y", "x"),)


@pytest.mark.parametrize("fail", [False, True])
def test_spill_directory_is_isolated_and_removed(tmp_path, monkeypatch, fail):
    from pathlib import Path
    from cyber_analyst.correlation import engine
    import tempfile

    a, b = pair(tmp_path, "key\nx\nx\n", "key\nx\n")
    cwd = tmp_path / "installation"
    temp_root = tmp_path / "user_temp"
    cwd.mkdir()
    temp_root.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(tempfile, "tempdir", str(temp_root))
    original_connect = engine.duckdb.connect
    directories = []

    def connect(*args, **kwargs):
        directory = Path(kwargs["config"]["temp_directory"])
        assert directory.parent == temp_root
        assert directory.is_dir()
        directories.append(directory)
        connection = original_connect(*args, **kwargs)
        assert connection.execute("SELECT current_setting('temp_directory')").fetchone()[0] == str(directory)
        return connection

    monkeypatch.setattr(engine.duckdb, "connect", connect)
    if fail:
        def broken_relation(*args):
            (directories[-1] / "synthetic-spill.tmp").write_bytes(b"synthetic")
            raise engine.duckdb.Error("controlled failure")
        monkeypatch.setattr(engine, "_relation", broken_relation)
        with pytest.raises(CorrelationError):
            correlate(a, b, "key", "key")
    else:
        assert correlate(a, b, "key", "key").summary.matched_rows == 2
    assert directories and all(not directory.exists() for directory in directories)
    assert not list(cwd.iterdir())
    assert not list(temp_root.iterdir())
