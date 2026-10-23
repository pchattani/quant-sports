/* The Quant Bullpen — the forecast board (#/markets; the old odds board, renamed on Design System 2.0).
 *
 *   games: every upcoming and live game with our forecast, as game cards;
 *   series: each postseason series with our chance to win it;
 *   futures: the World Series, pennants and the awards as chance bars.
 * v3: ours only; the market sits on game pages and the Model page (markets.json is read for our own futures
 * numbers, which it carries beside the market's).
 *
 * Reads mlb/<S>/markets.json (else markets.json), mlb/<S>/season.json (postseason paths when a futures entry
 * carries no model), mlb/<S>/awards.json (award models), and the GAME_CARDs in index.json. */
(function (BP) {
'use strict';

const esc = BP.esc;
const isNum = BP.isNum;

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
function futuresBars(f) {
  const ids = {};
  Object.keys(f.model).forEach(x => { ids[x] = 1; });
  const rows = Object.keys(ids).filter(id => isNum(f.model[id]) && f.model[id] > 0.0005).map(id => ({
    label: f.kind === 'team' ? BP.teamName(id) : BP.playerName(id), p: f.model[id],
    color: f.kind === 'team' ? (BP.teamInfo(id) || {}).colour : null, mark: f.kind === 'team' ? BP.ui.team(id) : null,
    href: f.kind === 'team' ? BP.teamHref(id) : BP.playerHref(id), sub: f.kind === 'team' ? '' : BP.teamAbbr((BP.player(id) || {}).team) }));
  if (!rows.length) return QK.empty('No forecast yet', Object.keys(f.market).length ? 'Our model for this question is not built yet.' : 'Nothing open.');
  return QK.chances(rows, { limit: 12 });
}
function gameCards(cards, L) {
  const list = cards.filter(c => c && !BP.isFinal(c) && BP.ui.fresh(c) && isNum((c.model || {}).p_home)).sort((a, b) => String(a.start || a.date).localeCompare(String(b.start || b.date)));
  if (!list.length) return QK.empty('No games ahead', 'Our next forecasts appear here when the schedule fills in.');
  return '<div class="bp-gc-grid">' + list.map(c => BP.gameCard(c, { level: L, date: true })).join('') + '</div>';
}
function seriesBars(post, L) {
  const list = ((post && post.series) || []).filter(s => s && !s.done && Array.isArray(s.p) && (s.teams || []).length === 2);
  if (!list.length) return QK.empty('No series in play', 'Series chances appear once the postseason starts.');
  return list.map(s => {
    const t = s.teams.map(String);
    const A = BP.ui.team(t[0], L), B = BP.ui.team(t[1], L);
    const pair = BP.ui.pair(t[0], t[1]); A.colour = pair[0]; B.colour = pair[1];
    return '<div class="bp-ser"><div class="bp-ser-h"><b>' + esc((s.round_name || BP.roundLabel(BP.roundKey(s.round)))) + '</b><span>' + esc(BP.teamAbbr(t[0]) + ' ' + (s.wins || [0, 0])[0] + '–' + (s.wins || [0, 0])[1] + ' ' + BP.teamAbbr(t[1])) + ' · best of ' + esc(s.best_of || '') + '</span></div>' +
      QK.wpBar(s.p[0], null, s.p[1], A, B, { colors: pair, label: 'Our series chance' }) + '</div>';
  }).join('');
}
function explainer() {
  return '<div class="mk-explain">' +
    '<p><b>Ours first.</b> Every bar and percentage on this page is our forecast: the plate-appearance game model for games, the bracket simulation for series, pennants and the World Series, and the award models for MVP, Cy Young and Rookie of the Year.</p>' +
    '<p>How our game forecasts have scored is on the <a href="#/calibration">calibration page</a>. For information and entertainment only. <a href="#/disclaimer">Disclaimer &amp; terms</a>.</p></div>';
}

function render(el, params) {
  const L = 'mlb', S = params.season;
  const idx = BP.index() || {};
  el.innerHTML = QK.sectionHead({ kicker: 'Forecast board · MLB ' + S, title: 'Our forecasts, all in one place', sub: 'Every game ahead, every live series and the season-long questions (World Series, pennants, awards), from our models.',
    actions: '<a class="qk-btn" href="' + BP.ghref('postseason') + '">Postseason</a><a class="qk-btn" href="' + BP.ghref('awards') + '">Award races</a>' }) + '<div id="mk-body">' + QK.skeleton('card', 2) + '</div>';
  return BP.loadAll([BP.marketsPath(S), BP.marketsPath(S), BP.ypath('season.json', L, S), BP.ypath('awards.json', L, S)]).then(arr => {
    if (!el.isConnected) return;
    const mk = BP.ok(arr[0]) ? arr[0] : (BP.ok(arr[1]) ? arr[1] : null);
    const season = BP.ok(arr[2]) ? arr[2] : null;
    const post = (season && season.postseason && season.postseason.teams ? Object.assign({}, season.postseason, { series: (idx.postseason || {}).series || season.postseason.series }) : null) || idx.postseason || null;
    const awards = BP.ok(arr[3]) ? arr[3] : null;
    const body = document.getElementById('mk-body');
    const cards = [].concat(idx.today || [], idx.upcoming || []);
    const fut = futures(mk, post, awards).filter(f => Object.keys(f.model).some(k => isNum(f.model[k]) && f.model[k] > 0));
    let html = '<section class="qk-section">' + QK.sectionHead({ kicker: 'Games', title: 'Next up', sub: 'Our win chance for every game ahead, with the probable starters.' }) + gameCards(cards, L) + '</section>';
    html += '<section class="qk-section"><div class="qk-grid"><div class="qk-span-5">' + BP.ui.card2('Series', 'our chance to win each live series', seriesBars(post, L)) + '</div>' +
      '<div class="qk-span-7">' + (fut.length ? BP.ui.card2('Season-long questions', 'our chance', '<div class="qk-seg" id="mk-tabs" role="group" aria-label="Question" style="flex-wrap:wrap;margin-bottom:12px">' + fut.map((f, i) => '<button type="button" aria-pressed="' + (i === 0) + '" data-value="' + esc(f.key) + '">' + esc(f.label) + '</button>').join('') + '</div><div id="mk-panel"></div>')
        : BP.ui.card2('Season-long questions', '', QK.empty('Nothing open', 'No World Series, pennant or award forecast right now.'))) + '</div></div></section>';
    html += '<section class="qk-section">' + BP.ui.card2('How to read this page', 'where each number comes from', explainer()) + '</section>';
    body.innerHTML = html;
    if (fut.length) {
      const show = k => { const f = fut.find(x => x.key === k) || fut[0]; document.getElementById('mk-panel').innerHTML = futuresBars(f); };
      show(fut[0].key);
      QK.seg(document.getElementById('mk-tabs'), show);
    }
    if (cards.some(BP.isLive)) BP.liveRefresh([BP.ypath('markets.json', L, S), 'markets.json'], 90000);
    BP.setMeta(mk && mk.updated_at ? 'Updated ' + esc(BP.fmtStamp(mk.updated_at)) : '');
  });
}

BP.marketFutures = futures;
BP.route('markets', render);
})(window.BP);
