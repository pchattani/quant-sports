/* The Quant Hardwood — the team page (#/<L>/team/<tid>).
 *
 * Overview tab: a header in the team colour with the headline numbers; the net rating over time (±1 se, game
 * results marked); the season odds against the market and the seed distribution; strengths and needs with the
 * best trade targets (current season); the current roster; the schedule (next games with the model line and the
 * team's availability term, recent results); moves (this team's transactions and rated trades).
 * Detail tab (?tab=detail): the pre-redesign team page in full (four factors, shot profiles, lineups, on/off,
 * rotation, the whole catalogue in percentiles, the trade ledger).
 *
 * Current roster: <L>/<S>/valuation.json (built each run from the latest ESPN rosters: every player whose team is
 * this one, with injury status), joined with the season's numbers from players.json. A past season shows everyone
 * who played for the team (teams.json roster). */
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
  return '<span class="s" style="white-space:nowrap" data-tip="Availability for the next game: points of margin from who is expected to play (injury report applied), against what the rating already reflects">avail. ' + U.sgnHTML(v, 1) + '</span>';
}

function render(el, params) {
  const L = U.L(params), S = U.S(params), tid = String(params.id || '');
  const isCur = U.isCur(L, S);
  const tab = U.tab(params, ['overview', 'detail'], 'overview');
  el.innerHTML = QK.skeleton('lines', 6);
  const opt = (cond, p) => (cond ? HW.load(p) : Promise.resolve(null));
  return Promise.all([HW.load(HW.path('season.json', L, S)), HW.load(HW.path('teams.json', L, S)), HW.load(HW.path('players.json', L, S)),
    opt(isCur, HW.path('needs/' + tid + '.json', L, S)), opt(isCur, HW.path('valuation.json', L, S)), opt(isCur, HW.path('transactions.json', L, S)),
    opt(isCur, HW.path('deals.json', L, S)), opt(isCur, HW.path('schedule.json', L, S)), opt(isCur, HW.lpath('markets.json', L))]).then(a => {
    if (!U.alive(el)) return;
    const season = U.ok(a[0]) ? a[0] : null, teams = U.ok(a[1]) ? a[1] : null, cat = U.ok(a[2]) ? a[2] : null;
    const needs = U.ok(a[3]) ? a[3] : null, val = U.ok(a[4]) ? a[4] : null, tx = U.ok(a[5]) ? a[5] : null, deals = U.ok(a[6]) ? a[6] : null, sched = U.ok(a[7]) ? a[7] : null;
    const markets = U.ok(a[8]) ? a[8] : null;
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
      ['Record', isNum(s.w) ? HW.record(s.w, s.l) : '—', isNum(s.seed) ? HW.ordinal(s.seed) + ' in the ' + (s.conf || 'league') : ''],
      ['Net rating', U.signed(r.net, 1), isNum(r.rank) ? HW.ordinal(r.rank) + ' · ± ' + U.f(r.se_net, 1) : ''],
      ['Offence', U.f(r.off, 1), 'pts per 100'], ['Defence', U.f(r.def, 1), 'allowed per 100']
    ];
    if (open) stats.push(['Projected', U.f(sim.exp_w, 1) + ' W', U.f(sim.w_p05, 0) + '–' + U.f(sim.w_p95, 0)]);
    if (isNum(sim.p_playoffs)) stats.push(['Playoffs', U.pct(sim.p_playoffs), 'title ' + U.pct(sim.p_title)]);
    let h = '<div class="qk-hero" style="--tc:' + esc(col) + '"><div class="hw-teamhead">' + QK.teamMark(U.team(L, tid), 'lg') + '<div><div class="qk-kicker">' + esc(U.kicker(L, S)) + '</div><h1>' + esc(name) + '</h1>' +
      '<div class="qk-hero-meta">' + [info.conference || s.conf, info.division].filter(Boolean).map(x => '<span>' + esc(x) + '</span>').join('') + (isNum(HW.simTeams(season)[tid] && sim.rating) ? '' : '') + '</div></div>' +
      '<div class="qk-hero-stats">' + stats.map(x => '<div class="qk-hero-stat"><div class="l">' + esc(x[0]) + '</div><div class="v">' + esc(x[1]) + '</div>' + (x[2] ? '<div class="hw-quiet">' + esc(x[2]) + '</div>' : '') + '</div>').join('') + '</div></div></div>';
    const base = HW.teamHref(L, tid, S);
    h += U.tabsHTML([{ key: 'overview', label: 'Overview', href: base }, { key: 'detail', label: 'Shots, lineups and the full catalogue', href: base + (base.indexOf('?') >= 0 ? '&' : '?') + 'tab=detail' }], tab);
    if (tab === 'detail') {
      el.innerHTML = h + '<div class="hw-sub"></div>';
      return U.legacy('team', el.querySelector('.hw-sub'), params);
    }
    if (!season && !teams) { el.innerHTML = h + U.empty('Not in this season', name + ' has no data for ' + HW.seasonLabel(L, S) + '.'); return; }
    const path = ((season && season.rating_paths) || {})[tid] || [];
    const log = (T.log || []).slice().sort((x, y) => String(x.date).localeCompare(String(y.date)));
    const mk = (T.odds || {}).market || {};
    const mkTitle = HW.titleProbs(markets && markets.futures && markets.futures.champion);
    const wt = ((markets && markets.win_totals) || {})[tid];
    h += '<div class="qk-grid hw-sec">';
    if (path.length > 1) h += U.card2('Rating over time', 'Net rating per 100 after each game (Kalman filter), shaded ±1 standard error' + (log.length ? '; dots are results' : ''), U.chart('tp-path', 300, 'Net rating over time'), { cls: 'qk-span-8' });
    const oddsRows = [['Playoffs', sim.p_playoffs, mk.p_playoffs], ['Top-six seed', sim.p_top6, mk.p_top6], ['Conference', sim.p_conf, mk.p_conf], ['Title', sim.p_title, isNum(mkTitle[tid]) ? mkTitle[tid] : mk.p_title]].filter(x => isNum(x[1]) && (x[1] > 0 || isNum(x[2])));
    if (oddsRows.length && isCur) h += U.card2('Season odds', 'Model' + (oddsRows.some(x => isNum(x[2])) ? ' against the market' : '') + (wt && isNum(wt.line) ? ' · win total ' + U.f(wt.line, 1) + ': over ' + U.pct(wt.p_over_model) + ' (market ' + U.pct(wt.p_over_market) + ')' : ''),
      '<ul class="hw-list">' + oddsRows.map(x => '<li><span class="nm" style="flex:1">' + esc(x[0]) + '</span>' + HW.ui.probBar(x[1], col) + '<span class="s">' + (isNum(x[2]) ? 'market ' + U.pct(x[2]) : '') + '</span></li>').join('') + '</ul>' +
      ((sim.seed_dist || []).length && open ? U.chart('tp-seed', 160, 'Seed distribution') + '<div class="hw-chartcap">Share of simulated seasons finishing in each seed</div>' : ''), { cls: path.length > 1 ? 'qk-span-4' : 'qk-span-12' });
    h += '</div>';
    // strengths and needs
    if (needs && needs.grades) {
      h += '<section class="qk-section"><div class="qk-section-head"><div><h2>Strengths and needs</h2><div class="qk-sub">Each position group and unit graded against the league on projected value (WAR over a full season); the best trade targets for each weak spot.</div></div></div><div class="qk-grid">' +
        U.card2('Grades', '', '<div id="tp-grades"></div>', { cls: 'qk-span-5', flush: true }) +
        U.card2('Where to improve', 'Ranked by wins added in this rotation', '<div id="tp-targets"></div>', { cls: 'qk-span-7', flush: true }) + '</div></section>';
    }
    h += '<section class="qk-section"><div class="qk-section-head"><div><h2>' + (isCur ? 'Current roster' : 'Roster') + '</h2><div class="qk-sub">' + (isCur && val ? 'From the latest rosters and injury report (rebuilt every run). HPM is the projected rest-of-season rate per 100; WAR the projected wins above replacement.' : 'Everyone who played, by minutes.') + '</div></div></div>' +
      '<div class="qk-card"><div id="tp-roster"></div></div></section>';
    // schedule + moves
    const upcoming = sched ? (sched.games || []).filter(g => (String(g.home) === tid || String(g.away) === tid) && HW.gameState(g) !== 'post').sort((x, y) => String(x.date).localeCompare(String(y.date))).slice(0, 8) : [];
    const recent = log.slice(-8).reverse();
    const txRows = tx ? U.rowsOf(tx).filter(x => String(x.team) === tid) : [];
    const seen = {}, txs = txRows.filter(x => { const k = x.date + x.text; if (seen[k]) return false; seen[k] = 1; return true; }).sort((x, y) => String(y.date).localeCompare(String(x.date))).slice(0, 10);
    const dl = deals && deals.teams ? deals.teams[tid] : null;
    h += '<div class="qk-grid hw-sec">' + U.card2('Schedule', upcoming.length ? 'Next games with the model’s win probability' : 'Results', '<div id="tp-sched"></div>', { cls: 'qk-span-6', flush: true });
    if (txs.length || dl) h += U.card2('Moves', dl ? dl.n + ' rated trade' + (dl.n === 1 ? '' : 's') + ' in 12 months · net ' + U.signed(dl.net_now, 1) + ' WAR in today’s view' : 'Transactions in the last 12 months',
      '<div>' + txs.map(x => '<div class="hw-tx"><span class="d">' + esc(HW.fmtDate(x.date, { year: 'auto', weekday: false })) + '</span><span>' + esc(x.text) + '</span></div>').join('') + '</div>',
      { cls: 'qk-span-6', flush: true, foot: U.link(HW.href(L, 'value') + '?tab=moves&team=' + encodeURIComponent(tid), 'Trade grades and the full feed') });
    h += '</div>';
    el.innerHTML = h;

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
          yAxis: QKC.axis(Tk, { fmt: v => U.signed(v, 0), scale: true, name: 'Net rating per 100', nameAlign: 'left' }),
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
      QKC.bar('#tp-seed', { cats: sd.map((v, i) => String(i + 1)), series: [{ name: 'Seed', data: sd.map(v => Math.round(v * 1000) / 1000) }], colors: sd.map(() => col), fmt: v => U.pct(v), valName: 'Probability', catName: 'Seed' });
    }
    if (needs && needs.grades) {
      QK.table(document.getElementById('tp-grades'), { dense: true, rows: needs.grades, columns: [
        { key: 'label', label: 'Area' }, { key: 'grade', label: 'Grade', fmt: v => U.grade(v) }, { key: 'value', label: 'WAR', num: true, fmt: v => U.f(v, 1), tip: 'Projected WAR over a full season' },
        { key: 'rank', label: 'Rank', num: true, fmt: (v, g) => HW.ordinal(v) + ' of ' + g.n }] });
      const strong = (needs.strengths || []).map(x => '<div class="hw-target"><div class="hw-flex">' + U.grade(x.grade) + '<b>' + esc(x.label) + '</b><span class="qk-badge" style="margin-left:auto">strength</span></div><div class="why">' + esc(x.evidence || '') + '</div></div>').join('');
      const weak = (needs.weaknesses || []).map(w => {
        const tg = (w.targets || []).slice(0, 2);
        return '<div class="hw-target"><div class="hw-flex">' + U.grade(w.grade) + '<b>' + esc(w.label) + '</b><span class="qk-badge" style="margin-left:auto">need</span></div><div class="why">' + esc(w.evidence || '') + '</div>' +
          tg.map(c => '<div class="hw-flex" style="margin-top:6px">' + U.playerEnt(L, c.id, c.name, c.team, HW.teamAbbr(L, c.team) + ' · ' + (U.ROLE1[c.role] || '') + (isNum(c.age) ? ' · ' + Math.floor(c.age) : '')) +
            '<span class="v" style="margin-left:auto">' + U.signed(c.wins, 1) + ' wins</span>' + (c.attainable ? '<span class="qk-badge accent">attainable</span>' : '') +
            '<a class="hw-link" href="' + esc('#/' + L + '/value?tab=trade&t=' + encodeURIComponent(tid) + ',' + encodeURIComponent(c.team) + '&m=' + encodeURIComponent(c.id) + '-' + encodeURIComponent(tid)) + '">Simulate →</a></div>').join('') + '</div>';
      }).join('');
      document.getElementById('tp-targets').innerHTML = strong + weak || U.empty('No grades', '');
    }
    // roster
    const P = (cat && cat.players) || {};
    const rosterNode = document.getElementById('tp-roster');
    const vrows = U.rowsOf(val).filter(x => String(x.team) === tid);
    if (isCur && vrows.length) {
      const rows = vrows.map(x => { const p = P[x.id] || {}, v = p.values || {}; return Object.assign({}, x, { gp: p.gp, ppg: v.pts_g, rpg: v.reb_g, apg: v.ast_g }); }).sort((x, y) => (y.mpg || 0) - (x.mpg || 0));
      const anyGp = rows.some(x => isNum(x.gp));
      QK.table(rosterNode, { dense: true, rows: rows, columns: [
        { key: 'name', label: 'Player', sticky: true, fmt: (v, x) => U.playerEnt(L, x.id, x.name, null, null, S) + (x.inj ? ' <span class="hw-inj" data-tip="' + esc(x.inj) + '">' + esc(String(x.inj).split(' ')[0]) + '</span>' : '') },
        { key: 'pos', label: 'Pos', fmt: (v, x) => U.pos(v) + ' <span class="hw-quiet">' + esc(U.ROLE1[x.role] || '') + '</span>' },
        { key: 'age', label: 'Age', num: true, fmt: v => (isNum(v) ? String(Math.floor(v)) : '—') },
        { key: 'mpg', label: 'Proj min', num: true, fmt: v => U.f(v, 1), tip: 'Projected minutes a game' }]
        .concat(anyGp ? [{ key: 'gp', label: 'GP', num: true }, { key: 'ppg', label: 'PPG', num: true, fmt: v => U.f(v, 1) }, { key: 'rpg', label: 'RPG', num: true, fmt: v => U.f(v, 1) }, { key: 'apg', label: 'APG', num: true, fmt: v => U.f(v, 1) }] : [])
        .concat([{ key: 'rate', label: 'HPM', num: true, fmt: v => U.sgnHTML(v, 1), tip: 'Projected rest-of-season impact per 100 possessions' },
          { key: 'w0', label: 'WAR', num: true, fmt: v => U.f(v, 1), tip: 'Projected wins above replacement, rest of season' },
          { key: 'v', label: '4-yr value', num: true, fmt: v => U.f(v, 1), tip: 'Discounted WAR over four seasons' }]) });
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
