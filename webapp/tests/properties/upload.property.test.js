// Feature: frontend-spa, Property 4: File selection displays file information
import { describe, it, expect, beforeEach, vi } from 'vitest';
import * as fc from 'fast-check';
import { formatFileSize } from '../../js/utils/dom.js';

// Mock the api module so we don't need real API calls
vi.mock('../../js/api.js', () => ({
  api: {
    uploadSubmission: vi.fn(),
    getSubmissions: vi.fn(),
    getReportUrl: vi.fn(),
  },
}));

/**
 * **Validates: Requirements 3.2**
 *
 * Property 4: File selection displays file information
 * For any file with any name and any size, selecting it via the file input
 * should result in the file's name and human-readable formatted size being
 * displayed in the upload form.
 */
describe('Property 4: File selection displays file information', () => {
  let outlet;

  beforeEach(() => {
    document.body.innerHTML = '';
    outlet = document.createElement('div');
    outlet.id = 'app-outlet';
    document.body.appendChild(outlet);
  });

  /**
   * Helper to simulate file selection on a file input in jsdom.
   * Since DataTransfer is not available in jsdom, we use Object.defineProperty
   * to set the files property with a mock FileList.
   */
  function simulateFileSelection(fileInput, file) {
    const fileList = {
      0: file,
      length: 1,
      item: (index) => (index === 0 ? file : null),
      [Symbol.iterator]: function* () { yield file; },
    };
    Object.defineProperty(fileInput, 'files', {
      value: fileList,
      writable: true,
      configurable: true,
    });
    const changeEvent = new Event('change', { bubbles: true });
    fileInput.dispatchEvent(changeEvent);
  }

  it('displays file name and human-readable size for any selected file', async () => {
    const { render } = await import('../../js/views/upload.js');

    // Arbitrary for file names: non-empty strings with a file extension
    const fileNameArb = fc.tuple(
      fc.string({ minLength: 1, maxLength: 50 }).filter(s => s.trim().length > 0),
      fc.constantFrom('.mp3', '.wav', '.m4a', '.aac', '.mp4', '.mov', '.webm', '.pdf', '.txt')
    ).map(([name, ext]) => name.replace(/[/\\:*?"<>|]/g, '_') + ext);

    // Arbitrary for file sizes: 0 to 2 GB range
    const fileSizeArb = fc.integer({ min: 0, max: 2 * 1024 * 1024 * 1024 });

    fc.assert(
      fc.property(fileNameArb, fileSizeArb, (fileName, fileSize) => {
        // Re-render fresh for each iteration
        outlet.innerHTML = '';
        render(outlet);

        const fileInput = outlet.querySelector('input[type="file"]');
        expect(fileInput).not.toBeNull();

        // Create a File-like object with the generated name and size
        const file = new File(['x'], fileName, { type: 'audio/mpeg' });
        Object.defineProperty(file, 'size', { value: fileSize, writable: false });

        // Simulate file selection
        simulateFileSelection(fileInput, file);

        // Check that the .file-info div contains the file name and formatted size
        const fileInfo = outlet.querySelector('.file-info');
        expect(fileInfo).not.toBeNull();

        const fileInfoText = fileInfo.textContent;
        const expectedSize = formatFileSize(fileSize);

        expect(fileInfoText).toContain(fileName);
        expect(fileInfoText).toContain(expectedSize);
      }),
      { numRuns: 100 }
    );
  });
});
