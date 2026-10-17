/* The Quant Footballer — the match centre (#/<comp>/match/<id>).
 *
 *   header and model line (before kick-off)
 *   match summary: goals, xG, npxG, xGOT, shots, big chances, possession
 *   expected result: every shot replayed as a coin flip weighted by its xG
 *   shot map: the full pitch, both sides, filterable; goal-mouth views
 *   xG race, momentum, event timeline
 *   who created the chances: xG and xA by player
 *   formations drawn on the pitch, rated
 *   team statistics by phase with derived ratios
 *   every player's full line
 *
 * Everything reads matches/<id>.json. Matches stored in the older, thinner
 * format have no team sheet, positions or goal-mouth data; each section says so
 * rather than disappearing. */
(function (FH) {
'use strict';

const { C, esc, num, pct, plot, layout, crest, playerLink, teamLink, teamHref, tableHTML, sortableIn, setHTML,
        statTile, probBar, statusChip, fmtDate, fmtTime, ROUND_LABELS, loadShard, D, comp } = FH;

const HOME = C.blue, AWAY = C.orange;
const OUTCOME = {
  goal: { label: 'Goal', color: C.green }, save: { label: 'Saved', color: '#79c0ff' }, post: { label: 'Woodwork', color: C.yellow },
  block: { label: 'Blocked', color: '#6e7681' }, miss: { label: 'Off target', color: '#c9d1d9' }
};
const BODY_SYMBOL = { 'right-foot': 'circle', 'left-foot': 'circle', head: 'triangle-up', other: 'square' };
const SITUATIONS = { all: 'All situations', open: 'Open play', set: 'Set pieces', penalty: 'Penalties' };

// ── shot helpers ───────────────────────────────────────────────────────────

function sideOf(s, m) { return s.is_home === undefined || s.is_home === null ? (s.team === m.home ? 'home' : 'away') : (s.is_home ? 'home' : 'away'); }
function outcomeOf(s) {
  const t = String(s.shot_type || s.type || '').toLowerCase();
  return t === 'goal' ? 'goal' : t === 'save' ? 'save' : t === 'post' ? 'post' : t.indexOf('block') >= 0 ? 'block' : 'miss';
}
function situationOf(s) {
  const t = String(s.situation || '').toLowerCase();
  if (t === 'penalty') return 'penalty';
  if (t.indexOf('set-piece') >= 0 || t === 'corner' || t === 'free-kick' || t === 'set-piece') return 'set';
  return 'open';
}
function nice(s) { return String(s || '').replace(/-/g, ' '); }
function minuteText(s) { return (s.time || 0) + (s.added_time ? '+' + s.added_time : '') + "'"; }
function onTarget(s) { const o = outcomeOf(s); return o === 'goal' || o === 'save'; }

function sideTotals(m) {
  const t = { home: null, away: null };
  ['home', 'away'].forEach(side => {
    const shots = (m.shots || []).filter(s => sideOf(s, m) === side);
    const sheet = ((m.team_stats || {})[side]) || {};
    const xg = shots.reduce((a, s) => a + (s.xg || 0), 0);
    const pens = shots.filter(s => situationOf(s) === 'penalty');
    t[side] = {
      goals: side === 'home' ? m.hs : m.as,
      xg: m.xg ? m.xg[side === 'home' ? 0 : 1] : xg,
      shot_xg: xg,
      npxg: xg - pens.reduce((a, s) => a + (s.xg || 0), 0),
      xgot: sheet.expectedGoalsOnTarget !== undefined ? sheet.expectedGoalsOnTarget : shots.filter(onTarget).reduce((a, s) => a + (s.xgot || 0), 0),
      shots: shots.length, sot: shots.filter(onTarget).length,
      big: sheet.bigChanceCreated, poss: sheet.ballPossession,
      per_shot: shots.length ? xg / shots.length : null
    };
  });
  return t;
}

// ── the expected result ────────────────────────────────────────────────────

function rng(seed) {                       // mulberry32: the same match always gives the same numbers
  let a = seed >>> 0;
  return () => { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
}

/* Each shot scores with probability equal to its xG, independently. Shots from
   one attack (a save and the rebound) are treated as separate chances, which
   overstates how often a side scores twice from one move; the result is read as
   "what the chances were worth", not a replay. */
function simulate(m, n) {
  const rand = rng(parseInt(m.id, 10) || 7);
  const h = [], a = [];
  (m.shots || []).forEach(s => (sideOf(s, m) === 'home' ? h : a).push(Math.min(Math.max(s.xg || 0, 0), 0.99)));
  const grid = Array.from({ length: 7 }, () => new Array(7).fill(0));
  let hw = 0, dr = 0, aw = 0;
  for (let i = 0; i < n; i++) {
    let gh = 0, ga = 0;
    for (const p of h) if (rand() < p) gh++;
    for (const p of a) if (rand() < p) ga++;
    if (gh > ga) hw++; else if (gh === ga) dr++; else aw++;
    grid[Math.min(gh, 6)][Math.min(ga, 6)]++;
  }
  return { h: hw / n, d: dr / n, a: aw / n, grid: grid.map(r => r.map(v => v / n)) };
}

function renderExpected(m) {
  if (!(m.shots || []).length) { setHTML('mc-expected', '<div class="muted pad">No shot data for this match.</div>'); return; }
  const sim = simulate(m, 20000);
  const actual = m.hs > m.as ? 'h' : m.hs === m.as ? 'd' : 'a';
  const pActual = sim[actual];
  const verdict = pActual >= 0.5 ? 'The result matched the chances.' : pActual >= 0.25 ? 'The result was plausible on the chances, not the most likely outcome.' : 'The result went against the run of the chances.';
  setHTML('mc-expected', '<div class="pad">' + probBar(sim) +
    '<div class="xr-legend"><span><b style="color:' + HOME + '">' + esc(m.home) + '</b> ' + pct(sim.h) + '</span><span>Draw ' + pct(sim.d) + '</span><span><b style="color:' + AWAY + '">' + esc(m.away) + '</b> ' + pct(sim.a) + '</span></div>' +
    '<p class="muted-inline xr-note">' + esc(verdict) + ' The actual result had a ' + pct(pActual) + ' chance given every shot\'s xG, replayed 20,000 times. Rebounds count as separate chances, so this slightly overstates multi-goal outcomes.</p></div>' +
    '<div id="mc-scoregrid" style="height:300px"></div>');
  const n = 6, z = [], text = [];
  for (let i = 0; i < n; i++) { z.push([]); text.push([]); for (let j = 0; j < n; j++) { const v = sim.grid[i][j]; z[i].push(v); text[i].push(v >= 0.005 ? Math.round(v * 100) + '%' : ''); } }
  plot('mc-scoregrid', [{
    type: 'heatmap', z: z, x: [0, 1, 2, 3, 4, 5].map(String), y: [0, 1, 2, 3, 4, 5].map(String), text: text, texttemplate: '%{text}',
    colorscale: [[0, 'rgba(22,27,34,1)'], [1, '#3fb950']], showscale: false, hovertemplate: esc(m.home) + ' %{y} – %{x} ' + esc(m.away) + ': %{z:.1%}<extra></extra>'
  }], layout({
    margin: { l: 60, r: 10, t: 10, b: 45 }, xaxis: { title: esc(m.away) + ' goals', fixedrange: true }, yaxis: { title: esc(m.home) + ' goals', fixedrange: true },
    shapes: (m.hs !== null && m.hs <= 5 && m.as <= 5) ? [{ type: 'rect', x0: m.as - 0.5, x1: m.as + 0.5, y0: m.hs - 0.5, y1: m.hs + 0.5, line: { color: '#e6edf3', width: 2 } }] : []
  }));
}

// ── the pitch ──────────────────────────────────────────────────────────────

/* A full horizontal pitch on a 0-100 × 0-100 grid (105 × 68 m). */
function fullPitch() {
  const L = { color: '#3d444d', width: 1 };
  const shapes = [
    { type: 'rect', x0: 0, x1: 100, y0: 0, y1: 100, line: L },
    { type: 'line', x0: 50, x1: 50, y0: 0, y1: 100, line: L },
    { type: 'circle', x0: 50 - 8.71, x1: 50 + 8.71, y0: 50 - 13.46, y1: 50 + 13.46, line: L },
    { type: 'circle', x0: 49.6, x1: 50.4, y0: 49.4, y1: 50.6, line: L, fillcolor: '#3d444d' }
  ];
  [0, 100].forEach(end => {
    const d = end === 0 ? 1 : -1;
    shapes.push({ type: 'rect', x0: end, x1: end + d * 15.71, y0: 20.35, y1: 79.65, line: L });
    shapes.push({ type: 'rect', x0: end, x1: end + d * 5.24, y0: 36.53, y1: 63.47, line: L });
    shapes.push({ type: 'rect', x0: end, x1: end - d * 1.6, y0: 44.6, y1: 55.4, line: { color: '#8b949e', width: 2 } });
    shapes.push({ type: 'circle', x0: end + d * 10.48 - 0.4, x1: end + d * 10.48 + 0.4, y0: 49.4, y1: 50.6, line: L, fillcolor: '#3d444d' });
    const ax = end + d * 15.71, bx = end + d * 19.2;
    shapes.push({ type: 'path', path: 'M ' + ax + ' 38.2 Q ' + bx + ' 50 ' + ax + ' 61.8', line: L });
  });
  return shapes;
}

function pitchLayout(extra) {
  return layout(Object.assign({
    shapes: fullPitch(), plot_bgcolor: 'rgba(46,160,67,0.04)',
    xaxis: { range: [-3, 103], visible: false, fixedrange: true },
    yaxis: { range: [-3, 103], visible: false, fixedrange: true, scaleanchor: 'x', scaleratio: 0.648 },
    margin: { l: 8, r: 8, t: 8, b: 8 }
  }, extra || {}));
}

/* Sofascore gives a shot's distance from the goal line (x, % of length) and its
   position across (y, where higher is the shooter's left). The home side attacks
   the right-hand goal, the away side the left. */
function shotXY(s, side) {
  return side === 'home' ? [100 - s.x, s.y] : [s.x, 100 - s.y];
}

function shotHover(s, m) {
  return '<b>' + esc(s.player_name || s.player || '') + '</b> (' + esc(sideOf(s, m) === 'home' ? m.home : m.away) + ') ' + minuteText(s) + '<br>' +
    OUTCOME[outcomeOf(s)].label + ' · ' + nice(s.body_part) + ' · ' + nice(s.situation) + '<br>xG ' + num(s.xg, 2) +
    (onTarget(s) && s.xgot ? ' · xGOT ' + num(s.xgot, 2) : '') + (s.goalkeeper && onTarget(s) ? '<br>keeper ' + esc(s.goalkeeper) : '');
}

function renderShotMap(m) {
  const team = document.getElementById('mc-sm-team').value, sit = document.getElementById('mc-sm-sit').value, res = document.getElementById('mc-sm-res').value;
  const shots = (m.shots || []).filter(s => s.x !== null && s.x !== undefined)
    .filter(s => team === 'both' || sideOf(s, m) === team)
    .filter(s => sit === 'all' || situationOf(s) === sit)
    .filter(s => res === 'all' || (res === 'target' ? onTarget(s) : outcomeOf(s) === 'goal'));
  const traces = Object.keys(OUTCOME).map(k => {
    const pts = shots.filter(s => outcomeOf(s) === k);
    const xy = pts.map(s => shotXY(s, sideOf(s, m)));
    return {
      type: 'scatter', mode: 'markers', name: OUTCOME[k].label, x: xy.map(p => p[0]), y: xy.map(p => p[1]),
      text: pts.map(s => shotHover(s, m)), hovertemplate: '%{text}<extra></extra>',
      marker: {
        size: pts.map(s => 8 + Math.sqrt(Math.max(s.xg || 0, 0.01)) * 34), color: OUTCOME[k].color,
        opacity: k === 'goal' ? 1 : 0.78, symbol: pts.map(s => BODY_SYMBOL[s.body_part] || 'circle'),
        line: { color: pts.map(s => (sideOf(s, m) === 'home' ? HOME : AWAY)), width: 2 }
      }
    };
  }).filter(t => t.x.length);
  const goals = shots.filter(s => outcomeOf(s) === 'goal');
  const ann = goals.map(s => { const p = shotXY(s, sideOf(s, m)); return { x: p[0], y: p[1], text: esc((s.player_name || '').split(' ').slice(-1)[0]) + ' ' + num(s.xg, 2), showarrow: false, yshift: 16, font: { size: 10, color: '#e6edf3' } }; });
  ann.push({ x: 75, y: 104, text: esc(m.home) + ' attacking →', showarrow: false, font: { color: HOME, size: 11 } });
  ann.push({ x: 25, y: 104, text: '← ' + esc(m.away) + ' attacking', showarrow: false, font: { color: AWAY, size: 11 } });
  plot('mc-shotmap', traces.length ? traces : [{ type: 'scatter', x: [], y: [] }], pitchLayout({
    annotations: ann, showlegend: true, legend: { orientation: 'h', y: -0.04, x: 0.5, xanchor: 'center', font: { color: C.text2 } },
    yaxis: { range: [-3, 108], visible: false, fixedrange: true, scaleanchor: 'x', scaleratio: 0.648 }
  }));
  const tot = s => s.reduce((a, x) => a + (x.xg || 0), 0);
  setHTML('mc-sm-sum', shots.length + ' shots · ' + num(tot(shots), 2) + ' xG · ' + shots.filter(onTarget).length + ' on target · ' + goals.length + ' goals' +
    ' · average ' + num(shots.length ? tot(shots) / shots.length : 0, 2) + ' xG per shot');
}

/* Where the shots on target (and the near misses) crossed the goal line, from
   the shooter's point of view. */
function renderGoalMouth(elId, m, side) {
  const shots = (m.shots || []).filter(s => sideOf(s, m) === side && s.gm_y !== undefined && s.gm_y !== null);
  if (!shots.length) { setHTML(elId, '<div class="muted pad">No goal-mouth data' + ((m.shots || []).length ? ' (older match format).' : '.') + '</div>'); return; }
  const traces = Object.keys(OUTCOME).map(k => {
    const pts = shots.filter(s => outcomeOf(s) === k && s.gm_z <= 75 && s.gm_y >= 36 && s.gm_y <= 64);
    return {
      type: 'scatter', mode: 'markers', name: OUTCOME[k].label, x: pts.map(s => 100 - s.gm_y), y: pts.map(s => s.gm_z),
      text: pts.map(s => shotHover(s, m)), hovertemplate: '%{text}<extra></extra>',
      marker: { size: pts.map(s => 9 + Math.sqrt(Math.max(s.xgot || s.xg || 0, 0.01)) * 26), color: OUTCOME[k].color, opacity: 0.9, line: { color: '#0d1117', width: 1 } }
    };
  }).filter(t => t.x.length);
  const frame = { color: '#e6edf3', width: 4 };
  plot(elId, traces, layout({
    showlegend: false, margin: { l: 8, r: 8, t: 8, b: 8 },
    shapes: [
      { type: 'line', x0: 36, x1: 64, y0: 0, y1: 0, line: { color: '#3d444d', width: 1 } },
      { type: 'line', x0: 44.6, x1: 44.6, y0: 0, y1: 38, line: frame }, { type: 'line', x0: 55.4, x1: 55.4, y0: 0, y1: 38, line: frame },
      { type: 'line', x0: 44.6, x1: 55.4, y0: 38, y1: 38, line: frame },
      { type: 'rect', x0: 44.6, x1: 55.4, y0: 0, y1: 38, line: { width: 0 }, fillcolor: 'rgba(255,255,255,0.03)' }
    ],
    xaxis: { range: [37, 63], visible: false, fixedrange: true },
    yaxis: { range: [-4, 78], visible: false, fixedrange: true, scaleanchor: 'x', scaleratio: 0.0947 }
  }));
}

// ── the flow of the match ──────────────────────────────────────────────────

function renderRace(m) {
  const list = (m.shots || []).filter(s => s.time !== null && s.time !== undefined).slice().sort((a, b) => (a.time + (a.added_time || 0) / 100) - (b.time + (b.added_time || 0) / 100));
  if (!list.length) { setHTML('mc-race', '<div class="muted pad">No shot data.</div>'); return; }
  const maxT = Math.max(90, ...list.map(s => s.time || 0)) + 1;
  const traces = [];
  ['home', 'away'].forEach(side => {
    const own = list.filter(s => sideOf(s, m) === side);
    const xs = [0], ys = [0]; let cum = 0;
    const px = [], py = [], pt = [], ps = [], pc = [];
    own.forEach(s => { cum += s.xg || 0; xs.push(s.time); ys.push(cum); px.push(s.time); py.push(cum); pt.push(shotHover(s, m)); ps.push(6 + Math.sqrt(s.xg || 0.01) * 18); pc.push(outcomeOf(s) === 'goal' ? C.green : (side === 'home' ? HOME : AWAY)); });
    xs.push(maxT); ys.push(cum);
    const col = side === 'home' ? HOME : AWAY, name = side === 'home' ? m.home : m.away;
    traces.push({ type: 'scatter', mode: 'lines', name: name, x: xs, y: ys, line: { shape: 'hv', color: col, width: 2.5 }, hoverinfo: 'skip' });
    traces.push({ type: 'scatter', mode: 'markers', name: name + ' shots', showlegend: false, x: px, y: py, text: pt, hovertemplate: '%{text}<extra></extra>',
      marker: { size: ps, color: pc, line: { color: '#0d1117', width: 1 } } });
  });
  plot('mc-race', traces, layout({
    showlegend: true, legend: { orientation: 'h', y: 1.12, font: { color: C.text2 } },
    xaxis: { title: 'Minute', range: [0, maxT] }, yaxis: { title: 'Cumulative xG', rangemode: 'tozero' },
    shapes: [{ type: 'line', x0: 45, x1: 45, yref: 'paper', y0: 0, y1: 1, line: { color: '#3d444d', dash: 'dot', width: 1 } }],
    margin: { l: 55, r: 20, t: 30, b: 45 }
  }));
}

function renderTimeline(m) {
  const inc = (m.incidents || []).filter(i => ['goal', 'card', 'substitution'].indexOf(String(i.incident_type || '').toLowerCase()) >= 0);
  if (!inc.length) { setHTML('mc-timeline', '<div class="muted pad">No events recorded.</div>'); return; }
  const kind = i => { const t = String(i.incident_type).toLowerCase(), c = String(i.incident_class || '').toLowerCase(); return t === 'goal' ? 'goal' : t === 'card' ? (c.indexOf('red') >= 0 ? 'red' : 'yellow') : 'sub'; };
  const style = { goal: ['Goal', 'star', C.green, 16], yellow: ['Yellow card', 'square', C.yellow, 11], red: ['Red card', 'square', C.red, 12], sub: ['Substitution', 'triangle-up', '#8b949e', 9] };
  const label = i => {
    const k = kind(i);
    if (k === 'sub') return '⇄ ' + esc(i.player_in || '') + ' for ' + esc(i.player_out || '');
    return style[k][0] + ': ' + esc(i.player_name || '') + (k === 'goal' && i.assist ? ' (assist ' + esc(i.assist) + ')' : '') + (k === 'goal' && i.home_score !== undefined ? ' → ' + i.home_score + '–' + i.away_score : '');
  };
  const traces = Object.keys(style).map(k => {
    const pts = inc.filter(i => kind(i) === k);
    return { type: 'scatter', mode: 'markers', name: style[k][0], x: pts.map(i => (i.time || 0) + (i.added_time || 0) * 0.1), y: pts.map(i => (i.is_home ? 1 : -1) * (k === 'sub' ? 0.45 : 1)),
      text: pts.map(i => minuteText(i) + ' ' + label(i)), hovertemplate: '%{text}<extra></extra>',
      marker: { symbol: style[k][1], size: style[k][3], color: style[k][2], line: { color: '#0d1117', width: 1 } } };
  }).filter(t => t.x.length);
  const maxT = Math.max(90, ...inc.map(i => i.time || 0)) + 2;
  plot('mc-timeline', traces, layout({
    showlegend: true, legend: { orientation: 'h', y: -0.25, font: { color: C.text2 } }, margin: { l: 90, r: 20, t: 10, b: 40 },
    xaxis: { range: [0, maxT], title: '', dtick: 15 }, yaxis: { range: [-1.6, 1.6], tickvals: [1, -1], ticktext: [esc(m.home), esc(m.away)], zeroline: false, fixedrange: true },
    shapes: [{ type: 'line', x0: 0, x1: maxT, y0: 0, y1: 0, line: { color: '#3d444d', width: 1 } }, { type: 'line', x0: 45, x1: 45, y0: -1.5, y1: 1.5, line: { color: '#3d444d', dash: 'dot', width: 1 } }]
  }));
}

// ── players ────────────────────────────────────────────────────────────────

function renderContributions(m) {
  const rows = [];
  ['home', 'away'].forEach(side => ((m.lineups || {})[side] || []).forEach(e => { if ((e.xg || 0) + (e.xa || 0) >= 0.03) rows.push(Object.assign({ side: side }, e)); }));
  if (!rows.length) { setHTML('mc-contrib', '<div class="muted pad">No per-player xG for this match.</div>'); return; }
  rows.sort((a, b) => ((a.xg || 0) + (a.xa || 0)) - ((b.xg || 0) + (b.xa || 0)));
  const top = rows.slice(-16);
  const names = top.map(r => r.n + (r.g ? ' ' + '⚽'.repeat(Math.min(r.g, 3)) : '') + (r.a ? ' 🅰' : ''));
  const col = top.map(r => r.side === 'home' ? HOME : AWAY);
  document.getElementById('mc-contrib').style.height = Math.max(220, 40 + top.length * 24) + 'px';
  plot('mc-contrib', [
    { type: 'bar', orientation: 'h', name: 'xG (shots taken)', y: names, x: top.map(r => r.xg || 0), marker: { color: col }, hovertemplate: '%{y}: %{x:.2f} xG<extra></extra>' },
    { type: 'bar', orientation: 'h', name: 'xA (chances created)', y: names, x: top.map(r => r.xa || 0), marker: { color: col, opacity: 0.45, pattern: { shape: '/' } }, hovertemplate: '%{y}: %{x:.2f} xA<extra></extra>' }
  ], layout({ barmode: 'stack', showlegend: true, legend: { orientation: 'h', y: 1.06, font: { color: C.text2 } }, margin: { l: 170, r: 20, t: 30, b: 35 }, xaxis: { title: 'Expected goals + expected assists' }, yaxis: { automargin: true } }));
}

/* Starters placed by the formation string: the goalkeeper, then each line in the
   order Sofascore lists it (right to left from the team's point of view). */
function formationPoints(m, side) {
  const list = ((m.lineups || {})[side] || []).filter(e => e.start);
  const f = ((m.formation || {})[side] || '');
  const lines = f.split('-').map(n => parseInt(n, 10)).filter(n => n > 0);
  const gk = list.filter(e => e.pos === 'G');
  const out = list.filter(e => e.pos !== 'G');
  if (list.length !== 11 || gk.length !== 1 || lines.reduce((a, b) => a + b, 0) !== 10) return null;
  const pts = [];
  const home = side === 'home';
  pts.push({ e: gk[0], x: home ? 4 : 96, y: 50 });
  let k = 0;
  lines.forEach((n, li) => {
    const depth = 4 + (li + 1) * (44 / (lines.length + 0.6));
    for (let j = 0; j < n; j++, k++) {
      const span = Math.min(76, 24 * (n - 1));             // a two-man line sits inside, a back five spans the pitch
      const across = n === 1 ? 50 : 50 - span / 2 + j * (span / (n - 1));
      pts.push({ e: out[k], x: home ? depth : 100 - depth, y: home ? across : 100 - across });
    }
  });
  return pts;
}

function ratingColor(r) {
  if (r === undefined || r === null) return '#6e7681';
  if (r >= 8) return '#238636'; if (r >= 7.3) return '#3fb950'; if (r >= 6.8) return '#d29922'; if (r >= 6.3) return '#f97316'; return '#f85149';
}

function renderFormations(m) {
  const ph = formationPoints(m, 'home'), pa = formationPoints(m, 'away');
  if (!ph && !pa) { setHTML('mc-formation', '<div class="muted pad">No formation for this match (older match format); the lineups are listed below.</div>'); return; }
  const traces = [];
  [['home', ph], ['away', pa]].forEach(([side, pts]) => {
    if (!pts) return;
    traces.push({
      type: 'scatter', mode: 'markers+text', x: pts.map(p => p.x), y: pts.map(p => p.y), text: pts.map(p => p.e.no || ''),
      textfont: { color: '#0d1117', size: 10 }, textposition: 'middle center', hoverinfo: 'text', showlegend: false,
      hovertext: pts.map(p => esc(p.e.n) + ' · ' + (p.e.pos || '') + ' · ' + (p.e.min || 0) + "' · rating " + (p.e.rt !== undefined ? num(p.e.rt, 1) : '—') + (p.e.g ? ' · ' + p.e.g + ' goal' + (p.e.g > 1 ? 's' : '') : '') + (p.e.a ? ' · ' + p.e.a + ' assist' : '')),
      marker: { size: 24, color: pts.map(p => ratingColor(p.e.rt)), line: { color: side === 'home' ? HOME : AWAY, width: 3 } }
    });
    traces.push({
      type: 'scatter', mode: 'text', x: pts.map(p => p.x), y: pts.map(p => p.y - 7.5), hoverinfo: 'skip', showlegend: false,
      text: pts.map(p => esc(String(p.e.n || '').split(' ').slice(-1)[0]) + (p.e.rt !== undefined ? ' ' + num(p.e.rt, 1) : '')), textfont: { color: '#c9d1d9', size: 10 }
    });
  });
  const ann = [];
  if ((m.formation || {}).home) ann.push({ x: 25, y: 104, text: esc(m.home) + ' · ' + esc(m.formation.home), showarrow: false, font: { color: HOME, size: 11 } });
  if ((m.formation || {}).away) ann.push({ x: 75, y: 104, text: esc(m.formation.away) + ' · ' + esc(m.away), showarrow: false, font: { color: AWAY, size: 11 } });
  plot('mc-formation', traces, pitchLayout({ annotations: ann, yaxis: { range: [-3, 108], visible: false, fixedrange: true, scaleanchor: 'x', scaleratio: 0.648 } }));
}

function benchList(m, side) {
  const list = ((m.lineups || {})[side] || []);
  const subs = list.filter(e => !e.start && (e.min || 0) > 0);
  const unused = list.filter(e => !e.start && !(e.min > 0));
  const missing = ((m.missing || {})[side] || []);
  const row = e => '<div class="lu-row"><span class="lu-no">' + esc(e.no || '') + '</span><span class="pos-badge pos-' + esc(e.pos || '') + '">' + esc(e.pos || '') + '</span><span class="lu-name">' + playerLink(e.id, e.n) + '</span><span class="lu-min">' + (e.min ? e.min + "'" : '') + '</span><span class="lu-rt">' + (e.rt !== undefined ? num(e.rt, 1) : '') + '</span></div>';
  const starters = list.filter(e => e.start);
  return (!(m.formation || {})[side] && starters.length ? '<div class="lu-sub-head">Starting XI</div>' + starters.map(row).join('') : '') +
    (subs.length ? '<div class="lu-sub-head">Came on</div>' + subs.map(row).join('') : '') +
    (unused.length ? '<div class="lu-sub-head">Unused</div>' + unused.map(row).join('') : '') +
    (missing.length ? '<div class="lu-sub-head">Missing</div>' + missing.map(x => '<div class="lu-missing"><span>' + esc(x.n) + '</span><span>' + esc(String(x.reason) === '3' ? 'suspended' : String(x.type || '') === 'doubtful' ? 'doubtful' : 'injured') + '</span></div>').join('') : '');
}

function frac(a, b) { return (a === undefined && b === undefined) ? null : (a || 0) + '/' + (b || 0); }
function ratio(a, b) { return b ? Math.round(100 * (a || 0) / b) + '%' : '—'; }

function renderPlayerTable(m) {
  const filt = (document.getElementById('mc-pt-team') || {}).value || 'both';
  const rows = [];
  ['home', 'away'].forEach(side => { if (filt !== 'both' && filt !== side) return; ((m.lineups || {})[side] || []).forEach(e => { if ((e.min || 0) > 0) rows.push(Object.assign({ side: side, team: side === 'home' ? m.home : m.away }, e)); }); });
  if (!rows.length) { setHTML('mc-players', '<div class="muted pad">No player statistics for this match.</div>'); return; }
  const v = x => (x === undefined || x === null ? '' : x);
  setHTML('mc-players', tableHTML([
    { label: 'Player' }, { label: 'Pos' }, { label: 'Min', align: 'right' }, { label: 'Rating', align: 'right' },
    { label: 'G', align: 'right' }, { label: 'A', align: 'right' }, { label: 'xG', align: 'right' }, { label: 'xA', align: 'right' },
    { label: 'Sh', align: 'right', title: 'Shots (on target)' }, { label: 'KP', align: 'right', title: 'Key passes' }, { label: 'BC', align: 'right', title: 'Big chances created' },
    { label: 'Passes', align: 'right', title: 'Accurate / attempted' }, { label: 'Pass %', align: 'right' }, { label: 'Long', align: 'right', title: 'Accurate long balls / attempted' },
    { label: 'Crosses', align: 'right' }, { label: 'Touch', align: 'right' }, { label: 'Prog', align: 'right', title: 'Progressive carries' },
    { label: 'Drib', align: 'right', title: 'Dribbles won / attempted' }, { label: 'Lost', align: 'right', title: 'Possession lost' },
    { label: 'Duels', align: 'right', title: 'Won / contested' }, { label: 'Aerial', align: 'right', title: 'Won / contested' },
    { label: 'Tkl', align: 'right', title: 'Tackles won / attempted' }, { label: 'Int', align: 'right' }, { label: 'Rec', align: 'right', title: 'Recoveries' },
    { label: 'Clr', align: 'right' }, { label: 'Blk', align: 'right' }, { label: 'Fouls', align: 'right', title: 'Committed / suffered' },
    { label: 'Saves', align: 'right' }, { label: 'GP', align: 'right', title: 'Goals prevented (xGOT faced − goals conceded)' },
    { label: 'km', align: 'right' }, { label: 'Top', align: 'right', title: 'Top speed, km/h' }
  ], rows.map(e => ({ cells: [
    { v: e.n, html: '<span class="team-dot" style="background:' + (e.side === 'home' ? HOME : AWAY) + '"></span>' + playerLink(e.id, e.n) + (e.start ? '' : ' <span class="muted-inline">sub</span>') },
    { v: e.pos || '', html: '<span class="pos-badge pos-' + esc(e.pos || '') + '">' + esc(e.pos || '') + '</span>' },
    { v: e.min || 0, align: 'right' }, { v: e.rt || 0, html: e.rt !== undefined ? '<span class="rt-chip" style="background:' + ratingColor(e.rt) + '">' + num(e.rt, 1) + '</span>' : '', align: 'right' },
    { v: e.g || 0, html: v(e.g) || '', align: 'right' }, { v: e.a || 0, html: v(e.a) || '', align: 'right' },
    { v: e.xg || 0, html: e.xg ? num(e.xg, 2) : '', align: 'right' }, { v: e.xa || 0, html: e.xa ? num(e.xa, 2) : '', align: 'right' },
    { v: e.sh || 0, html: e.sh ? e.sh + ' (' + (e.sot || 0) + ')' : '', align: 'right' }, { v: e.kp || 0, html: v(e.kp), align: 'right' }, { v: e.bc || 0, html: v(e.bc), align: 'right' },
    { v: e.pt || 0, html: e.pt ? frac(e.pa, e.pt) : '', align: 'right' }, { v: e.pt ? (e.pa || 0) / e.pt : 0, html: e.pt ? ratio(e.pa, e.pt) : '', align: 'right' },
    { v: e.lbt || 0, html: e.lbt ? frac(e.lb, e.lbt) : '', align: 'right' }, { v: e.crst || 0, html: e.crst ? frac(e.crs, e.crst) : '', align: 'right' },
    { v: e.tch || 0, html: v(e.tch), align: 'right' }, { v: e.pc || 0, html: v(e.pc), align: 'right' },
    { v: e.dra || 0, html: e.dra ? frac(e.drw, e.dra) : '', align: 'right' }, { v: e.pl || 0, html: v(e.pl), align: 'right' },
    { v: (e.dw || 0) + (e.dl || 0), html: (e.dw || e.dl) ? frac(e.dw, (e.dw || 0) + (e.dl || 0)) : '', align: 'right' },
    { v: (e.aw || 0) + (e.al || 0), html: (e.aw || e.al) ? frac(e.aw, (e.aw || 0) + (e.al || 0)) : '', align: 'right' },
    { v: e.tk || 0, html: e.tk ? frac(e.tw, e.tk) : '', align: 'right' }, { v: e.int || 0, html: v(e.int), align: 'right' }, { v: e.rec || 0, html: v(e.rec), align: 'right' },
    { v: e.clr || 0, html: v(e.clr), align: 'right' }, { v: e.blk || 0, html: v(e.blk), align: 'right' },
    { v: e.fl || 0, html: (e.fl || e.fld) ? (e.fl || 0) + '/' + (e.fld || 0) : '', align: 'right' },
    { v: e.sv || 0, html: v(e.sv), align: 'right' }, { v: e.gp || 0, html: e.gp !== undefined && e.pos === 'G' ? num(e.gp, 2) : '', align: 'right' },
    { v: e.km || 0, html: e.km ? num(e.km, 1) : '', align: 'right' }, { v: e.ts || 0, html: e.ts ? num(e.ts, 1) : '', align: 'right' }
  ] })), { sticky: true }));
  sortableIn('mc-players');
}

// ── the team sheet ─────────────────────────────────────────────────────────

const SHEET = [
  ['Attack', [['expectedGoals', 'Expected goals', '2'], ['expectedGoalsOnTarget', 'xG on target (xGOT)', '2'], ['bigChanceCreated', 'Big chances'], ['bigChanceScored', 'Big chances scored'], ['bigChanceMissed', 'Big chances missed', 'lower'],
    ['totalShotsOnGoal', 'Shots'], ['shotsOnGoal', 'On target'], ['shotsOffGoal', 'Off target', 'lower'], ['blockedScoringAttempt', 'Blocked'], ['totalShotsInsideBox', 'Shots inside the box'], ['totalShotsOutsideBox', 'Shots outside the box'],
    ['hitWoodwork', 'Woodwork'], ['touchesInOppBox', 'Touches in the opposition box'], ['cornerKicks', 'Corners'], ['offsides', 'Offsides', 'lower']]],
  ['Possession and passing', [['ballPossession', 'Possession', '%'], ['passes', 'Passes'], ['accuratePasses', 'Accurate passes'], ['finalThirdEntries', 'Final-third entries'],
    ['finalThirdPhaseStatistic', 'Final-third passes', 'ratio'], ['accurateLongBalls', 'Long balls', 'ratio'], ['accurateCross', 'Crosses', 'ratio'], ['accurateThroughBall', 'Through balls'], ['dispossessed', 'Dispossessed', 'lower']]],
  ['Duels and defending', [['duelWonPercent', 'Duels won', '%'], ['groundDuelsPercentage', 'Ground duels', 'ratio'], ['aerialDuelsPercentage', 'Aerial duels', 'ratio'], ['dribblesPercentage', 'Dribbles', 'ratio'],
    ['totalTackle', 'Tackles'], ['wonTacklePercent', 'Tackles won', 'ratio'], ['interceptionWon', 'Interceptions'], ['ballRecovery', 'Recoveries'], ['totalClearance', 'Clearances'],
    ['fouls', 'Fouls', 'lower'], ['yellowCards', 'Yellow cards', 'lower'], ['redCards', 'Red cards', 'lower']]],
  ['Goalkeeping', [['goalkeeperSaves', 'Saves'], ['goalsPrevented', 'Goals prevented', '2'], ['diveSaves', 'Diving saves'], ['highClaims', 'High claims'], ['punches', 'Punches'], ['goalKicks', 'Goal kicks']]],
  ['Physical', [['kilometersCovered', 'Distance (km)', '1'], ['numberOfSprints', 'Sprints'], ['avgRating', 'Average rating', '2']]]
];

function duelRow(label, hv, av, fmt, lower, htxt, atxt) {
  if ((hv === undefined || hv === null) && (av === undefined || av === null)) return '';
  hv = hv || 0; av = av || 0;
  const total = Math.abs(hv) + Math.abs(av) || 1;
  const text = v => fmt === '%' ? Math.round(v) + '%' : fmt === '2' ? Number(v).toFixed(2) : fmt === '1' ? Number(v).toFixed(1) : String(Math.round(v * 100) / 100);
  const better = lower ? (hv < av ? 'h' : hv > av ? 'a' : '') : (hv > av ? 'h' : hv < av ? 'a' : '');
  return '<div class="ts-row"><span class="ts-val' + (better === 'h' ? ' best' : '') + '">' + esc(htxt || text(hv)) + '</span>' +
    '<div class="ts-bars"><div class="ts-bar ts-h"><div style="width:' + (Math.abs(hv) / total * 100).toFixed(1) + '%"></div></div><span class="ts-label">' + esc(label) + '</span><div class="ts-bar ts-a"><div style="width:' + (Math.abs(av) / total * 100).toFixed(1) + '%"></div></div></div>' +
    '<span class="ts-val' + (better === 'a' ? ' best' : '') + '">' + esc(atxt || text(av)) + '</span></div>';
}

function renderSheet(m, t) {
  const h = (m.team_stats || {}).home, a = (m.team_stats || {}).away;
  let html = '<div class="ts-head"><span>' + crest(m.home) + esc(m.home) + '</span><span>' + esc(m.away) + crest(m.away) + '</span></div>';
  // Derived first: they exist even for the older format (from the shots).
  html += '<div class="ts-group">Derived</div>';
  html += duelRow('xG per shot', t.home.per_shot, t.away.per_shot, '2');
  html += duelRow('Non-penalty xG', t.home.npxg, t.away.npxg, '2');
  if (h && a) {
    html += duelRow('Pass accuracy', h.passes ? 100 * h.accuratePasses / h.passes : null, a.passes ? 100 * a.accuratePasses / a.passes : null, '%');
    const tilt = (h.touchesInOppBox || 0) + (a.touchesInOppBox || 0);
    if (tilt) html += duelRow('Box-touch share (field tilt)', 100 * (h.touchesInOppBox || 0) / tilt, 100 * (a.touchesInOppBox || 0) / tilt, '%');
    const da = s => (s.totalTackle || 0) + (s.interceptionWon || 0) + (s.fouls || 0);
    if (da(h) && da(a)) html += duelRow('Opponent passes per defensive action', (a.passes || 0) / da(h), (h.passes || 0) / da(a), '1', true);
    if ((h.expectedGoalsOnTarget || h.expectedGoals) && (a.expectedGoalsOnTarget || a.expectedGoals)) html += duelRow('Shot placement (xGOT − xG)', (h.expectedGoalsOnTarget || 0) - (h.expectedGoals || 0), (a.expectedGoalsOnTarget || 0) - (a.expectedGoals || 0), '2');
    SHEET.forEach(([group, rows]) => {
      const body = rows.map(([k, label, fmt]) => {
        if (fmt === 'ratio') return duelRow(label, h[k], a[k], '', false, h[k] !== undefined ? h[k] + '/' + (h[k + '_total'] || '?') : '—', a[k] !== undefined ? a[k] + '/' + (a[k + '_total'] || '?') : '—');
        return duelRow(label, h[k], a[k], fmt, fmt === 'lower');
      }).join('');
      if (body) html += '<div class="ts-group">' + esc(group) + '</div>' + body;
    });
  } else {
    html += '<div class="muted pad">No team-stat sheet for this match (fetched in the older format); the derived rows come from the shots.</div>';
  }
  setHTML('mc-sheet', html);
}

// ── header, model line, page ───────────────────────────────────────────────

function matchHeader(f, m, c) {
  const finished = f.status === 'finished' || f.status === 'live' || (m && m.hs !== null && m.hs !== undefined);
  const hs = m ? m.hs : f.hs, as = m ? m.as : f.as;
  const xg = (m && m.xg) ? m.xg : f.xg;
  const roundTxt = FH.roundText(f);
  return '<div class="match-header">' +
    '<div class="mh-meta"><a href="#/' + esc(c.slug) + '/fixtures">' + esc(c.name) + '</a> · ' + esc(fmtDate(f.date, true)) + (fmtTime(f.date) ? ' ' + esc(fmtTime(f.date)) : '') + (roundTxt ? ' · ' + esc(roundTxt) : '') + (f.group ? ' · Group ' + esc(f.group) : '') + '</div>' +
    '<div class="mh-main">' +
      '<div class="mh-team"><a href="' + esc(teamHref(f.home)) + '">' + crest(f.home, null, 'xl') + '<span>' + esc(f.home) + '</span></a></div>' +
      '<div class="mh-score">' + (finished ? '<span class="big">' + hs + ' – ' + as + '</span>' : '<span class="big vs">v</span>') +
        (xg ? '<span class="xg-line">xG ' + num(xg[0], 2) + ' – ' + num(xg[1], 2) + '</span>' : '') + '<div>' + statusChip(f) + '</div></div>' +
      '<div class="mh-team"><a href="' + esc(teamHref(f.away)) + '">' + crest(f.away, null, 'xl') + '<span>' + esc(f.away) + '</span></a></div>' +
    '</div></div>';
}

function modelCard(f) {
  const m = f.model;
  return '<div class="card"><div class="card-header">Model line <span class="card-sub">Dixon-Coles + Elo; fair odds carry no margin.</span></div><div class="pad model-card">' +
    probBar(m) + '<div class="kpi-grid six">' +
    statTile('Home win', pct(m.h), 'fair ' + ((m.fair || [])[0] || '—')) + statTile('Draw', pct(m.d), 'fair ' + ((m.fair || [])[1] || '—')) + statTile('Away win', pct(m.a), 'fair ' + ((m.fair || [])[2] || '—')) +
    statTile('Expected goals', num(m.lh, 2) + ' – ' + num(m.la, 2), 'most likely ' + esc(m.score || '') + (m.p_score ? ' (' + pct(m.p_score) + ')' : '')) +
    statTile('Over 2.5', pct(m.o25), 'under ' + pct(1 - m.o25)) + statTile('Both score', pct(m.btts), '') + '</div></div></div>';
}

function summaryTiles(t) {
  const pair = (h, a, d) => (h === null || h === undefined ? '—' : num(h, d)) + ' – ' + (a === null || a === undefined ? '—' : num(a, d));
  return '<div class="kpi-grid six">' +
    statTile('Expected goals', pair(t.home.xg, t.away.xg, 2), 'non-penalty ' + pair(t.home.npxg, t.away.npxg, 2)) +
    statTile('xG on target', pair(t.home.xgot, t.away.xgot, 2), 'quality of shots that hit the target') +
    statTile('Shots', t.home.shots + ' – ' + t.away.shots, 'on target ' + t.home.sot + ' – ' + t.away.sot) +
    statTile('xG per shot', pair(t.home.per_shot, t.away.per_shot, 2), 'average chance quality') +
    statTile('Big chances', (t.home.big === undefined ? '—' : t.home.big) + ' – ' + (t.away.big === undefined ? '—' : t.away.big), '') +
    statTile('Possession', t.home.poss === undefined ? '—' : t.home.poss + '% – ' + t.away.poss + '%', '') + '</div>';
}

function renderMatchPage(param) {
  const c = comp() || {};
  const pane = document.getElementById('tab-page');
  const fx = ((D().fixtures || {}).matches || []).find(f => String(f.id) === String(param));
  loadShard('matches/' + param + '.json').then(m => {
    if (FH.STATE.page !== 'match' || FH.STATE.param !== param) return;
    if (!m) {
      if (fx) pane.innerHTML = matchHeader(fx, null, c) + '<div class="card"><div class="muted pad">' + (fx.status === 'finished' ? 'No detailed data for this match yet; it is fetched a few hours after the final whistle.' : 'This match has not been played.') + '</div></div>' + (fx.model ? modelCard(fx) : '');
      else pane.innerHTML = '<div class="error-banner">No match with id ' + esc(param) + '.</div>';
      return;
    }
    const t = sideTotals(m);
    const opts = o => Object.keys(o).map(k => '<option value="' + k + '">' + esc(o[k]) + '</option>').join('') + '</select>';
    let html = matchHeader(fx || m, m, c);
    if (fx && fx.status !== 'finished' && fx.model) html += modelCard(fx);
    html += summaryTiles(t);
    html += '<div class="grid-2">' +
      '<div class="card"><div class="card-header">Expected result <span class="card-sub">What the chances were worth: each shot replayed at its xG.</span></div><div id="mc-expected"></div></div>' +
      '<div class="card"><div class="card-header">xG race <span class="card-sub">Cumulative xG; each dot a shot, sized by xG, green if scored.</span></div><div id="mc-race" style="height:380px"></div></div></div>';
    html += '<div class="card"><div class="card-header">Shot map <span class="card-sub">Size = xG · colour = outcome · ring = team · ▲ header, ■ other body part.</span></div>' +
      '<div class="controls">' + '<select id="mc-sm-team" class="team-select">' + opts({ both: 'Both teams', home: m.home, away: m.away }) + '<select id="mc-sm-sit" class="team-select">' + opts(SITUATIONS) + '<select id="mc-sm-res" class="team-select">' + opts({ all: 'All outcomes', target: 'On target', goal: 'Goals only' }) +
      '<span class="muted-inline" id="mc-sm-sum"></span></div><div id="mc-shotmap" style="height:520px"></div></div>';
    html += '<div class="grid-2"><div class="card"><div class="card-header">' + crest(m.home) + esc(m.home) + ' · where the shots went <span class="card-sub">Shooter\'s view; size = xG on target.</span></div><div id="mc-gm-h" style="height:230px"></div></div>' +
      '<div class="card"><div class="card-header">' + crest(m.away) + esc(m.away) + ' · where the shots went <span class="card-sub">Shooter\'s view; size = xG on target.</span></div><div id="mc-gm-a" style="height:230px"></div></div></div>';
    html += '<div class="grid-2"><div class="card"><div class="card-header">Timeline</div><div id="mc-timeline" style="height:200px"></div>' +
      '<div class="card-header">Momentum <span class="card-sub">Sofascore’s pressure index by minute.</span></div><div id="mc-momentum" style="height:200px"></div></div>' +
      '<div class="card"><div class="card-header">Who made the chances <span class="card-sub">xG from shots taken, xA from passes that led to shots.</span></div><div id="mc-contrib" style="height:320px"></div></div></div>';
    html += '<div class="card"><div class="card-header">Team statistics <span class="card-sub">Bold = the better side; derived ratios first.</span></div><div class="pad sheet-cols" id="mc-sheet"></div></div>';
    html += '<div class="card"><div class="card-header">Line-ups <span class="card-sub">Starting formations; colour = rating (green high, red low).</span></div><div id="mc-formation" style="height:470px"></div>' +
      '<div class="grid-2 pad"><div>' + benchList(m, 'home') + '</div><div>' + benchList(m, 'away') + '</div></div></div>';
    html += '<div class="card"><div class="card-header">Player statistics <span class="card-sub">Every player who played; sortable.</span></div><div class="controls">' +
      '<select id="mc-pt-team" class="team-select">' + opts({ both: 'Both teams', home: m.home, away: m.away }) + '</div><div id="mc-players"></div></div>';
    pane.innerHTML = html;
    renderExpected(m);
    renderRace(m);
    FH.renderMomentum('mc-momentum', m.momentum || [], m.home, m.away);
    ['mc-sm-team', 'mc-sm-sit', 'mc-sm-res'].forEach(id => document.getElementById(id).addEventListener('change', () => renderShotMap(m)));
    renderShotMap(m);
    renderGoalMouth('mc-gm-h', m, 'home');
    renderGoalMouth('mc-gm-a', m, 'away');
    renderTimeline(m);
    renderContributions(m);
    renderSheet(m, t);
    renderFormations(m);
    document.getElementById('mc-pt-team').addEventListener('change', () => renderPlayerTable(m));
    renderPlayerTable(m);
  });
}

FH.PAGES.match = renderMatchPage;
FH.fullPitch = fullPitch;
})(window.FH);
