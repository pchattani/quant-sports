/* The Quant Iron — rankings (#/standings?s=&cls=&t=&q=): our rating per stream with the weight class, 90-day movement,
 * a year's change, form against our forecast, and "what a result would do": the total at the lifter's bodyweight that
 * takes them to No. 1 or one place up at their next meet. Reads rankings.json. */
(function () {
'use strict';
var esc = QK.esc, isNum = QK.isNum, fmt = QK.fmt, U = IR.ui;

function mv(v) {
  if (!isNum(v)) return '<span class="qk-muted" title="Not ranked 90 days ago">new</span>';
  if (!v) return '<span class="qk-muted">–</span>';
  return '<span class="' + (v > 0 ? 'pos' : 'neg') + '">' + (v > 0 ? '▲' : '▼') + Math.abs(v) + '</span>';
}

IR.page('rankings', function (el, params) {
  return IR.load('rankings.json').then(function (rk) {
    var q = params.query || {};
    var s = IR.STREAMS[q.s] ? q.s : 'men_raw';
    var sex = IR.sexOf(s);
    var classes = (rk.classes || {})[sex] || IR.CLASSES[sex];
    var cl = classes.indexOf(q.cls) >= 0 ? q.cls : '';
    var tested = q.t === '1';
    el.innerHTML = U.head('Rankings', 'Our rating is the DOTS we expect at a lifter’s next full-power meet (DOTS puts every bodyweight on one scale). Ranked: ' + rk.min_meets + '+ scored meets and one in the last ' + rk.active_days + ' days. ' +
      'Movement compares with our ranking 90 days ago, rebuilt from the meets before that day. For the top 100, “to No. 1” is the total at their current bodyweight that would lift our rating past the leader’s at their next meet.', 'The Quant Iron') +
      '<div class="ir-controls"><label>Stream ' + U.streamSel('rk-s', s) + '</label>' +
      '<label>Class <select class="qk-select" id="rk-c"><option value="">Every class</option>' + classes.map(function (c) { return '<option value="' + esc(c) + '"' + (c === cl ? ' selected' : '') + '>' + esc(c) + ' kg</option>'; }).join('') + '</select></label>' +
      '<label><input type="checkbox" id="rk-t"' + (tested ? ' checked' : '') + '> Mostly tested meets</label>' +
      '<input class="qk-input ir-search" id="rk-q" type="search" placeholder="Lifter or country" value="' + esc(q.q || '') + '"></div>' +
      '<div id="rk-top"></div><div id="rk-table"></div>';
    function draw() {
      var ss = QK.$('#rk-s', el).value, c = QK.$('#rk-c', el).value, t = QK.$('#rk-t', el).checked, qq = String(QK.$('#rk-q', el).value || '').toLowerCase();
      try { history.replaceState(null, '', '#/standings?s=' + ss + (c ? '&cls=' + encodeURIComponent(c) : '') + (t ? '&t=1' : '') + (qq ? '&q=' + encodeURIComponent(qq) : '')); } catch (e) { /* no history */ }
      var all = (((rk.streams || {})[ss] || {}).rows || []);
      var rows = all.filter(function (r) { return (!c || r.cls === c) && (!t || (isNum(r.tested) && r.tested >= 0.5)) && (!qq || (r.name + ' ' + r.cc).toLowerCase().indexOf(qq) >= 0); });
      var risers = all.slice(0, 300).filter(function (r) { return isNum(r.mv); }).sort(function (a, b) { return b.mv - a.mv; });
      QK.$('#rk-top', el).innerHTML = rows.length ? QK.stats([
        { label: 'No. 1' + (c ? ' at ' + c + ' kg' : ''), value: rows[0].name, text: true, href: rows[0].pg ? IR.playerHref(rows[0].pid) : null, sub: IR.dots(rows[0].rt) + ' DOTS · ' + (rows[0].cls ? rows[0].cls + ' kg' : '') },
        { label: 'Ranked', value: fmt.num(rows.length), sub: IR.STREAMS[ss] + (c ? ' · ' + c + ' kg' : '') },
        risers[0] ? { label: 'Biggest climb, top 300', value: risers[0].name, text: true, href: risers[0].pg ? IR.playerHref(risers[0].pid) : null, sub: 'up ' + risers[0].mv + ' places in 90 days, now No. ' + risers[0].rank } : null,
        rows[1] && isNum(rows[1].need1) ? { label: 'No. 2 needs', value: IR.kg(rows[1].need1), sub: rows[1].name + ' at ' + IR.kg(rows[1].bw) + ' bodyweight to go top' } : null
      ]) : '';
      QK.$('#rk-table', el).innerHTML = U.card(IR.STREAMS[ss] + (c ? ' · ' + c + ' kg' : ''), rows.length + ' lifters' + (rows.length > 500 ? ' (the top 500 shown)' : '') + '. Form: the last five meets against our expectation (filled: beat it). Rank is the overall rank in the stream.',
        U.table([{ label: 'Rk' }, { label: '90d' }, { label: 'Lifter', align: 'left' }, { label: 'Class' }, { label: 'Age' }, { label: 'Rating' }, { label: 'Year' }, { label: 'Best 12m' }, { label: 'Meets' }, { label: 'Form', align: 'left' }, { label: 'To No. 1' }, { label: 'Up one' }, { label: '' }],
          rows.slice(0, 500).map(function (r) {
            return [{ v: r.rank, html: String(r.rank) }, { v: isNum(r.mv) ? r.mv : -9999, html: mv(r.mv) },
              { v: r.name, html: IR.playerLink(r.pid, r.name, r.pg) + (r.cc ? ' <small class="qk-muted">' + esc(r.cc) + '</small>' : '') + IR.thinTag(r.n) },
              { v: r.cls, html: esc(r.cls || '–') }, { v: r.age || 0, html: isNum(r.age) ? String(r.age) : '–' },
              { v: r.rt, html: '<b>' + IR.dots(r.rt) + '</b>' }, { v: isNum(r.d365) ? r.d365 : -999, html: '<span class="' + IR.cls(r.d365) + '">' + IR.signed(r.d365) + '</span>' },
              { v: r.best12 || 0, html: IR.dots(r.best12) }, { v: r.n, html: String(r.n) }, { v: r.form || '', html: IR.form(r.form) },
              { v: isNum(r.need1) ? r.need1 : 99999, html: isNum(r.need1) ? IR.kg(r.need1) : (r.rank === 1 ? '<span class="qk-muted">No. 1</span>' : '–') },
              { v: isNum(r.need_up) ? r.need_up : 99999, html: isNum(r.need_up) ? IR.kg(r.need_up) : '–' },
              { v: 0, html: IR.followStar(r.pid, r.name, r.cc) }];
          }), { cls: 'dense ir-rank', maxHeight: 900 }), { flush: true }) +
        U.note('“To No. 1” and “up one” come from our update rule: the lifter’s next meet becomes their last, their best moves if it is higher, and our rating is recomputed. They assume the same bodyweight and a typical gap before the meet after; a dash means out of reach in one meet.');
      U.wire(el);
    }
    draw();
    QK.$('#rk-s', el).addEventListener('change', function () {
      var ss = QK.$('#rk-s', el).value, sx = IR.sexOf(ss), cs = (rk.classes || {})[sx] || IR.CLASSES[sx];
      QK.$('#rk-c', el).innerHTML = '<option value="">Every class</option>' + cs.map(function (c) { return '<option value="' + esc(c) + '">' + esc(c) + ' kg</option>'; }).join('');
      draw();
    });
    QK.$('#rk-c', el).addEventListener('change', draw);
    QK.$('#rk-t', el).addEventListener('change', draw);
    var tm = null;
    QK.$('#rk-q', el).addEventListener('input', function () { clearTimeout(tm); tm = setTimeout(draw, 200); });
  });
});
})();
