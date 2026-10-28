/* Kit showcase: the progression module (progression.js, round 6) on sample data. Not shipped to any site. ES5. */
(function () {
'use strict';
var $ = QK.$;
var TEAMS = { EDM: { abbr: 'EDM', name: 'Edmonton Oilers', colour: '#041E42' }, NYR: { abbr: 'NYR', name: 'New York Rangers', colour: '#0038A8' }, COL: { abbr: 'COL', name: 'Colorado Avalanche', colour: '#6F263D' } };
var M = [
  { id: 'gar_60', label: 'Rink value per 60', unit: 'GAR/60', dir: 'higher', head: true, ours: { name: 'Rink value (GAR / WAR)' }, tip: 'Goals above a replacement-level player per 60 minutes.' },
  { id: 'p60', label: 'Points per 60', unit: 'per 60', dir: 'higher', head: true, tip: 'Goals and assists per 60 minutes, all situations.' },
  { id: 'adj_xgf_pct', label: 'Expected-goals share', unit: '% share', dir: 'higher', head: true, ours: { name: 'Expected goals' }, tip: 'The team’s share of 5v5 expected goals with the player on the ice.' },
  { id: 'rapm_def', label: 'Isolated defence (RAPM)', unit: 'xGA/60', dir: 'higher', head: true, ours: { name: 'RAPM' } },
  { id: 'toi_gp', label: 'Ice time per game', unit: 'min', dir: 'neutral' }
];
function season(y, team, age, gp, v, p, extra) {
  return Object.assign({ key: y + '' + (y + 1), x: y, label: y + '-' + String(y + 1).slice(2), age: age, team: TEAMS[team], group: 'forwards', n: gp, nMax: 82, nUnit: 'games', values: v, pct: p }, extra || {});
}
var A = { id: 'a', name: 'Sample Centre', short: 'Centre', seasons: [
  season(2015, 'EDM', 19.0, 45, { gar_60: 0.62, p60: 3.39, adj_xgf_pct: 0.56, rapm_def: -0.01, toi_gp: 18.9 }, { gar_60: 81, p60: 96, adj_xgf_pct: 78, rapm_def: 47, toi_gp: 60 }, { short: { kind: 'injury', tag: 'Injury', text: 'Missed 37 games (broken collarbone)' } }),
  season(2016, 'EDM', 20.1, 82, { gar_60: 0.88, p60: 3.46, adj_xgf_pct: 0.56, rapm_def: 0.02, toi_gp: 21.1 }, { gar_60: 93, p60: 97, adj_xgf_pct: 80, rapm_def: 55, toi_gp: 88 }),
  season(2017, 'EDM', 21.1, 82, { gar_60: 0.81, p60: 3.29, adj_xgf_pct: 0.53, rapm_def: -0.06, toi_gp: 21.3 }, { gar_60: 90, p60: 96, adj_xgf_pct: 66, rapm_def: 31, toi_gp: 90 }),
  season(2018, 'NYR', 22.1, 78, { gar_60: 0.97, p60: 3.69, adj_xgf_pct: 0.55, rapm_def: 0.04, toi_gp: 22.5 }, { gar_60: 96, p60: 99, adj_xgf_pct: 74, rapm_def: 62, toi_gp: 95 }),
  season(2019, 'NYR', 23.1, 64, { gar_60: 1.12, p60: 4.11, adj_xgf_pct: 0.58, rapm_def: 0.06, toi_gp: 22.6 }, { gar_60: 99, p60: 100, adj_xgf_pct: 86, rapm_def: 70, toi_gp: 95 }),
  season(2020, 'NYR', 24.1, 18, { gar_60: 1.3, p60: 4.6, adj_xgf_pct: 0.6, rapm_def: 0.1, toi_gp: 22 }, {}, { small: true }),
  season(2021, 'COL', 25.2, 80, { gar_60: 1.05, p60: 3.9, adj_xgf_pct: 0.6, rapm_def: 0.12, toi_gp: 21.9 }, { gar_60: 98, p60: 99, adj_xgf_pct: 91, rapm_def: 85, toi_gp: 93 })
] };
var B = { id: 'b', name: 'Sample Winger', short: 'Winger', seasons: [
  season(2013, 'COL', 18.5, 82, { gar_60: 0.31, p60: 2.2, adj_xgf_pct: 0.49, rapm_def: -0.02, toi_gp: 16 }, { gar_60: 55, p60: 70, adj_xgf_pct: 40, rapm_def: 45, toi_gp: 40 }),
  season(2014, 'COL', 19.5, 82, { gar_60: 0.45, p60: 2.5, adj_xgf_pct: 0.5, rapm_def: 0.0, toi_gp: 17 }, { gar_60: 68, p60: 80, adj_xgf_pct: 48, rapm_def: 50, toi_gp: 52 }),
  season(2015, 'COL', 20.5, 72, { gar_60: 0.6, p60: 2.9, adj_xgf_pct: 0.53, rapm_def: 0.03, toi_gp: 19 }, { gar_60: 80, p60: 88, adj_xgf_pct: 62, rapm_def: 58, toi_gp: 70 }),
  season(2016, 'COL', 21.5, 82, { gar_60: 0.9, p60: 3.3, adj_xgf_pct: 0.55, rapm_def: 0.05, toi_gp: 20 }, { gar_60: 94, p60: 96, adj_xgf_pct: 72, rapm_def: 66, toi_gp: 80 })
] };
var REF = function (S, id) {
  var base = { gar_60: [0.05, 0.2, 0.35, 0.52, 0.7], p60: [1.0, 1.4, 1.8, 2.3, 2.8], adj_xgf_pct: [0.44, 0.47, 0.5, 0.53, 0.56], rapm_def: [-0.12, -0.05, 0, 0.05, 0.1], toi_gp: [12, 14, 16, 18, 20] }[id];
  return base ? { q: base, n: 380 } : null;
};
$('#h-progression').innerHTML = QK.sectionHead({ kicker: 'Progression', title: 'Season by season, against the peers', sub: 'progression.js: QK.careerArc, QKC.progression, QK.progressionGrid, QK.progressionDeltas and QK.compareProgression (sample data).' });
var arc = QK.careerArc({ player: A, metrics: M.filter(function (m) { return m.head; }), all: M, key: M[0], peerName: 'forwards' });
$('#sc-pg-arc').innerHTML = arc.html + QK.explain(arc.text, { title: 'The short version.' });
QKC.progression('#sc-pg-chart', { player: A, metrics: [M[0]], ref: REF, peerName: 'forwards' });
$('#sc-pg-key').innerHTML = QK.progressionKey({ name: 'Centre', peerName: 'forwards', pctLine: true });
$('#sc-pg-grid').innerHTML = QK.progressionGrid({ player: A, metrics: M, groups: [{ label: 'Value and impact', ids: ['gar_60', 'adj_xgf_pct', 'rapm_def'] }, { label: 'Scoring and role', ids: ['p60', 'toi_gp'] }], peerName: 'forwards' });
$('#sc-pg-deltas').innerHTML = QK.progressionDeltas({ player: A, metrics: M, peerName: 'forwards' });
QK.compareProgression('#sc-pg-cmp', { players: [A, B], metrics: M, metric: 'gar_60', x: 'age', ref: function (P, S, id) { return REF(S, id); }, peerName: function () { return 'forwards'; }, suggest: [{ name: 'Another forward', href: '#progression' }] });
})();
