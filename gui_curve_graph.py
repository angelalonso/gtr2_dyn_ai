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
    points_deleted = pyqtSignal(list)  # Emitted when points are deleted, passes list of (id, session_type)
    
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
        
        # Store data points with their IDs for deletion
        self.qual_points_data = []  # list of (id, ratio, lap_time)
        self.race_points_data = []  # list of (id, ratio, lap_time)
        self.unknown_points_data = []  # list of (id, ratio, lap_time)
        
        self.qual_curve = None
        self.race_curve = None
        self.qual_scatter = None
        self.race_scatter = None
        self.unknown_scatter = None
        self.user_qual_point = None
        self.user_race_point = None
        self.user_qual_historical = None
        self.user_race_historical = None
        self.median_qual_point = None
        self.median_race_point = None
        self.legend = None
        self.selected_point_markers = []  # List of selected point markers
        self.selected_point_ids = set()  # Set of selected point IDs
        self.user_point_labels = []  # List of text labels for user points
        self.user_v_lines = []  # List of vertical/horizontal lines for user points
        
        # Selection mode state
        self.selection_mode = False
        self.selection_rect = None
        self.selection_start = None
        self.selection_rect_item = None
        self.last_click_pos = None
        
        self.setup_ui()
        self.setup_context_menu()
        
    def setup_context_menu(self):
        """Setup right-click context menu for the plot"""
        # Set context menu policy on the plot widget itself
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
        
        self.context_menu.addSeparator()
        
        self.delete_qual_action = QAction("Delete All Qualifying Points", self)
        self.delete_qual_action.triggered.connect(lambda: self.delete_all_points_for_session("qual"))
        self.context_menu.addAction(self.delete_qual_action)
        
        self.delete_race_action = QAction("Delete All Race Points", self)
        self.delete_race_action.triggered.connect(lambda: self.delete_all_points_for_session("race"))
        self.context_menu.addAction(self.delete_race_action)
        
    def show_context_menu(self, pos):
        """Show the context menu at the given position"""
        # Convert position to global coordinates
        global_pos = self.plot_widget.mapToGlobal(pos)
        self.context_menu.exec_(global_pos)
    
    def toggle_selection_mode(self, enabled):
        """Toggle selection mode on/off"""
        self.selection_mode = enabled
        if enabled:
            self.selection_mode_action.setText("Disable Selection Mode")
            self.setCursor(Qt.CrossCursor)
        else:
            self.selection_mode_action.setText("Enable Selection Mode (Click to select)")
            self.setCursor(Qt.ArrowCursor)
            self.clear_selection()
    
    def get_all_data_points_with_ids(self):
        """Get all data points with their IDs for the current track and selected classes"""
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
        """Select all visible data points on the graph"""
        self.clear_selection()
        
        all_points = []
        
        if self.show_qualifying:
            for point_data in self.qual_points_data:
                point_id = point_data[0]
                ratio = point_data[1]
                lap_time = point_data[2]
                all_points.append((point_id, ratio, lap_time, 'qual'))
        
        if self.show_race:
            for point_data in self.race_points_data:
                point_id = point_data[0]
                ratio = point_data[1]
                lap_time = point_data[2]
                all_points.append((point_id, ratio, lap_time, 'race'))
        
        if self.show_user_points and self.unknown_points_data:
            for point_data in self.unknown_points_data:
                point_id = point_data[0]
                ratio = point_data[1]
                lap_time = point_data[2]
                all_points.append((point_id, ratio, lap_time, 'unknown'))
        
        for point_id, ratio, lap_time, session_type in all_points:
            self.selected_point_ids.add(point_id)
        
        self.update_selected_markers()
        
        count = len(self.selected_point_ids)
        if count > 0:
            parent = self.parent()
            if hasattr(parent, 'info_text'):
                parent.info_text.setText(f"Selected {count} point(s). Right-click to delete selected points.")
    
    def clear_selection(self):
        """Clear all point selections"""
        self.selected_point_ids.clear()
        self.update_selected_markers()
        parent = self.parent()
        if hasattr(parent, 'info_text'):
            parent.info_text.setText("Selection cleared. Click on any data point to see its details.")
    
    def update_selected_markers(self):
        """Update the visual markers for selected points"""
        # Remove existing markers
        for marker in self.selected_point_markers:
            self._safe_remove_item(marker)
        self.selected_point_markers.clear()
        
        # Add markers for selected points
        selected_points = []
        
        # Collect selected points from all categories
        for point_data in self.qual_points_data:
            if point_data[0] in self.selected_point_ids:
                selected_points.append((point_data[1], point_data[2], '#00FF00'))
        
        for point_data in self.race_points_data:
            if point_data[0] in self.selected_point_ids:
                selected_points.append((point_data[1], point_data[2], '#00FF00'))
        
        for point_data in self.unknown_points_data:
            if point_data[0] in self.selected_point_ids:
                selected_points.append((point_data[1], point_data[2], '#00FF00'))
        
        # Create markers for selected points
        if selected_points:
            ratios = [p[0] for p in selected_points]
            times = [p[1] for p in selected_points]
            marker = pg.ScatterPlotItem(ratios, times, brush=pg.mkBrush('#00FF00'), 
                                         size=14, symbol='o', pen=pg.mkPen('white', width=2))
            self.plot.addItem(marker)
            self.selected_point_markers.append(marker)
    
    def delete_selected_points(self):
        """Delete all selected points from the database and graph"""
        if not self.selected_point_ids:
            QMessageBox.warning(self, "No Selection", 
                "No points selected. Right-click and use 'Select All Points' or click points while in selection mode.")
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
        failed_count = 0
        
        try:
            for point_id in point_ids:
                try:
                    # Delete the data point
                    cursor.execute("DELETE FROM data_points WHERE id = ?", (point_id,))
                    if cursor.rowcount > 0:
                        deleted_count += 1
                    else:
                        failed_count += 1
                except sqlite3.IntegrityError as e:
                    # Foreign key constraint - inform user
                    failed_count += 1
                    QMessageBox.warning(self, "Cannot Delete",
                        f"Point ID {point_id} is referenced by other data and cannot be deleted.\n\nError: {str(e)}")
            
            conn.commit()
            
            if deleted_count > 0:
                QMessageBox.information(self, "Deletion Complete",
                    f"Successfully deleted {deleted_count} data point(s).\nFailed: {failed_count}")
                
                # Clear selection
                self.selected_point_ids.clear()
                self.update_selected_markers()
                
                # Emit signal that points were deleted
                deleted_info = []
                for point_id in point_ids:
                    if point_id in [p[0] for p in self.qual_points_data]:
                        deleted_info.append((point_id, 'qual'))
                    elif point_id in [p[0] for p in self.race_points_data]:
                        deleted_info.append((point_id, 'race'))
                self.points_deleted.emit(deleted_info)
                
                # Refresh data and graph
                self.load_data()
                self.full_refresh()
                
                # Notify parent to reload formulas
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
    
    def delete_all_points_for_session(self, session_type: str):
        """Delete all points of a specific session type for the current track and selected classes"""
        if not self.current_track or not self.selected_classes:
            QMessageBox.warning(self, "No Track/Class", "Please select a track and vehicle class first.")
            return
        
        vehicle_classes = self._get_vehicles_for_classes(self.selected_classes)
        if not vehicle_classes:
            QMessageBox.warning(self, "No Classes", "No vehicle classes selected.")
            return
        
        count = 0
        if session_type == 'qual':
            count = len(self.qual_points_data)
        else:
            count = len(self.race_points_data)
        
        if count == 0:
            QMessageBox.information(self, "No Points", f"No {session_type.upper()} points to delete for this track/class.")
            return
        
        reply = QMessageBox.question(self, f"Delete All {session_type.upper()} Points",
            f"Delete all {count} {session_type.upper()} data point(s) for track '{self.current_track}'?\n\nThis action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No)
        
        if reply != QMessageBox.Yes:
            return
        
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        
        placeholders = ','.join('?' * len(vehicle_classes))
        query = f"""
            DELETE FROM data_points 
            WHERE track = ? AND vehicle_class IN ({placeholders}) AND session_type = ?
        """
        
        try:
            cursor.execute(query, [self.current_track] + vehicle_classes + [session_type])
            deleted_count = cursor.rowcount
            conn.commit()
            
            QMessageBox.information(self, "Deletion Complete",
                f"Successfully deleted {deleted_count} {session_type.upper()} data point(s).")
            
            # Refresh data and graph
            self.load_data()
            self.full_refresh()
            
            # Notify parent to reload formulas
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
        
        # Add toolbar for selection controls
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
        
        self.clear_selection_btn = QPushButton("Clear Selection")
        self.clear_selection_btn.clicked.connect(self.clear_selection)
        toolbar_layout.addWidget(self.clear_selection_btn)
        
        self.delete_selected_btn = QPushButton("Delete Selected")
        self.delete_selected_btn.setStyleSheet("background-color: #f44336;")
        self.delete_selected_btn.clicked.connect(self.delete_selected_points)
        toolbar_layout.addWidget(self.delete_selected_btn)
        
        toolbar_layout.addStretch()
        
        self.delete_qual_btn = QPushButton("Delete All Qualifying")
        self.delete_qual_btn.setStyleSheet("background-color: #f44336;")
        self.delete_qual_btn.clicked.connect(lambda: self.delete_all_points_for_session("qual"))
        toolbar_layout.addWidget(self.delete_qual_btn)
        
        self.delete_race_btn = QPushButton("Delete All Race")
        self.delete_race_btn.setStyleSheet("background-color: #f44336;")
        self.delete_race_btn.clicked.connect(lambda: self.delete_all_points_for_session("race"))
        toolbar_layout.addWidget(self.delete_race_btn)
        
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
        
        # Connect mouse events for point selection
        self.plot.scene().sigMouseClicked.connect(self.on_plot_click)
        
        layout.addWidget(self.plot_widget)
        
        info_layout = QHBoxLayout()
        self.formula_label = QLabel("")
        self.formula_label.setStyleSheet("color: #888; font-size: 10px; font-family: monospace;")
        info_layout.addWidget(self.formula_label)
        info_layout.addStretch()
        layout.addLayout(info_layout)
    
    def toggle_selection_mode_btn(self, checked):
        """Toggle selection mode from toolbar button"""
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
        """Set whether the formula is the default for a session type"""
        if session_type == "qual":
            self.qual_is_default = is_default
        else:
            self.race_is_default = is_default
    
    def _calculate_ratio_for_user_time(self, time_sec: float, session_type: str) -> float:
        if session_type == "qual":
            a, b = self.qual_a, self.qual_b
        else:
            a, b = self.race_a, self.race_b
        return ratio_from_time(time_sec, a, b)
    
    def select_track(self):
        if not self.all_tracks:
            QMessageBox.warning(self, "No Tracks", "No tracks available in database.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Select Track")
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)
        list_widget = QListWidget()
        list_widget.setSelectionMode(QAbstractItemView.SingleSelection)
        for track in self.all_tracks:
            list_widget.addItem(track)
        items = list_widget.findItems(self.current_track, Qt.MatchExactly)
        if items:
            list_widget.setCurrentItem(items[0])
        layout.addWidget(list_widget)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec_() == QDialog.Accepted and list_widget.currentItem():
            selected = list_widget.currentItem().text()
            if selected != self.current_track:
                self.current_track = selected
                self.load_data()
                self.update_graph()
                self.data_updated.emit()
    
    def select_classes(self):
        if not self.all_classes:
            QMessageBox.warning(self, "No Classes", "No vehicle classes available in database.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Select Vehicle Classes")
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)
        label = QLabel("Select vehicle classes to display:")
        layout.addWidget(label)
        list_widget = QListWidget()
        list_widget.setSelectionMode(QAbstractItemView.MultiSelection)
        for cls in self.all_classes:
            item = QListWidgetItem(cls)
            list_widget.addItem(item)
            if cls in self.selected_classes:
                item.setSelected(True)
        layout.addWidget(list_widget)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec_() == QDialog.Accepted:
            self.selected_classes = [item.text() for item in list_widget.selectedItems()]
            if not self.selected_classes:
                self.selected_classes = self.all_classes.copy()
            self.load_data()
            self.update_graph()
            self.data_updated.emit()
    
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
    
    def set_user_history(self, session_type: str, history: list):
        if session_type == "qual":
            self.user_qual_history = history
        else:
            self.user_race_history = history
        self.update_graph()
    
    def set_median_time(self, session_type: str, median_time: float):
        if session_type == "qual":
            self.median_qual_time = median_time
            if median_time > 0:
                self.median_qual_ratio = self._calculate_ratio_for_user_time(median_time, "qual")
        else:
            self.median_race_time = median_time
            if median_time > 0:
                self.median_race_ratio = self._calculate_ratio_for_user_time(median_time, "race")
        self.update_graph()
    
    def get_user_qual_time(self) -> float:
        return self.user_qual_time
    
    def get_user_race_time(self) -> float:
        return self.user_race_time
    
    def get_median_qual_time(self) -> float:
        return self.median_qual_time
    
    def get_median_race_time(self) -> float:
        return self.median_race_time
    
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
        
        # Convert to numpy arrays for pyqtgraph
        qual_times_array = np.array(qual_times)
        race_times_array = np.array(race_times)
        
        # Determine pen styles based on whether formulas are default
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
        
        quali_points = points_data.get('quali', [])
        if self.show_qualifying and quali_points:
            r = [p[0] for p in quali_points]
            t = [p[1] for p in quali_points]
            if self.qual_scatter is None:
                self.qual_scatter = pg.ScatterPlotItem(r, t, brush=pg.mkBrush('#FFFF00'), size=8, symbol='o', pen=pg.mkPen('white', width=1))
                self.plot.addItem(self.qual_scatter)
            else:
                if self.qual_scatter.scene() is None:
                    self.qual_scatter = pg.ScatterPlotItem(r, t, brush=pg.mkBrush('#FFFF00'), size=8, symbol='o', pen=pg.mkPen('white', width=1))
                    self.plot.addItem(self.qual_scatter)
                else:
                    self.qual_scatter.setData(r, t)
                    self.qual_scatter.setVisible(True)
        elif self.qual_scatter is not None:
            self.qual_scatter.setVisible(False)
        
        race_points = points_data.get('race', [])
        if self.show_race and race_points:
            r = [p[0] for p in race_points]
            t = [p[1] for p in race_points]
            if self.race_scatter is None:
                self.race_scatter = pg.ScatterPlotItem(r, t, brush=pg.mkBrush('#FF6600'), size=8, symbol='s', pen=pg.mkPen('white', width=1))
                self.plot.addItem(self.race_scatter)
            else:
                if self.race_scatter.scene() is None:
                    self.race_scatter = pg.ScatterPlotItem(r, t, brush=pg.mkBrush('#FF6600'), size=8, symbol='s', pen=pg.mkPen('white', width=1))
                    self.plot.addItem(self.race_scatter)
                else:
                    self.race_scatter.setData(r, t)
                    self.race_scatter.setVisible(True)
        elif self.race_scatter is not None:
            self.race_scatter.setVisible(False)
        
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
        
        # Handle user history points - history entries are (lap_time, ratio) or (lap_time, ratio, timestamp)
        qual_user_points = []
        race_user_points = []
        
        for entry in self.user_qual_history:
            if len(entry) >= 2:
                lap_time = entry[0]
                ratio = entry[1]
                if lap_time > 0 and ratio is not None:
                    qual_user_points.append((ratio, lap_time))
        
        for entry in self.user_race_history:
            if len(entry) >= 2:
                lap_time = entry[0]
                ratio = entry[1]
                if lap_time > 0 and ratio is not None:
                    race_user_points.append((ratio, lap_time))
        
        # Also include current user point if not in history
        if self.user_qual_time and self.user_qual_ratio:
            current_in_history = any(abs(p[1] - self.user_qual_time) < 0.01 for p in qual_user_points)
            if not current_in_history:
                qual_user_points.append((self.user_qual_ratio, self.user_qual_time))
        
        if self.user_race_time and self.user_race_ratio:
            current_in_history = any(abs(p[1] - self.user_race_time) < 0.01 for p in race_user_points)
            if not current_in_history:
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
                for i, (ratio_val, time_val) in enumerate(median_points):
                    label_text = "Median Qual" if i == 0 and self.median_qual_time else "Median Race"
                    if i == 0 and not self.median_qual_time:
                        label_text = "Median Race"
                    text_item = pg.TextItem(text=f"  {label_text}", color='#FF00FF', anchor=(0, 0.5))
                    text_item.setPos(ratio_val, time_val)
                    self.plot.addItem(text_item)
            else:
                if self.median_qual_point.scene() is None:
                    self.median_qual_point = pg.ScatterPlotItem(r, t, brush=pg.mkBrush('#FF00FF'), size=14, symbol='d', pen=pg.mkPen('white', width=2))
                    self.plot.addItem(self.median_qual_point)
                else:
                    self.median_qual_point.setData(r, t)
                    self.median_qual_point.setVisible(True)
        elif self.median_qual_point is not None:
            self.median_qual_point.setVisible(False)
        
        # Current user point (highlighted) - use green triangle
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
                
                # Update existing labels or create new ones
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
        
        # Update selected markers after redrawing points
        self.update_selected_markers()
        
        self._safe_remove_legend()
        
        self.legend = self.plot.addLegend()
        
        qual_label = f'Qualifying: {get_formula_string(self.qual_a, self.qual_b)}'
        if self.qual_is_default:
            qual_label += " (default)"
        
        race_label = f'Race: {get_formula_string(self.race_a, self.race_b)}'
        if self.race_is_default:
            race_label += " (default)"
        
        if self.show_qualifying and self.qual_curve is not None and self.qual_curve.scene() is not None:
            self.legend.addItem(self.qual_curve, qual_label)
        if self.show_race and self.race_curve is not None and self.race_curve.scene() is not None:
            self.legend.addItem(self.race_curve, race_label)
        if self.show_qualifying and quali_points and self.qual_scatter is not None and self.qual_scatter.scene() is not None:
            self.legend.addItem(self.qual_scatter, f'Qual Data ({len(quali_points)})')
        if self.show_race and race_points and self.race_scatter is not None and self.race_scatter.scene() is not None:
            self.legend.addItem(self.race_scatter, f'Race Data ({len(race_points)})')
        if unknown_points and self.unknown_scatter is not None and self.unknown_scatter.scene() is not None:
            self.legend.addItem(self.unknown_scatter, f'Unknown ({len(unknown_points)})')
        if all_user_points and self.user_qual_historical is not None and self.user_qual_historical.scene() is not None:
            self.legend.addItem(self.user_qual_historical, f'Your Lap Times ({len(all_user_points)})')
        if median_points and self.median_qual_point is not None and self.median_qual_point.scene() is not None:
            self.legend.addItem(self.median_qual_point, 'Median Lap Time')
        if current_user_points and self.user_qual_point is not None and self.user_qual_point.scene() is not None:
            self.legend.addItem(self.user_qual_point, 'Latest Lap')
        
        qual_info = ""
        race_info = ""
        if self.user_qual_time and self.user_qual_ratio:
            qual_minutes = int(self.user_qual_time) // 60
            qual_seconds = self.user_qual_time % 60
            qual_info = f"Latest Qual: {qual_minutes}:{qual_seconds:06.3f}s -> R={self.user_qual_ratio:.4f}"
        if self.user_race_time and self.user_race_ratio:
            race_minutes = int(self.user_race_time) // 60
            race_seconds = self.user_race_time % 60
            race_info = f"Latest Race: {race_minutes}:{race_seconds:06.3f}s -> R={self.user_race_ratio:.4f}"
        separator = "  |  " if qual_info and race_info else ""
        median_info = ""
        if self.median_qual_time:
            median_minutes = int(self.median_qual_time) // 60
            median_seconds = self.median_qual_time % 60
            median_info += f"Median Qual: {median_minutes}:{median_seconds:06.3f}s"
        if self.median_race_time:
            if median_info:
                median_info += " | "
            median_minutes = int(self.median_race_time) // 60
            median_seconds = self.median_race_time % 60
            median_info += f"Median Race: {median_minutes}:{median_seconds:06.3f}s"
        separator2 = "  |  " if (qual_info or race_info) and median_info else ""
        self.formula_label.setText(f"{qual_info}{separator}{race_info}{separator2}{median_info}")
    
    def on_plot_click(self, event):
        """Handle click on the plot for point selection"""
        if self.plot.scene().mouseGrabberItem() is not None:
            return
        
        pos = event.scenePos()
        mouse_point = self.plot.vb.mapSceneToView(pos)
        
        # Get all points with their IDs
        all_points = []
        for point_data in self.qual_points_data:
            point_id, ratio, lap_time = point_data
            all_points.append((point_id, ratio, lap_time, 'qual'))
        
        for point_data in self.race_points_data:
            point_id, ratio, lap_time = point_data
            all_points.append((point_id, ratio, lap_time, 'race'))
        
        for point_data in self.unknown_points_data:
            point_id, ratio, lap_time = point_data
            all_points.append((point_id, ratio, lap_time, 'unknown'))
        
        if not all_points:
            return
        
        # Find the closest point within distance threshold
        min_dist = float('inf')
        closest_point = None
        threshold = 0.05  # Ratio distance threshold
        
        for point_id, ratio, lap_time, session_type in all_points:
            dx = ratio - mouse_point.x()
            dy = (lap_time - mouse_point.y()) / 10  # Scale to make distance reasonable
            dist = (dx * dx + dy * dy) ** 0.5
            if dist < min_dist and dist < threshold:
                min_dist = dist
                closest_point = (point_id, ratio, lap_time, session_type)
        
        if closest_point:
            point_id, ratio, lap_time, session_type = closest_point
            
            # Check if Ctrl or Shift is pressed for multi-selection
            modifiers = QApplication.keyboardModifiers()
            
            if modifiers & Qt.ControlModifier or modifiers & Qt.ShiftModifier:
                # Toggle selection
                if point_id in self.selected_point_ids:
                    self.selected_point_ids.remove(point_id)
                else:
                    self.selected_point_ids.add(point_id)
            else:
                # Single click - clear other selections and select this one
                # But only if not in selection mode
                if not self.selection_mode:
                    self.selected_point_ids.clear()
                    self.selected_point_ids.add(point_id)
            
            self.update_selected_markers()
            
            # Update info text
            minutes = int(lap_time) // 60
            seconds = lap_time % 60
            count = len(self.selected_point_ids)
            parent = self.parent()
            if count > 1 and hasattr(parent, 'info_text'):
                parent.info_text.setText(f"{count} points selected. Right-click for delete options.")
            elif hasattr(parent, 'info_text'):
                parent.info_text.setText(
                    f"Point ID: {point_id} | Session: {session_type} | "
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
