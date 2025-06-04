import os
import sqlite3
import json
import uuid
from datetime import datetime
import logging

# Configure logging
logger = logging.getLogger(__name__)

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
DB_DIR = os.path.join(BASE_DIR, 'db')
CONFLICT_DB_FILE = os.path.join(DB_DIR, 'conflict_overrides.db')

def init_conflict_db():
    """
    Initializes the database:
    - Creates the database directory if it doesn't exist.
    - Creates tables for conflict overrides and detailed execution logging,
      reflecting the new importance and rule action type logic.
    Assumes a clean database state or that existing tables conform to this schema.
    """
    logger.info("--- Initializing/Verifying Database (with importance logic) ---")
    conn = None
    try:
        if not os.path.exists(DB_DIR):
            os.makedirs(DB_DIR)
            logger.info(f"Created database directory: {DB_DIR}")

        conn = sqlite3.connect(CONFLICT_DB_FILE)
        cursor = conn.cursor()

        # --- 1. Conflict Overrides Table ---
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS overrides (
                file_hash TEXT NOT NULL,
                action_type TEXT NOT NULL,           -- "placement", "rating"
                action_key TEXT,                     -- NULL for "placement", rating_service_key for "rating"
                winning_rule_id TEXT NOT NULL,
                winning_rule_importance INTEGER NOT NULL, -- This field stores the importance of the winning rule
                winning_rule_action_type TEXT NOT NULL,   -- Stores the action.type of the winning rule (e.g., "add_to", "force_in")
                rating_value_set TEXT,                    -- Store rating value as JSON string (None, bool, int) for rating actions
                timestamp TEXT NOT NULL,                  -- ISO 8601 format
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
        ''')
        logger.info("Table 'overrides' initialized/verified.")

        # --- 2. Rule Versions Table ---
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS rule_versions (
                rule_version_id TEXT PRIMARY KEY,
                rule_id TEXT NOT NULL,
                rule_name_at_version TEXT NOT NULL,
                importance_at_version INTEGER NOT NULL, -- This field stores the importance of the rule at the time of this version
                conditions_json_at_version TEXT NOT NULL,
                action_json_at_version TEXT NOT NULL,
                version_timestamp TEXT NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_rule_versions_rule_id
            ON rule_versions (rule_id)
        ''')
        logger.info("Table 'rule_versions' initialized/verified.")

        # --- 3. Execution Runs Table ---
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS execution_runs (
                run_id TEXT PRIMARY KEY,
                run_type TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT,
                status TEXT NOT NULL,
                summary_message TEXT
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_execution_runs_start_time
            ON execution_runs (start_time)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_execution_runs_run_type
            ON execution_runs (run_type)
        ''')
        logger.info("Table 'execution_runs' initialized/verified.")

        # --- 4. Rule Executions In Run Table ---
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS rule_executions_in_run (
                rule_execution_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                rule_id TEXT NOT NULL,
                rule_version_id TEXT NOT NULL,
                execution_order_in_run INTEGER,
                start_time TEXT NOT NULL,
                end_time TEXT,
                status TEXT NOT NULL,
                matched_search_count INTEGER,
                eligible_for_action_count INTEGER,
                actions_attempted_count INTEGER,
                actions_succeeded_count INTEGER,
                summary_message_from_logic TEXT,
                details_json_from_logic TEXT,
                FOREIGN KEY (run_id) REFERENCES execution_runs (run_id) ON DELETE CASCADE,
                FOREIGN KEY (rule_version_id) REFERENCES rule_versions (rule_version_id) ON DELETE RESTRICT
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_rule_executions_run_id
            ON rule_executions_in_run (run_id)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_rule_executions_rule_id_version_id
            ON rule_executions_in_run (rule_id, rule_version_id)
        ''')
        logger.info("Table 'rule_executions_in_run' initialized/verified.")

        # --- 5. File Action Details Table ---
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS file_action_details (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_execution_id TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                action_type_performed TEXT NOT NULL,
                action_parameters_json_at_exec TEXT NOT NULL,
                status TEXT NOT NULL,
                error_message TEXT,
                override_info_json TEXT,
                action_timestamp TEXT NOT NULL,
                FOREIGN KEY (rule_execution_id) REFERENCES rule_executions_in_run (rule_execution_id) ON DELETE CASCADE
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_file_action_details_rule_exec_id
            ON file_action_details (rule_execution_id)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_file_action_details_file_hash
            ON file_action_details (file_hash)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_file_action_details_action_timestamp
            ON file_action_details (action_timestamp)
        ''')
        logger.info("Table 'file_action_details' initialized/verified.")

        conn.commit()
        logger.info(f"Database schema initialized/verified at {CONFLICT_DB_FILE}")
    except sqlite3.Error as e:
        logger.critical(f"CRITICAL ERROR initializing/verifying database schema: {e}")
        if conn:
            conn.rollback()
        raise
    except OSError as e:
        logger.critical(f"CRITICAL ERROR creating database directory {DB_DIR}: {e}")
        raise
    finally:
        if conn:
            conn.close()
        logger.info("--- Finished Initializing/Verifying Database ---")

def get_db_connection(db_file=CONFLICT_DB_FILE):
    """Establishes and returns a database connection."""
    try:
        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row # Access columns by name
        return conn
    except sqlite3.Error as e:
        logger.error(f"Error connecting to database {db_file}: {e}")
        raise

def get_or_create_active_rule_version(db_conn, rule_dict):
    """
    Gets the rule_version_id for the given rule_dict.
    If an identical version exists, its ID is returned. Otherwise, a new version is created.
    Uses 'importance_number' (from rule_dict's 'priority' field) for versioning.
    """
    if not rule_dict or not isinstance(rule_dict, dict):
        logger.error("Invalid rule_dict provided to get_or_create_active_rule_version.")
        return None

    rule_id = rule_dict.get('id')
    rule_name = rule_dict.get('name', 'Unnamed Rule')
    # 'priority' field from UI/JSON is the source for 'importance_number'
    importance_number_str = rule_dict.get('priority', '1') # Default to string '1' for consistent parsing
    conditions = rule_dict.get('conditions', [])
    action = rule_dict.get('action', {})

    if not rule_id:
        logger.error(f"Rule '{rule_name}' is missing an 'id' in get_or_create_active_rule_version.")
        return None
    if not isinstance(conditions, list):
        logger.error(f"Rule '{rule_name}' (ID: {rule_id}) has invalid 'conditions' (not a list).")
        return None
    if not isinstance(action, dict) or not action.get('type'):
        logger.error(f"Rule '{rule_name}' (ID: {rule_id}) has invalid 'action' (not dict or no type).")
        return None

    try:
        current_importance_number = int(importance_number_str)
    except (ValueError, TypeError):
        logger.warning(f"Rule '{rule_name}' (ID: {rule_id}) has invalid importance (priority) '{importance_number_str}'. Defaulting to 1 for versioning.")
        current_importance_number = 1 # Default importance

    try:
        conditions_json = json.dumps(conditions, sort_keys=True)
        action_json = json.dumps(action, sort_keys=True)
    except TypeError as e:
        logger.error(f"Error serializing conditions/action for rule '{rule_name}' (ID: {rule_id}): {e}")
        return None

    cursor = db_conn.cursor()
    # Query must also check importance_at_version if it's part of what defines a "version"
    # For now, assuming version is defined by id, conditions, action. Importance is an attribute of that version.
    cursor.execute('''
        SELECT rule_version_id FROM rule_versions
        WHERE rule_id = ? AND conditions_json_at_version = ? AND action_json_at_version = ? AND importance_at_version = ?
        ORDER BY version_timestamp DESC LIMIT 1
    ''', (rule_id, conditions_json, action_json, current_importance_number))
    existing_version = cursor.fetchone()

    if existing_version:
        return existing_version['rule_version_id']
    else:
        new_rule_version_id = str(uuid.uuid4())
        current_timestamp_iso = datetime.utcnow().isoformat() + "Z"
        
        logger.info(f"Creating new version for rule '{rule_name}' (ID: {rule_id}, Imp: {current_importance_number}). New Version ID: {new_rule_version_id}")
        cursor.execute('''
            INSERT INTO rule_versions (
                rule_version_id, rule_id, rule_name_at_version, importance_at_version,
                conditions_json_at_version, action_json_at_version, version_timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            new_rule_version_id, rule_id, str(rule_name), current_importance_number,
            conditions_json, action_json, current_timestamp_iso
        ))
        return new_rule_version_id
    return None # Fallback

