/**
 * Feature: admin-panel, Properties 4 & 5: Change tracking (integration-level)
 *
 * **Validates: Requirements 5.1, 5.2, 5.3, 5.5, 6.1**
 *
 * Property 4: Change tracking round-trip preserves clean state
 * For any environment variable with an original value, if the value is changed to a different
 * value (setting Changed_Flag to true) and then changed back to the original value, the
 * Changed_Flag shall be false — identical to the initial state.
 *
 * Property 5: Save payload contains exactly the changed variables
 * For any set of environment variables with mixed Changed_Flag states (some true, some false),
 * the constructed save payload shall include all and only those variables whose Changed_Flag
 * is true; variables with Changed_Flag false shall not appear in the payload.
 *
 * This test exercises the actual page DOM rendered by render(),
 * dispatching real DOM events to trigger change listeners.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import * as fc from 'fast-check';

// Mock the admin-api module before importing env-vars
vi.mock('../../js/admin-api.js', () => ({
  adminApi: {
    getEnvironmentVariables: vi.fn(),
    updateEnvironmentVariables: vi.fn(),
  },
}));

// Mock the api.js module to prevent import errors
vi.mock('../../js/api.js', () => ({
  authenticatedFetch: vi.fn(),
  processResponse: vi.fn(),
  API_BASE_URL: 'http://localhost',
}));

import { adminApi } from '../../js/admin-api.js';
import { render } from '../../js/views/env-vars.js';

/**
 * Helper: create a fresh outlet element attached to the document and render the page into it.
 * @returns {HTMLElement} the rendered admin-page element (used as a query root)
 */
function renderPage() {
  const outlet = document.createElement('div');
  outlet.id = 'app-outlet';
  document.body.appendChild(outlet);
  render(outlet);
  return outlet;
}

/**
 * Known variable names used in the admin panel (from KNOWN_VARIABLES in env-vars.js).
 */
const KNOWN_VARIABLES = [
  'IDLE_TIMEOUT_MINUTES',
  'COGNITO_USER_POOL_NAME',
  'MAX_CONCURRENT_EVALUATIONS',
  'SESSION_SUPERVISOR_MODEL_ID',
  'COACHING_SUPERVISOR_MODEL_ID',
  'EVALUATION_MODEL_ID',
];

/**
 * Helper: Wait for the lightbox to render after the mocked API resolves.
 */
function waitForRender() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

/**
 * Helper: Dispatch an 'input' event on a text input element (mimics user typing).
 */
function dispatchInputEvent(element) {
  element.dispatchEvent(new Event('input', { bubbles: true }));
}

/**
 * Helper: Dispatch a 'change' event on any form control element.
 */
function dispatchChangeEvent(element) {
  element.dispatchEvent(new Event('change', { bubbles: true }));
}

/**
 * Arbitrary for non-empty alphanumeric strings suitable as variable values.
 */
const valueArb = fc.stringOf(fc.char().filter((c) => c >= ' ' && c <= '~'), {
  minLength: 1,
  maxLength: 50,
});

/**
 * Arbitrary for a pair of distinct strings (originalValue, modifiedValue).
 */
const distinctPairArb = fc
  .tuple(valueArb, valueArb)
  .filter(([a, b]) => a !== b);

describe('Property 4: Change tracking round-trip preserves clean state (via lightbox)', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  afterEach(() => {
    // Clean up any remaining rendered pages
    document.body.innerHTML = '';
    vi.clearAllMocks();
  });

  it('changing a text input away then back to original removes admin-form-group--changed class', async () => {
    await fc.assert(
      fc.asyncProperty(distinctPairArb, async ([originalValue, modifiedValue]) => {
        document.body.innerHTML = '';
        // Setup: mock API to return a single text variable
        adminApi.getEnvironmentVariables.mockResolvedValue([
          {
            name: 'IDLE_TIMEOUT_MINUTES',
            value: originalValue,
            description: 'Minutes of inactivity before the ECS evaluation task exits',
            inputType: 'text',
          },
        ]);

        // Render the page
        const overlay = renderPage();
        await waitForRender();

        // Find the rendered input
        const input = overlay.querySelector('input[name="IDLE_TIMEOUT_MINUTES"]');
        const formGroup = input.closest('.admin-form-group');

        // Initially: no changed class
        expect(formGroup.classList.contains('admin-form-group--changed')).toBe(false);

        // Step 1: Change value to something different
        input.value = modifiedValue;
        dispatchInputEvent(input);

        // Should have changed class
        expect(formGroup.classList.contains('admin-form-group--changed')).toBe(true);

        // Step 2: Change back to original
        input.value = originalValue;
        dispatchInputEvent(input);

        // Changed class should be removed — clean state restored
        expect(formGroup.classList.contains('admin-form-group--changed')).toBe(false);

        // Cleanup
        overlay.remove();
      }),
      { numRuns: 20 }
    );
  });

  it('setting a text input to same value as original never adds changed class', async () => {
    await fc.assert(
      fc.asyncProperty(valueArb, async (originalValue) => {
        document.body.innerHTML = '';
        // Setup: mock API to return a single text variable
        adminApi.getEnvironmentVariables.mockResolvedValue([
          {
            name: 'COGNITO_USER_POOL_NAME',
            value: originalValue,
            description: 'Name of the Cognito User Pool for user lookups',
            inputType: 'text',
          },
        ]);

        // Render the page
        const overlay = renderPage();
        await waitForRender();

        // Find the rendered input
        const input = overlay.querySelector('input[name="COGNITO_USER_POOL_NAME"]');
        const formGroup = input.closest('.admin-form-group');

        // Set value to same as original
        input.value = originalValue;
        dispatchInputEvent(input);

        // Should NOT have changed class
        expect(formGroup.classList.contains('admin-form-group--changed')).toBe(false);

        // Cleanup
        overlay.remove();
      }),
      { numRuns: 20 }
    );
  });
});

