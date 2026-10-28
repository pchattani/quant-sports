/* The Quant Ace — past seasons (round 9, 28 Oct 2026). The year picker reaches back to 2000 (ATP) and 2007 (WTA), but
 * rankings.json, race.json and elo.json describe only the season in play. A finished year reads its own files instead:
 *   <T>/<Y>/players.json  the season's catalogue: each player's official ranking at their last tour-level match of the
 *                         year ("rank"), the season-end Elo overall and by surface, the record and the titles;
 *   <T>/<Y>/events.json   the year's tournaments with their champions and runners-up (loaded by core before a page).
 *
 *   TA.past.is(T, Y)                    a finished season (Y before the tour's current year)
 *   TA.past.cat(T, Y)                   -> Promise of the catalogue (or null)
 *   TA.past.ranked(cat)                 [{ id, p }] by the season-end official ranking
 *   TA.past.byElo(cat, key)             [{ id, p }] by a season-end Elo ('elo', 'elo_hard', 'elo_clay', 'elo_grass')
 *   TA.past.champions(T, Y)             { slams: [event], finals: event | null } from events.json
 *   TA.past.band(T, Y, cat)             the black power list: the Slam and Finals champions and the season-end No. 1
 *   TA.past.officialTable(T, Y, cat)    the season-end ranking table (top 200)
 *   TA.past.eloTable(T, Y, cat, key)    the season-end Elo table (top 200)
 *   TA.past.race(el, T, Y)              the Race page for a finished season: who won the Finals, the season-end top 10
 * Older-browser rule: no optional chaining, no nullish coalescing. */
