/* The Quant Rink — the game centre (#/game/<game_id>).
 *
 * Header: teams, score, period and clock, live win probability and expected goals, the linescore by
 * period with shots on goal, venue, the game type (playoff round and game number). Tabs:
 *   Preview     model v market v line for the win (overtime included), regulation (three-way), overtime,
 *               puck line and total; the projected score, the exact-score grid and the total-goals
 *               distribution; the starting goalies;
 *   Game flow   the expected-goals race, our win probability with goals marked, the shot maps (half rink,
 *               each team attacking right, xG-sized dots, goals filled; strength and period filters),
 *               the goals and the game's awards;
 *   Lines & TOI forward lines and defence pairs from the shift charts (TOI by strength, on-ice xG and
 *               goals), and every skater's time on ice by strength;
 *   Box score   skaters (goals, assists, shots, individual xG, hits, blocks, giveaways, takeaways,
 *               face-offs, TOI by strength, on-ice xGF%) and goalies (saves, xGA, GSAx), team stats.
 *
 * Reads data/<S>/games/<game_id>.json (PAYLOADS.md "games/<game_id>.json"). Assumed shape (every block
 * optional; see the builder report): the GAME_CARD fields at the top level or under "card"; pregame
 * {model {p_home, p_reg_home, p_reg_away, p_ot, p_so, total, puck_line_home (P home covers its puck line),
 * home_goals, away_goals, score_dist ({rows, cols, p: 7x7 final scores} | [[p(h=i,a=j)]] | {"h-a": p}), total_dist [p(0..15)], p_over}, market
 * {p_home, p_ot, total, p_over, sources}, line {ml_home, ml_away, puck_line, total, open, close}, priced_at};
 * goalies {home, away: {pid, name, status, gsax, sv_pct, gp}}; linescore [{period, home, away, sog_home,
 * sog_away}]; sog {home, away}; shots {cols: [period, sec, team, player, x, y, type, shot_type, xg, goal,
 * strength], rows}; xg_race {home: [[sec, cum]], away, goals} (else built from shots); wp [[sec, p_home]] |
 * {cols, rows}; goals [{sec, period, team, player, assists: [pid], strength, xg}] (else from shots);
 * lines {home, away: {forwards|defence|pp|pk: [{players: [pid], toi, toi_by {5v5, PP, PK}, xgf, xga, gf,
 * ga, cf, ca}]}}; box {skaters|goalies: {cols, rows}, team: [{stat, home, away}]} (or box {home, away:
 * {skaters, goalies}}); awards [{title, pid, team, value, why}] | {key: {...}}. */
