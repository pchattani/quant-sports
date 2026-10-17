/* The Quant Bullpen — markets (#/markets).
 *
 *   game prices: every upcoming and live game with a market price, the model's win probability
 *     against the de-vigged market (Kalshi, Polymarket) and the DraftKings line, largest gap first;
 *   series prices: postseason series against the market;
 *   futures: World Series, pennants and the awards (MVP, Cy Young, Rookie of the Year), model
 *     against the market, with fair odds;
 *   how to read it: de-vigging, yes/no markets, thin markets, what a gap is (and is not).
 *
 * Reads mlb/<S>/markets.json (else markets.json), mlb/<S>/season.json (postseason path odds when
 * a futures entry carries no model), mlb/<S>/awards.json (award models), and the GAME_CARDs in index.json. */
(function (BP) {
'use strict';

const esc = BP.esc;
const isNum = BP.isNum;

function srcText(sources, extra) {
  const bits = [];
  if (sources && sources.length) bits.push(sources.map(x => '<span class="src-chip">' + esc(x) + '</span>').join(''));
  if (extra && isNum(extra.overround)) bits.push('overround ' + BP.pct(extra.overround, 1));
  if (extra && extra.available === false && extra.reason) bits.push('<span class="thin">' + esc(extra.reason) + '</span>');
  return bits.join(' · ');
}
function awardModel(awards, key) {
  if (!awards) return {};
  const a = awards[key] || (awards.awards || {})[key];
  if (!a) return {};
  const m = a.model || a;
  const out = {};
  Object.keys(m).forEach(p => { const v = m[p]; out[p] = isNum(v) ? Number(v) : (v && isNum(v.p) ? Number(v.p) : null); });
  return out;
}
/* Futures -> [{key, label, kind, model, market, floor, sources, binary, raw}] */
function rowsBlock(key, label, kind, blk) {
  const b = blk || {};
  const t = b.market || {};
  const model = {}, market = {};
  (b.rows || []).forEach(r => { if (isNum(r.model)) model[r.id] = Number(r.model); if (isNum(r.market)) market[r.id] = Number(r.market); });
  if (!Object.keys(market).length) Object.assign(market, BP.titleProbs(t));
  return { key: key, label: label, kind: kind, model: model, market: market, floor: t.floor || [], sources: t.sources || [], binary: !!t.binary, raw: t };
}
const AWARD_LABEL = { al_mvp: 'AL MVP', nl_mvp: 'NL MVP', al_cy: 'AL Cy Young', nl_cy: 'NL Cy Young', al_roy: 'AL Rookie of the Year', nl_roy: 'NL Rookie of the Year',
  mvp_al: 'AL MVP', mvp_nl: 'NL MVP', cy_al: 'AL Cy Young', cy_nl: 'NL Cy Young', roy_al: 'AL Rookie of the Year', roy_nl: 'NL Rookie of the Year' };
function futures(mk, post, awards) {
  if (mk && (mk.champion || mk.pennant || mk.awards) && !mk.futures) {
    const out = [];
    if (mk.champion) out.push(rowsBlock('ws', 'World Series', 'team', mk.champion));
    ['AL', 'NL'].forEach(lg => { if ((mk.pennant || {})[lg]) out.push(rowsBlock(lg.toLowerCase() + '_pennant', lg + ' pennant', 'team', mk.pennant[lg])); });
    Object.keys(mk.awards || {}).forEach(k => out.push(rowsBlock(k, AWARD_LABEL[k] || BP.titleCase(k), 'player', mk.awards[k])));
    return out;
  }
  const fut = (mk && mk.futures) || {};
  const pt = (post && post.teams) || {};
  const out = Object.keys(fut).map(k => {
    const f = fut[k] || {};
    const mkt = f.market || f;
    let model = f.model || {};
    if (!Object.keys(model).length && /^ws|world/.test(k)) Object.keys(pt).forEach(t => { model[t] = pt[t].p_ws; });
    if (!Object.keys(model).length && /pennant/.test(k)) { const lg = /^al/.test(k) ? 'AL' : 'NL'; Object.keys(pt).forEach(t => { if (pt[t].league === lg) model[t] = pt[t].p_pennant; }); }
    if (!Object.keys(model).length && /mvp|cy|roy/.test(k)) model = awardModel(awards, k);
    return { key: k, label: f.label || BP.titleCase(k), kind: f.kind || (/mvp|cy|roy/.test(k) ? 'player' : 'team'), model: model,
      market: BP.titleProbs(mkt), floor: mkt.floor || [], sources: mkt.sources || f.sources || [], binary: !!(mkt.binary || f.binary), raw: mkt };
  });
  const order = k => (/^ws|world/.test(k) ? 0 : /pennant/.test(k) ? 1 : /mvp/.test(k) ? 2 : /cy/.test(k) ? 3 : /roy/.test(k) ? 4 : 5);
  return out.sort((a, b) => order(a.key) - order(b.key) || a.key.localeCompare(b.key));
}
function futuresTable(f) {
  const ids = {};
  Object.keys(f.model).forEach(x => { ids[x] = 1; });
  Object.keys(f.market).forEach(x => { ids[x] = 1; });
  const list = Object.keys(ids).map(id => ({ id: id, model: f.model[id], market: f.market[id], floor: f.floor.indexOf(id) >= 0 }))
    .filter(r => (isNum(r.model) && r.model > 0) || isNum(r.market) || r.floor)
    .sort((a, b) => (b.model || 0) - (a.model || 0) || (b.market || 0) - (a.market || 0)).slice(0, 30);
  if (!list.length) return BP.muted(f.raw && f.raw.available === false ? 'No open market' + (f.raw.reason ? ' (' + esc(f.raw.reason) + ')' : '') + '.' : 'No prices.');
  const max = Math.max.apply(null, list.map(r => Math.max(r.model || 0, r.market || 0))) || 1;
  const who = id => (f.kind === 'team' ? BP.teamLink(id) : BP.playerLink(id, { team: true }));
  return BP.tableHTML([{ label: f.kind === 'team' ? 'Team' : 'Player' }, { label: 'Model', align: 'right' },
    { label: 'Market', align: 'right', title: f.binary ? 'Yes price (mid of bid and ask), not de-vigged' : 'De-vigged market probability' },
    { label: 'Gap', align: 'right', title: 'Model minus market, percentage points' }, { label: 'Fair odds', align: 'right', cls: 'hide-sm', title: 'Model probability as American odds' }],
  list.map(r => [{ v: f.kind === 'team' ? BP.teamName(r.id) : BP.playerName(r.id), html: who(r.id) },
    { v: r.model, html: isNum(r.model) ? BP.probCell(r.model, f.kind === 'team' ? BP.teamColour(r.id) : BP.C.clay, max) : '<span class="muted-inline">—</span>' },
    { v: r.market, html: isNum(r.market) ? BP.pct(r.market, 1) : (r.floor ? '<span class="thin" title="Only a no-bid floor: too thin to read">thin</span>' : '—') },
    { v: isNum(r.model) && isNum(r.market) ? r.model - r.market : null, html: BP.edgeHTML(r.model, r.market) },
    { v: r.model, html: BP.american(r.model) }]), { compact: true });
}
function gameTable(mk, cards, L) {
  const byId = {};
  cards.forEach(c => { if (c && c.gpk) byId[c.gpk] = c; });
  const mg = (mk && mk.games) || [];
  const listMk = Array.isArray(mg) ? mg : Object.keys(mg).map(k => Object.assign({ gpk: k }, mg[k]));
  const ids = listMk.map(x => String(x.gpk));
  cards.forEach(c => { if (c && !BP.isFinal(c) && c.market && isNum(c.market.p_home) && ids.indexOf(String(c.gpk)) < 0) ids.push(String(c.gpk)); });
  const rows = ids.map(id => {
    const x = listMk.find(z => String(z.gpk) === id) || {}, c = byId[id] || {};
    const g = Object.assign({}, x, c);
    if (BP.isFinal(c)) return null;
    const model = isNum((c.model || {}).p_home) ? c.model.p_home : (isNum(x.model) ? Number(x.model) : (x.model || {}).p_home);
    const market = isNum((c.market || {}).p_home) ? c.market.p_home : (isNum(x.market) ? Number(x.market) : (x.market || {}).p_home);
    if (!isNum(model) || !isNum(market)) return null;
    const edge = model - market;
    const homeSide = edge >= 0;
    const side = homeSide ? g.home : g.away;
    const pm = homeSide ? model : 1 - model, pk = homeSide ? market : 1 - market;
    const ln = g.line || {};
    const pl = Array.isArray(ln.ml) ? BP.devigAm(ln.ml) : null;
    const plSide = pl === null ? null : (homeSide ? pl : 1 - pl);
    const src = (c.market && c.market.sources) || x.sources || (x.market && x.market.sources) || [];
    return { abs: Math.abs(edge), cells: [
      { v: g.start || g.date, html: esc(BP.fmtDate(g.start || g.date, { year: false, time: true })), cls: 'hide-sm' },
      { v: BP.teamAbbr(g.away) + BP.teamAbbr(g.home), html: '<a href="' + BP.gameHref(id, L) + '">' + esc(BP.teamAbbr(g.away)) + ' @ ' + esc(BP.teamAbbr(g.home)) + '</a>' + (BP.isLive(g) ? ' <span class="live-dot"></span>' : '') +
        (g.series ? '<div class="sub-line">' + esc(BP.seriesText(g.series, true)) + '</div>' : '') },
      { v: BP.teamName(side), html: BP.teamLink(side, { short: true, level: L }) },
      { v: pm, html: BP.pct(pm, 0), align: 'right' }, { v: pk, html: BP.pct(pk, 0), align: 'right' },
      { v: Math.abs(edge), html: BP.edgeHTML(pm, pk), align: 'right' },
      { v: plSide, html: plSide === null ? '—' : BP.pct(plSide, 0) + ' <span class="muted-inline">' + BP.fmtOdds(homeSide ? ln.ml[0] : ln.ml[1]) + '</span>', align: 'right', cls: 'hide-sm' },
      { v: src.join(','), html: src.map(s => '<span class="src-chip">' + esc(s) + '</span>').join(''), cls: 'hide-sm' }] };
  }).filter(Boolean).sort((a, b) => b.abs - a.abs);
  if (!rows.length) return BP.muted('No upcoming game has a market price right now.');
  return BP.tableHTML([{ label: 'Starts', cls: 'hide-sm' }, { label: 'Game' }, { label: 'Model likes', title: 'The side the model rates above the market' },
    { label: 'Model', align: 'right' }, { label: 'Market', align: 'right' }, { label: 'Gap', align: 'right' },
    { label: 'DraftKings', align: 'right', cls: 'hide-sm', title: 'De-vigged moneyline probability for the same side' }, { label: 'Source', cls: 'hide-sm' }], rows, { compact: true });
}
function seriesTable(mk, post, L) {
  const fromMk = (mk && mk.series) || [];
  const list = (Array.isArray(fromMk) && fromMk.length ? fromMk : ((post && post.series) || []).filter(s => s.market)).map(s => ({
    id: s.id, round: s.round, teams: (s.teams || []).map(String), model: s.model || s.p, market: s.market, sources: s.sources || s.market_sources || [] }));
  const rows = list.filter(s => s.model && s.market && s.teams.length === 2).map(s => {
    const e = s.model[0] - s.market[0];
    const i = e >= 0 ? 0 : 1;
    return { abs: Math.abs(e), cells: [{ v: s.round, html: esc(BP.roundLabel(BP.roundKey(s.round), true)) },
      { v: BP.teamAbbr(s.teams[0]), html: BP.teamLink(s.teams[0], { abbr: true, level: L }) + ' <span class="muted-inline">v</span> ' + BP.teamLink(s.teams[1], { abbr: true, level: L }) },
      { v: BP.teamName(s.teams[i]), html: BP.teamLink(s.teams[i], { short: true, level: L }) },
      { v: s.model[i], html: BP.pct(s.model[i], 0), align: 'right' }, { v: s.market[i], html: BP.pct(s.market[i], 0), align: 'right' },
      { v: Math.abs(e), html: BP.edgeHTML(s.model[i], s.market[i]), align: 'right' },
      { v: s.sources.join(','), html: s.sources.map(x => '<span class="src-chip">' + esc(x) + '</span>').join(''), cls: 'hide-sm' }] };
  }).sort((a, b) => b.abs - a.abs);
  if (!rows.length) return BP.muted('No series is priced right now.');
  return BP.tableHTML([{ label: 'Round' }, { label: 'Series' }, { label: 'Model likes' }, { label: 'Model', align: 'right' }, { label: 'Market', align: 'right' }, { label: 'Gap', align: 'right' }, { label: 'Source', cls: 'hide-sm' }], rows, { compact: true });
}
function explainer() {
  return '<div class="mk-explain">' +
    '<p><b>De-vigging.</b> Prices add up to more than 100% (the overround). We take the middle of each market’s bid and ask, then scale a whole field — every team in a World Series or pennant market, both teams in a game or series — so it sums to 100%. When Kalshi and Polymarket both quote a market we average them. DraftKings moneylines are de-vigged the same way.</p>' +
    '<p><b>Yes/no markets.</b> Award markets are often quoted player by player. Those prices are shown as they are (marked as yes prices), not de-vigged, so they need not add up to 100%.</p>' +
    '<p><b>Thin markets.</b> Long shots often have no bid at all, or only 1¢. Those are marked <span class="thin">thin</span> and left out of the gap: a no-bid floor says nobody is interested, not that the chance is 1%.</p>' +
    '<p><b>Gaps.</b> The gap is the model minus the market, in percentage points. It is not advice: the model can miss a late scratch, an injury, an opener or a tired bullpen, which markets price in fast. The <a href="#/calibration">calibration page</a> shows how the game model has done against the closing lines.</p>' +
    '<p>For information and entertainment only; 18+; gamble responsibly. <a href="#/disclaimer">Disclaimer &amp; terms</a>.</p></div>';
}

function render(el, params) {
  const L = 'mlb', S = params.season;
  const idx = BP.index() || {};
  el.innerHTML = BP.pageHead('Markets', 'The model against Kalshi, Polymarket and the DraftKings line: games, series, the World Series, pennants and awards',
    '<a href="#/calibration">Calibration</a><a href="' + BP.ghref('postseason') + '">Postseason</a><a href="' + BP.ghref('awards') + '">Awards</a>') + '<div id="mk-body"><div class="muted">Loading…</div></div>';
  return BP.loadAll([BP.marketsPath(S), BP.marketsPath(S), BP.ypath('season.json', L, S), BP.ypath('awards.json', L, S)]).then(arr => {
    if (!el.isConnected) return;
    const mk = BP.ok(arr[0]) ? arr[0] : (BP.ok(arr[1]) ? arr[1] : null);
    const season = BP.ok(arr[2]) ? arr[2] : null;
    const post = (season && season.postseason && season.postseason.teams ? season.postseason : null) || idx.postseason || null;
    const awards = BP.ok(arr[3]) ? arr[3] : null;
    const body = document.getElementById('mk-body');
    const cards = [].concat(idx.today || [], idx.upcoming || []);
    const fut = futures(mk, post, awards);
    let html = BP.card('Game prices', 'model against the de-vigged market and DraftKings, largest gap first', '<div id="mk-games">' + gameTable(mk, cards, L) + '</div>');
    html += BP.card('Series prices', 'postseason series', '<div id="mk-series">' + seriesTable(mk, post, L) + '</div>');
    html += fut.length ? BP.card('Futures', 'model against the market', '<div class="toggle-row" id="mk-tabs">' + BP.toggles(fut.map(f => ({ key: f.key, label: f.label })), fut[0].key, 'data-mk') + '</div><div class="section-note" id="mk-sub"></div><div id="mk-panel"></div>')
      : BP.card('Futures', '', mk ? BP.muted('No futures markets are open.') : BP.notBuilt('The markets payload', arr[0] || arr[1]));
    html += BP.card('How to read this page', 'de-vigging, yes/no markets, thin markets and gaps', explainer());
    body.innerHTML = html;
    if (fut.length) {
      const show = k => {
        const f = fut.find(x => x.key === k) || fut[0];
        document.getElementById('mk-panel').innerHTML = futuresTable(f);
        document.getElementById('mk-sub').innerHTML = [srcText(f.sources, f.raw), f.binary ? 'yes prices' : '',
          Object.keys(f.model).length ? '' : 'no model yet: market only'].filter(Boolean).join(' · ');
        BP.sortable(document.getElementById('mk-panel'));
      };
      show(fut[0].key);
      BP.wireToggles(document.getElementById('mk-tabs'), 'data-mk', show);
    }
    BP.sortable(document.getElementById('mk-games'));
    BP.sortable(document.getElementById('mk-series'));
    if (cards.some(BP.isLive)) BP.liveRefresh([BP.ypath('markets.json', L, S), 'markets.json'], 90000);
    BP.setMeta(mk && mk.updated_at ? 'Prices ' + esc(BP.fmtStamp(mk.updated_at)) : '');
  });
}

BP.marketFutures = futures;
BP.route('markets', render);
})(window.BP);
