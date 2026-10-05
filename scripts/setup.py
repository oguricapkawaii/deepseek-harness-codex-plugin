"""Create a plugin-local virtual environment and install pinned dependencies."""

from __future__ import annotations

import os
import subprocess
import sys
import venv
from pathlib import Path


def main() -> int:
    plugin_root = Path(__file__).resolve().parents[1]
    venv_dir = plugin_root / ".venv"
    if not venv_dir.exists():
        venv.EnvBuilder(with_pip=True).create(venv_dir)
    python_name = "python.exe" if os.name == "nt" else "python"
    venv_python = venv_dir / ("Scripts" if os.name == "nt" else "bin") / python_name
    subprocess.run(
        [str(venv_python), "-m", "pip", "install", "--requirement", str(plugin_root / "requirements.txt")],
        cwd=plugin_root,
        check=True,
    )
    print(f"Ready: {venv_python}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
