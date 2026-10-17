/* The Quant Ace — markets (#/<T>/markets).
 *
 *   match prices: every upcoming and live match with a market price, the model's win
 *     probability against the de-vigged market (Kalshi, Polymarket), sorted by the gap;
 *   futures: tournament winners (model from the draw simulation), Finals qualification and
 *     year-end No. 1 (model from the season simulation), next year's Slams when quoted;
 *   how to read it: de-vigging, thin markets, yes/no markets, what an edge is (and is not).
 *
 * Reads <T>/markets.json, <T>/race.json, the MATCH_CARDs in index.json, and the tournament
 * payload of each event with a winner market. */
(function (TA) {
'use strict';

const esc = TA.esc;

function srcText(t) {
  if (!t) return '';
  const s = t.sources ? (Array.isArray(t.sources) ? t.sources : Object.keys(t.sources)) : Object.keys(t.by_source || {});
  const bits = [];
  if (s.length) bits.push(s.map(x => '<span class="src-chip">' + esc(x) + '</span>').join(''));
  if (TA.isNum(t.overround)) bits.push('overround ' + TA.pct(t.overround, 1));
  else if (TA.isNum(t.implied_total)) bits.push('prices add up to ' + TA.pct(t.implied_total, 0));
  if (t.available === false && t.reason) bits.push('<span class="thin">' + esc(t.reason) + '</span>');
  return bits.join(' · ');
}

/* rows [{pid, model, market, floor}] -> a futures table. */
function futuresTable(T, rows, opts) {
  const o = opts || {};
  const list = rows.filter(r => (TA.isNum(r.model) && r.model > 0) || TA.isNum(r.market) || r.floor)
    .sort((a, b) => (b.model || 0) - (a.model || 0) || (b.market || 0) - (a.market || 0)).slice(0, o.top || 30);
  if (!list.length) return TA.muted(o.empty || 'No prices.');
  const max = Math.max.apply(null, list.map(r => Math.max(r.model || 0, r.market || 0))) || 1;
  return TA.tableHTML([{ label: 'Player' }, { label: 'Model', align: 'right' }, { label: 'Market', align: 'right', title: o.binary ? 'Yes price (mid of bid and ask)' : 'De-vigged market probability' },
    { label: 'Edge', align: 'right', title: 'Model minus market, percentage points' }, { label: 'Fair odds', align: 'right', title: 'Model probability as decimal odds', cls: 'hide-sm' }],
  list.map(r => [{ v: TA.playerName(T, r.pid), html: TA.playerLink(T, r.pid, { rank: true }) }, { v: r.model, html: TA.probCell(r.model, TA.C.ace, max) },
    { v: r.market, html: TA.isNum(r.market) ? TA.pct(r.market, 1) : (r.floor ? '<span class="thin" title="Only a no-bid floor: too thin to read">thin</span>' : '—') },
    { v: TA.isNum(r.model) && TA.isNum(r.market) ? r.model - r.market : null, html: TA.edgeHTML(r.model, r.market) },
    { v: r.model, html: TA.decimal(r.model) }]), { compact: true });
}
function rowsOf(model, t) {
  const mk = TA.titleProbs(t), floor = (t && t.floor) || [];
  const ids = {};
  Object.keys(model || {}).forEach(x => { ids[x] = 1; });
  Object.keys(mk).forEach(x => { ids[x] = 1; });
  return Object.keys(ids).map(p => ({ pid: p, model: (model || {})[p], market: mk[p], floor: floor.indexOf(p) >= 0 }));
}

function matchTable(T, mm, cards) {
  const byId = {};
  cards.forEach(c => { byId[c.id] = c; });
  const ids = Object.keys(mm || {});
  cards.forEach(c => { if (!mm[c.id] && !TA.isFinished(c) && c.market && TA.isNum(c.market.p1) && c.model && TA.isNum(c.model.p1)) ids.push(c.id); });
  const rows = ids.map(id => {
    const x = (mm || {})[id] || {}, c = byId[id] || {};
    const model = TA.isNum(x.model) ? x.model : (c.model || {}).p1;
    const market = TA.isNum(x.market) ? x.market : (c.market || {}).p1;
    if (!TA.isNum(model) || !TA.isNum(market)) return null;
    const p1 = c.p1 || x.p1, p2 = c.p2 || x.p2;
    const edge = model - market;
    const side = edge >= 0 ? p1 : p2;      // the side the model likes more than the market
    const pm = side === p1 ? model : 1 - model, pk = side === p1 ? market : 1 - market;
    const evId = c.event || String(id).replace(/-(Q[123]|R128|R64|R32|R16|RR|QF|SF|BR|F)-.*$/, '');
    return { abs: Math.abs(edge), cells: [
      { v: c.date, html: c.date ? esc(TA.fmtDate(c.date, { year: false, time: true })) : '—', cls: 'hide-sm' },
      { v: TA.playerName(T, p1), html: '<a href="' + TA.matchHref(T, id) + '">' + (p1 ? esc(TA.playerSurname(T, p1)) + ' v ' + esc(TA.playerSurname(T, p2)) : esc(id)) + '</a>' + (TA.matchState(c) === 'live' ? ' <span class="live-dot"></span>' : '') },
      { v: evId, html: TA.eventLink(T, evId) + ' <span class="muted-inline">' + esc(TA.roundLabel(c.round, true)) + '</span>', cls: 'hide-sm' },
      { v: TA.playerName(T, side), html: esc(TA.playerSurname(T, side)) },
      { v: pm, html: TA.pct(pm, 0) }, { v: pk, html: TA.pct(pk, 0) },
      { v: Math.abs(edge), html: TA.edgeHTML(pm, pk) },
      { v: (x.sources || (c.market || {}).sources || []).join(','), html: (x.sources || (c.market || {}).sources || []).map(s => '<span class="src-chip">' + esc(s) + '</span>').join(''), cls: 'hide-sm' }
    ] };
  }).filter(Boolean).sort((a, b) => b.abs - a.abs);
  if (!rows.length) return TA.muted('No upcoming match has a market price right now.');
  return TA.tableHTML([{ label: 'Starts', cls: 'hide-sm' }, { label: 'Match' }, { label: 'Event', cls: 'hide-sm' }, { label: 'Model likes', title: 'The side the model rates above the market' },
    { label: 'Model', align: 'right' }, { label: 'Market', align: 'right' }, { label: 'Edge', align: 'right' }, { label: 'Source', cls: 'hide-sm' }], rows, { compact: true });
}

function explainer() {
  return '<div class="mk-explain">' +
    '<p><b>De-vigging.</b> Prices add up to more than 100% (the overround). We take the middle of each market’s bid and ask, then scale a whole field — every player in a tournament winner market, both players in a match — so it sums to 100%. When Kalshi and Polymarket both quote a market we average them.</p>' +
    '<p><b>Yes/no markets.</b> Finals qualification is quoted player by player. Those prices are shown as they are, not de-vigged, so they need not add up to eight qualifiers.</p>' +
    '<p><b>Thin markets.</b> Long shots often have no bid at all, or only 1¢. Those are marked <span class="thin">thin</span> and left out of the edge: a no-bid floor says nobody is interested, not that the chance is 1%.</p>' +
    '<p><b>Edges.</b> The edge is the model minus the market, in percentage points. It is not advice: the model does not know about injuries, illness, withdrawals or a player nursing a niggle, which markets price in fast. The calibration page shows how the model has done against Pinnacle’s closing odds.</p>' +
    '<p>For information and entertainment only; 18+; gamble responsibly. <a href="#/disclaimer">Disclaimer &amp; terms</a>.</p></div>';
}

function render(el, params) {
  const T = params.tour;
  el.innerHTML = TA.pageHead(TA.tourName(T) + ' markets', 'The model against Kalshi and Polymarket: matches, tournament winners, the Finals and year-end No. 1',
    '<a href="' + TA.href(T, 'calibration') + '">Calibration</a><a href="' + TA.href(T, 'race') + '">Race</a>') + '<div id="mk-body"><div class="muted">Loading…</div></div>';
  return TA.loadAll([TA.tpath('markets.json', T), TA.tpath('race.json', T)]).then(arr => {
    if (!el.isConnected) return null;
    const mk = TA.ok(arr[0]) ? arr[0] : null, race = TA.ok(arr[1]) ? arr[1] : null;
    const evIds = Object.keys(((mk || {}).futures || {}).events || {});
    /* read only events with a page: this year's from the year's event list, earlier years' as they are (next year's draws are not built) */
    const cy = TA.currentYear(T), have = e => { const y = Number(TA.yearOfId(e)) || 0; return y < cy ? y > 0 : y === cy && !!(TA.EVENTS[T][String(cy)] || {})[e]; };
    return TA.loadAll(evIds.map(e => (have(e) ? TA.eventPath(T, e) : 'index.json'))).then(evs => [mk, race, evIds, evs.map((v, i) => (have(evIds[i]) ? v : null)), arr[0]]);
  }).then(res => {
    if (!res || !el.isConnected) return;
    const mk = res[0], race = res[1], evIds = res[2], evs = res[3];
    const body = document.getElementById('mk-body');
    if (!mk) { body.innerHTML = TA.card('Markets', '', TA.notBuilt('The markets payload', res[4])) + TA.card('How to read this page', '', explainer()); return; }
    const fut = mk.futures || {};
    const tabs = [], panels = {};
    evIds.forEach((eid, i) => {
      const t = fut.events[eid];
      const ev = evs[i];
      const sim = ev && ev.sim && ev.sim.players ? ev.sim.players : {};
      const model = {};
      Object.keys(sim).forEach(p => { model[p] = sim[p].p_title; });
      panels['ev:' + eid] = futuresTable(T, rowsOf(model, t), { empty: 'No prices for this tournament.' }) +
        '<a class="more-link" href="' + TA.eventHref(T, eid) + '">The draw and path odds →</a>';
      tabs.push({ key: 'ev:' + eid, label: TA.eventName(T, eid) || (t && t.label) || eid, sub: srcText(t) });
    });
    if (race || fut.finals_qual) {
      panels.qual = futuresTable(T, rowsOf((race || {}).finals_qual, fut.finals_qual || ((race || {}).market || {}).finals_qual), { binary: true, empty: 'No Finals prices.' });
      tabs.push({ key: 'qual', label: 'Finals qualification', sub: [srcText(fut.finals_qual), 'yes prices'].filter(Boolean).join(' · ') });
    }
    if (race || fut.year_end_no1) {
      panels.no1 = futuresTable(T, rowsOf((race || {}).year_end_no1, fut.year_end_no1 || ((race || {}).market || {}).year_end_no1), { empty: 'No year-end No. 1 prices.' });
      tabs.push({ key: 'no1', label: 'Year-end No. 1', sub: srcText(fut.year_end_no1) });
    }
    if ((race && race.finals_title) || (fut.finals_winner && fut.finals_winner.available !== false)) {
      panels.fin = futuresTable(T, rowsOf((race || {}).finals_title, fut.finals_winner), { empty: 'No Finals prices.' });
      tabs.push({ key: 'fin', label: 'Finals winner', sub: srcText(fut.finals_winner) || 'model from the season simulation' });
    }
    // next season's Slams: the key is "slams_<next season>" (analytics/site.py markets_payload)
    const slKey = Object.keys(fut).filter(k => /^slams_\d{4}$/.test(k)).sort().pop();
    const sl = (slKey && fut[slKey]) || {}, slYear = slKey ? slKey.slice(6) : '';
    Object.keys(sl).forEach(k => {
      const t = sl[k];
      if (!t || typeof t !== 'object') return;
      panels['sl:' + k] = futuresTable(T, rowsOf({}, t), { binary: t.kind !== 'tournament', empty: 'No prices.' });
      tabs.push({ key: 'sl:' + k, label: TA.titleCase(k) + ' ' + slYear, sub: [srcText(t), 'market only'].filter(Boolean).join(' · ') });
    });
    const info = TA.tourInfo(T);
    const cards = [].concat(info.live || [], info.today || [], info.upcoming || []);
    let html = TA.card('Match prices', 'model against the de-vigged market, largest gap first', '<div id="mk-matches"></div>');
    html += tabs.length ? TA.card('Futures', 'model against the market', '<div class="toggle-row" id="mk-tabs">' + TA.toggles(tabs, tabs[0].key, 'data-mk') + '</div><div class="section-note" id="mk-sub"></div><div id="mk-panel"></div>')
      : TA.card('Futures', '', TA.muted('No futures markets are open.'));
    html += TA.card('How to read this page', 'de-vigging, yes/no markets, thin markets and edges', explainer());
    body.innerHTML = html;
    document.getElementById('mk-matches').innerHTML = matchTable(T, mk.matches || {}, cards);
    TA.sortable(document.getElementById('mk-matches'));
    if (tabs.length) {
      const show = k => {
        const tab = tabs.find(t => t.key === k) || tabs[0];
        document.getElementById('mk-panel').innerHTML = panels[tab.key] || TA.muted('No prices.');
        document.getElementById('mk-sub').innerHTML = tab.sub || '';
        TA.sortable(document.getElementById('mk-panel'));
      };
      show(tabs[0].key);
      TA.wireToggles(document.getElementById('mk-tabs'), 'data-mk', show);
    }
    TA.setMeta(mk.updated_at ? 'Prices ' + esc(TA.fmtStamp(mk.updated_at)) : '');
  });
}

TA.route('markets', render);
})(window.TA);
