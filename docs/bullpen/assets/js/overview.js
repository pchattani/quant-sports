/* The Quant Bullpen — Overview (#/ and #/<L>), the kit v4 "Broadcast" landing page (docs/rink/assets/js/rk-overview.js
 * is the reference).
 *
 *   1. the intro band: what the site covers and how to use it, with three quick links (Games, Standings or the
 *      bracket, Players);
 *   2. "This week in MLB" (the current MLB season): the stage (the week of the regular season, or the postseason
 *      round and the series still alive), then the top lines from index.json "digest" (scripts/build_bullpen.py with
 *      oddsmarkets/common/digest.py): the biggest postseason or World Series chance mover, the upset of the week,
 *      the team of the week, our record this week and the other games that matter;
 *   3. the game that matters most, by significance (digest.featured: oddsmarkets/common/featured.py), as the
 *      diagonal split hero labelled "Live now", "Tonight" (only when it truly is tonight in the reader's time),
 *      "Today", "Tomorrow" or the weekday; with nothing big on, the World Series race instead;
 *   4. "N games. Our calls."; the black power list (Who's hot); "We say it. Then we check it." beside "Who's for
 *      real?"; "What's that number?"; "Who wins the World Series?" with the bracket; the strength map; the
 *      standings; the leader boards.
 *
 * Reads index.json (cards, postseason, leaders, teams, digest; levels.aaa for Triple-A), <L>/<S>/season.json
 * (standings, ratings, simulation), mlb/calibration.json (the How sure section). */
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

/* ── the landing top (the same shape on every sport overview) ──────────────────────────────────────────────── */
const WORDS = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine'];
/* "Live now" | "Tonight" | "Today" | "Tomorrow" | the weekday | the date, in the reader's own time (QK.now()). */
function whenLabel(g) {
  if (!g) return '';
  if (g.status === 'live') return 'Live now';
  if (g.status === 'final') return 'Final';
  const d = new Date(g.start), now = new Date(QK.now());
  if (isNaN(d)) return '';
  const d0 = x => { const y = new Date(x.getTime()); y.setHours(0, 0, 0, 0); return y.getTime(); };
  const n = Math.round((d0(d) - d0(now)) / 864e5);
  if (n === 0) return d.getHours() >= 17 ? 'Tonight' : 'Today';
  if (n === 1) return 'Tomorrow';
  if (n > 1 && n < 7) return d.toLocaleDateString('en-GB', { weekday: 'long' });
  return QK.fmt.date(g.start);
}
function intro(o) {
  return '<section class="ql-intro" aria-label="About this site"><div class="ql-intro-l"><div class="qk-greet-date">' + esc(o.tag) + '</div>' +
    '<h1>' + esc(o.title) + '</h1><p>' + esc(o.lede) + '</p></div>' +
    '<nav class="ql-links" aria-label="Start here">' + o.links.map(l => '<a href="' + esc(l.href) + '"><b>' + esc(l.label) + '</b><span>' + esc(l.sub) + '</span></a>').join('') + '</nav></section>';
}
/* a date-only payload day ("2026-09-27") in en-GB without a time-zone shift */
const day = d => QK.fmt.date(String(d || '').length === 10 ? d + 'T12:00:00' : d);
const ptsOf = d => (d > 0 ? '+' : '−') + Math.abs(Math.round(d * 100)) + ' pts';
const the = t => 'the ' + BP.teamShort(t);
const The = t => 'The ' + BP.teamShort(t);
/* "the Mariners lead 3–2" for a postseason series {teams, wins} */
function seriesState(s) {
  if (!s || !s.teams || !s.wins || s.wins.length !== 2) return '';
  const w = s.wins, t = s.teams;
  if (w[0] === w[1]) return 'level at ' + w[0] + '–' + w[1];
  const i = w[0] > w[1] ? 0 : 1;
  return the(t[i]) + ' lead ' + w[i] + '–' + w[1 - i];
}
function seriesFor(c, post) {
  const pair = [String(c.home), String(c.away)].sort().join('|');
  return ((post && post.series) || []).filter(s => (s.teams || []).map(String).sort().join('|') === pair)[0] || null;
}
/* Why the featured game: the shared rule's reasons (the series words replace "a semi-final"), then our numbers. */
function reasonsWhy(r, c, idx, post) {
  const pt = (post && post.teams) || {}, it = idx.teams || {};
  const ws = t => (isNum((pt[t] || {}).p_ws) ? pt[t].p_ws : (it[t] || {}).p_ws);
  const pp = t => (it[t] || {}).p_postseason;
  const ser = c.series ? seriesFor(c, post) : null;
  const lead = (r || []).filter(x => x && !(c.series && /^a (final|semi-final|quarter-final|play-off)$/.test(x))).join(' and ');
  const head = c.series ? BP.seriesText(c.series) + (ser && seriesState(ser) ? ', ' + seriesState(ser) : '') : '';
  const A = BP.teamAbbr(c.away), H = BP.teamAbbr(c.home);
  const nums = isNum(ws(c.away)) && isNum(ws(c.home)) && (ws(c.away) > 0.005 || ws(c.home) > 0.005) ? 'to win the World Series ' + A + ' ' + U.pct(ws(c.away)) + ', ' + H + ' ' + U.pct(ws(c.home))
    : isNum(pp(c.away)) && isNum(pp(c.home)) ? 'our postseason chances ' + A + ' ' + U.pct(pp(c.away)) + ', ' + H + ' ' + U.pct(pp(c.home)) : '';
  const parts = [head, lead ? lead.charAt(0).toUpperCase() + lead.slice(1) : ''].filter(Boolean).join('. ');
  return parts ? parts + (nums ? ': ' + nums : '') + '.' : (nums ? nums.charAt(0).toUpperCase() + nums.slice(1) + '.' : '');
}
/* The game that matters most, on the shared significance rule (featured.py rank_featured: the tier, the stage and
 * the series, the stakes in our simulations, the start time and hour, live-ness; closeness only a small bonus),
 * from index.json digest.featured: the first of "today" still upcoming or live at the reader's clock, else "week".
 * An older payload without it gets the old pick (live first, then the closest calls). */
