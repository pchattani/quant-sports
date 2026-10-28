/* The Quant Ace — the player lab (#/<T>/lab).
 *
 * The football and Hardwood labs adapted to tennis: scatter any two metrics of the player
 * catalogue for one year or a rolling window of years, optionally on one surface, with presets
 * for the pairs that separate kinds of player, marker size by matches, colour by country,
 * year, surface or any metric, medians splitting the chart into quadrants, the players
 * furthest into the good corner labelled, a search highlight, and the group ranked underneath.
 * Small samples can be shrunk towards the median of the players on screen with a prior of
 * SHRINK_K matches, as the football lab does with its 450-minute prior.
 *
 * Address: ?x=<key>&y=<key> preset the axes; ?within=pos&pos=hard|clay|grass compares within one surface.
 *
 * "Compare within" (QK.within): Broad (the default) is the tour, every player over the match floor for the year or
 * window; Surface is the metrics spec's surface peer groups (atp_hard ... wta_grass), read from the payload's
 * "surface" block (rows per player-year-surface): the scatter, ranks, in-page percentiles, medians, presets, the
 * metric picker (the group's spec headline first) and the default minimum (the spec floor: 10 hard, 8 clay, 5 grass
 * matches) follow the group. Ratings the block does not carry (Elo, surface Elo, rank, points) come from the
 * player's all-surface row of the same year. A highlighted player gets a "Most like" strip: the five nearest in
 * the group on the group's headline metrics (QK.within.similar), each a link to Compare.
 *
 * Data: data/<T>/lab.json, column-oriented {"fields": ["id","name","year","matches", ...metric keys],
 * "metrics": [METRIC], "rows": [[...]], "years": [...]}. An optional "surface" field (rows per
 * player-year-surface, "all" for the whole year) enables the surface filter. Uses TA.fk. */
