body {
    font-family: sans-serif;
    margin: 0;
    padding: 0;
    background-color: #2c3e50; /* Dark background */
    color: #ecf0f1; /* Light text */
}

header {
    background-color: #34495e; /* Slightly lighter dark */
    color: white;
    padding: 10px 20px;
    display: flex;
    justify-content.space-between;
    align-items: center;
}

nav button {
    padding: 8px 15px;
    background-color: #3498db; /* Blue */
    color: white;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-size: 1em;
}

nav button:hover {
    background-color: #2980b9; /* Darker blue */
}

main {
    padding: 20px;
}

h1, h2, h3 {
    color: #ecf0f1;
}

/* Keep these specific styles for the settings form, but apply general form styles too */
#settings-form div {
    margin-bottom: 15px;
}

#settings-form label {
    display: block;
    margin-bottom: 5px;
    font-weight: bold;
}

#settings-form input[type="text"],
#settings-form input[type="password"],
#settings-form input[type="number"],
#settings-form select { /* Added select for settings form */
     width: calc(100% - 18px); /* Adjust for padding and border */
     padding: 8px;
     box-sizing: border-box;
     background-color: #3b546d;
     border: 1px solid #4a627a;
     color: #ecf0f1;
     border-radius: 4px;
}

#settings-form input[type="number"] {
    width: 100px; /* Make number inputs shorter */
}

{# --- START Modification 1: Styles for the new checkbox row layout --- #}
/* Styles for the new checkbox row layout */
#settings-form .checkbox-row {
    display: flex; /* Use flexbox to put checkbox and label side-by-side */
    align-items: center; /* Align items vertically in the middle */
    gap: 10px; /* Add space between the checkbox and the label */
    margin-bottom: 15px;
}
 #settings-form .checkbox-row label {
     margin-bottom: 0; /* Remove the default bottom margin from the label within the flex container */
     font-weight: normal; /* Reduce font weight for checkbox labels compared to standard labels */
     display: inline-block; /* Ensure label is inline-block so it flexes correctly */
 }
#settings-form .checkbox-row input[type="checkbox"] {
    width: auto; /* Prevent checkbox from trying to be 100% width */
    margin: 0; /* Remove default margin */
    flex-shrink: 0; /* Prevent the checkbox from shrinking */
}
{# --- END Modification 1 --- #}


/* General button style for forms (used in settings too) */
button[type="submit"] {
     padding: 10px 20px;
     background-color: #2ecc71; /* Green */
     color: white;
     border: none;
     border-radius: 4px;
     cursor: pointer;
     font-size: 1em;
}

button[type="submit"]:hover {
    background-color: #27ae60; /* Darker green */
}


footer {
    text-align: center;
    padding: 10px;
    margin-top: 20px;
    color: #bdc3c7; /* Grey */
    font-size: 0.9em;
}

ul {
    list-style: none;
    padding: 0;
}

ul li {
    margin-bottom: 5px;
}

.add-button {
    padding: 10px 15px;
    font-size: 1.5em;
    background-color: #2ecc71; /* Green */
    color: white;
    border: none;
    border-radius: 50%; /* Make it round */
    cursor: pointer;
    position: fixed; /* Fixed position on the page */
    bottom: 20px;
    right: 20px;
    box-shadow: 0 2px 5px rgba(0, 0, 0, 0.3);
    line-height: 1; /* Adjust for the plus sign */
    z-index: 500; /* Ensure it's above other main content */
}

.add-button:hover {
    background-color: #27ae60; /* Darker green */
}

.secondary-button {
    padding: 8px 15px;
    background-color: #3498db; /* Blue */
    color: white;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-size: 1em;
    margin-bottom: 10px; /* Space below the button */
}

.secondary-button:hover {
    background-color: #2980b9; /* Darker blue */
}


#rules-table-container {
    margin-top: 20px;
}

#rules-table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 10px;
}

#rules-table th,
#rules-table td {
    border: 1px solid #34495e;
    padding: 10px;
    text-align: left;
}

