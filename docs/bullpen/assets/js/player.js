/* The Quant Bullpen — the player page: #/<L>/hitter/<pid>, #/<L>/pitcher/<pid> and #/player/<pid>
 * (two-way players get Hitting and Pitching tabs; the plain route picks the side by position).
 *
 * Hitter: Savant-style percentile sliders over the whole catalogue (against MLB or the position),
 * tiles (xwOBA+ against Savant's xwOBA, Bullpen WAR, decision value, adjusted bat speed), the
 * spray chart coloured by xwOBA+, zone heatmaps by pitch type and count, the swing-decision map,
 * the bat-speed and swing-path profile, rolling xwOBA+ against wOBA, splits, the career
 * (Statcast seasons and Retrosheet-era seasons), projections with ranges and similar players.
 * Pitcher: the arsenal table, the movement plot against the league, release point and extension
 * consistency, tunneling pairs, usage by count and handedness, velocity and spin trends with
 * fatigue signals, zone heatmaps, times through the order, the career and projections.
 *
 * Data: data/players/<pid>.json (career, all levels: "current" holds the deep season panels),
 * data/<L>/<S>/hitters.json and pitchers.json (catalogue values and percentiles; pitchers also
 * "arsenal"), data/<L>/<S>/parks.json (wall distances for the spray chart). Uses BP.gk. */
