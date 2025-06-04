import json
import uuid
import math
import traceback
from datetime import datetime, timedelta
from urllib.parse import unquote
import logging
import sqlite3 # Added for specific exception handling in execute_single_rule

from hydrus_interface import call_hydrus_api
from database import (
    get_or_create_active_rule_version,
    get_conflict_override, set_conflict_override, # TODO: Update signatures/behavior of these functions
    log_file_action_detail
)
# We'll need to pass app_config or specific settings to functions that need them.

logger = logging.getLogger(__name__)

# --- Hydrus Butler Rule Logic Explanation ---
# (DONT DELETE )

# Running order:
# Rules are processed in an order determined by their 'importance_number' and action type.
# This order is determined globally before a "Run All Rules" job begins.
# 1. importance_number (ascending): Rules with a lower importance_number are attempted first.
#    (This value comes from the 'priority' field in the UI and rules.json, where a lower number means lower importance).
# 2. action.type == 'force_in': If importance_numbers are the same, 'force_in' rules are attempted before other types.
# 3. Original rule order: If importance and force_in consideration are identical, rules are attempted
#    based on their original order (e.g., in rules.json, lower index first).
# This means less important rules run first, allowing more important rules to override their effects if they
# target the same file for a conflicting action. The "last word" belongs to the most important rule.

# Importance number:
# This is a value provided by the user (UI field: 'priority', default: 1).
# - It primarily determines the running_order (see above): lower importance rules run earlier.
# - It determines the "winning" rule in case of conflict: the rule with the highest importance_number
#   that successfully processes the file for a given conflict type (e.g., "placement", "rating")
#   is generally considered the winner. Special handling exists for 'force_in' vs 'add_to' interactions
#   to ensure both actions can occur while the override database reflects the most important rule's influence
#   or maintains the win of a more important 'add_to' rule even if a less important 'force_in' also acts.

# --- Helper Functions (many previously in app.py) ---

def _get_rule_by_id(rule_id_to_find, rules_list):
    """Finds a rule dictionary from a list by its ID."""
    if not rule_id_to_find or not isinstance(rules_list, list):
        return None
    return next((rule for rule in rules_list if isinstance(rule, dict) and rule.get('id') == rule_id_to_find), None)

def create_default_details():
    """Creates a dictionary with default values for rule execution details."""
    return {
        "translation_warnings": [],
        "action_tag_service_key_used_for_search": None,
        "files_skipped_due_to_recent_view": 0,
        "files_skipped_due_to_override": 0,
        "metadata_errors": [],
        "action_processing_results": [],
        "critical_error": None,
        "critical_error_traceback_summary": None,
    }

def is_critical_warning(warning_message):
    """Determines if a translation warning is critical."""
    msg_lower = warning_message.lower()
    if "note:" in msg_lower:
        return False
    critical_phrases = [
        "skipping condition", "unhandled condition", "invalid value", "malformed 'file_service' condition",
        "not found for condition", "missing", "error translating", "unsupported operator for", "unknown specific url type"
    ]
    return any(phrase in msg_lower for phrase in critical_phrases)

def _ensure_available_services(app_config, rule_name_for_log):
    """
    Ensures Hydrus services list is loaded, fetching if necessary.
    Uses app_config for HYDRUS_SETTINGS and to store AVAILABLE_SERVICES.
    """
    available_services_cache = app_config.get('AVAILABLE_SERVICES')
    if isinstance(available_services_cache, list) and available_services_cache:
        return available_services_cache

    log_prefix = f"Rule '{rule_name_for_log}'" if rule_name_for_log else "EnsureServices"
    logger.info(f"{log_prefix}: Available services cache empty or invalid. Attempting to fetch.")

    settings = app_config.get('HYDRUS_SETTINGS', {})
    api_address = settings.get('api_address')
    api_key = settings.get('api_key')

    if not api_address:
        logger.warning(f"{log_prefix}: Hydrus API address not configured. Cannot fetch services.")
        app_config['AVAILABLE_SERVICES'] = []
        return []

    services_result, _ = call_hydrus_api(api_address, api_key, '/get_services')

    if services_result.get("success"):
        services_data = services_result.get('data')
        if isinstance(services_data, dict):
            services_object = services_data.get('services')
            if isinstance(services_object, dict):
                services_list = []
                for key, details in services_object.items():
                    if isinstance(details, dict):
                        services_list.append({
                            'service_key': key, 'name': details.get('name', 'Unnamed Service'),
                            'type': details.get('type'), 'type_pretty': details.get('type_pretty', 'Unknown Type'),
                            'star_shape': details.get('star_shape'), 'min_stars': details.get('min_stars'),
                            'max_stars': details.get('max_stars'),
                        })
                    else:
                        logger.warning(f"{log_prefix}: Service details for key '{key}' not a dict. Skipping.")
                app_config['AVAILABLE_SERVICES'] = services_list
                logger.info(f"{log_prefix}: Fetched and cached {len(services_list)} services.")
                return services_list
            else:
                logger.error(f"{log_prefix} failed: 'services' object not a dict. Data: {str(services_data)[:500]}")
        else:
            logger.error(f"{log_prefix} failed: 'data' field not a dict. Result: {str(services_result)[:500]}")
    else:
        logger.error(f"{log_prefix} failed: API call /get_services: {services_result.get('message', 'Unknown API error')}")

    app_config['AVAILABLE_SERVICES'] = []
    return []

def _fetch_metadata_for_hashes(app_config, rule_name_for_log, hashes_list, batch_size=256):
    """Fetches metadata for file hashes in batches."""
    all_files_metadata = []
    metadata_errors_list = []
    num_hashes = len(hashes_list)

    if num_hashes == 0:
        return [], []

    logger.info(f"Rule '{rule_name_for_log}': Fetching metadata for {num_hashes} files (batch size {batch_size}).")
    settings = app_config.get('HYDRUS_SETTINGS', {})
    api_address = settings.get('api_address')
    api_key = settings.get('api_key')

    if not api_address: # Should have been checked earlier, but good safeguard
        logger.error(f"Rule '{rule_name_for_log}': API address not set for metadata fetch.")
        return [], [{"message": "API address not configured.", "hashes_in_batch": hashes_list, "status_code": None}]


    for i in range(0, num_hashes, batch_size):
        batch_hashes = hashes_list[i : i + batch_size]
        params = {
            'hashes': json.dumps(batch_hashes),
            'include_services_object': json.dumps(True)
        }
        result, status = call_hydrus_api(api_address, api_key, '/get_files/file_metadata', params=params)

        if result.get("success") and isinstance(result.get('data'), dict):
            batch_metadata = result.get('data', {}).get('metadata', [])
            all_files_metadata.extend(batch_metadata)
        else:
            msg = f"Metadata fetch failed for a batch: {result.get('message', 'Unknown API error')}"
            logger.warning(f"Rule '{rule_name_for_log}': {msg}")
            metadata_errors_list.append({"message": msg, "hashes_in_batch": batch_hashes, "status_code": status})

    logger.info(f"Rule '{rule_name_for_log}': Metadata fetch complete. Retrieved for {len(all_files_metadata)} of {num_hashes} files.")
    if metadata_errors_list:
        logger.warning(f"Rule '{rule_name_for_log}': {len(metadata_errors_list)} metadata fetch errors.")
    return all_files_metadata, metadata_errors_list

def _parse_time_range_for_logs(args):
    """
    Parses time frame parameters (e.g., '24h', '1w', custom 'start_date', 'end_date')
    from Flask request.args into ISO 8601 datetime strings suitable for database queries.
    """
    time_frame = args.get('time_frame', '1w') # Default to 1 week
    start_date_str = args.get('start_date')
    end_date_str = args.get('end_date')

    now = datetime.utcnow()
    end_dt = now # Default end is now
    time_frame_used_for_response = time_frame # Store the initial or determined time_frame label

    if start_date_str: # Custom date range takes precedence
        try:
            # Handle URL encoded '+' for timezone, or 'Z'
            start_date_str_decoded = unquote(start_date_str)
            if 'T' in start_date_str_decoded: # Full ISO string likely
                start_dt = datetime.fromisoformat(start_date_str_decoded.replace('Z', '+00:00'))
            else: # Assume YYYY-MM-DD, set to start of day UTC
                start_dt = datetime.strptime(start_date_str_decoded, '%Y-%m-%d').replace(hour=0, minute=0, second=0, microsecond=0)

            if end_date_str:
                end_date_str_decoded = unquote(end_date_str)
                if 'T' in end_date_str_decoded: # Full ISO string likely
                    end_dt = datetime.fromisoformat(end_date_str_decoded.replace('Z', '+00:00'))
                else: # Assume YYYY-MM-DD, set to end of day UTC
                    end_dt = datetime.strptime(end_date_str_decoded, '%Y-%m-%d').replace(hour=23, minute=59, second=59, microsecond=999999)
            else: # If start_date is given but no end_date, end_date is now
                end_dt = now # Which is already set
            time_frame_used_for_response = "custom"
        except ValueError:
            logger.warning(f"Invalid custom date format. Falling back to default time_frame '{time_frame}'. Dates: {start_date_str}, {end_date_str}")
            # Fallback to default time_frame if parsing fails
            time_frame = '1w' # Reset to default '1w' or some other sensible default
            start_dt = now - timedelta(weeks=1)
            end_dt = now
            time_frame_used_for_response = time_frame # Update to actual used frame

    elif time_frame == '24h':
        start_dt = now - timedelta(hours=24)
        time_frame_used_for_response = "24h"
    elif time_frame == '3d':
        start_dt = now - timedelta(days=3)
        time_frame_used_for_response = "3d"
    elif time_frame == '1w':
        start_dt = now - timedelta(weeks=1)
        time_frame_used_for_response = "1w"
    elif time_frame == '1m':
        start_dt = now - timedelta(days=30) # Approx 1 month
        time_frame_used_for_response = "1m"
    elif time_frame == '6m':
        start_dt = now - timedelta(days=180) # Approx 6 months
        time_frame_used_for_response = "6m"
    elif time_frame == '1y':
        start_dt = now - timedelta(days=365) # Approx 1 year
        time_frame_used_for_response = "1y"
    elif time_frame == 'all':
        start_dt = datetime.min # Represents earliest possible time
        time_frame_used_for_response = "all"
    else: # Default / unrecognized time_frame
        logger.warning(f"Unrecognized time_frame '{time_frame}'. Defaulting to '1w'.")
        start_dt = now - timedelta(weeks=1)
        time_frame_used_for_response = "1w" # Use the actual default applied

    # Convert to ISO strings suitable for SQLite TEXT comparison (assuming stored as UTC 'Z' format)
    # For 'all' time, datetime.min is used.
    start_iso = start_dt.isoformat() + "Z" if time_frame_used_for_response != 'all' else (datetime.min.isoformat() + "Z")
    end_iso = end_dt.isoformat() + "Z" # end_dt is always a specific datetime

    return start_iso, end_iso, time_frame_used_for_response

