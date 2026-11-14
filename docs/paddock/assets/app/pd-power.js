/* The Quant Paddock — #/power: the power rankings (the kit's power.js, QKR.page) over data/power/drivers.json and
 * data/power/constructors.json, built by oddsmarkets/f1/analytics/power_build.py: the drivers (the default) and the
 * constructors ranked on our Elo after every Grand Prix, the climb race by race, and the best and worst drivers in each
 * discipline (qualifying, race pace, team-mate battles) with their numbers.
 * Address: ?l=constructors opens the constructors; ?g=<group> (quali, race, teammate) opens a discipline's tables.
 * The section's words ("by discipline", the Driver column) come from the file's players.head and players.cols.
 * The current season only.
 * Older-browser rule: no optional chaining, no nullish coalescing. */
(function (PD) {
'use strict';
if (!PD || !window.QKR) return;

var LEAGUES = [{ key: 'drivers', label: 'Drivers', href: '#/power' }, { key: 'constructors', label: 'Constructors', href: '#/power?l=constructors' }];

function addr(lg, g) { return '#/power' + PD.qs({ l: lg === 'drivers' ? '' : lg, g: g || '' }); }


PD.route('power', function (el, params) {
  var q = (params && params.query) || {};
  var lg = q.l === 'constructors' ? 'constructors' : 'drivers';
  return QKR.page(el, {
    url: 'data/power/' + lg + '.json', leagues: LEAGUES, group: q.g || null,
    onGroup: function (g) { PD.setHashQuiet(addr(lg, g)); }
  });
});
})(window.PD);
