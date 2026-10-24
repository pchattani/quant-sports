/* The Quant Paddock — Overview (#/), on kit v4 "Broadcast" (MIGRATION_V4.md, after rk-overview.js):
 *   the intro band (what the site covers, three quick links: the next race centre, Standings, Drivers);
 *   "This week in F1": the stage line (the next round, rounds and points left, the gap at the top), then the top lines
 *   from index.json "digest" (scripts/build_paddock.py digest_payload): the biggest title-chance mover between the
 *   last two rounds (the title favourite until title_history holds two), the last race (the upset of the week when
 *   the winner had under 40% before the start and was not our favourite), the form driver over three rounds, and
 *   the next session; then the next Grand Prix as the diagonal split hero (our favourite against our second pick in
 *   their constructors' colours), tagged with the live or next session in the reader's time ("Live now · Practice 1",
 *   "Tomorrow · Qualifying"), never "Our pick"; with no race in the coming week the title fight leads instead;
 *   "N calls. Our numbers." (kit game cards with the constructor-colour stripe and a reason each: the favourite, the
 *   closest podium call, the outsider, the title fight, the closest team-mate fight on points, the safety car); the
 *   black power list (QK.band + QK.hotRow); "We say it. Then we check it." (QK.howSure from calibration.json) beside
 *   "Who's for real?" (QKC.quadrant: points per start against race pace); "What's that number?"; the race weekend
 *   (countdown, schedule, our win chance); the title race (points so far and our projection, 538 style; title
 *   chances in constructor colours; how the race has moved, with the 90% band, once title_history holds three
 *   rounds; the season-end points range; standings with trends); car against driver; how our favourite has fared,
 *   the last race and the fantasy projections. No market anywhere here.
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
    var now = QK.now();
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

/* ── the landing top (the same shape on every sport overview; the Rink's rk-overview.js is the reference) ── */
var WORDS = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine'];

/* "Live now" | "Tonight" | "Today" | "Tomorrow" | the weekday | the date, in the reader's own time (QK.now()). */
function whenLabel(iso, live) {
  if (live) return 'Live now';
  var d = new Date(iso), now = new Date(QK.now());
  if (isNaN(d)) return '';
  var d0 = function (x) { var y = new Date(x.getTime()); y.setHours(0, 0, 0, 0); return y.getTime(); };
  var n = Math.round((d0(d) - d0(now)) / 864e5);
  if (n === 0) return d.getHours() >= 17 ? 'Tonight' : 'Today';
  if (n === 1) return 'Tomorrow';
  if (n > 1 && n < 7) return d.toLocaleDateString('en-GB', { weekday: 'long' });
  return QK.fmt.date(iso);
}
function intro(o) {
  return '<section class="ql-intro" aria-label="About this site"><div class="ql-intro-l"><div class="qk-greet-date">' + esc(o.tag) + '</div>' +
    '<h1>' + esc(o.title) + '</h1><p>' + esc(o.lede) + '</p></div>' +
    '<nav class="ql-links" aria-label="Start here">' + o.links.map(function (l) { return '<a href="' + esc(l.href) + '"><b>' + esc(l.label) + '</b><span>' + esc(l.sub) + '</span></a>'; }).join('') + '</nav></section>';
}
/* a date-only payload day ("2026-10-25") in en-GB without a time-zone shift */
function day(d) { return QK.fmt.date(String(d || '').length === 10 ? d + 'T12:00:00' : d); }
function ptsOf(d) { return (d > 0 ? '+' : '−') + Math.abs(Math.round(d * 100)) + ' pts'; }

/* The weekend's state at the reader's clock: the live session, else the next one (sessionsOf: the weekend's
   sessions in order), and whether the Grand Prix is within the coming week. */