#rules-table th {
    background-color: #34495e;
    color: white;
}

#rules-table tbody tr:nth-child(even) {
    background-color: #3b546d; /* Alternate row color */
}

#rules-table tbody tr:hover {
    background-color: #4a627a; /* Hover effect */
}

/* Style for action buttons within the table cells */
#rules-table td button {
    padding: 5px 10px;
    margin-right: 5px;
    cursor: pointer;
    border: none;
    border-radius: 4px;
}

#rules-table td button.run-button {
    background-color: #3498db; /* Blue */
    color: white;
}
#rules-table td button.run-button:hover { background-color: #2980b9; }

#rules-table td button.edit-button {
    background-color: #f39c12; /* Orange */
    color: white;
}
#rules-table td button.edit-button:hover { background-color: #e67e22; }


#rules-table td button.delete-button {
    background-color: #e74c3c; /* Red */
    color: white;
}
#rules-table td button.delete-button:hover { background-color: #c0392b; }


/* Styling for the modal background */
.modal-overlay {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background-color: rgba(0, 0, 0, 0.7); /* Semi-transparent black */
    display: flex;
    justify-content: center; /* Center horizontally */
    align-items: center;     /* Center vertically */
    z-index: 1000; /* Sit on top of other content */
}

/* Styling for the modal content */
.modal-content {
    background-color: #34495e;
    padding: 20px;
    border-radius: 8px;
    width: 90%;
    max-width: 700px; /* Increased max-width slightly */
    max-height: 80vh; /* Limit height to 80% of viewport height */
    overflow-y: auto; /* Add vertical scrolling if content exceeds max-height */
    color: #ecf0f1;
    box-shadow: 0 5px 15px rgba(0, 0, 0, 0.5);
    position: relative;
    display: flex; /* Use flexbox for potential inner layout if needed later */
    flex-direction: column;
}

/* Add some padding to the bottom to ensure content above the scrollbar is visible */
.modal-content form {
    padding-bottom: 20px;
}


.close-button {
    position: absolute;
    top: 10px;
    right: 10px;
    font-size: 1.5em;
    font-weight: bold;
    color: #ecf0f1;
    background: none;
    border: none;
    cursor: pointer;
}

.close-button:hover {
    color: #e74c3c; /* Red on hover */
}

/* Styles for the rule form within the modal */
#rule-form label {
    display: block;
    margin-bottom: 5px;
    font-weight: bold;
}

#rule-form input[type="text"],
#rule-form input[type="number"],
#rule-form select {
    /* Keep these full width when not in a condition row */
    width: calc(100% - 18px); /* Adjust for padding and border */
    padding: 8px;
    margin-bottom: 10px;
    box-sizing: border-box;
    background-color: #3b546d;
    border: 1px solid #4a627a;
    color: #ecf0f1;
    border-radius: 4px;
}

/* Apply button styles from the general section */
#rule-form button[type="submit"] {
    /* Already covered by the general button[type="submit"] rule */
}

#rule-form .add-condition-button,
#rule-form .remove-condition-button {
    padding: 8px 15px;
    margin-top: 10px;
    border: none;
    border-radius: 4px;
    cursor: pointer;
}

#rule-form .add-condition-button {
    background-color: #3498db; /* Blue */
    color: white;
    margin-right: 10px;
}
#rule-form .add-condition-button:hover { background-color: #2980b9; }

#rule-form .remove-condition-button {
    background-color: #e74c3c; /* Red */
    color: white;
}
#rule-form .remove-condition-button:hover { background-color: #c0392b; }


/* Styling for individual condition rows (top-level) */
.condition-row {
    background-color: #4a627a;
    padding: 10px;
    margin-bottom: 10px; /* Keep margin bottom for spacing */
    border-radius: 4px;
    display: flex; /* Use flexbox for inline elements in the row */
    align-items: center; /* Vertically align items */
    flex-wrap: wrap; /* Allow items to wrap if width is too small */
    gap: 10px; /* Add gap for spacing */
}

