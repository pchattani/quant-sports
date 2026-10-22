/* The Quant Gridiron — Trade simulator (#/trade?t=KC,BUF&m=<pid>:<to>,...), in Value & Moves.
 * Pick two or three teams and the players each sends. Per team: value in and out, the effect at each
 * position (an incoming player displaces the weakest starter if he is better), the QB term when the
 * starter changes, the change in strength (k_resp x the change in position value) and the change in wins
 * and our season chances read off each team's sensitivity curves, drawn as before/after dumbbells (Design System 2.0).
 * Reads <S>/trade.json (current season). */
(function (GI) {
'use strict';

const esc = GI.esc, isNum = GI.isNum;
const ODDS = [['p_playoffs', 'Playoffs'], ['p_div', 'Division'], ['p_bye', 'No. 1 seed'], ['p_conf', 'Conference'], ['p_sb', 'Super Bowl']];
const AVAIL = { ACT: 1, INA: 1 };
let D = null, P = {}, S = null;
const T = { teams: [], moves: [] };

function avail(p) { return !p.status || AVAIL[p.status] === 1; }
function hashOf() {
  const q = [];
  if (T.teams.length) q.push('t=' + T.teams.join(','));
  if (T.moves.length) q.push('m=' + T.moves.map(m => m.pid + ':' + m.to).join(','));
  return '#/trade' + (q.length ? '?' + q.join('&') : '');
}
function starters(ids, pos) {
  const n = (D.slots || {})[pos] || 1;
  const xs = ids.filter(p => P[p].pos === pos && avail(P[p]) && isNum(P[p].gvar_pg)).sort((a, b) => P[b].gvar_pg - P[a].gvar_pg).slice(0, n);
  return { ids: xs, value: xs.reduce((s, p) => s + Math.max(0, P[p].gvar_pg), 0) };
}
function qbOf(t, roster, sentSet, received) {
  const q = D.qb[t] || {};
  let cur = null;
  if (q.starter && !sentSet[q.starter]) cur = { pid: q.starter, val: isNum(q.val) ? q.val : D.qb_new };
  if (!cur) {
    const next = (q.depth || []).find(p => !sentSet[p] && roster.indexOf(p) >= 0 && (!P[p] || avail(P[p])));
    cur = next ? { pid: next, val: P[next] && isNum(P[next].qbv) ? P[next].qbv : D.qb_new } : { pid: null, val: D.qb_new };
  }
  received.forEach(p => { const x = P[p]; if (x.pos === 'QB' && avail(x) && isNum(x.qbv) && x.qbv > cur.val) cur = { pid: p, val: x.qbv }; });
  return cur;
}
function curveAt(t, key, x) {
  const s = D.sens || {}, c = (s.teams || {})[t], g = s.grid || [];
  if (!c || !c[key] || !g.length) return null;
  const xx = Math.max(g[0], Math.min(g[g.length - 1], x));
  for (let i = 0; i < g.length - 1; i++) if (xx <= g[i + 1]) { const u = (xx - g[i]) / (g[i + 1] - g[i]); return c[key][i] + u * (c[key][i + 1] - c[key][i]); }
  return c[key][c[key].length - 1];
}
function teamEffect(t) {
  const roster0 = Object.keys(P).filter(p => P[p].team === t);
  const sent = T.moves.filter(m => P[m.pid].team === t).map(m => m.pid);
  const recv = T.moves.filter(m => m.to === t).map(m => m.pid);
  const sentSet = {};
  sent.forEach(p => { sentSet[p] = 1; });
  const roster1 = roster0.filter(p => !sentSet[p]).concat(recv);
  const pos = [];
  let raw = 0;
  (D.positions || []).forEach(ps => {
    if (ps === 'QB' || !sent.concat(recv).some(p => P[p].pos === ps)) return;
    const a = starters(roster0, ps), b = starters(roster1, ps);
    pos.push({ pos: ps, before: a.value, after: b.value, d: b.value - a.value, out: a.ids.filter(p => b.ids.indexOf(p) < 0), inn: b.ids.filter(p => a.ids.indexOf(p) < 0) });
    raw += b.value - a.value;
  });
  const q0 = { pid: (D.qb[t] || {}).starter, val: isNum((D.qb[t] || {}).val) ? D.qb[t].val : D.qb_new };
  const q1 = qbOf(t, roster1, sentSet, recv);
  const qd = (D.np || 35) * (q1.val - q0.val);
  if (Math.abs(qd) > 1e-9 || sent.concat(recv).some(p => P[p].pos === 'QB')) raw += qd;
  const ages = l => l.map(p => P[p].age).filter(isNum);
  const ain = ages(recv), aout = ages(sent);
  return { t: t, sent: sent, recv: recv, pos: pos, q0: q0, q1: q1, qd: qd, raw: raw, dx: (D.k_resp || 0.85) * raw, ageGap: ain.length && aout.length ? GI.mean(ain) - GI.mean(aout) : null };
}

function pickers(teams, box, redraw) {
  box.innerHTML = '<div class="gi-trade-cols">' + T.teams.map((t, i) => {
    const mine = Object.keys(P).filter(p => P[p].team === t), byPos = {};
    mine.forEach(p => { (byPos[P[p].pos] = byPos[P[p].pos] || []).push(p); });
    const opts = (D.positions || []).filter(pos => byPos[pos]).map(pos => '<optgroup label="' + esc(GI.copyText((D.labels || {})[pos] || pos)) + '">' +
      byPos[pos].filter(p => !T.moves.some(m => m.pid === p)).sort((a, b) => (P[b].gvar_pg || -9) - (P[a].gvar_pg || -9)).map(p => { const x = P[p];
        const v = pos === 'QB' ? (isNum(x.qbv) ? 'QB ' + GI.signed(x.qbv, 3) + ' EPA/db' : 'no QB value') : (isNum(x.gvar_pg) ? GI.signed(x.gvar_pg, 2) + ' a game' : 'no sample');
        return '<option value="' + esc(p) + '">' + esc(x.name + ' · ' + v + (x.status === 'RES' ? ' · IR' : '')) + '</option>'; }).join('') + '</optgroup>').join('');
    const sent = T.moves.filter(m => P[m.pid].team === t);
    return '<div class="qk-card gi-trade-side" style="--tc:' + esc(GI.tc(t)) + '"><div class="qk-card-body"><div class="gi-toolbar">' + GI.mark(t) +
      '<select class="qk-select" data-ti="' + i + '" aria-label="Team ' + (i + 1) + '">' + teams.map(x => '<option value="' + x + '"' + (x === t ? ' selected' : '') + (x !== t && T.teams.indexOf(x) >= 0 ? ' disabled' : '') + '>' + esc(GI.teamName(x)) + '</option>').join('') + '</select>' +
      (T.teams.length > 2 ? '<button type="button" class="qk-btn" data-rm="' + i + '" aria-label="Remove this team">×</button>' : '') + '</div>' +
      GI.field('Sends', '<select class="qk-select" data-add="' + t + '"><option value="">Add a player…</option>' + opts + '</select>') +
      '<ul class="gi-moves">' + (sent.length ? sent.map(m => { const x = P[m.pid];
        return '<li><span>' + GI.playerLink(m.pid, x.name) + ' <span class="gi-tag">' + esc(GI.posLabel(x.pos)) + '</span></span>' +
          (T.teams.length > 2 ? '<select class="qk-select" data-to="' + esc(m.pid) + '" aria-label="Destination">' + T.teams.filter(z => z !== t).map(z => '<option value="' + z + '"' + (z === m.to ? ' selected' : '') + '>to ' + z + '</option>').join('') + '</select>' : '<span class="qk-muted">to ' + esc(m.to) + '</span>') +
          '<button type="button" class="qk-btn" data-del="' + esc(m.pid) + '" aria-label="Remove">×</button></li>'; }).join('') : '<li class="qk-muted">Nothing yet.</li>') + '</ul></div></div>';
  }).join('') + '</div>';
  box.querySelectorAll('select[data-ti]').forEach(s => s.addEventListener('change', () => { const i = Number(s.getAttribute('data-ti')), old = T.teams[i]; T.teams[i] = s.value; T.moves = T.moves.filter(m => P[m.pid].team !== old && m.to !== old); redraw(); }));
  box.querySelectorAll('select[data-add]').forEach(s => s.addEventListener('change', () => { const p = s.value, t = s.getAttribute('data-add'); if (!p) return; T.moves.push({ pid: p, to: T.teams.filter(z => z !== t)[0] }); redraw(); }));
  box.querySelectorAll('select[data-to]').forEach(s => s.addEventListener('change', () => { const m = T.moves.find(x => x.pid === s.getAttribute('data-to')); if (m) m.to = s.value; redraw(); }));
  box.querySelectorAll('[data-del]').forEach(b => b.addEventListener('click', () => { T.moves = T.moves.filter(m => m.pid !== b.getAttribute('data-del')); redraw(); }));
  box.querySelectorAll('[data-rm]').forEach(b => b.addEventListener('click', () => { const t = T.teams[Number(b.getAttribute('data-rm'))]; T.teams = T.teams.filter(z => z !== t); T.moves = T.moves.filter(m => P[m.pid].team !== t && m.to !== t); redraw(); }));
}

function results(box) {
  if (!T.moves.length) { box.innerHTML = QK.empty('Add a player', 'Pick a player from either team to see what the trade does to each side.'); return; }
  const sOk = (D.sens || {}).ok;
  const g = (D.sens || {}).grid || [0];
  const lim = Math.max(Math.abs(g[0]), Math.abs(g[g.length - 1]));
  const E = T.teams.map(teamEffect);
  const name = x => GI.playerLink(x, (P[x] || {}).name);
  box.innerHTML = '<div class="gi-trade-cols">' + E.map(e => {
    const t = e.t;
    const dW = sOk ? curveAt(t, 'mean_wins', e.dx) - curveAt(t, 'mean_wins', 0) : null, dP = sOk ? curveAt(t, 'p_playoffs', e.dx) - curveAt(t, 'p_playoffs', 0) : null;
    const now = isNum(dW) ? (dW >= 0.15 || dP >= 0.02 ? ['Wins now', GI.GOOD] : dW <= -0.15 || dP <= -0.02 ? ['Weakens now', GI.BAD] : ['Little change now', 'var(--ink-3)']) : (e.dx >= 0.3 ? ['Stronger', GI.GOOD] : e.dx <= -0.3 ? ['Weaker', GI.BAD] : ['Little change', 'var(--ink-3)']);
    const flow = (ids, sign) => ids.length ? ids.map(p => { const x = P[p]; const v = x.pos === 'QB' ? (isNum(x.qbv) ? 'QB ' + GI.signed(x.qbv, 3) + ' EPA/db' : '') : (isNum(x.gvar_pg) ? GI.signed(x.gvar_pg, 2) + ' a game' : 'no sample');
      return '<li><span>' + sign + ' ' + name(p) + ' <span class="gi-tag">' + esc(GI.posLabel(x.pos)) + '</span></span><span class="gi-num qk-muted">' + esc(v) + (x.status === 'RES' ? ' · IR' : '') + '</span></li>'; }).join('') : '<li class="qk-muted">Nobody.</li>';
    const posRows = e.pos.map(r => [{ html: '<b>' + esc(GI.posLabel(r.pos)) + '</b>' }, { html: GI.signed(r.before, 2) }, { html: GI.signed(r.after, 2) }, { html: '<b>' + GI.ptsEdge(r.d, 2) + '</b>' },
      { html: '<span class="gi-play-desc">' + ((r.inn.length ? 'in: ' + r.inn.map(name).join(', ') : '') + (r.inn.length && r.out.length ? '; ' : '') + (r.out.length ? 'out of the starters: ' + r.out.map(name).join(', ') : '') || 'no change to the starters') + '</span>' }]);
    if (e.q0.pid !== e.q1.pid || Math.abs(e.qd) > 1e-9) posRows.unshift([{ html: '<b>QB</b>' }, { html: name(e.q0.pid) + ' ' + GI.signed(e.q0.val, 3) }, { html: (e.q1.pid ? name(e.q1.pid) : 'a new QB') + ' ' + GI.signed(e.q1.val, 3) }, { html: '<b>' + GI.ptsEdge(e.qd, 2) + '</b>' }, { html: '<span class="gi-play-desc">QB term × ' + GI.num(D.np, 1) + ' dropbacks a game</span>' }]);
    const rec = (D.baseline[t] || {}).record || [];
    return '<section class="qk-card gi-trade-side" style="--tc:' + esc(GI.tc(t)) + '"><div class="qk-card-head"><div class="gi-card-titles"><h3 class="qk-card-title">' + GI.teamLink(t) + '</h3><div class="qk-card-sub">' + (rec.length && isNum(rec[0]) ? rec[0] + '-' + rec[1] + (rec[2] ? '-' + rec[2] : '') + ' · ' : '') + (isNum((D.baseline[t] || {}).remaining) ? D.baseline[t].remaining + ' games left' : '') + '</div></div>' + GI.pill(now[0], now[1]) + '</div><div class="qk-card-body">' +
      GI.kpis([GI.kpi('Strength', GI.signed(e.dx, 2), 'points a game v an average team', { signal: true, tip: GI.signed(e.raw, 2) + ' in position value × ' + GI.num(D.k_resp, 2) + ', the game model\'s response' }),
        isNum(dW) ? GI.kpi('Wins', GI.signed(dW, 2), 'expected, rest of season') : '', isNum(dP) ? GI.kpi('Playoffs', GI.signed(dP * 100, 1) + ' pts', GI.pct(curveAt(t, 'p_playoffs', 0), 0) + ' → ' + GI.pct(curveAt(t, 'p_playoffs', e.dx), 0)) : ''], 'gi-kpis-3') +
      '<div class="qk-grid" style="margin-top:12px"><div class="qk-span-6"><h4 class="gi-inj-h">In</h4><ul class="gi-moves">' + flow(e.recv, '+') + '</ul></div><div class="qk-span-6"><h4 class="gi-inj-h">Out</h4><ul class="gi-moves">' + flow(e.sent, '−') + '</ul></div></div>' +
      '<h4 class="gi-inj-h">By position <span class="qk-muted">(points a game above replacement among the starters)</span></h4>' + (posRows.length ? GI.tableHTML([{ label: 'Pos', sortable: false }, { label: 'Before', align: 'right', sortable: false }, { label: 'After', align: 'right', sortable: false }, { label: 'Change', align: 'right', sortable: false }, { label: 'Who moves', sortable: false }], posRows) : GI.muted('No position changes.')) +
      (sOk ? '<h4 class="gi-inj-h">Our season chances, now → after</h4>' + GI.chartBox('tr-odds-' + t, 240, 'Season chances before and after') + (Math.abs(e.dx) > lim ? '<p class="gi-cap">The change is beyond the simulated range (±' + lim + ' points): the chances are held at the end of the curve.</p>' : '')
        : GI.muted('No season simulation right now (' + esc((D.sens || {}).reason || 'the season is over') + '): strength only.')) +
      (isNum(e.ageGap) && Math.abs(e.ageGap) >= 3 ? '<p class="gi-cap">' + (e.ageGap < 0 ? 'Younger' : 'Older') + ' by ' + GI.num(Math.abs(e.ageGap), 1) + ' years on average.</p>' : '') + '</div></section>';
  }).join('') + '</div><p class="gi-cap">Starters: QB 1, RB 2, WR 3, TE 2, ED 2, DL 2, LB 2, CB 3, S 2, K 1, P 1. Players are valued at the per-game production they have shown this season. Injured-reserve players change nothing this season. Offensive linemen are not modelled individually. Interactions between the teams are not re-simulated.</p>';
  if (sOk) E.forEach(e => {
    const rows = ODDS.map(o => ({ label: o[1], a: curveAt(e.t, o[0], e.dx), b: curveAt(e.t, o[0], 0) })).filter(r => isNum(r.a) && isNum(r.b));
    GI.ch.dumbbell('tr-odds-' + e.t, { rows: rows, aName: 'After the trade', bName: 'Now', labelWidth: 90, valName: 'Our chance' });
  });
}

GI.route('trade', function (el, params) {
  S = GI.currentSeason();
  return GI.load(GI.ypath('trade.json', S)).then(d => {
    if (!el.isConnected) return;
    D = d;
    const head = GI.pageHead('Value & Moves · ' + S, 'Trade simulator', 'Swap players between two or three teams and see each side\'s strength, wins and our season chances move.' + (GI.ok(d) && d.basis_season && d.basis_season !== S ? ' Player values from ' + d.basis_season + '.' : '')) + GI.sectionNav('value', 'trade');
    if (!GI.ok(d) || !d.players) { el.innerHTML = head + GI.notBuilt('The ' + S + ' trade data', d); return; }
    P = {};
    (d.players || []).forEach(r => { const o = {}; d.cols.forEach((c, i) => { o[c] = r[i]; }); P[o.pid] = o; });
    const qy = params.query || {};
    T.teams = String(qy.t || '').split(',').map(x => x.trim().toUpperCase()).filter(x => x && D.qb[x]).slice(0, 3);
    T.moves = String(qy.m || '').split(',').map(x => { const a = x.split(':'); return { pid: a[0], to: String(a[1] || '').toUpperCase() }; })
      .filter(m => P[m.pid] && T.teams.indexOf(P[m.pid].team) >= 0 && T.teams.indexOf(m.to) >= 0 && m.to !== P[m.pid].team);
    const teams = Object.keys(D.qb).sort();
    if (T.teams.length < 2) { const free = teams.filter(t => T.teams.indexOf(t) < 0); while (T.teams.length < 2) T.teams.push(free.shift()); }
    el.innerHTML = head + GI.note('<p>' + esc(GI.copyText(d.label || '')) + ' ' + (d.contracts && !d.contracts.enabled ? esc(GI.copyText(d.contracts.note || '')) : '') + ' Each team\'s chances come from its own sensitivity curve (the season simulation re-run with that team\'s strength shifted).</p>') +
      GI.card('The trade', 'Choose the teams, then the players each one sends', '<div id="tr-pick"></div><div class="gi-toolbar" style="margin-top:12px"><button type="button" class="qk-btn" id="tr-add3">Add a third team</button><button type="button" class="qk-btn" id="tr-clear">Clear</button>' +
        GI.field('Share this trade', '<input id="tr-link" class="qk-input" type="text" readonly>') + '<button type="button" class="qk-btn primary" id="tr-copy">Copy link</button></div>') +
      '<div id="tr-out"></div>';
    const $ = id => document.getElementById(id);
    const redraw = () => {
      pickers(teams, $('tr-pick'), redraw);
      results($('tr-out'));
      GI.setHashQuiet(hashOf());
      $('tr-link').value = location.href.split('#')[0] + hashOf();
    };
    $('tr-add3').addEventListener('click', () => { if (T.teams.length < 3) { T.teams.push(teams.filter(t => T.teams.indexOf(t) < 0)[0]); redraw(); } });
    $('tr-clear').addEventListener('click', () => { T.moves = []; redraw(); });
    $('tr-copy').addEventListener('click', () => { const i = $('tr-link'); try { i.select(); if (navigator.clipboard) navigator.clipboard.writeText(i.value); else document.execCommand('copy'); } catch (e) { /* ok */ } });
    redraw();
  });
});

})(window.GI);
