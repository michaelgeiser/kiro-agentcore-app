/**
 * Environment Variables Lightbox — View module.
 * Renders a modal dialog for viewing and editing runtime environment variables.
 *
 * Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9,
 *              5.1, 5.2, 5.3, 5.4, 5.5, 6.1, 6.5, 6.6
 */

import { adminApi } from '../admin-api.js';

/**
 * Model options list — hardcoded current Amazon Nova and Anthropic Claude models.
 * Each entry: { displayName: string, modelId: string }
 * @type {Array<{displayName: string, modelId: string}>}
 */
export const MODEL_OPTIONS = [
  // Amazon Nova models (current generation)
  { displayName: 'Amazon Nova Premier (US CRI)', modelId: 'us.amazon.nova-premier-v1:0' },
  { displayName: 'Amazon Nova Pro (US CRI)', modelId: 'us.amazon.nova-pro-v1:0' },
  { displayName: 'Amazon Nova Pro (Single Region)', modelId: 'amazon.nova-pro-v1:0' },
  { displayName: 'Amazon Nova Lite (US CRI)', modelId: 'us.amazon.nova-lite-v1:0' },
  { displayName: 'Amazon Nova Lite (Single Region)', modelId: 'amazon.nova-lite-v1:0' },
  { displayName: 'Amazon Nova Micro (US CRI)', modelId: 'us.amazon.nova-micro-v1:0' },
  { displayName: 'Amazon Nova Micro (Single Region)', modelId: 'amazon.nova-micro-v1:0' },
  // Anthropic Claude models (current generation)
  { displayName: 'Claude Sonnet 4.6 (US CRI)', modelId: 'us.anthropic.claude-sonnet-4-6' },
  { displayName: 'Claude Sonnet 4.6 (Single Region)', modelId: 'anthropic.claude-sonnet-4-6' },
  { displayName: 'Claude Sonnet 4.5 (US CRI)', modelId: 'us.anthropic.claude-sonnet-4-5-20250514-v1:0' },
  { displayName: 'Claude Sonnet 4.5 (Single Region)', modelId: 'anthropic.claude-sonnet-4-5-20250514-v1:0' },
  { displayName: 'Claude Sonnet 4 (US CRI)', modelId: 'us.anthropic.claude-sonnet-4-20250514-v1:0' },
  { displayName: 'Claude Sonnet 4 (Single Region)', modelId: 'anthropic.claude-sonnet-4-20250514-v1:0' },
  { displayName: 'Claude Haiku 4.5 (US CRI)', modelId: 'us.anthropic.claude-haiku-4-5-20250514-v1:0' },
  { displayName: 'Claude Haiku 4.5 (Single Region)', modelId: 'anthropic.claude-haiku-4-5-20250514-v1:0' },
  { displayName: 'Claude Opus 4.6 (US CRI)', modelId: 'us.anthropic.claude-opus-4-6' },
  { displayName: 'Claude Opus 4.6 (Single Region)', modelId: 'anthropic.claude-opus-4-6' },
  { displayName: 'Claude Opus 4.7 (US CRI)', modelId: 'us.anthropic.claude-opus-4-7' },
  { displayName: 'Claude Opus 4.7 (Single Region)', modelId: 'anthropic.claude-opus-4-7' },
  { displayName: 'Claude Opus 4.8 (US CRI)', modelId: 'us.anthropic.claude-opus-4-8' },
  { displayName: 'Claude Opus 4.8 (Single Region)', modelId: 'anthropic.claude-opus-4-8' },
  { displayName: 'Claude Sonnet 5 (US CRI)', modelId: 'us.anthropic.claude-sonnet-5' },
  { displayName: 'Claude Sonnet 5 (Single Region)', modelId: 'anthropic.claude-sonnet-5' },
];

/**
 * MAX_CONCURRENT_EVALUATIONS dropdown options.
 * @type {number[]}
 */
export const CONCURRENCY_OPTIONS = [1, 2, 3, 5, 10];

/**
 * Open the environment variables lightbox.
 * Fetches current values from API, renders controls, handles cancel.
 * @returns {void}
 */
