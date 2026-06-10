import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { Router } from '../../js/router.js';

describe('Router', () => {
  let outlet;

  beforeEach(() => {
    outlet = document.createElement('div');
    outlet.id = 'app-outlet';
    document.body.appendChild(outlet);
    window.location.hash = '';
  });

  afterEach(() => {
    document.body.removeChild(outlet);
    window.location.hash = '';
  });

  describe('route registration and initial render', () => {
    it('renders the default upload route when hash is empty', () => {
      const uploadView = vi.fn((el) => { el.textContent = 'Upload Page'; });
      const listView = vi.fn((el) => { el.textContent = 'List Page'; });

      const router = new Router({ upload: uploadView, list: listView }, outlet);
      router.start();

      expect(uploadView).toHaveBeenCalledWith(outlet);
      expect(listView).not.toHaveBeenCalled();
    });

    it('renders the matching route when hash is set before start', () => {
      window.location.hash = 'list';

      const uploadView = vi.fn();
      const listView = vi.fn((el) => { el.textContent = 'List Page'; });

      const router = new Router({ upload: uploadView, list: listView }, outlet);
      router.start();

      expect(listView).toHaveBeenCalledWith(outlet);
      expect(uploadView).not.toHaveBeenCalled();
    });

    it('stores routes and outlet in the instance', () => {
      const routes = { upload: vi.fn(), list: vi.fn() };
      const router = new Router(routes, outlet);

      expect(router.routes).toBe(routes);
      expect(router.outlet).toBe(outlet);
    });
  });

  describe('hashchange event triggers correct view', () => {
    it('renders the new route when hash changes', async () => {
      const uploadView = vi.fn((el) => { el.textContent = 'Upload Page'; });
      const listView = vi.fn((el) => { el.textContent = 'List Page'; });

      const router = new Router({ upload: uploadView, list: listView }, outlet);
      router.start();

      // Reset mocks after initial render
      uploadView.mockClear();
      listView.mockClear();

      // Simulate hash change
      window.location.hash = 'list';
      window.dispatchEvent(new HashChangeEvent('hashchange'));

      expect(listView).toHaveBeenCalledWith(outlet);
      expect(uploadView).not.toHaveBeenCalled();
    });

    it('renders upload view when hash changes to upload', () => {
      window.location.hash = 'list';

      const uploadView = vi.fn((el) => { el.textContent = 'Upload Page'; });
      const listView = vi.fn((el) => { el.textContent = 'List Page'; });

      const router = new Router({ upload: uploadView, list: listView }, outlet);
      router.start();

      uploadView.mockClear();
      listView.mockClear();

      window.location.hash = 'upload';
      window.dispatchEvent(new HashChangeEvent('hashchange'));

      expect(uploadView).toHaveBeenCalledWith(outlet);
      expect(listView).not.toHaveBeenCalled();
    });
  });

  describe('programmatic navigation', () => {
    it('navigate() sets the window location hash', () => {
      const uploadView = vi.fn();
      const listView = vi.fn();

      const router = new Router({ upload: uploadView, list: listView }, outlet);
      router.start();

      router.navigate('list');

      expect(window.location.hash).toBe('#list');
    });

    it('navigate() triggers a hashchange that renders the target view', () => {
      const uploadView = vi.fn();
      const listView = vi.fn();

      const router = new Router({ upload: uploadView, list: listView }, outlet);
      router.start();

      uploadView.mockClear();
      listView.mockClear();

      router.navigate('list');
      window.dispatchEvent(new HashChangeEvent('hashchange'));

      expect(listView).toHaveBeenCalledWith(outlet);
    });
  });

  describe('unknown route fallback behavior', () => {
    it('renders upload view for unknown hash routes', () => {
      window.location.hash = 'nonexistent';

      const uploadView = vi.fn((el) => { el.textContent = 'Upload Page'; });
      const listView = vi.fn();

      const router = new Router({ upload: uploadView, list: listView }, outlet);
      router.start();

      expect(uploadView).toHaveBeenCalledWith(outlet);
      expect(listView).not.toHaveBeenCalled();
    });

    it('falls back to upload view when navigating to unregistered route', () => {
      const uploadView = vi.fn();
      const listView = vi.fn();

      const router = new Router({ upload: uploadView, list: listView }, outlet);
      router.start();

      uploadView.mockClear();

      window.location.hash = 'unknown-route';
      window.dispatchEvent(new HashChangeEvent('hashchange'));

      expect(uploadView).toHaveBeenCalledWith(outlet);
      expect(listView).not.toHaveBeenCalled();
    });

    it('does not throw when no routes match and upload route is not defined', () => {
      window.location.hash = 'something';

      const router = new Router({}, outlet);

      expect(() => router.start()).not.toThrow();
    });
  });
});
