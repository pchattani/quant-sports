/* The Quant Bullpen — fantasy (#/mlb/fantasy), on Design System 2.0.
 *
 * Tabs: Rankings (5x5 rotisserie values for a 12-team mixed league, or points under an editable scheme; hitters,
 * pitchers or everyone; position, club and name filters; tiers by position), Dynasty (five-season values and the best
 * prospects), Our picks (sleepers, fallers, young risers; luck against skills), Closers (projected saves and holds by club),
 * Steals (projected steals, attempt rates, sprint speed, untapped speed), This week (in season: two-start and streaming
 * starters, the best hitters' week), Backtest (the walk-forward checks against the official lines), Scoring (the points
 * weights, kept in this browser). Lists are v2 leaderboards; the page opens with stat tiles.
 * State in the hash: #/mlb/fantasy?tab=rank&fmt=5x5|pts&kind=all|H|P&pos=SS.
 *
 * Data: data/mlb/fantasy.json, data/mlb/fantasy_backtest.json (PAYLOADS.md, "Fantasy"). No optional chaining or
 * nullish coalescing (older browsers). */
(function (BP) {
'use strict';

const esc = BP.esc;
const isNum = BP.isNum;
const KEY = 'qb-fantasy-points-v1';
const POS_H = ['C', '1B', '2B', '3B', 'SS', 'OF', 'CI', 'MI', 'UT'];
const S = { tab: 'rank', fmt: '5x5', kind: 'all', pos: '', team: '', q: '' };
let WEIGHTS = null;
let AFTER = [];

function n0(v) { return isNum(v) ? Math.round(Number(v)).toString() : '—'; }
function n1(v) { return isNum(v) ? Number(v).toFixed(1) : '—'; }
function n2(v) { return isNum(v) ? Number(v).toFixed(2) : '—'; }
function avg(v) { return isNum(v) ? BP.fmtAvg(v) : '—'; }
function phref(pid, kind) { return BP.playerHref(pid, { level: 'mlb', role: kind === 'P' ? 'pitcher' : kind === 'H' ? 'hitter' : null }); }
function loadWeights(def) {
  let w = null;
  try { w = JSON.parse(window.localStorage.getItem(KEY) || 'null'); } catch (e) { w = null; }
  const out = { H: Object.assign({}, def.H), P: Object.assign({}, def.P) };
  if (w && w.H && w.P) { Object.keys(out.H).forEach(k => { if (isNum(w.H[k])) out.H[k] = Number(w.H[k]); }); Object.keys(out.P).forEach(k => { if (isNum(w.P[k])) out.P[k] = Number(w.P[k]); }); }
  return out;
}
function saveWeights(w) { try { window.localStorage.setItem(KEY, JSON.stringify(w)); } catch (e) { /* private mode: kept for this visit */ } }
function idx(fields) { const F = {}; (fields || []).forEach((f, i) => { F[f] = i; }); return F; }
function points(row, F, kind) {
  const w = WEIGHTS[kind];
  let t = 0;
  Object.keys(w).forEach(k => { if (F[k] !== undefined && isNum(row[F[k]])) t += w[k] * Number(row[F[k]]); });
  return t;
}
function hashOf() {
  const q = ['tab=' + S.tab, 'fmt=' + S.fmt, 'kind=' + S.kind];
  if (S.pos) q.push('pos=' + encodeURIComponent(S.pos));
  return '#/mlb/fantasy?' + q.join('&');
}
function tierChip(t) { return isNum(t) ? '<span class="ft-tier ft-t' + Math.min(t, 6) + '">' + t + '</span>' : ''; }
function flagsHTML(f) { return (f || []).length ? '<span class="bp-mv-why">' + esc(f.join(' · ')) + '</span>' : ''; }
function posOf(x) { const r = x.r, F = x.F; return x.kind === 'H' ? ((r[F.elig] || []).filter(p => p !== 'UT' && p !== 'CI' && p !== 'MI').join(' ') || 'UT') : (r[F.role] || ''); }
/* A v2 leaderboard drawn into a placeholder once the tab's HTML is in the page. */
function board(id, spec) { AFTER.push(() => { const n = document.getElementById(id); if (n) QK.leaderboard(n, spec); }); return '<div id="' + esc(id) + '"></div>'; }
const card = (t, s, b, o) => BP.ui.card2(t, s, b, o);

function fantasyPage(el, params) {
  const U = BP.ui;
  const qy = params.query || {};
  ['tab', 'fmt', 'kind', 'pos'].forEach(k => { if (qy[k] !== undefined) S[k] = qy[k]; });
  el.innerHTML = QK.skeleton('card', 2);
  if (params.level && params.level !== 'mlb') {
    el.innerHTML = QK.sectionHead({ kicker: 'Fantasy', title: 'Fantasy baseball', sub: 'The fantasy layer covers MLB; Triple-A players appear in the dynasty list as prospects.', actions: '<a class="qk-btn primary" href="#/mlb/fantasy">MLB fantasy</a>' });
    return null;
  }
  return Promise.all([BP.load('mlb/fantasy.json'), BP.load('mlb/fantasy_backtest.json')]).then(res => {
    if (!el.isConnected) return;
    const d = BP.ok(res[0]) ? res[0] : null, bt = BP.ok(res[1]) ? res[1] : null;
    const head = QK.sectionHead({ kicker: 'Fantasy · MLB ' + (d ? d.target || '' : ''), title: 'Fantasy baseball', sub: d ? (d.in_season ? 'Rest-of-season values' : String(d.target) + ' draft values') + ': 5x5 rotisserie for a ' + ((d.league || {}).teams || 12) + '-team mixed league, or points under your own scoring; dynasty, closers, steals and the weekly streamers.' : '',
      actions: '<a class="qk-btn" href="#/mlb/value">Player value</a><a class="qk-btn" href="#/mlb/moves">Moves</a>' });
    if (!d) { el.innerHTML = head + QK.empty('Not built yet', 'The fantasy file is not available.'); return; }
    Object.keys(d.teams || {}).forEach(t => { if (!BP.TEAMS[t] && d.teams[t] && d.teams[t].name) BP.TEAMS[t] = Object.assign({}, d.teams[t]); });
    WEIGHTS = loadWeights(d.points || { H: {}, P: {} });
    const HF = idx(d.h_fields), PF = idx(d.p_fields), PX = idx(d.prospect_fields);
    const tabs = [['rank', 'Rankings'], ['dyn', 'Dynasty'], ['picks', 'Our picks'], ['closers', 'Closers'], ['steals', 'Steals'], ['week', 'This week'], ['bt', 'Backtest'], ['scoring', 'Scoring']];
    const teams = Object.keys(d.teams || {}).sort((a, b) => BP.teamName(a).localeCompare(BP.teamName(b)));
    const h1 = (d.hitters || []).slice().sort((a, b) => (a[HF.rank] || 9999) - (b[HF.rank] || 9999))[0];
    const p1 = (d.pitchers || []).slice().sort((a, b) => (a[PF.rank] || 9999) - (b[PF.rank] || 9999))[0];
    const x1 = (d.prospects || []).slice().sort((a, b) => (a[PX.dyn_rank] || 9999) - (b[PX.dyn_rank] || 9999))[0];
    const sv = (d.pitchers || []).filter(r => isNum(r[PF.sv])).sort((a, b) => b[PF.sv] - a[PF.sv])[0];
    const tiles = QK.stats([
      h1 ? { label: 'Top hitter', value: BP.playerSurname(h1[HF.pid]) + ' $' + n0(h1[HF.usd]), signal: true, sub: '#' + n0(h1[HF.rank]) + ' overall · ' + BP.teamAbbr(h1[HF.team]), href: phref(h1[HF.pid], 'H') } : null,
      p1 ? { label: 'Top pitcher', value: BP.playerSurname(p1[PF.pid]) + ' $' + n0(p1[PF.usd]), sub: '#' + n0(p1[PF.rank]) + ' overall · ' + BP.teamAbbr(p1[PF.team]), href: phref(p1[PF.pid], 'P') } : null,
      sv ? { label: 'Most projected saves', value: BP.playerSurname(sv[PF.pid]) + ' ' + n0(sv[PF.sv]), sub: BP.teamAbbr(sv[PF.team]), href: phref(sv[PF.pid], 'P') } : null,
      x1 ? { label: 'Top dynasty prospect', value: BP.playerSurname(x1[PX.pid]) || x1[PX.name], sub: (x1[PX.pos] || '') + ' · age ' + n0(x1[PX.age]), href: phref(x1[PX.pid]) } : null
    ]);
    el.innerHTML = head + (d.in_season ? '' : '<p class="bp-note">Between seasons: the rankings are ' + esc(String(d.target)) + ' draft projections; rest-of-season, next-week, two-start and streaming views return when the season starts.</p>') +
      '<div class="bp-kpis">' + tiles + '</div>' +
      '<nav class="qk-tabs bp-tabs2" id="fx-tab" aria-label="Fantasy views">' + tabs.map(t => '<a class="qk-tab" href="javascript:void(0)" data-k="' + t[0] + '" aria-selected="' + (t[0] === S.tab) + '">' + esc(t[1]) + '</a>').join('') + '</nav>' +
      '<section class="qk-card" id="fx-filters"><div class="qk-card-body"><div class="bp-ctl">' + U.seg('fx-fmt', 'Format', [['5x5', '5x5'], ['pts', 'Points']], S.fmt) + U.seg('fx-kind', 'Players', [['all', 'All'], ['H', 'Hitters'], ['P', 'Pitchers']], S.kind) +
      '<label>Position<select id="fx-pos"><option value="">All</option>' + POS_H.concat(['SP', 'RP']).map(p => '<option value="' + p + '"' + (p === S.pos ? ' selected' : '') + '>' + p + '</option>').join('') + '</select></label>' +
      '<label>Club<select id="fx-team"><option value="">All</option>' + teams.map(t => '<option value="' + esc(t) + '"' + (t === S.team ? ' selected' : '') + '>' + esc(BP.teamAbbr(t) + ' · ' + BP.teamShort(t)) + '</option>').join('') + '</select></label>' +
      '<label>Find<input id="fx-q" type="search" placeholder="player…" value="' + esc(S.q) + '"></label></div></div></section><div id="fx-body" style="margin-top:var(--sp-4)"></div>';
    const $ = id => document.getElementById(id);
    const draw = () => {
      $('fx-filters').style.display = (S.tab === 'rank' || S.tab === 'dyn') ? '' : 'none';
      const body = $('fx-body');
      AFTER = [];
      if (S.tab === 'rank') body.innerHTML = rankHTML(d, HF, PF);
      else if (S.tab === 'dyn') body.innerHTML = dynHTML(d, HF, PF);
      else if (S.tab === 'picks') body.innerHTML = picksHTML(d, HF, PF, bt);
      else if (S.tab === 'closers') body.innerHTML = closersHTML(d, PF);
      else if (S.tab === 'steals') body.innerHTML = stealsHTML(d, HF);
      else if (S.tab === 'week') body.innerHTML = weekHTML(d);
      else if (S.tab === 'bt') body.innerHTML = btHTML(bt);
      else body.innerHTML = scoringHTML(d);
      AFTER.forEach(f => f());
      BP.sortable(body);
      if (S.tab === 'scoring') wireScoring(d, draw);
    };
    const upd = () => { history.replaceState(null, '', hashOf()); draw(); };
    $('fx-tab').querySelectorAll('a[data-k]').forEach(a => a.addEventListener('click', ev => {
      ev.preventDefault();
      $('fx-tab').querySelectorAll('a').forEach(x => x.setAttribute('aria-selected', x === a ? 'true' : 'false'));
      S.tab = a.getAttribute('data-k'); upd();
    }));
    QK.seg($('fx-fmt'), k => { S.fmt = k; upd(); });
    QK.seg($('fx-kind'), k => { S.kind = k; if ((k === 'H' && (S.pos === 'SP' || S.pos === 'RP')) || (k === 'P' && POS_H.indexOf(S.pos) >= 0)) { S.pos = ''; $('fx-pos').value = ''; } upd(); });
    $('fx-pos').onchange = e => { S.pos = e.target.value; upd(); };
    $('fx-team').onchange = e => { S.team = e.target.value; draw(); };
    let timer = null;
    $('fx-q').oninput = e => { S.q = e.target.value; clearTimeout(timer); timer = setTimeout(draw, 200); };
    draw();
    BP.setMeta(d.updated_at ? 'Fantasy file ' + esc(BP.fmtStamp(d.updated_at)) : '');
  });
}

// ── rankings ────────────────────────────────────────────────────────────────

function rowsFor(d, HF, PF) {
  const q = S.q.trim().toLowerCase();
  const out = [];
  const keep = (kind, r, F) => (!S.team || r[F.team] === S.team) && (!q || String(r[F.name] || '').toLowerCase().indexOf(q) >= 0) &&
    (!S.pos || (kind === 'H' ? (r[F.elig] || []).indexOf(S.pos) >= 0 : r[F.role] === S.pos));
  if (S.kind !== 'P' && !(S.pos === 'SP' || S.pos === 'RP')) (d.hitters || []).forEach(r => { if (keep('H', r, HF)) out.push({ kind: 'H', r: r, F: HF, pts: points(r, HF, 'H') }); });
  if (S.kind !== 'H' && POS_H.indexOf(S.pos) < 0) (d.pitchers || []).forEach(r => { if (keep('P', r, PF)) out.push({ kind: 'P', r: r, F: PF, pts: points(r, PF, 'P') }); });
  if (S.fmt === 'pts') out.sort((a, b) => b.pts - a.pts);
  else out.sort((a, b) => (a.r[a.F.rank] || 9999) - (b.r[b.F.rank] || 9999));
  return out;
}

function lineText(x) {
  const r = x.r, F = x.F;
  if (x.kind === 'H') return n0(r[F.pa]) + ' PA · ' + n0(r[F.r]) + ' R · ' + n0(r[F.hr]) + ' HR · ' + n0(r[F.rbi]) + ' RBI · ' + n0(r[F.sb]) + ' SB · ' + avg(r[F.avg]);
  return n0(r[F.ip]) + ' IP · ' + n0(r[F.w]) + ' W · ' + n0(r[F.sv]) + ' SV · ' + n0(r[F.so]) + ' K · ' + n2(r[F.era]) + ' · ' + n2(r[F.whip]);
}

function rankHTML(d, HF, PF) {
  const list = rowsFor(d, HF, PF);
  const pts = S.fmt === 'pts';
  const lg = d.league || {};
  const rows = list.slice(0, 500).map(x => {
    const r = x.r, F = x.F;
    const o = { pid: r[F.pid], kind: x.kind, name: r[F.name] || BP.playerName(r[F.pid]), team: r[F.team], sub: posOf(x) + ' · ' + (r[F.team] ? BP.teamAbbr(r[F.team]) : 'FA') + ' · ' + n0(r[F.age]),
      line: lineText(x), money: pts ? x.pts : r[F.usd], val: r[F.val], tier: r[F.tier], last: r[F.last_rank], flags: r[F.flags] };
    ['pa', 'r', 'hr', 'rbi', 'sb', 'avg', 'ip', 'gs', 'w', 'sv', 'so', 'era', 'whip', 'hld'].forEach(k => { if (F[k] !== undefined) o[k] = r[F[k]]; });
    return o;
  });
  const statCols = S.kind === 'H' ? [['pa', 'PA', n0], ['r', 'R', n0], ['hr', 'HR', n0], ['rbi', 'RBI', n0], ['sb', 'SB', n0], ['avg', 'AVG', avg]]
    : S.kind === 'P' ? [['ip', 'IP', n0], ['gs', 'GS', n0], ['w', 'W', n0], ['sv', 'SV', n0], ['so', 'K', n0], ['era', 'ERA', n2], ['whip', 'WHIP', n2], ['hld', 'HLD', n0]] : null;
  const cols = [{ key: 'name', label: S.kind === 'P' ? 'Pitcher' : S.kind === 'H' ? 'Hitter' : 'Player', type: 'entity', sub: 'sub', mark: o => (o.team ? BP.ui.team(o.team, 'mlb') : null), href: o => phref(o.pid, o.kind) }]
    .concat(statCols ? statCols.map(c => ({ key: c[0], label: c[1], num: true, fmt: c[2] })) : [{ key: 'line', label: 'Projection', sort: false, fmt: v => '<span class="ft-line">' + esc(v) + '</span>' }])
    .concat([pts ? { key: 'money', label: 'Points', type: 'bar', fmt: v => n0(v), tip: 'Projected points under your scoring (the Scoring tab)' } : { key: 'money', label: '$', type: 'bar', fmt: v => '$' + n0(v), tip: 'Auction value for a ' + (lg.teams || 12) + '-team league with a $' + (lg.budget || 260) + ' budget' },
      { key: 'val', label: 'Value', num: true, fmt: v => n2(v), tip: '5x5 z-score above replacement at his best position' },
      { key: 'tier', label: 'Tier', num: true, fmt: v => tierChip(v), tip: 'Tier within his position (1-D k-means of value)' },
      { key: 'last', label: 'Last', num: true, fmt: v => (isNum(v) ? '#' + v : '—'), tip: 'Last season\'s value rank' },
      { key: 'flags', label: 'Notes', sort: false, fmt: v => flagsHTML(v) }]);
  const sub = list.length + ' players · ' + (pts ? 'points under your scoring' : '5x5 for a ' + (lg.teams || 12) + '-team mixed league, $' + (lg.budget || 260) + ' budget') + (list.length > 500 ? ' · the first 500 shown' : '');
  return card('Rankings', esc(sub), rows.length ? board('fx-rank', { dense: true, rank: true, maxHeight: 720, columns: cols, rows: rows }) : QK.empty('Nobody here', 'No player matches these filters.'), { flush: true, foot: '<span>' + esc((d.notes || []).join(' ')) + '</span>' });
}

// ── dynasty ─────────────────────────────────────────────────────────────────

function dynHTML(d, HF, PF) {
  const q = S.q.trim().toLowerCase();
  const all = [];
  if (S.kind !== 'P') (d.hitters || []).forEach(r => all.push({ kind: 'H', r: r, F: HF }));
  if (S.kind !== 'H') (d.pitchers || []).forEach(r => all.push({ kind: 'P', r: r, F: PF }));
  const PX = idx(d.prospect_fields);
  (d.prospects || []).forEach(p => { if (S.kind === 'all' || S.kind === p[PX.kind]) all.push({ kind: 'X', r: p, F: PX }); });
  const list = all.filter(x => (!S.team || (x.kind === 'X' ? false : x.r[x.F.team] === S.team)) && (!q || String(x.r[x.F.name] || '').toLowerCase().indexOf(q) >= 0) &&
    (!S.pos || (x.kind === 'H' ? (x.r[x.F.elig] || []).indexOf(S.pos) >= 0 : x.kind === 'P' ? x.r[x.F.role] === S.pos : false)))
    .sort((a, b) => (a.r[a.F.dyn_rank] || 9999) - (b.r[b.F.dyn_rank] || 9999));
  const LV = { aaa: 'AAA', aa: 'AA', hia: 'A+', a: 'A' };
  const rows = list.slice(0, 400).map(x => {
    const r = x.r, F = x.F;
    if (x.kind === 'X') return { pid: r[F.pid], kind: r[F.kind], name: r[F.name] || BP.playerName(r[F.pid]), sub: (r[F.pos] || '') + ' · prospect · ' + n0(r[F.age]), dyn: r[F.dyn], red: null, now: isNum(r[F.p_value]) ? n2(r[F.p_value]) + ' WAR' : '—',
      line: (LV[r[F.level]] || r[F.level]) + ' line, z ' + (isNum(r[F.z]) ? BP.signed(r[F.z], 1) : '—') };
    return { pid: r[F.pid], kind: x.kind, name: r[F.name] || BP.playerName(r[F.pid]), team: r[F.team], sub: posOf(x) + ' · ' + (r[F.team] ? BP.teamAbbr(r[F.team]) : 'FA') + ' · ' + n0(r[F.age]), dyn: r[F.dyn], red: r[F.rank], now: n2(r[F.val]), line: lineText(x) };
  });
  return card('Dynasty and keepers', 'Five seasons of value: this season\'s 5x5 value above replacement times the five-season multiplier (expected WAR over five seasons, discounted 8% a year, aging and attrition included); prospects from the minor-league model, at ' + n2(d.war_to_value) + ' value per expected WAR',
    rows.length ? board('fx-dyn', { dense: true, rank: true, maxHeight: 720, columns: [
      { key: 'name', label: 'Player', type: 'entity', sub: 'sub', mark: o => (o.team ? BP.ui.team(o.team, 'mlb') : null), href: o => phref(o.pid, o.kind) },
      { key: 'dyn', label: 'Dynasty', type: 'bar', fmt: v => n2(v) }, { key: 'red', label: 'Redraft', num: true, fmt: v => (isNum(v) ? '#' + n0(v) : '—') },
      { key: 'now', label: 'This season / prospect', num: true, sort: false }, { key: 'line', label: 'Projection or line', sort: false, fmt: v => '<span class="ft-line">' + esc(v) + '</span>' }], rows: rows }) : QK.empty('Nobody here'), { flush: true });
}

// ── picks ───────────────────────────────────────────────────────────────────

function findRow(d, HF, PF, kind, pid) {
  const list = kind === 'H' ? d.hitters : d.pitchers;
  const F = kind === 'H' ? HF : PF;
  for (let i = 0; i < (list || []).length; i++) if (list[i][F.pid] === pid) return { r: list[i], F: F, kind: kind };
  return null;
}

function picksHTML(d, HF, PF, bt) {
  const P = d.picks || {};
  const block = (id, title, sub, list) => '<div class="qk-span-12">' + card(title, sub, (list || []).length ? board(id, { dense: true, columns: [
    { key: 'name', label: 'Player', type: 'entity', sub: 'sub', mark: o => (o.team ? BP.ui.team(o.team, 'mlb') : null), href: o => phref(o.pid, o.kind) },
    { key: 'ours', label: 'Our rank', num: true, fmt: v => '#' + v }, { key: 'last', label: 'Last season', num: true, fmt: v => (isNum(v) ? '#' + v : 'new') },
    { key: 'line', label: 'Projection', sort: false, fmt: v => '<span class="ft-line">' + esc(v) + '</span>' }, { key: 'why', label: 'Why', sort: false, fmt: v => flagsHTML(v) }],
    rows: list.map(it => { const x = findRow(d, HF, PF, it[0], it[1]); const r = x ? x.r : null; return { pid: it[1], kind: it[0], name: r ? r[x.F.name] : BP.playerName(it[1]), team: r ? r[x.F.team] : null, sub: x ? posOf(x) : '', ours: it[2], last: it[3], line: x ? lineText(x) : '', why: it[4] }; }) })
    : QK.empty('None'), { flush: true }) + '</div>';
  let luck = '';
  if (bt && bt.luck) {
    const L = bt.luck;
    luck = '<p class="bp-note">How much luck carries over: ' + ['H', 'P'].filter(k => L[k]).map(k => (k === 'H' ? 'hitters\' wOBA minus xwOBA' : 'pitchers\' RA9 minus xRA9') + ' against the next season\'s change, slope ' + n2(L[k].slope) + ' (−1: the gap closes fully), r ' + n2(L[k].corr) + ', ' + BP.int(L[k].n) + ' player-seasons').join('; ') + '.</p>';
  }
  return luck + '<div class="qk-grid">' + block('fx-sl', 'Sleepers', 'In our top 150 and at least 60 places better than last season\'s value rank (or new to the majors): buy.', P.sleepers) +
    block('fx-fa', 'Fallers', 'In last season\'s top 100 and at least 60 places worse in ours: sell high or pass.', P.fades || P.fallers) +
    block('fx-yr', 'Young risers', '25 or younger, in our top 200 and better than last season: dynasty and keeper targets.', P.young) + '</div>';
}

// ── closers and steals ──────────────────────────────────────────────────────

function closersHTML(d, PF) {
  const C = d.closers || {}, CF = idx(d.closer_fields);
  const byId = {};
  (d.pitchers || []).forEach(r => { byId[r[PF.pid]] = r; });
  const teams = Object.keys(C).sort((a, b) => BP.teamName(a).localeCompare(BP.teamName(b)));
  const cards = teams.map(t => '<div class="qk-span-3">' + card(BP.teamName(t), '', '<ul class="bp-list">' + C[t].map(x => {
    const r = byId[x[CF.pid]] || [];
    return '<li><span style="min-width:0">' + BP.ui.playerEnt(x[CF.pid], 'mlb', null, 'pitcher') + '<span class="bp-mv-why">' + (isNum(x[CF.sv_share]) && x[CF.sv_share] > 0 ? Math.round(100 * x[CF.sv_share]) + '% of the club\'s saves last season · ' : '') + 'ERA ' + n2(x[CF.era]) + ' · ' + n0(x[CF.so]) + ' K</span></span>' +
      '<span class="v">' + n0(x[CF.sv]) + ' SV <span class="qk-muted">' + n0(x[CF.hld]) + ' HLD</span></span></li>';
  }).join('') + '</ul>', { flush: true }) + '</div>').join('');
  return QK.sectionHead({ kicker: 'Closers', title: 'Saves and holds', sub: 'Projected saves and holds: the club\'s projected saves (holds) times the pitcher\'s share, carried with the persistence fitted on history' +
    (d.fits && d.fits.roles ? ' (' + Math.round(100 * (d.fits.roles.sv || 0)) + '% of a closer\'s share carries to the next season, ' + Math.round(100 * (d.fits.roles.hld || 0)) + '% of a set-up man\'s)' : '') + '; a pitcher who changed clubs keeps 60% of it.' +
    (d.in_season ? '' : ' Between seasons: roles from last season and the moves since.') }) + '<div class="qk-grid">' + cards + '</div>';
}

function stealsHTML(d, HF) {
  const SF = idx(d.steal_fields);
  const byId = {};
  (d.hitters || []).forEach(r => { byId[r[HF.pid]] = r; });
  const rows = (d.steals || []).map(x => { const r = byId[x[SF.pid]] || []; return { pid: x[SF.pid], name: r[HF.name] || BP.playerName(x[SF.pid]), team: r[HF.team], sub: r[HF.team] ? BP.teamAbbr(r[HF.team]) : 'FA', sb: x[SF.sb], last: x[SF.sb_last], att: x[SF.att], succ: x[SF.succ], sprint: x[SF.sprint], pa: x[SF.pa] }; });
  const up = (d.sb_upside || []).map(x => { const r = byId[x[0]] || []; return { pid: x[0], name: r[HF.name] || BP.playerName(x[0]), team: r[HF.team], sub: r[HF.team] ? BP.teamAbbr(r[HF.team]) : 'FA', sprint: x[3], att: x[2], sb: x[1], pa: x[4] }; });
  const ent = { key: 'name', label: 'Hitter', type: 'entity', sub: 'sub', mark: o => (o.team ? BP.ui.team(o.team, 'mlb') : null), href: o => phref(o.pid, 'H') };
  return '<div class="qk-grid"><div class="qk-span-7">' + card('Stolen bases', 'Steals = times on first × attempts per time on first × success; each rate a three-season weighted rate regressed to a prior from sprint speed, times the latest league rate (the 2023 rules raised attempts)',
    rows.length ? board('fx-sb', { dense: true, rank: true, maxHeight: 640, columns: [ent, { key: 'sb', label: 'SB', type: 'bar', fmt: v => n0(v) }, { key: 'last', label: 'Last season', num: true, fmt: v => n0(v) },
      { key: 'att', label: 'Attempts / time on 1st', num: true, fmt: v => (isNum(v) ? BP.pct(v, 1) : '—') }, { key: 'succ', label: 'Success', num: true, fmt: v => (isNum(v) ? BP.pct(v, 0) : '—') },
      { key: 'sprint', label: 'Sprint (ft/s)', num: true, fmt: v => n1(v) }, { key: 'pa', label: 'PA', num: true, fmt: v => n0(v) }], rows: rows }) : QK.empty('Not built yet'), { flush: true }) + '</div>' +
    '<div class="qk-span-5">' + card('Untapped speed', 'Sprint speed 28.5 ft/s or more, an attempt rate under 8% and 300+ PA: a change of club or manager could unlock steals (our projection does not assume it)',
      up.length ? board('fx-up', { dense: true, columns: [ent, { key: 'sprint', label: 'Sprint', num: true, fmt: v => n1(v) }, { key: 'att', label: 'Attempt rate', num: true, fmt: v => (isNum(v) ? BP.pct(v, 1) : '—') }, { key: 'sb', label: 'SB', num: true, fmt: v => n0(v) }], rows: up }) : QK.empty('None'), { flush: true }) + '</div></div>';
}

// ── this week ───────────────────────────────────────────────────────────────

function weekHTML(d) {
  if (!d.in_season) return card('This week', '', QK.empty('Between seasons', 'Next-week projections, two-start and streaming starters return with the regular season. Their backtest (2022 on) is on the Backtest tab.'));
  const SF = idx(d.start_fields);
  const stCols = [{ key: 'name', label: 'Pitcher', type: 'entity', sub: 'sub', href: o => phref(o.pid, 'P') }, { key: 'starts', label: 'Starts', num: true, fmt: v => n0(v) },
    { key: 'pts', label: 'Points', type: 'bar', fmt: v => n1(v) }, { key: 'so', label: 'K', num: true, fmt: v => n1(v) }, { key: 'era', label: 'ERA', num: true, fmt: v => n2(v) }, { key: 'w', label: 'W', num: true, fmt: v => n2(v) }];
  const stRows = list => list.map(x => ({ pid: x[SF.pid], name: x[SF.name], sub: (x[SF.games] || []).map(g => (g[2] ? 'v ' : '@ ') + BP.teamAbbr(g[1]) + ' ' + BP.fmtDate(g[0], { year: false })).join(', '), starts: x[SF.starts], pts: x[SF.pts], so: x[SF.so], era: x[SF.era], w: x[SF.w] }));
  const WF = idx(d.week_fields);
  const hh = (d.week_hitters || []).map(x => ({ pid: x[WF.pid], name: x[WF.name], pts: x[WF.pts], pa: x[WF.pa], hr: x[WF.hr], r: x[WF.r], rbi: x[WF.rbi], sb: x[WF.sb] }));
  return '<div class="qk-grid"><div class="qk-span-6">' + card('Two-start pitchers', 'Next Monday to Sunday, from the probable starters', (d.two_start || []).length ? board('fx-two', { dense: true, columns: stCols, rows: stRows(d.two_start) }) : QK.empty('None yet', 'No probable starter has two starts yet.'), { flush: true }) + '</div>' +
    '<div class="qk-span-6">' + card('Streaming starters', 'Outside our top 150 (a proxy for availability: we have no ownership data), by projected points next week', (d.streaming || []).length ? board('fx-str', { dense: true, columns: stCols, rows: stRows(d.streaming) }) : QK.empty('None yet'), { flush: true }) + '</div>' +
    '<div class="qk-span-12">' + card('Hitters next week', 'Games, lineup slot, the opposing starters\' hands and the parks', hh.length ? board('fx-wh', { dense: true, rank: true, columns: [{ key: 'name', label: 'Hitter', type: 'entity', href: o => phref(o.pid, 'H') },
      { key: 'pts', label: 'Points', type: 'bar', fmt: v => n1(v) }, { key: 'pa', label: 'PA', num: true, fmt: v => n1(v) }, { key: 'hr', label: 'HR', num: true, fmt: v => n1(v) }, { key: 'r', label: 'R', num: true, fmt: v => n1(v) }, { key: 'rbi', label: 'RBI', num: true, fmt: v => n1(v) }, { key: 'sb', label: 'SB', num: true, fmt: v => n1(v) }], rows: hh }) : QK.empty('Not built yet'), { flush: true }) + '</div></div>';
}

// ── backtest ────────────────────────────────────────────────────────────────

function btHTML(bt) {
  if (!bt) return card('Backtest', '', QK.empty('Not built yet', 'The backtest file is not available yet.'));
  const s = bt.summary || {};
  let h = '';
  const NAMES = { r: 'R', hr: 'HR', rbi: 'RBI', sb: 'SB', avg: 'AVG', w: 'W', sv: 'SV', so: 'K', era: 'ERA', whip: 'WHIP', points: 'Points' };
  const tiles = [];
  ['H', 'P'].forEach(k => { const rk = (((s.season || {})[k]) || {}).ranks || {}; if (isNum(rk.points_model)) tiles.push({ label: (k === 'H' ? 'Hitters' : 'Pitchers') + ': rank correlation', value: BP.num(rk.points_model, 2), signal: true, sub: 'points, ours · last season alone ' + BP.num(rk.points_last, 2) }); });
  if (tiles.length) h += '<div class="bp-kpis">' + QK.stats(tiles) + '</div>';
  ['H', 'P'].forEach(k => {
    const x = (s.season || {})[k];
    if (!x) return;
    const cats = Object.keys(x).filter(c => c !== 'ranks');
    const rows = cats.map(c => { const v = x[c]; const better = isNum(v.model) && isNum(v.last) && v.model < v.last; const dp = (c === 'avg' || c === 'era' || c === 'whip') ? 3 : 1;
      return [esc(NAMES[c] || c), { v: v.model, html: (better ? '<strong>' : '') + BP.num(v.model, dp) + (better ? '</strong>' : ''), align: 'right' }, { v: v.last, html: BP.num(v.last, dp), align: 'right' }, { v: v.n, html: BP.int(v.n), align: 'right' }]; });
    const rk = x.ranks || {};
    h += card((k === 'H' ? 'Hitters' : 'Pitchers') + ': season projections (draft)', 'Mean absolute error per player against the official line, ' + Object.keys(bt.by_season ? bt.by_season.season || {} : {}).join(', ') +
      ' (no 2020). Rank correlation with the actual: points ' + BP.num(rk.points_model, 2) + ' (last season ' + BP.num(rk.points_last, 2) + '), 5x5 value ' + BP.num(rk.value_model, 2) + ' (last season ' + BP.num(rk.value_last, 2) + ').',
      BP.tableHTML(['Category', { label: 'Ours', align: 'right' }, { label: 'Last season', align: 'right' }, { label: 'Player-seasons', align: 'right' }], rows, { compact: true }), { flush: true });
  });
  ['H', 'P'].forEach(k => {
    const x = (s.ros || {})[k];
    if (!x) return;
    const rows = Object.keys(x).map(c => { const v = x[c]; return [esc(NAMES[c] || c), { v: v.mae_model, html: BP.num(v.mae_model, 2), align: 'right' }, { v: v.mae_pace, html: BP.num(v.mae_pace, 2), align: 'right' },
      { v: v.rank_model, html: isNum(v.rank_model) ? BP.num(v.rank_model, 2) + ' v ' + BP.num(v.rank_pace, 2) : '', align: 'right' }, { v: v.n, html: BP.int(v.n), align: 'right' }]; });
    h += card((k === 'H' ? 'Hitters' : 'Pitchers') + ': rest of season', 'From 1 June, 1 July and 1 August, 2022 on, against the season-to-date pace',
      BP.tableHTML(['Category', { label: 'MAE ours', align: 'right' }, { label: 'MAE pace', align: 'right' }, { label: 'Rank r ours v pace', align: 'right' }, { label: 'n', align: 'right' }], rows, { compact: true }), { flush: true });
  });
  const w = s.week || {};
  const wr = ['H', 'P'].filter(k => w[k]).map(k => { const v = w[k]; return [k === 'H' ? 'Hitters' : 'Pitchers', { v: v.mae_model, html: BP.num(v.mae_model, 2), align: 'right' }, { v: v.mae_nomatch, html: BP.num(v.mae_nomatch, 2), align: 'right' },
    { v: v.mae_std, html: BP.num(v.mae_std, 2), align: 'right' }, { v: v.rank_model, html: BP.num(v.rank_model, 3), align: 'right' }, { v: v.rank_nomatch, html: BP.num(v.rank_nomatch, 3), align: 'right' },
    { v: v.rank_std, html: BP.num(v.rank_std, 3), align: 'right' }, { v: v.n, html: BP.int(v.n), align: 'right' }]; });
  if (wr.length) {
    const ts = w.two_start;
    h += card('Next week', 'Points per player-week, 2022 on. "No matchups": the same projection without the opposing starter\'s hand and the park; "to date": the season-to-date rate.' +
      (ts ? ' Two-start pitchers scored ' + n1(ts.points_two) + ' points a week on average, one-start pitchers ' + n1(ts.points_one) + '.' : ''),
      BP.tableHTML(['', { label: 'MAE ours', align: 'right' }, { label: 'No matchups', align: 'right' }, { label: 'To date', align: 'right' }, { label: 'Rank r ours', align: 'right' },
        { label: 'No matchups', align: 'right' }, { label: 'To date', align: 'right' }, { label: 'Player-weeks', align: 'right' }], wr, { compact: true }), { flush: true });
  }
  return '<div class="bp-stack">' + h + '</div><p class="bp-note">' + esc((bt.notes || []).join(' ')) + '</p>';
}

// ── scoring ─────────────────────────────────────────────────────────────────

const LABELS = { r: 'Run', rbi: 'RBI', b1: 'Single', d: 'Double', t: 'Triple', hr: 'Home run', bb: 'Walk', hbp: 'Hit by pitch', sb: 'Stolen base', cs: 'Caught stealing', so: 'Strikeout',
  outs: 'Out recorded (3 = an inning)', h: 'Hit allowed', er: 'Earned run', w: 'Win', l: 'Loss', sv: 'Save', hld: 'Hold' };

function scoringHTML(d) {
  const inp = (kind, k) => '<label class="ft-w">' + esc(kind === 'P' && k === 'so' ? 'Strikeout (pitcher)' : kind === 'P' && k === 'bb' ? 'Walk allowed' : kind === 'P' && k === 'hbp' ? 'Hit batter' : LABELS[k] || k) +
    ' <input type="number" step="0.5" data-kind="' + kind + '" data-k="' + k + '" value="' + esc(String(WEIGHTS[kind][k])) + '"></label>';
  return card('Points scoring', 'Kept in this browser; the Rankings tab\'s points use it. The default is our own scheme, not any platform\'s.',
    '<div class="qk-kicker" style="margin:0 0 8px">Hitters</div><div class="ft-ws">' + Object.keys(WEIGHTS.H).map(k => inp('H', k)).join('') + '</div>' +
    '<div class="qk-kicker" style="margin:16px 0 8px">Pitchers</div><div class="ft-ws">' + Object.keys(WEIGHTS.P).map(k => inp('P', k)).join('') + '</div>' +
    '<div style="margin-top:16px"><button type="button" class="qk-btn" id="fx-reset">Reset to the default</button></div>');
}

function wireScoring(d, redraw) {
  document.querySelectorAll('.ft-ws input[data-kind]').forEach(inp => inp.addEventListener('change', () => {
    const v = parseFloat(inp.value);
    if (isNum(v)) { WEIGHTS[inp.dataset.kind][inp.dataset.k] = v; saveWeights(WEIGHTS); }
  }));
  const r = document.getElementById('fx-reset');
  if (r) r.onclick = () => { WEIGHTS = { H: Object.assign({}, d.points.H), P: Object.assign({}, d.points.P) }; saveWeights(WEIGHTS); redraw(); };
}

if (typeof BP.route === 'function') BP.route('fantasy', fantasyPage);
})(window.BP || (window.BP = {}));
