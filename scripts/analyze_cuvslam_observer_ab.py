#!/usr/bin/env python3
"""Evaluate three static A/B observer rounds against the CPU and continuity gates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def nested(report: Dict[str, Any], *keys: str) -> Any:
    value: Any = report
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def numeric(report: Dict[str, Any], *keys: str) -> Optional[float]:
    value = nested(report, *keys)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def load_report(path: Path) -> Dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        report = json.load(handle)
    if not isinstance(report, dict):
        raise ValueError(f"report is not a JSON object: {path}")
    return report


def tri_signal_correlations(
    report: Dict[str, Any], window_seconds: float = 2.0
) -> List[Dict[str, Any]]:
    anomalies = report.get("anomalies") or []
    counter_events = [item for item in anomalies if item.get("kind") == "counter_gap"]
    frame_events = [
        item for item in anomalies if item.get("kind") == "frame_delta_log"
    ]
    odom_events = [
        item
        for item in anomalies
        if item.get("kind") == "stream_gap" and item.get("stream") == "odometry"
    ]
    window_ns = int(window_seconds * 1.0e9)

    def nearby(origin: Dict[str, Any], candidates: List[Dict[str, Any]]):
        origin_time = origin.get("monotonic_ns")
        if not isinstance(origin_time, int):
            return []
        return [
            candidate
            for candidate in candidates
            if isinstance(candidate.get("monotonic_ns"), int)
            and abs(candidate["monotonic_ns"] - origin_time) <= window_ns
        ]

    result = []
    for counter in counter_events:
        matching_frames = nearby(counter, frame_events)
        matching_odom = nearby(counter, odom_events)
        result.append(
            {
                "counter_event": counter,
                "frame_delta_events": matching_frames,
                "odometry_gap_events": matching_odom,
                "all_three_in_window": bool(matching_frames and matching_odom),
                "window_seconds": window_seconds,
            }
        )
    return result


def evaluate_pair(
    baseline: Dict[str, Any],
    observer: Dict[str, Any],
    self_cpu_limit: float = 5.0,
    aggregate_delta_limit: float = 2.0,
) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    if baseline.get("mode") != "baseline" or baseline.get("subscribe_topics") is not False:
        errors.append("A report is not a no-subscription baseline")
    if observer.get("mode") != "observer" or observer.get("subscribe_topics") is not True:
        errors.append("B report is not an observer run")

    baseline_cpu = numeric(baseline, "cpu", "aggregate_pct", "average")
    observer_cpu = numeric(observer, "cpu", "aggregate_pct", "average")
    observer_self_cpu = numeric(
        observer, "cpu", "probe_self_pct_one_core", "average"
    )
    if baseline_cpu is None or observer_cpu is None:
        errors.append("aggregate CPU average is missing")
        aggregate_delta = None
    else:
        aggregate_delta = observer_cpu - baseline_cpu
        if aggregate_delta >= aggregate_delta_limit:
            errors.append(
                "six-core aggregate CPU delta %.3f >= %.3f percentage points"
                % (aggregate_delta, aggregate_delta_limit)
            )
    if observer_self_cpu is None:
        errors.append("observer self CPU average is missing")
    elif observer_self_cpu >= self_cpu_limit:
        errors.append(
            "observer self CPU %.3f >= %.3f percent of one core"
            % (observer_self_cpu, self_cpu_limit)
        )

    duration = numeric(observer, "duration_s") or 0.0
    sample_count = numeric(observer, "cpu", "aggregate_pct", "count") or 0.0
    if duration > 0.0 and sample_count < duration * 0.75:
        errors.append(
            "observer CPU sample coverage is too low: %.0f samples for %.1fs"
            % (sample_count, duration)
        )

    if observer.get("measurement_gate_passed") is not True:
        errors.append("observer IR/IMU/odometry/log continuity gate failed")
    baseline_frame_warnings = numeric(
        baseline, "launch_log", "frame_delta_warning_count"
    )
    baseline_tracking_lost = numeric(baseline, "launch_log", "tracking_lost_count")
    if baseline_frame_warnings not in (None, 0.0):
        errors.append("A baseline contains cuVSLAM frame-delta warnings")
    if baseline_tracking_lost not in (None, 0.0):
        errors.append("A baseline contains tracking-lost warnings")

    status_graph = observer.get("status_graph") or {}
    if not status_graph.get("available", False):
        warnings.append("/visual_slam/status is absent; log and odometry gates remain active")
    elif not status_graph.get("compatible", False):
        warnings.append("/visual_slam/status type is not std_msgs/msg/String; not subscribed")

    return {
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
        "metrics": {
            "baseline_aggregate_cpu_pct": baseline_cpu,
            "observer_aggregate_cpu_pct": observer_cpu,
            "aggregate_cpu_delta_points": aggregate_delta,
            "observer_self_cpu_pct_one_core": observer_self_cpu,
            "observer_scheduler_delay_ms": nested(
                observer, "cpu", "scheduler_delay_ms"
            ),
            "observer_per_core_cpu_pct": nested(observer, "cpu", "per_core_pct"),
        },
        "observer_gate_checks": observer.get("gate_checks", {}),
        "tri_signal_correlations": tri_signal_correlations(observer),
    }


def evaluate_directory(
    root: Path,
    expected_rounds: int = 3,
    self_cpu_limit: float = 5.0,
    aggregate_delta_limit: float = 2.0,
) -> Dict[str, Any]:
    pairs = []
    for index in range(1, expected_rounds + 1):
        baseline_path = root / f"A{index}" / "report.json"
        observer_path = root / f"B{index}" / "report.json"
        baseline = load_report(baseline_path)
        observer = load_report(observer_path)
        result = evaluate_pair(
            baseline,
            observer,
            self_cpu_limit=self_cpu_limit,
            aggregate_delta_limit=aggregate_delta_limit,
        )
        result.update(
            {
                "round": index,
                "baseline_report": str(baseline_path),
                "observer_report": str(observer_path),
            }
        )
        pairs.append(result)
    return {
        "schema_version": 1,
        "decision": "GO" if all(pair["passed"] for pair in pairs) else "NO_GO",
        "expected_rounds": expected_rounds,
        "thresholds": {
            "observer_self_cpu_pct_one_core_lt": self_cpu_limit,
            "six_core_aggregate_cpu_delta_points_lt": aggregate_delta_limit,
            "all_observer_continuity_gates": True,
            "all_baseline_log_gates": True,
        },
        "pairs": pairs,
    }


def write_summary(root: Path, result: Dict[str, Any]) -> None:
    json_path = root / "observer_ab_summary.json"
    text_path = root / "observer_ab_summary.txt"
    json_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [f"decision={result['decision']}"]
    for pair in result["pairs"]:
        metrics = pair["metrics"]
        lines.append(
            "round=%d passed=%s aggregate_delta_points=%s self_cpu_pct_one_core=%s"
            % (
                pair["round"],
                str(pair["passed"]).lower(),
                metrics["aggregate_cpu_delta_points"],
                metrics["observer_self_cpu_pct_one_core"],
            )
        )
        lines.extend(f"  error: {error}" for error in pair["errors"])
        lines.extend(f"  warning: {warning}" for warning in pair["warnings"])
    text_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--expected-rounds", type=int, default=3)
    parser.add_argument("--self-cpu-limit", type=float, default=5.0)
    parser.add_argument("--aggregate-delta-limit", type=float, default=2.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.expected_rounds <= 0:
        raise SystemExit("--expected-rounds must be positive")
    result = evaluate_directory(
        args.input_root,
        expected_rounds=args.expected_rounds,
        self_cpu_limit=args.self_cpu_limit,
        aggregate_delta_limit=args.aggregate_delta_limit,
    )
    write_summary(args.input_root, result)
    return 0 if result["decision"] == "GO" else 2


if __name__ == "__main__":
    raise SystemExit(main())
