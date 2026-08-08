"""Jarvis_60 executor — run an owned tool with real input, behind a permission wall.
Trust Ladder rung 1: everything runs sandboxed; risky capabilities need explicit y/n."""
import sys, os, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.brain import think
from core.sandbox import run_code
from core.toolbelt import list_tools

TOOLS_DIR = os.path.join(os.path.dirname(__file__), "..", "tools")

# Capabilities that require explicit human permission before running
RISKY_PATTERNS = {
    "network":        r"\b(requests|urllib|socket|http\.client|ftplib)\b",
    "system_command": r"\b(subprocess|os\.system|os\.popen|shutil\.rmtree)\b",
    "file_write":     r"\bopen\([^)]*['\"](w|a|x)",
    "outside_paths":  r"(/Users/|~|os\.path\.expanduser|/etc/|/var/)",
}

def safety_scan(code: str) -> list[str]:
    return [name for name, pat in RISKY_PATTERNS.items() if re.search(pat, code)]

def execute(tool_name: str, task: str) -> None:
    info = list_tools().get(tool_name)
    if not info:
        print(f"No such tool: {tool_name}")
        return
    with open(os.path.join(TOOLS_DIR, info["file"])) as f:
        tool_code = f.read()

    check = think(
        f"Tool code:\n{tool_code}\n\nUser request: {task}\n\n"
        "Does the request contain ALL concrete input values needed to actually run "
        "the tool (real file paths, real numbers, real strings)? Reply ONLY YES or "
        "ONLY the word MISSING followed by what is missing.",
        system="You are Jarvis_60's executor. Terse answers.",
    ).strip()
    if check.upper().startswith("MISSING"):
        print(f"NEED INPUT — {check[7:].strip() or 'concrete input values required.'}")
        print("Re-run with the actual values in your request.")
        return

    call_line = think(
        f"Tool code:\n{tool_code}\n\nUser request: {task}\n\n"
        "Write ONLY the Python line(s) that call the tool's function with the "
        "concrete input from the user request and print the result. No fences. "
        "IMPORTANT: the code runs with working directory = the project's sandbox/ dir. "
        "The project root is /Users/leolo/jarvis60. If the user gives a relative path "
        "(e.g. sandbox/demo.txt or memory/x.json), convert it to an absolute path "
        "under the project root.",
        system="You are Jarvis_60's executor. Minimal code, only the call and print.",
    ).replace("```python", "").replace("```", "").strip()

    full = tool_code + "\n\n" + call_line
    risks = safety_scan(full)
    if risks:
        print(f"PERMISSION NEEDED — this run uses: {', '.join(risks)}")
        if input("Allow? [y/N] ").strip().lower() != "y":
            print("Denied. Nothing was run.")
            return

    verdict = run_code(full)
    if verdict["passed"]:
        print("RESULT:", verdict["stdout"])
    else:
        print("Tool run failed:\n", verdict["stderr"])
