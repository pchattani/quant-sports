/* The Quant Rink — the team page (#/team/<abbr>), kit v4 "Broadcast": a crumb, the full-bleed hero in the club colour
 * (the alternate colour on the diagonal, the abbreviation outlined) with the black strip of five numbers (our playoff
 * and Cup chances, projected points, our rating and the 5v5 chance share, both with their rank among the 32 clubs) and
 * "The short version" (record, our chances, what the club is best at and its weak spot, in plain English); then what
 * to watch next (the scoreboard bug and how the clubs match up, as the player page) beside the last game (the box
 * score by period and its expected-goals race, from the game file); then as below.
 *
 * Team header in the club colour (record, points, streak, rank; our rating and chances), stat tiles with our playoff
 * and Cup chances and the projected full-season points with the simulation's 90% range; Overview: the percentile
 * card on the spec's team set (docs/METRICS_SPEC.md "Teams": rank among the 32 clubs, from 10 games; a metric short
 * of the games where it settles is dashed), form over the season, results v process, strengths and needs, the
 * Outlook (who moves next: expected departures and arrivals by position, movement.json), the CURRENT roster with
 * each player's chance of not being in the lineup next season, the schedule with our win chance, and recent moves;
 * Detail (?view=detail): the full pre-redesign team page (lines, deployment, shot maps, goalies, trade ledger).
 *
 * Current roster: <S>/valuation.json rows whose team is this club (today's roster as of the last refresh); season
 * numbers join from teams.json deployment and value.json. Past seasons fall back to that season's deployment. */
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

/* "The short version" for a club: the record, our playoff and Cup chances, then (from 10 games, the spec's minimum
   for ranks) what it does best among the 32 clubs and its weak spot. Small samples are named. */
const NUMW = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten'];
function lc(x) { return /^[A-Z][a-z]/.test(x) ? x.charAt(0).toLowerCase() + x.slice(1) : x; }
function shortTeam(abbr, x, sim, tr) {
  const rec = x.record || {}, gp = rec.gp || 0;
  const nm = RK.teamShort(abbr);
  if (!gp) return sim && isNum(sim.p_playoffs) ? 'No games yet. Before the first puck drop we give the ' + nm + ' a ' + U.pct(sim.p_playoffs) + ' chance of making the playoffs.' : null;
  let t = 'The ' + nm + ' are ' + RK.record(rec.w, rec.l, rec.otl) + (isNum(rec.pts) ? ', with ' + rec.pts + ' point' + (rec.pts === 1 ? '' : 's') + ' from ' + gp + ' game' + (gp === 1 ? '' : 's') : '') + '.';
  if (sim && isNum(sim.p_playoffs)) t += ' We give them a ' + U.pct(sim.p_playoffs) + ' chance of the playoffs' + (isNum(sim.p_cup) ? ' and ' + U.pct(sim.p_cup, 1) + ' to win the Cup' : '') + '.';
  const pc = (tr && tr.p) || {};
  const rows = U.TEAM_SET.filter(m => m[0] !== 'pts_pct' && m[0] !== 'gd_g' && isNum(pc[m[0]])).map(m => [m[0], pc[m[0]], m[1]]);
  if (gp >= U.TEAM_MIN_GP && rows.length) {
    const top = rows.slice().sort((a, b) => b[1] - a[1])[0], low = rows.slice().sort((a, b) => a[1] - b[1])[0];
    if (top[1] >= 70) t += ' Best at ' + lc(top[2]) + ' (' + QK.ordinal(Math.round(top[1])) + ' percentile of the 32 clubs).';
    if (low[1] <= 30 && low[0] !== top[0]) t += ' The weak spot: ' + lc(low[2]) + ', in the ' + QK.ordinal(Math.round(low[1])) + ' percentile.';
  } else if (gp < U.TEAM_MIN_GP) t += ' ' + (NUMW[gp] || gp) + ' game' + (gp === 1 ? ' is' : 's is') + ' a small sample, so the ranks start after ' + U.TEAM_MIN_GP + '.';
  return t;
}
function header(abbr, S, x, row, sim, tr) {
  const rec = x.record || {};
  const v = (tr && tr.v) || {}, pc = (tr && tr.p) || {};
  /* the black strip: our chances first, then the two numbers that say how good the club is (with its rank) */
  const strip = [
    { label: 'Our playoff chance', value: sim && isNum(sim.p_playoffs) ? U.pct(sim.p_playoffs) : '—', signal: true, sub: 'from 20,000 simulated seasons', tip: 'Our chance of a playoff spot in the season simulation' },
    { label: 'Stanley Cup', value: sim && isNum(sim.p_cup) ? U.pct(sim.p_cup, 1) : '—', sub: 'our chance' + (sim && isNum(sim.p_div) ? ' · division ' + U.pct(sim.p_div) : '') },
    { label: 'Projected points', value: sim && isNum(sim.mean_pts) ? U.f(sim.mean_pts, 0) : '—', sub: sim && isNum(sim.pts_p05) ? '9 seasons in 10: ' + sim.pts_p05 + '–' + sim.pts_p95 : 'at the end of the full season', tip: 'The mean of the simulated seasons: points at the end of the full regular season, today’s included' },
    { label: 'Team rating', value: U.signed(isNum(v.rating) ? v.rating : (x.units || {}).rating, 2), pctl: pc.rating, sub: 'goals a game against an average club', tip: 'Our team-strength model: expected goal difference per game against an average team, all situations' },
    { label: '5v5 chance share', value: U.teamFmt('xgf_pct5', v.xgf_pct5), pctl: pc.xgf_pct5, sub: 'of the expected goals at 5-on-5', tip: 'Share of the 5-on-5 expected goals: over a season it predicts the next games better than the goal difference' }
  ];
  return QK.playerHeader({ name: RK.teamName(abbr), split: false, face: RK.teamAbbr(abbr), pos: (x.conference || RK.teamConf(abbr)) + ' Conference', kicker: RK.seasonLabel(S) + (rec.gp ? ' · ' + rec.gp + ' game' + (rec.gp === 1 ? '' : 's') + ' in' : ''),
    team: { name: (x.division || RK.teamDiv(abbr)) + ' Division', abbr: RK.teamAbbr(abbr), colour: RK.teamColourRaw(abbr), alt: RK.teamAlt(abbr) },
    meta: [['Record', RK.record(rec.w, rec.l, rec.otl)], ['Points', (isNum(rec.pts) ? rec.pts : '—') + ' in ' + (rec.gp || 0)], row && row.streak ? ['Streak', row.streak] : null, row && row.league_rank ? ['League', RK.ordinal(row.league_rank)] : null],
    strip: strip, short: shortTeam(abbr, x, sim, tr) });
}

