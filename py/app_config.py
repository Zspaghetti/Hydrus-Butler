import os
import json
import secrets
import logging
# from functools import cmp_to_key # No longer needed

# Configure logging (can be more sophisticated later if needed)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
SETTINGS_FILE = os.path.join(BASE_DIR, 'settings.json')
RULES_FILE = os.path.join(BASE_DIR, 'rules.json')

DEFAULT_SETTINGS = {
    'api_address': 'http://localhost:45869',
    'api_key': '',
    'rule_interval_seconds': 0,
    'last_viewed_threshold_seconds': 3600,
    'secret_key': None,
    'show_run_notifications': True,
    'show_run_all_notifications': True,
    'theme': 'Default',
    'available_themes': ['Default'],
    'butler_name': 'Hydrus Butler',
    'log_overridden_actions': False
}

def _discover_themes():
    """Scans for available themes in the static/css directory."""
    available_themes_discovered = []
    themes_dir = os.path.join(BASE_DIR, 'static', 'css')
    if os.path.exists(themes_dir) and os.path.isdir(themes_dir):
        for filename in os.listdir(themes_dir):
            if filename.endswith('.css'):
                theme_name = filename[:-4]
                available_themes_discovered.append(theme_name)
        if not available_themes_discovered:
            available_themes_discovered.append('default') # Fallback if no CSS found
            logger.warning(f"No CSS files found in {themes_dir}. Defaulting to 'available_themes': ['default'].")
    else:
        logger.warning(f"Themes directory {themes_dir} not found. Defaulting to 'available_themes': ['default'].")
        available_themes_discovered.append('default')
    return sorted(list(set(available_themes_discovered)))

def load_settings():
    """
    Loads settings from file, merging with defaults.
    Generates and saves a new secret_key if one is missing.
    Scans for available themes.
    """
    logger.info("--- Loading settings ---")
    settings = {}
    settings_file_exists = os.path.exists(SETTINGS_FILE)

    if settings_file_exists:
        logger.info(f"Settings file exists: {SETTINGS_FILE}")
        try:
            with open(SETTINGS_FILE, 'r') as f:
                loaded_settings = json.load(f)
                if isinstance(loaded_settings, dict):
                    settings = loaded_settings
                    logger.info("Successfully loaded settings from file.")
                else:
                    logger.warning(f"Settings file {SETTINGS_FILE} contains non-dict data. Using default settings.")
                    settings_file_exists = False
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error loading settings from {SETTINGS_FILE}: {e}")
            settings = {}
            settings_file_exists = False
    else:
        logger.info(f"Settings file not found: {SETTINGS_FILE}. Using default settings.")

    key_generated = False
    if 'secret_key' not in settings or not settings['secret_key']:
        logger.info("Secret key not found or is empty. Generating a new one...")
        generated_key_bytes = secrets.token_bytes(24)
        settings['secret_key'] = generated_key_bytes.hex()
        key_generated = True
        logger.info("New secret key generated.")
    else:
        settings['secret_key'] = str(settings['secret_key'])

    discovered_themes = _discover_themes()
    settings['available_themes'] = discovered_themes

    final_settings = {**DEFAULT_SETTINGS, **settings} # Start with defaults, override with loaded/generated

    # Validate and sanitize specific settings
    if final_settings.get('theme') not in final_settings['available_themes']:
        logger.warning(f"Saved theme '{final_settings.get('theme')}' is not in available themes {final_settings['available_themes']}. Falling back to default '{DEFAULT_SETTINGS['theme']}'.")
        final_settings['theme'] = DEFAULT_SETTINGS['theme']
        if final_settings['theme'] not in final_settings['available_themes'] and final_settings['available_themes']:
            final_settings['theme'] = final_settings['available_themes'][0]
        elif not final_settings['available_themes']:
            final_settings['theme'] = 'default'

    try:
        final_settings['rule_interval_seconds'] = int(final_settings.get('rule_interval_seconds', DEFAULT_SETTINGS['rule_interval_seconds']))
    except (ValueError, TypeError):
        logger.warning("Invalid value for rule_interval_seconds. Using default.")
        final_settings['rule_interval_seconds'] = DEFAULT_SETTINGS['rule_interval_seconds']

    try:
        final_settings['last_viewed_threshold_seconds'] = int(final_settings.get('last_viewed_threshold_seconds', DEFAULT_SETTINGS['last_viewed_threshold_seconds']))
    except (ValueError, TypeError):
        logger.warning("Invalid value for last_viewed_threshold_seconds. Using default.")
        final_settings['last_viewed_threshold_seconds'] = DEFAULT_SETTINGS['last_viewed_threshold_seconds']

    if not isinstance(final_settings.get('show_run_notifications'), bool):
        logger.warning("Invalid value for show_run_notifications. Using default.")
        final_settings['show_run_notifications'] = DEFAULT_SETTINGS['show_run_notifications']

    if not isinstance(final_settings.get('show_run_all_notifications'), bool):
        logger.warning("Invalid value for show_run_all_notifications. Using default.")
        final_settings['show_run_all_notifications'] = DEFAULT_SETTINGS['show_run_all_notifications']
    
    if not isinstance(final_settings.get('log_overridden_actions'), bool):
        logger.warning("Invalid value for log_overridden_actions. Using default.")
        final_settings['log_overridden_actions'] = DEFAULT_SETTINGS['log_overridden_actions']    

    if not isinstance(final_settings.get('theme'), str):
        logger.warning(f"Invalid type for theme. Using default '{DEFAULT_SETTINGS['theme']}'.")
        final_settings['theme'] = DEFAULT_SETTINGS['theme']
        if final_settings['theme'] not in final_settings['available_themes'] and final_settings['available_themes']:
            final_settings['theme'] = final_settings['available_themes'][0]
        elif not final_settings['available_themes']:
            final_settings['theme'] = 'default'
            
    if not isinstance(final_settings.get('butler_name'), str) or not final_settings.get('butler_name').strip():
        logger.warning(f"Invalid or empty value for butler_name. Using default '{DEFAULT_SETTINGS['butler_name']}'.")
        final_settings['butler_name'] = DEFAULT_SETTINGS['butler_name']
    else:
        final_settings['butler_name'] = final_settings['butler_name'].strip()

    # Determine if the file needs to be saved
    should_save_file = (
        key_generated or
        not settings_file_exists or
        settings.get('available_themes') != final_settings['available_themes'] or
        settings.get('theme') != final_settings['theme'] or # If theme was reset
        'show_run_all_notifications' not in settings or # If new setting missing
        'butler_name' not in settings or final_settings['butler_name'] != settings.get('butler_name') or # Sanitized or new
        'log_overridden_actions' not in settings 
    )

    if should_save_file:
        logger.info("Saving settings file to persist changes (key, theme, available_themes, new setting, or new file).")
        try:
            with open(SETTINGS_FILE, 'w') as f:
                json.dump(final_settings, f, indent=4)
            logger.info(f"Settings file saved: {SETTINGS_FILE}")
        except IOError as e:
            logger.critical(f"Could not save settings file {SETTINGS_FILE}: {e}. Please check file permissions.")
            # Potentially raise or handle this more gracefully if it's critical for app start

    logger.info(f"Final processed settings: {final_settings}")
    logger.info("--- Finished loading settings ---")
    return final_settings

