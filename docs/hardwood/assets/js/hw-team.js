/* The Quant Hardwood — the team page (#/<L>/team/<tid>), on kit v4 "Broadcast".
 *
 * Overview tab: the full-bleed team-colour hero with the black strip of numbers (record, our playoff and title
 * chances first, projected wins with the simulation's 90% range, the rating); the net rating through the
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

function render(el, params) {
  const L = U.L(params), S = U.S(params), tid = String(params.id || '');
  const isCur = U.isCur(L, S);
  const tab = U.tab(params, ['overview', 'detail'], 'overview');
  el.innerHTML = QK.skeleton('lines', 6);
  const opt = (cond, p) => (cond ? HW.load(p) : Promise.resolve(null));
  return Promise.all([HW.load(HW.path('season.json', L, S)), HW.load(HW.path('teams.json', L, S)), HW.load(HW.path('players.json', L, S)),
    opt(isCur, HW.path('needs/' + tid + '.json', L, S)), opt(isCur, HW.path('valuation.json', L, S)), opt(isCur, HW.path('transactions.json', L, S)),
    opt(isCur, HW.path('deals.json', L, S)), opt(isCur, HW.path('schedule.json', L, S)), isCur ? U.movement(L) : Promise.resolve(null)]).then(a => {
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
    const stats = [
      { label: 'Record', value: isNum(s.w) ? HW.record(s.w, s.l) : '—', sub: isNum(s.seed) && (s.w || s.l) ? HW.ordinal(s.seed) + ' in the ' + (s.conf || 'league') : (isCur ? 'no games yet' : '') },
      { label: 'Net rating', value: U.signed(r.net, 1), sub: isNum(r.rank) ? HW.ordinal(r.rank) + ' of ' + Object.keys((season && season.ratings) || {}).length : '' }
    ];
    if (open) stats.push({ label: 'Projected wins', value: U.f(sim.exp_w, 1), sub: U.f(sim.w_p05, 0) + '–' + U.f(sim.w_p95, 0) });
    const tiles = [];
    if (isCur && isNum(sim.p_playoffs)) tiles.push({ label: 'Our playoff chance', value: U.pct(sim.p_playoffs), signal: true, sub: 'from ' + Number(((season.sim || {}).n_sims) || 20000).toLocaleString('en-GB') + ' simulated seasons', tip: 'Our chance of a playoff place (play-in excluded)' });
    if (isCur && isNum(sim.p_title)) tiles.push({ label: 'Our title chance', value: U.pct(sim.p_title), signal: true, sub: isNum(sim.p_conf) ? 'conference ' + U.pct(sim.p_conf) : '' });
    if (open) tiles.push({ label: 'Projected wins', value: U.f(sim.exp_w, 1), sub: '90% range ' + U.f(sim.w_p05, 0) + ' to ' + U.f(sim.w_p95, 0), tip: 'Mean of the simulated seasons; the range holds nine seasons in ten' });
    if (isNum(r.net)) tiles.push({ label: 'Net rating', value: U.signed(r.net, 1), sub: 'per 100 possessions' + (isNum(r.se_net) ? ' ± ' + U.f(r.se_net, 1) : '') + (isNum(r.rank) ? ' · ' + HW.ordinal(r.rank) : ''), tip: 'Our opponent-adjusted net rating (Kalman filter); ± one standard error' });
    if (isNum(r.off)) tiles.push({ label: 'Offence · defence', value: U.f(r.off, 1) + ' · ' + U.f(r.def, 1), sub: 'points scored and allowed per 100' });
    /* v4: the full-bleed team-colour hero (the alternate colour on the diagonal, the abbreviation outlined) with the
       black strip of five numbers: the record, our chances, projected wins and the rating */
    let h = '<nav class="hw-crumb" aria-label="Breadcrumb"><a href="' + esc(HW.href(L, 'teams', S)) + '">' + esc(HW.leagueName(L)) + ' teams</a><span aria-hidden="true">›</span>' + esc(name) + '</nav>' +
      QK.playerHeader({ name: name, split: false, kicker: U.kicker(L, S), face: HW.teamAbbr(L, tid), team: { name: [info.conference || s.conf, info.division].filter(Boolean).join(' · ') || HW.leagueName(L), abbr: HW.teamAbbr(L, tid), colour: HW.teamColourRaw(L, tid), alt: HW.teamAlt(L, tid) },
        meta: [isNum(r.off) ? ['Offence', U.f(r.off, 1) + ' per 100'] : null, isNum(r.def) ? ['Defence', U.f(r.def, 1) + ' allowed'] : null, isNum(r.pace) ? ['Pace', U.f(r.pace, 1)] : null], strip: [stats[0]].concat(tiles.length ? tiles.filter(t => t.label !== 'Offence · defence') : stats.slice(1)).slice(0, 5) });
    const base = HW.teamHref(L, tid, S);
    h += '<div style="margin-top:var(--sp-4)"></div>' + U.tabsHTML([{ key: 'overview', label: 'Overview', href: base }, { key: 'detail', label: 'Shots, lineups and the full catalogue', href: base + (base.indexOf('?') >= 0 ? '&' : '?') + 'tab=detail' }], tab);
    if (tab === 'detail') {
      el.innerHTML = h + '<div class="hw-sub"></div>';
      return U.legacy('team', el.querySelector('.hw-sub'), params, null, { embed: 'detail' });
    }
    if (!season && !teams) { el.innerHTML = h + U.empty('Not in this season', name + ' has no data for ' + HW.seasonLabel(L, S) + '.'); return; }
    const path = ((season && season.rating_paths) || {})[tid] || [];
    const log = (T.log || []).slice().sort((x, y) => String(x.date).localeCompare(String(y.date)));
    if (isCur && isNum(sim.p_playoffs)) h += '<div style="margin-top:var(--sp-3)">' + QK.note('<b>' + U.pct(sim.p_playoffs) + '</b> to make the playoffs means ' + esc(HW.teamName(L, tid)) + ' made it in ' +
      (sim.p_playoffs >= 0.995 ? 'nearly all its' : sim.p_playoffs <= 0.005 ? 'almost none of the' : 'about ' + Math.max(1, Math.round(sim.p_playoffs * 10)) + ' of every 10') + ' simulated seasons.' + (isNum(r.net) ? ' A net rating of <b>' + U.signed(r.net, 1) + '</b> is the points per 100 trips the team is better than an average one, after the schedule.' : '')) + '</div>';
    h += '<div class="qk-grid hw-sec">';
    if (path.length > 1) h += U.card2('Net rating through the season', 'Our rating per 100 possessions after each game (Kalman filter), shaded ±1 standard error' + (log.length ? '; dots are results (green won, red lost)' : ''), U.chart('tp-path', 300, 'Net rating through the season'), { cls: 'qk-span-8' });
    const oddsRows = [['Playoffs', sim.p_playoffs], ['Top-six seed', sim.p_top6], ['Conference', sim.p_conf], ['Title', sim.p_title]].filter(x => isNum(x[1]) && x[1] > 0);
    if (oddsRows.length && isCur) h += U.card2('Season chances', 'Our chances from the season simulation',
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
    const recent = log.slice(-8).reverse();
    const txRows = tx ? U.rowsOf(tx).filter(x => String(x.team) === tid) : [];
    const seen = {}, txs = txRows.filter(x => { const k = x.date + x.text; if (seen[k]) return false; seen[k] = 1; return true; }).sort((x, y) => String(y.date).localeCompare(String(x.date))).slice(0, 10);
    const dl = deals && deals.teams ? deals.teams[tid] : null;
    /* v4: the next game as the scoreboard bug (our chance, the start, both teams in their colours) */
    if (upcoming.length) {
      const g0 = upcoming[0], st0 = U.status(g0);
      h += '<section class="qk-section">' + QK.sectionHead({ kicker: st0 === 'live' ? 'Live now' : (QK.fmt.relDay(g0.date) === 'Today' ? 'What to watch tonight' : 'Next up'), title: U.nick(L, g0.away) + ' at ' + U.nick(L, g0.home) }) +
        QK.previewCard(U.game(g0, L, { records: U.records(season) }), { layout: 'bug', nick: t => t.short || t.name, market: 'quiet' }) + '</section>';
    }
    h += '<div class="qk-grid hw-sec">' + U.card2('Schedule', upcoming.length ? 'Next games with our win chance' : 'Results', '<div id="tp-sched"></div>', { cls: 'qk-span-6', flush: true });
    if (txs.length || dl) h += U.card2('Moves', dl ? dl.n + ' rated trade' + (dl.n === 1 ? '' : 's') + ' in 12 months · net ' + U.signed(dl.net_now, 1) + ' WAR in today’s view' : 'Transactions in the last 12 months',
      '<div>' + txs.map(x => '<div class="hw-tx"><span class="d">' + esc(HW.fmtDate(x.date, { year: 'auto', weekday: false })) + '</span><span>' + esc(x.text) + '</span></div>').join('') + '</div>',
      { cls: 'qk-span-6', flush: true, foot: U.link(HW.href(L, 'value') + '?tab=moves&team=' + encodeURIComponent(tid), 'Trade grades and the full feed') });
    h += '</div>';
    el.innerHTML = h;
    if (lo) QKL.team(document.getElementById('tp-league'), lo, tid);
    if (window.QKL && QKL.performers) topPerformers(document.getElementById('tp-top'), L, S, tid, cat);

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
