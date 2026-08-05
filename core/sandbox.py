"""Jarvis_60 sandbox — runs untrusted code safely, returns a fitness verdict."""
import subprocess, tempfile, os, textwrap

SANDBOX_DIR = os.path.join(os.path.dirname(__file__), "..", "sandbox")

def run_code(code: str, timeout: int = 10) -> dict:
    """Run Python code in isolation. Returns {passed, stdout, stderr}."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", dir=SANDBOX_DIR, delete=False
    ) as f:
        f.write(code)
        path = f.name
    try:
        result = subprocess.run(
            ["python3", path],
            capture_output=True, text=True, timeout=timeout,
            cwd=SANDBOX_DIR,
        )
        return {
            "passed": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except subprocess.TimeoutExpired:
        return {"passed": False, "stdout": "", "stderr": f"TIMEOUT after {timeout}s"}
    finally:
        os.remove(path)

if __name__ == "__main__":
    good = run_code("print(2 + 2)")
    bad = run_code("print(undefined_variable)")
    loop = run_code("while True: pass", timeout=3)
    print("good code :", good)
    print("bad code  :", bad)
    print("infinite  :", loop)
