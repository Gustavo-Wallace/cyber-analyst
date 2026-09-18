import os
import subprocess
from unittest.mock import Mock

import pytest

from cyber_analyst.ai import LlamaClientError, LlamaRuntime, LlamaRuntimeError, RuntimeState
from cyber_analyst.ai import runtime as module


@pytest.fixture
def setup(tmp_path, monkeypatch):
    executable, model = tmp_path / "llama-server.exe", tmp_path / "model.GGUF"
    executable.touch()
    model.touch()
    process = Mock(pid=123, returncode=0)
    process.poll.return_value = None
    popen = Mock(return_value=process)
    monkeypatch.setattr(module.subprocess, "Popen", popen)
    monkeypatch.setattr(LlamaRuntime, "_select_port", lambda self: self.port or 45678)
    health = Mock(return_value=200)
    monkeypatch.setattr(module.LlamaServerClient, "health", health)
    clock = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(module.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    runtime = LlamaRuntime(executable, model, port=12345, startup_timeout=1)
    return runtime, process, popen, health


def test_start_and_context_cleanup(setup):
    runtime, process, popen, _ = setup
    assert runtime.state == RuntimeState.STOPPED
    with runtime:
        assert runtime.is_alive and runtime.is_ready and runtime.has_process
        assert runtime.base_url == "http://127.0.0.1:12345"
        assert popen.call_args.args[0] == [str(runtime.executable_path), "-m", str(runtime.model_path),
                                          "--host", "127.0.0.1", "--port", "12345"]
        assert popen.call_args.kwargs["stdout"] == subprocess.DEVNULL
        assert popen.call_args.kwargs["stderr"] == subprocess.DEVNULL
        if os.name == "nt":
            assert popen.call_args.kwargs["creationflags"] == subprocess.CREATE_NO_WINDOW
        with pytest.raises(LlamaRuntimeError, match="já possui"):
            runtime.start()
    process.terminate.assert_called_once()
    assert not runtime.has_process and runtime.state == RuntimeState.STOPPED
    runtime.stop()
    process.terminate.assert_called_once()


@pytest.mark.parametrize("invalid", ["executable", "model", "extension", "directory"])
def test_validation(setup, invalid, tmp_path):
    runtime, _, popen, _ = setup
    if invalid == "executable":
        runtime.executable_path.unlink()
    elif invalid == "model":
        runtime.model_path.unlink()
    elif invalid == "extension":
        path = tmp_path / "model.txt"
        path.touch()
        runtime.model_path = path
    else:
        runtime.executable_path = tmp_path
    with pytest.raises(LlamaRuntimeError):
        runtime.start()
    popen.assert_not_called()
    assert runtime.state == RuntimeState.FAILED


def test_loading_then_ready(setup):
    runtime, _, _, health = setup
    health.side_effect = [LlamaClientError("Unavailable"), 503, 200]
    runtime.start()
    assert runtime.is_ready and health.call_count == 3
    runtime.stop()


def test_early_exit(setup):
    runtime, process, _, health = setup
    process.poll.return_value = 7
    with pytest.raises(LlamaRuntimeError, match="código 7"):
        runtime.start()
    health.assert_not_called()
    assert not runtime.has_process and runtime.state == RuntimeState.FAILED


def test_startup_timeout_cleans_up(setup):
    runtime, process, _, health = setup
    health.return_value = 503
    with pytest.raises(LlamaRuntimeError, match="Timeout"):
        runtime.start()
    process.terminate.assert_called_once()
    assert not runtime.has_process and runtime.state == RuntimeState.FAILED


def test_force_stop(setup):
    runtime, process, _, _ = setup
    runtime.start()
    process.wait.side_effect = [subprocess.TimeoutExpired("server", 5), 0]
    runtime.stop()
    process.kill.assert_called_once()
    assert not runtime.has_process


def test_spawn_failure(setup):
    runtime, _, popen, _ = setup
    popen.side_effect = OSError("cannot execute")
    with pytest.raises(LlamaRuntimeError, match="iniciar"):
        runtime.start()
    assert runtime.state == RuntimeState.FAILED


def test_post_ready_death(setup):
    runtime, process, _, _ = setup
    runtime.start()
    process.poll.return_value = 2
    assert runtime.state == RuntimeState.FAILED
    assert not runtime.is_ready and not runtime.is_alive
    runtime.stop()


def test_port_selection():
    runtime = LlamaRuntime("unused", "unused.gguf")
    assert 1 <= runtime._select_port() <= 65535
