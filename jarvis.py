"""Jarvis_60 entry point — test-driven task solving with permanent toolbelt."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from core.brain import think
from core.evolve import solve
from core.toolbelt import save_tool, list_tools

def do(task: str, test_code: str = ""):
    result = solve(task, test_code)
    if not result["solved"]:
        print("FAILED after", result["attempts"], "attempts. Nothing saved.")
        return
    name = think(
        f"Suggest a short snake_case name (max 3 words) for a tool that does: {task}. "
        "Reply with ONLY the name."
    )
    path = save_tool(name, task, result["code"], result["attempts"])
    print(f"SOLVED in {result['attempts']} attempt(s). Tool saved: {os.path.basename(path)}")
    print("Toolbelt size:", len(list_tools()))

if __name__ == "__main__":
    from core.tasks import TEXT_TOOL_TASK, TEXT_TOOL_TEST
    do(TEXT_TOOL_TASK, TEXT_TOOL_TEST)
