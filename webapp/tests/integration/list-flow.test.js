/**
 * Integration tests for the List View flow.
 * Tests the full flow: API call → render submissions → report link click.
 *
 * Requirements: 6.1, 7.1, 7.2
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

const submissions = [
  {
    id: 'sub-1',
    title: 'First Presentation',
    fileName: 'first.mp3',
    description: 'My first talk',
    dateUploaded: '2024-01-10T10:00:00Z',
    status: 'Completed',
    dateCompleted: '2024-01-10T11:00:00Z',
    reportUrl: 'https://reports.example.com/sub-1',
  },
  {
    id: 'sub-2',
    title: 'Second Presentation',
    fileName: 'second.mp4',
    dateUploaded: '2024-01-15T10:00:00Z',
    status: 'Processing',
  },
  {
    id: 'sub-3',
    title: 'Third Presentation',
    fileName: 'third.wav',
    dateUploaded: '2024-01-12T10:00:00Z',
    status: 'Pending',
  },
];

describe('List View Integration Flow', () => {
  let outlet;

  beforeEach(() => {
    outlet = document.createElement('div');
    document.body.appendChild(outlet);
  });

  afterEach(() => {
    document.body.removeChild(outlet);
    vi.restoreAllMocks();
  });

  it('shows loading indicator then renders submissions after API resolves', async () => {
    api.getSubmissions.mockResolvedValue(submissions);

    render(outlet);

    // Loading indicator should appear immediately
    const loadingContainer = outlet.querySelector('.loading-container');
    expect(loadingContainer).not.toBeNull();
    expect(loadingContainer.getAttribute('role')).toBe('status');

    // Wait for submissions to render
    await vi.waitFor(() => {
      const cards = outlet.querySelectorAll('.card');
      expect(cards.length).toBe(3);
    });

    // Loading indicator should be gone
    expect(outlet.querySelector('.loading-container')).toBeNull();
  });

  it('renders submissions sorted by dateUploaded descending', async () => {
    api.getSubmissions.mockResolvedValue(submissions);

    render(outlet);

    await vi.waitFor(() => {
      const cards = outlet.querySelectorAll('.card');
      expect(cards.length).toBe(3);
    });

    const titles = outlet.querySelectorAll('.card-title');
    // Expected order: sub-2 (Jan 15), sub-3 (Jan 12), sub-1 (Jan 10)
    expect(titles[0].textContent).toBe('Second Presentation');
    expect(titles[1].textContent).toBe('Third Presentation');
    expect(titles[2].textContent).toBe('First Presentation');
  });

  it('displays report link for completed submission with target="_blank"', async () => {
    api.getSubmissions.mockResolvedValue(submissions);

    render(outlet);

    await vi.waitFor(() => {
      const cards = outlet.querySelectorAll('.card');
      expect(cards.length).toBe(3);
    });

    // The completed submission (sub-1) is rendered last due to sorting
    const reportLink = outlet.querySelector('a[href="https://reports.example.com/sub-1"]');
    expect(reportLink).not.toBeNull();
    expect(reportLink.getAttribute('target')).toBe('_blank');
    expect(reportLink.getAttribute('rel')).toBe('noopener noreferrer');
    expect(reportLink.textContent).toBe('View Report');
  });

  it('does not display report links for non-completed submissions', async () => {
    api.getSubmissions.mockResolvedValue(submissions);

    render(outlet);

    await vi.waitFor(() => {
      const cards = outlet.querySelectorAll('.card');
      expect(cards.length).toBe(3);
    });

    // Only one report link should exist (for sub-1 which is Completed)
    const reportLinks = outlet.querySelectorAll('a.link[target="_blank"]');
    expect(reportLinks.length).toBe(1);
    expect(reportLinks[0].getAttribute('href')).toBe('https://reports.example.com/sub-1');
  });

  it('report link href navigates to the correct report URL', async () => {
    api.getSubmissions.mockResolvedValue(submissions);

    render(outlet);

    await vi.waitFor(() => {
      const cards = outlet.querySelectorAll('.card');
      expect(cards.length).toBe(3);
    });

    const reportLink = outlet.querySelector('a[href="https://reports.example.com/sub-1"]');
    // Verify clicking the link would navigate to the report URL
    expect(reportLink.href).toBe('https://reports.example.com/sub-1');
  });

  it('calls getSubmissions API on render (Requirement 6.1)', async () => {
    api.getSubmissions.mockResolvedValue(submissions);

    render(outlet);

    await vi.waitFor(() => {
      expect(api.getSubmissions).toHaveBeenCalledTimes(1);
    });
  });
});
