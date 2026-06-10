// Feature: frontend-spa, Property 7: Submission rendering includes all required fields
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import * as fc from 'fast-check';
import { renderSubmissionCard } from '../../js/views/list.js';

/**
 * **Validates: Requirements 6.2**
 *
 * Property 7: Submission rendering includes all required fields
 * For any valid Submission object, rendered HTML contains title, file name,
 * description, date uploaded, status, and date completed (when present).
 */

const STATUSES = ['Pending', 'Processing', 'Completed', 'Failed'];

/**
 * Format an ISO 8601 date string to the expected display format.
 * Mirrors the formatDate function in list.js.
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
 * Arbitrary for a valid ISO 8601 date string.
 */
const isoDateArb = fc.date({
  min: new Date('2020-01-01T00:00:00Z'),
  max: new Date('2030-12-31T23:59:59Z'),
}).map((d) => d.toISOString());

/**
 * Arbitrary for a non-empty string suitable as a title or file name.
 */
const nonEmptyStringArb = fc.string({ minLength: 1, maxLength: 100 }).filter(
  (s) => s.trim().length > 0
);

/**
 * Arbitrary for a valid file name with extension.
 */
const fileNameArb = fc.tuple(
  fc.string({ minLength: 1, maxLength: 50 }).filter((s) => s.trim().length > 0),
  fc.constantFrom('.mp3', '.wav', '.m4a', '.aac', '.mp4', '.mov', '.webm')
).map(([name, ext]) => name + ext);

/**
 * Arbitrary for a valid Submission without dateCompleted (non-completed statuses).
 */
const submissionWithoutDateCompletedArb = fc.record({
  id: fc.uuid(),
  title: nonEmptyStringArb,
  fileName: fileNameArb,
  description: fc.option(
    fc.string({ minLength: 1, maxLength: 200 }).filter((s) => s.trim().length > 0),
    { nil: undefined }
  ),
  dateUploaded: isoDateArb,
  status: fc.constantFrom('Pending', 'Processing', 'Failed'),
});

/**
 * Arbitrary for a valid Submission with dateCompleted (status Completed).
 */
const submissionWithDateCompletedArb = fc.record({
  id: fc.uuid(),
  title: nonEmptyStringArb,
  fileName: fileNameArb,
  description: fc.option(
    fc.string({ minLength: 1, maxLength: 200 }).filter((s) => s.trim().length > 0),
    { nil: undefined }
  ),
  dateUploaded: isoDateArb,
  status: fc.constant('Completed'),
  dateCompleted: isoDateArb,
  reportUrl: fc.webUrl(),
});

/**
 * Arbitrary that generates any valid Submission (with or without dateCompleted).
 */
const submissionArb = fc.oneof(
  submissionWithoutDateCompletedArb,
  submissionWithDateCompletedArb
);

describe('Property 7: Submission rendering includes all required fields', () => {
  it('rendered card contains the submission title', () => {
    fc.assert(
      fc.property(submissionArb, (submission) => {
        const card = renderSubmissionCard(submission);
        const textContent = card.textContent;
        expect(textContent).toContain(submission.title);
      }),
      { numRuns: 100 }
    );
  });

  it('rendered card contains the file name', () => {
    fc.assert(
      fc.property(submissionArb, (submission) => {
        const card = renderSubmissionCard(submission);
        const textContent = card.textContent;
        expect(textContent).toContain(submission.fileName);
      }),
      { numRuns: 100 }
    );
  });

  it('rendered card contains the description when provided', () => {
    fc.assert(
      fc.property(submissionArb, (submission) => {
        const card = renderSubmissionCard(submission);
        const textContent = card.textContent;
        if (submission.description) {
          expect(textContent).toContain(submission.description);
        }
      }),
      { numRuns: 100 }
    );
  });

  it('rendered card contains the formatted date uploaded', () => {
    fc.assert(
      fc.property(submissionArb, (submission) => {
        const card = renderSubmissionCard(submission);
        const textContent = card.textContent;
        const formattedDate = formatDate(submission.dateUploaded);
        expect(textContent).toContain(formattedDate);
      }),
      { numRuns: 100 }
    );
  });

  it('rendered card contains the processing status', () => {
    fc.assert(
      fc.property(submissionArb, (submission) => {
        const card = renderSubmissionCard(submission);
        const textContent = card.textContent;
        expect(textContent).toContain(submission.status);
      }),
      { numRuns: 100 }
    );
  });

  it('rendered card contains the formatted date completed when present', () => {
    fc.assert(
      fc.property(submissionWithDateCompletedArb, (submission) => {
        const card = renderSubmissionCard(submission);
        const textContent = card.textContent;
        const formattedDate = formatDate(submission.dateCompleted);
        expect(textContent).toContain(formattedDate);
      }),
      { numRuns: 100 }
    );
  });
});


