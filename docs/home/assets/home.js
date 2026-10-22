/* The Quant home (Design System 2.0). Reads data/home.json (scripts/build_home.py) and refreshes live scores in the
 * browser from each sport's published index.json on GitHub Pages (CORS: Access-Control-Allow-Origin *).
 * Our numbers lead everywhere; a market probability, where one exists, is a quiet reference (STYLE_GUIDE.md). */
(function () {
'use strict';
var $ = QK.$, $$ = QK.$$, esc = QK.esc, fmt = QK.fmt, isNum = QK.isNum;
var D = null;               // home.json
var PAGE = window.innerWidth < 600 ? 6 : 12;
var state = { sport: 'all', when: 'now', shown: PAGE };
var FOOTBALL_TOP = ['champions-league', 'premier-league', 'la-liga', 'serie-a', 'bundesliga', 'ligue-1', 'world-cup', 'euro', 'europa-league', 'libertadores'];

var shell = QK.shell({
  sport: null,
  search: { load: function () {
    return QK.fetchJSON('data/search.json').then(function (j) {
      return (j.rows || []).map(function (r) { return { sport: r[0], t: r[1], s: r[2], href: r[3] }; });
    });
  } }
});

function sportOf(k) { return QK.sport(k) || { label: k, accent: 'var(--accent)' }; }
function spIcon(k) { return '<span class="hm-sp-ic" style="--sa:' + sportOf(k).accent + '" aria-hidden="true">' + (QK.ICON[k] || '') + '</span>'; }

/* section heads (static copy) */
$('#h-sports').innerHTML = QK.sectionHead({ kicker: 'Eight sites, one look', title: 'Pick your sport', sub: 'Each site opens on today’s games, the standings, the players and the models behind them.' });
$('#h-futures').innerHTML = QK.sectionHead({ kicker: 'Season simulations', title: 'Who wins it all', sub: 'Our title chances from thousands of simulated seasons. Where a prediction market trades the same question, its number is a grey tick, for reference.' });
$('#h-charts').innerHTML = QK.sectionHead({ kicker: 'One picture per site', title: 'Charts of the week', sub: 'A headline chart from each sport. Tap through for the full story.' });
$('#h-leaders').innerHTML = QK.sectionHead({ kicker: 'Leaderboards', title: 'Leaders', sub: 'Who is top of the numbers that matter in each sport.' });
$('#h-games').innerHTML = QK.sectionHead({ kicker: 'Scoreboard', title: 'Games', sub: 'Our win chance on every card, the favourite in violet. Tap a game for the full breakdown.',
  actions: '<div class="qk-seg" id="when" role="group" aria-label="When"><button type="button" aria-pressed="true" data-value="now">Live &amp; next</button><button type="button" aria-pressed="false" data-value="results">Results</button></div>' });

/* ───────────────────────────── load */
QK.fetchJSON('data/home.json', { cache: 'no-cache' }).then(function (j) {
  D = j;
  /* accuracy guard: a game still marked live or upcoming 12 hours after its start is a stale snapshot, not a fact */
  D.games = (D.games || []).filter(function (g) { return g.status === 'final' || !g.start || (Date.now() - new Date(g.start)) / 36e5 < 12; });
  renderAll();
  startLive();
}, function (e) {
  $('#main').innerHTML = QK.empty('The home page data did not load', String(e && e.message || e));
});

function renderAll() {
  var today = new Date();
  $('#hero-date').textContent = today.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' }) + ' · ' + sportCount();
  var jobs = [renderTicker, renderHeroStats, renderFeature, renderStats, renderTiles, renderChips, renderGames, renderFutures, renderCharts, renderLeaders];
  jobs.forEach(function (f) { try { f(); } catch (e) { if (window.console) console.error(e); } });
  $('#updated').textContent = 'Data built ' + fmt.ago(D.updated_at) + ' (' + new Date(D.updated_at).toLocaleString() + '). Live scores refresh every minute while games are on.';
  QK.seg($('#when'), function (v) { state.when = v; state.shown = PAGE; renderGames(); });
}

var NUMS = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'];
function sportCount() { var n = D.sports.length; return (NUMS[n] || String(n)) + (n === 1 ? ' sport' : ' sports'); }
function liveMap() { var m = {}; D.games.forEach(function (g) { if (g.status === 'live') m[g.sport] = true; }); return m; }

/* ───────────────────────────── ticker */
function renderTicker() {
  $('#ticker').innerHTML = QK.ticker(D.games.filter(function (x) { return !x.event; }), { max: 48 });
  shell.setLive(liveMap());
}

/* ───────────────────────────── hero */
function isToday(iso) { return fmt.relDay(iso) === 'Today'; }
function twoWay(g) { return g.status === 'pre' && !g.event && isNum(g.p_home) && !isNum(g.p_draw); }
function label(g) { return (g.away.abbr || g.away.name) + ' @ ' + (g.home.abbr || g.home.name); }
function renderHeroStats() {
  var live = D.games.filter(function (g) { return g.status === 'live'; }).length;
  var today = D.games.filter(function (g) { return isToday(g.start) && !g.event; }).length;
  var soon = D.games.filter(function (g) { var h = (new Date(g.start) - Date.now()) / 36e5; return twoWay(g) && h > -1 && h < 36; });
  var close = soon.slice().sort(function (a, b) { return Math.abs(a.p_home - 0.5) - Math.abs(b.p_home - 0.5); })[0];
  var fav = soon.slice().sort(function (a, b) { return Math.abs(b.p_home - 0.5) - Math.abs(a.p_home - 0.5); })[0];
  function favTeam(g) { return g.p_home >= 0.5 ? g.home : g.away; }
  $('#hero-stats').innerHTML = QK.stats([
    { label: 'Live now', value: String(live), sub: live ? 'games in play' : 'nothing in play right now' },
    { label: 'On today', value: String(today), sub: 'games across the sites' },
    close ? { label: 'Closest call', value: label(close), text: true, href: close.href, sub: 'our chance ' + fmt.pct(Math.max(close.p_home, 1 - close.p_home)) + ' for ' + (favTeam(close).abbr || favTeam(close).name), tip: 'The upcoming game our model finds hardest to call' } : null,
    fav ? { label: 'Biggest favourite', value: (favTeam(fav).abbr || favTeam(fav).name) + ' ' + fmt.pct(Math.max(fav.p_home, 1 - fav.p_home)), text: true, signal: true, href: fav.href, sub: label(fav) + ' · ' + sportOf(fav.sport).label } : null
  ]);
}

function featureScore(g) {
  if (g.status === 'final') return -1e9;
  var hrs = (new Date(g.start) - Date.now()) / 36e5;
  if (g.status !== 'live' && (hrs > 96 || hrs < -6)) return -1e9;
  var s = g.status === 'live' ? 40 : 0;
  var note = String(g.note || '') + ' ' + String(g.league || '');
  if (/Finals|Final\b|CS|Series|SF|Super Bowl|Playoff/i.test(note)) s += 22;
  if (g.sport === 'football' && FOOTBALL_TOP.indexOf(g.comp) >= 0) s += 18;
  if (g.event) s += 16;
  if (isNum(g.p_home)) s += 10 * (1 - Math.abs(g.p_home - (isNum(g.p_draw) ? (1 - g.p_draw) / 2 : 0.5)) * 2);
  return s - Math.max(0, hrs) * 0.35;
}
function renderFeature() {
  var c = D.games.slice().sort(function (a, b) { return featureScore(b) - featureScore(a); })[0];
  var el = $('#feature');
  if (!c) { el.innerHTML = QK.empty('No marquee game right now'); return; }
  var sp = sportOf(c.sport);
  if (c.event) return featureRace(el, c, sp);
  var ac = QK.probColour(c.away, c.home, 'left'), hc = QK.probColour(c.home, c.away, 'right');
  el.style.setProperty('--fh', hc); el.style.setProperty('--fa', ac);
  var pA = isNum(c.p_away) ? c.p_away : (isNum(c.p_home) ? 1 - c.p_home - (c.p_draw || 0) : null);
  var live = c.status === 'live';
  var favA = isNum(pA) && isNum(c.p_home) && pA > c.p_home;
  var mid = live || c.status === 'final' ? '<span class="sc">' + esc(isNum(c.as) ? c.as : 0) + '–' + esc(isNum(c.hs) ? c.hs : 0) + '</span>' + QK.statusBadge(c) :
    '<span>' + esc(fmt.relDay(c.start)) + '</span><span class="tm">' + esc(fmt.time(c.start)) + '</span>';
  var pl = live ? 'live chance' : 'our chance';
  el.innerHTML = '<a class="qk-card-body" href="' + esc(c.href || '#') + '" style="display:block">' +
    '<div class="hm-feature-top"><span class="qk-sh-kicker" style="margin:0">Game of the day</span><span class="qk-sportpill" style="--sa:' + sp.accent + '">' + esc(sp.label) + ' · ' + esc(c.league) + (c.note ? ' · ' + esc(c.note) : '') + '</span></div>' +
    '<div class="hm-vs"><div class="hm-vs-team">' + QK.teamMark(c.away, 'lg') + '<span class="nm">' + esc(c.away.name) + '</span><span class="p' + (favA ? ' fav' : '') + '">' + (isNum(pA) ? fmt.pct(pA) : '') + '</span><span class="pl">' + pl + '</span></div>' +
    '<div class="hm-vs-mid">' + mid + '</div>' +
    '<div class="hm-vs-team">' + QK.teamMark(c.home, 'lg') + '<span class="nm">' + esc(c.home.name) + '</span><span class="p' + (!favA ? ' fav' : '') + '">' + (isNum(c.p_home) ? fmt.pct(c.p_home) : '') + '</span><span class="pl">' + pl + '</span></div></div>' +
    QK.wpBar(pA, c.p_draw, c.p_home, c.away, c.home, { size: 'lg', labels: false, label: live ? 'Live win chance' : 'Our win chance' }) +
    '<div class="hm-feature-foot"><span>' + (isNum(c.p_draw) ? 'Draw <b>' + fmt.pct(c.p_draw) + '</b>' : (live ? 'Our live model' : 'Our pre-game model')) + '</span>' +
    (isNum(c.total) ? '<span>Projected total <b>' + fmt.num(c.total, 1) + '</b></span>' : '') +
    (isNum(c.market_home) && c.status === 'pre' ? '<span class="qk-mkt">Market <b>' + esc(c.home.abbr || c.home.name) + ' ' + fmt.pct(c.market_home) + '</b></span>' : '') + '</div></a>';
}
function featureRace(el, c, sp) {
  var r = D.charts.f1_next_race || {};
  var f = (r.field || []).slice(0, 6);
  el.style.setProperty('--fh', 'var(--a-f1)'); el.style.setProperty('--fa', 'var(--a-f1)');
  el.innerHTML = '<a class="qk-card-body" href="' + esc(r.href || c.href) + '" style="display:block"><div class="hm-feature-top"><span class="qk-sh-kicker" style="margin:0">Race weekend</span><span class="qk-sportpill" style="--sa:' + sp.accent + '">F1 · Round ' + esc(r.round) + '</span></div>' +
    '<h3 class="qk-display" style="font-size:var(--fs-xl);margin-top:10px">' + esc(r.name) + '</h3><div class="qk-sub">' + esc(r.circuit || '') + ' · ' + esc(r.locality || '') + ' · lights out ' + esc(fmt.date((r.sessions || {}).race || r.date)) + ' ' + esc(fmt.time((r.sessions || {}).race)) + '</div>' +
    '<div class="hm-race">' + QK.chances(f.map(function (d) { return { label: d.code || d.name, p: d.p || 0, market: d.market, color: d.colour }; }), { oursName: 'Our chance to win' }) + '</div></a>';
}

var statIdx = 0, statTimer = null;
function renderStats() {
  var S = D.stats || [];
  var el = $('#stat');
  if (!S.length) { el.innerHTML = QK.empty('No featured stat today'); return; }
  var day = Math.floor(Date.now() / 864e5);
  statIdx = day % S.length;
  function paint() {
    var s = S[statIdx], sp = sportOf(s.sport);
    el.style.setProperty('--sa', sp.accent);
    el.innerHTML = '<div class="qk-row" style="justify-content:space-between"><span class="qk-sh-kicker" style="margin:0">Stat of the day · ' + esc(s.kicker) + '</span>' + spIcon(s.sport) + '</div>' +
      '<a href="' + esc(s.href || '#') + '"><div class="big">' + esc(s.value) + '</div><div class="unit">' + esc(s.unit || '') + '</div><p>' + esc(s.text) + '</p></a>' +
      '<div class="hm-stat-nav" role="group" aria-label="More stats">' + S.map(function (x, i) { return '<button type="button" aria-label="Stat ' + (i + 1) + ': ' + esc(x.kicker) + '" aria-pressed="' + (i === statIdx) + '" data-i="' + i + '"></button>'; }).join('') + '</div>';
    $$('.hm-stat-nav button', el).forEach(function (b) { b.addEventListener('click', function () { statIdx = +b.getAttribute('data-i'); paint(); restart(); }); });
  }
  function restart() { if (statTimer) clearInterval(statTimer); if (!QK.reducedMotion()) statTimer = setInterval(function () { statIdx = (statIdx + 1) % S.length; paint(); }, 9000); }
  paint(); restart();
  el.addEventListener('mouseenter', function () { if (statTimer) clearInterval(statTimer); });
  el.addEventListener('mouseleave', restart);
}

/* ───────────────────────────── sport tiles */
function renderTiles() {
  var byKey = {}; D.sports.forEach(function (s) { byKey[s.key] = s; });
  var lm = liveMap();
  $('#tiles').innerHTML = QK.SPORTS.map(function (q) {
    var s = byKey[q.key] || {};
    var url = QK.sportUrl(q.key);
    /* a tile figure with no value (a dash, nothing behind it) says nothing: leave it out */
    var kp = (s.kpis || []).filter(function (k) { var v = k && k.value; return v !== null && v !== undefined && v !== '' && v !== '—' && v !== '-'; }).slice(0, 3);
    return '<a class="hm-tile" href="' + esc(url) + '" style="--sa:' + q.accent + '"><svg class="hm-tile-go" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M3 8h10M9 4l4 4-4 4"/></svg>' +
      '<div class="hm-tile-top"><span class="hm-tile-ic">' + QK.ICON[q.key] + '</span><div><div class="hm-tile-name">' + esc(q.label) + '</div><div class="hm-tile-site">' + esc(q.site) + '</div></div></div>' +
      '<div class="hm-tile-status">' + (lm[q.key] ? '<span class="qk-badge live">Live</span>' : '') + '<span class="qk-truncate">' + esc(s.ok === false ? 'Data unavailable' : (s.status || q.leagues)) + '</span></div>' +
      (kp.length ? '<div class="hm-tile-kpis">' + kp.map(function (k) { return '<div><div class="l">' + esc(k.label) + '</div><div class="v">' + esc(k.value) + '</div>' + (k.sub ? '<div class="s">' + esc(k.sub) + '</div>' : '') + '</div>'; }).join('') + '</div>' : '') + '</a>';
  }).join('');
}

/* ───────────────────────────── games */
function gamesFor() {
  return D.games.filter(function (g) {
    if (state.sport !== 'all' && g.sport !== state.sport) return false;
    if (g.event) return false;
    return state.when === 'results' ? g.status === 'final' : g.status !== 'final';
  });
}
function renderChips() {
  var counts = { all: 0 };
  D.games.forEach(function (g) { if (!g.event) { counts.all++; counts[g.sport] = (counts[g.sport] || 0) + 1; } });
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
    html += QK.gameCard(g);
  });
  grid.innerHTML = html;
  $$('.qk-gc', grid).forEach(function (el, i) { el.style.animationDelay = Math.min(i, 12) * 25 + 'ms'; });
  var more = list.length - state.shown;
  $('#game-more').innerHTML = more > 0 ? '<button class="qk-btn" type="button">Show ' + Math.min(more, PAGE) + ' more <span class="qk-muted">of ' + more + '</span></button>' : '';
  var b = $('#game-more button'); if (b) b.addEventListener('click', function () { state.shown += PAGE; renderGames(); });
}

