// Feature: frontend-spa, Property 3: File validation correctness
import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import { validateFile, VALIDATION } from '../../js/utils/validation.js';

/**
 * **Validates: Requirements 3.3, 3.4**
 *
 * Property 3: File validation correctness
 * For any file, validateFile returns valid:true iff MIME type is accepted AND size ≤ 500 MB
 */

const ACCEPTED_TYPES = [
  ...VALIDATION.ACCEPTED_AUDIO_TYPES,
  ...VALIDATION.ACCEPTED_VIDEO_TYPES,
];

const INVALID_MIME_TYPES = [
  'text/plain',
  'application/pdf',
  'image/png',
  'image/jpeg',
  'application/json',
  'audio/ogg',
  'video/avi',
  'application/octet-stream',
  'text/html',
  'audio/flac',
];

/**
 * Arbitrary for a valid MIME type (one that is accepted).
 */
const validMimeTypeArb = fc.constantFrom(...ACCEPTED_TYPES);

/**
 * Arbitrary for an invalid MIME type (not in the accepted list).
 */
const invalidMimeTypeArb = fc.constantFrom(...INVALID_MIME_TYPES);

/**
 * Arbitrary for a valid file size (0 to MAX_FILE_SIZE_BYTES inclusive).
 */
const validSizeArb = fc.integer({ min: 0, max: VALIDATION.MAX_FILE_SIZE_BYTES });

/**
 * Arbitrary for an invalid file size (exceeds MAX_FILE_SIZE_BYTES).
 */
const invalidSizeArb = fc.integer({ min: VALIDATION.MAX_FILE_SIZE_BYTES + 1, max: VALIDATION.MAX_FILE_SIZE_BYTES * 3 });

/**
 * Helper to create a File-like object for validation testing.
 */
function createFile(type, size) {
  return { type, size, name: 'test-file' };
}

describe('Property 3: File validation correctness', () => {
  it('returns valid:true for files with accepted MIME type AND size ≤ 500 MB', () => {
    fc.assert(
      fc.property(validMimeTypeArb, validSizeArb, (mimeType, size) => {
        const file = createFile(mimeType, size);
        const result = validateFile(file);
        expect(result.valid).toBe(true);
        expect(result.error).toBeUndefined();
      }),
      { numRuns: 100 }
    );
  });

  it('returns valid:false for files with invalid MIME type', () => {
    fc.assert(
      fc.property(invalidMimeTypeArb, validSizeArb, (mimeType, size) => {
        const file = createFile(mimeType, size);
        const result = validateFile(file);
        expect(result.valid).toBe(false);
        expect(result.error).toBeDefined();
        expect(typeof result.error).toBe('string');
      }),
      { numRuns: 100 }
    );
  });

  it('returns valid:false for files with size > 500 MB', () => {
    fc.assert(
      fc.property(validMimeTypeArb, invalidSizeArb, (mimeType, size) => {
        const file = createFile(mimeType, size);
        const result = validateFile(file);
        expect(result.valid).toBe(false);
        expect(result.error).toBeDefined();
        expect(typeof result.error).toBe('string');
      }),
      { numRuns: 100 }
    );
  });

  it('returns valid:true iff MIME type is accepted AND size ≤ 500 MB (biconditional)', () => {
    fc.assert(
      fc.property(
        fc.oneof(validMimeTypeArb, invalidMimeTypeArb),
        fc.oneof(validSizeArb, invalidSizeArb),
        (mimeType, size) => {
          const file = createFile(mimeType, size);
          const result = validateFile(file);

          const isAcceptedType = ACCEPTED_TYPES.includes(mimeType);
          const isValidSize = size <= VALIDATION.MAX_FILE_SIZE_BYTES;
          const shouldBeValid = isAcceptedType && isValidSize;

          expect(result.valid).toBe(shouldBeValid);
          if (!shouldBeValid) {
            expect(result.error).toBeDefined();
            expect(typeof result.error).toBe('string');
          } else {
            expect(result.error).toBeUndefined();
          }
        }
      ),
      { numRuns: 100 }
    );
  });
});


// Feature: frontend-spa, Property 5: Title validation
import { validateTitle } from '../../js/utils/validation.js';

/**
 * **Validates: Requirements 4.1, 4.3**
 *
 * Property 5: Title validation
 * For any non-empty string 1–200 chars, validateTitle returns valid:true;
 * for empty/whitespace-only or >200 chars, returns valid:false
 */