def save_settings_to_file(submitted_settings_data, current_app_config):
    logger.info("--- Saving settings (app_config.py) ---")
    logger.info(f"Received submitted_data: {submitted_settings_data}")

    # 1. Load current settings from disk (this applies defaults for missing keys)
    settings_on_disk = load_settings() # This load_settings already does validation and sanitization.
    settings_to_save = settings_on_disk.copy() # Start with a valid base

    # 2. Update with submitted values, carefully handling types
    
    # String values (strip them, API key only if new one provided)
    if 'api_address' in submitted_settings_data:
        settings_to_save['api_address'] = str(submitted_settings_data['api_address'] or '').strip()
    
    submitted_api_key = submitted_settings_data.get('api_key')
    if submitted_api_key: # Only update if a new, non-empty key is provided
        settings_to_save['api_key'] = submitted_api_key.strip()
    # If submitted_api_key is empty or None, settings_to_save['api_key'] retains its value from settings_on_disk

    if 'butler_name' in submitted_settings_data:
        butler_name_val = str(submitted_settings_data['butler_name'] or '').strip()
        settings_to_save['butler_name'] = butler_name_val if butler_name_val else DEFAULT_SETTINGS['butler_name']
    
    if 'theme' in submitted_settings_data and submitted_settings_data['theme'] in settings_to_save.get('available_themes', []):
        settings_to_save['theme'] = submitted_settings_data['theme']
    elif 'theme' in submitted_settings_data: # Submitted theme not available
        logger.warning(f"Submitted theme '{submitted_settings_data['theme']}' not in available themes. Keeping existing or default.")
        # settings_to_save['theme'] will retain its value from settings_on_disk

    # Integer values
    try:
        interval = submitted_settings_data.get('rule_interval_seconds')
        settings_to_save['rule_interval_seconds'] = int(interval) if interval is not None else DEFAULT_SETTINGS['rule_interval_seconds']
        if settings_to_save['rule_interval_seconds'] < 0: settings_to_save['rule_interval_seconds'] = 0
    except (ValueError, TypeError):
        logger.warning("Invalid value for rule_interval_seconds during save. Keeping existing or default.")
        settings_to_save['rule_interval_seconds'] = settings_on_disk.get('rule_interval_seconds', DEFAULT_SETTINGS['rule_interval_seconds'])

    try:
        threshold = submitted_settings_data.get('last_viewed_threshold_seconds')
        settings_to_save['last_viewed_threshold_seconds'] = int(threshold) if threshold is not None else DEFAULT_SETTINGS['last_viewed_threshold_seconds']
        if settings_to_save['last_viewed_threshold_seconds'] < 0: settings_to_save['last_viewed_threshold_seconds'] = 0
    except (ValueError, TypeError):
        logger.warning("Invalid value for last_viewed_threshold_seconds during save. Keeping existing or default.")
        settings_to_save['last_viewed_threshold_seconds'] = settings_on_disk.get('last_viewed_threshold_seconds', DEFAULT_SETTINGS['last_viewed_threshold_seconds'])
        
    # Boolean checkbox values
    # request.form.get('checkbox_name') in views.py returns "on" if checked, None if unchecked.
    settings_to_save['show_run_notifications'] = submitted_settings_data.get('show_run_notifications') is not None
    settings_to_save['show_run_all_notifications'] = submitted_settings_data.get('show_run_all_notifications') is not None
    settings_to_save['log_overridden_actions'] = submitted_settings_data.get('log_overridden_actions') is not None
    
    # Ensure 'secret_key' and 'available_themes' are preserved from the on-disk load
    settings_to_save['secret_key'] = settings_on_disk.get('secret_key') # Should always be there after load_settings
    settings_to_save['available_themes'] = settings_on_disk.get('available_themes', [DEFAULT_SETTINGS['theme']])


    # 3. Write to file
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings_to_save, f, indent=4)
        logger.info(f"Settings successfully written to file: {SETTINGS_FILE}")
        # Update live app config
        if current_app_config is not None:
            current_app_config['HYDRUS_SETTINGS'] = settings_to_save.copy() # Use a copy
            logger.info("Live app config HYDRUS_SETTINGS updated.")
        return True, settings_to_save
    except IOError as e:
        logger.error(f"Could not write settings to {SETTINGS_FILE}: {e}")
        return False, None