/* ───────────────────────────── title races */
function renderFutures() {
  var F = D.futures || {};
  var tabs = [];
  var ft = D.charts.football_titles || [];
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
  var lead = rows.slice().sort(function (a, b) { return b.p - a.p; })[0];
  var top = rows.slice().sort(function (a, b) { return b.p - a.p; }).slice(0, 3);
  var top3 = top.reduce(function (a, r) { return a + r.p; }, 0);
  p.innerHTML = '<div class="hm-fut"><div><div class="qk-kicker" style="margin-bottom:10px">' + esc(f.title) + ' · our chance</div>' +
    QK.chances(rows.map(function (r) { return { label: r.name, p: r.p, market: r.market, color: r.colour, href: r.href, mark: r.abbr ? { abbr: r.abbr, colour: r.colour } : null }; }), { limit: 12 }) + '</div>' +
    '<div class="hm-fut-side">' + QK.stats([
      lead ? { label: 'Favourite', value: lead.name, text: true, sub: fmt.pct(lead.p) + ' to win', signal: true } : null,
      rows.length > 1 ? { label: 'The field', value: fmt.pct(1 - (lead ? lead.p : 0)), sub: 'chance someone else wins' } : null,
      top.length === 3 ? { label: 'Top three combined', value: fmt.pct(top3), sub: top.map(function (r) { return r.abbr || r.name.split(' ').slice(-1)[0]; }).join(' · ') } : null,
      { label: 'Contenders', value: String(rows.filter(function (r) { return r.p >= 0.01; }).length), sub: 'with at least a 1% chance' }
    ]) +
    '<a class="qk-btn" href="' + esc(QK.sportUrl(sport)) + '">Full forecast on ' + esc(sportOf(sport).site) + ' →</a></div></div>';
}
function footballFutures(p, list) {
  p.innerHTML = '<div class="qk-row" style="margin-bottom:12px"><label class="qk-sub" for="fl-sel">League</label><select class="qk-select" id="fl-sel">' + list.map(function (l, i) { return '<option value="' + i + '">' + esc(l.league) + '</option>'; }).join('') + '</select></div><div class="fl-body"></div>';
  function show(i) {
    var l = list[i];
    futuresPanel($('.fl-body', p), { title: l.league + ' title', rows: l.rows }, 'football');
  }
  $('#fl-sel', p).addEventListener('change', function (e) { show(+e.target.value); });
  show(0);
}

