/* The Quant Paddock — Design System 2.0 helpers (PD.v2), the one place the comparison metric sets live.
 *
 *   DRIVER_SET / TEAM_SET          headline metrics by group, after docs/_design/metrics/f1.json (the metrics
 *                                  agent's spec): stable year to year and predictive; MORE_DRIVER / MORE_TEAM the
 *                                  secondary sets for the compare page
 *   floors(season, kind)           the peer group's sample floor (drivers: starts; constructors: rounds entered)
 *   peer(cat, kind, season)        the qualifying peer group and every metric's percentile within it, computed here
 *                                  from the payload values with the builders' formula (the payload pct ranks every
 *                                  entrant, one-race stand-ins included)
 *   pctGroups(...)  pctCard(...)   Savant-style percentile card rows, peer group and sample always named
 *   distribution(el, ...)          where a driver or team sits in the peer group, with the median marked
 *   pointsForecast(el, season, kind, n)   538-style points race: points so far, then our projection to the last round
 *   rangeChart(el, season, kind, n)        the season-end points range (5th to 95th percentile of the simulation)
 *
 * Older-browser rule: no optional chaining, no nullish coalescing. */
(function (PD) {
'use strict';

var esc = PD.esc, isNum = PD.isNum;
var V = PD.v2 = {};

/* ── metric sets (f1.json "headline" then "secondary"; m50 = the sample where a metric's split-half reliability
 * reaches 0.5: below it the percentile is drawn as early) ─────────────────────────────────────────────── */
V.DRIVER_SET = [
  ['Against the team-mate (the car taken out)', ['driver_effect', 'quali_driver_effect', 'race_h2h', 'team_points_share', 'elo_teammate']],
  ['Against the field', ['race_pace', 'points_per_race', 'lap1_gain']]
];
V.MORE_DRIVER = [
  ['Qualifying', ['quali_h2h', 'quali_gap_tm_pct', 'quali_pace', 'avg_grid', 'q3_rate']],
  ['Race', ['race_pace_tm_delta', 'race_pace_h2h', 'avg_finish', 'podium_rate', 'win_rate', 'points_rate', 'elo', 'pos_gained', 'overtakes_made', 'net_overtakes', 'consistency', 'tyre_mgmt', 'points_v_expected']],
  ['Speed and reliability', ['avg_fastest_rank', 'sector_rank', 'corner_speed_delta', 'dnf_rate', 'dnf_driver', 'dnf_mech']]
];
V.TEAM_SET = [
  ['Car and results', ['car_race_pace', 'points_per_race', 'dnf_rate']],
  ['Pit crew and strategy', ['pit_lane_v_field', 'pit_under_2500', 'strategy_gain']]
];
V.MORE_TEAM = [
  ['Car', ['car_quali_pace', 'car_pace_latest', 'car_pace_trend', 'corner_speed', 'top_speed', 'tyre_mgmt']],
  ['Results', ['avg_best_finish', 'avg_best_grid', 'both_points_rate', 'wins', 'podiums', 'lead_driver_share', 'car_share']],
  ['Pit crew and reliability', ['pit_stop_ms', 'pit_best_ms', 'dnf_mech']]
];
/* Display names and plain-words explanations for the headline metrics (f1.json display / explanation). */
V.NAMES = {
  driver_effect: ['Race pace v team-mate', 'His own share of race pace once the car is taken out: how much faster or slower than his team-mate per lap. Lower is faster.'],
  quali_driver_effect: ['Qualifying pace v team-mate', 'The same in qualifying: one-lap pace against the team-mate, % of a lap. Lower is faster.'],
  race_h2h: ['Race head-to-head v team-mate', 'Share of races he finished ahead of his team-mate.'],
  team_points_share: ['Share of team points v team-mate', 'His share of the points the car scored.'],
  elo_teammate: ['Elo v team-mates', 'Elo rating from head-to-heads with team-mates only.'],
  race_pace: ['Race pace v field', 'Race pace against the field, seconds a lap (driver and car together). Lower is faster.'],
  points_per_race: ['Points per race', 'Championship points per start.'],
  lap1_gain: ['Lap-1 gain', 'Places gained on the opening lap, per start.'],
  car_race_pace: ['Car race pace', 'The car’s share of race pace against the field, % of a lap. Lower is faster.'],
  dnf_rate: ['DNF rate', 'Share of starts that ended in a retirement.'],
  pit_lane_v_field: ['Pit-lane time v field', 'Time in the pit lane against the field’s median, milliseconds. Lower is better.'],
  pit_under_2500: ['Stops under 2.5 s', 'Share of stationary times under 2.5 seconds.'],
  strategy_gain: ['Places gained through stops', 'Places gained or lost across the pit-stop phases, per race.']
};
V.M50 = { driver_effect: 4.9, quali_driver_effect: 4.4, race_h2h: 15, team_points_share: 12.1, race_pace: 0.5, points_per_race: 1, lap1_gain: 20.2,
  quali_h2h: 4.9, quali_gap_tm_pct: 4.1, race_pace_tm_delta: 5.3, race_pace_h2h: 6.7, quali_pace: 0.6, avg_grid: 0.6, avg_finish: 1, podium_rate: 1.5, win_rate: 2.5,
  points_rate: 1.8, q3_rate: 0.9, pos_gained: 12.8, dnf_rate: 29.7, dnf_driver: 51.1, dnf_mech: 46.7, consistency: 14.2, avg_fastest_rank: 1, sector_rank: 0.6,
  corner_speed_delta: 3.7, overtakes_made: 39, net_overtakes: 10.6, tyre_mgmt: 20.3, points_v_expected: 14.3 };
V.M50_TEAM = { car_race_pace: 0.3, points_per_race: 0.5, dnf_rate: 16.9, pit_lane_v_field: 2.7, pit_under_2500: 7, strategy_gain: 3.6, car_quali_pace: 0.4, car_pace_latest: 0.3,
  car_pace_trend: 19.2, avg_best_finish: 0.5, avg_best_grid: 0.3, both_points_rate: 2, wins: 1.3, podiums: 0.6, pit_stop_ms: 46.7, pit_best_ms: 2, dnf_mech: 17.8,
  corner_speed: 3.1, top_speed: 57.3, tyre_mgmt: 21.4, lead_driver_share: 29.3 };

V.label = function (meta, k) { return (V.NAMES[k] || [])[0] || ((meta || {})[k] || {}).label || PD.titleCase(k); };
V.tip = function (meta, k) { return (V.NAMES[k] || [])[1] || ((meta || {})[k] || {}).desc || ''; };
V.metaMap = function (cat) { var m = {}; ((cat && cat.metrics) || []).forEach(function (x) { if (x && x.key) m[x.key] = x; }); return m; };
V.fmt = function (meta, k, v) {
  var m = (meta || {})[k] || {};
  if (!isNum(v)) return '—';
  if (m.fmt === 'prob') return PD.pct(v, 0);
  return PD.fmtVal(v, m.fmt);
};

/* ── peer groups and percentiles ───────────────────────────────────────────────────────────────────────── */
function roundsDone(season) { return season && isNum(season.rounds_done) ? season.rounds_done : null; }
/* drivers: starts, max(3, min(8, ceil(0.35 x rounds completed))) in a season still running, 8 once it is over;
   constructors: entered at least half the completed rounds. */
V.floors = function (season, kind) {
  var done = roundsDone(season), fin = !season || season.finished || !season.championship;
  if (kind === 'teams') return { n: done ? Math.ceil(done / 2) : 1, unit: 'rounds entered' };
  return { n: fin || !done ? 8 : Math.max(3, Math.min(8, Math.ceil(0.35 * done))), unit: 'starts' };
};
/* pct_i = 100 * (W_i + T_i / 2) / (n - 1): W the entries strictly worse, T the others tied (oddsmarkets/f1/analytics). */
function pctOf(vals, lower) {
  var ks = Object.keys(vals).filter(function (k) { return isNum(vals[k]); });
  var n = ks.length, out = {};
  if (!n) return out;
  if (n === 1) { out[ks[0]] = 50; return out; }
  ks.forEach(function (k) {
    var v = vals[k], worse = 0, tie = -1;
    ks.forEach(function (j) { var x = vals[j]; if (x === v) tie++; else if (lower ? x > v : x < v) worse++; });
    out[k] = Math.round(100 * (worse + 0.5 * tie) / (n - 1));
  });
  return out;
}
V.pctOf = pctOf;
/* The peer group of a catalogue (drivers.json: drivers; teams.json: teams) and every metric's percentile in it.
   Returns { ids, n, floor, unit, label, sample(id), pct: { id: { key: pctl } }, rows }. */
V.peer = function (cat, kind, season) {
  var rows = (cat && (kind === 'teams' ? cat.teams : cat.drivers)) || {};
  var meta = V.metaMap(cat), f = V.floors(season, kind);
  var size = function (id) { var r = rows[id] || {}; return kind === 'teams' ? ((r.log || []).length) : (isNum(r.races) ? r.races : 0); };
  var ids = Object.keys(rows).filter(function (id) { return size(id) >= f.n; });
  var pct = {};
  ids.forEach(function (id) { pct[id] = {}; });
  Object.keys(meta).forEach(function (k) {
    var vals = {};
    ids.forEach(function (id) { vals[id] = ((rows[id] || {}).values || {})[k]; });
    var p = pctOf(vals, !!meta[k].lower);
    Object.keys(p).forEach(function (id) { pct[id][k] = p[id]; });
  });
  var y = (cat && cat.year) || (season && season.year) || '';
  return {
    ids: ids, n: ids.length, floor: f.n, unit: f.unit, rows: rows, meta: meta, pct: pct, size: size, kind: kind,
    label: (kind === 'teams' ? 'F1 constructors' : 'F1 drivers') + ', ' + f.n + '+ ' + f.unit,
    sample: function (id) {
      var s = size(id);
      return s + ' ' + (kind === 'teams' ? 'rounds' : (s === 1 ? 'start' : 'starts')) + ' in ' + y + ' · ' + ids.length + ' ' + (kind === 'teams' ? 'constructors' : 'drivers') + ' reach the floor of ' + f.n;
    },
    qualified: function (id) { return ids.indexOf(id) >= 0; }
  };
};
/* Percentile-card groups for one entry. Out of the peer group (short of the floor): no percentiles. */
V.pctGroups = function (P, id, sets) {
  var row = P.rows[id] || {}, pc = P.pct[id];
  if (!pc) return [];
  var m50 = P.kind === 'teams' ? V.M50_TEAM : V.M50;
  return (sets || []).map(function (g) {
    return { label: g[0], rows: g[1].map(function (k) {
      if (!isNum(pc[k])) return null;
      return { label: V.label(P.meta, k), pctl: pc[k], value: V.fmt(P.meta, k, (row.values || {})[k]), tip: V.tip(P.meta, k), early: isNum(m50[k]) && P.size(id) < m50[k] };
    }).filter(Boolean) };
  });
};
V.pctCard = function (P, id, sets, o) {
  o = o || {};
  var q = P.qualified(id);
  return QK.pctCard({ title: o.title || 'Percentile rankings', peer: P.label, sample: P.sample(id), groups: q ? V.pctGroups(P, id, sets) : [], right: o.right, foot: o.foot,
    emptyTitle: 'Short of the sample floor', emptyText: q ? 'No headline metric has a value yet.' : 'Percentiles appear once ' + (P.kind === 'teams' ? 'the team reaches ' : 'he reaches ') + P.floor + ' ' + P.unit + ' this season.' });
};
/* The peer distribution of one metric, entries marked (first in the signal colour), the median dashed. */
V.distribution = function (el, P, key, marks) {
  var vals = P.ids.map(function (id) { return ((P.rows[id] || {}).values || {})[key]; }).filter(isNum).sort(function (a, b) { return a - b; });
  var node = typeof el === 'string' ? document.querySelector(el) : el;
  if (!node) return;
  if (vals.length < 5) { node.innerHTML = PD.muted('Too few ' + (P.kind === 'teams' ? 'constructors' : 'drivers') + ' at the floor yet.'); return; }
  var m = P.meta[key] || {};
  var med = vals.length % 2 ? vals[(vals.length - 1) / 2] : (vals[vals.length / 2 - 1] + vals[vals.length / 2]) / 2;
  var f = function (v) { return V.fmt(P.meta, key, v); };
  QKC.distribution(node, { values: vals, binCount: Math.min(12, Math.max(6, Math.round(vals.length / 2))), lowerBetter: !!m.lower, fmt: f,
    xName: V.label(P.meta, key) + (m.lower ? ' (lower is better)' : '') + ' · ' + vals.length + ' ' + (P.kind === 'teams' ? 'constructors' : 'drivers'), yName: P.kind === 'teams' ? 'Constructors' : 'Drivers',
    marks: (marks || []).filter(function (x) { return isNum(x.x); }).concat([{ x: med, label: 'Median' }]), label: 'Distribution of ' + V.label(P.meta, key) });
};
/* A segmented control of metrics for a distribution card: [[key, label]] */
V.distSeg = function (id, opts) {
  return '<div class="qk-seg pd-dist-seg" id="' + esc(id) + '" role="group" aria-label="Metric">' + opts.map(function (o, i) { return '<button type="button" aria-pressed="' + (i === 0) + '" data-value="' + esc(o[0]) + '">' + esc(o[1]) + '</button>'; }).join('') + '</div>';
};

/* ── title race: points so far, then our projection (538 style) ────────────────────────────────────────── */
function projection(season, kind) {
  var ch = season && season.championship;
  if (!ch) return null;
  var out = {};
  var D = ch.drivers || {};
  if (kind === 'drivers') {
    Object.keys(D).forEach(function (id) { out[id] = D[id].per_round_exp_points || {}; });
  } else {
    /* a constructor's expectation per remaining round is the sum of its drivers' (expectations add) */
    Object.keys(D).forEach(function (id) {
      var t = D[id].team, pr = D[id].per_round_exp_points || {};
      if (!t) return;
      if (!out[t]) out[t] = {};
      Object.keys(pr).forEach(function (r) { out[t][r] = (out[t][r] || 0) + (pr[r] || 0); });
    });
  }
  return out;
}
/* QKC.forecast of championship points by round: solid to the latest round, then each line carries on as our expected
   points to the last round (the shaded projection). n: how many (top of the table). */
V.pointsForecast = function (el, season, kind, n) {
  var node = typeof el === 'string' ? document.getElementById(el) : el;
  if (!node || !PD.ok(season)) return;
  var cal = (season.calendar || []).slice().sort(function (a, b) { return a.round - b.round; });
  var done = cal.filter(function (c) { return c.status === 'done'; });
  var prog = ((season.progression || {})[kind]) || {};
  var isD = kind === 'drivers';
  var order = ((season.standings || {})[kind] || []).map(function (r) { return isD ? r.driver : r.team; }).filter(function (id) { return prog[id]; }).slice(0, n || 6);
  if (!order.length) { PD.ch.none(node, 'No points yet this season.'); return; }
  var proj = projection(season, kind) || {};
  var xs = cal.map(function (c) { return 'R' + c.round; });
  var teamOf = {};
  ((season.standings || {}).drivers || []).forEach(function (r) { teamOf[r.driver] = r.team; });
  var st = isD ? PD.ch.styleMap(order, teamOf) : null;
  var last = done.length ? 'R' + done[done.length - 1].round : null;
  var series = order.map(function (id) {
    var p = prog[id] || [], data = [], cum = null;
    cal.forEach(function (c, i) {
      if (i < p.length) { cum = p[i]; data.push(isNum(cum) ? cum : null); return; }
      var e = (proj[id] || {})[String(c.round)];
      if (isNum(e) && isNum(cum)) { cum += e; data.push(Math.round(cum * 10) / 10); } else data.push(null);
    });
    return { name: isD ? PD.driverName(id) : PD.teamName(id), label: isD ? PD.driverCode(id) : PD.teamAbbr(id), data: data, color: isD ? st[id].colour : PD.teamColour(id), dash: isD ? st[id].dash : false };
  });
  var hasProj = season.championship && done.length < cal.length;
  QKC.forecast(node, { x: xs, xType: 'category', series: series, yFmt: function (v) { return PD.pts(v); }, yMax: 'auto', yMin: 0, yName: 'Championship points', xName: 'Round',
    today: hasProj ? last : undefined, split: hasProj ? { x: last, label: 'Projection: our expected points' } : undefined,
    xLabel: function (v) { var c = cal[xs.indexOf(v)]; return c ? v + ' · ' + c.name + (c.status === 'done' ? '' : ' (projected)') : v; }, label: (isD ? 'Drivers' : 'Constructors') + ' championship points, with our projection' });
};
/* Season-end points: the simulation's 5th to 95th percentile (bar) and the expectation (dot). */
V.rangeChart = function (el, season, kind, n) {
  var node = typeof el === 'string' ? document.getElementById(el) : el;
  var ch = season && season.championship ? season.championship[kind] || {} : null;
  if (!node) return;
  if (!ch) { PD.ch.none(node, 'The season is over: no simulation.'); return; }
  var isD = kind === 'drivers';
  var ids = Object.keys(ch).filter(function (id) { return isNum(ch[id].p05) && isNum(ch[id].p95); }).sort(function (a, b) { return ch[b].exp_points - ch[a].exp_points; }).slice(0, n || 10);
  QKC.range(node, { rows: ids.map(function (id) { return { label: isD ? PD.driverName(id) : PD.teamName(id), lo: ch[id].p05, hi: ch[id].p95, mid: ch[id].exp_points, href: isD ? PD.driverHref(id) : PD.teamHref(id),
    color: PD.teamColour(isD ? (ch[id].team || PD.driverTeam(id)) : id), sub: 'Our title chance ' + PD.pct(ch[id].p_title, ch[id].p_title > 0.99 ? 2 : 1) }; }),
    fmt: function (v) { return PD.num(v, 0); }, loName: '5th', hiName: '95th percentile', midName: 'Expected points', valName: 'Points at the season end', labelWidth: 130, label: 'Season-end points range' });
};

/* Copy pass for builder text shown on the page (STYLE_GUIDE §8): fantasy "prices" are player costs; betting words go.
   The builders keep their wording; this is display only. */
V.copy = function (t) {
  return String(t === undefined || t === null ? '' : t)
    .replace(/\bPrices\b/g, 'Costs').replace(/\bprices\b/g, 'costs').replace(/\bPrice\b/g, 'Cost').replace(/\bpriced\b/g, 'costed').replace(/\bprice\b/g, 'cost')
    .replace(/\bpace edge\b/g, 'pace advantage').replace(/\bedge\b/g, 'advantage');
};
/* Our chance rows for QK.chances (team colours; the market only where a page passes one: race detail). */
V.chanceRows = function (ids, pOf, isD, mk) {
  return ids.map(function (id) {
    var t = isD ? PD.driverTeam(id) : id;
    return { label: isD ? PD.driverName(id) : PD.teamName(id), p: pOf(id), market: mk && isNum(mk[id]) ? mk[id] : null, color: PD.teamColour(t), href: isD ? PD.driverHref(id) : PD.teamHref(id),
      mark: { name: PD.teamName(t), abbr: PD.teamAbbr(t), colour: PD.teamColour(t) } };
  });
};
})(window.PD);
