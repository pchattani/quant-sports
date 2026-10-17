/* The Quant Rink — shared chart helpers (RK.charts).
 *
 * Every helper takes a target (element or id) first and degrades to a muted line when its data is
 * missing. Column-oriented payloads ({cols|fields|columns, rows}) are normalised with RK.charts.rows(x).
 *
 * Rink coordinates are the NHL's: feet, centre ice at (0, 0), x along the length (-100..100), y across
 * (-42.5..42.5). Shot rows are normalised so the shooting team attacks +x (PAYLOADS.md), so a half-rink
 * map draws x 0..100 with the goal on the right (goal line at x = 89).
 *
 *   rows(x)                             [{...}] from an array of objects or {cols|fields|columns, rows}
 *   rinkShapes(opts)                    Plotly shapes for the rink: boards (28 ft corners), goal lines, blue lines, centre line,
 *                                       creases, nets, trapezoids, face-off circles and dots; opts {half: true (x 0..100) |
 *                                       false (full 200 ft), light: true (white ice), lines: 1 (opacity)}
 *   rinkAxes(half, height)              the layout part that keeps the rink to scale: {xaxis, yaxis, height}
 *   shotRows(x)                         normalised shots [{period, sec, team, player, x, y, type, shot_type, xg, goal, strength}]
 *   shotMap(el, shots, opts)            half-rink shot map attacking right, dots sized by xG, goals filled, misses faint, blocks as x,
 *                                       with team / strength / period filters above it and a shots-goals-xG line below;
 *                                       opts {home, away, team: 'all'|abbr, strength: 'all'|'5v5'|'PP'|'PK'|'EN', period: 'all'|n,
 *                                       filters: true, teamToggle: true, full: false (away attacks left, home right), highlight: pid, playoff,
 *                                       height, blocked: true, colours: {abbr: colour}}
 *   xgRace(el, data, opts)              cumulative expected goals by game time for both teams, goals marked; data = shot rows,
 *                                       or {home: [[sec, cum_xg]], away: [...], goals: [{sec, team, player}]}, or {cols: [sec, home, away, goal], rows}; opts {home, away,
 *                                       end (sec), until (sec: a live game's lines stop here), playoff, height}
 *   wpChart(el, rows, opts)             home win probability by game time; rows [{sec, p}] | [[sec, p]] | {cols, rows}
 *                                       (sec|t|time, p|p_home|wp_home); opts {home, away, goals [{sec, team, player, desc}], market
 *                                       (pre-game market p_home: a tick at the start), others [{name, rows, colour, dash}], playoff, height}
 *   shotHeatmap(el, grid, opts)         shot-location rates on a half rink: grid {x: [centres], y: [centres], v: [[y][x]], league?: same,
 *                                       n?} (heatmap), or {hex: [[x, y, v, n]] | [{x, y, v, n, league}], size} (hexes), or zones
 *                                       [{zone, v, league, n}] (bars); opts {vsLeague: true (show v - league), rel: true (v is already
 *                                       relative), invert: true (lower is better: defence), fmt, label, title, height}
 *   impactChart(el, pts, opts)          on-ice impact quadrant (RAPM): pts [{pid, name, team, off, def, toi}] with off = xGF/60 impact
 *                                       (higher better) and def = xGA/60 impact (lower better: drawn upward when negative); opts
 *                                       {highlight: [pids], labels: n (label the top n by |off|+|def|), defUp: false (def is already
 *                                       "higher = better"), xTitle, yTitle, height, colour}
 *   scoreGrid(el, dist, opts)           exact-score probabilities: [[p(home=i, away=j)]] | {"h-a": p} | {home: [p0..], away: [p0..]}
 *                                       (independent marginals); opts {home, away, actual: [hs, as], max: 7, height}
 *   percentileSliders(metrics, vals, pcts, opts)  HTML: Savant-style sliders (blue low, red high) grouped by METRIC.group;
 *                                       opts {groups: false, note, keys: [subset], onlyKnown, glossary: false, columns: 1}
 *   sliderRow(label, p, valueText, title)        one slider row (HTML)
 *   linescore(g, opts)                  HTML linescore by period (1st 2nd 3rd OT/SO) with totals and shots when known: g {home, away,
 *                                       hs, as, linescore|periods (see RK.periodsOf), sog: {home, away}}; opts {link}
 *   distBars(el, dist, opts)            bars of {k: p}; opts {actual, exp, line, xTitle, colour, height, unit, signed, split, colours}
 *   heatTable(spec)                     HTML: {cols, rows:[{label(html), values, titles}], fmt, scale:'div'|'seq', max, invert, corner, center}
 *   probBars(el, items, opts)           items [{label, p, colour, market}] horizontal bars, market as a tick
 *   lines(el, series, opts)             series [{name, x, y, colour, dash, width, err, band:[lo,hi], mode, shape, hover}]
 *   radar(el, series, opts)             series [{name, values:[0-100], colour}]; opts {labels, height}
 *   hexA(hex, a)                        rgba string
 */
