from pathlib import Path
import re
text = Path('app.py').read_text(encoding='utf-8').splitlines()
counts = {}
for i, line in enumerate(text, start=1):
    if '@app.route(' in line:
        m = re.search(r'@app\.route\("([^"]+)"', line)
        if m:
            counts.setdefault(m.group(1), []).append(i)
for path, lines in sorted(counts.items()):
    if len(lines) > 1:
        print(f'{path}: lines {lines}')
