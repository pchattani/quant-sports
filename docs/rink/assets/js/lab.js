/* The Quant Rink — the lab (#/lab): any two metrics for skaters, goalies or teams.
 *
 * Scatter any two catalogue metrics, with presets for the questions the models were built to answer
 * (individual xG/60 against goals/60, RAPM offence against defence, EDGE top speed against xGF%, GSAx
 * against workload ...), colour by team, position or any metric, medians as quadrants, the corners
 * labelled, a search highlight and the pool ranked below. Rates can be shrunk towards the median by each
 * metric's stabilisation point: shrunk = (n·x + k·median)/(n + k), with k = 3/7 of the sample at which
 * split-half reliability reaches 0.7 (r(n) = n/(n + k), so n₀.₇ = 7k/3).
 *
 * Address: #/lab?kind=S|G|T&pos=F|D&x=<key>&y=<key> (&s=<season>), or #/lab?within=pos&pos=F|D|G&x=&y=.
 * "Compare within" (QK.within): Broad (the default) is today's split, skaters (all, forwards or defence: the old
 * `pos=F|D` filter) or goalies; Position is the metrics spec's peer groups (hockey.json forwards, defence, goalies,
 * on the row's position group) at the spec's floor (the payload's `qualified`: 250 5v5 minutes prorated, goalies a
 * quarter of the team's minutes), and the scatter, ranks, percentiles, medians, metric order and the "Most like"
 * strip follow the group. In the address `pos` is the old skater filter under Broad and the group under Position, so
 * old links keep working. The lab writes its state back with history.replaceState (no re-render).
 * Data: data/<S>/lab.json (column-oriented per kind: {"skaters": {cols, rows}, "goalies": {cols, rows},
 * "teams"?: {cols, rows}, "metrics": {skaters: [METRIC], goalies: [...], teams: [...]} | [METRIC]}), falling
 * back to skaters.json, goalies.json and teams.json. Uses RK.fk. */
