/* The Quant Gridiron — markets (#/markets).
 *
 * The games on the board (this week and next) with our price against the de-vigged prediction
 * market and the betting line; then the futures: Super Bowl, conference champions, the eight
 * divisions, making the playoffs, the No. 1 seed, regular-season win totals and the awards, each
 * as a chart and a table with the model, the market, the gap and fair odds.
 *
 * Reads data/<S>/markets.json (current season; else data/markets.json): {games: [GAME_CARD-like],
 * futures: {key: {label, kind: 'team'|'player'|'totals', model {id: p}, market {id: p} | TITLE
 * {probs|prices|mid}, sources, binary} | {kind: 'totals', rows: [{team, line, p_over_model,
 * p_over_market, exp_wins}]}}, sources {name: fetched_at}, updated_at}. */
(function (GI) {
'use strict';

const esc = GI.esc;
const isNum = GI.isNum;
let SEL = null;

const ORDER = ['sb', 'afc', 'nfc', 'playoffs', 'seed1', 'win_totals', 'mvp', 'opoy', 'dpoy', 'oroy', 'droy', 'cpoy', 'coty'];
const AWARD = { mvp: 'MVP', opoy: 'Offensive Player of the Year', dpoy: 'Defensive Player of the Year', oroy: 'Offensive Rookie of the Year', droy: 'Defensive Rookie of the Year',
  cpoy: 'Comeback Player of the Year', coty: 'Coach of the Year' };
function labelOf(k, f) {
  if (f && !Array.isArray(f) && (f.label || f.name)) return f.label || f.name;
  if (k === 'sb') return 'Super Bowl winner';
  if (k === 'afc' || k === 'nfc') return k.toUpperCase() + ' champion';
  if (k === 'playoffs') return 'Make the playoffs';
  if (k === 'seed1') return 'No. 1 seed';
  if (/^div_/.test(k)) return GI.titleCase(k.replace(/^div_/, '')).replace(/^(Afc|Nfc)/, x => x.toUpperCase()) + ' winner';
  if (AWARD[k]) return AWARD[k];
  return GI.titleCase(k);
}
GI.marketLabel = k => labelOf(k, null);
function orderKey(k) { const i = ORDER.indexOf(k); return i >= 0 ? i : (/^div_/.test(k) ? 3.5 + GI.DIVISIONS.findIndex(d => 'div_' + d.toLowerCase().replace(/\s+/g, '_') === k) / 100 : 50); }
function entityLabel(id, kind) {
  if (kind === 'player' || /^\d\d-\d{5,}$/.test(String(id))) return { html: GI.playerLink(id) + (GI.player(id).team ? '<span class="pl-team">' + esc(GI.teamAbbr(GI.player(id).team)) + '</span>' : ''), text: GI.playerName(id), colour: GI.playerColour(id) };
  if (GI.TEAMS[GI.canonTeam(id)]) return { html: GI.teamLink(id, { short: true }), text: GI.teamShort(id), colour: GI.teamColour(id) };
  return { html: esc(id), text: String(id), colour: GI.C.accent };
}
function futureRows(f) {
  if (Array.isArray(f)) return f.map(r => ({ id: r.team || r.pid || r.id || r.name, model: isNum(r.model) ? r.model : r.p_model, market: isNum(r.market) ? r.market : (isNum(r.price) ? r.price : r.p_market), raw: r }));
  if (Array.isArray(f.candidates)) return f.candidates.map(r => ({ id: r.pid || r.team || r.name, model: r.p_model, market: r.p_market, score: r.score, name: r.name, team: r.team, raw: r }));
  if (Array.isArray(f.rows)) return f.rows.map(r => ({ id: r.team || r.pid || r.id || r.name, model: isNum(r.model) ? r.model : r.p_model, market: isNum(r.market) ? r.market : r.p_market, raw: r }));
  const model = f.model || {};
  const mkt = f.market && typeof f.market === 'object' && !Array.isArray(f.market) ? f.market : {};
  const market = mkt.probs || mkt.prices || mkt.mid || mkt.available === false ? GI.titleProbs(mkt) : mkt;
  const ids = Object.keys(model);
  Object.keys(market).forEach(k => { if (ids.indexOf(k) < 0) ids.push(k); });
  return ids.map(id => ({ id: id, model: GI.fx ? GI.fx.pOf(model[id]) : model[id], market: GI.fx ? GI.fx.pOf(market[id]) : market[id] }));
}
function futureView(el, key, f) {
  const kind = f.kind || (/^(mvp|opoy|dpoy|oroy|droy|cpoy)$/.test(key) ? 'player' : (key === 'win_totals' ? 'totals' : 'team'));
  const src = (Array.isArray(f) ? [] : (f.sources || (f.market && f.market.sources) || [])).join(' · ');
  if (kind === 'totals') {
    const rows = (f.rows || []).slice().sort((a, b) => (b.exp_wins || 0) - (a.exp_wins || 0));
    const hasLine = rows.some(r => isNum(r.line) || isNum(r.p_over_model) || isNum(r.p_over_market));
    const keepT = (x, i) => hasLine || i === 0 || i === 2;
    el.innerHTML = rows.length ? GI.tableHTML([{ label: 'Team' }, { label: 'Line', align: 'right' }, { label: 'Expected wins', align: 'right', title: 'Model mean' },
      { label: 'Model over', align: 'right' }, { label: 'Market over', align: 'right' }, { label: 'Model − market', align: 'right', title: 'Model minus market on the over, percentage points' }, { label: 'Model side', align: 'right', title: 'The side of the total our model is on: a disagreement, not a recommendation' }].filter(keepT),
    rows.map(r => {
      const mo = isNum(r.p_over_model) ? r.p_over_model : r.model, ko = isNum(r.p_over_market) ? r.p_over_market : r.market;
      const e = isNum(mo) && isNum(ko) ? mo - ko : null;
      return { _href: GI.teamHref(r.team), cells: [{ html: GI.teamLink(r.team, { short: true }), v: r.team }, { html: GI.num(r.line, 1), v: r.line }, { html: GI.num(r.exp_wins, 1), v: r.exp_wins },
        { html: GI.pct(mo, 0), v: mo }, { html: GI.pct(ko, 0), v: ko }, { html: GI.edgeHTML(mo, ko), v: e },
        { html: e === null || Math.abs(e) < 0.005 ? '—' : (e > 0 ? 'Over' : 'Under'), v: e === null ? null : Math.abs(e) }].filter(keepT) };
    }), { compact: true }) + (hasLine ? '' : '<div class="chart-note">Our simulated mean wins; the win-total lines arrive when the markets are fetched. Full distributions: <a href="' + GI.standingsHref() + '?view=wins">Standings → Win totals</a>.</div>') + (src ? '<div class="chart-note">Market: ' + esc(src) + '</div>' : '') : GI.muted('No win-total markets yet.');
    GI.sortable(el);
    return;
  }
  const all = futureRows(f);
  const rows = all.filter(r => isNum(r.model) || isNum(r.market)).sort((a, b) => (b.model || 0) - (a.model || 0) || (b.market || 0) - (a.market || 0));
  if (!rows.length && all.some(r => isNum(r.score))) {
    const sc = all.filter(r => isNum(r.score)).sort((a, b) => b.score - a.score);
    el.innerHTML = GI.tableHTML([{ label: '#', align: 'right' }, { label: kind === 'player' ? 'Player' : 'Team' }, { label: 'Team' }, { label: 'Pos' }, { label: 'Model score', align: 'right', title: 'Our award ranking score (probabilities arrive with the awards model)' }],
      sc.map((r, i) => [i + 1, { html: kind === 'player' && r.id ? GI.playerLink(r.id, r.name ? { name: r.name } : null) : esc(r.name || r.id), v: r.name }, { html: r.team ? GI.teamLink(r.team, { abbr: true }) : '—', v: r.team },
        (r.raw && r.raw.pos) || '—', { html: GI.num(r.score, 1), v: r.score }]), { compact: true }) +
      '<div class="chart-note">A ranking only: no award probabilities or market prices are available yet.</div>';
    GI.sortable(el);
    return;
  }
  if (!rows.length) { el.innerHTML = GI.muted('No prices for this market yet.'); return; }
  const table = GI.tableHTML([{ label: kind === 'player' ? 'Player' : 'Team' }, { label: 'Model', align: 'right' }, { label: 'Market', align: 'right' }, { label: 'Model − market', align: 'right', title: 'Model minus market, percentage points: a disagreement, not a recommendation' },
    { label: 'Fair odds', align: 'right', title: 'Our probability as American odds, no margin' }, { label: 'Market odds', align: 'right', title: 'The de-vigged market as American odds' }],
  rows.map(r => {
    const e = entityLabel(r.id, kind);
    return { cells: [{ html: e.html, v: e.text }, { html: '<b>' + GI.pct(r.model, 1) + '</b>', v: r.model }, { html: GI.pct(r.market, 1), v: r.market },
      { html: GI.edgeHTML(r.model, r.market), v: isNum(r.model) && isNum(r.market) ? r.model - r.market : null }, { html: GI.american(r.model), v: r.model }, { html: GI.american(r.market), v: r.market }] };
  }), { compact: true });
  el.innerHTML = '<div class="mk-grid"><div><div id="mk-bars"></div></div><div class="table-wrap" style="max-height:520px;overflow-y:auto">' + table + '</div></div>' +
    '<div class="chart-note">' + (f.binary ? 'Yes/no market: each team priced on its own (the column does not sum to 100%). ' : '') + 'Bars: our model; tick: the market' + (src ? ' (' + esc(src) + ')' : '') + '.</div>';
  GI.charts.probBars(el.querySelector('#mk-bars'), rows.slice(0, 14).map(r => { const e = entityLabel(r.id, kind); return { label: kind === 'player' ? GI.playerShort(r.id) : GI.teamAbbr(r.id), p: r.model || 0, market: r.market, colour: e.colour }; }), { top: 14 });
  GI.sortable(el);
}

/* Games with a market price first; the unpriced ones behind a collapsed toggle. */
function gamesBody(games) {
  if (!games.length) return GI.muted('No game markets listed right now.');
  const priced = games.filter(g => g.market && isNum(g.market.p_home));
  const rest = games.filter(g => priced.indexOf(g) < 0);
  return (priced.length ? GI.mvmTable(priced, { week: true }) : GI.muted('No game has a market price right now.')) +
    (rest.length ? '<details class="mk-more"><summary>' + rest.length + ' more game' + (rest.length === 1 ? '' : 's') + ' without prices</summary>' + GI.mvmTable(rest, { week: true }) + '</details>' : '');
}
GI.route('markets', function (el) {
  const S = GI.currentSeason();
  return GI.loadYear('markets.json', S).then(d => (GI.ok(d) ? d : GI.load('markets.json').then(d2 => (GI.ok(d2) ? d2 : d)))).then(d => {
    if (!el.isConnected) return;
    const sub = 'our model against prediction markets and the betting line · ' + S;
    if (!GI.ok(d)) { el.innerHTML = GI.pageHead('Markets', esc(sub)) + GI.notBuilt('Market prices', d); return; }
    const srcs = d.sources && typeof d.sources === 'object' && !Array.isArray(d.sources) ? Object.keys(d.sources).map(k => esc(GI.titleCase(k)) + (d.sources[k] ? ' ' + esc(GI.fmtStamp(d.sources[k])) : '')).join(' · ') : '';
    const games = (d.games || []).filter(Boolean).sort((a, b) => String(a.kickoff).localeCompare(String(b.kickoff)));
    const fut = Object.assign({}, d.futures || {});
    if (d.win_totals && !fut.win_totals) {
      const wt = d.win_totals;
      const mean = wd => { let e = 0, t = 0; (wd || []).forEach((v, k) => { e += k * (Number(v) || 0); t += Number(v) || 0; }); return t ? e / t : null; };
      fut.win_totals = Array.isArray(wt.rows) ? wt : { label: 'Regular-season win totals', kind: 'totals', rows: Object.keys(wt).map(t => {
        const x = wt[t] || {};
        return { team: t, exp_wins: isNum(x.mean_wins) ? x.mean_wins : mean(x.win_dist), line: x.line, p_over_model: x.p_over_model, p_over_market: x.p_over_market };
      }) };
    }
    if (d.awards) Object.keys(d.awards).forEach(k => { if (!fut[k] && d.awards[k]) fut[k] = Object.assign({ kind: 'player' }, d.awards[k]); });
    const keys = Object.keys(fut).filter(k => fut[k] && (Array.isArray(fut[k]) ? fut[k].length : (fut[k].model || fut[k].market || fut[k].rows || fut[k].candidates))).sort((a, b) => orderKey(a) - orderKey(b));
    const srcList = Array.isArray(d.sources) ? d.sources.join(', ') : '';
    const notFetched = d.fetched === false ? GI.muted('Market prices were not fetched on this build' + (srcList ? ' (' + esc(srcList) + ')' : '') + ': the model columns stand alone until they are.') : '';
    if (!SEL || keys.indexOf(SEL) < 0) SEL = keys[0] || null;
    const opts = keys.map(k => '<option value="' + esc(k) + '"' + (k === SEL ? ' selected' : '') + '>' + esc(labelOf(k, fut[k])) + '</option>').join('');
    el.innerHTML = GI.pageHead('Markets', esc(sub) + (d.updated_at ? ' · updated ' + esc(GI.fmtStamp(d.updated_at)) : '')) + notFetched +
      GI.card('Games', 'model v market v line' + (srcs ? ' · ' + srcs : ''), gamesBody(games)) +
      GI.card('How to read this page', '', '<div class="mk-explain"><p><b>Model</b> is our probability from the game model or the season simulation, with no margin. <b>Market</b> is the price on public prediction markets (Kalshi, Polymarket) with the overround removed in proportion; where a market lists only a yes price per team, it is shown as listed. <b>Line</b> is the sportsbook line as ESPN shows it.</p>' +
        '<p><b>Model − market</b> is our probability minus the market\'s, in percentage points. <b>A gap is a disagreement, not a recommendation.</b> Our game model trails the closing line: in the backtest its log-loss is worse than the closing moneyline\'s, and gaps between the model and the line have not predicted results. The numbers are on the <a href="#/calibration">calibration page</a>. Markets carry information our model does not. For information and entertainment only, 18+.</p></div>') +
      GI.card('Futures', 'season markets', keys.length ? '<div class="mk-ctl"><label>Market <select id="mk-sel">' + opts + '</select></label>' +
        '<span>' + GI.toggles(keys.filter(k => ['sb', 'afc', 'nfc', 'playoffs', 'win_totals', 'mvp'].indexOf(k) >= 0).map(k => ({ key: k, label: labelOf(k, fut[k]).replace(' winner', '').replace(' champion', '') })), SEL, 'data-mk') + '</span></div><div id="mk-fut"></div>'
        : GI.muted('No futures markets yet.'));
    GI.sortable(el);
    const box = el.querySelector('#mk-fut');
    const show = k => {
      SEL = k;
      const sel = el.querySelector('#mk-sel');
      if (sel) sel.value = k;
      el.querySelectorAll('[data-mk]').forEach(b => b.classList.toggle('active', b.getAttribute('data-mk') === k));
      if (typeof Plotly !== 'undefined') box.querySelectorAll('.js-plotly-plot').forEach(n => { try { Plotly.purge(n); } catch (e) { /* gone */ } });
      futureView(box, k, fut[k]);
    };
    if (box && SEL) {
      el.querySelector('#mk-sel').addEventListener('change', ev => show(ev.target.value));
      el.querySelectorAll('[data-mk]').forEach(b => b.addEventListener('click', () => show(b.getAttribute('data-mk'))));
      show(SEL);
    }
  });
});

})(window.GI);
