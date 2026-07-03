// Feature: admin-panel, Properties 4 & 5: Change tracking
import { describe, it, expect, beforeEach } from 'vitest';
import * as fc from 'fast-check';

/**
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
 */

/**
 * Simulate the onControlChange logic from env-vars.js.
 * Compares current value to data-original-value, updates changedVars set and CSS class.
 * @param {HTMLInputElement} control
 * @param {Set<string>} changedVars
 */
function onControlChange(control, changedVars) {
  const originalValue = control.getAttribute('data-original-value');
  const currentValue = control.value;
  const varName = control.name;
  const formGroup = control.closest('.admin-form-group');

  if (currentValue !== originalValue) {
    changedVars.add(varName);
    if (formGroup) {
      formGroup.classList.add('admin-form-group--changed');
    }
  } else {
    changedVars.delete(varName);
    if (formGroup) {
      formGroup.classList.remove('admin-form-group--changed');
    }
  }
}

/**
 * Construct save payload from changedVars set — mirrors handleSave in env-vars.js.
 * @param {HTMLElement} body - Container with input controls
 * @param {Set<string>} changedVars - Set of changed variable names
 * @returns {Object<string, string>} payload
 */
function constructPayload(body, changedVars) {
  const payload = {};
  for (const varName of changedVars) {
    const control = body.querySelector(`[name="${varName}"]`);
    if (control) {
      payload[varName] = control.value;
    }
  }
  return payload;
}

/**
 * Create a form group element with an input control, mirroring the env-vars.js DOM structure.
 * @param {string} name - Variable name
 * @param {string} originalValue - Original value stored in data-original-value
 * @returns {{group: HTMLElement, control: HTMLInputElement}}
 */
function createFormGroup(name, originalValue) {
  const group = document.createElement('div');
  group.className = 'admin-form-group';

  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'admin-form-group__input';
  input.name = name;
  input.value = originalValue;
  input.setAttribute('data-original-value', originalValue);

  group.appendChild(input);
  return { group, control: input };
}

/**
 * Arbitrary for non-empty strings suitable as variable values.
 * Avoids empty strings so we can guarantee original !== modified.
 */
const nonEmptyStringArb = fc.string({ minLength: 1, maxLength: 100 });

/**
 * Arbitrary for a pair of distinct strings (originalValue, modifiedValue).
 */
const distinctPairArb = fc
  .tuple(nonEmptyStringArb, nonEmptyStringArb)
  .filter(([a, b]) => a !== b);

/**
 * Arbitrary for a valid variable name (alphanumeric + underscores, non-empty).
 */
const varNameArb = fc.stringMatching(/^[A-Z][A-Z0-9_]{0,29}$/);

describe('Property 4: Change tracking round-trip preserves clean state', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  it('changing value away then back to original results in Changed_Flag false', () => {
    fc.assert(
      fc.property(varNameArb, distinctPairArb, (varName, [originalValue, modifiedValue]) => {
        const changedVars = new Set();
        const { group, control } = createFormGroup(varName, originalValue);
        document.body.appendChild(group);

        // Initial state: no change flag
        expect(changedVars.has(varName)).toBe(false);
        expect(group.classList.contains('admin-form-group--changed')).toBe(false);

        // Step 1: Change to a different value
        control.value = modifiedValue;
        onControlChange(control, changedVars);

        // Changed_Flag should be true
        expect(changedVars.has(varName)).toBe(true);
        expect(group.classList.contains('admin-form-group--changed')).toBe(true);

        // Step 2: Change back to original
        control.value = originalValue;
        onControlChange(control, changedVars);

        // Changed_Flag should be false — clean state restored
        expect(changedVars.has(varName)).toBe(false);
        expect(group.classList.contains('admin-form-group--changed')).toBe(false);

        // Cleanup
        document.body.removeChild(group);
      }),
      { numRuns: 100 }
    );
  });

  it('changing value to same as original never sets Changed_Flag', () => {
    fc.assert(
      fc.property(varNameArb, nonEmptyStringArb, (varName, originalValue) => {
        const changedVars = new Set();
        const { group, control } = createFormGroup(varName, originalValue);
        document.body.appendChild(group);

        // Set value to same as original
        control.value = originalValue;
        onControlChange(control, changedVars);

        // Changed_Flag should remain false
        expect(changedVars.has(varName)).toBe(false);
        expect(group.classList.contains('admin-form-group--changed')).toBe(false);

        // Cleanup
        document.body.removeChild(group);
      }),
      { numRuns: 100 }
    );
  });
});

describe('Property 5: Save payload contains exactly the changed variables', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  /**
   * Arbitrary for a list of variables, each with name, originalValue, and currentValue.
   * Some will have currentValue !== originalValue (changed), some will be the same (unchanged).
   */
  const variableSetArb = fc
    .array(
      fc.record({
        name: varNameArb,
        originalValue: nonEmptyStringArb,
        currentValue: nonEmptyStringArb,
      }),
      { minLength: 1, maxLength: 10 }
    )
    .map((vars) => {
      // Ensure unique names
      const seen = new Set();
      return vars.filter((v) => {
        if (seen.has(v.name)) return false;
        seen.add(v.name);
        return true;
      });
    })
    .filter((vars) => vars.length >= 1);

  it('payload includes all and only variables whose Changed_Flag is true', () => {
    fc.assert(
      fc.property(variableSetArb, (variables) => {
        const body = document.createElement('div');
        const changedVars = new Set();

        // Build DOM and simulate changes
        for (const { name, originalValue, currentValue } of variables) {
          const { group, control } = createFormGroup(name, originalValue);
          body.appendChild(group);

          // Simulate setting the current value
          control.value = currentValue;
          onControlChange(control, changedVars);
        }

        // Construct payload
        const payload = constructPayload(body, changedVars);

        // Determine expected changed variables
        const expectedChanged = variables.filter((v) => v.currentValue !== v.originalValue);
        const expectedUnchanged = variables.filter((v) => v.currentValue === v.originalValue);

        // Payload should contain exactly the changed variables
        expect(Object.keys(payload).length).toBe(expectedChanged.length);

        for (const { name, currentValue } of expectedChanged) {
          expect(payload).toHaveProperty(name);
          expect(payload[name]).toBe(currentValue);
        }

        // Payload should NOT contain unchanged variables
        for (const { name } of expectedUnchanged) {
          expect(payload).not.toHaveProperty(name);
        }
      }),
      { numRuns: 100 }
    );
  });

  it('payload is empty when all variables revert to original values', () => {
    fc.assert(
      fc.property(variableSetArb, (variables) => {
        const body = document.createElement('div');
        const changedVars = new Set();

        // Build DOM, change values, then revert all back
        for (const { name, originalValue, currentValue } of variables) {
          const { group, control } = createFormGroup(name, originalValue);
          body.appendChild(group);

          // Change to different value first
          control.value = currentValue;
          onControlChange(control, changedVars);

          // Revert to original
          control.value = originalValue;
          onControlChange(control, changedVars);
        }

        // Construct payload
        const payload = constructPayload(body, changedVars);

        // All reverted, so payload should be empty
        expect(Object.keys(payload).length).toBe(0);
      }),
      { numRuns: 100 }
    );
  });
});
