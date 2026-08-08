"""Jarvis_60 composer — solve a new task by gluing owned tools together.
The solver receives component code and writes ONLY the connecting logic;
the result faces the same examiner + sandbox as any solution."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.brain import think
from core.sandbox import run_code
from core.toolbelt import list_tools

TOOLS_DIR = os.path.join(os.path.dirname(__file__), "..", "tools")

COMPOSER_SYSTEM = (
    "You are Jarvis_60's composer. You receive existing, already-tested functions "
    "and a task. Write ONLY the new glue code (a new function) that solves the task "
    "by CALLING the provided functions. Do not rewrite or modify them — they will be "
    "present in the same file above your code. Reply with ONLY raw Python, no fences."
)

def compose(task: str, components: list[str], test_code: str, max_attempts: int = 4) -> dict:
    parts = []
    for name in components:
        with open(os.path.join(TOOLS_DIR, list_tools()[name]["file"])) as f:
            parts.append(f.read())
    base = "\n\n".join(parts)
    prompt = (
        f"Existing tested functions:\n{base}\n\nTask: {task}\n"
        f"Your glue code must make this test pass:\n{test_code}"
    )
    for attempt in range(1, max_attempts + 1):
        glue = think(prompt, system=COMPOSER_SYSTEM)
        glue = glue.replace("```python", "").replace("```", "").strip()
        full = base + "\n\n" + glue + "\n\n" + test_code + "\nprint('ALL_TESTS_PASSED')\n"
        verdict = run_code(full)
        ok = verdict["passed"] and "ALL_TESTS_PASSED" in verdict["stdout"]
        print(f"--- compose attempt {attempt}: {'PASS' if ok else 'FAIL'}")
        if ok:
            return {"solved": True, "attempts": attempt, "code": base + "\n\n" + glue}
        prompt = (
            f"Existing functions:\n{base}\n\nTask: {task}\nYour previous glue:\n{glue}\n"
            f"FAILED. stderr:\n{verdict['stderr']}\nstdout:\n{verdict['stdout']}\n"
            f"Test to pass:\n{test_code}\nFix ONLY the glue code."
        )
    return {"solved": False, "attempts": max_attempts}
