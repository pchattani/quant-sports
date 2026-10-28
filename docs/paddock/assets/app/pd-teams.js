/* The Quant Paddock — the Teams page (#/constructors[/<y>]), round 9 (28 Oct 2026; the Bullpen pilot bp-teams.js is
 * the reference): every constructor ranked, profiled and set against the rest. It replaces the old Constructors list
 * (the team cards and the metrics table); the team pages (#/team/<id>[/<y>], constructors.js) stay. Kit: scout.js
 * (QK.powerBars, QK.heatGrid, QK.strengths), quant.js (QK.tape with gap: true), quant-charts.js (QKC.scatter, QKC.line).
 *
 * Sections (a chip strip jumps between them; ?sec=<id> scrolls to one on arrival):
 *   1. Power board: each constructor ranked by our expected points per race above an average team, the bar split into
 *      the car and the drivers (season.json car_driver_split: the car's and each driver's share of our expected points,
 *      from the car/driver decomposition), the volt tick the total; car pace, points and wins beside it; the title
 *      chance quiet (">99.9%" until clinched). Before the decomposition (no split): points per race, unsplit.
 *   2. Team profile: the heat grid of the constructors by every teams.json metric, phase groups as chips (Overview,
 *      Car pace, Results, Tyres and pit crew, Reliability, Drivers), percentile cells, sortable, CSV (?grid=, gadd=, gsort=).
 *   3. Style map: any two team metrics, presets with the corners named (qualifying against race pace, straight line
 *      against cornering, tyres against pace, pit crew against strategy, car pace against points) (?map=, mx=, my=).
 *   4. Strengths and weaknesses: each constructor's three best and three worst process metrics, as percentile chips.
 *   5. Head to head: two constructors on the tale of the tape with the gap in percentile points (?a=, b=); it replaces
 *      Compare teams (#/compare/teams/<a>/<b> redirects here).
 *   6. Through the season: the car's race or qualifying pace by round (season.json car_pace) and points added up
 *      round by round (teams.json log), for the constructors picked (?trend=, clubs=).
 * Percentiles are the payload's (teams.json "pct", direction-aware, 100 = best); a metric without one is ranked among
 * the constructors on screen. Older-browser rule: no optional chaining, no nullish coalescing. */
