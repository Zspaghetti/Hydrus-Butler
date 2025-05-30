// Import API functions and state
import {
    fetchClientSettings,
    fetchAllServices,
    saveRule,
    loadRules,
    currentlyLoadedRules,
    showNotificationsSetting, // Keep this if used elsewhere
    clientThemeSetting,     // Import the new theme setting
    availableServices
} from './api.js';
// Import render function for the rules table
import { renderRulesTable } from './rules_table_ui.js';
// Import modal functions and the function to set the addConditionRow
import { resetForm, showModal, hideModal, setAddConditionRowFunction, renderModifyRatingInputs } from './modal.js';
// Import functions related to conditions UI and data
import { refreshModalConditionsUI, addConditionRow } from './conditions_ui.js';
// Import extraction logic for form submission
import { extractConditionData } from './conditions_data.js';
// Import action for running all rules manually
import { runAllRulesManual } from './rules_actions.js';


/**
 * Applies the selected theme to the application.
 * @param {string} themeName - The name of the theme (e.g., 'dark', 'light').
 */
function applyTheme(themeName) {
    console.log(`Applying theme: ${themeName}`);
    // Remove any existing theme-specific body classes
    document.body.className = document.body.className.replace(/\btheme-\S+/g, '');
    // Add the new theme class
    document.body.classList.add(`theme-${themeName}`);

    // Update the main stylesheet link
    // This assumes a single main stylesheet link that needs to be theme-dependent.
    // If you have multiple, you might need a more specific selector or ID.
    const stylesheetLink = document.querySelector('link[rel="stylesheet"][href*="static/css/"]');
    if (stylesheetLink) {
        // Check if the current href already matches the theme to avoid unnecessary DOM manipulation
        const expectedHref = `/static/css/${themeName}.css`; // Path as seen by the browser
        if (!stylesheetLink.getAttribute('href').endsWith(expectedHref)) {
            stylesheetLink.setAttribute('href', `/static/css/${themeName}.css`);
            console.log(`Stylesheet link updated to: /static/css/${themeName}.css`);
        }
    } else {
        console.warn("Could not find the main stylesheet link to update for the theme.");
    }
}


