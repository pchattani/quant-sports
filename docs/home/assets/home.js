/* The Quant home (kit v4 "Broadcast"). Reads data/home.json (scripts/build_home.py) and refreshes live scores in the
 * browser from each sport's published index.json on GitHub Pages (CORS: Access-Control-Allow-Origin *).
 *
 * Page, top to bottom (the Broadcast concept): the black ticker; the game to watch as the diagonal split hero with
 * our chance and "What's that number?"; "Six games. Our calls." (game cards with team stripes and a reason each);
 * the black power list ("Who's hot", one name per sport); the volt stat-of-the-day slab; "We say it. Then we check
 * it." (calibration bars from the sites' calibration.json) beside "Who's for real?" (NHL results against chances);
 * the title race in team colours, one league at a time; "What's that number?"; the sport tiles; every game; charts
 * of the week.
 * Our numbers lead everywhere; the market never appears on this page (STYLE_GUIDE.md §3). ?asof=<ISO> previews an
 * older snapshot (QK.now). */
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
function evening() { var h = new Date(QK.now()).getHours(); return h >= 15 || h < 5; }
function tonight() { return evening() ? 'tonight' : 'today'; }

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
  /* the market never shows on the home page */
  g.market_home = null;
}

function renderAll() {
  var jobs = [renderTicker, renderHero, renderWatch, renderHot, renderStats, renderHowSure, renderReal, renderRaces, renderTiles, renderChips, renderGames, renderCharts];
  jobs.forEach(function (f) { try { f(); } catch (e) { if (window.console) console.error(e); } });
  $('#updated').textContent = 'Data built ' + fmt.ago(D.updated_at) + ' (' + fmt.date(D.updated_at) + ' ' + fmt.time(D.updated_at) + '). Live scores refresh every minute while games are on.';
  QK.seg($('#when'), function (v) { state.when = v; state.shown = PAGE; renderGames(); });
}

function sportCount() { var n = D.sports.length; return (NUMS[n] || String(n)) + (n === 1 ? ' sport' : ' sports'); }
function liveMap() { var m = {}; D.games.forEach(function (g) { if (g.status === 'live') m[g.sport] = true; }); return m; }
function playable() { return D.games.filter(function (g) { return !g.event; }); }

/* ───────────────────────────── ticker (broadcast black) */
function renderTicker() {
  $('#ticker').innerHTML = QK.ticker(playable(), { max: 48 });
  shell.setLive(liveMap());
}

/* ───────────────────────────── the hero: the game to watch as the diagonal split, then "What's that number?" */
var featureId = null;
function tagOf(g) {
  var note = String(g.note || '');
  var m = /\bG(\d)\b|Game (\d)/.exec(note), n = m ? (m[1] || m[2]) : null;
  if (/Finals/i.test(note) && n) return note.split(' · ')[0].replace(/\s*G\d\b/, '') + ' · Game ' + n;
  if (n === '7') return 'Game 7';
  if (/CS\b|Series/i.test(note) && n) return (g.league || '') + ' · Game ' + n;
  if (g.status === 'live') return 'The game to watch';
  return 'Our pick ' + tonight();
}
function renderHero() {
  var list = playable().map(function (g) { return [QK.watchScore(g), g]; }).filter(function (x) { return x[0] > -1e8; }).sort(function (a, b) { return b[0] - a[0]; });
  var f = list.length ? list[0][1] : null;
  featureId = f ? f.sport + ':' + f.id : null;
  $('#hero').innerHTML = f ? QK.splitHero(f, { tag: tagOf(f) }) : QK.explain('<b>Nothing on right now.</b> The next games appear here as soon as they are scheduled.');
}

