/* The Quant Rink — the section pages of the redesigned IA (October 2026).
 *
 *   #/standings[/<S>]?tab=  table (new: wild card / divisions / league with odds, projected points range) · odds ·
 *                           ratings · lottery (the pre-redesign standings views) · bracket (playoffs) · markets · history
 *   #/teams?tab=            clubs (new: tiles by division, offence v defence chart) · stats (the team catalogue)
 *   #/players?tab=          leaders (new, with sample floors, and a search) · skaters · goalies · lines · awards (new) · boards
 *   #/lab?tab=              lab · compare            #/compare/<a>/<b> renders inside Lab
 *   #/model?tab=            methodology · calibration · glossary · terms
 *                           #/glossary/<key> and #/methodology/<part> render inside Model
 * Old routes (#/skaters, #/playoffs, #/markets, #/calibration ...) are redirected by core.js (REDIRECTS). */
(function (RK) {
'use strict';

const U = RK.ui, esc = RK.esc, isNum = RK.isNum;

/* ── standings ───────────────────────────────────────────────────────────── */
const ST_TABS = [['table', 'Standings'], ['odds', 'Playoff odds'], ['ratings', 'Ratings'], ['lottery', 'Draft lottery'], ['bracket', 'Bracket'], ['markets', 'Futures v market'], ['history', 'History']];

function stTable(rows, groups) {
  const head = '<tr><th class="num">#</th><th class="sticky-col">Club</th><th class="num">GP</th><th class="num">W</th><th class="num">L</th><th class="num">OTL</th><th class="num">PTS</th>' +
    '<th class="num">P%</th><th class="num qk-hide-sm">GF</th><th class="num qk-hide-sm">GA</th><th class="num">Diff</th><th class="num qk-hide-sm"><span data-tip="Share of 5v5 expected goals">xGF%</span></th>' +
    '<th class="num"><span data-tip="Our team rating: expected goal difference a game against an average club">Rating</span></th><th class="num">Playoffs</th><th class="num">Cup</th><th class="qk-hide-sm">L10</th><th class="qk-hide-sm">Strk</th></tr>';
  const tr = (r, i, cut) => '<tr' + (cut ? ' class="rk-cut"' : '') + '><td class="rank num">' + esc(i) + '</td><td class="sticky-col">' + U.teamEnt(r.team, { short: true }) + (r.clinch ? ' <span class="qk-badge" data-tip="Clinch mark">' + esc(r.clinch) + '</span>' : '') + '</td>' +
    '<td class="num">' + r.gp + '</td><td class="num">' + r.w + '</td><td class="num">' + r.l + '</td><td class="num">' + r.otl + '</td><td class="num"><b>' + r.pts + '</b></td>' +
    '<td class="num">' + RK.fmtVal(r.p_pct, '3') + '</td><td class="num qk-hide-sm">' + r.gf + '</td><td class="num qk-hide-sm">' + r.ga + '</td><td class="num ' + U.cls(r.diff) + '">' + U.signed(r.diff, 0) + '</td>' +
    '<td class="num qk-hide-sm">' + U.pct(r.xgf_pct, 1) + '</td><td class="num ' + U.cls(r.rating) + '">' + U.signed(r.rating, 2) + '</td>' +
    '<td class="num">' + (isNum(r.p_playoffs) ? U.pct(r.p_playoffs) : '—') + '</td><td class="num">' + (isNum(r.p_cup) ? U.pct(r.p_cup, 1) : '—') + '</td>' +
    '<td class="qk-hide-sm rk-num">' + (Array.isArray(r.l10) ? r.l10.join('-') : esc(r.l10 || '')) + '</td><td class="qk-hide-sm rk-num">' + esc(r.streak || '') + '</td></tr>';
  return groups.map(g => '<div class="rk-sec" style="margin-top:' + (g.first ? '0' : 'var(--sp-5)') + '"><div class="rk-day"><b>' + esc(g.title) + '</b>' + (g.sub ? '<span>' + esc(g.sub) + '</span>' : '') + '</div>' +
    '<div class="qk-card"><div class="qk-table-wrap"><table class="qk-table dense rk-st"><thead>' + head + '</thead><tbody>' +
    g.rows.map((r, i) => tr(r, g.label ? g.label(i) : i + 1, g.cut !== undefined && i === g.cut)).join('') + '</tbody></table></div></div></div>').join('');
}

function standingsNew(node, S) {
  node.innerHTML = QK.skeleton('lines', 8);
  return RK.loadYear('season.json', S).then(d => {
    if (!U.alive(node)) return;
    if (!RK.ok(d) || !((d.standings || {}).rows || []).length) { node.innerHTML = U.card2('Standings', '', QK.empty('Not built yet', RK.reason(d))); return; }
    const st = d.standings, rows = st.rows, by = {};
    rows.forEach(r => { by[r.team] = r; });
    const sim = (d.sim && d.sim.teams) || {};
    const wc = st.wild_card || {};
    let view = 'wc';
    node.innerHTML = '<div class="rk-flex" style="justify-content:space-between;margin-bottom:var(--sp-4)"><div class="qk-seg" id="st-view" role="group" aria-label="Standings view">' +
      [['wc', 'Wild card'], ['div', 'Divisions'], ['league', 'League']].map(v => '<button type="button" aria-pressed="' + (v[0] === view) + '" data-value="' + v[0] + '">' + v[1] + '</button>').join('') + '</div>' +
      '<span class="qk-sub">' + esc(RK.regGames(S)) + ' games · 2 points a win, 1 for an overtime or shootout loss</span></div><div id="st-body"></div>' +
      '<section class="qk-section"><div class="qk-section-head"><div><h2>Projected points</h2><div class="qk-sub">Simulated final points: the bar is the 90% range, the dot the mean, the tick today\'s points.</div></div>' +
      '<div class="qk-seg" id="st-conf" role="group" aria-label="Conference"><button type="button" aria-pressed="true" data-value="Eastern">East</button><button type="button" aria-pressed="false" data-value="Western">West</button></div></div>' +
      U.card2('Points range', d.sim && d.sim.n ? QK.fmt.num(d.sim.n) + ' simulations of the rest of the season' : '', U.chart('st-range', 520, 'Projected points range')) + '</section>' +
      '<p class="rk-note">Clinch marks: x playoff spot, y division, z conference, p Presidents\' Trophy, e eliminated. Ties: points %, regulation wins, regulation and overtime wins, then wins.' + (d.updated_at ? ' Updated ' + esc(RK.fmtStamp(d.updated_at)) + '.' : '') + '</p>';
    const draw = v => {
      view = v;
      let groups = [];
      if (v === 'wc') {
        ['Eastern', 'Western'].forEach(c => {
          const w = wc[c];
          if (!w) return;
          const divs = (st.divisions || []).filter(x => x.conference === c);
          divs.forEach((dv, k) => groups.push({ title: dv.division, sub: c + ' Conference · top three', rows: (dv.teams || []).filter(t => (w.leaders || []).indexOf(t) >= 0).map(t => by[t]).filter(Boolean), first: !groups.length }));
          groups.push({ title: c + ' wild card', sub: 'two places; the line marks the cut', rows: (w.wild_card || []).concat(w.chasers || []).map(t => by[t]).filter(Boolean), cut: (w.wild_card || []).length, label: i => (i < (w.wild_card || []).length ? 'WC' + (i + 1) : String(i + 1)) });
        });
      } else if (v === 'div') {
        (st.divisions || []).forEach((dv, k) => groups.push({ title: dv.division, sub: dv.conference + ' Conference', rows: (dv.teams || []).map(t => by[t]).filter(Boolean), cut: 3, first: k === 0 }));
      } else groups.push({ title: 'League', sub: 'all 32 clubs', rows: rows.slice().sort((a, b) => (a.league_rank || 99) - (b.league_rank || 99)), first: true });
      if (!groups.length) groups.push({ title: 'League', rows: rows, first: true });
      node.querySelector('#st-body').innerHTML = stTable(rows, groups);
    };
    draw('wc');
    QK.seg(node.querySelector('#st-view'), draw);
    const range = c => {
      const rs = rows.filter(r => r.conference === c).map(r => Object.assign({}, r, sim[r.team] || {})).filter(r => isNum(r.pts_p05) && isNum(r.pts_p95)).sort((a, b) => (b.mean_pts || 0) - (a.mean_pts || 0));
      if (!rs.length) { node.querySelector('#st-range').innerHTML = QK.empty('No simulation', 'The season simulation is not available for this season.'); return; }
      QKC.mount('#st-range', T => ({
        grid: { left: 8, right: 24, top: 10, bottom: 24, containLabel: true },
        xAxis: QKC.axis(T, { scale: true, name: 'Points', nameLocation: 'middle', nameGap: 26 }),
        yAxis: (function () { const a = QKC.axis(T, { type: 'category', data: rs.map(r => r.team), split: false, inverse: true }); a.axisLabel.color = T.ink2; return a; })(),
        tooltip: QKC.tooltip(T, { formatter: p => { const r = rs[p.dataIndex]; return '<b>' + esc(RK.teamName(r.team)) + '</b>' + QKC.tipRow(T.model, 'Mean', U.f(r.mean_pts, 1)) + QKC.tipRow(T.other, '90% range', r.pts_p05 + '–' + r.pts_p95) + QKC.tipRow(T.ink1, 'Now', String(r.pts)) + QKC.tipRow(T.market, 'Playoffs', U.pct(r.p_playoffs)); } }),
        series: [
          { type: 'custom', renderItem: (params, api) => {
            const y = api.value(0), a = api.coord([api.value(1), y]), b = api.coord([api.value(2), y]);
            const h = Math.max(6, api.size([0, 1])[1] * 0.42);
            return { type: 'rect', shape: { x: a[0], y: a[1] - h / 2, width: Math.max(2, b[0] - a[0]), height: h, r: h / 2 }, style: { fill: QKC.hexA(QK.color.ensure(RK.teamColourRaw(rs[params.dataIndex].team) || T.model, T.s1, 3), 0.45) } };
          }, data: rs.map((r, i) => [i, r.pts_p05, r.pts_p95]), encode: { y: 0, x: [1, 2] }, z: 1 },
          { type: 'scatter', symbolSize: 10, z: 3, data: rs.map((r, i) => ({ value: [r.mean_pts, i], href: RK.teamHref(r.team), itemStyle: { color: QK.color.ensure(RK.teamColourRaw(r.team) || T.model, T.s1, 3), borderColor: T.s1, borderWidth: 2 } })) }
        ]
      }), { label: 'Projected points range, ' + c });
    };
    range('Eastern');
    QK.seg(node.querySelector('#st-conf'), range);
  });
}

function standingsPage(el, params, state) {
  const S = params.season;
  const tab = U.tab(params, ST_TABS.map(t => t[0]), 'table');
  const base = RK.standingsHref(S);
  const tabs = ST_TABS.map((t, i) => ({ key: t[0], label: t[1], href: base + (i ? '?tab=' + t[0] : '') }));
  const nav = (S > RK.FIRST_SEASON ? '<a class="qk-btn" href="' + RK.standingsHref(S - 10001) + (tab !== 'table' ? '?tab=' + tab : '') + '">← ' + esc(RK.seasonLabel(S - 10001)) + '</a>' : '') +
    (S < RK.currentSeason() ? '<a class="qk-btn" href="' + RK.standingsHref(S + 10001) + (tab !== 'table' ? '?tab=' + tab : '') + '">' + esc(RK.seasonLabel(S + 10001)) + ' →</a>' : '');
  const body = U.section(el, { section: 'standings', title: 'Standings', sub: 'The table, playoff and Cup odds from simulating the rest of the season, the bracket and the futures markets.', tabs: tabs, active: tab });
  if (nav) el.querySelector('.rk-head').insertAdjacentHTML('beforeend', '<div class="rk-flex">' + nav + '</div>');
  if (tab === 'table') return standingsNew(body, S);
  if (tab === 'bracket') return U.legacy('playoffs', body, params, state);
  if (tab === 'markets') return U.legacy('markets', body, params, state);
  if (tab === 'history') return U.legacy('history', body, params, state);
  body.classList.add('rk-embed-std');
  return U.legacy('standings', body, params, state, { view: tab });
}

/* ── teams ───────────────────────────────────────────────────────────────── */
function teamsNew(node, S) {
  node.innerHTML = QK.skeleton('card', 4);
  return RK.loadYear('season.json', S).then(d => {
    if (!U.alive(node)) return;
    const rows = RK.ok(d) ? ((d.standings || {}).rows || []) : [];
    if (!rows.length) { node.innerHTML = QK.empty('Not built yet', RK.reason(d)); return; }
    const by = {}; rows.forEach(r => { by[r.team] = r; });
    const R = (d.ratings || {});
    const pts = rows.map(r => { const u = (R[r.team] || {}).units || {}; return { r: r, off: u.off5, def: u.def5 }; }).filter(x => isNum(x.off) && isNum(x.def));
    let h = '';
    if (pts.length) h += '<div class="qk-grid" style="margin-bottom:var(--sp-5)"><div class="qk-span-12">' + U.card2('Offence v defence', '5v5 expected goals for and against per 60 minutes; top right is best (the defence axis is flipped)', U.chart('tm-od', 420, 'Offence against defence')) + '</div></div>';
    (d.standings.divisions || []).forEach(dv => {
      h += '<div class="rk-day"><b>' + esc(dv.division) + '</b><span>' + esc(dv.conference) + ' Conference</span></div><div class="rk-mini-grid">' + (dv.teams || []).map(t => {
        const r = by[t] || {};
        const rt = isNum(r.rating) ? r.rating : 0;
        return '<a class="rk-teamtile" href="' + esc(RK.teamHref(t, S)) + '" style="--tc:' + esc(U.tcol(t)) + '"><div class="top">' + QK.teamMark(U.team(t)) + '<span class="nm">' + esc(RK.teamName(t)) + '</span><span class="rec">' + (isNum(r.pts) ? r.pts + ' pts' : '') + '</span></div>' +
          '<div class="row"><span>' + esc(RK.record ? RK.record(r.w, r.l, r.otl) : '') + ' · GP ' + (r.gp || 0) + '</span><span>Rating <b>' + U.signed(r.rating, 2) + '</b></span></div>' +
          '<div class="rk-bar" title="Playoff probability"><span style="width:' + Math.round((isNum(r.p_playoffs) ? r.p_playoffs : 0) * 100) + '%"></span></div>' +
          '<div class="row"><span>Playoffs</span><b>' + (isNum(r.p_playoffs) ? U.pct(r.p_playoffs) : '—') + '</b></div></a>';
      }).join('') + '</div>';
    });
    node.innerHTML = h;
    if (pts.length) {
      const mx = pts.reduce((s, p) => s + p.off, 0) / pts.length, my = pts.reduce((s, p) => s + p.def, 0) / pts.length;
      QKC.scatter('#tm-od', { points: pts.map(p => ({ x: p.off, y: p.def, name: RK.teamName(p.r.team), label: p.r.team, color: RK.teamColourRaw(p.r.team), href: RK.teamHref(p.r.team, S), size: 14 })),
        xName: 'xGF / 60 (5v5)', yName: 'xGA / 60', yFmt: v => v.toFixed(2), xFmt: v => v.toFixed(2), refX: mx, refY: my, labelAll: true, quadrants: ['Defend well, little attack', 'Best: attack and defend', 'Struggling', 'Attack, leak chances'] });
      const c = node.querySelector('#tm-od');
      if (c && c.__qkc) { const e = c.__qkc, b0 = e.build; e.build = (T, x) => { const o = b0(T, x); o.yAxis.inverse = true; return o; }; e.paint(); }
    }
  });
}
function teamsPage(el, params, state) {
  const S = params.season;
  const tab = U.tab(params, ['clubs', 'stats'], 'clubs');
  const body = U.section(el, { section: 'teams', title: 'Teams', sub: 'Every club: record, rating, playoff odds and how it plays. Open a club for its rating over time, current roster, strengths and needs, schedule and moves.',
    tabs: U.tabs('#/teams', [['clubs', 'Clubs'], ['stats', 'Team stats']], S), active: tab });
  if (tab === 'stats') return U.legacy('teams', body, params, state);
  return teamsNew(body, S);
}

/* ── players: leaders with sample floors, awards ────────────────────────── */
function floors(tg) {
  const n = Math.max(1, Number(tg) || 1);
  return { gp: Math.max(5, Math.ceil(0.5 * n)), toi5: Math.max(50, 7 * n), shots: Math.max(20, 3 * n), fo: Math.max(50, 12 * n), ggp: Math.max(3, Math.ceil(0.25 * n)), sa: Math.max(100, 25 * n) };
}
function leadersPage(node, S) {
  node.innerHTML = QK.skeleton('lines', 8);
  return Promise.all([RK.loadYear('skaters.json', S), RK.loadYear('goalies.json', S)]).then(res => {
    if (!U.alive(node)) return;
    const sk = RK.ok(res[0]) ? res[0] : null, gk = RK.ok(res[1]) ? res[1] : null;
    if (!sk) { node.innerHTML = QK.empty('Not built yet', RK.reason(res[0])); return; }
    const tg = Math.max(Number(sk.team_games) || 0, Number((gk || {}).team_games) || 0);
    const F = floors(tg);
    const P = Object.keys(sk.players || {}).map(id => Object.assign({ id: id }, sk.players[id]));
    const G = gk ? Object.keys(gk.players || {}).map(id => Object.assign({ id: id }, gk.players[id])) : [];
    const v = (p, k) => (p.values || {})[k];
    const board = (list, key, okFn, lower, n) => list.filter(p => isNum(v(p, key)) && (!okFn || okFn(p))).sort((a, b) => (lower ? v(a, key) - v(b, key) : v(b, key) - v(a, key))).slice(0, n || 10);
    const gpOK = p => (p.gp || 0) >= F.gp, t5 = p => (v(p, 'toi5') || 0) >= F.toi5, shOK = p => (v(p, 'sog') || 0) >= F.shots, foOK = p => (v(p, 'fo_taken') || 0) >= F.fo;
    const gOK = p => (p.gp || 0) >= F.ggp && (v(p, 'sa') || 0) >= F.sa;
    const B = [
      ['Points', P, 'p', null, x => String(x), 'all skaters'], ['Goals', P, 'g', null, x => String(x), 'all skaters'],
      ['Points / 60', P, 'p60', gpOK, x => U.f(x, 2), '≥ ' + F.gp + ' GP'], ['Rink value (GAR)', P, 'gar', null, x => U.f(x, 1), 'all skaters'],
      ['5v5 xGF%', P, 'xgf_pct', t5, x => U.pct(x, 1), '≥ ' + F.toi5 + ' min 5v5'], ['Goals above expected', P, 'gax', null, x => U.signed(x, 2), 'all skaters'],
      ['Shooting %', P, 'sh_pct', shOK, x => U.pct(x, 1), '≥ ' + F.shots + ' shots'], ['Faceoff %', P, 'fo_pct', foOK, x => U.pct(x, 1), '≥ ' + F.fo + ' faceoffs'],
      ['Save %', G, 'sv_pct', gOK, x => RK.fmtVal(x, '3'), '≥ ' + F.ggp + ' GP and ' + F.sa + ' shots'], ['GSAx', G, 'gsax', null, x => U.signed(x, 2), 'all goalies'],
      ['GSAx / 60', G, 'gsax60', gOK, x => U.signed(x, 3), '≥ ' + F.ggp + ' GP and ' + F.sa + ' shots'], ['Wins', G, 'w', null, x => String(x), 'all goalies']
    ];
    const fin = P.filter(p => (v(p, 'sog') || 0) >= F.shots && isNum(v(p, 'ixg')) && isNum(v(p, 'g')));
    node.innerHTML = '<div class="rk-flex" style="margin-bottom:var(--sp-4)"><input class="qk-input rk-search" id="pl-q" type="search" placeholder="Find a player…" aria-label="Find a player" autocomplete="off"><span class="qk-sub">Sample floors scale with the ' + tg + ' games each club has played: rates need ' +
      F.gp + ' games, ' + F.toi5 + ' 5v5 minutes, ' + F.shots + ' shots or ' + F.fo + ' faceoffs; goalie rates ' + F.ggp + ' games and ' + F.sa + ' shots against.</span></div><div id="pl-hits"></div>' +
      (fin.length ? U.card2('Finishing: goals against expected goals', 'Skaters with ≥ ' + F.shots + ' shots; above the line scores more than his chances suggest', U.chart('pl-fin', 400, 'Goals against expected goals')) : '') +
      '<div class="qk-grid" style="margin-top:var(--sp-5)">' + B.map((b, i) => {
        const r = board(b[1], b[2], b[3], false, 8);
        const mx = Math.max.apply(null, r.map(p => Math.abs(v(p, b[2]))).concat([1e-9]));
        return '<div class="qk-span-3">' + U.card2(b[0], esc(b[5]), r.length ? '<ul class="rk-list">' + r.map((p, j) => '<li><span class="n">' + (j + 1) + '</span>' + U.playerEnt(p.id, p.name, p.team) + '<span class="v">' + esc(b[4](v(p, b[2]))) + '</span></li>').join('') + '</ul>' : QK.empty('Nobody qualifies yet'), { flush: true }) + '</div>';
      }).join('') + '</div>';
    if (fin.length) {
      const top = fin.slice().sort((a, b) => v(b, 'g') - v(a, 'g')).slice(0, 160);
      const m = Math.max.apply(null, top.map(p => Math.max(v(p, 'g'), v(p, 'ixg'))));
      QKC.scatter('#pl-fin', { points: top.map(p => ({ x: v(p, 'ixg'), y: v(p, 'g'), name: p.name + ' · ' + RK.teamAbbr(p.team), label: (p.name || '').split(' ').slice(-1)[0], color: RK.teamColourRaw(p.team), href: RK.playerHref(p.id), size: 9 })),
        xName: 'Individual expected goals', yName: 'Goals', xFmt: x => x.toFixed(0), yFmt: x => x.toFixed(0), labelTop: 10, xMin: 0, yMin: 0, xMax: Math.ceil(m), yMax: Math.ceil(m) });
      const c = node.querySelector('#pl-fin');
      if (c && c.__qkc) { const e = c.__qkc, b0 = e.build; e.build = (T, x) => { const o = b0(T, x); o.series[0].markLine = { silent: true, symbol: 'none', lineStyle: { color: T.axis, type: [4, 4] }, label: { show: false }, data: [[{ coord: [0, 0] }, { coord: [Math.ceil(m), Math.ceil(m)] }]] }; return o; }; e.paint(); }
    }
    // search: every player this season (catalogues) and the career index
    const pool = P.concat(G).map(p => ({ id: p.id, name: p.name || '', team: p.team, pos: p.pos, gp: p.gp }));
    const inp = node.querySelector('#pl-q'), hits = node.querySelector('#pl-hits');
    const norm = s => String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
    inp.addEventListener('input', () => {
      const q = norm(inp.value.trim());
      if (q.length < 2) { hits.innerHTML = ''; return; }
      let list = pool.filter(p => norm(p.name).indexOf(q) >= 0);
      if (list.length < 8) {
        const seen = {}; list.forEach(p => { seen[p.id] = 1; });
        Object.keys(RK.NAMES).forEach(id => { const x = RK.NAMES[id]; if (!seen[id] && x && x.name && norm(x.name).indexOf(q) >= 0 && list.length < 24) list.push({ id: id, name: x.name, team: x.team, pos: x.pos, gp: null, old: true }); });
      }
      list = list.slice(0, 24);
      hits.innerHTML = U.card2('Players matching “' + esc(inp.value.trim()) + '”', list.length + ' shown', list.length ? '<ul class="rk-list">' + list.map(p => '<li>' + U.playerEnt(p.id, p.name, p.team, [p.pos, p.old ? 'career' : (isNum(p.gp) ? p.gp + ' GP' : '')].filter(Boolean).join(' · ')) + '</li>').join('') + '</ul>' : QK.empty('No player matches'), { flush: true });
    });
  });
}

function awardsPage(node, S) {
  node.innerHTML = QK.skeleton('lines', 6);
  return RK.loadYear('awards.json', S).then(a => {
    if (!U.alive(node)) return;
    if (!RK.ok(a)) { node.innerHTML = U.card2('Awards', '', QK.empty('Not built yet', RK.reason(a))); return; }
    const list = a.awards || [];
    const races = a.races || {}, boards = a.boards || {}, reasons = a.reasons || {}, winners = a.winners || {};
    const bc = a.board_cols || ['id', 'name', 'team', 'value'];
    node.innerHTML = '<div class="qk-grid">' + list.map(w => {
      const r = (races[w.key] || []).slice(0, 8);
      const b = (boards[w.key] || []).slice(0, 5);
      const win = winners[w.key];
      let body = '';
      if (win && win.length) body += '<div class="rk-note" style="margin:0 0 8px"><b>Winner:</b> ' + win.map(x => esc(x.name) + (x.team ? ' (' + esc(x.team) + ')' : '')).join(', ') + '</div>';
      if (r.length) body += U.chart('aw-' + w.key, Math.max(160, r.length * 26 + 20), w.name + ' odds');
      else body += '<div class="rk-note" style="margin:0 0 8px">' + esc(reasons[w.key] ? 'No model race yet: ' + reasons[w.key] + '.' : 'No model race yet.') + '</div>';
      if (b.length) body += '<div class="qk-kicker" style="margin:10px 0 4px">Leading the usual criteria</div><ul class="rk-list" style="margin:0 -16px">' + b.map((x, i) => { const o = {}; bc.forEach((k, j) => { o[k] = x[j]; }); return '<li><span class="n">' + (i + 1) + '</span>' + U.playerEnt(o.id, o.name, o.team) + '<span class="v">' + esc(isNum(o.value) ? (Number.isInteger(o.value) ? o.value : U.f(o.value, 2)) : '') + '</span></li>'; }).join('') + '</ul>';
      return '<div class="qk-span-6">' + U.card2(w.name, esc(w.desc || '') + (a.basis && a.basis[w.key] ? ' · ' + esc(a.basis[w.key] === 'clogit' ? 'model of past voting' : a.basis[w.key]) : ''), body) + '</div>';
    }).join('') + '</div>' + (a.model_note ? '<p class="rk-note">' + esc(a.model_note) + '</p>' : '');
    list.forEach(w => {
      const r = (races[w.key] || []).slice(0, 8);
      if (!r.length) return;
      QKC.bar('#aw-' + w.key, { cats: r.map(x => x.name), series: [{ name: 'Probability', data: r.map(x => x.p) }], horizontal: true, labels: true, fmt: v => U.pct(v, 1),
        colors: r.map(x => RK.teamColourRaw(RK.player(x.id).team)), hrefs: r.map(x => RK.playerHref(x.id)), labelWidth: 130 });
    });
  });
}

const PL_TABS = [['leaders', 'Leaders'], ['skaters', 'Skaters'], ['goalies', 'Goalies'], ['lines', 'Lines'], ['awards', 'Awards'], ['boards', 'All leaderboards']];
function playersPage(el, params, state) {
  const S = params.season;
  const tab = U.tab(params, PL_TABS.map(t => t[0]), 'leaders');
  const body = U.section(el, { section: 'players', title: 'Players', sub: 'Leaders with sample floors, every skater and goalie with percentiles, line combinations and the award races. Open a player for his season-by-season record, percentiles, value and shot map.',
    tabs: U.tabs('#/players', PL_TABS, S), active: tab });
  if (tab === 'leaders') return leadersPage(body, S);
  if (tab === 'awards') return awardsPage(body, S);
  if (tab === 'boards') return U.legacy('leaders', body, params, state);
  return U.legacy(tab, body, params, state);
}

/* ── lab and model ───────────────────────────────────────────────────────── */
function labPage(el, params, state) {
  const S = params.season;
  const tab = state.route === 'compare' ? 'compare' : U.tab(params, ['lab', 'compare'], 'lab');
  const body = U.section(el, { section: 'lab', title: 'Lab', sub: 'Build your own chart from any two metrics, or put two skaters, goalies or clubs side by side.',
    tabs: [{ key: 'lab', label: 'Chart builder', href: '#/lab' + (U.sq(S) ? '?' + U.sq(S) : '') }, { key: 'compare', label: 'Compare', href: '#/compare' + (U.sq(S) ? '?' + U.sq(S) : '') }], active: tab });
  return U.legacy(tab, body, params, state);
}
const MD_TABS = [['methodology', 'Methodology'], ['calibration', 'Calibration'], ['glossary', 'Glossary'], ['terms', 'Terms']];
function modelPage(el, params, state) {
  let tab = state.route === 'glossary' ? 'glossary' : state.route === 'methodology' ? 'methodology' : U.tab(params, MD_TABS.map(t => t[0]), 'methodology');
  if (tab === 'terms') { location.replace('#/disclaimer'); return; }
  const tabs = MD_TABS.map((t, i) => ({ key: t[0], label: t[1], href: t[0] === 'terms' ? '#/disclaimer' : '#/model' + (i ? '?tab=' + t[0] : '') }));
  const body = U.section(el, { section: 'model', title: 'Model', sub: 'How the models work, how well they have done, and what every number means.', tabs: tabs, active: tab });
  return U.legacy(tab, body, params, state);
}
RK.ui.modelTabs = active => U.tabsHTML(MD_TABS.map((t, i) => ({ key: t[0], label: t[1], href: t[0] === 'terms' ? '#/disclaimer' : '#/model' + (i ? '?tab=' + t[0] : '') })), active);

RK.page('standings', standingsPage);
RK.page('teams', teamsPage);
RK.page('players', playersPage);
RK.page('lab', labPage);
RK.page('compare', labPage);
RK.page('model', modelPage);
RK.page('glossary', modelPage);
RK.page('methodology', modelPage);
})(window.RK);
