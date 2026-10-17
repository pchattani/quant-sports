/* The Quant Bullpen — the lab (#/<L>/lab): any two metrics for hitters or pitchers.
 *
 * The Footballer/Hardwood/Ace lab for baseball: scatter any two catalogue metrics for one season
 * window, with presets for the questions the models were built to answer (stuff against results,
 * bat speed against xwOBA+, decision value against chase rate, VAA against whiff rate, xwOBA+
 * against Savant's xwOBA, framing against pop time), colour by team, position or any metric,
 * medians as quadrants, the corners labelled, a search highlight and the group ranked below.
 * Rates can be shrunk towards the median by each metric's own stabilisation point:
 * shrunk = (n · x + k · median) / (n + k), with k = n₀.₇ · 3/7 (the sample at which split-half
 * reliability reaches 0.7 is n₀.₇ = k · 7/3 under r(n) = n / (n + k)).
 *
 * Address: ?kind=hitter|pitcher&x=<key>&y=<key>.
 * NPB (since 15 October 2026): data/npb/<S>/lab.json in the same shape with a third kind, "team" (clubs), and
 * "n_label" (PA / BF / G); registered with BP.routeNpb.
 * Data: data/<L>/<S>/lab.json, column-oriented {"fields", "metrics", "rows", "kinds"}; a "kind" field
 * (hitter|pitcher) and a "season"/"window" field select rows; "windows": {label: {...}} is also read.
 * Falls back to the hitters and pitchers catalogues. Uses BP.gk. */
