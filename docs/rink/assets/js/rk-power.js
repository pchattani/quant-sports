/* The Quant Rink — #/power: the power rankings (the kit's power.js, QKR.page) over data/power/nhl.json, built by
 * oddsmarkets/nhl/analytics/power_build.py: the 32 clubs ranked by our rating with the weekly climb (each Monday's
 * refit, then now), and the best and worst players at every position with their numbers. ?g=<group> opens a
 * position's tables (c, w, d, g). The current season only.
 * Older-browser rule: no optional chaining, no nullish coalescing. */
(function (RK) {
'use strict';
RK.page('power', function (el, params) {
  const q = (params && params.query) || {};
  return QKR.page(el, { url: 'data/power/nhl.json', group: q.g || null,
    onGroup: g => { try { history.replaceState(null, '', '#/power' + (g ? '?g=' + encodeURIComponent(g) : '')); } catch (e) { /* no history API */ } } });
});
})(window.RK);
