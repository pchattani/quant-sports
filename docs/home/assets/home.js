/* The Quant home (kit v3 "Matchday"). Reads data/home.json (scripts/build_home.py) and refreshes live scores in the
 * browser from each sport's published index.json on GitHub Pages (CORS: Access-Control-Allow-Origin *).
 *
 * Page, top to bottom (the Matchday concept): the black ticker; the greeting hero with a feature game; "What to watch"
 * (six game cards with a one-line reason each); "Who's hot" (one name per sport); the stat of the day beside "New
 * here? Three things to know"; "How sure are we?" (calibration from the sites' calibration.json); two title races;
 * every title race; the sport tiles; every game; charts of the week.
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
  var jobs = [renderTicker, renderHero, renderWatch, renderHot, renderStats, renderHowSure, renderRaces, renderFutures, renderTiles, renderChips, renderGames, renderCharts];
  jobs.forEach(function (f) { try { f(); } catch (e) { if (window.console) console.error(e); } });
  $('#updated').textContent = 'Data built ' + fmt.ago(D.updated_at) + ' (' + new Date(D.updated_at).toLocaleString() + '). Live scores refresh every minute while games are on.';
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

/* ───────────────────────────── greeting hero + feature game */
var featureId = null;
function scribble(g) {
  var note = String(g.note || '');
  var m = /\bG(\d)\b|Game (\d)/.exec(note), n = m ? (m[1] || m[2]) : null;
  if (/Finals/i.test(note) && n) return 'Finals, Game ' + n + '!';
  if (n === '7') return 'Game 7!';
  if (/CS\b|Series/i.test(note) && n) return 'Game ' + n + '!';
  if (g.status === 'live') return 'Live now!';
  return 'Our pick ' + tonight() + '!';
}
function renderHero() {
  var list = playable().map(function (g) { return [QK.watchScore(g), g]; }).filter(function (x) { return x[0] > -1e8; }).sort(function (a, b) { return b[0] - a[0]; });
  var f = list.length ? list[0][1] : null;
  featureId = f ? f.sport + ':' + f.id : null;
  var date = new Date(QK.now()).toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' }) + ' · ' + sportCount() + ', one place';
  $('#hero').innerHTML = QK.greeting({
    date: date,
    lede: 'Our forecasts and the numbers behind them, in plain English. Every number comes with a line on what it means, and how sure we are.',
    ctas: [{ label: evening() ? 'Tonight’s games' : 'Today’s games', href: '#watch' }, { label: 'How our forecasts do', href: '#howsure', ghost: true }],
    side: f ? QK.featureCard(f, { scribble: scribble(f) }) : ''
  });
}

/* ───────────────────────────── what to watch */
function renderWatch() {
  var pool = playable().filter(function (g) { return g.sport + ':' + g.id !== featureId; });
  var upcoming = pool.filter(function (g) { return g.status !== 'final'; }).length;
  var n = Math.min(6, upcoming);
  $('#h-watch').innerHTML = QK.sectionHead({ kicker: 'What to watch ' + tonight(), title: n ? (NUMS[n].charAt(0).toUpperCase() + NUMS[n].slice(1)) + ' game' + (n === 1 ? '' : 's') + ' we’d pick' : 'Nothing on right now',
    sub: 'Our chance for each side, with a line on why it’s worth your time. Live games update as they go.',
    actions: '<a class="qk-more" href="#games">All ' + playable().length + ' games</a>' });
  $('#watch-grid').innerHTML = QK.watchGrid(pool, { limit: 6, card: { why: true } });
}

/* ───────────────────────────── who's hot */
var HOT = ['hockey', 'football', 'baseball', 'f1', 'tennis_atp', 'nfl', 'tennis_wta'];
function renderHot() {
  var L = D.leaders || {};
  var items = HOT.filter(function (k) { return L[k] && L[k].rows && L[k].rows.length && L[k].hot; }).slice(0, 5).map(function (k) {
    var l = L[k], r0 = l.rows[0], r1 = l.rows[1];
    return { sport: k.split('_')[0], title: l.hot.title, name: r0.name, value: r0.value, unit: l.unit || '', href: r0.href,
      next: r1 ? { name: r1.name, value: r1.value } : null, expl: l.hot.expl };
  });
  $('#hot').innerHTML = items.length ? QK.hotRow(items) : QK.empty('No leaders yet');
}

