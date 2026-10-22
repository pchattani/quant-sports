/* The Quant Ace — Overview (#/ and #/<T>), on Design System 2.0 (the Rink overview is the reference).
 *
 *   head: "Every <tour> match, by the numbers." with the tournaments in play;
 *   ticker: live, today's and the next matches with our chance before the first ball, then the latest results;
 *   stat tiles: our favourite in the tournament in play, the year-end No. 1 favourite, the World No. 1, the Elo No. 1,
 *               matches today (ours first; no market anywhere on the page);
 *   tournaments in play; the scoreboard (v2 game cards, Today / Next / Results);
 *   charts: title chances in the tournament in play, the Elo top 10 by surface, the race to the Finals (our chance of
 *           qualifying) and the year-end No. 1; past years: the champions.
 *
 * Reads index.json (tours[T]), <T>/race.json and the in-play events' <T>/events/<id>.json. Cards still live or
 * upcoming 12 hours after their start are dropped (TA.fresh): a stale snapshot never shows as today. */
(function (TA) {
'use strict';

const esc = TA.esc;
const isNum = TA.isNum;
const V = () => TA.v2;

function champions(T, Y) {
  const ev = TA.EVENTS[T][String(Y)] || {};
  const ids = Object.keys(ev).filter(id => ['slam', 'finals', 'm1000'].indexOf(ev[id].level) >= 0 && ev[id].champion)
    .sort((a, b) => String(ev[a].start).localeCompare(String(ev[b].start)));
  if (!ids.length) return '';
  return TA.tableHTML([{ label: 'Tournament' }, { label: 'Level', cls: 'hide-sm' }, { label: 'Champion' }, { label: 'Runner-up', cls: 'hide-sm' }],
    ids.map(id => [{ v: ev[id].start, html: TA.eventLink(T, id, { surface: true }) }, { v: TA.levelRank(ev[id].level), html: esc(TA.levelLabel(ev[id].level, T)), cls: 'hide-sm' },
      { v: TA.playerName(T, ev[id].champion), html: TA.playerLink(T, ev[id].champion) }, { v: TA.playerName(T, ev[id].runner_up), html: ev[id].runner_up ? TA.playerLink(T, ev[id].runner_up) : '—', cls: 'hide-sm' }]), { compact: true });
}

/* A MATCH_CARD as the kit's game shape for the ticker: p1 on the top row (away), p2 below (home). */
function tickGame(T, c) {
  const st = TA.matchState(c), fin = TA.isFinished(c), live = st === 'live';
  const m = c.model || {};
  const w = TA.setsWon(c);
  const ent = pid => ({ name: TA.playerShort(T, pid), abbr: TA.playerSurname(T, pid).slice(0, 12) });
  return { sport: 'tennis', league: TA.eventName(T, c.event), id: c.id, start: TA.parseDate(c.date) ? TA.parseDate(c.date).toISOString() : c.date, status: live ? 'live' : fin ? 'final' : 'pre',
    away: ent(c.p1), home: ent(c.p2), as: fin || live ? w[0] : null, hs: fin || live ? w[1] : null,
    p_home: !fin && isNum(m.p1) ? 1 - Number(live && isNum(c.wp_now) ? c.wp_now : m.p1) : null, href: TA.matchHref(T, c.id),
    tba: !!c.tba || (c.date && String(c.date).length <= 10) };
}

function render(el, params) {
  const T = params.tour, Y = params.year;
  const info = TA.tourInfo(T);
  const isCurrent = Y === TA.currentYear(T);
  const evNow = isCurrent ? (info.events_now || []) : [];
  el.innerHTML = QK.skeleton('card', 3);
  return TA.loadAll([TA.tpath('race.json', T)].concat(evNow.map(e => TA.eventPath(T, e.event)))).then(arr => {
    if (!el.isConnected) return;
    const race = isCurrent && TA.ok(arr[0]) ? arr[0] : null;
    const evs = {};
    evNow.forEach((e, i) => { if (TA.ok(arr[1 + i])) evs[e.event] = arr[1 + i]; });
    const live = isCurrent ? TA.fresh(info.live) : [], today = isCurrent ? TA.fresh(info.today) : [];
    const upcoming = isCurrent ? TA.fresh(info.upcoming) : [], recent = isCurrent ? (info.recent || []) : [];
    const elo1 = ((info.elo_top || {}).all || [])[0];
    let no1 = null;
    Object.keys(TA.NAMES[T]).forEach(pid => { if (TA.NAMES[T][pid].rank === 1) no1 = pid; });
    let yeFav = null;
    if (race && race.year_end_no1) Object.keys(race.year_end_no1).forEach(pid => { const p = race.year_end_no1[pid]; if (isNum(p) && (!yeFav || p > yeFav[1])) yeFav = [pid, p]; });
    const ev0 = evNow.length ? evs[evNow[0].event] : null;
    const sim0 = ev0 && ev0.sim && ev0.sim.players ? ev0.sim.players : null;
    const titleRows = sim0 ? Object.keys(sim0).map(pid => ({ pid: pid, p: sim0[pid].p_title })).filter(r => isNum(r.p) && r.p > 0.002).sort((a, b) => b.p - a.p) : [];
    const ev0Name = evNow.length ? (evNow[0].name || TA.eventName(T, evNow[0].event)) : '';

    // ── head, ticker and stat tiles
    const kicker = [TA.tourName(T), Y, isCurrent ? (evNow.length ? evNow.map(e => e.name || TA.eventName(T, e.event)).join(' · ') + ' in play' : 'between tournaments') : 'season review'].join(' · ');
    const shown = {};
    const pick = list => list.filter(c => c && !shown[c.id] && (shown[c.id] = 1));
    const byDate = (a, b) => String(a.date).localeCompare(String(b.date));
    const nowList = pick(live).concat(pick(today.filter(c => !TA.isFinished(c)).sort(byDate)));
    const nextList = pick(upcoming.slice().sort(byDate));
    const doneList = pick(today.filter(TA.isFinished).sort((a, b) => String(b.date).localeCompare(String(a.date)))).concat(pick(recent.slice().sort((a, b) => String(b.date).localeCompare(String(a.date)))));
    const tick = nowList.concat(nextList).slice(0, 14).concat(doneList.slice(0, 8)).map(c => tickGame(T, c));
    let html = (tick.length ? '<div class="qk-ticker ta-ticker" aria-label="Scoreboard">' + QK.ticker(tick, { group: 'league' }) + '</div>' : '') +
      QK.sectionHead({ kicker: kicker, title: isCurrent ? 'Every ' + TA.tourName(T) + ' match, by the numbers.' : 'The ' + TA.tourName(T) + ' in ' + Y + '.', size: 'lg', tag: 'h1',
        sub: isCurrent ? 'Our win chance for every match from surface Elo and serve and return ratings inferred from scores, title chances from simulating every draw, and the players behind it all.'
          : 'The ' + Y + ' season: the champions, the rankings and the ratings as they finished.',
        actions: (evNow.length ? '<a class="qk-btn primary" href="' + TA.eventHref(T, evNow[0].event) + '">' + esc(ev0Name) + ' draw</a>' : '<a class="qk-btn primary" href="' + TA.href(T, 'calendar', Y) + '">Tournaments</a>') +
          '<a class="qk-btn" href="' + TA.href(T, 'rankings', Y) + '">Rankings</a>' + (isCurrent ? '<a class="qk-btn" href="' + TA.href(T, 'markets') + '">Forecasts</a>' : '') });
    const tiles = [];
    if (titleRows.length) tiles.push({ label: ev0Name + ' favourite', value: TA.playerSurname(T, titleRows[0].pid) + ' ' + TA.pct(titleRows[0].p, 0), signal: true, href: TA.eventHref(T, evNow[0].event), sub: 'our title chance from simulating the draw', tip: 'Our chance of winning the tournament, from simulating the rest of the draw match by match' });
    if (isCurrent && yeFav) tiles.push({ label: 'Year-end No. 1', value: TA.playerSurname(T, yeFav[0]) + ' ' + TA.pct(yeFav[1], 0), signal: !titleRows.length, href: TA.href(T, 'race'), sub: race && race.n_sims ? 'from ' + Number(race.n_sims).toLocaleString('en-GB') + ' simulated seasons' : 'season simulation', tip: 'Our chance of finishing the year ranked No. 1' });
    tiles.push({ label: 'World No. 1', value: no1 ? TA.playerShort(T, no1) : '—', href: no1 ? TA.playerHref(T, no1) : null, sub: 'official ranking', text: true });
    tiles.push({ label: 'Elo No. 1', value: elo1 ? TA.playerSurname(T, elo1[0]) + ' ' + TA.num(elo1[1], 0) : '—', href: elo1 ? TA.playerHref(T, elo1[0]) : null, sub: 'our surface-blended rating', tip: 'Our strength rating from every tour-level result' });
    if (isCurrent) tiles.push({ label: live.length ? 'Live now' : 'Matches today', value: String(live.length || today.length), sub: live.length ? today.length + ' on today’s schedule' : (today.length ? today.filter(TA.isFinished).length + ' finished · ' + nextList.length + ' to come' : (nextList.length ? nextList.length + ' scheduled next' : 'none scheduled')) });
    else tiles.push({ label: 'Tournaments', value: String(Object.keys(TA.EVENTS[T][String(Y)] || {}).length), sub: 'in ' + Y });
    html += '<div class="ta-ov-kpis">' + QK.stats(tiles) + '</div>';

    if (evNow.length) {
      html += '<section class="qk-section">' + QK.sectionHead({ kicker: 'In play', title: 'Tournaments this week', sub: 'Open one for the draw, every path through it and our title chances from simulating the rest of it.' }) + '<div class="ta-evcards">' +
        evNow.map(e => {
          const inf = TA.eventInfo(T, e.event);
          const col = TA.surfaceColour(e.surface || inf.surface, inf.indoor);
          return '<a class="ta-evcard" href="' + TA.eventHref(T, e.event) + '" style="--sf:' + col + '"><span class="k">' + esc(TA.levelLabel(e.level || inf.level, T)) + ' · ' + esc(TA.surfaceLabel(e.surface || inf.surface, inf.indoor)) + '</span>' +
            '<b>' + esc(e.name || TA.eventName(T, e.event)) + '</b><span class="m">' + esc(TA.fmtRange(e.start, e.end)) + (e.round_now ? ' · ' + esc(TA.roundLabel(e.round_now)) : '') + '</span>' +
            (e.favourite && e.favourite[0] ? '<span class="f">Our favourite ' + esc(TA.playerShort(T, e.favourite[0])) + ' <b>' + TA.pct(e.favourite[1], 0) + '</b></span>' : '') + '</a>';
        }).join('') + '</div></section>';
    }

    if (isCurrent) {
      const first = nowList.length ? 'now' : nextList.length ? 'next' : 'results';
      html += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Scoreboard', title: '<span id="ov-gh"></span>', html: true, sub: 'Our win chance on every card before the first ball, the favourite in violet; then the score in sets and how our call looked.',
        actions: V().seg('ov-when', [['now', 'Today'], ['next', 'Next'], ['results', 'Results']], first, 'Matches') + '<a class="qk-btn" href="' + TA.href(T, 'calendar', Y) + '">Every draw</a>' }) +
        '<div class="ta-gc-grid" id="ov-games"></div></section>';
    }

    // ── charts
    const raceRows = isCurrent && race ? Object.keys(race.finals_qual || {}).map(pid => ({ pid: pid, p: race.finals_qual[pid] })).filter(r => isNum(r.p)).sort((a, b) => b.p - a.p).slice(0, 12) : [];
    const eloKeys = ['all', 'hard', 'clay', 'grass'].filter(k => ((info.elo_top || {})[k] || []).length);
    html += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Forecasts and ratings', title: 'The tour in charts', sub: 'Our chances from simulating the draw and the season, and our ratings. Tap a row to open the player.' }) + '<div class="qk-grid">';
    if (titleRows.length) html += '<div class="qk-span-6">' + V().card('Who wins ' + ev0Name, 'Our title chance from simulating the rest of the draw', '<div id="ov-title"></div>', { foot: '<span>Top ten</span><a href="' + TA.eventHref(T, evNow[0].event) + '">The draw and every path →</a>' }) + '</div>';
    if (eloKeys.length) html += '<div class="qk-span-6">' + V().card('Elo top 10', 'Our strength ratings from every tour-level result', V().seg('ov-sf', eloKeys.map(k => [k, k === 'all' ? 'Overall' : TA.surfaceLabel(k)]), eloKeys[0], 'Surface') + V().chart('ov-elo', 360, 'Elo top 10'), { foot: '<span></span><a href="' + TA.href(T, 'elo') + '">Elo tables and all-time peaks →</a>' }) + '</div>';
    if (raceRows.length) html += '<div class="qk-span-6">' + V().card('Race to the Finals', 'Our chance of qualifying, from ' + (race.n_sims ? Number(race.n_sims).toLocaleString('en-GB') + ' ' : '') + 'simulated seasons', '<div id="ov-race"></div>', { foot: '<span>Race points when the season was last simulated' + (race.as_of ? ' (' + esc(TA.fmtDate(race.as_of, { year: false, weekday: false })) + ')' : '') + '</span><a href="' + TA.href(T, 'race') + '">The race →</a>' }) + '</div>';
    if (isCurrent && race && race.year_end_no1 && Object.keys(race.year_end_no1).length) html += '<div class="qk-span-6">' + V().card('Year-end No. 1', 'Our chance of finishing the year ranked No. 1', '<div id="ov-no1"></div>', { foot: '<span></span><a href="' + TA.href(T, 'rankings') + '">Rankings →</a>' }) + '</div>';
    html += '</div></section>';
    if (!isCurrent) {
      const ch = champions(T, Y);
      if (ch) html += '<section class="qk-section">' + QK.sectionHead({ kicker: Y, title: 'Champions', sub: 'The Slams, the Finals and the 1000s in ' + Y + '.', actions: '<a class="qk-btn" href="' + TA.href(T, 'calendar', Y) + '">Every tournament</a>' }) + '<div class="qk-card">' + ch + '</div></section>';
    }
    html += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Explore', title: 'More on the ' + TA.tourName(T) }) + '<div class="ov-explore">' + [
      [TA.href(T, 'players', Y), 'Players', 'Ranked against their tour on the metrics that predict'],
      [TA.href(T, 'h2h'), 'Head to head', 'Any two players, any surface'],
      [TA.href(T, 'value'), 'Value', 'Breakouts, luck, over- and undervalued players'],
      [TA.href(T, 'compare'), 'Compare', 'Two or three players side by side'],
      [TA.href(T, 'calibration'), 'Calibration', 'How often our chances came true'],
      ['#/methodology', 'Model', 'How the ratings and simulations work']
    ].map(x => '<a class="qk-card is-link ov-x" href="' + x[0] + '"><b>' + esc(x[1]) + '</b><span>' + esc(x[2]) + '</span></a>').join('') + '</div></section>';

    el.innerHTML = html;

    if (isCurrent) {
      const draw = w => {
        const list = w === 'next' ? nextList : w === 'results' ? doneList : nowList;
        const gh = el.querySelector('#ov-gh');
        if (gh) gh.textContent = w === 'next' ? 'Next up' : w === 'results' ? 'Latest results' : (live.length ? 'Live and today' : 'Today');
        el.querySelector('#ov-games').innerHTML = list.length ? list.slice(0, 9).map(c => TA.matchCard(c, { tour: T })).join('')
          : QK.empty('No matches', w === 'now' ? 'Nothing on today’s schedule: see the next matches.' : w === 'next' ? 'No matches scheduled yet.' : 'No results yet.');
      };
      draw(nowList.length ? 'now' : nextList.length ? 'next' : 'results');
      QK.seg(el.querySelector('#ov-when'), draw);
    }
    if (titleRows.length) el.querySelector('#ov-title').innerHTML = QK.chances(titleRows.slice(0, 10).map(r => ({ label: TA.playerShort(T, r.pid), p: r.p, href: TA.playerHref(T, r.pid), sub: isNum(TA.playerRank(T, r.pid)) ? 'No. ' + TA.playerRank(T, r.pid) : '' })), { oursName: 'Our title chance' });
    if (eloKeys.length) {
      const drawElo = k => {
        const rows = (info.elo_top || {})[k] || [];
        const lo = Math.min.apply(null, rows.map(r => r[1]));
        QKC.bar('#ov-elo', { cats: rows.map(r => TA.playerShort(T, r[0]) + (isNum(TA.playerRank(T, r[0])) ? ' · No. ' + TA.playerRank(T, r[0]) : '')), series: [{ name: (k === 'all' ? 'Overall' : TA.surfaceLabel(k)) + ' Elo', data: rows.map(r => Math.round(r[1])), color: k === 'all' ? 'model' : undefined }],
          horizontal: true, labels: true, fmt: v => TA.num(v, 0), min: Math.floor((lo - 120) / 50) * 50, colors: rows.map(() => (k === 'all' ? null : TA.surfaceColour(k))).map(c => c || undefined),
          hrefs: rows.map(r => TA.playerHref(T, r[0])), labelWidth: 150, label: 'Elo top 10', valName: (k === 'all' ? 'Overall' : TA.surfaceLabel(k)) + ' Elo', catName: 'Player' });
      };
      drawElo(eloKeys[0]);
      QK.seg(el.querySelector('#ov-sf'), drawElo);
    }
    if (raceRows.length) el.querySelector('#ov-race').innerHTML = QK.chances(raceRows.map(r => ({ label: TA.playerShort(T, r.pid), p: r.p, href: TA.playerHref(T, r.pid), sub: isNum(((race.race || {})[r.pid] || {}).now) ? TA.num(race.race[r.pid].now, 0) + ' pts' : '' })), { max: 1, oursName: 'Our chance of qualifying' });
    const n1 = el.querySelector('#ov-no1');
    if (n1) n1.innerHTML = QK.chances(Object.keys(race.year_end_no1).map(pid => ({ label: TA.playerShort(T, pid), p: race.year_end_no1[pid], href: TA.playerHref(T, pid) })), { max: 1, oursName: 'Our chance' });
    if (live.length) TA.interval(() => { if (document.visibilityState === 'visible') TA.go(location.hash || '#/' + T); }, 90000);
    TA.setMeta(race && race.n_sims ? Number(race.n_sims).toLocaleString('en-GB') + ' season simulations' : '');
  });
}

TA.route('hub', render);
})(window.TA);
