/* The Quant Paddock — Standings (#/standings[/<y>][?tab=table|chances|history]), round 9: Table, Chances, History.
 *   Table (was Championship; ?tab=championship still lands): the tables with the title simulation (P(title), expected
 *     points and the 90% range, magic numbers, clinched / eliminated); a finished season's points progression.
 *   Chances (was Title chances, ?tab=odds; one tab for every season-simulation board): our chances from the season
 *     simulation, the points race with our projection (538 style), the title race after each round, where each driver
 *     and team finishes, the season-end points range and what the next rounds mean for the leader. Only while a season
 *     runs. The market reference for the titles is on Model › Our forecasts v the market.
 *   History: every champion since 1950 (index.json seasons_meta), the most titles, the dynasties (title streaks) and
 *     how long each of today's teams has waited.
 *   Car v driver (was ?tab=pace) moved to Value › Driver value (PD.carDriver, drawn there); the top and bottom
 *     performers moved to the Scouting Room's Leaders, with a link left here.
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
  if (q.tab === 'pace') { PD.go('#/value' + (y !== PD.currentSeason() && y >= 1994 ? '/' + y : '') + '?sec=cvd'); return null; }
  var tab = { championship: 'table', table: 'table', odds: 'chances', chances: 'chances', history: 'history' }[q.tab] || 'table';
  var base = '#/standings' + (y !== PD.currentSeason() ? '/' + y : '');
  var idxMeta = ((PD.index() || {}).seasons_meta || {})[String(y)] || {};
  var running = !(idxMeta.completed && idxMeta.rounds && idxMeta.completed >= idxMeta.rounds) && y === PD.currentSeason();
  var tabs = [[base, 'Table', 'table']].concat(running || tab === 'chances' ? [[base + '?tab=chances', 'Chances', 'chances']] : []).concat([[base + '?tab=history', 'History', 'history']]);
  el.innerHTML = PD.pageHead('Standings · ' + y, tab === 'history' ? 'Every champion since 1950' : running ? 'Who leads the ' + y + ' championship' : 'How the ' + y + ' championship finished', '', PD.yearPager('standings', y)) +
    PD.subnav(tabs, tab, 'Standings views') + '<div id="st-body">' + PD.empty('Loading', '') + '</div>';
  if (tab === 'history') return history(el);
  return Promise.all([PD.load(y + '/season.json')]).then(function (arr) {
    if (!PD.alive(el)) return;
    var season = arr[0], markets = null;
    if (!PD.ok(season)) { PD.set('st-body', PD.notBuilt('The ' + y + ' season', season)); return; }
    var ch = season.championship;
    var sub = el.querySelector('.pd-head .qk-sh-sub');
    if (sub) sub.innerHTML = season.rounds_done + ' of ' + season.rounds_total + ' rounds run' + (ch ? ' · title chances from ' + (ch.n_sims ? PD.int(ch.n_sims) + ' ' : '') + 'simulated seasons' : ' · final standings') + (season.updated_at ? ' · updated ' + esc(PD.fmtStamp(season.updated_at)) : '');
    if (tab === 'chances') return odds(season, markets, y);
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
    fav ? PD.kpi('Drivers’ title', esc(PD.driverCode(fav)) + ' ' + PD.titlePct(ch.drivers[fav], 1), esc(PD.driverName(fav)) + ' · our chance', { signal: true, href: PD.driverHref(fav) }) : PD.kpi('Champion’s wins', sd[0] ? String(sd[0].wins) : '—', sd[0] ? sd[0].podiums + ' podiums' : ''),
    PD.kpi('Rounds', season.rounds_done + ' / ' + season.rounds_total, (season.calendar || []).filter(function (c) { return c.sprint; }).length + ' sprint weekends')
  ]);
  if (finished) h = '<div id="st-recap"></div>' + h;
  if (!finished) h += '<div class="pd-mt">' + PD.note('The <b>magic number</b> is how many more points the leader needs to be champion whatever the others do. The bar beside each driver is the middle 90% of our simulated final points: the season ends inside it 9 times in 10.') + '</div>';
  var yq = season.year !== PD.currentSeason() ? '/' + season.year : '';
  h += PD.grid(
    PD.card('Drivers’ championship', finished ? 'Final standings.' : 'Our title chance, our expected final points with the middle 90% of simulated outcomes (bar), and the magic number to clinch.', '<div id="st-d"></div>', { span: 12, flush: true,
      foot: finished ? '' : '<span></span><a href="#/standings' + yq + '?tab=chances">Every title chance and where they finish →</a>' }) +
    (finished ? PD.card('The title race', 'Points after every round.', PD.chartBox('st-prog', 400, 'Championship points by round'), { span: 8, right: PD.seg('st-prog-k', [['drivers', 'Drivers'], ['constructors', 'Constructors']], 'drivers', 'Progression') }) : '') +
    PD.card('Constructors’ championship', '', '<div id="st-c"></div>', { span: finished ? 4 : 12, flush: true }), 'pd-mt');
  h += '<div id="st-fight"></div><div id="st-shape"></div><div id="st-prof"></div>' +
    '<p class="qk-caption pd-ov-doing"><a class="qk-link" href="#/scout?view=leaders' + (season.year !== PD.currentSeason() && season.year >= 2018 ? '&s=' + season.year : '') + '">Who leads the grid, metric by metric →</a> The top and bottom drivers on every key number are in the Scouting Room’s Leaders; the teams’ are on <a class="qk-link" href="#/constructors' + yq + '">Constructors</a>.</p>';
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
  if (finished) {
    recap(season);
    var prog = function (kind) { PD.v2.pointsForecast('st-prog', season, kind, kind === 'drivers' ? 10 : 11); };
    prog('drivers');
    PD.wireSeg(document, 'st-prog-k', prog);
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
      PD.card('What the next rounds mean', cond ? 'For the leader, ' + PD.driverLink(cond.driver, { dot: false }) + ': our chance of winning each remaining round, and of the title if the leader does or does not.' : 'Conditional chances for the championship leader.', '<div id="od-cond"></div>', { span: 6, flush: true }) +
      PD.card('What they need', 'Pick a challenger and the next round’s finishes: the points, the gap, and whether the title is settled by arithmetic.', '<div id="st-calc"></div>', { span: 12 }) +
      PD.card('Where they finish', 'Our chance of each championship position: the share of simulated seasons ending in each place.', PD.chartBox('st-pd', 500), { span: 12 })) + '</section>';
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
    var c = ch[kind] || {};
    var order = ((season.standings || {})[kind] || []).map(function (r) { return isD ? r.driver : r.team; }).filter(function (id) { return c[id]; });
    Object.keys(c).forEach(function (id) { if (order.indexOf(id) < 0) order.push(id); });
    PD.ch.posHeat('st-pd', order.map(function (id) { return { label: isD ? PD.driverName(id) : PD.teamName(id), dist: c[id].pos_dist || [] }; }), { xName: 'Championship position', yName: isD ? 'Driver' : 'Constructor' });
    var rows = PD.v2.chanceRows(ids, function (id) { return ch[kind][id].p_title; }, isD, null, function (id) { return ch[kind][id]; });
    rows.forEach(function (r, i) { var c = ch[kind][ids[i]]; r.sub = 'exp. ' + PD.num(c.exp_points, 0) + ' pts'; });
    PD.set('od-t', QK.chances(rows, { max: 1, oursName: 'Our title chance' }) + (Object.keys(ch[kind] || {}).some(function (id) { return ch[kind][id].eliminated; }) ? '<p class="pd-cap">Out of contention: ' + Object.keys(ch[kind]).filter(function (id) { return ch[kind][id].eliminated; }).map(function (id) { return isD ? PD.driverLink(id, { dot: false }) : PD.teamLink(id, { dot: false }); }).join(', ') + '.</p>' : ''));
  };
  draw('drivers');
  PD.wireSeg(document, 'od-k', draw);
  calculator(season);
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

/* The title-scenario calculator (round 9, Phase 4): "what X needs". The leader against a challenger still in it; pick
   each one's finish at the next round (and the sprint when the round has one): the points after it, the gap, the points
   still available, and the verdict by arithmetic (the magic-number rule: a lead larger than everything left is a clinch;
   level on points goes to countback, which this ignores, so a tie is called open). Points from championship.points_system;
   the fastest-lap point where the season awards it is ignored. */
