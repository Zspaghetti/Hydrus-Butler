from flask import Flask, render_template, send_from_directory, request, jsonify, flash, redirect, url_for
import os
import json
import requests
import uuid
import math
from datetime import datetime, timedelta
from flask_apscheduler import APScheduler
import logging
import secrets
import sqlite3
import sys


# Configure logging
logging.basicConfig(level=logging.INFO) # Set base logging level
# logging.getLogger('apscheduler').setLevel(logging.DEBUG)

app = Flask(__name__)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
SETTINGS_FILE = os.path.join(BASE_DIR, 'settings.json')
RULES_FILE = os.path.join(BASE_DIR, 'rules.json')
DB_DIR = os.path.join(BASE_DIR, 'db')
CONFLICT_DB_FILE = os.path.join(DB_DIR, 'conflict_overrides.db')

# Initialize Scheduler
scheduler = APScheduler()


# --- Settings Functions ---
def load_settings():
    """
    Loads settings from file, merging with defaults.
    Generates and saves a new secret_key if one is missing.
    Scans for available themes.
    """
    print("\n--- Loading settings ---")
    default_settings = {
        'api_address': 'http://localhost:45869',
        'api_key': '',
        'rule_interval_seconds': 0,
        'last_viewed_threshold_seconds': 3600,
        'secret_key': None,
        'show_run_notifications': True,
        'show_run_all_notifications': True,
        'theme': 'Blueprint',
        'available_themes': ['Blueprint'],
        'butler_name': 'Hydrus Butler' 
    }
    settings = {}
    settings_file_exists = os.path.exists(SETTINGS_FILE)

    if settings_file_exists:
        print(f"Settings file exists: {SETTINGS_FILE}")
        try:
            with open(SETTINGS_FILE, 'r') as f:
                loaded_settings = json.load(f)
                if isinstance(loaded_settings, dict):
                     settings = loaded_settings
                     print("Successfully loaded settings from file.")
                else:
                     print(f"Warning: Settings file {SETTINGS_FILE} contains non-dict data. Using default settings.")
                     settings_file_exists = False # Treat as if file doesn't exist for saving purposes
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading settings from {SETTINGS_FILE}: {e}")
            settings = {}
            settings_file_exists = False # Treat as if file doesn't exist for saving purposes
    else:
        print(f"Settings file not found: {SETTINGS_FILE}. Using default settings.")

    key_generated = False
    if 'secret_key' not in settings or not settings['secret_key']:
        print("Secret key not found or is empty. Generating a new one...")
        generated_key_bytes = secrets.token_bytes(24)
        settings['secret_key'] = generated_key_bytes.hex()
        key_generated = True
        print("New secret key generated.")
    else:
        print("Secret key found in settings.")
        settings['secret_key'] = str(settings['secret_key'])

    available_themes_discovered = []
    themes_dir = os.path.join(BASE_DIR, 'static', 'css')
    if os.path.exists(themes_dir) and os.path.isdir(themes_dir):
        for filename in os.listdir(themes_dir):
            if filename.endswith('.css'):
                theme_name = filename[:-4]
                available_themes_discovered.append(theme_name)
        if not available_themes_discovered:
            available_themes_discovered.append('default')
            print(f"Warning: No CSS files found in {themes_dir}. Defaulting to 'available_themes': ['default']. Make sure you have at least one theme CSS file (e.g., default.css).")
        else:
            print(f"Discovered themes: {available_themes_discovered}")
    else:
        print(f"Warning: Themes directory {themes_dir} not found. Defaulting to 'available_themes': ['default'].")
        available_themes_discovered.append('default')

    settings['available_themes'] = sorted(list(set(available_themes_discovered)))

    final_settings = {**default_settings, **settings}

    if final_settings.get('theme') not in final_settings['available_themes']:
        print(f"Warning: Saved theme '{final_settings.get('theme')}' is not in available themes {final_settings['available_themes']}. Falling back to default '{default_settings['theme']}'.")
        final_settings['theme'] = default_settings['theme']
        if final_settings['theme'] not in final_settings['available_themes'] and final_settings['available_themes']:
            final_settings['theme'] = final_settings['available_themes'][0]
        elif not final_settings['available_themes']:
             final_settings['theme'] = 'default'


    try:
        final_settings['rule_interval_seconds'] = int(final_settings.get('rule_interval_seconds', default_settings['rule_interval_seconds']))
    except (ValueError, TypeError):
        print(f"Warning: Invalid value for rule_interval_seconds. Using default.")
        final_settings['rule_interval_seconds'] = default_settings['rule_interval_seconds']

    try:
        final_settings['last_viewed_threshold_seconds'] = int(final_settings.get('last_viewed_threshold_seconds', default_settings['last_viewed_threshold_seconds']))
    except (ValueError, TypeError):
        print(f"Warning: Invalid value for last_viewed_threshold_seconds. Using default.")
        final_settings['last_viewed_threshold_seconds'] = default_settings['last_viewed_threshold_seconds']

    if not isinstance(final_settings.get('show_run_notifications'), bool):
         print(f"Warning: Invalid value for show_run_notifications. Using default.")
         final_settings['show_run_notifications'] = default_settings['show_run_notifications']

    if not isinstance(final_settings.get('show_run_all_notifications'), bool):
         print(f"Warning: Invalid value for show_run_all_notifications. Using default.")
         final_settings['show_run_all_notifications'] = default_settings['show_run_all_notifications']

    if not isinstance(final_settings.get('theme'), str):
        print(f"Warning: Invalid type for theme. Using default '{default_settings['theme']}'.")
        final_settings['theme'] = default_settings['theme']
        if final_settings['theme'] not in final_settings['available_themes'] and final_settings['available_themes']:
            final_settings['theme'] = final_settings['available_themes'][0]
        elif not final_settings['available_themes']:
             final_settings['theme'] = 'default'

    if not isinstance(final_settings.get('butler_name'), str) or not final_settings.get('butler_name').strip():
        print(f"Warning: Invalid or empty value for butler_name. Using default '{default_settings['butler_name']}'.")
        final_settings['butler_name'] = default_settings['butler_name']
    else:
        final_settings['butler_name'] = final_settings['butler_name'].strip() # Ensure no leading/trailing spaces

    should_save_file = key_generated or not settings_file_exists or \
                       settings.get('available_themes') != final_settings.get('available_themes') or \
                       settings.get('theme') != final_settings.get('theme') or \
                       'show_run_all_notifications' not in settings or \
                       'butler_name' not in settings or settings.get('butler_name') != final_settings.get('butler_name') # Save if new setting is missing or changed by sanitization

    if should_save_file:
         print("Saving settings file to persist changes (key, theme, available_themes, new setting, or new file).")
         try:
             with open(SETTINGS_FILE, 'w') as f:
                 json.dump(final_settings, f, indent=4)
             print(f"Settings file saved: {SETTINGS_FILE}")
         except IOError as e:
              print(f"CRITICAL ERROR: Could not save settings file {SETTINGS_FILE}: {e}")
              print("Please check file permissions.")

    print("Final processed settings:", final_settings)
    print("--- Finished loading settings ---")
    return final_settings

def save_settings(submitted_settings_data):
    """Saves settings, merging with current, and handles API key/secret key privacy."""
    print("\n--- Saving settings ---")
    print("Received settings data for saving:", submitted_settings_data)
    try:
        # Load existing settings to get the full current state, including secret_key and available_themes
        current_settings = load_settings() # This will re-scan themes as well
        print("Current settings (pre-update, incl. scanned themes):", current_settings)

        if 'api_address' in submitted_settings_data:
             current_settings['api_address'] = str(submitted_settings_data['api_address']).strip()

        if 'api_key' in submitted_settings_data:
             submitted_key = str(submitted_settings_data['api_key']).strip()
             if submitted_key:
                  current_settings['api_key'] = submitted_key

        if 'rule_interval_seconds' in submitted_settings_data:
             try:
                  interval = max(0, int(submitted_settings_data.get('rule_interval_seconds', current_settings.get('rule_interval_seconds', 0))))
                  current_settings['rule_interval_seconds'] = interval
             except (ValueError, TypeError):
                  print(f"Warning: Invalid value for rule_interval_seconds. Keeping old value or default.")

        if 'last_viewed_threshold_seconds' in submitted_settings_data:
              try:
                  threshold = max(0, int(submitted_settings_data.get('last_viewed_threshold_seconds', current_settings.get('last_viewed_threshold_seconds', 3600))))
                  current_settings['last_viewed_threshold_seconds'] = threshold
              except (ValueError, TypeError):
                  print(f"Warning: Invalid value for last_viewed_threshold_seconds. Keeping old value or default.")

        submitted_show_notifications = submitted_settings_data.get('show_run_notifications')
        current_settings['show_run_notifications'] = (submitted_show_notifications is not None)
        print("Updating show_run_notifications to:", current_settings['show_run_notifications'])

        submitted_show_all_notifications = submitted_settings_data.get('show_run_all_notifications')
        current_settings['show_run_all_notifications'] = (submitted_show_all_notifications is not None)
        print("Updating show_run_all_notifications to:", current_settings['show_run_all_notifications'])

        submitted_theme = submitted_settings_data.get('theme')
        if submitted_theme:
            scanned_available_themes = current_settings.get('available_themes', ['default'])
            if submitted_theme in scanned_available_themes:
                current_settings['theme'] = submitted_theme
                print(f"Updating theme to: {submitted_theme}")
            else:
                print(f"Warning: Submitted theme '{submitted_theme}' is not in the list of available themes {scanned_available_themes}. Keeping current theme '{current_settings['theme']}'.")
        else:
            print(f"No theme submitted. Keeping current theme '{current_settings['theme']}'.")

        submitted_butler_name = submitted_settings_data.get('butler_name')
        if submitted_butler_name and isinstance(submitted_butler_name, str):
            clean_butler_name = submitted_butler_name.strip()
            if clean_butler_name: # Ensure it's not empty after stripping
                current_settings['butler_name'] = clean_butler_name
                print(f"Updating butler_name to: '{clean_butler_name}'")
            else:
                # If submitted name is empty after strip, revert to default from loaded settings
                # (load_settings ensures there's always a valid default 'butler_name')
                default_butler_name_from_load = load_settings().get('butler_name', 'Hydrus Butler') # Re-fetch default if needed
                current_settings['butler_name'] = default_butler_name_from_load
                print(f"Warning: Submitted butler_name was empty. Reverting to default: '{default_butler_name_from_load}'.")
        elif 'butler_name' in submitted_settings_data and not submitted_butler_name: # Explicitly submitted as empty
            default_butler_name_from_load = load_settings().get('butler_name', 'Hydrus Butler')
            current_settings['butler_name'] = default_butler_name_from_load
            print(f"Warning: Submitted butler_name was empty. Reverting to default: '{default_butler_name_from_load}'.")
        # If 'butler_name' is not in submitted_settings_data, current_settings['butler_name'] from load_settings() is kept.


        print("Settings to save to file (incl. theme, available_themes, and new notification setting):", current_settings)
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(current_settings, f, indent=4)
        print(f"Settings successfully written to file: {SETTINGS_FILE}")

        app.config['HYDRUS_SETTINGS'] = current_settings
        print("App config HYDRUS_SETTINGS updated.")

        schedule_rules_job()

        print("Settings successfully saved to file and app config.")
        print("--- Finished saving settings ---")
        return True

    except IOError as e:
        print(f"Error saving settings to {SETTINGS_FILE}: {e}")
        print("--- Finished saving settings with IOError ---")
        return False
    except Exception as e:
         print(f"An unexpected error occurred during save_settings: {e}")
         import traceback
         traceback.print_exc()
         print("--- Finished saving settings with unexpected error ---")
         return False

# --- Rules Functions ---
def load_rules():
    """Loads rules from file, ensures it's a list."""
    if os.path.exists(RULES_FILE):
        try:
            with open(RULES_FILE, 'r') as f:
                rules = json.load(f)
                # Ensure rules is a list
                if not isinstance(rules, list):
                    print(f"Warning: Rules file {RULES_FILE} contains non-list data. Returning empty list.")
                    return []
                # Rules are sorted on save and retrieval via endpoint, no need to sort on every load
                return rules
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading rules from {RULES_FILE}: {e}")
            return [] # Return empty list on error
    return [] # Return empty list if file doesn't exist

def save_rules(rules_data):
    """Saves rules to file, sorting by priority."""
    try:
        # Sort rules by priority before saving for consistency
        # Ensure priority is treated as an integer, defaulting to 0 if missing/invalid
        sorted_rules = sorted(rules_data, key=lambda rule: int(rule.get('priority', 0) or 0))
        with open(RULES_FILE, 'w') as f:
            json.dump(sorted_rules, f, indent=4)
        # Update app config immediately with sorted rules
        app.config['AUTOMATION_RULES'] = sorted_rules
        print(f"Saved {len(sorted_rules)} rules to file and updated app config.")
        return True
    except IOError as e:
        print(f"Error saving rules to {RULES_FILE}: {e}")
        return False

# Load settings and rules when the app starts
app.config['HYDRUS_SETTINGS'] = load_settings()
app.config['AUTOMATION_RULES'] = load_rules()
app.config['AVAILABLE_SERVICES'] = []


# --- Hydrus API Interaction Helper ---
hydrus_api_session = requests.Session()

def call_hydrus_api(endpoint, method='GET', params=None, json_data=None, timeout=60):
    """Helper to make API calls to the Hydrus client, using a session."""
    global hydrus_api_session # Use the global session object
    settings = app.config.get('HYDRUS_SETTINGS', {}) 
    api_address = settings.get('api_address')
    api_key = settings.get('api_key')

    if not api_address:
        print("Hydrus API address is not configured.")
        return {"success": False, "message": "Hydrus API address is not configured. Please set it in the settings page."}, 400

    if not api_address.lower().startswith('http://') and not api_address.lower().startswith('https://'):
         api_address = f'http://{api_address}'

    url = f"{api_address}{endpoint}"
    headers = {
        'Hydrus-Client-API-Access-Key': api_key if api_key else ""
    }
    if json_data is not None:
        headers['Content-Type'] = 'application/json'

    try:
        # Use the session object for the request
        response = hydrus_api_session.request(
            method, 
            url, 
            headers=headers, 
            params=params if method == 'GET' else None, 
            json=json_data if method == 'POST' else None, 
            timeout=timeout
        )
        response.raise_for_status()
        try:
            if response.content and 'application/json' in response.headers.get('Content-Type', '').lower():
                 data = response.json()
                 return {"success": True, "data": data}, response.status_code
            else:
                 if response.status_code >= 200 and response.status_code < 300:
                    return {"success": True, "message": f"Request successful (status {response.status_code}), but no JSON content or non-JSON content received ({response.headers.get('Content-Type', 'Unknown')}). Response text: {response.text[:200]}"}, response.status_code
                 else: 
                    return {"success": False, "message": f"Request to {endpoint} returned status {response.status_code} with non-JSON content. Raw: {response.text[:200]}"}, response.status_code
        except json.JSONDecodeError:
            print(f"API call successful, but response is not valid JSON status: {response.status_code} for {endpoint}")
            print(f"Response text: {response.text}")
            print(f"Warning: Endpoint {endpoint} returned status {response.status_code} with non-JSON or invalid JSON content.")
            return {"success": False, "message": f"Request successful, but response was not valid JSON for endpoint {endpoint}.", "raw_response": response.text}, 500
    except requests.exceptions.ConnectionError as e:
        error_message_str = f"Could not connect to Hydrus client at {api_address}. Is it running? Error: {str(e)}"
        console_error_message = error_message_str.encode(sys.stdout.encoding if sys.stdout.encoding else 'utf-8', 'replace').decode(sys.stdout.encoding if sys.stdout.encoding else 'utf-8', 'replace')
        print(f"ConnectionError calling Hydrus API endpoint {endpoint}: {console_error_message}")
        return {"success": False, "message": error_message_str}, 503 
    except requests.exceptions.Timeout as e:
        error_message_str = f"Request to Hydrus client timed out for endpoint {endpoint}. Error: {str(e)}"
        console_error_message = error_message_str.encode(sys.stdout.encoding if sys.stdout.encoding else 'utf-8', 'replace').decode(sys.stdout.encoding if sys.stdout.encoding else 'utf-8', 'replace')
        print(f"Timeout calling Hydrus API endpoint {endpoint}: {console_error_message}")
        return {"success": False, "message": error_message_str}, 504 
    except requests.exceptions.RequestException as e:
        error_message_str = str(e) 
        status_code = 500 
        response_text_safe = "N/A"
        if e.response is not None:
             status_code = e.response.status_code
             try:
                 response_text_safe = e.response.text.encode('utf-8', 'replace').decode('utf-8', 'replace')
                 if 'application/json' in e.response.headers.get('Content-Type', '').lower():
                     error_details = e.response.json()
                     if 'message' in error_details: error_message_str = f"{status_code}: {error_details['message']}"
                     elif 'error' in error_details: error_message_str = f"{status_code}: {error_details['error']}"
                     else: error_message_str = f"{status_code}: Unexpected error JSON format from API. Raw: {response_text_safe[:200]}"
                 else:
                     error_message_str = f"{status_code}: {response_text_safe.strip()[:500]}" 
             except json.JSONDecodeError:
                  error_message_str = f"{status_code}: Failed to parse error response JSON - {response_text_safe.strip()[:200]}"
             except Exception as json_e:
                  error_message_str = f"{status_code}: Error processing error response ({json_e}) - {response_text_safe.strip()[:200]}"
        else: 
             error_message_str = f"Hydrus API request failed for {endpoint}: {str(e)}"
             status_code = 503 
        console_error_message = error_message_str.encode(sys.stdout.encoding if sys.stdout.encoding else 'utf-8', 'replace').decode(sys.stdout.encoding if sys.stdout.encoding else 'utf-8', 'replace')
        print(f"Error calling Hydrus API endpoint {endpoint}: {console_error_message}")
        return {"success": False, "message": f"Hydrus API Error: {error_message_str}"}, status_code

