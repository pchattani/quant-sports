/* #/mlb/power: the power rankings (the kit's power.js, QKR.page) over data/power/mlb.json, built by
 * oddsmarkets/baseball/analytics/power_build.py: the 30 clubs ranked by the season simulation's run-differential rating
 * with the climb over the last ten weeks, and the best and worst players at every position on WAR with their numbers.
 * ?g=<group> opens a position's tables (c, 1b, 2b, 3b, ss, cf, of, dh, sp, rp). MLB and the current season only: any
 * other level's #/<L>/power opens MLB (core.js redirectOf). */
(function () {
'use strict';
/* A season's first week has one snapshot (Now): QKR.list then leaves the move column out and its grid slips, and the
   climb's head reads "Now to Now". Hold the column with a level chip and say when the climb starts (until the kit's
   QKR.list always writes the chip). */
function oneSnapshot(el, doc) {
  if (!doc || !el.isConnected || (doc.snapshots || []).length >= 2) return doc;
  el.querySelectorAll('.qkp-row').forEach(r => {
    if (r.querySelector(':scope > .qkp-mv')) return;
    const rk = r.querySelector(':scope > .qkp-rk');
    if (rk) rk.insertAdjacentHTML('afterend', '<span class="qkp-mv eq" title="No earlier snapshot yet">–</span>');
  });
  const seg = el.querySelector('#qkp-top');
  if (seg && seg.parentNode) seg.parentNode.removeChild(seg);
  const bump = el.querySelector('#qkp-bump'), sec = bump ? bump.closest('section') : null, sub = sec ? sec.querySelector('.qk-sh-sub') : null;
  if (sub) sub.textContent = 'Rank at each weekly snapshot. The first comes once the season is a week old.';
  return doc;
}
function render(el, params) {
  const q = (params && params.query) || {};
  return QKR.page(el, { url: 'data/power/mlb.json', group: q.g || null,
    onGroup: g => { try { history.replaceState(null, '', '#/mlb/power' + (g ? '?g=' + encodeURIComponent(g) : '')); } catch (e) { /* no history API */ } } })
    .then(doc => oneSnapshot(el, doc));
}
if (typeof BP.route === 'function') BP.route('power', render);
})();
