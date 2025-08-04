import csv
import os
import json
from PyQt6.QtWidgets import QMessageBox
from models import Competitor

MAP_STATE_PATH = 'data/map_state.json'

def save_map_state(self):
    try:
        os.makedirs(os.path.dirname(MAP_STATE_PATH), exist_ok=True)
        data = {
            'zoom': getattr(self, 'current_zoom', 1.0),
        }
        with open(MAP_STATE_PATH, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        QMessageBox.warning(None, "Save Error", f"Failed to save map state: {str(e)}")

def load_from_csv(file_path):
    competitors = []
    history = []
    speech_recency_order = []
    question_recency_order = []
    resolution_list = []
    current_resolution = ""
    current_side = "Affirmative"
    
    try:
        # Load competitors
        with open(file_path, 'r', newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                try:
                    if 'name' not in row:
                        continue
                    # Use the from_dict class method to properly reconstruct the competitor
                    competitor = Competitor.from_dict(row)
                    if competitor.speech_rank == 0:
                        competitor.speech_rank = len(competitors) + 1
                    if competitor.question_rank == 0:
                        competitor.question_rank = len(competitors) + 1
                    competitors.append(competitor)
                except Exception as e:
                    print(f"Error parsing row {row}: {str(e)}")
                    continue

        # Load history if it exists
        history_filepath = file_path.replace('.csv', '_history.json')
        if os.path.exists(history_filepath):
            try:
                with open(history_filepath, 'r', encoding='utf-8') as f:
                    history_data = json.load(f)
                from models import HistoryItem # Import here to avoid circular imports
                history = [HistoryItem.from_dict(item) for item in history_data]
            except Exception as e:
                print(f"Error loading history: {str(e)}")

        # Load recency orders if they exist
        recency_filepath = file_path.replace('.csv', '_recency.json')
        if os.path.exists(recency_filepath):
            try:
                with open(recency_filepath, 'r', encoding='utf-8') as f:
                    recency_data = json.load(f)
                    speech_recency_order = recency_data.get('speech_recency_order', [])
                    question_recency_order = recency_data.get('question_recency_order', [])
            except Exception as e:
                print(f"Error loading recency orders: {str(e)}")
        
        # Load resolution data if it exists
        resolution_filepath = file_path.replace('.csv', '_resolutions.json')
        if os.path.exists(resolution_filepath):
            try:
                with open(resolution_filepath, 'r', encoding='utf-8') as f:
                    resolution_data = json.load(f)
                    resolution_list = resolution_data.get('resolution_list', [])
                    current_resolution = resolution_data.get('current_resolution', "")
                    current_side = resolution_data.get('current_side', "Affirmative")
            except Exception as e:
                print(f"Error loading resolution data: {str(e)}")
        
        # If no recency orders were loaded, create default ones
        if not speech_recency_order:
            speech_recency_order = [c.name for c in competitors]
        if not question_recency_order:
            question_recency_order = [c.name for c in competitors]

    except Exception as e:
        print(f"Error loading CSV: {str(e)}")
        raise

    return competitors, history, speech_recency_order, question_recency_order, resolution_list, current_resolution, current_side

def save_to_csv(filepath, competitors, history=None, speech_recency_order=None, question_recency_order=None, resolution_list=None, current_resolution=None, current_side=None):
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        # Save competitors
        with open(filepath, 'w', newline='', encoding='utf-8') as file:
            if competitors:
                fieldnames = [
                    'name',
                    'speeches',
                    'questions',
                    'last_speech_round',
                    'last_question_round',
                    'speech_rank',
                    'question_rank',
                    'current_side',
                    'notes',
                ]
                writer = csv.DictWriter(file, fieldnames=fieldnames)
                writer.writeheader()
                for c in competitors:
                    data = c.to_dict()
                    # Serialize notes to JSON string if they exist
                    if hasattr(c, 'notes'):
                        data['notes'] = json.dumps(c.notes)
                    else:
                        data['notes'] = json.dumps({'speeches': [], 'questions': []})
                    writer.writerow(data)

        # Save history separately as JSON
        if history is not None:
            history_filepath = filepath.replace('.csv', '_history.json')
            with open(history_filepath, 'w', encoding='utf-8') as f:
                history_data = [item.to_dict() for item in history]
                json.dump(history_data, f, indent=2)

        # Save recency orders separately as JSON
        if speech_recency_order is not None or question_recency_order is not None:
            recency_filepath = filepath.replace('.csv', '_recency.json')
            recency_data = {}
            if speech_recency_order is not None:
                recency_data['speech_recency_order'] = speech_recency_order
            if question_recency_order is not None:
                recency_data['question_recency_order'] = question_recency_order
            
            with open(recency_filepath, 'w', encoding='utf-8') as f:
                json.dump(recency_data, f, indent=2)

        # Save resolution data separately as JSON
        if resolution_list is not None or current_resolution is not None or current_side is not None:
            resolution_filepath = filepath.replace('.csv', '_resolutions.json')
            resolution_data = {}
            if resolution_list is not None:
                resolution_data['resolution_list'] = resolution_list
            if current_resolution is not None:
                resolution_data['current_resolution'] = current_resolution
            if current_side is not None:
                resolution_data['current_side'] = current_side
            
            with open(resolution_filepath, 'w', encoding='utf-8') as f:
                json.dump(resolution_data, f, indent=2)

    except Exception as e:
        QMessageBox.warning(None, "Save Error", f"Failed to save CSV file: {str(e)}")

def clear_csv_data(filepath):
    try:
        if os.path.exists(filepath):
            os.remove(filepath) # Deletes the file entirely
        
        # Also remove associated files
        history_filepath = filepath.replace('.csv', '_history.json')
        if os.path.exists(history_filepath):
            os.remove(history_filepath)
            
        recency_filepath = filepath.replace('.csv', '_recency.json')
        if os.path.exists(recency_filepath):
            os.remove(recency_filepath)
            
        resolution_filepath = filepath.replace('.csv', '_resolutions.json')
        if os.path.exists(resolution_filepath):
            os.remove(resolution_filepath)
            
    except Exception as e:
        QMessageBox.warning(None, "Clear Error", f"Failed to delete file: {str(e)}")