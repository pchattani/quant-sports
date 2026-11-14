/* #/<L>/power: the power rankings (the kit's power.js, QKR.page) over data/power/<L>.json, built by
 * oddsmarkets/college/power_build.py: every team of the level ranked by our rating with the climb week by week, and the
 * best and worst players at every position with their numbers. League chips for the levels in data/power.json (the
 * site's index; all five when it does not load). ?g=<group> opens a position's tables (football qb, rb, wr, te, dl, lb,
 * db, k, p; basketball g, f, c; hockey f, d, g). The current season only. */
(function () {
'use strict';
var LABEL = { cfb: 'Football', mbb: 'Men’s basketball', wbb: 'Women’s basketball', mch: 'Men’s hockey', wch: 'Women’s hockey' };
/* A level in its first week (or preseason) has one snapshot (Now): QKR.list then leaves the move column out and its grid
   slips, and the climb's head reads "Now to Now". Hold the column with a level chip and say when the climb starts
   (until the kit's QKR.list always writes the chip). */
function oneSnapshot(el, doc) {
  if (!doc || !el.isConnected || (doc.snapshots || []).length >= 2) return doc;
  QK.$$('.qkp-row', el).forEach(function (r) {
    if (r.querySelector(':scope > .qkp-mv')) return;
    var rk = r.querySelector(':scope > .qkp-rk');
    if (rk) rk.insertAdjacentHTML('afterend', '<span class="qkp-mv eq" title="No earlier snapshot yet">–</span>');
  });
  var seg = el.querySelector('#qkp-top');
  if (seg && seg.parentNode) seg.parentNode.removeChild(seg);
  var bump = el.querySelector('#qkp-bump'), sec = bump ? bump.closest('section') : null, sub = sec ? sec.querySelector('.qk-sh-sub') : null;
  if (sub) sub.textContent = 'Rank at each weekly snapshot. The first comes once the season is a week old.';
  return doc;
}
CC.route('power', function (el, p) {
  var L = p.L, q = p.query || {};
  el.innerHTML = QK.skeleton('lines', 4);
  return CC.load('power.json').then(function (idx) {
    if (!el.isConnected) return null;
    var have = CC.ok(idx) && Array.isArray(idx.leagues) ? idx.leagues.map(function (x) { return x.league; }) : CC.LEVELS.slice();
    var leagues = CC.LEVELS.filter(function (l) { return have.indexOf(l) >= 0 || l === L; }).map(function (l) {
      return { key: l, label: LABEL[l] || CC.LSHORT[l], href: '#/' + l + '/power' };
    });
    return QKR.page(el, { url: CC.DATA + 'power/' + L + '.json', leagues: leagues, group: q.g || null,
      onGroup: function (g) { try { history.replaceState(null, '', '#/' + L + '/power' + (g ? '?g=' + encodeURIComponent(g) : '')); } catch (e) { /* no history API */ } } })
      .then(function (doc) { return oneSnapshot(el, doc); });
  });
});
})();