function weekendNow(next) {
  if (!next) return null;
  var list = sessionsOf(next), now = QK.now();
  var live = list.filter(function (s) { return s.t.getTime() <= now && now < s.t.getTime() + (SESSION_LEN_MIN[s.key] || 60) * 60000; })[0];
  var up = list.filter(function (s) { return s.t.getTime() > now; })[0];
  var race = list.filter(function (s) { return s.key === 'race'; })[0];
  var rt = race ? race.t.getTime() : (PD.parseDate(next.date) || { getTime: function () { return NaN; } }).getTime();
  return { live: live || null, next: up || null, race: race || null, soon: isFinite(rt) && rt - now < 7 * 864e5 && rt + 3 * 36e5 > now };
}
/* "Round 18 of 23 next: the United States Grand Prix, Sun 25 Oct. Six rounds and up to 150 points left; ..." */
function stageLine(st) {
  if (!st) return '';
  var n = st.next, parts = [];
  if (n) parts.push('Round ' + n.round + ' of ' + st.total + ' next: the ' + n.name + ', ' + QK.fmt.date(n.start) + '.');
  else parts.push('The season is complete.');
  if (st.left) parts.push((WORDS[st.left] || st.left) + ' round' + (st.left === 1 ? '' : 's') + (st.sprints_left ? ' and ' + st.sprints_left + ' sprint' + (st.sprints_left === 1 ? '' : 's') : '') + ' left, up to ' + st.points_left + ' points for one driver.');
  if (st.leader && st.second && isNum(st.gap)) parts.push(PD.driverSurname(st.leader) + ' leads ' + PD.driverSurname(st.second) + ' by ' + PD.pts(st.gap) + '.');
  return parts.join(' ');
}
function weekTiles(dig, season, wk, next) {
  var out = [];
  var mv = dig.movers;
  var ch = PD.ok(season) && season.championship ? season.championship.drivers || {} : {};
  if (mv && (mv.up.length || mv.down.length)) {
    var up = mv.up[0], dn = mv.down[0], lead = up || dn;
    out.push({ label: 'Biggest mover', value: PD.driverCode(lead.key) + ' ' + ptsOf(lead.d), href: PD.driverHref(lead.key), signal: true,
      sub: PD.driverName(lead.key) + (lead.d > 0 ? ' climbed' : ' slipped') + ' to ' + PD.pct(lead.p, 0) + ' in our title chance after round ' + mv.after_round + '.' + (up && dn ? ' Biggest fall: ' + PD.driverCode(dn.key) + ' ' + ptsOf(dn.d) + '.' : '') });
  } else {
    var ids = Object.keys(ch).filter(function (d) { return isNum(ch[d].p_title); }).sort(function (a, b) { return ch[b].p_title - ch[a].p_title; });
    if (ids[0]) {
      var st = dig.stage || {};
      out.push({ label: 'Title favourite', value: PD.driverCode(ids[0]) + ' ' + PD.pct(ch[ids[0]].p_title, ch[ids[0]].p_title > 0.99 ? 1 : 0), href: '#/standings?tab=odds', signal: true,
        sub: PD.driverName(ids[0]) + (st.leader === ids[0] && isNum(st.gap) ? ', ' + PD.pts(st.gap) + ' points clear with up to ' + st.points_left + ' left' : '') + ': our chance from 20,000 simulated seasons.' });
    }
  }
  var l = dig.last;
  if (l && l.winner) {
    var recent = (QK.now() - Date.parse(l.start)) < 7 * 864e5;
    out.push({ label: l.upset && recent ? 'Upset of the week' : 'Last race', value: PD.driverCode(l.winner) + (isNum(l.p) ? ' ' + PD.pct(l.p, 0) : ''), href: PD.raceHref(season && season.year || '', l.round),
      sub: PD.driverName(l.winner) + ' won the ' + l.name + ' on ' + QK.fmt.date(l.start) + '.' + (isNum(l.p) ? ' We gave them ' + PD.pct(l.p, 0) + (l.after_quali ? ' after qualifying' : ' before qualifying') + (l.fav === l.winner ? ', our favourite.' : '; our favourite was ' + PD.driverSurname(l.fav) + ' at ' + PD.pct(l.fav_p, 0) + '.') : '') });
  }
  var h = dig.hot;
  if (h) out.push({ label: 'In form', value: PD.driverCode(h.key) + ' +' + PD.pts(h.v), href: PD.driverHref(h.key),
    sub: PD.driverName(h.key) + ': ' + PD.pts(h.v) + ' points over rounds ' + h.rounds[0] + '–' + h.rounds[h.rounds.length - 1] + '.' + (h.next ? ' Next best ' + PD.driverSurname(h.next) + ', ' + PD.pts(h.next_v) + '.' : '') });
  if (wk && (wk.live || wk.next)) {
    var s = wk.live || wk.next;
    out.push({ label: wk.live ? 'On track now' : 'Next session', value: s.label + ' ' + (wk.live ? '' : QK.fmt.time(s.iso)), href: next ? PD.raceHref(next.year, next.round) : '#/races', text: true,
      sub: (wk.live ? 'Live now at the ' : whenLabel(s.iso) + ' at the ') + PD.shortRace(next.name) + ' Grand Prix' + (wk.race && s.key !== 'race' ? '; the race is ' + whenLabel(wk.race.iso).replace(/^(Today|Tonight|Tomorrow)/, function (m) { return m.toLowerCase(); }) + ' at ' + QK.fmt.time(wk.race.iso) : '') + '.' });
  }
  return out;
}

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
  var kseg = function (id) { return PD.seg(id, [['drivers', 'Drivers'], ['constructors', 'Constructors']], 'drivers', 'Championship'); };
  var wk = weekendNow(next);
  var when = next ? (wk && wk.soon ? 'this weekend' : 'next') : 'this season';
  var where = next ? (((next.circuit || {}).locality) || PD.shortRace(next.name)) : '';
  var dig = idx.digest || {};
  el.innerHTML = intro({ tag: 'F1 · ' + y + (next ? ' · round ' + next.round + ' next' : ' · season complete'),
    title: 'Every F1 race, driver and team, by the numbers.',
    lede: 'Our chance for this weekend’s Grand Prix, who’s fast right now, and the fight for both titles, from 20,000 simulated seasons, in plain English.',
    links: [{ label: 'Races', sub: next ? PD.shortRace(next.name) + ' next' : 'Every race centre', href: next ? PD.raceHref(next.year, next.round) : '#/races' },
      { label: 'Standings', sub: 'And the title race', href: '#/standings' }, { label: 'Drivers', sub: 'Pace and percentiles', href: '#/drivers' }] }) +
    '<section class="qk-section ql-week">' + QK.sectionHead({ kicker: 'This week in F1', title: '<span id="ov-wkh">The week so far</span>', html: true, sub: esc(stageLine(dig.stage)) }) +
    '<div id="ov-week"></div><div class="ql-feat" id="ov-feat">' + QK.skeleton('card', 1) + '</div></section>' +
    '<section class="qk-section">' + QK.sectionHead({ kicker: 'What to watch ' + when, title: '<span id="ov-wh">' + (next ? 'Our calls for ' + esc(where) : 'What the numbers say') + '</span>', html: true,
      sub: 'Our numbers only, each with a line on why it’s worth your time. The stripe across the top of each card is our chance.' }) + '<div class="qk-watch" id="ov-watch">' + QK.skeleton('card', 3) + '</div></section>' +
    '<div id="ov-hot"></div>' +
    '<section class="qk-section qk-g75"><div><div id="ov-sure-h"></div><div id="ov-sure"></div></div>' +
    '<div class="pd-ov-real">' + QK.sectionHead({ kicker: 'Who’s for real?', title: 'Results v pace', sub: 'Drivers top-left are scoring more than their pace suggests; bottom-right, the reverse. A lucky run, or something real?' }) +
    '<div class="qk-card"><div class="qk-card-body"><div id="ov-luck" class="qk-chart" role="img" aria-label="Points per race against race pace"></div><p class="qk-caption" id="ov-luck-cap"></p></div></div></div></section>' +
    '<section class="qk-section">' + QK.newHere({ items: [QK.NEW_HERE[0],
      'A <b>percentile</b> ranks a driver against the other regular drivers this season: 90th means better than 90 in 100. Team-mate numbers take the car out.',
      'Every forecast is checked against what happened. <a class="qk-link" href="#/model">The record is on the Model page.</a>'] }) + '</section>' +
    '<section class="qk-section" id="ov-wk"></section>' +
    '<section class="qk-section">' + QK.sectionHead({ kicker: 'Title race', title: 'Who wins the title?', sub: 'Our chances from 20,000 simulated seasons. The lines are points so far, then our expected points for every round still to run.', actions: kseg('ov-k') }) +
    PD.grid(
      PD.card('The title race', 'Championship points by round; past the Today line, our projection.', PD.chartBox('ov-prog', 380, 'Championship points with our projection'), { span: 8 }) +
      PD.card('Title chances', '<span id="ov-odds-s">Our chance of winning the title.</span>', '<div id="ov-odds"></div>', { span: 4, foot: '<span></span><a href="#/standings?tab=odds">Every title chance →</a>' }) +
      '<div class="qk-span-12" id="ov-hist-w" hidden>' + PD.card('How the race has moved', 'Our expected final points after each round, with the band where 90% of simulated seasons end (5th to 95th percentile).', '<div id="ov-hist" class="qk-chart" style="--h:320px" role="img" aria-label="Expected final points after each round, with a 90% band"></div>') + '</div>' +
      PD.card('Where the points land', 'Season-end points: the bar spans the 5th to 95th percentile of the simulated seasons, the dot is our expectation.', PD.chartBox('ov-range', 360, 'Season-end points range'), { span: 6 }) +
      PD.card('Standings', 'Points so far and the trend after every round.', '<div id="ov-std"></div>', { span: 6, flush: true, foot: '<span></span><a href="#/standings">Full standings and magic numbers →</a>' })) + '</section>' +
    '<section class="qk-section">' + QK.sectionHead({ kicker: 'Car and driver', title: 'Who’s fast right now', sub: 'The lap-time model splits pace into the car and the driver. Bars are our estimates with one standard error either side.', actions: '<a class="qk-more" href="#/value">Driver value</a>' }) +
    QK.explain('Pace is a share of a lap: <b>0.5%</b> is about 0.45 seconds on a 90-second lap, roughly the gap between a front-row car and a midfield one.', { title: 'What’s that number?' }) +
    PD.grid(
      PD.card('Fastest cars right now', 'Car race pace at the latest round, % of a lap against the field (right is faster), ±1 standard error.', PD.chartBox('ov-cars', 320, 'Car pace by team'), { span: 6 }) +
      PD.card('Best drivers this season', 'Race pace above the team-mate, % of a lap (the driver alone), ±1 standard error; 5+ races.', PD.chartBox('ov-drv', 320, 'Pace above the team-mate'), { span: 6 }), 'pd-mt') + '</section>' +
    '<section class="qk-section">' + QK.sectionHead({ kicker: 'Track record', title: 'How our favourite fared', sub: 'Our pre-race favourite every round, and the last Grand Prix.', actions: '<a class="qk-more" href="#/model">The full record</a>' }) +
    PD.grid(
      PD.card('Our favourite, round by round', 'Our pre-race favourite each round: its win chance, filled in the team colour when it won.', PD.chartBox('ov-fav', 300, 'Our favourite’s win chance by round'), { span: 7 }) +
      PD.card('Last race', '', '<div id="ov-last"></div>', { span: 5 }) +
      PD.card('Fantasy: top projections', 'Expected points next weekend with our scoring table; whiskers run from the 10th to the 90th percentile.', PD.chartBox('ov-fan', 300, 'Fantasy projections'), { span: 12, foot: '<span></span><a href="#/fantasy">All picks and the schedule →</a>' })) + '</section>';
  howSureBlock();
  var raceP = next ? PD.load(next.year + '/races/' + next.round + '.json') : Promise.resolve(null);
  return Promise.all([PD.load(y + '/season.json'), raceP, PD.load(y + '/value.json'), PD.load(y + '/fantasy.json')]).then(function (arr) {
    if (!PD.alive(el)) return;
    var season = arr[0], race = arr[1], value = arr[2], fan = arr[3];
    var T = weekTiles(dig, season, wk, next);
    PD.set('ov-week', T.length ? QK.stats(T) : '');
    if (T.length >= 3) PD.set('ov-wkh', 'The week in ' + WORDS[T.length].toLowerCase() + ' lines');
    /* the next Grand Prix leads when it is this week, or when the title is all but decided (the title fight would
       say nothing); otherwise the title fight */
    var tr = titleRows(season, 'drivers'), decided = tr[0] && tr[0].model > 0.99;
    PD.set('ov-feat', wk && (wk.soon || wk.live || (decided && next)) ? feature(next, race, season, wk, dig) : raceLead(season, next));
    watch(next, race, season);
    hot(season, value);
    real(value);
    weekend(next, race, season);
    title(season);
    cars(value);
    bestDrivers(value);
    favourites(season);
    lastRace(last, season);
    fantasy(fan);
  });
}