def init_conflict_db():
    """Initializes the conflict overrides database and table if they don't exist."""
    print("--- Initializing Conflict Overrides Database ---")
    conn = None # Ensure conn is defined for the finally block
    try:
        if not os.path.exists(DB_DIR):
            os.makedirs(DB_DIR)
            print(f"Created database directory: {DB_DIR}")

        conn = sqlite3.connect(CONFLICT_DB_FILE)
        cursor = conn.cursor()
        
        # Rely on modern SQLite's handling of NULLs in composite PRIMARY KEYs.
        # (file_hash, action_type, action_key) must be unique.
        # For 'placement', action_key will be NULL.
        # For 'rating', action_key will be the rating_service_key.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS overrides (
                file_hash TEXT NOT NULL,
                action_type TEXT NOT NULL,    -- "placement", "rating"
                action_key TEXT,              -- NULL for "placement", rating_service_key for "rating"
                winning_rule_id TEXT NOT NULL,
                winning_rule_priority INTEGER NOT NULL,
                rating_value_set TEXT,        -- Store rating value as JSON string (None, bool, int)
                timestamp TEXT NOT NULL,      -- ISO 8601 format
                PRIMARY KEY (file_hash, action_type, action_key)
            )
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_overrides_winning_rule_id 
            ON overrides (winning_rule_id)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_overrides_file_hash_action
            ON overrides (file_hash, action_type, action_key) 
            -- This index helps lookup specific overrides quickly
        ''')
        conn.commit()
        print(f"Conflict overrides database initialized at {CONFLICT_DB_FILE}")
    except sqlite3.Error as e:
        print(f"CRITICAL ERROR initializing conflict overrides database: {e}")
        raise 
    except OSError as e:
        print(f"CRITICAL ERROR creating database directory {DB_DIR}: {e}")
        raise 
    finally:
        if conn:
            conn.close()

def get_db_connection(db_file=CONFLICT_DB_FILE):
    """Establishes and returns a database connection."""
    try:
        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row # Access columns by name
        return conn
    except sqlite3.Error as e:
        print(f"Error connecting to database {db_file}: {e}")
        # Depending on context, might want to raise or return None
        raise
        

def get_conflict_override(db_conn, file_hash, action_type, action_key=None):
    """
    Fetches a specific conflict override from the database.

    Args:
        db_conn: Active SQLite database connection.
        file_hash (str): The file hash.
        action_type (str): "placement" or "rating".
        action_key (str, optional): The rating_service_key if action_type is "rating".
                                    Should be None if action_type is "placement".

    Returns:
        dict: A dictionary representing the override row if found, else None.
              The 'rating_value_set' will be deserialized from JSON.
    """
    # print(f"DB_GET: hash={file_hash}, type={action_type}, key={action_key}") # Debug
    try:
        cursor = db_conn.cursor()
        # Use parameter binding to prevent SQL injection
        if action_key is None: # Specifically for placement or when action_key IS NULL
            cursor.execute('''
                SELECT * FROM overrides
                WHERE file_hash = ? AND action_type = ? AND action_key IS NULL
            ''', (file_hash, action_type))
        else: # For ratings where action_key is the service_key
            cursor.execute('''
                SELECT * FROM overrides
                WHERE file_hash = ? AND action_type = ? AND action_key = ?
            ''', (file_hash, action_type, action_key))
        
        row = cursor.fetchone()
        if row:
            override_dict = dict(row)
            # Deserialize rating_value_set if it's present and action_type is 'rating'
            if override_dict['action_type'] == 'rating' and override_dict['rating_value_set'] is not None:
                try:
                    override_dict['rating_value_set'] = json.loads(override_dict['rating_value_set'])
                except json.JSONDecodeError:
                    print(f"Warning: Could not decode rating_value_set for {file_hash}, {action_key}. Raw: {override_dict['rating_value_set']}")
                    # Keep it as raw string or set to a specific error indicator if preferred
            return override_dict
        return None
    except sqlite3.Error as e:
        print(f"Database error in get_conflict_override for {file_hash}, {action_type}, {action_key}: {e}")
        # Depending on desired error handling, could raise e, or return a specific error indicator
        return None # Or raise

def set_conflict_override(db_conn, file_hash, action_type, action_key,
                          winning_rule_id, winning_rule_priority,
                          rating_value_to_set=None, timestamp_dt=None):
    """
    Sets (inserts or replaces) a conflict override in the database.

    Args:
        db_conn: Active SQLite database connection.
        file_hash (str): The file hash.
        action_type (str): "placement" or "rating".
        action_key (str or None): The rating_service_key if action_type is "rating".
                                  Should be None if action_type is "placement".
        winning_rule_id (str): ID of the rule that won the conflict.
        winning_rule_priority (int): Priority of the winning rule.
        rating_value_to_set (any, optional): The actual value set by the rating rule (None, bool, int).
                                            Only used if action_type is "rating".
        timestamp_dt (datetime, optional): The datetime object for the timestamp. Defaults to datetime.now().
    Returns:
        bool: True if successful, False otherwise.
    """
    # print(f"DB_SET: hash={file_hash}, type={action_type}, key={action_key}, rule={winning_rule_id}, prio={winning_rule_priority}, val={rating_value_to_set}") # Debug
    current_timestamp_iso = (timestamp_dt or datetime.utcnow()).isoformat() + "Z"
    
    # Serialize rating_value_set to JSON string if action_type is 'rating'
    rating_value_json = None
    if action_type == 'rating':
        try:
            rating_value_json = json.dumps(rating_value_to_set)
        except TypeError as e:
            print(f"Error serializing rating_value_set '{rating_value_to_set}' to JSON: {e}")
            return False # Cannot store if cannot serialize

    try:
        cursor = db_conn.cursor()
        # Using INSERT OR REPLACE (UPSERT) based on the PRIMARY KEY
        # The primary key is (file_hash, action_type, COALESCE(action_key, '__PLACEMENT_ACTION_KEY__'))
        # So, action_key here should be the actual key or None.
        # The COALESCE in the table definition handles the NULL for the PK constraint.
        cursor.execute('''
            INSERT OR REPLACE INTO overrides 
            (file_hash, action_type, action_key, winning_rule_id, winning_rule_priority, rating_value_set, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (file_hash, action_type, action_key, winning_rule_id, winning_rule_priority, rating_value_json, current_timestamp_iso))
        # db_conn.commit() # Commit should be handled by the calling function (e.g., at the end of run_all_rules_scheduled)
        return True
    except sqlite3.Error as e:
        print(f"Database error in set_conflict_override for {file_hash}, {action_type}, {action_key}: {e}")
        return False

def remove_overrides_for_rule(db_conn, rule_id):
    """
    Removes all conflict overrides established by a specific rule_id.
    This is typically called when a rule is modified or deleted.

    Args:
        db_conn: Active SQLite database connection.
        rule_id (str): The ID of the rule whose overrides should be removed.

    Returns:
        int: The number of rows deleted, or -1 if an error occurred.
    """
    # print(f"DB_REMOVE_RULE_OVERRIDES: rule_id={rule_id}") # Debug
    try:
        cursor = db_conn.cursor()
        cursor.execute('''
            DELETE FROM overrides
            WHERE winning_rule_id = ?
        ''', (rule_id,))
        # db_conn.commit() # Commit should be handled by the calling function
        deleted_rows = cursor.rowcount
        # print(f"DB_REMOVE_RULE_OVERRIDES: Deleted {deleted_rows} overrides for rule_id {rule_id}") # Debug
        return deleted_rows
    except sqlite3.Error as e:
        print(f"Database error in remove_overrides_for_rule for rule_id {rule_id}: {e}")
        return -1 # Indicate error

def remove_specific_override(db_conn, file_hash, action_type, action_key=None):
    """
    Removes a single, specific conflict override from the database.
    This might be used if a rule explicitly "loses" a conflict and its previous
    override entry needs to be cleared rather than just replaced by a new winner
    (though INSERT OR REPLACE in set_conflict_override usually handles this).
    More likely useful if a condition that previously caused an override is no longer met.

    Args:
        db_conn: Active SQLite database connection.
        file_hash (str): The file hash.
        action_type (str): "placement" or "rating".
        action_key (str, optional): The rating_service_key if action_type is "rating".
                                    Should be None for "placement".

    Returns:
        int: The number of rows deleted (0 or 1), or -1 if an error occurred.
    """
    # print(f"DB_REMOVE_SPECIFIC_OVERRIDE: hash={file_hash}, type={action_type}, key={action_key}") # Debug
    try:
        cursor = db_conn.cursor()
        if action_key is None: # For placement or when action_key IS NULL
            cursor.execute('''
                DELETE FROM overrides
                WHERE file_hash = ? AND action_type = ? AND action_key IS NULL
            ''', (file_hash, action_type))
        else: # For ratings where action_key is the service_key
            cursor.execute('''
                DELETE FROM overrides
                WHERE file_hash = ? AND action_type = ? AND action_key = ?
            ''', (file_hash, action_type, action_key))
        # db_conn.commit() # Commit should be handled by the calling function
        deleted_rows = cursor.rowcount
        # print(f"DB_REMOVE_SPECIFIC_OVERRIDE: Deleted {deleted_rows} specific override for {file_hash}, {action_type}, {action_key}") # Debug
        return deleted_rows
    except sqlite3.Error as e:
        print(f"Database error in remove_specific_override for {file_hash}, {action_type}, {action_key}: {e}")
        return -1 # Indicate error 

def _ensure_available_services(rule_name_for_log):
    """
    Ensures that the list of available Hydrus services is loaded and cached.
    Tries to fetch from API if the cache is empty or invalid.
    Returns the list of available services, or an empty list if fetching/parsing fails.
    """
    available_services_cache = app.config.get('AVAILABLE_SERVICES')
    
    # Check if cache exists, is a list, and is not empty.
    # If services were successfully fetched at startup, this cache should be populated.
    # If startup fetch failed, cache would be an empty list.
    if isinstance(available_services_cache, list) and available_services_cache: # Only return non-empty cache
        # print(f"Rule '{rule_name_for_log}': Using cached available services ({len(available_services_cache)} services).") # Optional: for verbose logging
        return available_services_cache

    # If cache is empty or not a list, try to fetch.
    # This path will also be taken if the initial startup fetch failed.
    log_prefix = f"Rule '{rule_name_for_log}'" if rule_name_for_log else "EnsureServices"
    print(f"{log_prefix}: Available services cache empty, invalid, or not populated. Attempting to fetch.")
    
    # Check if API address is even configured before attempting a call
    settings = app.config.get('HYDRUS_SETTINGS', {})
    if not settings.get('api_address'):
        print(f"{log_prefix}: Hydrus API address not configured. Cannot fetch services. Returning empty list.")
        app.config['AVAILABLE_SERVICES'] = [] # Ensure cache is an empty list
        return [] # Return empty list, not None

    services_endpoint_result, services_endpoint_status = call_hydrus_api('/get_services')
    
    if services_endpoint_result.get("success"):
        services_data = services_endpoint_result.get('data')
        if isinstance(services_data, dict):
            services_object = services_data.get('services')
            if isinstance(services_object, dict):
                services_list = []
                for key, service_details in services_object.items():
                    if isinstance(service_details, dict):
                        services_list.append({
                            'service_key': key, 
                            'name': service_details.get('name', 'Unnamed Service'),
                            'type': service_details.get('type'), 
                            'type_pretty': service_details.get('type_pretty', 'Unknown Type'),
                            'star_shape': service_details.get('star_shape'), 
                            'min_stars': service_details.get('min_stars'),
                            'max_stars': service_details.get('max_stars'),
                        })
                    else:
                        # Use service_details.get('name', 'N/A') cautiously if service_details is not a dict
                        service_name_for_log = "N/A"
                        if isinstance(service_details, dict) and 'name' in service_details:
                            service_name_for_log = service_details['name']
                        elif isinstance(service_details, str): # Handle if it's just a string
                             service_name_for_log = service_details[:50] # Log part of it
                        print(f"{log_prefix}: Warning - service details for key '{key}' (Name: {service_name_for_log}) is not a dict. Skipping.")
                
                app.config['AVAILABLE_SERVICES'] = services_list
                print(f"{log_prefix}: Fetched and cached {len(services_list)} services.")
                return services_list
            else: 
                error_msg = f"{log_prefix} failed: Could not parse service list from Hydrus API ('services' object not a dict or missing in data). Data received: {str(services_data)[:500]}"
                print(error_msg)
                app.config['AVAILABLE_SERVICES'] = [] 
                return [] # Return empty list, not None
        else: 
            error_msg = f"{log_prefix} failed: Hydrus API /get_services returned success but 'data' field is not a dictionary or missing. Result: {str(services_endpoint_result)[:500]}"
            print(error_msg)
            app.config['AVAILABLE_SERVICES'] = []
            return [] # Return empty list, not None
    else: # API call itself failed (e.g., connection error, Hydrus down)
        error_msg = f"{log_prefix} failed: Could not load service list. API call to /get_services failed: {services_endpoint_result.get('message', 'Unknown API error')}"
        print(error_msg)
        app.config['AVAILABLE_SERVICES'] = [] 
        return [] # Return empty list, not None

def _fetch_metadata_for_hashes(rule_name_for_log, hashes_list, batch_size=256):
    """
    Fetches metadata for a list of file hashes in batches.

    Args:
        rule_name_for_log (str): The name of the rule, for logging.
        hashes_list (list): A list of file hashes.
        batch_size (int): The number of hashes to include in each API call.

    Returns:
        tuple: (list_of_metadata_objects, list_of_metadata_errors)
               metadata_objects can be empty if all fetches fail or no hashes.
               metadata_errors contains dicts with error details for failed batches.
    """
    all_files_metadata = []
    metadata_errors_list = []
    num_hashes_to_fetch = len(hashes_list)

    if num_hashes_to_fetch == 0:
        return [], []

    print(f"Rule '{rule_name_for_log}': Fetching metadata for {num_hashes_to_fetch} files in batches of {batch_size}...")

    for i in range(0, num_hashes_to_fetch, batch_size):
        batch_hashes = hashes_list[i : i + batch_size]
        # batch_num = int(i/batch_size) + 1 # For logging if needed
        # total_batches = math.ceil(num_hashes_to_fetch/batch_size) # For logging if needed

        metadata_params = {
            'hashes': json.dumps(batch_hashes),
            'include_services_object': json.dumps(True) # Crucial for 'force_in'
        }
        
        metadata_result, metadata_status = call_hydrus_api('/get_files/file_metadata', method='GET', params=metadata_params)
        
        if metadata_result.get("success") and isinstance(metadata_result.get('data'), dict):
            batch_metadata = metadata_result.get('data', {}).get('metadata', [])
            all_files_metadata.extend(batch_metadata)
        else:
            error_msg = f"Metadata fetch failed for a batch: {metadata_result.get('message', 'Unknown API error')}"
            print(f"Rule '{rule_name_for_log}': {error_msg}")
            metadata_errors_list.append({
                "message": error_msg, 
                "hashes_in_batch": batch_hashes, # Log which hashes were in the failed batch
                "status_code": metadata_status # Log status code if available
            })
            
    num_metadata_retrieved = len(all_files_metadata)
    print(f"Rule '{rule_name_for_log}': Metadata fetch complete. Retrieved for {num_metadata_retrieved} of {num_hashes_to_fetch} files.")
    if metadata_errors_list:
        print(f"Rule '{rule_name_for_log}': Metadata fetch errors encountered: {len(metadata_errors_list)}")

    return all_files_metadata, metadata_errors_list
    