def _get_rule_sort_key(item_with_index):
    """
    Helper function to generate a sort key for a rule to determine its running order.
    Less important rules run first, allowing more important rules to override their effects.
    The 'priority' field from the UI is treated as 'importance_number' internally.

    Input: tuple (original_index, rule_dict)
    Output: tuple for sorting (importance_number, is_not_force_in, original_index)
    
    Sorting criteria (ascending for each component):
    1.  `importance_number`: (Derived from UI 'priority') Rules with a lower numerical `importance_number`
        are considered less important and run EARLIER. (e.g., Importance 1 runs before Importance 5).
        Default importance is 1 if not specified or invalid.
    2.  `is_not_force_in` (0 for 'force_in', 1 for others): If importance_numbers are the SAME,
        a rule with the `force_in` action type runs before other action types.
    3.  `original_index`: If importance_numbers and the `force_in` consideration are identical,
        rules run based on their original order in the `rules.json` file (lower index first).
    """
    original_index, rule = item_with_index
    try:
        # 'priority' from UI/JSON is treated as 'importance_number'. Lower value = lower importance.
        importance_number = int(rule.get('priority', 1)) # Default importance is 1
    except (ValueError, TypeError):
        importance_number = 1 # Default importance if invalid

    action_type = rule.get('action', {}).get('type', '')
    # 0 for 'force_in', 1 for other types. Sorts 'force_in' (0) earlier.
    is_not_force_in_flag = 0 if action_type == 'force_in' else 1

    return (importance_number, is_not_force_in_flag, original_index)


def _sort_rules_for_execution(rules_with_indices):
    """
    Sorts a list of rules (each with its original index) to determine their running order.
    The sorting uses `_get_rule_sort_key`.

    Input: list of tuples [(original_index, rule_dict), ...]
    Output: list of rule_dict, sorted for execution (running order).
    """
    if not rules_with_indices:
        return []
    
    # Use the custom sort key. Standard sort is ascending by tuple elements.
    sorted_items_with_indices = sorted(rules_with_indices, key=_get_rule_sort_key)
    
    # Extract just the rule dictionaries from the sorted list
    return [rule_dict for original_index, rule_dict in sorted_items_with_indices]


