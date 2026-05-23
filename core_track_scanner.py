#!/usr/bin/env python3
"""
Shared track scanning utilities for Live AI Tuner
Provides consistent track discovery across all modules
"""

import logging
import re
from pathlib import Path
from typing import List, Optional
import sqlite3

logger = logging.getLogger(__name__)


def scan_tracks_from_filesystem(base_path: Path) -> List[str]:
    """
    Scan the Locations directory for actual track folders.
    
    Args:
        base_path: GTR2 installation path
    
    Returns:
        Sorted list of track names (folder names) that contain AIW files
    """
    tracks = []
    
    if not base_path or not base_path.exists():
        logger.warning(f"Base path not found: {base_path}")
        return tracks
    
    locations_dir = base_path / "GameData" / "Locations"
    if not locations_dir.exists():
        locations_dir = base_path / "GAMEDATA" / "Locations"
    
    if not locations_dir.exists():
        logger.warning(f"Locations directory not found: {locations_dir}")
        return tracks
    
    for track_dir in locations_dir.iterdir():
        if track_dir.is_dir():
            # Check if it contains an AIW file
            for ext in ["*.AIW", "*.aiw"]:
                aiw_files = list(track_dir.glob(ext))
                if aiw_files:
                    tracks.append(track_dir.name)
                    break
    
    return sorted(tracks)


def scan_tracks_from_database(db_path: str) -> List[str]:
    """
    Scan the database for tracks that have data points.
    
    Args:
        db_path: Path to the SQLite database
    
    Returns:
        Sorted list of track names from the database
    """
    tracks = []
    
    if not Path(db_path).exists():
        return tracks
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get tracks from data_points
        cursor.execute("SELECT DISTINCT track FROM data_points ORDER BY track")
        db_tracks = [row[0] for row in cursor.fetchall()]
        
        # Also get tracks from race_sessions if data_points is empty
        if not db_tracks:
            cursor.execute("SELECT DISTINCT track_name FROM race_sessions WHERE track_name IS NOT NULL ORDER BY track_name")
            db_tracks = [row[0] for row in cursor.fetchall()]
        
        # Also check formulas table for tracks
        try:
            cursor.execute("SELECT DISTINCT track FROM formulas WHERE track IS NOT NULL ORDER BY track")
            formula_tracks = [row[0] for row in cursor.fetchall()]
            for track in formula_tracks:
                if track not in db_tracks:
                    db_tracks.append(track)
        except sqlite3.OperationalError:
            pass
        
        conn.close()
        tracks = sorted(db_tracks)
        
    except Exception as e:
        logger.error(f"Error scanning tracks from database: {e}")
    
    return tracks


def get_available_tracks(base_path: Path, db_path: str = None) -> List[str]:
    """
    Get available tracks from the database only.
    Filesystem tracks are NOT included unless they have data in the database.
    
    Args:
        base_path: GTR2 installation path (unused, kept for compatibility)
        db_path: Path to database for tracks
    
    Returns:
        Sorted list of unique track names from database
    """
    if not db_path:
        return []
    
    db_tracks = scan_tracks_from_database(db_path)
    return sorted(db_tracks)


def find_aiw_file_for_track(track_name: str, base_path: Path) -> Optional[Path]:
    """
    Find AIW file for a given track name.
    Prioritizes exact folder name match.
    
    Args:
        track_name: Name of the track (can be folder name or canonical ID like "Estoril/3Estoril")
        base_path: GTR2 installation path
    
    Returns:
        Path to AIW file or None if not found
    """
    if not track_name or not base_path:
        logger.error(f"find_aiw_file_for_track: missing params - track_name={track_name}, base_path={base_path}")
        return None
    
    if not base_path.exists():
        logger.error(f"find_aiw_file_for_track: base_path does not exist: {base_path}")
        return None
    
    # Try both possible Locations directory names
    locations_candidates = [
        base_path / "GameData" / "Locations",
        base_path / "GAMEDATA" / "Locations",
    ]
    
    locations_dir = None
    for candidate in locations_candidates:
        if candidate.exists():
            locations_dir = candidate
            break
    
    if not locations_dir:
        logger.error(f"find_aiw_file_for_track: Locations directory not found in {base_path}")
        return None
    
    track_lower = track_name.lower()
    
    # Extract folder name if track_name is in canonical format "Folder/Stem"
    if '/' in track_name:
        parts = track_name.split('/')
        folder_name = parts[0]
        aiw_stem = parts[1] if len(parts) > 1 else folder_name
    else:
        folder_name = track_name
        aiw_stem = track_name
    
    logger.debug(f"find_aiw_file_for_track: looking for folder='{folder_name}', stem='{aiw_stem}'")
    
    # First, look for exact folder name match
    for track_dir in locations_dir.iterdir():
        if track_dir.is_dir() and track_dir.name.lower() == folder_name.lower():
            # Look for AIW file that matches the stem
            for ext in [".AIW", ".aiw"]:
                aiw_file = track_dir / f"{aiw_stem}{ext}"
                if aiw_file.exists():
                    logger.info(f"find_aiw_file_for_track: found exact match: {aiw_file}")
                    return aiw_file
                
                # Also look for any AIW file in this folder if stem doesn't match
                for aiw_file in track_dir.glob(f"*{ext}"):
                    logger.info(f"find_aiw_file_for_track: found AIW in folder: {aiw_file}")
                    return aiw_file
    
    # Second, look for folder where AIW stem exactly matches track name
    for track_dir in locations_dir.iterdir():
        if track_dir.is_dir():
            for ext in [".AIW", ".aiw"]:
                for aiw_file in track_dir.glob(f"*{ext}"):
                    if aiw_file.stem.lower() == track_lower or aiw_file.stem.lower() == folder_name.lower():
                        logger.info(f"find_aiw_file_for_track: found by stem match: {aiw_file}")
                        return aiw_file
    
    # Third, look for folder name containing track name (partial match)
    for track_dir in locations_dir.iterdir():
        if track_dir.is_dir() and (folder_name.lower() in track_dir.name.lower() or track_dir.name.lower() in folder_name.lower()):
            for ext in [".AIW", ".aiw"]:
                aiw_files = list(track_dir.glob(f"*{ext}"))
                if aiw_files:
                    logger.info(f"find_aiw_file_for_track: found by partial folder match: {aiw_files[0]}")
                    return aiw_files[0]
    
    # Fourth, try recursive search in all Locations subdirectories
    for ext in [".AIW", ".aiw"]:
        for aiw_file in locations_dir.rglob(f"*{ext}"):
            if aiw_file.stem.lower() == track_lower or aiw_file.stem.lower() == folder_name.lower():
                logger.info(f"find_aiw_file_for_track: found by recursive search: {aiw_file}")
                return aiw_file
    
    logger.warning(f"find_aiw_file_for_track: AIW file NOT found for track: {track_name}")
    return None
