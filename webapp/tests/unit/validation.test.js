import { describe, it, expect } from 'vitest';
import {
  validateFile,
  validateTitle,
  validateDescription,
  VALIDATION,
} from '../../js/utils/validation.js';

describe('VALIDATION constants', () => {
  it('defines MAX_FILE_SIZE_BYTES as 500 MB', () => {
    expect(VALIDATION.MAX_FILE_SIZE_BYTES).toBe(500 * 1024 * 1024);
  });

  it('defines MAX_TITLE_LENGTH as 200', () => {
    expect(VALIDATION.MAX_TITLE_LENGTH).toBe(200);
  });

  it('defines MAX_DESCRIPTION_LENGTH as 2000', () => {
    expect(VALIDATION.MAX_DESCRIPTION_LENGTH).toBe(2000);
  });

  it('defines accepted audio types', () => {
    expect(VALIDATION.ACCEPTED_AUDIO_TYPES).toEqual([
      'audio/mpeg',
      'audio/wav',
      'audio/x-m4a',
      'audio/aac',
    ]);
  });

  it('defines accepted video types', () => {
    expect(VALIDATION.ACCEPTED_VIDEO_TYPES).toEqual([
      'video/mp4',
      'video/quicktime',
      'video/webm',
    ]);
  });
});

describe('validateFile', () => {
  it('returns valid for an accepted audio file within size limit', () => {
    const file = { type: 'audio/mpeg', size: 1024 * 1024 }; // 1 MB MP3
    expect(validateFile(file)).toEqual({ valid: true });
  });

  it('returns valid for an accepted video file within size limit', () => {
    const file = { type: 'video/mp4', size: 100 * 1024 * 1024 }; // 100 MB MP4
    expect(validateFile(file)).toEqual({ valid: true });
  });

  it('returns valid for a file exactly at 500 MB', () => {
    const file = { type: 'audio/wav', size: 500 * 1024 * 1024 };
    expect(validateFile(file)).toEqual({ valid: true });
  });

  it('returns error for unsupported MIME type', () => {
    const file = { type: 'application/pdf', size: 1024 };
    const result = validateFile(file);
    expect(result.valid).toBe(false);
    expect(result.error).toContain('Unsupported file format');
  });

  it('returns error for file exceeding 500 MB', () => {
    const file = { type: 'video/mp4', size: 500 * 1024 * 1024 + 1 };
    const result = validateFile(file);
    expect(result.valid).toBe(false);
    expect(result.error).toContain('500 MB');
  });

  it('returns error when file is null', () => {
    const result = validateFile(null);
    expect(result.valid).toBe(false);
    expect(result.error).toContain('No file selected');
  });

  it('returns error when file is undefined', () => {
    const result = validateFile(undefined);
    expect(result.valid).toBe(false);
    expect(result.error).toContain('No file selected');
  });
});

describe('validateTitle', () => {
  it('returns valid for a normal title', () => {
    expect(validateTitle('My Presentation')).toEqual({ valid: true });
  });

  it('returns valid for a single character title', () => {
    expect(validateTitle('A')).toEqual({ valid: true });
  });

  it('returns valid for a title at exactly 200 characters', () => {
    const title = 'a'.repeat(200);
    expect(validateTitle(title)).toEqual({ valid: true });
  });

  it('returns error for an empty string', () => {
    const result = validateTitle('');
    expect(result.valid).toBe(false);
    expect(result.error).toContain('required');
  });

  it('returns error for a whitespace-only string', () => {
    const result = validateTitle('   ');
    expect(result.valid).toBe(false);
    expect(result.error).toContain('required');
  });

  it('returns error for a title exceeding 200 characters', () => {
    const title = 'a'.repeat(201);
    const result = validateTitle(title);
    expect(result.valid).toBe(false);
    expect(result.error).toContain('200');
  });

  it('returns error for non-string input (null)', () => {
    const result = validateTitle(null);
    expect(result.valid).toBe(false);
  });

  it('returns error for non-string input (undefined)', () => {
    const result = validateTitle(undefined);
    expect(result.valid).toBe(false);
  });
});

describe('validateDescription', () => {
  it('returns valid for an empty description', () => {
    expect(validateDescription('')).toEqual({ valid: true });
  });

  it('returns valid for a normal description', () => {
    expect(validateDescription('A brief summary of my presentation.')).toEqual({ valid: true });
  });

  it('returns valid for a description at exactly 2000 characters', () => {
    const desc = 'x'.repeat(2000);
    expect(validateDescription(desc)).toEqual({ valid: true });
  });

  it('returns error for a description exceeding 2000 characters', () => {
    const desc = 'x'.repeat(2001);
    const result = validateDescription(desc);
    expect(result.valid).toBe(false);
    expect(result.error).toContain('2000');
  });

  it('returns valid for non-string input (null treated gracefully)', () => {
    expect(validateDescription(null)).toEqual({ valid: true });
  });

  it('returns valid for non-string input (undefined treated gracefully)', () => {
    expect(validateDescription(undefined)).toEqual({ valid: true });
  });
});
