// Feature: admin-panel, Properties 1, 2 & 3: Environment variable rendering
import { describe, it, expect, beforeEach, vi } from 'vitest';
import * as fc from 'fast-check';

/**
 * **Validates: Requirements 3.3, 4.1, 4.4, 4.6, 4.7**
 *
 * Property 1: Variable rendering includes all required fields
 * For any environment variable object with a non-empty name, description, and value,
 * the rendered HTML output shall contain the variable name as a label, the description
 * text, and an editable input control pre-filled with the current value.
 *
 * Property 2: Input type determines rendered control type
 * For any environment variable with inputType of "model-dropdown", the rendered control
 * shall be a <select> element; for variables with inputType of "text", the rendered
 * control shall be an <input type="text"> element.
 *
 * Property 3: Dropdown selection reflects current value validity
 * For any model dropdown where the current value matches a known model ID in MODEL_OPTIONS,
 * that option shall be pre-selected; for any current value that does not match any entry
 * in MODEL_OPTIONS, the dropdown shall display an unselected/placeholder state indicating
 * the value is invalid or legacy.
 */

// Mock the admin API module
vi.mock('../../js/admin-api.js', () => ({
  adminApi: {
    getEnvironmentVariables: vi.fn(),
    updateEnvironmentVariables: vi.fn(),
  },
}));

import { adminApi } from '../../js/admin-api.js';
import { MODEL_OPTIONS, openEnvVarsLightbox } from '../../js/views/env-vars.js';

/**
 * Helper: flush pending promises to allow async operations to resolve.
 */
function flushPromises() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

/**
 * Arbitrary for a non-empty string (trimmed, no leading/trailing whitespace issues).
 */
const nonEmptyStringArb = fc.string({ minLength: 1, maxLength: 50 }).filter((s) => s.trim().length > 0);

/**
 * Arbitrary for a text-type environment variable object.
 */
const textVariableArb = fc.record({
  name: fc.stringMatching(/^[A-Z][A-Z0-9_]{0,29}$/),
  value: nonEmptyStringArb,
  description: nonEmptyStringArb,
  inputType: fc.constant('text'),
});

/**
 * Arbitrary for an inputType that is either "model-dropdown" or "text".
 */
const inputTypeArb = fc.oneof(fc.constant('model-dropdown'), fc.constant('text'));

/**
 * Arbitrary for an environment variable with random inputType.
 */
const variableWithTypeArb = fc.record({
  name: fc.stringMatching(/^[A-Z][A-Z0-9_]{0,29}$/),
  value: nonEmptyStringArb,
  description: nonEmptyStringArb,
  inputType: inputTypeArb,
});

/**
 * Arbitrary for a valid model ID (one of the known MODEL_OPTIONS modelIds).
 */
const validModelIdArb = fc.constantFrom(...MODEL_OPTIONS.map((opt) => opt.modelId));

/**
 * Arbitrary for an invalid model ID (random string not in MODEL_OPTIONS).
 */
const invalidModelIdArb = fc
  .string({ minLength: 1, maxLength: 50 })
  .filter((s) => s.trim().length > 0 && !MODEL_OPTIONS.some((opt) => opt.modelId === s));

/**
 * Arbitrary for a model ID — either valid or invalid.
 */
const modelIdArb = fc.oneof(validModelIdArb, invalidModelIdArb);

describe('Property 1: Variable rendering includes all required fields', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '';
  });

  it('rendered HTML contains the variable name as label', async () => {
    await fc.assert(
      fc.asyncProperty(textVariableArb, async (variable) => {
        document.body.innerHTML = '';
        adminApi.getEnvironmentVariables.mockResolvedValue([variable]);

        openEnvVarsLightbox();
        await flushPromises();

        const overlay = document.querySelector('.lightbox-overlay');
        expect(overlay).not.toBeNull();

        const label = overlay.querySelector('.admin-form-group__label');
        expect(label).not.toBeNull();
        expect(label.textContent).toBe(variable.name);
      }),
      { numRuns: 20 }
    );
  });

  it('rendered HTML contains the variable description text', async () => {
    await fc.assert(
      fc.asyncProperty(textVariableArb, async (variable) => {
        document.body.innerHTML = '';
        adminApi.getEnvironmentVariables.mockResolvedValue([variable]);

        openEnvVarsLightbox();
        await flushPromises();

        const overlay = document.querySelector('.lightbox-overlay');
        expect(overlay).not.toBeNull();

        const description = overlay.querySelector('.admin-form-group__description');
        expect(description).not.toBeNull();
        expect(description.textContent).toBe(variable.description);
      }),
      { numRuns: 20 }
    );
  });

  it('rendered HTML contains an editable input control with the current value', async () => {
    await fc.assert(
      fc.asyncProperty(textVariableArb, async (variable) => {
        document.body.innerHTML = '';
        adminApi.getEnvironmentVariables.mockResolvedValue([variable]);

        openEnvVarsLightbox();
        await flushPromises();

        const overlay = document.querySelector('.lightbox-overlay');
        expect(overlay).not.toBeNull();

        const input = overlay.querySelector(`input[name="${variable.name}"]`);
        expect(input).not.toBeNull();
        expect(input.value).toBe(variable.value);
      }),
      { numRuns: 20 }
    );
  });
});

