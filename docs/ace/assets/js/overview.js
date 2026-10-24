/* The Quant Ace — Overview (#/ and #/<T>), on kit v4 "Broadcast" (the Rink overview, rk-overview.js, is the reference).
 *
 *   ticker: live, today's and the next matches with our chance before the first ball, then the latest results;
 *   the greeting hero (QK.greeting) with the match to watch (QK.featureCard);
 *   stat tiles: our favourite in the tournament in play, the year-end No. 1 favourite, the World No. 1, the Elo No. 1,
 *               matches today (ours first; no market anywhere on the page);
 *   tournaments in play; "N matches. Our calls." (QK.gameCard with a one-line reason each, Today / Next / Results);
 *   the black power list (QK.band + QK.hotRow: the race leader, the most titles, the Elo No. 1, the best on clay and
 *   grass); "We say it. Then we check it." (QK.howSure from <T>/calibration.json) beside "Who's for real?"
 *   (QKC.quadrant: share of games won, the process, against share of matches won, the results, from value.json's
 *   luck rows; tennis has no xG, and games won is the steadier number that match wins drift back to); "What's that
 *   number?"; the title race in our chance only (the tournament in play, the year-end No. 1), the race to the Finals
 *   and the Elo top 10; past years: the champions. No market anywhere on the page.
 *
 * Reads index.json (tours[T]), <T>/race.json, <T>/calibration.json, <T>/value.json (current year) and the in-play
 * events' <T>/events/<id>.json.
 * Cards still live or upcoming 12 hours after their start are dropped (TA.fresh): a stale snapshot never shows as
 * today. */
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
    const tick = nowList.concat(nextList).slice(0, 14).concat(doneList.slice(0, 8)).map(c => TA.kitGame(c, T));
    /* the greeting: the match most worth watching on the side (a live one first, then the closest call soon) */
    const evening = new Date(QK.now()).getHours() >= 15;
    const when = evening ? 'tonight' : 'today';
    const feat = isCurrent ? nowList.concat(nextList).map(c => TA.kitGame(c, T, { initials: true })).map(g => [QK.watchScore(g), g]).filter(x => x[0] > -1e8).sort((a, b) => b[0] - a[0])[0] : null;
    let html = (tick.length ? '<div class="qk-ticker ta-ticker" aria-label="Scoreboard">' + QK.ticker(tick, { group: 'league', pill: false }) + '</div>' : '') +
      QK.greeting({ date: kicker,
        title: isCurrent ? esc(QK.greet()) + '! Here’s what’s ' + QK.mark('worth watching') + ' on the ' + TA.tourName(T) + ' tour ' + when + '.' : 'The ' + TA.tourName(T) + ' in ' + esc(Y) + ', ' + QK.mark('as it finished') + '.',
        lede: isCurrent ? 'Our chance for every match from surface Elo and serve and return ratings inferred from scores, title chances from simulating every draw, and the players behind it all, in plain English.'
          : 'The ' + Y + ' season: the champions, the rankings and the ratings as they finished.',
        ctas: (evNow.length ? [{ label: ev0Name + ' draw', href: TA.eventHref(T, evNow[0].event) }] : [{ label: 'Tournaments', href: TA.href(T, 'calendar', Y) }])
          .concat([{ label: 'Rankings', href: TA.href(T, 'rankings', Y), ghost: true }]),
        side: feat ? QK.featureCard(feat[1], { scribble: feat[1].status === 'live' ? 'Live now!' : 'Our pick ' + (QK.fmt.relDay(feat[1].start) === 'Today' ? when : 'next') + '!', kicker: feat[1].league + ' · ' + feat[1].note }) : '' });
    const tiles = [];
    if (titleRows.length) tiles.push({ label: ev0Name + ' favourite', value: TA.playerSurname(T, titleRows[0].pid) + ' ' + TA.pct(titleRows[0].p, 0), signal: true, href: TA.eventHref(T, evNow[0].event), sub: 'our title chance from simulating the draw', tip: 'Our chance of winning the tournament, from simulating the rest of the draw match by match' });
    if (isCurrent && yeFav) tiles.push({ label: 'Year-end No. 1', value: TA.playerSurname(T, yeFav[0]) + ' ' + TA.pct(yeFav[1], 0), signal: !titleRows.length, href: TA.href(T, 'race'), sub: race && race.n_sims ? 'from ' + Number(race.n_sims).toLocaleString('en-GB') + ' simulated seasons' : 'season simulation', tip: 'Our chance of finishing the year ranked No. 1' });
    tiles.push({ label: 'World No. 1', value: no1 ? TA.playerShort(T, no1) : '—', href: no1 ? TA.playerHref(T, no1) : null, sub: 'official ranking', text: true });
    tiles.push({ label: 'Elo No. 1', value: elo1 ? TA.playerSurname(T, elo1[0]) + ' ' + TA.num(elo1[1], 0) : '—', href: elo1 ? TA.playerHref(T, elo1[0]) : null, sub: 'our surface-blended rating', tip: 'Our strength rating from every tour-level result' });
    if (isCurrent) tiles.push({ label: live.length ? 'Live now' : 'Matches today', value: String(live.length || today.length), sub: live.length ? today.length + ' on today’s schedule' : (today.length ? today.filter(TA.isFinished).length + ' finished · ' + nextList.length + ' to come' : (nextList.length ? nextList.length + ' scheduled next' : 'none scheduled')) });
    else tiles.push({ label: 'Tournaments', value: String(Object.keys(TA.EVENTS[T][String(Y)] || {}).length), sub: 'in ' + Y });
    html += '<div class="ta-ov-kpis" style="margin-top:var(--sp-10)">' + QK.stats(tiles) + '</div>';

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
      html += '<section class="qk-section">' + QK.sectionHead({ kicker: 'What to watch ' + when, title: '<span id="ov-gh"></span>', html: true, sub: 'Our chance for each player before the first ball, the favourite in blue, and a line on why it’s worth your time. Once it starts: the score set by set.',
        actions: V().seg('ov-when', [['now', 'Today'], ['next', 'Next'], ['results', 'Results']], first, 'Matches') + '<a class="qk-btn" href="' + TA.href(T, 'calendar', Y) + '">Every draw</a>' }) +
        '<div class="qk-watch" id="ov-games"></div></section>';
    }

    // ── who's hot: from index.json and this year's champions (no extra payload)
    const hot = [];
    const rt = (info.race_top || []).filter(r => Array.isArray(r) && isNum(r[3])).sort((a, b) => b[3] - a[3]);
    if (isCurrent && rt.length) hot.push({ sport: 'tennis', title: 'Race leader', name: TA.playerShort(T, rt[0][0]), value: Math.round(rt[0][3]), unit: 'race points', next: rt[1] ? { name: TA.playerShort(T, rt[1][0]), value: Math.round(rt[1][3]) } : null, expl: 'Ranking points won this year: the race to the ' + (T === 'wta' ? 'WTA' : 'ATP') + ' Finals.', href: TA.href(T, 'race') });
    const ttl = {}, evY = TA.EVENTS[T][String(Y)] || {};
    Object.keys(evY).forEach(id => { const ch = evY[id] && evY[id].champion; if (ch && evY[id].level !== 'q') ttl[ch] = (ttl[ch] || 0) + 1; });
    const tl = Object.keys(ttl).sort((a, b) => ttl[b] - ttl[a]);
    if (tl.length) hot.push({ sport: 'tennis', title: 'Most titles in ' + Y, name: TA.playerShort(T, tl[0]), value: ttl[tl[0]], unit: ttl[tl[0]] === 1 ? 'title' : 'titles', next: tl[1] ? { name: TA.playerShort(T, tl[1]), value: ttl[tl[1]] } : null, expl: 'Tour-level titles this year, at every level.', href: TA.playerHref(T, tl[0]) });
    [['all', 'Elo No. 1', 'Our strength rating from every tour-level result; above 2,000 is rare air.'], ['clay', 'Best on clay', 'Clay Elo: the rating from clay matches only.'], ['grass', 'Best on grass', 'Grass Elo: a short season, so it moves slowly.']].forEach(x => {
      const r = (info.elo_top || {})[x[0]] || [];
      if (!r.length) return;
      hot.push({ sport: 'tennis', title: x[1], name: TA.playerShort(T, r[0][0]), value: Math.round(r[0][1]), unit: x[0] === 'all' ? 'Elo' : TA.surfaceLabel(x[0]) + ' Elo', next: r[1] ? { name: TA.playerShort(T, r[1][0]), value: Math.round(r[1][1]) } : null, expl: x[2], href: TA.playerHref(T, r[0][0]) });
    });
    if (hot.length >= 3) html += QK.band(QK.sectionHead({ kicker: 'Who’s hot', title: isCurrent ? 'The form players' : 'The year’s leaders', sub: 'The leaders in the race, the trophy count and our ratings, with the next best for scale.' }) + QK.hotRow(hot.slice(0, 5)));

    // ── We say it. Then we check it. (fills when <T>/calibration.json is there) beside Who's for real? (current year)
    html += '<section class="qk-section qk-g75"><div><div id="ov-sure-h"></div><div id="ov-sure"></div></div>' +
      (isCurrent ? '<div class="ta-ov-real">' + QK.sectionHead({ kicker: 'Who’s for real?', title: 'Results v chances', sub: 'Winning games is the steady part of a record; turning them into match wins takes tiebreaks and deciding sets, which come and go. Top-left: winning more matches than the games suggest. Bottom-right: the reverse.' }) +
        '<div class="qk-card"><div class="qk-card-body"><div id="ov-luck" class="qk-chart" role="img" aria-label="Share of matches won against share of games won">' + QK.skeleton('chart', 1) + '</div><p class="qk-caption" id="ov-luck-cap"></p></div></div></div>' : '<div></div>') + '</section>';
    html += '<section class="qk-section">' + QK.newHere({ items: [QK.NEW_HERE[0],
      'A <b>percentile</b> ranks a player against the rest of the tour: 90th means better than 90 in 100 qualified players.',
      'Every forecast is checked against what happened. <a class="qk-link" href="' + TA.href(T, 'calibration') + '">The record is on the calibration page.</a>'] }) + '</section>';

    // ── charts
    const raceRows = isCurrent && race ? Object.keys(race.finals_qual || {}).map(pid => ({ pid: pid, p: race.finals_qual[pid] })).filter(r => isNum(r.p)).sort((a, b) => b.p - a.p).slice(0, 12) : [];
    const eloKeys = ['all', 'hard', 'clay', 'grass'].filter(k => ((info.elo_top || {})[k] || []).length);
    const hasNo1 = isCurrent && race && race.year_end_no1 && Object.keys(race.year_end_no1).length;
    if (titleRows.length || hasNo1) {
      const t0 = titleRows[0];
      html += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Title race', title: titleRows.length ? 'Who lifts the trophy?' : 'Who finishes No. 1?',
        sub: (t0 ? (t0.p < 0.2 ? 'Nobody’s better than 1 in 5 in ' + ev0Name + '. ' : TA.playerShort(T, t0.pid) + ' leads our board in ' + ev0Name + ' at ' + TA.pct(t0.p, 0) + '. ') : '') + 'Our chances from simulating the rest of the draw and the season, match by match.',
        actions: titleRows.length ? '<a class="qk-more" href="' + TA.eventHref(T, evNow[0].event) + '">The draw and every path</a>' : '' }) + '<div class="qk-grid">';
      if (titleRows.length) html += '<div class="qk-span-6">' + V().card('Who wins ' + ev0Name, 'Our title chance from simulating the rest of the draw', '<div id="ov-title"></div>', { foot: '<span>Top ten</span><a href="' + TA.eventHref(T, evNow[0].event) + '">The draw and every path →</a>' }) + '</div>';
      if (hasNo1) html += '<div class="qk-span-6">' + V().card('Year-end No. 1', 'Our chance of finishing the year ranked No. 1', '<div id="ov-no1"></div>', { foot: '<span>From ' + (race.n_sims ? Number(race.n_sims).toLocaleString('en-GB') + ' ' : '') + 'simulated seasons</span><a href="' + TA.href(T, 'rankings') + '">Rankings →</a>' }) + '</div>';
      html += '</div></section>';
    }
    if (raceRows.length || eloKeys.length) {
      html += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Race and ratings', title: 'Who makes the ' + (T === 'wta' ? 'WTA' : 'ATP') + ' Finals?', sub: 'Our chance of qualifying from simulating the rest of the season, beside our strength ratings. Tap a row to open the player.' }) + '<div class="qk-grid">';
      if (raceRows.length) html += '<div class="qk-span-6">' + V().card('Race to the Finals', 'Our chance of qualifying, from ' + (race.n_sims ? Number(race.n_sims).toLocaleString('en-GB') + ' ' : '') + 'simulated seasons', '<div id="ov-race"></div>', { foot: '<span>Race points when the season was last simulated' + (race.as_of ? ' (' + esc(TA.fmtDate(race.as_of, { year: false, weekday: false })) + ')' : '') + '</span><a href="' + TA.href(T, 'race') + '">The race →</a>' }) + '</div>';
      if (eloKeys.length) html += '<div class="qk-span-6">' + V().card('Elo top 10', 'Our strength ratings from every tour-level result', V().seg('ov-sf', eloKeys.map(k => [k, k === 'all' ? 'Overall' : TA.surfaceLabel(k)]), eloKeys[0], 'Surface') + V().chart('ov-elo', 360, 'Elo top 10'), { foot: '<span>A 100-point gap makes the higher-rated player about a 64% favourite</span><a href="' + TA.href(T, 'elo') + '">Elo tables →</a>' }) + '</div>';
      html += '</div></section>';
    }
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

    /* We say it. Then we check it.: the match model's record from <T>/calibration.json (QK.howSure: the big numbers
       over the we-said / it-happened bars); nothing when the file is absent. The full record is on the calibration page. */
    TA.load(TA.tpath('calibration.json', T)).then(cj => {
      const box = el.querySelector('#ov-sure'), hd = el.querySelector('#ov-sure-h');
      const cb = box && TA.ok(cj) ? QK.calib.find(cj) : null;
      if (!box) return;
      if (!cb || !cb.bins.length) { box.innerHTML = ''; hd.innerHTML = ''; return; }
      const ys = (cj.years || []).slice().sort();
      hd.innerHTML = QK.sectionHead({ kicker: 'How sure are we?', title: 'We say it. Then we check it.', sub: 'Every ' + TA.tourName(T) + ' match we have forecast' + (ys.length ? ' since ' + ys[0] : '') + ', grouped by the chance we gave a player. When the two bars match, our numbers mean what they say.',
        actions: '<a class="qk-more" href="' + TA.href(T, 'calibration') + '">The full record</a>' });
      QK.howSure(box, { calibration: cj, league: TA.tourName(T), span: ys.length ? ys[0] + '–' + ys[ys.length - 1] : '', subject: 'that player', unit: 'matches' });
    });

    /* Who's for real?: share of matches won (results) against share of games won (the process) this season, from
       value.json's luck rows (the season block), the top 40 by ranking with 15 or more tour-level matches */
    if (isCurrent && el.querySelector('#ov-luck')) {
      TA.load(TA.tpath('value.json', T)).then(vj => {
        const host = el.querySelector('#ov-luck');
        if (!host) return;
        const rows = (((TA.ok(vj) && vj.luck) || {}).rows || []).map(r => ({ pid: String(r.pid), s: r.season || {} }))
          .filter(r => isNum(r.s.games_share) && isNum(r.s.win_pct) && (r.s.n || 0) >= 15);
        const rk = r => (isNum(TA.playerRank(T, r.pid)) ? TA.playerRank(T, r.pid) : 9999);
        const top = rows.sort((a, b) => rk(a) - rk(b)).slice(0, 40);
        if (top.length < 8) { host.innerHTML = QK.empty('Not yet', 'The chart fills in once enough players have 15 matches this season.'); return; }
        const pts = top.map(r => ({ x: r.s.games_share * 100, y: r.s.win_pct * 100, label: TA.playerSurname(T, r.pid), name: TA.playerName(T, r.pid) + (isNum(TA.playerRank(T, r.pid)) ? ' · No. ' + TA.playerRank(T, r.pid) : ''),
          sub: r.s.w + '–' + (r.s.n - r.s.w) + ' this season' + (isNum(r.s.adj_win_pct) ? '; on the games won, about ' + TA.pct(r.s.adj_win_pct, 0) + ' of matches' : ''), href: TA.playerHref(T, r.pid) }));
        const avgY = pts.reduce((a, p) => a + p.y, 0) / pts.length;
        QKC.quadrant('#ov-luck', { points: pts, xName: 'Share of games won (%)', yName: 'Share of matches won (%)', refX: 50, refY: avgY,
          xFmt: v => Math.round(v) + '%', yFmt: v => Math.round(v) + '%', label: TA.tourName(T) + ' players: share of games won against share of matches won' });
        el.querySelector('#ov-luck-cap').textContent = TA.tourName(T) + ' ' + Y + ', the top ' + pts.length + ' by ranking with 15 or more tour-level matches. Dashed lines: half the games, and the group’s average match record. Tap a player for the page.';
      });
    }

    if (isCurrent) {
      const draw = w => {
        const list = w === 'next' ? nextList : w === 'results' ? doneList : nowList;
        const gh = el.querySelector('#ov-gh');
        const n = Math.min(9, list.length);
        const W = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine'];
        if (gh) gh.textContent = w === 'next' ? 'Next up. Our calls.' : w === 'results' ? 'Latest results' : (n ? (W[n] || n) + ' match' + (n === 1 ? '' : 'es') + '. Our calls.' : 'Today');
        el.querySelector('#ov-games').innerHTML = list.length ? list.slice(0, 9).map(c => TA.matchCard(c, { tour: T, why: true })).join('')
          : QK.empty('No matches', w === 'now' ? 'Nothing on today’s schedule: see the next matches.' : w === 'next' ? 'No matches scheduled yet.' : 'No results yet.');
      };
      draw(nowList.length ? 'now' : nextList.length ? 'next' : 'results');
      QK.seg(el.querySelector('#ov-when'), draw);
    }
    if (titleRows.length) el.querySelector('#ov-title').innerHTML = QK.chances(titleRows.slice(0, 10).map(r => ({ label: TA.playerShort(T, r.pid), p: r.p, href: TA.playerHref(T, r.pid), sub: isNum(TA.playerRank(T, r.pid)) ? 'No. ' + TA.playerRank(T, r.pid) : '' })), { oursName: 'Our title chance', key: false });
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
    if (raceRows.length) el.querySelector('#ov-race').innerHTML = QK.chances(raceRows.map(r => ({ label: TA.playerShort(T, r.pid), p: r.p, href: TA.playerHref(T, r.pid), sub: isNum(((race.race || {})[r.pid] || {}).now) ? TA.num(race.race[r.pid].now, 0) + ' pts' : '' })), { max: 1, oursName: 'Our chance of qualifying', key: false });
    const n1 = el.querySelector('#ov-no1');
    if (n1) n1.innerHTML = QK.chances(Object.keys(race.year_end_no1).map(pid => ({ label: TA.playerShort(T, pid), p: race.year_end_no1[pid], href: TA.playerHref(T, pid) })), { max: 1, oursName: 'Our chance', key: false });
    if (live.length) TA.interval(() => { if (document.visibilityState === 'visible') TA.go(location.hash || '#/' + T); }, 90000);
    TA.setMeta(race && race.n_sims ? Number(race.n_sims).toLocaleString('en-GB') + ' season simulations' : '');
  });
}

TA.route('hub', render);
})(window.TA);
