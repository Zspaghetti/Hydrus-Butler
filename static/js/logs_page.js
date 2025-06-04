import {
    fetchClientSettings,
    clientThemeSetting,
    fetchLogStatsFilesPerRule,
    searchDetailedLogs,
    fetchAllServices, // Import function to ensure services are loaded
    loadRules,        // Import function to ensure rules are loaded
    availableServices, // Import to use the cached service list
    currentlyLoadedRules // Import to use the cached rule list
} from './api.js';
import { getServiceName } from './utils.js'; // Import utility to get service name

let statsChartInstance = null;
const DEFAULT_RECORDS_PER_PAGE = 50;
const MAX_RULES_IN_CHART = 12; // New constant for max rules in chart

let currentLogSearchParams = {
    limit: DEFAULT_RECORDS_PER_PAGE,
    offset: 0,
    sort_by: 'timestamp_desc',
    time_frame: '1w' // Default for initial log load
};

// --- DOM Elements ---
// Chart Elements
let statsTimeFrameSelect, statsCustomDateDiv, statsStartDateInput, statsEndDateInput,
    updateStatsChartButton, filesProcessedChartCanvas, statsLoadingMessage, statsErrorMessage;

// Detailed Log Elements
let logSearchForm, searchFileHashInput, searchRuleIdInput, searchRunIdInput, searchRuleExecutionIdInput,
    searchStatusFilterInput, searchTimeFrameSelect, searchCustomDateDiv, searchStartDateInput,
    searchEndDateInput, searchSortBySelect, searchLogsButton, resetSearchLogsButton,
    logsLoadingMessage, logsErrorMessage, detailedLogsTableBody, logsPaginationControls,
    detailedLogsResultsSummary;

let butlerNameHeader; // For updating the butler name in the header

/**
 * Applies the selected theme to the application.
 * @param {string} themeName - The name of the theme (e.g., 'Blueprint', 'Dark').
 */
function applyTheme(themeName) {
    console.log(`Logs Page: Applying theme: ${themeName}`);
    document.body.className = document.body.className.replace(/\btheme-\S+/g, '');
    document.body.classList.add(`theme-${themeName}`); // e.g., theme-Blueprint

    const stylesheetLink = document.querySelector('link[rel="stylesheet"][href*="static/css/"]#main-stylesheet');
    if (stylesheetLink) {
        const expectedHref = `/static/css/${themeName}.css`;
        if (!stylesheetLink.getAttribute('href').endsWith(expectedHref)) {
            stylesheetLink.setAttribute('href', expectedHref);
            console.log(`Logs Page: Stylesheet link updated to: ${expectedHref}`);
        }
    } else {
        const firstStylesheetLink = document.querySelector('link[rel="stylesheet"][href*="static/css/"]');
        if (firstStylesheetLink) {
            const expectedHref = `/static/css/${themeName}.css`;
             if (!firstStylesheetLink.getAttribute('href').endsWith(expectedHref)) {
                firstStylesheetLink.setAttribute('href', expectedHref);
                console.log(`Logs Page: Fallback Stylesheet link updated to: ${expectedHref}`);
            }
        } else {
            console.warn("Logs Page: Could not find a stylesheet link to update for the theme.");
        }
    }
}

/**
 * Updates the butler name in the header.
 */
function updateButlerNameDisplay() {
    if (butlerNameHeader && window.HYDRUS_BUTLER_SETTINGS && window.HYDRUS_BUTLER_SETTINGS.butler_name) {
        butlerNameHeader.textContent = window.HYDRUS_BUTLER_SETTINGS.butler_name;
    }
}


// --- Chart Functions ---
async function loadAndRenderLogStats() {
    if (!statsTimeFrameSelect || !filesProcessedChartCanvas) return;

    statsLoadingMessage.style.display = 'block';
    statsErrorMessage.style.display = 'none';
    if (statsChartInstance) {
        statsChartInstance.destroy();
        statsChartInstance = null;
    }

    const timeFrame = statsTimeFrameSelect.value;
    let startDate = null;
    let endDate = null;

    if (timeFrame === 'custom') {
        startDate = statsStartDateInput.value; // YYYY-MM-DD
        endDate = statsEndDateInput.value;     // YYYY-MM-DD
        if (!startDate || !endDate) {
            statsLoadingMessage.style.display = 'none';
            statsErrorMessage.textContent = 'For custom range, both start and end dates are required.';
            statsErrorMessage.style.display = 'block';
            return;
        }
    }

    const result = await fetchLogStatsFilesPerRule(timeFrame, startDate, endDate);

    statsLoadingMessage.style.display = 'none';
    if (result.success && result.data) {
        if (result.data.length === 0) {
            statsErrorMessage.textContent = `No rule activity found for the selected period (${result.time_frame_used}).`;
            statsErrorMessage.style.display = 'block';
            return;
        }
        renderFilesProcessedChart(result.data);
        statsErrorMessage.style.display = 'none';
    } else {
        statsErrorMessage.textContent = `Failed to load statistics: ${result.message || 'Unknown error'}`;
        statsErrorMessage.style.display = 'block';
    }
}

