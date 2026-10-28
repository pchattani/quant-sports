/* The Quant Paddock — progression (round 6): the driver page's "Progression" tab (#/driver/<id>?view=progression) and
 * Compare progression (#/compare/progression/<a>/<b>[/<c>/<d>]?m=<metric>&x=season|age|year&y=value|pct).
 *
 * The Paddock adapter for the kit module assets/qk/progression.js (MIGRATION_V4.md "Progression"), laid out by
 * assets/app/qk-progview.js (QPV). Reads the career file's season rows (seasons[].dv / dp / pg: the drivers' deep set,
 * the race and qualifying driver ratings against the team-mate, race pace, head-to-heads, Elo, points and results;
 * percentiles against that season's peer group, the drivers with the season's floor of starts; oddsmarkets/f1/
 * analytics/drivers.py `progression`), data/progression_ref.json (each season's peers: the median and the middle half)
 * and the spec's labels (QK.spec). Lap-time metrics run from 1996; Elo, team-mate head-to-heads and points from 1950. */
(function (PD) {
'use strict';
if (!PD || !window.QPV) return;
var QK = window.QK, QPV = window.QPV, esc = PD.esc, isNum = PD.isNum;
var REF_P = null;
function refJson() { if (!REF_P) REF_P = PD.load('progression_ref.json'); return REF_P; }
var compareHref = QPV.hrefFor('#/compare/progression/');

/* the routes, ahead of compare/:kind/:a/:b */
['compare/progression', 'compare/progression/:a', 'compare/progression/:a/:b', 'compare/progression/:a/:b/:c', 'compare/progression/:a/:b/:c/:d'].forEach(function (p) {
  PD.ROUTES.unshift({ pattern: p, segs: p.split('/'), name: 'compare-progression', section: 'lab' });
});

function toP(c) {
  var keys = ((c.prog || {}).keys || {}).drivers || [];
  var cur = PD.currentSeason();
  var rows = (c.seasons || []).filter(function (r) { return isNum(r.year); }).sort(function (a, b) { return a.year - b.year; });
  return { id: String(c.driver), name: c.name, short: QK.surname(c.name || '') || c.name,
    seasons: rows.map(function (r, i) {
      var t = r.team;
      return { key: String(r.year), x: Number(r.year), label: String(r.year), age: QPV.ageAt(c.dob, r.year), cy: i + 1,
        team: t ? { abbr: PD.teamAbbr(t), name: PD.teamName(t), colour: PD.teamColourRaw(t) } : null, teams: (r.teams || []).length > 1 ? r.teams.map(PD.teamAbbr) : null,
        group: r.pg || null, n: r.races, nUnit: 'starts', small: !(r.dp && r.dp.length), values: QPV.zip(keys, r.dv), pct: QPV.zip(keys, r.dp),
        partial: Number(r.year) === cur };
    }) };
}
/* lap-fraction metrics are stored in percent already (-0.076 = 0.076% of a lap faster); the other % metrics are shares */
var PCT_OF_LAP = /^(driver_effect|quali_driver_effect|quali_pace|quali_gap_tm_pct|quali_gap_pole_pct)$/;
function fmtOf(k, unit) {
  if (PCT_OF_LAP.test(k)) return function (v) { return isNum(v) ? (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(3) + '%' : '—'; };
  if (/^(race_pace|race_pace_tm_delta)$/.test(k)) return function (v) { return isNum(v) ? (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(3) + ' s' : '—'; };
  return undefined;
}
var LABELS = { quali_gap_pole_pct: 'Qualifying gap to pole', laps_led_share: 'Share of laps led', top5_rate: 'Top-5 rate', finish_rate: 'Finish rate' };
var UNITS = { quali_gap_pole_pct: '% of lap', laps_led_share: '%', top5_rate: '%', finish_rate: '%' };
var DIRS = { quali_gap_pole_pct: 'lower' };
function metricsFor(keys, cat) { return QPV.metrics(keys, cat, { head: cat ? cat.headline('drivers') : [], fmt: fmtOf, labels: LABELS, units: UNITS, dirs: DIRS }); }
function mates(c) {
  var out = [];
  (c.teammates || []).slice().sort(function (a, b) { return b.year - a.year; }).forEach(function (t) {
    if (t.teammate && t.teammate !== c.driver && !out.some(function (x) { return x.id === t.teammate; })) out.push({ id: t.teammate, name: QK.surname(PD.driverName(t.teammate)), year: t.year });
  });
  return out;
}

function tab(el, params) {
  var id = String(params.id || '');
  el.innerHTML = QK.skeleton('card', 1) + QK.skeleton('chart', 1);
  return Promise.all([PD.load('drivers/' + id + '.json'), refJson(), QK.spec.load('f1')]).then(function (res) {
    if (!PD.alive(el)) return;
    var c = PD.ok(res[0]) || (res[0] && res[0].seasons) ? res[0] : null, cat = res[2];
    if (!c || !c.seasons) { el.innerHTML = QK.empty('No career file for this driver', 'Try the drivers list.'); return; }
    document.title = c.name + ' · Progression · The Quant Paddock';
    var P = toP(c), peer = 'drivers';
    var ms = metricsFor(((c.prog || {}).keys || {}).drivers || [], cat);
    var head = (cat ? cat.headline('drivers') : []).map(function (k) { return ms.filter(function (m) { return m.id === k; })[0]; }).filter(Boolean);
    var R = QK.prog.ref(res[1]);
    var base = PD.driverHref(id);
    var lastS = P.seasons[P.seasons.length - 1] || {};
    QPV.tab(el, { P: P, metrics: ms, head: head, cat: cat, peer: peer, nUnit: 'starts',
      tabs: [['overview', 'Overview', base], ['progression', 'Progression', base + '?view=progression']],
      kicker: 'Progression · F1' + (lastS.team ? ' · ' + lastS.team.name : ''), title: esc(c.name),
      sub: P.seasons.length + ' season' + (P.seasons.length === 1 ? '' : 's') + ' in the data, each against that season’s regular drivers (the season’s floor of starts). The lap-time numbers (driver ratings, race pace) run from 1996; Elo, team-mate head-to-heads and points from 1950.',
      key: ms.filter(function (m) { return m.id === 'elo_teammate'; })[0] || null,
      ref: function (S, k) { return S.group ? R(S.group, S.key, k) : null; },
      note: 'Team-mate numbers measure the driver against one car’s other driver: they carry over at about 0.5 for a driver who stays and much less after a move.',
      compare: { sims: mates(c), href: compareHref } });
  });
}

function compare(el, params) {
  var q = params.query || {};
  var ids = [params.a, params.b, params.c, params.d].filter(Boolean).map(String);
  ids = ids.filter(function (x, i) { return ids.indexOf(x) === i; }).slice(0, 4);
  el.innerHTML = QK.skeleton('chart', 1);
  var fill = Promise.resolve(ids.length ? ids : ['max_verstappen', 'hamilton']);
  if (ids.length === 1) fill = PD.load('drivers/' + ids[0] + '.json').then(function (c) { var m = c ? mates(c) : []; return ids.concat(m.slice(0, 1).map(function (x) { return x.id; })); });
  return fill.then(function (list) {
    return Promise.all([Promise.all(list.map(function (x) { return PD.load('drivers/' + x + '.json'); })), refJson(), QK.spec.load('f1'), PD.load('elo.json')]).then(function (res) {
      if (!PD.alive(el)) return;
      var cs = res[0].filter(function (c) { return c && c.seasons; }), cat = res[2];
      var Ps = cs.map(toP);
      var keys = [];
      cs.forEach(function (c) { ((((c.prog || {}).keys || {}).drivers) || []).forEach(function (k) { if (keys.indexOf(k) < 0) keys.push(k); }); });
      var ms = metricsFor(keys, cat), hd = cat ? cat.headline('drivers') : [];
      var R = QK.prog.ref(res[1]);
      var sugg = [];
      cs.forEach(function (c) { mates(c).slice(0, 3).forEach(function (m) {
        if (Ps.length < 4 && !Ps.some(function (P) { return P.id === m.id; }) && !sugg.some(function (s) { return s.id === m.id; })) sugg.push({ id: m.id, name: PD.driverName(m.id), sub: 'Team-mate of ' + c.name + ' (' + m.year + ')', href: compareHref(Ps.map(function (P) { return P.id; }).concat([m.id]), '') });
      }); });
      var seen = {}, names = [];
      (((res[3] || {}).all_time) || []).forEach(function (r) { if (r.driver && !seen[r.driver]) { seen[r.driver] = 1; names.push([r.driver, r.name + ((r.years || []).length ? ' (' + r.years[0] + '–' + r.years[1] + ')' : '')]); } });
      var idx = (PD.index() || {}).drivers || {};
      Object.keys(idx).forEach(function (k) { if (!seen[k]) { seen[k] = 1; names.push([k, (idx[k].name || PD.driverName(k)) + ' (current)']); } });
      names.sort(function (a, b) { return a[1].localeCompare(b[1]); });
      var first = hd.filter(function (k) { return ms.some(function (m) { return m.id === k; }); })[0];
      document.title = 'Compare progression · The Quant Paddock';
      QPV.compare(el, { players: Ps, metrics: ms, cat: cat, metric: q.m || first || (ms[0] || {}).id, x: q.x, y: q.y,
        ref: function (P, S, k) { return S.group ? R(S.group, S.key, k) : null; }, peerName: function () { return 'drivers'; }, suggest: sugg,
        cyNote: 'Career year counts seasons with a start in our data (from 1950).', kicker: 'Compare progression · F1',
        actions: '<a class="qk-btn" href="#/compare/drivers' + (Ps[0] ? '/' + encodeURIComponent(Ps[0].id) : '') + (Ps[1] ? '/' + encodeURIComponent(Ps[1].id) : '') + '">Compare this season</a>',
        href: compareHref, names: names });
    });
  });
}

PD.route('compare-progression', compare);
PD.progression = { tab: tab, compare: compare, toP: toP, compareHref: compareHref };
})(window.PD);
