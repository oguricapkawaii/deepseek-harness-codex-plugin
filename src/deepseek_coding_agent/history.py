"""Read-only access to the isolated Harness session archive."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from .harness import HarnessLayout, _clip


async def _run_helper(*args: str) -> dict[str, Any]:
    layout = HarnessLayout.from_env()
    layout.validate()
    plugin_root = Path(__file__).resolve().parents[2]
    helper = plugin_root / "scripts" / "history.mjs"
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    def invoke() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            layout.node_command(
                str(helper),
                *args,
                str(layout.data_home),
                str(layout.install_home),
            ),
            cwd=plugin_root,
            env=layout.runtime_env(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            creationflags=creationflags,
            check=False,
        )

    completed = await asyncio.to_thread(invoke)
    output = completed.stdout
    diagnostics = completed.stderr.strip()
    if completed.returncode != 0:
        raise RuntimeError("Harness history reader failed: " + _clip(diagnostics or output, 4_000))
    result = json.loads(output)
    if not isinstance(result, dict):
        raise RuntimeError("Harness history reader returned an invalid response")
    return result


async def list_history(limit: int = 20, workspace: str = "") -> dict[str, Any]:
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    return await _run_helper("list", str(limit), workspace.strip())


async def export_history(session_id: str, max_chars: int = 30_000) -> dict[str, Any]:
    session_id = session_id.strip()
    if not session_id:
        raise ValueError("session_id must not be empty")
    if not 1_000 <= max_chars <= 80_000:
        raise ValueError("max_chars must be between 1000 and 80000")
    return await _run_helper("export", session_id, str(max_chars))
