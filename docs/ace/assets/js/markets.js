/* The Quant Ace — Forecasts (#/<T>/markets; the old "odds board" route), Design System 2.0.
 *
 *   stat tiles: open matches with our forecast, our biggest favourite, the closest call, tournaments in play;
 *   every open match: v2 game cards with our win chance, the likeliest score and expected games, and the same
 *     numbers in a sortable table;
 *   title chances in every tournament in play (from simulating the draw), the race to the Finals and the year-end
 *     No. 1 (from simulating the season).
 * Our forecast is the headline; the market appears only on the match centre and the Model pages, as a reference.
 *
 * Reads the MATCH_CARDs in index.json (live, today, upcoming), <T>/race.json and the in-play events' payloads. Cards
 * still live or upcoming 12 hours after their start are dropped (TA.fresh). */
(function (TA) {
'use strict';

const esc = TA.esc, isNum = TA.isNum;

function render(el, params) {
  const T = params.tour;
  const V = TA.v2;
  const info = TA.tourInfo(T);
  const evNow = info.events_now || [];
  el.innerHTML = QK.skeleton('card', 3);
  return TA.loadAll([TA.tpath('race.json', T)].concat(evNow.map(e => TA.eventPath(T, e.event)))).then(arr => {
    if (!el.isConnected) return;
    const race = TA.ok(arr[0]) ? arr[0] : null;
    const seen = {};
    const open = TA.fresh([].concat(info.live || [], info.today || [], info.upcoming || [])).filter(c => c && !TA.isFinished(c) && !seen[c.id] && (seen[c.id] = 1))
      .sort((a, b) => (TA.matchState(a) === 'live' ? -1 : 0) - (TA.matchState(b) === 'live' ? -1 : 0) || String(a.date).localeCompare(String(b.date)));
    const withP = open.filter(c => c.model && isNum(c.model.p1));
    const fav = p1 => Math.max(p1, 1 - p1);
    const big = withP.slice().sort((a, b) => fav(b.model.p1) - fav(a.model.p1))[0];
    const close = withP.slice().sort((a, b) => fav(a.model.p1) - fav(b.model.p1))[0];
    const favOf = c => (c.model.p1 >= 0.5 ? c.p1 : c.p2);
    const tiles = [
      { label: 'Open matches', value: String(withP.length), sub: open.length > withP.length ? (open.length - withP.length) + ' without a forecast yet' : 'each with our win chance' },
      big ? { label: 'Biggest favourite', value: TA.playerSurname(T, favOf(big)) + ' ' + TA.pct(fav(big.model.p1), 0), signal: true, href: TA.matchHref(T, big.id), sub: 'v ' + TA.playerSurname(T, favOf(big) === big.p1 ? big.p2 : big.p1) + ' · ' + TA.eventName(T, big.event) } : null,
      close && close !== big ? { label: 'Closest call', value: TA.playerSurname(T, favOf(close)) + ' ' + TA.pct(fav(close.model.p1), 0), href: TA.matchHref(T, close.id), sub: 'v ' + TA.playerSurname(T, favOf(close) === close.p1 ? close.p2 : close.p1) + ' · ' + TA.eventName(T, close.event) } : null,
      { label: 'Tournaments in play', value: String(evNow.length), sub: evNow.map(e => e.name || TA.eventName(T, e.event)).join(' · ') || 'none this week', text: false }
    ];
    let h = '<div class="ta-kpis">' + QK.stats(tiles) + '</div>';
    h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Matches', title: 'Every open match', sub: 'Our win chance before the first ball, the likeliest score in sets and the expected number of games. Tap a card for the match centre.' }) +
      (open.length ? '<div class="ta-gc-grid">' + open.slice(0, 24).map(c => TA.matchCard(c, { tour: T })).join('') + '</div>' +
        '<div style="margin-top:var(--sp-4)">' + V.card('The same numbers', 'Sortable; the favourite first in each row', '<div id="fc-table"></div>', { flush: true }) + '</div>'
        : V.card('Matches', '', QK.empty('No open matches', 'Nothing is scheduled with a forecast right now: see the tournaments for the latest results.'))) + '</section>';
    const evs = [];
    evNow.forEach((e, i) => { const d = arr[1 + i]; if (TA.ok(d) && d.sim && d.sim.players && !(d.event || {}).champion) evs.push([e, d]); });
    h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Tournaments', title: 'Title chances', sub: 'From simulating the rest of each draw, match by match, with our win chance for every possible meeting.' }) +
      (evs.length ? '<div class="qk-grid">' + evs.map((x, i) => '<div class="qk-span-6">' + V.card(x[0].name || TA.eventName(T, x[0].event), [TA.levelLabel(x[0].level, T), TA.surfaceLabel(x[0].surface), x[1].sim.n_sims ? Number(x[1].sim.n_sims).toLocaleString('en-GB') + ' simulated draws' : ''].filter(Boolean).join(' · '),
        '<div id="fc-ev-' + i + '"></div>', { foot: '<span></span><a href="' + TA.eventHref(T, x[0].event) + '">The draw and every path →</a>' }) + '</div>').join('') + '</div>'
        : V.card('Title chances', '', QK.empty('No tournament in play', 'Title chances appear once a draw is out.'))) + '</section>';
    const fq = race ? Object.keys(race.finals_qual || {}).map(p => ({ label: TA.playerShort(T, p), p: race.finals_qual[p], href: TA.playerHref(T, p) })).filter(r => isNum(r.p) && r.p > 0.001) : [];
    const n1 = race ? Object.keys(race.year_end_no1 || {}).map(p => ({ label: TA.playerShort(T, p), p: race.year_end_no1[p], href: TA.playerHref(T, p) })).filter(r => isNum(r.p)) : [];
    const ft = race ? Object.keys(race.finals_title || {}).map(p => ({ label: TA.playerShort(T, p), p: race.finals_title[p], href: TA.playerHref(T, p) })).filter(r => isNum(r.p) && r.p > 0.001) : [];
    if (fq.length || n1.length) {
      h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Season', title: 'The rest of the year', sub: 'From ' + (race.n_sims ? Number(race.n_sims).toLocaleString('en-GB') + ' ' : '') + 'simulations of the remaining calendar' + (race.as_of ? ', as of ' + esc(TA.fmtDate(race.as_of, { year: false, weekday: false })) : '') + '.' }) + '<div class="qk-grid">' +
        (fq.length ? '<div class="qk-span-4">' + V.card('Qualify for the ' + (T === 'wta' ? 'WTA' : 'ATP') + ' Finals', 'Our chance', QK.chances(fq, { limit: 14, max: 1, oursName: 'Our chance' }), { foot: '<span></span><a href="' + TA.href(T, 'race') + '">The race →</a>' }) + '</div>' : '') +
        (ft.length ? '<div class="qk-span-4">' + V.card('Win the Finals', 'Our chance', QK.chances(ft, { limit: 10, oursName: 'Our chance' })) + '</div>' : '') +
        (n1.length ? '<div class="qk-span-4">' + V.card('Year-end No. 1', 'Our chance', QK.chances(n1, { max: 1, oursName: 'Our chance' })) + '</div>' : '') + '</div></section>';
    }
    el.innerHTML = h;
    evs.forEach((x, i) => {
      const sim = x[1].sim.players;
      const rows = Object.keys(sim).filter(p => (sim[p].p_title || 0) > 0).map(p => ({ label: TA.playerShort(T, p), p: sim[p].p_title, href: TA.playerHref(T, p), sub: isNum(TA.playerRank(T, p)) ? 'No. ' + TA.playerRank(T, p) : '' }));
      el.querySelector('#fc-ev-' + i).innerHTML = rows.length ? QK.chances(rows, { limit: 10, oursName: 'Our title chance' }) : QK.empty('No title chances yet');
    });
    const tb = el.querySelector('#fc-table');
    if (tb) {
      QK.table(tb, { dense: true, sort: { key: 'date', dir: 'asc' }, rowHref: r => TA.matchHref(T, r.id), columns: [
        { key: 'date', label: 'Starts', fmt: (v, r) => esc(r.tba ? TA.fmtDate(v, { year: false }) + ' · TBA' : TA.fmtDate(v, { year: false, time: true })) },
        { key: 'match', label: 'Match', sticky: true, fmt: (v, r) => '<a href="' + TA.matchHref(T, r.id) + '"><b>' + esc(v) + '</b></a>' + (r.live ? ' <span class="live-dot"></span>' : '') },
        { key: 'ev', label: 'Event' }, { key: 'p', label: 'Our chance', num: true, fmt: v => (isNum(v) ? '<b style="color:var(--signal)">' + TA.pct(v, 0) + '</b>' : '—') },
        { key: 'score', label: 'Likeliest score', fmt: v => esc(v) }, { key: 'games', label: 'Exp. games', num: true, fmt: v => TA.num(v, 1) }],
      rows: open.map(c => {
        const m = c.model || {}, f1 = isNum(m.p1) && m.p1 >= 0.5;
        const a = f1 ? c.p1 : c.p2, b = f1 ? c.p2 : c.p1;
        const top = (m.sets_dist_top || [])[0];
        return { id: c.id, date: c.date, tba: !!c.tba || String(c.date || '').length <= 10, live: TA.matchState(c) === 'live', match: TA.playerSurname(T, a) + ' v ' + TA.playerSurname(T, b),
          ev: TA.eventName(T, c.event) + ' · ' + TA.roundLabel(c.round, true), p: isNum(m.p1) ? Math.max(m.p1, 1 - m.p1) : null, score: top ? (f1 ? top[0] : String(top[0]).split('-').reverse().join('-')) + ' (' + TA.pct(top[1], 0) + ')' : '—', games: m.exp_games };
      }) });
    }
    TA.setMeta(withP.length + ' open match' + (withP.length === 1 ? '' : 'es') + ' with our forecast');
  });
}

TA.route('markets', render);
})(window.TA);
