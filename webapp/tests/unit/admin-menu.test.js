/**
 * Unit tests for the Admin Hover Menu component.
 * Tests rendering, hover show/hide with 300ms delay, and menu item behavior.
 *
 * Requirements: 1.1, 1.2, 1.3, 1.4, 1.5
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { renderAdminMenu } from '../../js/views/admin-menu.js';

describe('Admin Hover Menu', () => {
  let navContainer;

  beforeEach(() => {
    navContainer = document.createElement('div');
    document.body.appendChild(navContainer);
    vi.useFakeTimers();
  });

  afterEach(() => {
    document.body.removeChild(navContainer);
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  describe('Rendering (Requirement 1.1)', () => {
    it('renders an "Administration" trigger button styled with admin-menu__trigger class', () => {
      renderAdminMenu(navContainer);

      const trigger = navContainer.querySelector('.admin-menu__trigger');
      expect(trigger).not.toBeNull();
      expect(trigger.textContent).toBe('Administration');
      expect(trigger.tagName).toBe('BUTTON');
    });

    it('wraps the menu in a container with admin-menu class', () => {
      renderAdminMenu(navContainer);

      const container = navContainer.querySelector('.admin-menu');
      expect(container).not.toBeNull();
    });

    it('creates a dropdown with admin-menu__dropdown class', () => {
      renderAdminMenu(navContainer);

      const dropdown = navContainer.querySelector('.admin-menu__dropdown');
      expect(dropdown).not.toBeNull();
    });

    it('trigger has aria-haspopup and aria-expanded attributes', () => {
      renderAdminMenu(navContainer);

      const trigger = navContainer.querySelector('.admin-menu__trigger');
      expect(trigger.getAttribute('aria-haspopup')).toBe('true');
      expect(trigger.getAttribute('aria-expanded')).toBe('false');
    });
  });

  describe('Dropdown items (Requirement 1.3)', () => {
    it('contains "Environment Variables" menu item as a link to #env-vars', () => {
      renderAdminMenu(navContainer);

      const items = navContainer.querySelectorAll('.admin-menu__item');
      const envVarsItem = Array.from(items).find(
        (item) => item.textContent === 'Environment Variables'
      );
      expect(envVarsItem).not.toBeUndefined();
      expect(envVarsItem.tagName).toBe('A');
      expect(envVarsItem.getAttribute('href')).toBe('#env-vars');
    });

    it('contains "Feature Flags" menu item as a link to #feature-flags', () => {
      renderAdminMenu(navContainer);

      const items = navContainer.querySelectorAll('.admin-menu__item');
      const featureFlagsItem = Array.from(items).find(
        (item) => item.textContent === 'Feature Flags'
      );
      expect(featureFlagsItem).not.toBeUndefined();
      expect(featureFlagsItem.tagName).toBe('A');
      expect(featureFlagsItem.getAttribute('href')).toBe('#feature-flags');
    });

    it('"Environment Variables" item hides the dropdown on click', () => {
      renderAdminMenu(navContainer);

      const container = navContainer.querySelector('.admin-menu');
      const dropdown = navContainer.querySelector('.admin-menu__dropdown');
      const items = navContainer.querySelectorAll('.admin-menu__item');
      const envVarsItem = Array.from(items).find(
        (item) => item.textContent === 'Environment Variables'
      );

      // Show the dropdown, then click the item
      container.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
      envVarsItem.click();

      expect(dropdown.classList.contains('admin-menu__dropdown--visible')).toBe(false);
    });
  });

  describe('Hover show/hide with 300ms delay (Requirements 1.3, 1.4)', () => {
    it('shows dropdown on mouseenter of the menu container', () => {
      renderAdminMenu(navContainer);

      const container = navContainer.querySelector('.admin-menu');
      const dropdown = navContainer.querySelector('.admin-menu__dropdown');

      container.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));

      expect(dropdown.classList.contains('admin-menu__dropdown--visible')).toBe(true);
    });

    it('sets aria-expanded to true on mouseenter', () => {
      renderAdminMenu(navContainer);

      const container = navContainer.querySelector('.admin-menu');
      const trigger = navContainer.querySelector('.admin-menu__trigger');

      container.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));

      expect(trigger.getAttribute('aria-expanded')).toBe('true');
    });

    it('does not immediately hide dropdown on mouseleave', () => {
      renderAdminMenu(navContainer);

      const container = navContainer.querySelector('.admin-menu');
      const dropdown = navContainer.querySelector('.admin-menu__dropdown');

      // Show
      container.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
      // Leave
      container.dispatchEvent(new MouseEvent('mouseleave', { bubbles: true }));

      // Should still be visible immediately after leave
      expect(dropdown.classList.contains('admin-menu__dropdown--visible')).toBe(true);
    });

    it('hides dropdown after 300ms delay on mouseleave', () => {
      renderAdminMenu(navContainer);

      const container = navContainer.querySelector('.admin-menu');
      const dropdown = navContainer.querySelector('.admin-menu__dropdown');

      // Show
      container.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
      // Leave
      container.dispatchEvent(new MouseEvent('mouseleave', { bubbles: true }));

      // Advance time by 300ms
      vi.advanceTimersByTime(300);

      expect(dropdown.classList.contains('admin-menu__dropdown--visible')).toBe(false);
    });

    it('cancels hide timeout if mouse re-enters before 300ms', () => {
      renderAdminMenu(navContainer);

      const container = navContainer.querySelector('.admin-menu');
      const dropdown = navContainer.querySelector('.admin-menu__dropdown');

      // Show
      container.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
      // Leave
      container.dispatchEvent(new MouseEvent('mouseleave', { bubbles: true }));
      // Re-enter before 300ms
      vi.advanceTimersByTime(150);
      container.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
      // Advance past the original 300ms
      vi.advanceTimersByTime(200);

      // Should still be visible because re-enter cancelled the hide
      expect(dropdown.classList.contains('admin-menu__dropdown--visible')).toBe(true);
    });

    it('sets aria-expanded to false after hide delay completes', () => {
      renderAdminMenu(navContainer);

      const container = navContainer.querySelector('.admin-menu');
      const trigger = navContainer.querySelector('.admin-menu__trigger');

      container.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
      container.dispatchEvent(new MouseEvent('mouseleave', { bubbles: true }));

      vi.advanceTimersByTime(300);

      expect(trigger.getAttribute('aria-expanded')).toBe('false');
    });
  });

  describe('Menu appended to navContainer', () => {
    it('appends the admin menu (wrapped in an <li>) as a child of navContainer', () => {
      renderAdminMenu(navContainer);

      expect(navContainer.children.length).toBe(1);
      expect(navContainer.firstChild.tagName).toBe('LI');
      expect(navContainer.querySelector('.admin-menu')).not.toBeNull();
    });
  });
});