def _translate_rule_to_hydrus_predicates(rule_conditions_list, rule_action_obj, last_viewed_threshold_seconds, available_services_list, rule_name_for_log):
    """
    Translates a rule's conditions list into Hydrus API search predicates.
    Includes logic to parse 'paste_search' text into predicate structure.
    Also adds exclusion/inclusion predicates based on the rule's action to ensure
    only files that *need* the action are processed.
    Adheres more strictly to the provided Hydrus predicate syntax list, including image confirmations.

    Returns:
        tuple: (string_predicates, translation_warnings, action_tag_service_key_for_search)
               string_predicates (list): The list of predicates for the 'tags' API parameter.
               translation_warnings (list): Any warnings generated during translation.
               action_tag_service_key_for_search (str|None): The service key to be used for the
                                                             'tag_service_key' API parameter if the
                                                             action is 'add_tags' or 'remove_tags'.
                                                             Otherwise, None.
    """
    string_predicates = []
    translation_warnings = []
    action_tag_service_key_for_search = None # Initialize

    # --- Helper to get service details by key ---
    def get_service_details(service_key):
        if not isinstance(available_services_list, list):
            non_list_warning = f"Rule '{rule_name_for_log}': Critical - available_services_list not a list. Type: {type(available_services_list)}"
            print(non_list_warning)
            # translation_warnings.append(non_list_warning) # Avoid modifying list from nested scope directly if not passed
            return None
        return next((s for s in available_services_list if isinstance(s, dict) and s.get('service_key') == service_key), None)

    # --- Inner Helper function to translate a single structured condition ---
    def translate_single_condition_inner(condition, warnings_list_ref):
        condition_type = condition.get('type')
        url_subtype = condition.get('url_subtype')
        specific_url_type = condition.get('specific_type')
        operator = condition.get('operator')
        value = condition.get('value')
        condition_service_key = condition.get('service_key')
        unit = condition.get('unit')

        predicate_string = None
        warning_msg = None

        try:
            if condition_type == 'tags' and operator == 'search_terms' and isinstance(value, list):
                if value:
                    # For general 'tags' conditions from the UI, these are direct search terms.
                    # They might include user-typed "tag@@service" or just "tag".
                    # This part is for user-defined *search conditions*, not action-based exclusions.
                    return value
                else:
                    warning_msg = f"Warning: Empty tags list in condition. Skipping."

            elif condition_type == 'rating' and condition_service_key and operator:
                service_info = get_service_details(condition_service_key)
                if not service_info:
                    warning_msg = f"Warning: Rating service with key {condition_service_key} not found. Skipping condition."
                else:
                    service_name = service_info['name']
                    service_type = service_info.get('type')
                    max_stars = service_info.get('max_stars')

                    if operator == 'no_rating' and value is None:
                        predicate_string = f"system:no rating for {service_name}"
                    elif operator == 'has_rating' and value is None:
                        predicate_string = f"system:has a rating for {service_name}"
                    elif service_type == 7:
                        predicate_base_for_rating = f"system:rating for {service_name}"
                        if operator == 'is':
                            if isinstance(value, bool):
                                keyword = 'like' if value is True else 'dislike'
                                predicate_string = f"{predicate_base_for_rating} is {keyword}"
                            else:
                                warning_msg = f"Warning: Unsupported value type '{type(value).__name__}' for 'is' on like/dislike rating. Expected boolean."
                        else:
                            warning_msg = f"Warning: Unsupported operator '{operator}' for like/dislike rating (excluding 'no_rating', 'has_rating')."
                    elif service_type == 6:
                        predicate_base_for_rating = f"system:rating for {service_name}"
                        if isinstance(value, (int, float)):
                            numeric_value = int(value)
                            if operator == 'is':
                                predicate_string = f"{predicate_base_for_rating} = {numeric_value}"
                                if max_stars is not None and max_stars > 0: predicate_string += f"/{max_stars}"
                                else: warnings_list_ref.append(f"Note: 'is {numeric_value}' for numerical rating '{service_name}' without max_stars. Standard numerical equality assumed.")
                            elif operator == 'more_than':
                                predicate_string = f"{predicate_base_for_rating} > {numeric_value}"
                                if max_stars is not None and max_stars > 0: predicate_string += f"/{max_stars}"
                            elif operator == 'less_than':
                                predicate_string = f"{predicate_base_for_rating} < {numeric_value}"
                                if max_stars is not None and max_stars > 0: predicate_string += f"/{max_stars}"
                            elif operator == '!=':
                                predicate_string = f"{predicate_base_for_rating} != {numeric_value}"
                                if max_stars is not None and max_stars > 0: predicate_string += f"/{max_stars}"
                                warnings_list_ref.append(f"Note: '!=' for numerical rating. Hydrus might use '<>' or require OR group. Verify.")
                            else:
                                warning_msg = f"Unsupported operator '{operator}' for numerical rating."
                        else:
                            warning_msg = f"Invalid value '{value}' for numerical rating. Expected number."
                    elif service_type == 22:
                        predicate_base_for_rating = f"system:rating for {service_name}"
                        if isinstance(value, (int, float)):
                            numeric_value = int(value)
                            if operator == 'is': predicate_string = f"{predicate_base_for_rating} = {numeric_value}"
                            elif operator == 'more_than': predicate_string = f"{predicate_base_for_rating} > {numeric_value}"
                            elif operator == 'less_than': predicate_string = f"{predicate_base_for_rating} < {numeric_value}"
                            elif operator == '!=': predicate_string = f"{predicate_base_for_rating} != {numeric_value}"
                            else: warning_msg = f"Unsupported operator '{operator}' for inc/dec rating."
                        else: warning_msg = f"Invalid value '{value}' for inc/dec rating. Expected number."
                    elif operator not in ['no_rating', 'has_rating']:
                         warning_msg = f"Unsupported rating service type ({service_type}) for '{service_name}' with operator '{operator}'."

            elif condition_type == 'file_service' and condition_service_key and operator in ['is_in', 'is_not_in']:
                service_info = get_service_details(condition_service_key)
                if not service_info:
                     warning_msg = f"Warning: File service key {condition_service_key} not found. Skipping."
                else:
                    service_name_for_predicate = service_info['name'] # Use the service name
                    if operator == 'is_in':
                        predicate_string = f"system:file service currently in {service_name_for_predicate}"
                    else: # is_not_in
                        predicate_string = f"system:file service is not currently in {service_name_for_predicate}"

            elif condition_type == 'filesize' and operator and value is not None and unit:
                 hydrus_operator_map = { '=': '~=', '>': '>', '<': '<', '!=': '≠' }
                 hydrus_op = hydrus_operator_map.get(operator)
                 if not hydrus_op:
                     warning_msg = f"Warning: Unsupported filesize operator '{operator}'. Using direct symbol."
                     hydrus_op = operator
                 hydrus_unit_map = { 'bytes': 'B', 'KB': 'kilobytes', 'MB': 'megabytes', 'GB': 'GB'}
                 hydrus_unit_str = hydrus_unit_map.get(unit)
                 if not hydrus_unit_str:
                     warning_msg = f"Warning: Invalid filesize unit '{unit}'. Skipping."
                 else:
                    try:
                        size_val = float(value)
                        # Ensure size_val is int if it's a whole number, otherwise keep as float for potential fuzzy matching if Hydrus supports it elsewhere
                        formatted_size_val = int(size_val) if size_val == int(size_val) else size_val
                        predicate_string = f"system:filesize {hydrus_op} {formatted_size_val} {hydrus_unit_str}"
                        if operator == '!=':
                             warnings_list_ref.append(f"Note: Filesize '!=' translated to Hydrus '≠'.")
                    except (ValueError, TypeError) as e:
                        warning_msg = f"Warning: Invalid filesize value '{value}': {e}. Skipping."

            elif condition_type == 'boolean' and operator and isinstance(value, bool):
                positive_forms = {
                    'inbox': 'system:inbox', 'archive': 'system:archive',
                    'has_duration': 'system:has duration',
                    'is_the_best_quality_file_of_its_duplicate_group': 'system:is the best quality file of its duplicate group',
                    'has_audio': 'system:has audio', 'has_exif': 'system:has exif',
                    'has_embedded_metadata': 'system:has embedded metadata',
                    'has_icc_profile': 'system:has icc profile',
                    'has_tags': 'system:has tags',
                    'has_notes': 'system:has notes'
                }
                negative_forms = {
                    'inbox': '-system:inbox',
                    'archive': '-system:archive',
                    'has_duration': 'system:no duration',
                    'is_the_best_quality_file_of_its_duplicate_group': 'system:is not the best quality file of its duplicate group',
                    'has_audio': 'system:no audio', 'has_exif': 'system:no exif',
                    'has_embedded_metadata': 'system:no embedded metadata',
                    'has_icc_profile': 'system:no icc profile',
                    'has_tags': 'system:no tags',
                    'has_notes': 'system:no notes',
                }
                if value is True:
                    if operator in positive_forms:
                        predicate_string = positive_forms[operator]
                    else:
                        warning_msg = f"Warning: Boolean operator '{operator}' (for TRUE) has no direct positive mapping to Hydrus syntax. Skipping."
                else:
                    if operator in negative_forms:
                        predicate_string = negative_forms[operator]
                        if operator == 'has_tags' and predicate_string == 'system:no tags':
                            warnings_list_ref.append("Note: 'has_tags is false' mapped to 'system:no tags'. 'system:untagged' is also an option from Hydrus list (no tags from 'my tags' services).")
                        if operator == 'has_notes' and predicate_string == 'system:no notes':
                             warnings_list_ref.append("Note: 'has_notes is false' mapped to 'system:no notes'. Hydrus list also has 'system:does not have notes'.")
                    elif operator in positive_forms:
                        predicate_string = f"-{positive_forms[operator]}"
                        warnings_list_ref.append(f"Note: Boolean operator '{operator}' (for FALSE) was negated generically as '{predicate_string}'. Verify if a more specific negative form (like 'system:no ...') is preferred from Hydrus list.")
                    else:
                        warning_msg = f"Warning: Boolean operator '{operator}' (for FALSE) has no mapping to Hydrus syntax. Skipping."
            elif condition_type == 'boolean' and operator and not isinstance(value, bool):
                warning_msg = f"Warning: Invalid value type '{type(value).__name__}' for boolean condition. Expected boolean."

            elif condition_type == 'filetype' and operator in ['is', 'is_not'] and isinstance(value, list) and value:
                 processed_values = [str(v).strip().lower() for v in value]
                 values_string = ", ".join(processed_values)
                 if operator == 'is':
                     predicate_string = f"system:filetype = {values_string}"
                 elif operator == 'is_not':
                     predicate_string = f"system:filetype is not {values_string}"


            elif condition_type == 'url' and url_subtype:
                url_value_str = str(value).strip() if value is not None else None
                if url_subtype == 'specific' and specific_url_type and operator in ['is', 'is_not'] and url_value_str:
                    negation_prefix = "does not have "
                    if specific_url_type == 'regex' and operator == 'is_not':
                        negation_prefix = "does not have a "
                    positive_verb = "has "
                    verb = positive_verb if operator == 'is' else negation_prefix
                    if specific_url_type == 'url': predicate_string = f"system:{verb}url {url_value_str}"
                    elif specific_url_type == 'domain': predicate_string = f"system:{verb}domain {url_value_str}"
                    elif specific_url_type == 'regex': predicate_string = f"system:{verb}url matching regex {url_value_str}"
                    else: warning_msg = f"Warning: Unknown specific URL type '{specific_url_type}'. Skipping."
                elif url_subtype == 'existence' and operator in ['has', 'has_not'] and value is None:
                    if operator == 'has': predicate_string = "system:has urls"
                    elif operator == 'has_not': predicate_string = "system:no urls"
                elif url_subtype == 'count' and operator and isinstance(value, int):
                    if operator == '=': predicate_string = f"system:number of urls = {value}"
                    elif operator == '>': predicate_string = f"system:number of urls > {value}"
                    elif operator == '<': predicate_string = f"system:number of urls < {value}"
                    elif operator == '!=':
                        predicate_string = [f"system:number of urls < {value}", f"system:number of urls > {value}"]
                        warnings_list_ref.append("Note: URL count '!=' translated to an OR group.")
                    else: warning_msg = f"Warning: Unsupported URL count operator '{operator}'. Skipping."
                else:
                    details_msg = f"Subtype: {url_subtype}, Specific: {specific_url_type}, Op: {operator}, Val: {value}"
                    warning_msg = f"Warning: Incomplete/invalid URL condition. {details_msg}. Skipping."
            elif condition_type == 'paste_search':
                warning_msg = "Dev Error: 'paste_search' in translate_single_condition_inner."
            elif condition_type:
                warning_msg = f"Unhandled condition type '{condition_type}'. Skipping."
            else:
                warning_msg = "Condition has no type. Skipping."
        except Exception as e:
            warning_msg = f"Error translating condition '{str(condition)[:100]}...': {e}. Skipping."
            print(f"Rule '{rule_name_for_log}': {warning_msg}")
            import traceback; traceback.print_exc()
        if warning_msg:
            ws_ref_is_list = isinstance(warnings_list_ref, list)
            if ws_ref_is_list:
                 warnings_list_ref.append(f"Cond (type: {condition.get('type','N/A')}, op: {condition.get('operator','N/A')}): {warning_msg}")
            else:
                 print(f"Rule '{rule_name_for_log}': CRITICAL - warnings_list_ref not list. Msg: {warning_msg}")
        return predicate_string
    # --- End of translate_single_condition_inner ---

    # --- Main Condition Processing Loop ---
    # This loop processes the rule_conditions_list using translate_single_condition_inner.
    # Its logic for OR groups, paste_search, and single conditions is not affected.
    for condition_idx, condition in enumerate(rule_conditions_list):
        if not isinstance(condition, dict):
            translation_warnings.append(f"Cond at idx {condition_idx} not dict. Skip: {condition}")
            continue
        condition_type = condition.get('type')
        if condition_type == 'or_group':
            nested_conditions_data = condition.get('conditions', [])
            if not isinstance(nested_conditions_data, list) or not nested_conditions_data:
                translation_warnings.append(f"OR group at idx {condition_idx} empty or invalid. Skipping.")
                continue
            nested_predicate_list = []
            for nested_cond_idx, nested_cond in enumerate(nested_conditions_data):
                if not isinstance(nested_cond, dict) or nested_cond.get('type') in ['or_group', 'paste_search']:
                    translation_warnings.append(f"Invalid nested item in OR group (idx {condition_idx}, nested_idx {nested_cond_idx}). Skipping nested item.")
                    continue
                nested_res = translate_single_condition_inner(nested_cond, translation_warnings)
                if nested_res:
                    if isinstance(nested_res, list): nested_predicate_list.extend(nested_res)
                    else: nested_predicate_list.append(nested_res)
            if nested_predicate_list: string_predicates.append(nested_predicate_list)
            else: translation_warnings.append(f"OR group idx {condition_idx} yielded no predicates. Skipping.")
        elif condition_type == 'paste_search':
            raw_text = condition.get('value')
            if not isinstance(raw_text, str) or not raw_text.strip():
                translation_warnings.append(f"'paste_search' idx {condition_idx} empty. Skipping.")
                continue
            lines = raw_text.strip().split('\n')
            parsed_paste_preds = []
            for line_num, line in enumerate(lines):
                s_line = line.strip()
                if not s_line or s_line.startswith('#'): continue
                if s_line.lower().startswith('system:limit'):
                    translation_warnings.append(f"Ignored 'system:limit' in paste_search (line {line_num + 1}).")
                    continue
                or_parts = [p.strip() for p in s_line.split(' OR ') if p.strip()]
                if len(or_parts) > 1: parsed_paste_preds.append(or_parts)
                elif or_parts: parsed_paste_preds.append(or_parts[0])
            if parsed_paste_preds: string_predicates.extend(parsed_paste_preds)
            else: translation_warnings.append(f"'paste_search' idx {condition_idx} yielded no predicates. Skipping.")
        else:
            res = translate_single_condition_inner(condition, translation_warnings)
            if res:
                if isinstance(res, list): string_predicates.append(res)
                else: string_predicates.append(res)

    # --- Action-Based Exclusion/Inclusion Predicates ---
    if rule_action_obj and isinstance(rule_action_obj, dict):
        action_type = rule_action_obj.get('type')
        if action_type == 'add_to':
            dest_keys = rule_action_obj.get('destination_service_keys', [])
            if isinstance(dest_keys, str): dest_keys = [dest_keys] if dest_keys else []
            for key in dest_keys:
                if not key: continue
                info = get_service_details(key)
                if info and info.get('name'):
                    service_name_for_predicate = info['name']
                    string_predicates.append(f"system:file service is not currently in {service_name_for_predicate}")
                else:
                    translation_warnings.append(f"Action 'add_to': service key '{key}' not found for exclusion predicate.")

        elif action_type == 'force_in':
            target_dest_keys_set = set()
            raw_dest_keys = rule_action_obj.get('destination_service_keys', [])
            if isinstance(raw_dest_keys, str):
                if raw_dest_keys: target_dest_keys_set.add(raw_dest_keys)
            elif isinstance(raw_dest_keys, list):
                for k in raw_dest_keys:
                    if k: target_dest_keys_set.add(k)

            if not target_dest_keys_set:
                translation_warnings.append(f"Action 'force_in': No valid target destination service keys found. Cannot generate specific search predicates.")
            else:
                other_local_file_services = []
                if isinstance(available_services_list, list):
                    for service in available_services_list:
                        if isinstance(service, dict) and service.get('type') == 2 and \
                           service.get('service_key') and service.get('service_key') not in target_dest_keys_set and \
                           service.get('name'):
                            other_local_file_services.append(service['name'])

                force_in_or_group = []
                if other_local_file_services:
                    for other_s_name in other_local_file_services:
                        force_in_or_group.append(f"system:file service currently in {other_s_name}")

                for target_key in target_dest_keys_set:
                    target_info = get_service_details(target_key)
                    if target_info and target_info.get('name'):
                        force_in_or_group.append(f"system:file service is not currently in {target_info['name']}")
                    else:
                        translation_warnings.append(f"Action 'force_in': Target service key '{target_key}' not found for generating exclusion predicate part.")

                if force_in_or_group:
                    string_predicates.append(force_in_or_group)
                    # translation_warnings.append(f"Note: For 'force_in', search predicates now include an OR group to find files potentially needing placement changes. The action logic remains the ultimate arbiter.") # This warning might be too verbose for every run
                else:
                    translation_warnings.append(f"Action 'force_in': Could not generate any specific OR-group predicates (e.g., no other local services or target services unresolved). Relying fully on action idempotency.")
        
        elif action_type == 'add_tags':
            tag_key_from_action = rule_action_obj.get('tag_service_key')
            tags_to_process = rule_action_obj.get('tags_to_process', [])
            if tag_key_from_action and tags_to_process:
                # Store the service key to be used for the 'tag_service_key' API parameter
                action_tag_service_key_for_search = tag_key_from_action
                for tag_str in tags_to_process:
                    clean_tag = tag_str.strip()
                    if clean_tag:
                        # Predicate for "tags" list: just the negative tag.
                        # The 'tag_service_key' API parameter will scope this.
                        string_predicates.append(f"-{clean_tag}")
                # Add a single warning if specific conditions are met to reduce verbosity.
                if not any("will be searched on service" in w and f"'{tag_key_from_action}'" in w for w in translation_warnings):
                    translation_warnings.append(f"Note: For 'add_tags' action, predicates for tags being added will be evaluated against service key '{tag_key_from_action}' (set via API's 'tag_service_key' parameter).")

            else: # Handle missing parts for add_tags
                if not tag_key_from_action:
                    translation_warnings.append("Action 'add_tags': Rule is missing 'tag_service_key'. Cannot define search domain for tag exclusion predicates.")
                if not tags_to_process:
                    translation_warnings.append("Action 'add_tags': Rule is missing 'tags_to_process'. No tag exclusion predicates generated.")

        elif action_type == 'remove_tags':
            tag_key_from_action = rule_action_obj.get('tag_service_key')
            tags_to_process = rule_action_obj.get('tags_to_process', [])
            if tag_key_from_action and tags_to_process:
                # Store the service key to be used for the 'tag_service_key' API parameter
                action_tag_service_key_for_search = tag_key_from_action
                for tag_str in tags_to_process:
                    clean_tag = tag_str.strip()
                    if clean_tag:
                        # Predicate for "tags" list: just the positive tag.
                        # The 'tag_service_key' API parameter will scope this.
                        string_predicates.append(clean_tag)
                if not any("will be searched on service" in w and f"'{tag_key_from_action}'" in w for w in translation_warnings):
                     translation_warnings.append(f"Note: For 'remove_tags' action, predicates for tags being removed will be evaluated against service key '{tag_key_from_action}' (set via API's 'tag_service_key' parameter).")
            else: # Handle missing parts for remove_tags
                if not tag_key_from_action:
                    translation_warnings.append("Action 'remove_tags': Rule is missing 'tag_service_key'. Cannot define search domain for tag inclusion predicates.")
                if not tags_to_process:
                    translation_warnings.append("Action 'remove_tags': Rule is missing 'tags_to_process'. No tag inclusion predicates generated.")

        elif action_type == 'modify_rating':
            rating_key = rule_action_obj.get('rating_service_key')
            target_val = rule_action_obj.get('rating_value')
            info = get_service_details(rating_key)
            if info and info.get('name'):
                s_name = info['name']; s_type = info['type']; s_max_stars = info.get('max_stars')
                action_exclusion_preds = []
                if target_val is None:
                    action_exclusion_preds.append(f"system:has a rating for {s_name}")
                elif isinstance(target_val, bool):
                    if s_type == 7:
                        other_state_keyword = 'dislike' if target_val is True else 'like'
                        action_exclusion_preds.append(f"system:rating for {s_name} is {other_state_keyword}")
                        action_exclusion_preds.append(f"system:no rating for {s_name}")
                    else: translation_warnings.append(f"Action modify_rating (bool) for non-Like/Dislike service '{s_name}'. No specific exclusion.")
                elif isinstance(target_val, (int, float)):
                    num_target = int(target_val)
                    if s_type == 6:
                        action_exclusion_preds.append(f"system:no rating for {s_name}")
                        action_exclusion_preds.append(f"system:rating for {s_name} < {num_target}" + (f"/{s_max_stars}" if s_max_stars else ""))
                        action_exclusion_preds.append(f"system:rating for {s_name} > {num_target}" + (f"/{s_max_stars}" if s_max_stars else ""))
                    elif s_type == 22:
                        action_exclusion_preds.append(f"system:no rating for {s_name}")
                        action_exclusion_preds.append(f"system:rating for {s_name} < {num_target}")
                        action_exclusion_preds.append(f"system:rating for {s_name} > {num_target}")
                    else: translation_warnings.append(f"Action modify_rating (num) for non-num/incdec service '{s_name}'. No specific exclusion.")
                if action_exclusion_preds:
                    if len(action_exclusion_preds) == 1: string_predicates.append(action_exclusion_preds[0])
                    else: string_predicates.append(action_exclusion_preds)
                elif not any("No specific exclusion" in w for w in translation_warnings if f"'{s_name}'" in w): # Avoid duplicate warnings for same service
                    translation_warnings.append(f"Action modify_rating for '{s_name}' to '{target_val}': Could not form optimal exclusion predicates.")
            elif rating_key: # Only warn if rating_key was provided but not found
                 translation_warnings.append(f"Action modify_rating: service key '{rating_key}' not found for exclusion predicate.")
    
    if not string_predicates:
         if rule_conditions_list or (rule_action_obj and rule_action_obj.get('type') not in ['add_tags', 'remove_tags']): # Adjusted condition slightly
             # If there were conditions, or if it was an action type other than tags (which might legitimately have no string_predicates if only action_tag_service_key is used)
             # and we still have no predicates, it's a potential issue.
             if not (rule_action_obj and rule_action_obj.get('type') in ['add_tags', 'remove_tags'] and action_tag_service_key_for_search):
                translation_warnings.append("Warning: No Hydrus search predicates generated from rule conditions or action exclusions. If enabled, this rule might match all files or no files if only an action tag service key was defined.")
    
    return string_predicates, translation_warnings, action_tag_service_key_for_search

