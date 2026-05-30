#!/usr/bin/env python3
"""
Session Panel component for Live AI Tuner
Provides the qualifying and race session control panels
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QCheckBox, QDoubleSpinBox, QMessageBox, QDialog,
    QDialogButtonBox
)
from PyQt5.QtCore import Qt, pyqtSignal

from core_config import get_ratio_limits, get_outlier_settings
from core_math import (
    DEFAULT_A_VALUE, time_from_ratio, ratio_from_time, clamp_ratio, 
    get_formula_string, fit_hyperbolic, MAX_B, calculate_data_quality_metrics
)
from gui_common_dialogs import ManualLapTimeDialog


class AutoFitResultDialog(QDialog):
    """Dialog showing Auto-Fit results and asking for acceptance"""
    
    def __init__(self, parent, session_type: str, old_a: float, old_b: float, 
                 new_a: float, new_b: float, stats, points_count: int, outliers_removed: int,
                 quality_suggestion: str = ""):
        super().__init__(parent)
        self.session_type = session_type
        self.old_a = old_a
        self.old_b = old_b
        self.new_a = new_a
        self.new_b = new_b
        self.stats = stats
        self.points_count = points_count
        self.outliers_removed = outliers_removed
        self.quality_suggestion = quality_suggestion
        self.accepted_formula = False
        
        self.setWindowTitle(f"Auto-Fit Results - {session_type.upper()}")
        self.setMinimumWidth(500)
        self.setMinimumHeight(420)
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        info_label = QLabel(f"Auto-Fit completed for {self.session_type.upper()} session")
        info_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #FFA500;")
        layout.addWidget(info_label)
        
        layout.addSpacing(10)
        
        formula_group = QGroupBox("Formula Comparison")
        formula_layout = QVBoxLayout(formula_group)
        
        old_formula = QLabel(f"Old formula: {get_formula_string(self.old_a, self.old_b)}")
        old_formula.setStyleSheet("color: #888; font-family: monospace;")
        formula_layout.addWidget(old_formula)
        
        new_formula = QLabel(f"New formula: {get_formula_string(self.new_a, self.new_b)}")
        new_formula.setStyleSheet("color: #4CAF50; font-family: monospace; font-weight: bold;")
        formula_layout.addWidget(new_formula)
        
        layout.addWidget(formula_group)
        
        stats_group = QGroupBox("Fit Statistics")
        stats_layout = QVBoxLayout(stats_group)
        
        points_used = self.points_count - self.outliers_removed
        stats_layout.addWidget(QLabel(f"Data points used: {points_used} (out of {self.points_count})"))
        
        if self.outliers_removed > 0:
            outlier_label = QLabel(f"Outliers removed: {self.outliers_removed}")
            outlier_label.setStyleSheet("color: #FFA500;")
            stats_layout.addWidget(outlier_label)
        
        stats_layout.addWidget(QLabel(f"Average error: {self.stats.avg_error:.3f} seconds"))
        stats_layout.addWidget(QLabel(f"Maximum error: {self.stats.max_error:.3f} seconds"))
        
        if self.stats.avg_error < 0.5:
            quality = "Excellent"
            color = "#4CAF50"
        elif self.stats.avg_error < 1.0:
            quality = "Good"
            color = "#8BC34A"
        elif self.stats.avg_error < 1.5:
            quality = "Fair"
            color = "#FFC107"
        elif self.stats.avg_error < 2.5:
            quality = "Poor"
            color = "#FF9800"
        else:
            quality = "Very Poor"
            color = "#f44336"
        
        quality_label = QLabel(f"Fit quality: {quality}")
        quality_label.setStyleSheet(f"color: {color}; font-weight: bold;")
        stats_layout.addWidget(quality_label)
        
        layout.addWidget(stats_group)
        
        if self.quality_suggestion:
            quality_group = QGroupBox("Data Quality Assessment")
            quality_layout = QVBoxLayout(quality_group)
            
            suggestion_label = QLabel(self.quality_suggestion)
            suggestion_label.setWordWrap(True)
            suggestion_label.setStyleSheet("color: #FFA500;")
            quality_layout.addWidget(suggestion_label)
            
            layout.addWidget(quality_group)
        
        if self.outliers_removed > 0:
            warning_label = QLabel(
                f"Warning: {self.outliers_removed} outlier(s) were detected and excluded from the fit.\n"
                f"You may want to review these points in the graph."
            )
            warning_label.setStyleSheet("color: #FFA500;")
            warning_label.setWordWrap(True)
            layout.addWidget(warning_label)
        
        layout.addSpacing(10)
        
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        button_box.button(QDialogButtonBox.Ok).setText("Apply Formula")
        button_box.button(QDialogButtonBox.Cancel).setText("Keep Old Formula")
        layout.addWidget(button_box)
    
    def accept(self):
        self.accepted_formula = True
        super().accept()
    
    def reject(self):
        self.accepted_formula = False
        super().reject()


class SessionPanel(QWidget):
    """Panel for a single session (Qualifying or Race) with controls"""
    
    formula_changed = pyqtSignal(str, float, float)  # Emitted when formula should be saved
    formula_preview = pyqtSignal(str, float, float)  # Emitted for live preview (no save)
    show_data_toggled = pyqtSignal(str, bool)
    calculate_ratio = pyqtSignal(str, float)
    auto_fit_requested = pyqtSignal(str)
    lap_time_edited = pyqtSignal(str, float)
    lock_toggled = pyqtSignal(str, bool)
    
    def __init__(self, session_type: str, title: str, db, parent=None):
        super().__init__(parent)
        self.session_type = session_type
        self.title = title
        self.db = db
        
        self.a = DEFAULT_A_VALUE
        self.b = 70.0
        self.user_time = None
        self.user_ratio = None
        self.current_ratio = None
        self.median_time = None
        self.calc_button_modified = False
        self.formula_is_default = True
        self.formula_is_locked = False
        self.formula_modified = False
        self.quality_suggestion = ""
        self.distinct_ratios = 0
        self.ratio_spread = 0.0
        
        self.current_track = ""
        self.current_vehicle_class = ""
        
        self.setup_ui()
    
    def set_current_track_class(self, track: str, vehicle_class: str):
        self.current_track = track
        self.current_vehicle_class = vehicle_class
        self.update_quality_suggestion()
    
    def update_quality_suggestion(self):
        """Update the quality suggestion from the database"""
        if not self.current_track or not self.current_vehicle_class:
            return
        
        from core_autopilot import AutopilotManager
        if hasattr(self.parent(), 'autopilot_manager'):
            suggestion = self.parent().autopilot_manager.get_quality_suggestion(
                self.current_track, self.current_vehicle_class, self.session_type
            )
            self.quality_suggestion = suggestion
            
            # Also update the accuracy display with the suggestion
            if hasattr(self, 'accuracy_label') and hasattr(self, 'accuracy_frame'):
                if suggestion and suggestion != "Insufficient data for quality assessment":
                    current_text = self.accuracy_label.text()
                    if "points" in current_text:
                        self.accuracy_label.setText(f"{current_text}\n{suggestion}")
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(6, 6, 6, 6)
        
        self.setStyleSheet("""
            QGroupBox {
                background-color: #2b2b2b;
                border-radius: 8px;
                margin-top: 8px;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
            QPushButton#edit_time_btn {
                background-color: #2196F3;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 2px 8px;
                font-size: 10px;
            }
            QPushButton#edit_time_btn:hover {
                background-color: #1976D2;
            }
            QLabel#median_label {
                color: #FFA500;
                font-family: monospace;
                font-size: 11px;
                font-weight: bold;
            }
            QLabel#ratio_label {
                color: #00FF00;
                font-family: monospace;
                font-size: 11px;
                font-weight: bold;
            }
        """)
        
        group = QGroupBox(self.title)
        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(4)
        group_layout.setContentsMargins(8, 8, 8, 8)

        row1 = QHBoxLayout()
        self.show_checkbox = QCheckBox("Show on graph")
        self.show_checkbox.setChecked(True)
        self.show_checkbox.setStyleSheet("color: #4CAF50; font-weight: bold;")
        self.show_checkbox.toggled.connect(self.on_show_toggled)
        row1.addWidget(self.show_checkbox)

        row1.addSpacing(12)
        row1.addWidget(QLabel("Latest Time:"))
        self.user_time_label = QLabel("--")
        self.user_time_label.setStyleSheet(
            "color: #4CAF50; font-weight: bold; font-family: monospace; font-size: 12px;"
        )
        row1.addWidget(self.user_time_label)

        self.edit_time_btn = QPushButton("Edit")
        self.edit_time_btn.setObjectName("edit_time_btn")
        self.edit_time_btn.setFixedSize(50, 20)
        self.edit_time_btn.clicked.connect(self.on_edit_time_clicked)
        row1.addWidget(self.edit_time_btn)
        
        row1.addSpacing(12)
        row1.addWidget(QLabel("Median:"))
        self.median_label = QLabel("--")
        self.median_label.setObjectName("median_label")
        row1.addWidget(self.median_label)
        
        row1.addStretch()
        group_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Formula:"))
        self.formula_label = QLabel(get_formula_string(self.a, self.b))
        self.formula_label.setStyleSheet("color: #FFA500; font-family: monospace;")
        row2.addWidget(self.formula_label)

        row2.addSpacing(8)
        row2.addWidget(QLabel("a:"))
        self.a_spin = QDoubleSpinBox()
        self.a_spin.setRange(0.01, 500.0)
        self.a_spin.setDecimals(3)
        self.a_spin.setValue(self.a)
        self.a_spin.setFixedWidth(70)
        self.a_spin.valueChanged.connect(self.on_a_changed)
        row2.addWidget(self.a_spin)

        row2.addWidget(QLabel("b:"))
        self.b_spin = QDoubleSpinBox()
        self.b_spin.setRange(0.01, MAX_B)
        self.b_spin.setDecimals(3)
        self.b_spin.setValue(self.b)
        self.b_spin.setFixedWidth(80)
        self.b_spin.valueChanged.connect(self.on_b_changed)
        row2.addWidget(self.b_spin)
        row2.addStretch()
        group_layout.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Current Ratio:"))
        self.ratio_value_label = QLabel("--")
        self.ratio_value_label.setObjectName("ratio_label")
        row3.addWidget(self.ratio_value_label)
        row3.addStretch()
        group_layout.addLayout(row3)

        row4 = QHBoxLayout()
        self.calc_btn = QPushButton("Calculate Ratio")
        self.calc_btn.clicked.connect(self.on_calculate_ratio)
        row4.addWidget(self.calc_btn)

        self.auto_fit_btn = QPushButton("Auto-Fit")
        self.auto_fit_btn.setStyleSheet("background-color: #2196F3;")
        self.auto_fit_btn.clicked.connect(self.on_auto_fit_clicked)
        row4.addWidget(self.auto_fit_btn)
        
        self.lock_btn = QPushButton("Lock")
        self.lock_btn.setStyleSheet("background-color: #9C27B0;")
        self.lock_btn.setCheckable(True)
        self.lock_btn.clicked.connect(self.on_lock_toggled)
        row4.addWidget(self.lock_btn)
        
        row4.addStretch()
        group_layout.addLayout(row4)

        self.accuracy_frame = QGroupBox("Data Quality")
        self.accuracy_frame.setStyleSheet("QGroupBox { color: #888; margin-top: 4px; padding-top: 4px; }")
        accuracy_layout = QVBoxLayout(self.accuracy_frame)
        accuracy_layout.setSpacing(2)
        accuracy_layout.setContentsMargins(6, 6, 6, 6)
        
        self.accuracy_label = QLabel("No data")
        self.accuracy_label.setStyleSheet("color: #888; font-size: 10px;")
        self.accuracy_label.setWordWrap(True)
        accuracy_layout.addWidget(self.accuracy_label)
        
        self.progress_bar = None
        
        group_layout.addWidget(self.accuracy_frame)
        
        layout.addWidget(group)
    
    def update_accuracy_display(self, confidence: float = None, data_points_used: int = 0,
                                avg_error: float = None, max_error: float = None,
                                outliers: int = 0):
        """Update the accuracy display with data quality information"""
        if data_points_used == 0:
            self.accuracy_frame.setVisible(False)
            return
        
        self.accuracy_frame.setVisible(True)
        
        if confidence is None:
            confidence = 0.5
        
        if confidence >= 0.8:
            color = "#4CAF50"
            quality_text = "Excellent"
        elif confidence >= 0.6:
            color = "#FFC107"
            quality_text = "Good"
        elif confidence >= 0.4:
            color = "#FF9800"
            quality_text = "Fair"
        else:
            color = "#f44336"
            quality_text = "Poor"
        
        percent = int(confidence * 100)
        
        quality_info = f"Fit: {quality_text} ({percent}%)"
        
        if self.distinct_ratios > 0:
            quality_info += f" | Ratios: {self.distinct_ratios} distinct groups"
        else:
            quality_info += f" | Points: {data_points_used}"
        
        if self.ratio_spread > 0:
            quality_info += f" | Spread: {self.ratio_spread:.3f}"
        
        if avg_error is not None and avg_error > 0:
            quality_info += f"\nAvg error: {avg_error:.2f}s"
        
        if self.quality_suggestion and self.quality_suggestion != "Insufficient data for quality assessment":
            quality_info += f"\n{self.quality_suggestion}"
        
        self.accuracy_label.setText(quality_info)
        self.accuracy_label.setStyleSheet(f"color: {color}; font-size: 10px;")
    
    def on_a_changed(self, value):
        """Handle manual a value change - preview only, no save"""
        if self.formula_is_locked:
            return
        self.a = value
        self.formula_modified = True
        self.formula_label.setText(get_formula_string(self.a, self.b))
        self._update_formula_style()
        self.set_calc_button_modified(True)
        # Send preview signal for live graph update (no save)
        self.formula_preview.emit(self.session_type, self.a, self.b)
    
    def on_b_changed(self, value):
        """Handle manual b value change - preview only, no save"""
        if self.formula_is_locked:
            return
        self.b = value
        self.formula_modified = True
        self.formula_label.setText(get_formula_string(self.a, self.b))
        self._update_formula_style()
        self.set_calc_button_modified(True)
        # Send preview signal for live graph update (no save)
        self.formula_preview.emit(self.session_type, self.a, self.b)
    
    def update_controls_enabled(self):
        enabled = not self.formula_is_locked
        self.a_spin.setEnabled(enabled)
        self.b_spin.setEnabled(enabled)
        self.auto_fit_btn.setEnabled(enabled)
    
    def update_current_ratio(self, ratio: float):
        if ratio is not None:
            self.ratio_value_label.setText(f"{ratio:.6f}")
        else:
            self.ratio_value_label.setText("--")
    
    def set_formula_is_default(self, is_default: bool):
        self.formula_is_default = is_default
        self._update_formula_style()
    
    def _update_formula_style(self):
        if self.formula_is_default:
            self.formula_label.setStyleSheet("color: #888888; font-family: monospace; font-style: italic;")
        elif self.formula_modified:
            self.formula_label.setStyleSheet("color: #888888; font-family: monospace; font-style: italic;")
        else:
            self.formula_label.setStyleSheet("color: #FFA500; font-family: monospace;")
    
    def on_auto_fit_clicked(self):
        if self.formula_is_locked:
            QMessageBox.warning(self, "Formula Locked", 
                "This formula is locked. Unlock it first to use Auto-Fit.")
            return
        
        if not self.current_track or not self.current_vehicle_class:
            QMessageBox.warning(self, "No Data", 
                "No track or vehicle class selected. Please select a track and class first.")
            return
        
        import sqlite3
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        
        session_filter = self.session_type
        cursor.execute("""
            SELECT ratio, lap_time FROM data_points 
            WHERE track = ? AND vehicle_class = ? AND session_type = ?
            ORDER BY ratio
        """, (self.current_track, self.current_vehicle_class, session_filter))
        
        rows = cursor.fetchall()
        conn.close()
        
        if len(rows) < 2:
            QMessageBox.warning(self, "Insufficient Data", 
                f"Need at least 2 data points to fit a curve.\n\n"
                f"Found {len(rows)} points for {self.current_track}/{self.current_vehicle_class}/{self.session_type}")
            return
        
        ratios = [row[0] for row in rows]
        times = [row[1] for row in rows]
        
        # Calculate data quality metrics
        quality_metrics = calculate_data_quality_metrics(ratios, times)
        quality_suggestion = quality_metrics.get('suggestion', '')
        self.distinct_ratios = quality_metrics.get('distinct_ratio_groups', 0)
        self.ratio_spread = quality_metrics.get('ratio_spread', 0.0)
        
        outlier_config = get_outlier_settings()
        min_ratio, max_ratio = get_ratio_limits()
        
        a, b, stats = fit_hyperbolic(
            ratios, times,
            fixed_a=None,
            outlier_method=outlier_config['method'],
            outlier_threshold=outlier_config['threshold'],
            optimize_a=True,
            min_ratio_limit=min_ratio,
            max_ratio_limit=max_ratio
        )
        
        if a is None or b is None:
            a, b, stats = fit_hyperbolic(
                ratios, times,
                fixed_a=None,
                outlier_method="none",
                outlier_threshold=outlier_config['threshold'],
                optimize_a=True,
                min_ratio_limit=min_ratio,
                max_ratio_limit=max_ratio
            )
        
        if a is None or b is None:
            a = DEFAULT_A_VALUE
            b_values = []
            for r, t in zip(ratios, times):
                if r > 0:
                    b_calc = t - (a / r)
                    b_values.append(b_calc)
            if b_values:
                b = sum(b_values) / len(b_values)
                from core_math import clamp_b
                b = clamp_b(b)
                predictions = [time_from_ratio(r, a, b) for r in ratios]
                errors = [abs(t - p) for t, p in zip(times, predictions)]
                stats.avg_error = sum(errors) / len(errors)
                stats.max_error = max(errors)
                stats.points_used = len(ratios)
                stats.outliers_removed = 0
        
        dialog = AutoFitResultDialog(
            self, self.session_type,
            self.a, self.b,
            a, b,
            stats,
            len(rows),
            stats.outliers_removed if hasattr(stats, 'outliers_removed') else 0,
            quality_suggestion
        )
        
        if dialog.exec_() == QDialog.Accepted and dialog.accepted_formula:
            # Apply the new formula
            self.a = a
            self.b = b
            self.a_spin.blockSignals(True)
            self.b_spin.blockSignals(True)
            self.a_spin.setValue(a)
            self.b_spin.setValue(b)
            self.a_spin.blockSignals(False)
            self.b_spin.blockSignals(False)
            self.formula_label.setText(get_formula_string(a, b))
            self.formula_modified = False
            self.formula_is_default = False
            self._update_formula_style()
            self.set_calc_button_modified(False)
            # Send save signal
            self.formula_changed.emit(self.session_type, a, b)
        
        # Update the accuracy display with quality info
        self.quality_suggestion = quality_suggestion
        self.update_accuracy_display(
            confidence=(stats.avg_error if stats else 1.0),
            data_points_used=len(rows),
            avg_error=stats.avg_error if stats else 0,
            max_error=stats.max_error if stats else 0,
            outliers=stats.outliers_removed if stats else 0
        )
    
    def update_median_time(self, median_time: float):
        self.median_time = median_time
        if median_time is not None and median_time > 0:
            minutes = int(median_time) // 60
            seconds = median_time % 60
            self.median_label.setText(f"{minutes}:{seconds:06.3f}")
        else:
            self.median_label.setText("--")
    
    def on_edit_time_clicked(self):
        dialog = ManualLapTimeDialog(self, self.session_type, self.user_time)
        if dialog.exec_() == QDialog.Accepted and dialog.new_time is not None:
            self.user_time = dialog.new_time
            minutes = int(self.user_time) // 60
            seconds = self.user_time % 60
            self.user_time_label.setText(f"{minutes}:{seconds:06.3f}")
            self.lap_time_edited.emit(self.session_type, self.user_time)
    
    def on_show_toggled(self, checked):
        self.show_data_toggled.emit(self.session_type, checked)
    
    def set_calc_button_modified(self, modified: bool):
        self.calc_button_modified = modified
        if modified:
            self.calc_btn.setStyleSheet("background-color: #FF9800;")
        else:
            self.calc_btn.setStyleSheet("")
    
    def on_calculate_ratio(self):
        if self.user_time and self.user_time > 0:
            new_ratio = ratio_from_time(self.user_time, self.a, self.b)
            
            if new_ratio is None:
                QMessageBox.warning(self, "Invalid Calculation", 
                    f"Cannot calculate ratio: T - b = {self.user_time:.3f} - {self.b:.2f} = {self.user_time - self.b:.3f} (must be positive)")
                return
            
            min_ratio, max_ratio = get_ratio_limits()
            clamped_ratio = clamp_ratio(new_ratio, min_ratio, max_ratio)
            
            if clamped_ratio != new_ratio:
                reply = QMessageBox.question(
                    self, "Ratio Out of Range",
                    f"The calculated {self.session_type.upper()} Ratio = {new_ratio:.6f} is outside the allowed range "
                    f"({min_ratio} - {max_ratio}).\n\n"
                    f"The ratio will be clamped to {clamped_ratio:.6f}.\n\nDo you want to continue?",
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply != QMessageBox.Yes:
                    return
                new_ratio = clamped_ratio
            
            self.current_ratio = new_ratio
            self.ratio_value_label.setText(f"{new_ratio:.6f}")
            
            # Save the formula since user explicitly clicked Calculate Ratio
            if self.formula_modified:
                self.formula_modified = False
                self.formula_is_default = False
                self._update_formula_style()
                self.formula_changed.emit(self.session_type, self.a, self.b)
            
            self.calculate_ratio.emit(self.session_type, self.user_time)
            self.set_calc_button_modified(False)
        else:
            QMessageBox.warning(self, "No Time", "No user time available for this session.\n\nClick the 'Edit' button to set a lap time manually.")
    
    def on_lock_toggled(self, checked):
        self.formula_is_locked = checked
        
        if checked:
            self.lock_btn.setText("Locked")
            self.lock_btn.setStyleSheet("background-color: #f44336;")
            self.lock_btn.setToolTip("Formula is locked - auto-updates disabled")
        else:
            self.lock_btn.setText("Lock")
            self.lock_btn.setStyleSheet("background-color: #9C27B0;")
            self.lock_btn.setToolTip("Lock formula to prevent auto-updates")
        
        self.update_controls_enabled()
        self.lock_toggled.emit(self.session_type, checked)
            
    def set_locked_status(self, is_locked: bool):
        self.formula_is_locked = is_locked
        self.lock_btn.blockSignals(True)
        self.lock_btn.setChecked(is_locked)
        if is_locked:
            self.lock_btn.setText("Locked")
            self.lock_btn.setStyleSheet("background-color: #f44336;")
            self.lock_btn.setToolTip("Formula is locked - auto-updates disabled")
        else:
            self.lock_btn.setText("Lock")
            self.lock_btn.setStyleSheet("background-color: #9C27B0;")
            self.lock_btn.setToolTip("Lock formula to prevent auto-updates")
        self.lock_btn.blockSignals(False)
        self.update_controls_enabled()
            
    def update_formula(self, a: float, b: float):
        """Update formula from external source (database load)"""
        self.a = a
        self.b = b
        self.a_spin.blockSignals(True)
        self.b_spin.blockSignals(True)
        self.a_spin.setValue(a)
        self.b_spin.setValue(b)
        self.a_spin.blockSignals(False)
        self.b_spin.blockSignals(False)
        self.formula_label.setText(get_formula_string(a, b))
        self.formula_modified = False
        self._update_formula_style()
        self.set_calc_button_modified(False)
        
    def update_user_time(self, time_sec: float):
        self.user_time = time_sec if time_sec > 0 else None
        if self.user_time:
            minutes = int(self.user_time) // 60
            seconds = self.user_time % 60
            self.user_time_label.setText(f"{minutes}:{seconds:06.3f}")
        else:
            self.user_time_label.setText("--")
            
    def update_ratio(self, ratio: float):
        self.current_ratio = ratio
        
    def set_show_data(self, show: bool):
        self.show_checkbox.blockSignals(True)
        self.show_checkbox.setChecked(show)
        self.show_checkbox.blockSignals(False)
    
    def update_accuracy(self, confidence: float, data_points_used: int,
                        avg_error: float = None, max_error: float = None,
                        outliers: int = 0):
        """Legacy method - now uses update_accuracy_display"""
        self.update_accuracy_display(confidence, data_points_used, avg_error, max_error, outliers)
