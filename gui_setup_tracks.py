#!/usr/bin/env python3
"""
Track Names Management Tab for Setup Manager (Tkinter version)
Allows renaming and merging track entries in the database
Shows only database tracks (what dyn_ai and dyn_ai_visualizer actually use)
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import sqlite3
import re
from pathlib import Path
from typing import List, Dict, Set, Tuple, Optional

from core_track_utils import normalize_track_from_path
from core_config import get_base_path
from core_track_scanner import scan_tracks_from_database


class TrackManagementTab(tk.Frame):
    """Track names management tab - allows fixing and normalizing track names"""
    
    def __init__(self, parent, db_path: str):
        super().__init__(parent)
        self.parent = parent
        self.db_path = db_path
        self.tracks = []  # List of track names from database
        self.selected_track = None
        self.gtr2_base_path = get_base_path()
        
        self.configure(bg='#1e1e1e')
        self.setup_ui()
        self.refresh_track_list()
    
    def setup_ui(self):
        # Main content - split view
        paned = tk.PanedWindow(self, orient=tk.HORIZONTAL, bg='#1e1e1e', sashwidth=2)
        paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Left panel - track list
        left_frame = tk.Frame(paned, bg='#1e1e1e')
        paned.add(left_frame, width=350)
        
        title_frame = tk.Frame(left_frame, bg='#1e1e1e')
        title_frame.pack(fill=tk.X, pady=(0, 5))
        
        tk.Label(title_frame, text="Tracks in Database:", bg='#1e1e1e', fg='white',
                 font=('Arial', 10, 'bold')).pack(side=tk.LEFT)
        
        self.track_count_label = tk.Label(title_frame, text="(0 tracks)", bg='#1e1e1e', fg='#888',
                                           font=('Arial', 9))
        self.track_count_label.pack(side=tk.LEFT, padx=(10, 0))
        
        list_container = tk.Frame(left_frame, bg='#1e1e1e')
        list_container.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = tk.Scrollbar(list_container)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.track_listbox = tk.Listbox(list_container, bg='#2b2b2b', fg='#4CAF50',
                                         font=('Courier', 10), height=15,
                                         yscrollcommand=scrollbar.set)
        self.track_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.track_listbox.yview)
        self.track_listbox.bind('<<ListboxSelect>>', self.on_track_selected)
        
        # Refresh button below the list
        refresh_list_btn = tk.Button(left_frame, text="Refresh List", bg='#2196F3', fg='white',
                                      font=('Arial', 10), relief=tk.FLAT, padx=15, pady=4,
                                      command=self.refresh_track_list)
        refresh_list_btn.pack(pady=(10, 0))
        
        # Right panel - actions
        right_frame = tk.Frame(paned, bg='#1e1e1e')
        paned.add(right_frame, width=450)
        
        # Current track info
        info_group = tk.LabelFrame(right_frame, text="Selected Track", 
                                    bg='#1e1e1e', fg='#FFA500')
        info_group.pack(fill=tk.X, pady=(0, 10))
        
        self.track_info_label = tk.Label(info_group, text="No track selected", 
                                          bg='#1e1e1e', fg='white',
                                          font=('Courier', 10), wraplength=430)
        self.track_info_label.pack(padx=10, pady=10)
        
        # Browse AIW File section
        browse_group = tk.LabelFrame(right_frame, text="Get Canonical Name from AIW File", 
                                      bg='#1e1e1e', fg='#2196F3')
        browse_group.pack(fill=tk.X, pady=(0, 10))
        
        browse_frame = tk.Frame(browse_group, bg='#1e1e1e')
        browse_frame.pack(padx=10, pady=10, fill=tk.X)
        
        tk.Label(browse_frame, text="AIW File Path:", bg='#1e1e1e', fg='white').pack(anchor=tk.W)
        
        browse_path_frame = tk.Frame(browse_frame, bg='#1e1e1e')
        browse_path_frame.pack(fill=tk.X, pady=5)
        
        self.aiw_path_var = tk.StringVar()
        self.aiw_path_entry = tk.Entry(browse_path_frame, textvariable=self.aiw_path_var,
                                        bg='#3c3c3c', fg='white', font=('Courier', 10))
        self.aiw_path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        browse_btn = tk.Button(browse_path_frame, text="Browse...", 
                                bg='#2196F3', fg='white',
                                command=self.browse_aiw_file)
        browse_btn.pack(side=tk.RIGHT, padx=(5, 0))
        
        self.canonical_preview_label = tk.Label(browse_frame, text="Canonical name: (none)", 
                                                 bg='#1e1e1e', fg='#FFA500',
                                                 font=('Courier', 10))
        self.canonical_preview_label.pack(anchor=tk.W, pady=(5, 0))
        
        use_canonical_btn = tk.Button(browse_frame, text="Use This Canonical Name for Selected Track", 
                                       bg='#4CAF50', fg='white',
                                       command=self.use_canonical_name)
        use_canonical_btn.pack(pady=(10, 0))
        
        # Rename section
        rename_group = tk.LabelFrame(right_frame, text="Rename Track", 
                                      bg='#1e1e1e', fg='#4CAF50')
        rename_group.pack(fill=tk.X, pady=(0, 10))
        
        rename_frame = tk.Frame(rename_group, bg='#1e1e1e')
        rename_frame.pack(padx=10, pady=10, fill=tk.X)
        
        tk.Label(rename_frame, text="New canonical name (e.g., Estoril/3Estoril):", 
                 bg='#1e1e1e', fg='white').pack(anchor=tk.W)
        self.rename_entry = tk.Entry(rename_frame, bg='#3c3c3c', fg='white', 
                                      font=('Courier', 10))
        self.rename_entry.pack(fill=tk.X, pady=5)
        
        rename_btn = tk.Button(rename_frame, text="Rename Track", 
                                bg='#2196F3', fg='white',
                                command=self.rename_track)
        rename_btn.pack(pady=5)
        
        # Merge section
        merge_group = tk.LabelFrame(right_frame, text="Merge Tracks", 
                                     bg='#1e1e1e', fg='#FF9800')
        merge_group.pack(fill=tk.X, pady=(0, 10))
        
        merge_frame = tk.Frame(merge_group, bg='#1e1e1e')
        merge_frame.pack(padx=10, pady=10, fill=tk.X)
        
        tk.Label(merge_frame, text="Target track (keep this one):", 
                 bg='#1e1e1e', fg='white').pack(anchor=tk.W)
        self.merge_target_combo = ttk.Combobox(merge_frame, state="readonly", width=45)
        self.merge_target_combo.pack(fill=tk.X, pady=5)
        
        tk.Label(merge_frame, text="Tracks to merge into target (select multiple):", 
                 bg='#1e1e1e', fg='white').pack(anchor=tk.W)
        self.merge_sources_listbox = tk.Listbox(merge_frame, bg='#2b2b2b', fg='white',
                                                  selectmode=tk.EXTENDED, height=6)
        self.merge_sources_listbox.pack(fill=tk.BOTH, expand=True, pady=5)
        
        merge_btn = tk.Button(merge_frame, text="Merge Selected into Target", 
                               bg='#FF9800', fg='white',
                               command=self.merge_tracks)
        merge_btn.pack(pady=5)
        
        # Delete Track section - compact version
        delete_group = tk.LabelFrame(right_frame, text="Delete Track", 
                                      bg='#1e1e1e', fg='#f44336')
        delete_group.pack(fill=tk.X, pady=(0, 10))
        
        delete_frame = tk.Frame(delete_group, bg='#1e1e1e')
        delete_frame.pack(padx=10, pady=8, fill=tk.X)
        
        delete_btn = tk.Button(delete_frame, text="Delete Selected Track", 
                                bg='#f44336', fg='white', font=('Arial', 10, 'bold'),
                                command=self.delete_selected_track)
        delete_btn.pack()
        
        # Statistics
        self.stats_label = tk.Label(right_frame, text="", bg='#1e1e1e', fg='#888',
                                     font=('Arial', 9))
        self.stats_label.pack(pady=10)
    
    def browse_aiw_file(self):
        """Browse for an AIW file and extract its canonical name"""
        initial_dir = str(self.gtr2_base_path) if self.gtr2_base_path and self.gtr2_base_path.exists() else ""
        
        file_path = filedialog.askopenfilename(
            title="Select AIW File",
            initialdir=initial_dir,
            filetypes=[("AIW Files", "*.AIW"), ("AIW Files", "*.aiw"), ("All Files", "*.*")]
        )
        
        if not file_path:
            return
        
        self.aiw_path_var.set(file_path)
        canonical_name = self.get_canonical_name_from_aiw_path(Path(file_path))
        
        if canonical_name:
            self.canonical_preview_label.config(text=f"Canonical name: {canonical_name}", fg='#4CAF50')
        else:
            self.canonical_preview_label.config(text="Canonical name: (could not determine - AIW may not be in GTR2 folder)", fg='#f44336')
    
    def get_canonical_name_from_aiw_path(self, aiw_path: Path) -> Optional[str]:
        """Extract canonical name from an AIW file path."""
        if self.gtr2_base_path and self.gtr2_base_path.exists():
            try:
                rel_path = aiw_path.relative_to(self.gtr2_base_path)
                rel_str = str(rel_path).replace('\\', '/')
                canonical_id, folder_name, aiw_stem = normalize_track_from_path(rel_str)
                if canonical_id:
                    return canonical_id
            except ValueError:
                pass
        
        # Fallback: try to extract from the path itself
        path_str = str(aiw_path).replace('\\', '/')
        
        # Find GameData/Locations in the path
        match = re.search(r'(?:GameData|GAMEDATA)/(?:Locations|LOCATIONS)/([^/]+)/([^/]+)\.AIW', path_str, re.IGNORECASE)
        if match:
            folder = match.group(1)
            stem = match.group(2)
            return f"{folder}/{stem}"
        
        # Last resort: use parent folder name and file stem
        folder = aiw_path.parent.name
        stem = aiw_path.stem
        if folder and stem:
            return f"{folder}/{stem}"
        
        return None
    
    def use_canonical_name(self):
        """Use the browsed AIW file's canonical name for the selected track"""
        if not self.selected_track:
            messagebox.showwarning("No Selection", "Please select a track from the list first.")
            return
        
        canonical_name = self.canonical_preview_label.cget("text").replace("Canonical name: ", "")
        if not canonical_name or canonical_name == "(none)":
            messagebox.showwarning("No Canonical Name", "Please browse to an AIW file first.")
            return
        
        if canonical_name.startswith("Canonical name:"):
            messagebox.showwarning("Invalid", "Could not determine canonical name. Please browse to a valid AIW file.")
            return
        
        self.rename_entry.delete(0, tk.END)
        self.rename_entry.insert(0, canonical_name)
        
        result = messagebox.askyesno(
            "Apply Canonical Name",
            f"Set canonical name to:\n\n"
            f"  {canonical_name}\n\n"
            f"For track:\n\n"
            f"  {self.selected_track}\n\n"
            f"Do you want to rename now?"
        )
        
        if result:
            self.rename_track()
    
    def get_database_tracks(self) -> List[str]:
        """Get all unique track names from database"""
        return scan_tracks_from_database(self.db_path)
    
    def get_track_stats(self, track: str) -> Dict[str, int]:
        """Get statistics for a track"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        stats = {}
        
        cursor.execute("SELECT COUNT(*) FROM data_points WHERE track = ?", (track,))
        stats['data_points'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM race_sessions WHERE track_name = ?", (track,))
        stats['race_sessions'] = cursor.fetchone()[0]
        
        try:
            cursor.execute("SELECT COUNT(*) FROM formulas WHERE track = ?", (track,))
            stats['formulas'] = cursor.fetchone()[0]
        except sqlite3.OperationalError:
            stats['formulas'] = 0
        
        try:
            cursor.execute("SELECT COUNT(*) FROM user_laptimes WHERE track = ?", (track,))
            stats['user_laptimes'] = cursor.fetchone()[0]
        except sqlite3.OperationalError:
            stats['user_laptimes'] = 0
        
        conn.close()
        return stats
    
    def refresh_track_list(self):
        """Refresh the track list display"""
        self.track_listbox.delete(0, tk.END)
        self.tracks = self.get_database_tracks()
        
        self.merge_target_combo['values'] = self.tracks
        
        self.merge_sources_listbox.delete(0, tk.END)
        
        for i, track in enumerate(self.tracks):
            self.track_listbox.insert(tk.END, track)
            self.track_listbox.itemconfig(i, fg='#4CAF50')
        
        self.update_merge_sources_listbox()
        
        # Update title with count
        self.track_count_label.config(text=f"({len(self.tracks)} tracks)")
        
        self.stats_label.config(text=f"Total tracks in database: {len(self.tracks)}")
    
    def update_merge_sources_listbox(self):
        """Update the merge sources listbox (exclude selected track)"""
        self.merge_sources_listbox.delete(0, tk.END)
        for track in self.tracks:
            if track != self.selected_track:
                self.merge_sources_listbox.insert(tk.END, track)
    
    def on_track_selected(self, event=None):
        """Handle track selection"""
        selection = self.track_listbox.curselection()
        if not selection:
            return
        
        self.selected_track = self.tracks[selection[0]]
        stats = self.get_track_stats(self.selected_track)
        
        info = f"Track: {self.selected_track}\n\n"
        info += f"Data points: {stats['data_points']}\n"
        info += f"Race sessions: {stats['race_sessions']}\n"
        info += f"Formulas: {stats['formulas']}\n"
        info += f"User laptimes: {stats['user_laptimes']}"
        
        self.track_info_label.config(text=info)
        self.rename_entry.delete(0, tk.END)
        self.rename_entry.insert(0, self.selected_track)
        
        self.update_merge_sources_listbox()
    
    def rename_track(self):
        """Rename the selected track"""
        if not self.selected_track:
            messagebox.showwarning("No Selection", "Please select a track first.")
            return
        
        new_name = self.rename_entry.get().strip()
        if not new_name:
            messagebox.showwarning("Invalid Name", "Please enter a new track name.")
            return
        
        if new_name == self.selected_track:
            messagebox.showinfo("No Change", "New name is the same as current.")
            return
        
        if '/' not in new_name:
            result = messagebox.askyesno(
                "Non-Canonical Format",
                f"'{new_name}' is not in canonical format 'Folder/Stem'.\n\n"
                f"Example: 'Estoril/3Estoril'\n\n"
                f"Do you want to proceed anyway?"
            )
            if not result:
                return
        
        if new_name in self.tracks:
            result = messagebox.askyesno(
                "Track Exists",
                f"Track '{new_name}' already exists.\n\n"
                f"Do you want to MERGE '{self.selected_track}' into '{new_name}'?\n\n"
                f"This will move all data to the existing track and delete the old one."
            )
            if result:
                self.merge_tracks_impl(self.selected_track, new_name)
            return
        
        stats = self.get_track_stats(self.selected_track)
        result = messagebox.askyesno(
            "Confirm Rename",
            f"Rename track:\n\n"
            f"From: {self.selected_track}\n"
            f"To:   {new_name}\n\n"
            f"This will update:\n"
            f"  - {stats['data_points']} data points\n"
            f"  - {stats['race_sessions']} race sessions\n"
            f"  - {stats['formulas']} formulas\n"
            f"  - {stats['user_laptimes']} user laptimes\n\n"
            f"Continue?"
        )
        
        if result:
            self.do_rename(self.selected_track, new_name)
    
    def do_rename(self, old_name: str, new_name: str):
        """Execute the rename operation"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("UPDATE data_points SET track = ? WHERE track = ?", (new_name, old_name))
            data_points_updated = cursor.rowcount
            
            cursor.execute("UPDATE race_sessions SET track_name = ? WHERE track_name = ?", (new_name, old_name))
            race_sessions_updated = cursor.rowcount
            
            try:
                cursor.execute("UPDATE formulas SET track = ? WHERE track = ?", (new_name, old_name))
                formulas_updated = cursor.rowcount
            except sqlite3.OperationalError:
                formulas_updated = 0
            
            try:
                cursor.execute("UPDATE user_laptimes SET track = ? WHERE track = ?", (new_name, old_name))
                user_laptimes_updated = cursor.rowcount
            except sqlite3.OperationalError:
                user_laptimes_updated = 0
            
            conn.commit()
            
            messagebox.showinfo("Rename Complete", 
                f"Track renamed successfully!\n\n"
                f"Updated:\n"
                f"  - {data_points_updated} data points\n"
                f"  - {race_sessions_updated} race sessions\n"
                f"  - {formulas_updated} formulas\n"
                f"  - {user_laptimes_updated} user laptimes")
            
            self.refresh_track_list()
            self.selected_track = new_name
            
        except Exception as e:
            conn.rollback()
            messagebox.showerror("Rename Failed", f"Error: {str(e)}")
        finally:
            conn.close()
    
    def merge_tracks_impl(self, source_track: str, target_track: str) -> bool:
        """Merge source track into target track"""
        if source_track == target_track:
            return False
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("UPDATE data_points SET track = ? WHERE track = ?", (target_track, source_track))
            data_points_updated = cursor.rowcount
            
            cursor.execute("UPDATE race_sessions SET track_name = ? WHERE track_name = ?", (target_track, source_track))
            race_sessions_updated = cursor.rowcount
            
            try:
                cursor.execute("UPDATE formulas SET track = ? WHERE track = ?", (target_track, source_track))
                formulas_updated = cursor.rowcount
            except sqlite3.OperationalError:
                formulas_updated = 0
            
            try:
                cursor.execute("UPDATE user_laptimes SET track = ? WHERE track = ?", (target_track, source_track))
                user_laptimes_updated = cursor.rowcount
            except sqlite3.OperationalError:
                user_laptimes_updated = 0
            
            try:
                cursor.execute("DELETE FROM formulas WHERE track = ? AND track IS NOT NULL", (source_track,))
            except sqlite3.OperationalError:
                pass
            
            conn.commit()
            
            messagebox.showinfo("Merge Complete", 
                f"Merged '{source_track}' into '{target_track}'\n\n"
                f"Updated:\n"
                f"  - {data_points_updated} data points\n"
                f"  - {race_sessions_updated} race sessions\n"
                f"  - {formulas_updated} formulas\n"
                f"  - {user_laptimes_updated} user laptimes")
            
            return True
            
        except Exception as e:
            conn.rollback()
            messagebox.showerror("Merge Failed", f"Error: {str(e)}")
            return False
        finally:
            conn.close()
    
    def merge_tracks(self):
        """Merge selected tracks into target"""
        if not self.merge_target_combo.get():
            messagebox.showwarning("No Target", "Please select a target track.")
            return
        
        target = self.merge_target_combo.get()
        selection = self.merge_sources_listbox.curselection()
        
        if not selection:
            messagebox.showwarning("No Selection", "Please select tracks to merge.")
            return
        
        sources = [self.merge_sources_listbox.get(idx) for idx in selection]
        
        if target in sources:
            messagebox.showerror("Invalid Merge", "Target track cannot be in the merge list.")
            return
        
        result = messagebox.askyesno(
            "Confirm Merge",
            f"Merge the following tracks into '{target}'?\n\n"
            + "\n".join(f"  - {s}" for s in sources) + "\n\n"
            f"This action cannot be undone.\n\n"
            f"Continue?"
        )
        
        if not result:
            return
        
        for source in sources:
            self.merge_tracks_impl(source, target)
        
        self.refresh_track_list()
        self.merge_target_combo.set(target)
    
    def delete_selected_track(self):
        """Completely delete the selected track and all its associated data from the database"""
        if not self.selected_track:
            messagebox.showwarning("No Selection", "Please select a track to delete.")
            return
        
        stats = self.get_track_stats(self.selected_track)
        
        warning_text = f"Delete track '{self.selected_track}'?\n\n"
        
        if stats['data_points'] > 0:
            warning_text += f"Data points: {stats['data_points']}\n"
        if stats['race_sessions'] > 0:
            warning_text += f"Race sessions: {stats['race_sessions']}\n"
        if stats['formulas'] > 0:
            warning_text += f"Formulas: {stats['formulas']}\n"
        if stats['user_laptimes'] > 0:
            warning_text += f"User laptimes: {stats['user_laptimes']}\n"
        
        if stats['data_points'] == 0 and stats['race_sessions'] == 0 and stats['formulas'] == 0 and stats['user_laptimes'] == 0:
            warning_text += "\nThis track has no associated data.\n\n"
        
        warning_text += "\nTHIS ACTION CANNOT BE UNDONE!\n\nContinue?"
        
        result = messagebox.askyesno(
            "Confirm Delete - WARNING",
            warning_text,
            icon='warning'
        )
        
        if not result:
            return
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("DELETE FROM data_points WHERE track = ?", (self.selected_track,))
            data_deleted = cursor.rowcount
            
            cursor.execute("DELETE FROM race_sessions WHERE track_name = ?", (self.selected_track,))
            sessions_deleted = cursor.rowcount
            
            try:
                cursor.execute("DELETE FROM formulas WHERE track = ?", (self.selected_track,))
                formulas_deleted = cursor.rowcount
            except sqlite3.OperationalError:
                formulas_deleted = 0
            
            try:
                cursor.execute("DELETE FROM user_laptimes WHERE track = ?", (self.selected_track,))
                laptimes_deleted = cursor.rowcount
            except sqlite3.OperationalError:
                laptimes_deleted = 0
            
            conn.commit()
            
            messagebox.showinfo("Delete Complete", 
                f"Track '{self.selected_track}' has been deleted.\n\n"
                f"Deleted:\n"
                f"  - {data_deleted} data points\n"
                f"  - {sessions_deleted} race sessions\n"
                f"  - {formulas_deleted} formulas\n"
                f"  - {laptimes_deleted} user laptimes\n\n"
                f"The track will no longer appear in dyn_ai and dyn_ai_visualizer.")
            
            self.selected_track = None
            self.refresh_track_list()
            
        except Exception as e:
            conn.rollback()
            messagebox.showerror("Delete Failed", f"Error: {str(e)}")
        finally:
            conn.close()
