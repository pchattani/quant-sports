/* The Quant Hardwood — the team page (#/<L>/team/<tid>), on kit v4 "Broadcast" (the Rink's team page is the reference).
 *
 * Overview tab: the full-bleed team-colour hero (the last ten results as form dots) with the black strip of numbers
 * (record, our playoff and title chances, projected wins with the simulation's 90% range as the likely-range bar, the
 * net rating with its percentile among the league's teams) and "The short version"; "How sure are we?"; what to watch
 * next (the scoreboard bug) beside the last game (its score, the line score by quarter and our win chance through it,
 * from the game file); the net rating through the
 * season (±1 standard error shaded, results marked); our season chances and the final-seed distribution; strengths
 * and needs (current season; no trade targets: the user's call, 25 Oct 2026); top performers overall and by role
 * against the league (QKL.performers, from players.json's role, qualified flag and role percentiles); the current roster as a leaderboard; the schedule (next
 * games with our win chance and the team's availability line, recent results); moves.
 * Detail tab (?tab=detail): the pre-redesign team page in full (four factors, shot profiles, lineups, on/off,
 * rotation, the whole catalogue in percentiles, the trade ledger).
 *
 * Current roster: <L>/<S>/valuation.json (built each run from the latest ESPN rosters: every player whose team is
 * this one, with injury status), joined with the season's numbers from players.json. A past season shows everyone
 * who played for the team (teams.json roster). The market is not shown here (game pages and the Model page only). */