function renderFilesProcessedChart(data) {
    const chartData = data.slice(0, MAX_RULES_IN_CHART);

    const labels = chartData.map(item => item.rule_name);
    const values = chartData.map(item => item.files_successfully_actioned);

    const ctx = filesProcessedChartCanvas.getContext('2d');
    statsChartInstance = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Files Successfully Actioned',
                data: values,
                backgroundColor: 'rgba(54, 162, 235, 0.6)',
                borderColor: 'rgba(54, 162, 235, 1)',
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            barPercentage: 0.7,
            categoryPercentage: 0.8,
            scales: {
                y: {
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: 'Number of Files'
                    }
                },
                x: {
                    title: {
                        display: true,
                        text: 'Rule Name'
                    }
                }
            },
            plugins: {
                legend: {
                    display: true,
                    position: 'top',
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            return `${context.dataset.label}: ${context.parsed.y}`;
                        }
                    }
                }
            }
        }
    });
}

function initializeLogStats() {
    statsTimeFrameSelect.addEventListener('change', () => {
        statsCustomDateDiv.style.display = statsTimeFrameSelect.value === 'custom' ? 'block' : 'none';
    });
    updateStatsChartButton.addEventListener('click', loadAndRenderLogStats);
    loadAndRenderLogStats(); // Initial load
}

// --- Detailed Log Functions ---
/**
 * Formats an ISO string to a more readable date/time or date-only string.
 * @param {string} isoString - The ISO date string.
 * @param {'datetime' | 'dateonly'} [type='datetime'] - The desired output format type.
 * @returns {string} Formatted date string, or 'N/A', 'Invalid Date', or original string on error.
 */
function formatTimestamp(isoString, type = 'datetime') {
    if (!isoString || typeof isoString !== 'string' || isoString.trim() === '') {
        return 'N/A';
    }
    try {
        const date = new Date(isoString);
        if (isNaN(date.getTime())) {
             console.warn(`formatTimestamp: Parsed to Invalid Date from isoString: '${isoString}' (type: ${type})`);
             return 'Invalid Date';
        }
        const year = date.getFullYear();
        const month = (date.getMonth() + 1).toString().padStart(2, '0');
        const day = date.getDate().toString().padStart(2, '0');
        
        if (type === 'dateonly') {
            return `${year}-${month}-${day}`;
        }
        
        const hours = date.getHours().toString().padStart(2, '0');
        const minutes = date.getMinutes().toString().padStart(2, '0');
        const seconds = date.getSeconds().toString().padStart(2, '0');
        return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
    } catch (e) {
        console.error(`formatTimestamp: Error constructing Date from isoString: '${isoString}' (type: ${type})`, e);
        return isoString; // Fallback
    }
}

function prettyPrintJson(data) {
    if (data === null || data === undefined) return 'N/A';
    let jsonData = data;
    if (typeof data === 'string') {
        try {
            jsonData = JSON.parse(data);
        } catch (e) {
            return data; // Not valid JSON, return as is
        }
    }
    return JSON.stringify(jsonData, null, 2);
}


