"""Jarvis_60 re-verification — rot defense.
Every tool's exam is stored beside it; recheck re-runs all exams.
FAIL -> tool marked broken, dispatcher must skip it. No silent rot."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.sandbox import run_code

TOOLS_DIR = os.path.join(os.path.dirname(__file__), "..", "tools")
REGISTRY = os.path.join(TOOLS_DIR, "registry.json")

def recheck_all() -> dict:
    with open(REGISTRY) as f:
        reg = json.load(f)
    report = {}
    for name, info in reg.items():
        exam_file = os.path.join(TOOLS_DIR, f"{name}.exam.py")
        if not os.path.exists(exam_file):
            report[name] = "UNVERIFIED (no stored exam)"
            reg[name]["status"] = "unverified"
            continue
        with open(os.path.join(TOOLS_DIR, info["file"])) as f:
            code = f.read()
        with open(exam_file) as f:
            exam = f.read()
        v = run_code(code + "\n\n" + exam + "\nprint('ALL_TESTS_PASSED')\n")
        ok = v["passed"] and "ALL_TESTS_PASSED" in v["stdout"]
        report[name] = "OK" if ok else "BROKEN"
        reg[name]["status"] = "ok" if ok else "broken"
    with open(REGISTRY, "w") as f:
        json.dump(reg, f, indent=2)
    return report

if __name__ == "__main__":
    for name, status in recheck_all().items():
        print(f"{status:28s} {name}")
