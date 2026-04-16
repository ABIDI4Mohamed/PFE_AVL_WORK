"""
scenario_reference.py
─────────────────────
Loads a scenario CSV file and provides step lookup by elapsed time.

CSV columns expected:
    scenario_id     str     e.g. "S001"
    step_id         int     sequential step number
    time_s          float   time since scenario start (seconds)
    steer_ref_deg   float   steering angle target (degrees, +right)
    throttle_ref    float   throttle target 0.0–1.0
    brake_ref       float   brake target 0.0–1.0
    speed_ref_mps   float   speed reference (for AI observer only)
    phase           str     human label, e.g. "accel", "cruise", "brake"

All rows must be sorted by time_s ascending.
"""

import csv
from pathlib import Path
from typing import List, Optional


# ──────────────────────────────────────────────────────────────
#  TYPES
# ──────────────────────────────────────────────────────────────
# A scenario row is a plain dict with string keys → typed values.
ScenarioRow   = dict
ScenarioData  = List[ScenarioRow]

_REQUIRED_COLS = {
    "scenario_id", "step_id", "time_s",
    "steer_ref_deg", "throttle_ref", "brake_ref",
    "speed_ref_mps", "phase",
}


# ──────────────────────────────────────────────────────────────
#  LOADER
# ──────────────────────────────────────────────────────────────
def load_scenario(path: str) -> ScenarioData:
    """
    Load and validate a scenario CSV.

    Returns a list of dicts with numeric fields already cast to float/int.
    Raises ValueError on missing columns.
    Raises FileNotFoundError if path does not exist.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Scenario file not found: {path}")

    rows: ScenarioData = []
    with p.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        # Validate columns
        if reader.fieldnames is None:
            raise ValueError("Scenario CSV is empty or has no header row.")
        missing = _REQUIRED_COLS - set(reader.fieldnames)
        if missing:
            raise ValueError(
                f"Scenario CSV missing required columns: {missing}\n"
                f"Found: {set(reader.fieldnames)}"
            )

        for raw in reader:
            row: ScenarioRow = {
                "scenario_id":   raw["scenario_id"].strip(),
                "step_id":       int(raw["step_id"]),
                "time_s":        float(raw["time_s"]),
                "steer_ref_deg": float(raw["steer_ref_deg"]),
                "throttle_ref":  float(raw["throttle_ref"]),
                "brake_ref":     float(raw["brake_ref"]),
                "speed_ref_mps": float(raw["speed_ref_mps"]),
                "phase":         raw["phase"].strip(),
            }
            # Clamp to valid ranges immediately
            row["throttle_ref"] = max(0.0, min(1.0, row["throttle_ref"]))
            row["brake_ref"]    = max(0.0, min(1.0, row["brake_ref"]))
            rows.append(row)

    if not rows:
        raise ValueError(f"Scenario CSV is empty: {path}")

    # Enforce ascending time order
    rows.sort(key=lambda r: r["time_s"])

    return rows


# ──────────────────────────────────────────────────────────────
#  STEP LOOKUP  (zero-order hold)
# ──────────────────────────────────────────────────────────────
def get_step(scenario_data: ScenarioData, elapsed_s: float) -> Optional[ScenarioRow]:
    """
    Return the active reference row at `elapsed_s` seconds since
    scenario start.  Uses zero-order hold: returns the last row
    whose time_s <= elapsed_s.

    Returns None in two cases:
      - elapsed_s is before the first row (scenario hasn't started)
      - elapsed_s is more than 0.5 s past the last row (scenario is over)

    None signals to the caller that AUTO mode should end.
    """
    if not scenario_data:
        return None

    last_time = scenario_data[-1]["time_s"]

    # Past end of scenario (with grace period)
    if elapsed_s > last_time + 0.5:
        return None

    # Find last row with time_s <= elapsed_s
    active: Optional[ScenarioRow] = None
    for row in scenario_data:
        if row["time_s"] <= elapsed_s:
            active = row
        else:
            break   # sorted ascending — safe early exit

    return active   # may be None if elapsed_s < first row time_s


# ──────────────────────────────────────────────────────────────
#  SCENARIO METADATA
# ──────────────────────────────────────────────────────────────
def get_scenario_id(scenario_data: ScenarioData) -> str:
    if not scenario_data:
        return "UNKNOWN"
    return scenario_data[0]["scenario_id"]


def get_duration(scenario_data: ScenarioData) -> float:
    if not scenario_data:
        return 0.0
    return scenario_data[-1]["time_s"]


def get_phase_at(scenario_data: ScenarioData, elapsed_s: float) -> str:
    step = get_step(scenario_data, elapsed_s)
    if step is None:
        return "DONE"
    return step["phase"]
