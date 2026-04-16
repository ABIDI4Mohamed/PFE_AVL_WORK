from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List, Optional, Any


class ScenarioReference:
    """
    Load one CSV file containing one or more scenarios and return
    the active reference row at a given time t.

    Expected CSV columns:
        scenario_id
        step_id
        time_s
        steer_ref_deg
        throttle_ref
        brake_ref
        speed_ref_mps
        tol_steer_deg
        tol_throttle
        tol_brake
        tol_speed_mps
        phase
    """

    REQUIRED_COLUMNS = [
        "scenario_id",
        "step_id",
        "time_s",
        "steer_ref_deg",
        "throttle_ref",
        "brake_ref",
        "speed_ref_mps",
        "tol_steer_deg",
        "tol_throttle",
        "tol_brake",
        "tol_speed_mps",
        "phase",
    ]

    FLOAT_COLUMNS = [
        "time_s",
        "steer_ref_deg",
        "throttle_ref",
        "brake_ref",
        "speed_ref_mps",
        "tol_steer_deg",
        "tol_throttle",
        "tol_brake",
        "tol_speed_mps",
    ]

    def __init__(self, csv_path: str | Path) -> None:
        self.csv_path = Path(csv_path)
        self.rows: List[Dict[str, Any]] = []
        self.rows_by_scenario: Dict[str, List[Dict[str, Any]]] = {}

        self._load()

    def _load(self) -> None:
        if not self.csv_path.exists():
            raise FileNotFoundError(f"Scenario CSV not found: {self.csv_path}")

        with self.csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)

            if reader.fieldnames is None:
                raise ValueError("Scenario CSV is empty or has no header.")

            missing = [c for c in self.REQUIRED_COLUMNS if c not in reader.fieldnames]
            if missing:
                raise ValueError(
                    f"Scenario CSV is missing required columns: {missing}"
                )

            loaded_rows: List[Dict[str, Any]] = []
            for line_idx, row in enumerate(reader, start=2):
                cleaned = dict(row)

                for key in self.FLOAT_COLUMNS:
                    try:
                        cleaned[key] = float(cleaned[key])
                    except (TypeError, ValueError):
                        raise ValueError(
                            f"Invalid numeric value for '{key}' at line {line_idx}: {cleaned.get(key)!r}"
                        )

                cleaned["scenario_id"] = str(cleaned["scenario_id"]).strip()
                cleaned["step_id"] = str(cleaned["step_id"]).strip()
                cleaned["phase"] = str(cleaned["phase"]).strip()

                loaded_rows.append(cleaned)

        loaded_rows.sort(key=lambda r: (r["scenario_id"], r["time_s"]))
        self.rows = loaded_rows

        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for row in self.rows:
            grouped.setdefault(row["scenario_id"], []).append(row)

        self.rows_by_scenario = grouped

    def list_scenarios(self) -> List[str]:
        return sorted(self.rows_by_scenario.keys())

    def has_scenario(self, scenario_id: str) -> bool:
        return scenario_id in self.rows_by_scenario

    def get_rows_for_scenario(self, scenario_id: str) -> List[Dict[str, Any]]:
        if scenario_id not in self.rows_by_scenario:
            raise KeyError(f"Unknown scenario_id: {scenario_id}")
        return self.rows_by_scenario[scenario_id]

    def get_reference_at_time(self, scenario_id: str, t_s: float) -> Optional[Dict[str, Any]]:
        """
        Zero-order hold:
        returns the last row whose time_s <= t_s.
        If t_s is before the first row, returns the first row.
        If scenario does not exist, raises KeyError.
        """
        rows = self.get_rows_for_scenario(scenario_id)
        if not rows:
            return None

        if t_s <= rows[0]["time_s"]:
            return rows[0]

        current = rows[0]
        for row in rows:
            if row["time_s"] <= t_s:
                current = row
            else:
                break
        return current

    def get_next_reference_after(self, scenario_id: str, t_s: float) -> Optional[Dict[str, Any]]:
        rows = self.get_rows_for_scenario(scenario_id)
        for row in rows:
            if row["time_s"] > t_s:
                return row
        return None

    def get_phase_at_time(self, scenario_id: str, t_s: float) -> Optional[str]:
        ref = self.get_reference_at_time(scenario_id, t_s)
        if ref is None:
            return None
        return str(ref["phase"])

    def get_duration(self, scenario_id: str) -> float:
        rows = self.get_rows_for_scenario(scenario_id)
        if not rows:
            return 0.0
        return float(rows[-1]["time_s"])

    def as_dict(self) -> Dict[str, List[Dict[str, Any]]]:
        return self.rows_by_scenario