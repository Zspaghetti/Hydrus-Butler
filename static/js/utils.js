/**
 * Helper function to get service name by key from a given list of services.
 * @param {string} serviceKey - The key of the service to find.
 * @param {Array<Object>} servicesList - The list of service objects (e.g., availableServices, availableFileServices).
 * @returns {string} The service name or the service key if not found.
 */
export function getServiceName(serviceKey, servicesList) {
    if (!servicesList) return serviceKey;
    const service = servicesList.find(s => s.service_key === serviceKey);
    return service ? service.name : serviceKey;
}

/**
 * Helper to populate a select element with options.
 * @param {HTMLSelectElement} selectElement - The select element to populate.
 * @param {Array<Object>} optionsList - An array of option objects { value: '...', text: '...' } or service objects { service_key: '...', name: '...' }.
 * @param {string} [defaultText=null] - Optional text for a default, unselectable option.
 * @param {*} [selectedValue=null] - Optional value to pre-select.
 */
export function populateSelectElement(selectElement, optionsList, defaultText = null, selectedValue = null) {
    if (!selectElement) {
        console.warn("populateSelectElement called with null element.");
        return;
    }

    selectElement.innerHTML = '';

    if (defaultText !== null && defaultText !== '') {
        const defaultOption = document.createElement('option');
        defaultOption.value = "";
        defaultOption.textContent = defaultText;
        selectElement.appendChild(defaultOption);
    }

    optionsList.forEach(optionData => {
        const option = document.createElement('option');
        // Use .value if available, otherwise fallback to .service_key
        const value = optionData.hasOwnProperty('value') ? optionData.value : optionData.service_key;
        // Use .text if available, otherwise fallback to .name
        const text = optionData.hasOwnProperty('text') ? optionData.text : optionData.name;


        option.value = value;
        option.textContent = text;

        // Store service details as data attributes if available
        if (optionData.type !== undefined) {
            option.dataset.serviceType = optionData.type;
            if (optionData.min_stars !== undefined) option.dataset.minStars = optionData.min_stars;
            if (optionData.max_stars !== undefined) option.dataset.maxStars = optionData.max_stars;
        }

        // Handle pre-selection, robustly comparing values
        if (selectedValue !== null && selectedValue !== undefined) {
             // Ensure robust comparison between different data types (e.g., numbers, strings, booleans represented as strings)
             // Comparing string representations should cover most cases safely.
            const optionValueString = String(option.value);
            const selectedValueString = String(selectedValue);

            if (optionValueString === selectedValueString) {
                option.selected = true;
            }
        }
        selectElement.appendChild(option);
    });
}