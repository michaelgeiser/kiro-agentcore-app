/**
 * Upload Page View
 * Provides file selection, metadata entry, and submission functionality.
 *
 * Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.3, 5.4, 5.5, 10.3, 10.5
 */

import { api } from '../api.js';
import { validateFile, validateTitle, validateDescription, VALIDATION } from '../utils/validation.js';
import { createElement, formatFileSize, showToast, clearChildren } from '../utils/dom.js';

/** Accepted MIME types for the file input */
const ACCEPTED_MIME_TYPES = [
  'audio/mpeg',
  'audio/wav',
  'audio/x-m4a',
  'audio/aac',
  'video/mp4',
  'video/quicktime',
  'video/webm',
].join(',');

/**
 * Render the Upload Page into the given outlet element.
 * @param {HTMLElement} outlet - The DOM element to render the view into
 */
export function render(outlet) {
  clearChildren(outlet);

  // Form state
  const state = {
    selectedFile: null,
    title: '',
    description: '',
    isUploading: false,
    errors: {},
  };

  // --- Section: Page heading ---
  const heading = createElement('h1', { textContent: 'Upload Presentation' });

  // --- Section: File input ---
  const fileGroup = createElement('div', { className: 'form-group' });
  const fileLabel = createElement('label', {
    className: 'form-label',
    for: 'upload-file-input',
  });
  fileLabel.innerHTML = 'Presentation File <span style="color: red;">* Required</span>';
  const fileInput = createElement('input', {
    id: 'upload-file-input',
    className: 'form-file-input',
    type: 'file',
    accept: ACCEPTED_MIME_TYPES,
    'aria-label': 'Select a presentation audio or video file',
  });
  const fileInfo = createElement('div', { className: 'file-info', 'aria-live': 'polite' });
  const fileError = createElement('div', { className: 'field-error', 'aria-live': 'polite' });

  fileGroup.appendChild(fileLabel);
  const fileHint = createElement('p', {
    className: 'form-hint',
    textContent: 'audio file (mp3, wav, m4a, aac)',
  });
  fileHint.style.border = '1px dashed #ccc';
  fileHint.style.padding = '12px';
  fileHint.style.textAlign = 'center';
  fileHint.style.marginBottom = '8px';
  fileHint.style.color = '#666';
  fileGroup.appendChild(fileHint);
  fileGroup.appendChild(fileInput);
  fileGroup.appendChild(fileInfo);
  fileGroup.appendChild(fileError);

  // --- Section: Title input ---
  const titleGroup = createElement('div', { className: 'form-group' });
  const titleLabel = createElement('label', {
    className: 'form-label',
    for: 'upload-title-input',
  });
  titleLabel.innerHTML = 'Presentation Title <span style="color: red;">* Required</span>';
  const titleInput = createElement('input', {
    id: 'upload-title-input',
    className: 'form-input',
    type: 'text',
    maxlength: String(VALIDATION.MAX_TITLE_LENGTH),
    required: 'true',
    placeholder: 'Enter presentation title',
    'aria-label': 'Presentation title',
    'aria-required': 'true',
  });
  const titleCounter = createElement('div', {
    className: 'char-counter',
    'aria-live': 'polite',
    textContent: `0 / ${VALIDATION.MAX_TITLE_LENGTH}`,
  });
  const titleError = createElement('div', { className: 'field-error', 'aria-live': 'polite' });

  titleGroup.appendChild(titleLabel);
  titleGroup.appendChild(titleInput);
  titleGroup.appendChild(titleCounter);
  titleGroup.appendChild(titleError);

  // --- Section: Description textarea ---
  const descGroup = createElement('div', { className: 'form-group' });
  const descLabel = createElement('label', {
    className: 'form-label',
    textContent: 'Description (optional)',
    for: 'upload-description-input',
  });
  const descInput = createElement('textarea', {
    id: 'upload-description-input',
    className: 'form-textarea',
    maxlength: String(VALIDATION.MAX_DESCRIPTION_LENGTH),
    placeholder: 'Describe your presentation',
    'aria-label': 'Presentation description',
  });
  const descCounter = createElement('div', {
    className: 'char-counter',
    'aria-live': 'polite',
    textContent: `0 / ${VALIDATION.MAX_DESCRIPTION_LENGTH}`,
  });
  const descError = createElement('div', { className: 'field-error', 'aria-live': 'polite' });

  descGroup.appendChild(descLabel);
  descGroup.appendChild(descInput);
  descGroup.appendChild(descCounter);
  descGroup.appendChild(descError);

  // --- Section: Progress indicator ---
  const progressContainer = createElement('div', {
    className: 'progress-container',
    'aria-live': 'polite',
  });
  progressContainer.style.display = 'none';

  const progressBar = createElement('div', { className: 'progress-bar' });
  const progressFill = createElement('div', { className: 'progress-bar__fill' });
  progressFill.style.width = '0%';
  progressBar.appendChild(progressFill);

  const progressLabel = createElement('div', {
    className: 'progress-label',
    textContent: 'Uploading... 0%',
  });

  progressContainer.appendChild(progressBar);
  progressContainer.appendChild(progressLabel);

  // --- Section: Messages area ---
  const messageArea = createElement('div', { 'aria-live': 'polite' });

  // --- Section: Submit button ---
  const submitBtn = createElement('button', {
    className: 'btn btn-primary',
    type: 'button',
    textContent: 'Upload',
    disabled: 'true',
    'aria-label': 'Upload presentation file',
  });

  // --- Validation and state management ---

  function updateSubmitState() {
    const fileValid = state.selectedFile && validateFile(state.selectedFile).valid;
    const titleValid = validateTitle(state.title).valid;
    const canSubmit = fileValid && titleValid && !state.isUploading;

    if (canSubmit) {
      submitBtn.removeAttribute('disabled');
    } else {
      submitBtn.setAttribute('disabled', 'true');
    }
  }

  // --- Event handlers ---

  fileInput.addEventListener('change', () => {
    const file = fileInput.files[0] || null;
    state.selectedFile = file;

    // Clear previous file info and error
    clearChildren(fileInfo);
    fileError.textContent = '';
    fileInput.classList.remove('form-file-input--error');

    if (file) {
      const result = validateFile(file);
      if (result.valid) {
        const nameSpan = createElement('span', { textContent: file.name });
        const sizeSpan = createElement('span', { textContent: ` (${formatFileSize(file.size)})` });
        fileInfo.appendChild(nameSpan);
        fileInfo.appendChild(sizeSpan);
      } else {
        state.errors.file = result.error;
        fileError.textContent = result.error;
        // Still show the file name/size even if invalid
        const nameSpan = createElement('span', { textContent: file.name });
        const sizeSpan = createElement('span', { textContent: ` (${formatFileSize(file.size)})` });
        fileInfo.appendChild(nameSpan);
        fileInfo.appendChild(sizeSpan);
      }
    }

    updateSubmitState();
  });

  titleInput.addEventListener('input', () => {
    state.title = titleInput.value;
    const len = titleInput.value.length;

    // Update character counter
    titleCounter.textContent = `${len} / ${VALIDATION.MAX_TITLE_LENGTH}`;

    // Apply warning style when close to limit
    if (len >= VALIDATION.MAX_TITLE_LENGTH * 0.9) {
      titleCounter.classList.add('char-counter--warning');
    } else {
      titleCounter.classList.remove('char-counter--warning');
    }

    // Validate and show/clear error
    const result = validateTitle(state.title);
    if (!result.valid && state.title.length > 0) {
      titleError.textContent = result.error;
      titleInput.classList.add('form-input--error');
    } else {
      titleError.textContent = '';
      titleInput.classList.remove('form-input--error');
    }

    updateSubmitState();
  });

  titleInput.addEventListener('blur', () => {
    // Show required error on blur if empty
    const result = validateTitle(state.title);
    if (!result.valid) {
      titleError.textContent = result.error;
      titleInput.classList.add('form-input--error');
    }
  });

  descInput.addEventListener('input', () => {
    state.description = descInput.value;
    const len = descInput.value.length;

    // Update character counter
    descCounter.textContent = `${len} / ${VALIDATION.MAX_DESCRIPTION_LENGTH}`;

    // Apply warning style when close to limit
    if (len >= VALIDATION.MAX_DESCRIPTION_LENGTH * 0.9) {
      descCounter.classList.add('char-counter--warning');
    } else {
      descCounter.classList.remove('char-counter--warning');
    }

    // Validate
    const result = validateDescription(state.description);
    if (!result.valid) {
      descError.textContent = result.error;
      descInput.classList.add('form-textarea--error');
    } else {
      descError.textContent = '';
      descInput.classList.remove('form-textarea--error');
    }

    updateSubmitState();
  });

  submitBtn.addEventListener('click', async () => {
    if (state.isUploading) return;

    // Final validation
    const fileResult = validateFile(state.selectedFile);
    const titleResult = validateTitle(state.title);

    if (!fileResult.valid || !titleResult.valid) {
      if (!fileResult.valid) fileError.textContent = fileResult.error;
      if (!titleResult.valid) titleError.textContent = titleResult.error;
      return;
    }

    // Start upload
    state.isUploading = true;
    submitBtn.setAttribute('disabled', 'true');
    progressContainer.style.display = '';
    progressFill.style.width = '0%';
    progressLabel.textContent = 'Uploading... 0%';
    clearChildren(messageArea);

    const metadata = {
      title: state.title.trim(),
    };
    if (state.description.trim()) {
      metadata.description = state.description.trim();
    }

    try {
      await api.uploadSubmission(state.selectedFile, metadata, (percentage) => {
        progressFill.style.width = `${percentage}%`;
        progressLabel.textContent = `Uploading... ${percentage}%`;
      });

      // Success
      progressContainer.style.display = 'none';
      const successMsg = createElement('div', {
        className: 'message-success',
        textContent: 'Upload successful! Redirecting to submissions list...',
        role: 'status',
      });
      messageArea.appendChild(successMsg);

      // Navigate to list view after a brief delay to show success message
      setTimeout(() => {
        window.location.hash = 'list';
      }, 1500);
    } catch (error) {
      // Error
      state.isUploading = false;
      progressContainer.style.display = 'none';
      submitBtn.removeAttribute('disabled');
      updateSubmitState();

      const errorMsg = createElement('div', {
        className: 'message-error',
        textContent: error.message || 'An unexpected error occurred. Please try again.',
        role: 'alert',
      });
      clearChildren(messageArea);
      messageArea.appendChild(errorMsg);
    }
  });

  // --- Assemble form ---
  const form = createElement('form', {
    className: 'upload-form',
    'aria-label': 'Upload presentation form',
    onSubmit: (e) => e.preventDefault(),
  });

  form.appendChild(fileGroup);
  form.appendChild(titleGroup);
  form.appendChild(descGroup);
  form.appendChild(progressContainer);
  form.appendChild(messageArea);
  form.appendChild(submitBtn);

  // --- Render into outlet ---
  outlet.appendChild(heading);
  outlet.appendChild(form);
}
