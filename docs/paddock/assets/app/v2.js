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
  driver_effect: ['Race pace v team-mate', 'Race pace once the car is taken out: how much faster or slower than the team-mate per lap. Lower is faster.'],
  quali_driver_effect: ['Qualifying pace v team-mate', 'The same in qualifying: one-lap pace against the team-mate, % of a lap. Lower is faster.'],
  race_h2h: ['Race head-to-head v team-mate', 'Share of races finished ahead of the team-mate.'],
  team_points_share: ['Share of team points v team-mate', 'Share of the points the car scored.'],
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
  /* drivers.json from 22 Oct 2026 carries peer_floor, qualified and pct_peer (the same formula among the qualifying
     drivers): read them when present, else compute here */
  var usePayload = kind !== 'teams' && cat && isNum(cat.peer_floor) && Object.keys(rows).some(function (id) { return rows[id] && rows[id].pct_peer; });
  if (usePayload) f = { n: cat.peer_floor, unit: f.unit };
  var ids = Object.keys(rows).filter(function (id) { return usePayload ? rows[id].qualified === true : size(id) >= f.n; });
  var pct = {};
  ids.forEach(function (id) { pct[id] = usePayload ? Object.assign({}, rows[id].pct_peer || {}) : {}; });
  if (!usePayload) Object.keys(meta).forEach(function (k) {
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
/* prev: last season's percentiles in the same peer group (the hollow ring on the v3 rail), or null. */
V.pctGroups = function (P, id, sets, prev) {
  var row = P.rows[id] || {}, pc = P.pct[id];
  if (!pc) return [];
  var m50 = P.kind === 'teams' ? V.M50_TEAM : V.M50;
  return (sets || []).map(function (g) {
    return { label: g[0], rows: g[1].map(function (k) {
      if (!isNum(pc[k])) return null;
      return { label: V.label(P.meta, k), sub: V.SUB[k] || '', pctl: pc[k], prev: prev && isNum(prev[k]) ? prev[k] : null, value: V.fmt(P.meta, k, (row.values || {})[k]), tip: V.tip(P.meta, k), early: isNum(m50[k]) && P.size(id) < m50[k] };
    }).filter(Boolean) };
  });
};
/* The v3 percentile rail (QK.pctRail): o.prev (last season's ring), o.ringLabel, o.id, o.kicker, o.title. */
V.pctCard = function (P, id, sets, o) {
  o = o || {};
  var q = P.qualified(id);
  return QK.pctRail({ id: o.id, kicker: o.kicker || 'How they stack up', title: o.title || (P.kind === 'teams' ? 'Percentiles: how the team ranks' : 'Percentiles: how the driver ranks'), peer: P.label, sample: P.sample(id),
    groups: q ? V.pctGroups(P, id, sets, o.prev) : [], right: o.right, foot: o.foot, ringLabel: o.ringLabel || 'last season',
    emptyTitle: 'Short of the sample floor', emptyText: q ? 'No headline metric has a value yet.' : 'Percentiles appear once ' + (P.kind === 'teams' ? 'the team reaches ' : 'the driver reaches ') + P.floor + ' ' + P.unit + ' this season.' });
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
/* Title chances after each completed round (season.json "title_history", recorded from round 17 of 2026): 538-style
   lines, one per contender, labelled at the end, the latest round "Today". mode 'pts': expected final points with the
   simulation's 5th-95th percentile band. Until three rounds are on record it writes a short note instead of a
   near-empty chart. */
V.titleHistory = function (el, season, kind, n, mode) {
  var node = typeof el === 'string' ? document.getElementById(el) : el;
  if (!node) return false;
  var H = ((season && season.title_history) || []).filter(function (h) { return h && isNum(h.after_round) && h[kind]; }).sort(function (a, b) { return a.after_round - b.after_round; });
  if (H.length < 3) {
    node.innerHTML = '<p class="pd-cap" style="margin:0">' + (H.length ? 'Recording started after round ' + H[0].after_round + ' with ' + H.length + ' round' + (H.length === 1 ? '' : 's') + ' so far' : 'No round has been recorded yet') +
      '. The chart appears once three rounds are on record; earlier rounds were never stored.</p>';
    node.style.height = 'auto';
    return false;
  }
  var isD = kind === 'drivers', pts = mode === 'pts';
  var lastH = H[H.length - 1][kind];
  var ids = Object.keys(lastH).filter(function (id) { return H.some(function (h) { return isNum((h[kind][id] || {}).p_title) && h[kind][id].p_title >= 0.01; }); })
    .sort(function (a, b) { return pts ? (((lastH[b] || {}).exp_points || 0) - ((lastH[a] || {}).exp_points || 0)) : (((lastH[b] || {}).p_title || 0) - ((lastH[a] || {}).p_title || 0)); }).slice(0, n || 6);
  if (!ids.length) { node.innerHTML = '<p class="pd-cap" style="margin:0">Nobody else has a 1% title chance on record.</p>'; return false; }
  var teamOf = {};
  ((season.standings || {}).drivers || []).forEach(function (r) { teamOf[r.driver] = r.team; });
  var st = isD ? PD.ch.styleMap(ids, teamOf) : null;
  var xs = H.map(function (h) { return 'R' + h.after_round; });
  var get = function (h, id, k) { var r = h[kind][id]; return r && isNum(r[k]) ? r[k] : null; };
  QKC.forecast(node, { x: xs, xType: 'category', xName: 'After round', yName: pts ? 'Expected final points (5th–95th percentile band)' : 'Our title chance',
    yFmt: pts ? function (v) { return PD.num(v, 0); } : undefined, yMax: pts ? 'auto' : undefined, yMin: 0,
    series: ids.map(function (id) { return { name: isD ? PD.driverName(id) : PD.teamName(id), label: isD ? PD.driverCode(id) : PD.teamAbbr(id), color: isD ? st[id].colour : PD.teamColour(id), dash: isD ? st[id].dash : false,
      data: H.map(function (h) { return get(h, id, pts ? 'exp_points' : 'p_title'); }),
      band: pts ? { lo: H.map(function (h) { return get(h, id, 'p05'); }), hi: H.map(function (h) { return get(h, id, 'p95'); }) } : undefined }; }),
    today: xs[xs.length - 1], label: (isD ? 'Drivers' : 'Constructors') + (pts ? ' expected points' : ' title chances') + ' after each round' });
  return true;
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

/* ── kit v3 (Matchday): plain lines on the rail, verdicts ──────────────────────────────────────────────── */
/* One plain-English line under each headline metric on the percentile rail (QK.pctRail r.sub). */
V.SUB = {
  driver_effect: 'Lap time with the car taken out, against the team-mate.',
  quali_driver_effect: 'One-lap speed against the team-mate.',
  race_h2h: 'How often the driver finishes ahead of the team-mate.',
  team_points_share: 'The driver’s share of the points the car scored.',
  elo_teammate: 'A rating built only from duels with team-mates.',
  race_pace: 'Race pace against the whole field, car included.',
  points_per_race: 'Championship points per start.',
  lap1_gain: 'Places made or lost on the opening lap.',
  car_race_pace: 'How fast the car is over a race, against the field.',
  dnf_rate: 'How often a start ends in a retirement (lower is better).',
  pit_lane_v_field: 'Time in the pit lane against the field (lower is better).',
  pit_under_2500: 'How often the crew turns a stop in under 2.5 seconds.',
  strategy_gain: 'Places made or lost through pit-stop timing.'
};
/* The type a driver's (or team's) best metric suggests (compare verdicts). */
V.ARCHETYPE = { driver_effect: 'The racer', quali_driver_effect: 'The qualifier', race_h2h: 'The team leader', team_points_share: 'The points carrier', elo_teammate: 'The team-mate beater',
  race_pace: 'The quick one', points_per_race: 'The points machine', lap1_gain: 'The fast starter', quali_h2h: 'The qualifier', avg_grid: 'The front-runner', podium_rate: 'The podium regular',
  win_rate: 'The winner', pos_gained: 'The charger', overtakes_made: 'The overtaker', consistency: 'The metronome', tyre_mgmt: 'The tyre whisperer', dnf_rate: 'The finisher',
  car_race_pace: 'The fast car', pit_lane_v_field: 'The slick pit lane', pit_under_2500: 'The quick crew', strategy_gain: 'The strategists' };
function lc(x) { x = String(x || ''); return /^[A-Z][a-z]/.test(x) ? x.charAt(0).toLowerCase() + x.slice(1) : x; }
V.lc = lc;
/* QK.verdicts items: for each entry, the metric where it leads the others by the most percentile points.
   Ps: a peer group per entry (V.peer), ids, sets (V.DRIVER_SET ...), names. */
V.verdicts = function (Ps, ids, sets, names) {
  var keys = [];
  (sets || []).forEach(function (g) { g[1].forEach(function (k) { if (keys.indexOf(k) < 0) keys.push(k); }); });
  return ids.map(function (id, i) {
    var best = null;
    keys.forEach(function (k) {
      var mine = Ps[i] && Ps[i].pct[id] ? Ps[i].pct[id][k] : null;
      if (!isNum(mine)) return;
      var others = ids.map(function (o, j) { return j === i ? null : (Ps[j] && Ps[j].pct[o] ? Ps[j].pct[o][k] : null); }).filter(isNum);
      if (!others.length) return;
      var d = mine - Math.max.apply(null, others);
      if (d > 0 && (!best || d > best.d)) best = { k: k, d: d };
    });
    if (!best) return null;
    var P = Ps[i], v = ((P.rows[id] || {}).values || {})[best.k];
    return { title: V.ARCHETYPE[best.k] || 'The standout', who: names[i], text: 'best of the ' + ids.length + ' on ' + lc(V.label(P.meta, best.k)) + ' (' + V.fmt(P.meta, best.k, v) + ', ' + PD.ordinal(Math.round(P.pct[id][best.k])) + ' percentile).' };
  });
};
/* The compare view on a metric set for 2-3 entries of one peer group (QK.compareView), the best in each row under the
   highlighter. */
V.compare = function (P, ids, sets, ents) {
  var meta = P.meta;
  var groups = sets.map(function (g) {
    return { label: g[0], rows: g[1].filter(function (k) { return meta[k]; }).map(function (k) {
      var m = meta[k];
      return { label: V.label(meta, k), tip: V.tip(meta, k), better: m.lower ? 'low' : 'high', values: ids.map(function (id) { return ((P.rows[id] || {}).values || {})[k]; }),
        pctls: ids.map(function (id) { return P.pct[id] ? P.pct[id][k] : null; }), fmt: function (v) { return V.fmt(meta, k, v); } };
    }) };
  });
  return QK.compareView({ entities: ents, groups: groups, delta: false });
};
/* Nearest entries in the peer group on the metric set's percentiles (mean absolute gap), excluding the entry itself. */
V.nearest = function (P, id, sets, n) {
  var mine = P.pct[id];
  if (!mine) return [];
  var keys = [];
  (sets || []).forEach(function (g) { g[1].forEach(function (k) { if (isNum(mine[k])) keys.push(k); }); });
  if (!keys.length) return [];
  return P.ids.filter(function (o) { return o !== id && P.pct[o]; }).map(function (o) {
    var s = 0, c = 0;
    keys.forEach(function (k) { var v = P.pct[o][k]; if (isNum(v)) { s += Math.abs(v - mine[k]); c++; } });
    return c ? { id: o, d: s / c } : null;
  }).filter(Boolean).sort(function (a, b) { return a.d - b.d; }).slice(0, n || 2);
};

/* "How sure are we?" from calibration.json: the race simulator's win forecasts before qualifying (every driver in every
   scored race; QK.calib.find reads metrics.model_pre.win), with the Brier score of giving everyone the base rate. */
V.calib = function (cj) {
  var cb = cj && cj.ok !== false ? QK.calib.find(cj) : null;
  if (!cb || !cb.bins.length) return null;
  var w = ((((cj.metrics || {}).model_pre) || {}).win) || {};
  var br = isNum(cb.base_rate) ? cb.base_rate : w.base_rate;
  var ys = Object.keys(cj.seasons_used || cj.seasons || {}).sort();
  return { n: cb.n, brier: cb.brier, bins: cb.bins, base_rate: br, base: isNum(br) ? br * (1 - br) : null, span: ys.length ? ys[0] + '–' + ys[ys.length - 1] : '' };
};

/* Copy pass for builder text shown on the page (STYLE_GUIDE §8): fantasy "prices" are player costs; betting words go.
   Display only. Kept for the local payloads: the local fantasy.json label and glossary.json still say "prices" /
   "edge" (23 Oct 2026); the deployed ones are clean (checked 23 Oct), so this goes after the next local rebuild. */
V.copy = function (t) {
  return String(t === undefined || t === null ? '' : t)
    .replace(/\bPrices\b/g, 'Costs').replace(/\bprices\b/g, 'costs').replace(/\bPrice\b/g, 'Cost').replace(/\bpriced\b/g, 'costed').replace(/\bprice\b/g, 'cost')
    .replace(/\bpace edge\b/g, 'pace advantage').replace(/\bedge\b/g, 'advantage');
};
/* Our chance rows for QK.chances (team colours; the market only where a page passes one: race detail). */
V.chanceRows = function (ids, pOf, isD, mk) {
  return ids.map(function (id) {
    var t = isD ? PD.driverTeam(id) : id;
    return { label: isD ? PD.driverName(id) : PD.teamName(id), p: pOf(id), market: mk && isNum(mk[id]) ? mk[id] : null, color: PD.teamColourRaw(t), href: isD ? PD.driverHref(id) : PD.teamHref(id),
      mark: { name: PD.teamName(t), abbr: PD.teamAbbr(t), colour: PD.teamColourRaw(t) } };
  });
};
/* ── kit v4 (Broadcast) ─────────────────────────────────────────────────────────────────────────────────── */
/* A driver as one side of a two-sided kit block (QK.splitHero, QK.previewCard, QK.scorebugXL, QK.tape): the surname
   shown, the code, the constructor's colour from the payloads (team-mates share it: QK.color.blockPair gives the
   second driver slate with the constructor colour as the rule), the full name, and the team and car number as the line
   under the name. No colour in the payloads: the kit's cobalt v slate rule. */
V.side = function (id, team) {
  var t = team || PD.driverTeam(id), info = PD.NAMES.drivers[id] || {};
  var sub = [t ? PD.teamName(t) : '', isNum(info.number) ? '#' + info.number : ''].filter(Boolean).join(' · ');
  /* city: the line QK.splitHero prints under the name when no sub function is passed (QK.previewCard) */
  return { name: PD.driverSurname(id), abbr: PD.driverCode(id), colour: PD.teamColourRaw(t), alt: PD.teamAlt(t), full: PD.driverName(id), team: t, sub: sub, city: sub, href: PD.driverHref(id) };
};
/* Two sides from one constructor: drop the second side's alt, so team-mates keep the F1 rule (the second driver on
   slate with the constructor colour as the rule) rather than taking the team's second livery colour. Returns b. */
V.mates = function (a, b) {
  if (a && b && a.team && a.team === b.team) delete b.alt;
  return b;
};
V.sideSub = function (t) { return t.sub || ''; };
/* The race as a two-sided "game" for the kit's diagonal hero: our favourite against our second pick, each with our win
   chance. The favourite is the "home" side and callers pass homeFirst: true, so it sits on the left and the quiet
   market line on the race page (QK.previewCard prints the home side's number) is the favourite's. A race is not a
   duel, so the note says how often the favourite loses to the whole field; factors set the two side by side. */
V.raceGame = function (race, ds, o) {
  o = o || {};
  var ids = Object.keys(ds || {}).filter(function (id) { return isNum((ds[id] || {}).p_win); }).sort(function (a, b) { return ds[b].p_win - ds[a].p_win; });
  if (ids.length < 2) return null;
  var a = ids[0], b = ids[1], c = ids[2];
  var teams = o.teams || {};
  var p = ds[a].p_win, miss = Math.max(1, Math.round(10 * (1 - p)));
  var note = '<b>How sure are we?</b> ' + PD.pct(p, 0) + ' means ' + esc(PD.driverSurname(a)) + ' loses a race like this about ' + miss + ' time' + (miss === 1 ? '' : 's') + ' in 10: with twenty cars, even a clear favourite is usually under 50%.' +
    (c ? ' ' + esc(PD.driverSurname(c)) + ' is next on ' + PD.pct(ds[c].p_win, 0) + '.' : '') + (o.extra ? ' ' + o.extra : '');
  return { ids: ids, note: note, g: { sport: 'f1', status: 'pre', start: o.start || race.date, league: o.league || ('Round ' + race.round), href: o.href,
    home: V.side(a, teams[a]), away: V.mates(V.side(a, teams[a]), V.side(b, teams[b])), p_home: p, p_away: ds[b].p_win },
    factors: [['Podium', 'p_podium', false, function (v) { return PD.pct(v, 0); }], ['Points finish', 'p_points', false, function (v) { return PD.pct(v, 0); }],
      ['Expected finish', 'exp_pos', true, function (v) { return 'P' + PD.num(v, 1); }], ['Retirement', 'p_dnf', true, function (v) { return PD.pct(v, 0); }]]
      .filter(function (f) { return isNum(ds[a][f[1]]) && isNum(ds[b][f[1]]); })
      .map(function (f) { var va = ds[b][f[1]], vb = ds[a][f[1]]; return { label: f[0], a: f[3](va), b: f[3](vb), better: Math.abs(va - vb) < 1e-9 ? null : ((va > vb) !== f[2] ? 'a' : 'b') }; }) };
};
/* One "call" on the overview, as a kit game card (.qk-gc): the stripe in the constructor colour split by our chance,
   the kicker, one or two rows (the team mark, the name and team, our number in Bebas, the favourite in blue), and the
   foot "Our chance · <why>". o: { kicker, right, href, rows: [{ team, name, sub, p | text, fav }], stripe: p, team,
   why, ft } */
V.callCard = function (o) {
  var tag = o.href ? 'a' : 'div';
  var raw = o.team ? PD.teamColourRaw(o.team) : null;
  var c = raw ? QK.color.team(raw) : 'var(--signal)';
  var sp = isNum(o.stripe) ? Math.max(0.04, Math.min(0.96, o.stripe)) : 1;
  var stripe = '<span class="qk-gc-stripe" aria-hidden="true"><i style="flex:' + sp.toFixed(3) + ';background:' + c + '"></i>' + (sp < 1 ? '<i style="flex:' + (1 - sp).toFixed(3) + ';background:var(--seg-off)"></i>' : '') + '</span>';
  var rows = (o.rows || []).map(function (r) {
    var mk = r.team ? PD.mark(r.team, 'md') : QK.teamMark({ abbr: r.abbr || '' }, 'md');
    var v = isNum(r.p) ? QK.pctSmall(r.p, r.p < 0.1 && r.p > 0 ? 1 : undefined) : esc(r.text || '');
    return '<div class="qk-gc-row' + (r.fav ? ' fav' : '') + '">' + mk + '<span class="qk-gc-nm">' + esc(r.name) + (r.sub ? '<small>' + esc(r.sub) + '</small>' : '') + '</span><span></span><span></span><span class="qk-gc-v pct">' + v + '</span></div>';
  }).join('');
  return '<' + tag + (o.href ? ' href="' + esc(o.href) + '"' : '') + ' class="qk-gc pd-call">' + stripe +
    '<div class="qk-gc-top"><span class="qk-gc-lg">' + esc(o.kicker || '') + '</span>' + (o.right ? '<span class="qk-badge">' + esc(o.right) + '</span>' : '') + '</div>' +
    '<div class="qk-gc-rows">' + rows + '</div>' + (o.why ? '<div class="qk-gc-ft"><b>' + esc(o.ft || 'Our chance · ') + '</b>' + esc(o.why) + '</div>' : '') + '</' + tag + '>';
};
/* "We say it. Then we check it." (QK.howSure) from calibration.json: the simulator's win chance before qualifying for
   every driver in every scored race, with F1 wording on the three big numbers (the Brier score against giving every
   driver the base rate, our contenders' bucket, the top end). Returns false when the record is missing. */
V.howSure = function (box, cj) {
  var cb = V.calib(cj);
  if (!box || !cb) return false;
  var shown = cb.bins.filter(function (b) { return b.n >= 30; });
  var fav = shown.filter(function (b) { return b.lo >= 0.2; }).sort(function (a, b) { return b.n - a.n; })[0];
  var top = shown[shown.length - 1], gap = top ? top.freq - top.mean_p : 0;
  var pts = [
    isNum(cb.brier) ? { k: cb.brier.toFixed(3), b: 'Brier score', text: '0 is perfect.' + (isNum(cb.base) ? ' Giving every driver the same ' + PD.pct(cb.base_rate, 0) + ' would score ' + cb.base.toFixed(3) + '.' : '') + ' Lower is better.' } : null,
    fav ? { k: Math.round(fav.freq * 100) + '%', b: 'won when we said ' + Math.round(fav.mean_p * 100) + '%', text: 'Our contenders: ' + QK.fmt.num(fav.n) + ' drivers we gave ' + Math.round(fav.lo * 100) + '–' + Math.round(fav.hi * 100) + '%; ' + PD.pct(fav.freq, 1) + ' of them won.' } : null,
    top ? { k: (gap > 0 ? '+' : gap < 0 ? '−' : '±') + Math.abs(Math.round(gap * 100)) + ' pts', b: 'at the top end', text: 'Our biggest favourites (' + Math.round(top.lo * 100) + '%+) won ' + PD.pct(top.freq, 0) + ' of the time; we said ' + PD.pct(top.mean_p, 0) + (Math.abs(gap) <= 0.03 ? ': spot on.' : gap > 0 ? ': a little too shy.' : ': a little too bold.') + (Math.abs(gap) > 0.03 ? ' Bins this small swing a lot.' : '') } : null
  ].filter(Boolean);
  QK.howSure(box, { bins: cb.bins, brier: cb.brier, n: cb.n, league: 'F1', span: cb.span, subject: 'the driver', unit: 'driver-races', points: pts });
  return true;
};
})(window.PD);