(function (RK) {
'use strict';

const C = RK.C;
const esc = RK.esc;
const isNum = RK.isNum;

function node(el) { return typeof el === 'string' ? document.getElementById(el) : el; }
function empty(el, text) { const n = node(el); if (n) n.innerHTML = '<div class="muted">' + text + '</div>'; }
function hexA(hex, a) {
  const h = String(hex || '').replace('#', '');
  if (h.length !== 6) return 'rgba(139,148,158,' + a + ')';
  return 'rgba(' + parseInt(h.slice(0, 2), 16) + ',' + parseInt(h.slice(2, 4), 16) + ',' + parseInt(h.slice(4, 6), 16) + ',' + a + ')';
}
/* Rows from an array of objects or a column-oriented {cols|fields|columns, rows}. */
function rows(x) {
  if (!x) return [];
  if (Array.isArray(x)) return x.filter(r => r && typeof r === 'object' && !Array.isArray(r));
  const cols = x.cols || x.fields || x.columns;
  if (Array.isArray(cols) && Array.isArray(x.rows)) return x.rows.map(r => { const o = {}; cols.forEach((c, i) => { o[c] = r[i]; }); return o; });
  if (Array.isArray(x.rows)) return rows(x.rows);
  return [];
}
function median(a) { const s = a.filter(isNum).map(Number).sort((x, y) => x - y); if (!s.length) return null; const k = s.length >> 1; return s.length % 2 ? s[k] : (s[k - 1] + s[k]) / 2; }
function mean(a) { const s = a.filter(isNum).map(Number); return s.length ? s.reduce((x, y) => x + y, 0) / s.length : null; }
function first(o, keys) { for (let i = 0; i < keys.length; i++) { const v = o[keys[i]]; if (v !== undefined && v !== null && v !== '') return v; } return null; }
const DIV_SCALE = [[0, '#2c64c8'], [0.25, '#7a9fd9'], [0.5, '#9a9a9a'], [0.75, '#e08a7a'], [1, '#d62828']];
const SEQ_SCALE = [[0, 'rgba(92,198,242,0.04)'], [0.5, 'rgba(92,198,242,0.45)'], [1, '#9be0ff']];
function divScale(invert) { return invert ? DIV_SCALE.map((s, i) => [s[0], DIV_SCALE[DIV_SCALE.length - 1 - i][1]]) : DIV_SCALE; }

// ── the rink ───────────────────────────────────────────────────────────────

/* Points of an arc centred (cx, cy), radius r, from angle a0 to a1 (degrees), as "x,y" pairs. */
function arcPts(cx, cy, r, a0, a1, n) {
  const out = [];
  const k = n || 18;
  for (let i = 0; i <= k; i++) {
    const a = (a0 + (a1 - a0) * i / k) * Math.PI / 180;
    out.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]);
  }
  return out;
}
function pathOf(pts, close) { return pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(2) + ',' + p[1].toFixed(2)).join(' ') + (close ? ' Z' : ''); }
/* The outline of the boards: 200 x 85 with 28 ft corners (or the right half when half). */
function boardsPath(half) {
  const R = 28, X = 100, Y = 42.5;
  let pts = [];
  if (half) {
    pts.push([0, -Y]);
    pts = pts.concat(arcPts(X - R, -Y + R, R, -90, 0));
    pts = pts.concat(arcPts(X - R, Y - R, R, 0, 90));
    pts.push([0, Y]);
    return pathOf(pts, false);
  }
  pts = pts.concat(arcPts(X - R, -Y + R, R, -90, 0));
  pts = pts.concat(arcPts(X - R, Y - R, R, 0, 90));
  pts = pts.concat(arcPts(-X + R, Y - R, R, 90, 180));
  pts = pts.concat(arcPts(-X + R, -Y + R, R, 180, 270));
  return pathOf(pts, true);
}
/* The y extent of the boards at x (the corners curve in). */
function boardY(x) {
  const R = 28, X = 100, Y = 42.5;
  const ax = Math.abs(x);
  if (ax <= X - R) return Y;
  const dx = ax - (X - R);
  return Y - R + Math.sqrt(Math.max(0, R * R - dx * dx));
}
function rinkShapes(opts) {
  const o = opts || {};
  const half = o.half !== false;
  const light = !!o.light;
  const op = isNum(o.lines) ? Number(o.lines) : 1;
  const red = light ? 'rgba(200,16,46,' + (0.85 * op) + ')' : 'rgba(229,72,77,' + (0.62 * op) + ')';
  const blue = light ? 'rgba(0,56,168,' + (0.8 * op) + ')' : 'rgba(74,144,217,' + (0.72 * op) + ')';
  const board = light ? '#5b6670' : 'rgba(201,209,217,' + (0.55 * op) + ')';
  const ice = light ? '#f4f9fc' : 'rgba(220,236,245,0.05)';
  const sides = half ? [1] : [-1, 1];
  const sh = [];
  const L = (x0, y0, x1, y1, col, w, dash) => sh.push({ type: 'line', x0: x0, y0: y0, x1: x1, y1: y1, layer: 'below', line: { color: col, width: w || 1.4, dash: dash || 'solid' } });
  const circle = (cx, cy, r, col, fill, w) => sh.push({ type: 'circle', x0: cx - r, x1: cx + r, y0: cy - r, y1: cy + r, layer: 'below', fillcolor: fill || 'rgba(0,0,0,0)', line: { color: col, width: w || 1.2 } });
  // ice and boards
  sh.push({ type: 'path', path: boardsPath(false), fillcolor: ice, line: { width: 0 }, layer: 'below' });
  // centre line, blue lines
  L(0, -42.5, 0, 42.5, red, half ? 2.4 : 3);
  sides.forEach(s => {
    sh.push({ type: 'rect', x0: s * 25, x1: s * 26, y0: -42.5, y1: 42.5, fillcolor: blue, line: { width: 0 }, layer: 'below' });
    // goal line (clipped to the corner curve)
    const gy = boardY(89);
    L(s * 89, -gy, s * 89, gy, red, 1.4);
    // crease: a 6 ft arc clipped to 4 ft either side, filled
    const cx = s * 89;
    const xc = Math.sqrt(36 - 16);
    const arc = arcPts(cx, 0, 6, s > 0 ? 180 + 41.81 : -41.81, s > 0 ? 180 - 41.81 : 41.81, 12);
    const cpts = [[cx, -4], [cx - s * xc, -4]].concat(arc).concat([[cx - s * xc, 4], [cx, 4]]);
    sh.push({ type: 'path', path: pathOf(cpts, true), fillcolor: light ? 'rgba(0,120,215,0.25)' : 'rgba(74,144,217,0.28)', line: { color: red, width: 1 }, layer: 'below' });
    // net: 6 ft wide, 40 in deep behind the goal line
    sh.push({ type: 'rect', x0: s > 0 ? cx : cx - 3.33, x1: s > 0 ? cx + 3.33 : cx, y0: -3, y1: 3, fillcolor: light ? 'rgba(200,16,46,0.15)' : 'rgba(229,72,77,0.18)', line: { color: red, width: 1.2 }, layer: 'below' });
    // trapezoid behind the net
    L(cx, -11, s * 100, -14, red, 1);
    L(cx, 11, s * 100, 14, red, 1);
    // end-zone face-off circles and dots, neutral-zone dots
    [-22, 22].forEach(y => {
      circle(s * 69, y, 15, red, null, 1.2);
      circle(s * 69, y, 1, red, red, 1);
      circle(s * 20, y, 1, red, red, 1);
    });
  });
  // centre circle and dot
  circle(0, 0, 15, blue, null, 1.2);
  circle(0, 0, 0.6, blue, blue, 1);
  // boards on top of the ice
  sh.push({ type: 'path', path: boardsPath(half), fillcolor: 'rgba(0,0,0,0)', line: { color: board, width: 2 }, layer: 'below' });
  if (half) L(0, -42.5, 0, 42.5, board, 1, 'dot');
  return sh;
}
/* Axes that keep the rink to scale. */
function rinkAxes(half, height) {
  const x = half ? [-1.5, 101.5] : [-101.5, 101.5];
  return {
    xaxis: { range: x, showgrid: false, zeroline: false, showticklabels: false, fixedrange: true, constrain: 'domain' },
    yaxis: { range: [-43.5, 43.5], showgrid: false, zeroline: false, showticklabels: false, fixedrange: true, scaleanchor: 'x', scaleratio: 1, constrain: 'domain' },
    height: height || (half ? 360 : 300)
  };
}
/* Height that fits the rink's aspect in the node's width. */
function rinkHeight(nd, half, extra) {
  const w = (nd && nd.clientWidth) || 600;
  const aspect = half ? 87 / 103 : 87 / 203;
  return Math.max(half ? 200 : 140, Math.round(w * aspect) + (extra || 20));
}

// ── shots ──────────────────────────────────────────────────────────────────

