#!/usr/bin/env python3
"""
Single source of truth for all mathematical operations.
NO database access, NO file I/O, NO GUI code.
"""

from typing import List, Tuple, Optional, Dict
from dataclasses import dataclass
import numpy as np

# Global constants - can be overridden by config
DEFAULT_A_VALUE = 32.0
MIN_RATIO = 0.3
MAX_RATIO = 3.0
MIN_B = 10.0
MAX_B = 2000.0  # Increased from 200 to 2000
MIN_A = 1.0
MAX_A = 300.0


@dataclass
class FitStats:
    """Statistics from curve fitting"""
    avg_error: float = 0.0
    max_error: float = 0.0
    outliers_removed: int = 0
    points_used: int = 0
    method_used: str = "none"
    threshold_used: float = 0.0
    a_optimized: bool = False
    original_a: float = 0.0
    new_a: float = 0.0


def time_from_ratio(ratio: float, a: float, b: float) -> float:
    """
    Calculate lap time from ratio using T = a/R + b
    
    Args:
        ratio: AI ratio value
        a: Curve steepness parameter
        b: Asymptote (minimum theoretical lap time)
    
    Returns:
        Lap time in seconds
    """
    if ratio <= 0 or a <= 0:
        return b
    return a / ratio + b


def ratio_from_time(lap_time: float, a: float, b: float) -> Optional[float]:
    """
    Calculate ratio from lap time using R = a/(T - b)
    
    Args:
        lap_time: Lap time in seconds
        a: Curve steepness parameter
        b: Asymptote
    
    Returns:
        Ratio value, or None if calculation is invalid
    """
    denominator = lap_time - b
    if denominator <= 0 or a <= 0:
        return None
    return a / denominator


def clamp_ratio(ratio: float, min_ratio: float = MIN_RATIO, max_ratio: float = MAX_RATIO) -> float:
    """Clamp ratio to acceptable range"""
    return max(min_ratio, min(max_ratio, ratio))


def clamp_a(a: float, min_a: float = MIN_A, max_a: float = MAX_A) -> float:
    """Clamp a parameter to acceptable range"""
    return max(min_a, min(max_a, a))


def clamp_b(b: float, min_b: float = MIN_B, max_b: float = MAX_B) -> float:
    """Clamp b parameter to acceptable range"""
    return max(min_b, min(max_b, b))


def is_valid_formula(a: float, b: float) -> bool:
    """Check if formula parameters are valid"""
    return MIN_A <= a <= MAX_A and MIN_B <= b <= MAX_B


def calculate_b_from_point(ratio: float, lap_time: float, a: float = DEFAULT_A_VALUE) -> float:
    """
    Calculate b parameter from a single data point.
    b = T - a/R
    """
    if ratio <= 0:
        return MIN_B
    b = lap_time - (a / ratio)
    return clamp_b(b)


def get_center_ratio(min_ratio: float = MIN_RATIO, max_ratio: float = MAX_RATIO) -> float:
    """Calculate the center ratio between min and max limits"""
    return min_ratio + ((max_ratio - min_ratio) / 2)


def calculate_optimal_a_from_center_point(
    ratios: List[float], 
    times: List[float], 
    min_ratio_limit: float = MIN_RATIO,
    max_ratio_limit: float = MAX_RATIO
) -> float:
    """
    Calculate optimal A value to hit the center point of the data range.
    This is used when first getting data for a formula.
    
    Args:
        ratios: List of ratio values (should be all the same for first data)
        times: List of corresponding lap times
        min_ratio_limit: Minimum allowed ratio
        max_ratio_limit: Maximum allowed ratio
    
    Returns:
        Calculated A value
    """
    if not ratios or not times:
        return DEFAULT_A_VALUE
    
    # Get the center ratio
    center_ratio = get_center_ratio(min_ratio_limit, max_ratio_limit)
    
    # Calculate average time from the data points
    avg_time = np.mean(times)
    
    # Calculate optimal a: a = (T - b) * R, but we don't know b yet
    # For center point, we need to find a that makes the curve pass through 
    # (center_ratio, avg_time) while maintaining reasonable b
    # b = avg_time - a/center_ratio
    # We want b to be reasonable (between MIN_B and MAX_B)
    
    # Solve for a that gives b = MIN_B
    a_min_b = (avg_time - MIN_B) * center_ratio
    
    # Solve for a that gives b = MAX_B
    a_max_b = (avg_time - MAX_B) * center_ratio
    
    # Choose a that gives b in reasonable range, default to a_min_b clamped
    optimal_a = clamp_a(a_min_b)
    
    return optimal_a


