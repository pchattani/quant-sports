/* Kit showcase: the Scouting Room and team-comparison kit (scout.js, round 8) on sample data. Not shipped to any site. ES5. */
(function () {
'use strict';
var $ = QK.$, esc = QK.esc;
$('#h-scouting').innerHTML = QK.sectionHead({ kicker: 'Round 8', title: 'The Scouting Room and the Teams page', sub: 'QK.board, QK.heatGrid, QK.powerBars, QK.leaderCard with QKC.strip, QK.profile (in QK.drawer), QK.trayCompare (in QK.tray), QK.strengths and QK.scoutBar. Sample data; the Bullpen pilot is the reference (bp-scout.js, bp-teams.js).' });

var P = [['Ava Ortiz', 'NYR', '#0038A8', 'C', 612, 26, 0.391, 0.155, 0.081, 6.1], ['Ben Kato', 'EDM', '#041E42', 'C', 590, 29, 0.352, 0.121, 0.064, 4.2],
  ['Cal Rios', 'COL', '#6F263D', 'LW', 544, 24, 0.371, 0.142, 0.092, 5.0], ['Dev Shah', 'NYR', '#0038A8', 'RW', 488, 31, 0.318, 0.097, 0.101, 2.1],
  ['Eli Moss', 'EDM', '#041E42', 'D', 630, 27, 0.299, 0.088, 0.071, 3.3], ['Fin Lowe', 'COL', '#6F263D', 'D', 401, 22, 0.335, 0.109, 0.118, 1.4],
  ['Gus Hale', 'NYR', '#0038A8', 'C', 350, 33, 0.287, 0.071, 0.122, 0.2], ['Hal Pike', 'EDM', '#041E42', 'LW', 455, 28, 0.344, 0.131, 0.085, 3.0]];
var rows = P.map(function (r, i) { return { id: 'p' + i, name: r[0], sub: r[3] + ' · ' + r[1] + ' · age ' + r[5], mark: { abbr: r[1], colour: r[2] }, href: '#', v: { xw: r[6], iso: r[7], k: r[8], war: r[9] }, n: r[4], age: r[5] }; });
var M = { xw: { label: 'xwOBA+', tip: 'Expected wOBA from the contact.', ours: { name: 'Expected contact' }, fmt: function (v) { return v.toFixed(3).replace(/^0/, ''); } },
  iso: { label: 'ISO', tip: 'Extra bases per at-bat.', fmt: function (v) { return v.toFixed(3).replace(/^0/, ''); } },
  k: { label: 'K%', tip: 'Strikeouts per plate appearance.', lower: true, fmt: function (v) { return (v * 100).toFixed(1) + '%'; } },
  war: { label: 'WAR/600', tip: 'Value per 600 plate appearances.', ours: { name: 'Bullpen WAR' }, fmt: function (v) { return v.toFixed(1); } } };
var pinned = {};
QK.board($('#sc-scout-board'), { id: 'sc-x-bd', noun: 'players', nameLabel: 'Player', sets: [{ key: 'view', label: 'Position view', groups: [{ label: 'Hitting', ids: ['xw', 'iso', 'k'] }, { label: 'Value', ids: ['war'] }] }, { key: 'pow', label: 'Power', groups: [{ label: 'Power', ids: ['iso'] }] }],
  meta: function (id) { return M[id]; }, rows: rows, val: function (r, id) { return r.v[id]; }, sort: { key: 'war', dir: 'desc' }, page: 5, csv: 'showcase-board.csv',
  lead: [{ key: 'n', label: 'PA', fmt: function (r) { return String(r.n); }, val: function (r) { return r.n; } }, { key: 'age', label: 'Age', fmt: function (r) { return String(r.age); }, val: function (r) { return r.age; } }],
  pin: { has: function (id) { return !!pinned[id]; }, toggle: function (r) { pinned[r.id] = !pinned[r.id]; } }, note: 'Cells on the percentile scale within the rows; K% is lower-is-better, so its colours flip.' });

var TM = [['NYR', 'New York', '#0038A8', 1.21, 0.62, 0.41, 0.18, '103–59', 'WWLWWWLWWW'], ['EDM', 'Edmonton', '#041E42', 0.55, 0.31, 0.12, 0.12, '92–70', 'LWWLWLWWLW'],
  ['COL', 'Colorado', '#6F263D', -0.12, 0.25, -0.31, -0.06, '79–83', 'LLWLWWLLWL'], ['BOS', 'Boston', '#FFB81C', -0.71, -0.42, -0.18, -0.11, '68–94', 'LLLWLLWLLL']];
$('#sc-scout-power').innerHTML = QK.powerBars(TM.map(function (t, i) {
  return { rank: i + 1, name: t[1], abbr: t[0], colour: t[2], href: '#', sub: t[7], value: t[3], text: QK.fmt.signed(t[3], 2), parts: { off: t[4], pit: t[5], def: t[6] },
    cells: [{ label: 'Run diff', text: QK.fmt.signed(t[3] * 160, 0) }], form: t[8], chances: [{ label: 'Postseason', p: 0.9 - i * 0.28 }] };
}), { valueLabel: 'Our rating', unit: 'runs per game', parts: [{ key: 'off', label: 'Offence', color: 'var(--c-2)' }, { key: 'pit', label: 'Pitching', color: 'var(--c-3)' }, { key: 'def', label: 'Defence', color: 'var(--c-5)' }] });

QK.heatGrid($('#sc-scout-grid'), { id: 'sc-x-hg', noun: 'clubs', nameLabel: 'Club', sets: [{ key: 'o', label: 'Overview', groups: [{ label: 'Ratings', ids: ['r', 'off', 'pit', 'def'] }] }],
  meta: function (id) { return { label: { r: 'Rating', off: 'Offence', pit: 'Pitching', def: 'Defence' }[id], fmt: function (v) { return QK.fmt.signed(v, 2); } }; },
  rows: TM.map(function (t) { return { id: t[0], name: t[1], sub: t[7], mark: { abbr: t[0], colour: t[2] }, href: '#', v: { r: t[3], off: t[4], pit: t[5], def: t[6] } }; }), val: function (r, id) { return r.v[id]; }, sort: { key: 'r', dir: 'desc' }, csv: 'showcase-grid.csv' });

var srt = rows.slice().sort(function (a, b) { return b.v.xw - a.v.xw; });
$('#sc-scout-lc').innerHTML = QK.leaderCard({ title: 'xwOBA+', ours: { name: 'Expected contact' }, tip: M.xw.tip, count: rows.length + ' players', stripId: 'sc-scout-strip',
  top: srt.slice(0, 3).map(function (r, i) { return { id: r.id, name: r.name, sub: r.sub, href: '#', text: M.xw.fmt(r.v.xw), w: 100 - i * 12, pctl: 100 - i * 12, mark: r.mark }; }),
  bottom: srt.slice(-2).map(function (r, i) { return { id: r.id, rank: srt.length - 1 + i, name: r.name, sub: r.sub, href: '#', text: M.xw.fmt(r.v.xw), w: 12 - i * 6, pctl: 12 - i * 6, mark: r.mark }; }) });
QKC.strip($('#sc-scout-strip'), { values: rows.map(function (r, i) { return { v: r.v.xw, name: r.name, id: r.id, hl: i === 0 }; }), xName: 'xwOBA+', fmt: M.xw.fmt });

$('#sc-scout-sw').innerHTML = QK.strengths({ name: 'New York', abbr: 'NYR', colour: '#0038A8', href: '#', sub: '103–59 · rating +1.21', best: [{ label: 'Staff Stuff+', pctl: 100, text: '108' }, { label: 'Lineup barrel%', pctl: 97, text: '9.6%' }, { label: 'OBP', pctl: 93, text: '.341' }],
  worst: [{ label: 'Framing runs', pctl: 7, text: '-6.3' }, { label: 'Lineup K%', pctl: 14, text: '24.7%' }, { label: 'Bullpen RA9', pctl: 21, text: '4.59' }] });

$('#sc-scout-pf').innerHTML = QK.profile({ kicker: 'Catcher · New York', name: 'Ava Ortiz', sub: 'Age 26 · Bats R · 612 PA · 2026', team: { abbr: 'NYR', colour: '#0038A8' },
  stats: [{ label: 'WAR/600', value: '6.1', pctl: 99 }, { label: 'xwOBA+', value: '.391', pctl: 97 }, { label: 'PA', value: '612' }], peer: 'catchers with 200+ PA',
  groups: [{ label: 'Catching', rows: [{ label: 'Framing', pctl: 88, value: '+1.4%' }, { label: 'Arm strength', pctl: 61, value: '82.0' }] }, { label: 'Hitting', rows: [{ label: 'xwOBA+', pctl: 97, value: '.391' }, { label: 'K%', pctl: 72, value: '18.1%' }] }],
  similar: { label: 'Most like Ortiz', items: [{ name: 'Cal Rios', href: '#' }, { name: 'Ben Kato', href: '#' }] }, links: [{ label: 'Full player page', href: '#' }, { label: 'Progression', href: '#' }] }) +
  '<p style="margin:12px 18px 0"><button type="button" class="qk-btn sm primary" id="sc-scout-open">Open it in the drawer</button></p>';
$('#sc-scout-open').addEventListener('click', function () { QK.drawer.open({ html: $('#sc-scout-pf .qk-pf').outerHTML, label: 'Sample profile' }); });

$('#sc-scout-tc').innerHTML = QK.trayCompare({ entities: rows.slice(0, 3).map(function (r) { return { name: r.name, short: r.name.split(' ')[1], sub: r.sub, colour: r.mark.colour, href: '#' }; }),
  groups: [{ label: 'Hitting', rows: ['xw', 'iso', 'k'].map(function (id) { return { label: M[id].label, ours: M[id].ours || null, cells: rows.slice(0, 3).map(function (r, i) { return { text: M[id].fmt(r.v[id]), pctl: [94, 71, 82][i] - (id === 'k' ? 20 : 0) }; }) }; }) }],
  note: 'Each player against their own peers; the volt underline marks the best on each row.' });
$('#sc-scout-bar').innerHTML = QK.scoutBar([{ label: 'Season', html: '<select class="qk-select"><option>2026</option></select>' }, { label: 'Team', html: '<select class="qk-select"><option>All teams</option></select>' },
  { label: 'Search', html: '<input class="qk-input" type="search" placeholder="Player or team…">', cls: 'grow' }]);
$('#sc-scout-nav').textContent = JSON.stringify(QK.sections('baseball', { scout: true }).map(function (s) { return s.label; }));
})();
