/* The Quant Gridiron — player value (#/value).
 *
 * One currency: points (EPA) above a replacement-level player at the same position (GVAR). QB, RB,
 * WR and TE from Gridiron Value (our opponent- and teammate-adjusted EPA ridge), kickers from points
 * over expected, punters from punting EPA over the league's mean punt, defenders from Splash EPA (the
 * plays the box score credits them with). Offensive linemen are not valued individually.
 *
 * Best at each position (the top ten qualified players), then the leaderboard with position, team,
 * sample and sort filters. Trend = this season's Gridiron Value per game minus last season's.
 *
 * Address: #/value?pos=<POS>&team=<abbr>&s=<season>. Data: data/<S>/value.json. Uses GI.fk. */
(function (GI) {
'use strict';

const K = () => GI.fk;
const ST = { pos: '', team: '', qual: true, sort: 'gvar', n: 50, q: '', season: null };
const POS_ORDER = ['QB', 'RB', 'WR', 'TE', 'EDGE', 'DL', 'LB', 'CB', 'S', 'K', 'P'];
const WHY_FMT = {
  pass: ['Passing', 'pts'], rush: ['Rushing', 'pts'], rec: ['Receiving', 'pts'], epa_db: ['EPA/dropback', 'epa'], cpoe: ['CPOE', 'pp'],
  composite: ['QB composite', 'int'], ryoe: ['RYOE/carry', '2'], ypc: ['Yards/carry', '2'], yacoe: ['YAC over exp.', '2'],
  croe: ['Catch rate over exp.', 'pctpp'], target_share: ['Target share', 'pct'], fg_oe: ['FG over exp.', '2'], fg_50: ['50+ made', 'int'],
  fg_pct: ['FG%', 'pct'], net: ['Net average', '1'], inside20: ['Inside the 20', 'pct'], net_oe: ['Net over exp.', '2'],
  sacks: ['Sacks', '1'], qb_hits: ['QB hits', 'int'], tfl: ['TFL', 'int'], ff: ['Forced fumbles', 'int'], pd: ['Passes defensed', 'int'], ints: ['INT', 'int']
};

function fmtWhy(v, f) {
  const k = K();
  if (!k.isNum(v)) return null;
  const x = Number(v);
  switch (f) {
    case 'pts': return k.signed(x, 1);
    case 'epa': return k.signed(x, 3);
    case 'pp': return k.signed(x, 1) + ' pp';
    case 'pctpp': return k.signed(x * 100, 1) + ' pp';
    case 'pct': return (x * 100).toFixed(1) + '%';
    case 'int': return String(Math.round(x));
    case '1': return x.toFixed(1);
    default: return k.signed(x, 2);
  }
}

/* The "why": the components that drive a player's value, in his position's order. */
function whyText(pos, why, keys, n) {
  const parts = [];
  (keys || []).forEach((key, i) => {
    const f = WHY_FMT[key];
    if (!f) return;
    const s = fmtWhy((why || [])[i], f[1]);
    if (s !== null) parts.push(f[0] + ' ' + s);
  });
  return parts.slice(0, n || 4).join(' · ');
}

function rowsOf(d) {
  const cols = d.cols || [];
  const ix = {};
  cols.forEach((c, i) => { ix[c] = i; });
  return (d.rows || []).map(r => {
    const o = {};
    cols.forEach((c, i) => { o[c] = r[i]; });
    return o;
  });
}

function render(el, params, state) {
  const k = K();
  const qy = params.query || {};
  if (qy.pos && POS_ORDER.indexOf(String(qy.pos).toUpperCase()) >= 0) ST.pos = String(qy.pos).toUpperCase();
  if (qy.team) ST.team = String(qy.team).toUpperCase();
  el.innerHTML = k.muted('Loading…');
  return k.ready().then(() => {
    const S = k.S(params, state);
    return Promise.all([k.loadY(S, 'value.json'), k.loadNames()]).then(res => ({ S: S, d: res[0] }));
  }).then(o => {
    if (!k.alive(el)) return;
    const S = o.S, d = o.d;
    if (ST.season !== S) { ST.season = S; if (!qy.team) ST.team = ''; }
    if (!k.ok(d) || !d.rows) {
      el.innerHTML = k.head('Player value', String(S)) + k.card('Player value', '', '<div class="gq-pad">' + k.notBuilt('The ' + S + ' value table', d) + '</div>');
      return;
    }
    const rows = rowsOf(d), by = {};
    rows.forEach(r => { by[r.pid] = r; });
    const notes = d.notes || {};
    let h = k.head('Player value', S + (d.basis_season && d.basis_season !== S ? ' · on ' + d.basis_season + ' values (the season has not started)' : '') +
      ' · points above a replacement player at the same position',
      '<a href="#/trade">Trade simulator →</a><a href="#/transactions">Transactions →</a><a href="#/fantasy">Fantasy →</a><a href="' + k.withQ('#/players', S) + '">Players →</a><a href="#/methodology/trade">How it works →</a>');
    h += '<div class="card"><div class="card-header">The currency <span class="card-sub">' + k.esc(notes.currency || '') + '</span></div><div class="gq-pad gv-notes">' +
      '<p><strong>QB, RB, WR, TE</strong>: Gridiron Value (EPA credited to the passer, receiver or rusher, adjusted for the opponent and the teammates on the play) above the position\'s replacement level. ' +
      '<strong>K</strong>: points over expected from our make-probability model. <strong>P</strong>: punting EPA over the league\'s average punt. ' +
      '<strong>Defenders</strong>: ' + k.esc(notes.defence || '') + '</p><p><strong>Offensive line</strong>: ' + k.esc(notes.ol || '') + '</p></div></div>';
    h += '<div class="card"><div class="card-header">Best at each position <span class="card-sub">The top ten qualified players by value above replacement this season, with what drives the top five; percentile of value per game among qualified players at the position. Click a position for its full table.</span></div><div class="gv-best" id="gv-best"></div></div>';
    h += '<div class="card"><div class="card-header">Leaderboard <span class="card-sub" id="gv-sub"></span></div>' +
      '<div class="lab-controls gq-controls"><label>Position<select id="gv-pos"><option value="">All</option>' + POS_ORDER.map(p => '<option value="' + p + '"' + (p === ST.pos ? ' selected' : '') + '>' + k.esc((d.labels || {})[p] || p) + '</option>').join('') + '</select></label>' +
      '<label>Team<select id="gv-team"><option value="">All teams</option></select></label>' +
      '<label>Sort<select id="gv-sort"><option value="gvar">Season value</option><option value="gvar_pg">Value per game</option><option value="pct">Percentile</option><option value="trend">Trend</option></select></label>' +
      '<label>How many<select id="gv-n"><option>25</option><option>50</option><option>100</option><option value="9999">All</option></select></label>' +
      '<label>Find<input id="gv-q" type="search" placeholder="name" autocomplete="off"></label>' +
      '<label class="inline"><input id="gv-qual" type="checkbox"> qualified only</label></div><div id="gv-table"></div>' +
      '<div class="pg-note gq-note">Season value: points above replacement over the season so far. Per game: per game played. Percentile: of value per game among qualified players at the position (sample floors: the catalogue\'s qualification). Trend: Gridiron Value per game this season minus last season (the raw currency of the players page; defenders in Splash EPA, kickers in points over expected). ' +
      'Replacement level: the ' + Math.round(100 * (d.repl_q || 0.2)) + 'th-percentile rate among the position\'s regulars. ' + k.esc(notes.trend || '') + '</div></div>';
    h += '<div id="gv-proj"></div>';
    el.innerHTML = h;
    k.setMeta('Player value · ' + S);
    best(S, d, by);
    projected(S);
    const teams = Array.from(new Set(rows.map(r => r.team).filter(Boolean))).sort();
    k.$('gv-team').innerHTML = '<option value="">All teams</option>' + teams.map(t => '<option value="' + k.esc(t) + '"' + (t === ST.team ? ' selected' : '') + '>' + k.esc(t) + '</option>').join('');
    k.$('gv-sort').value = ST.sort; k.$('gv-n').value = String(ST.n); k.$('gv-qual').checked = ST.qual; k.$('gv-q').value = ST.q;
    const draw = () => board(S, d, rows);
    k.$('gv-pos').onchange = e => { ST.pos = e.target.value; draw(); };
    k.$('gv-team').onchange = e => { ST.team = e.target.value; draw(); };
    k.$('gv-sort').onchange = e => { ST.sort = e.target.value; draw(); };
    k.$('gv-n').onchange = e => { ST.n = Number(e.target.value); draw(); };
    k.$('gv-qual').onchange = e => { ST.qual = e.target.checked; draw(); };
    k.$('gv-q').oninput = e => { ST.q = e.target.value; draw(); };
    el.querySelectorAll('[data-gvpos]').forEach(a => a.addEventListener('click', ev => {
      ev.preventDefault(); ST.pos = a.getAttribute('data-gvpos'); k.$('gv-pos').value = ST.pos; draw();
      const t = k.$('gv-table'); if (t && t.scrollIntoView) t.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }));
    draw();
  });
}

function best(S, d, by) {
  const k = K();
  const boxes = POS_ORDER.map(pos => {
    const ids = ((d.best || {})[pos] || []).filter(id => by[id]);
    const lab = (d.labels || {})[pos] || pos;
    if (!ids.length) return '<div class="gq-mini gv-mini"><div class="gq-mini-h">' + k.esc(lab) + '</div>' + k.muted('No qualified player yet.') + '</div>';
    return '<div class="gq-mini gv-mini"><div class="gq-mini-h"><a href="#" data-gvpos="' + pos + '">' + k.esc(lab) + '</a></div>' +
      ids.map((id, i) => {
        const r = by[id];
        return '<div class="gq-mini-r' + (i >= 5 ? ' gv-more' : '') + '" title="' + k.esc(whyText(pos, r.why, (d.why || {})[pos], 4)) + '"><span class="gq-mini-n">' + (i + 1) + '</span>' +
          '<span class="gv-nm">' + k.playerLink(id, r.name, S) + ' ' + k.teamChip(r.team, S) + '</span><span class="gq-mini-v gv-v">' + k.signed(r.gvar, 1) + ' ' + k.pill(r.pct) + '</span></div>' +
          (i < 5 ? '<div class="gv-why">' + k.esc(whyText(pos, r.why, (d.why || {})[pos], 3)) + '</div>' : '');
      }).join('') + '</div>';
  });
  k.set('gv-best', '<div class="gq-glance gv-glance">' + boxes.join('') + '</div>');
}

function board(S, d, rows) {
  const k = K();
  const q = k.fold(ST.q.trim());
  let list = rows.filter(r => (!ST.pos || r.pos === ST.pos) && (!ST.team || r.team === ST.team) && (!ST.qual || r.q) && (!q || k.fold(r.name).indexOf(q) >= 0));
  const key = ST.sort;
  list.sort((a, b) => (k.isNum(b[key]) ? b[key] : -1e9) - (k.isNum(a[key]) ? a[key] : -1e9));
  const total = list.length;
  list = list.slice(0, ST.n);
  const sample = r => (r.pos === 'K' ? r.opp + ' FGA' : r.pos === 'P' ? r.opp + ' punts' : ['EDGE', 'DL', 'LB', 'CB', 'S'].indexOf(r.pos) >= 0 ? r.games + ' g' : k.int(r.opp) + ' plays');
  k.set('gv-table', list.length ? k.table([{ label: '#', sortable: false }, { label: 'Player' }, { label: 'Team' }, { label: 'Pos' }, { label: 'Age', align: 'right' }, { label: 'G', align: 'right' },
    { label: 'Sample', align: 'right' }, { label: 'Value', align: 'right', title: 'Points above replacement this season' }, { label: 'Per game', align: 'right' },
    { label: 'Pct', align: 'right' }, { label: 'Trend', align: 'right', title: 'Gridiron Value per game v last season' }, { label: 'Why', sortable: false }],
  list.map((r, i) => ({ _href: k.playerHref(r.pid, S), cells: [{ v: i + 1, cls: 'pos-cell' },
    { v: r.name, html: k.playerLink(r.pid, r.name, S) + (r.q ? '' : ' <span class="gq-tag">small sample</span>') },
    { v: r.team || '', html: r.team ? k.teamChip(r.team, S) : '<span class="muted-inline">unsigned</span>' }, { v: r.pos, html: k.esc(r.pos) },
    { v: r.age, html: k.num(r.age, 0) }, { v: r.games, html: k.int(r.games) }, { v: r.opp, html: k.esc(sample(r)) },
    { v: r.gvar, html: '<strong>' + k.signed(r.gvar, 1) + '</strong>' }, { v: r.gvar_pg, html: k.signed(r.gvar_pg, 2) }, { v: r.pct, html: k.pill(r.pct) },
    { v: r.trend, html: k.isNum(r.trend) ? k.signed(r.trend, 2) : '<span class="muted-inline">—</span>' },
    { v: '', html: '<span class="gv-why-i">' + k.esc(whyText(r.pos, r.why, (d.why || {})[r.pos], 3)) + '</span>' }] })), { compact: true, sticky: true })
    : k.muted('No player matches.'));
  k.sortable(k.$('gv-table'));
  k.set('gv-sub', (ST.pos ? ((d.labels || {})[ST.pos] || ST.pos) : 'All positions') + (ST.team ? ' · ' + ST.team : '') + ' · ' + Math.min(ST.n, total) + ' of ' + total + ' · ' + S);
}

/* Valuation v2 (current season): projected multi-season value with its band, position scarcity, the pick curve. */
const PV = { pos: '', n: 50, sort: 'value' };
function projected(S) {
  const k = K();
  if (k.curSeason && Number(S) !== Number(k.curSeason())) return;
  k.loadY(S, 'valuation.json').then(v => {
    if (!k.ok(v) || !v.rows || !k.$('gv-proj')) return;
    const cols = v.cols || [];
    const rows = v.rows.map(r => { const o = {}; cols.forEach((c, i) => { o[c] = r[i]; }); return o; });
    const yrs = v.seasons || [];
    const draw = () => {
      let list = rows.filter(r => !PV.pos || r.pos === PV.pos);
      list.sort((a, b) => (k.isNum(b[PV.sort]) ? b[PV.sort] : -1e9) - (k.isNum(a[PV.sort]) ? a[PV.sort] : -1e9));
      const total = list.length;
      list = list.slice(0, PV.n);
      k.set('gv-ptable', k.table([{ label: '#', sortable: false }, { label: 'Player' }, { label: 'Team' }, { label: 'Pos' }, { label: 'Age', align: 'right' },
        { label: 'Level now', align: 'right', title: 'Current per-game value above replacement (shrunk; QBs from the QB model)' },
        { label: 'Per game ' + yrs.slice(1).join(' / '), align: 'right', title: 'Projected per-game level by season (ageing)' },
        { label: 'Games', align: 'right', title: 'Expected games: rest of this season, then each season (availability)' },
        { label: 'Value', align: 'right', title: 'Discounted points above replacement over the four seasons' }, { label: '10th–90th', align: 'right' },
        { label: 'Wins', align: 'right' }, { label: 'v marginal starter', align: 'right', title: 'Next season level above the last starter-quality player at the position league-wide' }],
      list.map((r, i) => ({ cells: [{ v: i + 1, cls: 'pos-cell' }, { v: r.name, html: k.playerLink(r.pid, r.name, S) + (r.status === 'RES' ? ' <span class="gq-tag">IR</span>' : '') + (r.status === 'FA' ? ' <span class="gq-tag">unsigned</span>' : '') },
        { v: r.team || '', html: r.team ? k.teamChip(r.team, S) : '<span class="muted-inline">—</span>' }, { v: r.pos, html: k.esc(r.pos) }, { v: r.age, html: k.num(r.age, 0) },
        { v: r.lvl, html: k.signed(r.lvl, 2) + (r.src === 'qb' ? ' <span class="muted-inline">QB</span>' : '') },
        { v: (r.proj || [])[1], html: (r.proj || []).slice(1).map(x => k.num(x, 2)).join(' / ') }, { v: (r.games || [])[0], html: (r.games || []).map(x => k.num(x, 0)).join(' / ') },
        { v: r.value, html: '<strong>' + k.num(r.value, 0) + '</strong>' }, { v: r.lo, html: k.num(r.lo, 0) + '–' + k.num(r.hi, 0) }, { v: r.wins, html: k.num(r.wins, 2) },
        { v: r.over_ms, html: k.signed(r.over_ms, 2) }] })), { compact: true, sticky: true }));
      k.sortable(k.$('gv-ptable'));
      k.set('gv-psub', (PV.pos || 'All positions') + ' · ' + Math.min(PV.n, total) + ' of ' + total);
    };
    const sc = v.scarcity || {};
    const scRows = Object.keys(sc).map(p => ({ cells: [{ v: p, html: k.esc(p) }, { v: sc[p].starters, html: k.int(sc[p].starters) }, { v: sc[p].marginal, html: k.num(sc[p].marginal, 2) },
      { v: sc[p].top5, html: k.num(sc[p].top5, 2) }, { v: sc[p].index, html: '<strong>' + k.num(sc[p].index, 2) + '</strong>' }] }));
    const pc = v.pick_curve || {};
    const pcTxt = pc.ok ? 'Round means (points over four seasons): ' + Object.keys(pc.rounds || {}).map(r => 'R' + r + ' ' + k.num(pc.rounds[r], 1)).join(', ') + '; pick 1 ' + k.num((pc.picks || [])[0], 1) +
      ', pick 32 ' + k.num((pc.picks || [])[31], 1) + ', pick 100 ' + k.num((pc.picks || [])[99], 1) + '. ' + k.esc(pc.note || '') : k.esc(pc.reason || 'not available');
    k.set('gv-proj', '<div class="card"><div class="card-header">Projected value <span class="card-sub">valuation v2: the rest of ' + yrs[0] + ' and the next three seasons, ageing and availability by position, discounted 10% a season; ' +
      k.esc((v.notes || {}).salary || '') + '</span></div><div class="lab-controls gq-controls"><label>Position<select id="gv-ppos"><option value="">All</option>' +
      POS_ORDER.map(p => '<option value="' + p + '">' + p + '</option>').join('') + '</select></label><label>Sort<select id="gv-psort"><option value="value">Value</option><option value="wins">Wins</option><option value="lvl">Level now</option><option value="over_ms">v marginal starter</option><option value="age">Age</option></select></label>' +
      '<label>How many<select id="gv-pn"><option>25</option><option selected>50</option><option>100</option><option value="9999">All</option></select></label></div><div id="gv-ptable"></div>' +
      '<div class="pg-note gq-note"><span id="gv-psub"></span>. ' + k.esc((v.notes || {}).value || '') + ' ' + k.esc((v.notes || {}).qb || '') + ' ' + k.esc((v.notes || {}).availability || '') +
      ' Wins = value × ' + k.num(v.k_resp, 2) + ' (game response) × ' + k.num(v.wins_per_point, 4) + ' wins per point of margin.</div></div>' +
      k.card('Position scarcity', 'next season: the marginal starter is the (32 × starters)-th best projected level; the index is the top-five-to-marginal spread against the average position', k.table(
        [{ label: 'Pos' }, { label: 'League starters', align: 'right' }, { label: 'Marginal starter', align: 'right' }, { label: 'Top five', align: 'right' }, { label: 'Scarcity index', align: 'right' }], scRows, { compact: true })) +
      k.card('Draft-pick value curve', 'used by the trade ratings', '<div class="gq-pad gv-notes"><p>' + pcTxt + '</p></div>'));
    k.$('gv-ppos').onchange = e => { PV.pos = e.target.value; draw(); };
    k.$('gv-psort').onchange = e => { PV.sort = e.target.value; draw(); };
    k.$('gv-pn').onchange = e => { PV.n = Number(e.target.value); draw(); };
    draw();
  });
}

if (typeof GI.route === 'function') { try { GI.route('value', render); } catch (e) { /* bound */ } }
})(window.GI || (window.GI = {}));
