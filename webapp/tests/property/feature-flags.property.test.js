// Feature: admin-panel, Properties 6 & 7: Feature flag rendering and toggle behavior
import { describe, it, expect, beforeEach, vi } from 'vitest';
import * as fc from 'fast-check';

/**
 * **Validates: Requirements 7.3, 7.7**
 *
 * Property 6: Feature flag rendering includes all required fields
 * For any feature flag object with a non-empty name, description, and boolean state,
 * the rendered output contains the flag's parameter name, description text, and
 * a toggle switch reflecting the current boolean state.
 *
 * Property 7: Failed toggle reverts to original state
 * For any feature flag in any boolean state, if the user toggles it and the backend
 * API request fails, the toggle switch reverts to the original state prior to the
 * toggle attempt.
 */

// Mock the admin API module
vi.mock('../../js/admin-api.js', () => ({
  adminApi: {
    getFeatureFlags: vi.fn(),
    updateFeatureFlag: vi.fn(),
  },
}));

import { adminApi } from '../../js/admin-api.js';
import { render } from '../../js/views/feature-flags.js';

/**
 * Arbitrary for a feature flag object with non-empty name, description, and boolean state.
 * Uses safe characters to avoid HTML entity issues in DOM text matching.
 */
const featureFlagArb = fc.record({
  name: fc.stringOf(
    fc.constantFrom(...'abcdefghijklmnopqrstuvwxyz-0123456789'.split('')),
    { minLength: 1, maxLength: 30 }
  ).filter((s) => s.trim().length > 0),
  description: fc.stringOf(
    fc.constantFrom(...'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -.'.split('')),
    { minLength: 1, maxLength: 100 }
  ).filter((s) => s.trim().length > 0),
  enabled: fc.boolean(),
});

/**
 * Helper: flush pending promises to allow async operations to resolve.
 */
function flushPromises() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

describe('Property 6: Feature flag rendering includes all required fields', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('rendered output contains the flag name', async () => {
    await fc.assert(
      fc.asyncProperty(featureFlagArb, async (flag) => {
        adminApi.getFeatureFlags.mockResolvedValue([flag]);

        const outlet = document.createElement('div');
        render(outlet);
        await vi.waitFor(() => {
          if (outlet.textContent.includes('Loading')) throw new Error('Still loading');
        });

        const textContent = outlet.textContent;
        expect(textContent).toContain(flag.name);
      }),
      { numRuns: 20 }
    );
  });

  it('rendered output contains the flag description', async () => {
    await fc.assert(
      fc.asyncProperty(featureFlagArb, async (flag) => {
        adminApi.getFeatureFlags.mockResolvedValue([flag]);

        const outlet = document.createElement('div');
        render(outlet);
        await vi.waitFor(() => {
          if (outlet.textContent.includes('Loading')) throw new Error('Still loading');
        });

        const textContent = outlet.textContent;
        expect(textContent).toContain(flag.description);
      }),
      { numRuns: 20 }
    );
  });

  it('toggle has toggle-switch--on class when enabled is true, absent when false', async () => {
    await fc.assert(
      fc.asyncProperty(featureFlagArb, async (flag) => {
        adminApi.getFeatureFlags.mockResolvedValue([flag]);

        const outlet = document.createElement('div');
        render(outlet);
        await vi.waitFor(() => {
          if (outlet.textContent.includes('Loading')) throw new Error('Still loading');
        });

        const toggleSwitch = outlet.querySelector('.toggle-switch');
        expect(toggleSwitch).not.toBeNull();

        if (flag.enabled) {
          expect(toggleSwitch.classList.contains('toggle-switch--on')).toBe(true);
        } else {
          expect(toggleSwitch.classList.contains('toggle-switch--on')).toBe(false);
        }
      }),
      { numRuns: 20 }
    );
  });

  it('toggle checkbox reflects the enabled boolean state', async () => {
    await fc.assert(
      fc.asyncProperty(featureFlagArb, async (flag) => {
        adminApi.getFeatureFlags.mockResolvedValue([flag]);

        const outlet = document.createElement('div');
        render(outlet);
        await vi.waitFor(() => {
          if (outlet.textContent.includes('Loading')) throw new Error('Still loading');
        });

        const checkbox = outlet.querySelector('.toggle-switch__input');
        expect(checkbox).not.toBeNull();
        expect(checkbox.checked).toBe(flag.enabled);
      }),
      { numRuns: 20 }
    );
  });
});

describe('Property 7: Failed toggle reverts to original state', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('toggle reverts to original state when API call fails', async () => {
    await fc.assert(
      fc.asyncProperty(featureFlagArb, async (flag) => {
        adminApi.getFeatureFlags.mockResolvedValue([flag]);
        adminApi.updateFeatureFlag.mockRejectedValue(new Error('API failure'));

        const outlet = document.createElement('div');
        render(outlet);
        await vi.waitFor(() => {
          if (outlet.textContent.includes('Loading')) throw new Error('Still loading');
        });

        // Find the toggle and checkbox
        const toggleSwitch = outlet.querySelector('.toggle-switch');
        const checkbox = outlet.querySelector('.toggle-switch__input');
        expect(toggleSwitch).not.toBeNull();
        expect(checkbox).not.toBeNull();

        // Verify initial state
        expect(checkbox.checked).toBe(flag.enabled);

        // Simulate clicking the toggle: change the checkbox and dispatch event
        checkbox.checked = !flag.enabled;
        checkbox.dispatchEvent(new Event('change', { bubbles: true }));

        // Wait for the failed API call to resolve and revert to happen
        await vi.waitFor(() => {
          if (checkbox.checked !== flag.enabled) throw new Error('Not reverted yet');
        });

        // Verify the toggle reverts to the original state
        expect(checkbox.checked).toBe(flag.enabled);

        // Verify the CSS class matches the original state
        if (flag.enabled) {
          expect(toggleSwitch.classList.contains('toggle-switch--on')).toBe(true);
        } else {
          expect(toggleSwitch.classList.contains('toggle-switch--on')).toBe(false);
        }
      }),
      { numRuns: 20 }
    );
  });
});
