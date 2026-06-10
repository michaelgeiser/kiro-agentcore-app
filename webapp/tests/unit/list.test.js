/**
 * Unit tests for the List View.
 * Tests loading indicator, empty state, report link behavior, and error state with retry.
 *
 * Requirements: 6.4, 6.5, 7.2
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mock the API module
vi.mock('../../js/api.js', () => ({
  api: {
    getSubmissions: vi.fn(),
    getReportUrl: vi.fn(),
  },
}));

import { render } from '../../js/views/list.js';
import { api } from '../../js/api.js';

describe('List View', () => {
  let outlet;

  beforeEach(() => {
    outlet = document.createElement('div');
    document.body.appendChild(outlet);
  });

  afterEach(() => {
    document.body.removeChild(outlet);
    vi.restoreAllMocks();
  });

  describe('Loading indicator display (Requirement 6.4)', () => {
    it('shows a loading indicator immediately when render is called', () => {
      // Keep the API call pending so loading state persists
      api.getSubmissions.mockReturnValue(new Promise(() => {}));

      render(outlet);

      const loadingContainer = outlet.querySelector('.loading-container');
      expect(loadingContainer).not.toBeNull();
      expect(loadingContainer.getAttribute('role')).toBe('status');
      expect(loadingContainer.getAttribute('aria-label')).toBe('Loading submissions');
    });

    it('shows a loading spinner inside the loading container', () => {
      api.getSubmissions.mockReturnValue(new Promise(() => {}));

      render(outlet);

      const spinner = outlet.querySelector('.loading-spinner');
      expect(spinner).not.toBeNull();
    });

    it('shows loading text indicating submissions are being loaded', () => {
      api.getSubmissions.mockReturnValue(new Promise(() => {}));

      render(outlet);

      const loadingText = outlet.querySelector('.loading-text');
      expect(loadingText).not.toBeNull();
      expect(loadingText.textContent).toContain('Loading');
    });
  });

  describe('Empty state message and upload link (Requirement 6.5)', () => {
    it('displays empty state message when API returns empty array', async () => {
      api.getSubmissions.mockResolvedValue([]);

      render(outlet);

      await vi.waitFor(() => {
        const emptyState = outlet.querySelector('.empty-state');
        expect(emptyState).not.toBeNull();
      });

      const emptyTitle = outlet.querySelector('.empty-state__title');
      expect(emptyTitle).not.toBeNull();
      expect(emptyTitle.textContent).toContain('No submissions');
    });

    it('provides a link to the Upload Page in the empty state', async () => {
      api.getSubmissions.mockResolvedValue([]);

      render(outlet);

      await vi.waitFor(() => {
        const uploadLink = outlet.querySelector('a[href="#upload"]');
        expect(uploadLink).not.toBeNull();
      });

      const uploadLink = outlet.querySelector('a[href="#upload"]');
      expect(uploadLink.textContent).toContain('Upload');
    });

    it('removes loading indicator after empty state renders', async () => {
      api.getSubmissions.mockResolvedValue([]);

      render(outlet);

      await vi.waitFor(() => {
        const emptyState = outlet.querySelector('.empty-state');
        expect(emptyState).not.toBeNull();
      });

      const loadingContainer = outlet.querySelector('.loading-container');
      expect(loadingContainer).toBeNull();
    });
  });

  describe('Report link opens in new tab (Requirement 7.2)', () => {
    it('report link has target="_blank" for completed submissions', async () => {
      const submissions = [
        {
          id: 'sub-1',
          title: 'My Presentation',
          fileName: 'presentation.mp3',
          description: 'A test presentation',
          dateUploaded: '2024-01-15T10:00:00Z',
          status: 'Completed',
          dateCompleted: '2024-01-15T11:00:00Z',
          reportUrl: 'https://reports.example.com/sub-1',
        },
      ];
      api.getSubmissions.mockResolvedValue(submissions);

      render(outlet);

      await vi.waitFor(() => {
        const reportLink = outlet.querySelector('a.link[href="https://reports.example.com/sub-1"]');
        expect(reportLink).not.toBeNull();
      });

      const reportLink = outlet.querySelector('a.link[href="https://reports.example.com/sub-1"]');
      expect(reportLink.getAttribute('target')).toBe('_blank');
    });

    it('report link has rel="noopener noreferrer" for security', async () => {
      const submissions = [
        {
          id: 'sub-1',
          title: 'My Presentation',
          fileName: 'presentation.mp3',
          dateUploaded: '2024-01-15T10:00:00Z',
          status: 'Completed',
          dateCompleted: '2024-01-15T11:00:00Z',
          reportUrl: 'https://reports.example.com/sub-1',
        },
      ];
      api.getSubmissions.mockResolvedValue(submissions);

      render(outlet);

      await vi.waitFor(() => {
        const reportLink = outlet.querySelector('a.link');
        expect(reportLink).not.toBeNull();
      });

      const reportLink = outlet.querySelector('a.link');
      expect(reportLink.getAttribute('rel')).toBe('noopener noreferrer');
    });

    it('report link text is "View Report"', async () => {
      const submissions = [
        {
          id: 'sub-1',
          title: 'My Presentation',
          fileName: 'presentation.mp3',
          dateUploaded: '2024-01-15T10:00:00Z',
          status: 'Completed',
          dateCompleted: '2024-01-15T11:00:00Z',
          reportUrl: 'https://reports.example.com/sub-1',
        },
      ];
      api.getSubmissions.mockResolvedValue(submissions);

      render(outlet);

      await vi.waitFor(() => {
        const reportLink = outlet.querySelector('a.link');
        expect(reportLink).not.toBeNull();
      });

      const reportLink = outlet.querySelector('a.link');
      expect(reportLink.textContent).toBe('View Report');
    });
  });

  describe('Error state with retry (Requirements 6.4, 6.5)', () => {
    it('displays error message when API call fails', async () => {
      api.getSubmissions.mockRejectedValue(new Error('Network unavailable'));

      render(outlet);

      await vi.waitFor(() => {
        const errorMsg = outlet.querySelector('.message-error');
        expect(errorMsg).not.toBeNull();
      });

      const errorMsg = outlet.querySelector('.message-error');
      expect(errorMsg.textContent).toContain('Failed to load');
    });

    it('displays a retry button when API call fails', async () => {
      api.getSubmissions.mockRejectedValue(new Error('Network unavailable'));

      render(outlet);

      await vi.waitFor(() => {
        const retryBtn = outlet.querySelector('button');
        expect(retryBtn).not.toBeNull();
      });

      const retryBtn = outlet.querySelector('button');
      expect(retryBtn.textContent).toBe('Retry');
      expect(retryBtn.getAttribute('aria-label')).toBe('Retry loading submissions');
    });

    it('clicking retry calls getSubmissions again', async () => {
      api.getSubmissions.mockRejectedValueOnce(new Error('Network unavailable'));
      api.getSubmissions.mockResolvedValueOnce([]);

      render(outlet);

      await vi.waitFor(() => {
        const retryBtn = outlet.querySelector('button');
        expect(retryBtn).not.toBeNull();
      });

      // Click retry
      const retryBtn = outlet.querySelector('button');
      retryBtn.click();

      await vi.waitFor(() => {
        expect(api.getSubmissions).toHaveBeenCalledTimes(2);
      });
    });

    it('shows loading indicator again after clicking retry', async () => {
      api.getSubmissions.mockRejectedValueOnce(new Error('Network unavailable'));
      // Second call will hang to show loading
      api.getSubmissions.mockReturnValueOnce(new Promise(() => {}));

      render(outlet);

      await vi.waitFor(() => {
        const retryBtn = outlet.querySelector('button');
        expect(retryBtn).not.toBeNull();
      });

      // Click retry
      const retryBtn = outlet.querySelector('button');
      retryBtn.click();

      const loadingContainer = outlet.querySelector('.loading-container');
      expect(loadingContainer).not.toBeNull();
    });

    it('renders submissions successfully after retry', async () => {
      const submissions = [
        {
          id: 'sub-1',
          title: 'Retry Success',
          fileName: 'test.mp3',
          dateUploaded: '2024-01-15T10:00:00Z',
          status: 'Pending',
        },
      ];
      api.getSubmissions.mockRejectedValueOnce(new Error('Network error'));
      api.getSubmissions.mockResolvedValueOnce(submissions);

      render(outlet);

      await vi.waitFor(() => {
        const retryBtn = outlet.querySelector('button');
        expect(retryBtn).not.toBeNull();
      });

      // Click retry
      const retryBtn = outlet.querySelector('button');
      retryBtn.click();

      await vi.waitFor(() => {
        const card = outlet.querySelector('.card');
        expect(card).not.toBeNull();
      });

      const cardTitle = outlet.querySelector('.card-title');
      expect(cardTitle.textContent).toBe('Retry Success');
    });
  });
});