/* What to watch next and the last game (as the player page): the scoreboard bug with the match-up factors from
   season.json, and the last game's box score by period with its expected-goals race (the game file). */
function nickOf(ab) { return U.nick ? U.nick(ab) : RK.teamName(ab); }
function nextAndLast(abbr, S, done, cur) {
  const idx = RK.index() || {};
  const games = cur ? [].concat(idx.live || [], idx.today || [], idx.upcoming || []).filter(g => g && (g.home === abbr || g.away === abbr)) : [];
  const nxt = games.filter(g => U.status(g) !== 'final').sort((a, b) => String(a.start).localeCompare(String(b.start)))[0] || null;
  const last = done.length ? done[done.length - 1] : null;
  if (!nxt && !last) return { html: '', nxt: null, last: null };
  let h = '<section class="qk-section rk-sec1"><div class="qk-g2">';
  if (nxt) {
    const live = U.status(nxt) === 'live';
    h += '<div>' + QK.sectionHead({ kicker: live ? 'Live now' : (QK.fmt.relDay(nxt.start) === 'Today' ? 'What to watch tonight' : 'Next up'), title: nickOf(nxt.away) + ' at ' + nickOf(nxt.home) }) + '<div id="tp-next">' + QK.skeleton('card', 1) + '</div></div>';
  }
  if (last) {
    const won = last.gf > last.ga, me = RK.teamAbbr(abbr), op = RK.teamAbbr(last.opp);
    const ttl = isNum(last.gf) && isNum(last.ga) ? (won ? me + ' ' + last.gf + ', ' + op + ' ' + last.ga : op + ' ' + last.ga + ', ' + me + ' ' + last.gf) : (last.home ? 'v ' : 'at ') + RK.teamName(last.opp);
    const pre = isNum(last.p_win) ? 'We gave the ' + RK.teamShort(abbr) + ' a ' + U.pct(last.p_win) + ' chance before the game. ' : '';
    const xgl = isNum(last.xgf) && isNum(last.xga) ? 'Expected goals ' + U.f(last.xgf, 1) + '–' + U.f(last.xga, 1) + (Math.abs(last.xgf - last.xga) < 0.5 ? ': an even game on chances.' : (last.xgf > last.xga) === won ? ': the chances backed the result.' : ': the result went against the chances.') : '';
    h += '<div>' + QK.sectionHead({ kicker: 'Last game', title: ttl, sub: RK.fmtDate(last.date, { year: false }) + (last.home ? ' · at home' : ' · away') }) + '<article class="qk-card"><div class="qk-card-body"><div id="tp-box"></div>' +
      (pre || xgl ? QK.explain(esc(pre + xgl)) : '') + '<div id="tp-race"></div><p class="qk-caption"><a class="qk-link" href="' + esc(RK.gameHref(last.game_id)) + '">The full game page →</a></p></div></article></div>';
  }
  return { html: h + '</div></section>', nxt: nxt, last: last };
}
function fillNext(body, nxt, sj) {
  const box = body.querySelector('#tp-next');
  if (!box || !nxt) return;
  const season = RK.ok(sj) ? sj : {};
  const rows = {}; (((season.standings || {}).rows) || []).forEach(r => { rows[r.team] = r; });
  const g = U.gameV2(nxt, null, rows);
  g.away.alt = RK.teamAlt(nxt.away); g.home.alt = RK.teamAlt(nxt.home);
  g.away.full = RK.teamName(nxt.away); g.home.full = RK.teamName(nxt.home);
  const R = season.ratings || {}, ua = (R[nxt.away] || {}).units || {}, uh = (R[nxt.home] || {}).units || {};
  const fx = [];
  const add = (label, a, b, f, low) => { if (isNum(a) && isNum(b)) fx.push({ label: label, a: f(a), b: f(b), better: Math.abs(a - b) < 1e-9 ? null : ((a > b) !== !!low ? 'a' : 'b') }); };
  add('Goals for per game', ua.gf_g, uh.gf_g, v => U.f(v, 1));
  add('Goals against per game', ua.ga_g, uh.ga_g, v => U.f(v, 1), true);
  add('Chance share, 5-on-5', ua.xgf_pct5, uh.xgf_pct5, v => U.pct(v, 1));
  add('Team rating', (rows[nxt.away] || {}).rating, (rows[nxt.home] || {}).rating, v => U.signed(v, 2));
  const m = nxt.model || {};
  const extra = isNum(m.p_ot) ? 'Overtime: ' + U.pct(m.p_ot) + ' (about 1 in ' + Math.max(2, Math.round(1 / m.p_ot)) + ').' : '';
  box.innerHTML = QK.previewCard(g, { layout: 'bug', nick: t => nickOf(t.abbr), factors: fx, factorsTitle: 'How they match up so far', noteExtra: esc(extra) });
}
function fillLast(body, abbr, last) {
  if (!last || !body.querySelector('#tp-box')) return;
  RK.loadGame(last.game_id).then(d => {
    if (!RK.ok(d) || !U.alive(body)) return;
    const ls = d.linescore || [], card = d.card || {};
    const home = card.home || (last.home ? abbr : last.opp), away = card.away || (last.home ? last.opp : abbr);
    if (ls.length) {
      const pl = RK.isPlayoffGame ? RK.isPlayoffGame(card) : false;
      const sum = k => ls.reduce((s, r) => s + (isNum(r[k]) ? r[k] : 0), 0);
      const row = (ab, side) => '<tr' + (ab === abbr ? ' class="hl"' : '') + '><td>' + QK.teamMark(U.team(ab), 'sm') + '</td>' + ls.map(r => '<td class="num">' + (isNum(r['g_' + side]) ? r['g_' + side] : '–') + '</td>').join('') +
        '<td class="num"><b>' + sum('g_' + side) + '</b></td><td class="num">' + sum('s_' + side) + '</td><td class="num">' + U.f(sum('xg_' + side), 2) + '</td></tr>';
      body.querySelector('#tp-box').innerHTML = '<div class="qk-table-wrap"><table class="qk-table dense"><thead><tr><th>Team</th>' + ls.map(r => '<th class="num">' + esc(RK.periodLabel ? RK.periodLabel(r.period, { playoff: pl }) : r.period) + '</th>').join('') +
        '<th class="num">Goals</th><th class="num">Shots</th><th class="num" data-tip="Expected goals: the chance quality of every shot, added up">Exp. goals</th></tr></thead><tbody>' + row(away, 'away') + row(home, 'home') + '</tbody></table></div>';
    }
    const race = d.xg_race && Array.isArray(d.xg_race.rows) ? d.xg_race.rows : [];
    if (race.length < 2) return;
    const ci = {}; (d.xg_race.cols || []).forEach((k, i) => { ci[k] = i; });
    const pr = U.pair(away, home), ca = pr[0], ch = pr[1];
    body.querySelector('#tp-race').innerHTML = U.chart('tp-race-c', 240, 'Expected goals through the last game');
    const x = race.map(r => r[ci.sec] / 60);
    QKC.mount('#tp-race-c', T => {
      const mk = (side, col, ab) => ({ type: 'line', name: RK.teamAbbr(ab), step: 'end', showSymbol: false, data: race.map((r, i) => [x[i], r[ci[side]]]), lineStyle: { width: 3, color: col }, itemStyle: { color: col },
        areaStyle: ab === abbr ? { color: QKC.hexA(col, 0.12) } : undefined,
        markPoint: { symbol: 'rect', symbolSize: 9, itemStyle: { color: col, borderColor: T.s1, borderWidth: 2 }, label: { show: false },
          data: race.map((r, i) => (r[ci.goal] && String(r[ci.goal]) === String(ab) ? { coord: [x[i], r[ci[side]]] } : null)).filter(Boolean) },
        endLabel: { show: true, formatter: p => RK.teamAbbr(ab) + ' ' + U.f(p.value[1], 1), color: T.ink1, fontFamily: T.fontDisplay, fontSize: 20 } });
      const xa = QKC.axis(T, { type: 'value', min: 0, max: Math.max(60, Math.ceil(x[x.length - 1] / 5) * 5), interval: 20, split: false, line: true });
      const ya = QKC.axis(T, { fmt: v => v.toFixed(1) });
      const gB = 8 + QKC.nameAxis(xa, 'Minutes played', 'bottom'), gT = 14 + QKC.nameAxis(ya, 'Expected goals', 'side');
      return { grid: { left: 8, right: 80, top: gT, bottom: gB, containLabel: true }, xAxis: xa, yAxis: ya,
        tooltip: QKC.tooltip(T, { trigger: 'axis', formatter: ps => '<div>Minute ' + esc(U.f(ps[0].value[0], 0)) + '</div>' + ps.map(q => QKC.tipRow(q.color, q.seriesName, U.f(q.value[1], 2) + ' xG')).join('') }),
        series: [mk('away', ca, away), mk('home', ch, home)] };
    }, { label: 'Expected goals through the last game' });
  });
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
        inj: Array.isArray(r.inj) && r.inj[0] ? r.inj[0] + (r.inj[1] ? ' · back ' + RK.fmtDate(r.inj[1], { year: false, weekday: false }) : '') : '', newc: s.team && s.team !== abbr };
    }) };
  }
  return { current: false, rows: (x.deployment || []).concat((x.goalies || []).filter(g => !dep[g.id] || !dep[g.id].pos).map(g => Object.assign({ pos: 'G' }, g))).map(d => {
    const s = vs[d.id] || {};
    return { id: d.id, name: d.name, pos: d.pos || 'G', age: s.age, gp: d.gp, toi_gp: d.toi_gp, p: d.p, gar: isNum(d.gar) ? d.gar : s.gar, now: null, total: null };
  }) };
}

