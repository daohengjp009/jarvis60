"""Tool: text_file_analyzer
Task: Write a function analyze_text(path) that reads a text file and returns a dict: {'lines': int, 'words': int, 'top5': list of the 5 most common words (lowercased)}.
Born after 1 attempt(s)."""

from collections import Counter
import re

def analyze_text(path):
    with open(path, 'r') as f:
        content = f.read()
    
    lines = content.splitlines()
    num_lines = len(lines)
    
    words = re.findall(r'\b\w+\b', content.lower())
    num_words = len(words)
    
    counter = Counter(words)
    top5 = [word for word, count in counter.most_common(5)]
    
    return {'lines': num_lines, 'words': num_words, 'top5': top5}
