/* The Quant Hardwood — trade simulator (#/<L>/trade): pick two or three teams and the players moving,
 * and see each team's depth chart, rating, wins and odds change.
 *
 * Data: data/<L>/<S>/trade.json for the league's current season (analytics/value.py trade_payload):
 * players {cols, rows} with each player's rest-of-season HPM (rate, o, d), projected minutes, position
 * group, age and next season's rate; teams {tid: baseline rating and odds}; curves {shifts, keys,
 * teams: {tid: {key: [value at each shift]}}} from re-running the season simulation with that team's
 * rating shifted; params (game minutes, cap, per-player cap, replacement, pace, points per win).
 *
 * The depth chart (applyMoves) follows analytics/value.py apply_moves exactly; the odds are the
 * team's curve at the change in its net rating (linear between grid points, the edge beyond it),
 * added to the full simulation's baseline. State lives in the URL hash:
 *   #/<L>/trade?t=<tid>,<tid>[,<tid>]&m=<pid>-<to tid>.<pid>-<to tid>
 * No salaries: the cap is not checked. */
(function (HW) {
'use strict';

const FX = () => HW.fx;
const ROLES = ['G', 'W', 'B'];
const ROLE_ONE = { G: 'Guard', W: 'Wing', B: 'Big' };
const ADJ = { G: ['W', 'B'], W: ['G', 'B'], B: ['W', 'G'] };
const BASIS = { b: 'this season and last', p: 'last season (projected)', c: 'this season only', r: 'no minutes last season or this: counted at replacement level' };
const ODDS = [['p_playoffs', 'Make the playoffs'], ['p_top6', 'Top-six seed'], ['p_conf', 'Reach the Finals'], ['p_title', 'Win the title'], ['p_top4', 'Top-four pick (lottery)']];

function cmpId(a, b) { a = String(a); b = String(b); return a < b ? -1 : a > b ? 1 : 0; }

// ── the depth chart (mirror of analytics/value.py) ───────────────────────────

function baseline(team, P) {
  let left = P.cap;
  const out = {};
  team.slice().sort((a, b) => (Math.min(b.mpg || 0, P.max_min) - Math.min(a.mpg || 0, P.max_min)) || cmpId(a.id, b.id)).forEach(p => {
    const take = Math.max(0, Math.min(Math.min(p.mpg || 0, P.max_min), left));
    out[p.id] = take;
    left -= take;
  });
  return out;
}

function teamValue(team, minutes, P) {
  const by = {}; team.forEach(p => { by[p.id] = p; });
  let used = 0, net = 0, off = 0, dfn = 0;
  Object.keys(minutes).forEach(k => { used += minutes[k]; if (by[k]) { net += by[k].rate * minutes[k]; off += by[k].o * minutes[k]; dfn += by[k].d * minutes[k]; } });
  const fill = Math.max(0, P.cap - used);
  return { net: net / P.G + P.repl * fill / P.G, off: off / P.G + P.repl / 2 * fill / P.G, def: dfn / P.G + P.repl / 2 * fill / P.G, fill: fill };
}

function applyMoves(team, outIds, incoming, P) {
  const outSet = {}; outIds.forEach(x => { outSet[String(x)] = true; });
  const own = {}; team.forEach(p => { own[String(p.id)] = true; });
  incoming = incoming.filter(p => !own[String(p.id)]);
  const isIn = {}; incoming.forEach(p => { isIn[p.id] = true; });
  const base = baseline(team, P);
  const before = teamValue(team, base, P);
  const roster = team.filter(p => !outSet[String(p.id)]).concat(incoming);
  const by = {}; roster.forEach(p => { by[p.id] = p; });
  const m = {};
  roster.forEach(p => { if (!isIn[p.id]) m[p.id] = base[p.id] || 0; });
  const open = { G: 0, W: 0, B: 0 };
  team.forEach(p => { if (outSet[String(p.id)]) open[p.role || 'W'] += base[p.id] || 0; });
  let used0 = 0; Object.keys(base).forEach(k => { used0 += base[k]; });
  let fill = Math.max(0, P.cap - used0);
  const displaced = {}, absorbed = {};
  incoming.slice().sort((a, b) => (b.rate - a.rate) || cmpId(a.id, b.id)).forEach(p => {
    let need = Math.min(p.mpg || 0, P.max_min);
    const role = p.role || 'W';
    const take = Math.min(need, open[role]);
    open[role] -= take;
    let got = take;
    need -= take;
    [role].concat(ADJ[role]).forEach(rr => {
      if (need <= 1e-9) return;
      let pool = Object.keys(m).filter(k => by[k] && by[k] !== p && (by[k].role || 'W') === rr && m[k] > 1e-9 && !isIn[k]).map(k => [by[k].rate, String(k)]);
      if (rr === role && fill > 1e-9) pool.push([P.repl, '']);
      pool.sort((a, b) => (a[0] - b[0]) || cmpId(a[1], b[1]));
      for (let i = 0; i < pool.length; i++) {
        if (need <= 1e-9) break;
        const rate = pool[i][0], k = pool[i][1];
        if (rate >= p.rate && k) break;
        let t;
        if (k === '') { t = Math.min(need, fill); fill -= t; }
        else { t = Math.min(need, m[k]); m[k] -= t; displaced[k] = (displaced[k] || 0) + t; }
        need -= t;
        got += t;
      }
    });
    m[p.id] = got;
  });
  ROLES.forEach(role => {
    let left = open[role];
    [role].concat(ADJ[role]).forEach(rr => {
      if (left <= 1e-9) return;
      Object.keys(m).filter(k => (by[k].role || 'W') === rr).sort((a, b) => (by[b].rate - by[a].rate) || cmpId(a, b)).forEach(k => {
        if (left <= 1e-9) return;
        const spare = Math.min(P.max_min - m[k], (P.extra || P.max_min) - (absorbed[k] || 0));
        if (spare <= 1e-9) return;
        const t = Math.min(spare, left);
        m[k] += t;
        absorbed[k] = (absorbed[k] || 0) + t;
        left -= t;
      });
    });
    fill += Math.max(0, left);
  });
  const after = teamValue(roster, m, P);
  const list = o => Object.keys(o).filter(k => o[k] > 0.05).map(k => [k, o[k]]).sort((a, b) => b[1] - a[1]);
  return { before: before.net, after: after.net, delta: after.net - before.net, delta_off: after.off - before.off, delta_def: after.def - before.def,
    minutes: m, base: base, displaced: list(displaced), absorbed: list(absorbed), fill_before: before.fill, fill_after: fill };
}

function interp(xs, ys, x) {
  const pts = [];
  for (let i = 0; i < xs.length; i++) if (ys[i] !== null && ys[i] !== undefined) pts.push([Number(xs[i]), Number(ys[i])]);
  if (!pts.length) return null;
  if (x <= pts[0][0]) return pts[0][1];
  if (x >= pts[pts.length - 1][0]) return pts[pts.length - 1][1];
  for (let i = 0; i + 1 < pts.length; i++) {
    const a = pts[i], b = pts[i + 1];
    if (a[0] <= x && x <= b[0]) return b[0] > a[0] ? a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0]) : a[1];
  }
  return pts[pts.length - 1][1];
}

