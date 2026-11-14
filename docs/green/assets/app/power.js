/* The Quant Green — #/power?l=men|women&g=<group>: the power rankings (the kit's power.js, QKR.page) over
 * data/power/<l>.json, built by oddsmarkets/golf/power_build.py: the top 100 players by our rating with the weekly
 * climb (one snapshot per completed event week), and the best and worst in each group: the men's strokes-gained
 * categories (ott, app, arg, putt; our estimate from PGA Tour season statistics), the LPGA's scoring splits (r12, wknd,
 * front, back). ?g= opens a group's tables. */
(function () {
'use strict';
var QK = window.QK, GR = window.GR;
var FALLBACK = [{ league: 'men', label: 'Men’s tours' }, { league: 'women', label: 'LPGA' }];
/* the players block's words (categories, splits, weight classes) come from the file's players.head and players.cols */

GR.page('power', function (el, params) {
  var q = (params && params.query) || {};
  return GR.maybe('power.json').then(function (ix) {
    if (!el.isConnected) return;
    var lgs = ((ix && ix.leagues) || FALLBACK).map(function (x) { return { key: x.league, label: x.label }; });
    var keys = lgs.map(function (x) { return x.key; });
    var lg = keys.indexOf(q.l) >= 0 ? q.l : ((ix && ix.default) || 'men');
    lgs.forEach(function (x) { x.href = '#/power?l=' + encodeURIComponent(x.key); });
    return QKR.page(el, { url: 'data/power/' + lg + '.json', leagues: lgs, group: q.g || null,
      onGroup: function (g) { GR.setQuery('power', 'l=' + encodeURIComponent(lg) + (g ? '&g=' + encodeURIComponent(g) : '')); } });
  });
});
})();
