/* The Quant Hardwood — #/<L>/power: the power rankings (the kit's power.js, QKR.page) over data/power/<L>.json, built
 * by oddsmarkets/basketball/analytics/power_build.py: every team ranked by our net rating after each game, with the
 * climb every seven days back from the latest game, and the best and worst guards, wings and bigs with their numbers.
 * NBA | WNBA chips switch the league; ?g=<group> opens a position's tables (guards, wings, bigs). Home links
 * #/power?l=<L>, and a hash without the league lands on #/<L>/power. The current season only.
 * Older-browser rule: no optional chaining, no nullish coalescing. */
(function (HW) {
'use strict';
function hashFor(L, g) { return '#/' + L + '/power' + (g ? '?g=' + encodeURIComponent(g) : ''); }
HW.page('power', function (el, params) {
  const q = (params && params.query) || {};
  const L = HW.isLeague(q.l) ? q.l : params.league;
  /* Home's link (#/power?l=wnba) and any hash without the league: the league-scoped address */
  if (!/^#\/(nba|wnba)\//.test(location.hash || '') || q.l) {
    try { location.replace(hashFor(L, q.g)); } catch (e) { location.hash = hashFor(L, q.g); }
    return null;
  }
  return QKR.page(el, { url: 'data/power/' + L + '.json', group: q.g || null,
    leagues: HW.LEAGUES.map(l => ({ key: l, label: HW.LEAGUE_NAME[l], href: hashFor(l) })),
    onGroup: g => { try { history.replaceState(null, '', hashFor(L, g)); } catch (e) { /* no history API */ } } });
});
})(window.HW);
