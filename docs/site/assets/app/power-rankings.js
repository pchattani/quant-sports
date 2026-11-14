/* The Quant Footballer — #/power[?l=<league>&g=<group>]: the power rankings (the kit's power.js, QKR.page) over
 * data/power/<league>.json, built by oddsmarkets/football/analytics/power_build.py after every competition: one file
 * per domestic league with a table (cups and national-team tournaments have none), the clubs ranked by our Elo with
 * the weekly climb, and the best and worst players at every position (gk, cb, fb, dm_cm, am_w, st) on GAR/90.
 * data/power.json lists the leagues and the default one (the Premier League); ?c= is read as ?l= too. The current
 * season only. Older-browser rule: no optional chaining, no nullish coalescing. */
(function (FB) {
'use strict';
var QK = window.QK;

FB.route('power', function (el, params) {
  var q = (params && params.query) || {};
  el.innerHTML = FB.loading('lines', 4);
  return FB.load('power.json').then(function (ix) {
    if (!FB.alive(el)) return;
    var ls = (ix && ix.leagues) || [];
    if (!ls.length || !window.QKR) { el.innerHTML = QK.empty('Power rankings are not built yet', 'They appear after the next build of this site.'); return; }
    var want = q.l || q.c;
    var cur = ls.filter(function (l) { return l.league === want; })[0] || ls.filter(function (l) { return l.league === ix.default; })[0] || ls[0];
    var leagues = ls.map(function (l) { return { key: l.league, label: l.label, href: '#/power' + FB.qs({ l: l.league }) }; });
    return window.QKR.page(el, { url: 'data/' + cur.file, leagues: leagues, group: q.g || null,
      onGroup: function (g) { FB.setHashQuiet('#/power' + FB.qs({ l: cur.league, g: g })); } });
  });
});
})(window.FB);
