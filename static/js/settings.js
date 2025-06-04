// static/js/settings.js

// Import necessary functions/state from api.js for theme application
import { fetchClientSettings, clientThemeSetting } from './api.js';

// Global variable for butler name header if it exists on settings page
// let butlerNameHeaderSettings; // Example: <h1 id="butler-name-header-settings">

/**
 * Applies the selected theme to the settings page.
 * @param {string} themeName - The name of the theme.
 */
function applyTheme(themeName) {
    console.log(`Settings Page: Applying theme: ${themeName}`);
    document.body.className = document.body.className.replace(/\btheme-\S+/g, '');
    document.body.classList.add(`theme-${themeName}`); // e.g., theme-default

    // Assume settings.html uses a main stylesheet link, possibly with an ID
    // like #main-stylesheet, or it's the first one.
    const stylesheetLink = document.querySelector('link[rel="stylesheet"][href*="static/css/"]#main-stylesheet') ||
                           document.querySelector('link[rel="stylesheet"][href*="static/css/"]');

    if (stylesheetLink) {
        const expectedHref = `/static/css/${themeName}.css`;
        if (!stylesheetLink.getAttribute('href').endsWith(expectedHref)) {
            stylesheetLink.setAttribute('href', expectedHref);
            console.log(`Settings Page: Stylesheet link updated to: ${expectedHref}`);
        }
    } else {
        console.warn("Settings Page: Could not find a stylesheet link to update for the theme.");
    }
}

/**
 * Updates the butler name in the settings page header (if such an element exists).
 * This relies on window.HYDRUS_BUTLER_SETTINGS being populated by a base HTML template.
 */
function updateButlerNameDisplayOnSettingsPage() {
    // const butlerNameHeaderElement = document.getElementById('butler-name-header-settings'); // Example ID
    if (window.HYDRUS_BUTLER_SETTINGS && window.HYDRUS_BUTLER_SETTINGS.butler_name) {
        console.log(`Settings Page: Butler name is ${window.HYDRUS_BUTLER_SETTINGS.butler_name}`);
        // if (butlerNameHeaderElement) {
        //    butlerNameHeaderElement.textContent = `${window.HYDRUS_BUTLER_SETTINGS.butler_name} - Settings`;
        // }
    }
}

