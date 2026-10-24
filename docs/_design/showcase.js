/* Kit v4 "Broadcast" showcase (dark only): every component on sample data (not shipped to any site). ES5.
 * The Broadcast pieces (split hero, scoreboard bug, quadrant, black band, tale of the tape, LED meters, explain strip,
 * outlined numbers) come first; then the Matchday modules and the v2 components, all drawn in the v4 look. */
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
  sections: [['broadcast', 'Broadcast'], ['matchday', 'Modules'], ['identity', 'Identity'], ['scoreboard', 'Scoreboard'], ['stats', 'Stat tiles'], ['player', 'Player'], ['forecast', 'Forecasts'], ['tables', 'Leaderboard'], ['compare', 'Compare'], ['copy', 'Copy']].map(function (x) { return { key: x[0], label: x[1], href: '#' + x[0] }; }),
  section: 'identity',
  ctx: '<span class="qk-tag signal">Kit ' + esc(QK.version) + '</span>'
});
$('#sc-ticker').innerHTML = QK.ticker(GAMES);

$('#sc-hero').innerHTML = QK.greeting({ date: 'Kit ' + QK.version + ' · sample data · dark only',
  lede: 'Broadcast: near-black and black blocks, Bebas Neue for scores and headlines, Barlow and Barlow Condensed for the rest, cobalt for ours, volt tags, team colours as big blocks, hard edges. Every block below is the real kit (assets/qk), drawn on sample numbers.',
  ctas: [{ label: 'Broadcast pieces', href: '#broadcast' }, { label: 'Modules', href: '#matchday', ghost: true }],
  side: QK.featureCard({ sport: 'basketball', league: 'WNBA', note: 'WNBA Finals · G1', status: 'live', start: iso(-2), period: 3, clock: '1:48', away: { name: 'Dream', abbr: 'ATL', colour: '#e31837' }, home: { name: 'Valkyries', abbr: 'GS', colour: '#b38fcf' }, as: 52, hs: 51, p_home: 0.55, wp_home: 0.5549, href: '#matchday' }, { scribble: 'Finals, Game 1!' }) });

/* ── v4 Broadcast pieces ── */
$('#h-broadcast').innerHTML = QK.sectionHead({ kicker: 'Broadcast', title: 'The signature pieces', sub: 'QK.splitHero (also what QK.featureCard and QK.previewCard draw), the scoreboard bug, QKC.quadrant, QK.band with QK.hotRow, QK.tape, QK.meter and QK.explain.' });
$('#sc-bc-split').innerHTML = QK.splitHero({ sport: 'hockey', league: 'NHL', status: 'pre', start: iso(4), away: { name: 'Lightning', full: 'Tampa Bay Lightning', abbr: 'TBL', colour: '#002868', record: '5-2-0' }, home: { name: 'Avalanche', full: 'Colorado Avalanche', abbr: 'COL', colour: '#6F263D', alt: '#236192', record: '5-2-1' }, p_home: 0.6, href: '#broadcast' }, { tag: 'Our pick tonight' });
$('#sc-bc-bug').innerHTML = QK.sectionHead({ kicker: 'What to watch tonight', title: 'QK.scorebug, size xl' }) + QK.previewCard({ sport: 'hockey', league: 'NHL', status: 'pre', start: iso(4), away: { name: 'Lightning', abbr: 'TBL', colour: '#002868', record: '5-2-0' }, home: { name: 'Avalanche', abbr: 'COL', colour: '#6F263D', record: '5-2-1' }, p_home: 0.6 },
  { layout: 'bug', factors: [{ label: 'Goals for per game', a: '3.0', b: '4.5', better: 'b' }, { label: 'Goals against per game', a: '2.7', b: '2.9', better: 'a' }, { label: 'Chance share, 5-on-5', a: '54.3%', b: '55.9%', better: 'b' }] });
$('#sc-bc-quad-h').innerHTML = QK.sectionHead({ kicker: 'Who’s for real?', title: 'QKC.quadrant' });
QKC.quadrant('#sc-bc-quad', { points: [['CAR', 59.6, 81.2, '#CE1126'], ['VGK', 57, 77.8, '#B4975A'], ['UTA', 61.9, 75, '#71AFE5'], ['OTT', 46.5, 75, '#C52032'], ['COL', 55.9, 68.8, '#6F263D'], ['TOR', 43, 50, '#00205B'], ['NJD', 62, 50, '#CE1126'], ['CHI', 38, 37.5, '#CF0A2C'], ['VAN', 40, 28.6, '#00205B'], ['PHI', 33.6, 16.7, '#F74902'], ['LAK', 51.3, 20, '#A2AAAD'], ['BUF', 53.5, 56.3, '#003087']].map(function (r) { return { label: r[0], name: r[0], x: r[1], y: r[2], color: r[3] }; }),
  xName: 'Share of expected goals at 5-on-5 (%)', yName: 'Points won (% of possible)', refX: 50, refY: 'mean', xFmt: function (v) { return Math.round(v) + '%'; }, yFmt: function (v) { return Math.round(v) + '%'; } });