def calculate_error_weighted_a(
    ratios: List[float], 
    times: List[float], 
    current_a: float,
    min_ratio_limit: float = MIN_RATIO,
    max_ratio_limit: float = MAX_RATIO
) -> Tuple[float, float, float]:
    """
    Calculate optimal A value that minimizes error, giving priority to points near center.
    
    Args:
        ratios: List of ratio values
        times: List of corresponding lap times
        current_a: Current A value
        min_ratio_limit: Minimum allowed ratio
        max_ratio_limit: Maximum allowed ratio
    
    Returns:
        Tuple of (optimal_a, best_error, center_ratio)
    """
    if len(ratios) < 2:
        return current_a, 0.0, 0.0
    
    center_ratio = get_center_ratio(min_ratio_limit, max_ratio_limit)
    
    # Calculate weights - higher weight for points near center ratio
    weights = []
    for r in ratios:
        distance = abs(r - center_ratio)
        # Gaussian-like weight: exp(-distance^2 / (2 * sigma^2))
        # sigma = 0.2 (reasonable spread)
        sigma = 0.2
        weight = np.exp(-(distance ** 2) / (2 * sigma ** 2))
        weights.append(max(0.1, weight))  # Minimum weight of 0.1
    
    weights = np.array(weights)
    
    # Try different A values and find the one with lowest weighted error
    a_candidates = np.linspace(max(MIN_A, current_a - 50), min(MAX_A, current_a + 50), 50)
    best_a = current_a
    best_error = float('inf')
    
    for a_candidate in a_candidates:
        # For each candidate a, calculate optimal b using weighted least squares
        # b = weighted_avg(T - a/R)
        b_values = []
        weighted_sum = 0.0
        weight_sum = 0.0
        
        for i, (r, t) in enumerate(zip(ratios, times)):
            if r > 0:
                b_candidate = t - (a_candidate / r)
                b_candidate = clamp_b(b_candidate)
                b_values.append(b_candidate)
                weighted_sum += weights[i] * b_candidate
                weight_sum += weights[i]
        
        if weight_sum > 0:
            b_candidate = weighted_sum / weight_sum
            b_candidate = clamp_b(b_candidate)
        else:
            b_candidate = 70.0
        
        # Calculate weighted error
        total_error = 0.0
        total_weight = 0.0
        for i, (r, t) in enumerate(zip(ratios, times)):
            if r > 0:
                predicted = a_candidate / r + b_candidate
                error = abs(predicted - t)
                total_error += weights[i] * error
                total_weight += weights[i]
        
        if total_weight > 0:
            avg_error = total_error / total_weight
        else:
            avg_error = float('inf')
        
        if avg_error < best_error:
            best_error = avg_error
            best_a = a_candidate
    
    return clamp_a(best_a), best_error, center_ratio