/* ───────────────────────────── charts of the week */
function card(span, title, sub, sport, href, body) {
  var sp = sportOf(sport);
  return '<div class="qk-card ' + span + '" style="--accent:' + sp.accent + '"><div class="qk-card-head"><div><div class="qk-card-title">' + esc(title) + '</div><div class="qk-card-sub">' + esc(sub) + '</div></div>' + spIcon(sport) + '</div>' +
    '<div class="qk-card-body">' + body + '</div>' + (href ? '<div class="qk-card-foot"><span>' + esc(sp.site) + '</span><a href="' + esc(href) + '">Open →</a></div>' : '') + '</div>';
}
function renderCharts() {
  var C = D.charts || {}, out = [], jobs = [];
  var tr = C.f1_title_race;
  if (tr && tr.series && tr.series.length) {
    out.push(card('qk-span-8', 'F1 title race', 'Drivers’ points after every round of ' + tr.year + ', each line labelled at its end', 'f1', tr.href, '<div id="c-f1" style="--h:300px"></div>'));
    jobs.push(function () { QKC.line('#c-f1', { x: tr.rounds, xName: 'Round', yName: 'Points', xLabel: function (r) { return 'Round ' + r; }, label: 'F1 drivers championship points by round', series: tr.series.map(function (s) { return { name: s.code || s.name, label: s.code, color: s.colour, dash: s.dash, data: s.points }; }) }); });
  }
  var nr = C.f1_next_race;
  if (nr && nr.field && nr.field.length) {
    out.push(card('qk-span-4', nr.name, 'Our chance of winning the race; grey tick: the market', 'f1', nr.href, QK.chances(nr.field.slice(0, 8).map(function (d) { return { label: d.code || d.name, sub: '', p: d.p || 0, market: d.market, color: d.colour, href: d.href }; }))));
  }
  var mv = C.nfl_movers;
  if (mv && mv.series && mv.series.length) {
    out.push(card('qk-span-6', 'NFL: who has moved', 'Net rating by week, the six biggest changes since week 1 (points v an average team)', 'nfl', mv.href, '<div id="c-nfl" style="--h:300px"></div>'));
    jobs.push(function () { QKC.line('#c-nfl', { x: mv.series[0].weeks.map(function (w) { return 'W' + w; }), xName: 'Week', yName: 'Rating (pts v average)', ref: { y: 0, label: 'average' }, yFmt: function (v) { return fmt.signed(v, 1); }, label: 'NFL net rating movers', series: mv.series.map(function (s) { return { name: s.abbr, label: s.abbr + ' ' + fmt.signed(s.delta, 1), data: s.net }; }) }); });
  }
  var xg = C.nhl_xg;
  if (xg && xg.points && xg.points.length) {
    out.push(card('qk-span-6', 'NHL: process v results', 'Points % against 5v5 expected-goals share: top left is winning more than the shots say', 'hockey', xg.href, '<div id="c-nhl" style="--h:300px"></div>'));
    jobs.push(function () { QKC.scatter('#c-nhl', { points: xg.points.map(function (p) { return { name: p.name, label: p.abbr, x: p.x, y: p.y, color: p.colour, href: p.href, size: 11 }; }), xName: 'Expected-goals share (5v5)', yName: 'Points %', xFmt: function (v) { return fmt.pct(v, 0); }, yFmt: function (v) { return fmt.pct(v, 0); }, refX: 0.5, refY: 0.5, labelTop: 10, quadrants: ['Running hot', 'Good and winning', 'Struggling', 'Unlucky'] }); });
  }
  var fav = C.football_favourites;
  if (fav && fav.length) {
    var top = fav.slice(0, 10);
    out.push(card('qk-span-6', 'Football: title favourites', 'Each league’s favourite and our title chance from the season simulation', 'football', QK.sportUrl('football'), QK.chances(top.map(function (f) { return { label: f.team, sub: f.league, p: f.p, href: f.href }; }), { max: 1, sort: false })));
  }
  var ms = C.mlb_series;
  if (ms && ms.length) {
    out.push(card('qk-span-6', 'MLB postseason', 'Series in play: wins so far and our chance to advance', 'baseball', QK.sportUrl('baseball') + '#/postseason', '<div class="hm-series">' + ms.map(function (s) {
      var pa = s.p && isNum(s.p[0]) ? s.p[0] : null;
      return '<div class="hm-series-row"><div class="qk-kicker">' + esc(s.round) + ' · best of ' + esc(s.best_of) + '</div>' +
        '<div class="hm-series-teams"><span class="qk-row">' + QK.teamMark(s.a) + esc(s.a.name) + '</span><span class="w">' + esc(s.wins[0]) + '–' + esc(s.wins[1]) + '</span><span class="qk-row">' + esc(s.b.name) + QK.teamMark(s.b) + '</span></div>' +
        (isNum(pa) ? QK.wpBar(pa, null, 1 - pa, s.a, s.b, { label: 'Our chance to advance', market: s.market && isNum(s.market[0]) ? s.market[0] : null }) : '') + '</div>';
    }).join('') + wsOdds() + '</div>'));
  }
  var np = C.nba_power;
  if (np && np.rows && np.rows.length) {
    var r = np.rows.slice(0, 8).concat(np.rows.slice(-4));
    out.push(card('qk-span-12', 'NBA: power ratings', 'Net rating (points per 100 possessions v average): the top eight and the bottom four', 'basketball', QK.sportUrl('basketball'), '<div id="c-nba" style="--h:260px"></div>'));
    jobs.push(function () { QKC.bar('#c-nba', { cats: r.map(function (x) { return x.abbr; }), series: [{ name: 'Net rating', data: r.map(function (x) { return x.value; }) }], diverging: true, hrefs: r.map(function (x) { return x.href; }), labels: true, catName: 'Team', valName: 'Net rating (pts per 100 poss.)', fmt: function (v) { return fmt.signed(v, 1); } }); });
  }
  $('#chart-grid').innerHTML = out.join('');
  jobs.forEach(function (f) { try { f(); } catch (e) { if (window.console) console.error(e); } });
}

