"""
Post-Mission Maximum A Posteriori (MAP) Parameter Calibration Utility.
Optimizes sensor prior probabilities against logged mission inference data and ground truth outcomes.
"""
import json
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional
import yaml


def load_mission_telemetry(log_file: Path) -> List[Dict[str, Any]]:
    """Ingest JSONL structured telemetry records from mission execution."""
    records: List[Dict[str, Any]] = []
    if not log_file.exists():
        raise FileNotFoundError(f"Mission log file not found: {log_file}")

    with open(log_file, "r", encoding="utf-8") as f:
        for line in f:
            line_str = line.strip()
            if line_str:
                try:
                    records.append(json.loads(line_str))
                except json.JSONDecodeError:
                    continue
    return records


def load_ground_truth(gt_file: Optional[Path]) -> Dict[str, bool]:
    """
    Parse optional ground truth CSV mapping zone_id -> victim_present (True/False).
    Format expected: zone_id,victim_present
    """
    ground_truth: Dict[str, bool] = {}
    if gt_file and gt_file.exists():
        with open(gt_file, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split(",")
                if len(parts) >= 2 and parts[0] != "zone_id":
                    zone_id = parts[0].strip()
                    is_victim = parts[1].strip().lower() in ("true", "1", "yes")
                    ground_truth[zone_id] = is_victim
    return ground_truth


def optimize_priors(
    records: List[Dict[str, Any]],
    ground_truth_map: Dict[str, bool],
    base_config_path: Path,
    output_path: Path
) -> Dict[str, Any]:
    """
    Calculate Maximum A Posteriori likelihood priors P(z|H) and P(z|~H)
    based on empirical sensor confidence distributions against verified targets.
    """
    with open(base_config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    inference_events = [r for r in records if r.get("record_type") == "INFERENCE_STEP"]
    if not inference_events:
        print("No INFERENCE_STEP events found in telemetry log. Retaining base configuration.")
        return config

    print(f"Analyzing {len(inference_events)} inference records for MAP optimization...")

    # Aggregators: sensor_type -> { "pos_conf_sum": float, "pos_count": int, "neg_conf_sum": float, "neg_count": int }
    sensor_stats: Dict[str, Dict[str, float]] = {}

    for event in inference_events:
        zone_id = event.get("zone_id", "")
        payload = event.get("sensor_payload", {})
        sensor_type = payload.get("sensor_type")
        conf = payload.get("confidence_score", 0.5)

        if not sensor_type:
            continue

        if sensor_type not in sensor_stats:
            sensor_stats[sensor_type] = {
                "pos_conf_sum": 0.0,
                "pos_count": 0.0,
                "neg_conf_sum": 0.0,
                "neg_count": 0.0
            }

        # Determine target state via ground truth mapping or high-probability convergence
        is_true_victim = ground_truth_map.get(zone_id, event.get("posterior_probability", 0.0) >= 0.85)

        if is_true_victim:
            sensor_stats[sensor_type]["pos_conf_sum"] += conf
            sensor_stats[sensor_type]["pos_count"] += 1.0
        else:
            sensor_stats[sensor_type]["neg_conf_sum"] += conf
            sensor_stats[sensor_type]["neg_count"] += 1.0

    sensor_priors = config.get("sensor_priors", {})

    for sensor_type, stats in sensor_stats.items():
        if sensor_type in sensor_priors:
            current_priors = sensor_priors[sensor_type]

            # MAP Prior Updates with Laplace smoothing
            if stats["pos_count"] > 0:
                empirical_p_z_h = (stats["pos_conf_sum"] + 1.0) / (stats["pos_count"] + 2.0)
                current_priors["p_z_given_h"] = round(max(0.60, min(0.99, empirical_p_z_h)), 3)

            if stats["neg_count"] > 0:
                empirical_p_z_not_h = (stats["neg_conf_sum"] + 0.1) / (stats["neg_count"] + 2.0)
                current_priors["p_z_given_not_h"] = round(max(0.01, min(0.35, empirical_p_z_not_h)), 3)

            print(f"  [{sensor_type}] Calibrated: P(z|H) = {current_priors['p_z_given_h']}, P(z|~H) = {current_priors['p_z_given_not_h']}")

    config["sensor_priors"] = sensor_priors
    config["version"] = config.get("version", 1) + 1
    config["activated_by"] = "MAP_CALIBRATION_PIPELINE"
    config["notes"] = f"Empirical MAP calibration generated from {len(inference_events)} telemetry samples."

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    print(f"Successfully wrote calibrated parameters to: {output_path} (Version: {config['version']})")
    return config


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Calibrate SAR Fusion Sensor Likelihood Priors (MAP)")
    parser.add_argument("--mission-logs", required=True, help="Path to mission JSONL log file")
    parser.add_argument("--ground-truth", required=False, help="Path to ground truth verification CSV")
    parser.add_argument("--base-config", default="config/fusion_parameters.yaml", help="Base YAML configuration path")
    parser.add_argument("--output", default="config/fusion_parameters.yaml", help="Output YAML path")

    args = parser.parse_args()

    mission_records = load_mission_telemetry(Path(args.mission_logs))
    gt_map = load_ground_truth(Path(args.ground_truth)) if args.ground_truth else {}

    optimize_priors(
        records=mission_records,
        ground_truth_map=gt_map,
        base_config_path=Path(args.base_config),
        output_path=Path(args.output)
    )