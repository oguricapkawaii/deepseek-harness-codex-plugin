"""Launch the server from the plugin-local virtual environment."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    plugin_root = Path(__file__).resolve().parents[1]
    python_name = "python.exe" if os.name == "nt" else "python"
    venv_python = plugin_root / ".venv" / ("Scripts" if os.name == "nt" else "bin") / python_name
    if not venv_python.exists():
        print(
            "DeepSeek Coding Agent is not set up. Run `python scripts/setup.py` in the plugin directory.",
            file=sys.stderr,
            flush=True,
        )
        return 2
    env = os.environ.copy()
    env["PYTHONPATH"] = str(plugin_root / "src")
    if os.name != "nt":
        os.chdir(plugin_root)
        os.execve(str(venv_python), [str(venv_python), "-m", "deepseek_coding_agent.server"], env)
    return subprocess.call(
        [str(venv_python), "-m", "deepseek_coding_agent.server"],
        cwd=plugin_root,
        env=env,
    )


if __name__ == "__main__":
    raise SystemExit(main())
