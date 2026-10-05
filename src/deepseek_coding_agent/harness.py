"""Safe, bounded launcher for isolated DeepSeek Harness coding runs."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Literal

DEFAULT_HARNESS_HOME = (Path("/Applications/DeepSeek Harness.app") if sys.platform == "darwin"
                        else Path(r"E:\DeepSeekHarness-win32-x64-0.1.1-rc.1"))
DEFAULT_HARNESS_DATA_HOME = (Path.home() / "Documents" / "DeepSeekHarness-GPT" if sys.platform == "darwin"
                             else Path(r"E:\DeepSeekHarness-GPT"))
HARNESS_MODELS = (
    "deepseek-v4-flash",
    "deepseek-v4-pro",
    "deepseek-v4-flash-vision-exp",
)
HarnessModel = Literal[
    "deepseek-v4-flash",
    "deepseek-v4-pro",
    "deepseek-v4-flash-vision-exp",
]
HARNESS_REASONING_EFFORTS = ("off", "low", "high", "max")
HarnessReasoningEffort = Literal["off", "low", "high", "max"]
MAX_TASK_CHARS = 40_000
MAX_OUTPUT_CHARS = 30_000
MIN_TIMEOUT_SECONDS = 60
MAX_TIMEOUT_SECONDS = 3_600


@dataclass(frozen=True)
class HarnessLayout:
    install_home: Path
    data_home: Path
    node: Path
    cli: Path

    @classmethod
    def from_env(cls) -> "HarnessLayout":
        install_home = Path(
            os.environ.get("DEEPSEEK_HARNESS_HOME", str(DEFAULT_HARNESS_HOME))
        ).expanduser().resolve()
        data_home = Path(
            os.environ.get("DEEPSEEK_HARNESS_DATA_HOME", str(DEFAULT_HARNESS_DATA_HOME))
        ).expanduser().resolve()
        mac_bundle = install_home.suffix.lower() == ".app"
        default_node = (install_home / "Contents" / "MacOS" / "DeepSeek Harness" if mac_bundle
                        else install_home / "resources" / "runtime" / "node.exe")
        default_cli = (install_home / "Contents" / "Resources" / "app.asar" / "dsh" / "node_modules"
                       / "@deepseek-ai" / "dsh-desktop-host" / "lib" / "cli.js" if mac_bundle
                       else install_home / "resources" / "runtime" / "node_modules"
                       / "@deepseek-ai" / "dsh" / "lib" / "bin.js")
        node = Path(
            os.environ.get(
                "DEEPSEEK_HARNESS_NODE",
                str(default_node),
            )
        ).expanduser().resolve()
        cli = Path(
            os.environ.get(
                "DEEPSEEK_HARNESS_CLI",
                str(default_cli),
            )
        ).expanduser().resolve()
        return cls(install_home=install_home, data_home=data_home, node=node, cli=cli)

    @property
    def is_mac_bundle(self) -> bool:
        return self.install_home.suffix.lower() == ".app"

    def node_command(self, *args: str) -> list[str]:
        return [str(self.node), *(["--expose-internals"] if self.is_mac_bundle else []), *args]

    def runtime_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["DSH_HOME"] = str(self.data_home)
        if self.is_mac_bundle:
            env["ELECTRON_RUN_AS_NODE"] = "1"
            env["DSH_DESKTOP_NODE_EXECUTABLE"] = str(self.node)
            support = self.install_home / "Contents" / "Resources" / "runtime" / "bin"
            env["PATH"] = str(support) + os.pathsep + env.get("PATH", "")
        return env

    def validate(self) -> None:
        required = (
            self.install_home,
            self.data_home,
            self.node,
            self.cli,
            self.data_home / "profiles" / "headless" / "package.json",
        )
        missing = [str(path) for path in required if not path.exists() and not
                   (path == self.cli and self.is_mac_bundle and
                    (self.install_home / "Contents" / "Resources" / "app.asar").is_file())]
        if missing:
            raise RuntimeError("DeepSeek Harness is incomplete or not configured: " + ", ".join(missing))
        if self.install_home == self.data_home:
            raise RuntimeError(
                "DEEPSEEK_HARNESS_DATA_HOME must be separate from the desktop Harness installation"
            )


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def validate_workspace(
    raw_workspace: str,
    *,
    harness_home: Path,
    data_home: Path,
    plugin_root: Path,
) -> Path:
    text = raw_workspace.strip()
    if not text:
        raise ValueError("workspace must not be empty")
    workspace = Path(text).expanduser().resolve()
    if not workspace.is_dir():
        raise ValueError(f"workspace is not an existing directory: {workspace}")
    if workspace == Path(workspace.anchor):
        raise ValueError("a drive or filesystem root cannot be used as the workspace")
    if workspace == Path.home().resolve():
        raise ValueError("the user home directory cannot be used as the workspace")
    if _is_relative_to(workspace, harness_home.resolve()):
        raise ValueError("the Harness installation cannot be used as the target workspace")
    if _is_relative_to(workspace, data_home.resolve()):
        raise ValueError("the isolated Harness data directory cannot be used as the target workspace")
    if _is_relative_to(workspace, plugin_root.resolve()):
        raise ValueError("the running MCP plugin cannot modify itself")

    allowed = [
        item.strip()
        for item in os.environ.get("DEEPSEEK_HARNESS_ALLOWED_ROOTS", "").split(os.pathsep)
        if item.strip()
    ]
    if allowed:
        allowed_roots = [Path(item).expanduser().resolve() for item in allowed]
        if not any(_is_relative_to(workspace, root) for root in allowed_roots):
            raise ValueError(
                "workspace is outside DEEPSEEK_HARNESS_ALLOWED_ROOTS: "
                + ", ".join(str(root) for root in allowed_roots)
            )
    return workspace


def build_task(task: str) -> str:
    task = task.strip()
    if not task:
        raise ValueError("task must not be empty")
    if len(task) > MAX_TASK_CHARS:
        raise ValueError(f"task exceeds the {MAX_TASK_CHARS:,}-character limit")
    return (
        "Work only inside the current workspace. Inspect the repository before changing it. "
        "Implement the following task with the smallest coherent change, preserve unrelated user work, "
        "and run relevant tests or checks. Do not commit, push, rewrite Git history, delete broad paths, "
        "or access credentials. If a required action is blocked by the workspace sandbox, report it instead "
        "of bypassing the boundary. End with a concise summary of changed files, checks run, and remaining risks.\n\n"
        f"TASK:\n{task}"
    )


def _normalize_model(model: str) -> str:
    selected = model.strip() or HARNESS_MODELS[0]
    if selected not in HARNESS_MODELS:
        raise ValueError("model must be one of: " + ", ".join(HARNESS_MODELS))
    return selected


def _normalize_reasoning_effort(reasoning_effort: str) -> str:
    selected = reasoning_effort.strip() or "max"
    if selected not in HARNESS_REASONING_EFFORTS:
        raise ValueError(
            "reasoning_effort must be one of: " + ", ".join(HARNESS_REASONING_EFFORTS)
        )
    return selected


@contextmanager
def model_override(
    layout: HarnessLayout,
    model: str,
    reasoning_effort: str = "max",
) -> Iterator[tuple[str, str, Path]]:
    """Create a task-local settings document and Cordis patch, then clean both up."""
    selected = _normalize_model(model)
    selected_effort = _normalize_reasoning_effort(reasoning_effort)
    source = layout.data_home / "settings.yaml"
    runtime_dir = layout.data_home / ".mcp-runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    nonce = uuid.uuid4().hex
    settings_path = runtime_dir / f"settings-{nonce}.json"
    patch_path = runtime_dir / f"patch-{nonce}.yaml"
    try:
        plugin_root = Path(__file__).resolve().parents[2]
        helper = plugin_root / "scripts" / "model-settings.mjs"
        completed = subprocess.run(
            layout.node_command(
                str(helper),
                str(source),
                str(settings_path),
                selected,
                selected_effort,
                str(layout.install_home),
            ),
            cwd=plugin_root,
            env=layout.runtime_env(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError("could not prepare task-local Harness settings: " + completed.stderr.strip())
        patch = [{"id": "settings", "config": {"path": str(settings_path), "watch": False}}]
        patch_path.write_text(json.dumps(patch, ensure_ascii=False, indent=2), encoding="utf-8")
        yield selected, selected_effort, patch_path
    finally:
        patch_path.unlink(missing_ok=True)
        settings_path.unlink(missing_ok=True)


def _clip(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    head = limit * 3 // 4
    tail = limit - head
    return f"{text[:head]}\n\n...[output clipped by MCP bridge]...\n\n{text[-tail:]}"


async def _run_capture(args: list[str], cwd: Path, env: dict[str, str], timeout: int) -> tuple[int, str, str]:
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(cwd),
        env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        creationflags=creationflags,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.terminate()
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)
        except TimeoutError:
            process.kill()
            stdout, stderr = await process.communicate()
        raise RuntimeError(
            f"DeepSeek Harness exceeded the {timeout}-second limit. Partial output: "
            + _clip((stdout + stderr).decode("utf-8", errors="replace"), 4_000)
        )
    return (
        int(process.returncode or 0),
        stdout.decode("utf-8", errors="replace").strip(),
        stderr.decode("utf-8", errors="replace").strip(),
    )


async def _git_summary(workspace: Path) -> dict[str, str | bool]:
    async def command(*args: str) -> tuple[int, str, str]:
        env = os.environ.copy()
        env["GIT_OPTIONAL_LOCKS"] = "0"
        return await _run_capture(["git", *args], workspace, env, 20)

    try:
        code, root, _ = await command("rev-parse", "--show-toplevel")
    except (FileNotFoundError, RuntimeError):
        return {"is_git_repository": False}
    if code != 0:
        return {"is_git_repository": False}
    _, status, _ = await command("status", "--short", "--untracked-files=all")
    _, stat, _ = await command("diff", "--stat", "--")
    return {
        "is_git_repository": True,
        "repository_root": root.strip(),
        "status": _clip(status, 12_000),
        "diff_stat": _clip(stat, 8_000),
    }


_workspace_locks: dict[str, asyncio.Lock] = {}


async def run_harness(
    workspace: str,
    task: str,
    timeout_seconds: int = 1_800,
    model: HarnessModel = "deepseek-v4-flash",
    reasoning_effort: HarnessReasoningEffort = "max",
) -> dict[str, Any]:
    if not MIN_TIMEOUT_SECONDS <= timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise ValueError(
            f"timeout_seconds must be between {MIN_TIMEOUT_SECONDS} and {MAX_TIMEOUT_SECONDS}"
        )
    layout = HarnessLayout.from_env()
    layout.validate()
    plugin_root = Path(__file__).resolve().parents[2]
    target = validate_workspace(
        workspace,
        harness_home=layout.install_home,
        data_home=layout.data_home,
        plugin_root=plugin_root,
    )
    prompt = build_task(task)
    lock = _workspace_locks.setdefault(os.path.normcase(str(target)), asyncio.Lock())

    async with lock:
        before = await _git_summary(target)
        env = layout.runtime_env()
        env.update(
            {
                "DSH_HOME": str(layout.data_home),
                "DSH_PERMISSION_MODE": "workspace-write",
                "DSH_TELEMETRY_DISABLED": "1",
                "NO_COLOR": "1",
            }
        )
        started = time.monotonic()
        with model_override(layout, model, reasoning_effort) as (
            selected_model,
            selected_effort,
            patch_path,
        ):
            code, stdout, stderr = await _run_capture(
                layout.node_command(
                    str(layout.cli),
                    "--profile",
                    "headless",
                    "--patch",
                    str(patch_path),
                    prompt,
                ),
                target,
                env,
                timeout_seconds,
            )
        duration = round(time.monotonic() - started, 2)
        after = await _git_summary(target)
        result: dict[str, Any] = {
            "ok": code == 0,
            "exit_code": code,
            "duration_seconds": duration,
            "workspace": str(target),
            "model": selected_model,
            "reasoning_effort": selected_effort,
            "data_home": str(layout.data_home),
            "assistant_result": _clip(stdout),
            "git_before": before,
            "git_after": after,
        }
        if stderr:
            result["diagnostics"] = _clip(stderr, 8_000)
        if code != 0:
            raise RuntimeError(f"DeepSeek Harness exited with code {code}: {result}")
        return result
