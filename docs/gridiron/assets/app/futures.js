/* The Quant Gridiron — Futures v market (#/futures; old #/markets), in the Standings section.
 * Every season market (Super Bowl, conferences, divisions, playoffs, No. 1 seed, win totals, awards)
 * as a model-v-market dumbbell and a table with fair odds; this week's game markets above.
 * Reads <S>/markets.json (current season). */
(function (GI) {
'use strict';

const esc = GI.esc, isNum = GI.isNum;
let SEL = null;
const ORDER = ['sb', 'conf_afc', 'conf_nfc', 'afc', 'nfc', 'playoffs', 'seed1_afc', 'seed1_nfc', 'seed1', 'win_totals', 'mvp', 'opoy', 'dpoy', 'oroy', 'droy', 'cpoy', 'coty'];
const AWARD = { mvp: 'MVP', opoy: 'Offensive Player of the Year', dpoy: 'Defensive Player of the Year', oroy: 'Offensive Rookie of the Year', droy: 'Defensive Rookie of the Year', cpoy: 'Comeback Player of the Year', coty: 'Coach of the Year' };
function labelOf(k, f) {
  if (f && !Array.isArray(f) && (f.label || f.name)) return f.label || f.name;
  if (k === 'sb') return 'Super Bowl';
  if (/^(conf_)?(afc|nfc)$/.test(k)) return k.replace('conf_', '').toUpperCase() + ' champion';
  if (k === 'playoffs') return 'Make the playoffs';
  if (/^seed1/.test(k)) return (k.split('_')[1] || '').toUpperCase() + ' No. 1 seed';
  if (/^div_/.test(k)) return GI.titleCase(k.replace(/^div_/, '')).replace(/^(Afc|Nfc)/, x => x.toUpperCase());
  if (k === 'win_totals') return 'Win totals';
  return AWARD[k] || GI.titleCase(k);
}
function orderKey(k) { const i = ORDER.indexOf(k); return i >= 0 ? i : (/^div_/.test(k) ? 7.5 : 50); }
function rowsOf(f) {
  const list = Array.isArray(f) ? f : (f.rows || f.candidates || []);
  if (Array.isArray(list) && list.length) return list.map(r => ({ id: r.team || r.pid || r.id || r.name, name: r.name, team: r.team, pid: r.pid, model: isNum(r.model) ? r.model : r.p_model, market: isNum(r.market) ? r.market : (isNum(r.price) ? r.price : r.p_market) }));
  const model = f.model || {}, mk = f.market && typeof f.market === 'object' ? GI.titleProbs(f.market) : {};
  const ids = Object.keys(model);
  Object.keys(mk).forEach(k => { if (ids.indexOf(k) < 0) ids.push(k); });
  return ids.map(id => ({ id: id, model: model[id], market: mk[id] }));
}
function entity(r, player) {
  if (player) return { html: (r.pid ? GI.playerLink(r.pid, r.name) : esc(r.name || r.id)) + (r.team ? ' <span class="gi-tag">' + esc(GI.teamAbbr(r.team)) + '</span>' : ''), text: r.name || GI.playerName(r.id), colour: r.team ? GI.teamColour(r.team) : null };
  if (GI.TEAMS[GI.canonTeam(r.id)]) return { html: GI.teamLink(r.id, { short: true }), text: GI.teamName(r.id), colour: GI.teamColour(r.id), href: GI.teamHref(r.id) };
  return { html: esc(r.id), text: String(r.id) };
}
function totalsRows(wt) {
  return Object.keys(wt || {}).map(t => {
    const x = wt[t] || {}, k = x.kalshi || x.polymarket || {};
    const mean = isNum(x.mean_wins) ? x.mean_wins : null;
    return { team: t, exp: mean, line: k.line, mo: k.model_over, ko: k.p_over };
  }).sort((a, b) => (b.exp || 0) - (a.exp || 0));
}
function view(el, key, f) {
  if (key === 'win_totals') {
    const rows = totalsRows(f);
    const hasLine = rows.some(r => isNum(r.line));
    el.innerHTML = (hasLine ? GI.chartBox('fu-chart', Math.max(420, rows.filter(r => isNum(r.mo) && isNum(r.ko)).length * 24 + 40), 'Chance of the over, model against market') : '') +
      GI.tableHTML([{ label: 'Team' }, { label: 'Expected wins', align: 'right' }, { label: 'Line', align: 'right' }, { label: 'Model over', align: 'right' }, { label: 'Market over', align: 'right' }, { label: 'Gap', align: 'right', title: 'Model minus market on the over, points' }],
        rows.map(r => ({ _href: GI.teamHref(r.team), cells: [{ html: GI.teamLink(r.team, { short: true }), v: r.team }, { html: GI.num(r.exp, 1), v: r.exp }, { html: GI.num(r.line, 1), v: r.line },
          { html: GI.pct(r.mo, 0), v: r.mo }, { html: GI.pct(r.ko, 0), v: r.ko }, { html: GI.gapHTML(r.mo, r.ko, 0), v: isNum(r.mo) && isNum(r.ko) ? r.mo - r.ko : null }] })), { sticky: true, maxHeight: 640 }) +
      '<p class="gi-cap">Full distributions: <a href="' + GI.standingsHref(null, 'wins') + '">Standings → Win totals</a>.</p>';
    GI.sortable(el);
    const dm = rows.filter(r => isNum(r.mo) && isNum(r.ko));
    if (dm.length) GI.ch.dumbbell('fu-chart', { rows: dm.map(r => ({ label: GI.teamName(r.team) + ' o' + GI.num(r.line, 1), a: r.mo, b: r.ko, href: GI.teamHref(r.team) })), labelWidth: 170, valName: 'Chance of the over' });
    return;
  }
  const player = !!AWARD[key];
  const rows = rowsOf(f).filter(r => isNum(r.model) || isNum(r.market)).sort((a, b) => (b.model || 0) - (a.model || 0) || (b.market || 0) - (a.market || 0));
  if (!rows.length) { el.innerHTML = GI.muted('No prices for this market yet.'); return; }
  const top = rows.filter(r => isNum(r.model) && isNum(r.market)).slice(0, 16);
  const max = Math.min(1, Math.max.apply(null, top.map(r => Math.max(r.model, r.market)).concat([0.05])) * 1.12);
  el.innerHTML = GI.grid('<div class="qk-span-6">' + (top.length ? GI.chartBox('fu-chart', Math.max(300, top.length * 28 + 40), 'Model against market') : GI.muted('No market prices to compare yet.')) + '</div>' +
    '<div class="qk-span-6">' + GI.tableHTML([{ label: player ? 'Player' : 'Team' }, { label: 'Model', align: 'right' }, { label: 'Market', align: 'right' }, { label: 'Gap', align: 'right', title: 'Model minus market, points: a disagreement, not a recommendation' },
      { label: 'Fair odds', align: 'right', title: 'Our probability as American odds, no margin' }, { label: 'Market odds', align: 'right' }],
      rows.map(r => { const e = entity(r, player); return { cells: [{ html: e.html, v: e.text }, { html: '<b>' + GI.pct(r.model, 1) + '</b>', v: r.model }, { html: GI.pct(r.market, 1), v: r.market },
        { html: GI.gapHTML(r.model, r.market), v: isNum(r.model) && isNum(r.market) ? r.model - r.market : null }, { html: GI.american(r.model), v: r.model }, { html: GI.american(r.market), v: r.market }] }; }), { sticky: true, maxHeight: 560 }) + '</div>');
  GI.sortable(el);
  if (top.length) GI.ch.dumbbell('fu-chart', { rows: top.map(r => { const e = entity(r, player); return { label: e.text, a: r.model, b: r.market, href: e.href }; }), max: max, labelWidth: 160 });
}

GI.route('futures', function (el) {
  const S = GI.currentSeason();
  return GI.loadYear('markets.json', S).then(d => {
    if (!el.isConnected) return;
    const head = GI.pageHead('Standings', 'Futures v market', 'Our season simulation against the de-vigged prediction markets (' + S + ')' + (d && d.updated_at ? ' · updated ' + esc(GI.fmtStamp(d.updated_at)) : ''));
    const nav = GI.sectionNav('standings', 'futures');
    if (!GI.ok(d)) { el.innerHTML = head + nav + GI.notBuilt('Market prices', d); return; }
    const fut = Object.assign({}, d.futures || {});
    if (d.win_totals) fut.win_totals = d.win_totals;
    Object.keys(d.awards || {}).forEach(k => { if (!fut[k] && (d.awards[k] || []).length) fut[k] = d.awards[k]; });
    const keys = Object.keys(fut).filter(k => fut[k] && (Array.isArray(fut[k]) ? fut[k].length : Object.keys(fut[k]).length)).sort((a, b) => orderKey(a) - orderKey(b) || a.localeCompare(b));
    if (!SEL || keys.indexOf(SEL) < 0) SEL = keys[0] || null;
    const games = (d.games || []).filter(g => g && g.market && isNum(g.market.p_home)).sort((a, b) => String(a.kickoff).localeCompare(String(b.kickoff)));
    el.innerHTML = head + nav +
      (d.fetched === false ? GI.note('Market prices were not fetched on this build: the model columns stand alone until they are.') : '') +
      GI.card('Season markets', 'blue model, orange market · ' + esc((Array.isArray(d.sources) ? d.sources : []).join(', ')), keys.length ?
        '<div class="qk-chips scroll" id="fu-chips" role="group" aria-label="Market">' + keys.map(k => '<button type="button" class="qk-chip" data-value="' + esc(k) + '" aria-pressed="' + (k === SEL) + '">' + esc(labelOf(k, fut[k])) + '</button>').join('') + '</div><div id="fu-body" style="margin-top:14px"></div>'
        : GI.muted('No futures markets yet.')) +
      (games.length ? GI.card('Game markets', 'this week\'s games with a market price · <a href="' + GI.weekHref() + '">every game →</a>', GI.mvmTable(games), { flush: true }) : '') +
      GI.note('<p><b>Model</b> is our probability from the game model or the season simulation, with no margin. <b>Market</b> is the price on public prediction markets (Kalshi, Polymarket) with the overround removed in proportion. ' +
        '<b>A gap is a disagreement, not a recommendation:</b> our game model trails the closing line in the backtest (<a href="#/calibration">calibration</a>), and markets carry information the model does not. For information and entertainment only, 18+.</p>');
    GI.sortable(el);
    const body = el.querySelector('#fu-body');
    const chips = el.querySelector('#fu-chips');
    if (body && SEL) {
      QK.chips(chips, v => { SEL = v[0]; view(body, SEL, fut[SEL]); });
      view(body, SEL, fut[SEL]);
    }
  });
});

})(window.GI);
