/**
 * Unit tests for the Upload Page view.
 * Tests file input, submit button states, progress display, success navigation,
 * error handling, and character count display.
 *
 * Requirements: 3.1, 3.5, 5.2, 5.3, 5.4, 5.5, 4.4
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mock the API module
vi.mock('../../js/api.js', () => ({
  api: {
    uploadSubmission: vi.fn(),
  },
}));

import { render } from '../../js/views/upload.js';
import { api } from '../../js/api.js';

describe('Upload Page', () => {
  let outlet;

  beforeEach(() => {
    outlet = document.createElement('div');
    document.body.appendChild(outlet);
    // Reset hash
    window.location.hash = '';
  });

  afterEach(() => {
    document.body.removeChild(outlet);
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  describe('File input accepts correct MIME types (Requirement 3.1)', () => {
    it('has an accept attribute with audio and video MIME types', () => {
      render(outlet);
      const fileInput = outlet.querySelector('input[type="file"]');

      expect(fileInput).not.toBeNull();
      const accept = fileInput.getAttribute('accept');
      // Audio types
      expect(accept).toContain('audio/mpeg');
      expect(accept).toContain('audio/wav');
      expect(accept).toContain('audio/x-m4a');
      expect(accept).toContain('audio/aac');
      // Video types
      expect(accept).toContain('video/mp4');
      expect(accept).toContain('video/quicktime');
      expect(accept).toContain('video/webm');
    });
  });

  describe('Submit button disabled states (Requirements 3.5, 5.3)', () => {
    it('submit button starts disabled', () => {
      render(outlet);
      const submitBtn = outlet.querySelector('button');

      expect(submitBtn.hasAttribute('disabled')).toBe(true);
    });

    it('submit button becomes enabled when valid file and valid title are provided', () => {
      render(outlet);
      const fileInput = outlet.querySelector('input[type="file"]');
      const titleInput = outlet.querySelector('#upload-title-input');
      const submitBtn = outlet.querySelector('button');

      // Simulate selecting a valid file
      const file = new File(['audio data'], 'presentation.mp3', { type: 'audio/mpeg' });
      Object.defineProperty(fileInput, 'files', { value: [file], configurable: true });
      fileInput.dispatchEvent(new Event('change'));

      // Simulate entering a valid title
      titleInput.value = 'My Presentation';
      titleInput.dispatchEvent(new Event('input'));

      expect(submitBtn.hasAttribute('disabled')).toBe(false);
    });

    it('submit button remains disabled when file is invalid', () => {
      render(outlet);
      const fileInput = outlet.querySelector('input[type="file"]');
      const titleInput = outlet.querySelector('#upload-title-input');
      const submitBtn = outlet.querySelector('button');

      // Simulate selecting an invalid file type
      const file = new File(['data'], 'document.pdf', { type: 'application/pdf' });
      Object.defineProperty(fileInput, 'files', { value: [file], configurable: true });
      fileInput.dispatchEvent(new Event('change'));

      // Provide a valid title
      titleInput.value = 'My Presentation';
      titleInput.dispatchEvent(new Event('input'));

      expect(submitBtn.hasAttribute('disabled')).toBe(true);
    });

    it('submit button remains disabled when title is empty', () => {
      render(outlet);
      const fileInput = outlet.querySelector('input[type="file"]');
      const titleInput = outlet.querySelector('#upload-title-input');
      const submitBtn = outlet.querySelector('button');

      // Simulate selecting a valid file
      const file = new File(['audio data'], 'presentation.mp3', { type: 'audio/mpeg' });
      Object.defineProperty(fileInput, 'files', { value: [file], configurable: true });
      fileInput.dispatchEvent(new Event('change'));

      // Title remains empty
      titleInput.value = '';
      titleInput.dispatchEvent(new Event('input'));

      expect(submitBtn.hasAttribute('disabled')).toBe(true);
    });
  });

  describe('Progress indicator display during upload (Requirement 5.2)', () => {
    it('shows progress indicator and updates percentage during upload', async () => {
      render(outlet);
      const fileInput = outlet.querySelector('input[type="file"]');
      const titleInput = outlet.querySelector('#upload-title-input');
      const submitBtn = outlet.querySelector('button');

      // Set up valid form state
      const file = new File(['audio data'], 'presentation.mp3', { type: 'audio/mpeg' });
      Object.defineProperty(fileInput, 'files', { value: [file], configurable: true });
      fileInput.dispatchEvent(new Event('change'));
      titleInput.value = 'My Presentation';
      titleInput.dispatchEvent(new Event('input'));

      // Mock uploadSubmission to call onProgress then resolve
      api.uploadSubmission.mockImplementation((f, meta, onProgress) => {
        onProgress(50);
        return Promise.resolve({ id: 'sub-123' });
      });

      // Click submit
      submitBtn.click();

      // Wait for async operations
      await vi.waitFor(() => {
        const progressContainer = outlet.querySelector('.progress-container');
        // Progress container was shown (display was set to '' during upload)
        const progressLabel = outlet.querySelector('.progress-label');
        expect(progressLabel.textContent).toContain('50%');
      });
    });

    it('disables submit button during upload', async () => {
      render(outlet);
      const fileInput = outlet.querySelector('input[type="file"]');
      const titleInput = outlet.querySelector('#upload-title-input');
      const submitBtn = outlet.querySelector('button');

      // Set up valid form state
      const file = new File(['audio data'], 'presentation.mp3', { type: 'audio/mpeg' });
      Object.defineProperty(fileInput, 'files', { value: [file], configurable: true });
      fileInput.dispatchEvent(new Event('change'));
      titleInput.value = 'My Presentation';
      titleInput.dispatchEvent(new Event('input'));

      // Mock uploadSubmission that holds (doesn't resolve immediately)
      let resolveUpload;
      api.uploadSubmission.mockImplementation(() => {
        return new Promise((resolve) => {
          resolveUpload = resolve;
        });
      });

      // Click submit
      submitBtn.click();

      // Button should be disabled during upload
      expect(submitBtn.hasAttribute('disabled')).toBe(true);

      // Resolve the upload
      resolveUpload({ id: 'sub-123' });
    });
  });

  describe('Success navigation to list view (Requirement 5.4)', () => {
    it('displays success message and navigates to #list on successful upload', async () => {
      vi.useFakeTimers();
      render(outlet);
      const fileInput = outlet.querySelector('input[type="file"]');
      const titleInput = outlet.querySelector('#upload-title-input');
      const submitBtn = outlet.querySelector('button');

      // Set up valid form state
      const file = new File(['audio data'], 'presentation.mp3', { type: 'audio/mpeg' });
      Object.defineProperty(fileInput, 'files', { value: [file], configurable: true });
      fileInput.dispatchEvent(new Event('change'));
      titleInput.value = 'My Presentation';
      titleInput.dispatchEvent(new Event('input'));

      // Mock successful upload
      api.uploadSubmission.mockResolvedValue({ id: 'sub-123' });

      // Click submit
      submitBtn.click();

      // Wait for the promise to resolve
      await vi.advanceTimersByTimeAsync(0);

      // Check success message is displayed
      const successMsg = outlet.querySelector('.message-success');
      expect(successMsg).not.toBeNull();
      expect(successMsg.textContent).toContain('successful');

      // Advance timer past the navigation delay
      await vi.advanceTimersByTimeAsync(1500);

      expect(window.location.hash).toBe('#list');
    });
  });

  describe('Error display and retry capability (Requirement 5.5)', () => {
    it('displays error message on upload failure', async () => {
      render(outlet);
      const fileInput = outlet.querySelector('input[type="file"]');
      const titleInput = outlet.querySelector('#upload-title-input');
      const submitBtn = outlet.querySelector('button');

      // Set up valid form state
      const file = new File(['audio data'], 'presentation.mp3', { type: 'audio/mpeg' });
      Object.defineProperty(fileInput, 'files', { value: [file], configurable: true });
      fileInput.dispatchEvent(new Event('change'));
      titleInput.value = 'My Presentation';
      titleInput.dispatchEvent(new Event('input'));

      // Mock failed upload
      api.uploadSubmission.mockRejectedValue(new Error('An unexpected server error occurred. Please try again later.'));

      // Click submit
      submitBtn.click();

      // Wait for async operations
      await vi.waitFor(() => {
        const errorMsg = outlet.querySelector('.message-error');
        expect(errorMsg).not.toBeNull();
        expect(errorMsg.textContent).toContain('server error');
      });
    });

    it('re-enables submit button after upload failure for retry', async () => {
      render(outlet);
      const fileInput = outlet.querySelector('input[type="file"]');
      const titleInput = outlet.querySelector('#upload-title-input');
      const submitBtn = outlet.querySelector('button');

      // Set up valid form state
      const file = new File(['audio data'], 'presentation.mp3', { type: 'audio/mpeg' });
      Object.defineProperty(fileInput, 'files', { value: [file], configurable: true });
      fileInput.dispatchEvent(new Event('change'));
      titleInput.value = 'My Presentation';
      titleInput.dispatchEvent(new Event('input'));

      // Mock failed upload
      api.uploadSubmission.mockRejectedValue(new Error('Network error'));

      // Click submit
      submitBtn.click();

      // Wait for async operations
      await vi.waitFor(() => {
        expect(submitBtn.hasAttribute('disabled')).toBe(false);
      });
    });
  });

  describe('Character count display (Requirement 4.4)', () => {
    it('title character count updates on input (shows "x / 200")', () => {
      render(outlet);
      const titleInput = outlet.querySelector('#upload-title-input');
      const charCounters = outlet.querySelectorAll('.char-counter');
      // First char-counter is for title
      const titleCounter = charCounters[0];

      // Initial state
      expect(titleCounter.textContent).toBe('0 / 200');

      // Type some text
      titleInput.value = 'Hello';
      titleInput.dispatchEvent(new Event('input'));

      expect(titleCounter.textContent).toBe('5 / 200');
    });

    it('description character count updates on input (shows "x / 2000")', () => {
      render(outlet);
      const descInput = outlet.querySelector('#upload-description-input');
      const charCounters = outlet.querySelectorAll('.char-counter');
      // Second char-counter is for description
      const descCounter = charCounters[1];

      // Initial state
      expect(descCounter.textContent).toBe('0 / 2000');

      // Type some text
      descInput.value = 'This is a description';
      descInput.dispatchEvent(new Event('input'));

      expect(descCounter.textContent).toBe('21 / 2000');
    });
  });
});
