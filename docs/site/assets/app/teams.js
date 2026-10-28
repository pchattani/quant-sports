/* The Quant Footballer — a competition's Teams tab (#/competition/<slug>/teams; "Nations" on national-team
 * competitions), round 9 (28 Oct 2026, the Bullpen pilot's design, bp-teams.js). It replaces the Power, Analytics and
 * Clubs tabs and the Race tab's team cards: every club ranked, profiled and set against the rest.
 *
 * Sections (a chip strip jumps between them):
 *   1. Power board: each club ranked by our rating (expected points a game against an average side, strength.json),
 *      the bar its xG margin a match split into attack (xG for above the competition's average) and defence (xG
 *      against below it) around zero, the total as the volt tick; points, expected points, Elo, the last six and our
 *      chances (title or trophy, the top band, the drop), quiet; by conference where the competition has them (?pw=).
 *   2. Team profile: the heat grid of clubs by every team metric (analytics.json team_metrics: Attack, Defence,
 *      Results, Style, Discipline, Physical, plus set pieces and our ratings), phase chips, percentile cells, sortable,
 *      rows linked, any metric added, CSV (?grid=, gadd=, gsort=).
 *   3. Style map: any two team metrics, presets (xG for against xG against, pressing against possession, set pieces
 *      against open play, field tilt against shot quality, our rating against points), the medians and the four
 *      corners named (?map=, mx=, my=).
 *   4. Strengths and weaknesses: each club's three best and three worst process metrics against the competition.
 *   5. Head to head: two clubs on the tale of the tape with the gap in percentile points (?a=, b=), and a link to
 *      Teams › Head to head for "If they met" (the pooled model).
 *   6. Through the season: xG difference, points or Elo match by match for the clubs picked (analytics.json rounds,
 *      strength.json elo_history: no new data) (?trend=, clubs=).
 *   7. The team of the week and the best XIs of the season (competition.js FB.compXI, the old Analytics tab's).
 * Percentiles are ranked among the clubs on screen with lower-is-better flipped. ES5: no optional chaining, no
 * nullish coalescing. */