/* The hero: the next Grand Prix as the diagonal split hero (QK.featureCard -> QK.splitHero), our favourite against our
   second pick in their constructors' colours (team-mates: the second falls to slate with the colour as its rule), our
   win chance as the giant numbers and the volt "Our pick" tag. Season over: the champion against the runner-up on
   points. No market. */
function feature(next, race, season, wk, dig) {
  if (!next) {
    var st = PD.ok(season) ? ((season.standings || {}).drivers || []) : [];
    if (!st[0] || !st[1]) return '';
    var c0 = PD.v2.side(st[0].driver, st[0].team), c1 = PD.v2.mates(c0, PD.v2.side(st[1].driver, st[1].team));
    return QK.featureCard({ sport: 'f1', status: 'final', league: 'F1 · ' + (season.year || ''), away: c0, home: c1, as: st[0].points, hs: st[1].points, href: PD.driverHref(st[0].driver) },
      { scribble: 'Champion!', sub: PD.v2.sideSub, note: '<b>What’s that number?</b> Final championship points. ' + esc(PD.driverName(st[0].driver)) + ' finished ' + PD.pts(st[0].points - st[1].points) + ' clear; every race centre is below.' });
  }
  var ns = nextSim(race);
  if (!ns) return QK.explain('Our forecast for the ' + esc(next.name) + ' is built once the weekend is near. <a class="qk-link" href="' + PD.raceHref(next.year, next.round) + '">The race centre</a> has the schedule.', { title: 'Next up.' });
  var R = PD.v2.raceGame(next, ns.sim.drivers, { start: ((next.sessions || {}).race) || next.date, href: PD.raceHref(next.year, next.round), league: 'Round ' + next.round + ' · ' + ((next.circuit || {}).locality || PD.shortRace(next.name)),
    extra: ns.post ? 'The grid is set: this is our forecast after qualifying.' : '' });
  if (!R) return '';
  var tag = wk && wk.live ? 'Live now · ' + wk.live.label : wk && wk.next && wk.soon ? whenLabel(wk.next.iso) + ' · ' + wk.next.label : 'The next Grand Prix';
  var F = (dig || {}).featured || {}, fr = (F.today || [])[0] || F.week;
  var why = fr && fr.why && fr.why.length ? '<b>Why this race?</b> ' + esc(fr.why.join(' and ').replace(/^./, function (c) { return c.toUpperCase(); })) + '. ' : '';
  return QK.splitHero(R.g, { tag: tag, homeFirst: true, sub: PD.v2.sideSub, note: why + (R.note || '') });
}
/* No Grand Prix in the coming week: the title fight leads instead (our title chances in constructor colours). */
function raceLead(season, next) {
  var rows = titleRows(season, 'drivers').slice(0, 6);
  if (!rows.length) return next ? feature(next, null, season, null, null) : '';
  var cr = PD.v2.chanceRows(rows.map(function (r) { return r.id; }), function (id) { return season.championship.drivers[id].p_title; }, true, null);
  return '<div class="ql-race">' + QK.sectionHead({ kicker: next ? 'No race this weekend' : 'Season complete', title: 'So here’s the title fight', tag: 'h3',
    sub: 'Our chance of the drivers’ title from 20,000 simulated seasons.' + (next ? ' Next up: the ' + next.name + ', ' + day(next.date) + '.' : '') }) + QK.chances(cr, { max: 1, key: false, oursName: 'Our title chance' }) + '</div>';
}