def load_rules():
    """
    Loads rules from file, ensures it's a list, and sorts them for execution (running order).
    The AUTOMATION_RULES in app.config will store this execution-sorted list.
    """
    logger.info(f"Loading rules from {RULES_FILE}")
    raw_rules = []
    if os.path.exists(RULES_FILE):
        try:
            with open(RULES_FILE, 'r') as f:
                loaded_data = json.load(f)
                if not isinstance(loaded_data, list):
                    logger.warning(f"Rules file {RULES_FILE} contains non-list data. Returning empty list.")
                    return []
                raw_rules = loaded_data
                logger.info(f"Successfully loaded {len(raw_rules)} rules from file before sorting.")
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error loading rules from {RULES_FILE}: {e}")
            return []
    else:
        logger.info(f"Rules file {RULES_FILE} not found. Returning empty list.")
        return []

    # Augment rules with their original index from the file
    rules_with_original_indices = []
    for i, rule in enumerate(raw_rules):
        if isinstance(rule, dict):
            rules_with_original_indices.append((i, rule))
        else:
            logger.warning(f"Skipping non-dictionary item at index {i} in rules file.")

    # Sort the rules for execution
    sorted_rules_for_execution = _sort_rules_for_execution(rules_with_original_indices)
    
    if sorted_rules_for_execution:
        log_msg_parts = []
        for idx_run, r_dict_sorted in enumerate(sorted_rules_for_execution): # Use a distinct name like r_dict_sorted
            # Find the original index of this sorted rule
            original_idx_found = 'N/A' # Default if not found (should not happen if logic is correct)
            for orig_idx, rule_orig_from_list in rules_with_original_indices:
                if rule_orig_from_list is r_dict_sorted: # Check object identity
                    original_idx_found = orig_idx
                    break
            
            log_msg_parts.append(
                f"'{r_dict_sorted.get('name', 'Unnamed')}'"
                f"(Imp:{r_dict_sorted.get('priority',1)}, " # 'priority' field is the source of importance
                f"OrigIdx:{original_idx_found}, "
                f"RunOrder:{idx_run})"
            )
        
        logger.info(f"Rules sorted for execution ({len(sorted_rules_for_execution)} total). Running order: {', '.join(log_msg_parts)}")
    else:
        logger.info("No rules to sort or all rules were invalid.")
        
    return sorted_rules_for_execution


def save_rules_to_file(rules_data, current_app_config):
    """
    Saves the provided rules_data (from UI/API) directly to rules.json to preserve user order.
    Then, sorts these rules for execution (running order) and updates the live app.config.
    """
    logger.info(f"Attempting to save {len(rules_data)} rules.")
    try:
        # Save rules_data as is to rules.json (preserves user's order)
        with open(RULES_FILE, 'w') as f:
            json.dump(rules_data, f, indent=4)
        logger.info(f"Successfully saved {len(rules_data)} rules to {RULES_FILE} (preserving user order).")

        # Now, prepare the execution-sorted version for app.config
        if current_app_config:
            # Augment with indices based on the current order in rules_data (which is the new original order)
            rules_with_current_indices = []
            for i, rule in enumerate(rules_data):
                 if isinstance(rule, dict):
                    rules_with_current_indices.append((i, rule))
                 else:
                    logger.warning(f"Skipping non-dictionary item during save_rules_to_file for app.config update: {rule}")
            
            execution_ordered_rules = _sort_rules_for_execution(rules_with_current_indices)
            current_app_config['AUTOMATION_RULES'] = execution_ordered_rules
            
            if execution_ordered_rules:
                log_msg_parts_live = []
                for idx_run, r_dict in enumerate(execution_ordered_rules):
                    original_idx_found = next((orig_idx for orig_idx, rule_orig in rules_with_current_indices if rule_orig is r_dict), 'N/A')
                    log_msg_parts_live.append(f"'{r_dict.get('name', 'Unnamed')}'(Imp:{r_dict.get('priority',1)}, OrigIdx:{original_idx_found}, RunOrder:{idx_run})")
                logger.info(f"Live app config AUTOMATION_RULES updated with {len(execution_ordered_rules)} execution-sorted rules. Running order: {', '.join(log_msg_parts_live)}")
            else:
                logger.info("Live app config AUTOMATION_RULES updated with an empty list (no valid rules after sorting).")

        return True
    except IOError as e:
        logger.error(f"Error saving rules to {RULES_FILE}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error saving rules: {e}", exc_info=True)
        return False