(function (FB) {
'use strict';

var QK = window.QK, QKC = window.QKC;
var esc = FB.esc, isNum = FB.isNum, num = FB.num, pct = FB.pct, signed = FB.signed;

var ST = {}, D = null, CTX = null, C = null, T = [], META = {}, MS = [], ROWS = {}, AN = {}, SP = {}, PR = {}, HOST = null;
/* metrics beyond analytics.json's team_metrics: our ratings, Elo and the set-piece split (analytics.json set_pieces) */
var EXTRA = [
  { key: 'rating', label: 'Our rating (points a game)', fmt: '2', group: 'Our models', desc: 'Our team rating: the points a game we would expect against an average side of this competition at a neutral ground (Dixon-Coles on goals and xG).', ours: true },
  { key: 'elo', label: 'Elo', fmt: '0', group: 'Our models', desc: 'Our Elo rating, replayed over the season’s matches.' },
  { key: 'sp_xg', label: 'Set-piece xG for', fmt: '2', group: 'Set pieces', desc: 'Expected goals from corners, free kicks and throw-ins, per match.' },
  { key: 'sp_xga', label: 'Set-piece xG against', fmt: '2', group: 'Set pieces', lower: true, desc: 'Expected goals conceded from set pieces, per match. Lower is better.' },
  { key: 'op_xg', label: 'Open-play xG for', fmt: '2', group: 'Set pieces', desc: 'Expected goals from open play, per match.' },
  { key: 'op_xga', label: 'Open-play xG against', fmt: '2', group: 'Set pieces', lower: true, desc: 'Expected goals conceded from open play, per match. Lower is better.' },
  { key: 'sp_share', label: 'Share of xG from set pieces', fmt: 'pct100', group: 'Set pieces', style: true, desc: 'How much of the club’s xG comes from set pieces: style, neither better nor worse.' }
];
/* style metrics: neither better nor worse (grey in the grid, never a strength) */
var STYLE = { luck: 1, possession: 1, passes: 1, long_ball_share: 1, crosses: 1, dribbles: 1, sp_share: 1, corners: 1, km: 1, sprints: 1, fouls: 0, cards: 0 };
var SW_POOL = ['xg_for', 'xg_against', 'xg_diff', 'shots', 'shots_against', 'shot_quality', 'shot_quality_against', 'sot_pct', 'big_chances', 'field_tilt', 'ppda',
  'aerial_pct', 'ground_duel_pct', 'pass_pct', 'finishing', 'keeping', 'sp_xg', 'sp_xga', 'op_xg', 'op_xga', 'rating'];
var H2H = [['Strength', ['rating', 'xg_diff', 'xpts_per_match', 'elo']], ['Attack', ['xg_for', 'shots', 'shot_quality', 'big_chances', 'sp_xg', 'finishing']],
  ['Defence', ['xg_against', 'shots_against', 'shot_quality_against', 'sp_xga', 'keeping']], ['Style', ['possession', 'field_tilt', 'ppda', 'pass_pct']]];
/* [label, x, y, corners { tl, tr, bl, br }]: better is up and to the right (lower-is-better axes flipped) */
var PRESETS = [
  ['xG for against xG against', 'xg_for', 'xg_against', { tl: 'Solid, blunt', tr: 'Strong both ways', bl: 'Struggling', br: 'Open games' }],
  ['Pressing against possession', 'possession', 'ppda', { tl: 'Press without the ball', tr: 'Press and keep it', bl: 'Sit deep, play direct', br: 'Patient, little press' }],
  ['Set pieces against open play', 'op_xg', 'sp_xg', { tl: 'Set-piece specialists', tr: 'Threat from everywhere', bl: 'Little threat', br: 'Open-play sides' }],
  ['Territory against chance quality', 'field_tilt', 'shot_quality', { tl: 'Few, good chances', tr: 'Camped in, good chances', bl: 'Pinned back', br: 'Pressure, poor chances' }],
  ['Our rating against points', 'rating', 'xpts_per_match', { tl: 'Due a run', tr: 'The real deal', bl: 'Struggling', br: 'Winning on luck?' }]
];

function intl() { return C && (C.scope === 'international' || FB.familyOf(C) === 'international'); }
function word() { return intl() ? 'team' : 'club'; }
function words() { return intl() ? 'teams' : 'clubs'; }
function meta(id) {
  var m = META[id] || { key: id, label: id };
  var f = m.fmt || '2';
  return { id: id, label: m.label || id, short: m.label || id, tip: m.desc || '', lower: !!m.lower, style: !!STYLE[id], ours: m.ours ? { name: 'Team rating model', about: '' } : null,
    fmt: function (v) { return !isNum(v) ? '—' : f === 'pct100' ? Math.round(v * 100) + '%' : f === '0' ? num(v, 0) : FB.fmtMetric(v, f); } };
}
function v(t, id) {
  if (id === 'rating') { var s = ROWS[t]; return s && isNum(s.strength_ppg) ? s.strength_ppg : null; }
  if (id === 'elo') { var e = ROWS[t]; return e && isNum(e.elo) ? e.elo : null; }
  if (/^(sp_|op_)/.test(id)) { var x = SP[t]; return x && isNum(x[id]) ? x[id] : null; }
  var p = (((AN[t] || {}).profile) || {})[id];
  return p && isNum(p.v) ? p.v : null;
}
/* percentile among the clubs on screen, 100 = best (lower-is-better flipped); null for style metrics in a strength read */
function pc(t, id) {
  var xs = T.map(function (u) { return v(u, id); }).filter(isNum).sort(function (a, b) { return a - b; }), y = v(t, id);
  if (!isNum(y) || xs.length < 4) return null;
  var q = QK.pctRank(xs, y);
  return meta(id).lower ? 100 - q : q;
}
function tid(t) { return CTX.tidOf(t); }
function tinfo(t) {
  var id = tid(t), nm = (id && FB.clubName(id)) || t;
  return { id: id, name: nm, abbr: FB.clubCode(nm), colour: id ? FB.clubColour(id) : null, alt: id ? FB.clubAlt(id) : null, href: id ? FB.href.club(id, { c: C.slug }) : null };
}
function byRating(list) { return list.slice().sort(function (a, b) { var x = v(a, 'rating'), y = v(b, 'rating'); return (isNum(y) ? y : -9) - (isNum(x) ? x : -9) || String(a).localeCompare(String(b)); }); }
function setQ(patch) { FB.setQuery(patch); }

var SECS = [['tm-power', 'Power board'], ['tm-sos', 'Schedule'], ['tm-grid', 'Team profile'], ['tm-map', 'Style map'], ['tm-sw', 'Strengths and weaknesses'], ['tm-h2h', 'Head to head'], ['tm-trend', 'Through the season'], ['tm-xi', 'Teams of the week']];

/* el: the page, body: the tab's box, c: the competition, d: { meta, teams, fixtures, strength, analytics, probs, table },
   ctx: competition.js makeCtx, q: the query, xi(el, host): the team-of-the-week renderer */
FB.teamsTab = function (el, body, c, d, ctx, q, xi) {
  C = c; D = d; CTX = ctx; HOST = el;
  q = q || {};
  ST = { pw: q.pw === 'all' ? 'all' : 'group', grid: q.grid || '', gadd: q.gadd ? String(q.gadd).split(',').filter(Boolean) : [], gsort: q.gsort ? { key: q.gsort, dir: q.gdir === 'asc' ? 'asc' : 'desc' } : null,
    map: isNum(q.map) ? Number(q.map) : 0, mx: q.mx || '', my: q.my || '', a: q.a || '', b: q.b || '', trend: ['xgd', 'pts', 'elo'].indexOf(q.trend) >= 0 ? q.trend : 'xgd', clubs: q.clubs ? String(q.clubs).split(',').filter(Boolean) : [] };
  ROWS = {}; ((d.strength || {}).rows || []).forEach(function (r) { ROWS[r.team] = r; });
  AN = (d.analytics || {}).teams || {};
  SP = ((d.analytics || {}).set_pieces || {}).teams || {};
  PR = {}; ((d.probs || {}).teams || []).forEach(function (r) { PR[r.team] = r; });
  MS = ((d.analytics || {}).team_metrics || []).concat(EXTRA);
  META = {}; MS.forEach(function (m) { META[m.key] = m; });
  var names = {};
  Object.keys(ROWS).concat(Object.keys(AN)).forEach(function (t) { names[t] = 1; });
  T = Object.keys(names);
  if (!T.length) { body.innerHTML = FB.empty('No ' + words() + ' to compare yet', 'The Teams tab fills once the competition has played matches.'); return; }
  body.innerHTML = '<nav class="tm-jump" aria-label="On this page"><div class="qk-chips scroll">' + SECS.map(function (s) { return '<a class="qk-chip" href="#' + s[0] + '" data-jump="' + s[0] + '">' + esc(s[0] === 'tm-power' && intl() ? 'Power board' : s[1]) + '</a>'; }).join('') + '</div></nav>' +
    SECS.map(function (s) { return '<section class="qk-section tm-sec" id="' + s[0] + '"></section>'; }).join('');
  QK.$$('[data-jump]', body).forEach(function (a) { a.addEventListener('click', function (ev) {
    ev.preventDefault();
    var t = document.getElementById(a.getAttribute('data-jump'));
    if (!t) return;
    var off = ['.qk-topbar', '.qk-secnav'].reduce(function (s, sel) { return s + ((document.querySelector(sel) || {}).offsetHeight || 0); }, 0) + 12;
    window.scrollTo({ top: t.getBoundingClientRect().top + window.scrollY - off, behavior: QK.reducedMotion && QK.reducedMotion() ? 'auto' : 'smooth' });
  }); });
  power(); schedule(); grid(); styleMap(); strengths(); h2h(); trend();
  var xh = document.getElementById('tm-xi');
  if (xh && xi) xi(el, xh); else if (xh) xh.remove();
};

/* 1. the power board */
function power() {
  var host = document.getElementById('tm-power');
  if (!host) return;
  var rated = T.filter(function (t) { var r = ROWS[t]; return r && r.played > 0 && isNum(r.xg_for) && isNum(r.xg_against); });
  if (rated.length < 3) { host.innerHTML = ''; return; }
  var per = function (t, k) { var r = ROWS[t]; return r[k] / r.played; };
  var mf = rated.reduce(function (s, t) { return s + per(t, 'xg_for'); }, 0) / rated.length;
  var ma = rated.reduce(function (s, t) { return s + per(t, 'xg_against'); }, 0) / rated.length;
  var all = byRating(rated);
  var rk = {}; all.forEach(function (t, i) { rk[t] = i + 1; });
  var fk = C.kind === 'conference' || C.kind === 'playoff' || C.kind === 'cup' ? 'p_cup' : 'p_title';
  var bands = ((D.probs || {}).bands || []);
  var up = bands.filter(function (b) { return b.kind === 'up'; })[0], dn = bands.filter(function (b) { return b.kind === 'down'; });
  var row = function (t) {
    var i = tinfo(t), r = ROWS[t], p = PR[t] || {}, att = per(t, 'xg_for') - mf, def = ma - per(t, 'xg_against');
    var ch = [];
    if (isNum(p[fk])) ch.push({ label: fk === 'p_title' ? 'Title' : 'Trophy', p: p[fk] });
    if (up && p.bands && isNum(p.bands[up.key])) ch.push({ label: up.label, p: p.bands[up.key] });
    if (dn.length && p.bands) { var s = dn.reduce(function (a, b) { return a + (p.bands[b.key] || 0); }, 0); if (s > 0.0005) ch.push({ label: dn.length > 1 ? 'Drop' : dn[0].label, p: s }); }
    return { rank: rk[t], name: i.name, abbr: i.abbr, colour: i.colour, href: i.href, sub: (r.points !== undefined ? r.points + ' pts from ' + r.played : r.played + ' played'),
      value: att + def, text: signed(att + def, 2), parts: { att: att, def: def },
      cells: [{ label: 'Our rating', text: isNum(r.strength_ppg) ? num(r.strength_ppg, 2) : '—' }, { label: 'Points', text: isNum(r.points) ? String(r.points) : '—' },
        { label: 'Expected', text: isNum(r.expected_points) ? num(r.expected_points, 1) : '—' }, { label: 'Elo', text: isNum(r.elo) ? num(r.elo, 0) : '—' }],
      form: (r.form_results || []).join(''), chances: ch };
  };
  var confs = Array.from(new Set(rated.map(function (t) { return ROWS[t].conference; }).filter(Boolean))).sort();
  var groups = ST.pw === 'group' && confs.length > 1 ? confs.map(function (g) { return { label: g, rows: all.filter(function (t) { return ROWS[t].conference === g; }).map(row) }; }) : [{ label: '', rows: all.map(row) }];
  host.innerHTML = QK.sectionHead({ kicker: 'Power board', title: 'Every ' + word() + ', ranked by our rating',
    sub: 'Ranked by our rating: the points a game we expect against an average side here. The bar is the xG margin a match, split into attack (xG created above the ' + (intl() ? 'tournament' : 'competition') + '’s average) and defence (xG allowed below it); the volt tick is the margin.' +
      (D.meta && D.meta.n_sims > 0 && !D.meta.unsimulated ? ' Chances come from ' + FB.int(D.meta.n_sims) + ' simulated seasons.' : ''),
    actions: confs.length > 1 ? FB.seg('tm-pw', [['group', 'By conference'], ['all', 'All ' + all.length]], ST.pw, 'Group the board') : '' }) +
    '<div class="qk-card"><div class="qk-card-body">' + QK.powerBars(null, { groups: groups, valueLabel: 'xG margin', unit: 'goals a match', formLabel: 'Last 6', formN: 6,
      parts: [{ key: 'att', label: 'Attack', color: 'var(--c-2)' }, { key: 'def', label: 'Defence', color: 'var(--c-3)' }] }) + '</div></div>' +
    QK.explain('An <b>xG margin of +1.0</b> means a ' + word() + ' creates a goal’s worth of chances a match more than it allows. The ranking is our rating, which also weighs the goals actually scored and the opposition: the two disagree most for a ' + word() + ' with a kind or hard schedule so far. The full table is on <a href="' + esc(FB.href.comp(C.slug, 'table')) + '">' + (C.kind === 'cup' ? 'the table' : 'Table') + '</a>.', { title: 'What’s that number?' });
  FB.wireSeg(host, 'tm-pw', function (x) { ST.pw = x; setQ({ pw: x === 'all' ? 'all' : null }); power(); });
}

/* 1b. strength of schedule (round 9, Phase 4): the average rating of the opponents each club has played and has still
   to play (strength.json sos_played / sos_remaining: our rating, points a game against an average side), the hardest
   run-in first; the gap is how much easier or harder the rest of the season is than the start. */
function schedule() {
  var host = document.getElementById('tm-sos');
  if (!host) return;
  var rows = T.filter(function (t) { var r = ROWS[t]; return r && isNum(r.sos_played) && isNum(r.sos_remaining); });
  if (rows.length < 4) { host.innerHTML = ''; return; }
  rows.sort(function (a, b) { return ROWS[b].sos_remaining - ROWS[a].sos_remaining; });
  var hard = rows[0], easy = rows[rows.length - 1];
  var swing = rows.slice().sort(function (a, b) { return (ROWS[b].sos_remaining - ROWS[b].sos_played) - (ROWS[a].sos_remaining - ROWS[a].sos_played); })[0];
  host.innerHTML = QK.sectionHead({ kicker: 'Schedule', title: 'Who has the hardest run-in?', sub: 'The average rating of the opponents each ' + word() + ' has played so far and has still to play (our rating: the points a game an opponent would take against an average side). Hardest run-in first.' }) +
    FB.kpis([
      FB.kpi('Hardest run-in', esc(tinfo(hard).name), { text: true, sub: 'opponents average ' + num(ROWS[hard].sos_remaining, 2) + ' points a game' }),
      FB.kpi('Easiest run-in', esc(tinfo(easy).name), { text: true, sub: 'opponents average ' + num(ROWS[easy].sos_remaining, 2) }),
      FB.kpi('Biggest step up', esc(tinfo(swing).name), { text: true, sub: signed(ROWS[swing].sos_remaining - ROWS[swing].sos_played, 2) + ' against the start of the season' })
    ]) +
    '<div class="qk-card fb-mt"><div class="qk-card-body"><div id="tm-sos-c" class="qk-chart" style="--h:' + Math.max(320, rows.length * 24 + 70) + 'px" role="img" aria-label="Strength of schedule"></div></div></div>' +
    QK.explain('A difference of <b>0.10</b> in the average opponent is worth roughly a tenth of a point a match: over ten matches, about one point. The next five opponents of each club, coloured by our chance of winning each, are on the <a href="' + esc(FB.href.comp(C.slug, 'race')) + '">Race</a> tab.', { title: 'What’s that number?' });
  QKC.bar(document.getElementById('tm-sos-c'), { horizontal: true, legend: true, labelWidth: 130, fmt: function (v) { return num(v, 2); }, cats: rows.map(function (t) { return tinfo(t).name; }),
    series: [{ name: 'Played so far', data: rows.map(function (t) { return ROWS[t].sos_played; }), color: QK.cssVar('--ink-4') }, { name: 'Still to play', data: rows.map(function (t) { return ROWS[t].sos_remaining; }), color: QK.cssVar('--signal') }],
    min: Math.max(0, Math.floor(Math.min.apply(null, rows.map(function (t) { return Math.min(ROWS[t].sos_played, ROWS[t].sos_remaining); })) * 10) / 10 - 0.1),
    valName: 'Average opponent rating (points a game)', catName: intl() ? 'Team' : 'Club', label: 'Strength of schedule' });
}

/* 2. the team profile grid */
function grid() {
  var host = document.getElementById('tm-grid');
  if (!host) return;
  var haveK = function (id) { return T.filter(function (t) { return isNum(v(t, id)); }).length >= 4; };
  var groupsOf = {};
  MS.forEach(function (m) { if (!haveK(m.key)) return; (groupsOf[m.group || 'Other'] = groupsOf[m.group || 'Other'] || []).push(m.key); });
  var order = ['Our models', 'Results', 'Attack', 'Defence', 'Set pieces', 'Style', 'Discipline', 'Physical', 'Other'];
  var gk = Object.keys(groupsOf).sort(function (a, b) { return (order.indexOf(a) < 0 ? 99 : order.indexOf(a)) - (order.indexOf(b) < 0 ? 99 : order.indexOf(b)); });
  if (!gk.length) { host.innerHTML = ''; return; }
  var overview = ['rating', 'xg_diff', 'xpts_per_match', 'xg_for', 'xg_against', 'field_tilt', 'ppda', 'possession', 'luck'].filter(haveK);
  var sets = [{ key: 'overview', label: 'Overview', groups: [{ label: 'Overview', ids: overview }] }].concat(gk.map(function (g) { return { key: g.toLowerCase().replace(/[^a-z]+/g, '-'), label: g, groups: [{ label: g, ids: groupsOf[g] }] }; }));
  var rows = byRating(T).map(function (t) { var i = tinfo(t), r = ROWS[t] || {}; return { id: t, name: i.name, sub: (isNum(r.played) ? r.played + ' played' : '') + (isNum(r.points) ? ' · ' + r.points + ' pts' : ''), mark: { abbr: i.abbr, colour: i.colour }, href: i.href || '' }; });
  var addable = gk.map(function (g) { return '<optgroup label="' + esc(g) + '">' + groupsOf[g].map(function (k) { return '<option value="' + esc(k) + '">' + esc(meta(k).label) + '</option>'; }).join('') + '</optgroup>'; }).join('');
  var nM = gk.reduce(function (s, g) { return s + groupsOf[g].length; }, 0);
  host.innerHTML = QK.sectionHead({ kicker: 'Team profile', title: T.length + ' ' + words() + ', every metric', sub: 'Each cell is the ' + word() + '’s value, coloured by its percentile among the ' + T.length + ' (blue worst, red best; a ↓ marks a metric where lower is better, grey is style). Pick a phase, add any of the ' + nM + ' metrics, sort by any column, tap a ' + word() + ' for its page.' }) +
    '<div class="qk-card"><div class="qk-card-body"><div id="tm-hg"></div></div></div>';
  QK.heatGrid(document.getElementById('tm-hg'), {
    id: 'tm-hgr', sets: sets, set: sets.some(function (s) { return s.key === ST.grid; }) ? ST.grid : 'overview', setsLabel: 'Phase', added: ST.gadd.filter(haveK), sort: ST.gsort || { key: overview[0] || 'rating', dir: 'desc' },
    nameLabel: intl() ? 'Team' : 'Club', subLabel: 'Played · points', noun: words(), meta: meta, addable: addable,
    rows: rows, val: function (r, id) { return v(r.id, id); },
    csv: 'footballer-' + C.slug + '-teams.csv',
    onState: function (st) { ST.grid = st.set === 'overview' ? '' : st.set; ST.gadd = st.added; ST.gsort = st.sort; setQ({ grid: ST.grid || null, gadd: ST.gadd.length ? ST.gadd.join(',') : null, gsort: st.sort && st.sort.key !== (overview[0] || 'rating') ? st.sort.key : null, gdir: st.sort && st.sort.key !== (overview[0] || 'rating') ? st.sort.dir : null }); }
  });
}

/* 3. the style map */
function styleMap() {
  var host = document.getElementById('tm-map');
  if (!host) return;
  var avail = function (id) { return T.filter(function (t) { return isNum(v(t, id)); }).length >= 5; };
  var opts = MS.filter(function (m) { return avail(m.key); }).map(function (m) { return { value: m.key, label: meta(m.key).label }; });
  var P = PRESETS.filter(function (p) { return avail(p[1]) && avail(p[2]); });
  if (!P.length && opts.length < 2) { host.innerHTML = ''; return; }
  if (ST.map >= P.length) ST.map = 0;
  var cur = ST.map >= 0 ? P[ST.map] : null;
  var x = cur ? cur[1] : (ST.mx || (opts[0] || {}).value), y = cur ? cur[2] : (ST.my || (opts[1] || {}).value);
  var sel = function (id, val) { return '<select class="qk-select" id="' + id + '">' + opts.map(function (o) { return '<option value="' + esc(o.value) + '"' + (o.value === val ? ' selected' : '') + '>' + esc(o.label) + '</option>'; }).join('') + '</select>'; };
  host.innerHTML = QK.sectionHead({ kicker: 'Style map', title: 'How each ' + word() + ' plays', sub: 'Any two team metrics against each other. The dashed lines are the medians; better is always up and to the right (axes where less is better are flipped). Tap a ' + word() + ' for its page.' }) +
    '<div class="qk-card"><div class="qk-card-body">' + QK.scoutBar([
      { label: 'Preset', html: '<select class="qk-select" id="tm-preset">' + P.map(function (p, i) { return '<option value="' + i + '"' + (i === ST.map ? ' selected' : '') + '>' + esc(p[0]) + '</option>'; }).join('') + '<option value="-1"' + (ST.map < 0 ? ' selected' : '') + '>Any two metrics</option></select>' },
      { label: 'Across', html: sel('tm-mx', x) }, { label: 'Up', html: sel('tm-my', y) }]) +
    '<div id="tm-map-c" class="qk-chart" style="--h:520px;margin-top:16px" role="img" aria-label="Style map"></div><p class="fb-cap" id="tm-map-n"></p></div></div>';
  var $ = function (id) { return document.getElementById(id); };
  $('tm-preset').onchange = function (e) { ST.map = parseInt(e.target.value, 10); if (ST.map < 0) { ST.mx = x; ST.my = y; } setQ({ map: ST.map ? ST.map : null, mx: ST.map < 0 ? ST.mx : null, my: ST.map < 0 ? ST.my : null }); styleMap(); };
  $('tm-mx').onchange = function (e) { ST.map = -1; ST.mx = e.target.value; ST.my = $('tm-my').value; setQ({ map: -1, mx: ST.mx, my: ST.my }); styleMap(); };
  $('tm-my').onchange = function (e) { ST.map = -1; ST.my = e.target.value; ST.mx = $('tm-mx').value; setQ({ map: -1, mx: ST.mx, my: ST.my }); styleMap(); };
  var mx = meta(x), my = meta(y);
  var pts = T.filter(function (t) { return isNum(v(t, x)) && isNum(v(t, y)); }).map(function (t) { var i = tinfo(t); return { x: v(t, x), y: v(t, y), name: i.name, label: i.abbr, color: i.colour || null, size: 15, href: i.href }; });
  var corners = cur ? cur[3] : { tl: '', tr: 'Better on both', bl: 'Worse on both', br: '' };
  QKC.scatter($('tm-map-c'), { points: pts, labelAll: true, refX: FB.median(pts.map(function (p) { return p.x; })), refY: FB.median(pts.map(function (p) { return p.y; })), xInverse: mx.lower, yInverse: my.lower, pad: '9%',
    xName: mx.label + (mx.lower ? ' (lower is better: flipped)' : ''), yName: my.label + (my.lower ? ' (lower is better: flipped)' : ''), xFmt: mx.fmt, yFmt: my.fmt,
    quadrants: [corners.tl, corners.tr, corners.bl, corners.br], label: my.label + ' against ' + mx.label });
  $('tm-map-n').innerHTML = '<b>' + esc(mx.label) + '</b>: ' + esc(mx.tip) + ' <b>' + esc(my.label) + '</b>: ' + esc(my.tip);
}

/* 4. strengths and weaknesses */
function strengths() {
  var host = document.getElementById('tm-sw');
  if (!host) return;
  var pool = SW_POOL.filter(function (id) { return META[id] && T.filter(function (t) { return isNum(v(t, id)); }).length >= 5; });
  if (pool.length < 6) { host.innerHTML = ''; return; }
  var cards = byRating(T).map(function (t) {
    var i = tinfo(t), r = ROWS[t] || {};
    var xs = pool.map(function (id) { return { id: id, p: pc(t, id) }; }).filter(function (o) { return isNum(o.p); });
    var chip = function (o) { var m = meta(o.id); return { label: m.label, pctl: o.p, text: m.fmt(v(t, o.id)), tip: m.tip }; };
    return QK.strengths({ name: i.name, abbr: i.abbr, colour: i.colour, href: i.href, sub: (isNum(r.points) ? r.points + ' pts · ' : '') + 'rating ' + (isNum(r.strength_ppg) ? num(r.strength_ppg, 2) : '—'),
      best: xs.slice().sort(function (a, b) { return b.p - a.p; }).slice(0, 3).map(chip), worst: xs.slice().sort(function (a, b) { return a.p - b.p; }).slice(0, 3).map(chip) });
  }).join('');
  host.innerHTML = QK.sectionHead({ kicker: 'Strengths and weaknesses', title: 'What each ' + word() + ' does best, and worst', sub: 'Each ' + word() + '’s three best and three worst of ' + pool.length + ' process metrics, as percentiles among the ' + T.length + ' (100 = best). Ordered by our rating.' }) +
    '<div class="qk-sw-grid">' + cards + '</div>';
}

/* 5. head to head */
function h2h() {
  var host = document.getElementById('tm-h2h');
  if (!host) return;
  var list = byRating(T);
  if (list.length < 2) { host.innerHTML = ''; return; }
  if (list.indexOf(ST.a) < 0) ST.a = list[0];
  if (list.indexOf(ST.b) < 0 || ST.b === ST.a) ST.b = list.filter(function (t) { return t !== ST.a; })[0];
  var opt = function (cur) { return list.slice().sort(function (a, b) { return tinfo(a).name.localeCompare(tinfo(b).name); }).map(function (t) { return '<option value="' + esc(t) + '"' + (t === cur ? ' selected' : '') + '>' + esc(tinfo(t).name) + '</option>'; }).join(''); };
  var A = tinfo(ST.a), B = tinfo(ST.b);
  var groups = H2H.map(function (g) { return { label: g[0], rows: g[1].filter(function (id) { return META[id]; }).map(function (id) {
    var m = meta(id);
    return { label: m.label, tip: m.tip, a: v(ST.a, id), b: v(ST.b, id), ta: m.fmt(v(ST.a, id)), tb: m.fmt(v(ST.b, id)), pa: m.style ? null : pc(ST.a, id), pb: m.style ? null : pc(ST.b, id), better: m.lower ? 'low' : 'high' };
  }) }; });
  var sub = function (t) { var r = ROWS[t] || {}; return (isNum(r.points) ? r.points + ' pts' : '') + (isNum(r.strength_ppg) ? ' · rating ' + num(r.strength_ppg, 2) : ''); };
  var met = A.id && B.id ? '<a class="qk-btn sm" href="#/clubs/h2h?a=' + esc(A.id) + '&amp;b=' + esc(B.id) + '">If they met: our chances →</a>' : '';
  host.innerHTML = QK.sectionHead({ kicker: 'Head to head', title: QK.surname(A.name) + ' or ' + QK.surname(B.name) + '?', sub: 'Two ' + words() + ' on the metrics that decide matches. Bars are percentiles among the ' + list.length + '; the small line under each metric is the gap in percentile points and who leads it.' }) +
    '<div class="qk-card"><div class="qk-card-body">' + QK.scoutBar([{ label: intl() ? 'Team' : 'Club', html: '<select class="qk-select" id="tm-a">' + opt(ST.a) + '</select>' }, { label: 'Against', html: '<select class="qk-select" id="tm-b">' + opt(ST.b) + '</select>' },
      { label: '', html: '<button type="button" class="qk-btn sm" id="tm-swap">⇄ Swap</button>' }]) + (met ? '<p class="fb-mt">' + met + '</p>' : '') +
    '<div style="margin-top:16px">' + QK.tape({ left: { name: A.name, short: A.abbr, sub: sub(ST.a), colour: A.colour, alt: A.alt, href: A.href }, right: { name: B.name, short: B.abbr, sub: sub(ST.b), colour: B.colour, alt: B.alt, href: B.href },
      groups: groups, wins: true, gap: true }) + '</div></div></div>';
  var $ = function (id) { return document.getElementById(id); };
  $('tm-a').onchange = function (e) { ST.a = e.target.value; setQ({ a: ST.a, b: ST.b }); h2h(); };
  $('tm-b').onchange = function (e) { ST.b = e.target.value; setQ({ a: ST.a, b: ST.b }); h2h(); };
  $('tm-swap').onclick = function () { var t = ST.a; ST.a = ST.b; ST.b = t; setQ({ a: ST.a, b: ST.b }); h2h(); };
}

/* 6. through the season: xG difference, points (analytics rounds) or Elo (strength elo_history), match by match */
function trend() {
  var host = document.getElementById('tm-trend');
  if (!host) return;
  var list = byRating(T);
  var rounds = function (t) { return ((AN[t] || {}).rounds || []).filter(function (r) { return isNum(r.xg) && isNum(r.xga); }); };
  var elo = (D.strength || {}).elo_history || {};
  if (!list.some(function (t) { return rounds(t).length > 1 || (elo[t] || []).length > 1; })) { host.innerHTML = ''; return; }
  var have = { xgd: list.some(function (t) { return rounds(t).length > 1; }), pts: list.some(function (t) { return rounds(t).length > 1; }), elo: list.some(function (t) { return (elo[t] || []).length > 1; }) };
  if (!have[ST.trend]) ST.trend = have.xgd ? 'xgd' : 'elo';
  var clubs = ST.clubs.filter(function (t) { return list.indexOf(t) >= 0; });
  if (!clubs.length) clubs = list.slice(0, 5);
  var chips = list.slice().sort(function (a, b) { return tinfo(a).abbr.localeCompare(tinfo(b).abbr); }).map(function (t) { return '<button type="button" class="qk-chip" data-club="' + esc(t) + '" aria-pressed="' + (clubs.indexOf(t) >= 0) + '" title="' + esc(tinfo(t).name) + '">' + esc(tinfo(t).abbr) + '</button>'; }).join('');
  var segs = [['xgd', 'xG difference'], ['pts', 'Points against expected'], ['elo', 'Elo']].filter(function (s) { return have[s[0]]; });
  var titles = { xgd: 'xG difference, match by match', pts: 'Points against expected points', elo: 'Elo, match by match' };
  var subs = { xgd: 'xG created minus xG allowed, added up over the ' + (intl() ? 'tournament' : 'season') + '. A line that climbs is out-chancing its opponents.',
    pts: 'Points won minus the expected points the chances were worth, added up: above zero is running ahead of the chances (often luck).',
    elo: 'Our Elo rating after each match: it moves with results and the strength of the opponent.' };
  host.innerHTML = QK.sectionHead({ kicker: 'Through the season', title: titles[ST.trend], sub: subs[ST.trend], actions: segs.length > 1 ? FB.seg('tm-tr', segs, ST.trend, 'Measure') : '' }) +
    '<div class="qk-card"><div class="qk-card-body"><div class="tm-clubs"><span class="qk-within-l">' + (intl() ? 'Teams' : 'Clubs') + '</span><div class="qk-chips">' + chips + '</div>' +
    '<div class="qk-chips tm-divs"><button type="button" class="qk-chip" data-set="top">Top five</button><button type="button" class="qk-chip" data-set="bottom">Bottom five</button></div></div>' +
    '<div id="tm-tr-c" class="qk-chart" style="--h:440px;margin-top:14px" role="img" aria-label="Through the season"></div></div></div>';
  var T0 = QKC.tokens(), used = [];
  var colOf = function (t, i) {
    var c = tinfo(t).colour, col = c && QK.color.parse(c) ? QK.color.team(c) : null;
    /* two clubs in near-identical kits are kept apart: the second takes a chart slot (kit rule) */
    if (!col || used.some(function (u) { return u.charAt(0) === '#' && col.charAt(0) === '#' && !QK.color.distinct(u, col); })) col = T0.cat[(i + 1) % 8];
    used.push(col);
    return col;
  };
  var series = clubs.map(function (t, i) {
    var s = 0, data;
    if (ST.trend === 'elo') data = (elo[t] || []).map(function (e, j) { return [j + 1, e.elo]; });
    else data = rounds(t).map(function (r, j) { s += ST.trend === 'xgd' ? r.xg - r.xga : (r.pts - r.xpts); return [j + 1, Math.round(s * 100) / 100]; });
    return { name: tinfo(t).abbr, color: colOf(t, i), data: data };
  });
  var n = Math.max.apply(null, series.map(function (x) { return x.data.length; }).concat([1]));
  QKC.line(document.getElementById('tm-tr-c'), { xType: 'value', x: Array.from({ length: n }, function (_, j) { return j + 1; }), series: series,
    yName: ST.trend === 'elo' ? 'Elo rating' : ST.trend === 'xgd' ? 'xG difference, added up (goals)' : 'Points minus expected points', xName: 'Matches played', xMin: 1, xMax: n,
    ref: ST.trend === 'elo' ? undefined : { y: 0, label: ST.trend === 'xgd' ? 'Even' : 'On par' }, endLabels: true, label: titles[ST.trend] });
  QK.$$('[data-club]', host).forEach(function (b) { b.addEventListener('click', function () {
    var t = b.getAttribute('data-club'), cur = clubs.slice(), i = cur.indexOf(t);
    if (i >= 0) { if (cur.length > 1) cur.splice(i, 1); } else if (cur.length < 8) cur.push(t);
    ST.clubs = cur; setQ({ clubs: cur.join(',') }); trend();
  }); });
  QK.$$('[data-set]', host).forEach(function (b) { b.addEventListener('click', function () {
    ST.clubs = b.getAttribute('data-set') === 'top' ? list.slice(0, 5) : list.slice(-5);
    setQ({ clubs: ST.clubs.join(',') }); trend();
  }); });
  FB.wireSeg(host, 'tm-tr', function (x) { ST.trend = x; setQ({ trend: x === 'xgd' ? null : x }); trend(); });
}

})(window.FB);