def set_conflict_override(db_conn, file_hash, action_type, action_key_param, # Renamed param for clarity
                          winning_rule_id, winning_rule_importance, winning_rule_action_type_str,
                          rating_value_to_set=None, timestamp_dt=None):
    current_timestamp_iso = (timestamp_dt or datetime.utcnow()).isoformat() + "Z"
    rating_value_json = None
    if action_type == 'rating':
        try:
            rating_value_json = json.dumps(rating_value_to_set)
        except TypeError as e:
            logger.error(f"Error serializing rating_value_set '{rating_value_to_set}' to JSON: {e}")
            return False

    # Determine the effective action_key for the database
    effective_action_key = action_key_param
    if action_type == 'placement':
        effective_action_key = "" # Use a consistent non-NULL placeholder for placement
    elif action_type == 'rating' and action_key_param is None:
        logger.error(f"action_key_param cannot be None for set_conflict_override with action_type 'rating'. File: {file_hash}")
        return False # Or raise an error

    try:
        cursor = db_conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO overrides 
            (file_hash, action_type, action_key, winning_rule_id, 
             winning_rule_importance, winning_rule_action_type, 
             rating_value_set, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (file_hash, action_type, effective_action_key, winning_rule_id, 
              winning_rule_importance, winning_rule_action_type_str,
              rating_value_json, current_timestamp_iso))
        # logger.info(f"Set override for {file_hash}, type {action_type}, key '{effective_action_key}', rule {winning_rule_id[:8]}, imp {winning_rule_importance}. Rows affected: {cursor.rowcount}")
        return True # cursor.rowcount might be 0 for INSERT OR REPLACE if no change, but operation succeeds.
    except sqlite3.Error as e:
        logger.error(f"DB error in set_conflict_override for {file_hash}, {action_type}, {effective_action_key}: {e}")
        return False
        
        
