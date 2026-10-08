from dataclasses import FrozenInstanceError
from datetime import date
from pathlib import Path
from threading import Event

import polars as pl
import pytest

from cyber_analyst.data.dataset import Dataset
from cyber_analyst.data.csv_loader import load_csv
from cyber_analyst.data.value_search import search_values, DataSearchCancelled, MAX_SEARCH_RESULTS


def dataset(name, **columns):
    frame = pl.DataFrame(columns)
    return Dataset(Path(name).resolve(), frame.height, frame.schema, frame.head(100), frame.lazy())


def test_literal_case_insensitive_search_preserves_identity_and_values():
    d = dataset('directory.csv', username=['Ana', 'bruno', None], email=['ANA@corp', 'bruno@corp', ''])
    r = search_values((d,), '  ana  ')
    assert [(h.row.dataset_name, h.row.row_index, h.column_name, h.value) for h in r.hits] == [
        ('directory.csv', 0, 'username', 'Ana'), ('directory.csv', 0, 'email', 'ANA@corp')]
    assert len(r.rows) == 1
    assert r.rows[0].columns == ('username', 'email')
    assert r.rows[0].values == ('Ana', 'ANA@corp')
    assert not r.truncated
    with pytest.raises(FrozenInstanceError):
        r.truncated = True


@pytest.mark.parametrize('query', ['[', '.*', '${x}', '<script>', 'https://evil'])
def test_query_is_literal_data(query):
    d = dataset('data.csv', text=[query, 'unrelated'])
    r = search_values((d,), query)
    assert [h.value for h in r.hits] == [query]


def test_all_datasets_keep_heterogeneous_schemas_and_input_order():
    a = dataset('a.csv', account=['ana'], count=[9])
    b = dataset('b.csv', host=['ANA'], enabled=[True])
    r = search_values((b, a), 'ana')
    assert [h.row.dataset_name for h in r.hits] == ['b.csv', 'a.csv']
    assert r.rows[0].columns == ('host', 'enabled')
    assert r.rows[0].values == ('ANA', True)
    assert r.rows[1].columns == ('account', 'count')
    assert search_values((b, a), 'ana') == r


def test_search_uses_full_data_not_preview_and_safe_row_index(tmp_path):
    path = tmp_path / 'rows.csv'
    path.write_text('_search_row,_search_columns,value\n' + '\n'.join(f'{i},tag,{"needle" if i==149 else "other"}' for i in range(150)), encoding='utf-8')
    before = path.read_bytes()
    d = load_csv(path)
    original_preview = d.preview.clone()
    r = search_values((d,), 'needle')
    assert len(r.hits) == 1
    assert r.hits[0].row.row_index == 149
    assert r.rows[0].values == (149, 'tag', 'needle')
    assert d.preview.equals(original_preview)
    assert path.read_bytes() == before


def test_limit_counts_cell_hits_and_reports_more():
    d = dataset('many.csv', a=['hit']*120, b=['hit']*120)
    r = search_values((d,), 'hit')
    assert len(r.hits) == MAX_SEARCH_RESULTS
    assert len(r.rows) == 100
    assert r.truncated
    assert [h.column_name for h in r.hits[:4]] == ['a','b','a','b']
    exact = search_values((dataset('exact.csv', a=['hit']*200),), 'hit')
    assert len(exact.hits) == 200 and not exact.truncated


def test_limit_applies_across_datasets_and_nulls_are_ignored():
    a = dataset('a.csv', a=['hit']*199)
    b = dataset('b.csv', b=[None, '', 'HIT', 'hit'])
    r = search_values((a,b), 'hit')
    assert len(r.hits) == 200 and r.truncated
    assert r.hits[-1].row.row_index == 2
    assert r.hits[-1].value == 'HIT'


def test_numeric_dates_and_original_types_preserved():
    d = dataset('typed.csv', number=[14.5], day=[date(2026,1,2)])
    assert search_values((d,), '14.5').hits[0].value == 14.5
    assert search_values((d,), '2026-01').hits[0].value == date(2026,1,2)


def test_blank_query_does_not_access_data(monkeypatch):
    monkeypatch.setattr(pl.LazyFrame, 'collect', lambda *a, **k: pytest.fail('empty query scanned'))
    assert search_values((dataset('a.csv', value=['ana']),), ' \t ').hits == ()


def test_cancelled_search_does_not_access_data(monkeypatch):
    event = Event(); event.set()
    monkeypatch.setattr(pl.LazyFrame, 'collect', lambda *a, **k: pytest.fail('cancelled query scanned'))
    with pytest.raises(DataSearchCancelled):
        search_values((dataset('a.csv', value=['ana']),), 'ana', event)
