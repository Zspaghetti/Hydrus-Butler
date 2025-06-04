import os
import sqlite3 # Added for specific exception handling if needed, though get_db_connection handles general
from flask import (
    Blueprint, render_template, request, jsonify, flash, redirect, url_for,
    current_app, send_from_directory
)
import json
import uuid
from datetime import datetime
from urllib.parse import unquote

# Imports from our new modules
from app_config import (
    save_settings_to_file,
    save_rules_to_file, # This function now handles override cleanup for deleted rules
    load_rules as app_config_load_rules
)
from database import (
    get_db_connection,
    remove_overrides_for_rule, # Still used for targeted update override removal
    get_or_create_active_rule_version
)
from hydrus_interface import call_hydrus_api
from rule_processing import execute_single_rule, _ensure_available_services, _parse_time_range_for_logs
from scheduler_tasks import schedule_rules_job

# Create a Blueprint
views_bp = Blueprint('views', __name__)

# --- Route Handlers ---

@views_bp.route('/')
def index():
    current_settings = current_app.config.get('HYDRUS_SETTINGS', {})
    return render_template('index.html',
                           current_theme=current_settings.get('theme', 'default'),
                           current_settings=current_settings)

@views_bp.route('/settings')
def settings_page():
    current_settings = current_app.config.get('HYDRUS_SETTINGS', {})
    settings_for_template = current_settings.copy()
    if 'api_key' in settings_for_template:
        settings_for_template['api_key'] = '' # Mask API key
    return render_template('settings.html', current_settings=settings_for_template)

@views_bp.route('/save_settings', methods=['POST'])
def handle_save_settings():
    current_app.logger.info("--- Received request to save settings (views.py) ---")
    submitted_data = {
        'api_address': request.form.get('api_address', '').strip(),                       
        'api_key': request.form.get('api_key', '').strip(),                             
        'rule_interval_seconds': request.form.get('rule_interval_seconds'),             
        'last_viewed_threshold_seconds': request.form.get('last_viewed_threshold_seconds'), 
        'show_run_notifications': request.form.get('show_run_notifications'),           
        'show_run_all_notifications': request.form.get('show_run_all_notifications'),   
        'theme': request.form.get('theme'),                                             
        'butler_name': request.form.get('butler_name', '').strip(),                     
        'log_overridden_actions': request.form.get('log_overridden_actions')          
    }
    current_app.logger.info(f"Processed form data for save: {submitted_data}")

    save_success, saved_settings_dict = save_settings_to_file(submitted_data, current_app.config)

    if save_success and saved_settings_dict:
        current_app.logger.info("Settings successfully saved to file and app config updated by save_settings_to_file.")
        schedule_rules_job(current_app._get_current_object())
        current_app.logger.info("Scheduler job re-evaluated based on new settings.")

        fetch_message = ""
        if saved_settings_dict.get('api_address'):
            current_app.logger.info("Attempting to fetch services with new settings...")
            services_list = _ensure_available_services(current_app.config, "SaveSettings")
            if services_list:
                 fetch_message = f"Successfully fetched {len(services_list)} services from Hydrus."
                 current_app.logger.info(fetch_message)
            else:
                 if not saved_settings_dict.get('api_address'):
                      fetch_message = "Settings saved. Hydrus API address is not configured, services not fetched."
                 else:
                      fetch_message = "Settings saved, but failed to fetch/parse service list from Hydrus API."
                 current_app.logger.warning(fetch_message)
        else:
            current_app.logger.info("Hydrus API address not configured after saving. Skipping service fetch.")
            current_app.config['AVAILABLE_SERVICES'] = []
            fetch_message = "Settings saved. Hydrus API address is not configured, so services were not fetched."

        flash(f"Settings saved. {fetch_message}", "success" if "Successfully fetched" in fetch_message or "not configured" in fetch_message else "info")
        return redirect(url_for('views.settings_page'))
    else:
        current_app.logger.error("Failed to save settings (save_settings_to_file returned false).")
        flash("Failed to write settings file. Check file permissions or logs.", "error")
        return redirect(url_for('views.settings_page'))


@views_bp.route('/get_all_services')
def get_all_services_route():
    services_list = _ensure_available_services(current_app.config, "GetAllServicesRoute")
    if services_list:
        return jsonify({"success": True, "services": services_list}), 200
    else:
        settings = current_app.config.get('HYDRUS_SETTINGS', {})
        if not settings.get('api_address'):
            message = "Hydrus API address is not configured. Cannot fetch services."
            return jsonify({"success": False, "message": message, "services": []}), 400
        else:
            message = "Failed to fetch or parse services from Hydrus API. Check logs."
            return jsonify({"success": False, "message": message, "services": []}), 503


@views_bp.route('/get_client_settings', methods=['GET'])
def get_client_settings_route():
    settings = current_app.config.get('HYDRUS_SETTINGS', {})
    client_settings = {
        'show_run_notifications': settings.get('show_run_notifications', True),
        'show_run_all_notifications': settings.get('show_run_all_notifications', True),
        'theme': settings.get('theme', 'default')
    }
    return jsonify({"success": True, "settings": client_settings}), 200

@views_bp.route('/rules', methods=['GET'])
def get_rules_route():
    rules = current_app.config.get('AUTOMATION_RULES', [])
    return jsonify({"success": True, "rules": rules}), 200

