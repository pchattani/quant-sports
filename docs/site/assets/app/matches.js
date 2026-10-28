/* The Quant Footballer — Matches (#/matches) and the match centre (#/match/<slug>/<id>).
 *
 * #/matches[?d=YYYY-MM-DD|recent|upcoming&f=<family>&c=<slug>&v=next|recent|all]
 *   Every competition's matches by day from hub.json (a day strip around today plus the "Latest results" and
 *   "Next up" buckets), filtered by family and competition, grouped by competition, live first. With ?c=<slug>
 *   the competition's own fixtures.json is used instead (coming, recent or the whole season, by date).
 *   hub.json is re-read every minute while anything is in play.
 *
 * #/match/<slug>/<id>
 *   the kit v4 diagonal split hero (QK.previewCard: home first, club colours when clubs_index.json has them, the
 *   score once it starts, our chance for the favourite, the home / draw / away bar, the market as a quiet line before
 *   kick-off: the only place it appears besides the Model page), stat tiles, our forecast before kick-off (win, draw, expected goals, most likely score, 3 or more goals, both score)
 *   with the prediction market only as a quiet reference column named by its source, the tale of the tape (our
 *   rating, Elo, xG for and against, from the competition's strength.json and team_stats.json), the confirmed XIs
 *   once posted (fixtures[].xi, about an hour before kick-off) with our forecast before and after the line-up term
 *   (model_pre, model), and,
 *   when the match has a page (fixtures[].detail): summary tiles, the expected result (every shot replayed at its
 *   xG), the xG race, the shot map (team / situation / result filters), where the shots went (goal mouth), the
 *   timeline and momentum, who made the chances, the team statistics, the line-ups on the pitch with benches and
 *   absentees, and every player's line. A match without a page gets a preview: both clubs' recent results across
 *   all competitions and their head-to-head (clubs/<tid>.json).
 *
 * The match is looked up in the competition's fixtures.json first, then in its past seasons (s/<sid>/season.json);
 * matches/<id>.json is requested only when the fixture says it exists, so nothing 404s. */