/**
 * Arbitrary for valid titles: non-empty, non-whitespace-only strings of length 1–200.
 * Uses a filtered string arbitrary that ensures at least one non-whitespace character
 * and total length does not exceed 200.
 */
const validTitleArb = fc.string({ minLength: 1, maxLength: 200 }).filter(
  (s) => s.trim().length > 0
);

/**
 * Arbitrary for whitespace-only strings (at least one char, all whitespace).
 */
const whitespaceOnlyArb = fc.stringOf(
  fc.constantFrom(' ', '\t', '\n', '\r', '\f', '\v'),
  { minLength: 1, maxLength: 50 }
);

/**
 * Arbitrary for strings exceeding max title length (>200 chars).
 */
const tooLongTitleArb = fc.string({ minLength: 201, maxLength: 500 });

describe('Property 5: Title validation', () => {
  it('returns valid:true for non-empty, non-whitespace-only strings of length 1–200', () => {
    fc.assert(
      fc.property(validTitleArb, (title) => {
        const result = validateTitle(title);
        expect(result.valid).toBe(true);
        expect(result.error).toBeUndefined();
      }),
      { numRuns: 100 }
    );
  });

  it('returns valid:false for empty strings', () => {
    const result = validateTitle('');
    expect(result.valid).toBe(false);
    expect(result.error).toBeDefined();
    expect(typeof result.error).toBe('string');
  });

  it('returns valid:false for whitespace-only strings', () => {
    fc.assert(
      fc.property(whitespaceOnlyArb, (title) => {
        const result = validateTitle(title);
        expect(result.valid).toBe(false);
        expect(result.error).toBeDefined();
        expect(typeof result.error).toBe('string');
      }),
      { numRuns: 100 }
    );
  });

  it('returns valid:false for strings exceeding 200 characters', () => {
    fc.assert(
      fc.property(tooLongTitleArb, (title) => {
        const result = validateTitle(title);
        expect(result.valid).toBe(false);
        expect(result.error).toBeDefined();
        expect(typeof result.error).toBe('string');
      }),
      { numRuns: 100 }
    );
  });
});


// Feature: frontend-spa, Property 6: Description validation
import { validateDescription } from '../../js/utils/validation.js';

/**
 * **Validates: Requirements 4.2**
 *
 * Property 6: Description validation
 * For any string 0–2000 chars, validateDescription returns valid:true;
 * for >2000 chars, returns valid:false
 */

/**
 * Arbitrary for valid descriptions: strings of length 0–2000 (including empty string).
 */
const validDescriptionArb = fc.string({ minLength: 0, maxLength: VALIDATION.MAX_DESCRIPTION_LENGTH });

/**
 * Arbitrary for strings exceeding max description length (>2000 chars).
 */
const tooLongDescriptionArb = fc.string({ minLength: VALIDATION.MAX_DESCRIPTION_LENGTH + 1, maxLength: 4000 });

describe('Property 6: Description validation', () => {
  it('returns valid:true for any string of length 0–2000 characters', () => {
    fc.assert(
      fc.property(validDescriptionArb, (description) => {
        const result = validateDescription(description);
        expect(result.valid).toBe(true);
        expect(result.error).toBeUndefined();
      }),
      { numRuns: 100 }
    );
  });

  it('returns valid:true for empty string', () => {
    const result = validateDescription('');
    expect(result.valid).toBe(true);
    expect(result.error).toBeUndefined();
  });

  it('returns valid:false for strings exceeding 2000 characters', () => {
    fc.assert(
      fc.property(tooLongDescriptionArb, (description) => {
        const result = validateDescription(description);
        expect(result.valid).toBe(false);
        expect(result.error).toBeDefined();
        expect(typeof result.error).toBe('string');
      }),
      { numRuns: 100 }
    );
  });

  it('returns valid:true for non-string inputs (graceful handling)', () => {
    fc.assert(
      fc.property(
        fc.oneof(
          fc.integer(),
          fc.constant(null),
          fc.constant(undefined),
          fc.boolean(),
          fc.array(fc.integer())
        ),
        (input) => {
          const result = validateDescription(input);
          expect(result.valid).toBe(true);
        }
      ),
      { numRuns: 100 }
    );
  });
});
