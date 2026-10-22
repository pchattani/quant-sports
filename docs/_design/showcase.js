/* Kit v2 showcase: every Design System 2.0 component on sample data (not shipped to any site). ES5. */
(function () {
'use strict';
var $ = QK.$, esc = QK.esc;
var day = 864e5, now = Date.now();
function iso(h) { return new Date(now + h * 36e5).toISOString(); }
var T = {
  BOS: { name: 'Boston Bruins', abbr: 'BOS', colour: '#FFB81C', record: '6-2-0', form: 'WWLWW' },
  TOR: { name: 'Toronto Maple Leafs', abbr: 'TOR', colour: '#00205B', record: '4-3-1', form: 'LWOLW' },
  EDM: { name: 'Edmonton Oilers', abbr: 'EDM', colour: '#041E42', record: '5-2-0', form: 'WWWLW' },
  COL: { name: 'Colorado Avalanche', abbr: 'COL', colour: '#6F263D', record: '7-1-0', form: 'WWWWL' },
  WSH: { name: 'Washington Capitals', abbr: 'WSH', colour: '#C8102E', record: '5-3-0', form: 'LWWLW' },
  NJD: { name: 'New Jersey Devils', abbr: 'NJD', colour: '#CE1126', record: '4-4-0', form: 'LLWWL' },
  ARS: { name: 'Arsenal', abbr: 'ARS', colour: '#EF0107', form: 'WDWWW' },
  CHE: { name: 'Chelsea', abbr: 'CHE', colour: '#034694', form: 'WLDWW' }
};
var GAMES = [
  { sport: 'hockey', league: 'NHL', status: 'live', start: iso(-1.5), away: T.NJD, home: T.WSH, as: 2, hs: 3, period: 3, p_home: 0.81, href: '#scoreboard' },
  { sport: 'hockey', league: 'NHL', status: 'pre', start: iso(3), away: T.TOR, home: T.BOS, p_home: 0.58, market_home: 0.55, href: '#scoreboard' },
  { sport: 'hockey', league: 'NHL', status: 'pre', start: iso(5), away: T.COL, home: T.EDM, p_home: 0.47, market_home: 0.52, href: '#scoreboard' },
  { sport: 'football', league: 'Premier League', status: 'pre', start: iso(20), away: T.CHE, home: T.ARS, p_home: 0.54, p_draw: 0.24, p_away: 0.22, market_home: 0.57, href: '#scoreboard' },
  { sport: 'hockey', league: 'NHL', status: 'final', start: iso(-26), away: T.EDM, home: T.TOR, as: 5, hs: 4, note: 'OT', p_home: 0.53, xg: [3.4, 2.9], href: '#scoreboard' },
  { sport: 'basketball', league: 'NBA', status: 'pre', start: iso(6), away: { name: 'Celtics', abbr: 'BOS', colour: '#007A33' }, home: { name: 'Knicks', abbr: 'NYK', colour: '#F58426' }, p_home: 0.44, href: '#scoreboard' },
  { sport: 'baseball', league: 'MLB', status: 'final', start: iso(-20), away: { name: 'Dodgers', abbr: 'LAD', colour: '#005A9C' }, home: { name: 'Yankees', abbr: 'NYY', colour: '#0C2340' }, as: 4, hs: 2, p_home: 0.51, href: '#scoreboard' }
];

QK.shell({
  sport: null,
  sections: [['identity', 'Identity'], ['scoreboard', 'Scoreboard'], ['stats', 'Stat tiles'], ['player', 'Player'], ['forecast', 'Forecasts'], ['tables', 'Leaderboard'], ['compare', 'Compare'], ['copy', 'Copy']].map(function (x) { return { key: x[0], label: x[1], href: '#' + x[0] }; }),
  section: 'identity',
  ctx: '<span class="qk-tag signal">Kit ' + esc(QK.version) + '</span>'
});
$('#sc-ticker').innerHTML = QK.ticker(GAMES);

$('#sc-hero').innerHTML = QK.sectionHead({ kicker: 'Design System 2.0 · sample data', title: 'Signal: the kit, on one page', size: 'lg', tag: 'h1',
  sub: 'Bloomberg density, ESPN scoreboard energy, 538 probability stories, Savant percentile cards — in one look of our own. Every block below is the real kit (assets/qk), drawn on sample numbers, in both themes and at 375 px.',
  actions: '<a class="qk-btn primary" href="#scoreboard">Components</a><button class="qk-btn" type="button" data-qk-theme-toggle-btn>Toggle theme</button>' });
var tb = document.querySelector('[data-qk-theme-toggle-btn]'); if (tb) tb.addEventListener('click', QK.theme.toggle);

function head(id, kicker, title, sub) { $('#h-' + id).innerHTML = QK.sectionHead({ kicker: kicker, title: title, sub: sub }); }
head('identity', 'Identity', 'Colour and type', 'One signature accent (signal violet) means "ours". Sport accents mark identity only. The percentile scale runs cold to hot. Team colours are accents, contrast-checked.');
var SW = [['--signal', 'Signal', 'ours: forecast, rating, primary action'], ['--c-market', 'Market', 'a quiet reference, never a headline'], ['--wp-a', 'Win prob A', 'fallback when kits clash'], ['--wp-b', 'Win prob B', 'fallback when kits clash'],
  ['--pc-0', 'Percentile 0', 'cold: worst in peers'], ['--pc-50', 'Percentile 50', 'average'], ['--pc-100', 'Percentile 100', 'hot: best in peers'], ['--live', 'Live', 'live status only'],
  ['--a-football', 'Football', 'sport mark'], ['--a-hockey', 'Hockey', 'sport mark'], ['--a-nfl', 'NFL', 'sport mark (gold in v2)'], ['--a-baseball', 'Baseball', 'sport mark']];
$('#sc-swatches').innerHTML = SW.map(function (s) { return '<div class="sc-sw"><i style="--k:var(' + s[0] + ')"></i><div><b>' + esc(s[1]) + '</b><code>' + esc(s[0]) + '</code><div class="qk-muted">' + esc(s[2]) + '</div></div></div>'; }).join('');
$('#sc-chips').innerHTML = [3, 18, 35, 50, 64, 81, 97].map(QK.pctlChip).join('');
$('#sc-type').innerHTML = [
  ['Display d1 · Archivo 800', '<span class="qk-display" style="font-size:var(--fs-d1);line-height:1">Every game, by the numbers.</span>', '--fs-d1'],
  ['Display d2 · page title', '<span class="qk-display" style="font-size:var(--fs-d2)">Connor McDavid</span>', '--fs-d2'],
  ['Display d3 · stat number', '<span class="qk-display" style="font-size:var(--fs-d3)">63.8% · 2.41 · +0.31</span>', '--fs-d3'],
  ['UI · Inter 15/1.55', '<span>Our chance comes from 20,000 simulated seasons. The market is shown as a reference.</span>', '--font-ui'],
  ['Data · JetBrains Mono', '<span class="num">BOS 4  TOR 3  ·  xG 3.41–2.07  ·  23:54 TOI</span>', '--font-num']
].map(function (r) { return '<div><div class="qk-kicker">' + esc(r[0]) + '<br><code>' + esc(r[2]) + '</code></div><div>' + r[1] + '</div></div>'; }).join('');

head('scoreboard', 'Scoreboard', 'Ticker, game cards, win-probability bars', 'The ticker (above the page) groups by sport, live first. Cards put our chance first: the favourite in the signal colour, the bar in team colours, the market a hollow ring and a tick.');
$('#sc-cards').innerHTML = GAMES.map(function (g) { return QK.gameCard(g); }).join('') +
  '<div class="qk-card"><div class="qk-card-body"><div class="qk-kicker" style="margin-bottom:10px">QK.wpBar, large</div>' + QK.wpBar(0.42, null, 0.58, T.TOR, T.BOS, { size: 'lg', market: 0.45 }) +
  '<div class="qk-kicker" style="margin:14px 0 10px">Three-way (draw)</div>' + QK.wpBar(0.22, 0.24, 0.54, T.CHE, T.ARS) + '</div></div>';

head('stats', 'Stat tiles', 'Big numbers with context', 'A label, one display number with its unit, a delta or context line, an optional percentile chip and a trend.');
$('#sc-stats').innerHTML = QK.stats([
  { label: 'Cup favourite', value: 'COL 17%', sub: 'from 20,000 simulated seasons', signal: true, tip: 'Our chance of winning the Stanley Cup' },
  { label: '5v5 expected goals share', value: '63.8', unit: '%', delta: 4.1, deltaFmt: function (v) { return '+' + v.toFixed(1) + ' pts'; }, sub: 'last 10 games', pctl: 96, trend: [52, 55, 54, 58, 57, 61, 60, 64, 63, 64] },
  { label: 'Goals saved above expected', value: '+7.3', sub: 'Linus Ullmark · 9 starts', pctl: 99, trend: [0.2, 1.1, 1.9, 2.4, 3.8, 4.1, 5.5, 6.2, 7.3] },
  { label: 'Points per 60', value: '6.46', delta: -0.4, sub: 'v 6.86 last season', pctl: 100 },
  { label: 'Live now', value: '3', sub: '14 games today', text: false }
]);

head('player', 'Player', 'Player card, percentiles, distribution, matchup', 'The header carries the team colour as a band; percentiles always name the peer group and the sample.');
$('#sc-ph').innerHTML = QK.playerHeader({ name: 'Connor McDavid', number: 97, pos: 'Centre', team: { name: 'Edmonton Oilers', abbr: 'EDM', colour: '#041E42', href: '#player' }, kicker: '2026-27',
  meta: [['Age', '29'], ['Height', '6′1″'], ['Shoots', 'L'], ['Drafted', '2015 · 1st overall']], tags: [QK.tag('Qualified', 'signal'), QK.tag('Top line · PP1')],
  stats: [{ label: 'GP', value: 7 }, { label: 'Goals', value: 4 }, { label: 'Assists', value: 14 }, { label: 'Points', value: 18 }] });
$('#sc-pcard').innerHTML = QK.pctCard({ peer: 'NHL forwards', sample: '7 GP · 117 min at 5v5 · min 5 GP', groups: [
  { label: 'Scoring', rows: [{ label: 'Points / 60', pctl: 100, value: '6.46', tip: 'Points per 60 minutes, all situations' }, { label: 'Goals / 60', pctl: 84, value: '1.43' }, { label: 'ixG / 60', pctl: 90, value: '0.92', tip: 'Individual expected goals per 60' }, { label: 'Goals above xG', pctl: 74, value: '+0.51', early: true }] },
  { label: 'Play driving (5v5)', rows: [{ label: 'xGF%', pctl: 100, value: '69.8%' }, { label: 'RAPM offence', pctl: 99, value: '+0.31' }, { label: 'RAPM defence', pctl: 50, value: '0.00' }] },
  { label: 'Physical', rows: [{ label: 'Hits / 60', pctl: 52, value: '2.1' }, { label: 'Takeaways / 60', pctl: 47, value: '1.0' }, { label: 'Faceoff %', pctl: 38, value: '48.3%' }, { label: 'Blocks / 60', pctl: 9, value: '0.3' }] }
] });
var dv = []; for (var i = 0; i < 380; i++) { var u = 0; for (var j = 0; j < 6; j++) u += Math.sin(i * (j + 3) * 12.9898) * 43758.5453 % 1; dv.push(Math.max(0.2, 1.9 + Math.abs(u) * 0.55 + (i % 17 === 0 ? 1.2 : 0))); }
QKC.distribution('#sc-dist', { values: dv, binCount: 24, marks: [{ x: 6.46, label: 'McDavid' }, { x: 2.3, label: 'Median' }], xName: 'Points per 60, all situations', yName: 'Forwards', fmt: function (v) { return v.toFixed(1); }, min: 0, max: 7 });
$('#sc-mu').innerHTML = QK.matchupBar({ left: T.BOS, right: T.TOR, rows: [
  { label: '5v5 xGF / 60', a: 3.01, b: 2.64 }, { label: '5v5 xGA / 60', a: 2.41, b: 2.88, better: 'low' }, { label: 'Power play %', a: 0.231, b: 0.274, fmt: function (v) { return (v * 100).toFixed(1) + '%'; } },
  { label: 'Goalie GSAx', a: 5.8, b: -1.2, fmt: function (v) { return (v > 0 ? '+' : '') + v.toFixed(1); } }, { label: 'Team rating', a: 0.31, b: 0.08, fmt: function (v) { return (v > 0 ? '+' : '') + v.toFixed(2); } }] });

head('forecast', 'Forecasts', 'Chances over time and chance bars', 'The 538 pattern: one line per team, labelled at its end, an uncertainty band, annotations for what moved it, and the market as a quiet tick on bar charts.');
var xs = [], b1 = [], b2 = [], b3 = [];
for (var d = 0; d < 40; d++) { xs.push(new Date(Date.UTC(2026, 9, 1) + d * 2 * day).toISOString().slice(0, 10)); b1.push(Math.min(0.97, 0.62 + d * 0.007 + Math.sin(d / 3) * 0.03)); b2.push(Math.max(0.05, 0.55 - d * 0.009 + Math.cos(d / 4) * 0.04)); b3.push(0.4 + Math.sin(d / 6) * 0.12); }
function band(a, w) { return { lo: a.map(function (v, k) { return Math.max(0, v - w * (1 - k / 60)); }), hi: a.map(function (v, k) { return Math.min(1, v + w * (1 - k / 60)); }) }; }
QKC.forecast('#sc-fc', { x: xs, xType: 'time', series: [{ name: 'Bruins', label: 'BOS', data: b1, color: T.BOS.colour, band: band(b1, 0.12) }, { name: 'Maple Leafs', label: 'TOR', data: b2, color: '#3d6fd8', band: band(b2, 0.12) }, { name: 'Senators', label: 'OTT', data: b3, color: '#C52032' }],
  annotations: [{ x: xs[9], label: 'Matthews injured' }, { x: xs[24], label: 'Trade deadline' }], today: xs[33], split: { x: xs[33], label: 'Projection' }, yName: 'Chance to make the playoffs', xName: 'Date' });
$('#sc-chances').innerHTML = QK.chances([{ label: 'Colorado', p: 0.168, market: 0.10, color: T.COL.colour, href: '#forecast' }, { label: 'Carolina', p: 0.138, market: 0.09, color: '#CE1126' }, { label: 'Vegas', p: 0.091, market: 0.11, color: '#B4975A' }, { label: 'Tampa Bay', p: 0.052, market: 0.06, color: '#002868' }, { label: 'Edmonton', p: 0.049, market: 0.08, color: T.EDM.colour }, { label: 'Boston', p: 0.045, color: T.BOS.colour }]);
var tt = [], pp = [], v0 = 0.54; for (var k = 0; k <= 60; k += 1) { tt.push(k); v0 = Math.max(0.02, Math.min(0.98, v0 + Math.sin(k * 1.7) * 0.03 + (k === 12 ? -0.17 : 0) + (k === 31 ? 0.2 : 0) + (k === 47 ? 0.15 : 0))); pp.push(v0); }
QKC.winProb('#sc-wp', { t: tt, p: pp, home: T.WSH, away: T.NJD, events: [{ t: 12, label: 'NJD' }, { t: 31, label: 'WSH' }, { t: 47, label: 'WSH' }], periods: [20, 40, 60], tFmt: function (v) { return Math.round(v) + "'"; } });
QKC.chances('#sc-chc', { rows: [{ label: 'Arsenal', p: 0.44, market: 0.62, color: T.ARS.colour }, { label: 'Man City', p: 0.53, market: 0.21, color: '#6CABDD' }, { label: 'Liverpool', p: 0.015, market: 0.04, color: '#C8102E' }, { label: 'Chelsea', p: 0.009, market: 0.07, color: T.CHE.colour }], valName: 'Chance to win the league', labelWidth: 90 });

head('tables', 'Tables', 'Leaderboard', 'Dense, sortable, sticky header and first column; heat cells use the percentile scale against the position peer group.');
var LB = [['Connor McDavid', 'EDM', 'C', 18, 6.46, 100, 0.698, 99, [1, 3, 2, 5, 1, 4, 2]], ['Nathan MacKinnon', 'COL', 'C', 16, 5.12, 98, 0.611, 93, [2, 2, 3, 1, 4, 2, 2]], ['Jack Eichel', 'VGK', 'C', 16, 4.87, 97, 0.582, 88, [0, 2, 3, 3, 2, 4, 2]],
  ['Evan Bouchard', 'EDM', 'D', 15, 3.96, 99, 0.655, 97, [1, 1, 4, 2, 3, 2, 2]], ['Kirill Kaprizov', 'MIN', 'L', 14, 4.40, 95, 0.540, 72, [3, 0, 2, 1, 3, 4, 1]], ['Auston Matthews', 'TOR', 'C', 12, 3.88, 90, 0.502, 55, [2, 1, 0, 3, 2, 2, 2]]];
QK.leaderboard('#sc-lb', { dense: true, rank: true, sort: { key: 'p', dir: 'desc' }, rowClass: function (r) { return r.name === 'Connor McDavid' ? 'is-me' : ''; }, columns: [
  { key: 'name', label: 'Player', type: 'entity', sub: 'pos', mark: function (r) { return { abbr: r.team, colour: { EDM: '#041E42', COL: '#6F263D', VGK: '#B4975A', MIN: '#154734', TOR: '#00205B' }[r.team] }; } },
  { key: 'p', label: 'Pts', num: true, type: 'bar' }, { key: 'p60', label: 'P/60', type: 'pctl', pctl: 'p60_pct', fmt: function (v) { return v.toFixed(2); } },
  { key: 'xgf', label: 'xGF%', type: 'pctl', pctl: 'xgf_pct', fmt: function (v) { return (v * 100).toFixed(1) + '%'; } }, { key: 'last', label: 'Last 7', type: 'spark' }],
  rows: LB.map(function (r) { return { name: r[0], team: r[1], pos: r[2], p: r[3], p60: r[4], p60_pct: r[5], xgf: r[6], xgf_pct: r[7], last: r[8] }; }) });

head('compare', 'Compare', 'Two or three players, one metric set', 'Values with a percentile bar against the position peer group; the better value is bold; for two players, the difference (green when the first is better).');
var CMPG = [{ label: 'Scoring', rows: [{ label: 'Points / 60', values: [6.46, 5.12], pctls: [100, 98] }, { label: 'Goals / 60', values: [1.43, 1.88], pctls: [84, 95] }, { label: 'ixG / 60', values: [0.92, 1.21], pctls: [90, 97] }] },
  { label: 'Play driving (5v5)', rows: [{ label: 'xGF%', values: [0.698, 0.611], pctls: [100, 93], fmt: function (v) { return (v * 100).toFixed(1) + '%'; }, dfmt: function (v) { return (v > 0 ? '+' : '−') + Math.abs(v * 100).toFixed(1) + ' pts'; } },
    { label: 'xGA / 60', values: [1.46, 2.02], pctls: [99, 80], better: 'low' }, { label: 'RAPM net', values: [0.31, 0.22], pctls: [99, 96] }] }];
$('#sc-cmp2').innerHTML = QK.compareView({ entities: [{ name: 'Connor McDavid', sub: 'EDM · C · 7 GP', colour: '#041E42' }, { name: 'Nathan MacKinnon', sub: 'COL · C · 8 GP', colour: '#6F263D' }], groups: CMPG });
$('#sc-cmp3').innerHTML = QK.compareView({ entities: [{ name: 'Connor McDavid', sub: 'EDM · C' }, { name: 'Nathan MacKinnon', sub: 'COL · C' }, { name: 'Jack Eichel', sub: 'VGK · C' }],
  groups: [{ label: 'Scoring', rows: [{ label: 'Points / 60', values: [6.46, 5.12, 4.87], pctls: [100, 98, 97] }, { label: 'Goals / 60', values: [1.43, 1.88, 1.32], pctls: [84, 95, 80] }] }] });

head('copy', 'Copy', 'Say it like a friendly analyst', 'Chance, rating, projection. No betting framing. The market is context, not the story.');
$('#sc-copy').innerHTML = [
  ['Headlines', ['Every game, priced.', 'Every game, by the numbers.'], ['Biggest edges tonight', 'Closest calls tonight']],
  ['Labels', ['Model v market · Gap +9 pts · Edge', 'Our chance 58% · Market 52% (reference)'], ['Value bet', '— (never)']],
  ['Explanations', ['xGF% 0.698 rel +0.311', '70% of the expected goals at 5v5 went his team’s way with him on the ice'], ['Priced at -118', 'Our chance: 58%']]
].map(function (c) {
  return '<div class="qk-card"><div class="qk-card-head"><div class="qk-card-title">' + esc(c[0]) + '</div></div><div class="qk-card-body">' +
    [c[1], c[2]].map(function (p) { return '<p><span class="sc-bad">Not:</span> ' + esc(p[0]) + '</p><p><span class="sc-good">Say:</span> ' + esc(p[1]) + '</p>'; }).join('') + '</div></div>';
}).join('');

/* keep the section nav in step with the scroll position */
var secs = ['identity', 'scoreboard', 'stats', 'player', 'forecast', 'tables', 'compare', 'copy'];
window.addEventListener('scroll', function () {
  var cur = secs[0];
  secs.forEach(function (id) { var e = document.getElementById(id); if (e && e.getBoundingClientRect().top < 160) cur = id; });
  QK.$$('.qk-secnav a[data-sec]').forEach(function (a) { if (a.getAttribute('data-sec') === cur) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
}, { passive: true });
})();