function renderDetailedLogRow(logEntry) {
    const row = detailedLogsTableBody.insertRow();

    let timestamp, mainStatus, ruleNameDisplay, ruleId, runId;
    let actionType = logEntry.action_type_performed || 'N/A';
    let fileHash = logEntry.file_hash || 'N/A';
    let parametersMessage = '';
    let logOrExecId = '';



    if (logEntry.log_id) { // It's a file_action_detail
        timestamp = logEntry.action_timestamp;
        mainStatus = logEntry.status;
        
        if (logEntry.rule_name_at_version) {
            ruleNameDisplay = logEntry.rule_name_at_version;
        } else {
            ruleNameDisplay = 'Rule Info N/A'; // Fallback if name is missing
        }

        ruleId = logEntry.rule_id || 'N/A';
        runId = logEntry.run_id || 'N/A';
        logOrExecId = `Log: ${logEntry.log_id}`;
        
        let processedParamsJsonString = ''; 
        let additionalParamsHtml = '';    

        if (logEntry.action_parameters_json_at_exec) {
            // The backend already deserialized this, so logEntry.action_parameters_json_at_exec should be an object.
            // If it's a string, it means parsing failed on the backend, and it contains an error message.
            let paramsToDisplay = {};
            if (typeof logEntry.action_parameters_json_at_exec === 'object' && logEntry.action_parameters_json_at_exec !== null) {
                paramsToDisplay = { ...logEntry.action_parameters_json_at_exec };
				
                if (paramsToDisplay.destination_service_names_resolved && Array.isArray(paramsToDisplay.destination_service_names_resolved)) {
                    // Replace keys with resolved names for display if preferred, or add as new field.             
                    // more readable display for service destinations
                    additionalParamsHtml += `<p style="margin-top: 5px; margin-bottom: 0;"><strong>Effective Destination(s):</strong> ${paramsToDisplay.destination_service_names_resolved.join(', ') || 'None'}</p>`;
                    // remove from the main JSON dump if handled separately:
                    delete paramsToDisplay.destination_service_names_resolved;
                    if (paramsToDisplay.destination_service_keys) { // Keep raw keys for full info but label clearly
                        paramsToDisplay["Raw Destination Keys"] = paramsToDisplay.destination_service_keys;
                        delete paramsToDisplay.destination_service_keys;
                    }
                }

                if (paramsToDisplay.tag_service_name_resolved) {
                    additionalParamsHtml += `<p style="margin-top: 5px; margin-bottom: 0;"><strong>Tag Service:</strong> ${paramsToDisplay.tag_service_name_resolved}</p>`;
                    delete paramsToDisplay.tag_service_name_resolved;
                    if (paramsToDisplay.tag_service_key) {
                        paramsToDisplay["Raw Tag Service Key"] = paramsToDisplay.tag_service_key;
                        delete paramsToDisplay.tag_service_key;
                    }
                }

                if (paramsToDisplay.rating_service_name_resolved) {
                    additionalParamsHtml += `<p style="margin-top: 5px; margin-bottom: 0;"><strong>Rating Service:</strong> ${paramsToDisplay.rating_service_name_resolved}</p>`;
                    delete paramsToDisplay.rating_service_name_resolved;
                    if (paramsToDisplay.rating_service_key) {
                        paramsToDisplay["Raw Rating Service Key"] = paramsToDisplay.rating_service_key;
                        delete paramsToDisplay.rating_service_key;
                    }
                }

                if (paramsToDisplay.original_rule_keys && Array.isArray(paramsToDisplay.original_rule_keys) && paramsToDisplay.original_rule_keys.length > 0) {
                    const ruleDescriptions = paramsToDisplay.original_rule_keys.map(origRuleId => {
                        const rule = currentlyLoadedRules.find(r => r.id === origRuleId); 
                        if (rule) {
                            return `${rule.name} (ID: ${origRuleId.substring(0, 8)}...)`;
                        }
                        return `Unknown Rule (ID: ${origRuleId.substring(0, 8)}...)`;
                    }).join('; ');

                    if (ruleDescriptions) {
                        additionalParamsHtml += `<p style="margin-top: 5px; margin-bottom: 0;"><strong>Referenced Original Rule(s) (current names):</strong> ${ruleDescriptions}</p>`;
                    }
                }
                
                if (paramsToDisplay.rule_configured_destination_keys && Array.isArray(paramsToDisplay.rule_configured_destination_keys)) {
                    const configuredKeysDisplay = paramsToDisplay.rule_configured_destination_keys.map(key => {
                        // Use getServiceName here as this is the *configured* key, not necessarily resolved by backend under this specific name
                        const serviceName = getServiceName(key, availableServices); 
                        return serviceName !== key ? `${serviceName} (key: ${key.substring(0, 8)}...)` : key;
                    }).join(', ');
                    
                    additionalParamsHtml += `<p style="margin-top: 5px; margin-bottom: 0;"><strong>Rule's Configured Destination(s):</strong> ${configuredKeysDisplay}</p>`;
                    delete paramsToDisplay.rule_configured_destination_keys;
                }
                processedParamsJsonString = Object.keys(paramsToDisplay).length > 0 ? prettyPrintJson(paramsToDisplay) : 'No further parameters.';

            } else if (typeof logEntry.action_parameters_json_at_exec === 'string') {
                // This case handles if backend failed to parse and sent back the raw string or an error object as string
                 processedParamsJsonString = prettyPrintJson(logEntry.action_parameters_json_at_exec); // Fallback
            } else {
                processedParamsJsonString = 'N/A';
            }

        } else {
            processedParamsJsonString = 'N/A';
        }
        
        // Check if processedParamsJsonString became empty string due to all params being moved to additionalParamsHtml
        if (processedParamsJsonString.trim() === '' || processedParamsJsonString === 'No further parameters.') {
            parametersMessage = additionalParamsHtml || 'N/A'; // Show only additional HTML or N/A
        } else {
            parametersMessage = `<pre>${processedParamsJsonString}</pre>${additionalParamsHtml}`;
        }


        if (logEntry.error_message) {
            parametersMessage += `<p style="color:red;"><strong>Error:</strong> ${logEntry.error_message}</p>`;
        }
        if (logEntry.override_info_json) {
             // Backend should have parsed this. If it's an object, prettyPrintJson will handle it.
             parametersMessage += `<p style="color:orange;"><strong>Override Info:</strong> <pre>${prettyPrintJson(logEntry.override_info_json)}</pre></p>`;
        }

    } else if (logEntry.rule_execution_id) { // It's a rule_executions_in_run
        timestamp = logEntry.start_time;
        mainStatus = logEntry.status;

        if (logEntry.rule_name_at_version) {
            ruleNameDisplay = logEntry.rule_name_at_version;
        } else {
            ruleNameDisplay = 'N/A Rule (execution summary)';
        }
        
        ruleId = logEntry.rule_id || 'N/A';
        runId = logEntry.run_id || 'N/A';
        logOrExecId = `Exec: ${logEntry.rule_execution_id.substring(0,8)}`;
        actionType = 'Rule Execution Summary';
        fileHash = `Matched: ${logEntry.matched_search_count || 0}, Eligible: ${logEntry.eligible_for_action_count || 0}, Attempted: ${logEntry.actions_attempted_count || 0}, Succeeded: ${logEntry.actions_succeeded_count || 0}`;
        if (logEntry.summary_message_from_logic) {
            parametersMessage = `<p>${logEntry.summary_message_from_logic}</p>`;
        }
        if (logEntry.details_json_from_logic) {
            // Backend should have parsed this.
            parametersMessage += `<details><summary>Execution Details (JSON)</summary><pre>${prettyPrintJson(logEntry.details_json_from_logic)}</pre></details>`;
        }
    } else if (logEntry.run_id) { // It's an execution_run
        timestamp = logEntry.start_time;
        mainStatus = logEntry.status;
        ruleNameDisplay = `Run Type: ${logEntry.run_type}`; // No version info for a run summary
        ruleId = 'N/A';
        runId = logEntry.run_id;
        logOrExecId = `Run: ${logEntry.run_id.substring(0,8)}`;
        actionType = 'Overall Run Summary';
        fileHash = 'N/A';
        if (logEntry.summary_message) {
            parametersMessage = `<p>${logEntry.summary_message}</p>`;
        }
    } else {
        // Fallback for unknown log structure
        timestamp = 'N/A'; mainStatus = 'N/A'; ruleNameDisplay = 'N/A Log Entry'; actionType = 'N/A'; fileHash = 'N/A';
        parametersMessage = `<pre>${prettyPrintJson(logEntry)}</pre>`;
    }


    row.insertCell().textContent = formatTimestamp(timestamp); // Main timestamp
    row.insertCell().textContent = ruleNameDisplay;
    row.insertCell().textContent = fileHash;
    row.insertCell().textContent = actionType;
    row.insertCell().textContent = mainStatus;
    row.insertCell().innerHTML = `<div class="log-details-cell">${parametersMessage || 'N/A'}</div>`; // Ensure parametersMessage isn't empty
    row.insertCell().textContent = runId ? runId.substring(0,8) : 'N/A';
    row.insertCell().textContent = logOrExecId;

    const fileHashCell = row.cells[2];
    if (logEntry.file_hash && logEntry.file_hash !== 'N/A' && logEntry.log_id) { // Ensure it's a file_action_detail for file hash click
        fileHashCell.style.cursor = 'pointer';
        fileHashCell.title = 'Click to copy file hash';
        fileHashCell.addEventListener('click', () => {
            navigator.clipboard.writeText(logEntry.file_hash).then(() => {
                const originalText = fileHashCell.textContent;
                fileHashCell.textContent = 'Copied!';
                setTimeout(() => { fileHashCell.textContent = originalText; }, 1500);
            }).catch(err => console.error('Failed to copy hash: ', err));
        });
    }
    const ruleNameCell = row.cells[1];
    if (ruleId && ruleId !== 'N/A') {
        ruleNameCell.style.cursor = 'pointer';
        ruleNameCell.title = `Click to search logs for Rule ID: ${ruleId.substring(0,8)}...`;
        ruleNameCell.addEventListener('click', () => {
            searchRuleIdInput.value = ruleId;
            searchFileHashInput.value = '';
            searchRunIdInput.value = '';
            searchRuleExecutionIdInput.value = '';
            logSearchForm.requestSubmit(); // Use native form submission to trigger our handler
        });
    }
}

