/* The Quant Paddock — markets (#/markets): the model against the prediction markets.
 *
 * Drivers' and constructors' titles (season simulation against de-vigged Kalshi and
 * Polymarket prices: price, model, edge, sources, eliminated runners), the next race
 * winner, and open head-to-heads.
 *
 * Data: data/markets.json; data/<y>/season.json for the model when the payload
 * carries only prices; data/<y>/races/<r>.json for the next race's forecast. */
(function (PD) {
'use strict';

const { esc, num, pct, signed, isNum, card, muted, tableHTML, sortable, plot, layout, C } = PD;
const PG = () => PD.pg;

/* Sources may be a list of names, or {source: {runner: mid}}. */
function sourceNames(src) {
  if (!src) return [];
  if (Array.isArray(src)) return src.map(s => (typeof s === 'string' ? s : s.name || s.source || JSON.stringify(s)));
  return Object.keys(src);
}
function sourceMid(src, name, id) { return src && !Array.isArray(src) && src[name] ? src[name][id] : undefined; }

function edgeHTML(e) {
  if (!isNum(e)) return '<span class="muted-inline">—</span>';
  return '<span class="' + (e > 0 ? 'pg-edge-pos' : 'pg-edge-neg') + '">' + signed(100 * e, 0) + '%</span>';
}

/* One title market: table + model v market chart. kind 'drivers' | 'constructors'. */
function titleBlock(el, kind, T, modelFallback) {
  const idCell = id => (kind === 'drivers' ? PD.driverLink(id, { team: (PD.NAMES.drivers[id] || {}).team }) : PD.teamLink(id));
  const nameOf = id => (kind === 'drivers' ? PD.driverName(id) : PD.teamName(id));
  const tableId = 'mk-' + kind, chartId = 'mk-' + kind + '-chart';
  const t = T || {};
  const prices = t.prices || t.probs || {};
  const model = Object.keys(t.model || {}).length ? t.model : (modelFallback || {});
  const ids = Array.from(new Set(Object.keys(prices).concat(Object.keys(model)))).sort((a, b) => ((model[b] || 0) + (prices[b] || 0)) - ((model[a] || 0) + (prices[a] || 0)));
  const srcNames = sourceNames(t.sources);
  const elim = new Set(t.eliminated || []), floor = new Set(t.floor || []);
  const head = '<div class="mk-line">' + (t.available ? '<span class="pg-tag good">published</span> ' : '<span class="pg-tag warn">not published</span> ' + esc(t.reason || 'no market yet') + ' · ') +
    (isNum(t.implied_total) ? 'implied total of the two-sided mids ' + num(t.implied_total, 3) + ' (overround ' + signed(100 * (t.implied_total - 1), 1) + '%)' : '') +
    (srcNames.length ? ' · sources ' + srcNames.map(s => '<span class="mk-src">' + esc(s) + '</span>').join('') : '') +
    (isNum(t.accounted) && isNum(t.field) ? ' · ' + t.accounted + ' of ' + t.field + ' runners accounted for' : '') + '</div>';
  if (!ids.length) return head + muted('No prices and no model for this market.');
  const live = ids.filter(id => !elim.has(id) && ((prices[id] || 0) > 0 || (model[id] || 0) > 0.0005));
  const rows = live.map(id => {
    const p = prices[id], m = model[id];
    const e = isNum((t.edge || {})[id]) ? t.edge[id] : (isNum(p) && p > 0 && isNum(m) ? m / p - 1 : null);
    const cells = [{ v: nameOf(id), html: idCell(id) + (floor.has(id) ? ' <span class="pg-tag" title="no bid, ask at or under the floor: under 1%, not unpriced">floor</span>' : '') },
      { v: m, html: PD.probCell(m, C.blue, 1) }, { v: p, html: PD.probCell(p, C.orange, 1) }, { v: e, html: edgeHTML(e), align: 'right' },
      { v: isNum(p) && p > 0 ? 1 / p : null, html: isNum(p) && p > 0 ? num(1 / p, 2) : '—', align: 'right', title: 'Fair decimal odds from the de-vigged market' }];
    srcNames.forEach(s => { const v = sourceMid(t.by_source || t.sources, s, id); cells.push({ v: v, html: isNum(v) ? pct(v) : '—', align: 'right' }); });
    return { _href: (kind === 'drivers' ? '#/driver/' : '#/team/') + id, cells: cells };
  });
  const cols = [{ label: kind === 'drivers' ? 'Driver' : 'Team' }, { label: 'Model' }, { label: 'Market' }, { label: 'Edge', align: 'right', title: 'model / market − 1' }, { label: 'Fair odds', align: 'right' }]
    .concat(srcNames.map(s => ({ label: s + ' mid', align: 'right', title: 'Two-sided midpoint before the de-vig' })));
  setTimeout(() => {
    const host = document.getElementById(tableId);
    if (host) sortable(host);
    const top = live.slice(0, 10).reverse();
    if (document.getElementById(chartId) && top.length) plot(chartId, [
      { type: 'bar', orientation: 'h', name: 'Model', y: top.map(nameOf), x: top.map(id => model[id] || 0), marker: { color: C.blue }, hovertemplate: '%{y}: model %{x:.1%}<extra></extra>' },
      { type: 'bar', orientation: 'h', name: 'Market', y: top.map(nameOf), x: top.map(id => prices[id] || 0), marker: { color: C.orange }, hovertemplate: '%{y}: market %{x:.1%}<extra></extra>' }
    ], layout({ barmode: 'group', showlegend: true, legend: { orientation: 'h', y: 1.0, yanchor: 'bottom', font: { color: C.text2 } }, margin: { l: 130, r: 20, t: 40, b: 40 }, xaxis: { tickformat: '.0%' } }));
  }, 0);
  return head + '<div class="grid-2"><div id="' + tableId + '">' + tableHTML(cols, rows, { compact: true }) + '</div><div id="' + chartId + '" style="height:' + Math.max(260, 26 * Math.min(10, live.length) + 80) + 'px"></div></div>' +
    (elim.size ? '<div class="pg-note"><strong>Eliminated</strong> (Polymarket runner closed and settled No, or Kalshi result "no"; probability 0): ' + Array.from(elim).map(id => (kind === 'drivers' ? PD.driverLink(id) : PD.teamLink(id))).join(', ') + '</div>' : '');
}

function renderMarkets(el, params, state) {
  const y = PD.currentSeason();
  el.innerHTML = '<div class="card"><div class="card-header">Markets <span class="card-sub">The model against Kalshi and Polymarket.</span></div>' +
    '<div class="mk-line"><strong>De-vig:</strong> each price is the midpoint of a live two-sided quote (spread at most 0.12), averaged across sources, then divided by the field\'s total so the probabilities sum to one. ' +
    '<strong>Thin-market rule:</strong> a field market is shown only when at least max(4, half the field) runners are accounted for — quoted, written off at a no-bid floor, or eliminated — and the implied total is between 0.8 and 1.3. ' +
    'Edge is model / market − 1. <a href="#/methodology">Methodology →</a></div><div class="pg-note" id="mk-meta"></div></div><div id="mk-body">' + muted('Loading…') + '</div>';
  return Promise.all([PD.load('markets.json'), PD.load(y + '/season.json'), PD.index ? Promise.resolve(PD.index()) : Promise.resolve(null)]).then(res => {
    if (!PG().alive(el)) return null;
    const mk = res[0], season = res[1], idx = res[2];
    if (!mk || mk.ok === false) { document.getElementById('mk-body').innerHTML = card('', '', PG().notBuilt('The markets file', mk)); return null; }
    document.getElementById('mk-meta').innerHTML = mk.updated_at ? 'Prices fetched ' + esc(PD.fmtStamp(mk.updated_at)) + '. Markets move; the site refreshes hourly.' : '';
    const ch = (season || {}).championship || {};
    const mdl = k => { const o = {}; Object.keys(ch[k] || {}).forEach(id => { o[id] = ch[k][id].p_title; }); return o; };
    let h = '<div class="card"><div class="card-header">Drivers\' championship <span class="card-sub">Season simulation (' + (ch.n_sims ? Number(ch.n_sims).toLocaleString() + ' runs' : 'model') + ') against the de-vigged market.</span></div>' + titleBlock(el, 'drivers', mk.drivers_title, mdl('drivers')) + '</div>';
    h += '<div class="card"><div class="card-header">Constructors\' championship</div>' + titleBlock(el, 'constructors', mk.constructors_title, mdl('constructors')) + '</div>';
    h += '<div class="card"><div class="card-header">Next race winner <span class="card-sub" id="mk-next-sub"></span></div><div id="mk-next">' + muted('Loading…') + '</div></div>';
    h += '<div class="card"><div class="card-header">Head to head <span class="card-sub">Who finishes ahead: race matchups and season matchups. Market probability is the mean across sources; the model column is the share of simulations in which A beats B where the payload carries it.</span></div><div id="mk-h2h"></div></div>';
    document.getElementById('mk-body').innerHTML = h;

    // Next race.
    const nr = mk.next_race || {};
    const nxt = (idx || {}).next || {};
    const year = nr.year || nxt.year || y, round = nr.round || nxt.round;
    const draw = (model, prices, srcs) => {
      const ids = Array.from(new Set(Object.keys(model || {}).concat(Object.keys(prices || {})))).sort((a, b) => ((model[b] || 0) + (prices[b] || 0)) - ((model[a] || 0) + (prices[a] || 0))).slice(0, 20);
      if (!ids.length) { document.getElementById('mk-next').innerHTML = muted('No forecast or market for the next race yet; race-winner markets list about a week out.'); return; }
      const srcNames = sourceNames(srcs);
      document.getElementById('mk-next').innerHTML = (nr.reason && !Object.keys(prices || {}).length ? '<div class="mk-line"><span class="pg-tag warn">no market</span> ' + esc(nr.reason) + '</div>' : '') + (srcNames.length ? '<div class="mk-line">Sources ' + srcNames.map(s => '<span class="mk-src">' + esc(s) + '</span>').join('') + '</div>' : (Object.keys(prices || {}).length ? '' : '<div class="mk-line">No market yet: model only.</div>')) +
        tableHTML([{ label: 'Driver' }, { label: 'Model' }, { label: 'Market' }, { label: 'Edge', align: 'right' }, { label: 'Fair odds', align: 'right' }],
          ids.map(id => { const m = (model || {})[id], p = (prices || {})[id]; return { _href: '#/driver/' + id, cells: [{ v: PD.driverName(id), html: PD.driverLink(id, { team: (PD.NAMES.drivers[id] || {}).team }) }, { v: m, html: PD.probCell(m, C.blue, 1) }, { v: p, html: PD.probCell(p, C.orange, 1) },
            { v: isNum(m) && isNum(p) && p > 0 ? m / p - 1 : null, html: edgeHTML(isNum(m) && isNum(p) && p > 0 ? m / p - 1 : null), align: 'right' }, { v: isNum(p) && p > 0 ? 1 / p : null, html: isNum(p) && p > 0 ? num(1 / p, 2) : '—', align: 'right' }] }; }), { compact: true });
      sortable('mk-next');
    };
    document.getElementById('mk-next-sub').innerHTML = round ? PD.raceLink(year, round, year + ' round ' + round + (nxt.name && nxt.round === round ? ': ' + nxt.name : '')) : '';
    if (Object.keys(nr.model || {}).length) draw(nr.model, nr.prices || {}, nr.sources);
    else if (round) {
      PD.load(year + '/races/' + round + '.json').then(r => {
        if (!PG().alive(el)) return;
        const f = ((r || {}).forecast) || {};
        const sim = f.post_quali || f.pre_quali;
        const m = {};
        Object.keys((sim || {}).drivers || {}).forEach(id => { m[id] = sim.drivers[id].p_win; });
        draw(m, nr.prices || {}, nr.sources);
      });
    } else draw({}, nr.prices || {}, nr.sources);

    // Head to head.
    const H = mk.h2h || [];
    const list = Array.isArray(H) ? H.map(x => Object.assign({ scope: x.scope || (x.round ? 'race' : 'season') }, x)) : (H.race || []).map(x => Object.assign({ scope: 'race' }, x)).concat((H.season || []).map(x => Object.assign({ scope: 'season' }, x)));
    document.getElementById('mk-h2h').innerHTML = list.length ? tableHTML([{ label: 'Scope' }, { label: 'A' }, { label: 'B' }, { label: 'Market P(A ahead)', align: 'right' }, { label: 'Model', align: 'right' }, { label: 'Edge on A', align: 'right' }, { label: 'Sources' }],
      list.map(x => {
        const pm = isNum(x.model_a) ? x.model_a : isNum(x.model) ? x.model : null;
        return [{ v: x.scope, html: x.scope === 'race' ? (x.round ? PD.raceLink(year, x.round, 'Race R' + x.round) : 'Race') + (x.date ? ' <span class="muted-inline">' + esc(x.date) + '</span>' : '') : 'Season' },
          { v: PD.driverName(x.a), html: PD.driverLink(x.a) }, { v: PD.driverName(x.b), html: PD.driverLink(x.b) }, { v: x.p_a, html: pct(x.p_a), align: 'right' },
          { v: pm, html: isNum(pm) ? pct(pm) : '—', align: 'right' }, { v: isNum(pm) && x.p_a ? pm / x.p_a - 1 : null, html: edgeHTML(isNum(pm) && x.p_a ? pm / x.p_a - 1 : null), align: 'right' },
          { v: '', html: Object.keys(x.sources || {}).map(s => '<span class="mk-src">' + esc(s) + ' ' + pct(x.sources[s], 0) + '</span>').join('') }];
      }), { compact: true }) : muted('No head-to-head market is open. Kalshi lists race matchups (KXF1H2H) and Polymarket race and season head-to-heads around race week.');
    sortable('mk-h2h');
    return null;
  });
}

PD.route('markets', renderMarkets);
})(window.PD);
