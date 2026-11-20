#!/usr/bin/env python3
"""Headless result importer and optional ratio updater."""

import argparse
import logging
from pathlib import Path
from typing import Iterable, List

from core_autopilot import AutopilotManager, get_vehicle_class, load_vehicle_classes
from core_config import (
    get_base_path,
    get_config_with_defaults,
    get_db_path,
    get_nr_last_user_laptimes,
    get_ratio_limits,
)
from core_data_extraction import DataExtractor
from core_database import CurveDatabase
from core_user_laptimes import UserLapTimesManager

logger = logging.getLogger("dyn_ai_cli")


def _result_files(file_path: Path | None, directory: Path | None) -> Iterable[Path]:
    if file_path:
        return [file_path]
    return sorted(
        (path for path in directory.iterdir() if path.is_file()),
        key=lambda path: path.stat().st_mtime_ns,
    )


def process_files(config_file: str, files: Iterable[Path], apply_ratios: bool) -> int:
    config = get_config_with_defaults(config_file)
    base_path = get_base_path(config_file)
    if not base_path:
        raise SystemExit("No valid GTR2 base_path configured")

    db = CurveDatabase(get_db_path(config_file))
    extractor = DataExtractor(base_path)
    class_mapping = load_vehicle_classes()
    processed = 0

    autopilot = None
    if apply_ratios:
        autopilot = AutopilotManager(db)
        min_ratio, max_ratio = get_ratio_limits(config_file)
        autopilot.set_ratio_limits(min_ratio, max_ratio)
        autopilot.set_user_laptimes_manager(
            UserLapTimesManager(db.db_path, get_nr_last_user_laptimes(config_file))
        )
        autopilot.set_enabled(True)
    target_settings = {
        "mode": "quartile_band" if config.get("ai_target_enabled", False) else "disabled",
        "band": config.get("ai_target_band", "top_25"),
        "min_ai_laps": config.get("ai_target_min_laps", 8),
        "min_ai_races": config.get("ai_target_min_races", 2),
    }

    for path in files:
        data = extractor.parse_race_results(path)
        if not data:
            print(f"SKIP {path}: parser failed")
            continue
        errors = data.validation_errors()
        if errors:
            print(f"SKIP {path}: {', '.join(errors)}")
            continue

        race_id = db.save_race_session(data.to_dict())
        if not race_id:
            print(f"SKIP {path}: already processed or could not be saved")
            continue

        points = []
        for track, vehicle, ratio, lap_time, session_type in data.to_data_points_with_vehicles():
            points.append((track, get_vehicle_class(vehicle, class_mapping), ratio, lap_time, session_type))
        db.add_data_points_batch(points)

        if autopilot:
            result = autopilot.process_new_data(data, data.aiw_path, target_settings)
            print(f"OK {path}: {race_id} ratios={result.get('success', False)}")
        else:
            print(f"OK {path}: {race_id} harvested={len(points)} points")
        processed += 1

    return processed


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="cfg.yml")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path)
    source.add_argument("--directory", type=Path)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Also update AIW ratios; without this flag only import/harvest is performed.",
    )
    args = parser.parse_args(argv)
    if args.directory and not args.directory.is_dir():
        parser.error(f"not a directory: {args.directory}")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    return 0 if process_files(args.config, _result_files(args.file, args.directory), args.apply) >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
