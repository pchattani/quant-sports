/* The Quant Hardwood — trade simulator (#/<L>/trade): pick two or three teams and the players moving,
 * and see each team's depth chart, rating, wins and chances change.
 *
 * Data: data/<L>/<S>/trade.json for the league's current season (analytics/value.py trade_payload):
 * players {cols, rows} with each player's rest-of-season HPM (rate, o, d), projected minutes, position
 * group, age and next season's rate; teams {tid: baseline rating and odds}; curves {shifts, keys,
 * teams: {tid: {key: [value at each shift]}}} from re-running the season simulation with that team's
 * rating shifted; params (game minutes, cap, per-player cap, replacement, pace, points per win).
 *
 * The depth chart (applyMoves) follows analytics/value.py apply_moves exactly; the odds are the
 * team's curve at the change in its net rating (linear between grid points, the end value beyond it),
 * added to the full simulation's baseline. Draft picks (data/<L>/<S>/picks.json, analytics/picks.py: each team's own
 * future picks valued from its projected finish, with protection presets) and the players' four-season values
 * (valuation.json) give a long-term "value in − out" in the players' unit; picks do not change this season's rating.
 * State lives in the URL hash:
 *   #/<L>/trade?t=<tid>,<tid>[,<tid>]&m=<pid>-<to tid>.<pid>-<to tid>&pk=<from>-<to>-<year>-<round>-<owner>-<protect>,...
 * No salaries: the cap is not checked.
 * Round 9 (28 Oct 2026): with no teams or moves in the address, the page opens on a real, topical example: the most
 * lopsided trade of the last 120 days (deals.json, graded at the time) whose players are all still with the teams that
 * got them, set up "undone" (each player back to the team that sent him), so the change shows what each side would
 * lose by reversing it, i.e. what the trade gave it. A before/after chart of every team's rating and title chance sits
 * on top of the result. */
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
  const picks = [];
  String(q.pk || '').split(',').forEach(s => {
    const a = s.split('-');
    if (a.length === 6) picks.push({ from: a[0], to: a[1], year: Number(a[2]), round: Number(a[3]), owner: a[4], prot: Number(a[5]) || 0 });
  });
  return { teams: t, moves: moves, picks: picks };
}

// ── draft picks (picks.json) ──────────────────────────────────────────────

function pickValue(PKD, pk) {
  const tb = ((PKD || {}).teams || {})[pk.owner];
  if (!tb) return null;
  const i = (tb.years || []).indexOf(pk.year);
  const row = (tb['r' + pk.round] || [])[i];
  if (i < 0 || !row) return null;
  let v = row[0];
  if (pk.round === 1 && pk.prot && tb.prot && tb.prot[String(pk.prot)]) v = tb.prot[String(pk.prot)][i];
  return { v: v, lo: row[1], hi: row[2] };
}

function pickLabel(L, pk) {
  const fx = FX();
  const ord = pk.round === 1 ? '1st' : pk.round === 2 ? '2nd' : '3rd';
  return pk.year + ' ' + ord + (pk.owner !== pk.from ? ' (via ' + fx.teamAbbr(L, pk.owner) + ')' : '') + (pk.prot ? ', top-' + pk.prot + ' protected' : '');
}

function writeState(L, st) {
  try {
    const m = Object.keys(st.moves).map(p => p + '-' + st.moves[p]).join('.');
    const q = [];
    if (st.teams.length) q.push('t=' + st.teams.map(encodeURIComponent).join(','));
    if (m) q.push('m=' + m);
    if ((st.picks || []).length) q.push('pk=' + st.picks.map(x => [x.from, x.to, x.year, x.round, x.owner, x.prot || 0].join('-')).join(','));
    history.replaceState(null, '', '#/' + L + '/value?tab=trade' + (q.length ? '&' + q.join('&') : ''));
  } catch (e) { /* history unavailable */ }
}

// ── page ──────────────────────────────────────────────────────────────────

