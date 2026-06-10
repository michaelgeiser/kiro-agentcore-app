/**
 * DOM helper utilities for the Presentation Coaching Platform SPA.
 * Provides element creation, file size formatting, and toast notifications.
 */

/**
 * Create a DOM element with attributes and children.
 * @param {string} tag - HTML tag name
 * @param {Object} [attributes={}] - Key/value pairs for element attributes.
 *   Special keys: 'className' sets class, 'textContent' sets text, 'innerHTML' sets HTML,
 *   keys starting with 'on' are added as event listeners (e.g., 'onClick' → 'click').
 * @param {Array<HTMLElement|string>} [children=[]] - Child elements or text strings to append
 * @returns {HTMLElement}
 */
export function createElement(tag, attributes = {}, children = []) {
  const el = document.createElement(tag);

  for (const [key, value] of Object.entries(attributes)) {
    if (key === 'className') {
      el.className = value;
    } else if (key === 'textContent') {
      el.textContent = value;
    } else if (key === 'innerHTML') {
      el.innerHTML = value;
    } else if (key.startsWith('on') && typeof value === 'function') {
      const event = key.slice(2).toLowerCase();
      el.addEventListener(event, value);
    } else if (value !== null && value !== undefined && value !== false) {
      el.setAttribute(key, value);
    }
  }

  for (const child of children) {
    if (typeof child === 'string') {
      el.appendChild(document.createTextNode(child));
    } else if (child instanceof Node) {
      el.appendChild(child);
    }
  }

  return el;
}

/**
 * Set multiple attributes on an existing element.
 * @param {HTMLElement} el - Target element
 * @param {Object} attributes - Key/value pairs for attributes
 */
export function setAttributes(el, attributes) {
  for (const [key, value] of Object.entries(attributes)) {
    if (value === null || value === undefined || value === false) {
      el.removeAttribute(key);
    } else {
      el.setAttribute(key, value);
    }
  }
}

/**
 * Remove all child nodes from an element.
 * @param {HTMLElement} el - Target element
 */
export function clearChildren(el) {
  while (el.firstChild) {
    el.removeChild(el.firstChild);
  }
}

/**
 * Format a file size in bytes to a human-readable string.
 * Uses binary units: KB (1024), MB (1024²), GB (1024³).
 * @param {number} bytes - File size in bytes
 * @returns {string} Human-readable file size (e.g., "1.5 MB", "256 KB")
 */
export function formatFileSize(bytes) {
  if (bytes === 0) return '0 Bytes';

  const units = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
  const k = 1024;
  const i = Math.floor(Math.log(Math.abs(bytes)) / Math.log(k));
  const unitIndex = Math.min(i, units.length - 1);

  if (unitIndex === 0) {
    return `${bytes} Bytes`;
  }

  const size = bytes / Math.pow(k, unitIndex);
  // Use up to 2 decimal places, but strip trailing zeros
  const formatted = size.toFixed(2).replace(/\.?0+$/, '');
  return `${formatted} ${units[unitIndex]}`;
}

/**
 * Show a toast notification message.
 * Uses CSS classes defined in components.css: .toast, .toast--error, .toast--success, .toast--info, .toast__close
 * @param {string} message - The message to display
 * @param {'error'|'success'|'info'} [type='info'] - Toast variant
 * @param {number} [duration=5000] - Auto-dismiss time in milliseconds (0 to disable)
 * @returns {HTMLElement} The toast element (useful for testing)
 */
export function showToast(message, type = 'info', duration = 5000) {
  const toast = createElement('div', {
    className: `toast toast--${type}`,
    role: 'alert',
    'aria-live': 'assertive',
  });

  const messageEl = createElement('span', { textContent: message });

  const closeBtn = createElement('button', {
    className: 'toast__close',
    'aria-label': 'Close notification',
    textContent: '×',
    onClick: () => dismissToast(toast),
  });

  toast.appendChild(messageEl);
  toast.appendChild(closeBtn);
  document.body.appendChild(toast);

  if (duration > 0) {
    setTimeout(() => dismissToast(toast), duration);
  }

  return toast;
}

/**
 * Dismiss and remove a toast element from the DOM.
 * @param {HTMLElement} toast - The toast element to remove
 */
function dismissToast(toast) {
  if (toast && toast.parentNode) {
    toast.parentNode.removeChild(toast);
  }
}
