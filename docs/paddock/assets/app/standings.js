/* The Quant Paddock — Standings (#/standings[/<y>][?tab=championship|odds|pace]).
 *   Championship: the tables with the title simulation (P(title), expected points and the 90% range,
 *     magic numbers, clinched / eliminated), points progression, the finishing-position distribution.
 *   Title chances (was #/markets): our chances from the season simulation, the points race with our projection
 *     (538 style), the season-end points range and what the next rounds mean for the leader. The market
 *     reference for the titles is on the Model page.
 *   Car v driver: car pace by round, driver effects, the car/driver split of points, Elo.
 *   Below the championship tables (fight.js, PD.fight): how the fights are shaping up (clinch lines, the next Grand
 *     Prix's stakes, the fights for places, who moved, points against our forecast, the run-in), the shape of the grid
 *     (tiers, car v driver, team-mate battles) and every driver's and team's strengths and weak spots; the drivers'
 *     table gains a Profile column of the same chips.
 * A finished season shows final standings without the simulation. Reads <y>/season.json. */
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
  el.innerHTML = PD.pageHead('Standings · ' + y, 'Who leads the ' + y + ' championship', '', PD.yearPager('standings', y)) +
    PD.subnav([[base, 'Championship', 'championship'], [base + '?tab=odds', 'Title chances', 'odds'], [base + '?tab=pace', 'Car v driver', 'pace']], tab, 'Standings views') + '<div id="st-body">' + PD.empty('Loading', '') + '</div>';
  return Promise.all([PD.load(y + '/season.json')]).then(function (arr) {
    if (!PD.alive(el)) return;
    var season = arr[0], markets = null;
    if (!PD.ok(season)) { PD.set('st-body', PD.notBuilt('The ' + y + ' season', season)); return; }
    var ch = season.championship;
    var sub = el.querySelector('.pd-head .qk-sh-sub');
    if (sub) sub.innerHTML = season.rounds_done + ' of ' + season.rounds_total + ' rounds run' + (ch ? ' · title chances from ' + (ch.n_sims ? PD.int(ch.n_sims) + ' ' : '') + 'simulated seasons' : ' · final standings') + (season.updated_at ? ' · updated ' + esc(PD.fmtStamp(season.updated_at)) : '');
    if (tab === 'odds') return odds(season, markets, y);
    if (tab === 'pace') return pace(season);
    return championship(season, markets);
  });
}

// ── championship ──────────────────────────────────────────────────────────

/* Top and bottom performers (QKL.leaders): the drivers on the spec's driver set (our race and qualifying driver
   ratings first, the car taken out) and the constructors on the team set, the top five and the bottom five among the
   qualified (PD.v2.peer: the f1.json floors), each linked to the driver or team page. From the season's drivers.json
   and teams.json (the team pages load the same files), after the first paint. */
var PERF_FMT = { driver_effect: '+3', quali_driver_effect: '+3', race_pace: '+3', car_race_pace: '+3', race_h2h: 'pct0', team_points_share: 'pct0', dnf_rate: 'pct0',
  pit_under_2500: 'pct0', elo_teammate: '0', points_per_race: '1', lap1_gain: '+2', strategy_gain: '+2', pit_lane_v_field: '+0' };