def _batch_api_call_with_retry(endpoint, method, items_to_process, batch_size,
                               batch_payload_formatter, single_item_payload_formatter,
                               rule_name_for_log, action_description,
                               expected_success_status_codes=None,
                               timeout_per_call=120):
    """
    Helper to make batch API calls to Hydrus, with individual retries on batch failure.

    Args:
        endpoint (str): The Hydrus API endpoint.
        method (str): HTTP method (e.g., 'POST').
        items_to_process (list): List of items (e.g., hashes) to process.
        batch_size (int): The number of items per batch.
        batch_payload_formatter (callable): A function that takes a list of items (a batch)
                                            and returns the JSON payload for the API call.
        single_item_payload_formatter (callable): A function that takes a single item
                                                  and returns the JSON payload for a retry API call.
        rule_name_for_log (str): Name of the rule for logging.
        action_description (str): Description of the action for logging (e.g., "migrate files").
        expected_success_status_codes (list, optional): List of HTTP status codes that indicate success.
                                                       Defaults to [200, 204] or common Hydrus success codes.
                                                       If the API returns content, 200 is typical.
                                                       If no content (like migrate/delete), 204 is typical.
                                                       `call_hydrus_api` already handles `raise_for_status`.
                                                       This is more for interpreting non-exception cases.
        timeout_per_call (int): Timeout in seconds for each API call.

    Returns:
        dict: {
            "successful_items": list,  // List of items that were successfully processed
            "failed_items_with_errors": list // List of tuples (item, error_message, status_code)
        }
    """
    if expected_success_status_codes is None:
        # Hydrus often returns 200 OK with no content for these types of actions.
        # call_hydrus_api success=True is the primary check.
        expected_success_status_codes = [200]


    successful_items = []
    failed_items_with_errors = []

    if not items_to_process:
        return {"successful_items": [], "failed_items_with_errors": []}

    print(f"Rule '{rule_name_for_log}': Batch processing {len(items_to_process)} items for '{action_description}' in batches of {batch_size}.")

    for i in range(0, len(items_to_process), batch_size):
        batch_items = items_to_process[i : i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = math.ceil(len(items_to_process) / batch_size)

        if not batch_items:
            continue

        batch_payload = batch_payload_formatter(batch_items)
        # print(f"Rule '{rule_name_for_log}': Batch {batch_num}/{total_batches} - Payload: {json.dumps(batch_payload, indent=2)}") # DEBUG

        batch_result, batch_status = call_hydrus_api(
            endpoint,
            method=method,
            json_data=batch_payload,
            timeout=timeout_per_call
        )

        if batch_result.get("success"): # and batch_status in expected_success_status_codes: <- call_hydrus_api handles this logic
            # Batch successful, all items in this batch are considered successful.
            # print(f"Rule '{rule_name_for_log}': Batch {batch_num}/{total_batches} for '{action_description}' succeeded for {len(batch_items)} items.") # Verbose
            successful_items.extend(batch_items)
        else:
            batch_error_message = batch_result.get('message', f"Unknown API error for batch {batch_num}")
            print(f"Rule '{rule_name_for_log}': Batch {batch_num}/{total_batches} for '{action_description}' failed: {batch_error_message}. Status: {batch_status}. Retrying items individually...")

            for item_idx, single_item in enumerate(batch_items):
                item_num_in_batch = item_idx + 1
                single_item_payload = single_item_payload_formatter(single_item)
                # print(f"Rule '{rule_name_for_log}': Batch {batch_num} (Retry {item_num_in_batch}/{len(batch_items)}) - Single Payload: {json.dumps(single_item_payload, indent=2)}") # DEBUG

                retry_result, retry_status = call_hydrus_api(
                    endpoint,
                    method=method,
                    json_data=single_item_payload,
                    timeout=timeout_per_call
                )

                if retry_result.get("success"): # and retry_status in expected_success_status_codes:
                    # print(f"Rule '{rule_name_for_log}': Retry for item '{str(single_item)[:50]}' (batch {batch_num}) succeeded.") # Verbose
                    successful_items.append(single_item)
                else:
                    retry_error_message = retry_result.get('message', f"Unknown API error for item {str(single_item)[:50]}")
                    print(f"Rule '{rule_name_for_log}': Retry for item '{str(single_item)[:50]}' (batch {batch_num}) failed: {retry_error_message}. Status: {retry_status}")
                    failed_items_with_errors.append((single_item, retry_error_message, retry_status))

    num_succeeded = len(successful_items)
    num_failed = len(failed_items_with_errors)
    print(f"Rule '{rule_name_for_log}': Batch processing for '{action_description}' complete. Succeeded: {num_succeeded}, Failed: {num_failed}.")
    if num_failed > 0:
        print(f"  Failed items and errors: {failed_items_with_errors}")


    return {"successful_items": successful_items, "failed_items_with_errors": failed_items_with_errors}

def _perform_action_add_to_files_batch(file_hashes, destination_service_keys, rule_name_for_log, batch_size=64):
    """
    Performs the 'add_to' action for a list of files in batches, migrating them
    to each specified destination service.

    Args:
        file_hashes (list): List of file hashes to process.
        destination_service_keys (list): A list of destination service keys.
        rule_name_for_log (str): The name of the rule, for logging.
        batch_size (int): Number of hashes to process per API call.

    Returns:
        dict: {
            "success": bool,  # True if all migrations for all files to all services were successful
            "total_successful_migrations": int, # Count of successful file-to-service migration operations
            "total_failed_migrations": int, # Count of failed file-to-service migration operations
            "files_with_some_errors": dict, # {file_hash: [error_details_for_this_hash]}
            "overall_errors": list # General errors not specific to a file hash
        }
        An "error_detail" is a dict: {"destination_service_key": str, "message": str, "status_code": int}
    """
    if not file_hashes:
        return {"success": True, "total_successful_migrations": 0, "total_failed_migrations": 0, "files_with_some_errors": {}, "overall_errors": []}
    if not destination_service_keys:
        # This means no action needed, so it's a success in terms of processing.
        return {"success": True, "total_successful_migrations": 0, "total_failed_migrations": 0, "files_with_some_errors": {}, "overall_errors": []}

    overall_success_flag = True
    total_successful_migrations = 0
    total_failed_migrations = 0
    files_with_errors_map = {} # Stores errors per file hash
    action_description_base = "add files to service"
    endpoint = '/add_files/migrate_files'
    method = 'POST'

    for dest_key in destination_service_keys:
        print(f"Rule '{rule_name_for_log}': Processing 'add_to' for service '{dest_key}' for {len(file_hashes)} files.")

        def batch_payload_formatter_migrate(batch_hashes_list):
            return {
                "hashes": batch_hashes_list,
                "file_service_key": dest_key
            }

        def single_item_payload_formatter_migrate(single_hash):
            return {
                "hash": single_hash,
                "file_service_key": dest_key
            }

        batch_results = _batch_api_call_with_retry(
            endpoint=endpoint,
            method=method,
            items_to_process=file_hashes, # Pass all hashes for this destination key
            batch_size=batch_size,
            batch_payload_formatter=batch_payload_formatter_migrate,
            single_item_payload_formatter=single_item_payload_formatter_migrate,
            rule_name_for_log=rule_name_for_log,
            action_description=f"{action_description_base} '{dest_key}'",
            timeout_per_call=180 # Potentially long for large batches
        )

        total_successful_migrations += len(batch_results["successful_items"])

        if batch_results["failed_items_with_errors"]:
            overall_success_flag = False
            total_failed_migrations += len(batch_results["failed_items_with_errors"])
            for failed_hash, error_msg, status_code in batch_results["failed_items_with_errors"]:
                if failed_hash not in files_with_errors_map:
                    files_with_errors_map[failed_hash] = []
                files_with_errors_map[failed_hash].append({
                    "destination_service_key": dest_key,
                    "message": error_msg,
                    "status_code": status_code
                })

    return {
        "success": overall_success_flag,
        "total_successful_migrations": total_successful_migrations,
        "total_failed_migrations": total_failed_migrations,
        "files_with_some_errors": files_with_errors_map, # Provides per-file error details
        "overall_errors": [] # Kept for consistency, specific errors are now in files_with_errors_map
    }
    
def _perform_action_add_to_file(file_hash, destination_service_keys, rule_name_for_log):
    """
    Performs the 'add_to' action for a single file.
    This involves copying (migrating) the file to each specified destination service.

    Args:
        file_hash (str): The hash of the file to process.
        destination_service_keys (list): A list of destination service keys.
        rule_name_for_log (str): The name of the rule, for logging.

    Returns:
        dict: {
            "success": bool,  # True if all migrations attempted were successful (or no destinations)
            "migrated_to_count": int, # Number of services the file was successfully migrated to
            "errors": list # List of error messages if any migrations failed
        }
    """
    if not file_hash:
        return {"success": False, "migrated_to_count": 0, "errors": ["File hash was missing."]}
    if not destination_service_keys: 
        return {"success": True, "migrated_to_count": 0, "errors": []} 

    migrated_count = 0
    errors = []

    for dest_key in destination_service_keys:
        migrate_payload = {
            "hash": file_hash,
            "file_service_key": dest_key 
        }
        migrate_result, migrate_status = call_hydrus_api(
            '/add_files/migrate_files', 
            method='POST', 
            json_data=migrate_payload, 
            timeout=120 
        )

        if migrate_result.get("success"):
            migrated_count += 1
        else:
            error_msg = f"Failed to add {file_hash} to service {dest_key}: {migrate_result.get('message', 'Unknown API error')}"
            print(f"Rule '{rule_name_for_log}': {error_msg}")
            errors.append({
                "hash": file_hash,
                "destination_service_key": dest_key,
                "message": error_msg,
                "status_code": migrate_status
            })

    overall_success = (len(errors) == 0) 
    return {"success": overall_success, "migrated_to_count": migrated_count, "errors": errors}    

def _perform_action_force_in_batch(files_metadata_list, destination_service_keys,
                                   all_local_service_keys_set, rule_name_for_log,
                                   available_services_list, batch_size=64):
    """
    Performs the 'force_in' action for a list of files in batches.
    1. Copies files to all specified destination services (batch).
    2. Verifies files are present in ALL destination services (fetches fresh metadata).
    3. If verified, deletes files from any OTHER local file services they're in (batch).

    Args:
        files_metadata_list (list): List of metadata objects for the files.
                                    Each object must include 'hash' and 'file_services'.
        destination_service_keys (list): A list of target destination service keys.
        all_local_service_keys_set (set): A set of all service keys that are local file services.
        rule_name_for_log (str): The name of the rule, for logging.
        available_services_list (list): Full list of available services (for names, types).
        batch_size (int): Number of items to process per API call for copy/delete.

    Returns:
        dict: {
            "success": bool, # True if all files were successfully forced into all destinations AND extraneous cleaned up
            "files_fully_successful": list, # Hashes of files that completed all phases successfully
            "files_with_errors": dict, # {file_hash: {"phase": str, "errors": [error_details]}}
            "summary_counts": {
                "initial_candidates": int,
                "copied_phase_success_count": int, # How many files succeeded copy to ALL dests
                "verified_phase_success_count": int, # How many files were verified in ALL dests
                "deleted_phase_success_count": int  # How many files had successful cleanup
            },
            "overall_errors": list # General errors not specific to a file
        }
        An "error_detail" is a dict: {"service_key": str (optional), "message": str, "status_code": int (optional)}
    """
    initial_candidate_count = len(files_metadata_list)
    if not files_metadata_list:
        return {
            "success": True, "files_fully_successful": [], "files_with_errors": {},
            "summary_counts": {"initial_candidates": 0, "copied_phase_success_count": 0, "verified_phase_success_count": 0, "deleted_phase_success_count": 0},
            "overall_errors": []
        }

    if not destination_service_keys:
        msg = f"Rule '{rule_name_for_log}': 'force_in' action called with no destination services. This is unsafe. Aborting."
        print(msg)
        return {
            "success": False, "files_fully_successful": [], "files_with_errors": {},
            "summary_counts": {"initial_candidates": initial_candidate_count, "copied_phase_success_count": 0, "verified_phase_success_count": 0, "deleted_phase_success_count": 0},
            "overall_errors": [msg]
        }

    files_fully_successful_list = []
    files_with_errors_map = {} # file_hash -> {"phase": "copy/verify/delete", "errors": []}
    
    candidate_hashes = [fm.get('hash') for fm in files_metadata_list if fm.get('hash')]
    if len(candidate_hashes) != initial_candidate_count:
        msg = f"Rule '{rule_name_for_log}': Some initial file metadata objects were missing hashes."
        print(msg)
        # This is a data integrity issue, record as an overall error.
        # We'll proceed with the valid hashes.
        # overall_errors.append(msg) # Decided to just log and proceed with valid ones.


    # --- Phase 1: Copy to all destination services ---
    print(f"Rule '{rule_name_for_log}': ForceIn - Phase 1 (Copy) for {len(candidate_hashes)} files to {destination_service_keys}")
    hashes_copied_to_all_dests = set(candidate_hashes) # Assume success, remove on failure

    for dest_key in destination_service_keys:
        if not hashes_copied_to_all_dests: break # No files left to process for this phase

        def batch_payload_formatter_migrate(batch_hashes_list):
            return {"hashes": batch_hashes_list, "file_service_key": dest_key}
        def single_item_payload_formatter_migrate(single_hash):
            return {"hash": single_hash, "file_service_key": dest_key}

        copy_results = _batch_api_call_with_retry(
            endpoint='/add_files/migrate_files', method='POST',
            items_to_process=list(hashes_copied_to_all_dests), # Process only those still considered successful
            batch_size=batch_size,
            batch_payload_formatter=batch_payload_formatter_migrate,
            single_item_payload_formatter=single_item_payload_formatter_migrate,
            rule_name_for_log=rule_name_for_log,
            action_description=f"ForceIn-Copy to dest '{dest_key}'",
            timeout_per_call=180
        )

        for failed_hash, error_msg, status_code in copy_results["failed_items_with_errors"]:
            hashes_copied_to_all_dests.discard(failed_hash)
            if failed_hash not in files_with_errors_map:
                files_with_errors_map[failed_hash] = {"phase": "copy", "errors": []}
            files_with_errors_map[failed_hash]["errors"].append({
                "service_key": dest_key, "message": f"Failed to copy to {dest_key}: {error_msg}", "status_code": status_code
            })
    
    copied_phase_success_count = len(hashes_copied_to_all_dests)
    print(f"Rule '{rule_name_for_log}': ForceIn - Phase 1 (Copy) completed. {copied_phase_success_count} files potentially copied to all destinations.")

    if not hashes_copied_to_all_dests:
        return {
            "success": False, "files_fully_successful": [], "files_with_errors": files_with_errors_map,
            "summary_counts": {"initial_candidates": initial_candidate_count, "copied_phase_success_count": 0, "verified_phase_success_count": 0, "deleted_phase_success_count": 0},
            "overall_errors": ["No files successfully copied to all destination services."]
        }

    # --- Phase 2: Verify presence in ALL destination services ---
    print(f"Rule '{rule_name_for_log}': ForceIn - Phase 2 (Verify) for {len(hashes_copied_to_all_dests)} files.")
    fresh_metadata_list, metadata_errors = _fetch_metadata_for_hashes(
        rule_name_for_log, list(hashes_copied_to_all_dests), batch_size=256 # Metadata fetch batch size
    )

    if metadata_errors:
        for err in metadata_errors:
            # Associate metadata fetch errors with affected hashes if possible
            for h_in_err_batch in err.get("hashes_in_batch", []):
                if h_in_err_batch in hashes_copied_to_all_dests: # Ensure it's a hash we care about
                    hashes_copied_to_all_dests.discard(h_in_err_batch) # Assume verification failed
                    if h_in_err_batch not in files_with_errors_map:
                        files_with_errors_map[h_in_err_batch] = {"phase": "verify", "errors": []}
                    files_with_errors_map[h_in_err_batch]["errors"].append({
                        "message": f"Metadata fetch failed during verification: {err.get('message')}",
                        "status_code": err.get("status_code")
                    })
        print(f"Rule '{rule_name_for_log}': ForceIn - Phase 2 (Verify) - Metadata fetch errors encountered for {len(metadata_errors)} batches.")


    hashes_verified_in_all_dests = set()
    destination_service_keys_set = set(destination_service_keys)

    for meta_obj in fresh_metadata_list:
        file_hash = meta_obj.get('hash')
        if not file_hash or file_hash not in hashes_copied_to_all_dests:
            continue # Not a hash we're currently tracking or malformed

        current_services_for_hash = set(meta_obj.get('file_services', {}).get('current', {}).keys())
        if destination_service_keys_set.issubset(current_services_for_hash):
            hashes_verified_in_all_dests.add(file_hash)
        else:
            missing_dests = destination_service_keys_set - current_services_for_hash
            if file_hash not in files_with_errors_map: # May have already had copy errors
                files_with_errors_map[file_hash] = {"phase": "verify", "errors": []}
            elif files_with_errors_map[file_hash]["phase"] != "verify": # If it had copy error, update phase
                 files_with_errors_map[file_hash]["phase"] = "verify" # Verification is the current point of failure
            
            files_with_errors_map[file_hash]["errors"].append({
                "message": f"Verification failed. Not in all required dests. Missing: {missing_dests}. Current: {current_services_for_hash}"
            })
    
    verified_phase_success_count = len(hashes_verified_in_all_dests)
    print(f"Rule '{rule_name_for_log}': ForceIn - Phase 2 (Verify) completed. {verified_phase_success_count} files verified in all destination services.")

    if not hashes_verified_in_all_dests:
        return {
            "success": False, "files_fully_successful": [], "files_with_errors": files_with_errors_map,
            "summary_counts": {"initial_candidates": initial_candidate_count, "copied_phase_success_count": copied_phase_success_count, "verified_phase_success_count": 0, "deleted_phase_success_count": 0},
            "overall_errors": ["No files verified in all destination services after copy attempts."]
        }

    # --- Phase 3: Delete from other local services (ONLY IF VERIFIED) ---
    print(f"Rule '{rule_name_for_log}': ForceIn - Phase 3 (Delete) for {len(hashes_verified_in_all_dests)} files.")
    
    # Map: service_key_to_delete_from -> list_of_hashes_to_delete_from_it
    deletions_by_service = {}
    # We need the fresh metadata again to determine current locations for deletion for *verified* files
    # Re-use fresh_metadata_list, filtered by hashes_verified_in_all_dests
    
    metadata_for_verified_hashes = {m['hash']: m for m in fresh_metadata_list if m.get('hash') in hashes_verified_in_all_dests}

    for file_hash in list(hashes_verified_in_all_dests): # Iterate copy as we might remove from set
        meta_obj = metadata_for_verified_hashes.get(file_hash)
        if not meta_obj: 
            # This shouldn't happen if _fetch_metadata_for_hashes worked for these hashes
            print(f"Rule '{rule_name_for_log}': Warning - Missing fresh metadata for verified hash {file_hash} during deletion phase prep.")
            hashes_verified_in_all_dests.discard(file_hash) # Cannot process for deletion
            if file_hash not in files_with_errors_map:
                 files_with_errors_map[file_hash] = {"phase": "delete_prep", "errors": []}
            files_with_errors_map[file_hash]["errors"].append({"message": "Missing fresh metadata for deletion prep."})
            continue

        current_services_for_hash = set(meta_obj.get('file_services', {}).get('current', {}).keys())
        services_to_delete_from_for_this_hash = (current_services_for_hash.intersection(all_local_service_keys_set)) - destination_service_keys_set
        
        for sk_del in services_to_delete_from_for_this_hash:
            if sk_del not in deletions_by_service:
                deletions_by_service[sk_del] = []
            deletions_by_service[sk_del].append(file_hash)

    hashes_deleted_successfully_from_extras = set(hashes_verified_in_all_dests) # Assume success, remove on failure

    for service_key_to_delete, hashes_on_this_service in deletions_by_service.items():
        if not hashes_on_this_service: continue
        if not hashes_deleted_successfully_from_extras: break # All remaining files already had a deletion error

        def batch_payload_formatter_delete(batch_hashes_list):
            # Default delete is "all my files". To delete from a specific service:
            return {"hashes": batch_hashes_list, "file_service_key": service_key_to_delete}
        def single_item_payload_formatter_delete(single_hash):
            return {"hash": single_hash, "file_service_key": service_key_to_delete}

        delete_results = _batch_api_call_with_retry(
            endpoint='/add_files/delete_files', method='POST',
            items_to_process=[h for h in hashes_on_this_service if h in hashes_deleted_successfully_from_extras],
            batch_size=batch_size,
            batch_payload_formatter=batch_payload_formatter_delete,
            single_item_payload_formatter=single_item_payload_formatter_delete,
            rule_name_for_log=rule_name_for_log,
            action_description=f"ForceIn-Delete from '{service_key_to_delete}'",
            timeout_per_call=180
        )

        for failed_hash, error_msg, status_code in delete_results["failed_items_with_errors"]:
            hashes_deleted_successfully_from_extras.discard(failed_hash)
            if failed_hash not in files_with_errors_map: # Should have entry from verify/copy
                files_with_errors_map[failed_hash] = {"phase": "delete", "errors": []}
            else: # If previous errors, ensure phase is now delete
                files_with_errors_map[failed_hash]["phase"] = "delete"
            files_with_errors_map[failed_hash]["errors"].append({
                "service_key": service_key_to_delete, "message": f"Failed to delete from {service_key_to_delete}: {error_msg}", "status_code": status_code
            })
    
    deleted_phase_success_count = 0
    # A file is fully successful if it was verified AND EITHER it needed no deletions OR all its required deletions succeeded.
    for h_verified in hashes_verified_in_all_dests:
        needed_deletion_from_some_service = any(h_verified in hash_list for hash_list in deletions_by_service.values())
        if not needed_deletion_from_some_service: # Verified and no deletions needed
            files_fully_successful_list.append(h_verified)
            deleted_phase_success_count+=1
        elif h_verified in hashes_deleted_successfully_from_extras: # Verified and all its deletions succeeded
            files_fully_successful_list.append(h_verified)
            deleted_phase_success_count+=1
        # Else, it was verified but some deletion for it failed (it's already in files_with_errors_map from above loop)
            
    print(f"Rule '{rule_name_for_log}': ForceIn - Phase 3 (Delete) completed. {deleted_phase_success_count} files had successful cleanup (if needed).")
    print(f"Rule '{rule_name_for_log}': ForceIn - Overall: {len(files_fully_successful_list)} files fully successful.")

    final_success_flag = (len(files_with_errors_map) == 0 and len(files_fully_successful_list) == initial_candidate_count)

    return {
        "success": final_success_flag,
        "files_fully_successful": files_fully_successful_list,
        "files_with_errors": files_with_errors_map,
        "summary_counts": {
            "initial_candidates": initial_candidate_count,
            "copied_phase_success_count": copied_phase_success_count,
            "verified_phase_success_count": verified_phase_success_count,
            "deleted_phase_success_count": deleted_phase_success_count
        },
        "overall_errors": [] # Specific errors are in files_with_errors
    }
    
def _execute_rule_logic(rule, db_conn, is_manual_run=False):
    """
    Internal function to execute a single rule's logic.
    Orchestrates condition translation, file searching, action execution,
    and manages persistent conflict overrides via database.
    Excludes recently viewed files from action if threshold is set.

    Args:
        rule (dict): The rule object.
        db_conn: Active SQLite database connection for conflict overrides.
        is_manual_run (bool): True if the rule is run manually, affects override behavior.
    Returns:
        dict: A dictionary containing the result and summary.
    """
    rule_id = rule.get('id', 'unknown')
    rule_name = rule.get('name', rule_id)
    current_rule_priority = int(rule.get('priority', 0))

    manual_run_log_str = "(Manual Run)" if is_manual_run else "(Scheduled Run)"
    print(f"Executing rule: '{rule_name}' (ID: {rule_id}, Prio: {current_rule_priority}) {manual_run_log_str}")

    files_skipped_due_to_override = 0
    files_skipped_due_to_recent_view = 0 # New counter

    def create_default_details():
        return {
            "translation_warnings": [], "metadata_errors": [],
            "action_processing_results": [], 
            "files_skipped_due_to_override": 0,
            "files_skipped_due_to_recent_view": 0, # New detail
            "action_tag_service_key_used_for_search": None
        }

    try:
        available_services = _ensure_available_services(rule_name)
        if available_services is None: # Should be empty list if failed, but defensive check
            details = create_default_details()
            return {
                "success": False,
                "message": f"Rule '{rule_name}' failed: Critical - Could not load Hydrus services.",
                "rule_id": rule_id, "rule_name": rule_name,
                "files_matched_by_search": 0, "files_metadata_fetched": 0,
                "files_action_attempted_on": 0, "files_added_successfully": 0,
                "files_forced_successfully": 0, "files_tag_action_success_on": 0,
                "files_rating_modified_successfully": 0,
                "files_skipped_due_to_override": files_skipped_due_to_override,
                "files_skipped_due_to_recent_view": files_skipped_due_to_recent_view,
                "details": details
            }

        settings = app.config['HYDRUS_SETTINGS']
        last_viewed_threshold_seconds = settings.get('last_viewed_threshold_seconds', 0)

        # --- Fetch Recently Viewed Files (if threshold is set) ---
        recently_viewed_hashes_set = set()
        if last_viewed_threshold_seconds > 0:
            print(f"Rule '{rule_name}': Checking for recently viewed files (threshold: {last_viewed_threshold_seconds}s).")
            try:
                # We want files viewed *after* this time
                threshold_time_dt = datetime.now() - timedelta(seconds=last_viewed_threshold_seconds)
                formatted_threshold_timestamp = threshold_time_dt.strftime('%Y-%m-%d %H:%M:%S')
                
                recent_view_predicates = [f"system:last viewed time > {formatted_threshold_timestamp}"]
                recent_view_search_params = {
                    'tags': json.dumps(recent_view_predicates),
                    'return_hashes': json.dumps(True),
                    'return_file_ids': json.dumps(False)
                }
                
                recent_view_result, recent_view_status = call_hydrus_api(
                    '/get_files/search_files', 
                    params=recent_view_search_params
                )

                if recent_view_result.get("success"):
                    fetched_recent_hashes = recent_view_result.get('data', {}).get('hashes', [])
                    recently_viewed_hashes_set = set(fetched_recent_hashes)
                    print(f"Rule '{rule_name}': Found {len(recently_viewed_hashes_set)} recently viewed files to exclude from actions.")
                else:
                    # Log error but proceed; rule execution shouldn't halt if this auxiliary search fails.
                    # Files just won't be excluded based on recent views for this run of this rule.
                    error_msg = recent_view_result.get('message', 'Unknown error during recent view search')
                    print(f"Rule '{rule_name}': Warning - Failed to fetch recently viewed files: {error_msg}. Proceeding without this exclusion.")
                    # Optionally add to translation_warnings or a specific new error list in details
            except Exception as e:
                print(f"Rule '{rule_name}': Warning - Exception while fetching recently viewed files: {e}. Proceeding without this exclusion.")

        rule_action_obj_for_translation = rule.get('action')
        if not isinstance(rule_action_obj_for_translation, (dict, type(None))):
            rule_action_obj_for_translation = None
        
        hydrus_predicates, translation_warnings, action_tag_service_key_for_search = \
            _translate_rule_to_hydrus_predicates(
                rule.get('conditions', []),
                rule_action_obj_for_translation,
                last_viewed_threshold_seconds, # Still passed, but no longer used by _translate_rule_to_hydrus_predicates for predicate generation
                available_services,
                rule_name
            )

        details_for_early_exit = create_default_details()
        details_for_early_exit["translation_warnings"] = translation_warnings
        details_for_early_exit["action_tag_service_key_used_for_search"] = action_tag_service_key_for_search
        # files_skipped_due_to_recent_view will be 0 here, updated later if applicable

        if not rule.get('conditions') and not hydrus_predicates:
             if not action_tag_service_key_for_search: 
                warning_msg_no_cond = f"Rule '{rule_name}' has no conditions, no generated exclusion predicates, and no action-specific tag service for search. It would match all files. Aborting execution for safety."
                print(warning_msg_no_cond)
                if not any("match all files" in warn.lower() for warn in translation_warnings): 
                    translation_warnings.append("Rule has no conditions, no generated exclusion predicates, and no action-specific tag service for search. Aborted for safety.")
                details_for_early_exit["translation_warnings"] = translation_warnings
                return {
                    "success": False, "message": warning_msg_no_cond,
                    "rule_id": rule_id, "rule_name": rule_name,
                    "files_matched_by_search": 0, "files_metadata_fetched": 0,
                    "files_action_attempted_on": 0, "files_added_successfully": 0,
                    "files_forced_successfully": 0, "files_tag_action_success_on": 0,
                    "files_rating_modified_successfully": 0,
                    "files_skipped_due_to_override": files_skipped_due_to_override,
                    "files_skipped_due_to_recent_view": files_skipped_due_to_recent_view,
                    "details": details_for_early_exit
                }

        search_params_for_api = {
            'return_hashes': json.dumps(True),
            'return_file_ids': json.dumps(False), 
            'tags': json.dumps(hydrus_predicates) 
        }

        if action_tag_service_key_for_search:
            search_params_for_api['tag_service_key'] = action_tag_service_key_for_search
            print(f"Rule '{rule_name}': Search will be restricted to tag service key '{action_tag_service_key_for_search}' due to action type.")

        search_result, search_status = call_hydrus_api('/get_files/search_files', params=search_params_for_api)

        if not search_result.get("success"):
            error_msg = search_result.get('message', 'Unknown error during file search')
            return {
                "success": False, "message": f"Rule '{rule_name}' failed file search: {error_msg}",
                "rule_id": rule_id, "rule_name": rule_name,
                "files_matched_by_search": 0,
                "files_metadata_fetched": 0,
                "files_action_attempted_on": 0,
                "files_added_successfully": 0,
                "files_forced_successfully": 0,
                "files_tag_action_success_on": 0,
                "files_rating_modified_successfully": 0,
                "files_skipped_due_to_override": files_skipped_due_to_override,
                "files_skipped_due_to_recent_view": files_skipped_due_to_recent_view,
                "details": details_for_early_exit
            }

        matched_hashes_from_search_raw = search_result.get('data', {}).get('hashes', [])
        num_matched_files_by_search_raw = len(matched_hashes_from_search_raw)
        print(f"Rule '{rule_name}': Hydrus search (main conditions) returned {num_matched_files_by_search_raw} hashes.")

        # --- Filter out recently viewed files from the main search results ---
        eligible_hashes_after_view_check = []
        if last_viewed_threshold_seconds > 0 and recently_viewed_hashes_set:
            for h in matched_hashes_from_search_raw:
                if h in recently_viewed_hashes_set:
                    files_skipped_due_to_recent_view += 1
                else:
                    eligible_hashes_after_view_check.append(h)
            print(f"Rule '{rule_name}': After 'recently viewed' check, {len(eligible_hashes_after_view_check)} files remain eligible. {files_skipped_due_to_recent_view} skipped as recently viewed.")
        else:
            eligible_hashes_after_view_check = list(matched_hashes_from_search_raw)
            # files_skipped_due_to_recent_view remains 0

        num_matched_files_after_view_filter = len(eligible_hashes_after_view_check)

        # Update details_for_early_exit with skip count before further checks
        details_for_early_exit["files_skipped_due_to_recent_view"] = files_skipped_due_to_recent_view

        if num_matched_files_after_view_filter == 0:
            message = f"Rule '{rule_name}': No files matched the Hydrus search conditions"
            if files_skipped_due_to_recent_view > 0:
                message += f" (or all matched were recently viewed: {files_skipped_due_to_recent_view} skipped)."
            else:
                message += "."
            return {
                "success": True, "message": message,
                "rule_id": rule_id, "rule_name": rule_name,
                "files_matched_by_search": num_matched_files_by_search_raw, # Report raw match count
                "files_metadata_fetched": 0,
                "files_action_attempted_on": 0, "files_added_successfully": 0,
                "files_forced_successfully": 0, "files_tag_action_success_on": 0,
                "files_rating_modified_successfully": 0,
                "files_skipped_due_to_override": files_skipped_due_to_override,
                "files_skipped_due_to_recent_view": files_skipped_due_to_recent_view,
                "details": details_for_early_exit
            }

        action_data_raw = rule.get('action')
        if not isinstance(action_data_raw, dict):
            details_for_early_exit["files_skipped_due_to_override"] = files_skipped_due_to_override
            return {
                "success": False, "message": f"Rule '{rule_name}' has malformed 'action' (not a dict).",
                "rule_id": rule_id, "rule_name": rule_name,                 
                "files_matched_by_search": num_matched_files_by_search_raw, 
                "files_metadata_fetched": 0,
                "files_action_attempted_on": 0, "files_added_successfully": 0,
                "files_forced_successfully": 0, "files_tag_action_success_on": 0,
                "files_rating_modified_successfully": 0,
                "files_skipped_due_to_override": files_skipped_due_to_override,
                "files_skipped_due_to_recent_view": files_skipped_due_to_recent_view,
                "details": details_for_early_exit
            }
        
        action_data = action_data_raw 
        action_type_from_rule = action_data.get('type')
        effective_action_type = action_type_from_rule 
        if action_type_from_rule == 'move':
            effective_action_type = 'force_in'
        elif action_type_from_rule == 'copy':
            effective_action_type = 'add_to'

        destination_service_keys = []
        tag_service_key_for_action = None
        tags_for_action = []
        rating_service_key_for_action = None
        rating_value_for_action = None

        # Action parameter validation (remains the same, uses num_matched_files_by_search_raw for context if erroring here)
        # ... (validation logic for destination_service_keys, tag_service_key_for_action, etc.)
        # If an error occurs in this block, the "files_matched_by_search" should still be num_matched_files_by_search_raw
        # and files_skipped_due_to_recent_view should be included in the return dict. Example for one:
        if effective_action_type in ['add_to', 'force_in']:
            destination_service_keys = action_data.get('destination_service_keys', [])
            if isinstance(destination_service_keys, str) and destination_service_keys:
                destination_service_keys = [destination_service_keys]
            elif not isinstance(destination_service_keys, list): 
                 destination_service_keys = []
            if not destination_service_keys or not all(isinstance(k, str) and k for k in destination_service_keys):
                err_msg_action = f"Rule '{rule_name}' action '{effective_action_type}' requires 'destination_service_keys' as a non-empty list of non-empty strings."
                return {"success": False, "message": err_msg_action, "rule_id": rule_id, "rule_name": rule_name, 
                        "files_matched_by_search": num_matched_files_by_search_raw, 
                        "files_action_attempted_on": 0, 
                        "files_skipped_due_to_override": files_skipped_due_to_override, 
                        "files_skipped_due_to_recent_view": files_skipped_due_to_recent_view,
                        "details": details_for_early_exit}
        # ... (similarly update other error returns in action param validation if they occur) ...
        elif effective_action_type in ['add_tags', 'remove_tags']:
            tag_service_key_for_action = action_data.get('tag_service_key') 
            tags_for_action = action_data.get('tags_to_process', [])
            if not tag_service_key_for_action: 
                err_msg_action = f"Rule '{rule_name}' action '{effective_action_type}' requires 'tag_service_key' for the action."
                return {"success": False, "message": err_msg_action, "rule_id": rule_id, "rule_name": rule_name, "files_matched_by_search": num_matched_files_by_search_raw, "files_action_attempted_on": 0, "files_skipped_due_to_override": files_skipped_due_to_override, "files_skipped_due_to_recent_view": files_skipped_due_to_recent_view, "details": details_for_early_exit}
            if not tags_for_action or not isinstance(tags_for_action, list) or not all(isinstance(t, str) and t for t in tags_for_action):
                err_msg_action = f"Rule '{rule_name}' action '{effective_action_type}' requires 'tags_to_process' as a non-empty list of non-empty strings."
                return {"success": False, "message": err_msg_action, "rule_id": rule_id, "rule_name": rule_name, "files_matched_by_search": num_matched_files_by_search_raw, "files_action_attempted_on": 0, "files_skipped_due_to_override": files_skipped_due_to_override, "files_skipped_due_to_recent_view": files_skipped_due_to_recent_view, "details": details_for_early_exit}
        elif effective_action_type == 'modify_rating':
            rating_service_key_for_action = action_data.get('rating_service_key')
            if 'rating_value' not in action_data: 
                err_msg_action = f"Rule '{rule_name}' action '{effective_action_type}' is missing 'rating_value'."
                return {"success": False, "message": err_msg_action, "rule_id": rule_id, "rule_name": rule_name, "files_matched_by_search": num_matched_files_by_search_raw, "files_action_attempted_on": 0, "files_skipped_due_to_override": files_skipped_due_to_override, "files_skipped_due_to_recent_view": files_skipped_due_to_recent_view, "details": details_for_early_exit}
            rating_value_for_action = action_data['rating_value']
            if not rating_service_key_for_action:
                err_msg_action = f"Rule '{rule_name}' action '{effective_action_type}' requires 'rating_service_key'."
                return {"success": False, "message": err_msg_action, "rule_id": rule_id, "rule_name": rule_name, "files_matched_by_search": num_matched_files_by_search_raw, "files_action_attempted_on": 0, "files_skipped_due_to_override": files_skipped_due_to_override, "files_skipped_due_to_recent_view": files_skipped_due_to_recent_view, "details": details_for_early_exit}
        else:
            err_msg_action = f"Rule '{rule_name}' has unknown/unsupported action type: '{action_type_from_rule}'."
            return {"success": False, "message": err_msg_action, "rule_id": rule_id, "rule_name": rule_name, "files_matched_by_search": num_matched_files_by_search_raw, "files_action_attempted_on": 0, "files_skipped_due_to_override": files_skipped_due_to_override, "files_skipped_due_to_recent_view": files_skipped_due_to_recent_view, "details": details_for_early_exit}


        candidate_hashes_for_action_after_override = []
        # Use eligible_hashes_after_view_check for override checks
        if not is_manual_run:
            for file_hash in eligible_hashes_after_view_check: # Iterate the view-filtered list
                skip_this_file_for_this_rule = False
                if effective_action_type == 'force_in':
                    existing_placement_override = get_conflict_override(db_conn, file_hash, "placement")
                    if existing_placement_override and existing_placement_override['winning_rule_priority'] > current_rule_priority:
                        files_skipped_due_to_override += 1
                        skip_this_file_for_this_rule = True
                elif effective_action_type == 'add_to':
                    existing_placement_override = get_conflict_override(db_conn, file_hash, "placement")
                    if existing_placement_override and existing_placement_override['winning_rule_priority'] > current_rule_priority:
                        files_skipped_due_to_override += 1
                        skip_this_file_for_this_rule = True
                elif effective_action_type == 'modify_rating':
                    existing_rating_override = get_conflict_override(db_conn, file_hash, "rating", rating_service_key_for_action) 
                    if existing_rating_override:
                        if existing_rating_override['winning_rule_priority'] > current_rule_priority:
                            files_skipped_due_to_override += 1
                            skip_this_file_for_this_rule = True
                        elif existing_rating_override['winning_rule_priority'] == current_rule_priority and \
                             existing_rating_override['winning_rule_id'] == rule_id and \
                             existing_rating_override['rating_value_set'] == rating_value_for_action: 
                            skip_this_file_for_this_rule = True 
                
                if not skip_this_file_for_this_rule:
                    candidate_hashes_for_action_after_override.append(file_hash)
                # else: # If skipped, it was already counted if by override.
                      # If skipped for other reasons (like already rated by same rule), files_skipped_due_to_override is not incremented here.
                      # The print statement below clarifies counts.
        else: 
            candidate_hashes_for_action_after_override = list(eligible_hashes_after_view_check) # Manual run ignores overrides

        num_candidates_after_all_filters = len(candidate_hashes_for_action_after_override)
        
        log_parts = [f"Rule '{rule_name}':"]
        log_parts.append(f"Initial search: {num_matched_files_by_search_raw} files.")
        if last_viewed_threshold_seconds > 0:
            log_parts.append(f"{files_skipped_due_to_recent_view} skipped as recently viewed.")
            log_parts.append(f"{num_matched_files_after_view_filter} remain after view filter.")
        if not is_manual_run:
            log_parts.append(f"{files_skipped_due_to_override} skipped due to higher-priority overrides.")
        log_parts.append(f"{num_candidates_after_all_filters} final candidates for '{effective_action_type}'.")
        print(" ".join(log_parts))


        details_for_early_exit["files_skipped_due_to_override"] = files_skipped_due_to_override
        # files_skipped_due_to_recent_view already set in details_for_early_exit

        if not candidate_hashes_for_action_after_override: # No files left after all filters
            message = f"Rule '{rule_name}': No files eligible for action after all filters (recent views, overrides)."
            # Add counts to the message for clarity
            message += f" (Initial: {num_matched_files_by_search_raw}, Skipped Recent: {files_skipped_due_to_recent_view}, Skipped Override: {files_skipped_due_to_override})"
            return {
                "success": True,
                "message": message,
                "rule_id": rule_id, "rule_name": rule_name,
                "files_matched_by_search": num_matched_files_by_search_raw,
                "files_metadata_fetched": 0, "files_action_attempted_on": 0,
                "files_added_successfully": 0, "files_forced_successfully": 0,
                "files_tag_action_success_on": 0, "files_rating_modified_successfully": 0,
                "files_skipped_due_to_override": files_skipped_due_to_override,
                "files_skipped_due_to_recent_view": files_skipped_due_to_recent_view,
                "details": details_for_early_exit
            }

        # --- Metadata Fetching (now primarily for 'force_in') ---
        files_to_process_metadata_list = [] 
        metadata_errors_accumulator = []
        num_metadata_fetched = 0

        if effective_action_type == 'force_in':
            fetched_meta, meta_errs = _fetch_metadata_for_hashes(rule_name, candidate_hashes_for_action_after_override)
            files_to_process_metadata_list = fetched_meta
            metadata_errors_accumulator.extend(meta_errs)
            num_metadata_fetched = len(files_to_process_metadata_list)
            
            if num_metadata_fetched == 0 and len(candidate_hashes_for_action_after_override) > 0 :
                details_for_early_exit["metadata_errors"] = metadata_errors_accumulator
                return {
                    "success": False,
                    "message": f"Rule '{rule_name}': Matched {num_matched_files_by_search_raw} files ({len(candidate_hashes_for_action_after_override)} after filters), but failed to get any metadata for 'force_in' action.",
                    "rule_id": rule_id, "rule_name": rule_name,
                    "files_matched_by_search": num_matched_files_by_search_raw,
                    "files_metadata_fetched": 0, "files_action_attempted_on": 0,
                    "files_skipped_due_to_override": files_skipped_due_to_override,
                    "files_skipped_due_to_recent_view": files_skipped_due_to_recent_view,
                    "details": details_for_early_exit
                }

        action_results_summary_list = []
        num_files_to_attempt_action_on = 0
        if effective_action_type == 'force_in':
            num_files_to_attempt_action_on = len(files_to_process_metadata_list)
        else: 
            num_files_to_attempt_action_on = len(candidate_hashes_for_action_after_override)

        print(f"Rule '{rule_name}': Attempting '{effective_action_type}' for {num_files_to_attempt_action_on} files/entries.")

        # --- Perform Actions Loop ---
        # Use candidate_hashes_for_action_after_override for actions other than force_in
        # Use files_to_process_metadata_list for force_in
        if effective_action_type == 'add_to':
            batch_add_to_result = _perform_action_add_to_files_batch(
                candidate_hashes_for_action_after_override, # Use the fully filtered list
                destination_service_keys,
                rule_name
            )
            action_results_summary_list.append({
                **batch_add_to_result,
                "action_type": effective_action_type,
            })
        elif effective_action_type in ['add_tags', 'remove_tags']:
            action_mode = 0 if effective_action_type == 'add_tags' else 1
            tag_action_result = _perform_action_manage_tags(
                candidate_hashes_for_action_after_override, # Use the fully filtered list
                tag_service_key_for_action, 
                tags_for_action,
                action_mode,
                rule_name
            )
            action_results_summary_list.append({
                **tag_action_result,
                "action_type": effective_action_type,
            })
        elif effective_action_type == 'modify_rating':
            for file_hash_for_action in candidate_hashes_for_action_after_override: # Use the fully filtered list
                action_result_single_file = {}
                try:
                    action_result_single_file = _perform_action_modify_rating(
                        file_hash_for_action,
                        rating_service_key_for_action, 
                        rating_value_for_action,
                        rule_name
                    )
                    if action_result_single_file.get("success"):
                        if not is_manual_run:
                            existing_override = get_conflict_override(db_conn, file_hash_for_action, "rating", rating_service_key_for_action)
                            can_claim = True
                            if existing_override and existing_override['winning_rule_priority'] > current_rule_priority:
                                can_claim = False
                            if can_claim:
                                set_conflict_override(db_conn, file_hash_for_action, "rating", rating_service_key_for_action,
                                                      rule_id, current_rule_priority,
                                                      rating_value_to_set=rating_value_for_action)
                except Exception as action_exc:
                    print(f"Rule '{rule_name}': Unexpected error during {effective_action_type} on {file_hash_for_action}: {action_exc}")
                    action_result_single_file = {"success": False, "errors": [f"Unexpected error: {str(action_exc)}"]}
                action_results_summary_list.append({**action_result_single_file, "hash": file_hash_for_action, "action_type": effective_action_type})
        
        elif effective_action_type == 'force_in':
            if files_to_process_metadata_list:
                local_file_service_keys_set = set()
                if isinstance(available_services, list):
                    local_file_service_keys_set = {
                        s['service_key'] for s in available_services 
                        if isinstance(s, dict) and s.get('type') == 2 and 'service_key' in s
                    }
                batch_force_in_result = _perform_action_force_in_batch(
                    files_metadata_list=files_to_process_metadata_list,
                    destination_service_keys=destination_service_keys,
                    all_local_service_keys_set=local_file_service_keys_set,
                    rule_name_for_log=rule_name,
                    available_services_list=available_services
                )
                action_results_summary_list.append({
                    **batch_force_in_result,
                    "action_type": effective_action_type,
                })
                if not is_manual_run and batch_force_in_result.get("files_fully_successful"):
                    for succeeded_hash in batch_force_in_result["files_fully_successful"]:
                        existing_override = get_conflict_override(db_conn, succeeded_hash, "placement")
                        can_claim = True
                        if existing_override and existing_override['winning_rule_priority'] > current_rule_priority:
                            can_claim = False
                        if can_claim:
                            set_conflict_override(db_conn, succeeded_hash, "placement", None,
                                                  rule_id, current_rule_priority)
            else: # No metadata for force_in
                action_results_summary_list.append({
                    "success": False, 
                    "message": "No files could be processed for 'force_in' due to metadata fetch failures for all candidates.",
                    "action_type": effective_action_type,
                    "files_fully_successful": [],
                    "files_with_errors": {h: {"phase":"metadata_fetch", "errors":[{"message":"Failed to fetch metadata"}]} for h in candidate_hashes_for_action_after_override},
                    "summary_counts": {"initial_candidates": len(candidate_hashes_for_action_after_override), "copied_phase_success_count": 0, "verified_phase_success_count": 0, "deleted_phase_success_count": 0},
                    "overall_errors": ["Metadata fetch failed for all 'force_in' candidates."]
                })

        all_action_errors_detailed = [] 
        total_files_added_successfully = 0 
        total_successful_add_to_operations = 0
        total_files_forced_successfully = 0
        total_files_tag_action_success_on = 0
        total_files_rating_modified_successfully = 0

        for res_data in action_results_summary_list:
            action_type_in_res = res_data.get("action_type")
            if action_type_in_res == 'add_to':
                total_successful_add_to_operations += res_data.get('total_successful_migrations', 0)
                if not res_data.get('success'):
                    # ... (error aggregation)
                    files_with_errs = res_data.get('files_with_some_errors', {})
                    for f_hash, err_list_for_hash in files_with_errs.items():
                        for err_detail in err_list_for_hash:
                            all_action_errors_detailed.append({
                                "hash": f_hash, "message": err_detail.get("message"),
                                "service_key": err_detail.get("destination_service_key"),
                                "status_code": err_detail.get("status_code")
                            })
                # Use candidate_hashes_for_action_after_override for calculating total_files_added_successfully
                if candidate_hashes_for_action_after_override: # Check if there were any candidates for add_to
                    successful_add_to_files_count = 0
                    # files_with_any_add_to_error_set should be based on the hashes actually processed by _perform_action_add_to_files_batch
                    # which are candidate_hashes_for_action_after_override
                    files_with_any_add_to_error_set = set(res_data.get('files_with_some_errors', {}).keys())
                    for f_hash in candidate_hashes_for_action_after_override:
                        if f_hash not in files_with_any_add_to_error_set:
                            successful_add_to_files_count += 1
                    total_files_added_successfully = successful_add_to_files_count

            elif action_type_in_res == 'force_in':
                total_files_forced_successfully = len(res_data.get("files_fully_successful", []))
                # ... (error aggregation)
                if not res_data.get("success"): 
                    files_with_errs = res_data.get('files_with_errors', {})
                    for f_hash, err_info in files_with_errs.items():
                        phase = err_info.get("phase", "unknown")
                        for err_detail in err_info.get("errors", []):
                            all_action_errors_detailed.append({
                                "hash": f_hash,
                                "message": f"[Phase: {phase}] {err_detail.get('message')}",
                                "service_key": err_detail.get("service_key"),
                                "status_code": err_detail.get("status_code")
                            })
                    for overall_err_msg in res_data.get("overall_errors", []):
                        all_action_errors_detailed.append({"message": f"[ForceIn Overall] {overall_err_msg}"})
            # ... (rest of error aggregation and success counting for other action types)
            elif not res_data.get('success'):
                current_action_errors = res_data.get('errors', [])
                if not isinstance(current_action_errors, list): current_action_errors = [str(current_action_errors)]
                for err_item in current_action_errors:
                    err_detail_dict = err_item if isinstance(err_item, dict) else {"message": str(err_item)}
                    if "hash" not in err_detail_dict and res_data.get("hash"): 
                        err_detail_dict["hash"] = res_data.get("hash")
                    all_action_errors_detailed.append(err_detail_dict)
            else: 
                if action_type_in_res == 'modify_rating': total_files_rating_modified_successfully += 1
                elif action_type_in_res in ['add_tags', 'remove_tags']:
                    total_files_tag_action_success_on = res_data.get("files_processed_count", 0)


        overall_rule_success = (len(all_action_errors_detailed) == 0)
        
        summary_parts = [f"Rule '{rule_name}' executed {manual_run_log_str}."]
        summary_parts.append(f"Hydrus search (main conditions) matched {num_matched_files_by_search_raw} files.")
        if action_tag_service_key_for_search: 
            summary_parts.append(f"Tag search was scoped to service key: '{action_tag_service_key_for_search}'.")
        if files_skipped_due_to_recent_view > 0:
            summary_parts.append(f"{files_skipped_due_to_recent_view} file(s) skipped due to recent viewing.")
        if files_skipped_due_to_override > 0:
            summary_parts.append(f"{files_skipped_due_to_override} file(s) skipped due to higher-priority overrides.")
        
        if effective_action_type == 'force_in' :
            summary_parts.append(f"Attempted to fetch metadata for {len(candidate_hashes_for_action_after_override)} candidates for 'force_in', got {num_metadata_fetched}.")
        
        if effective_action_type == 'add_to':
            summary_parts.append(f"Attempted 'Add To' for {num_files_to_attempt_action_on} files to {len(destination_service_keys)} service(s).")
            summary_parts.append(f"Total successful file-service migration operations: {total_successful_add_to_operations}.")
            if len(destination_service_keys) > 0 and num_files_to_attempt_action_on > 0:
                summary_parts.append(f"Files fully successful across all specified destinations: {total_files_added_successfully}/{num_files_to_attempt_action_on}.")
        elif effective_action_type == 'force_in':
            summary_parts.append(f"Attempted 'Force In' for {num_files_to_attempt_action_on} files (with fetched metadata). Fully succeeded for {total_files_forced_successfully} files.")
            if action_results_summary_list and isinstance(action_results_summary_list[0].get("summary_counts"), dict):
                counts = action_results_summary_list[0]["summary_counts"]
                summary_parts.append(f"  ForceIn Phases - Copied: {counts.get('copied_phase_success_count')}, Verified: {counts.get('verified_phase_success_count')}, Cleaned: {counts.get('deleted_phase_success_count')}.")
        elif effective_action_type in ['add_tags', 'remove_tags']:
            summary_parts.append(f"Attempted '{effective_action_type}' for {num_files_to_attempt_action_on} files. API call processed {total_files_tag_action_success_on} files.")
        elif effective_action_type == 'modify_rating':
            summary_parts.append(f"Attempted 'Modify Rating' for {num_files_to_attempt_action_on} files. Succeeded for {total_files_rating_modified_successfully} files.")

        if not overall_rule_success:
            summary_parts.append(f"Encountered {len(all_action_errors_detailed)} error(s) during actions.")
        if translation_warnings:
            summary_parts.append(f"Had {len(translation_warnings)} translation warning(s).")
        
        final_summary_message = " ".join(summary_parts)
        print(f"Rule '{rule_name}' final summary: {final_summary_message}")

        final_details = {
            "translation_warnings": translation_warnings,
            "metadata_errors": metadata_errors_accumulator,
            "action_processing_results": action_results_summary_list, 
            "files_skipped_due_to_override": files_skipped_due_to_override,
            "files_skipped_due_to_recent_view": files_skipped_due_to_recent_view, # Add to details
            "action_tag_service_key_used_for_search": action_tag_service_key_for_search 
        }

        return {
            "success": overall_rule_success, "message": final_summary_message,
            "rule_id": rule_id, "rule_name": rule_name,
            "action_performed": effective_action_type,
            "files_matched_by_search": num_matched_files_by_search_raw, # Report raw count
            "files_metadata_fetched": num_metadata_fetched,
            "files_action_attempted_on": num_files_to_attempt_action_on,
            "files_added_successfully": total_files_added_successfully, 
            "total_successful_add_to_file_service_operations": total_successful_add_to_operations if effective_action_type == 'add_to' else 0,
            "files_forced_successfully": total_files_forced_successfully,
            "files_tag_action_success_on": total_files_tag_action_success_on,
            "files_rating_modified_successfully": total_files_rating_modified_successfully,
            "files_skipped_due_to_override": files_skipped_due_to_override,
            "files_skipped_due_to_recent_view": files_skipped_due_to_recent_view, # Add to main result
            "details": final_details
        }

    except Exception as main_exec_exc:
        print(f"CRITICAL UNHANDLED ERROR in _execute_rule_logic for rule '{rule_name}' (ID: {rule_id}): {main_exec_exc}")
        import traceback
        traceback.print_exc()
        
        details = create_default_details() 
        try:
            if 'translation_warnings' in locals() and isinstance(translation_warnings, list):
                details["translation_warnings"] = translation_warnings
            if 'action_tag_service_key_used_for_search' in locals() and action_tag_service_key_for_search is not None:
                details["action_tag_service_key_used_for_search"] = action_tag_service_key_for_search
        except NameError: pass
        # Ensure skip counts are in details for critical errors too
        details["files_skipped_due_to_override"] = files_skipped_due_to_override
        details["files_skipped_due_to_recent_view"] = files_skipped_due_to_recent_view
        
        return {
            "success": False,
            "message": f"Core logic failure for rule '{rule_name}': {str(main_exec_exc)}",
            "rule_id": rule_id, "rule_name": rule_name,
            "files_matched_by_search": 0, "files_metadata_fetched": 0,
            "files_action_attempted_on": 0, "files_added_successfully": 0,
            "files_forced_successfully": 0, "files_tag_action_success_on": 0,
            "files_rating_modified_successfully": 0,
            "files_skipped_due_to_override": files_skipped_due_to_override,
            "files_skipped_due_to_recent_view": files_skipped_due_to_recent_view,
            "details": details
        }
def run_all_rules_scheduled():
    """
    This function is called by the scheduler. It iterates through all saved rules
    in priority order and executes each one using the internal logic.
    It now manages a database connection for persistent conflict overrides.
    It also checks if services are available before processing rules.
    """
    print(f"\n--- Scheduler: Starting scheduled rule execution at {datetime.now()} ---")
    
    db_conn = None
    changes_made_to_overrides = False 

    try:
        db_conn = get_db_connection()
        print("Scheduler: Database connection for conflict overrides established.")

        rules = load_rules() 
        # print(f"Scheduler: Loaded {len(rules)} rules directly from file for current run.") # Less verbose

        current_settings = load_settings() 
        app.config['HYDRUS_SETTINGS'] = current_settings 

        if not current_settings.get('api_address') or not current_settings.get('api_key'):
            missing_parts = []
            if not current_settings.get('api_address'): missing_parts.append("API address")
            if not current_settings.get('api_key'): missing_parts.append("API key")
            print(f"Scheduler: Hydrus {', '.join(missing_parts)} is not configured. Skipping scheduled run.")
            print(f"--- Scheduler: Finished scheduled rule execution at {datetime.now()} (API settings incomplete) ---")
            return 

        if not rules:
            print("Scheduler: No rules defined. Skipping scheduled run.")
            print(f"--- Scheduler: Finished scheduled rule execution at {datetime.now()} (no rules) ---")
            return 

        print("Scheduler: Ensuring Hydrus services are available for the run...")
        # _ensure_available_services will now return an empty list if services cannot be fetched
        available_services_list = _ensure_available_services("Scheduler_Run") 
        
        if not available_services_list: # Check if the list is empty
            print("Scheduler: CRITICAL - Could not fetch Hydrus services or service list is empty. Rule processing will be skipped for this run.")
            # This can happen if Hydrus is down or API call failed.
            # The app itself remains running, but this particular scheduled execution won't proceed with rules.
            print(f"--- Scheduler: Finished scheduled rule execution at {datetime.now()} (Hydrus services unavailable or empty) ---")
            return 
        else:
            print(f"Scheduler: Successfully ensured {len(available_services_list)} services are available/cached for rule processing.")

        rule_results = []
        for i, rule in enumerate(rules): 
            rule_name_for_log = rule.get('name', rule.get('id', 'Unnamed'))
            print(f"\nScheduler: Executing Rule {i+1}/{len(rules)}: '{rule_name_for_log}' (Priority: {rule.get('priority')})")
            try:
                execution_result = _execute_rule_logic(rule, db_conn, is_manual_run=False)
                rule_results.append(execution_result)

                if execution_result.get('success') or \
                   execution_result.get('files_forced_successfully', 0) > 0 or \
                   execution_result.get('files_rating_modified_successfully', 0) > 0:
                    changes_made_to_overrides = True
                
                # print(f"Scheduler: Rule '{rule_name_for_log}' Result: {execution_result.get('message', 'No summary message')}") # Less verbose by default
                if not execution_result.get('success', True): 
                    print(f"Scheduler: Rule '{rule_name_for_log}' reported issues or partial success. Summary: {execution_result.get('message', 'N/A')}")
                    if execution_result.get('details'):
                        details = execution_result['details']
                        # Reduced verbosity for scheduler logs, full details are available if needed via manual run or more detailed logging config
                        if details.get('translation_warnings') and details['translation_warnings']:
                            print(f"  Translation Warnings: {len(details['translation_warnings'])}")
                        if details.get('metadata_errors') and details['metadata_errors']:
                            print(f"  Metadata Errors: {len(details['metadata_errors'])}")
                        
                        action_errors_count = 0
                        if details.get('action_processing_results'):
                            for action_res in details['action_processing_results']:
                                if not action_res.get('success') and action_res.get('errors'):
                                    action_errors_count += len(action_res.get('errors', []))
                        if action_errors_count > 0:
                             print(f"  Action Errors Encountered: {action_errors_count}")


            except Exception as e:
                error_msg = f"Scheduler: An unexpected critical error occurred while processing rule '{rule_name_for_log}': {e}"
                print(error_msg)
                import traceback
                traceback.print_exc()
                rule_results.append({
                    "success": False, 
                    "message": error_msg, 
                    "rule_id": rule.get('id'), 
                    "rule_name": rule_name_for_log,
                    "details": {"translation_warnings": [], "metadata_errors": [], 
                                "action_processing_results": [], 
                                "files_skipped_due_to_override": 0, 
                                "critical_error": str(e)}
                })
        
        if db_conn and changes_made_to_overrides:
            print("Scheduler: Committing changes to conflict overrides database.")
            db_conn.commit()
        elif db_conn: # db_conn exists but no changes to commit
            pass # print("Scheduler: No changes detected that would require committing to conflict overrides database.") # Less verbose

    except sqlite3.Error as db_e:
        print(f"Scheduler: A database error occurred during scheduled run: {db_e}")
        import traceback
        traceback.print_exc()
    except Exception as global_e: 
        print(f"Scheduler: An unexpected global error occurred during scheduled run: {global_e}")
        import traceback
        traceback.print_exc()
    finally:
        if db_conn:
            # print("Scheduler: Closing database connection for conflict overrides.") # Less verbose
            db_conn.close()
        print(f"--- Scheduler: Finished scheduled rule execution at {datetime.now()} ---")


# --- APScheduler Management ---
def schedule_rules_job():
    """
    Manages the APScheduler job based on the 'rule_interval_seconds' setting.
    Removes any existing job and adds a new one if the interval is > 0.
    Includes an initial 20-second delay before the first run if the job is scheduled.
    """
    settings = app.config['HYDRUS_SETTINGS']
    interval_seconds = settings.get('rule_interval_seconds', 0) # Get interval, default 0
    job_id = 'run_all_rules_job'
    initial_delay_seconds = 20 # The new initial delay

    # Remove existing job if it exists
    if scheduler.get_job(job_id):
        print(f"Scheduler: Removing existing job '{job_id}'.")
        scheduler.remove_job(job_id)

    # Add new job if interval is greater than 0
    if isinstance(interval_seconds, (int, float)) and interval_seconds > 0:
        # Calculate the first run time: now + initial_delay_seconds
        first_run_time = datetime.now() + timedelta(seconds=initial_delay_seconds)
        
        print(f"Scheduler: Scheduling job '{job_id}' to run first at {first_run_time.strftime('%Y-%m-%d %H:%M:%S')} and then every {interval_seconds} seconds.")
        scheduler.add_job(
            id=job_id,
            func=run_all_rules_scheduled,
            trigger='interval',
            seconds=int(interval_seconds), # Ensure seconds is an integer for the interval
            next_run_time=first_run_time, # Specify the first run time
            replace_existing=True,
            misfire_grace_time=60 # Allow 60 seconds grace time for misfires
        )
    else:
        print(f"Scheduler: Rule interval is {interval_seconds} seconds (0 or invalid). Scheduled job will not be added.")

def _perform_action_manage_tags(file_hashes, tag_service_key, tags_to_process, action_mode, rule_name_for_log):
    """
    Performs tag management (add or remove) for a list of files on a specific tag service.

    Args:
        file_hashes (list): List of file hashes to process.
        tag_service_key (str): The service key of the target tag service.
        tags_to_process (list): List of tags to add or remove.
        action_mode (int): 0 for add, 1 for delete.
        rule_name_for_log (str): The name of the rule, for logging.

    Returns:
        dict: {
            "success": bool,
            "message": str,
            "files_processed_count": int, # Number of hashes sent to API
            "errors": list # List of error messages if API call failed
        }
    """
    if not file_hashes:
        return {"success": True, "message": "No files to process for tag action.", "files_processed_count": 0, "errors": []}
    if not tag_service_key:
        return {"success": False, "message": "Tag service key is missing for tag action.", "files_processed_count": 0, "errors": ["Missing tag_service_key."]}
    if not tags_to_process:
        return {"success": True, "message": "No tags specified for tag action.", "files_processed_count": len(file_hashes), "errors": []}

    action_type_str = "add" if action_mode == 0 else "remove"
    print(f"Rule '{rule_name_for_log}': Performing '{action_type_str} tags' action for {len(file_hashes)} files on service '{tag_service_key}'. Tags: {tags_to_process}")

    payload = {
        "hashes": file_hashes,
        "service_keys_to_actions_to_tags": {
            tag_service_key: {
                str(action_mode): tags_to_process  # action_mode must be a string key
            }
        }
    }

    # Set API behavior for adding/deleting tags
    if action_mode == 0: # Add
        payload["override_previously_deleted_mappings"] = True
    elif action_mode == 1: # Delete
        payload["create_new_deleted_mappings"] = True
        # For deletions, we might also want to ensure override is false if that becomes an option,
        # but current API has separate params. Stick to specified ones.

    add_tags_result, add_tags_status = call_hydrus_api(
        '/add_tags/add_tags',
        method='POST',
        json_data=payload,
        timeout=120  # Increased timeout for potentially many files/tags
    )

    if add_tags_result.get("success"):
        # The /add_tags/add_tags endpoint returns 200 OK with no content on success.
        # It doesn't return per-file success details for tag operations.
        # We assume success if the API call itself was successful.
        return {
            "success": True,
            "message": f"Successfully sent '{action_type_str} tags' request for {len(file_hashes)} files to service '{tag_service_key}'.",
            "files_processed_count": len(file_hashes),
            "errors": []
        }
    else:
        error_msg = f"Failed to {action_type_str} tags for {len(file_hashes)} files on service '{tag_service_key}': {add_tags_result.get('message', 'Unknown API error')}"
        print(f"Rule '{rule_name_for_log}': {error_msg}")
        return {
            "success": False,
            "message": error_msg,
            "files_processed_count": len(file_hashes), # Still attempted for this many
            "errors": [{"message": error_msg, "status_code": add_tags_status, "service_key": tag_service_key, "action_mode": action_mode}]
        }

def _perform_action_modify_rating(file_hash, rating_service_key, rating_value, rule_name_for_log):
    """
    Performs the 'modify_rating' action for a single file by calling the /edit_ratings/set_rating API.

    Args:
        file_hash (str): The hash of the file to modify the rating for.
        rating_service_key (str): The service key of the target rating service.
        rating_value (bool|int|None): The rating to set.
                                      - True/False for Like/Dislike services.
                                      - Integer for Numerical/Inc-Dec services.
                                      - None to unset the rating.
        rule_name_for_log (str): The name of the rule, for logging.

    Returns:
        dict: {
            "success": bool,
            "message": str, # Confirmation or error message
            "errors": list # Detailed error objects if API call failed
        }
    """
    if not file_hash:
        return {"success": False, "message": "File hash was missing for modify_rating.", "errors": ["File hash missing."]}
    if not rating_service_key:
        return {"success": False, "message": "Rating service key was missing for modify_rating.", "errors": ["Rating service key missing."]}
    # rating_value can be None, True, False, 0, so just check its presence conceptually (done by caller)

    action_log_str = f"rating_value: {rating_value} (type: {type(rating_value).__name__})"
    print(f"Rule '{rule_name_for_log}': Modifying rating for file {file_hash} on service '{rating_service_key}'. {action_log_str}")

    payload = {
        "hash": file_hash,
        "rating_service_key": rating_service_key,
        "rating": rating_value  # Direct use of the value (bool, int, or None)
    }

    # The /edit_ratings/set_rating endpoint expects a JSON body, not percent-encoded.
    # call_hydrus_api handles JSON serialization for POST if json_data is provided.
    set_rating_result, set_rating_status = call_hydrus_api(
        '/edit_ratings/set_rating',
        method='POST',
        json_data=payload, # Pass the dict directly
        timeout=60
    )

    if set_rating_result.get("success"):
        # The API returns 200 OK with no content on success.
        # call_hydrus_api for a successful POST with no JSON response content
        # will return a success message like "Request successful, received non-JSON content".
        success_msg = f"Successfully set rating for file {file_hash} on service '{rating_service_key}' to '{rating_value}'."
        print(f"Rule '{rule_name_for_log}': {success_msg}")
        return {
            "success": True,
            "message": success_msg,
            "errors": []
        }
    else:
        error_msg = (f"Failed to set rating for file {file_hash} on service '{rating_service_key}'. "
                     f"API Error: {set_rating_result.get('message', 'Unknown API error')}")
        print(f"Rule '{rule_name_for_log}': {error_msg}")
        return {
            "success": False,
            "message": error_msg,
            "errors": [{
                "message": set_rating_result.get('message', 'Unknown API error'),
                "status_code": set_rating_status,
                "hash": file_hash,
                "rating_service_key": rating_service_key
            }]
        }

# --- Flask Routes ---
@app.route('/')
def index():
    current_settings = app.config['HYDRUS_SETTINGS']
    # Pass the current theme and butler_name to the main page template
    return render_template('index.html', 
                           current_theme=current_settings.get('theme', 'default'),
                           current_settings=current_settings) # Pass the whole dict

@app.route('/settings')
def settings():
    current_settings = app.config['HYDRUS_SETTINGS']
    # Do NOT pass the api_key value to the template for security
    settings_for_template = current_settings.copy()
    if 'api_key' in settings_for_template:
         settings_for_template['api_key'] = '' # Replace with empty string

    # The template can access 'theme', 'available_themes', and 'butler_name'
    # directly from settings_for_template since it's a copy of current_settings.
    return render_template('settings.html', current_settings=settings_for_template)

@app.route('/save_settings', methods=['POST'])
def handle_save_settings():
    print("--- Received request to save settings ---")

    submitted_settings_data = {}
    submitted_settings_data['api_address'] = request.form.get('api-address', '').strip()
    submitted_settings_data['api_key'] = request.form.get('api-key', '').strip()
    submitted_settings_data['rule_interval_seconds'] = request.form.get('rule-interval-seconds')
    submitted_settings_data['last_viewed_threshold_seconds'] = request.form.get('last-viewed-threshold-seconds')
    submitted_settings_data['show_run_notifications'] = request.form.get('show-run-notifications')
    submitted_settings_data['show_run_all_notifications'] = request.form.get('show-run-all-notifications')
    submitted_settings_data['theme'] = request.form.get('theme')
    # --- Add new setting 'butler-name' retrieval from form ---
    submitted_settings_data['butler_name'] = request.form.get('butler-name', '').strip()
    
    print("Processed form data for save:", submitted_settings_data)

    save_success = save_settings(submitted_settings_data) 

    if save_success:
        print("Settings successfully saved to file and app config.")
        
        fetch_message = ""
        current_saved_settings = app.config.get('HYDRUS_SETTINGS', {})
        if current_saved_settings.get('api_address'):
            print("Attempting to fetch services with new settings...")
            services_endpoint_result, services_endpoint_status = call_hydrus_api('/get_services')

            if services_endpoint_result.get("success") and isinstance(services_endpoint_result.get('data'), dict):
                 services_object = services_endpoint_result["data"].get('services')
                 if isinstance(services_object, dict):
                     services_list = []
                     for key, service_details in services_object.items():
                          if isinstance(service_details, dict):
                               services_list.append({
                                   'service_key': key, 'name': service_details.get('name', 'Unnamed Service'),
                                   'type': service_details.get('type'), 'type_pretty': service_details.get('type_pretty', 'Unknown Type'),
                                    'star_shape': service_details.get('star_shape'), 'min_stars': service_details.get('min_stars'),
                                    'max_stars': service_details.get('max_stars'),
                               })
                     app.config['AVAILABLE_SERVICES'] = services_list
                     print(f"Fetched and cached {len(app.config['AVAILABLE_SERVICES'])} services after saving settings.")
                     fetch_message = f"Successfully fetched {len(services_list)} services from Hydrus."
                 else:
                      print(f"Warning: Failed to parse services object from /get_services response after saving settings.")
                      app.config['AVAILABLE_SERVICES'] = [] 
                      fetch_message = "Settings saved, but failed to parse service list from Hydrus API response."
            elif not services_endpoint_result.get("success"): 
                 print(f"Warning: Failed to fetch services after saving settings: {services_endpoint_result.get('message', 'Unknown error')}")
                 app.config['AVAILABLE_SERVICES'] = [] 
                 fetch_message = f"Settings saved, but failed to fetch service list from Hydrus API: {services_endpoint_result.get('message', 'Unknown error')}"
            else: 
                 print(f"Warning: Unexpected response when fetching services after saving. Status: {services_endpoint_status}. Using empty services list.")
                 app.config['AVAILABLE_SERVICES'] = []
                 fetch_message = "Settings saved, but received an unexpected response when fetching services."
        else:
            print("Hydrus API address not configured after saving settings. Skipping service fetch.")
            app.config['AVAILABLE_SERVICES'] = [] 
            fetch_message = "Settings saved. Hydrus API address is not configured, so services were not fetched."

        flash(f"Settings saved. {fetch_message}", "success" if "Successfully fetched" in fetch_message or "Hydrus API address is not configured" in fetch_message else "info")
        print("--- Finished saving settings successfully, redirecting ---")
        return redirect(url_for('settings'))
    else:
        print("Failed to save settings file.")
        print("--- Finished saving settings with failure ---")
        flash("Failed to write settings file. Check file permissions.", "error")
        return redirect(url_for('settings'))

@app.route('/get_all_services')
def get_all_services():
    """Endpoint to get all services from Hydrus API (cached or fetched)."""
    # print("Attempting to fetch all services from Hydrus API.") # Less verbose
    
    # Check cache first
    # If services were populated at startup or by _ensure_available_services,
    # and that list is not empty, return it.
    cached_services = app.config.get('AVAILABLE_SERVICES')
    if isinstance(cached_services, list) and cached_services: # Only return non-empty cache
         # print(f"Returning {len(cached_services)} services from cache.") # Less verbose
         return jsonify({"success": True, "services": cached_services}), 200

    # If cache is empty or not a list, attempt to fetch.
    # This will also be hit if startup fetch failed and user clicks "Update Services" button.
    print("Cache for available services is empty or not populated. Attempting to fetch from Hydrus API via /get_all_services endpoint.")

    # Ensure API address is configured before attempting call
    settings = app.config.get('HYDRUS_SETTINGS', {})
    if not settings.get('api_address'):
        message = "Hydrus API address is not configured. Cannot fetch services."
        print(f"/get_all_services: {message}")
        app.config['AVAILABLE_SERVICES'] = [] # Ensure cache is empty
        return jsonify({"success": False, "message": message, "services": []}), 400 # Bad Request or appropriate error

    result, status_code = call_hydrus_api('/get_services')

    if result.get("success") and isinstance(result.get('data'), dict):
        services_object = result["data"].get('services')
        if not isinstance(services_object, dict):
             message = "Unexpected response format from Hydrus API /get_services (services object not a dict)."
             print(f"/get_all_services: {message} Type: {type(services_object)}")
             app.config['AVAILABLE_SERVICES'] = []
             return jsonify({"success": False, "message": message, "services": []}), 500

        services_list = []
        for key, service_details in services_object.items():
             if isinstance(service_details, dict):
                  services_list.append({
                      'service_key': key, 'name': service_details.get('name', 'Unnamed Service'),
                      'type': service_details.get('type'), 'type_pretty': service_details.get('type_pretty', 'Unknown Type'),
                       'star_shape': service_details.get('star_shape'), 'min_stars': service_details.get('min_stars'),
                       'max_stars': service_details.get('max_stars'),
                  })
             else:
                  print(f"/get_all_services: Skipping service with key {key} due to unexpected details format: {type(service_details)}")

        print(f"/get_all_services: Successfully fetched {len(services_list)} services.")
        app.config['AVAILABLE_SERVICES'] = services_list
        # print(f"Stored {len(app.config['AVAILABLE_SERVICES'])} services in config.") # Less verbose
        return jsonify({"success": True, "services": services_list}), 200
    else: # call_hydrus_api returned success: False or other issues
        message = result.get('message', 'Unknown error occurred while fetching services from Hydrus.')
        print(f"/get_all_services: Failed to fetch services. API Error: {message}")
        app.config['AVAILABLE_SERVICES'] = [] 
        # Return the status_code from call_hydrus_api if available, otherwise 500/503
        # If status_code is already in result from call_hydrus_api, it would be used.
        # Here, status_code is from the tuple return of call_hydrus_api
        error_status_to_return = status_code if status_code else 503 # Default to 503 if not specific
        return jsonify({"success": False, "message": message, "services": []}), error_status_to_return


@app.route('/get_client_settings', methods=['GET'])
def get_client_settings():
    """Endpoint to get client-side specific settings."""
    settings = app.config['HYDRUS_SETTINGS'] # HYDRUS_SETTINGS is already up-to-date

    client_settings = {
        'show_run_notifications': settings.get('show_run_notifications', True),
        'show_run_all_notifications': settings.get('show_run_all_notifications', True), # Add new setting
        'theme': settings.get('theme', 'default') 
    }
    print("Providing client settings (including show_run_all_notifications and theme):", client_settings)
    return jsonify({"success": True, "settings": client_settings}), 200
    
@app.route('/rules', methods=['GET'])
def get_rules():
    """Endpoint to get all rules (already sorted)."""
    # Rules are loaded and sorted on app start and whenever they are saved
    # Return the sorted list from the config
    print("Returning rules from config (already sorted).")
    rules = app.config['AUTOMATION_RULES']
    return jsonify({"success": True, "rules": rules}), 200

# --- START OF COMPLETE app.py function ---
@app.route('/add_rule', methods=['POST'])
def add_rule():
    """Endpoint to add a new rule or update an existing one."""
    print("Attempting to add or update rule.")
    if not request.is_json:
        print("Add/update rule request was not JSON.")
        return jsonify({"success": False, "message": "Request must be JSON."}), 415

    rule_data = request.get_json()
    rule_id_from_payload = rule_data.get('id')
    rule_name_for_log = rule_data.get('name', 'Unnamed Rule')

    print(f"Received rule data for {'update' if rule_id_from_payload else 'add'}: {rule_name_for_log}")
    # DEBUG: Print the structure of conditions received from the frontend
    print(f"Received rule_data.conditions: {json.dumps(rule_data.get('conditions'), indent=2)}")

    required_fields = ['name', 'priority', 'conditions', 'action']
    if not all(field in rule_data for field in required_fields):
        missing = [field for field in required_fields if field not in rule_data]
        print(f"Missing required rule fields: {missing}")
        return jsonify({"success": False, "message": f"Missing required rule fields: {', '.join(missing)}."}), 400

    try:
        priority = int(rule_data['priority'])
        rule_data['priority'] = priority
    except (ValueError, TypeError):
        print("Priority must be a valid number.")
        return jsonify({"success": False, "message": "Priority must be a valid number."}), 400

    # Validate 'conditions' field: must be a list (can be empty)
    if not isinstance(rule_data.get('conditions'), list):
        print("Conditions field must be a list.")
        return jsonify({"success": False, "message": "Conditions field must be a list."}), 400

    action = rule_data.get('action', {})
    if not isinstance(action, dict) or 'type' not in action or not action.get('type'):
        print("Action must be an object with a non-empty 'type'.")
        return jsonify({"success": False, "message": "Action must be an object with a non-empty 'type'."}), 400
    
    action_type_value = action.get('type')

    # Detailed action parameter validation
    if action_type_value in ['add_to', 'force_in']:
        dest_keys = action.get('destination_service_keys')
        if not dest_keys or not isinstance(dest_keys, list) or not all(isinstance(k, str) and k for k in dest_keys):
            msg = f"Action '{action_type_value}' requires 'destination_service_keys' as a non-empty list of non-empty strings."
            print(msg)
            return jsonify({"success": False, "message": msg}), 400
        if len(set(dest_keys)) != len(dest_keys):
             msg = f"Action '{action_type_value}': Destination service keys must be unique."
             print(msg)
             return jsonify({"success": False, "message": msg}), 400
    elif action_type_value in ['add_tags', 'remove_tags']:
        tag_key = action.get('tag_service_key')
        tags_proc = action.get('tags_to_process')
        if not tag_key or not isinstance(tag_key, str):
            msg = f"Action '{action_type_value}' requires 'tag_service_key' as a non-empty string."
            print(msg)
            return jsonify({"success": False, "message": msg}), 400
        if not tags_proc or not isinstance(tags_proc, list) or not all(isinstance(t, str) and t for t in tags_proc):
            msg = f"Action '{action_type_value}' requires 'tags_to_process' as a non-empty list of non-empty strings."
            print(msg)
            return jsonify({"success": False, "message": msg}), 400
    elif action_type_value == 'modify_rating':
        rating_key = action.get('rating_service_key')
        if 'rating_value' not in action: # rating_value can be None, True, False, 0
            msg = f"Action '{action_type_value}' is missing 'rating_value'."
            print(msg)
            return jsonify({"success": False, "message": msg}), 400
        # rating_val = action['rating_value'] # Value extracted, type depends on service
        if not rating_key or not isinstance(rating_key, str):
            msg = f"Action '{action_type_value}' requires 'rating_service_key' as a non-empty string."
            print(msg)
            return jsonify({"success": False, "message": msg}), 400
    else:
        print(f"Unknown or unsupported action type for parameter validation: {action_type_value}")
        return jsonify({"success": False, "message": f"Unsupported action type: {action_type_value}."}), 400

    rules = load_rules()
    db_conn = None

    try:
        action_performed_text = ''
        final_rule_id_for_response = None

        if not rule_id_from_payload:  # ADD operation
            action_performed_text = 'added'
            rule_data['id'] = str(uuid.uuid4())
            final_rule_id_for_response = rule_data['id']
            submitted_name = rule_data.get('name', '').strip()
            if not submitted_name:
                max_rule_num = 0
                for r_item in rules:
                    r_name = r_item.get('name', '')
                    if r_name.startswith("Rule ") and r_name[5:].isdigit():
                        try:
                            num = int(r_name[5:])
                            if num > max_rule_num:
                                max_rule_num = num
                        except ValueError:
                            pass
                rule_data['name'] = f"Rule {max_rule_num + 1}"
            else:
                rule_data['name'] = submitted_name
            
            print(f"Adding new rule. ID: {rule_data['id']}, Name: {rule_data['name']}")
            # DEBUG: Print conditions being added for a new rule
            print(f"Conditions for new rule {rule_data['id']}: {json.dumps(rule_data.get('conditions'), indent=2)}")
            rules.append(rule_data)

        else:  # UPDATE operation
            action_performed_text = 'updated'
            final_rule_id_for_response = rule_id_from_payload
            found = False
            for i, rule_item in enumerate(rules):
                if rule_item.get('id') == rule_id_from_payload:
                    print(f"Updating rule ID {rule_id_from_payload}. Invalidating its conflict overrides...")
                    db_conn = get_db_connection()
                    deleted_override_count = remove_overrides_for_rule(db_conn, rule_id_from_payload)
                    db_conn.commit()
                    print(f"Invalidated {deleted_override_count} overrides for rule ID {rule_id_from_payload}.")
                    
                    rule_data['id'] = rule_id_from_payload  # Ensure ID remains the same
                    submitted_name_update = rule_data.get('name', '').strip()
                    if not submitted_name_update:
                        rule_data['name'] = rule_item.get('name', f"Rule (ID: {rule_id_from_payload[:8]})")
                    else:
                        rule_data['name'] = submitted_name_update
                    
                    rules[i] = rule_data
                    found = True
                    print(f"Prepared to update rule. ID: {rule_id_from_payload}, New Name: {rule_data.get('name')}")
                    # DEBUG: Print conditions being set for the update
                    print(f"Conditions for updating rule {rule_id_from_payload}: {json.dumps(rule_data.get('conditions'), indent=2)}")
                    break
            if not found:
                print(f"Rule with ID {rule_id_from_payload} not found for update.")
                return jsonify({"success": False, "message": f"Rule with ID {rule_id_from_payload} not found for update."}), 404

        if save_rules(rules):
            print(f"Rule {action_performed_text} successfully. Rule configuration saved to file.")
            return jsonify({
                "success": True,
                "message": f"Rule {action_performed_text} successfully.",
                "rule_id": final_rule_id_for_response,
                "rule_name": rule_data.get('name')
            }), 200
        else:
            print("Failed to save rule data to rules.json after add/update attempt.")
            return jsonify({"success": False, "message": "Failed to save rule data to file."}), 500

    except sqlite3.Error as e:
        print(f"Database error during add/update rule (override invalidation): {e}")
        return jsonify({"success": False, "message": f"A database error occurred: {e}"}), 500
    except Exception as e:
        print(f"Unexpected error during add/update rule: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "message": f"An unexpected error occurred: {e}"}), 500
    finally:
        if db_conn:
            db_conn.close()

@app.route('/rules/<rule_id>', methods=['DELETE'])
def delete_rule(rule_id):
    """Endpoint to delete a rule by ID and its associated conflict overrides."""
    print(f"Attempting to delete rule with ID: {rule_id}")
    rules = load_rules() 
    original_count = len(rules)
    
    rule_to_delete_exists = any(rule.get('id') == rule_id for rule in rules)

    if not rule_to_delete_exists:
        print(f"Rule with ID {rule_id} not found in rules.json for deletion.")
        return jsonify({"success": False, "message": f"Rule with ID {rule_id} not found."}), 404

    db_conn = None
    try:
        print(f"Deleting rule: Invalidating conflict overrides for rule ID {rule_id}...")
        db_conn = get_db_connection()
        deleted_override_count = remove_overrides_for_rule(db_conn, rule_id)
        # If remove_overrides_for_rule returns -1, it's an error. We should probably not proceed.
        if deleted_override_count == -1:
             print(f"Failed to remove conflict overrides for rule {rule_id}. Aborting rule deletion.")
             db_conn.rollback() # Rollback any potential transaction state if an error occurred in helper
             return jsonify({"success": False, "message": "Failed to remove conflict overrides from database. Rule not deleted."}), 500
        
        db_conn.commit() # Commit the override removal
        print(f"Invalidated {deleted_override_count} overrides for rule ID {rule_id}.")


        # Now proceed to remove the rule from the rules list and save the file
        rules = [rule for rule in rules if rule.get('id') != rule_id]
        new_count = len(rules) # Should be original_count - 1 if found and deleted

        if new_count < original_count: # Rule was found and removed from list
            if save_rules(rules): # Save the updated rules.json
                print(f"Rule with ID {rule_id} deleted successfully from rules.json and overrides cleared.")
                return jsonify({"success": True, "message": f"Rule with ID {rule_id} deleted successfully."}), 200
            else:
                print(f"Failed to save rules.json after preparing to delete rule {rule_id}. Overrides were cleared.")
                # This is an inconsistent state: overrides are gone, but rule still in file.
                # Hard to perfectly roll back file save failures easily.
                return jsonify({"success": False, "message": "Rule overrides cleared, but failed to save rules file."}), 500
        else:
            # This case should ideally be caught by the initial check, but as a safeguard:
            print(f"Rule with ID {rule_id} was not found in the list during filtering, though it existed initially. This is unexpected.")
            return jsonify({"success": False, "message": f"Rule with ID {rule_id} not found during list filtering (unexpected)."}), 404


    except sqlite3.Error as e:
        print(f"Database error during rule deletion (override invalidation) for rule ID {rule_id}: {e}")
        if db_conn: db_conn.rollback() # Rollback on error
        return jsonify({"success": False, "message": f"A database error occurred: {e}"}), 500
    except Exception as e:
        print(f"Unexpected error during rule deletion for ID {rule_id}: {e}")
        import traceback
        traceback.print_exc()
        if db_conn: db_conn.rollback()
        return jsonify({"success": False, "message": f"An unexpected error occurred: {e}"}), 500
    finally:
        if db_conn:
            db_conn.close()


@app.route('/run_rule/<rule_id>', methods=['POST'])
def run_rule_endpoint(rule_id):
    """
    Flask endpoint to manually run a single rule.
    Calls the internal _execute_rule_logic. For manual runs,
    persistent conflict overrides are ignored for execution and not updated.
    """
    print(f"Attempting to manually run rule with ID: {rule_id}")
    
    rule_name_for_error = "Unknown" 
    db_conn_manual_run = None # Initialize

    try:
        rules = load_rules() 
        rule = next((r for r in rules if r.get('id') == rule_id), None)

        if not rule:
            print(f"Rule with ID {rule_id} not found.")
            error_response = {
                "success": False, 
                "message": f"Rule with ID {rule_id} not found.",
                "rule_id": rule_id,
                "rule_name": rule_name_for_error, 
                "details": { # Ensure consistent detail structure
                    "translation_warnings": [], "metadata_errors": [], 
                    "action_processing_results": [], "files_skipped_due_to_override": 0
                }
            }
            return jsonify(error_response), 404
        
        rule_name_for_error = rule.get('name', rule_id)

        db_conn_manual_run = get_db_connection()
        print(f"Manual run for rule '{rule_name_for_error}': DB connection established (overrides will be bypassed for this run).")

        execution_result = _execute_rule_logic(rule, db_conn_manual_run, is_manual_run=True)


        # Ensure consistent detail structure in the response
        if 'details' not in execution_result: 
            execution_result['details'] = {}
        execution_result['details'].setdefault('translation_warnings', [])
        execution_result['details'].setdefault('metadata_errors', [])
        execution_result['details'].setdefault('action_processing_results', [])
        execution_result['details'].setdefault('files_skipped_due_to_override', 0) 
        
        status_code = 200 # HTTP 200 even if rule logic had partial success/errors reported in JSON
                         # Use 500 only for unhandled server errors.
        # The 'success' field within execution_result reflects the rule's own outcome.
        return jsonify(execution_result), status_code

    except sqlite3.Error as db_e: # Catch DB errors if connection fails
        print(f"CRITICAL DATABASE ERROR during manual run setup for rule ID {rule_id} (Name: {rule_name_for_error}): {db_e}")
        import traceback
        traceback.print_exc()
        critical_error_response = {
            "success": False,
            "message": f"A database connection error occurred while trying to run rule '{rule_name_for_error}'. Error: {str(db_e)}",
            "rule_id": rule_id, "rule_name": rule_name_for_error,
            "details": {"translation_warnings": [], "metadata_errors": [], "action_processing_results": [], "files_skipped_due_to_override": 0}
        }
        return jsonify(critical_error_response), 500
    except Exception as e:
        print(f"CRITICAL UNHANDLED ERROR in run_rule_endpoint for rule ID {rule_id} (Name: {rule_name_for_error}): {e}")
        import traceback
        traceback.print_exc()
        critical_error_response = {
            "success": False,
            "message": f"A critical server error occurred while trying to run rule '{rule_name_for_error}'. Error: {str(e)}",
            "rule_id": rule_id, "rule_name": rule_name_for_error,
            "details": {"translation_warnings": [], "metadata_errors": [], "action_processing_results": [], "files_skipped_due_to_override": 0}
        }
        return jsonify(critical_error_response), 500
    finally:
        if db_conn_manual_run:
            print(f"Manual run for rule '{rule_name_for_error}': Closing DB connection.")
            db_conn_manual_run.close()

@app.route('/run_all_rules_manual', methods=['POST'])
def run_all_rules_manual_endpoint():
    """
    Manually triggers the execution of all rules, respecting conflict overrides.
    Returns a summary of the execution.
    """
    print(f"\n--- Manual Trigger: Starting 'Run All Rules' at {datetime.now()} ---")
    
    db_conn = None
    all_rule_execution_summaries = []
    overall_success = True
    # Summary counters
    total_files_matched_by_search = 0
    total_files_action_attempted_on = 0
    total_files_added_successfully = 0
    total_files_forced_successfully = 0
    total_files_tag_action_success_on = 0
    total_files_rating_modified_successfully = 0
    total_files_skipped_due_to_override = 0
    total_rules_with_errors = 0
    changes_made_to_overrides_in_run = False

    try:
        db_conn = get_db_connection()
        print("Manual 'Run All Rules': Database connection for conflict overrides established.")

        rules = load_rules()
        current_settings = app.config['HYDRUS_SETTINGS'] # Use existing loaded settings

        if not current_settings.get('api_address') or not current_settings.get('api_key'):
            missing_parts = []
            if not current_settings.get('api_address'): missing_parts.append("API address")
            if not current_settings.get('api_key'): missing_parts.append("API key")
            message = f"Hydrus {', '.join(missing_parts)} is not configured. Cannot run rules."
            print(f"Manual 'Run All Rules': {message}")
            return jsonify({"success": False, "message": message, "results": []}), 400

        if not rules:
            message = "No rules defined. Nothing to run."
            print(f"Manual 'Run All Rules': {message}")
            return jsonify({"success": True, "message": message, "results": []}), 200

        print("Manual 'Run All Rules': Ensuring Hydrus services are available...")
        available_services_list = _ensure_available_services("Manual_Run_All")
        
        if not available_services_list:
            message = "CRITICAL - Could not fetch Hydrus services or service list is empty. Rule processing aborted."
            print(f"Manual 'Run All Rules': {message}")
            return jsonify({"success": False, "message": message, "results": []}), 503

        print(f"Manual 'Run All Rules': {len(available_services_list)} services available/cached.")

        for i, rule in enumerate(rules):
            rule_name_for_log = rule.get('name', rule.get('id', 'Unnamed'))
            print(f"\nManual 'Run All Rules': Executing Rule {i+1}/{len(rules)}: '{rule_name_for_log}' (Priority: {rule.get('priority')})")
            try:
                # Call _execute_rule_logic with is_manual_run=False to respect overrides
                execution_result = _execute_rule_logic(rule, db_conn, is_manual_run=False)
                all_rule_execution_summaries.append(execution_result)

                if not execution_result.get('success', True):
                    overall_success = False
                    total_rules_with_errors +=1
                
                # Aggregate stats
                total_files_matched_by_search += execution_result.get('files_matched_by_search', 0)
                total_files_action_attempted_on += execution_result.get('files_action_attempted_on', 0)
                total_files_added_successfully += execution_result.get('files_added_successfully', 0)
                total_files_forced_successfully += execution_result.get('files_forced_successfully', 0)
                total_files_tag_action_success_on += execution_result.get('files_tag_action_success_on', 0)
                total_files_rating_modified_successfully += execution_result.get('files_rating_modified_successfully', 0)
                total_files_skipped_due_to_override += execution_result.get('files_skipped_due_to_override', 0)
                
                # Check if this rule execution might have changed overrides
                if execution_result.get('success') or \
                   execution_result.get('files_forced_successfully', 0) > 0 or \
                   execution_result.get('files_rating_modified_successfully', 0) > 0:
                    changes_made_to_overrides_in_run = True


            except Exception as e:
                error_msg = f"Manual 'Run All Rules': An unexpected critical error occurred while processing rule '{rule_name_for_log}': {e}"
                print(error_msg)
                import traceback
                traceback.print_exc()
                all_rule_execution_summaries.append({
                    "success": False, "message": error_msg, 
                    "rule_id": rule.get('id'), "rule_name": rule_name_for_log,
                    "details": {"critical_error": str(e)}
                })
                overall_success = False
                total_rules_with_errors += 1
        
        if db_conn and changes_made_to_overrides_in_run:
            print("Manual 'Run All Rules': Committing changes to conflict overrides database.")
            db_conn.commit()
        
        final_summary_message = f"Manual 'Run All Rules' completed. Processed {len(rules)} rules. "
        final_summary_message += f"Overall success: {overall_success}. Rules with errors: {total_rules_with_errors}. "
        final_summary_message += f"Total files matched: {total_files_matched_by_search}, actions attempted: {total_files_action_attempted_on}, skipped by override: {total_files_skipped_due_to_override}."

        print(f"--- Manual Trigger: Finished 'Run All Rules' at {datetime.now()} ---")
        return jsonify({
            "success": overall_success,
            "message": final_summary_message,
            "results_per_rule": all_rule_execution_summaries,
            "summary_totals": {
                "rules_processed": len(rules),
                "rules_with_errors": total_rules_with_errors,
                "files_matched_by_search": total_files_matched_by_search,
                "files_action_attempted_on": total_files_action_attempted_on,
                "files_added_successfully": total_files_added_successfully,
                "files_forced_successfully": total_files_forced_successfully,
                "files_tag_action_success_on": total_files_tag_action_success_on,
                "files_rating_modified_successfully": total_files_rating_modified_successfully,
                "files_skipped_due_to_override": total_files_skipped_due_to_override
            }
        }), 200

    except sqlite3.Error as db_e:
        message = f"Manual 'Run All Rules': A database error occurred: {db_e}"
        print(message)
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "message": message, "results": []}), 500
    except Exception as global_e:
        message = f"Manual 'Run All Rules': An unexpected global error occurred: {global_e}"
        print(message)
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "message": message, "results": []}), 500
    finally:
        if db_conn:
            db_conn.close()
        print(f"--- Manual Trigger: 'Run All Rules' endpoint processing finished at {datetime.now()} ---")

