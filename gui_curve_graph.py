#!/usr/bin/env python3
"""
Curve Graph component for Live AI Tuner
Provides the hyperbolic curve visualization and data point display
"""

import sqlite3
import numpy as np
import pyqtgraph as pg
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QMessageBox, QListWidget, QListWidgetItem, QAbstractItemView,
    QDialog, QDialogButtonBox, QMenu, QAction, QApplication
)
from PyQt5.QtCore import Qt, pyqtSignal, QPoint

from core_math import DEFAULT_A_VALUE, time_from_ratio, ratio_from_time, get_formula_string
from core_autopilot import get_vehicle_class, load_vehicle_classes


class CurveGraphWidget(QWidget):
    """Widget containing the curve graph and data management"""
    
    point_selected = pyqtSignal(str, str, float, float)
    data_updated = pyqtSignal()
    formula_changed = pyqtSignal(str, float, float)
    points_deleted = pyqtSignal(list)
    
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.class_mapping = load_vehicle_classes()
        
        self.qual_a = DEFAULT_A_VALUE
        self.qual_b = 70.0
        self.race_a = DEFAULT_A_VALUE
        self.race_b = 70.0
        self.qual_is_default = True
        self.race_is_default = True
        self.show_qualifying = True
        self.show_race = True
        self.show_user_points = True
        self.show_median_point = True
        
        self.all_tracks = []
        self.all_classes = []
        self.current_track = ""
        self.current_vehicle = ""
        self.current_vehicle_class = ""
        self.selected_classes = []
        
        self.user_qual_time = None
        self.user_race_time = None
        self.user_qual_ratio = None
        self.user_race_ratio = None
        self.user_qual_history = []
        self.user_race_history = []
        self.median_qual_time = None
        self.median_race_time = None
        self.median_qual_ratio = None
        self.median_race_ratio = None
        
        self.qual_points_data = []
        self.race_points_data = []
        self.unknown_points_data = []
        
        self.invalid_point_ids = set()
        
        self.qual_curve = None
        self.race_curve = None
        self.qual_scatter = None
        self.race_scatter = None
        self.qual_invalid_scatter = None
        self.race_invalid_scatter = None
        self.unknown_scatter = None
        self.user_qual_point = None
        self.user_race_point = None
        self.user_qual_historical = None
        self.user_race_historical = None
        self.median_qual_point = None
        self.median_race_point = None
        self.legend = None
        self.selected_point_markers = []
        self.selected_point_ids = set()
        self.user_point_labels = []
        self.user_v_lines = []
        
        self.selection_mode = False
        
        self.setup_ui()
        self.setup_context_menu()
        
    def setup_context_menu(self):
        """Setup right-click context menu for the plot"""
        self.plot_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.plot_widget.customContextMenuRequested.connect(self.show_context_menu)
        
        self.context_menu = QMenu(self)
        
        self.delete_selected_action = QAction("Delete Selected Points", self)
        self.delete_selected_action.triggered.connect(self.delete_selected_points)
        self.context_menu.addAction(self.delete_selected_action)
        
        self.select_all_action = QAction("Select All Points", self)
        self.select_all_action.triggered.connect(self.select_all_points)
        self.context_menu.addAction(self.select_all_action)
        
        self.clear_selection_action = QAction("Clear Selection", self)
        self.clear_selection_action.triggered.connect(self.clear_selection)
        self.context_menu.addAction(self.clear_selection_action)
        
        self.context_menu.addSeparator()
        
        self.selection_mode_action = QAction("Enable Selection Mode (Click to select)", self)
        self.selection_mode_action.setCheckable(True)
        self.selection_mode_action.triggered.connect(self.toggle_selection_mode)
        self.context_menu.addAction(self.selection_mode_action)
        
    def show_context_menu(self, pos):
        global_pos = self.plot_widget.mapToGlobal(pos)
        self.context_menu.exec_(global_pos)
    
    def toggle_selection_mode(self, enabled):
        self.selection_mode = enabled
        if enabled:
            self.selection_mode_action.setText("Disable Selection Mode")
            self.setCursor(Qt.CrossCursor)
        else:
            self.selection_mode_action.setText("Enable Selection Mode (Click to select)")
            self.setCursor(Qt.ArrowCursor)
            self.clear_selection()
    
    def calculate_invalid_points(self):
        """Calculate which points are invalid based on current formulas"""
        self.invalid_point_ids.clear()
        invalid_threshold = 2.0
        
        for point_data in self.qual_points_data:
            point_id, ratio, lap_time = point_data
            predicted_time = time_from_ratio(ratio, self.qual_a, self.qual_b)
            if abs(predicted_time - lap_time) > invalid_threshold:
                self.invalid_point_ids.add(point_id)
        
        for point_data in self.race_points_data:
            point_id, ratio, lap_time = point_data
            predicted_time = time_from_ratio(ratio, self.race_a, self.race_b)
            if abs(predicted_time - lap_time) > invalid_threshold:
                self.invalid_point_ids.add(point_id)
    
    def get_invalid_points_info(self) -> str:
        """Get detailed information about invalid points"""
        info_lines = ["Invalid Points (Error > 2.0 seconds from current formula):", ""]
        
        for point_data in self.qual_points_data:
            point_id, ratio, lap_time = point_data
            if point_id in self.invalid_point_ids:
                predicted = time_from_ratio(ratio, self.qual_a, self.qual_b)
                error = abs(predicted - lap_time)
                minutes = int(lap_time) // 60
                seconds = lap_time % 60
                pred_min = int(predicted) // 60
                pred_sec = predicted % 60
                info_lines.append(f"Qualifying ID {point_id}:")
                info_lines.append(f"  Ratio: {ratio:.6f}")
                info_lines.append(f"  Actual: {minutes}:{seconds:06.3f}")
                info_lines.append(f"  Predicted: {pred_min}:{pred_sec:06.3f}")
                info_lines.append(f"  Error: {error:.3f}s")
                info_lines.append("")
        
        for point_data in self.race_points_data:
            point_id, ratio, lap_time = point_data
            if point_id in self.invalid_point_ids:
                predicted = time_from_ratio(ratio, self.race_a, self.race_b)
                error = abs(predicted - lap_time)
                minutes = int(lap_time) // 60
                seconds = lap_time % 60
                pred_min = int(predicted) // 60
                pred_sec = predicted % 60
                info_lines.append(f"Race ID {point_id}:")
                info_lines.append(f"  Ratio: {ratio:.6f}")
                info_lines.append(f"  Actual: {minutes}:{seconds:06.3f}")
                info_lines.append(f"  Predicted: {pred_min}:{pred_sec:06.3f}")
                info_lines.append(f"  Error: {error:.3f}s")
                info_lines.append("")
        
        if len(info_lines) == 2:
            return "No invalid points found. All points have error <= 2.0 seconds."
        
        return "\n".join(info_lines)
    
    def show_invalid_points_info(self):
        QMessageBox.information(self, "Invalid Points Information", self.get_invalid_points_info())
    
    def get_all_data_points_with_ids(self):
        if not self.current_track or not self.selected_classes:
            return [], [], []
        
        vehicle_classes = self._get_vehicles_for_classes(self.selected_classes)
        if not vehicle_classes:
            return [], [], []
        
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        placeholders = ','.join('?' * len(vehicle_classes))
        
        query = f"""
            SELECT id, ratio, lap_time, session_type 
            FROM data_points 
            WHERE track = ? AND vehicle_class IN ({placeholders})
        """
        cursor.execute(query, [self.current_track] + vehicle_classes)
        rows = cursor.fetchall()
        conn.close()
        
        qual_points = []
        race_points = []
        unknown_points = []
        
        for row in rows:
            point_id = row[0]
            ratio = row[1]
            lap_time = row[2]
            session_type = row[3]
            
            if session_type == 'qual':
                qual_points.append((point_id, ratio, lap_time))
            elif session_type == 'race':
                race_points.append((point_id, ratio, lap_time))
            else:
                unknown_points.append((point_id, ratio, lap_time))
        
        return qual_points, race_points, unknown_points
    
    def select_all_points(self):
        self.clear_selection()
        
        for point_data in self.qual_points_data:
            self.selected_point_ids.add(point_data[0])
        for point_data in self.race_points_data:
            self.selected_point_ids.add(point_data[0])
        for point_data in self.unknown_points_data:
            self.selected_point_ids.add(point_data[0])
        
        self.update_selected_markers()
        
        count = len(self.selected_point_ids)
        parent = self.parent()
        if hasattr(parent, 'info_text'):
            parent.info_text.setText(f"Selected {count} point(s). Right-click to delete selected points.")
    
    def select_qualifying_points(self):
        self.clear_selection()
        for point_data in self.qual_points_data:
            self.selected_point_ids.add(point_data[0])
        self.update_selected_markers()
        count = len(self.selected_point_ids)
        parent = self.parent()
        if hasattr(parent, 'info_text'):
            parent.info_text.setText(f"Selected {count} qualifying point(s).")
    
    def select_race_points(self):
        self.clear_selection()
        for point_data in self.race_points_data:
            self.selected_point_ids.add(point_data[0])
        self.update_selected_markers()
        count = len(self.selected_point_ids)
        parent = self.parent()
        if hasattr(parent, 'info_text'):
            parent.info_text.setText(f"Selected {count} race point(s).")
    
    def select_invalid_points(self):
        self.clear_selection()
        self.calculate_invalid_points()
        for point_id in self.invalid_point_ids:
            self.selected_point_ids.add(point_id)
        self.update_selected_markers()
        
        count = len(self.selected_point_ids)
        if count > 0:
            self.show_invalid_points_info()
        else:
            QMessageBox.information(self, "No Invalid Points", 
                "No invalid points found. All points have error <= 2.0 seconds from the current formula.\n\n"
                "Use Auto-Fit in the session panel to optimize the formula to fit all points.")
    
    def select_points_by_ratio(self):
        if not self.selected_point_ids:
            QMessageBox.warning(self, "No Selection", 
                "Please select at least one point first, then use this button to select all points with the same ratio.")
            return
        
        selected_ratio = None
        for point_data in self.qual_points_data:
            if point_data[0] in self.selected_point_ids:
                selected_ratio = point_data[1]
                break
        if selected_ratio is None:
            for point_data in self.race_points_data:
                if point_data[0] in self.selected_point_ids:
                    selected_ratio = point_data[1]
                    break
        
        if selected_ratio is None:
            QMessageBox.warning(self, "No Ratio Found", "Could not determine ratio from selected point.")
            return
        
        self.clear_selection()
        tolerance = 0.0001
        
        for point_data in self.qual_points_data:
            if abs(point_data[1] - selected_ratio) < tolerance:
                self.selected_point_ids.add(point_data[0])
        for point_data in self.race_points_data:
            if abs(point_data[1] - selected_ratio) < tolerance:
                self.selected_point_ids.add(point_data[0])
        
        self.update_selected_markers()
        
        count = len(self.selected_point_ids)
        parent = self.parent()
        if hasattr(parent, 'info_text'):
            parent.info_text.setText(f"Selected {count} point(s) with ratio {selected_ratio:.6f}")
    
    def clear_selection(self):
        self.selected_point_ids.clear()
        self.update_selected_markers()
        parent = self.parent()
        if hasattr(parent, 'info_text'):
            parent.info_text.setText("Selection cleared. Click on any data point to see its details.")
    
    def update_selected_markers(self):
        for marker in self.selected_point_markers:
            self._safe_remove_item(marker)
        self.selected_point_markers.clear()
        
        selected_points = []
        
        for point_data in self.qual_points_data:
            if point_data[0] in self.selected_point_ids:
                selected_points.append((point_data[1], point_data[2]))
        for point_data in self.race_points_data:
            if point_data[0] in self.selected_point_ids:
                selected_points.append((point_data[1], point_data[2]))
        for point_data in self.unknown_points_data:
            if point_data[0] in self.selected_point_ids:
                selected_points.append((point_data[1], point_data[2]))
        
        if selected_points:
            ratios = [p[0] for p in selected_points]
            times = [p[1] for p in selected_points]
            marker = pg.ScatterPlotItem(ratios, times, brush=pg.mkBrush('#00FF00'), 
                                         size=14, symbol='o', pen=pg.mkPen('white', width=2))
            self.plot.addItem(marker)
            self.selected_point_markers.append(marker)
    
    def delete_selected_points(self):
        if not self.selected_point_ids:
            QMessageBox.warning(self, "No Selection", "No points selected.")
            return
        
        point_ids = list(self.selected_point_ids)
        reply = QMessageBox.question(self, "Confirm Delete",
            f"Delete {len(point_ids)} selected data point(s)?\n\nThis action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No)
        
        if reply != QMessageBox.Yes:
            return
        
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        deleted_count = 0
        
        try:
            for point_id in point_ids:
                cursor.execute("DELETE FROM data_points WHERE id = ?", (point_id,))
                if cursor.rowcount > 0:
                    deleted_count += 1
            
            conn.commit()
            
            if deleted_count > 0:
                QMessageBox.information(self, "Deletion Complete", f"Deleted {deleted_count} point(s).")
                self.selected_point_ids.clear()
                self.update_selected_markers()
                
                deleted_info = []
                for point_id in point_ids:
                    if point_id in [p[0] for p in self.qual_points_data]:
                        deleted_info.append((point_id, 'qual'))
                    elif point_id in [p[0] for p in self.race_points_data]:
                        deleted_info.append((point_id, 'race'))
                self.points_deleted.emit(deleted_info)
                
                self.load_data()
                self.full_refresh()
                
                parent = self.parent()
                if hasattr(parent, 'load_current_data'):
                    parent.load_current_data()
                if hasattr(parent, 'update_all_display'):
                    parent.update_all_display()
                
        except Exception as e:
            conn.rollback()
            QMessageBox.critical(self, "Error", f"Failed to delete points: {str(e)}")
        finally:
            conn.close()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        toolbar = QFrame()
        toolbar.setStyleSheet("background-color: #2b2b2b; border-radius: 4px;")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(8, 4, 8, 4)
        
        self.selection_mode_btn = QPushButton("Selection Mode (Off)")
        self.selection_mode_btn.setCheckable(True)
        self.selection_mode_btn.setStyleSheet("background-color: #555;")
        self.selection_mode_btn.clicked.connect(self.toggle_selection_mode_btn)
        toolbar_layout.addWidget(self.selection_mode_btn)
        
        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.clicked.connect(self.select_all_points)
        toolbar_layout.addWidget(self.select_all_btn)
        
        self.select_qual_btn = QPushButton("Select All Qualifying")
        self.select_qual_btn.clicked.connect(self.select_qualifying_points)
        toolbar_layout.addWidget(self.select_qual_btn)
        
        self.select_race_btn = QPushButton("Select All Race")
        self.select_race_btn.clicked.connect(self.select_race_points)
        toolbar_layout.addWidget(self.select_race_btn)
        
        self.select_invalid_btn = QPushButton("Select Invalid Points")
        self.select_invalid_btn.clicked.connect(self.select_invalid_points)
        toolbar_layout.addWidget(self.select_invalid_btn)
        
        self.select_by_ratio_btn = QPushButton("Select All by Ratio")
        self.select_by_ratio_btn.setToolTip("Select all points with the same ratio as the selected point")
        self.select_by_ratio_btn.clicked.connect(self.select_points_by_ratio)
        toolbar_layout.addWidget(self.select_by_ratio_btn)
        
        self.clear_selection_btn = QPushButton("Clear Selection")
        self.clear_selection_btn.clicked.connect(self.clear_selection)
        toolbar_layout.addWidget(self.clear_selection_btn)
        
        self.delete_selected_btn = QPushButton("Delete Selected")
        self.delete_selected_btn.setStyleSheet("background-color: #f44336;")
        self.delete_selected_btn.clicked.connect(self.delete_selected_points)
        toolbar_layout.addWidget(self.delete_selected_btn)
        
        toolbar_layout.addStretch()
        
        layout.addWidget(toolbar)
        
        self.plot_widget = pg.GraphicsLayoutWidget()
        self.plot_widget.setBackground('#2b2b2b')
        self.plot = self.plot_widget.addPlot()
        self.plot.setLabel('bottom', 'Ratio (R)', color='white', size='11pt')
        self.plot.setLabel('left', 'Lap Time (seconds)', color='white', size='11pt')
        self.plot.setTitle('Hyperbolic Curves: T = a / R + b', color='#FFA500', size='12pt')
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        self.plot.setXRange(0.4, 2.0)
        self.plot.setYRange(50, 200)
        self.plot.getAxis('bottom').setPen('white')
        self.plot.getAxis('bottom').setTextPen('white')
        self.plot.getAxis('left').setPen('white')
        self.plot.getAxis('left').setTextPen('white')
        
        self.plot.scene().sigMouseClicked.connect(self.on_plot_click)
        
        layout.addWidget(self.plot_widget)
        
        info_layout = QHBoxLayout()
        self.formula_label = QLabel("")
        self.formula_label.setStyleSheet("color: #888; font-size: 10px; font-family: monospace;")
        info_layout.addWidget(self.formula_label)
        info_layout.addStretch()
        layout.addLayout(info_layout)
    
    def toggle_selection_mode_btn(self, checked):
        self.selection_mode = checked
        if checked:
            self.selection_mode_btn.setText("Selection Mode (On)")
            self.selection_mode_btn.setStyleSheet("background-color: #4CAF50;")
            self.setCursor(Qt.CrossCursor)
        else:
            self.selection_mode_btn.setText("Selection Mode (Off)")
            self.selection_mode_btn.setStyleSheet("background-color: #555;")
            self.setCursor(Qt.ArrowCursor)
            self.clear_selection()
    
    def set_formula_is_default(self, session_type: str, is_default: bool):
        if session_type == "qual":
            self.qual_is_default = is_default
        else:
            self.race_is_default = is_default
    
    def _calculate_ratio_for_user_time(self, time_sec: float, session_type: str) -> float:
        if session_type == "qual":
            return ratio_from_time(time_sec, self.qual_a, self.qual_b)
        else:
            return ratio_from_time(time_sec, self.race_a, self.race_b)
    
    def full_refresh(self):
        self.load_data()
        self.update_graph()
    
    def update_current_info(self, track: str = None, vehicle: str = None, 
                            qual_time: float = None, race_time: float = None,
                            qual_ratio: float = None, race_ratio: float = None,
                            qual_history: list = None, race_history: list = None,
                            median_qual_time: float = None, median_race_time: float = None):
        if track is not None and track != self.current_track:
            self.current_track = track
            self.load_data()
        if vehicle is not None and vehicle != self.current_vehicle:
            self.current_vehicle = vehicle
            self.current_vehicle_class = get_vehicle_class(vehicle, self.class_mapping)
            if self.current_vehicle_class not in self.selected_classes:
                self.selected_classes = [self.current_vehicle_class]
            self.load_data()
        if qual_time is not None and qual_time > 0:
            self.user_qual_time = qual_time
            self.user_qual_ratio = self._calculate_ratio_for_user_time(qual_time, "qual")
        if race_time is not None and race_time > 0:
            self.user_race_time = race_time
            self.user_race_ratio = self._calculate_ratio_for_user_time(race_time, "race")
        if qual_ratio is not None:
            self.user_qual_ratio = qual_ratio
        if race_ratio is not None:
            self.user_race_ratio = race_ratio
        if qual_history is not None:
            self.user_qual_history = qual_history
        if race_history is not None:
            self.user_race_history = race_history
        if median_qual_time is not None:
            self.median_qual_time = median_qual_time
            if median_qual_time > 0:
                self.median_qual_ratio = self._calculate_ratio_for_user_time(median_qual_time, "qual")
        if median_race_time is not None:
            self.median_race_time = median_race_time
            if median_race_time > 0:
                self.median_race_ratio = self._calculate_ratio_for_user_time(median_race_time, "race")
        self.update_graph()
    
    def load_data(self):
        if not self.db.database_exists():
            return
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT track FROM data_points ORDER BY track")
        self.all_tracks = [row[0] for row in cursor.fetchall()]
        cursor.execute("SELECT DISTINCT vehicle_class FROM data_points")
        all_vehicles = [row[0] for row in cursor.fetchall()]
        class_set = set()
        for vehicle in all_vehicles:
            vehicle_class = get_vehicle_class(vehicle, self.class_mapping)
            class_set.add(vehicle_class)
        self.all_classes = sorted(class_set)
        if not self.current_track and self.all_tracks:
            self.current_track = self.all_tracks[0]
        if not self.selected_classes and self.all_classes:
            self.selected_classes = self.all_classes.copy()
        conn.close()
        self.data_updated.emit()

    def _get_vehicles_for_classes(self, classes: list) -> list:
        if not classes:
            return []
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT vehicle_class FROM data_points")
        all_classes = [row[0] for row in cursor.fetchall()]
        conn.close()
        return [cls for cls in all_classes if cls in classes]

    def get_selected_data(self) -> dict:
        if not self.current_track or not self.selected_classes:
            return {'quali': [], 'race': [], 'unknown': []}
        vehicle_classes = self._get_vehicles_for_classes(self.selected_classes)
        if not vehicle_classes:
            return {'quali': [], 'race': [], 'unknown': []}
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        placeholders = ','.join('?' * len(vehicle_classes))
        query = f"""
            SELECT id, ratio, lap_time, session_type 
            FROM data_points 
            WHERE track = ? AND vehicle_class IN ({placeholders})
        """
        cursor.execute(query, [self.current_track] + vehicle_classes)
        rows = cursor.fetchall()
        conn.close()
        result = {'quali': [], 'race': [], 'unknown': []}
        qual_points = []
        race_points = []
        unknown_points = []
        
        for row in rows:
            point_id = row[0]
            ratio = row[1]
            lap_time = row[2]
            session_type = row[3]
            
            if session_type == 'qual':
                qual_points.append((point_id, ratio, lap_time))
                result['quali'].append((ratio, lap_time))
            elif session_type == 'race':
                race_points.append((point_id, ratio, lap_time))
                result['race'].append((ratio, lap_time))
            else:
                unknown_points.append((point_id, ratio, lap_time))
                result['unknown'].append((ratio, lap_time))
        
        self.qual_points_data = qual_points
        self.race_points_data = race_points
        self.unknown_points_data = unknown_points
        
        self.calculate_invalid_points()
        
        return result
    
    def _safe_remove_legend(self):
        if self.legend is not None:
            try:
                if self.legend.scene() is not None:
                    self.plot.scene().removeItem(self.legend)
            except Exception:
                pass
            self.legend = None
    
    def _safe_remove_item(self, item):
        if item is not None:
            try:
                if item.scene() is not None:
                    self.plot.scene().removeItem(item)
            except Exception:
                pass
    
    def update_graph(self):
        ratios = np.linspace(0.4, 2.0, 200)
        points_data = self.get_selected_data()
        qual_times = [time_from_ratio(r, self.qual_a, self.qual_b) for r in ratios]
        race_times = [time_from_ratio(r, self.race_a, self.race_b) for r in ratios]
        
        qual_times_array = np.array(qual_times)
        race_times_array = np.array(race_times)
        
        qual_pen = pg.mkPen(color='#888888', width=2.0, style=Qt.DashLine) if self.qual_is_default else pg.mkPen(color='#FFFF00', width=2.5)
        race_pen = pg.mkPen(color='#888888', width=2.0, style=Qt.DashLine) if self.race_is_default else pg.mkPen(color='#FF6600', width=2.5)
        
        if self.show_qualifying:
            if self.qual_curve is None:
                self.qual_curve = self.plot.plot(ratios, qual_times_array, pen=qual_pen)
            else:
                if self.qual_curve.scene() is None:
                    self.qual_curve = self.plot.plot(ratios, qual_times_array, pen=qual_pen)
                else:
                    self.qual_curve.setData(ratios, qual_times_array)
                    self.qual_curve.setPen(qual_pen)
                    self.qual_curve.setVisible(True)
        elif self.qual_curve is not None:
            self.qual_curve.setVisible(False)
        
        if self.show_race:
            if self.race_curve is None:
                self.race_curve = self.plot.plot(ratios, race_times_array, pen=race_pen)
            else:
                if self.race_curve.scene() is None:
                    self.race_curve = self.plot.plot(ratios, race_times_array, pen=race_pen)
                else:
                    self.race_curve.setData(ratios, race_times_array)
                    self.race_curve.setPen(race_pen)
                    self.race_curve.setVisible(True)
        elif self.race_curve is not None:
            self.race_curve.setVisible(False)
        
        qual_valid_r, qual_valid_t = [], []
        qual_invalid_r, qual_invalid_t = [], []
        
        for point_data in self.qual_points_data:
            point_id, ratio, lap_time = point_data
            if point_id in self.invalid_point_ids:
                qual_invalid_r.append(ratio)
                qual_invalid_t.append(lap_time)
            else:
                qual_valid_r.append(ratio)
                qual_valid_t.append(lap_time)
        
        race_valid_r, race_valid_t = [], []
        race_invalid_r, race_invalid_t = [], []
        
        for point_data in self.race_points_data:
            point_id, ratio, lap_time = point_data
            if point_id in self.invalid_point_ids:
                race_invalid_r.append(ratio)
                race_invalid_t.append(lap_time)
            else:
                race_valid_r.append(ratio)
                race_valid_t.append(lap_time)
        
        if self.show_qualifying and qual_valid_r:
            if self.qual_scatter is None:
                self.qual_scatter = pg.ScatterPlotItem(qual_valid_r, qual_valid_t, brush=pg.mkBrush('#FFFF00'), size=8, symbol='o', pen=pg.mkPen('white', width=1))
                self.plot.addItem(self.qual_scatter)
            else:
                if self.qual_scatter.scene() is None:
                    self.qual_scatter = pg.ScatterPlotItem(qual_valid_r, qual_valid_t, brush=pg.mkBrush('#FFFF00'), size=8, symbol='o', pen=pg.mkPen('white', width=1))
                    self.plot.addItem(self.qual_scatter)
                else:
                    self.qual_scatter.setData(qual_valid_r, qual_valid_t)
                    self.qual_scatter.setVisible(True)
        elif self.qual_scatter is not None:
            self.qual_scatter.setVisible(False)
        
        if self.show_qualifying and qual_invalid_r:
            if self.qual_invalid_scatter is None:
                self.qual_invalid_scatter = pg.ScatterPlotItem(qual_invalid_r, qual_invalid_t, brush=pg.mkBrush('#888888'), size=8, symbol='o', pen=pg.mkPen('white', width=1))
                self.plot.addItem(self.qual_invalid_scatter)
            else:
                if self.qual_invalid_scatter.scene() is None:
                    self.qual_invalid_scatter = pg.ScatterPlotItem(qual_invalid_r, qual_invalid_t, brush=pg.mkBrush('#888888'), size=8, symbol='o', pen=pg.mkPen('white', width=1))
                    self.plot.addItem(self.qual_invalid_scatter)
                else:
                    self.qual_invalid_scatter.setData(qual_invalid_r, qual_invalid_t)
                    self.qual_invalid_scatter.setVisible(True)
        elif self.qual_invalid_scatter is not None:
            self.qual_invalid_scatter.setVisible(False)
        
        if self.show_race and race_valid_r:
            if self.race_scatter is None:
                self.race_scatter = pg.ScatterPlotItem(race_valid_r, race_valid_t, brush=pg.mkBrush('#FF6600'), size=8, symbol='s', pen=pg.mkPen('white', width=1))
                self.plot.addItem(self.race_scatter)
            else:
                if self.race_scatter.scene() is None:
                    self.race_scatter = pg.ScatterPlotItem(race_valid_r, race_valid_t, brush=pg.mkBrush('#FF6600'), size=8, symbol='s', pen=pg.mkPen('white', width=1))
                    self.plot.addItem(self.race_scatter)
                else:
                    self.race_scatter.setData(race_valid_r, race_valid_t)
                    self.race_scatter.setVisible(True)
        elif self.race_scatter is not None:
            self.race_scatter.setVisible(False)
        
        if self.show_race and race_invalid_r:
            if self.race_invalid_scatter is None:
                self.race_invalid_scatter = pg.ScatterPlotItem(race_invalid_r, race_invalid_t, brush=pg.mkBrush('#888888'), size=8, symbol='s', pen=pg.mkPen('white', width=1))
                self.plot.addItem(self.race_invalid_scatter)
            else:
                if self.race_invalid_scatter.scene() is None:
                    self.race_invalid_scatter = pg.ScatterPlotItem(race_invalid_r, race_invalid_t, brush=pg.mkBrush('#888888'), size=8, symbol='s', pen=pg.mkPen('white', width=1))
                    self.plot.addItem(self.race_invalid_scatter)
                else:
                    self.race_invalid_scatter.setData(race_invalid_r, race_invalid_t)
                    self.race_invalid_scatter.setVisible(True)
        elif self.race_invalid_scatter is not None:
            self.race_invalid_scatter.setVisible(False)
        
        unknown_points = points_data.get('unknown', [])
        if unknown_points:
            r = [p[0] for p in unknown_points]
            t = [p[1] for p in unknown_points]
            if self.unknown_scatter is None:
                self.unknown_scatter = pg.ScatterPlotItem(r, t, brush=pg.mkBrush('#FF00FF'), size=6, symbol='t', pen=pg.mkPen('white', width=1))
                self.plot.addItem(self.unknown_scatter)
            else:
                if self.unknown_scatter.scene() is None:
                    self.unknown_scatter = pg.ScatterPlotItem(r, t, brush=pg.mkBrush('#FF00FF'), size=6, symbol='t', pen=pg.mkPen('white', width=1))
                    self.plot.addItem(self.unknown_scatter)
                else:
                    self.unknown_scatter.setData(r, t)
                    self.unknown_scatter.setVisible(True)
        elif self.unknown_scatter is not None:
            self.unknown_scatter.setVisible(False)
        
        qual_user_points = []
        race_user_points = []
        
        for entry in self.user_qual_history:
            if len(entry) >= 2:
                lap_time, ratio = entry[0], entry[1]
                if lap_time > 0 and ratio is not None:
                    qual_user_points.append((ratio, lap_time))
        
        for entry in self.user_race_history:
            if len(entry) >= 2:
                lap_time, ratio = entry[0], entry[1]
                if lap_time > 0 and ratio is not None:
                    race_user_points.append((ratio, lap_time))
        
        if self.user_qual_time and self.user_qual_ratio:
            if not any(abs(p[1] - self.user_qual_time) < 0.01 for p in qual_user_points):
                qual_user_points.append((self.user_qual_ratio, self.user_qual_time))
        
        if self.user_race_time and self.user_race_ratio:
            if not any(abs(p[1] - self.user_race_time) < 0.01 for p in race_user_points):
                race_user_points.append((self.user_race_ratio, self.user_race_time))
        
        all_user_points = qual_user_points + race_user_points
        
        if all_user_points and self.show_user_points:
            r = [p[0] for p in all_user_points]
            t = [p[1] for p in all_user_points]
            if self.user_qual_historical is None:
                self.user_qual_historical = pg.ScatterPlotItem(r, t, brush=pg.mkBrush('#8888FF'), size=8, symbol='t', pen=pg.mkPen('white', width=1))
                self.plot.addItem(self.user_qual_historical)
            else:
                if self.user_qual_historical.scene() is None:
                    self.user_qual_historical = pg.ScatterPlotItem(r, t, brush=pg.mkBrush('#8888FF'), size=8, symbol='t', pen=pg.mkPen('white', width=1))
                    self.plot.addItem(self.user_qual_historical)
                else:
                    self.user_qual_historical.setData(r, t)
                    self.user_qual_historical.setVisible(True)
        elif self.user_qual_historical is not None:
            self.user_qual_historical.setVisible(False)
        
        median_points = []
        if self.median_qual_time and self.median_qual_ratio and self.show_median_point:
            median_points.append((self.median_qual_ratio, self.median_qual_time))
        if self.median_race_time and self.median_race_ratio and self.show_median_point:
            median_points.append((self.median_race_ratio, self.median_race_time))
        
        if median_points:
            r = [p[0] for p in median_points]
            t = [p[1] for p in median_points]
            if self.median_qual_point is None:
                self.median_qual_point = pg.ScatterPlotItem(r, t, brush=pg.mkBrush('#FF00FF'), size=14, symbol='d', pen=pg.mkPen('white', width=2))
                self.plot.addItem(self.median_qual_point)
            else:
                if self.median_qual_point.scene() is None:
                    self.median_qual_point = pg.ScatterPlotItem(r, t, brush=pg.mkBrush('#FF00FF'), size=14, symbol='d', pen=pg.mkPen('white', width=2))
                    self.plot.addItem(self.median_qual_point)
                else:
                    self.median_qual_point.setData(r, t)
                    self.median_qual_point.setVisible(True)
        elif self.median_qual_point is not None:
            self.median_qual_point.setVisible(False)
        
        current_user_points = []
        current_labels = []
        if self.user_qual_time and self.user_qual_ratio:
            current_user_points.append((self.user_qual_ratio, self.user_qual_time))
            current_labels.append(("Latest Qual", self.user_qual_ratio, self.user_qual_time))
        if self.user_race_time and self.user_race_ratio:
            current_user_points.append((self.user_race_ratio, self.user_race_time))
            current_labels.append(("Latest Race", self.user_race_ratio, self.user_race_time))
        
        if current_user_points:
            r = [p[0] for p in current_user_points]
            t = [p[1] for p in current_user_points]
            if self.user_qual_point is None:
                self.user_qual_point = pg.ScatterPlotItem(r, t, brush=pg.mkBrush('#00FF00'), size=14, symbol='t', pen=pg.mkPen('white', width=2))
                self.plot.addItem(self.user_qual_point)
                self.user_point_labels = []
                for label, ratio_val, time_val in current_labels:
                    text_item = pg.TextItem(text=f"  {label}", color='#00FF00', anchor=(0, 0.5))
                    text_item.setPos(ratio_val, time_val)
                    self.plot.addItem(text_item)
                    self.user_point_labels.append(text_item)
            else:
                if self.user_qual_point.scene() is None:
                    self.user_qual_point = pg.ScatterPlotItem(r, t, brush=pg.mkBrush('#00FF00'), size=14, symbol='t', pen=pg.mkPen('white', width=2))
                    self.plot.addItem(self.user_qual_point)
                else:
                    self.user_qual_point.setData(r, t)
                    self.user_qual_point.setVisible(True)
                
                for i, (label, ratio_val, time_val) in enumerate(current_labels):
                    if i < len(self.user_point_labels) and self.user_point_labels[i] is not None:
                        if self.user_point_labels[i].scene() is not None:
                            self.user_point_labels[i].setPos(ratio_val, time_val)
                            self.user_point_labels[i].setHtml(f'  <span style="color:#00FF00;">{label}</span>')
                        else:
                            text_item = pg.TextItem(text=f"  {label}", color='#00FF00', anchor=(0, 0.5))
                            text_item.setPos(ratio_val, time_val)
                            self.plot.addItem(text_item)
                            self.user_point_labels[i] = text_item
                    else:
                        text_item = pg.TextItem(text=f"  {label}", color='#00FF00', anchor=(0, 0.5))
                        text_item.setPos(ratio_val, time_val)
                        self.plot.addItem(text_item)
                        if i < len(self.user_point_labels):
                            self.user_point_labels[i] = text_item
                        else:
                            self.user_point_labels.append(text_item)
        elif self.user_qual_point is not None:
            self.user_qual_point.setVisible(False)
            for label in self.user_point_labels:
                if label is not None and label.scene() is not None:
                    self.plot.scene().removeItem(label)
            self.user_point_labels = []
        
        if self.user_v_lines:
            for line in self.user_v_lines:
                self._safe_remove_item(line)
            self.user_v_lines = []
        
        if current_user_points and self.show_user_points:
            for ratio_val, time_val in current_user_points:
                v_line = pg.InfiniteLine(pos=ratio_val, angle=90, pen=pg.mkPen(color='#00FF00', width=1, style=Qt.DashLine))
                self.plot.addItem(v_line)
                self.user_v_lines.append(v_line)
                h_line = pg.InfiniteLine(pos=time_val, angle=0, pen=pg.mkPen(color='#00FF00', width=1, style=Qt.DashLine))
                self.plot.addItem(h_line)
                self.user_v_lines.append(h_line)
        
        self.update_selected_markers()
        
        self._safe_remove_legend()
        self.legend = self.plot.addLegend()
        
        qual_label = f'Qualifying: {get_formula_string(self.qual_a, self.qual_b)}'
        if self.qual_is_default:
            qual_label += " (default)"
        
        race_label = f'Race: {get_formula_string(self.race_a, self.race_b)}'
        if self.race_is_default:
            race_label += " (default)"
        
        if self.show_qualifying and self.qual_curve is not None:
            self.legend.addItem(self.qual_curve, qual_label)
        if self.show_race and self.race_curve is not None:
            self.legend.addItem(self.race_curve, race_label)
        if self.show_qualifying and qual_valid_r and self.qual_scatter is not None:
            self.legend.addItem(self.qual_scatter, f'Qual Data ({len(qual_valid_r)})')
        if self.show_qualifying and qual_invalid_r and self.qual_invalid_scatter is not None:
            self.legend.addItem(self.qual_invalid_scatter, f'Invalid Qual ({len(qual_invalid_r)})')
        if self.show_race and race_valid_r and self.race_scatter is not None:
            self.legend.addItem(self.race_scatter, f'Race Data ({len(race_valid_r)})')
        if self.show_race and race_invalid_r and self.race_invalid_scatter is not None:
            self.legend.addItem(self.race_invalid_scatter, f'Invalid Race ({len(race_invalid_r)})')
        if unknown_points and self.unknown_scatter is not None:
            self.legend.addItem(self.unknown_scatter, f'Unknown ({len(unknown_points)})')
        if all_user_points and self.user_qual_historical is not None:
            self.legend.addItem(self.user_qual_historical, f'Your Lap Times ({len(all_user_points)})')
        if median_points and self.median_qual_point is not None:
            self.legend.addItem(self.median_qual_point, 'Median Lap Time')
        if current_user_points and self.user_qual_point is not None:
            self.legend.addItem(self.user_qual_point, 'Latest Lap')
        
        qual_info = ""
        if self.user_qual_time and self.user_qual_ratio:
            minutes = int(self.user_qual_time) // 60
            seconds = self.user_qual_time % 60
            qual_info = f"Latest Qual: {minutes}:{seconds:06.3f}s -> R={self.user_qual_ratio:.4f}"
        race_info = ""
        if self.user_race_time and self.user_race_ratio:
            minutes = int(self.user_race_time) // 60
            seconds = self.user_race_time % 60
            race_info = f"Latest Race: {minutes}:{seconds:06.3f}s -> R={self.user_race_ratio:.4f}"
        separator = "  |  " if qual_info and race_info else ""
        median_info = ""
        if self.median_qual_time:
            minutes = int(self.median_qual_time) // 60
            seconds = self.median_qual_time % 60
            median_info += f"Median Qual: {minutes}:{seconds:06.3f}s"
        if self.median_race_time:
            if median_info:
                median_info += " | "
            minutes = int(self.median_race_time) // 60
            seconds = self.median_race_time % 60
            median_info += f"Median Race: {minutes}:{seconds:06.3f}s"
        separator2 = "  |  " if (qual_info or race_info) and median_info else ""
        self.formula_label.setText(f"{qual_info}{separator}{race_info}{separator2}{median_info}")
    
    def on_plot_click(self, event):
        if self.plot.scene().mouseGrabberItem() is not None:
            return
        
        pos = event.scenePos()
        mouse_point = self.plot.vb.mapSceneToView(pos)
        
        all_points = []
        for point_data in self.qual_points_data:
            all_points.append((point_data[0], point_data[1], point_data[2], 'qual'))
        for point_data in self.race_points_data:
            all_points.append((point_data[0], point_data[1], point_data[2], 'race'))
        for point_data in self.unknown_points_data:
            all_points.append((point_data[0], point_data[1], point_data[2], 'unknown'))
        
        if not all_points:
            return
        
        min_dist = float('inf')
        closest_point = None
        threshold = 0.05
        
        for point_id, ratio, lap_time, session_type in all_points:
            dx = ratio - mouse_point.x()
            dy = (lap_time - mouse_point.y()) / 10
            dist = (dx * dx + dy * dy) ** 0.5
            if dist < min_dist and dist < threshold:
                min_dist = dist
                closest_point = (point_id, ratio, lap_time, session_type)
        
        if closest_point:
            point_id, ratio, lap_time, session_type = closest_point
            
            modifiers = QApplication.keyboardModifiers()
            
            if modifiers & Qt.ControlModifier or modifiers & Qt.ShiftModifier:
                if point_id in self.selected_point_ids:
                    self.selected_point_ids.remove(point_id)
                else:
                    self.selected_point_ids.add(point_id)
            else:
                if not self.selection_mode:
                    self.selected_point_ids.clear()
                    self.selected_point_ids.add(point_id)
            
            self.update_selected_markers()
            
            minutes = int(lap_time) // 60
            seconds = lap_time % 60
            is_invalid = point_id in self.invalid_point_ids
            invalid_text = " (INVALID - error > 2s)" if is_invalid else ""
            
            count = len(self.selected_point_ids)
            parent = self.parent()
            if count > 1 and hasattr(parent, 'info_text'):
                parent.info_text.setText(f"{count} points selected. Right-click for delete options.")
            elif hasattr(parent, 'info_text'):
                parent.info_text.setText(
                    f"Point ID: {point_id} | Session: {session_type}{invalid_text} | "
                    f"Ratio: {ratio:.6f} | Lap Time: {minutes}:{seconds:06.3f}"
                )
    
    def set_formulas(self, qual_a: float, qual_b: float, race_a: float, race_b: float):
        self.qual_a = qual_a
        self.qual_b = qual_b
        self.race_a = race_a
        self.race_b = race_b
        if self.user_qual_time:
            self.user_qual_ratio = self._calculate_ratio_for_user_time(self.user_qual_time, "qual")
        if self.user_race_time:
            self.user_race_ratio = self._calculate_ratio_for_user_time(self.user_race_time, "race")
        if self.median_qual_time:
            self.median_qual_ratio = self._calculate_ratio_for_user_time(self.median_qual_time, "qual")
        if self.median_race_time:
            self.median_race_ratio = self._calculate_ratio_for_user_time(self.median_race_time, "race")
        self.update_graph()
    
    def set_show_qualifying(self, show: bool):
        self.show_qualifying = show
        self.update_graph()
        
    def set_show_race(self, show: bool):
        self.show_race = show
        self.update_graph()
