"""Safe, bounded launcher for isolated DeepSeek Harness coding runs."""

from __future__ import annotations

import asyncio
import json
import os
import re
import signal
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
DEFAULT_MODEL = "deepseek-flash"
# Model ids evolve independently of this bridge. The installed adapter validates them.
HarnessModel = str
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
    selected = model.strip() or DEFAULT_MODEL
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", selected):
        raise ValueError("model must be a valid model id (up to 200 characters)")
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
    """Override the current profile directly; never rewrite legacy settings or keys."""
    selected = _normalize_model(model)
    selected_effort = _normalize_reasoning_effort(reasoning_effort)
    runtime_dir = layout.data_home / ".mcp-runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    nonce = uuid.uuid4().hex
    patch_path = runtime_dir / f"patch-{nonce}.yaml"
    try:
        patch = [
            {"id": "agent-default-model", "config": {
                "provider": "deepseek-official", "model": selected,
                "reasoningEffort": selected_effort,
            }},
            # 0.2.1 headless disables the credential service by default. Restore it
            # explicitly in the isolated home, without exporting or copying a key.
            {"id": "credentials", "disabled": False},
            # Avoid an extra billed request just to title a one-shot job.
            {"id": "session-title-llm", "disabled": True},
        ]
        with patch_path.open("x", encoding="utf-8") as handle:
            os.chmod(patch_path, 0o600)
            json.dump(patch, handle, ensure_ascii=False, indent=2)
        yield selected, selected_effort, patch_path
    finally:
        patch_path.unlink(missing_ok=True)


async def list_models() -> dict[str, Any]:
    layout = HarnessLayout.from_env()
    layout.validate()
    helper = Path(__file__).resolve().parents[2] / "scripts" / "runtime-info.mjs"
    code, out, err = await _run_capture(
        layout.node_command(str(helper), str(layout.install_home), str(layout.data_home)),
        helper.parent, layout.runtime_env(), 30,
    )
    if code:
        raise RuntimeError("Cannot read installed Harness catalog: " + _clip(err, 2000))
    return json.loads(out)


def parse_run_events(output: str) -> dict[str, Any]:
    """Reduce public headless --json events; don't return tool traffic or thoughts."""
    session_id = None
    final = None
    finish_reason = None
    steps = 0
    samples: list[dict[str, Any]] = []
    errors = []
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Harness returned a non-JSON run event; check runtime compatibility") from exc
        if not isinstance(event, dict):
            raise RuntimeError("Harness returned an invalid run event")
        kind = event.get("type")
        if kind == "session":
            session_id = event.get("sessionId")
        elif kind == "final":
            final = event.get("text", "")
        elif kind == "error":
            errors.append(event.get("message", "Harness error"))
        elif kind == "status":
            if event.get("phase") == "turn_end":
                finish_reason = event.get("reason", {}).get("kind")
            elif event.get("phase") == "step_end":
                steps += 1
                if isinstance(event.get("usage"), dict):
                    samples.append(event["usage"])
    usage: dict[str, int | float] = {}
    # A missing sample is unknown, not zero. Optional buckets are only totaled
    # when every contributing step supplies them.
    if samples:
        for key in ("inputTokens", "outputTokens", "totalTokens", "cacheReadTokens", "cacheWriteTokens", "reasoningTokens"):
            values = [sample.get(key) for sample in samples]
            if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
                usage[key] = sum(values)
    return {
        "session_id": session_id, "assistant_result": _clip(final or ""),
        "finish_reason": finish_reason, "has_final": final is not None,
        "usage": usage or None, "usage_complete": steps > 0 and len(samples) == steps,
        "usage_scope": "root agent steps; excludes auxiliary and subagent requests",
        "errors": errors,
    }


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
        start_new_session=os.name != "nt",
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
        # Terminate the owned process group, including spawned shell workers.
        if os.name == "nt":
            killer = await asyncio.create_subprocess_exec(
                "taskkill", "/PID", str(process.pid), "/T", "/F",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            await killer.wait()
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)
        except asyncio.TimeoutError:
            try:
                if os.name == "nt":
                    process.kill()
                else:
                    os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = await process.communicate()
        if isinstance(exc, asyncio.CancelledError):
            raise
        raise RuntimeError(f"DeepSeek Harness exceeded the {timeout}-second limit; owned workers stopped") from exc
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
    model: HarnessModel = DEFAULT_MODEL,
    reasoning_effort: HarnessReasoningEffort = "max",
    session_id: str = "",
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
    session_id = session_id.strip()
    if session_id and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}", session_id):
        raise ValueError("session_id must be a valid saved session id")
    lock = _workspace_locks.setdefault(os.path.normcase(str(target)), asyncio.Lock())

    async with lock:
        from .history import inspect_history

        if session_id:
            previous = await inspect_history(session_id)
            saved_workspace = previous.get("workspace")
            if not saved_workspace or Path(saved_workspace).resolve() != target:
                raise ValueError("saved session belongs to a different workspace")
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
                    "--json",
                    *(["--session-id", session_id] if session_id else []),
                    "--",
                    prompt,
                ),
                target,
                env,
                timeout_seconds,
            )
        duration = round(time.monotonic() - started, 2)
        after = await _git_summary(target)
        parsed = parse_run_events(stdout)
        saved = None
        history_error = None
        if parsed["session_id"]:
            try:
                saved = await inspect_history(parsed["session_id"])
            except RuntimeError as exc:
                history_error = str(exc)
        result: dict[str, Any] = {
            "ok": code == 0 and parsed["has_final"] and parsed["finish_reason"] == "completed" and not parsed["errors"],
            "exit_code": code,
            "duration_seconds": duration,
            "workspace": str(target),
            "model": selected_model,
            "reasoning_effort": selected_effort,
            "selection_source": "requested; see runtime_selection for dispatched configuration",
            "runtime_selection": saved.get("runtime_selection") if saved else None,
            "model_verification": "persisted Harness request/header; backend deployment version is not independently verified",
            "resumed": bool(session_id),
            "data_home": str(layout.data_home),
            **parsed,
            "git_before": before,
            "git_after": after,
        }
        if stderr:
            result["diagnostics"] = _clip(stderr, 8_000)
        if history_error:
            result["history_error"] = _clip(history_error, 2000)
        # Return a structured failure with the session id so a caller can inspect
        # or resume it. Don't bury the durable identity in an exception string.
        if not result["ok"]:
            result["error"] = "Harness task did not complete; inspect diagnostics and session history"
        return result
