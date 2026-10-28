/* The Quant Rink — the section pages of the redesigned IA (October 2026).
 *
 *   #/standings[/<S>]?tab=  table (wild card / divisions / league) · chances (rk-chances.js: the season simulation's boards,
 *                           where they finish, one club's final points; view=lottery the draft lottery) · bracket · history ·
 *                           races (the award races). Round 9 (28 Oct 2026): the old odds, markets and lottery tabs land on
 *                           Chances, ratings on the Teams page's profile; the player leader boards moved to the Scouting
 *                           Room's Leaders (a link stays).
 *   #/teams                 rk-teams.js (round 9: power board, team profile, style map, strengths, head to head, form, lines)
 *   #/scout                 rk-scout.js (round 9: the Scouting Room; #/players and #/lab redirect there, core.js)
 *   #/compare[/<a>/<b>]     Compare, under the Scouting Room section
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
const ST_TABS = [['table', 'Table'], ['chances', 'Chances'], ['bracket', 'Bracket'], ['history', 'History'], ['races', 'Races']];
const ST_OLD = { odds: ['chances', ''], markets: ['chances', ''], lottery: ['chances', 'lottery'], standings: ['table', ''] };

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
      (lo ? '<div id="st-shape"></div>' : '') +
      '<p class="qk-sub rk-st-more">' + (Object.keys(sim).length ? '<a class="qk-link" href="' + esc(RK.standingsHref(S)) + '?tab=chances">Where they finish, and every season chance →</a> · <a class="qk-link" href="' + esc(RK.standingsHref(S)) + '?tab=chances&view=lottery">The draft lottery →</a> · ' : '') +
        '<a class="qk-link" href="#/scout?view=leaders' + (Number(S) !== Number(RK.currentSeason()) ? '&s=' + S : '') + '">Player leaders are in the Scouting Room →</a></p>' +
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
  });
}

function standingsPage(el, params, state) {
  const S = params.season;
  const q0 = (params.query || {}).tab;
  if (q0 === 'ratings') { location.replace('#/teams?go=grid' + (Number(S) !== Number(RK.currentSeason()) ? '&s=' + S : '')); return; }
  const old = ST_OLD[q0];
  const tab = old ? old[0] : U.tab(params, ST_TABS.map(t => t[0]), 'table');
  const view = old ? old[1] : ((params.query || {}).view || '');
  const base = RK.standingsHref(S);
  const tabs = ST_TABS.map((t, i) => ({ key: t[0], label: t[1], href: base + (i ? '?tab=' + t[0] : '') }));
  const nav = (S > RK.FIRST_SEASON ? '<a class="qk-btn" href="' + RK.standingsHref(S - 10001) + (tab !== 'table' ? '?tab=' + tab : '') + '">← ' + esc(RK.seasonLabel(S - 10001)) + '</a>' : '') +
    (S < RK.currentSeason() ? '<a class="qk-btn" href="' + RK.standingsHref(S + 10001) + (tab !== 'table' ? '?tab=' + tab : '') + '">' + esc(RK.seasonLabel(S + 10001)) + ' →</a>' : '');
  const body = U.section(el, { section: 'standings', title: 'Standings', sub: 'Where every club stands, and where we think it finishes: playoff and Cup chances from simulating the rest of the season, the bracket, the draft lottery, the history and the award races.', tabs: tabs, active: tab, actions: nav });
  if (tab === 'bracket') return U.legacy('playoffs', body, params, state);
  if (tab === 'chances') return RK.chancesTab(body, S, view);
  if (tab === 'history') return RK.historyTab(body);
  if (tab === 'races') { const r = awardsPage(body, S); if (r && r.then) r.then(() => { if (RK.recordsInReach && U.alive(body)) { body.insertAdjacentHTML('afterbegin', '<div id="st-rec"></div>'); RK.recordsInReach(body.querySelector('#st-rec'), S); } }); return r; }
  return standingsNew(body, S);
}

/* ── players: leaders with sample floors, awards ────────────────────────── */
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


