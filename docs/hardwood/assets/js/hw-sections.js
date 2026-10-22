/* The Quant Hardwood — section pages: Standings, Teams (list), Players (list), Lab and Model.
 *
 *   Standings (#/<L>/standings): Table (records, projected wins with the 90% range, our playoff / play-in /
 *     title chances, clinching), Chances & ratings (seed distribution, win totals, rating paths, schedule
 *     difficulty: the pre-redesign season page), Bracket, History (champions). Our forecasts against the market
 *     moved to the Model section (#/<L>/model?tab=markets), the one place the market sits beside ours.
 *   Teams (#/<L>/teams): tiles by conference with record, net rating and odds; offence v defence; Team stats tab
 *     (the full team catalogue).
 *   Players (#/<L>/players): Leaders (search, a leaderboard with role-percentile heat cells, impact at both ends), Catalogue,
 *     Awards, All leaderboards.
 *   Lab (#/<L>/lab): Chart builder and Compare (#/<L>/compare/... opens here).
 *   Model (#/<L>/model): Methodology, Calibration, Our forecasts v the market, Glossary, Terms (#/glossary/<key>, #/methodology/<part> and
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
      home_w: (r.home || [])[0], away_w: (r.away || [])[0], l10_w: (r.l10 || [])[0], nm: HW.teamShort(L, r.team) });
  });
  const cols = [
    { key: 'seedN', label: '#', num: true },
    { key: 'nm', label: 'Team', type: 'entity', mark: r => U.team(L, r.team), href: r => HW.teamHref(L, r.team, S) },
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
    cols.push({ key: 'exp', label: 'Proj W', num: true, tip: 'Projected wins (mean of our simulations) with the 90% range', fmt: (v, r) => (isNum(v) ? '<span data-tip="' + esc(U.f(r.s.w_p05, 0) + '–' + U.f(r.s.w_p95, 0) + ' (90% range)') + '">' + U.f(v, 1) + '</span>' : '—') });
    cols.push({ key: 'pp', label: 'Playoffs', type: 'bar', max: 1, fmt: v => U.pct(v), tip: 'Our chance of reaching the playoffs proper' });
    if (hasPin) cols.push({ key: 'pin', label: 'Play-in', num: true, fmt: v => U.pct(v), tip: 'Our chance of finishing in the play-in places' });
    if (!league) cols.push({ key: 'pc', label: 'Conf', num: true, fmt: v => U.pct(v), tip: 'Our chance of winning the conference' });
    cols.push({ key: 'pt', label: 'Title', num: true, fmt: v => '<b>' + U.pct(v) + '</b>' });
    cols.push({ key: 'mg', label: 'Clinch', sort: false, fmt: (v, r) => magic(r.s) });
  }
  QK.leaderboard(node, { columns: cols, rows: data, dense: true, rowHref: r => HW.teamHref(L, r.team, S) });
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
      h += '<div class="hw-kpis">' + QK.stats([{ label: 'Champion', value: HW.teamName(L, row.champion), text: true, signal: true, sub: row.runner_up ? 'beat ' + HW.teamName(L, row.runner_up) : '' },
        row.mvp ? { label: 'MVP', value: String(HW.NAMES[L].players[String(row.mvp)] ? HW.playerName(L, row.mvp) : row.mvp), text: true } : null,
        row.best_record ? { label: 'Best record', value: HW.teamAbbr(L, row.best_record[0]) + ' ' + HW.record(row.best_record[1], row.best_record[2]), sub: HW.teamName(L, row.best_record[0]) } : null]) + '</div>';
    }
    h += U.card2(open ? 'Standings and our chances' : 'Standings', open && season.sim ? Number(season.sim.n_sims).toLocaleString('en-GB') + ' simulations of the rest of the season. Dashed lines: the playoff' + (fmt.playin ? ' and play-in' : '') + ' cuts.' : 'Records and seeds.',
      (views.length > 1 ? '<div class="qk-seg" id="st-seg" role="group" aria-label="Group" style="margin:0 16px 12px">' + views.map(v => '<button type="button" data-value="' + esc(v[0]) + '" aria-pressed="' + (v[0] === first) + '">' + esc(v[1]) + '</button>').join('') + '</div>' : '') + '<div id="st-table"></div>', { flush: true });
    if (open) {
      h += '<div class="qk-grid hw-sec">' + confs.map((c, i) => U.card2(c + ': who makes the playoffs', fmt.playin ? 'Our chance: a top-six seed goes straight through; seeds 7-10 play in' : 'Our chance of a playoff place', U.chart('st-odds-' + i, 22 * (st[c] || []).length + 70, c + ' playoff chances'), { cls: confs.length > 1 ? 'qk-span-6' : 'qk-span-12' })).join('') + '</div>';
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
      QKC.bar('#st-odds-' + i, { cats: ids.map(t => HW.teamAbbr(L, t)), series: series, horizontal: true, stack: true, legend: series.length > 1, fmt: v => U.pct(v), max: 1, hrefs: ids.map(t => HW.teamHref(L, t, S)), labelWidth: 46, valName: 'Our playoff chance', catName: 'Team' });
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
    QKC.bar('#hs-ch', { cats: top.map(tn), series: [{ name: 'Titles', data: top.map(t => cnt[t]) }], horizontal: true, labels: true, fmt: v => String(v), colors: top.map(t => U.tcol(L, t)), labelWidth: 140, valName: 'Championships' });
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
  // the market comparison lives on the Model page now; old links land there
  if (((params.query || {}).tab) === 'markets') { HW.go(HW.href(L, 'model', S) + (HW.sq(L, S) ? '&' : '?') + 'tab=markets'); return null; }
  const tab = U.tab(params, ['table', 'odds', 'bracket', 'history'], 'table');
  const body = U.section(el, { title: 'Standings', kicker: U.kicker(L, S), sub: 'Records, our playoff and title chances from the season simulation, and the bracket.',
    tabs: U.tabs(L, 'standings', [['table', 'Table'], ['odds', 'Chances & ratings'], ['bracket', 'Bracket'], ['history', 'History', false]], S), active: tab });
  if (tab === 'table') return standingsTab(body, L, S, params);
  if (tab === 'history') return historyTab(body, L);
  const v = { odds: 'season', bracket: 'playoffs' }[tab];
  return U.legacy(v, body, params);
}

// ── Teams ──────────────────────────────────────────────────────────────────

function renderTeams(el, params) {
  const L = U.L(params), S = U.S(params);
  const tab = U.tab(params, ['teams', 'stats'], 'teams');
  const body = U.section(el, { title: 'Teams', kicker: U.kicker(L, S), sub: 'Every team’s record, rating and our chances. Open a team for its ratings over time, strengths and needs, current roster, schedule and moves.',
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
        (isNum(s.p_playoffs) ? '<div class="row"><span>' + (isNum(s.exp_w) && s.w_p95 > s.w_p05 ? 'Proj ' + U.f(s.exp_w, 1) + ' W · ' : '') + 'Playoffs</span><b>' + U.pct(s.p_playoffs) + '</b></div><div class="row"><span>Title chance</span><b>' + U.pct(s.p_title) + '</b></div>' : '') + '</a>';
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
        grid: { left: 8, right: 24, top: 34, bottom: 30, containLabel: true },
        xAxis: QKC.axis(T, { name: 'Offensive rating (points per 100)', nameLocation: 'middle', nameGap: 28, scale: true }),
        yAxis: QKC.axis(T, { name: 'Defensive rating (allowed per 100, reversed)', scale: true, inverse: true, nameLocation: 'start', nameAlign: 'left' }),
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
          let last = null; return { name: HW.teamAbbr(L, t), color: U.tcol(L, t), data: dates.map(d => { if (isNum(m[d])) last = Math.round(m[d] * 10) / 10; return last; }) }; }), yFmt: v => U.signed(v, 1), ref: { y: 0 }, xName: 'Date', yName: 'Net rating (points per 100 possessions)', label: 'Net rating through the season' });
      } else document.getElementById('tm-paths').innerHTML = U.empty('No games yet', 'Rating paths start with the first games.');
    }
  });
}

// ── Players ────────────────────────────────────────────────────────────────

/* The leaderboard's metrics: counting boards (everyone who qualifies ranks), then the role metric set. */
const COUNT = [['pts_g', 'Points a game', '1'], ['reb_g', 'Rebounds a game', '1'], ['ast_g', 'Assists a game', '1'], ['tpm_g', 'Threes a game', '1'], ['stl_g', 'Steals a game', '1'], ['blk_g', 'Blocks a game', '1']];

