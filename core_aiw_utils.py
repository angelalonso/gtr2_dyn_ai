#!/usr/bin/env python3
"""
Shared AIW file utilities for Live AI Tuner
Provides consistent AIW file finding across all modules
"""

import re
import shutil
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_AIW_LOCKS = {}
_AIW_LOCKS_GUARD = threading.Lock()


def _aiw_lock(path: Path):
    key = str(path.resolve())
    with _AIW_LOCKS_GUARD:
        return _AIW_LOCKS.setdefault(key, threading.RLock())


def _atomic_write(path: Path, content: str, attempts: int = 3) -> None:
    payload = content.encode("utf-8")
    last_error = None
    for attempt in range(attempts):
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False
            ) as temp:
                temp.write(payload)
                temp.flush()
                os.fsync(temp.fileno())
                temp_path = Path(temp.name)
            os.replace(temp_path, path)
            try:
                dir_fd = os.open(path.parent, os.O_DIRECTORY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except (AttributeError, OSError):
                pass
            return
        except OSError as exc:
            last_error = exc
            if temp_path:
                temp_path.unlink(missing_ok=True)
            if attempt + 1 < attempts:
                time.sleep(0.25 * (attempt + 1))
    raise last_error


def find_aiw_file_from_path(relative_path: str, base_path: Path) -> Optional[Path]:
    """
    Find AIW file from a relative path (like from raceresults.txt).
    Handles case-insensitive paths and different path separators.
    Also handles cases where the AIW filename doesn't match the referenced name.
    
    Args:
        relative_path: Path like "GAMEDATA/LOCATIONS/Testtrack2/Testtrack2.AIW"
        base_path: GTR2 installation path
    
    Returns:
        Full Path to AIW file or None if not found
    """
    if not relative_path or not base_path:
        logger.error(f"find_aiw_file_from_path: missing params - relative_path={relative_path}, base_path={base_path}")
        return None
    
    normalized = str(relative_path).replace('\\', '/')
    logger.debug(f"find_aiw_file_from_path: looking for '{normalized}'")
    
    full_path = base_path / normalized
    if full_path.exists():
        logger.debug(f"Found AIW via exact path: {full_path}")
        return full_path
    
    # Try case variations for the path
    path_variants = []
    
    if 'GAMEDATA' in normalized:
        path_variants.append(normalized.replace('GAMEDATA', 'GameData'))
    if 'gamedata' in normalized:
        path_variants.append(normalized.replace('gamedata', 'GameData'))
    if 'GameData' in normalized:
        path_variants.append(normalized.replace('GameData', 'GAMEDATA'))
    
    if 'LOCATIONS' in normalized:
        path_variants.append(normalized.replace('LOCATIONS', 'Locations'))
    if 'Locations' in normalized:
        path_variants.append(normalized.replace('Locations', 'LOCATIONS'))
    
    for variant in path_variants:
        test_path = base_path / variant
        if test_path.exists():
            logger.debug(f"Found AIW via path variant: {test_path}")
            return test_path
    
    # Try case-insensitive directory traversal
    path_parts = normalized.split('/')
    if path_parts and path_parts[0] == '':
        path_parts = path_parts[1:]
    
    current_path = base_path
    expected_filename = path_parts[-1] if path_parts else ""
    expected_stem = Path(expected_filename).stem
    track_folder = path_parts[-2] if len(path_parts) >= 2 else None
    
    for i, part in enumerate(path_parts):
        if i == len(path_parts) - 1:
            if current_path.exists() and current_path.is_dir():
                # First, try to find exact filename match
                for file_path in current_path.iterdir():
                    if file_path.is_file() and file_path.name.lower() == part.lower():
                        logger.debug(f"Found AIW via case-insensitive filename: {file_path}")
                        return file_path
                
                # Do not silently choose between multiple layouts.
                aiw_files = [
                    file_path for file_path in current_path.iterdir()
                    if file_path.is_file() and file_path.suffix.lower() == ".aiw"
                ]
                if len(aiw_files) == 1:
                    logger.debug(f"Found AIW via any AIW file in folder: {aiw_files[0]}")
                    return aiw_files[0]
                if len(aiw_files) > 1:
                    logger.error("Ambiguous AIW path %s; multiple layouts found", relative_path)
                    return None
        else:
            next_path = None
            if current_path.exists() and current_path.is_dir():
                for item in current_path.iterdir():
                    if item.is_dir() and item.name.lower() == part.lower():
                        next_path = item
                        break
            
            if next_path:
                current_path = next_path
            else:
                current_path = None
                break
    
    if current_path and current_path.exists() and current_path.is_dir():
        # Look for any AIW file in the final directory
        aiw_files = [
            file_path for file_path in current_path.iterdir()
            if file_path.is_file() and file_path.suffix.lower() == ".aiw"
        ]
        if len(aiw_files) == 1:
            logger.debug(f"Found AIW via any AIW file (fallback): {aiw_files[0]}")
            return aiw_files[0]
        if len(aiw_files) > 1:
            logger.error("Ambiguous AIW fallback for %s", relative_path)
            return None
    
    # Last resort: search by track folder name
    if track_folder:
        locations_candidates = [
            base_path / "GameData" / "Locations",
            base_path / "GAMEDATA" / "Locations",
        ]
        
        for locations_dir in locations_candidates:
            if locations_dir.exists():
                for track_dir in locations_dir.iterdir():
                    if track_dir.is_dir() and track_dir.name.lower() == track_folder.lower():
                        for ext in ['.AIW', '.aiw']:
                            for aiw_file in track_dir.glob(f'*{ext}'):
                                logger.debug(f"Found AIW via track folder search: {aiw_file}")
                                return aiw_file
                
                # Also try partial folder match
                for track_dir in locations_dir.iterdir():
                    if track_dir.is_dir() and track_folder.lower() in track_dir.name.lower():
                        for ext in ['.AIW', '.aiw']:
                            for aiw_file in track_dir.glob(f'*{ext}'):
                                logger.debug(f"Found AIW via partial track folder search: {aiw_file}")
                                return aiw_file
    
    logger.warning(f"AIW file NOT found for path: {relative_path}")
    return None


def find_aiw_file_by_track(track_name: str, base_path: Path) -> Optional[Path]:
    """
    Find AIW file by track name.
    This is a convenience wrapper around core_track_scanner.find_aiw_file_for_track.
    """
    from core_track_scanner import find_aiw_file_for_track
    return find_aiw_file_for_track(track_name, base_path)


def update_aiw_ratio(aiw_path: Path, ratio_name: str, new_ratio: float, backup_dir: Optional[Path] = None) -> bool:
    """
    Update a ratio in the AIW file.
    
    Args:
        aiw_path: Path to the AIW file
        ratio_name: "QualRatio" or "RaceRatio"
        new_ratio: New ratio value
        backup_dir: Directory to store backups (if None, no backup created)
    
    Returns:
        True if successful, False otherwise
    """
    try:
        if not aiw_path:
            logger.error(f"update_aiw_ratio: aiw_path is None")
            return False
        
        if not aiw_path.exists():
            logger.error(f"update_aiw_ratio: AIW file not found: {aiw_path}")
            return False

        if aiw_path.stat().st_mode & 0o222 == 0:
            logger.error(f"update_aiw_ratio: AIW file is read-only: {aiw_path}")
            return False
        
        logger.info(f"update_aiw_ratio: updating {ratio_name} to {new_ratio:.6f} in {aiw_path}")
        
        if backup_dir:
            backup_dir = Path(backup_dir)
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_path = backup_dir / f"{aiw_path.stem}_ORIGINAL{aiw_path.suffix}"
            if not backup_path.exists():
                shutil.copy2(aiw_path, backup_path)
                logger.debug(f"Created backup: {backup_path}")
            else:
                logger.debug(f"Original backup exists: {backup_path}")
        
        with _aiw_lock(aiw_path):
            raw = aiw_path.read_bytes()
            content = raw.replace(b"\x00", b"").decode("utf-8", errors="ignore")
            pattern = rf'({re.escape(ratio_name)}\s*=\s*\(?)\s*[0-9.eE+-]+\s*(\)?)'
            new_content, count = re.subn(
                pattern,
                lambda m: f"{m.group(1)}{new_ratio:.6f}{m.group(2)}",
                content,
                flags=re.IGNORECASE
            )
            if count == 0:
                logger.warning(f"Could not find {ratio_name} pattern in {aiw_path.name}")
                return False
            _atomic_write(aiw_path, new_content)
            verify = aiw_path.read_bytes().replace(b"\x00", b"").decode("utf-8", errors="ignore")
            if not re.search(
                rf'{re.escape(ratio_name)}\s*=\s*\(?\s*{re.escape(f"{new_ratio:.6f}")}',
                verify,
                re.IGNORECASE,
            ):
                logger.error("AIW verification failed after updating %s", ratio_name)
                return False
            logger.info(f"Updated {ratio_name} to {new_ratio:.6f} in {aiw_path.name}")
            return True
            
    except Exception as e:
        logger.error(f"Error updating AIW ratio: {e}")
        return False


def ensure_aiw_has_ratios(aiw_path: Path, backup_dir: Optional[Path] = None) -> bool:
    """
    Ensure AIW file has both QualRatio and RaceRatio entries.
    Adds them with default values if missing.
    
    Args:
        aiw_path: Path to the AIW file
        backup_dir: Directory to store backups
    
    Returns:
        True if successful, False otherwise
    """
    try:
        if not aiw_path:
            logger.error(f"ensure_aiw_has_ratios: aiw_path is None")
            return False
        
        if not aiw_path.exists():
            logger.error(f"ensure_aiw_has_ratios: AIW file not found: {aiw_path}")
            return False
        
        raw = aiw_path.read_bytes()
        content = raw.replace(b"\x00", b"").decode("utf-8", errors="ignore")
        
        has_qual = re.search(r'QualRatio\s*=', content, re.IGNORECASE) is not None
        has_race = re.search(r'RaceRatio\s*=', content, re.IGNORECASE) is not None
        
        if has_qual and has_race:
            logger.debug(f"AIW {aiw_path.name} already has both ratios")
            return True
        
        logger.info(f"AIW {aiw_path.name} missing ratios: qual={has_qual}, race={has_race}")
        
        if backup_dir:
            backup_dir = Path(backup_dir)
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_path = backup_dir / f"{aiw_path.stem}_ORIGINAL{aiw_path.suffix}"
            if not backup_path.exists():
                shutil.copy2(aiw_path, backup_path)
                logger.debug(f"Created backup before adding ratios: {backup_path}")
        
        waypoint_pattern = re.compile(r'(\[Waypoint\](.*?)(?=\[|$))', re.DOTALL | re.IGNORECASE)
        waypoint_match = waypoint_pattern.search(content)
        
        if not waypoint_match:
            logger.warning(f"Cannot find Waypoint section in {aiw_path.name}")
            return False
        
        waypoint_section = waypoint_match.group(1)
        waypoint_start = waypoint_match.start()
        
        insert_pos = waypoint_start + len("[Waypoint]")
        best_adjust_match = re.search(r'BestAdjust\s*=', waypoint_section, re.IGNORECASE)
        if best_adjust_match:
            line_end = waypoint_section.find('\n', best_adjust_match.end())
            if line_end != -1:
                insert_pos = waypoint_start + line_end + 1
        
        lines_to_insert = []
        if not has_qual:
            lines_to_insert.append("QualRatio = 1.000000")
        if not has_race:
            lines_to_insert.append("RaceRatio = 1.000000")
        
        if lines_to_insert:
            insert_text = "\n" + "\n".join(lines_to_insert)
            new_content = content[:insert_pos] + insert_text + content[insert_pos:]
            with _aiw_lock(aiw_path):
                _atomic_write(aiw_path, new_content)
            logger.info(f"Added missing ratios to {aiw_path.name}: {lines_to_insert}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error ensuring AIW has ratios: {e}")
        return False