export function openEnvVarsLightbox() {
  // Create the overlay
  const overlay = document.createElement('div');
  overlay.className = 'lightbox-overlay';
  overlay.setAttribute('role', 'dialog');
  overlay.setAttribute('aria-modal', 'true');
  overlay.setAttribute('aria-labelledby', 'env-vars-lightbox-title');

  // Create the modal
  const modal = document.createElement('div');
  modal.className = 'lightbox-modal';

  // Header
  const header = document.createElement('div');
  header.className = 'lightbox-modal__header';

  const title = document.createElement('h2');
  title.className = 'lightbox-modal__title';
  title.id = 'env-vars-lightbox-title';
  title.textContent = 'Environment Variables';

  const closeBtn = document.createElement('button');
  closeBtn.className = 'lightbox-modal__close';
  closeBtn.setAttribute('aria-label', 'Close');
  closeBtn.textContent = '\u00D7';
  closeBtn.addEventListener('click', () => closeLightbox(overlay));

  header.appendChild(title);
  header.appendChild(closeBtn);

  // Body (scrollable)
  const body = document.createElement('div');
  body.className = 'lightbox-modal__body';
  body.textContent = 'Loading...';

  // Footer
  const footer = document.createElement('div');
  footer.className = 'lightbox-modal__footer';

  const cancelBtn = document.createElement('button');
  cancelBtn.className = 'admin-btn admin-btn--secondary';
  cancelBtn.textContent = 'Cancel';
  cancelBtn.addEventListener('click', () => closeLightbox(overlay));

  const saveBtn = document.createElement('button');
  saveBtn.className = 'admin-btn admin-btn--primary';
  saveBtn.textContent = 'Save Changes';
  saveBtn.disabled = true; // Disabled initially — nothing changed yet

  footer.appendChild(cancelBtn);
  footer.appendChild(saveBtn);

  // Assemble modal
  modal.appendChild(header);
  modal.appendChild(body);
  modal.appendChild(footer);
  overlay.appendChild(modal);

  // Append to document
  document.body.appendChild(overlay);

  // Change tracking state: Set of variable names that have been modified
  const changedVars = new Set();

  // Fetch variables and render
  adminApi
    .getEnvironmentVariables()
    .then((variables) => {
      renderVariables(body, variables);
      attachChangeListeners(body, changedVars, saveBtn);
      updateSaveButtonState(body, changedVars, saveBtn);
    })
    .catch((error) => {
      body.textContent = '';
      const errorMsg = document.createElement('div');
      errorMsg.className = 'admin-message admin-message--error';
      errorMsg.textContent = `Failed to load environment variables: ${error.message || 'Unknown error'}`;
      body.appendChild(errorMsg);
    });

  // Wire up Save button
  saveBtn.addEventListener('click', () => {
    handleSave(body, changedVars, saveBtn, overlay);
  });
}

/**
 * Close and remove the lightbox overlay from the DOM.
 * @param {HTMLElement} overlay - The overlay element to remove
 */
function closeLightbox(overlay) {
  overlay.remove();
}

/**
 * Render all environment variables into the lightbox body.
 * @param {HTMLElement} body - The lightbox body container
 * @param {Array<{name: string, value: string, description: string, inputType: string}>} variables
 */
function renderVariables(body, variables) {
  body.textContent = '';

  for (const variable of variables) {
    const group = document.createElement('div');
    group.className = 'admin-form-group';

    const label = document.createElement('label');
    label.className = 'admin-form-group__label';
    label.textContent = variable.name;

    const description = document.createElement('p');
    description.className = 'admin-form-group__description';
    description.textContent = variable.description;

    const control = createControl(variable);

    group.appendChild(label);
    group.appendChild(description);
    group.appendChild(control);
    body.appendChild(group);
  }
}

/**
 * Create the appropriate input control based on the variable's inputType.
 * @param {{name: string, value: string, description: string, inputType: string}} variable
 * @returns {HTMLElement} The input or select element
 */
function createControl(variable) {
  switch (variable.inputType) {
    case 'model-dropdown':
      return createModelDropdown(variable);
    case 'concurrency-dropdown':
      return createConcurrencyDropdown(variable);
    default:
      return createTextInput(variable);
  }
}

/**
 * Create a <select> dropdown populated with MODEL_OPTIONS.
 * Pre-selects the option matching current value, or shows a placeholder if invalid/legacy.
 * @param {{name: string, value: string}} variable
 * @returns {HTMLSelectElement}
 */
function createModelDropdown(variable) {
  const select = document.createElement('select');
  select.className = 'admin-form-group__select';
  select.name = variable.name;
  select.setAttribute('data-original-value', variable.value);

  const isValidValue = MODEL_OPTIONS.some((opt) => opt.modelId === variable.value);

  if (!isValidValue) {
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = '-- Select a model (current value is invalid/legacy) --';
    placeholder.disabled = true;
    placeholder.selected = true;
    select.appendChild(placeholder);
  }

  for (const option of MODEL_OPTIONS) {
    const opt = document.createElement('option');
    opt.value = option.modelId;
    opt.textContent = option.displayName;
    if (option.modelId === variable.value) {
      opt.selected = true;
    }
    select.appendChild(opt);
  }

  return select;
}

/**
 * Create a <select> dropdown populated with CONCURRENCY_OPTIONS.
 * Pre-selects the option matching current value, or shows a placeholder if invalid.
 * @param {{name: string, value: string}} variable
 * @returns {HTMLSelectElement}
 */
function createConcurrencyDropdown(variable) {
  const select = document.createElement('select');
  select.className = 'admin-form-group__select';
  select.name = variable.name;
  select.setAttribute('data-original-value', variable.value);

  const currentNum = Number(variable.value);
  const isValidValue = CONCURRENCY_OPTIONS.includes(currentNum);

  if (!isValidValue) {
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = '-- Select concurrency (current value is invalid) --';
    placeholder.disabled = true;
    placeholder.selected = true;
    select.appendChild(placeholder);
  }

  for (const num of CONCURRENCY_OPTIONS) {
    const opt = document.createElement('option');
    opt.value = String(num);
    opt.textContent = String(num);
    if (num === currentNum) {
      opt.selected = true;
    }
    select.appendChild(opt);
  }

  return select;
}

