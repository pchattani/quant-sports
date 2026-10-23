/* The Quant Rink — trade simulator (#/trade): pick two or three clubs and the players moving, and see each
 * club's depth chart, rating, points and odds change.
 *
 * Data: data/<S>/trade.json for the current season (analytics/value.py trade_payload): players {cols, rows} with
 * each player's rest-of-season GAR per 60 (rate, and its components), projected minutes a game, position, age and
 * next season's rate; teams {abbr: baseline rating, points and odds}; curves {shifts, keys, teams: {abbr: {key:
 * [value at each shift]}}} from re-running the season simulation with that club's rating shifted (goals a game);
 * params (per-game forward / defence / goalie minutes, per-player caps).
 *
 * The depth chart (applyMoves) follows analytics/value.py apply_moves exactly. State in the URL hash:
 *   #/trade?t=<abbr>,<abbr>[,<abbr>]&m=<pid>-<to abbr>.<pid>-<to abbr>
 * No salaries: the cap is not checked. Uses RK.fk (skaters.js). */
(function (RK) {
'use strict';

const K = () => RK.fk;
const ROLES = ['C', 'L', 'R', 'D', 'G'];
const GROUP = { C: 'F', L: 'F', R: 'F', D: 'D', G: 'G' };
const ADJ = { C: ['L', 'R'], L: ['R', 'C'], R: ['L', 'C'], D: [], G: [] };
const POS_ONE = { C: 'C', L: 'LW', R: 'RW', D: 'D', G: 'G' };
const COMPS = ['ev_off', 'ev_def', 'pp', 'pk', 'shooting', 'pen'];
const ODDS = [['p_playoffs', 'Make the playoffs'], ['p_div', 'Win the division'], ['p_conf', 'Reach the Final'], ['p_cup', 'Win the Stanley Cup'], ['p_first', 'First overall pick (lottery)']];

function cmpId(a, b) { a = String(a); b = String(b); return a < b ? -1 : a > b ? 1 : 0; }

// ── the depth chart (mirror of analytics/value.py) ───────────────────────────

function baseline(team, P) {
  const out = {};
  ['F', 'D', 'G'].forEach(g => {
    let left = P.budget[g];
    const cap = P.cap[g];
    team.filter(p => GROUP[p.pos] === g).sort((a, b) => (Math.min(b.mpg || 0, cap) - Math.min(a.mpg || 0, cap)) || cmpId(a.id, b.id)).forEach(p => {
      const take = Math.max(0, Math.min(Math.min(p.mpg || 0, cap), left));
      out[p.id] = take;
      left -= take;
    });
  });
  return out;
}

function teamValue(team, minutes, P) {
  const by = {}; team.forEach(p => { by[p.id] = p; });
  const out = { net: 0, gk: 0 };
  COMPS.forEach(c => { out[c] = 0; });
  const used = { F: 0, D: 0, G: 0 };
  Object.keys(minutes).forEach(k => {
    const p = by[k], m = minutes[k];
    if (!p) return;
    used[GROUP[p.pos]] += m;
    out.net += p.rate * m / 60;
    if (p.pos === 'G') out.gk += p.rate * m / 60;
    COMPS.forEach(c => { out[c] += (p.comps[c] || 0) * m / 60; });
  });
  out.fill = { F: Math.max(0, P.budget.F - used.F), D: Math.max(0, P.budget.D - used.D), G: Math.max(0, P.budget.G - used.G) };
  return out;
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
  const open = { C: 0, L: 0, R: 0, D: 0, G: 0 };
  team.forEach(p => { if (outSet[String(p.id)]) open[p.pos] += base[p.id] || 0; });
  const fill = { F: before.fill.F, D: before.fill.D, G: before.fill.G };
  const displaced = {}, absorbed = {};
  incoming.slice().sort((a, b) => (b.rate - a.rate) || cmpId(a.id, b.id)).forEach(p => {
    const role = p.pos, grp = GROUP[role], cap = P.cap[grp];
    let need = Math.min(p.mpg || 0, cap);
    if (role === 'G') {
      let worse = 0;
      Object.keys(m).forEach(k => { if (by[k].pos === 'G' && !isIn[k] && by[k].rate < p.rate) worse += m[k]; });
      need = Math.min(cap, Math.max(need, open.G + worse + fill.G));
    }
    const take = Math.min(need, open[role]);
    open[role] -= take;
    let got = take;
    need -= take;
    [role].concat(ADJ[role]).forEach(rr => {
      if (need <= 1e-9) return;
      const pool = Object.keys(m).filter(k => by[k].pos === rr && m[k] > 1e-9 && !isIn[k]).map(k => [by[k].rate, String(k)]);
      if (rr === role && fill[grp] > 1e-9) pool.push([P.repl, '']);
      pool.sort((a, b) => (a[0] - b[0]) || cmpId(a[1], b[1]));
      for (let i = 0; i < pool.length; i++) {
        if (need <= 1e-9) break;
        const rate = pool[i][0], k = pool[i][1];
        if (rate >= p.rate && k) break;
        let t;
        if (k === '') { t = Math.min(need, fill[grp]); fill[grp] -= t; }
        else { t = Math.min(need, m[k]); m[k] -= t; displaced[k] = (displaced[k] || 0) + t; }
        need -= t;
        got += t;
      }
    });
    m[p.id] = got;
  });
  ROLES.forEach(role => {
    let left = open[role];
    const grp = GROUP[role], cap = P.cap[grp];
    [role].concat(ADJ[role]).forEach(rr => {
      if (left <= 1e-9) return;
      Object.keys(m).filter(k => by[k].pos === rr).sort((a, b) => (by[b].rate - by[a].rate) || cmpId(a, b)).forEach(k => {
        if (left <= 1e-9) return;
        const spare = Math.min(cap - m[k], ((P.extra || {})[grp] || cap) - (absorbed[k] || 0));
        if (spare <= 1e-9) return;
        const t = Math.min(spare, left);
        m[k] += t;
        absorbed[k] = (absorbed[k] || 0) + t;
        left -= t;
      });
    });
    fill[grp] += Math.max(0, left);
  });
  const after = teamValue(roster, m, P);
  const dc = {};
  COMPS.concat(['gk']).forEach(c => { dc[c] = after[c] - before[c]; });
  const list = o => Object.keys(o).filter(k => o[k] > 0.05).map(k => [k, o[k]]).sort((a, b) => b[1] - a[1]);
  return { before: before.net, after: after.net, delta: after.net - before.net, delta_comp: dc, minutes: m, base: base,
    displaced: list(displaced), absorbed: list(absorbed), fill_before: before.fill, fill_after: fill };
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

// ── state ─────────────────────────────────────────────────────────────────

function parseState(q, teamIds) {
  const t = String(q.t || '').toUpperCase().split(',').filter(x => teamIds.indexOf(x) >= 0);
  const moves = {};
  String(q.m || '').split('.').forEach(s => { const i = s.lastIndexOf('-'); if (i > 0) moves[s.slice(0, i)] = s.slice(i + 1).toUpperCase(); });
  return { teams: t, moves: moves };
}

function writeState(st) {
  try {
    const m = Object.keys(st.moves).map(p => p + '-' + st.moves[p]).join('.');
    const q = [];
    if (st.teams.length) q.push('t=' + st.teams.join(','));
    if (m) q.push('m=' + m);
    history.replaceState(null, '', '#/value?tab=trade' + (q.length ? '&' + q.join('&') : ''));
  } catch (e) { /* history unavailable */ }
}

// ── page ──────────────────────────────────────────────────────────────────

function render(el, params, state) {
  const k = K();
  el.innerHTML = k.muted('Loading…');
  return k.ready().then(() => {
    const S = k.curSeason();
    return Promise.all([k.loadY(S, 'trade.json'), k.loadNames()]).then(res => {
      if (!k.alive(el)) return;
      const d = res[0];
      if (!k.ok(d) || !d.players) { el.innerHTML = k.card('Trade simulator', '', '<div class="pad">' + k.notBuilt('The trade simulator for ' + k.sLabel(S), d) + '</div>'); return; }
      page(el, S, d, (params && params.query) || {}, k.S(params, state));
    });
  });
}

function page(el, S, d, query, shown) {
  const k = K();
  const P = d.params || {};
  const cols = d.players.cols || [];
  const players = d.players.rows.map(r => {
    const o = {}; cols.forEach((c, i) => { o[c] = r[i]; });
    o.rate = Number(o.rate || 0); o.next = Number(o.next || 0); o.mpg = Number(o.mpg || 0); o.comps = {};
    COMPS.forEach(c => { o.comps[c] = Number(o[c] || 0); });
    return o;
  });
  const byId = {}; players.forEach(p => { byId[p.id] = p; });
  const teamIds = Object.keys(d.teams || {}).filter(t => players.some(p => p.team === t)).sort((a, b) => String(k.teamName(a)).localeCompare(String(k.teamName(b))));
  const st = parseState(query, teamIds);
  if (st.teams.length < 2) st.teams = teamIds.slice(0, 2);
  Object.keys(st.moves).forEach(pid => { const p = byId[pid]; if (!p || st.teams.indexOf(p.team) < 0 || st.teams.indexOf(st.moves[pid]) < 0 || st.moves[pid] === p.team) delete st.moves[pid]; });
  const curves = d.curves, noSim = !curves;
  const range = curves ? Math.max.apply(null, curves.shifts.map(Math.abs)) : null;
  let h = '<div class="card"><div class="card-header">Trade simulator ' + k.esc(k.sLabel(S)) + ' <span class="card-sub">Pick the clubs and the players moving. Each player carries a rest-of-season Rink value rate (GAR per 60: this season\'s and last season\'s at 0.7, minute-weighted) and projected ice time; incoming players take minutes from the lowest-rated players at their position (a better goalie takes the starts), outgoing minutes go to the next players up. Odds come from re-running the season simulation with each club\'s rating shifted' + (curves ? ' (' + k.int(curves.n_sims) + ' runs a point, shifts ' + curves.shifts.map(x => k.signed(x, 2)).join(', ') + ' goals a game)' : '') + '. <strong>Cap not checked</strong>: there is no free, legitimate salary source we use.</span></div>';
  if (shown && Number(shown) !== Number(S)) h += '<div class="pad">' + k.muted('The trade simulator always uses the current season (' + k.esc(k.sLabel(S)) + ').') + '</div>';
  if (noSim) h += '<div class="pad">' + k.muted('No season simulation right now (' + k.esc(d.phase || 'offseason') + '): the page shows the rating change and goals over a full season, without odds.') + '</div>';
  h += '<div class="tr-pick" id="tr-pick"></div></div><div id="tr-rosters"></div><div id="tr-out"></div>';
  h += '<div class="card"><div class="pad pg-note gq-note">How to read it: the rating change is the club\'s goals a game above replacement after the depth chart is rebuilt (each player\'s GAR per 60 × ice time; a game has ' + k.num((P.budget || {}).F, 0) + ' forward, ' + k.num((P.budget || {}).D, 0) + ' defence and 60 goalie minutes; caps ' + k.num((P.cap || {}).F, 0) + ' / ' + k.num((P.cap || {}).D, 0) + ' minutes; unfilled minutes at replacement level). It shifts the club\'s net rating in the season simulation; each club\'s odds are read off its own curve with the others at their ratings, so the effect of the trading clubs meeting each other is left out (small). Beyond ±' + k.num(range || 0.5, 2) + ' goals a game the end value is used. Next season applies the delta-method aging curve to each player\'s rate over a full season at current ice time. Model suggestions based on on-field value; not considering the salary cap, contracts, fit or availability.</div></div>';
  el.innerHTML = h;

  function drawPick() {
    const pick = document.getElementById('tr-pick');
    pick.innerHTML = '<div class="lab-controls">' + st.teams.map((t, i) => '<label>Club ' + (i + 1) + ' <select data-slot="' + i + '">' + teamIds.map(x => '<option value="' + k.esc(x) + '"' + (x === t ? ' selected' : '') + '>' + k.esc(k.teamName(x)) + '</option>').join('') + '</select></label>').join('') +
      (st.teams.length < 3 ? '<button type="button" class="tbtn" id="tr-add">Add a third club</button>' : '<button type="button" class="tbtn" id="tr-rm">Remove club 3</button>') +
      '<button type="button" class="tbtn" id="tr-clear">Clear players</button><button type="button" class="tbtn" id="tr-copy">Copy link</button><span class="muted-inline" id="tr-copied"></span></div>';
    pick.querySelectorAll('select[data-slot]').forEach(s => s.onchange = e => {
      const i = Number(e.target.dataset.slot), v = e.target.value, j = st.teams.indexOf(v);
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
      const order = { F: 0, D: 1, G: 2 };
      team.sort((a, b) => (order[GROUP[a.pos]] - order[GROUP[b.pos]]) || ((base[b.id] || 0) - (base[a.id] || 0)) || (b.mpg - a.mpg) || cmpId(a.id, b.id));
      const others = st.teams.filter(x => x !== t);
      const COLS = [{ label: '' }, { label: 'Player' }, { label: 'Pos' }, { label: 'TOI', align: 'right', title: 'Projected minutes a game in the rotation' }, { label: 'GAR/60', align: 'right', title: 'Rest-of-season rate' }, { label: 'Age', align: 'right' }];
      const inRot = p => (base[p.id] || 0) >= 0.5 || !!st.moves[p.id];
      const rest = team.filter(p => !inRot(p));
      const T = d.teams[t] || {};
      return '<div class="card"><div class="card-header" style="border-left:4px solid ' + k.esc(k.teamColour(t)) + '">' + k.esc(k.teamName(t)) + ' <span class="card-sub">rating ' + k.signed(T.rating, 2) + ' goals a game</span></div>' +
        k.table(COLS, team.filter(inRot).map(rowOf), { compact: true }) +
        (rest.length ? '<details class="tr-rot"><summary>Outside the rotation (' + rest.length + ')</summary>' + k.table(COLS, rest.map(rowOf), { compact: true }) + '</details>' : '') + '</div>';
      function rowOf(p) {
        const sel = st.moves[p.id];
        const ctl = others.length === 1 ? '<input type="checkbox" class="tr-mv" data-pid="' + k.esc(p.id) + '" data-to="' + k.esc(others[0]) + '"' + (sel ? ' checked' : '') + ' aria-label="Trade ' + k.esc(p.name) + '">'
          : '<select class="tr-mv-s" data-pid="' + k.esc(p.id) + '"><option value="">stay</option>' + others.map(o => '<option value="' + k.esc(o) + '"' + (sel === o ? ' selected' : '') + '>to ' + k.esc(o) + '</option>').join('') + '</select>';
        return { _class: sel ? 'tr-sel' : '', cells: [{ v: sel ? 1 : 0, html: ctl }, { v: p.name, html: k.playerLink(p.id, p.name) + (p.basis === 'r' ? ' <span class="chip" title="No NHL minutes this season or last: replacement level">new</span>' : '') },
          { v: p.pos, html: POS_ONE[p.pos] || p.pos }, { v: base[p.id] || 0, html: k.num(base[p.id] || 0, 1) }, { v: p.rate, html: k.num(p.rate, 2) }, { v: p.age, html: k.num(p.age, 0) }] };
      }
    }).join('');
    box.querySelectorAll('input.tr-mv').forEach(c => c.onchange = e => { const pid = e.target.dataset.pid; if (e.target.checked) st.moves[pid] = e.target.dataset.to; else delete st.moves[pid]; redraw(true); });
    box.querySelectorAll('select.tr-mv-s').forEach(c => c.onchange = e => { const pid = e.target.dataset.pid; if (e.target.value) st.moves[pid] = e.target.value; else delete st.moves[pid]; redraw(true); });
  }
  function teamResult(t) {
    const team = players.filter(p => p.team === t);
    const outIds = Object.keys(st.moves).filter(pid => byId[pid].team === t);
    const incoming = Object.keys(st.moves).filter(pid => st.moves[pid] === t).map(pid => byId[pid]);
    const res = applyMoves(team, outIds, incoming, P);
    const T = d.teams[t] || {};
    const left = k.isNum(T.left) ? T.left : (noSim ? d.games : 0);
    const mins = p => Math.min(p.mpg || 0, P.cap[GROUP[p.pos]]);
    const garIn = incoming.reduce((s, p) => s + p.rate * mins(p) / 60 * left, 0);
    const garOut = outIds.reduce((s, pid) => s + byId[pid].rate * mins(byId[pid]) / 60 * left, 0);
    const nextIn = incoming.reduce((s, p) => s + p.next * mins(p) / 60 * d.games, 0);
    const nextOut = outIds.reduce((s, pid) => s + byId[pid].next * mins(byId[pid]) / 60 * d.games, 0);
    const dPts = curves ? curveDelta(curves, t, 'exp_pts', res.delta) : null;
    const dGoals = res.delta * left;
    const dCup = curves ? curveDelta(curves, t, 'p_cup', res.delta) : null;
    const nowTxt = left > 0 ? (dPts !== null ? (dPts >= 1 ? 'wins now' : dPts <= -1 ? 'weakens now' : 'about even now') : (dGoals >= 3 ? 'wins now' : dGoals <= -3 ? 'weakens now' : 'about even now'))
      : (dCup !== null && Math.abs(dCup) >= 0.005 ? (dCup > 0 ? 'better Cup odds now' : 'worse Cup odds now') : 'no change this season');
    const dNext = nextIn - nextOut;
    const longTxt = dNext >= 2 ? 'long-term gain' : dNext <= -2 ? 'long-term cost' : 'about even next season';
    const nm = pid => (byId[pid] || {}).name || k.name(pid);
    let o = '<div class="card"><div class="card-header" style="border-left:4px solid ' + k.esc(k.teamColour(t)) + '">' + k.esc(k.teamName(t)) + ' <span class="card-sub tr-verdict"><strong>' + k.esc(nowTxt.charAt(0).toUpperCase() + nowTxt.slice(1)) + ', ' + k.esc(longTxt) + '.</strong></span></div><div class="pad">';
    o += '<div class="tr-io"><div><span class="muted-inline">In</span> ' + (incoming.length ? incoming.map(p => k.playerLink(p.id, p.name) + ' <span class="muted-inline">' + (POS_ONE[p.pos] || '') + ', ' + k.num(p.rate, 2) + '/60</span>').join(', ') : '—') + '</div>' +
      '<div><span class="muted-inline">Out</span> ' + (outIds.length ? outIds.map(pid => k.playerLink(pid, nm(pid)) + ' <span class="muted-inline">' + (POS_ONE[byId[pid].pos] || '') + ', ' + k.num(byId[pid].rate, 2) + '/60</span>').join(', ') : '—') + '</div></div>';
    o += k.tiles([
      k.tile('Rating', k.signed(res.delta, 2), (k.isNum(T.rating) ? k.signed(T.rating, 2) + ' → ' + k.signed(T.rating + res.delta, 2) + ' goals a game' : 'goals a game') + ' · ' + k.signed(dGoals, 1) + ' goals over ' + k.int(left) + ' games'),
      k.tile(left > 0 ? 'Points' : 'Points (season over)', dPts !== null ? k.signed(dPts, 1) : '—', (k.isNum(T.exp_pts) && dPts !== null ? k.num(T.exp_pts, 1) + ' → ' + k.num(T.exp_pts + dPts, 1) + ' expected' : (noSim ? 'no simulation' : '')) + (range !== null && Math.abs(res.delta) > range ? ' · beyond the curve' : '')),
      k.tile('GAR in − out', k.signed(garIn - garOut, 1), 'over ' + k.int(left) + ' games at their ice time'),
      k.tile('Next season', k.signed(dNext, 1), 'GAR, aging applied')
    ]);
    if (curves) {
      const rows = ODDS.filter(x => k.isNum(T[x[0]]) && (curves.keys || []).indexOf(x[0]) >= 0).map(x => {
        const dd = curveDelta(curves, t, x[0], res.delta);
        const after = k.isNum(dd) ? Math.max(0, Math.min(1, T[x[0]] + dd)) : null;
        const ch = k.isNum(after) ? after - T[x[0]] : null;
        const good = x[0] === 'p_first' ? -1 : 1;
        return [x[1], { v: T[x[0]], html: k.pct(T[x[0]], 1) }, { v: after, html: k.pct(after, 1) }, { v: ch, html: k.isNum(ch) ? '<span class="' + (good * ch > 0.0005 ? 'pg-up' : good * ch < -0.0005 ? 'pg-down' : '') + '">' + k.signed(100 * ch, 1) + ' pp</span>' : '—' }];
      });
      if (rows.length) o += k.table([{ label: 'Season odds' }, { label: 'Now', align: 'right' }, { label: 'After', align: 'right' }, { label: 'Change', align: 'right' }], rows, { compact: true });
    }
    const mn = x => k.num(x, x < 1 ? 1 : 0);
    const disp = res.displaced.map(x => k.esc(nm(x[0])) + ' −' + mn(x[1]));
    const abs = res.absorbed.map(x => k.esc(nm(x[0])) + ' +' + mn(x[1]));
    const fb = res.fill_before, fa = res.fill_after;
    const fillTxt = ['F', 'D', 'G'].filter(g => Math.abs(fa[g] - fb[g]) > 0.05).map(g => ({ F: 'forwards', D: 'defence', G: 'goal' })[g] + ' ' + k.num(fb[g], 1) + ' → ' + k.num(fa[g], 1)).join(', ');
    o += '<div class="tr-depth">' + (disp.length ? '<div><span class="muted-inline">Ice time lost to the newcomers (minutes a game)</span> ' + disp.join(', ') + '</div>' : '') +
      (abs.length ? '<div><span class="muted-inline">Next players up</span> ' + abs.join(', ') + '</div>' : '') +
      (fillTxt ? '<div><span class="muted-inline">Replacement-level minutes</span> ' + fillTxt + '</div>' : '') + '</div>';
    const rot = Object.keys(res.minutes).filter(x => res.minutes[x] > 0.5 || (res.base[x] || 0) > 0.5).sort((a, b) => ({ F: 0, D: 1, G: 2 }[GROUP[byId[a].pos]] - { F: 0, D: 1, G: 2 }[GROUP[byId[b].pos]]) || (res.minutes[b] - res.minutes[a]));
    o += '<details class="tr-rot"><summary>Rotation after the trade</summary>' + k.table([{ label: 'Player' }, { label: 'Pos' }, { label: 'Before', align: 'right' }, { label: 'After', align: 'right' }, { label: 'GAR/60', align: 'right' }],
      rot.map(x => { const p = byId[x] || {}; return [{ v: p.name, html: k.playerLink(x, p.name) }, POS_ONE[p.pos] || '', { v: res.base[x] || 0, html: k.num(res.base[x] || 0, 1) }, { v: res.minutes[x], html: '<strong>' + k.num(res.minutes[x], 1) + '</strong>' }, { v: p.rate, html: k.num(p.rate, 2) }]; }), { compact: true }) + '</details>';
    return o + '</div></div>';
  }
  function drawResults() {
    const out = document.getElementById('tr-out');
    if (!Object.keys(st.moves).length) { out.innerHTML = k.card('Result', '', '<div class="pad">' + k.muted('Tick the players to move. With three clubs, choose each player\'s new club.') + '</div>'); return; }
    out.innerHTML = '<div class="grid-' + (st.teams.length === 3 ? '3' : '2') + '">' + st.teams.map(teamResult).join('') + '</div>';
  }
  function redraw(keepRosters) {
    writeState(st);
    if (!keepRosters) { drawPick(); drawRosters(); }
    else document.querySelectorAll('#tr-rosters tr').forEach(tr => { const c = tr.querySelector('[data-pid]'); if (c) tr.classList.toggle('tr-sel', !!st.moves[c.dataset.pid]); });
    drawResults();
  }
  redraw();
}

RK.route('trade', render);
RK.tradeModel = { baseline: baseline, teamValue: teamValue, applyMoves: applyMoves, interp: interp, curveDelta: curveDelta };
})(window.RK);
