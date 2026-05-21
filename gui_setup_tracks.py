#!/usr/bin/env python3
"""
Track Names Management Tab for Setup Manager (Tkinter version)
Allows renaming and merging track entries in the database
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import sqlite3
from pathlib import Path
from typing import List, Dict, Set, Tuple, Optional

from core_track_utils import normalize_track_from_path
from core_config import get_base_path


class TrackManagementTab(tk.Frame):
    """Track names management tab - allows fixing and normalizing track names"""
    
    def __init__(self, parent, db_path: str):
        super().__init__(parent)
        self.parent = parent
        self.db_path = db_path
        self.tracks = []
        self.selected_track = None
        self.gtr2_base_path = get_base_path()
        
        self.configure(bg='#1e1e1e')
        self.setup_ui()
        self.refresh_track_list()
    
    def setup_ui(self):
        # Info header
        info_frame = tk.LabelFrame(self, text="Track Name Management", 
                                    bg='#1e1e1e', fg='#4CAF50',
                                    font=('Arial', 11, 'bold'))
        info_frame.pack(fill=tk.X, padx=10, pady=10)
        
        info_text = (
            "This tool helps fix inconsistent track names in the database.\n\n"
            "Track names come from AIW files like 'GAMEDATA/LOCATIONS/Estoril/3Estoril.AIW'\n"
            "The canonical format is 'Folder/Stem' (e.g., 'Estoril/3Estoril')\n\n"
            "You can:\n"
            "  - Browse to any AIW file to get its canonical name\n"
            "  - Rename individual tracks\n"
            "  - Merge multiple tracks into one\n"
            "  - Auto-fix common patterns"
        )
        info_label = tk.Label(info_frame, text=info_text, bg='#1e1e1e', fg='#888',
                               justify=tk.LEFT, font=('Arial', 10))
        info_label.pack(padx=15, pady=15)
        
        # Main content - split view
        paned = tk.PanedWindow(self, orient=tk.HORIZONTAL, bg='#1e1e1e', sashwidth=2)
        paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Left panel - track list
        left_frame = tk.Frame(paned, bg='#1e1e1e')
        paned.add(left_frame, width=300)
        
        tk.Label(left_frame, text="Tracks in Database:", bg='#1e1e1e', fg='white',
                 font=('Arial', 10, 'bold')).pack(anchor=tk.W, pady=(0, 5))
        
        list_container = tk.Frame(left_frame, bg='#1e1e1e')
        list_container.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = tk.Scrollbar(list_container)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.track_listbox = tk.Listbox(list_container, bg='#2b2b2b', fg='#4CAF50',
                                         font=('Courier', 10), 
                                         yscrollcommand=scrollbar.set)
        self.track_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.track_listbox.yview)
        self.track_listbox.bind('<<ListboxSelect>>', self.on_track_selected)
        
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
        
        # Auto-fix section
        autofix_group = tk.LabelFrame(right_frame, text="Auto-Fix", 
                                       bg='#1e1e1e', fg='#4CAF50')
        autofix_group.pack(fill=tk.X, pady=(0, 10))
        
        autofix_frame = tk.Frame(autofix_group, bg='#1e1e1e')
        autofix_frame.pack(padx=10, pady=10, fill=tk.X)
        
        self.suggested_fixes_text = tk.Text(autofix_frame, bg='#2b2b2b', fg='#4CAF50',
                                             font=('Courier', 9), height=8, wrap=tk.WORD)
        self.suggested_fixes_text.pack(fill=tk.BOTH, expand=True, pady=5)
        
        autofix_btn = tk.Button(autofix_frame, text="Find and Suggest Fixes", 
                                 bg='#4CAF50', fg='white',
                                 command=self.suggest_fixes)
        autofix_btn.pack(pady=5)
        
        apply_all_btn = tk.Button(autofix_frame, text="Apply All Suggested Fixes", 
                                   bg='#f44336', fg='white',
                                   command=self.apply_all_fixes)
        apply_all_btn.pack(pady=5)
        
        # Statistics
        self.stats_label = tk.Label(right_frame, text="", bg='#1e1e1e', fg='#888',
                                     font=('Arial', 9))
        self.stats_label.pack(pady=10)
        
        # Bottom buttons
        bottom_frame = tk.Frame(self, bg='#1e1e1e')
        bottom_frame.pack(fill=tk.X, padx=10, pady=10)
        
        refresh_btn = tk.Button(bottom_frame, text="Refresh List", 
                                 bg='#2196F3', fg='white',
                                 command=self.refresh_track_list)
        refresh_btn.pack(side=tk.LEFT, padx=5)
    
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
        import re
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
    
    def get_all_tracks(self) -> List[str]:
        """Get all unique track names from database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        tracks = set()
        
        cursor.execute("SELECT DISTINCT track FROM data_points WHERE track IS NOT NULL")
        for row in cursor.fetchall():
            if row[0]:
                tracks.add(row[0])
        
        try:
            cursor.execute("SELECT DISTINCT track FROM formulas WHERE track IS NOT NULL")
            for row in cursor.fetchall():
                if row[0]:
                    tracks.add(row[0])
        except sqlite3.OperationalError:
            pass
        
        cursor.execute("SELECT DISTINCT track_name FROM race_sessions WHERE track_name IS NOT NULL")
        for row in cursor.fetchall():
            if row[0]:
                tracks.add(row[0])
        
        try:
            cursor.execute("SELECT DISTINCT track FROM user_laptimes WHERE track IS NOT NULL")
            for row in cursor.fetchall():
                if row[0]:
                    tracks.add(row[0])
        except sqlite3.OperationalError:
            pass
        
        conn.close()
        return sorted(tracks)
    
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
        self.tracks = self.get_all_tracks()
        
        self.merge_target_combo['values'] = self.tracks
        
        self.merge_sources_listbox.delete(0, tk.END)
        
        for i, track in enumerate(self.tracks):
            self.track_listbox.insert(tk.END, track)
            
            if '/' not in track:
                self.track_listbox.itemconfig(i, fg='#FFA500')
            elif not track.split('/')[-1] or len(track.split('/')[-1]) < 2:
                self.track_listbox.itemconfig(i, fg='#f44336')
        
        for track in self.tracks:
            if track != self.selected_track:
                self.merge_sources_listbox.insert(tk.END, track)
        
        self.stats_label.config(text=f"Total tracks: {len(self.tracks)}")
    
    def on_track_selected(self, event=None):
        """Handle track selection"""
        selection = self.track_listbox.curselection()
        if not selection:
            return
        
        self.selected_track = self.tracks[selection[0]]
        stats = self.get_track_stats(self.selected_track)
        
        info = f"Canonical ID: {self.selected_track}\n\n"
        info += f"Data points: {stats['data_points']}\n"
        info += f"Race sessions: {stats['race_sessions']}\n"
        info += f"Formulas: {stats['formulas']}\n"
        info += f"User laptimes: {stats['user_laptimes']}"
        
        self.track_info_label.config(text=info)
        self.rename_entry.delete(0, tk.END)
        self.rename_entry.insert(0, self.selected_track)
    
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
    
    def suggest_fixes(self):
        """Find tracks that need fixing and suggest canonical names"""
        self.suggested_fixes_text.delete(1.0, tk.END)
        
        fixes = []
        
        for track in self.tracks:
            if '/' in track:
                continue
            
            parts = track.split('/')
            if len(parts) == 1:
                track_lower = track.lower()
                
                common_mappings = {
                    'estoril': ('Estoril', '3Estoril'),
                    'monza': ('Monza', 'Monza'),
                    'spa': ('Spa', 'Spa'),
                    'nurburgring': ('Nurburgring', 'Nurburgring'),
                    'silverstone': ('Silverstone', 'Silverstone'),
                    'laguna seca': ('LagunaSeca', 'LagunaSeca'),
                    'imola': ('Imola', 'Imola'),
                    'magny cours': ('MagnyCours', 'MagnyCours'),
                    'barcelona': ('Barcelona', 'Barcelona'),
                    'hungaroring': ('Hungaroring', 'Hungaroring'),
                    'interlagos': ('Interlagos', 'Interlagos'),
                    'melbourne': ('Melbourne', 'Melbourne'),
                    'montreal': ('Montreal', 'Montreal'),
                    'monaco': ('Monaco', 'Monaco'),
                    'suzuka': ('Suzuka', 'Suzuka'),
                    'valencia': ('Valencia', 'Valencia'),
                    'zandvoort': ('Zandvoort', 'Zandvoort'),
                    'donington': ('Donington', 'Donington'),
                    'brands hatch': ('BrandsHatch', 'BrandsHatch'),
                    'oschersleben': ('Oschersleben', 'OscherslebenA'),
                }
                
                matched = False
                for key, (folder, stem) in common_mappings.items():
                    if key in track_lower:
                        canonical = f"{folder}/{stem}"
                        fixes.append((track, canonical))
                        matched = True
                        break
                
                if not matched:
                    folder = track.replace(' ', '')
                    canonical = f"{folder}/{track}"
                    fixes.append((track, canonical))
        
        if fixes:
            self.suggested_fixes_text.insert(tk.END, "Suggested fixes:\n\n")
            for old, new in fixes:
                self.suggested_fixes_text.insert(tk.END, f"  {old}  ->  {new}\n")
            return fixes
        else:
            self.suggested_fixes_text.insert(tk.END, "All tracks appear to be in canonical format.\n\nNo fixes suggested.")
            return []
    
    def apply_all_fixes(self):
        """Apply all suggested fixes"""
        fixes = self.suggest_fixes()
        
        if not fixes:
            messagebox.showinfo("No Fixes", "No fixes to apply.")
            return
        
        result = messagebox.askyesno(
            "Apply All Fixes",
            f"Apply {len(fixes)} suggested fixes?\n\n"
            "This will rename multiple tracks. You can review each change.\n\n"
            "Continue?"
        )
        
        if not result:
            return
        
        applied = 0
        skipped = 0
        
        for old_name, new_name in fixes:
            if new_name in self.tracks:
                result = messagebox.askyesno(
                    "Track Exists",
                    f"'{new_name}' already exists.\n\n"
                    f"Do you want to MERGE '{old_name}' into '{new_name}'?"
                )
                if result:
                    if self.merge_tracks_impl(old_name, new_name):
                        applied += 1
                    else:
                        skipped += 1
            else:
                result = messagebox.askyesno(
                    "Rename Track",
                    f"Rename '{old_name}' to '{new_name}'?"
                )
                if result:
                    self.do_rename(old_name, new_name)
                    applied += 1
                else:
                    skipped += 1
        
        messagebox.showinfo("Auto-Fix Complete", 
            f"Applied {applied} fixes.\n"
            f"Skipped {skipped} fixes.\n\n"
            f"Click Refresh List to see changes.")
        
        self.refresh_track_list()
