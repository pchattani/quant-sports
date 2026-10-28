/* The Quant Paddock — the championship fights on the Standings page (PD.fight), round 5 (24 Oct 2026).
 *
 *   PD.fight.load(y)               drivers.json, teams.json and circuits.json for the season (each may be null)
 *   PD.fight.race(el, season, ex)  "How the fights are shaping up": where it stands (clinch and elimination arithmetic
 *                                  from the points system and the rounds left), what is at stake at the next Grand Prix
 *                                  (season.json championship.conditional.next_round.fights: the same simulated
 *                                  seasons split by a podium there or not), the fights for each place (pos_dist),
 *                                  who moved at the last round and why (points against our pre-race forecast,
 *                                  championship places, the title_history snapshots), points against our forecast
 *                                  through the season, and the run-in (circuits, our expected points per round)
 *   PD.fight.shape(el, season, ex) "The shape of the grid": constructor tiers from car pace, car v driver (quadrant),
 *                                  team-mate battles
 *   PD.fight.profiles(el, season, ex)  strengths and weak spots: one expandable row per driver and per constructor,
 *                                  plain-English chips from the F1 metric set's percentiles (docs/_design/metrics/f1.json)
 *   PD.fight.chips(ex, id)         the chips for one driver (the standings table's Profile column)
 *
 * Everything is computed from payloads the site already writes; nothing here is a forecast of its own. The clinch
 * lines ignore countback, so "by N or more" is always enough on its own (the magic-number rule).
 * Older-browser rule: no optional chaining, no nullish coalescing. */
