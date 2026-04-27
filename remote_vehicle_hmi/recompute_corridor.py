import csv
import sys
from pathlib import Path

# THE ONE CANONICAL CORRIDOR — fixed for SC01_v2 VIDE
CANONICAL = {
    "start":     (0.0, 0.1),
    "accel_1":   (0.1, 1.3),
    "accel_2":   (1.1, 3.3),
    "stabilize": (3.5, 5.1),
    "hold":      (4.2, 5.1),
    "end":       (0.0, 5.0),
}

def recompute(input_path: Path, output_path: Path) -> None:
    with input_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print(f"[SKIP] Empty file: {input_path.name}")
        return

    fieldnames = list(rows[0].keys())

    # Make sure the needed columns exist
    required_new_cols = [
        "speed_min_mps",
        "speed_max_mps",
        "speed_in_corridor",
        "e_speed_low",
        "e_speed_high",
    ]
    for col in required_new_cols:
        if col not in fieldnames:
            fieldnames.append(col)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for row in rows:
            phase = str(row.get("phase", "")).strip()

            if phase in CANONICAL:
                vmin, vmax = CANONICAL[phase]
                try:
                    speed = float(row.get("speed_mps", 0) or 0)
                except ValueError:
                    speed = 0.0

                row["speed_min_mps"] = vmin
                row["speed_max_mps"] = vmax
                row["speed_in_corridor"] = 1 if (vmin <= speed <= vmax) else 0
                row["e_speed_low"] = round(speed - vmin, 5)
                row["e_speed_high"] = round(vmax - speed, 5)

            writer.writerow(row)

def main():
    # Usage:
    #   python recompute_corridor.py
    # or
    #   python recompute_corridor.py logs logs_recomputed
    in_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("logs")
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("logs_recomputed")

    out_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(in_dir.glob("S*_SC01.csv"))
    if not files:
        print(f"No matching files found in: {in_dir.resolve()}")
        return

    for p in files:
        out_path = out_dir / p.name
        recompute(p, out_path)
        print(f"Recomputed: {p.name}")

    print(f"\nDone. Output folder: {out_dir.resolve()}")

if __name__ == "__main__":
    main()
