/**
 * Integration tests for the Upload Flow.
 * Tests the complete workflow: file selection → metadata entry → submit → API call → success navigation.
 *
 * Requirements: 3.1, 4.1, 5.1, 5.4
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mock the API module to control responses
vi.mock('../../js/api.js', () => ({
  api: {
    uploadSubmission: vi.fn(),
  },
}));

import { render } from '../../js/views/upload.js';
import { api } from '../../js/api.js';

describe('Upload Flow Integration', () => {
  let outlet;

  beforeEach(() => {
    vi.useFakeTimers();
    outlet = document.createElement('div');
    document.body.appendChild(outlet);
    window.location.hash = '';
  });

  afterEach(() => {
    document.body.removeChild(outlet);
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it('completes full upload flow: file selection → metadata entry → submit → API call → success navigation', async () => {
    // 1. Render the upload view
    render(outlet);

    const fileInput = outlet.querySelector('input[type="file"]');
    const titleInput = outlet.querySelector('#upload-title-input');
    const submitBtn = outlet.querySelector('button');

    expect(fileInput).not.toBeNull();
    expect(titleInput).not.toBeNull();
    expect(submitBtn).not.toBeNull();
    expect(submitBtn.hasAttribute('disabled')).toBe(true);

    // 2. Select a valid file (simulate file input change)
    const file = new File(['audio content for testing'], 'my-presentation.mp3', {
      type: 'audio/mpeg',
    });
    Object.defineProperty(fileInput, 'files', { value: [file], configurable: true });
    fileInput.dispatchEvent(new Event('change'));

    // Verify file info is displayed (Requirement 3.1)
    const fileInfo = outlet.querySelector('.file-info');
    expect(fileInfo.textContent).toContain('my-presentation.mp3');

    // 3. Enter a title (Requirement 4.1)
    titleInput.value = 'Quarterly Business Review';
    titleInput.dispatchEvent(new Event('input'));

    // Submit button should now be enabled
    expect(submitBtn.hasAttribute('disabled')).toBe(false);

    // 4. Mock the API to capture the call and simulate progress
    let capturedFile, capturedMetadata, capturedOnProgress;
    api.uploadSubmission.mockImplementation((f, metadata, onProgress) => {
      capturedFile = f;
      capturedMetadata = metadata;
      capturedOnProgress = onProgress;
      // Simulate progress updates
      onProgress(25);
      onProgress(50);
      onProgress(75);
      onProgress(100);
      return Promise.resolve({ id: 'submission-001', status: 'Pending' });
    });

    // Click submit (Requirement 5.1)
    submitBtn.click();

    // Wait for the async upload promise to resolve
    await vi.advanceTimersByTimeAsync(0);

    // 5. Verify API client was called with correct file and metadata
    expect(api.uploadSubmission).toHaveBeenCalledTimes(1);
    expect(capturedFile).toBe(file);
    expect(capturedMetadata).toEqual({ title: 'Quarterly Business Review' });
    expect(typeof capturedOnProgress).toBe('function');

    // 6. Verify progress was shown during upload
    const progressLabel = outlet.querySelector('.progress-label');
    expect(progressLabel.textContent).toContain('100%');

    // 7. Verify success message is displayed (Requirement 5.4)
    const successMsg = outlet.querySelector('.message-success');
    expect(successMsg).not.toBeNull();
    expect(successMsg.textContent).toContain('successful');

    // 8. Verify navigation to #list occurs after 1500ms delay
    expect(window.location.hash).not.toBe('#list');
    await vi.advanceTimersByTimeAsync(1500);
    expect(window.location.hash).toBe('#list');
  });

  it('includes description in metadata when provided', async () => {
    render(outlet);

    const fileInput = outlet.querySelector('input[type="file"]');
    const titleInput = outlet.querySelector('#upload-title-input');
    const descInput = outlet.querySelector('#upload-description-input');
    const submitBtn = outlet.querySelector('button');

    // Select a valid file
    const file = new File(['video content'], 'demo.mp4', { type: 'video/mp4' });
    Object.defineProperty(fileInput, 'files', { value: [file], configurable: true });
    fileInput.dispatchEvent(new Event('change'));

    // Enter title and description
    titleInput.value = 'Product Demo';
    titleInput.dispatchEvent(new Event('input'));
    descInput.value = 'A walkthrough of the new feature set';
    descInput.dispatchEvent(new Event('input'));

    // Mock the API
    api.uploadSubmission.mockResolvedValue({ id: 'submission-002' });

    // Submit
    submitBtn.click();
    await vi.advanceTimersByTimeAsync(0);

    // Verify metadata includes description
    expect(api.uploadSubmission).toHaveBeenCalledWith(
      file,
      { title: 'Product Demo', description: 'A walkthrough of the new feature set' },
      expect.any(Function),
    );
  });

  it('shows progress indicator during upload and hides it on success', async () => {
    render(outlet);

    const fileInput = outlet.querySelector('input[type="file"]');
    const titleInput = outlet.querySelector('#upload-title-input');
    const submitBtn = outlet.querySelector('button');

    // Set up valid form state
    const file = new File(['audio data'], 'talk.wav', { type: 'audio/wav' });
    Object.defineProperty(fileInput, 'files', { value: [file], configurable: true });
    fileInput.dispatchEvent(new Event('change'));
    titleInput.value = 'Conference Talk';
    titleInput.dispatchEvent(new Event('input'));

    // Mock uploadSubmission with a held promise to inspect intermediate state
    let resolveUpload;
    api.uploadSubmission.mockImplementation((f, meta, onProgress) => {
      onProgress(42);
      return new Promise((resolve) => {
        resolveUpload = resolve;
      });
    });

    // Click submit
    submitBtn.click();

    // Progress container should be visible while uploading
    const progressContainer = outlet.querySelector('.progress-container');
    expect(progressContainer.style.display).toBe('');

    // Progress should show the current percentage
    const progressLabel = outlet.querySelector('.progress-label');
    expect(progressLabel.textContent).toContain('42%');

    // Submit button should be disabled during upload
    expect(submitBtn.hasAttribute('disabled')).toBe(true);

    // Resolve the upload
    resolveUpload({ id: 'submission-003' });
    await vi.advanceTimersByTimeAsync(0);

    // Progress container should be hidden after success
    expect(progressContainer.style.display).toBe('none');
  });

  it('handles upload error and allows retry', async () => {
    render(outlet);

    const fileInput = outlet.querySelector('input[type="file"]');
    const titleInput = outlet.querySelector('#upload-title-input');
    const submitBtn = outlet.querySelector('button');

    // Set up valid form state
    const file = new File(['audio data'], 'speech.aac', { type: 'audio/aac' });
    Object.defineProperty(fileInput, 'files', { value: [file], configurable: true });
    fileInput.dispatchEvent(new Event('change'));
    titleInput.value = 'Keynote Speech';
    titleInput.dispatchEvent(new Event('input'));

    // Mock a failed upload
    api.uploadSubmission.mockRejectedValue(
      new Error('An unexpected server error occurred. Please try again later.'),
    );

    // Click submit
    submitBtn.click();
    await vi.advanceTimersByTimeAsync(0);

    // Error message should be displayed
    const errorMsg = outlet.querySelector('.message-error');
    expect(errorMsg).not.toBeNull();
    expect(errorMsg.textContent).toContain('server error');

    // Submit button should be re-enabled for retry
    expect(submitBtn.hasAttribute('disabled')).toBe(false);

    // No navigation should occur
    expect(window.location.hash).not.toBe('#list');

    // Retry: mock a successful upload this time
    api.uploadSubmission.mockResolvedValue({ id: 'submission-004' });

    submitBtn.click();
    await vi.advanceTimersByTimeAsync(0);

    // Success message should replace the error
    const successMsg = outlet.querySelector('.message-success');
    expect(successMsg).not.toBeNull();
    expect(successMsg.textContent).toContain('successful');

    // Navigate after delay
    await vi.advanceTimersByTimeAsync(1500);
    expect(window.location.hash).toBe('#list');
  });

  it('submit button stays disabled when file is invalid', () => {
    render(outlet);

    const fileInput = outlet.querySelector('input[type="file"]');
    const titleInput = outlet.querySelector('#upload-title-input');
    const submitBtn = outlet.querySelector('button');

    // Select an unsupported file type
    const file = new File(['data'], 'document.pdf', { type: 'application/pdf' });
    Object.defineProperty(fileInput, 'files', { value: [file], configurable: true });
    fileInput.dispatchEvent(new Event('change'));

    // Enter a valid title
    titleInput.value = 'My Talk';
    titleInput.dispatchEvent(new Event('input'));

    // Submit button should remain disabled
    expect(submitBtn.hasAttribute('disabled')).toBe(true);

    // File error should be displayed
    const fileError = outlet.querySelector('.field-error');
    expect(fileError.textContent).toContain('Unsupported file format');
  });

  it('submit button stays disabled when title is missing', () => {
    render(outlet);

    const fileInput = outlet.querySelector('input[type="file"]');
    const titleInput = outlet.querySelector('#upload-title-input');
    const submitBtn = outlet.querySelector('button');

    // Select a valid file
    const file = new File(['audio data'], 'talk.mp3', { type: 'audio/mpeg' });
    Object.defineProperty(fileInput, 'files', { value: [file], configurable: true });
    fileInput.dispatchEvent(new Event('change'));

    // Leave title empty
    titleInput.value = '';
    titleInput.dispatchEvent(new Event('input'));

    // Submit button should remain disabled
    expect(submitBtn.hasAttribute('disabled')).toBe(true);
  });
});
