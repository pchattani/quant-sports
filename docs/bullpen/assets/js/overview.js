/* The Quant Bullpen — Overview (#/ and #/<L>), on kit v4 "Broadcast" (docs/_design/STYLE_GUIDE.md; the Rink overview
 * is the reference, MIGRATION_V4.md).
 *
 *   the greeting (the date tag, the line, buttons) over the game to watch as the diagonal split hero (QK.featureCard
 *              -> QK.splitHero, the clubs' full names and alternate colours), then the black stat strip: games today
 *              (live), the World Series favourite (our chance), the top-rated club, the hitter and pitcher WAR leaders,
 *              how our forecasts score;
 *   "N games. Our calls.": live and today's games, the next ones and the latest results as game cards (records, our
 *              chance, a one-line reason; no market anywhere on the overview);
 *   the black power list (QK.band + QK.hotRow from the leaders); "We say it. Then we check it." (QK.howSure from
 *              mlb/calibration.json) beside "Who's for real?" (QKC.quadrant: win % against run differential a game);
 *              "What's that number?";
 *   the title race: World Series chances in team colours (ours only) and the bracket;
 *   team strength: power ratings, the offence-against-run-prevention map and who has been lucky;
 *   standings by league as a leaderboard with our postseason chance; four leader boards.
 *
 * Reads index.json (cards, postseason, leaders, teams; levels.aaa for Triple-A), <L>/<S>/season.json (standings,
 * ratings, simulation), mlb/calibration.json (backtest: the tile and the How sure teaser). */
