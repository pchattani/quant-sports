/* The Quant Hardwood — the Player lab (#/<L>/lab).
 *
 * The football and F1 labs adapted to basketball: scatter any two metrics of the player
 * catalogue for one season or a window of seasons, filtered by position pool and minutes,
 * with presets for the pairs that separate kinds of player, marker size by minutes and
 * colour by team, pool, season or any metric, medians splitting the chart into quadrants,
 * the players furthest into the good corner labelled, a search highlight, and the group
 * ranked underneath. Small samples can be shrunk towards the pool median with a prior of
 * SHRINK_K minutes, as the football lab does with its 450-minute prior.
 *
 * "Compare within" (QK.within): Broad (the default) is today's grouping, every player or one listed position pool
 * (guards, forwards, centres); Position is the metrics spec's role peer groups (basketball.json guards, wings, bigs:
 * the rows' `role`, value.classify_roles) at the spec's floor (the payload's `qualified`: the season's min_floor), and
 * the scatter, ranks, percentiles, medians, shrinkage medians, metric order and the "Most like" strip follow the
 * group. Address: #/<L>/lab?within=pos&pos=G|W|B (also pool, x, y, q), written back with history.replaceState.
 * Position mode opens on the spec group's default view (QK.within.view): what makes the role good (playmaking for
 * guards, two-way play for wings, rim and glass for bigs) against its scoring, coloured by overall value (HPM). The
 * pickers and presets lead with the view's three sets, the ranked table adds the value column, and "Most like" uses
 * the view's metrics. Explicit x / y in the address still win. Broad is unchanged.
 *
 * Data: data/<L>/lab.json (or data/<L>/<S>/lab.json), column-oriented:
 * {fields: [id, name, team, season, pool, gp, min, qualified, role, ...metric keys], metrics, rows, years}; a payload
 * without `role` falls back to the listed pool (G -> guards, C -> bigs, F -> wings). */
