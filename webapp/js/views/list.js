/**
 * List View — Displays all user submissions with status and report access.
 *
 * Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 7.1, 7.2, 7.3, 10.5
 */

import { api } from '../api.js';
import { createElement, clearChildren, showToast } from '../utils/dom.js';

/**
 * Show a confirmation dialog and delete the submission if confirmed.
 * @param {string} submissionId
 * @param {string} title
 * @param {HTMLElement} cardElement - The card to remove from DOM on success
 */
async function _confirmAndDelete(submissionId, title, cardElement) {
  const confirmed = window.confirm(
    `Are you sure you want to delete "${title}"?\n\nThis will permanently remove all files, evaluations, and reports associated with this submission.`
  );

  if (!confirmed) return;

  try {
    await api.deleteSubmission(submissionId);
    cardElement.remove();
    showToast('Submission deleted successfully.', 'success');
  } catch (error) {
    showToast(error.message || 'Failed to delete submission.', 'error');
  }
}

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
 * @param {'Pending'|'Processing'|'Waiting'|'Evaluating'|'Report_Generating'|'Completed'|'Failed'} submission.status
 * @param {string} [submission.dateCompleted] - ISO 8601 date string
 * @param {string} [submission.reportUrl] - URL to the generated report
 * @returns {HTMLElement} The card element
 */
export function renderSubmissionCard(submission) {
  const statusClass = `status-badge status-badge--${submission.status.toLowerCase()}`;

  // Card header: title + status badge (with optional processing indicator)
  const titleEl = createElement('h3', { className: 'card-title', textContent: submission.title });

  // Processing indicator shown inline during active processing/evaluation
  const activeProcessingStates = ['Processing', 'Evaluating', 'Report_Generating'];
  let processingIndicator = null;
  if (activeProcessingStates.includes(submission.status)) {
    const processingText = createElement('span', {
      className: 'processing-indicator',
      textContent: 'Processing...',
      'aria-label': 'Processing in progress',
    });
    processingIndicator = processingText;
  }

  const statusBadge = createElement('span', {
    className: statusClass,
    textContent: submission.status === 'Report_Generating' ? 'Generating Report' : submission.status,
    'aria-label': `Status: ${submission.status}`,
  });

  const headerChildren = [titleEl];
  if (processingIndicator) headerChildren.push(processingIndicator);
  headerChildren.push(statusBadge);
  const header = createElement('div', { className: 'card-header' }, headerChildren);

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

  // Card footer: report link (only for Completed status) + delete button
  const footerChildren = [];

  if (submission.status === 'Completed' && submission.reportUrl) {
    const reportLink = createElement('a', {
      className: 'btn btn-secondary',
      href: submission.reportUrl,
      target: '_blank',
      rel: 'noopener noreferrer',
      textContent: 'Download Report',
      'aria-label': `Download coaching report for ${submission.title}`,
    });
    footerChildren.push(reportLink);
  }

  // Delete button (always shown, always on the right)
  const deleteBtn = createElement('button', {
    className: 'btn btn-danger',
    type: 'button',
    textContent: 'Delete',
    'aria-label': `Delete submission ${submission.title}`,
  });
  deleteBtn.style.marginLeft = 'auto';
  deleteBtn.addEventListener('click', () => {
    _confirmAndDelete(submission.id, submission.title, card);
  });
  footerChildren.push(deleteBtn);

  const card = createElement('article', { className: 'card', 'aria-label': `Submission: ${submission.title}` }, [
    header,
    body,
  ]);

  const footer = createElement('div', { className: 'card-footer' }, footerChildren);
  footer.style.display = 'flex';
  footer.style.alignItems = 'center';
  card.appendChild(footer);

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

/** @type {number|null} */
let _refreshInterval = null;

/**
 * Render the List View into the given outlet element.
 * Fetches submissions from the API and displays them sorted by date descending.
 *
 * @param {HTMLElement} outlet - The DOM element to render into
 */
export function render(outlet) {
  // Clear any existing refresh interval from a previous render
  if (_refreshInterval) {
    clearInterval(_refreshInterval);
    _refreshInterval = null;
  }

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
 * Sets up auto-refresh if any submissions are in a processing state.
 * @param {HTMLElement} contentArea - The element to render submissions into
 */
async function loadSubmissions(contentArea) {
  try {
    const submissions = await api.getSubmissions();

    clearChildren(contentArea);

    if (!submissions || submissions.length === 0) {
      contentArea.appendChild(renderEmptyState());
      _stopAutoRefresh();
      return;
    }

    // Check if any submissions are still processing
    const processingStates = ['Pending', 'Processing', 'Waiting', 'Evaluating', 'Report_Generating'];
    const hasProcessing = submissions.some(s => processingStates.includes(s.status));

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

    // Start auto-refresh if any submissions are still processing
    if (hasProcessing) {
      _startAutoRefresh(contentArea);
    } else {
      _stopAutoRefresh();
    }
  } catch (error) {
    clearChildren(contentArea);
    contentArea.appendChild(renderErrorState(() => {
      clearChildren(contentArea);
      contentArea.appendChild(renderLoading());
      loadSubmissions(contentArea);
    }));
  }
}

/**
 * Start auto-refreshing the submissions list every 60 seconds.
 * @param {HTMLElement} contentArea
 */
function _startAutoRefresh(contentArea) {
  _stopAutoRefresh();
  _refreshInterval = setInterval(() => {
    loadSubmissions(contentArea);
  }, 60000);
}

/**
 * Stop auto-refreshing the submissions list.
 */
function _stopAutoRefresh() {
  if (_refreshInterval) {
    clearInterval(_refreshInterval);
    _refreshInterval = null;
  }
}