(function (PD) {
'use strict';

var esc = PD.esc, isNum = PD.isNum;
var F = PD.fight = {};
var DEFAULT_PS = { race: [25, 18, 15, 12, 10, 8, 6, 4, 2, 1], sprint: [8, 7, 6, 5, 4, 3, 2, 1], fastest_lap: false };
var TIER_NAMES = ['Front of the grid', 'Best of the rest', 'Midfield', 'Back of the grid'];

F.load = function (y) {
  var opt = function (p) { return PD.load(p).then(function (d) { return PD.ok(d) ? d : null; }, function () { return null; }); };
  return Promise.all([opt(y + '/drivers.json'), opt(y + '/teams.json'), opt(y + '/circuits.json')]).then(function (a) {
    return { drivers: a[0], teams: a[1], circuits: a[2] };
  });
};

// ── small helpers ─────────────────────────────────────────────────────────

function nameOf(kind, id) { return kind === 'drivers' ? PD.driverName(id) : PD.teamName(id); }
function surname(kind, id) { return kind === 'drivers' ? PD.driverSurname(id) : PD.teamName(id); }
function linkOf(kind, id, o) { return kind === 'drivers' ? PD.driverLink(id, o) : PD.teamLink(id, o); }
function colourOf(kind, id) { return PD.teamColour(kind === 'drivers' ? PD.driverTeam(id) : id); }
function plural(n, w) { return n + ' ' + w + (n === 1 ? '' : 's'); }
function standOrder(season, kind) { return ((season.standings || {})[kind] || []).map(function (r) { return kind === 'drivers' ? r.driver : r.team; }); }
function standPoints(season, kind) { var o = {}; ((season.standings || {})[kind] || []).forEach(function (r) { o[kind === 'drivers' ? r.driver : r.team] = r.points; }); return o; }
function shortName(c) { return c ? PD.shortRace(c.name) : ''; }
function calBy(season) { var o = {}; (season.calendar || []).forEach(function (c) { o[c.round] = c; }); return o; }
function pp(v) { return PD.num(v * 100, 0) + ' pts'; }
function pctTxt(p) { return PD.pct(p, p > 0 && p < 0.01 ? 1 : 0); }

/* points one entrant can still take from one event: a driver the winner's score (plus a fastest-lap point where the
   season awards it), a constructor the first two places */
function eventMax(ps, ev, team) {
  var r = ps.race || DEFAULT_PS.race, s = ps.sprint || [];
  if (ev === 'sprint') return team ? (s[0] || 0) + (s[1] || 0) : (s[0] || 0);
  return team ? r[0] + r[1] + (ps.fastest_lap ? 1 : 0) : r[0] + (ps.fastest_lap ? 1 : 0);
}
/* the rounds still to run as [{round, max}] in calendar order, from championship.remaining ([[round, "race"|"sprint"]]) */
function runIn(ch, team) {
  var ps = ch.points_system || DEFAULT_PS, by = {}, order = [];
  (ch.remaining || []).forEach(function (x) {
    var r = +x[0];
    if (!by[r]) { by[r] = { round: r, max: 0, sprint: false }; order.push(r); }
    by[r].max += eventMax(ps, x[1], team);
    if (x[1] === 'sprint') by[r].sprint = true;
  });
  order.sort(function (a, b) { return a - b; });
  return order.map(function (r) { return by[r]; });
}

// ── 1. how the fights are shaping up ──────────────────────────────────────

/* The clinch and elimination lines for one championship (drivers | constructors). Pure arithmetic, no simulation. */
F.stakesText = function (season, kind) {
  var ch = season.championship, c = ch ? ch[kind] || {} : {};
  var order = standOrder(season, kind), P = standPoints(season, kind), team = kind === 'constructors';
  var rounds = runIn(ch || {}, team), cal = calBy(season);
  if (!ch || !order.length || !rounds.length) return [];
  var M = rounds.reduce(function (a, r) { return a + r.max; }, 0);
  var L = order[0], lead = P[L];
  var rivals = order.slice(1).filter(function (id) { return isNum(P[id]) && P[id] + M >= lead; });
  var out = [];
  var nx = rounds[0], Mrest = M - nx.max, nxName = (cal[nx.round] || {}).name || ('round ' + nx.round);
  var gp = rounds.length, spr = rounds.filter(function (r) { return r.sprint; }).length;
  if (!rivals.length) {
    out.push('<b>' + linkOf(kind, L, { dot: false }) + '</b> ' + (team ? 'have' : 'has') + ' the title sewn up: nobody can reach ' + PD.pts(lead) + ' points with ' + PD.pts(M) + ' still to win.');
    return out;
  }
  var R = rivals[0];
  out.push('<b>' + linkOf(kind, L, { dot: false }) + '</b> lead' + (team ? '' : 's') + ' ' + linkOf(kind, R, { dot: false }) + ' by <b>' + PD.pts(lead - P[R]) + '</b> with <b>' + PD.pts(M) + '</b> points still to win in ' +
    plural(gp, 'Grand Prix').replace('Grand Prixs', 'Grands Prix') + (spr ? ' and ' + plural(spr, 'sprint') : '') + '. ' +
    (rivals.length === 1 ? 'Only ' + esc(surname(kind, R)) + ' can still catch ' + (team ? 'them' : 'the leader') + '.' : plural(rivals.length, team ? 'team' : 'driver') + ' can still catch ' + (team ? 'them' : 'the leader') + '.'));
  /* clinch at the next round: over every rival r, the leader must outscore r there by n_r = Mrest - gap_r + 1 (or more);
     possible only when the largest n_r is at most the next round's maximum */
  var need = rivals.map(function (id) { return { id: id, n: Mrest - (lead - P[id]) + 1 }; }).sort(function (a, b) { return b.n - a.n; });
  if (need[0].n <= nx.max) {
    var binding = need.filter(function (x) { return x.n > -nx.max; }).slice(0, 3);
    out.push(esc(surname(kind, L)) + ' ' + (team ? 'are' : 'is') + ' champion' + (team ? 's' : '') + ' at the <b>' + esc(nxName) + '</b> by ' + binding.map(function (x) {
      return x.n > 0 ? 'outscoring ' + esc(surname(kind, x.id)) + ' by ' + PD.pts(x.n) + ' or more' : 'finishing no more than ' + PD.pts(-x.n) + ' behind ' + esc(surname(kind, x.id));
    }).join(' and ') + ' there.');
  } else {
    /* the earliest round the leader could clinch, scoring the maximum while the closest rival scores nothing */
    var gapMin = lead - P[R], cum = 0, when = null;
    for (var i = 0; i < rounds.length; i++) { cum += rounds[i].max; if (gapMin + cum >= M - cum + 1) { when = rounds[i]; break; } }
    out.push('It cannot be settled at the ' + esc(nxName) + ': the earliest ' + esc(surname(kind, L)) + ' could clinch is ' + (when ? 'the <b>' + esc((cal[when.round] || {}).name || 'round ' + when.round) + '</b> (round ' + when.round + ')' : 'the last round') + ', and only with a perfect run.');
  }
  rivals.slice(0, 3).forEach(function (id) {
    var gap = lead - P[id], n = Mrest - gap + 1, per = gap / gp;
    var line = '<b>' + linkOf(kind, id, { dot: false }) + '</b>: ' + PD.pts(gap) + ' behind, ' + PD.pts(P[id] + M) + ' at most. ';
    line += n <= nx.max ? 'Out at the ' + esc(nxName) + ' if ' + esc(surname(kind, L)) + ' outscore' + (team ? '' : 's') + ' them by ' + PD.pts(Math.max(1, n)) + ' or more there. ' : 'Cannot be knocked out at the ' + esc(nxName) + '. ';
    line += 'Needs about ' + PD.num(per, per < 10 ? 1 : 0) + ' points a round more than ' + esc(surname(kind, L)) + ' from here' + (isNum((c[id] || {}).p_title) ? ' (our title chance ' + PD.titlePct(c[id], c[id].p_title > 0 && c[id].p_title < 0.01 ? 1 : 0) + ').' : '.');
    out.push(line);
  });
  var outN = order.filter(function (id) { return isNum(P[id]) && P[id] + M < lead; }).length;
  if (outN) out.push(plural(outN, team ? 'team' : 'driver') + ' can no longer reach ' + PD.pts(lead) + ' points and ' + (outN === 1 ? 'is' : 'are') + ' out of the title fight.');
  return out;
};

/* The fights for places: our chance of each championship finish (pos_dist) for the entries still in one. */
function placeRows(season, kind) {
  var c = (season.championship || {})[kind] || {};
  return standOrder(season, kind).filter(function (id) { return c[id] && (c[id].pos_dist || []).length; }).map(function (id) {
    var d = c[id].pos_dist, cum = function (k) { var s = 0; for (var i = 0; i < k && i < d.length; i++) s += d[i]; return Math.min(1, s); };
    return { id: id, p1: cum(1), p2: cum(2), p3: cum(3), p5: cum(5), exp: c[id].exp_pos, pts: c[id].current_points, exp_pts: c[id].exp_points };
  }).filter(function (r) { return r.p3 >= 0.005 || r.p1 >= 0.0005; });
}
function placeWord(k, team) { return k === 1 ? 'the title' : k === 2 ? 'a top-two finish' : 'a top-three finish'; }
function placeShort(k) { return k === 1 ? 'Title' : 'Top ' + k; }

/* The next Grand Prix's stakes: championship.conditional.next_round.fights (the same simulated seasons, split by a
   podium at that Grand Prix or not). Rows sorted by the swing. */
function stakeRows(season, kind) {
  var nr = ((season.championship || {}).conditional || {}).next_round || {};
  var f = (nr.fights || {})[kind] || {};
  return Object.keys(f).map(function (id) {
    var r = f[id];
    return { id: id, place: r.place, p: r.p, pod: r.p_podium_next, a: r.p_if_podium, b: r.p_if_not, swing: isNum(r.p_if_podium) && isNum(r.p_if_not) ? r.p_if_podium - r.p_if_not : null };
  }).filter(function (r) { return isNum(r.swing); }).sort(function (x, y) { return y.swing - x.swing; });
}

/* Since the last round: each driver's result, points against our pre-race forecast (drivers.json log exp_points: the
   walk-forward forecast made before that race) and the championship places gained, plus the move in our title chance
   and expected final points between the last two title_history snapshots when there are two. */
function moverRows(season, ex) {
  var cat = ex.drivers, last = season.rounds_done;
  if (!cat || !cat.drivers || !last) return [];
  var prog = (season.progression || {}).drivers || {}, rounds = (season.progression || {}).rounds || [];
  var li = rounds.indexOf(last);
  var rankAt = function (i) {
    if (i < 0) return {};
    var ids = Object.keys(prog).filter(function (id) { return isNum(prog[id][i]); }).sort(function (a, b) { return prog[b][i] - prog[a][i]; });
    var o = {}; ids.forEach(function (id, k) { o[id] = k + 1; }); return o;
  };
  var now = rankAt(li), before = rankAt(li - 1);
  var H = (season.title_history || []).filter(function (h) { return h && !h.final && h.drivers; }).sort(function (a, b) { return a.after_round - b.after_round; });
  var h1 = H.length >= 2 ? H[H.length - 1] : null, h0 = H.length >= 2 ? H[H.length - 2] : null;
  var rows = [];
  Object.keys(cat.drivers).forEach(function (id) {
    var d = cat.drivers[id], lg = (d.log || []).filter(function (l) { return l.round === last; })[0];
    if (!lg) return;
    var row = { id: id, team: lg.team || d.team, pos: lg.pos, grid: lg.grid, status: lg.status, points: lg.points, race_points: lg.race_points, exp: lg.exp_points,
      vs: isNum(lg.race_points) && isNum(lg.exp_points) ? lg.race_points - lg.exp_points : null, now: now[id], before: before[id] };
    row.moved = isNum(row.now) && isNum(row.before) ? row.before - row.now : null;
    if (h0 && h1 && h0.drivers[id] && h1.drivers[id]) {
      row.dp = isNum(h1.drivers[id].p_title) && isNum(h0.drivers[id].p_title) ? h1.drivers[id].p_title - h0.drivers[id].p_title : null;
      row.dpts = isNum(h1.drivers[id].exp_points) && isNum(h0.drivers[id].exp_points) ? h1.drivers[id].exp_points - h0.drivers[id].exp_points : null;
    }
    rows.push(row);
  });
  return rows;
}
function resultWords(r) {
  if (!isNum(r.pos)) return 'Did not start';
  var fin = PD.finished(r.status);
  var g = isNum(r.grid) && r.grid > 0 ? (r.grid === r.pos && fin ? ' from P' + r.grid + ' on the grid' : ' from P' + r.grid) : ' from the pit lane';
  if (!fin) return (/disq/i.test(r.status || '') ? 'Disqualified' : 'Retired' + (r.status && r.status !== 'Retired' ? ' (' + r.status + ')' : '')) + g;
  return (r.pos === 1 ? 'Won' : 'P' + r.pos) + g;
}

F.race = function (el, season, ex) {
  var node = typeof el === 'string' ? document.getElementById(el) : el;
  var ch = season.championship;
  if (!node || !ch) return;
  var cal = calBy(season), rounds = runIn(ch, false), nx = rounds.length ? cal[rounds[0].round] : null;
  var nxName = nx ? nx.name : '';
  var H = (season.title_history || []).filter(function (h) { return h && !h.final && h.drivers; }).sort(function (a, b) { return a.after_round - b.after_round; });
  var since = H.length ? 'Tracking since ' + PD.fmtDate(H[0].as_of, { year: false }) + ' (after round ' + H[0].after_round + ')' : 'Tracking starts with the next simulation';
  var lastC = cal[season.rounds_done];
  var h = '<section class="qk-section pd-sec">' + PD.secHead('How it’s shaping up', 'The fights, round by round', 'Who can still win, what the next Grand Prix decides, and who is up or down on our forecasts. Clinch lines are exact arithmetic on the points still to win; chances come from our ' + PD.int(ch.n_sims) + ' simulated seasons.',
    PD.seg('fx-k', [['drivers', 'Drivers'], ['constructors', 'Constructors']], 'drivers', 'Championship')) +
    PD.grid(
      PD.card('Where it stands', 'What each contender needs. “By N or more” is enough whatever the countback.', '<ul class="fx-lines" id="fx-lines"></ul>', { span: 6 }) +
      PD.card('What’s at stake next', 'The same simulated seasons split by a podium at ' + (nxName ? 'the ' + esc(nxName) : 'the next Grand Prix') + ' or not: the place each one is fighting for, and how a podium moves it.', '<div id="fx-stake"></div>', { span: 6, flush: true }) +
      PD.card('The fights for places', 'Our chance of each final championship place, from the simulated seasons.', '<div id="fx-places"></div>', { span: 12, flush: true }) +
      PD.card('Since ' + (lastC ? 'the ' + esc(shortName(lastC)) + ' Grand Prix' : 'the last round'), 'Each result against our pre-race forecast (the expected points we gave before the start, from data up to that race only), and the championship places it moved.', '<div id="fx-moved"></div>', { span: 12, flush: true }) +
      PD.card('Title chances after each round', esc(since) + '. One snapshot of the simulation is kept after every round; earlier rounds were never stored, so the line starts here.', '<div id="fx-hist" class="qk-chart" style="--h:300px" role="img" aria-label="Title chances after each round"></div>', { span: 6, right: PD.seg('fx-hm', [['p', 'Title chance'], ['pts', 'Points']], 'p', 'Measure') }) +
      PD.card('Points against our forecast', 'Race points minus the expected points we gave before each start, added up through the season. Above zero: more than the pace and the grid suggested, through form, luck or our model missing something.', PD.chartBox('fx-luck', 300, 'Points against our pre-race forecast through the season'), { span: 6 }) +
      PD.card('The run-in', 'Every round left: the track and our expected points there for the front-runners (the championship simulation’s per-round expectation).', '<div id="fx-runin"></div>', { span: 12, flush: true }), 'pd-mt') + '</section>';
  node.innerHTML = h;
  var kind = 'drivers', hm = 'p';
  var draw = function (k) {
    kind = k;
    var lines = F.stakesText(season, k);
    PD.set('fx-lines', lines.length ? lines.map(function (l) { return '<li>' + l + '</li>'; }).join('') : '<li>' + PD.muted('No rounds left to simulate.') + '</li>');
    stakesTable(season, k, nxName);
    placesTable(season, k);
    histChart(season, k, hm);
  };
  draw('drivers');
  PD.wireSeg(node, 'fx-k', draw);
  PD.wireSeg(node, 'fx-hm', function (v) { hm = v; histChart(season, kind, hm); });
  movedTable(season, ex);
  luckChart(season, ex);
  runInTable(season, ex);
};

function histChart(season, kind, mode) {
  var n = document.getElementById('fx-hist');
  if (!n) return;
  n.style.height = '';
  var H = (season.title_history || []).filter(function (h) { return h && !h.final && h[kind]; });
  if (H.length >= 3) { PD.v2.titleHistory(n, season, kind, kind === 'drivers' ? 6 : 5, mode); return; }
  /* fewer than three snapshots: the latest as numbers rather than a near-empty chart */
  if (!H.length) { n.innerHTML = PD.muted('No round has been recorded yet.'); n.style.height = 'auto'; return; }
  var last = H[H.length - 1][kind];
  var ids = Object.keys(last).sort(function (a, b) { return mode === 'pts' ? (last[b].exp_points || 0) - (last[a].exp_points || 0) : ((last[b].p_title || 0) - (last[a].p_title || 0)) || ((last[b].exp_points || 0) - (last[a].exp_points || 0)); }).slice(0, 6);
  n.style.height = 'auto';
  n.innerHTML = '<p class="pd-cap" style="margin:0 0 8px">' + plural(H.length, 'round') + ' on record so far (after round ' + H.map(function (x) { return x.after_round; }).join(', ') + '); the lines draw from the third. The latest:</p>' +
    '<ul class="fx-snap">' + ids.map(function (id) {
      var r = last[id];
      return '<li><span>' + linkOf(kind, id) + '</span><b class="num">' + (mode === 'pts' ? PD.num(r.exp_points, 0) + ' pts' : PD.titlePct(r, 1)) + '</b><small>' + (mode === 'pts' ? PD.num(r.p05, 0) + '–' + PD.num(r.p95, 0) + ' (90% of seasons)' : PD.pts(r.points) + ' pts then') + '</small></li>';
    }).join('') + '</ul>';
}

function stakesTable(season, kind, nxName) {
  var rows = stakeRows(season, kind), team = kind === 'constructors';
  var host = document.getElementById('fx-stake');
  if (!host) return;
  if (!rows.length) {
    var cond = ((season.championship || {}).conditional || {}).next_round;
    host.innerHTML = '<div class="qk-card-body">' + PD.muted(cond && !cond.fights ? 'This view fills in with the next simulation run.' : 'No place is still in the balance at the next Grand Prix: every fight is settled one way or the other in at least 98% of our seasons.') + '</div>';
    return;
  }
  var top = rows[0];
  PD.table(host, [
    { key: 'name', label: team ? 'Team' : 'Driver', sticky: true, fmt: function (v, r) { return linkOf(kind, r.id); } },
    { key: 'place', label: 'Fight', fmt: function (v) { return esc(placeShort(v)); }, tip: 'The championship place most in the balance for them' },
    { key: 'p', label: 'Now', num: true, fmt: function (v) { return pctTxt(v); }, tip: 'Our chance of that place today' },
    { key: 'a', label: 'Podium', num: true, fmt: function (v) { return '<b>' + pctTxt(v) + '</b>'; }, tip: 'Our chance of that place in the seasons where ' + (team ? 'a car' : 'the driver') + ' is on the podium at the next Grand Prix' },
    { key: 'b', label: 'No podium', num: true, fmt: function (v) { return pctTxt(v); }, tip: 'The same chance when ' + (team ? 'neither car is' : 'the driver is not') + ' on the podium there' },
    { key: 'swing', label: 'Swing', num: true, fmt: function (v) { return '<span class="fx-swing" style="--w:' + Math.min(100, Math.round(v * 200)) + '%">' + PD.num(v * 100, 0) + '</span>'; }, tip: 'Percentage points between the two: what the podium is worth' },
    { key: 'pod', label: 'Podium chance', num: true, fmt: function (v) { return pctTxt(v); }, tip: 'Our chance of ' + (team ? 'a car' : 'the driver') + ' on the podium there' }
  ], rows.map(function (r) { return Object.assign({ name: nameOf(kind, r.id) }, r); }), { sort: { key: 'swing', dir: 'desc' } });
  host.insertAdjacentHTML('beforeend', '<p class="pd-cap fx-pad">Biggest swing: <b>' + esc(nameOf(kind, top.id)) + '</b> ' + (team ? 'have' : 'has') + ' ' + esc(placeWord(top.place)) + ' in ' + pctTxt(top.p) + ' of our seasons; ' + pctTxt(top.a) + ' with a podium ' + (nxName ? 'at the ' + esc(nxName) : 'next time out') + ', ' + pctTxt(top.b) + ' without.</p>');
}

function placesTable(season, kind) {
  var rows = placeRows(season, kind), team = kind === 'constructors';
  if (!rows.length) { PD.set('fx-places', '<div class="qk-card-body">' + PD.muted('No simulation for this season.') + '</div>'); return; }
  var bar = function (v, r) { return PD.probBar(v, colourOf(kind, r.id)); };
  PD.table('fx-places', [
    { key: 'name', label: team ? 'Team' : 'Driver', sticky: true, fmt: function (v, r) { return linkOf(kind, r.id); } },
    { key: 'pts', label: 'Pts', num: true, fmt: function (v) { return '<b>' + PD.pts(v) + '</b>'; } },
    { key: 'p1', label: 'Champion', num: true, fmt: bar, tip: 'Our chance of the title' },
    { key: 'p2', label: 'Top 2', num: true, fmt: bar, tip: 'Our chance of finishing first or second' },
    { key: 'p3', label: 'Top 3', num: true, fmt: bar, tip: 'Our chance of a top-three finish' },
    { key: 'exp', label: 'Exp. place', num: true, fmt: function (v) { return PD.num(v, 1); }, tip: 'The average final place over the simulated seasons' },
    { key: 'exp_pts', label: 'Exp. pts', num: true, fmt: function (v) { return PD.num(v, 0); } }
  ], rows.map(function (r) { return Object.assign({ name: nameOf(kind, r.id) }, r); }), { sort: { key: 'exp', dir: 'asc' } });
}

function movedTable(season, ex) {
  var rows = moverRows(season, ex);
  if (!rows.length) { PD.set('fx-moved', '<div class="qk-card-body">' + PD.muted('The last round’s results are not in the driver file yet.') + '</div>'); return; }
  var anyH = rows.some(function (r) { return isNum(r.dpts); });
  /* the ones worth a line: the biggest moves against the forecast and in the table, the top ten in the standings first */
  rows.forEach(function (r) { r.score = Math.abs(r.vs || 0) + 4 * Math.abs(r.moved || 0) + (isNum(r.now) && r.now <= 10 ? 3 : 0); });
  rows.sort(function (a, b) { return b.score - a.score; });
  var show = rows.slice(0, 10);
  var cols = [
    { key: 'name', label: 'Driver', sticky: true, fmt: function (v, r) { return PD.driverLink(r.id, { team: r.team }); } },
    { key: 'res', label: 'Result', sort: false, fmt: function (v, r) { return esc(resultWords(r)); } },
    { key: 'points', label: 'Pts', num: true, fmt: function (v, r) { return '<b>' + PD.pts(v) + '</b>' + (isNum(r.race_points) && r.points !== r.race_points ? ' <span class="qk-muted">(' + PD.pts(r.points - r.race_points) + ' sprint)</span>' : ''); } },
    { key: 'exp', label: 'Forecast', num: true, fmt: function (v) { return PD.num(v, 1); }, tip: 'The expected race points we gave before the start' },
    { key: 'vs', label: 'v forecast', num: true, fmt: function (v) { return PD.deltaHTML(v, 1); }, tip: 'Race points minus our pre-race expectation' },
    { key: 'moved', label: 'Table', num: true, fmt: function (v, r) { return isNum(r.now) ? 'P' + r.now + (v ? ' <span class="' + (v > 0 ? 'pd-up' : 'pd-down') + '">' + (v > 0 ? '▲' : '▼') + Math.abs(v) + '</span>' : '') : '—'; }, tip: 'Championship place now, and places gained or lost at this round' }
  ];
  if (anyH) {
    cols.push({ key: 'dpts', label: 'Exp. final pts', num: true, fmt: function (v) { return PD.deltaHTML(v, 0); }, tip: 'The move in our expected final points since the previous round’s simulation' });
    cols.push({ key: 'dp', label: 'Title chance', num: true, fmt: function (v) { return isNum(v) && Math.abs(v) >= 0.0005 ? PD.deltaHTML(v * 100, 1) + ' pts' : '<span class="qk-muted">—</span>'; }, tip: 'The move in our title chance since the previous round, percentage points' });
  }
  PD.table('fx-moved', cols, show.map(function (r) { return Object.assign({ name: PD.driverName(r.id), res: '' }, r); }), { sort: null });
  var best = rows.filter(function (r) { return isNum(r.vs); }).sort(function (a, b) { return b.vs - a.vs; });
  var lines = [];
  if (best.length) {
    var up = best[0], dn = best[best.length - 1];
    if (up.vs >= 3) lines.push('<b>' + esc(PD.driverName(up.id)) + '</b> beat our forecast by the most (' + esc(resultWords(up)) + '): ' + PD.pts(up.race_points) + ' race points where we expected ' + PD.num(up.exp, 1) + '.');
    if (dn.vs <= -3) lines.push('<b>' + esc(PD.driverName(dn.id)) + '</b> fell furthest short (' + esc(resultWords(dn)) + '): ' + PD.pts(dn.race_points) + ' race points where we expected ' + PD.num(dn.exp, 1) + '.');
  }
  if (!anyH) lines.push('Moves in our title chance appear from the second simulation snapshot on.');
  if (lines.length) document.getElementById('fx-moved').insertAdjacentHTML('beforeend', '<p class="pd-cap fx-pad">' + lines.join(' ') + '</p>');
}

function luckChart(season, ex) {
  var cat = ex.drivers;
  if (!cat || !cat.drivers) { PD.ch.none('fx-luck', 'The driver file is not available.'); return; }
  var done = (season.calendar || []).filter(function (c) { return c.status === 'done'; }).map(function (c) { return c.round; }).sort(function (a, b) { return a - b; });
  var ids = standOrder(season, 'drivers').filter(function (id) { return cat.drivers[id]; }).slice(0, 8);
  if (!done.length || !ids.length) { PD.ch.none('fx-luck', 'No rounds yet.'); return; }
  var teamOf = {};
  ids.forEach(function (id) { teamOf[id] = cat.drivers[id].team; });
  var st = PD.ch.styleMap(ids, teamOf);
  var series = ids.map(function (id) {
    var by = {};
    (cat.drivers[id].log || []).forEach(function (l) { if (isNum(l.race_points) && isNum(l.exp_points)) by[l.round] = l.race_points - l.exp_points; });
    var cum = 0, any = false;
    return { name: PD.driverName(id), label: PD.driverCode(id), color: st[id].colour, dash: st[id].dash,
      data: done.map(function (r) { if (isNum(by[r])) { cum += by[r]; any = true; } return any ? Math.round(cum * 10) / 10 : null; }) };
  });
  QKC.forecast(document.getElementById('fx-luck'), { x: done.map(function (r) { return 'R' + r; }), xType: 'category', xName: 'Round', yName: 'Points above our forecast (cumulative)', series: series,
    yFmt: function (v) { return PD.signed(v, 0); }, yMax: 'auto', annotations: [], xLabel: function (v) { var c = calBy(season)[+String(v).slice(1)]; return c ? v + ' · ' + c.name : v; }, label: 'Points against our pre-race forecast' });
}

function runInTable(season, ex) {
  var ch = season.championship, cal = calBy(season), rounds = runIn(ch, false);
  if (!rounds.length) { PD.set('fx-runin', '<div class="qk-card-body">' + PD.muted('No rounds left.') + '</div>'); return; }
  var D = ch.drivers || {}, circ = ex.circuits || {};
  var ids = standOrder(season, 'drivers').filter(function (id) { return D[id] && D[id].per_round_exp_points && !D[id].eliminated; }).slice(0, 4);
  if (ids.length < 4) ids = standOrder(season, 'drivers').filter(function (id) { return D[id] && D[id].per_round_exp_points; }).slice(0, 4);
  /* overtaking difficulty in thirds of this calendar's circuits */
  var diffs = (season.calendar || []).map(function (c) { var p = (circ[(c.circuit || {}).id] || {}).profile; return p && isNum(p.overtake_difficulty) ? p.overtake_difficulty : null; }).filter(isNum).sort(function (a, b) { return a - b; });
  var third = function (v) { if (!isNum(v) || diffs.length < 6) return null; var i = diffs.indexOf(v); var q = i / (diffs.length - 1); return q >= 0.67 ? 'Hard' : q <= 0.33 ? 'Easier' : 'Average'; };
  var cols = [
    { key: 'round', label: 'Rd', num: true },
    { key: 'name', label: 'Race', sticky: true, fmt: function (v, r) { return PD.raceLink(season.year, r.round, shortName(cal[r.round])) + (r.sprint ? ' <span class="qk-badge quiet">Sprint</span>' : ''); } },
    { key: 'date', label: 'Date', fmt: function (v) { return v ? esc(PD.fmtDate(v, { year: false })) : '—'; } },
    { key: 'pass', label: 'Passing', fmt: function (v) { return v ? esc(v) : '<span class="qk-muted">—</span>'; }, tip: 'How hard overtaking is here, against this calendar’s other tracks (our circuit profile)' },
    { key: 'sc', label: 'Safety car', num: true, fmt: function (v) { return isNum(v) ? PD.pct(v, 0) : '—'; }, tip: 'Share of races here with a safety car (our circuit profile)' }
  ];
  ids.forEach(function (id) {
    cols.push({ key: 'e_' + id, label: PD.driverCode(id), num: true, tip: 'Our expected points for ' + PD.driverName(id) + ' at this round', fmt: function (v, r) { return isNum(v) ? (r.best === id ? '<b>' + PD.num(v, 1) + '</b>' : PD.num(v, 1)) : '—'; } });
  });
  var rows = rounds.map(function (x) {
    var c = cal[x.round] || {}, p = (circ[(c.circuit || {}).id] || {}).profile || {};
    var row = { round: x.round, name: c.name, sprint: x.sprint, date: c.date, pass: third(p.overtake_difficulty), sc: p.p_sc_race };
    var best = null;
    ids.forEach(function (id) { var v = (D[id].per_round_exp_points || {})[String(x.round)]; row['e_' + id] = v; if (isNum(v) && (best === null || v > row['e_' + best])) best = id; });
    row.best = best;
    return row;
  });
  PD.table('fx-runin', cols, rows, { sort: { key: 'round', dir: 'asc' } });
  /* the run-in against the season so far: expected points a round from here v points a round to date */
  /* each front-runner's expected haul over the run-in, and the rounds where our numbers like them most and least */
  var lines = ids.map(function (id) {
    var pr = D[id].per_round_exp_points || {}, ks = Object.keys(pr).filter(function (k) { return isNum(pr[k]); }), tot = 0, hi = null, lo = null;
    ks.forEach(function (k) { tot += pr[k]; if (hi === null || pr[k] > pr[hi]) hi = k; if (lo === null || pr[k] < pr[lo]) lo = k; });
    if (!ks.length) return '';
    return '<b>' + esc(PD.driverSurname(id)) + '</b> ' + PD.num(tot, 0) + ' expected, best at ' + esc(shortName(cal[hi]) || 'round ' + hi) + ' (' + PD.num(pr[hi], 1) + ')' + (ks.length > 1 && lo !== hi ? ', weakest at ' + esc(shortName(cal[lo]) || 'round ' + lo) + ' (' + PD.num(pr[lo], 1) + ')' : '');
  }).filter(Boolean);
  if (lines.length) document.getElementById('fx-runin').insertAdjacentHTML('beforeend', '<p class="pd-cap fx-pad">Over the run-in: ' + lines.join('; ') + '. Each round’s expectation folds in the car, the driver and the track’s passing and safety-car profile.</p>');
}

// ── 2. the shape of the grid ──────────────────────────────────────────────

/* Constructor tiers: the latest car race pace (teams.json car_pace_latest, % of a lap, negative faster), split at the
   three largest gaps between neighbours (two or one with fewer teams). */
F.tiers = function (season, ex) {
  var T = ((ex.teams || {}).teams) || {};
  var ids = Object.keys(T).filter(function (t) { return isNum(((T[t] || {}).values || {}).car_pace_latest); });
  if (ids.length < 4) return [];
  var v = function (t) { return T[t].values.car_pace_latest; };
  ids.sort(function (a, b) { return v(a) - v(b); });
  var k = ids.length >= 8 ? 3 : ids.length >= 6 ? 2 : 1;
  var gaps = [];
  for (var i = 1; i < ids.length; i++) gaps.push({ i: i, g: v(ids[i]) - v(ids[i - 1]) });
  var cuts = gaps.slice().sort(function (a, b) { return b.g - a.g; }).slice(0, k).map(function (x) { return x.i; }).sort(function (a, b) { return a - b; });
  var out = [], start = 0;
  cuts.concat([ids.length]).forEach(function (c, j) {
    out.push({ ids: ids.slice(start, c), gap: j < cuts.length ? v(ids[c]) - v(ids[c - 1]) : null });
    start = c;
  });
  var chT = (season.championship || {}).constructors || {}, chD = (season.championship || {}).drivers || {};
  var names = out.length === 4 ? TIER_NAMES : out.length === 3 ? [TIER_NAMES[0], TIER_NAMES[2], TIER_NAMES[3]] : [TIER_NAMES[0], TIER_NAMES[3]];
  out.forEach(function (t, j) {
    /* "Title fight" only while a title is open: someone in the group at 1% or more and neither title at 99% */
    var settled = Object.keys(chT).some(function (id) { return chT[id].p_title >= 0.99; }) && Object.keys(chD).some(function (d) { return chD[d].p_title >= 0.99; });
    var title = !settled && t.ids.some(function (id) { return (chT[id] && chT[id].p_title >= 0.01) || Object.keys(chD).some(function (d) { return chD[d].team === id && chD[d].p_title >= 0.01; }); });
    t.name = j === 0 && title ? 'Title fight' : names[j];
  });
  return out;
};

F.shape = function (el, season, ex) {
  var node = typeof el === 'string' ? document.getElementById(el) : el;
  if (!node) return;
  node.innerHTML = '<section class="qk-section pd-sec">' + PD.secHead('Shape of the grid', 'Who has the car, who has the driver', 'Tiers from our lap-time model’s car pace, the car against the driver, and every team-mate battle.') +
    PD.grid(
      PD.card('The tiers', 'Teams grouped where the biggest gaps in car race pace open up: our lap-time model at the latest round, % of a lap faster than the field (+ is faster; 0.5% is about 0.45 s on a 90-second lap).', '<div id="fx-tiers"></div>', { span: 5 }) +
      PD.card('Car v driver', 'Across: how fast the car is. Up: how much faster the driver is than the team-mate in the same car. Right and up has both.', '<div id="fx-quad" class="qk-chart" style="--h:420px" role="img" aria-label="Car pace against driver pace"></div>', { span: 7 }) +
      PD.card('Team-mate battles', 'The one rival in identical machinery: qualifying and race head-to-heads, the points split and the median qualifying gap this season.', '<div id="fx-tm"></div>', { span: 12, flush: true }), 'pd-mt') + '</section>';
  tiersHTML(season, ex);
  quadrant(season, ex);
  teamMates(season, ex);
};

function tiersHTML(season, ex) {
  var tiers = F.tiers(season, ex), T = ((ex.teams || {}).teams) || {};
  var chT = (season.championship || {}).constructors || {};
  if (!tiers.length) { PD.set('fx-tiers', PD.muted('Car pace needs a few races of lap data.')); return; }
  PD.set('fx-tiers', '<ol class="fx-tiers">' + tiers.map(function (t) {
    return '<li><div class="fx-tier-h"><b>' + esc(t.name) + '</b>' + (isNum(t.gap) ? '<small>' + PD.num(t.gap, 2) + '% of a lap to the next group</small>' : '') + '</div>' +
      t.ids.map(function (id) {
        var v = T[id].values || {}, c = chT[id];
        return '<div class="fx-tier-row">' + PD.mark(id) + '<span class="fx-tier-n">' + PD.teamLink(id, { dot: false }) + '</span><span class="num">' + PD.signed(-v.car_pace_latest, 2) + '%</span><span class="qk-muted num">' + (c && isNum(c.exp_pos) ? 'exp. P' + PD.num(c.exp_pos, 0) : '') + '</span></div>';
      }).join('') + '</li>';
  }).join('') + '</ol>');
}

function quadrant(season, ex) {
  var T = ((ex.teams || {}).teams) || {}, cat = ex.drivers;
  var n = document.getElementById('fx-quad');
  if (!n) return;
  if (!cat || !cat.drivers) { n.innerHTML = PD.muted('The driver file is not available.'); return; }
  var pts = [];
  Object.keys(cat.drivers).forEach(function (id) {
    var d = cat.drivers[id], v = d.values || {}, t = d.team, car = ((T[t] || {}).values || {}).car_race_pace;
    if (!d.qualified || !isNum(v.driver_effect) || !isNum(car)) return;
    pts.push({ x: -car, y: -v.driver_effect, name: d.name || PD.driverName(id), label: d.code || PD.driverCode(id), color: PD.teamColourRaw(t) || undefined, href: PD.driverHref(id),
      sub: PD.teamName(t) + ' · car ' + PD.signed(-car, 2) + '% · driver ' + PD.signed(-v.driver_effect, 3) + '% v team-mate' });
  });
  if (pts.length < 6) { n.innerHTML = PD.muted('The chart fills in once the lap-time model has a few races.'); return; }
  QKC.quadrant(n, { points: pts, xName: 'Car race pace v field (% of a lap, right is faster)', yName: 'Driver v team-mate (% of a lap, up is faster)', refX: PD.median(pts.map(function (p) { return p.x; })), refY: 0,
    xFmt: function (v) { return PD.signed(v, 1); }, yFmt: function (v) { return PD.signed(v, 2); }, corners: { tl: 'Driver lifting the car', tr: 'The full package', bl: 'Struggling', br: 'Car doing the work' }, label: 'Car pace against driver pace' });
}

/* Team-mate battles from the drivers' logs: rounds where both drove for the team. */
function teamMates(season, ex) {
  var cat = ex.drivers, T = ((ex.teams || {}).teams) || {};
  if (!cat || !cat.drivers) { PD.set('fx-tm', '<div class="qk-card-body">' + PD.muted('The driver file is not available.') + '</div>'); return; }
  var rows = [];
  standOrder(season, 'constructors').forEach(function (t) {
    var ds = Object.keys(cat.drivers).filter(function (id) { return (cat.drivers[id].log || []).some(function (l) { return l.team === t; }); });
    var starts = function (id) { return (cat.drivers[id].log || []).filter(function (l) { return l.team === t; }).length; };
    ds.sort(function (a, b) { return starts(b) - starts(a); });
    if (ds.length < 2) return;
    var A = ds[0], B = ds[1];
    var la = {}, lb = {};
    (cat.drivers[A].log || []).forEach(function (l) { if (l.team === t) la[l.round] = l; });
    (cat.drivers[B].log || []).forEach(function (l) { if (l.team === t) lb[l.round] = l; });
    var q = [0, 0], r = [0, 0], p = [0, 0], shared = 0;
    Object.keys(la).forEach(function (k) {
      var a = la[k], b = lb[k];
      p[0] += a.points || 0;
      if (!b) return;
      shared++;
      if (isNum(a.quali_pos) && isNum(b.quali_pos) && a.quali_pos !== b.quali_pos) q[a.quali_pos < b.quali_pos ? 0 : 1]++;
      var fa = isNum(a.pos) && PD.finished(a.status), fb = isNum(b.pos) && PD.finished(b.status);
      if (fa && fb) r[a.pos < b.pos ? 0 : 1]++; else if (fa !== fb) r[fa ? 0 : 1]++;
    });
    Object.keys(lb).forEach(function (k) { p[1] += lb[k].points || 0; });
    if (p[1] > p[0]) { var s = A; A = B; B = s; q.reverse(); r.reverse(); p.reverse(); }
    var va = (cat.drivers[A].values || {});
    rows.push({ team: t, a: A, b: B, q: q, r: r, p: p, shared: shared, gap: va.quali_gap_tm_pct, gapMs: va.quali_gap_tm_ms, pace: va.race_pace_tm_delta, three: ds.length > 2 ? ds.slice(2) : [] });
  });
  if (!rows.length) { PD.set('fx-tm', '<div class="qk-card-body">' + PD.muted('No team-mate pairs yet.') + '</div>'); return; }
  var split = function (x, r) { var tot = x[0] + x[1]; var w = tot ? Math.round(100 * x[0] / tot) : 50; return '<span class="fx-split" style="--a:' + esc(PD.teamColour(r.team)) + ';--w:' + w + '%" title="' + x[0] + '–' + x[1] + '"><i></i></span><span class="num">' + PD.pts(x[0]) + '–' + PD.pts(x[1]) + '</span>'; };
  PD.table('fx-tm', [
    { key: 'teamName', label: 'Team', sticky: true, fmt: function (v, r) { return PD.teamLink(r.team); } },
    { key: 'pair', label: 'Ahead v behind (points)', sort: false, fmt: function (v, r) { return PD.driverLink(r.a, { dot: false }) + ' <span class="qk-muted">v</span> ' + PD.driverLink(r.b, { dot: false }) + (r.three.length ? ' <span class="qk-muted">(+' + r.three.map(PD.driverCode).join(', ') + ')</span>' : ''); } },
    { key: 'qs', label: 'Qualifying', fmt: function (v, r) { return split(r.q, r); }, tip: 'Sessions where each qualified ahead, in rounds they both drove for the team' },
    { key: 'rs', label: 'Races', fmt: function (v, r) { return split(r.r, r); }, tip: 'Races where each finished ahead (a finisher beats a retirement; two retirements count for neither)' },
    { key: 'ps', label: 'Points', fmt: function (v, r) { return split(r.p, r); }, tip: 'Points for this team, sprints included' },
    { key: 'gap', label: 'Quali gap', num: true, fmt: function (v, r) { return isNum(v) ? PD.signed(v, 2) + '%' + (isNum(r.gapMs) ? ' <span class="qk-muted">(' + PD.signed(r.gapMs / 1000, 3) + ' s)</span>' : '') : '—'; }, tip: 'The points leader’s median gap to the team-mate’s best lap in the same segment; negative is faster' },
    { key: 'pace', label: 'Race pace gap', num: true, fmt: function (v) { return isNum(v) ? PD.signed(v, 2) + '%' : '—'; }, tip: 'The points leader’s corrected race pace minus the team-mate’s, % of a lap; negative is faster' }
  ], rows.map(function (r) { return Object.assign({ teamName: PD.teamName(r.team), pair: '', qs: r.q[0] - r.q[1], rs: r.r[0] - r.r[1], ps: r.p[0] - r.p[1] }, r); }), { sort: null });
}

// ── 3. strengths and weak spots ───────────────────────────────────────────

/* [key, strong words, weak words] on the peer percentile (higher is always better in the payload's pct) */
var D_RULES = [
  ['race_pace', 'Front-running pace', 'Off the pace'],
  ['driver_effect', 'Quicker than the team-mate', 'Slower than the team-mate'],
  ['lap1_gain', 'Gains on lap 1', 'Loses places on lap 1'],
  ['consistency', 'Metronome laps', 'Erratic lap times'],
  ['tyre_mgmt', 'Kind to tyres', 'Hard on tyres'],
  ['overtakes_made', 'Overtaker', null],
  ['dnf_driver', null, 'Incident-prone'],
  ['dnf_mech', null, 'Unreliable car']
];
var T_RULES = [
  ['car_race_pace', 'Fast race car', 'Slow race car'],
  ['car_pace_trend', 'Getting faster', 'Falling back'],
  ['dnf_rate', 'Bulletproof', 'Reliability worries'],
  ['pit_under_2500', 'Quick pit crew', 'Slow stops'],
  ['strategy_gain', 'Gains on strategy', 'Loses out on strategy'],
  ['tyre_mgmt', 'Kind to tyres', 'Hard on tyres']
];
function peerFor(ex, kind, season) {
  var key = kind === 'teams' ? 'teams' : 'drivers';
  if (!ex[key]) return null;
  if (!ex['_P' + key]) ex['_P' + key] = PD.v2.peer(ex[key], kind === 'teams' ? 'teams' : 'drivers', season);
  return ex['_P' + key];
}
/* [{text, kind: 'up'|'down'|'luck', tip}] for one driver or constructor */
function chipList(ex, kind, id, season) {
  var P = peerFor(ex, kind, season), out = [];
  if (!P || !P.pct[id]) return out;
  var pc = P.pct[id], vals = (P.rows[id] || {}).values || {};
  var rules = kind === 'teams' ? T_RULES : D_RULES, ups = [], downs = [];
  if (kind !== 'teams' && isNum(pc.quali_driver_effect) && isNum(pc.driver_effect)) {
    if (pc.quali_driver_effect >= 70 && pc.quali_driver_effect - pc.driver_effect >= 30) ups.push({ p: pc.quali_driver_effect + 5, text: 'Saturday specialist', tip: 'Qualifying pace against the team-mate in the ' + QK.ordinal(pc.quali_driver_effect) + ' percentile, well above the race pace' });
    else if (pc.driver_effect >= 70 && pc.driver_effect - pc.quali_driver_effect >= 30) ups.push({ p: pc.driver_effect + 5, text: 'Better on Sundays', tip: 'Race pace against the team-mate in the ' + QK.ordinal(pc.driver_effect) + ' percentile, well above qualifying' });
  }
  if (kind === 'teams' && isNum(pc.car_quali_pace) && isNum(pc.car_race_pace) && Math.abs(pc.car_quali_pace - pc.car_race_pace) >= 30)
    ups.push({ p: 85, text: pc.car_quali_pace > pc.car_race_pace ? 'Quicker on Saturdays' : 'Stronger in races', tip: 'Car qualifying pace ' + QK.ordinal(pc.car_quali_pace) + ' v race pace ' + QK.ordinal(pc.car_race_pace) + ' percentile' });
  rules.forEach(function (r) {
    var p = pc[r[0]];
    if (!isNum(p)) return;
    var lab = PD.v2.label(P.meta, r[0]);
    if (p >= 80 && r[1]) ups.push({ p: p, text: r[1], tip: lab + ': ' + QK.ordinal(p) + ' percentile' });
    if (p <= 20 && r[2]) downs.push({ p: p, text: r[2], tip: lab + ': ' + QK.ordinal(p) + ' percentile' });
  });
  ups.sort(function (a, b) { return b.p - a.p; });
  downs.sort(function (a, b) { return a.p - b.p; });
  ups.slice(0, 2).forEach(function (c) { out.push({ text: c.text, kind: 'up', tip: c.tip }); });
  downs.slice(0, 1).forEach(function (c) { out.push({ text: c.text, kind: 'down', tip: c.tip }); });
  /* points against our pre-race forecast (2025 on): a large gap either way, per start */
  var pve = vals.points_v_expected, n = kind === 'teams' ? ((P.rows[id] || {}).log || []).length : vals.races;
  if (isNum(pve) && n >= 3) {
    var per = pve / n, lim = kind === 'teams' ? 2.5 : 1.5;
    if (per >= lim) out.push({ text: 'Above our forecast: ' + PD.signed(pve, 0) + ' pts', kind: 'luck', tip: 'Race points minus the expected points we gave before each start: more than the pace and grid suggested' });
    else if (per <= -lim) out.push({ text: 'Below our forecast: ' + PD.signed(pve, 0) + ' pts', kind: 'luck', tip: 'Race points minus the expected points we gave before each start: less than the pace and grid suggested' });
  }
  return out;
}
function chipsHTML(list) {
  return list.map(function (c) { return '<span class="fx-chip ' + c.kind + '"' + (c.tip ? ' data-tip="' + esc(c.tip) + '" tabindex="0"' : '') + '>' + esc(c.text) + '</span>'; }).join('');
}
F.chips = function (ex, id, season) { return ex ? chipsHTML(chipList(ex, 'drivers', id, season)) : ''; };
F.teamChips = function (ex, id, season) { return ex ? chipsHTML(chipList(ex, 'teams', id, season)) : ''; };

/* one plain sentence: the best and the weakest headline metric */
function shortVersion(P, id, sets) {
  var pc = P.pct[id] || {}, best = null, worst = null;
  sets.forEach(function (g) { g[1].forEach(function (k) { if (!isNum(pc[k])) return; if (!best || pc[k] > best.p) best = { k: k, p: pc[k] }; if (!worst || pc[k] < worst.p) worst = { k: k, p: pc[k] }; }); });
  if (!best) return '';
  var lab = function (x) { return PD.v2.lc(PD.v2.label(P.meta, x.k)); };
  return 'Best: ' + esc(lab(best)) + ' (' + QK.ordinal(best.p) + ' percentile). ' + (worst && worst.k !== best.k ? 'Weak spot: ' + esc(lab(worst)) + ' (' + QK.ordinal(worst.p) + ').' : '');
}

F.profiles = function (el, season, ex) {
  var node = typeof el === 'string' ? document.getElementById(el) : el;
  if (!node) return;
  var PDr = peerFor(ex, 'drivers', season), PT = peerFor(ex, 'teams', season);
  if (!PDr && !PT) { node.innerHTML = ''; return; }
  node.innerHTML = '<section class="qk-section pd-sec">' + PD.secHead('Strengths and weak spots', 'Every driver, every team', 'Percentiles against the grid on the F1 metric set (stable year to year and predictive); open a row for the full read. ' + (PDr ? esc(PDr.label) + '.' : ''),
    PD.seg('fx-pk', [['drivers', 'Drivers'], ['teams', 'Constructors']], 'drivers', 'Profiles')) + '<div id="fx-prof" class="pd-mt"></div></section>';
  var draw = function (kind) {
    var isT = kind === 'teams', P = isT ? PT : PDr;
    if (!P) { PD.set('fx-prof', PD.muted('No percentiles for this season yet.')); return; }
    var order = standOrder(season, isT ? 'constructors' : 'drivers');
    var sets = isT ? PD.v2.TEAM_SET.concat(PD.v2.MORE_TEAM.slice(0, 1)) : PD.v2.DRIVER_SET.concat([['Race craft', ['consistency', 'tyre_mgmt', 'overtakes_made', 'net_overtakes']]]);
    PD.set('fx-prof', '<div class="fx-prof">' + order.map(function (id, i) {
      var chips = chipList(ex, isT ? 'teams' : 'drivers', id, season);
      var q = P.qualified(id);
      var groups = q ? PD.v2.pctGroups(P, id, sets) : [];
      var body = q ? groups.map(function (g) { return g.rows.length ? '<div class="fx-pg"><h4>' + esc(g.label) + '</h4>' + QK.pctlBars(g.rows) + '</div>' : ''; }).join('') : PD.muted('Short of the sample floor (' + P.floor + ' ' + P.unit + '): no percentiles yet.');
      var st = (season.standings || {})[isT ? 'constructors' : 'drivers'] || [];
      var row = st.filter(function (r) { return (isT ? r.team : r.driver) === id; })[0] || {};
      return '<details class="fx-row" style="--tc:' + esc(PD.teamColour(isT ? id : row.team)) + '"><summary><span class="fx-pos num">' + (row.pos || i + 1) + '</span><span class="fx-name">' + (isT ? PD.teamLink(id) : PD.driverLink(id, { team: row.team })) +
        '<small>' + (isT ? '' : esc(PD.teamName(row.team)) + ' · ') + PD.pts(row.points) + ' pts</small></span><span class="fx-chips">' + (chips.length ? chipsHTML(chips) : '<span class="qk-muted">' + (q ? 'No standout either way' : 'Too few starts to read yet') + '</span>') + '</span></summary>' +
        '<div class="fx-body">' + (q ? '<p class="pd-cap">' + shortVersion(P, id, sets) + ' ' + esc(P.sample(id)) + '.</p>' : '') + '<div class="fx-pgs">' + body + '</div></div></details>';
    }).join('') + '</div>');
  };
  draw('drivers');
  PD.wireSeg(node, 'fx-pk', draw);
};

})(window.PD);