(function (HW) {
'use strict';

const FX = () => HW.fx;

/* Presets: [x candidates, y candidates, title, {color}]; candidates are matched in order against metric keys, then labels. */
const PRESETS = [
  [['hpm_o', 'o_hpm', /hpm_?o/], ['hpm_d', 'd_hpm', /hpm_?d/], 'Our impact model at both ends: offensive against defensive HPM'],
  [['min', /^min$/], ['war', /^war$/], 'Wins above replacement against minutes: our value model'],
  [['box_impact', /box/], ['rapm', /^rapm/], 'Box score against RAPM: does the box agree with the lineups?'],
  [['pox100', 'pox', 'shot_making', 'pox_100', /pox|shot_?making|over_?exp/], ['xpps', 'xefg', 'shot_difficulty', /xpps|xefg|difficult|xpts/], 'Shot-making against shot difficulty (expected points per shot)'],
  [['usg', 'usg_pct', /usg|usage/], ['ts', 'ts_pct', /^ts/], 'Usage against true shooting'],
  [['blk_pct', /blk/], ['hpm_d', 'd_hpm', /hpm_?d/], 'Rim protection: block rate against defensive HPM'],
  [['hpm', 'hpm_t', /^hpm$/], ['on_off', 'on_off_net', 'on_off_diff', /on_?off/], 'On/off against HPM'],
  [['tpar', 'tpa_rate', '3par', 'fg3a_rate', /3pa|tpa_?rate|three.*rate/], ['c3_freq', 'corner3_share', 'freq_corner3', 'corner3_freq', /corner|c3/], 'Three-point rate against corner-three share'],
  [['ast_pct', /ast_?pct|^ast%/], ['tov_pct', /tov/], 'Playmaking: assist rate against turnover rate'],
  [['rim_freq', 'freq_rim', /rim.*freq|freq.*rim/], ['ftr', 'ft_rate', /ftr|ft_?rate/], 'Pressure: rim attempts against free-throw rate'],
  [['trb_pct', 'reb_pct', /trb|reb_?pct/], ['blk_pct', /blk/], 'Bigs: rebound rate against block rate']
];
const SHRINK_K = 300;   // minutes of prior: a player with 300 minutes sits halfway between the pool median and his own rate
const NO_SHRINK = /^(gp|min|age|season|games|minutes)$/;

let LAB = null, LABL = null;
/* Round 9 (28 Oct 2026): the Lab is the Scouting Room's Chart view (hw-scout.js). HW.lab.mount(host, L, S, ext) draws the
   same chart, presets, colour, shrink, medians, labels, ranked table and "Most like" inside the room, without its own
   group, season, minimum, qualified and highlight controls: those come from the room's one bar. ext = { within
   ('broad' | 'pos'), role ('G' | 'W' | 'B'), min (minutes; null: the season's qualified players), q, x, y, color,
   keep(get) -> bool (the room's team and age filters; get(field) reads the row), onPick(pid, season) (a point opens the
   room's profile drawer), onAxes({ x, y, color }) }. #/<L>/lab redirects to #/<L>/scout?view=chart (core.js). */
let EXT = null;
let S = { win: null, pool: 'all', min: 250, shrink: true, preset: 0, x: '', y: '', color: 'team', q: '', within: 'broad', role: 'G', qual: false };
/* "Compare within: Position": [address code, spec group suffix, fallback display] */
const RGROUPS = [['G', 'guards', 'Guards'], ['W', 'wings', 'Wings'], ['B', 'bigs', 'Bigs']];
const RCODES = RGROUPS.map(g => g[0]);
const POOL_ROLE = { G: 'G', C: 'B', F: 'W' };
const byPos = () => S.within === 'pos';
function rgroup(code) {
  const g = RGROUPS.find(x => x[0] === code) || RGROUPS[0];
  const cat = HW.ours && HW.ours.cat ? HW.ours.cat() : null;
  const sg = cat && cat.group ? cat.group(LABL + '_' + g[1]) : null;
  return { code: g[0], id: LABL + '_' + g[1], name: (sg && sg.display) || g[2] };
}
function roleOf(r) { const v = raw(r, 'role'); return v || POOL_ROLE[raw(r, 'pool')] || 'W'; }
/* the shrinkage and median group of a row: its role under Position, its listed pool under Broad */
function grpKey(r) { return byPos() ? roleOf(r) : (raw(r, 'pool') || '_'); }
/* the spec group(s) whose headline metrics lead the pickers and drive "Most like" */
function groupIds() {
  if (byPos()) return [rgroup(S.role).id];
  const L = LABL;
  return S.pool === 'G' ? [L + '_guards'] : S.pool === 'C' ? [L + '_bigs'] : S.pool === 'F' ? [L + '_wings', L + '_bigs'] : [L + '_guards', L + '_wings', L + '_bigs'];
}
function headOrder() {
  const out = {}, cat = HW.ours && HW.ours.cat ? HW.ours.cat() : null;
  let n = 1;
  groupIds().forEach(id => { (cat ? cat.headline(id) : []).forEach(k => { if (out[k] === undefined) out[k] = n++; }); });
  return out;
}
function groupNoun() { return byPos() ? rgroup(S.role).name.toLowerCase() : ({ G: 'guards', F: 'forwards', C: 'centres' })[S.pool] || 'players'; }
/* the address: the within choice (or the Broad pool), the axes and the highlight; other keys kept */
function writeHash() {
  if (EXT) { if (EXT.onAxes) EXT.onAxes({ x: S.x, y: S.y, color: S.color }); return; }
  try {
    const h = String(location.hash || ''), qi = h.indexOf('?');
    const path = qi >= 0 ? h.slice(0, qi) : h, keep = [];
    (qi >= 0 ? h.slice(qi + 1).split('&') : []).forEach(kv => { const k = kv.split('=')[0]; if (kv && ['pool', 'pos', 'within', 'x', 'y', 'q'].indexOf(k) < 0) keep.push(kv); });
    const wq = QK.within.query({ within: S.within, pos: S.role });
    const add = { within: wq.within, pos: wq.pos, pool: !byPos() && S.pool !== 'all' ? S.pool : null, x: S.x || null, y: S.y || null, q: S.q.trim() || null };
    Object.keys(add).forEach(k => { if (add[k]) keep.push(k + '=' + encodeURIComponent(add[k])); });
    const nh = path + (keep.length ? '?' + keep.join('&') : '');
    if (path && nh !== h && window.history && history.replaceState) history.replaceState(null, '', nh);
  } catch (e) { /* the address is a convenience */ }
}
const MU = {};

function prep(raw) {
  const idx = {};
  (raw.fields || []).forEach((f, i) => { idx[f] = i; });
  const al = (want, list) => { if (idx[want] === undefined) for (let i = 0; i < list.length; i++) if (idx[list[i]] !== undefined) { idx[want] = idx[list[i]]; break; } };
  al('id', ['pid', 'player', 'player_id']); al('season', ['year']); al('min', ['minutes', 'mins']); al('gp', ['games', 'g']); al('pool', ['pos']);
  const meta = {};
  (raw.metrics || []).forEach(m => { meta[m.key] = m; });
  meta.min = meta.min || { key: 'min', label: 'Minutes', fmt: 'int' };
  meta.gp = meta.gp || { key: 'gp', label: 'Games', fmt: 'int' };
  const O = HW.ours;
  if (O && O.cat()) Object.keys(meta).forEach(k => { const r = O.row(k, 'player'); if (r) meta[k] = Object.assign({}, meta[k], { label: r[0], desc: r[6] || meta[k].desc, lower: r[2] === 'lower' }); });
  const years = (raw.years && raw.years.length ? raw.years.slice() : Array.from(new Set((raw.rows || []).map(r => r[idx.season])))).filter(v => FX().isNum(v)).map(Number).sort((a, b) => b - a);
  return { idx: idx, meta: meta, metrics: (raw.metrics || []).filter(m => idx[m.key] !== undefined).map(m => meta[m.key] || m), rows: raw.rows || [], years: years };
}
function resolve(pats) {
  const ms = LAB.metrics;
  for (let i = 0; i < pats.length; i++) { const p = pats[i]; if (typeof p === 'string') { const m = ms.find(x => x.key === p); if (m) return m.key; } }
  for (let i = 0; i < pats.length; i++) { const p = pats[i]; if (p instanceof RegExp) { const m = ms.find(x => p.test(x.key)); if (m) return m.key; } }
  for (let i = 0; i < pats.length; i++) { const p = pats[i]; if (p instanceof RegExp) { const m = ms.find(x => p.test(String(x.label || '').toLowerCase())); if (m) return m.key; } }
  return '';
}
/* Position mode: the view's presets (the default, excellence and scoring each against value, excellence against a
   second excellence metric) lead, then the lab's own. */
function presetList() {
  const base = PRESETS.map(p => ({ x: resolve(p[0]), y: resolve(p[1]), title: p[2] })).filter(p => p.x && p.y && p.x !== p.y);
  const v = posView();
  if (!v) return base;
  const nm = k => (LAB.meta[k] || {}).label || k;
  return QK.within.viewPresets(v, nm).map(p => ({ x: p.x, y: p.y, color: p.color, title: p.label, view: true })).concat(base);
}

/* The Position default view (QK.within.view on the spec group's `view`). Spec ids are the payload keys here. has(id):
   the lab carries the metric and at least VIEW_SHARE of the group on screen has a value for it (the role in the
   window when fewer than 3 rows clear the floors), so a default never opens on an empty chart; the kit then falls
   back to the next metric of the same set. */
const VIEW_SHARE = 0.3;
function posView() {
  if (!byPos() || !LAB) return null;
  const cat = HW.ours && HW.ours.cat ? HW.ours.cat() : null;
  const g = cat && cat.group ? cat.group(rgroup(S.role).id) : null;
  if (!g || !g.view) return null;
  let rows = pool();
  if (rows.length < 3) rows = LAB.rows.filter(r => inWindow(r) && roleOf(r) === S.role);
  const memo = {};
  const has = id => {
    if (memo[id] !== undefined) return memo[id];
    if (!LAB.metrics.some(m => m.key === id)) return (memo[id] = false);
    if (!rows.length) return (memo[id] = true);
    let n = 0;
    rows.forEach(r => { if (raw(r, id) !== null) n++; });
    return (memo[id] = n / rows.length >= VIEW_SHARE);
  };
  return QK.within.view(g, has);
}
/* entering Position, another role, or ?within=pos without axes: the view's x, y and colour (preset 0) */
function applyView() {
  const v = posView();
  S.preset = 0;
  if (!v || !v.x || !v.y) { applyPreset(); return; }
  S.x = v.x; S.y = v.y;
  if (v.color) S.color = v.color;
}
/* the ranked table's value column in Position mode: the view's colour metric, else its first aggregate, never X or Y */
function valueKey(v) {
  if (!v) return '';
  return [v.color].concat(v.sets[2].ids).filter(k => k && LAB.idx[k] !== undefined && k !== S.x && k !== S.y)[0] || '';
}

function raw(r, key) { const i = LAB.idx[key]; if (i === undefined) return null; const v = r[i]; return v === null || v === undefined || (typeof v === 'number' && !isFinite(v)) ? null : v; }
function shrinkable(key) { const m = LAB.meta[key] || {}; return !NO_SHRINK.test(key) && m.fmt !== 'int'; }
function val(r, key) {
  const v = raw(r, key);
  if (v === null || !S.shrink || !shrinkable(key)) return v;
  const mu = (MU[key] || {})[grpKey(r)];
  if (!FX().isNum(mu)) return v;
  const n = raw(r, 'min') || 0;
  return (n * v + SHRINK_K * mu) / (n + SHRINK_K);
}
function lower(key) { return !!(LAB.meta[key] || {}).lower; }
function label(key) { const m = LAB.meta[key] || {}; return (m.label || key) + (S.shrink && shrinkable(key) ? ' (shrunk)' : ''); }
function fmt(key, v) { return FX().fmtV(v, (LAB.meta[key] || {}).fmt); }
function stats(a) { const n = a.length; if (!n) return { m: 0, s: 1 }; const m = a.reduce((x, y) => x + y, 0) / n; const v = a.reduce((x, y) => x + (y - m) * (y - m), 0) / n; return { m: m, s: Math.sqrt(v) || 1 }; }
function pctRank(sorted, v) { let lo = 0, hi = sorted.length; while (lo < hi) { const mid = (lo + hi) >> 1; if (sorted[mid] < v) lo = mid + 1; else hi = mid; } let up = lo; while (up < sorted.length && sorted[up] === v) up++; return sorted.length ? 100 * ((lo + up) / 2) / sorted.length : null; }

function inWindow(r) {
  const y = raw(r, 'season');
  if (S.win === 'all') return true;
  if (typeof S.win === 'string' && S.win.indexOf('last') === 0) { const k = parseInt(S.win.slice(4), 10); return LAB.years.indexOf(y) >= 0 && LAB.years.indexOf(y) < k; }
  return y === S.win;
}
function pool() {
  const keep = EXT && EXT.keep ? r => EXT.keep(f => raw(r, f)) : null;
  return LAB.rows.filter(r => inWindow(r) && (raw(r, 'min') || 0) >= S.min && (!S.qual || raw(r, 'qualified') !== false) &&
    (byPos() ? roleOf(r) === S.role : (S.pool === 'all' || raw(r, 'pool') === S.pool)) && (!keep || keep(r)));
}

/* "Our models", then the peer group's spec headline metrics ("Key numbers · <group>", in the spec's order), then the
   payload's groups. */
function pickerGroups(ms) {
  const head = headOrder(), ours = [], key = [], rest = [];
  ms.forEach((m, i) => { const h = head[m.key] || 0, x = { m: m, h: h, i: i }; if (HW.ours.of(m.key)) ours.push(x); else if (h) key.push(x); else rest.push(x); });
  const cmp = (a, b) => ((a.h || 1e3) - (b.h || 1e3)) || (a.i - b.i);
  const out = [];
  if (ours.length) out.push({ name: 'Our models', items: ours.sort(cmp).map(x => x.m) });
  if (key.length) out.push({ name: 'Key numbers · ' + groupNoun(), items: key.sort(cmp).map(x => x.m) });
  rest.forEach(x => { const g = 'Box score · ' + (x.m.group || 'Other'); let b = out.find(y => y.name === g); if (!b) { b = { name: g, items: [] }; out.push(b); } b.items.push(x.m); });
  return out;
}
/* v (Position mode): the view's three sets lead as optgroups under the view's labels, then the colour groupings, then
   the lab's grouping of the rest ("Our models", key numbers, box score). */
function metricOptions(sel, scope, v) {
  const fx = FX();
  const cats = '<option value="team">Team</option><option value="pool">Position pool</option><option value="season">Season</option><option value="">One colour</option>';
  const opt = (m, tag) => '<option value="' + fx.esc(m.key) + '"' + (m.key === sel ? ' selected' : '') + '>' + fx.esc(m.label) + (m.lower ? ' ↓' : '') + (m.scope === 'pbp' ? ' ·pbp' : '') + (tag && HW.ours && HW.ours.of(m.key) ? ' · ours' : '') + '</option>';
  let h = scope === 'color' && !v ? cats : '', ms = LAB.metrics;
  if (v) {
    const r = QK.within.viewOrder(v, ms, m => m.key);
    r.sets.forEach(s => { h += '<optgroup label="' + fx.esc(s.label) + '">' + s.items.map(m => opt(m, true)).join('') + '</optgroup>'; });
    if (scope === 'color') h += '<optgroup label="Groups">' + cats + '</optgroup>';
    ms = r.rest;
  }
  (HW.ours ? pickerGroups(ms) : fx.groups(ms)).forEach(g => { h += '<optgroup label="' + fx.esc(g.name) + '">' + g.items.map(m => opt(m, false)).join('') + '</optgroup>'; });
  if (!scope) h += '<optgroup label="Sample"><option value="min"' + (sel === 'min' ? ' selected' : '') + '>Minutes</option><option value="gp"' + (sel === 'gp' ? ' selected' : '') + '>Games</option></optgroup>';
  return h;
}

function sync() {
  const fx = FX(), $ = id => document.getElementById(id), P = presetList(), v = posView();
  const yl = y => fx.seasonLabel(LABL, y);
  // the window or floors can change the list: keep the selected preset only while it still names the axes on screen
  if (S.preset >= 0 && (!P[S.preset] || P[S.preset].x !== S.x || P[S.preset].y !== S.y)) S.preset = P.findIndex(p => p.x === S.x && p.y === S.y);
  const nv = P.filter(p => p.view).length;
  const popt = (p, i) => '<option value="' + i + '"' + (i === S.preset ? ' selected' : '') + '>' + fx.esc(p.title) + '</option>';
  $('lab-win').innerHTML = LAB.years.map(y => '<option value="' + y + '"' + (y === S.win ? ' selected' : '') + '>' + fx.esc(yl(y)) + '</option>').join('') +
    (LAB.years.length > 2 ? '<option value="last3"' + (S.win === 'last3' ? ' selected' : '') + '>Last 3 seasons</option>' : '') +
    (LAB.years.length > 5 ? '<option value="last5"' + (S.win === 'last5' ? ' selected' : '') + '>Last 5 seasons</option>' : '') +
    '<option value="all"' + (S.win === 'all' ? ' selected' : '') + '>Every season since ' + fx.esc(yl(LAB.years[LAB.years.length - 1])) + '</option>';
  $('lab-preset').innerHTML = (nv ? '<optgroup label="' + fx.esc('Position view · ' + groupNoun()) + '">' + P.slice(0, nv).map(popt).join('') + '</optgroup><optgroup label="More pairs">' + P.slice(nv).map((p, i) => popt(p, i + nv)).join('') + '</optgroup>' : P.map(popt).join('')) +
    '<option value="-1"' + (S.preset < 0 ? ' selected' : '') + '>Custom axes</option>';
  $('lab-x').innerHTML = metricOptions(S.x, '', v); $('lab-y').innerHTML = metricOptions(S.y, '', v);
  $('lab-color').innerHTML = metricOptions(S.color, 'color', v); $('lab-color').value = S.color;
  $('lab-pool').value = S.pool; $('lab-pool').parentNode.style.display = byPos() ? 'none' : '';
  $('lab-qual').checked = S.qual;
  $('lab-within').innerHTML = QK.within.html({ within: S.within, pos: S.role }, { id: 'lab-wn', cls: 'hw-lab-within',
    groups: RGROUPS.map(g => [g[0], rgroup(g[0]).name]),
    note: byPos() ? 'Opens on what makes a ' + groupNoun().replace(/s$/, '') + ' good, their scoring and their overall value · role from play style (value model) · minimum: the spec’s floor, the season’s qualifying minutes' : 'Every player, or one listed position pool' }) +
    QK.within.viewWhy(v);
  QK.within.wire($('lab-within'), { within: S.within, pos: S.role }, w => {
    if (w.within === 'pos' && S.within !== 'pos') { w.pos = POOL_ROLE[S.pool] || S.role; S.qual = true; }
    if (w.within !== 'pos' && S.within === 'pos') { S.pool = ({ G: 'G', B: 'C', W: 'F' })[S.role] || 'all'; S.qual = false; }
    const fresh = w.within === 'pos' && (S.within !== 'pos' || w.pos !== S.role);
    S.within = w.within; S.role = w.pos;
    if (fresh) applyView();
    sync(); draw();
  }, { id: 'lab-wn' });
  $('lab-min').value = S.min; $('lab-min-v').textContent = S.min;
  $('lab-shrink').checked = S.shrink; $('lab-q').value = S.q;
}
function applyPreset() {
  const P = presetList();
  if (S.preset < 0 || !P.length) return;
  const p = P[S.preset] || P[0];
  S.x = p.x; S.y = p.y;
  // a view preset carries its colour; the "against value" ones colour by team rather than repeat an axis
  if (p.view) { if (p.color) S.color = p.color; else if (S.color === p.x || S.color === p.y) S.color = 'team'; }
}

function draw() {
  const fx = FX(), C = fx.C, I = LAB.idx, L = LABL;
  const base0 = pool(), v = posView(), vk = valueKey(v);
  // Pool medians for the shrinkage: per position pool within the window and minutes floor.
  Object.keys(MU).forEach(k => delete MU[k]);
  [S.x, S.y, S.color, vk].forEach(k => {
    if (!k || I[k] === undefined || !shrinkable(k)) return;
    MU[k] = {};
    (byPos() ? RCODES : ['G', 'F', 'C']).forEach(pl => { MU[k][pl] = fx.median(base0.filter(r => grpKey(r) === pl).map(r => raw(r, k))); });
    MU[k]._ = fx.median(base0.map(r => raw(r, k)));
    Object.keys(MU[k]).forEach(pl => { if (!fx.isNum(MU[k][pl])) MU[k][pl] = MU[k]._; });
  });
  const rows = base0.filter(r => val(r, S.x) !== null && val(r, S.y) !== null);
  const set = (id, h) => { const e = document.getElementById(id); if (e) e.innerHTML = h; };
  const multi = S.win === 'all' || String(S.win).indexOf('last') === 0;
  set('lab-sub', rows.length + ' player-seasons' + (multi ? ' (' + (S.win === 'all' ? 'every season' : 'last ' + S.win.slice(4) + ' seasons') + ')' : ' in ' + fx.seasonLabel(L, S.win)) + ' with ' + S.min + '+ minutes' + (byPos() ? ' · ' + groupNoun() + (S.qual ? ' · qualified' : '') : (S.pool !== 'all' ? ' · ' + S.pool + ' pool' : '') + (S.qual ? ' · qualified' : '')));
  writeHash();
  if (rows.length < 3) { set('lab-chart', fx.muted('Too few players for this view: lower the minutes floor, widen the window, untick qualified only or pick metrics that exist for these seasons (play-by-play metrics start about 2017).')); set('lab-table', ''); set('lab-sim', ''); return; }
  const xs = rows.map(r => val(r, S.x)), ys = rows.map(r => val(r, S.y));
  const mx = fx.median(xs), my = fx.median(ys), sx = stats(xs), sy = stats(ys);
  const dirx = lower(S.x) ? -1 : 1, diry = lower(S.y) ? -1 : 1;
  const score = r => dirx * (val(r, S.x) - sx.m) / sx.s + diry * (val(r, S.y) - sy.m) / sy.s;
  const ranked = rows.map(r => ({ r: r, z: score(r) })).sort((a, b) => b.z - a.z);
  const q = S.q.trim().toLowerCase();
  const nm = r => raw(r, 'name') || fx.playerName(L, raw(r, 'id'));
  const hits = q ? rows.filter(r => (String(nm(r)) + ' ' + fx.teamName(L, raw(r, 'team')) + ' ' + fx.teamAbbr(L, raw(r, 'team'))).toLowerCase().indexOf(q) >= 0) : [];
  // Labels: the eight furthest into the good corner, the four furthest into the bad one, and the search.
  const labelled = new Set(ranked.slice(0, 8).map(o => o.r).concat(ranked.slice(-4).map(o => o.r)).concat(hits.slice(0, 20)));
  const sortedX = xs.slice().sort((a, b) => a - b), sortedY = ys.slice().sort((a, b) => a - b);
  const sortedV = vk ? rows.map(r => val(r, vk)).filter(fx.isNum).sort((a, b) => a - b) : [], dirv = vk && lower(vk) ? -1 : 1;
  const pOf = (sorted, v, dir) => { const p = pctRank(sorted, v); return dir > 0 ? p : 100 - p; };
  const mins = rows.map(r => raw(r, 'min') || 0), lo = Math.min.apply(null, mins), hi = Math.max.apply(null, mins);
  const size = r => 6 + 14 * (hi > lo ? Math.sqrt(((raw(r, 'min') || 0) - lo) / (hi - lo)) : 0.5);
  const hover = r => '<b>' + fx.esc(nm(r)) + '</b> · ' + fx.esc(fx.teamAbbr(L, raw(r, 'team'))) + ' · ' + fx.esc(fx.seasonLabel(L, raw(r, 'season'))) + ' · ' + (raw(r, 'pool') || '') + ' · ' + fx.num(raw(r, 'min'), 0) + ' min' +
    '<br>' + fx.esc(label(S.x)) + ': ' + fmt(S.x, val(r, S.x)) + ' (pct ' + Math.round(pOf(sortedX, val(r, S.x), dirx)) + ')' +
    '<br>' + fx.esc(label(S.y)) + ': ' + fmt(S.y, val(r, S.y)) + ' (pct ' + Math.round(pOf(sortedY, val(r, S.y), diry)) + ')' +
    (S.shrink && (shrinkable(S.x) || shrinkable(S.y)) ? '<br><span style="opacity:.7">unshrunk: ' + fmt(S.x, raw(r, S.x)) + ' · ' + fmt(S.y, raw(r, S.y)) + '</span>' : '');
  // Groups (one series each, so the legend names them) and the colour of every point.
  const groups = [];
  const POOLN = { G: 'Guards', F: 'Forwards', C: 'Centres' };
  if (S.color === 'team') Array.from(new Set(rows.map(r => raw(r, 'team')))).forEach(t => groups.push({ name: fx.teamAbbr(L, t), colour: fx.teamColour(L, t), pts: rows.filter(r => raw(r, 'team') === t) }));
  else if (S.color === 'pool') {
    ['G', 'F', 'C'].forEach((pl, i) => { const pts = rows.filter(r => raw(r, 'pool') === pl); if (pts.length) groups.push({ name: POOLN[pl], cat: i, pts: pts }); });
    const other = rows.filter(r => ['G', 'F', 'C'].indexOf(raw(r, 'pool')) < 0);
    if (other.length) groups.push({ name: 'Other', ink: true, pts: other });
  } else if (S.color === 'season') Array.from(new Set(rows.map(r => raw(r, 'season')))).sort().forEach((y, i) => groups.push({ name: fx.seasonLabel(L, y), cat: i, pts: rows.filter(r => raw(r, 'season') === y) }));
  else if (S.color) {
    const cv = rows.map(r => val(r, S.color)).filter(fx.isNum).sort((a2, b2) => a2 - b2);
    const dirc = lower(S.color) ? -1 : 1;
    groups.push({ name: label(S.color), byPct: v => pOf(cv, v, dirc), key: S.color, pts: rows });
  } else groups.push({ name: 'Players', model: true, pts: rows });
  const showLegend = S.color === 'pool' || S.color === 'season' || (S.color === 'team' && groups.length <= 32);
  const node = document.getElementById('lab-chart');
  node.style.height = ''; node.style.setProperty('--h', (node.clientWidth < 520 ? 420 : 520) + 'px');
  QKC.mount(node, T => {
    const colOf = (g, r) => (g.byPct ? QK.pctHex(g.byPct(val(r, g.key))) : g.colour ? QK.color.ensure(g.colour, T.s1, 3) : g.ink ? T.ink3 : g.model ? T.model : T.cat[g.cat % 8]);
    const series = groups.map(g => ({
      type: 'scatter', name: g.name, z: 3, itemStyle: { color: g.byPct ? T.model : colOf(g, g.pts[0]) },
      data: g.pts.map(r => ({ value: [val(r, S.x), val(r, S.y)], r: r, symbolSize: size(r), itemStyle: { color: colOf(g, r), opacity: 0.85, borderColor: T.s1, borderWidth: 0.7 },
        label: labelled.has(r) ? { show: true, position: 'top', distance: 4, color: hits.indexOf(r) >= 0 ? T.ink1 : T.ink2, fontSize: 10, fontWeight: hits.indexOf(r) >= 0 ? 700 : 500, fontFamily: T.fontUI,
          formatter: fx.surname(nm(r)) + (multi ? ' ' + String(raw(r, 'season')).slice(2) : '') } : undefined }))
    }));
    if (hits.length) series.push({ type: 'scatter', name: '_search', z: 4, silent: true, symbol: 'circle', data: hits.map(r => ({ value: [val(r, S.x), val(r, S.y)], symbolSize: size(r) + 10 })), itemStyle: { color: 'transparent', borderColor: T.ink1, borderWidth: 2 } });
    series[0].markLine = { silent: true, symbol: 'none', label: { show: false }, lineStyle: { color: T.axis, type: [3, 3], width: 1 }, data: [{ xAxis: mx }, { yAxis: my }] };
    return {
      grid: { left: 10, right: 20, top: 34, bottom: showLegend ? 64 : 34, containLabel: true },
      legend: showLegend ? { bottom: 0, left: 'center', type: 'scroll', icon: 'circle', itemWidth: 9, itemHeight: 9, textStyle: { color: T.ink2, fontSize: 10.5 }, data: groups.map(g => g.name) } : { show: false },
      xAxis: QKC.axis(T, { scale: true, inverse: lower(S.x), name: label(S.x) + (lower(S.x) ? ' (reversed: less is better)' : ''), nameLocation: 'middle', nameGap: 28, fmt: v => fmt(S.x, v) }),
      yAxis: QKC.axis(T, { scale: true, inverse: lower(S.y), name: label(S.y) + (lower(S.y) ? ' (reversed: less is better)' : ''), nameLocation: lower(S.y) ? 'start' : 'end', nameAlign: 'left', fmt: v => fmt(S.y, v) }),
      tooltip: QKC.tooltip(T, { formatter: p => (p.data && p.data.r ? hover(p.data.r) : '') }),
      series: series
    };
  }, { label: label(S.y) + ' against ' + label(S.x), onClick: p => { const r = p.data && p.data.r; if (!r) return; if (EXT && EXT.onPick) EXT.onPick(String(raw(r, 'id')), Number(raw(r, 'season'))); else location.hash = fx.playerHref(L, raw(r, 'id'), Number(raw(r, 'season'))); } });
  set('lab-sim', simStrip(base0, hits, nm, v));
  const mX = LAB.meta[S.x] || {}, mY = LAB.meta[S.y] || {};
  set('lab-note', 'Dotted lines are the medians of the ' + groupNoun() + ' on screen' + (byPos() ? ' (compared within the role group)' : '') + '. ' + (lower(S.x) || lower(S.y) ? 'Axes where less is better are reversed, so better is always up and to the right. ' : 'Better is up and to the right. ') +
    'Labelled: the eight players furthest into that corner and the four furthest from it (sum of standard scores on both axes)' + (hits.length ? ', and your search' : '') + '. Marker size is minutes. Click a dot to open the player in that season.' +
    (S.shrink ? ' Rates marked "shrunk" are pulled towards the median of the player\'s ' + (byPos() ? 'role group' : 'position pool (guards, forwards, centres') + ', on screen) by ' + SHRINK_K + ' minutes of prior, (minutes × rate + ' + SHRINK_K + ' × median) / (minutes + ' + SHRINK_K + '), so a player with 200 minutes is not ranked on 200 minutes alone; hover shows the raw figures. Counts (games, minutes) are never shrunk.' : '') +
    (mX.desc ? '<br><strong>' + fx.esc(mX.label) + '</strong>: ' + fx.esc(mX.desc) : '') + (mY.desc ? '<br><strong>' + fx.esc(mY.label) + '</strong>: ' + fx.esc(mY.desc) : ''));
  set('lab-ours', HW.ours ? HW.ours.explain([S.x, S.y], { label: k => (LAB.meta[k] || {}).label || k }) : '');
  const oth = k => (HW.ours && HW.ours.of(k) ? 'qk-ours-th' : '');
  set('lab-rank-sub', 'The group by the combined standard score on both axes (top ' + (EXT ? '50: the Board has everyone' : '300') + ')' + (vk ? ', with each player’s ' + fx.esc((LAB.meta[vk] || {}).label || vk) + ' and its percentile among the ' + fx.esc(groupNoun()) + ' on screen' : '') + '. Click a row for the player.');
  const host = document.getElementById('lab-table');
  host.innerHTML = HW.tableHTML([
    { label: '#', sortable: false }, { label: 'Player' }, { label: 'Team' }, { label: 'Season', align: 'right' }, { label: 'Pool' }, { label: 'Role', title: 'The spec’s role group: G guard, W wing, B big' }, { label: 'Min', align: 'right' },
    { label: label(S.x), align: 'right', cls: oth(S.x) }, { label: 'Pct', align: 'right' }, { label: label(S.y), align: 'right', cls: oth(S.y) }, { label: 'Pct', align: 'right' }]
    .concat(vk ? [{ label: label(vk), align: 'right', cls: oth(vk), title: 'Overall value: the position view’s value metric' }, { label: 'Pct', align: 'right', title: 'Percentile within the ' + groupNoun() + ' on screen' }] : [])
    .concat([{ label: 'Combined', align: 'right', title: 'Sum of standard scores in the better direction (X and Y)' }
  ]), ranked.slice(0, EXT ? 50 : 300).map((o, i) => {
    const r = o.r, vx = val(r, S.x), vy = val(r, S.y), vv = vk ? val(r, vk) : null, pv = fx.isNum(vv) ? pOf(sortedV, vv, dirv) : null;
    return { _href: fx.playerHref(L, raw(r, 'id'), raw(r, 'season')), cells: [
      { v: i + 1, cls: 'pos-cell' }, { v: nm(r), html: fx.playerLink(L, raw(r, 'id'), nm(r), raw(r, 'team'), raw(r, 'season')) }, { v: fx.teamAbbr(L, raw(r, 'team')), html: fx.esc(fx.teamAbbr(L, raw(r, 'team'))) },
      { v: raw(r, 'season'), html: fx.esc(fx.seasonLabel(L, raw(r, 'season'))) }, raw(r, 'pool') || '', roleOf(r), { v: raw(r, 'min'), html: fx.num(raw(r, 'min'), 0) },
      { v: vx, html: fmt(S.x, vx) }, { v: pOf(sortedX, vx, dirx), html: fx.pill(pOf(sortedX, vx, dirx)) }, { v: vy, html: fmt(S.y, vy) }, { v: pOf(sortedY, vy, diry), html: fx.pill(pOf(sortedY, vy, diry)) }]
      .concat(vk ? [{ v: vv, html: fx.isNum(vv) ? fmt(vk, vv) : '—' }, { v: pv, html: fx.pill(pv) }] : [])
      .concat([{ v: o.z, html: '<strong>' + fx.num(o.z, 2) + '</strong>' }
    ]) };
  }), { sticky: true, compact: true });
  HW.sortable(host);
}

/* "Most like": the five player-seasons nearest the highlighted one within the group on screen (other players only),
   on standard scores of the group's spec headline metrics (QK.within.similar), each a link to Compare. */
function simStrip(rows, hits, nm, v) {
  const fx = FX(), L = LABL;
  if (!hits.length) return '<p class="pg-note">Highlight a player to list the five most like them among the ' + fx.esc(groupNoun()) + ' on this chart.</p>';
  const t = hits[0], tid = String(raw(t, 'id')), head = headOrder();
  // Position mode: the view's metrics (about 4 excellence, 4 scoring and 2 value ids the lab carries); Broad: the headline list
  let keys = v ? [] : Object.keys(head).filter(k => LAB.idx[k] !== undefined).sort((a, b) => head[a] - head[b]);
  if (v) [4, 4, 2].forEach((n, i) => { v.sets[i].ids.filter(k => LAB.idx[k] !== undefined && keys.indexOf(k) < 0).slice(0, n).forEach(k => keys.push(k)); });
  const pool2 = rows.filter(r => r === t || String(raw(r, 'id')) !== tid);
  const seen = {};
  const near = QK.within.similar(pool2, t, keys, (r, k) => { const v = raw(r, k); return fx.isNum(v) ? Number(v) : null; }, 12)
    .filter(o => { const id = String(raw(o.row, 'id')); if (seen[id]) return false; seen[id] = 1; return true; }).slice(0, 5);
  const multi = S.win === 'all' || String(S.win).indexOf('last') === 0;
  return QK.within.simHtml('Most like ' + nm(t) + (multi ? ' ' + fx.seasonLabel(L, raw(t, 'season')) : '') + ' · ' + groupNoun(), near.map(o => ({
    name: nm(o.row) + (multi ? ' ' + String(raw(o.row, 'season')).slice(2) : ''),
    href: '#/' + L + '/compare/players/' + encodeURIComponent(tid) + '/' + encodeURIComponent(String(raw(o.row, 'id'))) + '?s=' + raw(t, 'season'),
    sub: [fx.teamAbbr(L, raw(o.row, 'team')), fx.seasonLabel(L, raw(o.row, 'season')), roleOf(o.row)].filter(Boolean).join(' · ') + ' · compare' })));
}

function markup(room) {
  const hide = room ? ' style="display:none"' : '';
  return '<div class="card"><div class="card-header">' + (room ? 'The chart' : 'Player lab') + ' <span class="card-sub" id="lab-sub">Loading…</span></div>' +
    '<div id="lab-within" class="hw-lab-within-wrap"' + hide + '></div><div class="lab-controls hf-controls">' +
    '<label' + hide + '>Seasons<select id="lab-win"></select></label>' +
    '<label>Preset<select id="lab-preset" class="hf-wide"></select></label>' +
    '<label>X axis<select id="lab-x"></select></label>' +
    '<label>Y axis<select id="lab-y"></select></label>' +
    '<label>&nbsp;<button type="button" id="lab-swap" title="Swap the axes">⇄ swap</button></label>' +
    '<label' + hide + '>Position pool<select id="lab-pool"><option value="all">All</option><option value="G">Guards</option><option value="F">Forwards</option><option value="C">Centres</option></select></label>' +
    '<label>Colour<select id="lab-color"></select></label>' +
    '<label' + hide + '>Min minutes <span id="lab-min-v"></span><input id="lab-min" type="range" min="0" max="2000" step="25"></label>' +
    '<label class="inline"' + hide + '><input id="lab-qual" type="checkbox"> qualified only</label>' +
    '<label class="inline"><input id="lab-shrink" type="checkbox"> shrink small samples</label>' +
    '<label' + hide + '>Highlight<input id="lab-q" class="pg-search" type="search" placeholder="player or team…"></label>' +
    '</div><div id="lab-ours" class="hw-lab-ours"></div><div id="lab-chart" class="hf-lab-chart"></div><div id="lab-sim" class="hw-lab-sim"></div><div class="pg-note" id="lab-note"></div></div>' +
    '<div class="card"><div class="card-header">Ranked <span class="card-sub" id="lab-rank-sub">The group by the combined standard score on both axes (top 300). Click a row for the player.</span></div><div id="lab-table"></div></div>';
}
function renderLab(el, params, state) {
  const fx = FX(), L = fx.L(params, state);
  EXT = null;
  el.innerHTML = markup(false);
  return boot(el, L, params, state, null);
}
/* the Scouting Room's Chart view (ext above) */
function mount(host, L, S0, ext) {
  EXT = ext || {};
  host.innerHTML = markup(true);
  const q = {};
  if (EXT.within === 'pos') { q.within = 'pos'; q.pos = EXT.role; } else q.within = 'broad';
  if (EXT.x) q.x = EXT.x;
  if (EXT.y) q.y = EXT.y;
  q.q = EXT.q || '';
  return boot(host, L, { season: S0, league: L, query: q }, { league: L, season: S0 }, EXT);
}
function boot(el, L, params, state, ext) {
  const fx = FX();
  return fx.ready().then(() => {
    const Sx = fx.S(params, state, L);
    return Promise.all([fx.first([L + '/lab.json', fx.path(L, Sx, 'lab.json')]), HW.ours ? HW.ours.load() : null]).then(both => {
      const rawLab = both[0];
      if (!fx.alive(el)) return;
      if (!rawLab || rawLab.ok === false || !(rawLab.rows || []).length) { document.getElementById('lab-chart').innerHTML = fx.notBuilt('The lab file', rawLab); document.getElementById('lab-sub').textContent = ''; return; }
      if (LABL !== L) { S.win = null; S.x = ''; S.y = ''; S.preset = 0; }
      LAB = prep(rawLab); LABL = L;
      if (S.win === null || (typeof S.win === 'number' && LAB.years.indexOf(S.win) < 0)) S.win = LAB.years.indexOf(Sx) >= 0 ? Sx : LAB.years[0];
      // A season early in its schedule has few minutes: start the floor lower.
      const maxMin = Math.max.apply(null, LAB.rows.filter(inWindow).map(r => raw(r, 'min') || 0).concat([50]));
      if (S.min > maxMin * 0.5) S.min = Math.max(0, Math.round(maxMin * 0.25 / 25) * 25);
      document.getElementById('lab-min').max = String(Math.max(500, Math.ceil(maxMin / 100) * 100));
      const qy = params.query || {};
      if (ext) {
        /* the room: its season, group and floor; Broad is every player (no pool), the floor its qualified players */
        S.win = LAB.years.indexOf(Sx) >= 0 ? Sx : LAB.years[0]; S.pool = 'all'; S.x = ''; S.y = ''; S.preset = 0;
        S.qual = !fx.isNum(ext.min); S.min = fx.isNum(ext.min) ? ext.min : 0; S.color = 'team';
      }
      const wq = QK.within.read(qy, RCODES);
      if (wq.within === 'pos') { if (S.within !== 'pos') S.qual = true; S.within = 'pos'; S.role = wq.pos; }
      else if (qy.within !== undefined || qy.pool !== undefined) { S.within = 'broad'; S.qual = false; }
      if (/^(G|F|C|all)$/.test(qy.pool || '')) S.pool = qy.pool;
      if (qy.q !== undefined) S.q = String(qy.q);
      if (ext && wq.within !== 'pos') S.within = 'broad';
      if (qy.x && LAB.idx[qy.x] !== undefined) { S.x = qy.x; S.preset = -1; }
      if (qy.y && LAB.idx[qy.y] !== undefined) { S.y = qy.y; S.preset = -1; }
      if (!S.x || LAB.idx[S.x] === undefined || !S.y || LAB.idx[S.y] === undefined) { if (S.preset < 0) S.preset = 0; applyPreset(); }
      if (!S.x || !S.y) { const ms = LAB.metrics; S.x = (ms[0] || {}).key || 'min'; S.y = (ms[1] || {}).key || 'gp'; S.preset = -1; }
      // ?within=pos&pos=.. without axes opens on the role's view; explicit x / y in the address still win
      const qx = qy.x && LAB.idx[qy.x] !== undefined, qyy = qy.y && LAB.idx[qy.y] !== undefined;
      if (wq.within === 'pos' && (!qx || !qyy)) {
        applyView();
        if (qx) { S.x = qy.x; S.preset = -1; }
        if (qyy) { S.y = qy.y; S.preset = -1; }
      }
      if (ext && ext.color && (ext.color === 'team' || ext.color === 'pool' || ext.color === 'season' || LAB.idx[ext.color] !== undefined)) S.color = ext.color;
      sync();
      const $ = id => document.getElementById(id);
      $('lab-win').onchange = e => { const v = e.target.value; S.win = /^\d+$/.test(v) ? parseInt(v, 10) : v; if (S.win === 'all' && S.color === 'team') S.color = 'season'; sync(); draw(); };
      $('lab-preset').onchange = e => { S.preset = parseInt(e.target.value, 10); applyPreset(); sync(); draw(); };
      $('lab-x').onchange = e => { S.x = e.target.value; S.preset = -1; sync(); draw(); };
      $('lab-y').onchange = e => { S.y = e.target.value; S.preset = -1; sync(); draw(); };
      $('lab-swap').onclick = () => { const t = S.x; S.x = S.y; S.y = t; S.preset = -1; sync(); draw(); };
      $('lab-pool').onchange = e => { S.pool = e.target.value; draw(); };
      $('lab-color').onchange = e => { S.color = e.target.value; draw(); };
      $('lab-min').oninput = e => { S.min = parseInt(e.target.value, 10); $('lab-min-v').textContent = S.min; };
      $('lab-min').onchange = () => draw();
      $('lab-shrink').onchange = e => { S.shrink = e.target.checked; draw(); };
      $('lab-qual').onchange = e => { S.qual = e.target.checked; draw(); };
      let timer = null;
      $('lab-q').oninput = e => { S.q = e.target.value; clearTimeout(timer); timer = setTimeout(draw, 250); };
      draw();
    });
  });
}

HW.route('lab', renderLab);
HW.lab = { mount: mount, render: renderLab };
})(window.HW);