/**
 * Create a text input for variables that don't use a dropdown.
 * @param {{name: string, value: string}} variable
 * @returns {HTMLInputElement}
 */
function createTextInput(variable) {
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'admin-form-group__input';
  input.name = variable.name;
  input.value = variable.value;
  input.setAttribute('data-original-value', variable.value);
  return input;
}


/**
 * Attach change event listeners to all input controls within the lightbox body.
 * On each change, compares current value to the original value (stored in data-original-value)
 * and updates the Changed_Flag set and visual indication accordingly.
 *
 * @param {HTMLElement} body - The lightbox body container
 * @param {Set<string>} changedVars - Set of changed variable names
 * @param {HTMLButtonElement} saveBtn - The Save Changes button
 */
function attachChangeListeners(body, changedVars, saveBtn) {
  const controls = body.querySelectorAll('input, select');
  for (const control of controls) {
    control.addEventListener('change', () => {
      onControlChange(control, changedVars);
      updateSaveButtonState(body, changedVars, saveBtn);
    });
    // Also listen on 'input' for text inputs for real-time tracking
    if (control.tagName === 'INPUT') {
      control.addEventListener('input', () => {
        onControlChange(control, changedVars);
        updateSaveButtonState(body, changedVars, saveBtn);
      });
    }
  }
}

/**
 * Handle a control's value change: compare to original, update Changed_Flag set and CSS class.
 *
 * @param {HTMLInputElement|HTMLSelectElement} control - The input or select element
 * @param {Set<string>} changedVars - Set of changed variable names
 */
function onControlChange(control, changedVars) {
  const originalValue = control.getAttribute('data-original-value');
  const currentValue = control.value;
  const varName = control.name;
  const formGroup = control.closest('.admin-form-group');

  if (currentValue !== originalValue) {
    changedVars.add(varName);
    if (formGroup) {
      formGroup.classList.add('admin-form-group--changed');
    }
  } else {
    changedVars.delete(varName);
    if (formGroup) {
      formGroup.classList.remove('admin-form-group--changed');
    }
  }
}

/**
 * Update the Save Changes button disabled state.
 * Disabled when:
 * - No variables have been changed (nothing to save), OR
 * - Any model dropdown has an empty/placeholder value selected
 *
 * @param {HTMLElement} body - The lightbox body container
 * @param {Set<string>} changedVars - Set of changed variable names
 * @param {HTMLButtonElement} saveBtn - The Save Changes button
 */
function updateSaveButtonState(body, changedVars, saveBtn) {
  // Disable if nothing changed
  if (changedVars.size === 0) {
    saveBtn.disabled = true;
    return;
  }

  // Disable if any model dropdown has empty/placeholder value
  const selects = body.querySelectorAll('select');
  for (const select of selects) {
    if (select.value === '') {
      saveBtn.disabled = true;
      return;
    }
  }

  saveBtn.disabled = false;
}

/**
 * Handle the Save Changes button click.
 * Constructs payload with only changed variables, calls updateEnvironmentVariables API.
 * On success: shows success message briefly, then closes lightbox.
 * On failure: shows error message, keeps lightbox open for retry.
 *
 * @param {HTMLElement} body - The lightbox body container
 * @param {Set<string>} changedVars - Set of changed variable names
 * @param {HTMLButtonElement} saveBtn - The Save Changes button
 * @param {HTMLElement} overlay - The lightbox overlay element
 */
async function handleSave(body, changedVars, saveBtn, overlay) {
  // Construct payload with only changed variables
  const payload = {};
  for (const varName of changedVars) {
    const control = body.querySelector(`[name="${varName}"]`);
    if (control) {
      payload[varName] = control.value;
    }
  }

  // Disable save button during request to prevent double-submission
  saveBtn.disabled = true;
  saveBtn.textContent = 'Saving...';

  // Remove any previous messages
  const previousMsg = body.querySelector('.admin-message');
  if (previousMsg) {
    previousMsg.remove();
  }

  try {
    await adminApi.updateEnvironmentVariables(payload);

    // Show success message briefly, then close
    const successMsg = document.createElement('div');
    successMsg.className = 'admin-message admin-message--success';
    successMsg.textContent =
      'Configuration saved. ECS service redeployment triggered — new tasks will use updated values within minutes.';
    body.insertBefore(successMsg, body.firstChild);

    setTimeout(() => {
      closeLightbox(overlay);
    }, 1500);
  } catch (error) {
    // Show error message, keep lightbox open for retry
    const errorMsg = document.createElement('div');
    errorMsg.className = 'admin-message admin-message--error';
    errorMsg.textContent = `Failed to save changes: ${error.message || 'Unknown error'}`;
    body.insertBefore(errorMsg, body.firstChild);

    // Re-enable save button for retry
    saveBtn.disabled = false;
    saveBtn.textContent = 'Save Changes';
  }
}