function leadersTab(node, L, S) {
  return Promise.all([U.catalogue(L, S), U.roles(L, S)]).then(res => {
    if (!U.alive(node)) return;
    const r = res[0], cat = r.cat;
    if (!U.ok(cat) || !Object.keys(cat.players || {}).length) { node.innerHTML = U.empty('No player numbers yet', 'The catalogue fills in once games are played.'); return; }
    const SS = r.S;
    const roles = r.fallback ? {} : res[1];
    const finish = rl => {
      const P = cat.players;
      const ids = Object.keys(P).filter(id => P[id].qualified);
      const keys = COUNT.map(x => x[0]).concat(['hpm', 'hpm_o', 'hpm_d', 'pts100', 'ts_add', 'pox100', 'ast_pct', 'drb_pct', 'stl_pct', 'blk_pct', 'ts']).filter(k => ids.some(id => isNum((P[id].values || {})[k])));
      const lab = k => { const c = COUNT.find(x => x[0] === k); return c ? c[1] : U.mMeta(k).label; };
      const fmtK = (k, v) => { const c = COUNT.find(x => x[0] === k); return c ? U.f(v, 1) : U.fmtM(k, v); };
      let h = r.fallback ? '<div class="qk-note" style="margin-bottom:14px">No ' + esc(HW.seasonLabel(L, S)) + ' regular-season games yet: these are the final ' + esc(HW.seasonLabel(L, SS)) + ' numbers.</div>' : '';
      h += '<div class="hw-flex" style="margin-bottom:14px"><input class="qk-input hw-search" id="pl-q" type="search" placeholder="Find a player…" aria-label="Find a player" autocomplete="off"><span class="hw-quiet">Qualified: ' + Number(cat.min_floor || 0).toLocaleString('en-GB') + '+ minutes (' + ids.length + ' players). Heat cells: percentile within the player’s role (guards, wings, bigs).</span></div><div id="pl-hits"></div>';
      h += U.card2('Leaderboard', 'Pick a metric and a role. Every cell is coloured by the percentile within the role, cold to hot.',
        '<div class="hw-flex" style="margin-bottom:12px"><select class="qk-select" id="pl-k" aria-label="Metric">' + keys.map(k => '<option value="' + k + '">' + esc(lab(k)) + '</option>').join('') + '</select>' +
        '<div class="qk-seg" id="pl-r" role="group" aria-label="Role"><button type="button" data-value="" aria-pressed="true">All</button><button type="button" data-value="G" aria-pressed="false">Guards</button><button type="button" data-value="W" aria-pressed="false">Wings</button><button type="button" data-value="B" aria-pressed="false">Bigs</button></div></div><div id="pl-lb"></div>', { flush: false });
      h += '<div class="qk-grid hw-sec"><div class="qk-span-12">' + U.card2('Impact at both ends', 'HPM per 100 possessions, offence against defence; qualified players, size is minutes', U.chart('pl-sc', 440, 'Impact at both ends')) + '</div></div>';
      node.innerHTML = h;
      const st = { k: keys[0], r: '' };
      const drawLb = () => {
        const k = st.k, low = U.mMeta(k).better === 'low' && !COUNT.find(x => x[0] === k);
        const list = ids.filter(id => isNum((P[id].values || {})[k]) && (!st.r || U.roleOf(P[id], id, rl) === st.r)).sort((a, b) => (low ? 1 : -1) * (P[a].values[k] - P[b].values[k])).slice(0, 25);
        const rows = list.map(id => { const p = P[id], v = p.values || {}, role = U.roleOf(p, id, rl);
          return { id: id, name: p.name, team: p.team, sub: [HW.teamAbbr(L, p.team), (U.ROLE1 || {})[role] || p.pos].filter(Boolean).join(' · '), val: v[k], val_p: U.rolePctl(cat, rl, id, k),
            hpm: v.hpm, hpm_p: U.rolePctl(cat, rl, id, 'hpm'), ts: v.ts, ts_p: U.rolePctl(cat, rl, id, 'ts'), min: p.min, gp: p.gp }; });
        QK.leaderboard(document.getElementById('pl-lb'), { dense: true, rank: true, rows: rows, rowHref: x => HW.playerHref(L, x.id, SS), columns: [
          { key: 'name', label: 'Player', type: 'entity', sub: 'sub', mark: x => U.team(L, x.team), href: x => HW.playerHref(L, x.id, SS) },
          { key: 'val', label: lab(k), type: 'pctl', pctl: 'val_p', fmt: v => fmtK(k, v) },
          { key: 'hpm', label: 'HPM', type: 'pctl', pctl: 'hpm_p', fmt: v => U.signed(v, 1), tip: 'Total impact per 100 possessions' },
          { key: 'ts', label: 'TS%', type: 'pctl', pctl: 'ts_p', fmt: v => HW.fmtVal(v, 'pct') },
          { key: 'gp', label: 'GP', num: true }, { key: 'min', label: 'Min', type: 'bar', fmt: v => Number(Math.round(v || 0)).toLocaleString('en-GB') }] });
      };
      drawLb();
      document.getElementById('pl-k').addEventListener('change', e => { st.k = e.target.value; drawLb(); });
      QK.seg(document.getElementById('pl-r'), v => { st.r = v; drawLb(); });
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
        color: U.tcol(L, P[id].team), size: 5 + 11 * Math.sqrt((P[id].min || 0) / maxMin), href: HW.playerHref(L, id, SS) })), xName: 'Offensive impact (HPM per 100)', yName: 'Defensive impact (HPM per 100)', xFmt: v => U.signed(v, 1), yFmt: v => U.signed(v, 1),
        refX: 0, refY: 0, labelTop: 14, quadrants: ['Defence first', 'Both ends', 'Below average', 'Offence first'], label: 'Impact at both ends' });
      HW.setMeta('');
    };
    if (r.fallback) return U.roles(L, SS).then(rl => { if (U.alive(node)) finish(rl); });
    finish(roles);
    return null;
  });
}