$('#sc-bc-band').innerHTML = QK.band(QK.sectionHead({ kicker: 'Who’s hot', title: 'QK.band + QK.hotRow', sub: 'The black power list with outlined ranks; long names drop to Barlow Condensed.' }) + QK.hotRow([
  { sport: 'hockey', kicker: 'Hockey', title: 'Most points', name: 'Connor McDavid', value: 18, expl: 'Points = goals + assists. Nine games in, so it is early.' },
  { sport: 'f1', kicker: 'Formula 1', title: 'Drivers’ points', name: 'Andrea Kimi Antonelli', value: 340, expl: '102 points clear with six races left.' },
  { sport: 'baseball', kicker: 'Baseball', title: 'Best season (WAR)', name: 'Pete Crow-Armstrong', value: 7.5, expl: 'WAR: wins added over a bench-level player.' },
  { sport: 'tennis', kicker: 'Tennis', title: 'Top rated (Elo)', name: 'J. Sinner', value: 2136, expl: 'Beat a stronger player, gain more.' }]));
$('#sc-bc-tape').innerHTML = QK.sectionHead({ kicker: 'Tale of the tape', title: 'QK.tape' }) + QK.tape({ left: { name: 'Nathan MacKinnon', sub: 'Colorado · 8 games', colour: '#6F263D' }, right: { name: 'Connor McDavid', sub: 'Edmonton · 7 games', colour: '#041E42', alt: '#FF4C00' },
  rows: [{ label: 'Points', a: 16, b: 18, pa: 99, pb: 100 }, { label: 'Points per 60', a: 5.74, b: 6.46, pa: 99, pb: 100, ta: '5.74', tb: '6.46' }, { label: 'Expected-goals share', a: 0.595, b: 0.698, pa: 89, pb: 97, ta: '59.5%', tb: '69.8%' }, { label: 'Isolated defence', a: -0.05, b: 0, pa: 21, pb: 48, ta: '−0.05', tb: '0.00' }] });
$('#sc-bc-meters').innerHTML = '<div class="qk-pgrp-h">QK.meter (20 LED segments, ▼ last season)</div>' + [[100, 92], [74, 80], [21, 35], [3, null]].map(function (x) { return '<div style="margin:14px 0">' + QK.meter(x[0], { prev: x[1] }) + '</div>'; }).join('') + QK.pctKey({ ring: true }) +
  '<p style="margin:16px 0 0">' + QK.outlineNum('29', { size: '96px' }) + ' <span class="qk-display" style="font-size:60px">BEBAS</span> <span class="qk-cond qk-long" style="font-size:28px">Barlow Condensed for long names</span></p>';
$('#sc-bc-explain').innerHTML = QK.explain('<b>What’s that number?</b> Our live chance updates with the score and the clock. Before the start it was 55% too: a one-point game late in the third is still close to a coin flip.');

/* ── v3 Matchday modules, in the v4 look ── */
$('#h-matchday').innerHTML = QK.sectionHead({ kicker: 'What to watch tonight', title: 'QK.watchGrid: game cards with a reason', sub: 'Our chance for each side (favourite in blue), the team-colour bar with a key, the score bug when live, and an italic one-line reason (g.why, else QK.whyLine). No market on cards.' });
$('#sc-md-watch').innerHTML = QK.watchGrid(GAMES.concat([{ sport: 'nfl', league: 'NFL', note: 'Week 7', status: 'pre', start: iso(26), away: { name: 'Saints', abbr: 'NO', colour: '#D3BC8D' }, home: { name: 'Giants', abbr: 'NYG', colour: '#0B2265' }, p_home: 0.52 }]), { limit: 6 });
$('#sc-md-hot').innerHTML = QK.sectionHead({ kicker: 'Who’s hot', title: 'QK.hotRow', sub: 'One name per sport and what the number means; a swipeable row on phones.' }) + QK.hotRow([
  { sport: 'hockey', title: 'Most points', name: 'Connor McDavid', value: 18, unit: 'pts', next: { name: 'Nathan MacKinnon', value: 16 }, expl: 'Points = goals + assists. Nine games in, so it is early.' },
  { sport: 'football', title: 'Most goals, MLS', name: 'Lionel Messi', value: 23, unit: 'goals', next: { name: 'Kevin Viveros', value: 21 }, expl: '23 goals from chances worth 19.4: finishing better than the average shooter.' },
  { sport: 'baseball', title: 'Best season (WAR)', name: 'Pete Crow-Armstrong', value: 7.5, unit: 'WAR', next: { name: 'Bobby Witt Jr.', value: 6.2 }, expl: 'WAR: wins added over a bench-level player. 5 or more is all-star level.' },
  { sport: 'f1', title: 'Drivers’ points', name: 'Andrea Kimi Antonelli', value: 340, unit: 'pts', next: { name: 'George Russell', value: 238 }, expl: '102 points clear with 6 races left.' },
  { sport: 'tennis', title: 'Top rated (Elo)', name: 'J. Sinner', value: 2136, unit: 'Elo', next: { name: 'C. Alcaraz', value: 2024 }, expl: 'Elo rating: beat a stronger player, gain more. 2,000 and up is rare air.' }]);