function wsOdds() {
  var f = (D.futures || {}).baseball;
  if (!f || !f.rows.length) return '';
  return '<div class="qk-kicker" style="margin-top:6px">World Series · our chance</div>' + QK.chances(f.rows.map(function (r) { return { label: r.name, p: r.p, market: r.market, color: r.colour, href: r.href }; }), { key: false });
}

/* ───────────────────────────── leaders */
function renderLeaders() {
  var L = D.leaders || {};
  var keys = ['football', 'nfl', 'baseball', 'hockey', 'f1', 'tennis_atp', 'tennis_wta'];
  $('#leader-grid').innerHTML = keys.filter(function (k) { return L[k] && L[k].rows && L[k].rows.length; }).map(function (k) {
    var l = L[k], sport = k.split('_')[0], sp = sportOf(sport);
    var rows = l.rows.slice(0, 5);
    var mx = Math.max.apply(null, rows.map(function (r) { return Math.abs(r.value) || 0; }));
    var mn = k.indexOf('tennis') === 0 ? Math.min.apply(null, l.rows.map(function (r) { return r.value; })) - 50 : 0;
    return '<div class="qk-card" style="--sa:' + sp.accent + '"><div class="qk-card-head"><div><div class="qk-card-title">' + esc(l.title) + '</div><div class="qk-card-sub">' + esc(sp.label) + (k.indexOf('tennis_') === 0 ? ' · ' + esc(k.slice(7).toUpperCase()) : '') + '</div></div>' + spIcon(sport) + '</div><div class="qk-card-body flush" style="padding:8px 0 12px">' +
      rows.map(function (r, i) {
        var w = mx > mn ? 100 * ((Math.abs(r.value) || 0) - mn) / (mx - mn) : 0;
        return '<a class="hm-lead-row" href="' + esc(r.href || '#') + '"><span class="r">' + (i + 1) + '</span><span class="n">' + esc(r.name) + (r.team ? '<small>' + esc(r.team) + '</small>' : '') + '</span><span class="v">' + esc(isNum(r.value) ? fmt.num(r.value, r.value % 1 ? 1 : 0) : r.value) + (l.unit ? ' <small class="qk-muted" style="font:500 11px var(--font-ui)">' + esc(l.unit) + '</small>' : '') + '</span></a>' +
          '<div class="hm-lead-bar" aria-hidden="true"><i style="width:' + w + '%"></i></div>';
      }).join('') + '</div></div>';
  }).join('');
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
  basketball: ['index.json', function (j) { var out = []; Object.keys(j.leagues || {}).forEach(function (L) { var l = j.leagues[L]; ['today', 'next_games', 'last_games'].forEach(function (k) { (l[k] || []).forEach(function (g) { out.push({ id: g.id, status: g.status, hs: g.hs, as: g.as, period: g.period, clock: g.clock }); }); }); }); return out; }],
  baseball: ['index.json', function (j) { return [].concat(j.today || [], j.recent || [], j.upcoming || []).map(function (g) { return { id: g.gpk, status: g.status, hs: g.hs, as: g.as, period: g.inning }; }); }],
  nfl: ['index.json', function (j) { return [].concat(j.live || [], j.games || [], j.recent || []).map(function (g) { return { id: g.game_id, status: g.status, hs: g.hs, as: g.as, period: g.qtr, clock: g.clock }; }); }],
  hockey: ['index.json', function (j) { return [].concat(j.live || [], j.today || [], j.recent || [], j.upcoming || []).map(function (g) { return { id: g.game_id, status: g.status, hs: g.hs, as: g.as, period: g.period, clock: g.clock }; }); }],
  college: ['index.json', function (j) { var out = []; Object.keys(j.levels || {}).forEach(function (L) { var l = j.levels[L] || {}; ['today', 'next_games', 'last_games'].forEach(function (k) { (l[k] || []).forEach(function (g) { out.push({ id: g.id, status: g.status, hs: g.hs, as: g.as, period: g.period, clock: g.clock }); }); }); }); return out; }],
  tennis: ['index.json', function (j) { var out = []; Object.keys(j.tours || {}).forEach(function (T) { var t = j.tours[T]; [].concat(t.live || [], t.today || [], t.recent || []).forEach(function (m) { var s = m.sets || [], a = 0, b = 0; s.forEach(function (x) { if (isNum(x[0]) && isNum(x[1])) { if (x[0] > x[1]) a++; else if (x[1] > x[0]) b++; } }); out.push({ id: m.id, status: m.status, hs: s.length ? a : null, as: s.length ? b : null }); }); }); return out; }]
};
function needsLive(sport) {
  return D.games.some(function (g) {
    if (g.sport !== sport) return false;
    if (g.status === 'live') return true;
    var h = (Date.now() - new Date(g.start)) / 36e5;
    return g.status === 'pre' && h > -0.25 && h < 5;
  });
}
function refreshLive() {
  if (document.hidden) return;
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
        if (st !== g.status || x.hs !== g.hs || x.as !== g.as || x.period !== g.period) {
          g.status = st; if (x.hs !== null && x.hs !== undefined) g.hs = x.hs; if (x.as !== null && x.as !== undefined) g.as = x.as;
          g.period = x.period; g.clock = x.clock; changed = true;
        }
      });
      if (changed) { renderTicker(); renderGames(); renderHeroStats(); renderFeature(); }
    }, function () { /* offline or blocked: keep the built snapshot */ });
  });
}
function startLive() { refreshLive(); setInterval(refreshLive, 60000); document.addEventListener('visibilitychange', refreshLive); }
})();