(function (RK) {
'use strict';

const K = () => RK.fk;
const PRESETS = [
  ['S', ['rapm_off', /rapm.*(off|xgf)/], ['rapm_def', /rapm.*(def|xga)/], 'Our RAPM at both ends: isolated offence against defence (5v5 xG)'],
  ['S', ['gar_ev_off', /gar_ev_off/], ['gar_ev_def', /gar_ev_def/], 'Our value model at both ends: even-strength offence against defence (GAR)'],
  ['S', ['toi_gp', /toi.*(gp|pg)/], ['gar', 'value', /^(rink_)?value|gar|war/], 'Ice time per game against Rink value (GAR)'],
  ['S', ['ixg60', 'ixg_60', /^i?xg_?(per_?)?60/], ['g60_5v5', 'g60', 'goals60', /^g(oals)?_?(per_?)?60/], 'Individual xG/60 against goals/60 (5v5): finishing above or below the chances'],
  ['S', ['edge_max_speed', 'max_speed', /max_?speed|top_?speed/], ['xgf_pct', /xgf_?pct/], 'Tracked top skating speed against on-ice xGF%: does speed drive play?'],
  ['S', ['edge_shot_speed', 'max_shot_speed', /shot_?speed/], ['sh_pct', /sh(ooting)?_?pct/], 'Tracked hardest shot against shooting %'],
  ['S', ['xgf_pct', /xgf_?pct/], ['gf_pct', /gf_?pct/], 'On-ice xGF% against GF%: process against results'],
  ['S', ['ozs_pct', 'oz_start_pct', /oz.*start|ozs/], ['xgf_pct', /xgf_?pct/], 'Offensive-zone starts against xGF%: deployment or talent?'],
  ['S', ['qoc_toi', /qoc/], ['xgf_pct_rel', /xgf.*rel/], 'Quality of competition against relative xGF%'],
  ['S', ['p60', 'pts60', /^p(ts|oints)_?(per_?)?60/], ['rapm_off', /rapm.*(off|xgf)/], 'Points/60 against RAPM offence'],
  ['G', ['sa', 'shots_faced', /shots?_?faced|^sa$/], ['gsax', /^gsax$/], 'GSAx against workload (shots faced)'],
  ['G', ['xga60', /xga_?(per_?)?60/], ['gsax60', /gsax.*60/], 'Expected goals faced per 60 against GSAx per 60: busy nights and quality'],
  ['G', ['hd_share', /high.*share|hd_share/], ['gsax_high', /gsax.*(high|hd)|(high|hd).*gsax/], 'High-danger share against high-danger GSAx'],
  ['G', ['sv_pct', /^sv_?pct$/], ['gsax60', /gsax.*60/], 'Save % against GSAx/60: what the shots were worth'],
  ['T', ['off5'], ['def5'], 'Team 5v5 offence against defence (xGF/60 and xGA/60; defence axis reversed)'],
  ['T', ['xgf_pct5', /xgf_?pct/], ['rating'], 'Team 5v5 xGF% against the rating'],
  ['T', ['pp'], ['pk'], 'Power play against penalty kill'],
  ['T', ['xgf_g'], ['gf_g'], 'Expected goals against goals per game: finishing'],
  ['T', ['xga_g'], ['ga_g'], 'Expected goals against goals allowed per game: goaltending and luck']
];
const NO_SHRINK = /^(gp|gs|games|age|season|toi|toi\d*_gp|toi5|value|gar|war|gar_.*|rapm_.*|.*_se|g|a|a1|a2|p|pts|sog|iff|icf|shots|ixg|gax|xgf|xga|gsax|gsax_.*|shots_faced|sa|ga|w|l|otl|so|edge_.*|.*speed.*|bursts.*|ozs_pct|dzs_share|oz_start_pct|dz_start_pct|qo[ct]_.*|proj_.*|pts_pace|hits|blocks|pim|pp_p|sh_p|fo_taken|fo_net|pen_net)$/;
let LAB = null, LABK = '', LAB_RESET = null, LAB_REDRAW = null;
const S0 = { kind: 'S', pos: 'A', min: null, shrink: true, preset: 0, x: '', y: '', color: 'team', q: '', qual: true, within: 'broad', grp: 'F' };
/* "Compare within: Position": [address code, spec group id, fallback display] */
const PGROUPS = [['F', 'forwards', 'Forwards'], ['D', 'defence', 'Defence'], ['G', 'goalies', 'Goaltenders']];
const PCODES = PGROUPS.map(g => g[0]);
const byPos = () => S0.within === 'pos' && S0.kind !== 'T';
const specCat = () => (RK.ours && RK.ours.cat ? RK.ours.cat() : null);
function pgroup(code) {
  const g = PGROUPS.find(x => x[0] === code) || PGROUPS[0];
  const sg = specCat() && specCat().group ? specCat().group(g[1]) : null;
  return { code: g[0], id: g[1], name: (sg && sg.display) || g[2], min: sg && sg.min ? sg.min : null };
}
/* the spec group(s) whose headline metrics lead the pickers and drive "Most like" */
function groupIds() {
  if (S0.kind === 'T') return [];
  if (byPos()) return [pgroup(S0.grp).id];
  if (S0.kind === 'G') return ['goalies'];
  return S0.pos === 'F' ? ['forwards'] : S0.pos === 'D' ? ['defence'] : ['forwards', 'defence'];
}
function headOrder() {
  const out = {}, c = specCat();
  let n = 1;
  groupIds().forEach(id => { (c ? c.headline(id) : []).forEach(k => { if (out[k] === undefined) out[k] = n++; }); });
  return out;
}
/* the address: kind, the within choice (or the old skater filter under Broad), the axes; other keys kept */
function writeHash() {
  try {
    const h = String(location.hash || '#/lab'), qi = h.indexOf('?');
    const path = qi >= 0 ? h.slice(0, qi) : h, keep = [];
    (qi >= 0 ? h.slice(qi + 1).split('&') : []).forEach(kv => { const k = kv.split('=')[0]; if (kv && ['kind', 'g', 'pos', 'within', 'x', 'y', 'q'].indexOf(k) < 0) keep.push(kv); });
    const wq = QK.within.query({ within: byPos() ? 'pos' : 'broad', pos: S0.grp });
    const add = { kind: S0.kind !== 'S' && !byPos() ? S0.kind : null, within: wq.within, pos: wq.pos || (!byPos() && S0.kind === 'S' && S0.pos !== 'A' ? S0.pos : null), x: S0.x || null, y: S0.y || null, q: S0.q.trim() || null };
    Object.keys(add).forEach(k => { if (add[k]) keep.push(k + '=' + encodeURIComponent(add[k])); });
    const nh = path + (keep.length ? '?' + keep.join('&') : '');
    if (nh !== h && window.history && history.replaceState) history.replaceState(null, '', nh);
  } catch (e) { /* the address is a convenience */ }
}
const MU = {};
const KINDS = [['S', 'Skaters'], ['G', 'Goalies'], ['T', 'Teams']];

/* -> {S: {idx, meta, metrics, rows, nKey, nLabel}, G: ..., T: ...} */
function prep(raw, sk, gk, tms) {
  const k = K();
  const kinds = {};
  const metaFor = (kind, list) => {
    if (!raw || raw.ok === false) return list || [];
    const M = raw.metrics;
    const pick = M && !Array.isArray(M) ? (M[{ S: 'skaters', G: 'goalies', T: 'teams' }[kind]] || M[kind] || []) : (M || []);
    const extra = raw[{ S: 'skater_metrics', G: 'goalie_metrics', T: 'team_metrics' }[kind]] || [];
    return k.cleanMetrics(pick.concat(extra).concat(list || []));
  };
  const mkKind = (g, cols, rows, metrics) => {
    const idx = {};
    cols.forEach((c, i) => { idx[c] = i; });
    if (idx.pid === undefined && idx.id !== undefined) idx.pid = idx.id;
    const seen = {};
    const ms0 = metrics.filter(m => { if (!m || seen[m.key]) return false; seen[m.key] = 1; return true; });
    const meta = k.metaOf(ms0);
    // columns that carry numbers but no METRIC still become axes
    cols.forEach(c => { if (!meta[c] && !/^(pid|id|name|team|pos|qualified|colour|age)$/.test(c) && rows.some(r => k.isNum(r[idx[c]]))) { const m = { key: c, label: (RK.fk.playerLabel ? RK.fk.playerLabel(c) : c), group: 'Other', fmt: '' }; ms0.push(m); meta[c] = m; } });
    if (RK.ours && RK.ours.cat()) ms0.forEach((m, i) => { const r = RK.ours.row(m.key, g === 'T' ? 'team' : 'player'); if (r) { ms0[i] = meta[m.key] = Object.assign({}, m, { label: r[0], desc: r[6] || m.desc }); } });
    const ms = ms0.filter(m => idx[m.key] !== undefined && rows.some(r => k.isNum(r[idx[m.key]])));
    const nKey = g === 'T' ? (idx.gp !== undefined ? 'gp' : null) : (g === 'G' ? ['shots_faced', 'sa', 'toi'].find(c => idx[c] !== undefined) : (idx.toi !== undefined ? 'toi' : (idx.gp !== undefined ? 'gp' : null)));
    kinds[g] = { idx: idx, meta: meta, metrics: ms, rows: rows, nKey: nKey, nLabel: nKey === 'toi' ? 'TOI (min)' : nKey === 'gp' ? 'Games' : 'Shots faced' };
  };
  const fromCat = (g, cat, metrics) => {
    const P = cat.players, keys = metrics.map(m => m.key);
    const scale = k.toiScale(P);
    const cols = ['pid', 'name', 'team', 'pos', 'age', 'gp', 'toi', 'qualified'].concat(keys.filter(x => ['gp', 'toi', 'age'].indexOf(x) < 0));
    mkKind(g, cols, Object.keys(P).filter(id => g === 'G' || k.groupOf(P[id].pos) !== 'G').map(id => { const p = P[id]; return [id, p.name, p.team, p.pos, p.age, k.gpOf(p), k.toiOf(p, scale), p.qualified].concat(cols.slice(8).map(x => (p.values || {})[x])); }), metrics);
  };
  if (!kinds.S && sk) fromCat('S', sk, k.allMetrics(sk));
  if (!kinds.G && gk) fromCat('G', gk, k.allMetrics(gk));
  const TEAM_LABEL = { rating: ['Rating', 'signed', false, 'Units'], off5: ['5v5 offence (xGF/60)', '2', false, 'Units'], def5: ['5v5 defence (xGA/60)', '2', true, 'Units'], pp: ['Power play (xGF/60)', '2', false, 'Units'], pk: ['Penalty kill (xGA/60)', '2', true, 'Units'],
    goalie: ['Goaltending (GSAx/60)', '3', false, 'Units'], xgf_pct5: ['5v5 xGF%', 'pct', false, 'Shares'], cf_pct5: ['5v5 CF%', 'pct', false, 'Shares'], gf_g: ['Goals for / game', '2', false, 'Results'], ga_g: ['Goals against / game', '2', true, 'Results'],
    xgf_g: ['xGF / game', '2', false, 'Expected'], xga_g: ['xGA / game', '2', true, 'Expected'], gsax: ['Goalie GSAx', '1', false, 'Units'], pp_gf: ['PP goals', 'int', false, 'Special teams'], pk_ga: ['PK goals against', 'int', true, 'Special teams'],
    pp_toi_g: ['PP minutes / game', '1', false, 'Special teams'], pk_toi_g: ['PK minutes / game', '1', true, 'Special teams'], gp: ['Games', 'int', false, 'Results'], se: ['Rating SE', '3', false, 'Units'] };
  const fromCols = (g, X, extraMeta) => {
    if (!X || !Array.isArray(X.ids) || !X.data) return;
    const keys = (X.cols || Object.keys(X.data)).filter(c => Array.isArray(X.data[c]));
    const lab = X.labels || {};
    const metrics = keys.map(c => { const L = lab[c] || extraMeta[c] || null; return { key: c, label: L ? L[0] : c, fmt: L ? L[1] : '', lower: L ? !!L[2] : false, group: L ? (L[3] || 'Other') : 'Other' }; });
    const head = g === 'T' ? ['team'] : ['pid', 'name', 'team', 'pos', 'qualified', 'age'];
    const cols = head.concat(keys.filter(c => head.indexOf(c) < 0));
    const rows = X.ids.map((id, i) => cols.map(c => (c === 'pid' || c === 'team' && g === 'T' ? String(id) : (head.indexOf(c) >= 0 ? (X[c] || [])[i] : X.data[c][i]))));
    mkKind(g, cols, rows, metrics);
  };
  if (raw && raw.ok !== false) {
    if (!kinds.S) fromCols('S', raw.skaters, {});
    if (!kinds.G) fromCols('G', raw.goalies, {});
    if (!kinds.T) fromCols('T', raw.teams, TEAM_LABEL);
  }
  if (!kinds.T && tms && tms.teams) {
    const ms = tms.metrics || [], keys = ms.map(m => m.key);
    const T = tms.teams;
    mkKind('T', ['team', 'name', 'gp'].concat(keys), Object.keys(T).map(t => [t, T[t].name, ((T[t].record || {}).gp || (T[t].values || {}).gp || null)].concat(keys.map(x => (T[t].values || {})[x]))), ms);
  }
  return kinds;
}
function G() { return LAB[S0.kind] || LAB[Object.keys(LAB)[0]]; }
function raw(r, key) { const g = G(), i = g.idx[key]; if (i === undefined) return null; const v = r[i]; return v === null || v === undefined || (typeof v === 'number' && !isFinite(v)) ? null : v; }
function idOf(r) { return String(S0.kind === 'T' ? raw(r, 'team') : (raw(r, 'pid') || raw(r, 'id'))); }
function nOf(r) { const g = G(); if (!g.nKey) return 0; const v = raw(r, g.nKey); return K().isNum(v) ? Number(v) : 0; }
function meta(key) { return G().meta[key] || { key: key, label: key === G().nKey ? G().nLabel : key }; }
function shrinkable(key) { const m = meta(key); return S0.kind !== 'T' && !NO_SHRINK.test(key) && K().isNum(m.stabilises_at) && ['int', '0'].indexOf(m.fmt) < 0; }
function kOf(key) { const m = meta(key); return K().isNum(m.stabilises_at) ? m.stabilises_at * 3 / 7 : 200; }
function lower(key) { return !!meta(key).lower; }
function label(key) { return (meta(key).label || key) + (S0.shrink && shrinkable(key) ? ' (shrunk)' : ''); }
function fmt(key, v) { return K().fmtV(v, meta(key).fmt); }
/* The sample a metric is measured on: the metric's "unit" column when the row carries it, else the pool's sample. */
const UNIT_COL = { 'minutes': 'toi', '5v5 minutes': 'toi5', 'shots': 'sog', 'unblocked attempts': 'iff', 'faceoffs': 'fo_taken', 'games': 'gp', 'shots faced': 'sa', 'unblocked shots faced': 'sa' };
function nFor(r, key) { const u = meta(key).unit; const c = u ? (UNIT_COL[u] || u) : null; const v = c ? raw(r, c) : null; return K().isNum(v) ? Number(v) : nOf(r); }
function val(r, key) {
  const v = raw(r, key);
  if (v === null || !S0.shrink || !shrinkable(key)) return v;
  const mu = MU[key];
  if (!K().isNum(mu)) return v;
  const n = nFor(r, key), kk = kOf(key);
  return (n * v + kk * mu) / (n + kk);
}
function posOk(r) {
  if (byPos()) return S0.grp === 'G' ? true : K().groupOf(raw(r, 'pos')) === S0.grp;
  if (S0.kind !== 'S' || S0.pos === 'A') return true;
  return K().groupOf(raw(r, 'pos')) === S0.pos;
}
function presetList() {
  const k = K(), out = [], seen = {};
  const keys = Object.keys(G().idx);
  PRESETS.filter(p => p[0] === S0.kind).forEach(p => {
    const x = k.pick(keys, p[1]), y = k.pick(keys, p[2]);
    if (x && y && x !== y && !seen[x + '|' + y] && G().metrics.some(m => m.key === x) && G().metrics.some(m => m.key === y)) { seen[x + '|' + y] = 1; out.push({ x: x, y: y, title: p[3] }); }
  });
  return out;
}
function zs(a) { const n = a.length; if (!n) return { m: 0, s: 1 }; const m = a.reduce((x, y) => x + y, 0) / n; const v = a.reduce((x, y) => x + (y - m) * (y - m), 0) / n; return { m: m, s: Math.sqrt(v) || 1 }; }
function pctRank(sorted, v) { let lo = 0, hi = sorted.length; while (lo < hi) { const mid = (lo + hi) >> 1; if (sorted[mid] < v) lo = mid + 1; else hi = mid; } let up = lo; while (up < sorted.length && sorted[up] === v) up++; return sorted.length ? 100 * ((lo + up) / 2) / sorted.length : null; }

/* The pickers: "Our models", then the peer group's spec headline metrics ("Key numbers · <group>", in the spec's order),
   then the payload's groups. Teams keep the generic order. */
function pickerGroups(ms) {
  if (S0.kind === 'T') return RK.ours.groups(ms, { entity: 'team' });
  const head = headOrder(), ours = [], key = [], rest = [];
  ms.forEach((m, i) => { const h = head[m.key] || 0, x = { m: m, h: h, i: i }; if (RK.ours.of(m.key)) ours.push(x); else if (h) key.push(x); else rest.push(x); });
  const cmp = (a, b) => ((a.h || 1e3) - (b.h || 1e3)) || (a.i - b.i);
  const out = [];
  if (ours.length) out.push({ name: 'Our models', items: ours.sort(cmp).map(x => x.m) });
  if (key.length) out.push({ name: 'Key numbers · ' + groupNoun(), items: key.sort(cmp).map(x => x.m) });
  rest.forEach(x => { const g = 'Box score · ' + (x.m.group || 'Other'); let b = out.find(y => y.name === g); if (!b) { b = { name: g, items: [] }; out.push(b); } b.items.push(x.m); });
  return out;
}
function groupNoun() {
  if (S0.kind === 'T') return 'teams';
  if (byPos()) return pgroup(S0.grp).name.toLowerCase();
  return S0.kind === 'G' ? 'goalies' : ({ F: 'forwards', D: 'defencemen', A: 'skaters' })[S0.pos];
}
function metricOptions(sel, scope) {
  const k = K();
  let h = scope === 'color' ? '<option value="team">Team</option>' + (S0.kind === 'S' ? '<option value="pos">Position</option>' : (S0.kind === 'T' ? '<option value="conf">Conference</option>' : '')) + '<option value="">One colour</option>' : '';
  (RK.ours ? pickerGroups(G().metrics) : k.groups(G().metrics)).forEach(g => { h += '<optgroup label="' + k.esc(g.name) + '">' + g.items.map(m => '<option value="' + k.esc(m.key) + '"' + (m.key === sel ? ' selected' : '') + '>' + k.esc(m.label) + (m.lower ? ' ↓' : '') + '</option>').join('') + '</optgroup>'; });
  return h;
}
function sync() {
  const k = K(), $ = k.$, P = presetList();
  $('lab-kind').querySelectorAll('button').forEach(b => { b.classList.toggle('on', b.dataset.v === S0.kind); b.disabled = !LAB[b.dataset.v]; });
  $('lab-pos').value = S0.pos; $('lab-pos').parentNode.style.display = S0.kind === 'S' && !byPos() ? '' : 'none';
  const pg = byPos() ? pgroup(S0.grp) : null;
  $('lab-within').innerHTML = S0.kind === 'T' ? '' : QK.within.html({ within: byPos() ? 'pos' : 'broad', pos: S0.grp }, { id: 'lab-wn', cls: 'rk-lab-within',
    groups: PGROUPS.map(g => [g[0], pgroup(g[0]).name]),
    note: pg ? 'Minimum: the spec’s floor (' + (pg.code === 'G' ? 'a quarter of the team’s minutes in net' : '250 5v5 minutes, prorated to games played') + '), the qualified flag' : 'Skaters or goalies' });
  if (S0.kind !== 'T') QK.within.wire($('lab-within'), { within: byPos() ? 'pos' : 'broad', pos: S0.grp }, w => {
    if (w.within === 'pos' && S0.within !== 'pos') w.pos = S0.kind === 'G' ? 'G' : (S0.pos === 'D' ? 'D' : 'F');
    const was = S0.kind;
    S0.within = w.within; S0.grp = w.pos;
    if (S0.within === 'pos') { S0.kind = S0.grp === 'G' ? 'G' : 'S'; S0.qual = true; }
    else if (S0.kind === 'S') S0.pos = S0.grp === 'D' ? 'D' : S0.grp === 'F' ? 'F' : 'A';
    if (S0.kind !== was) { S0.x = ''; S0.y = ''; S0.preset = 0; S0.min = null; }
    if (LAB_RESET) LAB_RESET();
    sync(); if (LAB_REDRAW) LAB_REDRAW();
  }, { id: 'lab-wn' });
  $('lab-preset').innerHTML = P.map((p, i) => '<option value="' + i + '"' + (i === S0.preset ? ' selected' : '') + '>' + k.esc(p.title) + '</option>').join('') + '<option value="-1"' + (S0.preset < 0 || !P.length ? ' selected' : '') + '>Custom axes</option>';
  $('lab-x').innerHTML = metricOptions(S0.x); $('lab-y').innerHTML = metricOptions(S0.y);
  $('lab-x').value = S0.x; $('lab-y').value = S0.y;
  $('lab-color').innerHTML = metricOptions(S0.color, 'color'); $('lab-color').value = S0.color;
  $('lab-min').value = S0.min; $('lab-min-v').textContent = k.int(S0.min); $('lab-min-u').textContent = G().nLabel.toLowerCase();
  $('lab-min').parentNode.style.display = S0.kind === 'T' || !G().nKey ? 'none' : '';
  $('lab-qual').parentNode.style.display = S0.kind === 'T' || G().idx.qualified === undefined ? 'none' : '';
  $('lab-shrink').parentNode.style.display = S0.kind === 'T' ? 'none' : '';
  $('lab-shrink').checked = S0.shrink; $('lab-q').value = S0.q; $('lab-qual').checked = S0.qual;
}
function applyPreset() { const P = presetList(); if (S0.preset < 0 || !P.length) return; const p = P[S0.preset] || P[0]; S0.x = p.x; S0.y = p.y; }

function draw(S) {
  const k = K(), C = k.C;
  const team = S0.kind === 'T';
  const base0 = G().rows.filter(r => team || ((nOf(r) >= S0.min) && posOk(r) && (!S0.qual || G().idx.qualified === undefined || raw(r, 'qualified') !== false)));
  Object.keys(MU).forEach(key => delete MU[key]);
  [S0.x, S0.y, S0.color].forEach(key => { if (key && G().idx[key] !== undefined && shrinkable(key)) MU[key] = k.median(base0.map(r => raw(r, key))); });
  const rows = base0.filter(r => val(r, S0.x) !== null && val(r, S0.y) !== null);
  const noun = groupNoun();
  writeHash();
  k.set('lab-sub', rows.length + ' ' + noun + ' · ' + k.sLabel(S) + (team || !G().nKey ? '' : ' · ' + k.int(S0.min) + '+ ' + G().nLabel.toLowerCase() + (S0.qual ? ' · qualified' : '')));
  if (rows.length < 3) { k.set('lab-chart', k.muted('Too few for this view: lower the floor, untick qualified only, or pick metrics these players have (puck and player tracking starts in 2021–22, shift-based metrics in 2010–11).')); k.set('lab-table', ''); k.set('lab-note', ''); k.set('lab-sim', ''); return; }
  const xs = rows.map(r => val(r, S0.x)), ys = rows.map(r => val(r, S0.y));
  const mx = k.median(xs), my = k.median(ys), sx = zs(xs), sy = zs(ys);
  const dirx = lower(S0.x) ? -1 : 1, diry = lower(S0.y) ? -1 : 1;
  const score = r => dirx * (val(r, S0.x) - sx.m) / sx.s + diry * (val(r, S0.y) - sy.m) / sy.s;
  const ranked = rows.map(r => ({ r: r, z: score(r) })).sort((a, b) => b.z - a.z);
  const nm = r => (team ? k.teamName(raw(r, 'team')) : (raw(r, 'name') || k.name(idOf(r))));
  const short = r => (team ? raw(r, 'team') : k.surname(nm(r)));
  const tm = r => raw(r, 'team');
  const q = k.fold(S0.q.trim());
  const hits = q ? rows.filter(r => k.fold(nm(r) + ' ' + (tm(r) || '')).indexOf(q) >= 0) : [];
  const labelled = new Set(team ? rows : ranked.slice(0, 8).map(o => o.r).concat(ranked.slice(-4).map(o => o.r)).concat(hits.slice(0, 20)));
  const sortedX = xs.slice().sort((a, b) => a - b), sortedY = ys.slice().sort((a, b) => a - b);
  const pOf = (sorted, v, dir) => { const p = pctRank(sorted, v); return dir > 0 ? p : 100 - p; };
  const ns = rows.map(nOf), lo = Math.min.apply(null, ns), hi = Math.max.apply(null, ns);
  const size = r => (team ? 13 : 6 + 13 * (hi > lo ? Math.sqrt((nOf(r) - lo) / (hi - lo)) : 0.5));
  const href = r => (team ? k.teamHref(idOf(r), S) : k.playerHref(idOf(r), S));
  const hover = r => '<b>' + k.esc(nm(r)) + '</b>' + (team ? '' : ' · ' + k.esc(tm(r) || '') + (G().nKey ? ' · ' + k.int(nOf(r)) + ' ' + k.esc(G().nLabel.toLowerCase()) : '')) +
    '<br>' + k.esc(label(S0.x)) + ': ' + fmt(S0.x, val(r, S0.x)) + ' (pct ' + Math.round(pOf(sortedX, val(r, S0.x), dirx)) + ')' +
    '<br>' + k.esc(label(S0.y)) + ': ' + fmt(S0.y, val(r, S0.y)) + ' (pct ' + Math.round(pOf(sortedY, val(r, S0.y), diry)) + ')' +
    (S0.shrink && (shrinkable(S0.x) || shrinkable(S0.y)) ? '<br><span style="color:#8b949e">unshrunk: ' + fmt(S0.x, raw(r, S0.x)) + ' · ' + fmt(S0.y, raw(r, S0.y)) + '</span>' : '');
  const trace = (pts, name, color, extra) => Object.assign({
    type: 'scatter', mode: 'markers', name: name, x: pts.map(r => val(r, S0.x)), y: pts.map(r => val(r, S0.y)),
    text: pts.map(hover), hovertemplate: '%{text}<extra></extra>', customdata: pts.map(href),
    marker: { size: pts.map(size), color: color, opacity: 0.85, line: { color: '#0d1117', width: 0.7 } }
  }, extra || {});
  const traces = [];
  if (S0.color === 'team' || S0.color === 'pos' || S0.color === 'conf') {
    const key = S0.color === 'team' ? r => String(tm(r) || '—') : S0.color === 'conf' ? r => String(k.team(raw(r, 'team')).conference || '—') : r => String(k.posLabel(raw(r, 'pos')) || '—');
    const cnt = {};
    rows.forEach(r => { cnt[key(r)] = (cnt[key(r)] || 0) + 1; });
    Object.keys(cnt).sort((a, b) => cnt[b] - cnt[a]).slice(0, 34).forEach((c, i) => {
      const pts = rows.filter(r => key(r) === c);
      const col = S0.color === 'team' && pts[0] ? k.teamColour(tm(pts[0])) : (/^East/.test(c) ? '#e8504f' : /^West/.test(c) ? '#58a6ff' : k.PALETTE[i % k.PALETTE.length]);
      traces.push(trace(pts, c + ' (' + cnt[c] + ')', col));
    });
  } else if (S0.color) {
    const cv = rows.map(r => val(r, S0.color));
    traces.push(trace(rows, label(S0.color), cv, { marker: { size: rows.map(size), color: cv, colorscale: 'RdBu', reversescale: !lower(S0.color), opacity: 0.85,
      colorbar: { title: { text: label(S0.color), side: 'right' }, thickness: 10, tickfont: { color: C.text2 } }, line: { color: '#0d1117', width: 0.7 } } }));
  } else traces.push(trace(rows, 'All', '#58a6ff'));
  if (hits.length) traces.push(Object.assign(trace(hits, 'Search', '#ffffff'), { marker: { size: 20, color: 'rgba(0,0,0,0)', symbol: 'star-open', line: { color: '#ffffff', width: 2 } }, showlegend: false }));
  const ann = Array.from(labelled).map(r => ({ x: val(r, S0.x), y: val(r, S0.y), text: k.esc(short(r)), showarrow: false, yshift: 11, font: { size: 10, color: hits.indexOf(r) >= 0 ? '#ffffff' : '#c9d1d9' } }));
  const rr = k.corr(xs, ys);
  const node = k.$('lab-chart');
  const narrow = k.narrow(node);
  const pctAxis = m => (m.fmt === 'pct' ? '.0%' : '');
  k.plot(node, traces, k.layout({
    showlegend: !narrow && (S0.color === 'team' || S0.color === 'pos' || S0.color === 'conf') && traces.length <= 14, legend: { orientation: 'h', y: -0.18, font: { color: C.text2, size: 9 } }, margin: { l: 66, r: 16, t: 20, b: narrow ? 50 : 90 }, annotations: ann, hovermode: 'closest',
    xaxis: { title: label(S0.x), zeroline: false, autorange: lower(S0.x) ? 'reversed' : true, tickformat: pctAxis(meta(S0.x)) },
    yaxis: { title: label(S0.y), zeroline: false, autorange: lower(S0.y) ? 'reversed' : true, tickformat: pctAxis(meta(S0.y)) },
    shapes: [{ type: 'line', x0: mx, x1: mx, yref: 'paper', y0: 0, y1: 1, line: { color: '#3d444d', dash: 'dot', width: 1 } }, { type: 'line', y0: my, y1: my, xref: 'paper', x0: 0, x1: 1, line: { color: '#3d444d', dash: 'dot', width: 1 } }]
  }));
  k.clickThrough(node);
  k.set('lab-sim', team ? '' : simStrip(base0, hits, nm, S));
  const mX = meta(S0.x), mY = meta(S0.y);
  const unit = m => k.esc(m.unit || (S0.kind === 'G' ? 'shots' : 'minutes'));
  k.set('lab-note', 'Correlation on screen r = ' + k.num(rr, 2) + ' (' + rows.length + ' ' + noun + '). Dotted lines are the medians of the ' + noun + ' on screen' + (byPos() ? ' (compared within the position group)' : '') + '. ' + (lower(S0.x) || lower(S0.y) ? 'Axes where less is better are reversed, so better is always up and to the right. ' : 'Better is up and to the right. ') +
    (team ? '' : 'Labelled: the eight furthest into the good corner, the four furthest from it' + (hits.length ? ', and your search' : '') + '. Marker size is the sample. ') + 'Click a dot to open the page.' +
    (S0.shrink && !team ? ' Rates marked "shrunk" are pulled to the median of the ' + noun + ' on screen by their own stabilisation point: (n·x + k·median)/(n + k) with k = 3/7 of the sample at which the metric reaches 0.7 split-half reliability' + (shrinkable(S0.x) ? ' (' + k.esc(mX.label) + ' k = ' + k.int(kOf(S0.x)) + ' ' + unit(mX) + ')' : '') + (shrinkable(S0.y) ? ' (' + k.esc(mY.label) + ' k = ' + k.int(kOf(S0.y)) + ' ' + unit(mY) + ')' : '') + '. Totals, RAPM, values and tracking figures are never shrunk here: the models regularise them already or they are not rates.' : '') +
    (mX.desc ? '<br><strong>' + k.esc(mX.label) + '</strong>: ' + k.esc(k.cleanDesc(mX.desc)) : '') + (mY.desc ? '<br><strong>' + k.esc(mY.label) + '</strong>: ' + k.esc(k.cleanDesc(mY.desc)) : ''));
  k.set('lab-ours', RK.ours ? RK.ours.explain([S0.x, S0.y], { label: kk => meta(kk).label || kk, entity: team ? 'team' : 'player' }) : '');
  const oth = kk => (RK.ours && RK.ours.of(kk) ? 'qk-ours-th' : '');
  const host = k.$('lab-table');
  host.innerHTML = k.table([{ label: '#', sortable: false }, { label: team ? 'Team' : (S0.kind === 'G' ? 'Goalie' : 'Skater') }].concat(team ? [] : [{ label: 'Team' }].concat(G().nKey ? [{ label: G().nLabel, align: 'right' }] : []))
    .concat([{ label: label(S0.x), align: 'right', cls: oth(S0.x) }, { label: 'Pct', align: 'right' }, { label: label(S0.y), align: 'right', cls: oth(S0.y) }, { label: 'Pct', align: 'right' }, { label: 'Combined', align: 'right', title: 'Sum of standard scores in the better direction' }]),
  ranked.slice(0, 300).map((o, i) => { const r = o.r, vx = val(r, S0.x), vy = val(r, S0.y);
    return { _href: href(r), cells: [{ v: i + 1, cls: 'pos-cell' }, { v: nm(r), html: team ? k.teamChip(idOf(r), S) + ' <a href="' + href(r) + '">' + k.esc(nm(r)) + '</a>' : '<a class="ply-link" href="' + href(r) + '">' + k.esc(nm(r)) + '</a>' }]
      .concat(team ? [] : [{ v: tm(r) || '', html: k.teamChip(tm(r), S) }].concat(G().nKey ? [{ v: nOf(r), html: k.int(nOf(r)) }] : []))
      .concat([{ v: vx, html: fmt(S0.x, vx) }, { v: pOf(sortedX, vx, dirx), html: k.pill(pOf(sortedX, vx, dirx)) }, { v: vy, html: fmt(S0.y, vy) }, { v: pOf(sortedY, vy, diry), html: k.pill(pOf(sortedY, vy, diry)) }, { v: o.z, html: '<strong>' + k.num(o.z, 2) + '</strong>' }]) }; }), { sticky: true, compact: true });
  k.sortable(host);
}

/* "Most like": the five nearest the highlighted player within the group on screen, on standard scores of the group's
   spec headline metrics (QK.within.similar), each a link to Compare. */
function simStrip(rows, hits, nm, S) {
  const k = K();
  if (!hits.length) return '<p class="pg-note gq-note">Highlight a player to list the five most like them among the ' + k.esc(groupNoun()) + ' on this chart.</p>';
  const t = hits[0], head = headOrder();
  const keys = Object.keys(head).filter(x => G().idx[x] !== undefined).sort((a, b) => head[a] - head[b]);
  const near = QK.within.similar(rows, t, keys, (r, x) => { const v = raw(r, x); return k.isNum(v) ? Number(v) : null; }, 5);
  return QK.within.simHtml('Most like ' + nm(t) + ' · ' + groupNoun(), near.map(o => ({ name: nm(o.row), href: k.withQ('#/compare/' + encodeURIComponent(idOf(t)) + '/' + encodeURIComponent(idOf(o.row)), S),
    sub: [raw(o.row, 'team') || '', k.posLabel(raw(o.row, 'pos'))].filter(Boolean).join(' · ') + ' · compare' })));
}

function render(el, params, state) {
  const k = K();
  el.innerHTML = QK.explain('<b>What’s that number?</b> Each dot is a player or a club on the two metrics you pick. The ranked list orders them by the combined standard score on both axes: 0 is average, +1 one standard deviation better on each.', { html: true }) +
    '<div class="card"><div class="card-header">Lab <span class="card-sub" id="lab-sub">Loading…</span><span class="gq-ctl">' + k.toggle('lab-kind', KINDS, S0.kind) + '</span></div>' +
    '<div id="lab-within" class="rk-lab-within-wrap"></div><div class="lab-controls gq-controls"><label>Preset<select id="lab-preset" class="gq-wide"></select></label><label>Skaters<select id="lab-pos"><option value="A">All</option><option value="F">Forwards</option><option value="D">Defence</option></select></label>' +
    '<label>X axis<select id="lab-x"></select></label><label>Y axis<select id="lab-y"></select></label><label>&nbsp;<button type="button" id="lab-swap" class="gq-btn" title="Swap the axes">⇄ swap</button></label>' +
    '<label>Colour<select id="lab-color"></select></label><label><span>Min <span id="lab-min-u"></span> <span id="lab-min-v"></span></span><input id="lab-min" type="range" min="0" max="2000" step="10"></label>' +
    '<label class="inline"><input id="lab-qual" type="checkbox"> qualified only</label><label class="inline"><input id="lab-shrink" type="checkbox"> shrink by stabilisation</label><label>Highlight<input id="lab-q" class="gq-search" type="search" placeholder="player or team…"></label>' +
    '</div><div id="lab-ours" class="rk-lab-ours"></div><div id="lab-chart" class="gq-lab-chart"></div><div id="lab-sim" class="rk-lab-sim"></div><div class="pg-note gq-note" id="lab-note"></div></div>' +
    '<div class="card"><div class="card-header">Ranked <span class="card-sub">By the combined standard score on both axes (top 300). Click a row for the page.</span></div><div id="lab-table"></div></div>';
  return k.ready().then(() => {
    const S = k.S(params, state);
    return Promise.all([k.loadY(S, 'lab.json'), k.loadY(S, 'skaters.json'), k.loadY(S, 'goalies.json'), k.loadY(S, 'teams.json'), k.loadNames(), RK.ours ? RK.ours.load() : null]).then(res => ({ S: S, res: res }));
  }).then(o => {
    if (!k.alive(el)) return;
    const S = o.S, res = o.res, $ = k.$;
    const sk = k.catOf(res[1]), gk = k.catOf(res[2]);
    if (sk) k.learnCat(sk);
    if (gk) k.learnCat(gk);
    const tms = RK.fk.T ? RK.fk.T.teamsOf(res[3]) : null;
    if (LABK !== String(S)) { LAB = prep(res[0], sk, gk, tms); LABK = String(S); S0.min = null; S0.x = ''; S0.y = ''; S0.preset = 0; }
    if (!Object.keys(LAB).length) { $('lab-chart').innerHTML = k.notBuilt('The ' + k.sLabel(S) + ' lab file', res[0]); $('lab-sub').textContent = ''; return; }
    const qy = params.query || {};
    const qk = String(qy.kind || qy.g || '').toUpperCase().charAt(0);
    if (qk && LAB[qk]) S0.kind = qk;
    const wq = QK.within.read(qy, PCODES);
    if (wq.within === 'pos') { S0.within = 'pos'; S0.grp = wq.pos; S0.kind = wq.pos === 'G' ? 'G' : 'S'; S0.qual = true; }
    else { S0.within = 'broad'; if (/^(F|D|A)$/i.test(qy.pos || '')) S0.pos = String(qy.pos).toUpperCase(); }
    if (!LAB[S0.kind]) S0.kind = Object.keys(LAB)[0];
    const reset = () => {
      const g = G();
      const maxN = Math.max.apply(null, g.rows.map(nOf).concat([10]));
      $('lab-min').max = String(Math.ceil(maxN));
      $('lab-min').step = maxN > 400 ? '10' : '1';
      if (S0.min === null || S0.min > maxN) S0.min = 0;
      if (!S0.x || g.idx[S0.x] === undefined || !S0.y || g.idx[S0.y] === undefined) { if (S0.preset < 0) S0.preset = 0; applyPreset(); }
      if (!S0.x || !S0.y || g.idx[S0.x] === undefined || g.idx[S0.y] === undefined) { const ms = g.metrics; S0.x = (ms[0] || {}).key || g.nKey; S0.y = (ms[1] || {}).key || g.nKey; S0.preset = -1; }
      if (S0.color && ['team', 'pos', 'conf'].indexOf(S0.color) < 0 && g.idx[S0.color] === undefined) S0.color = 'team';
      if (S0.color === 'pos' && S0.kind !== 'S') S0.color = 'team';
      if (S0.color === 'conf' && S0.kind !== 'T') S0.color = 'team';
    };
    reset();
    LAB_RESET = reset;
    if (qy.q !== undefined) S0.q = String(qy.q);
    if (qy.x && G().idx[qy.x] !== undefined) { S0.x = qy.x; S0.preset = -1; }
    if (qy.y && G().idx[qy.y] !== undefined) { S0.y = qy.y; S0.preset = -1; }
    if (S0.x === S0.y) { const alt = G().metrics.find(m => m.key !== S0.x); if (alt) S0.y = alt.key; }
    sync();
    const redraw = () => draw(S);
    LAB_REDRAW = redraw;
    $('lab-kind').querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
      if (!LAB[b.dataset.v]) return;
      S0.kind = b.dataset.v; S0.x = ''; S0.y = ''; S0.preset = 0; S0.min = null;
      if (S0.within === 'pos') { if (S0.kind === 'T') S0.within = 'broad'; else if (S0.kind === 'G') S0.grp = 'G'; else if (S0.grp === 'G') S0.grp = 'F'; }
      reset(); sync(); redraw();
    }));
    $('lab-pos').onchange = e => { S0.pos = e.target.value; redraw(); };
    $('lab-preset').onchange = e => { S0.preset = parseInt(e.target.value, 10); applyPreset(); sync(); redraw(); };
    $('lab-x').onchange = e => { S0.x = e.target.value; S0.preset = -1; sync(); redraw(); };
    $('lab-y').onchange = e => { S0.y = e.target.value; S0.preset = -1; sync(); redraw(); };
    $('lab-swap').onclick = () => { const t = S0.x; S0.x = S0.y; S0.y = t; S0.preset = -1; sync(); redraw(); };
    $('lab-color').onchange = e => { S0.color = e.target.value; redraw(); };
    $('lab-min').oninput = e => { S0.min = parseInt(e.target.value, 10); $('lab-min-v').textContent = k.int(S0.min); };
    $('lab-min').onchange = redraw;
    $('lab-shrink').onchange = e => { S0.shrink = e.target.checked; redraw(); };
    $('lab-qual').onchange = e => { S0.qual = e.target.checked; redraw(); };
    let timer = null;
    $('lab-q').oninput = e => { S0.q = e.target.value; clearTimeout(timer); timer = setTimeout(redraw, 250); };
    redraw();
  });
}

if (typeof RK.route === 'function') { try { RK.route('lab', render); } catch (e) { /* bound */ } }
})(window.RK || (window.RK = {}));
