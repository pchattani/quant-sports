/* The Quant Scrum — Teams (the power board, the team-profile heat grid, the style map, strengths and weaknesses, head to
 * head) and the team page (the hero in the nation's colours, the next test, the profile against every side, form and
 * rating history, results and fixtures, head-to-head records, the squad and the most-capped players, title chances).
 * Reads <S>/teams.json and <S>/teams/<id>.json (oddsmarkets/rugby/pages.py). */
(function () {
'use strict';
var esc = QK.esc, isNum = QK.isNum, fmt = QK.fmt, U = SC.ui;
var PRESETS = [
  { key: 'score', label: 'Attack v defence', x: 'pf', y: 'pa', corners: { tr: 'Score a lot, leak a lot', tl: 'Tight games', br: 'Dominant', bl: 'Struggling' } },
  { key: 'ball', label: 'Possession v territory', x: 'poss', y: 'terr', corners: { tr: 'Ball and field', tl: 'Kick to win', br: 'Keep the ball', bl: 'Chasing' } },
  { key: 'carry', label: 'Metres v tackle success', x: 'metres', y: 'tackle_pct', corners: { tr: 'Strong both ways', tl: 'Defend first', br: 'Run first', bl: 'Struggling' } },
  { key: 'set', label: 'Scrum v lineout', x: 'scrum_pct', y: 'lineout_pct', corners: { tr: 'Set-piece kings', tl: 'Lineout side', br: 'Scrum side', bl: 'Set-piece trouble' } }
];

function mfmt(m, v) {
  if (!isNum(v)) return '—';
  if (m && (m.unit === '%')) return Math.round(v * 100) + '%';
  return Math.abs(v) >= 100 ? fmt.num(v, 0) : fmt.num(v, 1);
}

SC.route('teams', function (page, P) {
  var S = P.S;
  page.innerHTML = U.head('Teams', 'Every side’s rating, its profile against every other side over the last two years (opponent-adjusted), how it plays, and head to head.', SC.SNAME[S]) + '<div id="tm-body">' + QK.skeleton('lines', 8) + '</div>';
  var body = QK.$('#tm-body', page);
  return SC.load(S + '/teams.json').then(function (d) {
    if (!U.alive(body)) return;
    if (!SC.ok(d)) { body.innerHTML = U.missing('The teams page', d); return; }
    var M = {};
    (d.metrics || []).forEach(function (m) { M[m.id] = m; });
    var rows = (d.teams || []);
    var q = P.query || {};
    var preset = PRESETS.filter(function (p) { return p.key === q.map; })[0] || PRESETS[0];
    var html = U.sec('Power board', 'Every side with six tests in two years', 'Our rating split into attack and defence, the last ten results.', QK.powerBars ? QK.powerBars(null, { groups: [{ label: '', rows: rows.map(function (r, i) {
      var t = SC.team(S, r.id) || {};
      return { rank: i + 1, name: t.name, abbr: t.abbr, colour: t.colour, href: SC.teamHref(S, r.id), value: r.rating, text: SC.signed(r.rating, 1), parts: { att: r.att, dfn: r.dfn }, form: r.form,
        follow: SC.followItem(S, r.id), cells: [{ label: 'Tests', text: String(r.n) }] };
    }) }], parts: [{ key: 'att', label: 'Attack', color: 'var(--c-1)' }, { key: 'dfn', label: 'Defence', color: 'var(--c-3)' }], valueLabel: 'Our rating', unit: 'points', formN: 10 }) : '');
    html += U.sec('Team profile', 'Every side on every measure', 'Per test since ' + SC.date(d.since) + ', opponent-adjusted (shifted by how much each opponent usually allows), coloured by percentile among these sides. Grey columns describe style, not quality.', '<div id="tm-grid"></div>');
    html += U.sec('Style map', 'How they play', 'Two measures at a time; the dashed lines are the averages. Pick a pair.', '<div class="qk-chips sc-filters" id="tm-map">' + PRESETS.map(function (p) {
      return '<a class="qk-chip" href="' + esc(SC.href(S, 'teams', null, 'map=' + p.key)) + '" aria-pressed="' + (p.key === preset.key) + '">' + esc(p.label) + '</a>';
    }).join('') + '</div>' + U.card('', '', U.chart('tm-scatter', 440, preset.label)));
    var opts = rows.map(function (r) { return '<option value="' + esc(r.id) + '">' + esc(SC.tname(S, r.id)) + '</option>'; }).join('');
    var a = q.a || (rows[0] || {}).id, b = q.b || (rows[1] || {}).id;
    html += U.sec('Head to head', 'Tale of the tape', 'Two sides on the profile percentiles, the gap under each measure.', QK.scoutBar([{ label: 'Team', html: '<select class="qk-select" id="tm-a">' + opts + '</select>' },
      { label: 'v', html: '<select class="qk-select" id="tm-b">' + opts + '</select>' }]) + '<div id="tm-tape"></div>');
    html += U.sec('Strengths and weaknesses', 'Best and worst, side by side', 'Each side’s three best and three weakest measures (percentile among these sides).', '<div class="sc-sws">' + rows.slice(0, 12).map(function (r) {
      var t = SC.team(S, r.id) || {};
      var list = Object.keys(r.m || {}).filter(function (k) { return M[k] && !M[k].style && isNum(r.m[k][1]); }).map(function (k) { return { label: M[k].label, pctl: r.m[k][1], text: mfmt(M[k], r.m[k][0]) }; });
      list.sort(function (x, y) { return y.pctl - x.pctl; });
      return QK.strengths ? QK.strengths({ name: t.name, abbr: t.abbr, colour: t.colour, href: SC.teamHref(S, r.id), sub: SC.signed(r.rating, 1) + ' rating', best: list.slice(0, 3), worst: list.slice(-3).reverse() }) : '';
    }).join('') + '</div>');
    body.innerHTML = html;
    // heat grid
    var groups = {};
    (d.metrics || []).forEach(function (m) { (groups[m.group] = groups[m.group] || []).push(m.id); });
    if (QK.heatGrid) QK.heatGrid(QK.$('#tm-grid', body), { id: 'sc-hg', sets: [{ key: 'all', label: 'Every measure', groups: Object.keys(groups).map(function (g) { return { label: g, ids: groups[g] }; }) }],
      meta: function (id) { var m = M[id] || {}; return { label: m.label || id, lower: m.dir === 'lower', style: !!m.style, fmt: function (v) { return mfmt(m, v); }, tip: m.label + (m.unit === '%' ? '' : ', per test') }; },
      rows: rows.map(function (r) { var t = SC.team(S, r.id) || {}; return { id: r.id, name: t.name, sub: SC.signed(r.rating, 1), mark: { abbr: t.abbr, colour: t.colour }, href: SC.teamHref(S, r.id), vals: (function () { var o = {}; Object.keys(r.m || {}).forEach(function (k) { o[k] = r.m[k][0]; }); return o; })() }; }),
      entity: 'team', noun: 'sides', csv: 'scrum-team-profile.csv' });
    // style map
    var pts = rows.filter(function (r) { return r.m[preset.x] && r.m[preset.y]; }).map(function (r) {
      var t = SC.team(S, r.id) || {};
      var sx = M[preset.x].unit === '%' ? 100 : 1, sy = M[preset.y].unit === '%' ? 100 : 1;
      return { x: r.m[preset.x][0] * sx, y: r.m[preset.y][0] * sy, label: t.abbr, name: t.name, color: t.colour, href: SC.teamHref(S, r.id) };
    });
    var yInv = M[preset.y].dir === 'lower';
    if (window.QKC && pts.length > 3) QKC.quadrant(QK.$('#tm-scatter', body), { points: pts, xName: M[preset.x].label + (M[preset.x].unit === '%' ? ' (%)' : ' per test'), yName: M[preset.y].label + (M[preset.y].unit === '%' ? ' (%)' : ' per test') + (yInv ? ' (lower is better)' : ''),
      corners: preset.corners });
    // head to head
    var sa = QK.$('#tm-a', body), sb = QK.$('#tm-b', body);
    sa.value = a; sb.value = b;
    function tape() {
      var A = rows.filter(function (r) { return r.id === sa.value; })[0], B = rows.filter(function (r) { return r.id === sb.value; })[0];
      if (!A || !B) return;
      var ta = SC.team(S, A.id) || {}, tb = SC.team(S, B.id) || {};
      QK.$('#tm-tape', body).innerHTML = QK.tape({ left: { name: ta.name, short: ta.abbr, sub: SC.signed(A.rating, 1), colour: ta.colour, alt: ta.alt, href: SC.teamHref(S, A.id) },
        right: { name: tb.name, short: tb.abbr, sub: SC.signed(B.rating, 1), colour: tb.colour, alt: tb.alt, href: SC.teamHref(S, B.id) }, gap: true,
        groups: Object.keys(groups).map(function (g) { return { label: g, rows: groups[g].filter(function (k) { return A.m[k] && B.m[k]; }).map(function (k) {
          return { label: M[k].label, a: A.m[k][0], b: B.m[k][0], ta: mfmt(M[k], A.m[k][0]), tb: mfmt(M[k], B.m[k][0]), pa: A.m[k][1], pb: B.m[k][1] };
        }) }; }) });
    }
    sa.addEventListener('change', tape); sb.addEventListener('change', tape);
    tape();
  });
});

/* ── the team page ──────────────────────────────────────────────────── */
var GROUP_ORDER = ['Attack', 'Defence', 'Set piece', 'Discipline', 'Kicking'];

function ratingChart(el, S, T) {
  if (!el || !window.QKC || !T.rating_hist || T.rating_hist.length < 3) return;
  var x = T.rating_hist.map(function (h) { return h[0] + '-15'; });
  QKC.line(el, { x: x, xType: 'time', series: [{ name: 'Our rating', data: T.rating_hist.map(function (h) { return h[1]; }), color: 'var(--c-1)' }], ref: { y: 0, label: 'Average test side' },
    yName: 'Our rating (points)', xName: 'Month', endLabels: false });
}
function wrChart(el, S, T) {
  if (!el || !window.QKC || !T.wr_hist || T.wr_hist.length < 3) return;
  QKC.line(el, { x: T.wr_hist.map(function (h) { return h[0] + '-15'; }), xType: 'time', series: [{ name: 'World Rugby points', data: T.wr_hist.map(function (h) { return h[1]; }), color: 'var(--c-3)' }],
    yName: 'World Rugby points (our rebuild)', xName: 'Month', endLabels: false, step: 'end' });
}

SC.route('team', function (page, P) {
  var S = P.S, tid = P.id;
  page.innerHTML = QK.skeleton('card', 2);
  return Promise.all([SC.load(S + '/teams/' + tid + '.json'), SC.load(S + '/teams.json')]).then(function (res) {
    var T = res[0], all = res[1];
    if (!SC.ok(T)) { page.innerHTML = U.head(SC.tname(S, tid), '', SC.SNAME[S]) + U.missing('This team page', T); return; }
    var t = T.team || SC.team(S, tid) || {};
    var M = {};
    ((SC.ok(all) && all.metrics) || []).forEach(function (m) { M[m.id] = m; });
    var rk = SC.ok(all) ? (all.teams || []).map(function (r) { return r.id; }).indexOf(tid) + 1 : 0;
    var rec = T.record || [0, 0, 0];
    var yr = (T.results || []).filter(function (c) { return String(c.date).slice(0, 10) >= new Date(QK.now() - 365 * 864e5).toISOString().slice(0, 10); });
    var y12 = [0, 0, 0];
    yr.forEach(function (c) { var r = SC.result(S, c, tid); y12[r === 'W' ? 0 : r === 'D' ? 1 : 2]++; });
    var sw = T.profile ? T.profile.sw : null;
    var short = sw && sw.best.length ? t.name + ' are at their best on ' + sw.best.slice(0, 2).map(function (x) { return x.label.toLowerCase(); }).join(' and ') +
      ' (' + QK.ordinal(Math.round(sw.best[0].pct)) + ' percentile among test sides), and weakest on ' + (sw.worst[0] ? sw.worst[0].label.toLowerCase() : '') + '. Our rating has them ' + SC.signed(T.rating, 1) +
      ' points against an average side.' : t.name + ': our rating ' + SC.signed(T.rating, 1) + ' points against an average test side.';
    var html = '<nav class="sc-crumb"><a href="' + esc(SC.href(S, 'teams')) + '">Teams</a> / ' + esc(t.name) + '</nav>';
    html += QK.playerHeader({ name: t.name, face: t.abbr, kicker: SC.SNAME[S] + (rk ? ' · ' + QK.ordinal(rk) + ' in our ratings' : ''), team: { name: '', colour: t.colour, alt: t.alt },
      meta: [['Tests in our data', String(rec[0] + rec[1] + rec[2])], ['Since', SC.year(T.first)], ['All time', rec.join('–')]],
      tags: [SC.followStar(S, tid, 'sc-hero-star') || ''],
      strip: [{ label: 'Our rating', value: SC.signed(T.rating, 1), sub: rk ? QK.ordinal(rk) + ' of the sides we rate' : '', signal: true },
        { label: 'Attack', value: SC.signed(T.att, 1), sub: 'points scored v average' }, { label: 'Defence', value: SC.signed(T.dfn, 1), sub: 'points kept out v average' },
        { label: 'World Rugby', value: isNum(T.wr) ? SC.f(T.wr, 2) : '—', sub: 'points, our rebuild' }, { label: 'Last 12 months', value: y12.join('–'), sub: 'won, drawn, lost' }],
      short: short });
    var nxt = (T.next || [])[0];
    html += '<div class="qk-g2 sc-gap"><div>' + (nxt ? U.card('Next test', SC.compName(nxt.comp) + (nxt.venue ? ' · ' + esc(nxt.venue) : ''), QK.previewCard(SC.game(S, nxt), { layout: 'bug', homeFirst: true, noun: 'test' }) +
      (isNum(nxt.m) ? U.note('We expect ' + esc(SC.margin(S, nxt)) + (isNum(nxt.t) ? ', about ' + Math.round(nxt.t) + ' points in all' : '') + '.') : '')) : U.card('Next test', '', QK.empty('No test scheduled', 'The next fixture appears here once it is announced.'))) +
      (T.chances && T.chances.length ? U.card('Title chances', 'From our simulated tournaments.', QK.chances(T.chances.map(function (c) { return { label: SC.compName(c.comp) + ' ' + (c.season || ''), p: c.title || 0, href: SC.href(S, 'standings', null, 'tab=' + c.comp), color: t.colour, mark: SC.mark(S, tid) }; }), { key: false, sort: false })) : '') +
      '</div><div>' + U.card('Form', 'The last ten results.', '<div class="sc-formbig">' + U.form(T.form) + '</div>' + '<ul class="sc-list">' + (T.results || []).slice(0, 6).map(function (c) {
        var r = SC.result(S, c, tid), opp = String(c.home) === String(tid) ? c.away : c.home, home = String(c.home) === String(tid);
        var us = home ? c.hs : c.as, th = home ? c.as : c.hs;
        var p = c.p ? (home ? c.p[0] : c.p[2]) : null;
        return '<li><span class="sc-res ' + r + '">' + r + '</span><span class="s">' + esc(SC.date(c.date)) + '</span>' + (home ? 'v ' : 'at ') + U.teamEnt(S, opp) + '<a class="v" href="' + esc(SC.matchHref(S, c.id)) + '">' + us + '–' + th + '</a>' + (isNum(p) ? '<span class="s">we gave ' + SC.pct(p) + '</span>' : '') + '</li>';
      }).join('') + '</ul>') + '</div></div>';
    // the profile against every side
    if (T.profile) {
      var groups = {};
      Object.keys(T.profile.m).forEach(function (k) {
        var m = M[k];
        if (!m) return;
        (groups[m.group] = groups[m.group] || []).push({ label: m.label + (m.style ? ' (style)' : ''), pctl: T.profile.m[k].pct, value: mfmt(m, T.profile.m[k].v), tip: m.label + (m.unit === '%' ? '' : ' per test') + '; opponent-adjusted for the percentile' });
      });
      html += '<div class="qk-g75 sc-gap"><div>' + QK.pctCard({ title: 'Profile against every side', kicker: 'Per test, last two years', peer: 'test sides with six or more tests', sample: T.profile.n + ' tests since ' + SC.date(T.profile.since),
        groups: GROUP_ORDER.filter(function (g) { return groups[g]; }).map(function (g) { return { label: g, rows: groups[g] }; }) }) +
        QK.explain('<b>How sure are we?</b> ' + T.profile.n + ' tests is ' + (T.profile.n < 12 ? 'a small sample: one big win moves these a lot.' : 'a fair sample, though the opposition still matters: the percentiles are opponent-adjusted.')) +
        '</div><div>' + (QK.strengths && sw ? QK.strengths({ name: t.name, abbr: t.abbr, colour: t.colour, sub: 'Percentile among test sides', best: sw.best.map(function (x) { return { label: x.label, pctl: x.pct, text: mfmt(M[x.id], T.profile.m[x.id].v) }; }), worst: sw.worst.map(function (x) { return { label: x.label, pctl: x.pct, text: mfmt(M[x.id], T.profile.m[x.id].v) }; }) }) : '') + '</div></div>';
    }
    html += '<div class="qk-g2 sc-gap">' + U.card('Our rating over time', 'Month by month; 0 is an average test side.', U.chart('tp-rating', 300, 'Rating history')) +
      U.card('World Rugby points over time', 'Our rebuild of the official points, month by month.', U.chart('tp-wr', 300, 'World Rugby points history')) + '</div>';
    // results and fixtures
    var rcols = [{ label: 'Date', align: 'left' }, { label: 'Competition', align: 'left' }, { label: 'Opponent', align: 'left' }, { label: '' }, { label: 'Score' }, { label: 'Our chance' }];
    html += U.card('Results and fixtures', 'The last 60 tests and the next ones, with our chance for ' + esc(t.name) + ' before each.', U.table(rcols, (T.next || []).concat(T.results || []).map(function (c) {
      var home = String(c.home) === String(tid), opp = home ? c.away : c.home, us = home ? c.hs : c.as, th = home ? c.as : c.hs;
      var p = c.p ? (home ? c.p[0] : c.p[2]) : null, r = SC.result(S, c, tid);
      return [{ v: c.date, html: '<a href="' + esc(SC.matchHref(S, c.id)) + '">' + esc(SC.date(c.date)) + '</a>' }, { v: c.comp, html: esc(SC.compName(c.comp)) }, { v: SC.tname(S, opp), html: (home ? 'v ' : 'at ') + U.teamEnt(S, opp) },
        { v: r, html: r ? '<span class="sc-res ' + r + '">' + r + '</span>' : '<span class="qk-muted">Next</span>' }, { v: isNum(us) ? us - th : 0, html: isNum(us) ? us + '–' + th : '—' }, { v: p || 0, html: isNum(p) ? SC.pct(p) : '—' }];
    }), { cls: 'sc-table', maxHeight: 640 }), { flush: true });
    // head to head
    html += U.card('Head to head', 'Every opponent in our data, all time.', U.table([{ label: 'Opponent', align: 'left', sticky: true }, { label: 'P' }, { label: 'W' }, { label: 'D' }, { label: 'L' }, { label: 'Win %' }, { label: 'PF' }, { label: 'PA' }, { label: 'Last', align: 'left' }],
      (T.h2h || []).map(function (h) {
        return [{ v: SC.tname(S, h.opp), html: U.teamEnt(S, h.opp) }, { v: h.p, html: String(h.p) }, { v: h.w, html: String(h.w) }, { v: h.d, html: String(h.d) }, { v: h.l, html: String(h.l) },
          { v: h.w / h.p, html: SC.pct(h.w / h.p) }, { v: h.pf, html: String(h.pf) }, { v: h.pa, html: String(h.pa) },
          { v: h.last ? h.last.date : '', html: h.last ? '<a href="' + esc(SC.matchHref(S, h.last.id)) + '">' + h.last.us + '–' + h.last.them + ', ' + esc(SC.year(h.last.date)) + '</a>' : '' }];
      }), { cls: 'sc-table', maxHeight: 560 }), { flush: true });
    // squad and the most capped
    var pcols = [{ label: 'Player', align: 'left', sticky: true }, { label: 'Pos', align: 'left' }, { label: 'Age' }, { label: 'Caps' }, { label: 'Pts' }, { label: 'Tries' }, { label: 'Value' }, { label: 'Last test', align: 'left' }];
    var prow = function (r) {
      return [{ v: r.n, html: '<a href="' + esc(SC.playerHref(S, r.id)) + '">' + esc(r.n) + '</a>' }, { v: r.pos || '', html: '<span title="' + esc(SC.posName(r.pos)) + '">' + esc(r.pos || '') + '</span>' },
        { v: r.age || 0, html: isNum(r.age) ? String(Math.floor(r.age)) : '—' }, { v: r.caps, html: String(r.caps) }, { v: r.pts, html: String(r.pts) }, { v: r.tries, html: String(r.tries) },
        { v: isNum(r.val) ? r.val : -99, html: isNum(r.val) ? '<span class="sc-ours">' + SC.signed(r.val, 1) + '</span>' : '—' }, { v: r.last || '', html: esc(r.last ? SC.date(r.last) : '') }];
    };
    html += '<div class="qk-g2 sc-gap">' + U.card('The squad', 'Everyone capped in the last 12 months, by position. Value is our Scrum value per 80 minutes (regular players only). Caps are tests in our data.', U.table(pcols, (T.squad || []).map(prow), { cls: 'sc-table', maxHeight: 640 }), { flush: true }) +
      U.card('Most capped', 'The most tests for ' + esc(t.name) + ' in our data (since ' + esc(SC.year(T.first)) + '; older tests are missing, so these are not official cap counts).', U.table(pcols, (T.most_capped || []).map(prow), { cls: 'sc-table', maxHeight: 640 }), { flush: true }) + '</div>';
    if ((T.top_points || []).length) html += '<div class="qk-g2 sc-gap">' + U.card('Most points', 'In our data.', U.table(pcols, T.top_points.map(prow), { cls: 'sc-table' }), { flush: true }) +
      U.card('Most tries', 'In our data.', U.table(pcols, (T.top_tries || []).map(prow), { cls: 'sc-table' }), { flush: true }) + '</div>';
    page.innerHTML = html;
    U.wire(page);
    ratingChart(QK.$('#tp-rating', page), S, T);
    wrChart(QK.$('#tp-wr', page), S, T);
    document.title = t.name + ' · ' + SC.SITE;
  });
});
})();
