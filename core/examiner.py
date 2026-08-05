"""Jarvis_60 examiner — writes tests, with anti-weak-test AND anti-broken-test validation.
A test is accepted only if a do-nothing stub fails it with AssertionError specifically:
- stub passes  -> test too weak, rejected
- stub dies of ImportError/TypeError/etc -> test itself broken, rejected"""
import sys, os, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.brain import think
from core.sandbox import run_code

EXAMINER_SYSTEM = (
    "You are Jarvis_60's examiner. Given a task, you write a rigorous Python test.\n"
    "Rules:\n"
    "- First line must be a comment: # FUNCTION: <name(signature)> defining what the solver must implement.\n"
    "- The function will be defined IN THE SAME FILE above your test. Do NOT import it. "
    "No 'from solution import ...' — just call the function directly.\n"
    "- Call it with concrete inputs and assert exact expected outputs.\n"
    "- Cover normal case + at least one edge case.\n"
    "- Only assertions may fail; the test must not raise any other error type. "
    "Beware: the stub returns None — compare with ==, never subscript/iterate the result "
    "outside an assertion.\n"
    "- Use only Python stdlib. Create any needed files yourself and clean them up.\n"
    "- Reply with ONLY raw Python code, no markdown fences."
)

def _stub_from_test(test_code: str) -> str:
    m = re.search(r"#\s*FUNCTION:\s*(\w+)", test_code)
    fname = m.group(1) if m else "solution"
    return f"def {fname}(*args, **kwargs):\n    return None\n"

def write_test(task: str, max_attempts: int = 3) -> dict:
    prompt = f"Task the solver must implement: {task}\nWrite the test."
    for attempt in range(1, max_attempts + 1):
        test = think(prompt, system=EXAMINER_SYSTEM)
        test = test.replace("```python", "").replace("```", "").strip()
        stub_run = run_code(_stub_from_test(test) + "\n" + test + "\nprint('STUB_SURVIVED')\n")
        stub_passed = stub_run["passed"] and "STUB_SURVIVED" in stub_run["stdout"]
        died_of_assertion = "AssertionError" in stub_run["stderr"]
        if not stub_passed and died_of_assertion:
            return {"ok": True, "test": test, "attempts": attempt}
        if stub_passed:
            reason = "a do-nothing stub PASSED your test — too weak. Stricter concrete assertions."
            print(f"--- examiner attempt {attempt}: WEAK TEST rejected")
        else:
            reason = (f"your test crashed with a non-assertion error, so it is broken:\n"
                      f"{stub_run['stderr']}\nOnly AssertionError may occur. "
                      "Remember: no imports of the solution; the stub returns None.")
            print(f"--- examiner attempt {attempt}: BROKEN TEST rejected")
        prompt = f"Task: {task}\nYour previous test:\n{test}\n\nPROBLEM: {reason}\nRewrite the test."
    return {"ok": False, "attempts": max_attempts}

if __name__ == "__main__":
    r = write_test("Write a function is_palindrome(s) that ignores case and spaces.")
    print("Examiner ok:", r["ok"], "| attempts:", r["attempts"])
    if r["ok"]:
        print(r["test"][:400])