(function (RK) {
'use strict';

const esc = RK.esc;
const isNum = RK.isNum;
const R = x => RK.charts.rows(x);
const TAB = {};       // game_id -> tab shown (kept across live refreshes)

// ── normalise ──────────────────────────────────────────────────────────────

/* The two teams' colours for this game, told apart when the clubs share one (CAR and FLA are both red): the home
 * team keeps its colour, the away team falls back to its alternate or to white (RK.pairColours, as the xG race and
 * the WP chart use). {home, away, of(team)}. */
function gameColours(g) {
  const pc = RK.pairColours(g.home, g.away);
  return { home: pc[0], away: pc[1], of: t => (String(t) === String(g.home) ? pc[0] : String(t) === String(g.away) ? pc[1] : RK.teamColour(t)) };
}
function sideOf(g, t) { return String(t) === String(g.home) ? 'home' : (String(t) === String(g.away) ? 'away' : null); }
function goalsOf(g, shots) {
  const gl = R(g.goals || g.scoring);
  if (gl.length) return gl.map(x => Object.assign({}, x, { sec: isNum(x.sec) ? Number(x.sec) : null, assists: x.assists || [x.assist1, x.assist2].filter(Boolean) }));
  return shots.filter(s => s.goal).map(s => ({ sec: s.sec, period: s.period, team: s.team, player: s.player, name: s.name, assists: [], strength: s.strength, xg: s.xg, shot_type: s.shot_type }));
}
const BOX_ALIAS = { id: 'pid', player: 'pid', p: 'pts', blocks: 'blk', give: 'gv', take: 'tk', toi_5v5: 'toi_ev', toi_sh: 'toi_pk', toi_es: 'toi_ev' };
function aliasRow(r) {
  const o = Object.assign({}, r);
  Object.keys(BOX_ALIAS).forEach(k => { if (r[k] !== undefined && o[BOX_ALIAS[k]] === undefined) o[BOX_ALIAS[k]] = r[k]; });
  if (!isNum(o.sv) && isNum(o.sa) && isNum(o.ga)) o.sv = o.sa - o.ga;
  return o;
}
function boxRows(g, key) {
  return boxRows0(g, key).map(aliasRow);
}
function boxRows0(g, key) {
  const b = g.box || {};
  const sec = b[key];
  const cols = b[key.replace(/s$/, '') + '_cols'] || b[key + '_cols'];
  if (sec && !Array.isArray(sec) && typeof sec === 'object' && !sec.cols && !sec.rows && !(sec.home && sec.away && !Array.isArray(sec.home))) {
    // {TEAM: [[...], ...]} with box.<kind>_cols, or {TEAM: [{...}]}
    return Object.keys(sec).reduce((acc, t) => acc.concat((sec[t] || []).map(r => {
      const o = Array.isArray(r) && cols ? cols.reduce((x, c, i) => { x[c] = r[i]; return x; }, {}) : Object.assign({}, r);
      if (!o.team) o.team = t === 'home' || t === 'away' ? g[t] : t;
      return o;
    })), []);
  }
  if (b.home && b.away && typeof b.home === 'object' && !Array.isArray(b.home) && !b.home.cols) {
    return ['away', 'home'].reduce((acc, side) => acc.concat(R((b[side] || {})[key]).map(r => Object.assign({ team: g[side] }, r))), []);
  }
  return R(b[key]);
}
function playoffTag(g) {
  const pg = RK.parseGameId(g.game_id);
  if (!pg) return '';
  if (pg.playoff) return RK.roundName(pg.round) + (pg.game ? ' · Game ' + pg.game : '');
  return RK.gtypeLabel(pg.type);
}

// ── header ─────────────────────────────────────────────────────────────────

function header(g, pre) {
  const st = RK.gameState(g);
  const live = st === 'live' || st === 'int', fin = st === 'final';
  const hs = isNum(g.hs) ? Number(g.hs) : null, as = isNum(g.as) ? Number(g.as) : null;
  const m = (pre && pre.model) || g.model || {};
  const pre0 = isNum(m.p_home) ? Number(m.p_home) : null;
  const pNow = live && isNum(g.wp_home) ? Number(g.wp_home) : pre0;
  const xg = g.xg || {};
  const gl = g.goalies || {};
  const GC = gameColours(g);
  const row = (t, side, score, win) => {
    const p = pNow === null || fin ? null : (side === 'home' ? pNow : 1 - pNow);
    const pf = pre0 === null ? null : (side === 'home' ? pre0 : 1 - pre0);
    const goalie = gl[side] ? RK.goalieText(gl[side]) : '';
    const sub = [side === 'home' ? 'Home' : 'Away', g.records && g.records[side] ? esc(g.records[side]) : '', goalie ? 'G ' + goalie : '',
      (live || fin) && isNum(xg[side]) ? 'xG ' + RK.num(xg[side], 2) : ''].filter(Boolean).join(' · ');
    return '<div class="gm-team' + (fin && win === false ? ' lost' : '') + '"><span class="gm-sw" style="background:' + GC[side] + '"></span>' +
      '<div class="gm-tn"><div class="gm-name">' + RK.teamLink(t, { bar: false, season: RK.gameSeason(g.game_id) }) + '</div><div class="gm-tsub">' + sub + '</div></div>' +
      '<div class="gm-score">' + (score === null || st === 'pre' ? '' : esc(score)) + '</div>' +
      '<div class="gm-p">' + (fin ? (pf !== null ? RK.pct(pf, 0) + '<small>pre-game</small>' : '') : (p !== null ? RK.pct(p, 0) + '<small>' + (live && isNum(g.wp_home) ? 'live win' : 'to win') + '</small>' : '')) + '</div></div>';
  };
  const day = g.date || RK.localDay(g.start);
  const kv = [playoffTag(g) ? esc(playoffTag(g)) : '', g.start ? esc(RK.fmtDate(g.start, { time: true })) : (day ? esc(RK.fmtDate(day)) : ''),
    day ? '<a href="' + RK.gamesHref(day) + '">all games that day</a>' : '', g.venue ? esc(g.venue) : '', isNum(g.attendance) ? 'attendance ' + RK.int(g.attendance) : '', g.series && typeof g.series === 'string' ? esc(g.series) : ''].filter(Boolean);
  let liveRow = '';
  if (live) {
    const sit = g.situation ? RK.strength(g.situation, 'home') : null;
    liveRow = '<div class="gm-live"><span class="gm-clock">' + (st === 'int' ? esc(RK.periodLabel(g.period, g) + ' intermission') : esc(RK.clockText(g.period, g.clock, g) || 'Live')) + '</span>' +
      (sit && sit.key && sit.key !== '5v5' ? '<span class="gm-sit">' + esc(RK.teamAbbr(g.home)) + ' ' + esc(sit.label) + '</span>' : '') +
      (isNum(xg.home) && isNum(xg.away) ? '<span class="gm-sit">xG ' + esc(RK.teamAbbr(g.away)) + ' ' + RK.num(xg.away, 2) + ' – ' + RK.num(xg.home, 2) + ' ' + esc(RK.teamAbbr(g.home)) + '</span>' : '') +
      (isNum(g.wp_home) ? '<span class="gm-wp">' + esc(RK.teamAbbr(g.wp_home >= 0.5 ? g.home : g.away)) + ' ' + RK.pct(Math.max(g.wp_home, 1 - g.wp_home), 1) + ' to win</span>' : '') + '</div>';
  }
  const hasLs = RK.periodsOf(g).length > 0;
  return '<div class="gm-head"><div class="gm-kicker">' + RK.statusChip(g) + kv.join(' · ') + '</div>' +
    '<div class="gm-main"><div class="gm-board">' + row(g.away, 'away', as, fin && as !== null && hs !== null ? as > hs : null) + row(g.home, 'home', hs, fin && as !== null && hs !== null ? hs > as : null) + '</div>' +
    (hasLs ? '<div class="gm-ls">' + RK.charts.linescore(g) + '</div>' : '') + '</div>' + liveRow + '</div>';
}

// ── preview ────────────────────────────────────────────────────────────────

function mvmBig(g, pre) {
  const m = pre.model || {}, mk = pre.market || g.market || {}, ln0 = pre.line || g.line || {};
  const ln = RK.isFinal(g) && ln0.close && typeof ln0.close === 'object' ? Object.assign({}, ln0, ln0.close) : ln0;
  const H = RK.teamAbbr(g.home), A = RK.teamAbbr(g.away);
  const nv = isNum(ln.ml_home) && isNum(ln.ml_away) ? RK.devigAm([ln.ml_home, ln.ml_away]) : null;
  const pRegA = isNum(m.p_reg_away) ? m.p_reg_away : (isNum(m.p_reg_home) && isNum(m.p_ot) ? 1 - m.p_reg_home - m.p_ot : null);
  const pc = RK.puckCover(g, m, ln);
  const op = ln0.open || {};
  const sub = t => '<span class="sub-line">' + t + '</span>';
  const rows = [
    { cells: [{ html: 'Win (' + esc(H) + ')' + sub('overtime and shootout included'), cls: 'mv-k' }, { html: RK.pct(m.p_home), cls: 'mv-model' },
      { html: RK.pct(mk.p_home) + (RK.srcLabel(mk.sources) ? sub(esc(RK.srcLabel(mk.sources))) : '') },
      { html: isNum(ln.ml_home) ? esc(H) + ' ' + RK.fmtOdds(ln.ml_home) + ' / ' + esc(A) + ' ' + RK.fmtOdds(ln.ml_away) + (nv !== null ? sub('no-vig ' + RK.pct(nv)) : '') +
        (isNum(op.ml_home) && op.ml_home !== ln.ml_home ? sub('open ' + RK.fmtOdds(op.ml_home) + ' / ' + RK.fmtOdds(op.ml_away)) : '') : '—' },
      { html: RK.edgeHTML(m.p_home, isNum(mk.p_home) ? mk.p_home : nv), title: 'Model minus market (or the de-vigged moneyline), percentage points' }] },
    { cells: [{ html: 'Regulation' + sub(esc(H) + ' · OT · ' + esc(A) + ' after 60 minutes'), cls: 'mv-k' },
      { html: isNum(m.p_reg_home) ? RK.pct(m.p_reg_home, 0) + ' · ' + RK.pct(m.p_ot, 0) + ' · ' + RK.pct(pRegA, 0) : '—', cls: 'mv-model' },
      { html: isNum(mk.p_reg_home) ? RK.pct(mk.p_reg_home, 0) + ' · ' + RK.pct(mk.p_ot, 0) + ' · ' + RK.pct(mk.p_reg_away, 0) : '—' }, { html: '—' },
      { html: isNum(mk.p_reg_home) ? RK.edgeHTML(m.p_reg_home, mk.p_reg_home) : '—' }] },
    { cells: [{ html: 'Overtime' + sub('tied after 60 minutes' + (isNum(m.p_so) ? '; shootout ' + RK.pct(m.p_so, 0) : '')), cls: 'mv-k' }, { html: RK.pct(m.p_ot), cls: 'mv-model' },
      { html: RK.pct(mk.p_ot) }, { html: '—' }, { html: RK.edgeHTML(m.p_ot, mk.p_ot) }] },
    { cells: [{ html: 'Puck line', cls: 'mv-k' },
      { html: pc && pc.p !== null ? esc(RK.teamAbbr(pc.team)) + ' ' + RK.fmtLine(pc.line) + ' covers ' + RK.pct(pc.p, 0) : (isNum(m.puck_line_home) && Math.abs(m.puck_line_home) >= 1 ? esc(RK.lineText(g.home, g.away, m.puck_line_home)) : '—'), cls: 'mv-model' },
      { html: isNum(mk.p_cover) ? RK.pct(mk.p_cover, 0) : '—' },
      { html: esc(RK.lineText(g.home, g.away, RK.homeLine(ln))) + (isNum(RK.homeLine(op)) && RK.homeLine(op) !== RK.homeLine(ln) ? sub('open ' + esc(RK.lineText(g.home, g.away, RK.homeLine(op)))) : '') },
      { html: pc && pc.p !== null && isNum(mk.p_cover) ? RK.edgeHTML(pc.p, mk.p_cover) : '—' }] },
    { cells: [{ html: 'Total goals', cls: 'mv-k' },
      { html: RK.num(m.total, 2) + (isNum(m.p_over) && isNum(ln.total) ? sub('over ' + RK.num(ln.total, 1) + ': ' + RK.pct(m.p_over, 0)) : ''), cls: 'mv-model' },
      { html: isNum(mk.total) ? RK.num(mk.total, 1) + (isNum(mk.p_over) ? sub('over ' + RK.pct(mk.p_over, 0)) : '') : '—' },
      { html: RK.num(ln.total, 1) + (isNum(op.total) && op.total !== ln.total ? sub('open ' + RK.num(op.total, 1)) : '') },
      { html: isNum(m.total) && isNum(ln.total) ? RK.ptsEdge(m.total - ln.total) : '—', title: 'Model total minus the line, goals' }] }
  ];
  return RK.tableHTML([{ label: '', sortable: false }, { label: 'Model', sortable: false }, { label: 'Market', sortable: false }, { label: 'Line', sortable: false }, { label: 'Model v market', sortable: false }], rows, { cls: 'mvm-big' });
}
function projBlock(g, m, ln) {
  const pc = RK.puckCover(g, m, ln || { puck_line: isNum(m.p_home) && m.p_home < 0.5 ? 1.5 : -1.5 });
  let hg = isNum(m.home_goals) ? m.home_goals : m.xg_home, ag = isNum(m.away_goals) ? m.away_goals : m.xg_away;
  if (!isNum(hg) || !isNum(ag)) return '';
  const GC = gameColours(g);
  const t = (team, v) => '<div class="pj-t"><span class="pj-s" style="color:' + GC.of(team) + '">' + RK.num(v, 2) + '</span><span class="pj-n">' + esc(RK.teamShort(team)) + '</span></div>';
  return '<div class="proj">' + t(g.away, ag) + '<span class="pj-dash">–</span>' + t(g.home, hg) + '</div>' +
    '<div class="kpi-grid three pad">' + RK.statTile('Overtime', RK.pct(m.p_ot, 0), 'tied after 60') + RK.statTile('Shootout', RK.pct(m.p_so, 0), isNum(m.p_so) ? '' : 'not modelled') +
    (pc && pc.p !== null ? RK.statTile('Puck line', RK.pct(pc.p, 0), esc(RK.teamAbbr(pc.team)) + ' ' + RK.fmtLine(pc.line) + ' covers') : RK.statTile('Puck line', '—', 'no line yet')) + '</div>';
}
function goalieCard(g) {
  const gl = g.goalies || {};
  if (!gl.home && !gl.away) return '';
  const one = side => {
    const x = gl[side];
    if (!x) return '<div class="gk"><div class="gk-t">' + RK.teamBar(g[side], gameColours(g)[side]) + esc(RK.teamAbbr(g[side])) + '</div>' + RK.muted('Not announced.') + '</div>';
    const o = typeof x === 'object' ? x : { pid: x };
    const st = String(o.status || '').toLowerCase();
    return '<div class="gk"><div class="gk-t">' + RK.teamBar(g[side], gameColours(g)[side]) + esc(RK.teamAbbr(g[side])) + (st ? ' <span class="rk-pill" style="border-color:' + (st === 'confirmed' ? RK.C.green : RK.C.yellow) + ';color:' + (st === 'confirmed' ? RK.C.green : RK.C.yellow) + '">' + esc(st) + '</span>' : '') + '</div>' +
      '<div class="gk-name">' + (o.pid ? RK.playerLink(o.pid, o.name ? { name: o.name } : null) : esc(o.name || '—')) + '</div>' +
      '<div class="gk-stats">' + [isNum(o.gp) ? o.gp + ' GP' : '', isNum(o.sv_pct) ? RK.fmtVal(o.sv_pct, 'svpct') + ' SV%' : '', isNum(o.gsax) ? RK.signed(o.gsax, 1) + ' GSAx' : ''].filter(Boolean).join(' · ') + '</div></div>';
  };
  return RK.card('Starting goalies', 'confirmed or projected; season to date', '<div class="gk-grid">' + one('away') + one('home') + '</div>');
}
function previewTab(g, pre) {
  const m = pre.model || {};
  const hasModel = isNum(m.p_home) || isNum(m.total);
  let h = '';
  if (hasModel) {
    h += '<div class="grid-32"><div>' + RK.card('Model v market v line', pre.priced_at ? 'priced ' + esc(RK.fmtStamp(pre.priced_at)) + (RK.isPre(g) ? '' : ' · frozen at puck drop') : '', mvmBig(g, pre) +
      '<div class="chart-note">The puck line is the favourite\'s (negative = favoured by more than a goal). The market is the de-vigged prediction-market price; the line is the sportsbook line as ESPN shows it. For information only.</div>') + '</div>' +
      '<div>' + RK.card('Projected score', 'expected goals in regulation and overtime', projBlock(g, m, pre.line || g.line) || RK.muted('No projection.')) + goalieCard(g) + '</div></div>';
    const sd = m.score_dist || m.scores, td = m.total_dist;
    if (sd || td) {
      h += '<div class="grid-2">' +
        (sd ? RK.card('Exact scores', (RK.charts.isFinalScores(sd) ? 'final score, overtime and shootout winners included · up to 6 goals a side' : 'regulation · dotted diagonal: tied, to overtime') +
          (RK.isFinal(g) ? ' · outlined: the final' : ''), '<div id="gm-sd"></div>') : '<div></div>') +
        (td ? RK.card('Total goals', 'dashed: the line · dotted: our mean', '<div id="gm-td"></div>') : '<div></div>') + '</div>';
    }
  } else {
    h += RK.card('Model v market v line', '', RK.muted('The pre-game price is not available for this game.')) + goalieCard(g);
  }
  return { html: h, after: root => {
    const sd = m.score_dist || m.scores, td = m.total_dist;
    const ln = pre.line || g.line || {};
    const fin = RK.isFinal(g) && isNum(g.hs) && isNum(g.as);
    if (sd && root.querySelector('#gm-sd')) RK.charts.scoreGrid(root.querySelector('#gm-sd'), sd, { home: g.home, away: g.away, actual: fin && (RK.endedIn(g) === '' || RK.charts.isFinalScores(sd)) ? [g.hs, g.as] : null, height: 300 });
    if (td && root.querySelector('#gm-td')) RK.charts.distBars(root.querySelector('#gm-td'), td, { line: ln.total, exp: m.total, actual: fin ? Number(g.hs) + Number(g.as) : null, unit: 'goals', height: 300, xTitle: 'Total goals' });
  } };
}

// ── flow ───────────────────────────────────────────────────────────────────

function goalsTable(g, goals) {
  if (!goals.length) return '';
  const playoff = RK.isPlayoffGame(g);
  return RK.card('Goals', goals.length + ' · strength from the scoring team\'s side', RK.tableHTML([{ label: 'When' }, { label: 'Team' }, { label: 'Scorer' }, { label: 'Assists', sortable: false },
    { label: 'Strength' }, { label: 'Shot' }, { label: 'xG', align: 'right' }],
  goals.map(x => {
    const side = sideOf(g, x.team);
    const s = x.strength !== undefined && x.strength !== null && x.strength !== '' ? RK.strength(x.strength, side) : null;
    return [{ html: esc(isNum(x.sec) ? RK.secText(x.sec, playoff) : RK.periodLabel(x.period, { playoff: playoff })), v: x.sec },
      { html: RK.teamLink(x.team, { abbr: true }), v: x.team },
      { html: x.player ? RK.playerLink(x.player, x.name ? { name: x.name } : null) : esc(x.name || '—'), v: x.name || RK.playerName(x.player) },
      { html: (x.assists || []).length ? x.assists.map(a => RK.playerLink(a, { surname: true })).join(', ') : '<span class="muted-inline">unassisted</span>' },
      { html: s ? (RK.strengthTag(x.strength, side) || esc(s.short)) : '—', v: s ? s.key : '' },
      esc(x.shot_type ? RK.titleCase(x.shot_type) : '—'),
      { html: isNum(x.xg) ? RK.num(x.xg, 2) : '—', v: x.xg }];
  }), { compact: true }));
}
const AWARD_TITLE = { first_star: 'First star', second_star: 'Second star', third_star: 'Third star', mvp: 'Player of the game', goalie: 'Best goalie', line: 'Top line' };
const STARS = ['First star', 'Second star', 'Third star'];
function awardsOf(g) {
  const a = g.awards;
  if (!a) return [];
  if (Array.isArray(a)) return a;
  if (Array.isArray(a.stars) || a.top_xg || a.best_line) {
    const out = (a.stars || []).map((x, i) => ({ title: STARS[i] || 'Star', pid: x.id || x.pid, name: x.name, team: x.team, value: x.line || (isNum(x.score) ? 'game score ' + RK.num(x.score, 2) : null), why: '' }));
    if (a.top_xg) out.push({ title: 'Most individual xG', pid: a.top_xg.id || a.top_xg.pid, name: a.top_xg.name, team: a.top_xg.team, value: isNum(a.top_xg.ixg) ? RK.num(a.top_xg.ixg, 2) + ' ixG' : null });
    if (a.best_line) out.push({ title: 'Best line (5v5)', players: a.best_line.ids || a.best_line.players, names: a.best_line.names, team: a.best_line.team,
      value: isNum(a.best_line.xg_diff) ? RK.signed(a.best_line.xg_diff, 2) + ' xG differential' : null, why: isNum(a.best_line.toi) ? RK.fmtTOI(RK.toiGame(a.best_line.toi)) + ' together' : '' });
    return out;
  }
  return Object.keys(a).filter(k => a[k] && typeof a[k] === 'object').map(k => Object.assign({ title: AWARD_TITLE[k] || RK.titleCase(k) }, a[k]));
}
function awardsBlock(g) {
  const list = awardsOf(g);
  if (!list.length) return '';
  const method = g.awards && g.awards.method ? '<div class="chart-note">' + esc(g.awards.method) + '</div>' : '';
  return RK.card('Awards', 'from our models: xG, GSAx and on-ice impact', '<div class="awards">' + list.map(a =>
    '<div class="award"' + (a.team ? ' style="border-top-color:' + gameColours(g).of(a.team) + '"' : '') + '><span class="aw-title">' + esc(a.title || a.award || '') + '</span>' +
    '<span class="aw-who">' + (a.pid ? RK.playerLink(a.pid, a.name ? { name: a.name } : null) : (a.players ? a.players.map((p, k) => RK.playerLink(p, (a.names || [])[k] ? { name: RK.surnameOf(a.names[k]) } : { surname: true })).join(' – ') : a.team ? RK.teamLink(a.team) : esc(a.name || ''))) +
    (a.pid && a.team ? '<span class="pl-team">' + esc(RK.teamAbbr(a.team)) + '</span>' : '') + '</span>' +
    (a.value !== undefined && a.value !== null ? '<span class="aw-val">' + esc(isNum(a.value) ? RK.signed(a.value, 2) : a.value) + '</span>' : '') + (a.why ? '<span class="aw-why">' + esc(String(a.why).slice(0, 200)) + '</span>' : '') + '</div>').join('') + '</div>' + method);
}
function flowTab(g, pre, shots) {
  const goals = goalsOf(g, shots);
  const hasShots = shots.length > 0;
  const hasRace = hasShots || !!g.xg_race;
  const wp = RK.charts.wpRows(g.wp || g.wp_chart);
  const wpSrc = g.wp && g.wp.source ? String(g.wp.source) : '';
  const playoff = RK.isPlayoffGame(g);
  let h = '';
  if (!hasShots && !wp.length) {
    return { html: RK.card('Game flow', '', RK.muted(RK.isPre(g) ? 'The game flow starts at puck drop: expected goals, win probability and the shot maps fill in live.' : 'No play-by-play for this game yet.')) + awardsBlock(g), after: null };
  }
  h += '<div class="grid-2">' +
    RK.card('Expected goals', 'cumulative xG for each team · ● goals', hasRace ? '<div id="gm-xg"></div>' : RK.muted('No shots yet.')) +
    RK.card('Win probability', esc(RK.teamAbbr(g.home)) + ' (home), ' + (wpSrc && !/^(model|live|ours)$/.test(wpSrc) ? esc(wpSrc) + ' model' : 'our model') + ' · ● goals' + (pre && pre.market && isNum(pre.market.p_home) ? ' · tick: pre-game market' : ''), wp.length >= 2 ? '<div id="gm-wp"></div>' : RK.muted('No win-probability path yet.')) + '</div>';
  if (hasShots) {
    h += '<div class="grid-2 gm-maps">' + ['away', 'home'].map(side => RK.card(RK.teamName(g[side]) + ' shots', 'attacking right · size = xG · ● goal ○ on goal', '<div id="gm-map-' + side + '"></div>')).join('') + '</div>';
  }
  h += goalsTable(g, goals) + awardsBlock(g);
  return { html: h, after: root => {
    if (hasRace && root.querySelector('#gm-xg')) RK.charts.xgRace(root.querySelector('#gm-xg'), hasShots ? g.shots : g.xg_race, { home: g.home, away: g.away, playoff: playoff, height: 290,
      until: RK.isLive(g) && shots.length ? Math.max.apply(null, shots.map(x => (isNum(x.sec) ? x.sec : 0))) : null });
    if (wp.length >= 2 && root.querySelector('#gm-wp')) RK.charts.wpChart(root.querySelector('#gm-wp'), wp, { home: g.home, away: g.away, playoff: playoff, goals: goals, height: 290,
      market: pre && pre.market && isNum(pre.market.p_home) ? pre.market.p_home : null });
    if (hasShots) ['away', 'home'].forEach(side => {
      const n = root.querySelector('#gm-map-' + side);
      if (n) RK.charts.shotMap(n, shots.filter(s => String(s.team) === String(g[side])), { home: g.home, away: g.away, team: g[side], teamToggle: false, playoff: playoff, colours: { [g[side]]: gameColours(g)[side] } });
    });
  } };
}

// ── lines and TOI ──────────────────────────────────────────────────────────

const UNIT_LABEL = { forwards: 'Forward lines', defence: 'Defence pairs', defense: 'Defence pairs', pairs: 'Defence pairs', pp: 'Power-play units', pk: 'Penalty-kill units' };
function unitTable(g, side, key, list) {
  const rows = list.map((u, i) => {
    const xgf = isNum(u.xgf) ? Number(u.xgf) : null, xga = isNum(u.xga) ? Number(u.xga) : null;
    const xp = xgf !== null && xga !== null && xgf + xga > 0 ? xgf / (xgf + xga) : (isNum(u.xgf_pct) ? Number(u.xgf_pct) : null);
    const cf = isNum(u.cf) && isNum(u.ca) && u.cf + u.ca > 0 ? u.cf / (u.cf + u.ca) : (isNum(u.cf_pct) ? Number(u.cf_pct) : null);
    const by = u.toi_by || u.toi_strength || {};
    const ids = u.players || u.ids || [];
    return [{ html: '<span class="lu-n">' + (i + 1) + '</span>' + ids.map((p, k) => RK.playerLink(p, (u.names || [])[k] ? { name: RK.surnameOf(u.names[k]) } : { surname: true })).join(' – '), v: i },
      { html: RK.fmtTOI(RK.toiGame(u.toi)), v: RK.toiGame(u.toi) },
      { html: ['5v5', 'PP', 'PK'].filter(k => isNum(by[k])).map(k => '<span class="toi-k">' + (k === 'PK' ? 'SH' : k) + '</span> ' + RK.fmtTOI(RK.toiGame(by[k]))).join(' ') || '—' },
      { html: RK.num(xgf, 2), v: xgf }, { html: RK.num(xga, 2), v: xga },
      { html: xp === null ? '—' : '<span class="' + (xp >= 0.5 ? 'edge-pos' : 'edge-neg') + '">' + RK.pct(xp, 0) + '</span>', v: xp },
      { html: isNum(u.gf) || isNum(u.ga) ? (u.gf || 0) + '–' + (u.ga || 0) : '—', v: (u.gf || 0) - (u.ga || 0) },
      { html: RK.pct(cf, 0), v: cf }];
  });
  const hasBy = list.some(u => u.toi_by || u.toi_strength);
  if (!hasBy) rows.forEach(r => r.splice(2, 1));
  return '<div class="box-head">' + esc(UNIT_LABEL[key] || RK.titleCase(key)) + '</div>' + RK.tableHTML([{ label: 'Unit' }, { label: 'TOI', align: 'right' }].concat(hasBy ? [{ label: 'By strength', sortable: false }] : []).concat([
    { label: 'xGF', align: 'right', title: 'Expected goals for with the unit on the ice' }, { label: 'xGA', align: 'right' }, { label: 'xGF%', align: 'right' },
    { label: 'GF–GA', align: 'right' }, { label: 'CF%', align: 'right', title: 'Share of shot attempts' }]), rows, { compact: true, cls: 'lu-table' });
}
function linesTab(g) {
  const L0 = g.lines || g.line_usage || {};
  const L = { home: L0.home || L0[g.home] || null, away: L0.away || L0[g.away] || null };
  const U = g.usage || {};
  const usage = ['home', 'away'].reduce((acc, side) => acc.concat(R(U[side] || U[g[side]]).map(r => aliasRow(Object.assign({ team: g[side] }, r)))), []);
  const skaters = usage.length ? usage : boxRows(g, 'skaters');
  const hasToi = skaters.some(r => isNum(RK.toiGame(r.toi_ev)) || isNum(RK.toiGame(r.toi_pp)));
  const hasLines = ['home', 'away'].some(s => L[s] && Object.keys(L[s]).some(k => R(L[s][k]).length));
  if (!hasLines && !hasToi) return { html: RK.card('Lines and time on ice', '', RK.muted(RK.isPre(g) ? 'Line usage fills in from the shift charts once the game starts.' : 'No shift data for this game yet.')), after: null };
  let h = '';
  if (hasLines) {
    h += '<div class="grid-2">' + ['away', 'home'].map(side => {
      const u = L[side] || {};
      const keys = Object.keys(u).filter(k => R(u[k]).length).sort((a, b) => ['forwards', 'defence', 'defense', 'pairs', 'pp', 'pk'].indexOf(a) - ['forwards', 'defence', 'defense', 'pairs', 'pp', 'pk'].indexOf(b));
      return RK.card(RK.teamName(g[side]), 'from the shift charts', keys.length ? keys.map(k => unitTable(g, side, k, R(u[k]))).join('') : RK.muted('No units.'));
    }).join('') + '</div>';
  }
  if (hasToi) h += '<div class="grid-2">' + ['away', 'home'].map(side => RK.card(RK.teamAbbr(g[side]) + ' time on ice by strength', 'minutes · 5v5 (even strength), power play, shorthanded', '<div id="gm-toi-' + side + '"></div>')).join('') + '</div>';
  return { html: h, after: root => {
    if (!hasToi) return;
    ['away', 'home'].forEach(side => {
      const n = root.querySelector('#gm-toi-' + side);
      if (!n) return;
      const list = skaters.filter(r => String(r.team) === String(g[side])).map(r => ({ pid: r.pid || r.player, name: r.name, ev: RK.toiGame(r.toi_ev) || 0, pp: RK.toiGame(r.toi_pp) || 0, pk: RK.toiGame(r.toi_pk) || 0, all: RK.toiGame(r.toi) }))
        .map(r => Object.assign(r, { all: isNum(r.all) ? r.all : r.ev + r.pp + r.pk })).sort((a, b) => a.all - b.all);
      if (!list.length) { n.innerHTML = RK.muted('No skaters.'); return; }
      // initial and surname: two Tkachuks on one bench must not share a bar
      const y = list.map(r => (r.name ? (String(r.name).split(' ').length > 1 ? r.name.charAt(0) + '. ' + RK.surnameOf(r.name) : r.name) : RK.playerShort(r.pid)));
      const tr = (k, name, col) => ({ type: 'bar', orientation: 'h', name: name, y: y, x: list.map(r => r[k] / 60), marker: { color: col },
        text: list.map(r => RK.fmtTOI(r[k])), hovertemplate: '%{y} · ' + name + ' %{text}<extra></extra>' });
      const tc = gameColours(g)[side];
      const near = (a, b) => { const A = RK.charts.hexA(a, 1).match(/\d+/g).map(Number), B = RK.charts.hexA(b, 1).match(/\d+/g).map(Number); return Math.abs(A[0] - B[0]) + Math.abs(A[1] - B[1]) + Math.abs(A[2] - B[2]) < 120; };
      const shC = near(tc, RK.C.goal) ? RK.C.yellow : RK.C.goal, ppC = near(tc, RK.C.ice) ? RK.C.purple : RK.C.ice;
      RK.plot(n, [tr('ev', '5v5', tc), tr('pp', 'PP', ppC), tr('pk', 'SH', shC)], RK.layout({ barmode: 'stack', height: Math.max(220, list.length * 20 + 70),
        showlegend: true, legend: { orientation: 'h', y: 1.08, x: 0, font: { size: 10, color: RK.C.text2 } }, xaxis: { title: { text: 'Minutes', font: { size: 10 } }, fixedrange: true },
        yaxis: { automargin: true, fixedrange: true, tickfont: { size: 10 } }, margin: { l: 90, r: 10, t: 24, b: 36 } }));
    });
  } };
}

// ── box score ──────────────────────────────────────────────────────────────

const SK_COLS = [['g', 'G'], ['a', 'A'], ['pts', 'P'], ['sog', 'SOG'], ['ixg', 'ixG'], ['icf', 'iCF'], ['hits', 'Hits'], ['blk', 'Blk'], ['gv', 'GV'], ['tk', 'TK'], ['fo', 'FO'], ['pim', 'PIM'],
  ['toi', 'TOI'], ['toi_ev', '5v5'], ['toi_pp', 'PP'], ['toi_pk', 'SH'], ['xgf_pct', 'xGF%'], ['cf_pct', 'CF%'], ['pm', '+/-'], ['gs', 'GS']];
const SK_TITLE = { icf: 'Individual shot attempts', cf_pct: 'On-ice share of shot attempts (5v5)', gs: 'Game score', pim: 'Penalty minutes', ixg: 'Individual expected goals', gv: 'Giveaways', tk: 'Takeaways', fo: 'Face-offs won–lost', toi_ev: 'Even-strength TOI', toi_pp: 'Power-play TOI', toi_pk: 'Shorthanded TOI',
  xgf_pct: 'On-ice share of expected goals (5v5)', blk: 'Blocked shots' };
function skaterTable(g, side, list) {
  const has = k => (k === 'fo' ? list.some(r => isNum(r.fow) || isNum(r.fol)) : list.some(r => r[k] !== undefined && r[k] !== null));
  const cols = SK_COLS.filter(c => has(c[0]));
  const rows = list.map(r => {
    const pid = r.pid || r.player;
    return [{ html: RK.playerLink(pid, r.name ? { name: r.name } : null) + '<span class="pl-pos">' + esc(r.pos || RK.player(pid).pos || '') + '</span>', v: r.name || RK.playerName(pid) }].concat(cols.map(c => {
      const k = c[0];
      if (k === 'fo') return { html: isNum(r.fow) || isNum(r.fol) ? (r.fow || 0) + '–' + (r.fol || 0) : '—', v: (r.fow || 0) + (r.fol || 0) ? (r.fow || 0) / ((r.fow || 0) + (r.fol || 0)) : null };
      if (/^toi/.test(k)) return { html: RK.fmtTOI(RK.toiGame(r[k])), v: RK.toiGame(r[k]) };
      if (k === 'ixg') return { html: RK.num(r[k], 2), v: r[k] };
      if (k === 'xgf_pct' || k === 'cf_pct') return { html: RK.pct(r[k], 0), v: r[k] };
      if (k === 'gs') return { html: RK.num(r[k], 2), v: r[k] };
      if (k === 'pm') return { html: RK.signed(r[k], 0), v: r[k] };
      return { html: isNum(r[k]) ? String(r[k]) : '—', v: r[k] };
    }));
  });
  return '<div class="box-head">' + RK.teamBar(g[side], gameColours(g)[side]) + esc(RK.teamName(g[side])) + '</div>' +
    RK.tableHTML([{ label: 'Skater' }].concat(cols.map(c => ({ label: c[1], align: 'right', title: SK_TITLE[c[0]] || null }))), rows, { compact: true, cls: 'box-table' });
}
function goalieTable(g, list) {
  const rows = list.map(r => {
    const pid = r.pid || r.player;
    return [{ html: RK.playerLink(pid, r.name ? { name: r.name } : null), v: r.name || RK.playerName(pid) }, { html: RK.teamLink(r.team, { abbr: true }), v: r.team },
      isNum(r.sa) ? r.sa : '—', isNum(r.sv) ? r.sv : '—', isNum(r.ga) ? r.ga : '—', { html: RK.fmtVal(r.sv_pct, 'svpct'), v: r.sv_pct },
      { html: RK.num(r.xga, 2), v: r.xga }, { html: isNum(r.gsax) ? '<span class="' + (r.gsax >= 0 ? 'edge-pos' : 'edge-neg') + '">' + RK.signed(r.gsax, 2) + '</span>' : '—', v: r.gsax },
      { html: RK.fmtTOI(RK.toiGame(r.toi)), v: RK.toiGame(r.toi) }];
  });
  return RK.card('Goalies', 'GSAx: goals saved above expected (xG of unblocked shots on goal faced minus goals allowed)', RK.tableHTML([{ label: 'Goalie' }, { label: 'Team' }, { label: 'SA', align: 'right' }, { label: 'SV', align: 'right' },
    { label: 'GA', align: 'right' }, { label: 'SV%', align: 'right' }, { label: 'xGA', align: 'right' }, { label: 'GSAx', align: 'right' }, { label: 'TOI', align: 'right' }], rows, { compact: true, cls: 'box-table' }));
}
function teamStats(g) {
  const b = g.box || {};
  const list = R(b.team || b.teams);
  if (!list.length) return '';
  const fmt = (stat, v) => {
    if (!isNum(v)) return esc(v === null || v === undefined ? '—' : v);
    const x = Number(v);
    if (/%|pct|share/i.test(stat) && x <= 1) return RK.pct(x, 1);
    return Number.isInteger(x) ? String(x) : RK.num(x, 2);
  };
  return RK.card('Team stats', '', RK.tableHTML([{ label: '', sortable: false }, { label: RK.teamAbbr(g.away), align: 'right', sortable: false }, { label: RK.teamAbbr(g.home), align: 'right', sortable: false }],
    list.map(r => [{ html: esc(r.stat || r.label || '') }, { html: fmt(r.stat || '', r.away) }, { html: fmt(r.stat || '', r.home) }]), { compact: true, cls: 'box-table' }));
}
function boxTab(g) {
  const sk = boxRows(g, 'skaters'), gk = boxRows(g, 'goalies');
  if (!sk.length && !gk.length && !R((g.box || {}).team).length) return { html: RK.card('Box score', '', RK.muted(RK.isPre(g) ? 'The box score fills in from puck drop.' : 'No box score yet.')), after: null };
  const h = (sk.length ? RK.card('Skaters', 'with individual xG, TOI by strength and on-ice xGF%', ['away', 'home'].map(side => skaterTable(g, side, sk.filter(r => String(r.team) === String(g[side])))).join('')) : '') +
    (gk.length ? goalieTable(g, gk) : '') + teamStats(g);
  return { html: h + '<div class="chart-note">xG, GSAx and on-ice xGF% are our model\'s; the counting stats are the NHL\'s.</div>', after: null };
}

// ── page ───────────────────────────────────────────────────────────────────

/* Names carried by the game payload (box, usage, lines, awards) for players missing from players_index.json. */
function learnNames(g) {
  const put = (id, name, team, pos) => { if (id && name && !(RK.player(id) || {}).name) RK.putPlayer(String(id), { name: name, team: team, pos: pos }); };
  ['skaters', 'goalies'].forEach(k => boxRows(g, k).forEach(r => put(r.pid, r.name, r.team, r.pos)));
  const U = g.usage || {};
  Object.keys(U).forEach(t => R(U[t]).forEach(r => put(r.id || r.pid, r.name, t, r.pos)));
  const L = g.lines || {};
  Object.keys(L).forEach(t => Object.keys(L[t] || {}).forEach(k => R(L[t][k]).forEach(u => (u.ids || []).forEach((id, i) => put(id, (u.names || [])[i], t)))));
  const A = g.awards || {};
  (A.stars || []).forEach(x => put(x.id, x.name, x.team));
}
function cardFor(id) {
  const idx = RK.index() || {};
  return ['today', 'live', 'recent', 'upcoming'].reduce((acc, k) => acc || (idx[k] || []).find(c => c && c.game_id === id), null);
}
RK.route('game', function (el, params) {
  const id = params.id;
  const S = RK.gameSeason(id);
  return RK.loadGame(id).then(g0 => {
    if (!RK.ok(g0)) {
      // fall back to the schedule for a card
      return RK.loadYear('schedule.json', S).then(sch => {
        if (!el.isConnected) return;
        const c = cardFor(id) || (RK.ok(sch) ? (sch.games || []).find(x => x && String(x.game_id) === String(id)) : null);
        el.innerHTML = RK.pageHead(c ? RK.teamName(c.away) + ' at ' + RK.teamName(c.home) : 'Game ' + id, c ? esc(RK.fmtDate(c.date || c.start)) + ' · ' + esc(playoffTag(c)) : '',
          c ? '<a href="' + RK.gamesHref(c.date || RK.localDay(c.start)) + '">All games that day</a>' : '') +
          (c ? '<div class="gc-grid gm-solo">' + RK.gameCard(c, { goalies: true }) + '</div>' : '') +
          RK.notBuilt('The game centre for ' + id, g0) + (S && S < RK.currentSeason() - 10001 ? RK.muted('Game pages are kept for the current and the previous season.') : '');
      });
    }
    if (!el.isConnected) return;
    const g = Object.assign({}, cardFor(id) || {}, g0.card || {}, g0);
    if (!g.game_id) g.game_id = id;
    // the live card in index.json is fresher than a cached game payload
    const fresh = cardFor(id);
    if (fresh && RK.isLive(fresh)) ['status', 'period', 'clock', 'hs', 'as', 'wp_home', 'xg', 'intermission'].forEach(k => { if (fresh[k] !== undefined && fresh[k] !== null) g[k] = fresh[k]; });
    const pre = Object.assign({}, g.pregame || g.pre || {});
    if (!pre.model) pre.model = g.model || {};
    if (!pre.market) pre.market = g.market || null;
    if (!pre.line) pre.line = g.line || null;
    if (!g.goalies && g.card && g.card.goalies) g.goalies = g.card.goalies;
    learnNames(g);
    const shots = RK.charts.shotRows(g.shots);
    if (!g.xg && shots.length) {
      const sum = t => shots.filter(s => String(s.team) === String(t)).reduce((a, s) => a + (isNum(s.xg) ? s.xg : 0), 0);
      g.xg = { home: sum(g.home), away: sum(g.away) };
    }
    const st = RK.gameState(g);
    const live = st === 'live' || st === 'int';
    const tabs = [['preview', 'Preview'], ['flow', 'Game flow'], ['lines', 'Lines & TOI'], ['box', 'Box score']];
    const q = (params.query || {}).tab;
    let tab = TAB[id] || (tabs.some(t => t[0] === q) ? q : (st === 'pre' ? 'preview' : 'flow'));
    document.title = RK.teamAbbr(g.away) + ' @ ' + RK.teamAbbr(g.home) + ' · ' + RK.SITE;
    el.innerHTML = header(g, pre) + '<div class="seg-tabs gm-tabs">' + tabs.map(t => '<a data-tab="' + t[0] + '"' + (t[0] === tab ? ' class="active"' : '') + '>' + esc(t[1]) + '</a>').join('') + '</div><div id="gm-body"></div>';
    const body = el.querySelector('#gm-body');
    const show = k => {
      tab = k; TAB[id] = k;
      el.querySelectorAll('.gm-tabs a').forEach(a => a.classList.toggle('active', a.dataset.tab === k));
      const out = k === 'preview' ? previewTab(g, pre) : k === 'flow' ? flowTab(g, pre, shots) : k === 'lines' ? linesTab(g) : boxTab(g);
      RK.purge(body);
      body.innerHTML = out.html;
      RK.sortable(body);
      if (out.after) out.after(body);
    };
    el.querySelectorAll('.gm-tabs a').forEach(a => a.addEventListener('click', () => show(a.dataset.tab)));
    show(tab);
    RK.setMeta(live ? '<span class="live-dot"></span> live · refreshed every 30 seconds' : '');
    if (live) RK.liveRefresh([RK.gamePath(id)], 30000);
  });
});

})(window.RK);
