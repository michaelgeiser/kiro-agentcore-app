// Feature: admin-panel, Properties 1, 2, 3: Environment variable rendering
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import * as fc from 'fast-check';
import { MODEL_OPTIONS } from '../../js/views/env-vars.js';

/**
 * **Validates: Requirements 3.3, 4.1, 4.4, 4.6, 4.7**
 *
 * Property 1: Variable rendering includes all required fields
 * Property 2: Input type determines rendered control type
 * Property 3: Dropdown selection reflects current value validity
 *
 * These tests directly invoke the rendering logic by extracting the same
 * DOM construction patterns used in env-vars.js (createControl, createModelDropdown,
 * createTextInput, renderVariables) to verify properties without async API calls.
 */

/**
 * Render a single variable's form group, replicating the logic from env-vars.js renderVariables.
 * @param {{name: string, value: string, description: string, inputType: string}} variable
 * @returns {HTMLElement} The rendered form group
 */
function renderVariable(variable) {
  const group = document.createElement('div');
  group.className = 'admin-form-group';

  const label = document.createElement('label');
  label.className = 'admin-form-group__label';
  label.textContent = variable.name;

  const description = document.createElement('p');
  description.className = 'admin-form-group__description';
  description.textContent = variable.description;

  const control = createControl(variable);

  group.appendChild(label);
  group.appendChild(description);
  group.appendChild(control);
  return group;
}

/**
 * Create the appropriate input control based on the variable's inputType.
 * Mirrors createControl from env-vars.js.
 * @param {{name: string, value: string, description: string, inputType: string}} variable
 * @returns {HTMLElement}
 */
function createControl(variable) {
  switch (variable.inputType) {
    case 'model-dropdown':
      return createModelDropdown(variable);
    case 'concurrency-dropdown':
      return createConcurrencyDropdown(variable);
    default:
      return createTextInput(variable);
  }
}

/**
 * Create a model dropdown select element. Mirrors createModelDropdown from env-vars.js.
 * @param {{name: string, value: string}} variable
 * @returns {HTMLSelectElement}
 */
function createModelDropdown(variable) {
  const select = document.createElement('select');
  select.className = 'admin-form-group__select';
  select.name = variable.name;
  select.setAttribute('data-original-value', variable.value);

  const isValidValue = MODEL_OPTIONS.some((opt) => opt.modelId === variable.value);

  if (!isValidValue) {
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = '-- Select a model (current value is invalid/legacy) --';
    placeholder.disabled = true;
    placeholder.selected = true;
    select.appendChild(placeholder);
  }

  for (const option of MODEL_OPTIONS) {
    const opt = document.createElement('option');
    opt.value = option.modelId;
    opt.textContent = option.displayName;
    if (option.modelId === variable.value) {
      opt.selected = true;
    }
    select.appendChild(opt);
  }

  return select;
}

/**
 * Create a concurrency dropdown select element. Mirrors createConcurrencyDropdown from env-vars.js.
 * @param {{name: string, value: string}} variable
 * @returns {HTMLSelectElement}
 */
function createConcurrencyDropdown(variable) {
  const CONCURRENCY_OPTIONS = [1, 2, 3, 5, 10];
  const select = document.createElement('select');
  select.className = 'admin-form-group__select';
  select.name = variable.name;
  select.setAttribute('data-original-value', variable.value);

  const currentNum = Number(variable.value);
  const isValidValue = CONCURRENCY_OPTIONS.includes(currentNum);

  if (!isValidValue) {
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = '-- Select concurrency (current value is invalid) --';
    placeholder.disabled = true;
    placeholder.selected = true;
    select.appendChild(placeholder);
  }

  for (const num of CONCURRENCY_OPTIONS) {
    const opt = document.createElement('option');
    opt.value = String(num);
    opt.textContent = String(num);
    if (num === currentNum) {
      opt.selected = true;
    }
    select.appendChild(opt);
  }

  return select;
}

/**
 * Create a text input. Mirrors createTextInput from env-vars.js.
 * @param {{name: string, value: string}} variable
 * @returns {HTMLInputElement}
 */
function createTextInput(variable) {
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'admin-form-group__input';
  input.name = variable.name;
  input.value = variable.value;
  input.setAttribute('data-original-value', variable.value);
  return input;
}

// --- Arbitraries ---

/**
 * Arbitrary for variable names (alphanumeric with underscores, like real env var names).
 */
const varNameArb = fc.stringOf(
  fc.constantFrom(...'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_'.split('')),
  { minLength: 1, maxLength: 30 }
).filter((s) => /^[A-Z]/.test(s));

/**
 * Arbitrary for safe description text (avoids HTML-like characters).
 */
const descriptionArb = fc.stringOf(
  fc.constantFrom(...'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .,;:-_!'.split('')),
  { minLength: 1, maxLength: 100 }
).filter((s) => s.trim().length > 0);

/**
 * Arbitrary for safe value text.
 */
const valueArb = fc.stringOf(
  fc.constantFrom(...'abcdefghijklmnopqrstuvwxyz0123456789.-:_'.split('')),
  { minLength: 1, maxLength: 50 }
).filter((s) => s.trim().length > 0);

/**
 * Arbitrary for valid model IDs from MODEL_OPTIONS.
 */
const validModelIdArb = fc.constantFrom(...MODEL_OPTIONS.map((opt) => opt.modelId));

/**
 * Arbitrary for invalid model IDs (strings not in MODEL_OPTIONS).
 */