(function (BP) {
'use strict';

const K = () => BP.gk;
const RETRO_NOTICE = 'The information used here was obtained free of charge from and is copyrighted by Retrosheet. Interested parties may contact Retrosheet at "www.retrosheet.org".';
BP.RETRO_NOTICE = BP.RETRO_NOTICE || RETRO_NOTICE;

// ── labels and formats for keys that are not in a catalogue ────────────────

const LABEL = {
  season: 'Season', level: 'Level', team: 'Team', age: 'Age', g: 'G', gs: 'GS', pa: 'PA', ab: 'AB', h: 'H', '1b': '1B', '2b': '2B', '3b': '3B', hr: 'HR', r: 'R', rbi: 'RBI',
  sb: 'SB', cs: 'CS', bb: 'uBB', ibb: 'IBB', so: 'SO', k: 'SO', hbp: 'HBP', sf: 'SF', avg: 'AVG', obp: 'OBP', slg: 'SLG', ops: 'OPS', iso: 'ISO', babip: 'BABIP',
  woba: 'wOBA', xwoba_plus: 'xwOBA+', xwoba_savant: 'Savant xwOBA', xwoba: 'xwOBA', xba: 'xBA', xslg: 'xSLG', wrc_plus: 'wRC+', war: 'WAR', bwar: 'Bullpen WAR',
  ip: 'IP', w: 'W', l: 'L', sv: 'SV', hld: 'HLD', bf: 'BF', tbf: 'BF', er: 'ER', era: 'ERA', fip: 'FIP', xfip: 'xFIP', whip: 'WHIP', k_pct: 'K%', bb_pct: 'BB%', k_bb_pct: 'K−BB%',
  hr9: 'HR/9', k9: 'K/9', bb9: 'BB/9', ra9: 'RA9', stuff_plus: 'Stuff+', location_plus: 'Location+', pitching_plus: 'Pitching+', batting_runs: 'Batting runs', lw_runs: 'Linear-weights runs',
  rv: 'Run value', rv100: 'RV/100', usage: 'Usage', velo: 'Velo', ivb: 'IVB', hb: 'HB', spin: 'Spin', vaa: 'VAA', haa: 'HAA', ext: 'Ext', whiff: 'Whiff%', csw: 'CSW%', chase: 'Chase%',
  n: 'n', pitches: 'Pitches', stuff: 'Stuff+', location: 'Location+', pitching: 'Pitching+', xwoba_against: 'xwOBA+ against', putaway: 'Put-away%', zone: 'Zone%',
  bat_speed: 'Bat speed', bat_speed_adj: 'Adjusted bat speed', swing_length: 'Swing length', attack_angle: 'Attack angle', attack_direction: 'Attack direction', swing_path_tilt: 'Swing-path tilt',
  squared_up: 'Squared-up%', squared_up_exp: 'Expected squared-up%', squared_up_oe: 'Squared-up over expected', fast_swing: 'Fast-swing%', blast: 'Blast%', intercept_y: 'Intercept (in front)',
  decision_value: 'Decision value', chase_pct: 'Chase%', zone_swing_pct: 'Zone swing%', whiff_pct: 'Whiff%', barrel_pct: 'Barrel%', hard_hit_pct: 'Hard-hit%', ev: 'Exit velo', la: 'Launch angle',
  p10: '10th pct', p50: 'Median', p90: '90th pct', mean: 'Mean', lo: 'Low', hi: 'High',
  b1: '1B', b2: '2B', b3: '3B', dv: 'Decision value', hard_pct: 'Hard-hit%', csw_pct: 'CSW%', fb_velo: 'FB velo', oaa: 'OAA', framing_runs: 'Framing runs',
  games: 'G', outs: 'Outs', runs: 'R', wraa: 'wRAA', ra9_minus: 'RA9−', vL: 'v LHP', vR: 'v RHP', home: 'Home', away: 'Away', pos: 'Pos'
};
const RATE3 = /^(avg|obp|slg|ops|iso|babip|woba|xwoba.*|xba|xslg|x?obp|wobacon|xwobacon|ba|slg_against|avg_against)$/;
function label(k) { return LABEL[k] || LABEL[String(k).toLowerCase()] || K().titleCase(String(k).replace(/_pct$/, ' %').replace(/_plus$/, '+')); }
function guessFmt(k, v, meta) {
  if (meta && meta[k] && meta[k].fmt) return meta[k].fmt;
  const key = String(k).toLowerCase();
  if (RATE3.test(key) || /xwoba/.test(key)) return '3';
  if (/plus$|_plus|\+$|^stuff$|^location$|^pitching$/.test(key)) return 'plus';
  if (/_pct$|pct$|rate$|^usage|^whiff|^csw|^chase|^zone$|^putaway|share|^p_|prob/.test(key)) return Math.abs(v) <= 1.5 ? 'pct' : '1';
  if (/war$|runs|^rv$|value|^dv|_oe$|over_exp/.test(key)) return 'signed';
  if (/^ip$/.test(key)) return 'ip';
  if (/spin|rpm/.test(key)) return 'rpm';
  if (/velo|speed|mph|^ev$|ivb|^hb$|break|angle|vaa|haa|ext|length|tilt|^la$|_in$|_ft$|era|fip|whip|ra9|9$/.test(key)) return /era|fip|whip|ra9|9$/.test(key) ? '2' : '1';
  if (Number.isInteger(Number(v))) return 'int';
  return Math.abs(v) < 1 ? '3' : '2';
}
function fv(k, v, meta) { return K().fmtV(v, guessFmt(k, v, meta)); }

// ── generic structures ─────────────────────────────────────────────────────

const PITCHRE = /^(FF|SI|FC|FA|SL|ST|SV|CU|KC|CS|CH|FS|FO|SC|KN|EP|PO|all|ALL)$/;
const COUNTRE = /^([0-3]-[0-2]|ahead|behind|even|two_strikes|2k|first|first_pitch|0k|all)$/i;
function isMatrix(v) { return Array.isArray(v) && v.length > 1 && v.every(r => Array.isArray(r) && r.length === v[0].length) && v[0].length > 1; }
function isGrid(v) {
  if (!v) return false;
  if (isMatrix(v)) return true;
  if (Array.isArray(v)) return v.length > 0 && (Array.isArray(v[0]) ? v[0].length >= 3 : !!(v[0] && typeof v[0] === 'object' && ('x' in v[0] || 'px' in v[0])));
  if (typeof v === 'object') return ['v', 'values', 'grid', 'value', 'mean'].some(k => isMatrix(v[k])) || (isMatrix(v.z));
  return false;
}
/* Metrics carried by one grid object with several matrices: {x, z, xwoba_plus: [[...]], swing: [[...]], n: [[...]]}. */
function gridMetrics(g) {
  if (!g || Array.isArray(g) || typeof g !== 'object') return [];
  return Object.keys(g).filter(k => isMatrix(g[k]) && !/^(n|count|counts|x|xe|ze|z_edges|x_edges)$/.test(k));
}
function dimName(keys) {
  if (keys.every(k => PITCHRE.test(k) || k === 'all')) return 'Pitch';
  if (keys.every(k => COUNTRE.test(k) || k === 'all')) return 'Count';
  if (keys.every(k => /^(L|R|vL|vR|vs_?L|vs_?R|all)$/i.test(k))) return 'Hand';
  return 'View';
}
function keyLabel(k) {
  const k2 = String(k);
  if (PITCHRE.test(k2)) return K().pitchName(k2) + (k2 === 'all' || k2 === 'ALL' ? '' : ' (' + k2 + ')');
  if (/^vs_?L$|^vL$|^L$/i.test(k2)) return 'v LHP/LHB';
  if (/^vs_?R$|^vR$|^R$/i.test(k2)) return 'v RHP/RHB';
  if (/^[0-3]-[0-2]$/.test(k2)) return k2 + ' count';
  return label(k2);
}
/* Grid explorer: walks nested objects until it finds a grid; one select per level and one for the metric when a grid
 * carries several. host: element; root: the payload object; opts {fmt, diverge, label, prefer: [keys], id, reverse}. */
function gridExplorer(host, root, opts) {
  const k = K(), o = opts || {};
  if (!host) return;
  if (!root || (typeof root === 'object' && !Object.keys(root).length)) { host.innerHTML = k.muted(o.empty || 'Not available for this player yet.'); return; }
  const path = [];
  let metric = null;
  const ctl = document.createElement('div'); ctl.className = 'gq-gx-ctl';
  const fig = document.createElement('div'); fig.className = 'gq-zone';
  const note = document.createElement('div'); note.className = 'gq-gx-note';
  host.innerHTML = ''; host.appendChild(ctl); host.appendChild(fig); host.appendChild(note);
  const sortKeys = keys => keys.slice().sort((a, b) => (a === 'all' || a === 'ALL' ? -1 : b === 'all' || b === 'ALL' ? 1 : 0));
  const pickDefault = keys => { const pref = (o.prefer || []).concat(['all', 'ALL', 'FF', '0-0']); for (let i = 0; i < pref.length; i++) if (keys.indexOf(pref[i]) >= 0) return pref[i]; return keys[0]; };
  const draw = () => {
    // Resolve the path, rebuilding defaults where a level changed shape.
    let node = root, html = '', depth = 0;
    while (node && !isGrid(node) && typeof node === 'object' && !Array.isArray(node) && depth < 4) {
      const keys = sortKeys(Object.keys(node).filter(x => node[x] && typeof node[x] === 'object' && !/^(meta|desc|note|cols|x|z|xe|ze|n)$/.test(x)));
      if (!keys.length) break;
      if (path[depth] === undefined || keys.indexOf(path[depth]) < 0) path[depth] = pickDefault(keys);
      const id = (o.id || 'gx') + '-d' + depth;
      html += '<label>' + dimName(keys) + k.select(id, keys.map(x => [x, keyLabel(x)]), path[depth]) + '</label>';
      node = node[path[depth]];
      depth++;
    }
    path.length = depth;
    const ms = gridMetrics(node);
    if (ms.length > 1 || (ms.length === 1 && !isGrid(node))) {
      if (!metric || ms.indexOf(metric) < 0) metric = ms.find(x => (o.prefer || []).indexOf(x) >= 0) || ms[0];
      html += '<label>Metric' + k.select((o.id || 'gx') + '-m', ms.map(x => [x, label(x)]), metric) + '</label>';
    }
    ctl.innerHTML = html;
    ctl.querySelectorAll('select').forEach(sel => sel.addEventListener('change', () => {
      const m = /-d(\d+)$/.exec(sel.id);
      if (m) { path[Number(m[1])] = sel.value; path.length = Number(m[1]) + 1; } else metric = sel.value;
      draw();
    }));
    let grid = node;
    if (ms.length && metric && node && !Array.isArray(node)) grid = Object.assign({}, node, { v: node[metric] });
    const mk = metric || o.metricKey || '';
    const rateLike = /xwoba|woba|ba$|slg/.test(mk) || o.rate;
    const diverge = isNum(o.diverge) ? o.diverge : /value|rv|runs|_oe|diff/.test(mk) ? 0 : undefined;
    k.zoneHeat(fig, grid, { fmt: o.fmt || (rateLike ? '3' : /pct|rate|swing|whiff|chase|usage|prob/.test(mk) ? 'pct' : /value|rv|runs/.test(mk) ? 'signed2' : ''), diverge: diverge, label: mk ? label(mk) : (o.label || 'value'), top: o.top, bot: o.bot, reverse: o.reverse });
    note.innerHTML = (grid && grid.desc ? k.esc(grid.desc) + ' ' : '') + (o.note || '');
  };
  const isNum = k.isNum;
  draw();
}

/* The career files' zone grids: 5 × 5 cells, rows low → high, columns left → right from the catcher's view; the inner
 * 3 × 3 is the strike zone in thirds and the outer ring is outside it. A cell is an array of numbers (or null).
 * host: element; grids: {key: grid} (or one grid); opts {cols: [[name, label, index, fmt, scale ('div'|'seq'), centre]],
 * keyLabel, id, prefer, share: index of the count column to also offer a share-of-pitches view, note}. */
function zone5(host, grids, opts) {
  const k = K(), o = opts || {};
  if (!host) return;
  const isG = g => Array.isArray(g) && g.length === 5 && g.every(r => Array.isArray(r) && r.length === 5);
  const G = isG(grids) ? { all: grids } : (grids && typeof grids === 'object' ? grids : {});
  const keys = Object.keys(G).filter(x => isG(G[x]));
  if (!keys.length) { host.innerHTML = k.muted(o.empty || 'Not available for this player yet.'); return; }
  const cols = (o.cols || []).slice();
  if (k.isNum(o.share)) cols.push(['share', 'Share of pitches', o.share, 'pct', 'seq']);
  const st = { key: keys.indexOf(o.prefer) >= 0 ? o.prefer : keys[0], col: cols[0][0] };
  host.innerHTML = '<div class="gq-gx-ctl">' + (keys.length > 1 ? '<label>' + k.esc(o.keyName || 'Pitches') + k.select((o.id || 'z5') + '-k', keys.map(x => [x, o.keyLabel ? o.keyLabel(x) : x]), st.key) + '</label>' : '') +
    (cols.length > 1 ? '<label>Show' + k.select((o.id || 'z5') + '-c', cols.map(c => [c[0], c[1]]), st.col) + '</label>' : '') + '</div><div class="gq-zone"></div><div class="gq-gx-note"></div>';
  const fig = host.querySelector('.gq-zone'), note = host.querySelector('.gq-gx-note');
  const draw = () => {
    const g = G[st.key], c = cols.find(x => x[0] === st.col) || cols[0];
    let tot = 0;
    g.forEach(r => r.forEach(cell => { if (Array.isArray(cell) && k.isNum(cell[0])) tot += cell[0]; }));
    const val = cell => (!Array.isArray(cell) ? null : c[0] === 'share' ? (tot ? cell[c[2]] / tot : null) : cell[c[2]]);
    const nOf = cell => (Array.isArray(cell) ? cell[o.nIndex === undefined ? 0 : o.nIndex] : null);
    const z = g.map(r => r.map(val));
    const flat = [].concat.apply([], z).filter(k.isNum);
    if (!flat.length) { fig.innerHTML = k.muted('No pitches in this view.'); return; }
    let zmin = Math.min.apply(null, flat), zmax = Math.max.apply(null, flat);
    const div = c[4] === 'div';
    if (div) { const ctr = k.isNum(c[5]) ? c[5] : k.median(flat); const r = Math.max(zmax - ctr, ctr - zmin) || 1; zmin = ctr - r; zmax = ctr + r; }
    const txt = z.map((r, i) => r.map((v, j) => (k.isNum(v) ? k.fmtV(v, c[3]) : '')));
    const hov = z.map((r, i) => r.map((v, j) => (k.isNum(v) ? k.esc(c[1]) + ' ' + k.fmtV(v, c[3]) + (k.isNum(nOf(g[i][j])) ? ' · ' + k.int(nOf(g[i][j])) + (o.nLabel || ' pitches') : '') : 'no pitches')));
    const ann = [];
    z.forEach((r, i) => r.forEach((v, j) => { if (k.isNum(v)) ann.push({ x: j, y: i, text: txt[i][j], showarrow: false, font: { size: K().narrow(fig) ? 9 : 11, color: '#f0f3f6' } }); }));
    const scale = div ? K().DIVERGE : [[0, '#1b2433'], [0.5, '#5b6f8f'], [1, '#e8504f']];
    K().plot(fig, [{ type: 'heatmap', x: [0, 1, 2, 3, 4], y: [0, 1, 2, 3, 4], z: z, zmin: zmin, zmax: zmax, colorscale: scale, xgap: 2, ygap: 2, showscale: false, text: hov, hoverinfo: 'text' }],
      K().layout({ margin: { l: 6, r: 6, t: 6, b: 24 }, annotations: ann,
        xaxis: { range: [-0.6, 4.6], showgrid: false, zeroline: false, showticklabels: false, fixedrange: true, scaleanchor: 'y', scaleratio: 1.15 },
        yaxis: { range: [-1.0, 4.6], showgrid: false, zeroline: false, showticklabels: false, fixedrange: true },
        shapes: [{ type: 'rect', x0: 0.5, x1: 3.5, y0: 0.5, y1: 3.5, line: { color: '#e6edf3', width: 2 } },
          { type: 'path', path: 'M 1.0 -0.55 L 3.0 -0.55 L 3.0 -0.7 L 2.0 -0.9 L 1.0 -0.7 Z', line: { color: '#8b949e', width: 1 }, fillcolor: 'rgba(230,237,243,0.12)' }] }));
    note.innerHTML = 'Catcher\'s view. The white box is the strike zone in thirds (the batter\'s own zone height); the outer ring is outside it. ' + (o.note || '');
  };
  host.querySelectorAll('select').forEach(sel => sel.addEventListener('change', () => { if (/-k$/.test(sel.id)) st.key = sel.value; else st.col = sel.value; draw(); }));
  draw();
}

/* A table of named rows of metrics: {rowKey: {metric: v}} or [{split|name|key, ...}] → html. */
function rowsTable(obj, meta, opts) {
  const k = K(), o = opts || {};
  let rows = [];
  if (Array.isArray(obj)) rows = obj.map(r => ({ key: r.split || r.name || r.key || r.label || r.id || '', v: r }));
  else if (obj && typeof obj === 'object') rows = Object.keys(obj).filter(x => obj[x] && typeof obj[x] === 'object' && !Array.isArray(obj[x])).map(x => ({ key: x, v: obj[x] }));
  if (!rows.length) return k.muted(o.empty || 'Not available yet.');
  const skip = /^(split|name|key|label|id|desc|note)$/;
  const keys = [];
  rows.forEach(r => Object.keys(r.v).forEach(x => { if (!skip.test(x) && k.isNum(r.v[x]) && keys.indexOf(x) < 0) keys.push(x); }));
  const order = o.order || [];
  keys.sort((a, b) => (order.indexOf(a) < 0 ? 99 : order.indexOf(a)) - (order.indexOf(b) < 0 ? 99 : order.indexOf(b)));
  const cols = keys.slice(0, o.max || 14);
  return k.table([{ label: o.first || 'Split' }].concat(cols.map(c => ({ label: (meta && meta[c] && meta[c].label) || label(c), align: 'right', title: (meta && meta[c] && meta[c].desc) || '' }))),
    rows.map(r => [{ v: r.key, html: '<strong>' + k.esc(o.keyLabel ? o.keyLabel(r.key) : keyLabel(r.key)) + '</strong>' }].concat(cols.map(c => ({ v: r.v[c], html: fv(c, r.v[c], meta) })))), { compact: true });
}

// ── data shapes ────────────────────────────────────────────────────────────

function flatSeason(r) {
  if (!r || typeof r !== 'object') return {};
  const out = Object.assign({}, r);
  ['traditional', 'trad', 'stats', 'value'].forEach(x => { if (r[x] && typeof r[x] === 'object' && !Array.isArray(r[x])) Object.assign(out, r[x]); });
  return out;
}
/* Season rows of one side: hitting rows carry pa (or a "hitting" block), pitching rows ip/bf (or a "pitching" block). */
function seasonsOf(list, side) {
  return (list || []).map(r0 => {
    const r = r0 || {};
    if (r.hitting || r.pitching) { const b = side === 'pit' ? r.pitching : r.hitting; return b ? Object.assign({ season: r.season, level: r.level, team: r.team, age: r.age }, flatSeason(b)) : null; }
    const f = flatSeason(r);
    const role = String(f.kind || f.role || f.type || '').toLowerCase();
    if (role) return (side === 'pit') === /pit/.test(role) ? f : null;
    if (side === 'pit') return K().isNum(f.ip) || K().isNum(f.bf) || K().isNum(f.tbf) || K().isNum(f.era) ? f : null;
    return K().isNum(f.pa) || K().isNum(f.ab) ? f : null;
  }).filter(Boolean);
}
const HIT_COLS = ['season', 'level', 'team', 'pos', 'g', 'pa', 'ab', 'h', 'b2', 'b3', 'hr', 'bb', 'so', 'sb', 'avg', 'obp', 'slg', 'ops', 'woba', 'xwoba_plus', 'xwoba_savant', 'k_pct', 'bb_pct', 'barrel_pct', 'hard_pct', 'ev', 'chase_pct', 'whiff_pct', 'bat_speed', 'dv', 'oaa', 'framing_runs', 'war'];
const PIT_COLS = ['season', 'level', 'team', 'pos', 'g', 'gs', 'w', 'l', 'sv', 'ip', 'bf', 'so', 'bb', 'hr', 'ra9', 'fip', 'whip', 'k_pct', 'bb_pct', 'k_bb_pct', 'csw_pct', 'whiff_pct', 'xwoba_plus', 'xwoba_savant', 'fb_velo', 'stuff_plus', 'location_plus', 'pitching_plus', 'war'];
function careerTable(rows, cols, L, meta) {
  const k = K();
  if (!rows.length) return '';
  const present = cols.filter(c => rows.some(r => r[c] !== undefined && r[c] !== null));
  const tot = {};
  const TT = { g: 'Games with a plate appearance (hitters) or games pitched (pitchers)', bb: 'Unintentional walks (intentional walks are IBB)', r: 'For a pitcher, runs scored while the pitcher was on the mound (inherited runners are not reassigned; not earned runs)' };
  return k.table(present.map(c => ({ label: label(c), align: /season|level|team/.test(c) ? 'left' : 'right', title: TT[c] || '' })),
    rows.slice().sort((a, b) => (a.season - b.season) || String(a.level).localeCompare(String(b.level))).map(r => present.map(c => {
      const v = r[c];
      if (c === 'team') return { v: k.teamAbbr(v), html: v ? (k.TEAMS[String(v)] ? k.teamChip(r.level || L, v, r.season) : k.esc(v)) : '—' };
      if (c === 'level') return { v: v, html: '<span class="gq-lv gq-lv-' + k.esc(String(v || '').toLowerCase()) + '">' + k.esc(v ? (String(v).toLowerCase() === 'aaa' ? 'AAA' : String(v).toUpperCase()) : '—') + '</span>' };
      if (c === 'season') return { v: v, html: '<strong>' + k.esc(v) + '</strong>' };
      tot[c] = 1;
      return { v: v, html: fv(c, v, meta) };
    })), { compact: true, sticky: true });
}

/* Arsenal rows from {pt: {...}} or [{pitch_type, ...}]. */
function arsenalOf(a) {
  if (!a) return [];
  const list = Array.isArray(a) ? a.map(r => Object.assign({ pt: r.pitch_type || r.pt || r.type }, r)) : Object.keys(a).filter(pt => a[pt] && typeof a[pt] === 'object').map(pt => Object.assign({ pt: pt }, a[pt]));
  const k = K();
  const u = r => k.val(r, ['usage', 'usage_pct', 'pct', 'share']);
  return list.filter(r => r.pt && r.pt !== 'all' && r.pt !== 'ALL').sort((x, y) => (u(y) || 0) - (u(x) || 0));
}
const ARS = [
  ['usage', 'Usage', ['usage', 'usage_pct', 'share', 'pct'], 'pct', 'Share of the pitcher\'s pitches'],
  ['n', 'Pitches', ['n', 'pitches', 'count'], 'int', ''],
  ['velo', 'Velo', ['velo', 'velocity', 'release_speed', 'speed', 'mph'], '1', 'Average release speed (mph)'],
  ['ivb', 'IVB', ['ivb', 'induced_vb', 'pfx_z_in', 'ivb_in'], '1', 'Induced vertical break, inches (gravity removed)'],
  ['hb', 'HB (arm)', ['hb', 'horz_break', 'hb_arm', 'hb_in'], '1', 'Horizontal break in inches towards the pitcher\'s arm side (negative = glove side)'],
  ['spin', 'Spin', ['spin', 'spin_rate', 'release_spin_rate', 'rpm'], 'rpm', 'Spin rate (rpm)'],
  ['vaa', 'VAA', ['vaa', 'vaa_deg'], '1', 'Vertical approach angle at the plate (degrees)'],
  ['vaa_oe', 'VAA v exp', ['vaa_oe', 'vaa_above_exp', 'vaa_aa', 'vaa_rel'], 'signed', 'VAA against the expectation for its height in the zone'],
  ['ext', 'Ext', ['ext', 'extension', 'release_extension'], '1', 'Extension (ft)'],
  ['arm_angle', 'Arm°', ['arm_angle'], '0', 'Arm angle (degrees above horizontal)'],
  ['spin_eff', 'Spin eff.', ['spin_eff'], 'pct', 'Spin efficiency: the share of spin that moves the ball'],
  ['stuff', 'Stuff+', ['stuff_plus', 'stuff'], 'plus', 'Stuff+: expected run value from the pitch\'s physical characteristics only, 100 = league average'],
  ['location', 'Location+', ['location_plus', 'location'], 'plus', 'Location+: expected run value from location given count, pitch type and platoon'],
  ['pitching', 'Pitching+', ['pitching_plus', 'pitching'], 'plus', 'Pitching+: stuff, location and sequencing together'],
  ['whiff', 'Whiff%', ['whiff_pct', 'whiff', 'whiff_rate'], 'pct', 'Whiffs per swing'],
  ['csw', 'CSW%', ['csw_pct', 'csw'], 'pct', 'Called strikes plus whiffs per pitch'],
  ['chase', 'Chase%', ['chase', 'chase_pct'], 'pct', 'Swings at pitches outside the zone'],
  ['xw', 'xwOBA', ['xwoba_plus', 'xwoba', 'xwoba_against'], '3', 'Expected wOBA against the pitch'],
  ['xrv100', 'xRV/100', ['xrv100'], 'signed2', 'Pitching+ expected run value per 100 pitches (pitcher\'s side, + = good)'],
  ['rv', 'Run value', ['rv', 'run_value', 'rv_total'], 'signed', 'Runs saved with the pitch (positive = good for the pitcher)'],
  ['rv100', 'RV/100', ['rv100', 'rv_per_100', 'run_value_100'], 'signed2', 'Run value per 100 pitches']
];
function arsenalTable(rows, meta) {
  const k = K();
  const cols = ARS.filter(c => rows.some(r => k.pick(r, c[2]) !== null && k.isNum(r[k.pick(r, c[2])])));
  return k.table([{ label: 'Pitch' }].concat(cols.map(c => ({ label: c[1], align: 'right', title: c[4] }))), rows.map(r => [{ v: r.pt, html: k.pitchChip(r.pt) + ' ' + k.esc(k.pitchName(r.pt)) }].concat(cols.map(c => {
    const key = k.pick(r, c[2]), v = r[key];
    const pc = key === 'stuff' ? r.stuff_pct : key === 'whiff' ? r.whiff_pct_type : (r.pct || {})[key];
    const plus = c[3] === 'plus' && k.isNum(v);
    return { v: v, html: (plus ? '<span class="gq-plus" style="color:' + k.pctColor(Math.max(0, Math.min(100, 50 + (v - 100) * 2.5))) + '">' : '') + k.fmtV(v, c[3]) + (plus ? '</span>' : '') + (k.isNum(pc) ? ' ' + k.pill(pc) : '') };
  }))), { compact: true });
}

/* Movement groups from the payload's shapes: points [[pt, hb, ivb]] | {pt: [[hb, ivb]]} | [{pt, hb, ivb}] plus arsenal averages. */
/* Movement groups in catcher's view. E's rows: movement [[pt, arm-side HB, IVB, velo]], arsenal {pt: {hb (arm side), ivb}}.
 * side = +1 for a left-hander (arm side is the catcher's right), −1 for a right-hander. */
function movementGroups(mv, ars, side) {
  const k = K(), by = {};
  const add = (pt, hb, ivb) => { if (!pt || !k.isNum(hb) || !k.isNum(ivb)) return; (by[pt] = by[pt] || []).push([side * hb, +ivb]); };
  const pts = mv && (mv.points || mv.pts || (Array.isArray(mv) ? mv : null));
  if (Array.isArray(pts)) pts.forEach(p => { if (Array.isArray(p)) add(p[0], p[1], p[2]); else if (p) add(p.pt || p.pitch_type, p.hb, p.ivb); });
  const rows = ars.length ? ars : Object.keys(by).map(pt => ({ pt: pt }));
  return rows.map(r => {
    const hb = k.val(r, ['hb', 'hb_arm']), ivb = k.val(r, ['ivb', 'induced_vb']);
    const p = by[r.pt] || [];
    return { pt: r.pt, points: p, hb: k.isNum(hb) ? side * hb : k.mean(p.map(x => x[0])), ivb: k.isNum(ivb) ? ivb : k.mean(p.map(x => x[1])), usage: k.val(r, ['usage', 'usage_pct']), velo: k.val(r, ['velo', 'velocity']) };
  });
}

/* League norms per pitch type (pitchers.json "league_types", arm-side HB) for the pitch types he throws. */
function leagueRef(lt, ars, side) {
  const k = K(), out = [];
  ars.forEach(r => { const g = (lt || {})[r.pt]; if (g && k.isNum(g.hb) && k.isNum(g.ivb)) out.push({ pt: r.pt, hb: side * g.hb, ivb: g.ivb, sd_hb: g.sd_hb, sd_ivb: g.sd_ivb }); });
  return out;
}

// ── render ─────────────────────────────────────────────────────────────────

let VIEW = { basis: 'all', tab: null };

function render(el, params, state, forced) {
  const k = K();
  if (!k) { el.innerHTML = '<div class="muted">The page kit (hitters.js) did not load.</div>'; return null; }
  const L = k.L(params, state);
  const pid = String(params.id || params.pid || (params.rest || [])[0] || '');
  el.innerHTML = k.muted('Loading…');
  return k.ready().then(() => {
    const S = k.S(params, state);
    return Promise.all([BP.load('players/' + pid + '.json'), k.loadY(L, S, 'hitters.json'), k.loadY(L, S, 'pitchers.json'), k.loadY(L, S, 'parks.json'), k.loadNames()])
      .then(res => ({ S: S, res: res }));
  }).then(o => {
    if (!k.alive(el)) return;
    const res = o.res, S = o.S;
    const career = k.ok(res[0]) ? res[0] : null;
    const hc = k.catOf(res[1], 'hitters'), pc = k.catOf(res[2], 'pitchers');
    if (hc) k.learnCat(hc);
    if (pc) k.learnCat(pc);
    const hp = hc && hc.players[pid], pp = pc && pc.players[pid];
    const c = career || {};
    const pos = c.pos || (hp || {}).pos || (pp || {}).pos || (k.NAMES[pid] || {}).pos || '';
    const cur = c.current || {};
    const hasHit = !!hp || !!cur.hitting || seasonsOf(c.seasons, 'hit').length > 0;
    const hasPit = !!pp || !!cur.pitching || !!cur.arsenal || seasonsOf(c.seasons, 'pit').length > 0;
    let side = forced || (k.isPitcherPos(pos) ? 'pit' : 'hit');
    if (!forced && !k.isPitcherPos(pos) && !hasHit && hasPit) side = 'pit';
    const twoWay = k.isTwoWay(pos) || (hasHit && hasPit && hp && pp && k.sampleOf(hp, 'hitter') >= 50 && k.sampleOf(pp, 'pitcher') >= 50);
    if (!career && !hp && !pp) {
      el.innerHTML = k.card('Player', '', k.notBuilt('The page for ' + k.name(pid), res[0]) + '<div class="pg-note gq-note"><a href="' + k.href(L, 'hitters', S) + '">All hitters →</a> · <a href="' + k.href(L, 'pitchers', S) + '">All pitchers →</a></div>');
      return;
    }
    const name = c.name || (hp || pp || {}).name || k.name(pid);
    k.learn(pid, { name: name });
    const team = (hp || pp || {}).team || c.team || (k.NAMES[pid] || {}).team;
    const age = (hp || pp || {}).age || k.ageOf(c.dob);
    const ids = c.ids || {};
    const links = [];
    const sim = (c.similar || [])[0];
    const simId = Array.isArray(sim) ? sim[0] : sim && (sim.pid || sim.id);
    if (simId) links.push('<a href="' + k.compareHref(pid, simId) + '">Compare with ' + k.esc(k.surname(k.name(simId))) + ' →</a>');
    if (team) links.push('<a href="' + k.teamHref(L, team, S) + '">' + k.esc(k.teamName(team)) + ' →</a>');
    links.push('<a href="' + k.href(L, 'lab', S) + '">Lab →</a>');
    const ext = [];
    if (pid && /^\d+$/.test(pid)) ext.push('<a href="https://baseballsavant.mlb.com/savant-player/' + encodeURIComponent(pid) + '" target="_blank" rel="noopener">Savant ↗</a>');
    if (ids.bbref || c.bbref) ext.push('<a href="https://www.baseball-reference.com/players/' + encodeURIComponent(String(ids.bbref || c.bbref).charAt(0)) + '/' + encodeURIComponent(ids.bbref || c.bbref) + '.shtml" target="_blank" rel="noopener">Baseball-Reference ↗</a>');
    if (ids.fg || c.fg) ext.push('<a href="https://www.fangraphs.com/players/x/' + encodeURIComponent(ids.fg || c.fg) + '" target="_blank" rel="noopener">FanGraphs ↗</a>');
    const sub = [team ? k.teamChip(L, team, S) : '', pos ? '<span class="chip">' + k.esc(pos) + '</span>' : '',
      c.bats || c.throws ? '<span>Bats ' + k.esc(c.bats || '?') + ' · Throws ' + k.esc(c.throws || '?') + '</span>' : '',
      k.isNum(age) ? '<span>age ' + Math.floor(age) + '</span>' : '', c.debut ? '<span>debut ' + k.esc(String(c.debut).slice(0, 10)) + '</span>' : '',
      '<span class="chip">' + k.LN(L) + ' ' + S + '</span>'].filter(Boolean).join(' ');
    let h = k.head(k.esc(name), sub + (ext.length ? '<div class="gq-ext">' + ext.join(' · ') + '</div>' : ''), links.join(''), team ? k.esc(k.teamAbbr(team)) : (k.esc(pos) || 'MLB'), team ? k.teamColour(team) : null);
    if (twoWay) {
      if (!forced && VIEW.tab) side = VIEW.tab;
      h += '<div class="gq-tabs" id="pp-tabs"><button type="button" data-v="hit"' + (side === 'hit' ? ' class="on"' : '') + '>Hitting</button><button type="button" data-v="pit"' + (side === 'pit' ? ' class="on"' : '') + '>Pitching</button></div>';
    }
    h += '<div id="pp-body"></div>';
    el.innerHTML = h;
    const ctx = { L: L, S: S, pid: pid, career: c, cur: cur, hc: hc, pc: pc, hp: hp, pp: pp, parks: res[3], name: name, team: team, pos: pos };
    const draw = s => {
      const body = document.getElementById('pp-body');
      if (!body) return;
      body.innerHTML = '';
      if (s === 'pit') drawPitcher(body, ctx); else drawHitter(body, ctx);
      drawShared(body, ctx, s);
    };
    if (twoWay) {
      const tabs = document.getElementById('pp-tabs');
      tabs.querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
        tabs.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
        VIEW.tab = b.dataset.v;
        draw(b.dataset.v);
      }));
    }
    draw(side);
    if (typeof BP.setMeta === 'function') { try { BP.setMeta(k.esc(name)); } catch (e) { /* optional */ } }
  });
}