function shotKind(t, goal) {
  if (goal === true || goal === 1 || goal === '1') return 'goal';
  const k = String(t || '').toLowerCase();
  if (k === 'goal' || k === 'g') return 'goal';
  if (/block/.test(k)) return 'blocked';
  if (/miss|wide|post|cross/.test(k)) return 'missed';
  return 'sog';
}
function shotRows(x) {
  return rows(x).map(s => {
    const goal = s.goal === true || s.goal === 1 || s.goal === '1' || String(s.type || '').toLowerCase() === 'goal';
    return {
      period: isNum(s.period) ? Number(s.period) : null, sec: isNum(s.sec) ? Number(s.sec) : (isNum(s.t) ? Number(s.t) : null),
      team: s.team || s.team_abbr || null, player: s.player || s.shooter || s.pid || null, name: s.name || s.player_name || null,
      x: isNum(s.x) ? Number(s.x) : null, y: isNum(s.y) ? Number(s.y) : null, type: s.type || s.event || '', shot_type: s.shot_type || s.shotType || '',
      xg: isNum(s.xg) ? Number(s.xg) : (isNum(s.xG) ? Number(s.xG) : null), goal: goal, kind: shotKind(s.type || s.event, goal),
      strength: s.strength !== undefined ? s.strength : s.situation, goalie: s.goalie || null
    };
  }).filter(s => s.x !== null && s.y !== null);
}
function sideOf(team, o) { return o.home && String(team) === String(o.home) ? 'home' : (o.away && String(team) === String(o.away) ? 'away' : null); }
const FILT_KEY = '__rkShotFilt';
function shotMap(el, shots, opts) {
  const o = opts || {};
  const nd = node(el);
  if (!nd) return;
  const all = shotRows(shots);
  if (!all.length) { empty(nd, o.emptyText || 'No shots to map yet.'); return; }
  const teams = [];
  if (o.away) teams.push(o.away);
  if (o.home) teams.push(o.home);
  all.forEach(s => { if (s.team && teams.indexOf(s.team) < 0) teams.push(s.team); });
  const pair = teams.length >= 2 ? RK.pairColours(teams[0], teams[1]) : [RK.teamColour(teams[0]), C.p2];
  const colOf = t => ((o.colours || {})[t]) || (String(t) === String(teams[0]) ? pair[0] : String(t) === String(teams[1]) ? pair[1] : RK.teamColour(t));
  const f = nd[FILT_KEY] || { team: o.team || 'all', strength: o.strength || 'all', period: isNum(o.period) ? String(o.period) : (o.period || 'all') };
  nd[FILT_KEY] = f;
  const periods = [];
  all.forEach(s => { if (isNum(s.period) && periods.indexOf(s.period) < 0) periods.push(s.period); });
  periods.sort((a, b) => a - b);
  const hasStr = all.some(s => s.strength !== null && s.strength !== undefined && s.strength !== '');
  const ctl = o.filters === false ? '' : '<div class="toggle-row sm-ctl">' +
    (teams.length > 1 && o.teamToggle !== false ? '<span class="sm-grp" data-g="team">' + RK.toggles([{ key: 'all', label: 'Both' }].concat(teams.map(t => ({ key: t, label: RK.teamAbbr(t) }))), f.team, 'data-v') + '</span>' : '') +
    (hasStr ? '<span class="sm-grp" data-g="strength">' + RK.toggles(RK.STRENGTHS.filter(x => x[0] !== 'other').map(x => ({ key: x[0], label: x[0] === 'all' ? 'All' : x[0] === 'PK' ? 'SH' : x[0] })), f.strength, 'data-v') + '</span>' : '') +
    (periods.length > 1 ? '<span class="sm-grp" data-g="period">' + RK.toggles([{ key: 'all', label: 'All' }].concat(periods.map(p => ({ key: String(p), label: RK.periodLabel(p, { playoff: o.playoff }) }))), f.period, 'data-v') + '</span>' : '') + '</div>';
  nd.innerHTML = ctl + '<div class="sm-plot"></div><div class="sm-sum"></div>';
  const plotEl = nd.querySelector('.sm-plot'), sumEl = nd.querySelector('.sm-sum');
  const full = !!o.full;
  const draw = () => {
    const list = all.filter(s => {
      if (f.team !== 'all' && String(s.team) !== String(f.team)) return false;
      if (f.period !== 'all' && String(s.period) !== String(f.period)) return false;
      if (f.strength !== 'all' && RK.strengthGroup(s.strength, sideOf(s.team, o)) !== f.strength) return false;
      if (o.blocked === false && s.kind === 'blocked') return false;
      return true;
    });
    const traces = [];
    const byTeam = {};
    list.forEach(s => { (byTeam[s.team] = byTeam[s.team] || []).push(s); });
    const hover = s => '<b>' + esc(s.name || (s.player ? RK.playerName(s.player) : RK.teamAbbr(s.team))) + '</b> · ' + esc(RK.teamAbbr(s.team)) +
      '<br>' + esc(RK.shotTypeLabel(s.kind === 'sog' ? 'shot-on-goal' : s.kind === 'missed' ? 'missed-shot' : s.kind === 'blocked' ? 'blocked-shot' : 'goal')) +
      (s.shot_type ? ' · ' + esc(RK.titleCase(s.shot_type)) : '') + (isNum(s.xg) ? '<br>xG ' + s.xg.toFixed(2) : '') +
      (isNum(s.sec) ? '<br>' + esc(RK.secText(s.sec, o.playoff)) : (isNum(s.period) ? '<br>' + esc(RK.periodLabel(s.period, { playoff: o.playoff })) : '')) +
      (s.strength !== null && s.strength !== undefined && s.strength !== '' ? ' · ' + esc(RK.strength(s.strength, sideOf(s.team, o)).short) : '');
    const sz = s => (s.kind === 'blocked' ? 7 : 5 + 28 * Math.sqrt(Math.max(0, isNum(s.xg) ? s.xg : 0.02)));
    Object.keys(byTeam).forEach(t => {
      const col = colOf(t);
      const flip = full && o.away && String(t) === String(o.away);
      const X = s => (flip ? -s.x : s.x), Y = s => (flip ? -s.y : s.y);
      const groups = [['blocked', 'x-thin-open', 0.45], ['missed', 'circle-open', 0.45], ['sog', 'circle-open', 0.95], ['goal', 'circle', 1]];
      groups.forEach(gk => {
        const g = byTeam[t].filter(s => s.kind === gk[0]);
        if (!g.length) return;
        traces.push({ type: 'scatter', mode: 'markers', name: RK.teamAbbr(t) + ' ' + gk[0], x: g.map(X), y: g.map(Y), hovertext: g.map(hover), hoverinfo: 'text',
          marker: { symbol: gk[1], size: g.map(sz), color: col, opacity: gk[2],
            line: { width: gk[0] === 'goal' ? 1.5 : (gk[0] === 'blocked' ? 1.5 : 1.6), color: gk[0] === 'goal' ? '#ffffff' : col } } });
      });
      if (o.highlight) {
        const g = byTeam[t].filter(s => String(s.player) === String(o.highlight));
        if (g.length) traces.push({ type: 'scatter', mode: 'markers', x: g.map(X), y: g.map(Y), hoverinfo: 'skip', marker: { symbol: 'circle-open', size: g.map(s => sz(s) + 7), color: C.yellow, line: { width: 2, color: C.yellow } } });
      }
    });
    const ann = [];
    if (full && o.home && o.away) {
      ann.push({ x: -50, y: 46, text: esc(RK.teamAbbr(o.away)) + ' attack ←', showarrow: false, font: { size: 10, color: colOf(o.away) } });
      ann.push({ x: 50, y: 46, text: '→ ' + esc(RK.teamAbbr(o.home)) + ' attack', showarrow: false, font: { size: 10, color: colOf(o.home) } });
    }
    const ax = rinkAxes(!full, null);
    if (full) ax.yaxis.range = [-43.5, 49];
    RK.purge(plotEl);
    RK.plot(plotEl, traces, RK.layout(Object.assign(ax, { height: o.height || rinkHeight(plotEl, !full, 10), shapes: rinkShapes({ half: !full, light: o.light }), annotations: ann,
      margin: { l: 4, r: 4, t: full ? 18 : 4, b: 4 } })));
    // summary per team
    const parts = (f.team === 'all' ? teams : [f.team]).map(t => {
      const g = list.filter(s => String(s.team) === String(t));
      const xg = g.reduce((a, s) => a + (isNum(s.xg) ? s.xg : 0), 0);
      return '<span><i class="legend-sw" style="background:' + colOf(t) + '"></i><b>' + esc(RK.teamAbbr(t)) + '</b> ' + g.filter(s => s.kind === 'goal').length + ' G · ' +
        g.filter(s => s.kind === 'goal' || s.kind === 'sog').length + ' SOG · ' + g.filter(s => s.kind !== 'blocked').length + ' unblocked · xG ' + xg.toFixed(2) + '</span>';
    });
    sumEl.innerHTML = '<div class="legend-row">' + parts.join('') + '<span class="muted-inline">● goal · ○ on goal · faint ○ missed' + (o.blocked === false ? '' : ' · × blocked') + ' · size = xG</span></div>';
  };
  nd.querySelectorAll('.sm-grp').forEach(grp => {
    RK.wireToggles(grp, 'data-v', v => { f[grp.dataset.g] = v; draw(); });
  });
  draw();
}

// ── expected goals race ────────────────────────────────────────────────────

