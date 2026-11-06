/* The Quant Green — Rankings (#/standings?s=men|women&tab=ours|points): our ranking with its movement over 30, 90 and
 * 365 days, the last five finishes and what each result at the next event would do to the rating; and a points
 * ranking in the style of the official world ranking, rebuilt from results with our own field strengths (depth.py
 * points). Reads rankings.json and points.json. */
(function () {
'use strict';

var QK = window.QK, QKC = window.QKC, GR = window.GR, fmt = QK.fmt;
var esc = GR.esc, isNum = GR.isNum;

function fin(x) { return x[3] === 'finish' ? (x[2] ? 'T' : '') + x[1] : x[3] === 'cut' ? 'MC' : String(x[3] || '').toUpperCase(); }
function mv(v) { return isNum(v) ? '<span class="' + (v > 0.004 ? 'gr-up' : v < -0.004 ? 'gr-down' : '') + '">' + GR.signed(v, 2) + '</span>' : '<span class="gr-muted">new</span>'; }

function ours(el, rk, s) {
  var rows = rk[s] || [];
  var wi = rk[s + '_whatif'] || {};
  var top = rows.slice(0, 20);
  var html = '<div class="qk-g2 gr-gap">' + GR.card('The top 20', 'Our rating, strokes a round better than an average ' + (s === 'men' ? 'PGA Tour' : 'LPGA Tour') + ' player', GR.chart('rk-bar', 520, 'Top 20 ratings')) +
    GR.card('Biggest moves', 'The rating’s change over 90 days among the top 150', GR.chart('rk-mv', 520, 'Biggest moves in 90 days')) + '</div>';
  var cols = [{ label: '#' }, { label: 'Player', align: 'left' }, { label: 'Tour' }, { label: 'Rating' }, { label: '30 days' }, { label: '90 days' }, { label: '12 months' },
    { label: 'Starts' }, { label: 'Wins' }, { label: 'Top 10' }, { label: 'Cuts' }, { label: 'SG/rd' }, { label: 'Last five', align: 'left' },
    { label: 'If he wins', title: 'The rating after a win at the next event (four rounds at a typical winner’s strokes gained)' },
    { label: 'Top 10', title: 'After a top-10 finish' }, { label: 'Mid-table', title: 'After a finish between 30th and 50th' }, { label: 'Misses cut', title: 'After a missed cut (two rounds)' }];
  if (s === 'women') cols[13].label = 'If she wins';
  html += GR.card('Every ranked player', 'Ranked: 10 or more decayed rounds behind the rating and a round in the last 400 days. Movement compares the rating now with the rating before the last event on or before that date. The last four columns: what each result at the next event would do to the rating (the closed form of our update, at the strokes gained a typical player makes with that finish).',
    GR.table(cols, rows.map(function (r) {
      var w = r.wi || {};
      var c = function (k) { return { v: isNum(w[k]) ? w[k] : -99, html: isNum(w[k]) ? mv(w[k]) : '' }; };
      return [{ v: r.rank, html: String(r.rank) }, { v: r.name, html: GR.followStar(r.pid, r.name, s) + GR.playerLink(r.pid, r.name) + ' <span class="gr-muted">' + esc(r.cc || '') + '</span>' + GR.thinTag(r.wt) },
        { v: r.tour || '', html: esc(GR.tourShort(r.tour)) }, { v: r.rt, html: '<b>' + GR.rating(r.rt) + '</b>' },
        { v: isNum(r.d30) ? r.d30 : -99, html: mv(r.d30) }, { v: isNum(r.d90) ? r.d90 : -99, html: mv(r.d90) }, { v: isNum(r.d365) ? r.d365 : -99, html: mv(r.d365) },
        { v: r.starts, html: String(r.starts) }, { v: r.wins, html: String(r.wins) }, { v: r.top10, html: String(r.top10) }, { v: r.cuts, html: String(r.cuts) },
        { v: isNum(r.sg12) ? r.sg12 : -99, html: GR.signed(r.sg12, 2) },
        { v: 0, html: (r.l5 || []).map(function (x) { return '<a class="gr-fin" href="#/event/' + encodeURIComponent(x[0]) + '">' + esc(fin(x)) + '</a>'; }).join(' ') },
        c('win'), c('top10'), c('mid'), c('mc')];
    }), { maxHeight: 900 }), { flush: true, html: true });
  if (wi.win) html += GR.note('A typical winner gains ' + GR.signed(wi.win.sg, 2) + ' a round over ' + wi.win.rounds + ' rounds; a top-10 finisher ' + GR.signed(wi.top10.sg, 2) + '; a player finishing 30th to 50th ' + GR.signed(wi.mid.sg, 2) + (wi.mc && isNum(wi.mc.sg) ? '; a player who misses the cut ' + GR.signed(wi.mc.sg, 2) + ' over ' + wi.mc.rounds : '') + ' (raw strokes gained, the last three years). A player whose rating is above what a result implies falls even with a top 10.');
  el.innerHTML = html;
  QK.sortable(el);
  GR.safe(function () {
    QKC.bar(el.querySelector('#rk-bar'), { cats: top.map(function (r) { return r.name; }), series: [{ name: 'Rating', data: top.map(function (r) { return r.rt; }), color: 'var(--c-1)' }],
      horizontal: true, labels: true, fmt: function (v) { return GR.signed(v, 2); }, hrefs: top.map(function (r) { return GR.playerHref(r.pid); }), valName: 'Strokes a round v an average tour player', catName: 'Player' });
  });
  GR.safe(function () {
    var m = rows.slice(0, 150).filter(function (r) { return isNum(r.d90); }).sort(function (a, b) { return Math.abs(b.d90) - Math.abs(a.d90); }).slice(0, 16).sort(function (a, b) { return b.d90 - a.d90; });
    QKC.bar(el.querySelector('#rk-mv'), { cats: m.map(function (r) { return r.name; }), series: [{ name: '90 days', data: m.map(function (r) { return r.d90; }) }], diverging: true,
      horizontal: true, labels: true, fmt: function (v) { return GR.signed(v, 2); }, hrefs: m.map(function (r) { return GR.playerHref(r.pid); }), valName: 'Change in rating over 90 days (strokes a round)', catName: 'Player' });
  });
}

function points(el, pts, s, rk) {
  var d = (pts || {})[s] || {};
  var rows = d.rows || [];
  if (!rows.length) { el.innerHTML = QK.empty('The points ranking is not built yet', 'It appears after the next build.'); return; }
  var ourRank = {};
  (rk[s] || []).forEach(function (r) { ourRank[r.pid] = r.rank; });
  el.innerHTML = QK.note('<b>How it works.</b> Every finish of the last two years earns points: the winner of a major takes 100, the winner of any other event a share of up to 80 set by the strength of the field (the sum over the field of each player’s rating above −1, to the power 1.5, against the strongest non-major fields), and the places below a falling share of the winner’s (64% for second, 20% for tenth, 2.3% for 60th). Points keep full weight for 13 weeks and then fade to nothing at two years; the total is divided by the events played, between 40 and 52. It is the same shape as the official world ranking but our own method and field strengths: it is not the official ranking.') +
    '<div class="qk-g2 gr-gap">' + GR.card('Points against our rating', 'Each dot a player in both top 100s: our rank across, the points rank up. Off the diagonal: results and rating disagree (a hot streak, a thin schedule, weak fields).', GR.chart('pt-sc', 420, 'Points rank against our rank')) +
    GR.card('The strongest fields', 'Winner’s points by event, the last two years', GR.table([{ label: 'Event', align: 'left' }, { label: 'Tour' }, { label: 'Winner’s points' }],
      (d.top_events || []).map(function (e) { return [{ v: e.name, html: GR.eventLink(e.id, e.name) }, { v: e.tour, html: esc(GR.tourShort(e.tour)) }, { v: e.wp, html: fmt.num(e.wp, 1) }]; })), { flush: true }) + '</div>' +
    GR.card('The points ranking', d.events + ' events in the window', GR.table([{ label: '#' }, { label: 'Player', align: 'left' }, { label: 'Average' }, { label: 'Total' }, { label: 'Events' }, { label: 'Divisor' }, { label: 'Our rank' }],
      rows.map(function (r) { return [{ v: r.rank, html: String(r.rank) }, { v: r.name, html: GR.followStar(r.pid, r.name, s) + GR.playerLink(r.pid, r.name) + ' <span class="gr-muted">' + esc(r.cc || '') + '</span>' },
        { v: r.avg, html: '<b>' + fmt.num(r.avg, 2) + '</b>' }, { v: r.total, html: fmt.num(r.total, 1) }, { v: r.ev, html: String(r.ev) }, { v: r.div, html: String(r.div) },
        { v: ourRank[r.pid] || 999, html: ourRank[r.pid] ? String(ourRank[r.pid]) : '<span class="gr-muted">unranked</span>' }]; }), { maxHeight: 900 }), { flush: true });
  QK.sortable(el);
  GR.safe(function () {
    var pts2 = rows.slice(0, 100).filter(function (r) { return ourRank[r.pid] && ourRank[r.pid] <= 100; }).map(function (r) { return { x: ourRank[r.pid], y: r.rank, name: r.name, label: r.rank <= 12 ? GR.surname(r.name) : '', href: GR.playerHref(r.pid) }; });
    QKC.scatter(el.querySelector('#pt-sc'), { points: pts2, xName: 'Our rank', yName: 'Points rank', xInverse: true, yInverse: true, diagonal: true, label: 'Points rank against our rank' });
  });
}

GR.page('rankings', function (el, params) {
  var q = params.query || {};
  var s = q.s === 'women' ? 'women' : 'men';
  var tab = q.tab === 'points' ? 'points' : 'ours';
  return Promise.all([GR.load('rankings.json'), tab === 'points' ? GR.maybe('points.json') : Promise.resolve(null)]).then(function (r) {
    if (!el.isConnected) return;
    var rk = r[0];
    el.innerHTML = GR.head(s === 'men' ? 'Men' : 'Women', s === 'men' ? 'PGA Tour, DP World Tour, LIV and Korn Ferry Tour players on one scale, tied together by the majors and the events they share.' : 'LPGA Tour players.', 'Rankings') +
      '<div class="gr-controls">' + GR.seg('rk-s', [['men', 'Men'], ['women', 'Women']], s, 'Men or women') + '</div>' +
      GR.tabs([['ours', 'Our ranking', '#/standings?s=' + s], ['points', 'Points ranking (world-ranking style)', '#/standings?s=' + s + '&tab=points']], tab) + '<div id="rk-body"></div>';
    QK.seg(el.querySelector('#rk-s'), function (v) { location.hash = '#/standings?s=' + v + (tab === 'points' ? '&tab=points' : ''); });
    var body = el.querySelector('#rk-body');
    if (tab === 'points') points(body, r[1], s, rk); else ours(body, rk, s);
  });
});
})();