function parkDims(ctx) {
  const k = K();
  const P = ctx.parks && ctx.parks.ok !== false ? (ctx.parks.parks || ctx.parks) : {};
  const vid = (k.team(ctx.team) || {}).venue;
  const p = vid && P[vid];
  return (p && (p.dims || p.dimensions)) || null;
}

function sliderCard(ctx, cat, p, kind) {
  const k = K();
  const metrics = (cat && cat.metrics) || [];
  if (!p) return k.card('Percentiles', '', k.muted('Not in the ' + k.LN(ctx.L) + ' ' + ctx.S + ' ' + (kind === 'pit' ? 'pitcher' : 'hitter') + ' catalogue.'));
  const roleLbl = kind === 'pit' ? (k.roleOf(p) === 'RP' ? 'relievers' : k.roleOf(p) === 'SP' ? 'starters' : 'role') : (p.pos ? p.pos + 's' : 'position');
  return '<div class="card"><div class="card-header">Percentile rankings <span class="card-sub">All ' + metrics.length + ' catalogue metrics, ' + k.LN(ctx.L) + ' ' + ctx.S + ', ' + k.int(k.sampleOf(p, kind === 'pit' ? 'pitcher' : 'hitter')) + (kind === 'pit' ? ' batters faced' : ' PA') + '. Blue is good, red is poor (the same scale on every Quant site); lower-is-better metrics are flipped.' +
    (p.qualified === false ? ' <strong>Below the sample floor: percentiles are provisional or missing.</strong>' : '') + '</span>' +
    '<span class="gq-ctl">' + k.toggle('pp-basis', [['all', 'v ' + k.LN(ctx.L)], ['role', 'v ' + roleLbl]], VIEW.basis) + '</span></div><div id="pp-sl" class="gq-pad"></div></div>';
}
function fillSliders(ctx, cat, p) {
  const k = K();
  const host = document.getElementById('pp-sl');
  if (!host || !p) return;
  const draw = () => {
    const src = VIEW.basis === 'role' ? (p.pct_role || p.pct_pos || {}) : (p.pct || {});
    host.innerHTML = k.sliders(cat.metrics, p.values, src, { note: 'Hover a row for the definition and the sample at which it stabilises; click for the glossary entry.' });
  };
  draw();
  k.wireToggle(document, 'pp-basis', v => { VIEW.basis = v; draw(); });
}

