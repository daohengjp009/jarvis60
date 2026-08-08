"""Jarvis_60 dispatcher v2 — exact reuse first, then component detection."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.brain import think
from core.toolbelt import list_tools

def _catalog() -> str:
    return "\n".join(f"- {n}: {i['task']}" for n, i in list_tools().items())

def find_tool(task: str) -> str | None:
    """Exact match: one owned tool fully does the task."""
    tools = list_tools()
    if not tools:
        return None
    answer = think(
        f"Owned tools:\n{_catalog()}\n\nNew task: {task}\n\n"
        "If ONE owned tool already fully accomplishes this task, reply with ONLY its exact name. "
        "If none fully matches, reply ONLY NONE.",
        system="You are Jarvis_60's dispatcher. One word answers only.",
    ).strip()
    return answer if answer in tools else None

def find_components(task: str) -> list[str]:
    """Partial match: which owned tools would be USEFUL PARTS of solving this task?"""
    tools = list_tools()
    if len(tools) < 2:
        return []
    answer = think(
        f"Owned tools:\n{_catalog()}\n\nNew task: {task}\n\n"
        "Which owned tools would be genuinely useful as COMPONENTS in solving this task? "
        "Reply with ONLY a JSON list of exact tool names, e.g. [\"tool_a\", \"tool_b\"]. "
        "Empty list [] if none would truly help. Be strict — related is not useful.",
        system="You are Jarvis_60's dispatcher. JSON only.",
    ).strip().replace("```json", "").replace("```", "").strip()
    try:
        names = json.loads(answer)
        return [n for n in names if n in tools]
    except Exception:
        return []
