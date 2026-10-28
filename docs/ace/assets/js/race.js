/* The Quant Ace — the race (#/<T>/race), Design System 2.0.
 *
 *   stat tiles: our year-end No. 1 favourite, players virtually qualified, on the bubble, the simulations;
 *   Finals qualification: our chance from the rest-of-season simulation (chance bars and a table with race points,
 *     the gap to eighth and the simulated year-end points with their 5th-95th percentile range);
 *   year-end No. 1: our chances; where they finish: the simulated year-end rank as a heat map (both axes titled);
 *   chances over time from race.json "history" (one snapshot per simulation date; a note until three are on record);
 *   the events left in the simulation and what it assumes.
 * Round 5 (24 Oct 2026), through race-shape.js: the tiers (clinched / locks / bubble / long shots / out of reach) and the
 *   certain clinch lines (race.json bounds / status), the week's movers with their results, what is at stake in the
 *   next matches (race.json stakes), the contenders' profile cards (strengths and weak spots), and the shape of the
 *   tour (serve v return quadrant, surface strengths, ranking and rating movers).
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
  const T = params.tour, V = TA.v2, SH = TA.shape;
  const fin = T === 'atp' ? 'ATP Finals (Turin)' : 'WTA Finals (Riyadh)';
  if (TA.past && TA.past.is(T, params.year)) return TA.past.race(el, T, params.year);
  el.innerHTML = '<div id="rc-body">' + QK.skeleton('lines', 6) + '</div>';
  return TA.loadAll([TA.tpath('race.json', T), TA.tpath('rankings.json', T)]).then(arr => {
    if (!el.isConnected) return;
    const race = arr[0], rk = TA.ok(arr[1]) ? arr[1] : null;
    const body = document.getElementById('rc-body');
    if (!TA.ok(race)) { body.innerHTML = TA.card('Race', '', TA.notBuilt('The season simulation', race)); return; }
    const fq = race.finals_qual || {}, no1 = race.year_end_no1 || {}, ft = race.finals_title || {}, st = race.status || {}, bd = race.bounds || {};
    const pts = {};
    ((rk && rk.race) || []).forEach((r, i) => { pts[r[0]] = { pts: r[1], pos: i + 1 }; });
    let ptsNote = 'race points from the latest ranking, this week included';
    if (!Object.keys(pts).length && race.race && typeof race.race === 'object' && !Array.isArray(race.race)) {
      Object.keys(race.race).sort((a, b) => (race.race[b].now || 0) - (race.race[a].now || 0)).forEach((p, i) => { pts[p] = { pts: race.race[p].now, pos: i + 1 }; });
      ptsNote = 'race points when the season was last simulated';
    }
    const cutPts = ((rk && rk.race) || [])[7] ? rk.race[7][1] : null;
    const ids = Object.keys(fq).sort((a, b) => (fq[b] || 0) - (fq[a] || 0));
    const raceIds = Object.keys(pts).sort((a, b) => pts[a].pos - pts[b].pos);
    /* everyone the race tiers and cards look at: our order first, then the Race top 20 */
    const field = ids.concat(raceIds.slice(0, 20).filter(p => ids.indexOf(p) < 0));
    const nClinched = field.filter(p => st[p] === 'in').length;
    const top1 = Object.keys(no1).sort((a, b) => no1[b] - no1[a])[0];
    const bubble = ids.filter(p => (fq[p] || 0) > 0.05 && (fq[p] || 0) < 0.95);
    const nS = isNum(race.n_sims) ? Number(race.n_sims).toLocaleString('en-GB') : '';
    const H = SH.history(race);
    const since = H.length ? TA.fmtDate(H[0].as_of, { weekday: false, year: false }) : '';
    let html = '<div class="ta-kpis">' + QK.stats([
      { label: 'Year-end No. 1', value: top1 ? TA.playerSurname(T, top1) + ' ' + TA.pct(no1[top1], 0) : '—', signal: true, href: top1 ? TA.playerHref(T, top1) : null, sub: 'our chance, the favourite' },
      race.status ? { label: 'Clinched', value: String(nClinched) + ' of 8', sub: 'mathematically certain of a place' } : { label: 'Virtually qualified', value: String(ids.filter(p => (fq[p] || 0) >= 0.995).length), sub: 'our chance 99.5% or more' },
      { label: 'On the bubble', value: String(bubble.length), sub: 'our chance between 5% and 95%' },
      { label: 'Simulations', value: nS || '—', sub: (race.remaining_events || []).length + ' events left' + (race.as_of ? ' · from ' + TA.fmtDate(race.as_of, { year: false, weekday: false }) : '') }]) + '</div>' +
      QK.note('<b>How it works.</b> We play out every event left in the season ' + (nS || 'many') + ' times, match by match, with our win chances, and count how often each player ends up in the top eight. A 70% chance still misses about 3 times in 10.') + '<div style="height:var(--sp-5)"></div>';

    /* how the race is shaping up: tiers, the certain lines, then the chances and the table */
    html += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Race to the ' + fin.replace(/ \(.*\)$/, ''), title: 'Who’s in. Who’s chasing.',
      sub: 'Eight places. Who has one for certain, who is safe in our simulations, and who is still chasing.' }) +
      SH.tiersHTML(T, race, field, pts) + (race.status ? SH.clinchHTML(T, race, field) : '') + '</section>';
    html += '<div class="qk-grid"><div class="qk-span-5">' + V.card('Who makes it to the ' + esc(fin.replace(/ \(.*\)$/, '')), 'Our chance of a place at the ' + esc(fin), '<div id="rc-ch"></div>') + '</div><div class="qk-span-7">' +
      V.card('Finals qualification', esc(ptsNote) + '; the dashed line sits below eighth in our order', '<div id="rc-table"></div>', { flush: true,
        foot: '<span>The top eight in the race qualify' + (T === 'atp' ? '; a Slam champion ranked 9–20 takes the eighth place' : '') + '. “Most” is the Race total if the player won everything left, one event a week.</span>' }) + '</div></div>';

    /* the 538-style lines, the week's movers */
    html += '<section class="qk-section">' + V.card('Chances over time', 'Our chance after each simulation of the rest of the season' + (since ? '. Tracking since ' + esc(since) : ''),
      (H.length >= 2 ? V.seg('rc-h-k', [['finals_qual', 'Finals qualification'], ['year_end_no1', 'Year-end No. 1']], 'finals_qual', 'Chance') + V.chart('rc-hist', 340, 'Chances over time') +
        (H.length < 7 ? '<p class="ta-cap">Tracking since ' + esc(since) + ': ' + H.length + ' simulation dates so far, one a day from here. Earlier runs were not stored.</p>' : '')
        : '<p class="ta-cap" style="margin:0">' + (H.length ? 'Tracking since ' + esc(since) + ' with one simulation date so far' : 'The simulation has not recorded its history yet') +
          '. The lines appear with the second date; earlier runs were not stored.</p>')) + '</section>';
    html += '<section class="qk-section">' + V.card('Who moved this week', 'The biggest changes in our chance, with the results behind them',
      V.seg('rc-mv-k', [['finals_qual', 'Finals qualification'], ['year_end_no1', 'Year-end No. 1']], 'finals_qual', 'Chance') + '<div id="rc-mv"></div>') + '</section>';

    /* what is at stake next */
    const stQ = SH.stakesHTML(T, race, 'finals_qual', { limit: 8 }), stN = SH.stakesHTML(T, race, 'year_end_no1', { limit: 4 });
    if (stQ || stN) {
      html += '<section class="qk-section">' + QK.sectionHead({ kicker: 'What’s at stake', title: 'The matches that move the race',
        sub: 'For each contender, our chance if the next match at an event under way, or the first at one starting in the next ten days, is won or lost.' }) +
        (stQ ? '<h3 class="rs-h3">Finals qualification</h3>' + stQ : '') + (stN ? '<h3 class="rs-h3">Year-end No. 1</h3>' + stN : '') + '</section>';
    }

    /* strengths and weak spots */
    const cardIds = field.filter(p => (fq[p] || 0) >= 0.001 || (pts[p] && pts[p].pos <= 12));
    const cards = SH.cardsHTML(T, race, cardIds, { n: 8,
      sub: p => (pts[p] ? 'Race No. ' + pts[p].pos + ' · ' + TA.num(pts[p].pts, 0) + ' pts' : ''),
      badge: p => '<small>Finals</small>' + (st[p] === 'in' ? 'In' : st[p] === 'out' ? 'Out' : TA.pct(fq[p] || 0, (fq[p] || 0) > 0.995 || (fq[p] || 0) < 0.01 ? 1 : 0)) });
    if (cards) {
      html += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Player profiles', title: 'Strengths and weak spots',
        sub: 'Each contender’s season against the tour: percentiles among this season’s qualified players, from the metric set on the Model page.' }) + cards + '</section>';
    }

    /* shape of the tour */
    const quad = SH.quadrant(T, race, raceIds.slice(0, 24), 'rc-quad');
    const surf = SH.surfaceHTML(T, race, cardIds.length ? cardIds : raceIds.slice(0, 16));
    const mvR = SH.moversRankHTML(T, rk, race);
    if (quad.html || surf || mvR) {
      html += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Shape of the tour', title: 'How the contenders win',
        sub: 'Serve against return, the surfaces, and who is climbing.' }) + '<div class="qk-grid">' +
        (quad.html ? '<div class="qk-span-7">' + V.card('Serve v return', 'The Race top ' + Math.min(24, raceIds.length) + '; ratings inferred from scores, the dashed lines at this group’s average', quad.html) + '</div>' : '') +
        (surf ? '<div class="qk-span-5">' + V.card('Surface strengths', 'Surface Elo and its percentile (the box)', surf, { flush: true }) + '</div>' : '') + '</div>' +
        (mvR ? V.card('Movers', 'Official ranking moves in the top 100, and our Elo over the last 30 days in the top 50', mvR) : '') + '</section>';
    }

    html += '<section class="qk-section"><div class="qk-grid"><div class="qk-span-5">' + V.card('Year-end No. 1', 'Our chance of finishing the year ranked No. 1', '<div id="rc-no1"></div>') + '</div><div class="qk-span-7">' +
      V.card('Where they finish the year', 'Simulated year-end rank, 1–20; cells show the chance where it is 10% or more', V.chart('rc-heat', 420, 'Simulated year-end rank')) + '</div></div></section>';
    const rem = race.remaining_events || [];
    html += TA.card('Still to play', rem.length + ' event' + (rem.length === 1 ? '' : 's') + ' in the simulation',
      rem.length ? TA.tableHTML([{ label: 'Starts' }, { label: 'Event' }, { label: 'Level' }, { label: 'Surface', cls: 'hide-sm' }, { label: 'How it is simulated', cls: 'hide-sm' }], rem.map(e0 => {
        const e = typeof e0 === 'string' ? { id: e0 } : (e0 || {});
        const info = Object.assign({}, TA.eventInfo(T, e.id), e);
        return [{ v: info.start, html: esc(TA.fmtDate(info.start, { weekday: false, year: false })) },
          { v: info.name, html: info.start || info.name ? TA.eventLink(T, e.id, { surface: true, name: info.name }) : esc(TA.titleCase(e.id)) },
          { v: TA.levelRank(info.level), html: info.level ? esc(TA.levelLabel(info.level, T)) : '—' },
          { v: info.surface, html: info.surface ? TA.surfaceChip(info.surface, info.indoor) : '—', cls: 'hide-sm' },
          { v: info.method, html: info.method ? '<span class="muted-inline">' + esc(info.method) + '</span>' : '—', cls: 'hide-sm' }];
      }), { compact: true }) : TA.muted('The season is complete.')) +
      (race.simplifications ? TA.card('What the simulation assumes', '', '<div class="mk-explain">' + (Array.isArray(race.simplifications) ? race.simplifications.map(s => '<p>' + esc(s) + '</p>').join('') : esc(race.simplifications)) + '</div>') : '');
    body.innerHTML = html;
    el.querySelector('#rc-ch').innerHTML = QK.chances(ids.filter(p => fq[p] >= 0.001).slice(0, 16).map(p => ({ label: TA.playerShort(T, p), p: fq[p], href: TA.playerHref(T, p), sub: pts[p] ? TA.num(pts[p].pts, 0) + ' pts' : '' })), { max: 1, oursName: 'Our chance of qualifying' });
    const rows = ids.slice(0, 30).map((p, i) => {
      const r = pts[p] || {}, pr = (race.points || {})[p] || {};
      return { id: p, cut: i === 8, pos: r.pos, name: TA.playerShort(T, p), sub: TA.playerCountry(T, p), pts: r.pts, gap: isNum(cutPts) && isNum(r.pts) ? r.pts - cutPts : null,
        hi: (bd[p] || [])[1], st: st[p] || '', ye: pr.mean, lo: pr.p05, yhi: pr.p95, q: fq[p], t: ft[p] };
    });
    const cols = [
      { key: 'pos', label: 'Race', num: true, fmt: v => (isNum(v) ? String(v) : '—') },
      { key: 'name', label: 'Player', type: 'entity', sub: 'sub', href: r => TA.playerHref(T, r.id) },
      { key: 'pts', label: 'Points', num: true, fmt: v => TA.num(v, 0) },
      { key: 'gap', label: 'v 8th', num: true, fmt: v => (isNum(v) ? TA.signed(v, 0) : '—') }];
    if (race.bounds) cols.push({ key: 'hi', label: 'Most', num: true, tip: 'The most Race points still reachable: winning every event left, one a week', fmt: v => (isNum(v) ? TA.num(v, 0) : '—') });
    if (race.status) cols.push({ key: 'st', label: 'Status', fmt: v => (v === 'in' ? '<span class="rs-status in">Clinched</span>' : v === 'out' ? '<span class="rs-status out">Out</span>' : '') });
    cols.push({ key: 'ye', label: 'Year-end (5–95%)', num: true, fmt: (v, r) => (isNum(v) ? TA.num(v, 0) + ' <small class="muted-inline">' + TA.num(r.lo, 0) + '–' + TA.num(r.yhi, 0) + '</small>' : '—') },
      { key: 'q', label: 'Qualify', type: 'bar', max: 1, fmt: v => TA.pct(v, v > 0.995 || v < 0.01 ? 1 : 0) },
      { key: 't', label: 'Title', num: true, fmt: v => (isNum(v) ? TA.pct(v, 1) : '—') });
    QK.leaderboard(el.querySelector('#rc-table'), { dense: true, rowHref: r => TA.playerHref(T, r.id), rowClass: r => (r.cut ? 'cut' : ''), columns: cols, rows: rows });
    const items = Object.keys(no1).sort((a, b) => (no1[b] || 0) - (no1[a] || 0)).slice(0, 8).filter(p => (no1[p] || 0) >= 0.001).map(p => ({ label: TA.playerShort(T, p), p: no1[p], href: TA.playerHref(T, p) }));
    el.querySelector('#rc-no1').innerHTML = items.length ? QK.chances(items, { max: 1, oursName: 'Our chance' }) : QK.empty('No year-end No. 1 chances');
    rankHeat('#rc-heat', T, race, ids.length ? ids : Object.keys(race.rank_dist || {}));
    if (H.length >= 2) {
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
    const drawMv = key => { el.querySelector('#rc-mv').innerHTML = SH.moversHTML(T, race, key); };
    drawMv('finals_qual');
    QK.seg(el.querySelector('#rc-mv-k'), drawMv);
    quad.draw();
    SH.wire(el);
    TA.sortable(el);
    TA.setMeta(nS ? nS + ' season simulations' : '');
  });
}

TA.route('race', render);
})(window.TA);