// ── hitter ─────────────────────────────────────────────────────────────────

function drawHitter(body, ctx) {
  const k = K();
  const p = ctx.hp, cur = ctx.cur, hit = cur.hitting || {};
  const v = Object.assign({}, hit.values || {}, (p && p.values) || {});
  const pc = (p && p.pct) || hit.pct || {};
  const meta = k.metaOf((ctx.hc || {}).metrics);
  const g = cands => { const key = k.pick(v, cands); return key ? { key: key, v: v[key], p: pc[key] } : { v: null }; };
  const xw = g(['xwoba_plus']), sv = g(['xwoba_savant']), wo = g(['woba']), war = g(['war']);
  const dv = g(['dv', 'decision_value']), bs = g(['bat_speed_adj', 'bat_speed']), pa = g(['pa']);
  const pctTxt = x => (k.isNum(x.p) ? ' · ' + k.ordinal(x.p) + ' pct' : '');
  const curNote = k.isNum(cur.season) && Number(cur.season) !== ctx.S ? '<div class="warn-banner gq-warn">The charts below show ' + cur.season + ' (' + k.LN(cur.level || ctx.L) + '), the latest season on file for this player; the percentiles are for ' + ctx.S + '.</div>' : '';
  let h = curNote + k.tiles([
    k.tile('xwOBA+', k.rate3(xw.v), 'Savant xwOBA ' + k.rate3(sv.v) + (k.isNum(xw.v) && k.isNum(sv.v) ? ' (' + k.signed(1000 * (xw.v - sv.v), 0) + ' pts)' : '') + pctTxt(xw)),
    k.tile('wOBA', k.rate3(wo.v), k.isNum(wo.v) && k.isNum(xw.v) ? (wo.v >= xw.v ? 'above' : 'below') + ' xwOBA+ by ' + k.num(1000 * Math.abs(wo.v - xw.v), 0) + ' pts' : 'actual'),
    k.tile('Bullpen WAR', k.isNum(war.v) ? k.signed(war.v, 1) : '—', 'batting, running, fielding, position' + pctTxt(war)),
    k.tile('Decision value', k.isNum(dv.v) ? k.signed(dv.v, 1) : '—', 'runs from swing/take choices' + pctTxt(dv)),
    k.tile('Bat speed (adj.)', k.isNum(bs.v) ? k.num(bs.v, 1) + ' <span class="kpi-dim">mph</span>' : '—', 'for the pitches, counts and locations faced' + pctTxt(bs)),
    k.tile('PA', k.int(pa.v || (p && p.pa)), k.isNum(v.hr) ? k.int(v.hr) + ' HR · ' + fv('avg', v.avg) + '/' + fv('obp', v.obp) + '/' + fv('slg', v.slg) : '')
  ]);
  h += sliderCard(ctx, ctx.hc, p, 'hit');
  h += '<div class="grid-2"><div class="card"><div class="card-header">Spray chart <span class="card-sub">The last 400 balls in play, coloured by xwOBA+ (filled: hits, open: outs). Field drawn from the home park\'s fences.</span></div>' +
    '<div class="lab-controls gq-controls" id="sp-ctl"></div><div id="pp-spray" class="gq-spray"></div><div class="pg-note gq-note" id="sp-note"></div></div>' +
    '<div class="card"><div class="card-header">Zone profile <span class="card-sub">Results on pitches in each part of the zone, by pitch family.</span></div><div id="pp-zones" class="gq-pad"></div></div></div>';
  h += '<div class="grid-2"><div class="card"><div class="card-header">Swing decisions <span class="card-sub">Decision value per 100 pitches in each cell: red where the choices (swing or take) beat the average choice at that pitch, blue where they cost runs.</span></div><div id="pp-dec" class="gq-pad"></div></div>' +
    '<div class="card"><div class="card-header">Bat speed and swing path <span class="card-sub">Bat tracking adjusted for count, location and pitch speed; the swing path against the pitch\'s plane.</span></div><div id="pp-bat" class="gq-pad"></div></div></div>';
  h += '<div class="card"><div class="card-header">Rolling xwOBA+ against wOBA <span class="card-sub">Over the last 100 plate appearances at each date: the gap is luck, defence and park; the expected line is what the contact deserved.</span></div><div id="pp-roll" style="height:300px"></div></div>';
  h += '<div class="card"><div class="card-header">Splits <span class="card-sub">By pitcher hand, home and road, and month.</span></div><div id="pp-splits"></div></div>';
  body.innerHTML = h;
  fillSliders(ctx, ctx.hc, p);
  const pts = k.sprayPoints(cur.spray);
  const dims = parkDims(ctx);
  const ctl = document.getElementById('sp-ctl');
  const st = { res: '' };
  const RES = [['', 'All'], ['hit', 'Hits'], ['out', 'Outs'], ['home_run', 'Home runs'], ['hard', '95+ mph']];
  ctl.innerHTML = '<label>Show' + k.select('sp-res', RES, '') + '</label>';
  const isHit = e => ['single', 'double', 'triple', 'home_run'].indexOf(e) >= 0;
  const drawSpray = () => {
    const sel = pts.filter(x => !st.res || (st.res === 'hit' ? isHit(x.ev_desc) : st.res === 'out' ? !isHit(x.ev_desc) : st.res === 'hard' ? x.ev >= 95 : x.ev_desc === st.res));
    k.spray('pp-spray', sel, dims, { fmt: '3', label: 'xwOBA+' });
    const xs = sel.map(x => x.v).filter(k.isNum);
    const bats = ctx.career.bats;
    const pull = sel.filter(x => (bats === 'L' ? x.x > 0 : x.x < 0)).length;
    document.getElementById('sp-note').innerHTML = sel.length ? k.int(sel.length) + ' balls in play' + (xs.length ? ', mean xwOBA+ ' + k.rate3(k.mean(xs)) : '') +
      (bats === 'L' || bats === 'R' ? ', ' + k.pct(pull / sel.length, 0) + ' to the pull side' : '') + '.' : '';
  };
  document.getElementById('sp-res').addEventListener('change', e => { st.res = e.target.value; drawSpray(); });
  drawSpray();
  zone5(document.getElementById('pp-zones'), cur.zones, { id: 'hz', keyName: 'Pitches', keyLabel: x => ({ all: 'All pitches', fb: 'Fastballs', br: 'Breaking balls', os: 'Offspeed' }[x] || x), prefer: 'all',
    cols: [['xwoba', 'xwOBA (per PA ending there)', 3, '3', 'div', 0.315], ['swing', 'Swing%', 1, 'pct', 'seq'], ['whiff', 'Whiff%', 2, 'pct', 'seq'], ['n', 'Pitches seen', 0, 'int', 'seq']], share: 0,
    note: 'xwOBA counts plate appearances that ended on a pitch in the cell.', empty: 'Zone grids are not available for this player yet.' });
  zone5(document.getElementById('pp-dec'), cur.decisions, { id: 'hd', cols: [['dv', 'Decision value per 100 pitches', 0, 'signed2', 'div', 0], ['n', 'Pitches', 1, 'int', 'seq']], nIndex: 1,
    note: 'Decision value: the run value of the choice made minus the expected value of the average choice at that pitch, location and count (swing model).', empty: 'The swing-decision map is not available for this player yet.' });
  battrack(document.getElementById('pp-bat'), cur.battrack, v, pc, meta);
  rolling('pp-roll', cur.rolling, ['xwOBA+', 'wOBA'], ['#f97316', '#58a6ff'], '3');
  splitsTable(document.getElementById('pp-splits'), cur.splits, 'batter', meta);
}

