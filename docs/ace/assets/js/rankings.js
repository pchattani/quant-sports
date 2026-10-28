/* The Quant Ace — rankings (#/<T>/rankings, #/<T>/defend, #/<T>/profiles): three of the Rankings section's five views
 * (round 9: Official, Race, Elo, Points to defend, Profiles, one tab each; Race is race.js, Elo is elo.js).
 *
 *   official: the latest official ranking with weekly movement, next to each player's Elo rank
 *             (the gap shows who the ranking over- or under-rates), the race position and points to defend;
 *   defend:   the points each top player drops week by week over the coming year (a heat grid);
 *   profiles: strengths and weak spots of the top 32 as cards (race-shape.js, from race.json "profiles"); the
 *             official view carries the same plain-English chips in a column (round 5, 24 Oct 2026).
 * A finished season shows its season-end ranking (ta-past.js). Reads <T>/rankings.json and <T>/race.json. */
(function (TA) {
'use strict';

const esc = TA.esc;

function moveHTML(m) {
  if (!TA.isNum(m) || Number(m) === 0) return '<span class="muted-inline">–</span>';
  return Number(m) > 0 ? '<span class="mv-up">▲' + m + '</span>' : '<span class="mv-down">▼' + Math.abs(m) + '</span>';
}
function defendTotal(rows) { return (rows || []).reduce((a, r) => a + (TA.isNum(r[2]) ? Number(r[2]) : 0), 0); }

function official(T, rk, eloRank, raceRank, race) {
  const prof = TA.shape.profiles(race);
  const rows = (rk.official || []).slice(0, 200).map(r => {
    const pid = r[1], er = eloRank[pid];
    const gap = TA.isNum(er) ? r[0] - er : null;
    const fq = ((race || {}).finals_qual || {})[pid];
    return { _href: TA.playerHref(T, pid), cells: [
      { v: r[0], html: '<b>' + r[0] + '</b>' }, { v: r[3], html: moveHTML(r[3]), cls: 'hide-sm' },
      { v: TA.playerName(T, pid), html: TA.playerLink(T, pid, { country: true }) },
      { v: r[2], html: TA.num(r[2], 0) },
      { v: er, html: TA.isNum(er) ? String(er) : '—' },
      { v: gap, html: TA.isNum(gap) ? '<span class="rank-gap ' + (gap > 0 ? 'edge-pos' : gap < 0 ? 'edge-neg' : '') + '" title="' + (gap > 0 ? 'Elo ranks this player higher than the official ranking' : gap < 0 ? 'The official ranking is ahead of Elo' : '') + '">' + TA.signed(gap, 0) + '</span>' : '—', cls: 'hide-sm' },
      { v: raceRank[pid], html: TA.isNum(raceRank[pid]) ? String(raceRank[pid]) : '—', cls: 'hide-sm' },
      { v: defendTotal((rk.to_defend || {})[pid]), html: (rk.to_defend || {})[pid] ? TA.num(defendTotal(rk.to_defend[pid]), 0) : '—', cls: 'hide-sm' },
      { v: fq, html: TA.isNum(fq) ? TA.pct(fq, 0) : '—', cls: 'hide-sm' },
      { v: '', html: '<span class="rs-chips-cell">' + TA.shape.chipHTML(TA.shape.chips(prof(pid), 2)) + '</span>', cls: 'hide-sm' }
    ] };
  });
  if (!rows.length) return TA.muted('No official ranking yet.');
  return TA.tableHTML([{ label: 'Rank', align: 'right' }, { label: '±', title: 'Places moved since the previous ranking', cls: 'hide-sm' }, { label: 'Player' },
    { label: 'Points', align: 'right' }, { label: 'Elo rank', align: 'right' }, { label: 'Gap', align: 'right', title: 'Official rank minus Elo rank: positive means Elo rates the player higher', cls: 'hide-sm' },
    { label: 'Race', align: 'right', title: 'Position in the year-to-date race, this week\'s points included', cls: 'hide-sm' },
    { label: 'To defend', align: 'right', title: 'Points from the last 12 months that drop off over the coming year', cls: 'hide-sm' },
    { label: 'Finals', align: 'right', title: 'Model probability of qualifying for the Finals', cls: 'hide-sm' },
    { label: 'Strengths and weak spots', sortable: false, title: 'Plain-English reads of the season against the tour (percentiles among qualified players); hover a chip for the number', cls: 'hide-sm' }], rows, { compact: true, sticky: true });
}



/* to_defend rows are [event, when, points]: `when` is the drop-off date (ISO) or an ISO week number. */
function whenKey(w) { return typeof w === 'string' ? w.slice(0, 10) : String(w); }
function whenLabel(w) {
  if (typeof w === 'string' && /^\d{4}-\d\d-\d\d/.test(w)) return TA.fmtDate(w, { weekday: false, year: false });
  return 'W' + w;
}
function whenOrder(w) {
  if (typeof w === 'string') return w;
  const nowWk = isoWeek(new Date());
  return String(1000 + ((Number(w) - nowWk + 53) % 53));
}
function defend(T, rk) {
  const td = rk.to_defend || {};
  const offIds = (rk.official || []).slice(0, 30).map(r => r[1]).filter(p => td[p] && td[p].length);
  if (!offIds.length) return TA.muted('No points-to-defend data.');
  const whens = {};
  offIds.forEach(p => td[p].forEach(r => { whens[whenKey(r[1])] = r[1]; }));
  const keys = Object.keys(whens).sort((a, b) => whenOrder(whens[a]).localeCompare(whenOrder(whens[b])));
  const evOf = {};
  offIds.forEach(p => td[p].forEach(r => { (evOf[whenKey(r[1])] = evOf[whenKey(r[1])] || {})[r[0]] = 1; }));
  const max = Math.max.apply(null, [].concat.apply([], offIds.map(p => td[p].map(r => r[2] || 0)))) || 1;
  const sumAt = (p, k) => td[p].filter(r => whenKey(r[1]) === k).reduce((a, r) => a + (r[2] || 0), 0);
  const heat = heatTable({
    corner: 'Player', scale: 'seq', max: max,
    cols: keys.map(k => ({ label: whenLabel(whens[k]), title: Object.keys(evOf[k] || {}).map(e => TA.eventName(T, e, true)).join(', ') })),
    rows: offIds.map(p => ({ label: TA.playerLink(T, p, { surname: true, rank: true }), values: keys.map(k => (sumAt(p, k) ? sumAt(p, k) : null)),
      titles: keys.map(k => td[p].filter(r => whenKey(r[1]) === k).map(r => TA.eventName(T, r[0], true) + ': ' + r[2]).join(', ')) })),
    fmt: v => TA.num(v, 0)
  });
  const totals = keys.map(k => ({ k: k, pts: offIds.reduce((a, p) => a + sumAt(p, k), 0) })).filter(x => x.pts > 0).sort((a, b) => b.pts - a.pts).slice(0, 8);
  const big = '<div class="def-cal">' + totals.map(x => '<div class="def-wk"><div class="dw-h">' + esc(typeof whens[x.k] === 'string' ? 'Drops ' + whenLabel(whens[x.k]) : 'Week ' + whens[x.k]) + '</div><div class="dw-v">' + TA.num(x.pts, 0) + '</div><div class="dw-l">' +
    esc(Object.keys(evOf[x.k] || {}).map(e => TA.eventName(T, e)).join(', ')) + '</div></div>').join('') + '</div>';
  return '<div class="section-note">Points the top 30 earned in the last 12 months, by the date they drop off the ranking. A player who repeats last year’s result keeps them; anything less loses ranking points. Hover a cell for the event.</div>' +
    heat + '<div class="day-head">The heaviest drop-offs across the top 30</div>' + big;
}
/* the points-to-defend grid: players down the side, drop-off weeks across, each cell shaded by its points (round 9: the
   chart helper it once called was never shipped, so the view failed) */
function heatTable(o) {
  const max = o.max || 1;
  return '<div class="qk-table-wrap ta-heat"><table class="qk-table dense"><thead><tr><th>' + esc(o.corner || '') + '</th>' +
    o.cols.map(c => '<th class="num"' + (c.title ? ' title="' + esc(c.title) + '"' : '') + '>' + esc(c.label) + '</th>').join('') + '</tr></thead><tbody>' +
    o.rows.map(r => '<tr><td>' + r.label + '</td>' + r.values.map((v, i) => TA.isNum(v)
      ? '<td class="num" style="background:' + TA.seqColour(v / max) + '"' + ((r.titles || [])[i] ? ' title="' + esc(r.titles[i]) + '"' : '') + '>' + esc(o.fmt ? o.fmt(v) : v) + '</td>'
      : '<td class="num muted-inline">·</td>').join('') + '</tr>').join('') + '</tbody></table></div>';
}
function isoWeek(d) {
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const day = t.getUTCDay() || 7;
  t.setUTCDate(t.getUTCDate() + 4 - day);
  const y0 = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
  return Math.ceil(((t - y0) / 86400000 + 1) / 7);
}

function profiles(T, rk, race) {
  const ids = (rk.official || []).slice(0, 32).map(r => r[1]);
  const off = {};
  (rk.official || []).forEach(r => { off[r[1]] = r; });
  const html = TA.shape.cardsHTML(T, race, ids, { n: 12, sub: p => (off[p] ? 'No. ' + off[p][0] + ' · ' + TA.num(off[p][2], 0) + ' ranking points' : ''),
    badge: p => { const q = ((race || {}).finals_qual || {})[p]; return TA.isNum(q) && q >= 0.001 ? '<small>Finals</small>' + TA.pct(q, q > 0.995 || q < 0.01 ? 1 : 0) : ''; } });
  return html || TA.muted('Player profiles come with the season simulation’s next build.');
}


/* A finished season (round 9): the season-end official ranking from that year's catalogue (ta-past.js); Elo is the Elo
   view's, and the points to defend and the profiles belong to the season in play. */
function renderPast(el, T, Y, view) {
  el.innerHTML = '<div id="rk-body">' + QK.skeleton('lines', 8) + '</div>';
  return TA.past.cat(T, Y).then(cat => {
    if (!el.isConnected) return;
    const body = document.getElementById('rk-body');
    if (!cat) { body.innerHTML = TA.card('Rankings ' + Y, '', TA.muted('The ' + Y + ' season file is not on the site.')); return; }
    const other = view === 'defend' || view === 'profiles';
    body.innerHTML = TA.past.band(T, Y, cat) + (other ? QK.note('<b>' + (view === 'defend' ? 'Points to defend' : 'Profiles') + '</b> belong to the season in play. <a href="' + TA.href(T, view) + '">See them for ' + TA.currentYear(T) + ' →</a>') : '') +
      '<div class="card"><div class="card-header">Official ranking, the season’s end <span class="card-sub">' + Y + ' · each player’s ranking at their last tour-level match, beside our Elo</span></div><div id="rk-view"></div></div>' + TA.past.note(Y);
    const v = document.getElementById('rk-view');
    v.innerHTML = TA.past.officialTable(T, Y, cat);
    TA.sortable(v);
    if (TA.v2 && TA.v2.oursHeads) TA.v2.oursHeads(v, { Elo: 'elo', 'Elo rank': 'elo_rank' });
    TA.setMeta(TA.tourName(T) + ' ' + Y + ' · the season’s end');
  });
}

/* Round 9 (Phase 2): Rankings is one page with views, each a tab of the section: Official (#/<T>/rankings), Race
   (#/<T>/race, race.js), Elo (#/<T>/elo, elo.js), Points to defend (#/<T>/defend) and Profiles (#/<T>/profiles). The old
   ?v= links land on their tab (core.js redirectOf). The tour's leaders on each number are the Scouting Room's Leaders. */
function render(el, params, state) {
  const T = params.tour;
  const route = (state && state.route) || 'rankings';
  let view = route === 'defend' || route === 'profiles' ? route : 'official';
  if (TA.past && TA.past.is(T, params.year)) return renderPast(el, T, params.year, view);
  el.innerHTML = '<div id="rk-body">' + QK.skeleton('lines', 8) + '</div>';
  return TA.loadAll([TA.tpath('rankings.json', T), TA.tpath('race.json', T)]).then(arr => {
    if (!el.isConnected) return;
    const rk = arr[0], race = TA.ok(arr[1]) ? arr[1] : null;
    const body = document.getElementById('rk-body');
    if (!TA.ok(rk)) { body.innerHTML = TA.card('Rankings', '', TA.notBuilt('The rankings payload', rk)); return; }
    const eloRank = {}, raceRank = {};
    (rk.elo || []).forEach(r => { eloRank[r[1]] = r[0]; });
    (rk.race || []).forEach((r, i) => { raceRank[r[0]] = i + 1; });
    const subs = { official: 'as of ' + esc(TA.fmtDate(rk.date)) + ' · Elo rank and race position beside each player',
      profiles: 'the top 32: percentiles among this season’s qualified players, with a plain-English read of each', defend: 'points dropping off over the next 12 months' };
    const titles = { official: 'The official ranking', profiles: 'Strengths and weak spots', defend: 'Points to defend' };
    let band = '';
    if (view === 'official') {
      /* v4: the black power list of this week's biggest climbers inside the top 100 (places gained since the last ranking) */
      const climb = (rk.official || []).filter(r => r[0] <= 100 && TA.isNum(r[3]) && r[3] > 0).sort((a, b) => b[3] - a[3] || a[0] - b[0]).slice(0, 5);
      band = climb.length >= 3 ? QK.band(QK.sectionHead({ kicker: 'Who’s climbing', title: 'The week’s big movers', sub: 'The biggest climbs inside the top 100 since the last ranking. Points come from the last 52 weeks, so a deep run lifts a player straight away.' }) +
        QK.hotRow(climb.map(r => ({ sport: 'tennis', kicker: TA.tourName(T) + ' · up ' + r[3] + ' place' + (r[3] === 1 ? '' : 's'), title: 'Ranked No. ' + r[0], name: TA.playerShort(T, r[1]), value: '#' + r[0], href: TA.playerHref(T, r[1]),
          expl: TA.num(r[2], 0) + ' ranking points' + (TA.isNum(eloRank[r[1]]) ? '; No. ' + eloRank[r[1]] + ' by our Elo.' : '.') }))), { cls: 'ta-rk-band' }) : '';
    }
    body.innerHTML = band + '<div class="card"><div class="card-header">' + esc(titles[view]) + ' <span class="card-sub">' + subs[view] + '</span></div><div id="rk-view"></div></div>' +
      (view === 'official' ? QK.note('<b>Ranking or Elo?</b> The official ranking adds up points from the last 52 weeks, so it rewards playing a lot and going deep. Our Elo rates every result by who it came against, so it moves faster after an upset. A 100-point Elo gap means the higher-rated player wins about 64% of the time. <a href="' + TA.href(T, 'elo') + '">The Elo view →</a>') : '') +
      '<p class="ta-moved">Who leads the tour on each number, top five and bottom three: <a href="' + TA.href(T, 'scout') + '?view=leaders">the Scouting Room’s Leaders →</a></p>';
    const v = document.getElementById('rk-view');
    v.innerHTML = view === 'defend' ? defend(T, rk) : view === 'profiles' ? profiles(T, rk, race) : official(T, rk, eloRank, raceRank, race);
    TA.sortable(v);
    TA.shape.wire(v);
    if (TA.v2 && TA.v2.oursHeads) TA.v2.oursHeads(v, { 'Elo rank': 'elo_rank', 'Finals (our chance)': 'p_finals', Finals: 'p_finals' });
    TA.setMeta('Official ranking of ' + esc(TA.fmtDate(rk.date, { year: false })));
  });
}

TA.route('rankings', render);
TA.route('defend', render);
TA.route('profiles', render);
})(window.TA);
