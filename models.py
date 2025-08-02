import datetime
import json

class Competitor:
    def __init__(self, name):
        self.name = name
        self.speeches = 0
        self.questions = 0
        self.last_speech_round = 0
        self.last_question_round = 0
        self.speech_rank = 0
        self.question_rank = 0
        self.current_side = ""
        self.notes = {
            'speeches': [],
            'questions': [],
            'general': ""
        }
        
    def to_dict(self):
        """Convert competitor data to dictionary for serialization"""
        return {
            'name': self.name,
            'speeches': self.speeches,
            'questions': self.questions,
            'last_speech_round': self.last_speech_round,
            'last_question_round': self.last_question_round,
            'speech_rank': self.speech_rank,
            'question_rank': self.question_rank,
            'current_side': self.current_side,
            'notes': self.notes  # Store notes directly (will be JSON serialized later)
        }
        
    def add_speech(self, round_num, side="", duration=0, resolution=""):
        """Add a speech record with full details"""
        speech_data = {
            'round': round_num,
            'side': side,
            'duration': duration,
            'timestamp': datetime.datetime.now().isoformat(),
            'resolution': resolution
        }
        self.notes['speeches'].append(speech_data)
        self.speeches = len(self.notes['speeches'])
        self.current_side = side
        self.last_speech_round = round_num
        
    def add_question(self, round_num):
        """Add a question record"""
        question_data = {
            'round': round_num,
            'timestamp': datetime.datetime.now().isoformat()
        }
        self.notes['questions'].append(question_data)
        self.questions = len(self.notes['questions'])
        self.last_question_round = round_num
        
    def reset_side(self):
        """Reset side when resolution changes"""
        self.current_side = ""
        
    @classmethod
    def from_dict(cls, data):
        """Create Competitor from dictionary with robust error handling"""
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                data = {'name': 'Unknown'}
                
        competitor = cls(data.get('name', 'Unknown'))
        
        # Set all attributes with defaults
        competitor.speeches = int(data.get('speeches', 0))
        competitor.questions = int(data.get('questions', 0))
        competitor.last_speech_round = int(data.get('last_speech_round', 0))
        competitor.last_question_round = int(data.get('last_question_round', 0))
        competitor.speech_rank = int(data.get('speech_rank', 0))
        competitor.question_rank = int(data.get('question_rank', 0))
        competitor.current_side = data.get('current_side', "")
        # Handle notes with validation
        notes = data.get('notes', {})
        if isinstance(notes, str):
            try:
                notes = json.loads(notes)
            except json.JSONDecodeError:
                notes = {}
                
        # Ensure notes has required structure
        competitor.notes = {
            'speeches': notes.get('speeches', []),
            'questions': notes.get('questions', []),
            'general': notes.get('general', "")
        }
        
        # Validate speech data
        for speech in competitor.notes['speeches']:
            if not isinstance(speech, dict):
                competitor.notes['speeches'].remove(speech)
                continue
            speech.setdefault('resolution', "")
            speech.setdefault('side', "")
            speech.setdefault('duration', 0)
            
        return competitor
        
    def speech_display(self, show_sides=True):
        """Format for speech list display"""
        side_display = f"[{self.current_side}]" if show_sides and self.current_side else ""
        return f"{self.name:<20}{side_display:^6} | Speeches: {self.speeches:<3} | Rank: {self.speech_rank}"
        
    def question_display(self, show_sides=True):
        """Format for question list display"""
        side_display = f"[{self.current_side}]" if show_sides and self.current_side else ""
        return f"{self.name:<20}{side_display:^6} | Questions: {self.questions:<3} | Rank: {self.question_rank}"


class HistoryItem:
    def __init__(self, action_type, competitor_name, count_type, old_value, new_value, timestamp):
        self.action_type = action_type
        self.competitor_name = competitor_name
        self.count_type = count_type
        self.old_value = old_value
        self.new_value = new_value
        self.timestamp = timestamp
        
    def display_text(self):
        action = "gave speech" if self.action_type == 'speech' else "asked question"
        details = f" ({self.details})" if self.details else ""
        return f"{self.timestamp}: {self.competitor_name} {action} (was {self.old_value}, now {self.new_value}){details}"