/* The Quant Iron — a meet: leaderboard with our pre-meet expected total and DOTS. */
(function () {
'use strict';

var QK = window.QK, QKC = window.QKC, IR = window.IR;
var isNum = IR.isNum;

function chartSafe(fn) { try { fn(); } catch (e) { if (window.console) console.error(e); } }

IR.page('event', function (el, params) {
  return IR.load('events/' + encodeURIComponent(params.id) + '.json').then(function (e) {
    if (!el.isConnected) return;
    var sbd = (e.board || []).filter(function (r) { return r.event === 'SBD' && isNum(r.dots); });
    var fav = sbd.slice().sort(function (a, b) { return (b.pre || 0) - (a.pre || 0); })[0];
    var best = sbd.slice().sort(function (a, b) { return (b.total || 0) - (a.total || 0); })[0];
    el.innerHTML = QK.sectionHead({ tag: 'h1', kicker: (e.fed || '') + (e.parent ? ' · ' + e.parent : ''), title: e.name,
      sub: IR.dayMonth(e.date) + (e.country ? ' · ' + e.country : '') + (e.state ? ', ' + e.state : '') + ' · ' + (e.n || 0) + ' lifters' }) +
      QK.stats([
        { label: 'Lifters', value: String(e.n || 0), sub: (e.n_sbd || 0) + ' full-power' },
        { label: 'Our favourite', value: fav ? fav.name : '\u2014', sub: fav && isNum(fav.pre) ? IR.dots(fav.pre) + ' DOTS going in' : '' },
        { label: 'Best total', value: best ? IR.kg(best.total) : '\u2014', sub: best ? best.name : '' }
      ]) +
      '<div class="qk-grid"><div class="qk-span-12">' + IR.card('Expected vs actual DOTS', 'Each dot is a full-power lifter we had already seen. The diagonal is a perfect forecast.', '<div class="qk-chart" id="ir-sc" style="height:280px"></div>') + '</div></div>' +
      '<section class="qk-section">' + QK.sectionHead({ title: 'Leaderboard' }) + '<div id="ir-bd"></div></section>';
    chartSafe(function () {
      QKC.scatter(el.querySelector('#ir-sc'), {
        points: sbd.filter(function (r) { return isNum(r.pre) && isNum(r.dots); }).map(function (r) {
          return { x: r.pre, y: r.dots, name: r.name, href: '#/player/' + encodeURIComponent(r.pid) };
        }),
        xName: 'Our DOTS', yName: 'Actual DOTS', diagonal: true, label: 'Expected vs actual'
      });
    });
    QK.table(el.querySelector('#ir-bd'), {
      dense: true, maxHeight: 900, rows: e.board || [], sort: { key: 'dots', dir: 'desc' },
      rowHref: function (r) { return '#/player/' + encodeURIComponent(r.pid); },
      columns: [
        { key: 'name', label: 'Lifter', sticky: true, fmt: function (v, r) { return IR.playerLink(r.pid, v) + (r.tested ? '' : ' <span class="ir-thin">untested</span>'); } },
        { key: 'eq', label: 'Eq' },
        { key: 'class', label: 'Class' },
        { key: 'bw', label: 'Bw', num: true, fmt: function (v) { return IR.kg(v); } },
        { key: 'squat', label: 'Squat', num: true, fmt: function (v) { return isNum(v) ? v.toFixed(1) : '\u2014'; } },
        { key: 'bench', label: 'Bench', num: true, fmt: function (v) { return isNum(v) ? v.toFixed(1) : '\u2014'; } },
        { key: 'dead', label: 'Deadlift', num: true, fmt: function (v) { return isNum(v) ? v.toFixed(1) : '\u2014'; } },
        { key: 'total', label: 'Total', num: true, fmt: function (v) { return IR.kg(v); } },
        { key: 'exp', label: 'Our total', num: true, ours: 'Expected total', fmt: function (v) { return IR.kg(v); } },
        { key: 'dots', label: 'DOTS', num: true, fmt: function (v) { return IR.dots(v); } },
        { key: 'pre', label: 'Our DOTS', num: true, fmt: function (v) { return IR.dots(v); } },
        { key: 'place', label: 'Place' }
      ]
    });
  });
});

})();