document.addEventListener('DOMContentLoaded', () => {
    console.log('DOM fully loaded and parsed for main page.');

    const addRuleButton = document.getElementById('add-rule-button');
    const updateServicesButton = document.getElementById('update-services-button');
    const ruleForm = document.getElementById('rule-form');
    const conditionsContainer = document.getElementById('conditions-container');
    const ruleModal = document.getElementById('rule-modal');
    const runAllRulesButton = document.getElementById('run-all-rules-button');

    setAddConditionRowFunction(addConditionRow);

    console.log("Initial page load: Fetching client settings, all services, then loading rules.");

    async function initializeApp() {
        try {
            await fetchClientSettings(); // Fetches notification settings AND theme
            applyTheme(clientThemeSetting); // Use the fetched theme

            const servicesResult = await fetchAllServices();
            if (!servicesResult.success) {
                console.warn("Initial fetch of services failed or returned empty. UI might be limited but app should run.", servicesResult.message);
            }

            const rulesResult = await loadRules();
            if (rulesResult.success) {
                renderRulesTable(currentlyLoadedRules);
            } else {
                console.error("Failed to load rules:", rulesResult.message);
                const rulesTableBody = document.querySelector('#rules-table tbody');
                if (rulesTableBody) {
                    rulesTableBody.innerHTML = '<tr><td colspan="7" style="text-align:center; color:red;">Failed to load rules. Please check server logs.</td></tr>';
                }
                 document.getElementById('no-rules-message').style.display = 'none';
                 document.getElementById('rules-table').style.display = 'table';
            }
        } catch (error) {
            console.error("Critical error during initial app load sequence:", error);
            const mainContent = document.querySelector('main');
            if (mainContent) {
                mainContent.innerHTML = '<h2 style="color:red;">Failed to initialize the application. Please try refreshing the page or check server status.</h2>';
            }
        }
    }

    initializeApp();


    addRuleButton.addEventListener('click', () => {
        console.log("Add Rule button clicked");
        resetForm();
        if (addConditionRow && conditionsContainer) {
            console.log("Main.js: Adding initial condition row for new rule.");
            addConditionRow(conditionsContainer);
        } else {
            console.error("Main.js: Cannot add initial condition row - function or container missing.");
        }
        showModal();
    });

    updateServicesButton.addEventListener('click', async () => {
        console.log("Update Services button clicked");
        try {
            const servicesUpdateResult = await fetchAllServices(true);
            if (servicesUpdateResult.success) {
                console.log("Services updated successfully by button click.");
            } else {
                console.warn("Service update via button failed or returned empty:", servicesUpdateResult.message);
                alert(`Could not update services: ${servicesUpdateResult.message || 'Unknown error'}`);
            }

            if (ruleModal.style.display !== 'none') {
                   console.log("Modal is open, refreshing modal UI after service update attempt.");
                   refreshModalConditionsUI();

                   const actionTypeSelect = document.getElementById('action-type');
                   if(actionTypeSelect) {
                       actionTypeSelect.dispatchEvent(new Event('change'));
                       if (actionTypeSelect.value === 'modify_rating') {
                           const modifyRatingServiceSel = document.getElementById('modify-rating-service-select');
                           if (modifyRatingServiceSel) {
                               renderModifyRatingInputs(modifyRatingServiceSel.value, {});
                           }
                       }
                   }
              }
        } catch (error) {
              console.error("Error during services update via button:", error);
              alert(`An error occurred while updating services: ${error.message}`);
        }
    });

    if (runAllRulesButton) {
        runAllRulesButton.addEventListener('click', () => {
            console.log("'Run All Rules Now' button clicked.");
            runAllRulesManual();
        });
    } else {
        console.warn("'Run All Rules Now' button not found in the DOM.");
    }

    ruleForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        console.log("Rule form submitted");

        const ruleId = ruleForm.dataset.editingRuleId || '';
        let ruleName = document.getElementById('rule-name').value.trim();
        const rulePriority = parseInt(document.getElementById('rule-priority').value, 10);
        const actionType = document.getElementById('action-type').value;

        const destinationServiceSelects = document.querySelectorAll('.destination-service-select');
        const destinationServiceKeys = [];
        destinationServiceSelects.forEach(select => {
            if (select.value) {
                destinationServiceKeys.push(select.value);
            }
        });

        const tagActionServiceKey = document.getElementById('tag-action-service-select').value;
        const tagActionTagsValue = document.getElementById('tag-action-tags-input').value;
        const tagsToProcess = tagActionTagsValue.split(',')
                                             .map(tag => tag.trim())
                                             .filter(tag => tag !== '');

        let modifyRatingActionServiceKey = '';
        let modifyRatingActionValue = undefined;

        if (actionType === 'modify_rating') {
            modifyRatingActionServiceKey = document.getElementById('modify-rating-service-select').value;
            const service = availableServices.find(s => s.service_key === modifyRatingActionServiceKey);

            if (service) {
                if (service.type === 7) { // Like/Dislike
                    const stateSelect = document.querySelector('select[name="modify-rating-action-state"]');
                    if (stateSelect && stateSelect.value) {
                        if (stateSelect.value === 'liked') modifyRatingActionValue = true;
                        else if (stateSelect.value === 'disliked') modifyRatingActionValue = false;
                        else if (stateSelect.value === 'no_rating') modifyRatingActionValue = null;
                    }
                } else if (service.type === 6 || service.type === 22) { // Numerical or Inc/Dec
                    const choiceSelect = document.querySelector('select[name="modify-rating-action-numerical-choice"]');
                    if (choiceSelect && choiceSelect.value) {
                        if (choiceSelect.value === 'set_value') {
                            const valueInput = document.querySelector('input[name="modify-rating-action-value"]');
                            if (valueInput && valueInput.value !== '') {
                                modifyRatingActionValue = parseFloat(valueInput.value);
                                if (isNaN(modifyRatingActionValue)) modifyRatingActionValue = undefined;
                            }
                        } else if (choiceSelect.value === 'no_rating') {
                            modifyRatingActionValue = null;
                        }
                    }
                }
            }
        }

        const conditions = [];
        let overallFormIsValid = true;
        let validationMessages = [];

        if (!conditionsContainer) {
            console.error("conditionsContainer is not defined in ruleForm submit listener!");
            alert("Critical error: Cannot find conditions container.");
            return;
        }

        console.log(`Main.js submit: Found ${conditionsContainer.querySelectorAll(':scope > .condition-row').length} direct .condition-row children in conditionsContainer.`);

        conditionsContainer.querySelectorAll(':scope > .condition-row').forEach(rowElement => {
            console.log("Main.js submit: Processing rowElement HTML:", rowElement.outerHTML.substring(0, 300) + "...");
            const result = extractConditionData(rowElement);
            if (result.isValid) {
                conditions.push(result.data);
            } else {
                overallFormIsValid = false;
                validationMessages.push(`Condition invalid: ${result.message}`);
            }
        });

        if (isNaN(rulePriority)) {
            validationMessages.push('Please enter a valid number for Priority.');
            overallFormIsValid = false;
        }
        const totalConditionRows = conditionsContainer.querySelectorAll(':scope > .condition-row').length;
        if (conditions.length === 0 && totalConditionRows > 0) {
            validationMessages.push('Rule must contain at least one valid top-level condition, or all top-level conditions are invalid.');
            overallFormIsValid = false;
        } else if (totalConditionRows === 0) {
             validationMessages.push('Rule must have at least one top-level condition row. Please add one.');
             overallFormIsValid = false;
        }

        if (!actionType) {
            validationMessages.push('Please select an Action.');
            overallFormIsValid = false;
        }

        if (['add_to', 'force_in'].includes(actionType)) {
            if (destinationServiceKeys.length === 0) {
                validationMessages.push(`Action type "${actionType}" requires at least one destination file service.`);
                overallFormIsValid = false;
            }
            const uniqueDestinationServiceKeys = new Set(destinationServiceKeys);
            if (uniqueDestinationServiceKeys.size !== destinationServiceKeys.length) {
                validationMessages.push('Please select unique destination file services. Duplicates are not allowed.');
                overallFormIsValid = false;
            }
        } else if (['add_tags', 'remove_tags'].includes(actionType)) {
            if (!tagActionServiceKey) {
                validationMessages.push(`Action type "${actionType}" requires a target tag service.`);
                overallFormIsValid = false;
            }
            if (tagsToProcess.length === 0) {
                validationMessages.push(`Action type "${actionType}" requires at least one tag.`);
                overallFormIsValid = false;
            }
        } else if (actionType === 'modify_rating') {
            if (!modifyRatingActionServiceKey) {
                validationMessages.push('Modify Rating action requires a target rating service.');
                overallFormIsValid = false;
            }
            if (modifyRatingActionValue === undefined) {
                validationMessages.push('Modify Rating action requires a rating state/value to be set.');
                overallFormIsValid = false;
            } else {
                const service = availableServices.find(s => s.service_key === modifyRatingActionServiceKey);
                if (service && (service.type === 6 || service.type === 22) && typeof modifyRatingActionValue === 'number') {
                    if (service.min_stars !== undefined && modifyRatingActionValue < service.min_stars) {
                        validationMessages.push(`Rating value ${modifyRatingActionValue} is less than minimum ${service.min_stars} for service "${service.name}".`);
                        overallFormIsValid = false;
                    }
                    if (service.max_stars !== undefined && modifyRatingActionValue > service.max_stars) {
                        validationMessages.push(`Rating value ${modifyRatingActionValue} is greater than maximum ${service.max_stars} for service "${service.name}".`);
                        overallFormIsValid = false;
                    }
                }
            }
        }

        if (!overallFormIsValid) {
            alert('Please correct the following issues:\n\n' + validationMessages.join('\n'));
            console.warn("Form validation failed:", validationMessages);
            return;
        }

        let actionObject = {};
        if (['add_to', 'force_in'].includes(actionType)) {
            actionObject = {
                type: actionType,
                destination_service_keys: destinationServiceKeys
            };
        } else if (['add_tags', 'remove_tags'].includes(actionType)) {
            actionObject = {
                type: actionType,
                tag_service_key: tagActionServiceKey,
                tags_to_process: tagsToProcess
            };
        } else if (actionType === 'modify_rating') {
            actionObject = {
                type: 'modify_rating',
                rating_service_key: modifyRatingActionServiceKey,
                rating_value: modifyRatingActionValue
            };
        } else {
            console.error("Unknown action type during form submission:", actionType);
            alert("An unknown error occurred with the selected action type.");
            return;
        }

        const ruleToSave = {
            id: ruleId,
            name: ruleName,
            priority: rulePriority,
            conditions: conditions,
            action: actionObject
        };

        console.log("Attempting to save rule (from main.js):", JSON.parse(JSON.stringify(ruleToSave)));

        const result = await saveRule(ruleToSave);

        if (result.success) {
            console.log("Rule saved successfully:", result);
            hideModal();
            renderRulesTable(currentlyLoadedRules);
            // This ensures that if the theme was changed in settings and saved,
            // the current page reflects it immediately if the saveRule function itself
            // doesn't trigger a page reload. Given settings save *does* cause a redirect/reload,
            // this might be redundant but safe.
            // More importantly, if saveRule was for a *rule* and not settings, this is irrelevant.
            // However, if settings save leads to this page, the theme from fetchClientSettings
            // should be reapplied. The existing `applyTheme` in `initializeApp` covers this for
            // page load/reload.
            // No, this is not needed here because saveRule is for *rules*, not global settings.
            // Global settings save in Flask redirects, and initializeApp handles theme on next load.
        } else {
            console.error("Failed to save rule:", result.message);
            alert(`Failed to save rule: ${result.message || "An unknown error occurred."}`);
        }
    });

});