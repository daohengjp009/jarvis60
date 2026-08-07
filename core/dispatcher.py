"""Jarvis_60 dispatcher — check owned tools before solving from scratch."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.brain import think
from core.toolbelt import list_tools

def find_tool(task: str) -> str | None:
    """Return the name of an owned tool matching the task, else None."""
    tools = list_tools()
    if not tools:
        return None
    catalog = "\n".join(f"- {name}: {info['task']}" for name, info in tools.items())
    answer = think(
        f"Owned tools:\n{catalog}\n\nNew task: {task}\n\n"
        "If one owned tool already does this task, reply with ONLY its exact name. "
        "If none matches, reply with ONLY the word NONE. "
        "Match strictly: a tool must actually accomplish the task, not just be related.",
        system="You are Jarvis_60's dispatcher. One word answers only.",
    ).strip()
    return answer if answer in tools else None
