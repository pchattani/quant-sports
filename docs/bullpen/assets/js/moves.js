/* The Quant Bullpen — transactions and trade ratings (#/mlb/moves) and the team pages' "Moves" card
 * (BP.movesTeam(host, L, S, tid), called by teams.js for MLB clubs).
 *
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

function movesPage(el, params) {
  const qy = params.query || {};
  M.tab = qy.tab || M.tab || 'trades';
  M.team = qy.team !== undefined ? qy.team : M.team;
  M.kind = qy.kind !== undefined ? qy.kind : M.kind;
  el.innerHTML = BP.muted('Loading…');
  if (params.level && params.level !== 'mlb') {
    el.innerHTML = BP.pageHead('Moves', 'Transactions and trade ratings') + BP.muted('Transactions and trade ratings cover MLB clubs (Triple-A moves appear as call-ups and options of their parent clubs). <a href="#/mlb/moves">MLB moves →</a>');
    return null;
  }
  return Promise.all([BP.load('mlb/moves.json'), BP.load('mlb/trades.json')]).then(res => {
    if (!el.isConnected) return;
    const mv = BP.ok(res[0]) ? res[0] : null, tr = BP.ok(res[1]) ? res[1] : null;
    learnTeams(mv); learnTeams(tr);
    const win = (tr && tr.window) || (mv && mv.window) || [];
    const head = BP.pageHead('Moves', 'MLB transactions and trade ratings · ' + (win.length ? esc(BP.fmtDate(win[0])) + ' to ' + esc(BP.fmtDate(win[1])) : 'the last twelve months'),
      '<a href="' + BP.href('value', 'mlb') + '">Player value →</a>');
    if (!mv && !tr) { el.innerHTML = head + BP.notBuilt('The transactions files', res[0]); return; }
    const teams = Object.keys((tr && tr.teams) || (mv && mv.teams) || {}).sort((a, b) => BP.teamName(a).localeCompare(BP.teamName(b)));
    const tabs = [{ key: 'trades', label: 'Trades' }, { key: 'clubs', label: 'Clubs' }, { key: 'feed', label: 'Feed' }, { key: 'il', label: 'Injured list' }, { key: 'method', label: 'Method' }];
    el.innerHTML = head + '<div class="card"><div class="val-controls"><span class="tgl" id="mv-tab">' + BP.toggles(tabs, M.tab) + '</span>' +
      '<label>Club <select id="mv-team"><option value="">All</option>' + teams.map(t => '<option value="' + esc(t) + '"' + (t === M.team ? ' selected' : '') + '>' + esc(BP.teamName(t)) + '</option>').join('') + '</select></label>' +
      '<label id="mv-kind-w">Kind <select id="mv-kind"><option value="">All</option>' + Object.keys((mv && mv.kinds) || {}).map(k => '<option value="' + esc(k) + '"' + (k === M.kind ? ' selected' : '') + '>' + esc(mv.kinds[k]) + '</option>').join('') + '</select></label>' +
      '<label id="mv-q-w">Find <input id="mv-q" type="search" placeholder="player…" value="' + esc(M.q) + '"></label></div></div><div id="mv-body"></div>';
    const $ = id => document.getElementById(id);
    const draw = () => {
      $('mv-kind-w').style.display = M.tab === 'feed' ? '' : 'none';
      $('mv-q-w').style.display = (M.tab === 'feed' || M.tab === 'trades') ? '' : 'none';
      const body = $('mv-body');
      if (M.tab === 'trades') {
        body.innerHTML = tr ? tradesHTML(tr) : BP.card('', '', BP.notBuilt('The trade ratings', res[1]));
        if ($('mv-sort')) BP.wireToggles($('mv-sort'), 'data-k', k => { M.sort = k; draw(); });
      }
      else if (M.tab === 'clubs') body.innerHTML = clubsHTML(tr, mv);
      else if (M.tab === 'feed') body.innerHTML = mv ? feedHTML(mv) : BP.card('', '', BP.notBuilt('The transactions', res[0]));
      else if (M.tab === 'il') body.innerHTML = mv ? ilHTML(mv) : '';
      else body.innerHTML = methodHTML(tr, mv);
      BP.sortable(body);
    };
    BP.wireToggles($('mv-tab'), 'data-k', k => { M.tab = k; history.replaceState(null, '', hashOf()); draw(); });
    $('mv-team').onchange = e => { M.team = e.target.value; history.replaceState(null, '', hashOf()); draw(); };
    $('mv-kind').onchange = e => { M.kind = e.target.value; history.replaceState(null, '', hashOf()); draw(); };
    let timer = null;
    $('mv-q').oninput = e => { M.q = e.target.value; clearTimeout(timer); timer = setTimeout(draw, 200); };
    draw();
  });
}

// ── trades ──────────────────────────────────────────────────────────────────

function pieceRows(tr, t, F) {
  return t.pieces.map(p => {
    const typ = p[F.type];
    return [{ v: p[F.name], html: plink(p[F.pid], p[F.name]) + (p[F.detail] ? '<div class="val-why">' + esc(p[F.detail]) + '</div>' : '') },
      { v: BP.teamAbbr(p[F.from]), html: tlink(p[F.from]) + ' → ' + tlink(p[F.to]) },
      { v: p[F.age], html: n1(p[F.age]), align: 'right' }, { v: p[F.service] || '', html: esc(p[F.service] || '—'), align: 'right' },
      { v: typ, html: '<span class="muted-inline">' + esc(TYPE[typ] || typ || '') + '</span>' },
      { v: p[F.rest], html: s2(p[F.rest]), align: 'right' }, { v: p[F.next], html: s2(p[F.next]), align: 'right' },
      { v: p[F.value], html: '<strong>' + s2(p[F.value]) + '</strong>', align: 'right' }, { v: p[F.realised], html: s2(p[F.realised]), align: 'right' }];
  });
}

function tradesHTML(tr) {
  const F = {};
  (tr.piece_fields || []).forEach((f, i) => { F[f] = i; });
  const q = M.q.trim().toLowerCase();
  const list = (tr.trades || []).filter(t => (!M.team || t.teams.indexOf(M.team) >= 0) &&
    (!q || t.pieces.some(p => String(p[F.name] || '').toLowerCase().indexOf(q) >= 0)));
  if (!list.length) return BP.card('Trades', '', BP.muted('No trade matches.'));
  const size = t => Math.max.apply(null, t.teams.map(c => Math.abs((t.clubs[c] || {}).in || 0) + Math.abs((t.clubs[c] || {}).out || 0)));
  if (M.sort === 'big') list.sort((a, b) => size(b) - size(a));
  const cards = list.map(t => {
    const clubs = t.teams.map(c => {
      const x = t.clubs[c] || {};
      const ex = (x.extras || []).length ? ' <span class="muted-inline">+ ' + esc(x.extras.join(', ')) + '</span>' : '';
      return '<div class="trd-club' + (t.winner === c ? ' won' : '') + '">' + BP.teamLink(c, { level: 'mlb' }) + ex +
        '<div class="trd-club-n">' + gradeChip(x.grade) + ' <span title="Value in minus value out, at the time (expected WAR for the club, five seasons, discounted)">net ' + s2(x.net) + '</span>' +
        ' <span class="muted-inline">in ' + n1(x.in) + ' · out ' + n1(x.out) + '</span></div>' +
        '<div class="trd-club-r muted-inline">Realised since: ' + gradeChip(x.r_grade) + ' net ' + s2(x.r_net) + ' (in ' + n1(x.r_in) + ', out ' + n1(x.r_out) + ')</div></div>';
    }).join('');
    const verdict = t.winner ? '<b>' + esc(BP.teamShort(t.winner)) + '</b> won it at the time' : 'about even at the time';
    const rv = t.r_winner ? '; <b>' + esc(BP.teamShort(t.r_winner)) + '</b> ahead on what has happened since' : '; even on what has happened since';
    return '<div class="card trd-rated"><div class="card-header">' + esc(BP.fmtDate(t.date)) + ' <span class="card-sub">' + verdict + rv + '.</span></div>' +
      '<div class="trd-clubs">' + clubs + '</div>' +
      BP.tableHTML([{ label: 'Player' }, { label: 'Move' }, { label: 'Age', align: 'right' }, { label: 'MLB yrs', align: 'right', title: 'Seasons since his MLB debut (stands in for club control)' },
        { label: 'Valued by' }, { label: 'Rest', align: 'right', title: 'Expected WAR for the club over the rest of the season (in-season trades)' },
        { label: 'Next', align: 'right', title: 'Expected WAR next season (if he plays; before the chance he stays)' },
        { label: 'Value', align: 'right', title: 'Expected WAR for the club over five seasons, each weighted by the chance he is still there, discounted 8% a year' },
        { label: 'Realised', align: 'right', title: 'WAR produced for the club since the trade' }], pieceRows(tr, t, F), { compact: true }) + '</div>';
  });
  const bar = '<div class="val-controls"><span class="tgl" id="mv-sort">' + BP.toggles([{ key: 'big', label: 'Biggest first' }, { key: 'new', label: 'Newest first' }], M.sort) + '</span>' +
    '<span class="muted-inline">' + list.length + ' trades</span></div>';
  return bar + cards.join('') + '<div class="npb-note">' + esc((tr.notes || []).join(' ')) + '</div>';
}

function clubsHTML(tr, mv) {
  const T = (tr && tr.table) || {};
  const L = (mv && mv.ledger) || {};
  const ids = Object.keys(T).length ? Object.keys(T) : Object.keys(L);
  const rows = ids.filter(t => !M.team || t === M.team).map(t => {
    const x = T[t] || {}, l = L[t] || {};
    return [{ v: BP.teamName(t), html: BP.teamLink(t, { level: 'mlb' }) }, { v: x.n, html: BP.int(x.n), align: 'right' },
      { v: x.net, html: '<strong>' + s2(x.net) + '</strong>', align: 'right' }, { v: x.in, html: n1(x.in), align: 'right' }, { v: x.out, html: n1(x.out), align: 'right' },
      { v: x.won, html: BP.int(x.won) + '–' + BP.int(x.lost), align: 'right' }, { v: x.r_net, html: s2(x.r_net), align: 'right' },
      { v: (l.trade_in || 0) + (l.trade_out || 0), html: BP.int((l.trade_in || 0)) + ' / ' + BP.int(l.trade_out || 0), align: 'right' },
      { v: l.signing || 0, html: BP.int(l.signing || 0), align: 'right' }, { v: (l.recall || 0) + (l.selected || 0), html: BP.int((l.recall || 0) + (l.selected || 0)), align: 'right' },
      { v: l.option || 0, html: BP.int(l.option || 0), align: 'right' }, { v: l.il_place || 0, html: BP.int(l.il_place || 0), align: 'right' },
      { v: (l.dfa || 0) + (l.release || 0), html: BP.int((l.dfa || 0) + (l.release || 0)), align: 'right' }, { v: l.claim || 0, html: BP.int(l.claim || 0), align: 'right' }];
  }).sort((a, b) => (b[2].v || 0) - (a[2].v || 0));
  return BP.card('Winners and losers', 'Every club\'s trades of the last twelve months summed: expected WAR in and out at the time (five seasons, retention-weighted, discounted), trades won–lost (a winner needs a net of 0.75 wins), the net realised since; and the counts of its moves.',
    BP.tableHTML([{ label: 'Club' }, { label: 'Trades', align: 'right' }, { label: 'Net', align: 'right', title: 'Value in minus value out at the time' }, { label: 'In', align: 'right' }, { label: 'Out', align: 'right' },
      { label: 'Won–lost', align: 'right' }, { label: 'Realised net', align: 'right' }, { label: 'Players in / out', align: 'right' }, { label: 'Signings', align: 'right' },
      { label: 'Call-ups', align: 'right', title: 'Recalls and contracts selected' }, { label: 'Options', align: 'right' }, { label: 'IL placements', align: 'right' },
      { label: 'DFA / released', align: 'right' }, { label: 'Claims', align: 'right' }], rows, { compact: true, sticky: true }));
}

function feedHTML(mv) {
  const F = {};
  (mv.fields || []).forEach((f, i) => { F[f] = i; });
  const N = mv.names || {};
  const q = M.q.trim().toLowerCase();
  const list = (mv.rows || []).filter(r => (!M.team || r[F.from] === M.team || r[F.to] === M.team) && (!M.kind || r[F.kind] === M.kind) &&
    (!q || String(N[r[F.pid]] || '').toLowerCase().indexOf(q) >= 0));
  const rows = list.slice(0, 600).map(r => [{ v: r[F.date], html: esc(BP.fmtDate(r[F.date])) }, { v: r[F.kind], html: '<span class="mv-k mv-' + esc(r[F.kind]) + '">' + esc((mv.kinds || {})[r[F.kind]] || r[F.kind]) + '</span>' },
    { v: N[r[F.pid]] || '', html: plink(r[F.pid], N[r[F.pid]]) }, { v: BP.teamAbbr(r[F.from]), html: r[F.from] ? tlink(r[F.from]) : '' },
    { v: BP.teamAbbr(r[F.to]), html: r[F.to] ? tlink(r[F.to]) : '' }, { v: r[F.detail] || '', html: '<span class="muted-inline">' + esc(r[F.detail] || '') + '</span>' }]);
  return BP.card('Feed', list.length + ' moves' + (list.length > 600 ? ' (the latest 600 shown)' : ''),
    BP.tableHTML([{ label: 'Date' }, { label: 'Move' }, { label: 'Player' }, { label: 'From' }, { label: 'To' }, { label: 'Detail' }], rows, { compact: true, sticky: true }) +
    '<div class="npb-note">' + esc((mv.notes || []).join(' ')) + '</div>');
}

function ilHTML(mv) {
  const F = {};
  (mv.il_fields || []).forEach((f, i) => { F[f] = i; });
  const N = mv.names || {};
  const list = (mv.il_now || []).filter(r => !M.team || r[F.club] === M.team);
  const rows = list.map(r => [{ v: N[r[F.pid]] || '', html: plink(r[F.pid], N[r[F.pid]]) }, { v: BP.teamAbbr(r[F.club]), html: tlink(r[F.club]) },
    { v: r[F.list], html: r[F.list] + '-day', align: 'right' }, { v: r[F.start], html: esc(BP.fmtDate(r[F.start])) }, { v: r[F.part] || '', html: esc(PART[r[F.part]] || r[F.part] || '—') },
    { v: r[F.days], html: BP.int(r[F.days]), align: 'right' }]);
  return BP.card('On the injured list now', list.length + ' players · placements not yet followed by an activation, release or trade',
    rows.length ? BP.tableHTML([{ label: 'Player' }, { label: 'Club' }, { label: 'List', align: 'right' }, { label: 'Since' }, { label: 'Body part' }, { label: 'Days', align: 'right' }], rows, { compact: true }) : BP.muted('Nobody.'));
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
    h += BP.card('Does the value at the time predict what happened?', 'Trades of ' + esc(v.span || '') + ': the expectation over the rest of the trade\'s season and the next one against the WAR realised for the club over the same span. Naive: the player\'s last season\'s WAR rate over the same playing time.',
      BP.tableHTML(['', { label: 'n', align: 'right' }, { label: 'r (model)', align: 'right' }, { label: 'r (naive)', align: 'right' }, { label: 'Rank r (model)', align: 'right' },
        { label: 'Rank r (naive)', align: 'right' }, { label: 'MAE (model)', align: 'right' }, { label: 'MAE (naive)', align: 'right' }, { label: 'Slope', align: 'right', title: 'Realised on expected, through the origin' }], rows, { compact: true }));
  }
  if (tr && tr.retention && tr.retention.by) {
    const by = tr.retention.by, ns = tr.retention.n || {};
    const keys = Object.keys(by).filter(k => k.indexOf('none') < 0 && k.indexOf('any') < 0).sort();
    const rows = keys.map(k => { const p = k.split('|'); return [esc(p[0]) + ' MLB seasons, ' + (p[1] === 'in' ? 'in-season trade' : 'between seasons')].concat(by[k].map((x, i) => ({ v: x, html: isNum(x) ? BP.pct(x, 0) + ' <span class="muted-inline">' + BP.int((ns[k] || [])[i]) + '</span>' : '—', align: 'right' }))); });
    h += BP.card('Retention: the chance a traded player is still with the club', 'Of traded players who played in the majors in a later season, the share who did so mainly for the club that acquired them (2015 on). It stands in for contracts and club control. Columns: the first to fifth season after an in-season trade; the first to fifth season (the trade\'s own first) for one between seasons. Small numbers: players.',
      BP.tableHTML(['Group', { label: '1', align: 'right' }, { label: '2', align: 'right' }, { label: '3', align: 'right' }, { label: '4', align: 'right' }, { label: '5', align: 'right' }], rows, { compact: true }));
  }
  if (tr && tr.prospect_model) {
    const pm = tr.prospect_model;
    const rows = ['H', 'P'].filter(k => pm[k] && pm[k].validation).map(k => { const v = pm[k].validation; return [k === 'H' ? 'Hitters' : 'Pitchers', { v: v.n, html: BP.int(v.n), align: 'right' },
      { v: v.spearman_model, html: BP.num(v.spearman_model, 2), align: 'right' }, { v: v.spearman_level_mean, html: BP.num(v.spearman_level_mean, 2), align: 'right' },
      { v: v.mae_model, html: BP.num(v.mae_model, 2), align: 'right' }, { v: v.mae_level_mean, html: BP.num(v.mae_level_mean, 2), align: 'right' },
      { v: v.top5pct_mean_actual, html: BP.num(v.top5pct_mean_pred, 2) + ' → ' + BP.num(v.top5pct_mean_actual, 2), align: 'right' }, { v: v.all_mean_actual, html: BP.num(v.all_mean_actual, 2), align: 'right' }]; });
    h += BP.card('Prospects: expected MLB WAR from minor-league lines', 'Four seasons after a minor-league season, discounted; fitted on the cohorts to 2019 and scored on 2021–22 (no minor-league season in 2020), against each level\'s mean. Stat lines only — no scouting grades — so the very best prospects are under-rated.',
      BP.tableHTML(['', { label: 'n', align: 'right' }, { label: 'Rank r', align: 'right' }, { label: 'Rank r (level mean)', align: 'right' }, { label: 'MAE', align: 'right' }, { label: 'MAE (level mean)', align: 'right' },
        { label: 'Top 5%: expected → actual', align: 'right' }, { label: 'Mean actual', align: 'right' }], rows, { compact: true }));
  }
  if (tr && tr.base_rates) {
    const br = tr.base_rates;
    h += BP.card('Players with no record', 'Traded players with no MLB record and no minor-league line in the two seasons before (amateur signees, players hurt all season): the average of what traded players of the same age band with no MLB record went on to produce (2015–22 trades).',
      BP.tableHTML(['Age band', { label: 'Value (4 seasons, disc.)', align: 'right' }, { label: 'Share above 0.5 WAR', align: 'right' }, { label: 'n', align: 'right' }],
        Object.keys(br).map(k => [esc(k), { v: br[k].value, html: BP.num(br[k].value, 2), align: 'right' }, { v: br[k].share_positive, html: BP.pct(br[k].share_positive, 0), align: 'right' }, { v: br[k].n, html: BP.int(br[k].n), align: 'right' }]), { compact: true }));
  }
  h += BP.card('Sources and terms', '', '<div class="pad trd-text">' + esc((tr && tr.source) || (mv && mv.source) || '') + '</div>');
  return h;
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
if (typeof BP.route === 'function') BP.route('moves', movesPage);
})(window.BP || (window.BP = {}));
