/* The Quant Rink — player value (#/value): Rink value (GAR, WAR) for skaters and goalies, the best at each
 * position (C, LW, RW, D, G) and a filterable leaderboard.
 *
 * Data: data/<S>/value.json (analytics/value.py season_value: cols/rows, best, currency, roles).
 * GAR = goals above replacement (EV offence and defence, power play, penalty kill, shooting, penalties;
 * goalies: GSAx above replacement goalies); WAR = GAR / goals per win. Uses RK.fk (skaters.js). */
(function (RK) {
'use strict';

const K = () => RK.fk;
const POS = { C: 'Centres', L: 'Left wings', R: 'Right wings', D: 'Defence', G: 'Goalies' };
const POS_ONE = { C: 'C', L: 'LW', R: 'RW', D: 'D', G: 'G' };
const COMP = [['ev_off', 'EV off'], ['ev_def', 'EV def'], ['pp', 'PP'], ['pk', 'PK'], ['shooting', 'Shoot'], ['pen', 'Pen']];
const ST = { kind: 'S', pos: 'all', team: 'all', min: null, q: '1', n: '100' };

function rowsOf(v) {
  const cols = (v && v.cols) || [];
  return ((v && v.rows) || []).map(r => { const o = {}; cols.forEach((c, i) => { o[c] = r[i]; }); return o; });
}

function why(k, r) {
  if (r.kind === 'G') return (r.why || []).map(w => k.esc(w[0]) + ' ' + (w[0] === 'save %' ? k.fmtV(w[1], '3') : k.signed(w[1], 1))).join(' · ');
  return (r.why || []).map(w => k.esc(w[0]) + ' ' + k.signed(w[1], 1)).join(' · ');
}

function render(el, params, state) {
  const k = K();
  el.innerHTML = k.muted('Loading…');
  const q0 = (params && params.query) || {};
  if (q0.tab === 'val' && RK.valuation) return RK.valuation.render(el);
  return k.ready().then(() => {
    const S = k.S(params, state);
    const q = (params && params.query) || {};
    if (ST.key !== S) { ST.key = S; ST.team = 'all'; ST.min = null; }
    ['kind', 'pos', 'team', 'min', 'q', 'n'].forEach(x => { if (q[x] !== undefined && q[x] !== '') ST[x] = q[x]; });
    return Promise.all([k.loadY(S, 'value.json'), k.loadNames()]).then(res => {
      if (!k.alive(el)) return;
      const v = res[0];
      if (!k.ok(v) || !(v.rows || []).length) { el.innerHTML = k.card('Player value ' + k.sLabel(S), '', '<div class="pad">' + k.notBuilt('Player value for ' + k.sLabel(S), v) + '</div>'); return; }
      draw(el, S, v);
      if (RK.valuation) el.insertAdjacentHTML('afterbegin', RK.valuation.tabs(S, 'season'));
    });
  });
}

function draw(el, S, v) {
  const k = K();
  const rows = rowsOf(v);
  const by = {}; rows.forEach(r => { by[r.id] = r; });
  const cur = v.currency || {};
  const best = v.best || {};
  let h = '<div class="card"><div class="card-header">Player value ' + k.esc(k.sLabel(S)) + (k.isNum(v.team_games) ? ' <span class="chip">' + k.int(v.team_games) + ' team games</span>' : '') + ' <span class="card-sub">Rink value: goals above a replacement player (GAR) from even-strength offence and defence (xG RAPM with a box-score prior), the power play, the penalty kill, finishing and penalties; goalies from goals saved above expected against replacement goalies. WAR = GAR / ' + (k.isNum(cur.goals_per_win) ? k.num(cur.goals_per_win, 2) + ' ' : '') + 'goals per win (the derivative of the Pythagorean expectation). Rate: GAR per 60 minutes. Goalies are ranked separately. <a href="#/methodology">Methodology</a></span></div>';
  const topS = rows.filter(r => r.q && r.kind === 'S').sort((a, b) => b.war - a.war)[0];
  const topG = rows.filter(r => r.q && r.kind === 'G').sort((a, b) => b.war - a.war)[0];
  h += k.tiles([k.tile('Most WAR, skater', topS ? k.esc(topS.name) : '—', topS ? k.num(topS.war, 1) + ' WAR · ' + k.num(topS.gar, 1) + ' GAR · ' + k.esc(topS.team || '') : ''),
    k.tile('Most WAR, goalie', topG ? k.esc(topG.name) : '—', topG ? k.num(topG.war, 1) + ' WAR · GSAx ' + k.signed(topG.gsax, 1) + ' · ' + k.esc(topG.team || '') : '')]
    .concat(['C', 'D'].map(p => { const r = by[(best[p] || [])[0]]; return k.tile('Best ' + (p === 'C' ? 'centre' : 'defenceman'), r ? k.esc(r.name) : '—', r ? k.num(r.war, 1) + ' WAR · ' + k.esc(r.team || '') : ''); }))) + '</div>';
  h += '<div class="card"><div class="card-header">Best at each position <span class="card-sub">Qualified players (the catalogues\' floors: skaters 250 five-on-five minutes per 82 team games, prorated; goalies a quarter of the team\'s minutes). "Why" lists the two largest parts of a skater\'s GAR, and a goalie\'s GSAx and save percentage.</span></div><div class="vl-best5">' +
    ['C', 'L', 'R', 'D', 'G'].map(p => '<div><div class="vl-best-h">' + k.esc(POS[p]) + '</div>' + k.table([{ label: '#', align: 'right' }, { label: 'Player' }, { label: 'WAR', align: 'right' }, { label: 'GAR/60', align: 'right' }, { label: 'Pct', align: 'center', title: 'WAR percentile among qualified ' + (p === 'G' ? 'goalies' : 'skaters') }],
      (best[p] || []).map((id, i) => { const r = by[id] || {}; return { _href: k.playerHref(id, S), cells: [i + 1, { v: r.name, html: k.playerLink(id, r.name, S) + ' <span class="muted-inline">' + k.esc(r.team || '') + '</span><div class="vl-why">' + why(k, r) + '</div>' }, { v: r.war, html: '<strong>' + k.num(r.war, 1) + '</strong>' }, { v: r.rate, html: k.num(r.rate, 2) }, { v: r.pct, html: k.pill(r.pct) }] }; }), { compact: true }) + '</div>').join('') + '</div></div>';
  const teams = Array.from(new Set(rows.map(r => r.team).filter(Boolean))).sort();
  const maxToi = Math.max.apply(null, rows.map(r => r.toi || 0).concat([100]));
  if (teams.indexOf(ST.team) < 0) ST.team = 'all';
  if (ST.min === null || !k.isNum(ST.min)) ST.min = 0;
  h += '<div class="card"><div class="card-header">Leaderboard <span class="card-sub" id="vl-sub"></span></div>' +
    '<div class="lab-controls vl-ctl">' +
    '<label>Players<select id="vl-kind"><option value="S">Skaters</option><option value="G">Goalies</option></select></label>' +
    '<label>Position<select id="vl-pos"><option value="all">All</option><option value="F">Forwards</option><option value="C">Centres</option><option value="L">Left wings</option><option value="R">Right wings</option><option value="D">Defence</option></select></label>' +
    '<label>Team<select id="vl-team"><option value="all">All teams</option>' + teams.map(t => '<option value="' + k.esc(t) + '">' + k.esc(k.teamName(t)) + '</option>').join('') + '</select></label>' +
    '<label>Min minutes <span id="vl-min-v"></span><input id="vl-min" type="range" min="0" max="' + Math.ceil(maxToi / 100) * 100 + '" step="50"></label>' +
    '<label>Sample<select id="vl-q"><option value="1">Qualified only</option><option value="0">Everyone over the minutes</option></select></label>' +
    '<label>Show<select id="vl-n"><option value="50">Top 50</option><option value="100">Top 100</option><option value="0">All</option></select></label>' +
    '</div><div id="vl-table"></div><div class="pg-note gq-note">GAR and WAR count the whole season; GAR/60 is the rate. The component columns split a skater\'s GAR (even-strength offence and defence, power play, penalty kill, shooting above expected, penalties drawn less taken). Pct places WAR among qualified players (Pos pct within the position). ΔGAR/60 is the change from last season. Players below the sample floor are placed against the qualified players and do not move theirs. A percentile needs ' + ((v.min_toi_pct || {}).S || 200) + ' minutes (goalies ' + ((v.min_toi_pct || {}).G || 600) + '): before that most values are near-ties that a single game reorders, so there is none.</div></div>';
  el.innerHTML = h;
  const $ = id => document.getElementById(id);
  $('vl-kind').value = ST.kind; $('vl-pos').value = ST.pos; $('vl-team').value = teams.indexOf(ST.team) >= 0 ? ST.team : 'all';
  $('vl-q').value = String(ST.q); $('vl-n').value = String(ST.n); $('vl-min').value = ST.min; $('vl-min-v').textContent = ST.min;
  const redraw = () => { syncUrl(S); drawTable(S, rows); };
  $('vl-kind').onchange = e => { ST.kind = e.target.value; redraw(); };
  $('vl-pos').onchange = e => { ST.pos = e.target.value; redraw(); };
  $('vl-team').onchange = e => { ST.team = e.target.value; redraw(); };
  $('vl-q').onchange = e => { ST.q = e.target.value; redraw(); };
  $('vl-n').onchange = e => { ST.n = e.target.value; redraw(); };
  $('vl-min').oninput = e => { ST.min = Number(e.target.value); $('vl-min-v').textContent = ST.min; };
  $('vl-min').onchange = redraw;
  drawTable(S, rows);
  k.sortable(el);
}

function drawTable(S, rows) {
  const k = K();
  const goalies = ST.kind === 'G';
  document.getElementById('vl-pos').disabled = goalies;
  let list = rows.filter(r => r.kind === (goalies ? 'G' : 'S') && (goalies || ST.pos === 'all' || (ST.pos === 'F' ? r.pos !== 'D' : r.pos === ST.pos)) &&
    (ST.team === 'all' || r.team === ST.team) && (r.toi || 0) >= Number(ST.min || 0) && (String(ST.q) !== '1' || r.q));
  list.sort((a, b) => b.war - a.war);
  const total = list.length;
  if (Number(ST.n) > 0) list = list.slice(0, Number(ST.n));
  document.getElementById('vl-sub').textContent = total + (goalies ? ' goalies' : ' skaters') + (ST.team === 'all' ? '' : ' · ' + k.teamName(ST.team)) + ' · ' + ST.min + '+ minutes';
  const head = [{ label: '#', align: 'right' }, { label: 'Player' }, { label: 'Team' }].concat(goalies ? [] : [{ label: 'Pos' }]).concat([{ label: 'Age', align: 'right' }, { label: 'GP', align: 'right' }, { label: 'TOI', align: 'right', title: 'Minutes' },
    { label: 'GAR', align: 'right' }, { label: 'WAR', align: 'right' }, { label: 'GAR/60', align: 'right' }])
    .concat(goalies ? [{ label: 'GSAx', align: 'right' }] : COMP.map(c => ({ label: c[1], align: 'right', title: 'GAR from ' + c[1] })))
    .concat([{ label: 'Pct', align: 'center' }, { label: 'Pos pct', align: 'center' }, { label: 'ΔGAR/60', align: 'right', title: 'Change from last season' }, { label: 'Last WAR', align: 'right' }]);
  document.getElementById('vl-table').innerHTML = list.length ? k.table(head, list.map((r, i) => ({ _href: k.playerHref(r.id, S), cells: [i + 1, { v: r.name, html: k.playerLink(r.id, r.name, S) }, { v: r.team, html: k.teamChip(r.team, S) }]
    .concat(goalies ? [] : [POS_ONE[r.pos] || r.pos]).concat([{ v: r.age, html: k.num(r.age, 0) }, r.gp, { v: r.toi, html: k.num(r.toi, 0) }, { v: r.gar, html: k.num(r.gar, 1) }, { v: r.war, html: '<strong>' + k.num(r.war, 2) + '</strong>' }, { v: r.rate, html: k.num(r.rate, 3) }])
    .concat(goalies ? [{ v: r.gsax, html: k.signed(r.gsax, 1) }] : COMP.map(c => ({ v: r[c[0]], html: k.num(r[c[0]], 1) })))
    .concat([{ v: r.pct, html: k.pill(r.pct) }, { v: r.pct_pos, html: k.pill(r.pct_pos) }, { v: r.d_rate, html: k.isNum(r.d_rate) ? '<span class="' + (r.d_rate > 0 ? 'pg-up' : r.d_rate < 0 ? 'pg-down' : '') + '">' + k.signed(r.d_rate, 3) + '</span>' : '—' }, { v: r.prev_war, html: k.num(r.prev_war, 2) }]) })), { compact: true, sticky: true })
    : k.muted('No players match these filters.');
  k.sortable('vl-table');
}

function syncUrl(S) {
  const k = K();
  try {
    const q = {};
    if (ST.kind !== 'S') q.kind = ST.kind;
    if (ST.pos !== 'all') q.pos = ST.pos;
    if (ST.team !== 'all') q.team = ST.team;
    if (Number(ST.min)) q.min = String(ST.min);
    if (String(ST.q) !== '1') q.q = String(ST.q);
    if (String(ST.n) !== '100') q.n = String(ST.n);
    if (Number(S) !== k.curSeason()) q.s = String(S);
    const qs = Object.keys(q).map(x => encodeURIComponent(x) + '=' + encodeURIComponent(q[x])).join('&');
    history.replaceState(null, '', '#/value?tab=season' + (qs ? '&' + qs : ''));
  } catch (e) { /* history unavailable */ }
}

RK.route('value', render);
})(window.RK);
