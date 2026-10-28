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
  /* only once within reach (no more than half the games left, the league block's rule): an 80 in October says nothing */
  const left = (s.current || {}).remaining;
  if (k && isNum(left) && mg[k] > left / 2) return '<span class="qk-muted" data-tip="The magic number shows once it is within reach">—</span>';
  return k ? '<span data-tip="Magic number for a playoff place: wins, or losses by the first team out, to clinch">' + mg[k] + '</span>' : '';
}

/* The league module's options (docs/_design/league.js, QKL) from season.json: the teams, the race chart's groups
   (NBA: the six divisions, then the conferences; WNBA: the league, then the conferences) and the race log
   (data/<L>/race_log.json, through the site's cached loader). */
function leagueOpts(season, L, S) {
  /* season.json "league_block" (the payload's "league" is the league code); an object under "league" is read too */
  const lg = season && (season.league_block || (season.league && typeof season.league === 'object' ? season.league : null));
  if (!lg || !window.QKL) return null;
  const st = season.standings || {}, info = season.teams || {}, fmt = season.format || {}, teams = {}, groups = [];
  const confs = Object.keys(st).filter(c => (st[c] || []).length).sort();
  const all = [];
  confs.forEach(c => (st[c] || []).forEach(r => { all.push(r); const t = String(r.team);
    teams[t] = { abbr: HW.teamAbbr(L, t), name: HW.teamName(L, t), colour: (info[t] || {}).colour, href: HW.teamHref(L, t, S) }; }));
  if (fmt.seeding === 'league') groups.push({ key: '__all', label: 'League', teams: all.map(r => String(r.team)) });
  const divs = [];
  all.forEach(r => { if (r.division && divs.indexOf(r.division) < 0 && confs.indexOf(r.division) < 0) divs.push(r.division); });
  divs.sort().forEach(d => groups.push({ key: 'd:' + d, label: d, teams: all.filter(r => r.division === d).map(r => String(r.team)) }));
  confs.forEach(c => groups.push({ key: 'c:' + c, label: c, teams: (st[c] || []).map(r => String(r.team)) }));
  return { league: lg, teams: teams, groups: groups, season: String(S), loadLog: () => HW.load(HW.lpath('race_log.json', L)),
    title: 'How the race is shaping up', unitGames: 'games' };
}
HW.leagueOpts = leagueOpts;

