import os
import sys
import logging
from flask import Flask

# --- Initialize Logging Early ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__) # Logger for this main app.py

from app_config import (
    load_settings as app_config_load_settings,
    load_rules as app_config_load_rules
)
from database import init_conflict_db
from hydrus_interface import call_hydrus_api # For initial service fetch
from views import views_bp # Import the Blueprint from views.py
from scheduler_tasks import scheduler, schedule_rules_job as schedule_job_from_tasks_module

# --- Global App Variable (Flask instance) ---
# This will be configured by create_app function.
# It's defined globally here so that it can be imported by other modules IF ABSOLUTELY NEEDED,
# though the preference is to pass 'app' or 'current_app.config' around.
# For now, scheduler_tasks.py and views.py are designed to work with 'app' or 'current_app'.
app = Flask(__name__) # Create Flask app instance early

def create_app():
    """
    Application factory function.
    Configures and returns the Flask application instance.
    """
    logger.info("--- Application Starting ---")

    # --- Configure Static and Template Folders (explicitly) ---
    # Assuming 'static' and 'templates' are at the same level as this app.py
    PY_DIR = os.path.abspath(os.path.dirname(__file__)) # Path to the 'py' directory
    PROJECT_ROOT_DIR = os.path.dirname(PY_DIR) # Path to the project root (one level up)

    app.static_folder = os.path.join(PROJECT_ROOT_DIR, 'static')
    app.template_folder = os.path.join(PROJECT_ROOT_DIR, 'templates')
    logger.info(f"Project root determined as: {PROJECT_ROOT_DIR}")
    logger.info(f"Static folder set to: {app.static_folder}")
    logger.info(f"Template folder set to: {app.template_folder}")

    # --- Load Core Configurations ---
    # These use functions from app_config.py
    # The results are stored in app.config
    app.config['HYDRUS_SETTINGS'] = app_config_load_settings()
    app.config['AUTOMATION_RULES'] = app_config_load_rules()
    app.config['AVAILABLE_SERVICES'] = [] # Initialize as empty list

    # --- Set Flask Secret Key ---
    secret_key_hex = app.config['HYDRUS_SETTINGS'].get('secret_key')
    if secret_key_hex:
        try:
            app.secret_key = bytes.fromhex(secret_key_hex)
            logger.info("Flask secret_key set from loaded settings.")
        except ValueError:
            logger.critical(f"CRITICAL ERROR: Could not convert secret_key from hex. Using temporary key.")
            app.secret_key = os.urandom(24)
    else:
        logger.critical("CRITICAL ERROR: No secret_key found in settings. Using temporary key.")
        app.secret_key = os.urandom(24)

    # --- Initialize Database ---
    try:
        logger.info("Attempting to initialize database...")
        init_conflict_db() # From database.py
        logger.info("Database initialization process completed.")
    except Exception as e:
        logger.fatal(f"FATAL: Failed to initialize database: {e}. Application cannot start.", exc_info=True)
        sys.exit(1) # Exit if DB initialization fails

    # --- Register Blueprints (contains all the routes) ---
    app.register_blueprint(views_bp)
    logger.info("Views blueprint registered.")

    # --- Initialize Scheduler ---
    # The scheduler instance is imported from scheduler_tasks.py
    scheduler.init_app(app)
    logger.info("APScheduler initialized with Flask app.")

    return app

# --- Main Execution ---
if __name__ == '__main__':
    app_instance = create_app() # Create the app using the factory

    # --- Initial Hydrus Service Fetch on Startup (within app context) ---
    # This needs to happen after create_app() so app.config is populated.
    with app_instance.app_context():
        logger.info("Attempting to fetch Hydrus services on startup...")
        # Use app_instance.config as it's the fully configured app's config
        hydrus_settings = app_instance.config.get('HYDRUS_SETTINGS', {})
        if hydrus_settings.get('api_address'):
            api_addr = hydrus_settings.get('api_address')
            api_k = hydrus_settings.get('api_key')
            services_result, _ = call_hydrus_api(api_addr, api_k, '/get_services') # From hydrus_interface.py

            if services_result.get("success") and isinstance(services_result.get('data'), dict):
                services_object = services_result["data"].get('services')
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
                    app_instance.config['AVAILABLE_SERVICES'] = services_list
                    logger.info(f"Successfully fetched and cached {len(services_list)} services on startup.")
                else:
                    logger.warning("Could not parse services object from API response on startup. Using empty list.")
                    app_instance.config['AVAILABLE_SERVICES'] = []
            else:
                logger.warning(f"Failed to fetch Hydrus services on startup: {services_result.get('message', 'Unknown API error')}. Using empty list.")
                app_instance.config['AVAILABLE_SERVICES'] = []
        else:
            logger.warning("Hydrus API address not configured. Skipping service fetch on startup.")
            app_instance.config['AVAILABLE_SERVICES'] = []


    # --- Start Scheduler (conditionally to avoid reloader issues) ---
    APP_DEBUG_MODE = app_instance.config.get('DEBUG', False) # Get debug mode from app config
    run_scheduler_process = True
    if APP_DEBUG_MODE:
        if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
            run_scheduler_process = False
            logger.info("Flask reloader detected: Scheduler will NOT be started by this child process.")
        else:
            logger.info("Flask reloader detected: Scheduler WILL be started by this main process.")
    
    if run_scheduler_process:
        logger.info("Starting APScheduler...")
        scheduler.start() # Start the scheduler imported from scheduler_tasks
        logger.info("APScheduler started.")
        # Initial scheduling of the rules job (within app context)
        with app_instance.app_context():
            logger.info("Performing initial scheduling of rules job...")
            schedule_job_from_tasks_module(app_instance) # Pass the app_instance
    else:
        logger.info("Scheduler not started by this process (likely due to Flask reloader or configuration).")

    # --- Run Flask Development Server ---
    # For production, use a proper WSGI server like Gunicorn or uWSGI.
    logger.info(f"Starting Flask server on http://127.0.0.1:5556/ (Debug mode: {APP_DEBUG_MODE})")
    app_instance.run(
        host='127.0.0.1',
        port=5556,
        debug=APP_DEBUG_MODE, # Use the debug mode from app_instance.config
        threaded=True, # Good for dev with scheduler
        use_reloader=APP_DEBUG_MODE # Controlled by APP_DEBUG_MODE
    )