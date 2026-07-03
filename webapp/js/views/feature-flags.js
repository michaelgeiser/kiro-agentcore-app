/**
 * Feature Flags administration page.
 * Displays all feature flags with iOS-style toggle switches for administrators.
 * Each toggle immediately persists changes via the admin API.
 *
 * Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8
 */

import { adminApi } from '../admin-api.js';

/**
 * Show an admin-themed toast notification on the page.
 * Creates a temporary message element, appends it to the page container,
 * and auto-removes after 3 seconds.
 *
 * @param {HTMLElement} container - The page container to append the toast to
 * @param {string} message - The message text to display
 * @param {'success'|'error'} type - Toast variant
 */
function showAdminToast(container, message, type) {
  const toast = document.createElement('div');
  toast.className = `admin-message admin-message--${type}`;
  toast.setAttribute('role', 'alert');
  toast.setAttribute('aria-live', 'assertive');
  toast.textContent = message;

  // Insert toast at the top of the container (after the header)
  const header = container.querySelector('.admin-page-header');
  if (header && header.nextSibling) {
    container.insertBefore(toast, header.nextSibling);
  } else {
    container.appendChild(toast);
  }

  setTimeout(() => {
    if (toast.parentNode) {
      toast.parentNode.removeChild(toast);
    }
  }, 3000);
}

/**
 * Create an iOS-style toggle switch element for a feature flag.
 *
 * @param {{name: string, enabled: boolean, description: string}} flag - The feature flag data
 * @param {HTMLElement} pageContainer - The page container for toast notifications
 * @returns {HTMLElement} The toggle switch label element
 */
function createToggleSwitch(flag, pageContainer) {
  const wrapper = document.createElement('label');
  wrapper.className = `toggle-switch${flag.enabled ? ' toggle-switch--on' : ''}`;

  // Hidden checkbox for accessibility
  const input = document.createElement('input');
  input.type = 'checkbox';
  input.className = 'toggle-switch__input';
  input.checked = flag.enabled;
  input.setAttribute('aria-label', `Toggle ${flag.name}`);

  // Visual track
  const track = document.createElement('span');
  track.className = 'toggle-switch__track';

  // On/Off text labels
  const labelOn = document.createElement('span');
  labelOn.className = 'toggle-switch__label-on';
  labelOn.textContent = 'On';

  const labelOff = document.createElement('span');
  labelOff.className = 'toggle-switch__label-off';
  labelOff.textContent = 'Off';

  wrapper.appendChild(input);
  wrapper.appendChild(track);
  wrapper.appendChild(labelOn);
  wrapper.appendChild(labelOff);

  // Toggle handler
  input.addEventListener('change', async () => {
    const newState = input.checked;
    const previousState = !newState;

    // Optimistically update visual state
    if (newState) {
      wrapper.classList.add('toggle-switch--on');
    } else {
      wrapper.classList.remove('toggle-switch--on');
    }

    // Disable toggle during API call
    wrapper.classList.add('toggle-switch--disabled');
    input.disabled = true;

    try {
      await adminApi.updateFeatureFlag(flag.name, newState);
      const stateLabel = newState ? 'On' : 'Off';
      showAdminToast(pageContainer, `Flag ${flag.name} updated to ${stateLabel}`, 'success');
    } catch (error) {
      // Revert toggle to previous state on failure
      input.checked = previousState;
      if (previousState) {
        wrapper.classList.add('toggle-switch--on');
      } else {
        wrapper.classList.remove('toggle-switch--on');
      }
      const errorMessage = error.message || 'Unknown error';
      showAdminToast(pageContainer, `Failed to update ${flag.name}: ${errorMessage}`, 'error');
    } finally {
      // Re-enable toggle
      wrapper.classList.remove('toggle-switch--disabled');
      input.disabled = false;
    }
  });

  return wrapper;
}

/**
 * Render a single feature flag item card.
 *
 * @param {{name: string, enabled: boolean, description: string}} flag - The feature flag data
 * @param {HTMLElement} pageContainer - The page container for toast notifications
 * @returns {HTMLElement} The flag item element
 */
function renderFlagItem(flag, pageContainer) {
  const item = document.createElement('div');
  item.className = 'feature-flag-item';

  // Info section
  const info = document.createElement('div');
  info.className = 'feature-flag-item__info';

  const name = document.createElement('p');
  name.className = 'feature-flag-item__name';
  name.textContent = flag.name;

  const description = document.createElement('p');
  description.className = 'feature-flag-item__description';
  description.textContent = flag.description;

  info.appendChild(name);
  info.appendChild(description);

  // Control section
  const control = document.createElement('div');
  control.className = 'feature-flag-item__control';

  const toggle = createToggleSwitch(flag, pageContainer);
  control.appendChild(toggle);

  item.appendChild(info);
  item.appendChild(control);

  return item;
}

/**
 * Render the Feature Flags administration page.
 * Fetches all flags from the admin API and displays them with toggle switches.
 *
 * @param {HTMLElement} outlet - The router outlet element
 * @returns {void}
 */
export function render(outlet) {
  outlet.innerHTML = '';

  // Admin page wrapper
  const page = document.createElement('div');
  page.className = 'admin-page';

  // Admin context bar
  const contextBar = document.createElement('div');
  contextBar.className = 'admin-context-bar';
  contextBar.innerHTML = '<span class="admin-context-bar__icon"></span> Administration Mode';

  // Page header
  const header = document.createElement('div');
  header.className = 'admin-page-header';

  const title = document.createElement('h1');
  title.className = 'admin-page-header__title';
  title.textContent = 'Feature Flags';

  const badge = document.createElement('span');
  badge.className = 'admin-page-header__badge';
  badge.textContent = 'Admin';

  header.appendChild(title);
  header.appendChild(badge);

  // Content area (will hold the flags list or loading/error state)
  const content = document.createElement('div');
  content.style.padding = 'var(--spacing-lg)';

  // Loading state
  content.textContent = 'Loading feature flags...';

  page.appendChild(contextBar);
  page.appendChild(header);
  page.appendChild(content);
  outlet.appendChild(page);

  // Fetch and render flags
  adminApi
    .getFeatureFlags()
    .then((flags) => {
      content.textContent = '';

      const flagsList = document.createElement('div');
      flagsList.className = 'feature-flags-list';

      for (const flag of flags) {
        const flagItem = renderFlagItem(flag, page);
        flagsList.appendChild(flagItem);
      }

      content.appendChild(flagsList);
    })
    .catch((error) => {
      content.textContent = '';
      const errorMsg = document.createElement('div');
      errorMsg.className = 'admin-message admin-message--error';
      errorMsg.textContent = `Failed to load feature flags: ${error.message || 'Unknown error'}`;
      content.appendChild(errorMsg);
    });
}
