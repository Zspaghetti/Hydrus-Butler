import { currentlyLoadedRules, availableFileServices, availableTagServices, availableRatingServices, availableServices } from './api.js';
import { getConditionSummary } from './conditions_data.js';
import { getServiceName } from './utils.js';
import { runRule } from './rules_actions.js';
import { deleteRule } from './rules_actions.js';
import { editRule } from './edit_rule.js';


const rulesTableBody = document.querySelector('#rules-table tbody');
const noRulesMessage = document.getElementById('no-rules-message');
const rulesTable = document.getElementById('rules-table');

export function renderRulesTable(rules) {
    console.log("Rendering rules table with", rules.length, "rules. Rules data:", rules);
    rulesTableBody.innerHTML = '';

    if (!rules || rules.length === 0) {
        noRulesMessage.style.display = 'block';
        rulesTable.style.display = 'none';
    } else {
        noRulesMessage.style.display = 'none';
        rulesTable.style.display = 'table';

        rules.forEach((rule, index) => {
            const row = rulesTableBody.insertRow();

            row.insertCell(0).textContent = index + 1;
            row.insertCell(1).textContent = rule.priority;

            const nameCell = row.insertCell(2);
            nameCell.textContent = rule.name || `Rule #${index + 1}`;

            const conditionsSummary = (rule.conditions && Array.isArray(rule.conditions))
                ? rule.conditions.map(c => getConditionSummary(c)).join(' and ')
                : 'No conditions';
            const conditionsCell = row.insertCell(3);
            conditionsCell.textContent = conditionsSummary;
             if (conditionsSummary.length > 50) { // Add tooltip for long summaries
                 conditionsCell.setAttribute('title', conditionsSummary);
                 conditionsCell.textContent = conditionsSummary.substring(0, 47) + "...";
             }


            const actionCell = row.insertCell(4);
            actionCell.innerHTML = ''; // Clear previous content
            let actionText = rule.action.type; // Default

            if (rule.action.type === 'add_to') {
                actionText = 'Add to (File Service)';
                actionCell.textContent = actionText;
            } else if (rule.action.type === 'force_in') {
                actionText = 'Force in (File Service)';
                actionCell.textContent = actionText;
            } else if (rule.action.type === 'add_tags' || rule.action.type === 'remove_tags') {
                const actionVerb = rule.action.type === 'add_tags' ? 'Add' : 'Remove';
                if (Array.isArray(rule.action.tags_to_process) && rule.action.tags_to_process.length > 0) {
                    rule.action.tags_to_process.forEach(tag => {
                        const tagActionDiv = document.createElement('div');
                        tagActionDiv.textContent = `${actionVerb}: ${tag}`;
                        actionCell.appendChild(tagActionDiv);
                    });
                } else {
                    actionCell.textContent = `${actionVerb} Tags (No tags specified)`;
                }
            } else if (rule.action.type === 'modify_rating') {
                const ratingValue = rule.action.rating_value;
                const serviceDetails = availableServices.find(s => s.service_key === rule.action.rating_service_key);
                if (ratingValue === true) {
                    actionText = "Set to Liked";
                } else if (ratingValue === false) {
                    actionText = "Set to Disliked";
                } else if (ratingValue === null && typeof ratingValue === 'object') {
                    actionText = "Set to No Rating";
                } else if (typeof ratingValue === 'number') {
                    actionText = `Set to ${ratingValue}`;
                    if (serviceDetails && serviceDetails.type === 6 && serviceDetails.max_stars) { // Numerical (Type 6) with max_stars
                        actionText += `/${serviceDetails.max_stars}`;
                    }
                } else {
                    actionText = "Modify Rating (Unknown value)";
                }
                actionCell.textContent = actionText;
            } else {
                 actionCell.textContent = actionText; // Fallback for other types
            }


            const destinationCell = row.insertCell(5);
            let destinationDisplay = 'N/A';
            let destinationTitle = ''; // For tooltip

            if (rule.action.type === 'add_to' || rule.action.type === 'force_in') {
                if (rule.action.destination_service_keys && Array.isArray(rule.action.destination_service_keys) && rule.action.destination_service_keys.length > 0) {
                    const serviceNames = rule.action.destination_service_keys.map(key => getServiceName(key, availableFileServices));
                    destinationDisplay = serviceNames.join(', ');
                    destinationTitle = `File Services: ${serviceNames.join(', ')} (${rule.action.destination_service_keys.join(', ')})`;
                } else if (rule.action.destination_service_key) { // Fallback
                    destinationDisplay = getServiceName(rule.action.destination_service_key, availableFileServices);
                    destinationTitle = `File Service: ${destinationDisplay} (${rule.action.destination_service_key})`;
                }
            } else if (rule.action.type === 'add_tags' || rule.action.type === 'remove_tags') {
                if (rule.action.tag_service_key) {
                    destinationDisplay = getServiceName(rule.action.tag_service_key, availableTagServices);
                    destinationTitle = `Target Tag Service: ${destinationDisplay} (${rule.action.tag_service_key})`;
                } else {
                    destinationDisplay = "Tag Service (N/A)";
                }
            } else if (rule.action.type === 'modify_rating') {
                if (rule.action.rating_service_key) {
                    destinationDisplay = getServiceName(rule.action.rating_service_key, availableRatingServices);
                    destinationTitle = `Target Rating Service: ${destinationDisplay} (${rule.action.rating_service_key})`;
                } else {
                    destinationDisplay = "Rating Service (N/A)";
                }
            }

            destinationCell.textContent = destinationDisplay;
            // Tooltip and truncation logic
            if (destinationTitle) { // If a specific title is set, always use it
                destinationCell.setAttribute('title', destinationTitle);
                if (destinationDisplay.length > 30) { // Truncate if there's a title and display text is long
                     destinationCell.textContent = destinationDisplay.substring(0, 27) + "...";
                }
            } else if (destinationDisplay.length > 30) { // Auto-tooltip for long display text if no specific title
                destinationCell.setAttribute('title', destinationDisplay);
                destinationCell.textContent = destinationDisplay.substring(0, 27) + "...";
            }


            const actionsCell = row.insertCell(6);
            const runButton = document.createElement('button');
            runButton.classList.add('run-button');
            runButton.textContent = 'Run';
            runButton.addEventListener('click', async () => {
                 const ruleNameForNotif = rule.name || `Rule #${index + 1}`;
                 await runRule(rule.id, ruleNameForNotif);
            });
            actionsCell.appendChild(runButton);

            const editButton = document.createElement('button');
            editButton.classList.add('edit-button');
            editButton.textContent = 'Edit';
            editButton.addEventListener('click', () => editRule(rule.id));
            actionsCell.appendChild(editButton);

            const deleteButton = document.createElement('button');
            deleteButton.classList.add('delete-button');
            deleteButton.textContent = 'Delete';
            deleteButton.addEventListener('click', async () => {
                await deleteRule(rule.id);
            });
            actionsCell.appendChild(deleteButton);
        });
    }
}