function perfView(cat, kind, season, sets) {
  if (!PD.ok(cat)) return null;
  var V = PD.v2, P = V.peer(cat, kind, season), team = kind === 'teams', ent = team ? 'constructor' : 'driver';
  var keys = [].concat.apply([], sets.map(function (g) { return g[1]; }));
  var ms = keys.map(function (k) {
    var sm = V.spec ? V.spec.metric(k, ent) : null, o = V.ours(k);
    var rows = P.ids.map(function (id) { var r = P.rows[id] || {}; return { id: id, name: team ? PD.teamName(id) : PD.driverName(id), team: team ? id : r.team, v: (r.values || {})[k] }; });
    return QKL.board(rows, { key: k, label: V.label(P.meta, k), unit: sm && sm.unit !== '%' ? sm.unit : '', dir: (P.meta[k] || {}).lower ? 'lower' : 'higher', fmt: PERF_FMT[k] || '2', ours: o ? o.name : '', tip: V.tip(P.meta, k) }, 5);
  }).filter(function (m) { return m.n > 1; });
  ms = ms.filter(function (m) { return m.ours; }).concat(ms.filter(function (m) { return !m.ours; }));
  return ms.length ? { key: kind, label: team ? 'Constructors' : 'Drivers', entity: team ? 'team' : 'player', peer: team ? 'constructors' : 'drivers', min: P.floor + ' ' + P.unit + ' this season', metrics: ms } : null;
}
function performers(season) {
  var host = document.getElementById('st-perf');
  if (!host || !window.QKL || !QKL.leaders) return;
  var y = season.year;
  Promise.all([PD.loadAll([y + '/drivers.json', y + '/teams.json']), PD.v2.specP]).then(function (res) {
    var arr = res[0];
    host = document.getElementById('st-perf');
    if (!host) return;
    var views = [perfView(arr[0], 'drivers', season, PD.v2.DRIVER_SET), perfView(arr[1], 'teams', season, PD.v2.TEAM_SET)].filter(Boolean);
    QKL.leaders(host, { data: { views: views }, title: 'Who leads the grid, and who is struggling', scope: 'grid',
      sub: 'The top five and the bottom five on each key number among this season’s qualified drivers (our driver ratings first: race and qualifying pace against the team-mate, the car taken out) and constructors. Each name opens the driver or team page.',
      team: function (t) { return t ? { abbr: PD.teamAbbr(t), name: PD.teamName(t), colour: PD.teamColourRaw(t), href: PD.teamHref(t) } : null; },
      href: function (id) { return PD.driverHref(id); },
      empty: 'The boards fill once drivers reach the season’s floor of starts.' });
  });
}