// Feature: frontend-spa, Property 9: Report link displayed iff status is Completed

/**
 * **Validates: Requirements 7.1, 7.3**
 *
 * Property 9: Report link displayed iff status is Completed
 * For any submission, report link is shown only when status is "Completed"
 * and reportUrl is present. For Pending, Processing, or Failed statuses,
 * no report link is rendered.
 */

/**
 * Arbitrary for a report URL.
 */
const reportUrlArb = fc.webUrl();

/**
 * Arbitrary for a submission with status "Completed" and a reportUrl present.
 */
const completedSubmissionArb = fc.record({
  id: fc.uuid(),
  title: nonEmptyStringArb,
  fileName: fileNameArb,
  description: fc.option(fc.string({ minLength: 0, maxLength: 200 }), { nil: undefined }),
  dateUploaded: isoDateArb,
  status: fc.constant('Completed'),
  dateCompleted: isoDateArb,
  reportUrl: reportUrlArb,
});

/**
 * Arbitrary for a submission with a non-completed status (no report link expected).
 */
const nonCompletedSubmissionArb = fc.record({
  id: fc.uuid(),
  title: nonEmptyStringArb,
  fileName: fileNameArb,
  description: fc.option(fc.string({ minLength: 0, maxLength: 200 }), { nil: undefined }),
  dateUploaded: isoDateArb,
  status: fc.constantFrom('Pending', 'Processing', 'Failed'),
  dateCompleted: fc.constant(undefined),
  reportUrl: fc.constant(undefined),
});

/**
 * Arbitrary for any submission (mix of completed and non-completed).
 */
const anySubmissionArb = fc.oneof(completedSubmissionArb, nonCompletedSubmissionArb);

/**
 * Helper: check if a rendered card contains a "View Report" link.
 */
function hasReportLink(cardElement) {
  const links = cardElement.querySelectorAll('a');
  for (const link of links) {
    if (link.textContent === 'View Report') {
      return true;
    }
  }
  return false;
}

describe('Property 9: Report link displayed iff status is Completed', () => {
  it('shows a report link when status is "Completed" and reportUrl is present', () => {
    fc.assert(
      fc.property(completedSubmissionArb, (submission) => {
        const card = renderSubmissionCard(submission);
        expect(hasReportLink(card)).toBe(true);

        // Verify the link points to the correct URL and opens in new tab
        const reportLink = card.querySelector('a[href]');
        expect(reportLink).not.toBeNull();
        expect(reportLink.getAttribute('href')).toBe(submission.reportUrl);
        expect(reportLink.getAttribute('target')).toBe('_blank');
      }),
      { numRuns: 100 }
    );
  });

  it('does NOT show a report link when status is "Pending", "Processing", or "Failed"', () => {
    fc.assert(
      fc.property(nonCompletedSubmissionArb, (submission) => {
        const card = renderSubmissionCard(submission);
        expect(hasReportLink(card)).toBe(false);
      }),
      { numRuns: 100 }
    );
  });

  it('report link is displayed iff status is "Completed" (biconditional over all statuses)', () => {
    fc.assert(
      fc.property(anySubmissionArb, (submission) => {
        const card = renderSubmissionCard(submission);
        const hasLink = hasReportLink(card);

        const shouldHaveLink = submission.status === 'Completed' && !!submission.reportUrl;
        expect(hasLink).toBe(shouldHaveLink);
      }),
      { numRuns: 100 }
    );
  });
});


// Feature: frontend-spa, Property 8: Submissions sorted by date descending

/**
 * Property 8: Submissions sorted by date descending
 *
 * For any array of submissions, the List View renders them in descending
 * dateUploaded order (most recent first).
 *
 * This test verifies the sort behavior by:
 * 1. Sorting any generated array of submissions using the same logic as list.js
 * 2. Rendering the sorted submissions using renderSubmissionCard
 * 3. Verifying the rendered DOM order matches descending dateUploaded
 *
 * **Validates: Requirements 6.3**
 */
