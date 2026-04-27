import csv
import sys
from pathlib import Path

if len(sys.argv) < 2:
    print("Usage: python check_corridor_score.py logs_recomputed\\your_file.csv")
    sys.exit(1)

log_path = Path(sys.argv[1])

with log_path.open(newline="", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

started = [r for r in rows if r.get("scenario_started") == "1"]
in_c = [
    int(r["speed_in_corridor"])
    for r in started
    if r.get("speed_in_corridor") not in ("", "None", None)
]

corridor_pct = (sum(in_c) / len(in_c) * 100) if in_c else 0.0

print(f"file={log_path.name}")
print(f"n={len(started)} rows")
print(f"corridor={corridor_pct:.0f}%")