function pairsOf(x) {
  if (!x) return [];
  if (Array.isArray(x)) return x.map(r => (Array.isArray(r) ? [Number(r[0]), Number(r[1])] : (r && typeof r === 'object' ? [Number(first(r, ['sec', 't', 'time'])), Number(first(r, ['xg', 'cum', 'cum_xg', 'v', 'y']))] : null))).filter(p => p && isNum(p[0]) && isNum(p[1]));
  return pairsOf(rows(x));
}
function periodBreaks(end, playoff) {
  const out = [1200, 2400];
  if (end > 3600) out.push(3600);
  if (playoff) for (let t = 4800; t < end; t += 1200) out.push(t);
  return out;
}
function periodTicks(end, playoff) {
  const ticks = [], text = [];
  const n = Math.max(3, Math.ceil((end - 0.5) / 1200));
  for (let p = 1; p <= 3; p++) { ticks.push((p - 0.5) * 20); text.push(RK.periodLabel(p)); }
  if (end > 3600) {
    if (playoff) for (let p = 4; p <= n; p++) { ticks.push((p - 0.5) * 20); text.push(RK.periodLabel(p, { playoff: true })); }
    else { ticks.push(62.5); text.push('OT'); }
  }
  return { vals: ticks, text: text };
}
function xgRace(el, data, opts) {
  const o = opts || {};
  let H = [], A = [], goals = [];
  const dcols = data && !Array.isArray(data) ? (data.cols || data.fields || data.columns) : null;
  if (dcols && dcols.indexOf('home') >= 0 && dcols.indexOf('away') >= 0 && dcols.indexOf('x') < 0) {
    // {cols: [sec, home, away, goal], rows}: cumulative xG at each event; goal = the scoring team
    rows(data).forEach(r => {
      const t = Number(first(r, ['sec', 't', 'time']));
      if (!isNum(t)) return;
      if (isNum(r.home) && (!H.length || H[H.length - 1][1] !== Number(r.home))) H.push([t, Number(r.home)]);
      if (isNum(r.away) && (!A.length || A[A.length - 1][1] !== Number(r.away))) A.push([t, Number(r.away)]);
      if (r.goal) goals.push({ sec: t, team: r.goal === 'home' ? o.home : (r.goal === 'away' ? o.away : r.goal), player: r.player || null });
    });
  } else if (data && !Array.isArray(data) && (data.home || data.away) && !dcols) {
    H = pairsOf(data.home); A = pairsOf(data.away); goals = rows(data.goals);
  } else {
    const S = shotRows(data).filter(s => isNum(s.sec)).sort((a, b) => a.sec - b.sec);
    let h = 0, a = 0;
    S.forEach(s => {
      if (!isNum(s.xg) && !s.goal) return;
      if (String(s.team) === String(o.home)) { h += isNum(s.xg) ? s.xg : 0; H.push([s.sec, h]); } else if (String(s.team) === String(o.away)) { a += isNum(s.xg) ? s.xg : 0; A.push([s.sec, a]); }
      if (s.goal) goals.push({ sec: s.sec, team: s.team, player: s.player, name: s.name, strength: s.strength });
    });
  }
  if (H.length + A.length < 2) { empty(el, o.emptyText || 'No expected-goals path for this game yet.'); return; }
  const maxT = Math.max.apply(null, H.concat(A).map(p => p[0]).concat(goals.map(g => Number(g.sec) || 0)));
  const end = isNum(o.end) ? Number(o.end) : (maxT <= 3600 ? 3600 : maxT);
  const pc = RK.pairColours(o.home, o.away);
  const ser = (pts, t, col) => {
    const x = [0], y = [0];
    pts.forEach(p => { x.push(p[0] / 60); y.push(p[1]); });
    x.push((isNum(o.until) ? Math.min(end, Number(o.until)) : end) / 60); y.push(y[y.length - 1]);
    return { type: 'scatter', mode: 'lines', name: RK.teamAbbr(t), x: x, y: y, line: { color: col, width: 2.4, shape: 'hv' },
      hovertemplate: esc(RK.teamAbbr(t)) + ' xG %{y:.2f}<extra></extra>' };
  };
  const at = (pts, sec) => { let v = 0; pts.forEach(p => { if (p[0] <= sec) v = p[1]; }); return v; };
  const traces = [ser(A, o.away, pc[1]), ser(H, o.home, pc[0])];
  const gl = goals.filter(g => isNum(g.sec));
  if (gl.length) {
    const ys = gl.map(g => at(String(g.team) === String(o.home) ? H : A, Number(g.sec)));
    traces.push({ type: 'scatter', mode: 'markers', x: gl.map(g => Number(g.sec) / 60), y: ys, showlegend: false,
      marker: { size: 11, symbol: 'circle', color: gl.map(g => (String(g.team) === String(o.home) ? pc[0] : pc[1])), line: { width: 2, color: '#ffffff' } },
      hovertext: gl.map(g => '<b>Goal</b> · ' + esc(RK.teamAbbr(g.team)) + (g.player || g.name ? ' · ' + esc(g.name || RK.playerName(g.player)) : '') + '<br>' + esc(RK.secText(g.sec, o.playoff)) +
        (g.strength ? ' · ' + esc(RK.strength(g.strength, String(g.team) === String(o.home) ? 'home' : 'away').short) : '')), hoverinfo: 'text' });
  }
  const shapes = periodBreaks(end, o.playoff).map(b => ({ type: 'line', x0: b / 60, x1: b / 60, yref: 'paper', y0: 0, y1: 1, line: { color: '#30363d', width: 1, dash: 'dot' }, layer: 'below' }));
  const tk = periodTicks(end, o.playoff);
  RK.plot(el, traces, RK.layout({
    height: o.height || 280, shapes: shapes, showlegend: true,
    legend: { orientation: 'h', x: 0, y: 1.12, font: { size: 11, color: C.text2 } },
    xaxis: { range: [0, end / 60], tickvals: tk.vals, ticktext: tk.text, showgrid: false, zeroline: false, fixedrange: true },
    yaxis: { title: { text: 'Cumulative xG', font: { size: 10 } }, rangemode: 'tozero', fixedrange: true, zeroline: false },
    margin: { l: 50, r: 12, t: 26, b: 30 }
  }));
}

// ── win probability ────────────────────────────────────────────────────────

function wpRows(x) {
  if (x && !Array.isArray(x) && Array.isArray(x.series)) x = x.series;
  const list = Array.isArray(x) ? x : rows(x);
  return list.map(r => {
    if (Array.isArray(r)) return { sec: Number(r[0]), p: Number(r[1]), desc: r[2] || '' };
    if (r && typeof r === 'object') return { sec: Number(first(r, ['sec', 't', 'time', 'elapsed'])), p: Number(first(r, ['p_home', 'wp_home', 'p', 'wp'])), desc: r.desc || r.label || '' };
    return null;
  }).filter(r => r && isNum(r.sec) && isNum(r.p)).sort((a, b) => a.sec - b.sec);
}
function wpChart(el, data, opts) {
  const o = opts || {};
  const R = wpRows(data);
  if (R.length < 2) { empty(el, o.emptyText || 'No win-probability path for this game yet.'); return; }
  const pc = RK.pairColours(o.home, o.away);
  const hc = o.home ? pc[0] : C.home, ac = o.away ? pc[1] : C.away;
  const hn = o.home ? RK.teamAbbr(o.home) : 'Home', an = o.away ? RK.teamAbbr(o.away) : 'Away';
  const x = R.map(r => r.sec / 60), y = R.map(r => r.p);
  const end = Math.max(3600, R[R.length - 1].sec);
  const shapes = [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 0.5, y1: 0.5, line: { color: '#30363d', width: 1 } }]
    .concat(periodBreaks(end, o.playoff).map(b => ({ type: 'line', x0: b / 60, x1: b / 60, yref: 'paper', y0: 0, y1: 1, line: { color: '#2b323b', width: 1, dash: 'dot' }, layer: 'below' })));
  const txt = R.map(r => esc(RK.secText(r.sec, o.playoff)) + (r.desc ? ' · ' + esc(String(r.desc).slice(0, 100)) : '') + '<br>' + esc(hn) + ' ' + RK.pct(r.p, 1));
  const traces = [
    { type: 'scatter', mode: 'lines', x: x, y: x.map(() => 0.5), line: { width: 0 }, hoverinfo: 'skip', showlegend: false },
    { type: 'scatter', mode: 'lines', x: x, y: y.map(v => Math.max(v, 0.5)), fill: 'tonexty', fillcolor: hexA(hc, 0.22), line: { width: 0, shape: 'hv' }, hoverinfo: 'skip', showlegend: false },
    { type: 'scatter', mode: 'lines', x: x, y: x.map(() => 0.5), line: { width: 0 }, hoverinfo: 'skip', showlegend: false },
    { type: 'scatter', mode: 'lines', x: x, y: y.map(v => Math.min(v, 0.5)), fill: 'tonexty', fillcolor: hexA(ac, 0.22), line: { width: 0, shape: 'hv' }, hoverinfo: 'skip', showlegend: false },
    { type: 'scatter', mode: 'lines', x: x, y: y, name: o.mainName || 'Our model', line: { color: C.text, width: 2, shape: 'hv' }, text: txt, hovertemplate: '%{text}<extra></extra>' }
  ];
  (o.others || []).forEach(s => {
    const Q = wpRows(s.rows);
    if (Q.length >= 2) traces.push({ type: 'scatter', mode: 'lines', name: s.name, x: Q.map(r => r.sec / 60), y: Q.map(r => r.p), line: { color: s.colour || C.espn, width: 1.4, dash: s.dash || 'dot', shape: 'hv' },
      hovertemplate: esc(s.name) + ' ' + esc(hn) + ' %{y:.1%}<extra></extra>' });
  });
  const at = sec => { let best = null; R.forEach(r => { if (r.sec <= sec) best = r; }); return best ? best.p : null; };
  const gl = rows(o.goals).filter(g => isNum(g.sec));
  if (gl.length) {
    const pts = gl.map(g => ({ g: g, y: isNum(g.p) ? g.p : at(Number(g.sec) + 1) })).filter(p => p.y !== null);
    traces.push({ type: 'scatter', mode: 'markers', x: pts.map(p => Number(p.g.sec) / 60), y: pts.map(p => p.y), showlegend: false,
      marker: { size: 9, color: pts.map(p => (String(p.g.team) === String(o.home) ? hc : ac)), line: { width: 1.5, color: '#0d1117' } },
      hovertext: pts.map(p => '<b>Goal</b> · ' + esc(RK.teamAbbr(p.g.team)) + (p.g.player || p.g.name ? ' · ' + esc(p.g.name || RK.playerName(p.g.player)) : '') + '<br>' + esc(RK.secText(p.g.sec, o.playoff)) + '<br>' + esc(hn) + ' ' + RK.pct(p.y, 0)),
      hoverinfo: 'text' });
  }
  if (isNum(o.market)) shapes.push({ type: 'line', x0: -0.6, x1: 0.6, y0: o.market, y1: o.market, line: { color: C.text, width: 3 } });
  const tk = periodTicks(end, o.playoff);
  RK.plot(el, traces, RK.layout({
    height: o.height || 300, shapes: shapes,
    xaxis: { showgrid: false, fixedrange: true, zeroline: false, range: [-0.8, end / 60 + 0.5], tickvals: tk.vals, ticktext: tk.text },
    yaxis: { range: [0, 1], tickvals: [0, 0.25, 0.5, 0.75, 1], ticktext: [an + ' 100%', '75%', '50%', '75%', hn + ' 100%'], fixedrange: true, automargin: true },
    showlegend: (o.others || []).length > 0, legend: { orientation: 'h', y: -0.12, x: 1, xanchor: 'right', font: { size: 10, color: C.text2 } },
    margin: { l: 70, r: 10, t: 12, b: 30 }
  }));
}

