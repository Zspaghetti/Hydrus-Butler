// --- START OF FILE api.js (with new log functions added) ---

// State variables to cache data
export let availableServices = [];
export let availableFileServices = [];
export let availableRatingServices = [];
export let availableTagServices = [];
export let currentlyLoadedRules = [];
export let showNotificationsSetting = true;
export let clientShowRunAllNotificationsSetting = true; // New state variable for "Run All" notifications
export let clientThemeSetting = 'default'; // New state variable for client theme

/**
 * Fetches client-side settings from the backend.
 */
export async function fetchClientSettings() {
    console.log("Fetching client settings...");
    try {
        const response = await fetch('/get_client_settings');
        if (!response.ok) {
            console.warn(`Failed to fetch client settings (HTTP ${response.status}). Using defaults.`);
            showNotificationsSetting = true;
            clientShowRunAllNotificationsSetting = true; // Default on HTTP error
            clientThemeSetting = 'default'; // Default theme on HTTP error
            return;
        }
        const data = await response.json();

        if (data.success && data.settings) {
            showNotificationsSetting = data.settings.show_run_notifications;
            // Fetch and set the show_run_all_notifications setting
            if (typeof data.settings.show_run_all_notifications === 'boolean') {
                clientShowRunAllNotificationsSetting = data.settings.show_run_all_notifications;
            } else {
                clientShowRunAllNotificationsSetting = true; // Fallback if missing or not boolean
                console.warn("show_run_all_notifications setting missing or invalid, using default.");
            }
            // Fetch and set the theme setting
            if (typeof data.settings.theme === 'string' && data.settings.theme) {
                clientThemeSetting = data.settings.theme;
            } else {
                clientThemeSetting = 'default'; // Fallback if missing or not string
                console.warn("Theme setting missing or invalid in response, using default theme.");
            }
            console.log("Fetched show_run_notifications setting:", showNotificationsSetting);
            console.log("Fetched show_run_all_notifications setting:", clientShowRunAllNotificationsSetting);
            console.log("Fetched client theme setting:", clientThemeSetting);
        } else {
            console.warn("Failed to fetch client settings, using defaults:", data.message || "Unknown error");
            showNotificationsSetting = true;
            clientShowRunAllNotificationsSetting = true; // Default on backend error
            clientThemeSetting = 'default'; // Default theme on backend error
        }
    } catch (error) {
        console.error("Error fetching client settings, using defaults:", error);
        showNotificationsSetting = true;
        clientShowRunAllNotificationsSetting = true; // Default on catch
        clientThemeSetting = 'default'; // Default theme on catch
    }
}


/**
 * Fetches all services from the backend (which caches them from Hydrus API).
 * @param {boolean} [userInitiated=false] - True if triggered by user click.
 * @returns {Promise<Object>} A promise resolving to an object indicating success/failure.
 */
export async function fetchAllServices(userInitiated = false) {
    console.log("Fetching all services...");
    const updateServicesButton = document.getElementById('update-services-button');

    if (userInitiated && updateServicesButton) {
        updateServicesButton.disabled = true;
        updateServicesButton.textContent = 'Updating...';
        document.body.classList.add('loading-cursor');
    }

    try {
        const response = await fetch('/get_all_services');
        let data;
        try {
            data = await response.json();
        } catch (jsonError) {
            console.error("Error parsing JSON response from /get_all_services:", jsonError);
            if (!response.ok) {
                data = { success: false, message: `Failed to fetch services. HTTP Status: ${response.status} ${response.statusText}. Response was not valid JSON.` , services: []};
            } else {
                data = { success: false, message: `Received OK response for /get_all_services, but content was not valid JSON.`, services: [] };
            }
        }


        if (response.ok && data.success) {
            availableServices = data.services || [];
            console.log("Fetched all services:", availableServices);

            availableFileServices = availableServices.filter(service => service.type === 2);
            availableRatingServices = availableServices.filter(service =>
                service.type === 6 || service.type === 7 || service.type === 22
            );
            availableTagServices = availableServices.filter(service => service.type === 5);

            console.log(`Filtered: ${availableFileServices.length} file services, ${availableRatingServices.length} rating services, ${availableTagServices.length} tag services.`);

            if (userInitiated && updateServicesButton) {
                updateServicesButton.textContent = 'Services Updated';
                setTimeout(() => {
                    if (updateServicesButton.textContent === 'Services Updated') {
                        updateServicesButton.textContent = 'Update Services List';
                    }
                }, 2000);
            }
            return { success: true, services: availableServices };
        } else {
            const errorMessage = data.message || `Failed to fetch services. HTTP Status: ${response.status} ${response.statusText}`;
            console.error("Failed to fetch all services:", errorMessage);
            if (userInitiated && updateServicesButton) {
                updateServicesButton.textContent = 'Update Failed';
                 setTimeout(() => {
                     if (updateServicesButton.textContent === 'Update Failed') {
                         updateServicesButton.textContent = 'Update Services List';
                     }
                 }, 3000);
            }
            availableServices = [];
            availableFileServices = [];
            availableRatingServices = [];
            availableTagServices = [];
            return { success: false, message: errorMessage, services: [] };
        }
    } catch (error)
    {
        console.error("Network or other error fetching all services:", error);
        if (userInitiated && updateServicesButton) {
            updateServicesButton.textContent = 'Update Failed (Network)';
             setTimeout(() => {
                 if (updateServicesButton.textContent === 'Update Failed (Network)') {
                    updateServicesButton.textContent = 'Update Services List';
                 }
             }, 3000);
        }
        availableServices = [];
        availableFileServices = [];
        availableRatingServices = [];
        availableTagServices = [];
        return { success: false, message: `Network error or other issue: ${error.message}`, services: [] };
    } finally {
        if (userInitiated && updateServicesButton) {
            updateServicesButton.disabled = false;
            document.body.classList.remove('loading-cursor');
        }
    }
}

