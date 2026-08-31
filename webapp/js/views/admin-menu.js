/**
 * Admin Hover Menu — Renders the "Administration" dropdown in the navigation bar.
 *
 * Displays a red bold "Administration" trigger label. On hover, shows a dropdown
 * with "Environment Variables" and "Feature Flags" links. Implements a 300ms
 * hide delay on mouse-out to allow cursor travel to menu items.
 *
 * Requirements: 1.1, 1.2, 1.3, 1.4, 1.5
 */

import { createElement } from '../utils/dom.js';

/** @type {number|null} */
let _hideTimeout = null;

/**
 * Render the admin hover menu into the navigation container.
 * Only call this when `isAdmin()` returns true — the caller is responsible
 * for checking admin status before invoking this function.
 *
 * @param {HTMLElement} navContainer - The navigation links container
 * @returns {void}
 */
export function renderAdminMenu(navContainer) {
  // 1. Create the admin menu container
  const menuContainer = createElement('div', { className: 'admin-menu' });

  // 2. Create the trigger button
  const trigger = createElement('button', {
    className: 'admin-menu__trigger',
    textContent: 'Administration',
    'aria-haspopup': 'true',
    'aria-expanded': 'false',
  });

  // 3. Create the dropdown
  const dropdown = createElement('div', {
    className: 'admin-menu__dropdown',
    role: 'menu',
    'aria-label': 'Administration menu',
  });

  // 4. Add menu items
  const envVarsItem = createElement('a', {
    className: 'admin-menu__item',
    textContent: 'Environment Variables',
    href: '#env-vars',
    role: 'menuitem',
    onClick: () => {
      _hideDropdown(dropdown, trigger);
    },
  });

  const featureFlagsItem = createElement('a', {
    className: 'admin-menu__item',
    textContent: 'Feature Flags',
    href: '#feature-flags',
    role: 'menuitem',
    onClick: () => {
      _hideDropdown(dropdown, trigger);
    },
  });

  dropdown.appendChild(envVarsItem);
  dropdown.appendChild(featureFlagsItem);

  // 5. Mouse enter: show dropdown, cancel any pending hide
  menuContainer.addEventListener('mouseenter', () => {
    _cancelHideTimeout();
    _showDropdown(dropdown, trigger);
  });

  // 6. Mouse leave: set 300ms delay before hiding
  menuContainer.addEventListener('mouseleave', () => {
    _hideTimeout = setTimeout(() => {
      _hideDropdown(dropdown, trigger);
    }, 300);
  });

  // Assemble and append
  menuContainer.appendChild(trigger);
  menuContainer.appendChild(dropdown);

  // Wrap in <li> since navContainer is a <ul>
  const listItem = document.createElement('li');
  listItem.appendChild(menuContainer);
  navContainer.insertBefore(listItem, navContainer.firstChild);
}

/**
 * Show the dropdown menu.
 * @param {HTMLElement} dropdown
 * @param {HTMLElement} trigger
 */
function _showDropdown(dropdown, trigger) {
  dropdown.classList.add('admin-menu__dropdown--visible');
  trigger.setAttribute('aria-expanded', 'true');
}

/**
 * Hide the dropdown menu.
 * @param {HTMLElement} dropdown
 * @param {HTMLElement} trigger
 */
function _hideDropdown(dropdown, trigger) {
  dropdown.classList.remove('admin-menu__dropdown--visible');
  trigger.setAttribute('aria-expanded', 'false');
}

/**
 * Cancel any pending hide timeout.
 */
function _cancelHideTimeout() {
  if (_hideTimeout !== null) {
    clearTimeout(_hideTimeout);
    _hideTimeout = null;
  }
}
