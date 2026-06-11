from pathlib import Path
import re

HTML_FILE = Path("runemetrics_Bepsmum_Archaeology.html")

text = HTML_FILE.read_text(encoding="utf-8", errors="replace")

print(f"Characters: {len(text):,}")
print()

terms = [
    "Bepsmum",
    "Archaeology",
    "xp-monthly",
    "monthly",
    "XP",
    "chart",
    "data",
    "series",
    "error",
    "not found",
]

for term in terms:
    count = len(re.findall(re.escape(term), text, flags=re.IGNORECASE))
    print(f"{term}: {count}")

print()
print("Likely script/data snippets:")
for match in re.finditer(r".{0,80}(Bepsmum|Archaeology|xp-monthly|series|data|chart).{0,120}", text, flags=re.IGNORECASE):
    print("-" * 80)
    print(match.group(0))