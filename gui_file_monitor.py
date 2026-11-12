#!/usr/bin/env python3
"""
File monitoring daemon for raceresults.txt
Checks for changes every N seconds and processes race data
"""

import threading
import logging
from pathlib import Path
from typing import Optional, Callable, Tuple

from core_data_extraction import DataExtractor, RaceData

logger = logging.getLogger(__name__)


class SimplifiedLogger:
    """Helper class to generate simplified, human-readable log messages"""
    
    @staticmethod
    def new_data_detected(track, vehicle_class, session_type, ratio, lap_time):
        return f"New data received for Track {track}, {session_type} session, car class {vehicle_class}"
    
    @staticmethod
    def new_ratio_calculation(old_ratio, new_ratio, ratio_name, user_lap_time, ratio_value):
        return f"New Ratio calculated for {ratio_name} session: {new_ratio:.6f} because user laptime was {user_lap_time} at Ratio {ratio_value:.6f}"
    
    @staticmethod
    def autosave_status(enabled):
        return f"Auto-harvest Data {'ON' if enabled else 'OFF'}"
    
    @staticmethod
    def autoratio_status(enabled):
        return f"Auto-calculate Ratios {'ON' if enabled else 'OFF'}"


class FileMonitorDaemon:
    """Daemon that monitors the newest parseable result file in a directory."""
    
    def __init__(self, results_path: Path, base_path: Path, poll_interval: float = 5.0, callback: Optional[Callable] = None):
        self.results_path = Path(results_path)
        self.results_dir = self.results_path if self.results_path.suffix == "" else self.results_path.parent
        self.base_path = base_path
        self.poll_interval = poll_interval
        self.running = False
        self.last_file_state: Optional[Tuple[str, int, int]] = None
        self.timer = None
        self.callback = callback
        self.extractor = DataExtractor(base_path)
        self._read_lock = threading.Lock()
        logger.info(f"[MONITOR] Initialized: watching {self.results_dir}")
        
    def start(self):
        if not self.results_dir.exists():
            logger.warning(f"[MONITOR] Results directory does not exist yet: {self.results_dir}")
            self.results_dir.mkdir(parents=True, exist_ok=True)
        
        self._update_file_state()
        self.running = True
        self._schedule_check()
        logger.info(f"[MONITOR] Started monitoring: {self.results_dir}")
        
    def stop(self):
        self.running = False
        if self.timer:
            self.timer.cancel()
        logger.info("[MONITOR] Stopped monitoring")
    
    def _schedule_check(self):
        if self.running:
            self.timer = threading.Timer(self.poll_interval, self._check_file)
            self.timer.daemon = True
            self.timer.start()
    
    def _update_file_state(self):
        latest = self._find_latest_parseable_file()
        if latest:
            self.last_file_state = self._file_state(latest)
            logger.debug(f"[MONITOR] Initial state: {self.last_file_state}")

    def _file_state(self, path: Path) -> Tuple[str, int, int]:
        stat = path.stat()
        return str(path), stat.st_mtime_ns, stat.st_size

    def _find_latest_parseable_file(self) -> Optional[Path]:
        if not self.results_dir.exists():
            return None
        candidates = []
        for path in self.results_dir.iterdir():
            try:
                if path.is_file():
                    candidates.append((path, path.stat().st_mtime_ns))
            except OSError as exc:
                logger.warning(f"[MONITOR] Cannot inspect {path}: {exc}")
        candidates.sort(key=lambda item: item[1], reverse=True)
        for path, _ in candidates:
            try:
                race_data = self.extractor.parse_race_results(path)
                if race_data and race_data.has_data():
                    return path
            except OSError as exc:
                logger.warning(f"[MONITOR] Cannot inspect {path}: {exc}")
        return None

    def read_now(self):
        """Read the latest result file immediately, without waiting for the timer."""
        threading.Thread(target=self._read_latest, args=(True,), daemon=True).start()

    def _read_latest(self, force: bool = False):
        with self._read_lock:
            latest = self._find_latest_parseable_file()
            if not latest:
                logger.debug("[MONITOR] No parseable result files found")
                return
            try:
                state = self._file_state(latest)
            except OSError as exc:
                logger.warning(f"[MONITOR] Cannot inspect latest result file: {exc}")
                return
            if not force and state == self.last_file_state:
                return
            logger.info(f"[MONITOR] Reading latest result file: {latest}")
            race_data = self.extractor.parse_race_results(latest)
            if race_data and race_data.has_data() and self.callback:
                self.callback(race_data)
            self.last_file_state = state
    
    def _check_file(self):
        try:
            if not self.running:
                return
            self._read_latest()
        except Exception as e:
            logger.error(f"[MONITOR] Error checking file: {e}")
        finally:
            self._schedule_check()
