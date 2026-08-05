"""Jarvis_60 evolution loop v1 — fitness = passing a real test, not exit code."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.brain import think
from core.sandbox import run_code

SYSTEM = (
    "You are Jarvis_60's code generator. Reply with ONLY raw Python code. "
    "No markdown fences, no explanation."
)

def solve(task: str, test_code: str = "", max_attempts: int = 4) -> dict:
    """test_code: appended after the solution; must raise AssertionError if wrong."""
    prompt = (
        f"Task: {task}\n"
        "Write your solution as a FUNCTION so it can be tested. "
        "After the function, this test will run against it:\n"
        f"{test_code if test_code else '(no test provided — code must demonstrate the task on its own)'}"
    )
    for attempt in range(1, max_attempts + 1):
        code = think(prompt, system=SYSTEM)
        code = code.replace("```python", "").replace("```", "").strip()
        full = code + "\n\n" + test_code + "\nprint('ALL_TESTS_PASSED')\n"
        verdict = run_code(full)
        real_pass = verdict["passed"] and "ALL_TESTS_PASSED" in verdict["stdout"]
        print(f"--- attempt {attempt}: {'PASS' if real_pass else 'FAIL'}")
        if real_pass:
            return {"solved": True, "attempts": attempt,
                    "code": code, "output": verdict["stdout"]}
        prompt = (
            f"Task: {task}\n\nYour previous code:\n{code}\n\n"
            f"It FAILED. stderr:\n{verdict['stderr']}\nstdout:\n{verdict['stdout']}\n\n"
            f"The test that must pass:\n{test_code}\n\n"
            "Fix it. Reply with ONLY the corrected Python code."
        )
    return {"solved": False, "attempts": max_attempts}
