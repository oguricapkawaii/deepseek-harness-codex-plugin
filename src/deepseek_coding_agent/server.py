"""DeepSeek MCP tools for Harness automation and bounded review."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from .client import DeepSeekClient
from .harness import DEFAULT_MODEL, HarnessModel, HarnessReasoningEffort, list_models, run_harness
from .history import export_history, list_history
from .prompts import code_messages, fix_messages, require_text, review_messages

mcp = MCPServer(
    "deepseek-coding-agent",
    instructions=(
        "Use harness_run for approved end-to-end coding work in one explicit workspace. "
        "Harness runs with its workspace-write sandbox and may edit files or run tests there. "
        "The remaining DeepSeek tools are text-only and read only the text supplied to them."
    ),
)

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=False)
MUTATING = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False)


@mcp.tool(annotations=MUTATING)
async def harness_run(
    workspace: str,
    task: str,
    timeout_seconds: int = 1800,
    model: HarnessModel = DEFAULT_MODEL,
    reasoning_effort: HarnessReasoningEffort = "max",
    session_id: str = "",
) -> dict[str, Any]:
    """Run an isolated task; set session_id to resume it in the same workspace. Use harness_models for model ids. Returns session id, request selection and root-step usage."""
    return await run_harness(workspace, task, timeout_seconds, model, reasoning_effort, session_id)


@mcp.tool(annotations=READ_ONLY)
async def harness_models() -> dict[str, Any]:
    """Read the installed Harness version and advisory model catalog without a model request or credentials."""
    return await list_models()


@mcp.tool(annotations=READ_ONLY)
async def harness_history_list(limit: int = 20, workspace: str = "") -> dict[str, Any]:
    """List isolated GPT Harness sessions without returning conversation contents."""
    return await list_history(limit, workspace)


@mcp.tool(annotations=READ_ONLY)
async def harness_history_export(session_id: str, max_chars: int = 30_000) -> dict[str, Any]:
    """Export one isolated GPT Harness session as readable Markdown without modifying it."""
    return await export_history(session_id, max_chars)


async def _complete(messages: list[dict[str, str]], model: str, thinking: bool, max_tokens: int | None, reasoning_effort: str) -> dict[str, Any]:
    return await DeepSeekClient().complete(messages, model=model, thinking=thinking, max_tokens=max_tokens, reasoning_effort=reasoning_effort)


@mcp.tool(annotations=READ_ONLY)
async def deepseek_ask(
    prompt: str,
    system_prompt: str = "You are a precise software engineering assistant.",
    model: str = "",
    thinking: bool = True,
    max_tokens: int | None = None,
    reasoning_effort: str = "",
) -> dict[str, Any]:
    """Ask a bounded software-engineering question; sends only the supplied text to DeepSeek."""
    prompt = require_text("prompt", prompt)
    system_prompt = require_text("system_prompt", system_prompt)
    return await _complete(
        [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
        model,
        thinking,
        max_tokens,
        reasoning_effort,
    )


@mcp.tool(annotations=READ_ONLY)
async def deepseek_code(
    task: str,
    context: str = "",
    constraints: str = "",
    model: str = "",
    thinking: bool = True,
    max_tokens: int | None = None,
    reasoning_effort: str = "",
) -> dict[str, Any]:
    """Generate a code or patch proposal without reading or modifying local files."""
    return await _complete(code_messages(task, context, constraints), model, thinking, max_tokens, reasoning_effort)


@mcp.tool(annotations=READ_ONLY)
async def deepseek_review(
    code_or_diff: str,
    focus: str = "",
    model: str = "",
    thinking: bool = True,
    max_tokens: int | None = None,
    reasoning_effort: str = "",
) -> dict[str, Any]:
    """Review explicitly supplied code or a diff; never opens project files itself."""
    return await _complete(review_messages(code_or_diff, focus), model, thinking, max_tokens, reasoning_effort)


@mcp.tool(annotations=READ_ONLY)
async def deepseek_fix(
    task: str,
    review: str,
    code_or_diff: str,
    model: str = "",
    thinking: bool = True,
    max_tokens: int | None = None,
    reasoning_effort: str = "",
) -> dict[str, Any]:
    """Propose one focused revision from an explicit task, review, and code/diff."""
    return await _complete(fix_messages(task, review, code_or_diff), model, thinking, max_tokens, reasoning_effort)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