def calculate_error_metrics(
    ratios: List[float], 
    times: List[float], 
    a: float, 
    b: float
) -> Dict[str, float]:
    """
    Calculate error metrics for a given formula against data points.
    
    Args:
        ratios: List of ratio values
        times: List of corresponding lap times
        a: A parameter
        b: B parameter
    
    Returns:
        Dictionary with error metrics
    """
    if not ratios or not times:
        return {
            'avg_error': 0.0,
            'max_error': 0.0,
            'std_error': 0.0,
            'r_squared': 0.0,
            'points_count': 0
        }
    
    errors = []
    predicted_times = []
    
    for r, t in zip(ratios, times):
        if r > 0:
            predicted = a / r + b
            predicted_times.append(predicted)
            errors.append(abs(predicted - t))
    
    if not errors:
        return {
            'avg_error': 0.0,
            'max_error': 0.0,
            'std_error': 0.0,
            'r_squared': 0.0,
            'points_count': 0
        }
    
    errors_array = np.array(errors)
    predicted_array = np.array(predicted_times)
    times_array = np.array([t for t in times if t > 0])
    
    # Calculate R-squared
    if len(times_array) > 1:
        ss_res = np.sum((times_array - predicted_array) ** 2)
        ss_tot = np.sum((times_array - np.mean(times_array)) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
    else:
        r_squared = 0
    
    return {
        'avg_error': float(np.mean(errors_array)),
        'max_error': float(np.max(errors_array)),
        'std_error': float(np.std(errors_array)),
        'r_squared': float(r_squared),
        'points_count': len(ratios)
    }


def detect_outliers_std(
    ratios: List[float], 
    times: List[float], 
    a: float, 
    b: float, 
    std_multiplier: float = 2.0,
    min_points: int = 5
) -> Tuple[List[int], List[float], FitStats]:
    """
    Detect outliers using standard deviation method.
    Points with error > mean + std_multiplier * std_dev are considered outliers.
    """
    stats = FitStats(method_used="std", threshold_used=std_multiplier, points_used=len(ratios))
    
    if len(ratios) < min_points:
        return list(range(len(ratios))), [], stats
    
    predicted = [time_from_ratio(r, a, b) for r in ratios]
    errors = [abs(t - p) for t, p in zip(times, predicted)]
    
    mean_error = np.mean(errors)
    std_error = np.std(errors)
    
    if std_error < 0.01:
        return list(range(len(ratios))), errors, stats
    
    threshold = mean_error + (std_multiplier * std_error)
    
    outlier_indices = [i for i, err in enumerate(errors) if err > threshold]
    keep_indices = [i for i in range(len(ratios)) if i not in outlier_indices]
    
    stats.outliers_removed = len(outlier_indices)
    return keep_indices, errors, stats


def detect_outliers_iqr(
    ratios: List[float], 
    times: List[float], 
    a: float, 
    b: float, 
    iqr_multiplier: float = 1.5,
    min_points: int = 6
) -> Tuple[List[int], List[float], FitStats]:
    """Detect outliers using Interquartile Range (IQR) method."""
    stats = FitStats(method_used="iqr", threshold_used=iqr_multiplier, points_used=len(ratios))
    
    if len(ratios) < min_points:
        return list(range(len(ratios))), [], stats
    
    predicted = [time_from_ratio(r, a, b) for r in ratios]
    errors = [abs(t - p) for t, p in zip(times, predicted)]
    
    errors_sorted = sorted(errors)
    q1_idx = int(len(errors_sorted) * 0.25)
    q3_idx = int(len(errors_sorted) * 0.75)
    
    q1 = errors_sorted[q1_idx]
    q3 = errors_sorted[q3_idx]
    iqr = q3 - q1
    
    if iqr < 0.01:
        return list(range(len(ratios))), errors, stats
    
    threshold = q3 + (iqr_multiplier * iqr)
    
    outlier_indices = [i for i, err in enumerate(errors) if err > threshold]
    keep_indices = [i for i in range(len(ratios)) if i not in outlier_indices]
    
    stats.outliers_removed = len(outlier_indices)
    return keep_indices, errors, stats


def detect_outliers_percentile(
    ratios: List[float], 
    times: List[float], 
    a: float, 
    b: float, 
    percentile_threshold: float = 90.0,
    min_points: int = 4
) -> Tuple[List[int], List[float], FitStats]:
    """Detect outliers using percentile method."""
    stats = FitStats(method_used="percentile", threshold_used=percentile_threshold, points_used=len(ratios))
    
    if len(ratios) < min_points:
        return list(range(len(ratios))), [], stats
    
    predicted = [time_from_ratio(r, a, b) for r in ratios]
    errors = [abs(t - p) for t, p in zip(times, predicted)]
    
    errors_sorted = sorted(errors)
    percentile_idx = int(len(errors_sorted) * (percentile_threshold / 100.0))
    if percentile_idx >= len(errors_sorted):
        percentile_idx = len(errors_sorted) - 1
    threshold = errors_sorted[percentile_idx]
    
    outlier_indices = [i for i, err in enumerate(errors) if err > threshold]
    keep_indices = [i for i in range(len(ratios)) if i not in outlier_indices]
    
    stats.outliers_removed = len(outlier_indices)
    return keep_indices, errors, stats


def filter_outliers(
    ratios: List[float],
    times: List[float],
    a: float,
    b: float,
    method: str = "std",
    threshold: float = 2.0,
    min_points: int = 4
) -> Tuple[List[float], List[float], FitStats]:
    """
    Filter outliers from data points using specified method.
    
    Args:
        method: "std", "iqr", "percentile", or "none"
        threshold: Threshold parameter for the method
        min_points: Minimum points required before filtering
    
    Returns:
        (filtered_ratios, filtered_times, stats)
    """
    if len(ratios) < min_points or method == "none":
        return ratios, times, FitStats(points_used=len(ratios), method_used=method)
    
    if method == "std":
        keep_indices, _, stats = detect_outliers_std(ratios, times, a, b, threshold, min_points)
    elif method == "iqr":
        keep_indices, _, stats = detect_outliers_iqr(ratios, times, a, b, threshold, min_points)
    elif method == "percentile":
        keep_indices, _, stats = detect_outliers_percentile(ratios, times, a, b, threshold, min_points)
    else:
        return ratios, times, FitStats(points_used=len(ratios), method_used=method)
    
    if len(keep_indices) < 2:
        return ratios, times, FitStats(points_used=len(ratios), method_used=method)
    
    filtered_ratios = [ratios[i] for i in keep_indices]
    filtered_times = [times[i] for i in keep_indices]
    
    stats.points_used = len(filtered_ratios)
    return filtered_ratios, filtered_times, stats


def fit_hyperbolic(
    ratios: List[float], 
    times: List[float], 
    fixed_a: Optional[float] = None,
    outlier_method: str = "none",
    outlier_threshold: float = 2.0,
    min_points_after_filtering: int = 2,
    optimize_a: bool = False,
    min_ratio_limit: float = MIN_RATIO,
    max_ratio_limit: float = MAX_RATIO
) -> Tuple[Optional[float], Optional[float], FitStats]:
    """
    Fit hyperbolic curve T = a/R + b to data points.
    
    This is the SINGLE function used by ALL components for curve fitting.
    
    Args:
        ratios: List of ratio values
        times: List of corresponding lap times
        fixed_a: If provided, only optimize b (keep a fixed)
        outlier_method: "std", "iqr", "percentile", or "none"
        outlier_threshold: Threshold for outlier detection
        min_points_after_filtering: Minimum points required after filtering
        optimize_a: If True, try to find optimal A value that minimizes error
        min_ratio_limit: Minimum ratio limit for center calculation
        max_ratio_limit: Maximum ratio limit for center calculation
    
    Returns:
        (a, b, stats) where stats contains fit quality information
        Returns (None, None, stats) if fitting fails
    """
    stats = FitStats(method_used=outlier_method, threshold_used=outlier_threshold)
    
    if len(ratios) < 2:
        return None, None, stats
    
    # Determine if we should optimize A
    should_optimize_a = optimize_a and fixed_a is None
    
    # Initial guess for parameters
    if fixed_a is not None:
        a_guess = fixed_a
        # Guess b from first point
        if ratios[0] > 0:
            b_guess = clamp_b(times[0] - (a_guess / ratios[0]))
        else:
            b_guess = 70.0
    else:
        # Check if all ratios are the same (first data point case)
        unique_ratios = set(round(r, 6) for r in ratios)
        if len(unique_ratios) == 1 and should_optimize_a:
            # First data point case - calculate optimal A to hit center
            a_guess = calculate_optimal_a_from_center_point(
                ratios, times, min_ratio_limit, max_ratio_limit
            )
            stats.a_optimized = True
            stats.original_a = DEFAULT_A_VALUE
            stats.new_a = a_guess
            
            # Calculate b with this a
            b_guess = clamp_b(np.mean([t - (a_guess / r) for r, t in zip(ratios, times)]))
        else:
            # Guess a and b from first two points
            try:
                r1, t1 = ratios[0], times[0]
                r2, t2 = ratios[1], times[1]
                inv_r1 = 1.0 / max(r1, 0.01)
                inv_r2 = 1.0 / max(r2, 0.01)
                
                if abs(inv_r1 - inv_r2) > 1e-9:
                    a_guess = (t1 - t2) / (inv_r1 - inv_r2)
                    b_guess = t1 - a_guess * inv_r1
                else:
                    a_guess = DEFAULT_A_VALUE
                    b_guess = 70.0
            except Exception:
                a_guess = DEFAULT_A_VALUE
                b_guess = 70.0
            
            a_guess = max(a_guess, MIN_A)
            b_guess = clamp_b(b_guess)
    
    # Apply outlier filtering if requested
    filtered_ratios, filtered_times, outlier_stats = filter_outliers(
        ratios, times, a_guess, b_guess, outlier_method, outlier_threshold, min_points=4
    )
    
    stats.outliers_removed = outlier_stats.outliers_removed
    
    if len(filtered_ratios) < min_points_after_filtering:
        # Not enough points after filtering, use original data
        filtered_ratios, filtered_times = ratios, times
        stats.outliers_removed = 0
    
    if len(filtered_ratios) < 2:
        return None, None, stats
    
    # Perform the fit
    try:
        from scipy.optimize import curve_fit
        
        r_array = np.array(filtered_ratios)
        t_array = np.array(filtered_times)
        
        def hyperbolic_func(R, a, b):
            R_safe = np.maximum(R, 0.01)
            return a / R_safe + b
        
        if fixed_a is not None:
            # Only optimize b
            def hyperbolic_func_b_only(R, b):
                R_safe = np.maximum(R, 0.01)
                return fixed_a / R_safe + b
            
            popt, _ = curve_fit(hyperbolic_func_b_only, r_array, t_array, p0=[b_guess])
            a = fixed_a
            b = popt[0]
        else:
            popt, _ = curve_fit(hyperbolic_func, r_array, t_array, p0=[a_guess, b_guess])
            a, b = popt
        
        a = clamp_a(a)
        b = clamp_b(b)
        
        # If optimize_a was requested and we didn't use fixed_a, try to improve
        if should_optimize_a and not fixed_a and len(filtered_ratios) >= 3:
            # Calculate weighted optimal A
            optimal_a, weighted_error, center_ratio = calculate_error_weighted_a(
                filtered_ratios, filtered_times, a, min_ratio_limit, max_ratio_limit
            )
            
            # If weighted error is significantly better, use it
            if abs(optimal_a - a) > 1.0:
                # Recalculate b with optimal a
                b_values = []
                for r, t in zip(filtered_ratios, filtered_times):
                    if r > 0:
                        b_candidate = t - (optimal_a / r)
                        b_values.append(clamp_b(b_candidate))
                if b_values:
                    b_optimal = clamp_b(np.mean(b_values))
                    
                    # Calculate error with original and optimal
                    errors_original = [abs((a / r + b) - t) for r, t in zip(filtered_ratios, filtered_times)]
                    errors_optimal = [abs((optimal_a / r + b_optimal) - t) for r, t in zip(filtered_ratios, filtered_times)]
                    
                    if np.mean(errors_optimal) < np.mean(errors_original) * 0.95:  # 5% improvement
                        a = optimal_a
                        b = b_optimal
                        stats.a_optimized = True
                        stats.original_a = a_guess
                        stats.new_a = a
        
        # Calculate errors using all original data points
        predictions = [time_from_ratio(r, a, b) for r in ratios]
        errors = [abs(t - p) for t, p in zip(times, predictions)]
        stats.avg_error = float(np.mean(errors))
        stats.max_error = float(np.max(errors))
        stats.points_used = len(filtered_ratios)
        
        return a, b, stats
        
    except Exception:
        return None, None, stats


def get_formula_string(a: float, b: float) -> str:
    """Get formatted formula string"""
    return f"T = {a:.4f} / R + {b:.4f}"


def should_suggest_manual_adjustment(error_metrics: Dict[str, float], points_count: int) -> Tuple[bool, str]:
    """
    Determine if user should be suggested to manually adjust the formula.
    
    Args:
        error_metrics: Error metrics from calculate_error_metrics
        points_count: Number of data points used
    
    Returns:
        Tuple of (should_suggest, reason)
    """
    if points_count < 2:
        return False, ""
    
    avg_error = error_metrics.get('avg_error', 0)
    max_error = error_metrics.get('max_error', 0)
    r_squared = error_metrics.get('r_squared', 0)
    
    # Conditions for suggesting manual adjustment
    reasons = []
    
    if avg_error > 1.5:
        reasons.append(f"average error is high ({avg_error:.2f}s)")
    
    if max_error > 3.0:
        reasons.append(f"maximum error is very high ({max_error:.2f}s)")
    
    if r_squared < 0.7 and points_count >= 5:
        reasons.append(f"R-squared is low ({r_squared:.2f})")
    
    if points_count >= 8 and avg_error > 0.8:
        reasons.append(f"consistent high error over {points_count} points")
    
    if reasons:
        reason_text = "; ".join(reasons)
        return True, reason_text
    
    return False, ""


def get_optimal_a_for_data(
    ratios: List[float], 
    times: List[float], 
    min_ratio_limit: float = MIN_RATIO,
    max_ratio_limit: float = MAX_RATIO
) -> Tuple[float, float, float]:
    """
    Get optimal A value and its associated error for given data.
    
    Args:
        ratios: List of ratio values
        times: List of corresponding lap times
        min_ratio_limit: Minimum ratio limit
        max_ratio_limit: Maximum ratio limit
    
    Returns:
        Tuple of (optimal_a, error_at_optimal_a, center_ratio)
    """
    if len(ratios) < 2:
        return DEFAULT_A_VALUE, 0.0, 0.0
    
    optimal_a, best_error, center_ratio = calculate_error_weighted_a(
        ratios, times, DEFAULT_A_VALUE, min_ratio_limit, max_ratio_limit
    )
    
    return optimal_a, best_error, center_ratio