function standingsTable(node, L, S, rows, sim, fmt, league, lo) {
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
    { key: 'seedN', label: '#', num: true, fmt: (v, r) => (lo ? QKL.toggle(String(r.team), HW.teamName(L, r.team)) : '') + v },
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
  /* round 9: a finished season (no simulation) carries its final flags: z top seed, x playoffs, p play-in, e out */
  if (!live && HW.recap && HW.recap.flagSeason) {
    const fl = HW.recap.flags(HW.recap.flagSeason);
    if (Object.keys(fl).length) cols.push({ key: 'team', label: 'Finish', sort: false, fmt: v => HW.recap.flagHTML(fl[String(v)]), tip: 'z top seed, x playoffs, p out in the play-in, e missed the postseason' });
  }
  if (lo) cols.push({ key: 'team', label: 'Profile', sort: false, tip: 'What stands out about the team; press + for its full card (strengths, weaknesses and the race)',
    fmt: (v, r) => QKL.chip(lo, String(r.team)) || '<span class="qk-muted">—</span>' });
  QK.leaderboard(node, { columns: cols, rows: data, dense: true, rowHref: r => HW.teamHref(L, r.team, S) });
  if (lo) QKL.wire(node, lo);
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
    if (HW.recap) HW.recap.flagSeason = season;
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
      (views.length > 1 ? '<div class="qk-seg" id="st-seg" role="group" aria-label="Group" style="margin:0 16px 12px">' + views.map(v => '<button type="button" data-value="' + esc(v[0]) + '" aria-pressed="' + (v[0] === first) + '">' + esc(v[1]) + '</button>').join('') + '</div>' : '') + '<div id="st-table"></div>' +
      (open ? '<div style="padding:12px 16px 16px">' + QK.note('<b>Playoffs 60%</b> means the team made the playoffs in about 6 of every 10 simulated seasons. <b>Proj W</b> is the average win total across them; hover it for the range that holds nine seasons in ten.' + (season.league && window.QKL ? ' <b>+</b> opens a team’s card: its strengths and weaknesses against the rest of the league and where its race stands.' : '')) + '</div>' : ''), { flush: true });
    /* round 9: the playoff bars and the race chart moved to Chances; the player leaders to the Scouting Room */
    if (open) h += '<p class="hw-flex" style="margin-top:12px">' + U.link(HW.href(L, 'standings', S) + (HW.sq(L, S) ? '&' : '?') + 'tab=chances', 'Every chance: the title race, the playoff picture, seeds and win totals') + '</p>';
    const lo = leagueOpts(season, L, S);
    if (lo) h += '<div id="st-shape"></div>';
    h += QK.explain('The leaders and the bottom five on every number, by role, are in the <a class="qk-link" href="' + esc(HW.href(L, 'scout', S) + (HW.sq(L, S) ? '&' : '?') + 'view=leaders') + '">Scouting Room ▸ Leaders</a>.', { title: 'Looking for the player leaders?' });
    node.innerHTML = h;
    const draw = k => standingsTable(document.getElementById('st-table'), L, S, k === '__all' ? all() : (st[k] || []), sim, fmt, k === '__all', lo);
    draw(first);
    const seg = document.getElementById('st-seg');
    if (seg) QK.seg(seg, draw);
    if (lo) QKL.shape(document.getElementById('st-shape'), lo);
    if (!live) HW.setMeta('');
  });
}
/* Top and bottom performers (QKL.leaders): all players on our plus-minus first, then guards, wings and bigs on their
   spec headline sets (data/<L>/<S>/performers.json, oddsmarkets/basketball/analytics/performers.py: qualified players
   only, the catalogue's minutes floor), then the teams on the league block's team set (season.json, already loaded). */