document.addEventListener('DOMContentLoaded', async () => {
    console.log('Settings Page: DOM fully loaded and parsed.');

    // Apply theme and update butler name display on load
    try {
        await fetchClientSettings(); // Fetches theme from backend client settings
        applyTheme(clientThemeSetting);
        updateButlerNameDisplayOnSettingsPage(); // If butler name is displayed in settings page header
    } catch (error) {
        console.error("Settings Page: Error during initial setup (theme/butler name):", error);
    }

    const settingsForm = document.getElementById('settings-form');
    const messagesDiv = document.getElementById('messages'); // Ensure your settings.html has <div id="messages"> for Flask flashed messages and JS messages

    // Note: Initial form values and theme dropdown options are expected to be populated
    // by Jinja templating on the server-side (settings.html).

    if (settingsForm) {
        settingsForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            console.log('Settings form submission initiated.');

            if (messagesDiv) {
                // Clear previous JS-set messages, Flask messages will remain until next server response
                const jsMessages = messagesDiv.querySelectorAll('.js-message');
                jsMessages.forEach(msg => msg.remove());

                const savingMsg = document.createElement('div');
                savingMsg.textContent = 'Saving...';
                savingMsg.className = 'message info js-message'; // Add js-message class
                messagesDiv.appendChild(savingMsg);
            }

            const formData = new FormData(settingsForm);
            // The names in FormData are derived from the `name` attributes of your HTML inputs
            // e.g., <input name="api-address" ...>

            // Basic client-side validation (optional, server-side is primary)
            const ruleInterval = formData.get('rule-interval-seconds'); // Ensure this matches input name in HTML
            if (ruleInterval && parseInt(ruleInterval, 10) < 0) {
                if (messagesDiv) {
                    const errorMsg = document.createElement('div');
                    errorMsg.textContent = 'Error: Rule Interval cannot be negative.';
                    errorMsg.className = 'message error js-message';
                    messagesDiv.appendChild(errorMsg);
                    messagesDiv.querySelector('.info.js-message')?.remove(); // Remove "Saving..."
                }
                return;
            }
            const lastViewedThreshold = formData.get('last-viewed-threshold-seconds'); // Ensure this matches input name
            if (lastViewedThreshold && parseInt(lastViewedThreshold, 10) < 0) {
                 if (messagesDiv) {
                    const errorMsg = document.createElement('div');
                    errorMsg.textContent = 'Error: Last Viewed Threshold cannot be negative.';
                    errorMsg.className = 'message error js-message';
                    messagesDiv.appendChild(errorMsg);
                    messagesDiv.querySelector('.info.js-message')?.remove(); // Remove "Saving..."
                 }
                return;
            }

            try {
                const response = await fetch('/save_settings', {
                    method: 'POST',
                    body: formData // FormData is sent as 'multipart/form-data' or 'application/x-www-form-urlencoded'
                });

                // Backend redirects on success, browser handles it. Flashed messages appear on reload.
                // If !response.ok, an error occurred server-side before redirect.
                if (!response.ok) {
                    let errorData = { message: `HTTP error! Status: ${response.status}` };
                    try {
                        const jsonData = await response.json(); // Check if server sent a JSON error
                        if (jsonData && jsonData.message) errorData.message = jsonData.message;
                    } catch (e) {
                        errorData.message = response.statusText || errorData.message;
                    }
                    console.error('Failed to save settings:', errorData.message);
                    if (messagesDiv) {
                        const errorMsg = document.createElement('div');
                        errorMsg.textContent = `Error: ${errorData.message}`;
                        errorMsg.className = 'message error js-message';
                        messagesDiv.appendChild(errorMsg);
                        messagesDiv.querySelector('.info.js-message')?.remove(); // Remove "Saving..."
                    }
                } else {
                    // If response.ok and backend sends a redirect (status 302),
                    // the browser will automatically follow it.
                    // The 'fetch' promise resolves for redirects, so response.ok will be true.
                    // We don't need to manually reload if redirected.
                    if (response.redirected) {
                        console.log("Settings saved, browser is handling redirect.");
                        // The "Saving..." message will disappear on page reload.
                        // Flask's flashed messages will appear.
                    } else {
                        // This case handles if the backend responded with 200 OK but didn't redirect.
                        // (This is not the current behavior of views.py for save_settings)
                        const result = await response.json();
                         if (result.success) {
                            if (messagesDiv) {
                                const successMsg = document.createElement('div');
                                successMsg.textContent = result.message || 'Settings saved successfully! Page will reload.';
                                successMsg.className = 'message success js-message';
                                messagesDiv.appendChild(successMsg);
                                messagesDiv.querySelector('.info.js-message')?.remove(); // Remove "Saving..."
                            }
                            window.location.reload(); // Manually reload if no redirect from server
                         } else {
                            if (messagesDiv) {
                                const errorMsg = document.createElement('div');
                                errorMsg.textContent = `Error: ${result.message || 'Could not save settings.'}`;
                                errorMsg.className = 'message error js-message';
                                messagesDiv.appendChild(errorMsg);
                                messagesDiv.querySelector('.info.js-message')?.remove(); // Remove "Saving..."
                            }
                         }
                    }
                }
            } catch (error) {
                console.error('Network error or other issue saving settings:', error);
                if (messagesDiv) {
                    const errorMsg = document.createElement('div');
                    errorMsg.textContent = `Error: ${error.message || 'A network error occurred.'}`;
                    errorMsg.className = 'message error js-message';
                    messagesDiv.appendChild(errorMsg);
                    messagesDiv.querySelector('.info.js-message')?.remove(); // Remove "Saving..."
                }
            }
        });
    } else {
        console.warn('Settings form (#settings-form) not found.');
    }

    // "Test Hydrus API Connection" Button Functionality is REMOVED
    // as there is no corresponding backend endpoint in the provided views.py
    const testConnectionButton = document.getElementById('test-hydrus-connection-button');
    if (testConnectionButton) {
        console.warn("Test connection button found in HTML, but no JavaScript functionality is wired up because the backend endpoint is missing in views.py.");
        // Optionally hide it if it's not meant to be there without functionality:
        // testConnectionButton.style.display = 'none';
        // const testConnectionResultDiv = document.getElementById('test-connection-result');
        // if (testConnectionResultDiv) testConnectionResultDiv.style.display = 'none';
    }
});