const POS_ORDER = { C: 0, L: 1, LW: 1, R: 2, RW: 2, F: 2, D: 3, G: 4 };
const MV_POS = [['C', 'Centre'], ['LW', 'Left wing'], ['RW', 'Right wing'], ['D', 'Defence'], ['G', 'Goalie']];
const NEED_KEY = { C: 'C', LW: 'L', RW: 'R', D: 'D', G: 'G' };

/* The percentile card on the team set; before 10 games, the values so far without ranks. */
function teamCard(abbr, TS) {
  const r = TS.by[abbr];
  if (!r) return U.card2('Where they rank', '', QK.empty('No team numbers yet'));
  const sample = r.gp + ' games · ranks from ' + U.TEAM_MIN_GP + ' games; 5v5 xG share settles at about 13';
  if (r.gp < U.TEAM_MIN_GP) {
    return U.card2('Where they rank', 'Peers: the 32 NHL clubs · ' + esc(sample), '<p class="rk-note" style="margin:0 0 8px">Ranks start after ' + U.TEAM_MIN_GP + ' games (' + esc(RK.teamShort(abbr)) + ' have played ' + r.gp + '): before then they are mostly noise. The numbers so far:</p>' +
      '<ul class="rk-list" style="margin:0 -16px">' + U.TEAM_SET.map(m => '<li><span data-tip="' + esc(m[3]) + '" tabindex="0">' + esc(m[1]) + '</span><span class="v">' + U.teamFmt(m[0], r.v[m[0]]) + '</span></li>').join('') + '</ul>');
  }
  const rows = U.TEAM_SET.map(m => (isNum(r.p[m[0]]) ? { label: m[1], pctl: r.p[m[0]], value: U.teamFmt(m[0], r.v[m[0]]), tip: m[3] + ' (' + m[2] + ').', early: isNum(U.TEAM_SETTLE[m[0]]) && r.gp < U.TEAM_SETTLE[m[0]] } : null)).filter(Boolean);
  return QK.pctCard({ title: 'Where they rank', peer: 'the 32 NHL clubs', sample: sample, groups: [{ label: 'Strength', rows: rows.slice(0, 1) }, { label: 'Process (predicts results)', rows: rows.slice(1, 8) }, { label: 'Results', rows: rows.slice(8) }] });
}

