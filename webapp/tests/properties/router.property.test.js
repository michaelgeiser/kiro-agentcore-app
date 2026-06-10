// Feature: frontend-spa, Property 1: Client-side routing renders correct view

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import * as fc from 'fast-check';
import { Router } from '../../js/router.js';

/**
 * Property 1: Client-side routing renders correct view
 *
 * For any registered route hash, navigating to that hash renders the
 * corresponding view function's output into the outlet element.
 *
 * Validates: Requirements 1.3
 */
describe('Property 1: Client-side routing renders correct view', () => {
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

  /**
   * Arbitrary that generates a valid route name (alphanumeric, lowercase, 1-20 chars).
   * We avoid 'upload' as a generated key since it's the default fallback.
   */
  const routeNameArb = fc.stringMatching(/^[a-z][a-z0-9]{0,19}$/).filter(
    (s) => s.length > 0 && s !== 'upload'
  );

  /**
   * Creates a view function for a given route name.
   * Content is unique per route to verify correct rendering.
   */
  function makeViewFn(routeName) {
    return (el) => {
      el.innerHTML = `<div data-route="${routeName}">content-${routeName}</div>`;
    };
  }

  /**
   * Arbitrary that generates a routes map with at least one entry plus the 'upload' route.
   * Each route maps to a view function that renders unique content.
   */
  const routesMapArb = fc
    .uniqueArray(routeNameArb, { minLength: 1, maxLength: 10 })
    .map((names) => {
      const routes = {};
      // Always include 'upload' as the default route
      routes['upload'] = makeViewFn('upload');
      for (const name of names) {
        routes[name] = makeViewFn(name);
      }
      return routes;
    });

  it('navigating to any registered route renders that route\'s view into the outlet', () => {
    fc.assert(
      fc.property(routesMapArb, (routes) => {
        // Pick a random registered route key to navigate to
        const routeKeys = Object.keys(routes);
        const targetRoute = routeKeys[Math.floor(Math.random() * routeKeys.length)];

        // Set the hash to our target route
        window.location.hash = targetRoute;

        // Create router and start it (renders based on current hash)
        const router = new Router(routes, outlet);
        router.start();

        // Verify the outlet contains the correct view content
        const rendered = outlet.querySelector(`[data-route="${targetRoute}"]`);
        expect(rendered).not.toBeNull();
        expect(rendered.textContent).toBe(`content-${targetRoute}`);

        // Clean up event listener
        window.removeEventListener('hashchange', router._onHashChange);
      }),
      { numRuns: 100 }
    );
  });

  it('for any route map, each registered route renders correctly when navigated to', () => {
    fc.assert(
      fc.property(
        routesMapArb,
        fc.integer({ min: 0, max: 100 }),
        (routes, routeIndex) => {
          const routeKeys = Object.keys(routes);
          // Use modulo to select a route deterministically from the generated index
          const targetRoute = routeKeys[routeIndex % routeKeys.length];

          // Set hash before creating router
          window.location.hash = targetRoute;

          const router = new Router(routes, outlet);
          router.start();

          // Verify correct view rendered
          const rendered = outlet.querySelector(`[data-route="${targetRoute}"]`);
          expect(rendered).not.toBeNull();
          expect(rendered.textContent).toBe(`content-${targetRoute}`);

          // Clean up
          window.removeEventListener('hashchange', router._onHashChange);
        }
      ),
      { numRuns: 100 }
    );
  });

  it('unknown routes default to the upload view', () => {
    fc.assert(
      fc.property(
        routesMapArb,
        fc.stringMatching(/^[A-Z][A-Z0-9]{5,15}$/).filter(
          (s) => s.length > 0
        ),
        (routes, unknownRoute) => {
          // Ensure the unknown route isn't actually registered
          fc.pre(!Object.hasOwn(routes, unknownRoute));

          window.location.hash = unknownRoute;

          const router = new Router(routes, outlet);
          router.start();

          // Should fall back to 'upload' view
          const rendered = outlet.querySelector('[data-route="upload"]');
          expect(rendered).not.toBeNull();
          expect(rendered.textContent).toBe('content-upload');

          // Clean up
          window.removeEventListener('hashchange', router._onHashChange);
        }
      ),
      { numRuns: 100 }
    );
  });
});