function pickFeatured(idx, cards, post) {
  const by = {}, now = QK.now();
  cards.forEach(c => { by[c.gpk] = c; });
  const ok = (c, hrs) => { if (!c || BP.isFinal(c) || (BP.notNeeded && BP.notNeeded(c))) return false; const h = (Date.parse(c.start || c.date) - now) / 36e5; return BP.isLive(c) ? h > -8 : h > -1 && h < hrs; };
  const F = (idx.digest || {}).featured;
  if (F && (F.today || F.week)) {
    const T = (F.today || []).filter(f => ok(by[f.id], 24));
    const f = T[0] || (F.week && ok(by[F.week.id], 24 * 7) ? F.week : null);
    if (!f) return { c: null, rest: [] };
    return { c: by[f.id], why: reasonsWhy(f.why, by[f.id], idx, post), week: !T.length, rest: T.slice(1).map(x => by[x.id]) };
  }
  const sc = cards.filter(c => ok(c, 48)).map(c => [QK.watchScore(BP.kitGame(c, 'mlb')), c]).filter(x => x[0] > -1e8).sort((a, b) => b[0] - a[0]);
  return sc.length ? { c: sc[0][1], why: reasonsWhy([], sc[0][1], idx, post), rest: sc.slice(1).map(x => x[1]) } : null;
}
/* Under the hero: why we picked it, then how sure we are. */
function heroNote(g, why) {
  const p = g.p_home;
  let sure = '';
  if (g.status !== 'live' && isNum(p)) {
    const fav = p >= 0.5 ? g.home : g.away, other = p >= 0.5 ? g.away : g.home, pf = Math.max(p, 1 - p), miss = Math.max(1, Math.round(10 * (1 - pf)));
    sure = ' <b>How sure are we?</b> ' + U.pct(pf) + ' for the ' + esc(fav.short || fav.name) + ' means the ' + esc(other.short || other.name) + ' win a game like this about ' + miss + ' time' + (miss === 1 ? '' : 's') + ' in 10.';
  }
  return why ? '<b>Why this game?</b> ' + esc(why) + sure : (sure ? sure.slice(1) : undefined);
}
/* "This week in MLB": the stage line. */
function stageLine(st, phase) {
  if (!st) return PHASE[phase] ? PHASE[phase] + '.' : '';
  if (/pre/.test(phase)) return 'Spring training. Opening Day is ' + day(st.first) + '.';
  if (/off|complete/.test(phase)) return st.champion ? The(st.champion) + ' won the World Series. Our numbers pick up again in spring.' : 'The off-season. Our numbers pick up again in spring.';
  if (/post/.test(phase)) {
    if (st.champion) return The(st.champion) + ' won the World Series.';
    const al = (st.alive || []);
    if (!al.length) return 'The postseason.';
    const name = al[0].name || BP.roundLabel(al[0].round);
    const ser = al.map(s => BP.teamShort(s.teams[0]) + ' v ' + BP.teamShort(s.teams[1]) + ', ' + seriesState(s)).join('; ');
    return 'The postseason: the ' + name + (al.length > 1 ? 's' : '') + ' (best of ' + (al[0].best_of || 7) + '). ' + ser + '.' + (al[0].round !== 'WS' ? ' The World Series is next.' : '');
  }
  return 'Regular season, week ' + st.week + ' of ' + st.weeks + ': ' + QK.fmt.num(st.played) + ' of ' + QK.fmt.num(st.total) + ' games played. It runs to ' + day(st.last) + ', then twelve clubs play for the World Series.';
}
function weekTiles(dig, feat, titles, L, S) {
  const T = [];
  const mv = dig.movers;
  if (mv && (mv.up.length || mv.down.length)) {
    const up = mv.up[0], dn = mv.down[0], lead = up || dn, what = mv.metric === 'p_ws' ? 'World Series' : 'postseason';
    T.push({ label: 'Biggest mover', value: BP.teamAbbr(lead.key) + ' ' + ptsOf(lead.d), href: BP.teamHref(lead.key, L, S), signal: true,
      sub: The(lead.key) + (lead.d > 0 ? ' climbed' : ' slipped') + ' to ' + U.pct(lead.p) + ' in our ' + what + ' chance since ' + day(mv.since) + '.' + (up && dn ? ' Biggest fall: ' + BP.teamAbbr(dn.key) + ' ' + ptsOf(dn.d) + '.' : '') });
  } else if (titles.length) {
    const f = titles[0];
    T.push({ label: 'World Series favourite', value: BP.teamAbbr(f.t) + ' ' + U.pct(f.p), href: BP.teamHref(f.t, L, S), signal: true,
      sub: (f.p < 0.2 ? 'Nobody is better than 1 in 5. ' : '') + The(f.t) + ' lead our board, from 20,000 simulated brackets.' });
  }
  const u = dig.upset;
  if (u) {
    const score = u.side === 'home' ? u.hs + '–' + u.as : u.as + '–' + u.hs;
    T.push({ label: 'Upset of the week', value: BP.teamAbbr(u.winner) + ' ' + U.pct(u.p), href: BP.gameHref(u.id, L),
      sub: The(u.winner) + ' beat ' + the(u.loser) + ' ' + score + ' on ' + QK.fmt.date(u.start) + '. We gave them ' + U.pct(u.p) + ' before first pitch.' });
  }
  const h = dig.hot;
  if (h) T.push({ label: 'Team of the week', value: BP.teamAbbr(h.key) + ' ' + h.w + '–' + h.l, href: BP.teamHref(h.key, L, S),
    sub: The(h.key) + ': ' + h.w + ' win' + (h.w === 1 ? '' : 's') + ' in ' + h.gp + ' games, ' + (h.margin >= 0 ? '+' : '−') + Math.abs(h.margin) + ' run difference.' });
  const r = dig.record;
  if (r) {
    const diff = r.won - r.expected;
    T.push({ label: 'Our record this week', value: r.won + ' of ' + r.n, href: '#/calibration',
      sub: 'Our favourites won ' + r.won + ' of ' + r.n + '; we expected ' + QK.fmt.num(r.expected, 0) + '. ' + (Math.abs(diff) < 2 ? 'Right on our numbers.' : diff > 0 ? 'A good week for the favourites.' : 'A week of upsets: in baseball a 60% call still misses 4 times in 10.') });
  }
  const rest = ((feat && feat.rest) || []).filter(Boolean).slice(0, 2);
  if (rest.length) T.push({ label: 'Also worth a look', value: rest.map(c => BP.teamAbbr(c.away) + '–' + BP.teamAbbr(c.home)).join(' · '), href: BP.href('games', L, S), text: rest.length > 1,
    sub: rest.map(c => { const w = whenLabel(BP.kitGame(c, L)); return w + (BP.isLive(c) ? '' : ' ' + QK.fmt.time(c.start)) + ': ' + (c.series ? BP.seriesText(c.series, true) + ', ' : '') + 'the ' + BP.teamShort(c.away) + ' at the ' + BP.teamShort(c.home); }).join('. ') + '.' });
  return T;
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

    const when = 'today';
    const landing = isCurrent && L === 'mlb';
    const dig = landing ? (idx.digest || {}) : {};
    const feat = landing ? pickFeatured(idx, today.concat(next), post) : null;
    let h = '';
    if (landing) {
      h += intro({ tag: kicker, title: 'Every MLB game, team and player, by the numbers.',
        lede: inPost ? 'Our chance for every postseason game, who wins the World Series from 20,000 simulated brackets, and the Statcast numbers behind the players, in plain English.'
          : 'Our chance for every game from a plate-appearance simulation with the lineups and starters, the race for October from 20,000 simulated seasons, and Statcast percentiles for every player, in plain English.',
        links: [{ label: 'Games', sub: 'Every game, our chance', href: BP.href('games', L, S) },
          inPost ? { label: 'Bracket', sub: 'Every series and path', href: BP.ghref('postseason') } : { label: 'Standings', sub: 'The race for October', href: BP.href('standings', L, S) },
          { label: 'Players', sub: 'Statcast percentiles', href: BP.href('hitters', L, S) }] });
      h += '<section class="qk-section ql-week">' + QK.sectionHead({ kicker: 'This week in MLB', title: '<span id="ov-wk">The week so far</span>', html: true, sub: esc(stageLine(dig.stage, phase)) }) +
        '<div id="ov-week"></div><div id="ov-feat" class="ql-feat"></div></section>';
    } else if (isCurrent && today.length + next.length > 0) {
      h += intro({ tag: kicker, title: 'Triple-A, by the numbers.', lede: sub,
        links: [{ label: 'Games', sub: 'Every game, our chance', href: BP.href('games', L, S) }, { label: 'Standings', sub: 'The table', href: BP.href('standings', L, S) }, { label: 'Prospects', sub: 'Major-league translations', href: BP.href('prospects', L, S) }] });
    } else {
      h += QK.sectionHead({ kicker: kicker, title: title, sub: sub, size: 'lg', tag: 'h1',
        actions: '<a class="qk-btn primary" href="' + BP.href('games', L, S) + '">' + (isCurrent ? 'All games' : 'Every game') + '</a><a class="qk-btn ghost" href="' + BP.href('standings', L, S) + '">Standings</a>' });
    }

    if (hasGames) h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'What to watch', title: '<span id="ov-gh">Today</span>', html: true, sub: 'Our chance for each side, with a line on why it’s worth your time. Live games update as they go.',
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

    // team strength: where each club's strength comes from (the luck and power-rating charts repeat "Who's for real?")
    const haveRatings = Object.keys(rows).some(t => rows[t].rating && isNum(rows[t].rating.net));
    if (haveRatings) {
      h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Team strength', title: 'Bats or arms?', sub: 'Offence against run prevention (pitching and defence), in runs a game above an average club. Up and right is better.',
        actions: '<a class="qk-more" href="' + BP.href('teams', L, S) + '">Every team</a>' }) +
        U.card2('Team strength map', 'Runs a game above average, from our team ratings', U.chart('ov-map', 520, 'Offence against run prevention')) + '</section>';
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

    // this week: the top lines, then the game that matters most (or the World Series race when nothing big is on)
    if (landing) {
      const T = weekTiles(dig, feat, titles, L, S);
      el.querySelector('#ov-week').innerHTML = T.length ? QK.stats(T) : '';
      if (T.length >= 3) el.querySelector('#ov-wk').textContent = 'The week in ' + WORDS[T.length].toLowerCase() + ' lines';
      const fe = el.querySelector('#ov-feat');
      if (feat && feat.c) {
        const g = Object.assign(BP.kitGame(feat.c, L), { league: 'MLB' }), lab = whenLabel(g);
        const occ = feat.c.series ? BP.seriesText(feat.c.series, true) : (feat.week && !/^(Today|Tonight|Live now)$/.test(lab) ? 'The big one this week' : 'The one to watch');
        fe.innerHTML = QK.featureCard(g, { scribble: lab + ' · ' + occ, nick: t => t.short || t.name, note: heroNote(g, feat.why) });
      } else if (titles.length) {  /* nothing big on: lead with the race */
        fe.innerHTML = '<div class="ql-race">' + QK.sectionHead({ kicker: feat ? 'Nothing big on today' : 'No games soon', title: 'So here’s the race for the World Series', sub: 'Our chance of winning it all, from 20,000 simulated brackets.', tag: 'h3' }) +
          QK.chances(titles.slice(0, 6).map(r => ({ label: BP.teamShort(r.t), p: r.p, href: BP.teamHref(r.t, L, S), mark: U.team(r.t, L, S), color: U.raw(r.t) })), { key: false }) + '</div>';
      }
    }

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
    /* We say it. Then we check it.: the game model's record from mlb/calibration.json (QK.howSure, the kit's line chart); the full record is on the Model page */
    const box = el.querySelector('#ov-sure'), hd = el.querySelector('#ov-sure-h');
    if (box && hd) {
      hd.innerHTML = QK.sectionHead({ kicker: 'How sure are we?', title: 'We say it. Then we check it.', sub: 'Every MLB game we have forecast, grouped by the chance we gave the home team. When the two lines match, our numbers mean what they say.',
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
    // the strength map
    if (haveRatings) {
      const pw = Object.keys(rows).map(t => rows[t]).filter(r => r.rating && isNum(r.rating.net) && isNum(r.rating.off));
      const pts = pw.map(r => ({ x: r.rating.off, y: (isNum(r.rating.def) ? r.rating.def : 0) + (isNum(r.rating.pitch) ? r.rating.pitch : 0), name: BP.teamName(r.tid), label: BP.teamAbbr(r.tid), color: BP.teamInfo(r.tid).colour, href: BP.teamHref(r.tid, L, S), size: 13 }));
      QKC.scatter('#ov-map', { points: pts, xName: 'Offence (runs a game above average)', yName: 'Run prevention (runs a game)', xFmt: v => U.signed(v, 1), yFmt: v => U.signed(v, 1), refX: 0, refY: 0, labelAll: true,
        quadrants: ['Pitching and defence', 'Complete teams', 'Rebuilding', 'Bats carry them'], label: 'Team strength map' });
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