function curveDelta(curves, tid, key, shift) {
  const c = ((curves || {}).teams || {})[tid] || {};
  const ys = c[key], xs = (curves || {}).shifts || [];
  if (!ys || !xs.length) return null;
  const a = interp(xs, ys, shift), b = interp(xs, ys, 0);
  return a === null || b === null ? null : a - b;
}

function warOf(rate, minutes, P) { return (rate - P.repl) * minutes * P.pace / P.G / 100 / P.ppw; }

// ── state ─────────────────────────────────────────────────────────────────

function parseState(q, teamIds) {
  const t = String(q.t || '').split(',').filter(x => teamIds.indexOf(x) >= 0);
  const moves = {};
  String(q.m || '').split('.').forEach(s => { const i = s.lastIndexOf('-'); if (i > 0) moves[s.slice(0, i)] = s.slice(i + 1); });
  return { teams: t, moves: moves };
}

function writeState(L, st) {
  try {
    const m = Object.keys(st.moves).map(p => p + '-' + st.moves[p]).join('.');
    const q = [];
    if (st.teams.length) q.push('t=' + st.teams.map(encodeURIComponent).join(','));
    if (m) q.push('m=' + m);
    history.replaceState(null, '', '#/' + L + '/value?tab=trade' + (q.length ? '&' + q.join('&') : ''));
  } catch (e) { /* history unavailable */ }
}