/* ───────────────────────────── stat of the day + New here */
var statIdx = 0, statTimer = null;
function renderStats() {
  var S = D.stats || [];
  var el = $('#sotd');
  $('#newhere').innerHTML = QK.newHere();
  if (!S.length) { el.innerHTML = QK.empty('No featured stat today'); return; }
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

/* ───────────────────────────── how sure are we? */
var CAL_ORDER = ['hockey', 'basketball', 'nfl', 'baseball'];
function renderHowSure() {
  var C = D.calibration || {};
  var keys = CAL_ORDER.filter(function (k) { return C[k] && C[k].bins && C[k].bins.length; });
  var sec = $('#howsure');
  if (!keys.length) { sec.hidden = true; return; }
  if (!state.calib || keys.indexOf(state.calib) < 0) state.calib = keys[0];
  var seg = keys.length > 1 ? '<div class="qk-seg" id="hs-seg" role="group" aria-label="League">' + keys.map(function (k) { return '<button type="button" data-value="' + k + '" aria-pressed="' + (k === state.calib) + '">' + esc(C[k].league) + '</button>'; }).join('') + '</div>' : '';
  function draw(k) {
    var c = C[k];
    $('#h-howsure').innerHTML = QK.sectionHead({ kicker: 'How sure are we?', title: 'When we say 60%, does it happen 60% of the time?',
      sub: 'Every ' + c.league + ' game we’ve forecast, grouped by the chance we gave ' + c.subject + '. Dots on the dashed line mean the forecasts were honest.', actions: seg });
    QK.howSure('#howsure-body', { bins: c.bins, brier: c.brier, n: c.n, league: c.league, span: c.span, subject: c.subject, unit: c.unit || 'games' });
    if (seg) QK.seg($('#hs-seg'), function (v) { state.calib = v; draw(v); });
  }
  draw(state.calib);
}

/* ───────────────────────────── two title races, then every race */
var RACE_PICK = [['hockey', 'Hockey', 'Who lifts the Stanley Cup?'], ['basketball_2', 'NBA', 'Who wins the NBA title?'], ['nfl', 'NFL', 'Who wins the Super Bowl?'],
  ['basketball', 'Basketball', null], ['baseball', 'MLB', 'Who wins the World Series?'], ['college', 'College football', null]];
function raceLede(rows, sport) {
  var r = rows.slice().sort(function (a, b) { return b.p - a.p; });
  if (!r.length) return '';
  var top = r[0], nm = nick(top.name, sport);
  if (top.p < 0.2) return 'Nobody’s above 1 in 5. ' + nm + ' lead our board at ' + fmt.pct(top.p) + '.';
  var n = Math.round(1 / top.p);
  return nm + ' start as favourites, at about 1 in ' + n + ' (' + fmt.pct(top.p) + ').';
}
/* 'Colorado Avalanche' -> 'Avalanche' for the US leagues (the concept's title races read by nickname). */
var TWO_WORD = /(Maple Leafs|Red Wings|Golden Knights|Blue Jackets|Blue Jays|Red Sox|White Sox|Trail Blazers)$/;
function nick(name, sport) {
  if (['hockey', 'nfl', 'basketball', 'baseball'].indexOf(sport) < 0) return name;
  var m = TWO_WORD.exec(name);
  return m ? m[1] : String(name).split(' ').slice(-1)[0];
}
function chanceRows(rows, sport) { return rows.filter(function (r) { return r.p > 0; }).map(function (r) { return { label: sport ? nick(r.name, sport) : r.name, p: r.p, href: r.href, mark: r.abbr ? { abbr: r.abbr, colour: r.colour } : null }; }); }
function renderRaces() {
  var F = D.futures || {};
  var pick = RACE_PICK.filter(function (x) { return F[x[0]] && F[x[0]].rows && F[x[0]].rows.length > 1; }).slice(0, 2);
  $('#races').innerHTML = pick.map(function (x) {
    var f = F[x[0]];
    var title = x[2] || ('Who wins the ' + f.title.replace(/ title$/, '') + '?');
    return '<article class="qk-card hm-race"><div class="qk-card-body"><div class="qk-kicker">Title race · ' + esc(x[1]) + '</div><h3>' + esc(title) + '</h3><p class="hm-race-lede">' + esc(raceLede(f.rows, x[0].split('_')[0])) + '</p>' +
      QK.chances(chanceRows(f.rows, x[0].split('_')[0]), { limit: 6, key: false }) + '<a class="qk-more hm-race-more" href="' + esc(QK.sportUrl(x[0].split('_')[0])) + '">Full forecast</a></div></article>';
  }).join('');
}
function renderFutures() {
  var F = D.futures || {};
  var tabs = [];
  var ft = (D.charts || {}).football_titles || [];
  if (ft.length) tabs.push({ id: 'football', label: 'Football', sport: 'football' });
  /* A multi-league site writes one entry per league: <sport>, <sport>_2 (hardwood) or <sport>_<level> (campus). */
  [['nfl', 'NFL'], ['basketball', null], ['basketball_2', null], ['baseball', 'MLB'], ['hockey', 'NHL'], ['f1', 'F1'],
   ['college', 'CFB'], ['college_mbb', 'MBB'], ['college_wbb', 'WBB']].forEach(function (x) {
    if (F[x[0]]) tabs.push({ id: x[0], label: x[1] || F[x[0]].title.replace(' title', ''), sport: x[0].split('_')[0], title: F[x[0]].title });
  });
  $('#fut-tabs').innerHTML = tabs.map(function (t, i) { return '<button class="qk-tab" role="tab" id="ft-' + t.id + '" aria-controls="fp-' + t.id + '" aria-selected="' + (i === 0) + '"' + (t.title ? ' title="' + esc(t.title) + '"' : '') + '>' + esc(t.label) + '</button>'; }).join('');
  $('#fut-panels').innerHTML = tabs.map(function (t) { return '<div class="qk-tabpanel" role="tabpanel" id="fp-' + t.id + '" aria-labelledby="ft-' + t.id + '"></div>'; }).join('');
  var done = {};
  QK.tabs($('#fut-tabs'), function (pid) {
    var id = pid.slice(3);
    if (done[id]) return; done[id] = 1;
    var p = document.getElementById(pid);
    if (id === 'football') return footballFutures(p, ft);
    futuresPanel(p, F[id], id.split('_')[0]);
  });
}
function futuresPanel(p, f, sport) {
  var rows = f.rows.filter(function (r) { return r.p > 0; });
  var top = rows.slice().sort(function (a, b) { return b.p - a.p; });
  var lead = top[0];
  var top3 = top.slice(0, 3).reduce(function (a, r) { return a + r.p; }, 0);
  p.innerHTML = '<div class="hm-fut"><div><div class="qk-kicker" style="margin-bottom:12px">' + esc(f.title) + ' · our chance</div>' +
    QK.chances(chanceRows(rows), { limit: 12, key: false }) + '</div>' +
    '<div class="hm-fut-side">' + QK.stats([
      lead ? { label: 'Favourite', value: lead.name, text: true, sub: fmt.pct(lead.p) + ' to win', signal: true } : null,
      rows.length > 1 ? { label: 'The field', value: fmt.pct(1 - (lead ? lead.p : 0)), sub: 'chance someone else wins' } : null,
      top.length >= 3 ? { label: 'Top three combined', value: fmt.pct(top3), sub: top.slice(0, 3).map(function (r) { return r.abbr || r.name.split(' ').slice(-1)[0]; }).join(' · ') } : null,
      { label: 'Contenders', value: String(rows.filter(function (r) { return r.p >= 0.01; }).length), sub: 'with at least a 1% chance' }
    ]) + QK.note('From thousands of simulated seasons. ' + (lead ? fmt.pct(lead.p) + ' for the favourite still means it misses about ' + Math.max(1, Math.round(10 * (1 - lead.p))) + ' times in 10.' : '')) +
    '<a class="qk-more" href="' + esc(QK.sportUrl(sport)) + '">Full forecast on ' + esc(sportOf(sport).site) + '</a></div></div>';
}
function footballFutures(p, list) {
  p.innerHTML = '<div class="qk-row" style="margin-bottom:14px"><label class="qk-sub" for="fl-sel">League</label><select class="qk-select" id="fl-sel">' + list.map(function (l, i) { return '<option value="' + i + '">' + esc(l.league) + '</option>'; }).join('') + '</select></div><div class="fl-body"></div>';
  function show(i) { var l = list[i]; futuresPanel($('.fl-body', p), { title: l.league + ' title', rows: l.rows }, 'football'); }
  $('#fl-sel', p).addEventListener('change', function (e) { show(+e.target.value); });
  show(0);
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
  var xg = C.nhl_xg;
  if (xg && xg.points && xg.points.length) {
    out.push(card('qk-span-6', 'NHL: process v results', 'Points % against 5v5 expected-goals share: top left is winning more than the shots say', 'hockey', xg.href, '<div id="c-nhl" style="--h:320px"></div>'));
    jobs.push(function () { QKC.scatter('#c-nhl', { points: xg.points.map(function (p) { return { name: p.name, label: p.abbr, x: p.x, y: p.y, color: p.colour, href: p.href, size: 11 }; }), xName: 'Expected-goals share (5v5)', yName: 'Points %', xFmt: function (v) { return fmt.pct(v, 0); }, yFmt: function (v) { return fmt.pct(v, 0); }, refX: 0.5, refY: 0.5, labelTop: 10, quadrants: ['Running hot', 'Good and winning', 'Struggling', 'Unlucky'] }); });
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
