/**
 * Hash-based SPA router.
 * Routes map hash fragments to view render functions.
 * Supports route guards for admin-gated routes.
 */
export class Router {
  /**
   * @param {Object<string, Function>} routes - Map of hash paths to render functions
   * @param {HTMLElement} outlet - DOM element where views render
   * @param {Object} [options] - Optional configuration
   * @param {Function} [options.guardFn] - Function returning true if guarded routes are accessible
   * @param {string[]} [options.guardedRoutes] - Array of route keys that require guardFn to return true
   * @param {string} [options.fallbackRoute] - Route to redirect to when guard fails (default: 'upload')
   */
  constructor(routes, outlet, options = {}) {
    this.routes = routes;
    this.outlet = outlet;
    this._guardFn = options.guardFn || null;
    this._guardedRoutes = options.guardedRoutes || [];
    this._fallbackRoute = options.fallbackRoute || 'upload';
    this._onHashChange = this._onHashChange.bind(this);
  }

  /** Start listening to hashchange events and render initial route */
  start() {
    window.addEventListener('hashchange', this._onHashChange);
    this._render();
  }

  /** Navigate programmatically to a route */
  navigate(path) {
    window.location.hash = path;
  }

  /**
   * Handle hashchange event by rendering the matched route.
   * @private
   */
  _onHashChange() {
    this._render();
  }

  /**
   * Parse the current hash and render the corresponding view.
   * Defaults to the upload view for unknown routes.
   * Redirects to fallback if a guarded route is accessed without permission.
   * @private
   */
  _render() {
    const hash = window.location.hash.slice(1) || 'upload';

    // Gate admin routes: redirect non-admins to fallback
    if (this._guardedRoutes.includes(hash) && this._guardFn && !this._guardFn()) {
      window.location.hash = this._fallbackRoute;
      return;
    }

    const renderFn = this.routes[hash] || this.routes['upload'];

    if (renderFn) {
      renderFn(this.outlet);
    }
  }
}
