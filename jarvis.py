"""Jarvis_60 — dispatcher-first pipeline: reuse before re-solving."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from core.brain import think
from core.dispatcher import find_tool
from core.examiner import write_test
from core.evolve import solve
from core.toolbelt import save_tool, list_tools

def do(task: str):
    print(f"TASK: {task}\n[0/3] Dispatcher checking toolbelt...")
    owned = find_tool(task)
    if owned:
        print(f"REUSE: already own '{owned}' — no solving needed. (tools/{owned}.py)")
        return
    print("      no matching tool — solving from scratch.")
    print("[1/3] Examiner writing test...")
    exam = write_test(task)
    if not exam["ok"]:
        print("Examiner could not produce a valid test. Task aborted.")
        return
    print(f"      test accepted (attempt {exam['attempts']})")
    print("[2/3] Solver working...")
    result = solve(task, exam["test"])
    if not result["solved"]:
        print("FAILED after", result["attempts"], "attempts. Nothing saved.")
        return
    print("[3/3] Saving tool...")
    name = think(
        f"Suggest a short snake_case name (max 3 words) for a tool that does: {task}. "
        "Reply with ONLY the name."
    )
    path = save_tool(name, task, result["code"], result["attempts"])
    print(f"DONE. Tool saved: {os.path.basename(path)} | toolbelt size: {len(list_tools())}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python3 jarvis.py "your task here"')
    else:
        do(" ".join(sys.argv[1:]))
