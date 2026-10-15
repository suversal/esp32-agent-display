from __future__ import annotations

import re
import unicodedata
from pathlib import PurePosixPath
from typing import Any


def safe_text(value: Any, limit: int = 80) -> str:
    text = str(value) if value is not None else ""
    text = "".join(char for char in text if not unicodedata.category(char).startswith("C"))
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


def redact(text: str) -> str:
    text = re.sub(r"(https?://)[^/\s@]+@", r"\1***@", text, flags=re.I)
    text = re.sub(r"(?i)(authorization\s*[:=]\s*)([^\r\n]+)", r"\1***", text)
    text = re.sub(r"(?i)(bearer\s+)\S+", r"\1***", text)
    text = re.sub(
        r"(?i)((?:--password|-p|--token|--key|--secret)\s+|"
        r"(?:password|token|key|secret)\s*=\s*)(?:\"[^\"]*\"|'[^']*'|[^\s;]+)",
        r"\1***", text,
    )
    text = re.sub(r"(?<![\w])[A-Za-z0-9+/_=-]{20,}(?![\w])", "***", text)
    return text


def summarize(tool: str, arguments: Any, detailed: bool = False) -> str:
    # Local function tools can carry a namespace; MCP names retain their identity.
    tool = re.sub(r"^(?:functions|tools)\.", "", tool)
    args = arguments if isinstance(arguments, dict) else {}
    if tool in {"Bash", "exec_command", "run_shell_command", "shell", "shell_command"}:
        if detailed:
            command = args.get("command", args.get("cmd", ""))
            return safe_text("$ " + redact(str(command).splitlines()[0] if command else ""), 40)
        return "执行命令"
    if tool == "apply_patch":
        patch = args.get("command", args.get("patch", arguments if isinstance(arguments, str) else ""))
        paths = re.findall(r"^\*\*\* (?:Update|Add|Delete) File: (.+)$", str(patch), flags=re.M)
        filename = PurePosixPath(paths[0].replace("\\", "/")).name if paths else ""
        return safe_text(f"编辑 {filename}".strip(), 40)
    if tool in {"Edit", "Write", "MultiEdit", "NotebookEdit", "write_file", "replace"}:
        category = "编辑"
    elif tool in {"Read", "read_file", "read_many_files"}:
        category = "读取"
    else:
        category = ""
    if category:
        path = args.get("file_path", args.get("absolute_path", args.get("path", args.get("notebook_path", ""))))
        filename = PurePosixPath(str(path).replace("\\", "/")).name if path else ""
        return safe_text(f"{category} {filename}".strip(), 40)
    if tool in {"Grep", "Glob", "glob", "grep", "search_file_content"}:
        return "搜索代码"
    if tool in {"WebFetch", "WebSearch", "web_fetch", "google_web_search"}:
        return "访问网页"
    if tool in {"Task", "Agent", "spawn_agent"}:
        return "子任务"
    if tool == "write_stdin":
        return "等待命令结果"
    if tool == "update_plan":
        return "更新计划"
    if tool == "exec":
        return "处理工具任务"
    if tool.startswith(("mcp__", "mcp_")):
        return "MCP 工具"
    return safe_text(tool, 40)