(function (BP) {
'use strict';

const K = () => BP.gk;
const PRESETS = [
  ['pitcher', ['stuff_plus'], ['rv100', 'ra9'], 'Stuff+ against run value per 100 pitches: does the physical pitch predict results?'],
  ['hitter', ['bat_speed_adj', /bat_speed_adj/, 'bat_speed', /bat_speed/], ['xwoba_plus', /xwoba_?plus/], 'Bat speed against xwOBA+: does swinging harder pay?'],
  ['hitter', ['chase_pct'], ['dv', 'decision_value'], 'Decision value against chase rate: is chasing the whole story?'],
  ['pitcher', ['fb_vaa', /vaa/], ['whiff_pct', /whiff/], 'Fastball VAA against whiff rate: flat fastballs and swings and misses'],
  ['hitter', ['xwoba_savant', /savant/], ['xwoba_plus', /xwoba_?plus/], 'xwOBA+ against Savant xwOBA: where spray, park and speed change the answer'],
  ['hitter', ['pop_time', /pop/, 'arm'], ['framing_runs', /framing/], 'Framing runs against pop time or arm (catchers)'],
  ['pitcher', ['stuff_plus', /stuff/], ['location_plus', /location/], 'Stuff+ against Location+: two ways to get outs'],
  ['hitter', ['woba', /^woba$/], ['xwoba_plus', /xwoba_?plus/], 'wOBA against xwOBA+: who has been lucky?'],
  ['pitcher', ['k_pct', /^k_?pct/], ['bb_pct', /^bb_?pct/], 'Strikeouts against walks'],
  ['hitter', ['barrel_pct', /barrel/], ['k_pct', /^k_?pct/], 'Power against contact']
];
const NO_SHRINK = /^(pa|bf|n|g|gs|age|season|ip|war.*|.*_runs|runs.*|decision_value|dv|dv_zone|dv_chase|rv|re24|wpa.*|bsr|wsb|oaa.*|rar|pos_runs|repl_runs)$|plus$|_plus|^proj_|^pre_/;
let LAB = null, LABK = '', LAB_PRESETS = [], N_LABEL = {}, LAB_META = {};
/* NPB: where the play-by-play metrics come from, and how the expected stats were fitted and checked (npb/<S>/lab.json). */
function npbNote(keys) {
  const k = K();
  if (LAB_META.level !== 'npb') return '';
  const pb = LAB_META.pbp || {}, cv = pb.coverage || {};
  let h = '<br><strong>NPB play-by-play</strong>: ' + (pb.available ? k.int(cv.games_with_pbp) + ' of ' + k.int(cv.games_final) + ' regular-season games this season' +
    (k.isNum(cv.games_with_pitch_counts) ? ' (' + k.int(cv.games_with_pitch_counts) + ' with pitch counts)' : '') : 'not available for this season (it starts in 2016); the stat pages\' metrics only') + '.';
  const ex = LAB_META.expected;
  if (ex && keys.some(x => /^x|woba_minus_x/.test(x))) {
    h += ' <strong>Expected stats</strong>: ' + (ex.out_of_sample ? 'fitted on earlier seasons only (out of sample)' : 'fitted on seasons that include this one or later (in sample until enough earlier seasons exist)') + '.';
    ['bat', 'pit'].forEach(kd => {
      const v = (ex.validation || {})[kd];
      if (!v) return;
      h += ' ' + (kd === 'bat' ? 'Hitters' : 'Pitchers') + ': next season\'s BABIP correlates ' + k.num(v.corr_next.xbabip, 2) + ' with xBABIP and ' + k.num(v.corr_next.babip, 2) + ' with BABIP itself (' + k.int(v.n) + ' player-seasons).';
    });
  }
  return h;
}
/* the sample's unit by kind (NPB's lab.json carries n_label; clubs count games) */
function nU(kind) { const kd = kind || S0.kind; return N_LABEL[kd] || (kd === 'pitcher' ? 'BF' : kd === 'team' ? 'G' : 'PA'); }
function nLong(kind) { const u = nU(kind); return u === 'BF' ? 'Batters faced' : u === 'G' ? 'Games' : 'Plate appearances'; }
function kindNoun(kind) { const kd = kind || S0.kind; return kd === 'pitcher' ? 'pitchers' : kd === 'team' ? 'clubs' : 'hitters'; }
const S0 = { kind: 'hitter', win: null, min: null, shrink: true, preset: 0, x: '', y: '', color: 'team', q: '' };
const MU = {};

/* The payload as {kinds: {hitter: {idx, meta, metrics, rows}, pitcher: ...}, windows: [...]}. */
function prep(raw, hc, pc) {
  const k = K();
  LAB_META = {};
  const kinds = {};
  const fromCols = (d, kindDefault) => {
    const idx = {};
    (d.fields || []).forEach((f, i) => { idx[f] = i; });
    const al = (want, list) => { if (idx[want] === undefined) for (let i = 0; i < list.length; i++) if (idx[list[i]] !== undefined) { idx[want] = idx[list[i]]; break; } };
    al('id', ['pid', 'player', 'player_id']); al('win', ['season', 'window', 'year']); al('kind', ['role_kind', 'type']);
    const meta = k.metaOf(d.metrics || []);
    (d.rows || []).forEach(r => {
      const kd = idx.kind !== undefined ? String(r[idx.kind] || kindDefault || 'hitter') : (kindDefault || 'hitter');
      const kk = /pit/.test(kd) ? 'pitcher' : /catch/.test(kd) ? 'hitter' : kd;
      const g = kinds[kk] || (kinds[kk] = { idx: idx, meta: meta, rows: [] });
      g.rows.push(r);
    });
    Object.keys(kinds).forEach(kk => { const g = kinds[kk]; g.metrics = (d.metrics || []).filter(m => g.idx[m.key] !== undefined && (!m.kind || m.kind === kk || (m.kinds || []).indexOf(kk) >= 0) && g.rows.some(r => k.isNum(r[g.idx[m.key]]))); });
  };
  if (raw && raw.ok !== false && raw.metrics && !Array.isArray(raw.metrics) && raw.rows && !Array.isArray(raw.rows)) {
    // analytics/leaders.lab: {"fields": [pid, name, team, pos, n], "metrics": {kind: [METRIC]}, "rows": {kind: [[...fields, ...metric values]]}}
    Object.keys(raw.rows).forEach(kd => {
      const ms = raw.metrics[kd] || [];
      const fields = (raw.fields || ['pid', 'name', 'team', 'pos', 'n']).concat(ms.map(m => m.key));
      const idx = {};
      fields.forEach((f, i) => { idx[f] = i; });
      if (idx.id === undefined && idx.pid !== undefined) idx.id = idx.pid;
      const kk = /pit/.test(kd) ? 'pitcher' : /team|club/.test(kd) ? 'team' : 'hitter';
      kinds[kk] = { idx: idx, meta: k.metaOf(ms), rows: raw.rows[kd] || [], metrics: ms.filter(m => (raw.rows[kd] || []).some(r => k.isNum(r[idx[m.key]]))) };
    });
    LAB_PRESETS = (raw.presets || []).filter(p => p && p.kind && p.x && p.y);
    N_LABEL = raw.n_label || {};
    LAB_META = { pbp: raw.pbp || null, expected: raw.expected || null, level: raw.level || '' };
  } else if (raw && raw.ok !== false && raw.windows && typeof raw.windows === 'object') {
    Object.keys(raw.windows).forEach(w => {
      const d = raw.windows[w];
      if (!d || !d.fields) return;
      const f = d.fields.indexOf('window') < 0 && d.fields.indexOf('season') < 0 ? d.fields.concat(['window']) : d.fields;
      fromCols({ fields: f, metrics: d.metrics || raw.metrics, rows: (d.rows || []).map(r => (f.length > d.fields.length ? r.concat([w]) : r)) }, d.kind);
    });
  } else if (raw && raw.ok !== false && raw.fields) fromCols(raw);
  else {
    // Fallback: the season catalogues, one window.
    [[hc, 'hitter'], [pc, 'pitcher']].forEach(x => {
      const c = x[0];
      if (!c) return;
      const keys = (c.metrics || []).map(m => m.key);
      const fields = ['id', 'name', 'team', 'pos', 'n', 'win'].concat(keys);
      fromCols({ fields: fields, metrics: c.metrics, rows: Object.keys(c.players).map(pid => { const p = c.players[pid]; return [pid, p.name, p.team, x[1] === 'pitcher' ? k.roleOf(p) : p.pos, k.sampleOf(p, x[1]), 'season'].concat(keys.map(kk => (p.values || {})[kk])); }) }, x[1]);
    });
  }
  Object.keys(kinds).forEach(kk => {
    const g = kinds[kk];
    const al = (want, list) => { if (g.idx[want] === undefined) for (let i = 0; i < list.length; i++) if (g.idx[list[i]] !== undefined) { g.idx[want] = g.idx[list[i]]; break; } };
    al('n', kk === 'pitcher' ? ['bf', 'tbf', 'n', 'pa'] : ['pa', 'n']);
    al('pos', ['role', 'position']);
    const wins = g.idx.win !== undefined ? Array.from(new Set(g.rows.map(r => String(r[g.idx.win])))) : ['season'];
    g.wins = wins.sort((a, b) => (/^\d{4}$/.test(b) ? Number(b) : 0) - (/^\d{4}$/.test(a) ? Number(a) : 0) || a.localeCompare(b));
  });
  return kinds;
}
function G() { return LAB[S0.kind] || LAB[Object.keys(LAB)[0]]; }
function raw(r, key) { const g = G(), i = g.idx[key]; if (i === undefined) return null; const v = r[i]; return v === null || v === undefined || (typeof v === 'number' && !isFinite(v)) ? null : v; }
function meta(key) { return G().meta[key] || (key === 'n' ? { key: 'n', label: nLong(), fmt: 'int' } : { key: key, label: key }); }
function shrinkable(key) { const m = meta(key); if (S0.kind === 'team') return false; return !NO_SHRINK.test(key) && ['int', 'plus', 'signed', 'rv', 'war'].indexOf(m.fmt) < 0 && key !== 'n'; }
function kOf(key) { const m = meta(key); return K().isNum(m.stabilises_at) ? m.stabilises_at * 3 / 7 : 200; }
function lower(key) { return !!meta(key).lower; }
function label(key) { return (meta(key).label || key) + (S0.shrink && shrinkable(key) ? ' (shrunk)' : ''); }
function fmt(key, v) { return K().fmtV(v, meta(key).fmt); }
function val(r, key) {
  const v = raw(r, key);
  if (v === null || !S0.shrink || !shrinkable(key)) return v;
  const mu = MU[key];
  if (!K().isNum(mu)) return v;
  const n = raw(r, 'n') || 0, kk = kOf(key);
  return (n * v + kk * mu) / (n + kk);
}
function resolve(pats) {
  const ms = G().metrics;
  for (let i = 0; i < pats.length; i++) { const p = pats[i]; if (typeof p === 'string') { const m = ms.find(x => x.key === p); if (m) return m.key; } }
  for (let i = 0; i < pats.length; i++) { const p = pats[i]; if (p instanceof RegExp) { const m = ms.find(x => p.test(x.key)); if (m) return m.key; } }
  return '';
}
function presetList() {
  const out = [];
  const seen = {};
  const has = key => G().metrics.some(m => m.key === key);       // a metric with values this season (NPB: no xwOBA before two seasons of play-by-play)
  const add = p => { if (p.x && p.y && p.x !== p.y && !seen[p.x + '|' + p.y] && G().idx[p.x] !== undefined && G().idx[p.y] !== undefined && has(p.x) && has(p.y)) { seen[p.x + '|' + p.y] = 1; out.push(p); } };
  LAB_PRESETS.filter(p => p.kind === S0.kind).forEach(p => add({ x: p.x, y: p.y, title: p.label || (p.x + ' v ' + p.y) }));
  PRESETS.filter(p => p[0] === S0.kind).forEach(p => add({ x: resolve(p[1]), y: resolve(p[2]), title: p[3] }));
  return out;
}
function zs(a) { const n = a.length; if (!n) return { m: 0, s: 1 }; const m = a.reduce((x, y) => x + y, 0) / n; const v = a.reduce((x, y) => x + (y - m) * (y - m), 0) / n; return { m: m, s: Math.sqrt(v) || 1 }; }
function pctRank(sorted, v) { let lo = 0, hi = sorted.length; while (lo < hi) { const mid = (lo + hi) >> 1; if (sorted[mid] < v) lo = mid + 1; else hi = mid; } let up = lo; while (up < sorted.length && sorted[up] === v) up++; return sorted.length ? 100 * ((lo + up) / 2) / sorted.length : null; }

function metricOptions(sel, scope) {
  const k = K();
  let h = scope === 'color' ? '<option value="team">Team</option><option value="pos">' + (S0.kind === 'pitcher' ? 'Role' : S0.kind === 'team' ? 'League' : 'Position') + '</option><option value="">One colour</option>' : '';
  k.groups(G().metrics).forEach(g => { h += '<optgroup label="' + k.esc(g.name) + '">' + g.items.map(m => '<option value="' + k.esc(m.key) + '"' + (m.key === sel ? ' selected' : '') + '>' + k.esc(m.label) + (m.lower ? ' ↓' : '') + '</option>').join('') + '</optgroup>'; });
  if (!scope) h += '<optgroup label="Sample"><option value="n"' + (sel === 'n' ? ' selected' : '') + '>' + nLong() + '</option></optgroup>';
  return h;
}
function sync() {
  const k = K(), $ = id => document.getElementById(id), g = G(), P = presetList();
  $('lab-kind').querySelectorAll('button').forEach(b => { b.classList.toggle('on', b.dataset.v === S0.kind); b.disabled = !LAB[b.dataset.v]; });
  $('lab-win').innerHTML = g.wins.map(w => '<option value="' + k.esc(w) + '"' + (w === S0.win ? ' selected' : '') + '>' + k.esc(w === 'season' ? 'This season' : w) + '</option>').join('');
  $('lab-preset').innerHTML = P.map((p, i) => '<option value="' + i + '"' + (i === S0.preset ? ' selected' : '') + '>' + k.esc(p.title) + '</option>').join('') + '<option value="-1"' + (S0.preset < 0 ? ' selected' : '') + '>Custom axes</option>';
  $('lab-x').innerHTML = metricOptions(S0.x); $('lab-y').innerHTML = metricOptions(S0.y);
  $('lab-x').value = S0.x; $('lab-y').value = S0.y;
  $('lab-color').innerHTML = metricOptions(S0.color, 'color'); $('lab-color').value = S0.color;
  $('lab-min').value = S0.min; $('lab-min-v').textContent = S0.min; $('lab-min-u').textContent = nU();
  $('lab-shrink').checked = S0.shrink; $('lab-q').value = S0.q;
}
function applyPreset() { const P = presetList(); if (S0.preset < 0 || !P.length) return; const p = P[S0.preset] || P[0]; S0.x = p.x; S0.y = p.y; }
function rowsNow() { const g = G(); return g.rows.filter(r => (g.idx.win === undefined || String(raw(r, 'win')) === String(S0.win))); }

function draw(L, S) {
  const k = K(), C = k.C;
  const base0 = rowsNow().filter(r => (raw(r, 'n') || 0) >= S0.min);
  Object.keys(MU).forEach(key => delete MU[key]);
  [S0.x, S0.y, S0.color].forEach(key => { if (key && G().idx[key] !== undefined && shrinkable(key)) MU[key] = k.median(base0.map(r => raw(r, key))); });
  const rows = base0.filter(r => val(r, S0.x) !== null && val(r, S0.y) !== null);
  const set = (id, h) => { const e = document.getElementById(id); if (e) e.innerHTML = h; };
  set('lab-sub', rows.length + ' ' + kindNoun() + ' · ' + k.esc(S0.win === 'season' ? S : S0.win) + ' · ' + S0.min + '+ ' + nU());
  if (rows.length < 3) { set('lab-chart', k.muted(L === 'npb' ? 'Too few for this view: lower the floor, or pick metrics this season has (the play-by-play metrics start in 2016).' : 'Too few players for this view: lower the floor, widen the window, or pick metrics these players have (bat tracking starts in 2023; framing is for catchers).')); set('lab-table', ''); set('lab-note', ''); return; }
  const xs = rows.map(r => val(r, S0.x)), ys = rows.map(r => val(r, S0.y));
  const mx = k.median(xs), my = k.median(ys), sx = zs(xs), sy = zs(ys);
  const dirx = lower(S0.x) ? -1 : 1, diry = lower(S0.y) ? -1 : 1;
  const score = r => dirx * (val(r, S0.x) - sx.m) / sx.s + diry * (val(r, S0.y) - sy.m) / sy.s;
  const ranked = rows.map(r => ({ r: r, z: score(r) })).sort((a, b) => b.z - a.z);
  const nm = r => raw(r, 'name') || (S0.kind === 'team' ? k.teamName(String(raw(r, 'id'))) : k.name(String(raw(r, 'id'))));
  const tm = r => raw(r, 'team');
  const q = k.fold(S0.q.trim());
  const hits = q ? rows.filter(r => k.fold(nm(r) + ' ' + k.teamAbbr(tm(r))).indexOf(q) >= 0) : [];
  const labelled = new Set(ranked.slice(0, 8).map(o => o.r).concat(ranked.slice(-4).map(o => o.r)).concat(hits.slice(0, 20)));
  const sortedX = xs.slice().sort((a, b) => a - b), sortedY = ys.slice().sort((a, b) => a - b);
  const pOf = (sorted, v, dir) => { const p = pctRank(sorted, v); return dir > 0 ? p : 100 - p; };
  const ns = rows.map(r => raw(r, 'n') || 0), lo = Math.min.apply(null, ns), hi = Math.max.apply(null, ns);
  const size = r => 6 + 13 * (hi > lo ? Math.sqrt(((raw(r, 'n') || 0) - lo) / (hi - lo)) : 0.5);
  const href = r => (S0.kind === 'team' ? k.teamHref(L, String(raw(r, 'id')), S) : S0.kind === 'pitcher' ? k.pitcherHref(L, String(raw(r, 'id')), S) : k.hitterHref(L, String(raw(r, 'id')), S));
  const hover = r => '<b>' + k.esc(nm(r)) + '</b> · ' + k.esc(k.teamAbbr(tm(r))) + ' · ' + k.int(raw(r, 'n')) + ' ' + nU() +
    '<br>' + k.esc(label(S0.x)) + ': ' + fmt(S0.x, val(r, S0.x)) + ' (pct ' + Math.round(pOf(sortedX, val(r, S0.x), dirx)) + ')' +
    '<br>' + k.esc(label(S0.y)) + ': ' + fmt(S0.y, val(r, S0.y)) + ' (pct ' + Math.round(pOf(sortedY, val(r, S0.y), diry)) + ')' +
    (S0.shrink && (shrinkable(S0.x) || shrinkable(S0.y)) ? '<br><span style="opacity:.7">unshrunk: ' + fmt(S0.x, raw(r, S0.x)) + ' · ' + fmt(S0.y, raw(r, S0.y)) + '</span>' : '');
  const trace = (pts, name, color, extra) => Object.assign({
    type: 'scatter', mode: 'markers', name: name, x: pts.map(r => val(r, S0.x)), y: pts.map(r => val(r, S0.y)),
    text: pts.map(hover), hovertemplate: '%{text}<extra></extra>', customdata: pts.map(href),
    marker: { size: pts.map(size), color: color, opacity: 0.85, line: { color: '#0d1117', width: 0.7 } }
  }, extra || {});
  const traces = [];
  if (S0.color === 'team' || S0.color === 'pos') {
    const key = S0.color === 'team' ? r => k.teamAbbr(tm(r)) : r => String(raw(r, 'pos') || '—');
    const cnt = {};
    rows.forEach(r => { cnt[key(r)] = (cnt[key(r)] || 0) + 1; });
    const top = Object.keys(cnt).sort((a, b) => cnt[b] - cnt[a]).slice(0, S0.color === 'team' ? 30 : 12);
    top.forEach((c, i) => {
      const pts = rows.filter(r => key(r) === c);
      const col = S0.color === 'team' && pts[0] ? k.teamColour(tm(pts[0])) : k.PALETTE[i % k.PALETTE.length];
      traces.push(trace(pts, c + ' (' + cnt[c] + ')', col));
    });
  } else if (S0.color) {
    const cv = rows.map(r => val(r, S0.color));
    traces.push(trace(rows, label(S0.color), cv, { marker: { size: rows.map(size), color: cv, colorscale: 'RdBu', reversescale: !lower(S0.color), opacity: 0.85,
      colorbar: { title: { text: label(S0.color), side: 'right' }, thickness: 10, tickfont: { color: C.text2 } }, line: { color: '#0d1117', width: 0.7 } } }));
  } else traces.push(trace(rows, 'Players', '#58a6ff'));
  if (hits.length) traces.push(Object.assign(trace(hits, 'Search', '#ffffff'), { marker: { size: 20, color: 'rgba(0,0,0,0)', symbol: 'star-open', line: { color: '#ffffff', width: 2 } }, showlegend: false }));
  const ann = Array.from(labelled).map(r => ({ x: val(r, S0.x), y: val(r, S0.y), text: k.esc(k.surname(nm(r))), showarrow: false, yshift: 11, font: { size: 10, color: hits.indexOf(r) >= 0 ? '#ffffff' : '#c9d1d9' } }));
  const diag = (/xwoba/.test(S0.x) && /xwoba|^woba$/.test(S0.y)) || (/^woba$/.test(S0.x) && /xwoba/.test(S0.y));
  if (diag) { const lim = [Math.min(Math.min.apply(null, xs), Math.min.apply(null, ys)), Math.max(Math.max.apply(null, xs), Math.max.apply(null, ys))]; traces.unshift({ type: 'scatter', mode: 'lines', x: lim, y: lim, line: { color: '#6e7681', dash: 'dash', width: 1 }, hoverinfo: 'skip', showlegend: false }); }
  const r = k.corr(xs, ys);
  const narrow = k.narrow(document.getElementById('lab-chart'));
  k.plot('lab-chart', traces, k.layout({
    showlegend: !narrow && (S0.color === 'team' || S0.color === 'pos'), legend: { orientation: 'h', y: -0.18, font: { color: C.text2, size: 9 } }, margin: { l: 66, r: 16, t: 20, b: narrow ? 50 : 90 }, annotations: ann, hovermode: 'closest',
    xaxis: { title: label(S0.x), zeroline: false, autorange: lower(S0.x) ? 'reversed' : true, tickformat: meta(S0.x).fmt === 'pct' ? '.0%' : '' },
    yaxis: { title: label(S0.y), zeroline: false, autorange: lower(S0.y) ? 'reversed' : true, tickformat: meta(S0.y).fmt === 'pct' ? '.0%' : '' },
    shapes: [{ type: 'line', x0: mx, x1: mx, yref: 'paper', y0: 0, y1: 1, line: { color: '#3d444d', dash: 'dot', width: 1 } }, { type: 'line', y0: my, y1: my, xref: 'paper', x0: 0, x1: 1, line: { color: '#3d444d', dash: 'dot', width: 1 } }]
  }));
  const node = document.getElementById('lab-chart');
  if (node && node.on) node.on('plotly_click', ev => { const h = ev.points && ev.points[0] && ev.points[0].customdata; if (h && typeof h === 'string') location.hash = h; });
  const mX = meta(S0.x), mY = meta(S0.y);
  set('lab-note', 'Correlation on screen r = ' + k.num(r, 2) + ' (' + rows.length + ' players). Dotted lines are medians. ' + (lower(S0.x) || lower(S0.y) ? 'Axes where less is better are reversed, so better is always up and to the right. ' : 'Better is up and to the right. ') +
    (diag ? 'The dashed diagonal is equality. ' : '') + 'Labelled: the eight furthest into the good corner, the four furthest from it' + (hits.length ? ', and your search' : '') + '. Marker size is the sample. Click a dot to open the player.' +
    (S0.shrink ? ' Rates marked "shrunk" are pulled to the median of the players on screen by their own stabilisation point: (n·x + k·median)/(n + k) with k = 3/7 of the sample at which the metric reaches 0.7 split-half reliability (' + (shrinkable(S0.x) ? k.esc(mX.label || S0.x) + ' k = ' + k.int(kOf(S0.x)) : '') + (shrinkable(S0.x) && shrinkable(S0.y) ? ', ' : '') + (shrinkable(S0.y) ? k.esc(mY.label || S0.y) + ' k = ' + k.int(kOf(S0.y)) : '') + '). Model scores (the "+" scores), WAR and run totals are never shrunk here: the models regularise them already.' : '') +
    (mX.desc ? '<br><strong>' + k.esc(mX.label) + '</strong>: ' + k.esc(mX.desc) : '') + (mY.desc ? '<br><strong>' + k.esc(mY.label) + '</strong>: ' + k.esc(mY.desc) : '') + npbNote([S0.x, S0.y]));
  const host = document.getElementById('lab-table');
  host.innerHTML = k.table([{ label: '#', sortable: false }, { label: S0.kind === 'pitcher' ? 'Pitcher' : S0.kind === 'team' ? 'Club' : 'Hitter' }, { label: S0.kind === 'team' ? 'League' : 'Team' }, { label: nU(), align: 'right' },
    { label: label(S0.x), align: 'right' }, { label: 'Pct', align: 'right' }, { label: label(S0.y), align: 'right' }, { label: 'Pct', align: 'right' }, { label: 'Combined', align: 'right', title: 'Sum of standard scores in the better direction' }],
  ranked.slice(0, 300).map((o, i) => { const rr = o.r, vx = val(rr, S0.x), vy = val(rr, S0.y);
    return { _href: href(rr), cells: [{ v: i + 1, cls: 'pos-cell' }, { v: nm(rr), html: '<a class="ply-link" href="' + href(rr) + '">' + k.esc(nm(rr)) + '</a>' }, S0.kind === 'team' ? { v: raw(rr, 'pos'), html: k.esc(raw(rr, 'pos') || '—') } : { v: k.teamAbbr(tm(rr)), html: k.teamChip(L, tm(rr), S) }, { v: raw(rr, 'n'), html: k.int(raw(rr, 'n')) },
      { v: vx, html: fmt(S0.x, vx) }, { v: pOf(sortedX, vx, dirx), html: k.pill(pOf(sortedX, vx, dirx)) }, { v: vy, html: fmt(S0.y, vy) }, { v: pOf(sortedY, vy, diry), html: k.pill(pOf(sortedY, vy, diry)) }, { v: o.z, html: '<strong>' + k.num(o.z, 2) + '</strong>' }] }; }), { sticky: true, compact: true });
  k.sortable(host);
}

function render(el, params, state) {
  const k = K();
  const L = k.L(params, state);
  el.innerHTML = '<div class="card"><div class="card-header">' + k.LN(L) + ' lab <span class="card-sub" id="lab-sub">Loading…</span></div>' +
    '<div class="lab-controls gq-controls">' + k.toggle('lab-kind', L === 'npb' ? [['hitter', 'Hitters'], ['pitcher', 'Pitchers'], ['team', 'Clubs']] : [['hitter', 'Hitters'], ['pitcher', 'Pitchers']], S0.kind) +
    '<label>Window<select id="lab-win"></select></label><label>Preset<select id="lab-preset" class="gq-wide"></select></label>' +
    '<label>X axis<select id="lab-x"></select></label><label>Y axis<select id="lab-y"></select></label><label>&nbsp;<button type="button" id="lab-swap" class="gq-btn" title="Swap the axes">⇄ swap</button></label>' +
    '<label>Colour<select id="lab-color"></select></label><label>Min <span id="lab-min-u"></span> <span id="lab-min-v"></span><input id="lab-min" type="range" min="0" max="700" step="5"></label>' +
    '<label class="inline"><input id="lab-shrink" type="checkbox"> shrink by stabilisation</label><label>Highlight<input id="lab-q" class="gq-search" type="search" placeholder="player or team…"></label>' +
    '</div><div id="lab-chart" class="gq-lab-chart"></div><div class="pg-note gq-note" id="lab-note"></div></div>' +
    '<div class="card"><div class="card-header">Ranked <span class="card-sub">By the combined standard score on both axes (top 300). Click a row for the player.</span></div><div id="lab-table"></div></div>';
  return k.ready().then(() => {
    const S = k.S(params, state);
    // NPB: one file (npb/<S>/lab.json: hitters, pitchers and clubs); MLB and Triple-A fall back to the catalogues
    const more = L === 'npb' ? [Promise.resolve(null), Promise.resolve(null), Promise.resolve(null)] : [k.loadY(L, S, 'hitters.json'), k.loadY(L, S, 'pitchers.json'), k.loadNames()];
    return Promise.all([k.loadY(L, S, 'lab.json')].concat(more)).then(res => ({ S: S, res: res }));
  }).then(o => {
    if (!k.alive(el)) return;
    const S = o.S, res = o.res, $ = id => document.getElementById(id);
    const hc = k.catOf(res[1], 'hitters'), pc = k.catOf(res[2], 'pitchers');
    if (hc) k.learnCat(hc);
    if (pc) k.learnCat(pc);
    const key = L + '/' + S;
    if (LABK !== key) { LAB = prep(res[0], hc, pc); LABK = key; S0.win = null; S0.min = null; S0.x = ''; S0.y = ''; S0.preset = 0; }
    if (!Object.keys(LAB).length) { $('lab-chart').innerHTML = k.notBuilt('The ' + k.LN(L) + ' ' + S + ' lab file', res[0]); $('lab-sub').textContent = ''; return; }
    const qy = params.query || {};
    if (qy.kind && LAB[qy.kind]) S0.kind = qy.kind;
    if (!LAB[S0.kind]) S0.kind = Object.keys(LAB)[0];
    const reset = () => {
      const g = G();
      if (S0.win === null || g.wins.indexOf(S0.win) < 0) S0.win = g.wins.indexOf(String(S)) >= 0 ? String(S) : g.wins[0];
      const maxN = Math.max.apply(null, rowsNow().map(r => raw(r, 'n') || 0).concat([50]));
      $('lab-min').max = String(Math.ceil(maxN / 10) * 10);
      if (S0.min === null || S0.min > maxN * 0.6) S0.min = S0.kind === 'team' ? 0 : Math.round(Math.min(S0.kind === 'pitcher' ? 150 : 200, maxN * 0.25) / 5) * 5;
      if (!S0.x || g.idx[S0.x] === undefined || !S0.y || g.idx[S0.y] === undefined) { if (S0.preset < 0) S0.preset = 0; applyPreset(); }
      if (!S0.x || !S0.y) { const ms = g.metrics; S0.x = (ms[0] || {}).key || 'n'; S0.y = (ms[1] || {}).key || 'n'; S0.preset = -1; }
    };
    if (qy.x && G().idx[qy.x] !== undefined) { S0.x = qy.x; S0.preset = -1; }
    if (qy.y && G().idx[qy.y] !== undefined) { S0.y = qy.y; S0.preset = -1; }
    reset();
    sync();
    const redraw = () => draw(L, S);
    $('lab-kind').querySelectorAll('button').forEach(b => b.addEventListener('click', () => { if (!LAB[b.dataset.v]) return; S0.kind = b.dataset.v; S0.x = ''; S0.y = ''; S0.preset = 0; S0.min = null; if (S0.color !== 'team' && S0.color !== 'pos' && S0.color) S0.color = 'team'; reset(); sync(); redraw(); }));
    $('lab-win').onchange = e => { S0.win = e.target.value; S0.min = null; reset(); sync(); redraw(); };
    $('lab-preset').onchange = e => { S0.preset = parseInt(e.target.value, 10); applyPreset(); sync(); redraw(); };
    $('lab-x').onchange = e => { S0.x = e.target.value; S0.preset = -1; sync(); redraw(); };
    $('lab-y').onchange = e => { S0.y = e.target.value; S0.preset = -1; sync(); redraw(); };
    $('lab-swap').onclick = () => { const t = S0.x; S0.x = S0.y; S0.y = t; S0.preset = -1; sync(); redraw(); };
    $('lab-color').onchange = e => { S0.color = e.target.value; redraw(); };
    $('lab-min').oninput = e => { S0.min = parseInt(e.target.value, 10); $('lab-min-v').textContent = S0.min; };
    $('lab-min').onchange = redraw;
    $('lab-shrink').onchange = e => { S0.shrink = e.target.checked; redraw(); };
    let timer = null;
    $('lab-q').oninput = e => { S0.q = e.target.value; clearTimeout(timer); timer = setTimeout(redraw, 250); };
    redraw();
  });
}

if (typeof BP.route === 'function') { BP.route('lab', render); try { BP.route('#/<L>/lab', render); } catch (e) { /* bound */ } }
if (typeof BP.routeNpb === 'function') BP.routeNpb('lab', render);
})(window.BP || (window.BP = {}));
