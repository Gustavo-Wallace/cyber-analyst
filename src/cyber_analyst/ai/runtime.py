"""Ciclo de vida síncrono de um llama-server local explicitamente configurado.

Use em background quando houver integração futura com GUI. A instância não é
reentrante para start(). stop() pode interromper o startup/inferência de um owner
exclusivo; o lock protege criação/encerramento do processo.
"""

from enum import StrEnum
import logging
import math
import os
from pathlib import Path
import socket
import subprocess
import time
from threading import RLock

from cyber_analyst.ai.client import LlamaClientError, LlamaServerClient


logger = logging.getLogger(__name__)


class LlamaRuntimeError(Exception):
    """Falha esperada ao configurar, iniciar ou encerrar o runtime."""


class RuntimeState(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    READY = "ready"
    FAILED = "failed"


class LlamaRuntime:
    def __init__(self, executable_path: str | Path, model_path: str | Path, *,
                 port: int | None = None, startup_timeout: float = 120.0,
                 poll_interval: float = 0.2, request_timeout: float = 1.0,
                 stop_timeout: float = 5.0) -> None:
        self.executable_path = Path(executable_path)
        self.model_path = Path(model_path)
        if port is not None and (isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535):
            raise LlamaRuntimeError("A porta deve estar entre 1 e 65535.")
        for value in (startup_timeout, poll_interval, request_timeout, stop_timeout):
            if not math.isfinite(value) or value <= 0:
                raise LlamaRuntimeError("Timeouts e intervalo devem ser positivos e finitos.")
        self.port = port
        self.startup_timeout = startup_timeout
        self.poll_interval = poll_interval
        self.request_timeout = request_timeout
        self.stop_timeout = stop_timeout
        self._process = None
        self._state = RuntimeState.STOPPED
        self._base_url = None
        self._process_lock = RLock()

    @property
    def base_url(self) -> str:
        if self._base_url is None:
            raise LlamaRuntimeError("O runtime ainda não selecionou uma porta.")
        return self._base_url

    @property
    def state(self) -> RuntimeState:
        process = self._process
        if process is not None and process.poll() is not None and process is self._process:
            self._state = RuntimeState.FAILED
        return self._state

    @property
    def has_process(self) -> bool:
        return self._process is not None

    @property
    def is_alive(self) -> bool:
        process = self._process
        return process is not None and process.poll() is None

    @property
    def is_ready(self) -> bool:
        return self.state == RuntimeState.READY

    def _select_port(self) -> int:
        # A reserva é liberada antes de Popen; disputa de porta gera falha de startup.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            if os.name == "nt":
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind(("127.0.0.1", self.port if self.port is not None else 0))
            return listener.getsockname()[1]

    def start(self, *, cancel_event=None) -> None:
        if self.is_alive:
            raise LlamaRuntimeError("O runtime já possui um processo em execução.")
        if self._process is not None:
            self.stop()
        self._state = RuntimeState.STARTING
        try:
            executable = self.executable_path.resolve()
            model = self.model_path.resolve()
            if not executable.is_file():
                raise LlamaRuntimeError("Executável inexistente ou não é um arquivo.")
            if not model.is_file():
                raise LlamaRuntimeError("Modelo inexistente ou não é um arquivo.")
            if model.suffix.lower() != ".gguf":
                raise LlamaRuntimeError("O modelo deve possuir extensão .gguf.")
            port = self._select_port()
            self._base_url = f"http://127.0.0.1:{port}"
            command = [str(executable), "-m", str(model), "--host", "127.0.0.1", "--port", str(port)]
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            with self._process_lock:
                if cancel_event is not None and cancel_event.is_set():
                    raise LlamaRuntimeError('Runtime startup cancelled.')
                process = subprocess.Popen(
                    command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, creationflags=flags,
                )
                self._process = process
            # Apenas eventos de ciclo de vida; nunca prompts/respostas ou stdout bruto.
            logger.info("Runtime iniciado: pid=%s, porta=%s", process.pid, port)
            client = LlamaServerClient(self.base_url, timeout=self.request_timeout)
            deadline = time.monotonic() + self.startup_timeout
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise LlamaRuntimeError('Runtime startup cancelled.')
                code = process.poll()
                if code is not None:
                    raise LlamaRuntimeError(f"llama-server encerrou antes de ficar pronto (código {code}).")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise LlamaRuntimeError("Timeout aguardando o modelo ficar pronto.")
                try:
                    ready = client.health(timeout=min(self.request_timeout, remaining)) == 200
                except LlamaClientError:
                    ready = False
                if cancel_event is not None and cancel_event.is_set():
                    raise LlamaRuntimeError('Runtime startup cancelled.')
                if process.poll() is not None:
                    raise LlamaRuntimeError("llama-server encerrou durante o health check.")
                if ready and time.monotonic() < deadline:
                    self._state = RuntimeState.READY
                    logger.info("Runtime pronto: pid=%s", process.pid)
                    return
                time.sleep(min(self.poll_interval, max(0, deadline - time.monotonic())))
        except BaseException as exc:
            # Cleanup também em KeyboardInterrupt; erros inesperados são relançados.
            try:
                self.stop()
            finally:
                self._state = RuntimeState.FAILED
            if isinstance(exc, (OSError, subprocess.SubprocessError)):
                raise LlamaRuntimeError("Não foi possível iniciar o processo local ou reservar a porta.") from exc
            raise

    def stop(self) -> None:
        with self._process_lock:
            self._stop_process()

    def _stop_process(self) -> None:
        process = self._process
        if process is not None:
            try:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=self.stop_timeout)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=self.stop_timeout)
                else:
                    process.wait(timeout=self.stop_timeout)
            except (OSError, subprocess.SubprocessError) as exc:
                self._state = RuntimeState.FAILED
                raise LlamaRuntimeError("Não foi possível encerrar o processo; tente stop() novamente.") from exc
            logger.info("Runtime encerrado: pid=%s, código=%s", process.pid, process.returncode)
        self._process = None
        self._state = RuntimeState.STOPPED

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.stop()
