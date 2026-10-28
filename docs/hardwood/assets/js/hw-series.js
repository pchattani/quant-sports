/* The Quant Hardwood — playoff series pages (#/<L>/series/<a>-<b>?s=S), round 9 (28 Oct 2026, Phase 4). One page per
 * play-in or playoff series, linked from every bracket box (hw-bracket.js):
 *   - the head: the round, the two teams as blocks with their seeds, the series score in Bebas and who leads or won;
 *   - headline numbers: our series call where the season simulation has one (season.json bracket matchups:
 *     p_home_court_wins, while the series is live), our pre-game favourite's record in the series, the closest game;
 *   - game by game: our pre-game chance for each side (schedule.json model.p_home: the walk-forward number from the
 *     ratings before the game day, no look-ahead) as bars, the result marked, then the games as a table linking the game
 *     pages;
 *   - the tale of the tape on the season's ratings and the explain strip.
 * Data: <L>/<S>/season.json (postseason, ratings, standings, bracket) and <L>/<S>/schedule.json. Older-browser rule: no
 * optional chaining, no nullish coalescing. */
(function (HW) {
'use strict';

const U = HW.ui, esc = HW.esc, isNum = HW.isNum;

function render(el, params) {
  const L = U.L(params), S = U.S(params);
  const ids = String(params.id || '').split('-').filter(Boolean);
  el.innerHTML = QK.skeleton('lines', 6);
  return Promise.all([HW.load(HW.path('season.json', L, S)), HW.load(HW.path('schedule.json', L, S))]).then(res => {
    if (!U.alive(el)) return;
    const season = U.ok(res[0]) ? res[0] : null, sched = U.ok(res[1]) ? res[1] : null;
    const s = season && HW.bracket && ids.length === 2 ? HW.bracket.find(season, ids[0], ids[1]) : null;
    const back = '<nav class="hw-crumb" aria-label="Breadcrumb"><a href="' + esc(HW.href(L, 'standings', S) + (HW.sq(L, S) ? '&' : '?') + 'tab=bracket') + '">← ' + esc(HW.leagueName(L) + ' ' + HW.seasonLabel(L, S)) + ' bracket</a></nav>';
    if (!s) { el.innerHTML = back + U.secHead('Playoff series', '', null, null, U.kicker(L, S)) + U.empty('No such series', 'These two teams did not meet in the ' + HW.seasonLabel(L, S) + ' postseason.'); return; }
    const A = s.teams[0], B = s.teams[1];
    const seeds = {}; Object.keys((season.standings || {})).forEach(c => (season.standings[c] || []).forEach((r, i) => { seeds[String(r.team)] = isNum(r.seed) ? r.seed : i + 1; }));
    const [hi, lo] = [A, B].sort((x, y) => (seeds[x] || 99) - (seeds[y] || 99));
    const byId = {}; ((sched && sched.games) || []).forEach(g => { byId[String(g.id)] = g; });
    const games = (s.games || []).map(g => Object.assign({}, g, byId[String(g.id)] || {}, { status: (byId[String(g.id)] || {}).status || g.status })).sort((a, b) => String(a.date).localeCompare(String(b.date)));
    const played = games.filter(g => g.status === 'post' && isNum(g.hs) && isNum(g.as));
    const w = s.wins || {};
    const pc = U.pair(L, hi, lo);
    const pFor = (g, t) => { const p = (g.model || {}).p_home; return isNum(p) ? (String(g.home) === t ? p : 1 - p) : null; };
    const winner = g => String(g.hs > g.as ? g.home : g.away);
    const called = played.filter(g => { const p = pFor(g, hi); return isNum(p) && ((p >= 0.5) === (winner(g) === hi)); }).length;
    const withP = played.filter(g => isNum(pFor(g, hi))).length;
    const close = played.slice().sort((a, b) => Math.abs(a.hs - a.as) - Math.abs(b.hs - b.as))[0];
    /* our live series call from the season simulation's bracket */
    const mts = season.bracket && season.bracket.matchups ? [].concat.apply([], Object.keys(season.bracket.matchups).map(k => season.bracket.matchups[k] || [])) : [];
    const mt = mts.find(m => HW.bracket.key([m.home_court, m.other]) === HW.bracket.key([A, B]) && (m.p || 0) >= 0.999);
    const pSer = mt && isNum(mt.p_home_court_wins) ? { t: String(mt.home_court), p: mt.p_home_court_wins } : null;
    document.title = HW.teamAbbr(L, A) + ' v ' + HW.teamAbbr(L, B) + ' · ' + (s.round || 'Playoff series') + ' · The Quant Hardwood';
    const blk = t => { const b = QK.color.block(HW.teamColourRaw(L, t)); return '<a class="hw-ser-t" href="' + esc(HW.teamHref(L, t, S)) + '" style="--tc:' + esc(b.bg) + ';--te:' + esc(b.edge || b.bg) + '"><span class="sd">' + (seeds[t] ? 'Seed ' + seeds[t] : '') + '</span><b>' + esc(HW.teamName(L, t)) + '</b><span class="w">' + (s.stype === 'playin' ? '' : (w[t] || 0)) + '</span></a>'; };
    let h = back + U.secHead((s.stype === 'playin' ? 'Play-in: ' : '') + HW.teamShort(L, hi) + ' v ' + HW.teamShort(L, lo), esc((s.round || (s.stype === 'playin' ? 'Play-in' : 'Playoffs')) + (s.conf ? ' · ' + s.conf : '') + (s.best_of ? ' · best of ' + s.best_of : '')), null, null, U.kicker(L, S)) +
      '<div class="hw-ser">' + blk(hi) + '<div class="hw-ser-m"><b>' + esc(HW.bracket.line(L, s)) + '</b></div>' + blk(lo) + '</div>';
    const kp = [];
    if (pSer && !s.winner) kp.push({ label: 'Our series call', value: HW.teamAbbr(L, pSer.p >= 0.5 ? pSer.t : (pSer.t === A ? B : A)) + ' ' + U.pct(Math.max(pSer.p, 1 - pSer.p)), signal: true, sub: 'to win the series, from the season simulation' });
    if (withP) kp.push({ label: 'Our game calls', value: called + ' of ' + withP, sub: 'games where our pre-game favourite won' });
    if (close) kp.push({ label: 'Closest game', value: HW.teamAbbr(L, close.away) + ' ' + close.as + '–' + close.hs + ' ' + HW.teamAbbr(L, close.home), href: HW.gameHref(L, close.id, S), sub: HW.fmtDate(close.date, { year: false }) });
    if (kp.length) h += '<div class="hw-kpis">' + QK.stats(kp) + '</div>';
    h += '<div class="qk-grid hw-sec">' + U.card2('Game by game', 'Our pre-game chance for the ' + esc(HW.teamShort(L, hi)) + ' in each game; the result under each bar', U.chart('ser-c', 300, 'Our pre-game chance in each game'), { cls: 'qk-span-7' }) +
      U.card2('The games', '', '<div id="ser-t"></div>', { cls: 'qk-span-5', flush: true }) + '</div>';
    const R = season.ratings || {};
    const ra = R[hi] || {}, rb = R[lo] || {};
    if (isNum(ra.net) && isNum(rb.net)) h += U.card2('Tale of the tape', 'The two teams’ season ratings (points per 100 possessions, opponent-adjusted)', QK.matchupBar({ left: U.team(L, hi), right: U.team(L, lo), colors: pc, rows: [
      { label: 'Net rating', a: ra.net, b: rb.net, fmt: v => U.signed(v, 1) }, { label: 'Offensive rating', a: ra.off, b: rb.off, fmt: v => U.f(v, 1) }, { label: 'Defensive rating', a: ra.def, b: rb.def, fmt: v => U.f(v, 1), better: 'low' }] }), { cls: 'hw-sec' });
    h += QK.explain('Each bar is the chance our game model gave the ' + esc(HW.teamShort(L, hi)) + ' before that game, from the ratings as they stood the day before (no hindsight). A 60% call still goes the other way 4 times in 10, so a series can turn on one or two of them.', { title: 'What’s that number?' });
    el.innerHTML = h;
    const cats = games.map((g, i) => 'Game ' + (i + 1) + (g.status === 'post' && isNum(g.hs) ? ' · ' + HW.teamAbbr(L, winner(g)) + ' won' : ''));
    QKC.bar('#ser-c', { cats: cats, series: [{ name: 'Our chance for ' + HW.teamAbbr(L, hi), data: games.map(g => { const p = pFor(g, hi); return isNum(p) ? Math.round(p * 1000) / 10 : null; }), color: 'model' }], labels: true, fmt: v => v + '%', max: 100,
      valName: 'Our pre-game chance for ' + HW.teamAbbr(L, hi) + ' (%)', catName: 'Game', hrefs: games.map(g => HW.gameHref(L, g.id, S)) });
    QK.table(document.getElementById('ser-t'), { dense: true, rows: games.map((g, i) => ({ n: i + 1, g: g, date: g.date, res: g.status === 'post' && isNum(g.hs) ? winner(g) : null })), columns: [
      { key: 'n', label: '#', num: true }, { key: 'date', label: 'Date', fmt: v => esc(HW.fmtDate(v, { year: false })) },
      { key: 'g', label: 'Game', sort: false, fmt: v => '<a class="hw-link" href="' + esc(HW.gameHref(L, v.id, S)) + '">' + esc(HW.teamAbbr(L, v.away) + (isNum(v.as) && v.status === 'post' ? ' ' + v.as + ' – ' + v.hs + ' ' : ' at ') + HW.teamAbbr(L, v.home)) + '</a>' },
      { key: 'res', label: 'Won', sort: false, fmt: v => (v ? esc(HW.teamAbbr(L, v)) : '<span class="hw-quiet">to play</span>') }] });
    HW.setMeta('');
  });
}

HW.page('series', render);
})(window.HW);
