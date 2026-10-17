/* The Quant Paddock — driver-swap simulator (#/swap).
 *
 * "Put driver X in car Y": X swaps seats with W, one of Y's drivers. Every pair of current drivers on
 * different teams has been run through the championship simulation with the swap (X gets the seat's
 * pace plus the decomposition's driver difference, the seat's grid distribution, the car's mechanical
 * retirement risk with his own incident risk, and the team's points), with common random numbers
 * against a baseline run; the page adds each change to the published championship odds.
 *
 * Address (shareable): #/swap?x=<driverId>&w=<driverId>. Data: data/<y>/swap.json (current season),
 * data/<y>/value.json (pace context). */
(function (PD) {
'use strict';

const { esc, num, pct, signed, isNum, card, muted, tableHTML } = PD;
const PG = () => PD.pg;
let SW = null, VAL = null, Y = null;
const ST = { x: null, w: null };

function deltas(x, w) {
  const a = x < w ? x : w, b = x < w ? w : x;
  const v = (SW.pairs || {})[a + '|' + b];
  if (!v) return null;
  const mine = x === a;
  return { x: mine ? v.slice(0, 3) : v.slice(3, 6), w: mine ? v.slice(3, 6) : v.slice(0, 3),
    tx: mine ? v.slice(6, 8) : v.slice(8, 10), ty: mine ? v.slice(8, 10) : v.slice(6, 8) };
}

function share() {
  const h = '#/swap' + (ST.x && ST.w ? '?x=' + encodeURIComponent(ST.x) + '&w=' + encodeURIComponent(ST.w) : '');
  try { history.replaceState(null, '', h); } catch (e) { /* ok */ }
  const i = document.getElementById('sw-link');
  if (i) i.value = location.href.split('#')[0] + h;
}

function render(el, params, state) {
  Y = PD.currentSeason();
  el.innerHTML = muted('Loading…');
  return PD.loadAll([Y + '/swap.json', Y + '/value.json']).then(res => {
    if (!PG().alive(el)) return;
    SW = res[0]; VAL = res[1];
    if (!PD.ok(SW) || !SW.lineup) {
      el.innerHTML = card('Driver-swap simulator', String(Y), '<div class="pad">' + PG().notBuilt('The ' + Y + ' swap table', SW) +
        ' <span class="muted-inline">It needs a season still to run: the swaps go through the championship simulation of the remaining rounds.</span></div>');
      return;
    }
    const q = params.query || {};
    const L = SW.lineup;
    ST.x = L[q.x] ? q.x : (ST.x && L[ST.x] ? ST.x : Object.keys(L).sort()[0]);
    ST.w = L[q.w] && L[q.w] !== L[ST.x] ? q.w : null;
    let h = '<div class="page-head"><div><h2>Driver-swap simulator ' + Y + '</h2><div class="ph-sub muted-inline">Put a driver in another car: what it does to both drivers\' and both teams\' seasons over the ' +
      (SW.remaining || []).length + ' sessions left.</div></div><div class="ph-nav"><a href="#/value">Driver value →</a> <a href="#/methodology/value">How it works →</a></div></div>';
    h += card('The swap', esc(SW.label || ''), '<div class="pad sw-ctl">' +
      '<label>Driver<select id="sw-x"></select></label><label>Into the car of<select id="sw-t"></select></label><label>Replacing<select id="sw-w"></select></label>' +
      '<div class="sw-share"><label>Share <input id="sw-link" type="text" readonly></label></div></div>');
    h += '<div id="sw-out"></div>';
    el.innerHTML = h;
    PD.setMeta('Driver-swap simulator · ' + Y);
    const drivers = Object.keys(L).sort((a, b) => (L[a] + a).localeCompare(L[b] + b));
    const teams = Array.from(new Set(drivers.map(d => L[d])));
    const fill = () => {
      const sx = document.getElementById('sw-x'), st = document.getElementById('sw-t'), sw = document.getElementById('sw-w');
      sx.innerHTML = teams.map(t => '<optgroup label="' + esc(PD.teamName(t)) + '">' + drivers.filter(d => L[d] === t).map(d => '<option value="' + esc(d) + '"' + (d === ST.x ? ' selected' : '') + '>' + esc(name(d)) + '</option>').join('') + '</optgroup>').join('');
      const others = teams.filter(t => t !== L[ST.x]);
      if (!ST.w || L[ST.w] === L[ST.x]) ST.w = drivers.find(d => L[d] === others[0]) || null;
      const ty = ST.w ? L[ST.w] : others[0];
      st.innerHTML = others.map(t => '<option value="' + esc(t) + '"' + (t === ty ? ' selected' : '') + '>' + esc(PD.teamName(t)) + '</option>').join('');
      sw.innerHTML = drivers.filter(d => L[d] === ty).map(d => '<option value="' + esc(d) + '"' + (d === ST.w ? ' selected' : '') + '>' + esc(name(d)) + '</option>').join('');
    };
    fill();
    document.getElementById('sw-x').onchange = e => { ST.x = e.target.value; if (L[ST.w] === L[ST.x]) ST.w = null; fill(); out(); };
    document.getElementById('sw-t').onchange = e => { const t = e.target.value; ST.w = drivers.find(d => L[d] === t) || null; fill(); out(); };
    document.getElementById('sw-w').onchange = e => { ST.w = e.target.value; out(); };
    out();
  });
}

function name(d) { return (SW.names || {})[d] || PD.driverName(d); }

function out() {
  const box = document.getElementById('sw-out');
  if (!box) return;
  share();
  if (!ST.x || !ST.w) { box.innerHTML = card('The result', '', '<div class="pad">' + muted('Pick a driver and a seat.') + '</div>'); return; }
  const L = SW.lineup, dd = deltas(ST.x, ST.w);
  if (!dd) { box.innerHTML = card('The result', '', '<div class="pad">' + muted('This pair was not simulated.') + '</div>'); return; }
  const P = SW.published || {}, pd = P.drivers || {}, pt = P.constructors || {};
  const tx = L[ST.x], ty = L[ST.w];
  const clip = v => Math.max(0, Math.min(1, v));
  const drow = (d, del, team) => {
    const b = pd[d] || [];
    return [{ v: name(d), html: PD.driverLink(d, name(d)) + ' <span class="muted-inline">in the ' + esc(PD.teamName(team)) + '</span>' },
      { v: b[0], html: num(b[0], 1) + ' → <strong>' + num(b[0] + del[0], 1) + '</strong> <span class="sw-d">' + signed(del[0], 1) + '</span>' },
      { v: b[1], html: pct(b[1], 1) + ' → <strong>' + pct(clip(b[1] + del[1]), 1) + '</strong>' },
      { v: b[2], html: num(b[2], 1) + ' → <strong>' + num(b[2] + del[2], 1) + '</strong>' }];
  };
  const trow = (t, del) => {
    const b = pt[t] || [];
    return [{ v: PD.teamName(t), html: PD.teamLink(t) }, { v: b[0], html: num(b[0], 1) + ' → <strong>' + num(b[0] + del[0], 1) + '</strong> <span class="sw-d">' + signed(del[0], 1) + '</span>' },
      { v: b[1], html: pct(b[1], 1) + ' → <strong>' + pct(clip(b[1] + del[1]), 1) + '</strong>' }];
  };
  const eff = SW.drv_effect || {};
  const vcar = {};
  if (PD.ok(VAL) && VAL.teams) VAL.teams.forEach(r => { const o = {}; VAL.team_cols.forEach((c, i) => { o[c] = r[i]; }); vcar[o.id] = o; });
  const ctx = '<div class="sw-ctx">' + esc(name(ST.x)) + ': pace above team-mate ' + (isNum(eff[ST.x]) ? signed(-eff[ST.x], 3) + '%' : '—') + '; ' + esc(name(ST.w)) + ': ' + (isNum(eff[ST.w]) ? signed(-eff[ST.w], 3) + '%' : '—') +
    '. Car pace, latest: ' + esc(PD.teamName(tx)) + ' ' + (vcar[tx] && isNum(vcar[tx].car) ? signed(vcar[tx].car, 3) + '%' : '—') + ', ' + esc(PD.teamName(ty)) + ' ' + (vcar[ty] && isNum(vcar[ty].car) ? signed(vcar[ty].car, 3) + '%' : '—') +
    ' (% of a lap, positive = faster).</div>';
  box.innerHTML = card('Drivers', 'Season totals: now → with the swap (expected points, title odds, expected final position).',
    tableHTML([{ label: 'Driver', sortable: false }, { label: 'Expected points', align: 'right', sortable: false }, { label: 'Title', align: 'right', sortable: false }, { label: 'Final position', align: 'right', sortable: false }],
      [{ cells: drow(ST.x, dd.x, ty) }, { cells: drow(ST.w, dd.w, tx) }], { compact: true }) + '<div class="pad">' + ctx + '</div>') +
    card('Constructors', 'Expected points and title odds: now → with the swap.',
      tableHTML([{ label: 'Team', sortable: false }, { label: 'Expected points', align: 'right', sortable: false }, { label: 'Title', align: 'right', sortable: false }],
        [{ cells: trow(ty, dd.ty) }, { cells: trow(tx, dd.tx) }], { compact: true })) +
    '<div class="pg-note">The swap: ' + esc(name(ST.x)) + ' takes ' + esc(name(ST.w)) + '\'s seat in the ' + esc(PD.teamName(ty)) + ' (that seat\'s pace in the race inputs plus the decomposition\'s driver difference, its qualifying grid distribution, the car\'s mechanical retirement risk with his own incident risk, the team\'s form and points), and ' + esc(name(ST.w)) + ' takes his. Each pair: ' + (SW.n || '') +
    ' championship simulations with the same random numbers as a baseline run; the change is added to the published ' + ((P.n || 20000) + '').replace(/\B(?=(\d{3})+(?!\d))/g, ',') + '-run championship. Points already scored stay with the driver and the team that scored them.</div>';
}

PD.route('swap', render);
})(window.PD);
