/* The Quant Gridiron — the lab (#/lab): any two metrics for a position group, or for the teams.
 *
 * Scatter any two catalogue metrics, with presets for the questions the models were built to answer
 * (CPOE against aDOT, EPA under pressure against clean-pocket EPA, RYOE against success rate,
 * separation against YAC over expected, PROE against EPA per play ...), colour by team, position
 * or any metric, medians as quadrants, the corners labelled, a search highlight and the group
 * ranked below. Rates can be shrunk towards the median by each metric's stabilisation point:
 * shrunk = (n·x + k·median)/(n + k), with k = 3/7 of the sample at which split-half reliability
 * reaches 0.7 (r(n) = n/(n + k), so n₀.₇ = 7k/3).
 *
 * Address: #/lab?g=QB|RB|WR|TE|K|P|DEF|TEAM&x=<key>&y=<key>.
 * Data: data/<S>/lab.json ({"groups": {G: {cols, rows}}, "teams": {cols, rows}, "metrics", "team_metrics"}),
 * falling back to players.json and teams.json. Uses GI.fk. */
(function (GI) {
'use strict';

const K = () => GI.fk;
const PRESETS = [
  ['QB', ['cpoe'], ['adot'], 'CPOE against aDOT: accuracy against depth'],
  ['QB', ['epa_clean'], ['epa_pressure'], 'EPA in a clean pocket against EPA under pressure'],
  ['QB', ['ttt'], ['sack_rate'], 'Time to throw against sack rate: who holds the ball and pays for it'],
  ['QB', ['epa_db'], ['composite'], 'EPA per dropback against the QB composite'],
  ['QB', ['pa_rate'], ['epa_pa'], 'Play-action rate against EPA on play action'],
  ['RB', ['ryoe'], ['rush_success'], 'RYOE against success rate: yards over expected or staying on schedule?'],
  ['RB', ['box8'], ['ryoe'], 'Eight-man boxes against RYOE'],
  ['RB', ['explosive'], ['stuff_rate'], 'Explosive runs against stuffed runs'],
  ['WR', ['separation'], ['yacoe'], 'Separation against YAC over expected'],
  ['WR', ['adot'], ['croe'], 'aDOT against catch rate over expected'],
  ['WR', ['target_share'], ['rec_epa_tgt'], 'Target share against EPA per target: volume and efficiency'],
  ['TE', ['target_share'], ['rec_epa_tgt'], 'Target share against EPA per target'],
  ['K', ['avg_dist'], ['fg_oe'], 'Average attempt distance against FG over expected'],
  ['P', ['gross'], ['epa_punt'], 'Gross distance against EPA per punt'],
  ['DEF', ['pressures_pg'], ['def_value'], 'Sacks and hits per game against splash EPA'],
  ['TEAM', ['proe'], ['off_epa'], 'PROE against offensive EPA per play: does passing more pay?'],
  ['TEAM', ['off_epa'], ['def_epa'], 'Offence against defence (EPA per play; defence axis reversed)'],
  ['TEAM', ['go_rate'], ['fd_wp_lost'], 'Fourth-down go rate against win probability lost'],
  ['TEAM', ['sec_per_play_neutral'], ['off_epa'], 'Pace against offensive efficiency'],
  ['TEAM', ['pa_rate'], ['off_pass_epa'], 'Play-action rate against pass offence']
];
const NO_SHRINK = /^(n|g|games|age|season|composite|value|def_value|pts_oe|fg_oe|epa_total|rec_epa|scramble_epa|rush_epa_qb|.*_yds|.*_td|ints|sacks|qb_hits|tfl|tackles|pd|ff|att|carries|targets|rec|fga|fgm|fg_50|punts)$/;
let LAB = null, LABK = '';
const S0 = { kind: 'QB', min: null, shrink: true, preset: 0, x: '', y: '', color: 'team', q: '', qual: true };
const MU = {};

/* -> {QB: {idx, meta, metrics, rows, nKey, nLabel}, ..., TEAM: {...}} */
function prep(raw, cat, tms) {
  const k = K();
  const kinds = {};
  const mkKind = (g, cols, rows, metrics) => {
    const idx = {};
    cols.forEach((c, i) => { idx[c] = i; });
    if (idx.pid === undefined && idx.gsis_id !== undefined) idx.pid = idx.gsis_id;
    const meta = k.metaOf(metrics);
    const ms = metrics.filter(m => idx[m.key] !== undefined && rows.some(r => k.isNum(r[idx[m.key]])));
    const sk = g === 'TEAM' ? ['games', 'Games'] : (k.SAMPLE[g] || []).find(s => idx[s[0]] !== undefined) || ['games', 'Games'];
    kinds[g] = { idx: idx, meta: meta, metrics: ms, rows: rows, nKey: sk[0], nLabel: sk[1] };
  };
  if (raw && raw.ok !== false) { k.cleanMetrics(raw.metrics); k.cleanMetrics(raw.team_metrics); }
  if (raw && raw.ok !== false && raw.groups && typeof raw.groups === 'object') {
    Object.keys(raw.groups).forEach(g => { const G = raw.groups[g] || {}; if (Array.isArray(G.cols) && Array.isArray(G.rows) && G.rows.length) mkKind(g, G.cols, G.rows, k.metricsFor(raw, g).length ? k.metricsFor(raw, g) : (raw.metrics || [])); });
    if (raw.teams && Array.isArray(raw.teams.cols) && (raw.teams.rows || []).length) mkKind('TEAM', raw.teams.cols, raw.teams.rows, raw.team_metrics || []);
  }
  if (!Object.keys(kinds).length && cat) {
    const by = {};
    Object.keys(cat.players).forEach(id => { const p = cat.players[id]; const g = k.groupOf(p.pos, p.group); (by[g] = by[g] || []).push(id); });
    Object.keys(by).forEach(g => {
      if (k.GROUPS.indexOf(g) < 0) return;
      const ms = k.metricsFor(cat, g), keys = ms.map(m => m.key);
      const cols = ['pid', 'name', 'team', 'pos', 'age', 'games', 'qualified'].concat(keys);
      mkKind(g, cols, by[g].map(id => { const p = cat.players[id]; return [id, p.name, p.team, p.pos, p.age, p.games, p.qualified].concat(keys.map(x => (p.values || {})[x])); }), ms);
    });
  }
  if (!kinds.TEAM && tms && tms.teams) {
    const ms = tms.metrics || [], keys = ms.map(m => m.key);
    const T = tms.teams;
    mkKind('TEAM', ['team', 'name', 'colour', 'games'].concat(keys), Object.keys(T).map(t => [t, T[t].name, T[t].colour, ((T[t].record || {}).w || 0) + ((T[t].record || {}).l || 0) + ((T[t].record || {}).t || 0)].concat(keys.map(x => (T[t].values || {})[x]))), ms);
  }
  return kinds;
}
function G() { return LAB[S0.kind] || LAB[Object.keys(LAB)[0]]; }
function raw(r, key) { const g = G(), i = g.idx[key]; if (i === undefined) return null; const v = r[i]; return v === null || v === undefined || (typeof v === 'number' && !isFinite(v)) ? null : v; }
function idOf(r) { return String(S0.kind === 'TEAM' ? raw(r, 'team') : (raw(r, 'pid') || raw(r, 'id'))); }
function nOf(r) { const v = raw(r, G().nKey); return K().isNum(v) ? Number(v) : 0; }
function meta(key) { return G().meta[key] || { key: key, label: key === G().nKey ? G().nLabel : key }; }
function shrinkable(key) { const m = meta(key); return S0.kind !== 'TEAM' && !NO_SHRINK.test(key) && K().isNum(m.stabilises_at) && ['int', '0'].indexOf(m.fmt) < 0; }
function kOf(key) { const m = meta(key); return K().isNum(m.stabilises_at) ? m.stabilises_at * 3 / 7 : 200; }
function lower(key) { return !!meta(key).lower; }
function label(key) { return (meta(key).label || key) + (S0.shrink && shrinkable(key) ? ' (shrunk)' : ''); }
function fmt(key, v) { return K().fmtV(v, meta(key).fmt); }
/* The sample a metric is measured on: the metric's "unit" when the row carries it, else the group's sample. */
function nFor(r, key) { const u = meta(key).unit; const v = u ? raw(r, u) : null; return K().isNum(v) ? Number(v) : nOf(r); }
function val(r, key) {
  const v = raw(r, key);
  if (v === null || !S0.shrink || !shrinkable(key)) return v;
  const mu = MU[key];
  if (!K().isNum(mu)) return v;
  const n = nFor(r, key), kk = kOf(key);
  return (n * v + kk * mu) / (n + kk);
}
function presetList() {
  const out = [], seen = {};
  PRESETS.filter(p => p[0] === S0.kind || (S0.kind === 'TE' && p[0] === 'WR' && !PRESETS.some(q => q[0] === 'TE' && q[3] === p[3]))).forEach(p => {
    const x = p[1].find(c => G().idx[c] !== undefined), y = p[2].find(c => G().idx[c] !== undefined);
    if (x && y && x !== y && !seen[x + '|' + y]) { seen[x + '|' + y] = 1; out.push({ x: x, y: y, title: p[3] }); }
  });
  return out;
}
function zs(a) { const n = a.length; if (!n) return { m: 0, s: 1 }; const m = a.reduce((x, y) => x + y, 0) / n; const v = a.reduce((x, y) => x + (y - m) * (y - m), 0) / n; return { m: m, s: Math.sqrt(v) || 1 }; }
function pctRank(sorted, v) { let lo = 0, hi = sorted.length; while (lo < hi) { const mid = (lo + hi) >> 1; if (sorted[mid] < v) lo = mid + 1; else hi = mid; } let up = lo; while (up < sorted.length && sorted[up] === v) up++; return sorted.length ? 100 * ((lo + up) / 2) / sorted.length : null; }

function metricOptions(sel, scope) {
  const k = K();
  let h = scope === 'color' ? '<option value="team">Team</option>' + (S0.kind !== 'TEAM' ? '<option value="pos">Position</option>' : '<option value="conf">Conference</option>') + '<option value="">One colour</option>' : '';
  k.groups(G().metrics).forEach(g => { h += '<optgroup label="' + k.esc(g.name) + '">' + g.items.map(m => '<option value="' + k.esc(m.key) + '"' + (m.key === sel ? ' selected' : '') + '>' + k.esc(m.label) + (m.lower ? ' ↓' : '') + '</option>').join('') + '</optgroup>'; });
  return h;
}
function sync() {
  const k = K(), $ = k.$, P = presetList();
  $('lab-kind').querySelectorAll('button').forEach(b => { b.classList.toggle('on', b.dataset.v === S0.kind); b.disabled = !LAB[b.dataset.v]; });
  $('lab-preset').innerHTML = P.map((p, i) => '<option value="' + i + '"' + (i === S0.preset ? ' selected' : '') + '>' + k.esc(p.title) + '</option>').join('') + '<option value="-1"' + (S0.preset < 0 ? ' selected' : '') + '>Custom axes</option>';
  $('lab-x').innerHTML = metricOptions(S0.x); $('lab-y').innerHTML = metricOptions(S0.y);
  $('lab-x').value = S0.x; $('lab-y').value = S0.y;
  $('lab-color').innerHTML = metricOptions(S0.color, 'color'); $('lab-color').value = S0.color;
  $('lab-min').value = S0.min; $('lab-min-v').textContent = S0.min; $('lab-min-u').textContent = G().nLabel.toLowerCase();
  $('lab-min').parentNode.style.display = S0.kind === 'TEAM' ? 'none' : '';
  $('lab-qual').parentNode.style.display = S0.kind === 'TEAM' || G().idx.qualified === undefined ? 'none' : '';
  $('lab-shrink').parentNode.style.display = S0.kind === 'TEAM' ? 'none' : '';
  $('lab-shrink').checked = S0.shrink; $('lab-q').value = S0.q; $('lab-qual').checked = S0.qual;
}
function applyPreset() { const P = presetList(); if (S0.preset < 0 || !P.length) return; const p = P[S0.preset] || P[0]; S0.x = p.x; S0.y = p.y; }

function draw(S) {
  const k = K(), C = k.C;
  const team = S0.kind === 'TEAM';
  const base0 = G().rows.filter(r => team || ((nOf(r) >= S0.min) && (!S0.qual || G().idx.qualified === undefined || raw(r, 'qualified') !== false)));
  Object.keys(MU).forEach(key => delete MU[key]);
  [S0.x, S0.y, S0.color].forEach(key => { if (key && G().idx[key] !== undefined && shrinkable(key)) MU[key] = k.median(base0.map(r => raw(r, key))); });
  const rows = base0.filter(r => val(r, S0.x) !== null && val(r, S0.y) !== null);
  const noun = team ? 'teams' : (k.GROUP_NAME[S0.kind] || 'players').toLowerCase();
  k.set('lab-sub', rows.length + ' ' + noun + ' · ' + S + (team ? '' : ' · ' + S0.min + '+ ' + G().nLabel.toLowerCase() + (S0.qual ? ' · qualified' : '')));
  if (rows.length < 3) { k.set('lab-chart', k.muted('Too few for this view: lower the floor, untick qualified only, or pick metrics these players have (FTN charting starts in 2022, NGS in 2016).')); k.set('lab-table', ''); k.set('lab-note', ''); return; }
  const xs = rows.map(r => val(r, S0.x)), ys = rows.map(r => val(r, S0.y));
  const mx = k.median(xs), my = k.median(ys), sx = zs(xs), sy = zs(ys);
  const dirx = lower(S0.x) ? -1 : 1, diry = lower(S0.y) ? -1 : 1;
  const score = r => dirx * (val(r, S0.x) - sx.m) / sx.s + diry * (val(r, S0.y) - sy.m) / sy.s;
  const ranked = rows.map(r => ({ r: r, z: score(r) })).sort((a, b) => b.z - a.z);
  const nm = r => (team ? k.teamName(raw(r, 'team')) : (raw(r, 'name') || k.name(idOf(r))));
  const short = r => (team ? raw(r, 'team') : k.surname(nm(r)));
  const tm = r => (team ? raw(r, 'team') : raw(r, 'team'));
  const q = k.fold(S0.q.trim());
  const hits = q ? rows.filter(r => k.fold(nm(r) + ' ' + (tm(r) || '')).indexOf(q) >= 0) : [];
  const labelled = new Set(team ? rows : ranked.slice(0, 8).map(o => o.r).concat(ranked.slice(-4).map(o => o.r)).concat(hits.slice(0, 20)));
  const sortedX = xs.slice().sort((a, b) => a - b), sortedY = ys.slice().sort((a, b) => a - b);
  const pOf = (sorted, v, dir) => { const p = pctRank(sorted, v); return dir > 0 ? p : 100 - p; };
  const ns = rows.map(nOf), lo = Math.min.apply(null, ns), hi = Math.max.apply(null, ns);
  const size = r => (team ? 13 : 6 + 13 * (hi > lo ? Math.sqrt((nOf(r) - lo) / (hi - lo)) : 0.5));
  const href = r => (team ? k.teamHref(idOf(r), S) : k.playerHref(idOf(r), S));
  const hover = r => '<b>' + k.esc(nm(r)) + '</b>' + (team ? '' : ' · ' + k.esc(tm(r) || '') + ' · ' + k.int(nOf(r)) + ' ' + k.esc(G().nLabel.toLowerCase())) +
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
    const key = S0.color === 'team' ? r => String(tm(r) || '—') : S0.color === 'conf' ? r => String(k.team(raw(r, 'team')).conference || String(k.team(raw(r, 'team')).division || '').slice(0, 3) || '—') : r => String(raw(r, 'pos') || '—');
    const cnt = {};
    rows.forEach(r => { cnt[key(r)] = (cnt[key(r)] || 0) + 1; });
    Object.keys(cnt).sort((a, b) => cnt[b] - cnt[a]).slice(0, 34).forEach((c, i) => {
      const pts = rows.filter(r => key(r) === c);
      const col = S0.color === 'team' && pts[0] ? k.teamColour(tm(pts[0])) : (c === 'AFC' ? '#e8504f' : c === 'NFC' ? '#58a6ff' : k.PALETTE[i % k.PALETTE.length]);
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
  const mX = meta(S0.x), mY = meta(S0.y);
  k.set('lab-note', 'Correlation on screen r = ' + k.num(rr, 2) + ' (' + rows.length + ' ' + noun + '). Dotted lines are medians. ' + (lower(S0.x) || lower(S0.y) ? 'Axes where less is better are reversed, so better is always up and to the right. ' : 'Better is up and to the right. ') +
    (team ? '' : 'Labelled: the eight furthest into the good corner, the four furthest from it' + (hits.length ? ', and your search' : '') + '. Marker size is the sample. ') + 'Click a dot to open the page.' +
    (S0.shrink && !team ? ' Rates marked "shrunk" are pulled to the median of the ' + noun + ' on screen by their own stabilisation point: (n·x + k·median)/(n + k) with k = 3/7 of the sample at which the metric reaches 0.7 split-half reliability' + (shrinkable(S0.x) ? ' (' + k.esc(mX.label) + ' k = ' + k.int(kOf(S0.x)) + ')' : '') + (shrinkable(S0.y) ? ' (' + k.esc(mY.label) + ' k = ' + k.int(kOf(S0.y)) + ')' : '') + '. Totals, values and the QB composite are never shrunk: the models regularise them already.' : '') +
    (mX.desc ? '<br><strong>' + k.esc(mX.label) + '</strong>: ' + k.esc(mX.desc) : '') + (mY.desc ? '<br><strong>' + k.esc(mY.label) + '</strong>: ' + k.esc(mY.desc) : ''));
  const host = k.$('lab-table');
  host.innerHTML = k.table([{ label: '#', sortable: false }, { label: team ? 'Team' : 'Player' }].concat(team ? [] : [{ label: 'Team' }, { label: G().nLabel, align: 'right' }])
    .concat([{ label: label(S0.x), align: 'right' }, { label: 'Pct', align: 'right' }, { label: label(S0.y), align: 'right' }, { label: 'Pct', align: 'right' }, { label: 'Combined', align: 'right', title: 'Sum of standard scores in the better direction' }]),
  ranked.slice(0, 300).map((o, i) => { const r = o.r, vx = val(r, S0.x), vy = val(r, S0.y);
    return { _href: href(r), cells: [{ v: i + 1, cls: 'pos-cell' }, { v: nm(r), html: team ? k.teamChip(idOf(r), S) + ' <a href="' + href(r) + '">' + k.esc(nm(r)) + '</a>' : '<a class="ply-link" href="' + href(r) + '">' + k.esc(nm(r)) + '</a>' }]
      .concat(team ? [] : [{ v: tm(r) || '', html: k.teamChip(tm(r), S) }, { v: nOf(r), html: k.int(nOf(r)) }])
      .concat([{ v: vx, html: fmt(S0.x, vx) }, { v: pOf(sortedX, vx, dirx), html: k.pill(pOf(sortedX, vx, dirx)) }, { v: vy, html: fmt(S0.y, vy) }, { v: pOf(sortedY, vy, diry), html: k.pill(pOf(sortedY, vy, diry)) }, { v: o.z, html: '<strong>' + k.num(o.z, 2) + '</strong>' }]) }; }), { sticky: true, compact: true });
  k.sortable(host);
}

function render(el, params, state) {
  const k = K();
  const kinds = k.GROUPS.concat(['TEAM']);
  el.innerHTML = '<div class="card"><div class="card-header">Lab <span class="card-sub" id="lab-sub">Loading…</span><span class="gq-ctl">' + k.toggle('lab-kind', kinds.map(g => [g, g === 'TEAM' ? 'Teams' : g]), S0.kind) + '</span></div>' +
    '<div class="lab-controls gq-controls"><label>Preset<select id="lab-preset" class="gq-wide"></select></label>' +
    '<label>X axis<select id="lab-x"></select></label><label>Y axis<select id="lab-y"></select></label><label>&nbsp;<button type="button" id="lab-swap" class="gq-btn" title="Swap the axes">⇄ swap</button></label>' +
    '<label>Colour<select id="lab-color"></select></label><label><span>Min <span id="lab-min-u"></span> <span id="lab-min-v"></span></span><input id="lab-min" type="range" min="0" max="700" step="1"></label>' +
    '<label class="inline"><input id="lab-qual" type="checkbox"> qualified only</label><label class="inline"><input id="lab-shrink" type="checkbox"> shrink by stabilisation</label><label>Highlight<input id="lab-q" class="gq-search" type="search" placeholder="player or team…"></label>' +
    '</div><div id="lab-chart" class="gq-lab-chart"></div><div class="pg-note gq-note" id="lab-note"></div></div>' +
    '<div class="card"><div class="card-header">Ranked <span class="card-sub">By the combined standard score on both axes (top 300). Click a row for the page.</span></div><div id="lab-table"></div></div>';
  return k.ready().then(() => {
    const S = k.S(params, state);
    return Promise.all([k.loadY(S, 'lab.json'), k.loadY(S, 'players.json'), k.loadY(S, 'teams.json'), k.loadNames()]).then(res => ({ S: S, res: res }));
  }).then(o => {
    if (!k.alive(el)) return;
    const S = o.S, res = o.res, $ = k.$;
    const cat = k.catOf(res[1]);
    if (cat) k.learnCat(cat);
    const tms = GI.fk.T ? GI.fk.T.teamsOf(res[2]) : (res[2] && res[2].teams ? res[2] : null);
    if (LABK !== String(S)) { LAB = prep(res[0], cat, tms); LABK = String(S); S0.min = null; S0.x = ''; S0.y = ''; S0.preset = 0; }
    if (!Object.keys(LAB).length) { $('lab-chart').innerHTML = k.notBuilt('The ' + S + ' lab file', res[0]); $('lab-sub').textContent = ''; return; }
    const qy = params.query || {};
    if (qy.g && LAB[String(qy.g).toUpperCase()]) S0.kind = String(qy.g).toUpperCase();
    if (!LAB[S0.kind]) S0.kind = Object.keys(LAB)[0];
    const reset = () => {
      const g = G();
      const maxN = Math.max.apply(null, g.rows.map(nOf).concat([10]));
      $('lab-min').max = String(Math.ceil(maxN));
      if (S0.min === null || S0.min > maxN) S0.min = 0;
      if (!S0.x || g.idx[S0.x] === undefined || !S0.y || g.idx[S0.y] === undefined) { if (S0.preset < 0) S0.preset = 0; applyPreset(); }
      if (!S0.x || !S0.y || g.idx[S0.x] === undefined || g.idx[S0.y] === undefined) { const ms = g.metrics; S0.x = (ms[0] || {}).key || g.nKey; S0.y = (ms[1] || {}).key || g.nKey; S0.preset = -1; }
      if (S0.color && ['team', 'pos', 'conf'].indexOf(S0.color) < 0 && g.idx[S0.color] === undefined) S0.color = 'team';
      if (S0.color === 'pos' && S0.kind === 'TEAM') S0.color = 'team';
      if (S0.color === 'conf' && S0.kind !== 'TEAM') S0.color = 'team';
    };
    if (qy.x && G().idx[qy.x] !== undefined) { S0.x = qy.x; S0.preset = -1; }
    if (qy.y && G().idx[qy.y] !== undefined) { S0.y = qy.y; S0.preset = -1; }
    reset();
    if (qy.x && !qy.y && G().idx[qy.x] !== undefined) { S0.x = qy.x; S0.preset = -1; }
    sync();
    const redraw = () => draw(S);
    $('lab-kind').querySelectorAll('button').forEach(b => b.addEventListener('click', () => { if (!LAB[b.dataset.v]) return; S0.kind = b.dataset.v; S0.x = ''; S0.y = ''; S0.preset = 0; S0.min = null; reset(); sync(); redraw(); }));
    $('lab-preset').onchange = e => { S0.preset = parseInt(e.target.value, 10); applyPreset(); sync(); redraw(); };
    $('lab-x').onchange = e => { S0.x = e.target.value; S0.preset = -1; sync(); redraw(); };
    $('lab-y').onchange = e => { S0.y = e.target.value; S0.preset = -1; sync(); redraw(); };
    $('lab-swap').onclick = () => { const t = S0.x; S0.x = S0.y; S0.y = t; S0.preset = -1; sync(); redraw(); };
    $('lab-color').onchange = e => { S0.color = e.target.value; redraw(); };
    $('lab-min').oninput = e => { S0.min = parseInt(e.target.value, 10); $('lab-min-v').textContent = S0.min; };
    $('lab-min').onchange = redraw;
    $('lab-shrink').onchange = e => { S0.shrink = e.target.checked; redraw(); };
    $('lab-qual').onchange = e => { S0.qual = e.target.checked; redraw(); };
    let timer = null;
    $('lab-q').oninput = e => { S0.q = e.target.value; clearTimeout(timer); timer = setTimeout(redraw, 250); };
    redraw();
  });
}

if (typeof GI.route === 'function') { try { GI.route('lab', render); } catch (e) { /* bound */ } }
})(window.GI || (window.GI = {}));
