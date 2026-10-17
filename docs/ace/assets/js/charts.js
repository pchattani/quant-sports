/* The Quant Ace — shared chart helpers (TA.charts).
 *
 * Every helper takes a target (element or id) first and degrades to a muted line when its
 * data is missing. Colours: TA.C.p1 (ace yellow) for the first player, TA.C.p2 (blue) for the second.
 *
 *   bracketModel(draw)                 the draw as columns: {rounds, size, leaves:[{slot,pid,seed,entry}],
 *                                      cols: [[{r, j, lo, hi, a, b, card, winner}]]} (lo/hi = leaf range of the match)
 *   bracket(el, draw, opts)            interactive draw. opts {tour, sim: {pid: {reach:{round:p}}}, picked: pid,
 *                                      onPick(pid|null), section: 'all'|0..3, narrow (auto under 720 px)}
 *                                      Click a player to highlight their path; returns {pick(pid), model}.
 *   pathOdds(model, sim, pid)          [{round, p_reach, opponents:[[pid, p]], match}] along pid's path
 *   wpChart(el, wp, opts)              wp [[i, set, g1, g2, p1]] game by game; opts {tour, p1, p2, swings, market, height}
 *   setDist(el, sets, opts)            sets {"2-0": p, ...} from p1's view; opts {tour, p1, p2, actual:"2-1", height}
 *   gamesDist(el, dist, opts)          dist {n: p}; opts {actual, exp, line, xTitle, colour, height, signed}
 *   eloLines(el, series, opts)         series [{name, rows:[[date, elo]], colour, dash}]; opts {height, yTitle}
 *   surfaceRadar(el, series, opts)     series [{name, values:{hard, clay, grass[, indoor]}, colour}]; opts {height, range}
 *   heatTable(spec)                    HTML: {cols, rows:[{label(html), values, titles}], fmt, scale:'div'|'seq', max, invert, corner, center}
 *   probBars(el, items, opts)          items [{label, p, colour, market}] horizontal bars, market as a tick
 *   lines(el, series, opts)            series [{name, x, y, colour, dash, width, err, band:[lo,hi]}]
 *   radar(el, series, opts)            series [{name, values:[0-100], colour}]; opts {labels, height}
 *   hexA(hex, a)                       rgba string
 */