(function (TA) {
'use strict';

const esc = TA.esc, isNum = TA.isNum;
const P = TA.past = {};
const SLAM_ORDER = ['australian-open', 'roland-garros', 'french-open', 'wimbledon', 'us-open'];

P.is = (T, Y) => isNum(Y) && Number(Y) < TA.currentYear(T);
P.cat = (T, Y) => TA.load(T + '/' + Y + '/players.json').then(d => (TA.ok(d) && d.players ? d : null));
const val = (p, k) => { const v = ((p || {}).values || {})[k]; return isNum(v) ? Number(v) : null; };
P.val = val;
P.ranked = cat => Object.keys((cat || {}).players || {}).map(id => ({ id: id, p: cat.players[id] })).filter(x => isNum(x.p.rank)).sort((a, b) => a.p.rank - b.p.rank);
P.byElo = (cat, key) => Object.keys((cat || {}).players || {}).map(id => ({ id: id, p: cat.players[id] })).filter(x => isNum(val(x.p, key || 'elo')) && (x.p.matches || 0) >= 10)
  .sort((a, b) => val(b.p, key || 'elo') - val(a.p, key || 'elo'));
P.events = (T, Y) => { const ev = (TA.EVENTS[T] || {})[String(Y)] || {}; return Object.keys(ev).map(id => Object.assign({ id: id }, ev[id])); };
P.champions = (T, Y) => {
  const all = P.events(T, Y);
  const slamKey = e => { const i = SLAM_ORDER.findIndex(s => String(e.tid || e.id).indexOf(s) === 0); return i < 0 ? 9 : i; };
  const slams = all.filter(e => e.level === 'slam').sort((a, b) => slamKey(a) - slamKey(b) || String(a.start).localeCompare(String(b.start)));
  const finals = all.filter(e => e.level === 'finals').sort((a, b) => String(b.start).localeCompare(String(a.start)))[0] || null;
  return { slams: slams, finals: finals };
};
/* the black power list of the finished season: who won the majors and the Finals, and the season-end No. 1 */
P.band = (T, Y, cat) => {
  const ch = P.champions(T, Y), items = [], P0 = (cat || {}).players || {};
  /* the big number is the champion's ranking at the season's end */
  const card = e => { const rk = (P0[e.champion] || {}).rank; return { sport: 'tennis', kicker: e.name || TA.eventName(T, e.id), name: TA.playerShort(T, e.champion), value: isNum(rk) ? '#' + rk : '—',
    title: (e.runner_up ? 'beat ' + TA.playerSurname(T, e.runner_up) + ' in the final' : 'champion') + (isNum(rk) ? ' · No. ' + rk + ' at the season’s end' : ''), href: TA.eventHref(T, e.id) }; };
  ch.slams.forEach(e => { if (e.champion) items.push(card(e)); });
  if (ch.finals && ch.finals.champion) items.push(card(ch.finals));
  const no1 = P.ranked(cat)[0];
  if (no1 && items.length < 6) items.push({ sport: 'tennis', kicker: 'No. 1 at the season’s end', name: no1.p.short || no1.p.name, value: '#1', title: (val(no1.p, 'wins') || 0) + '-' + (val(no1.p, 'losses') || 0) + ' · ' + (val(no1.p, 'titles') || 0) + ' titles', href: TA.playerHref(T, no1.id, Y) });
  if (!items.length) return '';
  return QK.band(QK.sectionHead({ kicker: Y + ' · the season in one line', title: 'Who won ' + Y, sub: 'The Grand Slam and Finals champions and the player ranked No. 1 at the season’s end. Open one for the draw.' }) + QK.hotRow(items, { rank: false }), { cls: 'ta-past-band' });
};
const rec = p => { const w = val(p, 'wins'), l = val(p, 'losses'); return isNum(w) && isNum(l) ? w + '-' + l : '—'; };
P.officialTable = (T, Y, cat) => {
  const list = P.ranked(cat).slice(0, 200);
  if (!list.length) return TA.muted('No season-end ranking on file for ' + Y + '.');
  const eloRank = {};
  P.byElo(cat, 'elo').forEach((x, i) => { eloRank[x.id] = i + 1; });
  return TA.tableHTML([{ label: 'Rank', align: 'right' }, { label: 'Player' }, { label: 'Record', align: 'right', title: 'Tour-level main-draw wins and losses in ' + Y },
    { label: 'Titles', align: 'right' }, { label: 'Elo', align: 'right' }, { label: 'Elo rank', align: 'right', title: 'Rank by season-end Elo among players with 10+ matches' },
    { label: 'Games won', align: 'right', cls: 'hide-sm' }], list.map(x => ({ _href: TA.playerHref(T, x.id, Y), cells: [
    { v: x.p.rank, html: '<b>' + x.p.rank + '</b>' }, { v: x.p.name, html: TA.playerLink(T, x.id, { name: x.p.name, country: true, year: Y }) },
    { v: val(x.p, 'wins'), html: rec(x.p) }, { v: val(x.p, 'titles'), html: isNum(val(x.p, 'titles')) ? String(val(x.p, 'titles')) : '—' },
    { v: val(x.p, 'elo'), html: isNum(val(x.p, 'elo')) ? TA.num(val(x.p, 'elo'), 0) : '—' }, { v: eloRank[x.id], html: isNum(eloRank[x.id]) ? String(eloRank[x.id]) : '—' },
    { v: val(x.p, 'games_won_pct'), html: isNum(val(x.p, 'games_won_pct')) ? TA.pct(val(x.p, 'games_won_pct'), 1) : '—', cls: 'hide-sm' }] })), { compact: true, sticky: true });
};
P.eloTable = (T, Y, cat, key) => {
  const k = key || 'elo', list = P.byElo(cat, k).slice(0, 200);
  if (!list.length) return TA.muted('No season-end ratings on file for ' + Y + '.');
  const cell = (p, kk) => ({ v: val(p, kk), html: isNum(val(p, kk)) ? (kk === k ? '<b>' + TA.num(val(p, kk), 0) + '</b>' : TA.num(val(p, kk), 0)) : '—' });
  return TA.tableHTML([{ label: 'Rank', align: 'right' }, { label: 'Player' }, { label: 'Elo', align: 'right' }, { label: 'Hard', align: 'right' }, { label: 'Clay', align: 'right' },
    { label: 'Grass', align: 'right', cls: 'hide-sm' }, { label: 'Official', align: 'right', title: 'Official ranking at the player’s last tour-level match of ' + Y }],
    list.map((x, i) => ({ _href: TA.playerHref(T, x.id, Y), cells: [{ v: i + 1, html: '<b>' + (i + 1) + '</b>' }, { v: x.p.name, html: TA.playerLink(T, x.id, { name: x.p.name, country: true, year: Y }) },
      cell(x.p, 'elo'), cell(x.p, 'elo_hard'), cell(x.p, 'elo_clay'), Object.assign(cell(x.p, 'elo_grass'), { cls: 'hide-sm' }),
      { v: x.p.rank, html: isNum(x.p.rank) ? String(x.p.rank) : '—' }] })), { compact: true, sticky: true });
};
P.note = Y => QK.note('<b>A finished season.</b> Ranks are each player’s official ranking at their last tour-level match of ' + Y +
  ', ratings our Elo at the season’s end; the race, the points to defend and the simulations belong to the season in play. Pick the current year for those.');

/* The Race for a finished season: the race is decided, so the page shows how it ended */
P.race = (el, T, Y) => {
  el.innerHTML = QK.skeleton('lines', 6);
  return P.cat(T, Y).then(cat => {
    if (!el.isConnected) return;
    const ch = P.champions(T, Y), f = ch.finals;
    const fin = f && f.champion ? '<p class="ta-past-lede">' + TA.playerLink(T, f.champion, { year: Y }) + ' won the ' + esc(f.name || TA.levelLabel('finals', T)) +
      (f.runner_up ? ', beating ' + TA.playerLink(T, f.runner_up, { year: Y }) + ' in the final' : '') + '. <a href="' + TA.eventHref(T, f.id) + '">The ' + Y + ' Finals draw →</a></p>' : '';
    const top = P.ranked(cat).slice(0, 10);
    const rows = top.map(x => ({ _href: TA.playerHref(T, x.id, Y), _class: x.p.rank === 8 ? 'cut' : '', cells: [{ v: x.p.rank, html: '<b>' + x.p.rank + '</b>' },
      { v: x.p.name, html: TA.playerLink(T, x.id, { name: x.p.name, country: true, year: Y }) }, { v: val(x.p, 'wins'), html: rec(x.p) },
      { v: val(x.p, 'titles'), html: isNum(val(x.p, 'titles')) ? String(val(x.p, 'titles')) : '—' }] }));
    el.innerHTML = (cat ? P.band(T, Y, cat) : '') +
      TA.card('The ' + Y + ' race is over', 'How the season ended. The race and its simulation run for the season in play.',
        '<div class="pad">' + fin + (rows.length ? TA.tableHTML([{ label: 'Rank', align: 'right' }, { label: 'Player' }, { label: 'Record', align: 'right' }, { label: 'Titles', align: 'right' }], rows, { compact: true }) +
          '<div class="section-note">The season-end top ten: each player’s official ranking at their last tour-level match of ' + Y + '. The dashed line is under eighth. <a href="' + TA.href(T, 'rankings', Y) + '">The full ' + Y + ' ranking →</a> · <a href="' + TA.href(T, 'race', TA.currentYear(T)) + '">This year’s race →</a></div>'
          : TA.muted('No season-end ranking on file for ' + Y + '.')) + '</div>');
    TA.setMeta(TA.tourName(T) + ' ' + Y + ' · a finished season');
  });
};
/* The overview of a finished season (round 9, Phase 3): a recap, not an empty current-season page.
 *   the champions (the band); the Finals' last four as played, with our pre-match call on each card; our call going into
 *   every big event (our top-rated entrant, favourites.json) against who won; the season-end top ten (the top eight
 *   marked); the best by our numbers (season-end Elo overall and on each surface). */
P.recap = (host, T, Y) => {
  if (!host) return Promise.resolve();
  host.innerHTML = QK.skeleton('card', 2);
  const ch = P.champions(T, Y);
  return Promise.all([P.cat(T, Y), TA.loadTour('favourites.json', T), ch.finals && ch.finals.page ? TA.load(TA.eventPath(T, ch.finals.id)) : Promise.resolve(null)   /* event pages exist for the recent years only */]).then(res => {
    if (!host.isConnected) return;
    const cat = res[0], FV = TA.ok(res[1]) ? (res[1].events || {}) : {}, fe = TA.ok(res[2]) ? res[2] : null;
    let h = cat ? P.band(T, Y, cat) : '';
    /* the Finals' semi-finals and final as played */
    const dm = fe && fe.draw && fe.draw.matches ? fe.draw.matches : {};
    const ko = Object.keys(dm).map(k => dm[k]).filter(m => m && (m.round === 'SF' || m.round === 'F')).sort((a, b) => TA.roundIndex(a.round) - TA.roundIndex(b.round) || String(a.date).localeCompare(String(b.date)));
    if (ko.length) h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'How it ended', title: 'The ' + (ch.finals.name || TA.levelLabel('finals', T)) + ', last four', sub: 'The semi-finals and the final as played, each with our chance before the first ball.', actions: '<a class="qk-more" href="' + TA.eventHref(T, ch.finals.id) + '">The full draw</a>' }) +
      '<div class="qk-watch">' + ko.map(m => TA.matchCard(m, { tour: T, why: false, market: false })).join('') + '</div></section>';
    /* our call going into every big event */
    const big = P.events(T, Y).filter(e => ['slam', 'finals', 'm1000'].indexOf(e.level) >= 0 && e.champion).sort((a, b) => String(a.start).localeCompare(String(b.start)));
    const called = big.filter(e => FV[e.id]), hits = called.filter(e => String(FV[e.id][0]) === String(e.champion));
    if (called.length) h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Our call, then what happened', title: 'Our top-rated going in won ' + hits.length + ' of ' + called.length, sub: 'For every Grand Slam, the Finals and every 1000: the entrant with the highest Elo for the surface before their first match there, against the champion. One player against a whole draw wins far less often than not.' }) +
      '<div class="qk-card"><div class="qk-card-body">' + TA.tableHTML([{ label: 'Tournament' }, { label: 'Our top-rated going in' }, { label: 'Elo', align: 'right', cls: 'hide-sm' }, { label: 'Champion' }, { label: '', align: 'center', sortable: false }],
        called.map(e => { const f = FV[e.id], hit = String(f[0]) === String(e.champion); return { _href: TA.eventHref(T, e.id), _class: hit ? 'ta-hit' : '', cells: [
          { v: e.start, html: TA.eventLink(T, e.id, { surface: true }) }, { v: TA.playerName(T, f[0]), html: TA.playerLink(T, f[0], { year: Y }) }, { v: f[1], html: TA.num(f[1], 0), cls: 'hide-sm' },
          { v: TA.playerName(T, e.champion), html: TA.playerLink(T, e.champion, { year: Y }) }, { v: hit ? 1 : 0, html: '<span class="ta-cc-mark ' + (hit ? 'hit' : 'miss') + '" aria-label="' + (hit ? 'Hit' : 'Miss') + '">' + (hit ? '✓' : '✗') + '</span>' }] }; }), { compact: true }) + '</div></div></section>';
    /* the season-end top ten and the best by our numbers */
    if (cat) {
      const top = P.ranked(cat).slice(0, 10);
      const rows = top.map(x => ({ _href: TA.playerHref(T, x.id, Y), _class: x.p.rank === 8 ? 'cut' : '', cells: [{ v: x.p.rank, html: '<b>' + x.p.rank + '</b>' },
        { v: x.p.name, html: TA.playerLink(T, x.id, { name: x.p.name, country: true, year: Y }) }, { v: val(x.p, 'wins'), html: rec(x.p) },
        { v: val(x.p, 'titles'), html: isNum(val(x.p, 'titles')) ? String(val(x.p, 'titles')) : '—' }, { v: val(x.p, 'elo'), html: isNum(val(x.p, 'elo')) ? TA.num(val(x.p, 'elo'), 0) : '—' }] }));
      const best = [['elo', 'Elo No. 1'], ['elo_hard', 'Best on hard'], ['elo_clay', 'Best on clay'], ['elo_grass', 'Best on grass']].map(b => {
        const l = P.byElo(cat, b[0]); if (!l.length) return null;
        return { sport: 'tennis', kicker: b[1] + ', end of ' + Y, name: l[0].p.short || l[0].p.name, value: Math.round(val(l[0].p, b[0])), title: b[0] === 'elo' ? 'Elo' : TA.surfaceLabel(b[0].slice(4)) + ' Elo', next: l[1] ? { name: l[1].p.short || l[1].p.name, value: Math.round(val(l[1].p, b[0])) } : null, href: TA.playerHref(T, l[0].id, Y) };
      }).filter(Boolean);
      h += '<section class="qk-section"><div class="qk-grid"><div class="qk-span-6">' + QK.sectionHead({ kicker: 'Final standings', title: 'The season-end top ten', sub: 'Each player’s official ranking at their last tour-level match of ' + Y + '; the dashed line is under eighth.', tag: 'h3', actions: '<a class="qk-more" href="' + TA.href(T, 'rankings', Y) + '">The full ranking</a>' }) +
        '<div class="qk-card">' + TA.tableHTML([{ label: 'Rank', align: 'right' }, { label: 'Player' }, { label: 'Record', align: 'right' }, { label: 'Titles', align: 'right' }, { label: 'Elo', align: 'right' }], rows, { compact: true }) + '</div></div>' +
        '<div class="qk-span-6">' + QK.sectionHead({ kicker: 'By our numbers', title: 'The best of ' + Y, sub: 'Our Elo at the season’s end, overall and on each surface, with the next best for scale.', tag: 'h3', actions: '<a class="qk-more" href="' + TA.href(T, 'elo', Y) + '">Elo, ' + Y + '</a>' }) +
        QK.hotRow(best, { rank: false }) + '</div></div></section>';
    }
    host.innerHTML = h || QK.empty('Not on file', 'The ' + Y + ' season files are not on the site.');
    TA.sortable(host);
  });
};
})(window.TA);
