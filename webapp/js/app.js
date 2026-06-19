/**
 * Application entry point.
 * Initializes authentication, routing, and global event handlers.
 *
 * Requirements: 1.3, 2.1, 2.5, 10.7
 */

import { Router } from './router.js';
import { auth, isAdmin } from './auth.js';
import { render as renderUpload } from './views/upload.js';
import { render as renderList } from './views/list.js';
import { showToast } from './utils/dom.js';

/**
 * Render the landing/home page into the outlet.
 * @param {HTMLElement} outlet
 */
function renderHome(outlet) {
  outlet.innerHTML = `
    <div style="text-align: center; padding-top: 20px;">
      <img src="assets/heroAI-PC.png" alt="AI Presentation Coaching" style="max-width: 50%; height: auto;">
      <h2 style="margin-top: 24px;">AI-Powered Presentation Coaching</h2>
      <p style="max-width: 600px; margin: 12px auto; color: #555;">Upload your presentation audio and receive detailed feedback across 7 dimensions: delivery, structure, executive presence, technical communication, audience engagement, pacing, and persuasion.</p>
    </div>
  `;
}

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
    // Show landing page content (already in HTML)
    // Hide only the Logout button — keep Upload and Submissions visible
    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) logoutBtn.parentElement.style.display = 'none';

    // Wire the Sign In button
    const loginBtn = document.getElementById('landing-login-btn');
    if (loginBtn) {
      loginBtn.addEventListener('click', () => {
        auth.login();
      });
    }

    // Wire the brand link to just scroll to top
    const brandLink = document.querySelector('.nav-brand');
    if (brandLink) {
      brandLink.addEventListener('click', (e) => {
        e.preventDefault();
        window.scrollTo(0, 0);
      });
    }

    // Wire protected nav links to redirect to login
    document.querySelectorAll('#nav-links a[href="#upload"], #nav-links a[href="#list"]').forEach(link => {
      link.addEventListener('click', (e) => {
        e.preventDefault();
        auth.login();
      });
    });

    return;
  }

  // 3. Authenticated — hide landing page, show app
  const landingPage = document.getElementById('landing-page');
  if (landingPage) landingPage.remove();

  // Show logout button
  const logoutBtn2 = document.getElementById('logout-btn');
  if (logoutBtn2) logoutBtn2.parentElement.style.display = '';

  const outlet = document.getElementById('app-outlet');
  const router = new Router(
    { upload: renderUpload, list: renderList, home: renderHome },
    outlet
  );
  router.start();

  // 3.5. Show Administrator label if user is in the administrators group
  if (isAdmin()) {
    const navLinks = document.querySelector('.nav-links');
    if (navLinks) {
      const adminLabel = document.createElement('li');
      adminLabel.innerHTML = '<span style="color: red; font-weight: bold;">Administrator</span>';
      navLinks.insertBefore(adminLabel, navLinks.firstChild);
    }
  }

  // 4. Wire logout button
  const logoutBtn = document.getElementById('logout-btn');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', () => {
      auth.logout();
    });
  }

  // 4.5. Wire nav links to force re-render when clicking the current page
  document.querySelectorAll('.nav-links a[href^="#"]').forEach(link => {
    link.addEventListener('click', (e) => {
      const target = link.getAttribute('href').slice(1);
      const current = window.location.hash.slice(1) || 'upload';
      if (target === current) {
        e.preventDefault();
        router.start(); // Force re-render
      }
    });
  });

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
