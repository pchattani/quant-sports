/* The Quant Rink — the team page (#/team/<abbr>), on the kit.
 *
 * Hero in the club colour with record, rating and odds; then Overview: form over the season (rolling 10-game
 * xGF%, GF% and CF%), goal difference against expected-goal difference, unit percentiles, strengths and needs
 * (with trade targets), the CURRENT roster, the schedule (next games with model v market, results) and recent
 * moves; Detail (?view=detail): the full pre-redesign team page (lines, deployment, shot maps for and against,
 * goalies, the trade ledger).
 *
 * Current roster: <S>/valuation.json rows whose team is this club — the build's store carries every player's
 * team as of the last refresh (rosters, recalls and trades applied), so it is today's roster, with injury
 * status; season numbers for this club join from teams.json deployment and value.json. Past seasons fall back
 * to that season's deployment (everyone who played for the club). */
(function (RK) {
'use strict';

const U = RK.ui, esc = RK.esc, isNum = RK.isNum;
/* QKC.line centres its y title on the axis; left-align it so a long title runs over the plot, not off the card
 * (re-applied after the kit repaints on a theme change or a width-bucket resize). */
function yTitleLeft(node) {
  if (!node || !node.__qkc) return;
  const e = node.__qkc, p0 = e.paint;
  const fix = () => { try { e.chart.setOption({ yAxis: { nameTextStyle: { align: 'left' } } }); } catch (err) { /* disposed */ } };
  e.paint = () => { p0(); fix(); };
  if (window.ResizeObserver) new ResizeObserver(() => setTimeout(fix, 0)).observe(node);
  fix();
}

function heroHTML(abbr, S, x, row, sim) {
  const rec = x.record || {};
  const stat = (v, l) => '<div class="qk-hero-stat"><div class="v">' + v + '</div><div class="l">' + esc(l) + '</div></div>';
  return '<section class="qk-hero" style="--tc:' + esc(U.tcol(abbr)) + '"><div class="rk-teamhead">' + QK.teamMark(U.team(abbr), 'lg') +
    '<div><div class="qk-kicker">' + esc([x.division || RK.teamDiv(abbr), (x.conference || RK.teamConf(abbr)) + ' Conference', RK.seasonLabel(S)].filter(Boolean).join(' · ')) + '</div><h1>' + esc(RK.teamName(abbr)) + '</h1>' +
    '<div class="qk-hero-meta"><span><b>' + esc(RK.record(rec.w, rec.l, rec.otl)) + '</b></span><span><b>' + (isNum(rec.pts) ? rec.pts : '—') + '</b> pts in ' + (rec.gp || 0) + '</span>' +
    (row && row.streak ? '<span>Streak <b>' + esc(row.streak) + '</b></span>' : '') + (row && row.league_rank ? '<span><b>' + RK.ordinal(row.league_rank) + '</b> in the league</span>' : '') + '</div></div>' +
    '<div class="qk-hero-stats">' + stat(U.signed((x.units || {}).rating, 2), 'Rating') + stat(sim && isNum(sim.p_playoffs) ? U.pct(sim.p_playoffs) : '—', 'Playoffs') +
    stat(sim && isNum(sim.p_cup) ? U.pct(sim.p_cup, 1) : '—', 'Stanley Cup') + stat(sim && isNum(sim.mean_pts) ? U.f(sim.mean_pts, 0) : '—', 'Proj. points') + '</div></div></section>';
}

function rosterRows(abbr, S, x, val, value) {
  const dep = {}; (x.deployment || []).forEach(p => { dep[p.id] = p; });
  (x.goalies || []).forEach(g => { dep[g.id] = Object.assign({}, dep[g.id] || {}, { gp: g.gp, gsax: g.gsax, sv_pct: g.sv_pct }); });
  const vs = {}; U.rowsOf(value).forEach(r => { vs[r.id] = r; });
  const cur = Number(S) === Number(RK.currentSeason());
  const vr = cur ? U.rowsOf(val).filter(r => r.team === abbr) : [];
  if (vr.length) {
    return { current: true, rows: vr.map(r => {
      const d = dep[r.id] || {}, s = vs[r.id] || {};
      return { id: r.id, name: r.name, pos: r.pos, age: r.age, gp: isNum(s.gp) ? s.gp : d.gp, toi_gp: isNum(s.toi_gp) ? s.toi_gp : d.toi_gp, p: d.p, gar: s.gar, now: r.now, total: r.total, mpg: r.mpg,
        inj: Array.isArray(r.inj) && r.inj[0] ? r.inj[0] + (r.inj[1] ? ' · back ' + RK.fmtDate(r.inj[1], { year: false, weekday: false }) : '') : '', here: !!dep[r.id] || !s.team || s.team === abbr,
        newc: s.team && s.team !== abbr };
    }) };
  }
  return { current: false, rows: (x.deployment || []).concat((x.goalies || []).filter(g => !dep[g.id] || !dep[g.id].pos).map(g => Object.assign({ pos: 'G' }, g))).map(d => {
    const s = vs[d.id] || {};
    return { id: d.id, name: d.name, pos: d.pos || 'G', age: s.age, gp: d.gp, toi_gp: d.toi_gp, p: d.p, gar: isNum(d.gar) ? d.gar : s.gar, now: null, total: null };
  }) };
}

const POS_ORDER = { C: 0, L: 1, R: 2, F: 2, D: 3, G: 4 };

function render(el, params, state) {
  const abbr = RK.canonTeam(params.id);
  const S = params.season;
  const cur = Number(S) === Number(RK.currentSeason());
  const view = ((params.query || {}).view) === 'detail' ? 'detail' : 'overview';
  el.innerHTML = QK.skeleton('card', 1) + QK.skeleton('chart', 1);
  const loads = [RK.loadYear('teams.json', S), RK.loadYear('season.json', S), RK.loadYear('value.json', S)];
  if (cur) loads.push(RK.loadYear('valuation.json', S), RK.load(S + '/needs/' + abbr + '.json'), RK.loadYear('transactions.json', S));
  return Promise.all(loads).then(res => {
    if (!U.alive(el)) return;
    const tj = res[0], sj = res[1];
    const x = RK.ok(tj) ? ((tj.teams || {})[abbr] || null) : null;
    if (!x) { el.innerHTML = U.secHead('teams', RK.teamName(abbr), 'No data for this club in ' + RK.seasonLabel(S) + '.', null, null, 'NHL · Team') + U.card2('Not found', '', QK.empty('Nothing for ' + abbr, 'Pick a club from the teams page.')); return; }
    const row = RK.ok(sj) ? (((sj.standings || {}).rows || []).find(r => r.team === abbr) || null) : null;
    const sim = (RK.ok(sj) && sj.sim && sj.sim.teams && sj.sim.teams[abbr]) || x.sim || null;
    document.title = RK.teamName(abbr) + ' · ' + RK.seasonLabel(S) + ' · ' + RK.SITE;
    const tabs = [{ key: 'overview', label: 'Overview', href: RK.teamHref(abbr, S) }, { key: 'detail', label: 'Detail: lines, deployment, shot maps, goalies, trade ledger', href: RK.teamHref(abbr, S) + (RK.sq(S) ? '&' : '?') + 'view=detail' }];
    el.innerHTML = '<div class="qk-kicker" style="margin-bottom:10px"><a href="' + RK.href('teams', S) + '">← All teams</a></div>' + heroHTML(abbr, S, x, row, sim) + '<div style="margin-top:var(--sp-4)"></div>' + U.tabsHTML(tabs, view) + '<div id="tp-body"></div>';
    const body = el.querySelector('#tp-body');
    if (view === 'detail') return U.legacy('team', body, params, state);

    const val = cur ? res[3] : null, needs = cur && RK.ok(res[4]) ? res[4] : null, tx = cur && RK.ok(res[5]) ? res[5] : null;
    const R = rosterRows(abbr, S, x, RK.ok(val) ? val : null, RK.ok(res[2]) ? res[2] : null);
    const units = x.units || {}, pct = units.pct || {};
    const sched = x.schedule || [];
    const done = sched.filter(g => g.result), next = sched.filter(g => !g.result && g.status !== 'final').slice(0, 6);

    let h = '<div class="qk-grid">' +
      '<div class="qk-span-8">' + U.card2('Form through the season', 'Rolling 10-game shares at 5v5 (xGF%, CF%) and of all goals (GF%); above 50% the club is on top', U.chart('tp-form', 300, 'Rolling form')) + '</div>' +
      '<div class="qk-span-4">' + U.card2('Where they rank', 'League percentile of each unit (100 = best)',
        QK.pctlBars([['rating', 'Overall rating', U.signed(units.rating, 2)], ['off5', '5v5 offence (xGF/60)', U.f(units.off5, 2)], ['def5', '5v5 defence (xGA/60)', U.f(units.def5, 2)],
          ['pp', 'Power play', U.pct(units.pp_pct, 1)], ['pk', 'Penalty kill', U.pct(units.pk_pct, 1)], ['goalie', 'Goaltending (GSAx)', U.signed(units.gsax, 1)]]
          .filter(r => isNum(pct[r[0]])).map(r => ({ label: r[1], pctl: pct[r[0]], value: r[2] })))) + '</div>' +
      '</div>';
    h += '<div class="qk-grid" style="margin-top:var(--sp-4)"><div class="qk-span-12">' + U.card2('Results v process', 'Cumulative goal difference against cumulative expected-goal difference, game by game', U.chart('tp-cum', 260, 'Goal difference against expected goal difference')) + '</div></div>';

    if (needs && (needs.grades || []).length) {
      const gr = needs.grades.map(g => '<div class="rk-flex" style="gap:8px;min-width:0"><span class="rk-grade" data-g="' + esc(g.grade) + '">' + esc(g.grade) + '</span><div style="min-width:0"><div style="font-weight:600">' + esc(g.label) + '</div><div class="qk-muted" style="font-size:var(--fs-xs)">' + RK.ordinal(g.rank) + ' of ' + g.n + ' · ' + U.f(g.value, 1) + ' GAR</div></div></div>').join('');
      const str = (needs.strengths || []).map(s => '<li><span class="rk-grade" data-g="' + esc(s.grade) + '">' + esc(s.grade) + '</span><div><b>' + esc(s.label) + '</b><div class="s">' + esc(s.evidence || '') + '</div></div></li>').join('');
      const wk = (needs.weaknesses || []).map(w => '<li style="align-items:flex-start"><span class="rk-grade" data-g="' + esc(w.grade) + '">' + esc(w.grade) + '</span><div style="min-width:0"><b>' + esc(w.label) + '</b><div class="s">' + esc(w.evidence || '') + '</div>' +
        ((w.targets || []).length ? '<div class="s" style="margin-top:4px">Targets: ' + w.targets.slice(0, 3).map(t => '<a class="rk-link" href="' + RK.playerHref(t.id) + '">' + esc(t.name) + '</a> (' + esc(RK.teamAbbr(t.team)) + ', ' + U.signed(t.gain_season, 1) + ' goals a season' + (isNum(t.d_playoffs) ? ', playoffs ' + QK.fmt.pp(t.d_playoffs) : '') + ')').join(', ') + '</div>' : '') + '</div></li>').join('');
      h += '<section class="qk-section"><div class="qk-section-head"><div><h2>Strengths and needs</h2><div class="qk-sub">Projected value by position and unit against the other 31 clubs; targets are the players who would help most at the weak spots.</div></div></div>' +
        '<div class="qk-grid"><div class="qk-span-4">' + U.card2('Grades', 'A to F against the league', '<div style="display:grid;gap:12px;grid-template-columns:repeat(auto-fill,minmax(150px,1fr))">' + gr + '</div>') + '</div>' +
        '<div class="qk-span-4">' + U.card2('Strengths', '', '<ul class="rk-list">' + str + '</ul>', { flush: true }) + '</div>' +
        '<div class="qk-span-4">' + U.card2('Needs', '', '<ul class="rk-list">' + wk + '</ul>', { flush: true }) + '</div></div>' + (needs.note ? '<p class="rk-note">' + esc(needs.note) + '</p>' : '') + '</section>';
    }

    h += '<section class="qk-section"><div class="qk-section-head"><div><h2>' + (R.current ? 'Current roster' : 'Roster') + '</h2><div class="qk-sub">' +
      (R.current ? 'Today\'s roster (rosters, recalls, trades and injured reserve as of the last refresh), with season numbers and our value: WAR for the rest of this season and over four seasons.' : 'Everyone who played for the club in ' + esc(RK.seasonLabel(S)) + '.') + '</div></div></div>' +
      '<div class="qk-card"><div id="tp-roster"></div></div></section>';

    h += '<section class="qk-section"><div class="qk-grid"><div class="qk-span-' + (tx ? 7 : 12) + '">' + U.card2('Schedule', next.length ? 'Next games with our win probability and the market\'s; then results' : 'Results, game by game', '<div id="tp-sched"></div>', { flush: true }) + '</div>' +
      (tx ? '<div class="qk-span-5">' + U.card2('Recent moves', 'Transactions of the last twelve months (ESPN)', '<div id="tp-moves"></div>', { flush: true, foot: '<span>Trades are graded on Value &amp; Moves</span><a href="#/value?tab=moves&team=' + esc(abbr) + '">All moves →</a>' }) + '</div>' : '') + '</div></section>';
    body.innerHTML = h;

    // form chart
    const roll = x.rolling || [];
    if (roll.length > 1) {
      QKC.line('#tp-form', { x: roll.map(r => r[0]), series: [{ name: 'xGF%', data: roll.map(r => r[2]), color: U.tcol(abbr), width: 3 }, { name: 'GF%', data: roll.map(r => r[3]), dash: true }, { name: 'CF%', data: roll.map(r => r[4]) }],
        yFmt: v => Math.round(v * 100) + '%', ref: { y: 0.5 }, yScale: true, xName: 'Game', yName: 'Rolling 10-game share', xLabel: v => 'Game ' + v + (roll[v - 1] ? ' · ' + RK.fmtDate(roll[v - 1][1], { year: false }) : '') });
      yTitleLeft(body.querySelector('#tp-form'));
    } else body.querySelector('#tp-form').innerHTML = QK.empty('Not enough games', 'The rolling form starts after the first games.');
    // cumulative goal and xG difference
    const played = done.filter(g => isNum(g.gf) && isNum(g.ga));
    if (played.length > 1) {
      let a = 0, b = 0;
      const gd = [], xd = [];
      played.forEach(g => { a += g.gf - g.ga; b += (isNum(g.xgf) && isNum(g.xga) ? g.xgf - g.xga : 0); gd.push(a); xd.push(Math.round(b * 100) / 100); });
      QKC.line('#tp-cum', { x: played.map((g, i) => i + 1), series: [{ name: 'Goal diff', data: gd, color: U.tcol(abbr), width: 3 }, { name: 'xG diff', data: xd, dash: true }], ref: { y: 0 }, yFmt: v => (v > 0 ? '+' : '') + Number(v).toFixed(0), xName: 'Game', yName: 'Cumulative goal difference',
        xLabel: v => { const g = played[v - 1]; return g ? 'Game ' + v + ' · ' + (g.home ? 'v ' : '@ ') + g.opp + ' ' + g.result + ' ' + g.gf + '–' + g.ga : ''; } });
      yTitleLeft(body.querySelector('#tp-cum'));
    } else body.querySelector('#tp-cum').innerHTML = QK.empty('Not enough games');

    // roster table
    const rr = R.rows.slice().sort((p, q) => (POS_ORDER[p.pos] - POS_ORDER[q.pos]) || ((q.toi_gp || q.mpg || 0) - (p.toi_gp || p.mpg || 0)));
    const cols = [{ key: 'name', label: 'Player', sticky: true, fmt: (v, r) => U.playerEnt(r.id, v, null, r.inj ? '' : (r.newc ? 'new' : '')) + (r.inj ? ' <span class="rk-inj" data-tip="' + esc(r.inj) + '">' + esc(r.inj.split(' · ')[0]) + '</span>' : '') },
      { key: 'pos', label: 'Pos', fmt: v => U.pos(v) }, { key: 'age', label: 'Age', num: true, fmt: v => U.f(v, 0) }, { key: 'gp', label: 'GP', num: true },
      { key: 'toi_gp', label: 'TOI/GP', num: true, fmt: v => (isNum(v) ? RK.fmtTOI(v, { minutes: true }) : '—') }, { key: 'p', label: 'Pts', num: true, tip: 'Points for this club this season' },
      { key: 'gar', label: 'GAR', num: true, fmt: v => U.f(v, 1), tip: 'Goals above replacement this season (Rink value)' }];
    if (R.current) cols.push({ key: 'now', label: 'WAR rest', num: true, fmt: v => U.f(v, 2), tip: 'Projected wins above replacement for the rest of this season' }, { key: 'total', label: '4-season', num: true, fmt: v => U.f(v, 1), tip: 'Discounted WAR over the rest of this season and the next three' });
    QK.table(body.querySelector('#tp-roster'), { columns: cols, rows: rr, dense: true, maxHeight: 640 });

    // schedule
    const sRows = next.concat(done.slice().reverse()).map(g => ({ g: g, date: g.date, opp: g.opp, res: g.result ? g.result + ' ' + g.gf + '–' + g.ga : '', p: g.p_win, m: g.p_market, xg: isNum(g.xgf) ? U.f(g.xgf, 1) + '–' + U.f(g.xga, 1) : '' }));
    QK.table(body.querySelector('#tp-sched'), { dense: true, maxHeight: 420, columns: [
      { key: 'date', label: 'Date', fmt: (v, r) => '<a href="' + RK.gameHref(r.g.game_id) + '">' + esc(RK.fmtDate(v, { year: false })) + '</a>' },
      { key: 'opp', label: 'Opponent', fmt: (v, r) => '<span class="qk-muted">' + (r.g.home ? 'v' : '@') + '</span> ' + U.teamEnt(v, { abbr: true }) },
      { key: 'res', label: 'Result', fmt: (v, r) => (v ? '<b class="' + (r.g.result === 'W' ? 'pos' : r.g.result === 'L' ? 'neg' : '') + '">' + esc(v) + '</b>' : '<span class="qk-badge">Next</span>') },
      { key: 'p', label: 'Model', num: true, fmt: v => U.pct(v), tip: 'Our pre-game win probability' }, { key: 'm', label: 'Market', num: true, fmt: v => U.pct(v) },
      { key: 'xg', label: 'xG', num: true, sort: false }], rows: sRows });

    // moves
    if (tx) {
      const seen = {};
      const mv = U.rowsOf(tx).filter(r => r.team === abbr).filter(r => { const k = r.date + r.text; if (seen[k]) return false; seen[k] = 1; return true; }).slice(0, 10);
      const types = tx.types || {};
      body.querySelector('#tp-moves').innerHTML = mv.length ? '<ul class="rk-list">' + mv.map(r => '<li style="align-items:flex-start"><span class="qk-badge' + (r.type === 'trade' ? ' accent' : '') + '" style="flex:none">' + esc(types[r.type] || r.type) + '</span><div style="min-width:0"><div>' + esc(r.text) + '</div><div class="s">' + esc(RK.fmtDate(r.date, { year: false })) + '</div></div></li>').join('') + '</ul>' : QK.empty('No moves in the window');
    }
    RK.setMeta(x && tj.updated_at ? 'Team data ' + esc(RK.fmtStamp(tj.updated_at)) : '');
  });
}

RK.page('team', render);
})(window.RK);
