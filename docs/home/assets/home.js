/* The Quant Sports home (kit v4 "Broadcast"). Reads data/home.json (scripts/build_home.py) and refreshes live scores in the
 * browser from each sport's published index.json on GitHub Pages (CORS: Access-Control-Allow-Origin *).
 *
 * Page, top to bottom: the black ticker; a small intro (what The Quant Sports is, three pillars, "How it works", the
 * sports); "Today": the game of the day (the significance rule, oddsmarkets/common/featured.py, ranked in the
 * builder: never the closest call, never "Our pick") beside the week's top lines (the biggest swing in a title
 * chance, the upset of the week, the team of the week); "Around the sports" (one line per sport: where the season
 * is, the next big game, who's hot); "Six games. Our calls." (ranked by the same score); the black power list; "The
 * season's biggest surprises" (story cards: the biggest moves in a playoff chance since the season started, from
 * the sites' race logs); the volt stat-of-the-day slab; "Who's for real?" beside "On a roll" (each sport's team of
 * the week); the title race; every game; charts of the week; "How it works".
 * Round 6: our chance leads; the market sits beside it, small and grey (market: 'quiet', STYLE_GUIDE.md §3) on the
 * ticker, the game cards and under the game of the day. Our record and calibration live on each site's Model page
 * ("How we're doing"), linked from the foot. ?asof=<ISO> previews an older snapshot (QK.now). */