/* The player catalogue (Players ▸ Catalogue), Design System 2.0: every player of the season as a leaderboard on the
 * spec's shared headline metrics, heat cells by percentile within the role (or the league), a role filter, a team
 * filter, any extra catalogue column, and the chance of moving where the movement model is published (NBA). */
const CAT = { q: '', role: '', team: '', basis: 'role', extra: '', all: false };
const CAT_KEYS = ['hpm', 'hpm_o', 'hpm_d', 'pts100', 'ts_add', 'ast_pct', 'drb_pct', 'stl_pct', 'blk_pct'];
function catalogueTab(node, L, S) {
  return Promise.all([U.catalogue(L, S), U.roles(L, S), U.isCur(L, S) ? U.movement(L) : Promise.resolve(null)]).then(res => {
    if (!U.alive(node)) return null;
    const r = res[0], cat = r.cat, SS = r.S;
    if (!U.ok(cat) || !Object.keys(cat.players || {}).length) { node.innerHTML = U.empty('No player numbers yet', 'The catalogue fills in once games are played.'); return null; }
    const go = rl => draw(rl, res[2] && res[2].pub.next ? res[2] : null);
    if (r.fallback) return U.roles(L, SS).then(rl => { if (U.alive(node)) go(rl); });
    go(res[1]);
    return null;
    function draw(rl, mv) {
      const P = cat.players, ids = Object.keys(P);
      const meta = {}; (cat.metrics || []).forEach(m => { meta[m.key] = m; });
      const teams = Array.from(new Set(ids.map(id => P[id].team).filter(Boolean))).sort((a, b) => HW.teamName(L, a).localeCompare(HW.teamName(L, b)));
      const groups = {}; (cat.metrics || []).forEach(m => { (groups[m.group || 'Other'] || (groups[m.group || 'Other'] = [])).push(m); });
      node.innerHTML = (r.fallback ? '<div class="qk-note" style="margin-bottom:14px">No ' + esc(HW.seasonLabel(L, S)) + ' regular-season games yet: these are the final ' + esc(HW.seasonLabel(L, SS)) + ' numbers.</div>' : '') +
        U.card2('Every player', 'Heat cells: the percentile within the player’s role (guards, wings, bigs) or the whole league, 100 = best. Percentiles need ' + Number(cat.min_floor || 0).toLocaleString('en-GB') + '+ minutes.' + (mv ? ' Chance of moving: ' + esc(U.mvHorizon(mv)) + '.' : ''),
          '<div class="hw-catctl"><input class="qk-input hw-search" id="ct-q" type="search" placeholder="Player or team…" aria-label="Find a player" value="' + esc(CAT.q) + '">' +
          '<div class="qk-seg" id="ct-role" role="group" aria-label="Role">' + [['', 'All'], ['G', 'Guards'], ['W', 'Wings'], ['B', 'Bigs']].map(x => '<button type="button" data-value="' + x[0] + '" aria-pressed="' + (CAT.role === x[0]) + '">' + x[1] + '</button>').join('') + '</div>' +
          '<div class="qk-seg" id="ct-basis" role="group" aria-label="Percentiles against">' + [['role', 'Against the role'], ['league', 'Against the league']].map(x => '<button type="button" data-value="' + x[0] + '" aria-pressed="' + (CAT.basis === x[0]) + '">' + x[1] + '</button>').join('') + '</div>' +
          '<select class="qk-select" id="ct-team" aria-label="Team"><option value="">All teams</option>' + teams.map(t => '<option value="' + esc(t) + '"' + (t === CAT.team ? ' selected' : '') + '>' + esc(HW.teamName(L, t)) + '</option>').join('') + '</select>' +
          '<select class="qk-select" id="ct-extra" aria-label="Add a column"><option value="">Add a column…</option>' + Object.keys(groups).map(g => '<optgroup label="' + esc(g) + '">' + groups[g].map(m => '<option value="' + esc(m.key) + '"' + (m.key === CAT.extra ? ' selected' : '') + '>' + esc(m.label) + '</option>').join('') + '</optgroup>').join('') + '</select>' +
          '<label class="hw-quiet hw-chk"><input type="checkbox" id="ct-all"' + (CAT.all ? ' checked' : '') + '> include players under the floor</label></div>' +
          (mv ? '<div class="hw-mvline" style="margin-top:10px"><span class="qk-muted">Chance of moving, split by how:</span>' + U.mvKeys(mv) + '</div>' : '') +
          '<div id="ct-sub" class="hw-quiet" style="margin:8px 0"></div><div id="ct-table"></div>');
      const pctOf = (id, k) => (CAT.basis === 'league' ? ((P[id].pct || {})[k]) : U.rolePctl(cat, rl, id, k));
      const fmtK = (k, v) => (meta[k] && !U.MSET.meta[k] ? HW.fmtVal(v, meta[k].fmt) : U.fmtM(k, v));
      const lab = k => (U.MSET.meta[k] ? U.mMeta(k).label : (meta[k] || {}).label || k);
      const drawT = () => {
        const q = CAT.q.trim().toLowerCase();
        const keys = CAT_KEYS.concat(CAT.extra && CAT_KEYS.indexOf(CAT.extra) < 0 ? [CAT.extra] : []).filter(k => ids.some(id => isNum((P[id].values || {})[k])));
        const list = ids.filter(id => { const p = P[id];
          if (!CAT.all && !p.qualified) return false;
          if (CAT.role && U.roleOf(p, id, rl) !== CAT.role) return false;
          if (CAT.team && String(p.team) !== String(CAT.team)) return false;
          return !q || (String(p.name || '') + ' ' + HW.teamName(L, p.team) + ' ' + HW.teamAbbr(L, p.team)).toLowerCase().indexOf(q) >= 0; });
        const rows = list.map(id => { const p = P[id], v = p.values || {}, role = U.roleOf(p, id, rl), o = { id: id, name: p.name, team: p.team, gp: p.gp, min: p.min,
          sub: [HW.teamAbbr(L, p.team), (U.ROLE1 || {})[role] || p.pos, isNum(p.age) ? String(Math.floor(p.age)) : '', p.qualified ? '' : 'under the floor'].filter(Boolean).join(' · ') };
          keys.forEach(k => { o[k] = v[k]; o[k + '_p'] = p.qualified ? pctOf(id, k) : null; });
          if (mv) { const mr = mv.by[id]; o.mr = mr; o.p_next = mr ? mr.p_next : null; }
          return o; });
        document.getElementById('ct-sub').textContent = rows.length + ' of ' + ids.length + ' players · sorted by total impact; tap a header to sort, a row to open the player';
        QK.leaderboard(document.getElementById('ct-table'), { dense: true, rows: rows, maxHeight: 720, sort: { key: 'hpm', dir: 'desc' }, rowHref: x => HW.playerHref(L, x.id, SS), columns: [
          { key: 'name', label: 'Player', type: 'entity', sub: 'sub', mark: x => U.team(L, x.team), href: x => HW.playerHref(L, x.id, SS) },
          { key: 'gp', label: 'GP', num: true }, { key: 'min', label: 'Min', type: 'bar', fmt: v => Number(Math.round(v || 0)).toLocaleString('en-GB') }]
          .concat(keys.map(k => ({ key: k, label: lab(k).replace(/ \(HPM\)$/, ''), type: 'pctl', pctl: k + '_p', fmt: v => fmtK(k, v), tip: U.mMeta(k).desc || (meta[k] || {}).desc || '' })))
          .concat(mv ? [{ key: 'p_next', label: 'Chance of moving', num: true, fmt: (v, x) => U.mvBar(mv, x.mr), tip: 'Our chance the player has left the team ' + U.mvHorizon(mv) }] : []) });
      };
      drawT();
      const qEl = document.getElementById('ct-q');
      qEl.addEventListener('input', () => { CAT.q = qEl.value; clearTimeout(drawT.t); drawT.t = setTimeout(drawT, 150); });
      QK.seg(document.getElementById('ct-role'), v => { CAT.role = v; drawT(); });
      QK.seg(document.getElementById('ct-basis'), v => { CAT.basis = v; drawT(); });
      document.getElementById('ct-team').addEventListener('change', e => { CAT.team = e.target.value; drawT(); });
      document.getElementById('ct-extra').addEventListener('change', e => { CAT.extra = e.target.value; drawT(); });
      document.getElementById('ct-all').addEventListener('change', e => { CAT.all = e.target.checked; drawT(); });
      HW.setMeta('');
    }
  });
}