$('#sc-md-sotd').innerHTML = QK.statOfDay({ value: '+7.3', kicker: 'Stat of the day · Hockey', title: 'Ullmark has been a wall', text: 'Linus Ullmark (OTT) has saved 7.3 more goals than an average goalie would on the same shots this season.', note: '<b>Goals saved above expected</b> compares each shot faced with how often that kind of shot goes in.' });
$('#sc-md-new').innerHTML = QK.newHere();
$('#sc-md-sure').innerHTML = QK.sectionHead({ kicker: 'How sure are we?', title: 'QK.howSure: when we say 60%, does it happen 60% of the time?', sub: 'Fed from a site’s calibration.json through QK.calib.find; the chart is QKC.calibration.' }) + '<div id="sc-md-sure-body"></div>';
QK.howSure('#sc-md-sure-body', { league: 'NHL', span: '2009-10 to 2025-26', brier: 0.2396, bins: [
  { lo: 0.2, hi: 0.3, n: 30, mean_p: 0.2789, freq: 0.3 }, { lo: 0.3, hi: 0.4, n: 632, mean_p: 0.3693, freq: 0.3386 }, { lo: 0.4, hi: 0.5, n: 5201, mean_p: 0.4631, freq: 0.4336 },
  { lo: 0.5, hi: 0.6, n: 11276, mean_p: 0.549, freq: 0.5488 }, { lo: 0.6, hi: 0.7, n: 4337, mean_p: 0.6352, freq: 0.6569 }, { lo: 0.7, hi: 0.8, n: 429, mean_p: 0.7277, freq: 0.7972 }, { lo: 0.8, hi: 0.9, n: 5, mean_p: 0.8178, freq: 0.8 }] });
$('#sc-md-rail').innerHTML = QK.pctRail({ kicker: 'How they stack up', title: 'QK.pctRail: the Notebook slider rail', peer: 'NHL forwards (618 qualified)', sample: '8 GP · 167 min · 122 at 5v5', ringLabel: 'last season (80 games)', groups: [
  { label: 'Scoring', rows: [{ label: 'Points per 60', sub: 'Goals + assists for every hour on the ice.', pctl: 100, prev: 99, value: '5.74' }, { label: 'Individual xG per 60', sub: 'How good the player’s own shots are.', pctl: 94, prev: 90, value: '1.45' }] },
  { label: 'Play driving (5v5)', rows: [{ label: 'Shot-attempt share', sub: 'The team’s share of attempts with the player on.', pctl: 65, prev: 82, value: '52.3%' }, { label: 'Isolated defence', sub: 'The player’s own effect on chances against.', pctl: 21, prev: 33, value: '−0.05', early: true }] }] });
$('#sc-md-short').innerHTML = QK.shortVersion('MacKinnon has 16 points in 8 games, on pace for 168. In the top 1% of forwards for points per 60 and shot attempts per 60. The weak spot: isolated defence sits in the 21st percentile.');
$('#sc-md-preview').innerHTML = QK.previewCard({ sport: 'hockey', league: 'NHL', status: 'pre', start: iso(4), away: { name: 'Tampa Bay Lightning', abbr: 'TBL', colour: '#002868', record: '5–2–0', form: 'WWWLW' }, home: { name: 'Colorado Avalanche', abbr: 'COL', colour: '#6F263D', record: '5–2–1', form: 'WLWOW' }, p_home: 0.6 },
  { kicker: 'NHL · Ball Arena, Denver', nick: function (t) { return t.name.split(' ').slice(-1)[0]; }, noteExtra: 'About 1 in 4 (23%) go to overtime, and we expect about 6 goals in all.',
    factors: [{ label: 'Goals for per game', a: '3.0', b: '4.5', better: 'b' }, { label: 'Goals against per game', a: '2.7', b: '2.9', better: 'a' }, { label: 'Power play', a: '7.4%', b: '20.7%', better: 'b' }] });