/* Outlook (MOVES_VIEWS.md, US sports §2): published blocks only; base rates labelled as such. */
function outlook(abbr, M, R, needs) {
  if (!M) return '';
  const t = M.teams[abbr];
  if (!t) return '';
  const d = M.d, ba = d.base_arrivals || {};
  const mine = M.rows.filter(r => r.team === abbr);
  const depPos = {}; mine.forEach(r => { if (isNum(r.p_next)) depPos[r.pos] = (depPos[r.pos] || 0) + r.p_next; });
  const ol = {}; (t.outlook || []).forEach(o => { const x = Array.isArray(o) ? o : null; const k = x ? x[0] : o.pos; ol[k] = x ? { p_add: x[1], exp_arrivals: x[2], need: x[3], exp_departures: x[4] } : o; });
  const weak = {}; ((needs && needs.weaknesses) || []).forEach(w => { weak[w.key] = 1; });
  const arrPub = !!M.pub.arrivals;
  const arrSum = Object.keys(ba).reduce((s, k) => s + ((ba[k] || [])[1] || 0), 0);
  const cuts = d.status_cuts || {};
  const head = QK.stats([
    isNum(t.exp_departures) ? { label: 'Expected departures', value: U.f(t.exp_departures, 1), unit: 'players', signal: true, sub: 'not in the lineup by ' + M.horizon, tip: 'The sum of each player’s chance of not being in the lineup next season (our model; it counts a season in the minors).' } : null,
    arrPub && isNum(t.exp_arrivals) ? { label: 'Expected arrivals', value: U.f(t.exp_arrivals, 1), unit: 'players', sub: 'from other NHL rosters', tip: 'Prospects, draft picks and players from outside the NHL are not counted.' }
      : { label: 'Expected arrivals', value: U.f(arrSum, 1), unit: 'players', sub: 'league average (base rate)', tip: ((d.reasons || {}).arrivals || '') + ' Prospects, draft picks and players from outside the NHL are not counted.' }
  ]);
  const grid = '<div class="qk-table-wrap"><table class="rk-ol"><thead><tr><th>Position</th><th class="num" data-tip="' + esc(arrPub ? 'Our chance the club adds a player here from another NHL roster' : 'How often a club adds a player here from another NHL roster (league base rate)') + '">Chance of adding</th><th class="num">Expected arrivals</th><th class="num" data-tip="The sum of the roster’s chances of not being in the lineup next season at this position">Expected departures</th></tr></thead><tbody>' +
    MV_POS.map(p => {
      const o = ol[p[0]] || {};
      const pa = arrPub && isNum(o.p_add) ? o.p_add : (ba[p[0]] || [])[0], ea = arrPub && isNum(o.exp_arrivals) ? o.exp_arrivals : (ba[p[0]] || [])[1];
      const ed = isNum(o.exp_departures) ? o.exp_departures : depPos[p[0]];
      return '<tr><td>' + esc(p[1]) + (weak[NEED_KEY[p[0]]] ? ' ' + QK.tag('need') : '') + (isNum(o.need) ? ' ' + QK.pctlChip((1 - o.need) * 100) : '') + '</td><td class="num">' + (isNum(pa) ? U.pct(pa) : '—') + '</td><td class="num">' + U.f(ea, 2) + '</td><td class="num">' + U.f(ed, 1) + '</td></tr>';
    }).join('') + '</tbody></table></div>';
  const targets = M.pub.targets && (t.targets || []).length ? '' : '<p class="rk-note">Who they could get from other clubs is not shown: ' + esc(((d.reasons || {}).targets || 'the target ranking is not published.').replace(/^The /, 'the ')) + (needs && (needs.weaknesses || []).length ? ' The players listed under each need above come from the need x value ranking.' : '') + '</p>';
  return '<section class="qk-section">' + QK.sectionHead({ kicker: 'Who moves next', title: 'Outlook: ' + M.horizon, html: true,
      sub: 'Who is likely to leave the lineup and how many players a club like this usually adds, by position. ' + (t.status ? QK.tag(t.status, 'signal') + ' <span class="rk-info" tabindex="0" data-tip="' + esc('From the club’s record (a ' + RK.fmtVal(t.wp, '3') + ' win share): contending at ' + RK.fmtVal(cuts.contending, '3') + ' or better, rebuilding at ' + RK.fmtVal(cuts.rebuilding, '3') + ' or worse.') + '">ⓘ</span>' : '') }) +
    '<div class="qk-grid"><div class="qk-span-5">' + head + '</div><div class="qk-span-7">' + U.card2('By position', arrPub ? 'Our chances' : 'Departures: our model · arrivals: the league base rate ' + QK.tag('base rate'), grid, { flush: true }) + '</div></div>' +
    targets + '</section>';
}

