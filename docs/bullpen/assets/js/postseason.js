/* The Quant Bullpen — postseason (#/postseason).
 *
 *   the bracket (Wild Card best of three, Division Series best of five, League Championship
 *   and World Series best of seven) with series wins and the model's series odds against the market;
 *   series: every series with its odds, the market, the gap, its games and the next game;
 *   path odds: each team's chance to reach the Division Series, the LCS, win the pennant and the
 *   World Series, against the World Series market, with what the next game is worth;
 *   how the bracket is simulated.
 *
 * Reads <L>/<S>/season.json "postseason" (else index.json "postseason"), markets.json futures,
 * and schedule.json for the series' games. */
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
function futureMap(mk, re) {
  const fut = (mk && mk.futures) || {};
  const k = Object.keys(fut).find(x => re.test(x));
  return k ? { probs: BP.titleProbs(fut[k].market || fut[k]), sources: ((fut[k].market || {}).sources || fut[k].sources || []) } : { probs: {}, sources: [] };
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
      const p = s.p ? s.p[i] : null, m = s.market ? s.market[i] : null;
      return st.done ? (st.winner === t[i] ? '<span class="edge-pos">won</span>' : '<span class="muted-inline">out</span>') : (isNum(p) ? '<b class="bp-ours">' + BP.pct(p, 0) + '</b>' : '—') + (isNum(m) ? ' <span class="muted-inline" title="Market reference (Kalshi / Polymarket)">mkt ' + BP.pct(m, 0) + '</span>' : '');
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
  return BP.tableHTML([{ label: 'Round' }, { label: 'Series: wins · our chance to win the series · market (reference)', sortable: false }, { label: 'Next game', cls: 'hide-sm' }], rows, { compact: true, cls: 'ser-table' }) +
    '<div class="section-note">Series chances from ' + (sims ? BP.int(sims) : 'the') + ' simulations of the bracket; the next game in each series uses our game forecast with the probable starters, so a series can move before a pitch is thrown. Market: the de-vigged Kalshi or Polymarket number where they quote the series, for reference.</div>';
}

function pathTable(post, ws, L) {
  const pt = post.teams || {};
  const ids = Object.keys(pt).sort((a, b) => (pt[b].p_ws || 0) - (pt[a].p_ws || 0));
  if (!ids.length) return BP.muted('Path chances arrive with the bracket simulation.');
  const rows = ids.map(t => {
    const x = pt[t], nx = x.next || null, m = ws.probs[t];
    return [{ v: x.seed, html: '<span class="muted-inline">' + esc(x.league || '') + '</span> ' + esc(x.seed || '') },
      { v: BP.teamName(t), html: BP.teamLink(t, { level: L }) },
      { v: x.p_ds, html: x.p_ds >= 0.9995 ? '<span class="odds-done">✓</span>' : BP.pct(x.p_ds, 0), align: 'right' },
      { v: x.p_lcs, html: BP.pct(x.p_lcs, 0), align: 'right' },
      { v: x.p_pennant, html: BP.pct(x.p_pennant, 1), align: 'right' },
      { v: x.p_ws, html: BP.probCell(x.p_ws, BP.teamColour(t), 0.4), align: 'right' },
      { v: m, html: isNum(m) ? '<span class="qk-muted">' + BP.pct(m, 1) + '</span>' : '—', align: 'right' },
      { v: nx && nx.if_win ? nx.if_win.p_ws : null, html: nx && nx.if_win ? BP.pct(nx.if_win.p_ws, 1) + ' <span class="muted-inline">/</span> ' + BP.pct((nx.if_loss || {}).p_ws, 1) : '—', align: 'right', cls: 'hide-sm',
        title: 'World Series probability if they win / lose their next game' }];
  });
  return BP.tableHTML([{ label: 'Seed' }, { label: 'Team' }, { label: 'DS', align: 'right', title: 'Reach the Division Series' }, { label: 'LCS', align: 'right' },
    { label: 'Pennant', align: 'right' }, { label: 'World Series', align: 'right' }, { label: 'Market', align: 'right', title: 'The de-vigged World Series market, for reference' },
    { label: 'Next game: win / lose', align: 'right', cls: 'hide-sm' }], rows, { compact: true }) +
    (ws.sources.length ? '<div class="section-note">Market (reference): ' + esc(BP.ui.srcName(ws.sources)) + ', de-vigged across the field.</div>' : '');
}

function seriesDetail(s, games, L) {
  if (!s) return BP.muted('Click a series in the bracket to see its games.');
  const t = (s.teams || []).map(String);
  const gl = (s.games || []).map(id => games[id] || { gpk: id }).filter(c => !BP.notNeeded(c));
  const nx = s.next;
  const st = seriesState(s);
  return '<div class="sd-head"><b>' + esc((s.league && BP.roundKey(s.round) !== 'WS' ? s.league + ' ' : '') + BP.roundLabel(BP.roundKey(s.round))) + '</b> · ' +
    BP.teamLink(t[0], { level: L }) + ' <b>' + esc((s.wins || [])[0]) + '-' + esc((s.wins || [])[1]) + '</b> ' + BP.teamLink(t[1], { level: L }) +
    (st.done ? ' · <span class="edge-pos">' + esc(BP.teamShort(st.winner)) + ' won</span>' : (s.p ? ' · our chance ' + esc(BP.teamAbbr(t[0])) + ' ' + BP.pct(s.p[0], 0) : '')) + '</div>' +
    '<div class="bp-gc-grid">' + gl.map(c => (c && c.home ? BP.gameCard(c, { level: L, date: true, compact: false }) : '<a class="gc" href="' + BP.gameHref(c.gpk, L) + '">Game ' + esc(c.gpk) + '</a>')).join('') +
    (nx && !(s.games || []).some(g => String(g) === String(nx.gpk)) && games[nx.gpk] ? BP.gameCard(games[nx.gpk], { level: L, date: true }) : '') + '</div>';
}

