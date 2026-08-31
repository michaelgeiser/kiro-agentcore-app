/**
 * Unit tests for the Environment Variables administration page.
 * Tests rendering, control types, dropdown population, and admin page structure.
 *
 * Requirements: 3.1, 3.2, 3.3, 3.6, 3.7, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.9
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mock the admin-api module
vi.mock('../../js/admin-api.js', () => ({
  adminApi: {
    getEnvironmentVariables: vi.fn(),
  },
}));

import { render, MODEL_OPTIONS, CONCURRENCY_OPTIONS } from '../../js/views/env-vars.js';
import { adminApi } from '../../js/admin-api.js';

/**
 * Create a fresh outlet element attached to the document for rendering.
 * @returns {HTMLElement}
 */
function createOutlet() {
  const outlet = document.createElement('div');
  outlet.id = 'app-outlet';
  document.body.appendChild(outlet);
  return outlet;
}

describe('Environment Variables Page', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    vi.clearAllMocks();
  });

  afterEach(() => {
    document.body.innerHTML = '';
  });

  describe('MODEL_OPTIONS', () => {
    it('contains Amazon Nova and Anthropic Claude models', () => {
      const novaModels = MODEL_OPTIONS.filter((m) => m.displayName.includes('Nova'));
      const claudeModels = MODEL_OPTIONS.filter((m) => m.displayName.includes('Claude'));
      expect(novaModels.length).toBeGreaterThan(0);
      expect(claudeModels.length).toBeGreaterThan(0);
      expect(novaModels.length + claudeModels.length).toBe(MODEL_OPTIONS.length);
    });

    it('includes CRI and Single Region variants', () => {
      const criModels = MODEL_OPTIONS.filter((m) => m.displayName.includes('CRI'));
      const singleRegionModels = MODEL_OPTIONS.filter((m) => m.displayName.includes('Single Region'));
      expect(criModels.length).toBeGreaterThan(0);
      expect(singleRegionModels.length).toBeGreaterThan(0);
    });

    it('each option has displayName and modelId', () => {
      for (const option of MODEL_OPTIONS) {
        expect(option.displayName).toBeTruthy();
        expect(option.modelId).toBeTruthy();
      }
    });
  });

  describe('CONCURRENCY_OPTIONS', () => {
    it('contains [1, 2, 3, 5, 10]', () => {
      expect(CONCURRENCY_OPTIONS).toEqual([1, 2, 3, 5, 10]);
    });
  });

  describe('render', () => {
    it('renders an admin page into the outlet', async () => {
      adminApi.getEnvironmentVariables.mockResolvedValue([]);

      render(createOutlet());

      expect(document.querySelector('.admin-page')).not.toBeNull();
    });

    it('renders the admin context bar', async () => {
      adminApi.getEnvironmentVariables.mockResolvedValue([]);

      render(createOutlet());

      const contextBar = document.querySelector('.admin-context-bar');
      expect(contextBar).not.toBeNull();
      expect(contextBar.textContent).toContain('Administration Mode');
    });

    it('renders the page header with title "Environment Variables"', async () => {
      adminApi.getEnvironmentVariables.mockResolvedValue([]);

      render(createOutlet());

      const title = document.querySelector('.admin-page-header__title');
      expect(title.textContent).toBe('Environment Variables');
    });

    it('renders the red "Admin" badge', async () => {
      adminApi.getEnvironmentVariables.mockResolvedValue([]);

      render(createOutlet());

      const badge = document.querySelector('.admin-page-header__badge');
      expect(badge).not.toBeNull();
      expect(badge.textContent).toBe('Admin');
    });

    it('renders a Save Changes button (initially disabled)', async () => {
      adminApi.getEnvironmentVariables.mockResolvedValue([]);

      render(createOutlet());

      const saveBtn = document.querySelector('.admin-btn--primary');
      expect(saveBtn).not.toBeNull();
      expect(saveBtn.textContent).toBe('Save Changes');
      expect(saveBtn.disabled).toBe(true);
    });

    it('renders each variable with name label and description', async () => {
      const variables = [
        { name: 'IDLE_TIMEOUT_MINUTES', value: '30', description: 'Minutes of inactivity', inputType: 'text' },
        { name: 'COGNITO_USER_POOL_NAME', value: 'my-pool', description: 'Name of the Cognito User Pool', inputType: 'text' },
      ];
      adminApi.getEnvironmentVariables.mockResolvedValue(variables);

      render(createOutlet());
      await vi.waitFor(() => {
        expect(document.querySelectorAll('.admin-form-group').length).toBe(2);
      });

      const labels = document.querySelectorAll('.admin-form-group__label');
      expect(labels[0].textContent).toBe('IDLE_TIMEOUT_MINUTES');
      expect(labels[1].textContent).toBe('COGNITO_USER_POOL_NAME');

      const descriptions = document.querySelectorAll('.admin-form-group__description');
      expect(descriptions[0].textContent).toBe('Minutes of inactivity');
      expect(descriptions[1].textContent).toBe('Name of the Cognito User Pool');
    });

    it('renders text input for inputType "text"', async () => {
      const variables = [
        { name: 'IDLE_TIMEOUT_MINUTES', value: '30', description: 'Timeout', inputType: 'text' },
      ];
      adminApi.getEnvironmentVariables.mockResolvedValue(variables);

      render(createOutlet());
      await vi.waitFor(() => {
        expect(document.querySelector('.admin-form-group__input')).not.toBeNull();
      });

      const input = document.querySelector('.admin-form-group__input');
      expect(input.tagName).toBe('INPUT');
      expect(input.type).toBe('text');
      expect(input.value).toBe('30');
    });

    it('renders select dropdown for inputType "model-dropdown"', async () => {
      const variables = [
        { name: 'SESSION_SUPERVISOR_MODEL_ID', value: 'us.anthropic.claude-sonnet-4-6', description: 'Model', inputType: 'model-dropdown' },
      ];
      adminApi.getEnvironmentVariables.mockResolvedValue(variables);

      render(createOutlet());
      await vi.waitFor(() => {
        expect(document.querySelector('.admin-form-group__select')).not.toBeNull();
      });

      const select = document.querySelector('.admin-form-group__select');
      expect(select.tagName).toBe('SELECT');
      // Should have all MODEL_OPTIONS as options
      const options = select.querySelectorAll('option');
      expect(options.length).toBe(MODEL_OPTIONS.length);
    });

    it('pre-selects matching model in dropdown', async () => {
      const variables = [
        { name: 'SESSION_SUPERVISOR_MODEL_ID', value: 'us.anthropic.claude-sonnet-4-6', description: 'Model', inputType: 'model-dropdown' },
      ];
      adminApi.getEnvironmentVariables.mockResolvedValue(variables);

      render(createOutlet());
      await vi.waitFor(() => {
        expect(document.querySelector('.admin-form-group__select')).not.toBeNull();
      });

      const select = document.querySelector('.admin-form-group__select');
      expect(select.value).toBe('us.anthropic.claude-sonnet-4-6');
    });

    it('shows placeholder for invalid/legacy model value', async () => {
      const variables = [
        { name: 'SESSION_SUPERVISOR_MODEL_ID', value: 'some-legacy-model-v0:0', description: 'Model', inputType: 'model-dropdown' },
      ];
      adminApi.getEnvironmentVariables.mockResolvedValue(variables);

      render(createOutlet());
      await vi.waitFor(() => {
        expect(document.querySelector('.admin-form-group__select')).not.toBeNull();
      });

      const select = document.querySelector('.admin-form-group__select');
      const placeholderOption = select.querySelector('option[disabled]');
      expect(placeholderOption).not.toBeNull();
      expect(placeholderOption.selected).toBe(true);
      expect(placeholderOption.textContent).toContain('invalid');
    });

    it('renders concurrency dropdown with options [1, 2, 3, 5, 10]', async () => {
      const variables = [
        { name: 'MAX_CONCURRENT_EVALUATIONS', value: '5', description: 'Max concurrency', inputType: 'concurrency-dropdown' },
      ];
      adminApi.getEnvironmentVariables.mockResolvedValue(variables);

      render(createOutlet());
      await vi.waitFor(() => {
        expect(document.querySelector('.admin-form-group__select')).not.toBeNull();
      });

      const select = document.querySelector('.admin-form-group__select');
      const options = select.querySelectorAll('option');
      expect(options.length).toBe(5);
      const values = Array.from(options).map((o) => o.value);
      expect(values).toEqual(['1', '2', '3', '5', '10']);
    });

    it('pre-selects matching concurrency value', async () => {
      const variables = [
        { name: 'MAX_CONCURRENT_EVALUATIONS', value: '3', description: 'Max concurrency', inputType: 'concurrency-dropdown' },
      ];
      adminApi.getEnvironmentVariables.mockResolvedValue(variables);

      render(createOutlet());
      await vi.waitFor(() => {
        expect(document.querySelector('.admin-form-group__select')).not.toBeNull();
      });

      const select = document.querySelector('.admin-form-group__select');
      expect(select.value).toBe('3');
    });

    it('shows error message when API call fails', async () => {
      adminApi.getEnvironmentVariables.mockRejectedValue(new Error('Network error'));

      render(createOutlet());
      await vi.waitFor(() => {
        expect(document.querySelector('.admin-message--error')).not.toBeNull();
      });

      const errorMsg = document.querySelector('.admin-message--error');
      expect(errorMsg.textContent).toContain('Network error');
    });
  });
});