(function (PD) {
'use strict';

var esc = PD.esc, isNum = PD.isNum;
var ST = { y: null, grid: '', gadd: [], gsort: null, map: 0, mx: '', my: '', a: '', b: '', trend: 'pace', kind: 'race', clubs: [], sec: '' };
var T = null, META = {}, MS = [], SEA = null, STAND = {}, SPLIT = {}, ROUNDS = 1;

var GRID_SETS = [
  ['overview', 'Overview', [['Car', ['car_race_pace', 'car_quali_pace', 'car_pace_trend']], ['Results', ['points_per_race', 'wins', 'podiums', 'both_points_rate', 'points_v_expected']], ['Operations', ['pit_lane_v_field', 'pit_under_2500', 'strategy_gain', 'dnf_rate']]]],
  ['car', 'Car pace', [['Pace', ['car_race_pace', 'car_race_rank', 'car_quali_pace', 'car_quali_rank', 'car_pace_latest', 'car_pace_trend']], ['Profile', ['top_speed', 'speed_trap_rank', 'corner_speed', 'straightline_bias']]]],
  ['results', 'Results', [['Results', ['points', 'points_per_race', 'wins', 'podiums', 'poles', 'one_twos', 'both_points_rate', 'avg_best_finish', 'avg_best_grid']], ['Against our forecast', ['exp_points', 'points_v_expected']]]],
  ['pit', 'Tyres and pit crew', [['Tyres', ['tyre_mgmt', 'deg_soft', 'deg_medium', 'deg_hard']], ['Pit crew', ['pit_stop_ms', 'pit_best_ms', 'pit_under_2500', 'pit_slow', 'pit_lane_ms', 'pit_lane_v_field', 'stops']], ['Strategy', ['strategy_gain', 'stops_per_race']]]],
  ['reliability', 'Reliability', [['Reliability', ['finish_rate', 'dnf_rate', 'dnfs', 'dnf_mech']]]],
  ['drivers', 'Drivers', [['Car or driver', ['car_share', 'lead_driver_share', 'quali_h2h_split']]]]
];
/* what a strength or weakness is read from: the process, not counts */
var SW_POOL = ['car_race_pace', 'car_quali_pace', 'car_pace_trend', 'top_speed', 'corner_speed', 'tyre_mgmt', 'deg_medium', 'pit_stop_ms', 'pit_lane_v_field', 'pit_under_2500',
  'strategy_gain', 'dnf_rate', 'both_points_rate', 'points_v_expected'];
var H2H = [['Car', ['car_race_pace', 'car_quali_pace', 'car_pace_trend', 'top_speed', 'corner_speed', 'tyre_mgmt']], ['Results', ['points_per_race', 'wins', 'podiums', 'both_points_rate', 'points_v_expected']],
  ['Operations', ['pit_stop_ms', 'pit_lane_v_field', 'pit_under_2500', 'strategy_gain', 'dnf_rate']]];
/* [label, x, y, corners { tl, tr, bl, br }]: better is always up and to the right (axes where less is better flip) */
var PRESETS = [
  ['Qualifying against race pace', 'car_quali_pace', 'car_race_pace', { tl: 'Sunday cars', tr: 'Fast everywhere', bl: 'Struggling', br: 'Saturday cars' }],
  ['Straight line against cornering', 'top_speed', 'corner_speed', { tl: 'Downforce cars', tr: 'Quick everywhere', bl: 'Slow everywhere', br: 'Low-drag cars' }],
  ['Tyres against pace', 'tyre_mgmt', 'car_race_pace', { tl: 'Fast, hard on tyres', tr: 'The complete car', bl: 'Struggling', br: 'Kind to tyres, short of pace' }],
  ['Pit crew against strategy', 'pit_lane_v_field', 'strategy_gain', { tl: 'Calls beat the crew', tr: 'Sharp on both', bl: 'Losing time in the pits', br: 'Crew beats the calls' }],
  ['Car pace against points', 'car_race_pace', 'points_per_race', { tl: 'Scoring above the car', tr: 'The real deal', bl: 'Struggling', br: 'Due more points' }]
];

function meta(id) {
  var m = META[id] || { label: id };
  var c = PD.v2.spec, sm = c ? c.metric(id, 'constructor') : null;
  var label = (PD.v2.NAMES[id] || [])[0] || (sm && sm.label && sm.label !== id ? sm.label : '') || m.label || id;
  var tip = (PD.v2.NAMES[id] || [])[1] || (sm && sm.explain) || m.desc || '';
  var o = PD.v2.ours(id);
  return { id: id, label: label, short: label, tip: tip + (o ? (tip ? ' ' : '') + 'Our model: ' + o.name + '.' : ''), lower: !!m.lower, style: id === 'straightline_bias' || id === 'quali_h2h_split', ours: o ? { name: o.name, about: o.about } : null,
    fmt: function (v) { return m.fmt === 'prob' ? PD.pct(v, 0) : m.fmt === 'ms' ? PD.num(v / 1000, 2) + ' s' : PD.fmtVal(v, m.fmt); } };
}
function v(t, id) { var x = ((T[t] || {}).values || {})[id]; return isNum(x) ? x : null; }
function pc(t, id) {
  var p = ((T[t] || {}).pct || {})[id];
  if (isNum(p)) return p;
  var xs = ids().map(function (k) { return v(k, id); }).filter(isNum).sort(function (a, b) { return a - b; }), y = v(t, id);
  if (!isNum(y) || xs.length < 4) return null;
  var q = QK.pctRank(xs, y);
  return meta(id).lower ? 100 - q : q;
}
function ids() { return Object.keys(T || {}); }
function tinfo(t) { return { name: PD.teamName(t), abbr: PD.teamAbbr(t), colour: PD.teamColourRaw(t) || '', alt: PD.teamAlt(t) || '' }; }
function thref(t) { return PD.teamHref(t, ST.y); }
function rating(t) {
  var s = SPLIT[t];
  if (s && isNum(s.model_points) && isNum(s.baseline)) return (s.model_points - s.baseline) / ROUNDS;
  return null;
}
function power(t) { var r = rating(t); return isNum(r) ? r : v(t, 'points_per_race'); }
function byPower(list) { return list.slice().sort(function (a, b) { var x = power(a), y = power(b); return (isNum(y) ? y : -99) - (isNum(x) ? x : -99); }); }
function lineup(t) {
  var d = (((SEA || {}).teams || {})[t] || {}).drivers || (T[t] || {}).drivers || [];
  return d.map(PD.driverSurname).join(', ');
}

/* ── the address ─────────────────────────────────────────────────────────── */
function readQ(q) {
  q = q || {};
  ST.grid = q.grid || ''; ST.gadd = q.gadd ? String(q.gadd).split(',').filter(Boolean) : [];
  ST.gsort = q.gsort ? { key: q.gsort, dir: q.gdir === 'asc' ? 'asc' : 'desc' } : null;
  var mp = parseInt(q.map, 10); ST.map = isNaN(mp) ? 0 : mp; ST.mx = q.mx || ''; ST.my = q.my || '';
  ST.a = q.a || ''; ST.b = q.b || ''; ST.trend = q.trend === 'pts' ? 'pts' : 'pace'; ST.kind = q.kind === 'quali' ? 'quali' : 'race';
  ST.clubs = q.clubs ? String(q.clubs).split(',').filter(Boolean) : []; ST.sec = q.sec || '';
}
function writeQ() {
  var q = {};
  if (ST.grid) q.grid = ST.grid;
  if (ST.gadd.length) q.gadd = ST.gadd.join(',');
  if (ST.gsort && ST.gsort.key && !(ST.gsort.key === 'points_per_race' && ST.gsort.dir === 'desc')) { q.gsort = ST.gsort.key; q.gdir = ST.gsort.dir; }
  if (ST.map) q.map = ST.map;
  if (ST.map < 0) { q.mx = ST.mx; q.my = ST.my; }
  if (ST.a) q.a = ST.a;
  if (ST.b) q.b = ST.b;
  if (ST.trend !== 'pace') q.trend = ST.trend;
  if (ST.kind !== 'race') q.kind = ST.kind;
  if (ST.clubs.length) q.clubs = ST.clubs.join(',');
  PD.setHashQuiet('#/constructors' + (ST.y !== PD.currentSeason() ? '/' + ST.y : '') + PD.qs(q));
}

/* ── render ──────────────────────────────────────────────────────────────── */
var SECS = [['tm-power', 'Power board'], ['tm-grid', 'Team profile'], ['tm-map', 'Style map'], ['tm-sw', 'Strengths and weaknesses'], ['h2h', 'Head to head'], ['tm-trend', 'Through the season']];
function jump(id) {
  var t = document.getElementById(id);
  if (!t) return;
  var off = ['.qk-topbar', '.qk-secnav'].reduce(function (s, q) { return s + ((document.querySelector(q) || {}).offsetHeight || 0); }, 0) + 12;
  window.scrollTo({ top: t.getBoundingClientRect().top + window.pageYOffset - off, behavior: QK.reducedMotion && QK.reducedMotion() ? 'auto' : 'smooth' });
}
function render(el, params) {
  ST.y = isNum(params.year) ? params.year : PD.currentSeason();
  readQ(params.query || {});
  el.innerHTML = PD.pageHead('Constructors · ' + ST.y, 'Every team, ranked and compared', 'Who has the fastest car, who gets the most from it, and how each team wins. Tap a team for its page.', PD.yearPager('constructors', ST.y)) +
    '<nav class="tm-jump" aria-label="On this page"><div class="qk-chips scroll">' + SECS.map(function (s) { return '<a class="qk-chip" href="#' + s[0] + '" data-jump="' + s[0] + '">' + esc(s[1]) + '</a>'; }).join('') + '</div></nav>' +
    SECS.map(function (s) { return '<section class="qk-section tm-sec" id="' + s[0] + '">' + QK.skeleton('lines', 3) + '</section>'; }).join('');
  QK.$$('[data-jump]', el).forEach(function (a) { a.addEventListener('click', function (ev) { ev.preventDefault(); jump(a.getAttribute('data-jump')); }); });
  return Promise.all([PD.load(ST.y + '/teams.json'), PD.load(ST.y + '/season.json'), PD.v2.specP]).then(function (res) {
    if (!PD.alive(el)) return;
    var cat = res[0];
    SEA = PD.ok(res[1]) ? res[1] : null;
    if (!PD.ok(cat) || !cat.teams || !Object.keys(cat.teams).length) { SECS.forEach(function (s) { PD.set(s[0], ''); }); PD.set('tm-power', PD.notBuilt('The ' + ST.y + ' team catalogue', cat)); return; }
    T = cat.teams; MS = cat.metrics || [];
    META = {}; MS.forEach(function (m) { META[m.key] = m; });
    STAND = {}; (((SEA || {}).standings || {}).constructors || []).forEach(function (s) { STAND[s.team] = s; });
    SPLIT = (SEA || {}).car_driver_split || {};
    ROUNDS = Math.max(1, (SEA && SEA.rounds_done) || Math.max.apply(null, ids().map(function (t) { return ((T[t] || {}).log || []).length; }).concat([1])));
    powerBoard(); grid(); styleMap(); strengths(); h2h(); trend();
    if (ST.sec) setTimeout(function () { jump(ST.sec); }, 60);
  });
}

/* 1. the power board */
function powerBoard() {
  var host = document.getElementById('tm-power');
  if (!host) return;
  var all = byPower(ids()), split = all.some(function (t) { return isNum(rating(t)); });
  var ch = ((SEA || {}).championship || {}).constructors || null;
  var rows = all.map(function (t, i) {
    var i0 = tinfo(t), s = STAND[t] || {}, sp = SPLIT[t] || {}, c = ch ? ch[t] : null;
    var dsum = 0, nd = 0;
    Object.keys(sp.drivers || {}).forEach(function (d) { if (isNum(sp.drivers[d])) { dsum += sp.drivers[d]; nd++; } });
    var cells = [{ label: 'Points', text: isNum(s.points) ? PD.pts(s.points) + (s.pos ? ' · P' + s.pos : '') : '—' },
      { label: 'Car pace', text: isNum(v(t, 'car_race_pace')) ? PD.signed(-v(t, 'car_race_pace'), 2) + '%' : '—' },
      { label: 'Wins', text: String(s.wins || v(t, 'wins') || 0) }];
    return { rank: i + 1, name: i0.name, abbr: i0.abbr, colour: i0.colour, href: thref(t), sub: lineup(t), value: power(t),
      text: isNum(power(t)) ? (split ? PD.signed(power(t), 2) : PD.num(power(t), 2)) : '—',
      parts: split && isNum(sp.car) ? { car: sp.car / ROUNDS, drv: nd ? dsum / ROUNDS : 0 } : {},
      cells: cells, chances: c && !(SEA || {}).finished ? [{ label: 'Title', p: c.p_title, text: PD.titlePct(c) }] : [] };
  });
  var finished = !!(SEA && (SEA.finished || !SEA.championship));
  host.innerHTML = QK.sectionHead({ kicker: 'Power board', title: split ? 'Every team, ranked by our numbers' : 'Every team, ranked by points',
    sub: split ? 'Our rating is the points a race the team scores above an average team, by our race model. The bar splits it into the car (its pace with the drivers taken out) and the drivers (what the two of them add or lose in that car); the volt tick is the total.' + (finished ? '' : ' The title chance comes from the simulated seasons.')
      : 'Before 1996 there are no lap times to split car from driver, so the board ranks points per race.' }) +
    '<div class="qk-card"><div class="qk-card-body">' + QK.powerBars(rows, { valueLabel: split ? 'Our rating' : 'Points per race', unit: split ? 'points a race above an average team' : '',
      parts: split ? [{ key: 'car', label: 'Car', color: 'var(--c-3)' }, { key: 'drv', label: 'Drivers', color: 'var(--c-2)' }] : [], key: split ? undefined : false }) + '</div></div>' +
    QK.explain('A <b>rating of +10</b> means about ten points a race more than an average team would take from the same races. ' +
      '<b>Car pace</b> is the car’s share of lap time against the field (positive = faster), from our pace model. Team-mates share a car, so the drivers’ part is small next to it: in F1 the car decides most of the order. The full tables are on <a href="#/standings' + (ST.y !== PD.currentSeason() ? '/' + ST.y : '') + '">Standings</a>.', { title: 'What’s that number?' });
}

/* 2. the team profile grid */
function grid() {
  var host = document.getElementById('tm-grid');
  if (!host) return;
  var have = function (id) { return !!META[id] && ids().some(function (t) { return isNum(v(t, id)); }); };
  var sets = GRID_SETS.map(function (s) { return { key: s[0], label: s[1], groups: s[2].map(function (g) { return { label: g[0], ids: g[1].filter(have) }; }).filter(function (g) { return g.ids.length; }) }; }).filter(function (s) { return s.groups.length; });
  var used = {}; sets.forEach(function (s) { s.groups.forEach(function (g) { g.ids.forEach(function (id) { used[id] = 1; }); }); });
  var rest = MS.filter(function (m) { return !used[m.key] && have(m.key); }).map(function (m) { return m.key; });
  if (rest.length) sets.push({ key: 'more', label: 'More', groups: [{ label: 'More', ids: rest }] });
  var rows = byPower(ids()).map(function (t) { var i = tinfo(t), s = STAND[t] || {}; return { id: t, name: i.name, sub: (s.pos ? 'P' + s.pos + ' · ' : '') + PD.pts(s.points) + ' pts', mark: { abbr: i.abbr, colour: i.colour }, href: thref(t) }; });
  var groupsOpt = (function () {
    var gs = [];
    MS.forEach(function (m) { if (!have(m.key)) return; var g = gs.filter(function (x) { return x.name === (m.group || 'Other'); })[0]; if (!g) { g = { name: m.group || 'Other', items: [] }; gs.push(g); } g.items.push(m); });
    return gs.map(function (g) { return '<optgroup label="' + esc(g.name) + '">' + g.items.map(function (m) { return '<option value="' + esc(m.key) + '">' + esc(meta(m.key).label) + '</option>'; }).join('') + '</optgroup>'; }).join('');
  })();
  host.innerHTML = QK.sectionHead({ kicker: 'Team profile', title: ids().length + ' teams, every metric', sub: 'Each cell is the team’s value, coloured by its percentile among the ' + ids().length + ' (blue worst, red best; a ↓ marks a metric where lower is better). Pick a phase, add any metric, sort by any column, tap a team for its page.' }) +
    '<div class="qk-card"><div class="qk-card-body"><div id="tm-hg"></div></div></div>';
  QK.heatGrid(document.getElementById('tm-hg'), {
    id: 'tm-hgr', sets: sets, set: sets.some(function (s) { return s.key === ST.grid; }) ? ST.grid : 'overview', setsLabel: 'Phase', added: ST.gadd.filter(have), sort: ST.gsort || { key: 'points_per_race', dir: 'desc' },
    nameLabel: 'Constructor', subLabel: 'Position · points', noun: 'teams', meta: meta, addable: groupsOpt,
    rows: rows, val: function (r, id) { return v(r.id, id); },
    csv: 'paddock-' + ST.y + '-constructors.csv',
    onState: function (st) { ST.grid = st.set === 'overview' ? '' : st.set; ST.gadd = st.added; ST.gsort = st.sort; writeQ(); }
  });
}

/* 3. the style map */
function styleMap() {
  var host = document.getElementById('tm-map');
  if (!host) return;
  var opts = MS.filter(function (m) { return ids().some(function (t) { return isNum(v(t, m.key)); }); }).map(function (m) { return { value: m.key, label: meta(m.key).label }; });
  var P = PRESETS.filter(function (p) { return ids().filter(function (t) { return isNum(v(t, p[1])) && isNum(v(t, p[2])); }).length >= 4; });
  if (!opts.length || !P.length) { host.innerHTML = QK.sectionHead({ kicker: 'Style map', title: 'How each team goes fast' }) + PD.muted('Too few team metrics this season for a style map (lap and telemetry data start in 1996 and 2023).'); return; }
  if (ST.map >= P.length) ST.map = 0;
  var cur = ST.map >= 0 ? P[ST.map] : null;
  var x = cur ? cur[1] : (ST.mx || P[0][1]), y = cur ? cur[2] : (ST.my || P[0][2]);
  var sel = function (id, val) { return '<select class="qk-select" id="' + id + '">' + opts.map(function (o) { return '<option value="' + esc(o.value) + '"' + (o.value === val ? ' selected' : '') + '>' + esc(o.label) + '</option>'; }).join('') + '</select>'; };
  host.innerHTML = QK.sectionHead({ kicker: 'Style map', title: 'How each team goes fast', sub: 'Any two team metrics against each other. The dashed lines are the medians; better is always up and to the right (axes where less is better are flipped). Tap a team for its page.' }) +
    '<div class="qk-card"><div class="qk-card-body">' + QK.scoutBar([
      { label: 'Preset', html: '<select class="qk-select" id="tm-preset">' + P.map(function (p, i) { return '<option value="' + i + '"' + (i === ST.map ? ' selected' : '') + '>' + esc(p[0]) + '</option>'; }).join('') + '<option value="-1"' + (ST.map < 0 ? ' selected' : '') + '>Any two metrics</option></select>' },
      { label: 'Across', html: sel('tm-mx', x) }, { label: 'Up', html: sel('tm-my', y) }]) +
    '<div id="tm-map-c" class="qk-chart" style="--h:500px;margin-top:16px" role="img" aria-label="Style map"></div><p class="pd-cap" id="tm-map-n"></p></div></div>';
  var $ = function (id) { return document.getElementById(id); };
  $('tm-preset').onchange = function (e) { ST.map = parseInt(e.target.value, 10); if (ST.map < 0) { ST.mx = x; ST.my = y; } writeQ(); styleMap(); };
  $('tm-mx').onchange = function (e) { ST.map = -1; ST.mx = e.target.value; ST.my = $('tm-my').value; writeQ(); styleMap(); };
  $('tm-my').onchange = function (e) { ST.map = -1; ST.my = e.target.value; ST.mx = $('tm-mx').value; writeQ(); styleMap(); };
  var mx = meta(x), my = meta(y);
  var pts = ids().filter(function (t) { return isNum(v(t, x)) && isNum(v(t, y)); }).map(function (t) { var i = tinfo(t); return { x: v(t, x), y: v(t, y), name: i.name, label: i.abbr, color: i.colour || null, size: 15, href: thref(t) }; });
  var corners = cur ? cur[3] : { tl: '', tr: 'Better on both', bl: 'Worse on both', br: '' };
  QKC.scatter($('tm-map-c'), { points: pts, labelAll: true, refX: PD.median(pts.map(function (p) { return p.x; })), refY: PD.median(pts.map(function (p) { return p.y; })), xInverse: mx.lower, yInverse: my.lower, pad: '9%',
    xName: mx.label + (mx.lower ? ' (lower is better: flipped)' : ''), yName: my.label + (my.lower ? ' (lower is better: flipped)' : ''), xFmt: mx.fmt, yFmt: my.fmt,
    quadrants: [corners.tl, corners.tr, corners.bl, corners.br], label: my.label + ' against ' + mx.label });
  $('tm-map-n').innerHTML = '<b>' + esc(mx.label) + '</b>: ' + esc(mx.tip) + ' <b>' + esc(my.label) + '</b>: ' + esc(my.tip);
}

/* 4. strengths and weaknesses */
function strengths() {
  var host = document.getElementById('tm-sw');
  if (!host) return;
  var pool = SW_POOL.filter(function (id) { return META[id] && ids().some(function (t) { return isNum(v(t, id)); }); });
  if (!pool.length) { host.innerHTML = ''; return; }
  var cards = byPower(ids()).map(function (t) {
    var i = tinfo(t);
    var xs = pool.map(function (id) { return { id: id, p: pc(t, id) }; }).filter(function (o) { return isNum(o.p) && isNum(v(t, o.id)); });
    var chip = function (o) { var m = meta(o.id); return { label: m.label, pctl: o.p, text: m.fmt(v(t, o.id)), tip: m.tip }; };
    var best = xs.slice().sort(function (a, b) { return b.p - a.p; }).slice(0, 3).map(chip), worst = xs.slice().sort(function (a, b) { return a.p - b.p; }).slice(0, 3).map(chip);
    var s = STAND[t] || {};
    return QK.strengths({ name: i.name, abbr: i.abbr, colour: i.colour, href: thref(t), sub: (s.pos ? 'P' + s.pos + ' · ' : '') + PD.pts(s.points) + ' points', best: best, worst: worst });
  }).join('');
  host.innerHTML = QK.sectionHead({ kicker: 'Strengths and weaknesses', title: 'What each team does best, and worst', sub: 'Each team’s three best and three worst of ' + pool.length + ' car, tyre, pit-crew, strategy and reliability metrics, as percentiles among the ' + ids().length + ' teams (100 = best). Ordered by the power board.' }) +
    '<div class="qk-sw-grid">' + cards + '</div>';
}

/* 5. head to head */
function h2h() {
  var host = document.getElementById('h2h');
  if (!host) return;
  var list = byPower(ids());
  if (!T[ST.a]) ST.a = list[0];
  if (!T[ST.b] || ST.b === ST.a) ST.b = list.filter(function (t) { return t !== ST.a; })[0];
  var opt = function (cur) { return list.slice().sort(function (a, b) { return tinfo(a).name.localeCompare(tinfo(b).name); }).map(function (t) { return '<option value="' + esc(t) + '"' + (t === cur ? ' selected' : '') + '>' + esc(tinfo(t).name) + '</option>'; }).join(''); };
  var A = tinfo(ST.a), B = tinfo(ST.b);
  var groups = H2H.map(function (g) { return { label: g[0], rows: g[1].filter(function (id) { return META[id] && (isNum(v(ST.a, id)) || isNum(v(ST.b, id))); }).map(function (id) {
    var m = meta(id);
    return { label: m.label, tip: m.tip, a: v(ST.a, id), b: v(ST.b, id), ta: isNum(v(ST.a, id)) ? m.fmt(v(ST.a, id)) : '—', tb: isNum(v(ST.b, id)) ? m.fmt(v(ST.b, id)) : '—', pa: pc(ST.a, id), pb: pc(ST.b, id), better: m.lower ? 'low' : 'high' };
  }) }; }).filter(function (g) { return g.rows.length; });
  var sub = function (t) { var s = STAND[t] || {}; return (s.pos ? 'P' + s.pos + ' · ' : '') + PD.pts(s.points) + ' pts'; };
  host.innerHTML = QK.sectionHead({ kicker: 'Head to head', title: QK.surname(A.name.replace(/ F1 Team| Racing| Formula One Team/g, '')) + ' or ' + QK.surname(B.name.replace(/ F1 Team| Racing| Formula One Team/g, '')) + '?', sub: 'Two teams on the metrics that decide races. Bars are percentiles among the ' + list.length + ' teams; the small line under each metric is the gap in percentile points and who leads it.' }) +
    '<div class="qk-card"><div class="qk-card-body">' + QK.scoutBar([{ label: 'Team', html: '<select class="qk-select" id="tm-a">' + opt(ST.a) + '</select>' }, { label: 'Against', html: '<select class="qk-select" id="tm-b">' + opt(ST.b) + '</select>' },
      { label: '', html: '<button type="button" class="qk-btn sm" id="tm-swap">⇄ Swap</button>' }]) +
    '<div style="margin-top:16px">' + QK.tape({ left: { name: A.name, short: A.abbr, sub: sub(ST.a), colour: A.colour, alt: A.alt, href: thref(ST.a) },
      right: { name: B.name, short: B.abbr, sub: sub(ST.b), colour: B.colour, alt: B.alt, href: thref(ST.b) }, groups: groups, wins: true, gap: true }) + '</div>' +
    '<p class="pd-cap">Each team’s own page has its drivers, pit crew and run-in: <a href="' + esc(thref(ST.a)) + '">' + esc(A.name) + '</a> · <a href="' + esc(thref(ST.b)) + '">' + esc(B.name) + '</a>.</p></div></div>';
  var $ = function (id) { return document.getElementById(id); };
  $('tm-a').onchange = function (e) { ST.a = e.target.value; writeQ(); h2h(); };
  $('tm-b').onchange = function (e) { ST.b = e.target.value; writeQ(); h2h(); };
  $('tm-swap').onclick = function () { var t = ST.a; ST.a = ST.b; ST.b = t; writeQ(); h2h(); };
}

/* 6. through the season: car pace by round (season.json car_pace), points added up round by round (teams.json log) */
function trend() {
  var host = document.getElementById('tm-trend');
  if (!host) return;
  var list = byPower(ids());
  var cp = ((SEA || {}).car_pace || {});
  var paceOf = function (t, kind) { return ((cp[kind] || {})[t] || []).slice().sort(function (a, b) { return a.round - b.round; }); };
  var hasPace = list.some(function (t) { return paceOf(t, 'race').length > 1; });
  if (!hasPace && ST.trend === 'pace') ST.trend = 'pts';
  var logOf = function (t) { return ((T[t] || {}).log || []).slice().sort(function (a, b) { return a.round - b.round; }); };
  if (!list.some(function (t) { return logOf(t).length; })) { host.innerHTML = ''; return; }
  var clubs = ST.clubs.filter(function (t) { return T[t]; });
  if (!clubs.length) clubs = list.slice(0, 5);
  var chips = list.map(function (t) { return '<button type="button" class="qk-chip" data-club="' + esc(t) + '" aria-pressed="' + (clubs.indexOf(t) >= 0) + '">' + esc(tinfo(t).abbr) + '</button>'; }).join('');
  var segs = [['pace', 'Car pace'], ['pts', 'Points']].filter(function (s) { return s[0] !== 'pace' || hasPace; });
  host.innerHTML = QK.sectionHead({ kicker: 'Through the season', title: ST.trend === 'pace' ? 'Who got faster, round by round' : 'Points, round by round',
    sub: ST.trend === 'pace' ? 'The car’s ' + (ST.kind === 'quali' ? 'qualifying' : 'race') + ' pace with the drivers taken out, % of a lap faster than the field, from our pace model as it stood after each round.' : 'Constructors’ points added up over the season, from each team’s round log.',
    actions: (segs.length > 1 ? PD.seg('tm-tr', segs, ST.trend, 'Measure') : '') + (ST.trend === 'pace' ? PD.seg('tm-kind', [['race', 'Race'], ['quali', 'Qualifying']], ST.kind, 'Session') : '') }) +
    '<div class="qk-card"><div class="qk-card-body"><div class="tm-clubs"><span class="qk-within-l">Teams</span><div class="qk-chips">' + chips + '</div>' +
    '<div class="qk-chips tm-divs"><button type="button" class="qk-chip" data-set="top">Top five</button><button type="button" class="qk-chip" data-set="all">All ' + list.length + '</button></div></div>' +
    '<div id="tm-tr-c" class="qk-chart" style="--h:440px;margin-top:14px" role="img" aria-label="Through the season"></div></div></div>';
  var T0 = QKC.tokens();
  /* team colours kept apart: a colour too close to one already drawn falls back to the next chart slot */
  var used = [];
  var colOf = function (t, i) {
    var c = tinfo(t).colour, col = c && QK.color.parse(c) ? QK.color.team(c) : T0.cat[i % 8];
    if (used.some(function (u) { return QK.color.distinct && !QK.color.distinct(u, col); })) col = T0.cat[i % 8];
    used.push(col);
    return col;
  };
  var rounds = [];
  if (ST.trend === 'pace') {
    var series = clubs.map(function (t, i) { return { name: tinfo(t).abbr, color: colOf(t, i), data: paceOf(t, ST.kind).map(function (e) { if (rounds.indexOf(e.round) < 0) rounds.push(e.round); return [e.round, -e.effect]; }) }; });
    QKC.line(document.getElementById('tm-tr-c'), { xType: 'value', series: series, yName: 'Car pace (% of a lap, + is faster)', xName: 'Round', xMin: 1, xMax: Math.max.apply(null, rounds.concat([2])), ref: { y: 0, label: 'Field average' }, endLabels: true,
      yFmt: function (x) { return PD.signed(x, 1); }, label: 'Car pace by round' });
  } else {
    var series2 = clubs.map(function (t, i) { var s = 0; return { name: tinfo(t).abbr, color: colOf(t, i), data: logOf(t).map(function (g) { s += g.points || 0; if (rounds.indexOf(g.round) < 0) rounds.push(g.round); return [g.round, s]; }) }; });
    QKC.line(document.getElementById('tm-tr-c'), { xType: 'value', series: series2, yName: 'Points', xName: 'Round', xMin: 1, xMax: Math.max.apply(null, rounds.concat([2])), yMin: 0, endLabels: true, label: 'Points through the season' });
  }
  QK.$$('[data-club]', host).forEach(function (b) { b.addEventListener('click', function () {
    var t = b.getAttribute('data-club'), cur = clubs.slice(), i = cur.indexOf(t);
    if (i >= 0) { if (cur.length > 1) cur.splice(i, 1); } else if (cur.length < 11) cur.push(t);
    ST.clubs = cur; writeQ(); trend();
  }); });
  QK.$$('[data-set]', host).forEach(function (b) { b.addEventListener('click', function () { ST.clubs = b.getAttribute('data-set') === 'all' ? list.slice() : list.slice(0, 5); writeQ(); trend(); }); });
  PD.wireSeg(host, 'tm-tr', function (x) { ST.trend = x; writeQ(); trend(); });
  PD.wireSeg(host, 'tm-kind', function (x) { ST.kind = x; writeQ(); trend(); });
}

PD.route('constructors', render);
})(window.PD);
