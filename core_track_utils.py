#!/usr/bin/env python3
"""
Track name normalization and management utilities
Provides consistent track identification across all modules
"""

import re
import logging
from pathlib import Path
from typing import Optional, Tuple, Dict, List

logger = logging.getLogger(__name__)


def normalize_track_from_path(aiw_relative_path: str) -> Tuple[str, str, str]:
    """
    Extract canonical track identifier from AIW path.
    
    Input: "GAMEDATA/LOCATIONS/Estoril/3Estoril.AIW"
    Returns: ("Estoril/3Estoril", "Estoril", "3Estoril")
    
    Args:
        aiw_relative_path: Path like from AIDB in raceresults.txt
    
    Returns:
        Tuple of (canonical_id, folder_name, aiw_stem)
    """
    if not aiw_relative_path:
        return "", "", ""
    
    # Normalize path separators
    normalized = str(aiw_relative_path).replace('\\', '/')
    
    # Extract filename
    path = Path(normalized)
    aiw_stem = path.stem
    folder_name = path.parent.name if path.parent.name else ""
    
    # Create canonical ID: folder/aiw_stem
    canonical_id = f"{folder_name}/{aiw_stem}" if folder_name else aiw_stem
    
    return canonical_id, folder_name, aiw_stem


def get_canonical_track_id(aiw_path: Path, base_path: Path) -> Optional[str]:
    """
    Get canonical track ID from an AIW file path.
    
    Args:
        aiw_path: Full path to AIW file
        base_path: GTR2 installation base path
    
    Returns:
        Canonical track ID like "Estoril/3Estoril", or None
    """
    try:
        rel_path = aiw_path.relative_to(base_path)
        rel_str = str(rel_path).replace('\\', '/')
        canonical_id, _, _ = normalize_track_from_path(rel_str)
        return canonical_id
    except ValueError:
        logger.warning(f"Cannot get relative path for {aiw_path}")
        return None


def extract_track_info_from_race_data(aiw_relative_path: str, track_folder: str = "") -> Dict[str, str]:
    """
    Extract track information from race data.
    
    Returns a dictionary with:
        - canonical_id: "Estoril/3Estoril"
    """
    canonical_id, folder, aiw_stem = normalize_track_from_path(aiw_relative_path)
    
    # If canonical_id is empty, try to build from track_folder
    if not canonical_id and track_folder:
        canonical_id = f"{track_folder}/{track_folder}"
    
    return {
        'canonical_id': canonical_id,
    }