def _translate_rule_to_hydrus_predicates(rule_conditions_list, rule_action_obj,
                                         available_services_list, rule_name_for_log):
    """
    Translates rule conditions into Hydrus API search predicates.
    (Logic largely unchanged, but removed last_viewed_threshold_seconds as it's applied post-search)
    """
    string_predicates = []
    translation_warnings = []
    action_tag_service_key_for_search = None

    def get_service_details(service_key):
        if not isinstance(available_services_list, list):
            # This should be caught by _ensure_available_services earlier
            logger.critical(f"Rule '{rule_name_for_log}': available_services_list not a list in get_service_details. This is a program flow error.")
            return None
        return next((s for s in available_services_list if isinstance(s, dict) and s.get('service_key') == service_key), None)

    def translate_single_condition_inner(condition, warnings_list_ref):
        # It translates individual conditions (tags, rating, file_service, etc.)
        # into Hydrus predicate strings.
        # IMPORTANT: Ensure all logger calls inside this function use `logger.warning`, `logger.info` etc.
        # and refer to `rule_name_for_log`.
        condition_type = condition.get('type')
        url_subtype = condition.get('url_subtype')
        specific_url_type = condition.get('specific_type')
        operator = condition.get('operator')
        value = condition.get('value')
        condition_service_key = condition.get('service_key') # This is for 'rating' type
        unit = condition.get('unit')

        predicate_string = None
        warning_msg = None

        try:
            if condition_type == 'tags' and operator == 'search_terms' and isinstance(value, list):
                if value:
                    return value # Returns a list of tags, not a single predicate string
                else:
                    warning_msg = f"Warning: Empty tags list in condition. Skipping condition."

            elif condition_type == 'rating' and condition_service_key and operator:
                service_info = get_service_details(condition_service_key)
                if not service_info:
                    warning_msg = f"Warning: Rating service with key {condition_service_key} not found. Skipping condition."
                else:
                    service_name = service_info['name']
                    service_type = service_info.get('type')
                    max_stars = service_info.get('max_stars')

                    if operator == 'no_rating' and value is None: # Explicitly check value is None for no_rating
                        predicate_string = f"system:no rating for {service_name}"
                    elif operator == 'has_rating' and value is None: # Explicitly check value is None for has_rating
                        predicate_string = f"system:has a rating for {service_name}"
                    elif service_type == 7: # Like/Dislike
                        predicate_base_for_rating = f"system:rating for {service_name}"
                        if operator == 'is':
                            if isinstance(value, bool):
                                keyword = 'like' if value is True else 'dislike'
                                predicate_string = f"{predicate_base_for_rating} is {keyword}"
                            else:
                                warning_msg = f"Warning: Unsupported value type '{type(value).__name__}' for 'is' on like/dislike rating '{service_name}'. Expected boolean. Skipping condition."
                        else:
                            warning_msg = f"Warning: Unsupported operator '{operator}' for like/dislike rating '{service_name}' (excluding 'no_rating', 'has_rating'). Skipping condition."
                    elif service_type == 6: # Numerical Stars
                        predicate_base_for_rating = f"system:rating for {service_name}"
                        if isinstance(value, (int, float)):
                            numeric_value = int(value) # Hydrus predicates typically use integers for star counts
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
                                less_than_pred = f"{predicate_base_for_rating} < {numeric_value}"
                                more_than_pred = f"{predicate_base_for_rating} > {numeric_value}"
                                if max_stars is not None and max_stars > 0:
                                    less_than_pred += f"/{max_stars}"
                                    more_than_pred += f"/{max_stars}"
                                predicate_string = [less_than_pred, more_than_pred] # Return as a list for OR group
                                warnings_list_ref.append(f"Note: Numerical rating '!=' for '{service_name}' translated to OR group: [{less_than_pred}, {more_than_pred}].")
                            else:
                                warning_msg = f"Warning: Unsupported operator '{operator}' for numerical rating '{service_name}'. Skipping condition."
                        else:
                            warning_msg = f"Warning: Invalid value '{value}' for numerical rating '{service_name}'. Expected number. Skipping condition."
                    elif service_type == 22: # Increment/Decrement
                        predicate_base_for_rating = f"system:rating for {service_name}"
                        if isinstance(value, (int, float)):
                            numeric_value = int(value)
                            if operator == 'is': predicate_string = f"{predicate_base_for_rating} = {numeric_value}"
                            elif operator == 'more_than': predicate_string = f"{predicate_base_for_rating} > {numeric_value}"
                            elif operator == 'less_than': predicate_string = f"{predicate_base_for_rating} < {numeric_value}"
                            elif operator == '!=':
                                less_than_pred = f"{predicate_base_for_rating} < {numeric_value}"
                                more_than_pred = f"{predicate_base_for_rating} > {numeric_value}"
                                predicate_string = [less_than_pred, more_than_pred] # Return as a list for OR group
                                warnings_list_ref.append(f"Note: Inc/dec rating '!=' for '{service_name}' translated to OR group: [{less_than_pred}, {more_than_pred}].")
                            else: warning_msg = f"Warning: Unsupported operator '{operator}' for inc/dec rating '{service_name}'. Skipping condition."
                        else: warning_msg = f"Warning: Invalid value '{value}' for inc/dec rating '{service_name}'. Expected number. Skipping condition."
            elif condition_type == 'file_service':
                if value and operator in ['is_in', 'is_not_in']: # 'value' here is the service key
                    service_info = get_service_details(value) # 'value' is the service key
                    if not service_info:
                        warning_msg = f"Warning: File service key '{value}' (from 'value' field) not found for 'file_service' condition. Skipping condition."
                    else:
                        service_name_for_predicate = service_info['name']
                        if operator == 'is_in':
                            predicate_string = f"system:file service currently in {service_name_for_predicate}"
                        else: # is_not_in
                            predicate_string = f"system:file service is not currently in {service_name_for_predicate}"
                else:
                    details_for_log = []
                    if not value: details_for_log.append("missing service key (expected in 'value' field)")
                    if operator not in ['is_in', 'is_not_in']:
                        details_for_log.append(f"unexpected operator '{operator}' (expected 'is_in' or 'is_not_in')")
                    if details_for_log:
                        warning_msg = f"Warning: Malformed 'file_service' condition ({', '.join(details_for_log)}). Skipping condition."
                    else:
                        warning_msg = f"Warning: Unhandled 'file_service' condition variant. Skipping condition."

            elif condition_type == 'filesize' and operator and value is not None and unit:
                 hydrus_operator_map = { '=': '~=', '>': '>', '<': '<', '!=': '≠' }
                 hydrus_op = hydrus_operator_map.get(operator)
                 if not hydrus_op:
                     warning_msg = f"Warning: Unsupported filesize operator '{operator}'. Using direct symbol. Skipping condition."
                 hydrus_unit_map = { 'bytes': 'B', 'KB': 'kilobytes', 'MB': 'megabytes', 'GB': 'GB'}
                 hydrus_unit_str = hydrus_unit_map.get(unit)
                 if not hydrus_unit_str:
                     warning_msg = f"Warning: Invalid filesize unit '{unit}'. Skipping condition."
                 elif warning_msg:
                     pass
                 else:
                    try:
                        size_val = float(value)
                        formatted_size_val = int(size_val) if size_val == int(size_val) else size_val
                        predicate_string = f"system:filesize {hydrus_op} {formatted_size_val} {hydrus_unit_str}"
                        if operator == '!=':
                             warnings_list_ref.append(f"Note: Filesize '!=' translated to Hydrus '≠'.")
                    except (ValueError, TypeError) as e:
                        warning_msg = f"Warning: Invalid filesize value '{value}': {e}. Skipping condition."

            elif condition_type == 'boolean' and operator and isinstance(value, bool):
                positive_forms = {
                    'inbox': 'system:inbox', 'archive': 'system:archive',
                    'local': 'system:file service currently in all local files',
                    'trashed': 'system:file service currently in trash',
                    'deleted': 'system:is deleted',
                    'has_duration': 'system:has duration',
                    'is_the_best_quality_file_of_its_duplicate_group': 'system:is the best quality file of its duplicate group',
                    'has_audio': 'system:has audio', 'has_exif': 'system:has exif',
                    'has_embedded_metadata': 'system:has embedded metadata',
                    'has_icc_profile': 'system:has icc profile',
                    'has_tags': 'system:has tags',
                    'has_notes': 'system:has notes',
                    'has_transparency': 'system:has transparency',
                }
                negative_forms = {
                    'inbox': '-system:inbox', 'archive': '-system:archive',
                    'local': 'system:file service is not currently in all local files',
                    'trashed': 'system:file service is not currently in trash',
                    'deleted': '-system:is deleted',
                    'has_duration': 'system:no duration',
                    'is_the_best_quality_file_of_its_duplicate_group': 'system:is not the best quality file of its duplicate group',
                    'has_audio': 'system:no audio', 'has_exif': 'system:no exif',
                    'has_embedded_metadata': 'system:no embedded metadata',
                    'has_icc_profile': 'system:no icc profile',
                    'has_tags': 'system:no tags',
                    'has_notes': 'system:does not have notes',
                    'has_transparency': '-system:has transparency',
                }
                if value is True:
                    if operator in positive_forms: predicate_string = positive_forms[operator]
                    else: warning_msg = f"Warning: Boolean operator '{operator}' (for TRUE) has no direct positive mapping. Skipping."
                else: # value is False
                    if operator in negative_forms:
                        predicate_string = negative_forms[operator]
                        if operator == 'has_tags' and predicate_string == 'system:no tags':
                            warnings_list_ref.append("Note: 'has_tags is false' mapped to 'system:no tags'. 'system:untagged' is also an option.")
                        if operator == 'has_notes' and predicate_string == 'system:does not have notes':
                             warnings_list_ref.append("Note: 'has_notes is false' mapped to 'system:does not have notes'. Hydrus list also has 'system:no notes'.")
                    elif operator in positive_forms:
                        predicate_string = f"-{positive_forms[operator]}"
                        warnings_list_ref.append(f"Note: Boolean operator '{operator}' (for FALSE) negated generically as '{predicate_string}'.")
                    else: warning_msg = f"Warning: Boolean operator '{operator}' (for FALSE) has no mapping. Skipping."
            elif condition_type == 'boolean' and operator and not isinstance(value, bool):
                warning_msg = f"Warning: Invalid value type '{type(value).__name__}' for boolean condition '{operator}'. Expected boolean. Skipping."

            elif condition_type == 'filetype' and operator in ['is', 'is_not'] and isinstance(value, list) and value:
                 processed_values = [str(v).strip().lower() for v in value]
                 values_string = ", ".join(processed_values)
                 if operator == 'is': predicate_string = f"system:filetype = {values_string}"
                 elif operator == 'is_not':
                     predicate_string = f"system:filetype is not {values_string}"
                     if len(processed_values) > 1:
                         warnings_list_ref.append(f"Note: 'filetype is not {values_string}'. Check Hydrus behavior for multiple types with 'is not'.")
                 else: warning_msg = f"Warning: Unexpected operator '{operator}' for filetype. Skipping."
            elif condition_type == 'filetype' and (not isinstance(value, list) or not value):
                 warning_msg = f"Warning: 'filetype' condition requires a non-empty list of values. Skipping."

            elif condition_type == 'url' and url_subtype:
                url_value_str = str(value).strip() if value is not None else None
                if url_subtype == 'specific' and specific_url_type and operator in ['is', 'is_not'] and url_value_str:
                    negation_prefix = "does not have "
                    if specific_url_type == 'regex' and operator == 'is_not': negation_prefix = "does not have a "
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
                    details_msg_parts = [f"Subtype: {url_subtype or 'N/A'}"]
                    if url_subtype == 'specific': details_msg_parts.append(f"SpecificType: {specific_url_type or 'N/A'}")
                    details_msg_parts.append(f"Operator: {operator or 'N/A'}")
                    if url_subtype in ['specific', 'count']: details_msg_parts.append(f"Value: {value if value is not None else 'N/A'} (Type: {type(value).__name__})")
                    warning_msg = f"Warning: Incomplete/invalid URL condition. Details: {', '.join(details_msg_parts)}. Skipping."

            elif condition_type == 'paste_search':
                warning_msg = "Dev Error: 'paste_search' type unexpectedly reached translate_single_condition_inner."
            elif condition_type:
                warning_msg = f"Warning: Unhandled condition type '{condition_type}'. Skipping."
            else:
                warning_msg = "Warning: Condition has no type. Skipping."
        except Exception as e:
            warning_msg = f"Warning: Error translating condition '{str(condition)[:100]}...': {e}. Skipping."
            logger.error(f"Rule '{rule_name_for_log}': {warning_msg}", exc_info=True) # Log with traceback for unexpected errors

        if warning_msg:
            ws_ref_is_list = isinstance(warnings_list_ref, list)
            if ws_ref_is_list:
                 warnings_list_ref.append(f"Cond (type: {condition.get('type','N/A')}, op: {condition.get('operator','N/A')}): {warning_msg}")
            else:
                 logger.critical(f"Rule '{rule_name_for_log}': CRITICAL - warnings_list_ref is not a list in translate_single_condition_inner.")
        return predicate_string

    # Main loop for _translate_rule_to_hydrus_predicates 
    for condition_idx, condition in enumerate(rule_conditions_list):
        if not isinstance(condition, dict):
            translation_warnings.append(f"Warning: Cond at idx {condition_idx} not dict. Skipping: {str(condition)[:100]}")
            continue
        condition_type = condition.get('type')
        if condition_type == 'or_group':
            nested_conditions_data = condition.get('conditions', [])
            if not isinstance(nested_conditions_data, list) or not nested_conditions_data:
                translation_warnings.append(f"Warning: OR group idx {condition_idx} empty/invalid. Skipping.")
                continue
            nested_predicate_list = []
            for nested_cond_idx, nested_cond in enumerate(nested_conditions_data):
                if not isinstance(nested_cond, dict) or nested_cond.get('type') in ['or_group', 'paste_search']:
                    translation_warnings.append(f"Warning: Invalid nested item in OR group (idx {condition_idx}, nested_idx {nested_cond_idx}). Skipping nested.")
                    continue
                nested_res = translate_single_condition_inner(nested_cond, translation_warnings)
                if nested_res:
                    if isinstance(nested_res, list): nested_predicate_list.extend(nested_res)
                    else: nested_predicate_list.append(nested_res)
            if nested_predicate_list: string_predicates.append(nested_predicate_list)
            else: translation_warnings.append(f"Warning: OR group idx {condition_idx} yielded no predicates.")
        elif condition_type == 'paste_search':
            raw_text = condition.get('value')
            if not isinstance(raw_text, str) or not raw_text.strip():
                translation_warnings.append(f"Warning: 'paste_search' idx {condition_idx} empty. Skipping.")
                continue
            lines = raw_text.strip().split('\n')
            parsed_paste_preds = []
            for line_num, line in enumerate(lines):
                s_line = line.strip()
                if not s_line or s_line.startswith('#'): continue
                if s_line.lower().startswith('system:limit'):
                    translation_warnings.append(f"Note: Ignored 'system:limit' in paste_search (line {line_num + 1}).")
                    continue
                or_parts = [p.strip() for p in s_line.split(' OR ') if p.strip()]
                if len(or_parts) > 1: parsed_paste_preds.append(or_parts)
                elif or_parts: parsed_paste_preds.append(or_parts[0])
            if parsed_paste_preds: string_predicates.extend(parsed_paste_preds)
            else: translation_warnings.append(f"Warning: 'paste_search' idx {condition_idx} yielded no predicates.")
        else:
            res = translate_single_condition_inner(condition, translation_warnings)
            if res:
                if isinstance(res, list): string_predicates.append(res) # Should be extend if res is list of tags
                else: string_predicates.append(res)

    # Action-Based Exclusion/Inclusion Predicates 
    if rule_action_obj and isinstance(rule_action_obj, dict):
        action_type = rule_action_obj.get('type')
        # It generates additional predicates based on the rule's action (e.g., to avoid
        # adding files to a service they are already in).
        # IMPORTANT: Ensure all logger calls use `logger.warning`, `logger.info` and refer to `rule_name_for_log`.
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
                    translation_warnings.append(f"Warning: Action 'add_to': service key '{key}' not found for exclusion. Skipping exclusion.")

        elif action_type == 'force_in':
            target_dest_keys_set = set()
            raw_dest_keys = rule_action_obj.get('destination_service_keys', [])
            if isinstance(raw_dest_keys, str):
                if raw_dest_keys: target_dest_keys_set.add(raw_dest_keys)
            elif isinstance(raw_dest_keys, list):
                for k in raw_dest_keys:
                    if k: target_dest_keys_set.add(k)

            if not target_dest_keys_set:
                translation_warnings.append(f"Warning: Action 'force_in': No valid target keys. Cannot generate search predicates.")
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
                        translation_warnings.append(f"Warning: Action 'force_in': Target key '{target_key}' not found for exclusion part.")
                if force_in_or_group: string_predicates.append(force_in_or_group)
                else: translation_warnings.append(f"Note: Action 'force_in': Could not generate specific OR-group predicates.")

        elif action_type == 'add_tags':
            tag_key_from_action = rule_action_obj.get('tag_service_key')
            tags_to_process = rule_action_obj.get('tags_to_process', [])
            if tag_key_from_action and tags_to_process:
                action_tag_service_key_for_search = tag_key_from_action
                for tag_str in tags_to_process:
                    clean_tag = tag_str.strip()
                    if clean_tag: string_predicates.append(f"-{clean_tag}")
                if not any("will be searched on service" in w and f"'{tag_key_from_action}'" in w for w in translation_warnings):
                    translation_warnings.append(f"Note: 'add_tags' predicates for tags will be evaluated against service '{tag_key_from_action}'.")
            else:
                if not tag_key_from_action: translation_warnings.append("Warning: Action 'add_tags': missing 'tag_service_key'. Skipping exclusions.")
                if not tags_to_process: translation_warnings.append("Note: Action 'add_tags': missing 'tags_to_process'. No exclusions.")

        elif action_type == 'remove_tags':
            tag_key_from_action = rule_action_obj.get('tag_service_key')
            tags_to_process = rule_action_obj.get('tags_to_process', [])
            if tag_key_from_action and tags_to_process:
                action_tag_service_key_for_search = tag_key_from_action
                for tag_str in tags_to_process:
                    clean_tag = tag_str.strip()
                    if clean_tag: string_predicates.append(clean_tag)
                if not any("will be searched on service" in w and f"'{tag_key_from_action}'" in w for w in translation_warnings):
                     translation_warnings.append(f"Note: 'remove_tags' predicates for tags will be evaluated against service '{tag_key_from_action}'.")
            else:
                if not tag_key_from_action: translation_warnings.append("Warning: Action 'remove_tags': missing 'tag_service_key'. Skipping inclusions.")
                if not tags_to_process: translation_warnings.append("Note: Action 'remove_tags': missing 'tags_to_process'. No inclusions.")

        elif action_type == 'modify_rating':
            rating_key = rule_action_obj.get('rating_service_key')
            target_val = rule_action_obj.get('rating_value')
            info = get_service_details(rating_key)
            if info and info.get('name'):
                s_name = info['name']; s_type = info['type']; s_max_stars = info.get('max_stars')
                action_exclusion_preds = []
                if target_val is None: # Setting to "no rating"
                    action_exclusion_preds.append(f"system:has a rating for {s_name}") # Exclude files that already have a rating
                elif isinstance(target_val, bool): # Like/Dislike
                    if s_type == 7:
                        # Exclude if already has the target rating OR has no rating (target is specific like/dislike)
                        target_keyword = 'like' if target_val is True else 'dislike'
                        # Predicate to find files NOT matching target state
                        # "system:rating for service_name is like" OR "system:rating for service_name is dislike"
                        # We want to find files that are NOT "system:rating for service_name is target_keyword"
                        # This is complex for direct search exclusion. Simpler to check post-search or rely on Hydrus not erroring.
                        # Hydrus seems to handle "set like" on a file already liked fine.
                        # The original logic tried to exclude the *other* state, this is not quite right.
                        # To avoid re-applying, we'd need "NOT (system:rating for service_name is target_keyword)"
                        # The best Hydrus predicate for "does not have this specific rating" is not straightforward.
                        # For now, let's keep it simple: exclude files with no rating if target is a specific rating.
                        # And exclude files with the *other* rating.
                        other_state_keyword = 'dislike' if target_val is True else 'like'
                        action_exclusion_preds.append(f"system:rating for {s_name} is {other_state_keyword}") # if current is dislike, and target is like
                        action_exclusion_preds.append(f"system:no rating for {s_name}") # if current has no rating, and target is like/dislike
                    else: translation_warnings.append(f"Note: Action modify_rating (bool) for non-Like/Dislike service '{s_name}'. No specific exclusion.")
                elif isinstance(target_val, (int, float)): # Numerical or Inc/Dec
                    num_target = int(target_val)
                    # Exclude files that already have the target rating, or have no rating
                    if s_type == 6: # Numerical Stars
                        action_exclusion_preds.append(f"system:no rating for {s_name}")
                        # Predicate for "not equal to num_target"
                        action_exclusion_preds.append(f"system:rating for {s_name} < {num_target}" + (f"/{s_max_stars}" if s_max_stars else ""))
                        action_exclusion_preds.append(f"system:rating for {s_name} > {num_target}" + (f"/{s_max_stars}" if s_max_stars else ""))
                    elif s_type == 22: # Increment/Decrement
                        action_exclusion_preds.append(f"system:no rating for {s_name}")
                        action_exclusion_preds.append(f"system:rating for {s_name} < {num_target}")
                        action_exclusion_preds.append(f"system:rating for {s_name} > {num_target}")
                    else: translation_warnings.append(f"Note: Action modify_rating (num) for non-num/incdec service '{s_name}'. No specific exclusion.")

                if action_exclusion_preds:
                    # If multiple exclusion preds, they form an OR group: file must match one of these to be excluded from action
                    # So, for search, we want files that DON'T match any of these. This means ANDing their negations.
                    # Example: if target is 3 stars, exclude if "no rating" OR "<3 stars" OR ">3 stars".
                    # This means we want to find files that ARE RATED and ARE NOT <3 and ARE NOT >3.
                    # i.e. "has rating" AND "rating = 3 stars". This is finding files that *already match*.
                    # The goal of these predicates is to find files that *do not yet* match the target state.
                    # So, if we want to set rating to X, we should search for files "rating is not X" (including no rating).
                    # This is becoming complex. The Hydrus API for setting ratings is idempotent for most cases.
                    # For "set to no rating", we should search for "system:has a rating for service_name".
                    if target_val is None: # Setting to "no rating"
                        string_predicates.append(f"system:has a rating for {s_name}")
                    # For setting a specific rating, it's often simpler to let Hydrus handle idempotency.
                    # The current override logic (checking existing_override.get('rating_value_set')) handles this post-search.
                    # So, for predicate generation, we might not need complex exclusion here.
                    # The original code had an OR group for exclusions.
                    # If we want to set rating to VALUE, we search for files that (don't have rating) OR (rating is not VALUE).
                    # For now, let's stick to the original logic's structure for exclusion predicates and review if it's optimal.
                    if len(action_exclusion_preds) == 1: string_predicates.append(action_exclusion_preds[0])
                    elif len(action_exclusion_preds) > 1: string_predicates.append(action_exclusion_preds) # This forms an OR group for files to *match* for exclusion.

                elif not any("No specific exclusion" in w for w in translation_warnings if f"'{s_name}'" in w) and target_val is not None:
                    translation_warnings.append(f"Note: Action modify_rating for '{s_name}' to '{target_val}': Could not form optimal exclusion predicate to find files that *don't* have this rating. Relying on post-search override logic or Hydrus idempotency.")
            elif rating_key:
                 translation_warnings.append(f"Warning: Action modify_rating: service key '{rating_key}' not found for exclusion. Skipping specific search exclusion predicates.")

    if not string_predicates:
        # Determine if the rule had substantive conditions supplied by the user,
        # excluding paste_search conditions that were intentionally empty (e.g., only comments).
        has_substantive_user_conditions = False
        if rule_conditions_list:
            for c in rule_conditions_list:
                if isinstance(c, dict):
                    if c.get('type') == 'paste_search':
                        # A paste_search with actual content is substantive.
                        # If it then results in no predicates, that's a warning from paste_search logic itself.
                        if c.get('value','').strip() and not c.get('value','').strip().startswith('#'):
                            # This check is a bit simplistic for "all comments" but covers empty or pure comment.
                            # The main goal is to see if there was an *attempt* at a condition.
                            has_substantive_user_conditions = True 
                            break
                    elif c.get('type') == 'or_group':
                        if c.get('conditions'): # An OR group with sub-conditions is substantive.
                            has_substantive_user_conditions = True
                            break
                    else: # Any other condition type is substantive.
                        has_substantive_user_conditions = True
                        break
        
        # Conditions for adding a warning about no predicates:
        # 1. The rule has substantive user-defined conditions that failed to produce any predicates.
        #    This is critical because the user's intent is not being met.
        # 2. OR, the rule action type is one that typically requires predicates to narrow its scope
        #    (i.e., not add_tags/remove_tags which can operate on implicitly generated predicates like -tag/tag).
        #    If such an action has no predicates, it's also potentially unsafe or unintended.

        should_add_warning = False
        is_potentially_unsafe_action_without_predicates = False

        if rule_action_obj and rule_action_obj.get('type') not in ['add_tags', 'remove_tags']:
            is_potentially_unsafe_action_without_predicates = True
        
        # If action_tag_service_key_for_search is set, it means add_tags/remove_tags *did* generate their implicit predicates.
        # So, lack of other string_predicates might be fine if it's *only* an add_tags/remove_tags action.
        if rule_action_obj and rule_action_obj.get('type') in ['add_tags', 'remove_tags'] and action_tag_service_key_for_search:
            is_potentially_unsafe_action_without_predicates = False


        if has_substantive_user_conditions or is_potentially_unsafe_action_without_predicates:
            should_add_warning = True

        if should_add_warning:
            # Make the warning critical if there were substantive user conditions that vanished.
            # Otherwise, it's a standard warning if it's an action type that might run too broadly.
            warning_prefix = "CRITICAL Warning:" if has_substantive_user_conditions else "Warning:"
            message = (f"{warning_prefix} No Hydrus search predicates were generated from rule conditions "
                       f"or action-specific logic. The rule might match all files or no files in an unintended way. "
                       f"This is critical if user-defined conditions were specified but yielded no search terms.")
            
            # Avoid adding duplicate critical message if one already exists from a specific translation part
            # unless this is a new critical insight (has_substantive_user_conditions making it critical).
            is_already_critical = any(is_critical_warning(w) for w in translation_warnings)
            if not is_already_critical or (has_substantive_user_conditions and warning_prefix == "CRITICAL Warning:"):
                 # Add if no critical warning exists yet, OR if this specific condition (substantive user conditions leading to no predicates) makes it critical.
                if not any(message.endswith(w_existing.split(":", 1)[1].strip() if ":" in w_existing else w_existing) for w_existing in translation_warnings): # Avoid exact duplicate message
                    translation_warnings.append(message)

    return string_predicates, translation_warnings, action_tag_service_key_for_search

