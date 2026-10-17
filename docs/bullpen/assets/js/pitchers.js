/* The Quant Bullpen — the pitchers catalogue (#/<L>/pitchers).
 *
 * The hitters catalogue (hitters.js, BP.gk.renderCatalogue) with batters faced as the sample,
 * a starter/reliever filter and role percentiles (pct_role: against starters or against
 * relievers). Data: data/<L>/<S>/pitchers.json (PAYLOADS.md). */
(function (BP) {
'use strict';

function render(el, params, state) {
  const K = BP.gk;
  if (!K || !K.renderCatalogue) { el.innerHTML = '<div class="muted">The page kit (hitters.js) did not load.</div>'; return null; }
  return K.renderCatalogue(el, params, state, 'pitcher');
}
if (typeof BP.route === 'function') { BP.route('pitchers', render); try { BP.route('#/<L>/pitchers', render); } catch (e) { /* name already bound */ } }
})(window.BP || (window.BP = {}));
