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
    var prows = rows.filter(function (r) { return Object.keys(r.m || {}).length; });   /* sides with a team-stats profile */
    var q = P.query || {};
    var preset = PRESETS.filter(function (p) { return p.key === q.map; })[0] || PRESETS[0];
    var html = U.sec('Power board', 'Every ranked side', 'Our rating split into attack and defence, the last ten results. The ranks are the ones on the Rankings page; sides with a provisional rating are listed there, unranked.', QK.powerBars ? QK.powerBars(null, { groups: [{ label: '', rows: rows.map(function (r, i) {
      var t = SC.team(S, r.id) || {};
      return { rank: isNum(r.rank) ? r.rank : i + 1, name: t.name, abbr: t.abbr, colour: t.colour, href: SC.teamHref(S, r.id), value: r.rating, text: SC.signed(r.rating, 1), parts: { att: r.att, dfn: r.dfn }, form: r.form,
        follow: SC.followItem(S, r.id), cells: [{ label: 'Tests rated', text: String(r.tests || r.n) }] };
    }) }], parts: [{ key: 'att', label: 'Attack', color: 'var(--c-1)' }, { key: 'dfn', label: 'Defence', color: 'var(--c-3)' }], valueLabel: 'Our rating', unit: 'points', formN: 10 }) : '');
    html += U.sec('Team profile', 'Every side on every measure', 'Per test since ' + SC.date(d.since) + ', opponent-adjusted (shifted by how much each opponent usually allows), coloured by percentile among these sides. Grey columns describe style, not quality. Only the ' + prows.length + ' ranked sides with six or more tests that our source carries team statistics for are here (it has none for the 2026 Nations Championship).', '<div id="tm-grid"></div>');
    html += U.sec('Style map', 'How they play', 'Two measures at a time; the dashed lines are the averages. Pick a pair.', '<div class="qk-chips sc-filters" id="tm-map">' + PRESETS.map(function (p) {
      return '<a class="qk-chip" href="' + esc(SC.href(S, 'teams', null, 'map=' + p.key)) + '" aria-pressed="' + (p.key === preset.key) + '">' + esc(p.label) + '</a>';
    }).join('') + '</div>' + U.card('', '', U.chart('tm-scatter', 440, preset.label)));
    var opts = prows.map(function (r) { return '<option value="' + esc(r.id) + '">' + esc(SC.tname(S, r.id)) + '</option>'; }).join('');
    var a = q.a || (prows[0] || {}).id, b = q.b || (prows[1] || {}).id;
    html += U.sec('Head to head', 'Tale of the tape', 'Two sides on the profile percentiles, the gap under each measure.', QK.scoutBar([{ label: 'Team', html: '<select class="qk-select" id="tm-a">' + opts + '</select>' },
      { label: 'v', html: '<select class="qk-select" id="tm-b">' + opts + '</select>' }]) + '<div id="tm-tape"></div>' +
      (SC.cmpHref ? '<div class="qk-chips sc-jump"><a class="qk-chip" id="tm-full" href="' + esc(SC.cmpHref(S, 't', [a, b])) + '">The full comparison: ratings, head to head, over time →</a></div>' : ''));
    html += U.sec('Strengths and weaknesses', 'Best and worst, side by side', 'Each side’s three best and three weakest measures (percentile among these sides).', '<div class="sc-sws">' + prows.slice(0, 12).map(function (r) {
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
      rows: prows.map(function (r) { var t = SC.team(S, r.id) || {}; return { id: r.id, name: t.name, sub: SC.signed(r.rating, 1), mark: { abbr: t.abbr, colour: t.colour }, href: SC.teamHref(S, r.id), vals: (function () { var o = {}; Object.keys(r.m || {}).forEach(function (k) { o[k] = r.m[k][0]; }); return o; })() }; }),
      entity: 'team', noun: 'sides', csv: 'scrum-team-profile.csv' });
    // style map
    var pts = prows.filter(function (r) { return r.m[preset.x] && r.m[preset.y]; }).map(function (r) {
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
      var A = prows.filter(function (r) { return r.id === sa.value; })[0], B = prows.filter(function (r) { return r.id === sb.value; })[0];
      if (!A || !B) return;
      var full = QK.$('#tm-full', body);
      if (full && SC.cmpHref) full.setAttribute('href', SC.cmpHref(S, 't', [A.id, B.id]));
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
var GROUP_ORDER = ['Attack', 'Defence', 'Breakdown', 'Set piece', 'Discipline', 'Kicking', 'Conversion'];
var POS_HEAD = { front_row: ['val80', 'tk', 'tkpct', 'car', 'lopct'], lock: ['val80', 'tk', 'tkpct', 'car', 'ml'], back_row: ['val80', 'tk', 'car', 'm', 'db'],
  halves: ['val80', 'pts', 'pas', 'kfh', 'gkp'], centres: ['val80', 'm', 'cb', 'db', 'off'], back_three: ['val80', 'm', 'cb', 'db', 'tries'] };
var GRADE_ORDER = ['front_row', 'lock', 'back_row', 'halves', 'centres', 'back_three'];

function boardRows(bd) {
  var cols = (bd && bd.cols) || [], out = [];
  ((bd && bd.rows) || []).forEach(function (r) { var o = {}; for (var i = 0; i < cols.length; i++) o[cols[i]] = r[i]; out.push(o); });
  return out;
}
function mfmtP(id, v) { return SC.vfmt ? SC.vfmt(id, v) : (isNum(v) ? fmt.num(v, 1) : '—'); }

/* Top performers (QKL.performers, as the other sites): the side's best regulars by Scrum value per 80, overall and in
   each position group, with the percentile and rank among every regular of that group in test rugby */
function performers(node, S, tid, all) {
  if (!node || !window.QKL || !QKL.performers) return;
  var recent = new Date(QK.now() - 400 * 864e5).toISOString().slice(0, 10);
  var q = all.filter(function (r) { return r.q && isNum(r.val80) && r.grp; });
  var rank = {}, n = {};
  GRADE_ORDER.forEach(function (g) {
    var pool = q.filter(function (r) { return r.grp === g; }).sort(function (a, b) { return b.val80 - a.val80; });
    n[g] = pool.length;
    pool.forEach(function (r, i) { rank[r.id] = i + 1; });
  });
  var row = function (r) { return { name: r.n, href: SC.playerHref(S, r.id), pos: SC.posName(r.pos), value: SC.signed(r.val80, 1), pct: r.p_val80, rank: rank[r.id], n: n[r.grp], peer: (SC.GROUP[r.grp] || '').toLowerCase() }; };
  var mine = q.filter(function (r) { return String(r.team) === String(tid) && String(r.last || '') >= recent; }).sort(function (a, b) { return b.val80 - a.val80; });
  QKL.performers(node, { title: 'Who carries them, and how they compare',
    sub: 'The best regulars by Scrum value per 80, overall and in each position group, against every regular of that group in test rugby.',
    metric: { label: 'Scrum value per 80', unit: 'points of margin per 80 minutes above a replacement-level player', model: 'Scrum value' },
    overall: mine.slice(0, 4).map(row),
    groups: GRADE_ORDER.map(function (g) { return { label: SC.GROUP[g], rows: mine.filter(function (r) { return r.grp === g; }).slice(0, 3).map(row) }; }),
    note: 'The box is the percentile among regulars of the same position group (160+ minutes in the last two years) on Scrum value per 80, our model; the rank counts the same players. Players capped in the last 13 months.',
    empty: 'No regular has 160 minutes in the last two years for this side yet.' });
}

/* Top and bottom within the squad (QKL.leaders on the side's own regulars): every key number of each position group,
   the best three and the bottom three in the squad */
function squadBoards(node, S, tid, all, M) {
  if (!node || !window.QKL || !QKL.leaders || !QKL.board) return;
  var recent = new Date(QK.now() - 400 * 864e5).toISOString().slice(0, 10);
  var mine = all.filter(function (r) { return String(r.team) === String(tid) && r.q && String(r.last || '') >= recent; });
  var mk = function (ids, rows) {
    return ids.map(function (id) {
      var m = M[id] || { id: id, label: id };
      return QKL.board(rows.map(function (r) { return { id: r.id, name: r.n, team: tid, v: r[id] }; }), { key: id, label: m.label || id, unit: '', dir: m.dir === 'lower' ? 'lower' : 'higher',
        fmt: (id === 'tkpct' || id === 'kpct' || id === 'lopct') ? 'pct1' : '1', ours: id === 'val80' ? 'Scrum value' : '', tip: '' }, 3);
    }).filter(function (x) { return x.n > 1; });
  };
  var views = [{ key: 'all', label: 'All players', entity: 'player', peer: 'regulars in the squad', min: '160 minutes in the last two years', metrics: mk(['val80', 'inv', 'm', 'tk', 'tkpct', 'pc', 'cards'], mine) }];
  GRADE_ORDER.forEach(function (g) {
    var rows = mine.filter(function (r) { return r.grp === g; });
    if (rows.length >= 2) views.push({ key: g, label: SC.GROUP[g], entity: 'player', peer: (SC.GROUP[g] || '').toLowerCase() + ' in the squad', min: '160 minutes in the last two years', metrics: mk(POS_HEAD[g], rows) });
  });
  QKL.leaders(node, { data: { views: views }, kicker: 'Top and bottom performers', title: 'Who leads the squad, and who is struggling',
    sub: 'The squad’s regulars on each key number, overall and by position group: the best three and the bottom three. Rates per 80 minutes over the last two years, shrunk toward the position average so a short stint cannot top the list.',
    team: function () { var t = SC.team(S, tid) || {}; return { abbr: t.abbr, name: t.name, colour: t.colour, href: SC.teamHref(S, tid) }; },
    href: function (id) { return SC.playerHref(S, id); }, scope: 'squad',
    empty: 'Too few regulars with 160 minutes in the last two years.' });
}

/* Roster strength by position group: the side's best regulars' Scrum value against the other ranked sides */
function gradesHtml(S, T) {
  var G = T.grades;
  if (!G) return '';
  var rows = GRADE_ORDER.filter(function (g) { return G[g]; }).map(function (g) { return { g: g, x: G[g] }; });
  if (!rows.length) return '';
  var cls = { A: 'a', B: 'b', C: 'c', D: 'd', F: 'f' };
  var tile = function (r) {
    return '<li class="sc-grade g-' + cls[r.x.grade] + '"><b>' + r.x.grade + '</b><span><span class="t">' + esc(SC.GROUP[r.g]) + '</span><small>' + QK.ordinal(r.x.rank) + ' of ' + r.x.of + ' · ' + SC.signed(r.x.v, 2) + ' a player</small></span></li>';
  };
  var srt = rows.slice().sort(function (a, b) { return a.x.rank / a.x.of - b.x.rank / b.x.of; });
  var line = function (r, best) {
    var p = best ? r.x.lead : (r.x.weak || r.x.lead);
    return '<li><span class="sc-res ' + (best ? 'W' : 'L') + '">' + r.x.grade + '</span><span><b>' + esc(SC.GROUP[r.g]) + '</b> · ' + QK.ordinal(r.x.rank) + ' of ' + r.x.of + '; ' + (best ? 'led by ' : 'weakest regular ') +
      '<a href="' + esc(SC.playerHref(S, p.id)) + '">' + esc(p.n) + '</a> (' + SC.signed(p.v, 1) + ')</span></li>';
  };
  return U.sec('Roster strength', 'What they do well, and what they need', 'Each position group’s best regulars (four front-rowers, two locks, three back-rowers, two half-backs, two centres, three in the back three) by Scrum value per 80 over the last two years, ranked against the other ranked sides: A is the top 15%, F the bottom 15%.',
    '<div class="qk-g3">' + U.card('Grades', 'A to F against the ranked sides', '<ul class="sc-grades">' + rows.map(tile).join('') + '</ul>') +
    U.card('Strengths', 'The best-graded groups', '<ul class="sc-list sc-sn">' + srt.slice(0, 2).map(function (r) { return line(r, true); }).join('') + '</ul>') +
    U.card('Needs', 'The lowest-graded groups', '<ul class="sc-list sc-sn">' + srt.slice(-2).reverse().map(function (r) { return line(r, false); }).join('') + '</ul>') + '</div>');
}

/* Who plays together: the most-used starting pairs */
function combosHtml(S, T) {
  var C = (T.combos || []).filter(function (c) { return (c.rows || []).length; });
  if (!C.length) return '';
  return U.sec('Combinations', 'Who plays together', 'The most-used starting pairs over the last four years (jerseys 9 and 10, 12 and 13, 4 and 5), with their record and points difference together.',
    '<div class="qk-g3">' + C.map(function (c) {
      return U.card(c.label, 'Starting ' + c.jerseys.join(' and '), U.table([{ label: 'Pair', align: 'left' }, { label: 'Tests' }, { label: 'W-D-L' }, { label: 'PD' }],
        c.rows.map(function (r) { return [{ v: r.an, html: '<a href="' + esc(SC.playerHref(S, r.a)) + '">' + esc(QK.surname(r.an)) + '</a> · <a href="' + esc(SC.playerHref(S, r.b)) + '">' + esc(QK.surname(r.bn)) + '</a>' },
          { v: r.n, html: String(r.n) }, { v: r.w, html: r.w + '–' + r.d + '–' + r.l }, { v: r.pd, html: '<span class="' + SC.cls(r.pd) + '">' + SC.signed(r.pd, 0) + '</span>' }]; }), { cls: 'sc-table dense' }), { flush: true });
    }).join('') + '</div>');
}

function xwChart(el, S, T) {
  if (!el || !window.QKC || !T.xw || T.xw.length < 4) return;
  var t = SC.team(S, T.id) || {};
  QKC.line(el, { x: T.xw.map(function (r) { return r[0] + 'T12:00:00Z'; }), xType: 'time', series: [{ name: 'Tests won', data: T.xw.map(function (r) { return r[1]; }), color: SC.traw(S, T.id) || 'var(--c-1)' },
    { name: 'Wins we expected', data: T.xw.map(function (r) { return r[2]; }), color: 'var(--ink-3)', dash: true }], yName: 'Wins (running total)', xName: 'Date', endLabels: true, step: 'end' });
}

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
  return Promise.all([SC.load(S + '/teams/' + tid + '.json'), SC.load(S + '/teams.json'), SC.load(S + '/players.json')]).then(function (res) {
    var T = res[0], all = res[1], bd = res[2];
    var BR = SC.ok(bd) ? boardRows(bd) : [], BM = {};
    ((SC.ok(bd) && bd.metrics) || []).forEach(function (m) { BM[m.id] = m; });
    if (!SC.ok(T)) { page.innerHTML = U.head(SC.tname(S, tid), '', SC.SNAME[S]) + U.missing('This team page', T); return; }
    var t = T.team || SC.team(S, tid) || {};
    var M = {};
    ((SC.ok(all) && all.metrics) || []).forEach(function (m) { M[m.id] = m; });
    var rk = isNum(T.rank) ? T.rank : 0;
    var rec = T.record || [0, 0, 0];
    var yr = (T.results || []).filter(function (c) { return String(c.date).slice(0, 10) >= new Date(QK.now() - 365 * 864e5).toISOString().slice(0, 10); });
    var y12 = [0, 0, 0];
    yr.forEach(function (c) { var r = SC.result(S, c, tid); y12[r === 'W' ? 0 : r === 'D' ? 1 : 2]++; });
    var sw = T.profile ? T.profile.sw : null;
    var short = sw && sw.best.length ? t.name + ' are at their best on ' + sw.best.slice(0, 2).map(function (x) { return x.label.toLowerCase(); }).join(' and ') +
      ' (' + QK.ordinal(Math.round(sw.best[0].pct)) + ' percentile among test sides), and weakest on ' + (sw.worst[0] ? sw.worst[0].label.toLowerCase() : '') + '. Our rating has them ' + SC.signed(T.rating, 1) +
      ' points against an average side.' : t.name + ': our rating ' + SC.signed(T.rating, 1) + ' points against an average test side.';
    var html = '<nav class="sc-crumb"><a href="' + esc(SC.href(S, 'teams')) + '">Teams</a> / ' + esc(t.name) + '</nav>';
    html += QK.playerHeader({ name: t.name, face: t.abbr, kicker: SC.SNAME[S] + (rk ? ' · ' + QK.ordinal(rk) + ' in our ratings' : (T.prov ? ' · provisional rating' : '')) + (T.wr_rank ? ' · ' + QK.ordinal(T.wr_rank) + ' in World Rugby’s (our rebuild)' : ''), team: { name: '', colour: t.colour, alt: t.alt },
      meta: [['Tests in our data', String(rec[0] + rec[1] + rec[2])], ['Since', SC.year(T.first)], ['All time', rec.join('–')]],
      tags: [SC.followStar(S, tid, 'sc-hero-star') || ''],
      strip: [{ label: T.prov ? 'Our rating (provisional)' : 'Our rating', value: SC.signed(T.rating, 1), sub: rk ? QK.ordinal(rk) + ' of the ' + (T.of || '') + ' sides we rank' : (T.prov ? 'too few tests against the main pool to rank' : (T.invitational ? 'an invitational side, not ranked' : '')), signal: true },
        { label: 'Attack', value: SC.signed(T.att, 1), sub: 'points scored v average' }, { label: 'Defence', value: SC.signed(T.dfn, 1), sub: 'points kept out v average' },
        { label: 'World Rugby', value: isNum(T.wr) ? SC.f(T.wr, 2) : '—', sub: T.wr_rank ? QK.ordinal(T.wr_rank) + ', points in our rebuild' : 'points, our rebuild' }, { label: 'Last 12 months', value: y12.join('–'), sub: 'won, drawn, lost' }],
      short: short });
    if (SC.cmpHref) {
      var nopp = (T.next || [])[0] ? (String(T.next[0].home) === String(tid) ? T.next[0].away : T.next[0].home) : null;
      html += '<div class="qk-chips sc-gap sc-jump"><a class="qk-chip" href="' + esc(SC.cmpHref(S, 't', nopp ? [tid, String(nopp)] : [tid])) + '">Compare' + (nopp ? ' with ' + esc(SC.tname(S, nopp)) : '') + ' →</a>' +
        '<a class="qk-chip" href="' + esc(SC.progHref(S, 't', [tid])) + '">Rating and form over time →</a></div>';
    }
    var nxt = (T.next || [])[0];
    html += '<div class="qk-g2 sc-gap"><div>' + (nxt ? U.card('Next test', SC.compName(nxt.comp) + (nxt.venue ? ' · ' + esc(nxt.venue) : ''), QK.previewCard(SC.game(S, nxt), { layout: 'bug', homeFirst: true, noun: 'test' }) +
      (isNum(nxt.m) ? U.note('We expect ' + esc(SC.margin(S, nxt)) + (isNum(nxt.t) ? ', about ' + Math.round(nxt.t) + ' points in all' : '') + '.') : '')) : U.card('Next test', '', QK.empty('No test scheduled', 'The next fixture appears here once it is announced.'))) +
      (T.chances && T.chances.length ? U.card('Title chances', 'From our simulated tournaments.', QK.chances(T.chances.map(function (c) { return { label: SC.compName(c.comp) + ' ' + (c.season || ''), p: c.title || 0, href: SC.href(S, 'standings', null, 'tab=' + c.comp), color: t.colour, mark: SC.mark(S, tid) }; }), { key: false, sort: false })) : '') +
      '</div><div>' + U.card('Form', 'The last ten results.', '<div class="sc-formbig">' + U.form(T.form) + '</div>' + '<ul class="sc-list">' + (T.results || []).slice(0, 6).map(function (c) {
        var r = SC.result(S, c, tid), opp = String(c.home) === String(tid) ? c.away : c.home, home = String(c.home) === String(tid);
        var us = home ? c.hs : c.as, th = home ? c.as : c.hs;
        var p = c.p ? (home ? c.p[0] : c.p[2]) : null;
        return '<li><span class="sc-res ' + r + '">' + r + '</span><span class="s">' + esc(SC.date(c.date)) + '</span>' + (home ? 'v ' : 'at ') + U.teamEnt(S, opp) + '<a class="v" href="' + esc(SC.matchHref(S, c.id)) + '">' + SC.scoreText(us, th, c.ro) + '</a>' + (isNum(p) ? '<span class="s">we gave ' + SC.pct(p) + '</span>' : '') + '</li>';
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
    html += '<div id="tp-top"></div>' + gradesHtml(S, T) + '<div id="tp-squad"></div>';
    if (T.xw && T.xw.length >= 4) {
      var last = T.xw[T.xw.length - 1], gap = last[1] - last[2];
      html += '<div class="qk-g75 sc-gap"><div>' + U.card('Results against our chances', 'The last ' + T.xw.length + ' tests: wins (a draw counts half) against the wins our pre-test chances expected.', U.chart('tp-xw', 280, 'Wins against expected wins')) + '</div><div>' +
        QK.explain('<b>Who’s for real?</b> ' + esc(t.name) + ' won ' + SC.f(last[1], 1) + ' of these tests against ' + SC.f(last[2], 1) + ' expected: ' + (Math.abs(gap) < 1.5 ? 'about what the numbers said.' : gap > 0 ? SC.f(gap, 1) + ' more, close wins and upsets that seldom last.' : SC.f(-gap, 1) + ' fewer, near misses that tend to turn.')) + '</div></div>';
    }
    html += '<div class="qk-g2 sc-gap">' + U.card('Our rating over time', 'Month by month since ' + esc(SC.year((T.rating_hist || [[''] ])[0][0])) + ' (results before ESPN’s coverage from Wikipedia); 0 is an average test side.', U.chart('tp-rating', 300, 'Rating history')) +
      U.card('World Rugby points over time', 'Our rebuild of the official points, month by month.', U.chart('tp-wr', 300, 'World Rugby points history')) + '</div>';
    // results and fixtures
    var rcols = [{ label: 'Date', align: 'left' }, { label: 'Competition', align: 'left' }, { label: 'Opponent', align: 'left' }, { label: '' }, { label: 'Score' }, { label: 'Our chance' }];
    html += U.card('Results and fixtures', 'The last 60 tests and the next ones, with our chance for ' + esc(t.name) + ' before each.', U.table(rcols, (T.next || []).concat(T.results || []).map(function (c) {
      var home = String(c.home) === String(tid), opp = home ? c.away : c.home, us = home ? c.hs : c.as, th = home ? c.as : c.hs;
      var p = c.p ? (home ? c.p[0] : c.p[2]) : null, r = SC.result(S, c, tid);
      return [{ v: c.date, html: '<a href="' + esc(SC.matchHref(S, c.id)) + '">' + esc(SC.date(c.date)) + '</a>' }, { v: c.comp, html: esc(SC.compName(c.comp)) }, { v: SC.tname(S, opp), html: (home ? 'v ' : 'at ') + U.teamEnt(S, opp) },
        { v: r, html: r ? '<span class="sc-res ' + r + '">' + r + '</span>' : '<span class="qk-muted">Next</span>' }, { v: isNum(us) ? us - th : 0, html: isNum(us) ? SC.scoreText(us, th, c.ro) : '—' }, { v: p || 0, html: isNum(p) ? SC.pct(p) : '—' }];
    }), { cls: 'sc-table', maxHeight: 640 }), { flush: true });
    // head to head
    html += U.card('Head to head', 'Every opponent in our data, all time (from ' + esc(SC.year(T.first)) + '; points for and against leave out the tests before 1891, which have the result only).', U.table([{ label: 'Opponent', align: 'left', sticky: true }, { label: 'P' }, { label: 'W' }, { label: 'D' }, { label: 'L' }, { label: 'Win %' }, { label: 'PF' }, { label: 'PA' }, { label: 'Last', align: 'left' }],
      (T.h2h || []).map(function (h) {
        return [{ v: SC.tname(S, h.opp), html: U.teamEnt(S, h.opp) }, { v: h.p, html: String(h.p) }, { v: h.w, html: String(h.w) }, { v: h.d, html: String(h.d) }, { v: h.l, html: String(h.l) },
          { v: h.w / h.p, html: SC.pct(h.w / h.p) }, { v: h.pf, html: String(h.pf) }, { v: h.pa, html: String(h.pa) },
          { v: h.last ? h.last.date : '', html: h.last ? '<a href="' + esc(SC.matchHref(S, h.last.id)) + '">' + SC.scoreText(h.last.us, h.last.them, h.last.ro) + ', ' + esc(SC.year(h.last.date)) + '</a>' : '' }];
      }), { cls: 'sc-table', maxHeight: 560 }), { flush: true });
    html += combosHtml(S, T);
    // squad and the most capped
    var pcols = [{ label: 'Player', align: 'left', sticky: true }, { label: 'Pos', align: 'left' }, { label: 'Age' }, { label: 'Caps' }, { label: 'Pts' }, { label: 'Tries' }, { label: 'Value' }, { label: 'Last test', align: 'left' }];
    var hasW = (T.squad || []).some(function (r) { return isNum(r.wcaps); });
    var prow = function (r) {
      return [{ v: r.n, html: '<a href="' + esc(SC.playerHref(S, r.id)) + '">' + esc(r.n) + '</a>' }, { v: r.pos || '', html: '<span title="' + esc(SC.posName(r.pos)) + '">' + esc(r.pos || '') + '</span>' },
        { v: r.age || 0, html: isNum(r.age) ? String(Math.floor(r.age)) : '—' }, { v: isNum(r.wcaps) ? r.wcaps : r.caps, html: isNum(r.wcaps) ? '<b title="Career caps (Wikipedia)">' + r.wcaps + '</b>' + (r.wcaps !== r.caps ? ' <span class="qk-muted" title="Tests in our data">' + r.caps + '</span>' : '') : String(r.caps) }, { v: r.pts, html: String(r.pts) }, { v: r.tries, html: String(r.tries) },
        { v: isNum(r.val) ? r.val : -99, html: isNum(r.val) ? '<span class="sc-ours">' + SC.signed(r.val, 1) + '</span>' : '—' }, { v: r.last || '', html: esc(r.last ? SC.date(r.last) : '') }];
    };
    var careerCard = (T.career_caps || []).length ? U.card('Most capped, all time', 'Career caps for ' + esc(t.name) + ', from Wikipedia’s records (CC BY-SA 4.0), as of ' + esc(SC.date(T.caps_asof)) + '.',
      U.table([{ label: 'Player', align: 'left', sticky: true }, { label: 'Caps' }, { label: 'Career', align: 'left' }], T.career_caps.map(function (r) {
        return [{ v: r.name, html: r.id ? '<a href="' + esc(SC.playerHref(S, r.id)) + '">' + esc(r.name) + '</a>' : esc(r.name) }, { v: r.caps, html: '<b>' + r.caps + '</b>' }, { v: r.years || '', html: esc(r.years || '') }];
      }), { cls: 'sc-table', maxHeight: 640 }), { flush: true }) : '';
    html += '<div class="qk-g2 sc-gap">' + U.card('The squad', 'Everyone capped in the last 12 months, by position. Value is our Scrum value per 80 minutes (regular players only). ' + (hasW ? 'Caps in bold are career caps (Wikipedia’s squad list); the grey number is tests in our data.' : 'Caps are tests in our data.'), U.table(pcols, (T.squad || []).map(prow), { cls: 'sc-table', maxHeight: 640 }), { flush: true }) + careerCard +
      '</div><div class="qk-g2 sc-gap">' +
      U.card('Most capped', 'The most tests for ' + esc(t.name) + ' in our data (since ' + esc(SC.year(T.first)) + '; older tests are missing, so these are not official cap counts).', U.table(pcols, (T.most_capped || []).map(prow), { cls: 'sc-table', maxHeight: 640 }), { flush: true }) + '</div>';
    if ((T.top_points || []).length) html += '<div class="qk-g2 sc-gap">' + U.card('Most points', 'In our data.', U.table(pcols, T.top_points.map(prow), { cls: 'sc-table' }), { flush: true }) +
      U.card('Most tries', 'In our data.', U.table(pcols, (T.top_tries || []).map(prow), { cls: 'sc-table' }), { flush: true }) + '</div>';
    page.innerHTML = html;
    U.wire(page);
    ratingChart(QK.$('#tp-rating', page), S, T);
    xwChart(QK.$('#tp-xw', page), S, T);
    performers(QK.$('#tp-top', page), S, tid, BR);
    squadBoards(QK.$('#tp-squad', page), S, tid, BR, BM);
    wrChart(QK.$('#tp-wr', page), S, T);
    document.title = t.name + ' · ' + SC.SITE;
  });
});
})();