(function (TA) {
'use strict';

const K = () => TA.fk;

/* Presets: [x candidates, y candidates, title, tour ('' = both)]. Candidates match keys (strings exact, then regexes). */
const PRESETS = [
  [['hold', /^hold/], ['brk', 'break', /^br(ea)?k/], 'Hold % against break %: the two halves of the game', ''],
  [['spw_exp', 'xspw', /x_?spw|spw_?(exp|inf)/], ['spw_real', 'spw', /^spw$/], 'Inferred against real serve points won: does the score model see the serve?', 'wta'],
  [['rpw_exp', 'xrpw', /x_?rpw|rpw_?exp/], ['rpw_real', 'rpw', /^rpw$/], 'Inferred against real return points won', 'wta'],
  [['rank', /^rank$/, 'points', /^points$/, 'elo_rank'], ['tb_over', /tb.*(over|exp)/], 'Tiebreak wins over expected against ranking', ''],
  [['ace_pct', /^ace/], ['first_won', /first_?won|1st_?won/], 'Aces against first-serve points won', 'wta'],
  [['rank', /^rank$/, 'points', /^points$/], ['elo', /^elo$/], 'Elo against the official ranking', ''],
  [['serve_rating', /serve_?r/], ['return_rating', /return_?r/], 'Serve rating against return rating', ''],
  [['win_pct', /win_?pct/], ['wins_over_exp', 'over_exp', /over_?exp/], 'Win % against wins over expected: who beats our forecasts?', ''],
  [['hold_real', /hold_?real/], ['hold', /^hold$/], 'Real against inferred hold % (WTA stats)', 'wta'],
  [['first_in', /first_?in/], ['second_won', /second_?won|2nd/], 'First serves in against second-serve points won', 'wta'],
  [['rally_len', /rally_?len/], ['winners_pp', 'winners_pt', /winner/], 'Rally length against winners per point (charted players)', ''],
  [['tb_pct', 'tb_win', /tb_?win/], ['dec_pct', 'deciding_win', /decid/], 'Tiebreaks against deciding sets', ''],
  [['elo_hard', /elo_?hard/], ['elo_clay', /elo_?clay/], 'Hard-court Elo against clay Elo', '']
];
const SHRINK_K = 15;    // matches of prior: a player with 15 matches sits halfway between the median and her own rate
const NO_SHRINK = /^(matches|year|age|rank|points|race_points|to_defend)$|elo|rating|_se$|_rank$/;
const LATEST = /elo|rating|^rank$|^points$|race_points|^age$|to_defend/;
const SUM = /^(w|l|matches)$|_over$|over_exp$/;   // plus every fmt 'int' count
const SURFS = ['hard', 'clay', 'grass'];
const SURF_FLOOR = { hard: 10, clay: 8, grass: 5 };               // the spec's minimum when the labels file is missing
const SURF_COPY = /^(name|rank|best_rank|points|elo.*)$/;          // ratings a surface row takes from the year's all-surface row

let LAB = null, LABT = null;
let S = { win: null, within: 'broad', surf: 'all', min: 10, shrink: true, preset: 0, x: '', y: '', color: 'country', q: '' };
const MU = {};

function prep(raw) {
  const k = K(), idx = {};
  (raw.fields || []).forEach((f, i) => { idx[f] = i; });
  const al = (want, list) => { if (idx[want] === undefined) for (let i = 0; i < list.length; i++) if (idx[list[i]] !== undefined) { idx[want] = idx[list[i]]; break; } };
  al('id', ['pid', 'player', 'player_id']); al('year', ['season', 'window']); al('matches', ['n', 'm', 'played']);
  const meta = {};
  (raw.metrics || []).forEach(m => { meta[m.key] = specLabel(m); });
  meta.matches = meta.matches || { key: 'matches', label: 'Matches', fmt: 'int', group: 'Sample' };
  const ys = (raw.years && raw.years.length ? raw.years.slice() : Array.from(new Set((raw.rows || []).map(r => r[idx.year]))));
  const num = ys.filter(k.isNum).map(Number).sort((a, b) => b - a), lab = ys.filter(y => !k.isNum(y));
  /* the "surface" block (rows per player, year and surface, its own fields) in the main row layout */
  const sb = raw.surface && raw.surface.fields && (raw.surface.rows || []).length ? raw.surface : null;
  const srows = { hard: [], clay: [], grass: [] }, skeys = {};
  if (sb) {
    const SI = {};
    sb.fields.forEach((f, i) => { SI[f] = i; skeys[f] = 1; });
    const main = {};
    (raw.rows || []).forEach(r => { main[r[idx.id] + '|' + r[idx.year]] = r; });
    const fields = raw.fields || [];
    sb.rows.forEach(sr => {
      const sf = sr[SI.surface];
      if (!srows[sf]) return;
      const m = main[sr[SI.id] + '|' + sr[SI.year]] || null;
      srows[sf].push(fields.map((f, i) => (SI[f] !== undefined ? sr[SI[f]] : (m && SURF_COPY.test(f) ? m[i] : null))));
    });
    fields.forEach(f => { if (SURF_COPY.test(f)) skeys[f] = 1; });
  }
  return { idx: idx, meta: meta, metrics: (raw.metrics || []).filter(m => idx[m.key] !== undefined), rows: raw.rows || [], years: num, labels: lab,
    hasSurf: !!sb || idx.surface !== undefined, srows: sb ? srows : null, skeys: skeys, minMatches: k.isNum(raw.min_matches) ? raw.min_matches : 10 };
}
/* The spec's display name, unit and explanation for a payload metric (assets/qk/metrics/tennis.labels.json via
   TA.v2.spec); the payload's own label and description when the spec does not list it. */
function specLabel(m) {
  const c = TA.v2 && TA.v2.spec, sm = c ? c.metric(m.key, 'player') : null;
  if (!sm || sm.label === m.key || / on (hard|clay|grass)$/.test(sm.label)) return m;   // a surface group's name for an all-surface column
  const out = Object.assign({}, m);
  out.label = sm.label + (sm.unit === '%' && sm.label.indexOf('%') < 0 ? ' %' : '');
  if (sm.explain) out.desc = sm.explain;
  return out;
}
function resolve(pats) {
  const ms = LAB.metrics.concat(LAB.idx.rank !== undefined && !LAB.meta.rank ? [{ key: 'rank' }] : []);
  for (let i = 0; i < pats.length; i++) { const p = pats[i]; if (typeof p === 'string') { const m = ms.find(x => x.key === p); if (m) return m.key; } }
  for (let i = 0; i < pats.length; i++) { const p = pats[i]; if (p instanceof RegExp) { const m = ms.find(x => p.test(x.key)); if (m) return m.key; } }
  return '';
}
function presetList() { return PRESETS.filter(p => !p[3] || p[3] === LABT).map(p => ({ x: resolve(p[0]), y: resolve(p[1]), title: p[2] })).filter(p => p.x && p.y && p.x !== p.y && avail(p.x) && avail(p.y)); }
/* Surface mode: only the metrics the surface rows carry (their own fields, plus the ratings copied from the year's row) */
function bySurf() { return S.within === 'pos' && S.surf !== 'all'; }
function avail(key) { return !bySurf() || !LAB.srows || key === 'matches' || !!LAB.skeys[key]; }
function specGroup() { return TA.v2.group(LABT, bySurf() ? S.surf : null); }
function groupName() { const c = TA.v2.spec, g = c && c.group ? c.group(specGroup()) : null; return (g && g.display) || (K().TN(LABT) + (bySurf() ? ', ' + S.surf : '')); }
function surfFloor(sf) { const c = TA.v2.spec, g = c && c.group ? c.group(TA.v2.group(LABT, sf)) : null; const v = QK.within.floor(g); return K().isNum(v) ? v : SURF_FLOOR[sf]; }
/* the group's spec headline ids that this payload carries, in the spec's order */
function headKeys() { const c = TA.v2.spec; return (c ? c.headline(specGroup()) : []).filter(key => LAB.idx[key] !== undefined && avail(key)); }
function writeHash() {
  const h = String(location.hash || ''), qi = h.indexOf('?');
  const q = {};
  (qi >= 0 ? h.slice(qi + 1) : '').split('&').forEach(kv => { if (!kv) return; const i = kv.indexOf('='); q[i >= 0 ? kv.slice(0, i) : kv] = i >= 0 ? kv.slice(i + 1) : ''; });
  const w = QK.within.query({ within: bySurf() ? 'pos' : 'broad', pos: S.surf });
  delete q.within; delete q.pos;
  if (w.within) { q.within = w.within; q.pos = w.pos; }
  const qs = Object.keys(q).map(key => key + '=' + q[key]).join('&');
  try { history.replaceState(null, '', (qi >= 0 ? h.slice(0, qi) : h) + (qs ? '?' + qs : '')); } catch (e) { /* file:// */ }
}

function raw(r, key) { const i = LAB.idx[key]; if (i === undefined) return null; const v = r[i]; return v === null || v === undefined || (typeof v === 'number' && !isFinite(v)) ? null : v; }
function shrinkable(key) { const m = LAB.meta[key] || {}; return !NO_SHRINK.test(key) && m.fmt !== 'int' && m.fmt !== 'signed'; }
function lower(key) { return !!(LAB.meta[key] || {}).lower || key === 'rank'; }
function label(key) { const m = LAB.meta[key] || {}; return (m.label || (key === 'rank' ? 'Ranking' : key)) + (S.shrink && shrinkable(key) ? ' (shrunk)' : ''); }
function fmt(key, v) { return K().fmtV(v, (LAB.meta[key] || {}).fmt || (key === 'rank' ? 'int' : '')); }
function zs(a) { const n = a.length; if (!n) return { m: 0, s: 1 }; const m = a.reduce((x, y) => x + y, 0) / n; const v = a.reduce((x, y) => x + (y - m) * (y - m), 0) / n; return { m: m, s: Math.sqrt(v) || 1 }; }
function pctRank(sorted, v) { let lo = 0, hi = sorted.length; while (lo < hi) { const mid = (lo + hi) >> 1; if (sorted[mid] < v) lo = mid + 1; else hi = mid; } let up = lo; while (up < sorted.length && sorted[up] === v) up++; return sorted.length ? 100 * ((lo + up) / 2) / sorted.length : null; }

/* The rows for the window and surface; a multi-year window aggregates each player into one row:
 * rates matches-weighted, counts and over-expected figures summed, ratings and ranks from the latest year. */
function windowRows() {
  const k = K();
  const src = LAB.srows ? (S.surf !== 'all' ? (LAB.srows[S.surf] || []) : LAB.rows) : LAB.rows;
  const surfOk = r => LAB.srows || LAB.idx.surface === undefined || String(raw(r, 'surface') || 'all') === S.surf;
  if (typeof S.win === 'number' || (typeof S.win === 'string' && LAB.labels.indexOf(S.win) >= 0)) return src.filter(r => surfOk(r) && raw(r, 'year') === S.win);
  const n = S.win === 'all' ? LAB.years.length : parseInt(String(S.win).slice(4), 10);
  const yrs = LAB.years.slice(0, n);
  const by = {};
  src.forEach(r => { if (!surfOk(r) || yrs.indexOf(raw(r, 'year')) < 0) return; const id = raw(r, 'id'); (by[id] || (by[id] = [])).push(r); });
  const keys = Object.keys(LAB.idx);
  return Object.keys(by).map(id => {
    const rs = by[id].slice().sort((a, b) => raw(b, 'year') - raw(a, 'year'));
    const out = new Array(LAB.rows[0] ? LAB.rows[0].length : keys.length).fill(null);
    const set = (key, v) => { out[LAB.idx[key]] = v; };
    const tot = rs.reduce((s, r) => s + (raw(r, 'matches') || 0), 0);
    keys.forEach(key => {
      if (key === 'id' || key === 'name' || key === 'surface') { set(key, raw(rs[0], key)); return; }
      if (key === 'year') { set(key, rs.length > 1 ? raw(rs[rs.length - 1], 'year') + '–' + String(raw(rs[0], 'year')).slice(2) : raw(rs[0], 'year')); return; }
      if (key === 'matches') { set(key, tot); return; }
      const vals = rs.map(r => [raw(r, key), raw(r, 'matches') || 0]).filter(x => k.isNum(x[0]));
      if (!vals.length) return;
      if (LATEST.test(key)) set(key, vals[0][0]);
      else if (SUM.test(key) || (LAB.meta[key] || {}).fmt === 'int') set(key, vals.reduce((s, x) => s + Number(x[0]), 0));
      else { const w = vals.reduce((s, x) => s + x[1], 0); set(key, w ? vals.reduce((s, x) => s + x[0] * x[1], 0) / w : k.mean(vals.map(x => x[0]))); }
    });
    return out;
  });
}
function val(r, key) {
  const v = raw(r, key);
  if (v === null || !S.shrink || !shrinkable(key)) return v;
  const mu = MU[key];
  if (!K().isNum(mu)) return v;
  const n = raw(r, 'matches') || 0;
  return (n * v + SHRINK_K * mu) / (n + SHRINK_K);
}

function metricOptions(sel, scope) {
  const k = K();
  let h = scope === 'color' ? '<option value="country">Country</option><option value="year">Year</option>' + (LAB.hasSurf ? '' : '') + '<option value="">One colour</option>' : '';
  const extra = m => (m.scope === 'wta_stats' ? ' ·stats' : m.scope === 'charted' ? ' ·charted' : '');
  const hk = headKeys(), ms = LAB.metrics.filter(m => avail(m.key)).map(m => LAB.meta[m.key] || m);
  if (hk.length) h += '<optgroup label="Headline: ' + k.esc(groupName()) + '">' + hk.map(key => { const m = LAB.meta[key] || { key: key, label: key }; return '<option value="' + k.esc(key) + '"' + (key === sel ? ' selected' : '') + '>' + k.esc(m.label || key) + (m.lower ? ' ↓' : '') + extra(m) + '</option>'; }).join('') + '</optgroup>';
  h += TA.v2.picker(ms.filter(m => hk.indexOf(m.key) < 0), sel, k.groups, extra);
  if (!scope) h += '<optgroup label="Sample"><option value="matches"' + (sel === 'matches' ? ' selected' : '') + '>Matches</option>' + (LAB.idx.rank !== undefined && !LAB.meta.rank ? '<option value="rank"' + (sel === 'rank' ? ' selected' : '') + '>Ranking</option>' : '') + '</optgroup>';
  return h;
}

function sync() {
  const k = K(), $ = id => document.getElementById(id), P = presetList();
  $('lab-win').innerHTML = LAB.years.map(y => '<option value="' + y + '"' + (y === S.win ? ' selected' : '') + '>' + y + '</option>').join('') +
    LAB.labels.map(y => '<option value="' + k.esc(y) + '"' + (y === S.win ? ' selected' : '') + '>' + k.esc(y) + '</option>').join('') +
    [2, 3, 5].filter(n => LAB.years.length > n - 1 && n > 1).map(n => '<option value="last' + n + '"' + (S.win === 'last' + n ? ' selected' : '') + '>Last ' + n + ' years (combined)</option>').join('') +
    (LAB.years.length > 1 ? '<option value="all"' + (S.win === 'all' ? ' selected' : '') + '>Every year on file, combined</option>' : '');
  $('lab-wn-host').innerHTML = LAB.srows ? QK.within.html({ within: bySurf() ? 'pos' : 'broad', pos: bySurf() ? S.surf : 'hard' }, { id: 'lab-wn', pos: 'Surface',
    groups: SURFS.map(sf => [sf, sf.charAt(0).toUpperCase() + sf.slice(1)]),
    note: bySurf() ? k.esc(groupName()) + ': matches on ' + S.surf + ' only, ' + surfFloor(S.surf) + '+ by default (the metrics spec)' : k.esc(k.TN(LABT)) + ', every surface' }) : '';
  if (LAB.srows) QK.within.wire($('lab-wn-host'), { within: bySurf() ? 'pos' : 'broad', pos: bySurf() ? S.surf : 'hard' }, w => {
    S.within = w.within; S.surf = w.within === 'pos' ? w.pos : 'all';
    S.min = bySurf() ? surfFloor(S.surf) : LAB.minMatches;
    if (!avail(S.x) || !avail(S.y)) { S.preset = 0; applyPreset(); }
    else S.preset = presetList().findIndex(p => p.x === S.x && p.y === S.y);
    if (S.color && S.color !== 'country' && S.color !== 'year' && !avail(S.color)) S.color = 'country';
    if (LAB.rewin) LAB.rewin();
    sync(); draw();
  }, { id: 'lab-wn' });
  $('lab-preset').innerHTML = P.map((p, i) => '<option value="' + i + '"' + (i === S.preset ? ' selected' : '') + '>' + k.esc(p.title) + '</option>').join('') + '<option value="-1"' + (S.preset < 0 ? ' selected' : '') + '>Custom axes</option>';
  $('lab-x').innerHTML = metricOptions(S.x); $('lab-y').innerHTML = metricOptions(S.y);
  $('lab-x').value = S.x; $('lab-y').value = S.y;
  $('lab-color').innerHTML = metricOptions(S.color, 'color'); $('lab-color').value = S.color;
  $('lab-min').value = S.min; $('lab-min-v').textContent = S.min;
  $('lab-shrink').checked = S.shrink; $('lab-q').value = S.q;
}
function applyPreset() {
  const P = presetList();
  if (S.preset < 0 || !P.length) return;
  const p = P[S.preset] || P[0];
  S.x = p.x; S.y = p.y;
}

function draw() {
  const k = K(), C = k.C, T = LABT;
  const base0 = windowRows().filter(r => (raw(r, 'matches') || 0) >= S.min);
  Object.keys(MU).forEach(key => delete MU[key]);
  [S.x, S.y, S.color].forEach(key => { if (key && LAB.idx[key] !== undefined && shrinkable(key)) MU[key] = k.median(base0.map(r => raw(r, key))); });
  const rows = base0.filter(r => val(r, S.x) !== null && val(r, S.y) !== null);
  const set = (id, h) => { const e = document.getElementById(id); if (e) e.innerHTML = h; };
  const multi = typeof S.win === 'string' && LAB.labels.indexOf(S.win) < 0;
  writeHash();
  set('lab-sub', rows.length + ' players' + (multi ? ' (' + (S.win === 'all' ? 'every year on file' : 'last ' + S.win.slice(4) + ' years') + ', combined)' : ' in ' + k.esc(S.win)) + (LAB.hasSurf && S.surf !== 'all' ? ' on ' + S.surf : '') + ' with ' + S.min + '+ matches');
  if (rows.length < 3) { set('lab-chart', k.muted('Too few players for this view: lower the match floor, widen the window, compare within the broad group (every surface), or pick metrics that exist for these players (real serve stats are WTA only; style metrics need charted matches).')); set('lab-table', ''); set('lab-note', ''); set('lab-sim', ''); return; }
  const xs = rows.map(r => val(r, S.x)), ys = rows.map(r => val(r, S.y));
  const mx = k.median(xs), my = k.median(ys), sx = zs(xs), sy = zs(ys);
  const dirx = lower(S.x) ? -1 : 1, diry = lower(S.y) ? -1 : 1;
  const score = r => dirx * (val(r, S.x) - sx.m) / sx.s + diry * (val(r, S.y) - sy.m) / sy.s;
  const ranked = rows.map(r => ({ r: r, z: score(r) })).sort((a, b) => b.z - a.z);
  const q = S.q.trim().toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
  const nm = r => raw(r, 'name') || k.name(T, raw(r, 'id'));
  const ctry = r => raw(r, 'country') || k.country(T, raw(r, 'id')) || '—';
  const fold = t => String(t).toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
  const hits = q ? rows.filter(r => fold(nm(r) + ' ' + ctry(r)).indexOf(q) >= 0) : [];
  /* "Most like": the player the search names (by name, not country), against the group over the floor */
  const who = q ? rows.filter(r => fold(nm(r)).indexOf(q) >= 0)[0] : null;
  if (!who) set('lab-sim', '<p class="pg-note ta-lab-simhint">Highlight a player to list the five most like them in ' + k.esc(groupName()) + ' on this chart.</p>');
  else {
    const near = QK.within.similar(base0, who, headKeys(), (r, key) => raw(r, key), 5);
    set('lab-sim', QK.within.simHtml('Most like ' + nm(who) + ' · ' + groupName(), near.map(o => ({ name: nm(o.row), href: k.compareHref(T, raw(who, 'id'), raw(o.row, 'id')),
      sub: ctry(o.row) + ' · ' + (raw(o.row, 'matches') || 0) + ' matches · compare' }))) || '<p class="pg-note ta-lab-simhint">Too few players share the headline metrics with ' + k.esc(nm(who)) + ' here.</p>');
  }
  const labelled = new Set(ranked.slice(0, 8).map(o => o.r).concat(ranked.slice(-4).map(o => o.r)).concat(hits.slice(0, 20)));
  const sortedX = xs.slice().sort((a, b) => a - b), sortedY = ys.slice().sort((a, b) => a - b);
  const pOf = (sorted, v, dir) => { const p = pctRank(sorted, v); return dir > 0 ? p : 100 - p; };
  const ns = rows.map(r => raw(r, 'matches') || 0), lo = Math.min.apply(null, ns), hi = Math.max.apply(null, ns);
  const size = r => 6 + 14 * (hi > lo ? Math.sqrt(((raw(r, 'matches') || 0) - lo) / (hi - lo)) : 0.5);
  const hover = r => '<b>' + k.esc(nm(r)) + '</b> · ' + k.esc(ctry(r)) + ' · ' + k.esc(raw(r, 'year')) + ' · ' + (raw(r, 'matches') || 0) + ' matches' +
    '<br>' + k.esc(label(S.x)) + ': ' + fmt(S.x, val(r, S.x)) + ' (pct ' + Math.round(pOf(sortedX, val(r, S.x), dirx)) + ')' +
    '<br>' + k.esc(label(S.y)) + ': ' + fmt(S.y, val(r, S.y)) + ' (pct ' + Math.round(pOf(sortedY, val(r, S.y), diry)) + ')' +
    (S.shrink && (shrinkable(S.x) || shrinkable(S.y)) ? '<br><span style="color:#8b949e">unshrunk: ' + fmt(S.x, raw(r, S.x)) + ' · ' + fmt(S.y, raw(r, S.y)) + '</span>' : '');
  // the chart: QKC (ECharts) scatter, Design System 2.0. Groups (country, year) are series with a legend; a metric colour
  // runs on the percentile scale (cold = worse, hot = better); medians dotted; the y = x line where both axes are one rate.
  const diag = (/spw|rpw/.test(S.x) && /spw|rpw/.test(S.y)) || (/^hold/.test(S.x) && /^hold/.test(S.y));
  const lim = diag ? [Math.min(Math.min.apply(null, xs), Math.min.apply(null, ys)), Math.max(Math.max.apply(null, xs), Math.max.apply(null, ys))] : null;
  const pf = key => ((LAB.meta[key] || {}).fmt === 'pct' ? (v => Math.round(v * 100) + '%') : (v => (Math.abs(v) >= 100 ? String(Math.round(v)) : Number(v).toFixed(2))));
  const groups = [];
  if (S.color === 'country') {
    const cnt = {};
    rows.forEach(r => { cnt[ctry(r)] = (cnt[ctry(r)] || 0) + 1; });
    const top = Object.keys(cnt).sort((a, b) => cnt[b] - cnt[a]).slice(0, 8);
    top.forEach((c, i) => groups.push({ name: c + ' (' + cnt[c] + ')', rows: rows.filter(r => ctry(r) === c), color: i }));
    const rest = rows.filter(r => top.indexOf(ctry(r)) < 0);
    if (rest.length) groups.push({ name: 'Other countries', rows: rest, color: 'other' });
  } else if (S.color === 'year') {
    Array.from(new Set(rows.map(r => String(raw(r, 'year'))))).sort().forEach((y, i) => groups.push({ name: y, rows: rows.filter(r => String(raw(r, 'year')) === y), color: i }));
  } else groups.push({ name: S.color ? label(S.color) : 'Players', rows: rows, color: S.color ? 'metric' : 'signal' });
  const cvals = S.color && S.color !== 'country' && S.color !== 'year' ? rows.map(r => val(r, S.color)).filter(v => v !== null).sort((a, b) => a - b) : null;
  const cdir = S.color && lower(S.color) ? -1 : 1;
  const chart = document.getElementById('lab-chart');
  chart.classList.add('qk-chart');
  const byId = {};
  rows.forEach(r => { byId[raw(r, 'id') + '|' + raw(r, 'year')] = r; });
  QKC.mount(chart, Tk => {
    const colOf = (g, r) => {
      if (g.color === 'metric') { const v = val(r, S.color); return v === null ? Tk.ink3 : QK.pctHex(pOf(cvals, v, cdir)); }
      if (g.color === 'signal') return LAB.hasSurf && S.surf !== 'all' ? (TA.v2.SURF_HEX[S.surf] || Tk.model) : Tk.model;
      if (g.color === 'other') return Tk.ink3;
      return Tk.cat[g.color % 8];
    };
    const xa = QKC.axis(Tk, { name: label(S.x), nameLocation: 'middle', nameGap: 28, scale: true, inverse: lower(S.x), fmt: pf(S.x), line: true });
    const ya = QKC.axis(Tk, { name: label(S.y), scale: true, inverse: lower(S.y), fmt: pf(S.y), nameAlign: 'left', nameLocation: lower(S.y) ? 'start' : 'end' });
    const series = groups.map((g, gi) => ({
      type: 'scatter', name: g.name, itemStyle: { color: g.rows.length ? colOf(g, g.rows[0]) : Tk.model },
      data: g.rows.map(r => ({ value: [val(r, S.x), val(r, S.y)], id: raw(r, 'id') + '|' + raw(r, 'year'), symbolSize: size(r),
        itemStyle: { color: QKC.hexA(colOf(g, r), 0.82), borderColor: Tk.s1, borderWidth: 0.7 },
        label: { show: labelled.has(r), formatter: k.surname(nm(r)), position: 'top', distance: 3, color: hits.indexOf(r) >= 0 ? Tk.ink1 : Tk.ink2, fontSize: 10, fontWeight: hits.indexOf(r) >= 0 ? 700 : 500 } })),
      labelLayout: { hideOverlap: true },
      markLine: gi === 0 ? { silent: true, symbol: 'none', animation: false, label: { show: false }, data: [{ xAxis: mx, lineStyle: { color: Tk.axis, type: [3, 4] } }, { yAxis: my, lineStyle: { color: Tk.axis, type: [3, 4] } }]
        .concat(diag ? [[{ coord: [lim[0], lim[0]], lineStyle: { color: Tk.ink3, type: 'dashed' } }, { coord: [lim[1], lim[1]] }]] : []) } : undefined
    }));
    if (hits.length) series.push({ type: 'scatter', name: '_search', silent: true, tooltip: { show: false }, z: 5,
      data: hits.map(r => ({ value: [val(r, S.x), val(r, S.y)], symbolSize: size(r) + 10 })), itemStyle: { color: 'transparent', borderColor: Tk.ink1, borderWidth: 2 } });
    return {
      grid: { left: 8, right: 18, top: 34, bottom: groups.length > 1 ? 70 : 34, containLabel: true }, xAxis: xa, yAxis: ya,
      legend: groups.length > 1 ? { bottom: 0, left: 0, type: 'scroll', textStyle: { color: Tk.ink2 }, itemWidth: 10, itemHeight: 10, data: groups.map(g => g.name) } : undefined,
      tooltip: QKC.tooltip(Tk, { formatter: p => { const r = byId[(p.data || {}).id]; return r ? hover(r) : ''; } }),
      series: series
    };
  }, { label: label(S.y) + ' against ' + label(S.x) });
  const inst = window.echarts && echarts.getInstanceByDom(chart);
  if (inst) { inst.off('click'); inst.on('click', ev => { const id = String(((ev.data || {}).id) || '').split('|')[0]; if (id) location.hash = k.playerHref(T, id); }); }
  const mX = LAB.meta[S.x] || {}, mY = LAB.meta[S.y] || {};
  set('lab-note', 'Dotted lines are the medians of the players on screen (' + k.esc(groupName()) + '). ' + (lower(S.x) || lower(S.y) ? 'Axes where less is better (and the ranking) are reversed, so better is always up and to the right. ' : 'Better is up and to the right. ') +
    (diag ? 'The dashed diagonal is equality: a dot above it won more points on serve than the score model inferred. ' : '') +
    'Labelled: the eight players furthest into the good corner and the four furthest from it (sum of standard scores on both axes)' + (hits.length ? ', and your search (ringed)' : '') + '. Marker size is matches' + (S.color && S.color !== 'country' && S.color !== 'year' ? '; colour is the percentile of ' + k.esc(label(S.color)) + ' on screen (blue worse, red better)' : '') + '. Click a dot to open the player.' +
    (S.shrink ? ' Rates marked "shrunk" are pulled towards the median of the players on screen by ' + SHRINK_K + ' matches of prior, (matches × rate + ' + SHRINK_K + ' × median) / (matches + ' + SHRINK_K + '), so a player with five matches is not ranked on five matches alone; hover shows the raw figures. Ratings, Elo, ranks and counts are never shrunk: the models behind them already regularise.' : '') +
    (multi ? ' A combined window sums counts and over-expected figures, averages rates weighted by matches, and takes ratings and ranks from the latest year.' : '') +
    (mX.desc ? '<br><strong>' + k.esc(mX.label) + '</strong>' + TA.v2.oursTag(S.x) + ': ' + k.esc(mX.desc) : '') + (mY.desc ? '<br><strong>' + k.esc(mY.label) + '</strong>' + TA.v2.oursTag(S.y) + ': ' + k.esc(mY.desc) : ''));
  const ox = TA.v2.ours(S.x), oy = TA.v2.ours(S.y), models = [];
  [ox, oy].forEach(o => { if (o && models.every(x => x.key !== o.key)) models.push(o); });
  set('lab-ours', models.length ? QK.oursExplain(models.map(o => '<b>' + k.esc(o.name) + '.</b> ' + k.esc(o.about)).join(' '), { title: models.length > 1 ? 'Our models.' : 'Our model.' })
    : QK.explain('Neither axis comes from our models. Elo, surface Elo, the serve and return ratings and the hold and break they imply are ours: they lead every metric list, tagged ' + QK.ours({ short: true }) + '.'));
  const host = document.getElementById('lab-table');
  host.innerHTML = k.table([
    { label: '#', sortable: false }, { label: 'Player' }, { label: 'Ctry' }, { label: 'Year', align: 'right' }, { label: 'Matches', align: 'right' },
    { label: label(S.x), align: 'right' }, { label: 'Pct', align: 'right' }, { label: label(S.y), align: 'right' }, { label: 'Pct', align: 'right' }, { label: 'Combined', align: 'right', title: 'Sum of standard scores in the better direction' }
  ], ranked.slice(0, 300).map((o, i) => {
    const r = o.r, vx = val(r, S.x), vy = val(r, S.y);
    return { _href: k.playerHref(T, raw(r, 'id')), cells: [
      { v: i + 1, cls: 'pos-cell' }, { v: nm(r), html: k.playerLink(T, raw(r, 'id'), nm(r)) }, { v: ctry(r), html: k.ctry(ctry(r)) },
      { v: String(raw(r, 'year')), html: k.esc(raw(r, 'year')) }, { v: raw(r, 'matches'), html: String(raw(r, 'matches') || 0) },
      { v: vx, html: fmt(S.x, vx) }, { v: pOf(sortedX, vx, dirx), html: k.pill(pOf(sortedX, vx, dirx)) }, { v: vy, html: fmt(S.y, vy) }, { v: pOf(sortedY, vy, diry), html: k.pill(pOf(sortedY, vy, diry)) },
      { v: o.z, html: '<strong>' + k.num(o.z, 2) + '</strong>' }
    ] };
  }), { sticky: true, compact: true });
  k.sortable(host);
  const hm = {}; hm[label(S.x)] = S.x; hm[label(S.y)] = S.y;
  TA.v2.oursHeads(host, hm);
}

function render(el, params, state) {
  const k = K(), T = k.T(params, state);
  el.innerHTML = '<div class="card"><div class="card-header">' + k.TN(T) + ' player lab <span class="card-sub" id="lab-sub">Loading…</span></div>' +
    '<div id="lab-wn-host" class="ta-lab-within"></div>' +
    '<div class="lab-controls af-controls">' +
    '<label>Years<select id="lab-win"></select></label>' +
    '<label>Preset<select id="lab-preset" class="af-wide"></select></label>' +
    '<label>X axis<select id="lab-x"></select></label>' +
    '<label>Y axis<select id="lab-y"></select></label>' +
    '<label>&nbsp;<button type="button" id="lab-swap" title="Swap the axes">⇄ swap</button></label>' +
    '<label>Colour<select id="lab-color"></select></label>' +
    '<label>Min matches <span id="lab-min-v"></span><input id="lab-min" type="range" min="0" max="80" step="1"></label>' +
    '<label class="inline"><input id="lab-shrink" type="checkbox"> shrink small samples</label>' +
    '<label>Highlight<input id="lab-q" class="pg-search" type="search" placeholder="player or country…"></label>' +
    '</div><div id="lab-chart" class="af-lab-chart qk-chart" style="--h:520px" role="img" aria-label="Scatter of the two chosen metrics"></div><div id="lab-sim" class="ta-lab-sim"></div><div class="pg-note" id="lab-note"></div><div id="lab-ours" class="af-lab-ours"></div></div>' +
    '<div class="card"><div class="card-header">Ranked <span class="card-sub">The group by the combined standard score on both axes (top 300). Click a row for the player.</span></div><div id="lab-table"></div></div>';
  return k.ready().then(() => Promise.all([TA.load(T + '/lab.json'), k.loadNames(T), TA.v2.specP])).then(res => {
    if (!k.alive(el)) return;
    const rawLab = res[0];
    if (!rawLab || rawLab.ok === false || !(rawLab.rows || []).length) { document.getElementById('lab-chart').innerHTML = k.notBuilt('The ' + k.TN(T) + ' lab file', rawLab); document.getElementById('lab-sub').textContent = ''; return; }
    if (LABT !== T) { S.win = null; S.x = ''; S.y = ''; S.preset = 0; }
    LAB = prep(rawLab); LABT = T;
    const Y = k.Y(params, state, T);
    if (S.win === null || (typeof S.win === 'number' && LAB.years.indexOf(S.win) < 0)) S.win = LAB.years.indexOf(Y) >= 0 ? Y : (LAB.years[0] !== undefined ? LAB.years[0] : LAB.labels[0]);
    const qw = QK.within.read(params.query || {}, LAB.srows ? SURFS : []);
    const was = S.within + '|' + S.surf;
    S.within = qw.within; S.surf = qw.within === 'pos' ? qw.pos : 'all';
    if (was !== S.within + '|' + S.surf) S.min = bySurf() ? surfFloor(S.surf) : LAB.minMatches;
    const maxN = Math.max.apply(null, windowRows().map(r => raw(r, 'matches') || 0).concat([10]));
    if (S.min > maxN * 0.5) S.min = Math.max(0, Math.round(maxN * 0.2));
    document.getElementById('lab-min').max = String(Math.max(40, Math.ceil(maxN / 10) * 10));
    const qy = params.query || {};
    if (typeof qy.q === 'string') S.q = qy.q;                    // ?q= highlights a player (shared links)
    if (qy.x && LAB.idx[qy.x] !== undefined) { S.x = qy.x; S.preset = -1; }
    if (qy.y && LAB.idx[qy.y] !== undefined) { S.y = qy.y; S.preset = -1; }
    if (!S.x || LAB.idx[S.x] === undefined || !S.y || LAB.idx[S.y] === undefined) { if (S.preset < 0) S.preset = 0; applyPreset(); }
    if (!S.x || !S.y) { const ms = LAB.metrics; S.x = (ms[0] || {}).key || 'matches'; S.y = (ms[1] || {}).key || 'matches'; S.preset = -1; }
    sync();
    const $ = id => document.getElementById(id);
    const rewin = () => { const mx2 = Math.max.apply(null, windowRows().map(r => raw(r, 'matches') || 0).concat([10])); $('lab-min').max = String(Math.max(40, Math.ceil(mx2 / 10) * 10)); if (S.min > mx2) { S.min = Math.round(mx2 * 0.2); } };
    $('lab-win').onchange = e => { const v = e.target.value; S.win = /^\d+$/.test(v) ? parseInt(v, 10) : v; rewin(); sync(); draw(); };
    LAB.rewin = rewin;
    $('lab-preset').onchange = e => { S.preset = parseInt(e.target.value, 10); applyPreset(); sync(); draw(); };
    $('lab-x').onchange = e => { S.x = e.target.value; S.preset = -1; sync(); draw(); };
    $('lab-y').onchange = e => { S.y = e.target.value; S.preset = -1; sync(); draw(); };
    $('lab-swap').onclick = () => { const t = S.x; S.x = S.y; S.y = t; S.preset = -1; sync(); draw(); };
    $('lab-color').onchange = e => { S.color = e.target.value; draw(); };
    $('lab-min').oninput = e => { S.min = parseInt(e.target.value, 10); $('lab-min-v').textContent = S.min; };
    $('lab-min').onchange = () => draw();
    $('lab-shrink').onchange = e => { S.shrink = e.target.checked; draw(); };
    let timer = null;
    $('lab-q').oninput = e => { S.q = e.target.value; clearTimeout(timer); timer = setTimeout(draw, 250); };
    draw();
  });
}

if (typeof TA.route === 'function') TA.route('lab', render);
})(window.TA || (window.TA = {}));