/**
 * Loads rules from the backend.
 * @returns {Promise<Object>} A promise resolving to an object with success status and rules array.
 */
export async function loadRules() {
    console.log("Loading rules...");
    try {
        const response = await fetch('/rules');
        if (!response.ok) {
            const errorText = await response.text();
            console.error(`Failed to load rules (HTTP ${response.status}):`, errorText);
            currentlyLoadedRules = [];
            return { success: false, message: `Failed to load rules: HTTP ${response.status} ${response.statusText}`, rules: [] };
        }
        const data = await response.json();

        if (data.success) {
            currentlyLoadedRules = data.rules || [];
            console.log("Loaded rules:", currentlyLoadedRules);
            return { success: true, rules: currentlyLoadedRules };
        } else {
            console.error("Failed to load rules (backend error):", data.message);
            currentlyLoadedRules = [];
             return { success: false, message: data.message, rules: [] };
        }
    } catch (error) {
        console.error("Error fetching rules (network/JS error):", error);
        currentlyLoadedRules = [];
         return { success: false, message: `Error fetching rules: ${error.message}`, rules: [] };
    }
}

/**
 * Saves a rule (adds or updates) to the backend.
 * @param {object} ruleData - The rule object to save.
 * @returns {Promise<Object>} An object indicating success/failure and a message.
 */
export async function saveRule(ruleData) {
    console.log("Attempting to save rule via API:", ruleData);
    try {
        const response = await fetch('/add_rule', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(ruleData)
        });

        const result = await response.json();

        if (response.ok && result.success) {
            console.log("Rule saved successfully via API:", result);
            await loadRules();
            return { success: true, message: result.message, rule_id: result.rule_id, rule_name: result.rule_name };
        } else {
            const errorMessage = result.message || (response.ok ? "Backend reported failure but HTTP status was OK." : `HTTP Error: ${response.status} ${response.statusText}`);
            console.error("Failed to save rule via API:", errorMessage);
             return { success: false, message: errorMessage };
        }
    } catch (error) {
        console.error("Error sending rule data to backend API:", error);
         return { success: false, message: `An error occurred while saving the rule: ${error.message}` };
    }
}


/**
 * Runs a rule by its ID via the backend.
 * @param {string} ruleId - The ID of the rule to run.
 * @returns {Promise<Object>} An object indicating success/failure and a message.
 */
export async function runRule(ruleId) {
    console.log("Running rule via API with ID:", ruleId);
    try {
        document.body.classList.add('loading-cursor');
        const response = await fetch(`/run_rule/${ruleId}`, {
            method: 'POST',
        });
        const result = await response.json();
        document.body.classList.remove('loading-cursor');

        if (response.ok) {
            console.log("Rule execution request processed by API:", result);
            return { ...result };
        } else {
            const errorMessage = result.message || `Rule execution failed with HTTP Error: ${response.status} ${response.statusText}`;
            console.error("Failed to execute rule via API (HTTP error):", errorMessage);
            return { success: false, message: errorMessage, ...result };
        }
    } catch (error) {
        document.body.classList.remove('loading-cursor');
        console.error("Error executing rule via API (network/JS error):", error);
         return { success: false, message: `An error occurred while executing rule: ${error.message}` };
    }
}


/**
 * Deletes a rule by its ID via the backend.
 * @param {string} ruleId - The ID of the rule to delete.
 * @returns {Promise<Object>} An object indicating success/failure and a message.
 */
