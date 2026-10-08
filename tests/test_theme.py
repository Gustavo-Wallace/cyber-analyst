"""Theme refresh preserves categorical identity and read-only UI behavior."""
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication
import pytest

from cyber_analyst.ui.theme import (
    COLORS, DATA_PALETTE, ATTENTION_COLORS, data_color, data_colors, apply_theme,
)
from test_investigation_ui import window
from test_investigation_context import synthetic


def test_categorical_and_attention_colors_preserve_previous_identity():
    assert DATA_PALETTE == ('#54ccd7', '#79a9df', '#a995ee', '#b08bd1',
                            '#cf8eb8', '#72bbb0', '#d9b77c')
    assert dict(ATTENTION_COLORS) == {
        'informational':'#79a9df', 'low':'#72bbb0', 'medium':'#a995ee', 'high':'#cf8eb8',
    }
    assert [data_color(k) for k in ('username','email','ip_address','hostname','cve')] == [
        '#54ccd7', '#79a9df', '#a995ee', '#72bbb0', '#cf8eb8',
    ]
    categories = ('IT','Finance','HR','Operations')
    assert data_colors(categories) == data_colors(reversed(categories))


def test_surfaces_are_neutral_charcoal_and_status_colors_unchanged():
    for name in ('background','sidebar','canvas','surface','elevated','input','hover','selected','border'):
        channels = [int(COLORS[name][i:i+2],16) for i in (1,3,5)]
        assert max(channels)-min(channels) <= 16, name
    assert {name:COLORS[name] for name in ('success','warning','danger','info')} == {
        'success':'#21D07A', 'warning':'#F4B74A', 'danger':'#FF5D5D', 'info':'#63A8FF',
    }


def luminance(color):
    channels = [int(color[i:i+2], 16)/255 for i in (1,3,5)]
    linear = [v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4 for v in channels]
    return sum(weight * value for weight,value in zip((.2126,.7152,.0722),linear))


@pytest.mark.parametrize('foreground,background', [
    ('text','canvas'), ('text','surface'), ('text','selected'),
    ('text','input'), ('muted','input'),
    ('secondary','elevated'), ('secondary','selected'),
    ('muted','surface'), ('muted','elevated'),
    ('background','cyan'), ('background','cyan_hover'), ('background','cyan_pressed'),
    ('success','surface'), ('warning','surface'), ('danger','surface'), ('info','surface'),
])
def test_text_and_status_contrast(foreground, background):
    low,high = sorted((luminance(COLORS[foreground]),luminance(COLORS[background])))
    assert (high+.05)/(low+.05) >= 4.5


def test_theme_reapplication_preserves_state_geometry_and_navigation(window):
    window.set_investigation(synthetic())
    session = window.investigation_session
    session.set_dataset_scope(('remote_access',))
    session.navigate(next(iter(session.search('ana'))))
    QApplication.processEvents()
    before = (session.result,session.context,session.state,session.view)
    controls = (window.workspace.header,window.workspace.search,window.workspace.filters_button,
                window.workspace.inspector_button,window.sidebar)
    geometry = tuple(widget.geometry() for widget in controls)
    charts = tuple(window.overview_page.visual_panels.values())
    apply_theme(window)
    QApplication.processEvents()
    assert all(a is b for a,b in zip(before,(session.result,session.context,session.state,session.view)))
    assert tuple(widget.geometry() for widget in controls) == geometry
    assert tuple(window.overview_page.visual_panels.values()) == charts
    assert window.palette().color(QPalette.ColorRole.Window).name().lower() == COLORS['background'].lower()
    assert window.palette().color(QPalette.ColorRole.ToolTipBase).name().lower() == COLORS['elevated'].lower()
    assert window.workspace.search.palette().color(QPalette.ColorRole.Base).name().lower() == COLORS['input'].lower()
    window.navigation.button(5).click()
    assert window.workspace.command_panel.isHidden() and window.workspace.run_button.isHidden()
    assert window.settings_page.apply_button.isEnabled()
    window.navigation.button(0).click()
    assert not window.workspace.command_panel.isHidden()
    assert all(a is b for a,b in zip(before,(session.result,session.context,session.state,session.view)))


def test_analysis_grid_uses_theme_without_changing_series_or_result(window):
    from test_investigation_analysis_page import fixture
    result = fixture()
    window.set_investigation(result)
    page = window.analysis_explorer
    page.selector.selectRow(0)
    chart = page.chart_view.chart()
    assert all(axis.gridLineColor().name().lower() == COLORS['border'].lower()
               for axis in chart.axes())
    bars = chart.series()[0].barSets()[0]
    assert [bars.at(i) for i in range(bars.count())] == [2, 1]
    assert result.datasets[0].analysis_execution.results[0].rows == (('ana',2), ('bruno',1))