// ── shot heatmaps ──────────────────────────────────────────────────────────

function shotHeatmap(el, grid, opts) {
  const o = opts || {};
  const nd = node(el);
  if (!nd) return;
  const g = grid || {};
  const fmt = o.fmt ? (v => RK.fmtVal(v, o.fmt)) : (v => (o.vsLeague || o.rel ? RK.signed(v, 2) : RK.num(v, 2)));
  const scaleRel = !!(o.vsLeague || o.rel);
  // zones -> bars
  const zl = Array.isArray(g) ? g : (Array.isArray(g.zones) ? g.zones : null);
  if (zl && zl.length && (zl[0].zone || zl[0].name)) {
    const list = zl.map(z => ({ label: z.zone || z.name, v: Number(first(z, ['v', 'value', 'rate'])), league: first(z, ['league', 'lg']), n: z.n })).filter(z => isNum(z.v));
    if (!list.length) { empty(nd, o.emptyText || 'No zone data.'); return; }
    const rev = list.slice().reverse();
    const vals = rev.map(z => (o.vsLeague && isNum(z.league) ? z.v - z.league : z.v));
    const traces = [{ type: 'bar', orientation: 'h', y: rev.map(z => z.label), x: vals, text: vals.map(fmt), textposition: 'outside', cliponaxis: false,
      marker: { color: vals.map(v => (scaleRel ? ((v > 0) !== !!o.invert ? C.red : C.blue) : C.accent)) }, hovertemplate: '%{y}: %{text}<extra></extra>' }];
    if (!o.vsLeague && rev.some(z => isNum(z.league))) traces.push({ type: 'scatter', mode: 'markers', y: rev.filter(z => isNum(z.league)).map(z => z.label), x: rev.filter(z => isNum(z.league)).map(z => Number(z.league)),
      marker: { symbol: 'line-ns-open', size: 16, color: C.text, line: { width: 3, color: C.text } }, name: 'League', hovertemplate: 'League %{x:.2f}<extra></extra>' });
    RK.plot(nd, traces, RK.layout({ height: o.height || Math.max(200, list.length * 30 + 60), bargap: 0.3, xaxis: { fixedrange: true, zeroline: true, title: { text: o.label || '', font: { size: 10 } } },
      yaxis: { automargin: true, fixedrange: true }, margin: { l: 110, r: 40, t: 10, b: 36 } }));
    return;
  }
  // hexes -> scatter of hexagons
  const hx = g.hex || g.hexes || g.cells || (Array.isArray(g.points) ? g.points : null);
  if (hx && hx.length) {
    const list = hx.map(h => (Array.isArray(h) ? { x: h[0], y: h[1], v: h[2], n: h[3], league: h[4] } : h)).filter(h => isNum(h.x) && isNum(h.y) && isNum(h.v));
    if (!list.length) { empty(nd, o.emptyText || 'No shot-location data.'); return; }
    const vals = list.map(h => (o.vsLeague && isNum(h.league) ? h.v - h.league : Number(h.v)));
    const dev = Math.max.apply(null, vals.map(v => Math.abs(scaleRel ? v : v - median(vals)))) || 1;
    const nmax = Math.max.apply(null, list.map(h => (isNum(h.n) ? Number(h.n) : 1))) || 1;
    const hgt = o.height || rinkHeight(nd, true, 10);
    const pxPerFt = Math.min((nd.clientWidth || 600) / 103, (hgt - 10) / 87);
    const base = (isNum(g.size) ? Number(g.size) : 4) * 2 * pxPerFt * 0.95;
    const c0 = scaleRel ? 0 : median(vals);
    RK.plot(nd, [{ type: 'scatter', mode: 'markers', x: list.map(h => h.x), y: list.map(h => h.y),
      marker: { symbol: 'hexagon', size: list.map(h => (isNum(h.n) ? base * (0.45 + 0.55 * Math.sqrt(h.n / nmax)) : base)), color: vals, cmin: c0 - dev, cmax: c0 + dev,
        colorscale: divScale(o.invert), line: { width: 0 }, opacity: 0.9, showscale: o.showscale !== false,
        colorbar: { thickness: 8, len: 0.7, tickfont: { size: 9, color: C.text2 }, outlinewidth: 0, title: { text: o.label || '', font: { size: 9, color: C.text2 } } } },
      text: list.map((h, i) => fmt(vals[i]) + (isNum(h.n) ? '<br>n ' + h.n : '')), hovertemplate: '%{text}<extra></extra>' }],
    RK.layout(Object.assign(rinkAxes(true), { height: hgt, shapes: rinkShapes({ half: true, lines: 0.8 }), margin: { l: 4, r: 4, t: o.title ? 22 : 4, b: 4 },
      title: o.title ? { text: o.title, font: { size: 12, color: C.text2 }, x: 0.02 } : undefined })));
    return;
  }
  // matrix -> heatmap over the rink
  let v = g.v || g.values || g.z;
  if (!Array.isArray(v) || !v.length) { empty(nd, o.emptyText || 'No shot-location data.'); return; }
  if (o.vsLeague && Array.isArray(g.league)) v = v.map((r, i) => r.map((x, j) => (isNum(x) && isNum((g.league[i] || [])[j]) ? x - g.league[i][j] : null)));
  const ny = v.length, nx = v[0].length;
  const xs = g.x || Array.from({ length: nx }, (_, i) => (100 * (i + 0.5)) / nx);
  const ys = g.y || Array.from({ length: ny }, (_, i) => -42.5 + (85 * (i + 0.5)) / ny);
  const flat = [];
  v.forEach(r => r.forEach(x => { if (isNum(x)) flat.push(Number(x)); }));
  if (!flat.length) { empty(nd, o.emptyText || 'No shot-location data.'); return; }
  const c0 = scaleRel ? 0 : median(flat);
  const dev = Math.max.apply(null, flat.map(x => Math.abs(x - c0))) || 1;
  const seq = !scaleRel && o.scale === 'seq';
  RK.plot(nd, [{ type: 'heatmap', x: xs, y: ys, z: v, zmin: seq ? Math.min.apply(null, flat) : c0 - dev, zmax: seq ? Math.max.apply(null, flat) : c0 + dev,
    colorscale: seq ? SEQ_SCALE : divScale(o.invert), zsmooth: o.smooth === false ? false : 'best', opacity: 0.75, hoverongaps: false,
    text: v.map(r => r.map(x => (isNum(x) ? fmt(x) : ''))), hovertemplate: '%{text}<extra></extra>',
    colorbar: { thickness: 8, len: 0.7, tickfont: { size: 9, color: C.text2 }, outlinewidth: 0, title: { text: o.label || '', font: { size: 9, color: C.text2 } } } }],
  RK.layout(Object.assign(rinkAxes(true), { height: o.height || rinkHeight(nd, true, 10), shapes: rinkShapes({ half: true, lines: 0.9 }).map(s => Object.assign({}, s, { layer: 'above' })),
    margin: { l: 4, r: 4, t: o.title ? 22 : 4, b: 4 }, title: o.title ? { text: o.title, font: { size: 12, color: C.text2 }, x: 0.02 } : undefined })));
}

// ── on-ice impact quadrant ─────────────────────────────────────────────────

