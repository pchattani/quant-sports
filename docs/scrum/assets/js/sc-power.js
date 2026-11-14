/* The Quant Scrum — #/<S>/power?g=<group>: the power rankings (the kit's power.js, QKR.page) over
 * data/power/<S>.json, built by oddsmarkets/rugby/power_build.py: the ranked sides on our rating with the month by
 * month climb, and the best and worst players in each position group (front_row, lock, back_row, halves, centres,
 * back_three) on Scrum value per 80. Men and women are the two "leagues". Older-browser rule: no optional chaining,
 * no nullish coalescing. */
(function () {
'use strict';
SC.route('power', function (el, p) {
  var S = p.S, q = p.query || {};
  if (!window.QKR) { el.innerHTML = QK.empty('Power rankings are not available', 'The page script did not load. Try a reload.'); return; }
  var leagues = SC.SCOPES.filter(function (k) { return SC.info(k).ok !== false; }).map(function (k) {
    return { key: k, label: SC.SNAME[k], href: '#/' + k + '/power' };
  });
  return QKR.page(el, { url: SC.DATA + 'power/' + S + '.json', leagues: leagues, group: q.g || null,
    onGroup: function (g) { try { window.history.replaceState(null, '', '#/' + S + '/power' + (g ? '?g=' + encodeURIComponent(g) : '')); } catch (e) { /* not shareable */ } } });
});
})();
