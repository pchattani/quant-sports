/* The Quant Rink — Fantasy (#/fantasy?tab=board|tools).
 *
 * Board (Design System 2.0): stat tiles, this week's picks (adds, buy low, sell high, streamers, breakouts), the rest-of-season leaders,
 * schedule strength for the next four weeks (games per club and week), the rankings with position filters and
 * the backtest. Tools: the pre-redesign fantasy page (scoring weights, categories, weekly planner, goalie starts).
 *
 * Reads <S>/fantasy.json (current season). Points use our default weights (fantasy.json "points"). */
(function (RK) {
'use strict';

const U = RK.ui, esc = RK.esc, isNum = RK.isNum;
const KIND_ORDER = ['Add', 'Breakout', 'Buy low', 'Sell high', 'Stream', 'Drop'];

function board(node) {
  const S = RK.currentSeason();
  node.innerHTML = QK.skeleton('lines', 8);
  return RK.loadYear('fantasy.json', S).then(f => {
    if (!U.alive(node)) return;
    if (!RK.ok(f)) { node.innerHTML = U.card2('Fantasy', '', QK.empty('Not built yet', RK.reason(f))); return; }
    const rows = U.rowsOf(f);
    const top = rows.slice().sort((a, b) => (a.rank || 999) - (b.rank || 999));
    const picks = (f.picks || []).slice().sort((a, b) => KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind));
    const bt = (f.backtest || {}).pts || {};
    const sw = bt.S_week || {};
    const wk = f.weeks || [];
    const add = picks.find(p => p.kind === 'Add');
    const k = [
      top[0] ? { label: 'No. 1 for the rest of the season', value: RK.surnameOf(top[0].name) + ' ' + U.f(top[0].ros, 0), unit: 'pts', signal: true, href: RK.playerHref(top[0].id), sub: 'our projection · ' + RK.teamAbbr(top[0].team), tip: 'Projected fantasy points for the rest of the season, our default scoring' } : null,
      add ? { label: 'Top add', value: add.name, text: true, href: RK.playerHref(add.id), sub: add.why || '' } : null,
      wk[0] ? { label: 'This week', value: RK.fmtDate(wk[0][0], { year: false, weekday: false }) + '–' + RK.fmtDate(wk[0][1], { year: false, weekday: false }), text: true, sub: 'four weeks planned ahead' } : null,
      sw.model ? { label: 'How good the weekly projection is', value: U.f(sw.model[0], 3), sub: sw.std ? 'points a game off, v ' + U.f(sw.std[0], 3) + ' for season-to-date' : '', tip: 'Mean absolute error of fantasy points per game over the next week, on five past seasons (lower is better)' } : null
    ];
    const weekCols = wk.map((w, i) => 'Wk ' + (i + 1));
    const teams = Object.keys(f.teams || {}).sort((a, b) => {
      const s = t => ((f.teams[t] || {}).weeks || []).reduce((x, w) => x + (w[0] || 0), 0);
      return s(b) - s(a) || a.localeCompare(b);
    });
    node.innerHTML = '<div class="rk-kpis">' + QK.stats(k) + '</div>' +
      '<div class="qk-grid"><div class="qk-span-5">' + U.card2('This week\'s picks', 'From our projections, ice time and luck model', picks.length ? picks.map(p => '<div class="rk-pick"><span class="qk-badge' + (p.kind === 'Add' || p.kind === 'Breakout' ? ' accent' : '') + '" style="flex:none;min-width:70px;justify-content:center">' + esc(p.kind) + '</span><div style="min-width:0">' + U.playerEnt(p.id, p.name, p.team, p.pos) + '<div class="why">' + esc(p.why || '') + '</div></div></div>').join('') : QK.empty('No picks this week'), { flush: true }) + '</div>' +
      '<div class="qk-span-7">' + U.card2('Rest-of-season leaders', 'Projected fantasy points for the rest of the season (our default scoring)', U.chart('fy-top', 470, 'Projected rest-of-season points')) + '</div></div>' +
      '<section class="qk-section"><div class="qk-grid"><div class="qk-span-5">' + U.card2('Schedule: games per week', 'Clubs with more games give their players more chances; sorted by games in the four weeks', U.chart('fy-wk', Math.max(400, teams.length * 18 + 60), 'Games per club and week')) + '</div>' +
      '<div class="qk-span-7">' + U.card2('Rankings', 'Rest-of-season value over replacement at the position; filter by position', '<div class="qk-chips" id="fy-pos" role="group" aria-label="Position" style="padding:0 0 10px">' +
        ['All', 'C', 'L', 'R', 'D', 'G'].map((p, i) => '<button type="button" class="qk-chip" aria-pressed="' + (i === 0) + '" data-value="' + p + '">' + p + '</button>').join('') + '</div><div id="fy-tab"></div>') + '</div></div></section>' +
      (f.note ? '<p class="rk-note">' + esc(f.note) + '</p>' : '');
    const t20 = top.slice(0, 20);
    QKC.bar('#fy-top', { cats: t20.map(r => r.name + ' (' + r.pos + ')'), series: [{ name: 'Points', data: t20.map(r => r.ros) }], horizontal: true, labels: true, fmt: x => U.f(x, 0), colors: t20.map(r => RK.teamColourRaw(r.team)), hrefs: t20.map(r => RK.playerHref(r.id)), labelWidth: 150, valName: 'Projected fantasy points' });
    if (teams.length && wk.length) {
      const data = [];
      teams.forEach((t, yi) => ((f.teams[t] || {}).weeks || []).forEach((w, xi) => data.push([xi, yi, w[0] || 0])));
      QKC.heatmap('#fy-wk', { x: weekCols, y: teams, data: data, fmt: v => String(Math.round(v)), xName: 'Week', yName: 'Club' });
    }
    const draw = sel => {
      const p = (sel && sel[0]) || 'All';
      const list = top.filter(r => p === 'All' || r.pos === p).slice(0, 150);
      QK.leaderboard(node.querySelector('#fy-tab'), { dense: true, maxHeight: 520, sort: { key: 'rank', dir: 'asc' }, rowHref: r => RK.playerHref(r.id), columns: [
        { key: 'rank', label: 'Rk', num: true }, { key: 'name', label: 'Player', type: 'entity', mark: r => U.team(r.team), href: r => RK.playerHref(r.id), sub: 'pos' },
        { key: 'inj', label: 'Status', sort: false, fmt: v => (v && v[0] ? '<span class="rk-inj">' + esc(v[0]) + '</span>' : '') },
        { key: 'ros', label: 'RoS pts', type: 'bar', fmt: v => U.f(v, 0), tip: 'Projected fantasy points for the rest of the season' }, { key: 'pts_pg', label: 'Pts/G', num: true, fmt: v => U.f(v, 2) },
        { key: 'vor', label: 'VOR', num: true, fmt: v => U.f(v, 0), tip: 'Points over a replacement player at the position' }, { key: 'pre_rank', label: 'Pre', num: true, tip: 'Rank at the start of the season' },
        { key: 'flags', label: 'Flags', sort: false, fmt: v => (v || []).map(x => '<span class="qk-badge">' + esc(x) + '</span>').join(' ') }], rows: list });
    };
    draw(['All']);
    QK.chips(node.querySelector('#fy-pos'), draw, false);
  });
}

function page(el, params, state) {
  const tab = U.tab(params, ['board', 'tools'], 'board');
  const body = U.section(el, { section: 'fantasy', title: 'Fantasy', sub: 'Rest-of-season and weekly projections for points leagues and categories, the picks of the week, schedule strength and goalie starts.',
    tabs: [{ key: 'board', label: 'Board', href: '#/fantasy' }, { key: 'tools', label: 'Rankings and tools: scoring, categories, weekly planner, goalie starts', href: '#/fantasy?tab=tools' }], active: tab });
  if (tab === 'tools') return U.legacy('fantasy', body, params, state);
  return board(body);
}

RK.page('fantasy', page);
})(window.RK);
