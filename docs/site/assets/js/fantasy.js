/* The Quant Footballer — fantasy: our own FPL-style points, projections, picks and a suggested squad.
 *
 *   #/fantasy   ?l=<league>&v=<rank|gw|fdr|picks|squad|method>&p=<G|D|M|F>&max=<price>&q=<text>&fd=<att|def>
 *
 * Reads data/fantasy/meta.json (scoring, the walk-forward backtest, the leagues) and
 * data/fantasy/<league>.json (players with projections per gameweek, the fixture-difficulty
 * table, the picks and the optimised squad). Method: docs/MODELS.md 11c; payloads:
 * docs/site/UNIFIED_PAYLOADS.md 12. Prices are our own proxy from the value model; official
 * FPL prices and ownership are not used (the Premier League's terms forbid reuse). */
(function (FH) {
'use strict';

const { esc, num, signed, crest, statTile, tableHTML, setHTML, sortableIn, loadSite, clubHref, personHref, rowsOf, normText } = FH;

const POS_LABEL = { G: 'Goalkeeper', D: 'Defender', M: 'Midfielder', F: 'Forward' };
const POS_ORDER = ['G', 'D', 'M', 'F'];
const VIEWS = [['rank', 'Rankings'], ['gw', 'Next gameweek'], ['fdr', 'Fixtures'], ['picks', 'Picks'], ['squad', 'Suggested squad'], ['method', 'Method and backtest']];
const PART_LABEL = { app: 'Minutes', goals: 'Goals', assists: 'Assists', cs: 'Clean sheet', gc: 'Conceded', saves: 'Saves', cards: 'Cards', og_pm: 'OG / pen. miss', dc: 'Def. contribution', bonus: 'Bonus' };
let TOKEN = 0;

function has(v) { return v !== undefined && v !== null && !(typeof v === 'number' && isNaN(v)); }
function n1(v) { return has(v) ? Number(v).toFixed(1) : '—'; }
function pctTxt(v) { return has(v) ? Math.round(v * 100) + '%' : '—'; }
function posBadge(p) { return '<span class="fpos fpos-' + esc(p) + '" title="' + esc(POS_LABEL[p] || p) + '">' + esc(p === 'G' ? 'GK' : p === 'D' ? 'DEF' : p === 'M' ? 'MID' : 'FWD') + '</span>'; }
function playerA(r) { return '<a class="player-link" href="' + esc(personHref(r.id)) + '">' + esc(r.name || ('#' + r.id)) + '</a>'; }
function clubA(r) { return r.tid ? '<a class="team-link" href="' + esc(clubHref(r.tid)) + '">' + crest(r.club || '', 'assets/crests/' + r.tid + '.png') + esc(r.club || '') + '</a>' : esc(r.club || '—'); }
function price(v) { return has(v) ? '£' + Number(v).toFixed(1) : '—'; }

function setQuery(q) {
  Object.keys(q).forEach(k => { if (q[k] === '' || q[k] === undefined || q[k] === null) delete q[k]; });
  const target = '#/fantasy' + FH.queryString(q);
  if (location.hash !== target) history.replaceState(null, '', target);
  FH.STATE.query = q;
}

function renderFantasy() {
  const pane = document.getElementById('tab-fantasy');
  const token = ++TOKEN;
  pane.innerHTML = '<div class="muted">Loading fantasy projections…</div>';
  loadSite('fantasy/meta.json').then(meta => {
    if (token !== TOKEN) return;
    if (!meta || !(meta.leagues || []).length) {
      pane.innerHTML = '<div class="card"><div class="muted">The fantasy payloads are not built yet (data/fantasy/). They arrive with the next hourly build.</div></div>';
      return;
    }
    const q = Object.assign({}, FH.STATE.query || {});
    const leagues = meta.leagues;
    if (!q.l || !leagues.some(x => x.slug === q.l)) q.l = leagues[0].slug;
    loadSite('fantasy/' + q.l + '.json').then(doc => {
      if (token !== TOKEN) return;
      if (!doc) { pane.innerHTML = '<div class="error-banner">No fantasy file for this league.</div>'; return; }
      draw(pane, meta, doc, q);
    });
  }).catch(err => { pane.innerHTML = '<div class="error-banner">Could not load fantasy: ' + esc(err.message) + '</div>'; });
}

function header(meta, doc, q) {
  const bt = meta.backtest || {};
  const m = (bt.methods || {}).model || {};
  const l5 = (bt.methods || {}).last5 || {};
  const gw = (doc.gameweeks || [])[0];
  return '<div class="card"><div class="card-header">Fantasy <span class="card-sub">FPL-style points computed by us from Sofascore\'s match data, projected from our match model\'s expected goals. <a href="#/fantasy?l=' + esc(q.l) + '&v=method">How it works →</a></span></div>' +
    '<div class="controls"><label>League <select class="team-select" id="fa-league">' + meta.leagues.map(x => '<option value="' + esc(x.slug) + '"' + (x.slug === q.l ? ' selected' : '') + '>' + esc(x.name) + '</option>').join('') + '</select></label>' +
    '<div class="scope-chips fa-views">' + VIEWS.map(v => '<button type="button" class="fam-btn' + ((q.v || 'rank') === v[0] ? ' active' : '') + '" data-v="' + v[0] + '">' + esc(v[1]) + '</button>').join('') + '</div></div>' +
    '<div class="kpi-grid">' +
    statTile('Next gameweek', gw ? esc(gw.label) : '—', gw ? gw.n + ' fixtures' : 'no fixtures with a model line') +
    statTile('Players projected', String((doc.rows || []).length), 'current squads of ' + esc(doc.name || '')) +
    statTile('Backtest rank correlation', has(m.spearman_round_mean) ? num(m.spearman_round_mean, 3) : '—', 'per round · last-5 form ' + (has(l5.spearman_round_mean) ? num(l5.spearman_round_mean, 3) : '—')) +
    statTile('Top-20 picks scored', has(m.top20_actual_mean) ? n1(m.top20_actual_mean) + ' pts' : '—', 'a round on average · form picks ' + (has(l5.top20_actual_mean) ? n1(l5.top20_actual_mean) : '—')) +
    '</div><div class="pad vsmall muted-inline">Prices are our own proxy from the player value model (FPL\'s official prices and ownership are not used: the Premier League\'s terms forbid reusing its data). For fun and research, not advice.</div></div>';
}

function draw(pane, meta, doc, q) {
  setQuery(q);
  const rows = rowsOf(doc);
  const byId = {};
  rows.forEach(r => { byId[r.id] = r; });
  pane.innerHTML = header(meta, doc, q) + '<div id="fa-body"></div>';
  const go = nq => { location.hash = '#/fantasy' + FH.queryString(Object.assign({}, nq)); };
  const sel = document.getElementById('fa-league');
  if (sel) sel.addEventListener('change', () => go({ l: sel.value, v: q.v }));
  pane.querySelectorAll('.fa-views [data-v]').forEach(b => b.addEventListener('click', () => go(Object.assign({}, q, { v: b.dataset.v === 'rank' ? undefined : b.dataset.v }))));
  const v = q.v || 'rank';
  if (v === 'gw') drawGW(doc, rows);
  else if (v === 'fdr') drawFDR(doc, q);
  else if (v === 'picks') drawPicks(doc, byId);
  else if (v === 'squad') drawSquad(doc, byId);
  else if (v === 'method') drawMethod(meta, doc);
  else drawRank(doc, rows, q);
}

// ── rankings ────────────────────────────────────────────────────────────────

function formCell(r) {
  if (!r.form_apps) return '<span class="muted-inline">—</span>';
  const d = (r.form_pts || 0) - (r.form_xpts || 0);
  return '<span title="Last five club league matches: ' + n1(r.form_pts) + ' points, ' + n1(r.form_xpts) + ' from the underlying numbers">' + Math.round(r.form_pts || 0) + ' <span class="' + (d >= 0 ? 'vup' : 'vdown') + '">(' + signed(d, 1) + ')</span></span>';
}

function drawRank(doc, rows, q) {
  const body = document.getElementById('fa-body');
  body.innerHTML = '<div class="card"><div class="controls" id="fa-ctl"></div><div id="fa-note" class="pad vsmall muted-inline"></div><div id="fa-table"></div></div>';
  const redraw = () => {
    const qn = q.q ? normText(q.q) : '';
    const maxP = has(q.max) && q.max !== '' ? Number(q.max) : null;
    const list = rows.filter(r => (!q.p || r.pos === q.p) && (maxP === null || (r.price || 0) <= maxP) && (!qn || normText(r.name || '').indexOf(qn) >= 0))
      .sort((a, b) => (b.h5 || 0) - (a.h5 || 0));
    const shown = list.slice(0, 120);
    const gws = doc.gameweeks || [];
    setHTML('fa-note', list.length + ' players' + (list.length > shown.length ? ' (top ' + shown.length + ' shown)' : '') + ' · next 5 = projected points over the next ' + Math.min(5, gws.length) + ' gameweeks; ROS = every remaining gameweek with a model line (' + doc.n_gameweeks + '). Tiers break where the next-5 projection drops sharply within a position. Form: points in the last five club league matches and, in brackets, points above what the underlying numbers (xG, xA, chances conceded) were worth — a big positive number is luck likely to fade.');
    setHTML('fa-table', shown.length ? tableHTML([
      { label: '#', sortable: false }, { label: 'Player' }, { label: 'Club' }, { label: 'Pos', align: 'center' }, { label: 'Price', align: 'right', title: 'Our price proxy (from the value model)' },
      { label: 'Next GW', align: 'right' }, { label: 'Next 5', align: 'right' }, { label: 'ROS', align: 'right', title: 'Rest of season' }, { label: 'Tier', align: 'center' },
      { label: 'xMin', align: 'right', title: 'Expected minutes a match' }, { label: 'P(goal)', align: 'right', title: 'Chance of scoring in the next gameweek' },
      { label: 'CS', align: 'right', title: 'Chance of a clean sheet (60+ minutes) next gameweek' }, { label: 'Season', align: 'right', title: 'Points this season in the league' },
      { label: 'Form (v underlying)', align: 'right' }
    ], shown.map((r, i) => ({ cells: [
      { v: i + 1, cls: 'pos-cell' }, { v: r.name, html: playerA(r) }, { v: r.club || '', html: clubA(r) }, { v: r.pos, html: posBadge(r.pos), align: 'center' },
      { v: r.price || 0, html: price(r.price), align: 'right' }, { v: r.next || 0, html: n1(r.next), align: 'right' },
      { v: r.h5 || 0, html: '<strong>' + n1(r.h5) + '</strong>', align: 'right' }, { v: r.ros || 0, html: n1(r.ros), align: 'right' },
      { v: r.tier || 9, html: '<span class="ftier ftier-' + Math.min(r.tier || 6, 6) + '">' + (r.tier || '—') + '</span>', align: 'center' },
      { v: r.e_min || 0, html: has(r.e_min) ? Math.round(r.e_min) + "'" : '—', align: 'right' }, { v: r.p_goal || 0, html: pctTxt(r.p_goal), align: 'right' },
      { v: r.cs || 0, html: pctTxt(r.cs), align: 'right' }, { v: r.season_pts || 0, html: has(r.season_pts) ? String(r.season_pts) : '—', align: 'right' },
      { v: (r.form_pts || 0) - (r.form_xpts || 0), html: formCell(r), align: 'right' }
    ] })), { sticky: true }) : '<div class="muted">No player clears the filters.</div>');
    sortableIn('fa-table');
  };
  setHTML('fa-ctl', '<div class="scope-chips"><button type="button" class="fam-btn' + (!q.p ? ' active' : '') + '" data-p="">All</button>' +
    POS_ORDER.map(p => '<button type="button" class="fam-btn' + (q.p === p ? ' active' : '') + '" data-p="' + p + '">' + esc(POS_LABEL[p]) + 's</button>').join('') + '</div>' +
    '<label>Max price <input type="number" id="fa-max" min="4" max="15" step="0.5" value="' + esc(q.max || '') + '" style="width:70px"></label>' +
    '<input type="search" id="fa-q" placeholder="Find a player" value="' + esc(q.q || '') + '" style="max-width:180px">');
  document.querySelectorAll('#fa-ctl [data-p]').forEach(b => b.addEventListener('click', () => {
    q.p = b.dataset.p || undefined; setQuery(Object.assign({}, q));
    document.querySelectorAll('#fa-ctl [data-p]').forEach(x => x.classList.toggle('active', x === b)); redraw();
  }));
  let t = null;
  [['fa-max', 'max'], ['fa-q', 'q']].forEach(([id, key]) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('input', () => { clearTimeout(t); t = setTimeout(() => { q[key] = el.value || undefined; setQuery(Object.assign({}, q)); redraw(); }, 300); });
  });
  redraw();
}

// ── next gameweek ───────────────────────────────────────────────────────────

function drawGW(doc, rows) {
  const gw = (doc.gameweeks || [])[0];
  const parts = doc.parts || [];
  const top = rows.slice().sort((a, b) => (b.next || 0) - (a.next || 0)).slice(0, 30);
  const cap = (doc.picks || {}).captain || [];
  const byId = {};
  rows.forEach(r => { byId[r.id] = r; });
  let h = '<div class="card"><div class="card-header">Captain picks <span class="card-sub">' + (gw ? esc(gw.label) : '') + ' · the highest projections for the gameweek (a double gameweek adds both fixtures)</span></div><div class="fa-caps">' +
    cap.map((id, i) => { const r = byId[id]; if (!r) return ''; return '<div class="fa-cap"><div class="fa-cap-rank">' + (i + 1) + '</div><div><div>' + playerA(r) + ' ' + posBadge(r.pos) + '</div><div class="vsmall muted-inline">' + esc(r.club || '') + ' · ' + price(r.price) + '</div></div><div class="fa-cap-pts">' + n1(r.next) + '<span class="vsmall"> pts</span><div class="vsmall muted-inline">goal ' + pctTxt(r.p_goal) + ' · G/A ' + pctTxt(r.p_ga) + '</div></div></div>'; }).join('') + '</div></div>';
  h += '<div class="card"><div class="card-header">Top 30 for the gameweek <span class="card-sub">expected points by scoring component</span></div><div id="fa-gw"></div></div>';
  document.getElementById('fa-body').innerHTML = h;
  setHTML('fa-gw', tableHTML([{ label: 'Player' }, { label: 'Club' }, { label: 'Pos', align: 'center' }, { label: 'Price', align: 'right' }, { label: 'Total', align: 'right' }]
    .concat(parts.map(p => ({ label: PART_LABEL[p] || p, align: 'right' }))),
    top.map(r => ({ cells: [{ v: r.name, html: playerA(r) }, { v: r.club || '', html: clubA(r) }, { v: r.pos, html: posBadge(r.pos), align: 'center' },
      { v: r.price || 0, html: price(r.price), align: 'right' }, { v: r.next || 0, html: '<strong>' + n1(r.next) + '</strong>', align: 'right' }]
      .concat(parts.map((p, i) => { const x = (r.next_parts || [])[i]; return { v: x || 0, html: has(x) ? num(x, 2) : '—', align: 'right' }; })) })), { compact: true }));
  sortableIn('fa-gw');
}

// ── fixture difficulty ──────────────────────────────────────────────────────

function drawFDR(doc, q) {
  const mode = q.fd === 'def' ? 'def' : 'att';
  const gws = (doc.gameweeks || []).slice(0, 6);
  const fdr = (doc.fdr || []).slice().sort((a, b) => mode === 'att' ? (b.xg_for || 0) - (a.xg_for || 0) : (b.cs_sum || 0) - (a.cs_sum || 0));
  const cell = fx => fx.length ? fx.map(x => {
    const rating = mode === 'att' ? x[4] : x[5];
    return '<div class="fdr fdr-' + rating + '" title="' + esc(x[0]) + (x[1] ? ' (home)' : ' (away)') + ': expected goals for ' + num(x[2], 2) + ', against ' + num(x[3], 2) + '">' + esc(String(x[0] || '').slice(0, 3).toUpperCase()) + (x[1] ? '' : ' (a)') +
      '<span>' + num(mode === 'att' ? x[2] : x[3], 1) + '</span></div>';
  }).join('') : '<div class="fdr fdr-blank">—</div>';
  document.getElementById('fa-body').innerHTML = '<div class="card"><div class="card-header">Fixture difficulty <span class="card-sub">the next six gameweeks from the match model\'s expected goals</span></div>' +
    '<div class="controls"><div class="scope-chips"><button type="button" class="fam-btn' + (mode === 'att' ? ' active' : '') + '" data-fd="att">For attackers (goals for)</button><button type="button" class="fam-btn' + (mode === 'def' ? ' active' : '') + '" data-fd="def">For defenders (goals against)</button></div></div>' +
    '<div class="pad vsmall muted-inline">1 (green) is the easiest fifth of the league\'s fixtures, 5 (red) the hardest. Sorted by ' + (mode === 'att' ? 'total expected goals for' : 'expected clean sheets') + ' over the six gameweeks; (a) is away.</div><div class="fdr-wrap">' +
    tableHTML([{ label: 'Club' }, { label: mode === 'att' ? 'xG for' : 'xCS', align: 'right' }].concat(gws.map(g => ({ label: 'GW' + g.gw, title: g.label, sortable: false }))),
      fdr.map(c => ({ cells: [{ v: c.club, html: '<a class="team-link" href="' + esc(clubHref(c.tid)) + '">' + crest(c.club, 'assets/crests/' + c.tid + '.png') + esc(c.club) + '</a>' },
        { v: mode === 'att' ? c.xg_for : c.cs_sum, html: num(mode === 'att' ? c.xg_for : c.cs_sum, 1), align: 'right' }]
        .concat(gws.map((g, i) => ({ v: '', html: cell((c.gws || [])[i] || []) }))) })), { compact: true }) + '</div></div>';
  sortableIn('fa-body');
  document.querySelectorAll('#fa-body [data-fd]').forEach(b => b.addEventListener('click', () => { location.hash = '#/fantasy' + FH.queryString(Object.assign({}, q, { v: 'fdr', fd: b.dataset.fd === 'att' ? undefined : 'def' })); }));
}

// ── picks ───────────────────────────────────────────────────────────────────

function pickList(title, sub, ids, byId, extra) {
  const rs = (ids || []).map(id => byId[id]).filter(Boolean);
  return '<div class="vbest-card"><div class="vbest-head">' + esc(title) + '</div><div class="vsmall muted-inline fa-pick-sub">' + esc(sub) + '</div>' + (rs.length ? '<ol>' + rs.map(r =>
    '<li><div class="vbest-row"><span class="vbest-name">' + playerA(r) + ' ' + posBadge(r.pos) + '</span><span class="vbest-val">' + n1(r.h5) + '</span></div>' +
    '<div class="vbest-sub">' + esc(r.club || '') + ' · ' + price(r.price) + (extra ? ' · ' + extra(r) : '') + '</div></li>').join('') + '</ol>' : '<div class="muted">Nobody fits.</div>') + '</div>';
}

function drawPicks(doc, byId) {
  const p = doc.picks || {};
  const luck = r => 'last 5: ' + Math.round(r.form_pts || 0) + ' pts v ' + n1(r.form_xpts) + ' underlying';
  let h = '<div class="card"><div class="card-header">Our suggested picks <span class="card-sub">from the projections (next five gameweeks in the right-hand number); model suggestions, not advice</span></div><div class="vbest">';
  POS_ORDER.forEach(k => { h += pickList('Best buys: ' + POS_LABEL[k] + 's', 'projected well above what players at their price usually score', (p.buys || {})[k], byId, r => 'xMin ' + Math.round(r.e_min || 0)); });
  h += pickList('Value picks (£6.5 or less)', 'most projected points per pound above the floor', p.value, byId, r => 'xMin ' + Math.round(r.e_min || 0));
  h += pickList('Differentials', 'projected in the top tier but outside the top 15 at their position by points so far (no ownership data: FPL\'s is not used)', p.differentials, byId, r => (r.season_pts || 0) + ' pts so far');
  h += pickList('Transfer out', 'scored well so far, projected well below that over the next five', p.sell, byId, r => (r.season_pts || 0) + ' pts in ' + (r.season_apps || 0) + ' apps');
  h += pickList('Buy low', 'underlying numbers better than the points of the last five (unlucky)', p.buy_low, byId, luck);
  h += pickList('Sell high', 'points well above the underlying numbers of the last five (lucky)', p.sell_high, byId, luck);
  h += '</div></div>';
  document.getElementById('fa-body').innerHTML = h;
}

// ── the squad ───────────────────────────────────────────────────────────────

function drawSquad(doc, byId) {
  const s = doc.squad || {};
  if (!s.xi) { document.getElementById('fa-body').innerHTML = '<div class="card"><div class="muted">No optimised squad this build.</div></div>'; return; }
  const line = (ids, label) => '<div class="fa-line"><div class="fa-line-label">' + esc(label) + '</div><div class="fa-line-players">' + ids.map(id => {
    const r = byId[id]; if (!r) return '';
    const tag = id === s.captain ? ' <span class="chip ok" title="Captain">C</span>' : id === s.vice ? ' <span class="chip" title="Vice-captain">V</span>' : '';
    return '<div class="fa-shirt"><div class="fa-shirt-name">' + playerA(r) + tag + '</div><div class="vsmall muted-inline">' + esc(r.club || '') + '</div><div class="vsmall">' + price(r.price) + ' · ' + n1(r.next) + ' / ' + n1(r.h5) + '</div></div>';
  }).join('') + '</div></div>';
  const xi = s.xi.map(id => byId[id]).filter(Boolean);
  const by = p => xi.filter(r => r.pos === p).map(r => r.id);
  document.getElementById('fa-body').innerHTML = '<div class="card"><div class="card-header">Suggested squad <span class="card-sub">' + esc(s.solver || '') + ' · ' + esc(s.formation || '') + ' · cost ' + price(s.cost) + ' of ' + price(s.budget) + '</span></div>' +
    '<div class="pad vsmall muted-inline">Fifteen players (2 goalkeepers, 5 defenders, 5 midfielders, 3 forwards), at most three from a club, within the budget, chosen to maximise the starting XI\'s projected points over the next ' + (s.horizon || 5) + ' gameweeks (plus a tenth of the bench\'s) and the captain\'s next-gameweek points, as an integer programme. Each card: price · next gameweek / next ' + (s.horizon || 5) + '. XI projected: ' + n1(s.xi_h5) + ' over ' + (s.horizon || 5) + ' gameweeks; ' + n1(s.xi_next) + ' next gameweek with the captain doubled.</div>' +
    '<div class="fa-pitch">' + line(by('G'), 'Goalkeeper') + line(by('D'), 'Defence') + line(by('M'), 'Midfield') + line(by('F'), 'Attack') + '</div>' +
    line(s.bench || [], 'Bench') + '</div>';
}

// ── method ──────────────────────────────────────────────────────────────────

function drawMethod(meta, doc) {
  const bt = meta.backtest || {};
  const ms = bt.methods || {};
  const sc = meta.scoring || {};
  let h = '<div class="card"><div class="card-header">Walk-forward backtest <span class="card-sub">' + (bt.rounds || 0) + ' league rounds, ' + ((bt.player_rounds || 0).toLocaleString('en-US')) + ' player-rounds, every followed league</span></div>';
  if (bt.ok) {
    h += tableHTML([{ label: 'Projection' }, { label: 'MAE', align: 'right', title: 'Mean absolute error of a player\'s points in a round' }, { label: 'RMSE', align: 'right' }, { label: 'Bias', align: 'right' },
      { label: 'Rank corr. per round', align: 'right', title: 'Spearman correlation of projected and actual points among the round\'s players, averaged over rounds' },
      { label: 'Top-20 points', align: 'right', title: 'Actual points of the 20 highest-projected players in a round, on average' }, { label: 'Big-five MAE', align: 'right' }],
    ['model', 'last5', 'std', 'y365'].filter(k => ms[k]).map(k => ({ cells: [{ v: ms[k].label, html: k === 'model' ? '<strong>' + esc(ms[k].label) + '</strong>' : esc(ms[k].label) },
      { v: ms[k].mae, html: num(ms[k].mae, 3), align: 'right' }, { v: ms[k].rmse, html: num(ms[k].rmse, 3), align: 'right' }, { v: ms[k].bias, html: signed(ms[k].bias, 3), align: 'right' },
      { v: ms[k].spearman_round_mean, html: num(ms[k].spearman_round_mean, 3), align: 'right' }, { v: ms[k].top20_actual_mean, html: num(ms[k].top20_actual_mean, 2), align: 'right' },
      { v: ms[k].big5_mae, html: num(ms[k].big5_mae, 3), align: 'right' }] })), { compact: true });
    h += '<div class="pad vsmall muted-inline">Each round is projected from earlier matches only, and the fixture\'s expected goals come from a walk-forward team-strength stand-in (past fixtures keep no model line), so the live projections, which use the match model, should do at least this well. Actual points are computed with the same scoring from the line-ups (0 for a player who did not play). Most players score 1-3 points most weeks, which is why the absolute errors are close; the ranking and the top picks are where a projection earns its keep.</div>';
  } else h += '<div class="muted">No backtest this build: ' + esc(bt.reason || '') + '</div>';
  h += '</div><div class="card"><div class="card-header">Scoring <span class="card-sub">FPL\'s 2025/26 rules applied by us to Sofascore\'s match data</span></div><div class="pad prose-dark"><ul>' +
    '<li>Minutes: ' + esc(sc.minutes || '') + '. Goals: goalkeeper 10, defender 6, midfielder 5, forward 4. Assists 3.</li>' +
    '<li>Clean sheet (60+ minutes, nothing conceded while on the pitch): goalkeeper and defender 4, midfielder 1. ' + esc(sc.goals_conceded || '') + '. ' + esc(sc.saves || '') + '.</li>' +
    '<li>Yellow -1, red -3 (a second yellow counts as the red only), own goal -2, penalty missed -2.</li>' +
    '<li>Defensive contribution: ' + esc(sc.defensive_contribution || '') + '.</li><li>Bonus: ' + esc(sc.bonus || '') + '.</li><li>Not scored: ' + esc(sc.not_scored || '') + '.</li></ul>' +
    '<p>Projection per player and fixture: expected minutes and the chances of playing and of 60+ minutes from his recent share of his club\'s league minutes (60-day half-weight); per-90 rates (180-day weighting, shrunk to the position) of goals and assists (70% expected, 30% actual), saves, cards, bonus and defensive-contribution hits; scaled by the fixture: attacking rates by the team\'s expected goals in the fixture against its average over its remaining fixtures, the clean sheet as exp(-expected goals against), goals conceded and saves from Poisson expectations.</p>' +
    '<p>Prices: our own proxy, each player\'s expected points above replacement next season from the value model, ranked within the league and position and mapped onto FPL-like ranges (goalkeepers £4.0-6.0, defenders £4.0-7.5, midfielders £4.5-13.0, forwards £4.5-14.5). ' + esc(meta.official_data || '') + '</p></div></div>';
  document.getElementById('fa-body').innerHTML = h;
  sortableIn('fa-body');
}

Object.assign(FH.GLOBAL_PAGES, { fantasy: renderFantasy });
})(window.FH);