function render(el, params) {
  const L = 'mlb', S = params.season;
  const idx = BP.index() || {};
  el.innerHTML = QK.sectionHead({ kicker: 'Postseason · MLB ' + S, title: 'The bracket', sub: 'Our chance in every series from simulating the bracket, and every team’s path to the World Series.',
    actions: '<a class="qk-btn" href="' + BP.href('standings', L, S) + '">Standings</a><a class="qk-btn" href="#/markets">Forecast board</a>' }) + '<div id="ps-body">' + QK.skeleton('card', 2) + '</div>';
  return BP.loadAll([BP.ypath('season.json', L, S), BP.marketsPath(S), BP.marketsPath(S), BP.ypath('schedule.json', L, S)]).then(arr => {
    if (!el.isConnected) return;
    const season = BP.ok(arr[0]) ? arr[0] : null;
    const mk = BP.ok(arr[1]) ? arr[1] : (BP.ok(arr[2]) ? arr[2] : null);
    const post = postOf(season, S === BP.currentSeason(L) ? idx.postseason : null);
    const body = document.getElementById('ps-body');
    if (!post || (!(post.series || []).length && !Object.keys(post.teams || {}).length)) {
      body.innerHTML = BP.card('Postseason', '', season && season.postseason && season.postseason.available === false ? BP.notBuilt('The bracket', season.postseason) : BP.muted('The ' + S + ' bracket is not set yet. Until it is, our playoff chances live on the <a href="' + BP.href('standings', L, S) + '">standings page</a>.'));
      return;
    }
    const games = {};
    const sched = arr[3] && Array.isArray(arr[3].games) ? arr[3].games : [];
    sched.forEach(g => { if (g && g.gpk) games[g.gpk] = g; });
    [].concat(idx.today || [], idx.recent || [], idx.upcoming || []).forEach(g => { if (g && g.gpk) games[g.gpk] = g; });
    const ws = futureMap(mk, /^ws|world/);
    const list = BP.charts.seriesList(post);
    const live = list.filter(s => !seriesState(s).done);
    let sel = live.find(s => (s.games || []).length) || live[0] || list[list.length - 1] || null;
    body.innerHTML = BP.card('Bracket', esc(post.round ? 'now: ' + BP.roundLabel(post.round) : '') + ' · click a series for its games', '<div id="ps-bk"></div><div id="ps-sd" class="pad0"></div>') +
      '<div class="grid-2"><div>' + BP.card('World Series chances', 'our chance; the grey tick is the market, for reference', '<div id="ps-ws"></div>') + '</div><div>' +
        BP.card('Series', 'wins and our chance to win each series', seriesTable(list, games, L, post.sims)) + '</div></div>' +
      BP.card('Path chances', 'each team’s chance to reach every round', pathTable(post, ws, L)) +
      BP.card('How the bracket is simulated', '', '<div class="mk-explain">' +
        '<p><b>Format.</b> Six teams per league: three division winners and three wild cards. Seeds 1 and 2 (the best division winners) skip the Wild Card Series. The Wild Card Series is best of three, all at the higher seed; the Division Series best of five (2-2-1); the League Championship Series and the World Series best of seven (2-3-2). Seed 1 meets the winner of 4 v 5; seed 2 the winner of 3 v 6. No reseeding.</p>' +
        '<p><b>Simulation.</b> Every remaining game is drawn from the game model\'s probabilities between the two teams (lineups, the rotation in order, the bullpen, home field), with a shared team-strength shock per simulation so a hot team stays hot. The next game of each live series uses our full game forecast with the announced starters.' + (post.sims ? ' ' + BP.int(post.sims) + ' brackets.' : '') + '</p>' +
        '<p><b>What the next game is worth.</b> The win / lose columns rerun the bracket with the next game fixed each way, so the gap between them is how much that single game moves the World Series chances.</p>' +
        '<p><b>Markets.</b> Series, pennant and World Series numbers from Kalshi and Polymarket, de-vigged, are shown as a grey reference beside ours. For information and entertainment only. <a href="#/disclaimer">Disclaimer &amp; terms</a>.</p></div>');
    const drawSel = () => {
      document.getElementById('ps-sd').innerHTML = seriesDetail(sel, games, L);
      document.querySelectorAll('#ps-bk .bk-series').forEach(x => x.classList.toggle('sel', !!sel && x.getAttribute('data-sid') === String(sel.id)));
    };
    BP.charts.mlbBracket(document.getElementById('ps-bk'), post, { level: L, onSeries: s => { if (s) { sel = s; drawSel(); } } });
    drawSel();
    const pt = post.teams || {};
    document.getElementById('ps-ws').innerHTML = QK.chances(Object.keys(pt).filter(t => isNum(pt[t].p_ws) && pt[t].p_ws > 0.0005).map(t => ({ label: BP.teamName(t), p: pt[t].p_ws, market: isNum(ws.probs[t]) ? ws.probs[t] : null, color: (BP.teamInfo(t) || {}).colour, href: BP.teamHref(t, L, S), mark: BP.ui.team(t, L, S) })),
      { limit: 12, marketName: 'Market (' + (BP.ui.srcName(ws.sources) || 'reference') + ')' });
    BP.sortable(body);
    BP.setMeta(post.sims ? BP.int(post.sims) + ' bracket simulations' : '');
  });
}

BP.route('postseason', render);
})(window.BP);