describe('Property 5: Save payload contains exactly the changed variables (via lightbox)', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  afterEach(() => {
    document.body.innerHTML = '';
    vi.clearAllMocks();
  });

  /**
   * Arbitrary: For each known variable, randomly decide whether to change it.
   * Returns an array of { name, originalValue, newValue, shouldChange }.
   */
  const variableChangesArb = fc
    .tuple(
      // Generate original values for each known text variable
      fc.array(valueArb, { minLength: 2, maxLength: 2 }),
      // Generate new values (potentially different)
      fc.array(valueArb, { minLength: 2, maxLength: 2 }),
      // Boolean flags: should we change each variable?
      fc.array(fc.boolean(), { minLength: 2, maxLength: 2 })
    )
    .map(([originals, newValues, changeFlags]) => {
      const textVars = ['IDLE_TIMEOUT_MINUTES', 'COGNITO_USER_POOL_NAME'];
      return textVars.map((name, i) => ({
        name,
        originalValue: originals[i],
        newValue: newValues[i],
        shouldChange: changeFlags[i],
      }));
    })
    // Ensure at least one changed and one unchanged if possible, or allow any mix
    .filter((vars) => vars.length === 2);

  it('payload sent to updateEnvironmentVariables contains exactly the changed variables', async () => {
    await fc.assert(
      fc.asyncProperty(variableChangesArb, async (variables) => {
        // Reset per-run state: clear DOM and mock call history
        document.body.innerHTML = '';
        adminApi.updateEnvironmentVariables.mockClear();

        // Filter out cases where shouldChange is true but original === new (not really a change)
        const effectiveChanges = variables.map((v) => ({
          ...v,
          isEffectivelyChanged: v.shouldChange && v.originalValue !== v.newValue,
        }));

        // Setup: mock API to return these variables
        adminApi.getEnvironmentVariables.mockResolvedValue(
          variables.map((v) => ({
            name: v.name,
            value: v.originalValue,
            description: `Description for ${v.name}`,
            inputType: 'text',
          }))
        );
        adminApi.updateEnvironmentVariables.mockResolvedValue({
          updatedVars: [],
          deploymentStatus: 'triggered',
          message: 'Saved',
        });

        // Render the page
        const overlay = renderPage();
        await waitForRender();

        // Apply changes
        for (const v of effectiveChanges) {
          const input = overlay.querySelector(`input[name="${v.name}"]`);
          if (v.shouldChange) {
            input.value = v.newValue;
            dispatchInputEvent(input);
          }
          // If not shouldChange, leave at original
        }

        // Click Save
        const saveBtn = overlay.querySelector('.admin-btn--primary');

        // Determine expected payload
        const expectedChangedNames = effectiveChanges
          .filter((v) => v.isEffectivelyChanged)
          .map((v) => v.name);

        if (expectedChangedNames.length === 0) {
          // Save button should be disabled if nothing changed
          expect(saveBtn.disabled).toBe(true);
        } else {
          // Save button should be enabled
          expect(saveBtn.disabled).toBe(false);

          // Click save and check payload
          saveBtn.click();
          await waitForRender();

          // Verify the payload sent to updateEnvironmentVariables
          expect(adminApi.updateEnvironmentVariables).toHaveBeenCalledTimes(1);
          const payload = adminApi.updateEnvironmentVariables.mock.calls[0][0];

          // Payload should include exactly the effectively changed variables
          const payloadKeys = Object.keys(payload).sort();
          expect(payloadKeys).toEqual(expectedChangedNames.sort());

          // Each changed variable should have its new value
          for (const v of effectiveChanges) {
            if (v.isEffectivelyChanged) {
              expect(payload[v.name]).toBe(v.newValue);
            } else {
              expect(payload).not.toHaveProperty(v.name);
            }
          }
        }

        // Cleanup
        overlay.remove();
      }),
      { numRuns: 20 }
    );
  });

  it('payload is empty (save disabled) when all variables revert to original values', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.tuple(valueArb, valueArb).filter(([a, b]) => a !== b),
        async ([originalValue, tempValue]) => {
          document.body.innerHTML = '';
          // Setup: mock API to return a variable
          adminApi.getEnvironmentVariables.mockResolvedValue([
            {
              name: 'IDLE_TIMEOUT_MINUTES',
              value: originalValue,
              description: 'Minutes of inactivity before exit',
              inputType: 'text',
            },
          ]);

          // Render the page
          const overlay = renderPage();
          await waitForRender();
          const input = overlay.querySelector('input[name="IDLE_TIMEOUT_MINUTES"]');
          const saveBtn = overlay.querySelector('.admin-btn--primary');

          // Change to different value
          input.value = tempValue;
          dispatchInputEvent(input);

          // Save should be enabled now
          expect(saveBtn.disabled).toBe(false);

          // Revert to original
          input.value = originalValue;
          dispatchInputEvent(input);

          // Save should be disabled — nothing to save
          expect(saveBtn.disabled).toBe(true);

          // Cleanup
          overlay.remove();
        }
      ),
      { numRuns: 20 }
    );
  });
});

