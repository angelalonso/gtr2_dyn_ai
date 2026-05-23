#!/usr/bin/env python3
"""
Autopilot module for Live AI Tuner
Automatically adjusts AIW ratios based on detected race data
"""

import logging
import re
import sqlite3
import json
import shutil
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Any, Set
from dataclasses import dataclass, field
from datetime import datetime

from core_math import (
    DEFAULT_A_VALUE, MIN_A, MAX_A, MIN_B, MAX_B, MIN_RATIO, MAX_RATIO,
    time_from_ratio, ratio_from_time, clamp_ratio, 
    clamp_b, is_valid_formula, calculate_b_from_point, fit_hyperbolic,
    get_formula_string, calculate_error_metrics, should_suggest_manual_adjustment
)
from core_database import CurveDatabase
from core_data_extraction import RaceData
from core_config import get_base_path, get_nr_last_user_laptimes, get_ratio_limits
from core_aiw_utils import find_aiw_file_from_path, find_aiw_file_by_track, update_aiw_ratio, ensure_aiw_has_ratios
from core_user_laptimes import UserLapTimesManager

logger = logging.getLogger(__name__)

VEHICLE_CLASSES_FILE = Path(__file__).parent / "vehicle_classes.json"
_BACKED_UP_AIW_FILES: Set[str] = set()


def load_vehicle_classes(classes_path=None):
    """Load vehicle classes from JSON file"""
    default_classes = {
        "Formula Cars": {
            "vehicles": ["Formula Senior", "Formula Junior", "Formula 3", "Formula Renault", "Formula Ford", "f4", "F4", "F3", "F2", "F1"]
        },
        "GT Cars": {
            "vehicles": ["Porsche 911", "Porsche 996", "Ferrari 550", "Ferrari 360", "Lamborghini Murcielago", "Saleen S7", "Corvette C5R", "Dodge Viper", "Aston Martin DBR9", "Maserati MC12", "gt", "GT", "GTE", "GT3"]
        },
        "Prototype Cars": {
            "vehicles": ["LMP1", "LMP2", "Audi R8", "Bentley Speed 8", "Cadillac LMP"]
        },
        "Production Cars": {
            "vehicles": ["BMW M3", "Audi R8 LMS", "Mercedes SLS"]
        }
    }
    
    if classes_path is None:
        try:
            from core_common import get_data_file_path
            classes_path = get_data_file_path("vehicle_classes.json")
        except ImportError:
            classes_path = Path(__file__).parent / "vehicle_classes.json"
    
    if isinstance(classes_path, str):
        classes_path = Path(classes_path)
    
    if not classes_path.exists():
        try:
            classes_path.parent.mkdir(parents=True, exist_ok=True)
            with open(classes_path, 'w') as f:
                json.dump(default_classes, f, indent=2)
            logger.info(f"Created default vehicle_classes.json at {classes_path}")
            return default_classes
        except Exception as e:
            logger.warning(f"Could not create vehicle_classes.json: {e}")
            return default_classes
    
    try:
        with open(classes_path, 'r') as f:
            classes = json.load(f)
        return classes
    except Exception as e:
        logger.warning(f"Error loading {classes_path}: {e}, using defaults")
        return default_classes


def get_vehicle_class(vehicle_name: str, class_mapping: Dict[str, Dict]) -> str:
    if not vehicle_name:
        return "Unknown"
    
    vehicle_lower = vehicle_name.lower().strip()
    
    for class_name, class_data in class_mapping.items():
        vehicles = class_data.get("vehicles", [])
        for v in vehicles:
            if v.lower() == vehicle_lower:
                return class_name
    
    for class_name, class_data in class_mapping.items():
        vehicles = class_data.get("vehicles", [])
        for v in vehicles:
            if v.lower() in vehicle_lower or vehicle_lower in v.lower():
                return class_name
    
    return vehicle_name


