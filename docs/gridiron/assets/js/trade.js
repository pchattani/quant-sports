/* The Quant Gridiron — trade simulator (#/trade).
 *
 * Pick two (or three) teams and the players each sends. Per team: value in and out, the effect at
 * each position (an incoming player displaces the weakest starter if he is better; a departing
 * starter is replaced by the team's own next man up), the QB term when the starting QB changes, the
 * change in strength (k_resp x the change in position values, points per game against an average
 * team), and the change in wins, playoff, division, bye, conference and Super Bowl odds and the mean
 * draft slot, read off each team's sensitivity curves (the season simulation re-run with the team's
 * strength shifted; season_sim.sensitivity). Cap hits only when the contracts data may be published.
 *
 * Address (shareable): #/trade?t=KC,BUF&m=<pid>:<to team>,<pid>:<to team>. Data: data/<S>/trade.json
 * (current season). Uses GI.fk. */
(function (GI) {
'use strict';

const K = () => GI.fk;
const ODDS = [['p_playoffs', 'Playoffs'], ['p_div', 'Division'], ['p_bye', 'First-round bye'], ['p_conf', 'Conference'], ['p_sb', 'Super Bowl']];
const AVAIL = { ACT: 1, INA: 1 };
const DEF = { EDGE: 1, DL: 1, LB: 1, CB: 1, S: 1 };
let D = null, P = {}, S = null;
const T = { teams: [], moves: [] };   // moves: [{pid, to}]

function avail(p) { return !p.status || AVAIL[p.status] === 1; }

function parseState(qy) {
  const k = K();
  T.teams = String(qy.t || '').split(',').map(x => x.trim().toUpperCase()).filter(x => x && D.qb[x]).slice(0, 3);
  T.moves = String(qy.m || '').split(',').map(x => { const a = x.split(':'); return { pid: a[0], to: String(a[1] || '').toUpperCase() }; })
    .filter(m => P[m.pid] && T.teams.indexOf(P[m.pid].team) >= 0 && T.teams.indexOf(m.to) >= 0 && m.to !== P[m.pid].team);
  if (!T.teams.length) T.teams = [];
  return k;
}

function hashOf() {
  const q = [];
  if (T.teams.length) q.push('t=' + T.teams.join(','));
  if (T.moves.length) q.push('m=' + T.moves.map(m => m.pid + ':' + m.to).join(','));
  return '#/trade' + (q.length ? '?' + q.join('&') : '');
}

function sync() {
  try { history.replaceState(null, '', hashOf()); } catch (e) { /* ok */ }
  const a = K().$('gt-link');
  if (a) a.value = location.href.split('#')[0] + hashOf();
}

function rows(d) {
  const out = {};
  (d.players || []).forEach(r => { const o = {}; d.cols.forEach((c, i) => { o[c] = r[i]; }); out[o.pid] = o; });
  return out;
}

function render(el, params, state) {
  const k = K();
  el.innerHTML = k.muted('Loading…');
  return k.ready().then(() => {
    S = k.curSeason ? k.curSeason() : k.S(params, state);
    return Promise.all([k.loadY(S, 'trade.json'), k.loadNames()]);
  }).then(res => {
    if (!k.alive(el)) return;
    D = res[0];
    if (!k.ok(D) || !D.players) {
      el.innerHTML = k.head('Trade simulator', String(S)) + k.card('Trade simulator', '', '<div class="gq-pad">' + k.notBuilt('The ' + S + ' trade data', D) + '</div>');
      return;
    }
    P = rows(D);
    parseState(params.query || {});
    const teams = Object.keys(D.qb).sort();
    let h = k.head('Trade simulator', S + ' · ' + k.esc(D.phase || '') + (D.basis_season && D.basis_season !== S ? ' · player values from ' + D.basis_season : ''),
      '<a href="' + k.withQ('#/value', S) + '">Player value →</a><a href="#/methodology/trade">How it works →</a>');
    h += '<div class="card"><div class="gq-pad gt-intro"><p>' + k.esc(D.label || '') + ' ' + (D.contracts && !D.contracts.enabled ? k.esc(D.contracts.note || '') : '') + '</p>' +
      '<p class="muted-inline">Each team\'s odds come from its own sensitivity curve (the season simulation re-run with that team\'s strength shifted; ' + k.int((D.sens || {}).n) + ' importance-weighted runs a team), so a trade between two rivals moves each team\'s odds for its own change only.</p></div></div>';
    h += '<div class="card"><div class="card-header">The trade <span class="card-sub">Choose the teams, then add the players each one sends.</span></div><div class="gq-pad">' +
      '<div class="gt-teams" id="gt-teams"></div><div class="gt-addteam"><button type="button" class="tbtn" id="gt-add3">Add a third team</button> <button type="button" class="tbtn" id="gt-clear">Clear</button></div>' +
      '<div class="gt-share"><label>Share this trade <input id="gt-link" type="text" readonly></label> <button type="button" class="tbtn" id="gt-copy">Copy link</button></div></div></div>';
    h += '<div id="gt-out"></div>';
    el.innerHTML = h;
    k.setMeta('Trade simulator · ' + S);
    const draw = () => { pickers(teams); result(); sync(); };
    k.$('gt-add3').onclick = () => { if (T.teams.length < 3) { const free = teams.filter(t => T.teams.indexOf(t) < 0); T.teams.push(free[0]); draw(); } };
    k.$('gt-clear').onclick = () => { T.moves = []; draw(); };
    k.$('gt-copy').onclick = () => { const i = k.$('gt-link'); try { i.select(); if (navigator.clipboard) navigator.clipboard.writeText(i.value); else document.execCommand('copy'); } catch (e) { /* ok */ } };
    if (T.teams.length < 2) { const free = teams.filter(t => T.teams.indexOf(t) < 0); while (T.teams.length < 2) T.teams.push(free.shift()); }
    pickers.draw = draw;
    draw();
  });
}

function pickers(teams) {
  const k = K();
  const box = k.$('gt-teams');
  if (!box) return;
  box.innerHTML = T.teams.map((t, i) => {
    const mine = Object.keys(P).filter(p => P[p].team === t);
    const byPos = {};
    mine.forEach(p => { (byPos[P[p].pos] = byPos[P[p].pos] || []).push(p); });
    const opts = (D.positions || []).filter(pos => byPos[pos]).map(pos => '<optgroup label="' + k.esc((D.labels || {})[pos] || pos) + '">' +
      byPos[pos].filter(p => !T.moves.some(m => m.pid === p)).map(p => { const x = P[p];
        const v = pos === 'QB' ? (k.isNum(x.qbv) ? 'QB value ' + k.signed(x.qbv, 3) + ' EPA/db' : 'no QB value') : (k.isNum(x.gvar_pg) ? k.signed(x.gvar_pg, 2) + ' a game' : 'no sample');
        return '<option value="' + k.esc(p) + '">' + k.esc(x.name + ' · ' + v + (x.status === 'RES' ? ' · injured reserve' : '')) + '</option>'; }).join('') + '</optgroup>').join('');
    const sent = T.moves.filter(m => P[m.pid].team === t);
    return '<div class="gt-team" style="--tc:' + k.teamColour(t) + '"><div class="gt-team-h"><select data-ti="' + i + '">' +
      teams.map(x => '<option value="' + x + '"' + (x === t ? ' selected' : '') + (x !== t && T.teams.indexOf(x) >= 0 ? ' disabled' : '') + '>' + k.esc(k.teamName(x)) + '</option>').join('') + '</select>' +
      (T.teams.length > 2 ? '<button type="button" class="tbtn gt-x" data-rm="' + i + '" title="Remove this team">×</button>' : '') + '</div>' +
      '<label class="gt-add">Sends<select data-add="' + t + '"><option value="">Add a player…</option>' + opts + '</select></label>' +
      '<div class="gt-sent">' + (sent.length ? sent.map(m => { const x = P[m.pid];
        return '<div class="gt-mv"><span>' + k.playerLink(m.pid, x.name, S) + ' <span class="muted-inline">' + k.esc(x.pos) + '</span></span>' +
          (T.teams.length > 2 ? '<select data-to="' + k.esc(m.pid) + '">' + T.teams.filter(z => z !== t).map(z => '<option value="' + z + '"' + (z === m.to ? ' selected' : '') + '>to ' + z + '</option>').join('') + '</select>' : '<span class="muted-inline">to ' + k.esc(m.to) + '</span>') +
          '<button type="button" class="tbtn gt-x" data-del="' + k.esc(m.pid) + '" title="Remove">×</button></div>'; }).join('') : k.muted('Nothing yet.')) + '</div></div>';
  }).join('');
  box.querySelectorAll('select[data-ti]').forEach(s => s.addEventListener('change', () => {
    const i = Number(s.getAttribute('data-ti')), old = T.teams[i];
    T.teams[i] = s.value;
    T.moves = T.moves.filter(m => P[m.pid].team !== old && m.to !== old);
    pickers.draw();
  }));
  box.querySelectorAll('select[data-add]').forEach(s => s.addEventListener('change', () => {
    const p = s.value, t = s.getAttribute('data-add');
    if (!p) return;
    const to = T.teams.filter(z => z !== t)[0];
    T.moves.push({ pid: p, to: to });
    pickers.draw();
  }));
  box.querySelectorAll('select[data-to]').forEach(s => s.addEventListener('change', () => {
    const m = T.moves.find(x => x.pid === s.getAttribute('data-to'));
    if (m) m.to = s.value;
    pickers.draw();
  }));
  box.querySelectorAll('[data-del]').forEach(b => b.addEventListener('click', () => { T.moves = T.moves.filter(m => m.pid !== b.getAttribute('data-del')); pickers.draw(); }));
  box.querySelectorAll('[data-rm]').forEach(b => b.addEventListener('click', () => {
    const t = T.teams[Number(b.getAttribute('data-rm'))];
    T.teams = T.teams.filter(z => z !== t);
    T.moves = T.moves.filter(m => P[m.pid].team !== t && m.to !== t);
    pickers.draw();
  }));
}

/* Starters model: the n best per-game values (each floored at 0, a replacement player) among available players. */
function starters(ids, pos) {
  const n = (D.slots || {})[pos] || 1;
  const xs = ids.filter(p => P[p].pos === pos && avail(P[p]) && GI.fk.isNum(P[p].gvar_pg)).sort((a, b) => P[b].gvar_pg - P[a].gvar_pg).slice(0, n);
  return { ids: xs, value: xs.reduce((s, p) => s + Math.max(0, P[p].gvar_pg), 0) };
}

function qbOf(t, roster, sentSet, received) {
  const k = K(), q = D.qb[t] || {};
  let cur = null;
  if (q.starter && !sentSet[q.starter]) cur = { pid: q.starter, val: k.isNum(q.val) ? q.val : D.qb_new };
  if (!cur) {
    const next = (q.depth || []).find(p => !sentSet[p] && roster.indexOf(p) >= 0 && (!P[p] || avail(P[p])));
    cur = next ? { pid: next, val: P[next] && k.isNum(P[next].qbv) ? P[next].qbv : D.qb_new } : { pid: null, val: D.qb_new };
  }
  received.forEach(p => { const x = P[p]; if (x.pos === 'QB' && avail(x) && k.isNum(x.qbv) && x.qbv > cur.val) cur = { pid: p, val: x.qbv }; });
  return cur;
}

function curveAt(t, key, x) {
  const s = D.sens || {}, c = (s.teams || {})[t], g = s.grid || [];
  if (!c || !c[key] || !g.length) return null;
  const xx = Math.max(g[0], Math.min(g[g.length - 1], x));
  for (let i = 0; i < g.length - 1; i++) {
    if (xx <= g[i + 1]) { const u = (xx - g[i]) / (g[i + 1] - g[i]); return c[key][i] + u * (c[key][i + 1] - c[key][i]); }
  }
  return c[key][c[key].length - 1];
}

function teamEffect(t) {
  const k = K();
  const roster0 = Object.keys(P).filter(p => P[p].team === t);
  const sent = T.moves.filter(m => P[m.pid].team === t).map(m => m.pid);
  const recv = T.moves.filter(m => m.to === t).map(m => m.pid);
  const sentSet = {};
  sent.forEach(p => { sentSet[p] = 1; });
  const roster1 = roster0.filter(p => !sentSet[p]).concat(recv);
  const pos = [];
  let raw = 0;
  (D.positions || []).forEach(ps => {
    if (ps === 'QB') return;
    const touched = sent.concat(recv).some(p => P[p].pos === ps);
    if (!touched) return;
    const a = starters(roster0, ps), b = starters(roster1, ps);
    const out = a.ids.filter(p => b.ids.indexOf(p) < 0), inn = b.ids.filter(p => a.ids.indexOf(p) < 0);
    pos.push({ pos: ps, before: a.value, after: b.value, d: b.value - a.value, out: out, inn: inn });
    raw += b.value - a.value;
  });
  const q0 = { pid: (D.qb[t] || {}).starter, val: k.isNum((D.qb[t] || {}).val) ? D.qb[t].val : D.qb_new };
  const q1 = qbOf(t, roster1, sentSet, recv);
  const qd = (D.np || 35) * (q1.val - q0.val);
  if (Math.abs(qd) > 1e-9 || sent.concat(recv).some(p => P[p].pos === 'QB')) raw += qd;
  const dx = (D.k_resp || 0.85) * raw;
  const ages = l => l.map(p => P[p].age).filter(k.isNum);
  const ain = ages(recv), aout = ages(sent);
  return { t: t, sent: sent, recv: recv, pos: pos, q0: q0, q1: q1, qd: qd, raw: raw, dx: dx,
    ageGap: ain.length && aout.length ? k.mean(ain) - k.mean(aout) : null };
}

function verdict(e) {
  const k = K();
  const sOk = (D.sens || {}).ok;
  const dw = curveAt(e.t, 'mean_wins', e.dx), w0 = curveAt(e.t, 'mean_wins', 0);
  const dp = curveAt(e.t, 'p_playoffs', e.dx), p0 = curveAt(e.t, 'p_playoffs', 0);
  const dW = k.isNum(dw) && k.isNum(w0) ? dw - w0 : null, dP = k.isNum(dp) && k.isNum(p0) ? dp - p0 : null;
  let now;
  if (sOk && k.isNum(dW)) now = (dW >= 0.15 || dP >= 0.02) ? ['Wins now', 'gt-good'] : (dW <= -0.15 || dP <= -0.02) ? ['Weakens now', 'gt-bad'] : ['Little change now', ''];
  else now = e.dx >= 0.3 ? ['Stronger', 'gt-good'] : e.dx <= -0.3 ? ['Weaker', 'gt-bad'] : ['Little change', ''];
  const parts = ['<span class="gt-verdict ' + now[1] + '">' + now[0] + '</span>'];
  if (k.isNum(e.ageGap) && e.ageGap <= -3) parts.push('younger by ' + k.num(-e.ageGap, 1) + ' years: a possible long-term gain (we have no ageing model, so it is not quantified)');
  if (k.isNum(e.ageGap) && e.ageGap >= 3) parts.push('older by ' + k.num(e.ageGap, 1) + ' years');
  return parts.join(' · ');
}

function result() {
  const k = K();
  const box = k.$('gt-out');
  if (!box) return;
  if (!T.moves.length) { box.innerHTML = k.card('What it does', '', '<div class="gq-pad">' + k.muted('Add at least one player to see the effect on each team.') + '</div>'); return; }
  const sOk = (D.sens || {}).ok;
  const g = (D.sens || {}).grid || [0];
  const lim = Math.max(Math.abs(g[0]), Math.abs(g[g.length - 1]));
  const cards = T.teams.map(t => {
    const e = teamEffect(t);
    const name = x => k.playerLink(x, (P[x] || {}).name, S);
    const flow = (ids, sign) => ids.length ? ids.map(p => { const x = P[p];
      const v = x.pos === 'QB' ? (k.isNum(x.qbv) ? 'QB ' + k.signed(x.qbv, 3) + ' EPA/db' : '') : (k.isNum(x.gvar_pg) ? k.signed(x.gvar_pg, 2) + ' a game' : 'no sample');
      return '<div class="gt-flow">' + sign + ' ' + name(p) + ' <span class="muted-inline">' + k.esc(x.pos) + ' · ' + k.esc(v) + (x.status === 'RES' ? ' · injured reserve (no effect this season)' : '') + '</span></div>'; }).join('') : k.muted('Nobody.');
    let posRows = e.pos.map(r => ({ cells: [{ v: r.pos, html: '<strong>' + k.esc(r.pos) + '</strong>' }, { v: r.before, html: k.signed(r.before, 2) }, { v: r.after, html: k.signed(r.after, 2) },
      { v: r.d, html: '<strong>' + k.signed(r.d, 2) + '</strong>' },
      { v: '', html: (r.inn.length ? 'in: ' + r.inn.map(name).join(', ') : '') + (r.inn.length && r.out.length ? '; ' : '') + (r.out.length ? 'out of the starters: ' + r.out.map(name).join(', ') : '') || '<span class="muted-inline">no change to the starters</span>' }] }));
    if (e.q0.pid !== e.q1.pid || Math.abs(e.qd) > 1e-9) posRows.unshift({ cells: [{ v: 'QB', html: '<strong>QB</strong>' }, { v: 0, html: name(e.q0.pid) + ' ' + k.signed(e.q0.val, 3) },
      { v: 0, html: (e.q1.pid ? name(e.q1.pid) : 'a new QB') + ' ' + k.signed(e.q1.val, 3) }, { v: e.qd, html: '<strong>' + k.signed(e.qd, 2) + '</strong>' },
      { v: '', html: 'starting QB (team-strength QB term, EPA per dropback × ' + k.num(D.np, 1) + ' dropbacks a game)' }] });
    const posT = posRows.length ? k.table([{ label: 'Pos', sortable: false }, { label: 'Before', align: 'right', sortable: false }, { label: 'After', align: 'right', sortable: false },
      { label: 'Change', align: 'right', sortable: false }, { label: 'Who moves', sortable: false }], posRows, { compact: true }) : k.muted('No position changes.');
    let odds = '';
    if (sOk) {
      const orow = (lab, key, f) => { const a = curveAt(t, key, 0), b = curveAt(t, key, e.dx);
        return { cells: [{ v: lab, html: k.esc(lab) }, { v: a, html: f(a) }, { v: b, html: '<strong>' + f(b) + '</strong>' }, { v: b - a, html: key === 'mean_pick' ? k.signed(b - a, 1) : key === 'mean_wins' ? k.signed(b - a, 2) : k.signed((b - a) * 100, 1) + ' pp' }] }; };
      const pf = x => k.pct(x, 1);
      odds = k.table([{ label: '', sortable: false }, { label: 'Now', align: 'right', sortable: false }, { label: 'After', align: 'right', sortable: false }, { label: 'Change', align: 'right', sortable: false }],
        [orow('Wins (mean)', 'mean_wins', x => k.num(x, 2))].concat(ODDS.map(o => orow(o[1], o[0], pf))).concat([orow('Draft slot (mean)', 'mean_pick', x => k.num(x, 1))]), { compact: true }) +
        (Math.abs(e.dx) > lim ? '<div class="pg-note gq-note">The change is beyond the simulated range (±' + lim + ' points): the odds are held at the edge of the curve.</div>' : '');
    } else odds = k.muted('No season simulation for ' + S + ' right now (' + k.esc((D.sens || {}).reason || 'the season is over') + '): strength only.');
    let cap = '';
    if (D.cap && D.cap.teams) {
      const capOf = p => (P[p] && k.isNum(P[p].cap_hit) ? P[p].cap_hit : 0);
      const before = D.cap.teams[t] || 0, after = before - e.sent.reduce((s, p) => s + capOf(p), 0) + e.recv.reduce((s, p) => s + capOf(p), 0);
      const lc = D.cap.season_cap;
      cap = '<div class="gt-cap">Cap: $' + k.num(before, 1) + 'M → <strong>$' + k.num(after, 1) + 'M</strong>' + (k.isNum(lc) ? ' of a $' + k.num(lc, 1) + 'M cap · ' + (after <= lc ? '<span class="gt-good">under the cap</span>' : '<span class="gt-bad">over the cap by $' + k.num(after - lc, 1) + 'M</span>') : '') +
        '<div class="muted-inline">' + k.esc(D.cap.note || '') + ' ' + k.esc(D.cap.credit || '') + '</div></div>';
    } else cap = '<div class="gt-cap muted-inline">Cap and contracts: not checked (see the note at the top).</div>';
    const rec = (D.baseline[t] || {}).record || [];
    return '<div class="card gt-res" style="--tc:' + k.teamColour(t) + '"><div class="card-header">' + k.teamChip(t, S) + ' ' + k.esc(k.teamName(t)) +
      ' <span class="card-sub">' + (rec.length && k.isNum(rec[0]) ? rec[0] + '-' + rec[1] + (rec[2] ? '-' + rec[2] : '') + ' · ' : '') + (k.isNum((D.baseline[t] || {}).remaining) ? D.baseline[t].remaining + ' games left' : '') + '</span></div><div class="gq-pad">' +
      '<div class="gt-verdict-line">' + verdict(e) + '</div>' +
      '<div class="gt-strength">Strength ' + '<strong>' + k.signed(e.dx, 2) + '</strong> points a game against an average team <span class="muted-inline">(' + k.signed(e.raw, 2) + ' in position value × ' + k.num(D.k_resp, 2) + ', the game model\'s response to a rating change)</span></div>' +
      '<div class="grid-2 gt-flows"><div><div class="gt-sub">In</div>' + flow(e.recv, '+') + '</div><div><div class="gt-sub">Out</div>' + flow(e.sent, '−') + '</div></div>' +
      '<div class="gt-sub">By position <span class="muted-inline">(points a game above replacement among the starters)</span></div>' + posT +
      '<div class="gt-sub">Season odds</div>' + odds + cap + '</div></div>';
  });
  box.innerHTML = '<div class="gt-results">' + cards.join('') + '</div>' +
    '<div class="pg-note gq-note">Starters: QB 1, RB 2, WR 3, TE 2, EDGE 2, DL 2, LB 2, CB 3, S 2, K 1, P 1. Players are valued at the per-game production they have shown this season (a backup\'s per-play rate is never stretched to a starter\'s workload). Injured-reserve players change nothing this season. Offensive linemen are not modelled individually. Interactions between the teams (two rivals both changing) are not re-simulated.</div>';
}

if (typeof GI.route === 'function') { try { GI.route('trade', render); } catch (e) { /* bound */ } }
})(window.GI || (window.GI = {}));
