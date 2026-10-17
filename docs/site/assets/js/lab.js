/* The Quant Footballer — the Player lab (#/lab, #/lab/<comp>/<pos>).
 *
 * Scatter any two player metrics against each other for one position group,
 * within one competition or across every competition on the site. Presets pick
 * the pairs that separate styles of player (volume against quality, creating
 * against scoring, activity against success); any metric in the catalogue can
 * go on either axis, on marker size or on colour. Medians split the chart into
 * quadrants; the players furthest into the good corner are labelled; a search
 * box highlights anyone. Across competitions, attacking rates can be put on one
 * footing with the pooled model's league scoring factors.
 *
 * Data: players_lab.json (column-oriented; one row per player per competition). */
(function (FH) {
'use strict';

const { C, PALETTE, esc, num, fmtMetric, plot, layout, tableHTML, sortableIn, setHTML, loadSite, pctPill } = FH;

const POS = { F: 'Forwards', M: 'Midfielders', D: 'Defenders', G: 'Goalkeepers', O: 'All outfield players' };
const PRESETS = {
  F: [
    ['npxg_90', 'xa_90', 'Threat: scoring against creating'],
    ['shots_90', 'xg_per_shot', 'Shot volume against shot quality'],
    ['npxg_90', 'finishing', 'Chances against finishing'],
    ['xg_per_shot', 'placement', 'Chance quality against shot placement'],
    ['dribbles_90', 'dribble_pct', 'Dribbling: volume against success'],
    ['touches_90', 'loss_per_100', 'Involvement against ball security'],
    ['npxg_xa_90', 'def_actions_90', 'Output against work off the ball']
  ],
  M: [
    ['xa_90', 'key_passes_90', 'Creation: quality against volume'],
    ['prog_actions_90', 'opp_half_passes_90', 'Progression: carrying against passing'],
    ['passes_90', 'pass_pct', 'Passing volume against security'],
    ['padj_tkl_int_90', 'ball_wins_90', 'Ball winning'],
    ['npxg_xa_90', 'padj_tkl_int_90', 'Two-way midfielders'],
    ['shot_creation_90', 'xa_per_kp', 'Creation volume against chance quality']
  ],
  D: [
    ['padj_tkl_int_90', 'duel_pct', 'Defending: activity against success'],
    ['aerials_90', 'aerial_pct', 'Aerial presence against dominance'],
    ['long_balls_90', 'long_ball_pct', 'Long distribution'],
    ['prog_actions_90', 'passes_90', 'Ball-playing defenders'],
    ['clearances_90', 'blocks_90', 'Defending the box'],
    ['crosses_90', 'xa_90', 'Attacking full-backs']
  ],
  G: [
    ['save_pct', 'goals_prevented_90', 'Shot stopping'],
    ['sweeper_90', 'high_claims_90', 'Command of the area'],
    ['passes_90', 'long_ball_pct', 'Distribution']
  ],
  O: [
    ['npxg_xa_90', 'padj_tkl_int_90', 'Attacking output against defending'],
    ['prog_actions_90', 'shot_creation_90', 'Progression against chance creation'],
    ['duels_90', 'duel_pct', 'Duels: volume against success']
  ]
};
const EXTRA_ADJ = ['npxg_xa_90', 'ga_90', 'shot_creation_90'];   // attacking rates adjusted like the catalogue's own

let LAB = null;           // the loaded window: { fields, idx, metrics, meta, comps, rows, window }
const LABS = {};          // by window tag
const WINDOWS = { season: 'This season, per competition', '365': 'Last 12 months, all competitions', ytd: 'Calendar year so far, all competitions' };
const SHRINK_K = 450;     // minutes of prior: a player's rate counts as much as the group median's after five full matches
const MU = {};            // group medians of the metrics on screen, for the shrinkage
let S = { win: 'season', comp: '', pos: 'F', min: 450, adj: true, shrink: true, preset: 0, x: '', y: '', size: 'minutes', color: 'comp', q: '' };

function prep(raw) {
  const idx = {};
  raw.fields.forEach((f, i) => { idx[f] = i; });
  const meta = {};
  raw.metrics.forEach(m => { meta[m.key] = m; });
  meta.minutes = { key: 'minutes', label: 'Minutes', fmt: 'int' };
  meta.age = { key: 'age', label: 'Age', fmt: 'int' };
  return { fields: raw.fields, idx: idx, meta: meta, metrics: raw.metrics, comps: raw.comps, adj: new Set((raw.adjusted_keys || []).concat(EXTRA_ADJ)), rows: raw.rows, min: raw.min_minutes, window: raw.window || null };
}

/* League adjustment applies whenever players from different competitions share
   the chart: across competitions in the season view, always in a calendar view
   (a player's window mixes competitions; the row carries his own blended factor). */
function adjOn() { return S.adj && (!S.comp || S.win !== 'season'); }

function raw(r, key) {
  const i = LAB.idx[key];
  if (i === undefined) return null;
  let v = r[i];
  if (v === null || v === undefined) return null;
  if (adjOn() && LAB.adj.has(key)) v = v * (LAB.idx.factor !== undefined ? (r[LAB.idx.factor] || 1) : ((LAB.comps[r[LAB.idx.comp]] || {}).factor || 1));
  return v;
}

/* Small samples shrunk towards the group median: (minutes × rate + K × median) /
   (minutes + K). Five matches of data move a player halfway from the median to
   his own rate; two thousand minutes leave him almost untouched. */
function val(r, key) {
  let v = raw(r, key);
  if (v === null || !S.shrink || key === 'minutes' || key === 'age' || MU[key] === undefined) return v;
  const m = r[LAB.idx.minutes] || 0;
  return (m * v + SHRINK_K * MU[key]) / (m + SHRINK_K);
}

function pool() {
  const I = LAB.idx;
  return LAB.rows.filter(r => {
    if (S.comp && r[I.comp] !== S.comp) return false;
    const p = r[I.position];
    if (S.pos === 'O' ? (p === 'G' || !p) : p !== S.pos) return false;
    return (r[I.minutes] || 0) >= S.min;
  });
}

function label(key) {
  const m = LAB.meta[key] || {}, tags = [];
  if (adjOn() && LAB.adj.has(key)) tags.push('adj.');
  if (S.shrink && key !== 'minutes' && key !== 'age') tags.push('shrunk');
  return (m.label || key) + (tags.length ? ' (' + tags.join(', ') + ')' : '');
}
function lower(key) { return !!(LAB.meta[key] || {}).lower; }
function fmt(key, v) { return fmtMetric(v, (LAB.meta[key] || {}).fmt || '2'); }

function median(a) { if (!a.length) return null; const s = a.slice().sort((x, y) => x - y); const k = s.length >> 1; return s.length % 2 ? s[k] : (s[k - 1] + s[k]) / 2; }
function stats(a) { const n = a.length; if (!n) return { m: 0, s: 1 }; const m = a.reduce((x, y) => x + y, 0) / n; const v = a.reduce((x, y) => x + (y - m) * (y - m), 0) / n; return { m: m, s: Math.sqrt(v) || 1 }; }
function pctRank(sorted, v) { let lo = 0, hi = sorted.length; while (lo < hi) { const mid = (lo + hi) >> 1; if (sorted[mid] < v) lo = mid + 1; else hi = mid; } let up = lo; while (up < sorted.length && sorted[up] === v) up++; return sorted.length ? 100 * ((lo + up) / 2) / sorted.length : null; }

function metricOptions(sel, scope) {
  const groups = {};
  LAB.metrics.forEach(m => {
    if (S.pos === 'G' ? m.scope === 'out' : m.scope === 'gk') return;
    (groups[m.group] = groups[m.group] || []).push(m);
  });
  let h = scope === 'size' ? '<option value="minutes">Minutes played</option><option value="">Same size</option>' : scope === 'color' ? '<option value="comp">Competition</option><option value="team">Club</option><option value="">One colour</option>' : '';
  Object.keys(groups).forEach(g => { h += '<optgroup label="' + esc(g) + '">' + groups[g].map(m => '<option value="' + esc(m.key) + '"' + (m.key === sel ? ' selected' : '') + '>' + esc(m.label) + '</option>').join('') + '</optgroup>'; });
  if (scope !== 'size' && scope !== 'color') h += '<optgroup label="Profile"><option value="age"' + (sel === 'age' ? ' selected' : '') + '>Age</option><option value="minutes"' + (sel === 'minutes' ? ' selected' : '') + '>Minutes</option></optgroup>';
  return h;
}

function syncControls() {
  const $ = id => document.getElementById(id);
  const comps = Object.keys(LAB.comps).sort((a, b) => LAB.comps[a].name.localeCompare(LAB.comps[b].name));
  $('lab-win').innerHTML = Object.keys(WINDOWS).map(k => '<option value="' + k + '"' + (k === S.win ? ' selected' : '') + '>' + esc(WINDOWS[k]) + '</option>').join('');
  $('lab-shrink').checked = S.shrink;
  $('lab-comp-label').textContent = S.win === 'season' ? 'Scope' : 'Main competition';
  $('lab-comp').innerHTML = '<option value="">All competitions (global)</option>' + comps.map(k => '<option value="' + esc(k) + '"' + (k === S.comp ? ' selected' : '') + '>' + esc(LAB.comps[k].name) + '</option>').join('');
  $('lab-pos').innerHTML = Object.keys(POS).map(k => '<option value="' + k + '"' + (k === S.pos ? ' selected' : '') + '>' + POS[k] + '</option>').join('');
  $('lab-preset').innerHTML = PRESETS[S.pos].map((p, i) => '<option value="' + i + '"' + (i === S.preset ? ' selected' : '') + '>' + esc(p[2]) + '</option>').join('') + '<option value="-1"' + (S.preset < 0 ? ' selected' : '') + '>Custom axes</option>';
  $('lab-x').innerHTML = metricOptions(S.x); $('lab-y').innerHTML = metricOptions(S.y);
  $('lab-size').innerHTML = metricOptions(S.size, 'size'); $('lab-size').value = S.size;
  $('lab-color').innerHTML = metricOptions(S.color, 'color'); $('lab-color').value = S.color;
  $('lab-min').value = S.min; $('lab-min-v').textContent = S.min + "'";
  $('lab-adj').checked = S.adj; $('lab-adj-wrap').style.display = (S.comp && S.win === 'season') ? 'none' : '';
  $('lab-q').value = S.q;
}

function applyPreset() {
  if (S.preset < 0) return;
  const p = PRESETS[S.pos][S.preset] || PRESETS[S.pos][0];
  S.x = p[0]; S.y = p[1];
}

function draw() {
  const I = LAB.idx;
  const base0 = pool();
  Object.keys(MU).forEach(k => delete MU[k]);
  [S.x, S.y, S.size, S.color].forEach(k => { if (k && LAB.idx[k] !== undefined && k !== 'minutes' && k !== 'age') { const a = base0.map(r => raw(r, k)).filter(v => v !== null); if (a.length) MU[k] = median(a); } });
  const rows = base0.filter(r => val(r, S.x) !== null && val(r, S.y) !== null);
  const scopeName = S.comp ? ((LAB.comps[S.comp] || {}).name || S.comp) : 'every competition';
  const W = LAB.window;
  setHTML('lab-sub', rows.length + ' ' + POS[S.pos].toLowerCase() + (S.win === 'season' ? ' in ' + esc(scopeName) : (S.comp ? ' whose main competition is ' + esc(scopeName) : '') + ', ' + esc(W.label.toLowerCase()) + ' (' + esc(W.start) + ' to ' + esc(W.end) + ')') + ' with ' + S.min + '+ minutes');
  if (S.win !== 'season' && W) {
    const present = new Set(rows.map(r => r[I.comp]));
    const late = Object.keys(LAB.comps).filter(k => present.has(k) && LAB.comps[k].first_detail && LAB.comps[k].first_detail > W.start)
      .sort((a, b) => LAB.comps[b].first_detail.localeCompare(LAB.comps[a].first_detail));
    setHTML('lab-cover', late.length ? '<div class="warn-banner">Match detail does not yet reach back to ' + esc(W.start) + ' for: ' +
      late.map(k => esc(LAB.comps[k].name) + ' (from ' + esc(LAB.comps[k].first_detail) + ')').join(', ') +
      '. Players from those competitions are compared on less of the window than the rest; the hourly fetch is filling last season in, newest first.</div>' : '');
  } else setHTML('lab-cover', '');
  if (rows.length < 3) { setHTML('lab-chart', '<div class="muted pad">Too few players for this view; lower the minutes or widen the scope.</div>'); setHTML('lab-table', ''); return; }
  const xs = rows.map(r => val(r, S.x)), ys = rows.map(r => val(r, S.y));
  const mx = median(xs), my = median(ys), sx = stats(xs), sy = stats(ys);
  const dirx = lower(S.x) ? -1 : 1, diry = lower(S.y) ? -1 : 1;
  const score = r => dirx * (val(r, S.x) - sx.m) / sx.s + diry * (val(r, S.y) - sy.m) / sy.s;
  const ranked = rows.map(r => ({ r: r, z: score(r) })).sort((a, b) => b.z - a.z);
  const q = S.q.trim().toLowerCase();
  const hits = q ? rows.filter(r => String(r[I.name]).toLowerCase().indexOf(q) >= 0) : [];
  const labelled = new Set(ranked.slice(0, 12).map(o => o.r).concat(hits));
  const sortedX = xs.slice().sort((a, b) => a - b), sortedY = ys.slice().sort((a, b) => a - b);

  // Size and colour.
  const sizeOf = (() => {
    if (!S.size) return () => 9;
    const v = rows.map(r => S.size === 'minutes' ? r[I.minutes] : val(r, S.size)).filter(x => x !== null);
    const lo = Math.min(...v), hi = Math.max(...v);
    return r => { const x = S.size === 'minutes' ? r[I.minutes] : val(r, S.size); return x === null ? 5 : 6 + 16 * (hi > lo ? (x - lo) / (hi - lo) : 0.5); };
  })();
  const groupKey = S.color === 'comp' ? r => r[I.comp] : S.color === 'team' ? r => r[I.team] : null;
  const traces = [];
  const hover = r => '<b>' + esc(r[I.name]) + '</b> · ' + esc(r[I.team]) + '<br>' + (I.mix !== undefined ? esc(r[I.mix]) : esc((LAB.comps[r[I.comp]] || {}).name || r[I.comp]) + ' · ' + r[I.minutes] + "'") + ' · age ' + (r[I.age] || '—') +
    '<br>' + esc(label(S.x)) + ': ' + fmt(S.x, val(r, S.x)) + ' (pct ' + Math.round((dirx > 0 ? pctRank(sortedX, val(r, S.x)) : 100 - pctRank(sortedX, val(r, S.x)))) + ')' +
    '<br>' + esc(label(S.y)) + ': ' + fmt(S.y, val(r, S.y)) + ' (pct ' + Math.round((diry > 0 ? pctRank(sortedY, val(r, S.y)) : 100 - pctRank(sortedY, val(r, S.y)))) + ')' +
    (S.shrink ? '<br><span style="color:#8b949e">unshrunk: ' + fmt(S.x, raw(r, S.x)) + ' · ' + fmt(S.y, raw(r, S.y)) + '</span>' : '');
  const base = (pts, name, color, extra) => Object.assign({
    type: 'scattergl', mode: 'markers', name: name, x: pts.map(r => val(r, S.x)), y: pts.map(r => val(r, S.y)),
    text: pts.map(hover), hovertemplate: '%{text}<extra></extra>', customdata: pts.map(r => r[I.comp] + '|' + r[I.player_id]),
    marker: { size: pts.map(sizeOf), color: color, opacity: 0.72, line: { color: '#0d1117', width: 0.5 } }
  }, extra || {});
  if (groupKey) {
    const counts = {};
    rows.forEach(r => { const k = groupKey(r); counts[k] = (counts[k] || 0) + 1; });
    const top = Object.keys(counts).sort((a, b) => counts[b] - counts[a]).slice(0, 8);
    top.forEach((k, i) => traces.push(base(rows.filter(r => groupKey(r) === k), S.color === 'comp' ? ((LAB.comps[k] || {}).name || k) : k, PALETTE[i % PALETTE.length])));
    const rest = rows.filter(r => top.indexOf(groupKey(r)) < 0);
    if (rest.length) traces.push(base(rest, 'Others', '#6e7681'));
  } else if (S.color) {
    const cv = rows.map(r => val(r, S.color));
    traces.push(base(rows, label(S.color), cv, { marker: { size: rows.map(sizeOf), color: cv, colorscale: 'RdBu', reversescale: !lower(S.color), opacity: 0.8,
      colorbar: { title: { text: label(S.color), side: 'right' }, thickness: 10, tickfont: { color: C.text2 } }, line: { color: '#0d1117', width: 0.5 } } }));
  } else {
    traces.push(base(rows, 'Players', C.blue));
  }
  if (hits.length) traces.push(Object.assign(base(hits, 'Search', '#ffffff'), { type: 'scatter', marker: { size: 16, color: 'rgba(0,0,0,0)', symbol: 'star-open', line: { color: '#ffffff', width: 2 } } }));
  const ann = Array.from(labelled).map(r => ({ x: val(r, S.x), y: val(r, S.y), text: esc(String(r[I.name]).split(' ').slice(-1)[0]), showarrow: false, yshift: 11, font: { size: 10, color: hits.indexOf(r) >= 0 ? '#ffffff' : '#c9d1d9' } }));
  plot('lab-chart', traces, layout({
    showlegend: !!groupKey, legend: { orientation: 'h', y: -0.14, font: { color: C.text2 } }, margin: { l: 65, r: 20, t: 20, b: 60 }, annotations: ann, hovermode: 'closest',
    xaxis: { title: label(S.x), zeroline: false, autorange: lower(S.x) ? 'reversed' : true },
    yaxis: { title: label(S.y), zeroline: false, autorange: lower(S.y) ? 'reversed' : true },
    shapes: [
      { type: 'line', x0: mx, x1: mx, yref: 'paper', y0: 0, y1: 1, line: { color: '#3d444d', dash: 'dot', width: 1 } },
      { type: 'line', y0: my, y1: my, xref: 'paper', x0: 0, x1: 1, line: { color: '#3d444d', dash: 'dot', width: 1 } }
    ]
  }));
  const el = document.getElementById('lab-chart');
  if (el && el.on) el.on('plotly_click', ev => { const d = ev.points && ev.points[0] && ev.points[0].customdata; if (d) { const [c, id] = d.split('|'); location.hash = '#/' + c + '/player/' + id; } });
  setHTML('lab-note', 'Dotted lines are the medians of this group. ' + (lower(S.x) || lower(S.y) ? 'Axes where less is better are reversed, so better is always up and to the right. ' : 'Better is up and to the right. ') +
    'Labelled: the twelve players furthest into that corner (sum of standard scores on both axes)' + (hits.length ? ', and your search' : '') + '. Click a dot to open the player.' +
    (adjOn() ? ' Attacking rates marked "adj." are multiplied by the league\'s scoring factor from the pooled model' + (S.win !== 'season' ? ' (for a calendar window, the minutes-weighted blend of the competitions the player played in).' : '.') : '') +
    (S.shrink ? ' Rates marked "shrunk" are pulled towards the group median by ' + SHRINK_K + " minutes of prior, so a player five matches in is not ranked on five matches alone; hover shows the raw figures." : ''));

  // The table: the whole group ranked by the same combined score.
  setHTML('lab-table', tableHTML([
    { label: '#', sortable: false }, { label: 'Player' }, { label: 'Club' }, { label: I.mix !== undefined ? 'Competitions (minutes)' : 'Competition' }, { label: 'Age', align: 'right' }, { label: 'Min', align: 'right' },
    { label: label(S.x), align: 'right' }, { label: 'Pct', align: 'right' }, { label: label(S.y), align: 'right' }, { label: 'Pct', align: 'right' }, { label: 'Combined', align: 'right', title: 'Sum of standard scores, better direction' }
  ], ranked.slice(0, 60).map((o, i) => {
    const r = o.r, vx = val(r, S.x), vy = val(r, S.y);
    const px = dirx > 0 ? pctRank(sortedX, vx) : 100 - pctRank(sortedX, vx), py = diry > 0 ? pctRank(sortedY, vy) : 100 - pctRank(sortedY, vy);
    return { _href: '#/' + r[I.comp] + '/player/' + r[I.player_id], cells: [
      { v: i + 1, cls: 'pos-cell' }, { v: r[I.name], html: '<a href="#/' + esc(r[I.comp]) + '/player/' + esc(r[I.player_id]) + '">' + esc(r[I.name]) + '</a>' },
      { v: r[I.team], html: esc(r[I.team]) }, { v: r[I.comp], html: I.mix !== undefined ? '<span class="muted-inline">' + esc(r[I.mix]) + '</span>' : esc((LAB.comps[r[I.comp]] || {}).name || r[I.comp]) },
      { v: r[I.age] || 0, html: r[I.age] || '—', align: 'right' }, { v: r[I.minutes], align: 'right' },
      { v: vx, html: fmt(S.x, vx), align: 'right' }, { v: px, html: pctPill(px), align: 'right' },
      { v: vy, html: fmt(S.y, vy), align: 'right' }, { v: py, html: pctPill(py), align: 'right' },
      { v: o.z, html: '<strong>' + num(o.z, 2) + '</strong>', align: 'right' }
    ] };
  }), { sticky: true }));
  sortableIn('lab-table');
  const hash = '#/lab/' + (S.comp || 'all') + '/' + S.pos + (S.win !== 'season' ? '/' + S.win : '');
  if (location.hash !== hash) history.replaceState(null, '', hash);
}

function loadWindow(win) {
  if (LABS[win]) return Promise.resolve(LABS[win]);
  return loadSite(win === 'season' ? 'players_lab.json' : 'players_lab_' + win + '.json').then(raw => {
    if (!raw || !(raw.rows || []).length) return null;
    LABS[win] = prep(raw);
    return LABS[win];
  });
}

function show(win) {
  return loadWindow(win).then(lab => {
    if (!lab) { setHTML('lab-chart', '<div class="muted pad">This view is not built yet.</div>'); setHTML('lab-table', ''); return false; }
    LAB = lab;
    if (S.comp && !LAB.comps[S.comp]) S.comp = '';
    return true;
  });
}

function renderLab(param) {
  const parts = String(param || '').split('/').filter(Boolean);
  if (parts[2] && WINDOWS[parts[2]]) S.win = parts[2]; else if (parts.length) S.win = 'season';
  show(S.win).then(ok => {
    if (!ok) return;
    if (parts[0]) S.comp = parts[0] === 'all' ? '' : (LAB.comps[parts[0]] ? parts[0] : '');
    if (parts[1] && POS[parts[1]]) S.pos = parts[1];
    S.min = (S.comp && S.win === 'season') ? Math.min(S.min, 270) : Math.max(S.min, 450);
    if (S.comp && S.color === 'comp') S.color = 'rating';
    if (!S.x) applyPreset();
    syncControls();
    const $ = id => document.getElementById(id);
    $('lab-win').onchange = e => { S.win = e.target.value; show(S.win).then(ok2 => { if (!ok2) return; S.min = (S.comp && S.win === 'season') ? 270 : 450; syncControls(); draw(); }); };
    $('lab-shrink').onchange = e => { S.shrink = e.target.checked; draw(); };
    $('lab-comp').onchange = e => { S.comp = e.target.value; S.min = (S.comp && S.win === 'season') ? 270 : 450; if (S.comp && S.color === 'comp') S.color = 'rating'; if (!S.comp && S.color === 'rating') S.color = 'comp'; syncControls(); draw(); };
    $('lab-pos').onchange = e => { S.pos = e.target.value; S.preset = 0; applyPreset(); syncControls(); draw(); };
    $('lab-preset').onchange = e => { S.preset = parseInt(e.target.value, 10); applyPreset(); syncControls(); draw(); };
    $('lab-x').onchange = e => { S.x = e.target.value; S.preset = -1; syncControls(); draw(); };
    $('lab-y').onchange = e => { S.y = e.target.value; S.preset = -1; syncControls(); draw(); };
    $('lab-size').onchange = e => { S.size = e.target.value; draw(); };
    $('lab-color').onchange = e => { S.color = e.target.value; draw(); };
    $('lab-min').oninput = e => { S.min = parseInt(e.target.value, 10); $('lab-min-v').textContent = S.min + "'"; };
    $('lab-min').onchange = () => draw();
    $('lab-adj').onchange = e => { S.adj = e.target.checked; draw(); };
    $('lab-swap').onclick = () => { const t = S.x; S.x = S.y; S.y = t; S.preset = -1; syncControls(); draw(); };
    $('lab-q').oninput = e => { S.q = e.target.value; clearTimeout(renderLab._t); renderLab._t = setTimeout(draw, 250); };
    draw();
  });
}

Object.assign(FH.GLOBAL_PAGES, { lab: renderLab });
})(window.FH);