@views_bp.route('/add_rule', methods=['POST'])
def add_rule_route():
    current_app.logger.info("Attempting to add or update rule (views.py).")
    if not request.is_json:
        return jsonify({"success": False, "message": "Request must be JSON."}), 415

    rule_data_from_payload = request.get_json()
    rule_id_from_payload = rule_data_from_payload.get('id')
    action_performed_text = 'updated' if rule_id_from_payload else 'added'
    
    # --- Validation ---
    required_fields = ['name', 'priority', 'conditions', 'action']
    if not all(field in rule_data_from_payload for field in required_fields):
        missing = [field for field in required_fields if field not in rule_data_from_payload]
        current_app.logger.warning(f"Missing required rule fields: {missing}")
        return jsonify({"success": False, "message": f"Missing required rule fields: {', '.join(missing)}."}), 400
    try:
        priority = int(rule_data_from_payload['priority'])
        rule_data_from_payload['priority'] = priority
    except (ValueError, TypeError):
        current_app.logger.warning("Priority must be a valid number.")
        return jsonify({"success": False, "message": "Priority must be a valid number."}), 400
    if not isinstance(rule_data_from_payload.get('conditions'), list):
        current_app.logger.warning("Conditions field must be a list.")
        return jsonify({"success": False, "message": "Conditions field must be a list."}), 400
    action = rule_data_from_payload.get('action', {})
    if not isinstance(action, dict) or 'type' not in action or not action.get('type'):
        current_app.logger.warning("Action must be an object with a non-empty 'type'.")
        return jsonify({"success": False, "message": "Action must be an object with a non-empty 'type'."}), 400
    action_type_value = action.get('type')
    # (Specific action validation as before)
    if action_type_value in ['add_to', 'force_in']:
        dest_keys = action.get('destination_service_keys')
        if not dest_keys or not isinstance(dest_keys, list) or not all(isinstance(k, str) and k for k in dest_keys):
            msg = f"Action '{action_type_value}' requires 'destination_service_keys' as non-empty list of non-empty strings."
            current_app.logger.warning(msg)
            return jsonify({"success": False, "message": msg}), 400
        if len(set(dest_keys)) != len(dest_keys):
             msg = f"Action '{action_type_value}': Destination service keys must be unique."
             current_app.logger.warning(msg)
             return jsonify({"success": False, "message": msg}), 400
    elif action_type_value in ['add_tags', 'remove_tags']:
        tag_key = action.get('tag_service_key')
        tags_proc = action.get('tags_to_process')
        if not tag_key or not isinstance(tag_key, str):
            msg = f"Action '{action_type_value}' requires 'tag_service_key' as non-empty string."
            current_app.logger.warning(msg)
            return jsonify({"success": False, "message": msg}), 400
        if not tags_proc or not isinstance(tags_proc, list) or not all(isinstance(t, str) and t for t in tags_proc):
            msg = f"Action '{action_type_value}' requires 'tags_to_process' as non-empty list of non-empty strings."
            current_app.logger.warning(msg)
            return jsonify({"success": False, "message": msg}), 400
    elif action_type_value == 'modify_rating':
        rating_key = action.get('rating_service_key')
        if 'rating_value' not in action: 
            msg = f"Action '{action_type_value}' is missing 'rating_value'."
            current_app.logger.warning(msg)
            return jsonify({"success": False, "message": msg}), 400
        if not rating_key or not isinstance(rating_key, str):
            msg = f"Action '{action_type_value}' requires 'rating_service_key' as non-empty string."
            current_app.logger.warning(msg)
            return jsonify({"success": False, "message": msg}), 400
    else:
        current_app.logger.warning(f"Unsupported action type for validation: {action_type_value}")
        return jsonify({"success": False, "message": f"Unsupported action type: {action_type_value}."}), 400
    # --- End of Validation ---

    # Load current rules from file to form the basis of the new rules list
    rules_list_for_save = app_config_load_rules() 
    db_conn = None
    final_rule_id_to_return = rule_id_from_payload
    final_rule_name_to_return = rule_data_from_payload.get('name')

    try:
        db_conn = get_db_connection()
        
        # Prepare rule_data object that will be versioned and saved
        # This is `rule_data_from_payload` potentially augmented with ID/name
        rule_data_for_db_and_list = rule_data_from_payload.copy()


        if not rule_id_from_payload: # ADD
            rule_data_for_db_and_list['id'] = str(uuid.uuid4())
            final_rule_id_to_return = rule_data_for_db_and_list['id']
            
            submitted_name = rule_data_for_db_and_list.get('name', '').strip()
            if not submitted_name:
                max_rule_num = 0
                for r_item in rules_list_for_save: # Check against existing rules
                    r_name = r_item.get('name', '')
                    if r_name.startswith("Rule ") and r_name[5:].isdigit():
                        try: num = int(r_name[5:]); max_rule_num = max(max_rule_num, num)
                        except ValueError: pass
                rule_data_for_db_and_list['name'] = f"Rule {max_rule_num + 1}"
            else:
                rule_data_for_db_and_list['name'] = submitted_name
            final_rule_name_to_return = rule_data_for_db_and_list['name']
            
            rules_list_for_save.append(rule_data_for_db_and_list) # Add to the list that will be saved
        else: # UPDATE
            found_idx = next((i for i, r in enumerate(rules_list_for_save) if r.get('id') == rule_id_from_payload), -1)
            if found_idx == -1:
                return jsonify({"success": False, "message": f"Rule ID {rule_id_from_payload} not found for update."}), 404
            
            # Clear overrides for this specific rule ID as its definition is changing
            deleted_overrides = remove_overrides_for_rule(db_conn, rule_id_from_payload)
            if deleted_overrides == -1: # Error
                db_conn.rollback() # Rollback before returning
                return jsonify({"success": False, "message": "DB error removing overrides for rule update."}), 500
            current_app.logger.info(f"Invalidated {deleted_overrides} overrides for rule ID {rule_id_from_payload} due to update.")
            
            submitted_name_update = rule_data_for_db_and_list.get('name', '').strip()
            if not submitted_name_update:
                rule_data_for_db_and_list['name'] = rules_list_for_save[found_idx].get('name', f"Rule (ID: {rule_id_from_payload[:8]})")
            else:
                rule_data_for_db_and_list['name'] = submitted_name_update
            final_rule_name_to_return = rule_data_for_db_and_list['name']

            rules_list_for_save[found_idx] = rule_data_for_db_and_list # Update in the list for saving

        # Version the rule (new or updated)
        active_version_id = get_or_create_active_rule_version(db_conn, rule_data_for_db_and_list)
        if not active_version_id:
            db_conn.rollback()
            return jsonify({"success": False, "message": "Failed to version rule in database."}), 500
        
        db_conn.commit() # Commit versioning and (if update) specific override removal
        current_app.logger.info(f"Rule version '{active_version_id}' ensured in DB for rule ID '{rule_data_for_db_and_list['id']}'. DB changes committed.")

        # Now, save the modified rules_list_for_save to file.
        # save_rules_to_file will handle cleaning overrides for any *other* rules that might have been
        # deleted if this operation was part of a larger conceptual "save all" (though this route is for single add/update).
        # More importantly, it updates current_app.config['AUTOMATION_RULES'].
        if save_rules_to_file(rules_list_for_save, current_app.config):
            current_app.logger.info(f"Rule '{final_rule_name_to_return}' (ID: {final_rule_id_to_return}) {action_performed_text} successfully. Rules file and app config updated.")
            return jsonify({
                "success": True, "message": f"Rule {action_performed_text} successfully.",
                "rule_id": final_rule_id_to_return, "rule_name": final_rule_name_to_return
            }), 200
        else:
            # DB changes (versioning, specific override clear) were committed.
            # But file save failed. This is an inconsistent state.
            # save_rules_to_file's own error handling (including potential rollback of its DB ops) would have run.
            current_app.logger.error(f"DB operations for rule '{final_rule_name_to_return}' committed, but subsequent save_rules_to_file failed.")
            return jsonify({"success": False, "message": "Rule data processed for DB, but failed to save main rule list to file. Check logs."}), 500

    except sqlite3.Error as e_sql:
        if db_conn: db_conn.rollback()
        current_app.logger.error(f"SQLite DB error during add/update rule: {e_sql}", exc_info=True)
        return jsonify({"success": False, "message": f"Database error: {e_sql}"}), 500
    except Exception as e:
        if db_conn: db_conn.rollback()
        current_app.logger.error(f"Unexpected error during add/update rule: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"Unexpected error: {e}"}), 500
    finally:
        if db_conn: db_conn.close()


@views_bp.route('/rules/<rule_id>', methods=['DELETE'])
def delete_rule_route(rule_id):
    current_app.logger.info(f"Attempting to delete rule ID: {rule_id} (views.py)")
    
    rules_before_delete = app_config_load_rules() 
    rule_to_delete = next((r for r in rules_before_delete if r.get('id') == rule_id), None)
    if not rule_to_delete:
        return jsonify({"success": False, "message": f"Rule ID {rule_id} not found."}), 404

    db_conn = None
    try:
        db_conn = get_db_connection()
        deleted_overrides = remove_overrides_for_rule(db_conn, rule_id)
        if deleted_overrides == -1: # Error
            db_conn.rollback()
            current_app.logger.error(f"DB error removing overrides for deleted rule ID {rule_id}.")
            return jsonify({"success": False, "message": "Database error while clearing overrides for the rule."}), 500
        db_conn.commit()
        current_app.logger.info(f"Cleared {deleted_overrides} overrides for deleted rule ID {rule_id}.")

        rules_after_delete_list = [r for r in rules_before_delete if r.get('id') != rule_id]
        
        if save_rules_to_file(rules_after_delete_list, current_app.config):
            current_app.logger.info(f"Rule ID {rule_id} successfully deleted. Rules file and app config updated.")
            return jsonify({"success": True, "message": f"Rule ID {rule_id} deleted."}), 200
        else:
            current_app.logger.error(f"save_rules_to_file failed during deletion of rule ID {rule_id} AFTER overrides were cleared. Rules list on disk/config might be out of sync with override DB state for this rule (it should be cleared).")
            # This is an inconsistent state, but overrides are cleared. The main rules file is the problem.
            return jsonify({"success": False, "message": f"Failed to save rules after deleting rule {rule_id}. Overrides cleared, but rules file update failed. Check logs."}), 500

    except sqlite3.Error as e_sql:
        if db_conn: db_conn.rollback()
        current_app.logger.error(f"SQLite DB error during delete rule {rule_id}: {e_sql}", exc_info=True)
        return jsonify({"success": False, "message": f"Database error: {e_sql}"}), 500
    except Exception as e:
        if db_conn: db_conn.rollback()
        current_app.logger.error(f"Unexpected error during delete rule {rule_id}: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"Unexpected error: {e}"}), 500
    finally:
        if db_conn: db_conn.close()

@views_bp.route('/run_rule/<rule_id_from_path>', methods=['POST'])
def run_single_rule_route(rule_id_from_path):
    run_start_time = datetime.utcnow()
    run_id = str(uuid.uuid4())
    run_type = "manual_single"
    rule_name_log = f"Rule ID {rule_id_from_path}"
    current_app.logger.info(f"\n--- Manual Single Rule Trigger (views.py): Run ID {run_id[:8]} for {rule_name_log} ---")

    db_conn = None
    overall_run_status = "started"
    run_summary = f"Manual run for {rule_name_log} (ID {run_id[:8]}) started."
    exec_result_response = {}

    try:
        db_conn = get_db_connection()
        cursor = db_conn.cursor()
        cursor.execute("INSERT INTO execution_runs (run_id, run_type, start_time, status, summary_message) VALUES (?, ?, ?, ?, ?)",
                       (run_id, run_type, run_start_time.isoformat() + "Z", overall_run_status, run_summary))
        db_conn.commit()

        # Load rules using app_config_load_rules to ensure consistency with how app.config is populated
        rules_in_system = app_config_load_rules() # This loads from file and sorts
        rule_to_run = next((r for r in rules_in_system if r.get('id') == rule_id_from_path), None)

        if not rule_to_run:
            run_summary = f"Rule ID {rule_id_from_path} not found in current rules. Manual run aborted."
            overall_run_status = "failed_early_rule_not_found"
            # exec_result_response will be built in finally or if error caught by general Exception
        else:
            rule_name_log = rule_to_run.get('name', rule_id_from_path) # Update rule_name_log
            settings = current_app.config.get('HYDRUS_SETTINGS', {})
            if not settings.get('api_address') or not settings.get('api_key'):
                 run_summary = f"Hydrus API not configured. Manual run for '{rule_name_log}' aborted."
                 overall_run_status = "failed_early_config"
                 raise Exception(run_summary)

            if not _ensure_available_services(current_app.config, f"Manual_Single_Run_{rule_id_from_path[:8]}"):
                run_summary = f"Could not fetch Hydrus services. Manual run for '{rule_name_log}' aborted."
                overall_run_status = "failed_early_services"
                raise Exception(run_summary)

            exec_result_response = execute_single_rule(
                current_app.config, db_conn, rule_to_run,
                run_id, 1, is_manual_run=True # is_manual_run=True bypasses override checks for this specific rule
            )
            if exec_result_response.get('success'):
                overall_run_status = "completed_ok"
                run_summary = f"Manual run for '{rule_name_log}' complete. Rule: {exec_result_response.get('message','OK')}"
            else:
                overall_run_status = "completed_with_rule_failures"
                run_summary = f"Manual run for '{rule_name_log}' failed. Rule: {exec_result_response.get('message','Failed')}"
            db_conn.commit()
            current_app.logger.info(f"Manual Single Run (ID {run_id[:8]}): Rule execution DB changes committed.")
            
    except Exception as e:
        current_app.logger.error(f"Global error in run_single_rule_route for {rule_name_log}: {e}", exc_info=True)
        # Update run_summary if it was still the initial "started" message
        if "started" in run_summary and overall_run_status == "started":
             run_summary = f"Manual run for '{rule_name_log}' failed globally: {str(e)}"
        # Update overall_run_status if it hasn't been set to a more specific failure
        if overall_run_status == "started":
            overall_run_status = "failed_global_error"
        
        if db_conn: db_conn.rollback() # Rollback any partial DB changes from this try block
        
        # Ensure exec_result_response is populated for the final jsonify
        if not exec_result_response:
            exec_result_response = {"success": False, "message": run_summary, "rule_id": rule_id_from_path, 
                                    "details": {"critical_error_in_view": str(e)}}
        elif "message" not in exec_result_response or not exec_result_response["message"]:
            exec_result_response["message"] = run_summary
    finally:
        run_end_time = datetime.utcnow()
        if db_conn:
            try:
                cursor = db_conn.cursor()
                # Ensure summary reflects the most accurate state before DB update
                if "message" in exec_result_response and exec_result_response["message"] and "Rule:" not in run_summary:
                     run_summary = f"Manual run for '{rule_name_log}' outcome. Rule: {exec_result_response.get('message', 'Final state unknown')}"
                elif "started" in run_summary and overall_run_status != "started": # Generic update if specific exec_result_response message not available
                     run_summary = f"Manual run for '{rule_name_log}' finished with status: {overall_run_status}."

                cursor.execute("UPDATE execution_runs SET end_time = ?, status = ?, summary_message = ? WHERE run_id = ?",
                               (run_end_time.isoformat() + "Z", overall_run_status, run_summary, run_id))
                db_conn.commit()
            except Exception as e_final_db:
                current_app.logger.error(f"CRITICAL: Failed to update final status for manual single run {run_id}: {e_final_db}")
            finally:
                db_conn.close()
        current_app.logger.info(f"--- Manual Single Rule (views.py): Finished Run ID {run_id[:8]} ---")

    # Ensure these keys are always present in the response payload
    exec_result_response["overall_run_id_for_log"] = run_id
    exec_result_response["overall_run_status_for_log"] = overall_run_status
    if "success" not in exec_result_response: # Should be set by execute_single_rule or error handling
        exec_result_response["success"] = False
    if "message" not in exec_result_response:
        exec_result_response["message"] = run_summary
    if "rule_id" not in exec_result_response:
         exec_result_response["rule_id"] = rule_id_from_path

    http_status = 200
    if overall_run_status == "failed_early_rule_not_found": http_status = 404
    elif overall_run_status.startswith("failed"): http_status = 500
    elif not exec_result_response.get("success", False): http_status = 500 # If rule execution itself failed

    return jsonify(exec_result_response), http_status


@views_bp.route('/run_all_rules_manual', methods=['POST'])
def run_all_rules_manual_route():
    run_start_time = datetime.utcnow()
    run_id = str(uuid.uuid4())
    run_type = "manual_all" # Changed from "manual_all" to distinguish if needed, but "manual_all" is fine.
    current_app.logger.info(f"\n--- Manual 'Run All Rules' Trigger (views.py): Run ID {run_id[:8]} ---")

    db_conn = None
    overall_run_status = "started"
    run_summary = f"Manual 'Run All Rules' ({run_id[:8]}) started."
    all_individual_results = []
    # any_rule_proc_error = False # Replaced by checking total_failed_rules or critical_errors_in_loop

    try:
        db_conn = get_db_connection()
        cursor = db_conn.cursor()
        cursor.execute("INSERT INTO execution_runs (run_id, run_type, start_time, status, summary_message) VALUES (?, ?, ?, ?, ?)",
                       (run_id, run_type, run_start_time.isoformat() + "Z", overall_run_status, run_summary))
        db_conn.commit()

        # Load rules using app_config_load_rules to get the execution-sorted list
        rules_to_run = current_app.config.get('AUTOMATION_RULES', []) # Use live, sorted rules
        if not rules_to_run: # If app.config was empty, try loading from file as a fallback
            rules_to_run = app_config_load_rules()

        settings = current_app.config.get('HYDRUS_SETTINGS',{})
        if not settings.get('api_address') or not settings.get('api_key'):
             run_summary = f"Hydrus API not configured. Manual 'Run All' aborted."
             overall_run_status = "failed_early_config"
             raise Exception(run_summary) # Caught by general handler below
        
        if not rules_to_run:
            run_summary = "No rules defined. Manual 'Run All' completed without processing."
            overall_run_status = "completed_no_rules"
        else:
            if not _ensure_available_services(current_app.config, f"Manual_Run_All_{run_id[:8]}"):
                run_summary = f"Could not fetch Hydrus services. Manual 'Run All' aborted."
                overall_run_status = "failed_early_services"
                raise Exception(run_summary) # Caught by general handler below
            
            current_app.logger.info(f"Manual 'Run All' (ID {run_id[:8]}): Processing {len(rules_to_run)} rules in their execution order.")
            total_processed_rules = 0
            total_failed_rules = 0
            critical_errors_in_loop = 0

            for i, rule_instance in enumerate(rules_to_run):
                total_processed_rules += 1
                rule_name_log = rule_instance.get('name', rule_instance.get('id', 'Unnamed Rule'))
                current_app.logger.info(f"Manual 'Run All' (ID {run_id[:8]}): Executing Rule {i+1}/{len(rules_to_run)}: '{rule_name_log}'")
                try:
                    # For 'Run All Rules' (manual or scheduled), is_manual_run should be False
                    # so that override logic fully applies between rules in the run.
                    result = execute_single_rule(
                        current_app.config, db_conn, rule_instance,
                        run_id, i + 1, is_manual_run=False
                    )
                    all_individual_results.append(result)
                    if not result.get('success'):
                        total_failed_rules +=1
                        if result.get("details", {}).get("critical_error"): # Check if execute_single_rule reported a critical error
                            critical_errors_in_loop +=1
                except Exception as e_exec: # Catch exceptions from execute_single_rule itself, if any
                    total_failed_rules +=1
                    critical_errors_in_loop +=1
                    err_msg = f"CRITICAL unhandled error processing rule '{rule_name_log}' in manual run all: {str(e_exec)}"
                    current_app.logger.error(err_msg, exc_info=True)
                    all_individual_results.append({
                        "success": False, "message": err_msg,
                        "rule_id": rule_instance.get('id'), "rule_name": rule_name_log,
                        "details":{"critical_error_in_view_loop": str(e_exec)}
                    })
            
            if critical_errors_in_loop > 0:
                overall_run_status = "completed_with_critical_rule_errors"
            elif total_failed_rules > 0:
                overall_run_status = "completed_with_rule_failures"
            else:
                overall_run_status = "completed_ok"
            
            run_summary = f"Manual 'Run All' ({run_id[:8]}) {overall_run_status}. Processed {total_processed_rules} rules, {total_failed_rules} had issues ({critical_errors_in_loop} critical)."
        
        if db_conn: db_conn.commit() # Commit all rule execution details logged by execute_single_rule
        current_app.logger.info(f"Manual 'Run All' (ID {run_id[:8]}): All rule execution DB changes committed.")

    except Exception as e: # Catches exceptions from setup (API check, service fetch) or unexpected issues
        current_app.logger.error(f"Global error in run_all_rules_manual_route (Run ID {run_id[:8]}): {e}", exc_info=True)
        if "started" in run_summary and overall_run_status == "started": # If error happened before more specific summary
            run_summary = f"Manual 'Run All' ({run_id[:8]}) failed globally: {str(e)}"
        if overall_run_status == "started": # If status not updated by more specific failure
            overall_run_status = "failed_global_error"
        
        if db_conn: db_conn.rollback() # Rollback any partial DB changes from this try block
    finally:
        run_end_time = datetime.utcnow()
        if db_conn:
            try:
                cursor = db_conn.cursor()
                cursor.execute("UPDATE execution_runs SET end_time = ?, status = ?, summary_message = ? WHERE run_id = ?",
                               (run_end_time.isoformat() + "Z", overall_run_status, run_summary, run_id))
                db_conn.commit()
            except Exception as e_final_db:
                current_app.logger.error(f"CRITICAL: Failed to update final status for manual 'Run All' {run_id}: {e_final_db}")
            finally:
                db_conn.close()
        current_app.logger.info(f"--- Manual 'Run All Rules' (views.py): Finished Run ID {run_id[:8]} ---")

    response_payload = {
        "success": overall_run_status.startswith("completed") and not "error" in overall_run_status and not "failure" in overall_run_status, 
        "message": run_summary, "run_id_for_log": run_id,
        "results_per_rule": all_individual_results
    }
    http_status = 200
    if overall_run_status.startswith("failed") or "error" in overall_run_status or "failure" in overall_run_status:
        http_status = 500
    
    return jsonify(response_payload), http_status


@views_bp.route('/logs')
def logs_page_route():
    current_settings = current_app.config.get('HYDRUS_SETTINGS', {})
    return render_template('logs.html',
                           current_theme=current_settings.get('theme', 'default'),
                           current_settings=current_settings)

@views_bp.route('/logs/stats/files_processed_per_rule', methods=['GET'])
def get_log_stats_files_per_rule_route():
    db_conn = None
    try:
        start_iso, end_iso, time_frame_used = _parse_time_range_for_logs(request.args)
        db_conn = get_db_connection()
        cursor = db_conn.cursor()
        
        query = """
            SELECT rei.rule_id, rv.rule_name_at_version, SUM(COALESCE(rei.actions_succeeded_count, 0)) as total_files_successfully_actioned
            FROM rule_executions_in_run rei
            JOIN rule_versions rv ON rei.rule_version_id = rv.rule_version_id
            WHERE (rei.status LIKE 'success%' OR rei.status LIKE 'completed%') 
                  AND rei.actions_succeeded_count > 0 """
        params = []
        if time_frame_used != 'all':
            query += "AND rei.start_time >= ? AND rei.start_time <= ? "
            params.extend([start_iso, end_iso])
        query += """
            GROUP BY rei.rule_id, rv.rule_name_at_version
            HAVING total_files_successfully_actioned > 0
            ORDER BY total_files_successfully_actioned DESC;
        """ # Added rule_name_at_version to GROUP BY and SELECT
        cursor.execute(query, tuple(params))
        raw_stats = cursor.fetchall()

        # Get current rule names as a fallback if versioned name isn't ideal or for deleted rules
        current_rules_map = {rule['id']: rule['name'] for rule in current_app.config.get('AUTOMATION_RULES', [])}
        
        chart_data = []
        for row in raw_stats:
            rule_name = row['rule_name_at_version']
            if not rule_name or rule_name.startswith("Rule (ID:"): # Fallback if versioned name is generic
                rule_name = current_rules_map.get(row['rule_id'], f"Unknown/Deleted Rule (ID: {row['rule_id'][:8]})")

            chart_data.append({
                "rule_id": row['rule_id'],
                "rule_name": rule_name,
                "files_successfully_actioned": row['total_files_successfully_actioned']
            })


        return jsonify({
            "success": True, "data": chart_data, "time_frame_used": time_frame_used,
            "start_date_used": start_iso if time_frame_used != 'all' else "all_time",
            "end_date_used": end_iso if time_frame_used != 'all' else "all_time"
        }), 200
    except sqlite3.Error as e:
        current_app.logger.error(f"DB error in get_log_stats_files_per_rule: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"Database error: {e}"}), 500
    except Exception as e:
        current_app.logger.error(f"Error in get_log_stats_files_per_rule: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"Unexpected error: {e}"}), 500
    finally:
        if db_conn: db_conn.close()


@views_bp.route('/logs/search', methods=['GET'])
def search_detailed_logs_route():
    db_conn = None
    try:
        args = request.args
        limit = int(args.get('limit', 100)); offset = int(args.get('offset', 0))
        limit = max(1, min(limit, 1000)); offset = max(0, offset)
        sort_by = args.get('sort_by', 'timestamp_desc')
        
        allowed_sorts_fad = {
            "timestamp_desc": "fad.action_timestamp DESC", "timestamp_asc": "fad.action_timestamp ASC",
            "rule_name_asc": "rv.rule_name_at_version ASC, fad.action_timestamp DESC",
            "rule_name_desc": "rv.rule_name_at_version DESC, fad.action_timestamp DESC",
            "status_asc": "fad.status ASC, fad.action_timestamp DESC",
            "status_desc": "fad.status DESC, fad.action_timestamp DESC",
        }
        allowed_sorts_rei = {
            "timestamp_desc": "rei.start_time DESC", "timestamp_asc": "rei.start_time ASC",
            "rule_name_asc": "rv.rule_name_at_version ASC, rei.start_time DESC",
            "rule_name_desc": "rv.rule_name_at_version DESC, rei.start_time DESC",
            "status_asc": "rei.status ASC, rei.start_time DESC",
            "status_desc": "rei.status DESC, rei.start_time DESC",
        }
        order_by_clause = ""

        file_hash_q = args.get('file_hash'); rule_id_q = args.get('rule_id')
        run_id_q = args.get('run_id'); rule_exec_id_q = args.get('rule_execution_id')
        status_filter = args.get('status_filter')
        # Use unquote for search terms that might be URL encoded
        log_search_term_q = unquote(args.get('log_search_term', '')).strip()


        start_iso, end_iso, time_frame_used = _parse_time_range_for_logs(args) # time_frame_used not directly used here but parsed

        db_conn = get_db_connection()
        cursor = db_conn.cursor()
        
        base_fields, base_from_join = "", ""
        where_clauses, query_params = [], []
        search_type_resp, query_params_resp = "general", {} # query_params_resp is for the response, not SQL
        
        # --- Query Building Logic ---
        if file_hash_q:
            search_type_resp = "file_hash"; query_params_resp["file_hash"] = file_hash_q
            base_fields = """ fad.log_id, fad.rule_execution_id, fad.file_hash, fad.action_type_performed,
                              fad.action_parameters_json_at_exec, fad.status, fad.error_message,
                              fad.override_info_json, fad.action_timestamp, rei.run_id, rei.rule_id, 
                              rei.rule_version_id, rv.rule_name_at_version, rv.importance_at_version AS rule_importance_at_version, er.run_type """ # Renamed priority_at_version
            base_from_join = """ FROM file_action_details fad JOIN rule_executions_in_run rei ON fad.rule_execution_id = rei.rule_execution_id
                                 JOIN rule_versions rv ON rei.rule_version_id = rv.rule_version_id
                                 JOIN execution_runs er ON rei.run_id = er.run_id """
            where_clauses.append("fad.file_hash = ?"); query_params.append(file_hash_q)
            if not status_filter or "skip_action" not in status_filter.lower(): # Default: Exclude skips for direct file hash search unless specified
                 where_clauses.append("fad.action_type_performed != 'skip_action'")
            order_by_clause = allowed_sorts_fad.get(sort_by, "fad.action_timestamp DESC")

        elif rule_exec_id_q:
            search_type_resp = "rule_execution_id_details"; query_params_resp["rule_execution_id"] = rule_exec_id_q
            base_fields = """ fad.log_id, fad.rule_execution_id, fad.file_hash, fad.action_type_performed,
                              fad.action_parameters_json_at_exec, fad.status, fad.error_message,
                              fad.override_info_json, fad.action_timestamp, rei.run_id, rei.rule_id, 
                              rei.rule_version_id, rv.rule_name_at_version, rv.importance_at_version AS rule_importance_at_version, er.run_type """
            base_from_join = """ FROM file_action_details fad JOIN rule_executions_in_run rei ON fad.rule_execution_id = rei.rule_execution_id
                                 JOIN rule_versions rv ON rei.rule_version_id = rv.rule_version_id
                                 JOIN execution_runs er ON rei.run_id = er.run_id """
            where_clauses.append("fad.rule_execution_id = ?"); query_params.append(rule_exec_id_q)
            order_by_clause = allowed_sorts_fad.get(sort_by, "fad.action_timestamp ASC") # Often chronological for details

        elif rule_id_q:
            search_type_resp = "rule_id_executions"; query_params_resp["rule_id"] = rule_id_q
            base_fields = """ rei.rule_execution_id, rei.run_id, rei.rule_id, rei.rule_version_id, rei.execution_order_in_run, 
                              rei.start_time, rei.end_time, rei.status, rei.matched_search_count, rei.eligible_for_action_count,
                              rei.actions_attempted_count, rei.actions_succeeded_count, rei.summary_message_from_logic, 
                              rei.details_json_from_logic, rv.rule_name_at_version, rv.importance_at_version AS rule_importance_at_version, 
                              rv.conditions_json_at_version, rv.action_json_at_version, er.run_type """
            base_from_join = """ FROM rule_executions_in_run rei JOIN rule_versions rv ON rei.rule_version_id = rv.rule_version_id
                                 JOIN execution_runs er ON rei.run_id = er.run_id """
            where_clauses.append("rei.rule_id = ?"); query_params.append(rule_id_q)
            order_by_clause = allowed_sorts_rei.get(sort_by, "rei.start_time DESC")

        elif run_id_q:
            search_type_resp = "run_id_details"; query_params_resp["run_id"] = run_id_q
            base_fields = """ rei.rule_execution_id, rei.run_id, rei.rule_id, rei.rule_version_id, rei.execution_order_in_run,
                              rei.start_time, rei.end_time, rei.status, rei.matched_search_count, rei.eligible_for_action_count,
                              rei.actions_attempted_count, rei.actions_succeeded_count, rei.summary_message_from_logic,
                              rei.details_json_from_logic, rv.rule_name_at_version, rv.importance_at_version AS rule_importance_at_version, er.run_type """
            base_from_join = """ FROM rule_executions_in_run rei JOIN rule_versions rv ON rei.rule_version_id = rv.rule_version_id
                                 JOIN execution_runs er ON rei.run_id = er.run_id """
            where_clauses.append("rei.run_id = ?"); query_params.append(run_id_q)
            # For a specific run's details, sort by execution order within that run
            order_by_clause = "rei.execution_order_in_run ASC, rei.start_time ASC" 
        else: # General recent execution_runs (top-level overview)
            search_type_resp = "general_runs"; query_params_resp["message"] = "Recent execution runs."
            base_fields = "er.run_id, er.run_type, er.start_time, er.end_time, er.status, er.summary_message"
            base_from_join = "FROM execution_runs er"
            order_by_clause = "er.start_time DESC" # Default sort for general runs

        # Determine timestamp and status columns based on the primary table being queried
        ts_col_for_filter = "er.start_time"; status_col_for_filter = "er.status" # Defaults for general_runs
        if search_type_resp in ["file_hash", "rule_execution_id_details"]:
            ts_col_for_filter = "fad.action_timestamp"; status_col_for_filter = "fad.status"
        elif search_type_resp in ["rule_id_executions", "run_id_details"]:
            ts_col_for_filter = "rei.start_time"; status_col_for_filter = "rei.status"

        # Apply time range filters
        if start_iso != (datetime.min.isoformat()+"Z"): # Not 'all time'
            where_clauses.append(f"{ts_col_for_filter} >= ?"); query_params.append(start_iso)
        query_params_resp["start_date_used"] = start_iso if start_iso != (datetime.min.isoformat()+"Z") else "all_time"
        
        where_clauses.append(f"{ts_col_for_filter} <= ?"); query_params.append(end_iso)
        query_params_resp["end_date_used"] = end_iso

        # Apply status filters
        if status_filter:
            statuses = [s.strip().lower() for s in status_filter.split(',') if s.strip()]
            if statuses:
                placeholders = ', '.join(['?'] * len(statuses))
                where_clauses.append(f"LOWER({status_col_for_filter}) IN ({placeholders})"); query_params.extend(statuses)
                query_params_resp["status_filter"] = statuses
        
        # Apply log_search_term filter (simple LIKE search on relevant text fields)
        if log_search_term_q:
            query_params_resp["log_search_term"] = log_search_term_q
            search_term_like = f"%{log_search_term_q}%"
            text_search_clauses = []
            if search_type_resp in ["file_hash", "rule_execution_id_details"]:
                text_search_clauses.append("fad.file_hash LIKE ?")
                text_search_clauses.append("fad.action_parameters_json_at_exec LIKE ?")
                text_search_clauses.append("fad.error_message LIKE ?")
                text_search_clauses.append("rv.rule_name_at_version LIKE ?")
                for _ in range(len(text_search_clauses)): query_params.append(search_term_like)
            elif search_type_resp in ["rule_id_executions", "run_id_details", "general_runs"]: # general_runs uses er table
                # For rule_id_executions and run_id_details
                if base_from_join.startswith("FROM rule_executions_in_run"):
                    text_search_clauses.append("rei.summary_message_from_logic LIKE ?")
                    text_search_clauses.append("rei.details_json_from_logic LIKE ?")
                    text_search_clauses.append("rv.rule_name_at_version LIKE ?")
                    for _ in range(len(text_search_clauses)): query_params.append(search_term_like)
                # For general_runs
                elif base_from_join.startswith("FROM execution_runs"):
                    text_search_clauses.append("er.summary_message LIKE ?")
                    query_params.append(search_term_like)

            if text_search_clauses:
                where_clauses.append(f"({' OR '.join(text_search_clauses)})")
        
        # Construct final queries
        full_query_sql = f"SELECT {base_fields} {base_from_join}"
        count_query_sql = f"SELECT COUNT(DISTINCT {base_fields.split(',')[0].strip()}) as total_records {base_from_join}" # Count distinct primary entities

        if where_clauses:
            where_condition_sql = " WHERE " + " AND ".join(where_clauses)
            full_query_sql += where_condition_sql
            count_query_sql += where_condition_sql
        
        full_query_sql += f" ORDER BY {order_by_clause} LIMIT ? OFFSET ?"
        
        # Prepare parameters for count and full query
        # Count query does not need limit/offset, full query does.
        # Parameters up to where_clauses are the same for both.
        params_for_count = tuple(query_params) # query_params built so far are for WHERE
        params_for_full_query = tuple(query_params + [limit, offset])

        current_app.logger.debug(f"Log Search Count SQL: {count_query_sql} with params {params_for_count}")
        cursor.execute(count_query_sql, params_for_count)
        total_records_result = cursor.fetchone()
        total_records = total_records_result['total_records'] if total_records_result else 0
        
        current_app.logger.debug(f"Log Search Full SQL: {full_query_sql} with params {params_for_full_query}")
        cursor.execute(full_query_sql, params_for_full_query)
        results = [dict(row) for row in cursor.fetchall()]
        available_services = current_app.config.get('AVAILABLE_SERVICES', [])
        service_name_map = {service['service_key']: service['name'] for service in available_services}
        
        # Deserialize JSON fields for the response
        for entry in results:
            # Deserialize existing JSON fields first
            for key, value in list(entry.items()): # Use list(entry.items()) for safe iteration if modifying dict
                if isinstance(value, str) and (key.endswith("_json") or key.endswith("_json_at_exec") or key.endswith("_json_from_logic")):
                    try:
                        entry[key] = json.loads(value)
                    except json.JSONDecodeError:
                        entry[key] = {"error": "Failed to parse JSON content", "raw_value_preview": value[:100]}
            
            # Enrich with service names if applicable
            # This typically applies to file_action_details logs
            if 'action_parameters_json_at_exec' in entry and isinstance(entry['action_parameters_json_at_exec'], dict):
                action_params = entry['action_parameters_json_at_exec']
                
                if 'destination_service_keys' in action_params and isinstance(action_params['destination_service_keys'], list):
                    resolved_names = []
                    for service_key in action_params['destination_service_keys']:
                        resolved_names.append(service_name_map.get(service_key, f"Unknown Service ({service_key[:8]}...)"))
                    # Add resolved names to the action_params dictionary
                    action_params['destination_service_names_resolved'] = resolved_names
                
                # Potentially handle other service keys here if needed in the future, e.g., tag_service_key
                if 'tag_service_key' in action_params and isinstance(action_params['tag_service_key'], str):
                    service_key = action_params['tag_service_key']
                    action_params['tag_service_name_resolved'] = service_name_map.get(service_key, f"Unknown Service ({service_key[:8]}...)")

                if 'rating_service_key' in action_params and isinstance(action_params['rating_service_key'], str):
                    service_key = action_params['rating_service_key']
                    action_params['rating_service_name_resolved'] = service_name_map.get(service_key, f"Unknown Service ({service_key[:8]}...)")

        return jsonify({
            "success": True, "search_type": search_type_resp, "query_parameters_applied": query_params_resp,
            "logs": results, "total_records": total_records, "limit": limit, "offset": offset,
            "sort_by_applied": sort_by
        }), 200

    except sqlite3.Error as e_sql:
        current_app.logger.error(f"DB error in search_detailed_logs: {e_sql}", exc_info=True)
        return jsonify({"success": False, "message": f"Database error: {e_sql}"}), 500
    except Exception as e:
        current_app.logger.error(f"Error in search_detailed_logs: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"Unexpected error: {e}"}), 500
    finally:
        if db_conn: db_conn.close()


@views_bp.route('/static/<path:filename>')
def static_files_route(filename):
    try:
        # current_app.static_folder should be correctly set in app.py to the project's static folder
        return send_from_directory(current_app.static_folder, filename)
    except Exception as e:
        current_app.logger.error(f"Could not serve static file {filename} from app.static_folder='{current_app.static_folder}': {e}")
        # As a last resort, try a path relative to the blueprint, if you have blueprint-specific static files
        # This usually requires the blueprint to be registered with its own static_folder.
        # For simplicity, we rely on the app's main static folder.
        return "Static file not found", 404