(function () {
'use strict';
var $ = QK.$, $$ = QK.$$, esc = QK.esc, fmt = QK.fmt, isNum = QK.isNum;
var D = null;               // home.json
var PAGE = window.innerWidth < 600 ? 6 : 12;
var state = { sport: 'all', when: 'now', shown: PAGE, calib: null };
var NUMS = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'];

var shell = QK.shell({
  sport: null,
  search: { load: function () {
    return QK.fetchJSON('data/search.json').then(function (j) {
      return (j.rows || []).map(function (r) { return { sport: r[0], t: r[1], s: r[2], href: r[3] }; });
    });
  } }
});

function sportOf(k) { return QK.sport(k) || { label: k, accent: 'var(--accent)', site: k }; }
function cap(s) { s = String(s || ''); return s.charAt(0).toUpperCase() + s.slice(1); }
function keyOf(g) { return g.sport + ':' + g.id; }
/* whole days from today to the start, at the viewer's own clock */
function dayDiff(iso) {
  var d = new Date(iso); if (isNaN(d)) return null;
  var t = new Date(QK.now()); t.setHours(0, 0, 0, 0);
  var x = new Date(d); x.setHours(0, 0, 0, 0);
  return Math.round((x - t) / 864e5);
}
/* The one label rule for a start (featured.py when_label): "Live now"; "Tonight · 20:00" only for a start later
 * today at 17:00 or after, in the viewer's own time zone; "Today · 14:00"; "Tomorrow · 03:00"; "Sat · 18:30"
 * within the week; else the date. Never "Our pick". */
function whenTag(g) {
  if (g.status === 'live') return 'Live now';
  if (g.status === 'final') return 'Final';
  var n = dayDiff(g.start), t = g.tba ? 'time TBA' : fmt.time(g.start);
  if (n === null) return '';
  if (n === 0) return (!g.tba && new Date(g.start).getHours() >= 17 ? 'Tonight · ' : 'Today · ') + t;
  if (n === 1) return 'Tomorrow · ' + t;
  if (n > 1 && n < 7) return new Date(g.start).toLocaleDateString('en-GB', { weekday: 'short' }) + ' · ' + t;
  return fmt.date(g.start);
}
/* live, or not yet started (a "pre" game more than 30 min past its start is a lagging status, not the game to lead with) */
function stillOn(g) { return !!g && (g.status === 'live' || (g.status === 'pre' && (new Date(g.start) - QK.now()) / 36e5 > -0.5)); }

/* ───────────────────────────── load */
QK.fetchJSON('data/home.json', { cache: 'no-cache' }).then(function (j) {
  D = j;
  /* accuracy guard: a game still marked live or upcoming 12 hours after its start is a stale snapshot, not a fact */
  D.games = (D.games || []).filter(function (g) { return g.status === 'final' || !g.start || (QK.now() - new Date(g.start)) / 36e5 < 12; });
  D.games.forEach(prep);
  renderAll();
  startLive();
}, function (e) {
  $('#main').innerHTML = QK.empty('The home page data did not load', String(e && e.message || e));
});

/* A live game whose site publishes no live chance keeps only the pre-game one: say so on the card (QK.gameCard). */
function prep(g) {
  if (g.status === 'live' && !isNum(g.wp_home)) g.pre_only = true;
  else delete g.pre_only;
}

function renderAll() {
  var jobs = [renderTicker, renderSportNav, renderFeature, renderToplines, renderAround, renderWatch, renderHot, renderSurprises, renderStats, renderReal, renderRoll, renderRaces, renderChips, renderGames, renderCharts, renderHow];
  jobs.forEach(function (f) { try { f(); } catch (e) { if (window.console) console.error(e); } });
  $('#updated').textContent = 'Data built ' + fmt.ago(D.updated_at) + ' (' + fmt.date(D.updated_at) + ' ' + fmt.time(D.updated_at) + '). Live scores refresh every minute while games are on.';
  QK.seg($('#when'), function (v) { state.when = v; state.shown = PAGE; renderChips(); renderGames(); });
}

function sportCount() { var n = D.sports.length; return (NUMS[n] || String(n)) + (n === 1 ? ' sport' : ' sports'); }
function liveMap() { var m = {}; D.games.forEach(function (g) { if (g.status === 'live') m[g.sport] = true; }); return m; }
function playable() { return D.games.filter(function (g) { return !g.event; }); }

/* ───────────────────────────── ticker (broadcast black) */
function renderTicker() {
  $('#ticker').innerHTML = QK.ticker(playable(), { max: 48, market: 'quiet' });
  shell.setLive(liveMap());
}

/* ───────────────────────────── the intro's sport links ("Pick your sport", high up) */
function renderSportNav() {
  var lm = liveMap();
  $('#sportnav').innerHTML = QK.SPORTS.map(function (q) {
    return '<a class="hm-sn" href="' + esc(QK.sportUrl(q.key)) + '" style="--sa:' + q.accent + '"><span class="hm-sn-ic" aria-hidden="true">' + QK.ICON[q.key] + '</span><span class="hm-sn-l">' + esc(q.label) + '</span>' + (lm[q.key] ? '<span class="hm-sn-live" role="img" aria-label="Live now" title="Live now"></span>' : '') + '</a>';
  }).join('');
}

/* ───────────────────────────── today: the game of the day (the builder's significance rule) */
var featureId = null;
function byKey() { var m = {}; D.games.forEach(function (g) { m[keyOf(g)] = g; }); return m; }
/* the first of the builder's ranked games still upcoming or live at the viewer's clock, else the week's biggest
 * occasion, else nothing (the card then shows a title race) */
function pickFeature() {
  var F = D.featured || {}, m = byKey(), i, r;
  for (i = 0; i < (F.today || []).length; i++) { r = F.today[i]; if (stillOn(m[r.key])) return { g: m[r.key], r: r, kind: 'today', rest: F.today.slice(i + 1).filter(function (x) { return stillOn(m[x.key]); }).map(function (x) { return m[x.key]; }) }; }
  if (F.week && stillOn(m[F.week.key])) return { g: m[F.week.key], r: F.week, kind: 'week', rest: [] };
  return null;
}
var SPORT_LEAGUE = { nfl: 'the NFL', basketball: null, baseball: 'MLB', hockey: 'the NHL', f1: 'Formula 1', tennis: null, college: null, football: null };
function compName(g) {
  if (g.sport === 'tennis') return String(g.league || 'the tour').split(' · ').slice(-1)[0];
  if (g.sport === 'basketball' || g.sport === 'college') return g.league === 'CFB' ? 'college football' : g.league === 'MBB' ? 'men’s college basketball' : g.league === 'WBB' ? 'women’s college basketball' : 'the ' + g.league;
  return SPORT_LEAGUE[g.sport] || g.league || sportOf(g.sport).label;
}
function whyFeature(p) {
  var g = p.g, rs = (p.r.reasons || []).slice(0, 3);
  var when = g.status === 'live' ? 'it is on now' : (g.tba ? 'it is ' + whenTag(g).replace(' · time TBA', '').toLowerCase() : 'it starts ' + whenTag(g).replace(' · ', ' at ').replace(/^(Today|Tonight|Tomorrow)/, function (x) { return x.toLowerCase(); }) + ' your time');
  var lead = p.kind === 'week' ? '<b>Nothing big today.</b> The biggest occasion of the next seven days: ' : '<b>Why this one?</b> ';
  var bits = [compName(g)].concat(rs);
  var txt = lead + esc(cap(bits.join(', '))) + ', and ' + esc(when) + '.';
  return txt + ' We rank games by the size of the competition, the stage, what rides on it in our simulations and the start time. How close it is counts only a little.';
}
function renderFeature() {
  var p = pickFeature(), box = $('#feature');
  var today = fmt.date(new Date(QK.now()).toISOString());
  /* the head follows the lead game's day at the reader's clock: "today" only when it is on today */
  var isToday = !!p && (p.g.status === 'live' || dayDiff(p.g.start) === 0);
  $('#h-today').innerHTML = QK.sectionHead(isToday || !p
    ? { kicker: 'Today · ' + today, title: 'What matters today', sub: 'The game of the day, the week’s biggest swing, its upset and the team on a roll.' }
    : { kicker: 'Coming up · ' + whenTag(p.g).split(' · ')[0], title: 'What matters next', sub: 'Nothing that big is on today. The next game that matters, the week’s biggest swing, its upset and the team on a roll.' });
  featureId = p ? keyOf(p.g) : null;
  if (!p) { box.innerHTML = raceFallback(); return; }
  var g = p.g, live = g.status === 'live';
  var tag = live ? 'Live now · game of the day' : p.kind === 'week' ? 'The big one this week' : isToday ? 'Game of the day' : 'The next big game';
  var chip = live ? undefined : (g.league || sportOf(g.sport).label) + ' · ' + whenTag(g);
  var hero = g.event ? eventCard(g, tag, chip) : QK.splitHero(g, { tag: tag, chip: chip, compact: true, note: false });
  var also = p.rest.slice(0, 2);
  box.innerHTML = hero + (g.event ? '' : QK.marketLine(g, { cls: 'hm-feat-mq' })) + QK.explain(whyFeature(p), { html: true }) +
    (also.length ? '<div class="hm-also"><span class="hm-also-k">' + alsoLabel(also) + '</span>' + also.map(function (x) { return '<a href="' + esc(x.href || '#') + '"><b>' + esc(matchup(x)) + '</b> <span>' + esc((x.league || '') + ' · ' + whenTag(x)) + '</span></a>'; }).join('') + '</div>' : '');
}
/* "Also big today" / "Also big tomorrow" when every game is that day (reader's clock), else "Also coming up" */
function alsoLabel(list) {
  var days = list.map(function (x) { return x.status === 'live' ? 0 : dayDiff(x.start); });
  var same = days.every(function (d) { return d === days[0]; });
  return same && days[0] === 0 ? 'Also big today' : same && days[0] === 1 ? 'Also big tomorrow' : 'Also coming up';
}
function matchup(g) {
  if (g.event) return g.home && g.home.name || 'Grand Prix';
  var a = g.away && g.away.name, h = g.home && g.home.name;
  return g.sport === 'football' ? h + ' v ' + a : a + ' v ' + h;
}
/* an F1 Grand Prix as the feature: our chance for the favourite, the rest of the field after */
function eventCard(g, tag, chip) {
  var nr = (D.charts || {}).f1_next_race || {}, field = (nr.field || []).slice(0, 5);
  return '<a class="qk-card hm-event" href="' + esc(g.href || '#') + '"><div class="hm-event-top"><span class="qk-bchip volt">' + esc(tag) + '</span><span class="qk-bchip">' + esc(chip || '') + '</span></div>' +
    '<div class="hm-event-name">' + esc(g.home && g.home.name || 'Grand Prix') + '</div>' +
    (field.length ? QK.chances(field.map(function (d) { return { label: d.code || d.name, p: d.p || 0, color: d.colour }; }), { key: false }) + '<div class="qk-caption">Our chance of winning the race, each driver out of 100%.</div>' : '') + '</a>';
}
/* nothing scheduled that matters: the tightest title race instead of a minor game */
var FEATURE_RACE = null;
function raceFallback() {
  var F = D.futures || {}, best = null;
  Object.keys(F).forEach(function (k) {
    var rows = (F[k].rows || []).filter(function (r) { return r.p > 0; });
    if (rows.length < 2) return;
    var gap = rows[0].p - rows[1].p;
    if (!best || gap < best.gap) best = { k: k, f: F[k], rows: rows, gap: gap };
  });
  FEATURE_RACE = best ? best.k : null;
  if (!best) return QK.explain('<b>No big game today.</b> The next big games appear here as soon as they are scheduled.', { html: true });
  var sp = best.k.split('_')[0];
  return '<div class="qk-card hm-event"><div class="hm-event-top"><span class="qk-bchip volt">Title race</span><span class="qk-bchip">' + esc(sportOf(sp).label + ' · ' + raceLabel(best.k, best.f.title)) + '</span></div><div class="hm-event-name">' + esc(question(best.k, best.f.title)) + '</div>' +
    QK.chances(chanceRows(best.rows.slice(0, 5), sp), { key: false }) + '<div class="qk-caption">No big game today, so here is the closest race we simulate: ' + esc(raceLede(best.rows.map(function (r) { return { name: r.name, p: r.p }; }))) + '</div></div>';
}

/* ───────────────────────────── today: the week's top lines (oddsmarkets/common/digest.py) */
var SPORT_SHORT = { nfl: 'NFL', hockey: 'NHL', baseball: 'MLB', basketball: 'NBA/WNBA', tennis: 'tennis', college: 'college', football: 'football', f1: 'F1' };
function tl(kicker, num, head, text, href, sport) {
  var sp = sportOf(sport);
  return '<' + (href ? 'a href="' + esc(href) + '"' : 'div') + ' class="hm-tl" style="--sa:' + (sp.accent || 'var(--accent)') + '"><div class="hm-tl-k">' + esc(kicker) + '</div>' +
    '<div class="hm-tl-row"><div class="hm-tl-num num">' + num + '</div><div class="hm-tl-head">' + esc(head) + '</div></div><p class="hm-tl-text">' + text + '</p></' + (href ? 'a' : 'div') + '>';
}
function pts(d) { var v = Math.round(Math.abs(d) * 100); return (d > 0 ? '+' : d < 0 ? '−' : '±') + v; }
function sayPct(p) { return Math.round(p * 100) + '%'; }
function inN(p) { var n = Math.round(1 / Math.max(p, 0.01)); return 'about 1 in ' + n; }
function renderToplines() {
  var G = D.digest || {}, out = [];
  var s = G.swing;
  if (s && isNum(s.delta)) {
    var up = s.delta > 0;
    out.push(tl('Biggest swing this week', pts(s.delta) + '<small>pts</small>', s.name + (s.kind === 'playoff' ? ' play-off chance' : ', ' + s.league),
      esc(s.name) + '’s ' + (s.kind === 'playoff' ? 'play-off' : 'title') + ' chance went ' + (up ? 'up' : 'down') + ' from <b>' + sayPct(s.from) + '</b> to <b>' + sayPct(s.to) + '</b> since ' + esc(fmt.date(s.since)) + ', in our season simulations. “Pts” are percentage points.', s.href, s.sport));
  }
  var u = G.upset;
  if (u && isNum(u.p)) {
    var sc = u.score && isNum(u.score[0]) ? ' ' + u.score[0] + '–' + u.score[1] + (u.players ? ' in sets' : '') : '';
    var lg = String(u.league || '').split(' · ');
    var the = THE_SPORTS.indexOf(u.sport) >= 0 && !u.players;
    out.push(tl('Upset of the week', sayPct(u.p), u.players ? surname(u.winner) + ' beat ' + surname(u.loser) : (the ? 'The ' : '') + u.winner + ' beat ' + (the ? 'the ' : '') + u.loser,
      'Before the start we gave ' + (the ? 'the ' : '') + esc(u.winner) + ' a ' + sayPct(u.p) + ' chance, ' + inN(u.p) + '. They won' + esc(sc) + ' (' + esc(lg[lg.length - 1] || SPORT_SHORT[u.sport] || '') + ', ' + esc(fmt.date(u.start)) + '). A chance that size should still come off now and then.', u.href, u.sport));
  }
  var h = ((D.stories || {}).hot || [])[0];
  if (h) {
    var rec = h.w + '–' + h.l + (h.d ? '–' + h.d : '');
    var lg2 = h.league && h.league !== SPORT_SHORT[h.sport] ? h.league : (SPORT_SHORT[h.sport] || '');
    out.push(tl(h.players ? 'Player of the week' : 'Team of the week', esc(rec), (h.players ? '' : (THE_SPORTS.indexOf(h.sport) >= 0 ? 'The ' : '')) + (h.name || h.short),
      esc(h.name || h.short) + (h.players ? ' won ' : ' went ') + h.w + '–' + h.l + (h.d ? '–' + h.d : '') + ' in ' + (h.players ? 'matches' : 'games') + ' over the last week' + (isNum(h.margin) && !h.players ? ', ' + (h.margin >= 0 ? '+' : '−') + Math.abs(Math.round(h.margin)) + ' on the scoreboard' : '') + ' (' + esc(lg2) + '). The best week across our ' + sportCount() + '.', h.href, h.sport));
  }
  $('#toplines').innerHTML = out.length ? out.join('') : QK.explain('<b>This week.</b> The week’s numbers appear here once games have been played.', { html: true });
}
var THE_SPORTS = ['nfl', 'hockey', 'baseball', 'basketball'];
/* 'YYYY-MM-DD' as that calendar day ('Sat 10 Oct'), never shifted by the viewer's time zone */
function ymd(s) { var m = /^(\d{4})-(\d\d)-(\d\d)$/.exec(String(s || '')); return m ? fmt.date(new Date(+m[1], +m[2] - 1, +m[3], 12).toISOString()) : fmt.date(s); }
function surname(n) { var p = String(n || '').split(' '); return p.length > 1 ? p.slice(1).join(' ') : n; }

/* ───────────────────────────── around the sports: one line each (stage, the next big game, who's hot) */
var HOT_OF = { football: ['football'], f1: ['f1'], basketball: [], tennis: ['tennis_atp', 'tennis_wta'], baseball: ['baseball'], nfl: ['nfl'], hockey: ['hockey'], college: [] };
function renderAround() {
  var by = {}; D.sports.forEach(function (s) { by[s.key] = s; });
  var lm = liveMap(), L = D.leaders || {};
  $('#h-around').innerHTML = QK.sectionHead({ kicker: 'Pick your sport', title: 'Around the sports', sub: 'Where each season stands, the next game that matters, and who’s hot. Tap a sport for its own site.' });
  $('#around-grid').innerHTML = QK.SPORTS.map(function (q) {
    var s = by[q.key] || {}, t = s.topline || {}, n = t.next;
    var hot = (HOT_OF[q.key] || []).map(function (k) { var l = L[k]; return l && l.rows && l.rows[0] ? l : null; }).filter(Boolean)[0];
    var hr = hot ? hot.rows[0] : null;
    return '<article class="hm-ar" style="--sa:' + q.accent + '"><a class="hm-ar-top" href="' + esc(QK.sportUrl(q.key)) + '"><span class="hm-ar-ic" aria-hidden="true">' + QK.ICON[q.key] + '</span><span class="hm-ar-name">' + esc(q.label) + '</span>' + (lm[q.key] ? '<span class="qk-pill live">Live</span>' : '') + '<span class="hm-ar-site">' + esc(q.site) + ' →</span></a>' +
      '<p class="hm-ar-stage">' + esc(s.ok === false ? 'Data unavailable right now' : (t.stage || s.status || q.leagues)) + (s.stale ? ' <span class="hm-ar-stale">· data ' + esc(Math.round(s.age_hours)) + ' h old</span>' : '') + '</p>' +
      (n ? '<a class="hm-ar-next" href="' + esc(n.href || QK.sportUrl(q.key)) + '"><span class="k">' + (n.live ? 'Now' : 'Next') + '</span><b>' + esc(n.title) + '</b><span class="w">' + esc(whenTag({ status: n.live ? 'live' : 'pre', start: n.start, tba: n.tba })) + '</span></a>' : '') +
      (hr ? '<a class="hm-ar-hot" href="' + esc(hr.href || '#') + '"><span class="k">Hot</span><b>' + esc(hr.name) + '</b><span class="w num">' + esc(hr.value) + ' ' + esc(hot.unit || hot.title || '') + '</span></a>' : '') + '</article>';
  }).join('');
}

/* ───────────────────────────── what to watch: "Six games. Our calls." (ranked by the significance score) */
function renderWatch() {
  var pool = playable().filter(function (g) { return keyOf(g) !== featureId && stillOn(g) && (g.status === 'live' || (new Date(g.start) - QK.now()) / 36e5 < 36); });
  pool.sort(function (a, b) { return (b.weight || 0) - (a.weight || 0); });
  var per = {}, first = [], rest = [];
  pool.forEach(function (g) { per[g.sport] = (per[g.sport] || 0) + 1; (per[g.sport] <= 2 ? first : rest).push(g); });
  pool = first.concat(rest);
  var later = false;
  if (!pool.length) {
    /* nothing big in the next day and a half: the next games on the calendar instead, said as such */
    pool = playable().filter(function (g) { return keyOf(g) !== featureId && stillOn(g); }).sort(function (a, b) { return a.start > b.start ? 1 : -1; }).slice(0, 6);
    later = pool.length > 0;
  }
  var n = Math.min(6, pool.length);
  var upcoming = playable().filter(function (g) { return g.status !== 'final'; }).length;
  $('#h-watch').innerHTML = QK.sectionHead({ kicker: 'What to watch next', title: n ? cap(NUMS[n]) + ' game' + (n === 1 ? '' : 's') + '. Our calls.' : 'Nothing scheduled yet',
    sub: later ? 'Nothing big starts in the next day and a half, so these are the next games on the calendar. Our chance for each side, the favourite in blue.'
      : n ? 'The biggest games of the next day and a half, at most two per sport. Our chance for each side, the favourite in blue.' : 'The next games appear here as soon as the sports publish them.',
    actions: upcoming ? '<a class="qk-more" href="#games">All ' + upcoming + ' upcoming</a>' : '' });
  $('#watch-grid').innerHTML = QK.watchGrid(pool, { limit: 6, pick: false, card: { why: true, market: 'quiet' } });
}

/* ───────────────────────────── who's hot: the black power list */
var HOT = ['hockey', 'football', 'baseball', 'f1', 'tennis_atp', 'nfl', 'tennis_wta'];
function renderHot() {
  var L = D.leaders || {};
  var items = HOT.filter(function (k) { return L[k] && L[k].rows && L[k].rows.length && L[k].hot; }).slice(0, 5).map(function (k) {
    var l = L[k], r0 = l.rows[0], r1 = l.rows[1], sp = k.split('_')[0];
    return { sport: sp, kicker: sportOf(sp).label, title: l.hot.title, name: r0.name, value: r0.value, unit: l.unit || '', href: r0.href,
      next: r1 ? { name: r1.name, value: r1.value } : null, expl: l.hot.expl };
  });
  $('#hot-band').innerHTML = items.length ? QK.band(QK.sectionHead({ kicker: 'Who’s hot', title: 'The leaderboard, one sport at a time',
    sub: 'The top name in ' + (NUMS[items.length] || items.length) + ' sports, and a line on what the number means.' }) + QK.hotRow(items), { id: 'hot-sec' }) : '';
}

/* ───────────────────────────── stat of the day: the volt slab */
var statIdx = 0, statTimer = null;
function renderStats() {
  var S = D.stats || [];
  var el = $('#sotd');
  if (!S.length) { el.hidden = true; return; }
  statIdx = Math.floor(QK.now() / 864e5) % S.length;
  function paint() {
    var s = S[statIdx], sp = sportOf(s.sport);
    var nav = '<div class="qk-sotd-nav" role="group" aria-label="More stats">' + S.map(function (x, i) { return '<button type="button" aria-label="Stat ' + (i + 1) + ': ' + esc(x.kicker) + '" aria-pressed="' + (i === statIdx) + '" data-i="' + i + '"></button>'; }).join('') + '</div>';
    el.innerHTML = QK.statOfDay({ value: s.value, kicker: 'Stat of the day · ' + sp.label, title: s.title || s.kicker, text: s.text, note: s.note || (s.unit ? '<b>' + esc(s.value) + '</b> ' + esc(s.unit) + '.' : ''), href: s.href }, { nav: nav });
    $$('.qk-sotd-nav button', el).forEach(function (b) { b.addEventListener('click', function () { statIdx = +b.getAttribute('data-i'); paint(); restart(); }); });
  }
  function restart() { if (statTimer) clearInterval(statTimer); if (!QK.reducedMotion()) statTimer = setInterval(function () { statIdx = (statIdx + 1) % S.length; paint(); }, 12000); }
  paint(); restart();
  el.addEventListener('mouseenter', function () { if (statTimer) clearInterval(statTimer); });
  el.addEventListener('mouseleave', restart);
}

/* ───────────────────────────── the season's biggest surprises (story cards from the sites' race logs) */
var WHAT_SHORT = { 'playoff chance': 'Playoff chance', 'postseason chance': 'Postseason chance' };
function renderSurprises() {
  var S = ((D.stories || {}).surprises || []).filter(function (r) { return isNum(r.from) && isNum(r.to); });
  var sec = $('#surprises');
  if (!S.length) { sec.hidden = true; return; }
  var day = function (d) { return ymd(d); };
  sec.innerHTML = QK.sectionHead({ kicker: 'Biggest surprises', title: 'Nobody saw these coming', sub: 'The biggest moves in a ' + (S.every(function (r) { return r.what === 'playoff chance'; }) ? 'playoff' : 'playoff or postseason') + ' chance since each season began, in our season simulations. Up and down, one league at a time.' }) +
    QK.storyCards(S.map(function (r) {
      var up = r.delta > 0, lg = SPORT_SHORT[r.sport] === r.league ? r.league : r.league;
      return { kicker: (up ? 'Climbing · ' : 'Sliding · ') + lg, name: r.name, sub: (WHAT_SHORT[r.what] || cap(r.what)) + ' since ' + day(r.since), sport: r.sport,
        value: (up ? '+' : '−') + Math.round(Math.abs(r.delta) * 100), unit: 'pts', colour: r.colour, mark: r.abbr ? { abbr: r.abbr, colour: r.colour } : null, href: r.href,
        from: { label: 'Then', pos: r.from * 100, value: sayPct(r.from) }, to: { label: 'Now', pos: r.to * 100, value: sayPct(r.to) },
        text: (THE_SPORTS.indexOf(r.sport) >= 0 ? 'The ' : '') + r.short + (up ? ' have climbed from ' : ' have slid from ') + sayPct(r.from) + ' to ' + sayPct(r.to) + ' to ' + (r.what === 'postseason chance' ? 'make the postseason' : r.what === 'playoff chance' ? 'make the playoffs' : 'get there') + '. ' + (up ? (r.from < 0.5 ? 'Outsiders at the start, in the mix now.' : 'From hopeful to near certain.') : (r.from >= 0.5 ? 'Favourites at the start, in trouble now.' : 'A long way back from here.')) };
    }), { cols: Math.min(4, S.length) }) +
    '<p class="qk-caption">“Pts” are percentage points. Each season simulation plays out the rest of the schedule thousands of times with our game forecasts.</p>';
}

/* ───────────────────────────── on a roll: each sport's team (or player) of the week, beside "Who's for real?" */
function renderRoll() {
  var H = ((D.stories || {}).hot || []).slice(1, 4), box = $('#roll');
  if (!H.length) { box.hidden = true; return; }
  box.innerHTML = QK.sectionHead({ kicker: 'On a roll', title: 'Hot this week', sub: 'More of the week’s best runs: wins and losses over the last seven days.' }) +
    QK.storyCards(H.map(function (h) {
      return { kicker: (h.players ? 'Player of the week · ' : 'Team of the week · ') + (h.league || SPORT_SHORT[h.sport] || ''), name: h.name || h.short, sport: h.sport,
        value: h.w + '–' + h.l + (h.d ? '–' + h.d : ''), unit: h.players ? 'this week' : 'last 7 days', colour: h.colour, mark: h.abbr ? { abbr: h.abbr, colour: h.colour } : null, href: h.href,
        text: isNum(h.margin) && !h.players ? (h.margin >= 0 ? '+' : '−') + Math.abs(Math.round(h.margin)) + ' on the scoreboard across ' + h.gp + ' games.' : '' };
    }), { cols: 1 });
}

/* ───────────────────────────── "Who's for real?": results against chances (NHL) */
function renderReal() {
  var X = (D.charts || {}).nhl_xg, box = $('#real');
  var pts = X && X.points ? X.points.filter(function (p) { return isNum(p.x) && isNum(p.y); }) : [];
  if (pts.length < 6) { box.hidden = true; return; }
  var gps = pts.map(function (p) { return p.gp; }).filter(isNum), lo = Math.min.apply(null, gps), hi = Math.max.apply(null, gps);
  var avg = pts.reduce(function (a, p) { return a + p.y; }, 0) / pts.length;
  box.innerHTML = QK.sectionHead({ kicker: 'Who’s for real?', title: 'Results v chances',
    sub: 'Teams top-left are winning more than their chances suggest; bottom-right, the reverse. Early-season luck, or something real?' }) +
    '<div class="qk-card"><div class="qk-card-body"><div id="c-real" class="qk-chart" style="--h:420px"></div><div class="qk-caption">NHL, this season' + (gps.length ? ', ' + (lo === hi ? lo : lo + '–' + hi) + ' games each' : '') + '. Dashed lines: a 50% chance share and the league’s average points. <a class="qk-link" href="' + esc(X.href || QK.sportUrl('hockey')) + '">Standings</a></div></div></div>';
  QKC.quadrant('#c-real', { points: pts.map(function (p) { return { x: p.x * 100, y: p.y * 100, name: p.name, label: p.abbr, color: p.colour, href: p.href, sub: isNum(p.gp) ? p.gp + ' games' : '' }; }),
    xName: 'Share of expected goals at 5-on-5 (%)', yName: 'Points won (% of possible)', refX: 50, refY: avg * 100,
    xFmt: function (v) { return Math.round(v) + '%'; }, yFmt: function (v) { return Math.round(v) + '%'; }, label: 'NHL teams: share of expected goals against points won' });
}

/* ───────────────────────────── title race: team-colour bars, one league at a time */
var TWO_WORD = /(Maple Leafs|Red Wings|Golden Knights|Blue Jackets|Blue Jays|Red Sox|White Sox|Trail Blazers)$/;
function nick(name, sport) {
  if (['hockey', 'nfl', 'basketball', 'baseball'].indexOf(sport) < 0) return name;
  var m = TWO_WORD.exec(name);
  return m ? m[1] : String(name).split(' ').slice(-1)[0];
}
function raceLede(rows) {
  var r = rows.slice().sort(function (a, b) { return b.p - a.p; });
  if (!r.length) return '';
  var top = r[0], nm = top.name;
  if (top.p < 0.2) return 'Nobody’s better than 1 in 5. ' + nm + ' lead our board at ' + fmt.pct(top.p) + '.';
  if (top.p > 0.95) return nm + ': ' + fmt.pct(top.p) + ' in our simulations. All but settled.';
  return nm + ' lead at ' + fmt.pct(top.p) + ', which still misses about ' + Math.max(1, Math.round(10 * (1 - top.p))) + ' times in 10.';
}
/* the market never shows here: rows carry our chance, the team square and colour only */
function chanceRows(rows, sport) {
  return rows.filter(function (r) { return r.p > 0; }).map(function (r) {
    return { label: sport ? nick(r.name, sport) : r.name, p: r.p, href: r.href, color: r.colour, mark: r.abbr ? { abbr: r.abbr, colour: r.colour } : null };
  });
}
var QUESTION = { hockey: 'Who lifts the Stanley Cup?', nfl: 'Who wins the Super Bowl?', baseball: 'Who wins the World Series?', f1: 'Who wins the F1 drivers’ title?' };
function question(id, title) {
  if (QUESTION[id]) return QUESTION[id];
  return 'Who wins the ' + String(title || 'title').replace(/^College football national title$/i, 'college football title') + '?';
}
function raceLabel(id, title) {
  var L = { hockey: 'NHL', nfl: 'NFL', baseball: 'MLB', f1: 'F1', college: 'CFB', college_mbb: 'MBB', college_wbb: 'WBB' };
  return L[id] || String(title || id).replace(/ title$/i, '');
}
var RACE_ORDER = ['hockey', 'basketball_2', 'basketball', 'nfl', 'baseball', 'f1', 'college', 'college_mbb', 'college_wbb'];
function renderRaces() {
  var F = D.futures || {}, ft = (D.charts || {}).football_titles || [];
  /* the race already leading the page (the fallback hero) is not shown twice */
  var tabs = RACE_ORDER.filter(function (k) { return k !== FEATURE_RACE && F[k] && F[k].rows && F[k].rows.filter(function (r) { return r.p > 0; }).length > 1; }).map(function (k) {
    return { id: k, sport: k.split('_')[0], label: raceLabel(k, F[k].title), title: F[k].title || k };
  });
  if (ft.length) tabs.push({ id: 'football', sport: 'football', label: 'Football', title: 'League titles' });
  var sec = $('#races');
  if (!tabs.length) { sec.hidden = true; return; }
  var fl = 0;
  var seg = tabs.length > 1 ? '<div class="qk-seg" id="race-seg" role="group" aria-label="Title race">' + tabs.map(function (t, i) { return '<button type="button" data-value="' + esc(t.id) + '" aria-pressed="' + (i === 0) + '" title="' + esc(t.title) + '">' + esc(t.label) + '</button>'; }).join('') + '</div>' : '';
  sec.innerHTML = '<div id="race-h"></div><div class="qk-card hm-race" id="race-card"></div>';
  function draw(id) {
    var t = tabs.filter(function (x) { return x.id === id; })[0] || tabs[0];
    var rows, title, href = QK.sportUrl(t.sport), extra = '';
    if (t.id === 'football') {
      var L = ft[fl] || ft[0];
      rows = chanceRows(L.rows || []); title = 'Who wins the ' + L.league + '?'; href = L.href || href;
      extra = '<label class="qk-sub" for="fl-sel" style="margin-right:8px">League</label><select class="qk-select" id="fl-sel">' + ft.map(function (l, i) { return '<option value="' + i + '"' + (i === fl ? ' selected' : '') + '>' + esc(l.league) + '</option>'; }).join('') + '</select>';
    } else {
      rows = chanceRows(F[t.id].rows, t.sport); title = question(t.id, t.title);
    }
    $('#race-h').innerHTML = QK.sectionHead({ kicker: 'Title race', title: title, sub: raceLede(rows.map(function (r) { return { name: r.label, p: r.p }; })),
      actions: '<a class="qk-more" href="' + esc(href) + '">Full forecast</a>' });
    $('#race-card').innerHTML = '<div class="hm-race-head">' + (seg || '<span></span>') + (extra ? '<div>' + extra + '</div>' : '') + '</div>' + QK.chances(rows, { limit: 8, key: false }) +
      '<div class="hm-race-foot"><span class="qk-caption" style="margin:0">Our chance from thousands of simulated seasons.</span></div>';
    var sel = $('#fl-sel'); if (sel) sel.addEventListener('change', function (e) { fl = +e.target.value; draw('football'); });
    var sg = $('#race-seg');
    if (sg) {
      $$('button', sg).forEach(function (b) { b.setAttribute('aria-pressed', b.getAttribute('data-value') === t.id ? 'true' : 'false'); });
      QK.seg(sg, function (v) { draw(v); });
    }
  }
  draw(tabs[0].id);
}

/* ───────────────────────────── every game */
function gamesFor() {
  return playable().filter(function (g) {
    if (state.sport !== 'all' && g.sport !== state.sport) return false;
    return state.when === 'results' ? g.status === 'final' : g.status !== 'final';
  });
}
function renderChips() {
  /* each chip counts the games the grid shows under the open tab (upcoming and live, or results), never the others */
  var counts = { all: 0 };
  playable().filter(function (g) { return state.when === 'results' ? g.status === 'final' : g.status !== 'final'; }).forEach(function (g) { counts.all++; counts[g.sport] = (counts[g.sport] || 0) + 1; });
  var chips = [['all', 'All sports', 'var(--signal)', '']].concat(QK.SPORTS.filter(function (s) { return counts[s.key]; }).map(function (s) { return [s.key, s.label, s.accent, QK.ICON[s.key]]; }));
  $('#sport-chips').innerHTML = chips.map(function (c) {
    return '<button type="button" class="qk-chip" data-value="' + c[0] + '" aria-pressed="' + (state.sport === c[0]) + '" style="--ca:' + c[2] + '">' + c[3] + esc(c[1]) + ' <span class="n">' + (counts[c[0]] || 0) + '</span></button>';
  }).join('');
  QK.chips($('#sport-chips'), function (v) { state.sport = v[0] || 'all'; state.shown = PAGE; renderGames(); });
}
function renderGames() {
  var list = gamesFor();
  var order = { live: 0, pre: 1, final: 2 };
  list.sort(function (a, b) {
    if (state.when === 'results') return a.start < b.start ? 1 : -1;
    return order[a.status] - order[b.status] || (a.start > b.start ? 1 : -1);
  });
  var grid = $('#game-grid');
  if (!list.length) { grid.innerHTML = '<div style="grid-column:1/-1">' + QK.empty(state.when === 'results' ? 'No recent results' : 'Nothing scheduled in the window', 'Try another sport, or the other tab.') + '</div>'; $('#game-more').innerHTML = ''; return; }
  var html = '', lastDay = null;
  list.slice(0, state.shown).forEach(function (g) {
    var day = g.status === 'live' ? 'Live now' : fmt.relDay(g.start);
    if (day !== lastDay) { html += '<div class="hm-day">' + esc(day) + '</div>'; lastDay = day; }
    html += QK.gameCard(g, { why: false, market: 'quiet' });
  });
  grid.innerHTML = html;
  var more = list.length - state.shown;
  $('#game-more').innerHTML = more > 0 ? '<button class="qk-btn" type="button">Show ' + Math.min(more, PAGE) + ' more <span class="qk-muted">of ' + more + '</span></button>' : '';
  var b = $('#game-more button'); if (b) b.addEventListener('click', function () { state.shown += PAGE; renderGames(); });
}

/* ───────────────────────────── charts of the week */
function card(span, title, sub, sport, href, body) {
  var sp = sportOf(sport);
  return '<div class="qk-card ' + span + '" style="--accent:' + sp.accent + '"><div class="qk-card-head"><div><div class="qk-kicker" style="margin-bottom:6px">' + esc(sp.label) + '</div><div class="qk-card-title">' + esc(title) + '</div><div class="qk-card-sub">' + esc(sub) + '</div></div></div>' +
    '<div class="qk-card-body">' + body + '</div>' + (href ? '<div class="qk-card-foot"><span>' + esc(sp.site) + '</span><a href="' + esc(href) + '">Open →</a></div>' : '') + '</div>';
}
function renderCharts() {
  var C = D.charts || {}, out = [], jobs = [];
  var tr = C.f1_title_race;
  if (tr && tr.series && tr.series.length) {
    out.push(card('qk-span-8', 'F1 title race', 'Drivers’ points after every round of ' + tr.year + ', each line labelled at its end', 'f1', tr.href, '<div id="c-f1" style="--h:320px"></div>'));
    jobs.push(function () { QKC.line('#c-f1', { x: tr.rounds, xName: 'Round', yName: 'Points', xLabel: function (r) { return 'Round ' + r; }, label: 'F1 drivers championship points by round', series: tr.series.map(function (s) { return { name: s.code || s.name, label: s.code, color: s.colour, dash: s.dash, data: s.points }; }) }); });
  }
  var nr = C.f1_next_race;
  if (nr && nr.field && nr.field.length) {
    out.push(card('qk-span-4', nr.name, 'Our chance of winning the race', 'f1', nr.href, QK.chances(nr.field.slice(0, 8).map(function (d) { return { label: d.code || d.name, p: d.p || 0, href: d.href }; }), { key: false })));
  }
  var mv = C.nfl_movers;
  if (mv && mv.series && mv.series.length) {
    out.push(card('qk-span-6', 'NFL: who has moved', 'Net rating by week, the six biggest changes since week 1 (points v an average team)', 'nfl', mv.href, '<div id="c-nfl" style="--h:320px"></div>'));
    jobs.push(function () { QKC.line('#c-nfl', { x: mv.series[0].weeks.map(function (w) { return 'W' + w; }), xName: 'Week', yName: 'Rating (pts v average)', ref: { y: 0, label: 'average team' }, yFmt: function (v) { return fmt.signed(v, 1); }, label: 'NFL net rating movers', series: mv.series.map(function (s) { return { name: s.abbr, label: s.abbr + ' ' + fmt.signed(s.delta, 1), data: s.net }; }) }); });
  }
  var fav = C.football_favourites;
  if (fav && fav.length) {
    out.push(card('qk-span-6', 'Football: title favourites', 'Each league’s favourite and our title chance from the season simulation', 'football', QK.sportUrl('football'), QK.chances(fav.slice(0, 10).map(function (f) { return { label: f.team, sub: f.league, p: f.p, href: f.href }; }), { max: 1, sort: false, key: false })));
  }
  var ms = C.mlb_series;
  if (ms && ms.length) {
    out.push(card('qk-span-6', 'MLB postseason', 'Series in play: wins so far and our chance to advance', 'baseball', QK.sportUrl('baseball') + '#/postseason', '<div class="hm-series">' + ms.map(function (s) {
      var pa = s.p && isNum(s.p[0]) ? s.p[0] : null;
      return '<div class="hm-series-row"><div class="qk-kicker">' + esc(s.round) + ' · best of ' + esc(s.best_of) + '</div>' +
        '<div class="hm-series-teams"><span class="qk-row">' + QK.teamMark(s.a) + esc(s.a.name) + '</span><span class="w">' + esc(s.wins[0]) + '–' + esc(s.wins[1]) + '</span><span class="qk-row">' + esc(s.b.name) + QK.teamMark(s.b) + '</span></div>' +
        (isNum(pa) ? QK.wpBar(pa, null, 1 - pa, s.a, s.b, { label: 'Our chance to advance' }) : '') + '</div>';
    }).join('') + '</div>'));
  }
  var np = C.nba_power;
  if (np && np.rows && np.rows.length) {
    var r = np.rows.slice(0, 8).concat(np.rows.slice(-4));
    out.push(card('qk-span-12', 'NBA: power ratings', 'Net rating (points per 100 possessions v average): the top eight and the bottom four', 'basketball', QK.sportUrl('basketball'), '<div id="c-nba" style="--h:280px"></div>'));
    jobs.push(function () { QKC.bar('#c-nba', { cats: r.map(function (x) { return x.abbr; }), series: [{ name: 'Net rating', data: r.map(function (x) { return x.value; }) }], diverging: true, hrefs: r.map(function (x) { return x.href; }), labels: true, catName: 'Team', valName: 'Net rating (pts per 100 poss.)', fmt: function (v) { return fmt.signed(v, 1); } }); });
  }
  $('#chart-grid').innerHTML = pack(out).join('');
  jobs.forEach(function (f) { try { f(); } catch (e) { if (window.console) console.error(e); } });
}

/* The charts grid in rows of 12 columns: a card that would leave its row part empty (the next one does not fit beside
   it, or it is the last) widens to fill the row, so no grid cell stays blank. */
function pack(cards) {
  var spanOf = function (h) { var m = /qk-span-(\d+)/.exec(h); return m ? +m[1] : 12; };
  var out = [], used = 0;
  var widen = function () { if (used > 0 && used < 12 && out.length) { var i = out.length - 1, s = spanOf(out[i]); out[i] = out[i].replace('qk-span-' + s, 'qk-span-' + (s + 12 - used)); } };
  cards.forEach(function (h) {
    var s = spanOf(h);
    if (used + s > 12) { widen(); used = 0; }
    out.push(h); used += s;
    if (used === 12) used = 0;
  });
  widen();
  return out;
}

/* ───────────────────────────── how it works */
var METHOD = { football: '#/model/methodology', college: '#/model' };
/* each site's "How we're doing" (the Model page tab with our record and calibration, round 6) */
var DOING = { football: '#/model/calibration', f1: '#/model', basketball: '#/nba/model?tab=calibration', tennis: '#/atp/calibration', baseball: '#/calibration', nfl: '#/calibration', hockey: '#/model?tab=calibration', college: '#/cfb/model?tab=calibration' };
function renderHow() {
  $('#how').innerHTML = QK.sectionHead({ kicker: 'How it works', title: 'Where the numbers come from', sub: 'Each sport has its own models, built from public data and checked on seasons they never saw.' }) +
    QK.newHere({ items: [QK.NEW_HERE[0], QK.NEW_HERE[1], 'A <b>season simulation</b> plays out the rest of the schedule thousands of times with our game forecasts, so every team gets a chance of the title and the playoffs.'] }) +
    '<div class="hm-method">' + QK.SPORTS.map(function (q) { return '<a href="' + esc(QK.sportUrl(q.key) + (METHOD[q.key] || '#/methodology')) + '" style="--sa:' + q.accent + '"><span aria-hidden="true">' + QK.ICON[q.key] + '</span>' + esc(q.label) + ': how the model works</a>'; }).join('') + '</div>' +
    '<p class="hm-doing"><b>How we’re doing:</b> ' + QK.SPORTS.map(function (q) { return '<a class="qk-link" href="' + esc(QK.sportUrl(q.key) + (DOING[q.key] || '#/model')) + '">' + esc(q.label) + '</a>'; }).join(' · ') + '. Our record and calibration, on each site’s Model page.</p>';
}

/* ───────────────────────────── live scores (browser-side, cross-origin) */
function norm(s) {
  s = String(s || '').toLowerCase();
  if (/^(finished|final|post|done|closed|ft|complete|completed)$/.test(s)) return 'final';
  if (/^(live|in|inprogress|in_progress|running)$/.test(s)) return 'live';
  return 'pre';
}
var ADAPT = {
  football: ['hub.json', function (j) { var out = []; Object.keys(j.days || {}).forEach(function (d) { (j.days[d] || []).forEach(function (m) { out.push({ id: m.id, status: m.status, hs: m.hs, as: m.as }); }); }); return out; }],
  basketball: ['index.json', function (j) { var out = []; Object.keys(j.leagues || {}).forEach(function (L) { var l = j.leagues[L]; ['today', 'next_games', 'last_games'].forEach(function (k) { (l[k] || []).forEach(function (g) { out.push({ id: g.id, status: g.status, hs: g.hs, as: g.as, period: g.period, clock: g.clock, wp_home: g.wp_home }); }); }); }); return out; }],
  baseball: ['index.json', function (j) { return [].concat(j.today || [], j.recent || [], j.upcoming || []).map(function (g) { return { id: g.gpk, status: g.status, hs: g.hs, as: g.as, period: g.inning, wp_home: g.wp_home }; }); }],
  nfl: ['index.json', function (j) { return [].concat(j.live || [], j.games || [], j.recent || []).map(function (g) { return { id: g.game_id, status: g.status, hs: g.hs, as: g.as, period: g.qtr, clock: g.clock, wp_home: g.wp_home }; }); }],
  hockey: ['index.json', function (j) { return [].concat(j.live || [], j.today || [], j.recent || [], j.upcoming || []).map(function (g) { return { id: g.game_id, status: g.status, hs: g.hs, as: g.as, period: g.period, clock: g.clock, wp_home: g.wp_home }; }); }],
  college: ['index.json', function (j) { var out = []; Object.keys(j.levels || {}).forEach(function (L) { var l = j.levels[L] || {}; ['today', 'next_games', 'last_games'].forEach(function (k) { (l[k] || []).forEach(function (g) { out.push({ id: g.id, status: g.status, hs: g.hs, as: g.as, period: g.period, clock: g.clock }); }); }); }); return out; }],
  tennis: ['index.json', function (j) { var out = []; Object.keys(j.tours || {}).forEach(function (T) { var t = j.tours[T]; [].concat(t.live || [], t.today || [], t.recent || []).forEach(function (m) { var s = m.sets || [], a = 0, b = 0; s.forEach(function (x) { if (isNum(x[0]) && isNum(x[1])) { if (x[0] > x[1]) a++; else if (x[1] > x[0]) b++; } }); out.push({ id: m.id, status: m.status, hs: s.length ? a : null, as: s.length ? b : null }); }); }); return out; }]
};
function needsLive(sport) {
  return D.games.some(function (g) {
    if (g.sport !== sport) return false;
    if (g.status === 'live') return true;
    var h = (QK.now() - new Date(g.start)) / 36e5;
    return g.status === 'pre' && h > -0.25 && h < 5;
  });
}
function refreshLive() {
  if (document.hidden || QK.asof() !== null) return;
  Object.keys(ADAPT).forEach(function (sport) {
    if (!needsLive(sport)) return;
    var s = QK.sport(sport), a = ADAPT[sport];
    QK.fetchJSON(s.data + a[0], { cache: 'no-cache' }).then(function (j) {
      var map = {}; a[1](j).forEach(function (x) { map[String(x.id)] = x; });
      var changed = false;
      D.games.forEach(function (g) {
        var x = g.sport === sport ? map[g.id] : null;
        if (!x) return;
        var st = norm(x.status);
        if (st !== g.status || x.hs !== g.hs || x.as !== g.as || x.period !== g.period || x.wp_home !== g.wp_home) {
          g.status = st; if (x.hs !== null && x.hs !== undefined) g.hs = x.hs; if (x.as !== null && x.as !== undefined) g.as = x.as;
          g.period = x.period; g.clock = x.clock; if (isNum(x.wp_home)) g.wp_home = x.wp_home;
          prep(g); changed = true;
        }
      });
      if (changed) { renderTicker(); renderSportNav(); renderFeature(); renderWatch(); renderGames(); }
    }, function () { /* offline or blocked: keep the built snapshot */ });
  });
}
function startLive() { refreshLive(); setInterval(refreshLive, 60000); document.addEventListener('visibilitychange', refreshLive); }
})();
