/* The Quant Hardwood — section pages: Standings, Teams (list), Players (list), Lab and Model.
 *
 *   Standings (#/<L>/standings): Table (new: records, projected wins with the 90% range, playoff / play-in /
 *     title odds, clinching), Odds & ratings (seed distribution, win totals v market, rating paths, schedule
 *     difficulty: the pre-redesign season page), Bracket, Futures v market, History (champions).
 *   Teams (#/<L>/teams): tiles by conference with record, net rating and odds; offence v defence; Team stats tab
 *     (the full team catalogue).
 *   Players (#/<L>/players): Leaders (new: search, impact at both ends, boards with sample floors), Catalogue,
 *     Awards, All leaderboards.
 *   Lab (#/<L>/lab): Chart builder and Compare (#/<L>/compare/... opens here).
 *   Model (#/<L>/model): Methodology, Calibration, Glossary, Terms (#/glossary/<key>, #/methodology/<part> and
 *     #/disclaimer open here). */
(function (HW) {
'use strict';

const U = HW.ui, esc = HW.esc, isNum = HW.isNum;

// ── Standings ──────────────────────────────────────────────────────────────

function magic(s) {
  if (!s) return '';
  const cl = s.clinched || {}, el = s.eliminated || {}, mg = s.magic || {};
  if (el.postseason || el.playoffs) return '<span class="qk-badge" data-tip="Eliminated from the postseason">e</span>';
  const t = [];
  if (cl.top_seed) t.push('<span class="qk-badge accent" data-tip="Clinched the top seed">z</span>');
  else if (cl.division) t.push('<span class="qk-badge accent" data-tip="Clinched the division">y</span>');
  if (cl.postseason || cl.playoffs || cl.top6) t.push('<span class="qk-badge accent" data-tip="Clinched a playoff place">x</span>');
  if (t.length) return t.join(' ');
  const k = ['postseason', 'playoffs', 'top6'].find(x => isNum(mg[x]));
  return k ? '<span data-tip="Magic number for a playoff place">' + mg[k] + '</span>' : '';
}

function standingsTable(node, L, S, rows, sim, fmt, league) {
  const live = Object.keys(sim).length > 0;
  const pre = live && rows.every(r => !r.w && !r.l);
  if (pre) rows = rows.slice().sort((a, b) => ((sim[b.team] || {}).exp_w || 0) - ((sim[a.team] || {}).exp_w || 0));
  const hasPin = !!(fmt && fmt.playin);
  const direct = hasPin ? 6 : ((fmt && fmt.playoff_teams) || 8), last = hasPin ? 10 : direct;
  const data = rows.map((r, i) => {
    const s = sim[r.team] || {};
    return Object.assign({}, r, { seedN: pre ? i + 1 : (r.seed || i + 1), exp: s.exp_w, pp: s.p_playoffs, pin: s.p_playin, pc: s.p_conf, pt: s.p_title, s: s,
      home_w: (r.home || [])[0], away_w: (r.away || [])[0], l10_w: (r.l10 || [])[0] });
  });
  const cols = [
    { key: 'seedN', label: '#', num: true },
    { key: 'team', label: 'Team', sticky: true, fmt: v => U.teamEnt(L, v, { season: S }) },
    { key: 'w', label: 'W-L', num: true, fmt: (v, r) => HW.record(r.w, r.l) },
    { key: 'pct', label: 'Pct', num: true, fmt: v => (isNum(v) ? HW.fmtVal(v, '3') : '—') },
    { key: 'gb', label: 'GB', num: true, fmt: v => (isNum(v) ? (v === 0 ? '—' : U.f(v, 1)) : esc(v || '—')) },
    { key: 'home_w', label: 'Home', num: true, fmt: (v, r) => (r.home ? HW.record(r.home[0], r.home[1]) : '—') },
    { key: 'away_w', label: 'Away', num: true, fmt: (v, r) => (r.away ? HW.record(r.away[0], r.away[1]) : '—') },
    { key: 'l10_w', label: 'L10', num: true, fmt: (v, r) => (r.l10 ? HW.record(r.l10[0], r.l10[1]) : '—') },
    { key: 'streak', label: 'Strk', fmt: v => esc(v || '—') },
    { key: 'pd', label: 'Diff', num: true, fmt: v => U.sgnHTML(v, 0), tip: 'Points differential' }
  ];
  if (live) {
    cols.push({ key: 'exp', label: 'Proj W', num: true, tip: 'Projected wins (mean of the simulations) with the 90% range', fmt: (v, r) => (isNum(v) ? '<span data-tip="' + esc(U.f(r.s.w_p05, 0) + '–' + U.f(r.s.w_p95, 0) + ' (90% range)') + '">' + U.f(v, 1) + '</span>' : '—') });
    cols.push({ key: 'pp', label: 'Playoffs', num: true, fmt: (v, r) => HW.ui.probBar(v, U.tcol(L, r.team)), tip: 'Reach the playoffs proper' });
    if (hasPin) cols.push({ key: 'pin', label: 'Play-in', num: true, fmt: v => U.pct(v), tip: 'Finish in the play-in places' });
    if (!league) cols.push({ key: 'pc', label: 'Conf', num: true, fmt: v => U.pct(v), tip: 'Win the conference' });
    cols.push({ key: 'pt', label: 'Title', num: true, fmt: v => '<b>' + U.pct(v) + '</b>' });
    cols.push({ key: 'mg', label: 'Clinch', sort: false, fmt: (v, r) => magic(r.s) });
  }
  QK.table(node, { columns: cols, rows: data, dense: true });
  // playoff and play-in cut lines (in seed order only)
  const trs = node.querySelectorAll('tbody tr');
  if (trs[direct]) trs[direct].classList.add('hw-cut');
  if (hasPin && trs[last]) trs[last].classList.add('hw-cut2');
}

function standingsTab(node, L, S, params) {
  return Promise.all([HW.load(HW.path('season.json', L, S)), HW.load(HW.lpath('history.json', L))]).then(arr => {
    if (!U.alive(node)) return;
    const season = U.ok(arr[0]) ? arr[0] : null;
    if (!season) { node.innerHTML = U.empty('Not built yet', 'The season payload for ' + HW.seasonLabel(L, S) + ' is not available.'); return; }
    const sim = HW.simTeams(season), st = season.standings || {}, fmt = season.format || {};
    const confs = Object.keys(st).filter(c => (st[c] || []).length).sort();
    const leagueWide = fmt.seeding === 'league';
    const all = () => { const list = []; confs.forEach(c => (st[c] || []).forEach(r => list.push(r)));
      return list.sort((a, b) => (leagueWide && isNum(a.seed) && isNum(b.seed) ? a.seed - b.seed : 0) || (b.pct || 0) - (a.pct || 0) || (b.w || 0) - (a.w || 0)).map((r, i) => Object.assign({}, r, { seed: leagueWide ? r.seed : i + 1 })); };
    const views = confs.map(c => [c, c]).concat(confs.length > 1 ? [['__all', 'League']] : []);
    const first = leagueWide && confs.length > 1 ? '__all' : (views[0] || [])[0];
    const hist = U.ok(arr[1]) ? arr[1] : null;
    const row = hist && (hist.seasons || []).find(x => Number(x.season) === Number(S));
    const live = Object.keys(sim).length > 0;
    const open = Object.keys(sim).some(t => isNum(sim[t].w_p05) && sim[t].w_p95 > sim[t].w_p05);
    let h = '';
    if (row && row.champion && !open) {
      h += '<div class="qk-kpis hw-kpis">' + QK.kpi({ label: 'Champion', value: HW.teamName(L, row.champion), text: true, sub: row.runner_up ? 'beat ' + HW.teamName(L, row.runner_up) : '' }) +
        (row.mvp ? QK.kpi({ label: 'MVP', value: String(HW.NAMES[L].players[String(row.mvp)] ? HW.playerName(L, row.mvp) : row.mvp), text: true }) : '') +
        (row.best_record ? QK.kpi({ label: 'Best record', value: HW.teamAbbr(L, row.best_record[0]) + ' ' + HW.record(row.best_record[1], row.best_record[2]), sub: HW.teamName(L, row.best_record[0]) }) : '') + '</div>';
    }
    h += U.card2(open ? 'Standings and odds' : 'Standings', open && season.sim ? HW.num(season.sim.n_sims, 0) + ' simulations of the rest of the season. Dashed lines: the playoff' + (fmt.playin ? ' and play-in' : '') + ' cuts.' : 'Records and seeds.',
      (views.length > 1 ? '<div class="qk-seg" id="st-seg" role="group" aria-label="Group" style="margin:0 16px 12px">' + views.map(v => '<button type="button" data-value="' + esc(v[0]) + '" aria-pressed="' + (v[0] === first) + '">' + esc(v[1]) + '</button>').join('') + '</div>' : '') + '<div id="st-table"></div>', { flush: true });
    if (open) {
      h += '<div class="qk-grid hw-sec">' + confs.map((c, i) => U.card2(c + ': playoff odds', fmt.playin ? 'A top-six seed goes straight through; seeds 7-10 play in' : 'Chance of a playoff place', U.chart('st-odds-' + i, 22 * (st[c] || []).length + 50, c + ' playoff odds'), { cls: confs.length > 1 ? 'qk-span-6' : 'qk-span-12' })).join('') + '</div>';
    }
    node.innerHTML = h;
    const draw = k => standingsTable(document.getElementById('st-table'), L, S, k === '__all' ? all() : (st[k] || []), sim, fmt, k === '__all');
    draw(first);
    const seg = document.getElementById('st-seg');
    if (seg) QK.seg(seg, draw);
    if (open) confs.forEach((c, i) => {
      const ids = (st[c] || []).map(r => r.team).sort((a, b) => ((sim[b] || {}).p_playoffs || 0) - ((sim[a] || {}).p_playoffs || 0));
      const series = fmt.playin
        ? [{ name: 'Top-six seed', data: ids.map(t => r3((sim[t] || {}).p_top6)) }, { name: 'Via the play-in', data: ids.map(t => r3(Math.max(0, ((sim[t] || {}).p_playoffs || 0) - ((sim[t] || {}).p_top6 || 0)))) }]
        : [{ name: 'Playoffs', data: ids.map(t => r3((sim[t] || {}).p_playoffs)) }];
      QKC.bar('#st-odds-' + i, { cats: ids.map(t => HW.teamAbbr(L, t)), series: series, horizontal: true, stack: true, legend: series.length > 1, fmt: v => U.pct(v), max: 1, hrefs: ids.map(t => HW.teamHref(L, t, S)), labelWidth: 46 });
    });
    if (!live) HW.setMeta('');
  });
}
function r3(v) { return isNum(v) ? Math.round(v * 1000) / 1000 : 0; }

function historyTab(node, L) {
  return HW.load(HW.lpath('history.json', L)).then(hist => {
    if (!U.alive(node)) return;
    if (!U.ok(hist)) { node.innerHTML = U.empty('No history', 'The champions list is not built yet.'); return; }
    const rows = (hist.seasons || []).slice().sort((a, b) => b.season - a.season);
    const cnt = {};
    rows.forEach(r => { if (r.champion) cnt[r.champion] = (cnt[r.champion] || 0) + 1; });
    const top = Object.keys(cnt).sort((a, b) => cnt[b] - cnt[a]).slice(0, 12);
    const tn = id => (hist.team_names || {})[id] || HW.teamName(L, id);
    node.innerHTML = '<div class="qk-grid">' + U.card2('Titles since ' + (hist.first_season || ''), 'Championships by team in the data', U.chart('hs-ch', 26 * top.length + 30, 'Titles by team'), { cls: 'qk-span-5' }) +
      U.card2('Champions', 'Season by season', '<div id="hs-t"></div>', { cls: 'qk-span-7', flush: true }) + '</div>';
    QKC.bar('#hs-ch', { cats: top.map(tn), series: [{ name: 'Titles', data: top.map(t => cnt[t]) }], horizontal: true, labels: true, fmt: v => String(v), colors: top.map(t => U.tcol(L, t)), labelWidth: 140 });
    QK.table(document.getElementById('hs-t'), { dense: true, maxHeight: 560, rows: rows.map(r => Object.assign({}, r, { bw: r.best_record ? r.best_record[1] : null })), columns: [
      { key: 'season', label: 'Season', num: true, fmt: v => '<a class="hw-link" href="' + esc(HW.href(L, 'standings', v)) + '">' + esc(HW.seasonLabel(L, v)) + '</a>' },
      { key: 'champion', label: 'Champion', fmt: v => (v ? U.teamEnt(L, v, { name: tn(v) }) : '—') },
      { key: 'runner_up', label: 'Runner-up', fmt: v => (v ? esc(tn(v)) : '—') },
      { key: 'mvp', label: 'MVP', fmt: v => esc(v ? (HW.NAMES[L].players[String(v)] ? HW.playerName(L, v) : v) : '—') },
      { key: 'bw', label: 'Best record', num: true, fmt: (v, r) => (r.best_record ? esc(HW.teamAbbr(L, r.best_record[0])) + ' ' + HW.record(r.best_record[1], r.best_record[2]) : '—') }
    ] });
  });
}

function renderStandings(el, params) {
  const L = U.L(params), S = U.S(params);
  const tab = U.tab(params, ['table', 'odds', 'bracket', 'markets', 'history'], 'table');
  const body = U.section(el, { title: 'Standings', kicker: U.kicker(L, S), sub: 'Records, playoff and title odds from the season simulation, the bracket and the market.',
    tabs: U.tabs(L, 'standings', [['table', 'Table'], ['odds', 'Odds & ratings'], ['bracket', 'Bracket'], ['markets', 'Futures v market'], ['history', 'History', false]], S), active: tab });
  if (tab === 'table') return standingsTab(body, L, S, params);
  if (tab === 'history') return historyTab(body, L);
  const v = { odds: 'season', bracket: 'playoffs', markets: 'markets' }[tab];
  return U.legacy(v, body, params);
}

// ── Teams ──────────────────────────────────────────────────────────────────

function renderTeams(el, params) {
  const L = U.L(params), S = U.S(params);
  const tab = U.tab(params, ['teams', 'stats'], 'teams');
  const body = U.section(el, { title: 'Teams', kicker: U.kicker(L, S), sub: 'Every team’s record, rating and odds. Open a team for its ratings over time, strengths and needs, current roster, schedule and moves.',
    tabs: U.tabs(L, 'teams', [['teams', 'Teams'], ['stats', 'Team stats']], S), active: tab });
  if (tab === 'stats') return U.legacy('teams', body, params);
  return HW.load(HW.path('season.json', L, S)).then(season => {
    if (!U.alive(body)) return;
    if (!U.ok(season)) { body.innerHTML = U.empty('Not built yet', 'The season payload is not available.'); return; }
    const sim = HW.simTeams(season), R = season.ratings || {}, st = season.standings || {};
    const confs = Object.keys(st).filter(c => (st[c] || []).length).sort();
    const ids = Object.keys(R).length ? Object.keys(R) : Object.keys(season.teams || {});
    const rec = {}; confs.forEach(c => (st[c] || []).forEach(r => { rec[r.team] = Object.assign({ conf: c }, r); }));
    const maxNet = Math.max.apply(null, ids.map(t => Math.abs((R[t] || {}).net || 0)).concat([1]));
    const tile = t => {
      const r = R[t] || {}, s = sim[t] || {}, x = rec[t] || {};
      const net = isNum(r.net) ? r.net : null;
      return '<a class="hw-teamtile" href="' + esc(HW.teamHref(L, t, S)) + '" style="--tc:' + esc(U.tcol(L, t)) + '"><div class="top">' + QK.teamMark(U.team(L, t), 'sm') + '<span class="nm">' + esc(HW.teamName(L, t)) + '</span><span class="rec">' + (isNum(x.w) ? HW.record(x.w, x.l) : '') + '</span></div>' +
        '<div class="row"><span>Net rating' + (isNum(r.rank) ? ' · ' + HW.ordinal(r.rank) : '') + '</span><b>' + U.signed(net, 1) + '</b></div><div class="hw-bar"><span style="width:' + (net === null ? 0 : Math.max(2, 50 + 50 * net / maxNet)).toFixed(1) + '%"></span></div>' +
        (isNum(s.p_playoffs) ? '<div class="row"><span>' + (isNum(s.exp_w) && s.w_p95 > s.w_p05 ? 'Proj ' + U.f(s.exp_w, 1) + ' W · ' : '') + 'Playoffs</span><b>' + U.pct(s.p_playoffs) + '</b></div><div class="row"><span>Title</span><b>' + U.pct(s.p_title) + '</b></div>' : '') + '</a>';
    };
    const groups = confs.length ? confs.map(c => [c, (st[c] || []).map(r => r.team).filter(t => ids.indexOf(t) >= 0).sort((a, b) => ((R[b] || {}).net || -99) - ((R[a] || {}).net || -99))]) : [['', ids]];
    const withR = ids.filter(t => isNum((R[t] || {}).off) && isNum((R[t] || {}).def));
    let h = groups.map(g => (g[0] ? '<div class="hw-day"><b>' + esc(g[0]) + '</b> · by net rating</div>' : '') + '<div class="hw-mini-grid">' + g[1].map(tile).join('') + '</div>').join('');
    if (withR.length) {
      h += '<div class="qk-grid hw-sec">' + U.card2('Offence against defence', 'Opponent-adjusted points per 100 possessions. Up and right is better (defence axis reversed); the dashed lines are the league average.', U.chart('tm-od', 460, 'Offence against defence'), { cls: 'qk-span-7' }) +
        U.card2('Net rating through the season', 'Kalman path after each game', U.chart('tm-paths', 460, 'Rating paths'), { cls: 'qk-span-5' }) + '</div>';
    }
    body.innerHTML = h;
    if (withR.length) {
      const mx = withR.reduce((s, t) => s + R[t].off, 0) / withR.length, my = withR.reduce((s, t) => s + R[t].def, 0) / withR.length;
      QKC.mount('#tm-od', T => ({
        grid: { left: 8, right: 24, top: 20, bottom: 30, containLabel: true },
        xAxis: QKC.axis(T, { name: 'Offensive rating', nameLocation: 'middle', nameGap: 28, scale: true }),
        yAxis: QKC.axis(T, { name: 'Defensive rating (reversed)', scale: true, inverse: true }),
        tooltip: QKC.tooltip(T, { formatter: p => { const t = withR[p.dataIndex]; return '<div style="font-weight:600;margin-bottom:4px">' + esc(HW.teamName(L, t)) + '</div>' + QKC.tipRow(p.color, 'Offence', U.f(R[t].off, 1)) + QKC.tipRow(p.color, 'Defence', U.f(R[t].def, 1)) + QKC.tipRow(p.color, 'Net', U.signed(R[t].net, 1) + (isNum(R[t].se_net) ? ' ± ' + U.f(R[t].se_net, 1) : '')); } }),
        series: [{ type: 'scatter', symbolSize: 13, data: withR.map(t => ({ value: [R[t].off, R[t].def], href: HW.teamHref(L, t, S), itemStyle: { color: U.tcol(L, t), borderColor: T.s1, borderWidth: 1.5 },
          label: { show: true, formatter: HW.teamAbbr(L, t), position: 'top', color: T.ink2, fontSize: 10, fontWeight: 600, fontFamily: T.fontUI } })), labelLayout: { hideOverlap: true },
          markLine: { silent: true, symbol: 'none', lineStyle: { color: T.axis, type: [4, 4] }, label: { show: false }, data: [{ xAxis: mx }, { yAxis: my }] } }]
      }), { label: 'Offence against defence' });
      const paths = season.rating_paths || {};
      const top = ids.filter(t => (paths[t] || []).length > 1).sort((a, b) => ((R[b] || {}).net || 0) - ((R[a] || {}).net || 0));
      if (top.length) {
        const dates = Array.from(new Set([].concat.apply([], top.map(t => paths[t].map(p => p.date))))).sort();
        const show = top.slice(0, 5).concat(top.slice(-3));
        QKC.line('#tm-paths', { x: dates.map(d => HW.fmtDate(d, { year: false, weekday: false })), series: show.map(t => { const m = {}; paths[t].forEach(p => { m[p.date] = p.net; });
          let last = null; return { name: HW.teamAbbr(L, t), color: U.tcol(L, t), data: dates.map(d => { if (isNum(m[d])) last = Math.round(m[d] * 10) / 10; return last; }) }; }), yFmt: v => U.signed(v, 1), ref: { y: 0 } });
      } else document.getElementById('tm-paths').innerHTML = U.empty('No games yet', 'Rating paths start with the first games.');
    }
  });
}

// ── Players ────────────────────────────────────────────────────────────────

const BOARDS = [['pts_g', 'Points a game'], ['reb_g', 'Rebounds a game'], ['ast_g', 'Assists a game'], ['tpm_g', 'Threes a game'], ['stl_g', 'Steals a game'], ['blk_g', 'Blocks a game'],
  ['ts', 'True shooting'], ['hpm', 'Impact (HPM)'], ['pox100', 'Shot-making (pts over exp. / 100)'], ['wpa', 'Win probability added'], ['on_off', 'On/off (net per 100)'], ['gmsc', 'Game score']];

function leadersTab(node, L, S) {
  return U.catalogue(L, S).then(r => {
    if (!U.alive(node)) return;
    const cat = r.cat;
    if (!U.ok(cat) || !Object.keys(cat.players || {}).length) { node.innerHTML = U.empty('No player numbers yet', 'The catalogue fills in once games are played.'); return; }
    const P = cat.players, meta = {};
    (cat.metrics || []).forEach(m => { meta[m.key] = m; });
    const fl = U.floor(cat);
    const ok = id => (P[id].min || 0) >= fl.min && (P[id].gp || 0) >= fl.gp;
    const ids = Object.keys(P).filter(ok);
    const SS = r.S;
    let h = r.fallback ? '<div class="qk-note" style="margin-bottom:14px">No ' + esc(HW.seasonLabel(L, S)) + ' regular-season games yet: these are the final ' + esc(HW.seasonLabel(L, SS)) + ' numbers.</div>' : '';
    h += '<div class="hw-flex" style="margin-bottom:14px"><input class="qk-input hw-search" id="pl-q" type="search" placeholder="Find a player…" aria-label="Find a player" autocomplete="off"><span class="hw-quiet">Floors: ' + fl.min + '+ minutes and ' + fl.gp + '+ games (' + ids.length + ' players qualify). Counting boards and rates use the same floor.</span></div><div id="pl-hits"></div>';
    h += '<div class="qk-grid">' + U.card2('Impact at both ends', 'HPM per 100 possessions, offence against defence; qualified players, size is minutes', U.chart('pl-sc', 440, 'Impact at both ends'), { cls: 'qk-span-12' }) + '</div>';
    h += '<div class="hw-leaders hw-sec">' + BOARDS.filter(b => meta[b[0]]).map(b => {
      const m = meta[b[0]];
      const list = ids.filter(id => isNum((P[id].values || {})[b[0]])).sort((a, c) => (m.lower ? 1 : -1) * ((P[a].values[b[0]]) - (P[c].values[b[0]]))).slice(0, 8);
      return '<div class="qk-card"><div class="qk-card-head"><div class="qk-card-title">' + esc(b[1]) + '</div></div><ul class="hw-list">' + list.map((id, i) =>
        '<li><span class="n">' + (i + 1) + '</span>' + U.playerEnt(L, id, P[id].name, P[id].team, null, SS) + '<span class="v">' + HW.fmtVal(P[id].values[b[0]], m.fmt) + '</span></li>').join('') + '</ul></div>';
    }).join('') + '</div>';
    node.innerHTML = h;
    const q = document.getElementById('pl-q'), hits = document.getElementById('pl-hits');
    const all = Object.keys(P).sort((a, b) => (P[b].min || 0) - (P[a].min || 0));
    q.addEventListener('input', () => {
      const s = q.value.trim().toLowerCase();
      if (s.length < 2) { hits.innerHTML = ''; return; }
      const found = all.filter(id => String(P[id].name || '').toLowerCase().indexOf(s) >= 0 || HW.teamName(L, P[id].team).toLowerCase().indexOf(s) >= 0).slice(0, 12);
      hits.innerHTML = '<div class="qk-card" style="margin-bottom:14px"><ul class="hw-list">' + (found.length ? found.map(id => '<li>' + U.playerEnt(L, id, P[id].name, P[id].team, (P[id].pos || '') + ' · ' + HW.teamAbbr(L, P[id].team), SS) +
        '<span class="v">' + U.f((P[id].values || {}).pts_g, 1) + ' ppg</span></li>').join('') : '<li class="hw-quiet">No player matches.</li>') + '</ul></div>';
    });
    const pts = ids.filter(id => isNum((P[id].values || {}).hpm_o) && isNum((P[id].values || {}).hpm_d));
    const maxMin = Math.max.apply(null, pts.map(id => P[id].min || 0).concat([1]));
    QKC.scatter('#pl-sc', { points: pts.map(id => ({ x: P[id].values.hpm_o, y: P[id].values.hpm_d, name: P[id].name + ' · ' + HW.teamAbbr(L, P[id].team), label: (P[id].name || '').split(' ').slice(-1)[0],
      color: U.tcol(L, P[id].team), size: 5 + 11 * Math.sqrt((P[id].min || 0) / maxMin), href: HW.playerHref(L, id, SS) })), xName: 'Offensive HPM', yName: 'Defensive HPM', xFmt: v => U.signed(v, 1), yFmt: v => U.signed(v, 1),
      refX: 0, refY: 0, labelTop: 14, quadrants: ['Defence first', 'Both ends', 'Below average', 'Offence first'] });
  });
}

function renderPlayers(el, params) {
  const L = U.L(params), S = U.S(params);
  const tab = U.tab(params, ['leaders', 'catalogue', 'awards', 'boards'], 'leaders');
  const body = U.section(el, { title: 'Players', kicker: U.kicker(L, S), sub: 'Leaders with sample floors, the full catalogue of 125 metrics with percentiles, and the award races. Open a player for his season by season, splits and value.',
    tabs: U.tabs(L, 'players', [['leaders', 'Leaders'], ['catalogue', 'Catalogue'], ['awards', 'Awards'], ['boards', 'Any metric']], S), active: tab });
  if (tab === 'leaders') return leadersTab(body, L, S);
  return U.legacy({ catalogue: 'players', awards: 'awards', boards: 'leaders' }[tab], body, params);
}

// ── Lab and Model ──────────────────────────────────────────────────────────

function renderLab(el, params, state) {
  const L = U.L(params), S = U.S(params);
  const r = state.route;
  const compare = r === 'compare' || r === 'compare-players' || r === 'compare-teams' || U.tab(params, ['lab', 'compare'], 'lab') === 'compare';
  const tab = compare ? 'compare' : 'lab';
  const body = U.section(el, { title: 'Lab', kicker: U.kicker(L, S), sub: 'Build your own chart from any two player metrics, or put two players or two teams side by side.',
    tabs: U.tabs(L, 'lab', [['lab', 'Chart builder'], ['compare', 'Compare']], S), active: tab });
  if (!compare) return U.legacy('lab', body, params);
  const name = r === 'compare-players' ? 'compare-players' : r === 'compare-teams' ? 'compare-teams' : 'compare';
  return U.legacy(name, body, params);
}

function renderModel(el, params, state) {
  const L = U.L(params);
  const r = state.route;
  let tab = r === 'glossary' ? 'glossary' : r === 'methodology' ? 'methodology' : r === 'disclaimer' ? 'terms' : U.tab(params, ['methodology', 'calibration', 'glossary', 'terms'], 'methodology');
  const body = U.section(el, { title: 'Model', kicker: HW.leagueName(L) + ' · how it works', sub: 'How the models are built, how well they have done, and what every number means.',
    tabs: U.tabs(L, 'model', [['methodology', 'Methodology'], ['calibration', 'Calibration'], ['glossary', 'Glossary'], ['terms', 'Terms']], null), active: tab });
  const v = { methodology: 'methodology', calibration: 'calibration', glossary: 'glossary', terms: 'disclaimer' }[tab];
  return U.legacy(v, body, params);
}

HW.page('standings', renderStandings);
HW.page('teams', renderTeams);
HW.page('players', renderPlayers);
HW.page('lab', renderLab);
['compare', 'compare-players', 'compare-teams'].forEach(n => HW.page(n, renderLab));
['model', 'glossary', 'methodology', 'disclaimer'].forEach(n => HW.page(n, renderModel));
})(window.HW);