async function loadAndRenderDetailedLogs(page = 1) {
    logsLoadingMessage.style.display = 'block';
    logsErrorMessage.style.display = 'none';
    detailedLogsTableBody.innerHTML = '';
    logsPaginationControls.innerHTML = '';
    detailedLogsResultsSummary.textContent = '';


    currentLogSearchParams.offset = (page - 1) * currentLogSearchParams.limit;

    const result = await searchDetailedLogs(currentLogSearchParams);
    logsLoadingMessage.style.display = 'none';

    if (result.success && result.logs) {
        if (result.logs.length === 0) {
            detailedLogsResultsSummary.textContent = `No logs found matching your criteria. (Searched ${result.search_type || 'general'})`;
        } else {
            detailedLogsResultsSummary.textContent = `Showing ${result.offset + 1}-${result.offset + result.logs.length} of ${result.total_records} logs. (Search Type: ${result.search_type})`;
            result.logs.forEach(logEntry => renderDetailedLogRow(logEntry));
            renderPaginationControls(result.total_records, result.limit, result.offset);
        }
        logsErrorMessage.style.display = 'none';
    } else {
        logsErrorMessage.textContent = `Failed to load logs: ${result.message || 'Unknown error'}`;
        logsErrorMessage.style.display = 'block';
    }
}

