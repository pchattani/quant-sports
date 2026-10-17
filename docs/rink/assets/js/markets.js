/* The Quant Rink — markets (#/markets).
 *
 * The games on the board with our price against the de-vigged prediction market and the betting line
 * (moneyline, puck line, total); then the futures: the Stanley Cup, the conferences, the divisions,
 * making the playoffs, the Presidents' Trophy, regular-season points totals and the awards (Hart,
 * Vezina, Norris, Calder, Art Ross, Rocket Richard, Selke), each as a chart and a table with the model,
 * the market, the gap and fair odds.
 *
 * Reads data/<S>/markets.json (current season; else data/markets.json): {games: [GAME_CARD], futures:
 * {key: {label, kind: 'team'|'player'|'totals', model {id: p}, market {id: p} | TITLE {probs|prices|mid},
 * sources, binary} | {kind: 'totals', rows: [{team, line, exp_pts, p_over_model, p_over_market}]}},
 * sources {name: fetched_at}, updated_at}. Futures keys recognised: cup, east, west, div_<name>, playoffs,
 * pres, points, hart, vezina, norris, calder, ross, richard, selke (others are shown by their label). */
(function (RK) {
'use strict';

const esc = RK.esc;
const isNum = RK.isNum;
let SEL = null;

const ORDER = ['cup', 'stanley_cup', 'conference', 'east', 'west', 'division', 'playoffs', 'pres', 'presidents', 'points', 'hart', 'vezina', 'norris', 'calder', 'ross', 'richard', 'selke'];
const AWARD = { hart: 'Hart Trophy (MVP)', vezina: 'Vezina Trophy (best goalie)', norris: 'Norris Trophy (best defenceman)', calder: 'Calder Trophy (best rookie)',
  ross: 'Art Ross Trophy (most points)', richard: 'Rocket Richard Trophy (most goals)', selke: 'Selke Trophy (best defensive forward)', conn_smythe: 'Conn Smythe Trophy' };
const QUICK = ['cup', 'conference', 'east', 'west', 'playoffs', 'points', 'hart'];
function labelOf(k, f) {
  if (f && !Array.isArray(f) && (f.label || f.name)) return f.label || f.name;
  if (k === 'cup' || k === 'stanley_cup') return 'Stanley Cup winner';
  if (k === 'east') return 'Eastern Conference winner';
  if (k === 'west') return 'Western Conference winner';
  if (k === 'playoffs') return 'Make the playoffs';
  if (k === 'pres' || k === 'presidents') return "Presidents' Trophy";
  if (k === 'conference') return 'Conference winner';
  if (k === 'division') return 'Division winner';
  if (k === 'points') return 'Regular-season points';
  if (/^div_/.test(k)) return RK.titleCase(k.replace(/^div_/, '')) + ' Division winner';
  if (AWARD[k]) return AWARD[k];
  return RK.titleCase(k);
}
RK.marketLabel = k => labelOf(k, null);
function orderKey(k) { const i = ORDER.indexOf(k); return i >= 0 ? i : (/^div_/.test(k) ? 3.5 + RK.DIVISIONS.findIndex(d => 'div_' + d.toLowerCase() === k) / 100 : 50); }
function entityLabel(id, kind) {
  if (kind === 'player' || /^\d{7}$/.test(String(id))) return { html: RK.playerLink(id) + (RK.player(id).team ? '<span class="pl-team">' + esc(RK.teamAbbr(RK.player(id).team)) + '</span>' : ''), text: RK.playerName(id), colour: RK.playerColour(id), short: RK.playerShort(id) };
  if (RK.TEAMS[RK.canonTeam(id)]) return { html: RK.teamLink(id, { short: true }), text: RK.teamShort(id), colour: RK.teamColour(id), short: RK.teamAbbr(id) };
  return { html: esc(id), text: String(id), colour: RK.C.accent, short: String(id) };
}
const pOf = v => (isNum(v) ? Number(v) : v && isNum(v.p) ? Number(v.p) : null);
function futureRows(f) {
  if (Array.isArray(f)) return f.map(r => ({ id: r.team || r.pid || r.id || r.name, model: isNum(r.model) ? r.model : r.p_model, market: isNum(r.market) ? r.market : (isNum(r.price) ? r.price : r.p_market) }));
  if (Array.isArray(f.candidates)) return f.candidates.map(r => ({ id: r.pid || r.team || r.name, model: r.p_model, market: r.p_market, score: r.score, name: r.name, team: r.team, raw: r }));
  if (Array.isArray(f.rows)) return f.rows.map(r => ({ id: r.team || r.pid || r.id || r.name, model: isNum(r.model) ? r.model : r.p_model, market: isNum(r.market) ? r.market : r.p_market }));
  const model = f.model || {};
  const mkt = f.market && typeof f.market === 'object' && !Array.isArray(f.market) ? f.market : {};
  const market = mkt.probs || mkt.prices || mkt.mid || mkt.available === false ? RK.titleProbs(mkt) : mkt;
  const ids = Object.keys(model);
  Object.keys(market).forEach(k => { if (ids.indexOf(k) < 0 && k !== 'sources') ids.push(k); });
  return ids.map(id => ({ id: id, model: pOf(model[id]), market: pOf(market[id]) }));
}
function futureView(el, key, f) {
  const kind = f.kind || (AWARD[key] ? 'player' : (key === 'points' ? 'totals' : 'team'));
  const rowsOf = Array.isArray(f) ? f : (Array.isArray(f.rows) ? f.rows : []);
  const src = RK.srcLabel(Array.isArray(f) ? [] : (f.sources || (f.market && f.market.sources) || [])) ||
    RK.srcLabel(rowsOf.reduce((acc, r) => acc.concat(r && r.sources ? r.sources : (r && r.source ? [r.source] : [])), []));
  if (kind === 'totals') {
    const rows = (f.rows || []).slice().sort((a, b) => (b.exp_pts || 0) - (a.exp_pts || 0) || String(a.team).localeCompare(String(b.team)) || (a.points || 0) - (b.points || 0));
    const hasExp = rows.some(r => isNum(r.exp_pts) || isNum(r.mean));
    // markets.json points rows: {team, source, points (the line N), market P(pts >= N), model, edge}
    const hasLine = rows.some(r => isNum(r.line) || isNum(r.points) || isNum(r.p_over_model) || isNum(r.p_over_market));
    el.innerHTML = rows.length ? RK.tableHTML([{ label: 'Team' }, { label: 'Line', align: 'right' }].concat(hasExp ? [{ label: 'Expected points', align: 'right', title: 'Model mean' }] : []).concat([
      { label: 'Model over', align: 'right' }, { label: 'Market over', align: 'right' }, { label: 'Edge', align: 'right', title: 'Model minus market on the over' }, { label: 'Lean', align: 'right' }]),
    rows.map(r => {
      const mo = isNum(r.p_over_model) ? r.p_over_model : r.model, ko = isNum(r.p_over_market) ? r.p_over_market : r.market;
      const e = isNum(mo) && isNum(ko) ? mo - ko : null;
      return { _href: RK.teamHref(r.team), cells: [{ html: RK.teamLink(r.team, { short: true }), v: r.team }, { html: RK.num(isNum(r.line) ? r.line : r.points, isNum(r.line) ? 1 : 0) + (r.source ? '<span class="sub-line">' + esc(RK.srcLabel([r.source])) + '</span>' : ''), v: isNum(r.line) ? r.line : r.points }].concat(hasExp ? [{ html: RK.num(isNum(r.exp_pts) ? r.exp_pts : r.mean, 1), v: r.exp_pts }] : []).concat([
        { html: RK.pct(mo, 0), v: mo }, { html: RK.pct(ko, 0), v: ko }, { html: RK.edgeHTML(mo, ko), v: e },
        { html: e === null || Math.abs(e) < 0.005 ? '—' : (e > 0 ? 'Over' : 'Under'), v: e === null ? null : Math.abs(e) }]) };
    }), { compact: true }) + (hasLine ? '' : '<div class="chart-note">Our simulated mean points; the lines arrive when the markets are fetched. Full distributions: <a href="' + RK.standingsHref() + '?view=odds">Standings → Playoff odds</a>.</div>') +
      (src ? '<div class="chart-note">Market: ' + esc(src) + '</div>' : '') : RK.muted('No points-total markets yet.');
    RK.sortable(el);
    return;
  }
  const all = futureRows(f);
  const rows = all.filter(r => isNum(r.model) || isNum(r.market)).sort((a, b) => (b.model || 0) - (a.model || 0) || (b.market || 0) - (a.market || 0));
  if (!rows.length && all.some(r => isNum(r.score))) {
    const sc = all.filter(r => isNum(r.score)).sort((a, b) => b.score - a.score);
    el.innerHTML = RK.tableHTML([{ label: '#', align: 'right' }, { label: 'Player' }, { label: 'Team' }, { label: 'Pos' }, { label: 'Model score', align: 'right', title: 'Our award ranking score' }],
      sc.map((r, i) => [i + 1, { html: r.id ? RK.playerLink(r.id, r.name ? { name: r.name } : null) : esc(r.name), v: r.name }, { html: r.team ? RK.teamLink(r.team, { abbr: true }) : '—', v: r.team },
        (r.raw && r.raw.pos) || '—', { html: RK.num(r.score, 1), v: r.score }]), { compact: true }) +
      '<div class="chart-note">A ranking only: no award probabilities or market prices are available yet.</div>';
    RK.sortable(el);
    return;
  }
  if (!rows.length) { el.innerHTML = RK.muted('No prices for this market yet.'); return; }
  const table = RK.tableHTML([{ label: kind === 'player' ? 'Player' : 'Team' }, { label: 'Model', align: 'right' }, { label: 'Market', align: 'right' }, { label: 'Edge', align: 'right', title: 'Model minus market, percentage points' },
    { label: 'Fair odds', align: 'right', title: 'Our probability as American odds, no margin' }, { label: 'Market odds', align: 'right', title: 'The de-vigged market as American odds' }],
  rows.map(r => {
    const e = entityLabel(r.id, kind);
    return { cells: [{ html: e.html, v: e.text }, { html: '<b>' + RK.pct(r.model, 1) + '</b>', v: r.model }, { html: RK.pct(r.market, 1), v: r.market },
      { html: RK.edgeHTML(r.model, r.market), v: isNum(r.model) && isNum(r.market) ? r.model - r.market : null }, { html: RK.american(r.model), v: r.model }, { html: RK.american(r.market), v: r.market }] };
  }), { compact: true });
  el.innerHTML = '<div class="mk-grid"><div><div id="mk-bars"></div></div><div class="table-wrap" style="max-height:520px;overflow-y:auto">' + table + '</div></div>' +
    '<div class="chart-note">' + (f.binary ? 'Yes/no market: each team priced on its own (the column does not sum to 100%). ' : '') + 'Bars: our model; tick: the market' + (src ? ' (' + esc(src) + ')' : '') + '.</div>';
  RK.charts.probBars(el.querySelector('#mk-bars'), rows.slice(0, 14).map(r => { const e = entityLabel(r.id, kind); return { label: e.short, p: r.model || 0, market: r.market, colour: e.colour }; }), { top: 14 });
  RK.sortable(el);
}

RK.route('markets', function (el) {
  const S = RK.currentSeason();
  return RK.loadYear('markets.json', S).then(d => (RK.ok(d) ? d : RK.load('markets.json').then(d2 => (RK.ok(d2) ? d2 : d)))).then(d => {
    if (!el.isConnected) return;
    const sub = 'our model against prediction markets and the betting line · ' + RK.seasonLabel(S);
    const idx = RK.index() || {};
    // the games: markets.json first, else index.json today and upcoming
    let games = RK.ok(d) ? (d.games || []).filter(Boolean) : [];
    if (!games.length) games = (idx.today || []).concat(idx.upcoming || []).filter(g => g && !RK.isFinal(g));
    games = games.slice().sort((a, b) => String(a.start).localeCompare(String(b.start)));
    if (!RK.ok(d) && !games.length) { el.innerHTML = RK.pageHead('Markets', esc(sub)) + RK.notBuilt('Market prices', d); return; }
    const srcs = d && d.sources && typeof d.sources === 'object' && !Array.isArray(d.sources) ? Object.keys(d.sources).map(k => esc(RK.titleCase(k)) + (d.sources[k] ? ' ' + esc(RK.fmtStamp(d.sources[k])) : '')).join(' · ')
      : (d && d.sources ? esc(RK.srcLabel(d.sources)) : '');
    const fut = Object.assign({}, (d && d.futures) || {});
    if (d && d.points && !fut.points) fut.points = Array.isArray(d.points) ? { kind: 'totals', rows: d.points } : Object.assign({ kind: 'totals' }, d.points);
    if (d && d.awards) Object.keys(d.awards).forEach(k => { if (!fut[k] && d.awards[k]) fut[k] = Object.assign({ kind: 'player' }, d.awards[k]); });
    const keys = Object.keys(fut).filter(k => fut[k] && (Array.isArray(fut[k]) ? fut[k].length : (fut[k].model || fut[k].market || fut[k].rows || fut[k].candidates))).sort((a, b) => orderKey(a) - orderKey(b));
    const anyMarket = keys.some(k => futureRows(fut[k]).some(r => isNum(r.market)));
    const notFetched = d && (d.fetched === false || (keys.length && !anyMarket)) ? RK.muted('No futures market prices on this build' + (d.note ? ' (' + esc(d.note) + ')' : '') + ': the model columns stand alone until they are fetched.') : '';
    if (!SEL || keys.indexOf(SEL) < 0) SEL = keys[0] || null;
    const opts = keys.map(k => '<option value="' + esc(k) + '"' + (k === SEL ? ' selected' : '') + '>' + esc(labelOf(k, fut[k])) + '</option>').join('');
    const days = [];
    games.forEach(g => { const x = g.date || RK.localDay(g.start); if (days.indexOf(x) < 0) days.push(x); });
    el.innerHTML = RK.pageHead('Markets', esc(sub) + (d && d.updated_at ? ' · updated ' + esc(RK.fmtStamp(d.updated_at)) : '')) + notFetched +
      RK.card('Games', 'model v market v line' + (srcs ? ' · ' + srcs : ''), games.length ? RK.mvmTable(games, { date: days.length > 1 }) +
        '<div class="chart-note">Win probabilities include overtime and the shootout. The puck line is the favourite\'s, with our chance it covers. Where the market column is marked "No-vig line", no prediction market listed the game and the de-vigged sportsbook moneyline stands in.</div>' : RK.muted('No game markets listed right now.')) +
      RK.card('Futures', 'season markets', keys.length ? '<div class="mk-ctl"><label>Market <select id="mk-sel">' + opts + '</select></label>' +
        '<span>' + RK.toggles(keys.filter(k => QUICK.indexOf(k) >= 0).map(k => ({ key: k, label: labelOf(k, fut[k]).replace(' winner', '').replace(' Conference', '').replace('Regular-season p', 'P') })), SEL, 'data-mk') + '</span></div><div id="mk-fut"></div>'
        : RK.muted('No futures markets yet.')) +
      RK.card('How to read this page', '', '<div class="mk-explain"><p><b>Model</b> is our probability from the game model or the season simulation, with no margin. <b>Market</b> is the price on public prediction markets (Kalshi, Polymarket) with the overround removed in proportion; where a market lists only a yes price per team, it is shown as listed. <b>Line</b> is the sportsbook line (moneyline, puck line and total) as ESPN shows it.</p>' +
        '<p><b>Edge</b> is model minus market in percentage points. A gap is a disagreement, not a recommendation: markets carry information our model does not, and the <a href="#/calibration">calibration page</a> shows how often the model has been right. For information and entertainment only, 18+.</p></div>');
    RK.sortable(el);
    const box = el.querySelector('#mk-fut');
    const show = k => {
      SEL = k;
      const sel = el.querySelector('#mk-sel');
      if (sel) sel.value = k;
      el.querySelectorAll('[data-mk]').forEach(b => b.classList.toggle('active', b.getAttribute('data-mk') === k));
      RK.purge(box);
      futureView(box, k, fut[k]);
    };
    if (box && SEL) {
      el.querySelector('#mk-sel').addEventListener('change', ev => show(ev.target.value));
      el.querySelectorAll('[data-mk]').forEach(b => b.addEventListener('click', () => show(b.getAttribute('data-mk'))));
      show(SEL);
    }
  });
});

})(window.RK);
