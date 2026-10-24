/* The Quant Rink — the section pages of the redesigned IA (October 2026).
 *
 *   #/standings[/<S>]?tab=  table (new: wild card / divisions / league with odds, projected points range) · odds ·
 *                           ratings · lottery (the pre-redesign standings views) · bracket (playoffs) · markets · history
 *   #/teams?tab=            clubs (new: tiles by division, offence v defence chart) · stats (the team catalogue)
 *   #/players?tab=          leaders (new, with sample floors, and a search) · skaters · goalies · lines · awards (new) · boards
 *   #/lab?tab=              lab · compare            #/compare/<a>/<b> renders inside Lab
 *   #/model?tab=            methodology · calibration · glossary · terms
 *                           #/glossary/<key> and #/methodology/<part> render inside Model
 * Old routes (#/skaters, #/playoffs, #/markets, #/calibration ...) are redirected by core.js (REDIRECTS).
 *
 * Kit v4 "Broadcast" (MIGRATION_V4.md): friendly section titles (the volt tag says what it is, the Bebas title
 * the story), explain strips (QK.note) under the numbers that need a sentence, the black power list (QK.band +
 * QK.hotRow) on Players and on the standings (the clubs on top of four boards), our playoff chance as a bar in each
 * club's colour, "We say it. Then we check it." (QK.howSure, from data/calibration.json) at the top of the Model
 * page, and season forecasts in team colours without the market tick (the market stays on game pages and the Model
 * page only). */
