/* The Quant Ace — shared chart helpers (TA.charts).
 *
 * Every helper takes a target (element or id) first and degrades to a muted line when its data is missing.
 *
 *   bracketModel(draw)                 the draw as columns: {rounds, size, leaves:[{slot,pid,seed,entry}],
 *                                      cols: [[{r, j, lo, hi, a, b, card, winner}]]} (lo/hi = leaf range of the match)
 *   bracket(el, draw, opts)            interactive draw. opts {tour, sim: {pid: {reach:{round:p}}}, picked: pid,
 *                                      onPick(pid|null), section: 'all'|0..3, narrow (auto under 720 px)}
 *                                      Click a player to highlight their path; returns {pick(pid), model}.
 *   pathOdds(model, sim, pid)          [{round, p_reach, opponents:[[pid, p]], match}] along pid's path
 *   wpChart(el, wp, opts)              wp [[i, set, g1, g2, p1]] game by game (QKC.winProb); opts {tour, p1, p2, swings, height}
 *   setDist(el, sets, opts)            sets {"2-0": p, ...} from p1's view; opts {tour, p1, p2, actual:"2-1", height}
 *   gamesDist(el, dist, opts)          dist {n: p}; opts {actual, exp, xTitle, colour: 'b' (player A blue), height, signed}
 *   hexA(hex, a)                       rgba string
 * Charts are the kit's (QKC on ECharts, Design System 2.0): every axis titled, ours in the signal colour, players A and
 * B in the win-probability pair.
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

// ── win probability by game (Design System 2.0: QKC.winProb) ─────────────

function wpChart(el, wp, opts) {
  const o = opts || {};
  const T = o.tour || TA.state.tour;
  const rows = (wp || []).filter(r => Array.isArray(r) && TA.isNum(r[0]) && TA.isNum(r[4]));
  const n = node(el);
  if (!n) return;
  if (rows.length < 2) { empty(el, o.emptyText || 'No win-probability path for this match yet.'); return; }
  if (!n.classList.contains('qk-chart')) { n.classList.add('qk-chart'); n.style.setProperty('--h', (o.height || 300) + 'px'); }
  const n1 = o.p1 ? TA.playerSurname(T, o.p1) : 'Player 1', n2 = o.p2 ? TA.playerSurname(T, o.p2) : 'Player 2';
  const periods = [];
  rows.forEach((r, i) => { if (i > 0 && r[1] !== rows[i - 1][1]) periods.push(rows[i - 1][0] + 0.5); });
  const byI = {};
  rows.forEach(r => { byI[r[0]] = r; });
  const sw = (o.swings || []).filter(s => TA.isNum(s.i) && byI[s.i]).slice(0, o.top || 5);
  QKC.winProb(n, {
    t: rows.map(r => r[0]), p: rows.map(r => r[4]), step: false,
    home: { name: n1, abbr: n1, colour: QK.cssVar('--wp-a') }, away: { name: n2, abbr: n2, colour: QK.cssVar('--wp-b') },
    periods: periods, events: sw.map((s, k) => ({ t: s.i, p: byI[s.i][4], label: String(k + 1) })),
    tFmt: v => String(Math.round(v)), tName: 'Games played', yName: n1 + ' win chance (' + n2 + ' below 50%)',
    tLabel: t => { const r = byI[Math.round(t)]; return r ? (r[0] === rows[0][0] ? 'Before the first ball' : 'Set ' + r[1] + ' · ' + r[2] + '-' + r[3]) : ''; },
    label: 'Win chance game by game'
  });
}

// ── distributions (QKC on ECharts; every axis titled) ─────────────────────

function setOrder(keys) {
  return keys.slice().sort((a, b) => {
    const pa = a.split('-').map(Number), pb = b.split('-').map(Number);
    const wa = pa[0] > pa[1], wb = pb[0] > pb[1];
    if (wa !== wb) return wa ? -1 : 1;
    return wa ? pa[1] - pb[1] : pb[0] - pa[0];
  });
}
function prep(el, h) {
  const n = node(el);
  if (!n) return null;
  if (!n.classList.contains('qk-chart')) { n.classList.add('qk-chart'); n.style.setProperty('--h', h + 'px'); }
  return n;
}
function setDist(el, sets, opts) {
  const o = opts || {};
  const T = o.tour || TA.state.tour;
  const keys = setOrder(Object.keys(sets || {}).filter(k => TA.isNum(sets[k])));
  if (!keys.length) { empty(el, 'No set-score distribution.'); return; }
  const n = prep(el, o.height || 240);
  if (!n) return;
  const n1 = o.p1 ? TA.playerSurname(T, o.p1) : 'Player 1', n2 = o.p2 ? TA.playerSurname(T, o.p2) : 'Player 2';
  const lab = k => { const p = k.split('-').map(Number); return p[0] > p[1] ? n1 + ' ' + k : n2 + ' ' + p[1] + '-' + p[0]; };
  QKC.mount(n, Tk => {
    const xa = QKC.axis(Tk, { type: 'category', data: keys.map(lab), split: false, line: true });
    QKC.nameAxis(xa, 'Set score', 'bottom');
    const ya = QKC.axis(Tk, { fmt: v => Math.round(v * 100) + '%', min: 0 });
    QKC.nameAxis(ya, 'Our chance', 'side');
    const ca = QK.cssVar('--wp-a'), cb = QK.cssVar('--wp-b');
    return { grid: { left: 8, right: 12, top: 34, bottom: 34, containLabel: true }, xAxis: xa, yAxis: ya,
      tooltip: QKC.tooltip(Tk, { formatter: p => esc(p.name) + ': <b>' + TA.pct(p.value, 1) + '</b>' + (keys[p.dataIndex] === o.actual ? ' · what happened' : '') }),
      series: [{ type: 'bar', barMaxWidth: 46, data: keys.map(k => { const w = Number(k.split('-')[0]) > Number(k.split('-')[1]);
        return { value: sets[k], itemStyle: { color: QKC.hexA(w ? ca : cb, 0.85), borderColor: k === o.actual ? Tk.ink1 : 'transparent', borderWidth: k === o.actual ? 2 : 0, borderRadius: [3, 3, 0, 0] } }; }),
        label: { show: true, position: 'top', color: Tk.ink2, fontFamily: Tk.fontNum, fontSize: 10.5, formatter: p => TA.pct(p.value, 0) } }] };
  }, { label: 'Set-score distribution' });
}
function gamesDist(el, dist, opts) {
  const o = opts || {};
  const ks = Object.keys(dist || {}).filter(k => TA.isNum(dist[k]) && dist[k] > 0.0005).map(Number).sort((a, b) => a - b);
  if (!ks.length) { empty(el, 'No distribution.'); return; }
  const n = prep(el, o.height || 240);
  if (!n) return;
  const lo = ks[0], hi = ks[ks.length - 1];
  const full = [];
  for (let k = lo; k <= hi; k++) full.push(k);
  const fx = v => (o.signed && v > 0 ? '+' : '') + v;
  QKC.mount(n, Tk => {
    const col = o.colour === 'b' ? QK.cssVar('--wp-a') : Tk.model;
    const xa = QKC.axis(Tk, { type: 'category', data: full.map(fx), split: false, line: true });
    QKC.nameAxis(xa, o.xTitle || 'Games', 'bottom');
    const ya = QKC.axis(Tk, { fmt: v => Math.round(v * 100) + '%', min: 0 });
    QKC.nameAxis(ya, o.yTitle || 'Our chance', 'side');
    const ml = [];
    if (TA.isNum(o.exp)) ml.push({ xAxis: Math.max(0, Math.min(full.length - 1, o.exp - lo)), lineStyle: { color: Tk.ink2, type: [3, 3] }, label: { show: true, formatter: 'Expected ' + TA.num(o.exp, 1), color: Tk.ink2, fontSize: 10 } });
    return { grid: { left: 8, right: 12, top: 34, bottom: 34, containLabel: true }, xAxis: xa, yAxis: ya,
      tooltip: QKC.tooltip(Tk, { formatter: p => esc(p.name) + ' ' + esc(o.unit || 'games') + ': <b>' + TA.pct(p.value, 1) + '</b>' + (TA.isNum(o.actual) && full[p.dataIndex] === Number(o.actual) ? ' · what happened' : '') }),
      series: [{ type: 'bar', barCategoryGap: '12%', data: full.map(k => ({ value: dist[k] || 0, itemStyle: { color: TA.isNum(o.actual) && k === Number(o.actual) ? Tk.ink1 : QKC.hexA(col, 0.8), borderRadius: [2, 2, 0, 0] } })),
        markLine: ml.length ? { silent: true, symbol: 'none', data: ml } : undefined }] };
  }, { label: o.xTitle || 'Games distribution' });
}

TA.charts = Object.assign(TA.charts || {}, {
  bracketModel: bracketModel, bracket: bracket, pathOdds: pathOdds,
  wpChart: wpChart, setDist: setDist, setOrder: setOrder, gamesDist: gamesDist, hexA: hexA
});
})(window.TA);