function impactChart(el, pts, opts) {
  const o = opts || {};
  const list = (Array.isArray(pts) ? pts : rows(pts)).map(p => ({ pid: p.pid || p.id, name: p.name, team: p.team, off: Number(first(p, ['off', 'offence', 'offense', 'xgf'])),
    def: Number(first(p, ['def', 'defence', 'defense', 'xga'])), toi: p.toi, pos: p.pos })).filter(p => isNum(p.off) && isNum(p.def));
  if (!list.length) { empty(el, o.emptyText || 'No on-ice impact estimates yet.'); return; }
  const up = o.defUp === true ? 1 : -1;
  const ys = list.map(p => up * p.def);
  const lim = Math.max.apply(null, list.map(p => Math.abs(p.off)).concat(ys.map(Math.abs))) * 1.12 || 0.5;
  const hl = (o.highlight || []).map(String);
  const toiMax = Math.max.apply(null, list.map(p => (isNum(p.toi) ? Number(p.toi) : 0))) || 0;
  const size = p => (toiMax && isNum(p.toi) ? 6 + 10 * Math.sqrt(p.toi / toiMax) : 8);
  const nameOf = p => p.name || (p.pid ? RK.playerName(p.pid) : '');
  const base = list.filter(p => hl.indexOf(String(p.pid)) < 0);
  const top = list.filter(p => hl.indexOf(String(p.pid)) >= 0);
  const labelN = isNum(o.labels) ? Number(o.labels) : (list.length <= 14 ? list.length : 8);
  const ranked = base.slice().sort((a, b) => (Math.abs(b.off) + Math.abs(b.def)) - (Math.abs(a.off) + Math.abs(a.def))).slice(0, labelN).map(p => p.pid);
  const hov = p => '<b>' + esc(nameOf(p)) + '</b>' + (p.team ? ' · ' + esc(RK.teamAbbr(p.team)) : '') + '<br>Offence ' + RK.signed(p.off, 3) + ' xGF/60<br>Defence ' + RK.signed(p.def, 3) + (o.defUp ? '' : ' xGA/60');
  const traces = [{ type: 'scatter', mode: 'markers+text', x: base.map(p => p.off), y: base.map(p => up * p.def), text: base.map(p => (ranked.indexOf(p.pid) >= 0 ? esc(RK.surnameOf(nameOf(p))) : '')),
    textposition: 'top center', textfont: { size: 9, color: C.text2 }, hovertext: base.map(hov), hoverinfo: 'text',
    marker: { size: base.map(size), color: base.map(p => o.colour || (p.team ? RK.teamColour(p.team) : C.accent)), opacity: 0.7, line: { width: 0.5, color: '#0d1117' } } }];
  if (top.length) traces.push({ type: 'scatter', mode: 'markers+text', x: top.map(p => p.off), y: top.map(p => up * p.def), text: top.map(p => '<b>' + esc(RK.surnameOf(nameOf(p))) + '</b>'),
    textposition: 'top center', textfont: { size: 11, color: C.text }, hovertext: top.map(hov), hoverinfo: 'text',
    marker: { size: top.map(p => size(p) + 5), color: C.yellow, line: { width: 2, color: '#0d1117' } } });
  const q = (x, y, t, xa, ya) => ({ x: x, y: y, text: t, showarrow: false, xanchor: xa, yanchor: ya, font: { size: 10, color: C.text3 } });
  RK.plot(el, traces, RK.layout({
    height: o.height || 420,
    shapes: [{ type: 'line', x0: -lim, x1: lim, y0: 0, y1: 0, line: { color: '#30363d', width: 1 } }, { type: 'line', x0: 0, x1: 0, y0: -lim, y1: lim, line: { color: '#30363d', width: 1 } },
      { type: 'rect', x0: 0, x1: lim, y0: 0, y1: lim, fillcolor: 'rgba(63,185,80,0.05)', line: { width: 0 }, layer: 'below' },
      { type: 'rect', x0: -lim, x1: 0, y0: -lim, y1: 0, fillcolor: 'rgba(248,81,73,0.05)', line: { width: 0 }, layer: 'below' }],
    annotations: [q(lim, lim, 'Good both ways', 'right', 'top'), q(-lim, lim, 'Defensive', 'left', 'top'), q(lim, -lim, 'Offensive', 'right', 'bottom'), q(-lim, -lim, 'Struggling', 'left', 'bottom')],
    xaxis: { range: [-lim, lim], zeroline: false, fixedrange: true, title: { text: o.xTitle || 'Offence: xGF/60 impact →', font: { size: 10 } } },
    yaxis: { range: [-lim, lim], zeroline: false, fixedrange: true, title: { text: o.yTitle || (o.defUp ? 'Defence →' : 'Defence: xGA/60 impact (suppression ↑)'), font: { size: 10 } } },
    margin: { l: 56, r: 12, t: 12, b: 44 }
  }));
}

// ── exact scores ───────────────────────────────────────────────────────────

function scoreMatrix(dist, max) {
  const M = max || 7;
  const z = [];
  for (let i = 0; i <= M; i++) { z.push([]); for (let j = 0; j <= M; j++) z[i].push(0); }
  if (!dist) return null;
  // {rows: 'home goals 0-6', cols: 'away goals 0-6', p: [[...]]} (the build's final-score matrix)
  if (!Array.isArray(dist) && typeof dist === 'object' && Array.isArray(dist.p || dist.matrix)) dist = dist.p || dist.matrix;
  let any = false;
  if (Array.isArray(dist) && Array.isArray(dist[0])) {
    dist.forEach((r, i) => r.forEach((p, j) => { if (isNum(p)) { z[Math.min(i, M)][Math.min(j, M)] += Number(p); any = true; } }));
  } else if (dist.home && dist.away && Array.isArray(dist.home)) {
    dist.home.forEach((ph, i) => dist.away.forEach((pa, j) => { if (isNum(ph) && isNum(pa)) { z[Math.min(i, M)][Math.min(j, M)] += ph * pa; any = true; } }));
  } else if (typeof dist === 'object') {
    Object.keys(dist).forEach(k => { const m = /^(\d+)\D+(\d+)$/.exec(k); if (m && isNum(dist[k])) { z[Math.min(Number(m[1]), M)][Math.min(Number(m[2]), M)] += Number(dist[k]); any = true; } });
  }
  return any ? z : null;
}
/* True for a final-score matrix (overtime and shootout winners included: nothing on the tied diagonal). */
function isFinalScores(dist) {
  const z = scoreMatrix(dist, 15);
  if (!z) return false;
  let diag = 0, tot = 0;
  z.forEach((r, i) => r.forEach((p, j) => { tot += p; if (i === j) diag += p; }));
  return tot > 0 && diag / tot < 0.005;
}
function scoreGrid(el, dist, opts) {
  const o = opts || {};
  const src = dist && !Array.isArray(dist) && typeof dist === 'object' && Array.isArray(dist.p || dist.matrix) ? (dist.p || dist.matrix) : dist;
  // a bare n x n matrix is drawn at its own size (its last row is that score exactly, not "or more")
  const bare = Array.isArray(src) && Array.isArray(src[0]);
  const M = o.max || (bare ? src.length - 1 : 7);
  const z = scoreMatrix(src, M);
  if (!z) { empty(el, o.emptyText || 'No score distribution.'); return; }
  const fin = o.final !== undefined ? !!o.final : isFinalScores(src);
  const lab = Array.from({ length: M + 1 }, (_, i) => (i === M && !bare ? M + '+' : String(i)));
  const hn = RK.teamAbbr(o.home), an = RK.teamAbbr(o.away);
  const maxP = Math.max.apply(null, z.map(r => Math.max.apply(null, r))) || 1;
  const shapes = [];
  if (Array.isArray(o.actual) && isNum(o.actual[0]) && isNum(o.actual[1])) {
    const i = Math.min(M, o.actual[0]), j = Math.min(M, o.actual[1]);
    shapes.push({ type: 'rect', x0: j - 0.5, x1: j + 0.5, y0: i - 0.5, y1: i + 0.5, line: { color: C.yellow, width: 2.5 } });
  }
  // the draw diagonal (tied after regulation): goes to overtime (a final-score matrix has none)
  if (!fin) for (let k = 0; k <= M; k++) shapes.push({ type: 'rect', x0: k - 0.5, x1: k + 0.5, y0: k - 0.5, y1: k + 0.5, line: { color: 'rgba(230,237,243,0.25)', width: 1, dash: 'dot' } });
  RK.plot(el, [{ type: 'heatmap', x: lab.map((_, j) => j), y: lab.map((_, i) => i), z: z, zmin: 0, zmax: maxP, colorscale: [[0, 'rgba(92,198,242,0.05)'], [0.6, '#1f6f9f'], [1, '#2a86bd']], showscale: false, xgap: 2, ygap: 2,
    text: z.map(r => r.map(p => (p >= 0.005 ? (p * 100).toFixed(p >= 0.1 ? 0 : 1) : ''))), texttemplate: '%{text}', textfont: { size: 10, color: '#e6edf3' },
    customdata: z.map((r, i) => r.map((p, j) => esc(hn) + ' ' + lab[i] + ', ' + esc(an) + ' ' + lab[j] + ': ' + RK.pct(p, 1))), hovertemplate: '%{customdata}<extra></extra>' }],
  RK.layout({ height: o.height || 300, shapes: shapes,
    xaxis: { tickvals: lab.map((_, j) => j), ticktext: lab, title: { text: esc(an) + (fin ? ' goals (final score)' : ' goals (regulation)'), font: { size: 10 } }, fixedrange: true, showgrid: false, zeroline: false },
    yaxis: { tickvals: lab.map((_, i) => i), ticktext: lab, title: { text: esc(hn) + ' goals', font: { size: 10 } }, fixedrange: true, showgrid: false, zeroline: false },
    margin: { l: 52, r: 8, t: 8, b: 44 } }));
}