function performers(host, season, L, S) {
  if (!host) return;
  const lg = season && (season.league_block || (season.league && typeof season.league === 'object' ? season.league : null));
  const info = (season && season.teams) || {};
  HW.load(HW.path('performers.json', L, S)).then(pf => {
    if (!U.alive(host)) return;
    const views = ((U.ok(pf) && pf.views) || []).slice();
    const tv = lg ? QKL.teamView(lg, { label: 'Teams', peer: 'teams', ours: 'Team rating model', name: t => HW.teamName(L, t) }) : null;
    if (tv) views.push(tv);
    QKL.leaders(host, { data: { views: views }, title: 'Who leads the ' + HW.leagueName(L) + ', and who is struggling',
      sub: 'The top five and the bottom five on each key number: every player on our plus-minus first, then guards, wings and bigs on the numbers that matter for each role, and the teams. Qualified players only; each name opens the player page.',
      team: t => ({ abbr: HW.teamAbbr(L, t), name: HW.teamName(L, t), colour: (info[t] || {}).colour, href: HW.teamHref(L, t, S) }),
      href: id => HW.playerHref(L, id, S),
      empty: 'The boards fill once players reach the minutes floor (a fifth of the season’s most played).' });
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

/* Races (round 9: the award races moved here from Players): our chance for each award; before the season's first
   games, last season's final races, said so. */
function racesTab(body, L, S, params) {
  return HW.load(HW.path('awards.json', L, S)).then(d => {
    if (!U.alive(body)) return null;
    const has = x => !!x && Object.keys(x).some(k => x[k] && x[k].model && Object.keys(x[k].model).length);
    const prev = HW.seasons(L).filter(x => x < S)[0];
    if (has(U.ok(d) ? d : null) || !prev) return U.legacy('awards', body, params);
    body.innerHTML = '<div class="qk-note" style="margin-bottom:14px">No ' + esc(HW.seasonLabel(L, S)) + ' award races until the season starts: these are the final ' + esc(HW.seasonLabel(L, prev)) + ' races.</div><div></div>';
    return U.legacy('awards', body.lastChild, Object.assign({}, params, { season: prev }));
  });
}

function renderStandings(el, params) {
  const L = U.L(params), S = U.S(params);
  // the market comparison lives on the Model page now; old links land there
  if (((params.query || {}).tab) === 'markets') { HW.go(HW.href(L, 'model', S) + (HW.sq(L, S) ? '&' : '?') + 'tab=markets'); return null; }
  const q = params.query || {};
  const tab = q.tab === 'odds' ? 'chances' : U.tab(params, ['table', 'chances', 'bracket', 'history', 'races'], 'table');
  const body = U.section(el, { title: 'Standings', kicker: U.kicker(L, S), sub: 'Where every team stands, our playoff and title chances from the season simulation, and the bracket.',
    tabs: U.tabs(L, 'standings', [['table', 'Table'], ['chances', 'Chances'], ['bracket', 'Bracket'], ['history', 'History', false], ['races', 'Races']], S), active: tab });
  if (tab === 'chances') return HW.chances.tab(body, L, S);
  if (tab === 'table') return standingsTab(body, L, S, params);
  if (tab === 'races') return racesTab(body, L, S, params);
  if (tab === 'history') return (HW.historyTab || historyTab)(body, L);
  const v = { bracket: 'playoffs' }[tab];
  return U.legacy(v, body, params);
}

// ── Teams: hw-teams.js (round 9: the power board, profile grid, style map, strengths, head to head, through the season)

// ── Players ────────────────────────────────────────────────────────────────

/* The leaderboard's metrics: counting boards (everyone who qualifies ranks), then the role metric set. */
const COUNT = [['pts_g', 'Points a game', '1'], ['reb_g', 'Rebounds a game', '1'], ['ast_g', 'Assists a game', '1'], ['tpm_g', 'Threes a game', '1'], ['stl_g', 'Steals a game', '1'], ['blk_g', 'Blocks a game', '1']];

const WAR_LABEL = 'Wins above replacement (WAR)';
const oursOf = k => (HW.ours ? HW.ours.of(k) : null);
function leadersTab(node, L, S) {
  return Promise.all([U.catalogue(L, S), U.roles(L, S), HW.ours ? HW.ours.load() : null]).then(res => HW.fx.joinValue(L, res[0].S, res[0].cat).then(() => res)).then(res => {
    if (!U.alive(node)) return;
    const r = res[0], cat = r.cat;
    if (!U.ok(cat) || !Object.keys(cat.players || {}).length) { node.innerHTML = U.empty('No player numbers yet', 'The catalogue fills in once games are played.'); return; }
    const SS = r.S;
    const roles = r.fallback ? {} : res[1];
    const finish = rl => {
      const P = cat.players;
      const ids = Object.keys(P).filter(id => P[id].qualified);
      const keys = COUNT.map(x => x[0]).concat(['hpm', 'hpm_o', 'hpm_d', 'war', 'pts100', 'ts_add', 'pox100', 'ast_pct', 'drb_pct', 'stl_pct', 'blk_pct', 'ts']).filter(k => ids.some(id => isNum((P[id].values || {})[k])));
      const lab = k => { const c = COUNT.find(x => x[0] === k); return c ? c[1] : k === 'war' ? WAR_LABEL : U.mMeta(k).label; };
      const fmtK = (k, v) => { const c = COUNT.find(x => x[0] === k); return c || k === 'war' ? U.f(v, 1) : U.fmtM(k, v); };
      const picker = HW.ours ? HW.ours.groups(keys.map(k => ({ key: k, label: lab(k), group: COUNT.find(x => x[0] === k) ? 'per game' : 'rates' }))) : [{ name: 'Metrics', items: keys.map(k => ({ key: k, label: lab(k) })) }];
      let h = r.fallback ? '<div class="qk-note" style="margin-bottom:14px">No ' + esc(HW.seasonLabel(L, S)) + ' regular-season games yet: these are the final ' + esc(HW.seasonLabel(L, SS)) + ' numbers.</div>' : '';
      /* v4: Who's hot, the black power list: the top qualified name on five boards */
      const HOT = [['pts_g', 'Most points', 'points a game', U.f], ['reb_g', 'Most rebounds', 'rebounds a game', U.f], ['ast_g', 'Most assists', 'assists a game', U.f],
        ['hpm', 'Biggest impact', 'points per 100 (HPM)', (x, d) => U.signed(x, d)], ['war', 'Most wins added', 'wins above replacement', x => U.f(x, 1)], ['ts', 'Best shooter', 'true shooting', x => HW.fmtVal(x, 'pct')]];
      const EXPL = { pts_g: 'Per game, among players over the minutes floor.', reb_g: 'Per game, among players over the minutes floor.', ast_g: 'Per game, among players over the minutes floor.',
        hpm: 'Points per 100 trips the player adds to the team’s margin over an average player. Our impact model.', war: 'Wins added over a replacement-level player in the minutes played. Our value model, from HPM.', ts: 'Points per shot, with threes and free throws counted.' };
      const hot = HOT.map(b => { const top = ids.filter(id => isNum((P[id].values || {})[b[0]])).sort((x, y) => P[y].values[b[0]] - P[x].values[b[0]]);
        if (!top.length) return null; const a = P[top[0]], n = top[1] ? P[top[1]] : null;
        return { sport: 'basketball', kicker: HW.leagueName(L) + ' · ' + HW.teamAbbr(L, a.team), title: b[1], name: a.name, value: b[3](a.values[b[0]], 1), unit: b[2], next: n ? { name: n.name, value: b[3](n.values[b[0]], 1) } : null, expl: EXPL[b[0]], href: HW.playerHref(L, top[0], SS) }; }).filter(Boolean).slice(0, 5);
      if (hot.length) h += QK.band(QK.sectionHead({ kicker: 'Who’s hot', title: 'The leaders, stat by stat', sub: 'The top qualified name on five boards, the next best behind, and what the number means.' }) + QK.hotRow(hot));
      h += '<div class="hw-flex" style="margin-bottom:14px"><input class="qk-input hw-search" id="pl-q" type="search" placeholder="Find a player…" aria-label="Find a player" autocomplete="off"><span class="hw-quiet">Qualified: ' + Number(cat.min_floor || 0).toLocaleString('en-GB') + '+ minutes (' + ids.length + ' players). Heat cells: percentile within the player’s role (guards, wings, bigs).</span></div><div id="pl-hits"></div>';
      h += U.card2('Pick a stat, pick a role', 'Every cell is coloured by the percentile within the role, cold (blue) to hot (red).',
        '<div class="hw-flex" style="margin-bottom:12px"><select class="qk-select" id="pl-k" aria-label="Metric">' + picker.map(g => '<optgroup label="' + esc(g.name) + '">' + g.items.map(it => '<option value="' + it.key + '">' + esc(it.label) + '</option>').join('') + '</optgroup>').join('') + '</select>' +
        '<div class="qk-seg" id="pl-r" role="group" aria-label="Role"><button type="button" data-value="" aria-pressed="true">All</button><button type="button" data-value="G" aria-pressed="false">Guards</button><button type="button" data-value="W" aria-pressed="false">Wings</button><button type="button" data-value="B" aria-pressed="false">Bigs</button></div></div><div id="pl-lbx"></div><div id="pl-lb" class="qk-ours-cols"></div>', { flush: false });
      h += '<div class="qk-grid hw-sec"><div class="qk-span-12">' + U.card2('Impact at both ends', 'HPM per 100 possessions, offence against defence; qualified players, size is minutes', U.chart('pl-sc', 440, 'Impact at both ends') +
        QK.note('<b>HPM</b> is the points per 100 trips a player adds to the team’s margin over an average player. Top right helps at both ends; most stars sit right of centre, and the best defenders sit high.')) + '</div></div>';
      node.innerHTML = h;
      const st = { k: keys.indexOf('hpm') >= 0 ? 'hpm' : keys[0], r: '' };
      const drawLb = () => {
        const k = st.k, low = U.mMeta(k).better === 'low' && !COUNT.find(x => x[0] === k);
        const list = ids.filter(id => isNum((P[id].values || {})[k]) && (!st.r || U.roleOf(P[id], id, rl) === st.r)).sort((a, b) => (low ? 1 : -1) * (P[a].values[k] - P[b].values[k])).slice(0, 25);
        const rows = list.map(id => { const p = P[id], v = p.values || {}, role = U.roleOf(p, id, rl);
          return { id: id, name: p.name, team: p.team, sub: [HW.teamAbbr(L, p.team), (U.ROLE1 || {})[role] || p.pos].filter(Boolean).join(' · '), val: v[k], val_p: U.rolePctl(cat, rl, id, k),
            hpm: v.hpm, hpm_p: U.rolePctl(cat, rl, id, 'hpm'), war: v.war, ts: v.ts, ts_p: U.rolePctl(cat, rl, id, 'ts'), min: p.min, gp: p.gp }; });
        const xb = document.getElementById('pl-lbx');
        if (xb) xb.innerHTML = HW.ours ? HW.ours.explain([k], { label: lab }) : '';
        QK.leaderboard(document.getElementById('pl-lb'), { dense: true, rank: true, rows: rows, rowHref: x => HW.playerHref(L, x.id, SS), columns: [
          { key: 'name', label: 'Player', type: 'entity', sub: 'sub', mark: x => U.team(L, x.team), href: x => HW.playerHref(L, x.id, SS) },
          { key: 'val', label: lab(k), type: 'pctl', pctl: 'val_p', fmt: v => fmtK(k, v), tip: HW.ours ? HW.ours.tip(k, '') : '' },
          { key: 'hpm', label: 'HPM', type: 'pctl', pctl: 'hpm_p', fmt: v => U.signed(v, 1), tip: HW.ours ? HW.ours.tip('hpm', 'Total impact per 100 possessions') : 'Total impact per 100 possessions' }]
          .concat(k !== 'war' && rows.some(x => isNum(x.war)) ? [{ key: 'war', label: 'WAR', num: true, fmt: v => U.f(v, 1), tip: HW.ours ? HW.ours.tip('war', 'Wins added over a replacement-level player in the minutes played, from HPM.') : '' }] : []).concat([
          { key: 'ts', label: 'TS%', type: 'pctl', pctl: 'ts_p', fmt: v => HW.fmtVal(v, 'pct') },
          { key: 'gp', label: 'GP', num: true }, { key: 'min', label: 'Min', type: 'bar', fmt: v => Number(Math.round(v || 0)).toLocaleString('en-GB') }]) });
        const vh = document.querySelector('#pl-lb th[data-k="val"]');
        if (vh) vh.classList.toggle('qk-ours-th', !!oursOf(k));
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
const CAT_KEYS = ['hpm', 'hpm_o', 'hpm_d', 'war', 'pts100', 'ts_add', 'ast_pct', 'drb_pct', 'stl_pct', 'blk_pct'];
function catalogueTab(node, L, S) {
  return Promise.all([U.catalogue(L, S), U.roles(L, S), U.isCur(L, S) ? U.movement(L) : Promise.resolve(null), HW.ours ? HW.ours.load() : null]).then(res => HW.fx.joinValue(L, res[0].S, res[0].cat).then(() => res)).then(res => {
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
      const pick = HW.ours ? HW.ours.groups(HW.ours.relabel(cat.metrics || [], 'player')) : HW.fx.groups(cat.metrics || []);
      node.innerHTML = (r.fallback ? '<div class="qk-note" style="margin-bottom:14px">No ' + esc(HW.seasonLabel(L, S)) + ' regular-season games yet: these are the final ' + esc(HW.seasonLabel(L, SS)) + ' numbers.</div>' : '') +
        U.card2('Every player', 'Heat cells: the percentile within the player’s role (guards, wings, bigs) or the whole league, 100 = best. Percentiles need ' + Number(cat.min_floor || 0).toLocaleString('en-GB') + '+ minutes.' + (mv ? ' Chance of moving: ' + esc(U.mvHorizon(mv)) + '.' : ''),
          '<div class="hw-catctl"><input class="qk-input hw-search" id="ct-q" type="search" placeholder="Player or team…" aria-label="Find a player" value="' + esc(CAT.q) + '">' +
          '<div class="qk-seg" id="ct-role" role="group" aria-label="Role">' + [['', 'All'], ['G', 'Guards'], ['W', 'Wings'], ['B', 'Bigs']].map(x => '<button type="button" data-value="' + x[0] + '" aria-pressed="' + (CAT.role === x[0]) + '">' + x[1] + '</button>').join('') + '</div>' +
          '<div class="qk-seg" id="ct-basis" role="group" aria-label="Percentiles against">' + [['role', 'Against the role'], ['league', 'Against the league']].map(x => '<button type="button" data-value="' + x[0] + '" aria-pressed="' + (CAT.basis === x[0]) + '">' + x[1] + '</button>').join('') + '</div>' +
          '<select class="qk-select" id="ct-team" aria-label="Team"><option value="">All teams</option>' + teams.map(t => '<option value="' + esc(t) + '"' + (t === CAT.team ? ' selected' : '') + '>' + esc(HW.teamName(L, t)) + '</option>').join('') + '</select>' +
          '<select class="qk-select" id="ct-extra" aria-label="Add a column"><option value="">Add a column…</option>' + pick.map(g => '<optgroup label="' + esc(g.name) + '">' + g.items.map(m => '<option value="' + esc(m.key) + '"' + (m.key === CAT.extra ? ' selected' : '') + '>' + esc(m.label) + '</option>').join('') + '</optgroup>').join('') + '</select>' +
          '<label class="hw-quiet hw-chk"><input type="checkbox" id="ct-all"' + (CAT.all ? ' checked' : '') + '> include players under the floor</label></div>' +
          (mv ? '<div class="hw-mvline" style="margin-top:10px"><span class="qk-muted">Chance of moving, split by how:</span>' + U.mvKeys(mv) + '</div>' : '') +
          '<div id="ct-sub" class="hw-quiet" style="margin:8px 0"></div><div id="ct-table" class="qk-ours-cols"></div>' + (HW.ours ? HW.ours.explain(['hpm', 'war'], { label: k => (k === 'war' ? WAR_LABEL : U.mMeta(k).label) }) : ''));
      const pctOf = (id, k) => (CAT.basis === 'league' ? ((P[id].pct || {})[k]) : U.rolePctl(cat, rl, id, k));
      const fmtK = (k, v) => (meta[k] && !U.MSET.meta[k] ? HW.fmtVal(v, meta[k].fmt) : U.fmtM(k, v));
      const lab = k => (U.MSET.meta[k] ? U.mMeta(k).label : HW.ours ? HW.ours.label(k, (meta[k] || {}).label || k) : (meta[k] || {}).label || k);
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
          .concat(keys.map(k => ({ key: k, label: k === 'war' ? 'WAR' : lab(k).replace(/ \(HPM\)$/, ''), type: k === 'war' ? undefined : 'pctl', num: k === 'war', pctl: k === 'war' ? undefined : k + '_p', fmt: v => (k === 'war' ? U.f(v, 1) : fmtK(k, v)),
            tip: HW.ours && HW.ours.of(k) ? HW.ours.tip(k, k === 'war' ? 'Wins added over a replacement-level player in the minutes played, from HPM.' : U.mMeta(k).desc) : U.mMeta(k).desc || (meta[k] || {}).desc || '' })))
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
  const body = U.section(el, { title: 'Players', kicker: U.kicker(L, S), sub: 'Leaderboards against each player’s role (guards, wings, bigs), the full catalogue with percentiles, and the award races. Open a player for the short version, season by season and value.',
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
  /* round 9: the standing order on every site: How it works, How we're doing, Our forecasts v the market, Who moves next
     (the validation; the fan board is Value ▸ Who moves next), Glossary, Terms */
  const body = U.section(el, { title: 'Model', kicker: HW.leagueName(L) + ' · how it works', sub: 'How the models are built, how well they have done, and what every number means.',
    tabs: U.tabs(L, 'model', [['methodology', 'How it works'], ['calibration', 'How we’re doing'], ['markets', 'Our forecasts v the market'], ['moves', 'Who moves next'], ['glossary', 'Glossary'], ['terms', 'Terms']], null), active: tab });
  if (tab === 'moves') return movesModel(body, L);
  const v = { methodology: 'methodology', calibration: 'calibration', markets: 'markets', glossary: 'glossary', terms: 'disclaimer' }[tab];
  if (tab !== 'methodology' && tab !== 'calibration') return U.legacy(v, body, params);
  /* Round 6: "How we're doing" (the calibration tab, id kept so ?tab=calibration still works): our favourites' record
     over the last week (index.json digest.record) as tiles, then the game model's record from <L>/calibration.json
     (QK.doing -> QK.howSure). The methodology tab links it; the overview no longer carries either. */
  /* round 9: How it works opens for fans (hw-method.js: what the site does, one diagram per model); the technical
     document (sources, endpoints, code paths, constants) is folded under "Technical detail" */
  if (tab === 'methodology') {
    const deep = !!((params.rest || [])[0]);
    body.innerHTML = (HW.method ? HW.method.html(L) : '') + '<details class="hw-fold hw-tech"' + (deep ? ' open' : '') + '><summary>Technical detail: data sources, formulas, code paths and every constant</summary><div></div></details>';
    return U.legacy(v, body.querySelector('.hw-tech > div'), params);
  }
  body.innerHTML = '<section class="qk-section hw-sure" id="md-sure" hidden></section><div></div>';
  HW.load(L + '/calibration.json').then(cj => {
    const box = body.querySelector('#md-sure');
    const rec = ((HW.leagueInfo(L) || {}).digest || {}).record || null;
    const ok = U.ok(cj) && QK.calib.find(cj);
    if (!box || (!ok && !rec)) return;
    const ss = ok ? (cj.seasons || []).slice().sort((a, b) => a - b) : [];
    const span = ss.length ? HW.seasonLabel(L, ss[0]) + ' to ' + HW.seasonLabel(L, ss[ss.length - 1]) : '';
    box.hidden = false;
    QK.doing(box, { record: rec, calibration: ok ? cj : null, league: HW.leagueName(L), span: span, subject: 'the home team',
      sub: 'Our favourites over the last week, then every pre-game forecast in the test seasons' + (span ? ' (' + span + ')' : '') + ', grouped by the chance we gave the home team, against how often the home team won. When the two match, our numbers mean what they say.' });
  });
  return U.legacy(v, body.lastChild, params);
}

HW.page('standings', renderStandings);
HW.page('players', renderPlayers);
HW.page('lab', renderLab);
['compare', 'compare-players', 'compare-teams'].forEach(n => HW.page(n, renderLab));
['model', 'glossary', 'methodology', 'disclaimer'].forEach(n => HW.page(n, renderModel));
})(window.HW);
