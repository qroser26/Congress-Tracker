import csv
import os
import json
from PyQt6.QtWidgets import QMessageBox
from models import Competitor

# In persistence.py (or the relevant part of your code)

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
    try:
        with open(file_path, 'r', newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                try:
                    if 'name' not in row:
                        continue
                    competitor = Competitor(row['name'])
                    # ...existing attribute loads...
                    competitors.append(competitor)
                except Exception as e:
                    print(f"Error parsing row {row}: {str(e)}")
                    continue
    except Exception as e:
        print(f"Error loading CSV: {str(e)}")
        raise
    return competitors
def save_to_csv(filepath, competitors):
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
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
                        data['notes'] = json.dumps({'speeches': [], 'questions': ''})
                    writer.writerow(data)
    except Exception as e:
        QMessageBox.warning(None, "Save Error", f"Failed to save CSV file: {str(e)}")

def clear_csv_data(filepath):
    try:
        if os.path.exists(filepath):
            os.remove(filepath)  # Deletes the file entirely
    except Exception as e:
        QMessageBox.warning(None, "Clear Error", f"Failed to delete file: {str(e)}")