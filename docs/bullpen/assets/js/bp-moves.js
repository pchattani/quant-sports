/* The Quant Bullpen — who moves next (docs/_design/MOVES_VIEWS.md, "US sports"), from mlb/movement.json
 * (oddsmarkets/common/movement.py payload(); method and validation in docs/research/moves_model.md).
 *
 *   BP.moves.load()                         the payload (226 KB), loaded once and only by the views that need it
 *   BP.moves.rosterColumn(tid) -> spec       a QK.leaderboard column "Chance of moving" (bar split by type) + legend HTML
 *   BP.moves.teamCards(host, tid, L, S)      the Outlook card and the Targets table (team page)
 *   BP.moves.playerCard(host, pid, L, S)     the Movement card (player page)
 *   BP.moves.modelBlock(host)                "Who moves next" on the Model page: notes verbatim, validation, deciles
 *
 * The views follow the payload's `published` flags: a block that is not published shows its base rate with a
 * "base rate" chip and `reasons` (the deadline block today), never a placeholder. Names come from players_index.json
 * where it has them (the payload's own names can carry encoding damage), else the payload. MLB only. */
(function (BP) {
'use strict';

const esc = BP.esc, isNum = BP.isNum;
let P = null;
const TYPE_COL = ['var(--c-1)', 'var(--c-3)', 'var(--c-4)', 'var(--c-6)'];

function load() {
  if (P) return P;
  P = BP.load('mlb/movement.json').then(d => {
    if (!BP.ok(d) || !Array.isArray(d.players)) return null;
    const F = {};
    (d.player_fields || []).forEach((f, i) => { F[f] = i; });
    const byPid = {};
    d.players.forEach(r => { byPid[String(r[F.pid])] = r; });
    const TF = {};
    Object.keys(d.team_fields || {}).forEach(k => { TF[k] = {}; (d.team_fields[k] || []).forEach((f, i) => { TF[k][f] = i; }); });
    return { d: d, F: F, TF: TF, byPid: byPid };
  });
  return P;
}
const pct = (p, d) => (isNum(p) ? (p > 0 && p < 0.01 && !d ? '<1%' : QK.fmt.pct(p, d)) : '—');
const nameOf = (pid, fallback) => { const x = BP.player(pid) || {}; return x.name || fallback || BP.playerName(pid); };
const tip = (txt, label) => '<span data-tip="' + esc(txt) + '" tabindex="0">' + esc(label || 'ⓘ') + '</span>';
const baseChip = why => '<span class="qk-tag" data-tip="' + esc(why || 'The league base rate, not a player-level forecast') + '" tabindex="0">base rate</span>';
function typeKeys(m) {
  const d = m.d;
  return QK.keys((d.types || []).map((t, i) => ({ name: (d.type_labels || {})[t] || t, color: TYPE_COL[i % TYPE_COL.length], kind: 'dot' }))) +
    (d.published && d.published.type === false ? ' ' + baseChip('The split is the league\'s shares, not the player\'s') : '');
}
/* A 0-100% bar of the chance he moves, split by how (types order), with the percentage. */
function typeBar(m, row, w) {
  const d = m.d, F = m.F, p = row[F.p_next];
  if (!isNum(p)) return '—';
  const segs = (d.types || []).map((t, i) => { const x = row[F['p_' + t]]; return isNum(x) && x > 0 ? '<b style="width:' + (100 * x).toFixed(1) + '%;background:' + TYPE_COL[i % TYPE_COL.length] + '" title="' + esc(((d.type_labels || {})[t] || t) + ' ' + pct(x)) + '"></b>' : ''; }).join('');
  return '<span class="bp-mv"' + (w ? ' style="--w:' + w + 'px"' : '') + '><i class="tr" role="img" aria-label="' + esc('Chance of leaving ' + pct(p)) + '">' + segs + '</i><span class="v">' + pct(p) + '</span></span>';
}

/* The roster column: the leaderboard spec and the legend line to put above the table. */
function rosterColumn(m, label) {
  const d = m.d, F = m.F;
  if (!d.published || d.published.next === false) return null;
  const head = 'Chance he’s gone by ' + (d.horizons || {}).next;
  return {
    col: { key: 'p_move', label: label || 'Chance of leaving', tip: head + '. ' + ((d.notes || [])[0] || ''), fmt: (x, r) => (r._mv ? typeBar(m, r._mv) + (r._mv[F.why] ? '<div class="bp-mv-why">' + esc(r._mv[F.why]) + '</div>' : '') : '<span class="qk-muted" title="Not on a club’s roster in the movement file">—</span>') },
    rowOf: pid => m.byPid[String(pid)] || null,
    pOf: pid => { const r = m.byPid[String(pid)]; return r ? r[F.p_next] : null; },
    legend: '<div class="bp-mv-legend"><span class="qk-kicker" style="margin:0">' + esc(head) + '</span>' + typeKeys(m) + deadlineLine(m) + '</div>'
  };
}
function deadlineLine(m) {
  const d = m.d;
  if (d.published && d.published.deadline) return '';
  const r = (d.base_rates || {}).deadline;
  if (!isNum(r)) return '';
  return '<span class="bp-mv-dl">About ' + pct(r) + ' of players are ' + esc(d.deadline_label || 'traded') + ' before ' + esc(BP.fmtDate((d.horizons || {}).deadline, { year: true })) + ' ' + baseChip((d.reasons || {}).deadline) + '</span>';
}

/* Team page: Outlook and Targets. */
function teamCards(host, tid, L, S) {
  if (!host) return;
  if (L !== 'mlb' || Number(S) !== BP.currentSeason('mlb')) { host.innerHTML = ''; return; }
  load().then(m => {
    if (!host.isConnected || !m) { if (host.isConnected) host.innerHTML = ''; return; }
    const d = m.d, t = (d.teams || {})[String(tid)];
    if (!t) { host.innerHTML = ''; return; }
    const U = BP.ui, O = m.TF.outlook || {}, TG = m.TF.targets || {};
    const hz = d.team_horizon === 'deadline' ? 'to the deadline' : (d.horizons || {}).next;
    const pubA = !d.published || d.published.arrivals !== false;
    const cuts = d.status_cuts || {};
    const status = t.status ? '<span class="qk-tag" data-tip="' + esc('From our standings: contending above ' + pct(cuts.contending) + ' expected win share, rebuilding below ' + pct(cuts.rebuilding)) + '" tabindex="0">' + esc(t.status) + '</span>' : '';
    const ba = d.base_arrivals || {};
    const rows = (t.outlook || []).map(r => ({ pos: r[O.pos], p_add: pubA ? r[O.p_add] : (ba[r[O.pos]] || [])[0], arr: pubA ? r[O.exp_arrivals] : (ba[r[O.pos]] || [])[1], dep: r[O.exp_departures], need: r[O.need], n: r[O.players] }));
    const arrSum = pubA ? t.exp_arrivals : Object.keys(ba).reduce((s0, k) => s0 + (ba[k][1] || 0), 0);
    const tiles = QK.stats([
      { label: 'Expected departures', value: U.f(t.exp_departures, 1), sub: 'players gone by ' + (d.horizons || {}).next, tip: 'The sum of every rostered player\'s chance of leaving' },
      { label: pubA ? 'Expected arrivals' : 'Expected arrivals (league average)', value: U.f(arrSum, 1), sub: 'from other MLB clubs', tip: 'From other clubs\' rosters only: prospects from the club\'s own system, draft picks and signings from outside MLB are not counted' }
    ]);
    const grid = '<div id="mv-out"></div>';
    const outlook = U.card2('Outlook: ' + hz, 'Who leaves and where the club is likely to add, by position' + (pubA ? '' : ' ' + baseChip((d.reasons || {}).arrivals)), tiles + '<div style="margin-top:12px">' + grid + '</div>', { right: status });
    const tg = (t.targets || []);
    const pubT = d.published && d.published.targets;
    const vt = ((d.validation || {}).targets || {}).test || {};
    const vtip = isNum((vt.model || {}).precision) ? 'On 2023-2025, ' + pct((vt.model || {}).precision, 1) + ' of a club\'s top 10 joined it, against ' + pct((vt.need_value || {}).precision, 1) + ' for the best upgrades alone and ' + pct(vt.chance_precision, 1) + ' by chance. A shortlist, not a prediction of the move.' : '';
    let targets;
    if (pubT) targets = U.card2('Who they could get', 'Ranked by chance of joining: the chance he moves x the chance he lands here; only players who would upgrade the weakest regular at the position ' + (vtip ? tip(vtip) : ''), tg.length ? '<div id="mv-tg"></div>' : QK.empty('No targets', 'No player on another club would upgrade a regular slot here.'));
    else targets = U.card2('Who they could get', '', QK.empty('Not published', (d.reasons || {}).targets || 'The targets model did not pass its test.'));
    host.innerHTML = '<div class="qk-grid" style="margin-top:var(--sp-4)"><div class="qk-span-5">' + outlook + '</div><div class="qk-span-7">' + targets + '</div></div>';
    QK.leaderboard(host.querySelector('#mv-out'), { dense: true, sort: { key: 'p_add', dir: 'desc' }, columns: [
      { key: 'pos', label: 'Pos' },
      { key: 'p_add', label: 'Chance of adding', type: 'bar', max: 1, fmt: x => pct(x), tip: 'The chance the club adds at least one player at this position from another MLB club by ' + (d.horizons || {}).next },
      { key: 'arr', label: 'Arrivals', num: true, fmt: x => U.f(x, 1), tip: 'Expected arrivals at the position' },
      { key: 'dep', label: 'Departures', num: true, fmt: x => U.f(x, 1), tip: 'Expected departures at the position' },
      { key: 'need', label: 'Strength', num: true, fmt: x => (isNum(x) ? QK.pctlChip(Math.round((1 - x) * 100)) : '—'), tip: 'The club\'s strength at the position among the 30 clubs as a percentile (100 = the strongest)' }],
      rows: rows });
    const tgHost = host.querySelector('#mv-tg');
    if (tgHost) QK.leaderboard(tgHost, { dense: true, rank: true, sort: { key: 'p_join', dir: 'desc' }, columns: [
      { key: 'name', label: 'Player', type: 'entity', sub: 'sub', mark: r => U.team(r.team), href: r => BP.playerHref(r.pid, { level: 'mlb', role: /^(SP|RP|P)$/.test(r.pos) ? 'pitcher' : 'hitter' }) },
      { key: 'p_join', label: 'Chance of joining', num: true, fmt: x => pct(x, 1), tip: 'The chance he joins this club by ' + (d.horizons || {}).next + '; 1-2% is a strong target among 30 clubs' },
      { key: 'p_move', label: 'Availability', type: 'bar', max: 1, fmt: x => pct(x), tip: 'His chance of leaving his club at all' },
      { key: 'gain', label: 'Fit', num: true, fmt: (x, r) => (isNum(x) ? U.signed(x, 1) + ' ' + esc(d.unit || 'WAR') : '—'), tip: 'The upgrade over the club\'s weakest regular at his position' },
      { key: 'why', label: 'Why', sort: false, fmt: x => '<span class="bp-mv-why">' + esc(x || '') + '</span>' }],
      rows: tg.map(r => ({ pid: String(r[TG.pid]), name: nameOf(r[TG.pid], r[TG.name]), team: String(r[TG.team]), pos: r[TG.pos], sub: r[TG.pos] + ' · ' + BP.teamAbbr(r[TG.team]) + ' · age ' + Math.floor(r[TG.age]), p_join: r[TG.p_join], p_move: r[TG.p_move], gain: r[TG.gain], why: r[TG.why] })) });
  });
}

/* Player page: the Movement card, written into host when it scrolls into view (the payload loads then). */
function playerCard(host, pid, L, S) {
  if (!host) return;
  if (L !== 'mlb' || Number(S) !== BP.currentSeason('mlb')) { host.remove(); return; }
  const go = () => load().then(m => {
    if (!host.isConnected) return;
    const row = m && m.byPid[String(pid)];
    if (!m || !row || !m.d.published || m.d.published.next === false) { host.remove(); return; }
    const d = m.d, F = m.F, U = BP.ui;
    const fits = [];
    const TG = m.TF.targets || {};
    Object.keys(d.teams || {}).forEach(t => (d.teams[t].targets || []).forEach(r => { if (String(r[TG.pid]) === String(pid)) fits.push({ t: t, p: r[TG.p_join] }); }));
    fits.sort((a, b) => b.p - a.p);
    const ctx = [isNum(row[F.age]) ? 'age ' + Math.floor(row[F.age]) : '', isNum(row[F.yrs]) ? row[F.yrs] + ' season' + (row[F.yrs] === 1 ? '' : 's') + ' since his debut' : '', isNum(row[F.value]) ? U.signed(row[F.value], 1) + ' ' + (d.unit || 'WAR') + ' (two seasons blended)' : ''].filter(Boolean).join(' · ');
    host.innerHTML = U.card2('Movement', 'Chance he’s gone by ' + esc((d.horizons || {}).next) + ' ' + tip((d.notes || []).slice(0, 2).join(' ')),
      '<div class="bp-mv-big"><span class="big">' + pct(row[F.p_next]) + '</span><span class="qk-muted">' + esc(row[F.why] || '') + '</span></div>' + typeBar(m, row) +
      '<div style="margin-top:8px">' + typeKeys(m) + '</div><div class="bp-note">' + esc(ctx) + '</div>' +
      (deadlineLine(m) ? '<div class="bp-note">' + deadlineLine(m) + '</div>' : (isNum(row[F.p_dl]) ? '<div class="bp-note">' + esc(d.deadline_label === 'traded' ? 'Traded' : 'Moved') + ' before the deadline: <b>' + pct(row[F.p_dl]) + '</b></div>' : '')) +
      (fits.length ? '<div class="qk-kicker" style="margin:12px 0 6px">Clubs that fit</div><ul class="bp-list">' + fits.slice(0, 5).map(f => '<li>' + U.teamEnt(f.t, 'mlb') + '<span class="v">' + pct(f.p, 1) + '</span></li>').join('') + '</ul>' : ''),
      { foot: '<span>An estimate from on-field value and history; no contract data</span><a href="#/methodology#who-moves-next">How →</a>' });
  });
  if ('IntersectionObserver' in window) {
    const io = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) { io.disconnect(); go(); } }, { rootMargin: '200px' });
    io.observe(host);
    BP.onLeave(() => io.disconnect());
  } else go();
}

