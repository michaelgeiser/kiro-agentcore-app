/**
 * Pure validation functions for upload form inputs.
 */

/**
 * Validation constants for file uploads and metadata.
 */
export const VALIDATION = {
  MAX_FILE_SIZE_BYTES: 500 * 1024 * 1024, // 500 MB
  MAX_TITLE_LENGTH: 200,
  MAX_DESCRIPTION_LENGTH: 2000,
  ACCEPTED_AUDIO_TYPES: ['audio/mpeg', 'audio/wav', 'audio/x-m4a', 'audio/aac'],
  ACCEPTED_VIDEO_TYPES: ['video/mp4', 'video/quicktime', 'video/webm'],
};

/**
 * All accepted MIME types (audio + video combined).
 */
const ACCEPTED_TYPES = [
  ...VALIDATION.ACCEPTED_AUDIO_TYPES,
  ...VALIDATION.ACCEPTED_VIDEO_TYPES,
];

/**
 * Validate a selected file against type and size constraints.
 * @param {File} file
 * @returns {{ valid: boolean, error?: string }}
 */
export function validateFile(file) {
  if (!file) {
    return { valid: false, error: 'No file selected.' };
  }

  if (!ACCEPTED_TYPES.includes(file.type)) {
    return {
      valid: false,
      error: 'Unsupported file format. Accepted formats: MP3, WAV, M4A, AAC, MP4, MOV, WebM.',
    };
  }

  if (file.size > VALIDATION.MAX_FILE_SIZE_BYTES) {
    return {
      valid: false,
      error: 'File exceeds the maximum allowed size of 500 MB.',
    };
  }

  return { valid: true };
}

/**
 * Validate presentation title.
 * @param {string} title
 * @returns {{ valid: boolean, error?: string }}
 */
export function validateTitle(title) {
  if (typeof title !== 'string' || title.trim().length === 0) {
    return { valid: false, error: 'Title is required.' };
  }

  if (title.length > VALIDATION.MAX_TITLE_LENGTH) {
    return {
      valid: false,
      error: `Title must be ${VALIDATION.MAX_TITLE_LENGTH} characters or fewer.`,
    };
  }

  return { valid: true };
}

/**
 * Validate presentation description.
 * @param {string} description
 * @returns {{ valid: boolean, error?: string }}
 */
export function validateDescription(description) {
  if (typeof description !== 'string') {
    return { valid: true };
  }

  if (description.length > VALIDATION.MAX_DESCRIPTION_LENGTH) {
    return {
      valid: false,
      error: `Description must be ${VALIDATION.MAX_DESCRIPTION_LENGTH} characters or fewer.`,
    };
  }

  return { valid: true };
}
