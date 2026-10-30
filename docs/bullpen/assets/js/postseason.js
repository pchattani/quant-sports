/* The Quant Bullpen — the bracket (#/postseason, Standings > Bracket).
 *
 * A season being played: our title favourite, the bracket (Wild Card best of three, Division Series best of five, League
 * Championship and World Series best of seven) with series wins and our chance in each series, the World Series chances,
 * every series and each club's path. A finished season: the recap (the champion, our calls against what happened, the
 * final bracket with seeds and series scores, every series). No market on this page (it lives on Model > Our forecasts
 * v the market).
 *
 * Reads <L>/<S>/season.json "postseason" (else index.json "postseason") and "calls", and schedule.json for the series'
 * games. */
(function (BP) {
'use strict';

const esc = BP.esc;
const isNum = BP.isNum;
const ORDER = { WC: 0, DS: 1, LCS: 2, WS: 3 };

function postOf(season, idx) {
  const p = (season && (season.postseason || season.bracket)) || null;
  if (p && (p.series || p.teams)) return Object.assign({}, idx || {}, p);
  return idx || null;
}
function seriesState(s) {
  const w = BP.charts.winnerOf(Object.assign({}, s, { teams: (s.teams || []).map(String) }));
  if (w) return { done: true, winner: w };
  return { done: false, started: (s.wins || [0, 0])[0] + (s.wins || [0, 0])[1] > 0 };
}

function seriesTable(list, games, L, sims) {
  const rows = list.slice().sort((a, b) => (ORDER[BP.roundKey(a.round)] - ORDER[BP.roundKey(b.round)]) || String(a.league || '').localeCompare(String(b.league || ''))).map(s => {
    const st = seriesState(s);
    const t = (s.teams || []).map(String);
    const nx = s.next || null;
    const lastG = (s.games || []).slice(-1)[0];
    const cell = i => {
      const p = s.p ? s.p[i] : null;
      return st.done ? (st.winner === t[i] ? '<span class="edge-pos">won</span>' : '<span class="muted-inline">out</span>') : (isNum(p) ? '<b class="bp-ours">' + BP.pct(p, 0) + '</b>' : '—');
    };
    return { _class: st.done ? 'ser-done' : '', cells: [
      { v: ORDER[BP.roundKey(s.round)], html: '<b>' + esc((s.league && BP.roundKey(s.round) !== 'WS' ? s.league + ' ' : '') + BP.roundLabel(BP.roundKey(s.round), true)) + '</b><div class="sub-line">best of ' + esc(s.best_of || '') + '</div>' },
      { v: BP.teamName(t[0]), html: '<div class="ser-t">' + BP.teamLink(t[0], { short: true, level: L }) + '<span class="ser-w">' + esc((s.wins || [])[0]) + '</span><span class="ser-p">' + cell(0) + '</span></div>' +
        '<div class="ser-t">' + BP.teamLink(t[1], { short: true, level: L }) + '<span class="ser-w">' + esc((s.wins || [])[1]) + '</span><span class="ser-p">' + cell(1) + '</span></div>' },
      { v: nx ? (nx.date || '') : '', html: nx ? (nx.gpk ? BP.gameLink(nx.gpk, BP.teamAbbr(nx.away) + ' @ ' + BP.teamAbbr(nx.home) + (nx.date ? ' · ' + BP.fmtDate(nx.date, { year: false }) : ''), L) : esc(BP.teamAbbr(nx.away) + ' @ ' + BP.teamAbbr(nx.home))) +
        (isNum(nx.p_home) ? '<div class="sub-line">our chance ' + esc(BP.teamAbbr(nx.home)) + ' ' + BP.pct(nx.p_home, 0) + '</div>' : '') : (lastG ? BP.gameLink(lastG, 'Latest game', L) : '—'), cls: 'hide-sm' }
    ] };
  });
  if (!rows.length) return BP.muted('No series yet.');
  return BP.tableHTML([{ label: 'Round' }, { label: 'Series: wins · our chance to win the series', sortable: false }, { label: 'Next game', cls: 'hide-sm' }], rows, { compact: true, cls: 'ser-table' }) +
    '<div class="section-note">Series chances from ' + (sims ? BP.int(sims) : 'the') + ' simulations of the bracket; the next game in each series uses our game forecast with the probable starters, so a series can move before a pitch is thrown.</div>';
}

function pathTable(post, L) {
  const pt = post.teams || {};
  const ids = Object.keys(pt).sort((a, b) => (pt[b].p_ws || 0) - (pt[a].p_ws || 0));
  if (!ids.length) return BP.muted('Path chances arrive with the bracket simulation.');
  const rows = ids.map(t => {
    const x = pt[t], nx = x.next || null;
    return [{ v: x.seed, html: '<span class="muted-inline">' + esc(x.league || '') + '</span> ' + esc(x.seed || '') },
      { v: BP.teamName(t), html: BP.teamLink(t, { level: L }) },
      { v: x.p_ds, html: x.p_ds >= 0.9995 ? '<span class="odds-done">✓</span>' : BP.pct(x.p_ds, 0), align: 'right' },
      { v: x.p_lcs, html: BP.pct(x.p_lcs, 0), align: 'right' },
      { v: x.p_pennant, html: BP.pct(x.p_pennant, 1), align: 'right' },
      { v: x.p_ws, html: BP.probCell(x.p_ws, BP.teamColour(t), 0.4), align: 'right' },
      { v: nx && nx.if_win ? nx.if_win.p_ws : null, html: nx && nx.if_win ? BP.pct(nx.if_win.p_ws, 1) + ' <span class="muted-inline">/</span> ' + BP.pct((nx.if_loss || {}).p_ws, 1) : '—', align: 'right', cls: 'hide-sm',
        title: 'World Series probability if they win / lose their next game' }];
  });
  return BP.tableHTML([{ label: 'Seed' }, { label: 'Team' }, { label: 'DS', align: 'right', title: 'Reach the Division Series' }, { label: 'LCS', align: 'right' },
    { label: 'Pennant', align: 'right' }, { label: 'World Series', align: 'right' },
    { label: 'Next game: win / lose', align: 'right', cls: 'hide-sm' }], rows, { compact: true });
}

function seriesDetail(s, games, L) {
  if (!s) return BP.muted('Click a series in the bracket to see its games.');
  const t = (s.teams || []).map(String);
  const all = (s.games || []).map(id => games[id] || { gpk: id }), unneeded = BP.unneededIn(all);
  const gl = all.filter(c => !BP.notNeeded(c) && !unneeded(c));
  const nx = s.next;
  const st = seriesState(s);
  return '<div class="sd-head"><b>' + esc((s.league && BP.roundKey(s.round) !== 'WS' ? s.league + ' ' : '') + BP.roundLabel(BP.roundKey(s.round))) + '</b> · ' +
    BP.teamLink(t[0], { level: L }) + ' <b>' + esc((s.wins || [])[0]) + '-' + esc((s.wins || [])[1]) + '</b> ' + BP.teamLink(t[1], { level: L }) +
    (st.done ? ' · <span class="edge-pos">' + esc(BP.teamShort(st.winner)) + ' won</span>' : (s.p ? ' · our chance ' + esc(BP.teamAbbr(t[0])) + ' ' + BP.pct(s.p[0], 0) : '')) + '</div>' +
    '<div class="bp-gc-grid">' + gl.map(c => (c && c.home ? BP.gameCard(c, { level: L, date: true, compact: false }) : '<a class="gc" href="' + BP.gameHref(c.gpk, L) + '">Game ' + esc(c.gpk) + '</a>')).join('') +
    (nx && !(s.games || []).some(g => String(g) === String(nx.gpk)) && games[nx.gpk] ? BP.gameCard(games[nx.gpk], { level: L, date: true }) : '') + '</div>';
}

/* Round 9 (Phase 3): the page reads headline, chart, table, then the explain strip.
 *   a season still being played: our title favourite, the bracket with each series' chance, the World Series chances,
 *   every series, each club's path;
 *   a finished season (season.json postseason.actual): the recap. The champion, our calls against what happened (the
 *   chance we gave each club on the eve of the postseason beside how far it went, from season.json "calls"), the final
 *   bracket with the seeds and every series score, and every series with its games. */
const REACH = { CH: 'Champions', WS: 'World Series', CS: 'LCS', LC: 'League final', DS: 'Division Series', WC: 'Wild Card' };
function reachOf(post, t, champ) {
  if (t === champ) return 'Champions';
  const r = ((post.teams || {})[t] || {}).reached;
  return r === 'WS' ? 'Lost the World Series' : r === 'CS' ? 'Lost the LCS' : r === 'DS' ? 'Out in the Division Series' : r === 'WC' ? 'Out in the Wild Card round' : '';
}
function recap(el, post, season, games, L, S) {
  const champ = post.champion;
  const calls = (season && season.calls) || {};
  const pre = (calls.preplayoff || {}).p_ws || {}, first = (calls.first || {}).p_ws || {};
  const list = BP.charts.seriesList(post);
  const ws = list.find(x => x.rk === 'WS');
  const runner = ws ? ws.teams.find(t => t !== champ) : null;
  const wsW = ws ? (ws.teams[0] === champ ? ws.wins : [ws.wins[1], ws.wins[0]]) : null;
  const ranked = Object.keys(pre).sort((a, b) => pre[b] - pre[a]);
  const fav = ranked[0];
  const upsets = list.filter(x => { const w = BP.charts.winnerOf(x); return w && x.teams[1] === w; }).length;
  /* round 11: a decided postseason's tiles: champion, runner-up, the series result, our call for the champion */
  const tiles = [];
  if (champ) tiles.push({ label: 'Champion', value: BP.teamAbbr(champ), signal: true, sub: BP.teamName(champ), href: BP.teamHref(champ, L, S) });
  if (runner) tiles.push({ label: 'Runner-up', value: BP.teamAbbr(runner), sub: BP.teamName(runner), href: BP.teamHref(runner, L, S) });
  if (wsW) tiles.push({ label: 'Series result', value: wsW[0] + '–' + wsW[1], sub: 'the World Series, in ' + (wsW[0] + wsW[1]) + ' games' });
  if (champ && isNum(pre[champ])) tiles.push({ label: 'Our call for them', value: BP.ui.pct(pre[champ]), sub: 'on the eve of the postseason, ' + ordinal(ranked.indexOf(champ) + 1) + ' of ' + ranked.length +
    (fav && fav !== champ ? '; our favourite, the ' + BP.teamShort(fav) + ' (' + BP.ui.pct(pre[fav]) + '), ' + (reachOf(post, fav, champ) || 'did not win').toLowerCase() : fav === champ ? ': our favourite' : '') +
    (isNum(first[champ]) ? '; ' + BP.ui.pct(first[champ]) + ' after the first week' : '') });
  const upNote = upsets + ' of ' + list.filter(x => BP.charts.winnerOf(x)).length + ' series went to the club without home field.';
  let h = QK.sectionHead({ kicker: 'Postseason · MLB ' + S, title: champ ? 'The ' + BP.teamShort(champ) + ' won it all' : 'How the ' + S + ' postseason went', sub: 'The bracket as it was played, every series score, and the chances we gave each club before the first pitch of October against how far it went.' }) +
    '<div class="bp-kpis">' + QK.stats(tiles) + '</div>';
  if (ranked.length) h += '<section class="qk-section">' + BP.ui.card2('Our calls against what happened', 'Our World Series chance for each club on ' + BP.fmtDate((calls.preplayoff || {}).asof) + ', on the eve of the postseason, and how far each went', '<div id="ps-calls" class="qk-chart" style="--h:' + Math.max(300, 34 * ranked.length + 60) + 'px" role="img" aria-label="Our pre-postseason World Series chances against how far each club went"></div>') + '</section>';
  h += '<section class="qk-section">' + BP.ui.card2('The bracket', 'Seeds, every series score; click a series for its games', '<div id="ps-bk"></div><div id="ps-sd" class="pad0"></div>') + '</section>' +
    '<section class="qk-section">' + BP.ui.card2('Every series', list.length + ' series', seriesTable(list, games, L, null), { flush: true }) + '</section>' +
    QK.explain((/as logged/.test(calls.method || '') ? esc(calls.method) + ' ' : 'Our calls are rebuilt walk-forward from what was known that morning: the season simulation on team ratings from each club’s run differential, the bracket as it stood. ' + (calls.method ? esc(calls.method) + ' ' : '')) + 'A 15% favourite still loses 85 times in 100, and a 12-club bracket of short series is close to a lottery: ' + esc(upNote), { title: 'How sure were we?' });
  el.innerHTML = h;
  if (ranked.length) callsChart('#ps-calls', post, calls);
}
/* Our calls against what happened: the World Series chance we gave each club on the eve of the postseason (season.json
   "calls"), the champion in volt, each bar labelled with how far the club went. Shared with the overview's recap. */
function callsChart(sel, post, calls) {
  const pre = ((calls || {}).preplayoff || {}).p_ws || {}, champ = post.champion;
  const rows = Object.keys(pre).sort((a, b) => pre[b] - pre[a]);
  if (!rows.length) return;
  const T = QKC.tokens();
  QKC.bar(sel, { cats: rows.map(t => BP.teamAbbr(t) + ' · ' + (reachOf(post, t, champ) || '')), series: [{ name: 'Our World Series chance', data: rows.map(t => pre[t]) }],
    colors: rows.map(t => (t === champ ? T.volt : QK.color.ensure(BP.ui.raw(t) || T.model, T.s1, 3))), horizontal: true, labels: true, labelWidth: 230, fmt: v => BP.pct(v, 0),
    valName: 'Our World Series chance before the postseason', catName: 'Club and how far it went', label: 'Our calls against what happened' });
}
BP.recap = { callsChart: callsChart, reachOf: reachOf };
function ordinal(n) { const s = ['th', 'st', 'nd', 'rd'], v = n % 100; return n + (s[(v - 20) % 10] || s[v] || s[0]); }

function render(el, params) {
  const L = 'mlb', S = params.season;
  const idx = BP.index() || {};
  el.innerHTML = '<div id="ps-body">' + QK.skeleton('card', 2) + '</div>';
  return BP.loadAll([BP.ypath('season.json', L, S), BP.ypath('schedule.json', L, S)]).then(arr => {
    if (!el.isConnected) return;
    const season = BP.ok(arr[0]) ? arr[0] : null;
    /* round 11: a decided World Series opens as played (the recap), this season's too */
    const post = BP.charts.asPlayed(postOf(season, S === BP.currentSeason(L) ? idx.postseason : null));
    const body = document.getElementById('ps-body');
    if (!post || (!(post.series || []).length && !Object.keys(post.teams || {}).length)) {
      body.innerHTML = QK.sectionHead({ kicker: 'Postseason · MLB ' + S, title: 'The bracket' }) + BP.ui.card2('Postseason', '', season && season.postseason && season.postseason.available === false ? BP.notBuilt('The bracket', season.postseason) : BP.muted('The ' + S + ' bracket is not set yet. Until it is, our playoff chances live on <a href="' + BP.href('chances', L, S) + '">Chances</a>.'));
      return;
    }
    const games = {};
    const sched = arr[1] && Array.isArray(arr[1].games) ? arr[1].games : [];
    sched.forEach(g => { if (g && g.gpk) games[g.gpk] = g; });
    if (S === BP.currentSeason(L)) [].concat(idx.today || [], idx.recent || [], idx.upcoming || []).forEach(g => { if (g && g.gpk) games[g.gpk] = g; });
    const list = BP.charts.seriesList(post);
    const live = list.filter(x => !seriesState(x).done);
    let sel = live.find(x => (x.games || []).length) || live[0] || list[list.length - 1] || null;
    const drawSel = () => {
      document.getElementById('ps-sd').innerHTML = seriesDetail(sel, games, L);
      document.querySelectorAll('#ps-bk .bk-series').forEach(x => x.classList.toggle('sel', !!sel && x.getAttribute('data-sid') === String(sel.id)));
    };
    if (post.actual) {
      recap(body, post, season, games, L, S);
      BP.charts.mlbBracket(document.getElementById('ps-bk'), post, { level: L, onSeries: x => { if (x) { sel = x; drawSel(); } } });
      drawSel();
      BP.sortable(body);
      BP.setMeta('The postseason as played');
      return;
    }
    const pt = post.teams || {};
    const fav = Object.keys(pt).filter(t => isNum(pt[t].p_ws)).sort((a, b) => pt[b].p_ws - pt[a].p_ws)[0];
    const alive = Object.keys(pt).filter(t => isNum(pt[t].p_ws) && pt[t].p_ws > 0.0005).length;
    body.innerHTML = QK.sectionHead({ kicker: 'Postseason · MLB ' + S, title: 'The bracket', sub: 'Our chance in every series from simulating the bracket, and every club’s path to the World Series.',
      actions: '<a class="qk-btn" href="' + BP.href('chances', L, S) + '">Chances</a>' }) +
      '<div class="bp-kpis">' + QK.stats([fav ? { label: 'Title favourite', value: BP.teamAbbr(fav) + ' ' + BP.ui.pct(pt[fav].p_ws), signal: true, sub: 'our chance of winning the World Series', href: BP.teamHref(fav, L, S) } : null,
        { label: 'Still alive', value: String(alive), sub: 'clubs with a title chance' }, post.round ? { label: 'Now', value: BP.roundLabel(post.round, true), sub: BP.roundLabel(post.round) } : null,
        post.sims ? { label: 'Brackets simulated', value: QK.fmt.num(post.sims), sub: 'every remaining game played out' } : null].filter(Boolean)) + '</div>' +
      '<section class="qk-section">' + BP.ui.card2('The bracket', (post.round ? 'now: ' + BP.roundLabel(post.round) + ' · ' : '') + 'click a series for its games', '<div id="ps-bk"></div><div id="ps-sd" class="pad0"></div>') + '</section>' +
      '<section class="qk-section"><div class="qk-grid"><div class="qk-span-5">' + BP.ui.card2('World Series chances', 'Our chance from the bracket simulation', '<div id="ps-ws"></div>') + '</div><div class="qk-span-7">' +
        BP.ui.card2('Every series', 'Wins and our chance to win each series', seriesTable(list, games, L, post.sims), { flush: true }) + '</div></div></section>' +
      '<section class="qk-section">' + BP.ui.card2('Every club’s path', 'Each club’s chance to reach every round', pathTable(post, L), { flush: true }) + '</section>' +
      QK.explain('<b>Format.</b> Six clubs a league: three division winners and three wild cards. Seeds 1 and 2 skip the Wild Card Series (best of three, all at the higher seed); the Division Series is best of five (2-2-1), the League Championship Series and the World Series best of seven (2-3-2). Seed 1 meets the winner of 4 v 5, seed 2 the winner of 3 v 6. ' +
        '<b>Simulation.</b> Every remaining game is drawn from the game model’s chances between the two clubs (lineups, the rotation in order, the bullpen, home field), with a shared strength shock per simulation so a hot team stays hot; the next game of each live series uses our full game forecast with the announced starters. ' +
        '<b>What the next game is worth.</b> The win / lose column reruns the bracket with the next game fixed each way.', { title: 'How the bracket is simulated' });
    BP.charts.mlbBracket(document.getElementById('ps-bk'), post, { level: L, onSeries: x => { if (x) { sel = x; drawSel(); } } });
    drawSel();
    document.getElementById('ps-ws').innerHTML = QK.chances(Object.keys(pt).filter(t => isNum(pt[t].p_ws) && pt[t].p_ws > 0.0005).sort((a, b) => pt[b].p_ws - pt[a].p_ws).map(t => ({ label: BP.teamName(t), p: pt[t].p_ws, color: (BP.teamInfo(t) || {}).colour, href: BP.teamHref(t, L, S), mark: BP.ui.team(t, L, S) })),
      { limit: 12, key: false });
    BP.sortable(body);
    BP.setMeta(post.sims ? BP.int(post.sims) + ' bracket simulations' : '');
  });
}

BP.route('postseason', render);
})(window.BP);