(function (FB) {
'use strict';

var QK = window.QK, QKC = window.QKC;
var esc = FB.esc, isNum = FB.isNum, num = FB.num, pct = FB.pct;

var FAMS = [['all', 'All']].concat(FB.FAMILIES.map(function (f) { return [f.key, f.key === 'cup' ? 'Continental' : f.label]; }));
var STATUS_ORDER = { live: 0, scheduled: 1, finished: 2, postponed: 3, cancelled: 4 };

function cHex(n) { return QK.cssVar('--c-' + n); }
/* Team colours on the match page: football payloads carry no kit colours, so home takes the kit's right-hand
   win-probability colour and away the left-hand one, as on the game cards' bars. */
function sideHex(side) { return QK.cssVar(side === 'home' ? '--wp-b' : '--wp-a'); }
function sideVar(side) { return side === 'home' ? 'var(--wp-b)' : 'var(--wp-a)'; }
function shiftDay(k, n) { var d = FB.parseDate(k + 'T12:00:00'); d.setDate(d.getDate() + n); return FB.localDay(d); }
function dayLabel(k) {
  if (k === 'recent') return 'Latest results';
  if (k === 'upcoming') return 'Next up';
  var r = FB.relDay(k + 'T12:00:00');
  return r === 'Today' || r === 'Tomorrow' || r === 'Yesterday' ? r : FB.fmtDate(k + 'T12:00:00');
}
function compRank() { var r = {}; FB.comps().forEach(function (c, i) { r[c.slug] = i; }); return r; }
function sortMatches(list) {
  return list.sort(function (a, b) { return (STATUS_ORDER[a.status] - STATUS_ORDER[b.status]) || String(a.date).localeCompare(String(b.date)); });
}

// ── #/matches ─────────────────────────────────────────────────────────────

FB.route('matches', function (el, p) {
  var q = p.query || {};
  if (q.c && FB.comp(q.c) && FB.comp(q.c).ok) return compMatches(el, q);
  el.innerHTML = FB.pageHead('Matches', 'Every match, every competition',
    'Results and fixtures across all ' + FB.comps().filter(function (c) { return c.ok; }).length + ' competitions, with our home / draw / away chance before kick-off and expected goals after it. Kick-off times in your time zone.', '<a class="qk-btn" href="#/">Overview</a><a class="qk-btn" href="#/competitions">Competitions</a>') +
    '<div id="mx-days" class="fb-mx-days"></div><div id="mx-filters" class="fb-mx-filters"></div><div id="mx-body">' + FB.loading('lines', 8) + '</div>';
  var HUB = null;
  function draw() { if (FB.alive(el)) drawHub(el, HUB, FB.state.params.query || {}); }
  FB.interval(function () {
    var soon = hubAll(HUB).some(function (m) { var t = FB.parseDate(m.date); return m.status === 'live' || (m.status === 'scheduled' && t && Math.abs(t - Date.now()) < 15 * 60000); });
    if (!soon) return;
    FB.reload('hub.json').then(function (h) { if (!h || !FB.alive(el)) return; HUB = h; FB.hubLive(h); draw(); });
  }, 60000);
  return FB.load('hub.json').then(function (h) { HUB = h || { days: {} }; draw(); });
});

function hubAll(h) {
  var out = [];
  var days = (h || {}).days || {};
  Object.keys(days).forEach(function (k) { (days[k] || []).forEach(function (m) { out.push(m); }); });
  return out;
}

function drawHub(el, h, q) {
  var buckets = {};
  hubAll(h).forEach(function (m) { var k = FB.localDay(m.date); if (k) (buckets[k] = buckets[k] || []).push(m); });
  var keys = Object.keys(buckets).sort();
  var order = keys.slice();
  if ((h.recent || []).length) { buckets.recent = h.recent; order.unshift('recent'); }
  if ((h.upcoming || []).length) { buckets.upcoming = h.upcoming; order.push('upcoming'); }
  var t = FB.today();
  var day = q.d && buckets[q.d] ? q.d : (buckets[t] ? t : (keys.filter(function (k) { return k > t; })[0] || keys[keys.length - 1] || order[0]));
  var fam = q.f || 'all';
  var all = (buckets[day] || []).slice();

  var strip = el.querySelector('#mx-days');
  strip.innerHTML = '<div class="qk-chips scroll fb-mx-strip" role="group" aria-label="Day">' + order.map(function (k) {
    var n = buckets[k].length, live = buckets[k].filter(function (m) { return m.status === 'live'; }).length;
    return '<button class="qk-chip fb-mx-day' + (k === t ? ' is-today' : '') + '" type="button" data-value="' + esc(k) + '" aria-pressed="' + (k === day) + '">' +
      esc(dayLabel(k)) + ' <span class="n">' + n + '</span>' + (live ? '<i class="fb-mx-livedot" aria-label="live"></i>' : '') + '</button>';
  }).join('') + '</div>';
  QK.chips(strip.querySelector('.qk-chips'), function (v) { FB.setQuery({ d: v[0], c: null }, true); });
  var cur = strip.querySelector('[aria-pressed="true"]');
  if (cur && cur.scrollIntoView && cur.parentNode.scrollWidth > cur.parentNode.clientWidth) { try { cur.parentNode.scrollLeft = cur.offsetLeft - 60; } catch (e) { /* old browsers */ } }

  var counts = { all: all.length };
  all.forEach(function (m) { var f = FB.familyOf(FB.comp(m.comp)); counts[f] = (counts[f] || 0) + 1; });
  var inDay = {};
  all.forEach(function (m) { inDay[m.comp] = (inDay[m.comp] || 0) + 1; });
  var compOpts = [['', 'All competitions']].concat(FB.comps().filter(function (c) { return c.ok; }).map(function (c) { return [c.slug, c.name + (inDay[c.slug] ? ' (' + inDay[c.slug] + ')' : '')]; }));
  var filters = el.querySelector('#mx-filters');
  filters.innerHTML = '<div class="qk-chips scroll" id="mx-fam" role="group" aria-label="Competition family">' + FAMS.map(function (f) {
    return '<button class="qk-chip" type="button" data-value="' + f[0] + '" aria-pressed="' + (f[0] === fam) + '">' + esc(f[1]) + ' <span class="n">' + (counts[f[0]] || 0) + '</span></button>';
  }).join('') + '</div>' + FB.select('mx-comp', compOpts, '', 'Open one competition\'s fixtures', 'fb-mx-compsel');
  QK.chips(filters.querySelector('#mx-fam'), function (v) { FB.setQuery({ f: v[0] === 'all' ? null : v[0] }, true); });
  filters.querySelector('#mx-comp').addEventListener('change', function (e) { if (e.target.value) FB.go(FB.href.matches({ c: e.target.value })); });

  var list = fam === 'all' ? all : all.filter(function (m) { return FB.familyOf(FB.comp(m.comp)) === fam; });
  var body = el.querySelector('#mx-body');
  if (!list.length) { body.innerHTML = FB.empty('No matches', fam === 'all' ? 'Nothing across the competitions followed for this day.' : 'Nothing from this family for this day. Try All.'); return; }
  var showDate = day === 'recent' || day === 'upcoming';
  var by = {};
  list.forEach(function (m) { (by[m.comp] = by[m.comp] || []).push(m); });
  var rank = compRank();
  var slugs = Object.keys(by).sort(function (a, b) {
    var la = by[a].some(function (m) { return m.status === 'live'; }) ? 0 : 1, lb = by[b].some(function (m) { return m.status === 'live'; }) ? 0 : 1;
    return la - lb || (rank[a] === undefined ? 999 : rank[a]) - (rank[b] === undefined ? 999 : rank[b]);
  });
  var live = list.filter(function (m) { return m.status === 'live' && !FB.staleLive(m); }).length;
  body.innerHTML = '<p class="fb-cap fb-mx-sum">' + list.length + ' matches in ' + slugs.length + ' competition' + (slugs.length === 1 ? '' : 's') +
    (live ? ' · <b class="fb-mx-live">' + live + ' live</b>' : '') + ' · the bar is our home / draw / away chance; xG after the whistle.</p>' +
    '<div class="fb-mx-groups">' + slugs.map(function (s) { return groupCard(s, sortMatches(by[s]), showDate); }).join('') + '</div>';
}

function groupCard(slug, list, showDate) {
  var c = FB.comp(slug) || {};
  var head = '<div class="fb-mx-ghead">' + FB.compLink(slug) + '<span class="qk-muted">' + esc(c.country || (FB.KIND_LABEL[FB.kindOf(slug)] || '')) + '</span>' +
    '<a class="fb-mx-more" href="' + esc(FB.href.matches({ c: slug })) + '">All fixtures →</a></div>';
  return '<section class="qk-card fb-mx-group">' + head + '<div class="fb-fxlist">' + list.map(function (m) { return FB.fixtureRow(m, { slug: slug, date: showDate, round: true }); }).join('') + '</div></section>';
}

/* One competition's fixtures (?c=<slug>): coming, recent or the whole season, grouped by day. */
function compMatches(el, q) {
  var c = FB.comp(q.c);
  el.innerHTML = FB.pageHead('<a href="#/matches">Matches</a> · ' + esc(FB.KIND_LABEL[FB.kindOf(c.slug)] || ''), c.name,
    esc(FB.currentSeason(c).season) + ' · our home / draw / away chance before kick-off; kick-off times in your time zone. <a href="' + esc(FB.href.comp(c.slug)) + '">Table, chances and players →</a>',
    '<a class="qk-btn" href="#/matches">All competitions</a>') + '<div id="mx-cview"></div><div id="mx-body">' + FB.loading('lines', 8) + '</div>';
  return FB.compFiles(c.slug, ['fixtures', 'teams']).then(function (d) {
    if (!FB.alive(el)) return;
    var all = ((d.fixtures || {}).matches || []).slice().sort(function (a, b) { return String(a.date).localeCompare(String(b.date)); });
    var ids = teamIds(d.teams);
    all.forEach(function (m) { if (!m.home_id) m.home_id = ids[m.home]; if (!m.away_id) m.away_id = ids[m.away]; });
    var coming = all.filter(function (m) { return m.status !== 'finished' && m.status !== 'cancelled'; });
    var done = all.filter(function (m) { return m.status === 'finished'; });
    var v = q.v || (coming.length ? 'next' : 'recent');
    el.querySelector('#mx-cview').innerHTML = FB.seg('mx-v', [['next', 'Coming (' + coming.length + ')'], ['recent', 'Results (' + done.length + ')'], ['all', 'Whole season (' + all.length + ')']], v, 'Which matches');
    FB.wireSeg(el, 'mx-v', function (x) { FB.setQuery({ v: x }, true); });
    var list = v === 'next' ? coming.slice(0, 60) : v === 'recent' ? done.slice(-60).reverse() : all;
    var body = el.querySelector('#mx-body');
    if (!list.length) { body.innerHTML = FB.empty('No matches', v === 'next' ? 'Nothing left to play in this edition.' : 'No result yet.'); return; }
    var by = {}, keys = [];
    list.forEach(function (m) { var k = FB.localDay(m.date) || 'TBD'; if (!by[k]) { by[k] = []; keys.push(k); } by[k].push(m); });
    body.innerHTML = '<div class="fb-mx-days-list">' + keys.map(function (k) {
      return '<section class="qk-card fb-mx-group"><div class="fb-mx-ghead"><b>' + esc(k === 'TBD' ? 'Date to be confirmed' : longDay(k)) + '</b><span class="qk-muted">' + by[k].length + ' match' + (by[k].length === 1 ? '' : 'es') + '</span></div>' +
        '<div class="fb-fxlist">' + by[k].map(function (m) { return FB.fixtureRow(m, { slug: c.slug, round: true }); }).join('') + '</div></section>';
    }).join('') + '</div>' + (v !== 'all' && (v === 'next' ? coming : done).length > 60 ? '<p class="fb-cap">Showing 60. <a href="' + esc(FB.href.matches({ c: c.slug, v: 'all' })) + '">The whole season →</a></p>' : '');
  });
}

function longDay(k) {
  var r = FB.relDay(k + 'T12:00:00'), d = FB.fmtDate(k + 'T12:00:00', { year: true });
  return r === 'Today' || r === 'Tomorrow' || r === 'Yesterday' ? r + ' · ' + d : d;
}
function teamIds(teamsDoc) {
  var t = (teamsDoc || {}).teams || {}, out = {};
  Object.keys(t).forEach(function (n) { if (t[n] && t[n].team_id) out[n] = t[n].team_id; });
  return out;
}

// ── #/match/<slug>/<id> ───────────────────────────────────────────────────

/* Find the fixture: current fixtures.json, then the past seasons with a season file, then hub.json. */
function findFixture(c, id) {
  return FB.compFiles(c.slug, ['fixtures', 'teams']).then(function (d) {
    var ids = teamIds(d.teams);
    var f = (((d.fixtures || {}).matches) || []).filter(function (m) { return String(m.id) === String(id); })[0];
    if (f) return { f: f, ids: ids, season: FB.currentSeason(c).season, past: false };
    return FB.seasonsOf(c).then(function (list) {
      var past = list.filter(function (s) { return s.source !== 'live' && (s.source === 'store' || s.path) && (s.matches || s.finished || s.detail); });
      function next(i) {
        if (i >= past.length || i >= 6) return FB.load('hub.json').then(function (h) {
          var all = hubAll(h).concat((h || {}).recent || [], (h || {}).upcoming || []);
          var x = all.filter(function (m) { return String(m.id) === String(id) && m.comp === c.slug; })[0];
          return x ? { f: x, ids: ids, season: FB.currentSeason(c).season, past: false } : null;
        });
        return FB.loadPastSeason(c, past[i].sid).then(function (doc) {
          var x = ((doc || {}).fixtures || []).filter(function (m) { return String(m.id) === String(id); })[0];
          return x ? { f: x, ids: ids, season: doc.season || past[i].season, past: true, sid: past[i].sid } : next(i + 1);
        });
      }
      return next(0);
    });
  });
}

FB.route('match', function (el, p) {
  var c = FB.comp(p.slug);
  if (!c) { el.innerHTML = FB.pageHead('Match', 'Unknown competition', 'There is no competition called “' + esc(p.slug) + '”.') + '<p><a class="qk-btn" href="#/matches">Every match →</a></p>'; return; }
  FB.setCompPicker(c.slug);
  el.innerHTML = FB.loading('card', 1) + FB.loading('lines', 6);
  return findFixture(c, p.id).then(function (hit) {
    if (!FB.alive(el)) return;
    if (!hit) {
      el.innerHTML = FB.pageHead(FB.compLink(c.slug), 'Match not found', 'No match ' + esc(p.id) + ' in ' + esc(c.name) + '\'s fixtures or past seasons.') +
        '<p><a class="qk-btn" href="' + esc(FB.href.matches({ c: c.slug })) + '">' + esc(c.name) + ' fixtures →</a></p>';
      return;
    }
    var f = hit.f;
    f.home_id = f.home_id || hit.ids[f.home] || FB.tidFromCrest(f.crests && f.crests[0]);
    f.away_id = f.away_id || hit.ids[f.away] || FB.tidFromCrest(f.crests && f.crests[1]);
    document.title = f.home + ' v ' + f.away + ' · The Quant Footballer';
    var jobs = [f.detail ? FB.load(c.slug + '/matches/' + f.id + '.json') : Promise.resolve(null)];
    jobs.push(f.status !== 'finished' && FB.hasFile(c.slug, 'market_odds') ? FB.compFile(c.slug, 'market_odds') : Promise.resolve(null));
    jobs.push(!hit.past ? FB.compFiles(c.slug, ['strength', 'team_stats', 'table']) : Promise.resolve(null));
    /* a finished match whose fixture no longer carries our line: the chance frozen before kick-off (forecast_log.json,
       id -> [home, draw, away, kick-off, competition]), so the page keeps "Our pre-match call" */
    var needLog = f.status === 'finished' && !(f.model && isNum(f.model.h));
    jobs.push(needLog ? FB.load('forecast_log.json') : Promise.resolve(null));
    return Promise.all(jobs).then(function (r) {
      if (!FB.alive(el)) return;
      var m = r[0];
      var lg = needLog && r[3] ? r[3][String(f.id)] : null;
      if (lg && isNum(lg[0]) && isNum(lg[1]) && isNum(lg[2])) f = FB.merge(f, { model: { h: lg[0], d: lg[1], a: lg[2], logged: true } });
      var mk = null;
      (((r[1] || {}).matches || {}).fixtures || []).forEach(function (x) { if (String(x.match_id) === String(f.id) && x.market) mk = x; });
      if (mk) { mk._src = (r[1] || {}).sources || []; mk._at = (r[1] || {}).updated_at; }
      renderMatch(el, c, f, m, mk, hit, r[2]);
    });
  });
});

// Why a finished match has no detail: older than a year (season and player pages only), or a recent tie the
// detail fetch leaves out (qualifying and early cup rounds without a followed club, where Sofascore usually has no
// line-ups), or one Sofascore has not published detail for.
function noDetailReason(f) {
  var t = Date.parse(f.date || '');
  var old = isFinite(t) && Date.now() - t > 365 * 864e5;
  if (old) return 'the detailed data (line-ups, shots, statistics) is not in the store; matches older than a year feed the season and player pages only.';
  return 'there are no line-ups, shots or statistics for this tie: qualifying and early cup rounds without a followed club are tracked from the result only, and Sofascore publishes no detail for many of them.';
}

function renderMatch(el, c, f, m, mk, hit, side) {
  var pre = f.status !== 'finished' && f.status !== 'live';
  var back = '<div class="qk-kicker fb-mx-back"><a href="' + esc(FB.href.matches({ c: c.slug })) + '">← ' + esc(c.name) + ' fixtures</a></div>';
  var right = '';
  if (pre && f.model) right = kpiStrip(f) + forecastCard(f, mk);
  else if (f.model) right = forecastCard(f, null, true);
  var html = back + '<div class="fb-mx-top' + (right ? '' : ' solo') + '">' + hero(c, f, m, hit, mk, side) + (right ? '<div class="fb-mx-stack">' + right + '</div>' : '') + '</div>';
  var tape = pre ? tapeCard(c, f, side) : '';
  var hasDetail = !!(m && (m.shots || m.lineups || m.team_stats));
  if (tape && hasDetail) html += '<div class="fb-mt">' + FB.grid(tape) + '</div>';
  if (f.status !== 'finished' && f.xi) html += xiCard(f);
  if (m && (m.shots || m.lineups || m.team_stats)) {
    html += '<section class="qk-section">' + QK.sectionHead({ kicker: f.status === 'live' ? 'In play' : 'After the whistle', title: 'How the match was won', sub: 'What the chances were worth, where the shots came from, the line-ups and every player’s line.' }) + '<div id="mx-detail"></div></section>';
  } else {
    html += '<div class="fb-mt">' + FB.note(f.status === 'finished'
      ? 'No match page for this one: ' + (f.detail === false ? noDetailReason(f) : 'it is fetched a few hours after the final whistle.')
      : 'The match centre opens with line-ups, shots and statistics once the match has been played.') + '</div><div id="mx-preview"></div>';
  }
  el.innerHTML = html;
  if (m && (m.shots || m.lineups || m.team_stats)) detail(el, c, f, m);
  else preview(el, c, f, tape);
  absences(el, c, f, m);
}

/* Round 9, Phase 4: who is missing and what it costs. A match with line-ups lists each side's injured, suspended and
   doubtful players (the match file's `missing`); a match whose XIs are in also lists the usual starters left out
   (fixtures[].xi out, each with the value the line-up model gives them). Each player carries our projected value
   (GAR/90 from the club's value file: goals of expected goal difference a match above a replacement-level player);
   the regulars' sum is what the side is missing, about, if a replacement-level player stands in. */
function absences(el, c, f, m) {
  var miss = (m && m.missing) || {};
  var x = f.xi || {};
  var sides = ['home', 'away'].map(function (s) {
    var inSquad = {};
    (((m || {}).lineups || {})[s] || []).forEach(function (e) { if (e.id) inSquad[String(e.id)] = 1; });
    return { side: s, name: s === 'home' ? f.home : f.away, tid: s === 'home' ? f.home_id : f.away_id,
      list: (miss[s] || (x[s] || {}).missing || []).filter(function (p) { return !(p.id && inSquad[String(p.id)]); }), out: ((x[s] || {}).out || []) };
  });
  if (!sides.some(function (s) { return s.list.length || s.out.length; })) return;
  var host = document.createElement('section');
  host.className = 'qk-section';
  el.appendChild(host);
  Promise.all(sides.map(function (s) { return FB.absenceRows(s.tid, s.list); })).then(function (rows) {
    if (!FB.alive(el)) return;
    var col = function (s, rs) {
      var reg = rs.filter(function (r) { return r.regular && isNum(r.proj); });
      var cost = reg.reduce(function (a, r) { return a + r.proj; }, 0);
      var outV = s.out.filter(function (o) { return isNum(o.v); }).reduce(function (a, o) { return a + o.v; }, 0);
      var head = rs.length ? FB.kpi('Missing', String(rs.length), { sub: reg.length ? reg.length + ' regular' + (reg.length === 1 ? '' : 's') + ', worth about ' + FB.signed(cost, 2) + ' goals a match' : 'none of them a regular' }) : '';
      var headOut = s.out.length ? FB.kpi('Usual starters left out', String(s.out.length), { sub: 'worth ' + FB.signed(outV, 2) + ' goals a match to the usual XI' }) : '';
      var li = rs.map(function (r) {
        return '<li><span class="fb-mx-abn">' + (r.id ? FB.playerLink(r.id, r.name) : esc(r.name)) + (r.role ? ' <span class="qk-muted">' + esc(r.role) + '</span>' : '') + '</span>' +
          '<span class="fb-mx-abw ' + esc(r.why) + '">' + esc(r.why) + '</span><b class="fb-num">' + (isNum(r.proj) ? FB.signed(r.proj, 2) : '—') + '</b></li>';
      }).join('') + s.out.map(function (o) {
        return '<li><span class="fb-mx-abn">' + FB.playerLink(o.id, o.n || ('#' + o.id)) + '</span><span class="fb-mx-abw out">left out</span><b class="fb-num">' + (isNum(o.v) ? FB.signed(o.v, 2) : '—') + '</b></li>';
      }).join('');
      return FB.card(FB.clubLink(s.tid, s.name), (rs.length + s.out.length) + ' absent', FB.kpis([head, headOut].filter(Boolean)) + '<ul class="fb-mx-ab">' + li + '</ul>', { span: 6 });
    };
    host.innerHTML = QK.sectionHead({ kicker: 'Absences', title: 'Who’s missing, and what it costs', sub: 'Injured, suspended and doubtful players' + (sides.some(function (s) { return s.out.length; }) ? ', and the usual starters left out of the XI' : '') + '. The number is our projected value: goals of expected goal difference a match above a replacement-level player.' }) +
      FB.grid(col(sides[0], rows[0]) + col(sides[1], rows[1])) +
      QK.explain('A regular worth <b>+0.20</b> is about one goal of difference every five matches over the player a club could sign cheaply. Values come from the player value model; a player outside a followed league has none (—).', { title: 'What’s that number?' });
  });
}

/* The hero (kit v4 QK.previewCard, the diagonal split as on the Rink game page): football's home-first order ("Home v
   Away"), the clubs' raw kit and alternate colours (FB.toGame, from clubs_index.json; QK.color.blockPair makes the blocks
   and resolves a clash; cobalt v slate by our favourite until the colours land), short codes (FB.heroGame), the record and
   league form, the score once it starts (the score bug while live), our chance for the favourite as a big blue number
   with a sentence, the home / draw / away bar, a plain-English "how sure" note and how the sides match up so far.
   Football has no live model: during a match the card keeps the pre-match chance and says so. The market sits here
   only as a quiet labelled reference line before kick-off. */
function hero(c, f, m, hit, mk, side) {
  var stale = FB.staleLive(f);
  var live = f.status === 'live' && !stale;
  var hs = m && isNum(m.hs) ? m.hs : f.hs, as = m && isNum(m.as) ? m.as : f.as;
  var g = FB.heroGame(FB.toGame(FB.merge(f, { hs: hs, as: as }), c.slug));
  g.href = null;
  var rows = {};
  var tbl = side && side.table && Array.isArray(side.table.standings) ? side.table.standings : [];
  tbl.forEach(function (r) { rows[r.team] = r; });
  var st = {};
  (((side && side.strength) || {}).rows || []).forEach(function (r) { st[r.team] = r; });
  var rec = function (n) { var r = rows[n]; return r && isNum(r.w) ? r.w + '–' + r.d + '–' + r.l + (isNum(r.pts) ? ' · ' + r.pts + ' pts' : '') : ''; };
  var form = function (n) { var r = st[n]; return r && (r.form_results || []).length ? r.form_results.slice(-5).join('') : null; };
  g.home.record = rec(f.home); g.away.record = rec(f.away);
  if (f.status !== 'finished') { g.home.form = form(f.home); g.away.form = form(f.away); }
  var md = f.model || {};
  var extra = [];
  if (!live && f.status !== 'finished' && isNum(md.lh) && isNum(md.la)) extra.push('We expect about ' + num(md.lh + md.la, 1) + ' goals in all' + (md.score ? ', and ' + esc(md.score) + ' is the likeliest score' + (isNum(md.p_score) ? ' (' + pct(md.p_score) + ')' : '') : ''));
  if (md.lineups && f.status !== 'finished') extra.push('the forecast includes the confirmed line-ups');
  var note;
  if (live) note = '<b>Our pre-match chance.</b> We have no live model for football, so this is the call from before kick-off; the score has not moved it yet.';
  var ts = (((side && side.team_stats) || {}).teams) || {};
  var th = (ts[f.home] || {}).season || {}, ta = (ts[f.away] || {}).season || {};
  var h = st[f.home] || {}, a = st[f.away] || {};
  var fx = [];
  var add = function (label, av, bv, fm, low) { if (isNum(av) && isNum(bv)) fx.push({ label: label, a: fm(av), b: fm(bv), better: Math.abs(av - bv) < 1e-9 ? null : ((av > bv) !== !!low ? 'a' : 'b') }); };
  /* before kick-off the tale of the tape below carries these: the hero keeps them only after it */
  if (f.status !== 'finished' && !live) add = function () {};
  add('Our rating (points a game)', a.strength_ppg, h.strength_ppg, function (v) { return num(v, 2); });
  add('Points a game', a.ppg, h.ppg, function (v) { return num(v, 2); });
  add('xG for a match', isNum(ta.xg) ? ta.xg : null, isNum(th.xg) ? th.xg : null, function (v) { return num(v, 2); });
  add('xG against a match', isNum(ta.xga) ? ta.xga : null, isNum(th.xga) ? th.xga : null, function (v) { return num(v, 2); }, true);
  add('Elo', a.elo, h.elo, function (v) { return num(v, 0); });
  /* round 6: the market's home / draw / away chance in one small grey line under the hero (kit market: 'quiet'), the
     source on hover; before kick-off only, and only from a snapshot under three days old at the page clock */
  var mkAt = mk ? FB.parseDate(mk._at) : null, mkFresh = !!mkAt && QK.now() - mkAt.getTime() <= 3 * 864e5;
  if (f.status !== 'finished' && !live && mkFresh && mk.market && isNum(mk.market.home) && isNum(mk.market.away)) {
    g.market_home = mk.market.home; g.market_draw = mk.market.draw; g.market_away = mk.market.away; g.market_src = mk._src || [];
  }
  var mref = isNum(g.market_home) ? 'quiet' : null;
  var rnd = FB.roundText(f, c.slug);
  var void_ = /postponed|cancelled|not reported/.exec(String(g.note || ''));
  var kick = c.name + (rnd ? ' · ' + rnd : '') + (void_ ? ' · ' + void_[0] : '') + (f.group || (m && m.group) ? ' · Group ' + (f.group || m.group) : '') + (m && m.venue ? ' · ' + m.venue : '');
  var o = { kicker: kick, nick: function (t) { return t.name; }, factors: fx, factorsTitle: 'How they match up this season', noteExtra: extra.length ? extra.join(', and ') + '.' : '', market: mref,
    homeFirst: true, vs: 'v', noun: 'match' };
  if (note) o.note = note;
  var meta = [esc(FB.fmtDate(f.date, { year: true, time: true })), hit.season ? esc(c.name + ' ' + hit.season) : ''];
  var xg = m && m.xg ? m.xg : f.xg;
  if (xg && isNum(xg[0]) && f.status !== 'scheduled') meta.push('xG ' + FB.esc(f.home) + ' ' + num(xg[0], 2) + ' – ' + num(xg[1], 2) + ' ' + FB.esc(f.away));
  var links = '<div class="fb-mx-hmeta">' + meta.filter(Boolean).map(function (x) { return '<span>' + x + '</span>'; }).join('') +
    (f.home_id ? '<a href="' + esc(FB.href.club(f.home_id, { c: c.slug })) + '">' + esc(f.home) + ' →</a>' : '') + (f.away_id ? '<a href="' + esc(FB.href.club(f.away_id, { c: c.slug })) + '">' + esc(f.away) + ' →</a>' : '') + '</div>';
  return '<div class="fb-mx-hero">' + QK.previewCard(g, o) + links + '</div>';
}

/* Stat tiles before kick-off: ours first. */
function kpiStrip(f) {
  var md = f.model || {};
  var out = [];
  /* the home / draw / away chance is the hero's: it is not repeated here */
  if (isNum(md.lh)) out.push(FB.kpi('Expected goals', num(md.lh, 2) + '–' + num(md.la, 2), { sub: esc(f.home) + ' – ' + esc(f.away), tip: 'The goals our model expects each side to score' }));
  if (md.score) out.push(FB.kpi('Most likely score', esc(md.score), { sub: isNum(md.p_score) ? pct(md.p_score) + ' chance, home first' : 'home first' }));
  if (isNum(md.o25)) out.push(FB.kpi('3 or more goals', pct(md.o25), { sub: '2 or fewer: ' + pct(1 - md.o25) }));
  if (isNum(md.btts)) out.push(FB.kpi('Both score', pct(md.btts), { sub: 'one goal each at least', tip: 'Our chance that both sides score at least once' }));
  return FB.kpis(out.slice(0, 4), 'fb-mx-ktiles');
}

/* Our forecast, with the market as a quiet reference column named by its source (never a gap or a headline). */
function forecastCard(f, mk, done) {
  var md = f.model;
  if (!done) mk = null;
  var src = mk ? (mk._src || []).map(function (k) { return k === 'kalshi' ? 'Kalshi' : k === 'polymarket' ? 'Polymarket' : k; }) : [];
  var mlab = 'Market' + (src.length ? ' (' + src.join(' / ') + ')' : '');
  var mv = function (k) { return mk && mk.market && isNum(mk.market[k]) ? pct(mk.market[k], 0) : ''; };
  /* before kick-off the hero carries the home / draw / away chance (and the market's, quietly): the table keeps the
     other questions; after the whistle it is the record of our call */
  var rows = done ? [
    [esc(f.home) + ' win', pct(md.h, 0), mv('home')],
    ['Draw', pct(md.d, 0), mv('draw')],
    [esc(f.away) + ' win', pct(md.a, 0), mv('away')]
  ] : [];
  if (isNum(md.lh)) rows.push(['Expected goals', esc(f.home) + ' ' + num(md.lh, 2) + ' – ' + num(md.la, 2) + ' ' + esc(f.away), '']);
  if (md.score) rows.push(['Most likely score', esc(md.score) + (isNum(md.p_score) ? ' (' + pct(md.p_score) + ')' : ''), '']);
  if (isNum(md.o25)) rows.push(['3 or more goals', pct(md.o25), '']);
  if (isNum(md.btts)) rows.push(['Both sides score', pct(md.btts), '']);
  if (done && isNum(f.hs) && isNum(f.as) && f.status === 'finished') {
    var res = f.hs > f.as ? 'h' : f.hs < f.as ? 'a' : 'd';
    var said = [['h', md.h], ['d', md.d], ['a', md.a]].sort(function (x, y) { return y[1] - x[1]; })[0][0];
    rows.push(['What happened', esc(res === 'd' ? 'A draw, ' + f.hs + '–' + f.as : (res === 'h' ? f.home : f.away) + ' won ' + Math.max(f.hs, f.as) + '–' + Math.min(f.hs, f.as)) +
      ' · we gave that ' + pct(md[res], 0) + (said === res ? ' (our likeliest result)' : ''), '']);
  }
  var table = '<div class="qk-table-wrap"><table class="qk-table dense fb-mx-fc"><thead><tr><th scope="col">Question</th><th scope="col">Our forecast' + (md.lineups ? ' (with the XIs)' : '') + '</th>' +
    (mk ? '<th scope="col" class="mk"><span data-tip="The prediction markets’ probability with the margin removed, shown as a reference next to ours">' + esc(mlab) + '</span></th>' : '') + '</tr></thead><tbody>' +
    rows.map(function (r) { return '<tr><td>' + r[0] + '</td><td class="ours">' + r[1] + '</td>' + (mk ? '<td class="mk">' + (r[2] || '') + '</td>' : '') + '</tr>'; }).join('') + '</tbody></table></div>';
  var outs = [['h', f.home + ' win'], ['d', 'Draw'], ['a', f.away + ' win']];
  var shift = '';
  if (f.model_pre && md.lineups) {
    shift = '<div class="fb-mx-mkt"><div class="qk-kicker">What the confirmed line-ups changed</div>' +
      '<div class="qk-table-wrap"><table class="qk-table dense fb-mx-cmp"><thead><tr><th scope="col">Outcome</th><th class="num" scope="col">Before</th><th class="num" scope="col">With XIs</th><th class="num" scope="col">Change (pts)</th></tr></thead><tbody>' +
      outs.map(function (o) {
        var a = f.model_pre[o[0]], b = md[o[0]];
        return '<tr><td>' + esc(o[1]) + '</td><td class="num">' + pct(a, 1) + '</td><td class="num">' + pct(b, 1) + '</td><td class="num">' + pts(b - a) + '</td></tr>';
      }).join('') + '</tbody></table></div></div>';
  }
  var cap = '<p class="fb-cap">Ours: Dixon-Coles on goals and xG, with past closing lines as an input' + (md.lineups ? ' and the confirmed line-ups' : '') + '. ' +
    (mk ? esc(mlab) + ': the margin removed' + (mk.books > 1 ? ', the average of ' + mk.books + ' venues' : '') + (mk._at ? ', read ' + esc(FB.fmtStamp(mk._at)) : '') + '; shown for reference, it is not part of our forecast. ' : '') +
    '<a href="#/model/calibration">How our forecasts score →</a></p>';
  return FB.card(done ? 'Our pre-match call' : 'Our forecast', done ? 'What we said before kick-off, against what happened.' : 'Goals, the likeliest score and both sides scoring; the win chances are in the hero.', table + shift + cap, { flush: false });
}

/* The tale of the tape: our rating, Elo and the season's xG for both clubs (strength.json, team_stats.json). */
function tapeCard(c, f, side) {
  if (!side) return '';
  var st = {}, ts = ((side.team_stats || {}).teams) || {};
  (((side.strength || {}).rows) || []).forEach(function (r) { st[r.team] = r; });
  var h = st[f.home] || {}, a = st[f.away] || {}, th = (ts[f.home] || {}).season || {}, ta = (ts[f.away] || {}).season || {};
  var per = function (r, k) { return isNum(r[k]) && r.played ? r[k] / r.played : null; };
  var rows = [
    { label: 'Our rating (points a game)', a: h.strength_ppg, b: a.strength_ppg, fmt: function (v) { return num(v, 2); }, tip: 'Our model\'s expected points a game against an average side in this competition' },
    { label: 'Elo', a: h.elo, b: a.elo, fmt: function (v) { return num(v, 0); } },
    { label: 'Points a game', a: h.ppg, b: a.ppg, fmt: function (v) { return num(v, 2); } },
    { label: 'xG for a match', a: isNum(th.xg) ? th.xg : per(h, 'xg_for'), b: isNum(ta.xg) ? ta.xg : per(a, 'xg_for'), fmt: function (v) { return num(v, 2); } },
    { label: 'xG against a match', a: isNum(th.xga) ? th.xga : per(h, 'xg_against'), b: isNum(ta.xga) ? ta.xga : per(a, 'xg_against'), fmt: function (v) { return num(v, 2); }, better: 'low' },
    { label: 'Shots on target a match', a: th.sot, b: ta.sot, fmt: function (v) { return num(v, 1); } },
    { label: 'Possession', a: th.poss, b: ta.poss, fmt: function (v) { return Math.round(v) + '%'; } }
  ].filter(function (r) { return isNum(r.a) && isNum(r.b); });   // home on the left, as in the hero ("Home v Away")
  if (rows.length < 2) return '';
  var form = function (r) { return (r.form_results || []).length ? QK.formDots(r.form_results.join('')) : ''; };
  var team = function (tid, name) { return { name: name, logo: FB.crestUrl(tid), colour: FB.clubColour(tid), alt: FB.clubAlt(tid) }; };
  return FB.card('Tale of the tape', 'This season in ' + esc(c.name) + '; the better side\'s bar is solid.',
    QK.matchupBar({ left: team(f.home_id, f.home), right: team(f.away_id, f.away), rows: rows }) +
    (form(h) || form(a) ? '<div class="fb-mx-tform"><span>' + form(h) + '</span><span class="qk-muted">League form, oldest first</span><span>' + form(a) + '</span></div>' : ''), { span: 6 });
}

// Percentage points, signed: 0.034 -> "+3.4" (the column header says pts).
function pts(v) { return isNum(v) ? FB.signed(v * 100, 1) : '—'; }

// ── the confirmed XIs (fixtures[].xi: lineup_strength.live_terms) ─────────────

function xiCard(f) {
  var x = f.xi || {};
  function side(key, name) {
    var s = x[key] || {};
    var list = (s.xi || []).map(function (p) {
      var isNew = isNum(p.share) && p.share < 0.5;
      return '<li class="fb-cxi-p' + (isNew ? ' new' : '') + '"><span class="fb-cxi-no">' + esc(p.no || '') + '</span>' +
        FB.playerLink(p.id, p.n) + '<span class="fb-cxi-pos">' + esc(p.pos || '') + '</span>' +
        (isNew ? '<span class="qk-badge" data-tip="Started ' + Math.round(p.share * 100) + '% of the club\'s last ' + (s.n_usual || x.n_usual) + ' matches">In</span>' : '') + '</li>';
    }).join('');
    var out = (s.out || []).map(function (p) {
      return '<li>' + FB.playerLink(p.id, p.n || ('#' + p.id)) + ' <span class="qk-muted">started ' + Math.round(p.share * 100) + '% of the last ' + (s.n_usual || x.n_usual) + '</span></li>';
    }).join('');
    var inXi = {};
    (s.xi || []).forEach(function (p) { if (p.id) inXi[String(p.id)] = 1; });
    var miss = (s.missing || []).filter(function (p) { return !(p.id && inXi[String(p.id)]); }).map(function (p) { return esc(p.n); }).join(', ');
    var head = isNum(s.delta)
      ? FB.kpi('Against the usual XI', FB.signed(s.delta, 2), { sub: 'goals of expected goal difference a match', tip: 'The XI\'s player values minus the club\'s usual XI (its last ' + (s.n_usual || x.n_usual) + ' line-ups), both at today\'s values.' })
      : FB.kpi('Against the usual XI', '—', { sub: 'too few earlier line-ups to compare' });
    return FB.card(FB.clubLink(key === 'home' ? f.home_id : f.away_id, name), (s.f ? 'Formation ' + esc(s.f) : 'Starting XI'),
      FB.kpis([head]) + '<ol class="fb-cxi">' + list + '</ol>' +
      (out || miss ? '<p class="fb-cap">Who is missing and what it costs: the Absences section below.</p>' : ''), { span: 6 });
  }
  var lead = x.applied
    ? 'Our forecast above includes them: each XI is valued against the club\'s usual XI and the difference (' + FB.signed(x.d, 2) + ' goals a match, home minus away) tilts the expected goals.'
    : 'Shown for information: our forecast is not adjusted because a club has too few earlier line-ups to define its usual XI.';
  return '<div class="fb-mt">' + FB.note('<b>Confirmed line-ups</b>' + (x.at ? ' (read ' + esc(FB.fmtStamp(x.at)) + ')' : '') + '. ' + lead +
    ' <a href="#/model/methodology">How the line-up term works</a>.') + FB.grid(side('home', f.home) + side('away', f.away), 'fb-mt') + '</div>';
}

// ── the preview (no match page) ───────────────────────────────────────────

function preview(el, c, f, tape) {
  var box = el.querySelector('#mx-preview');
  if (!f.home_id || !f.away_id) { box.innerHTML = tape ? '<div class="fb-mt">' + FB.grid(tape) + '</div>' : ''; return; }
  box.innerHTML = '<div class="fb-mt">' + FB.loading('lines', 5) + '</div>';
  return FB.clubsIndex().then(function (ci) {
    var ok = function (t) { return !!ci.byId[String(t)]; };
    return Promise.all([ok(f.home_id) ? FB.load('clubs/' + f.home_id + '.json') : null, ok(f.away_id) ? FB.load('clubs/' + f.away_id + '.json') : null]);
  }).then(function (docs) {
    if (!FB.alive(el)) return;
    var h = docs[0], a = docs[1];
    function recent(doc) { return ((doc || {}).matches || []).filter(function (x) { return x.status === 'finished' && isNum(x.gf); }).slice(0, 6); }
    function form(doc, tid, name) {
      var list = recent(doc);
      if (!list.length) return FB.muted('No recent results.');
      return '<div class="fb-mx-formhead">' + FB.formChips(list.map(function (x) { return x.res || (x.gf > x.ga ? 'W' : x.gf < x.ga ? 'L' : 'D'); })) + '<span class="qk-muted">last ' + list.length + ', every competition</span></div>' +
        '<div class="fb-fxlist">' + list.map(function (x) { return clubMatchRow(x, tid, name); }).join('') + '</div>';
    }
    var h2h = ((h || {}).matches || []).filter(function (x) { return String(x.opp_tid) === String(f.away_id) && x.status === 'finished'; }).slice(0, 8);
    var hw = 0, dr = 0, aw = 0;
    h2h.forEach(function (x) { if (x.gf > x.ga) hw++; else if (x.gf === x.ga) dr++; else aw++; });
    box.innerHTML = '<section class="qk-section">' + QK.sectionHead({ kicker: 'Before kick-off', title: 'Form and history', sub: 'How both sides have been playing across every competition, and every meeting on record.' }) + FB.grid(
      (tape || '') +
      FB.card('Head to head', h2h.length ? hw + ' ' + esc(f.home) + ' wins · ' + dr + ' draws · ' + aw + ' ' + esc(f.away) + ' wins in the last ' + h2h.length + ' meetings on record' : 'No meeting on record.',
        h2h.length ? '<div class="fb-fxlist">' + h2h.map(function (x) { return clubMatchRow(x, f.home_id, f.home); }).join('') + '</div>' : '', { span: tape ? 6 : 12 }) +
      FB.card(FB.clubLink(f.away_id, f.away), 'Last six, every competition', form(a, f.away_id, f.away), { span: 6 }) +
      FB.card(FB.clubLink(f.home_id, f.home), 'Last six, every competition', form(h, f.home_id, f.home), { span: 6 })
    ) + '</section>';
  });
}

/* A club's match (clubs/<tid>.json matches[]) as a fixture row. */
function clubMatchRow(x, tid, name) {
  var home = x.home === 1 || x.home === true;
  var row = {
    id: x.id, date: x.date, status: x.status, round: x.round, stage: x.stage, detail: x.detail, comp: x.comp, xg: x.xg ? (home ? x.xg : [x.xg[1], x.xg[0]]) : null,
    home: home ? name : x.opp, away: home ? x.opp : name, home_id: home ? tid : x.opp_tid, away_id: home ? x.opp_tid : tid,
    hs: home ? x.gf : x.ga, as: home ? x.ga : x.gf
  };
  return FB.fixtureRow(row, { slug: x.comp, date: true, comp: true });
}

// ── the match page (detail) ───────────────────────────────────────────────

function sideOf(s, m) { return s.is_home === undefined || s.is_home === null ? (s.team === m.home ? 'home' : 'away') : (s.is_home ? 'home' : 'away'); }
function outcomeOf(s) { return FB.charts.outcomeOf(s); }
function situationOf(s) {
  var t = String(s.situation || '').toLowerCase();
  if (t === 'penalty') return 'penalty';
  if (t.indexOf('set-piece') >= 0 || t === 'corner' || t === 'free-kick' || t === 'set-piece' || t === 'throw-in-set-piece') return 'set';
  return 'open';
}
function onTarget(s) { var o = outcomeOf(s); return o === 'goal' || o === 'save'; }
function minuteText(s) { return (s.time || 0) + (s.added_time ? '+' + s.added_time : '') + '\''; }

function sideTotals(m) {
  var t = {};
  ['home', 'away'].forEach(function (side) {
    var shots = (m.shots || []).filter(function (s) { return sideOf(s, m) === side; });
    var sheet = ((m.team_stats || {})[side]) || {};
    var xg = shots.reduce(function (a, s) { return a + (s.xg || 0); }, 0);
    var pen = shots.filter(function (s) { return situationOf(s) === 'penalty'; }).reduce(function (a, s) { return a + (s.xg || 0); }, 0);
    t[side] = {
      xg: m.xg ? m.xg[side === 'home' ? 0 : 1] : (shots.length ? xg : null), npxg: shots.length ? xg - pen : null,
      xgot: isNum(sheet.expectedGoalsOnTarget) ? sheet.expectedGoalsOnTarget : (shots.length ? shots.filter(onTarget).reduce(function (a, s) { return a + (s.xgot || 0); }, 0) : null),
      shots: shots.length || sheet.totalShotsOnGoal || 0, sot: shots.length ? shots.filter(onTarget).length : (sheet.shotsOnGoal || 0),
      big: sheet.bigChanceCreated, poss: sheet.ballPossession, per_shot: shots.length ? xg / shots.length : null
    };
  });
  return t;
}

function detail(el, c, f, m) {
  var t = sideTotals(m);
  var pair = function (h, a, d) { return (isNum(h) ? num(h, d) : '—') + ' – ' + (isNum(a) ? num(a, d) : '—'); };
  var hasShots = (m.shots || []).length > 0;
  var box = el.querySelector('#mx-detail');
  var selects = FB.toolbar([
    FB.field('Team', FB.select('mx-sm-team', [['both', 'Both teams'], ['home', m.home], ['away', m.away]], 'both', 'Team')),
    FB.field('Situation', FB.select('mx-sm-sit', [['all', 'All situations'], ['open', 'Open play'], ['set', 'Set pieces'], ['penalty', 'Penalties']], 'all', 'Situation')),
    FB.field('Result', FB.select('mx-sm-res', [['all', 'All outcomes'], ['target', 'On target'], ['goal', 'Goals only']], 'all', 'Result'))
  ]);
  box.innerHTML =
    '<div class="fb-mt">' + FB.kpis([
      FB.kpi('Expected goals', pair(t.home.xg, t.away.xg, 2), { sub: 'non-penalty ' + pair(t.home.npxg, t.away.npxg, 2), tip: 'Expected goals: the chance each shot is scored, given where and how it was taken, summed.' }),
      FB.kpi('xG on target', pair(t.home.xgot, t.away.xgot, 2), { sub: 'quality of the shots that hit the target', tip: 'Post-shot xG: the chance a shot on target goes in, given where it was placed.' }),
      FB.kpi('Shots', t.home.shots + ' – ' + t.away.shots, { sub: 'on target ' + t.home.sot + ' – ' + t.away.sot }),
      FB.kpi('xG per shot', pair(t.home.per_shot, t.away.per_shot, 2), { sub: 'average chance quality' }),
      FB.kpi('Big chances', (isNum(t.home.big) ? t.home.big : '—') + ' – ' + (isNum(t.away.big) ? t.away.big : '—')),
      FB.kpi('Possession', isNum(t.home.poss) ? t.home.poss + '% – ' + t.away.poss + '%' : '—')
    ], 'fb-mx-kpis') + '</div>' +
    '<div class="fb-mt">' + FB.grid(
      FB.card('Expected result', 'What the chances were worth: every shot replayed 20,000 times at its xG.', '<div id="mx-exp"></div>', { span: 5 }) +
      FB.card('xG race', 'Cumulative xG minute by minute; <b style="color:var(--wp-b)">' + esc(m.home) + '</b> v <b style="color:var(--wp-a)">' + esc(m.away) + '</b>; goals marked.', FB.chartBox('mx-race', 320, 'Cumulative xG through the match'), { span: 7 })
    ) + '</div>' +
    '<div class="fb-mt">' + FB.card('Shot map', 'Size is xG; colour is the outcome. ' + esc(m.home) + ' attack to the right.', selects + '<div id="mx-shots"></div><p class="fb-cap" id="mx-sm-sum"></p>') + '</div>' +
    '<div class="fb-mt">' + FB.grid(
      FB.card(FB.crest(f.home_id, m.home, 'sm') + ' ' + esc(m.home) + ' · where the shots went', 'Shooter\'s view of the goal; size is xG on target.', FB.chartBox('mx-gm-h', 220, 'Goal mouth, ' + m.home), { span: 6 }) +
      FB.card(FB.crest(f.away_id, m.away, 'sm') + ' ' + esc(m.away) + ' · where the shots went', 'Shooter\'s view of the goal; size is xG on target.', FB.chartBox('mx-gm-a', 220, 'Goal mouth, ' + m.away), { span: 6 })
    ) + '</div>' +
    '<div class="fb-mt">' + FB.grid(
      FB.card('Timeline', 'Goals, cards and substitutions.', '<div id="mx-tl"></div>', { span: 5 }) +
      '<div class="qk-span-7 fb-mx-stack">' +
        FB.card('Momentum', 'Sofascore\'s pressure index by minute: up for ' + esc(m.home) + ', down for ' + esc(m.away) + '.', FB.chartBox('mx-mom', 200, 'Momentum by minute')) +
        FB.card('Who made the chances', 'xG from shots taken and xA from the passes that led to shots.', '<div id="mx-contrib"></div>') +
      '</div>'
    ) + '</div>' +
    '<div class="fb-mt">' + FB.card('Line-ups', 'Starting formations; the dot is the Sofascore rating (green high, red low), the number the shirt.', '<div id="mx-form"></div><div class="qk-grid fb-mt" id="mx-bench"></div>') + '</div>' +
    '<div class="fb-mt">' + FB.card('Team statistics', 'The better side in bold; derived ratios first.', '<div id="mx-sheet"></div>') + '</div>' +
    '<div class="fb-mt">' + FB.card('Player statistics', 'Every player who played; sort any column.', '<div class="fb-toolbar" id="mx-pt-pick"></div><div id="mx-pt"></div>', { flush: false }) + '</div>';

  drawExpected(el, m, hasShots);
  drawRace(el, m, hasShots);
  function shots() { drawShotMap(el, m); }
  ['mx-sm-team', 'mx-sm-sit', 'mx-sm-res'].forEach(function (id) { var n = el.querySelector('#' + id); if (n) n.addEventListener('change', shots); });
  shots();
  drawGoalMouth(el.querySelector('#mx-gm-h'), m, 'home');
  drawGoalMouth(el.querySelector('#mx-gm-a'), m, 'away');
  drawTimeline(el, m);
  drawMomentum(el, m);
  drawContrib(el, m);
  drawFormations(el, m);
  drawBench(el, m);
  drawSheet(el, m, t, f);
  drawPlayers(el, m, 'both');
}

/* mulberry32: the same match always gives the same numbers */
function rng(seed) {
  var a = seed >>> 0;
  return function () { a |= 0; a = a + 0x6D2B79F5 | 0; var t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
}
function simulate(m, n) {
  var rand = rng(parseInt(m.id, 10) || 7);
  var h = [], a = [];
  (m.shots || []).forEach(function (s) { (sideOf(s, m) === 'home' ? h : a).push(Math.min(Math.max(s.xg || 0, 0), 0.99)); });
  var grid = [], i, j;
  for (i = 0; i < 7; i++) { grid.push([0, 0, 0, 0, 0, 0, 0]); }
  var hw = 0, dr = 0, aw = 0;
  for (i = 0; i < n; i++) {
    var gh = 0, ga = 0;
    for (j = 0; j < h.length; j++) if (rand() < h[j]) gh++;
    for (j = 0; j < a.length; j++) if (rand() < a[j]) ga++;
    if (gh > ga) hw++; else if (gh === ga) dr++; else aw++;
    grid[Math.min(gh, 6)][Math.min(ga, 6)]++;
  }
  return { h: hw / n, d: dr / n, a: aw / n, grid: grid.map(function (r) { return r.map(function (v) { return v / n; }); }) };
}
function drawExpected(el, m, hasShots) {
  var box = el.querySelector('#mx-exp');
  if (!hasShots) { box.innerHTML = FB.muted('No shot data for this match.'); return; }
  var sim = simulate(m, 20000);
  var actual = m.hs > m.as ? 'h' : m.hs === m.as ? 'd' : 'a';
  var p = sim[actual];
  var verdict = !isNum(m.hs) ? '' : p >= 0.5 ? 'The result matched the chances.' : p >= 0.25 ? 'The result was plausible on the chances, not the most likely outcome.' : 'The result went against the run of the chances.';
  box.innerHTML = QK.wpBar(sim.h, sim.d, sim.a, { name: m.home }, { name: m.away }, { colors: [sideHex('home'), sideHex('away')], label: 'Chance of each result on the chances created' }) +
    (verdict ? '<p class="fb-cap">' + esc(verdict) + ' The actual result had a ' + pct(p) + ' chance. Rebounds count as separate chances, so this slightly overstates multi-goal outcomes.</p>' : '') +
    '<div class="qk-kicker fb-mt">Score grid · ' + esc(m.home) + ' goals down, ' + esc(m.away) + ' across</div>' + FB.chartBox('mx-grid', 240, 'Chance of each scoreline');
  var data = [];
  for (var i = 0; i < 6; i++) for (var j = 0; j < 6; j++) data.push([j, i, Math.round(sim.grid[i][j] * 1000) / 10]);
  QKC.heatmap(box.querySelector('#mx-grid'), { x: ['0', '1', '2', '3', '4', '5+'], y: ['0', '1', '2', '3', '4', '5+'], data: data, min: 0, fmt: function (v) { return v >= 0.5 ? Math.round(v) + '%' : ''; }, xName: m.away + ' goals', yName: m.home + ' goals', label: 'Scoreline probabilities' });
}

function drawRace(el, m, hasShots) {
  var box = el.querySelector('#mx-race');
  if (!hasShots) { box.style.height = 'auto'; box.innerHTML = FB.muted('No shot data.'); return; }
  var shots = (m.shots || []).filter(function (s) { return isNum(s.time); });
  var maxT = Math.max(90, shots.reduce(function (a, s) { return Math.max(a, (s.time || 0) + (s.added_time && s.time >= 90 ? s.added_time : 0)); }, 0)) + 1;
  var inc = {};
  shots.forEach(function (s) { var tm = minOf(s, maxT); var k = sideOf(s, m) === 'home' ? 0 : 1; inc[tm] = inc[tm] || [0, 0]; inc[tm][k] += s.xg || 0; });
  var x = [], hh = [], aa = [], ch = 0, ca = 0;
  for (var t = 0; t <= maxT; t++) {
    if (inc[t]) { ch += inc[t][0]; ca += inc[t][1]; }
    x.push(t); hh.push(Math.round(ch * 100) / 100); aa.push(Math.round(ca * 100) / 100);
  }
  var goals = shots.filter(function (s) { return outcomeOf(s) === 'goal'; });
  QKC.mount(box, function (T) {
    var hc = sideHex('home'), ac = sideHex('away');
    function line(name, data, col) {
      return { type: 'line', name: name, data: data, step: 'end', showSymbol: false, lineStyle: { width: 2.5, color: col }, itemStyle: { color: col },
        areaStyle: { color: QKC.hexA(col, 0.08) }, endLabel: { show: true, formatter: function (p) { return FB.clubCode(name, name === m.home ? m.away : m.home) + ' ' + Number(p.value).toFixed(2); }, color: T.ink1, fontFamily: T.fontDisplay, fontSize: 20 } };
    }
    var gp = goals.map(function (s) {
      var side = sideOf(s, m);
      var tm = minOf(s, maxT);
      return { value: [String(tm), (side === 'home' ? hh : aa)[tm]], name: (s.player_name || '') + ' ' + minuteText(s), itemStyle: { color: side === 'home' ? hc : ac, borderColor: T.s1, borderWidth: 2 } };
    });
    var xa = QKC.axis(T, { type: 'category', data: x.map(String), split: false, line: true, boundaryGap: false });
    var ya = QKC.axis(T, { fmt: function (v) { return v.toFixed(1); } });
    var gB = 8 + QKC.nameAxis(xa, 'Minute', 'bottom'), gT = 16 + QKC.nameAxis(ya, 'Expected goals, added up', 'side');
    return {
      grid: { left: 8, right: 120, top: gT, bottom: gB, containLabel: true },
      xAxis: xa, yAxis: ya,
      tooltip: QKC.tooltip(T, { trigger: 'axis', formatter: function (ps) {
        var mm = ps[0].axisValue;
        return '<div style="color:' + T.ink3 + ';font-size:11px">Minute ' + esc(mm) + '</div>' + ps.filter(function (q) { return q.seriesType === 'line'; }).map(function (q) { return QKC.tipRow(q.color, q.seriesName, Number(q.value).toFixed(2)); }).join('');
      } }),
      series: [line(m.home, hh, hc), line(m.away, aa, ac),
        { type: 'scatter', name: 'Goals', data: gp, symbolSize: 12, z: 5, tooltip: { show: false },
          label: { show: true, position: 'top', formatter: function (p) { return String(p.name).split(' ').slice(-2).join(' '); }, color: T.ink2, fontSize: 10, fontWeight: 600 } }]
    };
  }, { label: 'Cumulative xG through the match' });
}

function minOf(s, maxT) { return Math.min(maxT, s.time + (s.time >= 90 ? (s.added_time || 0) : 0)); }

function drawShotMap(el, m) {
  var team = el.querySelector('#mx-sm-team').value, sit = el.querySelector('#mx-sm-sit').value, res = el.querySelector('#mx-sm-res').value;
  var list = (m.shots || []).filter(function (s) { return isNum(s.x); })
    .filter(function (s) { return team === 'both' || sideOf(s, m) === team; })
    .filter(function (s) { return sit === 'all' || situationOf(s) === sit; })
    .filter(function (s) { return res === 'all' || (res === 'target' ? onTarget(s) : outcomeOf(s) === 'goal'); });
  var box = el.querySelector('#mx-shots');
  var shots = list.map(function (s) {
    return { x: s.x, y: s.y, side: sideOf(s, m), xg: s.xg, shot_type: s.shot_type, name: (s.player_name || '') + ' · ' + (sideOf(s, m) === 'home' ? m.home : m.away),
      time: s.time, added_time: s.added_time, body_part: s.body_part, situation: s.situation, href: s.player_id ? FB.href.player(s.player_id) : null };
  });
  if (!(m.shots || []).length) { box.innerHTML = FB.muted('No shot locations for this match.'); FB.set('mx-sm-sum', ''); return; }
  if (!shots.length) { box.innerHTML = FB.muted('No shot matches these filters.'); FB.set('mx-sm-sum', ''); return; }
  box.innerHTML = '';
  var host = document.createElement('div');
  box.appendChild(host);
  FB.charts.shotMap(host, shots, { surface: 'full', homeName: m.home, awayName: m.away, label: 'Shot map, ' + m.home + ' v ' + m.away });
  var tot = list.reduce(function (a, s) { return a + (s.xg || 0); }, 0);
  var sum = el.querySelector('#mx-sm-sum');
  if (sum) sum.textContent = list.length + ' shots · ' + num(tot, 2) + ' xG · ' + list.filter(onTarget).length + ' on target · ' + list.filter(function (s) { return outcomeOf(s) === 'goal'; }).length + ' goals · ' + num(list.length ? tot / list.length : 0, 2) + ' xG per shot';
}

function drawGoalMouth(box, m, side) {
  var shots = (m.shots || []).filter(function (s) { return sideOf(s, m) === side && isNum(s.gm_y) && isNum(s.gm_z) && s.gm_z <= 75 && s.gm_y >= 36 && s.gm_y <= 64; });
  if (!shots.length) { box.style.height = 'auto'; box.innerHTML = FB.muted((m.shots || []).length ? 'No goal-mouth data (older match format).' : 'No shots.'); return; }
  QKC.mount(box, function (T) {
    var col = FB.charts.outcomeColours(T);
    var frame = { type: 'line', data: [[44.6, 0], [44.6, 38], [55.4, 38], [55.4, 0]], symbol: 'none', silent: true, lineStyle: { color: T.ink1, width: 3 }, tooltip: { show: false }, z: 1 };
    var ground = { type: 'line', data: [[37, 0], [63, 0]], symbol: 'none', silent: true, lineStyle: { color: T.axis, width: 1 }, tooltip: { show: false } };
    var series = FB.charts.OUTCOMES.map(function (o) {
      var pts = shots.filter(function (s) { return outcomeOf(s) === o[0]; });
      return { type: 'scatter', name: o[1], z: 3, itemStyle: { color: col[o[0]] }, data: pts.map(function (s) {
        return { value: [100 - s.gm_y, s.gm_z, s.xgot || s.xg || 0], name: s.player_name + ' ' + minuteText(s), itemStyle: { color: col[o[0]], borderColor: T.s1, borderWidth: 1 } };
      }), symbolSize: function (v) { return 8 + Math.sqrt(Math.max(v[2], 0.01)) * 24; } };
    }).filter(function (s) { return s.data.length; });
    return {
      grid: { left: 4, right: 4, top: 24, bottom: 4 },
      legend: { top: 0, left: 0, icon: 'circle', itemWidth: 8, itemHeight: 8, textStyle: { color: T.ink2, fontSize: 10.5 }, data: series.map(function (s) { return s.name; }) },
      xAxis: { type: 'value', min: 37, max: 63, show: false, name: 'Across the goal' }, yAxis: { type: 'value', min: -3, max: 78, show: false, name: 'Height' },
      tooltip: QKC.tooltip(T, { formatter: function (p) { return '<b>' + esc(p.name) + '</b><br>' + esc(p.seriesName) + (isNum(p.value[2]) ? ' · ' + Number(p.value[2]).toFixed(2) : ''); } }),
      series: [ground, frame].concat(series)
    };
  }, { label: 'Where the shots went' });
}

function drawTimeline(el, m) {
  var box = el.querySelector('#mx-tl');
  var inc = (m.incidents || []).filter(function (i) { return ['goal', 'card', 'substitution'].indexOf(String(i.incident_type || '').toLowerCase()) >= 0; })
    .sort(function (a, b) { return (a.time + (a.added_time || 0) / 100) - (b.time + (b.added_time || 0) / 100); });
  if (!inc.length) { box.innerHTML = FB.muted('No events recorded.'); return; }
  box.innerHTML = '<ol class="fb-mx-tl">' + inc.map(function (i) {
    var t = String(i.incident_type).toLowerCase(), cls = String(i.incident_class || '').toLowerCase();
    var k = t === 'goal' ? 'goal' : t === 'card' ? (cls.indexOf('red') >= 0 ? 'red' : 'yellow') : 'sub';
    var who = i.player_id ? FB.playerLink(i.player_id, i.player_name) : esc(i.player_name || '');
    var text = k === 'sub' ? '<span class="fb-mx-in">▲ ' + esc(i.player_in || '') + '</span> <span class="fb-mx-out">▼ ' + esc(i.player_out || '') + '</span>'
      : k === 'goal' ? '<b>' + who + '</b>' + (cls === 'owngoal' ? ' (own goal)' : cls === 'penalty' ? ' (pen)' : '') + (i.assist ? ' <span class="qk-muted">assist ' + esc(i.assist) + '</span>' : '') + (isNum(i.home_score) ? ' <b class="fb-num">' + i.home_score + '–' + i.away_score + '</b>' : '')
      : who + (i.reason ? ' <span class="qk-muted">' + esc(i.reason) + '</span>' : '');
    var icon = k === 'goal' ? '<i class="fb-mx-ico goal" aria-label="Goal">●</i>' : k === 'sub' ? '<i class="fb-mx-ico sub" aria-label="Substitution">⇄</i>' : '<i class="fb-mx-ico card ' + k + '" aria-label="' + (k === 'red' ? 'Red card' : 'Yellow card') + '"></i>';
    return '<li class="' + (i.is_home ? 'h' : 'a') + ' k-' + k + '"><span class="fb-mx-min">' + esc(minuteText(i)) + '</span>' + icon + '<span class="fb-mx-ev">' + text + '<span class="fb-mx-evteam">' + esc(i.is_home ? m.home : m.away) + '</span></span></li>';
  }).join('') + '</ol>';
}

function drawMomentum(el, m) {
  var box = el.querySelector('#mx-mom');
  var mom = m.momentum || [];
  if (!mom.length) { box.style.height = 'auto'; box.innerHTML = FB.muted('No momentum data.'); return; }
  QKC.mount(box, function (T) {
    return {
      grid: { left: 8, right: 8, top: 26, bottom: 28, containLabel: true },
      xAxis: QKC.axis(T, { type: 'category', data: mom.map(function (x) { return String(x.minute); }), split: false, name: 'Minute', nameLocation: 'middle', nameGap: 26 }),
      yAxis: QKC.axis(T, { fmt: function () { return ''; }, name: 'Pressure, ' + m.home + ' up', nameAlign: 'left' }),
      tooltip: QKC.tooltip(T, { trigger: 'axis', formatter: function (ps) { var v = ps[0].value; return 'Minute ' + esc(ps[0].name) + '<br><b>' + esc(v >= 0 ? m.home : m.away) + '</b> ' + Math.abs(v); } }),
      series: [{ type: 'bar', barCategoryGap: '15%', data: mom.map(function (x) { return { value: x.value, itemStyle: { color: x.value >= 0 ? sideHex('home') : sideHex('away') } }; }) }]
    };
  }, { label: 'Momentum by minute' });
}

function drawContrib(el, m) {
  var box = el.querySelector('#mx-contrib');
  var rows = [];
  ['home', 'away'].forEach(function (side) { ((m.lineups || {})[side] || []).forEach(function (e) { if ((e.xg || 0) + (e.xa || 0) >= 0.03) rows.push({ side: side, e: e }); }); });
  if (!rows.length) {
    /* older format: the shots still give xG per player */
    var by = {};
    (m.shots || []).forEach(function (s) { var k = s.player_name || '?'; if (!by[k]) by[k] = { side: sideOf(s, m), e: { n: k, id: s.player_id, xg: 0, xa: 0 } }; by[k].e.xg += s.xg || 0; });
    rows = Object.keys(by).map(function (k) { return by[k]; }).filter(function (r) { return r.e.xg >= 0.03; });
  }
  if (!rows.length) { box.innerHTML = FB.muted('No per-player xG for this match.'); return; }
  rows.sort(function (a, b) { return ((b.e.xg || 0) + (b.e.xa || 0)) - ((a.e.xg || 0) + (a.e.xa || 0)); });
  var top = rows.slice(0, 12);
  box.innerHTML = FB.chartBox('mx-contrib-c', Math.max(200, 44 + top.length * 26), 'xG and xA by player');
  var tag = function (r) { return r.side === 'home' ? '●' : '○'; };
  QKC.bar(box.querySelector('#mx-contrib-c'), {
    horizontal: true, stack: true, legend: true, labelWidth: 140, fmt: function (v) { return num(v, 2); }, valName: 'xG plus xA',
    cats: top.map(function (r) { return tag(r) + ' ' + r.e.n + (r.e.g ? ' (' + r.e.g + 'G)' : '') + (r.e.a ? ' (' + r.e.a + 'A)' : ''); }),
    series: [{ name: 'xG (shots taken)', data: top.map(function (r) { return Math.round((r.e.xg || 0) * 100) / 100; }), color: cHex(1) }, { name: 'xA (chances created)', data: top.map(function (r) { return Math.round((r.e.xa || 0) * 100) / 100; }), color: cHex(3) }],
    hrefs: top.map(function (r) { return r.e.id ? FB.href.player(r.e.id) : null; }), label: 'Who made the chances'
  });
  box.insertAdjacentHTML('beforeend', '<p class="fb-cap">● ' + esc(m.home) + ' · ○ ' + esc(m.away) + '</p>');
}

function drawFormations(el, m) {
  var box = el.querySelector('#mx-form');
  var ph = FB.charts.lineupPoints((m.lineups || {}).home, (m.formation || {}).home, 'home');
  var pa = FB.charts.lineupPoints((m.lineups || {}).away, (m.formation || {}).away, 'away');
  if (!ph && !pa) { box.innerHTML = FB.muted('No formation for this match (older format or incomplete line-up); the squads are listed below.'); return; }
  var pts = [];
  [[ph, 'home', sideHex('home')], [pa, 'away', sideHex('away')]].forEach(function (x) {
    (x[0] || []).forEach(function (q) {
      var e = q.e || {};
      pts.push({ x: q.x, y: q.y, mark: e.no || '', rt: isNum(e.rt) ? e.rt : null, ring: x[2], label: FB.surname(e.n), sub: isNum(e.rt) ? num(e.rt, 1) : '',
        href: e.id ? FB.href.player(e.id) : null, tip: (e.n || '') + ' · ' + (FB.POS_LABEL[e.pos] || e.pos || '') + ' · ' + (e.min || 0) + '\'' + (isNum(e.rt) ? ' · rating ' + num(e.rt, 1) : '') + (e.g ? ' · ' + e.g + ' goal' + (e.g > 1 ? 's' : '') : '') + (e.a ? ' · ' + e.a + ' assist' + (e.a > 1 ? 's' : '') : '') });
    });
  });
  box.innerHTML = '<div class="fb-mx-formhead"><span><i class="fb-mx-sw" style="background:var(--wp-b)"></i>' + esc(m.home) + ' <b class="fb-num">' + esc((m.formation || {}).home || '') + '</b></span><span><b class="fb-num">' + esc((m.formation || {}).away || '') + '</b> ' + esc(m.away) + '<i class="fb-mx-sw" style="background:var(--wp-a)"></i></span></div><div id="mx-pitch"></div>';
  FB.charts.formation(box.querySelector('#mx-pitch'), { surface: 'full', points: pts, label: 'Starting line-ups' });
}

function drawBench(el, m) {
  var box = el.querySelector('#mx-bench');
  function row(e) {
    return '<li><span class="fb-mx-no">' + esc(e.no || '') + '</span>' + FB.posBadge(e.pos) + '<span class="fb-mx-pn">' + FB.playerLink(e.id, e.n) + (e.cap ? ' <span class="qk-muted">(c)</span>' : '') + '</span><span class="fb-num qk-muted">' + (e.min ? e.min + '\'' : '') + '</span>' +
      (isNum(e.rt) ? '<span class="fb-mx-rt" style="background:' + FB.charts.ratingColor(e.rt) + ';color:' + FB.charts.ratingInk(e.rt) + '">' + num(e.rt, 1) + '</span>' : '<span></span>') + '</li>';
  }
  function side(s, name) {
    var list = (m.lineups || {})[s] || [];
    var starters = list.filter(function (e) { return e.start; }), subs = list.filter(function (e) { return !e.start && (e.min || 0) > 0; }), unused = list.filter(function (e) { return !e.start && !(e.min > 0); });
    /* a player in the match squad is never also "Missing" (Sofascore can list a late fitness test as both) */
    var inSquad = {};
    list.forEach(function (e) { if (e.id) inSquad['i' + e.id] = 1; if (e.n) inSquad['n' + String(e.n).toLowerCase()] = 1; });
    var missing = ((m.missing || {})[s] || []).filter(function (x) { return !(x.id && inSquad['i' + x.id]) && !(x.n && inSquad['n' + String(x.n).toLowerCase()]); });
    var out = '<div class="qk-span-6"><div class="qk-kicker fb-mx-bh">' + esc(name) + '</div>';
    if (starters.length) out += '<div class="fb-mx-bt">Starting XI</div><ul class="fb-mx-list">' + starters.map(row).join('') + '</ul>';
    if (subs.length) out += '<div class="fb-mx-bt">Came on</div><ul class="fb-mx-list">' + subs.map(row).join('') + '</ul>';
    if (unused.length) out += '<div class="fb-mx-bt">Unused</div><ul class="fb-mx-list">' + unused.map(row).join('') + '</ul>';
    /* the missing players are the Absences section's (valued), below the line-ups */
    if (!list.length && !missing.length) out += FB.muted('No line-up.');
    return out + '</div>';
  }
  box.innerHTML = side('home', m.home) + side('away', m.away);
}

var SHEET = [
  ['Attack', [['expectedGoals', 'Expected goals', '2'], ['expectedGoalsOnTarget', 'xG on target (xGOT)', '2'], ['bigChanceCreated', 'Big chances'], ['bigChanceScored', 'Big chances scored'], ['bigChanceMissed', 'Big chances missed', 'lower'],
    ['totalShotsOnGoal', 'Shots'], ['shotsOnGoal', 'On target'], ['shotsOffGoal', 'Off target', 'lower'], ['blockedScoringAttempt', 'Blocked'], ['totalShotsInsideBox', 'Shots inside the box'], ['totalShotsOutsideBox', 'Shots outside the box'],
    ['hitWoodwork', 'Woodwork'], ['touchesInOppBox', 'Touches in the opposition box'], ['cornerKicks', 'Corners'], ['offsides', 'Offsides', 'lower']]],
  ['Possession and passing', [['ballPossession', 'Possession', '%'], ['passes', 'Passes'], ['accuratePasses', 'Accurate passes'], ['finalThirdEntries', 'Final-third entries'],
    ['finalThirdPhaseStatistic', 'Final-third passes', 'ratio'], ['accurateLongBalls', 'Long balls', 'ratio'], ['accurateCross', 'Crosses', 'ratio'], ['accurateThroughBall', 'Through balls'], ['dispossessed', 'Dispossessed', 'lower']]],
  ['Duels and defending', [['duelWonPercent', 'Duels won', '%'], ['groundDuelsPercentage', 'Ground duels', 'ratio'], ['aerialDuelsPercentage', 'Aerial duels', 'ratio'], ['dribblesPercentage', 'Dribbles', 'ratio'],
    ['totalTackle', 'Tackles'], ['wonTacklePercent', 'Tackles won', 'ratio'], ['interceptionWon', 'Interceptions'], ['ballRecovery', 'Recoveries'], ['totalClearance', 'Clearances'],
    ['fouls', 'Fouls', 'lower'], ['yellowCards', 'Yellow cards', 'lower'], ['redCards', 'Red cards', 'lower']]],
  ['Goalkeeping', [['goalkeeperSaves', 'Saves'], ['goalsPrevented', 'Goals prevented', '2'], ['diveSaves', 'Diving saves'], ['highClaims', 'High claims'], ['punches', 'Punches'], ['goalKicks', 'Goal kicks']]],
  ['Physical', [['kilometersCovered', 'Distance (km)', '1'], ['numberOfSprints', 'Sprints'], ['avgRating', 'Average rating', '2']]]
];
function duelRow(label, hv, av, f, lower, htxt, atxt) {
  if (!isNum(hv) && !isNum(av)) return '';
  hv = Number(hv) || 0; av = Number(av) || 0;
  var total = Math.abs(hv) + Math.abs(av) || 1;
  var text = function (v) { return f === '%' ? Math.round(v) + '%' : f === '2' ? Number(v).toFixed(2) : f === '1' ? Number(v).toFixed(1) : String(Math.round(v * 100) / 100); };
  var better = lower ? (hv < av ? 'h' : hv > av ? 'a' : '') : (hv > av ? 'h' : hv < av ? 'a' : '');
  return '<div class="fb-mx-duel"><span class="v' + (better === 'h' ? ' best' : '') + '">' + esc(htxt || text(hv)) + '</span>' +
    '<span class="l">' + esc(label) + '</span><span class="v r' + (better === 'a' ? ' best' : '') + '">' + esc(atxt || text(av)) + '</span>' +
    '<span class="bars"><span class="bh"><i style="width:' + (Math.abs(hv) / total * 100).toFixed(1) + '%"></i></span><span class="ba"><i style="width:' + (Math.abs(av) / total * 100).toFixed(1) + '%"></i></span></span></div>';
}
function drawSheet(el, m, t, f) {
  var h = (m.team_stats || {}).home, a = (m.team_stats || {}).away;
  var groups = [];
  var derived = duelRow('xG per shot', t.home.per_shot, t.away.per_shot, '2') + duelRow('Non-penalty xG', t.home.npxg, t.away.npxg, '2');
  if (h && a) {
    derived += duelRow('Pass accuracy', h.passes ? 100 * h.accuratePasses / h.passes : null, a.passes ? 100 * a.accuratePasses / a.passes : null, '%');
    var tilt = (h.touchesInOppBox || 0) + (a.touchesInOppBox || 0);
    if (tilt) derived += duelRow('Box-touch share (field tilt)', 100 * (h.touchesInOppBox || 0) / tilt, 100 * (a.touchesInOppBox || 0) / tilt, '%');
    var da = function (s) { return (s.totalTackle || 0) + (s.interceptionWon || 0) + (s.fouls || 0); };
    if (da(h) && da(a)) derived += duelRow('Opponent passes per defensive action (PPDA)', (a.passes || 0) / da(h), (h.passes || 0) / da(a), '1', true);
    if (isNum(h.expectedGoalsOnTarget) && isNum(a.expectedGoalsOnTarget)) derived += duelRow('Shot placement (xGOT − xG)', h.expectedGoalsOnTarget - (h.expectedGoals || 0), a.expectedGoalsOnTarget - (a.expectedGoals || 0), '2');
  }
  if (derived) groups.push(['Derived', derived]);
  if (h && a) {
    SHEET.forEach(function (g) {
      var body = g[1].map(function (r) {
        var k = r[0], fm = r[2];
        if (fm === 'ratio') return duelRow(r[1], h[k], a[k], '', false, isNum(h[k]) ? h[k] + '/' + (h[k + '_total'] || '?') : '—', isNum(a[k]) ? a[k] + '/' + (a[k + '_total'] || '?') : '—');
        return duelRow(r[1], h[k], a[k], fm, fm === 'lower');
      }).join('');
      if (body) groups.push([g[0], body]);
    });
  }
  var box = el.querySelector('#mx-sheet');
  if (!groups.length) { box.innerHTML = FB.muted('No team statistics for this match.'); return; }
  box.innerHTML = '<div class="fb-mx-sheethead"><span>' + FB.clubLink(f.home_id, m.home) + '</span><span>' + FB.clubLink(f.away_id, m.away) + '</span></div>' +
    (h && a ? '' : FB.note('No team-stat sheet for this match (older format); the derived rows come from the shots.')) +
    '<div class="fb-mx-sheet">' + groups.map(function (g) { return '<div class="fb-mx-sg"><div class="qk-kicker">' + esc(g[0]) + '</div>' + g[1] + '</div>'; }).join('') + '</div>';
}

function frac(a, b) { return !isNum(a) && !isNum(b) ? '' : (a || 0) + '/' + (b || 0); }
function drawPlayers(el, m, which) {
  var pick = el.querySelector('#mx-pt-pick');
  pick.innerHTML = FB.seg('mx-pt-side', [['both', 'Both teams'], ['home', m.home], ['away', m.away]], which, 'Team');
  FB.wireSeg(pick, 'mx-pt-side', function (v) { drawPlayers(el, m, v); });
  var rows = [];
  ['home', 'away'].forEach(function (side) {
    if (which !== 'both' && which !== side) return;
    ((m.lineups || {})[side] || []).forEach(function (e) {
      if (!((e.min || 0) > 0)) return;
      var r = {}; Object.keys(e).forEach(function (k) { r[k] = e[k]; });
      r.side = side; r.team = side === 'home' ? m.home : m.away;
      r.passpct = e.pt ? (e.pa || 0) / e.pt : null;
      r.duels = (e.dw || 0) + (e.dl || 0); r.aerial = (e.aw || 0) + (e.al || 0);
      rows.push(r);
    });
  });
  var box = el.querySelector('#mx-pt');
  if (!rows.length) { box.innerHTML = FB.muted('No player statistics for this match.'); return; }
  var blank = function (v, d) { return isNum(v) && v !== 0 ? (d !== undefined ? num(v, d) : String(v)) : ''; };
  FB.table(box, [
    { key: 'n', label: 'Player', sticky: true, fmt: function (v, r) { return '<span class="fb-mx-dot" style="background:' + sideVar(r.side) + '"></span>' + FB.playerLink(r.id, v) + (r.start ? '' : ' <span class="qk-muted">sub</span>'); } },
    { key: 'pos', label: 'Pos', fmt: function (v) { return FB.posBadge(v); } },
    { key: 'min', label: 'Min', num: true },
    { key: 'rt', label: 'Rating', num: true, fmt: function (v) { return isNum(v) ? '<span class="fb-mx-rt" style="background:' + FB.charts.ratingColor(v) + ';color:' + FB.charts.ratingInk(v) + '">' + num(v, 1) + '</span>' : ''; } },
    { key: 'g', label: 'G', num: true, fmt: function (v) { return blank(v); } },
    { key: 'a', label: 'A', num: true, fmt: function (v) { return blank(v); } },
    { key: 'xg', label: 'xG', num: true, fmt: function (v) { return blank(v, 2); } },
    { key: 'xa', label: 'xA', num: true, fmt: function (v) { return blank(v, 2); } },
    { key: 'sh', label: 'Sh', num: true, tip: 'Shots (on target)', fmt: function (v, r) { return v ? v + ' (' + (r.sot || 0) + ')' : ''; } },
    { key: 'kp', label: 'KP', num: true, tip: 'Key passes', fmt: function (v) { return blank(v); } },
    { key: 'bc', label: 'BC', num: true, tip: 'Big chances created', fmt: function (v) { return blank(v); } },
    { key: 'pt', label: 'Passes', num: true, tip: 'Accurate / attempted', fmt: function (v, r) { return v ? frac(r.pa, v) : ''; } },
    { key: 'passpct', label: 'Pass %', num: true, fmt: function (v) { return isNum(v) ? Math.round(v * 100) + '%' : ''; } },
    { key: 'lbt', label: 'Long', num: true, tip: 'Accurate long balls / attempted', fmt: function (v, r) { return v ? frac(r.lb, v) : ''; } },
    { key: 'crst', label: 'Crosses', num: true, fmt: function (v, r) { return v ? frac(r.crs, v) : ''; } },
    { key: 'tch', label: 'Touch', num: true, fmt: function (v) { return blank(v); } },
    { key: 'pc', label: 'Prog', num: true, tip: 'Progressive carries', fmt: function (v) { return blank(v); } },
    { key: 'dra', label: 'Drib', num: true, tip: 'Dribbles won / attempted', fmt: function (v, r) { return v ? frac(r.drw, v) : ''; } },
    { key: 'pl', label: 'Lost', num: true, tip: 'Possession lost', fmt: function (v) { return blank(v); } },
    { key: 'duels', label: 'Duels', num: true, tip: 'Won / contested', fmt: function (v, r) { return v ? frac(r.dw, v) : ''; } },
    { key: 'aerial', label: 'Aerial', num: true, tip: 'Won / contested', fmt: function (v, r) { return v ? frac(r.aw, v) : ''; } },
    { key: 'tk', label: 'Tkl', num: true, tip: 'Tackles won / attempted', fmt: function (v, r) { return v ? frac(r.tw, v) : ''; } },
    { key: 'int', label: 'Int', num: true, tip: 'Interceptions', fmt: function (v) { return blank(v); } },
    { key: 'rec', label: 'Rec', num: true, tip: 'Recoveries', fmt: function (v) { return blank(v); } },
    { key: 'clr', label: 'Clr', num: true, tip: 'Clearances', fmt: function (v) { return blank(v); } },
    { key: 'blk', label: 'Blk', num: true, tip: 'Blocks', fmt: function (v) { return blank(v); } },
    { key: 'fl', label: 'Fouls', num: true, tip: 'Committed / suffered', fmt: function (v, r) { return v || r.fld ? (v || 0) + '/' + (r.fld || 0) : ''; } },
    { key: 'sv', label: 'Saves', num: true, fmt: function (v) { return blank(v); } },
    { key: 'gp', label: 'GP', num: true, tip: 'Goals prevented: xGOT faced minus goals conceded', fmt: function (v, r) { return isNum(v) && r.pos === 'G' ? FB.signed(v, 2) : ''; } },
    { key: 'km', label: 'km', num: true, fmt: function (v) { return blank(v, 1); } },
    { key: 'ts', label: 'Top', num: true, tip: 'Top speed, km/h', fmt: function (v) { return blank(v, 1); } }
  ], rows, { sort: { key: 'rt', dir: 'desc' }, maxHeight: 620, caption: 'Player statistics' });
}

FB.matches = { clubMatchRow: clubMatchRow, simulate: simulate };
})(window.FB);