describe('Property 2: Input type determines rendered control type', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '';
  });

  it('model-dropdown renders a <select> element; text renders an <input type="text">', async () => {
    await fc.assert(
      fc.asyncProperty(variableWithTypeArb, async (variable) => {
        document.body.innerHTML = '';

        // For model-dropdown, use a valid model ID to ensure proper rendering
        const testVariable =
          variable.inputType === 'model-dropdown'
            ? { ...variable, value: MODEL_OPTIONS[0].modelId }
            : variable;

        adminApi.getEnvironmentVariables.mockResolvedValue([testVariable]);

        openEnvVarsLightbox();
        await flushPromises();

        const overlay = document.querySelector('.lightbox-overlay');
        expect(overlay).not.toBeNull();

        if (testVariable.inputType === 'model-dropdown') {
          const select = overlay.querySelector(`select[name="${testVariable.name}"]`);
          expect(select).not.toBeNull();
          // Should not have a text input for this variable
          const textInput = overlay.querySelector(`input[type="text"][name="${testVariable.name}"]`);
          expect(textInput).toBeNull();
        } else {
          const textInput = overlay.querySelector(`input[type="text"][name="${testVariable.name}"]`);
          expect(textInput).not.toBeNull();
          // Should not have a select for this variable
          const select = overlay.querySelector(`select[name="${testVariable.name}"]`);
          expect(select).toBeNull();
        }
      }),
      { numRuns: 20 }
    );
  });

  it('model-dropdown options have displayName as text and modelId as value', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.record({
          name: fc.stringMatching(/^[A-Z][A-Z0-9_]{0,29}$/),
          value: validModelIdArb,
          description: nonEmptyStringArb,
          inputType: fc.constant('model-dropdown'),
        }),
        async (variable) => {
          document.body.innerHTML = '';
          adminApi.getEnvironmentVariables.mockResolvedValue([variable]);

          openEnvVarsLightbox();
          await flushPromises();

          const overlay = document.querySelector('.lightbox-overlay');
          const select = overlay.querySelector(`select[name="${variable.name}"]`);
          expect(select).not.toBeNull();

          // Verify each MODEL_OPTIONS entry appears as an option
          for (const modelOpt of MODEL_OPTIONS) {
            const option = select.querySelector(`option[value="${modelOpt.modelId}"]`);
            expect(option).not.toBeNull();
            expect(option.textContent).toBe(modelOpt.displayName);
          }
        }
      ),
      { numRuns: 20 }
    );
  });
});

describe('Property 3: Dropdown selection reflects current value validity', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '';
  });

  it('valid model IDs result in the matching option being pre-selected', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.record({
          name: fc.stringMatching(/^[A-Z][A-Z0-9_]{0,29}$/),
          value: validModelIdArb,
          description: nonEmptyStringArb,
          inputType: fc.constant('model-dropdown'),
        }),
        async (variable) => {
          document.body.innerHTML = '';
          adminApi.getEnvironmentVariables.mockResolvedValue([variable]);

          openEnvVarsLightbox();
          await flushPromises();

          const overlay = document.querySelector('.lightbox-overlay');
          const select = overlay.querySelector(`select[name="${variable.name}"]`);
          expect(select).not.toBeNull();

          // The select's value should match the variable's value
          expect(select.value).toBe(variable.value);

          // The selected option should have the correct modelId
          const selectedOption = select.querySelector('option:checked');
          expect(selectedOption).not.toBeNull();
          expect(selectedOption.value).toBe(variable.value);

          // No placeholder/disabled option should be present for valid values
          const placeholderOpt = select.querySelector('option[disabled]');
          expect(placeholderOpt).toBeNull();
        }
      ),
      { numRuns: 20 }
    );
  });

  it('invalid model IDs show placeholder state with disabled option selected', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.record({
          name: fc.stringMatching(/^[A-Z][A-Z0-9_]{0,29}$/),
          value: invalidModelIdArb,
          description: nonEmptyStringArb,
          inputType: fc.constant('model-dropdown'),
        }),
        async (variable) => {
          document.body.innerHTML = '';
          adminApi.getEnvironmentVariables.mockResolvedValue([variable]);

          openEnvVarsLightbox();
          await flushPromises();

          const overlay = document.querySelector('.lightbox-overlay');
          const select = overlay.querySelector(`select[name="${variable.name}"]`);
          expect(select).not.toBeNull();

          // A placeholder/disabled option should be present for invalid values
          const placeholderOpt = select.querySelector('option[disabled]');
          expect(placeholderOpt).not.toBeNull();
          expect(placeholderOpt.selected).toBe(true);

          // The placeholder text should indicate the value is invalid/legacy
          expect(placeholderOpt.textContent).toContain('invalid');
        }
      ),
      { numRuns: 20 }
    );
  });
});
