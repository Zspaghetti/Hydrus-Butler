import { 
    runRule as runRuleApi, 
    deleteRule as deleteRuleApi, 
    runAllRulesManualApi,
    currentlyLoadedRules, 
    showNotificationsSetting,
    clientShowRunAllNotificationsSetting // Import the new setting
} from './api.js';

import { renderRulesTable } from './rules_table_ui.js'; // Import render function to refresh table after delete


/**
 * Executes a rule manually.
 * @param {string} ruleId - The ID of the rule to run.
 * @param {string} ruleName - The name of the rule (for notifications).
 * @returns {Promise<void>}
 */
export async function runRule(ruleId, ruleName) {
    console.log("Attempting to run rule:", ruleName);

    // Check the setting before the confirmation prompt
    if (showNotificationsSetting) {
        if (!confirm(`Are you sure you want to run the rule "${ruleName}"? This action might affect files in your Hydrus library.`)) {
            console.log("Rule run cancelled by user.");
            return; // User cancelled
        }
    }

    // Call the API function to run the rule
    const result = await runRuleApi(ruleId);

    // Handle the result and provide feedback
    if (result.success) {
        console.log("Rule execution successful:", result);
        let message = `Rule "${ruleName}" executed successfully.`;
        // Append summary details if available in the result
        if (result.message) {
            message += `\nSummary: ${result.message}`;
        }
        // Include other relevant summary counts
        if (result.files_matched_by_search !== undefined) {
            message += `\nFiles Matched: ${result.files_matched_by_search}`;
        }
        if (result.files_action_attempted_on !== undefined) {
            message += `\nAction Attempted On: ${result.files_action_attempted_on}`;
        }
        if (result.files_migrated_successfully !== undefined) {
            message += `\nMigrated/Copied: ${result.files_migrated_successfully}`;
        }
        if (result.action_performed === 'move' && result.deletion_operations_successful !== undefined) {
            message += `\nDeletion Operations Successful: ${result.deletion_operations_successful}`;
        }
         if (result.translation_warnings && result.translation_warnings.length > 0) {
            message += `\nWarnings: ${result.translation_warnings.length}`;
        }
         if (result.metadata_errors && result.metadata_errors.length > 0) {
            message += `\nMetadata Errors: ${result.metadata_errors.length}`;
         }
         if (result.migration_errors && result.migration_errors.length > 0) {
            message += `\nMigration Errors: ${result.migration_errors.length}`;
         }
         if (result.deletion_errors && result.deletion_errors.length > 0) {
            message += `\nDeletion Errors: ${result.deletion_errors.length}`;
         }


        // Check the setting again before showing the result notification
        if (showNotificationsSetting) {
            alert(message);
        }

    } else {
        console.error("Failed to execute rule:", result.message);
        // Always show error notifications, regardless of setting
        alert(`Failed to execute rule "${ruleName}":\n${result.message || "An unknown error occurred."}`);
    }
}
/**
 * Manually triggers the execution of all rules.
 * @returns {Promise<void>}
 */
export async function runAllRulesManual() {
    console.log("Attempting to 'Run All Rules' manually.");

    let userConfirmed = false;
    if (clientShowRunAllNotificationsSetting) {
        if (confirm(`Are you sure you want to run ALL rules now? 
This will process rules according to their priority and respect existing conflict overrides. 
This action might affect many files in your Hydrus library.`)) {
            userConfirmed = true;
        }
    } else {
        userConfirmed = true; // Skip confirmation if setting is false
    }

    if (!userConfirmed) {
        console.log("'Run All Rules' manually cancelled by user.");
        return; 
    }

    // Call the API function to run all rules
    const result = await runAllRulesManualApi();

    // Handle the result and provide feedback
    if (result.success !== undefined) { // Check if result is structured as expected
        console.log("'Run All Rules' manually execution processed:", result);
        let alertMessage = `'Run All Rules' process completed.`;
        
        if (result.message) {
            alertMessage += `\n\nOverall Summary: ${result.message}`;
        }

        if (result.summary_totals) {
            const totals = result.summary_totals;
            alertMessage += `\n\n--- Totals ---`;
            alertMessage += `\nRules Processed: ${totals.rules_processed || 0}`;
            if (totals.rules_with_errors > 0) {
                alertMessage += `\nRules with Errors: ${totals.rules_with_errors}`;
            }
            alertMessage += `\nFiles Matched: ${totals.files_matched_by_search || 0}`;
            alertMessage += `\nActions Attempted: ${totals.files_action_attempted_on || 0}`;
            if (totals.files_skipped_due_to_override > 0) {
                 alertMessage += `\nSkipped by Override: ${totals.files_skipped_due_to_override}`;
            }
            // You can add more details from summary_totals if needed
        }
        
        if (result.results_per_rule && result.results_per_rule.length > 0) {
            const rulesWithIssues = result.results_per_rule.filter(r => !r.success);
            if (rulesWithIssues.length > 0) {
                alertMessage += `\n\n--- Rules with Issues ---`;
                rulesWithIssues.forEach(r => {
                    alertMessage += `\n- ${r.rule_name || r.rule_id}: ${r.message || 'Failed'}`;
                });
            }
        }
        
        if (clientShowRunAllNotificationsSetting) {
            alert(alertMessage);
        }

    } else {
        // Fallback for unexpected result structure
        console.error("Failed to execute 'Run All Rules' manually or unexpected result structure:", result);
        // Always show error notifications for the "Run All" action if the API call itself seems to have failed badly
        alert(`Failed to execute 'Run All Rules' manually:\n${result.message || "An unknown error or unexpected server response occurred."}`);
    }
}


/**
 * Deletes a rule.
 * @param {string} ruleId - The ID of the rule to delete.
 * @returns {Promise<object>} The result object from the API call.
 */
export async function deleteRule(ruleId) {
    console.log("Attempting to delete rule with ID:", ruleId);
    // Find the rule name for the confirmation message
    const ruleToDelete = currentlyLoadedRules.find(rule => rule.id === ruleId);
    const ruleName = ruleToDelete ? `"${ruleToDelete.name}"` : `with ID ${ruleId}`;

    if (confirm(`Are you sure you want to delete the rule ${ruleName}? This action cannot be undone.`)) {
        // Call the API function to delete the rule
        const result = await deleteRuleApi(ruleId);

        if (result.success) {
            console.log("Rule deleted successfully:", result);
            // API's deleteRule calls loadRules, so currentlyLoadedRules is updated.
            renderRulesTable(currentlyLoadedRules); // Re-render the table
        } else {
            console.error("Failed to delete rule:", result.message);
            alert(`Failed to delete rule: ${result.message || "An unknown error occurred."}`);
        }
         return result; // Return the API result
    } else {
         console.log("Rule deletion cancelled by user.");
         return { success: false, message: "Deletion cancelled." };
    }
}