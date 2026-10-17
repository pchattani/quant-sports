/* Living style guide for docs/_design. Demo data only; every component is the real kit. */
(function () {
'use strict';
var $ = QK.$, esc = QK.esc;

var shell = QK.shell({ sport: null, search: { load: function () { return Promise.resolve(DEMO_SEARCH); } } });
var DEMO_SEARCH = [
  { sport: 'football', t: 'Arsenal', s: 'Club · England', href: '#tables' },
  { sport: 'football', t: 'Erling Haaland', s: 'Manchester City · F', href: '#tables' },
  { sport: 'nfl', t: 'Buffalo Bills', s: 'NFL team · AFC East', href: '#tables' },
  { sport: 'basketball', t: 'Boston Celtics', s: 'NBA team', href: '#tables' },
  { sport: 'hockey', t: 'Colorado Avalanche', s: 'NHL team', href: '#tables' },
  { sport: 'f1', t: 'Lando Norris', s: 'Driver · McLaren', href: '#tables' },
  { sport: 'tennis', t: 'C. Alcaraz', s: 'ATP player', href: '#tables' },
  { sport: 'baseball', t: 'Milwaukee Brewers', s: 'MLB team · NL Central', href: '#tables' }
];
shell.setLive({ hockey: true, football: true });
var demo = QK.shell({ mount: '#shell-demo', sport: 'nfl', section: 'standings', sections: QK.sections('nfl'), demo: true, search: {},
  ctx: '<div class="qk-seg"><button aria-pressed="true">2026</button><button aria-pressed="false">2025</button></div>' });
demo.setLive({ nfl: true });

/* ── swatches */
function sw(list) {
  return list.map(function (x) {
    var v = QK.cssVar(x[0]);
    return '<div class="sg-sw"><i style="--k:var(' + x[0] + ')"></i><div><b>' + esc(x[1]) + '</b><code>' + esc(x[0]) + '</code><code class="v" data-var="' + x[0] + '">' + esc(v) + '</code></div></div>';
  }).join('');
}
function paintSwatches() {
  $('#sw-surface').innerHTML = sw([['--bg', 'Page'], ['--bg-raise', 'Raised'], ['--s-1', 'Card'], ['--s-2', 'Card head'], ['--s-3', 'Pressed'], ['--s-4', 'Strong'], ['--ink-1', 'Ink 1'], ['--ink-2', 'Ink 2'], ['--ink-3', 'Ink 3 (muted)'], ['--ink-4', 'Ink 4 (decor)']]);
  $('#sw-accent').innerHTML = sw([['--brand', 'Brand amber'], ['--a-football', 'Football'], ['--a-nfl', 'NFL'], ['--a-basketball', 'Basketball'], ['--a-baseball', 'Baseball'], ['--a-hockey', 'Hockey'], ['--a-f1', 'F1'], ['--a-tennis', 'Tennis'], ['--focus', 'Focus ring'], ['--live', 'Live']]);
  $('#sw-cat').innerHTML = sw([['--c-1', '1 Model'], ['--c-2', '2 Market'], ['--c-3', '3'], ['--c-4', '4'], ['--c-5', '5'], ['--c-6', '6'], ['--c-7', '7'], ['--c-8', '8'], ['--c-other', 'Other']]);
  $('#sw-seq').innerHTML = sw([['--seq-1', 'Seq 1'], ['--seq-3', 'Seq 3'], ['--seq-5', 'Seq 5'], ['--div-neg', 'Diverging −'], ['--div-mid', 'Midpoint'], ['--div-pos', 'Diverging +'], ['--st-good', 'Good'], ['--st-warn', 'Warning'], ['--st-serious', 'Serious'], ['--st-crit', 'Critical'], ['--up', 'Delta up'], ['--down', 'Delta down']]);
  var teams = [['Chicago Bears', '#0B162A'], ['Seattle Kraken', '#001628'], ['Los Angeles Kings', '#111111'], ['Boston Bruins', '#FFB81C'], ['Pittsburgh Pirates', '#27251f'], ['Mercedes', '#00D7B6'], ['Philadelphia Flyers', '#F74902'], ['Brooklyn Nets', '#000000']];
  var surf = QK.color.surface();
  $('#team-contrast').innerHTML = '<b class="qk-kicker">Team</b><b class="qk-kicker">Raw kit</b><b class="qk-kicker">On this card</b><b class="qk-kicker">Monogram</b>' + teams.map(function (t) {
    var fixed = QK.color.team(t[1]);
    return '<span>' + esc(t[0]) + '</span><span class="qk-row"><i class="bar" style="background:' + t[1] + '"></i><span class="num qk-muted">' + QK.color.contrast(t[1], surf).toFixed(1) + ':1</span></span>' +
      '<span class="qk-row"><i class="bar" style="background:' + fixed + '"></i><span class="num">' + QK.color.contrast(fixed, surf).toFixed(1) + ':1</span></span>' + QK.teamMark({ name: t[0], colour: t[1] });
  }).join('');
}

/* ── space */
$('#sg-space').innerHTML = [1, 2, 3, 4, 5, 6, 8, 10, 12, 16].map(function (n) { var px = QK.cssVar('--sp-' + n); return '<span><i style="width:' + px + ';height:' + px + '"></i>' + n + ' · ' + px + '</span>'; }).join('');

/* ── KPIs */
$('#kpis').innerHTML = [
  QK.kpi({ label: 'Title odds', value: '62.4%', delta: 4.1, deltaFmt: function (d) { return QK.fmt.signed(d) + ' pts'; }, sub: 'this week', spark: [41, 44, 43, 50, 55, 58, 62.4] }),
  QK.kpi({ label: 'Net rating', value: '+8.7', delta: -1.2, sub: 'per 100 possessions', spark: [6, 7.5, 9.9, 9.1, 8.7], sparkColor: 'var(--c-1)' }),
  QK.kpi({ label: 'xG for', value: '18.4', sub: '7 games · 2.6 per game', tip: 'Expected goals from every shot taken' }),
  QK.kpi({ label: 'Top scorer', value: 'Erling Haaland', text: true, sub: '8 G · 6.9 xG' }),
  QK.kpi({ label: 'Model accuracy', value: '0.198', sub: 'Brier, last 500 games', delta: -0.004, deltaFmt: function (d) { return d.toFixed(3); } })
].join('');
$('#spark-big').innerHTML = '<div class="qk-kicker" style="margin-bottom:6px">Elo, last 30 matches</div>' + QK.spark([1810, 1822, 1815, 1830, 1846, 1841, 1860, 1871, 1866, 1880, 1895, 1902, 1890, 1911], { w: 320, h: 70, color: 'var(--accent)', label: 'Elo rising from 1810 to 1911' });

/* ── table */
var qbs = [
  { n: 'Brock Purdy', t: 'SF', c: '#AA0000', comp: 121.3, epa: 0.31, cpoe: 6.2, ypa: 8.9, p1: 99, p2: 97, p3: 96 },
  { n: 'Jared Goff', t: 'DET', c: '#0076B6', comp: 116.7, epa: 0.27, cpoe: 5.1, ypa: 8.4, p1: 96, p2: 93, p3: 90 },
  { n: 'Josh Allen', t: 'BUF', c: '#00338D', comp: 112.0, epa: 0.24, cpoe: 2.8, ypa: 7.9, p1: 92, p2: 74, p3: 81 },
  { n: 'Lamar Jackson', t: 'BAL', c: '#241773', comp: 109.8, epa: 0.22, cpoe: 3.4, ypa: 8.1, p1: 88, p2: 80, p3: 85 },
  { n: 'Patrick Mahomes', t: 'KC', c: '#E31837', comp: 104.2, epa: 0.17, cpoe: 1.9, ypa: 7.2, p1: 79, p2: 62, p3: 58 },
  { n: 'Bo Nix', t: 'DEN', c: '#FB4F14', comp: 96.1, epa: 0.08, cpoe: -0.6, ypa: 6.6, p1: 55, p2: 38, p3: 33 },
  { n: 'Bryce Young', t: 'CAR', c: '#0085CA', comp: 84.4, epa: -0.04, cpoe: -2.9, ypa: 6.0, p1: 21, p2: 15, p3: 14 },
  { n: 'Drew Lock', t: 'SEA', c: '#002244', comp: 79.0, epa: -0.09, cpoe: -4.1, ypa: 5.7, p1: 9, p2: 6, p3: 8 }
];
QK.table('#tbl', {
  rows: qbs, rank: true, sort: { key: 'comp', dir: 'desc' }, maxHeight: 340, caption: 'Quarterback composite leaders',
  columns: [
    { key: 'n', label: 'Player', sticky: true, fmt: function (v, r) { return '<a class="qk-entity" href="#tables">' + QK.teamMark({ abbr: r.t, colour: r.c }, 'sm') + '<span class="qk-entity-name">' + esc(v) + '</span><span class="qk-entity-meta">' + r.t + '</span></a>'; } },
    { key: 'comp', label: 'Composite', num: true, d: 1, pctl: 'p1', tip: 'Blend of EPA per dropback and CPOE, scaled to 100 = league average' },
    { key: 'epa', label: 'EPA/db', num: true, fmt: function (v) { return QK.fmt.signed(v, 2); }, pctl: 'p2' },
    { key: 'cpoe', label: 'CPOE', num: true, fmt: function (v) { return QK.fmt.signed(v, 1); }, pctl: 'p3' },
    { key: 'ypa', label: 'Y/A', num: true, d: 1 }
  ]
});
$('#pbars').innerHTML = QK.pctlBars([
  { label: 'xwOBA', pctl: 97, value: '.412' }, { label: 'Barrel %', pctl: 91, value: '17.8' }, { label: 'Hard-hit %', pctl: 84, value: '52.1' },
  { label: 'Chase %', pctl: 62, value: '25.4' }, { label: 'Whiff %', pctl: 38, value: '27.0' }, { label: 'Sprint speed', pctl: 12, value: '25.9' }, { label: 'OAA', pctl: 50, value: '0' }
]);

/* ── controls */
QK.tabs($('#tabs-demo'));
QK.seg($('#seg-demo'));
$('#chips-demo').innerHTML = [['all', 'All sports', null, 43]].concat(QK.SPORTS.map(function (s) { return [s.key, s.label, s.key, Math.round(Math.random() * 12) + 1]; })).map(function (c, i) {
  return '<button class="qk-chip" data-value="' + c[0] + '" aria-pressed="' + (i === 0) + '" style="--ca:' + (c[2] ? 'var(--a-' + c[2] + ')' : 'var(--brand)') + '">' + (c[2] ? QK.ICON[c[2]] : '') + esc(c[1]) + ' <span class="n">' + c[3] + '</span></button>';
}).join('');
QK.chips($('#chips-demo'));

/* ── games */
var now = Date.now();
function iso(h) { return new Date(now + h * 3600e3).toISOString(); }
var G = [
  { sport: 'football', league: 'Premier League', note: 'Round 8', start: iso(-0.8), status: 'live', home: { name: 'Newcastle', abbr: 'NEW', colour: '#241F20' }, away: { name: 'Aston Villa', abbr: 'AVL', colour: '#95BFE5' }, hs: 1, as: 1, p_home: 0.47, p_draw: 0.24, p_away: 0.29, xg: [1.4, 0.9] },
  { sport: 'basketball', league: 'WNBA', note: 'Finals · G1', start: iso(3), status: 'pre', home: { name: 'Valkyries', abbr: 'GS', colour: '#B38FCF' }, away: { name: 'Liberty', abbr: 'NY', colour: '#6ECEB2' }, p_home: 0.69, market_home: 0.56 },
  { sport: 'hockey', league: 'NHL', start: iso(-1.5), status: 'live', period: 2, home: { name: 'Capitals', abbr: 'WSH', colour: '#C8102E' }, away: { name: 'Devils', abbr: 'NJD', colour: '#CE1126' }, hs: 3, as: 1, p_home: 0.58, market_home: 0.85 },
  { sport: 'baseball', league: 'MLB', note: 'ALCS · G4', start: iso(5), status: 'pre', home: { name: 'Guardians', abbr: 'CLE', colour: '#002b5c' }, away: { name: 'Rays', abbr: 'TB', colour: '#092c5c' }, p_home: 0.526, market_home: 0.485 },
  { sport: 'nfl', league: 'NFL', note: 'Week 6', start: iso(-20), status: 'final', home: { name: 'Broncos', abbr: 'DEN', colour: '#FB4F14' }, away: { name: 'Seahawks', abbr: 'SEA', colour: '#002244' }, hs: 17, as: 14 },
  { sport: 'tennis', league: 'ATP · Shanghai Masters', note: 'F', start: iso(14), status: 'pre', home: { name: 'A. Davidovich Fokina' }, away: { name: 'R. Jodar' }, p_home: 0.503, market_home: 0.441 }
];
$('#cards-demo').innerHTML = G.map(function (g) { return QK.matchCard(g); }).join('');
$('#ticker-demo').innerHTML = G.concat(G).map(QK.tick).join('');

/* ── headers */
function teamHeader() {
  var c = QK.color.team('#00338D');
  $('#hdr-team').innerHTML = '<div class="qk-hero" style="--tc:' + c + '"><div class="qk-hero-in">' + QK.teamMark({ abbr: 'BUF', colour: '#00338D' }, 'lg') +
    '<div><div class="qk-kicker">AFC East · 4–1</div><h1>Buffalo Bills</h1><div class="qk-hero-meta"><span>Rating <b>+6.1</b></span><span>Rank <b>3rd</b></span><span>Next <b>v MIA, Sun</b></span></div></div>' +
    '<div class="qk-hero-stats"><div class="qk-hero-stat"><div class="v">94%</div><div class="l">Playoffs</div></div><div class="qk-hero-stat"><div class="v">19%</div><div class="l">Super Bowl</div></div></div></div></div>';
  $('#hdr-player').innerHTML = '<div class="qk-hero" style="--tc:' + QK.color.team('#6CABDD') + '"><div class="qk-hero-in"><div class="qk-avatar" style="--tc:' + QK.color.team('#6CABDD') + '">EH</div>' +
    '<div><div class="qk-kicker">Manchester City · Forward · 26</div><h1>Erling Haaland</h1><div class="qk-hero-meta"><span>Norway</span><span>Value <b>€180m</b></span><span>Contract <b>2034</b></span></div></div>' +
    '<div class="qk-hero-stats"><div class="qk-hero-stat"><div class="v">8</div><div class="l">Goals</div></div><div class="qk-hero-stat"><div class="v">6.9</div><div class="l">xG</div></div><div class="qk-hero-stat"><div class="v">99</div><div class="l">Pctl</div></div></div></div></div>';
}

/* ── feedback */
$('#sk1').innerHTML = QK.skeleton('lines', 5);
$('#sk2').innerHTML = QK.skeleton('chart', 1);
$('#empty1').innerHTML = QK.empty('No games today', 'The next slate starts Saturday at 12:30.');

/* ── charts */
var rounds = []; for (var i = 1; i <= 17; i++) rounds.push(i);
function cum(seed, pts) { var s = 0, out = []; for (var i = 0; i < 17; i++) { s += pts[(i * seed + 3) % pts.length]; out.push(s); } return out; }
QKC.line('#ch-line', {
  x: rounds, xLabel: function (r) { return 'Round ' + r; }, yFmt: function (v) { return QK.fmt.num(v); }, label: 'Drivers championship points by round',
  series: [
    { name: 'Antonelli', color: '#00D7B6', data: cum(5, [25, 18, 25, 15, 25, 12, 18, 25]) },
    { name: 'Russell', color: '#7fe8d8', data: cum(3, [18, 15, 12, 25, 10, 15, 8, 18]), dash: true },
    { name: 'Verstappen', color: '#4781D7', data: cum(7, [12, 25, 8, 18, 6, 25, 10, 15]) },
    { name: 'Leclerc', color: '#ED1131', data: cum(2, [15, 10, 18, 8, 12, 6, 15, 10]) },
    { name: 'Norris', color: '#F47600', data: cum(4, [10, 12, 6, 12, 18, 8, 12, 6]) }
  ]
});
QKC.line('#ch-area', { x: ['W1', 'W2', 'W3', 'W4', 'W5', 'W6'], series: [{ name: 'Net rating', data: [1.3, 2.9, 4.2, 3.8, 5.6, 6.1], area: true, color: QK.cssVar('--accent') }], ref: { y: 0, label: 'avg' }, yFmt: function (v) { return QK.fmt.signed(v, 0); }, endLabels: false });
var odds = [['Bills', 0.19, '#00338D'], ['Jaguars', 0.118, '#006778'], ['Lions', 0.084, '#0076B6'], ['Chiefs', 0.081, '#E31837'], ['Vikings', 0.073, '#4F2683'], ['Patriots', 0.06, '#002244'], ['Rams', 0.043, '#003594'], ['Bengals', 0.028, '#FB4F14']];
QKC.bar('#ch-hbar', { horizontal: true, cats: odds.map(function (o) { return o[0]; }), series: [{ name: 'Super Bowl', data: odds.map(function (o) { return o[1]; }) }], colors: odds.map(function (o) { return o[2]; }), labels: true, fmt: function (v) { return QK.fmt.pct(v, 1); }, label: 'Super Bowl odds' });
QKC.dumbbell('#ch-db', { rows: [
  { label: 'Sharks make the playoffs', a: 0.107, b: 0.525 }, { label: 'Man City win the EPL', a: 0.529, b: 0.213 }, { label: 'Bruins make the playoffs', a: 0.768, b: 0.468 },
  { label: 'Bears make the playoffs', a: 0.296, b: 0.553 }, { label: 'Verstappen wins in Austin', a: 0.179, b: 0.374 }, { label: 'Inter win Serie A', a: 0.796, b: 0.598 }
] });
var ga = [['NYR', 6.2], ['TOR', 4.1], ['EDM', 3.0], ['COL', 1.4], ['BOS', 0.3], ['DAL', -0.8], ['VGK', -1.9], ['CHI', -3.6], ['SJS', -5.4]];
QKC.bar('#ch-bar', { cats: ga.map(function (x) { return x[0]; }), series: [{ name: 'Goals above expected', data: ga.map(function (x) { return x[1]; }) }], diverging: true, fmt: function (v) { return QK.fmt.signed(v, 1); } });
var sc = [['VGK', 0.57, 0.778, '#B4975A'], ['COL', 0.58, 0.69, '#6F263D'], ['CAR', 0.6, 0.72, '#CE1126'], ['EDM', 0.55, 0.6, '#FF4C00'], ['SJS', 0.43, 0.3, '#006D75'], ['CHI', 0.44, 0.38, '#CF0A2C'], ['BOS', 0.47, 0.71, '#FFB81C'], ['FLA', 0.54, 0.42, '#C8102E'], ['NYR', 0.49, 0.66, '#0038A8'], ['TOR', 0.52, 0.5, '#00205B'], ['DAL', 0.53, 0.58, '#006847'], ['SEA', 0.46, 0.62, '#99D9D9']];
QKC.scatter('#ch-sc', { points: sc.map(function (p) { return { name: p[0], x: p[1], y: p[2], color: p[3], label: p[0] }; }), xName: 'xG share 5v5', yName: 'Points %', xFmt: function (v) { return QK.fmt.pct(v, 0); }, yFmt: function (v) { return QK.fmt.pct(v, 0); }, refX: 0.5, refY: 0.5, labelAll: true, quadrants: ['Lucky', 'Good', 'Bad', 'Unlucky'] });
var counts = ['0-0', '0-1', '0-2', '1-0', '1-1', '1-2', '2-0', '2-1', '2-2', '3-0', '3-1', '3-2'];
var pitches = ['Four-seam', 'Sinker', 'Slider', 'Sweeper', 'Curve', 'Changeup', 'Splitter'];
var hm = []; counts.forEach(function (c, xi) { pitches.forEach(function (p, yi) { hm.push([xi, yi, Math.round((Math.sin(xi * 1.3 + yi * 2.1) * 1.6 + (yi === 3 ? -0.8 : 0) + (xi > 8 ? 0.7 : 0)) * 10) / 10]); }); });
QKC.heatmap('#ch-hm', { x: counts, y: pitches, data: hm, diverging: true, mid: 0, fmt: function (v) { return QK.fmt.signed(v, 1); } });
var t = [], p = [], q = 0.55; for (var m = 0; m <= 60; m++) { q = Math.max(0.02, Math.min(0.98, q + Math.sin(m / 3.1) * 0.035 + (m === 21 ? 0.14 : 0) + (m === 44 ? -0.42 : 0) + (m === 57 ? 0.3 : 0))); t.push(m); p.push(m === 60 ? 1 : q); }
QKC.winProb('#ch-wp', { t: t, p: p, home: { name: 'Broncos', abbr: 'DEN', colour: '#FB4F14' }, away: { name: 'Seahawks', abbr: 'SEA', colour: '#002244' }, periods: [15, 30, 45], interval: 15, tFmt: function (v) { return 'Q' + Math.min(4, Math.floor(v / 15) + 1) + ' ' + (15 - v % 15) + ':00'; }, events: [{ t: 21, label: 'TD' }, { t: 44, label: 'INT' }, { t: 57, label: 'FG' }] });

/* shot maps: deterministic pseudo-random */
var seed = 7; function rnd() { seed = (seed * 16807) % 2147483647; return seed / 2147483647; }
function shots(n, f) { var out = []; for (var i = 0; i < n; i++) out.push(f(i)); return out; }
QKC.shotMap('#sm-pitch', { surface: 'pitch', label: 'Shot map, demo match', shots: shots(28, function () { var x = 105 - rnd() * 30 - 2, y = 34 + (rnd() - 0.5) * 34; var d = Math.hypot(105 - x, 34 - y); var xg = Math.max(0.02, Math.min(0.8, 0.9 * Math.exp(-d / 7))); return { x: x, y: y, v: xg, made: rnd() < xg, name: 'Shot ' + Math.round(d) + ' m out' }; }) });
QKC.shotMap('#sm-rink', { surface: 'rink', label: 'Shot map, demo game', shots: shots(46, function (i) { var side = i % 2 ? 1 : -1; var x = side * (89 - rnd() * 55), y = (rnd() - 0.5) * 70; var d = Math.hypot(side * 89 - x, y); var xg = Math.max(0.01, Math.min(0.5, 0.45 * Math.exp(-d / 18))); return { x: x, y: y, v: xg, made: rnd() < xg * 0.9, name: (side > 0 ? 'Home' : 'Away') + ' shot · ' + Math.round(d) + ' ft' }; }) });
QKC.shotMap('#sm-court', { surface: 'court', sizeScale: 11, label: 'Shot chart, demo player', madeLabel: 'Make', missLabel: 'Miss', vName: 'Exp. pts', shots: shots(70, function () { var a = (rnd() - 0.5) * Math.PI, r = rnd() < 0.4 ? rnd() * 8 : 18 + rnd() * 9; var x = Math.sin(a) * r, y = Math.cos(a) * r; var three = r > 22; return { x: x, y: Math.max(-4, y), v: three ? 1.1 : 1.0, made: rnd() < (r < 6 ? 0.62 : three ? 0.37 : 0.42), name: three ? 'Three' : r < 6 ? 'At the rim' : 'Mid-range' }; }) });
QKC.shotMap('#sm-field', { surface: 'field', sizeScale: 16, label: 'Spray chart, demo hitter', madeLabel: 'Hit', missLabel: 'Out', vName: 'xBA', shots: shots(60, function () { var a = (rnd() - 0.5) * Math.PI / 2 * 0.92, r = rnd() < 0.3 ? 60 + rnd() * 100 : 180 + rnd() * 215; var xba = r > 380 ? 0.9 : r < 150 ? 0.25 : 0.32; return { x: Math.sin(a) * r, y: Math.cos(a) * r, v: xba, made: rnd() < xba, name: Math.round(r) + ' ft' }; }) });

paintSwatches(); teamHeader();
QK.theme.onChange(function () { setTimeout(function () { paintSwatches(); teamHeader(); }, 40); });
})();