/* Styling for nested condition rows (within an OR group) */
.condition-row.nested-condition-row {
    background-color: #5a728a; /* Slightly different background for nested */
    border-left: 4px solid #3498db; /* Highlight nesting */
    margin-left: 20px; /* Indent nested rows */
    padding: 10px; /* Keep padding */
    margin-bottom: 10px; /* Keep margin */
    border-radius: 4px; /* Keep border radius */
    /* Flex properties inherited from .condition-row, adjust gap if needed */
     gap: 8px; /* Slightly smaller gap for nested */
}


/* Direct children styling - adjust margin/gap interaction */
/* Using gap on the parent .condition-row is better than margin-right on children */
/* Keep this only if needed for specific overrides */
/* .condition-row > * {
    margin-right: 10px;
    margin-bottom: 5px;
}
.condition-row > *:last-child {
    margin-right: 0;
} */


.condition-row .remove-condition-button {
     /* Ensure remove button doesn't take up too much space */
     flex-shrink: 0; /* Prevent shrinking */
     /* margin-right: 10px; Remove if using gap */
     margin-bottom: 0; /* Reset bottom margin for alignment */
}


.condition-row select,
.condition-row input[type="text"],
.condition-row input[type="number"] { /* Added number type here */
     width: auto; /* Allow elements to size based on content */
     flex-grow: 1; /* Allow these to grow to fill space */
     /* margin-right: 10px; Remove if using gap */
     margin-bottom: 0; /* Reset bottom margin for alignment */
     /* Remove the calc() width for elements inside condition rows */
     width: initial;
     /* Ensure inputs/selects within condition rows use the correct padding/border from the general rule-form rule */
     padding: 8px;
     box-sizing: border-box;
     background-color: #3b546d;
     border: 1px solid #4a627a;
     color: #ecf0f1;
     border-radius: 4px;
}

/* Ensure form elements don't go full width in condition rows */
.condition-row label {
    display: inline-block;
    /* margin-right: 5px; Remove if using gap */
    margin-bottom: 0; /* Reset bottom margin for alignment */
    flex-shrink: 0; /* Prevent label from shrinking */
}

/* Style for the area holding dynamic options */
.condition-row .options-area {
    display: flex; /* Use flexbox if multiple options elements need arrangement */
    align-items: center;
    flex-grow: 1; /* Allow the options area to take up available space */
    flex-wrap: wrap; /* Allow contents inside options area to wrap */
    gap: 8px; /* Add gap within options area */

    /* --- START Nice Change: Add some subtle styling to options area --- */
    background-color: #5a728a; /* Lighter than main row, darker than nested row - Adjusted from previous */
    padding: 8px; /* Add padding inside the options area */
    border-radius: 4px; /* Match border-radius */
    /* Add a subtle border */
    border: 1px solid #4a627a;
    /* --- END Nice Change --- */
}

/* Ensure the first element in the options area doesn't have left margin */
/* .condition-row .options-area > *:first-child {
    margin-left: 0;
} */

/* Ensure the last element in the options area doesn't have right margin */
/* .condition-row .options-area > *:last-child {
    margin-right: 0;
} */


/* Styling for the container holding conditions within an OR group */
.or-group-conditions-container {
    border: 1px dashed #4a627a; /* Dashed border around the OR group */
    padding: 15px;
    margin-top: 10px; /* Space above */
    margin-bottom: 10px; /* Space below */
    border-radius: 4px;
    width: calc(100% - 30px); /* Adjust width for padding */
    box-sizing: border-box;
    /* Display as block or flex-direction: column to stack nested condition rows */
    display: flex;
    flex-direction: column;
    /* Use gap for spacing between nested condition rows */
    gap: 10px; /* Gap between nested condition rows */

    /* Remove padding/margin from direct children .condition-row if using parent gap */
    .condition-row.nested-condition-row {
        margin: 0; /* Reset margin */
        padding: 10px; /* Keep internal padding */
        border-left: 4px solid #3498db; /* Keep highlight */
        /* Gap for elements *inside* nested row is handled by its own .condition-row gap */
    }
}