function renderPaginationControls(totalRecords, limit, currentOffset) {
    logsPaginationControls.innerHTML = '';
    if (totalRecords <= limit) return;

    const totalPages = Math.ceil(totalRecords / limit);
    const currentPage = Math.floor(currentOffset / limit) + 1;

    const prevButton = document.createElement('button');
    prevButton.textContent = 'Previous';
    prevButton.disabled = currentPage === 1;
    prevButton.addEventListener('click', () => loadAndRenderDetailedLogs(currentPage - 1));
    logsPaginationControls.appendChild(prevButton);

    const pageInfo = document.createElement('span');
    pageInfo.textContent = ` Page ${currentPage} of ${totalPages} `;
    logsPaginationControls.appendChild(pageInfo);

    const nextButton = document.createElement('button');
    nextButton.textContent = 'Next';
    nextButton.disabled = currentPage === totalPages;
    nextButton.addEventListener('click', () => loadAndRenderDetailedLogs(currentPage + 1));
    logsPaginationControls.appendChild(nextButton);
}


function handleLogSearchFormSubmit(event) {
    if (event) event.preventDefault();

    currentLogSearchParams.file_hash = searchFileHashInput.value.trim();
    currentLogSearchParams.rule_id = searchRuleIdInput.value.trim();
    currentLogSearchParams.run_id = searchRunIdInput.value.trim();
    currentLogSearchParams.rule_execution_id = searchRuleExecutionIdInput.value.trim();
    currentLogSearchParams.status_filter = searchStatusFilterInput.value.trim();
    currentLogSearchParams.sort_by = searchSortBySelect.value;
    currentLogSearchParams.time_frame = searchTimeFrameSelect.value;

    if (currentLogSearchParams.time_frame === 'custom') {
        currentLogSearchParams.start_date = searchStartDateInput.value;
        currentLogSearchParams.end_date = searchEndDateInput.value;
        if (!currentLogSearchParams.start_date || !currentLogSearchParams.end_date) {
            logsErrorMessage.textContent = 'For custom range, both start and end dates are required.';
            logsErrorMessage.style.display = 'block';
            return;
        }
    } else {
        delete currentLogSearchParams.start_date;
        delete currentLogSearchParams.end_date;
    }

    loadAndRenderDetailedLogs(1);
}