@dataclass
class Formula:
    """Immutable formula representation"""
    track: str
    vehicle_class: str
    a: float
    b: float
    session_type: str
    created_at: str = ""
    last_used: str = ""
    confidence: float = 1.0
    data_points_used: int = 0
    avg_error: float = 0.0
    max_error: float = 0.0
    vehicles_in_class: Set[str] = field(default_factory=set)
    is_locked: bool = False
    locked_by_user: bool = False
    lock_reason: str = ""
    
    def get_time_at_ratio(self, ratio: float) -> float:
        """Calculate time from ratio using the formula"""
        return time_from_ratio(ratio, self.a, self.b)
    
    def get_ratio_for_time(self, lap_time: float) -> Optional[float]:
        """Calculate ratio from time using the formula"""
        return ratio_from_time(lap_time, self.a, self.b)
    
    def is_valid(self) -> bool:
        """Check if formula parameters are valid"""
        return is_valid_formula(self.a, self.b)
    
    def get_formula_string(self) -> str:
        """Get formatted formula string"""
        return get_formula_string(self.a, self.b)
    
    def should_auto_update(self) -> bool:
        """Determine if formula should be auto-updated (not locked by user)"""
        return not (self.is_locked and self.locked_by_user)
    
    @classmethod
    def from_point(cls, track: str, vehicle_class: str, ratio: float, 
                   lap_time: float, session_type: str, a_value: float = DEFAULT_A_VALUE,
                   is_locked: bool = False) -> 'Formula':
        """Create formula from a single data point"""
        b = calculate_b_from_point(ratio, lap_time, a_value)
        logger.debug(f"Created formula from point: a={a_value:.4f}, b={b:.4f}")
        return cls(
            track=track,
            vehicle_class=vehicle_class,
            a=a_value,
            b=b,
            session_type=session_type,
            confidence=0.5,
            data_points_used=1,
            vehicles_in_class={vehicle_class},
            is_locked=is_locked,
            locked_by_user=is_locked
        )
    
    @classmethod
    def from_points(cls, track: str, vehicle_class: str, session_type: str,
                    ratios: List[float], times: List[float], 
                    fixed_a: Optional[float] = None,
                    outlier_method: str = "none",
                    outlier_threshold: float = 2.0,
                    optimize_a: bool = False,
                    min_ratio_limit: float = 0.5,
                    max_ratio_limit: float = 1.5,
                    is_locked: bool = False) -> Optional['Formula']:
        """Create formula by fitting to multiple data points"""
        # When optimize_a is False, we keep a fixed and only fit b
        a, b, stats = fit_hyperbolic(
            ratios, times, 
            fixed_a=fixed_a,
            outlier_method=outlier_method,
            outlier_threshold=outlier_threshold,
            optimize_a=optimize_a,
            min_ratio_limit=min_ratio_limit,
            max_ratio_limit=max_ratio_limit
        )
        
        if a is None or b is None:
            return None
        
        # Calculate error metrics for confidence
        error_metrics = calculate_error_metrics(ratios, times, a, b)
        
        # Determine confidence based on R-squared
        r_squared = error_metrics.get('r_squared', 0)
        if r_squared >= 0.95:
            confidence = 0.95
        elif r_squared >= 0.85:
            confidence = 0.85
        elif r_squared >= 0.70:
            confidence = 0.70
        else:
            confidence = 0.50
        
        return cls(
            track=track,
            vehicle_class=vehicle_class,
            a=a,
            b=b,
            session_type=session_type,
            confidence=confidence,
            data_points_used=stats.points_used,
            avg_error=stats.avg_error,
            max_error=stats.max_error,
            vehicles_in_class={vehicle_class},
            is_locked=is_locked,
            locked_by_user=is_locked
        )


