/* The Quant Campus — Overview (#/<L>): the level at a glance, charts first.
 *   headline numbers (title favourite, best team, AP No. 1 or the champion, next kick-off / tip-off, biggest gap v market);
 *   live, today's and upcoming games (model v market on every card), recent results;
 *   who wins it all (model v market), power ratings with their uncertainty, AP poll v our ranking,
 *   the CFP picture (cfb) or bracketology / the bracket (basketball).
 * Reads index.json, <L>/<S>/season.json, <L>/<S>/cfp.json | bracket.json, <L>/markets.json, <L>/history.json,
 * <L>/<S>/schedule.json (past seasons). */
(function (CC) {
'use strict';
var U = CC.ui, esc = CC.esc, isNum = CC.isNum;

function dataTable(cols, rows, label) {
  return '<details class="cc-data"><summary>' + esc(label || 'Show the numbers as a table') + '</summary>' + U.table(cols, rows, { maxHeight: 360 }) + '</details>';
}

function kpis(L, S, d) {
  var out = [], isCur = CC.isCur(L, S), info = CC.info(L);
  var sim = d.sim, tit = Object.keys(sim).filter(function (t) { return isNum(sim[t].p_title); }).sort(function (a, b) { return sim[b].p_title - sim[a].p_title; });
  if (isCur && tit.length) {
    var fav = tit[0], mk = (info.title_odds || []).filter(function (r) { return String(r.team) === String(fav); })[0];
    out.push(QK.kpi({ label: 'Title favourite', html: true, value: esc(CC.tabbr(L, fav)) + ' ' + CC.pct(sim[fav].p_title),
      sub: '<a href="' + esc(CC.teamHref(L, fav)) + '">' + esc(CC.tname(L, fav)) + '</a>' + (mk && isNum(mk.market) ? ' · market ' + CC.pct(mk.market) : ''),
      tip: 'Share of simulated seasons in which the team wins the national title' }));
  } else if (d.champ) {
    out.push(QK.kpi({ label: 'Champion', html: true, value: '<a href="' + esc(CC.teamHref(L, d.champ, S)) + '">' + esc(CC.tshort(L, d.champ)) + '</a>', text: true, sub: CC.seasonLabel(L, S) }));
  }
  var pw = d.power[0];
  if (pw) {
    var R = d.ratings[String(pw.team)] || {};
    out.push(QK.kpi({ label: 'Best team (model)', html: true, value: esc(CC.tabbr(L, pw.team)) + ' ' + CC.signed(pw.rating, 1),
      sub: (CC.fb(L) ? 'points v average FBS' : 'points per 100 v average D-I') + (isNum(R.se) ? ' · ± ' + CC.f(R.se, 1) : ''),
      tip: CC.fb(L) ? 'Expected margin against an average FBS team on a neutral field' : 'Adjusted efficiency margin per 100 possessions' }));
  }
  var ap = d.ap[0];
  if (ap) out.push(QK.kpi({ label: 'AP No. 1', html: true, value: '<a href="' + esc(CC.teamHref(L, ap.team, S)) + '">' + esc(CC.tshort(L, ap.team)) + '</a>', text: true,
    sub: (isNum(ap.first) && ap.first ? ap.first + ' first-place votes' : 'latest AP poll') + (d.rec[ap.team] ? ' · ' + d.rec[ap.team] : '') }));
  if (isCur) {
    var live = (info.today || []).filter(function (g) { return g.status === 'in'; });
    var nx = (info.today || []).concat(info.next_games || []).filter(function (g) { return g.status === 'pre'; }).sort(function (a, b) { return String(a.date).localeCompare(String(b.date)); })[0];
    if (live.length) out.push(QK.kpi({ label: 'Live now', value: live.length + ' game' + (live.length > 1 ? 's' : ''), sub: live.slice(0, 3).map(function (g) { return CC.tabbr(L, g.away) + '–' + CC.tabbr(L, g.home); }).join(' · ') }));
    else if (nx) out.push(QK.kpi({ label: CC.fb(L) ? 'Next kick-off' : 'Next tip-off', value: QK.whenShort(nx.date), sub: CC.tabbr(L, nx.away) + ' @ ' + CC.tabbr(L, nx.home) + ' · ' + CC.date(nx.date) }));
    var best = null;
    (info.today || []).concat(info.next_games || []).forEach(function (g) {
      if (g.status !== 'pre' || !g.model || !g.market || !isNum(g.model.p_home) || !isNum(g.market.p_home)) return;
      var gap = g.model.p_home - g.market.p_home;
      if (!best || Math.abs(gap) > Math.abs(best.gap)) best = { gap: gap, g: g };
    });
    if (best) out.push(QK.kpi({ label: 'Biggest gap v market', value: QK.fmt.pp(best.gap), sub: CC.tabbr(L, best.g.away) + ' @ ' + CC.tabbr(L, best.g.home) + ' · home side',
      tip: 'Model win probability minus the market price, percentage points' }));
  }
  return '<div class="qk-kpis cc-kpis">' + out.join('') + '</div>';
}

function gamesBlock(L, S, info) {
  var seen = {};
  function take(list) { return (list || []).filter(function (g) { if (seen[g.id]) return false; seen[g.id] = 1; return true; }); }
  var live = take((info.today || []).filter(function (g) { return g.status === 'in'; }));
  var today = take(info.today);
  var next = take(info.next_games).slice(0, Math.max(0, 9 - live.length - today.length));
  var last = take(info.last_games).slice(0, 6);
  function grid(title, list) { return list.length ? '<div class="cc-day">' + title + '</div><div class="cc-games">' + list.map(function (g) { return CC.card(g, L); }).join('') + '</div>' : ''; }
  var html = grid('<b>Live</b>', live) + grid('<b>Today</b>', today) + grid(today.length || live.length ? 'Coming up' : '<b>Next up</b>', next) + grid('Recent results', last);
  if (!html) return '';
  return U.section(live.length ? 'Live and today' : today.length ? 'Today' : 'Games', 'Model win probability on every card; before kick-off the blue and orange dots compare it with the market.', html, U.link(CC.href(L, 'games'), 'All games'));
}

function pastGames(L, S, sched) {
  var PRI = { cfp: 0, ncaa: 0, bowl: 1, nit: 2, wbit: 2 };
  var g = ((sched && sched.games) || []).filter(function (c) { return c.status === 'post' && PRI[c.stype] !== undefined; });
  g.sort(function (a, b) { return PRI[a.stype] - PRI[b.stype] || String(b.date).localeCompare(String(a.date)); });
  if (!g.length) return '';
  return U.section('How it ended', 'The last postseason games of ' + CC.seasonLabel(L, S) + '.', '<div class="cc-games">' + g.slice(0, 9).map(function (c) { return CC.card(c, L); }).join('') + '</div>', U.link(CC.href(L, 'games', null, S), 'All games'));
}

CC.route('overview', function (el, p) {
  var L = p.L, S = p.S, isCur = CC.isCur(L, S), fb = CC.fb(L);
  var info = CC.info(L);
  el.innerHTML = U.head(CC.LNAME[L] + ' ' + CC.seasonLabel(L, S), isCur ? esc(info.headline || '') : '', U.kicker(L, S)) + QK.skeleton('lines', 5);
  return Promise.all([CC.season(L, S), CC.load(CC.lpath(L, 'markets.json')), CC.load(CC.path(L, S, fb ? 'cfp.json' : 'bracket.json')),
    CC.load(CC.lpath(L, 'history.json')), isCur ? Promise.resolve(null) : CC.load(CC.path(L, S, 'schedule.json'))]).then(function (a) {
    if (!U.alive(el)) return;
    var season = CC.ok(a[0]) ? a[0] : null, markets = CC.ok(a[1]) && String(a[1].season) === String(S) ? a[1] : null, post = CC.ok(a[2]) ? a[2] : null, hist = CC.ok(a[3]) ? a[3] : null;
    if (!season) { el.innerHTML = U.head(CC.LNAME[L] + ' ' + CC.seasonLabel(L, S), '', U.kicker(L, S)) + U.missing('This season', a[0]); return; }
    var sim = (season.sim && season.sim.teams) || {}, ratings = season.ratings || {};
    var power = (season.power || []).filter(function (r) { return r && r.team !== undefined; });
    if (!power.length) power = Object.keys(ratings).filter(function (t) { return isNum(ratings[t].rating); }).sort(function (x, y) { return ratings[y].rating - ratings[x].rating; }).map(function (t, i) { return { rank: i + 1, team: t, rating: ratings[t].rating }; });
    var ap = ((season.polls || {}).ap || []);
    var rec = {};
    Object.keys(season.standings || {}).forEach(function (c) { (season.standings[c] || []).forEach(function (r) { rec[String(r.team)] = CC.record(r.w, r.l); }); });
    var champ = null;
    ((hist && hist.champions) || []).forEach(function (c) { if (Number(c.season) === Number(S)) champ = String(c.team); });
    if (!champ && post && post.actual && post.actual.champion) champ = String(post.actual.champion);
    if (!champ && post && post.actual) {
      var fin = ((post.actual.games || (post.actual.bracket && post.actual.bracket.games)) || []).filter(function (g) { return /championship|^final$/i.test(String(g.round || '')) && (g.winner || CC.status(g) === 'final'); })[0];
      if (fin) champ = String(fin.winner || (fin.hs > fin.as ? fin.home : fin.away));
    }
    var d = { sim: sim, ratings: ratings, power: power, ap: ap, rec: rec, champ: champ };
    var html = U.head(CC.LNAME[L] + ' ' + CC.seasonLabel(L, S), isCur ? esc(info.headline || '') : (champ ? esc(CC.tname(L, champ)) + ' won the title.' : ''), U.kicker(L, S)) + kpis(L, S, d);
    html += isCur ? gamesBlock(L, S, info) : pastGames(L, S, a[4]);
    // charts
    var title = (isCur ? (info.title_odds || []) : []).filter(function (r) { return isNum(r.p); }).slice(0, 12);
    if (!title.length) title = Object.keys(sim).filter(function (t) { return isNum(sim[t].p_title) && sim[t].p_title > 0; }).sort(function (x, y) { return sim[y].p_title - sim[x].p_title; }).slice(0, 12).map(function (t) { return { team: t, p: sim[t].p_title, market: null }; });
    var mkTitle = markets && markets.futures && markets.futures.champion && markets.futures.champion.probs ? markets.futures.champion.probs : {};
    title.forEach(function (r) { if (!isNum(r.market) && isNum(mkTitle[r.team])) r.market = mkTitle[r.team]; });
    var hasMk = title.some(function (r) { return isNum(r.market); });
    var top = power.slice(0, 25);
    var grid = '<div class="qk-grid cc-grid">';
    if (title.length) grid += '<div class="qk-span-6">' + U.card('Who wins it all', hasMk ? 'Model title odds against the de-vigged market price.' : 'Model title odds (no market prices loaded).', U.chart('ov-title', Math.max(260, title.length * 30 + 40), 'Title odds, model against market') +
      dataTable(['Team', { label: 'Model', align: 'right' }, { label: 'Market', align: 'right' }], title.map(function (r) { return [{ html: U.teamEnt(L, r.team), v: CC.tname(L, r.team) }, { v: r.p, html: CC.pct(r.p, 1) }, { v: isNum(r.market) ? r.market : -1, html: CC.pct(r.market, 1) }]; }))) + '</div>';
    if (top.length) grid += '<div class="qk-span-6">' + U.card('Power ratings', (fb ? 'Points better than an average FBS team on a neutral field' : 'Adjusted efficiency margin per 100 possessions') + '; whiskers ± one standard error.',
      U.chart('ov-power', Math.max(320, top.length * 22 + 30), 'Power ratings, top 25') +
      dataTable(['#', 'Team', { label: 'Rating', align: 'right' }, { label: '±', align: 'right' }, { label: 'Record', align: 'right' }], top.map(function (r) { var R = ratings[String(r.team)] || {}; return [r.rank, { html: U.teamEnt(L, r.team, { season: S }), v: CC.tname(L, r.team) }, { v: r.rating, html: CC.signed(r.rating, 1) }, CC.f(R.se, 1), rec[String(r.team)] || '—']; }))) + '</div>';
    if (ap.length) {
      var mrank = {}; power.forEach(function (r, i) { mrank[String(r.team)] = r.rank || i + 1; });
      var pts = ap.slice(0, 25).filter(function (r) { return isNum(mrank[String(r.team)]); });
      grid += '<div class="qk-span-6">' + U.card('AP poll v our ranking', 'Across: AP rank; down: our rank (1 at the top). Above the line, we rank the team higher than the voters do.', U.chart('ov-ap', 340, 'AP rank against model rank') +
        dataTable(['AP', 'Team', { label: 'Prev', align: 'right' }, { label: 'Ours', align: 'right' }, { label: 'Record', align: 'right' }], ap.slice(0, 25).map(function (r) { return [r.rank, { html: U.teamEnt(L, r.team, { season: S }), v: CC.tname(L, r.team) }, isNum(r.prev) ? r.prev : '—', isNum(mrank[String(r.team)]) ? mrank[String(r.team)] : '—', rec[String(r.team)] || '—']; }))) + '</div>';
      d.apPts = pts; d.mrank = mrank;
    }
    grid += '<div class="qk-span-6" id="ov-post"></div></div>';
    html += U.section(isCur ? 'The race' : 'The season in numbers', '', grid);
    el.innerHTML = html;
    U.wire(el);
    if (title.length) {
      if (hasMk) QKC.dumbbell('#ov-title', { rows: title.map(function (r) { return { label: CC.tshort(L, r.team), a: r.p, b: isNum(r.market) ? r.market : r.p, href: CC.teamHref(L, r.team) }; }), aName: 'Model', bName: 'Market', max: Math.min(1, Math.max.apply(null, title.map(function (r) { return Math.max(r.p, r.market || 0); })) * 1.15 + 0.02), labelWidth: 110 });
      else QKC.bar('#ov-title', { cats: title.map(function (r) { return CC.tshort(L, r.team); }), series: [{ name: 'Title', data: title.map(function (r) { return r.p; }) }], horizontal: true, labels: true, fmt: function (v) { return CC.pct(v); }, colors: title.map(function (r) { return CC.tcol(L, r.team); }), hrefs: title.map(function (r) { return CC.teamHref(L, r.team); }) });
    }
    if (top.length) QKC.bar('#ov-power', { cats: top.map(function (r) { return CC.tshort(L, r.team); }), horizontal: true, fmt: function (v) { return CC.signed(v, 1); },
      series: [{ name: 'Rating', data: top.map(function (r) { return r.rating; }), lo: top.map(function (r) { var R = ratings[String(r.team)] || {}; return isNum(R.se) ? r.rating - R.se : null; }), hi: top.map(function (r) { var R = ratings[String(r.team)] || {}; return isNum(R.se) ? r.rating + R.se : null; }) }],
      colors: top.map(function (r) { return CC.tcol(L, r.team); }), hrefs: top.map(function (r) { return CC.teamHref(L, r.team, S); }), labelWidth: 96 });
    if (d.apPts && d.apPts.length) QKC.scatter('#ov-ap', { points: d.apPts.map(function (r) { return { x: r.rank, y: d.mrank[String(r.team)], name: CC.tname(L, r.team), label: CC.tabbr(L, r.team), color: CC.tcol(L, r.team), href: CC.teamHref(L, r.team, S) }; }),
      xName: 'AP rank', yName: '', xInverse: false, yInverse: true, diagonal: { label: 'agree' }, labelTop: 10, xMin: 0, yMin: 1 });
    postSnapshot(L, S, post, sim, QK.$('#ov-post', el));
  });
});

/* The CFP picture (cfb) or the bracket picture (basketball). */
function postSnapshot(L, S, post, sim, node) {
  if (!node) return;
  var fb = CC.fb(L);
  if (fb) {
    var odds = (post && post.odds) || {};
    var rows = Object.keys(odds).filter(function (t) { return isNum(odds[t].p_in); }).sort(function (a, b) { return odds[b].p_in - odds[a].p_in; }).slice(0, 16);
    if (!rows.length) rows = Object.keys(sim).filter(function (t) { return isNum(sim[t].p_cfp); }).sort(function (a, b) { return sim[b].p_cfp - sim[a].p_cfp; }).slice(0, 16).map(function (t) { odds[t] = { p_in: sim[t].p_cfp, p_bye: sim[t].p_bye, p_title: sim[t].p_title }; return t; });
    if (!rows.length) { node.innerHTML = U.card('Playoff picture', '', U.missing('Playoff odds', post)); return; }
    node.innerHTML = U.card('Playoff picture', 'Chance to make the 12-team College Football Playoff, with a first-round bye and to win it.', U.chart('ov-cfp', rows.length * 24 + 50, 'Playoff odds, top 16') +
      '<details class="cc-data"><summary>Show the numbers as a table</summary>' + U.table(['Team', { label: 'In', align: 'right' }, { label: 'Bye', align: 'right' }, { label: 'Title', align: 'right' }], rows.map(function (t) {
        return [{ html: U.teamEnt(L, t, { season: S }), v: CC.tname(L, t) }, U.heat(odds[t].p_in), U.heat(odds[t].p_bye), U.heat(odds[t].p_title)]; })) + '</details>', { foot: U.link(CC.href(L, 'standings', null, S, 'tab=playoff'), 'Projected bracket and committee proxy') });
    U.wire(node);
    QKC.bar('#ov-cfp', { cats: rows.map(function (t) { return CC.tshort(L, t); }), horizontal: true, legend: true, fmt: function (v) { return CC.pct(v); }, max: 1,
      series: [{ name: 'Make the playoff', data: rows.map(function (t) { return odds[t].p_in; }) }, { name: 'Win the title', data: rows.map(function (t) { return odds[t].p_title || 0; }) }], hrefs: rows.map(function (t) { return CC.teamHref(L, t, S); }), labelWidth: 96 });
    return;
  }
  var bo = (post && post.bracketology) || [];
  var od = (post && post.odds) || {};
  if (post && post.actual && post.actual.regions) {
    var champ = Object.keys(od).filter(function (t) { return isNum((od[t].p_round || {}).Champion); }).sort(function (a, b) { return od[b].p_round.Champion - od[a].p_round.Champion; }).slice(0, 12);
    node.innerHTML = U.card('Pre-tournament title odds', 'Our probabilities when the field was set, with the seed.', U.table(['Team', { label: 'Seed', align: 'right' }, { label: 'Final Four', align: 'right' }, { label: 'Title', align: 'right' }], champ.map(function (t) {
      return [{ html: U.teamEnt(L, t, { season: S }), v: CC.tname(L, t) }, od[t].seed || '—', U.heat(od[t].p_round.F4), U.heat(od[t].p_round.Champion)]; })), { foot: U.link(CC.href(L, 'standings', null, S, 'tab=bracket'), 'The full bracket') });
    U.wire(node);
    return;
  }
  if (!bo.length) { node.innerHTML = U.card('Bracketology', '', U.missing('Bracketology', post)); return; }
  var top = bo.slice(0, 16);
  node.innerHTML = U.card('Bracketology', 'Projected seed lines from simulated seasons and a selection model fitted on past fields.', U.table(['Team', { label: 'Seed', align: 'right' }, { label: 'In field', align: 'right' }, { label: 'Auto bid', align: 'right' }, { label: 'Rec.', align: 'right' }], top.map(function (r) {
    return [{ html: U.teamEnt(L, r.team, { season: S }), v: CC.tname(L, r.team) }, { v: r.seed_mean, html: CC.f(r.seed_mean, 1) }, U.heat(r.p_ncaa), U.heat(r.p_auto), r.record || '—']; }), { maxHeight: 420 }),
    { foot: U.link(CC.href(L, 'standings', null, S, 'tab=bracket'), 'Projected bracket') });
  U.wire(node);
}

})(window.CC);
