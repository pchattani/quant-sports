/* The Quant Bullpen — standings (#/<L>/standings).
 *
 *   Divisions: W-L, GB, runs scored and allowed, run differential, Pythagorean record, our
 *              expected record (from the team ratings), playoff, division, bye and World Series
 *              odds from the season simulation, and division magic numbers;
 *   Wild card: each league's race below the division leaders, with the cut line;
 *   Ratings:   offence, run prevention and pitching in runs per game, and record against
 *              Pythagorean record (luck).
 *
 * Reads <L>/<S>/season.json; when it is not built, a table is computed from schedule.json
 * (final regular-season games) so the page is never empty. BP.standingsRows(season) is shared. */
(function (BP) {
'use strict';

const esc = BP.esc;
const isNum = BP.isNum;
let VIEW = 'div';
let LO = null;      // the league module's options (docs/_design/league.js, QKL) for the season on show, or null
let SIMCOLS = true; // false on a level with no season simulation (Triple-A: index.json levels.aaa.sim is false): no chance columns

/* QKL options from season.json's "league" block (oddsmarkets/baseball/analytics/race.py): the clubs, the race chart's
   groups (divisions, then the two leagues) and the race log (data/<L>/race_log.json through the site's cached loader). */
function leagueOpts(d, L, S) {
  const lg = d && d.league;
  if (!lg || !window.QKL) return null;
  const rows = rowsOf(d), teams = {}, divs = {}, lgs = {};
  Object.keys(rows).forEach(t => {
    const r = rows[t];
    if (BP.teamInfo(t).placeholder) return;
    teams[t] = { abbr: BP.teamAbbr(t), name: BP.teamName(t), colour: BP.teamColourRaw(t), href: BP.teamHref(t, L, S) };
    if (r.division) (divs[r.division] = divs[r.division] || []).push(t);
    if (r.league) (lgs[r.league] = lgs[r.league] || []).push(t);
  });
  const order = (a, b) => { const ia = BP.DIVISIONS.indexOf(a), ib = BP.DIVISIONS.indexOf(b); return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.localeCompare(b); };
  const groups = Object.keys(divs).sort(order).map(k => ({ key: k, label: k, teams: divs[k] }))
    .concat(Object.keys(lgs).sort().map(k => ({ key: 'lg:' + k, label: k, teams: lgs[k] })));
  /* the chart opens on the postseason race (the story of a finished regular season); movers and swings follow the
     block's own metric (the World Series once the field is set) */
  const metric = (lg.metrics || []).some(m => m.key === 'p_postseason') ? 'p_postseason' : undefined;
  return { league: lg, teams: teams, groups: groups, season: String(S), loadLog: () => BP.loadLevel('race_log.json', L),
    title: 'How the races are shaping up', unitGames: 'games', metric: metric };
}
BP.leagueOpts = leagueOpts;

/* season.json -> {tid: row} merging standings, simulation, ratings and magic numbers. Accepts
 * standings as [row], {divisions: [{name, teams: [row]}]} or {tid: row}; the simulation under
 * sim.teams / regular.teams / sim. */
function rowsOf(season) {
  const out = {};
  const s = season || {};
  const put = (t, x, extra) => { if (!t) return; out[String(t)] = Object.assign(out[String(t)] || { tid: String(t) }, x || {}, extra || {}); };
  const st = s.standings;
  if (Array.isArray(st)) st.forEach(r => put(r.tid || r.team || r.id, r));
  else if (st && Array.isArray(st.divisions)) st.divisions.forEach(d => (d.teams || []).forEach(r => put(r.tid || r.team, r, { division: r.division || d.name, league: r.league || d.league })));
  else if (st && typeof st === 'object') Object.keys(st).forEach(k => {
    const v = st[k];
    if (Array.isArray(v)) v.forEach(r => put(r.tid || r.team, r, { division: r.division || k }));
    else if (v && typeof v === 'object') put(k, v);
  });
  const sim = (s.sim && s.sim.teams) || (s.regular && s.regular.teams) || (s.regular_season && s.regular_season.teams) || null;
  if (sim) Object.keys(sim).forEach(t => {
    const x = sim[t] || {};
    const cur = out[String(t)] || {};
    put(t, { sim: x, exp_w_final: x.exp_w, magic: x.magic || cur.magic, league: cur.league || x.league, division: cur.division || x.division,
      w: isNum(cur.w) ? cur.w : x.w_now, l: isNum(cur.l) ? cur.l : x.l_now });
  });
  const rt = s.ratings || {};
  Object.keys(rt).forEach(t => {
    const x = rt[t] || {};
    if (out[String(t)]) out[String(t)].rating = { off: x.off, def: x.def, pitch: isNum(x.pitch) ? x.pitch : x.pit, net: isNum(x.net) ? x.net : x.total };
  });
  Object.keys(out).forEach(t => {
    const r = out[t];
    const info = BP.teamInfo(t);
    r.league = r.league || info.league || '';
    r.division = r.division || info.division || '';
    const g = (r.w || 0) + (r.l || 0);
    if (!isNum(r.pct) && g) r.pct = r.w / g;
    // odds written on the row itself (the build) rather than under sim
    if (!r.sim && ['p_postseason', 'p_division', 'p_ws', 'p_bye', 'p_wildcard'].some(k => isNum(r[k]))) r.sim = r;
    if (isNum(r.pythag_w) && !isNum(r.pythag_l) && g) r.pythag_l = g - r.pythag_w;
    if (isNum(r.exp_w) && !isNum(r.exp_l) && g) r.exp_l = g - r.exp_w;
    if (!r.rating && (isNum(r.off) || isNum(r.def))) r.rating = { off: r.off, def: r.def, pitch: r.pit, net: isNum(r.rating) ? r.rating : null };
    if (!isNum(r.rd) && isNum(r.rs) && isNum(r.ra)) r.rd = r.rs - r.ra;
    if (!isNum(r.pythag_w) && isNum(r.rs) && isNum(r.ra) && g && r.rs + r.ra > 0) {
      const e = 1.83, p = Math.pow(r.rs, e) / (Math.pow(r.rs, e) + Math.pow(r.ra, e));
      r.pythag_w = p * g; r.pythag_l = g - p * g;
    }
  });
  return out;
}
/* Fallback: a table from the final regular-season games in schedule.json. */
function fromSchedule(sched) {
  const out = {};
  const games = sched && Array.isArray(sched.games) ? sched.games : [];
  games.forEach(g => {
    if (!BP.isFinal(g) || (g.gtype && g.gtype !== 'R') || !isNum(g.hs) || !isNum(g.as)) return;
    [[g.home, g.hs, g.as], [g.away, g.as, g.hs]].forEach(x => {
      const r = out[x[0]] = out[x[0]] || { tid: String(x[0]), w: 0, l: 0, rs: 0, ra: 0 };
      r.rs += x[1]; r.ra += x[2];
      if (x[1] > x[2]) r.w++; else r.l++;
    });
  });
  return rowsOf({ standings: Object.keys(out).map(k => out[k]) });
}
function gbOf(rows) {
  if (!rows.length) return;
  const lead = rows[0];
  rows.forEach(r => { if (!isNum(r.gb)) r.gb_calc = ((lead.w - r.w) + (r.l - lead.l)) / 2; });
}
function fmtGB(r) {
  const v = isNum(r.gb) ? Number(r.gb) : r.gb_calc;
  return !isNum(v) || v === 0 ? '—' : (v % 1 ? v.toFixed(1) : String(v));
}
function clinch(r) {
  const s = r.sim || {}, m = r.magic || {};
  const c = String(r.clinched || '');
  if (c) return '<span class="clinch" title="Clinched">' + esc(c.length <= 2 ? c : c.charAt(0)) + '</span>';
  if (r.div_winner && isNum(r.seed) && r.seed <= 2) return '<span class="clinch" title="Division winner with a bye (seed ' + r.seed + ')">z</span>';
  if (m.clinched_division || s.p_division === 1 || r.div_winner) return '<span class="clinch" title="Clinched the division">y</span>';
  if (s.p_postseason === 1) return '<span class="clinch" title="Clinched a postseason place">x</span>';
  if (s.p_postseason === 0 && isNum(s.p_postseason)) return '<span class="clinch out" title="Eliminated">e</span>';
  return '';
}
function oddsCell(p) {
  if (!isNum(p)) return { v: null, html: '<span class="muted-inline">—</span>', align: 'right' };
  const x = Number(p);
  return { v: x, html: x >= 0.9995 ? '<span class="odds-done">✓</span>' : x <= 0.0005 ? '<span class="muted-inline">0</span>' : BP.probCell(x, BP.C.clay), align: 'right' };
}
function magicCell(r) {
  const m = r.magic || {};
  if (m.clinched_division) return { v: -1, html: '<span class="edge-pos">clinched</span>' };
  if (m.eliminated_division) return { v: 999, html: '<span class="muted-inline">out</span>' };
  if (isNum(m.division_magic)) return { v: m.division_magic, html: '<b>' + m.division_magic + '</b>', title: 'Division magic number' };
  if (isNum(m.division_tragic)) return { v: 500 + m.division_tragic, html: '<span class="muted-inline">' + m.division_tragic + ' tragic</span>' };
  return { v: null, html: '—' };
}

function teamCell(r, L, S) {
  return { v: BP.teamName(r.tid), html: (LO ? QKL.toggle(r.tid, BP.teamName(r.tid)) : '') + BP.teamLink(r.tid, { short: true, level: L, season: S }) + clinch(r) };
}
/* the club's first chip ("Bullpen is the weak spot"); + under the club opens the full card */
function profileCell(r) {
  return { v: '', html: (LO && QKL.chip(LO, r.tid)) || '<span class="muted-inline">—</span>', cls: 'hide-sm' };
}
const PROFILE_COL = { label: 'Profile', sortable: false, cls: 'hide-sm', title: 'What stands out about the club; + opens its card (strengths, weaknesses and the race)' };
function divisionTable(list, L, S) {
  gbOf(list);
  const rows = list.map(r => {
    const s = r.sim || {};
    const g = (r.w || 0) + (r.l || 0);
    const luck = isNum(r.pythag_w) ? r.w - r.pythag_w : null;
    const ew = isNum(r.exp_w) ? r.exp_w : null, el = isNum(r.exp_l) ? r.exp_l : (isNum(ew) && g ? g - ew : null);
    return { cells: [teamCell(r, L, S), { v: r.w, html: esc(r.w) }, { v: r.l, html: esc(r.l) }, { v: r.pct, html: BP.fmtAvg(r.pct) },
      { v: isNum(r.gb) ? r.gb : r.gb_calc, html: fmtGB(r) },
      { v: r.rs, html: esc(isNum(r.rs) ? r.rs : '—'), cls: 'hide-sm' }, { v: r.ra, html: esc(isNum(r.ra) ? r.ra : '—'), cls: 'hide-sm' },
      { v: r.rd, html: isNum(r.rd) ? '<span class="' + (r.rd > 0 ? 'edge-pos' : r.rd < 0 ? 'edge-neg' : '') + '">' + BP.signed(r.rd, 0) + '</span>' : '—' },
      { v: r.pythag_w, html: isNum(r.pythag_w) ? BP.record(r.pythag_w, r.pythag_l) + (isNum(luck) && Math.abs(luck) >= 3 ? ' <span class="' + (luck > 0 ? 'edge-pos' : 'edge-neg') + '" title="Wins above Pythagorean record">' + BP.signed(luck, 0) + '</span>' : '') : '—', cls: 'hide-sm' },
      { v: ew, html: isNum(ew) ? BP.record(ew, el) : '—', cls: 'hide-sm', title: 'Expected record from our team ratings (offence, defence, pitching)' }]
      .concat(SIMCOLS ? [oddsCell(s.p_postseason), Object.assign(oddsCell(s.p_division), { cls: 'hide-sm' }), Object.assign(oddsCell(s.p_bye), { cls: 'hide-sm' }), oddsCell(s.p_ws),
        Object.assign(magicCell(r), { align: 'right', cls: 'hide-sm' })] : []).concat(LO ? [profileCell(r)] : []) };
  });
  return BP.tableHTML([{ label: 'Team' }, { label: 'W', align: 'right' }, { label: 'L', align: 'right' }, { label: 'Pct', align: 'right' }, { label: 'GB', align: 'right' },
    { label: 'RS', align: 'right', cls: 'hide-sm' }, { label: 'RA', align: 'right', cls: 'hide-sm' }, { label: 'Diff', align: 'right' },
    { label: 'Pythag', align: 'right', cls: 'hide-sm', title: 'Pythagorean record from runs scored and allowed (exponent 1.83); the figure is wins above it' },
    { label: 'Expected', align: 'right', cls: 'hide-sm', title: 'Our expected record from the team ratings' }]
    .concat(SIMCOLS ? [{ label: 'Playoffs', align: 'right', title: 'Our chance of a postseason place (season simulation)' }, { label: 'Division', align: 'right', cls: 'hide-sm' },
      { label: 'Bye', align: 'right', cls: 'hide-sm', title: 'A top-two seed: straight to the Division Series' }, { label: 'WS', align: 'right', title: 'Our World Series chance' },
      { label: 'Magic', align: 'right', cls: 'hide-sm', title: 'Division magic number: wins plus rival losses to clinch' }] : []).concat(LO ? [PROFILE_COL] : []), rows, { compact: true, cls: 'std-table' });
}
function wildcardTable(list, L, S) {
  // the division leaders sit out; the rest are ranked by win percentage, the cut after the third
  const byDiv = {};
  list.forEach(r => { (byDiv[r.division] = byDiv[r.division] || []).push(r); });
  const leaders = {};
  Object.keys(byDiv).forEach(d => { byDiv[d].sort((a, b) => b.pct - a.pct); if (byDiv[d][0]) leaders[byDiv[d][0].tid] = 1; });
  const lead = list.filter(r => leaders[r.tid]).sort((a, b) => b.pct - a.pct);
  const rest = list.filter(r => !leaders[r.tid]).sort((a, b) => b.pct - a.pct);
  const cut = rest[2], first = rest[3];
  const row = (r, k, isLead) => {
    const s = r.sim || {};
    const wgb = isLead || !cut ? null : ((cut.w - r.w) + (r.l - cut.l)) / 2;
    return { _class: !isLead && k === 2 ? 'wc-cut' : '', cells: [{ v: k, html: isLead ? '<span class="muted-inline">' + (k + 1) + '</span>' : String(k + 4) }, teamCell(r, L, S),
      { v: r.w, html: esc(r.w) }, { v: r.l, html: esc(r.l) }, { v: r.pct, html: BP.fmtAvg(r.pct) },
      { v: wgb, html: isLead ? '<span class="muted-inline">leader</span>' : (k < 3 ? (first ? '+' + (((r.w - first.w) + (first.l - r.l)) / 2) : '—') : (isNum(wgb) ? String(wgb) : '—')) },
      { v: r.rd, html: isNum(r.rd) ? BP.signed(r.rd, 0) : '—', cls: 'hide-sm' }, oddsCell(s.p_postseason), oddsCell(s.p_wildcard), oddsCell(s.p_ws)].concat(LO ? [profileCell(r)] : []) };
  };
  return BP.tableHTML([{ label: 'Seed', sortable: false }, { label: 'Team' }, { label: 'W', align: 'right' }, { label: 'L', align: 'right' }, { label: 'Pct', align: 'right' },
    { label: 'WCGB', align: 'right', title: 'Games ahead of / behind the third wild card' }, { label: 'Diff', align: 'right', cls: 'hide-sm' },
    { label: 'Playoffs', align: 'right' }, { label: 'Wild card', align: 'right' }, { label: 'WS', align: 'right' }].concat(LO ? [PROFILE_COL] : []),
  lead.map((r, k) => row(r, k, true)).concat(rest.map((r, k) => row(r, k, false))), { compact: true, cls: 'std-table' }) +
    '<div class="section-note">Division leaders first (seeds 1–3 by record, the top two with a bye), then the wild-card race: the dashed line is the cut after the third wild card.</div>';
}
function ratingsPanel(el, all, L, S) {
  const list = all.filter(r => r.rating || isNum(r.pythag_w));
  const rows = list.map(r => {
    const t = r.rating || {};
    const luck = isNum(r.pythag_w) ? r.w - r.pythag_w : null;
    return [teamCell(r, L, S), { v: t.off, html: isNum(t.off) ? BP.signed(t.off, 2) : '—' }, { v: t.def, html: isNum(t.def) ? BP.signed(t.def, 2) : '—' },
      { v: t.pitch, html: isNum(t.pitch) ? BP.signed(t.pitch, 2) : '—', cls: 'hide-sm' }, { v: t.net, html: isNum(t.net) ? '<b>' + BP.signed(t.net, 2) + '</b>' : '—' },
      { v: r.w, html: BP.record(r.w, r.l) }, { v: r.pythag_w, html: isNum(r.pythag_w) ? BP.record(r.pythag_w, r.pythag_l) : '—', cls: 'hide-sm' },
      { v: luck, html: isNum(luck) ? '<span class="' + (luck > 0 ? 'edge-pos' : luck < 0 ? 'edge-neg' : '') + '">' + BP.signed(luck, 1) + '</span>' : '—' }];
  });
  el.innerHTML = '<div class="grid-23 pad0 std-rt"><div><div id="std-luck" class="chart-box"></div><div class="chart-note">Wins against Pythagorean wins: above the line, the record beats the run differential.</div></div><div>' +
    BP.tableHTML([{ label: 'Team' }, { label: 'Offence', align: 'right', title: 'Runs per game above average, batting and baserunning' }, { label: 'Defence', align: 'right', title: 'Runs per game saved, fielding and framing' },
      { label: 'Pitching', align: 'right', cls: 'hide-sm', title: 'Runs per game saved by the staff' }, { label: 'Net', align: 'right' }, { label: 'Record', align: 'right' },
      { label: 'Pythag', align: 'right', cls: 'hide-sm' }, { label: 'Luck', align: 'right', title: 'Wins above Pythagorean' }], rows, { compact: true }) + '</div></div>';
  const pts = list.filter(r => isNum(r.pythag_w));
  if (pts.length) {
    const lo = Math.min.apply(null, pts.map(r => Math.min(r.w, r.pythag_w))) - 3, hi = Math.max.apply(null, pts.map(r => Math.max(r.w, r.pythag_w))) + 3;
    BP.plot('std-luck', [{ type: 'scatter', mode: 'markers+text', x: pts.map(r => r.pythag_w), y: pts.map(r => r.w), text: pts.map(r => BP.teamAbbr(r.tid)), textposition: 'top center',
      textfont: { size: 9, color: BP.C.text2 }, marker: { size: 10, color: pts.map(r => BP.teamColour(r.tid)), line: { width: 1, color: '#0d1117' } },
      hovertext: pts.map(r => esc(BP.teamName(r.tid)) + '<br>' + r.w + ' wins · Pythag ' + BP.num(r.pythag_w, 1)), hoverinfo: 'text' }], BP.layout({
      height: 400, shapes: [{ type: 'line', x0: lo, y0: lo, x1: hi, y1: hi, line: { color: '#30363d', dash: 'dash' } }],
      xaxis: { title: 'Pythagorean wins', range: [lo, hi] }, yaxis: { title: 'Wins', range: [lo, hi] }, margin: { l: 50, r: 10, t: 10, b: 45 } }));
  }
  BP.sortable(el);
}

function render(el, params) {
  const L = params.level, S = params.season;
  const simOn = BP.levelInfo(L).sim !== false;
  el.innerHTML = QK.sectionHead({ kicker: 'Standings · ' + BP.levelName(L) + ' ' + S, title: 'The table', sub: 'Records, run differential, Pythagorean and expected records' + (simOn ? ', and our chances from the season simulation.' : '.'),
    actions: '<a class="qk-btn" href="' + BP.ghref('postseason') + '">Postseason</a><a class="qk-btn" href="' + BP.href('teams', L, S) + '">Teams</a>' }) +
    QK.note('<b>Pythagorean</b> is the record a club’s runs scored and allowed usually buy; a gap to the real record is mostly close-game luck. ' + (simOn ? '<b>Postseason 60%</b> means the club made it in about 6 of every 10 simulated seasons.' : '')) + '<div id="std-body">' + QK.skeleton('card', 2) + '</div>';
  return BP.loadYear('season.json', L, S).then(d => {
    if (!el.isConnected) return null;
    if (BP.ok(d) && (d.standings || d.sim)) return { d: d, rows: rowsOf(d) };
    return BP.loadYear('schedule.json', L, S).then(sc => ({ d: d, rows: fromSchedule(sc), fallback: true }));
  }).then(res => {
    if (!res || !el.isConnected) return;
    const body = document.getElementById('std-body');
    const all = Object.keys(res.rows).map(t => res.rows[t]).filter(r => !BP.teamInfo(r.tid).placeholder);
    if (!all.length) { body.innerHTML = BP.card('Standings', '', BP.notBuilt('The ' + S + ' standings', res.d)); return; }
    const leagues = [];
    all.forEach(r => { if (leagues.indexOf(r.league) < 0) leagues.push(r.league); });
    leagues.sort();
    const divs = {};
    all.forEach(r => { (divs[r.division] = divs[r.division] || []).push(r); });
    const divOrder = Object.keys(divs).sort((a, b) => { const ia = BP.DIVISIONS.indexOf(a), ib = BP.DIVISIONS.indexOf(b); return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.localeCompare(b); });
    const d = res.d || {};
    LO = res.fallback ? null : leagueOpts(d, L, S);
    SIMCOLS = BP.levelInfo(L).sim !== false;
    if (!SIMCOLS && VIEW === 'wc') VIEW = 'div';
    const draw = () => {
      const box = document.getElementById('std-view');
      if (VIEW === 'div') {
        box.innerHTML = '<div class="std-grid">' + leagues.map(lg => '<div>' + divOrder.filter(dv => divs[dv][0].league === lg).map(dv => {
          const list = divs[dv].slice().sort((a, b) => (isNum(a.div_rank) && isNum(b.div_rank) ? a.div_rank - b.div_rank : b.pct - a.pct));
          return BP.card(dv || lg, '', divisionTable(list, L, S));
        }).join('') + '</div>').join('') + '</div>';
      } else if (VIEW === 'wc') {
        box.innerHTML = '<div class="std-grid">' + leagues.map(lg => BP.card((lg || 'League') + ' postseason race', 'division leaders, then the wild cards', wildcardTable(all.filter(r => r.league === lg), L, S))).join('') + '</div>';
      } else {
        box.innerHTML = BP.card('Team ratings', 'runs per game against an average team', '<div id="std-rt"></div>');
        ratingsPanel(document.getElementById('std-rt'), all, L, S);
      }
      BP.sortable(box);
    };
    const best = all.slice().sort((a, b) => (b.pct || 0) - (a.pct || 0))[0];
    const rdb = all.filter(r => isNum(r.rd)).sort((a, b) => b.rd - a.rd)[0];
    const lk = all.filter(r => isNum(r.pythag_w)).map(r => ({ r: r, v: r.w - r.pythag_w })).sort((a, b) => b.v - a.v)[0];
    const wsf = all.filter(r => r.sim && isNum(r.sim.p_ws)).sort((a, b) => b.sim.p_ws - a.sim.p_ws)[0];
    const tiles = [];
    /* round 11: a decided World Series shows its champion, never a favourite at 100% */
    const champ = L === 'mlb' && d.postseason ? BP.charts.champOf(d.postseason) : null;
    if (champ) tiles.push({ label: 'World Series champions', value: BP.teamAbbr(champ), signal: true, sub: BP.teamName(champ), href: BP.teamHref(champ, L, S) });
    else if (wsf && wsf.sim.p_ws > 0) tiles.push({ label: 'World Series favourite', value: BP.teamAbbr(wsf.tid) + ' ' + BP.ui.pct(wsf.sim.p_ws), signal: true, sub: 'our chance, season simulation', href: BP.teamHref(wsf.tid, L, S) });
    if (best) tiles.push({ label: 'Best record', value: BP.teamAbbr(best.tid) + ' ' + best.w + '-' + best.l, sub: BP.fmtAvg(best.pct), href: BP.teamHref(best.tid, L, S) });
    if (rdb) tiles.push({ label: 'Best run differential', value: BP.teamAbbr(rdb.tid) + ' ' + BP.ui.signed(rdb.rd, 0), sub: rdb.rs + ' scored, ' + rdb.ra + ' allowed', href: BP.teamHref(rdb.tid, L, S) });
    if (lk) tiles.push({ label: 'Luckiest', value: BP.teamAbbr(lk.r.tid) + ' ' + BP.ui.signed(lk.v, 1), sub: 'wins above the Pythagorean record', href: BP.teamHref(lk.r.tid, L, S) });
    const tabs = [{ key: 'div', label: 'Divisions' }].concat(SIMCOLS ? [{ key: 'wc', label: 'Wild card' }] : []).concat([{ key: 'rt', label: 'Ratings and luck' }]);
    body.innerHTML = (tiles.length ? '<div class="bp-kpis">' + QK.stats(tiles) + '</div>' : '') + '<div class="toggle-row std-tabs" id="std-tabs">' + BP.toggles(tabs, VIEW, 'data-v') + '</div>' +
      '<div id="std-view"></div>' + (LO ? '<div id="std-shape"></div>' : '') +
      '<p class="qk-sub bp-moved">' + (SIMCOLS && L === 'mlb' ? 'Our chances over the season, division by division, are on <a class="qk-link" href="' + BP.href('chances', L, S) + '">Chances</a>. ' : '') +
      'The players leading and trailing at every position are in the <a class="qk-link" href="' + BP.href('scout', L, S) + '?view=leaders">Scouting Room’s Leaders</a>.</p>' +
      '<div class="section-note">' + (res.fallback ? 'Computed from the final regular-season games while the season payload is built; our chances and expected records arrive with it. ' : '') +
      (SIMCOLS ? 'Chances: ' + (d.sim && (d.sim.n_sims || d.sim.sims) ? BP.int(d.sim.n_sims || d.sim.sims) + ' ' : '') + 'simulations of the rest of the season and the bracket from our team ratings (x: clinched a place, y: the division, z: the division and a bye, e: eliminated). ' :
        'We do not simulate the Triple-A season, so the table shows records, run differential and our team ratings only. ') +
      'Pythagorean records use exponent 1.83.' + (SIMCOLS ? ' Magic numbers count wins plus division-rival losses to clinch.' : '') + '</div>';
    BP.wireToggles(document.getElementById('std-tabs'), 'data-v', k => { VIEW = k; draw(); });
    draw();
    if (LO) {
      QKL.wire(document.getElementById('std-view'), LO);
      QKL.shape(document.getElementById('std-shape'), LO);
    }
    BP.setMeta(d.updated_at ? 'Season data ' + esc(BP.fmtStamp(d.updated_at)) : '');
  });
}

/* ── Chances (#/mlb/chances, round 9): the season simulation's boards in one tab ────────────────────────────────
   The title race (World Series), each league's postseason or pennant race, the division boards with the projected wins
   and their 80% range, the seed distribution, and our chances day by day (QKL.race on race_log.json). A finished season
   shows what happened and the race as it ran; Triple-A has no simulation. */
function chancesView(el, params) {
  const L = params.level, S = params.season;
  el.innerHTML = QK.sectionHead({ kicker: 'Chances · ' + BP.levelName(L) + ' ' + S, title: 'Who wins it all?', sub: 'Our chances from simulating the rest of the season and the bracket 20,000 times: the title, the postseason, each division, the seeds, and how the race has moved.' }) +
    '<div id="ch-body">' + QK.skeleton('card', 2) + '</div>';
  if (BP.levelInfo(L).sim === false) {
    document.getElementById('ch-body').innerHTML = QK.empty('No simulation for Triple-A', 'We simulate the major-league season and bracket only. The Triple-A table and the league finals are on the Table and Bracket tabs.');
    return null;
  }
  return BP.loadYear('season.json', L, S).then(d => {
    const body = document.getElementById('ch-body');
    if (!body || !el.isConnected) return;
    if (!BP.ok(d)) { body.innerHTML = QK.empty('Not built yet', 'The ' + S + ' season file is not available.'); return; }
    const rows = rowsOf(d), all = Object.keys(rows).map(t => rows[t]).filter(r => !BP.teamInfo(r.tid).placeholder);
    const post = d.postseason || {}, pt = post.teams || {};
    const actual = !!post.actual || !(d.sim && d.sim.available) || !!BP.charts.champOf(post);
    const lo = leagueOpts(d, L, S);
    const team = t => ({ label: BP.teamShort(t), href: BP.teamHref(t, L, S), mark: BP.ui.team(t, L, S), color: BP.ui.raw(t) });
    const P = (r, k) => { const s = r.sim || r; return isNum(s[k]) ? s[k] : (pt[r.tid] && isNum(pt[r.tid][k]) ? pt[r.tid][k] : null); };
    let h = '';
    if (actual) {
      const ch = BP.charts.champOf(post);
      h += QK.explain((ch ? '<b>' + esc(BP.teamName(ch)) + ' won the ' + S + ' World Series.</b> ' : '') + 'This season is over, so its chances are history: the race below shows how our numbers moved through the year, and the <a class="qk-link" href="' + BP.ghref('postseason', S) + '">Bracket</a> has every series as it was played.', { title: 'A finished season' });
    } else {
      const ws = all.filter(r => isNum(P(r, 'p_ws')) && P(r, 'p_ws') > 0.0005).sort((a, b) => P(b, 'p_ws') - P(a, 'p_ws'));
      const w0 = ws[0];
      const tiles = [];
      if (w0) tiles.push({ label: 'Title favourite', value: BP.teamAbbr(w0.tid) + ' ' + BP.ui.pct(P(w0, 'p_ws')), signal: true, sub: P(w0, 'p_ws') < 0.2 ? 'nobody is better than 1 in 5' : 'about ' + Math.round(10 * P(w0, 'p_ws')) + ' in 10 simulated brackets', href: BP.teamHref(w0.tid, L, S) });
      const alive = all.filter(r => isNum(P(r, 'p_ws')) && P(r, 'p_ws') > 0.0005).length;
      tiles.push({ label: 'Still alive', value: String(alive), sub: 'clubs with a World Series chance' });
      if (d.sim && (d.sim.sims || d.sim.n_sims)) tiles.push({ label: 'Simulations', value: QK.fmt.num(d.sim.sims || d.sim.n_sims), sub: d.sim.kind === 'postseason' ? 'brackets, every remaining game played out' : 'seasons, every remaining game and the bracket' });
      h += '<div class="bp-kpis">' + QK.stats(tiles) + '</div>';
      h += '<section class="qk-section"><div class="qk-grid"><div class="qk-span-6">' + BP.ui.card2('World Series', 'Our chance of winning it all', QK.chances(ws.slice(0, 12).map(r => Object.assign(team(r.tid), { p: P(r, 'p_ws') })), { key: false })) + '</div>';
      const inPost = d.sim && d.sim.kind === 'postseason';
      const key2 = inPost ? 'p_pennant' : 'p_postseason';
      const lgs = Array.from(new Set(all.map(r => r.league).filter(Boolean))).sort();
      h += '<div class="qk-span-6">' + lgs.map(lg => {
        const list = all.filter(r => r.league === lg && isNum(P(r, key2)) && P(r, key2) > 0.0005).sort((a, b) => P(b, key2) - P(a, key2)).slice(0, inPost ? 6 : 9);
        const won = inPost && list.length === 1 && P(list[0], key2) >= 0.9995 ? list[0] : null;
        return BP.ui.card2(lg + (inPost ? ' pennant' : ' postseason'), inPost ? 'Our chance of reaching the World Series' : 'Our chance of a place in October',
          won ? '<p class="bp-decided">' + BP.ui.teamEnt(won.tid, L, S) + ' won the ' + esc(lg) + ' pennant.</p>' : list.length ? QK.chances(list.map(r => Object.assign(team(r.tid), { p: P(r, key2) })), { key: false }) : QK.empty('Decided', 'Every place is settled.'));
      }).join('') + '</div></div></section>';
      if (!inPost && all.some(r => isNum(P(r, 'p_division')))) {
        const divs = {};
        all.forEach(r => { (divs[r.division] = divs[r.division] || []).push(r); });
        const order = Object.keys(divs).sort((a, b) => { const ia = BP.DIVISIONS.indexOf(a), ib = BP.DIVISIONS.indexOf(b); return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.localeCompare(b); });
        h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Divisions', title: 'Every division race', sub: 'Our chance of winning the division, a bye and a place in October, and the wins we expect with the middle 90% of the simulations.' }) +
          '<div class="qk-grid">' + order.map(dv => '<div class="qk-span-6">' + BP.ui.card2(dv, '', '<div id="ch-dv-' + esc(dv.replace(/\W+/g, '')) + '"></div>', { flush: true }) + '</div>').join('') + '</div></section>';
        h += '<section class="qk-section">' + BP.ui.card2('Projected wins', 'The average of the simulations (dot) and the middle 90% (bar), every club', '<div id="ch-wins" class="qk-chart" style="height:' + Math.max(420, 18 * all.length) + 'px"></div>') + '</section>';
        body.innerHTML = h + (lo && (lo.league.metrics || []).length ? '<section class="qk-section" id="ch-race"></section>' : '');
        order.forEach(dv => {
          const host = document.getElementById('ch-dv-' + dv.replace(/\W+/g, ''));
          const list = divs[dv].slice().sort((a, b) => (P(b, 'p_division') || 0) - (P(a, 'p_division') || 0));
          QK.leaderboard(host, { dense: true, columns: [{ key: 'name', label: 'Club', type: 'entity', mark: o => BP.ui.team(o.t, L, S), href: o => BP.teamHref(o.t, L, S) },
            { key: 'w', label: 'Proj. W', num: true, fmt: v => (isNum(v) ? v.toFixed(0) : '—') }, { key: 'div', label: 'Division', type: 'bar', fmt: v => BP.ui.pct(v) },
            { key: 'bye', label: 'Bye', num: true, fmt: v => BP.ui.pct(v) }, { key: 'po', label: 'Postseason', num: true, fmt: v => BP.ui.pct(v) }],
          rows: list.map(r => ({ t: r.tid, name: BP.teamShort(r.tid), w: isNum(r.proj_w) ? r.proj_w : r.exp_w_final, div: P(r, 'p_division'), bye: P(r, 'p_bye'), po: P(r, 'p_postseason') })) });
        });
        const pw = all.filter(r => isNum(r.proj_w) || isNum(r.exp_w_final)).sort((a, b) => (b.proj_w || b.exp_w_final) - (a.proj_w || a.exp_w_final));
        winsChart(pw, L);
      } else body.innerHTML = h + (lo && (lo.league.metrics || []).length ? '<section class="qk-section" id="ch-race"></section>' : '');
    }
    if (actual) body.innerHTML = h + (lo && (lo.league.metrics || []).length ? '<section class="qk-section" id="ch-race"></section>' : '<p class="bp-note">No day-by-day record of our chances for ' + esc(S) + '.</p>');
    const rh = document.getElementById('ch-race');
    if (rh && lo) { rh.innerHTML = '<div id="ch-race-c"></div>'; QKL.race(document.getElementById('ch-race-c'), lo); }
    /* round 9 (Phase 4): once the regular season is over, next season's standings as the rosters stand */
    const over = actual || /post|off|complete/.test(String(d.phase || ''));
    if (over && Number(S) === BP.currentSeason(L)) nextSeason(body, L, S, all);
    BP.setMeta(d.updated_at ? 'Season data ' + esc(BP.fmtStamp(d.updated_at)) : '');
  });
}
/* Next season as the rosters stand (round 9, Phase 4): every player's expected WAR next season from the five-season
   projections (value.json "e1", valuation v2; "proj" where it is missing), summed by the club the player is with now, and
   set against the league average (81 wins; a win of WAR is a win). Before free agency, trades and signings: a snapshot of
   the rosters, not a forecast of next year's clubs. */
function nextSeason(body, L, S, all) {
  BP.loadYear('value.json', L, S).then(v => {
    if (!body.isConnected || !BP.ok(v) || !Array.isArray(v.rows)) return;
    const F = {};
    (v.fields || []).forEach((f, i) => { F[f] = i; });
    if (F.team === undefined || (F.e1 === undefined && F.proj === undefined)) return;
    const tot = {}, top = {};
    v.rows.forEach(r => {
      const t = String(r[F.team] || ''), x = F.e1 !== undefined && isNum(r[F.e1]) ? r[F.e1] : (F.proj !== undefined ? r[F.proj] : null);
      if (!t || !isNum(x)) return;
      tot[t] = (tot[t] || 0) + x;
      (top[t] = top[t] || []).push([r[F.name], x]);
    });
    const ids = all.map(r => r.tid).filter(t => isNum(tot[t]));
    if (ids.length < 20) return;
    const mean = ids.reduce((a, t) => a + tot[t], 0) / ids.length;
    const W = t => 81 + (tot[t] - mean);
    const divs = {};
    all.forEach(r => { if (isNum(tot[r.tid])) (divs[r.division] = divs[r.division] || []).push(r); });
    const order = Object.keys(divs).sort((a, b) => { const ia = BP.DIVISIONS.indexOf(a), ib = BP.DIVISIONS.indexOf(b); return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.localeCompare(b); });
    const best = ids.slice().sort((a, b) => W(b) - W(a))[0];
    const sec = document.createElement('section');
    sec.className = 'qk-section';
    sec.innerHTML = QK.sectionHead({ kicker: 'Next season', title: (Number(S) + 1) + ' as the rosters stand', sub: 'Every player’s expected WAR next season from our five-season projections, summed by the club they are with today and set against an average club (81 wins). Before free agency, trades and signings: the starting point of the winter, not a forecast of who wins.' }) +
      '<div class="bp-kpis">' + QK.stats([{ label: 'Strongest roster for ' + (Number(S) + 1), value: BP.teamAbbr(best) + ' ' + Math.round(W(best)), signal: true, sub: 'projected wins, ' + BP.ui.signed(tot[best], 1) + ' WAR', href: BP.teamHref(best, L, S) }]) + '</div>' +
      '<div class="qk-grid">' + order.map(dv => '<div class="qk-span-6">' + BP.ui.card2(dv, 'Projected ' + (Number(S) + 1) + ' wins', '<div id="nx-' + esc(dv.replace(/\W+/g, '')) + '"></div>', { flush: true }) + '</div>').join('') + '</div>';
    body.appendChild(sec);
    order.forEach(dv => {
      const host = document.getElementById('nx-' + dv.replace(/\W+/g, ''));
      const list = divs[dv].slice().sort((a, b) => W(b.tid) - W(a.tid));
      QK.leaderboard(host, { dense: true, rank: true, columns: [{ key: 'name', label: 'Club', type: 'entity', sub: 'sub', mark: o => BP.ui.team(o.t, L, S), href: o => BP.teamHref(o.t, L, S) },
        { key: 'w', label: 'Proj. W–L', num: true, fmt: (x, o) => Math.round(x) + '–' + (162 - Math.round(x)) }, { key: 'war', label: 'Roster WAR', num: true, fmt: x => BP.ui.signed(x, 1) },
        { key: 'now', label: (S) + ' W–L', num: true, fmt: (x, o) => o.rec }],
      rows: list.map(r => { const tp = (top[r.tid] || []).sort((a, b) => b[1] - a[1]).slice(0, 2).map(x => x[0]).join(', '); return { t: r.tid, name: BP.teamShort(r.tid), sub: tp, w: W(r.tid), war: tot[r.tid], now: r.w, rec: r.w + '–' + r.l }; }) });
    });
  });
}
/* projected wins: the mean (dot) and the 5th to 95th percentile band of the simulations, one row a club */
function winsChart(pw, L) {
  const host = document.getElementById('ch-wins');
  if (!host || !pw.length) return;
  const T = QKC.tokens();
  QKC.mount(host, () => ({
    grid: { left: 8, right: 24, top: 10, bottom: 34, containLabel: true },
    xAxis: { type: 'value', name: 'Wins (season total)', nameLocation: 'middle', nameGap: 26, scale: true, axisLabel: { color: T.ink3 }, splitLine: { lineStyle: { color: T.grid } } },
    yAxis: { type: 'category', inverse: true, data: pw.map(r => BP.teamAbbr(r.tid)), axisLabel: { color: T.ink2, fontFamily: T.fontCond, fontWeight: 700 } },
    tooltip: { trigger: 'item', backgroundColor: '#000', borderColor: T.volt, textStyle: { color: '#fff' },
      formatter: p => { const r = pw[p.dataIndex]; return esc(BP.teamName(r.tid)) + '<br>' + (isNum(r.proj_w) ? r.proj_w.toFixed(1) : '') + ' wins expected' + (isNum(r.w_p05) ? ' (range ' + r.w_p05 + '–' + r.w_p95 + ')' : ''); } },
    series: [
      { type: 'custom', renderItem: (params, api) => { const lo = api.coord([api.value(0), api.value(2)]), hi = api.coord([api.value(1), api.value(2)]); return { type: 'rect', shape: { x: lo[0], y: lo[1] - 4, width: Math.max(1, hi[0] - lo[0]), height: 8 }, style: { fill: T.grid } }; },
        encode: { x: [0, 1], y: 2 }, data: pw.map((r, i) => [isNum(r.w_p05) ? r.w_p05 : r.proj_w, isNum(r.w_p95) ? r.w_p95 : r.proj_w, i]) },
      { type: 'scatter', symbolSize: 11, data: pw.map((r, i) => ({ value: [isNum(r.proj_w) ? r.proj_w : r.exp_w_final, i], itemStyle: { color: QK.color.ensure(BP.ui.raw(r.tid) || T.model, T.s1, 3) } })) }
    ]
  }), { label: 'Projected wins with the middle 90% of the simulations, every club' });
}

BP.standingsRows = rowsOf;
BP.route('standings', render);
BP.route('chances', chancesView);
})(window.BP);