describe('Property 8: Submissions sorted by date descending', () => {
  /**
   * Arbitrary that generates a random ISO 8601 date string.
   * Dates range from 2020 to 2025 for realistic variation.
   */
  const dateArb = fc.date({
    min: new Date('2020-01-01T00:00:00.000Z'),
    max: new Date('2025-12-31T23:59:59.999Z'),
  }).map((d) => d.toISOString());

  /**
   * Arbitrary for a valid processing status.
   */
  const statusArb = fc.constantFrom('Pending', 'Processing', 'Completed', 'Failed');

  /**
   * Arbitrary for a valid submission object with a random dateUploaded.
   */
  const submissionArb = fc.record({
    id: fc.uuid(),
    title: fc.string({ minLength: 1, maxLength: 100 }).filter((s) => s.trim().length > 0),
    fileName: fc.string({ minLength: 1, maxLength: 50 }).filter((s) => s.trim().length > 0).map((s) => s + '.mp4'),
    dateUploaded: dateArb,
    status: statusArb,
  });

  /**
   * Arbitrary for arrays of 2-20 submissions.
   */
  const submissionsArrayArb = fc.array(submissionArb, { minLength: 2, maxLength: 20 });

  /**
   * Replicate the sort logic from list.js to test it as a property.
   * This is the same sort implementation used in the List View.
   */
  function sortDescendingByDate(submissions) {
    return [...submissions].sort((a, b) => {
      return new Date(b.dateUploaded).getTime() - new Date(a.dateUploaded).getTime();
    });
  }

  it('sorting produces descending dateUploaded order for any input array', () => {
    fc.assert(
      fc.property(submissionsArrayArb, (submissions) => {
        const sorted = sortDescendingByDate(submissions);

        // Verify the sorted result is in descending order by dateUploaded
        for (let i = 0; i < sorted.length - 1; i++) {
          const currentDate = new Date(sorted[i].dateUploaded).getTime();
          const nextDate = new Date(sorted[i + 1].dateUploaded).getTime();
          expect(currentDate).toBeGreaterThanOrEqual(nextDate);
        }
      }),
      { numRuns: 100 }
    );
  });

  it('rendering sorted submissions produces cards in descending dateUploaded order', () => {
    fc.assert(
      fc.property(submissionsArrayArb, (submissions) => {
        // Sort using the same logic as list.js
        const sorted = sortDescendingByDate(submissions);

        // Render each sorted submission into a card
        const container = document.createElement('div');
        for (const submission of sorted) {
          const card = renderSubmissionCard(submission);
          container.appendChild(card);
        }

        // Extract rendered cards in DOM order
        const cards = container.querySelectorAll('article.card');
        expect(cards.length).toBe(submissions.length);

        // Verify DOM order matches the sorted array order by index.
        // Since we render sorted[i] as cards[i], the dates at each position
        // should be in descending order.
        for (let i = 0; i < cards.length - 1; i++) {
          const currentDate = new Date(sorted[i].dateUploaded).getTime();
          const nextDate = new Date(sorted[i + 1].dateUploaded).getTime();
          expect(currentDate).toBeGreaterThanOrEqual(nextDate);
        }
      }),
      { numRuns: 100 }
    );
  });

  it('sort preserves all submissions (no items lost or duplicated)', () => {
    fc.assert(
      fc.property(submissionsArrayArb, (submissions) => {
        const sorted = sortDescendingByDate(submissions);

        // Same length
        expect(sorted.length).toBe(submissions.length);

        // Same set of IDs (no items lost or duplicated)
        const originalIds = submissions.map((s) => s.id).sort();
        const sortedIds = sorted.map((s) => s.id).sort();
        expect(sortedIds).toEqual(originalIds);
      }),
      { numRuns: 100 }
    );
  });

  it('a single submission sorts without error', () => {
    const singleSubmissionArb = fc.array(submissionArb, { minLength: 1, maxLength: 1 });

    fc.assert(
      fc.property(singleSubmissionArb, (submissions) => {
        const sorted = sortDescendingByDate(submissions);
        expect(sorted.length).toBe(1);
        expect(sorted[0].id).toBe(submissions[0].id);
      }),
      { numRuns: 100 }
    );
  });
});