/* ── lab and model ───────────────────────────────────────────────────────── */
function labPage(el, params, state) {
  const S = params.season;
  const body = U.section(el, { section: 'scout', title: 'Compare', sub: 'Put skaters, goalies or clubs side by side on the numbers that matter for their position.',
    tabs: [{ key: 'scout', label: 'Scouting Room', href: '#/scout' + (U.sq(S) ? '?' + U.sq(S) : '') }, { key: 'compare', label: 'Compare', href: '#/compare' + (U.sq(S) ? '?' + U.sq(S) : '') }], active: 'compare' });
  return U.legacy('compare', body, params, state);
}
const MD_TABS = [['methodology', 'How it works'], ['calibration', 'How we’re doing'], ['market', 'Our forecasts v the market'], ['moves', 'Who moves next'], ['glossary', 'Glossary'], ['terms', 'Terms']];
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
/* Round 6: "How we're doing" (the Model page's calibration tab, id kept so ?tab=calibration and #/calibration still
   work): our favourites' record over the last week (index.json digest.record) as tiles, then the game model's record
   from data/calibration.json (QK.doing -> QK.howSure). The overview no longer carries either. */
function howSure(node) {
  return RK.load('calibration.json').then(cj => {
    if (!U.alive(node)) return;
    const cb = QK.calib.find(RK.ok(cj) ? cj : null);
    const rec = ((RK.index() || {}).digest || {}).record || null;
    if (!cb && !rec) { node.innerHTML = ''; return; }
    const ss = (((cj || {}).game_model || {}).seasons || []).slice().sort();
    const span = ss.length ? RK.seasonLabel(ss[0]) + ' to ' + RK.seasonLabel(ss[ss.length - 1]) : '';
    QK.doing(node, { record: rec, calibration: cb ? cj : null, league: 'NHL', span: span, subject: 'the home team',
      sub: 'Our favourites over the last week, then every game forecast we would have made before puck drop' + (span ? ', ' + span : '') + ', grouped by the chance we gave the home team, against how often it won. When the two match, our numbers mean what they say.' });
  });
}
function modelPage(el, params, state) {
  let tab = state.route === 'glossary' ? 'glossary' : state.route === 'methodology' ? 'methodology' : U.tab(params, MD_TABS.map(t => t[0]), 'methodology');
  if (tab === 'terms') { location.replace('#/disclaimer'); return; }
  const tabs = MD_TABS.map((t, i) => ({ key: t[0], label: t[1], href: t[0] === 'terms' ? '#/disclaimer' : '#/model' + (i ? '?tab=' + t[0] : '') }));
  const sub = tab === 'glossary' ? 'Every number on the site in plain English: what it measures, and how many games it takes to mean something.' : 'How the models work, how well they have done on seasons they never saw, and what every number means.';
  const body = U.section(el, { section: 'model', title: tab === 'glossary' ? 'Glossary' : 'Model', sub: sub, tabs: tabs, active: tab });
  if (tab === 'moves') return movesModel(body, params.season);
  if (tab === 'market') return RK.marketTab(body, RK.currentSeason());
  if (tab === 'calibration') {
    body.innerHTML = '<div class="rk-howsure" id="md-sure"></div><div id="md-tab"></div>';
    howSure(body.querySelector('#md-sure'));
    return U.legacy(tab, body.querySelector('#md-tab'), params, state);
  }
  if (tab === 'methodology') return RK.howItWorks(body, params, state);
  if (tab === 'glossary') {
    body.innerHTML = '<div id="md-tab"></div>' + QK.explain('<b>New here?</b> A <b>percentile</b> ranks a player against others in the same role: 90th means better than 90 in 100. Before a number has its sample (How it works lists them), read it lightly.', { html: true });
    return U.legacy(tab, body.querySelector('#md-tab'), params, state);
  }
  return U.legacy(tab, body, params, state);
}

RK.ui.modelTabs = active => U.tabsHTML(MD_TABS.map((t, i) => ({ key: t[0], label: t[1], href: t[0] === 'terms' ? '#/disclaimer' : '#/model' + (i ? '?tab=' + t[0] : '') })), active);

RK.page('standings', standingsPage);
RK.page('compare', labPage);
RK.page('model', modelPage);
RK.page('glossary', modelPage);
RK.page('methodology', modelPage);
})(window.RK);
