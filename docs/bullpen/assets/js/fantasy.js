/* The Quant Bullpen — fantasy (#/mlb/fantasy).
 *
 * Tabs: Rankings (5x5 rotisserie values for a 12-team mixed league, or points under an editable scheme; hitters,
 * pitchers or everyone; position, club and name filters; tiers by position), Dynasty (five-season values and the best
 * prospects), Our picks (sleepers, fades, young risers; luck against skills), Closers (projected saves and holds by club),
 * Steals (projected steals, attempt rates, sprint speed, untapped speed), This week (in season: two-start and streaming
 * starters, the best hitters' week), Backtest (the walk-forward checks against the official lines), Scoring (the points
 * weights, kept in this browser).
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

function n0(v) { return isNum(v) ? Math.round(Number(v)).toString() : '—'; }
function n1(v) { return isNum(v) ? Number(v).toFixed(1) : '—'; }
function n2(v) { return isNum(v) ? Number(v).toFixed(2) : '—'; }
function avg(v) { return isNum(v) ? BP.fmtAvg(v) : '—'; }
function plink(pid, name, kind) { return '<a class="ply-link" href="' + BP.playerHref(pid, { level: 'mlb' }) + '">' + esc(name || BP.playerName(pid)) + '</a>'; }
function tlink(tid) { return tid ? BP.teamLink(tid, { level: 'mlb', abbr: true }) : '<span class="muted-inline" title="A free agent, or no club yet">FA</span>'; }
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
function flagsHTML(f) { return (f || []).length ? '<span class="val-why">' + esc(f.join(' · ')) + '</span>' : ''; }

function fantasyPage(el, params) {
  const qy = params.query || {};
  ['tab', 'fmt', 'kind', 'pos'].forEach(k => { if (qy[k] !== undefined) S[k] = qy[k]; });
  el.innerHTML = BP.muted('Loading…');
  if (params.level && params.level !== 'mlb') {
    el.innerHTML = BP.pageHead('Fantasy', 'MLB') + BP.muted('The fantasy layer covers MLB; Triple-A players appear in the dynasty list as prospects. <a href="#/mlb/fantasy">MLB fantasy →</a>');
    return null;
  }
  return Promise.all([BP.load('mlb/fantasy.json'), BP.load('mlb/fantasy_backtest.json')]).then(res => {
    if (!el.isConnected) return;
    const d = BP.ok(res[0]) ? res[0] : null, bt = BP.ok(res[1]) ? res[1] : null;
    const head = BP.pageHead('Fantasy', d ? 'MLB · ' + esc(d.mode) + ' · 5x5 rotisserie and points' : 'MLB', '<a href="#/mlb/value">Player value →</a> <a href="#/mlb/moves">Moves →</a>');
    if (!d) { el.innerHTML = head + BP.notBuilt('The fantasy file', res[0]); return; }
    Object.keys(d.teams || {}).forEach(t => { if (!BP.TEAMS[t] && d.teams[t] && d.teams[t].name) BP.TEAMS[t] = Object.assign({}, d.teams[t]); });
    WEIGHTS = loadWeights(d.points || { H: {}, P: {} });
    const HF = idx(d.h_fields), PF = idx(d.p_fields);
    const tabs = [{ key: 'rank', label: 'Rankings' }, { key: 'dyn', label: 'Dynasty' }, { key: 'picks', label: 'Our picks' }, { key: 'closers', label: 'Closers' },
      { key: 'steals', label: 'Steals' }, { key: 'week', label: 'This week' }, { key: 'bt', label: 'Backtest' }, { key: 'scoring', label: 'Scoring' }];
    const teams = Object.keys(d.teams || {}).sort((a, b) => BP.teamName(a).localeCompare(BP.teamName(b)));
    el.innerHTML = head + (d.in_season ? '' : '<div class="npb-note">Between seasons: the rankings are ' + esc(String(d.target)) + ' draft projections; rest-of-season, next-week, two-start and streaming views return when the season starts.</div>') +
      '<div class="card"><div class="val-controls"><span class="tgl" id="fx-tab">' + BP.toggles(tabs, S.tab) + '</span></div>' +
      '<div class="val-controls" id="fx-filters"><span class="tgl" id="fx-fmt">' + BP.toggles([{ key: '5x5', label: '5x5' }, { key: 'pts', label: 'Points' }], S.fmt) + '</span>' +
      '<span class="tgl" id="fx-kind">' + BP.toggles([{ key: 'all', label: 'All' }, { key: 'H', label: 'Hitters' }, { key: 'P', label: 'Pitchers' }], S.kind) + '</span>' +
      '<label>Position <select id="fx-pos"><option value="">All</option>' + POS_H.concat(['SP', 'RP']).map(p => '<option value="' + p + '"' + (p === S.pos ? ' selected' : '') + '>' + p + '</option>').join('') + '</select></label>' +
      '<label>Club <select id="fx-team"><option value="">All</option>' + teams.map(t => '<option value="' + esc(t) + '"' + (t === S.team ? ' selected' : '') + '>' + esc(BP.teamAbbr(t) + ' · ' + BP.teamShort(t)) + '</option>').join('') + '</select></label>' +
      '<label>Find <input id="fx-q" type="search" placeholder="player…" value="' + esc(S.q) + '"></label></div></div><div id="fx-body"></div>';
    const $ = id => document.getElementById(id);
    const draw = () => {
      $('fx-filters').style.display = (S.tab === 'rank' || S.tab === 'dyn') ? '' : 'none';
      const body = $('fx-body');
      if (S.tab === 'rank') body.innerHTML = rankHTML(d, HF, PF);
      else if (S.tab === 'dyn') body.innerHTML = dynHTML(d, HF, PF);
      else if (S.tab === 'picks') body.innerHTML = picksHTML(d, HF, PF, bt);
      else if (S.tab === 'closers') body.innerHTML = closersHTML(d, PF);
      else if (S.tab === 'steals') body.innerHTML = stealsHTML(d, HF);
      else if (S.tab === 'week') body.innerHTML = weekHTML(d);
      else if (S.tab === 'bt') body.innerHTML = btHTML(bt);
      else body.innerHTML = scoringHTML(d);
      BP.sortable(body);
      if (S.tab === 'scoring') wireScoring(d, draw);
    };
    const upd = () => { history.replaceState(null, '', hashOf()); draw(); };
    BP.wireToggles($('fx-tab'), 'data-k', k => { S.tab = k; upd(); });
    BP.wireToggles($('fx-fmt'), 'data-k', k => { S.fmt = k; upd(); });
    BP.wireToggles($('fx-kind'), 'data-k', k => { S.kind = k; if ((k === 'H' && (S.pos === 'SP' || S.pos === 'RP')) || (k === 'P' && POS_H.indexOf(S.pos) >= 0)) S.pos = ''; upd(); });
    $('fx-pos').onchange = e => { S.pos = e.target.value; upd(); };
    $('fx-team').onchange = e => { S.team = e.target.value; draw(); };
    let timer = null;
    $('fx-q').oninput = e => { S.q = e.target.value; clearTimeout(timer); timer = setTimeout(draw, 200); };
    draw();
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
  let cols, body;
  const lastCell = x => { const l = x.r[x.F.last]; return { v: x.r[x.F.last_rank], html: isNum(x.r[x.F.last_rank]) ? '#' + x.r[x.F.last_rank] : '—', align: 'right' }; };
  if (S.kind === 'all') {
    cols = [{ label: '#', sortable: false }, { label: 'Player' }, { label: 'Pos' }, { label: 'Club' }, { label: 'Age', align: 'right' }, { label: 'Projection' },
      pts ? { label: 'Points', align: 'right' } : { label: '$', align: 'right' }, { label: 'Value', align: 'right', title: '5x5 z-score above replacement at his best position' },
      { label: 'Tier', align: 'right', title: 'Tier within his position (1-D k-means of value)' }, { label: 'Last', align: 'right', title: 'Last season\'s value rank' }, { label: 'Notes' }];
    body = list.slice(0, 500).map((x, i) => { const r = x.r, F = x.F; return [{ v: i + 1, cls: 'pos-cell' }, { v: r[F.name], html: plink(r[F.pid], r[F.name]) },
      { v: x.kind === 'H' ? (r[F.elig] || []).join(' ') : r[F.role], html: esc(x.kind === 'H' ? (r[F.elig] || []).filter(p => p !== 'UT' && p !== 'CI' && p !== 'MI').join(' ') || 'UT' : r[F.role]) },
      { v: BP.teamAbbr(r[F.team]), html: tlink(r[F.team]) }, { v: r[F.age], html: n1(r[F.age]), align: 'right' }, { v: '', html: '<span class="ft-line">' + lineText(x) + '</span>' },
      pts ? { v: x.pts, html: '<strong>' + n0(x.pts) + '</strong>', align: 'right' } : { v: r[F.usd], html: '<strong>$' + n0(r[F.usd]) + '</strong>', align: 'right' },
      { v: r[F.val], html: n2(r[F.val]), align: 'right' }, { v: r[F.tier], html: tierChip(r[F.tier]), align: 'right' }, lastCell(x), { v: '', html: flagsHTML(r[F.flags]) }]; });
  } else if (S.kind === 'H') {
    cols = [{ label: '#', sortable: false }, { label: 'Hitter' }, { label: 'Pos' }, { label: 'Club' }, { label: 'Age', align: 'right' }, { label: 'PA', align: 'right' }, { label: 'R', align: 'right' },
      { label: 'HR', align: 'right' }, { label: 'RBI', align: 'right' }, { label: 'SB', align: 'right' }, { label: 'AVG', align: 'right' }, pts ? { label: 'Points', align: 'right' } : { label: '$', align: 'right' },
      { label: 'Value', align: 'right' }, { label: 'Tier', align: 'right' }, { label: 'Last', align: 'right' }, { label: 'Notes' }];
    body = list.slice(0, 500).map((x, i) => { const r = x.r, F = x.F; return [{ v: i + 1, cls: 'pos-cell' }, { v: r[F.name], html: plink(r[F.pid], r[F.name]) },
      esc((r[F.elig] || []).filter(p => p !== 'UT' && p !== 'CI' && p !== 'MI').join(' ') || 'UT'), { v: BP.teamAbbr(r[F.team]), html: tlink(r[F.team]) }, { v: r[F.age], html: n1(r[F.age]), align: 'right' },
      { v: r[F.pa], html: n0(r[F.pa]), align: 'right' }, { v: r[F.r], html: n0(r[F.r]), align: 'right' }, { v: r[F.hr], html: n0(r[F.hr]), align: 'right' }, { v: r[F.rbi], html: n0(r[F.rbi]), align: 'right' },
      { v: r[F.sb], html: n0(r[F.sb]), align: 'right' }, { v: r[F.avg], html: avg(r[F.avg]), align: 'right' },
      pts ? { v: x.pts, html: '<strong>' + n0(x.pts) + '</strong>', align: 'right' } : { v: r[F.usd], html: '<strong>$' + n0(r[F.usd]) + '</strong>', align: 'right' },
      { v: r[F.val], html: n2(r[F.val]), align: 'right' }, { v: r[F.tier], html: tierChip(r[F.tier]), align: 'right' }, lastCell(x), { v: '', html: flagsHTML(r[F.flags]) }]; });
  } else {
    cols = [{ label: '#', sortable: false }, { label: 'Pitcher' }, { label: 'Role' }, { label: 'Club' }, { label: 'Age', align: 'right' }, { label: 'IP', align: 'right' }, { label: 'GS', align: 'right' },
      { label: 'W', align: 'right' }, { label: 'SV', align: 'right' }, { label: 'K', align: 'right' }, { label: 'ERA', align: 'right' }, { label: 'WHIP', align: 'right' }, { label: 'HLD', align: 'right' },
      pts ? { label: 'Points', align: 'right' } : { label: '$', align: 'right' }, { label: 'Value', align: 'right' }, { label: 'Tier', align: 'right' }, { label: 'Last', align: 'right' }, { label: 'Notes' }];
    body = list.slice(0, 500).map((x, i) => { const r = x.r, F = x.F; return [{ v: i + 1, cls: 'pos-cell' }, { v: r[F.name], html: plink(r[F.pid], r[F.name]) }, esc(r[F.role] || ''),
      { v: BP.teamAbbr(r[F.team]), html: tlink(r[F.team]) }, { v: r[F.age], html: n1(r[F.age]), align: 'right' }, { v: r[F.ip], html: n0(r[F.ip]), align: 'right' }, { v: r[F.gs], html: n0(r[F.gs]), align: 'right' },
      { v: r[F.w], html: n0(r[F.w]), align: 'right' }, { v: r[F.sv], html: n0(r[F.sv]), align: 'right' }, { v: r[F.so], html: n0(r[F.so]), align: 'right' }, { v: r[F.era], html: n2(r[F.era]), align: 'right' },
      { v: r[F.whip], html: n2(r[F.whip]), align: 'right' }, { v: r[F.hld], html: n0(r[F.hld]), align: 'right' },
      pts ? { v: x.pts, html: '<strong>' + n0(x.pts) + '</strong>', align: 'right' } : { v: r[F.usd], html: '<strong>$' + n0(r[F.usd]) + '</strong>', align: 'right' },
      { v: r[F.val], html: n2(r[F.val]), align: 'right' }, { v: r[F.tier], html: tierChip(r[F.tier]), align: 'right' }, lastCell(x), { v: '', html: flagsHTML(r[F.flags]) }]; });
  }
  const lg = d.league || {};
  const sub = list.length + ' players · ' + (pts ? 'points under your scoring (the Scoring tab)' : '5x5 for a ' + (lg.teams || 12) + '-team mixed league, $' + (lg.budget || 260) + ' budget') + (list.length > 500 ? ' · the first 500 shown' : '');
  return BP.card('Rankings', sub, BP.tableHTML(cols, body, { compact: true, sticky: true }) + '<div class="npb-note">' + esc((d.notes || []).join(' ')) + '</div>');
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
  const rows = list.slice(0, 400).map((x, i) => {
    const r = x.r, F = x.F;
    if (x.kind === 'X') return [{ v: i + 1, cls: 'pos-cell' }, { v: r[F.name], html: plink(r[F.pid], r[F.name]) + ' <span class="chip">prospect</span>' }, esc(r[F.pos] || ''), { v: r[F.age], html: n1(r[F.age]), align: 'right' },
      { v: r[F.dyn], html: '<strong>' + n2(r[F.dyn]) + '</strong>', align: 'right' }, { v: null, html: '—', align: 'right' }, { v: r[F.p_value], html: n2(r[F.p_value]) + ' WAR', align: 'right' },
      { v: '', html: '<span class="val-why">' + esc((LV[r[F.level]] || r[F.level]) + ' line, z ' + (isNum(r[F.z]) ? BP.signed(r[F.z], 1) : '—')) + '</span>' }];
    return [{ v: i + 1, cls: 'pos-cell' }, { v: r[F.name], html: plink(r[F.pid], r[F.name]) }, esc(x.kind === 'H' ? ((r[F.elig] || [])[0] || 'UT') : r[F.role]), { v: r[F.age], html: n1(r[F.age]), align: 'right' },
      { v: r[F.dyn], html: '<strong>' + n2(r[F.dyn]) + '</strong>', align: 'right' }, { v: r[F.rank], html: '#' + n0(r[F.rank]), align: 'right' }, { v: r[F.val], html: n2(r[F.val]), align: 'right' },
      { v: '', html: '<span class="ft-line">' + lineText(x) + '</span>' }];
  });
  return BP.card('Dynasty and keepers', 'Five seasons of value: this season\'s 5x5 value above replacement times the player\'s five-season multiplier (expected WAR over five seasons, discounted 8% a year, against next season\'s — aging and attrition included); prospects from the minor-league model, converted at ' + n2(d.war_to_value) + ' value per expected WAR.',
    BP.tableHTML([{ label: '#', sortable: false }, { label: 'Player' }, { label: 'Pos' }, { label: 'Age', align: 'right' }, { label: 'Dynasty', align: 'right' }, { label: 'Redraft', align: 'right' },
      { label: 'This season / prospect', align: 'right' }, { label: 'Projection or line' }], rows, { compact: true, sticky: true }));
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
  const block = (title, sub, list) => BP.card(title, sub, (list || []).length ? BP.tableHTML([{ label: 'Player' }, { label: 'Our rank', align: 'right' }, { label: 'Last season', align: 'right' }, { label: 'Projection' }, { label: 'Why' }],
    list.map(it => { const x = findRow(d, HF, PF, it[0], it[1]); const r = x ? x.r : null; return [{ v: r ? r[x.F.name] : it[1], html: r ? plink(it[1], r[x.F.name]) : esc(it[1]) }, { v: it[2], html: '#' + it[2], align: 'right' },
      { v: it[3], html: isNum(it[3]) ? '#' + it[3] : 'new', align: 'right' }, { v: '', html: x ? '<span class="ft-line">' + lineText(x) + '</span>' : '' }, { v: '', html: flagsHTML(it[4]) }]; }), { compact: true }) : BP.muted('None.'));
  let luck = '';
  if (bt && bt.luck) {
    const L = bt.luck;
    luck = '<div class="npb-note">How much luck carries over: ' + ['H', 'P'].filter(k => L[k]).map(k => (k === 'H' ? 'hitters\' wOBA minus xwOBA' : 'pitchers\' RA9 minus xRA9') + ' against the next season\'s change, slope ' + n2(L[k].slope) + ' (−1: the gap closes fully), r ' + n2(L[k].corr) + ', ' + BP.int(L[k].n) + ' player-seasons').join('; ') + '.</div>';
  }
  return luck + block('Sleepers', 'In our top 150 and at least 60 places better than last season\'s value rank (or new to the majors): buy.', P.sleepers) +
    block('Fades', 'In last season\'s top 100 and at least 60 places worse in ours: sell high or pass.', P.fades) +
    block('Young risers', '25 or younger, in our top 200 and better than last season: dynasty and keeper targets.', P.young);
}

// ── closers and steals ──────────────────────────────────────────────────────

function closersHTML(d, PF) {
  const C = d.closers || {}, CF = idx(d.closer_fields);
  const byId = {};
  (d.pitchers || []).forEach(r => { byId[r[PF.pid]] = r; });
  const teams = Object.keys(C).sort((a, b) => BP.teamName(a).localeCompare(BP.teamName(b)));
  const cards = teams.map(t => '<div class="val-pos"><div class="val-pos-h">' + BP.teamLink(t, { level: 'mlb' }) + '</div><ol>' + C[t].map(x => {
    const r = byId[x[CF.pid]] || [];
    return '<li><span class="val-bn">' + plink(x[CF.pid], r[PF.name]) + '</span><span class="val-bw"><strong>' + n0(x[CF.sv]) + ' SV</strong> <span class="muted-inline">' + n0(x[CF.hld]) + ' HLD</span></span>' +
      '<div class="val-why">' + (isNum(x[CF.sv_share]) && x[CF.sv_share] > 0 ? Math.round(100 * x[CF.sv_share]) + '% of the club\'s saves last season · ' : '') + 'ERA ' + n2(x[CF.era]) + ' · ' + n0(x[CF.so]) + ' K</div></li>';
  }).join('') + '</ol></div>').join('');
  return BP.card('Closers and set-up men', 'Projected saves and holds: the club\'s projected saves (holds) times the pitcher\'s share, carried with the persistence fitted on history' +
    (d.fits && d.fits.roles ? ' (' + Math.round(100 * (d.fits.roles.sv || 0)) + '% of a closer\'s share carries to the next season, ' + Math.round(100 * (d.fits.roles.hld || 0)) + '% of a set-up man\'s)' : '') + '; a pitcher who changed clubs keeps 60% of it. ' +
    (d.in_season ? '' : 'Between seasons: roles from last season and the moves since; they change with signings and spring training.'), '<div class="val-best">' + cards + '</div>');
}

function stealsHTML(d, HF) {
  const SF = idx(d.steal_fields);
  const byId = {};
  (d.hitters || []).forEach(r => { byId[r[HF.pid]] = r; });
  const rows = (d.steals || []).map(x => { const r = byId[x[SF.pid]] || []; return [{ v: r[HF.name], html: plink(x[SF.pid], r[HF.name]) }, { v: BP.teamAbbr(r[HF.team]), html: tlink(r[HF.team]) },
    { v: x[SF.sb], html: '<strong>' + n0(x[SF.sb]) + '</strong>', align: 'right' }, { v: x[SF.sb_last], html: n0(x[SF.sb_last]), align: 'right' }, { v: x[SF.att], html: isNum(x[SF.att]) ? BP.pct(x[SF.att], 1) : '—', align: 'right' },
    { v: x[SF.succ], html: isNum(x[SF.succ]) ? BP.pct(x[SF.succ], 0) : '—', align: 'right' }, { v: x[SF.sprint], html: n1(x[SF.sprint]), align: 'right' }, { v: x[SF.pa], html: n0(x[SF.pa]), align: 'right' }]; });
  const up = (d.sb_upside || []).map(x => { const r = byId[x[0]] || []; return [{ v: r[HF.name], html: plink(x[0], r[HF.name]) }, { v: x[3], html: n1(x[3]), align: 'right' }, { v: x[2], html: isNum(x[2]) ? BP.pct(x[2], 1) : '—', align: 'right' },
    { v: x[1], html: n0(x[1]), align: 'right' }, { v: x[4], html: n0(x[4]), align: 'right' }]; });
  return BP.card('Stolen bases', 'Steals = times on first (singles, walks, hit by pitch) × attempts per time on first × success. Each rate is a three-season weighted rate against its season\'s league rate, regressed to a prior from sprint speed, times the latest league rate (the 2023 rules raised attempts).',
    BP.tableHTML([{ label: 'Hitter' }, { label: 'Club' }, { label: 'SB', align: 'right' }, { label: 'Last season', align: 'right' }, { label: 'Attempts / time on 1st', align: 'right' },
      { label: 'Success', align: 'right' }, { label: 'Sprint (ft/s)', align: 'right' }, { label: 'PA', align: 'right' }], rows, { compact: true })) +
    BP.card('Untapped speed', 'Sprint speed 28.5 ft/s or more, an attempt rate under 8% and 300+ PA: a change of club or manager could unlock steals (our projection does not assume it).',
      up.length ? BP.tableHTML([{ label: 'Hitter' }, { label: 'Sprint', align: 'right' }, { label: 'Attempt rate', align: 'right' }, { label: 'SB', align: 'right' }, { label: 'PA', align: 'right' }], up, { compact: true }) : BP.muted('None.'));
}

// ── this week ───────────────────────────────────────────────────────────────

function weekHTML(d) {
  if (!d.in_season) return BP.card('This week', '', BP.muted('The season is over: next-week projections, two-start and streaming starters return with the regular season. Their backtest (2022 on) is on the Backtest tab.'));
  const SF = idx(d.start_fields);
  const st = list => BP.tableHTML([{ label: 'Pitcher' }, { label: 'Starts', align: 'right' }, { label: 'Opponents' }, { label: 'Points', align: 'right' }, { label: 'K', align: 'right' }, { label: 'ERA', align: 'right' }, { label: 'W', align: 'right' }],
    list.map(x => [{ v: x[SF.name], html: plink(x[SF.pid], x[SF.name]) }, { v: x[SF.starts], html: n0(x[SF.starts]), align: 'right' },
      { v: '', html: (x[SF.games] || []).map(g => (g[2] ? 'v ' : '@ ') + esc(BP.teamAbbr(g[1])) + ' <span class="muted-inline">' + esc(BP.fmtDate(g[0])) + '</span>').join(', ') },
      { v: x[SF.pts], html: '<strong>' + n1(x[SF.pts]) + '</strong>', align: 'right' }, { v: x[SF.so], html: n1(x[SF.so]), align: 'right' }, { v: x[SF.era], html: n2(x[SF.era]), align: 'right' }, { v: x[SF.w], html: n2(x[SF.w]), align: 'right' }]), { compact: true });
  const WF = idx(d.week_fields);
  const hh = (d.week_hitters || []).map(x => [{ v: x[WF.name], html: plink(x[WF.pid], x[WF.name]) }, { v: x[WF.pts], html: '<strong>' + n1(x[WF.pts]) + '</strong>', align: 'right' },
    { v: x[WF.pa], html: n1(x[WF.pa]), align: 'right' }, { v: x[WF.hr], html: n1(x[WF.hr]), align: 'right' }, { v: x[WF.r], html: n1(x[WF.r]), align: 'right' }, { v: x[WF.rbi], html: n1(x[WF.rbi]), align: 'right' }, { v: x[WF.sb], html: n1(x[WF.sb]), align: 'right' }]);
  return BP.card('Two-start pitchers', 'Next Monday to Sunday, from the probable starters', (d.two_start || []).length ? st(d.two_start) : BP.muted('No probable starter has two starts yet.')) +
    BP.card('Streaming starters', 'Outside our top 150 (a proxy for availability: we have no ownership data), by projected points next week', (d.streaming || []).length ? st(d.streaming) : BP.muted('None yet.')) +
    BP.card('Hitters next week', 'Games, lineup slot, the opposing starters\' hands and the parks', hh.length ? BP.tableHTML([{ label: 'Hitter' }, { label: 'Points', align: 'right' }, { label: 'PA', align: 'right' }, { label: 'HR', align: 'right' }, { label: 'R', align: 'right' }, { label: 'RBI', align: 'right' }, { label: 'SB', align: 'right' }], hh, { compact: true }) : BP.muted('Not built.'));
}

// ── backtest ────────────────────────────────────────────────────────────────

function btHTML(bt) {
  if (!bt) return BP.card('Backtest', '', BP.muted('The backtest file is not available yet.'));
  const s = bt.summary || {};
  let h = '';
  const NAMES = { r: 'R', hr: 'HR', rbi: 'RBI', sb: 'SB', avg: 'AVG', w: 'W', sv: 'SV', so: 'K', era: 'ERA', whip: 'WHIP', points: 'Points' };
  ['H', 'P'].forEach(k => {
    const x = (s.season || {})[k];
    if (!x) return;
    const cats = Object.keys(x).filter(c => c !== 'ranks');
    const rows = cats.map(c => { const v = x[c]; const better = isNum(v.model) && isNum(v.last) && v.model < v.last; const dp = (c === 'avg' || c === 'era' || c === 'whip') ? 3 : 1;
      return [esc(NAMES[c] || c), { v: v.model, html: (better ? '<strong>' : '') + BP.num(v.model, dp) + (better ? '</strong>' : ''), align: 'right' }, { v: v.last, html: BP.num(v.last, dp), align: 'right' }, { v: v.n, html: BP.int(v.n), align: 'right' }]; });
    const rk = x.ranks || {};
    h += BP.card((k === 'H' ? 'Hitters' : 'Pitchers') + ': season projections (draft)', 'Mean absolute error per player against the official line, ' + Object.keys(bt.by_season ? bt.by_season.season || {} : {}).join(', ') +
      ' (no 2020). Rank correlation with the actual: points ' + BP.num(rk.points_model, 2) + ' (last season ' + BP.num(rk.points_last, 2) + '), 5x5 value ' + BP.num(rk.value_model, 2) + ' (last season ' + BP.num(rk.value_last, 2) + ').',
      BP.tableHTML(['Category', { label: 'Ours', align: 'right' }, { label: 'Last season', align: 'right' }, { label: 'Player-seasons', align: 'right' }], rows, { compact: true }));
  });
  ['H', 'P'].forEach(k => {
    const x = (s.ros || {})[k];
    if (!x) return;
    const rows = Object.keys(x).map(c => { const v = x[c]; return [esc(NAMES[c] || c), { v: v.mae_model, html: BP.num(v.mae_model, 2), align: 'right' }, { v: v.mae_pace, html: BP.num(v.mae_pace, 2), align: 'right' },
      { v: v.rank_model, html: isNum(v.rank_model) ? BP.num(v.rank_model, 2) + ' v ' + BP.num(v.rank_pace, 2) : '', align: 'right' }, { v: v.n, html: BP.int(v.n), align: 'right' }]; });
    h += BP.card((k === 'H' ? 'Hitters' : 'Pitchers') + ': rest of season', 'From 1 June, 1 July and 1 August, 2022 on, against the season-to-date pace',
      BP.tableHTML(['Category', { label: 'MAE ours', align: 'right' }, { label: 'MAE pace', align: 'right' }, { label: 'Rank r ours v pace', align: 'right' }, { label: 'n', align: 'right' }], rows, { compact: true }));
  });
  const w = s.week || {};
  const wr = ['H', 'P'].filter(k => w[k]).map(k => { const v = w[k]; return [k === 'H' ? 'Hitters' : 'Pitchers', { v: v.mae_model, html: BP.num(v.mae_model, 2), align: 'right' }, { v: v.mae_nomatch, html: BP.num(v.mae_nomatch, 2), align: 'right' },
    { v: v.mae_std, html: BP.num(v.mae_std, 2), align: 'right' }, { v: v.rank_model, html: BP.num(v.rank_model, 3), align: 'right' }, { v: v.rank_nomatch, html: BP.num(v.rank_nomatch, 3), align: 'right' },
    { v: v.rank_std, html: BP.num(v.rank_std, 3), align: 'right' }, { v: v.n, html: BP.int(v.n), align: 'right' }]; });
  if (wr.length) {
    const ts = w.two_start;
    h += BP.card('Next week', 'Points per player-week, 2022 on. "No matchups": the same projection without the opposing starter\'s hand and the park; "to date": the season-to-date rate.' +
      (ts ? ' Two-start pitchers scored ' + n1(ts.points_two) + ' points a week on average, one-start pitchers ' + n1(ts.points_one) + '.' : ''),
      BP.tableHTML(['', { label: 'MAE ours', align: 'right' }, { label: 'No matchups', align: 'right' }, { label: 'To date', align: 'right' }, { label: 'Rank r ours', align: 'right' },
        { label: 'No matchups', align: 'right' }, { label: 'To date', align: 'right' }, { label: 'Player-weeks', align: 'right' }], wr, { compact: true }));
  }
  return h + '<div class="npb-note">' + esc((bt.notes || []).join(' ')) + '</div>';
}

// ── scoring ─────────────────────────────────────────────────────────────────

const LABELS = { r: 'Run', rbi: 'RBI', b1: 'Single', d: 'Double', t: 'Triple', hr: 'Home run', bb: 'Walk', hbp: 'Hit by pitch', sb: 'Stolen base', cs: 'Caught stealing', so: 'Strikeout',
  outs: 'Out recorded (3 = an inning)', h: 'Hit allowed', er: 'Earned run', w: 'Win', l: 'Loss', sv: 'Save', hld: 'Hold' };

function scoringHTML(d) {
  const inp = (kind, k) => '<label class="ft-w">' + esc(kind === 'P' && k === 'so' ? 'Strikeout (pitcher)' : kind === 'P' && k === 'bb' ? 'Walk allowed' : kind === 'P' && k === 'hbp' ? 'Hit batter' : LABELS[k] || k) +
    ' <input type="number" step="0.5" data-kind="' + kind + '" data-k="' + k + '" value="' + esc(String(WEIGHTS[kind][k])) + '"></label>';
  return BP.card('Points scoring', 'Kept in this browser; the Rankings tab\'s points use it. The default is our own scheme, not any platform\'s.',
    '<div class="pad"><div class="val-sn-t">Hitters</div><div class="ft-ws">' + Object.keys(WEIGHTS.H).map(k => inp('H', k)).join('') + '</div>' +
    '<div class="val-sn-t">Pitchers</div><div class="ft-ws">' + Object.keys(WEIGHTS.P).map(k => inp('P', k)).join('') + '</div>' +
    '<button type="button" class="tbtn" id="fx-reset">Reset to the default</button></div>');
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
