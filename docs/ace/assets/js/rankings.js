/* The Quant Ace — rankings (#/<T>/rankings).
 *
 *   official: the latest official ranking with weekly movement, next to each player's Elo rank
 *             (the gap shows who the ranking over- or under-rates), the race position and points to defend;
 *   elo: the Elo ranking with surface ratings and the official rank beside it;
 *   race: the year-to-date race with the Finals cut;
 *   to defend: the points each top player drops week by week over the coming year (a heat grid).
 *
 * ?v=official|elo|race|defend picks the view. Reads <T>/rankings.json and <T>/race.json. */
(function (TA) {
'use strict';

const esc = TA.esc;
const VIEWS = [{ key: 'official', label: 'Official' }, { key: 'elo', label: 'Elo' }, { key: 'race', label: 'Race' }, { key: 'defend', label: 'Points to defend' }];

function moveHTML(m) {
  if (!TA.isNum(m) || Number(m) === 0) return '<span class="muted-inline">–</span>';
  return Number(m) > 0 ? '<span class="mv-up">▲' + m + '</span>' : '<span class="mv-down">▼' + Math.abs(m) + '</span>';
}
function defendTotal(rows) { return (rows || []).reduce((a, r) => a + (TA.isNum(r[2]) ? Number(r[2]) : 0), 0); }

function official(T, rk, eloRank, raceRank, race) {
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
      { v: fq, html: TA.isNum(fq) ? TA.pct(fq, 0) : '—', cls: 'hide-sm' }
    ] };
  });
  if (!rows.length) return TA.muted('No official ranking yet.');
  return TA.tableHTML([{ label: 'Rank', align: 'right' }, { label: '±', title: 'Places moved since the previous ranking', cls: 'hide-sm' }, { label: 'Player' },
    { label: 'Points', align: 'right' }, { label: 'Elo rank', align: 'right' }, { label: 'Gap', align: 'right', title: 'Official rank minus Elo rank: positive means Elo rates the player higher', cls: 'hide-sm' },
    { label: 'Race', align: 'right', title: 'Position in the year-to-date race', cls: 'hide-sm' },
    { label: 'To defend', align: 'right', title: 'Points from the last 12 months that drop off over the coming year', cls: 'hide-sm' },
    { label: 'Finals', align: 'right', title: 'Model probability of qualifying for the Finals', cls: 'hide-sm' }], rows, { compact: true, sticky: true });
}

function elo(T, rk, offRank) {
  const rows = (rk.elo || []).slice(0, 200).map(r => {
    const sf = r[3] || {};
    return { _href: TA.playerHref(T, r[1]), cells: [{ v: r[0], html: '<b>' + r[0] + '</b>' }, { v: TA.playerName(T, r[1]), html: TA.playerLink(T, r[1], { country: true }) },
      { v: r[2], html: '<b>' + TA.num(r[2], 0) + '</b>' }].concat(['hard', 'clay', 'grass'].map(s => ({ v: sf[s], html: TA.isNum(sf[s]) ? TA.num(sf[s], 0) : '—', cls: s === 'grass' ? 'hide-sm' : '' })),
      [{ v: offRank[r[1]], html: TA.isNum(offRank[r[1]]) ? String(offRank[r[1]]) : '—' }]) };
  });
  if (!rows.length) return TA.muted('No Elo ranking yet.');
  return TA.tableHTML([{ label: 'Rank', align: 'right' }, { label: 'Player' }, { label: 'Elo', align: 'right' },
    { label: 'Hard', align: 'right' }, { label: 'Clay', align: 'right' }, { label: 'Grass', align: 'right', cls: 'hide-sm' }, { label: 'Official', align: 'right' }], rows, { compact: true, sticky: true }) +
    '<a class="more-link" href="' + TA.href(T, 'elo') + '">Elo histories and all-time peaks →</a>';
}