class FormulaManager:
    def __init__(self, db: CurveDatabase):
        self.db = db
        self._formulas: Dict[str, Dict[str, Dict[str, Formula]]] = {}
        self._class_mapping = load_vehicle_classes()
        self._init_database()
        self._load_formulas()
    
    def _init_database(self):
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS formulas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                track TEXT NOT NULL,
                vehicle_class TEXT NOT NULL,
                a REAL NOT NULL,
                b REAL NOT NULL,
                session_type TEXT NOT NULL,
                confidence REAL DEFAULT 1.0,
                data_points_used INTEGER DEFAULT 0,
                avg_error REAL DEFAULT 0.0,
                max_error REAL DEFAULT 0.0,
                vehicles_in_class TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_used TEXT DEFAULT CURRENT_TIMESTAMP,
                a_value REAL DEFAULT 32.0,
                is_locked INTEGER DEFAULT 0,
                locked_by_user INTEGER DEFAULT 0,
                lock_reason TEXT DEFAULT ''
            )
        """)
        
        cursor.execute("PRAGMA table_info(formulas)")
        columns = [col[1] for col in cursor.fetchall()]
        if 'a_value' not in columns:
            cursor.execute("ALTER TABLE formulas ADD COLUMN a_value REAL DEFAULT 32.0")
        if 'is_locked' not in columns:
            cursor.execute("ALTER TABLE formulas ADD COLUMN is_locked INTEGER DEFAULT 0")
        if 'locked_by_user' not in columns:
            cursor.execute("ALTER TABLE formulas ADD COLUMN locked_by_user INTEGER DEFAULT 0")
        if 'lock_reason' not in columns:
            cursor.execute("ALTER TABLE formulas ADD COLUMN lock_reason TEXT DEFAULT ''")
        
        conn.commit()
        conn.close()
    
    def _load_formulas(self):
        self._formulas.clear()
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT track, vehicle_class, a, b, session_type, confidence, 
                   data_points_used, avg_error, max_error, vehicles_in_class, a_value,
                   is_locked, locked_by_user, lock_reason
            FROM formulas
        """)
        rows = cursor.fetchall()
        conn.close()
        
        logger.debug(f"Loading formulas from database...")
        
        for row in rows:
            vehicles_str = row[9] if len(row) > 9 else ""
            vehicles_set = set(vehicles_str.split(',')) if vehicles_str else set()
            is_locked = bool(row[11]) if len(row) > 11 else False
            locked_by_user = bool(row[12]) if len(row) > 12 else False
            lock_reason = row[13] if len(row) > 13 else ""
            
            formula = Formula(
                track=row[0], vehicle_class=row[1], a=row[2], b=row[3],
                session_type=row[4], confidence=row[5], data_points_used=row[6],
                avg_error=row[7], max_error=row[8], vehicles_in_class=vehicles_set,
                is_locked=is_locked, locked_by_user=locked_by_user, lock_reason=lock_reason
            )
            if formula.is_valid():
                if formula.track not in self._formulas:
                    self._formulas[formula.track] = {}
                if formula.vehicle_class not in self._formulas[formula.track]:
                    self._formulas[formula.track][formula.vehicle_class] = {}
                self._formulas[formula.track][formula.vehicle_class][formula.session_type] = formula
        
        logger.debug(f"Loaded {self.get_formula_count()} formulas from database")
    
    def get_formula(self, track: str, vehicle_name: str, session_type: str) -> Optional[Formula]:
        vehicle_class = get_vehicle_class(vehicle_name, self._class_mapping)
        track_dict = self._formulas.get(track, {})
        class_dict = track_dict.get(vehicle_class, {})
        return class_dict.get(session_type)
    
    def get_formula_by_class(self, track: str, vehicle_class: str, session_type: str) -> Optional[Formula]:
        track_dict = self._formulas.get(track, {})
        class_dict = track_dict.get(vehicle_class, {})
        return class_dict.get(session_type)
    
    def get_all_formulas_for_track(self, track: str) -> List[Formula]:
        formulas = []
        track_dict = self._formulas.get(track, {})
        for class_dict in track_dict.values():
            formulas.extend(class_dict.values())
        return formulas
    
    def get_all_formulas(self) -> List[Formula]:
        formulas = []
        for track_dict in self._formulas.values():
            for class_dict in track_dict.values():
                formulas.extend(class_dict.values())
        return formulas
    
    def get_formula_count(self) -> int:
        count = 0
        for track_dict in self._formulas.values():
            for class_dict in track_dict.values():
                count += len(class_dict)
        return count
    
    def get_tracks_with_formulas(self) -> List[str]:
        return list(self._formulas.keys())
    
    def save_formula(self, formula: Formula) -> bool:
        if not formula.is_valid():
            logger.warning(f"Not saving invalid formula: {formula.get_formula_string()}")
            return False
        
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        
        vehicles_str = ','.join(formula.vehicles_in_class)
        
        cursor.execute("""
            INSERT OR REPLACE INTO formulas 
            (track, vehicle_class, a, b, session_type, confidence, data_points_used, 
             avg_error, max_error, vehicles_in_class, last_used, a_value,
             is_locked, locked_by_user, lock_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?, ?)
        """, (
            formula.track, formula.vehicle_class, formula.a, formula.b, 
            formula.session_type, formula.confidence, formula.data_points_used,
            formula.avg_error, formula.max_error, vehicles_str, formula.a,
            1 if formula.is_locked else 0, 1 if formula.locked_by_user else 0, formula.lock_reason
        ))
        conn.commit()
        conn.close()
        
        if formula.track not in self._formulas:
            self._formulas[formula.track] = {}
        if formula.vehicle_class not in self._formulas[formula.track]:
            self._formulas[formula.track][formula.vehicle_class] = {}
        self._formulas[formula.track][formula.vehicle_class][formula.session_type] = formula
        
        logger.debug(f"Saved formula for {formula.track}/{formula.vehicle_class}/{formula.session_type}: {formula.get_formula_string()} (locked={formula.is_locked})")
        return True
    
    def lock_formula(self, track: str, vehicle_class: str, session_type: str, reason: str = "") -> bool:
        """Lock a formula so it won't be auto-updated"""
        formula = self.get_formula_by_class(track, vehicle_class, session_type)
        if not formula:
            logger.warning(f"Cannot lock formula: not found for {track}/{vehicle_class}/{session_type}")
            return False
        
        new_formula = Formula(
            track=formula.track,
            vehicle_class=formula.vehicle_class,
            a=formula.a,
            b=formula.b,
            session_type=formula.session_type,
            confidence=formula.confidence,
            data_points_used=formula.data_points_used,
            avg_error=formula.avg_error,
            max_error=formula.max_error,
            vehicles_in_class=formula.vehicles_in_class,
            is_locked=True,
            locked_by_user=True,
            lock_reason=reason
        )
        return self.save_formula(new_formula)
    
    def unlock_formula(self, track: str, vehicle_class: str, session_type: str) -> bool:
        """Unlock a formula to allow auto-updates"""
        formula = self.get_formula_by_class(track, vehicle_class, session_type)
        if not formula:
            return False
        
        new_formula = Formula(
            track=formula.track,
            vehicle_class=formula.vehicle_class,
            a=formula.a,
            b=formula.b,
            session_type=formula.session_type,
            confidence=formula.confidence,
            data_points_used=formula.data_points_used,
            avg_error=formula.avg_error,
            max_error=formula.max_error,
            vehicles_in_class=formula.vehicles_in_class,
            is_locked=False,
            locked_by_user=False,
            lock_reason=""
        )
        return self.save_formula(new_formula)
    
    def is_formula_locked(self, track: str, vehicle_class: str, session_type: str) -> bool:
        """Check if a formula is locked"""
        formula = self.get_formula_by_class(track, vehicle_class, session_type)
        return formula.is_locked if formula else False
    
    def get_lock_reason(self, track: str, vehicle_class: str, session_type: str) -> str:
        """Get the lock reason for a locked formula"""
        formula = self.get_formula_by_class(track, vehicle_class, session_type)
        return formula.lock_reason if formula else ""
    
    def update_formula_a_value(self, track: str, vehicle_class: str, session_type: str, a_value: float) -> bool:
        """Manually update the A value - only called by user, never by autopilot"""
        formula = self.get_formula_by_class(track, vehicle_class, session_type)
        if not formula:
            return False
        
        new_formula = Formula(
            track=formula.track,
            vehicle_class=formula.vehicle_class,
            a=a_value,
            b=formula.b,
            session_type=formula.session_type,
            confidence=formula.confidence,
            data_points_used=formula.data_points_used,
            vehicles_in_class=formula.vehicles_in_class,
            is_locked=formula.is_locked,
            locked_by_user=formula.locked_by_user,
            lock_reason=formula.lock_reason
        )
        return self.save_formula(new_formula)
    
    def update_formula_with_point(self, track: str, vehicle_class: str, session_type: str,
                                   ratio: float, lap_time: float,
                                   min_ratio_limit: float = 0.5, max_ratio_limit: float = 1.5) -> Optional[Formula]:
        """
        Update formula by adding a new data point.
        IMPORTANT: This only updates b (the asymptote). a remains fixed.
        """
        existing = self.get_formula_by_class(track, vehicle_class, session_type)
        
        # Don't update if formula is locked by user
        if existing and existing.is_locked and existing.locked_by_user:
            logger.info(f"Formula for {track}/{vehicle_class}/{session_type} is locked by user, not updating")
            return existing
        
        if existing and existing.data_points_used >= 1:
            # Get all points from database for this combo
            conn = sqlite3.connect(self.db.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT ratio, lap_time FROM data_points 
                WHERE track = ? AND vehicle_class = ? AND session_type = ?
            """, (track, vehicle_class, session_type))
            rows = cursor.fetchall()
            conn.close()
            
            if rows:
                ratios = [r[0] for r in rows]
                times = [r[1] for r in rows]
                # Add the new point
                ratios.append(ratio)
                times.append(lap_time)
                
                # IMPORTANT: When updating formula with new point, we KEEP A FIXED
                # Only b is recalculated based on all data points
                # We set fixed_a to the existing a value, and optimize_a to False
                new_formula = Formula.from_points(
                    track, vehicle_class, session_type,
                    ratios, times, 
                    fixed_a=existing.a,  # Keep a fixed to the existing value
                    outlier_method="none",  # No outlier detection for auto-updates
                    optimize_a=False,  # NEVER optimize a in auto-updates
                    min_ratio_limit=min_ratio_limit,
                    max_ratio_limit=max_ratio_limit,
                    is_locked=existing.is_locked
                )
                if new_formula:
                    self.save_formula(new_formula)
                    logger.debug(f"Updated formula for {track}/{vehicle_class}/{session_type}: a kept at {existing.a:.4f}, b changed from {existing.b:.4f} to {new_formula.b:.4f}")
                    return new_formula
        
        # No existing formula or not enough points, create from single point
        # For first point, use the default A value
        new_formula = Formula.from_point(
            track, vehicle_class, ratio, lap_time, session_type, 
            a_value=DEFAULT_A_VALUE, is_locked=False
        )
        self.save_formula(new_formula)
        logger.debug(f"Created initial formula for {track}/{vehicle_class}/{session_type}: a={DEFAULT_A_VALUE:.4f}, b={new_formula.b:.4f}")
        return new_formula
    
    def check_formula_quality(self, track: str, vehicle_class: str, session_type: str) -> Tuple[bool, str]:
        """Check formula quality and return whether manual adjustment is suggested"""
        formula = self.get_formula_by_class(track, vehicle_class, session_type)
        if not formula or formula.data_points_used < 2:
            return False, ""
        
        # Get all data points for this combo
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT ratio, lap_time FROM data_points 
            WHERE track = ? AND vehicle_class = ? AND session_type = ?
        """, (track, vehicle_class, session_type))
        rows = cursor.fetchall()
        conn.close()
        
        if len(rows) < 2:
            return False, ""
        
        ratios = [r[0] for r in rows]
        times = [r[1] for r in rows]
        
        error_metrics = calculate_error_metrics(ratios, times, formula.a, formula.b)
        return should_suggest_manual_adjustment(error_metrics, len(rows))


