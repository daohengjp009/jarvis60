"""Task definitions: each task = description + a real test that proves it."""

TEXT_TOOL_TASK = (
    "Write a function analyze_text(path) that reads a text file and returns a dict: "
    "{'lines': int, 'words': int, 'top5': list of the 5 most common words (lowercased)}."
)

TEXT_TOOL_TEST = '''
import os
_p = "_test_sample.txt"
with open(_p, "w") as f:
    f.write("apple banana apple\\ncherry apple banana\\ncherry date egg fig\\n")
r = analyze_text(_p)
os.remove(_p)
assert r["lines"] == 3, f"lines wrong: {r['lines']}"
assert r["words"] == 10, f"words wrong: {r['words']}"
assert r["top5"][0] == "apple", f"top word wrong: {r['top5']}"
assert set(r["top5"][:2]) >= {"apple"}, "ranking wrong"
'''