def remove_overrides_for_rule(db_conn, rule_id):
    """Removes all conflict overrides established by a specific rule_id (winning_rule_id)."""
    if not rule_id:
        logger.warning("remove_overrides_for_rule called with no rule_id.")
        return 0
    try:
        cursor = db_conn.cursor()
        cursor.execute('DELETE FROM overrides WHERE winning_rule_id = ?', (rule_id,))
        deleted_rows = cursor.rowcount
        # logger.info(f"Removed {deleted_rows} overrides for winning_rule_id {rule_id}.")
        return deleted_rows
    except sqlite3.Error as e:
        logger.error(f"DB error in remove_overrides_for_rule for rule_id {rule_id}: {e}")
        return -1 # Indicate error
    except Exception as ex:
        logger.error(f"Unexpected error in remove_overrides_for_rule for rule_id {rule_id}: {ex}", exc_info=True)
        return -1        

def get_conflict_override(db_conn, file_hash, action_type, action_key_param=None):
    """
    Fetches a specific conflict override from the 'overrides' table.
    For 'placement' action_type, action_key_param being None is mapped to an empty string "" for DB query.
    For 'rating' action_type, action_key_param must be the specific rating service key.

    Returns: tuple (winning_rule_id, winning_rule_importance, winning_rule_action_type, rating_value_set_json_string) 
             if found, else None. Importance is returned as int.
    """
    cursor = db_conn.cursor()
    
    effective_action_key_for_query = action_key_param
    if action_type == "placement":
        # Use a consistent non-NULL placeholder for placement type overrides in the database.
        # This ensures that (file_hash, "placement", "") is the unique key.
        effective_action_key_for_query = "" 
    elif action_type == "rating":
        if action_key_param is None:
            logger.error(f"action_key_param cannot be None for get_conflict_override with action_type 'rating'. File: {file_hash}")
            return None
        # For rating, effective_action_key_for_query remains action_key_param (the service key)
    else:
        logger.error(f"Unsupported action_type '{action_type}' in get_conflict_override. File: {file_hash}")
        return None

    # The SQL query is now the same structure for both, relying on effective_action_key_for_query
    sql = """
        SELECT winning_rule_id, winning_rule_importance, winning_rule_action_type, rating_value_set
        FROM overrides
        WHERE file_hash = ? AND action_type = ? AND action_key = ?; 
    """
    params = (file_hash, action_type, effective_action_key_for_query)

    try:
        # logger.debug(f"Executing get_conflict_override SQL: {sql} with params: {params}")
        cursor.execute(sql, params)
        row = cursor.fetchone()
        if row:
            importance_val = row['winning_rule_importance']
            try:
                # Ensure importance is consistently an integer for comparisons
                importance_int = int(importance_val) 
            except (ValueError, TypeError) as e:
                logger.error(f"Could not convert winning_rule_importance '{importance_val}' to int for override on {file_hash}, type {action_type}, key '{effective_action_key_for_query}'. Error: {e}")
                return None 

            # logger.debug(f"Get override for {file_hash}, type {action_type}, key '{effective_action_key_for_query}'. Found: Rule {row['winning_rule_id'][:8]}, Imp {importance_int}, Type {row['winning_rule_action_type']}")
            return (row['winning_rule_id'], importance_int, row['winning_rule_action_type'], row['rating_value_set'])
        else:
            # logger.debug(f"Get override for {file_hash}, type {action_type}, key '{effective_action_key_for_query}'. Found: None")
            return None
    except sqlite3.Error as e:
        logger.error(f"DB Error in get_conflict_override for {file_hash}, type {action_type}, key '{effective_action_key_for_query}': {e}")
        return None
    except Exception as ex: 
        logger.error(f"Unexpected error in get_conflict_override for {file_hash}, type {action_type}, key '{effective_action_key_for_query}': {ex}", exc_info=True)
        return None

