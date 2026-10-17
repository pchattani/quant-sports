/* The Quant Gridiron — transactions and trade ratings (#/transactions).
 *
 * The last twelve months of ESPN's club transaction notes, parsed: every trade rated for each side in the value
 * page's currency (points above replacement, and wins) at the time and now (realised value since, plus what is still
 * projected while the player is on that roster; picks at our draft-pick value curve), the best and worst deals, a
 * winners-and-losers table by club, the feed, and each club's ledger (data/<S>/ledgers/<abbr>.json).
 *
 * Address: #/transactions?tab=trades|table|feed|team&team=<abbr>&type=<type>. Data: data/<S>/transactions.json. */
(function (GI) {
'use strict';

const K = () => GI.fk;
const TABS = [['trades', 'Trade ratings'], ['table', 'Winners & losers'], ['feed', 'Feed'], ['team', 'Team ledger']];
const TYPES = [['', 'All moves'], ['trade', 'Trades'], ['signing', 'Signings'], ['release', 'Releases'], ['claim', 'Waiver claims'], ['extension', 'Extensions']];
const ST = { tab: 'trades', team: '', type: '', q: '' };
let D = null, S = null;

function gradeChip(g) {
  if (!g) return '<span class="muted-inline">—</span>';
  const col = { A: '#3fb950', B: '#7ee787', C: '#8b949e', D: '#f0883e', F: '#f85149' }[g] || '#8b949e';
  return '<span class="gt-grade" style="background:' + col + '">' + g + '</span>';
}
function asset(a) {
  const k = K();
  if (a.kind === 'pick') {
    return '<span class="gx-a">' + (a.conditional ? 'conditional ' : '') + a.year + ' ' + (a.overall ? 'pick ' + a.overall : k.ordinal(a.round) + ' round') + ' <span class="muted-inline">' + k.num(a.at, 1) + '</span></span>';
  }
  if (a.kind === 'considerations') return '<span class="gx-a muted-inline">draft considerations</span>';
  const v = a.valued ? (k.num(a.at, 1) + ' → ' + k.num(a.now, 1)) : (a.why || 'not valued');
  return '<span class="gx-a">' + k.esc(a.pos || '') + ' ' + (a.pid ? k.playerLink(a.pid, a.name, S) : k.esc(a.name || '')) +
    ' <span class="muted-inline" title="' + (a.valued ? 'value at the time → now (realised ' + k.num(a.real, 1) + ' in ' + (a.games || 0) + ' games)' : '') + '">' + k.esc(v) + '</span>' +
    (a.valued && a.on_roster === false ? ' <span class="gq-tag">gone</span>' : '') + '</span>';
}
function tradeCard(t) {
  const k = K();
  const sides = (t.sides || []).map(sd => '<div class="gx-side" style="--tc:' + k.teamColour(sd.team) + '"><div class="gx-side-h">' + k.teamChip(sd.team, S) + ' received ' +
    '<span class="gx-g">' + gradeChip(sd.grade_now) + ' now <span class="muted-inline">(' + (sd.grade_at || '—') + ' at the time)</span></span></div>' +
    '<div class="gx-assets">' + ((sd.gets || []).length ? sd.gets.map(asset).join('') : '<span class="muted-inline">nothing listed</span>') + '</div>' +
    '<div class="gx-net">net ' + k.signed(sd.wins_now, 2) + ' wins now · ' + k.signed(sd.wins_at, 2) + ' at the time · received ' + k.num(sd.in_now, 1) + ' pts</div></div>').join('');
  const w = t.winner === 'even' ? 'even so far' : (t.winner ? K().teamName(t.winner) + ' ahead' : '');
  return '<div class="gx-trade"><div class="gx-th"><span>' + k.esc(k.fmtDate ? k.fmtDate(t.date) : t.date) + '</span><span class="gx-w">' + k.esc(w) + '</span></div><div class="gx-sides">' + sides + '</div>' +
    '<details class="gx-notes"><summary>Club notes</summary>' + (t.notes || []).map(n => '<div>' + k.esc(n) + '</div>').join('') + '</details></div>';
}

function render(el, params, state) {
  const k = K();
  const qy = params.query || {};
  if (qy.tab && TABS.some(x => x[0] === qy.tab)) ST.tab = qy.tab;
  if (qy.team) { ST.team = String(qy.team).toUpperCase(); if (!qy.tab) ST.tab = 'team'; }
  if (qy.type !== undefined) ST.type = String(qy.type);
  el.innerHTML = k.muted('Loading…');
  return k.ready().then(() => {
    S = k.curSeason ? k.curSeason() : k.S(params, state);
    return Promise.all([k.loadY(S, 'transactions.json'), k.loadNames()]);
  }).then(res => {
    if (!k.alive(el)) return;
    D = res[0];
    if (!k.ok(D) || !D.trades) {
      el.innerHTML = k.head('Transactions', String(S)) + k.card('Transactions', '', '<div class="gq-pad">' + k.notBuilt('The transactions', D) + '</div>');
      return;
    }
    let h = k.head('Transactions & trade ratings', 'the last twelve months · ' + k.esc((D.window || []).join(' to ')),
      '<a href="#/value">Player value →</a><a href="#/trade">Trade simulator →</a><a href="#/methodology/trade">How it works →</a>');
    h += '<div class="card"><div class="gq-pad gt-intro"><p>' + k.esc((D.notes || {}).method || '') + '</p><p class="muted-inline">' + k.esc((D.notes || {}).source || '') + ' ' +
      k.esc((D.notes || {}).left_out || '') + ' Defensive values are a floor (box-score credit only), so deals for defenders read worse than they may be; offensive linemen are not valued.</p>' +
      '<div class="gf-tabs">' + k.toggle('gx-tab', TABS, ST.tab) + '</div></div></div><div id="gx-body"></div>';
    el.innerHTML = h;
    k.setMeta('Transactions · ' + S);
    k.wireToggle(el, 'gx-tab', v => { ST.tab = v; draw(); });
    draw();
  });
}

function sync() {
  const q = ['tab=' + ST.tab];
  if (ST.team) q.push('team=' + ST.team);
  if (ST.type) q.push('type=' + ST.type);
  try { history.replaceState(null, '', '#/transactions?' + q.join('&')); } catch (e) { /* ok */ }
}

function teamSelect(id, allLabel) {
  const k = K();
  const teams = (D.table || []).map(r => r.team).sort();
  return '<label>Team <select id="' + id + '"><option value="">' + k.esc(allLabel) + '</option>' + teams.map(t => '<option value="' + t + '"' + (t === ST.team ? ' selected' : '') + '>' + k.esc(k.teamName(t)) + '</option>').join('') + '</select></label>';
}

function draw() {
  const k = K();
  sync();
  const body = k.$('gx-body');
  if (!body) return;
  if (ST.tab === 'trades') {
    const list = (D.trades || []).filter(t => !ST.team || (t.teams || []).indexOf(ST.team) >= 0);
    const best = (D.best || []).map(b => '<div class="gq-mini-r"><span class="gv-nm">' + k.teamChip(b[1], S) + ' from ' + k.esc(b[2] || '?') + ' <span class="muted-inline">' + k.esc(b[0]) + '</span></span><span class="gq-mini-v">' + k.signed(b[3], 2) + ' ' + gradeChip(b[4]) + '</span></div>').join('');
    const worst = (D.worst || []).map(b => '<div class="gq-mini-r"><span class="gv-nm">' + k.teamChip(b[1], S) + ' from ' + k.esc(b[2] || '?') + ' <span class="muted-inline">' + k.esc(b[0]) + '</span></span><span class="gq-mini-v">' + k.signed(b[3], 2) + ' ' + gradeChip(b[4]) + '</span></div>').join('');
    body.innerHTML = '<div class="gq-glance gx-bw"><div class="gq-mini"><div class="gq-mini-h">Best deals (net wins now)</div>' + best + '</div><div class="gq-mini"><div class="gq-mini-h">Worst deals</div>' + worst + '</div></div>' +
      k.card('Every trade', list.length + ' trades · grades on the net in wins: A ≥ +1, B ≥ +0.3, C within 0.3 of even, D ≥ −1, F below', '<div class="gq-pad"><div class="lab-controls gq-controls">' + teamSelect('gx-team', 'All teams') + '</div>' + list.map(tradeCard).join('') + '</div>');
  } else if (ST.tab === 'table') {
    const rows = (D.table || []).map((r, i) => ({ cells: [{ v: i + 1, cls: 'pos-cell' }, { v: r.team, html: k.teamChip(r.team, S) + ' ' + k.esc(k.teamName(r.team)) }, { v: r.trades, html: k.int(r.trades) },
      { v: r.wins_at, html: k.signed(r.wins_at, 2) }, { v: r.wins_now, html: '<strong>' + k.signed(r.wins_now, 2) + '</strong>' }, { v: r.real, html: k.num(r.real, 1) },
      { v: r.signed, html: k.num(r.signed, 0) + ' <span class="muted-inline">(' + r.n_signed + ')</span>' }, { v: r.lost, html: k.num(r.lost, 0) + ' <span class="muted-inline">(' + r.n_lost + ')</span>' }],
    _href: '#/transactions?tab=team&team=' + r.team }));
    body.innerHTML = k.card('Winners and losers', 'net value of every club\'s trades in the window, and the projected value of the players it signed and released', k.table(
      [{ label: '#', sortable: false }, { label: 'Club' }, { label: 'Trades', align: 'right' }, { label: 'Net wins at the time', align: 'right' }, { label: 'Net wins now', align: 'right' },
        { label: 'Realised in', align: 'right', title: 'Points above replacement the players it traded for have produced for it' },
        { label: 'Signed (value)', align: 'right', title: 'Projected multi-season value of players with a value history it signed' }, { label: 'Released (value)', align: 'right' }], rows, { compact: true, sticky: true })) +
      '<div class="pg-note gq-note">Signings and releases use each player\'s projected value now (valuation v2), not a contract figure: we have no contract data we may publish.</div>';
  } else if (ST.tab === 'feed') {
    const q = k.fold(ST.q.trim());
    const list = (D.feed || []).filter(f => (!ST.team || f[1] === ST.team) && (!ST.type || f[2] === ST.type) && (!q || k.fold(f[3]).indexOf(q) >= 0));
    body.innerHTML = k.card('Feed', 'trades, signings, releases, claims and extensions · ' + list.length + ' shown (of ' + k.int(D.n_feed) + ' moves, practice-squad and reserve moves in the team ledgers)',
      '<div class="gq-pad"><div class="lab-controls gq-controls">' + teamSelect('gx-team', 'All teams') + '<label>Type <select id="gx-type">' + TYPES.map(t => '<option value="' + t[0] + '"' + (t[0] === ST.type ? ' selected' : '') + '>' + t[1] + '</option>').join('') + '</select></label>' +
      '<label>Find <input id="gx-q" type="search" placeholder="name or text" autocomplete="off"></label></div>' + feedList(list.slice(0, 300), true) + '</div>');
  } else {
    if (!ST.team) ST.team = ((D.table || [])[0] || {}).team || 'ARI';
    body.innerHTML = k.card('Team ledger', '', '<div class="gq-pad"><div class="lab-controls gq-controls">' + teamSelect('gx-team', 'Choose') + '</div><div id="gx-ledger">' + k.muted('Loading…') + '</div></div>');
    k.loadY(S, 'ledgers/' + ST.team + '.json').then(L => {
      if (!k.ok(L)) { k.set('gx-ledger', k.notBuilt('The ledger', L)); return; }
      const s = L.summary || {};
      k.set('gx-ledger', k.tiles([k.tile('Trades', k.int(s.trades)), k.tile('Net wins now', k.signed(s.wins_now, 2), 'at the time ' + k.signed(s.wins_at, 2)),
        k.tile('Signed', k.num(s.signed, 0), (s.n_signed || 0) + ' valued players'), k.tile('Released', k.num(s.lost, 0), (s.n_lost || 0) + ' valued players')]) +
        ((L.trades || []).length ? '<div class="gt-sub">Trades</div>' + L.trades.map(tradeCard).join('') : '') +
        '<div class="gt-sub">Every move</div>' + feedList((L.feed || []).map(f => [f[0], L.team, f[1], f[2], f[3]]), false));
    });
  }
  body.querySelectorAll('.table-wrap').forEach(t => k.sortable(t));
  const ts = k.$('gx-team');
  if (ts) ts.onchange = e => { ST.team = e.target.value; draw(); };
  const ty = k.$('gx-type');
  if (ty) ty.onchange = e => { ST.type = e.target.value; draw(); };
  const qi = k.$('gx-q');
  if (qi) { qi.value = ST.q; qi.oninput = e => { ST.q = e.target.value; const p = qi.selectionStart; draw(); const n = k.$('gx-q'); if (n) { n.focus(); try { n.setSelectionRange(p, p); } catch (er) { /* ok */ } } }; }
}

function feedList(list, withTeam) {
  const k = K();
  if (!list.length) return k.muted('Nothing in the window.');
  return '<div class="gx-feed">' + list.map(f => {
    const pl = (f[4] || []).filter(p => p[0] && k.isNum(p[3]) && p[3] > 0).map(p => k.playerLink(p[0], p[1], S) + ' <span class="muted-inline">' + k.num(p[3], 0) + '</span>').join(', ');
    return '<div class="gx-f"><span class="gx-fd">' + k.esc(f[0]) + '</span>' + (withTeam ? k.teamChip(f[1], S) : '') + ' <span class="gq-tag">' + k.esc(f[2]) + '</span> <span class="gx-ft">' + k.esc(f[3]) + '</span>' +
      (pl ? '<div class="gx-fv">model value: ' + pl + '</div>' : '') + '</div>';
  }).join('') + '</div>';
}

if (typeof GI.route === 'function') { try { GI.route('transactions', render); } catch (e) { /* bound */ } }
})(window.GI || (window.GI = {}));
