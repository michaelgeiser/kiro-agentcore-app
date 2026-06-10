/**
 * List View — Displays all user submissions with status and report access.
 *
 * Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 7.1, 7.2, 7.3, 10.5
 */

import { api } from '../api.js';
import { createElement, clearChildren } from '../utils/dom.js';

/**
 * Format an ISO 8601 date string to a human-readable format.
 * @param {string} isoString - ISO 8601 date string
 * @returns {string} Formatted date string
 */
function formatDate(isoString) {
  if (!isoString) return '';
  const date = new Date(isoString);
  return date.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/**
 * Render a single submission card element.
 * Exported for property-based testing.
 *
 * @param {Object} submission
 * @param {string} submission.id
 * @param {string} submission.title
 * @param {string} submission.fileName
 * @param {string} [submission.description]
 * @param {string} submission.dateUploaded - ISO 8601 date string
 * @param {'Pending'|'Processing'|'Completed'|'Failed'} submission.status
 * @param {string} [submission.dateCompleted] - ISO 8601 date string
 * @param {string} [submission.reportUrl] - URL to the generated report
 * @returns {HTMLElement} The card element
 */
export function renderSubmissionCard(submission) {
  const statusClass = `status-badge status-badge--${submission.status.toLowerCase()}`;

  // Card header: title + status badge
  const titleEl = createElement('h3', { className: 'card-title', textContent: submission.title });
  const statusBadge = createElement('span', {
    className: statusClass,
    textContent: submission.status,
    'aria-label': `Status: ${submission.status}`,
  });
  const header = createElement('div', { className: 'card-header' }, [titleEl, statusBadge]);

  // Card body: file name, description, dates
  const bodyChildren = [];

  const fileNameEl = createElement('p', { className: 'card-meta' }, [
    createElement('strong', { textContent: 'File: ' }),
    document.createTextNode(submission.fileName),
  ]);
  bodyChildren.push(fileNameEl);

  if (submission.description) {
    const descEl = createElement('p', { className: 'card-body', textContent: submission.description });
    bodyChildren.push(descEl);
  }

  const dateUploadedEl = createElement('p', { className: 'card-meta' }, [
    createElement('strong', { textContent: 'Uploaded: ' }),
    document.createTextNode(formatDate(submission.dateUploaded)),
  ]);
  bodyChildren.push(dateUploadedEl);

  if (submission.dateCompleted) {
    const dateCompletedEl = createElement('p', { className: 'card-meta' }, [
      createElement('strong', { textContent: 'Completed: ' }),
      document.createTextNode(formatDate(submission.dateCompleted)),
    ]);
    bodyChildren.push(dateCompletedEl);
  }

  const body = createElement('div', { className: 'card-body' }, bodyChildren);

  // Card footer: report link (only for Completed status)
  const footerChildren = [];

  if (submission.status === 'Completed' && submission.reportUrl) {
    const reportLink = createElement('a', {
      className: 'link',
      href: submission.reportUrl,
      target: '_blank',
      rel: 'noopener noreferrer',
      textContent: 'View Report',
      'aria-label': `View report for ${submission.title}`,
    });
    footerChildren.push(reportLink);
  }

  const card = createElement('article', { className: 'card', 'aria-label': `Submission: ${submission.title}` }, [
    header,
    body,
  ]);

  if (footerChildren.length > 0) {
    const footer = createElement('div', { className: 'card-footer' }, footerChildren);
    card.appendChild(footer);
  }

  return card;
}

/**
 * Render the loading state into the outlet.
 * @returns {HTMLElement}
 */
function renderLoading() {
  const spinner = createElement('div', {
    className: 'loading-spinner loading-spinner--large',
    'aria-hidden': 'true',
  });
  const text = createElement('p', { className: 'loading-text', textContent: 'Loading submissions...' });
  return createElement('div', {
    className: 'loading-container',
    role: 'status',
    'aria-label': 'Loading submissions',
  }, [spinner, text]);
}

/**
 * Render the empty state when no submissions exist.
 * @returns {HTMLElement}
 */
function renderEmptyState() {
  const title = createElement('h2', { className: 'empty-state__title', textContent: 'No submissions yet' });
  const description = createElement('p', { className: 'empty-state__description', textContent: 'Upload a presentation to get started with coaching feedback.' });
  const uploadLink = createElement('a', {
    className: 'btn btn-primary',
    href: '#upload',
    'aria-label': 'Go to upload page',
    textContent: 'Upload a Presentation',
  });
  return createElement('div', { className: 'empty-state' }, [title, description, uploadLink]);
}

/**
 * Render the error state with a retry button.
 * @param {Function} onRetry - Callback to invoke when retry is clicked
 * @returns {HTMLElement}
 */
function renderErrorState(onRetry) {
  const message = createElement('p', { className: 'message-error', textContent: 'Failed to load submissions. Please try again.' });
  const retryBtn = createElement('button', {
    className: 'btn btn-secondary',
    textContent: 'Retry',
    'aria-label': 'Retry loading submissions',
    onClick: onRetry,
  });
  const container = createElement('div', { className: 'empty-state' }, [message, retryBtn]);
  return container;
}

/**
 * Render the List View into the given outlet element.
 * Fetches submissions from the API and displays them sorted by date descending.
 *
 * @param {HTMLElement} outlet - The DOM element to render into
 */
export function render(outlet) {
  clearChildren(outlet);

  const container = createElement('section', { 'aria-label': 'Submissions list' });
  const heading = createElement('h1', { textContent: 'My Submissions' });
  container.appendChild(heading);

  const contentArea = createElement('div', {});
  container.appendChild(contentArea);
  outlet.appendChild(container);

  // Show loading state
  contentArea.appendChild(renderLoading());

  // Fetch and render submissions
  loadSubmissions(contentArea);
}

/**
 * Load submissions from the API and render them into the content area.
 * @param {HTMLElement} contentArea - The element to render submissions into
 */
async function loadSubmissions(contentArea) {
  try {
    const submissions = await api.getSubmissions();

    clearChildren(contentArea);

    if (!submissions || submissions.length === 0) {
      contentArea.appendChild(renderEmptyState());
      return;
    }

    // Sort by dateUploaded descending (most recent first)
    const sorted = [...submissions].sort((a, b) => {
      return new Date(b.dateUploaded).getTime() - new Date(a.dateUploaded).getTime();
    });

    const list = createElement('div', { className: 'submissions-list', role: 'list', 'aria-label': 'Submissions' });

    for (const submission of sorted) {
      const card = renderSubmissionCard(submission);
      card.setAttribute('role', 'listitem');
      list.appendChild(card);
    }

    contentArea.appendChild(list);
  } catch (error) {
    clearChildren(contentArea);
    contentArea.appendChild(renderErrorState(() => {
      clearChildren(contentArea);
      contentArea.appendChild(renderLoading());
      loadSubmissions(contentArea);
    }));
  }
}