// ── percentile sliders (Savant style) ──────────────────────────────────────

function sliderRow(label, p, valueText, title) {
  const known = isNum(p);
  const x = known ? Math.max(0, Math.min(100, Number(p))) : 0;
  const col = RK.pctColor(p);
  return '<div class="ps-row"' + (title ? ' title="' + esc(title) + '"' : '') + '>' +
    '<span class="ps-label">' + label + '</span>' +
    '<span class="ps-track">' + (known
      ? '<span class="ps-fill" style="width:' + x + '%;background:' + col + '"></span><span class="ps-dot" style="left:' + x + '%;background:' + col + '">' + Math.round(p) + '</span>'
      : '<span class="ps-none">below the sample floor</span>') +
    '<i class="ps-tick" style="left:10%"></i><i class="ps-tick mid" style="left:50%"></i><i class="ps-tick" style="left:90%"></i></span>' +
    '<span class="ps-val">' + (valueText === undefined ? '' : valueText) + '</span></div>';
}
function percentileSliders(metrics, vals, pcts, opts) {
  const o = opts || {};
  let list = (metrics || []).filter(m => m && m.key);
  if (o.keys) list = o.keys.map(k => list.find(m => m.key === k)).filter(Boolean);
  if (o.onlyKnown) list = list.filter(m => isNum((pcts || {})[m.key]));
  if (!list.length) return '<div class="muted">No percentiles yet.</div>';
  const row = m => sliderRow((o.glossary === false ? esc(m.label) : '<a class="gl-link" href="' + RK.glossHref(m.key) + '">' + esc(m.label) + '</a>') + (m.lower ? ' <span class="ps-lower" title="Lower is better: the percentile already accounts for it">↓</span>' : ''),
    (pcts || {})[m.key], RK.fmtVal((vals || {})[m.key], m.fmt), (m.desc || '') + (isNum(m.stabilises_at) ? ' · stabilises at about ' + m.stabilises_at : ''));
  let body;
  if (o.groups === false) body = '<div class="ps-group">' + list.map(row).join('') + '</div>';
  else {
    const groups = [];
    list.forEach(m => { const g = m.group || 'Other'; let x = groups.find(z => z.name === g); if (!x) { x = { name: g, items: [] }; groups.push(x); } x.items.push(m); });
    body = groups.map(g => '<div class="ps-group"><div class="ps-group-head">' + esc(g.name) + '</div>' + g.items.map(row).join('') + '</div>').join('');
  }
  return '<div class="ps-panel' + (o.columns === 1 ? ' one' : '') + '">' + body + '</div>' +
    '<div class="ps-legend"><span><i style="background:' + RK.pctColor(5) + '"></i>Poor</span><span><i style="background:' + RK.pctColor(50) + '"></i>Average</span><span><i style="background:' + RK.pctColor(95) + '"></i>Great</span>' +
    (o.note ? '<span class="ps-note">' + o.note + '</span>' : '') + '</div>';
}

// ── linescore ──────────────────────────────────────────────────────────────

function linescore(g, opts) {
  const o = opts || {};
  if (!g) return '';
  const ps = RK.periodsOf(g);
  const n = Math.max(3, ps.length);
  const playoff = RK.isPlayoffGame(g);
  let sog = g.sog || g.shots_on_goal || null;
  if (!sog && ps.length && ps.some(r => isNum(r.sog_home))) sog = { home: ps.reduce((a, r) => a + (Number(r.sog_home) || 0), 0), away: ps.reduce((a, r) => a + (Number(r.sog_away) || 0), 0) };
  const cell = (v, cls) => '<td class="' + (cls || '') + '">' + (v === null || v === undefined ? '' : esc(v)) + '</td>';
  // the two teams' bars in colours that can be told apart (the same pair as the xG race, WP chart and shot maps)
  const pc = o.colours || RK.pairColours(g.home, g.away);
  const row = (t, side) => {
    const col = side === 'home' ? pc[0] : pc[1];
    let h = '<tr><th class="ls-team">' + (o.link === false ? RK.teamBar(t, col) + esc(RK.teamAbbr(t)) : RK.teamLink(t, { abbr: true, colour: col })) + '</th>';
    for (let i = 0; i < n; i++) { const v = ps[i] ? ps[i][side] : null; h += cell(v, Number(v) > 0 ? 'ls-run' : ''); }
    const tot = side === 'away' ? g.as : g.hs;
    h += cell(isNum(tot) ? tot : (ps.length ? ps.reduce((s, r) => s + (Number(r[side]) || 0), 0) : ''), 'ls-r');
    if (sog) h += cell(isNum(sog[side]) ? sog[side] : '', 'ls-sog');
    return h + '</tr>';
  };
  let head = '<tr><th></th>';
  for (let i = 0; i < n; i++) head += '<th>' + esc(ps[i] && ps[i].label ? String(ps[i].label).replace(/ period$/, '') : RK.periodLabel(i + 1, { playoff: playoff })) + '</th>';
  head += '<th class="ls-r">T</th>' + (sog ? '<th class="ls-sog" title="Shots on goal">SOG</th>' : '') + '</tr>';
  return '<div class="table-wrap"><table class="linescore"><thead>' + head + '</thead><tbody>' + row(g.away, 'away') + row(g.home, 'home') + '</tbody></table></div>';
}

// ── generic ────────────────────────────────────────────────────────────────

