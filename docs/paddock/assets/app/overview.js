/* The Quant Paddock — Overview (#/), on kit v3 "Matchday" (MIGRATION_V3.md, after rk-overview.js): the greeting hero
 * with the next Grand Prix as the feature card (our favourite, the top three, how sure); stat tiles; "What to watch"
 * (six cards from our own numbers, each with a reason); "Who's hot"; "New here?" beside a "How sure are we?" teaser
 * from calibration.json; the race weekend (countdown, schedule, our win chance); the title race (points so far and our
 * projection, 538 style; title chances; how the race has moved, with the 90% band, once title_history holds three
 * rounds; the season-end points range; standings with trends), car against driver, how our favourite has fared, the
 * last race and the fantasy projections. No market anywhere on this page.
 * Reads index.json, calibration.json, <y>/season.json, <y>/races/<next>.json, <y>/value.json, <y>/fantasy.json. */
(function (PD) {
'use strict';

var esc = PD.esc, isNum = PD.isNum;
var SESSION_LABEL = { fp1: 'Practice 1', fp2: 'Practice 2', fp3: 'Practice 3', sprint_quali: 'Sprint qualifying', sprint_shootout: 'Sprint shootout', sprint: 'Sprint', quali: 'Qualifying', qualifying: 'Qualifying', race: 'Grand Prix' };
var SESSION_LEN_MIN = { fp1: 60, fp2: 60, fp3: 60, sprint_quali: 45, sprint_shootout: 45, sprint: 40, quali: 60, qualifying: 60, race: 120 };

function sessionsOf(next) {
  var s = (next && next.sessions) || {};
  return Object.keys(s).filter(function (k) { return s[k]; }).map(function (k) { return { key: k, label: SESSION_LABEL[k] || PD.titleCase(k), t: PD.parseDate(s[k]), iso: s[k] }; })
    .filter(function (x) { return x.t; }).sort(function (a, b) { return a.t - b.t; });
}
PD.sessionsOf = sessionsOf;
PD.SESSION_LEN_MIN = SESSION_LEN_MIN;
function tzName() { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || 'local'; } catch (e) { return 'local'; } }

/* Countdown + schedule, ticking every second while the page is open. */
function weekendClock(list, cdId, schedId) {
  function tick() {
    var now = Date.now();
    var upcoming = list.filter(function (s) { return s.t.getTime() > now; })[0];
    var live = list.filter(function (s) { return s.t.getTime() <= now && now < s.t.getTime() + (SESSION_LEN_MIN[s.key] || 60) * 60000; })[0];
    var cd = document.getElementById(cdId);
    if (!cd) return;
    if (live) cd.innerHTML = '<div class="pd-cd-l">Now</div><div class="pd-cd-v"><span class="qk-badge live">Live</span> ' + esc(live.label) + '</div><div class="pd-cd-s">Started ' + esc(PD.fmtTime(live.iso)) + '</div>';
    else if (upcoming) cd.innerHTML = '<div class="pd-cd-l">' + esc(upcoming.label) + ' starts in</div><div class="pd-cd-v">' + esc(PD.countdown(upcoming.iso, now)) + '</div><div class="pd-cd-s">' + esc(PD.fmtDate(upcoming.iso, { year: false, time: true })) + ', your time</div>';
    else cd.innerHTML = '<div class="pd-cd-l">Weekend</div><div class="pd-cd-v">Sessions complete</div><div class="pd-cd-s">Results arrive with the next build.</div>';
    var sch = document.getElementById(schedId);
    if (sch) sch.innerHTML = list.map(function (s) {
      var past = s.t.getTime() + (SESSION_LEN_MIN[s.key] || 60) * 60000 < now;
      var on = (upcoming && s.key === upcoming.key) || (live && live.key === s.key);
      return '<li class="' + (past ? 'past' : '') + (on ? ' on' : '') + '"><span>' + esc(PD.fmtDate(s.iso, { year: false })) + '</span><b>' + esc(s.label) + '</b><span class="t">' + esc(PD.fmtTime(s.iso)) + '</span></li>';
    }).join('') || '<li>Session times not published yet.</li>';
  }
  tick();
  PD.interval(tick, 1000);
}
PD.weekendClock = weekendClock;

function titleRows(season, kind) {
  var ch = PD.ok(season) && season.championship ? season.championship[kind] || {} : {};
  return Object.keys(ch).filter(function (id) { return !ch[id].eliminated && isNum(ch[id].p_title); })
    .sort(function (a, b) { return (ch[b].p_title - ch[a].p_title) || ((ch[b].exp_points || 0) - (ch[a].exp_points || 0)); })
    .map(function (id) { return { id: id, model: ch[id].p_title, c: ch[id] }; });
}
function nextSim(race) {
  var f = PD.ok(race) && race.forecast ? race.forecast : null;
  var post = f && f.post_quali && f.post_quali.drivers && Object.keys(f.post_quali.drivers).length ? f.post_quali : null;
  var sim = post || (f && f.pre_quali);
  return sim && sim.drivers ? { sim: sim, post: !!post } : null;
}

function render(el) {
  var idx = PD.index() || {};
  var y = idx.current_season || PD.currentSeason();
  var next = idx.next, last = idx.last;
  var meta = (idx.seasons_meta || {})[String(y)] || {};
  var kseg = function (id) { return PD.seg(id, [['drivers', 'Drivers'], ['constructors', 'Constructors']], 'drivers', 'Championship'); };
  var nd = next ? PD.parseDate(next.date) : null;
  var soon = nd && (nd.getTime() - QK.now()) < 7 * 864e5;
  var when = next ? (soon ? 'this weekend' : 'next') : 'this season';
  var where = next ? (((next.circuit || {}).locality) || PD.shortRace(next.name)) : '';
  el.innerHTML = QK.greeting({ date: 'F1 · ' + y + (next ? ' · round ' + next.round + ' next' : ' · season complete'),
    title: esc(QK.greet()) + '! Here’s what’s ' + QK.mark('worth watching') + ' in F1 ' + when + '.',
    lede: 'Our chance for every Grand Prix and both championships from 20,000 simulated seasons, car pace against driver skill, and the drivers behind it all, in plain English.',
    ctas: (next ? [{ label: 'Race centre', href: PD.raceHref(next.year, next.round) }] : []).concat([{ label: 'Standings', href: '#/standings', ghost: !!next }]),
    side: '<div id="ov-feat">' + QK.skeleton('card', 1) + '</div>' }) +
    '<div id="ov-kpis" style="margin-top:var(--sp-10)">' + QK.skeleton('lines', 2) + '</div>' +
    '<section class="qk-section pd-sec">' + QK.sectionHead({ kicker: 'What to watch ' + when, title: next ? 'Six things we’d watch in ' + esc(where) : 'What the numbers say', html: true,
      sub: 'Our numbers only, each with a line on why it’s worth your time.' }) + '<div class="qk-watch" id="ov-watch">' + QK.skeleton('card', 3) + '</div></section>' +
    '<section class="qk-section pd-sec">' + QK.sectionHead({ kicker: 'Who’s hot', title: 'In form right now', sub: 'Leaders on the numbers that matter, with the next best beside each.', actions: '<a class="qk-btn" href="#/drivers">Every driver →</a>' }) +
      '<div id="ov-hot">' + QK.skeleton('lines', 2) + '</div></section>' +
    '<section class="qk-section pd-sec qk-gside" id="ov-new"><div id="ov-sure"></div><div>' + QK.newHere({ items: [QK.NEW_HERE[0],
      'A <b>percentile</b> ranks a driver against the other regular drivers this season: 90th means better than 90 in 100. Team-mate numbers take the car out.',
      'Every forecast is checked against what happened. <a class="qk-link" href="#/model">The record is on the Model page.</a>'] }) + '</div></section>' +
    '<section class="qk-section pd-sec" id="ov-wk"></section>' +
    '<section class="qk-section pd-sec">' + PD.secHead('Season simulation', 'Who wins the title', 'Our chances from 20,000 simulated seasons. The lines are points so far, then our expected points for every round still to run.', kseg('ov-k')) +
    PD.grid(
      PD.card('The title race', 'Championship points by round; past the Today line, our projection.', PD.chartBox('ov-prog', 380, 'Championship points with our projection'), { span: 8 }) +
      PD.card('Title chances', '<span id="ov-odds-s">Our chance of winning the title.</span>', '<div id="ov-odds"></div>', { span: 4, foot: '<span></span><a href="#/standings?tab=odds">Every title chance →</a>' }) +
      '<div class="qk-span-12" id="ov-hist-w" hidden>' + PD.card('How the race has moved', 'Our expected final points after each round, with the band where 90% of simulated seasons end (5th to 95th percentile).', '<div id="ov-hist" class="qk-chart" style="--h:320px" role="img" aria-label="Expected final points after each round, with a 90% band"></div>') + '</div>' +
      PD.card('Where the points land', 'Season-end points: the bar spans the 5th to 95th percentile of the simulated seasons, the dot is our expectation.', PD.chartBox('ov-range', 360, 'Season-end points range'), { span: 6 }) +
      PD.card('Standings', 'Points so far and the trend after every round.', '<div id="ov-std"></div>', { span: 6, flush: true, foot: '<span></span><a href="#/standings">Full standings and magic numbers →</a>' })) + '</section>' +
    '<section class="qk-section pd-sec">' + PD.secHead('Car and driver', 'Who’s fast right now', 'The lap-time model splits pace into the car and the driver. Bars are our estimates with one standard error either side.', '<a class="qk-btn" href="#/value">Driver value →</a>') +
    PD.note('Pace is a share of a lap: <b>0.5%</b> is about 0.45 seconds on a 90-second lap, roughly the gap between a front-row car and a midfield one.') +
    PD.grid(
      PD.card('Fastest cars right now', 'Car race pace at the latest round, % of a lap against the field (right is faster), ±1 standard error.', PD.chartBox('ov-cars', 320, 'Car pace by team'), { span: 6 }) +
      PD.card('Best drivers this season', 'Race pace above the team-mate, % of a lap (the driver alone), ±1 standard error; 5+ races.', PD.chartBox('ov-drv', 320, 'Pace above the team-mate'), { span: 6 }), 'pd-mt') + '</section>' +
    '<section class="qk-section pd-sec">' + PD.secHead('Track record', 'How our forecasts have done', 'Our pre-race favourite every round, and the last Grand Prix.', '<a class="qk-btn" href="#/model">The full record →</a>') +
    PD.grid(
      PD.card('How our favourite fared', 'Our pre-race favourite each round: its win chance, filled in the team colour when it won.', PD.chartBox('ov-fav', 300, 'Our favourite’s win chance by round'), { span: 7 }) +
      PD.card('Last race', '', '<div id="ov-last"></div>', { span: 5 }) +
      PD.card('Fantasy: top projections', 'Expected points next weekend with our scoring table; whiskers run from the 10th to the 90th percentile.', PD.chartBox('ov-fan', 300, 'Fantasy projections'), { span: 12, foot: '<span></span><a href="#/fantasy">All picks and the schedule →</a>' })) + '</section>';
  howSureTeaser();
  var raceP = next ? PD.load(next.year + '/races/' + next.round + '.json') : Promise.resolve(null);
  return Promise.all([PD.load(y + '/season.json'), raceP, PD.load(y + '/value.json'), PD.load(y + '/fantasy.json')]).then(function (arr) {
    if (!PD.alive(el)) return;
    var season = arr[0], race = arr[1], value = arr[2], fan = arr[3];
    PD.set('ov-feat', feature(next, race, season));
    tiles(idx, season, race, value, meta);
    watch(next, race, season);
    hot(season, value);
    weekend(next, race, season);
    title(season);
    cars(value);
    bestDrivers(value);
    favourites(season);
    lastRace(last, season);
    fantasy(fan);
  });
}

/* The hero's side card: the next Grand Prix with our favourite as a big teal number, the top three, and how sure. */
function feature(next, race, season) {
  if (!next) {
    var champ = PD.ok(season) ? ((season.standings || {}).drivers || [])[0] : null;
    return champ ? '<a class="qk-card qk-feature" href="' + PD.driverHref(champ.driver) + '" style="--sa:var(--a-f1)"><div class="qk-scribble">Champion!</div><div class="qk-feature-meta"><span class="qk-pill">F1 · ' + esc(String(season.year || '')) + '</span></div>' +
      '<div class="qk-feature-row"><div class="t">' + PD.mark(champ.team, 'md') + '<span>' + esc(PD.driverName(champ.driver)) + '</span></div><div class="s">' + PD.pts(champ.points) + '</div></div>' + QK.note('The season is over: the final standings and every race centre are below.') + '</a>' : '';
  }
  var ns = nextSim(race);
  var circ = next.circuit || {};
  var meta = '<div class="qk-feature-meta"><span class="qk-pill">Round ' + next.round + ' · ' + esc(circ.locality || circ.name || '') + '</span><span class="qk-badge">' + esc(PD.fmtDate(((next.sessions || {}).race) || next.date, { year: false, time: true })) + '</span></div>';
  var head = '<div class="pd-feat-name">' + esc(next.name) + '</div>';
  if (!ns) return '<a class="qk-card qk-feature" href="' + PD.raceHref(next.year, next.round) + '" style="--sa:var(--a-f1)">' + meta + head + QK.note('Our forecast for the weekend is built once the race is near.') + '</a>';
  var ds = ns.sim.drivers;
  var ids = Object.keys(ds).sort(function (a, b) { return ds[b].p_win - ds[a].p_win; });
  var f = ids[0], p = ds[f].p_win;
  var miss = Math.max(1, Math.round(10 * (1 - p)));
  var row = function (id) { var t = PD.driverTeam(id); return '<div class="qk-feature-row"><div class="t">' + (t ? PD.mark(t, 'md') : '') + '<span>' + esc(PD.driverName(id)) + '</span></div><div class="s pd-feat-p">' + PD.pct(ds[id].p_win, 0) + '</div></div>'; };
  return '<a class="qk-card qk-feature" href="' + PD.raceHref(next.year, next.round) + '" style="--sa:var(--a-f1)"><div class="qk-scribble">Our pick ' + (ns.post ? 'after qualifying' : 'this weekend') + '!</div>' + meta + head +
    '<div class="qk-feature-big"><div class="big">' + PD.pct(p, 0) + '</div><div class="say">chance <b>' + esc(PD.driverSurname(f)) + '</b> wins the ' + esc(PD.shortRace(next.name)) + ' Grand Prix.</div></div>' +
    ids.slice(0, 3).map(row).join('') +
    QK.note('<b>How sure are we?</b> ' + PD.pct(p, 0) + ' means the favourite loses a race like this about ' + miss + ' time' + (miss === 1 ? '' : 's') + ' in 10. With twenty cars, even a clear favourite is usually under 50%.') + '</a>';
}

/* "What to watch": up to six cards from our own numbers (no market): the favourite, the closest podium call, the best
   outsider, the title fight, the closest team-mate fight on points and the safety car. */
function watch(next, race, season) {
  var host = document.getElementById('ov-watch');
  if (!host) return;
  var ns = nextSim(race), cards = [];
  var card = function (o) {
    return '<a class="qk-card pd-watch" href="' + esc(o.href) + '"' + (o.team ? ' style="--tc:' + esc(PD.tc(o.team)) + '"' : '') + '><div class="qk-kicker">' + esc(o.kicker) + '</div><h3>' + esc(o.title) + '</h3>' +
      '<div class="pd-watch-n"><span class="v">' + o.value + '</span><span class="l">' + esc(o.label) + '</span></div>' + QK.aside(o.why) + '</a>';
  };
  var rh = next ? PD.raceHref(next.year, next.round) : '#/races';
  var ds = ns ? ns.sim.drivers : {};
  var ids = Object.keys(ds).sort(function (a, b) { return ds[b].p_win - ds[a].p_win; });
  if (ids.length) {
    var f = ids[0], p = ds[f].p_win, n = Math.round(1 / Math.max(0.01, 1 - p));
    cards.push({ kicker: 'The favourite', title: PD.driverName(f) + ' to win', value: PD.pct(p, 0), label: 'our chance', team: PD.driverTeam(f), href: PD.driverHref(f),
      why: p >= 0.5 ? 'A clear favourite, but a ' + PD.pct(1 - p, 0) + ' chance of losing still comes off about 1 race in ' + n + '.' : 'Our favourite, but under 50%: the field beats ' + PD.driverSurname(f) + ' more often than not.' });
    var pod = ids.filter(function (id) { return isNum(ds[id].p_podium); }).sort(function (a, b) { return Math.abs(ds[a].p_podium - 0.5) - Math.abs(ds[b].p_podium - 0.5); })[0];
    if (pod) cards.push({ kicker: 'The closest call', title: PD.driverName(pod) + ' on the podium?', value: PD.pct(ds[pod].p_podium, 0), label: 'our podium chance', team: PD.driverTeam(pod), href: PD.driverHref(pod),
      why: 'Our nearest thing to a coin flip for the top three this weekend.' });
    var dark = ids.slice(3).filter(function (id) { return ds[id].p_win >= 0.01; })[0];
    if (dark) cards.push({ kicker: 'The outsider', title: PD.driverName(dark) + ' to win', value: PD.pct(ds[dark].p_win, 0), label: 'our chance', team: PD.driverTeam(dark), href: PD.driverHref(dark),
      why: 'Our best pick outside the top three: it comes off about 1 time in ' + Math.round(1 / ds[dark].p_win) + '.' });
  }
  var ch = PD.ok(season) && season.championship ? season.championship.drivers || {} : null;
  var st = PD.ok(season) ? ((season.standings || {}).drivers || []) : [];
  if (ch && st[0]) {
    var lead = st[0], sec = st[1], left = (season.rounds_total || 0) - (season.rounds_done || 0);
    var pl = (ch[lead.driver] || {}).p_title;
    if (isNum(pl) && pl > 0.995) cards.push({ kicker: 'The title', title: PD.driverName(lead.driver) + ' all but champion', value: PD.pct(pl, pl > 0.999 ? 1 : 0), label: 'of simulated seasons', team: lead.team, href: '#/standings?tab=odds',
      why: PD.pts(lead.points - (sec ? sec.points : 0)) + ' points clear with ' + left + ' round' + (left === 1 ? '' : 's') + ' left.' });
    else if (sec && isNum((ch[sec.driver] || {}).p_title)) cards.push({ kicker: 'The title fight', title: 'Can ' + PD.driverSurname(sec.driver) + ' catch ' + PD.driverSurname(lead.driver) + '?', value: PD.pct(ch[sec.driver].p_title, 0), label: 'our title chance', team: sec.team, href: '#/standings?tab=odds',
      why: PD.pts(lead.points - sec.points) + ' points behind with ' + left + ' round' + (left === 1 ? '' : 's') + ' left.' });
  }
  if (st.length) {
    var byT = {};
    st.forEach(function (r) { if (r.points >= 20) (byT[r.team] = byT[r.team] || []).push(r); });
    var pair = Object.keys(byT).filter(function (t) { return byT[t].length >= 2; }).map(function (t) { return byT[t]; }).sort(function (a, b) { return Math.abs(a[0].points - a[1].points) - Math.abs(b[0].points - b[1].points); })[0];
    if (pair) {
      var a = pair[0], b = pair[1], gap = Math.abs(a.points - b.points);
      var ea = (ds[a.driver] || {}).exp_pos, eb = (ds[b.driver] || {}).exp_pos;
      cards.push({ kicker: 'Team-mates', title: PD.driverSurname(a.driver) + ' v ' + PD.driverSurname(b.driver), value: PD.pts(gap), label: gap === 1 ? 'point between them' : 'points between them', team: a.team, href: '#/compare/drivers/' + encodeURIComponent(a.driver) + '/' + encodeURIComponent(b.driver),
        why: 'The closest team-mate fight on points.' + (isNum(ea) && isNum(eb) ? ' This weekend we expect ' + PD.driverSurname(ea <= eb ? a.driver : b.driver) + ' ahead: P' + PD.num(Math.min(ea, eb), 1) + ' v P' + PD.num(Math.max(ea, eb), 1) + ' on average.' : '') });
    }
  }
  if (ns && isNum(ns.sim.p_sc)) cards.push({ kicker: 'The wild card', title: 'A safety car?', value: PD.pct(ns.sim.p_sc, 0), label: 'our chance of at least one', href: rh,
    why: ns.sim.p_sc >= 0.5 ? 'More likely than not here, and a safety car reshuffles the strategy for everyone.' : 'Less likely than not here, so the grid order should matter more.' });
  host.innerHTML = cards.length ? cards.slice(0, 6).map(card).join('') : QK.empty('Nothing to watch yet', 'The cards appear once the next race forecast is built.');
}

/* "Who's hot": the kit's hot row; F1 leaders on points, wins, recent form, pace against the team-mate and car pace. */
function hot(season, value) {
  var host = document.getElementById('ov-hot');
  if (!host) return;
  var st = PD.ok(season) ? ((season.standings || {}).drivers || []) : [];
  var items = [];
  if (st[0]) items.push({ sport: 'f1', title: 'Most points', name: PD.driverName(st[0].driver), value: st[0].points, unit: 'points', next: st[1] ? { name: PD.driverName(st[1].driver), value: st[1].points } : null, href: PD.driverHref(st[0].driver), expl: 'The championship leader.' });
  var w = st.slice().sort(function (a, b) { return (b.wins || 0) - (a.wins || 0); });
  if (w[0] && w[0].wins) items.push({ sport: 'f1', title: 'Most wins', name: PD.driverName(w[0].driver), value: w[0].wins, unit: 'Grand Prix wins', next: w[1] ? { name: PD.driverName(w[1].driver), value: w[1].wins || 0 } : null, href: PD.driverHref(w[0].driver) });
  var prog = PD.ok(season) ? ((season.progression || {}).drivers || {}) : {};
  var form = Object.keys(prog).map(function (id) { var p = prog[id] || []; var n = p.length; return n >= 4 && isNum(p[n - 1]) && isNum(p[n - 4]) ? { id: id, v: p[n - 1] - p[n - 4] } : null; }).filter(Boolean).sort(function (a, b) { return b.v - a.v; });
  if (form[0]) items.push({ sport: 'f1', title: 'Last three rounds', name: PD.driverName(form[0].id), value: form[0].v, unit: 'points', next: form[1] ? { name: PD.driverName(form[1].id), value: form[1].v } : null, href: PD.driverHref(form[0].id), expl: 'Points scored over the last three rounds.' });
  if (PD.ok(value) && value.drivers) {
    var minR = value.min_races || 5;
    var D = PD.rowsOf(value.driver_cols, value.drivers).filter(function (r) { return isNum(r.pace_tm) && (r.races || 0) >= minR; }).sort(function (a, b) { return b.pace_tm - a.pace_tm; });
    if (D[0]) items.push({ sport: 'f1', title: 'Fastest v team-mate', name: D[0].name, value: PD.signed(D[0].pace_tm, 2) + '%', unit: 'of a lap', next: D[1] ? { name: D[1].name, value: PD.signed(D[1].pace_tm, 2) + '%' } : null, href: PD.driverHref(D[0].id), expl: 'Race pace with the car taken out.' });
  }
  if (PD.ok(value) && value.teams) {
    var T = PD.rowsOf(value.team_cols, value.teams).filter(function (r) { return isNum(r.car); }).sort(function (a, b) { return b.car - a.car; });
    if (T[0]) items.push({ sport: 'f1', title: 'Fastest car', name: PD.teamName(T[0].id), value: PD.signed(T[0].car, 2) + '%', unit: 'of a lap v the field', next: T[1] ? { name: PD.teamName(T[1].id), value: PD.signed(T[1].car, 2) + '%' } : null, href: PD.teamHref(T[0].id), expl: 'Car pace at the latest round.' });
  }
  host.innerHTML = items.length ? QK.hotRow(items.slice(0, 5)) : QK.empty('No leaders yet', 'The season has not started.');
}

/* "How sure are we?" teaser from calibration.json (the race simulator's win forecasts, every driver in every race). */
function howSureTeaser() {
  PD.load('calibration.json').then(function (cj) {
    var box = document.getElementById('ov-sure');
    if (!box) return;
    var cb = PD.v2.calib(cj);
    if (!cb) { box.innerHTML = ''; return; }
    var fav = cb.bins.filter(function (b) { return b.lo >= 0.2 && b.n >= 30; }).sort(function (a, b) { return b.n - a.n; })[0];
    box.innerHTML = '<article class="qk-card" style="height:100%"><div class="qk-card-body"><div class="qk-kicker">How sure are we?</div>' +
      (fav ? '<h3 style="margin:8px 0 6px">When we give a driver ' + Math.round(fav.lo * 100) + '–' + Math.round(fav.hi * 100) + '%, they win ' + Math.round(fav.freq * 100) + '% of the time</h3>' +
        '<p style="margin:0 0 6px;color:var(--ink-2)">Across ' + QK.fmt.num(fav.n) + ' drivers we rated like that' + (cb.span ? ' (' + esc(cb.span) + ')' : '') + ', our average call was ' + QK.fmt.pct(fav.mean_p, 1) + ' and they won ' + QK.fmt.pct(fav.freq, 1) + '.</p>' : '') +
      QK.note('<b>Brier score ' + (isNum(cb.brier) ? cb.brier.toFixed(3) : '—') + '</b> over ' + QK.fmt.num(cb.n) + ' driver-races: 0 is perfect' + (isNum(cb.base) ? ', and giving every driver the same ' + QK.fmt.pct(cb.base_rate, 0) + ' would score ' + cb.base.toFixed(3) : '') + '. Lower is better.') +
      '<a class="qk-more" style="display:inline-block;margin-top:14px" href="#/model">The full record</a></div></article>';
  });
}

function tiles(idx, season, race, value, meta) {
  var next = idx.next;
  var st = PD.ok(season) ? (season.standings || {}).drivers || [] : [];
  var ct = PD.ok(season) ? (season.standings || {}).constructors || [] : [];
  var lead = st[0], second = st[1];
  var dr = titleRows(season, 'drivers'), cr = titleRows(season, 'constructors');
  var ns = nextSim(race);
  var fav = ns ? Object.keys(ns.sim.drivers).sort(function (a, b) { return ns.sim.drivers[b].p_win - ns.sim.drivers[a].p_win; })[0] : null;
  var prog = PD.ok(season) && lead ? ((season.progression || {}).drivers || {})[lead.driver] : null;
  var T = PD.ok(value) && value.teams ? PD.rowsOf(value.team_cols, value.teams).filter(function (r) { return isNum(r.car); }).sort(function (a, b) { return b.car - a.car; }) : [];
  var list = [];
  if (next) list.push(PD.kpi(PD.shortRace(next.name) + ' favourite', fav ? esc(PD.driverCode(fav)) + ' ' + PD.pct(ns.sim.drivers[fav].p_win, 0) : '—', fav ? 'our win chance · ' + (ns.post ? 'after qualifying' : 'before qualifying') : 'forecast not built yet', { signal: true, href: PD.raceHref(next.year, next.round), tip: 'Our chance of winning the next Grand Prix, from 20,000 simulated races' }));
  if (dr[0]) list.push(PD.kpi('Drivers’ title', esc(PD.driverCode(dr[0].id)) + ' ' + PD.pct(dr[0].model, dr[0].model > 0.99 ? 2 : 1), 'our chance · from simulated seasons', { signal: true, href: PD.driverHref(dr[0].id), tip: 'Our chance of winning the drivers’ championship' }));
  else if (meta.champion) list.push(PD.kpi('Champion', esc(PD.driverName(meta.champion)), 'drivers’ title', { text: true, href: PD.driverHref(meta.champion) }));
  list.push(PD.kpi('Leader', lead ? esc(PD.driverCode(lead.driver)) + ' ' + PD.pts(lead.points) : '—', lead ? (second ? PD.pts(lead.points - second.points) + ' clear of ' + esc(PD.driverCode(second.driver)) : 'points') : '', { href: lead ? PD.driverHref(lead.driver) : null, trend: prog && prog.length > 1 ? prog : null, trendColor: lead ? PD.tc(lead.team) : null, trendLabel: 'Points after each round' }));
  list.push(PD.kpi('Constructors', ct[0] ? esc(PD.teamAbbr(ct[0].team)) + ' ' + PD.pts(ct[0].points) : '—', ct[0] ? esc(PD.teamName(ct[0].team)) + (cr[0] ? ' · our title chance ' + PD.pct(cr[0].model, cr[0].model > 0.99 ? 2 : 1) : '') : '', { href: ct[0] ? PD.teamHref(ct[0].team) : null }));
  list.push(PD.kpi('Fastest car', T[0] ? esc(PD.teamAbbr(T[0].id)) + ' ' + PD.signed(T[0].car, 2) + '%' : '—', T[0] ? 'of a lap faster than the field, latest round' : 'needs lap data', { href: T[0] ? PD.teamHref(T[0].id) : null, tip: 'Our car-pace estimate from the lap-time model' }));
  list.push(PD.kpi('Rounds run', PD.ok(season) ? season.rounds_done + '/' + season.rounds_total : '—', PD.ok(season) ? (season.calendar || []).filter(function (c) { return c.sprint; }).length + ' sprint weekends' : ''));
  PD.set('ov-kpis', PD.kpis(list));
}

function weekend(next, race, season) {
  var host = document.getElementById('ov-wk');
  if (!host) return;
  if (!next) { host.innerHTML = PD.secHead('Season complete', 'No race left this season', 'The final standings and every race centre stay below.', '<a class="qk-btn" href="#/races">Every race</a>'); return; }
  var circ = next.circuit || {};
  var ns = nextSim(race);
  host.innerHTML = PD.secHead('Next up · round ' + next.round + ' of ' + ((season || {}).rounds_total || ''), esc(next.name), PD.circuitLink(circ.id, circ.name) + (circ.locality ? ' · ' + esc(circ.locality) : '') + (circ.country ? ', ' + esc(circ.country) : '') + ' · ' + esc(PD.fmtDate(next.date, { year: false })),
    '<a class="qk-btn primary" href="' + PD.raceHref(next.year, next.round) + '">Race centre</a>') +
    PD.grid(
      PD.card('Race weekend', 'Times in your time zone (' + esc(tzName()) + ').', '<div class="pd-wk"><div class="pd-cd" id="ov-cd"></div><ul class="pd-sched" id="ov-sched" aria-label="Weekend schedule"></ul></div>', { span: 5 }) +
      PD.card('Who wins the ' + esc(PD.shortRace(next.name)) + ' Grand Prix', ns ? (ns.post ? 'After qualifying' : 'Before qualifying') + ' · our chance from ' + (ns.sim.n ? Number(ns.sim.n).toLocaleString('en-GB') : '20,000') + ' simulated races' + (isNum(ns.sim.p_sc) ? ' · safety car ' + PD.pct(ns.sim.p_sc, 0) : '') : 'The forecast is built once the weekend is near.',
        '<div id="ov-who"></div>', { span: 7, foot: '<span>Podium chance beside each name</span><a href="' + PD.raceHref(next.year, next.round) + '">Every driver and position →</a>' }));
  weekendClock(sessionsOf(next), 'ov-cd', 'ov-sched');
  if (!ns) { PD.set('ov-who', PD.empty('No forecast yet', 'The forecast for ' + next.name + ' is not built yet.')); return; }
  var ds = ns.sim.drivers;
  var ids = Object.keys(ds).sort(function (a, b) { return ds[b].p_win - ds[a].p_win; }).slice(0, 10);
  var rows = PD.v2.chanceRows(ids, function (id) { return ds[id].p_win; }, true, null);
  rows.forEach(function (r, i) { r.sub = 'podium ' + PD.pct(ds[ids[i]].p_podium, 0); });
  PD.set('ov-who', QK.chances(rows, { oursName: 'Our win chance' }));
}

function title(season) {
  var draw = function (kind) {
    PD.v2.pointsForecast('ov-prog', season, kind, 6);
    PD.v2.rangeChart('ov-range', season, kind, 10);
    var hw = document.getElementById('ov-hist-w');
    if (hw) hw.hidden = !PD.v2.titleHistory('ov-hist', season, kind, 6, 'pts');
    standings(season, kind);
    var host = document.getElementById('ov-odds');
    if (!host) return;
    if (!PD.ok(season) || !season.championship) { PD.set('ov-odds-s', 'The championship is decided.'); host.innerHTML = PD.muted('No simulation for a finished season.'); return; }
    var rows = titleRows(season, kind).slice(0, 8);
    var isD = kind === 'drivers';
    PD.set('ov-odds-s', 'Our chance of the ' + (isD ? 'drivers’' : 'constructors’') + ' title' + (rows[0] && rows[0].model > 0.995 ? ': ' + esc(isD ? PD.driverName(rows[0].id) : PD.teamName(rows[0].id)) + ' wins ' + PD.pct(rows[0].model, 2) + ' of simulated seasons' : ''));
    var cr = PD.v2.chanceRows(rows.map(function (r) { return r.id; }), function (id) { return season.championship[kind][id].p_title; }, isD, null);
    cr.forEach(function (r, i) { r.sub = 'exp. ' + PD.num(rows[i].c.exp_points, 0) + ' pts'; });
    host.innerHTML = QK.chances(cr, { max: 1, oursName: 'Our title chance' });
  };
  draw('drivers');
  PD.wireSeg(document, 'ov-k', draw);
}

function standings(season, kind) {
  var host = document.getElementById('ov-std');
  if (!host) return;
  if (!PD.ok(season)) { host.innerHTML = PD.muted('Standings not built yet.'); return; }
  var isD = kind === 'drivers';
  var list = ((season.standings || {})[kind] || []).slice(0, 10);
  var prog = ((season.progression || {})[kind]) || {};
  var leadPts = list.length ? list[0].points : 0;
  QK.leaderboard(host, { dense: true, rowHref: function (r) { return isD ? PD.driverHref(r.id) : PD.teamHref(r.id); }, columns: [
    { key: 'pos', label: 'Pos', num: true },
    { key: 'name', label: isD ? 'Driver' : 'Constructor', type: 'entity', sub: 'sub', mark: function (r) { return { name: PD.teamName(r.team), abbr: PD.teamAbbr(r.team), colour: PD.teamColour(r.team) }; }, href: function (r) { return isD ? PD.driverHref(r.id) : PD.teamHref(r.id); } },
    { key: 'trend', label: 'Trend', type: 'spark' },
    { key: 'points', label: 'Pts', num: true, fmt: function (v) { return '<b>' + PD.pts(v) + '</b>'; } },
    { key: 'gap', label: 'Gap', num: true, fmt: function (v) { return v ? '−' + PD.pts(v) : '—'; } }
  ], rows: list.map(function (r) { var id = isD ? r.driver : r.team; return { pos: r.pos, id: id, team: r.team, name: isD ? PD.driverName(id) : PD.teamName(id), sub: isD ? PD.teamAbbr(r.team) : '', trend: prog[id] || [], points: r.points, gap: leadPts - r.points }; }) });
}

function cars(value) {
  if (!PD.ok(value) || !value.teams) return PD.ch.none('ov-cars', 'Car pace is estimated once a race has lap data.');
  var T = PD.rowsOf(value.team_cols, value.teams).filter(function (r) { return isNum(r.car); }).sort(function (a, b) { return b.car - a.car; });
  PD.ch.hbars('ov-cars', T.map(function (r) { return { label: PD.teamName(r.id), value: r.car, lo: r.car - (r.car_se || 0), hi: r.car + (r.car_se || 0), colour: PD.teamColour(r.id), href: PD.teamHref(r.id),
    sub: 'Season mean ' + PD.signed(r.car_mean, 2) + '% · last five rounds ' + PD.signed(r.trend, 2) }; }), { fmt: function (v) { return PD.signed(v, 2) + '%'; }, name: 'Car pace', errName: '±1 se', xName: 'Car pace (% of a lap)', label: 'Car pace by team' });
}

function bestDrivers(value) {
  if (!PD.ok(value) || !value.drivers) return PD.ch.none('ov-drv', 'Driver value needs lap data (1994 on).');
  var minR = value.min_races || 5;
  var D = PD.rowsOf(value.driver_cols, value.drivers).filter(function (r) { return isNum(r.pace_tm) && (r.races || 0) >= minR; }).sort(function (a, b) { return b.pace_tm - a.pace_tm; }).slice(0, 10);
  PD.ch.hbars('ov-drv', D.map(function (r) { return { label: r.name, value: r.pace_tm, lo: r.pace_tm - (r.pace_tm_se || 0), hi: r.pace_tm + (r.pace_tm_se || 0), colour: PD.teamColour(r.team), href: PD.driverHref(r.id), sub: PD.teamName(r.team) + ' · ' + r.races + ' races' }; }),
    { fmt: function (v) { return PD.signed(v, 2) + '%'; }, name: 'Above team-mate', errName: '±1 se', xName: 'Pace above team-mate (%)', label: 'Pace above the team-mate' });
}

function favourites(season) {
  if (!PD.ok(season)) return PD.ch.none('ov-fav', 'No calendar.');
  var done = (season.calendar || []).filter(function (c) { return c.status === 'done' && (c.p_win_top || []).length; }).sort(function (a, b) { return a.round - b.round; });
  if (!done.length) return PD.ch.none('ov-fav', 'No forecasts stored for this season.');
  var won = done.filter(function (c) { return c.winner === c.p_win_top[0][0]; }).length;
  var mean = PD.mean(done.map(function (c) { return c.p_win_top[0][1]; }));
  PD.ch.columns('ov-fav', { cats: done.map(function (c) { return 'R' + c.round; }), label: 'Our favourite win chance by round',
    series: [{ name: 'Our favourite’s win chance', data: done.map(function (c) { return c.p_win_top[0][1]; }), colours: done.map(function (c) { return c.winner === c.p_win_top[0][0] ? PD.teamColour(c.winner_team || PD.driverTeam(c.winner)) : PD.col('faint'); }), fmt: function (v) { return PD.pct(v); } }],
    fmt: function (v) { return Math.round(v * 100) + '%'; }, yMin: 0, xName: 'Round', yName: 'Our favourite’s win chance',
    tipLabel: function (i) { var c = done[i]; return 'R' + c.round + ' ' + c.name + ': ' + PD.driverName(c.p_win_top[0][0]) + (c.winner === c.p_win_top[0][0] ? ' won' : ' (winner ' + PD.driverName(c.winner) + ')'); } });
  var n = document.getElementById('ov-fav');
  if (n) n.insertAdjacentHTML('afterend', '<p class="pd-cap">Our favourite won <b>' + won + ' of ' + done.length + '</b> races; its average win chance was ' + PD.pct(mean, 0) + ', so about ' + PD.num(mean * done.length, 1) + ' wins were expected.</p>');
}

function lastRace(last, season) {
  if (!last || !last.winner) { PD.set('ov-last', PD.muted('No race run yet this season.')); return; }
  var c = PD.ok(season) ? (season.calendar || []).filter(function (x) { return x.round === last.round; })[0] || {} : {};
  var fav = (c.p_win_top || [])[0];
  var team = last.winner_team || PD.driverTeam(last.winner);
  PD.set('ov-last', '<div class="pd-last" style="--tc:' + esc(PD.tc(team)) + '"><div class="qk-kicker">' + esc(last.name) + ' · ' + esc(PD.fmtDate(last.date, { year: false })) + '</div>' +
    '<div class="pd-last-win">' + PD.mark(team, 'lg') + '<div><div class="pd-last-name">' + PD.driverLink(last.winner, { dot: false }) + '</div><div class="qk-sub">' + esc(PD.teamName(team)) + ' · winner</div></div></div>' +
    PD.kpis([PD.kpi('Pole', c.pole ? PD.driverLink(c.pole, { code: true }) : '—', '', { text: true }), PD.kpi('Fastest lap', c.fastest ? PD.driverLink(c.fastest, { code: true }) : '—', '', { text: true }),
      PD.kpi('Our favourite', fav ? PD.driverLink(fav[0], { code: true }) : '—', fav ? PD.pct(fav[1]) + ' to win' + (fav[0] === last.winner ? ' · won' : '') : '', { text: true, signal: true })], 'pd-kpis-3') +
    '<div class="pd-cardlink"><a href="' + PD.raceHref(last.year, last.round) + '">Race centre: laps, strategy, awards →</a></div></div>');
}

function fantasy(F) {
  if (!PD.ok(F) || !F.drivers || !F.projection_ok) return PD.ch.none('ov-fan', F && F.reason ? F.reason : 'No fantasy projection right now.');
  var D = PD.rowsOf(F.driver_cols, F.drivers).filter(function (r) { return isNum(r.next); }).sort(function (a, b) { return b.next - a.next; }).slice(0, 8);
  PD.ch.hbars('ov-fan', D.map(function (r) { return { label: r.name, value: r.next, lo: r.p10, hi: r.p90, colour: PD.teamColour(r.team), href: PD.driverHref(r.id), sub: 'Floor ' + PD.num(r.p10, 0) + ', ceiling ' + PD.num(r.p90, 0) + ' · value ' + PD.signed(r.value, 1) }; }),
    { fmt: function (v) { return PD.num(v, 1); }, name: 'Projected points', errName: '10th–90th pct', xName: 'Projected fantasy points', label: 'Fantasy projections' });
}

PD.route('overview', render);
})(window.PD);
