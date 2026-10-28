/* The Quant Hardwood — Fantasy (#/<L>/fantasy).
 *
 * Board tab (new): headline numbers; our picks (core, breakouts, streamers, punt builds) with the reasons; the top
 * of the 9-category and points rankings with per-game projections; projected fantasy points against minutes;
 * games per team over the next fantasy weeks (a schedule heatmap); how the projections did in the walk-forward test.
 * Tools tab (?tab=tools): the pre-redesign page (any format and weights, punts, horizons, tiers, VORP by position,
 * buy-low / sell-high, waiver targets, streaming).
 * Data: <L>/<S>/fantasy.json (current season), <L>/fantasy_backtest.json. Our projections only: no platform data. */
(function (HW) {
'use strict';

const U = HW.ui, esc = HW.esc, isNum = HW.isNum;
const PICKS = { core: 'Core', points: 'Points leagues', breakouts: 'Breakouts', buy_low: 'Buy low', sell_high: 'Sell high', adds: 'Adds', drops: 'Drops', streamers: 'Streamers', punt_fg: 'Punt FG%', punt_ft: 'Punt FT%', punt_tov: 'Punt TO' };

function board(node, L) {
  const S = HW.currentSeason(L);
  return Promise.all([HW.load(HW.path('fantasy.json', L, S)), HW.load(HW.lpath('fantasy_backtest.json', L))]).then(a => {
    if (!U.alive(node)) return;
    const d = U.ok(a[0]) ? a[0] : null, bt = U.ok(a[1]) ? a[1] : null;
    if (!d) { node.innerHTML = U.empty('Not built yet', 'Fantasy projections for ' + HW.seasonLabel(L, S) + ' are not available.'); return; }
    const pgc = d.pg_cols || [];
    const rows = U.rowsOf(d).map(r => { const o = Object.assign({}, r); pgc.forEach((c, i) => { o['pg_' + c] = (r.pg || [])[i]; }); return o; });
    const byId = {}; rows.forEach(r => { byId[r.id] = r; });
    const preset = (d.presets || {}).standard || (d.presets || {})[Object.keys(d.presets || {})[0]];
    const fp = r => (preset ? Object.keys(preset.w).reduce((s, k) => s + (isNum(r['pg_' + k]) ? r['pg_' + k] * preset.w[k] : 0), 0) : null);
    rows.forEach(r => { r.fp = fp(r); });
    const top9 = rows.filter(r => isNum(r.rank9)).sort((x, y) => x.rank9 - y.rank9).slice(0, 25);
    const topP = rows.filter(r => isNum(r.fp)).sort((x, y) => y.fp - x.fp).slice(0, 15);
    const target = d.season_over ? HW.seasonLabel(L, d.target) : null;
    const kp = [];
    if (top9[0]) kp.push(({ label: '9-cat number one', value: top9[0].name, text: true, signal: true, href: HW.playerHref(L, top9[0].id), sub: HW.teamAbbr(L, top9[0].team) + ' · ' + U.f(top9[0].pg_pts, 1) + ' pts, ' + U.f(top9[0].pg_reb, 1) + ' reb, ' + U.f(top9[0].pg_ast, 1) + ' ast' }));
    if (topP[0]) kp.push(({ label: 'Points number one', value: topP[0].name, text: true, sub: U.f(topP[0].fp, 1) + ' fantasy points a game (' + esc(preset ? preset.label : 'standard') + ')' }));
    const br = ((d.picks || {}).breakouts || [])[0];
    if (br && byId[br[0]]) kp.push(({ label: 'Top breakout', value: byId[br[0]].name, text: true, sub: String(br[1] || '') }));
    const sm = bt && bt.summary && bt.summary.ros;
    if (sm && sm.ours) kp.push(({ label: 'Projection check', value: U.f(sm.ours.spearman, 2), sub: 'rank correlation, rest of season' + (sm.season_to_date ? ' (season to date ' + U.f(sm.season_to_date.spearman, 2) + ')' : ''), tip: 'Walk-forward backtest: Spearman correlation of projected and actual rest-of-season value' }));
    let h = (target ? '<div class="qk-note" style="margin-bottom:14px">The ' + esc(HW.seasonLabel(L, S)) + ' season is over: projections are for ' + esc(target) + '.</div>' : '') + '<div class="hw-kpis">' + QK.stats(kp) + '</div>';
    const pk = Object.keys(PICKS).filter(k => ((d.picks || {})[k] || []).length);
    if (pk.length) {
      h += '<section class="qk-section">' + U.head({ kicker: 'Our picks', title: 'Who to start, add and stash', sub: 'From our own projections; the reason is under each name.' }) + '<div class="hw-leaders">' + pk.map(k => '<div class="qk-card"><div class="qk-card-head"><div class="qk-card-title">' + esc(PICKS[k]) + '</div></div><div>' +
        d.picks[k].slice(0, 5).map(x => { const r = byId[x[0]] || {}; return '<div class="hw-pick"><div style="min-width:0">' + U.playerEnt(L, x[0], r.name, r.team, HW.teamAbbr(L, r.team) + (r.pos ? ' · ' + r.pos : '')) + '<div class="why">' + esc(x[1] || '') + '</div></div></div>'; }).join('') + '</div></div>').join('') + '</div></section>';
    }
    h += '<section class="qk-section">' + U.head({ kicker: 'Rankings', title: 'The top of the board', sub: '9-category rank (z-scores on per-game projections, no punts) and points rank. Change the format, punts and horizon in the tools.', actions: U.btnLink(HW.href(L, 'fantasy') + '?tab=tools', 'All formats and tools') }) + '' +
      '<div class="qk-card"><div id="fb-rank"></div></div></section>';
    h += '<div class="qk-grid hw-sec">' + U.card2('Fantasy points a game', (preset ? esc(preset.label) + ' scoring' : 'Standard scoring') + ', projected', U.chart('fb-pts', 24 * topP.length + 40, 'Fantasy points a game'), { cls: 'qk-span-6' });
    const tw = d.teams || {}, wk = d.weeks || [];
    const tids = Object.keys(tw).filter(t => (tw[t].weeks || []).length);
    if (tids.length && wk.length) h += U.card2('Games per week', 'Games each team plays in the coming fantasy weeks (more games, more stats)', U.chart('fb-wk', 18 * tids.length + 70, 'Games per week'), { cls: 'qk-span-6' });
    h += '</div>';
    node.innerHTML = h;
    top9.forEach(r => { r.sub = [HW.teamAbbr(L, r.team), r.pos, r.inj ? String(r.inj).split(' ')[0] : ''].filter(Boolean).join(' · '); });
    QK.leaderboard(document.getElementById('fb-rank'), { dense: true, maxHeight: 620, rows: top9, rowHref: r => HW.playerHref(L, r.id), columns: [
      { key: 'rank9', label: '9-cat', num: true }, { key: 'rankp', label: 'Pts', num: true },
      { key: 'name', label: 'Player', type: 'entity', sub: 'sub', mark: r => U.team(L, r.team), href: r => HW.playerHref(L, r.id) },
      { key: 'mpg', label: 'Min', type: 'bar', fmt: x => U.f(x, 1) },
      { key: 'pg_pts', label: 'Pts', num: true, fmt: x => U.f(x, 1) }, { key: 'pg_reb', label: 'Reb', num: true, fmt: x => U.f(x, 1) }, { key: 'pg_ast', label: 'Ast', num: true, fmt: x => U.f(x, 1) },
      { key: 'pg_stl', label: 'Stl', num: true, fmt: x => U.f(x, 1) }, { key: 'pg_blk', label: 'Blk', num: true, fmt: x => U.f(x, 1) }, { key: 'pg_tpm', label: '3PM', num: true, fmt: x => U.f(x, 1) },
      { key: 'pg_tov', label: 'TO', num: true, fmt: x => U.f(x, 1) }, { key: 'xgp', label: 'Games', num: true, fmt: x => U.f(x, 0), tip: 'Projected games for the rest of the season' }] });
    QKC.bar('#fb-pts', { cats: topP.map(r => r.name), series: [{ name: 'Fantasy points', data: topP.map(r => Math.round(r.fp * 10) / 10) }], horizontal: true, labels: true, fmt: x => U.f(x, 1), colors: topP.map(r => U.tcol(L, r.team)), hrefs: topP.map(r => HW.playerHref(L, r.id)), labelWidth: 140, valName: 'Fantasy points a game', catName: 'Player' });
    if (document.getElementById('fb-wk')) {
      const nW = Math.min(wk.length, (tw[tids[0]].weeks || []).length);
      const order = tids.slice().sort((a1, b1) => tw[b1].weeks.slice(0, nW).reduce((s, w) => s + (w[0] || 0), 0) - tw[a1].weeks.slice(0, nW).reduce((s, w) => s + (w[0] || 0), 0));
      const data = [];
      order.forEach((t, yi) => tw[t].weeks.slice(0, nW).forEach((w, xi) => data.push([xi, yi, w[0] || 0])));
      QKC.heatmap('#fb-wk', { x: wk.slice(0, nW).map(w => HW.fmtDate(w[0], { year: false, weekday: false })), y: order.map(t => HW.teamAbbr(L, t)), data: data, fmt: x => String(Math.round(x)), xName: 'Week starting', yName: 'Team' });
    }
    HW.setMeta(d.updated_at ? 'Projections ' + esc(HW.fmtStamp(d.updated_at)) : '');
  });
}

/* round 9: WNBA Fantasy is hidden in the off-season (no nav entry, core.js updateHeader); the route says when it is back */
HW.fantasyHidden = L => L === 'wnba' && HW.phase(L) === 'offseason';
function render(el, params) {
  const L = U.L(params), S = U.S(params);
  if (HW.fantasyHidden(L)) {
    el.innerHTML = U.secHead('Fantasy', '', null, null, U.kicker(L, HW.currentSeason(L))) +
      '<div class="qk-card hw-offcard"><div class="qk-card-body">' + QK.sectionHead({ kicker: 'WNBA off-season', title: 'Fantasy returns in May', sub: 'Our WNBA projections, rankings and picks come back with the new season’s rosters, before tip-off in May. Until then, the NBA board is live.' }) +
      '<p class="hw-flex">' + U.btnLink(HW.href('nba', 'fantasy'), 'NBA fantasy') + U.btnLink(HW.href(L, 'scout'), 'WNBA Scouting Room') + '</p></div></div>';
    return null;
  }
  const tab = U.tab(params, ['board', 'tools'], 'board');
  const body = U.section(el, { title: 'Fantasy', kicker: U.kicker(L, HW.currentSeason(L)), sub: 'Projections per game, for the rest of the season and the next fantasy weeks, from our own models: rankings, picks, schedule and streaming.',
    tabs: U.tabs(L, 'fantasy', [['board', 'Board', false], ['tools', 'Rankings & tools', false]], S), active: tab });
  if (tab === 'board') return board(body, L);
  return U.legacy('fantasy', body, params);
}

HW.page('fantasy', render);
})(window.HW);