/* "What to watch": up to six calls from our own numbers (no market), each a kit game card with the constructor-colour
   stripe split by our chance: the favourite, the closest podium call, the best outsider, the title fight, the closest
   team-mate fight on points and the safety car. */
function watch(next, race, season) {
  var host = document.getElementById('ov-watch');
  if (!host) return;
  var ns = nextSim(race), cards = [];
  var rh = next ? PD.raceHref(next.year, next.round) : '#/races';
  var ds = ns ? ns.sim.drivers : {};
  var ids = Object.keys(ds).sort(function (a, b) { return ds[b].p_win - ds[a].p_win; });
  var row = function (id, p, fav, sub) { var t = PD.driverTeam(id); return { team: t, name: PD.driverName(id), sub: sub || (t ? PD.teamName(t) : ''), p: p, fav: fav }; };
  if (ids.length) {
    var f = ids[0], p = ds[f].p_win, n = Math.round(1 / Math.max(0.01, 1 - p));
    cards.push({ kicker: 'The favourite · to win', team: PD.driverTeam(f), stripe: p, href: PD.driverHref(f), rows: [row(f, p, true)],
      why: p >= 0.5 ? 'A clear favourite, but a ' + PD.pct(1 - p, 0) + ' chance of losing still comes off about 1 race in ' + n + '.' : 'Our favourite, but under 50%: the field beats ' + PD.driverSurname(f) + ' more often than not.' });
    var pod = ids.filter(function (id) { return isNum(ds[id].p_podium); }).sort(function (a, b) { return Math.abs(ds[a].p_podium - 0.5) - Math.abs(ds[b].p_podium - 0.5); })[0];
    if (pod) cards.push({ kicker: 'The closest call · podium', team: PD.driverTeam(pod), stripe: ds[pod].p_podium, href: PD.driverHref(pod), rows: [row(pod, ds[pod].p_podium, true)],
      why: 'Our nearest thing to a coin flip for the top three this weekend.' });
    var dark = ids.slice(3).filter(function (id) { return ds[id].p_win >= 0.01; })[0];
    if (dark) cards.push({ kicker: 'The outsider · to win', team: PD.driverTeam(dark), stripe: ds[dark].p_win, href: PD.driverHref(dark), rows: [row(dark, ds[dark].p_win, true)],
      why: 'Our best pick outside the top three: it comes off about 1 time in ' + Math.round(1 / ds[dark].p_win) + '.' });
  }
  var ch = PD.ok(season) && season.championship ? season.championship.drivers || {} : null;
  var st = PD.ok(season) ? ((season.standings || {}).drivers || []) : [];
  if (ch && st[0]) {
    var lead = st[0], sec = st[1], left = (season.rounds_total || 0) - (season.rounds_done || 0);
    var pl = (ch[lead.driver] || {}).p_title;
    if (isNum(pl) && pl > 0.995) { /* the title is all but decided: the "Title favourite" tile at the top says so */ }
    else if (sec && isNum((ch[sec.driver] || {}).p_title)) cards.push({ kicker: 'The title fight', team: sec.team, stripe: ch[sec.driver].p_title, href: '#/standings?tab=odds', ft: 'Our title chance · ',
      rows: [{ team: lead.team, name: PD.driverName(lead.driver), sub: PD.pts(lead.points) + ' points', p: (ch[lead.driver] || {}).p_title, fav: true }, { team: sec.team, name: PD.driverName(sec.driver), sub: PD.pts(sec.points) + ' points', p: ch[sec.driver].p_title }],
      why: 'Can ' + PD.driverSurname(sec.driver) + ' catch ' + PD.driverSurname(lead.driver) + '? ' + PD.pts(lead.points - sec.points) + ' points behind with ' + left + ' round' + (left === 1 ? '' : 's') + ' left.' });
  }
  if (st.length) {
    var byT = {};
    st.forEach(function (r) { if (r.points >= 20) (byT[r.team] = byT[r.team] || []).push(r); });
    var pair = Object.keys(byT).filter(function (t) { return byT[t].length >= 2; }).map(function (t) { return byT[t]; }).sort(function (a, b) { return Math.abs(a[0].points - a[1].points) - Math.abs(b[0].points - b[1].points); })[0];
    if (pair) {
      var a = pair[0], b = pair[1], gap = Math.abs(a.points - b.points);
      var ea = (ds[a.driver] || {}).exp_pos, eb = (ds[b.driver] || {}).exp_pos;
      cards.push({ kicker: 'Team-mates · points so far', team: a.team, stripe: a.points / Math.max(1, a.points + b.points), href: '#/compare/drivers/' + encodeURIComponent(a.driver) + '/' + encodeURIComponent(b.driver), ft: gap === 1 ? '1 point apart · ' : PD.pts(gap) + ' points apart · ',
        rows: [{ team: a.team, name: PD.driverName(a.driver), text: PD.pts(a.points), fav: true }, { team: b.team, name: PD.driverName(b.driver), text: PD.pts(b.points) }],
        why: 'The closest team-mate fight on points.' + (isNum(ea) && isNum(eb) ? ' This weekend we expect ' + PD.driverSurname(ea <= eb ? a.driver : b.driver) + ' ahead: P' + PD.num(Math.min(ea, eb), 1) + ' v P' + PD.num(Math.max(ea, eb), 1) + ' on average.' : '') });
    }
  }
  if (ns && isNum(ns.sim.p_sc)) cards.push({ kicker: 'The wild card · safety car', stripe: ns.sim.p_sc, href: rh,
    rows: [{ abbr: 'SC', name: 'At least one safety car', sub: next ? PD.shortRace(next.name) + ' Grand Prix' : '', p: ns.sim.p_sc, fav: true }],
    why: ns.sim.p_sc >= 0.5 ? 'More likely than not here, and a safety car reshuffles the strategy for everyone.' : 'Less likely than not here, so the grid order should matter more.' });
  var W = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six'];
  var list = cards.slice(0, 6);
  var hd = document.getElementById('ov-wh');
  if (hd && list.length) hd.textContent = (W[list.length] || list.length) + ' call' + (list.length === 1 ? '' : 's') + '. Our numbers.';
  host.innerHTML = list.length ? list.map(PD.v2.callCard).join('') : QK.empty('Nothing to watch yet', 'The cards appear once the next race forecast is built.');
}

