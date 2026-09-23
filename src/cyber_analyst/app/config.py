"""Local paths only; no process startup or persistent settings."""
from dataclasses import dataclass
from pathlib import Path
import os

@dataclass(frozen=True)
class RuntimeConfig:
    llama_executable: Path
    model_path: Path

    def validate(self):
        executable, model = Path(self.llama_executable), Path(self.model_path)
        if not executable.is_file() or executable.name.lower() != 'llama-server.exe':
            raise ValueError('Select an existing llama-server.exe file')
        if not model.is_file() or model.suffix.lower() != '.gguf':
            raise ValueError('Select an existing .gguf model file')

def discover_paths(local_appdata=None):
    root = local_appdata if local_appdata is not None else os.environ.get('LOCALAPPDATA')
    if not root:
        return None, None
    base = Path(root) / 'CyberAnalyst'
    def unique(folder, pattern):
        matches = sorted(p for p in folder.rglob(pattern) if p.is_file()) if folder.is_dir() else []
        return matches[0] if len(matches) == 1 else None
    return unique(base / 'runtime' / 'llama.cpp', 'llama-server.exe'), unique(base / 'models', '*.gguf')