/* ───────────────────────────── what to watch: "Six games. Our calls." */
function renderWatch() {
  var pool = playable().filter(function (g) { return g.sport + ':' + g.id !== featureId; });
  var upcoming = pool.filter(function (g) { return g.status !== 'final'; }).length;
  var n = Math.min(6, upcoming);
  $('#h-watch').innerHTML = QK.sectionHead({ kicker: 'What to watch ' + tonight(), title: n ? (NUMS[n].charAt(0).toUpperCase() + NUMS[n].slice(1)) + ' game' + (n === 1 ? '' : 's') + '. Our calls.' : 'Nothing on right now',
    sub: 'Our chance for every side. Live games update as they go; the stripe up top splits the chances in team colours.',
    actions: '<a class="qk-more" href="#games">All ' + playable().length + ' games</a>' });
  $('#watch-grid').innerHTML = QK.watchGrid(pool, { limit: 6, card: { why: true } });
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
  $('#newhere').innerHTML = QK.newHere();
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

/* ───────────────────────────── "We say it. Then we check it." (calibration) */
var CAL_ORDER = ['hockey', 'basketball', 'nfl', 'baseball'];
function renderHowSure() {
  var C = D.calibration || {};
  var keys = CAL_ORDER.filter(function (k) { return C[k] && C[k].bins && C[k].bins.length; });
  var sec = $('#howsure');
  if (!keys.length) { sec.hidden = true; return; }
  if (!state.calib || keys.indexOf(state.calib) < 0) state.calib = keys[0];
  var seg = keys.length > 1 ? '<div class="qk-seg" id="hs-seg" role="group" aria-label="League">' + keys.map(function (k) { return '<button type="button" data-value="' + k + '" aria-pressed="' + (k === state.calib) + '">' + esc(C[k].league) + '</button>'; }).join('') + '</div>' : '';
  function draw(k) {
    var c = C[k], since = c.span ? ' since ' + String(c.span).split(' to ')[0] : '';
    $('#h-howsure').innerHTML = QK.sectionHead({ kicker: 'How sure are we?', title: 'We say it. Then we check it.',
      sub: 'Every ' + c.league + ' game' + since + ', grouped by the chance we gave ' + c.subject + '. When the two bars match, our numbers mean what they say.', actions: seg });
    QK.howSure('#howsure-body', { bins: c.bins, brier: c.brier, n: c.n, league: c.league, span: c.span, subject: c.subject, unit: c.unit || 'games' });
    if (seg) QK.seg($('#hs-seg'), function (v) { state.calib = v; draw(v); });
  }
  draw(state.calib);
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
var QUESTION = { hockey: 'Who lifts the Cup?', nfl: 'Who wins the Super Bowl?', baseball: 'Who wins the World Series?', f1: 'Who wins the drivers’ title?' };
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
  var tabs = RACE_ORDER.filter(function (k) { return F[k] && F[k].rows && F[k].rows.filter(function (r) { return r.p > 0; }).length > 1; }).map(function (k) {
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

/* ───────────────────────────── sport tiles */
function renderTiles() {
  var byKey = {}; D.sports.forEach(function (s) { byKey[s.key] = s; });
  var lm = liveMap();
  $('#tiles').innerHTML = QK.SPORTS.map(function (q) {
    var s = byKey[q.key] || {};
    var kp = (s.kpis || []).filter(function (k) { var v = k && k.value; return v !== null && v !== undefined && v !== '' && v !== '—' && v !== '-'; }).slice(0, 3);
    return '<a class="hm-tile" href="' + esc(QK.sportUrl(q.key)) + '" style="--sa:' + q.accent + '">' +
      '<div class="hm-tile-top"><span class="hm-tile-ic">' + QK.ICON[q.key] + '</span><div style="min-width:0"><div class="hm-tile-name">' + esc(q.label) + '</div><div class="hm-tile-site">' + esc(q.site) + '</div></div></div>' +
      '<div class="hm-tile-status">' + (lm[q.key] ? '<span class="qk-pill live">Live</span>' : '') + '<span class="qk-truncate">' + esc(s.ok === false ? 'Data unavailable' : (s.status || q.leagues)) + '</span></div>' +
      (kp.length ? '<div class="hm-tile-kpis">' + kp.map(function (k) { return '<div><div class="l">' + esc(k.label) + '</div><div class="v">' + esc(k.value) + '</div>' + (k.sub ? '<div class="s">' + esc(k.sub) + '</div>' : '') + '</div>'; }).join('') + '</div>' : '') + '</a>';
  }).join('');
}

/* ───────────────────────────── every game */
function gamesFor() {
  return playable().filter(function (g) {
    if (state.sport !== 'all' && g.sport !== state.sport) return false;
    return state.when === 'results' ? g.status === 'final' : g.status !== 'final';
  });
}
function renderChips() {
  var counts = { all: 0 };
  playable().forEach(function (g) { counts.all++; counts[g.sport] = (counts[g.sport] || 0) + 1; });
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
    html += QK.gameCard(g, { why: false });
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
  $('#chart-grid').innerHTML = out.join('');
  jobs.forEach(function (f) { try { f(); } catch (e) { if (window.console) console.error(e); } });
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
      if (changed) { renderTicker(); renderHero(); renderWatch(); renderGames(); }
    }, function () { /* offline or blocked: keep the built snapshot */ });
  });
}
function startLive() { refreshLive(); setInterval(refreshLive, 60000); document.addEventListener('visibilitychange', refreshLive); }
})();