(function (HW) {
'use strict';

const U = HW.ui, esc = HW.esc, isNum = HW.isNum;

function standRow(season, tid) {
  let out = null;
  const st = (season && season.standings) || {};
  Object.keys(st).forEach(c => (st[c] || []).forEach(r => { if (String(r.team) === String(tid)) out = Object.assign({ conf: c }, r); }));
  return out || {};
}

// The informed model's availability term for this team in its next game (GAME_CARD model.av: points of the
// team's own margin from who is expected to play, injury-report Outs applied).
function avNote(g, home) {
  const av = (g.model || {}).av;
  if (!av || !isNum(av[0]) || !isNum(av[1])) return '';
  const v = home ? av[0] : av[1];
  if (Math.abs(v) < 0.05) return '';
  return '<span class="s" style="white-space:nowrap" data-tip="Availability for the next game: points of margin from who is expected to play (injury report applied), against what the rating already reflects">availability ' + U.sgnHTML(v, 1) + ' pts</span>';
}

/* Top performers (QKL.performers): the team's best qualified players by HPM (our plus-minus: points per 100
   possessions better than average), overall and by role (guards / wings / bigs, the spec's role groups), each with its
   percentile among the league's qualified players of that role (players.json pct_role.hpm, the spec's minutes floor
   via `qualified`) and its rank among them. */
const ROLES = [['G', 'Guards', 'guards'], ['W', 'Wings', 'wings'], ['B', 'Bigs', 'bigs']];
function topPerformers(node, L, S, tid, cat) {
  if (!node) return;
  const P = (cat && cat.players) || {};
  const all = Object.keys(P).map(id => Object.assign({ id: id }, P[id])).filter(p => p.qualified && p.role && isNum((p.values || {}).hpm));
  const rank = {}, n = {};
  ROLES.forEach(r => {
    const pool = all.filter(p => p.role === r[0]).sort((a, b) => b.values.hpm - a.values.hpm);
    n[r[0]] = pool.length;
    pool.forEach((p, i) => { rank[p.id] = i + 1; });
  });
  const peer = {}; ROLES.forEach(r => { peer[r[0]] = r[2]; });
  const row = p => ({ name: p.name, href: HW.playerHref(L, p.id, S), pos: U.ROLE1[p.role] || p.pos, value: U.signed(p.values.hpm, 1),
    pct: (p.pct_role || {}).hpm, rank: rank[p.id], n: n[p.role], peer: peer[p.role] });
  const mine = all.filter(p => String(p.team) === String(tid)).sort((a, b) => b.values.hpm - a.values.hpm);
  const floor = cat && cat.min_floor;
  QKL.performers(node, {
    title: 'Who carries them, and how they compare',
    sub: 'The best players by our plus-minus, overall and at each role, against every qualified player in the ' + HW.leagueName(L) + '.',
    metric: { label: 'HPM', unit: 'points per 100 possessions v average', model: 'HPM (Hardwood plus-minus)' },
    overall: mine.slice(0, 4).map(row),
    groups: ROLES.map(r => ({ label: r[1], rows: mine.filter(p => p.role === r[0]).slice(0, 3).map(row) })),
    note: 'The box is the league percentile among qualified players of the same role (guards, wings, bigs) on HPM, our estimate of the points per 100 possessions a player adds; the rank counts the same players. Qualified: at least ' + (floor || 'the season’s') + ' minutes so far (a fifth of the most played).',
    empty: 'Nobody has reached the minutes floor yet' + (floor ? ' (' + floor + ' minutes)' : '') + ': the list fills in after a few games.'
  });
}

/* "The short version" (as the Rink's team page): the record and the seed, our playoff and title chances, the net rating
   and its rank, then, from 10 games (the Rink's floor for ranks), what the team does best and its weak spot among the
   league's teams on the league block's team set (season.json league_block: percentiles oriented so 100 is best; style
   metrics such as pace left out). Small samples are named. */
const NUMW = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten'];
/* "about 3 in 10" for a chance, in hundreds near the ends (1% is about 1 in 100, never "1 in 10") */
function freqWords(p) {
  if (p >= 0.995) return 'nearly all';
  if (p <= 0.005) return 'almost none';
  return p < 0.095 || p > 0.905 ? 'about ' + Math.round(p * 100) + ' in 100' : 'about ' + Math.round(p * 10) + ' in 10';
}
const RANK_GP = 10;
function lc(x) { return /^[A-Z][a-z]/.test(x) ? x.charAt(0).toLowerCase() + x.slice(1) : x; }
function shortTeam(L, tid, isCur, s, sim, r, lbT, prof, nTeams) {
  const nm = HW.teamShort(L, tid);
  const gp = (s.w || 0) + (s.l || 0);
  if (!gp) return isCur && isNum(sim.p_playoffs) ? 'No games yet. Before the opening tip we give the ' + nm + ' a ' + U.pct(sim.p_playoffs) + ' chance of making the playoffs.' : null;
  /* the season in play reads in the present; a finished one (a past season, or this one in the offseason) in the past */
  const over = !isCur || HW.phase(L) === 'offseason';
  let t = 'The ' + nm + (over ? ' finished ' : ' are ') + HW.record(s.w, s.l) + (isNum(s.seed) ? ', ' + HW.ordinal(s.seed) + ' in the ' + (s.conf || 'league') : '') + '.';
  if (isCur && isNum(sim.p_playoffs)) t += ' We give them a ' + U.pct(sim.p_playoffs) + ' chance of the playoffs' + (isNum(sim.p_title) ? ' and ' + U.pct(sim.p_title) + ' to win the title' : '') + '.';
  if (isNum(r.net)) t += ' Our net rating of ' + U.signed(r.net, 1) + ' points per 100 possessions' + (isNum(r.rank) && nTeams ? ' ranks ' + HW.ordinal(r.rank) + ' of ' + nTeams : '') + '.';
  const pc = (lbT && lbT.pct) || {};
  /* process metrics only (as the Rink's): the rating itself and the results group (the average margin) are left out */
  const rows = (prof || []).filter(m => m && !m.style && m.id !== 'model_net' && m.group !== 'Results' && isNum(pc[m.id])).map(m => [m.id, pc[m.id], m.label]);
  if (gp >= RANK_GP && rows.length) {
    const top = rows.slice().sort((a, b) => b[1] - a[1])[0], low = rows.slice().sort((a, b) => a[1] - b[1])[0];
    if (top[1] >= 70) t += ' Best at ' + lc(top[2]) + ' (' + QK.ordinal(Math.round(top[1])) + ' percentile of the ' + (nTeams || 'league’s') + ' teams).';
    if (low[1] <= 30 && low[0] !== top[0]) t += ' The weak spot: ' + lc(low[2]) + ', in the ' + QK.ordinal(Math.round(low[1])) + ' percentile.';
  } else if (gp < RANK_GP) t += ' ' + (NUMW[gp] || gp) + ' game' + (gp === 1 ? ' is' : 's is') + ' a small sample, so the strengths and weak spots start after ' + RANK_GP + '.';
  return t;
}

/* What to watch next (the scoreboard bug and how the teams match up, as the Rink's team page) beside the last game:
   its score as the title, our pre-game chance against the result, the line score by quarter and our win chance
   through it (the game file, as the player page). No market here: it sits on the game page only. */
function nextAndLast(L, S, tid, upcoming, log, season) {
  const nxt = upcoming[0] || null, last = log.length ? log[log.length - 1] : null;
  if (!nxt && !last) return '';
  let h = '<section class="qk-section hw-sec1"><div class="qk-g2">';
  if (nxt) {
    const st0 = U.status(nxt);
    const R = (season && season.ratings) || {};
    /* before tip-off the season to date; live, the teams going in (fillNext, the game file's tape_pre) or no rows */
    const fx = st0 === 'pre' ? U.clubRows(R[String(nxt.away)] || {}, R[String(nxt.home)] || {}) : [];
    const m = nxt.model || {};
    const extra = st0 === 'pre' && isNum(m.margin) ? 'We expect ' + HW.teamAbbr(L, m.margin >= 0 ? nxt.home : nxt.away) + ' by about ' + Math.max(1, Math.round(Math.abs(m.margin))) + (isNum(m.total) ? ', with about ' + Math.round(m.total) + ' points in all' : '') + '.' : '';
    h += '<div>' + QK.sectionHead({ kicker: st0 === 'live' ? 'Live now' : (QK.fmt.relDay(nxt.date) === 'Today' ? 'What to watch tonight' : 'Next up'), title: U.nick(L, nxt.away) + ' at ' + U.nick(L, nxt.home) }) +
      '<div id="tp-next-bug">' + QK.previewCard(U.game(nxt, L, { records: U.records(season) }), { layout: 'bug', nick: t => t.short || t.name, factors: fx, factorsTitle: 'How they match up this season', noteExtra: esc(extra) }) + '</div></div>';
  }
  if (last) {
    const me = HW.teamAbbr(L, tid), op = HW.teamAbbr(L, last.opp), won = String(last.res).charAt(0) === 'W';
    const ttl = isNum(last.pts) && isNum(last.opp_pts) ? (won ? me + ' ' + last.pts + ', ' + op + ' ' + last.opp_pts : op + ' ' + last.opp_pts + ', ' + me + ' ' + last.pts) : (last.home ? 'v ' : 'at ') + HW.teamName(L, last.opp);
    let pre = '';
    if (isNum(last.p_win)) {
      const fav = last.p_win >= 0.5;
      pre = 'We gave the ' + HW.teamShort(L, tid) + ' a ' + U.pct(last.p_win) + ' chance before the game' + (Math.abs(last.p_win - 0.5) < 0.05 ? ': a coin flip, ' + (won ? 'and they won.' : 'and they lost.') : fav === won ? ': the favourite won.' : ': ' + (won ? 'an upset win.' : 'an upset loss.'));
    }
    const href = last.game ? HW.gameHref(L, last.game, S) : null;
    /* alone (no next game: the offseason, a past season) the card runs full width, the box beside the race */
    const body = nxt ? '<div id="tp-box"></div>' + (pre ? QK.explain(esc(pre)) : '') + '<div id="tp-race"></div>'
      : '<div class="qk-g2"><div><div id="tp-box"></div>' + (pre ? QK.explain(esc(pre)) : '') + '</div><div id="tp-race"></div></div>';
    h += '<div>' + QK.sectionHead({ kicker: 'Last game', title: '<span id="tp-last-t">' + esc(ttl) + '</span>', html: true, sub: esc(HW.fmtDate(last.date, { year: false }) + (last.home ? ' · at home' : ' · away')),
      actions: href ? '<a class="qk-more" href="' + esc(href) + '">The game centre</a>' : '' }) +
      '<article class="qk-card"><div class="qk-card-body">' + body + '</div></article></div>';
  }
  return h.replace('<div class="qk-g2">', nxt && last ? '<div class="qk-g2">' : '<div>') + '</div></section>';
}
/* A live next game: the bug again with the teams going in (the game file's tape_pre), when the file has it. */
function fillNext(el, L, S, nxt, season) {
  if (!nxt || U.status(nxt) !== 'live' || !el.querySelector('#tp-next-bug')) return;
  HW.gameCentre.loadGame(L, S, nxt.id).then(res => {
    const gi = U.goingIn(res && U.ok(res.d) ? res.d : null), box = el.querySelector('#tp-next-bug');
    if (!gi || !box || !U.alive(box)) return;
    box.innerHTML = QK.previewCard(U.game(nxt, L, { records: U.records(season) }), { layout: 'bug', nick: t => t.short || t.name, factors: U.clubRows(gi.away, gi.home), factorsTitle: U.goingTitle(gi) });
  });
}
function fillLast(el, L, S, tid, last) {
  if (!last || !last.game || !el.querySelector('#tp-box')) return;
  HW.gameCentre.loadGame(L, S, last.game).then(res => {
    if (!res || !U.ok(res.d) || !U.alive(el)) return;
    const d = res.d, H = String(d.home), A = String(d.away);
    const ln = d.line || {}, la = ln.away || [], lh = ln.home || [];
    if (la.length && lh.length && el.querySelector('#tp-box')) {
      const n = Math.max(la.length, lh.length);
      const ql = i => (i < 4 ? 'Q' + (i + 1) : (n > 5 ? 'OT' + (i - 3) : 'OT'));
      const sum = a => a.reduce((s, x) => s + (isNum(x) ? x : 0), 0);
      const row = (t, a) => '<tr' + (t === tid ? ' class="hl"' : '') + '><td>' + QK.teamMark(U.team(L, t), 'sm') + '</td>' + a.map(x => '<td class="num">' + (isNum(x) ? x : '–') + '</td>').join('') + '<td class="num"><b>' + sum(a) + '</b></td></tr>';
      el.querySelector('#tp-box').innerHTML = '<div class="qk-table-wrap"><table class="qk-table dense"><thead><tr><th>Team</th>' + la.map((_, i) => '<th class="num">' + ql(i) + '</th>').join('') + '<th class="num">Total</th></tr></thead><tbody>' + row(A, la) + row(H, lh) + '</tbody></table></div>';
    }
    const wp = ((d.wp || {}).model || []).filter(x => isNum(x[0]) && isNum(x[1]));
    const node = el.querySelector('#tp-race');
    if (wp.length > 4 && node) {
      const PS = L === 'wnba' ? 600 : 720, tMax = Math.max(wp[wp.length - 1][0], 4 * PS);
      const per = []; for (let t = PS; t < tMax; t += t < 4 * PS ? PS : 300) per.push(t);
      const hc = U.pair(L, H, A);
      node.innerHTML = U.chart('tp-race-c', 240, 'Our win chance through the last game');
      QKC.winProb('#tp-race-c', { t: wp.map(x => x[0]), p: wp.map(x => x[1]), step: true, tMin: 0, tMax: tMax, interval: PS, periods: per,
        home: { name: HW.teamName(L, H), abbr: HW.teamAbbr(L, H), colour: hc[0] }, away: { name: HW.teamName(L, A), abbr: HW.teamAbbr(L, A), colour: hc[1] },
        tFmt: x => (x < 4 * PS ? 'Q' + (Math.round(x / PS) + 1) : ''), tLabel: x => (x < 4 * PS ? 'Q' + (Math.floor(x / PS) + 1) : 'OT') + ' · ' + Math.floor((x % PS) / 60) + ' min in',
        tName: 'Game time (quarters)', yName: HW.teamAbbr(L, H) + ' win chance (ours)' });
    }
  });
}

function render(el, params) {
  const L = U.L(params), S = U.S(params), tid = String(params.id || '');
  const isCur = U.isCur(L, S);
  const tab = U.tab(params, ['overview', 'detail'], 'overview');
  el.innerHTML = QK.skeleton('lines', 6);
  const opt = (cond, p) => (cond ? HW.load(p) : Promise.resolve(null));
  return Promise.all([HW.load(HW.path('season.json', L, S)), HW.load(HW.path('teams.json', L, S)), HW.load(HW.path('players.json', L, S)),
    opt(isCur, HW.path('needs/' + tid + '.json', L, S)), opt(isCur, HW.path('valuation.json', L, S)), opt(isCur, HW.path('transactions.json', L, S)),
    opt(isCur, HW.path('deals.json', L, S)), HW.load(HW.path('schedule.json', L, S)), isCur ? U.movement(L) : Promise.resolve(null)]).then(a => {
    if (!U.alive(el)) return;
    const season = U.ok(a[0]) ? a[0] : null, teams = U.ok(a[1]) ? a[1] : null, cat = U.ok(a[2]) ? a[2] : null;
    const mv = a[8] || null;
    const needs = U.ok(a[3]) ? a[3] : null, val = U.ok(a[4]) ? a[4] : null, tx = U.ok(a[5]) ? a[5] : null, deals = U.ok(a[6]) ? a[6] : null, sched = U.ok(a[7]) ? a[7] : null;
    const T = (teams && teams.teams && teams.teams[tid]) || {};
    const r = ((season && season.ratings) || {})[tid] || {};
    const sim = HW.simTeams(season)[tid] || {};
    const s = standRow(season, tid);
    const info = HW.team(L, tid);
    const name = T.name || HW.teamName(L, tid);
    const col = U.tcol(L, tid);
    document.title = name + ' · ' + HW.leagueName(L) + ' · The Quant Hardwood';
    const open = isNum(sim.w_p05) && sim.w_p95 > sim.w_p05;
    const nTeams = Object.keys((season && season.ratings) || {}).length;
    /* the league block (season.json): the team set's percentiles against the league, oriented so 100 is best */
    const lb = season && (season.league_block || (season.league && typeof season.league === 'object' ? season.league : null));
    const lbT = lb && lb.teams ? lb.teams[tid] || null : null;
    const prof = lb && lb.profile ? lb.profile.metrics || [] : [];
    const pcNet = lbT && lbT.pct && isNum(lbT.pct.model_net) ? lbT.pct.model_net : null;
    const nSims = Number(((season && season.sim) || {}).n_sims || 20000);
    const cur0 = sim.current || {}, nGames = isNum(cur0.remaining) && isNum(cur0.w) && isNum(cur0.l) ? cur0.w + cur0.l + cur0.remaining : null;
    const tiles = [{ label: 'Record', value: isNum(s.w) ? HW.record(s.w, s.l) : '—', sub: isNum(s.seed) && (s.w || s.l) ? HW.ordinal(s.seed) + ' in the ' + (s.conf || 'league') : (isCur ? 'no games yet' : '') }];
    if (isCur && isNum(sim.p_playoffs)) tiles.push({ label: 'Our playoff chance', value: U.pct(sim.p_playoffs), signal: true, sub: 'from ' + nSims.toLocaleString('en-GB') + ' simulated seasons', tip: 'Our chance of a playoff place (play-in excluded)' });
    if (isCur && isNum(sim.p_title)) tiles.push({ label: 'Our title chance', value: U.pct(sim.p_title), signal: true, sub: isNum(sim.p_conf) ? 'conference ' + U.pct(sim.p_conf) : '' });
    /* projected wins with the simulation's own 90% range as the likely-range bar, on the scale of the full season */
    if (open) tiles.push({ label: 'Projected wins', value: U.f(sim.exp_w, 1), sub: '9 seasons in 10: ' + U.f(sim.w_p05, 0) + '–' + U.f(sim.w_p95, 0) + (nGames ? ' of ' + nGames : ''), tip: 'Mean of the simulated seasons; the bar is the range that holds nine seasons in ten' + (nGames ? ', drawn on the scale of the ' + nGames + '-game season' : ''),
      range: { lo: sim.w_p05, hi: sim.w_p95, mid: sim.exp_w, min: nGames ? 0 : undefined, max: nGames || undefined, label: 'Projected wins, nine seasons in ten', fmt: v => U.f(v, 0) } });
    if (isNum(r.net)) tiles.push({ label: 'Net rating', value: U.signed(r.net, 1), pctl: pcNet, sub: 'per 100 possessions' + (isNum(r.se_net) ? ' ± ' + U.f(r.se_net, 1) : '') + (isNum(r.rank) ? ' · ' + HW.ordinal(r.rank) + ' of ' + nTeams : ''), tip: 'Our opponent-adjusted net rating (Kalman filter); ± one standard error; the chip is its percentile among the league’s teams' });
    /* a past season (no simulation): the two halves of the rating fill the strip, with their percentiles */
    const pcOf = k => (lbT && lbT.pct && isNum(lbT.pct[k]) ? lbT.pct[k] : null);
    if (tiles.length < 5 && isNum(r.off)) tiles.push({ label: 'Offence', value: U.f(r.off, 1), pctl: pcOf('model_off'), sub: 'points scored per 100, adjusted' });
    if (tiles.length < 5 && isNum(r.def)) tiles.push({ label: 'Defence', value: U.f(r.def, 1), pctl: pcOf('model_def'), sub: 'points allowed per 100 (lower is better)' });
    const path = ((season && season.rating_paths) || {})[tid] || [];
    const log = (T.log || []).slice().sort((x, y) => String(x.date).localeCompare(String(y.date)));
    /* every game the team has finished this season, playoffs included (teams.json's log is the regular season only),
       from the season's schedule.json: the last game and the form come from it; the log is the fallback */
    const played = sched ? (sched.games || []).filter(g => (String(g.home) === tid || String(g.away) === tid) && HW.gameState(g) === 'post' && g.stype !== 'pre' && isNum(g.hs) && isNum(g.as))
      .sort((x, y) => String(x.date).localeCompare(String(y.date))).map(g => {
        const home = String(g.home) === tid, pts = home ? g.hs : g.as, opp = home ? g.as : g.hs, ph = (g.model || {}).p_home;
        return { game: g.id, date: g.date, opp: home ? g.away : g.home, home: home, res: pts > opp ? 'W' : 'L', pts: pts, opp_pts: opp, p_win: isNum(ph) ? (home ? ph : 1 - ph) : null };
      }) : [];
    const games = played.length ? played : log;
    /* form: the last ten results, oldest first, on a black chip in the hero (the dots keep their contrast) */
    /* the streak from the same games as the form (playoffs included), so the two never disagree */
    let streak = s.streak || '';
    if (played.length) { const lastR = played[played.length - 1].res; let k = 0; for (let i = played.length - 1; i >= 0 && played[i].res === lastR; i--) k++; streak = lastR + k; }
    const f10 = games.slice(-10).map(g => String(g.res || '').charAt(0).toUpperCase()).filter(x => x === 'W' || x === 'L');
    const formTag = f10.length ? '<span class="hw-ph-form" tabindex="0" data-tip="The last ' + f10.length + ' results, oldest first">Last ' + f10.length + ' ' + QK.formDots(f10, f10.length) + '<b class="num">' + f10.filter(x => x === 'W').length + '–' + f10.filter(x => x === 'L').length + '</b></span>' : '';
    /* v4: the full-bleed team-colour hero (the alternate colour on the diagonal, the abbreviation outlined) with the
       black strip of five numbers: the record, our chances, projected wins and the rating; then "The short version" */
    let h = '<nav class="hw-crumb" aria-label="Breadcrumb"><a href="' + esc(HW.href(L, 'teams', S)) + '">' + esc(HW.leagueName(L)) + ' teams</a><span aria-hidden="true">›</span>' + esc(name) + '</nav>' +
      QK.playerHeader({ name: name, split: false, kicker: U.kicker(L, S), face: HW.teamAbbr(L, tid), team: { name: [info.conference || s.conf, info.division].filter(Boolean).join(' · ') || HW.leagueName(L), abbr: HW.teamAbbr(L, tid), colour: HW.teamColourRaw(L, tid), alt: HW.teamAlt(L, tid) },
        meta: [isNum(r.off) ? ['Offence', U.f(r.off, 1) + ' per 100'] : null, isNum(r.def) ? ['Defence', U.f(r.def, 1) + ' allowed'] : null, isNum(r.pace) ? ['Pace', U.f(r.pace, 1)] : null, streak ? ['Streak', streak] : null],
        tags: formTag ? [formTag] : [], strip: tiles.slice(0, 5), short: shortTeam(L, tid, isCur, s, sim, r, lbT, prof, nTeams),
        /* round 12 (My Teams): follow the team from the hero; it then leads Home and this site's overview */
        follow: U.followItem(L, tid) });
    const base = HW.teamHref(L, tid, S);
    h += '<div style="margin-top:var(--sp-4)"></div>' + U.tabsHTML([{ key: 'overview', label: 'Overview', href: base }, { key: 'detail', label: 'Shots, lineups and the full catalogue', href: base + (base.indexOf('?') >= 0 ? '&' : '?') + 'tab=detail' }], tab);
    if (tab === 'detail') {
      el.innerHTML = h + '<div class="hw-sub"></div>';
      const sub = el.querySelector('.hw-sub'), out = U.legacy('team', sub, params, null, { embed: 'detail' });
      U.foldTables(sub, 2, out);
      return out;
    }
    if (!season && !teams) { el.innerHTML = h + U.empty('Not in this season', name + ' has no data for ' + HW.seasonLabel(L, S) + '.'); return; }
    /* "How sure are we?": what the playoff chance means, and the sample behind the rating (its standard error) */
    const gp0 = (s.w || 0) + (s.l || 0);
    const sure = [];
    if (isCur && isNum(sim.p_playoffs)) sure.push('<b>' + U.pct(sim.p_playoffs) + '</b> to make the playoffs means the ' + esc(HW.teamShort(L, tid)) + ' made it in ' +
      freqWords(sim.p_playoffs) + ' of our ' + nSims.toLocaleString('en-GB') + ' simulated seasons.');
    const over0 = !isCur || HW.phase(L) === 'offseason';
    if (isNum(r.net)) sure.push((gp0 ? (over0 ? 'Over ' + gp0 + ' game' + (gp0 === 1 ? '' : 's') : esc(NUMW[gp0] || String(gp0)) + ' game' + (gp0 === 1 ? '' : 's') + ' in') + ', our' : 'Before the first game our') + ' net rating is <b>' + U.signed(r.net, 1) + (isNum(r.se_net) ? ' ± ' + U.f(r.se_net, 1) : '') + '</b> points per 100 possessions against an average team' + (isNum(r.se_net) ? ' (one standard error)' : '') + '.' +
      (open ? ' That is why the projected wins still run from ' + U.f(sim.w_p05, 0) + ' to ' + U.f(sim.w_p95, 0) + ' in nine seasons out of ten.' : ''));
    if (sure.length) h += '<div style="margin-top:var(--sp-3)">' + QK.explain(sure.join(' '), { title: 'How sure are we?' }) + '</div>';
    h += '%NEXT_LAST%';
    h += '<div class="qk-grid hw-sec">';
    const oddsRows = [['Playoffs', sim.p_playoffs], ['Top-six seed', sim.p_top6], ['Conference', sim.p_conf], ['Title', sim.p_title]].filter(x => isNum(x[1]) && x[1] > 0);
    const chancesOn = !!(oddsRows.length && isCur);
    /* the rating path runs full width when there are no season chances beside it (the offseason, a past season) */
    if (path.length > 1) h += U.card2('Net rating through the season', 'Our rating per 100 possessions after each game (Kalman filter), shaded ±1 standard error' + (log.length ? '; dots are regular-season results (green won, red lost)' : ''), U.chart('tp-path', 300, 'Net rating through the season'), { cls: chancesOn ? 'qk-span-8' : 'qk-span-12' });
    if (chancesOn) h += U.card2('Season chances', 'Our chances from the season simulation',
      QK.chances(oddsRows.map(x => ({ label: x[0], p: x[1], color: HW.teamColourRaw(L, tid) })), { sort: false, max: 1, key: false }) +
      ((sim.seed_dist || []).length && open ? U.chart('tp-seed', 190, 'Chance of each final seed') : ''), { cls: path.length > 1 ? 'qk-span-4' : 'qk-span-12' });
    h += '</div>';
    // strengths and weaknesses on the spec's team set, chips and the race (docs/_design/league.js, from season.json "league")
    const lo = HW.leagueOpts && season ? HW.leagueOpts(season, L, S) : null;
    h += '<div id="tp-top"></div>';
    if (lo) h += '<div id="tp-league"></div>';
    // strengths and needs
    if (needs && needs.grades) {
      h += '<section class="qk-section">' + U.head({ kicker: 'Roster construction', title: 'Strengths and needs', sub: 'Each position group and unit graded against the league on projected value (WAR over a full season).' }) + '<div class="qk-grid">' +
        U.card2('Grades', '', '<div id="tp-grades"></div>', { cls: 'qk-span-5', flush: true }) +
        U.card2('Strengths and needs', 'Where the roster is strong and where it is thin', '<div id="tp-targets"></div>', { cls: 'qk-span-7', flush: true }) + '</div></section>';
    }
    const mvT = mv ? (mv.m.teams || {})[tid] : null;
    if (mv && mvT) {
      const ST = { contending: 'contending', 'in the middle': 'in the middle', rebuilding: 'rebuilding' };
      const cuts = mv.m.status_cuts || {};
      const tl = [];
      if (mv.pub.next && isNum(mvT.exp_departures)) tl.push({ label: 'Expected departures', value: U.f(mvT.exp_departures, 1), signal: true, sub: U.mvHorizon(mv), tip: 'The sum of every rostered player\'s chance of leaving' });
      const most = mv.pub.next ? (mv.m.players || []).map(r => mv.by[String(r[0])]).filter(x => x && String(x.team) === tid && isNum(x.p_next)).sort((x, y) => y.p_next - x.p_next)[0] : null;
      if (most) tl.push({ label: 'Most likely to move', value: most.name, text: true, href: HW.playerHref(L, most.pid, S), sub: U.pctMv(most.p_next) + (most.why ? ' · ' + most.why : '') });
      const lines = (mv.pub.next ? '' : U.mvBaseLine(mv, 'next')) + (mv.pub.deadline ? '' : U.mvBaseLine(mv, 'deadline'));
      h += '<section class="qk-section">' + U.head({ kicker: 'Who moves next', title: 'Who might leave', sub: 'Our chance that each player has left ' + esc(U.mvHorizon(mv)) + ', how, and the team\'s expected departures. No contract data is used: see the Model page.',
        actions: mvT.status ? '<span data-tip="' + esc('From our standings: contending above ' + U.pct(cuts.contending) + ' projected win %, rebuilding below ' + U.pct(cuts.rebuilding)) + '" tabindex="0">' + QK.tag(ST[mvT.status] || mvT.status, mvT.status === 'contending' ? 'signal' : '') + '</span>' : '' }) +
        (tl.length ? '<div class="hw-kpis">' + QK.stats(tl) + '</div>' : '') + lines + '</section>';
    }
    h += '<section class="qk-section">' + U.head({ kicker: 'Players', title: isCur ? 'Who’s on the roster' : 'Who played', sub: isCur && val ? 'From the latest rosters and injury report (rebuilt every run). HPM is our projected rest-of-season impact per 100; WAR the projected wins above replacement.' : 'Everyone who played, by minutes.' }) +
      '<div class="qk-card"><div id="tp-roster"></div></div></section>';
    // schedule + moves
    const upcoming = sched ? (sched.games || []).filter(g => (String(g.home) === tid || String(g.away) === tid) && HW.gameState(g) !== 'post' && U.fresh(g)).sort((x, y) => String(x.date).localeCompare(String(y.date))).slice(0, 8) : [];
    const recent = games.slice(-8).reverse();
    const txRows = tx ? U.rowsOf(tx).filter(x => String(x.team) === tid) : [];
    const seen = {}, txs = txRows.filter(x => { const k = x.date + x.text; if (seen[k]) return false; seen[k] = 1; return true; }).sort((x, y) => String(y.date).localeCompare(String(x.date))).slice(0, 10);
    const dl = deals && deals.teams ? deals.teams[tid] : null;
    /* v4 (as the Rink): what to watch next (the scoreboard bug) beside the last game, straight under the hero */
    h = h.replace('%NEXT_LAST%', nextAndLast(L, S, tid, upcoming, games, season));
    h += '<div class="qk-grid hw-sec">' + U.card2('Schedule', upcoming.length ? 'Next games with our win chance' : 'Results', '<div id="tp-sched"></div>', { cls: 'qk-span-6', flush: true });
    if (txs.length || dl) h += U.card2('Moves', dl ? dl.n + ' rated trade' + (dl.n === 1 ? '' : 's') + ' in 12 months · net ' + U.signed(dl.net_now, 1) + ' WAR in today’s view' : 'Transactions in the last 12 months',
      '<div>' + txs.map(x => '<div class="hw-tx"><span class="d">' + esc(HW.fmtDate(x.date, { year: 'auto', weekday: false })) + '</span><span>' + esc(x.text) + '</span></div>').join('') + '</div>',
      { cls: 'qk-span-6', flush: true, foot: U.link(HW.href(L, 'value') + '?tab=moves&team=' + encodeURIComponent(tid), 'Trade grades and the full feed') });
    h += '</div>';
    el.innerHTML = h;
    if (lo) QKL.team(document.getElementById('tp-league'), lo, tid);
    if (window.QKL && QKL.performers) topPerformers(document.getElementById('tp-top'), L, S, tid, cat);
    fillLast(el, L, S, tid, games.length ? games[games.length - 1] : null);
    fillNext(el, L, S, upcoming[0] || null, season);

    // rating path with the se band and results
    if (document.getElementById('tp-path')) {
      const byGame = {}; log.forEach(g => { byGame[g.game] = g; });
      QKC.mount('#tp-path', Tk => {
        const xs = path.map(p => p.date);
        const lo = path.map(p => Math.round((p.net - (p.se || 0)) * 10) / 10), band = path.map(p => Math.round(2 * (p.se || 0) * 10) / 10);
        const res = path.map((p, i) => { const g = byGame[p.game]; return g ? { value: [i, p.net], res: g, itemStyle: { color: String(g.res).charAt(0) === 'W' ? Tk.up : Tk.down } } : null; }).filter(Boolean);
        return {
          grid: { left: 8, right: 16, top: 32, bottom: 30, containLabel: true },
          xAxis: QKC.axis(Tk, { type: 'category', data: xs.map(d => HW.fmtDate(d, { year: false, weekday: false })), split: false, line: true, boundaryGap: false, name: 'Date', nameLocation: 'middle', nameGap: 26 }),
          yAxis: QKC.axis(Tk, { fmt: v => U.signed(v, 0), scale: true, name: 'Net rating (points per 100 possessions)', nameAlign: 'left' }),
          tooltip: QKC.tooltip(Tk, { trigger: 'axis', formatter: ps => { const i = ps[0].dataIndex, p = path[i], g = byGame[p.game];
            return '<div style="color:' + Tk.ink3 + ';font-size:11px">' + esc(HW.fmtDate(p.date, { year: false })) + '</div>' + QKC.tipRow(col, 'Net', U.signed(p.net, 1) + ' ± ' + U.f(p.se, 1)) +
              (g ? '<div style="margin-top:4px">' + esc((g.home ? 'v ' : '@ ') + HW.teamAbbr(L, g.opp) + ' ' + (g.res || '') + ' ' + g.pts + '-' + g.opp_pts) + '</div>' : ''); } }),
          series: [
            { type: 'line', stack: 'b', data: lo, showSymbol: false, silent: true, lineStyle: { opacity: 0 }, tooltip: { show: false } },
            { type: 'line', stack: 'b', data: band, showSymbol: false, silent: true, lineStyle: { opacity: 0 }, areaStyle: { color: QKC.hexA(col, 0.18) }, tooltip: { show: false } },
            { type: 'line', data: path.map(p => p.net), showSymbol: false, lineStyle: { width: 2.2, color: col }, itemStyle: { color: col },
              markLine: { silent: true, symbol: 'none', lineStyle: { color: Tk.axis, type: [3, 3] }, label: { show: false }, data: [{ yAxis: 0 }] } },
            { type: 'scatter', data: res, symbolSize: 6, z: 5 }
          ]
        };
      }, { label: 'Net rating over time' });
    }
    if (document.getElementById('tp-seed')) {
      const sd = sim.seed_dist;
      QKC.bar('#tp-seed', { cats: sd.map((v, i) => String(i + 1)), series: [{ name: 'Chance', data: sd.map(v => Math.round(v * 1000) / 1000) }], colors: sd.map(() => col), fmt: v => U.pct(v), valName: 'Our chance', catName: 'Final seed' });
    }
    if (needs && needs.grades) {
      QK.table(document.getElementById('tp-grades'), { dense: true, rows: needs.grades, columns: [
        { key: 'label', label: 'Area' }, { key: 'grade', label: 'Grade', fmt: v => U.grade(v) }, { key: 'value', label: 'WAR', num: true, fmt: v => U.f(v, 1), tip: 'Projected WAR over a full season' },
        { key: 'rank', label: 'Rank', num: true, fmt: (v, g) => HW.ordinal(v) + ' of ' + g.n }] });
      const strong = (needs.strengths || []).map(x => '<div class="hw-target"><div class="hw-flex">' + U.grade(x.grade) + '<b>' + esc(x.label) + '</b><span class="qk-badge" style="margin-left:auto">strength</span></div><div class="why">' + esc(x.evidence || '') + '</div></div>').join('');
      /* needs keep their grade and evidence; the players other teams could give up are not listed (no signings or
         trade targets on the team page) */
      const weak = (needs.weaknesses || []).map(w => '<div class="hw-target"><div class="hw-flex">' + U.grade(w.grade) + '<b>' + esc(w.label) + '</b><span class="qk-badge" style="margin-left:auto">need</span></div><div class="why">' + esc(w.evidence || '') + '</div></div>').join('');
      document.getElementById('tp-targets').innerHTML = strong + weak || U.empty('No grades', '');
    }
    // roster
    const P = (cat && cat.players) || {};
    const rosterNode = document.getElementById('tp-roster');
    const vrows = U.rowsOf(val).filter(x => String(x.team) === tid);
    if (isCur && vrows.length) {
      const rows = vrows.map(x => { const p = P[x.id] || {}, v = p.values || {}; return Object.assign({}, x, { gp: p.gp, ppg: v.pts_g, rpg: v.reb_g, apg: v.ast_g }); }).sort((x, y) => (y.mpg || 0) - (x.mpg || 0));
      const anyGp = rows.some(x => isNum(x.gp));
      const mvOn = mv && mv.pub.next;
      rows.forEach(x => { const mr = mvOn ? mv.by[String(x.id)] : null; x.p_next = mr ? mr.p_next : null; x.p_dl = mr ? mr.p_dl : null; x.mr = mr;
        x.sub = [x.pos, U.ROLE1[x.role] || '', isNum(x.age) ? String(Math.floor(x.age)) : ''].filter(Boolean).join(' · ') + (x.inj ? ' · ' + String(x.inj).split(' ')[0] : '') + (mr && mr.why ? ' · ' + mr.why : ''); });
      if (mvOn) rosterNode.insertAdjacentHTML('beforebegin', '<div class="hw-mvline" style="padding:10px 16px 0"><span class="qk-muted">Chance of moving, split by how:</span>' + U.mvKeys(mv) + '</div>');
      QK.leaderboard(rosterNode, { dense: true, rows: rows, sort: mvOn ? { key: 'p_next', dir: 'desc' } : undefined, rowHref: x => HW.playerHref(L, x.id, S), columns: [
        { key: 'name', label: 'Player', type: 'entity', sub: 'sub', href: x => HW.playerHref(L, x.id, S) },
        { key: 'mpg', label: 'Proj min', num: true, fmt: v => U.f(v, 1), tip: 'Projected minutes a game' }]
        .concat(anyGp ? [{ key: 'gp', label: 'GP', num: true }, { key: 'ppg', label: 'PPG', num: true, fmt: v => U.f(v, 1) }, { key: 'rpg', label: 'RPG', num: true, fmt: v => U.f(v, 1) }, { key: 'apg', label: 'APG', num: true, fmt: v => U.f(v, 1) }] : [])
        .concat([{ key: 'rate', label: 'HPM', num: true, fmt: v => U.sgnHTML(v, 1), tip: 'Our projected rest-of-season impact per 100 possessions' },
          { key: 'w0', label: 'WAR', type: 'bar', fmt: v => U.f(v, 1), tip: 'Projected wins above replacement, rest of season' },
          { key: 'v', label: '4-yr value', num: true, fmt: v => U.f(v, 1), tip: 'Discounted WAR over four seasons' }])
        .concat(mvOn ? [{ key: 'p_next', label: 'Chance of moving', num: true, fmt: (v, x) => U.mvBar(mv, x.mr), tip: 'Our chance the player has left ' + U.mvHorizon(mv) + '. ' + ((mv.m.notes || [])[0] || '') }] : [])
        .concat(mvOn && mv.pub.deadline ? [{ key: 'p_dl', label: 'Deadline', num: true, fmt: v => U.pctMv(v), tip: 'Our chance the player is ' + (mv.m.deadline_label || 'traded or claimed') + ' before the trade deadline (' + HW.fmtDate(String((mv.m.horizons || {}).deadline || ''), { weekday: false }) + ')' }] : []) });
    } else {
      const ro = (T.roster || []).slice().sort((x, y) => (y.min || 0) - (x.min || 0)).map(x => Object.assign({}, x, { mpg: x.mpg || (x.gp ? x.min / x.gp : null) }));
      if (!ro.length) rosterNode.innerHTML = U.empty('No roster yet', 'The roster appears once the team plays.');
      else QK.table(rosterNode, { dense: true, rows: ro, columns: [
        { key: 'name', label: 'Player', sticky: true, fmt: (v, x) => U.playerEnt(L, x.id, x.name, null, null, S) }, { key: 'pos', label: 'Pos', fmt: v => U.pos(v) },
        { key: 'gp', label: 'GP', num: true }, { key: 'mpg', label: 'MPG', num: true, fmt: v => U.f(v, 1) },
        { key: 'hpm', label: 'HPM', num: true, fmt: v => U.sgnHTML(v, 1) }, { key: 'o', label: 'O', num: true, fmt: v => U.signed(v, 1) }, { key: 'd', label: 'D', num: true, fmt: v => U.signed(v, 1) }] });
    }
    // schedule
    const sn = document.getElementById('tp-sched');
    const lines = [];
    upcoming.forEach(g => { const home = String(g.home) === tid, opp = home ? g.away : g.home, p = (g.model || {}).p_home; const pt = isNum(p) ? (home ? p : 1 - p) : null;
      lines.push('<li><span class="n" style="width:auto">' + esc(HW.fmtDate(g.date, { year: false })) + '</span><a class="hw-ent" href="' + esc(HW.gameHref(L, g.id, S)) + '"><span class="nm">' + (home ? 'v ' : '@ ') + esc(HW.teamName(L, opp)) + '</span></a>' + (g === upcoming[0] ? avNote(g, home) : '') + '<span class="v">' + (pt === null ? HW.fmtTime(g.date) : U.pct(pt) + ' win') + '</span></li>'); });
    if (recent.length) lines.push('<li class="hw-quiet" style="padding-top:12px">Recent results</li>');
    recent.forEach(g => lines.push('<li><span class="n" style="width:auto">' + esc(HW.fmtDate(g.date, { year: false })) + '</span><a class="hw-ent" href="' + esc(HW.gameHref(L, g.game, S)) + '"><span class="nm">' + (g.home ? 'v ' : '@ ') + esc(HW.teamName(L, g.opp)) + '</span></a>' +
      '<span class="v ' + (String(g.res).charAt(0) === 'W' ? 'pos' : 'neg') + '">' + esc((g.res || '') + ' ' + g.pts + '-' + g.opp_pts) + '</span></li>'));
    sn.innerHTML = lines.length ? '<ul class="hw-list">' + lines.join('') + '</ul>' : U.empty('No games', 'Nothing scheduled yet.');
    HW.setMeta('');
  });
}

HW.page('team', render);
})(window.HW);
