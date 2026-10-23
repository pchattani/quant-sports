/* The Quant Ace — the race (#/<T>/race), Design System 2.0.
 *
 *   stat tiles: our year-end No. 1 favourite, players virtually qualified, on the bubble, the simulations;
 *   Finals qualification: our chance from the rest-of-season simulation (chance bars and a table with race points,
 *     the gap to eighth and the simulated year-end points with their 5th-95th percentile range);
 *   year-end No. 1: our chances; where they finish: the simulated year-end rank as a heat map (both axes titled);
 *   chances over time from race.json "history" (one snapshot per simulation date; a note until three are on record);
 *   the events left in the simulation and what it assumes.
 * Race points come from the latest ranking (this week included); the simulation starts from its own snapshot.
 * Reads <T>/race.json and <T>/rankings.json. */
(function (TA) {
'use strict';

const esc = TA.esc, isNum = TA.isNum;

function rankHeat(sel, T, race, ids) {
  const rd = race.rank_dist || {};
  const list = ids.filter(p => (rd[p] || []).length).slice(0, 20);
  const node = document.querySelector(sel);
  if (!list.length) { node.innerHTML = TA.muted('No rank distributions in the simulation.'); return; }
  const n = Math.max.apply(null, list.map(p => rd[p].length));
  const xl = (race.rank_dist_labels || []).length === n ? race.rank_dist_labels.map(String) : Array.from({ length: n }, (_, i) => String(i + 1));
  const data = [];
  list.forEach((p, yi) => { for (let xi = 0; xi < n; xi++) { const v = rd[p][xi]; if (isNum(v) && v > 0) data.push([xi, yi, v]); } });
  node.style.setProperty('--h', Math.max(280, list.length * 24 + 110) + 'px');
  QKC.heatmap(sel, { x: xl, y: list.map(p => TA.playerSurname(T, p)), data: data, min: 0, fmt: v => Math.round(v * 100) + '%', labelMin: 0.095,
    xName: 'Year-end rank', yName: 'Player', label: 'Simulated year-end rank by player' });
}

function render(el, params) {
  const T = params.tour, V = TA.v2;
  const fin = T === 'atp' ? 'ATP Finals (Turin)' : 'WTA Finals (Riyadh)';
  el.innerHTML = '<div id="rc-body">' + QK.skeleton('lines', 6) + '</div>';
  return TA.loadAll([TA.tpath('race.json', T), TA.tpath('rankings.json', T)]).then(arr => {
    if (!el.isConnected) return;
    const race = arr[0], rk = TA.ok(arr[1]) ? arr[1] : null;
    const body = document.getElementById('rc-body');
    if (!TA.ok(race)) { body.innerHTML = TA.card('Race', '', TA.notBuilt('The season simulation', race)); return; }
    const fq = race.finals_qual || {}, no1 = race.year_end_no1 || {}, ft = race.finals_title || {};
    const pts = {};
    ((rk && rk.race) || []).forEach((r, i) => { pts[r[0]] = { pts: r[1], pos: i + 1 }; });
    let ptsNote = 'race points from the latest ranking, this week included';
    if (!Object.keys(pts).length && race.race && typeof race.race === 'object' && !Array.isArray(race.race)) {
      Object.keys(race.race).sort((a, b) => (race.race[b].now || 0) - (race.race[a].now || 0)).forEach((p, i) => { pts[p] = { pts: race.race[p].now, pos: i + 1 }; });
      ptsNote = 'race points when the season was last simulated';
    }
    const cutPts = ((rk && rk.race) || [])[7] ? rk.race[7][1] : null;
    const ids = Object.keys(fq).sort((a, b) => (fq[b] || 0) - (fq[a] || 0));
    const nIn = ids.filter(p => (fq[p] || 0) >= 0.995).length;
    const top1 = Object.keys(no1).sort((a, b) => no1[b] - no1[a])[0];
    const bubble = ids.filter(p => (fq[p] || 0) > 0.05 && (fq[p] || 0) < 0.95);
    const nS = isNum(race.n_sims) ? Number(race.n_sims).toLocaleString('en-GB') : '';
    let html = '<div class="ta-kpis">' + QK.stats([
      { label: 'Year-end No. 1', value: top1 ? TA.playerSurname(T, top1) + ' ' + TA.pct(no1[top1], 0) : '—', signal: true, href: top1 ? TA.playerHref(T, top1) : null, sub: 'our chance, the favourite' },
      { label: 'Virtually qualified', value: String(nIn), sub: 'our chance 99.5% or more' },
      { label: 'On the bubble', value: String(bubble.length), sub: 'our chance between 5% and 95%' },
      { label: 'Simulations', value: nS || '—', sub: (race.remaining_events || []).length + ' events left' + (race.as_of ? ' · from ' + TA.fmtDate(race.as_of, { year: false, weekday: false }) : '') }]) + '</div>';
    html += '<div class="qk-grid"><div class="qk-span-5">' + V.card('Who qualifies', 'Our chance of a place at the ' + esc(fin), '<div id="rc-ch"></div>') + '</div><div class="qk-span-7">' +
      V.card('Finals qualification', esc(ptsNote) + '; the dashed line sits below eighth in our order', '<div id="rc-table"></div>', { flush: true,
        foot: '<span>The top eight in the race qualify' + (T === 'atp' ? '; a Slam champion ranked 9–20 takes the eighth place' : '') + '</span>' }) + '</div></div>';
    const H = (race.history || []).filter(h => h && h.as_of).sort((a, b) => String(a.as_of).localeCompare(String(b.as_of)));
    html += '<section class="qk-section">' + V.card('Chances over time', 'Our chance after each simulation of the rest of the season' + (H.length ? ', from ' + esc(TA.fmtDate(H[0].as_of, { weekday: false })) : ''),
      (H.length >= 3 ? V.seg('rc-h-k', [['finals_qual', 'Finals qualification'], ['year_end_no1', 'Year-end No. 1']], 'finals_qual', 'Chance') + V.chart('rc-hist', 340, 'Chances over time')
        : '<p class="ta-cap" style="margin:0">' + (H.length ? 'Recording started on ' + esc(TA.fmtDate(H[0].as_of, { weekday: false })) + ' with ' + H.length + ' simulation date' + (H.length === 1 ? '' : 's') + ' so far' : 'The simulation has not recorded its history yet') +
          '. The chart appears once three dates are on record; earlier runs were not stored.</p>')) + '</section>';
    html += '<section class="qk-section"><div class="qk-grid"><div class="qk-span-5">' + V.card('Year-end No. 1', 'Our chance of finishing the year ranked No. 1', '<div id="rc-no1"></div>') + '</div><div class="qk-span-7">' +
      V.card('Where they finish', 'Simulated year-end rank, 1–20; cells show the chance where it is 10% or more', V.chart('rc-heat', 420, 'Simulated year-end rank')) + '</div></div></section>';
    const rem = race.remaining_events || [];
    html += TA.card('Still to play', rem.length + ' event' + (rem.length === 1 ? '' : 's') + ' in the simulation',
      rem.length ? TA.tableHTML([{ label: 'Starts' }, { label: 'Event' }, { label: 'Level' }, { label: 'How it is simulated', cls: 'hide-sm' }], rem.map(e0 => {
        const e = typeof e0 === 'string' ? { id: e0 } : (e0 || {});
        const info = Object.assign({}, TA.eventInfo(T, e.id), e);
        return [{ v: info.start, html: esc(TA.fmtDate(info.start, { weekday: false, year: false })) },
          { v: info.name, html: info.start || info.name ? TA.eventLink(T, e.id, { surface: true, name: info.name }) : esc(TA.titleCase(e.id)) },
          { v: TA.levelRank(info.level), html: info.level ? esc(TA.levelLabel(info.level, T)) : '—' },
          { v: info.method, html: info.method ? '<span class="muted-inline">' + esc(info.method) + '</span>' : '—' }];
      }), { compact: true }) : TA.muted('The season is complete.')) +
      (race.simplifications ? TA.card('What the simulation assumes', '', '<div class="mk-explain">' + (Array.isArray(race.simplifications) ? race.simplifications.map(s => '<p>' + esc(s) + '</p>').join('') : esc(race.simplifications)) + '</div>') : '');
    body.innerHTML = html;
    el.querySelector('#rc-ch').innerHTML = QK.chances(ids.filter(p => fq[p] >= 0.001).slice(0, 16).map(p => ({ label: TA.playerShort(T, p), p: fq[p], href: TA.playerHref(T, p), sub: pts[p] ? TA.num(pts[p].pts, 0) + ' pts' : '' })), { max: 1, oursName: 'Our chance of qualifying' });
    const rows = ids.slice(0, 30).map((p, i) => {
      const r = pts[p] || {}, pr = (race.points || {})[p] || {};
      return { id: p, cut: i === 8, pos: r.pos, name: TA.playerShort(T, p), sub: TA.playerCountry(T, p), pts: r.pts, gap: isNum(cutPts) && isNum(r.pts) ? r.pts - cutPts : null,
        ye: pr.mean, lo: pr.p05, hi: pr.p95, q: fq[p], t: ft[p] };
    });
    QK.leaderboard(el.querySelector('#rc-table'), { dense: true, rowHref: r => TA.playerHref(T, r.id), rowClass: r => (r.cut ? 'cut' : ''), columns: [
      { key: 'pos', label: 'Race', num: true, fmt: v => (isNum(v) ? String(v) : '—') },
      { key: 'name', label: 'Player', type: 'entity', sub: 'sub', href: r => TA.playerHref(T, r.id) },
      { key: 'pts', label: 'Points', num: true, fmt: v => TA.num(v, 0) },
      { key: 'gap', label: 'v 8th', num: true, fmt: v => (isNum(v) ? TA.signed(v, 0) : '—') },
      { key: 'ye', label: 'Year-end (5–95%)', num: true, fmt: (v, r) => (isNum(v) ? TA.num(v, 0) + ' <small class="muted-inline">' + TA.num(r.lo, 0) + '–' + TA.num(r.hi, 0) + '</small>' : '—') },
      { key: 'q', label: 'Qualify', type: 'bar', max: 1, fmt: v => TA.pct(v, v > 0.995 || v < 0.01 ? 1 : 0) },
      { key: 't', label: 'Title', num: true, fmt: v => (isNum(v) ? TA.pct(v, 1) : '—') }], rows: rows });
    const items = Object.keys(no1).sort((a, b) => (no1[b] || 0) - (no1[a] || 0)).slice(0, 8).filter(p => (no1[p] || 0) >= 0.001).map(p => ({ label: TA.playerShort(T, p), p: no1[p], href: TA.playerHref(T, p) }));
    el.querySelector('#rc-no1').innerHTML = items.length ? QK.chances(items, { max: 1, oursName: 'Our chance' }) : QK.empty('No year-end No. 1 chances');
    rankHeat('#rc-heat', T, race, ids.length ? ids : Object.keys(race.rank_dist || {}));
    if (H.length >= 3) {
      const drawH = key => {
        const last = H[H.length - 1][key] || {};
        const who = Object.keys(last).filter(p => H.some(h => isNum((h[key] || {})[p]) && h[key][p] >= 0.02 && h[key][p] <= 0.995))
          .sort((a, b) => (last[b] || 0) - (last[a] || 0)).slice(0, 8);
        if (!who.length) { el.querySelector('#rc-hist').innerHTML = QK.empty('No contest yet', 'Every contender is above 99.5% or below 2%.'); return; }
        QKC.forecast('#rc-hist', { x: H.map(h => h.as_of), xType: 'time', xName: 'Simulation date', yName: key === 'year_end_no1' ? 'Our chance of finishing No. 1' : 'Our chance of qualifying',
          series: who.map((p, i) => ({ name: TA.playerShort(T, p), label: TA.playerSurname(T, p), color: QK.cssVar('--c-' + ((i % 8) + 1)), data: H.map(h => { const v = (h[key] || {})[p]; return isNum(v) ? v : null; }) })),
          today: H[H.length - 1].as_of, label: 'Chances over time' });
      };
      drawH('finals_qual');
      QK.seg(el.querySelector('#rc-h-k'), drawH);
    }
    TA.sortable(el);
    TA.setMeta(nS ? nS + ' season simulations' : '');
  });
}

TA.route('race', render);
})(window.TA);
