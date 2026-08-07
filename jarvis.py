"""Jarvis_60 — full loop: dispatch -> (reuse|solve) -> execute -> answer."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from core.brain import think
from core.dispatcher import find_tool
from core.examiner import write_test
from core.evolve import solve
from core.toolbelt import save_tool, list_tools
from core.executor import execute

def do(task: str):
    print(f"TASK: {task}\n[dispatch] checking toolbelt...")
    owned = find_tool(task)
    if owned:
        print(f"[reuse] running owned tool '{owned}'...")
        execute(owned, task)
        return
    print("[solve] no matching tool — earning a new one.")
    exam = write_test(task)
    if not exam["ok"]:
        print("Examiner could not produce a valid test. Task aborted.")
        return
    result = solve(task, exam["test"])
    if not result["solved"]:
        print("FAILED after", result["attempts"], "attempts. Nothing saved.")
        return
    name = think(
        f"Suggest a short snake_case name (max 3 words) for a tool that does: {task}. "
        "Reply with ONLY the name."
    )
    save_tool(name, task, result["code"], result["attempts"])
    tool_name = [n for n in list_tools() if list_tools()[n]["task"] == task][0]
    print(f"[earned] new tool '{tool_name}' | toolbelt size: {len(list_tools())}")
    print("[run] executing it on your input...")
    execute(tool_name, task)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python3 jarvis.py "your task here"')
    else:
        do(" ".join(sys.argv[1:]))