/* Splits from the career file: {batter|pitcher: {vL, vR, home, away, months: {YYYY-MM: {...}}}}. */
function splitsTable(host, sp, who, meta) {
  const k = K();
  if (!host) return;
  const s = (sp && (sp[who] || (sp.vL || sp.home ? sp : null))) || null;
  if (!s) { host.innerHTML = k.muted('Splits are not available yet.'); return; }
  const main = {};
  ['vL', 'vR', 'home', 'away'].forEach(x => { if (s[x]) main[x] = s[x]; });
  const LB = who === 'pitcher' ? { vL: 'v LHB', vR: 'v RHB', home: 'Home', away: 'Road' } : { vL: 'v LHP', vR: 'v RHP', home: 'Home', away: 'Road' };
  let h = rowsTable(main, meta, { first: 'Split', keyLabel: x => LB[x] || x, order: ['pa', 'woba', 'k_pct'] });
  const mo = s.months || {};
  const mk = Object.keys(mo).sort();
  if (mk.length) h += '<div class="gq-sub-head">By month</div>' + rowsTable(mk.map(m => Object.assign({ split: m }, mo[m])), meta, { first: 'Month', keyLabel: x => { const d = new Date(x + '-15T12:00:00Z'); return isNaN(d.getTime()) ? x : d.toLocaleString('en-GB', { month: 'long' }); }, order: ['pa', 'woba', 'k_pct'] });
  host.innerHTML = h;
}

function battrack(host, bt, v, pc, meta) {
  const k = K();
  if (!host) return;
  const b = Object.assign({}, bt || {});
  const keys = [['bat_speed_adj', 'Adjusted bat speed', 'mph', '1'], ['bat_speed', 'Raw bat speed', 'mph', '1'], ['fast_swing_pct', 'Fast-swing rate', '', 'pct'], ['swing_length_adj', 'Adjusted swing length', 'ft', '1'],
    ['swing_length', 'Raw swing length', 'ft', '1'], ['attack_angle', 'Attack angle', '°', '1'], ['attack_direction', 'Attack direction', '°', '1'], ['swing_path_tilt', 'Swing-path tilt', '°', '1'],
    ['sq_contact', 'Squared-up (contact)', '', 'pct'], ['sq_swing', 'Squared-up (swing)', '', 'pct'], ['sq_oe', 'Squared-up v expected', '', 'pct'], ['matched', 'Path matched to pitch', '', 'pct'],
    ['abs_mismatch', 'Path mismatch', '°', '1'], ['intercept_y_rel', 'Contact point v league', 'in', '1']];
  const tiles = [];
  keys.forEach(x => {
    const val = k.isNum(b[x[0]]) ? b[x[0]] : v[x[0]];
    if (!k.isNum(val)) return;
    const p = pc[x[0]] !== undefined ? pc[x[0]] : pc[{ swing_path_tilt: 'swing_tilt', matched: 'path_matched_pct', abs_mismatch: 'path_mismatch', intercept_y_rel: 'intercept_rel' }[x[0]]];
    tiles.push(k.tile(x[1], (x[3] === 'pct' && x[0] === 'sq_oe' ? k.signed(100 * val, 1) + ' pp' : k.fmtV(val, x[3])) + (x[2] ? ' <span class="kpi-dim">' + x[2] + '</span>' : ''), k.isNum(p) ? k.ordinal(p) + ' percentile' : ''));
  });
  let h = tiles.length ? '<div class="kpi-grid gq-tiles gq-tiles-3">' + tiles.join('') + '</div>' : '';
  if (k.isNum(b.n)) h += '<div class="pg-note gq-note">' + k.int(b.n) + ' competitive swings (50+ mph). Adjusted figures add the hitter\'s residuals against a league model of the pitch speed, location and count faced, shrunk with 50 swings; squared up means 80% or more of the exit velocity the swing and pitch allowed (1.23 × bat speed + 0.23 × pitch speed); the path is matched when attack angle + VAA is within 5°.</div>';
  host.innerHTML = h || k.muted('Bat tracking is not available for this player (it starts in 2023 and needs competitive swings).');
}

function rolling(id, raw, names, colours, fmt) {
  const k = K();
  const node = document.getElementById(id);
  if (!node) return;
  let rows = [];
  if (Array.isArray(raw)) rows = raw.map(r => (Array.isArray(r) ? r : [r.date || r.d || r.x || r.pa, r.xwoba_plus !== undefined ? r.xwoba_plus : r.a, r.woba !== undefined ? r.woba : r.b, r.xwoba_savant]));
  else if (raw && Array.isArray(raw.rows)) rows = raw.rows;
  if (!rows.length) { node.innerHTML = k.muted('Not enough plate appearances for a rolling line yet.'); return; }
  const tr = [];
  const ncol = Math.max.apply(null, rows.map(r => r.length));
  const nm = names.concat(['Savant xwOBA', 'Series 4']);
  const col = colours.concat(['#bc8cff', '#8b949e']);
  for (let j = 1; j < ncol; j++) {
    if (!rows.some(r => k.isNum(r[j]))) continue;
    tr.push({ type: 'scatter', mode: 'lines', name: nm[j - 1], x: rows.map(r => r[0]), y: rows.map(r => (k.isNum(r[j]) ? r[j] : null)), line: { color: col[j - 1], width: j === 1 ? 2.5 : 1.8, dash: j > 2 ? 'dot' : 'solid' }, connectgaps: true,
      hovertemplate: '%{x}: %{y:' + (fmt === '3' ? '.3f' : '.1f') + '}<extra>' + nm[j - 1] + '</extra>' });
  }
  k.plot(node, tr, k.layout(Object.assign({ margin: { l: 50, r: 12, t: 26, b: 36 }, yaxis: { title: 'Rolling wOBA (100 PA)', tickformat: fmt === '3' ? '.3f' : '' }, xaxis: { title: 'Date' } }, k.legendTop())));
}