class AutopilotEngine:
    def __init__(self, db: CurveDatabase, formula_manager: FormulaManager):
        self.db = db
        self.formula_manager = formula_manager
        self._class_mapping = load_vehicle_classes()
        self.user_laptimes_manager = None
        self._min_ratio, self._max_ratio = 0.5, 1.5
    
    def set_ratio_limits(self, min_ratio: float, max_ratio: float):
        self._min_ratio = min_ratio
        self._max_ratio = max_ratio
    
    def set_user_laptimes_manager(self, manager: UserLapTimesManager):
        self.user_laptimes_manager = manager
    
    def _backup_aiw_file(self, aiw_path: Path) -> bool:
        global _BACKED_UP_AIW_FILES
        
        aiw_key = str(aiw_path.absolute())
        if aiw_key in _BACKED_UP_AIW_FILES:
            return True
        
        try:
            backup_dir = Path(self.db.db_path).parent / "aiw_backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_name = f"{aiw_path.stem}_ORIGINAL{aiw_path.suffix}"
            backup_path = backup_dir / backup_name
            if not backup_path.exists():
                shutil.copy2(aiw_path, backup_path)
                logger.debug(f"Created backup: {backup_path}")
            _BACKED_UP_AIW_FILES.add(aiw_key)
            return True
        except Exception as e:
            logger.error(f"Failed to backup AIW: {e}")
            return False
    
    def _get_data_points(self, track: str, vehicle_class: str, session_type: str) -> List[Tuple[float, float]]:
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        session_filter = "qual" if session_type == "qual" else "race"
        cursor.execute("""
            SELECT ratio, lap_time 
            FROM data_points 
            WHERE track = ? AND vehicle_class = ? AND session_type = ?
        """, (track, vehicle_class, session_filter))
        rows = cursor.fetchall()
        conn.close()
        return [(ratio, lap_time) for ratio, lap_time in rows]
    
    def calculate_target_time_from_settings(self, best_ai_time, worst_ai_time, settings):
        if best_ai_time <= 0 or worst_ai_time <= 0:
            return best_ai_time if best_ai_time > 0 else worst_ai_time
        
        ai_range = worst_ai_time - best_ai_time
        mode = settings.get("mode", "percentage")
        
        if mode == "percentage":
            pct = settings.get("percentage", 50) / 100.0
            target = best_ai_time + (ai_range * pct)
        elif mode == "faster_than_best":
            offset = settings.get("offset_seconds", 0.0)
            target = best_ai_time + offset
        else:
            offset = settings.get("offset_seconds", 0.0)
            target = worst_ai_time - offset
        
        error_margin = settings.get("error_margin", 0.0)
        target = target + error_margin
        target = max(best_ai_time, min(worst_ai_time + error_margin, target))
        return target
    
    def _get_median_user_laptime(self, track: str, vehicle_class: str, session_type: str) -> Optional[float]:
        if self.user_laptimes_manager:
            return self.user_laptimes_manager.get_median_laptime_for_combo(track, vehicle_class, session_type)
        return None
    
    def _add_user_laptime(self, track: str, vehicle_class: str, session_type: str, 
                          lap_time: float, current_ratio: float) -> bool:
        if self.user_laptimes_manager:
            return self.user_laptimes_manager.add_laptime(track, vehicle_class, session_type, 
                                                          lap_time, current_ratio)
        return False
    
    def _get_user_laptimes_for_graph(self, track: str, vehicle_class: str, 
                                      session_type: str) -> List[Tuple[float, float]]:
        if self.user_laptimes_manager:
            times = self.user_laptimes_manager.get_laptimes_for_combo(track, vehicle_class, session_type)
            return [(lt[0], lt[1]) for lt in times]
        return []
    
    def _get_or_create_formula(self, track: str, vehicle_class: str, session_type: str, 
                                current_ratio: float, target_time: float) -> Formula:
        formula = self.formula_manager.get_formula_by_class(track, vehicle_class, session_type)
        
        # Check if formula is locked - don't modify if locked by user
        if formula and formula.is_locked and formula.locked_by_user:
            logger.info(f"Formula for {track}/{vehicle_class}/{session_type} is locked by user, using existing formula without update")
            return formula
        
        if formula:
            # Update formula with new point - this only updates b, keeps a fixed
            updated = self.formula_manager.update_formula_with_point(
                track, vehicle_class, session_type, current_ratio, target_time,
                self._min_ratio, self._max_ratio
            )
            if updated:
                logger.info(f"Formula for Track {track}, car class {vehicle_class} updated to {updated.get_formula_string()}")
                return updated
            return formula
        else:
            logger.debug(f"Creating new formula for {track}/{vehicle_class}/{session_type}")
            # For first point, use default A value
            new_formula = Formula.from_point(track, vehicle_class, current_ratio, target_time, session_type, DEFAULT_A_VALUE)
            self.formula_manager.save_formula(new_formula)
            return new_formula
    
    def _calculate_new_ratio_direct(self, user_lap_time: float, a: float, b: float) -> Optional[float]:
        """Calculate new ratio using the unified math function"""
        return ratio_from_time(user_lap_time, a, b)
    
    def _find_aiw_file_for_track(self, track_name: str, base_path: Path) -> Optional[Path]:
        return find_aiw_file_by_track(track_name, base_path)
    
    def _update_aiw_ratio(self, aiw_path: Path, ratio_name: str, new_ratio: float) -> bool:
        backup_dir = Path(self.db.db_path).parent / "aiw_backups"
        return update_aiw_ratio(aiw_path, ratio_name, new_ratio, backup_dir)
    
    def _process_session(self, track: str, vehicle_class: str, session_type: str, 
                         current_ratio: float, user_lap_time: float, midpoint_time: float, 
                         aiw_path: Path, ratio_name: str, ai_target_settings: Dict = None,
                         race_data_aiw_path: Path = None) -> Dict[str, Any]:
        
        result = {"updated": False, "old_ratio": current_ratio, "new_ratio": None, "formula": None, "message": ""}
        
        logger.debug(f"\n{'='*50}")
        logger.debug(f"[{session_type.upper()}] Processing {session_type} session")
        logger.debug(f"Current ratio from AIW: {current_ratio:.6f}")
        logger.debug(f"User lap time: {user_lap_time:.3f}s" if user_lap_time > 0 else "User lap time: Not available")
        
        actual_aiw_path = None
        
        if race_data_aiw_path and race_data_aiw_path.exists():
            actual_aiw_path = race_data_aiw_path
            logger.info(f"Using AIW path from race_data: {actual_aiw_path}")
        elif aiw_path and aiw_path.exists():
            actual_aiw_path = aiw_path
            logger.info(f"Using AIW path from config: {actual_aiw_path}")
        else:
            base_path = get_base_path()
            if base_path:
                actual_aiw_path = self._find_aiw_file_for_track(track, base_path)
                if actual_aiw_path:
                    logger.info(f"Found AIW via track search: {actual_aiw_path}")
        
        if actual_aiw_path:
            logger.info(f"AIW path resolution for {session_type}: using {actual_aiw_path}")
        else:
            logger.error(f"AIW path resolution for {session_type}: FAILED - no path found")
            result["message"] = f"AIW file not found for track: {track}"
            return result
        
        if not actual_aiw_path or not actual_aiw_path.exists():
            logger.error(f"Cannot find AIW file for track: {track}")
            result["message"] = f"AIW file not found for track: {track}"
            return result
        
        backup_dir = Path(self.db.db_path).parent / "aiw_backups"
        ensure_aiw_has_ratios(actual_aiw_path, backup_dir)
        
        existing_formula = self.formula_manager.get_formula_by_class(track, vehicle_class, session_type)
        
        # Check if formula is locked - if locked by user, use it as is without modification
        if existing_formula and existing_formula.is_locked and existing_formula.locked_by_user:
            logger.info(f"Formula for {track}/{vehicle_class}/{session_type} is locked by user: {existing_formula.lock_reason}")
            a = existing_formula.a
            b = existing_formula.b
            result["formula"] = existing_formula
            
            # Still calculate new ratio using locked formula
            effective_user_time = user_lap_time
            if user_lap_time > 0:
                median_time = self._get_median_user_laptime(track, vehicle_class, session_type)
                if median_time is not None:
                    effective_user_time = median_time
                self._add_user_laptime(track, vehicle_class, session_type, user_lap_time, current_ratio)
            
            new_ratio = None
            if effective_user_time > 0:
                new_ratio = self._calculate_new_ratio_direct(effective_user_time, a, b)
                if new_ratio:
                    new_ratio = clamp_ratio(new_ratio, self._min_ratio, self._max_ratio)
            
            if new_ratio and abs(new_ratio - current_ratio) > 0.000001:
                logger.info(f"Updating {ratio_name} from {current_ratio:.6f} to {new_ratio:.6f} (using locked formula)")
                if self._update_aiw_ratio(actual_aiw_path, ratio_name, new_ratio):
                    result["updated"] = True
                    result["new_ratio"] = new_ratio
            return result
        
        if existing_formula and existing_formula.is_valid():
            a = existing_formula.a
            b = existing_formula.b
            logger.debug(f"Using existing formula: a={a:.2f}, b={b:.2f}")
            result["formula"] = existing_formula
        else:
            # No existing formula - use default A value
            a = DEFAULT_A_VALUE
            b = 70.0
            logger.debug(f"No formula found, using default a={a:.2f}, b={b:.2f}")
        
        effective_user_time = user_lap_time
        
        if user_lap_time > 0:
            median_time = self._get_median_user_laptime(track, vehicle_class, session_type)
            if median_time is not None:
                effective_user_time = median_time
                logger.debug(f"Using median user lap time for combo: {median_time:.3f}s")
            self._add_user_laptime(track, vehicle_class, session_type, user_lap_time, current_ratio)
        
        new_ratio = None
        if effective_user_time > 0:
            new_ratio = self._calculate_new_ratio_direct(effective_user_time, a, b)
            if new_ratio:
                logger.debug(f"Direct new ratio (using {'median' if effective_user_time != user_lap_time else 'current'} time): {new_ratio:.6f}")
            else:
                logger.debug(f"Cannot calculate ratio: denominator <= 0")
        
        if new_ratio:
            clamped_ratio = clamp_ratio(new_ratio, self._min_ratio, self._max_ratio)
            if clamped_ratio != new_ratio:
                logger.debug(f"Ratio clamped from {new_ratio:.6f} to {clamped_ratio:.6f}")
                new_ratio = clamped_ratio
        
        if ai_target_settings and new_ratio and new_ratio != current_ratio:
            existing_points = self._get_data_points(track, vehicle_class, session_type)
            if existing_points:
                ai_times = [t for _, t in existing_points]
                best_ai_time = min(ai_times)
                worst_ai_time = max(ai_times)
                
                target_time = self.calculate_target_time_from_settings(best_ai_time, worst_ai_time, ai_target_settings)
                adjusted_ratio = self._calculate_new_ratio_direct(target_time, a, b)
                if adjusted_ratio:
                    adjusted_ratio = clamp_ratio(adjusted_ratio, self._min_ratio, self._max_ratio)
                    if abs(adjusted_ratio - current_ratio) > 0.000001:
                        logger.debug(f"Adjusted for AI target: {adjusted_ratio:.6f}")
                        new_ratio = adjusted_ratio
        
        if new_ratio and abs(new_ratio - current_ratio) > 0.000001:
            logger.info(f"Updating {ratio_name} from {current_ratio:.6f} to {new_ratio:.6f}")
            if self._update_aiw_ratio(actual_aiw_path, ratio_name, new_ratio):
                result["updated"] = True
                result["new_ratio"] = new_ratio
                logger.info(f"Successfully updated {ratio_name} in AIW")
            else:
                logger.error(f"Failed to update AIW file")
                result["message"] = f"Failed to update {ratio_name} in AIW file"
        
        if effective_user_time > 0:
            target_time_for_formula = effective_user_time
            updated_formula = self.formula_manager.update_formula_with_point(
                track, vehicle_class, session_type, current_ratio, target_time_for_formula,
                self._min_ratio, self._max_ratio
            )
            if updated_formula:
                result["formula"] = updated_formula
                logger.debug(f"Updated formula with new data point (a kept fixed at {updated_formula.a:.4f})")
                
                # Check formula quality and suggest manual adjustment
                should_suggest, reason = self.formula_manager.check_formula_quality(track, vehicle_class, session_type)
                if should_suggest:
                    logger.warning(f"Formula quality warning for {track}/{vehicle_class}/{session_type}: {reason}")
                    result["suggest_manual"] = True
                    result["suggest_reason"] = reason
            elif existing_formula:
                result["formula"] = existing_formula
        
        return result
    
    def get_user_laptimes_for_combo(self, track: str, vehicle_class: str, 
                                     session_type: str) -> List[Tuple[float, float]]:
        return self._get_user_laptimes_for_graph(track, vehicle_class, session_type)
    
    def process_race_data(self, race_data: RaceData, aiw_path: Path, ai_target_settings: Dict = None) -> Dict[str, Any]:
        result = {
            "success": False,
            "qual_updated": False,
            "race_updated": False,
            "qual_new_ratio": None,
            "race_new_ratio": None,
            "qual_old_ratio": None,
            "race_old_ratio": None,
            "qual_formula": None,
            "race_formula": None,
            "message": "",
            "qual_suggest_manual": False,
            "race_suggest_manual": False,
            "qual_suggest_reason": "",
            "race_suggest_reason": ""
        }
        
        if not race_data.track_name:
            result["message"] = "No track name"
            return result
        
        track = race_data.track_name
        user_vehicle = race_data.user_vehicle or "Unknown"
        vehicle_class = get_vehicle_class(user_vehicle, self._class_mapping)
        
        race_aiw_path = race_data.aiw_path if hasattr(race_data, 'aiw_path') and race_data.aiw_path else None
        if race_aiw_path and race_aiw_path.exists():
            logger.info(f"Using AIW path from race_data: {race_aiw_path}")
        
        has_qual = (race_data.qual_ratio is not None and race_data.qual_ratio > 0 and 
                    race_data.qual_best_ai_lap_sec > 0 and race_data.qual_worst_ai_lap_sec > 0)
        has_race = (race_data.race_ratio is not None and race_data.race_ratio > 0 and 
                    race_data.best_ai_lap_sec > 0 and race_data.worst_ai_lap_sec > 0)
        
        session_type_str = ""
        if has_qual and has_race:
            session_type_str = "both"
        elif has_qual:
            session_type_str = "qualifying"
        elif has_race:
            session_type_str = "race"
        
        if session_type_str != "none":
            logger.info(f"New data received for Track {track}, {session_type_str} session, car class {vehicle_class}")
        
        logger.debug(f"\n{'='*70}")
        logger.debug(f"[AUTO] Processing race data")
        logger.debug(f"{'='*70}")
        logger.debug(f"Track: '{track}'")
        logger.debug(f"User Vehicle: '{user_vehicle}' -> Class: '{vehicle_class}'")
        
        if has_qual:
            result["qual_old_ratio"] = race_data.qual_ratio
            qual_result = self._process_session(
                track, vehicle_class, "qual",
                race_data.qual_ratio, race_data.user_qualifying_sec,
                (race_data.qual_best_ai_lap_sec + race_data.qual_worst_ai_lap_sec) / 2,
                aiw_path, "QualRatio", ai_target_settings, race_aiw_path
            )
            result["qual_updated"] = qual_result["updated"]
            result["qual_new_ratio"] = qual_result["new_ratio"]
            result["qual_formula"] = qual_result["formula"]
            result["qual_suggest_manual"] = qual_result.get("suggest_manual", False)
            result["qual_suggest_reason"] = qual_result.get("suggest_reason", "")
        
        if has_race:
            result["race_old_ratio"] = race_data.race_ratio
            race_result = self._process_session(
                track, vehicle_class, "race",
                race_data.race_ratio, race_data.user_best_lap_sec,
                (race_data.best_ai_lap_sec + race_data.worst_ai_lap_sec) / 2,
                aiw_path, "RaceRatio", ai_target_settings, race_aiw_path
            )
            result["race_updated"] = race_result["updated"]
            result["race_new_ratio"] = race_result["new_ratio"]
            result["race_formula"] = race_result["formula"]
            result["race_suggest_manual"] = race_result.get("suggest_manual", False)
            result["race_suggest_reason"] = race_result.get("suggest_reason", "")
        
        result["success"] = result["qual_updated"] or result["race_updated"]
        
        logger.debug(f"\n{'='*70}")
        logger.debug(f"[AUTO] Summary")
        logger.debug(f"{'='*70}")
        if result["qual_updated"]:
            logger.debug(f"QUALIFYING: {result['qual_old_ratio']:.6f} -> {result['qual_new_ratio']:.6f}")
        if result["race_updated"]:
            logger.debug(f"RACE: {result['race_old_ratio']:.6f} -> {result['race_new_ratio']:.6f}")
        if result.get("qual_suggest_manual", False):
            logger.debug(f"QUALIFYING SUGGESTION: {result['qual_suggest_reason']}")
        if result.get("race_suggest_manual", False):
            logger.debug(f"RACE SUGGESTION: {result['race_suggest_reason']}")
        logger.debug(f"{'='*70}\n")
        
        return result
    
    def calculate_ratio_from_formula(self, track: str, vehicle_class: str, session_type: str, lap_time: float) -> Optional[float]:
        formula = self.formula_manager.get_formula_by_class(track, vehicle_class, session_type)
        if not formula:
            formula = Formula(track, vehicle_class, DEFAULT_A_VALUE, 70.0, session_type)
        
        return formula.get_ratio_for_time(lap_time)


