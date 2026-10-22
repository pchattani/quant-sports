/* The Quant Footballer — Overview (#/): every competition at once, on Design System 2.0 (the Rink overview is the
 * reference page).
 *
 *   head + ticker  the page head (v2 large section head) and a scoreboard ticker of today's live and coming matches
 *   stat tiles     matches today, live now, the biggest league's title favourite (our chance), the top-rated club on
 *                  the pooled scale, the top scorer across competitions
 *   scoreboard     v2 game cards for one day (our home / draw / away chance before kick-off, the score and xG after),
 *                  by family; the form dots are the club's league form, shown only on its own league's matches
 *   title races    every open race's favourite and our chance (538-style chance bars), and the big five leagues'
 *                  title chances run by run (forecast lines with end labels)
 *   leaders        goals against xG across competitions; the strongest clubs on the pooled scale; national teams
 *   leagues        the leagues at a glance: progress, leader, our favourite, top scorer
 *
 * Reads competitions.json (FB.INDEX), hub.json, the big leagues' history.json, pool.json and nations.json; each
 * card degrades on its own. While a match is live, hub.json is re-read every minute. A match a cached snapshot
 * still marks live 12 hours after kick-off is not counted as live (FB.staleLive). */
(function (FB) {
'use strict';

var QK = window.QK, QKC = window.QKC;
var esc = FB.esc, isNum = FB.isNum, pct = FB.pct, num = FB.num;

var BIG = ['premier-league', 'la-liga', 'serie-a', 'bundesliga', 'ligue-1'];
var FAM_CHIPS = [['all', 'All'], ['league', 'Leagues'], ['cup', 'Continental'], ['domestic', 'National cups'], ['super', 'Super cups'], ['international', 'National teams']];
var view = { fam: 'all', day: null, race: 'premier-league' };
var FORM = null;   // team id -> { comp, form } from pool.json (league form, oldest first)

function allHub(h) {
  var out = [];
  var days = (h || {}).days || {};
  Object.keys(days).forEach(function (k) { (days[k] || []).forEach(function (m) { out.push(m); }); });
  return out;
}
function isLive(m) { return (m.status === 'live' || m.status === 'inprogress') && !FB.staleLive(m); }
function famOfSlug(slug) { return FB.familyOf(FB.comp(slug)); }
function inSeason(c) { return c.ok && !FB.isLastEdition(c); }

FB.route('overview', function (el) {
  var comps = FB.comps();
  var d = new Date();
  var nIn = comps.filter(inSeason).length;
  el.innerHTML =
    FB.pageHead('Football · ' + esc(FB.DAYS[d.getDay()] + ' ' + d.getDate() + ' ' + FB.MONTHS[d.getMonth()] + ' ' + d.getFullYear()) + ' · ' + nIn + ' competitions in season',
      'World football, by the numbers.',
      'Our win chance for every match, title, qualification and cup chances from 30,000 simulated seasons, expected goals, and one page for every club and player across all the competitions they play.',
      '<a class="qk-btn" href="#/matches">All matches</a><a class="qk-btn" href="#/competitions">Competitions</a>') +
    '<div class="fb-ov-quick">' + BIG.concat(['champions-league', 'brasileirao', 'mls', 'liga-argentina', 'libertadores']).filter(function (s) { return FB.comp(s) && FB.comp(s).ok; }).map(function (s) {
      return '<a class="qk-chip" href="' + esc(FB.href.comp(s)) + '">' + esc(FB.compName(s, true)) + '</a>';
    }).join('') + '<a class="qk-chip" href="#/competitions">All ' + comps.filter(function (c) { return c.ok; }).length + ' →</a></div>' +
    '<div class="qk-ticker fb-ov-ticker" id="ov-ticker" aria-label="Scoreboard ticker" hidden></div>' +
    '<div id="ov-kpis" class="fb-ov-kpis">' + QK.skeleton('lines', 2) + '</div>' +
    '<section class="fb-sec">' + FB.secHead('<span id="ov-gh">Today</span>', '<span id="ov-day-sub">Our home / draw / away chance on every card, the favourite in violet; the score and expected goals after the whistle. Kick-off in your time zone.</span>',
        '<span id="ov-days"></span><a class="qk-btn" href="#/matches">Every match →</a>', 'Scoreboard') +
      '<div class="qk-chips scroll" id="ov-fam" role="group" aria-label="Competition family">' + FAM_CHIPS.map(function (f) {
        return '<button class="qk-chip" type="button" data-value="' + f[0] + '" aria-pressed="' + (f[0] === view.fam) + '">' + esc(f[1]) + ' <span class="n" data-n="' + f[0] + '"></span></button>';
      }).join('') + '</div>' +
      '<div id="ov-cards" class="fb-cards fb-mt">' + QK.skeleton('card', 6) + '</div>' +
      '<div id="ov-more" class="fb-cap"></div></section>' +
    '<section class="fb-sec">' + FB.secHead('Who wins it', 'Our chances from the season simulations: each open competition\'s favourite, and how the big five title races have moved run by run.', '', 'Season simulations') +
      FB.grid(
        FB.card('Favourites', 'Our chance that each open competition\'s favourite wins it.', '<div id="ov-races"></div>', { span: 5, foot: '<span>Up to fourteen open races</span><a href="#/competitions">Every competition →</a>' }) +
        FB.card('The title race, run by run', 'Our title chance after each hourly model run, for the top five in the league.', '<div class="fb-toolbar" id="ov-race-pick"></div>' + FB.chartBox('ov-race', 340, 'Title chances over time'), { span: 7 })
      ) + '</section>' +
    '<section class="fb-sec">' + FB.secHead('Leaders', 'Across every competition this season, and the strongest sides on one scale.', '<a class="qk-btn" href="#/players/leaders">Players →</a>', 'Leaderboards') +
      FB.grid(
        FB.card('Goals against expected', 'The leading scorers across every competition: goals scored and the xG of their shots.', FB.chartBox('ov-goals', 360, 'Goals and xG of the top scorers'), { span: 6 }) +
        '<div class="qk-span-3">' + FB.card('Strongest clubs', 'Pooled model: expected points a game against an average side.', '<div id="ov-pool"></div>', { flush: true, foot: '<span></span><a href="#/clubs">All clubs →</a>' }) + '</div>' +
        '<div class="qk-span-3">' + FB.card('Strongest national teams', 'Our international rating.', '<div id="ov-nations"></div>', { flush: true, foot: '<span></span><a href="#/clubs/nations">All national teams →</a>' }) + '</div>'
      ) + '</section>' +
    '<section class="fb-sec">' + FB.secHead('Leagues at a glance', 'How far each league has gone, who leads, our title favourite and the top scorer.', '<a class="qk-btn" href="#/competitions">Competitions →</a>', 'Leagues') +
      FB.card('', '', '<div id="ov-leagues"></div>', { flush: true }) + '</section>' +
    '<section class="fb-sec">' + FB.card('Between editions', 'Competitions with no edition in progress: the last one, as it finished.', '<div id="ov-last" class="fb-ov-last"></div>') + '</section>';

  QK.chips(el.querySelector('#ov-fam'), function (vals) { view.fam = vals[0] || 'all'; drawCards(el, HUB); });

  var HUB = null, POOL = null;
  var hubP = FB.load('hub.json');
  var poolP = FB.load('pool.json');
  var p = Promise.all([hubP, poolP]).then(function (arr) {
    if (!FB.alive(el)) return;
    HUB = arr[0] || { days: {} };
    POOL = arr[1];
    FORM = formMap(POOL);
    drawCards(el, HUB);
    drawTicker(el, HUB);
    drawKpis(el, HUB, POOL);
    drawLeaders(el, HUB);
    drawPool(el, POOL);
  });
  drawRaces(el);
  drawRaceHistory(el);
  drawLeagues(el);
  drawLast(el);
  FB.load('nations.json').then(function (n) { if (FB.alive(el)) drawNations(el, n); });

  /* live: re-read the scoreboard every minute while anything is in play or about to start */
  FB.interval(function () {
    var soon = allHub(HUB).some(function (m) { var t = FB.parseDate(m.date); return isLive(m) || (m.status !== 'finished' && t && Math.abs(t - Date.now()) < 15 * 60000); });
    if (!soon) return;
    FB.reload('hub.json').then(function (h) { if (!FB.alive(el) || !h) return; HUB = h; FB.hubLive(h); drawCards(el, HUB); drawTicker(el, HUB); drawKpis(el, HUB, POOL); });
  }, 60000);
  return p;
});

/* ── league form for the cards (pool.json form_results, oldest first: checked against the fixtures) */
function formMap(pool) {
  var out = {};
  ((pool || {}).clubs || []).forEach(function (c) { if (c.team_id && (c.form_results || []).length) out[String(c.team_id)] = { comp: c.comp, form: c.form_results.join('') }; });
  return out;
}
function extraFor(m) {
  if (!FORM) return null;
  var h = FB.tidFromCrest(m.crests && m.crests[0]), a = FB.tidFromCrest(m.crests && m.crests[1]);
  var fh = h && FORM[String(h)], fa = a && FORM[String(a)];
  return {
    home_form: fh && fh.comp === m.comp ? fh.form : null,
    away_form: fa && fa.comp === m.comp ? fa.form : null
  };
}

/* ── one day's matches */
function dayList(h) {
  var by = {};
  allHub(h).forEach(function (m) { var k = FB.localDay(m.date); if (k) (by[k] = by[k] || []).push(m); });
  return by;
}
function statusRank(m) { return isLive(m) ? 0 : m.status === 'scheduled' ? 1 : m.status === 'finished' || FB.staleLive(m) ? 2 : m.status === 'postponed' ? 3 : 4; }
function drawCards(el, h) {
  var by = dayList(h);
  var keys = Object.keys(by).sort();
  var t = FB.today();
  if (!view.day || keys.indexOf(view.day) < 0) view.day = keys.indexOf(t) >= 0 ? t : (keys.filter(function (k) { return k > t; })[0] || keys[keys.length - 1] || t);
  var gh = el.querySelector('#ov-gh');
  if (gh) gh.textContent = view.day === t ? 'Today' : FB.relDay(view.day + 'T12:00:00');
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
  var rank = {};
  FB.comps().forEach(function (c, i) { rank[c.slug] = i; });
  list.sort(function (a, b) { return (statusRank(a) - statusRank(b)) || String(a.date).localeCompare(String(b.date)) || (rank[a.comp] - rank[b.comp]); });
  var box = el.querySelector('#ov-cards');
  if (!box) return;
  if (!list.length) { box.innerHTML = '<div style="grid-column:1/-1">' + FB.empty('No matches', view.fam === 'all' ? 'Nothing scheduled across the competitions followed on this day.' : 'Nothing from this family on this day.') + '</div>'; FB.set('ov-more', ''); return; }
  var LIM = 12;
  box.innerHTML = list.slice(0, LIM).map(function (m) { return FB.matchCard(m, m.comp, extraFor(m)); }).join('');
  var more = el.querySelector('#ov-more');
  if (more) more.innerHTML = list.length > LIM ? list.length - LIM + ' more on this day: <a href="' + esc(FB.href.matches({ d: view.day, f: view.fam === 'all' ? null : view.fam })) + '">see every match →</a>' : '';
}
function shiftDay(k, n) { var d = FB.parseDate(k + 'T12:00:00'); d.setDate(d.getDate() + n); return FB.localDay(d); }

/* ── the ticker: live first, then today's coming matches, then today's results (kit QK.ticker by league) */
function drawTicker(el, h) {
  var box = el.querySelector('#ov-ticker');
  if (!box) return;
  var t = FB.today();
  var list = allHub(h).filter(function (m) { return isLive(m) || FB.localDay(m.date) === t; });
  if (!list.length) { box.hidden = true; return; }
  var rank = {};
  FB.comps().forEach(function (c, i) { rank[c.slug] = i; });
  list.sort(function (a, b) { return (rank[a.comp] === undefined ? 999 : rank[a.comp]) - (rank[b.comp] === undefined ? 999 : rank[b.comp]) || String(a.date).localeCompare(String(b.date)); });
  var games = list.slice(0, 40).map(function (m) { return FB.toGame(m, m.comp); });
  box.innerHTML = QK.ticker(games, { group: 'league', max: 40 });
  box.hidden = false;
}

/* ── stat tiles: ours first, no market */
function drawKpis(el, h, pool) {
  var all = allHub(h);
  var t = FB.today();
  var todays = all.filter(function (m) { return FB.localDay(m.date) === t; });
  var live = all.filter(isLive);
  var box = el.querySelector('#ov-kpis');
  if (!box) return;
  var tiles = [];
  tiles.push(FB.kpi(live.length ? 'Live now' : 'Matches today', String(live.length || todays.length), {
    sub: live.length ? esc(live.slice(0, 2).map(function (m) { return m.home + ' ' + m.hs + '–' + m.as + ' ' + m.away; }).join(' · ')) + (todays.length ? ' · ' + todays.length + ' today' : '')
      : todays.filter(function (m) { return m.status === 'finished'; }).length + ' finished · ' + todays.filter(function (m) { return m.status === 'scheduled'; }).length + ' to come',
    cls: live.length ? 'fb-ov-livetile' : '' }));
  var lead = BIG.map(FB.comp).filter(function (c) { return c && inSeason(c) && c.favourite && isNum(c.p_favourite); })[0];
  if (lead) tiles.push(FB.kpi((lead.short_name || lead.name) + ' favourite', esc(lead.favourite) + ' ' + pct(lead.p_favourite), { signal: true, text: true, href: FB.href.comp(lead.slug, 'odds'),
    sub: 'our title chance · from 30,000 simulated seasons', tip: 'Our chance of winning the league in the season simulation' }));
  var clubs = ((pool || {}).clubs || []).filter(function (c) { return (c.in_league || (c.played || 0) > 0) && isNum(c.strength); }).sort(function (a, b) { return b.strength - a.strength; });
  if (clubs.length) tiles.push(FB.kpi('Top-rated club', esc(clubs[0].team) + ' ' + num(clubs[0].strength, 2), { text: true, href: clubs[0].team_id ? FB.href.club(clubs[0].team_id) : null,
    sub: 'expected points a game against an average side', tip: 'Our pooled rating across leagues: the points a game this club would expect against an average side' }));
  var g = (((h || {}).leaders || {}).goals || [])[0];
  if (g) tiles.push(FB.kpi('Top scorer', esc(g.name) + ' ' + g.value, { text: true, href: FB.href.player(g.id),
    sub: esc(g.comp_name || FB.compName(g.comp, true)) + (isNum(g.xg) ? ' · ' + num(g.xg, 1) + ' xG' : ''), tip: 'Goals across every competition this season' }));
  tiles.push(FB.kpi('Updated', esc(FB.fmtTime(h.updated_at) || '—'), { text: true, sub: esc(FB.fmtDate(h.updated_at)) + ' · hourly' }));
  box.innerHTML = FB.kpis(tiles);
}

/* ── title races: our chance only */
function drawRaces(el) {
  var rows = FB.comps().filter(function (c) { return inSeason(c) && c.favourite && isNum(c.p_favourite) && !c.complete && c.p_favourite < 0.995; })
    .sort(function (a, b) { return b.p_favourite - a.p_favourite; }).slice(0, 14);
  var box = el.querySelector('#ov-races');
  if (!rows.length) { box.innerHTML = FB.empty('No open races', 'Every competition followed is decided or between editions.'); return; }
  box.innerHTML = FB.chances(rows.map(function (c) {
    return { label: c.favourite, sub: c.short_name || c.name, p: c.p_favourite, href: FB.href.comp(c.slug, 'odds'), mark: { name: c.favourite } };
  }), { max: 1, oursName: 'Our chance the favourite wins it' });
}
function drawRaceHistory(el) {
  var avail = BIG.filter(function (s) { var c = FB.comp(s); return c && inSeason(c) && FB.hasFile(s, 'history'); });
  var pick = el.querySelector('#ov-race-pick');
  if (!avail.length) { FB.set('ov-race', FB.empty('No history yet', 'Title chances are recorded after each model run.')); return; }
  if (avail.indexOf(view.race) < 0) view.race = avail[0];
  pick.innerHTML = FB.seg('ov-race-seg', avail.map(function (s) { return [s, FB.compName(s, true)]; }), view.race, 'League');
  FB.wireSeg(pick, 'ov-race-seg', function (v) { view.race = v; draw(); });
  function draw() {
    var slug = view.race;
    FB.compFiles(slug, ['history']).then(function (d) {
      var box = el.querySelector('#ov-race');
      if (!box || !FB.alive(el)) return;
      var snaps = ((d.history || {}).snapshots || []).filter(function (s) { return s.title && FB.parseDate(s.ts); });
      if (snaps.length < 2) { box.style.height = 'auto'; box.innerHTML = FB.empty('Not enough runs yet', 'The line appears after two model runs.'); return; }
      box.style.height = '';
      var last = snaps[snaps.length - 1].title;
      var teams = Object.keys(last).sort(function (a, b) { return last[b] - last[a]; }).slice(0, 5).filter(function (t) { return last[t] > 0.005; });
      if (!teams.length) teams = Object.keys(last).slice(0, 3);
      QKC.forecast(box, {
        xType: 'time', x: snaps.map(function (s) { return s.ts; }),
        xFmt: function (v) { var dd = new Date(v); return isNaN(dd.getTime()) ? '' : dd.getDate() + ' ' + FB.MONTHS[dd.getMonth()]; },
        xLabel: function (v) { return 'Model run · ' + FB.fmtStamp(new Date(v)); },
        xName: 'Model run (date)', yName: 'Our title chance', label: 'Our title chances by model run, ' + FB.compName(slug),
        series: teams.map(function (t, i) { return { name: t, label: shortName(t, teams), data: snaps.map(function (s) { return isNum(s.title[t]) ? s.title[t] : 0; }), ours: false, color: QK.cssVar('--c-' + (i + 1)) }; })
      });
    });
  }
  draw();
}

/* A line's end label: the club's name, or one word of it when long (the first, or the last when two clubs share the first). */
function shortName(t, all) {
  if (t.length <= 12) return t;
  var w = t.split(' '), first = w[0];
  var shared = all.filter(function (x) { return x !== t && x.split(' ')[0] === first; }).length > 0;
  return shared ? w[w.length - 1] : first;
}

/* ── leaders: goals v xG */
function drawLeaders(el, h) {
  var L = ((h || {}).leaders || {}).goals || [];
  var box = el.querySelector('#ov-goals');
  if (!box) return;
  var top = L.slice(0, 10);
  if (!top.length) { box.style.height = 'auto'; box.innerHTML = FB.empty('No player data yet'); return; }
  QKC.bar(box, {
    horizontal: true, legend: true, labelWidth: 150, fmt: function (v) { return num(v, 0); }, valName: 'Goals and xG this season', catName: 'Player',
    cats: top.map(function (p) { return p.name + ' (' + (p.comp_name || FB.compName(p.comp, true)) + ')'; }),
    series: [{ name: 'Goals', data: top.map(function (p) { return p.value; }), color: QK.cssVar('--c-1') }, { name: 'xG', data: top.map(function (p) { return isNum(p.xg) ? Math.round(p.xg * 10) / 10 : null; }), color: QK.cssVar('--c-3') }],
    hrefs: top.map(function (p) { return FB.href.player(p.id); }), label: 'Top scorers: goals and xG'
  });
}

/* ── leagues at a glance (leaderboard) */
function drawLeagues(el) {
  var rows = FB.comps().filter(function (c) { return c.ok && FB.familyOf(c) === 'league'; }).map(function (c) {
    return { slug: c.slug, name: c.name, country: c.country || '', c: c, prog: c.games_total ? (c.games_played || 0) / c.games_total : null,
      leader: (c.leader || {}).team || '', pts: (c.leader || {}).pts, fav: c.favourite, p: isNum(c.p_favourite) ? c.p_favourite : null,
      scorer: (c.top_scorer || {}).name, sid: (c.top_scorer || {}).id, goals: (c.top_scorer || {}).goals };
  });
  QK.leaderboard(el.querySelector('#ov-leagues'), {
    dense: true, caption: 'Leagues at a glance',
    columns: [
      { key: 'name', label: 'League', type: 'entity', sub: 'country', href: function (r) { return FB.href.comp(r.slug); } },
      { key: 'prog', label: 'Season played', type: 'bar', max: 1, fmt: function (v, r) { return isNum(v) ? Math.round(v * 100) + '%' : '—'; } },
      { key: 'leader', label: 'Leader', fmt: function (v, r) { return v ? esc(v) + ' <span class="qk-muted fb-num">' + r.pts + ' pts</span>' : '—'; } },
      { key: 'p', label: 'Our favourite', num: true, fmt: function (v, r) { return r.fav && isNum(v) ? esc(r.fav) + ' <b class="fb-num fb-ov-sig">' + pct(v) + '</b>' : '—'; } },
      { key: 'goals', label: 'Top scorer', num: true, fmt: function (v, r) { return r.scorer ? (r.sid ? FB.playerLink(r.sid, r.scorer) : esc(r.scorer)) + ' <b class="fb-num">' + v + '</b>' : '—'; } }
    ], rows: rows
  });
}

function leadList(items) {
  return '<ul class="fb-ov-lead">' + items.map(function (x, i) {
    return '<li><span class="n">' + (x.rank || i + 1) + '</span><span class="who">' + x.who + (x.sub ? '<span class="s">' + esc(x.sub) + '</span>' : '') + '</span><span class="v">' + esc(x.v) + '</span></li>';
  }).join('') + '</ul>';
}
function drawPool(el, pool) {
  var box = el.querySelector('#ov-pool');
  if (!box) return;
  /* clubs with no rated matches yet (cup entrants seen only in a draw) carry the prior, not a measured strength */
  var clubs = ((pool || {}).clubs || []).filter(function (c) { return (c.in_league || (c.played || 0) > 0) && isNum(c.strength); }).sort(function (a, b) { return b.strength - a.strength; }).slice(0, 8);
  if (!clubs.length) { box.innerHTML = FB.muted('The pooled fit is not available.'); return; }
  box.innerHTML = leadList(clubs.map(function (c) { return { who: FB.clubLink(c.team_id, c.team), sub: c.comp_name || '', v: num(c.strength, 2) }; }));
}
function drawNations(el, n) {
  var box = el.querySelector('#ov-nations');
  var t = ((n || {}).teams || []).slice(0, 8);
  if (!t.length) { box.innerHTML = FB.muted('No international fit yet.'); return; }
  FB.clubsIndex().then(function (ci) {
    if (!FB.alive(box)) return;
    var byName = {};
    ci.list.forEach(function (r) { if (r.national) byName[r.name] = r.id; });
    box.innerHTML = leadList(t.map(function (x) { return { rank: x.rank, who: FB.clubLink(byName[x.team], x.team), sub: x.confederation || '', v: num(x.strength, 2) }; }));
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