function renderPlayers(el, params) {
  const L = U.L(params), S = U.S(params);
  const tab = U.tab(params, ['leaders', 'catalogue', 'awards', 'boards'], 'leaders');
  const body = U.section(el, { title: 'Players', kicker: U.kicker(L, S), sub: 'Leaderboards against each player’s role, the full catalogue of 125 metrics with percentiles, and the award races. Open a player for season by season, splits and value.',
    tabs: U.tabs(L, 'players', [['leaders', 'Leaders'], ['catalogue', 'Catalogue'], ['awards', 'Awards'], ['boards', 'Any metric']], S), active: tab });
  if (tab === 'leaders') return leadersTab(body, L, S);
  if (tab === 'catalogue') return catalogueTab(body, L, S);
  // before the first games the boards and award races show last season's final numbers, said so, never empty dashes
  if (tab === 'boards' || tab === 'awards') {
    const file = tab === 'awards' ? 'awards.json' : 'players.json';
    const has = d => (tab === 'awards' ? !!d && Object.keys(d).some(k => d[k] && d[k].model && Object.keys(d[k].model).length) : !!d && Object.keys(d.players || {}).length > 0);
    return HW.load(HW.path(file, L, S)).then(d => {
      if (!U.alive(body)) return null;
      const prev = HW.seasons(L).filter(x => x < S)[0];
      if (has(U.ok(d) ? d : null) || !prev) return U.legacy(tab === 'awards' ? 'awards' : 'leaders', body, params);
      body.innerHTML = '<div class="qk-note" style="margin-bottom:14px">No ' + esc(HW.seasonLabel(L, S)) + (tab === 'awards' ? ' award races until the season starts' : ' regular-season games yet') + ': these are the final ' + esc(HW.seasonLabel(L, prev)) + ' numbers.</div><div></div>';
      const r = U.legacy(tab === 'awards' ? 'awards' : 'leaders', body.lastChild, Object.assign({}, params, { season: prev }));
      return r;
    });
  }
  return U.legacy({ catalogue: 'players', awards: 'awards', boards: 'leaders' }[tab], body, params);
}

