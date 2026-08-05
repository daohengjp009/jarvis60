"""Jarvis_60 evolution loop v0 — generate, test, learn from failure, retry."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.brain import think
from core.sandbox import run_code

SYSTEM = (
    "You are Jarvis_60's code generator. Reply with ONLY raw Python code. "
    "No markdown fences, no explanation. The code must print its result "
    "and exit with code 0 on success."
)

def solve(task: str, max_attempts: int = 4) -> dict:
    prompt = f"Task: {task}"
    for attempt in range(1, max_attempts + 1):
        code = think(prompt, system=SYSTEM)
        code = code.replace("```python", "").replace("```", "").strip()
        verdict = run_code(code)
        print(f"--- attempt {attempt}: {'PASS' if verdict['passed'] else 'FAIL'}")
        if verdict["passed"]:
            return {"solved": True, "attempts": attempt,
                    "code": code, "output": verdict["stdout"]}
        # feed the failure back — this is the learning step
        prompt = (
            f"Task: {task}\n\nYour previous code:\n{code}\n\n"
            f"It FAILED with error:\n{verdict['stderr']}\n\n"
            "Fix it. Reply with ONLY the corrected Python code."
        )
    return {"solved": False, "attempts": max_attempts}

if __name__ == "__main__":
    task = "Compute the 20th Fibonacci number and the sum of primes below 100, print both."
    result = solve(task)
    print()
    print("SOLVED:", result["solved"], "| attempts:", result.get("attempts"))
    if result["solved"]:
        print("OUTPUT:", result["output"])