function championship(season) {
  var ch = season.championship, finished = !ch;
  var sd = (season.standings || {}).drivers || [], sc = (season.standings || {}).constructors || [];
  var fav = ch ? Object.keys(ch.drivers || {}).sort(function (a, b) { return ch.drivers[b].p_title - ch.drivers[a].p_title; })[0] : null;
  var h = PD.kpis([
    PD.kpi(finished ? 'Champion' : 'Leader', sd[0] ? PD.driverLink(sd[0].driver, { team: sd[0].team }) : '—', sd[0] ? PD.pts(sd[0].points) + ' pts' + (sd[1] ? ' · ' + PD.pts(sd[0].points - sd[1].points) + ' clear' : '') : '', { text: true }),
    PD.kpi(finished ? 'Constructors’ champion' : 'Constructors’ leader', sc[0] ? PD.teamLink(sc[0].team) : '—', sc[0] ? PD.pts(sc[0].points) + ' pts' : '', { text: true }),
    fav ? PD.kpi('Drivers’ title', esc(PD.driverCode(fav)) + ' ' + PD.titlePct(ch.drivers[fav], 1), esc(PD.driverName(fav)) + ' · our chance', { signal: true, href: PD.driverHref(fav) }) : PD.kpi('Champion’s wins', sd[0] ? String(sd[0].wins) : '—', sd[0] ? sd[0].podiums + ' podiums' : ''),
    PD.kpi('Rounds', season.rounds_done + ' / ' + season.rounds_total, (season.calendar || []).filter(function (c) { return c.sprint; }).length + ' sprint weekends')
  ]);
  if (!finished) h += '<div class="pd-mt">' + PD.note('The <b>magic number</b> is how many more points the leader needs to be champion whatever the others do. The bar beside each driver is the middle 90% of our simulated final points: the season ends inside it 9 times in 10.') + '</div>';
  h += PD.grid(
    PD.card('Drivers’ championship', finished ? 'Final standings.' : 'Our title chance, our expected final points with the middle 90% of simulated outcomes (bar), and the magic number to clinch.', '<div id="st-d"></div>', { span: 12, flush: true }) +
    PD.card('The title race', 'Points after every round, then our expected points to the last round (shaded).', PD.chartBox('st-prog', 400, 'Championship points with our projection'), { span: 8, right: PD.seg('st-prog-k', [['drivers', 'Drivers'], ['constructors', 'Constructors']], 'drivers', 'Progression') }) +
    PD.card('Constructors’ championship', '', '<div id="st-c"></div>', { span: 4, flush: true }) +
    (finished ? '' : PD.card('Where they finish', 'Our chance of each championship position: the share of simulated seasons ending in each place.', PD.chartBox('st-pd', 500), { span: 12, right: PD.seg('st-pd-k', [['drivers', 'Drivers'], ['constructors', 'Constructors']], 'drivers', 'Distribution') })), 'pd-mt');
  h += '<div id="st-fight"></div>' + (window.QKL && QKL.leaders ? '<div id="st-perf"></div>' : '') + '<div id="st-shape"></div><div id="st-prof"></div>';
  PD.set('st-body', h);
  standingsTable('st-d', season, 'drivers');
  standingsTable('st-c', season, 'constructors', true);
  /* the fights, the shape of the grid and the profiles (fight.js); the drivers' table is drawn again with its chips */
  if (PD.fight) PD.fight.load(season.year).then(function (ex) {
    if (!document.getElementById('st-fight')) return;
    standingsTable('st-d', season, 'drivers', false, function (id) { return PD.fight.chips(ex, id, season); });
    PD.fight.race('st-fight', season, ex);
    PD.fight.shape('st-shape', season, ex);
    PD.fight.profiles('st-prof', season, ex);
  });
  performers(season);
  var prog = function (kind) { PD.v2.pointsForecast('st-prog', season, kind, kind === 'drivers' ? 10 : 11); };
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

function standingsTable(id, season, kind, compact, chipsOf) {
  var isD = kind === 'drivers';
  var list = (season.standings || {})[kind] || [];
  if (!list.length) { PD.set(id, PD.muted('No standings for this season.')); return; }
  var ch = season.championship ? (season.championship[kind] || {}) : null;
  var maxE = ch ? Math.max.apply(null, Object.keys(ch).map(function (k) { return ch[k].p95 || 0; }).concat([1])) : 1;
  var rows = list.map(function (r) {
    var key = isD ? r.driver : r.team, c = ch ? ch[key] : null;
    return { pos: r.pos, id: key, team: r.team, name: isD ? PD.driverName(key) : PD.teamName(key), points: r.points, gross: r.points_gross, excluded: r.excluded || null, wins: r.wins, podiums: r.podiums, poles: r.poles,
      p: c ? c.p_title : null, exp: c ? c.exp_points : null, lo: c ? c.p05 : null, hi: c ? c.p95 : null, magic: magicOf(c), clinched: flag(c, 'clinched'), elim: flag(c, 'eliminated') };
  });
  var cols = [
    /* an entry excluded from the championship (Schumacher 1997, McLaren 2007) keeps its results, scores 0 and ranks last: EX */
    { key: 'pos', label: 'Pos', num: true, fmt: function (v, r) { return r.excluded ? '<span class="qk-badge" data-tip="Excluded from the championship: ' + esc(String(r.excluded)) + '" tabindex="0">EX</span>' : (isNum(v) ? String(v) : '—'); } },
    { key: 'name', label: isD ? 'Driver' : 'Constructor', sticky: true, fmt: function (v, r) { return (isD ? PD.driverLink(r.id, { team: r.team }) : PD.teamLink(r.id)) + (!season.championship && r.pos === 1 ? ' <span class="qk-badge accent">Champion</span>' : r.clinched ? ' <span class="qk-badge accent">Clinched</span>' : ''); } }
  ];
  if (isD && !compact) cols.push({ key: 'team', label: 'Team', fmt: function (v) { return '<span class="qk-muted">' + esc(PD.teamName(v)) + '</span>'; } });
  /* counted points; the gross total beside them when dropped scores (before 1991) or an exclusion made them differ */
  cols.push({ key: 'points', label: 'Pts', num: true, tip: 'Points that count for the championship; the smaller figure is the gross total when dropped scores or an exclusion made them differ', fmt: function (v, r) { return '<b>' + PD.pts(v) + '</b>' + (isNum(r.gross) && isNum(v) && Math.abs(r.gross - v) > 1e-9 ? ' <span class="qk-muted">(' + PD.pts(r.gross) + ' gross)</span>' : ''); } });
  cols.push({ key: 'wins', label: 'Wins', num: true });
  if (isD && !compact) { cols.push({ key: 'podiums', label: 'Podiums', num: true }); cols.push({ key: 'poles', label: 'Poles', num: true }); }
  if (ch) {
    cols.push({ key: 'p', label: 'Title', num: true, tip: 'Our title chance: the share of simulated seasons won', fmt: function (v, r) { return r.elim ? '<span class="qk-muted">out</span>' : PD.probBar(v, PD.tc(isD ? r.team : r.id), null, PD.chance(v, { clinched: r.clinched })); } });
    if (!compact) {
      cols.push({ key: 'exp', label: 'Exp. pts', num: true, fmt: function (v) { return PD.num(v, 0); } });
      cols.push({ key: 'lo', label: '90% range', sort: false, tip: 'The middle 90% of simulated final points; the tick is the expectation', fmt: function (v, r) { return rangeBar(r.lo, r.exp, r.hi, maxE); } });
      cols.push({ key: 'magic', label: 'Magic', num: true, tip: 'Points needed over every rival’s maximum to clinch', fmt: function (v, r) { return v === null || r.elim ? '<span class="qk-muted">—</span>' : PD.num(v, 0); } });
    }
  }
  if (chipsOf) cols.push({ key: 'id', label: 'Profile', sort: false, tip: 'Standout strengths and weak spots against the grid (percentiles on the F1 metric set), and points against our pre-race forecast', fmt: function (v) { return '<span class="fx-chips">' + (chipsOf(v) || '') + '</span>'; } });
  PD.table(id, cols, rows, { sort: { key: 'pos', dir: 'asc' } });
}
function rangeBar(lo, mid, hi, max) {
  if (!isNum(lo) || !isNum(hi) || !max) return '—';
  var x = function (v) { return Math.max(0, Math.min(100, v / max * 100)).toFixed(1); };
  return '<span class="pd-range" title="' + PD.num(lo, 0) + '–' + PD.num(hi, 0) + '"><span class="pd-range-t"><span style="left:' + x(lo) + '%;width:' + Math.max(1, x(hi) - x(lo)) + '%"></span>' + (isNum(mid) ? '<i style="left:' + x(mid) + '%"></i>' : '') + '</span><span class="pd-range-v">' + PD.num(lo, 0) + '–' + PD.num(hi, 0) + '</span></span>';
}
PD.rangeBar = rangeBar;

// ── title chances (was "title odds v market"; the market reference now sits on the Model page) ───────────

function odds(season, markets, y) {
  var ch = season.championship;
  if (!ch) { PD.set('st-body', PD.empty('The ' + y + ' championship is decided', 'Title chances exist only for a season still running.')); return; }
  var top = function (kind) {
    var c = ch[kind] || {};
    return Object.keys(c).filter(function (id) { return !c[id].eliminated && isNum(c[id].p_title); }).sort(function (a, b) { return (c[b].p_title - c[a].p_title) || ((c[b].exp_points || 0) - (c[a].exp_points || 0)); });
  };
  var dTop = top('drivers'), cTop = top('constructors');
  var fav = dTop[0], cfav = cTop[0];
  var cond = (ch.conditional || {}).leader;
  var h = PD.kpis([
    PD.kpi('Drivers’ title', fav ? esc(PD.driverCode(fav)) + ' ' + PD.titlePct(ch.drivers[fav], 1) : '—', fav ? esc(PD.driverName(fav)) + ' · our chance' : '', { signal: true, href: fav ? PD.driverHref(fav) : null }),
    PD.kpi('Constructors’ title', cfav ? esc(PD.teamAbbr(cfav)) + ' ' + PD.titlePct(ch.constructors[cfav], 1) : '—', cfav ? esc(PD.teamName(cfav)) + ' · our chance' : '', { signal: true, href: cfav ? PD.teamHref(cfav) : null }),
    PD.kpi('Still in it', String(dTop.filter(function (id) { return ch.drivers[id].p_title >= 0.0005; }).length), 'drivers with at least a 0.05% chance'),
    PD.kpi('Rounds left', String((ch.remaining || []).length), isNum((ch.max_points_left || {}).driver) ? (ch.max_points_left.driver) + ' points still to win' : ''),
    PD.kpi('Simulated seasons', PD.int(ch.n_sims), 'each remaining round raced again')
  ]);
  h += '<div class="pd-mt">' + PD.note('A <b>title chance</b> is the share of our ' + PD.int(ch.n_sims) + ' simulated seasons that a driver or team wins: 5% is about 1 season in 20. Every remaining round is raced again in each one.') + '</div>';
  h += '<section class="qk-section pd-sec">' + PD.secHead('Season simulation', 'The title race', 'Points so far, then our expected points for every round still to run (the shaded projection).', PD.seg('od-k', [['drivers', 'Drivers'], ['constructors', 'Constructors']], 'drivers', 'Championship')) +
    PD.grid(
      PD.card('Points, with our projection', 'Each line is labelled at its end with our expected final points.', PD.chartBox('od-fc', 400, 'Championship points with our projection'), { span: 8 }) +
      PD.card('Title chances', '<span id="od-t-s"></span>', '<div id="od-t"></div>', { span: 4 }) +
      PD.card('After each round', 'Our title chance, or expected final points with the 5th–95th percentile band, as each round finished; the latest is Today.', '<div id="od-hist" class="qk-chart" style="--h:320px" role="img" aria-label="Title race after each round"></div>', { span: 12, right: PD.seg('od-hm', [['p', 'Title chance'], ['pts', 'Points']], 'p', 'Measure') }) +
      PD.card('Where the points land', 'The bar spans the 5th to 95th percentile of simulated season-end points; the dot is our expectation.', PD.chartBox('od-range', 400, 'Season-end points range'), { span: 6 }) +
      PD.card('What the next rounds mean', cond ? 'For the leader, ' + PD.driverLink(cond.driver, { dot: false }) + ': our chance of winning each remaining round, and of the title if the leader does or does not.' : 'Conditional chances for the championship leader.', '<div id="od-cond"></div>', { span: 6, flush: true })) + '</section>';
  PD.set('st-body', h);
  var curK = 'drivers', hm = 'p';
  var draw = function (kind) {
    var isD = kind === 'drivers';
    var ids = (isD ? dTop : cTop).slice(0, 10);
    PD.v2.pointsForecast('od-fc', season, kind, isD ? 8 : 6);
    curK = kind;
    PD.v2.titleHistory('od-hist', season, kind, isD ? 6 : 5, hm);
    PD.v2.rangeChart('od-range', season, kind, 10);
    PD.set('od-t-s', 'Our chance of the ' + (isD ? 'drivers’' : 'constructors’') + ' title from ' + PD.int(ch.n_sims) + ' simulated seasons.');
    var rows = PD.v2.chanceRows(ids, function (id) { return ch[kind][id].p_title; }, isD, null, function (id) { return ch[kind][id]; });
    rows.forEach(function (r, i) { var c = ch[kind][ids[i]]; r.sub = 'exp. ' + PD.num(c.exp_points, 0) + ' pts'; });
    PD.set('od-t', QK.chances(rows, { max: 1, oursName: 'Our title chance' }) + (Object.keys(ch[kind] || {}).some(function (id) { return ch[kind][id].eliminated; }) ? '<p class="pd-cap">Out of contention: ' + Object.keys(ch[kind]).filter(function (id) { return ch[kind][id].eliminated; }).map(function (id) { return isD ? PD.driverLink(id, { dot: false }) : PD.teamLink(id, { dot: false }); }).join(', ') + '.</p>' : ''));
  };
  draw('drivers');
  PD.wireSeg(document, 'od-k', draw);
  PD.wireSeg(document, 'od-hm', function (v) { hm = v; PD.v2.titleHistory('od-hist', season, curK, curK === 'drivers' ? 6 : 5, hm); });
  if (cond && cond.by_round) {
    var rounds = Object.keys(cond.by_round).sort(function (a, b) { return a - b; });
    var calBy = {};
    (season.calendar || []).forEach(function (c) { calBy[c.round] = c; });
    PD.table('od-cond', [
      { key: 'round', label: 'Rd', num: true },
      { key: 'name', label: 'Race', sticky: true, fmt: function (v, r) { return PD.raceLink(season.year, r.round, PD.shortRace(v)); } },
      { key: 'pw', label: 'Wins it', num: true, tip: 'Our chance the leader wins this round', fmt: function (v) { return PD.pct(v, 0); } },
      { key: 'iw', label: 'Title with win', num: true, fmt: function (v) { return PD.pct(v, 1); } },
      { key: 'inw', label: 'If not', num: true, fmt: function (v) { return PD.pct(v, 1); } }
    ], rounds.map(function (k) { var b = cond.by_round[k]; return { round: +k, name: (calBy[k] || {}).name || 'Round ' + k, pw: b.p_win_round, iw: b.p_title_if_win, inw: b.p_title_if_not_win }; }), { sort: { key: 'round', dir: 'asc' } });
  } else PD.set('od-cond', PD.muted('No conditional chances for this season.'));
}

// ── car v driver ──────────────────────────────────────────────────────────

function pace(season) {
  var cp = season.car_pace || {};
  var anyPace = Object.keys(cp).some(function (k) { return Object.keys(cp[k] || {}).length; });
  var h = '<div class="pd-mt">' + PD.note('Our lap-time model splits every lap into the <b>car</b> and the <b>driver</b>. Pace is a share of a lap: 0.5% is about 0.45 seconds on a 90-second lap. The driver part is measured against the team-mate, so the car is taken out.') + '</div>' + PD.grid(
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
    for (var k = 0; k < maxD; k++) series.push({ name: k ? 'Second driver' : 'First driver', stack: 's', colour: k ? PD.col('plum') : PD.col('mint'), data: teams.map(function (t) { var ds = Object.keys(sp[t].drivers || {}); return ds[k] ? sp[t].drivers[ds[k]] : 0; }), fmt: function (v) { return PD.signed(v, 1) + ' pts'; } });
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
