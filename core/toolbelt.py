"""Jarvis_60 toolbelt — solved tasks become permanent, reusable tools."""
import os, json, re

TOOLS_DIR = os.path.join(os.path.dirname(__file__), "..", "tools")
REGISTRY = os.path.join(TOOLS_DIR, "registry.json")

def _load_registry() -> dict:
    if os.path.exists(REGISTRY):
        with open(REGISTRY) as f:
            return json.load(f)
    return {}

def save_tool(name: str, task: str, code: str, attempts: int) -> str:
    """Store passing code as a permanent tool + registry entry."""
    name = re.sub(r"[^a-z0-9_]", "", name.lower().replace(" ", "_"))[:40]
    path = os.path.join(TOOLS_DIR, f"{name}.py")
    with open(path, "w") as f:
        f.write(f'"""Tool: {name}\nTask: {task}\nBorn after {attempts} attempt(s)."""\n\n{code}\n')
    registry = _load_registry()
    registry[name] = {"task": task, "file": f"{name}.py", "attempts": attempts}
    with open(REGISTRY, "w") as f:
        json.dump(registry, f, indent=2)
    return path

def list_tools() -> dict:
    return _load_registry()

if __name__ == "__main__":
    print("Current toolbelt:", json.dumps(list_tools(), indent=2))