def _batch_api_call_with_retry(app_config, endpoint, method, items_to_process, batch_size,
                               batch_payload_formatter, single_item_payload_formatter,
                               rule_name_for_log, action_description,
                               expected_success_status_codes=None, # Not used as call_hydrus_api handles success check
                               timeout_per_call=120):
    """Helper for batch API calls with individual retries."""
    settings = app_config.get('HYDRUS_SETTINGS', {})
    api_address = settings.get('api_address')
    api_key = settings.get('api_key')

    successful_items = []
    failed_items_with_errors = []

    if not items_to_process:
        return {"successful_items": [], "failed_items_with_errors": []}

    if not api_address:
        logger.error(f"Rule '{rule_name_for_log}': API address not set for batch API call '{action_description}'.")
        # Mark all items as failed if API address is missing
        for item in items_to_process:
            failed_items_with_errors.append((item, "API address not configured.", None))
        return {"successful_items": [], "failed_items_with_errors": failed_items_with_errors}

    logger.info(f"Rule '{rule_name_for_log}': Batch processing {len(items_to_process)} items for '{action_description}' (batch size {batch_size}).")

    for i in range(0, len(items_to_process), batch_size):
        batch_items = items_to_process[i : i + batch_size]
        batch_num = (i // batch_size) + 1

        if not batch_items: continue

        batch_payload = batch_payload_formatter(batch_items)
        batch_result, batch_status = call_hydrus_api(
            api_address, api_key, endpoint, method=method,
            json_data=batch_payload, timeout=timeout_per_call
        )

        if batch_result.get("success"):
            successful_items.extend(batch_items)
        else:
            batch_err_msg = batch_result.get('message', f"Unknown API error for batch {batch_num}")
            logger.warning(f"Rule '{rule_name_for_log}': Batch {batch_num} for '{action_description}' failed: {batch_err_msg}. Status: {batch_status}. Retrying individually...")
            for item_idx, single_item in enumerate(batch_items):
                single_payload = single_item_payload_formatter(single_item)
                retry_result, retry_status = call_hydrus_api(
                    api_address, api_key, endpoint, method=method,
                    json_data=single_payload, timeout=timeout_per_call
                )
                if retry_result.get("success"):
                    successful_items.append(single_item)
                else:
                    retry_err_msg = retry_result.get('message', f"Unknown API error for item {str(single_item)[:50]}")
                    logger.warning(f"Rule '{rule_name_for_log}': Retry for item '{str(single_item)[:50]}' (batch {batch_num}) failed: {retry_err_msg}. Status: {retry_status}")
                    failed_items_with_errors.append((single_item, retry_err_msg, retry_status))

    logger.info(f"Rule '{rule_name_for_log}': Batch '{action_description}' complete. Succeeded: {len(successful_items)}, Failed: {len(failed_items_with_errors)}.")
    if failed_items_with_errors:
        logger.debug(f"  Failed items/errors for '{action_description}': {failed_items_with_errors}")
    return {"successful_items": successful_items, "failed_items_with_errors": failed_items_with_errors}

# --- Action Performing Functions ---

def _perform_action_add_to_files_batch(app_config, file_hashes, destination_service_keys, rule_name_for_log, batch_size=64):
    """Performs 'add_to' action for files in batches."""
    if not file_hashes:
        return {"success": True, "total_successful_migrations": 0, "total_failed_migrations": 0, "files_with_some_errors": {}, "overall_errors": []}
    if not destination_service_keys:
        return {"success": True, "total_successful_migrations": 0, "total_failed_migrations": 0, "files_with_some_errors": {}, "overall_errors": []}

    overall_success_flag = True
    total_successful_migrations = 0
    total_failed_migrations = 0
    files_with_errors_map = {}
    endpoint = '/add_files/migrate_files'

    for dest_key in destination_service_keys:
        logger.info(f"Rule '{rule_name_for_log}': Processing 'add_to' for service '{dest_key}' for {len(file_hashes)} files.")
        batch_results = _batch_api_call_with_retry(
            app_config, endpoint, 'POST', file_hashes, batch_size,
            lambda batch_h: {"hashes": batch_h, "file_service_key": dest_key},
            lambda single_h: {"hash": single_h, "file_service_key": dest_key},
            rule_name_for_log, f"add files to service '{dest_key}'", timeout_per_call=180
        )
        total_successful_migrations += len(batch_results["successful_items"])
        if batch_results["failed_items_with_errors"]:
            overall_success_flag = False
            total_failed_migrations += len(batch_results["failed_items_with_errors"])
            for h, msg, status in batch_results["failed_items_with_errors"]:
                files_with_errors_map.setdefault(h, []).append({"destination_service_key": dest_key, "message": msg, "status_code": status})

    return {"success": overall_success_flag, "total_successful_migrations": total_successful_migrations,
            "total_failed_migrations": total_failed_migrations, "files_with_some_errors": files_with_errors_map, "overall_errors": []}


def _perform_action_force_in_batch(app_config, files_metadata_list, rule_configured_destination_keys, # Changed from destination_service_keys
                                   all_local_service_keys_set, rule_name_for_log,
                                   available_services_list, batch_size=64):
    """Performs 'force_in' action in batches (copy, verify, delete).
    `rule_configured_destination_keys` are the destinations defined in this specific force_in rule.
    """
    initial_candidates = len(files_metadata_list)
    if not files_metadata_list:
        return {"success": True, "files_fully_successful": [], "files_with_errors": {}, "summary_counts": {"initial_candidates":0, "copied_phase_success_count":0, "verified_phase_success_count":0, "deleted_phase_success_count":0}, "overall_errors": []}
    
    # CRITICAL SAFETY CHECK: This function must never be called with empty destination keys.
    # While execute_single_rule now validates this, this check serves as a vital safeguard
    # within the most dangerous action function itself. An empty destination list for a "force_in"
    # action would effectively mean "delete files from wherever they are", which must be prevented.
    if not isinstance(rule_configured_destination_keys, list) or \
       not rule_configured_destination_keys or \
       not all(isinstance(k, str) and k.strip() for k in rule_configured_destination_keys):
        msg = (f"Rule '{rule_name_for_log}': 'force_in' action was called with invalid or empty destination keys. "
               f"This is a critical safety violation. Aborting 'force_in' operation. "
               f"Keys provided: {rule_configured_destination_keys}")
        logger.critical(msg) # Log as critical because this indicates a programming error.
        return {"success": False, "files_fully_successful": [], "files_with_errors": {},
                "summary_counts": {"initial_candidates": initial_candidates, "copied_phase_success_count": 0, "verified_phase_success_count": 0, "deleted_phase_success_count": 0},
                "overall_errors": [msg]}

    files_with_errors_map = {}
    candidate_hashes = [fm.get('hash') for fm in files_metadata_list if fm.get('hash')]

    # Phase 1: Copy
    logger.info(f"Rule '{rule_name_for_log}': ForceIn - Phase 1 (Copy) for {len(candidate_hashes)} files to {rule_configured_destination_keys}")
    hashes_copied_to_all_dests = set(candidate_hashes)
    for dest_key in rule_configured_destination_keys: # Iterate over rule's own destination keys
        if not hashes_copied_to_all_dests: break
        copy_results = _batch_api_call_with_retry(
            app_config, '/add_files/migrate_files', 'POST', list(hashes_copied_to_all_dests), batch_size,
            lambda bh: {"hashes": bh, "file_service_key": dest_key},
            lambda sh: {"hash": sh, "file_service_key": dest_key},
            rule_name_for_log, f"ForceIn-Copy to '{dest_key}'", timeout_per_call=180
        )
        for h, msg, status in copy_results["failed_items_with_errors"]:
            hashes_copied_to_all_dests.discard(h)
            files_with_errors_map.setdefault(h, {"phase": "copy", "errors": []})["errors"].append({"service_key": dest_key, "message": f"Copy fail: {msg}", "status_code": status})
    copied_count = len(hashes_copied_to_all_dests)
    logger.info(f"Rule '{rule_name_for_log}': ForceIn - Phase 1 (Copy) complete. {copied_count} files potentially copied.")
    if not hashes_copied_to_all_dests:
        return {"success": False, "files_fully_successful": [], "files_with_errors": files_with_errors_map, "summary_counts": {"initial_candidates":initial_candidates, "copied_phase_success_count":0, "verified_phase_success_count":0, "deleted_phase_success_count":0}, "overall_errors": ["No files copied."]}

    # Phase 2: Verify
    logger.info(f"Rule '{rule_name_for_log}': ForceIn - Phase 2 (Verify) for {len(hashes_copied_to_all_dests)} files.")
    fresh_meta, meta_errs = _fetch_metadata_for_hashes(app_config, rule_name_for_log, list(hashes_copied_to_all_dests))
    if meta_errs:
        for err in meta_errs:
            for h_err in err.get("hashes_in_batch", []):
                if h_err in hashes_copied_to_all_dests:
                    hashes_copied_to_all_dests.discard(h_err) # Verification failed
                    files_with_errors_map.setdefault(h_err, {"phase": "verify", "errors": []})["errors"].append({"message": f"Meta fetch fail: {err.get('message')}", "status_code": err.get("status_code")})

    hashes_verified_in_all_dests = set()
    dest_set_for_verification = set(rule_configured_destination_keys) # Verify against rule's own keys
    for meta in fresh_meta:
        h = meta.get('hash')
        if not h or h not in hashes_copied_to_all_dests: continue
        current_services = set(meta.get('file_services', {}).get('current', {}).keys())
        if dest_set_for_verification.issubset(current_services):
            hashes_verified_in_all_dests.add(h)
        else:
            missing = dest_set_for_verification - current_services
            files_with_errors_map.setdefault(h, {"phase": "verify", "errors": []})["errors"].append({"message": f"Verify fail. Missing in rule's configured destinations: {missing}. Current services: {current_services}"})
    verified_count = len(hashes_verified_in_all_dests)
    logger.info(f"Rule '{rule_name_for_log}': ForceIn - Phase 2 (Verify) complete. {verified_count} files verified.")
    if not hashes_verified_in_all_dests:
         return {"success": False, "files_fully_successful": [], "files_with_errors": files_with_errors_map, "summary_counts": {"initial_candidates":initial_candidates, "copied_phase_success_count":copied_count, "verified_phase_success_count":0, "deleted_phase_success_count":0}, "overall_errors": ["No files verified."]}

    # Phase 3: Delete from other local services
    logger.info(f"Rule '{rule_name_for_log}': ForceIn - Phase 3 (Delete from others) for {len(hashes_verified_in_all_dests)} files.")
    deletions_by_service = {}
    meta_map_verified = {m['hash']: m for m in fresh_meta if m.get('hash') in hashes_verified_in_all_dests}

    for h_verified in list(hashes_verified_in_all_dests): # Iterate copy
        meta_obj = meta_map_verified.get(h_verified)
        if not meta_obj:
            logger.warning(f"Rule '{rule_name_for_log}': Missing fresh metadata for verified hash {h_verified} during delete prep.")
            hashes_verified_in_all_dests.discard(h_verified)
            files_with_errors_map.setdefault(h_verified, {"phase": "delete_prep", "errors": []})["errors"].append({"message": "Missing fresh metadata for delete."})
            continue
        current_services = set(meta_obj.get('file_services', {}).get('current', {}).keys())
        # Delete from local services that are NOT part of this rule's configured destinations
        to_delete_from = (current_services.intersection(all_local_service_keys_set)) - set(rule_configured_destination_keys)
        for sk_del in to_delete_from:
            deletions_by_service.setdefault(sk_del, []).append(h_verified)

    hashes_deleted_successfully_from_extras = set(hashes_verified_in_all_dests)
    for service_key_del, hashes_on_service in deletions_by_service.items():
        if not hashes_on_service or not hashes_deleted_successfully_from_extras: break
        delete_results = _batch_api_call_with_retry(
            app_config, '/add_files/delete_files', 'POST',
            [h for h in hashes_on_service if h in hashes_deleted_successfully_from_extras], batch_size,
            lambda bh: {"hashes": bh, "file_service_key": service_key_del},
            lambda sh: {"hash": sh, "file_service_key": service_key_del},
            rule_name_for_log, f"ForceIn-Delete from '{service_key_del}'", timeout_per_call=180
        )
        for h, msg, status in delete_results["failed_items_with_errors"]:
            hashes_deleted_successfully_from_extras.discard(h)
            files_with_errors_map.setdefault(h, {"phase": "delete", "errors": []})["errors"].append({"service_key": service_key_del, "message": f"Delete fail: {msg}", "status_code": status})

    files_fully_successful = []
    deleted_phase_count = 0
    for h_v in hashes_verified_in_all_dests: # Check original verified set
        needed_del = any(h_v in h_list for h_list in deletions_by_service.values())
        if not needed_del: # Verified, no deletions needed from other local services
            files_fully_successful.append(h_v)
            deleted_phase_count +=1
        elif h_v in hashes_deleted_successfully_from_extras: # Verified, deletions needed and succeeded
            files_fully_successful.append(h_v)
            deleted_phase_count +=1

    logger.info(f"Rule '{rule_name_for_log}': ForceIn - Phase 3 (Delete) complete. {deleted_phase_count} successful cleanups from other local services.")
    logger.info(f"Rule '{rule_name_for_log}': ForceIn - Overall: {len(files_fully_successful)} fully successful.")

    final_success = (len(files_with_errors_map) == 0 and len(files_fully_successful) == initial_candidates)
    return {"success": final_success, "files_fully_successful": files_fully_successful, "files_with_errors": files_with_errors_map,
            "summary_counts": {"initial_candidates":initial_candidates, "copied_phase_success_count":copied_count, "verified_phase_success_count":verified_count, "deleted_phase_success_count":deleted_phase_count},
            "overall_errors": []}


def _perform_action_manage_tags(app_config, file_hashes, tag_service_key, tags_to_process, action_mode, rule_name_for_log):
    """Performs tag management (add/remove)."""
    if not file_hashes: return {"success": True, "message": "No files for tag action.", "files_processed_count": 0, "errors": []}
    if not tag_service_key: return {"success": False, "message": "Tag service key missing.", "files_processed_count": 0, "errors": ["Missing tag_service_key."]}
    if not tags_to_process: return {"success": True, "message": "No tags specified.", "files_processed_count": len(file_hashes), "errors": []}

    settings = app_config.get('HYDRUS_SETTINGS', {})
    api_address = settings.get('api_address')
    api_key = settings.get('api_key')
    if not api_address: return {"success": False, "message": "API address not set for tag action.", "files_processed_count": 0, "errors": ["API address not configured."]}

    action_str = "add" if action_mode == 0 else "remove"
    logger.info(f"Rule '{rule_name_for_log}': '{action_str} tags' for {len(file_hashes)} files on service '{tag_service_key}'. Tags: {tags_to_process}")
    payload = {
        "hashes": file_hashes,
        "service_keys_to_actions_to_tags": {tag_service_key: {str(action_mode): tags_to_process}}
    }
    if action_mode == 0: payload["override_previously_deleted_mappings"] = True
    else: payload["create_new_deleted_mappings"] = True

    result, status = call_hydrus_api(api_address, api_key, '/add_tags/add_tags', method='POST', json_data=payload, timeout=120)
    if result.get("success"):
        msg = f"Successfully sent '{action_str} tags' request for {len(file_hashes)} files to '{tag_service_key}'."
        return {"success": True, "message": msg, "files_processed_count": len(file_hashes), "errors": []}
    else:
        err_msg = f"Failed to {action_str} tags for {len(file_hashes)} files on '{tag_service_key}': {result.get('message', 'API error')}"
        logger.warning(f"Rule '{rule_name_for_log}': {err_msg}")
        return {"success": False, "message": err_msg, "files_processed_count": len(file_hashes), "errors": [{"message": err_msg, "status_code": status}]}


def _perform_action_modify_rating(app_config, file_hash, rating_service_key, rating_value, rule_name_for_log):
    """Performs 'modify_rating' action."""
    if not file_hash: return {"success": False, "message": "File hash missing for rating.", "errors": ["File hash missing."]}
    if not rating_service_key: return {"success": False, "message": "Rating service key missing.", "errors": ["Rating service key missing."]}

    settings = app_config.get('HYDRUS_SETTINGS', {})
    api_address = settings.get('api_address')
    api_key = settings.get('api_key')
    if not api_address: return {"success": False, "message": "API address not set for rating action.", "errors": ["API address not configured."]}

    logger.info(f"Rule '{rule_name_for_log}': Modifying rating for {file_hash} on '{rating_service_key}' to {rating_value}.")
    payload = {"hash": file_hash, "rating_service_key": rating_service_key, "rating": rating_value}
    result, status = call_hydrus_api(api_address, api_key, '/edit_ratings/set_rating', method='POST', json_data=payload, timeout=60)

    if result.get("success"):
        msg = f"Successfully set rating for {file_hash} on '{rating_service_key}' to '{rating_value}'."
        return {"success": True, "message": msg, "errors": []}
    else:
        err_msg = f"Failed to set rating for {file_hash} on '{rating_service_key}': {result.get('message', 'API error')}"
        logger.warning(f"Rule '{rule_name_for_log}': {err_msg}")
        return {"success": False, "message": err_msg, "errors": [{"message": err_msg, "status_code": status}]}

def _determine_file_action_status_based_on_override(
    db_conn, 
    file_hash, 
    current_rule_id, 
    current_rule_importance, 
    current_rule_action_type, 
    rating_service_key_for_action, # Specific to modify_rating
    rating_value_for_action,       # Specific to modify_rating
    log_prefix # For consistent logging
    ):
    """
    Checks if a file should be skipped by the current rule due to an existing conflict override.

    Returns:
        tuple: (
            bool: True if the file should be skipped, False otherwise.
            dict or None: Details of the winning override if one caused a skip, else None.
        )
    """
    skip_file = False
    override_db_conflict_type = None
    override_db_conflict_key = None
    log_override_details_for_skip = None

    if current_rule_action_type in ['add_to', 'force_in']:
        override_db_conflict_type = "placement"
    elif current_rule_action_type == 'modify_rating':
        override_db_conflict_type = "rating"
        override_db_conflict_key = rating_service_key_for_action
    
    if not override_db_conflict_type: # e.g. tag actions don't participate in this override type
        return False, None

    existing_override_tuple = get_conflict_override(db_conn, file_hash, override_db_conflict_type, override_db_conflict_key)

    if existing_override_tuple:
        win_id, win_importance, win_action_type, win_rating_val_json = existing_override_tuple
        
        log_override_details_for_skip = {
            "winning_rule_id": win_id,
            "winning_rule_importance": win_importance,
            "winning_rule_action_type": win_action_type,
            # Potentially add win_rating_val_json if needed for logging
        }

        # Primary condition: Is the existing winner more important?
        if win_importance > current_rule_importance:
            skip_file = True
            logger.info(f"{log_prefix}: File {file_hash} - SKIPPING. Existing override by rule '{win_id[:8]}' (Imp: {win_importance}, Type: {win_action_type}) is MORE IMPORTANT than current rule (Imp: {current_rule_importance}, Type: {current_rule_action_type}).")
        
        # Secondary condition: Equal importance, different rules
        elif win_importance == current_rule_importance and win_id != current_rule_id:
            # If current is 'add_to' and winner is 'force_in' (same importance), 'add_to' skips.
            if current_rule_action_type == 'add_to' and win_action_type == 'force_in':
                skip_file = True
                logger.info(f"{log_prefix}: File {file_hash} - SKIPPING. Current 'add_to' (Imp: {current_rule_importance}) defers to existing 'force_in' winner '{win_id[:8]}' (Imp: {win_importance}) of EQUAL IMPORTANCE.")
            # If current is 'force_in' and winner is 'add_to' (same importance), 'force_in' DOES NOT skip. It will run and attempt to win.
            elif current_rule_action_type == 'force_in' and win_action_type == 'add_to':
                logger.info(f"{log_prefix}: File {file_hash} - PROCEEDING. Current 'force_in' (Imp: {current_rule_importance}) WILL RUN against existing 'add_to' winner '{win_id[:8]}' (Imp: {win_importance}) of EQUAL IMPORTANCE.")
                # skip_file remains False
            # If both are same action type (e.g. add_to vs add_to, force_in vs force_in) and same importance, first one wins.
            elif current_rule_action_type == win_action_type:
                skip_file = True
                logger.info(f"{log_prefix}: File {file_hash} - SKIPPING. Existing override by rule '{win_id[:8]}' (Type: {win_action_type}) has SAME IMPORTANCE ({win_importance}) as current rule and already won.")
            # Else (e.g. different action types that don't have specific precedence like force_in vs add_to)
            # and it's not covered above, implies the current rule might proceed if types are non-interfering
            # or if no specific rule dictates a skip.
            # However, if override_db_conflict_type matched, they are considered conflicting.
            # The previous case (current_rule_action_type == win_action_type) handles direct conflicts.
            # This path might be hit if e.g. a future action type has the same conflict_type.
            # For now, if importance is equal and IDs are different, and it's not force_in vs add_to,
            # assume the existing winner holds unless more specific logic is added.
            # To be safe, if not force_in vs add_to (which has special handling),
            # and types are different but conflict_type is same, let's assume skip if it's not the current rule.
            elif current_rule_action_type != win_action_type: # And not the force_in vs add_to special case
                 logger.info(f"{log_prefix}: File {file_hash} - SKIPPING (default for same importance, different rule, different action type but same conflict type). Existing override by rule '{win_id[:8]}' (Type: {win_action_type}, Imp: {win_importance}) vs Current (Type: {current_rule_action_type}, Imp: {current_rule_importance}).")
                 skip_file = True


        # Tertiary condition: Equal importance, same rule (e.g. for rating values)
        elif win_importance == current_rule_importance and win_id == current_rule_id:
            if current_rule_action_type == 'modify_rating' and \
               win_rating_val_json is not None and \
               rating_value_for_action is not None: # Ensure current rule's target value is also known
                try:
                    parsed_win_rating = json.loads(win_rating_val_json)
                    # Compare actual values, not just JSON strings, for robustness
                    if parsed_win_rating == rating_value_for_action:
                        skip_file = True
                        logger.info(f"{log_prefix}: File {file_hash} - SKIPPING. Rating already set to target value '{rating_value_for_action}' by this rule '{current_rule_id[:8]}'.")
                except json.JSONDecodeError:
                    logger.warning(f"{log_prefix}: File {file_hash} - Could not parse winning rating JSON '{win_rating_val_json}' for comparison.")
            # For 'add_to' or 'force_in', if it's the same rule that won, it means it already ran successfully.
            # It shouldn't run again in the same overall scheduled job on the same file.
            # This prevents re-processing if the rule somehow matches the file again after its own action.
            # However, this rule implies statefulness within a single execution_single_rule call,
            # which is not how it's designed. The rule execution is for *this current pass*.
            # If the rule won previously (in a prior run) and parameters are the same, that's fine.
            # Let's assume this check is mostly for 'modify_rating'.
            # For placement, if the rule previously won, it would be picked up by importance checks typically.

        # If current rule is more important (win_importance < current_rule_importance), it will run.
        if not skip_file and win_importance < current_rule_importance:
             logger.info(f"{log_prefix}: File {file_hash} - PROCEEDING. Current rule (Imp: {current_rule_importance}, Type: {current_rule_action_type}) is MORE IMPORTANT than existing override by rule '{win_id[:8]}' (Imp: {win_importance}, Type: {win_action_type}). Will attempt to process and win.")
    
    else: # No existing override for this conflict type
        logger.debug(f"{log_prefix}: File {file_hash} - PROCEEDING. No existing override found for conflict type '{override_db_conflict_type}'.")
        # skip_file remains False, log_override_details_for_skip remains None

    return skip_file, log_override_details_for_skip
# --- END OF NEW HELPER FUNCTION ---

def execute_single_rule(app_config, db_conn, rule, current_run_id, execution_order_in_run, is_manual_run=False):
    """
    Internal function to execute a single rule's logic.
    Orchestrates condition translation, file searching, action execution,
    manages conflict overrides based on importance, and logs details.
    Requires app_config for settings and db_conn for database operations.
    """
    rule_id = rule.get('id', 'unknown_rule_id_' + str(uuid.uuid4())[:8])
    rule_name = rule.get('name', rule_id)
    current_rule_importance = int(rule.get('priority', 1)) 
    rule_exec_start_time = datetime.utcnow()
    rule_execution_id = str(uuid.uuid4())

    log_prefix = f"RuleExec ID {rule_execution_id[:8]} (Rule '{rule_name}', RunID {current_run_id[:8]})"
    manual_run_log_str = "(Manual Run - Overrides Bypassed)" if is_manual_run else "(Run with Override Logic)"
    logger.info(f"{log_prefix}: Executing (Importance: {current_rule_importance}, Type: {rule.get('action',{}).get('type')}) {manual_run_log_str}")

    final_details = create_default_details()
    num_matched_files_by_search_raw = 0
    num_candidates_after_all_filters = 0 # Will be len(candidate_files_for_action)
    num_files_to_attempt_action_on = 0
    total_files_added_successfully = 0
    total_successful_add_to_operations = 0 # Granular count for add_to
    total_files_forced_successfully = 0
    total_files_tag_action_success_on = 0
    total_files_rating_modified_successfully = 0
    files_skipped_due_to_recent_view = 0
    files_skipped_due_to_override = 0
    metadata_fetched_count = 0


    overall_rule_success_flag = True
    final_summary_message_str = f"Rule '{rule_name}' processing started."
    active_rule_version_id = None
    current_rule_action_type = rule.get('action', {}).get('type', "unknown")

    try:
        active_rule_version_id = get_or_create_active_rule_version(db_conn, rule)
        if not active_rule_version_id:
            raise Exception(f"{log_prefix}: CRITICAL - Failed to get or create active rule version. Aborting.")

        cursor = db_conn.cursor()
        cursor.execute('''
            INSERT INTO rule_executions_in_run (
                rule_execution_id, run_id, rule_id, rule_version_id, execution_order_in_run,
                start_time, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            rule_execution_id, current_run_id, rule_id, active_rule_version_id,
            execution_order_in_run, rule_exec_start_time.isoformat() + "Z", "started"
        ))

        available_services = _ensure_available_services(app_config, rule_name)
        if not available_services :
             raise Exception(f"{log_prefix}: Critical - Could not load Hydrus services. Aborting.")

        settings = app_config.get('HYDRUS_SETTINGS', {})
        api_address = settings.get('api_address')
        api_key = settings.get('api_key')
        last_viewed_threshold_seconds = settings.get('last_viewed_threshold_seconds', 0)
        log_overridden_actions_setting = settings.get('log_overridden_actions', False)

        recently_viewed_hashes_set = set()
        if last_viewed_threshold_seconds > 0:
            threshold_dt = datetime.now() - timedelta(seconds=last_viewed_threshold_seconds)
            recent_predicates = [f"system:last viewed time > {threshold_dt.strftime('%Y-%m-%d %H:%M:%S')}"]
            search_params = {'tags': json.dumps(recent_predicates), 'return_hashes': json.dumps(True), 'return_file_ids': json.dumps(False)}
            recent_res, _ = call_hydrus_api(api_address, api_key, '/get_files/search_files', params=search_params)
            if recent_res.get("success"):
                recently_viewed_hashes_set = set(recent_res.get('data', {}).get('hashes', []))
            else:
                logger.warning(f"{log_prefix}: Failed to fetch recently viewed files: {recent_res.get('message')}")

        hydrus_predicates, translation_warnings, action_tag_service_key = \
            _translate_rule_to_hydrus_predicates(
                rule.get('conditions', []), rule.get('action'),
                available_services, rule_name
            )
        final_details["translation_warnings"] = translation_warnings
        final_details["action_tag_service_key_used_for_search"] = action_tag_service_key
        if any(is_critical_warning(w) for w in translation_warnings):
            crit_warns = [w for w in translation_warnings if is_critical_warning(w)]
            # Combine critical warnings for a more comprehensive message if multiple exist
            combined_crit_msg = "; ".join(crit_warns)
            raise Exception(f"{log_prefix}: ABORTED due to critical translation error(s). Details: \"{combined_crit_msg}\"")

        # The following block is now largely covered by the critical translation warnings.
        # If hydrus_predicates is empty when it shouldn't be, a critical warning should have been generated by _translate...
        # if not rule.get('conditions') and not hydrus_predicates and not action_tag_service_key:
        #     # Allow rules with no conditions if they are tag/rating actions that might use broad predicates derived from action
        #     if not (current_rule_action_type in ['add_tags', 'remove_tags', 'modify_rating'] and hydrus_predicates): # This check might be redundant if _translate adds implicit predicates
        #          raise Exception(f"{log_prefix}: Rule has no conditions and generated no search predicates. Aborting to prevent matching all files.")

        # --- Start: Strict validation of Action data ---
        action_data = rule.get('action', {})
        # current_rule_action_type is already set before _translate_rule_to_hydrus_predicates call
        # but we re-check here to ensure integrity before proceeding.
        current_rule_action_type = action_data.get('type') # Get it fresh from action_data
        
        if not current_rule_action_type:
            raise Exception(f"{log_prefix}: Rule definition is missing 'action.type'. Aborting.")

        rule_configured_destination_keys = [] # Specific to add_to, force_in
        tag_service_key_for_action = None     # Specific to tag actions
        tags_for_action = []                  # Specific to tag actions
        rating_service_key_for_action = None  # Specific to rating actions
        rating_value_for_action = None        # Specific to rating actions

        if current_rule_action_type == 'add_to' or current_rule_action_type == 'force_in':
            rule_configured_destination_keys = action_data.get('destination_service_keys', [])
            if not isinstance(rule_configured_destination_keys, list) or \
               not rule_configured_destination_keys or \
               not all(isinstance(k, str) and k.strip() for k in rule_configured_destination_keys):
                raise Exception(f"{log_prefix}: Action '{current_rule_action_type}' requires 'destination_service_keys' "
                                f"to be a non-empty list of valid, non-empty service key strings. Found: '{rule_configured_destination_keys}'. Aborting.")
        elif current_rule_action_type == 'add_tags' or current_rule_action_type == 'remove_tags':
            tag_service_key_for_action = action_data.get('tag_service_key')
            tags_for_action = action_data.get('tags_to_process', [])
            if not tag_service_key_for_action or not isinstance(tag_service_key_for_action, str) or not tag_service_key_for_action.strip():
                raise Exception(f"{log_prefix}: Action '{current_rule_action_type}' requires a valid, non-empty 'tag_service_key' string. Found: '{tag_service_key_for_action}'. Aborting.")
            if not isinstance(tags_for_action, list) or not tags_for_action or not all(isinstance(t, str) and t.strip() for t in tags_for_action):
                raise Exception(f"{log_prefix}: Action '{current_rule_action_type}' requires 'tags_to_process' "
                                f"to be a non-empty list of valid, non-empty tag strings. Found: '{tags_for_action}'. Aborting.")
        elif current_rule_action_type == 'modify_rating':
            rating_service_key_for_action = action_data.get('rating_service_key')
            if not rating_service_key_for_action or not isinstance(rating_service_key_for_action, str) or not rating_service_key_for_action.strip():
                raise Exception(f"{log_prefix}: Action '{current_rule_action_type}' requires a valid, non-empty 'rating_service_key' string. Found: '{rating_service_key_for_action}'. Aborting.")
            if 'rating_value' not in action_data: # Presence of the key is important, even if value is null (for "remove rating")
                raise Exception(f"{log_prefix}: Action '{current_rule_action_type}' is missing the 'rating_value' field. Aborting.")
            rating_value_for_action = action_data.get('rating_value')
            # Further validation of rating_value type (bool for like/dislike, num for stars, null for clear) happens
            # implicitly in _perform_action_modify_rating or Hydrus API, but basic presence is checked here.
        else:
            raise Exception(f"{log_prefix}: Unsupported or unknown action type '{current_rule_action_type}' defined in rule. Aborting.")

        search_api_params = {'return_hashes': json.dumps(True), 'return_file_ids': json.dumps(False), 'tags': json.dumps(hydrus_predicates)}
        if action_tag_service_key: # This is from conditions, used for initial search
            search_api_params['tag_service_key'] = action_tag_service_key

        search_result, _ = call_hydrus_api(api_address, api_key, '/get_files/search_files', params=search_api_params)
        if not search_result.get("success"):
            raise Exception(f"{log_prefix}: Failed Hydrus file search: {search_result.get('message', 'API error')}. Predicates: {str(hydrus_predicates)[:500]}. Aborting.")

        matched_hashes_raw = search_result.get('data', {}).get('hashes', [])
        num_matched_files_by_search_raw = len(matched_hashes_raw)
        logger.info(f"{log_prefix}: Hydrus search returned {num_matched_files_by_search_raw} hashes.")

        eligible_hashes_after_view = []
        if last_viewed_threshold_seconds > 0 and recently_viewed_hashes_set:
            for h_view in matched_hashes_raw:
                if h_view in recently_viewed_hashes_set:
                    files_skipped_due_to_recent_view += 1
                    log_file_action_detail(db_conn, rule_execution_id, h_view, "skip_action", json.dumps({"reason": "recently_viewed"}), "skipped_recent_view")
                else:
                    eligible_hashes_after_view.append(h_view)
        else:
            eligible_hashes_after_view = list(matched_hashes_raw)
        final_details["files_skipped_due_to_recent_view"] = files_skipped_due_to_recent_view

        candidate_files_for_action = []
        if not is_manual_run:
            for file_hash in eligible_hashes_after_view:
                should_skip, override_details_logged = _determine_file_action_status_based_on_override(
                    db_conn, file_hash, rule_id, current_rule_importance, current_rule_action_type,
                    rating_service_key_for_action, rating_value_for_action, log_prefix
                )
                if should_skip:
                    files_skipped_due_to_override += 1
                    if log_overridden_actions_setting:
                        logger.debug(f"{log_prefix}: File {file_hash} skipped due to override. Logging detail as per setting.")
                        log_file_action_detail(db_conn, rule_execution_id, file_hash, "skip_action",
                                               json.dumps({"reason": "override"}), "skipped_override",
                                               override_info_json=json.dumps(override_details_logged) if override_details_logged else None)
                    else:
                        logger.debug(f"{log_prefix}: File {file_hash} skipped due to override. NOT logging detail as per setting.")
                else:
                    candidate_files_for_action.append((file_hash, list(rule_configured_destination_keys))) # Store hash and its designated keys for this rule
        else: 
            candidate_files_for_action = [(h, list(rule_configured_destination_keys)) for h in eligible_hashes_after_view]

        final_details["files_skipped_due_to_override"] = files_skipped_due_to_override
        num_candidates_after_all_filters = len(candidate_files_for_action)
        logger.info(f"{log_prefix}: Search matched {num_matched_files_by_search_raw}. After view filter ({files_skipped_due_to_recent_view} skipped): {len(eligible_hashes_after_view)}. After override logic ({files_skipped_due_to_override} skipped): {num_candidates_after_all_filters} candidates.")

        items_for_action_loop = []
        if current_rule_action_type == 'force_in' and candidate_files_for_action:
            hashes_for_meta = [item[0] for item in candidate_files_for_action]
            fetched_meta_list, meta_errs = _fetch_metadata_for_hashes(app_config, rule_name, hashes_for_meta)
            final_details["metadata_errors"].extend(meta_errs)
            meta_map = {meta['hash']: meta for meta in fetched_meta_list}
            metadata_fetched_count = len(fetched_meta_list)

            for file_hash, configured_keys_for_file in candidate_files_for_action:
                if file_hash in meta_map:
                    items_for_action_loop.append((meta_map[file_hash], configured_keys_for_file))
                else:
                    action_params_for_log_failure = {"destination_service_keys": configured_keys_for_file, "error": "metadata_fetch_failed"}
                    log_file_action_detail(db_conn, rule_execution_id, file_hash, current_rule_action_type,
                                           json.dumps(action_params_for_log_failure), "failure",
                                           error_message="Metadata fetch failed pre-action")
            if not items_for_action_loop and hashes_for_meta: # All metadata fetches failed
                overall_rule_success_flag = False 
                final_summary_message_str = f"{log_prefix}: Failed. Could not fetch metadata for any 'force_in' candidates."
        else: # For non-force_in actions, or if force_in has no candidates
            items_for_action_loop = candidate_files_for_action # Contains (hash, rule_configured_destination_keys or empty list)

        num_files_to_attempt_action_on = len(items_for_action_loop)

        if overall_rule_success_flag and num_files_to_attempt_action_on > 0:
            logger.info(f"{log_prefix}: Attempting '{current_rule_action_type}' for {num_files_to_attempt_action_on} entries.")

            if current_rule_action_type == 'add_to':
                # For 'add_to', all items use the same rule_configured_destination_keys
                hashes_for_add = [item[0] for item in items_for_action_loop]
                action_params_json = json.dumps({"destination_service_keys": rule_configured_destination_keys})
                batch_add_result = _perform_action_add_to_files_batch(app_config, hashes_for_add, rule_configured_destination_keys, rule_name)
                final_details["action_processing_results"].append({**batch_add_result, "action_type": "add_to"})
                total_successful_add_to_operations = batch_add_result.get('total_successful_migrations',0) # Granular count

                for f_hash in hashes_for_add: # Iterate through all hashes attempted
                    is_successful_for_file = f_hash not in batch_add_result.get('files_with_some_errors', {})
                    if is_successful_for_file:
                        total_files_added_successfully += 1
                        log_file_action_detail(db_conn, rule_execution_id, f_hash, "add_to", action_params_json, "success")
                        if not is_manual_run:
                            should_set_override = True
                            existing_override = get_conflict_override(db_conn, f_hash, "placement", None)
                            if existing_override:
                                _win_id, win_imp, win_act_type, _ = existing_override
                                if win_imp > current_rule_importance: should_set_override = False
                                elif win_imp == current_rule_importance:
                                    if win_act_type == 'force_in': should_set_override = False
                                    elif win_act_type == 'add_to' and _win_id != rule_id: should_set_override = False
                            
                            if should_set_override:
                                set_conflict_override(db_conn, f_hash, "placement", None,
                                                      rule_id, current_rule_importance, 'add_to')
                                diagnostic_override = get_conflict_override(db_conn, f_hash, "placement", None)
                                logger.info(f"{log_prefix}: DIAGNOSTIC - File {f_hash}, Action add_to. Set Override. Read back: {diagnostic_override}")
                            else:
                                logger.info(f"{log_prefix}: File {f_hash}, Action add_to. Override NOT SET due to existing more important or equal 'force_in' winner. Existing: {existing_override}")
                    else:
                        errs = batch_add_result['files_with_some_errors'][f_hash]
                        log_file_action_detail(db_conn, rule_execution_id, f_hash, "add_to", json.dumps({"destination_service_keys": rule_configured_destination_keys, "errors": errs}), "failure", str(errs[0]['message']) if errs else "Add_to failed")
                if not batch_add_result.get('success', True): # Check overall batch success if defined
                    overall_rule_success_flag = False


            elif current_rule_action_type in ['add_tags', 'remove_tags']:
                mode = 0 if current_rule_action_type == 'add_tags' else 1
                hashes_for_tag_action = [item[0] for item in items_for_action_loop]
                action_params_json = json.dumps({"tag_service_key": tag_service_key_for_action, "tags": tags_for_action, "mode": mode})
                tag_res = _perform_action_manage_tags(app_config, hashes_for_tag_action, tag_service_key_for_action, tags_for_action, mode, rule_name)
                final_details["action_processing_results"].append({**tag_res, "action_type": current_rule_action_type})
                log_status = "success" if tag_res.get("success") else "failure"
                log_err = None if tag_res.get("success") else tag_res.get("message")
                for f_hash in hashes_for_tag_action: # Log detail for each attempted file
                     log_file_action_detail(db_conn, rule_execution_id, f_hash, current_rule_action_type, action_params_json, log_status, error_message=log_err)
                if tag_res.get("success"):
                    total_files_tag_action_success_on = tag_res.get("files_processed_count", len(hashes_for_tag_action)) # Assume all processed if success true
                else: overall_rule_success_flag = False

            elif current_rule_action_type == 'modify_rating':
                action_params_json = json.dumps({"rating_service_key": rating_service_key_for_action, "rating_value": rating_value_for_action})
                for file_hash, _ in items_for_action_loop: # items are (hash, empty_dest_keys_list)
                    rating_res = _perform_action_modify_rating(app_config, file_hash, rating_service_key_for_action, rating_value_for_action, rule_name)
                    final_details["action_processing_results"].append({**rating_res, "hash":file_hash, "action_type": "modify_rating"})
                    log_status = "success" if rating_res.get("success") else "failure"
                    log_err = None if rating_res.get("success") else str(rating_res.get("errors",["Rating failed"])[0].get('message', 'Unknown'))
                    log_file_action_detail(db_conn, rule_execution_id, file_hash, "modify_rating", action_params_json, log_status, error_message=log_err)
                    if rating_res.get("success"):
                        total_files_rating_modified_successfully += 1
                        if not is_manual_run:
                            should_set_override = True
                            existing_override = get_conflict_override(db_conn, file_hash, "rating", rating_service_key_for_action)
                            if existing_override:
                                _win_id, win_imp, _win_act_type, _win_val_json = existing_override
                                if win_imp > current_rule_importance: should_set_override = False
                                elif win_imp == current_rule_importance and _win_id != rule_id: should_set_override = False
                                # If win_id == rule_id and same importance, current action (new value or re-affirm) wins/updates
                            
                            if should_set_override:
                                set_conflict_override(db_conn, file_hash, "rating", rating_service_key_for_action,
                                                      rule_id, current_rule_importance, 'modify_rating',
                                                      rating_value_to_set=rating_value_for_action)
                                diagnostic_override = get_conflict_override(db_conn, file_hash, "rating", rating_service_key_for_action)
                                logger.info(f"{log_prefix}: DIAGNOSTIC - File {file_hash}, Action modify_rating. Set Override. Read back: {diagnostic_override}")
                            else:
                                logger.info(f"{log_prefix}: File {file_hash}, Action modify_rating. Override NOT SET due to existing more important winner. Existing: {existing_override}")
                    else: overall_rule_success_flag = False

            elif current_rule_action_type == 'force_in':
                # items_for_action_loop contains (metadata_object, rule_configured_destination_keys)
                meta_list_for_force_in = [item[0] for item in items_for_action_loop]
                # All items in this batch use the same rule_configured_destination_keys for this rule.
                action_params_json_force_in = json.dumps({"destination_service_keys": rule_configured_destination_keys})
                logger.info(f"{log_prefix}: ForceIn with configured_keys: {rule_configured_destination_keys} for {len(meta_list_for_force_in)} files.")

                all_local_keys_set = {s['service_key'] for s in available_services if isinstance(s,dict) and s.get('type') == 2 and 'service_key' in s}
                batch_force_res = _perform_action_force_in_batch(app_config, meta_list_for_force_in, rule_configured_destination_keys,
                                                                 all_local_keys_set, rule_name, available_services)
                final_details["action_processing_results"].append({**batch_force_res, "action_type": "force_in", "configured_dest_keys_used": rule_configured_destination_keys})

                for f_hash_ok in batch_force_res.get("files_fully_successful", []):
                    total_files_forced_successfully +=1
                    log_file_action_detail(db_conn, rule_execution_id, f_hash_ok, "force_in", action_params_json_force_in, "success")
                    if not is_manual_run:
                        should_set_override = True
                        existing_override = get_conflict_override(db_conn, f_hash_ok, "placement", None)
                        if existing_override:
                            _win_id, win_imp, win_act_type, _ = existing_override
                            if win_imp > current_rule_importance: should_set_override = False
                            elif win_imp == current_rule_importance:
                                # If existing is 'add_to' of same importance, 'force_in' wins.
                                # If existing is 'force_in' of same importance AND different rule, current one should have been skipped.
                                # If same rule, it's just re-affirming. 'force_in' claims win over 'add_to' of same importance.
                                if win_act_type == 'force_in' and _win_id != rule_id: should_set_override = False 
                                # else 'force_in' will win (either over 'add_to' or re-affirming self)
                        
                        if should_set_override:
                            set_conflict_override(db_conn, f_hash_ok, "placement", None,
                                                  rule_id, current_rule_importance, 'force_in')
                            diagnostic_override = get_conflict_override(db_conn, f_hash_ok, "placement", None)
                            logger.info(f"{log_prefix}: DIAGNOSTIC - File {f_hash_ok}, Action force_in. Set Override. Read back: {diagnostic_override}")
                        else:
                            logger.info(f"{log_prefix}: File {f_hash_ok}, Action force_in. Override NOT SET due to existing more important winner or other same-imp force_in. Existing: {existing_override}")
                            
                for f_hash_bad, err_detail in batch_force_res.get("files_with_errors", {}).items():
                    err_msg_short = f"Phase: {err_detail.get('phase')}, Errors: {str(err_detail.get('errors'))[:100]}"
                    log_params_with_failure = {**json.loads(action_params_json_force_in), "failure_details": err_detail}
                    log_file_action_detail(db_conn, rule_execution_id, f_hash_bad, "force_in", json.dumps(log_params_with_failure), "failure", error_message=err_msg_short)

                if not batch_force_res.get('success', True): # Check overall batch success
                    overall_rule_success_flag = False
        
        #  Add info about override logging to final_details ---
        final_details["override_detail_logging_enabled"] = log_overridden_actions_setting
        if not log_overridden_actions_setting and files_skipped_due_to_override > 0:
            final_details["note_on_skipped_overrides"] = f"{files_skipped_due_to_override} files were skipped due to overrides; detailed logs for these skips were not recorded due to settings."
        # Construct final summary message
        succeeded_count_total = total_files_added_successfully + total_files_forced_successfully + total_files_tag_action_success_on + total_files_rating_modified_successfully
        if num_matched_files_by_search_raw == 0:
            final_summary_message_str = f"{log_prefix}: Completed. No files matched the search criteria."
        elif num_candidates_after_all_filters == 0 : # Matched but all filtered out
            final_summary_message_str = f"{log_prefix}: Completed. No files eligible after filters from {num_matched_files_by_search_raw} search matches. (View: {files_skipped_due_to_recent_view}, Override: {files_skipped_due_to_override})"
        elif num_files_to_attempt_action_on == 0 and num_candidates_after_all_filters > 0: # e.g. force_in failed all metadata
             if "Failed. Could not fetch metadata" not in final_summary_message_str: # Avoid overriding more specific error
                final_summary_message_str = f"{log_prefix}: Completed. {num_candidates_after_all_filters} candidates identified, but none proceeded to action (e.g., metadata fetch failed for all)."
        elif overall_rule_success_flag:
            final_summary_message_str = f"{log_prefix}: Completed. Attempted '{current_rule_action_type}' on {num_files_to_attempt_action_on} files, succeeded for {succeeded_count_total}."
            if final_details.get("translation_warnings"):
                final_summary_message_str += f" ({len(final_details['translation_warnings'])} translation notes)."
        elif "processing started" in final_summary_message_str: # Error occurred, but not one that overwrote the initial message
            if num_files_to_attempt_action_on > 0:
                final_summary_message_str = f"{log_prefix}: Completed with errors during action '{current_rule_action_type}'. Succeeded for {succeeded_count_total}/{num_files_to_attempt_action_on} files."
            elif final_details.get("critical_error"): # Error before action attempts
                 final_summary_message_str = f"{log_prefix}: Failed. {final_details.get('critical_error')}"
            else: # Default if specific error not captured in summary
                final_summary_message_str = f"{log_prefix}: Failed before actions could be attempted. Check logs for rule_execution_id {rule_execution_id}."


        logger.info(f"{log_prefix} Final Summary: {final_summary_message_str}")

    except Exception as main_exc:
        overall_rule_success_flag = False
        error_message_for_summary = str(main_exc)
        # Check if it's a known "abort" type message that's already informative
        if "Aborting." in error_message_for_summary or "ABORTED" in error_message_for_summary:
            final_summary_message_str = error_message_for_summary # Use the specific abort message
        else:
            final_summary_message_str = f"{log_prefix}: CRITICAL EXCEPTION: {error_message_for_summary}"
        
        logger.error(f"{log_prefix}: EXCEPTION CAUGHT IN MAIN EXECUTE_SINGLE_RULE: {error_message_for_summary}", exc_info=True)
        final_details["critical_error"] = str(main_exc) # Store original exception string
        final_details["critical_error_traceback_summary"] = traceback.format_exc(limit=3)

    finally:
        db_status_log = "unknown_final"
        succeeded_actions_final_count = total_files_added_successfully + total_files_forced_successfully + total_files_tag_action_success_on + total_files_rating_modified_successfully
        if overall_rule_success_flag:
            if succeeded_actions_final_count > 0 : db_status_log = "success_actions_processed"
            elif num_files_to_attempt_action_on > 0 and succeeded_actions_final_count == 0: db_status_log = "success_actions_attempted_none_succeeded" # All failed
            elif num_candidates_after_all_filters > 0 and num_files_to_attempt_action_on == 0: # e.g. all metadata failed for force_in
                 db_status_log = "success_no_actions_performed"
            elif num_candidates_after_all_filters == 0 and num_matched_files_by_search_raw > 0:
                 db_status_log = "success_no_actions_eligible"
            elif num_matched_files_by_search_raw == 0: db_status_log = "success_no_matches"
            else: db_status_log = "success_completed" # General success if no actions but no errors
        else: # overall_rule_success_flag is False
            summary_lower = final_summary_message_str.lower()
            if "versioning failed" in summary_lower or "failed to get or create active rule version" in summary_lower: db_status_log = "error_versioning"
            elif "could not load hydrus services" in summary_lower: db_status_log = "error_services_load"
            elif "aborted due to critical translation error" in summary_lower : db_status_log = "failure_translation"
            elif "failed hydrus file search" in summary_lower: db_status_log = "failure_search"
            elif "malformed 'action'" in summary_lower or "rule has no conditions and generated no search predicates" in summary_lower or "requires valid" in summary_lower : db_status_log = "failure_setup"
            elif "could not fetch metadata" in summary_lower and "force_in" in current_rule_action_type.lower() : db_status_log = "failure_metadata"
            elif succeeded_actions_final_count < num_files_to_attempt_action_on and num_files_to_attempt_action_on > 0: db_status_log = "failure_action_partial"
            elif num_files_to_attempt_action_on > 0 and succeeded_actions_final_count == 0 : db_status_log = "failure_action_all"
            elif final_details.get("critical_error"): db_status_log = "error_critical_runtime"
            else: db_status_log = "failure_unknown"

        try:
            details_json_db = json.dumps(final_details)
            if db_conn: # Ensure db_conn is not None from a higher level commit/close
                cursor = db_conn.cursor() # Re-obtain cursor if necessary, though usually fine
                cursor.execute('''
                    UPDATE rule_executions_in_run
                    SET end_time = ?, status = ?, matched_search_count = ?,
                        eligible_for_action_count = ?, actions_attempted_count = ?,
                        actions_succeeded_count = ?, summary_message_from_logic = ?,
                        details_json_from_logic = ?
                    WHERE rule_execution_id = ?
                ''', (
                    datetime.utcnow().isoformat() + "Z", db_status_log,
                    num_matched_files_by_search_raw,
                    num_candidates_after_all_filters, # This is files after override filter
                    num_files_to_attempt_action_on,   # This is files for which action was actually tried (e.g. after metadata for force_in)
                    succeeded_actions_final_count,
                    final_summary_message_str,
                    details_json_db,
                    rule_execution_id
                ))
            else:
                logger.error(f"{log_prefix}: DB connection was None, cannot perform final update to rule_executions_in_run.")

        except sqlite3.Error as e_db_final:
            logger.error(f"{log_prefix}: DB Error during final UPDATE to rule_executions_in_run: {e_db_final}")
        except Exception as e_final_generic:
             logger.error(f"{log_prefix}: Generic error during final UPDATE to rule_executions_in_run: {e_final_generic}", exc_info=True)

    return {
        "success": overall_rule_success_flag,
        "message": final_summary_message_str,
        "rule_id": rule_id, "rule_name": rule_name,
        "rule_execution_id_for_log": rule_execution_id,
        "action_performed": current_rule_action_type,
        "files_matched_by_search": num_matched_files_by_search_raw,
        "files_metadata_fetched": metadata_fetched_count,
        "files_action_attempted_on": num_files_to_attempt_action_on,
        "files_added_successfully": total_files_added_successfully, # Files where add_to wholly succeeded
        "total_successful_add_to_file_service_operations": total_successful_add_to_operations, # Granular add_to ops
        "files_forced_successfully": total_files_forced_successfully,
        "files_tag_action_success_on": total_files_tag_action_success_on,
        "files_rating_modified_successfully": total_files_rating_modified_successfully,
        "files_skipped_due_to_override": files_skipped_due_to_override,
        "files_skipped_due_to_recent_view": files_skipped_due_to_recent_view,
        "details": final_details
    }
