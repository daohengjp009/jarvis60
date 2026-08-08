"""Jarvis_60 — dispatch: reuse > compose > solve from scratch."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from core.brain import think
from core.dispatcher import find_tool, find_components
from core.examiner import write_test
from core.evolve import solve
from core.composer import compose
from core.toolbelt import save_tool, list_tools
from core.executor import execute

def _name_and_save(task, code, attempts, composed_from=None):
    name = think(
        f"Suggest a short snake_case name (max 3 words) for a tool that does: {task}. "
        "Reply with ONLY the name."
    )
    path = save_tool(name, task, code, attempts)
    tool_name = os.path.basename(path)[:-3]
    if composed_from:
        import json
        reg_path = os.path.join(os.path.dirname(__file__), "tools", "registry.json")
        with open(reg_path) as f: reg = json.load(f)
        reg[tool_name]["composed_from"] = composed_from
        with open(reg_path, "w") as f: json.dump(reg, f, indent=2)
    return tool_name

def do(task: str):
    print(f"TASK: {task}\n[dispatch] exact match?")
    owned = find_tool(task)
    if owned:
        print(f"[reuse] running owned tool '{owned}'...")
        execute(owned, task)
        return
    parts = find_components(task)
    exam = write_test(task)
    if not exam["ok"]:
        print("Examiner failed to produce a valid test. Aborted.")
        return
    if len(parts) >= 1:
        print(f"[compose] using owned pieces: {parts}")
        result = compose(task, parts, exam["test"])
        if result["solved"]:
            tool_name = _name_and_save(task, result["code"], result["attempts"], composed_from=parts)
            print(f"[earned-by-composition] '{tool_name}' | toolbelt: {len(list_tools())}")
            execute(tool_name, task)
            return
        print("[compose] failed — falling back to scratch.")
    print("[solve] from scratch.")
    result = solve(task, exam["test"])
    if not result["solved"]:
        print("FAILED after", result["attempts"], "attempts. Nothing saved.")
        return
    tool_name = _name_and_save(task, result["code"], result["attempts"])
    print(f"[earned] '{tool_name}' | toolbelt: {len(list_tools())}")
    execute(tool_name, task)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python3 jarvis.py "your task here"')
    else:
        do(" ".join(sys.argv[1:]))