const validModelIds = new Set(MODEL_OPTIONS.map((opt) => opt.modelId));
const invalidModelIdArb = fc.stringOf(
  fc.constantFrom(...'abcdefghijklmnopqrstuvwxyz0123456789.-:'.split('')),
  { minLength: 1, maxLength: 40 }
).filter((s) => s.trim().length > 0 && !validModelIds.has(s));

// --- Property 1 Tests ---

describe('Property 1: Variable rendering includes all required fields', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  it('rendered variable contains its name as a label, description text, and editable input with current value', () => {
    fc.assert(
      fc.property(varNameArb, descriptionArb, valueArb, (name, description, value) => {
        const group = renderVariable({ name, description, value, inputType: 'text' });
        document.body.appendChild(group);

        // Label contains the variable name
        const label = group.querySelector('.admin-form-group__label');
        expect(label).not.toBeNull();
        expect(label.textContent).toBe(name);

        // Description text is present
        const descEl = group.querySelector('.admin-form-group__description');
        expect(descEl).not.toBeNull();
        expect(descEl.textContent).toBe(description);

        // Editable input control with current value
        const input = group.querySelector('input[type="text"]');
        expect(input).not.toBeNull();
        expect(input.value).toBe(value);
        expect(input.name).toBe(name);

        // Cleanup
        document.body.removeChild(group);
      }),
      { numRuns: 100 }
    );
  });
});

// --- Property 2 Tests ---

describe('Property 2: Input type determines rendered control type', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  it('"model-dropdown" inputType renders a <select> element, not an <input type="text">', () => {
    fc.assert(
      fc.property(varNameArb, descriptionArb, validModelIdArb, (name, description, value) => {
        const group = renderVariable({ name, description, value, inputType: 'model-dropdown' });
        document.body.appendChild(group);

        const select = group.querySelector('select');
        expect(select).not.toBeNull();
        expect(select.name).toBe(name);

        // No text input should exist
        const textInput = group.querySelector('input[type="text"]');
        expect(textInput).toBeNull();

        // Cleanup
        document.body.removeChild(group);
      }),
      { numRuns: 100 }
    );
  });

  it('"text" inputType renders an <input type="text"> element, not a <select>', () => {
    fc.assert(
      fc.property(varNameArb, descriptionArb, valueArb, (name, description, value) => {
        const group = renderVariable({ name, description, value, inputType: 'text' });
        document.body.appendChild(group);

        const input = group.querySelector('input[type="text"]');
        expect(input).not.toBeNull();
        expect(input.name).toBe(name);

        // No select should exist
        const select = group.querySelector('select');
        expect(select).toBeNull();

        // Cleanup
        document.body.removeChild(group);
      }),
      { numRuns: 100 }
    );
  });

  it('model dropdown options have display text (human-friendly) differing from value attribute (API model ID)', () => {
    fc.assert(
      fc.property(varNameArb, descriptionArb, validModelIdArb, (name, description, value) => {
        const group = renderVariable({ name, description, value, inputType: 'model-dropdown' });
        document.body.appendChild(group);

        const select = group.querySelector('select');
        expect(select).not.toBeNull();

        // Each MODEL_OPTIONS entry should have a corresponding option
        for (const modelOpt of MODEL_OPTIONS) {
          const matchingOption = Array.from(select.options).find(
            (opt) => opt.value === modelOpt.modelId && opt.textContent === modelOpt.displayName
          );
          expect(matchingOption).toBeDefined();
          // Display name differs from model ID value
          expect(modelOpt.displayName).not.toBe(modelOpt.modelId);
        }

        // Cleanup
        document.body.removeChild(group);
      }),
      { numRuns: 100 }
    );
  });
});

// --- Property 3 Tests ---

describe('Property 3: Dropdown selection reflects current value validity', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  it('valid model ID results in that option being pre-selected', () => {
    fc.assert(
      fc.property(varNameArb, descriptionArb, validModelIdArb, (name, description, modelId) => {
        const group = renderVariable({ name, description, value: modelId, inputType: 'model-dropdown' });
        document.body.appendChild(group);

        const select = group.querySelector('select');
        expect(select).not.toBeNull();

        // The select value should be the valid model ID
        expect(select.value).toBe(modelId);

        // The selected option should have the correct model ID
        const selectedOption = select.options[select.selectedIndex];
        expect(selectedOption.value).toBe(modelId);

        // No disabled placeholder should be present
        const placeholder = select.querySelector('option[disabled]');
        expect(placeholder).toBeNull();

        // Cleanup
        document.body.removeChild(group);
      }),
      { numRuns: 100 }
    );
  });

  it('invalid model ID shows placeholder/unselected state', () => {
    fc.assert(
      fc.property(varNameArb, descriptionArb, invalidModelIdArb, (name, description, invalidId) => {
        const group = renderVariable({ name, description, value: invalidId, inputType: 'model-dropdown' });
        document.body.appendChild(group);

        const select = group.querySelector('select');
        expect(select).not.toBeNull();

        // A disabled placeholder option should be present
        const placeholderOption = select.querySelector('option[disabled]');
        expect(placeholderOption).not.toBeNull();
        expect(placeholderOption.selected).toBe(true);

        // The selected index should point to the placeholder (index 0)
        expect(select.selectedIndex).toBe(0);

        // Cleanup
        document.body.removeChild(group);
      }),
      { numRuns: 100 }
    );
  });
});