(function (RK) {
'use strict';

const U = RK.ui, esc = RK.esc, isNum = RK.isNum;

/* ── standings ───────────────────────────────────────────────────────────── */
const ST_TABS = [['table', 'Standings'], ['odds', 'Playoff chances'], ['ratings', 'Ratings'], ['lottery', 'Draft lottery'], ['bracket', 'Bracket'], ['markets', 'Season forecasts'], ['history', 'History']];

/* our chance as a bar in the club's colour (lifted to 3:1 on the card), the number beside it */
function teamBarCell(v, team) {
  if (!isNum(v)) return '—';
  return '<span class="qk-barcell"><span>' + U.pct(v) + '</span><i aria-hidden="true"><b style="width:' + Math.min(100, 100 * v).toFixed(1) + '%;background:' + esc(QK.color.team(RK.teamColourRaw(team))) + '"></b></i></span>';
}

/* The league module's options (docs/_design/league.js, QKL) from season.json: the clubs, the race chart's groups
   (divisions, then conferences, then the league) and the race log (data/race_log.json, the site's cached loader). */
function leagueOpts(d, S) {
  const L = d && d.league;
  if (!L || !window.QKL) return null;
  const rows = ((d.standings || {}).rows || []), teams = {};
  rows.forEach(r => { teams[r.team] = { abbr: RK.teamAbbr(r.team), name: RK.teamName(r.team), colour: RK.teamColourRaw(r.team), href: RK.teamHref(r.team, S) }; });
  const groups = [];
  ((d.standings || {}).divisions || []).forEach(dv => groups.push({ key: dv.division, label: dv.division, teams: (dv.teams || []).slice() }));
  ['Eastern', 'Western'].forEach(c => { const ts = rows.filter(r => r.conference === c).map(r => r.team); if (ts.length) groups.push({ key: c, label: c.slice(0, 4), teams: ts }); });
  return { league: L, teams: teams, groups: groups, season: String(S), loadLog: () => RK.load('race_log.json'), title: 'How the race is shaping up', unitGames: 'games' };
}
RK.leagueOpts = leagueOpts;

/* One standings block as a v2 leaderboard: heat cells for the 5v5 xG share and our rating (league percentile among
   the 32 clubs), our playoff chance as a bar, the cut line dashed. */
function stBoard(node, g, pc, lo) {
  const rows = g.rows.map((r, i) => Object.assign({}, r, { pos: g.label ? g.label(i) : String(i + 1), cut: g.cut !== undefined && i === g.cut, name: RK.teamShort(r.team),
    l10s: Array.isArray(r.l10) ? r.l10.join('-') : (r.l10 || ''), xp: pc.xgf[r.team], rp: pc.rating[r.team] }));
  QK.leaderboard(node, { dense: true, rowClass: r => (r.cut ? 'rk-cut' : ''), rowHref: r => RK.teamHref(r.team), columns: [
    { key: 'pos', label: '#', sort: false, fmt: (v, r) => (lo ? QKL.toggle(r.team, RK.teamName(r.team)) : '') + '<span class="qk-muted">' + esc(v) + '</span>' },
    { key: 'name', label: 'Club', type: 'entity', mark: r => U.team(r.team), href: r => RK.teamHref(r.team), sub: 'clinch' },
    { key: 'gp', label: 'GP', num: true }, { key: 'w', label: 'W', num: true }, { key: 'l', label: 'L', num: true }, { key: 'otl', label: 'OTL', num: true },
    { key: 'pts', label: 'PTS', num: true, fmt: v => '<b>' + v + '</b>' }, { key: 'p_pct', label: 'P%', num: true, fmt: v => RK.fmtVal(v, '3') },
    { key: 'gf', label: 'GF', num: true }, { key: 'ga', label: 'GA', num: true }, { key: 'diff', label: 'Diff', num: true, fmt: v => '<span class="' + U.cls(v) + '">' + U.signed(v, 0) + '</span>' },
    { key: 'xgf_pct', label: 'xGF%', type: 'pctl', pctl: 'xp', fmt: v => U.pct(v, 1), tip: 'Share of 5v5 expected goals; the cell is coloured by its rank among the 32 clubs' },
    { key: 'rating', label: 'Rating', type: 'pctl', pctl: 'rp', fmt: v => U.signed(v, 2), tip: 'Our team rating: expected goal difference a game against an average club' },
    { key: 'p_playoffs', label: 'Playoffs', num: true, fmt: (v, r) => teamBarCell(v, r.team), tip: 'Our chance of a playoff spot, from 20,000 simulated seasons' },
    { key: 'p_cup', label: 'Cup', num: true, fmt: v => (isNum(v) ? U.pct(v, 1) : '—'), tip: 'Our chance of winning the Stanley Cup' },
    { key: 'l10s', label: 'L10', sort: false }, { key: 'streak', label: 'Strk', sort: false }
  ].concat(lo ? [{ key: 'team', label: 'Profile', sort: false, tip: 'What stands out about the club; press + for its full card (strengths, weaknesses and the race)', fmt: (v, r) => QKL.chip(lo, r.team) || '<span class="qk-muted">—</span>' }] : []), rows: rows });
  if (lo) QKL.wire(node, lo);
}

function standingsNew(node, S) {
  node.innerHTML = QK.skeleton('lines', 8);
  return RK.loadYear('season.json', S).then(d => {
    if (!U.alive(node)) return;
    if (!RK.ok(d) || !((d.standings || {}).rows || []).length) { node.innerHTML = U.card2('Standings', '', QK.empty('Not built yet', RK.reason(d))); return; }
    const st = d.standings, rows = st.rows, by = {};
    rows.forEach(r => { by[r.team] = r; });
    const lo = leagueOpts(d, S);
    const sim = (d.sim && d.sim.teams) || {};
    const wc = st.wild_card || {};
    const early = rows.every(r => (r.gp || 0) < U.TEAM_MIN_GP);
    const pc = { xgf: {}, rating: {} };
    if (!early) rows.forEach(r => { pc.xgf[r.team] = U.rankPct(rows.map(x => x.xgf_pct), r.xgf_pct); pc.rating[r.team] = U.rankPct(rows.map(x => x.rating), r.rating); });
    const top = (list, k) => list.filter(r => isNum(r[k])).sort((a, b) => b[k] - a[k])[0];
    const lead = rows.slice().sort((a, b) => (b.pts - a.pts) || (b.p_pct - a.p_pct))[0];
    const best = top(rows, 'rating');
    const simRows = Object.keys(sim).map(t => Object.assign({ team: t }, sim[t]));
    const pres = top(simRows, 'p_pres'), cup = top(simRows, 'p_cup');
    const tiles = QK.stats([
      cup ? { label: 'Cup favourite', value: RK.teamAbbr(cup.team) + ' ' + U.pct(cup.p_cup, 0), signal: true, href: RK.teamHref(cup.team, S), sub: 'our chance, from ' + QK.fmt.num((d.sim || {}).n || 20000) + ' simulated seasons' } : null,
      pres ? { label: 'Presidents’ Trophy', value: RK.teamAbbr(pres.team) + ' ' + U.pct(pres.p_pres, 0), href: RK.teamHref(pres.team, S), sub: 'our chance of the best record', tip: 'Our chance of finishing with the most points in the league' } : null,
      lead ? { label: 'Most points', value: RK.teamAbbr(lead.team) + ' ' + lead.pts, href: RK.teamHref(lead.team, S), sub: RK.record(lead.w, lead.l, lead.otl) + ' in ' + lead.gp + ' games' } : null,
      best ? { label: 'Top-rated club', value: RK.teamAbbr(best.team) + ' ' + U.signed(best.rating, 2), href: RK.teamHref(best.team, S), sub: 'goals a game better than an average club', tip: 'Our team rating: expected goal difference per game against an average club' } : null
    ]);
    /* Who's on top: the club leading four boards, with the next best and what the number means */
    const two = (list, k) => list.filter(r => isNum(r[k])).sort((a, b) => b[k] - a[k]).slice(0, 2);
    const hotT = (title, list, k, f, expl) => { const t = two(list, k); return t.length && !(t[1] && f(t[0][k]) === f(t[1][k])) ? { sport: 'hockey', kicker: 'NHL · ' + RK.teamAbbr(t[0].team), title: title, name: RK.teamName(t[0].team), value: f(t[0][k]), href: RK.teamHref(t[0].team, S), next: t[1] ? { name: RK.teamShort(t[1].team), value: f(t[1][k]) } : null, expl: expl } : null; };
    const nSim = QK.fmt.num((d.sim || {}).n || 20000);
    const hot = [hotT('Cup favourite', simRows, 'p_cup', x => U.pct(x, 0), 'Our chance of winning the Stanley Cup, from ' + nSim + ' simulated seasons.'),
      hotT('Presidents’ Trophy', simRows, 'p_pres', x => U.pct(x, 0), 'Our chance of finishing with the best record in the league.'),
      hotT('Most points', rows, 'pts', x => String(x), 'Two for a win, one for an overtime or shootout loss.'),
      hotT('Top-rated club', rows, 'rating', x => U.signed(x, 2), 'Goals a game better than an average club, all situations: our rating.'),
      hotT('Best 5v5 chance share', rows, 'xgf_pct', x => U.pct(x, 1), 'Share of the 5-on-5 expected goals: over a season, the number that best predicts the next games.' + (early ? ' Early: under ' + U.TEAM_MIN_GP + ' games.' : ''))].filter(Boolean);
    /* the black power list replaces the stat tiles when it has enough cards (it carries the same leaders, the next best
       and a line on each number); otherwise the tiles stay */
    node.innerHTML = (hot.length >= 3 ? QK.band(QK.sectionHead({ kicker: 'Who’s on top', title: 'The clubs to beat', sub: 'The club leading each board, the next best, and what the number means.' }) + QK.hotRow(hot), { cls: 'rk-hot rk-hot-top' }) : '<div class="rk-kpis">' + tiles + '</div>') +
      QK.sectionHead({ kicker: 'The table · ' + RK.seasonLabel(S), title: 'Where everyone stands', sub: esc(RK.regGames(S)) + ' games a club · 2 points a win, 1 for an overtime or shootout loss.' + (early ? ' The heat colours start after ' + U.TEAM_MIN_GP + ' games: earlier ranks are noise.' : ' xGF% and rating cells are coloured by rank among the 32 clubs (red best, blue worst).'), html: true,
        actions: '<div class="qk-seg" id="st-view" role="group" aria-label="Standings view">' + [['wc', 'Wild card'], ['div', 'Divisions'], ['league', 'League']].map((v, i) => '<button type="button" aria-pressed="' + (i === 0) + '" data-value="' + v[0] + '">' + v[1] + '</button>').join('') + '</div>' }) +
      '<div id="st-body"></div>' +
      QK.note('<b>Reading the table.</b> <b>P%</b> is the share of the points available that a club has taken. <b>xGF%</b> is its share of the 5-on-5 chances (expected goals): over a season it predicts the next games better than the goal difference. <b>Rating</b> is our estimate of how many goals a game better or worse than an average club it is. <b>Playoffs</b> is our chance from ' + QK.fmt.num((d.sim || {}).n || 20000) + ' simulated seasons: 80% still misses about 1 time in 5.' + (lo ? ' <b>+</b> opens a club’s card: its strengths and weaknesses against the other 31 and where its race stands.' : '')) +
      (lo ? '<div id="st-race"></div>' : '') +
      '<section class="qk-section">' + QK.sectionHead({ kicker: 'Season simulation', title: 'Where they finish', sub: 'Each club’s points at the end of the regular season across the simulated seasons: the dot is the mean, the bar the range it lands in nine times out of ten.',
        actions: '<div class="qk-seg" id="st-conf" role="group" aria-label="Conference"><button type="button" aria-pressed="true" data-value="Eastern">East</button><button type="button" aria-pressed="false" data-value="Western">West</button></div>' }) +
      U.card2('Projected full-season points', d.sim && d.sim.n ? QK.fmt.num(d.sim.n) + ' simulations of the rest of the season, from today’s points' : '', U.chart('st-range', 520, 'Projected full-season points with a 90% range') +
        QK.note('<b>Why are the bars so wide?</b> Every club still has most of its games to play, and hockey games are close to coin flips. The bars narrow with every game day.')) + '</section>' +
      (lo ? '<div id="st-shape"></div>' : '') +
      QK.note('<b>Clinch marks:</b> x playoff spot, y division, z conference, p Presidents\' Trophy, e eliminated. Ties go to points %, then regulation wins, regulation and overtime wins, then wins.' + (d.updated_at ? ' Updated ' + esc(RK.fmtStamp(d.updated_at)) + '.' : ''));
    const draw = v => {
      const groups = [];
      if (v === 'wc') {
        ['Eastern', 'Western'].forEach(c => {
          const w = wc[c];
          if (!w) return;
          (st.divisions || []).filter(x => x.conference === c).forEach(dv => groups.push({ title: dv.division, sub: c + ' Conference · top three', rows: (dv.teams || []).filter(t => (w.leaders || []).indexOf(t) >= 0).map(t => by[t]).filter(Boolean) }));
          groups.push({ title: c + ' wild card', sub: 'two places; the dashed line marks the cut', rows: (w.wild_card || []).concat(w.chasers || []).map(t => by[t]).filter(Boolean), cut: (w.wild_card || []).length, label: i => (i < (w.wild_card || []).length ? 'WC' + (i + 1) : String(i + 1)) });
        });
      } else if (v === 'div') {
        (st.divisions || []).forEach(dv => groups.push({ title: dv.division, sub: dv.conference + ' Conference', rows: (dv.teams || []).map(t => by[t]).filter(Boolean), cut: 3 }));
      } else groups.push({ title: 'League', sub: 'all 32 clubs', rows: rows.slice().sort((a, b) => (a.league_rank || 99) - (b.league_rank || 99)) });
      if (!groups.length) groups.push({ title: 'League', rows: rows });
      const body = node.querySelector('#st-body');
      body.innerHTML = groups.map((g, i) => '<div class="rk-day rk-grp"' + (i ? '' : ' style="margin-top:0"') + '><b>' + esc(g.title) + '</b>' + (g.sub ? '<span>' + esc(g.sub) + '</span>' : '') + '</div><div class="qk-card rk-st" id="st-g' + i + '"></div>').join('');
      groups.forEach((g, i) => stBoard(body.querySelector('#st-g' + i), g, pc, lo));
    };
    draw('wc');
    if (lo) { QKL.race(node.querySelector('#st-race'), lo); QKL.shape(node.querySelector('#st-shape'), lo); }
    QK.seg(node.querySelector('#st-view'), draw);
    const range = c => {
      const rs = rows.filter(r => r.conference === c).map(r => Object.assign({}, r, sim[r.team] || {})).filter(r => isNum(r.pts_p05) && isNum(r.pts_p95)).sort((a, b) => (b.mean_pts || 0) - (a.mean_pts || 0));
      if (!rs.length) { node.querySelector('#st-range').innerHTML = QK.empty('No simulation yet', 'The projection appears once the season simulation has run.'); return; }
      QKC.range('#st-range', { rows: rs.map(r => ({ label: RK.teamName(r.team), lo: r.pts_p05, hi: r.pts_p95, mid: r.mean_pts, href: RK.teamHref(r.team, S), color: RK.teamColourRaw(r.team), sub: r.pts + ' points now · ' + U.pct(r.p_playoffs) + ' to make the playoffs' })),
        fmt: v => U.f(v, 0), loName: '5th', hiName: '95th percentile', midName: 'Projected full-season points', valName: 'Points at season end (full season)', labelWidth: 150 });
    };
    range('Eastern');
    QK.seg(node.querySelector('#st-conf'), range);
  });
}

/* Season forecasts: our chances for every season-long question (Cup, conference, division, Presidents' Trophy,
   playoffs). v3: ours only; the market appears only on game pages and the Model page. */
const FC = [['cup', 'Stanley Cup', 'Our chance of winning the Cup'], ['conference', 'Conference', 'Our chance of winning the conference (reaching the Final)'], ['presidents', 'Presidents’ Trophy', 'Our chance of the best regular-season record'],
  ['division', 'Division', 'Our chance of winning the division'], ['playoffs', 'Playoffs', 'Our chance of a playoff spot']];
function forecastsTab(node, S) {
  node.innerHTML = QK.skeleton('lines', 8);
  return Promise.all([RK.loadYear('markets.json', S), RK.loadYear('season.json', S)]).then(res => {
    if (!U.alive(node)) return;
    const mk = RK.ok(res[0]) ? res[0] : {}, se = RK.ok(res[1]) ? res[1] : {};
    const F = mk.futures || {}, sim = (se.sim && se.sim.teams) || {};
    const simKey = { cup: 'p_cup', conference: 'p_conf', presidents: 'p_pres', division: 'p_div', playoffs: 'p_playoffs' };
    const block = f => {
      let rows = (F[f[0]] || []).filter(x => isNum(x.model)).map(x => ({ team: x.team, p: x.model }));
      if (!rows.length) rows = Object.keys(sim).filter(t => isNum(sim[t][simKey[f[0]]])).map(t => ({ team: t, p: sim[t][simKey[f[0]]] }));
      if (!rows.length) return '';
      const full = f[0] === 'playoffs' || f[0] === 'division';
      return '<div class="qk-span-6">' + U.card2(f[1], esc(f[2]),
        QK.chances(rows.map(r => ({ label: RK.teamName(r.team), p: r.p, href: RK.teamHref(r.team, S), mark: U.team(r.team), color: RK.teamColourRaw(r.team) })), { limit: full ? 32 : 16, key: false, max: full ? 1 : undefined })) + '</div>';
    };
    const html = FC.map(block).join('');
    const cupTop = Object.keys(sim).map(t => sim[t].p_cup).filter(isNum).sort((a, b) => b - a)[0];
    node.innerHTML = html ? QK.sectionHead({ kicker: 'Season simulation', title: 'Every question about the season', html: true, sub: 'Our chances for the Cup, the conference, the division, the best record and a playoff spot, from ' + QK.fmt.num((se.sim || {}).n || 20000) + ' simulated seasons. <a class="qk-link" href="#/model?tab=calibration">How past simulations did is on the Model page.</a>' }) +
      (isNum(cupTop) ? QK.note('<b>Is ' + U.pct(cupTop) + ' a lot for the Cup?</b> For the favourite, yes. With 32 clubs and four rounds of best-of-seven series, even the best club loses somewhere along the way ' + (cupTop < 0.5 ? 'more often than not' : 'quite often') + ': ' + U.pct(cupTop) + ' still misses about ' + Math.round(10 * (1 - cupTop)) + ' times in 10.') : '') +
      '<div class="qk-grid" style="margin-top:var(--sp-5)">' + html + '</div>' : U.card2('Season forecasts', '', QK.empty('Not built yet', 'The season simulation has not run for this season.'));
  });
}

function standingsPage(el, params, state) {
  const S = params.season;
  const tab = U.tab(params, ST_TABS.map(t => t[0]), 'table');
  const base = RK.standingsHref(S);
  const tabs = ST_TABS.map((t, i) => ({ key: t[0], label: t[1], href: base + (i ? '?tab=' + t[0] : '') }));
  const nav = (S > RK.FIRST_SEASON ? '<a class="qk-btn" href="' + RK.standingsHref(S - 10001) + (tab !== 'table' ? '?tab=' + tab : '') + '">← ' + esc(RK.seasonLabel(S - 10001)) + '</a>' : '') +
    (S < RK.currentSeason() ? '<a class="qk-btn" href="' + RK.standingsHref(S + 10001) + (tab !== 'table' ? '?tab=' + tab : '') + '">' + esc(RK.seasonLabel(S + 10001)) + ' →</a>' : '');
  const body = U.section(el, { section: 'standings', title: 'Standings', sub: 'Where every club stands, and where we think it finishes: playoff and Cup chances from simulating the rest of the season, our team ratings, the bracket and the draft lottery.', tabs: tabs, active: tab, actions: nav });
  if (tab === 'table') return standingsNew(body, S);
  if (tab === 'bracket') return U.legacy('playoffs', body, params, state);
  if (tab === 'markets') return forecastsTab(body, S);
  if (tab === 'history') return U.legacy('history', body, params, state);
  body.classList.add('rk-embed-std');
  return U.legacy('standings', body, params, state, { view: tab });
}

/* ── teams ───────────────────────────────────────────────────────────────── */
/* Clubs: stat tiles, the 32 clubs on the spec's team set (heat cells = rank among the clubs, from 10 games), offence
   v defence, then the clubs by division. */
function teamsNew(node, S) {
  node.innerHTML = QK.skeleton('card', 4);
  return Promise.all([RK.loadYear('season.json', S), RK.loadYear('teams.json', S)]).then(res => {
    if (!U.alive(node)) return;
    const d = res[0];
    const rows = RK.ok(d) ? ((d.standings || {}).rows || []) : [];
    if (!rows.length) { node.innerHTML = QK.empty('Not built yet', RK.reason(d)); return; }
    const by = {}; rows.forEach(r => { by[r.team] = r; });
    const TS = U.teamSet(RK.ok(res[1]) ? res[1] : null, d);
    const R = (d.ratings || {});
    const pts = rows.map(r => { const u = (R[r.team] || {}).units || {}; return { r: r, off: u.off5, def: u.def5 }; }).filter(x => isNum(x.off) && isNum(x.def));
    const early = TS.rows.every(r => r.gp < U.TEAM_MIN_GP);
    const best = k => TS.rows.filter(r => isNum(r.v[k])).sort((a, b) => b.v[k] - a.v[k])[0];
    const tile = (k, label, sub, tip, signal) => { const r = best(k); return r ? { label: label, value: RK.teamAbbr(r.team) + ' ' + U.teamFmt(k, r.v[k]), href: RK.teamHref(r.team, S), sub: sub, tip: tip, signal: signal } : null; };
    let h = '<div class="rk-kpis">' + QK.stats([
      tile('rating', 'Top-rated club', 'goals a game better than an average club', 'Our team rating: expected goal difference a game against an average club', true),
      tile('xgf_pct5', 'Best 5v5 xG share', 'of the expected goals at 5-on-5', 'Share of 5-on-5 expected goals the team gets'),
      tile('pp', 'Most dangerous power play', 'expected goals per 60 on the power play', 'Expected goals created per 60 minutes on the power play'),
      tile('goalie', 'Best goaltending', 'goals saved above expected per 60', 'Goals the team’s goalies saved above expected per 60 minutes')
    ]) + '</div>';
    h += '<section class="qk-section" style="margin-top:0">' + QK.sectionHead({ kicker: 'How they compare', title: 'The 32 clubs, side by side', html: true,
      sub: 'Our rating first, then the process numbers that predict results (5v5 expected-goal and shot-attempt shares, offence, defence, special teams, goaltending), then the results. ' +
        (early ? 'Ranks start after ' + U.TEAM_MIN_GP + ' games: before then they are mostly noise, so the cells stay grey.' : 'Cells are coloured by rank among the 32 clubs: red best, blue worst (for defence and the penalty kill, fewer chances allowed is better).') }) +
      '<div class="qk-card" id="tm-board"></div>' +
      QK.note('<b>Rating</b> is our estimate of how many goals a game better (or worse) than an average club a team is, in all situations: +0.50 means half a goal a game. The <b>process</b> numbers (shares of chances and shot attempts) come first because they predict the next games better than the record does.') + '</section>';
    if (pts.length) h += '<section class="qk-section"><div class="qk-grid"><div class="qk-span-12">' + U.card2('Offence v defence', '5v5 expected goals for and against per 60 minutes; top right is best (the defence axis is flipped)', U.chart('tm-od', 420, 'Offence against defence')) + '</div></div></section>';
    h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'By division', title: 'Every club, division by division', sub: 'Record, our rating and our playoff chance. Open a club for its rating over time, roster, strengths and needs, schedule and outlook.' });
    (d.standings.divisions || []).forEach(dv => {
      h += '<div class="rk-day rk-grp"><b>' + esc(dv.division) + '</b><span>' + esc(dv.conference) + ' Conference</span></div><div class="rk-mini-grid">' + (dv.teams || []).map(t => {
        const r = by[t] || {};
        return '<a class="rk-teamtile" href="' + esc(RK.teamHref(t, S)) + '" style="--tc:' + esc(U.tcol(t)) + '"><div class="top">' + QK.teamMark(U.team(t)) + '<span class="nm">' + esc(RK.teamName(t)) + '</span><span class="rec">' + (isNum(r.pts) ? r.pts + ' pts' : '') + '</span></div>' +
          '<div class="row"><span>' + esc(RK.record ? RK.record(r.w, r.l, r.otl) : '') + ' · GP ' + (r.gp || 0) + '</span><span>Rating <b>' + U.signed(r.rating, 2) + '</b></span></div>' +
          (isNum(r.p_playoffs) ? '<div class="rk-bar" role="img" aria-label="Our playoff chance ' + esc(U.pct(r.p_playoffs)) + '"><span style="width:' + Math.round(r.p_playoffs * 100) + '%"></span></div>' +
          '<div class="row"><span>Our playoff chance</span><b>' + U.pct(r.p_playoffs) + '</b></div>' : '') + '</a>';
      }).join('') + '</div>';
    });
    h += '</section>';
    node.innerHTML = h;
    // the team-set leaderboard
    const cols = [{ key: 'name', label: 'Club', type: 'entity', mark: r => U.team(r.team), href: r => RK.teamHref(r.team, S) }, { key: 'gp', label: 'GP', num: true }]
      .concat(U.TEAM_SET.map(m => ({ key: m[0], label: m[0] === 'rating' ? 'Rating' : m[0] === 'xgf_pct5' ? 'xGF%' : m[0] === 'cf_pct5' ? 'CF%' : m[0] === 'off5' ? 'Off 5v5' : m[0] === 'def5' ? 'Def 5v5' : m[0] === 'pp' ? 'PP' : m[0] === 'pk' ? 'PK' : m[0] === 'goalie' ? 'Goalies' : m[0] === 'gd_g' ? 'GD/GP' : 'Pts%',
        type: 'pctl', pctl: 'p_' + m[0], fmt: v => U.teamFmt(m[0], v), tip: m[1] + ' (' + m[2] + '): ' + m[3] })));
    QK.leaderboard(node.querySelector('#tm-board'), { dense: true, rank: true, sort: { key: 'rating', dir: 'desc' }, rowHref: r => RK.teamHref(r.team, S), columns: cols,
      rows: TS.rows.map(r => { const o = { team: r.team, name: RK.teamShort(r.team), gp: r.gp }; U.TEAM_SET.forEach(m => { o[m[0]] = r.v[m[0]]; o['p_' + m[0]] = r.p[m[0]]; }); return o; }) });
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
  const body = U.section(el, { section: 'teams', title: 'Teams', sub: 'Every club on the numbers that predict results: our rating, the share of the chances, special teams and goaltending. Open a club for the short version, its form and its roster.',
    tabs: U.tabs('#/teams', [['clubs', 'Clubs'], ['stats', 'Team stats']], S), active: tab });
  if (tab === 'stats') return U.legacy('teams', body, params, state);
  return teamsNew(body, S);
}


/* ── players: leaders with sample floors, awards ────────────────────────── */
/* Leaders: totals where totals mean something (everyone ranks), then the spec's headline rates by peer group, each
   limited to players at the spec's minimum (the payload's "qualified": 250 5v5 minutes a full season for skaters, a
   quarter of the team's minutes for goalies, prorated by games played; goalies also need 100 unblocked shots). A
   board nobody has reached yet says so, with the floor and who is closest, instead of an empty card. */
function leadersPage(node, S) {
  node.innerHTML = QK.skeleton('lines', 8);
  return Promise.all([RK.loadYear('skaters.json', S), RK.loadYear('goalies.json', S)]).then(res => {
    if (!U.alive(node)) return;
    const sk = RK.ok(res[0]) ? res[0] : null, gk = RK.ok(res[1]) ? res[1] : null;
    if (!sk) { node.innerHTML = QK.empty('Not built yet', RK.reason(res[0])); return; }
    const tg = Math.max(Number(sk.team_games) || 0, Number((gk || {}).team_games) || 0);
    const P = Object.keys(sk.players || {}).map(id => Object.assign({ id: id }, sk.players[id]));
    const G = gk ? Object.keys(gk.players || {}).map(id => Object.assign({ id: id }, gk.players[id])) : [];
    const v = (p, k) => (p.values || {})[k];
    const ref = sk.reference || {}, gref = (gk || {}).reference || {};
    const skFloor = isNum(ref.min_toi5) ? Math.round(ref.min_toi5) : null, gFloor = isNum(gref.min_toi) ? Math.round(gref.min_toi) : null;
    const gFa = ((gref.floors || {}).fa) || 100;
    const skQ = p => !!p.qualified, gQ = p => !!p.qualified && (U.faOf(p) || 0) >= gFa;
    const F = P.filter(p => p.group === 'F'), D = P.filter(p => p.group === 'D');
    const fmt = k => (x => U.fmtBy((U.metaMap(sk)[k] || U.metaMap(gk || {})[k] || {}), x));
    /* [title, pool, key, qualifier, formatter, peer line, closest(p) -> progress text] */
    const skClose = p => U.f(v(p, 'toi5'), 0) + ' 5v5 min', gClose = p => U.f(p.toi, 0) + ' min, about ' + (U.faOf(p) || 0) + ' unblocked shots';
    const skNeed = skFloor !== null ? skFloor + ' 5v5 minutes' : 'the 5v5 minutes floor';
    const gNeed = (gFloor !== null ? gFloor + ' minutes in net' : 'a quarter of the team’s minutes') + ' and ' + gFa + ' unblocked shots';
    const TOT = [['Points', P, 'p', null, x => String(x), 'all skaters'], ['Goals', P, 'g', null, x => String(x), 'all skaters'],
      ['Rink value (GAR)', P, 'gar', null, x => U.f(x, 2), 'all skaters · goals above replacement'], ['Goals saved above expected', G, 'gsax', null, x => U.signed(x, 1), 'all goalies']];
    const RATE = [['Rink value per 60', F, 'gar_60', skQ, fmt('gar_60'), 'forwards', skNeed, skClose], ['Rink value per 60', D, 'gar_60', skQ, fmt('gar_60'), 'defencemen', skNeed, skClose],
      ['Points per 60', F, 'p60', skQ, x => U.f(x, 2), 'forwards', skNeed, skClose], ['Shot attempts per 60 (5v5)', F, 'icf60', skQ, x => U.f(x, 1), 'forwards', skNeed, skClose],
      ['On-ice xG share (5v5)', F, 'adj_xgf_pct', skQ, x => U.pct(x, 1), 'forwards', skNeed, skClose], ['Isolated defence (RAPM)', D, 'rapm_def', skQ, x => U.signed(x, 2), 'defencemen', skNeed, skClose],
      ['GSAx per 100 shots', G, 'gsax100', gQ, x => U.signed(x, 2), 'goalies', gNeed, gClose], ['Save percentage', G, 'sv_pct', gQ, x => RK.fmtVal(x, '3'), 'goalies', gNeed, gClose]];
    const board = (b, rate) => {
      const list = b[1].filter(p => isNum(v(p, b[2])) && (!b[3] || b[3](p))).sort((x, y) => ((U.SPEC[b[2]] || {}).lower ? v(x, b[2]) - v(y, b[2]) : v(y, b[2]) - v(x, b[2]))).slice(0, 8);
      let inner;
      if (list.length) inner = '<ul class="rk-list rk-lead">' + list.map((p, j) => '<li><span class="n">' + (j + 1) + '</span>' + U.playerEnt(p.id, p.name, p.team) + '<span class="v">' + esc(b[4](v(p, b[2]))) + '</span></li>').join('') + '</ul>';
      else {
        const pool = b[1].filter(p => isNum(v(p, b[2])));
        const close = rate ? pool.slice().sort((x, y) => (rate === 'g' ? (y.toi || 0) - (x.toi || 0) : (v(y, 'toi5') || 0) - (v(x, 'toi5') || 0)))[0] : null;
        inner = '<div class="rk-board-empty"><b>Fills in when the first ' + esc(b[5]) + ' reach the floor</b><span>The floor is ' + esc(b[6]) + ' at this point of the season (it grows with games played).' +
          (close ? ' Closest: ' + esc(close.name) + ', ' + esc(b[7](close)) + '.' : '') + '</span></div>';
      }
      const sp = U.SPEC[b[2]] || {};
      return '<div class="qk-span-3">' + U.card2(b[0], esc(b[5]) + (rate ? ' · qualified' : ''), inner, { flush: true, cls: 'rk-board', right: sp.tip ? '<span class="rk-info" tabindex="0" data-tip="' + esc(sp.tip) + '">ⓘ</span>' : '' }) + '</div>';
    };
    const fin = P.filter(p => (v(p, 'sog') || 0) >= 20 && isNum(v(p, 'ixg')) && isNum(v(p, 'g')));
    /* Who's hot: the leader of each headline total (and the qualified leader per 60), with the next best */
    const lead2 = (pool, k, q, lower) => pool.filter(p => isNum(v(p, k)) && (!q || q(p))).sort((x, y) => (lower ? v(x, k) - v(y, k) : v(y, k) - v(x, k))).slice(0, 2);
    /* a leader tied with the next best (as shown) is no leader: that card is left out */
    const hot = (title, pool, k, f, unit, expl, q) => { const t = lead2(pool, k, q); return t.length && !(t[1] && f(v(t[0], k)) === f(v(t[1], k))) ? { sport: 'hockey', title: title, name: t[0].name, value: f(v(t[0], k)), unit: unit + ' · ' + RK.teamAbbr(t[0].team), next: t[1] ? { name: t[1].name, value: f(v(t[1], k)) } : null, expl: expl, href: RK.playerHref(t[0].id) } : null; };
    const hotItems = [hot('Most points', P, 'p', x => String(x), 'points', 'Goals plus assists, all situations.'),
      hot('Most goals', P, 'g', x => String(x), 'goals', 'Finishing swings a lot over a few weeks; the chances behind it swing less.'),
      hot('Most value', P, 'gar', x => U.f(x, 1), 'goals above replacement', 'Goals added over a replacement-level player, all parts of the game.'),
      hot('Best in net', G, 'gsax', x => U.signed(x, 1), 'goals saved above expected', 'Goals stopped beyond what an average goalie would on the same shots.'),
      hot('Best per hour', F, 'gar_60', x => U.f(x, 2), 'value per 60, forwards', 'Value per 60 minutes among qualified forwards: fair across ice time.', skQ),
      hot('Most assists', P, 'a', x => String(x), 'assists', 'Primary and secondary assists, all situations.')].filter(Boolean).slice(0, 5);
    node.innerHTML = '<div class="rk-flex" style="margin-bottom:var(--sp-4)"><input class="qk-input rk-search" id="pl-q" type="search" placeholder="Find a player…" aria-label="Find a player" autocomplete="off"></div><div id="pl-hits"></div>' +
      (hotItems.length >= 3 ? QK.band(QK.sectionHead({ kicker: 'Who’s hot', title: 'Leading the way in ' + RK.seasonLabel(S), sub: 'The leader of each headline number, with the next best. Tap a card for the player.' }) + QK.hotRow(hotItems), { cls: 'rk-hot' }) : '') +
      QK.sectionHead({ kicker: 'Season leaders', title: 'Who has the most', sub: 'Counting stats, so everyone ranks.' }) + '<div class="qk-grid">' + TOT.map(b => board(b, null)).join('') + '</div>' +
      '<section class="qk-section">' + QK.sectionHead({ kicker: 'Rates by position', title: 'Who is best per minute', html: true,
        sub: 'The stable, predictive rates from our metric spec, ranked within each position group. Only qualified players rank: skaters need 250 5v5 minutes over a full season (' + (skFloor !== null ? skFloor + ' now' : 'prorated') + '), goalies a quarter of the team’s minutes and ' + gFa + ' unblocked shots. ' + tg + ' team games played.' }) +
      '<div class="qk-grid">' + RATE.map(b => board(b, b[1] === G ? 'g' : 's')).join('') + '</div>' +
      QK.note('<b>Why per 60 minutes?</b> A rate compares a fourth-liner and a top-line star on the same footing. The floor keeps one hot week from topping a board: below it, a rate is mostly noise.') + '</section>' +
      (fin.length ? '<section class="qk-section">' + U.card2('Finishing: goals against expected goals', 'Skaters with 20+ shots; above the dashed line scores more than the chances suggest', U.chart('pl-fin', 400, 'Goals against expected goals') +
        QK.note('<b>Hot hands cool off.</b> Over one season, scoring above or below the chances is mostly luck: the players far above the line usually drift back towards it.')) + '</section>' : '');
    if (fin.length) {
      const top = fin.slice().sort((a, b) => v(b, 'g') - v(a, 'g')).slice(0, 160);
      const m = Math.max.apply(null, top.map(p => Math.max(v(p, 'g'), v(p, 'ixg'))));
      QKC.scatter('#pl-fin', { points: top.map(p => ({ x: v(p, 'ixg'), y: v(p, 'g'), name: p.name + ' · ' + RK.teamAbbr(p.team), label: QK.surname(p.name || ''), color: RK.teamColourRaw(p.team), href: RK.playerHref(p.id), size: 9 })),
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

/* Awards: our chance where the award model has a race; where it has none (no fit yet, or a fit that came out flat),
   the reason in words and the players leading the usual criteria. Market numbers stay off this page. */
function awardsPage(node, S) {
  node.innerHTML = QK.skeleton('lines', 6);
  return RK.loadYear('awards.json', S).then(a => {
    if (!U.alive(node)) return;
    if (!RK.ok(a)) { node.innerHTML = U.card2('Awards', '', QK.empty('Not built yet', RK.reason(a))); return; }
    const list = a.awards || [];
    const races = a.races || {}, boards = a.boards || {}, reasons = a.reasons || {}, winners = a.winners || {};
    const bc = a.board_cols || ['id', 'name', 'team', 'value'];
    /* a race whose chances are all the same carries no information (a degenerate fit): treat it as no race */
    const live = k => { const r = races[k] || []; if (!r.length) return false; const p0 = r[0].p; return !r.every(x => Math.abs((x.p || 0) - (p0 || 0)) < 1e-6); };
    const withRace = list.filter(w => live(w.key));
    node.innerHTML = QK.sectionHead({ kicker: 'Award races', title: 'Who wins the awards', sub: 'Our chances where the award model has a race, and the players leading the usual criteria.' }) +
      (withRace.length ? '' : QK.note('None of the award models has a race yet this season. Each card says why and lists the players leading the usual criteria.', { cls: 'rk-note-top' })) + '<div class="qk-grid">' + list.map(w => {
      const r = live(w.key) ? (races[w.key] || []).slice(0, 8) : [];
      const b = (boards[w.key] || []).slice(0, 5);
      const win = winners[w.key];
      let body = '';
      if (win && win.length) body += '<div class="rk-note" style="margin:0 0 8px"><b>Winner:</b> ' + win.map(x => esc(x.name) + (x.team ? ' (' + esc(x.team) + ')' : '')).join(', ') + '</div>';
      if (r.length) body += U.chart('aw-' + w.key, Math.max(160, r.length * 26 + 20), w.name + ': our chances');
      else if (!(win && win.length)) body += '<div class="rk-board-empty" style="padding:0 0 8px"><b>No race from our model yet</b><span>' + esc(reasons[w.key] ? 'Why: ' + reasons[w.key] + '.' : (races[w.key] || []).length ? 'Its fit came out flat (every player the same chance), so it is being refitted.' : 'The model has not run for this award this season.') + '</span></div>';
      if (b.length) body += '<div class="qk-kicker" style="margin:10px 0 4px">Leading the usual criteria</div><ul class="rk-list" style="margin:0 -16px">' + b.map((x, i) => { const o = {}; bc.forEach((k, j) => { o[k] = x[j]; }); return '<li><span class="n">' + (i + 1) + '</span>' + U.playerEnt(o.id, o.name, o.team) + '<span class="v">' + esc(isNum(o.value) ? (Number.isInteger(o.value) ? o.value : U.f(o.value, 2)) : '') + '</span></li>'; }).join('') + '</ul>';
      return '<div class="qk-span-6">' + U.card2(w.name, esc(w.desc || '') + (r.length && a.basis && a.basis[w.key] ? ' · ' + esc(a.basis[w.key] === 'clogit' ? 'our model of past voting' : a.basis[w.key]) : ''), body) + '</div>';
    }).join('') + '</div>' + (a.model_note ? '<p class="rk-note">' + esc(a.model_note) + '</p>' : '');
    withRace.forEach(w => {
      const r = (races[w.key] || []).slice(0, 8);
      QKC.bar('#aw-' + w.key, { cats: r.map(x => x.name), series: [{ name: 'Our chance', data: r.map(x => x.p) }], horizontal: true, labels: true, fmt: v => U.pct(v, 1), valName: 'Our chance of winning',
        colors: r.map(x => RK.teamColourRaw(RK.player(x.id).team)), hrefs: r.map(x => RK.playerHref(x.id)), labelWidth: 130 });
    });
  });
}


const PL_TABS = [['leaders', 'Leaders'], ['skaters', 'Skaters'], ['goalies', 'Goalies'], ['lines', 'Lines'], ['awards', 'Awards'], ['boards', 'All leaderboards']];
function playersPage(el, params, state) {
  const S = params.season;
  const tab = U.tab(params, PL_TABS.map(t => t[0]), 'leaders');
  const body = U.section(el, { section: 'players', title: 'Players', sub: 'Who leads, who is best per minute at each position, every skater and goalie against their peers, the line combinations and the award races. Open a player for the short version.',
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
  const body = U.section(el, { section: 'lab', title: 'Lab', sub: 'Your turn: pick any two numbers and see who stands out, or put skaters, goalies or clubs side by side.',
    tabs: [{ key: 'lab', label: 'Chart builder', href: '#/lab' + (U.sq(S) ? '?' + U.sq(S) : '') }, { key: 'compare', label: 'Compare', href: '#/compare' + (U.sq(S) ? '?' + U.sq(S) : '') }], active: tab });
  return U.legacy(tab, body, params, state);
}
const MD_TABS = [['methodology', 'Methodology'], ['calibration', 'Calibration'], ['moves', 'Who moves next'], ['glossary', 'Glossary'], ['terms', 'Terms']];
/* Model › Who moves next (MOVES_VIEWS.md "Model page text"): the notes verbatim, the validation of each block on the
   sealed seasons (published or not, with the reason), and the calibration deciles of the published model. */
const MV_BLOCKS = [['next', 'Not in the lineup next season'], ['deadline', 'Traded or claimed before the deadline'], ['type', 'Kind of departure'], ['arrivals', 'Arrivals by position'], ['targets', 'Targets']];
function movesModel(node, S) {
  node.innerHTML = QK.skeleton('lines', 6);
  return U.moves(S || RK.currentSeason()).then(M => {
    if (!U.alive(node)) return;
    if (!M) { node.innerHTML = U.card2('Who moves next', '', QK.empty('Not built yet', 'The movement model has not been published for this season.')); return; }
    const d = M.d, V = d.validation || {}, pub = M.pub, R = d.reasons || {}, split = (d.split || {}).test || [];
    const sea = split.length ? RK.seasonLabel(split[0]) + ' to ' + RK.seasonLabel(split[split.length - 1]) : 'the sealed seasons';
    const ci = x => (Array.isArray(x) && x.length >= 3 ? U.f(x[0], 4) + ' (' + U.f(x[1], 4) + ' to ' + U.f(x[2], 4) + ')' : '—');
    const rows = MV_BLOCKS.map(b => {
      const t = (V[b[0]] || {}).test || {};
      const p = b[0] === 'arrivals' ? pub.arrivals : b[0] === 'targets' ? pub.targets : pub[b[0]];
      if (b[0] === 'targets') return '<tr><td>' + esc(b[1]) + '</td><td class="num">' + (isNum(t.team_seasons) ? QK.fmt.num(t.team_seasons) + ' club-seasons' : '—') + '</td><td class="num" colspan="4">' + (isNum(t.model) ? 'top ' + (t.k || 10) + ' joined: ' + U.pct(t.model, 1) + (isNum(t.need_value) ? ' · need x value ' + U.pct(t.need_value, 1) : '') + (isNum(t.chance_precision) ? ' · chance ' + U.pct(t.chance_precision, 1) : '') : '—') + '</td><td>' + (p ? QK.tag('published', 'signal') : QK.tag('not published')) + (R[b[0]] ? '<span class="rk-why">' + esc(R[b[0]]) + '</span>' : '') + '</td></tr>';
      return '<tr><td>' + esc(b[1]) + '</td><td class="num">' + (isNum(t.n) ? QK.fmt.num(t.n) : '—') + '</td><td class="num">' + (isNum(t.rate) ? U.pct(t.rate, 1) : '—') + '</td><td class="num">' + (isNum(t.logloss) ? U.f(t.logloss, 4) + ' v ' + U.f(t.logloss_base, 4) : '—') + '</td><td class="num">' + ci(t.ll_gain) + '</td><td class="num">' + (isNum(t.cal_slope) ? U.f(t.cal_slope, 2) : '—') + '</td><td>' +
        (p ? QK.tag('published', 'signal') : QK.tag(b[0] === 'type' || b[0] === 'deadline' || b[0] === 'arrivals' ? 'base rate shown' : 'not published')) + (R[b[0]] ? '<span class="rk-why">' + esc(R[b[0]]) + '</span>' : '') + '</td></tr>';
    }).join('');
    const nx = (V.next || {}).test || {};
    node.innerHTML = QK.sectionHead({ kicker: 'Movement model · ' + RK.seasonLabel(d.season || S), title: 'Who moves next', sub: 'How we estimate each player’s chance of not being in the club’s lineup next season, and how it did on seasons it never saw (' + sea + ').' }) +
      '<div class="qk-grid"><div class="qk-span-7">' + U.card2('How it works', 'In our own words, as the payload states it', '<ul class="rk-list">' + (d.notes || []).map(n => '<li style="align-items:flex-start"><span>' + esc(n) + '</span></li>').join('') + '</ul>', { flush: true }) + '</div>' +
      '<div class="qk-span-5">' + U.card2('Calibration: not in the lineup next season', 'Each dot is a tenth of the sealed-season players by our chance; on the diagonal, the chance came true as often as it said', U.chart('mv-dec', 300, 'Predicted chance against observed share')) + '</div></div>' +
      '<section class="qk-section">' + U.card2('Validation on the sealed seasons', 'Log-loss: ours v the league base rate (lower is better); the gain is base minus ours with its 95% interval. A block is published only when the gain’s interval excludes zero and it stays calibrated.',
        '<div class="qk-table-wrap"><table class="rk-ol"><thead><tr><th>Block</th><th class="num">Players</th><th class="num">Happened</th><th class="num">Log-loss</th><th class="num">Gain (95% CI)</th><th class="num">Calibration slope</th><th>Status</th></tr></thead><tbody>' + rows + '</tbody></table></div>', { flush: true }) + '</section>';
    const dec = (nx.deciles || []).filter(x => Array.isArray(x) && isNum(x[0]) && isNum(x[1]));
    if (dec.length) {
      QKC.scatter('#mv-dec', { points: dec.map(x => ({ x: x[0], y: x[1], name: 'Predicted ' + U.pct(x[0]) + ' · happened ' + U.pct(x[1]) + ' · ' + x[2] + ' players', size: 11 })), xName: 'Predicted chance', yName: 'Observed share', xFmt: v => Math.round(v * 100) + '%', yFmt: v => Math.round(v * 100) + '%', xMin: 0, yMin: 0, xMax: 0.8, yMax: 0.8 });
      const c = node.querySelector('#mv-dec');
      if (c && c.__qkc) { const e = c.__qkc, b0 = e.build; e.build = (T, x) => { const o = b0(T, x); o.series[0].markLine = { silent: true, symbol: 'none', lineStyle: { color: T.axis, type: [4, 4] }, label: { show: false }, data: [[{ coord: [0, 0] }, { coord: [0.8, 0.8] }]] }; return o; }; e.paint(); }
    } else node.querySelector('#mv-dec').innerHTML = QK.empty('No deciles published');
  });
}
/* v3: "How sure are we?" at the top of the Model page (methodology and calibration): the game model's record from
   data/calibration.json (QK.howSure), our chance for the home team against how often it won. Nothing when absent. */
function howSure(node) {
  return RK.load('calibration.json').then(cj => {
    if (!U.alive(node)) return;
    const cb = QK.calib.find(RK.ok(cj) ? cj : null);
    if (!cb) { node.innerHTML = ''; return; }
    const ss = (((cj || {}).game_model || {}).seasons || []).slice().sort();
    const span = ss.length ? RK.seasonLabel(ss[0]) + ' to ' + RK.seasonLabel(ss[ss.length - 1]) : '';
    node.innerHTML = QK.sectionHead({ kicker: 'How sure are we?', title: 'We say it. Then we check it.', sub: 'Every game forecast we would have made before puck drop' + (span ? ', ' + esc(span) : '') + ', grouped by the chance we gave the home team, against how often it won. When the two bars match, our numbers mean what they say.' }) + '<div id="md-sure-mod"></div>';
    QK.howSure(node.querySelector('#md-sure-mod'), { calibration: cj, league: 'NHL', span: span, subject: 'the home team' });
  });
}
function modelPage(el, params, state) {
  let tab = state.route === 'glossary' ? 'glossary' : state.route === 'methodology' ? 'methodology' : U.tab(params, MD_TABS.map(t => t[0]), 'methodology');
  if (tab === 'terms') { location.replace('#/disclaimer'); return; }
  const tabs = MD_TABS.map((t, i) => ({ key: t[0], label: t[1], href: t[0] === 'terms' ? '#/disclaimer' : '#/model' + (i ? '?tab=' + t[0] : '') }));
  const sub = tab === 'glossary' ? 'Every number on the site in plain English: what it measures, and how many games it takes to mean something.' : 'How the models work, how well they have done on seasons they never saw, and what every number means.';
  const body = U.section(el, { section: 'model', title: tab === 'glossary' ? 'Glossary' : 'Model', sub: sub, tabs: tabs, active: tab });
  if (tab === 'moves') return movesModel(body, params.season);
  if (tab === 'methodology' || tab === 'calibration') {
    body.innerHTML = '<div class="rk-howsure" id="md-sure"></div><div id="md-tab"></div>';
    howSure(body.querySelector('#md-sure'));
    return U.legacy(tab, body.querySelector('#md-tab'), params, state);
  }
  if (tab === 'glossary') {
    body.innerHTML = QK.note('<b>New here?</b> A <b>percentile</b> ranks a player against others in the same role: 90th means better than 90 in 100. <b>Stabilises at</b> is the sample after which a number is more signal than noise; before it, read it lightly.', { cls: 'rk-note-top' }) + '<div id="md-tab"></div>';
    return U.legacy(tab, body.querySelector('#md-tab'), params, state);
  }
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
