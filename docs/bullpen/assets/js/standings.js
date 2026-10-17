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
  return { v: BP.teamName(r.tid), html: BP.teamLink(r.tid, { short: true, level: L, season: S }) + clinch(r) };
}
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
      { v: ew, html: isNum(ew) ? BP.record(ew, el) : '—', cls: 'hide-sm', title: 'Expected record from our team ratings (offence, defence, pitching)' },
      oddsCell(s.p_postseason), Object.assign(oddsCell(s.p_division), { cls: 'hide-sm' }), Object.assign(oddsCell(s.p_bye), { cls: 'hide-sm' }), oddsCell(s.p_ws),
      Object.assign(magicCell(r), { align: 'right', cls: 'hide-sm' })] };
  });
  return BP.tableHTML([{ label: 'Team' }, { label: 'W', align: 'right' }, { label: 'L', align: 'right' }, { label: 'Pct', align: 'right' }, { label: 'GB', align: 'right' },
    { label: 'RS', align: 'right', cls: 'hide-sm' }, { label: 'RA', align: 'right', cls: 'hide-sm' }, { label: 'Diff', align: 'right' },
    { label: 'Pythag', align: 'right', cls: 'hide-sm', title: 'Pythagorean record from runs scored and allowed (exponent 1.83); the figure is wins above it' },
    { label: 'Expected', align: 'right', cls: 'hide-sm', title: 'Our expected record from the team ratings' },
    { label: 'Playoffs', align: 'right', title: 'Probability of a postseason place (season simulation)' }, { label: 'Division', align: 'right', cls: 'hide-sm' },
    { label: 'Bye', align: 'right', cls: 'hide-sm', title: 'A top-two seed: straight to the Division Series' }, { label: 'WS', align: 'right', title: 'World Series probability' },
    { label: 'Magic', align: 'right', cls: 'hide-sm', title: 'Division magic number: wins plus rival losses to clinch' }], rows, { compact: true, cls: 'std-table' });
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
      { v: r.rd, html: isNum(r.rd) ? BP.signed(r.rd, 0) : '—', cls: 'hide-sm' }, oddsCell(s.p_postseason), oddsCell(s.p_wildcard), oddsCell(s.p_ws)] };
  };
  return BP.tableHTML([{ label: 'Seed', sortable: false }, { label: 'Team' }, { label: 'W', align: 'right' }, { label: 'L', align: 'right' }, { label: 'Pct', align: 'right' },
    { label: 'WCGB', align: 'right', title: 'Games ahead of / behind the third wild card' }, { label: 'Diff', align: 'right', cls: 'hide-sm' },
    { label: 'Playoffs', align: 'right' }, { label: 'Wild card', align: 'right' }, { label: 'WS', align: 'right' }],
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
  el.innerHTML = BP.pageHead(BP.levelName(L) + ' standings ' + S, 'Records, run differential, Pythagorean and expected records, and the season simulation’s odds',
    '<a href="' + BP.ghref('postseason') + '">Postseason</a><a href="' + BP.href('teams', L, S) + '">Teams</a>') + '<div id="std-body"><div class="muted">Loading…</div></div>';
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
    body.innerHTML = '<div class="toggle-row std-tabs" id="std-tabs">' + BP.toggles([{ key: 'div', label: 'Divisions' }, { key: 'wc', label: 'Wild card' }, { key: 'rt', label: 'Ratings and luck' }], VIEW, 'data-v') + '</div>' +
      '<div id="std-view"></div>' +
      '<div class="section-note">' + (res.fallback ? 'Computed from the final regular-season games while the season payload is built; odds and expected records arrive with it. ' : '') +
      'Odds: ' + (d.sim && (d.sim.n_sims || d.sim.sims) ? BP.int(d.sim.n_sims || d.sim.sims) + ' ' : '') + 'simulations of the rest of the season and the bracket from our team ratings (x: clinched a place, y: the division, z: the division and a bye, e: eliminated). ' +
      'Pythagorean records use exponent 1.83. Magic numbers count wins plus division-rival losses to clinch.</div>';
    BP.wireToggles(document.getElementById('std-tabs'), 'data-v', k => { VIEW = k; draw(); });
    draw();
    BP.setMeta(d.updated_at ? 'Season data ' + esc(BP.fmtStamp(d.updated_at)) : '');
  });
}

BP.standingsRows = rowsOf;
BP.route('standings', render);
})(window.BP);