(function (TA) {
'use strict';

const C = TA.C;
const esc = TA.esc;

function node(el) { return typeof el === 'string' ? document.getElementById(el) : el; }
function empty(el, text) { const n = node(el); if (n) n.innerHTML = '<div class="muted">' + text + '</div>'; }
function hexA(hex, a) {
  const h = String(hex || '').replace('#', '');
  if (h.length !== 6) return TA.alpha ? TA.alpha(hex, a) : 'rgba(139,148,158,' + a + ')';
  return 'rgba(' + parseInt(h.slice(0, 2), 16) + ',' + parseInt(h.slice(2, 4), 16) + ',' + parseInt(h.slice(4, 6), 16) + ',' + a + ')';
}
const ROUNDS_ALL = ['R128', 'R64', 'R32', 'R16', 'QF', 'SF', 'F'];

// ── the draw ───────────────────────────────────────────────────────────────

function log2(n) { return Math.round(Math.log(n) / Math.LN2); }

function bracketModel(draw) {
  const d = draw || {};
  const rawSlots = (d.slots || []).filter(s => Array.isArray(s));
  const cards = d.matches || {};
  const list = Object.keys(cards).map(k => cards[k]).filter(c => c && c.round && ROUNDS_ALL.indexOf(c.round) >= 0);
  let size = Number(d.size) || 0;
  if (!size && rawSlots.length) size = Math.pow(2, Math.ceil(log2(Math.max.apply(null, rawSlots.map(s => s[0])))));
  if (!size) return null;
  const nR = log2(size);
  let rounds = (d.rounds && d.rounds.length === nR) ? d.rounds.slice() : ROUNDS_ALL.slice(ROUNDS_ALL.length - nR);
  if (rounds.length !== nR) rounds = ROUNDS_ALL.slice(Math.max(0, ROUNDS_ALL.length - nR));
  const leaves = [];
  for (let i = 0; i < size; i++) leaves.push({ slot: i + 1, pid: null, seed: null, entry: null });
  rawSlots.forEach(s => { const i = Number(s[0]) - 1; if (i >= 0 && i < size) leaves[i] = { slot: i + 1, pid: s[1] || null, seed: s[2] || null, entry: s[3] || null }; });
  const leafOf = {};
  leaves.forEach((l, i) => { if (l.pid) leafOf[l.pid] = i; });
  const byRound = {};
  list.forEach(c => { (byRound[c.round] = byRound[c.round] || []).push(c); });
  // A slot the source left empty (a seed whose name was not resolved, say) is filled from a later match:
  // the unknown player sits in the half of that match's block opposite their known opponent.
  for (let r = 0; r < nR; r++) {
    const span = Math.pow(2, r + 1);
    (byRound[rounds[r]] || []).forEach(c => {
      const k1 = leafOf[c.p1] !== undefined, k2 = leafOf[c.p2] !== undefined;
      if (k1 === k2) return;
      const known = k1 ? c.p1 : c.p2, unknown = k1 ? c.p2 : c.p1;
      if (!unknown) return;
      const li = leafOf[known], lo = Math.floor(li / span) * span, mid = lo + span / 2;
      const oLo = li < mid ? mid : lo, oHi = li < mid ? lo + span - 1 : mid - 1;
      let pick = -1;
      for (let k = oLo; k <= oHi; k++) if (!leaves[k].pid && leaves[k].seed) { pick = k; break; }
      if (pick < 0) for (let k = oLo; k <= oHi; k++) if (!leaves[k].pid) { pick = k; break; }
      if (pick >= 0) { leaves[pick].pid = unknown; leaves[pick].filled = true; leafOf[unknown] = pick; }
    });
  }
  const inRange = (pid, lo, hi) => pid && leafOf[pid] !== undefined && leafOf[pid] >= lo && leafOf[pid] <= hi;
  const cols = [];
  let occ = leaves.map(l => l.pid);
  for (let r = 0; r < nR; r++) {
    const span = Math.pow(2, r + 1), col = [], next = [];
    for (let j = 0; j < size / span; j++) {
      const lo = j * span, hi = lo + span - 1, mid = lo + span / 2;
      let a = occ[2 * j] || null, b = occ[2 * j + 1] || null;
      const card = (byRound[rounds[r]] || []).find(c =>
        (inRange(c.p1, lo, mid - 1) && inRange(c.p2, mid, hi)) || (inRange(c.p2, lo, mid - 1) && inRange(c.p1, mid, hi))) || null;
      if (card) {
        if (inRange(card.p1, lo, mid - 1)) { a = card.p1; b = card.p2; } else { a = card.p2; b = card.p1; }
      }
      let winner = card && card.winner ? card.winner : null;
      // a bye: the other half of the first round is empty and nobody from it plays later
      const bye = r === 0 && !card && ((a && !b) || (b && !a));
      if (bye) winner = a || b;
      col.push({ r: r, j: j, lo: lo, hi: hi, a: a, b: b, card: card, winner: winner, bye: bye });
      next.push(winner);
    }
    // a later-round card names the occupant even when the earlier result is missing
    if (r + 1 < nR) {

      (byRound[rounds[r + 1]] || []).forEach(c => {
        [c.p1, c.p2].forEach(pid => {
          if (!pid || leafOf[pid] === undefined) return;
          const j = Math.floor(leafOf[pid] / span);
          if (!next[j]) next[j] = pid;
        });
      });

    }
    cols.push(col);
    occ = next;
  }
  const champion = cols.length ? cols[cols.length - 1][0].winner : null;
  return { rounds: rounds, size: size, leaves: leaves, leafOf: leafOf, cols: cols, champion: champion };
}

/* Along pid's path: for each round from the first, P(reach it), the likeliest opponents there, and the match. */
function pathOdds(model, sim, pid) {
  if (!model || !pid || model.leafOf[pid] === undefined) return [];
  const li = model.leafOf[pid];
  const S = sim || {};
  const reachOf = (q, rnd) => { const x = S[q]; if (!x || !x.reach) return null; const v = x.reach[rnd]; return TA.isNum(v) ? Number(v) : null; };
  const out = [];
  for (let r = 0; r < model.cols.length; r++) {
    const span = Math.pow(2, r + 1), j = Math.floor(li / span);
    const m = model.cols[r][j];
    const mid = m.lo + span / 2;
    const mine = li < mid;
    const oLo = mine ? mid : m.lo, oHi = mine ? m.hi : mid - 1;
    const rnd = model.rounds[r];
    const opps = [];
    for (let k = oLo; k <= oHi; k++) {
      const q = model.leaves[k].pid;
      if (!q) continue;
      const p = reachOf(q, rnd);
      if (p !== null && p > 0) opps.push([q, p]);
    }
    opps.sort((x, y) => y[1] - x[1]);
    const known = mine ? m.b : m.a;
    out.push({ round: rnd, p_reach: reachOf(pid, rnd), p_win: reachOf(pid, r + 1 < model.rounds.length ? model.rounds[r + 1] : 'W'),
      opponents: known && m.card ? [[known, 1]] : opps.slice(0, 4), match: m });
  }
  return out;
}

function bracket(el, draw, opts) {
  const root = node(el);
  if (!root) return null;
  const o = opts || {};
  const T = o.tour || TA.state.tour;
  const model = bracketModel(draw);
  if (!model || !model.cols.length) { root.innerHTML = '<div class="muted">The draw is not available yet.</div>'; return null; }
  const sim = o.sim || {};
  let picked = o.picked || null;
  let roundSel = null;
  const nQ = model.size >= 64 ? 4 : (model.size >= 32 ? 2 : 1);
  const qSize = model.size / nQ;
  // big draws open on one quarter (the picked player's), small ones whole
  let section = o.section !== undefined ? o.section : (model.size >= 64 ? (picked && model.leafOf[picked] !== undefined ? String(Math.floor(model.leafOf[picked] / qSize)) : '0') : 'all');
  const seedOf = pid => { const i = model.leafOf[pid]; return i === undefined ? null : model.leaves[i].seed; };
  const entryOf = pid => { const i = model.leafOf[pid]; return i === undefined ? null : model.leaves[i].entry; };

  const nameRow = (m, pid, side) => {
    const nextR = m.r + 1 < model.rounds.length ? model.rounds[m.r + 1] : 'W';
    const c = m.card;
    const lost = m.winner && pid && m.winner !== pid;
    const won = m.winner && pid && m.winner === pid;
    let score = '';
    if (c && c.sets && c.sets.length) {
      const flip = c.p1 !== pid;
      score = c.sets.map(s => {
        const g = flip ? s[1] : s[0], og = flip ? s[0] : s[1];
        const tb = flip ? s[3] : s[2];
        return '<span class="br-g' + (g > og ? ' w' : '') + '">' + g + (TA.isNum(tb) && g < og ? '<sup>' + tb + '</sup>' : '') + '</span>';
      }).join('');
      if (c.status === 'ret' && lost) score += '<span class="br-g r">ret</span>';
    } else if (c && c.status === 'wo' && lost) score = '<span class="br-g r">w/o</span>';
    else if (c && c.live && c.live.games && TA.matchState(c) === 'live') score = '<span class="br-g cur">' + c.live.games[side] + '</span>';
    let p = '';
    if (!m.winner && pid && sim[pid] && sim[pid].reach && TA.isNum(sim[pid].reach[nextR])) p = '<span class="br-p" title="Model probability of winning this match (reaching ' + esc(TA.roundLabel(nextR)) + ')">' + TA.pct(sim[pid].reach[nextR], 0) + '</span>';
    const sd = pid ? seedOf(pid) : null, en = pid ? entryOf(pid) : null;
    const label = pid ? esc(TA.playerSurname(T, pid)) : (m.r === 0 && m.bye ? '<span class="br-bye">bye</span>' : '<span class="br-tbd">TBD</span>');
    return '<div class="br-pl' + (lost ? ' out' : '') + (won ? ' won' : '') + (pid && pid === picked ? ' hl' : '') + '"' + (pid ? ' data-pid="' + esc(pid) + '"' : '') + '>' +
      '<span class="br-seed">' + (sd ? sd : (en ? esc(en) : '')) + '</span><span class="br-nm" title="' + (pid ? esc(TA.playerName(T, pid)) : '') + '">' + label + '</span>' +
      '<span class="br-sc">' + score + '</span>' + p + '</div>';
  };
  const box = m => {
    const onPath = picked && (m.a === picked || m.b === picked);
    const live = m.card && TA.matchState(m.card) === 'live';
    return '<div class="br-m' + (m.winner ? ' done' : '') + (live ? ' live' : '') + (onPath ? ' path' : '') + '">' +
      nameRow(m, m.a, 0) + nameRow(m, m.b, 1) +
      (m.card ? '<a class="br-link" href="' + TA.matchHref(T, m.card.id) + '" title="Match centre">' + (live ? '<span class="live-dot"></span>' : '↗') + '</a>' : '') + '</div>';
  };
  const inSection = m => section === 'all' || (m.hi >= Number(section) * qSize && m.lo <= (Number(section) + 1) * qSize - 1);

  const draw_ = () => {
    const narrow = o.narrow !== undefined ? o.narrow : (root.clientWidth || 1000) < 720;
    const secBar = nQ > 1 ? '<div class="toggle-row br-sec">' + TA.toggles([{ key: 'all', label: 'Whole draw' }].concat(
      Array.from({ length: nQ }, (_, i) => ({ key: String(i), label: (nQ === 4 ? 'Quarter ' : 'Half ') + (i + 1) }))), String(section), 'data-sec') + '</div>' : '';
    let firstOpen = 0;
    model.cols.forEach((col, r) => { if (col.some(m => !m.winner && (m.a || m.b))) { if (!firstOpen) firstOpen = r; } });
    if (firstOpen === 0 && model.cols[0].every(m => m.winner)) firstOpen = model.cols.length - 1;
    if (roundSel === null) roundSel = narrow ? firstOpen : 0;
    let html = secBar;
    if (narrow) {
      html += '<div class="toggle-row br-rounds">' + TA.toggles(model.rounds.map((r, i) => ({ key: String(i), label: TA.roundLabel(r, true) })), String(roundSel), 'data-rd') + '</div>';
      const col = model.cols[roundSel].filter(inSection);
      html += '<div class="br-list"><div class="br-title">' + esc(TA.roundLabel(model.rounds[roundSel])) + '</div>' + (col.map(box).join('') || '<div class="muted">No matches.</div>') + '</div>';
    } else {
      html += '<div class="bracket-wrap"><div class="bracket ta-bracket">' + model.cols.map((col, r) => {
        const ms = col.filter(inSection);
        return '<div class="br-round"><div class="br-title">' + esc(TA.roundLabel(model.rounds[r], true)) + '</div><div class="br-col">' + ms.map(box).join('') + '</div></div>';
      }).join('') + (model.champion ? '<div class="br-round br-champ"><div class="br-title">Champion</div><div class="br-col"><div class="br-m done champ">' +
        '<div class="br-pl won' + (picked === model.champion ? ' hl' : '') + '" data-pid="' + esc(model.champion) + '"><span class="br-seed">🏆</span><span class="br-nm">' + esc(TA.playerName(T, model.champion)) + '</span></div></div></div></div>' : '') +
        '</div></div>';
    }
    root.innerHTML = html;
    TA.wireToggles(root.querySelector('.br-sec'), 'data-sec', k => { section = k; draw_(); });
    TA.wireToggles(root.querySelector('.br-rounds'), 'data-rd', k => { roundSel = Number(k); draw_(); });
    root.querySelectorAll('.br-pl[data-pid]').forEach(x => x.addEventListener('click', ev => {
      if (ev.target.closest('a')) return;
      const pid = x.getAttribute('data-pid');
      api.pick(picked === pid ? null : pid);
    }));
  };
  const api = {
    model: model,
    pick: pid => {
      picked = pid || null;
      if (picked && section !== 'all' && model.leafOf[picked] !== undefined) section = String(Math.floor(model.leafOf[picked] / qSize));
      draw_();
      if (typeof o.onPick === 'function') o.onPick(picked);
    },
    redraw: () => draw_()
  };
  draw_();
  let lastW = root.clientWidth;
  const onResize = () => { if (!root.isConnected) return; const w = root.clientWidth; if ((w < 720) !== (lastW < 720)) { roundSel = null; draw_(); } lastW = w; };
  window.addEventListener('resize', onResize);
  TA.onLeave(() => window.removeEventListener('resize', onResize));
  return api;
}

// ── win probability by game ────────────────────────────────────────────────

function wpChart(el, wp, opts) {
  const o = opts || {};
  const T = o.tour || TA.state.tour;
  const rows = (wp || []).filter(r => Array.isArray(r) && TA.isNum(r[0]) && TA.isNum(r[4]));
  if (rows.length < 2) { empty(el, o.emptyText || 'No win-probability path for this match yet.'); return; }
  const n1 = o.p1 ? TA.playerSurname(T, o.p1) : 'Player 1', n2 = o.p2 ? TA.playerSurname(T, o.p2) : 'Player 2';
  const x = rows.map(r => r[0]), y = rows.map(r => r[4]);
  const txt = rows.map((r, i) => (i === 0 ? 'Pre-match' : 'Set ' + r[1] + ' · ' + r[2] + '-' + r[3]) + ' · ' + esc(n1) + ' ' + TA.pct(r[4], 1));
  const shapes = [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 0.5, y1: 0.5, line: { color: '#30363d', width: 1 } }];
  const ann = [];
  let prev = rows[0][1];

  const setStarts = [[rows[0][0], rows[0][1]]];
  rows.forEach((r, i) => {
    if (i > 0 && r[1] !== prev) {
      const xb = rows[i - 1][0] + 0.5;
      shapes.push({ type: 'line', x0: xb, x1: xb, yref: 'paper', y0: 0, y1: 1, line: { color: '#3d444d', width: 1, dash: 'dot' }, layer: 'below' });
      setStarts.push([xb, r[1]]);
      prev = r[1];
    }
  });
  setStarts.forEach((s, i) => {
    const end = i + 1 < setStarts.length ? setStarts[i + 1][0] : rows[rows.length - 1][0];
    ann.push({ x: (s[0] + end) / 2, y: 1.04, yref: 'paper', text: 'Set ' + s[1], showarrow: false, font: { size: 10, color: C.text3 } });
  });

  const traces = [
    { type: 'scatter', mode: 'lines', x: x, y: x.map(() => 0.5), line: { width: 0 }, hoverinfo: 'skip', showlegend: false },
    { type: 'scatter', mode: 'lines', x: x, y: y.map(v => Math.max(v, 0.5)), fill: 'tonexty', fillcolor: hexA(C.p1, 0.22), line: { width: 0 }, hoverinfo: 'skip', showlegend: false },
    { type: 'scatter', mode: 'lines', x: x, y: x.map(() => 0.5), line: { width: 0 }, hoverinfo: 'skip', showlegend: false },
    { type: 'scatter', mode: 'lines', x: x, y: y.map(v => Math.min(v, 0.5)), fill: 'tonexty', fillcolor: hexA(C.p2, 0.22), line: { width: 0 }, hoverinfo: 'skip', showlegend: false },
    { type: 'scatter', mode: 'lines+markers', x: x, y: y, name: 'Win probability', line: { color: C.text, width: 1.8, shape: 'linear' },
      marker: { size: 4, color: y.map(v => (v >= 0.5 ? C.p1 : C.p2)) }, text: txt, hovertemplate: '%{text}<extra></extra>' }
  ];
  const sw = (o.swings || []).filter(s => TA.isNum(s.i)).slice(0, o.top || 5);
  if (sw.length) {
    const at = i => { const r = rows.find(z => z[0] === i); return r ? r[4] : null; };
    const pts = sw.map((s, k) => ({ x: s.i, y: at(s.i), k: k + 1, s: s })).filter(p => p.y !== null);
    traces.push({ type: 'scatter', mode: 'markers+text', x: pts.map(p => p.x), y: pts.map(p => p.y), text: pts.map(p => String(p.k)), textposition: 'top center',
      textfont: { size: 10, color: C.text }, marker: { size: 10, color: pts.map(p => (p.s.delta > 0 ? C.p1 : C.p2)), line: { width: 1.5, color: '#0d1117' } },
      hovertext: pts.map(p => 'Swing ' + p.k + ': ' + esc(p.s.kind || '') + ' · set ' + p.s.set + ' · ' + (p.s.games ? p.s.games.join('-') : '') + ' · ' + TA.signed((p.s.delta || 0) * 100, 1) + ' pp'),
      hoverinfo: 'text', showlegend: false });
  }
  if (TA.isNum(o.market)) shapes.push({ type: 'line', x0: rows[0][0] - 0.4, x1: rows[0][0] + 0.4, y0: o.market, y1: o.market, line: { color: C.text, width: 3 } });
  TA.plot(el, traces, TA.layout({
    height: o.height || 300, shapes: shapes, annotations: ann,
    xaxis: { title: '', showgrid: false, fixedrange: true, zeroline: false, tickfont: { size: 9 } },
    yaxis: { range: [0, 1], tickvals: [0, 0.25, 0.5, 0.75, 1], ticktext: [n2 + ' 100%', '75%', '50%', '75%', n1 + ' 100%'], fixedrange: true, automargin: true },
    margin: { l: 80, r: 10, t: 22, b: 30 }
  }));
}

// ── distributions ──────────────────────────────────────────────────────────

function setOrder(keys) {
  return keys.slice().sort((a, b) => {
    const pa = a.split('-').map(Number), pb = b.split('-').map(Number);
    const wa = pa[0] > pa[1], wb = pb[0] > pb[1];
    if (wa !== wb) return wa ? -1 : 1;
    return wa ? pa[1] - pb[1] : pb[0] - pa[0];
  });
}
function setDist(el, sets, opts) {
  const o = opts || {};
  const T = o.tour || TA.state.tour;
  const keys = setOrder(Object.keys(sets || {}).filter(k => TA.isNum(sets[k])));
  if (!keys.length) { empty(el, 'No set-score distribution.'); return; }
  const n1 = o.p1 ? TA.playerSurname(T, o.p1) : 'P1', n2 = o.p2 ? TA.playerSurname(T, o.p2) : 'P2';
  const lab = k => { const p = k.split('-').map(Number); return p[0] > p[1] ? n1 + ' ' + k : n2 + ' ' + p[1] + '-' + p[0]; };
  TA.plot(el, [{ type: 'bar', x: keys.map(lab), y: keys.map(k => sets[k]), text: keys.map(k => TA.pct(sets[k], 0)), textposition: 'outside', cliponaxis: false,
    textfont: { size: 11, color: C.text },
    marker: { color: keys.map(k => { const p = k.split('-').map(Number); return p[0] > p[1] ? C.p1 : C.p2; }),
      line: { width: keys.map(k => (k === o.actual ? 3 : 0)), color: C.text } },
    hovertemplate: '%{x}: %{y:.1%}<extra></extra>' }], TA.layout({
    height: o.height || 230, bargap: 0.25,
    xaxis: { type: 'category', fixedrange: true, tickfont: { size: 10 } },
    yaxis: { tickformat: '.0%', fixedrange: true, range: [0, Math.max.apply(null, keys.map(k => sets[k])) * 1.25] },
    margin: { l: 44, r: 10, t: 14, b: 40 }
  }));
}
function gamesDist(el, dist, opts) {
  const o = opts || {};
  const ks = Object.keys(dist || {}).filter(k => TA.isNum(dist[k]) && dist[k] > 0.0005).map(Number).sort((a, b) => a - b);
  if (!ks.length) { empty(el, 'No distribution.'); return; }
  const col = o.colour || C.ace;
  const shapes = [];
  if (TA.isNum(o.line)) shapes.push({ type: 'line', x0: o.line, x1: o.line, yref: 'paper', y0: 0, y1: 1, line: { color: C.text2, width: 1.5, dash: 'dash' } });
  if (TA.isNum(o.exp)) shapes.push({ type: 'line', x0: o.exp, x1: o.exp, yref: 'paper', y0: 0, y1: 1, line: { color: col, width: 1.5, dash: 'dot' } });
  TA.plot(el, [{ type: 'bar', x: ks, y: ks.map(k => dist[k]),
    marker: { color: ks.map(k => (TA.isNum(o.actual) && Number(k) === Number(o.actual) ? C.text : hexA(col, 0.8))) },
    hovertemplate: (o.signed ? '%{x:+d}' : '%{x}') + ' ' + esc(o.unit || 'games') + ': %{y:.1%}<extra></extra>' }], TA.layout({
    height: o.height || 220, bargap: 0.12, shapes: shapes,
    xaxis: { title: o.xTitle || '', fixedrange: true, dtick: ks.length > 24 ? 4 : 2, tickformat: o.signed ? '+d' : 'd' },
    yaxis: { tickformat: '.0%', fixedrange: true },
    margin: { l: 44, r: 10, t: 10, b: o.xTitle ? 42 : 28 }
  }));
}

// ── ratings ────────────────────────────────────────────────────────────────

function eloLines(el, series, opts) {
  const o = opts || {};
  const list = (series || []).filter(s => (s.rows || []).length);
  if (!list.length) { empty(el, o.emptyText || 'No rating history.'); return; }
  TA.plot(el, list.map((s, i) => {
    const col = s.colour || TA.PALETTE[i % TA.PALETTE.length];
    return { type: 'scatter', mode: s.mode || 'lines', name: s.name, x: s.rows.map(r => r[0]), y: s.rows.map(r => r[1]),
      line: { color: col, width: s.width || 2, dash: s.dash || 'solid', shape: 'hv' }, connectgaps: true,
      hovertemplate: esc(s.name || '') + ' · %{x|%d %b %Y}: %{y:.0f}<extra></extra>' };
  }), TA.layout({
    height: o.height || 320, showlegend: list.length > 1, legend: { orientation: 'h', y: -0.18, font: { size: 10, color: C.text2 } },
    xaxis: { type: 'date', fixedrange: false }, yaxis: { title: o.yTitle || 'Elo', fixedrange: true },
    margin: { l: 55, r: 15, t: 10, b: 45 }
  }));
}
function surfaceRadar(el, series, opts) {
  const o = opts || {};
  const axes = o.axes || ['hard', 'clay', 'grass'];
  const list = (series || []).filter(s => s && s.values && axes.some(a => TA.isNum(s.values[a])));
  if (!list.length) { empty(el, 'No surface ratings.'); return; }
  const vals = [];
  list.forEach(s => axes.forEach(a => { if (TA.isNum(s.values[a])) vals.push(Number(s.values[a])); }));
  const range = o.range || [Math.floor((Math.min.apply(null, vals) - 60) / 50) * 50, Math.ceil((Math.max.apply(null, vals) + 30) / 50) * 50];
  const labels = axes.map(a => TA.surfaceLabel(a));
  TA.plot(el, list.map((s, i) => {
    const col = s.colour || TA.PALETTE[i % TA.PALETTE.length];
    const r = axes.map(a => (TA.isNum(s.values[a]) ? Number(s.values[a]) : range[0]));
    return { type: 'scatterpolar', r: r.concat([r[0]]), theta: labels.concat([labels[0]]), name: s.name, fill: 'toself', fillcolor: hexA(col, 0.16),
      line: { color: col, width: 2 }, hovertemplate: '%{theta}: %{r:.0f}<extra>' + esc(s.name || '') + '</extra>' };
  }), TA.layout({
    height: o.height || 300,
    polar: { bgcolor: 'rgba(0,0,0,0)', radialaxis: { range: range, gridcolor: '#30363d', tickfont: { size: 8, color: C.text3 }, angle: 90 },
      angularaxis: { gridcolor: '#30363d', tickfont: { size: 11, color: C.text2 }, direction: 'clockwise' } },
    showlegend: list.length > 1, legend: { orientation: 'h', y: -0.08, font: { size: 10, color: C.text2 } },
    margin: { l: 40, r: 40, t: 24, b: 24 }
  }));
}

// ── generic (as the Hardwood) ──────────────────────────────────────────────

function heatTable(spec) {
  const s = spec || {};
  const rows = s.rows || [];
  if (!rows.length) return '<div class="muted">No data.</div>';
  const nCols = Math.max.apply(null, rows.map(r => (r.values || []).length));
  const centers = [];
  for (let i = 0; i < nCols; i++) {
    if (s.center !== 'col') { centers.push(TA.isNum(s.center) ? s.center : 0); continue; }
    const col = rows.map(r => (r.values || [])[i]).filter(TA.isNum).sort((a, b) => a - b);
    centers.push(col.length ? col[Math.floor(col.length / 2)] : 0);
  }
  const vals = [];
  rows.forEach(r => (r.values || []).forEach((v, i) => { if (TA.isNum(v)) vals.push(Math.abs(v - centers[i])); }));
  vals.sort((a, b) => a - b);
  const max = s.max || vals[Math.floor(vals.length * 0.95)] || vals[vals.length - 1] || 1;
  const fmt = s.fmt || (v => TA.num(v, 2));
  const colour = (v, i) => (s.scale === 'seq' ? TA.seqColour(v / (s.max || (vals[vals.length - 1] || 1))) : TA.divColour(v - centers[i], max, s.invert));
  let h = '<div class="table-wrap heat-wrap"' + (s.maxWidth ? ' style="max-width:' + s.maxWidth + 'px"' : '') + '><table class="wc-table heat-table"><thead><tr><th class="heat-corner">' + esc(s.corner || '') + '</th>';
  (s.cols || []).forEach(c => { const cc = typeof c === 'object' ? c : { label: c }; h += '<th' + (cc.title ? ' title="' + esc(cc.title) + '"' : '') + '>' + esc(cc.label) + '</th>'; });
  h += '</tr></thead><tbody>';
  rows.forEach(r => {
    h += '<tr><td class="heat-label">' + (r.label || '') + '</td>';
    (r.values || []).forEach((v, i) => {
      const t = r.titles && r.titles[i] ? ' title="' + esc(r.titles[i]) + '"' : '';
      h += TA.isNum(v) ? '<td class="heat-cell" style="background:' + colour(v, i) + '"' + t + '>' + fmt(v) + '</td>' : '<td class="heat-cell heat-empty"' + t + '>·</td>';
    });
    h += '</tr>';
  });
  return h + '</tbody></table></div>';
}
function probBars(el, items, opts) {
  const o = opts || {};
  const list = (items || []).filter(i => TA.isNum(i.p) && (i.p > 0 || TA.isNum(i.market))).slice(0, o.top || 12);
  if (!list.length) { empty(el, o.emptyText || 'Nothing to show.'); return; }
  const rev = list.slice().reverse();
  const max = Math.max.apply(null, list.map(i => Math.max(i.p || 0, i.market || 0)));
  const traces = [{
    type: 'bar', orientation: 'h', y: rev.map(i => i.label), x: rev.map(i => i.p), name: o.modelName || 'Model',
    text: rev.map(i => TA.pct(i.p)), textposition: 'outside', cliponaxis: false, textfont: { color: C.text, size: 11 },
    marker: { color: rev.map(i => i.colour || C.ace) }, showlegend: false, hovertemplate: '%{y}: %{x:.1%}<extra>' + (o.modelName || 'Model') + '</extra>'
  }];
  if (list.some(i => TA.isNum(i.market))) {
    const m = rev.filter(i => TA.isNum(i.market));
    traces.push({ type: 'scatter', mode: 'markers', name: o.marketName || 'Market', y: m.map(i => i.label), x: m.map(i => i.market),
      marker: { symbol: 'line-ns-open', size: 18, color: C.text, line: { width: 3, color: C.text } }, hovertemplate: '%{y}: %{x:.1%}<extra>' + (o.marketName || 'Market') + '</extra>' });
  }
  TA.plot(el, traces, TA.layout({
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
    const col = s.colour || TA.PALETTE[i % TA.PALETTE.length];
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
  TA.plot(el, traces, TA.layout(Object.assign({
    height: o.height || 380, showlegend: o.legend !== false,
    legend: { orientation: 'h', y: -0.2, font: { size: 10, color: C.text2 } },
    xaxis: Object.assign({ title: o.xTitle || '' }, o.xaxis || {}), yaxis: Object.assign({ title: o.yTitle || '' }, o.yaxis || {}),
    margin: { l: 55, r: 20, t: 20, b: 55 }
  }, o.layout || {})));
}
function radar(el, series, opts) {
  const o = opts || {};
  const labels = o.labels || [];
  const list = (series || []).filter(s => (s.values || []).some(TA.isNum));
  if (!list.length || !labels.length) { empty(el, o.emptyText || 'Not enough data for a radar.'); return; }
  const traces = list.map((s, i) => {
    const col = s.colour || TA.PALETTE[i % TA.PALETTE.length];
    const r = s.values.map(v => (TA.isNum(v) ? v : 0));
    return { type: 'scatterpolar', r: r.concat([r[0]]), theta: labels.concat([labels[0]]), name: s.name, fill: 'toself',
      fillcolor: hexA(col, 0.18), line: { color: col, width: 2 }, hovertemplate: '%{theta}: %{r:.0f}<extra>' + esc(s.name || '') + '</extra>' };
  });
  TA.plot(el, traces, TA.layout({
    height: o.height || 360,
    polar: { bgcolor: 'rgba(0,0,0,0)', radialaxis: { range: [0, 100], tickvals: [25, 50, 75, 100], gridcolor: '#30363d', tickfont: { size: 8, color: C.text3 }, angle: 90 },
      angularaxis: { gridcolor: '#30363d', tickfont: { size: 10, color: C.text2 }, direction: 'clockwise' } },
    showlegend: list.length > 1, legend: { orientation: 'h', y: -0.08, font: { size: 10, color: C.text2 } },
    margin: { l: 50, r: 50, t: 30, b: 30 }
  }));
}

TA.charts = Object.assign(TA.charts || {}, {
  bracketModel: bracketModel, bracket: bracket, pathOdds: pathOdds,
  wpChart: wpChart, setDist: setDist, setOrder: setOrder, gamesDist: gamesDist,
  eloLines: eloLines, surfaceRadar: surfaceRadar,
  heatTable: heatTable, probBars: probBars, lines: lines, radar: radar, hexA: hexA
});
})(window.TA);