@app.route('/static/<path:filename>')
def static_files(filename):
    """Serves static files."""
    return send_from_directory(os.path.join(BASE_DIR, 'static'), filename)

# --- App Setup and Startup ---
if __name__ == '__main__':
    # Ensure necessary directories and files exist
    static_path = os.path.join(BASE_DIR, 'static')
    if not os.path.exists(static_path): os.makedirs(static_path)
    templates_path = os.path.join(BASE_DIR, 'templates')
    if not os.path.exists(templates_path): os.makedirs(templates_path)

    # --- Load Settings (and generate key if needed) ---
    app_settings = load_settings()
    app.config['HYDRUS_SETTINGS'] = app_settings

    secret_key_hex = app_settings.get('secret_key')
    if secret_key_hex:
        try:
            app.secret_key = bytes.fromhex(secret_key_hex)
            print("Flask secret_key set from loaded settings.")
        except ValueError:
             print(f"CRITICAL ERROR: Could not convert secret_key '{secret_key_hex}' from hex to bytes. Flask sessions will not work correctly.")
             app.secret_key = os.urandom(24) 
             print("Set a temporary secret_key. Please check your settings file.")
    else:
        print("CRITICAL ERROR: No secret_key found or generated in settings. Flask sessions will not work correctly.")
        app.secret_key = os.urandom(24) 
        print("Set a temporary secret_key. Please check your settings file and permissions.")

    # --- Load Rules ---
    app.config['AUTOMATION_RULES'] = load_rules()
    
    # --- Initialize Conflict Overrides Database ---
    try:
        print("Attempting to initialize conflict overrides database...")
        init_conflict_db() 
        print("Conflict overrides database initialization process completed.")
    except Exception as e:
        print(f"FATAL: Failed to initialize conflict overrides database: {e}")
        print("Application will not start without a functional conflict overrides database.")
        sys.exit(1) 

    # Initialize and start the scheduler within the application context
    scheduler.init_app(app)
    
    APP_DEBUG_MODE = False
    # Determine if scheduler should start based on Werkzeug reloader
    # This logic helps prevent the scheduler from running twice in debug mode.
    run_scheduler = True
    if app.debug:
        # WERKZEUG_RUN_MAIN is set by the main Werkzeug process.
        # If it's not set, this is likely a child process spawned by the reloader.
        if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
            run_scheduler = False
            print("Flask reloader detected: Scheduler will NOT be started by this child process.")
        else:
            print("Flask reloader detected: Scheduler WILL be started by this main process.")
    
    if run_scheduler:
         print("Starting scheduler...")
         scheduler.start()
         print("Scheduler started.")

         # Initial service fetch on startup
         with app.app_context():
             print("Attempting to fetch Hydrus services on startup...")
             # Set a default empty list for AVAILABLE_SERVICES
             app.config['AVAILABLE_SERVICES'] = []
             
             # Only attempt to fetch services if API address is configured
             if app.config['HYDRUS_SETTINGS'].get('api_address'):
                 services_endpoint_result, services_endpoint_status = call_hydrus_api('/get_services')
                 
                 if services_endpoint_result.get("success") and isinstance(services_endpoint_result.get('data'), dict):
                      services_object = services_endpoint_result["data"].get('services')
                      if isinstance(services_object, dict):
                          services_list = []
                          for key, service_details in services_object.items():
                               if isinstance(service_details, dict):
                                    services_list.append({
                                        'service_key': key, 'name': service_details.get('name', 'Unnamed Service'),
                                        'type': service_details.get('type'), 'type_pretty': service_details.get('type_pretty', 'Unknown Type'),
                                         'star_shape': service_details.get('star_shape'), 'min_stars': service_details.get('min_stars'),
                                         'max_stars': service_details.get('max_stars'),
                                    })
                          app.config['AVAILABLE_SERVICES'] = services_list 
                          print(f"Successfully fetched and cached {len(app.config['AVAILABLE_SERVICES'])} services on startup.")
                      else:
                           print(f"Warning: Could not parse services object from /get_services response on startup. Using empty services list.")
                 elif services_endpoint_result.get("success") is False : # Explicitly check for False success
                      print(f"Warning: Failed to fetch Hydrus services on startup: {services_endpoint_result.get('message', 'Unknown API error')}. Using empty services list.")
                 else: # Success might be true but data malformed, or other unexpected cases
                      print(f"Warning: Unexpected response when fetching Hydrus services on startup. Status: {services_endpoint_status}, Result: {str(services_endpoint_result)[:200]}. Using empty services list.")
             else:
                 print("Warning: Hydrus API address not configured in settings. Skipping service fetch on startup. Using empty services list.")

             # Schedule the initial job based on settings
             # This should run regardless of whether services were fetched, as it depends on local settings.
             schedule_rules_job()
        # print("Running with Flask reloader or in a context where scheduler should not start. Scheduler not started by this process.")


    print("Starting Flask server on http://127.0.0.1:5556/")
    # Use debug=True only for development.
    # The threaded=True argument is generally good for development with a scheduler.
    # For production, consider a more robust setup (e.g., Gunicorn/uWSGI).
    app.run(
        host='127.0.0.1',
        port=5556,
        debug=APP_DEBUG_MODE,
        threaded=True,
        use_reloader=APP_DEBUG_MODE
    )