function render(el, params, state) {
  const fx = FX(), L = fx.L(params, state);
  el.innerHTML = fx.muted('Loading…');
  return fx.ready().then(() => {
    const S = fx.current(L) || fx.S(params, state, L);
    return HW.loadAll([fx.path(L, S, 'trade.json'), fx.path(L, S, 'picks.json'), fx.path(L, S, 'valuation.json'), fx.path(L, S, 'deals.json')]).then(r => {
      const d = r[0];
      if (!fx.alive(el)) return;
      if (!fx.ok(d) || !d.players) { el.innerHTML = fx.card('Trade simulator', '', fx.notBuilt('The trade simulator for ' + fx.seasonLabel(L, S), d)); return; }
      const v4 = {};
      const val = r[2];
      if (fx.ok(val) && val.cols) { const iv = val.cols.indexOf('id'), vv = val.cols.indexOf('v'); (val.rows || []).forEach(x => { v4[String(x[iv])] = x[vv]; }); }
      let query = (params && params.query) || {};
      const pre = !query.t && !query.m && !query.pk ? topical(d, fx.ok(r[3]) ? r[3] : null) : null;
      if (pre) query = Object.assign({}, query, { t: pre.teams.join(','), m: pre.moves });
      page(el, L, S, d, query, fx.S(params, state, L), fx.ok(r[1]) ? r[1] : null, v4, pre);
    });
  });
}

/* the topical example: the most lopsided two-team trade of the last 120 days still intact on today's rosters, undone */
function topical(d, deals) {
  if (!deals || !Array.isArray(deals.deals) || !d || !d.players) return null;
  const cols = d.players.cols || [], iId = cols.indexOf('id'), iT = cols.indexOf('team');
  const teamOf = {}; (d.players.rows || []).forEach(r => { teamOf[String(r[iId])] = String(r[iT]); });
  const now = Date.parse((d.updated_at || '').slice(0, 10)) || (window.QK ? QK.now() : Date.now());
  let best = null;
  deals.deals.forEach(x => {
    if (!x || (x.teams || []).length !== 2 || !(x.sides || []).length || !isFinite(Date.parse(x.date)) || now - Date.parse(x.date) > 120 * 864e5) return;
    const moves = [];
    let ok = true;
    x.sides.forEach(sd => (sd['in'] || []).forEach(it => {
      if (it.k !== 'p') return;
      const from = (x.teams || []).filter(t => String(t) !== String(sd.team))[0];
      if (teamOf[String(it.id)] !== String(sd.team)) ok = false; else moves.push(String(it.id) + '-' + String(from));
    }));
    const sh = x.sides.map(sd => sd.share).filter(v => typeof v === 'number');
    /* players both ways, so undoing it is the whole deal (picks stay out of the example) */
    if (!ok || !moves.length || !sh.length || !x.sides.every(sd => (sd['in'] || []).some(it => it.k === 'p'))) return;
    const lop = Math.abs(Math.max.apply(null, sh) - 0.5) * (x.total || 0);
    if (!best || lop > best.lop) best = { lop: lop, deal: x, teams: x.teams.map(String), moves: moves.join('.') };
  });
  return best;
}

