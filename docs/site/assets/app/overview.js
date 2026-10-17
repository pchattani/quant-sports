/* The Quant Footballer — Overview (#/): every competition at once.
 *
 *   the band       today's numbers (matches, live, competitions in season) and the quick competition links
 *   today          match cards for today (live first), by family, with the model's line and the market where priced
 *   model v market the biggest gaps between the model and the prediction markets on the coming fixtures (dumbbell + list)
 *   title races    every open race's favourite (bar), and the big five leagues' title odds run by run (line)
 *   leaders        goals against xG across competitions; the strongest clubs on the pooled scale; national teams
 *   leagues        the leagues at a glance: leader, favourite, top scorer, how far the season has gone
 *
 * Reads competitions.json (FB.INDEX), hub.json, each priced competition's market_odds.json, the big leagues'
 * history.json, pool.json and nations.json; each card degrades on its own. While a match is live, hub.json is
 * re-read every minute. */
(function (FB) {
'use strict';

var QK = window.QK, QKC = window.QKC;
var esc = FB.esc, isNum = FB.isNum, pct = FB.pct, num = FB.num;

var BIG = ['premier-league', 'la-liga', 'serie-a', 'bundesliga', 'ligue-1'];
var FAM_CHIPS = [['all', 'All'], ['league', 'Leagues'], ['cup', 'Continental'], ['domestic', 'National cups'], ['super', 'Super cups'], ['international', 'National teams']];
var view = { fam: 'all', day: null, race: 'premier-league' };

function allHub(h) {
  var out = [];
  var days = (h || {}).days || {};
  Object.keys(days).forEach(function (k) { (days[k] || []).forEach(function (m) { out.push(m); }); });
  return out;
}
function famOfSlug(slug) { return FB.familyOf(FB.comp(slug)); }
function inSeason(c) { return c.ok && !FB.isLastEdition(c); }

FB.route('overview', function (el) {
  var comps = FB.comps();
  var d = new Date();
  el.innerHTML =
    '<section class="fb-ov-hero">' +
      '<div class="fb-ov-hero-main">' +
        '<div class="qk-kicker">' + esc(FB.DAYS[d.getDay()] + ' ' + d.getDate() + ' ' + FB.MONTHS[d.getMonth()] + ' ' + d.getFullYear()) + ' · ' + comps.filter(inSeason).length + ' competitions in season</div>' +
        '<h1 class="fb-ov-title">World football, priced and measured</h1>' +
        '<p class="fb-ov-sub">Every match with the model\'s line, the title and cup odds from 30,000 simulated seasons, and one page for every club and player across all the competitions they play.</p>' +
        '<div class="fb-ov-quick">' + BIG.concat(['champions-league', 'brasileirao', 'mls', 'liga-argentina', 'libertadores']).filter(function (s) { return FB.comp(s) && FB.comp(s).ok; }).map(function (s) {
          return '<a class="qk-chip" href="' + esc(FB.href.comp(s)) + '" style="--ca:' + FB.kindColor(FB.kindOf(s)) + '">' + esc(FB.compName(s, true)) + '</a>';
        }).join('') + '<a class="qk-chip" href="#/competitions">All ' + comps.filter(function (c) { return c.ok; }).length + ' →</a></div>' +
      '</div>' +
      '<div class="fb-ov-hero-side" id="ov-kpis">' + FB.kpis([FB.kpi('Matches today', '…'), FB.kpi('Live now', '…'), FB.kpi('Model v market', '…'), FB.kpi('Updated', '…', { text: true })], 'fb-ov-kpis') + '</div>' +
    '</section>' +
    '<section class="fb-sec"><div class="qk-section-head"><div><h2>Matches</h2><div class="qk-sub" id="ov-day-sub">Kick-off in your time zone. The bar is the model: home, draw, away.</div></div>' +
      '<div class="fb-head-r"><span id="ov-days"></span><a class="qk-btn" href="#/matches">Every match →</a></div></div>' +
      '<div class="qk-chips scroll" id="ov-fam" role="group" aria-label="Competition family">' + FAM_CHIPS.map(function (f) {
        return '<button class="qk-chip" type="button" data-value="' + f[0] + '" aria-pressed="' + (f[0] === view.fam) + '">' + esc(f[1]) + ' <span class="n" data-n="' + f[0] + '"></span></button>';
      }).join('') + '</div>' +
      '<div id="ov-cards" class="fb-cards fb-mt">' + QK.skeleton('card', 6) + '</div>' +
      '<div id="ov-more" class="fb-cap"></div></section>' +
    '<section class="fb-sec">' + FB.grid(
      FB.card('Model v market', 'The biggest disagreements on the coming fixtures: <b style="color:var(--c-model)">model</b> against the <b style="color:var(--c-market)">prediction-market</b> price (de-vigged), on the outcome where they differ most.',
        FB.chartBox('ov-mvm', 360, 'Model against market') + '<div id="ov-mvm-list"></div>', { span: 7, id: 'ov-mvm-card' }) +
      FB.card('Title races', 'Each open competition\'s favourite and its chance of winning, from the season simulations.', FB.chartBox('ov-races', 360, 'Favourites\' chances by competition'), { span: 5 })
    ) + '</section>' +
    '<section class="fb-sec">' + FB.grid(
      FB.card('The title race, run by run', 'Chance of winning the league after each hourly model run.', '<div class="fb-toolbar" id="ov-race-pick"></div>' + FB.chartBox('ov-race', 320, 'Title odds over time'), { span: 7 }) +
      FB.card('Goals against expected', 'The leading scorers across every competition this season: goals scored and the xG of their shots.', FB.chartBox('ov-goals', 320, 'Goals and xG of the top scorers'), { span: 5 })
    ) + '</section>' +
    '<section class="fb-sec">' + FB.grid(
      FB.card('Leagues at a glance', 'Leader, favourite and top scorer of each league in season.', '<div id="ov-leagues"></div>', { span: 8, flush: true }) +
      '<div class="qk-span-4 fb-ov-stack">' +
        FB.card('Strongest clubs', 'On one scale across leagues (pooled model): expected points per game against an average side.', '<div id="ov-pool"></div>', { foot: '<span></span><a href="#/clubs">All clubs →</a>' }) +
        FB.card('Strongest national teams', 'International model rating.', '<div id="ov-nations"></div>', { foot: '<span></span><a href="#/clubs/nations">All national teams →</a>' }) +
      '</div>'
    ) + '</section>' +
    '<section class="fb-sec">' + FB.card('Between editions', 'Competitions with no edition in progress: the last one, as it finished.', '<div id="ov-last" class="fb-ov-last"></div>') + '</section>';

  QK.chips(el.querySelector('#ov-fam'), function (vals) { view.fam = vals[0] || 'all'; drawCards(el, HUB); });

  var HUB = null;
  var p = FB.load('hub.json').then(function (h) {
    if (!FB.alive(el)) return;
    HUB = h || { days: {} };
    drawCards(el, HUB);
    drawKpis(el, HUB);
    drawLeaders(el, HUB);
    return loadMarkets().then(function (mk) { if (FB.alive(el)) { MARKET = mk; drawCards(el, HUB); drawMvm(el, mk, HUB); drawKpis(el, HUB); } });
  });
  drawRaces(el);
  drawRaceHistory(el);
  drawLeagues(el);
  drawLast(el);
  FB.load('pool.json').then(function (pool) { if (FB.alive(el)) drawPool(el, pool); });
  FB.load('nations.json').then(function (n) { if (FB.alive(el)) drawNations(el, n); });

  /* live: re-read the scoreboard every minute while anything is in play or about to start */
  FB.interval(function () {
    var soon = allHub(HUB).some(function (m) { var t = FB.parseDate(m.date); return m.status === 'live' || (m.status !== 'finished' && t && Math.abs(t - Date.now()) < 15 * 60000); });
    if (!soon) return;
    FB.reload('hub.json').then(function (h) { if (!FB.alive(el) || !h) return; HUB = h; FB.hubLive(h); drawCards(el, HUB); drawKpis(el, HUB); });
  }, 60000);
  return p;
});

/* ── market prices for the coming fixtures, by Sofascore match id */
var MARKET = null;
function loadMarkets() {
  var soon = function (c) { var t = FB.parseDate((c.next || {}).date); return t && t - Date.now() < 8 * 864e5; };
  var list = FB.comps().filter(function (c) { return c.ok && (c.tabs || []).indexOf('market') >= 0 && soon(c); });
  return Promise.all(list.map(function (c) { return FB.compFile(c.slug, 'market_odds'); })).then(function (docs) {
    var byId = {};
    docs.forEach(function (d, i) {
      if (!d || d.ok === false) return;
      ((d.matches || {}).fixtures || []).forEach(function (f) { if (f.market && f.model) byId[String(f.match_id)] = { slug: list[i].slug, f: f }; });
    });
    return byId;
  });
}

/* ── today's matches */
function dayList(h) {
  var by = {};
  allHub(h).forEach(function (m) { var k = FB.localDay(m.date); if (k) (by[k] = by[k] || []).push(m); });
  return by;
}
function drawCards(el, h) {
  var by = dayList(h);
  var keys = Object.keys(by).sort();
  var t = FB.today();
  if (!view.day || keys.indexOf(view.day) < 0) view.day = keys.indexOf(t) >= 0 ? t : (keys.filter(function (k) { return k > t; })[0] || keys[keys.length - 1] || t);
  var days = el.querySelector('#ov-days');
  if (days) {
    var lo = shiftDay(t, -1), hi = shiftDay(t, 2);
    var shown = keys.filter(function (k) { return (k >= lo && k <= hi) || k === view.day; });
    days.innerHTML = shown.length > 1 ? FB.seg('ov-day', shown.map(function (k) { return [k, FB.relDay(k + 'T12:00:00')]; }), view.day, 'Day') : '';
    FB.wireSeg(days, 'ov-day', function (v) { view.day = v; drawCards(el, h); });
  }
  var list = (by[view.day] || []).slice();
  var counts = { all: list.length };
  list.forEach(function (m) { var f = famOfSlug(m.comp); counts[f] = (counts[f] || 0) + 1; });
  Array.prototype.forEach.call(el.querySelectorAll('#ov-fam [data-n]'), function (n) { n.textContent = counts[n.getAttribute('data-n')] || 0; });
  if (view.fam !== 'all') list = list.filter(function (m) { return famOfSlug(m.comp) === view.fam; });
  var order = { live: 0, scheduled: 1, finished: 2, postponed: 3, cancelled: 4 };
  var rank = {};
  FB.comps().forEach(function (c, i) { rank[c.slug] = i; });
  list.sort(function (a, b) { return (order[a.status] - order[b.status]) || String(a.date).localeCompare(String(b.date)) || (rank[a.comp] - rank[b.comp]); });
  var box = el.querySelector('#ov-cards');
  if (!box) return;
  if (!list.length) { box.innerHTML = '<div style="grid-column:1/-1">' + FB.empty('No matches', view.fam === 'all' ? 'Nothing scheduled across the competitions followed on this day.' : 'Nothing from this family on this day.') + '</div>'; FB.set('ov-more', ''); return; }
  var LIM = 12;
  box.innerHTML = list.slice(0, LIM).map(function (m) {
    var mk = MARKET && MARKET[String(m.id)];
    return FB.matchCard(m, m.comp, mk ? { market_home: mk.f.market.home } : null);
  }).join('');
  var more = el.querySelector('#ov-more');
  if (more) more.innerHTML = list.length > LIM ? list.length - LIM + ' more on this day: <a href="' + esc(FB.href.matches({ d: view.day, f: view.fam === 'all' ? null : view.fam })) + '">see every match →</a>' : '';
}
function shiftDay(k, n) { var d = FB.parseDate(k + 'T12:00:00'); d.setDate(d.getDate() + n); return FB.localDay(d); }

function drawKpis(el, h) {
  var all = allHub(h);
  var t = FB.today();
  var todays = all.filter(function (m) { return FB.localDay(m.date) === t; });
  var live = all.filter(function (m) { return m.status === 'live'; });
  var gaps = MARKET ? Object.keys(MARKET).length : null;
  var box = el.querySelector('#ov-kpis');
  if (!box) return;
  box.innerHTML = FB.kpis([
    FB.kpi('Matches today', String(todays.length), { sub: todays.filter(function (m) { return m.status === 'finished'; }).length + ' finished · ' + todays.filter(function (m) { return m.status === 'scheduled'; }).length + ' to come' }),
    FB.kpi('Live now', '<span class="' + (live.length ? 'fb-ov-live' : '') + '">' + live.length + '</span>', { sub: live.length ? live.slice(0, 2).map(function (m) { return esc(m.home) + ' ' + m.hs + '–' + m.as + ' ' + esc(m.away); }).join(' · ') : 'Nothing in play' }),
    FB.kpi('Priced fixtures', gaps === null ? '…' : String(gaps), { sub: 'model v prediction markets', tip: 'Coming fixtures with a de-vigged prediction-market price (Kalshi, Polymarket) beside the model.' }),
    FB.kpi('Updated', esc(FB.fmtTime(h.updated_at) || '—'), { text: true, sub: esc(FB.fmtDate(h.updated_at)) + ' · hourly' })
  ], 'fb-ov-kpis');
}

/* ── model v market */
function drawMvm(el, mk, h) {
  var hubById = {};
  allHub(h).forEach(function (m) { hubById[String(m.id)] = m; });
  var rowsAll = Object.keys(mk).map(function (id) {
    var x = mk[id], f = x.f;
    var t = FB.parseDate(f.commence);
    if (!t || t < Date.now() - 2 * 3600e3 || t - Date.now() > 8 * 864e5) return null;
    var k = ['home', 'draw', 'away'].sort(function (a, b) { return Math.abs(f.model[b] - f.market[b]) - Math.abs(f.model[a] - f.market[a]); })[0];
    var lab = k === 'draw' ? 'Draw' : (k === 'home' ? f.home : f.away) + ' win';
    return { id: id, slug: x.slug, f: f, k: k, a: f.model[k], b: f.market[k], gap: f.model[k] - f.market[k], label: lab + ' · ' + f.home + ' v ' + f.away, hub: hubById[id] };
  }).filter(Boolean).sort(function (a, b) { return Math.abs(b.gap) - Math.abs(a.gap); });
  /* prefer fixtures priced by both markets (thin single-venue prices make the biggest, least meaningful gaps) */
  var deep = rowsAll.filter(function (r) { return (r.f.books || 0) >= 2; });
  var top = (deep.length >= 6 ? deep : rowsAll).slice(0, 10);
  if (!top.length) {
    FB.set('ov-mvm', ''); var c = el.querySelector('#ov-mvm'); if (c) c.style.display = 'none';
    FB.set('ov-mvm-list', FB.empty('No market prices', 'No coming fixture has a prediction-market price right now.'));
    return;
  }
  QKC.dumbbell(el.querySelector('#ov-mvm'), { rows: top.map(function (r) { return { label: r.label, a: r.a, b: r.b, href: FB.href.match(r.slug, r.id), sub: FB.compName(r.slug) + ' · ' + FB.fmtDate(r.f.commence, { time: true }) }; }), labelWidth: 210 });
  FB.set('ov-mvm-list', '<p class="fb-cap">' + rowsAll.length + ' priced fixtures in the next week. A gap is a difference of opinion, not a bet: the model is wrong often. <a href="#/model/methodology">How the model is checked →</a></p>');
}

/* ── title races */
function drawRaces(el) {
  var rows = FB.comps().filter(function (c) { return inSeason(c) && c.favourite && isNum(c.p_favourite) && !c.complete && c.p_favourite < 0.995; })
    .sort(function (a, b) { return FB.KIND_ORDER[FB.kindOf(a.slug)] - FB.KIND_ORDER[FB.kindOf(b.slug)] || b.p_favourite - a.p_favourite; }).slice(0, 14);
  var box = el.querySelector('#ov-races');
  if (!rows.length) { box.style.height = 'auto'; box.innerHTML = FB.empty('No open races', 'Every competition followed is decided or between editions.'); return; }
  rows.sort(function (a, b) { return b.p_favourite - a.p_favourite; });
  QKC.bar(box, {
    horizontal: true, labels: true, labelWidth: 150, fmt: function (v) { return pct(v); }, max: 1,
    cats: rows.map(function (c) { return c.favourite + ' · ' + (c.short_name || c.name); }),
    series: [{ name: 'Chance to win', data: rows.map(function (c) { return c.p_favourite; }) }],
    colors: rows.map(function (c) { return FB.kindColorHex(FB.kindOf(c.slug)); }),
    hrefs: rows.map(function (c) { return FB.href.comp(c.slug, 'odds'); }), label: 'Favourite\'s chance in each open competition'
  });
}
function drawRaceHistory(el) {
  var avail = BIG.filter(function (s) { var c = FB.comp(s); return c && inSeason(c) && FB.hasFile(s, 'history'); });
  var pick = el.querySelector('#ov-race-pick');
  if (!avail.length) { FB.set('ov-race', FB.empty('No history yet', 'Title odds are recorded after each model run.')); return; }
  if (avail.indexOf(view.race) < 0) view.race = avail[0];
  pick.innerHTML = FB.seg('ov-race-seg', avail.map(function (s) { return [s, FB.compName(s, true)]; }), view.race, 'League');
  FB.wireSeg(pick, 'ov-race-seg', function (v) { view.race = v; draw(); });
  function draw() {
    var slug = view.race;
    FB.compFiles(slug, ['history', 'teams']).then(function (d) {
      var box = el.querySelector('#ov-race');
      if (!box || !FB.alive(el)) return;
      var snaps = ((d.history || {}).snapshots || []).filter(function (s) { return s.title; });
      if (snaps.length < 2) { box.innerHTML = FB.empty('Not enough runs yet', 'The line appears after two model runs.'); return; }
      var last = snaps[snaps.length - 1].title;
      var teams = Object.keys(last).sort(function (a, b) { return last[b] - last[a]; }).slice(0, 5).filter(function (t) { return last[t] > 0.005; });
      if (!teams.length) teams = Object.keys(last).slice(0, 3);
      var x = snaps.map(function (s) { return s.ts; });
      QKC.line(box, {
        x: x, xLabel: function (v) { return FB.fmtStamp(v); }, xFmt: function (v) { var dd = FB.parseDate(v); return dd ? dd.getDate() + ' ' + FB.MONTHS[dd.getMonth()] : ''; },
        yFmt: function (v) { return pct(v); }, yMin: 0, label: 'Title odds by model run, ' + FB.compName(slug),
        series: teams.map(function (t) { return { name: t, data: snaps.map(function (s) { return isNum(s.title[t]) ? s.title[t] : 0; }) }; })
      });
    });
  }
  draw();
}

/* ── leaders: goals v xG */
function drawLeaders(el, h) {
  var L = ((h || {}).leaders || {}).goals || [];
  var box = el.querySelector('#ov-goals');
  if (!box) return;
  var top = L.slice(0, 10);
  if (!top.length) { box.style.height = 'auto'; box.innerHTML = FB.empty('No player data yet'); return; }
  QKC.bar(box, {
    horizontal: true, legend: true, labelWidth: 130, fmt: function (v) { return num(v, 0); },
    cats: top.map(function (p) { return p.name + ' (' + (p.comp_name || FB.compName(p.comp, true)) + ')'; }),
    series: [{ name: 'Goals', data: top.map(function (p) { return p.value; }) }, { name: 'xG', data: top.map(function (p) { return isNum(p.xg) ? Math.round(p.xg * 10) / 10 : null; }) }],
    hrefs: top.map(function (p) { return FB.href.player(p.id); }), label: 'Top scorers: goals and xG'
  });
}

/* ── leagues at a glance */
function drawLeagues(el) {
  var rows = FB.comps().filter(function (c) { return c.ok && FB.familyOf(c) === 'league'; }).map(function (c) {
    return { slug: c.slug, name: c.name, short: c.short_name || c.name, c: c, prog: c.games_total ? (c.games_played || 0) / c.games_total : null,
      leader: (c.leader || {}).team, pts: (c.leader || {}).pts, fav: c.favourite, p: c.p_favourite, scorer: (c.top_scorer || {}).name, goals: (c.top_scorer || {}).goals };
  });
  FB.table(el.querySelector('#ov-leagues'), [
    { key: 'name', label: 'League', sticky: true, fmt: function (v, r) { return FB.compLink(r.slug); } },
    { key: 'prog', label: 'Season', num: true, fmt: function (v, r) { return isNum(v) ? '<span class="fb-rowbar" title="' + (r.c.games_played || 0) + ' of ' + r.c.games_total + ' played"><i style="width:' + (v * 100).toFixed(0) + '%"></i></span> ' + Math.round(v * 100) + '%' : '—'; } },
    { key: 'leader', label: 'Leader', fmt: function (v, r) { return v ? esc(v) + ' <span class="qk-muted fb-num">' + r.pts + '</span>' : '—'; } },
    { key: 'p', label: 'Favourite', num: true, fmt: function (v, r) { return r.fav ? esc(r.fav) + ' <b class="fb-num">' + pct(v) + '</b>' : '—'; } },
    { key: 'goals', label: 'Top scorer', num: true, fmt: function (v, r) { return r.scorer ? esc(r.scorer) + ' <b class="fb-num">' + v + '</b>' : '—'; } }
  ], rows, { caption: 'Leagues at a glance' });
}

function drawPool(el, pool) {
  var box = el.querySelector('#ov-pool');
  var clubs = ((pool || {}).clubs || []).slice().sort(function (a, b) { return b.strength - a.strength; }).slice(0, 8);
  if (!clubs.length) { box.innerHTML = FB.muted('The pooled fit is not available.'); return; }
  var max = clubs[0].strength;
  box.innerHTML = '<ol class="fb-ov-rank">' + clubs.map(function (c, i) {
    return '<li><span class="r">' + (i + 1) + '</span>' + FB.clubLink(c.team_id, c.team) + '<span class="qk-muted fb-ov-c">' + esc(c.comp_name || '') + '</span><span class="fb-rowbar"><i style="width:' + (c.strength / max * 100).toFixed(0) + '%"></i></span><b class="fb-num">' + num(c.strength, 2) + '</b></li>';
  }).join('') + '</ol>';
}
function drawNations(el, n) {
  var box = el.querySelector('#ov-nations');
  var t = ((n || {}).teams || []).slice(0, 6);
  if (!t.length) { box.innerHTML = FB.muted('No international fit yet.'); return; }
  FB.clubsIndex().then(function (ci) {
    var byName = {};
    ci.list.forEach(function (r) { if (r.national) byName[r.name] = r.id; });
    box.innerHTML = '<ol class="fb-ov-rank">' + t.map(function (x) {
      return '<li><span class="r">' + x.rank + '</span>' + FB.clubLink(byName[x.team], x.team) + '<span class="qk-muted fb-ov-c">' + esc(x.confederation || '') + '</span><b class="fb-num">' + num(x.strength, 2) + '</b></li>';
    }).join('') + '</ol>';
  });
}
function drawLast(el) {
  var last = FB.comps().filter(function (c) { return c.ok && FB.isLastEdition(c); });
  var box = el.querySelector('#ov-last');
  if (!last.length) { box.innerHTML = FB.muted('Every competition followed has an edition in progress.'); return; }
  box.innerHTML = last.map(function (c) {
    var won = c.winner && c.winner.team ? c.winner : null;
    return '<a class="fb-ov-lastc" href="' + esc(FB.href.comp(c.slug)) + '"><span class="qk-kicker">' + esc(FB.currentSeason(c).season) + '</span><b>' + esc(c.name) + '</b>' +
      '<span class="fb-ov-won">' + (won ? FB.crest(won.tid, won.team, 'sm') + esc(won.team) : '<span class="qk-muted">last edition</span>') + '</span></a>';
  }).join('');
}

})(window.FB);