function distBars(el, dist, opts) {
  const o = opts || {};
  let entries;
  if (Array.isArray(dist)) entries = dist.map((p, k) => (Array.isArray(p) ? [Number(p[0]), p[1]] : [k + (o.offset || 0), p]));
  else entries = Object.keys(dist || {}).map(k => [Number(k), dist[k]]);
  entries = entries.filter(e => isNum(e[0]) && isNum(e[1]) && e[1] > 0.0005).sort((a, b) => a[0] - b[0]);
  if (!entries.length) { empty(el, o.emptyText || 'No distribution.'); return; }
  const col = o.colour || C.accent;
  const shapes = [];
  if (isNum(o.line)) shapes.push({ type: 'line', x0: o.line, x1: o.line, yref: 'paper', y0: 0, y1: 1, line: { color: C.text2, width: 1.5, dash: 'dash' } });
  if (isNum(o.exp)) shapes.push({ type: 'line', x0: o.exp, x1: o.exp, yref: 'paper', y0: 0, y1: 1, line: { color: col, width: 1.5, dash: 'dot' } });
  const ks = entries.map(e => e[0]);
  const colourOf = k => {
    if (isNum(o.actual) && Number(k) === Number(o.actual)) return C.text;
    if (o.split !== undefined && o.split !== null) return k > o.split ? hexA(o.colours ? o.colours[0] : col, 0.85) : (k < o.split ? hexA(o.colours ? o.colours[1] : C.p2, 0.85) : hexA(C.text3, 0.8));
    return hexA(col, 0.8);
  };
  RK.plot(el, [{ type: 'bar', x: ks, y: entries.map(e => e[1]), marker: { color: ks.map(colourOf) },
    hovertemplate: (o.signed ? '%{x:+d}' : '%{x}') + ' ' + esc(o.unit || 'goals') + ': %{y:.1%}<extra></extra>' }], RK.layout({
    height: o.height || 220, bargap: 0.12, shapes: shapes,
    xaxis: { title: o.xTitle || '', fixedrange: true, dtick: ks.length > 40 ? 7 : (ks.length > 24 ? 4 : (ks.length > 14 ? 2 : 1)), tickformat: o.signed ? '+d' : 'd' },
    yaxis: { tickformat: '.0%', fixedrange: true },
    margin: { l: 44, r: 10, t: 10, b: o.xTitle ? 42 : 28 }
  }));
}
function heatTable(spec) {
  const s = spec || {};
  const rws = s.rows || [];
  if (!rws.length) return '<div class="muted">No data.</div>';
  const nCols = Math.max.apply(null, rws.map(r => (r.values || []).length));
  const centers = [];
  for (let i = 0; i < nCols; i++) {
    if (s.center !== 'col') { centers.push(isNum(s.center) ? s.center : 0); continue; }
    const col = rws.map(r => (r.values || [])[i]).filter(isNum).sort((a, b) => a - b);
    centers.push(col.length ? col[Math.floor(col.length / 2)] : 0);
  }
  const vals = [];
  rws.forEach(r => (r.values || []).forEach((v, i) => { if (isNum(v)) vals.push(Math.abs(v - centers[i])); }));
  vals.sort((a, b) => a - b);
  const max = s.max || vals[Math.floor(vals.length * 0.95)] || vals[vals.length - 1] || 1;
  const fmt = s.fmt || (v => RK.num(v, 2));
  const colour = (v, i) => (s.scale === 'seq' ? RK.seqColour(v / (s.max || (vals[vals.length - 1] || 1))) : RK.divColour(v - centers[i], max, s.invert));
  let h = '<div class="table-wrap heat-wrap"' + (s.maxWidth ? ' style="max-width:' + s.maxWidth + 'px"' : '') + '><table class="wc-table heat-table"><thead><tr><th class="heat-corner">' + esc(s.corner || '') + '</th>';
  (s.cols || []).forEach(c => { const cc = typeof c === 'object' ? c : { label: c }; h += '<th' + (cc.title ? ' title="' + esc(cc.title) + '"' : '') + '>' + esc(cc.label) + '</th>'; });
  h += '</tr></thead><tbody>';
  rws.forEach(r => {
    h += '<tr><td class="heat-label">' + (r.label || '') + '</td>';
    (r.values || []).forEach((v, i) => {
      const t = r.titles && r.titles[i] ? ' title="' + esc(r.titles[i]) + '"' : '';
      h += isNum(v) ? '<td class="heat-cell" style="background:' + colour(v, i) + '"' + t + '>' + fmt(v, i) + '</td>' : '<td class="heat-cell heat-empty"' + t + '>·</td>';
    });
    h += '</tr>';
  });
  return h + '</tbody></table></div>';
}
function probBars(el, items, opts) {
  const o = opts || {};
  const list = (items || []).filter(i => isNum(i.p) && (i.p > 0 || isNum(i.market))).slice(0, o.top || 12);
  if (!list.length) { empty(el, o.emptyText || 'Nothing to show.'); return; }
  const rev = list.slice().reverse();
  const max = Math.max.apply(null, list.map(i => Math.max(i.p || 0, i.market || 0)));
  const traces = [{
    type: 'bar', orientation: 'h', y: rev.map(i => i.label), x: rev.map(i => i.p), name: o.modelName || 'Model',
    text: rev.map(i => RK.pct(i.p)), textposition: 'outside', cliponaxis: false, textfont: { color: C.text, size: 11 },
    marker: { color: rev.map(i => i.colour || C.accent) }, showlegend: false, hovertemplate: '%{y}: %{x:.1%}<extra>' + (o.modelName || 'Model') + '</extra>'
  }];
  if (list.some(i => isNum(i.market))) {
    const mk = rev.filter(i => isNum(i.market));
    traces.push({ type: 'scatter', mode: 'markers', name: o.marketName || 'Market', y: mk.map(i => i.label), x: mk.map(i => i.market),
      marker: { symbol: 'line-ns-open', size: 18, color: C.text, line: { width: 3, color: C.text } }, hovertemplate: '%{y}: %{x:.1%}<extra>' + (o.marketName || 'Market') + '</extra>' });
  }
  RK.plot(el, traces, RK.layout({
    height: o.height || Math.max(220, list.length * 28 + 50), bargap: 0.3,
    xaxis: { tickformat: '.0%', range: [0, Math.min(1.08, max * 1.25 + 0.02)], fixedrange: true },
    yaxis: { automargin: true, fixedrange: true, tickfont: { size: 11 } },
    showlegend: traces.length > 1, legend: { orientation: 'h', y: -0.12, font: { color: C.text2 } },
    margin: { l: 110, r: 50, t: 10, b: 35 }
  }));
}
function lines(el, series, opts) {
  const o = opts || {};
  const list = (series || []).filter(s => (s.y || []).length);
  if (!list.length) { empty(el, o.emptyText || 'No data.'); return; }
  const traces = [];
  list.forEach((s, i) => {
    const col = s.colour || RK.PALETTE[i % RK.PALETTE.length];
    const x = s.x || s.y.map((_, k) => k + 1);
    if (s.band && s.band[0] && s.band[1]) {
      traces.push({ type: 'scatter', mode: 'lines', x: x, y: s.band[1], line: { width: 0, color: col }, hoverinfo: 'skip', showlegend: false });
      traces.push({ type: 'scatter', mode: 'lines', x: x, y: s.band[0], line: { width: 0, color: col }, fill: 'tonexty', fillcolor: hexA(col, 0.15), hoverinfo: 'skip', showlegend: false });
    }
    traces.push({
      type: 'scatter', mode: s.mode || o.mode || 'lines', name: s.name, x: x, y: s.y,
      line: { color: col, width: s.width || 2, dash: s.dash || 'solid', shape: s.shape || 'linear' },
      marker: { size: 5, color: col }, connectgaps: true, text: s.text,
      error_y: s.err ? { type: 'data', array: s.err, visible: true, color: col, thickness: 1, width: 0 } : undefined,
      hovertemplate: s.hover || (esc(s.name) + ' · %{y}<extra></extra>')
    });
  });
  RK.plot(el, traces, RK.layout(Object.assign({
    height: o.height || 380, showlegend: o.legend !== false,
    legend: { orientation: 'h', y: -0.2, font: { size: 10, color: C.text2 } },
    xaxis: Object.assign({ title: o.xTitle || '' }, o.xaxis || {}), yaxis: Object.assign({ title: o.yTitle || '' }, o.yaxis || {}),
    margin: { l: 55, r: 20, t: 20, b: 55 }
  }, o.layout || {})));
}
function radar(el, series, opts) {
  const o = opts || {};
  const labels = o.labels || [];
  const list = (series || []).filter(s => (s.values || []).some(isNum));
  if (!list.length || !labels.length) { empty(el, o.emptyText || 'Not enough data for a radar.'); return; }
  const traces = list.map((s, i) => {
    const col = s.colour || RK.PALETTE[i % RK.PALETTE.length];
    const r = s.values.map(v => (isNum(v) ? v : 0));
    return { type: 'scatterpolar', r: r.concat([r[0]]), theta: labels.concat([labels[0]]), name: s.name, fill: 'toself',
      fillcolor: hexA(col, 0.18), line: { color: col, width: 2 }, hovertemplate: '%{theta}: %{r:.0f}<extra>' + esc(s.name || '') + '</extra>' };
  });
  RK.plot(el, traces, RK.layout({
    height: o.height || 360,
    polar: { bgcolor: 'rgba(0,0,0,0)', radialaxis: { range: [0, 100], tickvals: [25, 50, 75, 100], gridcolor: '#30363d', tickfont: { size: 8, color: C.text3 }, angle: 90 },
      angularaxis: { gridcolor: '#30363d', tickfont: { size: 10, color: C.text2 }, direction: 'clockwise' } },
    showlegend: list.length > 1, legend: { orientation: 'h', y: -0.08, font: { size: 10, color: C.text2 } },
    margin: { l: 50, r: 50, t: 30, b: 30 }
  }));
}

RK.charts = Object.assign(RK.charts || {}, {
  rows: rows, rinkShapes: rinkShapes, rinkAxes: rinkAxes, rinkHeight: rinkHeight, boardY: boardY, shotRows: shotRows, shotMap: shotMap,
  xgRace: xgRace, wpRows: wpRows, wpChart: wpChart, shotHeatmap: shotHeatmap, impactChart: impactChart, scoreGrid: scoreGrid, scoreMatrix: scoreMatrix, isFinalScores: isFinalScores,
  percentileSliders: percentileSliders, sliderRow: sliderRow, linescore: linescore, distBars: distBars, heatTable: heatTable, probBars: probBars,
  lines: lines, radar: radar, hexA: hexA, median: median, mean: mean, DIV_SCALE: DIV_SCALE, SEQ_SCALE: SEQ_SCALE
});
})(window.RK);