function raceView(T, rk, race, offRank) {
  const list = rk.race || [];
  if (!list.length) return TA.muted('The race starts with the first tournament of the year.');
  const cut = list[7] ? list[7][1] : null;
  const rows = list.slice(0, 60).map((r, i) => {
    const fq = ((race || {}).finals_qual || {})[r[0]];
    return { _href: TA.playerHref(T, r[0]), _class: i === 8 ? 'cut' : '', cells: [{ v: i + 1, html: '<b>' + (i + 1) + '</b>' }, { v: TA.playerName(T, r[0]), html: TA.playerLink(T, r[0], { country: true }) },
      { v: r[1], html: TA.num(r[1], 0) }, { v: TA.isNum(cut) ? r[1] - cut : null, html: TA.isNum(cut) && i !== 7 ? TA.signed(r[1] - cut, 0) : (i === 7 ? '<span class="muted-inline">8th</span>' : '—'), cls: 'hide-sm' },
      { v: offRank[r[0]], html: TA.isNum(offRank[r[0]]) ? String(offRank[r[0]]) : '—', cls: 'hide-sm' }, { v: fq, html: TA.isNum(fq) ? TA.probCell(fq) : '—' }] };
  });
  return TA.tableHTML([{ label: '#', align: 'right' }, { label: 'Player' }, { label: 'Race points', align: 'right' }, { label: 'v 8th', align: 'right', title: 'Points ahead of (or behind) the eighth place, the last automatic Finals place', cls: 'hide-sm' },
    { label: 'Official', align: 'right', cls: 'hide-sm' }, { label: 'Finals (model)' }], rows, { compact: true }) +
    '<div class="section-note">The dashed line marks the top eight, the automatic Finals places (a Grand Slam champion ranked 9th to 20th can take the last place at the ATP Finals). ' +
    '<a href="' + TA.href(T, 'race') + '">The full race simulation →</a></div>';
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
  const heat = TA.charts.heatTable({
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
function isoWeek(d) {
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const day = t.getUTCDay() || 7;
  t.setUTCDate(t.getUTCDate() + 4 - day);
  const y0 = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
  return Math.ceil(((t - y0) / 86400000 + 1) / 7);
}

function render(el, params) {
  const T = params.tour;
  let view = (params.query || {}).v;
  if (!VIEWS.some(v => v.key === view)) view = 'official';
  el.innerHTML = TA.pageHead(TA.tourName(T) + ' rankings', 'The official ranking against Elo, the race and points to defend',
    '<a href="' + TA.href(T, 'race') + '">Race</a><a href="' + TA.href(T, 'elo') + '">Elo</a>') + '<div id="rk-body"><div class="muted">Loading…</div></div>';
  return TA.loadAll([TA.tpath('rankings.json', T), TA.tpath('race.json', T)]).then(arr => {
    if (!el.isConnected) return;
    const rk = arr[0], race = TA.ok(arr[1]) ? arr[1] : null;
    const body = document.getElementById('rk-body');
    if (!TA.ok(rk)) { body.innerHTML = TA.card('Rankings', '', TA.notBuilt('The rankings payload', rk)); return; }
    const eloRank = {}, offRank = {}, raceRank = {};
    (rk.elo || []).forEach(r => { eloRank[r[1]] = r[0]; });
    (rk.official || []).forEach(r => { offRank[r[1]] = r[0]; });
    (rk.race || []).forEach((r, i) => { raceRank[r[0]] = i + 1; });
    const subs = { official: 'as of ' + esc(TA.fmtDate(rk.date)) + ' · Elo rank and race position beside each player',
      elo: 'surface-blended Elo; surface columns are the surface ratings', race: 'points won this calendar year', defend: 'points dropping off over the next 12 months' };
    body.innerHTML = '<div class="card"><div class="toggle-row" id="rk-tabs">' + TA.toggles(VIEWS, view, 'data-v') + '</div><div class="section-note" id="rk-sub"></div><div id="rk-view"></div></div>';
    const show = k => {
      view = k;
      document.getElementById('rk-sub').innerHTML = subs[k];
      const v = document.getElementById('rk-view');
      v.innerHTML = k === 'elo' ? elo(T, rk, offRank) : k === 'race' ? raceView(T, rk, race, offRank) : k === 'defend' ? defend(T, rk) : official(T, rk, eloRank, raceRank, race);
      TA.sortable(v);
    };
    show(view);
    TA.wireToggles(document.getElementById('rk-tabs'), 'data-v', show);
    TA.setMeta('Official ranking of ' + esc(TA.fmtDate(rk.date, { year: false })));
  });
}

TA.route('rankings', render);
})(window.TA);