// ── Lab and Model ──────────────────────────────────────────────────────────

function renderLab(el, params, state) {
  const L = U.L(params), S = U.S(params);
  const r = state.route;
  const compare = r === 'compare' || r === 'compare-players' || r === 'compare-teams' || U.tab(params, ['lab', 'compare'], 'lab') === 'compare';
  const tab = compare ? 'compare' : 'lab';
  // players compare (Design System 2.0, hw-compare.js); ?view=all and teams keep the classic every-metric view
  if (compare && r !== 'compare-teams' && ((params.query || {}).view) !== 'all' && HW.compareV2) return HW.compareV2(el, params);
  if (compare && HW.compareTabs) {
    // the classic every-metric comparison and team compare sit under the same Compare head and tabs
    const ids = [params.a, params.b].concat(params.rest || []).filter(Boolean).map(String);
    const team = r === 'compare-teams';
    const cb = U.section(el, { title: 'Compare', kicker: U.kicker(L, S), sub: team ? 'Two teams side by side: every catalogue metric with league percentiles, rating paths, four factors, shot profiles and lineups.' : 'Every catalogue metric for two players, with the gaps, radar, shot charts and careers.',
      tabs: HW.compareTabs(L, S, team ? 'teams' : 'all', team ? [] : ids), active: team ? 'teams' : 'all' });
    return U.legacy(team ? 'compare-teams' : (r === 'compare-players' ? 'compare-players' : 'compare'), cb, params);
  }
  const body = U.section(el, { title: 'Lab', kicker: U.kicker(L, S), sub: 'Build your own chart from any two player metrics, or put two players or two teams side by side.',
    tabs: U.tabs(L, 'lab', [['lab', 'Chart builder'], ['compare', 'Compare']], S), active: tab });
  if (!compare) return U.legacy('lab', body, params);
  const name = r === 'compare-players' ? 'compare-players' : r === 'compare-teams' ? 'compare-teams' : 'compare';
  return U.legacy(name, body, params);
}

