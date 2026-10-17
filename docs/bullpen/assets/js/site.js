/* The Quant Bullpen — the disclaimer route (its text is the <template> in index.html) and the first-visit notice. */
(function (BP) {
'use strict';
BP.route('disclaimer', function (el) {
  var t = document.getElementById('disclaimer-template');
  el.innerHTML = t ? t.innerHTML : '';
});
var KEY = 'qb-notice-v1', box = document.getElementById('first-visit-notice');
if (box) {
  var seen = false;
  try { seen = window.localStorage.getItem(KEY) === '1'; } catch (e) { seen = false; }
  if (!seen) box.hidden = false;
  var btn = document.getElementById('fv-dismiss');
  if (btn) btn.addEventListener('click', function () {
    box.hidden = true;
    try { window.localStorage.setItem(KEY, '1'); } catch (e) { /* private mode: shown again next visit */ }
  });
}
})(window.BP);
