import sys
import os
import datetime
import json
import traceback
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QPushButton,
    QLineEdit, QMessageBox, QHBoxLayout, QComboBox, QCompleter,
    QListWidget, QTabWidget, QListWidgetItem, QInputDialog, QFileDialog,
    QGridLayout, QGroupBox, QSpinBox, QScrollArea, QFrame, QMenu, QTextEdit, QDialog
)
from PyQt6.QtCore import Qt, QPropertyAnimation, QPoint, QTimer, QSize, QModelIndex, QParallelAnimationGroup
from PyQt6.QtGui import QColor, QPalette, QFont, QKeySequence, QShortcut, QAction
from models import Competitor, HistoryItem
import persistence
from PyQt6.QtWidgets import QTabBar, QCheckBox, QStylePainter, QStyleOptionTab, QStyle, QSizePolicy, QTableWidget, QHeaderView, QTableWidgetItem

class ExpandingTabBar(QTabBar):
    def tabSizeHint(self, index):
        # Calculate width to distribute space evenly
        width = max(100, self.parent().width() / max(1, self.count()))
        return QSize(int(width), super().tabSizeHint(index).height())

    def paintEvent(self, event):
        painter = QStylePainter(self)
        option = QStyleOptionTab()
        
        for index in range(self.count()):
            self.initStyleOption(option, index)
            
            # Custom styling
            if self.currentIndex() == index:
                option.palette.setColor(QPalette.ColorRole.Window, QColor("#555555"))
                option.palette.setColor(QPalette.ColorRole.WindowText, QColor("#FFFFFF"))
            else:
                option.palette.setColor(QPalette.ColorRole.Window, QColor("#333333"))
                option.palette.setColor(QPalette.ColorRole.WindowText, QColor("#CCCCCC"))
            
            painter.drawControl(QStyle.ControlElement.CE_TabBarTabShape, option)
            painter.drawControl(QStyle.ControlElement.CE_TabBarTabLabel, option)