def remove_specific_override(db_conn, file_hash, action_type, action_key=None):
    """Removes a single, specific conflict override from the database."""
    try:
        cursor = db_conn.cursor()
        if action_key is None:
            cursor.execute('''
                DELETE FROM overrides
                WHERE file_hash = ? AND action_type = ? AND action_key IS NULL
            ''', (file_hash, action_type))
        else:
            cursor.execute('''
                DELETE FROM overrides
                WHERE file_hash = ? AND action_type = ? AND action_key = ?
            ''', (file_hash, action_type, action_key))
        deleted_rows = cursor.rowcount
        return deleted_rows
    except sqlite3.Error as e:
        logger.error(f"DB error in remove_specific_override for {file_hash}, {action_type}, {action_key}: {e}")
        return -1

def log_file_action_detail(db_conn, rule_execution_id, file_hash,
                           action_type_performed, action_parameters_json,
                           status, error_message=None, override_info_json=None,
                           timestamp_dt=None):
    """Logs the details of an action performed (or attempted) on a single file."""
    if not all([db_conn, rule_execution_id, file_hash, action_type_performed]) or action_parameters_json is None:
        logger.error(f"Missing critical params in log_file_action_detail. RuleExecID: {rule_execution_id}, FileHash: {file_hash}, ActionType: {action_type_performed}")
        return

    action_timestamp_iso = (timestamp_dt if timestamp_dt else datetime.utcnow()).isoformat() + "Z"
    try:
        cursor = db_conn.cursor()
        cursor.execute('''
            INSERT INTO file_action_details (
                rule_execution_id, file_hash, action_type_performed,
                action_parameters_json_at_exec, status, error_message,
                override_info_json, action_timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            rule_execution_id, file_hash, action_type_performed,
            action_parameters_json, status, error_message,
            override_info_json, action_timestamp_iso
        ))
    except sqlite3.Error as e:
        logger.error(f"DB Error in log_file_action_detail for RuleExecID {rule_execution_id}, File {file_hash}: {e}")
    except Exception as e_gen:
        logger.error(f"General Error in log_file_action_detail for RuleExecID {rule_execution_id}, File {file_hash}: {e_gen}")