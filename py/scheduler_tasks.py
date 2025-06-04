import logging
from datetime import datetime, timedelta
import uuid # For run_id

from flask_apscheduler import APScheduler

logger = logging.getLogger(__name__)
scheduler = APScheduler()

def run_all_rules_scheduled_job(app):
    """
    Scheduled job function. Iterates through rules and executes them.
    Manages DB connection and overall run logging.
    Requires the Flask 'app' instance to create an app context.
    """
    with app.app_context(): # Essential for accessing app.config, extensions, etc.
        # Now we can safely import and use app-dependent modules/functions
        from rule_processing import execute_single_rule, _ensure_available_services
        from database import get_db_connection
        from app_config import load_rules as app_config_load_rules # Renamed to avoid conflict

        current_run_start_time = datetime.utcnow()
        current_run_id = str(uuid.uuid4())
        run_type = "scheduled_all"

        logger.info(f"\n--- Scheduler: Starting Run ID {current_run_id[:8]} ({run_type}) at {current_run_start_time.strftime('%Y-%m-%d %H:%M:%S UTC')} ---")

        db_conn = None
        overall_run_status = "started"
        run_summary_message = f"Scheduled run ({current_run_id[:8]}) started."
        any_rule_had_processing_error = False

        try:
            db_conn = get_db_connection() # From database.py
            cursor = db_conn.cursor()
            cursor.execute('''
                INSERT INTO execution_runs (run_id, run_type, start_time, status, summary_message)
                VALUES (?, ?, ?, ?, ?)
            ''', (current_run_id, run_type, current_run_start_time.isoformat() + "Z", overall_run_status, run_summary_message))
            db_conn.commit()
            logger.info(f"Scheduler (Run ID {current_run_id[:8]}): Logged start to execution_runs table.")

            rules = app_config_load_rules() # From app_config.py
            current_settings = app.config['HYDRUS_SETTINGS'] # Access Flask app's config

            if not current_settings.get('api_address') or not current_settings.get('api_key'):
                missing = [p for p in ("API address", "API key") if not current_settings.get(p.lower().replace(" ", "_"))]
                run_summary_message = f"Hydrus {', '.join(missing)} not configured. Scheduled run aborted."
                overall_run_status = "failed_early_config"
                logger.warning(f"Scheduler (Run ID {current_run_id[:8]}): {run_summary_message}")
                # No return here, let it flow to finally
            elif not rules:
                run_summary_message = "No rules defined. Scheduled run completed without processing."
                overall_run_status = "completed_no_rules"
                logger.info(f"Scheduler (Run ID {current_run_id[:8]}): {run_summary_message}")
            else:
                # Ensure services are available (uses app.config directly)
                logger.info(f"Scheduler (Run ID {current_run_id[:8]}): Ensuring Hydrus services are available...")
                available_services = _ensure_available_services(app.config, f"Scheduler_Run_{current_run_id[:8]}")
                if not available_services:
                    run_summary_message = "CRITICAL - Could not fetch Hydrus services. Scheduled run aborted."
                    overall_run_status = "failed_early_services"
                    logger.error(f"Scheduler (Run ID {current_run_id[:8]}): {run_summary_message}")
                else:
                    logger.info(f"Scheduler (Run ID {current_run_id[:8]}): {len(available_services)} services available. Processing {len(rules)} rules.")
                    total_rules_processed = 0
                    total_rules_with_errors_or_failures = 0

                    for i, rule in enumerate(rules):
                        total_rules_processed += 1
                        rule_name_log = rule.get('name', rule.get('id', 'Unnamed'))
                        logger.info(f"\nScheduler (Run ID {current_run_id[:8]}): Executing Rule {i+1}/{len(rules)}: '{rule_name_log}'")
                        try:
                            # Pass app.config to execute_single_rule
                            exec_result = execute_single_rule(
                                app.config, db_conn, rule,
                                current_run_id, i + 1, is_manual_run=False
                            )
                            if not exec_result.get('success', True):
                                total_rules_with_errors_or_failures += 1
                                logger.warning(f"Scheduler (Run ID {current_run_id[:8]}): Rule '{rule_name_log}' reported issues. Summary: {exec_result.get('message', 'N/A')}")
                            else:
                                logger.info(f"Scheduler (Run ID {current_run_id[:8]}): Rule '{rule_name_log}' completed. Summary: {exec_result.get('message', 'OK')}")
                        except Exception as e_rule_proc:
                            any_rule_had_processing_error = True
                            total_rules_with_errors_or_failures +=1
                            err_msg_crit = f"Scheduler (Run ID {current_run_id[:8]}): CRITICAL error processing rule '{rule_name_log}': {e_rule_proc}"
                            logger.error(err_msg_crit, exc_info=True)
                    
                    # Determine overall status after processing rules
                    if any_rule_had_processing_error:
                        overall_run_status = "completed_with_critical_rule_errors"
                        run_summary_message = f"Scheduled run ({current_run_id[:8]}) completed with critical rule errors."
                    elif total_rules_with_errors_or_failures > 0:
                        overall_run_status = "completed_with_rule_failures"
                        run_summary_message = f"Scheduled run ({current_run_id[:8]}) completed. {total_rules_with_errors_or_failures}/{total_rules_processed} rule(s) had issues."
                    else:
                        overall_run_status = "completed_ok"
                        run_summary_message = f"Scheduled run ({current_run_id[:8]}) completed successfully. Processed {total_rules_processed} rules."
            
            if db_conn: # Commit all changes if db_conn was established
                db_conn.commit()
                logger.info(f"Scheduler (Run ID {current_run_id[:8]}): All database changes for the run committed.")

        except sqlite3.Error as db_e:
            overall_run_status = "failed_db_error"
            run_summary_message = f"Scheduler (Run ID {current_run_id[:8]}): DB error: {db_e}"
            logger.error(run_summary_message, exc_info=True)
            if db_conn: db_conn.rollback()
        except Exception as global_e:
            overall_run_status = "failed_global_error"
            run_summary_message = f"Scheduler (Run ID {current_run_id[:8]}): Global error: {global_e}"
            logger.error(run_summary_message, exc_info=True)
            if db_conn: db_conn.rollback()
        finally:
            current_run_end_time = datetime.utcnow()
            if db_conn: # db_conn might be None if initial get_db_connection failed
                try:
                    cursor = db_conn.cursor() # Re-ensure cursor
                    cursor.execute('''
                        UPDATE execution_runs SET end_time = ?, status = ?, summary_message = ?
                        WHERE run_id = ?
                    ''', (current_run_end_time.isoformat() + "Z", overall_run_status, run_summary_message, current_run_id))
                    db_conn.commit()
                    logger.info(f"Scheduler (Run ID {current_run_id[:8]}): Final status '{overall_run_status}' updated.")
                except sqlite3.Error as e_final:
                    logger.error(f"Scheduler (Run ID {current_run_id[:8]}): CRITICAL - Failed to update final run status: {e_final}")
                finally:
                    db_conn.close()
                    logger.info(f"Scheduler (Run ID {current_run_id[:8]}): Database connection closed.")
            
            logger.info(f"--- Scheduler: Finished Run ID {current_run_id[:8]} ({run_type}) at {current_run_end_time.strftime('%Y-%m-%d %H:%M:%S UTC')} ---")


