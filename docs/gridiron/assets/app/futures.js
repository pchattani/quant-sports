/* The Quant Gridiron — Season forecasts (#/futures; old #/markets), in the Standings section, on kit v3.
 * Every season question we forecast (Super Bowl, conferences, divisions, playoffs, No. 1 seed, win totals, awards):
 * our chance as chance bars and a table. The market stays off this page (STYLE_GUIDE: the market appears only as a
 * quiet reference on game detail and the Model page); the win-total questions keep the line the prediction markets
 * ask about, as the question. Reads <S>/markets.json (current season). */
(function (GI) {
'use strict';

const QK = window.QK;
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
  if (Array.isArray(list) && list.length) return list.map(r => ({ id: r.team || r.pid || r.id || r.name, name: r.name, team: r.team, pid: r.pid, model: isNum(r.model) ? r.model : r.p_model, market: isNum(r.market) ? r.market : r.p_market }));
  const model = f.model || {}, mk = f.market && typeof f.market === 'object' ? GI.titleProbs(f.market) : {};
  const ids = Object.keys(model);
  Object.keys(mk).forEach(k => { if (ids.indexOf(k) < 0) ids.push(k); });
  return ids.map(id => ({ id: id, model: model[id], market: mk[id] }));
}
function teamMark(t) { return { name: GI.teamName(t), abbr: GI.teamAbbr(t), colour: GI.teamInfo(t).colour }; }
function entity(r, player) {
  if (player) return { html: (r.pid ? GI.playerLink(r.pid, r.name) : esc(r.name || r.id)) + (r.team ? ' <span class="gi-tag">' + esc(GI.teamAbbr(r.team)) + '</span>' : ''), text: (r.name || GI.playerName(r.id)) + (r.team ? ' · ' + GI.teamAbbr(r.team) : ''), colour: r.team ? GI.teamColour(r.team) : null, mark: r.team ? teamMark(r.team) : null, href: r.pid ? GI.playerHref(r.pid) : null };
  if (GI.TEAMS[GI.canonTeam(r.id)]) return { html: GI.teamLink(r.id, { short: true }), text: GI.teamName(r.id), colour: GI.teamColour(r.id), href: GI.teamHref(r.id), mark: teamMark(r.id) };
  return { html: esc(r.id), text: String(r.id) };
}
function totalsRows(wt) {
  return Object.keys(wt || {}).map(t => {
    const x = wt[t] || {}, k = x.kalshi || x.polymarket || {};
    const mean = isNum(x.mean_wins) ? x.mean_wins : null;
    return { team: t, exp: mean, line: k.line, mo: k.model_over };
  }).sort((a, b) => (b.exp || 0) - (a.exp || 0));
}
function view(el, key, f) {
  if (key === 'win_totals') {
    const rows = totalsRows(f);
    const need = r => (isNum(r.line) ? Math.floor(Number(r.line)) + 1 : null);
    const ch = rows.filter(r => isNum(r.mo) && isNum(need(r)));
    el.innerHTML = GI.grid('<div class="qk-span-6">' + (ch.length ? QK.chances(ch.map(r => ({ label: GI.teamName(r.team), sub: need(r) + '+ wins', p: r.mo, color: GI.teamColour(r.team), href: GI.teamHref(r.team), mark: teamMark(r.team) })), { max: 1, oursName: 'Our chance of that many wins' }) : GI.muted('No win-total questions yet.')) + '</div>' +
      '<div class="qk-span-6">' + GI.tableHTML([{ label: 'Team' }, { label: 'Projected wins', align: 'right', title: 'The mean of our simulated seasons' }, { label: 'Question', align: 'right' }, { label: 'Our chance', align: 'right' }],
        rows.map(r => ({ _href: GI.teamHref(r.team), cells: [{ html: GI.teamLink(r.team, { short: true }), v: r.team }, { html: GI.num(r.exp, 1), v: r.exp }, { html: isNum(need(r)) ? need(r) + '+ wins' : '—', v: need(r) },
          { html: '<b class="gi-ours">' + GI.pct(r.mo, 0) + '</b>', v: r.mo }] })), { sticky: true, maxHeight: 640 }) + '</div>') +
      '<p class="gi-cap">Each team’s question is a win total: our chance that they reach it. Full distributions: <a href="' + GI.standingsHref(null, 'wins') + '">Standings → Win totals</a>.</p>';
    GI.sortable(el);
    return;
  }
  const player = !!AWARD[key];
  const rows = rowsOf(f).filter(r => isNum(r.model)).sort((a, b) => (b.model || 0) - (a.model || 0));
  if (!rows.length) { el.innerHTML = GI.muted('We do not forecast this question yet.'); return; }
  el.innerHTML = GI.grid('<div class="qk-span-6">' + QK.chances(rows.map(r => { const e = entity(r, player); return { label: e.text, p: r.model, color: e.colour, href: e.href, mark: e.mark }; }), { limit: 16 }) + '</div>' +
    '<div class="qk-span-6">' + GI.tableHTML([{ label: player ? 'Player' : 'Team' }, { label: 'Our chance', align: 'right' }],
      rows.map(r => { const e = entity(r, player); return { cells: [{ html: e.html, v: e.text }, { html: '<b class="gi-ours">' + GI.pct(r.model, 1) + '</b>', v: r.model }] }; }), { sticky: true, maxHeight: 560 }) + '</div>');
  GI.sortable(el);
}

GI.route('futures', function (el) {
  const S = GI.currentSeason();
  return GI.loadYear('markets.json', S).then(d => {
    if (!el.isConnected) return;
    const head = GI.pageHead('Standings · ' + S, 'Season forecasts', 'Our chances from the season simulation for every season question: titles, divisions, the playoffs, win totals and awards.' + (d && d.updated_at ? ' Updated ' + esc(GI.fmtStamp(d.updated_at)) + '.' : ''));
    const nav = GI.sectionNav('standings', 'futures');
    if (!GI.ok(d)) { el.innerHTML = head + nav + GI.notBuilt('The season forecasts', d); return; }
    const fut = Object.assign({}, d.futures || {});
    if (d.win_totals) fut.win_totals = d.win_totals;
    Object.keys(d.awards || {}).forEach(k => { if (!fut[k] && (d.awards[k] || []).length) fut[k] = d.awards[k]; });
    const keys = Object.keys(fut).filter(k => fut[k] && (Array.isArray(fut[k]) ? fut[k].length : Object.keys(fut[k]).length)).sort((a, b) => orderKey(a) - orderKey(b) || a.localeCompare(b));
    if (!SEL || keys.indexOf(SEL) < 0) SEL = keys[0] || null;
    el.innerHTML = head + nav +
      GI.card('Season questions', 'Our chance as the bar, from the season simulation', keys.length ?
        '<div class="qk-chips scroll" id="fu-chips" role="group" aria-label="Question">' + keys.map(k => '<button type="button" class="qk-chip" data-value="' + esc(k) + '" aria-pressed="' + (k === SEL) + '">' + esc(labelOf(k, fut[k])) + '</button>').join('') + '</div><div id="fu-body" style="margin-top:14px"></div>'
        : GI.muted('No season forecasts yet.')) +
      GI.note('<p><b>Our chance</b> comes from 20,000 simulated seasons (the award forecasts from our player models). How our game forecasts have done, and how they compare with the closing line, is on the <a href="#/calibration">Model page</a>. For information and entertainment only.</p>');
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