/* Who moves next, on the Model page: the method notes verbatim, the held-out validation of each block (published
 * or not, and why) and the calibration deciles of the chance of leaving. */
function movesModel(body, L) {
  body.innerHTML = QK.skeleton('lines', 6);
  return U.movement(L).then(mv => {
    if (!U.alive(body)) return;
    if (!mv) { body.innerHTML = U.empty('Not built yet', 'The movement model has not run for this league.'); return; }
    const m = mv.m, V = m.validation || {}, sp = m.split || {};
    const NAME = { next: 'Leaves by next season', deadline: 'Traded or claimed before the deadline', type: 'How players leave (type split)', arrivals: 'Arrivals by position', targets: 'Targets' };
    const ci = a => (Array.isArray(a) ? (a[0] >= 0 ? '+' : '') + U.f(a[0] * 1000, 1) + ' (' + U.f(a[1] * 1000, 1) + ' to ' + U.f(a[2] * 1000, 1) + ')' : '—');
    const rows = Object.keys(NAME).filter(k => V[k]).map(k => {
      const t = V[k].test || {};
      return { key: k, block: NAME[k], n: t.n || t.team_seasons, rate: t.rate, ll: t.logloss, llb: t.logloss_base, gain: t.ll_gain, slope: t.cal_slope, pub: !!(m.published || {})[k], why: (m.reasons || {})[k] || '' };
    });
    body.innerHTML = '<div class="qk-grid"><div class="qk-span-7">' + U.card2('How it works', 'The model notes, as published with the payload', '<div class="prose-dark">' + (m.notes || []).map(x => '<p>' + esc(x) + '</p>').join('') + '</div>') + '</div>' +
      '<div class="qk-span-5">' + U.card2('Calibration: chance of leaving', 'Sealed seasons ' + esc((sp.test || []).join(', ')) + ': our chance (decile mean) against the share who left', U.chart('mv-dec', 300, 'Predicted against observed, by decile')) + '</div></div>' +
      '<section class="qk-section">' + U.card2('Validation on the sealed seasons', 'Each block is published only when it beats the base rate with confidence and stays calibrated; otherwise the page shows the base rate or nothing',
        '<div id="mv-val"></div>', { flush: true }) + '</section>';
    QK.table(document.getElementById('mv-val'), { dense: true, rows: rows, columns: [
      { key: 'block', label: 'Block', sort: false }, { key: 'n', label: 'n', num: true }, { key: 'rate', label: 'Rate', num: true, fmt: v => U.pct(v, 1) },
      { key: 'll', label: 'Log-loss', num: true, fmt: v => U.f(v, 3), tip: 'Lower is better' }, { key: 'llb', label: 'Base rate', num: true, fmt: v => U.f(v, 3), tip: 'Log-loss of the base rate' },
      { key: 'gain', label: 'Gain ×1000 (95% CI)', num: true, fmt: v => ci(v), tip: 'Log-loss improvement over the base rate, with its 95% interval (team-clustered)' },
      { key: 'slope', label: 'Cal. slope', num: true, fmt: v => U.f(v, 2), tip: 'Calibration slope; 1 is ideal' },
      { key: 'pub', label: 'Published', fmt: (v, r) => (v ? QK.tag('yes', 'signal') : '<span data-tip="' + esc(r.why) + '" tabindex="0">' + QK.tag(r.key === 'targets' ? 'no: not shown' : 'no: base rate') + '</span>') }] });
    const dec = ((V.next || {}).test || {}).deciles || [];
    if (dec.length) QKC.scatter('#mv-dec', { points: dec.map((d, i) => ({ x: d[0], y: d[1], name: 'Decile ' + (i + 1) + ' · ' + d[2] + ' players', size: 10 })), diagonal: { label: 'perfect' }, xMin: 0, xMax: 1, yMin: 0, yMax: 1,
      xName: 'Our chance (decile mean)', yName: 'Share who left', xFmt: v => Math.round(v * 100) + '%', yFmt: v => Math.round(v * 100) + '%', label: 'Calibration of the chance of leaving' });
    else document.getElementById('mv-dec').innerHTML = U.empty('No deciles', '');
  });
}