// ── pitcher ────────────────────────────────────────────────────────────────

function drawPitcher(body, ctx) {
  const k = K();
  const p = ctx.pp, cur = ctx.cur, pit = cur.pitching || {};
  const v = Object.assign({}, pit.values || {}, (p && p.values) || {});
  const pc = (p && p.pct) || pit.pct || {};
  const meta = k.metaOf((ctx.pc || {}).metrics);
  const g = cands => { const key = k.pick(v, cands); return key ? { key: key, v: v[key], p: pc[key] } : { v: null }; };
  const pctTxt = x => (k.isNum(x.p) ? k.ordinal(x.p) + ' percentile' : '');
  const pp = g(['pitching_plus']), st = g(['stuff_plus']), lo = g(['location_plus']), war = g(['war']), warx = g(['war_x']);
  const ra9 = g(['ra9', 'era']), fip = g(['fip', 'xfip']), kbb = g(['k_bb_pct']), xw = g(['xwoba_plus']), bf = g(['bf']), ip = g(['ip']);
  // Horizontal break and release side stay arm-side positive for both hands, as the build writes them (and the game pages draw them).
  const side = 1;
  const curNote = k.isNum(cur.season) && Number(cur.season) !== ctx.S ? '<div class="warn-banner gq-warn">The charts below show ' + cur.season + ' (' + k.LN(cur.level || ctx.L) + '), the latest season on file; the percentiles are for ' + ctx.S + '.</div>' : '';
  let h = curNote + k.tiles([
    k.tile('Pitching+', k.fmtV(pp.v, 'plus'), 'stuff, location and sequence · 100 = average' + (pctTxt(pp) ? ' · ' + pctTxt(pp) : '')),
    k.tile('Stuff+', k.fmtV(st.v, 'plus'), pctTxt(st) || 'the pitch\'s physics only'),
    k.tile('Location+', k.fmtV(lo.v, 'plus'), pctTxt(lo) || 'location given count and pitch'),
    k.tile('Bullpen WAR', k.isNum(war.v) ? k.signed(war.v, 1) : '—', k.isNum(warx.v) ? 'RA9-based · from xwOBA+ against ' + k.signed(warx.v, 1) : 'RA9-based'),
    k.tile('RA9 · FIP', k.fmtV(ra9.v, '2') + ' <span class="kpi-dim">· ' + k.fmtV(fip.v, '2') + '</span>', k.isNum(ip.v) ? k.num(ip.v, 1) + ' IP' + (k.isNum(bf.v) ? ' · ' + k.int(bf.v) + ' BF' : '') : ''),
    k.tile('K−BB%', k.fmtV(kbb.v, 'pct'), (k.isNum(xw.v) ? 'xwOBA+ against ' + k.rate3(xw.v) : '') + (pctTxt(kbb) ? ' · ' + pctTxt(kbb) : ''))
  ]);
  h += sliderCard(ctx, ctx.pc, p, 'pit');
  h += '<div class="card"><div class="card-header">Arsenal <span class="card-sub">Per pitch type, ' + (k.isNum(cur.season) ? cur.season : ctx.S) + ' (10+ thrown). Movement in inches with gravity removed; HB is towards the arm side. Stuff+, Location+ and Pitching+: 100 = league average; pills on Stuff+ and Whiff% are percentiles among pitches of the same type (100+ thrown).</span></div><div id="pp-ars"></div></div>';
  h += '<div class="grid-2"><div class="card"><div class="card-header">Movement <span class="card-sub">Induced vertical break against horizontal break towards the arm side (glove side negative). Dots are a sample of the pitches, discs the averages (size = usage), dotted rings the league average for each type; the dashed line is the arm angle.</span></div><div id="pp-mov" class="gq-mov"></div></div>' +
    '<div class="card"><div class="card-header">Release point and extension <span class="card-sub">Where each pitch type leaves the hand (feet; side measured towards the arm side) and how consistently.</span></div><div id="pp-rel" style="height:300px"></div><div id="pp-rel-t"></div></div></div>';
  h += '<div class="grid-2"><div class="card"><div class="card-header">Tunneling <span class="card-sub">Back-to-back pairs: distance apart at the batter\'s decision point (167 ms before the plate) against separation at the plate. Index 100 = an average pair; above it, the pair stays together longer than pairs that split as much usually do.</span></div><div id="pp-tun"></div></div>' +
    '<div class="card"><div class="card-header">Usage by count and batter hand <span class="card-sub">Share of each pitch type in each situation.</span></div><div id="pp-use" style="height:300px"></div></div></div>';
  h += '<div class="card"><div class="card-header">Velocity, spin and fatigue <span class="card-sub">The primary fastball game by game against the season baseline, the within-game decline, and the workload flag.</span></div><div id="pp-fat"></div></div>';
  h += '<div class="grid-2"><div class="card"><div class="card-header">Locations <span class="card-sub">Where each pitch type goes, and how often it is missed when swung at.</span></div><div id="pp-zones" class="gq-pad"></div></div>' +
    '<div class="card"><div class="card-header">Times through the order <span class="card-sub">Expected wOBA allowed each time through the lineup (shrunk with 100 PA to the league\'s).</span></div><div id="pp-tto"></div></div></div>';
  body.innerHTML = h;
  fillSliders(ctx, ctx.pc, p);
  const arsRaw = cur.arsenal || ((ctx.pc || {}).arsenal || {})[ctx.pid];
  const ars = arsenalOf(arsRaw);
  document.getElementById('pp-ars').innerHTML = ars.length ? arsenalTable(ars, meta) : k.muted('The arsenal is not available for this pitcher yet.');
  const rel = cur.release || {};
  const arm = [rel.arm_angle, v.arm_angle, k.mean(ars.map(r => r.arm_angle))].find(k.isNum);
  k.movement('pp-mov', movementGroups(cur.movement, ars, side), { league: leagueRef((ctx.pc || {}).league_types, ars, side), armAngle: arm, armSide: 1, xTitle: 'Horizontal break (in, arm side +)' });
  releasePanel(rel, ars, side);
  tunnels(cur.tunnels);
  usage(null, ars);
  fatigue(cur.fatigue || {}, ctx);
  zone5(document.getElementById('pp-zones'), cur.pitch_zones, { id: 'pz', keyName: 'Pitch', keyLabel: x => k.pitchName(x) + ' (' + x + ')', prefer: (ars[0] || {}).pt,
    cols: [['whiff', 'Whiff%', 1, 'pct', 'seq'], ['n', 'Pitches', 0, 'int', 'seq']], share: 0, empty: 'Location grids are not available for this pitcher yet (50+ of a type).' });
  const f = cur.fatigue || {};
  const tto = {};
  [1, 2, 3].forEach(i => { const x = [f['xwoba_tto' + i], v['xwoba_tto' + i]].find(k.isNum); if (k.isNum(x)) tto[i] = { pa: f['pa_tto' + i], xwoba: x }; });
  const pen = [f.tto_penalty, v.tto_penalty].find(k.isNum);
  document.getElementById('pp-tto').innerHTML = Object.keys(tto).length ? rowsTable(tto, { xwoba: { label: 'xwOBA allowed', fmt: '3' }, pa: { label: 'PA', fmt: 'int' } }, { first: 'Time through', keyLabel: x => k.ordinal(Number(x)) + (x === '3' ? '+' : '') + ' time', order: ['pa', 'xwoba'] }) +
    '<div class="pg-note gq-note">' + (k.isNum(pen) ? 'Penalty (third time minus first): ' + k.signed(1000 * pen, 0) + ' points of xwOBA. ' : '') + 'The game model applies the league\'s times-through-the-order multipliers to every starter.</div>'
    : k.muted('Times-through-the-order splits are not available yet.');
}

/* Release: the per-type means from the arsenal (rel_side arm-side ft, rel_z ft, ext, spread_in) and the pitcher's
 * consistency (release dict: sd_side_in, sd_height_in, sd_ext_in, sd_arm_angle, spread_in, type_spread_in). */
function releasePanel(rel, ars, side) {
  const k = K();
  const node = document.getElementById('pp-rel'), tab = document.getElementById('pp-rel-t');
  if (!node) return;
  const rows = ars.map(r => ({ pt: r.pt, x: k.isNum(r.rel_side) ? side * r.rel_side : null, z: r.rel_z, ext: r.ext, sp: r.spread_in, arm: r.arm_angle, n: r.n })).filter(r => k.isNum(r.x) && k.isNum(r.z));
  if (!rows.length) { node.innerHTML = k.muted('Release data is not available yet.'); node.style.height = 'auto'; return; }
  const shapes = [], tr = [];
  rows.forEach(r => {
    const rad = k.isNum(r.sp) ? r.sp / 12 : 0;
    if (rad) shapes.push({ type: 'circle', x0: r.x - rad, x1: r.x + rad, y0: r.z - rad, y1: r.z + rad, line: { color: k.pitchColour(r.pt), width: 1 }, fillcolor: k.alpha(k.pitchColour(r.pt), 0.12) });
    tr.push({ type: 'scatter', mode: 'markers+text', x: [r.x], y: [r.z], text: [r.pt], textposition: 'top center', textfont: { size: 10, color: k.C.text }, marker: { size: 11, color: k.pitchColour(r.pt), line: { color: '#0d1117', width: 1 } },
      hovertemplate: k.esc(k.pitchName(r.pt)) + '<br>side %{x:.2f} ft · height %{y:.2f} ft' + (k.isNum(r.ext) ? '<br>extension ' + k.num(r.ext, 2) + ' ft' : '') + (k.isNum(r.sp) ? '<br>spread ' + k.num(r.sp, 1) + ' in' : '') + '<extra></extra>', showlegend: false });
  });
  const xs = rows.map(r => r.x), zs = rows.map(r => r.z);
  const cx = k.mean(xs), cz = k.mean(zs);
  k.plot(node, tr, k.layout({ margin: { l: 44, r: 10, t: 6, b: 36 }, shapes: shapes, xaxis: { title: 'Release side (ft, arm side +)', range: [cx - 0.8, cx + 0.8], zeroline: false }, yaxis: { title: 'Release height (ft)', range: [cz - 0.6, cz + 0.6] } }));
  const r0 = rel || {};
  const tiles = [];
  [['release_height', 'Release height', 'ft', '2'], ['extension', 'Extension', 'ft', '2'], ['arm_angle', 'Arm angle', '°', '1'], ['spread_in', 'Release spread', 'in', '1'], ['type_spread_in', 'Gap between types', 'in', '1'], ['sd_ext_in', 'Extension SD', 'in', '1']].forEach(x => {
    if (k.isNum(r0[x[0]])) tiles.push(k.tile(x[1], k.fmtV(r0[x[0]], x[3]) + ' <span class="kpi-dim">' + x[2] + '</span>', ''));
  });
  if (tab) tab.innerHTML = (tiles.length ? '<div class="kpi-grid gq-tiles gq-tiles-3">' + tiles.join('') + '</div>' : '') +
    '<div class="pg-note gq-note">Discs are each type\'s mean release point; rings are its release spread (√(SD side² + SD height²)). A large gap between types\' release points can tip pitches.</div>';
}