/* Model page: "Who moves next". */
function modelBlock(host) {
  if (!host) return;
  load().then(m => {
    if (!host.isConnected || !m) return;
    const d = m.d, V = d.validation || {}, pub = d.published || {}, U = BP.ui;
    const NAME = { next: 'Leaves by next season', deadline: 'Traded before the deadline', type: 'How he leaves', arrivals: 'Arrivals by position', targets: 'Targets (top 10 per club)' };
    const rows = Object.keys(NAME).filter(k => V[k]).map(k => {
      const t = V[k].test || {};
      if (k === 'targets') return '<tr><td>' + esc(NAME[k]) + '</td><td class="num">' + esc((d.split || {}).test ? d.split.test.join(', ') : '') + '</td><td class="num">' + esc(t.team_seasons) + ' club-seasons</td><td class="num" colspan="3">precision ' + pct((t.model || {}).precision, 1) + ' v ' + pct((t.need_value || {}).precision, 1) + ' (need x value) and ' + pct(t.chance_precision, 1) + ' (chance)</td><td>' + (pub[k] ? 'yes' : 'no') + '</td></tr>';
      const g = t.ll_gain || [];
      return '<tr><td>' + esc(NAME[k]) + '</td><td class="num">' + esc((d.split || {}).test ? d.split.test.join(', ') : '') + '</td><td class="num">' + QK.fmt.num(t.n) + (isNum(t.rate) ? ' · ' + pct(t.rate, 1) + ' happened' : '') + '</td><td class="num">' + U.f(t.logloss, 4) + ' v ' + U.f(t.logloss_base, 4) + '</td><td class="num">' + (isNum(g[0]) ? U.f(g[0], 4) + ' (' + U.f(g[1], 4) + ' to ' + U.f(g[2], 4) + ')' : '—') + '</td><td class="num">' + U.f(t.cal_slope, 2) + '</td><td>' + (pub[k] ? 'yes' : 'no' + ((d.reasons || {})[k] ? ' ' + tip(d.reasons[k]) : '')) + '</td></tr>';
    }).join('');
    const dec = ((V.next || {}).test || {}).deciles || [];
    host.innerHTML = U.card2('Who moves next', 'Chance of leaving, how, outlook by position and targets: the method in our own words, then how it did on the sealed seasons',
      (d.notes || []).map(n => '<p>' + esc(n) + '</p>').join('') +
      '<div class="qk-table-wrap"><table class="qk-table dense"><thead><tr><th>Block</th><th class="num">Sealed seasons</th><th class="num">Cases</th><th class="num">Log loss: model v base rate</th><th class="num">Gain (95% CI)</th><th class="num">Calibration slope</th><th>Published</th></tr></thead><tbody>' + rows + '</tbody></table></div>' +
      (dec.length ? U.chart('mv-dec', 300, 'Predicted chance against the observed share, by decile') + '<p class="bp-note">Leaves by next season on the sealed seasons, in ten bins by our chance: the diagonal is perfect calibration.</p>' : ''), { id: 'who-moves-next' });
    if (dec.length) {
      const top = Math.min(1, Math.ceil(Math.max.apply(null, dec.map(x => Math.max(x[0], x[1]))) * 10 + 0.5) / 10);
      QKC.line('#mv-dec', { xType: 'value', xMin: 0, xMax: top, yMin: 0, yMax: top, series: [
        { name: 'Perfect', data: [[0, 0], [top, top]], color: QK.cssVar('--ink-3'), dash: true, width: 1 },
        { name: 'Observed share', data: dec.map(x => [x[0], x[1]]), color: QK.cssVar('--signal'), symbols: true, width: 2 }],
        xFmt: x => pct(x), yFmt: x => pct(x), xName: 'Predicted chance', yName: 'Observed share', endLabels: true, label: 'Calibration of the chance of leaving' });
    }
  });
}

BP.moves = { load: load, rosterColumn: rosterColumn, teamCards: teamCards, playerCard: playerCard, modelBlock: modelBlock, typeBar: typeBar, typeKeys: typeKeys };

/* The Model page: append "Who moves next" to the methodology. */
const METH = BP.HANDLERS.methodology;
if (METH) BP.route('methodology', (el, params, state) => Promise.resolve(METH(el, params, state)).then(() => {
  if (!el.isConnected) return;
  const box = document.createElement('div');
  box.className = 'qk-section';
  el.appendChild(box);
  modelBlock(box);
}));
})(window.BP);