function render(el, params, state) {
  const abbr = RK.canonTeam(params.id);
  const S = params.season;
  const cur = Number(S) === Number(RK.currentSeason());
  const view = ((params.query || {}).view) === 'detail' ? 'detail' : 'overview';
  el.innerHTML = QK.skeleton('card', 1) + QK.skeleton('chart', 1);
  const loads = [RK.loadYear('teams.json', S), RK.loadYear('season.json', S), RK.loadYear('value.json', S)];
  if (cur) loads.push(RK.loadYear('valuation.json', S), RK.load(S + '/needs/' + abbr + '.json'), RK.loadYear('transactions.json', S), U.moves(S));
  return Promise.all(loads).then(res => {
    if (!U.alive(el)) return;
    const tj = res[0], sj = res[1];
    const x = RK.ok(tj) ? ((tj.teams || {})[abbr] || null) : null;
    if (!x) { el.innerHTML = U.secHead('teams', RK.teamName(abbr), 'No data for this club in ' + RK.seasonLabel(S) + '.', null, null, 'NHL · Team') + U.card2('Not found', '', QK.empty('Nothing for ' + abbr, 'Pick a club from the teams page.')); return; }
    const row = RK.ok(sj) ? (((sj.standings || {}).rows || []).find(r => r.team === abbr) || null) : null;
    const sim = (RK.ok(sj) && sj.sim && sj.sim.teams && sj.sim.teams[abbr]) || x.sim || null;
    document.title = RK.teamName(abbr) + ' · ' + RK.seasonLabel(S) + ' · ' + RK.SITE;
    const tabs = [{ key: 'overview', label: 'Overview', href: RK.teamHref(abbr, S) }, { key: 'detail', label: 'Detail: lines, deployment, shot maps, goalies, trade ledger', href: RK.teamHref(abbr, S) + (RK.sq(S) ? '&' : '?') + 'view=detail' }];
    const TS = U.teamSet(tj, RK.ok(sj) ? sj : null);
    const tr = TS.by[abbr] || { p: {}, v: {} };
    const crumb = '<nav class="rk-crumb" aria-label="Breadcrumb"><a href="#/">Hockey</a><span aria-hidden="true">›</span><a href="' + esc(RK.href('teams', S)) + '">Teams</a><span aria-hidden="true">›</span>' + esc(RK.teamName(abbr)) + '</nav>';
    el.innerHTML = crumb + header(abbr, S, x, row, sim, tr) + '<div style="margin-top:var(--sp-6)"></div>' + U.tabsHTML(tabs, view) + '<div id="tp-body"></div>';
    const body = el.querySelector('#tp-body');
    if (view === 'detail') return U.legacy('team', body, params, state);

    const val = cur ? res[3] : null, needs = cur && RK.ok(res[4]) ? res[4] : null, tx = cur && RK.ok(res[5]) ? res[5] : null, M = cur ? res[6] : null;
    const R = rosterRows(abbr, S, x, RK.ok(val) ? val : null, RK.ok(res[2]) ? res[2] : null);
    const sched = x.schedule || [];
    const done = sched.filter(g => g.result), next = sched.filter(g => !g.result && g.status !== 'final').slice(0, 6);

    const NL = nextAndLast(abbr, S, done, cur);
    let h = NL.html + '<section class="qk-section' + (NL.html ? '' : ' rk-sec1') + '">' + QK.sectionHead({ kicker: 'How good are they?', title: 'Where they rank, and where they are heading', sub: 'Each number ranked among the 32 clubs, then form over the season and results against chances.' }) + '<div class="qk-grid">' +
      '<div class="qk-span-5">' + teamCard(abbr, TS) + '</div>' +
      '<div class="qk-span-7"><div class="rk-stack">' + U.card2('Form through the season', 'Rolling 10-game shares at 5v5 (xGF%, CF%) and of all goals (GF%); above 50% the club is on top', U.chart('tp-form', 300, 'Rolling form') +
        QK.note('<b>Which line matters most?</b> The expected-goal share (the thick line) predicts the next games better than the goal share: goals swing on a few bounces, chances much less.')) +
      U.card2('Results v chances', 'Cumulative goal difference against cumulative expected-goal difference, game by game', U.chart('tp-cum', 260, 'Goal difference against expected goal difference') +
        QK.note('<b>Who’s for real?</b> When the solid line runs above the dashed one, the club has done better than its chances suggest. Over a season that gap usually shrinks.')) + '</div></div></div></section>';
    const lo = RK.leagueOpts && RK.ok(sj) ? RK.leagueOpts(sj, S) : null;
    if (lo) h += '<div id="tp-league"></div>';

    if (needs && (needs.grades || []).length) {
      const gr = needs.grades.map(g => '<div class="rk-flex" style="gap:8px;min-width:0"><span class="rk-grade" data-g="' + esc(g.grade) + '">' + esc(g.grade) + '</span><div style="min-width:0"><div style="font-weight:600">' + esc(g.label) + '</div><div class="qk-muted" style="font-size:var(--fs-xs)">' + RK.ordinal(g.rank) + ' of ' + g.n + ' · ' + U.f(g.value, 1) + ' GAR</div></div></div>').join('');
      const str = (needs.strengths || []).map(s => '<li><span class="rk-grade" data-g="' + esc(s.grade) + '">' + esc(s.grade) + '</span><div><b>' + esc(s.label) + '</b><div class="s">' + esc(s.evidence || '') + '</div></div></li>').join('');
      const wk = (needs.weaknesses || []).map(w => '<li style="align-items:flex-start"><span class="rk-grade" data-g="' + esc(w.grade) + '">' + esc(w.grade) + '</span><div style="min-width:0"><b>' + esc(w.label) + '</b><div class="s">' + esc(w.evidence || '') + '</div>' +
        ((w.targets || []).length ? '<div class="s" style="margin-top:4px">Ways to improve: ' + w.targets.slice(0, 3).map(t => '<a class="rk-link" href="' + RK.playerHref(t.id) + '">' + esc(t.name) + '</a> (' + esc(RK.teamAbbr(t.team)) + ', ' + U.signed(t.gain_season, 1) + ' goals a season' + (isNum(t.d_playoffs) ? ', playoffs ' + QK.fmt.pp(t.d_playoffs) : '') + ')').join(', ') + '</div>' : '') + '</div></li>').join('');
      h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Roster strength', title: 'What they do well, and what they need', sub: 'Projected value by position and unit against the other 31 clubs; the players listed under a need are the ones who would help most there.' }) +
        '<div class="qk-grid"><div class="qk-span-4">' + U.card2('Grades', 'A to F against the league', '<div style="display:grid;gap:12px;grid-template-columns:repeat(auto-fill,minmax(150px,1fr))">' + gr + '</div>') + '</div>' +
        '<div class="qk-span-4">' + U.card2('Strengths', '', '<ul class="rk-list">' + str + '</ul>', { flush: true }) + '</div>' +
        '<div class="qk-span-4">' + U.card2('Needs', '', '<ul class="rk-list">' + wk + '</ul>', { flush: true }) + '</div></div>' + (needs.note ? '<p class="rk-note">' + esc(needs.note) + '</p>' : '') + '</section>';
    }
    h += outlook(abbr, M, R, needs);

    h += '<section class="qk-section">' + QK.sectionHead({ kicker: R.current ? 'Today' : RK.seasonLabel(S), title: R.current ? 'Current roster' : 'Roster',
      sub: R.current ? 'Today’s roster (rosters, recalls, trades and injured reserve as of the last refresh), with season numbers, our value (WAR for the rest of this season and over four seasons)' + (M ? ' and each player’s chance of not being in the lineup next season.' : '.') : 'Everyone who played for the club in ' + RK.seasonLabel(S) + '.' }) +
      (M ? U.deadlineLine(M) : '') + '<div class="qk-card">' + (M ? '<div class="rk-keys-row">' + U.moveKeys(M) + '</div>' : '') + '<div id="tp-roster"></div></div></section>';

    h += '<section class="qk-section"><div class="qk-grid"><div class="qk-span-' + (tx ? 7 : 12) + '">' + U.card2(next.length ? 'Coming up, and how it went' : 'How it went', next.length ? 'Next games with our win chance; then results' : 'Results, game by game, with our pre-game win chance', '<div id="tp-sched"></div>', { flush: true, foot: '<span>How sure are we? 60% means the club loses a game like that about 4 times in 10.</span>' }) + '</div>' +
      (tx ? '<div class="qk-span-5">' + U.card2('Recent moves', 'Transactions of the last twelve months (ESPN)', '<div id="tp-moves"></div>', { flush: true, foot: '<span>Trades are graded on Value &amp; Moves</span><a href="#/value?tab=moves&team=' + esc(abbr) + '">All moves →</a>' }) + '</div>' : '') + '</div></section>';
    body.innerHTML = h;
    if (lo) QKL.team(body.querySelector('#tp-league'), Object.assign({}, lo, { meters: false }), abbr);
    fillNext(body, NL.nxt, sj);
    fillLast(body, abbr, NL.last);

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

    // roster leaderboard (+ the chance of not being in the lineup next season)
    const rr = R.rows.slice().sort((p, q) => ((POS_ORDER[p.pos] || 0) - (POS_ORDER[q.pos] || 0)) || ((q.toi_gp || q.mpg || 0) - (p.toi_gp || p.mpg || 0)))
      .map(r => { const m = M ? M.byPid[String(r.id)] : null; return Object.assign({}, r, { mv: m ? m.p_next : null, mvr: m, why: m ? m.why : '', sub: [r.pos, isNum(r.age) ? 'age ' + Math.floor(r.age) : ''].filter(Boolean).join(' · ') }); });
    const cols = [{ key: 'name', label: 'Player', type: 'entity', href: r => RK.playerHref(r.id), sub: 'sub' },
      { key: 'inj', label: 'Status', sort: false, fmt: (v, r) => (v ? '<span class="rk-inj" data-tip="' + esc(v) + '">' + esc(v.split(' · ')[0]) + '</span>' : (r.newc ? QK.tag('new') : '')) },
      { key: 'gp', label: 'GP', num: true }, { key: 'toi_gp', label: 'TOI/GP', num: true, fmt: v => (isNum(v) ? RK.fmtTOI(v, { minutes: true }) : '—') }, { key: 'p', label: 'Pts', num: true, tip: 'Points for this club this season' },
      { key: 'gar', label: 'GAR', num: true, fmt: v => U.f(v, 1), tip: 'Goals above replacement this season (Rink value)' }];
    if (R.current) cols.push({ key: 'now', label: 'WAR rest', type: 'bar', fmt: v => U.f(v, 2), tip: 'Projected wins above replacement for the rest of this season' }, { key: 'total', label: '4-season', num: true, fmt: v => U.f(v, 1), tip: 'Discounted WAR over the rest of this season and the next three' });
    if (M) cols.push({ key: 'mv', label: 'Not in lineup next season', num: true, tip: U.moveTip(M), fmt: (v, r) => U.moveBar(r.mvr, M) + (r.why ? '<span class="rk-why">' + esc(r.why) + '</span>' : '') });
    QK.leaderboard(body.querySelector('#tp-roster'), { columns: cols, rows: rr, dense: true, maxHeight: 680, rowHref: r => RK.playerHref(r.id) });

    // schedule: our chance only (the market is on each game's page)
    const sRows = next.concat(done.slice().reverse()).map(g => ({ g: g, date: g.date, opp: g.opp, res: g.result ? g.result + ' ' + g.gf + '–' + g.ga : '', p: g.p_win, xg: isNum(g.xgf) ? U.f(g.xgf, 1) + '–' + U.f(g.xga, 1) : '' }));
    QK.table(body.querySelector('#tp-sched'), { dense: true, maxHeight: 420, rowHref: r => RK.gameHref(r.g.game_id), columns: [
      { key: 'date', label: 'Date', fmt: (v, r) => '<a href="' + RK.gameHref(r.g.game_id) + '">' + esc(RK.fmtDate(v, { year: false })) + '</a>' },
      { key: 'opp', label: 'Opponent', fmt: (v, r) => '<span class="qk-muted">' + (r.g.home ? 'v' : '@') + '</span> ' + U.teamEnt(v, { abbr: true }) },
      { key: 'res', label: 'Result', fmt: (v, r) => (v ? '<b class="' + (r.g.result === 'W' ? 'pos' : r.g.result === 'L' ? 'neg' : '') + '">' + esc(v) + '</b>' : '<span class="qk-badge">Next</span>') },
      { key: 'p', label: 'Our chance', num: true, fmt: v => (isNum(v) ? '<b class="rk-ours">' + U.pct(v) + '</b>' : '—'), tip: 'Our pre-game win chance' },
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