function tunnels(list) {
  const k = K();
  const node = document.getElementById('pp-tun');
  if (!node) return;
  const rows = (Array.isArray(list) ? list : (list && (list.pairs || list.rows)) || []).map(r => (Array.isArray(r) ? { a: r[0], b: r[1], dp: r[2], plate: r[3], n: r[4] } : r));
  if (!rows.length) { node.innerHTML = k.muted('Tunneling pairs are not available yet.'); return; }
  const gv = (r, c) => k.val(r, c);
  rows.sort((x, y) => (gv(y, ['n']) || 0) - (gv(x, ['n']) || 0));
  node.innerHTML = k.table([{ label: 'Pair' }, { label: 'n', align: 'right' }, { label: 'At decision', align: 'right', title: 'Distance between the two pitches 167 ms before the plate (inches)' }, { label: 'At plate', align: 'right', title: 'Separation at the plate (inches)' },
    { label: 'Ratio', align: 'right', title: 'Plate separation / decision-point distance' }, { label: 'Tunnel', align: 'right', title: 'Inches closer at the decision point than the league curve expects for this plate separation' }, { label: 'Index', align: 'right', title: '100 = average pair' }, { label: 'Whiff%', align: 'right', title: 'Whiffs per swing on the second pitch' }],
  rows.map(r => {
    const pr = String(r.pair || '').split(/[>\-]/);
    const a = r.a || r.first || pr[0], b = r.b || r.second || pr[1];
    const dp = gv(r, ['dp', 'dist_decision', 'decision_dist']), pl = gv(r, ['plate', 'dist_plate', 'plate_dist']);
    const ratio = k.isNum(gv(r, ['ratio'])) ? gv(r, ['ratio']) : (k.isNum(dp) && dp ? pl / Math.max(dp, 0.5) : null);
    const idx = gv(r, ['index']);
    return [{ v: a + b, html: k.pitchChip(a) + ' → ' + k.pitchChip(b) }, { v: gv(r, ['n']), html: k.int(gv(r, ['n'])) },
      { v: dp, html: k.num(dp, 1) }, { v: pl, html: k.num(pl, 1) }, { v: ratio, html: k.num(ratio, 2) }, { v: gv(r, ['tunnel']), html: k.isNum(gv(r, ['tunnel'])) ? k.signed(gv(r, ['tunnel']), 2) : '—' },
      { v: idx, html: k.isNum(idx) ? '<strong>' + Math.round(idx) + '</strong>' : '—' }, { v: gv(r, ['whiff', 'whiff_pct']), html: k.fmtV(gv(r, ['whiff', 'whiff_pct']), 'pct') }];
  }), { compact: true });
  k.sortable(node);
}

/* Usage by situation from the arsenal: overall, v LHB, v RHB, ahead, behind, two strikes. */
function usage(u, ars) {
  const k = K();
  const node = document.getElementById('pp-use');
  if (!node) return;
  const SIT = [['usage', 'All'], ['usage_vl', 'v LHB'], ['usage_vr', 'v RHB'], ['usage_ahead', 'Ahead'], ['usage_behind', 'Behind'], ['usage_two', 'Two strikes']];
  const sits = SIT.filter(x => ars.some(r => k.isNum(r[x[0]])));
  if (!ars.length || sits.length < 2) { node.innerHTML = k.muted('Usage splits are not available yet.'); node.style.height = 'auto'; return; }
  const lbl = sits.map(x => x[1]);
  k.plot(node, ars.map(r => ({ type: 'bar', orientation: 'h', name: r.pt, y: lbl, x: sits.map(x => r[x[0]] || 0), marker: { color: k.pitchColour(r.pt) },
    hovertemplate: k.esc(k.pitchName(r.pt)) + ' %{y}: %{x:.1%}<extra></extra>' })), k.layout(Object.assign({ barmode: 'stack', margin: { l: 80, r: 10, t: 28, b: 30 }, xaxis: { title: 'Share of pitches', tickformat: '.0%', range: [0, 1] }, yaxis: { autorange: 'reversed', type: 'category' } }, k.legendTop())));
}

/* Fatigue (models/fatigue.py per pitcher): baselines, last-three-game changes, within-game slopes per 100 pitches,
 * the 30-day trend, the flag, and series [[date, velo, spin]]; plus the rolling pitch-model scores. */
function fatigue(f, ctx) {
  const k = K();
  const host = document.getElementById('pp-fat');
  if (!host) return;
  const games = (f.series || f.games || []).map(r => (Array.isArray(r) ? { date: r[0], velo: r[1], spin: r[2] } : { date: r.date, velo: r.velo, spin: r.spin }));
  let h = '';
  const tiles = [];
  [['velo_base', 'Fastball velo (season)', 'mph', '1'], ['velo_last3', 'Last 3 games v season', 'mph', 'signed2'], ['spin_last3', 'Spin, last 3 v season', 'rpm', 'signed'], ['velo_per100', 'Velo per 100 pitches in a game', 'mph', 'signed2'],
    ['velo_trend_30d', 'Velo trend per 30 days', 'mph', 'signed2'], ['rel_z_last3_in', 'Release height, last 3', 'in', 'signed']].forEach(x => {
    if (k.isNum(f[x[0]])) tiles.push(k.tile(x[1], k.fmtV(f[x[0]], x[3]) + ' <span class="kpi-dim">' + x[2] + '</span>', ''));
  });
  if (tiles.length) h += '<div class="kpi-grid gq-tiles">' + tiles.join('') + '</div>';
  if (f.flag === true || f.flag === 1) h += '<div class="gq-flags"><span class="chip warn">Workload flag: the last three games\' fastball is down 1+ mph or 75+ rpm on the season</span></div>';
  else if (f.flag === false || f.flag === 0) h += '<div class="gq-flags"><span class="chip">No workload flag</span></div>';
  h += '<div class="grid-2"><div id="fat-g" style="height:280px"></div><div id="fat-w" style="height:280px"></div></div>' +
    '<div class="pg-note gq-note">Descriptive, not medical. Within-game slopes are shrunk to the league\'s by empirical Bayes; the flag needs five or more games. Right: rolling Stuff+, Location+ and Pitching+ over 500-pitch windows.</div>';
  host.innerHTML = h;
  if (games.length) {
    const tr = [{ type: 'scatter', mode: 'lines+markers', name: 'Velo (mph)', x: games.map(r => r.date), y: games.map(r => r.velo), line: { color: '#f85149', width: 2 }, marker: { size: 5 } }];
    if (games.some(r => k.isNum(r.spin))) tr.push({ type: 'scatter', mode: 'lines', name: 'Spin (rpm)', x: games.map(r => r.date), y: games.map(r => r.spin), yaxis: 'y2', line: { color: '#58a6ff', width: 1.5, dash: 'dot' } });
    const base = k.isNum(f.velo_base) ? f.velo_base : null;
    k.plot('fat-g', tr, k.layout(Object.assign({ margin: { l: 44, r: 50, t: 28, b: 32 }, xaxis: { title: 'Date' }, yaxis: { title: 'Fastball velocity (mph)' }, yaxis2: { title: 'Spin rate (rpm)', overlaying: 'y', side: 'right', showgrid: false },
      shapes: base ? [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: base, y1: base, line: { color: '#6e7681', dash: 'dash', width: 1 } }] : [] }, k.legendTop())));
  } else document.getElementById('fat-g').innerHTML = k.muted('No game-by-game fastball velocity yet.');
  const pr = (ctx.cur.pitching_rolling || []).map(r => (Array.isArray(r) ? r : [r.date, r.n, r.stuff, r.location, r.pitching, r.roll]));
  if (pr.length) {
    const ser = [[2, 'Stuff+', '#f97316'], [3, 'Location+', '#58a6ff'], [4, 'Pitching+', '#3fb950']].filter(x => pr.some(r => k.isNum(r[x[0]])));
    k.plot('fat-w', ser.map(x => ({ type: 'scatter', mode: 'lines', name: x[1], x: pr.map(r => r[0]), y: pr.map(r => r[x[0]]), line: { color: x[2], width: 2 } })),
      k.layout(Object.assign({ margin: { l: 40, r: 10, t: 28, b: 32 }, xaxis: { title: 'Date' }, yaxis: { title: 'Score (100 = average)' },
        shapes: [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 100, y1: 100, line: { color: '#6e7681', dash: 'dot', width: 1 } }] }, k.legendTop())));
  } else document.getElementById('fat-w').innerHTML = k.muted('No rolling pitch-model series yet.');
}

// ── shared: projections, career, similar ───────────────────────────────────