function calculator(season) {
  var host = document.getElementById('st-calc');
  var ch = season.championship;
  if (!host || !ch) return;
  var st = (season.standings || {}).drivers || [];
  var cd = ch.drivers || {};
  var alive = st.filter(function (r) { return cd[r.driver] && !cd[r.driver].eliminated; });
  if (alive.length < 2) { host.innerHTML = PD.muted('Only one driver can still win the title.'); return; }
  var ps = ch.points_system || {}, race = ps.race || [], spr = ps.sprint || [];
  var rem = ch.remaining || [];
  var next = rem.length ? rem[0][0] : null;
  var nextHasSprint = rem.some(function (x) { return x[0] === next && x[1] === 'sprint'; });
  var maxLeft = isNum((ch.max_points_left || {}).driver) ? ch.max_points_left.driver : null;
  var cal = {};
  (season.calendar || []).forEach(function (c) { cal[c.round] = c; });
  var leader = alive[0], S = { b: alive[1].driver, la: 1, lb: 2, sa: 1, sb: 2 };
  var posOpts = function (cur) { var h = ''; for (var i = 1; i <= 20; i++) h += '<option value="' + i + '"' + (i === cur ? ' selected' : '') + '>P' + i + '</option>'; return h + '<option value="0"' + (cur === 0 ? ' selected' : '') + '>No points / DNF</option>'; };
  var pts = function (arr, p) { return p >= 1 && p <= arr.length ? arr[p - 1] : 0; };
  var name = function (d) { return PD.driverSurname(d); };
  function draw() {
    var a = leader.driver, b = S.b, ra = st.filter(function (r) { return r.driver === a; })[0], rb = st.filter(function (r) { return r.driver === b; })[0];
    var addA = pts(race, S.la) + (nextHasSprint ? pts(spr, S.sa) : 0), addB = pts(race, S.lb) + (nextHasSprint ? pts(spr, S.sb) : 0);
    var thisRound = (race[0] || 0) + (nextHasSprint ? (spr[0] || 0) : 0);
    var after = isNum(maxLeft) ? Math.max(0, maxLeft - thisRound) : null;
    var pa = ra.points + addA, pb = rb.points + addB, gap = pa - pb;
    var roundsAfter = rem.filter(function (x) { return x[1] === 'race' && x[0] !== next; }).length;
    var verdict;
    if (!isNum(after)) verdict = '';
    else if (gap > after) verdict = '<b>' + esc(PD.driverName(a)) + ' is champion</b>: a lead of ' + PD.pts(gap) + ' with only ' + PD.pts(after) + ' points left for anyone.';
    else if (-gap > after) verdict = '<b>' + esc(PD.driverName(b)) + ' is champion</b>: a lead of ' + PD.pts(-gap) + ' with only ' + PD.pts(after) + ' points left.';
    else if (gap > 0) verdict = esc(name(b)) + ' is ' + PD.pts(gap) + ' behind with ' + PD.pts(after) + ' points left over ' + roundsAfter + ' race' + (roundsAfter === 1 ? '' : 's') + ': ' + esc(name(b)) + ' needs to outscore ' + esc(name(a)) + ' by about ' + PD.num(gap / Math.max(1, roundsAfter), 1) + ' points a race. ' + esc(name(a)) + '’s magic number would be ' + PD.pts(after - gap + 1) + ' (the points ' + esc(name(a)) + ' still has to score, or ' + esc(name(b)) + ' to miss, to settle it against ' + esc(name(b)) + ').';
    else if (gap < 0) verdict = esc(name(b)) + ' would lead by ' + PD.pts(-gap) + ' with ' + PD.pts(after) + ' points left: the title stays open.';
    else verdict = 'Level on points with ' + PD.pts(after) + ' left: the title stays open.';
    var nm = next && cal[next] ? PD.shortRace(cal[next].name) : 'the next round';
    var opts = alive.slice(1).map(function (r) { return '<option value="' + esc(r.driver) + '"' + (r.driver === b ? ' selected' : '') + '>' + esc(PD.driverName(r.driver)) + ' (' + PD.pts(r.points) + ')</option>'; }).join('');
    host.innerHTML = QK.scoutBar([
      { label: 'Challenger', html: '<select class="qk-select" id="sc-b">' + opts + '</select>' },
      { label: name(a) + ' at ' + nm, html: '<select class="qk-select" id="sc-la">' + posOpts(S.la) + '</select>' },
      { label: name(b) + ' at ' + nm, html: '<select class="qk-select" id="sc-lb">' + posOpts(S.lb) + '</select>' }
    ].concat(nextHasSprint ? [{ label: name(a) + ' sprint', html: '<select class="qk-select" id="sc-sa">' + posOpts(S.sa) + '</select>' }, { label: name(b) + ' sprint', html: '<select class="qk-select" id="sc-sb">' + posOpts(S.sb) + '</select>' }] : [])) +
      '<div class="pd-mt">' + PD.kpis([
        PD.kpi(name(a) + ' after ' + nm, PD.pts(pa), PD.pts(ra.points) + ' + ' + PD.pts(addA)),
        PD.kpi(name(b) + ' after ' + nm, PD.pts(pb), PD.pts(rb.points) + ' + ' + PD.pts(addB)),
        PD.kpi('The gap', (gap >= 0 ? name(a) : name(b)) + ' +' + PD.pts(Math.abs(gap)), 'points', { text: true }),
        PD.kpi('Points left after it', isNum(after) ? PD.pts(after) : '—', roundsAfter + ' race' + (roundsAfter === 1 ? '' : 's') + (rem.some(function (x) { return x[1] === 'sprint' && x[0] !== next; }) ? ' and sprints' : ''))
      ]) + '</div>' + (verdict ? QK.explain(verdict + ' Our simulated seasons give ' + esc(name(a)) + ' ' + PD.titlePct(cd[a], 1) + ' and ' + esc(name(b)) + ' ' + PD.titlePct(cd[b], 1) + ' as things stand.', { title: 'What it means.' }) : '');
    var $ = function (id) { return document.getElementById(id); };
    $('sc-b').onchange = function (e) { S.b = e.target.value; draw(); };
    $('sc-la').onchange = function (e) { S.la = parseInt(e.target.value, 10); draw(); };
    $('sc-lb').onchange = function (e) { S.lb = parseInt(e.target.value, 10); draw(); };
    if ($('sc-sa')) $('sc-sa').onchange = function (e) { S.sa = parseInt(e.target.value, 10); draw(); };
    if ($('sc-sb')) $('sc-sb').onchange = function (e) { S.sb = parseInt(e.target.value, 10); draw(); };
  }
  draw();
}