// ── page ──────────────────────────────────────────────────────────────────

function render(el, params, state) {
  const fx = FX(), L = fx.L(params, state);
  el.innerHTML = fx.muted('Loading…');
  return fx.ready().then(() => {
    const S = fx.current(L) || fx.S(params, state, L);
    return HW.load(fx.path(L, S, 'trade.json')).then(d => {
      if (!fx.alive(el)) return;
      if (!fx.ok(d) || !d.players) { el.innerHTML = fx.card('Trade simulator', '', fx.notBuilt('The trade simulator for ' + fx.seasonLabel(L, S), d)); return; }
      page(el, L, S, d, (params && params.query) || {}, fx.S(params, state, L));
    });
  });
}

function page(el, L, S, d, query, shown) {
  const fx = FX();
  const P = d.params || {};
  const cols = d.players.cols || [];
  const players = d.players.rows.map(r => { const o = {}; cols.forEach((c, i) => { o[c] = r[i]; }); o.rate = Number(o.rate); o.o = Number(o.o); o.d = Number(o.d); o.mpg = Number(o.mpg || 0); return o; });
  const byId = {}; players.forEach(p => { byId[p.id] = p; });
  const teamIds = Object.keys(d.teams || {}).filter(t => players.some(p => p.team === t)).sort((a, b) => String(fx.teamName(L, a)).localeCompare(String(fx.teamName(L, b))));
  const st = parseState(query, teamIds);
  if (st.teams.length < 2) { st.teams = teamIds.slice(0, 2); }
  Object.keys(st.moves).forEach(pid => { const p = byId[pid]; if (!p || st.teams.indexOf(p.team) < 0 || st.teams.indexOf(st.moves[pid]) < 0 || st.moves[pid] === p.team) delete st.moves[pid]; });
  const curves = d.curves;
  const noSim = !curves;
  let h = '<div class="card"><div class="card-header">Trade simulator ' + fx.esc(fx.seasonLabel(L, S)) + ' <span class="card-sub">Pick the teams and the players moving. Each player carries a rest-of-season HPM (this season\'s blended with last season\'s projection) and projected minutes; incoming players take minutes from the lowest-rated players at their position, outgoing minutes go to the next players up. Odds come from re-running the season simulation with each team\'s rating shifted' + (curves ? ' (' + fx.num(curves.n_sims, 0) + ' runs a point, shifts ' + (curves.shifts || []).map(x => fx.signed(x, 1)).join(', ') + ' per 100)' : '') + '. <strong>Cap not checked</strong>: there is no free, legitimate salary source we use.</span></div>';
  if (shown && shown !== S) h += '<div class="pad">' + fx.muted('The trade simulator always uses the current season (' + fx.esc(fx.seasonLabel(L, S)) + ').') + '</div>';
  if (noSim) h += '<div class="pad">' + fx.muted('No season simulation right now (' + fx.esc(d.phase || 'offseason') + '): the page shows the rating change and wins over a full season from the game model\'s conversion, without odds.') + '</div>';
  h += '<div class="tr-pick" id="tr-pick"></div></div><div class="grid-' + (st.teams.length === 3 ? '3' : '2') + '" id="tr-rosters"></div><div id="tr-out"></div>';
  h += '<div class="card"><div class="pad pg-note">How to read it: the rating change is the team\'s net points per 100 possessions after the depth chart is rebuilt (impact of every player × minutes, replacement level ' + fx.signed(P.repl, 1) + ' for unfilled minutes, each player capped at ' + fx.num(P.max_min, 1) + ' minutes). Each team\'s odds are read off its own sensitivity curve with every other team at its rating, so the effect of the two trading teams meeting each other is left out (small). Beyond the curve\'s range (±' + fx.num(curves ? Math.max.apply(null, curves.shifts.map(Math.abs)) : 6, 0) + ') the edge value is used. Next season applies the aging curve to each player\'s rate over a full season at current minutes. Model suggestions based on on-field value; not considering the salary cap, contracts, fit or availability.</div></div>';
  el.innerHTML = h;

  function teamSelect(i) {
    return '<label>Team ' + (i + 1) + ' <select data-slot="' + i + '">' + teamIds.map(t => '<option value="' + fx.esc(t) + '"' + (st.teams[i] === t ? ' selected' : '') + '>' + fx.esc(fx.teamName(L, t)) + '</option>').join('') + '</select></label>';
  }
  function drawPick() {
    const pick = document.getElementById('tr-pick');
    pick.innerHTML = '<div class="lab-controls hf-controls">' + st.teams.map((t, i) => teamSelect(i)).join('') +
      (st.teams.length < 3 ? '<button type="button" class="tbtn" id="tr-add">Add a third team</button>' : '<button type="button" class="tbtn" id="tr-rm">Remove team 3</button>') +
      '<button type="button" class="tbtn" id="tr-clear">Clear players</button><button type="button" class="tbtn" id="tr-copy">Copy link</button><span class="muted-inline" id="tr-copied"></span></div>';
    pick.querySelectorAll('select[data-slot]').forEach(s => s.onchange = e => {
      const i = Number(e.target.dataset.slot), v = e.target.value;
      const j = st.teams.indexOf(v);
      if (j >= 0 && j !== i) st.teams[j] = st.teams[i];
      st.teams[i] = v;
      Object.keys(st.moves).forEach(pid => { const p = byId[pid]; if (!p || st.teams.indexOf(p.team) < 0 || st.teams.indexOf(st.moves[pid]) < 0) delete st.moves[pid]; });
      redraw();
    });
    const add = document.getElementById('tr-add');
    if (add) add.onclick = () => { const t = teamIds.find(x => st.teams.indexOf(x) < 0); if (t) st.teams.push(t); redraw(); };
    const rm = document.getElementById('tr-rm');
    if (rm) rm.onclick = () => { const gone = st.teams.pop(); Object.keys(st.moves).forEach(pid => { if (byId[pid].team === gone || st.moves[pid] === gone) delete st.moves[pid]; }); redraw(); };
    document.getElementById('tr-clear').onclick = () => { st.moves = {}; redraw(); };
    document.getElementById('tr-copy').onclick = () => {
      const msg = document.getElementById('tr-copied');
      try { navigator.clipboard.writeText(location.href).then(() => { msg.textContent = 'Link copied.'; }, () => { msg.textContent = location.href; }); } catch (e) { msg.textContent = location.href; }
    };
  }
  function drawRosters() {
    const box = document.getElementById('tr-rosters');
    box.className = 'grid-' + (st.teams.length === 3 ? '3' : '2');
    box.innerHTML = st.teams.map(t => {
      const team = players.filter(p => p.team === t);
      const base = baseline(team, P);
      team.sort((a, b) => (base[b.id] - base[a.id]) || (b.mpg - a.mpg) || cmpId(a.id, b.id));
      const others = st.teams.filter(x => x !== t);
      const COLS = [{ label: '' }, { label: 'Player' }, { label: 'Pos' }, { label: 'Min', align: 'right', title: 'Projected minutes a game (in the rotation)' }, { label: 'HPM', align: 'right', title: 'Rest-of-season rate per 100' }, { label: 'Age', align: 'right' }];
      const inRot = p => (base[p.id] || 0) >= 0.5 || !!st.moves[p.id];
      const rest = team.filter(p => !inRot(p));
      return '<div class="card"><div class="card-header" style="border-left:4px solid ' + fx.esc(fx.teamColour(L, t)) + '">' + fx.esc(fx.teamName(L, t)) + ' <span class="card-sub">rating ' + fx.signed((d.teams[t] || {}).rating, 1) + ' per 100</span></div>' +
        HW.tableHTML(COLS, team.filter(inRot).map(rowOf), { compact: true }) +
        (rest.length ? '<details class="tr-rot tr-rest"><summary>Outside the rotation (' + rest.length + ')</summary>' + HW.tableHTML(COLS, rest.map(rowOf), { compact: true }) + '</details>' : '') + '</div>';
      function rowOf(p) {
        const sel = st.moves[p.id];
        const ctl = others.length === 1 ? '<input type="checkbox" class="tr-mv" data-pid="' + fx.esc(p.id) + '" data-to="' + fx.esc(others[0]) + '"' + (sel ? ' checked' : '') + ' aria-label="Trade ' + fx.esc(p.name) + '">'
              : '<select class="tr-mv-s" data-pid="' + fx.esc(p.id) + '"><option value="">stay</option>' + others.map(o => '<option value="' + fx.esc(o) + '"' + (sel === o ? ' selected' : '') + '>to ' + fx.esc(fx.teamAbbr(L, o)) + '</option>').join('') + '</select>';
            return { _class: sel ? 'tr-sel' : '', cells: [{ v: sel ? 1 : 0, html: ctl }, { v: p.name, html: fx.playerLink(L, p.id, p.name) + (p.inj ? ' <span class="chip red" title="' + fx.esc(p.inj) + '">inj</span>' : '') + (p.basis === 'r' ? ' <span class="chip" title="' + fx.esc(BASIS.r) + '">new</span>' : '') },
              { v: p.role, html: fx.esc(ROLE_ONE[p.role] || p.role) }, { v: base[p.id], html: fx.num(base[p.id], 0) }, { v: p.rate, html: fx.signed(p.rate, 1) }, { v: p.age, html: fx.num(p.age, 0) }] };
      }
    }).join('');
    box.querySelectorAll('input.tr-mv').forEach(c => c.onchange = e => { const pid = e.target.dataset.pid; if (e.target.checked) st.moves[pid] = e.target.dataset.to; else delete st.moves[pid]; redraw(true); });
    box.querySelectorAll('select.tr-mv-s').forEach(c => c.onchange = e => { const pid = e.target.dataset.pid; if (e.target.value) st.moves[pid] = e.target.value; else delete st.moves[pid]; redraw(true); });
  }
  function drawResults() {
    const out = document.getElementById('tr-out');
    const movers = Object.keys(st.moves);
    if (!movers.length) { out.innerHTML = fx.card('Result', '', '<div class="pad">' + fx.muted('Tick the players to move. With three teams, choose each player\'s new team.') + '</div>'); return; }
    out.innerHTML = '<div class="grid-' + (st.teams.length === 3 ? '3' : '2') + '">' + st.teams.map(t => teamResult(t)).join('') + '</div>';
    HW.sortable(out);
  }
  function teamResult(t) {
    const team = players.filter(p => p.team === t);
    const outIds = Object.keys(st.moves).filter(pid => byId[pid].team === t);
    const incoming = Object.keys(st.moves).filter(pid => st.moves[pid] === t).map(pid => byId[pid]);
    const res = applyMoves(team, outIds, incoming, P);
    const T = d.teams[t] || {};
    const left = fx.isNum(T.left) ? T.left : (noSim ? d.games : 0);
    const mins = p => Math.min(p.mpg || 0, P.max_min);
    const warIn = incoming.reduce((s, p) => s + warOf(p.rate, mins(p) * left, P), 0);
    const warOut = outIds.reduce((s, pid) => s + warOf(byId[pid].rate, mins(byId[pid]) * left, P), 0);
    const nextIn = incoming.reduce((s, p) => s + warOf(p.next, mins(p) * d.games, P), 0);
    const nextOut = outIds.reduce((s, pid) => s + warOf(byId[pid].next, mins(byId[pid]) * d.games, P), 0);
    let dW = curves ? curveDelta(curves, t, 'exp_w', res.delta) : null;
    if (dW === null) dW = res.delta * P.pace / 100 * left / P.ppw;
    const range = curves ? Math.max.apply(null, curves.shifts.map(Math.abs)) : null;
    const nowTxt = left > 0 ? (dW >= 0.5 ? 'wins now' : dW <= -0.5 ? 'weakens now' : 'about even now') : (curves && Math.abs(curveDelta(curves, t, 'p_title', res.delta) || 0) >= 0.005 ? ((curveDelta(curves, t, 'p_title', res.delta) > 0) ? 'better title odds now' : 'worse title odds now') : 'no change this season');
    const dNext = nextIn - nextOut;
    const longTxt = dNext >= 0.5 ? 'long-term gain' : dNext <= -0.5 ? 'long-term cost' : 'about even next season';
    const nm = pid => (byId[pid] || {}).name || fx.playerName(L, pid);
    let h = '<div class="card"><div class="card-header" style="border-left:4px solid ' + fx.esc(fx.teamColour(L, t)) + '">' + fx.esc(fx.teamName(L, t)) + ' <span class="card-sub tr-verdict"><strong>' + fx.esc(nowTxt.charAt(0).toUpperCase() + nowTxt.slice(1)) + ', ' + fx.esc(longTxt) + '.</strong></span></div><div class="pad">';
    h += '<div class="tr-io"><div><span class="muted-inline">In</span> ' + (incoming.length ? incoming.map(p => fx.playerLink(L, p.id, p.name) + ' <span class="muted-inline">' + fx.esc(ROLE_ONE[p.role] || '') + ', ' + fx.signed(p.rate, 1) + '</span>').join(', ') : '—') + '</div>' +
      '<div><span class="muted-inline">Out</span> ' + (outIds.length ? outIds.map(pid => fx.playerLink(L, pid, nm(pid)) + ' <span class="muted-inline">' + fx.esc(ROLE_ONE[byId[pid].role] || '') + ', ' + fx.signed(byId[pid].rate, 1) + '</span>').join(', ') : '—') + '</div></div>';
    h += '<div class="kpi-grid tr-kpi">' + [
      fx.tile('Rating', fx.signed(res.delta, 2), (fx.isNum(T.rating) ? fx.signed(T.rating, 1) + ' → ' + fx.signed(T.rating + res.delta, 1) : 'net per 100') + ' · O ' + fx.signed(res.delta_off, 1) + ' · D ' + fx.signed(res.delta_def, 1)),
      fx.tile(left > 0 ? 'Wins' : 'Wins (season over)', fx.signed(dW, 1), (fx.isNum(T.exp_w) && curves ? fx.num(T.exp_w, 1) + ' → ' + fx.num(T.exp_w + dW, 1) + ' expected' : (noSim ? 'over a full season' : '')) + (range !== null && Math.abs(res.delta) > range ? ' · beyond the curve' : '')),
      fx.tile('Value in − out', fx.signed(warIn - warOut, 1), 'WAR over ' + fx.num(left, 0) + ' games at their minutes'),
      fx.tile('Next season', fx.signed(dNext, 1), 'WAR, aging applied')
    ].join('') + '</div>';
    if (curves) {
      const rows = ODDS.filter(o => fx.isNum(T[o[0]]) && (curves.keys || []).indexOf(o[0]) >= 0 && !(L === 'wnba' && o[0] === 'p_top6')).map(o => {
        const dd = curveDelta(curves, t, o[0], res.delta);
        const after = fx.isNum(dd) ? Math.max(0, Math.min(1, T[o[0]] + dd)) : null;
        return [o[1], { v: T[o[0]], html: fx.pct(T[o[0]]) }, { v: after, html: fx.pct(after) }, { v: fx.isNum(after) ? after - T[o[0]] : null, html: fx.isNum(after) ? '<span class="' + (after - T[o[0]] > 0.0005 ? (o[0] === 'p_top4' ? 'pg-down' : 'pg-up') : after - T[o[0]] < -0.0005 ? (o[0] === 'p_top4' ? 'pg-up' : 'pg-down') : '') + '">' + fx.signed(100 * (after - T[o[0]]), 1) + ' pp</span>' : '—' }];
      });
      h += rows.length ? HW.tableHTML([{ label: 'Season odds' }, { label: 'Now', align: 'right' }, { label: 'After', align: 'right' }, { label: 'Change', align: 'right' }], rows, { compact: true }) : '';
    }
    const mn = x => fx.num(x, x < 1 ? 1 : 0);
    const disp = res.displaced.map(x => fx.esc(nm(x[0])) + ' −' + mn(x[1]));
    const abs = res.absorbed.map(x => fx.esc(nm(x[0])) + ' +' + mn(x[1]));
    h += '<div class="tr-depth">' + (disp.length ? '<div><span class="muted-inline">Minutes lost to the newcomers</span> ' + disp.join(', ') + '</div>' : '') +
      (abs.length ? '<div><span class="muted-inline">Next players up</span> ' + abs.join(', ') + '</div>' : '') +
      (Math.abs(res.fill_after - res.fill_before) > 0.05 ? '<div><span class="muted-inline">Replacement-level minutes</span> ' + fx.num(res.fill_before, 0) + ' → ' + fx.num(res.fill_after, 0) + '</div>' : '') + '</div>';
    const rot = Object.keys(res.minutes).filter(k => res.minutes[k] > 0.5 || (res.base[k] || 0) > 0.5).sort((a, b) => res.minutes[b] - res.minutes[a]);
    h += '<details class="tr-rot"><summary>Rotation after the trade</summary>' + HW.tableHTML([{ label: 'Player' }, { label: 'Pos' }, { label: 'Before', align: 'right' }, { label: 'After', align: 'right' }, { label: 'HPM', align: 'right' }],
      rot.map(k => { const p = byId[k] || {}; return [{ v: p.name, html: fx.playerLink(L, k, p.name) }, ROLE_ONE[p.role] || '', { v: res.base[k] || 0, html: fx.num(res.base[k] || 0, 0) }, { v: res.minutes[k], html: '<strong>' + fx.num(res.minutes[k], 0) + '</strong>' }, { v: p.rate, html: fx.signed(p.rate, 1) }]; }), { compact: true }) + '</details>';
    return h + '</div></div>';
  }
  function redraw(keepRosters) {
    writeState(L, st);
    if (!keepRosters) { drawPick(); drawRosters(); }
    else document.querySelectorAll('#tr-rosters tr').forEach(tr => { const c = tr.querySelector('[data-pid]'); if (c) tr.classList.toggle('tr-sel', !!st.moves[c.dataset.pid]); });
    drawResults();
  }
  redraw();
}

HW.route('trade', render);
HW.tradeModel = { baseline: baseline, teamValue: teamValue, applyMoves: applyMoves, interp: interp, curveDelta: curveDelta };
})(window.HW);
