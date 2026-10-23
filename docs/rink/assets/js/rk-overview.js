/* The Quant Rink — Overview (#/), the kit v3 "Matchday" reference page for every sport's overview (MIGRATION_V3.md).
 *
 *   v3: the greeting hero (QK.greeting) with the game to watch (QK.featureCard); "What to watch tonight" game cards with
 *       a one-line reason each and no market; "New here? Three things to know" beside a "How sure are we?" teaser read
 *       from data/calibration.json (QK.calib.find), linking to the full record on the Model page;
 *   headline and stat tiles: games today (live), the Cup favourite, the top-rated club, the points leader, the
 *              best goalie by goals saved above expected (ours first; no market headline);
 *   scoreboard: live and today's games (then the next ones and the latest results) as v2 game cards;
 *   charts: Stanley Cup chances (ours only, no market tick), projected points with the
 *           simulation's 90% range, power ratings, results v process (points % against 5v5 xGF%);
 *   playoff race by conference (chance bars) beside the standings; four leader boards (counting stats).
 *
 * Reads index.json, <S>/season.json, <S>/markets.json. Refreshes every minute while a game is live. */
(function (RK) {
'use strict';

const U = RK.ui, esc = RK.esc, isNum = RK.isNum;

function tiles(idx, rows, cup) {
  const today = idx.today || [], live = (idx.live || []).length || today.filter(g => U.status(g) === 'live').length;
  const fav = cup.slice().sort((a, b) => (b.model || 0) - (a.model || 0))[0];
  const top = rows.slice().filter(r => isNum(r.rating)).sort((a, b) => b.rating - a.rating)[0];
  const ld = ((idx.leaders || {}).s_p || [])[0];
  const gk = ((idx.leaders || {}).g_gsax || [])[0];
  return QK.stats([
    { label: live ? 'Live now' : 'Games today', value: String(live || today.length), sub: live ? today.length + ' on the slate today' : (today.length ? 'first puck drop ' + QK.fmt.time((today[0] || {}).start) : 'no games today') },
    { label: 'Cup favourite', value: fav ? RK.teamAbbr(fav.team) + ' ' + U.pct(fav.model) : '—', signal: true, href: fav ? RK.teamHref(fav.team) : null, sub: 'from 20,000 simulated seasons', tip: 'Our chance of winning the Stanley Cup in the season simulation' },
    { label: 'Top-rated club', value: top ? RK.teamAbbr(top.team) + ' ' + U.signed(top.rating, 2) : '—', href: top ? RK.teamHref(top.team) : null, sub: top ? 'goals a game better than an average club' : '', tip: 'Our team rating: expected goal difference per game against an average club' },
    { label: 'Points leader', value: ld ? RK.playerSurname(ld[0]) + ' ' + ld[1] : '—', href: ld ? RK.playerHref(ld[0]) : null, sub: ld ? RK.teamName(RK.player(ld[0]).team) : '' },
    { label: 'Best goalie so far', value: gk ? RK.playerSurname(gk[0]) + ' ' + U.signed(gk[1], 1) : '—', href: gk ? RK.playerHref(gk[0]) : null, sub: 'goals saved above expected', tip: 'Goals stopped beyond what the quality of the shots faced predicts' }
  ]);
}

function gamesBlock(idx) {
  const today = (idx.today || []).slice(), live = idx.live || [];
  const seen = {};
  const list = [];
  live.concat(today).forEach(g => { if (!seen[g.game_id]) { seen[g.game_id] = 1; list.push(g); } });
  const order = { live: 0, pre: 1, final: 2 };
  list.sort((a, b) => order[U.status(a)] - order[U.status(b)] || String(a.start).localeCompare(String(b.start)));
  const up = (idx.upcoming || []).filter(g => !seen[g.game_id]).slice(0, 8);
  const rec = (idx.recent || []).filter(g => !seen[g.game_id]).slice().sort((a, b) => String(b.start).localeCompare(String(a.start))).slice(0, 8);
  return { today: list, upcoming: up, recent: rec };
}

function render(el) {
  const S = RK.currentSeason();
  const idx = RK.index() || {};
  const seg = '<div class="qk-seg" id="ov-when" role="group" aria-label="Games"><button type="button" aria-pressed="true" data-value="today">Today</button><button type="button" aria-pressed="false" data-value="next">Next</button><button type="button" aria-pressed="false" data-value="results">Results</button></div>';
  const G0 = gamesBlock(idx);
  const feat = G0.today.concat(G0.upcoming).map(c => U.game(c)).filter(g => g.status !== 'final').map(g => [QK.watchScore(g), g]).sort((a, b) => b[0] - a[0])[0];
  const evening = new Date(QK.now()).getHours() >= 15;
  el.innerHTML = QK.greeting({ date: 'NHL · ' + RK.seasonLabel(S) + (RK.phaseLabel() ? ' · ' + RK.phaseLabel() : ''),
    title: esc(QK.greet()) + '! Here’s what’s ' + QK.mark('worth watching') + ' in the NHL ' + (evening ? 'tonight' : 'today') + '.',
    lede: 'Our chance for every game, playoff and Cup chances from 20,000 simulated seasons, expected goals, and the players behind it all, in plain English.',
    ctas: [{ label: 'All games', href: '#/games' }, { label: 'Standings', href: '#/standings', ghost: true }],
    side: feat ? QK.featureCard(feat[1], { scribble: feat[1].status === 'live' ? 'Live now!' : 'Our pick ' + (evening ? 'tonight' : 'today') + '!' }) : '' }) +
    '<div id="ov-kpis" style="margin-top:var(--sp-10)">' + QK.skeleton('lines', 2) + '</div>' +
    '<section class="qk-section">' + QK.sectionHead({ kicker: 'What to watch ' + (evening ? 'tonight' : 'today'), title: '<span id="ov-gh">Tonight</span>', html: true, sub: 'Our chance for each side, with a line on why it’s worth your time. Live games update as they go.', actions: seg }) +
    '<div class="qk-watch" id="ov-games">' + QK.skeleton('card', 3) + '</div></section>' +
    '<section class="qk-section qk-gside" id="ov-new"><div id="ov-sure"></div><div>' + QK.newHere({ items: [QK.NEW_HERE[0], QK.NEW_HERE[1], 'Every forecast is checked against what happened. <a class="qk-link" href="#/model?tab=calibration">The record is on the Model page.</a>'] }) + '</div></section>' +
    '<section class="qk-section">' + QK.sectionHead({ kicker: 'Season simulation', title: 'Who wins the Cup', sub: 'Our chances from 20,000 simulated seasons, with each club’s projected points and the range it lands in nine times out of ten.' }) +
    '<div class="qk-grid"><div class="qk-span-5">' + U.card2('Stanley Cup chances', 'Our chance from 20,000 simulated seasons', '<div id="ov-cup"></div>', { foot: '<span>Top twelve of 32</span><a href="#/standings?tab=markets">Every season forecast →</a>' }) + '</div>' +
    '<div class="qk-span-7">' + U.card2('Projected full-season points', 'Mean of the simulated seasons (dot) and its 90% range (bar)', U.chart('ov-range', 470, 'Projected points with a 90% range'), { foot: '<span>Range: 5th to 95th percentile of 20,000 seasons</span><a href="#/standings">Standings →</a>' }) + '</div></div></section>' +
    '<section class="qk-section">' + QK.sectionHead({ kicker: 'Team strength', title: 'Ratings and process', sub: 'How good each club is per game, and whether its results match the chances it creates.' }) +
    '<div class="qk-grid"><div class="qk-span-5">' + U.card2('Power ratings', 'Expected goal difference a game against an average club', U.chart('ov-power', 470, 'Team ratings'), { foot: '<span>All 32 clubs</span><a href="#/standings?tab=ratings">Ratings by component →</a>' }) + '</div>' +
    '<div class="qk-span-7">' + U.card2('Results v process', 'Points % against share of 5v5 expected goals. Right of centre: plays better than its record; above: winning more than its play', U.chart('ov-luck', 470, 'Points percentage against expected goals share'), { foot: '<span>Tap a club for its page</span><a href="#/teams">All teams →</a>' }) + '</div></div></section>' +
    '<section class="qk-section">' + QK.sectionHead({ kicker: 'Playoff race', title: 'Who makes the playoffs', sub: 'Our chance of a playoff spot by conference, beside the table as it stands.',
      actions: '<div class="qk-seg" id="ov-conf" role="group" aria-label="Conference"><button type="button" aria-pressed="true" data-value="Eastern">East</button><button type="button" aria-pressed="false" data-value="Western">West</button></div>' }) +
    '<div class="qk-grid"><div class="qk-span-6">' + U.card2('Playoff chances', 'Our chance of making the playoffs', '<div id="ov-po"></div>') + '</div>' +
    '<div class="qk-span-6">' + U.card2('Standings', 'Points, points % and our playoff chance', '<div id="ov-st"></div>', { flush: true, foot: '<span>Wild-card format</span><a href="#/standings">Full standings →</a>' }) + '</div></div></section>' +
    '<section class="qk-section">' + QK.sectionHead({ kicker: 'Leaderboards', title: 'Leaders', sub: 'Counting stats this season, so everyone ranks. Rates with sample floors are on the Players page.', actions: '<a class="qk-btn" href="#/players">Players →</a>' }) +
    '<div class="qk-grid" id="ov-leaders"></div></section>';

  /* How sure are we? (teaser): the game model's record from data/calibration.json, the full chart on the Model page */
  RK.load('calibration.json').then(cj => {
    const box = el.querySelector('#ov-sure');
    const cb = QK.calib.find(RK.ok(cj) ? cj : null);
    if (!box) return;
    if (!cb) { box.innerHTML = ''; return; }
    const big = cb.bins.slice().sort((a, b) => b.n - a.n)[0];
    box.innerHTML = '<article class="qk-card" style="height:100%"><div class="qk-card-body"><div class="qk-kicker">How sure are we?</div><h3 style="margin:8px 0 6px">When we say ' + Math.round(big.mean_p * 100) + '%, it happens ' + Math.round(big.freq * 100) + '% of the time</h3>' +
      '<p style="margin:0 0 6px;color:var(--ink-2)">Our most common call puts the home team at ' + Math.round(big.lo * 100) + '–' + Math.round(big.hi * 100) + '%. Across ' + QK.fmt.num(big.n) + ' games like that, the home team won ' + QK.fmt.pct(big.freq, 1) + '.</p>' +
      QK.note('<b>Brier score ' + (isNum(cb.brier) ? cb.brier.toFixed(3) : '—') + '</b> over ' + QK.fmt.num(cb.n) + ' games: 0 is perfect, 0.25 is a coin flip. Hockey is close to random, so small gains count.') +
      '<a class="qk-more" style="display:inline-block;margin-top:14px" href="#/model?tab=calibration">The full record</a></div></article>';
  });
  return Promise.all([RK.load(S + '/season.json'), RK.load(S + '/markets.json')]).then(res => {
    if (!U.alive(el)) return;
    const season = RK.ok(res[0]) ? res[0] : {}, mk = RK.ok(res[1]) ? res[1] : {};
    const rows = ((season.standings || {}).rows || []).slice();
    const byTeam = {}; rows.forEach(r => { byTeam[r.team] = r; });
    const cup = (((mk.futures || {}).cup) || []).slice();
    const odds = idx.playoff_odds || {};
    if (!cup.length) Object.keys(odds).forEach(t => cup.push({ team: t, model: odds[t].p_cup, market: null }));
    el.querySelector('#ov-kpis').innerHTML = tiles(idx, rows, cup);

    // scoreboard
    const G = gamesBlock(idx);
    const draw = w => {
      const list = w === 'next' ? G.upcoming : w === 'results' ? G.recent : G.today;
      const n = Math.min(9, list.length);
      el.querySelector('#ov-gh').textContent = w === 'next' ? 'Next up' : w === 'results' ? 'Latest results' : (n ? (n === 1 ? 'One game' : n + ' games') + ' on the slate' : 'Today');
      el.querySelector('#ov-games').innerHTML = list.length ? list.slice(0, 9).map(g => U.gc(g, null, byTeam, true)).join('') : QK.empty('No games', w === 'today' ? 'No games today: see the next ones.' : 'Nothing to show yet.');
    };
    draw(G.today.length ? 'today' : 'next');
    if (!G.today.length) el.querySelectorAll('#ov-when button').forEach(b => b.setAttribute('aria-pressed', b.getAttribute('data-value') === 'next' ? 'true' : 'false'));
    QK.seg(el.querySelector('#ov-when'), draw);

    // cup chances: ours only (the market is on game pages and the Model page)
    el.querySelector('#ov-cup').innerHTML = QK.chances(cup.filter(r => isNum(r.model)).map(r => ({ label: RK.teamName(r.team), p: r.model, href: RK.teamHref(r.team), mark: U.team(r.team) })),
      { limit: 12, key: false });

    // projected points: mean and the 90% range from the simulation
    const sim = (season.sim && season.sim.teams) || {};
    const rr = Object.keys(sim).filter(t => isNum(sim[t].mean_pts) && isNum(sim[t].pts_p05) && isNum(sim[t].pts_p95)).sort((a, b) => sim[b].mean_pts - sim[a].mean_pts);
    if (rr.length) {
      const show = rr.slice(0, 16);
      QKC.range('#ov-range', { rows: show.map(t => ({ label: RK.teamName(t), lo: sim[t].pts_p05, hi: sim[t].pts_p95, mid: sim[t].mean_pts, href: RK.teamHref(t), color: RK.teamColourRaw(t), sub: U.pct(sim[t].p_playoffs) + ' to make the playoffs' })),
        fmt: v => U.f(v, 0), loName: '5th', hiName: '95th percentile', midName: 'Projected full-season points', valName: 'Points at season end (full season)', labelWidth: 150 });
      el.querySelector('#ov-range').insertAdjacentHTML('afterend', '<p class="qk-caption">The top sixteen by projected points. Each bar spans the 5th to 95th percentile of the club’s points across the simulated seasons.</p>');
    } else el.querySelector('#ov-range').innerHTML = QK.empty('No simulation yet', 'The projection appears once the season simulation has run.');

    // power
    const pw = rows.filter(r => isNum(r.rating)).sort((a, b) => b.rating - a.rating);
    if (pw.length) {
      QKC.bar('#ov-power', { cats: pw.map(r => r.team), series: [{ name: 'Rating', data: pw.map(r => r.rating) }], horizontal: true, diverging: true, fmt: v => U.signed(v, 2), hrefs: pw.map(r => RK.teamHref(r.team)), labelWidth: 44, valName: 'Expected goal difference a game', catName: 'Club' });
    } else el.querySelector('#ov-power').innerHTML = QK.empty('No ratings yet', 'Ratings arrive with the first games.');

    // results v process
    const pts = rows.filter(r => isNum(r.xgf_pct) && isNum(r.p_pct) && r.gp > 0).map(r => ({ x: r.xgf_pct, y: r.p_pct, name: RK.teamName(r.team) + ' · ' + r.pts + ' pts in ' + r.gp, label: r.team, color: RK.teamColourRaw(r.team), href: RK.teamHref(r.team), size: 13 }));
    if (pts.length) QKC.scatter('#ov-luck', { points: pts, xName: '5v5 share of expected goals', yName: 'Points %', xFmt: v => Math.round(v * 100) + '%', yFmt: v => Math.round(v * 100) + '%', refX: 0.5, refY: 0.5, labelAll: true,
      quadrants: ['Winning more than its play', 'Good and winning', 'Struggling', 'Better than its record'] });
    else el.querySelector('#ov-luck').innerHTML = QK.empty('Not yet', 'The chart fills in after the first games.');

    // playoff race + standings snapshot
    const conf = c => rows.filter(r => r.conference === c);
    const drawConf = c => {
      const rs = conf(c).filter(r => isNum(r.p_playoffs));
      el.querySelector('#ov-po').innerHTML = rs.length ? QK.chances(rs.map(r => ({ label: RK.teamName(r.team), p: r.p_playoffs, color: RK.teamColourRaw(r.team), href: RK.teamHref(r.team), mark: U.team(r.team) })), { max: 1, oursName: 'Our playoff chance' }) : QK.empty('No simulation yet');
      const st = conf(c).slice().sort((a, b) => (b.pts - a.pts) || (b.p_pct - a.p_pct));
      QK.leaderboard(el.querySelector('#ov-st'), {
        dense: true, rank: true, rowHref: r => RK.teamHref(r.team), columns: [
          { key: 'name', label: 'Club', type: 'entity', mark: r => U.team(r.team), href: r => RK.teamHref(r.team) },
          { key: 'gp', label: 'GP', num: true }, { key: 'pts', label: 'Pts', num: true },
          { key: 'p_pct', label: 'Pts%', num: true, fmt: v => RK.fmtVal(v, '3') },
          { key: 'p_playoffs', label: 'Playoffs', type: 'bar', max: 1, fmt: v => U.pct(v) }
        ], rows: st.map(r => Object.assign({ name: RK.teamShort(r.team) }, r))
      });
    };
    drawConf('Eastern');
    QK.seg(el.querySelector('#ov-conf'), drawConf);

    // leaders (counting stats, everyone ranks)
    const L = idx.leaders || {};
    const boards = [['s_p', 'Points', v => String(v)], ['s_g', 'Goals', v => String(v)], ['s_gar', 'Rink value (GAR)', v => U.f(v, 1)], ['g_gsax', 'Goals saved above expected', v => U.signed(v, 1)]];
    el.querySelector('#ov-leaders').innerHTML = boards.map(b => {
      const r = (L[b[0]] || []).slice(0, 5);
      return '<div class="qk-span-3">' + U.card2(b[1], '', r.length ? '<ul class="rk-list rk-lead">' + r.map((x, i) => '<li><span class="n">' + (i + 1) + '</span>' + U.playerEnt(x[0], null, RK.player(x[0]).team) + '<span class="v">' + esc(b[2](x[1])) + '</span></li>').join('') + '</ul>' : QK.empty('No leaders yet'), { flush: true }) + '</div>';
    }).join('');

    RK.setMeta('');
    if ((idx.live || []).length || (idx.today || []).some(g => U.status(g) === 'live')) RK.liveRefresh([S + '/season.json'], 60000);
  });
}

RK.page('hub', render);
})(window.RK);