export async function deleteRule(ruleId) {
    console.log("Deleting rule via API with ID:", ruleId);
    try {
        const response = await fetch(`/rules/${ruleId}`, {
            method: 'DELETE',
        });
        const result = await response.json();

        if (response.ok && result.success) {
            console.log("Rule deleted successfully via API:", result);
            await loadRules();
            return { success: true, message: result.message };
        } else {
            const errorMessage = result.message || (response.ok ? "Backend reported failure but HTTP status was OK." : `HTTP Error: ${response.status} ${response.statusText}`);
            console.error("Failed to delete rule via API:", errorMessage);
             return { success: false, message: errorMessage };
        }
    } catch (error) {
        console.error("Error deleting rule via API:", error);
        return { success: false, message: `An error occurred while deleting the rule: ${error.message}` };
    }
}

/**
 * Runs all rules manually via the backend, respecting conflict overrides.
 * @returns {Promise<Object>} An object indicating success/failure and a comprehensive summary.
 */
export async function runAllRulesManualApi() {
    console.log("Running all rules manually via API...");
    try {
        document.body.classList.add('loading-cursor');
        const response = await fetch(`/run_all_rules_manual`, {
            method: 'POST',
        });
        const result = await response.json();
        document.body.classList.remove('loading-cursor');

        if (response.ok) {
            console.log("Manual 'Run All Rules' request processed by API:", result);
            return { ...result };
        } else {
            const errorMessage = result.message || `Manual 'Run All Rules' failed with HTTP Error: ${response.status} ${response.statusText}`;
            console.error("Failed to execute 'Run All Rules' via API (HTTP error):", errorMessage);
            return { success: false, message: errorMessage, results_per_rule: [], summary_totals: {}, ...result };
        }
    } catch (error) {
        document.body.classList.remove('loading-cursor');
        console.error("Error executing 'Run All Rules' via API (network/JS error):", error);
        return {
            success: false,
            message: `An error occurred while executing 'Run All Rules': ${error.message}`,
            results_per_rule: [],
            summary_totals: {}
        };
    }
}


/**
 * Fetches statistics for files processed per rule within a given time frame.
 * @param {string} timeFrame - Predefined time frame (e.g., '24h', '1w', 'custom').
 * @param {string} [startDate] - ISO date string for custom start date (YYYY-MM-DD or full ISO).
 * @param {string} [endDate] - ISO date string for custom end date (YYYY-MM-DD or full ISO).
 * @returns {Promise<Object>} Object with { success: Boolean, data: Array, message?: String, time_frame_used?: String, start_date_used?: String, end_date_used?: String }.
 */
export async function fetchLogStatsFilesPerRule(timeFrame, startDate, endDate) {
    console.log(`Fetching log stats for files per rule. TimeFrame: ${timeFrame}, Start: ${startDate}, End: ${endDate}`);
    const params = new URLSearchParams();
    if (timeFrame) params.append('time_frame', timeFrame);
    if (startDate) params.append('start_date', startDate); // Ensure these are ISO strings if provided
    if (endDate) params.append('end_date', endDate);

    try {
        const response = await fetch(`/logs/stats/files_processed_per_rule?${params.toString()}`);
        const result = await response.json();

        if (response.ok && result.success) {
            console.log("Successfully fetched log stats for files per rule:", result);
            return result; // Contains success, data, time_frame_used, etc.
        } else {
            const errorMessage = result.message || `HTTP Error: ${response.status} ${response.statusText}`;
            console.error("Failed to fetch log stats for files per rule:", errorMessage);
            return { success: false, message: errorMessage, data: [] };
        }
    } catch (error) {
        console.error("Error fetching log stats for files per rule (network/JS):", error);
        return { success: false, message: `Network/JS error: ${error.message}`, data: [] };
    }
}

/**
 * Searches detailed logs based on various parameters.
 * @param {Object} searchParams - An object containing search parameters.
 *   Expected keys: file_hash, rule_id, run_id, rule_execution_id, status_filter,
 *                  time_frame, start_date, end_date, limit, offset, sort_by.
 * @returns {Promise<Object>} Object with { success: Boolean, logs: Array, total_records: Number, message?: String, ...other_meta }.
 */
export async function searchDetailedLogs(searchParams) {
    console.log("Searching detailed logs with params:", searchParams);
    const params = new URLSearchParams();
    for (const key in searchParams) {
        if (searchParams[key] !== undefined && searchParams[key] !== null && searchParams[key] !== '') {
            params.append(key, searchParams[key]);
        }
    }

    try {
        const response = await fetch(`/logs/search?${params.toString()}`);
        const result = await response.json();

        if (response.ok && result.success) {
            console.log("Successfully searched detailed logs:", result);
            return result; // Contains success, logs, total_records, limit, offset, etc.
        } else {
            const errorMessage = result.message || `HTTP Error: ${response.status} ${response.statusText}`;
            console.error("Failed to search detailed logs:", errorMessage);
            return { success: false, message: errorMessage, logs: [], total_records: 0 };
        }
    } catch (error) {
        console.error("Error searching detailed logs (network/JS):", error);
        return { success: false, message: `Network/JS error: ${error.message}`, logs: [], total_records: 0 };
    }
}