(function (BP) {
'use strict';

const esc = BP.esc;
const isNum = BP.isNum;
const U = BP.ui;

const PHASE = { preseason: 'Preseason', regular: 'Regular season', postseason: 'Postseason', offseason: 'Off-season', complete: 'Season complete' };
const BOARDS = [
  ['h_war', 'Hitters: Bullpen WAR', v => BP.num(v, 1)], ['h_xwoba_plus', 'Hitters: xwOBA+', v => BP.fmtAvg(v)],
  ['p_war', 'Pitchers: Bullpen WAR', v => BP.num(v, 1)], ['p_stuff_plus', 'Pitchers: Stuff+', v => String(Math.round(v))]
];

/* World Series chances: ours only (the postseason paths, else index teams); no market on the overview. */
function titleRows(idx, post) {
  const pt = (post && post.teams) || {};
  const it = idx.teams || {};
  const ids = Object.keys(Object.keys(pt).length ? pt : it);
  return ids.map(t => {
    const p = isNum((pt[t] || {}).p_ws) ? pt[t].p_ws : (it[t] || {}).p_ws;
    return { t: t, p: p };
  }).filter(r => isNum(r.p) && r.p > 0.0005).sort((a, b) => b.p - a.p);
}
/* Who's hot: one card per leaderboard, the leader with the next best behind. */
const HOT = [['h_war', 'Best hitter', 'Bullpen WAR', 'Wins above a replacement player: batting, running, fielding and position.', v => BP.num(v, 1), 'hitter'],
  ['h_hr', 'Most home runs', 'home runs', 'The season total so far.', v => String(v), 'hitter'],
  ['h_xwoba_plus', 'Best contact', 'xwOBA+', 'Our expected wOBA from how hard and at what angle the ball was hit: .320 is about average.', v => BP.fmtAvg(v), 'hitter'],
  ['p_war', 'Best pitcher', 'Bullpen WAR', 'Wins above a replacement-level arm, from the runs allowed.', v => BP.num(v, 1), 'pitcher'],
  ['p_stuff_plus', 'Nastiest stuff', 'Stuff+', 'The physics of the pitches alone: 100 is league average, 110 is excellent.', v => String(Math.round(v)), 'pitcher']];
function hotItems(lead, L) {
  return HOT.filter(x => (lead[x[0]] || []).length).map(x => {
    const r = lead[x[0]][0], r2 = lead[x[0]][1];
    const tm = (BP.player(r[0]) || {}).team;
    return { sport: 'baseball', kicker: BP.levelName(L) + (tm ? ' · ' + BP.teamAbbr(tm) : ''), title: x[1], name: BP.playerName(r[0]), value: x[4](r[1]), unit: x[2], next: r2 ? { name: BP.playerName(r2[0]), value: x[4](r2[1]) } : null, expl: x[3],
      href: BP.playerHref(r[0], { level: L, role: x[5] }) };
  });
}

BP.ui.hotItems = hotItems;   // leaders.js draws the same power list

function tiles(L, S, src, rows, titles, cal, isCurrent, lv) {
  const today = isCurrent ? (src.today || []).filter(U.fresh) : [];
  const live = today.filter(BP.isLive).length;
  const fav = titles[0] || null;
  const top = Object.keys(rows).map(t => rows[t]).filter(r => r.rating && isNum(r.rating.net)).sort((a, b) => b.rating.net - a.rating.net)[0];
  const lead = src.leaders || {};
  const h = (lead.h_war || [])[0], p = (lead.p_war || [])[0];
  const pooled = cal && cal.games && cal.games.pooled ? cal.games.pooled : null;
  const out = [];
  if (isCurrent) out.push({ label: live ? 'Live now' : 'Games today', value: String(live || today.length), sub: live ? today.length + ' on the slate today' : (today.length ? 'first pitch ' + (QK.fmt.time(today.slice().sort((a, b) => String(a.start).localeCompare(String(b.start)))[0].start) || 'TBD') : 'no games today') });
  else out.push({ label: 'Games played', value: BP.int(lv.final || lv.games || 0), sub: 'regular season and postseason' });
  if (fav) out.push({ label: 'World Series favourite', value: BP.teamAbbr(fav.t) + ' ' + U.pct(fav.p), signal: true, href: BP.teamHref(fav.t, L, S), sub: 'from 20,000 simulated brackets', tip: 'Our chance of winning the World Series, from simulating the rest of the season and the bracket' });
  if (top) out.push({ label: 'Top-rated club', value: BP.teamAbbr(top.tid) + ' ' + U.signed(top.rating.net, 2), href: BP.teamHref(top.tid, L, S), sub: 'runs a game better than an average club', tip: 'Our team rating: offence, defence and pitching in runs per game against an average club' });
  if (h) out.push({ label: 'Top hitter', value: BP.playerSurname(h[0]) + ' ' + BP.num(h[1], 1), href: BP.playerHref(h[0], { level: L }), sub: 'Bullpen WAR · ' + BP.teamAbbr(BP.player(h[0]).team), tip: 'Our wins above replacement: batting, baserunning, fielding and position' });
  if (p) out.push({ label: 'Top pitcher', value: BP.playerSurname(p[0]) + ' ' + BP.num(p[1], 1), href: BP.playerHref(p[0], { level: L, role: 'pitcher' }), sub: 'Bullpen WAR · ' + BP.teamAbbr(BP.player(p[0]).team) });
  if (pooled && pooled.model && out.length < 6) out.push({ label: 'Our game forecasts', value: BP.int(pooled.n_games), unit: 'games', sub: 'log loss ' + BP.num(pooled.model.logloss, 3) + ' · scored before first pitch since 2015', href: '#/calibration', tip: 'Every game since 2015 forecast walk-forward from what was known before the first pitch; lower log loss is better (a coin flip scores 0.693)' });
  return QK.stats(out.slice(0, 6));
}

function render(el, params) {
  const L = params.level, S = params.season;
  const idx = BP.index() || {};
  const isCurrent = S === BP.currentSeason(L);
  const lv = BP.levelInfo(L);
  const src = L === 'mlb' ? idx : lv;
  const phase = isCurrent ? String(lv.phase || idx.phase || '') : 'complete';
  el.innerHTML = QK.skeleton('card', 3);
  return BP.loadAll([BP.ypath('season.json', L, S), 'index.json', L === 'mlb' ? BP.lpath('calibration.json', L) : 'index.json']).then(arr => {
    if (!U.alive(el)) return;
    const season = BP.ok(arr[0]) ? arr[0] : null;
    const cal = L === 'mlb' && BP.ok(arr[2]) ? arr[2] : null;
    let post = isCurrent ? (L === 'mlb' ? idx.postseason : lv.postseason) || null : null;
    const sp = season && season.postseason && typeof season.postseason === 'object' && season.postseason.series ? season.postseason : null;
    if (sp) post = Object.assign({}, sp, post || {}, { teams: sp.teams || (post && post.teams), seeds: sp.seeds || (post && post.seeds), series: (post && post.series) || sp.series });
    const rows = BP.standingsRows ? BP.standingsRows(season || {}) : {};
    BP.setRecords(U.records(season || {}));
    const hasSim = Object.keys(rows).some(t => rows[t].sim && isNum(rows[t].sim.p_postseason)) || Object.keys(rows).some(t => isNum(rows[t].p_postseason));
    const titles = L === 'mlb' ? titleRows(idx, post) : [];
    const inPost = phase === 'postseason' && post && post.series && post.series.length;
    const round = inPost && post.round ? BP.roundLabel(post.round) : '';
    const kicker = [BP.levelLong(L), S, PHASE[phase] || BP.titleCase(phase), round].filter(Boolean).join(' · ');
    const title = L === 'aaa' ? 'Triple-A, by the numbers.' : isCurrent ? 'Every MLB game, by the numbers.' : 'The ' + S + ' season, by the numbers.';
    const sub = !isCurrent ? 'The final standings, how good every club really was, who was lucky, and the players behind it.'
      : L === 'aaa' ? 'Statcast for the International and Pacific Coast Leagues, with major-league translations for every prospect.'
        : 'Our win chance for every game from a plate-appearance simulation with the lineups and starters, postseason chances from 20,000 simulated brackets, Statcast percentiles and the players behind it all.';

    // scoreboard lists
    const seen = {};
    const pick = list => list.filter(c => c && U.fresh(c) && !seen[c.gpk] && (seen[c.gpk] = 1));
    const order = { live: 0, pre: 1, final: 2 };
    const st = c => (BP.isLive(c) ? 'live' : BP.isFinal(c) ? 'final' : 'pre');
    const today = isCurrent ? pick((src.today || []).slice()).sort((a, b) => order[st(a)] - order[st(b)] || String(a.start).localeCompare(String(b.start))) : [];
    const next = isCurrent ? pick((src.upcoming || []).slice().sort((a, b) => String(a.start || a.date).localeCompare(String(b.start || b.date)))) : [];
    const results = isCurrent ? pick((src.recent || []).slice().sort((a, b) => String(b.start || b.date).localeCompare(String(a.start || a.date)))) : [];
    const hasGames = today.length + next.length + results.length > 0;
    const first = today.length ? 'today' : next.length ? 'next' : 'results';

    const evening = new Date(QK.now()).getHours() >= 15;
    const when = evening ? 'tonight' : 'today';
    const lgName = L === 'aaa' ? 'Triple-A' : 'majors';
    /* the game to watch: live first, then the closest calls in the next two days (QK.watchScore) */
    const feat = today.concat(next).map(c => Object.assign(BP.kitGame(c, L), { league: c.series ? BP.seriesText(c.series, true) : (L === 'aaa' ? 'Triple-A' : 'MLB') })).filter(g => g.status !== 'final')
      .map(g => [QK.watchScore(g), g]).filter(x => x[0] > -1e8).sort((a, b) => b[0] - a[0])[0];
    let h = '';
    /* the split hero: the level on the status chip, the occasion (a postseason game) or our pick as the volt tag */
    const featHTML = fg => {
      const occ = fg.league && fg.league !== 'MLB' && fg.league !== 'Triple-A' ? fg.league : '';
      return QK.featureCard(Object.assign({}, fg, { league: L === 'aaa' ? 'Triple-A' : 'MLB' }), { scribble: occ || (fg.status === 'live' ? 'Live now!' : 'Our pick ' + when + '!'), nick: t => t.short || t.name });
    };
    if (isCurrent && (L === 'mlb' || today.length + next.length > 0)) {
      h += QK.greeting({ date: kicker, title: esc(QK.greet()) + '! Here’s what’s ' + QK.mark('worth watching') + ' in ' + (L === 'aaa' ? 'Triple-A' : 'the ' + lgName) + ' ' + when + '.',
        lede: sub, ctas: [{ label: 'All games', href: BP.href('games', L, S) }, { label: inPost && L === 'mlb' ? 'The bracket' : 'Standings', href: inPost && L === 'mlb' ? BP.ghref('postseason') : BP.href('standings', L, S), ghost: true }],
        side: feat ? featHTML(feat[1]) : '' });
    } else {
      h += QK.sectionHead({ kicker: kicker, title: title, sub: sub, size: 'lg', tag: 'h1',
        actions: '<a class="qk-btn primary" href="' + BP.href('games', L, S) + '">' + (isCurrent ? 'All games' : 'Every game') + '</a><a class="qk-btn ghost" href="' + BP.href('standings', L, S) + '">Standings</a>' });
    }
    h += '<div class="bp-tiles">' + tiles(L, S, src, rows, titles, cal, isCurrent, lv) + '</div>';

    if (hasGames) h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'What to watch ' + when, title: '<span id="ov-gh">Today</span>', html: true, sub: 'Our chance for each side, with a line on why it’s worth your time. Live games update as they go.',
      actions: U.seg('ov-when', 'Games', [['today', 'Today'], ['next', 'Next'], ['results', 'Results']], first) }) + '<div class="qk-watch" id="ov-games"></div></section>';
    const hot = hotItems(src.leaders || {}, L);
    /* Who's hot: the black power list, the top name on five boards */
    if (hot.length) h += QK.band(QK.sectionHead({ kicker: isCurrent ? 'Who’s hot' : 'The season’s best', title: isCurrent ? 'The leaders, board by board' : 'Who led the way', sub: 'The top name on five boards, the next best behind, and a line on what the number means.',
      actions: '<a class="qk-more" href="' + BP.href('leaders', L, S) + '">Every leaderboard</a>' }) + QK.hotRow(hot));
    /* We say it. Then we check it. (MLB: calibration.json) beside Who's for real? (win % against run differential) */
    const realHTML = '<div class="bp-ov-real">' + QK.sectionHead({ kicker: 'Who’s for real?', title: 'Results v chances', sub: 'Clubs top-left are winning more than their runs suggest; bottom-right, the reverse. Luck in close games, or something real?' }) +
      '<div class="qk-card"><div class="qk-card-body"><div id="ov-real" class="qk-chart" role="img" aria-label="Win percentage against run differential a game"></div><p class="qk-caption" id="ov-real-cap"></p></div></div></div>';
    const sureOn = L === 'mlb' && isCurrent && !!(cal && QK.calib.find(cal));
    h += sureOn ? '<section class="qk-section qk-g75"><div><div id="ov-sure-h"></div><div id="ov-sure"></div></div>' + realHTML + '</section>' : '<section class="qk-section">' + realHTML + '</section>';
    if (isCurrent) h += '<section class="qk-section">' + QK.newHere({ items: [QK.NEW_HERE[0],
      'A <b>percentile</b> ranks a player against the same position or role (shortstops, starters, relievers): 90th means better than 90 in 100.',
      'Every forecast is checked against what happened. <a class="qk-link" href="#/calibration">The record is on the Model page.</a>'] }) + '</section>';

    // season simulation
    if (titles.length || inPost) {
      h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Title race', title: 'Who wins the World Series?', html: true, sub: '<span id="ov-ws-lede">Our chances from simulating every remaining game and the bracket, each series played out in the model.</span>',
        actions: '<a class="qk-more" href="' + BP.ghref('postseason') + '">Every series and path</a>' }) +
        '<div class="qk-grid">' + (titles.length ? '<div class="qk-span-' + (inPost ? 5 : 12) + '">' + U.card2('World Series chances', 'Our chance from 20,000 simulated brackets, in team colours', '<div id="ov-ws"></div>', { foot: '<span>Clubs still alive</span>' + U.more(BP.ghref('postseason'), 'Every series and path') }) + '</div>' : '') +
        (inPost ? '<div class="qk-span-' + (titles.length ? 7 : 12) + '">' + U.card2('The bracket', 'Series wins and our chance to win each series', '<div id="ov-bk"></div>', { foot: '<span>' + (post.sims ? BP.int(post.sims) + ' simulated brackets' : '') + '</span>' + U.more(BP.ghref('postseason'), 'Postseason') }) + '</div>' : '') + '</div></section>';
    }

    // team strength
    const haveRatings = Object.keys(rows).some(t => rows[t].rating && isNum(rows[t].rating.net));
    const haveLuck = Object.keys(rows).some(t => isNum(rows[t].pythag_w));
    if (haveRatings || haveLuck) {
      h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Team strength', title: 'Ratings and luck', sub: 'How good each club is per game, where its strength comes from, and whether its record matches its runs.' }) + '<div class="qk-grid">';
      if (haveRatings) h += '<div class="qk-span-5">' + U.card2('Power ratings', 'Runs a game better than an average club, our ratings', U.chart('ov-power', 560, 'Team ratings'), { foot: '<span>All clubs</span>' + U.more(BP.href('teams', L, S), 'Every team') }) + '</div>' +
        '<div class="qk-span-7">' + U.card2('Team strength map', 'Offence against run prevention (pitching and defence), runs a game above average. Up and right is better.', U.chart('ov-map', 560, 'Offence against run prevention')) + '</div>';
      if (haveLuck) h += '<div class="qk-span-12">' + U.card2('Who has been lucky', 'Wins above (or below) the Pythagorean record from runs scored and allowed', U.chart('ov-luck', 300, 'Wins above the Pythagorean record') +
        QK.note('A club <b>+5</b> here won five more games than its runs scored and allowed usually buy: close wins tend not to last, so expect it to drift back.'), { foot: '<span>The eight luckiest and unluckiest</span>' + U.more(BP.href('standings', L, S), 'Standings') }) + '</div>';
      h += '</div></section>';
    }

    // standings
    const leagues = [];
    Object.keys(rows).forEach(t => { const lg = rows[t].league; if (lg && leagues.indexOf(lg) < 0) leagues.push(lg); });
    leagues.sort();
    if (leagues.length) h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Standings', title: 'The table', sub: 'Wins and losses, run differential' + (hasSim ? ', and our chance of a postseason place from the season simulation.' : '.'),
      actions: leagues.length > 1 ? U.seg('ov-lg', 'League', leagues.map(x => [x, x]), leagues[0]) : '' }) +
      U.card2(isCurrent && inPost ? 'Final regular season' : 'Standings', '', '<div id="ov-st"></div>', { flush: true, foot: '<span>' + esc(BP.levelName(L) + ' ' + S) + '</span>' + U.more(BP.href('standings', L, S), 'Full standings') }) + '</section>';

    // leaders
    const lead = src.leaders || {};
    const boards = BOARDS.filter(b => (lead[b[0]] || []).length);
    if (boards.length) h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Leaderboards', title: 'Leaders', sub: 'This season. Rates with sample floors and percentiles against each position are on the Players pages.', actions: '<a class="qk-btn" href="' + BP.href('leaders', L, S) + '">Every leaderboard</a>' }) +
      '<div class="qk-grid">' + boards.map(b => '<div class="qk-span-3">' + U.card2(b[1], '', '<ul class="bp-list bp-lead">' + lead[b[0]].slice(0, 5).map((x, i) =>
        '<li><span class="n">' + (i + 1) + '</span>' + U.playerEnt(x[0], L, BP.teamAbbr(BP.player(x[0]).team), b[0].charAt(0) === 'p' ? 'pitcher' : 'hitter') + '<span class="v">' + esc(b[2](x[1])) + '</span></li>').join('') + '</ul>', { flush: true }) + '</div>').join('') + '</div></section>';

    el.innerHTML = h;

    // draw: games
    if (hasGames) {
      const draw = w => {
        const list = w === 'next' ? next : w === 'results' ? results : today;
        const n = Math.min(9, list.length);
        const W = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine'];
        el.querySelector('#ov-gh').textContent = w === 'next' ? 'Next up. Our calls.' : w === 'results' ? 'Latest results' : (n ? (W[n] || n) + ' game' + (n === 1 ? '' : 's') + '. Our calls.' : 'Today');
        el.querySelector('#ov-games').innerHTML = list.length ? list.slice(0, 9).map(c => BP.gameCard(c, { level: L, date: w !== 'today', why: true })).join('') : QK.empty('No games', w === 'today' ? 'No games today: see the next ones.' : 'Nothing to show yet.');
      };
      draw(first);
      QK.seg(el.querySelector('#ov-when'), draw);
    }
    // World Series chances: ours only (the market is on game pages and the Model page)
    /* the title race in team colours, ours only (the market is on game pages and the Model page) */
    if (titles.length && el.querySelector('#ov-ws')) {
      const wsRows = titles.map(r => ({ label: BP.teamShort(r.t), p: r.p, href: BP.teamHref(r.t, L, S), mark: U.team(r.t, L, S), color: U.raw(r.t) }));
      el.querySelector('#ov-ws').innerHTML = QK.chances(wsRows, { limit: 10, key: false });
      const w0 = wsRows[0], lede = el.querySelector('#ov-ws-lede');
      if (w0 && lede) lede.textContent = (w0.p < 0.2 ? 'Nobody’s better than 1 in 5. The ' + w0.label + ' lead our board at ' + U.pct(w0.p) + '.'
        : 'The ' + w0.label + ' lead at ' + U.pct(w0.p) + (w0.p >= 0.5 ? ': they win it in about ' + Math.round(w0.p * 10) + ' of 10 simulated brackets.' : '.')) + ' Every remaining game and series simulated 20,000 times.';
    }
    /* We say it. Then we check it.: the game model's record from mlb/calibration.json (QK.howSure: big numbers and the
       we-said / it-happened bars); the full record is on the Model page */
    const box = el.querySelector('#ov-sure'), hd = el.querySelector('#ov-sure-h');
    if (box && hd) {
      hd.innerHTML = QK.sectionHead({ kicker: 'How sure are we?', title: 'We say it. Then we check it.', sub: 'Every MLB game we have forecast, grouped by the chance we gave the home team. When the two bars match, our numbers mean what they say.',
        actions: '<a class="qk-more" href="#/calibration">The full record</a>' });
      QK.howSure(box, { calibration: cal, league: 'MLB', subject: 'the home team' });
    }
    /* Who's for real?: games won against run differential a game (QKC.quadrant), the corners named */
    if (el.querySelector('#ov-real')) {
      const rr = Object.keys(rows).map(t => rows[t]).filter(r => isNum(r.w) && isNum(r.l) && r.w + r.l > 0 && isNum(r.rd));
      const pts = rr.map(r => ({ x: r.rd / (r.w + r.l), y: r.w / (r.w + r.l) * 100, name: BP.teamName(r.tid), sub: r.w + '–' + r.l + ' · run differential ' + U.signed(r.rd, 0), label: BP.teamAbbr(r.tid), color: U.raw(r.tid), href: BP.teamHref(r.tid, L, S) }));
      if (pts.length >= 6) {
        const gps = rr.map(r => r.w + r.l), g0 = Math.min.apply(null, gps), g1 = Math.max.apply(null, gps);
        QKC.quadrant('#ov-real', { points: pts, xName: 'Run differential a game (runs)', yName: 'Games won (%)', refX: 0, refY: 50, xFmt: v => U.signed(v, 1), yFmt: v => Math.round(v) + '%', label: BP.levelName(L) + ' clubs: run differential against games won' });
        el.querySelector('#ov-real-cap').textContent = BP.levelName(L) + ' ' + S + ', ' + (g0 === g1 ? g0 : g0 + '–' + g1) + ' games each. Run differential is runs scored minus runs allowed, per game. Dashed lines: an even differential and a .500 record. Tap a club for its page.';
      } else el.querySelector('#ov-real').innerHTML = QK.empty('Not yet', 'The chart fills in after the first games.');
    }
    if (inPost && BP.charts && BP.charts.mlbBracket && el.querySelector('#ov-bk')) BP.charts.mlbBracket(el.querySelector('#ov-bk'), post, { level: L, narrow: true });
    // power ratings and the strength map
    if (haveRatings) {
      const pw = Object.keys(rows).map(t => rows[t]).filter(r => r.rating && isNum(r.rating.net)).sort((a, b) => b.rating.net - a.rating.net);
      QKC.bar('#ov-power', { cats: pw.map(r => BP.teamAbbr(r.tid)), series: [{ name: 'Rating', data: pw.map(r => r.rating.net) }], horizontal: true, diverging: true, labels: true, fmt: v => U.signed(v, 2),
        hrefs: pw.map(r => BP.teamHref(r.tid, L, S)), labelWidth: 44, valName: 'Runs a game against an average club', catName: 'Club', label: 'Power ratings' });
      const pts = pw.filter(r => isNum(r.rating.off)).map(r => ({ x: r.rating.off, y: (isNum(r.rating.def) ? r.rating.def : 0) + (isNum(r.rating.pitch) ? r.rating.pitch : 0), name: BP.teamName(r.tid), label: BP.teamAbbr(r.tid), color: BP.teamInfo(r.tid).colour, href: BP.teamHref(r.tid, L, S), size: 13 }));
      QKC.scatter('#ov-map', { points: pts, xName: 'Offence (runs a game above average)', yName: 'Run prevention (runs a game)', xFmt: v => U.signed(v, 1), yFmt: v => U.signed(v, 1), refX: 0, refY: 0, labelAll: true,
        quadrants: ['Pitching and defence', 'Complete teams', 'Rebuilding', 'Bats carry them'], label: 'Team strength map' });
    }
    if (haveLuck) {
      const lk = Object.keys(rows).filter(t => isNum(rows[t].pythag_w) && isNum(rows[t].w)).map(t => ({ t: t, v: rows[t].w - rows[t].pythag_w })).sort((a, b) => b.v - a.v);
      const pk = lk.length > 16 ? lk.slice(0, 8).concat(lk.slice(-8)) : lk;
      QKC.bar('#ov-luck', { cats: pk.map(r => BP.teamAbbr(r.t)), series: [{ name: 'Wins above Pythagorean', data: pk.map(r => Math.round(r.v * 10) / 10) }], diverging: true, labels: true,
        fmt: v => U.signed(v, 1), hrefs: pk.map(r => BP.teamHref(r.t, L, S)), label: 'Wins above the Pythagorean record', valName: 'Wins above Pythagorean', catName: 'Club' });
    }
    // standings by league
    if (leagues.length) {
      const drawLg = lg => {
        const rs = Object.keys(rows).map(t => rows[t]).filter(r => r.league === lg).sort((a, b) => (b.pct || 0) - (a.pct || 0) || (b.w || 0) - (a.w || 0));
        const lead0 = {};
        rs.forEach(r => { const d = r.division || ''; if (!lead0[d]) lead0[d] = r; });
        const cols = [
          { key: 'name', label: 'Club', type: 'entity', sub: 'div', mark: r => U.team(r.tid, L, S), href: r => BP.teamHref(r.tid, L, S) },
          { key: 'w', label: 'W', num: true }, { key: 'l', label: 'L', num: true },
          { key: 'pct', label: 'Pct', num: true, fmt: v => BP.fmtAvg(v) },
          { key: 'gb', label: 'GB', num: true, fmt: v => { const x = Number(v); return isNum(v) && isFinite(x) && x > 0 ? (x % 1 ? x.toFixed(1) : String(x)) : '—'; } },
          { key: 'rd', label: 'RD', num: true, fmt: v => (isNum(v) ? U.signed(v, 0) : '—') }
        ];
        if (hasSim) cols.push({ key: 'pp', label: 'Postseason', type: 'bar', max: 1, fmt: v => (isNum(v) ? (v >= 0.9995 ? 'In' : v <= 0.0005 ? 'Out' : U.pct(v)) : '—'), tip: 'Our chance of a postseason place from the season simulation' });
        QK.leaderboard(el.querySelector('#ov-st'), { dense: true, rank: true, rowHref: r => BP.teamHref(r.tid, L, S), columns: cols,
          rows: rs.map(r => Object.assign({}, r, { name: BP.teamShort(r.tid), div: String(r.division || '').replace(/^(AL|NL)\s/, ''), gb: isNum(r.gb) ? r.gb : (lead0[r.division || ''] ? ((lead0[r.division || ''].w - r.w) + (r.l - lead0[r.division || ''].l)) / 2 : null),
            pp: r.sim && isNum(r.sim.p_postseason) ? r.sim.p_postseason : (isNum(r.p_postseason) ? r.p_postseason : null) })) });
      };
      drawLg(leagues[0]);
      if (leagues.length > 1) QK.seg(el.querySelector('#ov-lg'), drawLg);
    }
    if (today.some(BP.isLive)) BP.liveRefresh([BP.ypath('season.json', L, S)], 60000);
    BP.setMeta(post && post.sims ? BP.int(post.sims) + ' bracket simulations' : '');
  });
}

BP.route('hub', render);
})(window.BP);