class AutopilotManager:
    def __init__(self, db: CurveDatabase):
        self.db = db
        self.formula_manager = FormulaManager(db)
        self.engine = AutopilotEngine(db, self.formula_manager)
        self.enabled = False
        self.user_laptimes_manager = None
    
    def set_ratio_limits(self, min_ratio: float, max_ratio: float):
        """Set ratio limits for A optimization"""
        self.engine.set_ratio_limits(min_ratio, max_ratio)
    
    def set_user_laptimes_manager(self, manager: UserLapTimesManager):
        self.user_laptimes_manager = manager
        self.engine.set_user_laptimes_manager(manager)
    
    def set_enabled(self, enabled: bool):
        self.enabled = enabled
        logger.debug(f"Autoratio {'ENABLED' if enabled else 'DISABLED'}")
    
    def process_new_data(self, race_data: RaceData, aiw_path: Path, ai_target_settings: Dict = None) -> Dict[str, Any]:
        if not self.enabled:
            return {"success": False, "message": "Autoratio disabled"}
        return self.engine.process_race_data(race_data, aiw_path, ai_target_settings)
    
    def get_status(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "formula_count": self.formula_manager.get_formula_count(),
            "tracks_with_formulas": self.formula_manager.get_tracks_with_formulas()
        }
    
    def reload_formulas(self):
        self.formula_manager._load_formulas()
    
    def calculate_ratio(self, track: str, vehicle_class: str, session_type: str, lap_time: float) -> Optional[float]:
        return self.engine.calculate_ratio_from_formula(track, vehicle_class, session_type, lap_time)
    
    def get_user_laptimes_for_combo(self, track: str, vehicle_class: str, 
                                     session_type: str) -> List[Tuple[float, float]]:
        if self.user_laptimes_manager:
            return self.user_laptimes_manager.get_laptimes_for_combo(track, vehicle_class, session_type)
        return []
    
    def lock_formula(self, track: str, vehicle_class: str, session_type: str, reason: str = "") -> bool:
        """Lock a formula to prevent auto-updates"""
        return self.formula_manager.lock_formula(track, vehicle_class, session_type, reason)
    
    def unlock_formula(self, track: str, vehicle_class: str, session_type: str) -> bool:
        """Unlock a formula to allow auto-updates"""
        return self.formula_manager.unlock_formula(track, vehicle_class, session_type)
    
    def is_formula_locked(self, track: str, vehicle_class: str, session_type: str) -> bool:
        """Check if a formula is locked"""
        return self.formula_manager.is_formula_locked(track, vehicle_class, session_type)
    
    def get_lock_reason(self, track: str, vehicle_class: str, session_type: str) -> str:
        """Get lock reason for a locked formula"""
        return self.formula_manager.get_lock_reason(track, vehicle_class, session_type)
    
    def update_formula_a_value(self, track: str, vehicle_class: str, session_type: str, a_value: float) -> bool:
        """Manually update the A value - called only by user, never by autopilot"""
        return self.formula_manager.update_formula_a_value(track, vehicle_class, session_type, a_value)
