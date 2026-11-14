/* The Quant Iron — #/power?l=<stream>&g=<class>: the power rankings (the kit's power.js, QKR.page) over
 * data/power/<stream>.json, built by oddsmarkets/powerlifting/power_build.py: the top 100 lifters of a stream by our
 * rating (expected DOTS at the next meet) with the monthly climb, and the best and worst in every IPF weight class.
 * Men and women raw (each stream is its own DOTS scale), men_raw by default. ?g= opens a class's
 * tables (59 ... 120p for 120+). */
(function () {
'use strict';
var QK = window.QK, IR = window.IR;

/* the players block's words (weight classes, the Lifter and Country columns) come from the file's players.head and .cols */

IR.page('power', function (el, params) {
  var q = (params && params.query) || {};
  return IR.load('power.json').then(function (ix) { return ix; }, function () { return null; }).then(function (ix) {
    if (!el.isConnected) return;
    var lgs = ((ix && ix.leagues) || ['men_raw', 'women_raw'].map(function (k) { return { league: k, label: IR.STREAMS[k] }; }))
      .map(function (x) { return { key: x.league, label: x.label, href: '#/power?l=' + encodeURIComponent(x.league) }; });
    var keys = lgs.map(function (x) { return x.key; });
    var lg = keys.indexOf(q.l) >= 0 ? q.l : ((ix && ix.default) || 'men_raw');
    return QKR.page(el, { url: 'data/power/' + lg + '.json', leagues: lgs, group: q.g || null,
      onGroup: function (g) { try { history.replaceState(null, '', '#/power?l=' + encodeURIComponent(lg) + (g ? '&g=' + encodeURIComponent(g) : '')); } catch (e) { /* no history API */ } } });
  });
});
})();