/* "Who's hot": the black power list (QK.band + QK.hotRow); F1 leaders on points, wins, recent form, pace against the
   team-mate and car pace. */
function hot(season, value) {
  var host = document.getElementById('ov-hot');
  if (!host) return;
  var st = PD.ok(season) ? ((season.standings || {}).drivers || []) : [];
  var items = [];
  var kick = function (t) { return 'F1 · ' + (t ? PD.teamAbbr(t) : ''); };
  if (st[0]) items.push({ sport: 'f1', kicker: kick(st[0].team), title: 'Most points', name: PD.driverName(st[0].driver), value: st[0].points, next: st[1] ? { name: PD.driverName(st[1].driver), value: st[1].points } : null, href: PD.driverHref(st[0].driver), expl: 'The championship leader: 25 for a win, 18 for second, down to 1 for tenth, plus sprints.' });
  var w = st.slice().sort(function (a, b) { return (b.wins || 0) - (a.wins || 0); });
  if (w[0] && w[0].wins) items.push({ sport: 'f1', kicker: kick(w[0].team), title: 'Most wins', name: PD.driverName(w[0].driver), value: w[0].wins, next: w[1] ? { name: PD.driverName(w[1].driver), value: w[1].wins || 0 } : null, href: PD.driverHref(w[0].driver), expl: 'Grand Prix wins this season (sprints not counted).' });
  var prog = PD.ok(season) ? ((season.progression || {}).drivers || {}) : {};
  var form = Object.keys(prog).map(function (id) { var p = prog[id] || []; var n = p.length; return n >= 4 && isNum(p[n - 1]) && isNum(p[n - 4]) ? { id: id, v: p[n - 1] - p[n - 4] } : null; }).filter(Boolean).sort(function (a, b) { return b.v - a.v; });
  if (form[0]) items.push({ sport: 'f1', kicker: kick(PD.driverTeam(form[0].id)), title: 'Last three rounds', name: PD.driverName(form[0].id), value: form[0].v, next: form[1] ? { name: PD.driverName(form[1].id), value: form[1].v } : null, href: PD.driverHref(form[0].id), expl: 'Points scored over the last three rounds: the form guide.' });
  if (PD.ok(value) && value.drivers) {
    var minR = value.min_races || 5;
    var D = PD.rowsOf(value.driver_cols, value.drivers).filter(function (r) { return isNum(r.pace_tm) && (r.races || 0) >= minR; }).sort(function (a, b) { return b.pace_tm - a.pace_tm; });
    if (D[0]) items.push({ sport: 'f1', kicker: kick(D[0].team), title: 'Fastest v team-mate, % of a lap', name: D[0].name, value: PD.signed(D[0].pace_tm, 2) + '%', next: D[1] ? { name: D[1].name, value: PD.signed(D[1].pace_tm, 2) + '%' } : null, href: PD.driverHref(D[0].id), expl: 'Race pace with the car taken out: 0.1% is about 0.09 s a lap.' });
  }
  if (PD.ok(value) && value.teams) {
    var T = PD.rowsOf(value.team_cols, value.teams).filter(function (r) { return isNum(r.car); }).sort(function (a, b) { return b.car - a.car; });
    if (T[0]) items.push({ sport: 'f1', kicker: kick(T[0].id), title: 'Fastest car, % of a lap', name: PD.teamName(T[0].id), value: PD.signed(T[0].car, 2) + '%', next: T[1] ? { name: PD.teamName(T[1].id), value: PD.signed(T[1].car, 2) + '%' } : null, href: PD.teamHref(T[0].id), expl: 'Car race pace against the field at the latest round.' });
  }
  if (items.length) host.innerHTML = QK.band(QK.sectionHead({ kicker: 'Who’s hot', title: 'In form right now', sub: 'The top name on five boards, the next best beside each, and a line on what the number means.', actions: '<a class="qk-more" href="#/drivers">Every driver</a>' }) + QK.hotRow(items.slice(0, 5)));
}

