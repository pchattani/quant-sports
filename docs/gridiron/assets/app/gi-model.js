/* The Quant Gridiron — two Model tabs (round 9, 28 Oct 2026; the standing Model order is How it works, How we're doing,
 * Our forecasts v the market, Who moves next, Glossary, Terms):
 *   #/markets       Our forecasts v the market: our chance beside the prediction markets' for the season questions, the
 *                   award races and this week's games, as a reference. The market lives on this page only (and quietly
 *                   on game pages); the rest of the site leads with ours. Reads <S>/markets.json, <S>/awards.json and
 *                   index.json.
 *   #/model/moves   Who moves next: how the movement model has done (GI.MV.modelSection, moved from How we're doing).
 * Older-browser rule: no optional chaining, no nullish coalescing. */
(function (GI) {
'use strict';

const QK = window.QK;
const esc = GI.esc, isNum = GI.isNum;
const QNAME = { sb: 'Super Bowl', conf_afc: 'AFC champion', conf_nfc: 'NFC champion', seed1_afc: 'AFC No. 1 seed', seed1_nfc: 'NFC No. 1 seed', playoffs: 'Make the playoffs' };
const qname = k => QNAME[k] || (/^div_/.test(k) ? GI.titleCase(k.replace(/^div_/, '')).replace(/^(Afc|Nfc)/, x => x.toUpperCase()) : GI.titleCase(k));
const diff = (a, b) => (isNum(a) && isNum(b) ? '<span class="num">' + GI.signed(100 * (a - b), 0) + '</span>' : '—');

GI.route('markets', function (el) {
  const S = GI.currentSeason();
  el.innerHTML = GI.pageHead('Model', 'Our forecasts v the market', 'Our chance beside the prediction markets’, question by question. The market is a reference, not our forecast: it moves with money and news our models read late or not at all. How the two have scored on the same games is on <a href="#/calibration">How we’re doing</a>.') +
    GI.sectionNav('model', 'markets') + '<div id="mk-body">' + QK.skeleton('lines', 4) + '</div>';
  return Promise.all([GI.loadYear('markets.json', S), GI.loadYear('awards.json', S)]).then(res => {
    if (!el.isConnected) return;
    const m = res[0], a = res[1], idx = GI.index() || {};
    const out = [];
    /* this week's games: ours and the market's for the home side, before kick-off */
    const games = (idx.games || []).filter(g => GI.isPre(g) && g.model && isNum(g.model.p_home) && g.market && isNum(g.market.p_home));
    if (games.length) out.push(GI.card('This week’s games', 'Our chance for the home side, and the market’s, before kick-off', '<div id="mk-games"></div>' +
      GI.tableHTML([{ label: 'Game' }, { label: 'Kick-off' }, { label: 'Ours (home)', align: 'right' }, { label: 'Market (home)', align: 'right' }, { label: 'Difference', align: 'right', title: 'Ours minus the market, percentage points' }],
        games.map(g => ({ _href: GI.gameHref(g.game_id), cells: [{ html: GI.matchupLink(g.game_id, g.away, g.home), v: g.game_id }, { html: esc(GI.fmtDate(g.kickoff, { year: false }) + ' ' + GI.fmtTime(g.kickoff)), v: g.kickoff },
          { html: '<b class="gi-ours">' + GI.pct(g.model.p_home, 0) + '</b>', v: g.model.p_home }, { html: GI.pct(g.market.p_home, 0), v: g.market.p_home }, { html: diff(g.model.p_home, g.market.p_home), v: g.model.p_home - g.market.p_home }] })), { sticky: true }), { flush: false }));
    /* the season questions */
    const F = GI.ok(m) ? (m.futures || {}) : {};
    const keys = Object.keys(F).filter(k => Array.isArray(F[k]) && F[k].some(r => isNum(r.model) && isNum(r.market)));
    keys.forEach((k, i) => {
      const rows = F[k].filter(r => isNum(r.model) && isNum(r.market)).sort((x, y) => y.model - x.model).slice(0, k === 'playoffs' ? 32 : 12);
      out.push(GI.card(qname(k), 'Our chance (blue) and the market’s (grey)', (k === 'sb' ? GI.chartBox('mk-sb', Math.max(260, rows.length * 30 + 50), 'Super Bowl: ours and the market') : '') +
        GI.tableHTML([{ label: 'Team' }, { label: 'Ours', align: 'right' }, { label: 'Market', align: 'right' }, { label: 'Difference', align: 'right', title: 'Ours minus the market, percentage points' }],
          rows.map(r => ({ _href: GI.teamHref(r.team), cells: [{ html: GI.teamLink(r.team, { short: true }), v: r.team }, { html: '<b class="gi-ours">' + GI.pct(r.model, 1) + '</b>', v: r.model }, { html: GI.pct(r.market, 1), v: r.market }, { html: diff(r.model, r.market), v: r.model - r.market }] })), { sticky: true, maxHeight: 520 }), { span: i === 0 ? 12 : 6, flush: false }));
    });
    /* the award races */
    const A = GI.ok(a) ? (a.awards || {}) : {};
    Object.keys(A).forEach(k => {
      const c = (A[k].candidates || []).filter(r => isNum(r.p_model) && isNum(r.p_market)).sort((x, y) => y.p_model - x.p_model).slice(0, 8);
      if (!c.length) return;
      out.push(GI.card(esc(A[k].name || k), 'Award race: ours and the market’s', GI.tableHTML([{ label: 'Player' }, { label: 'Ours', align: 'right' }, { label: 'Market', align: 'right' }, { label: 'Difference', align: 'right' }],
        c.map(r => [{ html: r.pid ? GI.playerLink(r.pid, r.name) : esc(r.name), v: r.name }, { html: '<b class="gi-ours">' + GI.pct(r.p_model, 1) + '</b>', v: r.p_model }, { html: GI.pct(r.p_market, 1), v: r.p_market }, { html: diff(r.p_model, r.p_market), v: r.p_model - r.p_market }])), { span: 6 }));
    });
    const srcs = GI.ok(m) && m.sources ? (Array.isArray(m.sources) ? m.sources : Object.keys(m.sources)).map(String).join(', ') : 'Kalshi and Polymarket';
    GI.set('mk-body', out.length ? GI.grid(out.join('')) + '<p class="gi-cap">Market chances: ' + esc(srcs) + ', the latest market reading with the margin taken out' + (GI.ok(m) && m.updated_at ? ', ' + esc(GI.fmtStamp(m.updated_at)) : '') + '. Ours: 20,000 simulated seasons, the game model and our player models. Information and entertainment only.</p>'
      : QK.empty('No market to set beside ours', 'The prediction markets have no open season questions we can match right now.'));
    GI.sortable(el);
    const sb = (F.sb || []).filter(r => isNum(r.model) && isNum(r.market)).sort((x, y) => y.model - x.model).slice(0, 12);
    if (sb.length && document.getElementById('mk-sb')) GI.ch.dumbbell('mk-sb', { rows: sb.map(r => ({ label: GI.teamAbbr(r.team), a: r.model, b: r.market, href: GI.teamHref(r.team) })), aName: 'Ours', bName: 'Market', labelWidth: 60, valName: 'Chance of winning the Super Bowl' });
  });
});

GI.route('movesmodel', function (el) {
  el.innerHTML = GI.pageHead('Model', 'Who moves next: the record', 'How our model of who changes teams has done: the validation, the deciles and the notes. The fan view is on each team page and player page.') + GI.sectionNav('model', 'movesmodel') + '<div id="mv-body">' + QK.skeleton('lines', 4) + '</div>';
  if (!GI.MV) { GI.set('mv-body', QK.empty('Not available', 'The movement model did not load.')); return; }
  return GI.MV.load().then(md => {
    if (!el.isConnected) return;
    if (!md) { GI.set('mv-body', GI.notBuilt('The movement model', null)); return; }
    GI.set('mv-body', GI.MV.modelSection(md));
    GI.MV.drawModel(md);
  });
});

})(window.GI);