$('#sc-md-misc').innerHTML = '<div class="qk-kicker">Small pieces</div><h3 style="margin:8px 0 14px">Score bug, note, aside, highlighter, verdicts</h3>' +
  '<div class="qk-row" style="gap:14px">' + QK.scorebug(GAMES[0]) + QK.scorebug(GAMES[0], { size: 'lg' }) + '</div>' +
  QK.note('<b>QK.note</b>: one or two friendly sentences on what a number means.') + '<div style="margin-top:12px">' + QK.aside('QK.aside: a one-line reason in italic Fraunces.') + '</div>' +
  '<p style="margin-top:12px">QK.mark puts the ' + QK.mark('sun highlighter') + ' under a phrase.</p>' +
  QK.verdicts([{ title: 'The volume shooter', who: 'MacKinnon', text: 'more 5-on-5 shots per hour than any regular (13.8).' }, { title: 'The playmaker', who: 'McDavid', text: '14 assists in 7 games.' }, { title: 'Due a goal or two', who: 'Kucherov', text: '1 goal on about 17 shots.' }]);

function head(id, kicker, title, sub) { $('#h-' + id).innerHTML = QK.sectionHead({ kicker: kicker, title: title, sub: sub }); }
head('identity', 'Identity', 'Colour and type', 'Blue (cobalt) means "ours"; volt is the highlighter and the tags, red-orange is live, team colours are up front. Sport accents mark identity only. The percentile scale runs cold to hot. Team colours are accents, contrast-checked.');
var SW = [['--signal', 'Ours (cobalt)', 'our forecast, rating, links'], ['--volt', 'Volt', 'kickers, highlighter, key numbers'], ['--live', 'Live', 'live games'], ['--coral', 'Red-orange', 'asides, a second series'], ['--sky', 'Cyan', 'a third series'], ['--bg', 'Page', 'near-black'], ['--s-1', 'Card', 'surface'], ['--s-cream', 'Cream card', 'New here, short version'], ['--c-market', 'Market', 'a quiet reference, never a headline'], ['--wp-a', 'Win prob A', 'fallback when kits clash'], ['--wp-b', 'Win prob B', 'fallback when kits clash'],
  ['--pc-0', 'Percentile 0', 'cold: worst in peers'], ['--pc-50', 'Percentile 50', 'average'], ['--pc-100', 'Percentile 100', 'hot: best in peers'], ['--live', 'Live', 'live status only'],
  ['--a-football', 'Football', 'sport mark'], ['--a-hockey', 'Hockey', 'sport mark'], ['--a-nfl', 'NFL', 'sport mark'], ['--a-baseball', 'Baseball', 'sport mark']];
$('#sc-swatches').innerHTML = SW.map(function (s) { return '<div class="sc-sw"><i style="--k:var(' + s[0] + ')"></i><div><b>' + esc(s[1]) + '</b><code>' + esc(s[0]) + '</code><div class="qk-muted">' + esc(s[2]) + '</div></div></div>'; }).join('');
$('#sc-chips').innerHTML = [3, 18, 35, 50, 64, 81, 97].map(QK.pctlChip).join('');
$('#sc-type').innerHTML = [
  ['Display d1 · Fraunces 650', '<span class="qk-display" style="font-size:var(--fs-d1);line-height:1">Every game, by the numbers.</span>', '--fs-d1'],
  ['Display d2 · page title', '<span class="qk-display" style="font-size:var(--fs-d2)">Connor McDavid</span>', '--fs-d2'],
  ['Display d3 · stat number', '<span class="qk-display" style="font-size:var(--fs-d3)">63.8% · 2.41 · +0.31</span>', '--fs-d3'],
  ['UI · DM Sans 16/1.55', '<span>Our chance comes from 20,000 simulated seasons. The market is shown as a reference.</span>', '--font-ui'],
  ['Numbers · DM Sans, tabular figures', '<span class="num">BOS 4  TOR 3  ·  xG 3.41–2.07  ·  23:54 TOI</span>', '--font-num']
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
  ['Explanations', ['xGF% 0.698 rel +0.311', '70% of the expected goals at 5v5 went the team’s way with this player on the ice'], ['Priced at -118', 'Our chance: 58%']]
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