function renderModel(el, params, state) {
  const L = U.L(params);
  const r = state.route;
  let tab = r === 'glossary' ? 'glossary' : r === 'methodology' ? 'methodology' : r === 'disclaimer' ? 'terms' : U.tab(params, ['methodology', 'calibration', 'markets', 'moves', 'glossary', 'terms'], 'methodology');
  const body = U.section(el, { title: 'Model', kicker: HW.leagueName(L) + ' · how it works', sub: 'How the models are built, how well they have done, and what every number means.',
    tabs: U.tabs(L, 'model', [['methodology', 'Methodology'], ['calibration', 'Calibration'], ['markets', 'Our forecasts v the market'], ['moves', 'Who moves next'], ['glossary', 'Glossary'], ['terms', 'Terms']], null), active: tab });
  if (tab === 'moves') return movesModel(body, L);
  const v = { methodology: 'methodology', calibration: 'calibration', markets: 'markets', glossary: 'glossary', terms: 'disclaimer' }[tab];
  return U.legacy(v, body, params);
}

HW.page('standings', renderStandings);
HW.page('teams', renderTeams);
HW.page('players', renderPlayers);
HW.page('lab', renderLab);
['compare', 'compare-players', 'compare-teams'].forEach(n => HW.page(n, renderLab));
['model', 'glossary', 'methodology', 'disclaimer'].forEach(n => HW.page(n, renderModel));
})(window.HW);