function resetLogSearchForm() {
    logSearchForm.reset();
    searchCustomDateDiv.style.display = 'none';

    currentLogSearchParams = {
        limit: DEFAULT_RECORDS_PER_PAGE,
        offset: 0,
        sort_by: 'timestamp_desc',
        time_frame: '1w',
        file_hash: '',
        rule_id: '',
        run_id: '',
        rule_execution_id: '',
        status_filter: ''
    };
    loadAndRenderDetailedLogs(1);
}


function initializeDetailedLogsSearch() {
    searchTimeFrameSelect.addEventListener('change', () => {
        searchCustomDateDiv.style.display = searchTimeFrameSelect.value === 'custom' ? 'block' : 'none';
    });
    logSearchForm.addEventListener('submit', handleLogSearchFormSubmit);
    resetSearchLogsButton.addEventListener('click', resetLogSearchForm);

    loadAndRenderDetailedLogs(1);
}


// --- DOMContentLoaded ---
document.addEventListener('DOMContentLoaded', async () => {
    console.log('Logs Page: DOM fully loaded and parsed.');

    butlerNameHeader = document.getElementById('butler-name-header');
    statsTimeFrameSelect = document.getElementById('stats-time-frame');
    statsCustomDateDiv = document.getElementById('stats-custom-date-range');
    statsStartDateInput = document.getElementById('stats-start-date');
    statsEndDateInput = document.getElementById('stats-end-date');
    updateStatsChartButton = document.getElementById('update-stats-chart-button');
    filesProcessedChartCanvas = document.getElementById('filesProcessedChart');
    statsLoadingMessage = document.getElementById('stats-loading-message');
    statsErrorMessage = document.getElementById('stats-error-message');
    logSearchForm = document.getElementById('log-search-form');
    searchFileHashInput = document.getElementById('search-file-hash');
    searchRuleIdInput = document.getElementById('search-rule-id');
    searchRunIdInput = document.getElementById('search-run-id');
    searchRuleExecutionIdInput = document.getElementById('search-rule-execution-id');
    searchStatusFilterInput = document.getElementById('search-status-filter');
    searchTimeFrameSelect = document.getElementById('search-time-frame');
    searchCustomDateDiv = document.getElementById('search-custom-date-range');
    searchStartDateInput = document.getElementById('search-start-date');
    searchEndDateInput = document.getElementById('search-end-date');
    searchSortBySelect = document.getElementById('search-sort-by');
    searchLogsButton = document.getElementById('search-logs-button');
    resetSearchLogsButton = document.getElementById('reset-search-logs-button');
    logsLoadingMessage = document.getElementById('logs-loading-message');
    logsErrorMessage = document.getElementById('logs-error-message');
    detailedLogsTableBody = document.getElementById('detailed-logs-table-body');
    logsPaginationControls = document.getElementById('logs-pagination-controls');
    detailedLogsResultsSummary = document.getElementById('detailed-logs-results-summary');

    try {
        await fetchClientSettings();
        applyTheme(clientThemeSetting);

        if (typeof window.HYDRUS_BUTLER_SETTINGS !== 'undefined' && window.HYDRUS_BUTLER_SETTINGS.butler_name) {
             if(butlerNameHeader) butlerNameHeader.textContent = window.HYDRUS_BUTLER_SETTINGS.butler_name + ' - Activity Logs';
        } else {
            console.warn("Butler name settings not found on window object for logs page header.");
        }

        // Ensure services and rules are loaded for use in renderDetailedLogRow
        // These calls will populate 'availableServices' and 'currentlyLoadedRules' in api.js
        await Promise.all([
            fetchAllServices(), 
            loadRules()         
        ]);
        console.log('Logs Page: Services and rules loaded and cached in api.js.');

        initializeLogStats();
        initializeDetailedLogsSearch();
    } catch (error) {
        console.error("Error initializing logs page:", error);
        if (statsErrorMessage) {
            statsErrorMessage.textContent = "Failed to initialize page. Please refresh.";
            statsErrorMessage.style.display = 'block';
        }
        if (logsErrorMessage) {
            logsErrorMessage.textContent = "Failed to initialize page. Please refresh.";
            logsErrorMessage.style.display = 'block';
        }
    }
});