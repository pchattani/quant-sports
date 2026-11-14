/* The Quant Ace — #/<T>/power: the power rankings (the kit's power.js, QKR.page) over data/power/atp.json and
 * data/power/wta.json, built by oddsmarkets/tennis/analytics/power_build.py: the top 100 on our Elo with the climb week
 * by week, and the best and worst on serve, on return and on each surface with their numbers.
 * Address: ?g=<group> (serve, return, hard, clay, grass) opens a group's tables; #/power?l=wta lands on #/wta/power (the
 * form Home's section links with). The current season only.
 * The section's words (serve, return and surfaces; the Nation column) come from the file's players.head and players.cols.
 * Older-browser rule: no optional chaining, no nullish coalescing. */
(function () {
'use strict';
const TA = window.TA;
if (!TA || !window.QKR) return;

function leagues() { return TA.TOURS.map(t => ({ key: t, label: t.toUpperCase(), href: '#/' + t + '/power' })); }
function addr(T, g) { return '#/' + T + '/power' + (g ? '?g=' + encodeURIComponent(g) : ''); }


TA.route('power', function (el, params) {
  const q = (params && params.query) || {};
  if (q.l && TA.TOURS.indexOf(q.l) >= 0 && q.l !== params.tour) { location.replace(addr(q.l, q.g)); return null; }
  const T = params.tour;
  return QKR.page(el, {
    url: 'data/power/' + T + '.json', leagues: leagues(), group: q.g || null,
    onGroup: g => { try { history.replaceState(null, '', addr(T, g)); } catch (e) { /* no history API */ } }
  });
});
})();
