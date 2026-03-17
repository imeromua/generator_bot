/**
 * sd-router.js — Lightweight hash-based SPA router.
 *
 * Routes are registered with router.on(hash, handler).
 * Navigating to a route: router.navigate('#dashboard')
 *
 * Example:
 *   router.on('dashboard', async () => { ... render ... });
 *   router.start('#dashboard');  // default route
 */

const router = (() => {
  const _routes   = {};    // hash → handler fn
  let   _default  = null;
  let   _current  = null;

  /** Register a route handler. */
  function on(hash, handler) {
    _routes[hash] = handler;
    return { on, start };   // fluent
  }

  /** Called when the URL hash changes. */
  function _dispatch() {
    const raw  = window.location.hash.slice(1) || _default || '';
    const hash = raw.split('?')[0];   // strip any query string

    if (hash === _current) return;
    _current = hash;

    // Update active state for nav links
    document.querySelectorAll('[data-route]').forEach(el => {
      el.classList.toggle('active', el.dataset.route === hash);
    });

    const handler = _routes[hash];
    if (handler) {
      Promise.resolve(handler(hash)).catch(console.error);
    } else if (_default && _routes[_default]) {
      window.location.hash = '#' + _default;
    }
  }

  /**
   * Start the router, registering the hashchange listener.
   * @param {string} defaultRoute  — hash fragment used when none is present (without '#')
   */
  function start(defaultRoute = 'dashboard') {
    _default = defaultRoute;
    window.addEventListener('hashchange', _dispatch);
    _dispatch();   // handle the current URL on load
  }

  /** Programmatically navigate to a route. */
  function navigate(hash) {
    const frag = hash.startsWith('#') ? hash : '#' + hash;
    if (window.location.hash === frag) {
      _dispatch();   // force re-render if already on that route
    } else {
      window.location.hash = frag;
    }
  }

  /** Return the current active route name (without '#'). */
  function current() { return _current; }

  return { on, start, navigate, current };
})();

if (typeof module !== 'undefined') module.exports = router;
