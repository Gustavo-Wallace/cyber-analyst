import subprocess
import sys


def test_module_entry_point():
    result = subprocess.run(
        [sys.executable, "-m", "cyber_analyst"],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "Cyber Analyst iniciado com sucesso."
    assert result.stderr == ""
