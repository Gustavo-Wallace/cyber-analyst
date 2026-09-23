import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
import pytest
from PySide6.QtWidgets import QApplication
from cyber_analyst.app.config import RuntimeConfig, discover_paths
from cyber_analyst.app.pipeline_factory import create_pipeline
from cyber_analyst.ui.main_window import MainWindow
from test_investigation_context import synthetic

@pytest.fixture
def config(tmp_path,monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path))
    exe=tmp_path/'CyberAnalyst/runtime/llama.cpp/llama-server.exe'
    model=tmp_path/'CyberAnalyst/models/model.gguf'
    for p in (exe,model):p.parent.mkdir(parents=True,exist_ok=True);p.touch()
    from cyber_analyst.ai.runtime import LlamaRuntime
    def forbidden(*a,**k):raise AssertionError('runtime started')
    monkeypatch.setattr(LlamaRuntime,'start',forbidden)
    return RuntimeConfig(exe,model)

def test_discovery(tmp_path,config):
    assert discover_paths(tmp_path/'missing')==(None,None)
    assert discover_paths(tmp_path)==(config.llama_executable,config.model_path)
    other=config.llama_executable.parent/'other';other.mkdir();(other/'llama-server.exe').touch()
    (config.model_path.parent/'other.gguf').touch()
    assert discover_paths(tmp_path)==(None,None)

def test_validation(config,tmp_path):
    config.validate()
    with pytest.raises(ValueError):RuntimeConfig(tmp_path,config.model_path).validate()
    wrong=tmp_path/'wrong.exe';wrong.touch()
    with pytest.raises(ValueError):RuntimeConfig(wrong,config.model_path).validate()
    model=tmp_path/'wrong.txt';model.touch()
    with pytest.raises(ValueError):RuntimeConfig(config.llama_executable,model).validate()

def test_factory_and_lifecycle(config,monkeypatch):
    p=create_pipeline(config)
    from cyber_analyst.investigation.pipeline import InvestigationPipeline
    from cyber_analyst.entities import EntityService
    assert isinstance(p.pipeline,InvestigationPipeline)
    assert isinstance(p.pipeline.entity_service,EntityService)
    assert not p.runtime.has_process
    calls=[]
    monkeypatch.setattr(p.runtime,'start',lambda:calls.append('start'))
    monkeypatch.setattr(p.runtime,'stop',lambda:calls.append('stop'))
    result=object()
    monkeypatch.setattr(p.pipeline,'run',lambda datasets:result)
    assert p.run(()) is result and calls==['start','stop']
    def fail(datasets):raise ValueError('failure')
    monkeypatch.setattr(p.pipeline,'run',fail)
    with pytest.raises(ValueError):p.run(())
    assert calls==['start','stop','start','stop']

def test_settings_apply_transactional(config):
    app=QApplication.instance() or QApplication([])
    injected=object();w=MainWindow(investigation_pipeline=injected)
    try:
        assert w.investigation_runner.pipeline is injected
        assert w.settings_page.status.text()=='Not configured'
        for entry in synthetic().datasets:w.collection.add(entry.dataset)
        w._collection_changed()
        w.settings_page.apply()
        assert w.settings_page.status.text()=='Valid'
        pipeline=w.investigation_runner.pipeline
        assert pipeline is not injected and not pipeline.runtime.has_process
        assert w.workspace.run_button.isEnabled()
        w.settings_page.model.setText('missing.gguf');w.settings_page.apply()
        assert w.settings_page.status.text().startswith('Invalid')
        assert w.investigation_runner.pipeline is pipeline
        w.investigation_runner.thread=object()
        try:
            with pytest.raises(ValueError):w._apply_runtime_config(config)
            assert w.investigation_runner.pipeline is pipeline
        finally:w.investigation_runner.thread=None
    finally:w.close();app.processEvents()

def test_empty_settings(tmp_path,monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path))
    app=QApplication.instance() or QApplication([])
    w=MainWindow()
    assert not w.settings_page.executable.text() and not w.settings_page.model.text()
    assert w.settings_page.status.text()=='Not configured'
    w.close();app.processEvents()
