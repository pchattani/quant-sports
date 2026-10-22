/* The Quant Paddock — Standings (#/standings[/<y>][?tab=championship|odds|pace]).
 *   Championship: the tables with the title simulation (P(title), expected points and the 90% range,
 *     magic numbers, clinched / eliminated), points progression, the finishing-position distribution.
 *   Title odds v market (was #/markets): the season simulation against de-vigged Kalshi and Polymarket
 *     prices for both titles and the next race, what the next rounds mean for the leader, head to heads.
 *   Car v driver: car pace by round, driver effects, the car/driver split of points, Elo.
 * A finished season shows final standings without the simulation. Reads <y>/season.json, markets.json. */
(function (PD) {
'use strict';

var esc = PD.esc, isNum = PD.isNum;

function magicOf(c) { if (!c) return null; var m = c.magic; if (m && typeof m === 'object') return isNum(m.magic_number) ? m.magic_number : null; return isNum(m) ? m : null; }
function flag(c, k) { if (!c) return false; if (c[k] !== undefined) return !!c[k]; return !!(c.magic && typeof c.magic === 'object' && c.magic[k]); }

function render(el, params) {
  var y = isNum(params.year) ? params.year : PD.currentSeason();
  var q = params.query || {};
  var tab = ['championship', 'odds', 'pace'].indexOf(q.tab) >= 0 ? q.tab : 'championship';
  var base = '#/standings' + (y !== PD.currentSeason() ? '/' + y : '');
  el.innerHTML = PD.pageHead('Season ' + y, 'Standings', '', PD.yearPager('standings', y)) +
    PD.subnav([[base, 'Championship', 'championship'], [base + '?tab=odds', 'Title odds v market', 'odds'], [base + '?tab=pace', 'Car v driver', 'pace']], tab, 'Standings views') + '<div id="st-body">' + PD.empty('Loading', '') + '</div>';
  return Promise.all([PD.load(y + '/season.json'), PD.load('markets.json')]).then(function (arr) {
    if (!PD.alive(el)) return;
    var season = arr[0], markets = arr[1];
    if (!PD.ok(season)) { PD.set('st-body', PD.notBuilt('The ' + y + ' season', season)); return; }
    var ch = season.championship;
    var sub = el.querySelector('.pd-head .qk-sub');
    if (sub) sub.innerHTML = season.rounds_done + ' of ' + season.rounds_total + ' rounds run' + (ch ? ' · title odds from ' + (ch.n_sims ? PD.int(ch.n_sims) + ' ' : '') + 'simulated seasons' : ' · final standings') + (season.updated_at ? ' · updated ' + esc(PD.fmtStamp(season.updated_at)) : '');
    if (tab === 'odds') return odds(season, markets, y);
    if (tab === 'pace') return pace(season);
    return championship(season, markets);
  });
}

// ── championship ──────────────────────────────────────────────────────────

function championship(season) {
  var ch = season.championship, finished = !ch;
  var sd = (season.standings || {}).drivers || [], sc = (season.standings || {}).constructors || [];
  var fav = ch ? Object.keys(ch.drivers || {}).sort(function (a, b) { return ch.drivers[b].p_title - ch.drivers[a].p_title; })[0] : null;
  var h = PD.kpis([
    PD.kpi(finished ? 'Champion' : 'Leader', sd[0] ? PD.driverLink(sd[0].driver, { team: sd[0].team }) : '—', sd[0] ? PD.pts(sd[0].points) + ' pts' + (sd[1] ? ' · ' + PD.pts(sd[0].points - sd[1].points) + ' clear' : '') : '', { text: true }),
    PD.kpi(finished ? 'Constructors’ champion' : 'Constructors’ leader', sc[0] ? PD.teamLink(sc[0].team) : '—', sc[0] ? PD.pts(sc[0].points) + ' pts' : '', { text: true }),
    fav ? PD.kpi('Title favourite', PD.driverLink(fav), PD.pct(ch.drivers[fav].p_title, 2) + ' to win the title', { text: true }) : PD.kpi('Champion’s wins', sd[0] ? String(sd[0].wins) : '—', sd[0] ? sd[0].podiums + ' podiums' : ''),
    PD.kpi('Rounds', season.rounds_done + ' / ' + season.rounds_total, (season.calendar || []).filter(function (c) { return c.sprint; }).length + ' sprint weekends')
  ]);
  h += PD.grid(
    PD.card('Drivers’ championship', finished ? 'Final standings.' : 'P(title), expected final points with the middle 90% of simulated outcomes (bar), magic number to clinch.', '<div id="st-d"></div>', { span: 12, flush: true }) +
    PD.card('Points progression', '', PD.chartBox('st-prog', 400), { span: 8, right: PD.seg('st-prog-k', [['drivers', 'Drivers'], ['constructors', 'Constructors']], 'drivers', 'Progression') }) +
    PD.card('Constructors’ championship', '', '<div id="st-c"></div>', { span: 4, flush: true }) +
    (finished ? '' : PD.card('Where they finish', 'Share of simulated seasons ending in each place.', PD.chartBox('st-pd', 500), { span: 12, right: PD.seg('st-pd-k', [['drivers', 'Drivers'], ['constructors', 'Constructors']], 'drivers', 'Distribution') })), 'pd-mt');
  PD.set('st-body', h);
  standingsTable('st-d', season, 'drivers');
  standingsTable('st-c', season, 'constructors', true);
  var prog = function (kind) {
    var P = ((season.progression || {})[kind]) || {};
    var order = ((season.standings || {})[kind] || []).map(function (r) { return kind === 'drivers' ? r.driver : r.team; }).filter(function (id) { return P[id]; }).slice(0, kind === 'drivers' ? 10 : 11);
    var done = (season.calendar || []).filter(function (c) { return c.status === 'done'; }).sort(function (a, b) { return a.round - b.round; });
    var teamOf = {};
    ((season.standings || {}).drivers || []).forEach(function (r) { teamOf[r.driver] = r.team; });
    var st = kind === 'drivers' ? PD.ch.styleMap(order, teamOf) : null;
    var n = Math.max.apply(null, order.map(function (id) { return P[id].length; }).concat([0]));
    var xs = []; for (var i = 0; i < n; i++) xs.push(done[i] ? 'R' + done[i].round : 'R' + (i + 1));
    PD.ch.lines('st-prog', order.map(function (id) {
      return { name: kind === 'drivers' ? PD.driverName(id) : PD.teamName(id), short: kind === 'drivers' ? PD.driverCode(id) : PD.teamAbbr(id), data: P[id], colour: kind === 'drivers' ? st[id].colour : PD.teamColour(id), dash: kind === 'drivers' ? st[id].dash : false };
    }), { xs: xs, endLabels: true, legend: false, xName: 'Round', yName: 'Points', yScale: false, yFmt: function (v) { return PD.pts(v); }, xLabel: function (v) { var c = done[xs.indexOf(v)]; return c ? v + ' · ' + c.name : v; }, label: 'Points progression' });
  };
  prog('drivers');
  PD.wireSeg(document, 'st-prog-k', prog);
  if (!finished) {
    var pd = function (kind) {
      var c = ch[kind] || {};
      var order = ((season.standings || {})[kind] || []).map(function (r) { return kind === 'drivers' ? r.driver : r.team; }).filter(function (id) { return c[id]; });
      Object.keys(c).forEach(function (id) { if (order.indexOf(id) < 0) order.push(id); });
      PD.ch.posHeat('st-pd', order.map(function (id) { return { label: kind === 'drivers' ? PD.driverName(id) : PD.teamName(id), dist: c[id].pos_dist || [] }; }), { xName: 'Championship position', yName: kind === 'drivers' ? 'Driver' : 'Constructor' });
    };
    pd('drivers');
    PD.wireSeg(document, 'st-pd-k', pd);
  }
}

function standingsTable(id, season, kind, compact) {
  var isD = kind === 'drivers';
  var list = (season.standings || {})[kind] || [];
  if (!list.length) { PD.set(id, PD.muted('No standings for this season.')); return; }
  var ch = season.championship ? (season.championship[kind] || {}) : null;
  var maxE = ch ? Math.max.apply(null, Object.keys(ch).map(function (k) { return ch[k].p95 || 0; }).concat([1])) : 1;
  var rows = list.map(function (r) {
    var key = isD ? r.driver : r.team, c = ch ? ch[key] : null;
    return { pos: r.pos, id: key, team: r.team, name: isD ? PD.driverName(key) : PD.teamName(key), points: r.points, wins: r.wins, podiums: r.podiums, poles: r.poles,
      p: c ? c.p_title : null, exp: c ? c.exp_points : null, lo: c ? c.p05 : null, hi: c ? c.p95 : null, magic: magicOf(c), clinched: flag(c, 'clinched'), elim: flag(c, 'eliminated') };
  });
  var cols = [
    { key: 'pos', label: 'Pos', num: true },
    { key: 'name', label: isD ? 'Driver' : 'Constructor', sticky: true, fmt: function (v, r) { return (isD ? PD.driverLink(r.id, { team: r.team }) : PD.teamLink(r.id)) + (!season.championship && r.pos === 1 ? ' <span class="qk-badge accent">Champion</span>' : r.clinched ? ' <span class="qk-badge accent">Clinched</span>' : ''); } }
  ];
  if (isD && !compact) cols.push({ key: 'team', label: 'Team', fmt: function (v) { return '<span class="qk-muted">' + esc(PD.teamName(v)) + '</span>'; } });
  cols.push({ key: 'points', label: 'Pts', num: true, fmt: function (v) { return '<b>' + PD.pts(v) + '</b>'; } });
  cols.push({ key: 'wins', label: 'Wins', num: true });
  if (isD && !compact) { cols.push({ key: 'podiums', label: 'Podiums', num: true }); cols.push({ key: 'poles', label: 'Poles', num: true }); }
  if (ch) {
    cols.push({ key: 'p', label: 'Title', num: true, tip: 'Share of simulated seasons won', fmt: function (v, r) { return r.elim ? '<span class="qk-muted">out</span>' : PD.probBar(v, PD.tc(isD ? r.team : r.id)); } });
    if (!compact) {
      cols.push({ key: 'exp', label: 'Exp. pts', num: true, fmt: function (v) { return PD.num(v, 0); } });
      cols.push({ key: 'lo', label: '90% range', sort: false, tip: 'The middle 90% of simulated final points; the tick is the expectation', fmt: function (v, r) { return rangeBar(r.lo, r.exp, r.hi, maxE); } });
      cols.push({ key: 'magic', label: 'Magic', num: true, tip: 'Points needed over every rival’s maximum to clinch', fmt: function (v, r) { return v === null || r.elim ? '<span class="qk-muted">—</span>' : PD.num(v, 0); } });
    }
  }
  PD.table(id, cols, rows, { sort: { key: 'pos', dir: 'asc' } });
}
function rangeBar(lo, mid, hi, max) {
  if (!isNum(lo) || !isNum(hi) || !max) return '—';
  var x = function (v) { return Math.max(0, Math.min(100, v / max * 100)).toFixed(1); };
  return '<span class="pd-range" title="' + PD.num(lo, 0) + '–' + PD.num(hi, 0) + '"><span class="pd-range-t"><span style="left:' + x(lo) + '%;width:' + Math.max(1, x(hi) - x(lo)) + '%"></span>' + (isNum(mid) ? '<i style="left:' + x(mid) + '%"></i>' : '') + '</span><span class="pd-range-v">' + PD.num(lo, 0) + '–' + PD.num(hi, 0) + '</span></span>';
}
PD.rangeBar = rangeBar;

// ── odds v market ─────────────────────────────────────────────────────────

function edgeHTML(e) { return isNum(e) ? '<span class="' + (e > 0 ? 'pd-up' : 'pd-down') + '">' + PD.signed(100 * e, 0) + '%</span>' : '<span class="qk-muted">—</span>'; }
function sourceNames(src) { if (!src) return []; if (Array.isArray(src)) return src.map(function (s) { return typeof s === 'string' ? s : s.name || s.source || ''; }); return Object.keys(src); }

function odds(season, markets, y) {
  var cur = y === PD.currentSeason();
  var ch = season.championship;
  if (!ch) { PD.set('st-body', PD.empty('The ' + y + ' championship is decided', 'Title odds and market prices exist only for a season still running.')); return; }
  var mk = cur && markets && markets.ok !== false ? markets : {};
  var h = PD.note('<b>De-vig:</b> each price is the midpoint of a live two-sided quote (spread at most 0.12), averaged across sources, then divided by the field’s total so the probabilities sum to one. A field market is shown only when at least max(4, half the field) runners are accounted for and the implied total is between 0.8 and 1.3. Edge = model / market − 1.' + (mk.updated_at ? ' Prices fetched ' + esc(PD.fmtStamp(mk.updated_at)) + '.' : ''));
  h += PD.grid(
    PD.card('Drivers’ title', '<span id="od-d-s"></span>', PD.chartBox('od-d', 340) + '<div id="od-d-t"></div>', { span: 6 }) +
    PD.card('Constructors’ title', '<span id="od-c-s"></span>', PD.chartBox('od-c', 340) + '<div id="od-c-t"></div>', { span: 6 }) +
    PD.card('Next race winner', '<span id="od-n-s"></span>', PD.chartBox('od-n', 420), { span: 7 }) +
    PD.card('What the next rounds mean', 'For the championship leader: the chance of winning each remaining round and the title if he does or does not.', '<div id="od-cond"></div>', { span: 5, flush: true }) +
    PD.card('Head to head', 'Who finishes ahead: open race and season matchups.', '<div id="od-h2h"></div>', { span: 12, flush: true }), 'pd-mt');
  PD.set('st-body', h);
  ['drivers', 'constructors'].forEach(function (kind) {
    var T = mk[kind === 'drivers' ? 'drivers_title' : 'constructors_title'] || {};
    var model = {};
    Object.keys(ch[kind] || {}).forEach(function (id) { model[id] = ch[kind][id].p_title; });
    var prices = T.available ? (T.prices || {}) : {};
    var elim = {};
    (T.eliminated || []).forEach(function (id) { elim[id] = 1; });
    var ids = Object.keys(model).concat(Object.keys(prices).filter(function (k) { return !(k in model); })).filter(function (id) { return !elim[id] && ((model[id] || 0) > 0.0005 || (prices[id] || 0) > 0); })
      .sort(function (a, b) { return ((model[b] || 0) + (prices[b] || 0)) - ((model[a] || 0) + (prices[a] || 0)); });
    var isD = kind === 'drivers', pre = isD ? 'od-d' : 'od-c';
    var srcs = sourceNames(T.sources);
    PD.set(pre + '-s', (T.available ? 'Market from ' + esc(srcs.join(', ') || 'prediction markets') + (isNum(T.implied_total) ? ' · implied total ' + PD.num(T.implied_total, 3) : '') : 'No market published' + (T.reason ? ': ' + esc(T.reason) : '')) + ' · model ' + PD.int(ch.n_sims) + ' simulated seasons');
    if (T.available && ids.length) window.QKC.dumbbell(document.getElementById(pre), { rows: ids.slice(0, 8).map(function (id) { return { label: isD ? PD.driverName(id) : PD.teamName(id), a: model[id] || 0, b: prices[id] || 0, href: isD ? PD.driverHref(id) : PD.teamHref(id) }; }), labelWidth: 120, valName: 'Title probability' });
    else PD.ch.hbars(pre, ids.slice(0, 8).map(function (id) { return { label: isD ? PD.driverName(id) : PD.teamName(id), value: model[id] || 0, colour: PD.teamColour(isD ? PD.driverTeam(id) : id) }; }), { fmt: function (v) { return PD.pct(v); }, name: 'Model' });
    PD.table(pre + '-t', [
      { key: 'name', label: isD ? 'Driver' : 'Team', sticky: true, fmt: function (v, r) { return isD ? PD.driverLink(r.id) : PD.teamLink(r.id); } },
      { key: 'model', label: 'Model', num: true, fmt: function (v) { return PD.pct(v); } },
      { key: 'market', label: 'Market', num: true, fmt: function (v) { return isNum(v) ? PD.pct(v) : '—'; } },
      { key: 'edge', label: 'Edge', num: true, fmt: edgeHTML },
      { key: 'fair', label: 'Fair odds', num: true, tip: 'Decimal odds from the de-vigged market', fmt: function (v) { return isNum(v) ? PD.num(v, 2) : '—'; } }
    ], ids.map(function (id) { var m = model[id], p = prices[id]; var e = isNum((T.edge || {})[id]) ? T.edge[id] : (isNum(p) && p > 0 && isNum(m) ? m / p - 1 : null);
      return { id: id, name: isD ? PD.driverName(id) : PD.teamName(id), model: m, market: p, edge: e, fair: isNum(p) && p > 0 ? 1 / p : null }; }), { sort: { key: 'model', dir: 'desc' } });
    var host = document.getElementById(pre + '-t');
    if (host && Object.keys(elim).length) host.insertAdjacentHTML('beforeend', '<p class="pd-cap">Eliminated (settled no; probability 0): ' + Object.keys(elim).map(function (id) { return isD ? PD.driverLink(id, { dot: false }) : PD.teamLink(id, { dot: false }); }).join(', ') + '.</p>');
  });
  // next race
  var idx = PD.index() || {}, nx = idx.next || {}, nr = mk.next_race || {};
  var ry = nr.year || nx.year, rr = nr.round || nx.round;
  if (!cur || !rr) { PD.ch.none('od-n', 'No race left.'); }
  else {
    PD.set('od-n-s', PD.raceLink(ry, rr, ry + ' round ' + rr + (nx.name && nx.round === rr ? ': ' + nx.name : '')) + ' · blue model, orange market');
    var drawN = function (model, prices) {
      var ids = Object.keys(model).concat(Object.keys(prices).filter(function (k) { return !(k in model); })).sort(function (a, b) { return Math.max(model[b] || 0, prices[b] || 0) - Math.max(model[a] || 0, prices[a] || 0); }).slice(0, 12);
      if (!ids.length) return PD.ch.none('od-n', 'No forecast or market for the next race yet; race-winner markets list about a week out.');
      if (!Object.keys(prices).length) return PD.ch.hbars('od-n', ids.map(function (id) { return { label: PD.driverName(id), value: model[id] || 0, colour: PD.teamColour(PD.driverTeam(id)), href: PD.driverHref(id) }; }), { fmt: function (v) { return PD.pct(v); }, name: 'Model' });
      window.QKC.dumbbell(document.getElementById('od-n'), { rows: ids.map(function (id) { return { label: PD.driverName(id), a: model[id] || 0, b: prices[id] || 0, href: PD.driverHref(id) }; }), labelWidth: 120, valName: 'Win probability',
        max: Math.min(1, Math.max.apply(null, ids.map(function (id) { return Math.max(model[id] || 0, prices[id] || 0); })) * 1.15 + 0.02) });
    };
    if (Object.keys(nr.model || {}).length) drawN(nr.model, nr.prices || {});
    else PD.load(ry + '/races/' + rr + '.json').then(function (r) { var f = (r || {}).forecast || {}; var sim = f.post_quali || f.pre_quali; var m = {}; Object.keys((sim || {}).drivers || {}).forEach(function (id) { m[id] = sim.drivers[id].p_win; }); drawN(m, nr.prices || {}); });
  }
  // conditional
  var cond = (ch.conditional || {}).leader;
  if (cond && cond.by_round) {
    var rounds = Object.keys(cond.by_round).sort(function (a, b) { return a - b; });
    var calBy = {};
    (season.calendar || []).forEach(function (c) { calBy[c.round] = c; });
    PD.table('od-cond', [
      { key: 'round', label: 'Rd', num: true },
      { key: 'name', label: 'Race', sticky: true, fmt: function (v, r) { return PD.raceLink(season.year, r.round, PD.shortRace(v)); } },
      { key: 'pw', label: 'Wins it', num: true, fmt: function (v) { return PD.pct(v, 0); } },
      { key: 'iw', label: 'Title if win', num: true, fmt: function (v) { return PD.pct(v, 1); } },
      { key: 'inw', label: 'If not', num: true, fmt: function (v) { return PD.pct(v, 1); } }
    ], rounds.map(function (k) { var b = cond.by_round[k]; return { round: +k, name: (calBy[k] || {}).name || 'Round ' + k, pw: b.p_win_round, iw: b.p_title_if_win, inw: b.p_title_if_not_win }; }), { sort: { key: 'round', dir: 'asc' } });
    var hc = document.getElementById('od-cond');
    if (hc) hc.insertAdjacentHTML('afterbegin', '<p class="pd-cap pd-pad">Leader: ' + PD.driverLink(cond.driver) + '.</p>');
  } else PD.set('od-cond', PD.muted('No conditional odds for this season.'));
  // h2h
  var H = mk.h2h || [];
  var list = Array.isArray(H) ? H.map(function (x) { return Object.assign({ scope: x.scope || (x.round ? 'race' : 'season') }, x); }) : (H.race || []).map(function (x) { return Object.assign({ scope: 'race' }, x); }).concat((H.season || []).map(function (x) { return Object.assign({ scope: 'season' }, x); }));
  if (!list.length) PD.set('od-h2h', PD.muted('No head-to-head market is open. Kalshi lists race matchups and Polymarket race and season head-to-heads around race week.'));
  else PD.table('od-h2h', [
    { key: 'scope', label: 'Scope', fmt: function (v, r) { return v === 'race' ? (r.round ? PD.raceLink(ry, r.round, 'Race R' + r.round) : 'Race') : 'Season'; } },
    { key: 'a', label: 'A', sticky: true, fmt: function (v) { return PD.driverLink(v); } },
    { key: 'b', label: 'B', fmt: function (v) { return PD.driverLink(v); } },
    { key: 'p_a', label: 'Market P(A ahead)', num: true, fmt: function (v) { return PD.pct(v); } },
    { key: 'pm', label: 'Model', num: true, fmt: function (v) { return isNum(v) ? PD.pct(v) : '—'; } },
    { key: 'edge', label: 'Edge on A', num: true, fmt: edgeHTML }
  ], list.map(function (x) { var pm = isNum(x.model_a) ? x.model_a : isNum(x.model) ? x.model : null; return Object.assign({}, x, { pm: pm, edge: isNum(pm) && x.p_a ? pm / x.p_a - 1 : null }); }));
}

// ── car v driver ──────────────────────────────────────────────────────────

function pace(season) {
  var cp = season.car_pace || {};
  var anyPace = Object.keys(cp).some(function (k) { return Object.keys(cp[k] || {}).length; });
  var h = PD.grid(
    PD.card('Car pace by race', 'Each car’s pace as a % of a lap against the field from the lap-time model; negative (blue) is faster.', PD.chartBox('cp-heat', 360), { span: 12, right: anyPace ? PD.seg('cp-k', [['race', 'Race'], ['quali', 'Qualifying']], 'race', 'Session') : '' }) +
    PD.card('Car pace through the season', 'Same numbers as lines; up is faster.', PD.chartBox('cp-lines', 380), { span: 12 }) +
    PD.card('Driver effects', 'Pace against the car, % of a lap with a 95% interval; left is faster.', PD.chartBox('cp-eff', 560), { span: 6, right: anyPace ? PD.seg('cp-ek', [['race', 'Race'], ['quali', 'Qualifying']], 'race', 'Session') : '' }) +
    PD.card('Car and driver', 'Each team’s points split into what the car would score with average drivers and what its drivers added.', PD.chartBox('cp-split', 420), { span: 6 }) +
    PD.card('Elo', 'Driver ratings after the latest round: field, against the team-mate only, and in qualifying.', '<div id="cp-elo"></div>', { span: 12, flush: true }), 'pd-mt');
  PD.set('st-body', h);
  var cal = {};
  (season.calendar || []).forEach(function (c) { cal[c.round] = c; });
  var drawCP = function (kind) {
    var C = cp[kind] || {};
    var teams = Object.keys(C).filter(function (t) { return (C[t] || []).length; });
    if (!teams.length) { PD.ch.none('cp-heat', 'Car pace needs lap data (2018 on for this model).'); PD.ch.none('cp-lines', 'Car pace needs lap data.'); return; }
    var rounds = [];
    teams.forEach(function (t) { C[t].forEach(function (e) { if (rounds.indexOf(e.round) < 0) rounds.push(e.round); }); });
    rounds.sort(function (a, b) { return a - b; });
    var meanOf = function (t) { return PD.mean(C[t].map(function (e) { return e.effect; })); };
    teams.sort(function (a, b) { return meanOf(a) - meanOf(b); });
    var data = [];
    teams.forEach(function (t, yi) { C[t].forEach(function (e) { data.push([rounds.indexOf(e.round), yi, e.effect]); }); });
    PD.ch.heat('cp-heat', { xs: rounds.map(function (r) { return 'R' + r; }), ys: teams.map(PD.teamName), xName: 'Round', yName: 'Constructor', data: data, diverging: true, invert: true, fmt: function (v) { return PD.signed(v, 2); },
      tipFmt: function (v) { var t = teams[v[1]], r = rounds[v[0]]; var e = C[t].filter(function (z) { return z.round === r; })[0] || {}; return (cal[r] ? cal[r].name + ': ' : '') + PD.signed(v[2], 3) + '% ± ' + PD.num(e.se, 3); }, label: 'Car pace by race' });
    PD.ch.lines('cp-lines', teams.map(function (t) { return { name: PD.teamName(t), short: PD.teamAbbr(t), colour: PD.teamColour(t), data: C[t].slice().sort(function (a, b) { return a.round - b.round; }).map(function (e) { return [e.round, -e.effect]; }) }; }),
      { xName: 'Round', endLabels: true, legend: false, yName: '% of a lap faster than the field', yFmt: function (v) { return PD.signed(v, 2); }, xFmt: function (v) { return 'R' + v; }, xLabel: function (v) { return 'Round ' + v + (cal[v] ? ' · ' + cal[v].name : ''); }, label: 'Car pace lines' });
  };
  drawCP('race');
  PD.wireSeg(document, 'cp-k', drawCP);
  var teamOf = {};
  ((season.standings || {}).drivers || []).forEach(function (r) { teamOf[r.driver] = r.team; });
  var drawE = function (kind) {
    var eff = ((season.driver_effects || {})[kind]) || {};
    var ids = Object.keys(eff).filter(function (id) { return isNum(eff[id].effect); }).sort(function (a, b) { return eff[a].effect - eff[b].effect; });
    PD.ch.hbars('cp-eff', ids.map(function (id) { var e = eff[id]; return { label: PD.driverName(id), value: e.effect, lo: e.effect - 1.96 * (e.se || 0), hi: e.effect + 1.96 * (e.se || 0), colour: PD.teamColour(teamOf[id] || PD.driverTeam(id)), href: PD.driverHref(id), sub: (e.races || 0) + ' races' }; }),
      { fmt: function (v) { return PD.signed(v, 3) + '%'; }, name: 'Driver effect', errName: '95% interval', labels: false, axisLabels: true, xName: 'Driver effect (% of a lap)', emptyText: 'Driver effects need lap data (2018 on).', label: 'Driver effects' });
  };
  drawE('race');
  PD.wireSeg(document, 'cp-ek', drawE);
  var sp = season.car_driver_split || {};
  var teams = Object.keys(sp).sort(function (a, b) { return (sp[b].points || 0) - (sp[a].points || 0); });
  if (teams.length) {
    var maxD = Math.max.apply(null, teams.map(function (t) { return Object.keys(sp[t].drivers || {}).length; }));
    var series = [{ name: 'Car', data: teams.map(function (t) { return sp[t].car || 0; }), colours: teams.map(PD.teamColour), stack: 's', fmt: function (v) { return PD.num(v, 1) + ' pts'; } }];
    for (var k = 0; k < maxD; k++) series.push({ name: k ? 'Second driver' : 'First driver', stack: 's', colour: k ? '#8e8cf0' : '#46b9c9', data: teams.map(function (t) { var ds = Object.keys(sp[t].drivers || {}); return ds[k] ? sp[t].drivers[ds[k]] : 0; }), fmt: function (v) { return PD.signed(v, 1) + ' pts'; } });
    PD.ch.columns('cp-split', { cats: teams.map(PD.teamAbbr), series: series, yName: 'Points against an average team', fmt: function (v) { return PD.num(v, 0); },
      tipLabel: function (i) { var t = teams[i]; var ds = Object.keys(sp[t].drivers || {}); return PD.teamName(t) + ' · ' + PD.pts(sp[t].points) + ' pts' + (ds.length ? ' (' + ds.map(PD.driverCode).join(', ') + ')' : ''); }, label: 'Car and driver split' });
  } else PD.ch.none('cp-split', 'No car-driver split for this season.');
  var elo = season.elo || {};
  var ids = Object.keys(elo);
  if (ids.length) PD.table('cp-elo', [
    { key: 'name', label: 'Driver', sticky: true, fmt: function (v, r) { return PD.driverLink(r.id, { team: teamOf[r.id] }); } },
    { key: 'elo', label: 'Elo', num: true, tip: 'Against the whole field', fmt: function (v) { return '<b>' + PD.num(v, 0) + '</b>'; } },
    { key: 'tm', label: 'Team-mate', num: true, tip: 'Elo from head-to-heads with the team-mate only', fmt: function (v) { return PD.num(v, 0); } },
    { key: 'q', label: 'Quali', num: true, tip: 'Elo from qualifying', fmt: function (v) { return PD.num(v, 0); } }
  ], ids.map(function (id) { return { id: id, name: PD.driverName(id), elo: elo[id].elo, tm: elo[id].elo_teammate, q: elo[id].elo_quali }; }), { sort: { key: 'elo', dir: 'desc' }, rank: true, maxHeight: 520 });
  else PD.set('cp-elo', PD.muted('No Elo ratings for this season.'));
}

PD.route('standings', render);
})(window.PD);
