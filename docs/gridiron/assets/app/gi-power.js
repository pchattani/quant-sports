/* #/power: the power rankings (the kit's power.js, QKR.page) over data/power/nfl.json, built by
 * oddsmarkets/nfl/analytics/power_build.py: the 32 teams ranked by our rating with the weekly climb, and the best and
 * worst players at every position with their numbers. ?g=<group> opens a position's tables (qb, rb, wr, te, edge, dl,
 * lb, cb, s, k, p). The current season only. */
(function () {
'use strict';
GI.route('power', function (el, params) {
  const q = (params && params.query) || {};
  return QKR.page(el, { url: 'data/power/nfl.json', group: q.g || null,
    onGroup: g => { if (GI.setHashQuiet) GI.setHashQuiet('#/power' + (g ? '?g=' + encodeURIComponent(g) : '')); } });
});
})();
