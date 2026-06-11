/**
 * Application entry point.
 * Initializes authentication, routing, and global event handlers.
 *
 * Requirements: 1.3, 2.1, 2.5, 10.7
 */

import { Router } from './router.js';
import { auth } from './auth.js';
import { render as renderUpload } from './views/upload.js';
import { render as renderList } from './views/list.js';
import { showToast } from './utils/dom.js';

/**
 * Initialize the application.
 * Handles Cognito callback, authentication check, and router setup.
 */
async function init() {
  // 1. Check URL for authorization code (Cognito callback)
  const urlParams = new URLSearchParams(window.location.search);
  const code = urlParams.get('code');

  if (code) {
    try {
      await auth.handleCallback(code);
    } catch (error) {
      showToast('Login failed. Please try again.', 'error');
      // Clear the code from URL to prevent retry loop
      const cleanUrl = window.location.origin + window.location.pathname;
      window.history.replaceState({}, document.title, cleanUrl);
      // Don't call auth.login() here — let the user click to retry
      // Otherwise we get an infinite redirect loop with Cognito
      return;
    }

    // Remove the authorization code from URL to keep it clean
    const cleanUrl = window.location.origin + window.location.pathname + window.location.hash;
    window.history.replaceState({}, document.title, cleanUrl);
  }

  // 2. Check authentication state
  if (!auth.isAuthenticated()) {
    // Redirect to Cognito login
    auth.login();
    return;
  }

  // 3. Authenticated — initialize router
  const outlet = document.getElementById('app-outlet');
  const router = new Router(
    { upload: renderUpload, list: renderList },
    outlet
  );
  router.start();

  // 4. Wire logout button
  const logoutBtn = document.getElementById('logout-btn');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', () => {
      auth.logout();
    });
  }

  // 5. Wire hamburger menu toggle for mobile navigation
  const navToggle = document.querySelector('.nav-toggle');
  const navLinks = document.querySelector('.nav-links');

  if (navToggle && navLinks) {
    navToggle.addEventListener('click', () => {
      const isOpen = navLinks.classList.toggle('open');
      navToggle.setAttribute('aria-expanded', String(isOpen));
    });
  }
}

// 6. Global unhandled promise rejection handler
window.addEventListener('unhandledrejection', (event) => {
  const message = event.reason?.message || 'An unexpected error occurred.';
  showToast(message, 'error');
});

// Start the app when DOM is ready
init();
