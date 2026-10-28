/* The Quant Bullpen — transactions and trade ratings (#/mlb/moves) and the team pages' "Moves" card
 * (BP.movesTeam(host, L, S, tid), called by teams.js for MLB clubs).
 *
 * Design System 2.0: stat tiles, v2 tabs and leaderboards; a "Who leaves next" tab from mlb/movement.json (bp-moves.js).
 * Tabs: Trades (every trade of the last twelve months rated for each club: value at the time, realised since, grades,
 * the winner), Clubs (net value over the window, trades won and lost, the counts of every kind of move), Feed (every
 * move: trades, signings, call-ups, options, injured-list moves, releases ...; filters for club, kind and name), Injured
 * list (who is on it now), Method (the validation, retention, prospect base rates, sources and terms).
 * State in the hash: #/mlb/moves?tab=trades&team=<tid>&kind=<kind>.
 *
 * Data: data/mlb/moves.json, data/mlb/trades.json (PAYLOADS.md, "Transactions and trade ratings"). No optional chaining
 * or nullish coalescing (older browsers). */
(function (BP) {
'use strict';

const esc = BP.esc;
const isNum = BP.isNum;
const GRADE_CLS = { A: 'vg-a', B: 'vg-b', C: 'vg-c', D: 'vg-d', F: 'vg-f' };
const TYPE = { mlb: 'MLB projection', prospect: 'prospect model', base: 'base rate' };
const PART = { elbow: 'elbow', shoulder: 'shoulder', lat: 'lat', hamstring: 'hamstring', oblique: 'oblique', back: 'back', knee: 'knee',
  ankle: 'ankle', foot: 'foot', hand: 'hand / wrist', hip: 'hip / groin', calf: 'calf', quad: 'quad', head: 'head / concussion', ribs: 'ribs',
  arm: 'arm', illness: 'illness', other: 'other' };
const M = { tab: 'trades', team: '', kind: '', q: '', sort: 'big' };

function s2(v) { return isNum(v) ? BP.signed(v, 1) : '—'; }
function n1(v) { return isNum(v) ? Number(v).toFixed(1) : '—'; }
function gradeChip(g) { return g ? '<span class="vg ' + (GRADE_CLS[g] || '') + '">' + esc(g) + '</span>' : '—'; }
function plink(pid, name) { return pid ? '<a class="ply-link" href="' + BP.playerHref(pid, { level: 'mlb' }) + '">' + esc(name || BP.playerName(pid)) + '</a>' : esc(name || '—'); }
function tlink(tid) { return tid ? BP.teamLink(tid, { level: 'mlb', abbr: true }) : '<span class="muted-inline">—</span>'; }
function learnTeams(d) { const T = (d && d.teams) || {}; Object.keys(T).forEach(t => { if (!BP.TEAMS[t] && T[t] && T[t].name) BP.TEAMS[t] = Object.assign({}, T[t]); }); }
function hashOf() {
  const q = ['tab=' + encodeURIComponent(M.tab)];
  if (M.team) q.push('team=' + encodeURIComponent(M.team));
  if (M.kind) q.push('kind=' + encodeURIComponent(M.kind));
  return '#/mlb/moves?' + q.join('&');
}
let AFTER = [];
function board(id, spec) { AFTER.push(() => { const n = document.getElementById(id); if (n) QK.leaderboard(n, spec); }); return '<div id="' + esc(id) + '"></div>'; }
const card = (t, s, b, o) => BP.ui.card2(t, s, b, o);
const ENT = (label, key) => ({ key: key || 'name', label: label || 'Player', type: 'entity', sub: 'sub', mark: o => (o.team ? BP.ui.team(o.team, 'mlb') : null), href: o => (o.pid ? BP.playerHref(o.pid, { level: 'mlb' }) : null) });
const nameOf = (pid, n) => { const x = BP.player(pid) || {}; return x.name || n || BP.playerName(pid); };

function movesPage(el, params) {
  const U = BP.ui;
  const qy = params.query || {};
  M.tab = qy.tab || M.tab || 'trades';
  /* round 9: the Method tab is Model > Who moves next now (the validation lives with the model) */
  if (M.tab === 'method') { M.tab = 'trades'; }
  M.team = qy.team !== undefined ? qy.team : M.team;
  M.kind = qy.kind !== undefined ? qy.kind : M.kind;
  el.innerHTML = QK.skeleton('card', 2);
  if (params.level && params.level !== 'mlb') {
    el.innerHTML = QK.sectionHead({ kicker: 'Moves', title: 'Transactions and trades', sub: 'Transactions and trade ratings cover MLB clubs (Triple-A moves appear as call-ups and options of their parent clubs).', actions: '<a class="qk-btn primary" href="#/mlb/moves">MLB moves</a>' });
    return null;
  }
  return Promise.all([BP.load('mlb/moves.json'), BP.load('mlb/trades.json'), BP.moves ? BP.moves.load() : Promise.resolve(null)]).then(res => {
    if (!el.isConnected) return;
    const mv = BP.ok(res[0]) ? res[0] : null, tr = BP.ok(res[1]) ? res[1] : null, mn = res[2];
    learnTeams(mv); learnTeams(tr);
    const win = (tr && tr.window) || (mv && mv.window) || [];
    const head = QK.sectionHead({ kicker: 'Moves · MLB', title: 'Transactions and trades', sub: 'Every trade of the last twelve months rated for both clubs, every move in a feed, who is on the injured list' + (mn ? ', and who is likely to leave next' : '') + '. Window: ' + (win.length ? BP.fmtDate(win[0]) + ' to ' + BP.fmtDate(win[1]) : 'the last twelve months') + '.',
      actions: '<a class="qk-btn" href="' + BP.href('value', 'mlb') + '">Player value</a>' });
    if (!mv && !tr) { el.innerHTML = head + QK.empty('Not built yet', 'The transactions files are not available.'); return; }
    const teams = Object.keys((tr && tr.teams) || (mv && mv.teams) || {}).sort((a, b) => BP.teamName(a).localeCompare(BP.teamName(b)));
    const T = (tr && tr.table) || {};
    const tw = Object.keys(T).sort((a, b) => (T[b].net || 0) - (T[a].net || 0));
    const big = tr ? (tr.trades || []).slice().sort((a, b) => Math.max.apply(null, b.teams.map(c => Math.abs((b.clubs[c] || {}).net || 0))) - Math.max.apply(null, a.teams.map(c => Math.abs((a.clubs[c] || {}).net || 0))))[0] : null;
    const tiles = QK.stats([
      tr ? { label: 'Trades rated', value: BP.int((tr.trades || []).length), sub: 'the last twelve months' } : null,
      tw.length ? { label: 'Best trader', value: BP.teamAbbr(tw[0]) + ' ' + s2(T[tw[0]].net), signal: true, sub: 'expected WAR in minus out, at the time', href: BP.teamHref(tw[0], 'mlb') } : null,
      tw.length ? { label: 'Gave the most away', value: BP.teamAbbr(tw[tw.length - 1]) + ' ' + s2(T[tw[tw.length - 1]].net), sub: 'expected WAR in minus out', href: BP.teamHref(tw[tw.length - 1], 'mlb') } : null,
      mv ? { label: 'On the injured list', value: BP.int((mv.il_now || []).filter(r => !(r[5] > 400)).length), sub: 'players right now' } : null,
      big && big.winner ? { label: 'Most lopsided trade', value: BP.teamAbbr(big.winner) + ' ' + s2((big.clubs[big.winner] || {}).net), sub: BP.fmtDate(big.date) } : null
    ]);
    const tabs = [['trades', 'Trades'], ['clubs', 'Clubs']].concat(mn ? [['next', 'Who leaves next']] : []).concat([['feed', 'Feed'], ['il', 'Injured list']]);
    el.innerHTML = head + '<div class="bp-kpis">' + tiles + '</div>' +
      '<nav class="qk-tabs bp-tabs2" id="mv-tab" aria-label="Moves views">' + tabs.map(t => '<a class="qk-tab" href="javascript:void(0)" data-k="' + t[0] + '" aria-selected="' + (t[0] === M.tab) + '">' + esc(t[1]) + '</a>').join('') + '</nav>' +
      '<section class="qk-card"><div class="qk-card-body"><div class="bp-ctl"><label>Club<select id="mv-team"><option value="">All</option>' + teams.map(t => '<option value="' + esc(t) + '"' + (t === M.team ? ' selected' : '') + '>' + esc(BP.teamName(t)) + '</option>').join('') + '</select></label>' +
      '<label id="mv-kind-w">Kind<select id="mv-kind"><option value="">All</option>' + Object.keys((mv && mv.kinds) || {}).map(k => '<option value="' + esc(k) + '"' + (k === M.kind ? ' selected' : '') + '>' + esc(mv.kinds[k]) + '</option>').join('') + '</select></label>' +
      '<label id="mv-q-w">Find<input id="mv-q" type="search" placeholder="player…" value="' + esc(M.q) + '"></label><span id="mv-sort-w"></span></div></div></section><div id="mv-body" style="margin-top:var(--sp-4)"></div>' +
      '<p class="qk-sub bp-moved">How trades are rated, and how well the ratings have held up: <a class="qk-link" href="#/who-moves-next">Model › Who moves next</a>.</p>';
    const $ = id => document.getElementById(id);
    const draw = () => {
      $('mv-kind-w').style.display = M.tab === 'feed' ? '' : 'none';
      $('mv-q-w').style.display = (M.tab === 'feed' || M.tab === 'trades' || M.tab === 'next') ? '' : 'none';
      $('mv-sort-w').innerHTML = M.tab === 'trades' ? U.seg('mv-sort', 'Order', [['big', 'Biggest first'], ['new', 'Newest first']], M.sort) : '';
      if ($('mv-sort')) QK.seg($('mv-sort'), k => { M.sort = k; draw(); });
      const body = $('mv-body');
      AFTER = [];
      if (M.tab === 'trades') body.innerHTML = tr ? tradesHTML(tr) : QK.empty('Not built yet', 'The trade ratings are not available.');
      else if (M.tab === 'clubs') body.innerHTML = clubsHTML(tr, mv);
      else if (M.tab === 'next') body.innerHTML = nextHTML(mn);
      else if (M.tab === 'feed') body.innerHTML = mv ? feedHTML(mv) : QK.empty('Not built yet', 'The transactions are not available.');
      else if (M.tab === 'il') body.innerHTML = mv ? ilHTML(mv) : '';
      AFTER.forEach(f => f());
      BP.sortable(body);
    };
    $('mv-tab').querySelectorAll('a[data-k]').forEach(a => a.addEventListener('click', ev => {
      ev.preventDefault();
      $('mv-tab').querySelectorAll('a').forEach(x => x.setAttribute('aria-selected', x === a ? 'true' : 'false'));
      M.tab = a.getAttribute('data-k'); history.replaceState(null, '', hashOf()); draw();
    }));
    $('mv-team').onchange = e => { M.team = e.target.value; history.replaceState(null, '', hashOf()); draw(); };
    $('mv-kind').onchange = e => { M.kind = e.target.value; history.replaceState(null, '', hashOf()); draw(); };
    let timer = null;
    $('mv-q').oninput = e => { M.q = e.target.value; clearTimeout(timer); timer = setTimeout(draw, 200); };
    draw();
    BP.setMeta(tr && tr.updated_at ? 'Trades ' + esc(BP.fmtStamp(tr.updated_at)) : '');
  });
}

// ── trades ──────────────────────────────────────────────────────────────────

function tradesHTML(tr) {
  const F = {};
  (tr.piece_fields || []).forEach((f, i) => { F[f] = i; });
  const q = M.q.trim().toLowerCase();
  const list = (tr.trades || []).filter(t => (!M.team || t.teams.indexOf(M.team) >= 0) &&
    (!q || t.pieces.some(p => String(p[F.name] || '').toLowerCase().indexOf(q) >= 0)));
  if (!list.length) return QK.empty('No trade matches', 'Widen the filters.');
  const size = t => Math.max.apply(null, t.teams.map(c => Math.abs((t.clubs[c] || {}).in || 0) + Math.abs((t.clubs[c] || {}).out || 0)));
  if (M.sort === 'big') list.sort((a, b) => size(b) - size(a));
  else list.sort((a, b) => String(b.date).localeCompare(String(a.date)));
  const cards = list.slice(0, 60).map((t, i) => {
    const clubs = t.teams.map(c => {
      const x = t.clubs[c] || {};
      return '<div class="bp-trd-club' + (t.winner === c ? ' won' : '') + '" style="--tc:' + esc(BP.ui.tcol(c)) + '">' + BP.ui.teamEnt(c, 'mlb') + ((x.extras || []).length ? '<span class="bp-mv-why">+ ' + esc(x.extras.join(', ')) + '</span>' : '') +
        '<div class="bp-trd-n">' + gradeChip(x.grade) + '<b data-tip="Value in minus value out, at the time (expected WAR for the club, five seasons, discounted)">' + s2(x.net) + '</b><span class="qk-muted">in ' + n1(x.in) + ' · out ' + n1(x.out) + '</span></div>' +
        '<div class="bp-mv-why">Realised since: ' + gradeChip(x.r_grade) + ' net ' + s2(x.r_net) + ' (in ' + n1(x.r_in) + ', out ' + n1(x.r_out) + ')</div></div>';
    }).join('');
    const verdict = t.winner ? BP.teamShort(t.winner) + ' won it at the time' : 'about even at the time';
    const rv = t.r_winner ? '; ' + BP.teamShort(t.r_winner) + ' ahead on what has happened since' : '; even on what has happened since';
    const names = t.pieces.map(p => nameOf(p[F.pid], p[F.name])).slice(0, 4);
    const sum = '<summary class="bp-trd-sum"><span class="d">' + esc(BP.fmtDate(t.date, { year: false })) + '</span><span class="c">' + t.teams.map(c => esc(BP.teamAbbr(c)) + ' ' + gradeChip((t.clubs[c] || {}).grade)).join(' <span class="qk-muted">·</span> ') + '</span>' +
      '<span class="w">' + esc(names.join(', ') + (t.pieces.length > 4 ? ' and ' + (t.pieces.length - 4) + ' more' : '')) + '</span><span class="v">' + esc(verdict) + '</span></summary>';
    return '<details class="bp-trd"' + (i < 3 ? ' open' : '') + '>' + sum + card(BP.fmtDate(t.date) + ' · ' + t.teams.map(c => BP.teamAbbr(c)).join(' – '), esc(verdict + rv), '<div class="bp-trd-clubs">' + clubs + '</div>' +
      board('mv-tp' + i, { dense: true, columns: [ENT(), { key: 'move', label: 'Move', sort: false }, { key: 'age', label: 'Age', num: true, fmt: v => n1(v) },
        { key: 'svc', label: 'MLB yrs', num: true, tip: 'Seasons since MLB debut (stands in for club control)' }, { key: 'typ', label: 'Valued by', sort: false, fmt: v => '<span class="qk-muted">' + esc(v) + '</span>' },
        { key: 'rest', label: 'Rest', num: true, fmt: v => s2(v), tip: 'Expected WAR for the club over the rest of the season (in-season trades)' },
        { key: 'next', label: 'Next', num: true, fmt: v => s2(v), tip: 'Expected WAR next season (if the player plays; before the chance of staying)' },
        { key: 'value', label: 'Value', type: 'bar', fmt: v => s2(v), tip: 'Expected WAR for the club over five seasons, each weighted by the chance the player is still there, discounted 8% a year' },
        { key: 'real', label: 'Realised', num: true, fmt: v => s2(v), tip: 'WAR produced for the club since the trade' }],
        rows: t.pieces.map(p => ({ pid: p[F.pid], name: nameOf(p[F.pid], p[F.name]), team: p[F.to], sub: p[F.detail] || '', move: BP.teamAbbr(p[F.from]) + ' → ' + BP.teamAbbr(p[F.to]), age: p[F.age], svc: p[F.service] || '—',
          typ: TYPE[p[F.type]] || p[F.type] || '', rest: p[F.rest], next: p[F.next], value: p[F.value], real: p[F.realised] })) }), { flush: false }) + '</details>';
  });
  return '<p class="bp-note">' + list.length + ' trades' + (list.length > 60 ? ', the first 60 shown' : '') + '; the first three open, a click opens any other. ' + esc((tr.notes || []).join(' ')) + '</p><div class="bp-stack bp-trds">' + cards.join('') + '</div>';
}

function clubsHTML(tr, mv) {
  const T = (tr && tr.table) || {};
  const L = (mv && mv.ledger) || {};
  const ids = Object.keys(T).length ? Object.keys(T) : Object.keys(L);
  const rows = ids.filter(t => !M.team || t === M.team).map(t => {
    const x = T[t] || {}, l = L[t] || {};
    return { tid: t, name: BP.teamShort(t), n: x.n, net: x.net, inn: x.in, out: x.out, wl: BP.int(x.won) + '–' + BP.int(x.lost), won: x.won, rnet: x.r_net, io: BP.int(l.trade_in || 0) + ' / ' + BP.int(l.trade_out || 0),
      sign: l.signing || 0, up: (l.recall || 0) + (l.selected || 0), opt: l.option || 0, il: l.il_place || 0, rel: (l.dfa || 0) + (l.release || 0), claim: l.claim || 0 };
  }).sort((a, b) => (b.net || 0) - (a.net || 0));
  const top = rows.filter(r => isNum(r.net));
  return '<div class="qk-grid"><div class="qk-span-5">' + card('Net value from trades', 'Expected WAR in minus out at the time, five seasons, retention-weighted and discounted', top.length ? BP.ui.chart('mv-clubs', Math.max(300, 18 * top.length + 60), 'Net trade value by club') : QK.empty('No trades')) + '</div>' +
    '<div class="qk-span-7">' + card('Winners and losers', 'Every club\'s trades summed (a winner needs a net of 0.75 wins), the net realised since, and the counts of its moves', board('mv-clubs-t', { dense: true, rank: true, maxHeight: 640, rowHref: r => BP.teamHref(r.tid, 'mlb'), columns: [
      { key: 'name', label: 'Club', type: 'entity', mark: r => BP.ui.team(r.tid, 'mlb'), href: r => BP.teamHref(r.tid, 'mlb') }, { key: 'n', label: 'Trades', num: true, fmt: v => BP.int(v) },
      { key: 'net', label: 'Net', type: 'bar', fmt: v => s2(v), tip: 'Value in minus value out at the time' }, { key: 'won', label: 'Won–lost', num: true, fmt: (v, r) => r.wl },
      { key: 'rnet', label: 'Realised net', num: true, fmt: v => s2(v) }, { key: 'io', label: 'Players in / out', num: true, sort: false }, { key: 'sign', label: 'Signings', num: true },
      { key: 'up', label: 'Call-ups', num: true, tip: 'Recalls and contracts selected' }, { key: 'opt', label: 'Options', num: true }, { key: 'il', label: 'IL placements', num: true },
      { key: 'rel', label: 'DFA / released', num: true }, { key: 'claim', label: 'Claims', num: true }], rows: rows }), { flush: true }) + '</div></div>' +
    (top.length ? chartAfter(top) : '');
}
function chartAfter(top) {
  AFTER.push(() => { if (document.getElementById('mv-clubs')) QKC.bar('#mv-clubs', { cats: top.map(r => BP.teamAbbr(r.tid)), series: [{ name: 'Net', data: top.map(r => r.net) }], horizontal: true, diverging: true, labels: true, fmt: v => s2(v),
    hrefs: top.map(r => BP.teamHref(r.tid, 'mlb')), labelWidth: 44, valName: 'Expected WAR in minus out', catName: 'Club', label: 'Net trade value' }); });
  return '';
}

/* Who leaves next: every rostered player's chance of leaving by the next horizon (bp-moves.js, mlb/movement.json). */
function nextHTML(m) {
  if (!m || !BP.moves) return QK.empty('Not published', 'The movement model is not available.');
  const d = m.d, F = m.F;
  if (!d.published || d.published.next === false) return QK.empty('Not published', (d.reasons || {}).next || 'The movement model did not pass its test.');
  const q = M.q.trim().toLowerCase();
  const rows = (d.players || []).filter(r => (!M.team || String(r[F.team]) === M.team) && (!q || String(nameOf(r[F.pid], r[F.name])).toLowerCase().indexOf(q) >= 0))
    .sort((a, b) => (b[F.p_next] || 0) - (a[F.p_next] || 0)).slice(0, 300);
  const col = BP.moves.rosterColumn(m, 'Chance of leaving');
  return card('Who leaves next', 'The chance each rostered player is not with the club by ' + esc((d.horizons || {}).next) + ', split by how; ranked from the most likely' + (rows.length === 300 ? ' (the first 300)' : ''),
    col.legend + (rows.length ? board('mv-next', { dense: true, rank: true, maxHeight: 680, columns: [ENT(), { key: 'age', label: 'Age', num: true, fmt: v => n1(v) }, { key: 'value', label: (d.unit || 'WAR'), num: true, fmt: v => s2(v), tip: 'Value, the last two seasons blended 3:2' }, col.col],
      rows: rows.map(r => ({ pid: r[F.pid], name: nameOf(r[F.pid], r[F.name]), team: r[F.team], sub: (r[F.pos] || '') + ' · ' + BP.teamAbbr(r[F.team]), age: r[F.age], value: r[F.value], _mv: r, p_move: r[F.p_next] })) }) : QK.empty('Nobody here')),
    { foot: '<span class="bp-fn">' + esc((d.notes || []).slice(0, 2).join(' ')) + '</span><a href="#/who-moves-next">How →</a>' });
}

function feedHTML(mv) {
  const F = {};
  (mv.fields || []).forEach((f, i) => { F[f] = i; });
  const N = mv.names || {};
  const q = M.q.trim().toLowerCase();
  const list = (mv.rows || []).filter(r => (!M.team || r[F.from] === M.team || r[F.to] === M.team) && (!M.kind || r[F.kind] === M.kind) &&
    (!q || String(N[r[F.pid]] || '').toLowerCase().indexOf(q) >= 0));
  return card('Feed', list.length + ' moves' + (list.length > 600 ? ' (the latest 600 shown)' : ''), list.length ? board('mv-feed', { dense: true, maxHeight: 700, columns: [
    { key: 'date', label: 'Date', fmt: v => esc(BP.fmtDate(v)) }, { key: 'kind', label: 'Move', fmt: (v, o) => '<span class="mv-k mv-' + esc(v) + '">' + esc(o.kl) + '</span>' }, ENT(),
    { key: 'from', label: 'From', fmt: v => (v ? esc(BP.teamAbbr(v)) : '') }, { key: 'to', label: 'To', fmt: v => (v ? esc(BP.teamAbbr(v)) : '') }, { key: 'detail', label: 'Detail', sort: false, fmt: v => '<span class="qk-muted">' + esc(v || '') + '</span>' }],
    rows: list.slice(0, 600).map(r => ({ date: r[F.date], kind: r[F.kind], kl: (mv.kinds || {})[r[F.kind]] || r[F.kind], pid: r[F.pid], name: nameOf(r[F.pid], N[r[F.pid]]), team: r[F.to] || r[F.from], sub: '', from: r[F.from], to: r[F.to], detail: r[F.detail] })) }) : QK.empty('Nothing here'),
    { flush: true, foot: '<span class="bp-fn">' + esc((mv.notes || []).join(' ')) + '</span>' });
}

function ilHTML(mv) {
  const F = {};
  (mv.il_fields || []).forEach((f, i) => { F[f] = i; });
  const N = mv.names || {};
  /* a placement open for more than 400 days lost its activation (older payloads; the builder drops them since round 9) */
  const list = (mv.il_now || []).filter(r => (!M.team || r[F.club] === M.team) && !(r[F.days] > 400));
  const parts = {};
  list.forEach(r => { const p = PART[r[F.part]] || r[F.part] || 'other'; parts[p] = (parts[p] || 0) + 1; });
  const pk = Object.keys(parts).sort((a, b) => parts[b] - parts[a]);
  AFTER.push(() => warLost(mv));
  return '<section class="qk-section" id="mv-lost"></section><div class="qk-grid"><div class="qk-span-4">' + card('Where it hurts', 'Players on the list now, by body part', pk.length ? BP.ui.chart('mv-parts', Math.max(240, 22 * pk.length + 60), 'Injured list by body part') : QK.empty('Nobody')) + '</div>' +
    '<div class="qk-span-8">' + card('On the injured list now', list.length + ' players · placements not yet followed by an activation, release or trade', list.length ? board('mv-il', { dense: true, maxHeight: 640, sort: { key: 'days', dir: 'desc' }, columns: [ENT(),
      { key: 'list', label: 'List', num: true, fmt: v => v + '-day' }, { key: 'start', label: 'Since', fmt: v => esc(BP.fmtDate(v)) }, { key: 'part', label: 'Body part' }, { key: 'days', label: 'Days', type: 'bar', fmt: v => BP.int(v) }],
      rows: list.map(r => ({ pid: r[F.pid], name: nameOf(r[F.pid], N[r[F.pid]]), team: r[F.club], sub: BP.teamAbbr(r[F.club]), list: r[F.list], start: r[F.start], part: PART[r[F.part]] || r[F.part] || '—', days: r[F.days] })) }) : QK.empty('Nobody'), { flush: true }) + '</div></div>' +
    (pk.length ? partsAfter(pk, parts) : '');
}
/* WAR lost to the injured list, by club (round 9, Phase 4): every stint of the regular season rebuilt from the feed
   (a placement to the next activation, else the season's end), each day valued at the player's projected full-season WAR
   (value.json: "e1" from the five-season projections, else "proj") spread over the regular season's 186 days. What a
   healthy player is worth to the club, not what the stand-in cost. */
const SEASON_DAYS = 186;
function warLost(mv) {
  const host = document.getElementById('mv-lost');
  if (!host) return;
  const S = BP.currentSeason('mlb');
  BP.loadYear('value.json', 'mlb', S).then(v => {
    if (!host.isConnected || !BP.ok(v) || !Array.isArray(v.rows)) return;
    const VF = {}; (v.fields || []).forEach((f, i) => { VF[f] = i; });
    const worth = {};
    v.rows.forEach(r => { const x = VF.e1 !== undefined && isNum(r[VF.e1]) ? r[VF.e1] : r[VF.proj]; if (isNum(x) && x > 0) worth[String(r[VF.pid])] = x; });
    const F = {}; (mv.fields || []).forEach((f, i) => { F[f] = i; });
    const N = mv.names || {};
    const lo = S + '-03-20', hi = S + '-09-30';
    const rows = (mv.rows || []).filter(r => /^il_(place|activate)$/.test(r[F.kind])).sort((a, b) => String(a[F.date]).localeCompare(String(b[F.date])));
    const open = {}, stints = [];
    rows.forEach(r => {
      const pid = String(r[F.pid]), d = String(r[F.date]).slice(0, 10), club = r[F.to] || r[F.from];
      if (r[F.kind] === 'il_place') { if (!open[pid]) open[pid] = { pid: pid, club: club, from: d, part: String(r[F.detail] || '') }; }
      else if (open[pid]) { stints.push(Object.assign(open[pid], { to: d })); delete open[pid]; }
    });
    Object.keys(open).forEach(pid => stints.push(Object.assign(open[pid], { to: hi })));
    const day = x => Date.parse(x + 'T12:00:00Z');
    const club = {}, worst = [];
    stints.forEach(st => {
      const a = st.from > lo ? st.from : lo, b = st.to < hi ? st.to : hi;
      if (b <= a || !worth[st.pid] || !st.club) return;
      const days = Math.round((day(b) - day(a)) / 864e5);
      const lost = worth[st.pid] * days / SEASON_DAYS;
      const c = club[st.club] = club[st.club] || { war: 0, days: 0, n: 0 };
      c.war += lost; c.days += days; c.n += 1;
      worst.push({ pid: st.pid, club: st.club, days: days, lost: lost, from: st.from, part: st.part.replace(/^\d+-day\s*[^\w]*\s*/, '') });
    });
    const ids = Object.keys(club).filter(t => !M.team || t === M.team).sort((a, b) => club[b].war - club[a].war);
    if (!ids.length) return;
    const top = worst.filter(x => !M.team || x.club === M.team).sort((a, b) => b.lost - a.lost).slice(0, 12);
    const tot = ids.reduce((a, t) => a + club[t].war, 0);
    host.innerHTML = QK.sectionHead({ kicker: 'Injury impact', title: 'The wins the injured list took', sub: 'Every stint on the injured list this regular season, each day valued at what the player is worth over a healthy season by our projections: the WAR each club lost to injuries.' }) +
      '<div class="bp-kpis">' + QK.stats([
        { label: 'Hit hardest', value: BP.teamAbbr(ids[0]) + ' ' + BP.ui.signed(-club[ids[0]].war, 1), signal: true, sub: 'WAR lost, ' + BP.int(club[ids[0]].n) + ' stints, ' + BP.int(club[ids[0]].days) + ' player-days', href: BP.teamHref(ids[0], 'mlb') },
        { label: 'Most fortunate', value: BP.teamAbbr(ids[ids.length - 1]) + ' ' + BP.ui.signed(-club[ids[ids.length - 1]].war, 1), sub: 'WAR lost', href: BP.teamHref(ids[ids.length - 1], 'mlb') },
        { label: 'Across the majors', value: BP.num(tot, 0), sub: 'WAR lost to the injured list' },
        top[0] ? { label: 'Costliest absence', value: BP.num(top[0].lost, 1), sub: nameOf(top[0].pid, N[top[0].pid]) + ' (' + BP.teamAbbr(top[0].club) + '), ' + top[0].days + ' days', href: BP.playerHref(top[0].pid, { level: 'mlb' }) } : null
      ].filter(Boolean)) + '</div>' +
      '<div class="qk-grid"><div class="qk-span-5">' + card('WAR lost by club', 'Projected WAR of the days spent on the injured list', BP.ui.chart('mv-lost-c', Math.max(300, 18 * ids.length + 60), 'WAR lost to the injured list by club')) + '</div>' +
      '<div class="qk-span-7">' + card('The costliest absences', 'Stints this regular season, by the WAR they cost', '<div id="mv-lost-t"></div>', { flush: true }) + '</div></div>';
    QK.leaderboard(document.getElementById('mv-lost-t'), { dense: true, rank: true, columns: [ENT(),
        { key: 'from', label: 'From', fmt: x => esc(BP.fmtDate(x, { year: false })) }, { key: 'days', label: 'Days', num: true }, { key: 'part', label: 'Injury', sort: false, fmt: x => '<span class="qk-muted">' + esc(x) + '</span>' },
        { key: 'lost', label: 'WAR lost', type: 'bar', fmt: x => BP.num(x, 1) }],
      rows: top.map(x => ({ pid: x.pid, name: nameOf(x.pid, N[x.pid]), team: x.club, sub: BP.teamAbbr(x.club), from: x.from, days: x.days, part: x.part, lost: x.lost })) });
    QKC.bar('#mv-lost-c', { cats: ids.map(t => BP.teamAbbr(t)), series: [{ name: 'WAR lost', data: ids.map(t => club[t].war) }], colors: ids.map(t => QK.color.ensure(BP.ui.raw(t) || '#7d93ff', '#14171d', 3)),
      horizontal: true, labels: true, fmt: x => BP.num(x, 1), labelWidth: 44, hrefs: ids.map(t => BP.teamHref(t, 'mlb')), valName: 'WAR lost to the injured list', catName: 'Club', label: 'WAR lost to the injured list by club' });
    BP.sortable(host);
  });
}
function partsAfter(pk, parts) {
  AFTER.push(() => { if (document.getElementById('mv-parts')) QKC.bar('#mv-parts', { cats: pk, series: [{ name: 'Players', data: pk.map(p => parts[p]), color: 'model' }], horizontal: true, labels: true, fmt: v => String(v), labelWidth: 110, valName: 'Players on the list', catName: 'Body part', label: 'Injured list by body part' }); });
  return '';
}

function vRow(label, x) {
  if (!x || !isNum(x.n)) return null;
  return [label, { v: x.n, html: BP.int(x.n), align: 'right' }, { v: x.r_model, html: BP.num(x.r_model, 2), align: 'right' }, { v: x.r_naive, html: BP.num(x.r_naive, 2), align: 'right' },
    { v: x.spearman_model, html: BP.num(x.spearman_model, 2), align: 'right' }, { v: x.spearman_naive, html: BP.num(x.spearman_naive, 2), align: 'right' },
    { v: x.mae_model, html: BP.num(x.mae_model, 2), align: 'right' }, { v: x.mae_naive, html: BP.num(x.mae_naive, 2), align: 'right' }, { v: x.slope, html: BP.num(x.slope, 2), align: 'right' }];
}

function methodHTML(tr, mv) {
  let h = '';
  if (tr && tr.validation) {
    const v = tr.validation;
    const rows = [vRow('Players with an MLB projection', v.pieces), vRow('Each trade\'s net for its first club', v.nets)].filter(Boolean);
    h += card('Does the value at the time predict what happened?', 'Trades of ' + esc(v.span || '') + ': the expectation over the rest of the trade\'s season and the next one against the WAR realised for the club over the same span. Naive: the player\'s last season\'s WAR rate over the same playing time.',
      BP.tableHTML(['', { label: 'n', align: 'right' }, { label: 'r (model)', align: 'right' }, { label: 'r (naive)', align: 'right' }, { label: 'Rank r (model)', align: 'right' },
        { label: 'Rank r (naive)', align: 'right' }, { label: 'MAE (model)', align: 'right' }, { label: 'MAE (naive)', align: 'right' }, { label: 'Slope', align: 'right', title: 'Realised on expected, through the origin' }], rows, { compact: true }), { flush: true });
  }
  if (tr && tr.retention && tr.retention.by) {
    const by = tr.retention.by, ns = tr.retention.n || {};
    const keys = Object.keys(by).filter(k => k.indexOf('none') < 0 && k.indexOf('any') < 0).sort();
    const rows = keys.map(k => { const p = k.split('|'); return [esc(p[0]) + ' MLB seasons, ' + (p[1] === 'in' ? 'in-season trade' : 'between seasons')].concat(by[k].map((x, i) => ({ v: x, html: isNum(x) ? BP.pct(x, 0) + ' <span class="muted-inline">' + BP.int((ns[k] || [])[i]) + '</span>' : '—', align: 'right' }))); });
    h += card('Retention: the chance a traded player is still with the club', 'Of traded players who played in the majors in a later season, the share who did so mainly for the club that acquired them (2015 on). It stands in for contracts and club control. Columns: the first to fifth season after an in-season trade; the first to fifth season (the trade\'s own first) for one between seasons. Small numbers: players.',
      BP.tableHTML(['Group', { label: '1', align: 'right' }, { label: '2', align: 'right' }, { label: '3', align: 'right' }, { label: '4', align: 'right' }, { label: '5', align: 'right' }], rows, { compact: true }), { flush: true });
  }
  if (tr && tr.prospect_model) {
    const pm = tr.prospect_model;
    const rows = ['H', 'P'].filter(k => pm[k] && pm[k].validation).map(k => { const v = pm[k].validation; return [k === 'H' ? 'Hitters' : 'Pitchers', { v: v.n, html: BP.int(v.n), align: 'right' },
      { v: v.spearman_model, html: BP.num(v.spearman_model, 2), align: 'right' }, { v: v.spearman_level_mean, html: BP.num(v.spearman_level_mean, 2), align: 'right' },
      { v: v.mae_model, html: BP.num(v.mae_model, 2), align: 'right' }, { v: v.mae_level_mean, html: BP.num(v.mae_level_mean, 2), align: 'right' },
      { v: v.top5pct_mean_actual, html: BP.num(v.top5pct_mean_pred, 2) + ' → ' + BP.num(v.top5pct_mean_actual, 2), align: 'right' }, { v: v.all_mean_actual, html: BP.num(v.all_mean_actual, 2), align: 'right' }]; });
    h += card('Prospects: expected MLB WAR from minor-league lines', 'Four seasons after a minor-league season, discounted; fitted on the cohorts to 2019 and scored on 2021–22 (no minor-league season in 2020), against each level\'s mean. Stat lines only, no scouting grades, so the very best prospects are under-rated.',
      BP.tableHTML(['', { label: 'n', align: 'right' }, { label: 'Rank r', align: 'right' }, { label: 'Rank r (level mean)', align: 'right' }, { label: 'MAE', align: 'right' }, { label: 'MAE (level mean)', align: 'right' },
        { label: 'Top 5%: expected → actual', align: 'right' }, { label: 'Mean actual', align: 'right' }], rows, { compact: true }), { flush: true });
  }
  if (tr && tr.base_rates) {
    const br = tr.base_rates;
    h += card('Players with no record', 'Traded players with no MLB record and no minor-league line in the two seasons before (amateur signees, players hurt all season): the average of what traded players of the same age band with no MLB record went on to produce (2015–22 trades).',
      BP.tableHTML(['Age band', { label: 'Value (4 seasons, disc.)', align: 'right' }, { label: 'Share above 0.5 WAR', align: 'right' }, { label: 'n', align: 'right' }],
        Object.keys(br).map(k => [esc(k), { v: br[k].value, html: BP.num(br[k].value, 2), align: 'right' }, { v: br[k].share_positive, html: BP.pct(br[k].share_positive, 0), align: 'right' }, { v: br[k].n, html: BP.int(br[k].n), align: 'right' }]), { compact: true }), { flush: true });
  }
  h += card('Sources and terms', '', '<p class="bp-note" style="margin:0">' + esc((tr && tr.source) || (mv && mv.source) || '') + '</p>');
  return '<div class="bp-stack">' + h + '</div>';
}

// ── the team page's card ────────────────────────────────────────────────────

function movesTeam(host, L, S, tid) {
  if (!host) return;
  if (L !== 'mlb' || Number(S) !== BP.currentSeason('mlb')) { host.innerHTML = ''; return; }
  Promise.all([BP.load('mlb/moves.json'), BP.load('mlb/trades.json')]).then(res => {
    if (!host.isConnected) return;
    const mv = BP.ok(res[0]) ? res[0] : null, tr = BP.ok(res[1]) ? res[1] : null;
    if (!mv && !tr) { host.innerHTML = ''; return; }
    let h = '';
    if (tr) {
      const x = (tr.table || {})[tid] || {};
      const mine = (tr.trades || []).filter(t => t.teams.indexOf(tid) >= 0).slice(0, 8);
      const F = {};
      (tr.piece_fields || []).forEach((f, i) => { F[f] = i; });
      const rows = mine.map(t => {
        const c = t.clubs[tid] || {};
        const ins = t.pieces.filter(p => p[F.to] === tid).map(p => esc(p[F.name])).join(', ') || '—';
        const outs = t.pieces.filter(p => p[F.from] === tid).map(p => esc(p[F.name])).join(', ') || '—';
        return [{ v: t.date, html: esc(BP.fmtDate(t.date)) }, { v: ins, html: '<span class="val-why">in: ' + ins + '<br>out: ' + outs + '</span>' },
          { v: c.grade, html: gradeChip(c.grade) }, { v: c.net, html: s2(c.net), align: 'right' }, { v: c.r_net, html: s2(c.r_net), align: 'right' }];
      });
      h += '<div class="pad trd-text">Last twelve months: ' + BP.int(x.n) + ' trades, net ' + s2(x.net) + ' expected WAR at the time (' + BP.int(x.won) + ' won, ' + BP.int(x.lost) + ' lost), ' + s2(x.r_net) + ' realised since.</div>' +
        (rows.length ? BP.tableHTML([{ label: 'Date' }, { label: 'Players' }, { label: 'Grade' }, { label: 'Net', align: 'right' }, { label: 'Realised', align: 'right' }], rows, { compact: true }) : '');
    }
    if (mv) {
      const F = {};
      (mv.fields || []).forEach((f, i) => { F[f] = i; });
      const N = mv.names || {};
      const recent = (mv.rows || []).filter(r => r[F.from] === tid || r[F.to] === tid).slice(0, 10);
      if (recent.length) h += BP.tableHTML([{ label: 'Date' }, { label: 'Move' }, { label: 'Player' }, { label: 'Detail' }], recent.map(r => [{ v: r[F.date], html: esc(BP.fmtDate(r[F.date])) }, { v: (mv.kinds || {})[r[F.kind]] || r[F.kind], html: esc((mv.kinds || {})[r[F.kind]] || r[F.kind]) },
        { v: N[r[F.pid]] || BP.playerName(r[F.pid]), html: plink(r[F.pid], N[r[F.pid]]) }, { v: r[F.detail] || '', html: '<span class="muted-inline">' + esc(r[F.detail] || (r[F.from] === tid && r[F.to] ? 'to ' + BP.teamAbbr(r[F.to]) : r[F.to] === tid && r[F.from] ? 'from ' + BP.teamAbbr(r[F.from]) : '')) + '</span>' }]), { compact: true });
    }
    host.innerHTML = BP.card('Moves', '<a href="#/mlb/moves?tab=trades&team=' + encodeURIComponent(tid) + '">All trades and moves →</a>', h);
    BP.sortable(host);
  });
}

BP.movesTeam = movesTeam;
/* Model > Who moves next (bp-moves.js) shows the trade ratings' validation, retention and prospect model here */
BP.tradeMethod = host => Promise.all([BP.load('mlb/moves.json'), BP.load('mlb/trades.json')]).then(res => {
  if (!host || !host.isConnected) return;
  const mv = BP.ok(res[0]) ? res[0] : null, tr = BP.ok(res[1]) ? res[1] : null;
  if (!mv && !tr) return;
  host.innerHTML = QK.sectionHead({ kicker: 'Trade ratings', title: 'How trades are rated, and how well', sub: 'Each trade valued at the time from what was known that day, then checked against what the players went on to do for their new clubs.' }) + methodHTML(tr, mv);
  BP.sortable(host);
});
if (typeof BP.route === 'function') BP.route('moves', movesPage);
})(window.BP || (window.BP = {}));
