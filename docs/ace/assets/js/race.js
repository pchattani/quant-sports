/* The Quant Ace — the race (#/<T>/race).
 *
 *   Finals qualification: the model's probability from the rest-of-season simulation against the
 *     market (Kalshi, Polymarket yes prices), with race points and the gap to eighth;
 *   year-end No. 1: model against the de-vigged market;
 *   rank distributions: where each contender finishes the year (a heat map over ranks 1-20);
 *   projected year-end race points (mean and the 5th-95th percentile range);
 *   the events left in the simulation.
 *
 * Reads <T>/race.json, <T>/rankings.json (race points) and <T>/markets.json (futures, when race.json carries no market). */
(function (TA) {
'use strict';

const esc = TA.esc;

function rankHeat(el, T, race, ids) {
  const rd = race.rank_dist || {};
  const list = ids.filter(p => (rd[p] || []).length).slice(0, 20);
  if (!list.length) { el.innerHTML = TA.muted('No rank distributions in the simulation.'); return; }
  const n = Math.max.apply(null, list.map(p => rd[p].length));
  const z = list.map(p => { const a = rd[p].slice(); while (a.length < n) a.push(0); return a.map(v => (v > 0 ? v : null)); });
  const text = z.map(r => r.map(v => (v !== null && v >= 0.095 ? String(Math.round(v * 100)) : '')));
  const labels = list.map(p => TA.playerSurname(T, p));
  const narrow = (el.clientWidth || 800) < 560;
  const xl = (race.rank_dist_labels || []).length === n ? race.rank_dist_labels.map(String) : Array.from({ length: n }, (_, i) => String(i + 1));
  TA.plot(el, [{ type: 'heatmap', z: z, x: xl, y: labels, text: text, texttemplate: '%{text}', textfont: { size: 9, color: '#0d1117' },
    colorscale: [[0, '#1b2108'], [0.15, '#45520f'], [0.4, '#8fa22a'], [0.7, '#c4dc45'], [1, '#ecff9a']], zmin: 0,
    hovertemplate: '%{y} · finishes No. %{x}: %{z:.1%}<extra></extra>', xgap: 1, ygap: 1, showscale: false }], TA.layout({
    height: Math.max(260, list.length * 22 + 60),
    xaxis: { side: 'top', type: 'category', fixedrange: true, tickfont: { size: narrow ? 8 : 10 }, title: '' },
    yaxis: { autorange: 'reversed', type: 'category', fixedrange: true, automargin: true, tickfont: { size: 10 } },
    margin: { l: 90, r: 8, t: 26, b: 8 }
  }));
}

function render(el, params) {
  const T = params.tour;
  const fin = T === 'atp' ? 'ATP Finals (Turin)' : 'WTA Finals (Riyadh)';
  el.innerHTML = TA.pageHead('The race to the ' + (T === 'atp' ? 'ATP' : 'WTA') + ' Finals', 'Finals qualification and year-end No. 1, simulated against the market',
    '<a href="' + TA.href(T, 'rankings') + '">Rankings</a><a href="' + TA.href(T, 'markets') + '">Markets</a>') + '<div id="rc-body"><div class="muted">Loading…</div></div>';
  return TA.loadAll([TA.tpath('race.json', T), TA.tpath('rankings.json', T), TA.tpath('markets.json', T)]).then(arr => {
    if (!el.isConnected) return;
    const race = arr[0], rk = TA.ok(arr[1]) ? arr[1] : null, mk = TA.ok(arr[2]) ? arr[2] : null;
    const body = document.getElementById('rc-body');
    if (!TA.ok(race)) { body.innerHTML = TA.card('Race', '', TA.notBuilt('The season simulation', race)); return; }
    const fq = race.finals_qual || {}, no1 = race.year_end_no1 || {}, ft = race.finals_title || {};
    const rmk = race.market || {};
    const fut = (mk && mk.futures) || {};
    const mq = TA.titleProbs(rmk.finals_qual || fut.finals_qual), m1 = TA.titleProbs(rmk.year_end_no1 || fut.year_end_no1);
    const pts = {};
    ((rk && rk.race) || []).forEach((r, i) => { pts[r[0]] = { pts: r[1], pos: i + 1 }; });
    if (!Object.keys(pts).length && race.race && typeof race.race === 'object' && !Array.isArray(race.race)) {
      Object.keys(race.race).sort((a, b) => (race.race[b].now || 0) - (race.race[a].now || 0)).forEach((p, i) => { pts[p] = { pts: race.race[p].now, pos: i + 1 }; });
    }
    const cutPts = ((rk && rk.race) || [])[7] ? rk.race[7][1] : null;
    const ids = Object.keys(fq).concat(Object.keys(mq).filter(p => !(p in fq)))
      .sort((a, b) => (fq[b] || 0) - (fq[a] || 0) || (mq[b] || 0) - (mq[a] || 0));
    const nIn = ids.filter(p => (fq[p] || 0) >= 0.995).length;

    // ── tiles
    const top1 = Object.keys(no1).sort((a, b) => no1[b] - no1[a])[0];
    const bubble = ids.filter(p => (fq[p] || 0) > 0.05 && (fq[p] || 0) < 0.95);
    let html = '<div class="kpi-grid">' +
      TA.statTile('Year-end No. 1 favourite', top1 ? esc(TA.playerSurname(T, top1)) + ' ' + TA.pct(no1[top1], 0) : '—', top1 && TA.isNum(m1[top1]) ? 'market ' + TA.pct(m1[top1], 0) : '') +
      TA.statTile('Virtually qualified', String(nIn), 'players at 99.5% or more') +
      TA.statTile('On the bubble', String(bubble.length), 'between 5% and 95%') +
      TA.statTile('Simulations', TA.isNum(race.n_sims) ? TA.num(race.n_sims, 0) : '—', (race.remaining_events || []).length + ' events left') + '</div>';

    // ── qualification
    const rows = ids.slice(0, 30).map((p, i) => {
      const r = pts[p] || {}, pr = (race.points || {})[p] || {};
      return { _href: TA.playerHref(T, p), _class: i === 8 ? 'cut' : '', cells: [
        { v: r.pos, html: TA.isNum(r.pos) ? String(r.pos) : '—' },
        { v: TA.playerName(T, p), html: TA.playerLink(T, p, { country: true }) },
        { v: r.pts, html: TA.num(r.pts, 0) },
        { v: TA.isNum(cutPts) && TA.isNum(r.pts) ? r.pts - cutPts : null, html: TA.isNum(cutPts) && TA.isNum(r.pts) ? TA.signed(r.pts - cutPts, 0) : '—', cls: 'hide-sm' },
        { v: pr.mean, html: TA.isNum(pr.mean) ? TA.num(pr.mean, 0) + '<span class="rk-sub"> ' + TA.num(pr.p05, 0) + '–' + TA.num(pr.p95, 0) + '</span>' : '—', cls: 'hide-sm' },
        { v: fq[p], html: TA.probCell(fq[p]) },
        { v: ft[p], html: TA.isNum(ft[p]) ? TA.pct(ft[p], 1) : '—', cls: 'hide-sm' },
        { v: mq[p], html: TA.isNum(mq[p]) ? TA.pct(mq[p], 0) : '—' },
        { v: TA.isNum(fq[p]) && TA.isNum(mq[p]) ? fq[p] - mq[p] : null, html: TA.edgeHTML(fq[p], mq[p]) }
      ] };
    });
    html += TA.card('Finals qualification', esc(fin) + ' · model against the market (yes prices, not de-vigged)',
      TA.tableHTML([{ label: 'Race', align: 'right' }, { label: 'Player' }, { label: 'Points', align: 'right' }, { label: 'v 8th', align: 'right', cls: 'hide-sm' },
        { label: 'Year-end (5–95%)', align: 'right', title: 'Simulated year-end race points: mean, then the 5th to 95th percentile', cls: 'hide-sm' },
        { label: 'Qualify (model)' }, { label: 'Title', align: 'right', title: 'Model probability of winning the Finals', cls: 'hide-sm' }, { label: 'Market', align: 'right' }, { label: 'Edge', align: 'right' }], rows, { compact: true }) +
      '<div class="section-note">The top eight in the race qualify; the dashed line sits below eighth place in the model’s order. Per-player yes/no markets are priced one by one, so they need not add up to eight.</div>');

    // ── No. 1 and rank distributions
    html += '<div class="grid-2"><div>' + TA.card('Year-end No. 1', 'model bars · de-vigged market ticks', '<div id="rc-no1"></div>') + '</div><div>' +
      TA.card('Where they finish', 'simulated year-end rank, 1–20 (numbers are % where 10% or more)', '<div id="rc-heat"></div>') + '</div></div>';
    const rem = race.remaining_events || [];
    html += TA.card('Still to play', rem.length + ' event' + (rem.length === 1 ? '' : 's') + ' in the simulation',
      rem.length ? TA.tableHTML([{ label: 'Starts' }, { label: 'Event' }, { label: 'Level' }, { label: 'How it is simulated', cls: 'hide-sm' }], rem.map(e0 => {
        // remaining events are ids or {id, name, level, start, surface, method}
        const e = typeof e0 === 'string' ? { id: e0 } : (e0 || {});
        const info = Object.assign({}, TA.eventInfo(T, e.id), e);
        return [{ v: info.start, html: esc(TA.fmtDate(info.start, { weekday: false, year: false })) },
          { v: info.name, html: info.start || info.name ? TA.eventLink(T, e.id, { surface: true, name: info.name }) : esc(TA.titleCase(e.id)) },
          { v: TA.levelRank(info.level), html: info.level ? esc(TA.levelLabel(info.level, T)) : '—' },
          { v: info.method, html: info.method ? '<span class="muted-inline">' + esc(info.method) + '</span>' : '—' }];
      }), { compact: true }) : TA.muted('The season is complete.')) +
      (race.simplifications ? TA.card('What the simulation assumes', '', '<div class="mk-explain">' + (Array.isArray(race.simplifications) ? race.simplifications.map(s => '<p>' + esc(s) + '</p>').join('') : esc(race.simplifications)) + '</div>') : '');
    body.innerHTML = html;
    const items = Object.keys(no1).concat(Object.keys(m1).filter(p => !(p in no1))).sort((a, b) => (no1[b] || 0) - (no1[a] || 0)).slice(0, 8)
      .filter(p => (no1[p] || 0) >= 0.001 || (TA.isNum(m1[p]) && m1[p] >= 0.01)).map(p => ({ label: TA.playerSurname(T, p), p: no1[p] || 0, market: TA.isNum(m1[p]) ? m1[p] : null }));
    TA.charts.probBars('rc-no1', items, { top: 8, emptyText: 'No year-end No. 1 odds.' });
    rankHeat(document.getElementById('rc-heat'), T, race, ids.length ? ids : Object.keys(race.rank_dist || {}));
    TA.sortable(el);
    TA.setMeta((TA.isNum(race.n_sims) ? TA.num(race.n_sims, 0) + ' season simulations' : ''));
  });
}

TA.route('race', render);
})(window.TA);
