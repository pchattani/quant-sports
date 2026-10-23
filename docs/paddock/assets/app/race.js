/* The Quant Paddock — the race centre (#/race/<y>/<r>[/laps|strategy|quali|telemetry]).
 * Upcoming (kit v3, after rk-games.js): a preview hero (our favourite as a big teal number with a how-sure note, the
 * top three, the market as one quiet labelled line when there is a usable quote) with the forecast table beside it;
 * then the weekend schedule, our forecast before and after qualifying (and the sprint; the market a grey reference
 * tick) and the finishing-position distribution. Finished: awards, the result against the
 * forecast; Laps (positions, gaps, lap times, corrected pace, overtakes, race control); Strategy
 * (stints, pit stops, degradation, weather); Qualifying; Telemetry (two laps overlaid, telemetry.js).
 * Every section says so when its data is missing (no stints, overtakes or race control before 2023,
 * no laps before 1996). Reads <y>/races/<r>.json, <y>/season.json, markets.json. */
(function (PD) {
'use strict';

var esc = PD.esc, isNum = PD.isNum;
var has = function (o) { return !!o && (Array.isArray(o) ? o.length > 0 : Object.keys(o).length > 0); };
var TABS = [['', 'Overview'], ['laps', 'Laps'], ['strategy', 'Strategy'], ['quali', 'Qualifying'], ['telemetry', 'Telemetry']];

function teamMap(race, season) {
  var m = {};
  ((PD.ok(season) && season.standings && season.standings.drivers) || []).forEach(function (x) { if (x.team) m[x.driver] = x.team; });
  ['qualifying', 'sprint', 'results'].forEach(function (k) { (race[k] || []).forEach(function (x) { if (x.team) m[x.driver] = x.team; }); });
  return m;
}
PD.raceTeamMap = teamMap;

function head(race, season, tab, teams) {
  var y = race.year, r = race.round;
  var cal = PD.ok(season) ? (season.calendar || []) : [];
  var prev = cal.filter(function (c) { return c.round < r; }).sort(function (a, b) { return b.round - a.round; })[0];
  var nxt = cal.filter(function (c) { return c.round > r; }).sort(function (a, b) { return a.round - b.round; })[0];
  var row = cal.filter(function (c) { return c.round === r; })[0] || {};
  var circ = race.circuit || row.circuit || {};
  var res = (race.results || []).slice().sort(function (a, b) { return (a.pos || 99) - (b.pos || 99); });
  var win = race.status === 'done' && res[0] ? res[0] : null;
  var status = race.status === 'done' ? '<span class="qk-badge final">Result</span>' : row.status === 'next' ? '<span class="qk-badge accent">Next race</span>' : '<span class="qk-badge">Upcoming</span>';
  var sub = [circ.id ? PD.circuitLink(circ.id, circ.name) : '', circ.locality ? esc(circ.locality) + (circ.country ? ', ' + esc(circ.country) : '') : '', esc(PD.fmtDate(race.date || row.date))].filter(Boolean).join(' · ');
  var h = QK.sectionHead({ kicker: 'F1 · ' + y + ' · Round ' + r + (row.sprint || (race.sprint && race.sprint.length) ? ' · sprint weekend' : ''), title: esc(race.name || row.name || 'Round ' + r), size: 'lg', tag: 'h1', html: true, cls: 'pd-head',
    sub: sub, actions: status });
  h += '<div class="pd-racebar">' + PD.subnav(TABS.map(function (t) { return [PD.raceHref(y, r, t[0]), t[1], t[0]]; }), tab || '', 'Race views') +
    '<div class="pd-pager">' + (prev ? '<a class="qk-btn" href="' + PD.raceHref(y, prev.round, tab) + '" title="' + esc(prev.name) + '">← ' + esc(PD.shortRace(prev.name)) + '</a>' : '') +
    (nxt ? '<a class="qk-btn" href="' + PD.raceHref(y, nxt.round, tab) + '" title="' + esc(nxt.name) + '">' + esc(PD.shortRace(nxt.name)) + ' →</a>' : '') + '</div></div>';
  return h;
}

function render(el, params) {
  var y = params.year, r = params.round, tab = params.tab || '';
  if (tab && !TABS.some(function (t) { return t[0] === tab; })) tab = '';
  el.innerHTML = PD.empty('Loading the race centre', '');
  return Promise.all([PD.load(y + '/races/' + r + '.json'), PD.load(y + '/season.json'), PD.load('markets.json')]).then(function (arr) {
    if (!PD.alive(el)) return;
    var race = arr[0], season = arr[1], markets = arr[2];
    if (!PD.ok(race)) {
      var cal = PD.ok(season) ? (season.calendar || []).filter(function (c) { return c.round === r; })[0] : null;
      var stub = { year: y, round: r, name: cal ? cal.name : 'Round ' + r, date: cal ? cal.date : null, circuit: cal ? cal.circuit : {}, status: cal && cal.status === 'done' ? 'done' : 'upcoming', results: [] };
      el.innerHTML = head(stub, season, tab, {}) + PD.empty('The race centre for this round is not available', PD.reason(race)) +
        (cal && cal.winner ? PD.card('Result', '', '<p>Winner ' + PD.driverLink(cal.winner) + (cal.pole ? ' · pole ' + PD.driverLink(cal.pole) : '') + '</p>') : '');
      return;
    }
    var teams = teamMap(race, season);
    document.title = race.name + ' ' + race.year + ' · The Quant Paddock';
    var done = race.status === 'done' && has(race.results);
    el.innerHTML = head(race, season, tab, teams) + '<div id="rc-tab"></div>';
    var host = document.getElementById('rc-tab');
    if (tab === 'telemetry') return PD.telemetryLab(host, race, params.query || {});
    if (tab === 'quali') return quali(host, race, teams);
    if (!done && (tab === 'laps' || tab === 'strategy')) { host.innerHTML = PD.empty('Not run yet', 'Laps and strategy appear once the race has run. The forecast is on the overview.'); return; }
    if (tab === 'laps') return laps(host, race, teams);
    if (tab === 'strategy') return strategy(host, race, teams);
    if (done) return overviewDone(host, race, season, teams);
    return overviewUpcoming(host, race, season, teams, markets);
  });
}

// ── forecasts ─────────────────────────────────────────────────────────────

function forecastViews(race) {
  var f = race.forecast || {};
  var v = [];
  if (f.pre_quali && has(f.pre_quali.drivers)) v.push(['pre', 'Before qualifying', f.pre_quali]);
  if (f.post_quali && has(f.post_quali.drivers)) v.push(['post', 'After qualifying', f.post_quali]);
  if (race.sprint_forecast && has(race.sprint_forecast.drivers)) v.push(['sprint', 'Sprint', race.sprint_forecast]);
  return v;
}
function forecastBlock(hostId, views, teams, title, startKey, market) {
  var host = document.getElementById(hostId);
  if (!host) return;
  if (!views.length) { host.innerHTML = PD.card(title, '', PD.muted('No forecast was built for this race.')); return; }
  var start = views.filter(function (v) { return v[0] === startKey; })[0] || views[views.length - 1];
  host.innerHTML = PD.grid(
    PD.card(esc(title), '<span id="' + hostId + '-s"></span>', '<div id="' + hostId + '-ch"></div>', { span: 7, right: views.length > 1 ? PD.seg(hostId + '-k', views.map(function (v) { return [v[0], v[1]]; }), start[0], 'Forecast') : '' }) +
    PD.card('Where they finish', 'Our chance of each finishing position: the share of simulated races ending in each place.', PD.chartBox(hostId + '-heat', 520), { span: 5 }) +
    PD.card('Every driver', '', '<div id="' + hostId + '-t"></div>', { span: 12, flush: true }));
  var draw = function (key) {
    var v = views.filter(function (x) { return x[0] === key; })[0] || start;
    var sim = v[2], ds = sim.drivers;
    var ids = Object.keys(ds).sort(function (a, b) { return (ds[b].p_win - ds[a].p_win) || (ds[a].exp_pos - ds[b].exp_pos); });
    var mk = v[0] !== 'sprint' && market ? market : null;
    PD.set(hostId + '-s', esc(v[1]) + (isNum(sim.p_sc) ? ' · P(safety car) ' + PD.pct(sim.p_sc, 0) : '') + (isNum(sim.p_vsc) ? ' · P(VSC) ' + PD.pct(sim.p_vsc, 0) : '') + (isNum(sim.p_wet) && sim.p_wet > 0.005 ? ' · P(wet) ' + PD.pct(sim.p_wet, 0) : '') + ' · our win chance' + (mk ? '; the grey tick is the Kalshi / Polymarket number, for reference' : ''));
    var top = ids.slice(0, 12);
    var rows = PD.v2.chanceRows(top, function (id) { return (ds[id] || {}).p_win || 0; }, true, mk);
    rows.forEach(function (r0, i) { var d0 = ds[top[i]] || {}; r0.sub = 'podium ' + PD.pct(d0.p_podium, 0); });
    PD.set(hostId + '-ch', QK.chances(rows, { oursName: 'Our win chance', marketName: 'Market (Kalshi / Polymarket), for reference' }));
    var order = ids.slice().sort(function (a, b) { return ds[a].exp_pos - ds[b].exp_pos; });
    PD.ch.posHeat(hostId + '-heat', order.map(function (id) { return { label: PD.driverName(id), dist: ds[id].pos_dist || [] }; }), { zmax: 0.6, yName: 'Driver' });
    var hasPts = ids.some(function (id) { return isNum(ds[id].exp_points); });
    PD.table(hostId + '-t', [
      { key: 'name', label: 'Driver', sticky: true, fmt: function (x, row) { return PD.driverLink(row.id, { team: teams[row.id] }); } },
      { key: 'team', label: 'Team', fmt: function (x) { return '<span class="qk-muted">' + esc(PD.teamName(x)) + '</span>'; } },
      { key: 'p_win', label: 'Win', num: true, fmt: function (x, row) { return PD.probBar(x, PD.tc(row.team), Math.max(0.25, ds[ids[0]].p_win)); } },
      { key: 'p_podium', label: 'Podium', num: true, fmt: function (x) { return PD.pct(x); } },
      { key: 'p_points', label: 'Points', num: true, fmt: function (x) { return PD.pct(x); } },
      { key: 'p_dnf', label: 'DNF', num: true, fmt: function (x) { return PD.pct(x); } },
      { key: 'exp_pos', label: 'Exp. pos', num: true, fmt: function (x) { return PD.num(x, 1); } }
    ].concat(hasPts ? [{ key: 'exp_points', label: 'Exp. pts', num: true, fmt: function (x) { return PD.num(x, 1); } }] : []).concat(mk ? [{ key: 'mkt', label: 'Market (ref.)', num: true, tip: 'Kalshi / Polymarket win probability, shown as a reference next to ours', fmt: function (x) { return isNum(x) ? '<span class="qk-muted">' + PD.pct(x) + '</span>' : '—'; } }] : []),
    ids.map(function (id) { var d = ds[id]; return { id: id, name: PD.driverName(id), team: teams[id] || PD.driverTeam(id), p_win: d.p_win, p_podium: d.p_podium, p_points: d.p_points, p_dnf: d.p_dnf, exp_pos: d.exp_pos, exp_points: d.exp_points, mkt: mk ? mk[id] : null }; }),
    { sort: { key: 'exp_pos', dir: 'asc' } });
  };
  draw(start[0]);
  PD.wireSeg(host, hostId + '-k', draw);
}

function overviewUpcoming(host, race, season, teams, markets) {
  var views = forecastViews(race);
  var post = views.filter(function (v) { return v[0] === 'post'; })[0], pre = views.filter(function (v) { return v[0] === 'pre'; })[0];
  var main = post || pre;
  var ds = main ? main[2].drivers : {};
  var fav = Object.keys(ds || {}).sort(function (a, b) { return ds[b].p_win - ds[a].p_win; })[0];
  var idx = PD.index() || {};
  var isNext = idx.next && idx.next.year === race.year && idx.next.round === race.round;
  var sessions = isNext ? PD.sessionsOf(idx.next) : [];
  if (!sessions.length && race.schedule) {
    var sch = Object.assign({}, race.schedule);
    if (race.date && !sch.race) sch.race = race.date + 'T' + (race.time || '12:00:00Z');
    sessions = PD.sessionsOf({ sessions: sch });
  }
  var nr = (markets || {}).next_race || {};
  var mk = nr.year === race.year && nr.round === race.round && nr.prices && Object.keys(nr.prices).length ? nr.prices : null;
  var raceS = sessions.filter(function (s) { return s.key === 'race'; })[0];
  host.innerHTML = '<div class="pd-gtop">' + hero(race, main, mk, raceS, post) + '<div class="pd-gside">' +
    PD.card(post ? 'Our forecast, after qualifying' : 'Our forecast', 'The top ten by our win chance, from ' + (main && main[2].n ? PD.int(main[2].n) : '20,000') + ' simulated races.', '<div id="rc-top"></div>', { flush: true }) +
    PD.kpis([
      PD.kpi('Safety car', main && isNum(main[2].p_sc) ? PD.pct(main[2].p_sc, 0) : '—', 'our chance of at least one' + (main && isNum(main[2].p_vsc) ? ' · VSC ' + PD.pct(main[2].p_vsc, 0) : '')),
      PD.kpi('Race start', raceS ? esc(PD.fmtTime(raceS.iso)) : esc(PD.fmtDate(race.date, { year: false })), raceS ? esc(PD.fmtDate(raceS.iso, { year: false })) + ', your time' : '')
    ], 'pd-kpis-2') + '</div></div>' +
    (sessions.length ? PD.grid(PD.card('The weekend', 'Times in your time zone.', '<div class="pd-wk"><div class="pd-cd" id="rc-cd"></div><ul class="pd-sched" id="rc-sched"></ul></div>', { span: 12 }), 'pd-mt') : '') +
    '<div id="rc-fc" class="pd-mt"></div>' + (race.forecast && race.forecast.generated_at ? '<p class="pd-cap">Forecast made ' + esc(PD.fmtStamp(race.forecast.generated_at)) + '.</p>' : '');
  if (main) {
    var top = Object.keys(ds).sort(function (a, b) { return ds[b].p_win - ds[a].p_win; }).slice(0, 10);
    PD.table('rc-top', [
      { key: 'name', label: 'Driver', sticky: true, sort: false, fmt: function (x, row) { return PD.driverLink(row.id, { team: teams[row.id] }); } },
      { key: 'p_win', label: 'Win', num: true, sort: false, fmt: function (x) { return '<b class="pd-ours">' + PD.pct(x, x < 0.1 ? 1 : 0) + '</b>'; } },
      { key: 'p_podium', label: 'Podium', num: true, sort: false, fmt: function (x) { return PD.pct(x, 0); } },
      { key: 'p_points', label: 'Points', num: true, sort: false, fmt: function (x) { return PD.pct(x, 0); } },
      { key: 'exp_pos', label: 'Exp. pos', num: true, sort: false, tip: 'Our average finishing position across the simulated races', fmt: function (x) { return PD.num(x, 1); } }
    ], top.map(function (id) { var d = ds[id]; return { id: id, name: PD.driverName(id), p_win: d.p_win, p_podium: d.p_podium, p_points: d.p_points, exp_pos: d.exp_pos }; }));
  } else PD.set('rc-top', PD.muted('The forecast is built once the weekend is near.'));
  if (sessions.length) PD.weekendClock(sessions, 'rc-cd', 'rc-sched');
  forecastBlock('rc-fc', views, teams, 'Who wins? Our chance', post ? 'post' : 'pre', mk);
}

/* v3 (Matchday) hero for a race still to run, after QK.previewCard: the round and circuit, our favourite as a big
   teal number with the next two, the top three with team marks, a "How sure are we?" note, and the market as one quiet
   labelled line (game detail is one of the two places it may appear) when a usable quote exists. */
function hero(race, main, mk, raceS, post) {
  var circ = race.circuit || {};
  var meta = '<div class="qk-feature-meta"><span class="qk-pill">F1 · ' + esc(circ.name || PD.shortRace(race.name)) + '</span><span class="qk-badge">' + esc(raceS ? PD.fmtDate(raceS.iso, { year: false, time: true }) : PD.fmtDate(race.date, { year: false })) + '</span></div>';
  if (!main) return '<article class="qk-card qk-feature pd-rhero">' + meta + QK.note('Our forecast for this race is built once the weekend is near.') + '</article>';
  var ds = main[2].drivers;
  var ids = Object.keys(ds).sort(function (a, b) { return ds[b].p_win - ds[a].p_win; });
  var f = ids[0], p = ds[f].p_win, miss = Math.max(1, Math.round(10 * (1 - p)));
  var row = function (id) { var t = PD.driverTeam(id); return '<div class="qk-feature-row"><div class="t">' + (t ? PD.mark(t, 'md') : '') + '<span>' + esc(PD.driverName(id)) + '</span></div><div class="s pd-feat-p">' + PD.pct(ds[id].p_win, 0) + '</div></div>'; };
  var mline = mk && isNum(mk[f]) ? '<div class="pd-mkt-line"><span class="qk-mkt">Market (Kalshi / Polymarket), for reference: ' + esc(PD.driverSurname(f)) + ' ' + PD.pct(mk[f], 0) + '</span></div>' : '';
  return '<article class="qk-card qk-feature pd-rhero">' + meta +
    '<div class="qk-feature-big"><div class="big">' + PD.pct(p, 0) + '</div><div class="say">chance <b>' + esc(PD.driverSurname(f)) + '</b> wins' + (post ? ', now the grid is set' : '') + '. ' +
    ids.slice(1, 3).map(function (id) { return esc(PD.driverSurname(id)) + ': <b>' + PD.pct(ds[id].p_win, 0) + '</b>'; }).join(', ') + '.</div></div>' +
    ids.slice(0, 3).map(row).join('') + mline +
    QK.note('<b>How sure are we?</b> ' + PD.pct(p, 0) + ' means ' + esc(PD.driverSurname(f)) + ' loses a race like this about ' + miss + ' time' + (miss === 1 ? '' : 's') + ' in 10.' +
      (isNum(ds[f].p_podium) ? ' A podium is ' + PD.pct(ds[f].p_podium, 0) + ', and we expect P' + PD.num(ds[f].exp_pos, 1) + ' on average.' : '')) + '</article>';
}

// ── finished race: overview ───────────────────────────────────────────────

var AWARDS = [['driver_of_the_day', 'Driver of the day'], ['best_drive_from_back', 'Drive from the back'], ['best_strategy', 'Best strategy'], ['fastest_stop', 'Fastest stop'],
  ['overtake_of_race', 'Overtake of the race'], ['smoothest', 'Smoothest'], ['unluckiest', 'Unluckiest'], ['team_of_weekend', 'Team of the weekend']];

function resultRows(results, teams) {
  var win = results.filter(function (x) { return x.pos === 1; })[0] || {};
  return results.map(function (x) {
    var team = x.team || teams[x.driver];
    var classified = isNum(x.time_ms) || /^(Finished|\+\d+ Laps?|Lapped)$/i.test(String(x.status || ''));
    var gap;
    if (x.pos === 1 && isNum(x.time_ms)) gap = PD.fmtMs(x.time_ms);
    else if (isNum(x.gap_ms) && x.gap_ms > 0) gap = PD.fmtGap(x.gap_ms);
    else if (/^\+\d+ Laps?$/i.test(String(x.status || ''))) gap = esc(x.status);
    else gap = '<span class="qk-muted">' + (isNum(x.laps) ? 'out, lap ' + x.laps : '—') + '</span>';
    return { pos: isNum(x.pos) ? x.pos : 99, posT: classified || x.pos ? String(x.pos) : '—', driver: x.driver, name: PD.driverName(x.driver), team: team, grid: x.grid,
      delta: isNum(x.grid) && x.grid > 0 && isNum(x.pos) ? x.grid - x.pos : null, status: x.status, points: x.points || 0,
      t: isNum(x.time_ms) ? x.time_ms : (isNum(x.gap_ms) ? (win.time_ms || 0) + x.gap_ms : 1e12 - (x.laps || 0)), gap: gap, fl: x.fastest_ms, flr: x.fastest_rank };
  });
}
function resultsTable(id, results, teams) {
  if (!has(results)) { PD.set(id, PD.muted('No classification yet.')); return; }
  PD.table(id, [
    { key: 'pos', label: 'Pos', num: true, fmt: function (v, r) { return '<b>' + r.posT + '</b>'; } },
    { key: 'name', label: 'Driver', sticky: true, fmt: function (v, r) { return PD.driverLink(r.driver, { team: r.team }); } },
    { key: 'team', label: 'Team', fmt: function (v) { return '<span class="qk-muted">' + esc(PD.teamName(v)) + '</span>'; } },
    { key: 'grid', label: 'Grid', num: true, fmt: function (v) { return v === 0 ? 'PL' : isNum(v) ? String(v) : '—'; } },
    { key: 'delta', label: '+/−', num: true, tip: 'Places gained from the grid', fmt: function (v) { return v === null ? '—' : v > 0 ? '<span class="pd-up">▲' + v + '</span>' : v < 0 ? '<span class="pd-down">▼' + (-v) + '</span>' : '<span class="qk-muted">=</span>'; } },
    { key: 'status', label: 'Status', fmt: function (v) { return /^Finished$/i.test(v || '') ? '<span class="qk-muted">Finished</span>' : esc(v || '—'); } },
    { key: 'points', label: 'Pts', num: true, fmt: function (v) { return v ? '<b>' + PD.pts(v) + '</b>' : '<span class="qk-muted">0</span>'; } },
    { key: 't', label: 'Time / gap', num: true, fmt: function (v, r) { return r.gap; } },
    { key: 'fl', label: 'Fastest lap', num: true, fmt: function (v, r) { return isNum(v) ? '<span class="' + (r.flr === 1 ? 'pd-best' : '') + '">' + PD.fmtMs(v) + '</span>' : '—'; } }
  ], resultRows(results, teams), { sort: { key: 'pos', dir: 'asc' } });
}

function overviewDone(host, race, season, teams) {
  var res = race.results.slice().sort(function (a, b) { return (a.pos || 99) - (b.pos || 99); });
  var winner = res[0];
  var q = (race.qualifying || []).slice().sort(function (a, b) { return a.pos - b.pos; })[0];
  var fl = res.filter(function (x) { return isNum(x.fastest_ms); }).sort(function (a, b) { return a.fastest_ms - b.fastest_ms; })[0];
  var nLaps = (race.laps || {}).n || (winner && winner.laps) || null;
  var bands = PD.ch.controlBands(race.control, nLaps);
  var sc = bands.filter(function (b) { return b.kind === 'SC'; }).length, vsc = bands.filter(function (b) { return b.kind === 'VSC'; }).length, red = bands.filter(function (b) { return b.kind === 'RED'; }).length;
  var pre = race.forecast && race.forecast.pre_quali && race.forecast.pre_quali.drivers;
  var fav = pre ? Object.keys(pre).sort(function (a, b) { return pre[b].p_win - pre[a].p_win; })[0] : null;
  var winnerP = pre && winner && pre[winner.driver] ? pre[winner.driver].p_win : null;
  var favRes = fav ? res.filter(function (x) { return x.driver === fav; })[0] : null;
  var aw = race.awards || {};
  var cards = AWARDS.filter(function (a) { return aw[a[0]] && (aw[a[0]].driver || aw[a[0]].team); }).map(function (a) {
    var x = aw[a[0]], team = x.team || teams[x.driver];
    return '<div class="pd-award" style="--tc:' + esc(PD.tc(team)) + '"><div class="qk-kicker">' + esc(a[1]) + '</div><div class="pd-award-who">' + (x.driver ? PD.driverLink(x.driver, { team: team }) : PD.teamLink(x.team)) + '</div>' +
      (x.label ? '<div class="pd-award-v">' + esc(x.label) + '</div>' : '') + (x.why ? '<div class="pd-award-why">' + esc(x.why) + '</div>' : '') + '</div>';
  });
  host.innerHTML = PD.kpis([
    PD.kpi('Winner', winner ? PD.driverLink(winner.driver, { team: teams[winner.driver] }) : '—', winner ? (winner.grid ? 'from P' + winner.grid : '') + (isNum(winnerP) ? ' · our chance was ' + PD.pct(winnerP) : '') : '', { text: true }),
    PD.kpi('Pole', q ? PD.driverLink(q.driver, { team: teams[q.driver] }) : '—', q ? PD.fmtMs(q.q3 || q.q2 || q.q1) : '', { text: true }),
    PD.kpi('Fastest lap', fl ? PD.driverLink(fl.driver, { team: teams[fl.driver] }) : '—', fl ? PD.fmtMs(fl.fastest_ms) : '', { text: true }),
    PD.kpi('Neutralisations', has(race.control) ? String(sc + vsc + red) : '—', has(race.control) ? [sc + ' SC', vsc + ' VSC'].concat(red ? [red + ' red'] : []).join(' · ') : 'no race control data'),
    PD.kpi('Our favourite', fav ? PD.driverLink(fav, { team: teams[fav] }) : '—', fav ? PD.pct(pre[fav].p_win) + ' to win · finished ' + (favRes ? (PD.finished(favRes.status) ? 'P' + favRes.pos : 'DNF') : '—') : 'no pre-race forecast', { text: true })
  ]) +
  (fav && winner ? '<div class="pd-mt">' + QK.note(winner.driver === fav ? 'Our favourite won: we gave <b>' + esc(PD.driverName(fav)) + '</b> ' + PD.pct(pre[fav].p_win, 0) + ' before qualifying.'
    : '<b>' + esc(PD.driverName(winner.driver)) + '</b> won' + (isNum(winnerP) ? ', at ' + PD.pct(winnerP, winnerP < 0.1 ? 1 : 0) + ' in our numbers before qualifying' + (winnerP < 0.1 ? ': a real surprise, about 1 race in ' + Math.round(1 / Math.max(winnerP, 0.001)) : '') : '') + '. Our favourite, ' + esc(PD.driverName(fav)) + ', finished ' + (favRes ? (PD.finished(favRes.status) ? 'P' + favRes.pos : 'out of the race') : 'unclassified') + '.') + '</div>' : '') +
  (cards.length ? '<section class="qk-section pd-sec">' + PD.secHead('Awards', 'The race in numbers', 'Our picks of the race, each with the number behind it.') + '<div class="pd-awards">' + cards.join('') + '</div></section>' : '') +
  PD.grid(
    PD.card('Result', race.sprint && race.sprint.length ? 'Sprint result below.' : '', '<div id="rc-res"></div>', { span: 7, flush: true }) +
    PD.card('Forecast v result', 'Where we expected each driver to finish (teal) against where they did (ring).', PD.chartBox('rc-eva', 560), { span: 5 }) +
    PD.card('Positions lap by lap', 'Team colours; a team’s second driver is dashed. Bands: safety car (amber), red flag.', PD.chartBox('rc-pos-mini', 420), { span: 12, foot: '<a href="' + PD.raceHref(race.year, race.round, 'laps') + '">Gaps, lap times, overtakes and race control →</a>' }) +
    (race.sprint && race.sprint.length ? PD.card('Sprint result', '', '<div id="rc-sprint"></div>', { span: 12, flush: true }) : ''), 'pd-mt') +
  '<div id="rc-prefc" class="pd-mt"></div>';
  resultsTable('rc-res', res, teams);
  if (race.sprint && race.sprint.length) resultsTable('rc-sprint', race.sprint.slice().sort(function (a, b) { return (a.pos || 99) - (b.pos || 99); }), teams);
  var eva = race.expected_v_actual || {};
  var order = res.map(function (x) { return x.driver; }).filter(function (id) { return eva[id] && isNum(eva[id].exp_pos) && isNum(eva[id].actual); });
  if (order.length) window.QKC.dumbbell(document.getElementById('rc-eva'), { rows: order.map(function (id) { var e = eva[id]; var pc = isNum(e.pctile_of_actual) ? (e.pctile_of_actual <= 1 ? e.pctile_of_actual * 100 : e.pctile_of_actual) : null;
    return { label: PD.driverCode(id), a: e.exp_pos, b: e.actual, href: PD.driverHref(id), sub: PD.driverName(id) + (pc !== null ? ' · ' + PD.ordinal(Math.round(pc)) + ' percentile of the forecast' : '') }; }),
    aName: 'Our expectation', bName: 'Finished', min: 0, max: Math.max(20, order.length + 1), labelWidth: 44, valName: 'Finishing position', fmt: function (v, d) { return isNum(v) ? 'P' + (d === 0 ? Math.round(v) : PD.num(v, 1)) : '—'; } });
  else PD.ch.none('rc-eva', 'No forecast to compare with.');
  positionChart('rc-pos-mini', race, res, teams, nLaps);
  var views = forecastViews(race);
  if (views.length) forecastBlock('rc-prefc', views, teams, 'The forecast before the race', views.some(function (v) { return v[0] === 'post'; }) ? 'post' : 'pre', null);
}

function positionChart(id, race, res, teams, nLaps) {
  var laps = race.laps || {};
  if (!has(laps.positions)) { PD.ch.none(id, race.year < 1996 ? 'Lap-by-lap data starts in 1996.' : 'No lap data for this race.'); return; }
  var fixed = {};
  Object.keys(laps.positions).forEach(function (d) { fixed[d] = laps.positions[d].slice(); });
  res.forEach(function (x) { var ps = fixed[x.driver]; if (ps && isNum(x.pos) && x.laps && ps.length >= x.laps && x.laps === nLaps) ps[x.laps - 1] = x.pos; });
  var n = Object.keys(fixed).length;
  PD.ch.lapLines(id, fixed, { order: res.map(function (x) { return x.driver; }), teams: teams, control: race.control, invert: true, yMin: 1, yMax: n, interval: n > 12 ? 2 : 1, yName: 'Position', fmt: function (v) { return 'P' + v; }, yFmt: function (v) { return 'P' + v; }, label: 'Positions lap by lap' });
}

// ── laps ──────────────────────────────────────────────────────────────────

function laps(host, race, teams) {
  var res = race.results.slice().sort(function (a, b) { return (a.pos || 99) - (b.pos || 99); });
  var order = res.map(function (x) { return x.driver; });
  var L = race.laps || {};
  var nLaps = L.n || (res[0] && res[0].laps) || null;
  var noLaps = race.year < 1996 ? 'Lap-by-lap data starts in 1996.' : 'No lap data for this race.';
  host.innerHTML = PD.grid(
    PD.card('Positions lap by lap', 'Team colours; a team’s second driver is dashed. Bands: safety car (amber), red flag.', PD.chartBox('rl-pos', 520), { span: 12 }) +
    PD.card('Gap to the leader', 'Seconds behind the leader after each lap; the scale is cut so the fight at the front stays readable.', PD.chartBox('rl-gap', 440), { span: 12 }) +
    PD.card('Lap times', 'Green-flag laps within 107% of each driver’s median; lap 1 and pit laps dropped.', PD.chartBox('rl-lt', 400), { span: 8 }) +
    PD.card('Corrected pace', 'Seconds per lap against the field, corrected for fuel, tyres and traffic; negative is faster.', '<div id="rl-pace"></div>', { span: 4, flush: true }) +
    PD.card('Overtakes by lap', 'On-track passes per lap (tracked from 2023).', PD.chartBox('rl-ot', 260), { span: 6 }) +
    PD.card('Race control', 'Neutralisations, penalties and other key messages.', '<div id="rl-rc"></div>', { span: 6, flush: true }));
  if (has(L.positions)) positionChart('rl-pos', race, res, teams, nLaps); else PD.ch.none('rl-pos', noLaps);
  if (has(L.gaps)) {
    var all = [];
    Object.keys(L.gaps).forEach(function (d) { L.gaps[d].forEach(function (v) { if (isNum(v)) all.push(v); }); });
    all.sort(function (a, b) { return a - b; });
    var cap = Math.max(10, all[Math.floor(all.length * 0.9)] * 1.15 || 60);
    PD.ch.lapLines('rl-gap', L.gaps, { order: order, teams: teams, control: race.control, invert: true, yMin: 0, yMax: Math.ceil(cap), cap: cap, yName: 'Seconds behind', fmt: function (v) { return isNum(v) ? '+' + PD.num(v, 1) + 's' : '—'; }, label: 'Gap to the leader' });
  } else PD.ch.none('rl-gap', noLaps);
  var T = L.times || {};
  var pitIdx = {};
  (race.pits || []).forEach(function (p) { (pitIdx[p.driver] = pitIdx[p.driver] || {})[p.lap] = 1; });
  if (has(T)) {
    PD.ch.boxes('rl-lt', order.filter(function (d) { return T[d]; }).map(function (d) {
      var v = (T[d] || []).map(function (t, i) { return { lap: i + 1, s: isNum(t) ? t / 1000 : null }; }).filter(function (x) { return x.s !== null && x.lap > 1 && !((pitIdx[d] || {})[x.lap] || (pitIdx[d] || {})[x.lap - 1]); });
      var med = PD.median(v.map(function (x) { return x.s; }));
      return { label: PD.driverCode(d), sub: PD.driverName(d), colour: PD.teamColour(teams[d]), values: v.filter(function (x) { return x.s <= med * 1.07; }).map(function (x) { return x.s; }) };
    }), { yName: 'Lap time (s)', fmt: function (v) { return PD.fmtMs(v * 1000); }, label: 'Lap time distribution' });
  } else PD.ch.none('rl-lt', noLaps);
  var ds = (race.pace || {}).drivers || {};
  var pids = Object.keys(ds).filter(function (d) { return isNum(ds[d].pace); });
  if (pids.length) PD.table('rl-pace', [
    { key: 'name', label: 'Driver', sticky: true, fmt: function (v, r) { return PD.driverLink(r.id, { code: true, team: teams[r.id] }); } },
    { key: 'pace', label: 'Pace', num: true, fmt: function (v) { return '<span class="' + (v < 0 ? 'pd-up' : 'pd-down') + '">' + PD.signed(v, 3) + '</span>'; } },
    { key: 'se', label: '±', num: true, fmt: function (v) { return PD.num(v, 3); } },
    { key: 'laps', label: 'Laps', num: true },
    { key: 'traffic', label: 'Traffic', num: true, tip: 'Seconds lost in dirty air', fmt: function (v) { return isNum(v) ? PD.num(v, 1) + 's' : '—'; } }
  ], pids.map(function (d) { return { id: d, name: PD.driverName(d), pace: ds[d].pace, se: ds[d].se, laps: ds[d].laps, traffic: ds[d].traffic_cost }; }), { sort: { key: 'pace', dir: 'asc' }, rank: true, maxHeight: 400 });
  else PD.set('rl-pace', PD.muted('No corrected pace for this race.'));
  var ov = (race.overtakes || []).filter(function (o) { return o && isNum(o.lap); });
  if (ov.length) {
    var n = nLaps || Math.max.apply(null, ov.map(function (o) { return o.lap; }));
    var counts = [], who = {};
    for (var i = 1; i <= n; i++) counts.push(0);
    ov.forEach(function (o) { if (o.lap <= n) { counts[o.lap - 1]++; (who[o.lap] = who[o.lap] || []).push(PD.driverCode(o.by) + ' on ' + PD.driverCode(o.on)); } });
    PD.ch.columns('rl-ot', { cats: counts.map(function (c, k) { return String(k + 1); }), series: [{ name: 'Overtakes', data: counts, colour: PD.col('sky'), fmt: function (v) { return String(v); } }], xName: 'Lap', yName: 'Overtakes', fmt: function (v) { return PD.num(v, 0); },
      tipLabel: function (k) { var w = who[k + 1] || []; return 'Lap ' + (k + 1) + (w.length ? ': ' + w.slice(0, 6).join(', ') + (w.length > 6 ? '…' : '') : ''); }, label: 'Overtakes by lap' });
  } else PD.ch.none('rl-ot', 'No overtake data for this race (tracked from 2023).');
  var key = (race.control || []).filter(function (e) { return e && (e.kind === 'SC' || e.kind === 'VSC' || e.kind === 'RED' || e.kind === 'PENALTY' || /INVESTIGATION|DELETED|DRS (EN|DIS)ABLED|RED FLAG|CHEQUERED/i.test(e.message || '')); });
  PD.set('rl-rc', key.length ? '<ul class="pd-rcl">' + key.map(function (e) {
    var cls = e.kind === 'RED' ? 'live' : e.kind === 'SC' || e.kind === 'VSC' ? 'edge' : e.kind === 'PENALTY' ? 'accent' : '';
    return '<li><span class="pd-rcl-lap">Lap ' + esc(e.lap) + '</span><span class="qk-badge ' + cls + '">' + esc(e.kind) + '</span><span class="pd-rcl-msg">' + esc(e.message || '') + '</span></li>';
  }).join('') + '</ul>' : PD.muted(race.year < 2023 ? 'Race control messages are tracked from 2023.' : 'No neutralisations or penalties.'));
}

// ── strategy ──────────────────────────────────────────────────────────────

function strategy(host, race, teams) {
  var res = race.results.slice().sort(function (a, b) { return (a.pos || 99) - (b.pos || 99); });
  var order = res.map(function (x) { return x.driver; });
  var nLaps = (race.laps || {}).n || (res[0] && res[0].laps) || null;
  var legend = '<div class="pd-legend">' + ['SOFT', 'MEDIUM', 'HARD', 'INTERMEDIATE', 'WET'].map(function (c) { return '<span><i style="background:' + PD.compoundColour(c) + '"></i>' + c.charAt(0) + c.slice(1).toLowerCase() + '</span>'; }).join('') + '</div>';
  host.innerHTML = PD.grid(
    PD.card('Tyre strategy', 'Stints by compound, in finishing order; hover a stint for its laps.', legend + PD.chartBox('rs-st', 480), { span: 12 }) +
    PD.card('Stop times', 'Every stop, fastest first, in team colours.', PD.chartBox('rs-stops', 300), { span: 7 }) +
    PD.card('Pit stops', '', '<div id="rs-pits"></div>', { span: 5, flush: true }) +
    PD.card('Degradation by compound', 'Seconds per lap lost per lap of tyre age, against each compound’s median driver (blue degrades least).', '<div id="rs-deg"></div>', { span: 7, flush: true }) +
    PD.card('Weather', '', PD.chartBox('rs-wx', 280), { span: 5 }));
  if (has(race.stints)) PD.ch.stints('rs-st', race.stints, { order: order, nLaps: nLaps });
  else PD.ch.none('rs-st', race.year < 2023 ? 'Tyre stints are tracked from 2023.' : 'No tyre stints for this race.');
  var pits = (race.pits || []).filter(function (p) { return p && p.driver; });
  if (pits.length) {
    var useStop = pits.some(function (p) { return isNum(p.stop_ms); });
    var k = useStop ? 'stop_ms' : 'lane_ms';
    var sorted = pits.filter(function (p) { return isNum(p[k]); }).sort(function (a, b) { return a[k] - b[k]; });
    PD.ch.columns('rs-stops', { cats: sorted.map(function (p) { return PD.driverCode(p.driver); }), series: [{ name: useStop ? 'Stationary' : 'Pit lane', data: sorted.map(function (p) { return p[k] / 1000; }), colours: sorted.map(function (p) { return PD.teamColour(teams[p.driver]); }), fmt: function (v) { return PD.num(v, 2) + 's'; } }],
      yName: useStop ? 'Stationary time (s)' : 'Pit lane time (s)', fmt: function (v) { return PD.num(v, 1); }, rotate: sorted.length > 16 ? 90 : 0, tipLabel: function (i) { return PD.driverName(sorted[i].driver) + ', lap ' + sorted[i].lap; }, label: 'Pit stop times' });
    var best = Math.min.apply(null, pits.filter(function (p) { return isNum(p.stop_ms); }).map(function (p) { return p.stop_ms; }).concat([Infinity]));
    PD.table('rs-pits', [
      { key: 'name', label: 'Driver', sticky: true, fmt: function (v, r) { return PD.driverLink(r.driver, { code: true, team: teams[r.driver] }); } },
      { key: 'lap', label: 'Lap', num: true },
      { key: 'stop', label: 'Stationary', num: true, fmt: function (v) { return isNum(v) ? '<span class="' + (v === best ? 'pd-best' : '') + '">' + PD.num(v / 1000, 2) + 's</span>' : '—'; } },
      { key: 'lane', label: 'Pit lane', num: true, fmt: function (v) { return isNum(v) ? PD.num(v / 1000, 1) + 's' : '—'; } }
    ], pits.map(function (p) { return { driver: p.driver, name: PD.driverName(p.driver), lap: p.lap, stop: p.stop_ms, lane: p.lane_ms }; }), { sort: { key: 'lap', dir: 'asc' }, maxHeight: 300 });
  } else { PD.ch.none('rs-stops', 'No pit stops recorded.'); PD.set('rs-pits', PD.muted('No pit stops recorded.')); }
  var ds = (race.pace || {}).drivers || {};
  var comps = [];
  Object.keys(ds).forEach(function (d) { Object.keys(ds[d].deg || {}).forEach(function (c) { if (comps.indexOf(c) < 0) comps.push(c); }); });
  var ORDER = ['SOFT', 'MEDIUM', 'HARD', 'INTERMEDIATE', 'WET'];
  comps.sort(function (a, b) { return ORDER.indexOf(a.toUpperCase()) - ORDER.indexOf(b.toUpperCase()); });
  var dids = Object.keys(ds).filter(function (d) { return has(ds[d].deg); }).sort(function (a, b) { return (ds[a].pace || 0) - (ds[b].pace || 0); });
  PD.set('rs-deg', comps.length && dids.length ? PD.heatTable({ corner: 'Driver', cols: comps.map(function (c) { return c.charAt(0) + c.slice(1).toLowerCase(); }),
    rows: dids.map(function (d) { return { label: PD.driverLink(d, { code: true, team: teams[d] }), values: comps.map(function (c) { return (ds[d].deg || {})[c]; }) }; }), fmt: function (v) { return PD.signed(v, 3); }, center: 'col', invert: true }) : PD.muted('No degradation estimates for this race.'));
  var w = (race.weather || []).filter(function (r) { return r && isNum(r.t_ms); }).sort(function (a, b) { return a.t_ms - b.t_ms; });
  if (w.length >= 2) PD.ch.lines('rs-wx', [
    { name: 'Track °C', data: w.map(function (r) { return [r.t_ms / 60000, r.track > 0 ? r.track : null]; }), colour: PD.col('coral') },
    { name: 'Air °C', data: w.map(function (r) { return [r.t_ms / 60000, r.air]; }), colour: PD.col('sky') },
    { name: 'Wind m/s', data: w.map(function (r) { return [r.t_ms / 60000, r.wind]; }), colour: PD.col('grey'), dash: true }
  ], { xName: 'Minutes from the start' + (w.some(function (r) { return r.rain; }) ? ' (rain recorded)' : ''), xFmt: function (v) { return Math.round(v); }, xLabel: function (v) { return Math.round(v) + ' min'; }, yName: '°C, or m/s for wind', yFmt: function (v) { return PD.num(v, 1); }, label: 'Weather through the race' });
  else PD.ch.none('rs-wx', 'No weather readings for this race.');
}

// ── qualifying ────────────────────────────────────────────────────────────

function quali(host, race, teams) {
  var ql = (race.qualifying || []).slice().sort(function (a, b) { return a.pos - b.pos; });
  if (!ql.length) { host.innerHTML = PD.empty('No qualifying classification', race.status === 'done' ? 'None was recorded for this race.' : 'Qualifying has not run yet.'); return; }
  var best = function (k) { return Math.min.apply(null, ql.map(function (x) { return isNum(x[k]) ? x[k] : Infinity; })); };
  var b1 = best('q1'), b2 = best('q2'), b3 = best('q3'), hasQ2 = isFinite(b2), hasQ3 = isFinite(b3);
  var outIn = function (x) { return hasQ3 && isNum(x.q3) ? null : hasQ2 && isNum(x.q2) ? 'Q2' : hasQ2 || hasQ3 ? 'Q1' : null; };
  var pole = ql[0];
  var tm = ql.filter(function (x) { return isNum(x.teammate_gap_ms); }).sort(function (a, b) { return Math.abs(a.teammate_gap_ms) - Math.abs(b.teammate_gap_ms); });
  var fmtQ = function (v) { return isNum(v) ? PD.fmtMs(v) : (v ? esc(v) : '—'); };
  host.innerHTML = PD.kpis([
    PD.kpi('Pole', PD.driverLink(pole.driver, { team: pole.team || teams[pole.driver] }), fmtQ(pole.q3 || pole.q2 || pole.q1), { text: true }),
    PD.kpi('Front row', ql[1] ? PD.driverLink(ql[1].driver, { team: ql[1].team || teams[ql[1].driver] }) : '—', ql[1] && isNum(ql[1].gap_ms_to_pole) ? PD.fmtGap(ql[1].gap_ms_to_pole) + ' to pole' : '', { text: true }),
    PD.kpi('Top-10 spread', ql[9] && isNum(ql[9].gap_ms_to_pole) ? PD.fmtGap(ql[9].gap_ms_to_pole) : '—', 'P1 to P10'),
    PD.kpi('Closest team-mates', tm.length ? esc(PD.teamName(tm[0].team || teams[tm[0].driver])) : '—', tm.length ? PD.fmtMs(Math.abs(tm[0].teammate_gap_ms)) + 's apart' : '', { text: true })
  ]) + PD.grid(
    PD.card('Gap to pole', 'Each driver’s best lap against pole, in team colours.', PD.chartBox('rq-gap', Math.max(320, ql.length * 22 + 40)), { span: 5 }) +
    PD.card('Qualifying', 'Highlighted: fastest in each segment.', '<div id="rq-t"></div>', { span: 7, flush: true }), 'pd-mt');
  var g = ql.filter(function (x) { return isNum(x.gap_ms_to_pole); });
  PD.ch.hbars('rq-gap', g.map(function (x) { return { label: PD.driverCode(x.driver), full: PD.driverName(x.driver), value: x.gap_ms_to_pole / 1000, colour: PD.teamColour(x.team || teams[x.driver]), href: PD.driverHref(x.driver), sub: 'P' + x.pos + (outIn(x) ? ' · out in ' + outIn(x) : '') }; }),
    { fmt: function (v) { return v ? '+' + PD.num(v, 3) : 'pole'; }, name: 'Seconds to pole', labelWidth: 44, emptyText: 'No lap times to compare.' });
  var segCell = function (bst) { return function (v) { return '<span class="' + (isNum(v) && v === bst ? 'pd-best' : '') + '">' + fmtQ(v) + '</span>'; }; };
  PD.table('rq-t', [
    { key: 'pos', label: 'Pos', num: true },
    { key: 'name', label: 'Driver', sticky: true, fmt: function (v, r) { return PD.driverLink(r.driver, { team: r.team }); } },
    { key: 'q1', label: 'Q1', num: true, fmt: segCell(b1) }, { key: 'q2', label: 'Q2', num: true, fmt: segCell(b2) }, { key: 'q3', label: 'Q3', num: true, fmt: segCell(b3) },
    { key: 'gap', label: 'Gap', num: true, fmt: function (v, r) { return r.pos === 1 ? '<span class="qk-muted">pole</span>' : isNum(v) ? PD.fmtGap(v) : '—'; } },
    { key: 'tm', label: 'v team-mate', num: true, fmt: function (v) { return isNum(v) ? '<span class="' + (v <= 0 ? 'pd-up' : 'pd-down') + '">' + (v <= 0 ? '−' + PD.fmtMs(-v) : '+' + PD.fmtMs(v)) + '</span>' : '—'; } },
    { key: 'out', label: '', sort: false, fmt: function (v) { return v ? '<span class="qk-badge">out in ' + v + '</span>' : (hasQ3 ? '<span class="qk-badge accent">Q3</span>' : ''); } }
  ], ql.map(function (x) { return { pos: x.pos, driver: x.driver, name: PD.driverName(x.driver), team: x.team || teams[x.driver], q1: x.q1, q2: x.q2, q3: x.q3, gap: x.gap_ms_to_pole, tm: x.teammate_gap_ms, out: outIn(x) }; }), { sort: { key: 'pos', dir: 'asc' } });
}

PD.route('race', render);
PD.race = { resultsTable: resultsTable, teamMap: teamMap };
})(window.PD);