// ── car v driver ──────────────────────────────────────────────────────────

/* Car v driver (round 9: drawn on Value › Driver value; Standings ?tab=pace redirects there): PD.carDriver(host, season) */
function pace(season, host) {
  var cp = season.car_pace || {};
  var anyPace = Object.keys(cp).some(function (k) { return Object.keys(cp[k] || {}).length; });
  var h = '<div class="pd-mt">' + PD.note('Our lap-time model splits every lap into the <b>car</b> and the <b>driver</b>. Pace is a share of a lap: 0.5% is about 0.45 seconds on a 90-second lap. The driver part is measured against the team-mate, so the car is taken out.') + '</div>' + PD.grid(
    PD.card('Car pace by race', 'Each car’s pace as a % of a lap against the field from the lap-time model; negative (blue) is faster.', PD.chartBox('cp-heat', 360), { span: 12, right: anyPace ? PD.seg('cp-k', [['race', 'Race'], ['quali', 'Qualifying']], 'race', 'Session') : '' }) +
    PD.card('Car pace through the season', 'Same numbers as lines; up is faster.', PD.chartBox('cp-lines', 380), { span: 12 }) +
    PD.card('Driver effects', 'Pace against the car, % of a lap with a 95% interval; left is faster.', PD.chartBox('cp-eff', 560), { span: 6, right: anyPace ? PD.seg('cp-ek', [['race', 'Race'], ['quali', 'Qualifying']], 'race', 'Session') : '' }) +
    PD.card('Car and driver', 'Each team’s points split into what the car would score with average drivers and what its drivers added.', PD.chartBox('cp-split', 420), { span: 6 }) +
    PD.card('Elo', 'Driver ratings after the latest round: field, against the team-mate only, and in qualifying.', '<div id="cp-elo"></div>', { span: 12, flush: true }), 'pd-mt');
  if (typeof host === 'string') PD.set(host, h); else host.innerHTML = h;
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

PD.carDriver = function (host, season) { return pace(season, host); };

// ── a finished season's recap (round 9) ───────────────────────────────────

/* The champion in the constructor's colour, the constructors' champion, then "our calls against what happened": the
   walk-forward race forecasts of the season (calibration.json per_race, 2014 on: our chance for the eventual winner
   before each race, after qualifying where it exists), the average and the biggest surprise. Pre-season title calls
   were not stored before 2026, and the page says so. */
function recap(season) {
  var host = document.getElementById('st-recap');
  if (!host) return;
  var y = season.year, sd = (season.standings || {}).drivers || [], sc = (season.standings || {}).constructors || [];
  var c = sd[0], k = sc[0];
  if (!c) return;
  var bk = QK.color.block(PD.teamColourRaw(c.team));
  host.innerHTML = '<section class="qk-section pd-sec" style="margin-top:0">' + QK.sectionHead({ kicker: 'How ' + y + ' finished', title: 'The ' + y + ' season, in one look' }) +
    '<a class="pd-champ" href="' + PD.driverHref(c.driver, y) + '" style="--tb:' + esc(bk.bg) + (bk.edge ? ';--te:' + esc(bk.edge) : '') + '"><span class="k">' + y + ' World Champion</span><b>' + esc(PD.driverName(c.driver)) + '</b>' +
    '<span class="s">' + esc(PD.teamName(c.team)) + ' · ' + PD.pts(c.points) + ' points · ' + (c.wins || 0) + ' win' + (c.wins === 1 ? '' : 's') + (sd[1] ? ' · ' + PD.pts(c.points - sd[1].points) + ' clear of ' + esc(PD.driverName(sd[1].driver)) : '') + '</span></a>' +
    (k ? '<p class="pd-cap">Constructors’ champion: <a class="qk-link" href="' + PD.teamHref(k.team, y) + '">' + esc(PD.teamName(k.team)) + '</a>, ' + PD.pts(k.points) + ' points' + (sc[1] ? ', ' + PD.pts(k.points - sc[1].points) + ' clear of ' + esc(PD.teamName(sc[1].team)) : '') + '.</p>' : '') +
    '<div id="st-calls"></div></section>';
  PD.load('calibration.json').then(function (cal) {
    var box = document.getElementById('st-calls');
    if (!box) return;
    var pr = ((cal || {}).per_race || []).filter(function (r) { return r.year === y; }).sort(function (a, b) { return a.round - b.round; });
    var pw = function (r) { var p = r.p_winner || {}; return isNum(p.model_post) ? p.model_post : p.model_pre; };
    pr = pr.filter(function (r) { return isNum(pw(r)); });
    if (!pr.length) { box.innerHTML = PD.muted('Our walk-forward race forecasts start in 2014, so there are no calls to set against ' + y + '.'); return; }
    var avg = PD.mean(pr.map(pw)), low = pr.slice().sort(function (a, b) { return pw(a) - pw(b); })[0], high = pr.slice().sort(function (a, b) { return pw(b) - pw(a); })[0];
    var strong = pr.filter(function (r) { return pw(r) >= 0.3; }).length;
    box.innerHTML = PD.kpis([
      PD.kpi('Races called', String(pr.length), 'each forecast made before the race, from what was known then'),
      PD.kpi('Our chance for the winner', PD.pct(avg, 0), 'on average; twenty cars share 100%', { signal: true }),
      PD.kpi('Won as a clear pick', strong + ' of ' + pr.length, 'winners we gave 30% or more'),
      PD.kpi('Biggest surprise', esc(PD.driverSurname(low.winner)) + ' ' + PD.pct(pw(low), 0), esc(PD.shortRace(low.name)) + ': our chance before the race', { text: true })
    ]) + PD.grid(PD.card('Our chance for each race’s winner', 'Before the race (after qualifying where we had it), round by round; taller is a winner we saw coming. ' + esc(PD.driverName(high.winner)) + ' at ' + esc(PD.shortRace(high.name)) + ' was our most confident call (' + PD.pct(pw(high), 0) + ').',
      PD.chartBox('st-calls-c', 300, 'Our chance for each race winner'), { span: 12 }), 'pd-mt') +
      '<p class="pd-cap">Our pre-season and mid-season title chances were not stored before 2026, so a title call cannot be checked for ' + y + '; the race calls are the walk-forward backtest on <a class="qk-link" href="#/calibration">How we’re doing</a>.</p>';
    PD.ch.columns('st-calls-c', { cats: pr.map(function (r) { return 'R' + r.round; }), xName: 'Round', yName: 'Our chance for the winner', yMin: 0, fmt: function (v) { return Math.round(v * 100) + '%'; },
      series: [{ name: 'Our chance for the winner', data: pr.map(pw), colours: pr.map(function (r) { return PD.teamColour(((season.calendar || []).filter(function (cc) { return cc.round === r.round; })[0] || {}).winner_team || PD.driverTeam(r.winner)); }), fmt: function (v) { return PD.pct(v, 0); } }],
      tipLabel: function (i) { return PD.shortRace(pr[i].name) + ': ' + PD.driverName(pr[i].winner) + ' won'; }, label: 'Our chance for each race winner' });
  });
}

// ── history ───────────────────────────────────────────────────────────────

/* Every champion since 1950 from index.json seasons_meta (drivers from 1950, constructors from 1958): the champions
   year by year, the most titles, the dynasties (unbroken runs of titles) and how long each of today's teams has waited. */
var OLD_TEAMS = { brm: 'BRM', 'brabham-repco': 'Brabham-Repco', 'cooper-climax': 'Cooper-Climax', 'lotus-climax': 'Lotus-Climax', 'lotus-ford': 'Lotus-Ford', 'matra-ford': 'Matra-Ford', team_lotus: 'Team Lotus', vanwall: 'Vanwall' };
function tName(id) { return OLD_TEAMS[id] || PD.teamName(id); }
function history(el) {
  return PD.load('elo.json').then(function () {
    if (!PD.alive(el)) return;
    var meta = (PD.index() || {}).seasons_meta || {};
    var years = Object.keys(meta).map(Number).filter(function (y) { var m = meta[y]; return m && m.completed && m.completed >= m.rounds; }).sort(function (a, b) { return b - a; });
    if (!years.length) { PD.set('st-body', PD.muted('No finished seasons in the index.')); return; }
    var count = function (key) {
      var n = {}, last = {}, first = {};
      years.forEach(function (y) { var c = meta[y][key]; if (!c) return; n[c] = (n[c] || 0) + 1; last[c] = Math.max(last[c] || 0, y); first[c] = Math.min(first[c] || 9999, y); });
      return Object.keys(n).sort(function (a, b) { return n[b] - n[a] || last[b] - last[a]; }).map(function (k) { return { id: k, n: n[k], last: last[k], first: first[k], years: years.filter(function (y) { return meta[y][key] === k; }).sort() }; });
    };
    var streaks = function (key) {
      var asc = years.slice().sort(function (a, b) { return a - b; }), out = [], cur = null;
      asc.forEach(function (y) {
        var c = meta[y][key];
        if (cur && c === cur.id && y === cur.to + 1) { cur.to = y; cur.n++; }
        else { if (cur && cur.n >= 2) out.push(cur); cur = c ? { id: c, from: y, to: y, n: 1 } : null; }
      });
      if (cur && cur.n >= 2) out.push(cur);
      return out.sort(function (a, b) { return b.n - a.n || b.to - a.to; });
    };
    var D = count('champion'), C = count('constructors_champion'), sD = streaks('champion'), sC = streaks('constructors_champion');
    var tcol = function (t) { return PD.teamColourRaw(t) || null; };
    var tile = function (y, t, label) { var bk = QK.color.block(tcol(t)); return '<a class="pd-hy" href="#/standings/' + y + '" title="' + esc(y + ': ' + label) + '" style="background:' + bk.bg + (bk.edge ? ';box-shadow:inset 0 -4px 0 ' + bk.edge : '') + '">' + String(y).slice(2) + '</a>'; };
    var dyn = function (list, isD) {
      return '<div class="pd-dyn">' + list.slice(0, 12).map(function (r) {
        var nm = isD ? PD.driverName(r.id) : tName(r.id);
        return '<div class="pd-dyn-row"><span class="nm">' + (isD ? PD.driverLink(r.id, { name: nm, dot: false, y: r.last }) : '<a href="' + PD.teamHref(r.id, r.last) + '">' + esc(nm) + '</a>') + '</span><b class="n num">' + r.n + '</b><span class="bl">' +
          r.years.map(function (y) { return tile(y, isD ? null : r.id, nm); }).join('') + '</span></div>';
      }).join('') + '</div>';
    };
    var cur = (PD.index() || {}).teams || {};
    var waits = Object.keys(cur).map(function (t) { var hit = C.filter(function (r) { return r.id === t; })[0]; return { id: t, last: hit ? hit.last : null, n: hit ? hit.n : 0 }; })
      .sort(function (a, b) { return (a.last || 0) - (b.last || 0); });
    var y0 = years[years.length - 1], latest = years[0];
    var h = PD.kpis([
      PD.kpi('Champions crowned', String(years.length), y0 + ' to ' + latest),
      PD.kpi('Most drivers’ titles', D[0] ? esc(PD.driverSurname(D[0].id)) + ' ' + D[0].n : '—', D[1] && D[1].n === D[0].n ? 'level with ' + esc(PD.driverName(D[1].id)) : '', { text: true }),
      PD.kpi('Most constructors’ titles', C[0] ? esc(tName(C[0].id)) + ' ' + C[0].n : '—', 'since 1958', { text: true }),
      PD.kpi('Longest run', sD[0] ? esc(PD.driverSurname(sD[0].id)) + ' ' + sD[0].n : '—', sD[0] ? sD[0].from + '–' + sD[0].to + ' in a row' : '', { text: true })
    ]) +
      '<section class="qk-section pd-sec">' + PD.secHead('Dynasties', 'Who won the most', 'Every title, one block per season (the constructors’ blocks in the team colour where we have it). Tap a block for that season.') +
      PD.grid(PD.card('Drivers’ titles', '', dyn(D, true), { span: 6 }) + PD.card('Constructors’ titles', '', dyn(C, false), { span: 6 })) + '</section>' +
      '<section class="qk-section pd-sec">' + PD.secHead('Records', 'Runs and waits', 'Unbroken runs of titles, and how long each of today’s teams has waited since its last constructors’ title.') +
      PD.grid(PD.card('The longest runs', 'Back-to-back titles.', '<div id="hy-runs"></div>', { span: 6, flush: true }) + PD.card('The wait', 'Today’s teams, longest wait first.', '<div id="hy-wait"></div>', { span: 6, flush: true })) + '</section>' +
      '<section class="qk-section pd-sec">' + PD.secHead('Every champion', 'Season by season', 'The drivers’ and constructors’ champions of every finished season; tap a year for its standings.') + PD.card('', '', '<div id="hy-all"></div>', { flush: true }) + '</section>';
    PD.set('st-body', h);
    PD.table('hy-runs', [
      { key: 'who', label: 'Champion', sticky: true, sort: false, fmt: function (v, r) { return r.isD ? PD.driverLink(r.id, { dot: false, y: r.to }) : '<a class="pd-link" href="' + PD.teamHref(r.id, r.to) + '">' + esc(tName(r.id)) + '</a>'; } },
      { key: 'kind', label: 'Title' }, { key: 'n', label: 'In a row', num: true }, { key: 'span', label: 'Seasons', sort: false }
    ], sD.map(function (r) { return Object.assign({ isD: true, kind: 'Drivers', span: r.from + '–' + r.to }, r); }).concat(sC.map(function (r) { return Object.assign({ isD: false, kind: 'Constructors', span: r.from + '–' + r.to }, r); }))
      .sort(function (a, b) { return b.n - a.n || b.to - a.to; }).slice(0, 12), { sort: null });
    PD.table('hy-wait', [
      { key: 'id', label: 'Team', sticky: true, fmt: function (v) { return PD.teamLink(v); } },
      { key: 'last', label: 'Last title', num: true, fmt: function (v) { return isNum(v) ? String(v) : 'never'; } },
      { key: 'wait', label: 'Seasons since', num: true, fmt: function (v) { return isNum(v) ? String(v) : '—'; } },
      { key: 'n', label: 'Titles', num: true }
    ], waits.map(function (r) { return Object.assign({ wait: isNum(r.last) ? latest - r.last : null }, r); }), { sort: null });
    PD.table('hy-all', [
      { key: 'y', label: 'Season', num: true, fmt: function (v) { return '<a class="pd-link" href="#/standings/' + v + '">' + v + '</a>'; } },
      { key: 'd', label: 'Drivers’ champion', fmt: function (v, r) { return v ? PD.driverLink(v, { dot: false, y: r.y }) : '—'; } },
      { key: 'c', label: 'Constructors’ champion', fmt: function (v, r) { return v ? '<a class="pd-link" href="' + PD.teamHref(v, r.y) + '">' + esc(tName(v)) + '</a>' : '<span class="qk-muted">not yet awarded</span>'; } },
      { key: 'rounds', label: 'Rounds', num: true }
    ], years.map(function (y) { return { y: y, d: meta[y].champion, c: meta[y].constructors_champion, rounds: meta[y].rounds }; }), { sort: { key: 'y', dir: 'desc' }, maxHeight: 640 });
  });
}

PD.route('standings', render);
})(window.PD);