class CongressTracker(QWidget):
    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Always reflow both lists
        self.update_lists()
        # Also refresh the tab bar sizing
        tb = self.tabs.tabBar()
        tb.updateGeometry()
        tb.update()
        self.tabs.updateGeometry()

    def __init__(self):
        super().__init__()
        self.load_config()


        # Window settings
        self.setup_fonts()
        self.setWindowTitle("Congress Tracker")
        self.setGeometry(100, 100, 600, 400)

        # Data initialization
        self.competitors = []
        self.entered_names = []
        self.pending_speech_competitor = None
        self.pending_question_competitor = None
        self.csv_file_path = None
        self.current_round = 0
        self.history = []
        self.speech_recency_order = []
        self.question_recency_order = []

        # Resolution system initialization
        self.current_resolution = ""
        self.resolution_list = []
        self.current_side = "Affirmative"
        self.tracking_started = False

        # Initialize UI elements that will be created in init_ui
        self.side_indicator = None
        self.current_resolution_label = None
        self.next_speaker_label = None
        self.resolution_header = None

        # Initialize UI
        
        self.init_ui()
        self.apply_dark_mode()
        self.setup_timer()

        self.update_lists()
        self.setup_keyboard_shortcuts()

        # Initial updates
        self.load_resolution_state_on_startup()
        self.update_status(loaded=False)
        self.timer_checkbox.stateChanged.connect(self.on_timer_toggle)

        # Connect signals
        self.speech_log_button.clicked.connect(self.on_speech_log_button_clicked)
        self.question_log_button.clicked.connect(self.on_question_log_button_clicked)
        self.manual_reordering_speech_enabled  = True
        self.manual_reordering_question_enabled = True

        # Double‑click handlers (now lists have items!)
        self.speech_list.doubleClicked.connect(self._on_speech_index_double_clicked)
        self.question_list.doubleClicked.connect(self._on_question_index_double_clicked)

    def _on_speech_index_double_clicked(self, index: QModelIndex):
        """Adapter from QListView's doubleClicked to your existing handler."""
        # FIX #3: Only allow double-click after tracking has started
        if not self.tracking_started:
            return
            
        print("_on_speech_index_double_clicked was called")
        item = self.speech_list.item(index.row())
        if item:
            self.on_speech_list_double_clicked(item)

    def _on_question_index_double_clicked(self, index: QModelIndex):
        # FIX #3: Only allow double-click after tracking has started
        if not self.tracking_started:
            return
            
        item = self.question_list.item(index.row())
        if item:
            self.on_question_list_double_clicked(item)

    def on_speech_list_double_clicked(self, item):
        # 1) Get competitor
        name = item.data(Qt.ItemDataRole.UserRole) or item.text()
        if not name:
            return
        comp = next((c for c in self.competitors if c.name == name), None)
        if not comp:
            return
        self.pending_speech_competitor = comp

        # 2) Show input row & populate combo
        self.speech_input_container.setVisible(True)
        self.speech_name_input.clear()
        self.speech_name_input.addItems(self.entered_names)
        self.speech_name_input.setCurrentText(name)
        self.speech_name_input.setFocus()

        # 3) Reset button to initial state
        try:
            self.speech_log_button.clicked.disconnect()
        except TypeError:
            pass
        self.speech_log_button.setText("▶ Log Speech")
        self.speech_log_button.setEnabled(True)
        # Connect directly to start animation - no lambda needed
        self.speech_log_button.clicked.connect(self.start_speech_animation_for_pending)

        # 4) Ensure cancel is hidden until after slide
        self.speech_cancel_button.setVisible(False)
        
        # 5) Connect text box changes to update pending competitor
        try:
            self.speech_name_input.currentTextChanged.disconnect()
        except TypeError:
            pass
        self.speech_name_input.currentTextChanged.connect(self.update_pending_speech_competitor)

    def update_pending_speech_competitor(self, text):
        """Update pending speech competitor when text box changes"""
        if not text.strip():
            self.pending_speech_competitor = None
            return
        
        competitor = self.find_competitor(text.strip())
        if competitor:
            self.pending_speech_competitor = competitor
        else:
            self.pending_speech_competitor = None

    def update_pending_question_competitor(self, text):
        """Update pending question competitor when text box changes"""
        if not text.strip():
            self.pending_question_competitor = None
            return
        
        competitor = self.find_competitor(text.strip())
        if competitor:
            self.pending_question_competitor = competitor
        else:
            self.pending_question_competitor = None
    def start_speech_animation_for_pending(self):
        """Start speech animation using the pending competitor"""
        if not self.pending_speech_competitor:
            QMessageBox.information(self, "Select Competitor",
                "Please choose a valid competitor from the drop-down to log a speech.")
            return
        
        # FIX #1: Update button text BEFORE starting animation
        competitor_name = self.pending_speech_competitor.name
        self.speech_log_button.setText(f"✔ Log Speech for {competitor_name}")
        
        # Force UI update to make text change visible immediately
        self.speech_log_button.repaint()
        
        # Slide‐away the combo, leaving side/time intact
        anim = QParallelAnimationGroup(self)
        combo_anim = QPropertyAnimation(self.speech_name_input, b"maximumWidth")
        combo_anim.setDuration(250)
        combo_anim.setStartValue(self.speech_name_input.width())
        combo_anim.setEndValue(0)
        anim.addAnimation(combo_anim)

        # Slide the same button in
        btn = self.speech_log_button
        geom = btn.geometry()
        btn.move(self.speech_input_container.width() + 10, geom.y())
        btn_anim = QPropertyAnimation(btn, b"pos")
        btn_anim.setDuration(250)
        end = geom.topLeft()
        btn_anim.setStartValue(end + QPoint(80, 0))
        btn_anim.setEndValue(end)
        anim.addAnimation(btn_anim)

        # When done, just connect to confirm (text already updated above)
        def on_done():
            try: 
                btn.clicked.disconnect()
            except TypeError:
                pass
            btn.clicked.connect(self.confirm_log_speech)
            self.speech_cancel_button.setVisible(True)
        
        anim.finished.connect(on_done)
        anim.finished.connect(anim.deleteLater)
        anim.start()



    def on_question_list_double_clicked(self, item):
        # 1) Get competitor
        name = item.data(Qt.ItemDataRole.UserRole) or item.text()
        if not name:
            return
        comp = next((c for c in self.competitors if c.name == name), None)
        if not comp:
            return
        self.pending_question_competitor = comp

        # 2) Show input row & populate combo
        self.question_input_container.setVisible(True)
        self.question_name_input.clear()
        self.question_name_input.addItems(self.entered_names)
        self.question_name_input.setCurrentText(name)
        self.question_name_input.setFocus()

        # 3) Reset button to initial state
        try:
            self.question_log_button.clicked.disconnect()
        except TypeError:
            pass
        self.question_log_button.setText("▶ Log Question")
        self.question_log_button.setEnabled(True)
        self.question_log_button.clicked.connect(self.start_question_animation_for_pending)

        # 4) Hide cancel until after the slide
        self.question_cancel_button.setVisible(False)
        
        # 5) Connect text box changes to update pending competitor
        try:
            self.question_name_input.currentTextChanged.disconnect()
        except TypeError:
            pass
        self.question_name_input.currentTextChanged.connect(self.update_pending_question_competitor)

    def start_question_animation_for_pending(self):
        """Start question animation using the pending competitor"""
        if not self.pending_question_competitor:
            QMessageBox.information(self, "Select Competitor",
                "Please choose a valid competitor from the drop-down to log a question.")
            return
        
        # FIX #1: Update button text BEFORE starting animation
        competitor_name = self.pending_question_competitor.name
        self.question_log_button.setText(f"✔ Log Question for {competitor_name}")
        
        # Force UI update to make text change visible immediately
        self.question_log_button.repaint()
        
        # Show the full question row
        self.question_input_container.setVisible(True)

        # Hide cancel button during animation
        self.question_cancel_button.setVisible(False)

        anim = QParallelAnimationGroup(self)
        combo_anim = QPropertyAnimation(self.question_name_input, b"maximumWidth")
        combo_anim.setDuration(250)
        combo_anim.setStartValue(self.question_name_input.width())
        combo_anim.setEndValue(0)
        anim.addAnimation(combo_anim)

        btn = self.question_log_button
        geom = btn.geometry()
        btn.move(self.question_input_container.width() + 10, geom.y())
        btn_anim = QPropertyAnimation(btn, b"pos")
        btn_anim.setDuration(250)
        end = geom.topLeft()
        btn_anim.setStartValue(end + QPoint(80, 0))
        btn_anim.setEndValue(end)
        anim.addAnimation(btn_anim)

        def on_done():
            try: 
                btn.clicked.disconnect()
            except TypeError:
                pass
            btn.clicked.connect(self.confirm_log_question)
            self.question_cancel_button.setVisible(True)
        
        anim.finished.connect(on_done)
        anim.finished.connect(anim.deleteLater)
        anim.start()

    def setup_fonts(self):
        # Use a monospace font that's available cross-platform
        self.mono_font = QFont()
        self.mono_font.setFamily("Courier New")
        self.mono_font.setStyleHint(QFont.StyleHint.TypeWriter)
        self.mono_font.setFixedPitch(True)
        self.mono_font.setPointSize(10)
    def on_question_log_button_clicked(self):
        # This ensures the input row is visible on the first click before proceeding.
        self.question_input_container.setVisible(True)

        name = self.question_name_input.currentText().strip()
        if not name:
            QMessageBox.information(self, "Select Competitor",
                "Please choose a competitor from the drop-down to log a question.")
            return

        competitor = self.find_competitor(name)
        if not competitor:
            QMessageBox.warning(self, "Error", f"No competitor named '{name}' found.")
            return

        self.pending_question_competitor = competitor
        
        # Connect text box changes to update pending competitor
        try:
            self.question_name_input.currentTextChanged.disconnect()
        except TypeError:
            pass
        self.question_name_input.currentTextChanged.connect(self.update_pending_question_competitor)
        
        self.start_question_animation_for_pending()



    def toggle_current_side(self):
        self.current_side = "Negative" if self.current_side == "Affirmative" else "Affirmative"
        self.side_indicator.setText("Neg" if self.current_side == "Negative" else "Aff")

    def update_button_sizes(self):
        """Ensure buttons don't exceed 60% of available width"""
        # For speech tab
        if self.speech_input_container.isVisible():
            max_width = int(self.speech_input_container.width() * 0.6)
            self.speech_log_button.setMaximumWidth(max_width)
        
        # For question tab
        if self.question_log_button.isVisible():
            max_width = int(self.question_log_button.parent().width() * 0.6)
            self.question_log_button.setMaximumWidth(max_width)

    def add_resolution(self):
        text = self.resolution_input.text().strip()
        if text:
            if text not in self.resolution_list:
                self.resolution_list.append(text)
                self.resolution_list_widget.addItem(text)
                
                # If no current resolution, set this as current
                if not self.current_resolution:
                    self.set_current_resolution(text)
                    
                self.resolution_input.clear()
                self.save_to_csv()
                self.update_resolution_combos()
            else:
                QMessageBox.warning(self, "Duplicate", "This resolution already exists.")
    def load_resolution_state_on_startup(self):
        """Load resolution state at startup and determine next speaker from history"""
        if not self.resolution_list:
            self.set_current_resolution("")
            return
            
        # If we have a current resolution, use it; otherwise use the first one
        if not self.current_resolution and self.resolution_list:
            self.current_resolution = self.resolution_list[0]
            self.current_side = "Affirmative"
        
        # FIX: Determine the next speaker based on speech history for this resolution
        if self.current_resolution:
            # Get all speeches for this resolution, sorted by timestamp
            all_resolution_speeches = []
            for c in self.competitors:
                if hasattr(c, 'notes') and 'speeches' in c.notes:
                    for speech in c.notes['speeches']:
                        if isinstance(speech, dict) and speech.get('resolution') == self.current_resolution:
                            speech_with_name = speech.copy()
                            speech_with_name['competitor_name'] = c.name
                            all_resolution_speeches.append(speech_with_name)
            
            # Sort by timestamp to find the most recent speech
            all_resolution_speeches.sort(key=lambda x: x.get('timestamp', ''))
            
            if all_resolution_speeches:
                # Get the side of the most recent speech
                last_speech_side = all_resolution_speeches[-1].get('side', 'Aff')
                # Next speaker should be the opposite side
                if last_speech_side == 'Aff':
                    self.current_side = "Negative"
                else:
                    self.current_side = "Affirmative"
            else:
                # No speeches yet, start with Affirmative
                self.current_side = "Affirmative"
        
        # Load competitor sides for this resolution
        for c in self.competitors:
            if self.current_resolution in c.resolution_sides:
                c.current_side = c.resolution_sides[self.current_resolution]
            elif hasattr(c, 'notes') and 'speeches' in c.notes:
                # Determine side from speech history
                resolution_speeches = [s for s in c.notes['speeches'] 
                                    if isinstance(s, dict) and s.get('resolution') == self.current_resolution]
                if resolution_speeches:
                    c.current_side = resolution_speeches[-1].get('side', '')
                    c.resolution_sides[self.current_resolution] = c.current_side
                else:
                    c.current_side = ""
            else:
                c.current_side = ""
        
        self.set_current_resolution(self.current_resolution)
    
    def load_resolution_state(self):
        """Load resolution state at startup"""
        if self.resolution_list:
            self.set_current_resolution(self.resolution_list[0])
        else:
            self.set_current_resolution("")

    def move_competitor(self, name, direction, list_type):
        """Move competitor up (-1) or down (+1) in the given recency list, and update rank in model."""
        order = self.speech_recency_order if list_type == 'speech' else self.question_recency_order

        try:
            idx = order.index(name)
            new_idx = idx + direction
            if 0 <= new_idx < len(order):
                order[idx], order[new_idx] = order[new_idx], order[idx]

                # Update rank in each Competitor
                for i, n in enumerate(order):
                    comp = next((c for c in self.competitors if c.name == n), None)
                    if comp:
                        if list_type == 'speech':
                            comp.speech_rank = i + 1
                        else:
                            comp.question_rank = i + 1

                self.update_lists()
                self.save_to_csv()  # This will now save the recency orders too!
        except ValueError:
            print(f"Competitor {name} not found in {list_type} list.")
    def next_resolution(self):
        if not self.resolution_list:
            return
            
        current_idx = self.resolution_list.index(self.current_resolution) if self.current_resolution in self.resolution_list else -1
        next_idx = (current_idx + 1) % len(self.resolution_list)
        self.current_resolution = self.resolution_list[next_idx]
        
        # FIXED: Always reset to Affirmative (not based on current side)
        self.current_side = "Affirmative"
        
        # Load saved sides for this resolution or clear if new resolution
        for c in self.competitors:
            if self.current_resolution in c.resolution_sides:
                # Restore the saved side for this resolution
                c.current_side = c.resolution_sides[self.current_resolution]
            else:
                # Clear side for new resolution
                c.current_side = ""
        
        # Update UI
        self.set_current_resolution(self.current_resolution)
        self.update_resolution_display()
        self.update_lists()
        self.save_to_csv()


    def remove_resolution(self):
        selected = self.resolution_list_widget.currentItem()
        if selected:
            text = selected.text()
            reply = QMessageBox.question(
                self,
                "Confirm Removal",
                f"Remove resolution '{text}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.resolution_list.remove(text)
                self.resolution_list_widget.takeItem(self.resolution_list_widget.row(selected))
                if self.current_resolution == text:
                    self.current_resolution = self.resolution_list[0] if self.resolution_list else ""
                    self.current_side = "Affirmative"
                self.update_resolution_display()
                self.save_to_csv()
                self.update_resolution_combos()

    def update_resolution_display(self):
        """Update all resolution-related UI elements safely."""
        # 1) Resolution label (Speech tab)
        if hasattr(self, 'current_resolution_label') and self.current_resolution_label:
            res_text = f"Resolution: {self.current_resolution}" if self.current_resolution else "Resolution: None"
            self.current_resolution_label.setText(res_text)

        # 2) Next speaker label (Speech tab)
        if hasattr(self, 'next_speaker_label') and self.next_speaker_label:
            side_abbrev = "Aff" if self.current_side == "Affirmative" else "Neg"
            self.next_speaker_label.setText(f"Next Speaker: {side_abbrev}")

        # 3) Side indicator (in the input container)
        if hasattr(self, 'side_indicator') and self.side_indicator:
            self.side_indicator.setText("Aff" if self.current_side == "Affirmative" else "Neg")

        # 4) Question tab resolution label - FIX: Update question tab labels too
        if hasattr(self, 'q_current_resolution_label') and self.q_current_resolution_label:
            res_text = f"Resolution: {self.current_resolution}" if self.current_resolution else "Resolution: None"
            self.q_current_resolution_label.setText(res_text)
            
        # 5) Question tab next speaker label - FIX: Update question tab next speaker
        if hasattr(self, 'q_next_speaker_label') and self.q_next_speaker_label:
            side_abbrev = "Aff" if self.current_side == "Affirmative" else "Neg"
            self.q_next_speaker_label.setText(f"Next Speaker: {side_abbrev}")

    def get_speech_duration(self):
        """Calculate speech duration from input fields"""
        try:
            mins = int(self.minutes_input.text()) if self.minutes_input.text() else 0
            secs = int(self.seconds_input.text()) if self.seconds_input.text() else 0
            return mins * 60 + secs
        except ValueError:
            return 0

    def log_history(self, action_type, competitor_name, count_type, old_value, new_value):
        """Log an action to history"""
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.history.append(HistoryItem(
            action_type=action_type,
            competitor_name=competitor_name,
            count_type=count_type,
            old_value=old_value,
            new_value=new_value,
            timestamp=timestamp
        ))
        # Keep only last 15 items (5 speeches + 10 questions)
        self.history = self.history[-15:]
        self.update_history_tab()

    def update_history_tab(self):
        self.history_list.clear()
        show_speeches = self.history_toggle.currentText() == "Show Speeches History"
        
        filtered_history = [h for h in self.history if 
                        (show_speeches and h.action_type == 'speech') or
                        (not show_speeches and h.action_type == 'question')]
            
        # Show last 5 speeches or last 10 questions
        max_items = 5 if show_speeches else 10
        for item in filtered_history[-max_items:]:
            self.history_list.addItem(item.display_text())

    def restore_history_item(self, item):
        try:
            text = item.text()
            # Extract the competitor name from the history text
            parts = text.split(": ")
            if len(parts) < 2:
                raise ValueError("Invalid history item format")
            
            timestamp = parts[0]
            rest = parts[1]
            
            # Determine if this is a speech or question history item
            if "gave speech" in rest:
                action_type = 'speech'
                name_part = rest.split(" gave speech")[0]
            elif "asked question" in rest:
                action_type = 'question'
                name_part = rest.split(" asked question")[0]
            else:
                raise ValueError("Unknown action type in history")
            
            # Find the values to restore
            values_part = rest.split("(was ")[1].split(")")[0]
            old_value = int(values_part.split(", now ")[0])
            
            # Find the matching competitor
            competitor = next((c for c in self.competitors if c.name == name_part), None)
            if not competitor:
                raise ValueError("Competitor not found")
            
            # Restore the values
            if action_type == 'speech':
                competitor.speeches = old_value
                # Find the most recent speech round for this competitor
                if old_value == 0:
                    competitor.last_speech_round = 0
                else:
                    # This is a simplified approach - you might need more sophisticated logic
                    # to properly restore the last_speech_round
                    competitor.last_speech_round = self.current_round - 1
            else:
                competitor.questions = old_value
                if old_value == 0:
                    competitor.last_question_round = 0
                else:
                    competitor.last_question_round = self.current_round - 1
            
            # Update the UI and save
            self.update_lists()
            self.save_to_csv()
            QMessageBox.information(self, "Restored", 
                                f"Successfully restored {name_part}'s {action_type} count to {old_value}")
            
        except Exception as e:
            print(f"Error restoring history item: {str(e)}")
            QMessageBox.warning(self, "Error", 
                            f"Could not restore this version. Error: {str(e)}")

    def get_unique_file_path(self):
        base_dir = os.path.expanduser("~/Documents/CongressTracker")
        if not os.path.exists(base_dir):
            os.makedirs(base_dir)
        
        base_name = "congress_tracker_data"
        extension = ".csv"
        counter = 0
        file_path = os.path.join(base_dir, f"{base_name}{extension}")
        
        while os.path.exists(file_path):
            counter += 1
            file_path = os.path.join(base_dir, f"{base_name}{counter}{extension}")
        
        return file_path




    def setup_timer(self):
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_timer)
        self.start_time = None
        self.elapsed_seconds = 0
        self.is_paused = False
        self.pause_start_time = None

        # Timer container exposed for resize detection
        self.timer_container = QWidget()
        timer_layout = QHBoxLayout(self.timer_container)
        timer_layout.setContentsMargins(0, 0, 0, 0)
        timer_layout.setSpacing(8)

        # Timer display
        self.timer_label = QLabel("03:00")
        self.timer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timer_label.setStyleSheet("""
            font-size: 24px;
            font-weight: bold;
            background: #2a2a2a;
            padding: 4px 10px;
            border-radius: 4px;
            min-width: 80px;
        """)
        timer_layout.addWidget(self.timer_label)

        # Button styling helper
        def style_btn(btn, base, hover, press):
            btn.setFixedHeight(32)
            btn.setMinimumWidth(48)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {base};
                    color: white;
                    border: none;
                    padding: 0 12px;
                    font-size: 16px;
                    border-radius: 4px;
                    max-width: 120px;
                }}
                QPushButton:hover {{ background: {hover}; }}
                QPushButton:pressed {{ background: {press}; }}
            """)

        # Group buttons in a container to better control layout width
        button_container = QWidget()
        button_layout = QHBoxLayout(button_container)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(8)

        # Start/Pause button (changes between play and pause)
        self.start_pause_button = QPushButton("▶")
        style_btn(self.start_pause_button, "#2e7d32", "#66bb6a", "#1b5e20")
        button_layout.addWidget(self.start_pause_button)

        # Reset button
        self.reset_timer_button = QPushButton("↺")
        style_btn(self.reset_timer_button, "#1565c0", "#5e92f3", "#0d47a1")
        button_layout.addWidget(self.reset_timer_button)

        button_container.setMaximumWidth(int(self.width() * 0.4))
        timer_layout.addWidget(button_container)

        self.layout.addWidget(self.timer_container)

        # Connect buttons
        self.start_pause_button.clicked.connect(self.toggle_timer_state)
        self.reset_timer_button.clicked.connect(self.reset_timer)

        # Timer flashing setup
        self.flash_timer = QTimer(self)
        self.flash_timer.timeout.connect(self.toggle_flash)
        self.flash_state = False

        # Initial visibility setup
        self.update_timer_visibility()


    def toggle_timer_state(self):
        """Toggle between start, pause, and resume states"""
        if not self.timer.isActive() and not self.is_paused:
            # Start the timer
            self.start_timer()
        elif self.timer.isActive() and not self.is_paused:
            # Pause the timer
            self.pause_timer()
        elif self.is_paused:
            # Resume the timer
            self.resume_timer()

    def toggle_flash(self):
        """Toggle between red and normal background for 0-second flashing"""
        self.flash_state = not self.flash_state
        if self.flash_state:
            self.timer_label.setStyleSheet("""
                QLabel {
                    font-size: 24px;
                    font-weight: bold;
                    qproperty-alignment: AlignCenter;
                    padding: 2px 5px;
                    background-color: #ff0000;
                    border-radius: 3px;
                    color: black;
                }
            """)
        else:
            self.timer_label.setStyleSheet("""
                QLabel {
                    font-size: 24px;
                    font-weight: bold;
                    qproperty-alignment: AlignCenter;
                    padding: 2px 5px;
                    background-color: #2a2a2a;
                    border-radius: 3px;
                    color: white;
                }
            """)

    def update_timer_visibility(self):
        """Update visibility based on current config"""
        visible = self.config.get('enable_timer', True)
        self.timer_label.setVisible(visible)
        self.start_pause_button.setVisible(visible)
        self.reset_timer_button.setVisible(visible)
        # Update checkbox to match
        self.timer_checkbox.setChecked(visible)
    def start_timer(self):
        """Start the timer from the beginning"""
        self.start_time = datetime.datetime.now()
        self.elapsed_seconds = 0
        self.is_paused = False
        self.pause_start_time = None
        self.timer.start(1000)
        self.start_pause_button.setText("⏸")  # Pause symbol
        self.start_pause_button.setStyleSheet("""
            QPushButton {
                background: #f57c00;
                color: white;
                border: none;
                padding: 0 12px;
                font-size: 16px;
                border-radius: 4px;
                max-width: 120px;
            }
            QPushButton:hover { background: #ff9800; }
            QPushButton:pressed { background: #e65100; }
        """)
    def pause_timer(self):
        """Pause the timer"""
        if self.timer.isActive():
            self.timer.stop()
            self.pause_start_time = datetime.datetime.now()
            self.is_paused = True
            self.flash_timer.stop()  # Stop flashing when paused
            self.start_pause_button.setText("▶")  # Play symbol
            self.start_pause_button.setStyleSheet("""
                QPushButton {
                    background: #2e7d32;
                    color: white;
                    border: none;
                    padding: 0 12px;
                    font-size: 16px;
                    border-radius: 4px;
                    max-width: 120px;
                }
                QPushButton:hover { background: #66bb6a; }
                QPushButton:pressed { background: #1b5e20; }
            """)
    def resume_timer(self):
        """Resume the timer from where it was paused"""
        if self.is_paused and self.pause_start_time:
            # Calculate how long we were paused and adjust start time
            pause_duration = datetime.datetime.now() - self.pause_start_time
            self.start_time += pause_duration
            
            self.is_paused = False
            self.pause_start_time = None
            self.timer.start(1000)
            self.start_pause_button.setText("⏸")  # Pause symbol
            self.start_pause_button.setStyleSheet("""
                QPushButton {
                    background: #f57c00;
                    color: white;
                    border: none;
                    padding: 0 12px;
                    font-size: 16px;
                    border-radius: 4px;
                    max-width: 120px;
                }
                QPushButton:hover { background: #ff9800; }
                QPushButton:pressed { background: #e65100; }
            """)
    def stop_timer(self):
        self.timer.stop()
        self.flash_timer.stop()  # Stop flashing when timer is stopped

    def reset_timer(self):
        """Reset the timer to initial state"""
        self.timer.stop()
        self.flash_timer.stop()  # Stop flashing when timer is reset
        self.start_time = None
        self.elapsed_seconds = 0
        self.is_paused = False
        self.pause_start_time = None
        
        # Reset display
        if self.config['timer_mode'] == 'countdown':
            mins = self.config['speech_time_limit'] // 60
            secs = self.config['speech_time_limit'] % 60
            self.timer_label.setText(f"{mins:02}:{secs:02}")
        else:
            self.timer_label.setText("00:00")
        
        # Reset button to start state
        self.start_pause_button.setText("▶")
        self.start_pause_button.setStyleSheet("""
            QPushButton {
                background: #2e7d32;
                color: white;
                border: none;
                padding: 0 12px;
                font-size: 16px;
                border-radius: 4px;
                max-width: 120px;
            }
            QPushButton:hover { background: #66bb6a; }
            QPushButton:pressed { background: #1b5e20; }
        """)
        
        # Reset to normal style
        self.timer_label.setStyleSheet("""
            QLabel {
                font-size: 24px;
                font-weight: bold;
                qproperty-alignment: AlignCenter;
                padding: 2px 5px;
                background-color: #2a2a2a;
                border-radius: 3px;
                color: white;
            }
        """)

    def update_timer(self):
        if self.start_time:
            now = datetime.datetime.now()
            elapsed = int((now - self.start_time).total_seconds())
            
            if self.config['timer_mode'] == 'countdown':
                remaining = max(0, self.config['speech_time_limit'] - elapsed)
                mins = remaining // 60
                secs = remaining % 60
                self.timer_label.setText(f"{mins:02}:{secs:02}")
                
                # Check for signals
                if remaining in self.config['time_signals']:
                    self.show_time_signal(remaining)
                
                # Handle 0 seconds separately - start flashing
                if remaining == 0 and not self.flash_timer.isActive():
                    self.flash_timer.start(500)  # Flash every 500ms
            else:  # stopwatch mode
                mins = elapsed // 60
                secs = elapsed % 60
                self.timer_label.setText(f"{mins:02}:{secs:02}")

    def show_time_signal(self, seconds_remaining):
        # Visual flash effect - keep same font size and padding as normal state
        self.timer_label.setStyleSheet("""
            QLabel {
                font-size: 24px;
                font-weight: bold;
                qproperty-alignment: AlignCenter;
                padding: 2px 5px;
                background-color: #ff9800;
                border-radius: 3px;
                color: black;
            }
        """)
        QTimer.singleShot(500, lambda: self.timer_label.setStyleSheet("""
            QLabel {
                font-size: 24px;
                font-weight: bold;
                qproperty-alignment: AlignCenter;
                padding: 2px 5px;
                background-color: #2a2a2a;
                border-radius: 3px;
                color: white;
            }
        """))

    def save_to_csv(self):
        # Only save if we have competitors and a valid file path
        if not self.competitors or not self.csv_file_path:
            return
            
        try:
            persistence.save_to_csv(
                self.csv_file_path, 
                self.competitors, 
                self.history,
                self.speech_recency_order,
                self.question_recency_order,
                self.resolution_list,  # Add resolutions
                self.current_resolution,  # Add current resolution
                self.current_side  # Add current side
            )
        except Exception as e:
            print(f"Error saving CSV: {e}")

    def clear_csv_data(self):
        reply = QMessageBox.question(
            self,
            "Clear All Data",
            "Are you sure you want to clear all competitor data? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.competitors = []
            self.entered_names = []
            self.history = []  # Clear history as well
            if self.csv_file_path and os.path.exists(self.csv_file_path):
                persistence.clear_csv_data(self.csv_file_path)
                # Also remove history file
                history_filepath = self.csv_file_path.replace('.csv', '_history.json')
                if os.path.exists(history_filepath):
                    os.remove(history_filepath)
            self.reset_ui_to_initial_state()
            self.update_lists()
            self.update_history_tab()  # Update history display
            self.update_status(loaded=False)

    def refresh_status(self):
        """Refresh the status tab information"""
        if self.csv_file_path and os.path.exists(self.csv_file_path):
            self.update_status(loaded=True, filepath=self.csv_file_path)
        else:
            self.update_status(loaded=False)

    def edit_file_path(self):
        if not self.csv_file_path:
            return
        
        new_path, ok = QInputDialog.getText(
            self,
            "Edit File Path",
            "Enter new file path:",
            QLineEdit.EchoMode.Normal,
            self.csv_file_path
        )
        
        if ok and new_path.strip() and new_path != self.csv_file_path:
            try:
                # Check if the directory exists
                dir_path = os.path.dirname(new_path)
                if not os.path.exists(dir_path):
                    os.makedirs(dir_path)
                
                # Rename the file
                os.rename(self.csv_file_path, new_path)
                self.csv_file_path = new_path
                self.update_status(loaded=True, filepath=new_path)
                QMessageBox.information(self, "Success", "File path updated successfully.")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not update file path: {str(e)}")

    def update_status(self, loaded=False, filepath=None):
        try:
            if loaded and filepath:
                # Only try to get file stats if we have a valid path
                try:
                    size = os.path.getsize(filepath)
                    mtime = os.path.getmtime(filepath)
                    last_modified = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
                    self.file_path_label.setText(f"<b>File Path:</b> {filepath}")
                    # Show edit button
                    self.rename_file_button.setVisible(True)
                except (TypeError, OSError) as e:
                    size = 0
                    last_modified = "N/A"
                    
                num_competitors = len(self.competitors)
                
                self.file_path_label.setText(f"<b>File Path:</b> {filepath}")
                self.file_size_label.setText(f"<b>File Size:</b> {self.format_size(size)}")
                self.last_modified_label.setText(f"<b>Last Modified:</b> {last_modified}")
                self.num_competitors_label.setText(f"<b>Competitors:</b> {num_competitors}")
                
                # Update status indicator
                self.status_indicator.setText("●")
                self.status_indicator.setStyleSheet("color: #55FF55;")
                
                total_speeches = sum(c.speeches for c in self.competitors)
                total_questions = sum(c.questions for c in self.competitors)
                self.stats_label.setText(
                    f"<b>Statistics:</b>\n"
                    f"  • Total Speeches: {total_speeches}\n"
                    f"  • Total Questions: {total_questions}"
                )
            else:
                # Handle not-loaded case
                self.rename_file_button.setVisible(False)
                self.status_indicator.setText("●")
                self.status_indicator.setStyleSheet("color: #FF5555;")
                self.file_path_label.setText("<b>File Path:</b> No file loaded")
                self.file_size_label.setText("<b>File Size:</b> N/A")
                self.last_modified_label.setText("<b>Last Modified:</b> N/A")
                self.num_competitors_label.setText("<b>Competitors:</b> 0")
                self.stats_label.setText("<b>Statistics:</b> No data available")
                self.update_tab_indicators()
                
        except Exception as e:
            print(f"Error updating status: {e}")

    def format_size(self, size):
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} GB"

    def reset_ui_to_initial_state(self):
        self.name_input.show()
        self.instructions.show()
        self.start_button.show()
        self.speech_log_button.setEnabled(False)
        self.speech_name_input.setEnabled(False)
        self.question_log_button.setEnabled(False)
        self.question_name_input.setEnabled(False)
        self.add_competitor_button.setEnabled(False)
        self.clear_log_inputs()

    def set_current_resolution(self, resolution):
        """Set and display the current resolution"""
        self.current_resolution = resolution
        
        # Load saved sides for this resolution
        for c in self.competitors:
            if resolution in c.resolution_sides:
                c.current_side = c.resolution_sides[resolution]
            else:
                c.current_side = ""
        
        if resolution:
            # Update settings panel label
            if hasattr(self, 'resolution_settings_label'):
                self.resolution_settings_label.setText(f"Current: {resolution}")
        else:
            if hasattr(self, 'resolution_settings_label'):
                self.resolution_settings_label.setText("Current: None")
        
        # FIX: Make sure to update all resolution displays
        self.update_resolution_display()
        self.save_to_csv()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Resize and hasattr(self, 'timer_container'):
            max_w = int(self.timer_container.width() * 0.4)
            for btn in (self.start_timer_button, self.stop_timer_button, self.reset_timer_button):
                btn.setMaximumWidth(max_w)
        return super().eventFilter(obj, event)

    def init_ui(self):
        self.layout = QVBoxLayout()

        # Initial input section
        self.instructions = QLabel("Enter competitor names one by one, press Enter to add, then click Start")
        self.layout.addWidget(self.instructions)

        self.name_input = QLineEdit()
        self.name_input.returnPressed.connect(self.add_name)
        self.layout.addWidget(self.name_input)

        self.start_button = QPushButton("Start Tracking")
        self.start_button.clicked.connect(self.start_tracking)
        self.layout.addWidget(self.start_button)

        # Initialize tabs with the custom expanding tab bar
        self.tabs = QTabWidget()
        self.tabs.setTabBar(ExpandingTabBar(self.tabs))
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.layout.addWidget(self.tabs)

    # ---- SPEECH TAB ----
        # Helper to build the header widget
        def make_header(title_text, resolution_label, speaker_label, button):
            header = QWidget()
            header.setStyleSheet("background: transparent;")
            header.setFixedHeight(32)
            hl = QHBoxLayout(header)
            hl.setContentsMargins(0, 4, 0, 4)
            hl.setSpacing(16)

            title = QLabel(title_text)
            title.setStyleSheet("font-weight: bold; font-size: 14px;")
            hl.addWidget(title)

            resolution_label.setStyleSheet(
                "font-size: 12px; color: #FFFFFF; font-weight: bold;"
            )
            hl.addWidget(resolution_label)

            speaker_label.setStyleSheet(
                "font-size: 12px; color: #FFFFFF; font-weight: bold;"
            )
            hl.addWidget(speaker_label)

            hl.addStretch()
            hl.addWidget(button)
            return header

        # Create the speech tab and its layouts
        self.speech_tab = QWidget()
        speech_main_layout = QHBoxLayout(self.speech_tab)

        # Right‐side panel inside the speech tab
        speech_right_panel = QWidget()
        speech_right_layout = QVBoxLayout(speech_right_panel)
        speech_right_layout.setContentsMargins(0, 0, 0, 0)

        # Resolution & Next Speaker controls
        self.current_resolution_label = QLabel("Resolution: None")
        self.next_speaker_label     = QLabel("Next Speaker: Aff")
        self.next_resolution_btn    = QPushButton("Next Resolution")
        self.next_resolution_btn.setStyleSheet("""
            QPushButton {
                padding: 4px 10px;
                font-size: 12px;
                color: #FFFFFF;
                background: #505050;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover { background: #606060; }
            QPushButton:pressed { background: #404040; }
        """)
        self.next_resolution_btn.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed
        )
        self.next_resolution_btn.setFixedHeight(28)
        self.next_resolution_btn.clicked.connect(self.next_resolution)

        # Build and add the header
        speech_header = make_header(
            "Speeches",
            self.current_resolution_label,
            self.next_speaker_label,
            self.next_resolution_btn
        )
        speech_right_layout.addWidget(speech_header)

        # ---- Speech list ----
        self.speech_list = QListWidget()
        speech_right_layout.addWidget(self.speech_list)

        # ---- Speech input container (hidden by default) ----
        self.speech_input_container = QWidget()
        self.speech_input_container.setVisible(False)
        speech_right_layout.addWidget(self.speech_input_container)

        # Layout for all speech‐logging controls
        input_layout = QHBoxLayout(self.speech_input_container)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(8)

        # 1) Competitor picker combo (must be first for the slide‐away animation)
        self.speech_name_input = QComboBox()
        self.speech_name_input.setEditable(True)
        self.speech_name_input.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed
        )
        input_layout.addWidget(self.speech_name_input, 3)
        self.update_competitor_combos()  # fill with competitor names

        # 2) Side indicator + toggle
        self.side_indicator = QLabel("Aff")
        self.side_indicator.setFixedWidth(40)
        self.side_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        input_layout.addWidget(self.side_indicator)

        self.side_toggle_btn = QPushButton("↻")
        self.side_toggle_btn.setFixedSize(24, 24)
        self.side_toggle_btn.setToolTip("Toggle side")
        self.side_toggle_btn.clicked.connect(self.toggle_current_side)
        input_layout.addWidget(self.side_toggle_btn)

        # 3) Time inputs
        self.minutes_input = QLineEdit()
        self.minutes_input.setPlaceholderText("M")
        self.minutes_input.setFixedWidth(40)
        input_layout.addWidget(self.minutes_input)
        input_layout.addWidget(QLabel(":"))
        self.seconds_input = QLineEdit()
        self.seconds_input.setPlaceholderText("S")
        self.seconds_input.setFixedWidth(40)
        input_layout.addWidget(self.seconds_input)

        # 4) Log / Confirm / Cancel buttons
        self.speech_log_button = QPushButton("Log Speech")
        self.speech_log_button.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed
        )
        self.speech_log_button.clicked.connect(self.on_speech_log_button_clicked)
        input_layout.addWidget(self.speech_log_button, 1)

        self.speech_confirm_button = QPushButton("✔")
        self.speech_confirm_button.setVisible(False)
        self.speech_confirm_button.clicked.connect(self.confirm_log_speech)
        input_layout.addWidget(self.speech_confirm_button)

        self.speech_cancel_button = QPushButton("✘")
        self.speech_cancel_button.setVisible(False)
        self.speech_cancel_button.clicked.connect(self.cancel_log_speech)
        input_layout.addWidget(self.speech_cancel_button)

        # Add the right panel into the speech tab and register the tab
        speech_main_layout.addWidget(speech_right_panel, 3)
        self.tabs.addTab(self.speech_tab, "Speeches")

        # ===== QUESTION TAB =====
        self.question_tab = QWidget()
        question_main_layout = QHBoxLayout(self.question_tab)

        # Right: Question controls and list
        question_right_panel = QWidget()
        question_right_layout = QVBoxLayout(question_right_panel)
        question_right_layout.setContentsMargins(0, 0, 0, 0)

        # — QUESTIONS TAB HEADER (match speech) —
        question_header = QWidget()
        question_header.setStyleSheet("background: transparent;")
        question_header.setFixedHeight(32)
        qh_layout = QHBoxLayout(question_header)
        qh_layout.setContentsMargins(0, 4, 0, 4)
        qh_layout.setSpacing(16)

        # Title
        q_title = QLabel("Questions")
        q_title.setStyleSheet("font-weight: bold; font-size: 14px;")
        qh_layout.addWidget(q_title)

        # Resolution + Next Speaker
        self.q_current_resolution_label = QLabel("Resolution: None")
        self.q_current_resolution_label.setStyleSheet("font-size:12px; color:#FFFFFF; font-weight:bold;")
        qh_layout.addWidget(self.q_current_resolution_label)

        self.q_next_speaker_label = QLabel("Next Speaker: Aff")
        self.q_next_speaker_label.setStyleSheet("font-size:12px; color:#FFFFFF; font-weight:bold;")
        qh_layout.addWidget(self.q_next_speaker_label)

        qh_layout.addStretch()

        # Next Resolution button (reuse the dimmed style)
        self.q_next_resolution_btn = QPushButton("Next Resolution")
        self.q_next_resolution_btn.setStyleSheet(self.next_resolution_btn.styleSheet())
        self.q_next_resolution_btn.setFixedHeight(28)
        self.q_next_resolution_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.q_next_resolution_btn.clicked.connect(self.next_resolution)
        qh_layout.addWidget(self.q_next_resolution_btn)

        question_right_layout.addWidget(question_header)

        # Question list
        self.question_list = QListWidget()
        question_right_layout.addWidget(self.question_list)

        # Question input container
        self.question_input_container = QWidget()
        self.question_input_container.setVisible(False)
        question_right_layout.addWidget(self.question_input_container)

        question_input_layout = QHBoxLayout(self.question_input_container)
        question_input_layout.setContentsMargins(0, 0, 0, 0)
        question_input_layout.setSpacing(8)



        self.question_name_input = QComboBox()
        self.question_name_input.setEditable(True)
        self.question_name_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        question_input_layout.addWidget(self.question_name_input, 3)

        self.question_log_button = QPushButton("Log Question")
        self.question_log_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.question_log_button.clicked.connect(self.on_question_log_button_clicked)
        question_input_layout.addWidget(self.question_log_button, 1)

        self.question_confirm_button = QPushButton("✔")
        self.question_confirm_button.setVisible(False)
        self.question_confirm_button.clicked.connect(self.confirm_log_question)
        question_input_layout.addWidget(self.question_confirm_button)

        self.question_cancel_button = QPushButton("✘")
        self.question_cancel_button.setVisible(False)
        self.question_cancel_button.clicked.connect(self.cancel_log_question)
        question_input_layout.addWidget(self.question_cancel_button)


        # Add the right panel to the tab layout
        question_main_layout.addWidget(question_right_panel, 3)
        self.tabs.addTab(self.question_tab, "Questions")



        # ===== SETTINGS TAB =====
        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        
        settings_container = QWidget()
        self.manage_layout = QVBoxLayout(settings_container)
        self.manage_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Competitor management
        self.manage_list = QListWidget()
        self.manage_list.itemSelectionChanged.connect(self.update_manage_buttons)
        self.manage_layout.addWidget(self.manage_list)

        manage_buttons = QHBoxLayout()
        self.rename_button = QPushButton("Rename Selected")
        self.rename_button.clicked.connect(self.rename_competitor)
        self.rename_button.setEnabled(False)
        manage_buttons.addWidget(self.rename_button)

        self.delete_button = QPushButton("Delete Selected")
        self.delete_button.clicked.connect(self.delete_competitor)
        self.delete_button.setEnabled(False)
        manage_buttons.addWidget(self.delete_button)
        self.manage_layout.addLayout(manage_buttons)

        self.add_competitor_button = QPushButton("Add Competitor")
        self.add_competitor_button.clicked.connect(self.add_competitor)
        self.add_competitor_button.setEnabled(False)
        self.manage_layout.addWidget(self.add_competitor_button)

        # File operations
        file_buttons = QHBoxLayout()
        self.load_csv_button = QPushButton("📂 Load CSV File")
        self.load_csv_button.clicked.connect(self.prompt_load_csv)
        file_buttons.addWidget(self.load_csv_button)

        self.clear_data_button = QPushButton("🗑️ Clear All Data")
        self.clear_data_button.clicked.connect(self.clear_csv_data)
        self.clear_data_button.setStyleSheet("""
            QPushButton { 
                background-color: #8B0000; 
                color: white; 
                font-weight: bold; 
            }
            QPushButton:hover { background-color: #A52A2A; }
        """)
        file_buttons.addWidget(self.clear_data_button)
        self.manage_layout.addLayout(file_buttons)

        # Resolution settings toggle
        self.resolution_toggle = QPushButton("▼ Resolution Settings")
        self.resolution_toggle.setCheckable(True)
        self.resolution_toggle.setChecked(False)
        self.resolution_toggle.clicked.connect(self.toggle_resolution_settings)
        self.manage_layout.addWidget(self.resolution_toggle)
        
        # Resolution settings group (initially hidden)
        self.resolution_group = QGroupBox()
        resolution_layout = QVBoxLayout()

        # Current resolution display
        self.resolution_settings_label = QLabel("Current: None")
        resolution_layout.addWidget(self.resolution_settings_label)

        # Resolution list widget
        self.resolution_list_widget = QListWidget()
        resolution_layout.addWidget(self.resolution_list_widget)
        
        # Resolution input
        resolution_input_layout = QHBoxLayout()
        self.resolution_input = QLineEdit()
        self.resolution_input.setPlaceholderText("Enter resolution title")
        resolution_input_layout.addWidget(self.resolution_input)
        
        # Add resolution button
        add_res_btn = QPushButton("Add")
        add_res_btn.clicked.connect(self.add_resolution)
        resolution_input_layout.addWidget(add_res_btn)
        resolution_layout.addLayout(resolution_input_layout)
        
        # Resolution controls
        resolution_controls = QHBoxLayout()
        next_res_btn = QPushButton("Next Resolution")
        next_res_btn.clicked.connect(self.next_resolution)
        resolution_controls.addWidget(next_res_btn)
        
        remove_res_btn = QPushButton("Remove Selected")
        remove_res_btn.clicked.connect(self.remove_resolution)
        resolution_controls.addWidget(remove_res_btn)
        resolution_layout.addLayout(resolution_controls)
        
        # Side toggle button
        self.side_toggle_btn = QPushButton("Toggle Side")
        self.side_toggle_btn.clicked.connect(self.toggle_current_side)
        resolution_layout.addWidget(self.side_toggle_btn)
        
        self.resolution_group.setLayout(resolution_layout)
        self.resolution_group.setVisible(False)
        self.manage_layout.addWidget(self.resolution_group)

        # Timer settings toggle
        self.timer_toggle = QPushButton("▼ Timer Settings")
        self.timer_toggle.setCheckable(True)
        self.timer_toggle.setChecked(False)
        self.timer_toggle.clicked.connect(self.toggle_timer_settings)
        self.manage_layout.addWidget(self.timer_toggle)

        # Timer settings group (initially hidden)
        self.timer_group = QGroupBox()
        timer_layout = QVBoxLayout()

        # Timer enable checkbox
        self.timer_checkbox = QCheckBox("Enable Timer")
        self.timer_checkbox.setChecked(self.config.get('enable_timer', True))
        self.timer_checkbox.stateChanged.connect(self.on_timer_toggle)
        timer_layout.addWidget(self.timer_checkbox)

        # Timer mode
        self.timer_mode_combo = QComboBox()
        self.timer_mode_combo.addItems(["Countdown", "Stopwatch"])
        self.timer_mode_combo.setCurrentText(self.config['timer_mode'].capitalize())
        timer_layout.addWidget(QLabel("Timer Mode:"))
        timer_layout.addWidget(self.timer_mode_combo)

        # Time limit
        self.time_limit_spin = QSpinBox()
        self.time_limit_spin.setRange(30, 600)
        self.time_limit_spin.setValue(self.config['speech_time_limit'])
        timer_layout.addWidget(QLabel("Speech Time Limit (seconds):"))
        timer_layout.addWidget(self.time_limit_spin)

        # Time signals
        self.time_signals_edit = QLineEdit(",".join(map(str, self.config['time_signals'])))
        timer_layout.addWidget(QLabel("Signal Points (comma-separated):"))
        timer_layout.addWidget(self.time_signals_edit)

        # Save settings button
        save_btn = QPushButton("Save Timer Settings")
        save_btn.clicked.connect(self.save_timer_settings)
        timer_layout.addWidget(save_btn)

        self.timer_group.setLayout(timer_layout)
        self.timer_group.setVisible(False)
        self.manage_layout.addWidget(self.timer_group)

# Accessibility settings toggle
        self.accessibility_toggle = QPushButton("▼ Accessibility Settings")
        self.accessibility_toggle.setCheckable(True)
        self.accessibility_toggle.setChecked(False)
        self.accessibility_toggle.clicked.connect(self.toggle_accessibility_settings)
        self.manage_layout.addWidget(self.accessibility_toggle)

        # Accessibility settings group (initially hidden)
        self.accessibility_group = QGroupBox()
        accessibility_layout = QVBoxLayout()

        # Keyboard shortcuts checkbox
        self.shortcuts_checkbox = QCheckBox("Enable Keyboard Shortcuts")
        self.shortcuts_checkbox.setChecked(self.config.get('enable_shortcuts', True))
        accessibility_layout.addWidget(self.shortcuts_checkbox)
        
        # Add shortcut help text
        shortcuts_help = QLabel("""
Keyboard Shortcuts:
• Space: Start/Stop Timer
• Ctrl+S: Quick Log Speech (first person)
• Ctrl+Q: Quick Log Question (first person) 
• Ctrl+Tab: Next Tab
• Ctrl+Shift+Tab: Previous Tab
• R: Reset Timer
        """)
        shortcuts_help.setStyleSheet("font-size: 11px; color: #AAAAAA; margin-left: 20px;")
        shortcuts_help.setWordWrap(True)
        accessibility_layout.addWidget(shortcuts_help)

        # High contrast checkbox
        self.high_contrast_checkbox = QCheckBox("High Contrast Mode")
        self.high_contrast_checkbox.setChecked(self.config.get('high_contrast', False))
        accessibility_layout.addWidget(self.high_contrast_checkbox)

        # Large text checkbox
        self.large_text_checkbox = QCheckBox("Large Text Mode")
        self.large_text_checkbox.setChecked(self.config.get('large_text', False))
        accessibility_layout.addWidget(self.large_text_checkbox)

        # Save accessibility settings button
        save_accessibility_btn = QPushButton("Save Accessibility Settings")
        save_accessibility_btn.clicked.connect(self.save_accessibility_settings)
        accessibility_layout.addWidget(save_accessibility_btn)

        self.accessibility_group.setLayout(accessibility_layout)
        self.accessibility_group.setVisible(False)
        self.manage_layout.addWidget(self.accessibility_group)

        settings_scroll.setWidget(settings_container)
        self.tabs.addTab(settings_scroll, "Settings")

        # ===== HISTORY TAB =====
        self.history_tab = QWidget()
        history_layout = QVBoxLayout(self.history_tab)
        
        self.history_toggle = QComboBox()
        self.history_toggle.addItems(["Show Speeches History", "Show Questions History"])
        self.history_toggle.currentIndexChanged.connect(self.update_history_tab)
        history_layout.addWidget(self.history_toggle)
        
        self.history_list = QListWidget()
        self.history_list.itemDoubleClicked.connect(self.restore_history_item)
        history_layout.addWidget(self.history_list)
        
        self.tabs.addTab(self.history_tab, "History")

        # ===== STATUS TAB =====
        self.status_tab = QWidget()
        self.status_layout = QVBoxLayout(self.status_tab)
        self.status_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Header
        header_layout = QHBoxLayout()
        self.status_indicator = QLabel("●")
        self.status_indicator.setStyleSheet("color: red; font-size: 16px; font-weight: bold;")
        header_layout.addWidget(self.status_indicator)

        self.status_title = QLabel("Session Status")
        self.status_title.setStyleSheet("font-size: 16px; font-weight: bold;")
        header_layout.addWidget(self.status_title)
        header_layout.addStretch()
        self.status_layout.addLayout(header_layout)

        # Info Grid
        grid = QGridLayout()
        grid.setVerticalSpacing(10)

        # File path with edit button
        file_path_layout = QHBoxLayout()
        self.file_path_label = QLabel("<b>File Path:</b> No file loaded")
        self.file_path_label.setWordWrap(True)
        file_path_layout.addWidget(self.file_path_label, 1)  # Make it expandable

        # Add edit button
        self.rename_file_button = QPushButton("✏️")  # Pencil icon
        self.rename_file_button.setToolTip("Rename current file")
        self.rename_file_button.setFixedSize(25, 25)
        self.rename_file_button.setStyleSheet("""
            QPushButton {
                border: none; 
                padding: 0;
                font-size: 12px;
            }
            QPushButton:hover {
                color: #ffffff;
            }
        """)
        self.rename_file_button.clicked.connect(self.rename_current_file)
        self.rename_file_button.setVisible(False)
        file_path_layout.addWidget(self.rename_file_button)

        grid.addLayout(file_path_layout, 0, 0, 1, 2)

        self.file_size_label = QLabel("<b>File Size:</b> N/A")
        grid.addWidget(self.file_size_label, 1, 0)

        self.last_modified_label = QLabel("<b>Last Modified:</b> N/A")
        grid.addWidget(self.last_modified_label, 1, 1)

        self.num_competitors_label = QLabel("<b>Competitors:</b> 0")
        grid.addWidget(self.num_competitors_label, 2, 0)

        self.stats_label = QLabel("<b>Statistics:</b> No data available")
        self.stats_label.setWordWrap(True)
        grid.addWidget(self.stats_label, 3, 0, 1, 2)

        self.status_layout.addLayout(grid)

        # Buttons
        button_layout = QHBoxLayout()
        self.refresh_button = QPushButton("🔄 Refresh Status")
        self.refresh_button.clicked.connect(self.refresh_status)
        button_layout.addWidget(self.refresh_button)

        self.open_folder_button = QPushButton("📂 Open Folder")
        self.open_folder_button.clicked.connect(self.open_data_folder)
        button_layout.addWidget(self.open_folder_button)

        self.status_layout.addLayout(button_layout)
        self.tabs.addTab(self.status_tab, "● Status")

        # ===== STATISTICS TAB =====
        self.stats_tab = QWidget()
        stats_layout = QVBoxLayout(self.stats_tab)
        
        # Create resolution combo
        self.stats_resolution_combo = QComboBox()
        stats_layout.addWidget(QLabel("Select Resolution:"))
        stats_layout.addWidget(self.stats_resolution_combo)
        
        self.stats_table = QTableWidget()
        self.stats_table.setColumnCount(4)
        self.stats_table.setHorizontalHeaderLabels(["Name", "Side", "Speech Count", "Avg. Time"])
        self.stats_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        stats_layout.addWidget(self.stats_table)
        
        self.tabs.addTab(self.stats_tab, "Statistics")

        # ===== CREDITS TAB =====
        self.credits_tab = QWidget()
        credits_layout = QVBoxLayout(self.credits_tab)
        credits_label = QLabel("Credits:\n\nDeveloped by mrogenmoser\n\nCourtesy of PHS Debate")
        credits_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        credits_label.setStyleSheet("font-size: 16pt;")
        credits_layout.addWidget(credits_label)
        self.tabs.addTab(self.credits_tab, "Credits")

        # Set up context menus
        for list_widget in [self.speech_list, self.question_list, self.manage_list]:
            list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            list_widget.customContextMenuRequested.connect(self.show_context_menu)

        self.setLayout(self.layout)
        self.apply_dark_mode()
        self.update_status(loaded=False)
        self.update_resolution_display()
        self.load_resolution_state()
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.update_tab_indicators()


    def toggle_timer_settings(self):
        visible = not self.timer_group.isVisible()
        self.timer_group.setVisible(visible)
        self.timer_toggle.setText("▲ Timer Settings" if visible else "▼ Timer Settings")

    def update_stats_display(self):
        # Clear previous content
        self.stats_table.setRowCount(0)
        
        # Add "All" option to resolutions
        all_resolutions = ["All"] + self.resolution_list
        current_resolution = self.stats_resolution_combo.currentText()
        self.stats_resolution_combo.clear()
        self.stats_resolution_combo.addItems(all_resolutions)
        
        # Restore selection if possible
        if current_resolution in all_resolutions:
            self.stats_resolution_combo.setCurrentText(current_resolution)
        else:
            self.stats_resolution_combo.setCurrentText("All")
        
        resolution = self.stats_resolution_combo.currentText()
        
        # Check if we have any speech data
        has_data = False
        for competitor in self.competitors:
            res_speeches = self._get_speeches_for_resolution(competitor, resolution)
            if res_speeches:
                has_data = True
                break
        
        if not has_data:
            # Show "no data" message
            self.stats_table.setRowCount(1)
            self.stats_table.setColumnCount(1)
            self.stats_table.setItem(0, 0, QTableWidgetItem("No statistics available. Please log speeches to view statistics."))
            self.stats_table.setSpan(0, 0, 1, 4)  # Merge cells for the message
            return
        
        # Restore column count if it was changed
        self.stats_table.setColumnCount(4)
        self.stats_table.setHorizontalHeaderLabels(["Name", "Side", "Speech Count", "Avg. Time"])
        
        # Populate statistics
        for competitor in self.competitors:
            res_speeches = self._get_speeches_for_resolution(competitor, resolution)
            if res_speeches:
                row = self.stats_table.rowCount()
                self.stats_table.insertRow(row)
                
                timed_speeches = [s for s in res_speeches if s.get('duration', 0) > 0]

                total_time = sum(s['duration'] for s in timed_speeches)
                speech_count = len([s for s in res_speeches if s.get('duration', 0) >= 0])

                if speech_count > 0:
                    avg_seconds = total_time // speech_count
                    mins, secs = divmod(avg_seconds, 60)
                    time_str = f"{mins}:{secs:02d}"
                else:
                    time_str = "n/a"
                
                # Get side (use the most common side if multiple)
                sides = [s.get('side', '') for s in res_speeches]
                side = max(set(sides), key=sides.count) if sides else ""
                
                self.stats_table.setItem(row, 0, QTableWidgetItem(competitor.name))
                self.stats_table.setItem(row, 1, QTableWidgetItem(side))
                self.stats_table.setItem(row, 2, QTableWidgetItem(str(speech_count)))
                self.stats_table.setItem(row, 3, QTableWidgetItem(time_str))
    def reset_speech_inputs(self):
        
        self.speech_log_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.speech_log_button.setText("Log Speech")
        self.speech_confirm_button.setVisible(False)
        self.speech_cancel_button.setVisible(False)
        self.pending_speech_competitor = None
        self.minutes_input.clear()
        self.seconds_input.clear()
        self.side_indicator.setText("Aff")

    def _get_speeches_for_resolution(self, competitor, resolution):
        """Get speeches for a competitor filtered by resolution"""
        # Make sure we have the speeches list
        if not hasattr(competitor, 'notes') or 'speeches' not in competitor.notes:
            return []
        
        speeches = competitor.notes['speeches']
        
        # Filter for specific resolution if not "All"
        if resolution != "All":
            return [s for s in speeches if isinstance(s, dict) and s.get('resolution') == resolution]
        return speeches

    def show_context_menu(self, position):
        sender = self.sender()
        item = sender.itemAt(position)
        if not item:
            return

        # Skip separators (they have no selectable/enabled flags)
        if not (item.flags() & (Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)):
            return

        # Pull the competitor name from UserRole
        name = item.data(Qt.ItemDataRole.UserRole)
        if not name:
            return

        competitor = self.find_competitor(name)
        if not competitor:
            return

        menu = QMenu(self)
        notes_action = menu.addAction("📝 Edit Notes")
        action = menu.exec(sender.viewport().mapToGlobal(position))
        if action == notes_action:
            self.show_notes_dialog(competitor)

    def update_resolution_combos(self):
        """Update all resolution combo boxes in the app"""
        # Update statistics tab
        self.stats_resolution_combo.clear()
        self.stats_resolution_combo.addItems(self.resolution_list)
        if self.current_resolution:
            self.stats_resolution_combo.setCurrentText(self.current_resolution)

    def show_notes_dialog(self, competitor):
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Notes for {competitor.name}")
        dialog.setMinimumWidth(400)
        
        layout = QVBoxLayout()
        
        # Create a scroll area for the notes
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        
        container = QWidget()
        container_layout = QVBoxLayout(container)
        
        # Notes category dropdown
        self.notes_dropdown = QComboBox()
        self.notes_dropdown.addItems(["General Notes", "Speech 1", "Speech 2", "Speech 3", "Speech 4", "Speech 5", "Questions"])
        self.notes_dropdown.setCurrentIndex(0)
        container_layout.addWidget(self.notes_dropdown)
        
        # Notes editor
        self.notes_edit = QTextEdit()
        self.notes_edit.setPlainText(competitor.notes.get('general', ''))
        container_layout.addWidget(self.notes_edit)
        
        # Connect dropdown change
        self.notes_dropdown.currentIndexChanged.connect(
            lambda: self.on_notes_category_changed(competitor)
        )
        
        container_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll)
        
        # Save button
        save_button = QPushButton("Save Notes")
        save_button.clicked.connect(lambda: self.save_notes(competitor, dialog))
        layout.addWidget(save_button)
        
        dialog.setLayout(layout)
        dialog.exec()

    def rename_current_file(self):
        if not self.csv_file_path:
            QMessageBox.warning(self, "Error", "No file is currently loaded")
            return
        
        current_dir = os.path.dirname(self.csv_file_path)
        current_filename = os.path.basename(self.csv_file_path)
        
        new_name, ok = QInputDialog.getText(
            self,
            "Rename File",
            "Enter new filename:",
            QLineEdit.EchoMode.Normal,
            current_filename
        )
        
        if ok and new_name.strip():
            if not new_name.lower().endswith('.csv'):
                new_name += '.csv'
            
            new_path = os.path.join(current_dir, new_name)
            
            try:
                # First delete the old file if it exists
                if os.path.exists(new_path):
                    os.remove(new_path)
                    
                os.rename(self.csv_file_path, new_path)
                self.csv_file_path = new_path
                self.update_status(loaded=True, filepath=new_path)
                QMessageBox.information(self, "Success", "File renamed successfully")
                
                # Also remove the original file
                if os.path.exists(self.csv_file_path):
                    os.remove(self.csv_file_path)
                    
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not rename file: {str(e)}")
        
    def on_notes_category_changed(self, competitor):
        category = self.notes_dropdown.currentText().lower().replace(' ', '_')
        if category == 'general_notes':
            category = 'general'
        elif category.startswith('speech_'):
            num = category.split('_')[1]
            category = f'speech_{num}'
        
        # Save current notes before switching
        current_category = self.notes_dropdown.currentData()
        if current_category:
            competitor.notes[current_category] = self.notes_edit.toPlainText()
        
        # Load new category
        self.notes_edit.setPlainText(competitor.notes.get(category, ''))

    def update_display_options(self):
        # Show/hide resolution header
        show_res = self.show_resolution_check.isChecked()
        self.current_resolution_label.setVisible(show_res)
        
        # Update lists to show/hide sides
        self.update_lists()

    def next_resolution(self):
        if not self.resolution_list:
            return
            
        current_idx = self.resolution_list.index(self.current_resolution) if self.current_resolution in self.resolution_list else -1
        next_idx = (current_idx + 1) % len(self.resolution_list)
        self.current_resolution = self.resolution_list[next_idx]
        
        # FIXED: Always reset to Affirmative (not based on current side)
        self.current_side = "Affirmative"
        
        # FIX: Load saved sides for this resolution OR determine from speech history
        for c in self.competitors:
            if self.current_resolution in c.resolution_sides:
                # Restore the saved side for this resolution
                c.current_side = c.resolution_sides[self.current_resolution]
            else:
                # FIX: Check if they have speeches for this resolution and determine side
                if hasattr(c, 'notes') and 'speeches' in c.notes:
                    resolution_speeches = [s for s in c.notes['speeches'] 
                                        if isinstance(s, dict) and s.get('resolution') == self.current_resolution]
                    if resolution_speeches:
                        # Use the most recent side they spoke on for this resolution
                        c.current_side = resolution_speeches[-1].get('side', '')
                        # Save this side for future reference
                        c.resolution_sides[self.current_resolution] = c.current_side
                    else:
                        # Clear side for new resolution
                        c.current_side = ""
                else:
                    # Clear side for new resolution
                    c.current_side = ""
        
        # Update UI
        self.set_current_resolution(self.current_resolution)
        self.update_resolution_display()
        self.update_lists()
        self.save_to_csv()

    def save_notes(self, competitor, dialog):
        # Save current notes before closing
        category = self.notes_dropdown.currentText().lower().replace(' ', '_')
        if category == 'general_notes':
            category = 'general'
        elif category.startswith('speech_'):
            num = category.split('_')[1]
            category = f'speech_{num}'
        
        competitor.notes[category] = self.notes_edit.toPlainText()
        self.save_to_csv()
        dialog.close()


    def start_speech_confirmation(self, competitor):
        # Hide input fields
        self.side_indicator.setVisible(False)
        self.minutes_input.setVisible(False)
        self.seconds_input.setVisible(False)
        self.side_toggle_btn.setVisible(False)
        
        # Change button text
        self.speech_log_button.setText(f"Log for {competitor.name}?")
        
        # Show confirm/cancel buttons
        self.speech_confirm_button.setVisible(True)
        self.speech_cancel_button.setVisible(True)

    # Update on_speech_log_button_clicked
    def on_speech_log_button_clicked(self):
        # This ensures the input row is visible on the first click before proceeding.
        self.speech_input_container.setVisible(True)

        name = self.speech_name_input.currentText().strip()
        if not name:
            QMessageBox.information(self, "Select Competitor",
                "Please choose a competitor from the drop-down to log a speech.")
            return

        competitor = self.find_competitor(name)
        if not competitor:
            QMessageBox.warning(self, "Error", f"No competitor named '{name}' found.")
            return

        self.pending_speech_competitor = competitor
        
        # Connect text box changes to update pending competitor
        try:
            self.speech_name_input.currentTextChanged.disconnect()
        except TypeError:
            pass
        self.speech_name_input.currentTextChanged.connect(self.update_pending_speech_competitor)
        
        self.start_speech_animation_for_pending()

    def start_question_animation(self, competitor):
        # 1) Show the full question row
        self.question_input_container.setVisible(True)

        # 2) Prep the log button and hide cancel
        self.question_log_button.setText("▶ Log Question")
        self.question_cancel_button.setVisible(False)

        try: self.question_log_button.clicked.disconnect()
        except: pass
        self.question_log_button.clicked.connect(lambda: _run_q())

        def _run_q():
            anim = QParallelAnimationGroup(self)
            combo_anim = QPropertyAnimation(self.question_name_input, b"maximumWidth")
            combo_anim.setDuration(250)
            combo_anim.setStartValue(self.question_name_input.width())
            combo_anim.setEndValue(0)
            anim.addAnimation(combo_anim)

            btn = self.question_log_button
            geom = btn.geometry()
            btn.move(self.question_input_container.width() + 10, geom.y())
            btn_anim = QPropertyAnimation(btn, b"pos")
            btn_anim.setDuration(250)
            end = geom.topLeft()
            btn_anim.setStartValue(end + QPoint(80, 0))
            btn_anim.setEndValue(end)
            anim.addAnimation(btn_anim)

            def on_done_q():
                name = competitor.name
                btn.setText(f"✔ Log Question for {name}")
                try: btn.clicked.disconnect()
                except: pass
                btn.clicked.connect(self.confirm_log_question)
                self.question_cancel_button.setVisible(True)
            anim.finished.connect(on_done_q)
            anim.finished.connect(anim.deleteLater)
            anim.start()



    def open_data_folder(self):
        if self.csv_file_path and os.path.exists(self.csv_file_path):
            folder = os.path.dirname(self.csv_file_path)
            os.startfile(folder) if os.name == 'nt' else os.system(f'open "{folder}"' if sys.platform == 'darwin' else f'xdg-open "{folder}"')
        else:
            default_folder = os.path.expanduser("~/Documents/CongressTracker")
            if not os.path.exists(default_folder):
                os.makedirs(default_folder)
            os.startfile(default_folder) if os.name == 'nt' else os.system(f'open "{default_folder}"' if sys.platform == 'darwin' else f'xdg-open "{default_folder}"')

    def save_timer_settings(self):
        self.config['timer_mode'] = self.timer_mode_combo.currentText().lower()
        self.config['speech_time_limit'] = self.time_limit_spin.value()
        self.config['time_signals'] = sorted(
            [int(x.strip()) for x in self.time_signals_edit.text().split(",") if x.strip()],
            reverse=True
        )
        self.save_config()
        QMessageBox.information(self, "Settings Saved", "Timer settings have been updated.")

    def on_speech_input_entered(self):
        name = self.speech_name_input.currentText().strip()
        competitor = self.find_competitor(name)
        if competitor:
            self.pending_speech_competitor = competitor
            self.speech_log_button.setText(f"Log Speech for {competitor.name}")
            self.start_speech_animation(competitor)
        else:
            QMessageBox.warning(self, "Error", f"No competitor named '{name}' found.")

    def start_speech_animation(self, competitor):
        # 1) Ensure the input row (with combo, side, time, buttons) is shown
        self.speech_input_container.setVisible(True)

        # 2) Prep buttons off to the right
        #    We’ll use speech_log_button as both “▶ Log” and then “✔ Confirm”,
        #    and speech_cancel_button stays the same.
        self.speech_log_button.setText("▶ Log Speech")
        self.speech_cancel_button.setVisible(False)

        # Disconnect any old handlers, then make Log start the animation
        try: self.speech_log_button.clicked.disconnect()
        except: pass
        self.speech_log_button.clicked.connect(lambda: _run())

        def _run():
            # Slide‐away the combo, leaving side/time intact
            anim = QParallelAnimationGroup(self)
            combo_anim = QPropertyAnimation(self.speech_name_input, b"maximumWidth")
            combo_anim.setDuration(250)
            combo_anim.setStartValue(self.speech_name_input.width())
            combo_anim.setEndValue(0)
            anim.addAnimation(combo_anim)

            # Slide the same button in
            btn = self.speech_log_button
            geom = btn.geometry()
            btn.move(self.speech_input_container.width() + 10, geom.y())
            btn_anim = QPropertyAnimation(btn, b"pos")
            btn_anim.setDuration(250)
            end = geom.topLeft()
            btn_anim.setStartValue(end + QPoint(80, 0))
            btn_anim.setEndValue(end)
            anim.addAnimation(btn_anim)

            # When done, swap to “Confirm” mode
            def on_done():
                name = competitor.name
                btn.setText(f"✔ Log Speech for {name}")
                try: btn.clicked.disconnect()
                except: pass
                btn.clicked.connect(self.confirm_log_speech)
                self.speech_cancel_button.setVisible(True)
            anim.finished.connect(on_done)
            anim.finished.connect(anim.deleteLater)
            anim.start()

        # Kick off the first-phase (so _run is defined)
        # we don’t call it yet—only on button click




    def update_speech_duration(self):
        if self.speech_start_time:
            elapsed = datetime.datetime.now() - self.speech_start_time
            mins = elapsed.seconds // 60
            secs = elapsed.seconds % 60
            self.speech_duration_label.setText(f"Duration: {mins}:{secs:02}")
    def apply_dark_mode(self):
        qss = """
        /* Base colors */
        QWidget, QLineEdit, QComboBox, QTextEdit {
        background: #2D2D2D;
color: #E0E0E0;
        font-family: 'Segoe UI', Arial, sans-serif;
        font-size: 13px;
        }

        /* Containers */
        QTabWidget::pane, QGroupBox {
        background: #3A3A3A;
border: 1px solid #444;
        }
        QGroupBox {
        margin-top: 10px;
padding-top: 15px;
        }
        QGroupBox::title {
        subcontrol-origin: margin;
left: 10px;
        padding: 0 3px;
        }

        /* Tabs */
        QTabBar::tab {
        background: #3A3A3A;
color: #BBBBBB;
        padding: 8px 16px; margin-right: 2px;
        border: 1px solid #444;
        border-top-left-radius: 4px; border-top-right-radius: 4px;
}
        QTabBar::tab:hover { background: #454545;
}
        QTabBar::tab:selected { background: #505050; color: #FFFFFF; border-bottom-color: #6D9EEB;
}

        /* Lists & Inputs */
        QListWidget, QLineEdit, QComboBox, QTextEdit {
        background: #3A3A3A;
border: 1px solid #444;
        padding: 4px; font-size: 13px;
        }
        QListWidget {
        border-radius: 4px;
}
        QListWidget::item:hover    { background: #444;
}
        QListWidget::item:selected { background: #444}
        

        """
        self.setStyleSheet(qss)

    def on_timer_toggle(self, state):
        enabled = state == Qt.CheckState.Checked.value
        self.config['enable_timer'] = enabled
        self.save_config()
        self.update_timer_visibility()

    def set_timer_visibility(self, visible):
        """Helper method to set visibility of all timer elements"""
        self.timer_label.setVisible(visible)
        self.start_timer_button.setVisible(visible)
        self.stop_timer_button.setVisible(visible) 
        self.reset_timer_button.setVisible(visible)

    def save_config(self):
        try:
            with open(self.config_path, "w") as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            print(f"Error saving config: {e}")

    def load_config(self):
        # Default configuration with all expected settings
        default_config = {
            'enable_timer': True,
            'speech_time_limit': 180,  # 3 minutes
            'time_signals': [60, 30, 10],  # Signal points in seconds
            'timer_mode': 'countdown',  # or 'stopwatch'
            'enable_shortcuts': True,
            'high_contrast': False,
            'large_text': False
        }

        # Set up config directory
        config_dir = os.path.expanduser("~/.congress_tracker")
        os.makedirs(config_dir, exist_ok=True)
        self.config_path = os.path.join(config_dir, "config.json")
        
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r") as f:
                    # Load saved config and merge with defaults
                    saved_config = json.load(f)
                    self.config = {**default_config, **saved_config}
                    
                    # Ensure time_signals is properly formatted
                    if isinstance(self.config['time_signals'], str):
                        # Convert "60,30,10" string to [60, 30, 10] list
                        self.config['time_signals'] = [
                            int(x.strip()) for x in self.config['time_signals'].split(",") 
                            if x.strip().isdigit()
                        ]
                    elif not isinstance(self.config['time_signals'], list):
                        self.config['time_signals'] = default_config['time_signals']
            else:
                # Use defaults if no config file exists
                self.config = default_config
                # Save the default config immediately
                self.save_config()
                
        except Exception as e:
            print(f"Error loading config: {e}")
            # Fall back to defaults if there's any error
            self.config = default_config
            # Try to save the default config
            try:
                self.save_config()
            except:
                pass  # If we can't save, at least we have defaults

        # Final validation of critical values
        if not isinstance(self.config['speech_time_limit'], int) or self.config['speech_time_limit'] <= 0:
            self.config['speech_time_limit'] = 180
        if self.config['timer_mode'] not in ['countdown', 'stopwatch']:
            self.config['timer_mode'] = 'countdown'

    def prompt_load_csv(self):
        default_dir = os.path.expanduser("~/Documents/CongressTracker")
        if not os.path.exists(default_dir):
            os.makedirs(default_dir)
        
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load CSV File",
            default_dir,
            "CSV Files (*.csv)"
        )
        if file_path:
            try:
                self.csv_file_path = file_path
                # Updated to receive resolutions
                loaded_competitors, loaded_history, speech_recency, question_recency, resolution_list, current_resolution, current_side = persistence.load_from_csv(self.csv_file_path)
                
                if not loaded_competitors:
                    QMessageBox.warning(self, "Error", "The CSV file is empty or couldn't be parsed.")
                    return
                
                self.competitors = loaded_competitors
                self.history = loaded_history
                
                # Load the recency orders
                self.speech_recency_order = speech_recency
                self.question_recency_order = question_recency
                
                # Load resolution data
                self.resolution_list = resolution_list or []
                self.current_resolution = current_resolution or ""
                self.current_side = current_side or "Affirmative"
                
                # Initialize missing attributes for backward compatibility
                for c in self.competitors:
                    if not hasattr(c, 'current_side'):
                        c.current_side = ""
                    if not hasattr(c, 'resolution_sides'):
                        c.resolution_sides = {}
                    if not hasattr(c, 'notes'):
                        c.notes = {}
                    if not hasattr(c, 'last_speech_round'):
                        c.last_speech_round = 0
                    if not hasattr(c, 'last_question_round'):
                        c.last_question_round = 0
                
                max_speech_round = max((c.last_speech_round for c in self.competitors), default=0)
                max_question_round = max((c.last_question_round for c in self.competitors), default=0)
                self.current_round = max(max_speech_round, max_question_round)
                
                # Check if any competitor has logged speeches/questions to determine manual mode
                has_speeches = any(c.speeches > 0 for c in self.competitors)
                has_questions = any(c.questions > 0 for c in self.competitors)
                
                self.manual_reordering_speech_enabled = not has_speeches
                self.manual_reordering_question_enabled = not has_questions
                
                self.entered_names = [c.name for c in self.competitors]
                
                # Mark as tracking started
                self.tracking_started = True
                
                # FIX: Load resolution state with proper next speaker determination
                self.load_resolution_state_on_startup()
                
                self.update_lists()
                self.update_all_ui_post_start()
                self.update_history_tab()
                self.update_status(loaded=True, filepath=file_path)
                self.update_tab_indicators()
                
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load CSV file: {str(e)}")
                print(f"Error loading CSV: {traceback.format_exc()}")
                self.csv_file_path = None
                self.update_status(loaded=False)

    def update_tab_indicators(self):
        tab_names = ["Speeches", "Questions", "Settings", "History", "Status", "Statistics", "Credits"]
        current_index = self.tabs.currentIndex()
        
        # Simply set tab names without any indicators to prevent text cutoff
        for i, name in enumerate(tab_names):
            if i < self.tabs.count():  # Make sure we don't exceed available tabs
                self.tabs.setTabText(i, name)


    def add_name(self):
        input_text = self.name_input.text().strip()
        if input_text:
            names = [name.strip() for name in input_text.split(',') if name.strip()]
            for name in names:
                if name.lower() not in [n.lower() for n in self.entered_names]:
                    self.entered_names.append(name)
                    self.competitors.append(Competitor(name))
            self.name_input.clear()
            
            # Update all lists
            self.speech_list.clear()
            self.question_list.clear()
            self.manage_list.clear()
            for name in sorted(self.entered_names, key=lambda x: x.lower()):
                self.speech_list.addItem(name)
                self.question_list.addItem(name)
                self.manage_list.addItem(name)

    def start_tracking(self):
        # Add any remaining names from input
        current_input = self.name_input.text().strip()
        if current_input:
            names = [name.strip() for name in current_input.split(',') if name.strip()]
            for name in names:
                if name.lower() not in [c.name.lower() for c in self.competitors]:
                    self.competitors.append(Competitor(name))
            self.name_input.clear()

        if not self.competitors:
                QMessageBox.warning(self, "Error", "Please add competitors first!")
                return
        
        # FIX: Initialize recency order lists BEFORE the first UI update.
        # This ensures the lists have data to draw from immediately.
        self.speech_recency_order = [c.name for c in self.competitors]
        self.question_recency_order = [c.name for c in self.competitors]
        self.manual_reordering_speech_enabled   = True
        self.manual_reordering_question_enabled = True
        # Set file path ONLY when starting tracking
        if not self.csv_file_path:
            self.csv_file_path = self.get_unique_file_path()

        # Update UI for tracking mode
        self.name_input.hide()
        self.instructions.hide()
        self.start_button.hide()
        self.tracking_started = True
        
        # Enable question logging if using that feature
        if hasattr(self, 'question_log_button'):
            self.question_log_button.setEnabled(True)
            self.question_name_input.setEnabled(True)
        
        # Enable competitor management
        if hasattr(self, 'add_competitor_button'):
            self.add_competitor_button.setEnabled(True)
        
        # Now that everything is set up, update the UI.
        self.update_lists()
        self.update_competitor_combos()
        self.update_status(loaded=True, filepath=self.csv_file_path)
        self.update_tab_indicators()
        self.save_to_csv()

    def update_all_ui_post_start(self):
        """Update UI after loading data or starting tracking"""
        self.name_input.hide()
        self.instructions.hide()
        self.start_button.hide()
        
        # Initialize speech_name_input if it doesn't exist
        if not hasattr(self, 'speech_name_input'):
            self.speech_name_input = QComboBox()
            self.speech_name_input.setEditable(True)
            completer = QCompleter([c.name for c in self.competitors])
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            self.speech_name_input.setCompleter(completer)
        
        # Update competitor lists
        self.update_competitor_combos()
        self.clear_log_inputs()
        self.update_lists()
        self.update_tab_indicators()
        
        # Enable logging buttons
        if hasattr(self, 'speech_log_button'):
            self.speech_log_button.setEnabled(True)
        if hasattr(self, 'question_log_button'):
            self.question_log_button.setEnabled(True)
        if hasattr(self, 'add_competitor_button'):
            self.add_competitor_button.setEnabled(True)
        
        # Refresh seating charts if they exist
        if hasattr(self, 'speech_seating_chart_widget'):
            self.speech_seating_chart_widget.init_ui()
        if hasattr(self, 'question_seating_chart_widget'):
            self.question_seating_chart_widget.init_ui()

    def update_competitor_combos(self):
        names = [c.name for c in self.competitors]
        
        # Speech name combo
        if not hasattr(self, 'speech_name_input'):
            self.speech_name_input = QComboBox()
            self.speech_name_input.setEditable(True)  # Must be editable for completer
        
        self.speech_name_input.clear()
        self.speech_name_input.addItems(names)
        if self.speech_name_input.isEditable():  # Only set completer if editable
            completer = QCompleter(names)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            self.speech_name_input.setCompleter(completer)
        
        # Question name combo
        if hasattr(self, 'question_name_input'):
            self.question_name_input.clear()
            self.question_name_input.addItems(names)
            if self.question_name_input.isEditable():
                completer = QCompleter(names)
                completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
                self.question_name_input.setCompleter(completer)
    def clear_log_inputs(self):
        """Clear all input fields in the logging sections"""
        # For QComboBox, use setCurrentText instead of setText
        if hasattr(self, 'speech_name_input') and isinstance(self.speech_name_input, QComboBox):
            self.speech_name_input.setCurrentText("")
        
        self.minutes_input.clear()
        self.seconds_input.clear()
        
        # Clear question input if it exists
        if hasattr(self, 'question_name_input') and isinstance(self.question_name_input, QComboBox):
            self.question_name_input.setCurrentText("")
        
        # Hide the input container
        self.speech_input_container.setVisible(False)

    def fill_speech_name(self, item: QListWidgetItem):
        # First try our UserRole data, else use the text
        raw = item.data(Qt.ItemDataRole.UserRole)
        text = raw if isinstance(raw, str) else item.text()
        # Extract just the name before any "|" separator
        name = text.split("|")[0].strip()
        
        competitor = self.find_competitor(name)
        if not competitor:
            return

        # show the speech input as before
        self.pending_speech_competitor = competitor
        self.speech_log_button.setText(f"Log Speech for {competitor.name}")
        self.side_indicator.setText("Aff" if self.current_side=="Affirmative" else "Neg")
        self.speech_input_container.setVisible(True)
        self.minutes_input.setFocus()





    def fill_question_name(self, item: QListWidgetItem):
        # Populate the combo from the list’s selected item
        name = item.data(Qt.ItemDataRole.UserRole)
        self.question_name_input.setCurrentText(name)

        # Show the container (so the animation/confirm buttons have somewhere to appear)
        self.question_input_container.setVisible(True)
        self.question_name_input.setFocus()





    def toggle_resolution_settings(self):
        visible = not self.resolution_group.isVisible()
        self.resolution_group.setVisible(visible)
        self.resolution_toggle.setText("▲ Resolution Settings" if visible else "▼ Resolution Settings")

    def log_speech(self):
        if not self.pending_speech_competitor:
            QMessageBox.warning(self, "Error", "No competitor selected for speech.")
            return
        
        competitor = self.pending_speech_competitor
        old_speeches = competitor.speeches
        
        # Get time input (optional)
        minutes = self.minutes_input.text().strip() or "0"
        seconds = self.seconds_input.text().strip() or "0"
        
        try:
            duration = int(minutes) * 60 + int(seconds)
        except ValueError:
            duration = 0
        
        # Assign side if not set
        if not competitor.current_side:
            competitor.current_side = "Aff" if self.current_side == "Affirmative" else "Neg"
        
        competitor.add_speech(
            round_num=self.current_round,
            side=competitor.current_side,
            duration=duration
        )
        
        # Toggle global side for next speaker
        self.current_side = "Negative" if self.current_side == "Affirmative" else "Affirmative"
        
        self.current_round += 1
        competitor.last_speech_round = self.current_round
        self.log_history('speech', competitor.name, 'increment', old_speeches, competitor.speeches)
        self.update_lists()
        self.save_to_csv()
        self.update_resolution_display()
        
        # Clear inputs
        self.minutes_input.clear()
        self.seconds_input.clear()
        self.speech_name_input.clear()
        self.side_indicator.clear()
        self.pending_speech_competitor = None
        self.speech_input_container.setVisible(False)
    def cancel_log_speech(self):
        # 1) Reset layout and UI
        self.speech_confirm_button.setVisible(False)
        self.speech_cancel_button.setVisible(False)

        self.speech_name_input.setMaximumWidth(16777215)
        self.speech_name_input.setCurrentText("")
        self.speech_log_button.setText("Log Speech")
        self.speech_input_container.setVisible(False)

        self.pending_speech_competitor = None
        self.speech_list.clearSelection()



    
    def log_question(self):
        name = self.question_name_input.currentText().strip()
        if not name:
            QMessageBox.warning(self, "Error", "Please select a competitor.")
            return
        
        competitor = self.find_competitor(name)
        if not competitor:
            QMessageBox.warning(self, "Error", f"Competitor '{name}' not found.")
            return
        
        self.pending_question_competitor = competitor
        self.question_log_button.setText(f"Log Question for {competitor.name}")
        self.start_question_animation(competitor)
        
        # Connect confirm button with current state
        self.question_confirm_button.clicked.connect(lambda: self.confirm_log_question(competitor))
    

    def on_tab_changed(self, index):
        self.update_tab_indicators()
        if index == 5:  # Statistics tab index
            self.update_stats_display()
    
    def confirm_log_speech(self):
        # 1) Validate selection
        if not self.pending_speech_competitor:
            QMessageBox.warning(self, "Error", "No competitor selected")
            return

        competitor = self.pending_speech_competitor

        # 2) Get duration and side
        duration = self.get_speech_duration()
        side = "Aff" if self.current_side == "Affirmative" else "Neg"

        # 3a) Capture old count
        old_count = competitor.speeches

        # 3b) Set and save the side for this resolution
        competitor.current_side = side
        if self.current_resolution:
            competitor.resolution_sides[self.current_resolution] = side

        # 3c) Log the speech
        competitor.add_speech(
            round_num=self.current_round,
            side=side,
            duration=duration,
            resolution=self.current_resolution
        )

        # 3d) Capture new count
        new_count = competitor.speeches

        # 3e) Record in history
        self.log_history(
            action_type='speech',
            competitor_name=competitor.name,
            count_type='speech_count',
            old_value=old_count,
            new_value=new_count
        )

        # 4) Toggle side & advance round
        self.current_side = "Negative" if self.current_side == "Affirmative" else "Affirmative"
        self.current_round += 1

        # 5) Refresh UI
        self.update_resolution_display()
        self.manual_reordering_speech_enabled = False
        self.update_lists()
        self.save_to_csv()
        self.update_stats_display()

        # 6) Reset speech‑logging UI
        self.speech_name_input.setMaximumWidth(16777215)
        self.speech_name_input.setCurrentText("")
        self.speech_log_button.setText("Log Speech")
        self.speech_confirm_button.setVisible(False)
        self.speech_cancel_button.setVisible(False)
        self.pending_speech_competitor = None
        self.speech_list.clearSelection()
        self.speech_input_container.setVisible(False)

        # Clear the time inputs after logging
        self.minutes_input.clear()
        self.seconds_input.clear()



    def confirm_log_question(self):
        # 1) Re‐implement your original “log question” steps:
        if not self.pending_question_competitor:
            QMessageBox.warning(self, "Error", "No competitor selected")
            return

        c = self.pending_question_competitor
        old_questions = c.questions
        c.questions += 1
        c.last_question_round = self.current_round
        self.current_round += 1

        self.log_history(
            action_type='question',
            competitor_name=c.name,
            count_type='question_count',
            old_value=old_questions,
            new_value=c.questions
        )

        # Refresh & persist
        self.manual_reordering_question_enabled = False
        self.update_lists()
        self.save_to_csv()

        # 2) Tear down the UI exactly like cancel does:
        self.reset_question_inputs()
        self.question_input_container.setVisible(False)
        self.question_confirm_button.setVisible(False)
        self.question_cancel_button.setVisible(False)
        self.pending_question_competitor = None
        self.question_list.clearSelection()
        self.update_stats_display()


    def cancel_log_question(self):
        # reset UI
        self.question_name_input.setMaximumWidth(self.question_input_container.width())
        self.question_input_container.setVisible(False)
        self.question_confirm_button.setVisible(False)
        self.question_cancel_button.setVisible(False)
        self.question_log_button.setText("Log Question")
        self.pending_question_competitor = None
        self.reset_question_inputs()


    def reset_question_inputs(self):
        self.question_log_button.setText("Log Question")
        self.question_name_input.setVisible(True)  # optional, but harmless

        self.question_confirm_button.setVisible(False)
        self.question_cancel_button.setVisible(False)

        # Hide input container again
        self.question_input_container.setVisible(False)
        

        self.pending_question_competitor = None
        self.question_name_input.setMaximumWidth(16777215)
        self.question_name_input.setCurrentText("")

        self.question_list.clearSelection()

    def find_competitor(self, name):
        # Clean the name by removing any extra formatting or [side] indicator
        clean_name = name.split('[')[0].strip()
        for competitor in self.competitors:
            if competitor.name.lower() == clean_name.lower():
                return competitor
        return None  # Don't show error message here, let caller handle it
    def rename_competitor(self):
        selected_items = self.manage_list.selectedItems()
        if not selected_items:
            return
            
        old_name = selected_items[0].text()
        new_name, ok = QInputDialog.getText(
            self,
            "Rename Competitor",
            f"Enter new name for {old_name}:",
            QLineEdit.EchoMode.Normal,
            old_name
        )
        
        if ok and new_name.strip():
            new_name = new_name.strip()
            # Check for duplicate names
            if any(c.name.lower() == new_name.lower() for c in self.competitors):
                QMessageBox.warning(self, "Error", "A competitor with this name already exists.")
                return
                
            # Find and update the competitor
            for c in self.competitors:
                if c.name == old_name:
                    c.name = new_name
                    break
            
            # Update recency orders
            if old_name in self.speech_recency_order:
                idx = self.speech_recency_order.index(old_name)
                self.speech_recency_order[idx] = new_name
            if old_name in self.question_recency_order:
                idx = self.question_recency_order.index(old_name)
                self.question_recency_order[idx] = new_name
                    
            # Update all lists and UI
            self.update_lists()
            self.update_competitor_combos()
            self.save_to_csv()
    
    def update_lists(self):
        # 1) If no data, just show names
        if not self.competitors:
            self.speech_list.clear()
            self.question_list.clear()
            for name in sorted(self.entered_names):
                for lw in (self.speech_list, self.question_list):
                    lw.addItem(QListWidgetItem(name))
            return

        # 2) Determine manual vs automatic modes
        in_manual_speech = self.manual_reordering_speech_enabled
        in_manual_question = self.manual_reordering_question_enabled

        # 3) Build ordered lists
        # Speech order: ALWAYS use preserved recency order as base, then sort by count within groups
        temp = {c.name: c for c in self.competitors}
        
        if in_manual_speech:
            # Pure manual mode - use exact recency order
            speakers = [temp[name] for name in self.speech_recency_order if name in temp]
        else:
            # Automatic mode - preserve recency order within each speech count group
            # Group competitors by speech count
            speech_groups = {}
            for comp in self.competitors:
                count = comp.speeches
                if count not in speech_groups:
                    speech_groups[count] = []
                speech_groups[count].append(comp)
            
            # Sort each group by recency order (preserve manual ordering within groups)
            speakers = []
            for count in sorted(speech_groups.keys()):
                group = speech_groups[count]
                # Sort this group by recency order (lower index = higher priority)
                group_sorted = sorted(group, key=lambda c: self.speech_recency_order.index(c.name) 
                                    if c.name in self.speech_recency_order else float('inf'))
                speakers.extend(group_sorted)
        
        for idx, comp in enumerate(speakers, start=1):
            comp.speech_rank = idx

        # Question order: same logic
        if in_manual_question:
            # Pure manual mode - use exact recency order
            askers = [temp[name] for name in self.question_recency_order if name in temp]
        else:
            # Automatic mode - preserve recency order within each question count group
            question_groups = {}
            for comp in self.competitors:
                count = comp.questions
                if count not in question_groups:
                    question_groups[count] = []
                question_groups[count].append(comp)
            
            # Sort each group by recency order
            askers = []
            for count in sorted(question_groups.keys()):
                group = question_groups[count]
                group_sorted = sorted(group, key=lambda c: self.question_recency_order.index(c.name) 
                                    if c.name in self.question_recency_order else float('inf'))
                askers.extend(group_sorted)
                
        for idx, comp in enumerate(askers, start=1):
            comp.question_rank = idx

        # 4) Compute column widths
        fm = self.speech_list.fontMetrics()
        name_w   = max(fm.horizontalAdvance(c.name) for c in self.competitors) + 20
        marker_w = fm.horizontalAdvance("|")
        side_w   = fm.horizontalAdvance("Neg") + 10
        label_w  = fm.horizontalAdvance("Speeches:")
        count_w  = fm.horizontalAdvance("99") + 10
        rec_w    = fm.horizontalAdvance("Recency:") + fm.horizontalAdvance("99")

        # Helpers
        def make_label(text, fixed_w=None):
            lbl = QLabel(text)
            if fixed_w is not None:
                lbl.setFixedWidth(fixed_w)
            lbl.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
            lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            return lbl

        def make_separator_item():
            sep = QFrame()
            sep.setFixedHeight(1)
            sep.setStyleSheet("background-color: rgba(255,255,255,0.15); border: none;")
            container = QWidget()
            layout = QHBoxLayout(container)
            layout.setContentsMargins(8,1,8,1)
            layout.addWidget(sep)
            item = QListWidgetItem()
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setSizeHint(container.sizeHint())
            return item, container

        # 5) Populate SPEECH list
        self.speech_list.clear()
        last_s = None
        for comp in speakers:
            if last_s is not None and comp.speeches != last_s:
                sep_item, sep_widget = make_separator_item()
                self.speech_list.addItem(sep_item)
                self.speech_list.setItemWidget(sep_item, sep_widget)

            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, comp.name)
            widget = QWidget()
            widget.setStyleSheet("background: transparent;")
            lo = QHBoxLayout(widget)
            lo.setContentsMargins(8,4,8,4)
            lo.setSpacing(6)
            lo.setAlignment(Qt.AlignmentFlag.AlignLeft)

            lo.addWidget(make_label(comp.name, name_w))
            lo.addWidget(make_label("|", marker_w))
            lo.addWidget(make_label(comp.current_side or "—", side_w))
            lo.addWidget(make_label("|", marker_w))
            lo.addWidget(make_label("Speeches:", label_w))
            lo.addWidget(make_label(str(comp.speeches), count_w))
            lo.addWidget(make_label("|", marker_w))
            lo.addWidget(make_label("Recency:", None))
            lo.addWidget(make_label(str(comp.speech_rank), None))

            if in_manual_speech:
                up = QPushButton("▲")
                up.setFixedSize(20,20)
                up.clicked.connect(lambda _, n=comp.name: self.move_competitor(n, -1, 'speech'))
                down = QPushButton("▼")
                down.setFixedSize(20,20)
                down.clicked.connect(lambda _, n=comp.name: self.move_competitor(n, 1, 'speech'))
                lo.addWidget(up)
                lo.addWidget(down)

            lo.addStretch()
            item.setSizeHint(widget.sizeHint())
            self.speech_list.addItem(item)
            self.speech_list.setItemWidget(item, widget)
            last_s = comp.speeches

        # 6) Populate QUESTION list
        self.question_list.clear()
        last_q = None
        for comp in askers:
            if last_q is not None and comp.questions != last_q:
                sep_item, sep_widget = make_separator_item()
                self.question_list.addItem(sep_item)
                self.question_list.setItemWidget(sep_item, sep_widget)

            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, comp.name)
            widget = QWidget()
            widget.setStyleSheet("background: transparent;")
            lo = QHBoxLayout(widget)
            lo.setContentsMargins(8,4,8,4)
            lo.setSpacing(6)
            lo.setAlignment(Qt.AlignmentFlag.AlignLeft)

            lo.addWidget(make_label(comp.name, name_w))
            lo.addWidget(make_label("|", marker_w))
            lo.addWidget(make_label("Questions:", label_w))
            lo.addWidget(make_label(str(comp.questions), count_w))
            lo.addWidget(make_label("|", marker_w))
            lo.addWidget(make_label("Recency:", None))
            lo.addWidget(make_label(str(comp.question_rank), None))

            if in_manual_question:
                up = QPushButton("▲")
                up.setFixedSize(20,20)
                up.clicked.connect(lambda _, n=comp.name: self.move_competitor(n, -1, 'question'))
                down = QPushButton("▼")
                down.setFixedSize(20,20)
                down.clicked.connect(lambda _, n=comp.name: self.move_competitor(n, 1, 'question'))
                lo.addWidget(up)
                lo.addWidget(down)

            lo.addStretch()
            item.setSizeHint(widget.sizeHint())
            self.question_list.addItem(item)
            self.question_list.setItemWidget(item, widget)
            last_q = comp.questions

        # 7) Rebuild manage list
        self.manage_list.clear()
        for c in sorted(self.competitors, key=lambda x: x.name.lower()):
            self.manage_list.addItem(c.name)
        self.update_manage_buttons()



    def rename_competitor(self):
            selected_items = self.manage_list.selectedItems()
            if not selected_items:
                return
            old_name = selected_items[0].text()
            new_name, ok = QInputDialog.getText(self, "Rename Competitor", f"Rename '{old_name}' to:")
            if ok and new_name.strip():
                new_name = new_name.strip()
                if any(c.name.lower() == new_name.lower() for c in self.competitors):
                    QMessageBox.warning(self, "Error", f"A competitor named '{new_name}' already exists.")
                    return
                for c in self.competitors:
                    if c.name == old_name:
                        c.name = new_name
                        break
                self.update_competitor_combos()
                self.update_lists()
                self.save_to_csv()




    def delete_competitor(self):
        selected_items = self.manage_list.selectedItems()
        if not selected_items:
            return
        name_to_delete = selected_items[0].text()
        reply = QMessageBox.question(
            self,
            "Delete Competitor",
            f"Are you sure you want to delete '{name_to_delete}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.competitors = [c for c in self.competitors if c.name != name_to_delete]
            
            # Remove from recency orders
            if name_to_delete in self.speech_recency_order:
                self.speech_recency_order.remove(name_to_delete)
            if name_to_delete in self.question_recency_order:
                self.question_recency_order.remove(name_to_delete)
                
            self.update_competitor_combos()
            self.update_lists()
            self.save_to_csv()

    def add_competitor(self):
        new_name, ok = QInputDialog.getText(self, "Add Competitor", "Enter new competitor name:")
        if ok and new_name.strip():
            new_name = new_name.strip()
            if any(c.name.lower() == new_name.lower() for c in self.competitors):
                QMessageBox.warning(self, "Error", f"A competitor named '{new_name}' already exists.")
                return
            c = Competitor(new_name)
            c.last_speech_round = 0
            c.last_question_round = 0
            self.competitors.append(c)
            
            # Add to recency orders
            self.speech_recency_order.append(new_name)
            self.question_recency_order.append(new_name)
            
            self.update_competitor_combos()
            self.update_lists()
            self.save_to_csv()

    def update_manage_buttons(self):
        selected = bool(self.manage_list.selectedItems())
        self.rename_button.setEnabled(selected)
        self.delete_button.setEnabled(selected)
    def setup_keyboard_shortcuts(self):
        """Set up keyboard shortcuts"""
        if not self.config.get('enable_shortcuts', True):
            return
        
        # Timer shortcuts
        self.start_timer_shortcut = QShortcut(QKeySequence("Space"), self)
        self.start_timer_shortcut.activated.connect(self.toggle_timer)
        
        self.reset_timer_shortcut = QShortcut(QKeySequence("Ctrl+R"), self)
        self.reset_timer_shortcut.activated.connect(self.reset_timer)
        
        # Speech logging shortcuts
        self.log_speech_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        self.log_speech_shortcut.activated.connect(self.quick_log_speech)
        
        # Question logging shortcuts  
        self.log_question_shortcut = QShortcut(QKeySequence("Ctrl+Q"), self)
        self.log_question_shortcut.activated.connect(self.quick_log_question)
        
        # Navigation shortcuts
        self.next_tab_shortcut = QShortcut(QKeySequence("Ctrl+Tab"), self)
        self.next_tab_shortcut.activated.connect(self.next_tab)
        
        self.prev_tab_shortcut = QShortcut(QKeySequence("Ctrl+Shift+Tab"), self)
        self.prev_tab_shortcut.activated.connect(self.prev_tab)

    def toggle_timer(self):
        """Toggle timer start/pause/resume with spacebar (for keyboard shortcut)"""
        self.toggle_timer_state()

    def quick_log_speech(self):
        """Quick log speech for first person in speech list"""
        if not self.tracking_started or self.speech_list.count() == 0:
            return
        
        # Get first item that's not a separator
        first_item = None
        for i in range(self.speech_list.count()):
            item = self.speech_list.item(i)
            if item.flags() & Qt.ItemFlag.ItemIsSelectable:
                first_item = item
                break
        
        if first_item:
            self.on_speech_list_double_clicked(first_item)

    def quick_log_question(self):
        """Quick log question for first person in question list"""
        if not self.tracking_started or self.question_list.count() == 0:
            return
        
        # Get first item that's not a separator
        first_item = None
        for i in range(self.question_list.count()):
            item = self.question_list.item(i)
            if item.flags() & Qt.ItemFlag.ItemIsSelectable:
                first_item = item
                break
        
        if first_item:
            self.on_question_list_double_clicked(first_item)

    def next_tab(self):
        """Go to next tab"""
        current = self.tabs.currentIndex()
        next_index = (current + 1) % self.tabs.count()
        self.tabs.setCurrentIndex(next_index)

    def prev_tab(self):
        """Go to previous tab"""
        current = self.tabs.currentIndex()
        prev_index = (current - 1) % self.tabs.count()
        self.tabs.setCurrentIndex(prev_index)

    def apply_accessibility_settings(self):
        """Apply accessibility settings like high contrast and large text"""
        base_font_size = 13
        if self.config.get('large_text', False):
            base_font_size = 16
        
        if self.config.get('high_contrast', False):
            # High contrast dark theme
            qss = f"""
            QWidget, QLineEdit, QComboBox, QTextEdit {{
                background: #000000;
                color: #FFFFFF;
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: {base_font_size}px;
                font-weight: bold;
            }}
            
            QTabWidget::pane, QGroupBox {{
                background: #1A1A1A;
                border: 2px solid #FFFFFF;
            }}
            
            QTabBar::tab {{
                background: #000000;
                color: #FFFFFF;
                padding: 8px 16px;
                margin-right: 2px;
                border: 2px solid #FFFFFF;
                font-weight: bold;
            }}
            QTabBar::tab:hover {{
                background: #333333;
            }}
            QTabBar::tab:selected {{
                background: #FFFFFF;
                color: #000000;
            }}
            
            QListWidget, QLineEdit, QComboBox, QTextEdit {{
                background: #000000;
                border: 2px solid #FFFFFF;
                color: #FFFFFF;
                padding: 6px;
                font-size: {base_font_size}px;
                font-weight: bold;
            }}
            
            QListWidget::item:hover {{
                background: #444444;
            }}
            QListWidget::item:selected {{
                background: #FFFFFF;
                color: #000000;
            }}
            
            QPushButton {{
                background: #000000;
                color: #FFFFFF;
                border: 2px solid #FFFFFF;
                padding: 8px 16px;
                font-size: {base_font_size}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: #FFFFFF;
                color: #000000;
            }}
            QPushButton:pressed {{
                background: #CCCCCC;
                color: #000000;
            }}
            
            QLabel {{
                color: #FFFFFF;
                font-size: {base_font_size}px;
                font-weight: bold;
            }}
            """
        else:
            # Regular dark theme with size adjustment
            qss = f"""
            QWidget, QLineEdit, QComboBox, QTextEdit {{
                background: #2D2D2D;
                color: #E0E0E0;
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: {base_font_size}px;
            }}

            QTabWidget::pane, QGroupBox {{
                background: #3A3A3A;
                border: 1px solid #444;
            }}
            QGroupBox {{
                margin-top: 10px;
                padding-top: 15px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px;
            }}

            QTabBar::tab {{
                background: #3A3A3A;
                color: #BBBBBB;
                padding: 8px 16px;
                margin-right: 2px;
                border: 1px solid #444;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }}
            QTabBar::tab:hover {{
                background: #454545;
            }}
            QTabBar::tab:selected {{
                background: #505050;
                color: #FFFFFF;
                border-bottom-color: #6D9EEB;
            }}

            QListWidget, QLineEdit, QComboBox, QTextEdit {{
                background: #3A3A3A;
                border: 1px solid #444;
                padding: 4px;
                font-size: {base_font_size}px;
            }}
            QListWidget {{
                border-radius: 4px;
            }}
            QListWidget::item:hover {{
                background: #444;
            }}
            QListWidget::item:selected {{
                background: #444;
            }}
            """
        
        self.setStyleSheet(qss)

    def save_accessibility_settings(self):
        """Save accessibility settings to config"""
        self.config['enable_shortcuts'] = self.shortcuts_checkbox.isChecked()
        self.config['high_contrast'] = self.high_contrast_checkbox.isChecked()
        self.config['large_text'] = self.large_text_checkbox.isChecked()
        self.save_config()
        
        # Apply settings immediately
        self.apply_accessibility_settings()
        self.setup_keyboard_shortcuts()
        
        QMessageBox.information(self, "Settings Saved", "Accessibility settings have been updated.")

    def toggle_accessibility_settings(self):
        """Toggle accessibility settings panel"""
        visible = not self.accessibility_group.isVisible()
        self.accessibility_group.setVisible(visible)
        self.accessibility_toggle.setText("▲ Accessibility Settings" if visible else "▼ Accessibility Settings")



if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = CongressTracker()
    window.show()
    sys.exit(app.exec())