function drawShared(body, ctx, side) {
  const k = K();
  const c = ctx.career, cur = ctx.cur;
  const meta = k.metaOf(((side === 'pit' ? ctx.pc : ctx.hc) || {}).metrics);
  const wrap = document.createElement('div');
  let h = '<div class="card"><div class="card-header">Projection <span class="card-sub">Bullpen projections: each component regressed at its own stabilisation rate over three weighted seasons, with aging; ranges are the 10th to 90th percentiles.</span></div><div id="pp-proj"></div></div>';
  const rows = seasonsOf(c.seasons, side);
  h += '<div class="card"><div class="card-header">Career <span class="card-sub">Every season on file, MLB and Triple-A. xwOBA+ and the pitch models start in 2015 (Triple-A in 2023).</span></div>' + (rows.length ? careerTable(rows, side === 'pit' ? PIT_COLS : HIT_COLS, ctx.L, meta) : k.muted('No season lines on file yet.')) + '</div>';
  const hist = c.history || null;
  let histRows = [];
  if (hist && typeof hist === 'object' && !Array.isArray(hist)) {
    const kind = side === 'pit' ? 'pitching' : 'batting';
    const cols = (hist.cols || {})[kind] || [];
    histRows = (hist[kind] || []).map(r => { if (!Array.isArray(r)) return flatSeason(r); const o = {}; cols.forEach((cn, i) => { o[cn] = r[i]; }); return o; });
    histRows.forEach(r => { if (k.isNum(r.outs) && !k.isNum(r.ip)) r.ip = r.outs / 3; if (k.isNum(r.k) && !k.isNum(r.so)) r.so = r.k; });
  } else if (Array.isArray(hist)) histRows = seasonsOf(hist, side);
  if (histRows.length) {
    const HC = side === 'pit' ? ['season', 'games', 'ip', 'bf', 'runs', 'so', 'bb', 'hr', 'ra9', 'ra9_minus', 'war'] : ['season', 'pa', 'ab', 'h', 'b2', 'b3', 'hr', 'bb', 'so', 'woba', 'wrc_plus', 'wraa', 'war'];
    h += '<div class="card"><div class="card-header">Retrosheet era <span class="card-sub">Seasons before 2015 from Retrosheet play-by-play, valued by each season\'s own linear weights; wRC+ and RA9− are against that season\'s league (100 = average), not park-adjusted. WAR here is the historical version: fielding is a range-factor proxy from Lahman that overrates some dead-ball-era fielders, and seasons before 1908 have no play-by-play.</span></div>' +
      careerTable(histRows, HC, ctx.L, {}) + '<div class="gq-retro">' + k.esc(((c.meta || {}).retrosheet_notice) || BP.RETRO_NOTICE || RETRO_NOTICE) + '</div></div>';
  }
  h += '<div class="card"><div class="card-header">Similar players <span class="card-sub">Nearest player-seasons on the standardised skill profile (' + (side === 'pit' ? 'strikeouts, walks, ground balls, fastball velocity and ride, whiffs, chases, called strikes plus whiffs, pitch mix, hard contact' : 'strikeouts, walks, power, Savant xwOBA, barrels, chases, whiffs, exit velocity, pulled air balls, ground balls, sprint speed') + '); a shorter distance is more alike.</span></div><div id="pp-sim"></div></div>';
  wrap.innerHTML = h;
  body.appendChild(wrap);
  projections(document.getElementById('pp-proj'), cur.projection || c.projection, side, meta);
  similar(document.getElementById('pp-sim'), c.similar, ctx, side);
}

const COMP = { K: ['Strikeouts per PA', 'pct'], BB: ['Walks per PA', 'pct'], HBP: ['Hit by pitch per PA', 'pct'], GB: ['Ground balls per ball in play', 'pct'], XWCON: ['xwOBA on contact', '3'],
  HRBIP: ['Home runs per ball in play', 'pct'], HITS: ['Hits per ball in play (non-HR)', 'pct'], XBH: ['Extra-base hits per ball in play', 'pct'], TRIP: ['Triples per extra-base hit', 'pct'], BATSPD: ['Bat speed (mph)', '1'] };
const EVENTS9 = ['K', 'BB', 'HBP', '1B', '2B', '3B', 'HR', 'GO', 'AO'];
function projections(host, pr, side, meta) {
  const k = K();
  if (!host) return;
  if (!pr || typeof pr !== 'object') { host.innerHTML = k.muted('No projection yet.'); return; }
  const pit = side === 'pit' || /pitch/.test(String(pr.kind || ''));
  let h = '';
  const tiles = [];
  if (k.isNum(pr.wOBA)) tiles.push(k.tile(pit ? 'wOBA allowed' : 'wOBA', k.rate3(pr.wOBA), (pr.season ? pr.season + ' projection' : 'projection')));
  if (k.isNum(pr.ISO)) tiles.push(k.tile(pit ? 'ISO allowed' : 'ISO', k.rate3(pr.ISO), ''));
  if (k.isNum(pr.BABIP)) tiles.push(k.tile(pit ? 'BABIP allowed' : 'BABIP', k.rate3(pr.BABIP), ''));
  if (k.isNum(pr.n)) tiles.push(k.tile('Weighted sample', k.int(pr.n), (pit ? 'batters faced' : 'plate appearances') + ', three seasons weighted'));
  if (k.isNum(pr.age)) tiles.push(k.tile('Age', k.num(pr.age, 1), 'on 1 July of the projected season'));
  if (tiles.length) h += '<div class="kpi-grid gq-tiles">' + tiles.join('') + '</div>';
  const comps = pr.components || {};
  const ck = Object.keys(comps).filter(c => comps[c] && k.isNum(comps[c].proj));
  if (ck.length) {
    h += k.table([{ label: 'Component' }, { label: 'Projection', align: 'right' }, { label: '10th–90th', align: 'right' }, { label: '', sortable: false }, { label: 'Sample', align: 'right', title: 'The weighted events behind it' }],
      ck.map(c => { const x = comps[c], f = (COMP[c] || [c, '3'])[1];
        const span = k.isNum(x.p10) && k.isNum(x.p90) && x.p90 > x.p10;
        const bar = span ? '<span class="gq-range"><span style="left:0;width:100%"></span><i style="left:' + Math.max(0, Math.min(100, 100 * (x.proj - x.p10) / (x.p90 - x.p10))).toFixed(0) + '%"></i></span>' : '';
        return [{ v: c, html: '<strong>' + k.esc((COMP[c] || [c])[0]) + '</strong>' }, { v: x.proj, html: k.fmtV(x.proj, f) }, { v: x.p10, html: span ? k.fmtV(x.p10, f) + ' – ' + k.fmtV(x.p90, f) : '—' }, { v: '', html: bar }, { v: x.n, html: k.int(x.n) }]; }), { compact: true });
  }
  const R = pr.rates || {};
  if (Array.isArray(R.L) && Array.isArray(R.R)) {
    h += '<div class="gq-sub-head">Plate-appearance outcomes by ' + (pit ? 'batter' : 'pitcher') + ' hand (what the game model draws from)</div>' +
      k.table([{ label: 'Hand' }].concat(EVENTS9.map(e => ({ label: e, align: 'right' }))), [['L', pit ? 'v LHB' : 'v LHP'], ['R', pit ? 'v RHB' : 'v RHP'], ['all', 'All']].filter(x => Array.isArray(R[x[0]]))
        .map(x => [{ v: x[1], html: '<strong>' + x[1] + '</strong>' }].concat(R[x[0]].map(v => ({ v: v, html: k.fmtV(v, 'pct') })))), { compact: true });
  }
  if (!h) {
    // A generic {metric: {p10, p50, p90}} projection.
    const keys = Object.keys(pr).filter(x => pr[x] && typeof pr[x] === 'object' && [pr[x].p50, pr[x].mean, pr[x].proj].some(k.isNum));
    h = keys.length ? k.table([{ label: 'Metric' }, { label: 'Projection', align: 'right' }, { label: 'Range', align: 'right' }], keys.map(x => { const v = pr[x], m = [v.p50, v.proj, v.mean].find(k.isNum); return [{ v: x, html: k.esc(label(x)) }, { v: m, html: fv(x, m, meta) }, { v: v.p10, html: k.isNum(v.p10) ? fv(x, v.p10, meta) + ' – ' + fv(x, v.p90, meta) : '—' }]; }), { compact: true }) : '';
  }
  host.innerHTML = h || k.muted('No projection yet.');
}

function similar(host, list, ctx, side) {
  const k = K();
  if (!host) return;
  const rows = (list || []).map(r => (Array.isArray(r) ? { pid: String(r[0]), d: r[1], season: r[2] } : { pid: String(r.pid || r.id), d: r.distance, s: [r.sim, r.score, r.similarity].find(k.isNum), season: r.season, name: r.name }));
  if (!rows.length) { host.innerHTML = k.muted('No similar players computed yet (MLB players with 200+ PA or BF).'); return; }
  rows.forEach(r => { if (r.name) k.learn(r.pid, { name: r.name }); });
  const ds = rows.map(r => r.d).filter(k.isNum), dmax = ds.length ? Math.max.apply(null, ds) * 1.25 : 1;
  host.innerHTML = '<div class="gq-sim">' + rows.slice(0, 10).map(r => {
    const w = k.isNum(r.d) ? 100 * (1 - r.d / dmax) : (k.isNum(r.s) ? (r.s <= 1 ? 100 * r.s : r.s) : 0);
    const href = side === 'pit' ? k.pitcherHref(ctx.L, r.pid, r.season) : k.hitterHref(ctx.L, r.pid, r.season);
    return '<div class="gq-sim-row"><span><a href="' + href + '">' + k.esc(r.name || k.name(r.pid)) + '</a>' + (r.season ? ' <span class="muted-inline">' + k.esc(r.season) + '</span>' : '') + '</span>' +
      '<span class="gq-sim-bar"><span style="width:' + Math.max(4, Math.min(100, w)).toFixed(0) + '%"></span></span><span class="gq-sim-v" title="Distance in standard deviations (lower is closer)">' + (k.isNum(r.d) ? k.num(r.d, 2) : k.isNum(r.s) ? k.num(r.s, 2) : '') + '</span>' +
      '<a class="gq-sim-cmp" href="' + k.compareHref(ctx.pid, r.pid) + '">compare</a></div>';
  }).join('') + '</div>';
}

// ── routes ─────────────────────────────────────────────────────────────────

/* Shared with the umpire, park, team and compare pages. */
(function (G) { G.gridExplorer = gridExplorer; G.rowsTable = rowsTable; G.label = label; G.fv = fv; G.guessFmt = guessFmt; G.rolling = rolling; })(BP.gk = BP.gk || {});

function renderHitter(el, params, state) { return render(el, params, state, 'hit'); }
function renderPitcher(el, params, state) { return render(el, params, state, 'pit'); }
function renderPlayer(el, params, state) { return render(el, params, state, null); }
if (typeof BP.route === 'function') {
  [['hitter', renderHitter], ['#/<L>/hitter/<pid>', renderHitter], ['pitcher', renderPitcher], ['#/<L>/pitcher/<pid>', renderPitcher], ['player', renderPlayer], ['#/player/<pid>', renderPlayer]]
    .forEach(r => { try { BP.route(r[0], r[1]); } catch (e) { /* bound */ } });
}
})(window.BP || (window.BP = {}));