.loading-cursor {
    cursor: wait; /* Indicate waiting state */
}

{# --- START Modification 2: Styles for Flashed Messages --- #}
/* Styles for Flashed Messages */
#flashes-container {
    margin-bottom: 20px; /* Space below the messages */
}

.flash-message {
    padding: 10px;
    margin-bottom: 10px;
    border-radius: 4px;
    font-weight: bold;
}

.flash-success {
    background-color: #2ecc71; /* Green */
    color: white;
    border-left: 4px solid #27ae60; /* Darker green border */
}

.flash-error {
    background-color: #e74c3c; /* Red */
    color: white;
    border-left: 4px solid #c0392b; /* Darker red border */
}

.flash-info { /* Optional: Add styling for info messages */
    background-color: #3498db; /* Blue */
    color: white;
    border-left: 4px solid #2980b9; /* Darker blue border */
}
{# --- END Modification 2 --- #}


/* --- START Additions for Filetype UI in style.css --- */

/* Container for the filetype options (checkboxes/submenus) */
.filetype-options-container {
    background-color: #3b546d; /* Match input background */
    padding: 10px;
    border-radius: 4px;
    border: 1px solid #4a627a; /* Match input border */
    margin-top: 10px; /* Space from operator select */
    width: 100%; /* Allow it to take full width within options-area */
    box-sizing: border-box;
    /* Remove padding/gap inherited from options-area if needed */
    /* padding: 0; */
    /* gap: 0; */
}

/* Row for each filetype category */
.filetype-category-row {
    margin-bottom: 5px;
    padding-bottom: 5px;
    border-bottom: 1px dashed #4a627a; /* Subtle separator */
}

.filetype-category-row:last-child {
    border-bottom: none; /* No separator for the last category */
    margin-bottom: 0;
    padding-bottom: 0;
}

/* Header for the category row (checkbox, label, toggle button) */
.filetype-category-header {
    display: flex;
    align-items: center;
    cursor: pointer; /* Indicate clickable area for header */
    padding: 5px 0; /* Add padding for click area */
}

/* Style for the category checkbox and label within the flex container */
.filetype-category-header input[type="checkbox"] {
    flex-shrink: 0; /* Prevent checkbox from shrinking */
    margin-right: 5px;
    width: auto; /* Reset width */
}

.filetype-category-header label {
    flex-grow: 1; /* Allow label to take up space */
    margin: 0; /* Reset default label margins */
    font-weight: bold; /* Make category labels bold */
    cursor: pointer; /* Maintain pointer cursor on label */
}

/* Style for the toggle button (arrow) */
.filetype-toggle-extensions {
    margin-left: auto; /* Push to the right */
    background: none;
    border: none;
    color: inherit; /* Use parent color */
    cursor: pointer;
    font-size: 0.9em;
    padding: 0 5px;
    transition: transform 0.2s ease; /* Smooth rotation */
}

/* Rotate the arrow when the extensions container is shown */
/* This requires JS to add a class or check display state.
   Alternatively, toggle the text content as implemented in JS.
   If you want rotation, JS would need to add/remove a class like 'expanded'. */
/* .filetype-category-header.expanded .filetype-toggle-extensions {
     transform: rotate(180deg);
} */


/* Container for extensions within a category (submenu) */
.filetype-extensions-container {
    /* display controlled by JS */
    padding-left: 20px; /* Indent extensions */
    margin-top: 5px;
     display: none; /* Ensure it's hidden by default CSS */
}

/* Row for each individual extension */
.filetype-extension-row {
    margin-bottom: 3px;
    display: flex; /* Align checkbox and label */
    align-items: center;
}

/* Style for the extension checkbox and label */
.filetype-extension-row input[type="checkbox"] {
    flex-shrink: 0;
    margin-right: 5px;
     width: auto; /* Reset width */
}

.filetype-extension-row label {
    margin: 0; /* Reset default label margins */
    font-weight: normal; /* Extensions labels are not bold */
}