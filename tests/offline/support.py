"""Small stdlib-only helpers for offline distribution tests."""

from pathlib import Path
import subprocess


def run(command, *, cwd, env=None, input="", timeout=20) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        input=input,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def write_file(root, relative, text, mode=0o644) -> Path:
    path = Path(root) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(mode)
    return path