/* "We say it. Then we check it." (QK.howSure from calibration.json: the race simulator's win chance before qualifying,
   every driver in every scored race since 2014); the full record is on the Model page. */
function howSureBlock() {
  PD.load('calibration.json').then(function (cj) {
    var box = document.getElementById('ov-sure'), hd = document.getElementById('ov-sure-h');
    if (!box || !hd) return;
    if (!PD.v2.calib(cj)) { box.innerHTML = ''; return; }
    hd.innerHTML = QK.sectionHead({ kicker: 'How sure are we?', title: 'We say it. Then we check it.', sub: 'Every driver in every Grand Prix we have forecast, grouped by the win chance we gave before qualifying. When the two lines match, our numbers mean what they say.',
      actions: '<a class="qk-more" href="#/model">The full record</a>' });
    PD.v2.howSure(box, cj);
  });
}

/* "Who's for real?" (QKC.quadrant): F1's process against results. x is our race pace against the field at the latest
   round (value.json pace_field: driver and car together, % of a lap, right is faster), y is points per start this
   season; the dashed lines sit at the field's medians. Drivers top-left score more than their pace suggests (luck,
   reliability, team orders, a weak field), bottom-right the reverse. Drivers with the value model's minimum races. */
function real(value) {
  var node = document.getElementById('ov-luck');
  if (!node) return;
  if (!PD.ok(value) || !value.drivers) { node.innerHTML = QK.empty('Not yet', 'The chart fills in once the lap-time model has a few races.'); return; }
  var minR = value.min_races || 5;
  var D = PD.rowsOf(value.driver_cols, value.drivers).filter(function (r) { return isNum(r.pace_field) && isNum(r.points) && (r.races || 0) >= minR; });
  if (D.length < 6) { node.innerHTML = QK.empty('Not yet', 'The chart fills in once the lap-time model has a few races.'); return; }
  var pts = D.map(function (r) { return { x: r.pace_field, y: r.points / r.races, name: r.name, label: PD.driverCode(r.id), color: PD.teamColourRaw(r.team) || undefined, href: PD.driverHref(r.id),
    sub: PD.teamName(r.team) + ' · ' + PD.pts(r.points) + ' points in ' + r.races + ' starts' }; });
  var med = function (k) { return PD.median(pts.map(function (p) { return p[k]; })); };
  QKC.quadrant('#ov-luck', { points: pts, xName: 'Race pace against the field (% of a lap, right is faster)', yName: 'Points per start', refX: med('x'), refY: med('y'),
    xFmt: function (v) { return PD.signed(v, 1) + '%'; }, yFmt: function (v) { return PD.num(v, 0); }, corners: { tl: 'Winning on luck?', tr: 'The real deal', bl: 'Struggling', br: 'Due a haul' }, label: 'F1 drivers: race pace against points per start' });
  PD.set('ov-luck-cap', 'F1 ' + (value.year || '') + ', drivers with ' + minR + '+ starts. Pace is our lap-time model’s latest estimate, driver and car together. Dashed lines: the field’s medians. Tap a driver for the page.');
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
    { key: 'name', label: isD ? 'Driver' : 'Constructor', type: 'entity', sub: 'sub', mark: function (r) { return { name: PD.teamName(r.team), abbr: PD.teamAbbr(r.team), colour: PD.teamColourRaw(r.team) }; }, href: function (r) { return isD ? PD.driverHref(r.id) : PD.teamHref(r.id); } },
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
