/* The Quant Bullpen — game centre (#/<L>/game/<gpk>).
 *
 *   header: teams, score, status, series, park, umpire; live state (inning, count, bases, outs,
 *           at bat) and win probability; the linescore once the game has started;
 *   Preview: model v market v DraftKings for win, run line, total and first five (with the
 *            total-runs distribution); starters; lineups with matchup projections; weather,
 *            park and umpire;
 *   Game:    win probability (ours v ESPN) with the top WPA plays; spray chart with xwOBA+ v
 *            Savant xwOBA and the batted-ball table;
 *   Pitches: pitch-by-pitch with filters (pitcher, batter, inning, pitch type, result) and the
 *            strike zone (catcher's view) coloured by type, result, Stuff+ or xwOBA+;
 *   Box score with expected stats; Umpire scorecard (missed calls, run cost, favoured team)
 *   and ABS challenges; Arsenals: each pitcher's pitches today against his season norm.
 *
 * Reads <L>/<S>/games/<gpk>.json (PAYLOADS.md), falling back to the GAME_CARD in
 * schedule.json / index.json while the game payload is not built. */
(function (BP) {
'use strict';

const esc = BP.esc;
const isNum = BP.isNum;
const CH = () => BP.charts;
const TAB = {};       // gpk -> last tab
const FILT = {};      // gpk -> pitch filters

function pctOr(p, d) { return isNum(p) ? BP.pct(p, d === undefined ? 1 : d) : '—'; }
function half(h) { return BP.halfOf(h); }
/* The team batting in a half-inning: the away team bats in the top. */
function battingTeam(g, h) { return half(h) === 'top' ? g.away : g.home; }

function findCard(L, S, gpk) {
  const idx = BP.index() || {};
  const src = L === 'mlb' ? idx : BP.levelInfo(L);
  const c = [].concat(src.today || [], src.recent || [], src.upcoming || []).find(x => x && String(x.gpk) === String(gpk));
  if (c) return Promise.resolve(c);
  return BP.loadYear('schedule.json', L, S).then(d => {
    const list = d && Array.isArray(d.games) ? d.games : [];
    return list.find(x => x && String(x.gpk) === String(gpk)) || null;
  });
}
function preOf(g) { return g._pre || {}; }

// ── normalise: the build's page shape (scripts/build_bullpen.py, analytics/games.py) and the
//    PAYLOADS.md sketch differ in places; every panel reads the fields set here. ─────────────

function callKey(p) {
  if (BP.CALLS[p.call] && String(p.call).length > 1) return p.call;
  if (BP.CALLS[p.desc]) return p.desc;
  return p.call || p.desc;
}
function normPitches(raw) {
  return CH().rows(raw).map(p => {
    const q = Object.assign({}, p, { pitcher: p.pitcher ? String(p.pitcher) : p.pitcher, batter: p.batter ? String(p.batter) : p.batter });
    q._call = callKey(p);
    // the play text: "des", or "desc" when it is not a pitch result
    q._des = p.des || (p.desc && !BP.CALLS[p.desc] ? p.desc : '');
    return q;
  });
}
/* Inches from the edge of the rulebook zone (ball edge included): + outside, - inside. */
function missDist(m) {
  if (!isNum(m.plate_x) || !isNum(m.plate_z)) return null;
  const top = isNum(m.sz_top) ? Number(m.sz_top) : 3.4, bot = isNum(m.sz_bot) ? Number(m.sz_bot) : 1.55;
  const dx = Math.abs(Number(m.plate_x)) - 0.83, dz = Math.max(bot - 0.12 - Number(m.plate_z), Number(m.plate_z) - (top + 0.12));
  const out = Math.max(dx, dz);
  return Math.round((out > 0 ? out : out) * 120) / 10;
}
function normalise(raw, P) {
  const g = Object.assign({}, raw);
  // park
  const v = g.park || (g.venue && typeof g.venue === 'object' ? g.venue : null);
  g._vid = v ? String(v.vid || v.id || '') : (g.venue ? String(g.venue) : '');
  g._park = v ? Object.assign({}, v, { factor: v.factor || v.factors || {} }) : {};
  if (g.venue && typeof g.venue === 'object') g.venue = g._vid;
  // the plate umpire and the scorecard
  const scRaw = g.umpire_scorecard || g.scorecard || (g.umpire && (isNum(g.umpire.called) || g.umpire.calls) ? g.umpire : null);
  const id0 = g.umpire_hp || (g.umpire && !scRaw ? g.umpire : null) || {};
  const seasonU = id0.season || (scRaw && scRaw.season) || {};
  g._ump = { id: id0.id || (scRaw && scRaw.umpire) || null, name: id0.name || (scRaw && scRaw.name) || null,
    accuracy: isNum(id0.accuracy) ? id0.accuracy : seasonU.accuracy, x_accuracy: isNum(id0.x_accuracy) ? id0.x_accuracy : seasonU.x_accuracy,
    run_impact_pg: isNum(id0.run_impact_pg) ? id0.run_impact_pg : seasonU.runs_per_game, games: isNum(id0.games) ? id0.games : seasonU.games,
    zone: id0.zone || null, consistency: seasonU.consistency };
  if (g._ump.id && g._ump.name && !BP.UMPS[g._ump.id]) BP.UMPS[g._ump.id] = { name: g._ump.name };
  g._sc = null;
  if (scRaw) {
    let missed = Array.isArray(scRaw.missed) ? scRaw.missed : null;
    if (!missed && Array.isArray(scRaw.calls)) {
      const cols = scRaw.calls_cols || ['inning', 'half', 'ab', 'pitch_no', 'batter', 'pitcher', 'balls', 'strikes', 'plate_x', 'plate_z', 'sz_top', 'sz_bot', 'call', 'runs_batting'];
      missed = CH().rows({ cols: cols, rows: scRaw.calls }).map(m => {
        const batting = BP.halfOf(m.half) === 'top' ? String(g.away) : String(g.home), fielding = batting === String(g.home) ? String(g.away) : String(g.home);
        const rb = Number(m.runs_batting) || 0;
        return Object.assign({}, m, { batter: String(m.batter), pitcher: String(m.pitcher), call: m.call === 'strike' ? 'called_strike' : (m.call === 'ball' ? 'ball' : m.call),
          re_cost: Math.abs(rb), favoured: rb > 0 ? batting : fielding, dist_in: missDist(m) });
      });
    }
    const fav = scRaw.favoured && typeof scRaw.favoured === 'object' ? scRaw.favoured
      : { team: scRaw.favoured || null, runs: isNum(scRaw.home_favour) ? Math.abs(scRaw.home_favour) : null };
    g._sc = { called: scRaw.called, accuracy: scRaw.accuracy, x_accuracy: isNum(scRaw.x_accuracy) ? scRaw.x_accuracy : seasonU.x_accuracy,
      consistency: isNum(scRaw.consistency) ? scRaw.consistency : seasonU.consistency, missed: missed || [], favoured: fav,
      total: isNum(scRaw.total_impact) ? scRaw.total_impact : null };
  }
  // ABS challenges
  const ab = g.abs;
  const ch = Array.isArray(ab) ? ab : ((ab && ab.challenges) || []);
  g._abs = { summary: g.abs_summary || (ab && !Array.isArray(ab) ? ab.summary : null) || {}, challenges: ch.map(c => {
    const team = c.team || (BP.halfOf(c.half) === 'top' ? (/catcher|pitcher|fielding/i.test(String(c.kind || c.role || '')) ? g.home : g.away) : null);
    const pitch = !isNum(c.plate_x) && isNum(c.ab) ? P.filter(q => q.ab === c.ab && BP.callInfo(q._call).kind === 'called').pop() : null;
    return Object.assign({}, c, { team: team ? String(team) : null, by: c.by || null, who: c.who || null, role: c.role || c.kind || null,
      overturned: c.overturned !== undefined ? !!c.overturned : /overturn/i.test(String(c.result || '')),
      call: c.call || (pitch ? pitch._call : null), plate_x: isNum(c.plate_x) ? c.plate_x : (pitch ? pitch.plate_x : null),
      plate_z: isNum(c.plate_z) ? c.plate_z : (pitch ? pitch.plate_z : null), sz_top: c.sz_top || (pitch ? pitch.sz_top : null), sz_bot: c.sz_bot || (pitch ? pitch.sz_bot : null),
      balls: isNum(c.balls) ? c.balls : (pitch ? pitch.balls : null), strikes: isNum(c.strikes) ? c.strikes : (pitch ? pitch.strikes : null) });
  }) };
  // box score: {home: {tid, batting, pitching}} from either {batting: {home}, pitching: {home}} or the per-side shape
  const bx = g.box || {};
  g._box = {};
  ['home', 'away'].forEach(sd => {
    if (bx[sd]) g._box[sd] = bx[sd];
    else if (bx.batting || bx.pitching) g._box[sd] = { tid: g[sd], batting: (bx.batting || {})[sd] || [], pitching: (bx.pitching || {})[sd] || [] };
  });
  const dec = g.decisions || {};
  ['home', 'away'].forEach(sd => ((g._box[sd] || {}).pitching || []).forEach(x => {
    if (!x.decision) x.decision = dec.w === x.pid ? 'W' : dec.l === x.pid ? 'L' : dec.s === x.pid ? 'S' : null;
    if (!isNum(x.er) && isNum(x.r)) x._r = true;
  }));
  // arsenals: {pid: {team, throws, arm_angle, n, pitches: {pt: {..., norm}}}}
  g._ars = {};
  const A = g.arsenals || g.arsenal || {};
  Object.keys(A).forEach(pid => {
    const a = A[pid] || {};
    let pitches = a.pitches;
    if (!pitches) {
      pitches = {};
      Object.keys(a).forEach(pt => {
        const x = a[pt];
        if (!x || typeof x !== 'object') return;
        const norm = {};
        ['velo', 'ivb', 'hb', 'spin', 'stuff'].forEach(k => { if (isNum(x[k]) && isNum(x['d_' + k])) norm[k] = x[k] - x['d_' + k]; });
        pitches[pt] = Object.assign({}, x, { norm: Object.keys(norm).length ? norm : null });
      });
    }
    const tot = Object.keys(pitches).reduce((t, k) => t + (pitches[k].n || 0), 0);
    Object.keys(pitches).forEach(k => { if (!isNum(pitches[k].usage) && tot) pitches[k].usage = (pitches[k].n || 0) / tot; });
    const mine = P.filter(q => q.pitcher === String(pid));
    const team = a.team || (mine.length ? (BP.halfOf(mine[0].half) === 'top' ? g.home : g.away) : null);
    g._ars[pid] = { team: team ? String(team) : null, throws: a.throws || BP.player(pid).throws || null, arm_angle: a.arm_angle, n: a.n || tot, pitches: pitches };
  });
  // win probability: ours by plate appearance; ESPN's x scaled to the same axis; the top plays
  const wp = Array.isArray(g.wp) ? { ours: g.wp } : (g.wp || {});
  const ours = wp.ours || [];
  let espn = wp.espn || [];
  const maxI = ours.length ? Math.max.apply(null, ours.map(r => Number(Array.isArray(r) ? r[0] : r.i) || 0)) : 0;
  if (espn.length && maxI > 1 && Math.max.apply(null, espn.map(r => Number(Array.isArray(r) ? r[0] : r.i) || 0)) <= 1) {
    espn = espn.map(r => (Array.isArray(r) ? [r[0] * maxI, r[1]] : Object.assign({}, r, { i: r.i * maxI })));
  }
  let top = wp.top || g.wpa_top || null;
  if (!top && Array.isArray(g.wpa_leaders)) {
    const abs = []; P.forEach(q => { if (abs.indexOf(q.ab) < 0) abs.push(q.ab); });
    abs.sort((a2, b2) => a2 - b2);
    top = g.wpa_leaders.slice(0, 5).map(x => {
      const last = P.filter(q => q.ab === x.ab).pop() || {};
      const h = BP.halfOf(isNum(last.half) || last.half ? last.half : null);
      return { i: abs.indexOf(x.ab) + 1, inning: x.inning, half: last.half, wpa: (h === 'top' ? -1 : 1) * (Number(x.wpa) || 0),
        desc: last._des || (BP.playerName(x.batter) + (last.event ? ': ' + BP.eventLabel(last.event) : '')) };
    });
  }
  g._wp = { ours: ours, espn: espn, top: top || [], kind: wp.ours_kind || null };
  // pre-game
  const pr = g.pregame || g.pre || {};
  const L0 = g.lineups || pr.lineups || null;
  let lineups = null, projected = !!(pr.lineups_projected || g.lineups_projected);
  if (L0) {
    lineups = {};
    ['home', 'away'].forEach(sd => {
      const x = L0[sd];
      if (Array.isArray(x)) { lineups[sd] = x; return; }
      if (x && Array.isArray(x.batters)) {
        if (x.source === 'projected') projected = true;
        lineups[sd] = x.batters.map(b => ({ pid: String(b.pid), order: b.slot || b.order, pos: b.pos, bats: b.bats,
          proj: b.matchup ? { woba: b.matchup.woba, k: b.matchup.k, bb: b.matchup.bb, hr: b.matchup.hr } : (b.proj || {}), vs: b.vs || {} }));
      }
    });
  }
  g._pre = { model: pr.model || g.model || {}, market: pr.market || g.market || pr.store_market || null, line: pr.line || g.lines || g.line || null,
    lineups: lineups, projected: projected, starters: pr.starters || g.starters || null, priced_at: pr.priced_at || null };
  // linescore
  if (Array.isArray(g.linescore)) g.linescore = { innings: g.linescore };
  if (!g.linescore && Array.isArray(g.innings)) g.linescore = { innings: g.innings };
  // hits from the pitch table when the linescore has none
  if (g.linescore && !g.linescore.h && P.length) {
    const h = [0, 0];
    P.forEach(q => { if (q.event && BP.isHit(q.event)) h[BP.halfOf(q.half) === 'top' ? 0 : 1]++; });
    g.linescore = Object.assign({}, g.linescore, { h: h });
  }
  return g;
}

// ── header ─────────────────────────────────────────────────────────────────

function header(g, L, S) {
  const st = BP.gameState(g);
  const pre = preOf(g);
  const pH = isNum(pre.model.p_home) ? Number(pre.model.p_home) : null;
  const live = st === 'live', fin = st === 'final';
  const wpH = live && isNum(g.wp_home) ? Number(g.wp_home) : null;
  const started = live || fin;
  const winH = fin && g.hs > g.as, winA = fin && g.as > g.hs;
  const side = (tid, score, isHome) => {
    const won = isHome ? winH : winA, lost = isHome ? winA : winH;
    const sp = (g.probables || {})[isHome ? 'home' : 'away'];
    const p = live ? (wpH === null ? null : (isHome ? wpH : 1 - wpH)) : (pH === null ? null : (isHome ? pH : 1 - pH));
    return '<div class="gm-team' + (won ? ' won' : '') + (lost ? ' lost' : '') + '">' +
      '<span class="gm-sw" style="background:' + BP.teamColour(tid) + '"></span>' +
      '<div class="gm-tn"><div class="gm-name">' + BP.teamLink(tid, { bar: false, level: L }) + '</div>' +
      '<div class="gm-tsub">' + (isHome ? 'Home' : 'Away') + (sp && !started ? ' · ' + BP.playerLink(sp, { role: 'pitcher', level: L }) : '') + '</div></div>' +
      (started ? '<span class="gm-score">' + esc(isNum(score) ? score : '') + '</span>' : '') +
      '<span class="gm-p" title="' + (live ? 'Live win probability (our model)' : 'Model pre-game win probability') + '">' + (p === null ? '' : BP.pct(p, 0) + '<small>' + (live ? 'live' : 'pre-game') + '</small>') + '</span></div>';
  };
  const ump = g._ump || {};
  const kick = [BP.statusChip(g)];
  if (g.series) kick.push('<span>' + esc(BP.seriesText(g.series)) + '</span>');
  else if (g.gtype && g.gtype !== 'R') kick.push('<span>' + esc(BP.roundLabel(g.gtype)) + '</span>');
  kick.push('<span>' + esc(BP.fmtDate(g.start || g.date, { time: true })) + '</span>');
  const vid = g._vid;
  if (vid) kick.push(BP.parkLink(vid, g._park.name));
  let liveBox = '';
  if (live) {
    const ab = g.at_bat || {};
    liveBox = '<div class="gm-live"><span class="gm-inn">' + esc(BP.inningLabel(g.inning, g.half)) + '</span>' +
      (isNum(g.balls) ? '<span class="gm-count">' + BP.countText(g.balls, g.strikes) + '</span>' : '') +
      BP.basesHTML(g.bases, g.outs) +
      (ab.batter ? '<span class="gm-ab">' + BP.playerLink(ab.batter, { short: true, level: L }) + (ab.pitcher ? ' <span class="muted-inline">v</span> ' + BP.playerLink(ab.pitcher, { short: true, role: 'pitcher', level: L }) : '') + '</span>' : '') +
      (wpH !== null ? '<span class="gm-wp">' + esc(BP.teamAbbr(wpH >= 0.5 ? g.home : g.away)) + ' ' + BP.pct(Math.max(wpH, 1 - wpH), 0) + ' to win</span>' : '') + '</div>';
  }
  const sub = [];
  if (fin && g.decisions) {
    const d = g.decisions;
    if (d.w) sub.push('W ' + BP.playerLink(d.w, { short: true, role: 'pitcher', level: L }));
    if (d.l) sub.push('L ' + BP.playerLink(d.l, { short: true, role: 'pitcher', level: L }));
    if (d.s) sub.push('S ' + BP.playerLink(d.s, { short: true, role: 'pitcher', level: L }));
  }
  if (ump.id || ump.name) sub.push('Plate umpire ' + BP.umpireLink(ump.id, ump.name));
  if (g.weather && (g.weather.temp || g.weather.cond)) sub.push(esc([isNum(g.weather.temp) ? g.weather.temp + '°F' : '', g.weather.cond, g.weather.wind].filter(Boolean).join(', ')));
  return '<div class="gm-head"><div class="gm-kicker">' + kick.join('') + '</div>' +
    '<div class="gm-board">' + side(g.away, g.as, false) + side(g.home, g.hs, true) + '</div>' + liveBox +
    (started ? '<div class="gm-ls">' + CH().linescore(g, { level: L }) + '</div>' : '') +
    (sub.length ? '<div class="gm-sub">' + sub.map(x => '<span>' + x + '</span>').join('<span class="dot">·</span>') + '</div>' : '') + '</div>';
}

// ── preview ────────────────────────────────────────────────────────────────

function priceRows(g) {
  const pre = preOf(g);
  const m = pre.model || {}, k = pre.market || {}, ln = pre.line || {};
  const H = BP.teamAbbr(g.home), A = BP.teamAbbr(g.away);
  const rows = [];
  const dk = ln.close || ln;
  // win
  const mlP = Array.isArray(dk.ml) ? BP.devigAm(dk.ml) : null;
  rows.push({ label: H + ' to win', model: m.p_home, market: k.p_home, line: mlP, lineTxt: Array.isArray(dk.ml) ? H + ' ' + BP.fmtOdds(dk.ml[0]) + ' / ' + A + ' ' + BP.fmtOdds(dk.ml[1]) : '' });
  // run line
  const rl = dk.rl && typeof dk.rl === 'object' ? dk.rl : null;
  const pt = rl && isNum(rl.home) ? Number(rl.home) : -1.5;
  const rlm = m.runline || {};
  const key = 'home_' + (pt > 0 ? '+' : '') + pt.toFixed(1);
  const rlModel = isNum(rlm[key]) ? rlm[key] : (pt === -1.5 && isNum(m.rl_home) ? m.rl_home : null);
  rows.push({ label: H + ' ' + BP.fmtLine(pt), model: rlModel, market: isNum(k.rl_home) ? k.rl_home : null,
    line: rl && Array.isArray(rl.price) ? BP.devigAm(rl.price) : null, lineTxt: rl && Array.isArray(rl.price) ? BP.fmtOdds(rl.price[0]) + ' / ' + BP.fmtOdds(rl.price[1]) : '' });
  // total
  const tot = dk.total && typeof dk.total === 'object' ? dk.total : (isNum(dk.total) ? { line: dk.total } : null);
  const tl = tot && isNum(tot.line) ? Number(tot.line) : (isNum(k.total) ? Number(k.total) : null);
  if (tl !== null) {
    let pOver = (m.over || {})[tl.toFixed(1)];
    if (!isNum(pOver) && Array.isArray(m.total_dist)) {
      let win = 0, lose = 0;
      m.total_dist.forEach((p, n) => { if (n > tl) win += p; else if (n < tl) lose += p; });
      pOver = win + lose > 0 ? win / (win + lose) : null;
    }
    rows.push({ label: 'Over ' + BP.num(tl, 1) + ' runs', model: pOver, market: isNum(k.p_over) && (!isNum(k.total) || Number(k.total) === tl) ? k.p_over : null,
      line: isNum(tot && tot.over) && isNum(tot.under) ? BP.devigAm([tot.over, tot.under]) : null, lineTxt: tot && isNum(tot.over) ? 'O ' + BP.fmtOdds(tot.over) + ' / U ' + BP.fmtOdds(tot.under) : '',
      extra: isNum((m.runs || {}).total) ? 'model expects ' + BP.num(m.runs.total, 1) : '' });
  }
  // first five
  const f5 = m.f5 || {};
  if (isNum(f5.home)) {
    const noTie = isNum(f5.away) && f5.home + f5.away > 0 ? f5.home / (f5.home + f5.away) : null;
    rows.push({ label: H + ' first five', model: noTie, market: isNum(k.f5_home) ? k.f5_home : null, line: null, lineTxt: '',
      extra: 'tie ' + pctOr(f5.tie, 0) + ' (pushed) · ' + BP.num(f5.total, 1) + ' runs' });
  }
  return rows;
}
function priceTable(g) {
  const rows = priceRows(g);
  const pre = preOf(g);
  const src = (pre.market && pre.market.sources) || [];
  const t = BP.tableHTML([{ label: 'Bet' }, { label: 'Model', align: 'right' }, { label: 'Market', align: 'right', title: 'De-vigged prediction-market probability' },
    { label: 'Gap', align: 'right', title: 'Model minus market, points' }, { label: (pre.line && pre.line.src) || 'DraftKings', align: 'right', title: 'De-vigged line probability' },
    { label: 'Fair odds', align: 'right', cls: 'hide-sm', title: 'Model probability as American odds' }],
  rows.map(r => [
    { v: r.label, html: '<b>' + esc(r.label) + '</b>' + (r.extra ? '<div class="sub-line">' + esc(r.extra) + '</div>' : '') },
    { v: r.model, html: isNum(r.model) ? '<b class="clay">' + BP.pct(r.model, 1) + '</b>' : '—' },
    { v: r.market, html: pctOr(r.market) },
    { v: isNum(r.model) && isNum(r.market) ? r.model - r.market : null, html: BP.edgeHTML(r.model, r.market) },
    { v: r.line, html: isNum(r.line) ? BP.pct(r.line, 1) + (r.lineTxt ? '<div class="sub-line">' + esc(r.lineTxt) + '</div>' : '') : '—' },
    { v: r.model, html: BP.american(r.model) }
  ]), { compact: true });
  return t + '<div class="section-note">Model: ' + (isNum((pre.model || {}).sims) ? BP.int(pre.model.sims) + ' ' : '') + 'plate-appearance simulations with the lineups, starters, bullpens, park, weather and umpire. Market: ' +
    (src.length ? esc(src.join(' and ')) : 'prediction markets') + ', de-vigged. The first five is shown without the tie (a tie pushes). 18+.</div>';
}
function lineupTable(list, L, side, g) {
  const rows = (list || []).map(x => {
    const pr = x.proj || {}, vs = x.vs || {};
    return [
      { v: x.order, html: '<span class="muted-inline">' + esc(x.order || '') + '</span>' },
      { v: BP.playerName(x.pid), html: BP.playerLink(x.pid, { level: L }) + '<span class="pl-pos">' + esc(x.pos || BP.player(x.pid).pos || '') + '</span>' + (x.bats || BP.player(x.pid).bats ? '<span class="pl-pos">' + esc(x.bats || BP.player(x.pid).bats) + '</span>' : '') },
      { v: pr.xwoba_plus || pr.woba, html: BP.fmtAvg(isNum(pr.xwoba_plus) ? pr.xwoba_plus : pr.woba), align: 'right', title: 'Projected wOBA in this matchup' },
      { v: pr.k, html: isNum(pr.k) ? BP.pct(pr.k, 0) : '—', align: 'right', cls: 'hide-sm' },
      { v: pr.bb, html: isNum(pr.bb) ? BP.pct(pr.bb, 0) : '—', align: 'right', cls: 'hide-sm' },
      { v: pr.hr, html: isNum(pr.hr) ? BP.pct(pr.hr, 1) : '—', align: 'right' },
      { v: vs.pa, html: isNum(vs.pa) && vs.pa > 0 ? vs.pa + ' PA, ' + BP.fmtAvg(vs.woba) : '<span class="muted-inline">none</span>', align: 'right', cls: 'hide-sm', title: 'Career head-to-head against the opposing starter (wOBA)' }
    ];
  });
  if (!rows.length) return BP.muted('No lineup yet.');
  const opp = ((g.probables || {})[side === 'home' ? 'away' : 'home']);
  return BP.tableHTML([{ label: '#', sortable: false }, { label: 'Batter' }, { label: 'xwOBA', align: 'right', title: 'Projected wOBA (xwOBA+ basis) against this starter' },
    { label: 'K%', align: 'right', cls: 'hide-sm' }, { label: 'BB%', align: 'right', cls: 'hide-sm' }, { label: 'HR%', align: 'right' }, { label: 'v SP', align: 'right', cls: 'hide-sm' }], rows, { compact: true }) +
    (opp ? '<div class="section-note">Projections per plate appearance against ' + esc(BP.playerName(opp)) + ' and the bullpen behind him.</div>' : '');
}
function starterTiles(st, L) {
  const one = (s, label) => {
    if (!s || !s.pid) return BP.statTile(label, 'TBD', 'not announced');
    const p = s.proj || {};
    return '<div class="kpi"><div class="kpi-label">' + esc(label) + '</div><div class="kpi-value">' + BP.playerLink(s.pid, { role: 'pitcher', level: L }) + '</div>' +
      '<div class="kpi-sub">' + [isNum(p.ip) ? BP.num(p.ip, 1) + ' IP' : '', isNum(p.k) ? BP.num(p.k, 1) + ' K' : '', isNum(p.er) ? BP.num(p.er, 1) + ' ER' : '', isNum(p.pitches) ? p.pitches + ' pitches' : '', isNum(p.stuff) ? 'Stuff+ ' + Math.round(p.stuff) : ''].filter(Boolean).join(' · ') + '</div></div>';
  };
  return '<div class="kpi-grid two pad">' + one((st || {}).away, 'Away starter (projected)') + one((st || {}).home, 'Home starter (projected)') + '</div>';
}
function contextCard(g, L) {
  const w = g.weather || {}, pk = g._park || {}, u = g._ump || {};
  const dims = pk.dims || {};
  const f0 = pk.factor || pk.factors || {};
  // park factors as 100-based indices, whether written as 101 or as a ratio (1.01); the build keys them by event (HR, 1B, ...)
  const idx100 = v => (isNum(v) ? (Math.abs(v) < 3 ? v * 100 : Number(v)) : null);
  const f = { runs: idx100(isNum(f0.runs) ? f0.runs : (isNum(f0.R) ? f0.R : f0.woba)), hr: idx100(isNum(f0.hr) ? f0.hr : f0.HR),
    hr_lhb: idx100(f0.hr_lhb), hr_rhb: idx100(f0.hr_rhb) };
  const vid = g._vid;
  const kv = (k, v) => '<div class="gm-kv"><span>' + esc(k) + '</span><strong>' + v + '</strong></div>';
  return '<div class="gm-ctx">' +
    '<div><div class="gm-ctx-h">Weather</div>' + kv('Temperature', isNum(w.temp) ? w.temp + '°F' : '—') + kv('Wind', esc(w.wind || '—')) + kv('Conditions', esc(w.cond || '—')) +
      (pk.roof ? kv('Roof', esc(pk.roof)) : '') + (w.forecast ? '<div class="sub-line">forecast</div>' : '') + '</div>' +
    '<div><div class="gm-ctx-h">Park</div>' + kv('Venue', vid ? BP.parkLink(vid, pk.name) : '—') +
      kv('Dimensions', dims.lf ? dims.lf + ' · ' + dims.cf + ' · ' + dims.rf + ' ft' : '—') + kv('Run factor', isNum(f.runs) ? Math.round(f.runs) : '—') +
      kv('HR factor', isNum(f.hr) ? Math.round(f.hr) + (isNum(f.hr_lhb) ? ' <span class="muted-inline">(L ' + Math.round(f.hr_lhb) + ', R ' + Math.round(f.hr_rhb) + ')</span>' : '') : '—') +
      (isNum(pk.elev_ft) ? kv('Elevation', pk.elev_ft + ' ft') : '') + '</div>' +
    '<div><div class="gm-ctx-h">Plate umpire</div>' + kv('Umpire', u.id || u.name ? BP.umpireLink(u.id, u.name) : 'TBA') +
      kv('Accuracy', isNum(u.accuracy) ? BP.pct(u.accuracy, 1) + (isNum(u.x_accuracy) ? ' <span class="muted-inline">v ' + BP.pct(u.x_accuracy, 1) + ' expected</span>' : '') : '—') +
      kv('Run impact / game', isNum(u.run_impact_pg) ? BP.num(u.run_impact_pg, 2) : '—') + (u.zone ? kv('Zone', esc(u.zone)) : '') + (isNum(u.games) ? kv('Games', u.games) : '') + '</div></div>';
}
function previewPanel(el, g, L) {
  const pre = preOf(g);
  const m = pre.model || {};
  el.innerHTML = '<div class="grid-32">' +
    BP.card('Model v market v line', 'win · run line · total · first five', priceTable(g)) +
    BP.card('Total runs', 'model distribution · dashed: the line', '<div id="gm-tot" class="chart-box"></div>' +
      (isNum((m.runs || {}).home) ? '<div class="section-note">Expected runs: ' + esc(BP.teamAbbr(g.away)) + ' ' + BP.num(m.runs.away, 2) + ', ' + esc(BP.teamAbbr(g.home)) + ' ' + BP.num(m.runs.home, 2) +
        (isNum(m.extra_innings) ? ' · extra innings ' + BP.pct(m.extra_innings, 0) : '') + '</div>' : '')) + '</div>' +
    BP.card('Starters', 'projections for today', starterTiles(pre.starters || { home: { pid: (g.probables || {}).home }, away: { pid: (g.probables || {}).away } }, L)) +
    '<div class="grid-2">' +
      BP.card(BP.teamName(g.away), pre.projected ? 'projected lineup' : 'lineup', lineupTable((pre.lineups || {}).away, L, 'away', g)) +
      BP.card(BP.teamName(g.home), pre.projected ? 'projected lineup' : 'lineup', lineupTable((pre.lineups || {}).home, L, 'home', g)) + '</div>' +
    BP.card('Weather, park and umpire', 'the context the model prices in', contextCard(g, L));
  const ln = pre.line || {};
  const dk = ln.close || ln;
  const tl = dk.total && typeof dk.total === 'object' ? dk.total.line : dk.total;
  if (Array.isArray(m.total_dist)) CH().distBars('gm-tot', m.total_dist, { line: tl, exp: (m.runs || {}).total, xTitle: 'Total runs', height: 240, split: isNum(tl) ? tl : undefined, colour: BP.C.clay });
  else document.getElementById('gm-tot').innerHTML = BP.muted('No total distribution yet.');
  BP.sortable(el);
}

// ── game: win probability and batted balls ─────────────────────────────────

function gamePanel(el, g, P, L) {
  const wp = g._wp;
  const top = wp.top || [];
  const balls = P.filter(p => isNum(p.hc_x) && isNum(p.hc_y));
  const pk = g._park || {};
  el.innerHTML = BP.card('Win probability', ((wp.espn || []).length ? 'ours (solid) v ESPN (dotted)' : 'ours') + ' · numbered: the biggest plays', '<div id="gm-wp" class="chart-box"></div>' +
      (top.length ? '<div class="wpa-list">' + top.map((t, k) => '<div class="wpa-row"><span class="wpa-n">' + (k + 1) + '</span><span class="wpa-inn">' + esc(BP.inningLabel(t.inning, t.half, true)) + '</span>' +
        '<span class="wpa-d">' + esc(t.desc || '') + '</span><span class="wpa-v ' + ((t.wpa || 0) > 0 ? 'edge-pos' : 'edge-neg') + '" title="Home win probability added">' + BP.signed((t.wpa || 0) * 100, 1) + '</span></div>').join('') +
        '<div class="section-note">Win probability added for ' + esc(BP.teamName(g.home)) + ', in points.</div></div>' : '')) +
    '<div class="grid-23">' + BP.card('Spray chart', 'colour: expected wOBA on contact · filled: hits', '<div class="toggle-row" id="sp-ctl"></div><div id="gm-spray" class="chart-box"></div>') +
      BP.card('Batted balls', 'xwOBA+ (our model: launch, hang time, park and sprint speed) v Savant xwOBA', '<div id="gm-bb"></div>') + '</div>';
  CH().wpChart('gm-wp', wp.ours || [], { espn: wp.espn, top: top, home: g.home, away: g.away, height: 330, market: isNum((preOf(g).market || {}).p_home) ? preOf(g).market.p_home : undefined });
  let team = 'all', metric = 'xwoba_plus';
  const draw = () => {
    const list = team === 'all' ? balls : balls.filter(b => battingTeam(g, b.half) === team);
    CH().sprayChart('gm-spray', list, { dims: pk.dims, metric: metric, height: 400, emptyText: list.length ? '' : 'No batted balls yet.' });
    const rows = list.filter(b => isNum(b.xwoba_plus) || isNum(b.xwoba_savant) || isNum(b.launch_speed))
      .sort((a, b) => (Number(b.xwoba_plus) || 0) - (Number(a.xwoba_plus) || 0));
    document.getElementById('gm-bb').innerHTML = rows.length ? BP.tableHTML([{ label: 'Batter' }, { label: 'Inn', cls: 'hide-sm' }, { label: 'Result' }, { label: 'EV', align: 'right' }, { label: 'LA', align: 'right', cls: 'hide-sm' },
      { label: 'xwOBA+', align: 'right' }, { label: 'Savant', align: 'right' }, { label: 'Diff', align: 'right', cls: 'hide-sm', title: 'xwOBA+ minus Savant xwOBA' }],
    rows.map(b => [{ v: BP.playerName(b.batter), html: BP.playerLink(b.batter, { short: true, level: L }) }, { v: b.inning, html: esc(BP.inningLabel(b.inning, b.half, true)) },
      { v: b.event, html: BP.isHit(b.event) ? '<b>' + esc(BP.eventLabel(b.event)) + '</b>' : esc(BP.eventLabel(b.event)) }, { v: b.launch_speed, html: BP.num(b.launch_speed, 1) },
      { v: b.launch_angle, html: isNum(b.launch_angle) ? BP.num(b.launch_angle, 0) + '°' : '—' }, { v: b.xwoba_plus, html: BP.fmtAvg(b.xwoba_plus) }, { v: b.xwoba_savant, html: BP.fmtAvg(b.xwoba_savant) },
      { v: isNum(b.xwoba_plus) && isNum(b.xwoba_savant) ? b.xwoba_plus - b.xwoba_savant : null, html: isNum(b.xwoba_plus) && isNum(b.xwoba_savant) ? BP.signed((b.xwoba_plus - b.xwoba_savant) * 1000, 0) : '—' }]),
    { compact: true, cls: 'bb-table', id: 'bb-wrap' }) + '<div class="section-note">Diff in points of wOBA (thousandths). Savant xwOBA uses exit velocity and launch angle; xwOBA+ adds hang time, the park and the batter\'s sprint speed; the ball\'s direction is not used.</div>' : BP.muted('No batted balls yet.');
    BP.sortable(document.getElementById('gm-bb'));
  };
  const ctl = document.getElementById('sp-ctl');
  ctl.innerHTML = BP.toggles([{ key: 'all', label: 'Both teams' }, { key: String(g.away), label: BP.teamAbbr(g.away) }, { key: String(g.home), label: BP.teamAbbr(g.home) }], team, 'data-tm') +
    '<span class="ctl-sep"></span>' + BP.toggles([{ key: 'xwoba_plus', label: 'xwOBA+' }, { key: 'xwoba_savant', label: 'Savant xwOBA' }, { key: 'launch_speed', label: 'Exit velo' }], metric, 'data-mt');
  BP.wireToggles(ctl, 'data-tm', k => { team = k; draw(); });
  BP.wireToggles(ctl, 'data-mt', k => { metric = k; draw(); });
  draw();
}

// ── pitches ────────────────────────────────────────────────────────────────

function opts(list, cur) { return list.map(o => '<option value="' + esc(o[0]) + '"' + (String(o[0]) === String(cur) ? ' selected' : '') + '>' + esc(o[1]) + '</option>').join(''); }
function pitchesPanel(el, g, P, L) {
  if (!P.length) { el.innerHTML = BP.card('Pitch by pitch', '', BP.muted(BP.gameState(g) === 'pre' ? 'Pitches arrive once the game starts.' : 'No pitch data for this game yet.')); return; }
  const f = FILT[g.gpk] = FILT[g.gpk] || { pitcher: 'all', batter: 'all', inning: 'all', type: 'all', call: 'all', colour: 'type' };
  const pitchers = [], batters = [];
  P.forEach(p => { if (p.pitcher && pitchers.indexOf(p.pitcher) < 0) pitchers.push(p.pitcher); if (p.batter && batters.indexOf(p.batter) < 0) batters.push(p.batter); });
  const innings = []; P.forEach(p => { if (isNum(p.inning) && innings.indexOf(p.inning) < 0) innings.push(p.inning); });
  const types = []; P.forEach(p => { const t = String(p.pitch_type || '').toUpperCase(); if (t && types.indexOf(t) < 0) types.push(t); });
  types.sort((a, b) => BP.PITCH_ORDER.indexOf(a) - BP.PITCH_ORDER.indexOf(b));
  const teamOfP = pid => { const x = P.find(p => p.pitcher === pid); return x ? (half(x.half) === 'top' ? g.home : g.away) : null; };
  el.innerHTML = BP.card('Pitch by pitch', 'filter, then read the zone (catcher\'s view) and the table',
    '<div class="pz-ctl">' +
      '<label>Pitcher<select id="pf-pitcher">' + opts([['all', 'All pitchers']].concat(pitchers.map(p => [p, BP.teamAbbr(teamOfP(p)) + ' · ' + BP.playerName(p)])), f.pitcher) + '</select></label>' +
      '<label>Batter<select id="pf-batter">' + opts([['all', 'All batters']].concat(batters.map(p => [p, BP.playerName(p)])), f.batter) + '</select></label>' +
      '<label>Inning<select id="pf-inning">' + opts([['all', 'All']].concat(innings.map(i => [i, ordinal(i)])), f.inning) + '</select></label>' +
      '<label>Pitch<select id="pf-type">' + opts([['all', 'All types']].concat(types.map(t => [t, BP.pitchName(t)])), f.type) + '</select></label>' +
      '<label>Result<select id="pf-call">' + opts([['all', 'All'], ['called', 'Called strikes'], ['ball', 'Balls'], ['swinging', 'Swinging strikes'], ['foul', 'Fouls'], ['inplay', 'In play']], f.call) + '</select></label>' +
    '</div><div class="pz-grid"><div><div class="toggle-row" id="pz-col"></div><div id="gm-zone" class="chart-box"></div><div class="chart-note" id="pz-note"></div></div><div id="gm-ptab" class="pz-table"></div></div>');
  function ordinal(i) { return BP.ordinal(i); }
  const col = document.getElementById('pz-col');
  col.innerHTML = 'Colour by ' + BP.toggles([{ key: 'type', label: 'Pitch type' }, { key: 'call', label: 'Result' }, { key: 'stuff', label: 'Stuff+' }, { key: 'xwoba', label: 'xwOBA+' }], f.colour, 'data-cb');
  const draw = () => {
    const list = P.filter(p => (f.pitcher === 'all' || p.pitcher === f.pitcher) && (f.batter === 'all' || p.batter === f.batter) &&
      (f.inning === 'all' || String(p.inning) === String(f.inning)) && (f.type === 'all' || String(p.pitch_type || '').toUpperCase() === f.type) &&
      (f.call === 'all' || BP.callInfo(p._call).kind === f.call));
    const onePA = list.length && list.every(p => p.ab === list[0].ab);
    CH().strikeZone('gm-zone', list, { colourBy: f.colour, height: 420, numbers: onePA, emptyText: 'No pitches match the filters.' });
    document.getElementById('pz-note').textContent = list.length + ' pitch' + (list.length === 1 ? '' : 'es') + (onePA ? ' · numbers are the pitch order' : '') + ' · catcher’s view; the zone is drawn from ' + (f.batter !== 'all' || onePA ? "this batter's" : "the batters' median") + ' top and bottom; dashed: the edge a ball can touch.';
    // table grouped by plate appearance, newest first
    const groups = [];
    list.forEach(p => { let gr = groups.find(x => x.ab === p.ab); if (!gr) { gr = { ab: p.ab, rows: [] }; groups.push(gr); } gr.rows.push(p); });
    groups.sort((a, b) => b.ab - a.ab);
    const max = 60;
    let html = '<div class="table-wrap"><table class="wc-table pz-tab"><thead><tr><th>#</th><th>Count</th><th>Pitch</th><th class="r">mph</th><th class="r hide-sm">Spin</th><th class="r hide-sm" title="Induced vertical break / horizontal break, inches">IVB / HB</th><th>Result</th><th class="r" title="Stuff+ (100 = average)">Stuff+</th><th class="r hide-sm" title="Exit velocity and launch angle">EV / LA</th><th class="r" title="Run expectancy change (batting team)">RE</th></tr></thead><tbody>';
    groups.slice(0, max).forEach(gr => {
      const last = gr.rows[gr.rows.length - 1];
      const wpa = gr.rows.reduce((a, p) => a + (Number(p.wpa) || 0), 0);
      html += '<tr class="pa-head"><td colspan="10"><span class="pa-inn">' + esc(BP.inningLabel(last.inning, last.half, true)) + '</span> ' + BP.playerLink(last.batter, { short: true, level: L }) +
        ' <span class="muted-inline">v</span> ' + BP.playerLink(last.pitcher, { short: true, role: 'pitcher', level: L }) +
        (last.event ? ' · <b>' + esc(BP.eventLabel(last.event)) + '</b>' : '') + (isNum(last.outs) ? ' <span class="muted-inline">' + BP.outsText(last.outs) + '</span>' : '') +
        (wpa ? ' <span class="pa-wpa ' + (wpa > 0 ? 'edge-pos' : 'edge-neg') + '" title="Home win probability added">' + BP.signed(wpa * 100, 1) + '</span>' : '') +
        (last._des ? '<div class="pa-des">' + esc(last._des) + '</div>' : '') + '</td></tr>';
      gr.rows.slice().sort((a, b) => a.pitch_no - b.pitch_no).forEach(p => {
        const ci = BP.callInfo(p._call);
        html += '<tr><td class="muted-inline">' + esc(p.pitch_no) + '</td><td>' + BP.countText(p.balls, p.strikes) + '</td><td>' + BP.pitchChip(p.pitch_type) + '</td>' +
          '<td class="r">' + BP.num(p.velo, 1) + '</td><td class="r hide-sm">' + (isNum(p.spin) ? Math.round(p.spin) : '—') + '</td>' +
          '<td class="r hide-sm">' + BP.num(p.ivb, 1) + ' / ' + BP.num(p.hb, 1) + '</td>' +
          '<td><span class="call-dot" style="background:' + ci.colour + '"></span>' + esc(ci.label) + '</td>' +
          '<td class="r">' + (isNum(p.stuff) ? '<span style="color:' + BP.pctColor(Math.max(0, Math.min(100, 50 + (p.stuff - 100) * 2))) + '">' + Math.round(p.stuff) + '</span>' : '—') + '</td>' +
          '<td class="r hide-sm">' + (isNum(p.launch_speed) ? BP.num(p.launch_speed, 0) + ' / ' + BP.num(p.launch_angle, 0) + '°' : '') + '</td>' +
          '<td class="r">' + (isNum(p.re24) ? BP.signed(p.re24, 2) : '') + '</td></tr>';
      });
    });
    html += '</tbody></table></div>';
    if (groups.length > max) html += '<div class="section-note">Showing the latest ' + max + ' of ' + groups.length + ' plate appearances; filter to see the rest.</div>';
    document.getElementById('gm-ptab').innerHTML = groups.length ? html : BP.muted('No pitches match the filters.');
  };
  ['pitcher', 'batter', 'inning', 'type', 'call'].forEach(k => {
    const s = document.getElementById('pf-' + k);
    if (s) s.addEventListener('change', () => { f[k] = s.value; draw(); });
  });
  BP.wireToggles(col, 'data-cb', k => { f.colour = k; draw(); });
  draw();
}

// ── box score ──────────────────────────────────────────────────────────────

function boxPanel(el, g, L) {
  const box = g._box || {};
  const side = s => {
    const b = box[s] || {};
    const tid = b.tid || g[s];
    const bat = (b.batting || []).map(x => [
      { v: BP.playerName(x.pid), html: BP.playerLink(x.pid, { short: true, level: L }) + '<span class="pl-pos">' + esc(x.pos || BP.player(x.pid).pos || '') + '</span>' },
      { v: x.ab, html: esc(isNum(x.ab) ? x.ab : '—') }, { v: x.h, html: esc(isNum(x.h) ? x.h : '—') }, { v: x.hr, html: esc(isNum(x.hr) ? x.hr : '—'), cls: 'hide-sm' },
      { v: x.rbi, html: esc(isNum(x.rbi) ? x.rbi : '—') }, { v: x.bb, html: esc(isNum(x.bb) ? x.bb : '—') }, { v: x.so, html: esc(isNum(x.so) ? x.so : '—') },
      { v: x.xwoba_plus, html: BP.fmtAvg(x.xwoba_plus) }, { v: x.xwoba_savant, html: BP.fmtAvg(x.xwoba_savant), cls: 'hide-sm' },
      { v: x.wpa, html: isNum(x.wpa) ? '<span class="' + (x.wpa > 0 ? 'edge-pos' : x.wpa < 0 ? 'edge-neg' : '') + '">' + BP.signed(x.wpa, 2) + '</span>' : '—' },
      { v: x.re24, html: isNum(x.re24) ? BP.signed(x.re24, 2) : '—', cls: 'hide-sm' }]);
    const pit = (b.pitching || []).map(x => [
      { v: BP.playerName(x.pid), html: BP.playerLink(x.pid, { short: true, role: 'pitcher', level: L }) + (x.decision ? ' <span class="chip dec">' + esc(x.decision) + '</span>' : '') },
      { v: isNum(x.outs) ? x.outs : x.ip, html: isNum(x.outs) ? BP.fmtIP(x.outs, true) : BP.fmtIP(x.ip) }, { v: x.h, html: esc(isNum(x.h) ? x.h : '—') }, { v: isNum(x.er) ? x.er : x.r, html: esc(isNum(x.er) ? x.er : (isNum(x.r) ? x.r : '—')) },
      { v: x.bb, html: esc(isNum(x.bb) ? x.bb : '—') }, { v: x.so, html: esc(isNum(x.so) ? x.so : '—') }, { v: x.hr, html: esc(isNum(x.hr) ? x.hr : '—'), cls: 'hide-sm' },
      { v: x.pitches, html: isNum(x.pitches) ? x.pitches + (isNum(x.strikes) ? '-' + x.strikes : '') : '—', cls: 'hide-sm' },
      { v: x.stuff, html: isNum(x.stuff) ? Math.round(x.stuff) : '—' }, { v: x.csw, html: isNum(x.csw) ? BP.pct(x.csw, 0) : '—', cls: 'hide-sm' },
      { v: x.xera, html: isNum(x.xera) ? BP.num(x.xera, 2) : '—', cls: 'hide-sm' },
      { v: x.wpa, html: isNum(x.wpa) ? '<span class="' + (x.wpa > 0 ? 'edge-pos' : x.wpa < 0 ? 'edge-neg' : '') + '">' + BP.signed(x.wpa, 2) + '</span>' : '—' }]);
    return BP.card(BP.teamName(tid), 'batting', bat.length ? BP.tableHTML([{ label: 'Batter' }, { label: 'AB', align: 'right' }, { label: 'H', align: 'right' }, { label: 'HR', align: 'right', cls: 'hide-sm' },
      { label: 'RBI', align: 'right' }, { label: 'BB', align: 'right' }, { label: 'SO', align: 'right' }, { label: 'xwOBA+', align: 'right', title: 'Expected wOBA from our model, this game' },
      { label: 'Savant', align: 'right', cls: 'hide-sm', title: 'Savant xwOBA, this game' }, { label: 'WPA', align: 'right', title: 'Win probability added' }, { label: 'RE24', align: 'right', cls: 'hide-sm' }], bat, { compact: true, cls: 'box-table' }) : BP.muted('No batting lines yet.')) +
      BP.card(BP.teamName(tid), 'pitching', pit.length ? BP.tableHTML([{ label: 'Pitcher' }, { label: 'IP', align: 'right' }, { label: 'H', align: 'right' }, { label: 'ER', align: 'right', title: 'Earned runs (all runs where the split is not available)' }, { label: 'BB', align: 'right' },
        { label: 'SO', align: 'right' }, { label: 'HR', align: 'right', cls: 'hide-sm' }, { label: 'P-S', align: 'right', cls: 'hide-sm', title: 'Pitches and strikes' }, { label: 'Stuff+', align: 'right' },
        { label: 'CSW', align: 'right', cls: 'hide-sm', title: 'Called plus swinging strikes per pitch' }, { label: 'xERA', align: 'right', cls: 'hide-sm', title: 'Expected ERA from the contact and strikeouts allowed' },
        { label: 'WPA', align: 'right' }], pit, { compact: true, cls: 'box-table' }) : BP.muted('No pitching lines yet.'));
  };
  el.innerHTML = (box.away || box.home) ? '<div class="grid-2"><div>' + side('away') + '</div><div>' + side('home') + '</div></div>' : BP.card('Box score', '', BP.muted('The box score arrives once the game starts.'));
  BP.sortable(el);
}

// ── umpire and ABS ─────────────────────────────────────────────────────────

function umpirePanel(el, g, P, L) {
  const u = g._sc || {};
  const ab = g._abs || {};
  const missed = u.missed || [];
  const fav = u.favoured || {};
  const ump = g._ump || {};
  const calledP = P.filter(p => { const k = BP.callInfo(p._call).kind; return k === 'called' || (k === 'ball' && /ball/.test(String(p._call || ''))); });
  const key = p => p.ab + '-' + p.pitch_no;
  const missedKeys = {}; missed.forEach(m => { missedKeys[m.ab + '-' + m.pitch_no] = 1; });
  const tiles = '<div class="kpi-grid five pad">' +
    BP.statTile('Called pitches', isNum(u.called) ? u.called : calledP.length) +
    BP.statTile('Accuracy', isNum(u.accuracy) ? BP.pct(u.accuracy, 1) : '—', isNum(u.x_accuracy) ? 'expected ' + BP.pct(u.x_accuracy, 1) : '') +
    BP.statTile('Missed calls', String(missed.length), missed.length ? BP.num(missed.reduce((a, m) => a + (Number(m.re_cost) || 0), 0), 2) + ' runs in total' : '') +
    BP.statTile('Consistency', isNum(u.consistency) ? BP.pct(u.consistency, 1) : '—', 'same pitch, same call') +
    BP.statTile('Favoured', fav.team ? BP.teamLink(fav.team, { abbr: true, level: L }) : '—', isNum(fav.runs) ? '+' + BP.num(fav.runs, 2) + ' runs net' : '') + '</div>';
  const mrows = missed.slice().sort((a, b) => (b.re_cost || 0) - (a.re_cost || 0)).map(m => [
    { v: m.inning * 2 + (half(m.half) === 'bot' ? 1 : 0), html: esc(BP.inningLabel(m.inning, m.half, true)) },
    { v: BP.playerName(m.batter), html: BP.playerLink(m.pitcher, { short: true, role: 'pitcher', level: L }) + ' <span class="muted-inline">to</span> ' + BP.playerLink(m.batter, { short: true, level: L }), cls: 'hide-sm' },
    { v: (m.balls || 0) * 3 + (m.strikes || 0), html: BP.countText(m.balls, m.strikes) },
    { v: m.call, html: '<span class="call-dot" style="background:' + BP.callInfo(m.call).colour + '"></span>' + esc(BP.callInfo(m.call).label) },
    { v: m.dist_in, html: isNum(m.dist_in) ? BP.num(Math.abs(m.dist_in), 1) + ' in ' + (m.dist_in > 0 ? 'outside' : 'inside') : '—', cls: 'hide-sm', title: 'Distance of the ball edge from the zone' },
    { v: m.re_cost, html: isNum(m.re_cost) ? BP.num(m.re_cost, 2) : '—', align: 'right' },
    { v: m.favoured, html: m.favoured ? BP.teamLink(m.favoured, { abbr: true, level: L }) : '—' }]);
  const ch = ab.challenges || [];
  const sm = ab.summary || {};
  const chRows = ch.map(c => [
    { v: c.inning, html: esc(BP.inningLabel(c.inning, c.half, true)) }, { v: c.team, html: BP.teamLink(c.team, { abbr: true, level: L }) },
    { v: c.by ? BP.playerName(c.by) : (c.who || ''), html: (c.by ? BP.playerLink(c.by, { short: true, level: L }) : esc(c.who || '—')) + (c.role ? '<span class="pl-pos">' + esc(c.role) + '</span>' : '') },
    { v: (c.balls || 0) * 3 + (c.strikes || 0), html: BP.countText(c.balls, c.strikes), cls: 'hide-sm' },
    { v: c.call, html: esc(BP.callInfo(c.call).label) },
    { v: c.overturned ? 1 : 0, html: c.overturned ? '<span class="edge-pos">Overturned</span>' : '<span class="edge-neg">Upheld</span>' },
    { v: c.re_value, html: isNum(c.re_value) ? BP.signed(c.re_value, 2) : '—', align: 'right' }]);
  const absSum = ['away', 'home'].map(s => { const x = sm[s] || {}; return '<div class="abs-team">' + BP.teamLink(g[s], { abbr: true, level: L }) + ' <span>won ' + (x.won || 0) + ' · lost ' + (x.lost || 0) + ' · ' + (isNum(x.left) ? x.left + ' left' : '') + '</span></div>'; }).join('');
  el.innerHTML = BP.card('Umpire scorecard', (ump.id || ump.name ? BP.umpireLink(ump.id, ump.name) + ' · ' : '') + 'called pitches against the rulebook zone', tiles +
      '<div class="grid-23 pad0"><div><div id="gm-uz" class="chart-box"></div><div class="chart-note">Every called pitch, catcher\'s view; ringed: missed calls.</div></div><div>' +
      (mrows.length ? BP.tableHTML([{ label: 'Inn' }, { label: 'Matchup', cls: 'hide-sm' }, { label: 'Count' }, { label: 'Call' }, { label: 'Miss by', cls: 'hide-sm' }, { label: 'Runs', align: 'right', title: 'Run-expectancy cost of the missed call' }, { label: 'Helped' }], mrows, { compact: true }) : BP.muted(missed ? 'No missed calls recorded.' : 'The scorecard arrives after the game.')) +
      '</div></div><div class="section-note">A call is missed when the ball\'s edge is wholly outside the zone on a called strike, or touches it on a ball (zone from each batter\'s Statcast top and bottom). Run cost is the run-expectancy swing between the call made and the right call.</div>') +
    BP.card('ABS challenges', 'the automated ball-strike challenge system (2026)', '<div class="abs-sum">' + absSum + '</div>' +
      (chRows.length ? '<div class="grid-23 pad0"><div id="gm-abs" class="chart-box"></div><div>' + BP.tableHTML([{ label: 'Inn' }, { label: 'Team' }, { label: 'By' }, { label: 'Count', cls: 'hide-sm' }, { label: 'Call' }, { label: 'Result' }, { label: 'Runs', align: 'right', title: 'Run expectancy gained by the challenging team' }], chRows, { compact: true }) + '</div></div>'
        : BP.muted('No challenges in this game.')));
  const zoneList = calledP.length ? calledP : missed;
  CH().strikeZone('gm-uz', zoneList, { colourBy: 'call', height: 400, highlight: p => !!missedKeys[key(p)] || missed.indexOf(p) >= 0, highlightName: 'Missed call' });
  if (chRows.length) CH().strikeZone('gm-abs', ch.map(c => Object.assign({ desc: c.call }, c)), { colourBy: 'call', height: 320, highlight: c => !!c.overturned, highlightName: 'Overturned', hover: c => esc(BP.inningLabel(c.inning, c.half, true)) + ' · ' + esc(BP.playerName(c.by)) + '<br>' + (c.overturned ? 'Overturned' : 'Upheld') });
  BP.sortable(el);
}

// ── arsenals ───────────────────────────────────────────────────────────────

function delta(v, n, d, unit) {
  if (!isNum(v)) return '—';
  const base = BP.num(v, d);
  if (!isNum(n)) return base;
  const x = v - n;
  const cls = Math.abs(x) < (d === 0 ? 30 : 0.5) ? 'muted-inline' : (x > 0 ? 'edge-pos' : 'edge-neg');
  return base + ' <span class="' + cls + '">' + BP.signed(x, d) + (unit || '') + '</span>';
}
function arsenalPanel(el, g, P, L) {
  const ars = g._ars || {};
  const pids = Object.keys(ars);
  if (!pids.length) { el.innerHTML = BP.card('Arsenals', '', BP.muted(BP.gameState(g) === 'pre' ? 'Each pitcher\'s arsenal against his norm appears once he has thrown.' : 'No arsenal data for this game yet.')); return; }
  // starters first, by pitches thrown, away team first
  pids.sort((a, b) => (ars[a].team === g.away ? 0 : 1) - (ars[b].team === g.away ? 0 : 1) || (ars[b].n || 0) - (ars[a].n || 0));
  let cur = pids[0];
  el.innerHTML = BP.card('Arsenals today v norm', 'each pitch type: today, and the change from his season (green up, red down)',
    '<div class="toggle-row" id="ar-pick">' + BP.toggles(pids.map(p => ({ key: p, label: BP.teamAbbr(ars[p].team) + ' ' + BP.playerSurname(p) })), cur, 'data-p') + '</div><div id="ar-body"></div>');
  const draw = () => {
    const a = ars[cur] || {};
    const pt = a.pitches || {};
    const types = Object.keys(pt).sort((x, y) => (pt[y].n || 0) - (pt[x].n || 0));
    const rows = types.map(t => {
      const x = pt[t], n = x.norm || {};
      return [{ v: t, html: BP.pitchChip(t) + ' ' + esc(BP.pitchName(t)) }, { v: x.n, html: esc(x.n) }, { v: x.usage, html: isNum(x.usage) ? BP.pct(x.usage, 0) + (isNum(n.usage) ? ' <span class="muted-inline">' + BP.signed((x.usage - n.usage) * 100, 0) + '</span>' : '') : '—' },
        { v: x.velo, html: delta(x.velo, n.velo, 1) }, { v: x.velo_max, html: BP.num(x.velo_max, 1), cls: 'hide-sm' }, { v: x.spin, html: delta(x.spin, n.spin, 0), cls: 'hide-sm' },
        { v: x.ivb, html: delta(x.ivb, n.ivb, 1) }, { v: x.hb, html: delta(x.hb, n.hb, 1), cls: 'hide-sm' },
        { v: x.stuff, html: isNum(x.stuff) ? Math.round(x.stuff) + (isNum(n.stuff) ? ' <span class="muted-inline">' + BP.signed(x.stuff - n.stuff, 0) + '</span>' : '') : '—' },
        { v: isNum(x.whiff) ? x.whiff : x.whiffs, html: isNum(x.whiff) ? BP.pct(x.whiff, 0) : (isNum(x.whiffs) ? String(x.whiffs) : '—'), cls: 'hide-sm' }, { v: x.csw, html: isNum(x.csw) ? BP.pct(x.csw, 0) : '—' }];
    });
    const mine = P.filter(p => p.pitcher === cur);
    const norms = {};
    types.forEach(t => { const n = (pt[t] || {}).norm; if (n && isNum(n.hb) && isNum(n.ivb)) norms[t] = { hb: n.hb, ivb: n.ivb, sd_hb: 1.6, sd_ivb: 1.6 }; });
    document.getElementById('ar-body').innerHTML = '<div class="ar-head">' + BP.playerLink(cur, { role: 'pitcher', level: L }) + ' <span class="muted-inline">' + esc(a.throws ? a.throws + 'HP' : '') +
      (isNum(a.arm_angle) ? ' · arm angle ' + Math.round(a.arm_angle) + '°' : '') + ' · ' + (a.n || mine.length) + ' pitches</span></div>' +
      BP.tableHTML([{ label: 'Pitch' }, { label: 'N', align: 'right' }, { label: 'Usage', align: 'right' }, { label: 'mph', align: 'right' }, { label: 'Max', align: 'right', cls: 'hide-sm' },
        { label: 'Spin', align: 'right', cls: 'hide-sm' }, { label: 'IVB', align: 'right', title: 'Induced vertical break, inches' }, { label: 'HB', align: 'right', cls: 'hide-sm', title: "Horizontal break, inches (catcher's view)" },
        { label: 'Stuff+', align: 'right' }, { label: 'Whiff', align: 'right', cls: 'hide-sm', title: 'Whiffs per swing (or the number of whiffs)' }, { label: 'CSW', align: 'right' }], rows, { compact: true }) +
      '<div class="grid-2 pad0"><div><div class="ar-sub">Movement today (dots) and his season norm (dotted circles)</div><div id="ar-mv" class="chart-box"></div></div>' +
      '<div><div class="ar-sub">Velocity by pitch of the game (dashed: season norm)</div><div id="ar-velo" class="chart-box"></div></div></div>';
    CH().movementPlot('ar-mv', mine.length ? mine : types.map(t => Object.assign({ pitch_type: t }, pt[t])), { throws: a.throws, armAngle: a.arm_angle, league: norms, height: 360, means: !mine.length });
    const base = {};
    types.forEach(t => { const n = (pt[t] || {}).norm; if (n && isNum(n.velo)) base[t] = n.velo; });
    CH().pitchTrend('ar-velo', mine.map((p, i) => ({ x: i + 1, pitch_type: p.pitch_type, y: p.velo })), { baseline: base, yTitle: 'mph', xTitle: 'Pitch of the game', height: 360, mode: 'markers' });
    BP.sortable(document.getElementById('ar-body'));
  };
  BP.wireToggles(document.getElementById('ar-pick'), 'data-p', k => { cur = k; draw(); });
  draw();
}

// ── page ───────────────────────────────────────────────────────────────────

function render(el, params) {
  const L = params.level, S = params.season, gpk = params.id;
  el.innerHTML = '<div class="muted">Loading the game…</div>';
  return BP.loadGame(gpk, L, S).then(d => {
    if (!el.isConnected) return null;
    if (BP.ok(d)) return { g: d, full: true };
    return findCard(L, S, gpk).then(c => ({ g: c, full: false, raw: d }));
  }).then(res => {
    if (!res || !el.isConnected) return;
    if (!res.g) {
      el.innerHTML = BP.pageHead('Game ' + gpk, '', '<a href="' + BP.href('games', L, S) + '">All games</a>') + BP.card('Game centre', '', BP.notBuilt('This game', res.raw));
      return;
    }
    const P = normPitches(res.g.pitches);
    const g = normalise(res.g, P);
    const st = BP.gameState(g);
    const started = st === 'live' || st === 'final';
    const tabs = [];
    if (res.full || g.model) tabs.push({ key: 'preview', label: 'Preview' });
    if (started && res.full) {
      tabs.push({ key: 'game', label: 'Win probability · spray' });
      tabs.push({ key: 'pitches', label: 'Pitch by pitch' });
      tabs.push({ key: 'box', label: 'Box score' });
      tabs.push({ key: 'umpire', label: 'Umpire · ABS' });
      tabs.push({ key: 'arsenal', label: 'Arsenals' });
    }
    let tab = TAB[gpk] && tabs.some(t => t.key === TAB[gpk]) ? TAB[gpk] : (started && res.full ? 'game' : 'preview');
    if (params.query && params.query.tab && tabs.some(t => t.key === params.query.tab)) tab = params.query.tab;
    el.innerHTML = '<div class="ph-nav gm-nav"><a href="' + BP.href('games/' + g.date, L, S) + '">‹ ' + esc(BP.fmtDate(g.date, { year: false })) + ' games</a>' +
      (g.series ? '<a href="' + BP.ghref('postseason') + '">Postseason</a>' : '<a href="' + BP.href('standings', L, S) + '">Standings</a>') + '</div>' +
      header(g, L, S) +
      (tabs.length > 1 ? '<div class="seg-tabs" id="gm-tabs">' + tabs.map(t => '<a href="javascript:void(0)" data-tab="' + t.key + '"' + (t.key === tab ? ' class="active"' : '') + '>' + esc(t.label) + '</a>').join('') + '</div>' : '') +
      '<div id="gm-panel"></div>' + (res.full ? '' : '<div class="section-note">' + (Number(S || BP.currentSeason(L)) < Number(BP.currentSeason(L)) ?
        'Pitch-by-pitch game centres are kept on the site for the current season only; this is the schedule card. Stats, tables and careers for the season are complete.' :
        'The full game centre for this game is not built yet; this is the schedule card.') + '</div>');
    const panel = document.getElementById('gm-panel');
    const show = k => {
      TAB[gpk] = k;
      panel.innerHTML = '';
      const box = document.createElement('div');
      panel.appendChild(box);
      if (k === 'preview') {
        if (res.full) previewPanel(box, g, L);
        else box.innerHTML = '<div class="pad0">' + BP.gameCard(g, { level: L, season: S }) + '</div>';
      } else if (k === 'game') gamePanel(box, g, P, L);
      else if (k === 'pitches') pitchesPanel(box, g, P, L);
      else if (k === 'box') boxPanel(box, g, L);
      else if (k === 'umpire') umpirePanel(box, g, P, L);
      else if (k === 'arsenal') arsenalPanel(box, g, P, L);
    };
    document.querySelectorAll('#gm-tabs a[data-tab]').forEach(a => a.addEventListener('click', ev => {
      ev.preventDefault();
      document.querySelectorAll('#gm-tabs a').forEach(x => x.classList.toggle('active', x === a));
      show(a.dataset.tab);
    }));
    show(tab);
    document.title = BP.teamAbbr(g.away) + ' @ ' + BP.teamAbbr(g.home) + ' · ' + BP.fmtDate(g.date, { year: false }) + ' · ' + BP.SITE;
    if (st === 'live') BP.liveRefresh([BP.gamePath(gpk, L, S)], 45000);
    BP.setMeta(g.updated_at ? 'Game data ' + esc(BP.fmtStamp(g.updated_at)) : '');
  });
}

BP.route('game', render);
})(window.BP);
