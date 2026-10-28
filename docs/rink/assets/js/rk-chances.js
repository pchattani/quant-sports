/* The Quant Rink — Standings › Chances (one tab for the season simulation, round 9, 28 Oct 2026) and Model › Our
 * forecasts v the market.
 *
 * Chances (#/standings?tab=chances; the old ?tab=odds, ?tab=markets and ?tab=lottery land here):
 *   view=chances (default): the season-simulation boards as bars in team colours: the Stanley Cup, reaching the Final,
 *     the division, the Presidents' Trophy and a playoff spot; then where each club finishes (the 90% range of
 *     projected points by conference) and one club's final-points distribution (the histogram, the playoff line);
 *   view=lottery: the draft lottery, rebuilt (headline number, chart, table, explain strip): our chance of the first
 *     pick for each club, the expected pick, and each club's pick distribution as a heat table.
 * Our forecasts v the market (#/model?tab=market; #/markets redirects): our season chances beside the prediction
 *   markets' for the Cup, the conference, the division, the Presidents' Trophy and the playoffs, as a dumbbell per
 *   question and a table. The market is a quiet reference here, the one page where it sits beside ours.
 * Reads <S>/season.json (sim.teams, lottery) and <S>/markets.json (futures). */
(function (RK) {
'use strict';

const U = RK.ui, esc = RK.esc, isNum = v => typeof v === 'number' && isFinite(v);
const Q = [['p_cup', 'Stanley Cup', 'Who lifts the Cup?', 'Our chance of winning the Stanley Cup.'], ['p_conf', 'Reach the Final', 'Who wins the conference?', 'Our chance of winning the conference and reaching the Stanley Cup Final.'],
  ['p_div', 'Division', 'Who wins the division?', 'Our chance of finishing first in the division.'], ['p_playoffs', 'Playoffs', 'Who makes the playoffs?', 'Our chance of a playoff spot: the top three in each division and two wild cards a conference.'],
  ['p_pres', 'Presidents’ Trophy', 'Who has the best record?', 'Our chance of the most points in the league.']];

function simRows(d) {
  const sim = (d && d.sim && d.sim.teams) || {};
  const rows = RK.seasonRows(d), by = {};
  rows.forEach(r => { by[r.team] = r; });
  return Object.keys(sim).map(t0 => { const t = RK.canonTeam(t0); return Object.assign({ team: t, row: by[t] || {} }, sim[t0]); });
}
function chancesView(node, d, S) {
  const L = simRows(d), n = (d.sim || {}).n || 20000;
  if (!L.length || !L.some(r => isNum(r.p_playoffs))) { node.innerHTML = QK.empty('No simulation for ' + RK.seasonLabel(S), Number(S) === Number(RK.currentSeason()) ? 'The season simulation has not run yet.' : 'This season is over: its final table, bracket and history are on the other tabs.'); return; }
  const board = q => QK.chances(L.filter(r => isNum(r[q[0]])).map(r => ({ label: RK.teamName(r.team), p: r[q[0]], href: RK.teamHref(r.team, S), mark: U.team(r.team), color: RK.teamColourRaw(r.team) })), { limit: q[0] === 'p_playoffs' || q[0] === 'p_div' ? 32 : q[0] === 'p_pres' ? 8 : 12, key: false, max: q[0] === 'p_playoffs' ? 1 : undefined });
  const top = k => L.filter(r => isNum(r[k])).sort((a, b) => b[k] - a[k])[0];
  const cup = top('p_cup'), pres = top('p_pres');
  const bubble = L.filter(r => isNum(r.p_playoffs) && r.p_playoffs > 0.35 && r.p_playoffs < 0.65).length;
  node.innerHTML = QK.stats([cup ? { label: 'Cup favourite', value: RK.teamAbbr(cup.team) + ' ' + U.pct(cup.p_cup, 0), signal: true, href: RK.teamHref(cup.team, S), sub: RK.teamName(cup.team) + ': ' + (cup.p_cup < 0.2 ? 'nobody is better than 1 in 5' : 'the clear favourite') } : null,
      pres ? { label: 'Best record', value: RK.teamAbbr(pres.team) + ' ' + U.pct(pres.p_pres, 0), href: RK.teamHref(pres.team, S), sub: 'our chance of the Presidents’ Trophy' } : null,
      { label: 'On the bubble', value: String(bubble), sub: 'clubs between 35% and 65% for a playoff spot' },
      { label: 'Simulated seasons', value: QK.fmt.num(n), sub: 'the rest of the schedule played out with our game model' }].filter(Boolean)) +
    QK.explain('<b>Is ' + (cup ? U.pct(cup.p_cup) : 'that') + ' a lot for the Cup?</b> For the favourite, yes. Sixteen clubs, four rounds of best-of-seven series: even the best team loses somewhere along the way most years. How past simulations did is on <a class="qk-link" href="#/model?tab=calibration">the Model page</a>.', { html: true }) +
    '<div class="qk-grid" style="margin-top:var(--sp-5)">' + Q.map(q => '<div class="qk-span-' + (q[0] === 'p_pres' ? 12 : 6) + '">' + U.card2(q[1], esc(q[3]), board(q)) + '</div>').join('') + '</div>' +
    '<section class="qk-section">' + QK.sectionHead({ kicker: 'Season simulation', title: 'Where they finish', sub: 'Each club’s points at the end of the regular season across the simulated seasons: the dot is the mean, the bar the range it lands in nine times out of ten.',
      actions: '<div class="qk-seg" id="ch-conf" role="group" aria-label="Conference"><button type="button" aria-pressed="true" data-value="Eastern">East</button><button type="button" aria-pressed="false" data-value="Western">West</button></div>' }) +
    U.card2('Projected full-season points', QK.fmt.num(n) + ' simulations of the rest of the season, from today’s points', U.chart('ch-range', 520, 'Projected full-season points with a 90% range')) + '</section>' +
    '<section class="qk-section">' + QK.sectionHead({ kicker: 'One club', title: 'Every way the season can end', sub: 'How often each final points total came up for one club across the simulated seasons, with the mean marked.',
      actions: '<select class="qk-select" id="ch-team" aria-label="Club">' + L.slice().sort((a, b) => RK.teamName(a.team).localeCompare(RK.teamName(b.team))).map(r => '<option value="' + esc(r.team) + '"' + (cup && r.team === cup.team ? ' selected' : '') + '>' + esc(RK.teamName(r.team)) + '</option>').join('') + '</select>' }) +
    U.card2('Final points', '<span id="ch-dist-s"></span>', U.chart('ch-dist', 300, 'Distribution of final points')) + '</section><div id="ch-sos-w"></div>';
  const range = c => {
    const rs = L.filter(r => (r.row.conference || RK.teamConf(r.team)) === c && isNum(r.pts_p05) && isNum(r.pts_p95)).sort((a, b) => (b.mean_pts || 0) - (a.mean_pts || 0));
    QKC.range('#ch-range', { rows: rs.map(r => ({ label: RK.teamName(r.team), lo: r.pts_p05, hi: r.pts_p95, mid: r.mean_pts, href: RK.teamHref(r.team, S), color: RK.teamColourRaw(r.team), sub: (isNum(r.row.pts) ? r.row.pts + ' points now · ' : '') + U.pct(r.p_playoffs) + ' to make the playoffs' })),
      fmt: v => U.f(v, 0), loName: '5th', hiName: '95th percentile', midName: 'Projected full-season points', valName: 'Points at season end (full season)', labelWidth: 150 });
  };
  range('Eastern');
  QK.seg(node.querySelector('#ch-conf'), range);
  const dist = t => {
    const r = L.filter(x => x.team === t)[0];
    if (!r || !r.points_dist) return;
    const ks = Object.keys(r.points_dist).map(Number).filter(isNum).sort((a, b) => a - b);
    node.querySelector('#ch-dist-s').textContent = RK.teamName(t) + ': mean ' + U.f(r.mean_pts, 1) + ' points, 90% between ' + U.f(r.pts_p05, 0) + ' and ' + U.f(r.pts_p95, 0) + ' · our playoff chance ' + U.pct(r.p_playoffs);
    QKC.mount('#ch-dist', T => {
      const xa = QKC.axis(T, { type: 'category', data: ks.map(String), split: false, line: true });
      xa.axisLabel.interval = 4;
      const ya = QKC.axis(T, { fmt: v => Math.round(v * 100) + '%' });
      const gB = 8 + QKC.nameAxis(xa, 'Final points', 'bottom'), gT = 14 + QKC.nameAxis(ya, 'Share of simulated seasons', 'side');
      const c = QK.color.team(RK.teamColourRaw(t));
      return { grid: { left: 8, right: 12, top: gT, bottom: gB, containLabel: true }, xAxis: xa, yAxis: ya,
        tooltip: QKC.tooltip(T, { trigger: 'axis', formatter: ps => '<b>' + esc(ps[0].name) + ' points</b>' + QKC.tipRow(c, 'Share of seasons', U.pct(ps[0].value, 1)) }),
        series: [{ type: 'bar', barCategoryGap: '8%', data: ks.map(x => r.points_dist[String(x)] || 0), itemStyle: { color: c },
          markLine: isNum(r.mean_pts) ? { silent: true, symbol: 'none', lineStyle: { color: T.volt, type: [4, 3] }, label: Object.assign(QKC.annot(T), { formatter: 'Mean ' + U.f(r.mean_pts, 1) }), data: [{ xAxis: String(Math.round(r.mean_pts)) }] } : undefined }] };
    }, { label: 'Final points distribution' });
  };
  if (RK.scheduleStrength && Number(S) === Number(RK.currentSeason())) RK.scheduleStrength(node.querySelector('#ch-sos-w'), S);
  const sel = node.querySelector('#ch-team');
  dist(sel.value);
  sel.addEventListener('change', () => dist(sel.value));
}

function lotteryView(node, d, S) {
  const Lt = d && d.lottery, T = (Lt && Lt.teams) || {};
  const sim = (d && d.sim && d.sim.teams) || {};
  const list = Object.keys(T).map(t0 => Object.assign({ team: RK.canonTeam(t0) }, T[t0])).filter(r => isNum(r.p_first));
  if (!list.length) { node.innerHTML = QK.empty('No lottery for ' + RK.seasonLabel(S), 'The draft-lottery chances come from the season simulation of the current season.'); return; }
  list.forEach(r => { const pd = r.pick_dist || []; r.exp = pd.length ? pd.reduce((s, p, i) => s + p * (i + 1), 0) / Math.max(1e-9, pd.reduce((s, p) => s + p, 0)) : null; r.inLot = pd.reduce((s, p) => s + p, 0); r.po = (sim[r.team] || {}).p_playoffs; });
  list.sort((a, b) => b.p_first - a.p_first);
  const fav = list[0], odds = Lt.odds || [];
  node.innerHTML = QK.stats([{ label: 'Lottery favourite', value: RK.teamAbbr(fav.team) + ' ' + U.pct(fav.p_first, 1), signal: true, href: RK.teamHref(fav.team, S), sub: RK.teamName(fav.team) + ': our chance of the first pick' },
      { label: 'Top three', value: U.pct(fav.p_top3, 0), sub: 'our chance ' + RK.teamShort(fav.team) + ' pick in the top three' },
      odds.length ? { label: 'Best odds in the draw', value: U.f(odds[0], 1) + '%', sub: 'for the club that finishes last, before the draw; a club can move up at most 10 places' } : null].filter(Boolean)) +
    QK.explain('<b>How it works.</b> The 16 clubs that miss the playoffs enter. Two draws decide the first two picks, weighted by the order of finish (the worst club ' + (odds.length ? U.f(odds[0], 1) + '%' : 'most') + '); the rest go in reverse order of points. Our chance mixes where each club finishes in the simulated seasons with the draw itself.', { html: true }) +
    '<div class="qk-grid" style="margin-top:var(--sp-5)"><div class="qk-span-5">' + U.card2('First overall pick', 'Our chance, every club with one', QK.chances(list.filter(r => r.p_first >= 0.001).map(r => ({ label: RK.teamName(r.team), p: r.p_first, href: RK.teamHref(r.team, S), mark: U.team(r.team), color: RK.teamColourRaw(r.team) })), { limit: 16, key: false })) + '</div>' +
    '<div class="qk-span-7">' + U.card2('Where each club picks', 'Share of simulated seasons ending with each pick, 1 to 16 (blank: never)', '<div id="lt-heat"></div>', { flush: true }) + '</div></div>';
  const n = 16, shade = p => (p >= 0.005 ? 'background:rgba(125,147,255,' + Math.min(0.85, 0.12 + 1.4 * p).toFixed(2) + ');color:' + (p > 0.3 ? '#000' : 'var(--ink-1)') : '');
  node.querySelector('#lt-heat').innerHTML = '<div class="qk-table-wrap"><table class="qk-table dense rk-lot"><thead><tr><th>Club</th><th class="num" data-tip="The expected pick if the club misses the playoffs">Exp.</th>' + Array.from({ length: n }, (_, i) => '<th class="num">' + (i + 1) + '</th>').join('') + '<th class="num" data-tip="Our playoff chance: a playoff club does not pick in the lottery">Playoffs</th></tr></thead><tbody>' +
    list.filter(r => r.inLot >= 0.01).sort((a, b) => (a.exp || 99) - (b.exp || 99)).map(r => '<tr><td>' + U.teamEnt(r.team, { abbr: true, season: S }) + '</td><td class="num">' + U.f(r.exp, 1) + '</td>' +
      Array.from({ length: n }, (_, i) => { const p = (r.pick_dist || [])[i] || 0; return '<td class="num" style="' + shade(p) + '" title="' + esc(RK.teamAbbr(r.team) + ', pick ' + (i + 1) + ': ' + U.pct(p, 1)) + '">' + (p >= 0.005 ? Math.round(p * 100) : '') + '</td>'; }).join('') +
      '<td class="num">' + U.pct(r.po, 0) + '</td></tr>').join('') + '</tbody></table></div>';
}

/* Standings › Chances */
RK.chancesTab = function (node, S, view) {
  node.innerHTML = QK.skeleton('lines', 8);
  return RK.loadYear('season.json', S).then(d => {
    if (!U.alive(node)) return;
    if (!RK.ok(d)) { node.innerHTML = QK.empty('Not built yet', RK.reason(d)); return; }
    const v = view === 'lottery' ? 'lottery' : 'chances';
    node.innerHTML = '<div class="qk-seg" id="ch-view" role="group" aria-label="Chances view" style="margin-bottom:var(--sp-4)"><button type="button" data-value="chances" aria-pressed="' + (v === 'chances') + '">Season chances</button><button type="button" data-value="lottery" aria-pressed="' + (v === 'lottery') + '">Draft lottery</button></div><div id="ch-body"></div>';
    const draw = x => {
      const b = node.querySelector('#ch-body');
      try { history.replaceState(null, '', RK.standingsHref(S) + '?tab=chances' + (x === 'lottery' ? '&view=lottery' : '')); } catch (e) { /* no history API */ }
      if (x === 'lottery') lotteryView(b, d, S); else chancesView(b, d, S);
    };
    draw(v);
    QK.seg(node.querySelector('#ch-view'), draw);
  });
};

/* Model › Our forecasts v the market */
RK.marketTab = function (node, S) {
  node.innerHTML = QK.skeleton('lines', 8);
  return RK.loadYear('markets.json', S).then(mk => {
    if (!U.alive(node)) return;
    const F = RK.ok(mk) ? (mk.futures || {}) : {};
    const QS = [['cup', 'Stanley Cup'], ['conference', 'Conference'], ['division', 'Division'], ['presidents', 'Presidents’ Trophy'], ['playoffs', 'Playoffs']].filter(q => (F[q[0]] || []).some(r => isNum(r.model) && isNum(r.market)));
    if (!QS.length) { node.innerHTML = QK.sectionHead({ kicker: 'Our forecasts v the market', title: 'Ours, beside the market' }) + QK.empty('No market to compare', 'The prediction markets have no season questions listed right now.'); return; }
    const src = (mk.sources && typeof mk.sources === 'object' ? Object.keys(mk.sources) : []).map(s => RK.srcLabel(s)).filter(Boolean).join(', ') || 'Kalshi and Polymarket';
    node.innerHTML = QK.sectionHead({ kicker: 'Our forecasts v the market', title: 'Ours, beside the market', sub: 'Our season chances next to the prediction markets’ (' + esc(src) + ', each turned into a chance with the margin removed). The market is a reference, not our forecast: where the two differ, neither is necessarily right.', html: true,
      actions: '<div class="qk-seg" id="mk-q" role="group" aria-label="Question">' + QS.map((q, i) => '<button type="button" data-value="' + q[0] + '" aria-pressed="' + (i === 0) + '">' + esc(q[1]) + '</button>').join('') + '</div>' }) +
      '<div class="qk-grid"><div class="qk-span-7">' + U.card2('Our chance and the market’s', '<span id="mk-s"></span>', U.chart('mk-db', 560, 'Our chance against the market')) + '</div>' +
      '<div class="qk-span-5">' + U.card2('Side by side', 'Every club the market lists', '<div id="mk-t"></div>', { flush: true }) + '</div></div>' +
      QK.explain('<b>How to read it.</b> Blue is ours, grey the market. A gap of a few points is normal: the market reacts to news within minutes (injuries, trades, goalies) while our numbers move with results and our ratings. How our forecasts have done over past seasons is on <a class="qk-link" href="#/model?tab=calibration">How we’re doing</a>.' + (mk.updated_at ? ' Market chances as of ' + esc(RK.fmtStamp(mk.updated_at)) + '.' : ''), { html: true });
    const draw = key => {
      const rows = (F[key] || []).filter(r => isNum(r.model) && isNum(r.market)).sort((a, b) => b.model - a.model);
      const show = rows.slice(0, key === 'playoffs' || key === 'division' ? 32 : 16);
      node.querySelector('#mk-s').textContent = (QS.filter(q => q[0] === key)[0] || [])[1] + ' · ' + rows.length + ' clubs listed';
      QKC.dumbbell('#mk-db', { rows: show.map(r => ({ label: RK.teamName(r.team), a: r.model, b: r.market, href: RK.teamHref(r.team, S) })), aName: 'Our chance', bName: 'Market', fmt: v => U.pct(v, v < 0.1 ? 1 : 0), min: 0, max: Math.min(1, Math.ceil(Math.max.apply(null, show.map(r => Math.max(r.model, r.market)).concat([0.1])) * 10) / 10), valName: 'Chance' });
      QK.leaderboard(node.querySelector('#mk-t'), { dense: true, rank: true, maxHeight: 560, rowHref: r => RK.teamHref(r.team, S), columns: [
        { key: 'name', label: 'Club', type: 'entity', mark: r => U.team(r.team), href: r => RK.teamHref(r.team, S) },
        { key: 'model', label: 'Ours', num: true, fmt: v => '<b class="rk-ours">' + U.pct(v, 1) + '</b>' },
        { key: 'market', label: 'Market', num: true, fmt: v => '<span class="qk-muted">' + U.pct(v, 1) + '</span>' },
        { key: 'diff', label: 'Ours − market', num: true, fmt: v => U.signed(100 * v, 1) + ' pts', tip: 'Our chance minus the market’s, in percentage points' }],
        rows: rows.map(r => ({ team: r.team, name: RK.teamShort(r.team), model: r.model, market: r.market, diff: r.model - r.market })) });
    };
    draw(QS[0][0]);
    QK.seg(node.querySelector('#mk-q'), draw);
  });
};
})(window.RK);