function page(el, L, S, d, query, shown, PKD, V4, PRE) {
  const fx = FX();
  const P = d.params || {};
  const cols = d.players.cols || [];
  const players = d.players.rows.map(r => { const o = {}; cols.forEach((c, i) => { o[c] = r[i]; }); o.rate = Number(o.rate); o.o = Number(o.o); o.d = Number(o.d); o.mpg = Number(o.mpg || 0); return o; });
  const byId = {}; players.forEach(p => { byId[p.id] = p; });
  const teamIds = Object.keys(d.teams || {}).filter(t => players.some(p => p.team === t)).sort((a, b) => String(fx.teamName(L, a)).localeCompare(String(fx.teamName(L, b))));
  const st = parseState(query, teamIds);
  if (st.teams.length < 2) { st.teams = teamIds.slice(0, 2); }
  Object.keys(st.moves).forEach(pid => { const p = byId[pid]; if (!p || st.teams.indexOf(p.team) < 0 || st.teams.indexOf(st.moves[pid]) < 0 || st.moves[pid] === p.team) delete st.moves[pid]; });
  const pkYears = PKD && PKD.teams && Object.keys(PKD.teams).length ? (PKD.teams[Object.keys(PKD.teams)[0]].years || []) : [];
  const pkRounds = ((PKD || {}).constants || {}).rounds || 2;
  const pkPresets = ((PKD || {}).constants || {}).presets || [];
  const validPick = x => st.teams.indexOf(x.from) >= 0 && st.teams.indexOf(x.to) >= 0 && x.from !== x.to && pkYears.indexOf(x.year) >= 0 && x.round >= 1 && x.round <= pkRounds && !!(PKD.teams || {})[x.owner];
  st.picks = PKD ? st.picks.filter(validPick) : [];
  const curves = d.curves;
  const noSim = !curves;
  let h = '<div class="card"><div class="card-header">Trade simulator ' + fx.esc(fx.seasonLabel(L, S)) + ' <span class="card-sub">Pick the teams and the players moving. Each player carries a rest-of-season HPM (this season\'s blended with last season\'s projection) and projected minutes; incoming players take minutes from the lowest-rated players at their position, outgoing minutes go to the next players up. Odds come from re-running the season simulation with each team\'s rating shifted' + (curves ? ' (' + fx.num(curves.n_sims, 0) + ' runs a point, shifts ' + (curves.shifts || []).map(x => fx.signed(x, 1)).join(', ') + ' per 100)' : '') + '. <strong>Cap not checked</strong>: there is no free, legitimate salary source we use.</span></div>';
  if (PRE) {
    const dl = PRE.deal, win = dl.sides.slice().sort((a, b) => (b.share || 0) - (a.share || 0))[0], lose = dl.sides.filter(x => x !== win)[0];
    const items = sd => (sd['in'] || []).map(it => it.name || it.label).filter(Boolean).join(', ');
    h += '<div class="pad"><div class="qk-note"><b>Loaded for you: the most lopsided trade of the last four months, undone.</b> On ' + fx.esc(HW.fmtDate(dl.date, { weekday: false })) + ' ' + fx.esc(fx.teamName(L, win.team)) + ' got ' + fx.esc(items(win) || 'picks') + ' (grade ' + fx.esc(win.grade || '—') + ') and ' + fx.esc(fx.teamName(L, lose.team)) + ' got ' + fx.esc(items(lose) || 'picks') + ' (grade ' + fx.esc(lose.grade || '—') + '). Every player is sent back below, so each team’s change is what reversing the deal would cost it: the opposite is what the trade gave it. Clear the players to build your own.</div></div>';
  }
  if (shown && shown !== S) h += '<div class="pad">' + fx.muted('The trade simulator always uses the current season (' + fx.esc(fx.seasonLabel(L, S)) + ').') + '</div>';
  if (noSim) h += '<div class="pad">' + fx.muted('No season simulation right now (' + fx.esc(d.phase || 'offseason') + '): the page shows the rating change and wins over a full season from the game model\'s conversion, without odds.') + '</div>';
  h += '<div class="tr-pick" id="tr-pick"></div></div><div class="grid-' + (st.teams.length === 3 ? '3' : '2') + '" id="tr-rosters"></div>' + (PKD ? '<div class="card" id="tr-picks"></div>' : '') + '<div id="tr-out"></div>';
  h += '<div class="card"><div class="pad pg-note">How to read it: the rating change is the team\'s net points per 100 possessions after the depth chart is rebuilt (impact of every player × minutes, replacement level ' + fx.signed(P.repl, 1) + ' for unfilled minutes, each player capped at ' + fx.num(P.max_min, 1) + ' minutes). Each team\'s chances are read off its own sensitivity curve with every other team at its rating, so the effect of the two trading teams meeting each other is left out (small). Beyond the curve\'s range (±' + fx.num(curves ? Math.max.apply(null, curves.shifts.map(Math.abs)) : 6, 0) + ') the end value is used. Next season applies the aging curve to each player\'s rate over a full season at current minutes. Model suggestions based on on-field value; not considering the salary cap, contracts, fit or availability.</div></div>';
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
      st.picks = st.picks.filter(validPick);
      redraw();
    });
    const add = document.getElementById('tr-add');
    if (add) add.onclick = () => { const t = teamIds.find(x => st.teams.indexOf(x) < 0); if (t) st.teams.push(t); redraw(); };
    const rm = document.getElementById('tr-rm');
    if (rm) rm.onclick = () => { const gone = st.teams.pop(); Object.keys(st.moves).forEach(pid => { if (byId[pid].team === gone || st.moves[pid] === gone) delete st.moves[pid]; }); st.picks = st.picks.filter(validPick); redraw(); };
    document.getElementById('tr-clear').onclick = () => { st.moves = {}; st.picks = []; redraw(); };
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
  function drawPicks() {
    const box = document.getElementById('tr-picks');
    if (!box) return;
    const opt = (list, cur) => list.map(x => '<option value="' + fx.esc(x[0]) + '"' + (String(cur) === String(x[0]) ? ' selected' : '') + '>' + fx.esc(x[1]) + '</option>').join('');
    const tOpts = st.teams.map(t => [t, fx.teamAbbr(L, t)]);
    const allOwners = Object.keys(PKD.teams || {}).sort((a, b) => String(fx.teamName(L, a)).localeCompare(String(fx.teamName(L, b)))).map(t => [t, fx.teamAbbr(L, t)]);
    const rows = st.picks.map((x, i) => {
      const pv = pickValue(PKD, x);
      return '<div class="lab-controls hf-controls tr-pkrow" data-i="' + i + '"><label>From<select data-k="from">' + opt(tOpts, x.from) + '</select></label><label>To<select data-k="to">' + opt(tOpts, x.to) + '</select></label>' +
        '<label>Draft<select data-k="year">' + opt(pkYears.map(y => [y, y]), x.year) + '</select></label><label>Round<select data-k="round">' + opt([[1, '1st'], [2, '2nd'], [3, '3rd']].slice(0, pkRounds), x.round) + '</select></label>' +
        '<label>Original owner<select data-k="owner">' + opt(allOwners, x.owner) + '</select></label>' +
        (x.round === 1 ? '<label>Protection<select data-k="prot">' + opt([[0, 'none']].concat(pkPresets.map(n => [n, 'top ' + n])), x.prot || 0) + '</select></label>' : '') +
        '<span class="muted-inline">' + (pv ? '≈ ' + fx.num(pv.v, 1) + ' WAR · likely slot ' + pv.lo + '–' + pv.hi : 'no value') + '</span><button type="button" class="tbtn" data-rm="' + i + '">Remove</button></div>';
    }).join('');
    box.innerHTML = '<div class="card-header">Draft picks <span class="card-sub">A pick\'s value is the pick-value curve over its original owner\'s projected draft slot (this season from the season simulation, later drafts regressed towards the average), discounted 0.9 a season; protected picks convey only outside the top N, else roll a year. ESPN does not list who owns which pick, so choose the original owner. <a href="#/' + L + '/value?tab=moves&mt=picks">Pick values and validation</a></span></div>' +
      '<div class="pad">' + (rows || fx.muted('No picks in this trade.')) + '<button type="button" class="tbtn" id="tr-pkadd">Add a pick</button></div>';
    box.querySelectorAll('.tr-pkrow select').forEach(sel => sel.onchange = e => {
      const i = Number(e.target.closest('.tr-pkrow').dataset.i), k = e.target.dataset.k, x = st.picks[i];
      const v = e.target.value;
      if (k === 'from') { if (x.owner === x.from) x.owner = v; x.from = v; if (x.to === v) x.to = st.teams.filter(t => t !== v)[0]; }
      else if (k === 'to') { x.to = v; if (x.from === v) { x.from = st.teams.filter(t => t !== v)[0]; x.owner = x.from; } }
      else if (k === 'year' || k === 'round' || k === 'prot') { x[k] = Number(v); if (k === 'round' && x.round !== 1) x.prot = 0; }
      else x[k] = v;
      redrawPicks();
    });
    box.querySelectorAll('button[data-rm]').forEach(bt => bt.onclick = () => { st.picks.splice(Number(bt.dataset.rm), 1); redrawPicks(); });
    document.getElementById('tr-pkadd').onclick = () => { st.picks.push({ from: st.teams[0], to: st.teams[1], year: pkYears[0], round: 1, owner: st.teams[0], prot: 0 }); redrawPicks(); };
  }
  function redrawPicks() { writeState(L, st); drawPicks(); drawResults(); }
  function drawResults() {
    const out = document.getElementById('tr-out');
    const movers = Object.keys(st.moves);
    if (!movers.length && !st.picks.length) { out.innerHTML = fx.card('Result', '', '<div class="pad">' + fx.muted('Tick the players to move. With three teams, choose each player\'s new team.') + '</div>'); return; }
    out.innerHTML = '<div class="card"><div class="card-header">Before and after <span class="card-sub">Each team’s net rating (points per 100 possessions against an average team) and title chance, now and with the trade</span></div><div class="grid-2"><div id="tr-ba-r" class="qk-chart" style="--h:240px" role="img" aria-label="Rating before and after"></div><div id="tr-ba-t" class="qk-chart" style="--h:240px" role="img" aria-label="Title chance before and after"></div></div></div>' +
      '<div class="grid-' + (st.teams.length === 3 ? '3' : '2') + '">' + st.teams.map(t => teamResult(t)).join('') + '</div>';
    HW.sortable(out);
    beforeAfter();
  }
  /* the before/after chart: rating and title chance for every team in the deal */
  function beforeAfter() {
    const rows = st.teams.map(t => {
      const team = players.filter(p => p.team === t);
      const outIds = Object.keys(st.moves).filter(pid => byId[pid].team === t);
      const incoming = Object.keys(st.moves).filter(pid => st.moves[pid] === t).map(pid => byId[pid]);
      const res = applyMoves(team, outIds, incoming, P), T = d.teams[t] || {};
      const dT = curves ? curveDelta(curves, t, 'p_title', res.delta) : null;
      return { t: t, r0: T.rating, r1: fx.isNum(T.rating) ? T.rating + res.delta : null, p0: T.p_title, p1: fx.isNum(T.p_title) && fx.isNum(dT) ? Math.max(0, Math.min(1, T.p_title + dT)) : null };
    });
    const cats = rows.map(r => fx.teamAbbr(L, r.t));
    if (rows.some(r => fx.isNum(r.r0))) QKC.bar('#tr-ba-r', { cats: cats, series: [{ name: 'Now', data: rows.map(r => fx.isNum(r.r0) ? Math.round(r.r0 * 10) / 10 : null), color: QK.cssVar('--c-other') }, { name: 'After the trade', data: rows.map(r => fx.isNum(r.r1) ? Math.round(r.r1 * 10) / 10 : null), color: 'model' }],
      labels: true, legend: true, fmt: x => fx.signed(x, 1), valName: 'Net rating (points per 100)', catName: 'Team' });
    else document.getElementById('tr-ba-r').remove();
    if (rows.some(r => fx.isNum(r.p1))) QKC.bar('#tr-ba-t', { cats: cats, series: [{ name: 'Now', data: rows.map(r => fx.isNum(r.p0) ? Math.round(r.p0 * 1000) / 10 : null), color: QK.cssVar('--c-other') }, { name: 'After the trade', data: rows.map(r => fx.isNum(r.p1) ? Math.round(r.p1 * 1000) / 10 : null), color: 'model' }],
      labels: true, legend: true, fmt: x => x + '%', valName: 'Title chance (%)', catName: 'Team' });
    else { const e = document.getElementById('tr-ba-t'); if (e) e.remove(); }
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
    const nowTxt = left > 0 ? (dW >= 0.5 ? 'wins now' : dW <= -0.5 ? 'weakens now' : 'about even now') : (curves && Math.abs(curveDelta(curves, t, 'p_title', res.delta) || 0) >= 0.005 ? ((curveDelta(curves, t, 'p_title', res.delta) > 0) ? 'better title chances now' : 'worse title chances now') : 'no change this season');
    const dNext = nextIn - nextOut;
    const pIn = st.picks.filter(x => x.to === t), pOut = st.picks.filter(x => x.from === t);
    const pv = x => (pickValue(PKD, x) || { v: 0 }).v || 0;
    const v4 = pid => (V4 && fx.isNum(V4[pid]) ? Math.max(0, V4[pid]) : null);
    const missing4 = incoming.concat(outIds.map(pid => byId[pid])).filter(p => v4(p.id) === null).length;
    const long4 = incoming.reduce((s, p) => s + (v4(p.id) || 0), 0) - outIds.reduce((s, pid) => s + (v4(pid) || 0), 0) + pIn.reduce((s, x) => s + pv(x), 0) - pOut.reduce((s, x) => s + pv(x), 0);
    const longT = (V4 || PKD) && (st.picks.length || Object.keys(V4 || {}).length) ? (long4 >= 0.5 ? 'long-term gain' : long4 <= -0.5 ? 'long-term cost' : 'about even long-term') : longTxt;
    const pkTxt = xs => xs.map(x => { const q = pickValue(PKD, x); return '<span class="mv-pick">' + fx.esc(pickLabel(L, x)) + '</span> <span class="muted-inline">≈ ' + fx.num(q ? q.v : null, 1) + (q ? ', likely slot ' + q.lo + '–' + q.hi : '') + '</span>'; });
    const longTxt = dNext >= 0.5 ? 'long-term gain' : dNext <= -0.5 ? 'long-term cost' : 'about even next season';

    const nm = pid => (byId[pid] || {}).name || fx.playerName(L, pid);
    let h = '<div class="card"><div class="card-header" style="border-left:4px solid ' + fx.esc(fx.teamColour(L, t)) + '">' + fx.esc(fx.teamName(L, t)) + ' <span class="card-sub tr-verdict"><strong>' + fx.esc(nowTxt.charAt(0).toUpperCase() + nowTxt.slice(1)) + ', ' + fx.esc(longT) + '.</strong></span></div><div class="pad">';
    const inTxt = incoming.map(p => fx.playerLink(L, p.id, p.name) + ' <span class="muted-inline">' + fx.esc(ROLE_ONE[p.role] || '') + ', ' + fx.signed(p.rate, 1) + '</span>').concat(pkTxt(pIn));
    const outTxt = outIds.map(pid => fx.playerLink(L, pid, nm(pid)) + ' <span class="muted-inline">' + fx.esc(ROLE_ONE[byId[pid].role] || '') + ', ' + fx.signed(byId[pid].rate, 1) + '</span>').concat(pkTxt(pOut));
    h += '<div class="tr-io"><div><span class="muted-inline">In</span> ' + (inTxt.length ? inTxt.join(', ') : '—') + '</div>' +
      '<div><span class="muted-inline">Out</span> ' + (outTxt.length ? outTxt.join(', ') : '—') + '</div></div>';
    h += '<div class="kpi-grid tr-kpi">' + [
      fx.tile('Rating', fx.signed(res.delta, 2), (fx.isNum(T.rating) ? fx.signed(T.rating, 1) + ' → ' + fx.signed(T.rating + res.delta, 1) : 'net per 100') + ' · O ' + fx.signed(res.delta_off, 1) + ' · D ' + fx.signed(res.delta_def, 1)),
      fx.tile(left > 0 ? 'Wins' : 'Wins (season over)', fx.signed(dW, 1), (fx.isNum(T.exp_w) && curves ? fx.num(T.exp_w, 1) + ' → ' + fx.num(T.exp_w + dW, 1) + ' expected' : (noSim ? 'over a full season' : '')) + (range !== null && Math.abs(res.delta) > range ? ' · beyond the curve' : '')),
      fx.tile('Value in − out', fx.signed(warIn - warOut, 1), 'WAR over ' + fx.num(left, 0) + ' games at their minutes'),
      fx.tile('Next season', fx.signed(dNext, 1), 'WAR, aging applied'),
      fx.tile('Four seasons, picks in', V4 || PKD ? fx.signed(long4, 1) : '—', 'WAR: players\' four-season value' + (PKD ? ' + picks' : '') + (missing4 ? ' (' + missing4 + ' with no value)' : ''))
    ].join('') + '</div>';
    if (curves) {
      const rows = ODDS.filter(o => fx.isNum(T[o[0]]) && (curves.keys || []).indexOf(o[0]) >= 0 && !(L === 'wnba' && o[0] === 'p_top6')).map(o => {
        const dd = curveDelta(curves, t, o[0], res.delta);
        const after = fx.isNum(dd) ? Math.max(0, Math.min(1, T[o[0]] + dd)) : null;
        return [o[1], { v: T[o[0]], html: fx.pct(T[o[0]]) }, { v: after, html: fx.pct(after) }, { v: fx.isNum(after) ? after - T[o[0]] : null, html: fx.isNum(after) ? '<span class="' + (after - T[o[0]] > 0.0005 ? (o[0] === 'p_top4' ? 'pg-down' : 'pg-up') : after - T[o[0]] < -0.0005 ? (o[0] === 'p_top4' ? 'pg-up' : 'pg-down') : '') + '">' + fx.signed(100 * (after - T[o[0]]), 1) + ' pp</span>' : '—' }];
      });
      h += rows.length ? HW.tableHTML([{ label: 'Season chances' }, { label: 'Now', align: 'right' }, { label: 'After', align: 'right' }, { label: 'Change', align: 'right' }], rows, { compact: true }) : '';
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
    if (!keepRosters) { drawPick(); drawRosters(); drawPicks(); }
    else document.querySelectorAll('#tr-rosters tr').forEach(tr => { const c = tr.querySelector('[data-pid]'); if (c) tr.classList.toggle('tr-sel', !!st.moves[c.dataset.pid]); });
    drawResults();
  }
  redraw();
}

HW.route('trade', render);
HW.tradeModel = { baseline: baseline, teamValue: teamValue, applyMoves: applyMoves, interp: interp, curveDelta: curveDelta };
})(window.HW);