def schedule_rules_job(app):
    """
    Manages the APScheduler job based on settings.
    Requires the Flask 'app' instance to access app.config and the scheduler.
    """
    # Access HYDRUS_SETTINGS from the passed app's config
    settings = app.config.get('HYDRUS_SETTINGS', {})
    interval_seconds = settings.get('rule_interval_seconds', 0)
    job_id = 'run_all_rules_job'
    initial_delay_seconds = 20

    # Use the scheduler instance from this module
    global scheduler
    if scheduler.get_job(job_id):
        logger.info(f"Scheduler: Removing existing job '{job_id}'.")
        scheduler.remove_job(job_id)

    if isinstance(interval_seconds, (int, float)) and interval_seconds > 0:
        first_run_time = datetime.now() + timedelta(seconds=initial_delay_seconds)
        logger.info(f"Scheduler: Scheduling job '{job_id}' to run first at {first_run_time.strftime('%Y-%m-%d %H:%M:%S')} and then every {interval_seconds} seconds.")
        
        # Pass the app instance to the job function
        scheduler.add_job(
            id=job_id,
            func=run_all_rules_scheduled_job, # Target the new job function
            args=[app], # Pass the Flask app instance
            trigger='interval',
            seconds=int(interval_seconds),
            next_run_time=first_run_time,
            replace_existing=True,
            misfire_grace_time=60
        )
    else:
        logger.info(f"Scheduler: Rule interval is {interval_seconds} seconds. Scheduled job will not be added.")