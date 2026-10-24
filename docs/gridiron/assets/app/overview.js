/* The Quant Gridiron — Overview (#/), on kit v4 "Broadcast" (the Rink overview is the reference, MIGRATION_V4.md).
 *   the ticker; the greeting (the lower third) over the game to watch as the diagonal split hero (QK.featureCard ->
 *   QK.splitHero; the latest final when nothing is left to play); the black stat strip: games this week, the Super Bowl
 *   favourite (ours), the top-rated team, the EPA-per-dropback leader, the closest game of the week;
 *   "N games. Our calls.": our six picks (live, then the closest calls with the most at stake), every game this week or
 *   last week's results, each card with a one-line reason; the black power list (QK.band + QK.hotRow, five boards);
 *   "We say it. Then we check it." (QK.howSure from calibration.json) beside "Who's for real?" (QKC.quadrant: win %
 *   against the EPA-per-play margin); "What's that number?"; "Who lifts the Lombardi Trophy?" (team-colour bars, our
 *   chances only: no market on the overview) beside projected wins with the simulation's 90% range; power map and
 *   rating trend; the playoff race by conference; divisions at a glance; leaders.
 * Reads index.json, <S>/season.json, glossary.json (leader labels), calibration.json (the teaser). */
(function (GI) {
'use strict';

const QK = window.QK, QKC = window.QKC;
const esc = GI.esc, isNum = GI.isNum;

const LEADER_FALLBACK = { composite: ['QB composite', '1'], epa_db: ['EPA per dropback', 'epa'], cpoe: ['CPOE', 'signed1'], rush_epa: ['Rush EPA per carry', 'epa'],
  ryoe: ['Rush yards over expected per carry', 'signed'], rec_epa: ['Receiving EPA', '1'], sacks: ['Sacks', '1'], fg_oe: ['FG points over expected', 'signed1'] };
function glossIndex(g) {
  const out = {};
  ((g && g.groups) || []).forEach(gr => (gr.entries || []).forEach(e => { if (e && e.key && !out[e.key]) out[e.key] = e; }));
  return out;
}
function leaderMeta(key, G) {
  const m = /^(qb|rb|wr|te|k|p|def)_(.+)$/.exec(key);
  const k = m ? m[2] : key, pre = m ? m[1].toUpperCase() : '';
  const e = G[key] || G[k];
  if (e) return { label: e.label, fmt: e.fmt, lower: e.lower, pre: pre, desc: e.desc };
  const f = LEADER_FALLBACK[k];
  return { label: f ? f[0] : GI.titleCase(k), fmt: f ? f[1] : null, pre: pre };
}

/* The game to watch: live first, else the upcoming game with the most at stake and the closest call. */
function watchVal(g, po) {
  if (GI.isLive(g)) return 100;
  if (!GI.isPre(g)) return -1;
  const p = isNum((g.model || {}).p_home) ? g.model.p_home : 0.5;
  const stake = ((po[g.home] || {}).p_playoffs || 0.5) + ((po[g.away] || {}).p_playoffs || 0.5);
  return stake * (1 - Math.abs(p - 0.5) * 1.6);
}
function featured(games, po) {
  const list = games.filter(g => GI.isLive(g) || GI.isPre(g));
  if (!list.length) return null;
  return list.slice().sort((a, b) => watchVal(b, po) - watchVal(a, po))[0];
}
/* "Who's hot": the top of five of the builder's leaderboards, each with what the number means. */
const HOT = [
  ['qb_epa_db', 'Best passer', 'EPA per dropback', 'Expected points added each time the quarterback drops back, sacks and scrambles included. Zero is an average play.'],
  ['rb_ryoe', 'Best runner', 'rush yards over expected a carry', 'Yards beyond what our model expects from the blocking, the box and the down and distance.'],
  ['wr_rec_epa', 'Best receiver', 'receiving EPA', 'Expected points the offence gained on the throws to this receiver, this season.'],
  ['def_sacks', 'Most sacks', 'sacks', 'Sacks this season. Pressure without the sack does not show in public data.'],
  ['k_fg_oe', 'Best kicker', 'field-goal points over expected', 'Points from field goals beyond what our model expects from the distances tried. Kicking is close to noise.']
];
function hotItems(L, G) {
  return HOT.map(h => {
    const list = L[h[0]] || [];
    const r0 = list[0], r1 = list[1];
    if (!r0) return null;
    const m = leaderMeta(h[0], G);
    const f = v => GI.fmtVal(v, m.fmt);
    return { sport: 'nfl', kicker: h[1] + ' · ' + GI.teamAbbr(GI.player(r0[0]).team), title: h[2].charAt(0).toUpperCase() + h[2].slice(1), name: GI.playerName(r0[0]), value: f(r0[1]), href: GI.playerHref(r0[0]),
      next: r1 ? { name: GI.playerName(r1[0]), value: f(r1[1]) } : null, expl: h[3] };
  }).filter(Boolean);
}

function divisionsGrid(rows) {
  if (!rows.length) return GI.muted('Standings arrive with the first build.');
  return '<div class="gi-divs">' + GI.DIVISIONS.map(dv => {
    const list = rows.filter(r => r.division === dv).sort((a, b) => (b.pct - a.pct) || ((b.p_div || 0) - (a.p_div || 0)));
    if (!list.length) return '';
    return '<div class="gi-div"><div class="gi-div-h"><span>' + esc(dv) + '</span><span>W-L</span><span>Playoffs</span></div>' + list.map((r, i) =>
      '<div class="gi-div-r' + (i === 0 ? ' lead' : '') + '">' + GI.teamLink(r.team, { short: true }) + '<span class="n">' + esc(GI.record(r.w, r.l, r.t)) + '</span>' +
      '<span>' + GI.probBar(r.p_playoffs, GI.tc(r.team)) + '</span></div>').join('') + '</div>';
  }).join('') + '</div>';
}

function seasonRows(season) {
  const out = [];
  ((season && season.standings) || []).forEach(d => (d.teams || []).forEach(t => out.push(Object.assign({ division: d.division, conference: d.conference }, t))));
  return out;
}

GI.route('overview', function (el) {
  const idx = GI.index() || {};
  if (!GI.ok(idx)) { el.innerHTML = GI.pageHead('NFL', 'The Quant Gridiron', '') + GI.notBuilt('The overview', idx); return; }
  const S = GI.currentSeason(), W = GI.currentWeek();
  return GI.loadAll([GI.ypath('season.json', S), 'glossary.json']).then(res => {
    if (!el.isConnected) return;
    const season = GI.ok(res[0]) ? res[0] : null, G = glossIndex(res[1]);
    const all = (idx.games || []).slice().sort((a, b) => String(a.kickoff).localeCompare(String(b.kickoff)));
    const games = all.filter(g => !GI.isStale(g));
    const stale = all.length - games.length;
    const liveIds = {};
    games.filter(GI.isLive).forEach(g => { liveIds[g.game_id] = 1; });
    (idx.live || []).forEach(g => { if (g && GI.isLive(g) && !GI.isStale(g)) liveIds[g.game_id] = 1; });
    const live = games.filter(g => liveIds[g.game_id]);
    const po = idx.playoff_odds || {};
    const rows = seasonRows(season);
    const byTeam = GI.rowsByTeam(rows);
    const fav = Object.keys(po).sort((a, b) => (po[b].p_sb || 0) - (po[a].p_sb || 0))[0];
    const next = games.filter(GI.isPre).map(g => g.kickoff).filter(Boolean).sort()[0];
    const done = games.filter(GI.isFinal).length;
    const ratings = (season && season.ratings) || {};
    const topR = Object.keys(ratings).sort((a, b) => ((ratings[b].values || {}).rating || -99) - ((ratings[a].values || {}).rating || -99))[0];
    const ph = GI.phase();
    const phaseText = ph === 'playoffs' ? 'Playoffs' : ph === 'offseason' ? 'Offseason' : ph === 'preseason' ? 'Preseason' : 'Regular season';
    const feat = featured(games, po);
    const L = idx.leaders || {};
    const qb = (L.qb_epa_db || [])[0];
    const close = games.filter(g => GI.isPre(g) && isNum((g.model || {}).p_home)).sort((a, b) => Math.abs(a.model.p_home - 0.5) - Math.abs(b.model.p_home - 0.5))[0];
    const tick = games.length ? '<div class="qk-ticker gi-ticker" aria-label="This week\'s games">' + QK.ticker(games.map(g => GI.qkGame(g, byTeam)), { group: 'league', pill: false }) + '</div>' : '';
    const wk = GI.weekLabel(W, S);
    /* v4: with nothing left to play this week (or every game waiting on its result), the hero is the latest final,
       with our pre-game call */
    const lastFinal = feat ? null : games.concat(idx.recent || []).filter(GI.isFinal).sort((a, b) => String(b.kickoff).localeCompare(String(a.kickoff)))[0];
    const heroG = feat || lastFinal;
    const fq = heroG ? GI.qkGame(heroG, byTeam) : null;
    if (fq) fq.league = (heroG.week ? GI.weekLabel(heroG.week, GI.gameSeason(heroG.game_id)) : wk) + (heroG.div_game ? ' · Division game' : '');

    el.innerHTML = tick +
      QK.greeting({ date: 'NFL · ' + S + ' · ' + phaseText + ' · ' + wk,
        title: esc(QK.greet()) + '! Here’s what’s ' + QK.mark('worth watching') + ' in the NFL this week.',
        lede: 'Our chance for every game, playoff and Super Bowl chances from 20,000 simulated seasons, every fourth down graded, and the players behind it all, in plain English.',
        ctas: [{ label: 'All ' + wk + ' games', href: GI.weekHref(S, W) }, { label: 'Standings', href: '#/standings', ghost: true }],
        side: fq ? QK.featureCard(fq, { scribble: feat ? (GI.isLive(feat) ? 'Live now' : 'Our pick this week') : 'The latest final', nick: t => t.name }) : '' }) +
      '<div style="margin-top:var(--sp-10)">' + GI.kpis([
        GI.kpi(live.length ? 'Live now' : 'Games this week', String(live.length || all.length), live.length ? all.length + ' this week' : done ? done + ' final' + (games.length - done ? ' · ' + (games.length - done) + ' to play' : '') + (stale ? ' · ' + stale + ' awaiting results' : '') : (next ? 'first kickoff ' + esc(GI.fmtDate(next, { year: false })) : '')),
        GI.kpi('Super Bowl favourite', fav ? esc(GI.teamAbbr(fav)) + ' ' + GI.pct(po[fav].p_sb, 0) : '—', fav ? esc(GI.teamShort(fav)) + ' · from 20,000 simulated seasons' : '', { signal: true, href: fav ? GI.teamHref(fav) : null, tip: 'Our chance of winning the Super Bowl in the season simulation' }),
        GI.kpi('Top-rated team', topR ? esc(GI.teamAbbr(topR)) + ' ' + GI.signed((ratings[topR].values || {}).rating, 1) : '—', topR ? 'points a game better than an average team' : '', { href: topR ? GI.teamHref(topR) : null, tip: 'Our team-strength rating: points per game better than an average team on a neutral field' }),
        GI.kpi('Best passer so far', qb ? esc(GI.playerSurname(qb[0])) + ' ' + GI.signed(qb[1], 2) : '—', qb ? 'EPA per dropback · ' + esc(GI.teamAbbr(GI.player(qb[0]).team)) : '', { href: qb ? GI.playerHref(qb[0]) : null, tip: 'Expected points added per dropback (passes, sacks and scrambles), qualified quarterbacks' }),
        GI.kpi('Closest call', close ? esc(GI.teamAbbr(close.away)) + ' at ' + esc(GI.teamAbbr(close.home)) : '—', close ? 'our chance ' + esc(GI.teamAbbr(close.model.p_home >= 0.5 ? close.home : close.away)) + ' ' + GI.pct(Math.max(close.model.p_home, 1 - close.model.p_home), 0) : 'no games to play this week', { text: true, href: close ? GI.gameHref(close.game_id) : null })
      ]) + '</div>' +

      '<section class="qk-section">' + QK.sectionHead({ kicker: 'What to watch this week', title: '<span id="ov-gh">Games we’d pick</span>', html: true,
        sub: 'Our chance for each side, with a line on why it’s worth your time. Live games update as they go.',
        actions: GI.seg('ov-when', [['picks', 'Our picks'], ['all', 'All ' + all.length], ['results', 'Last week', !(idx.recent || []).length]], 'picks', 'Games') }) +
        '<div id="ov-games"></div>' +
        (stale ? '<p class="qk-caption">' + stale + ' game' + (stale === 1 ? '' : 's') + ' from ' + esc(wk) + ' ' + (stale === 1 ? 'is' : 'are') + ' waiting for ' + (stale === 1 ? 'its result' : 'their results') + ' in the next update; the <a href="' + GI.weekHref(S, W) + '">week page</a> keeps our pre-game forecast for each.</p>' : '') + '</section>' +

      '<div id="ov-hot"></div>' +

      '<section class="qk-section qk-g75"><div><div id="ov-sure-h"></div><div id="ov-sure"></div></div>' +
        '<div class="gi-ov-real">' + QK.sectionHead({ kicker: 'Who’s for real?', title: 'Results v chances', sub: 'Teams top-left are winning more than their play suggests; bottom-right, the reverse. A hot start, or something real?' }) +
        '<div class="qk-card"><div class="qk-card-body"><div id="ov-luck" class="qk-chart" role="img" aria-label="Win percentage against EPA per play margin, every team"></div><p class="qk-caption" id="ov-luck-cap"></p></div></div></div></section>' +

      '<section class="qk-section">' + QK.newHere({ items: [QK.NEW_HERE[0], 'A <b>rating</b> is points a game better than an average team on a neutral field: +7 is a touchdown better.', 'Every forecast is checked against what happened. <a class="qk-link" href="#/calibration">The record is on the Model page.</a>'] }) + '</section>' +

      '<section class="qk-section">' + QK.sectionHead({ kicker: 'Title race', title: 'Who lifts the Lombardi Trophy?', sub: '<span id="ov-sb-lede">Our chances from 20,000 simulated seasons.</span>', html: true, actions: '<a class="qk-more" href="#/futures">Every season forecast</a>' }) +
        GI.grid(GI.card('Super Bowl chances', 'Our chance from 20,000 simulated seasons, in team colours', '<div id="ov-sb"></div>', { span: 6, foot: '<span>Top ten of 32</span><a href="#/playoffs">Bracket →</a>' }) +
          GI.card('Projected wins', 'Mean of the simulated seasons (dot) and its 90% range (bar)', GI.chartBox('ov-range', 520, 'Projected wins with a 90% range'), { span: 6, foot: '<span>Range: 5th to 95th percentile of 20,000 seasons</span><a href="' + GI.standingsHref(S, 'wins') + '">Win totals →</a>' })) +
        QK.explain('<b>What’s that number?</b> Even the favourite misses most seasons. A 20% Super Bowl chance means four seasons in five end without the trophy.') + '</section>' +

      '<section class="qk-section">' + GI.secHead({ kicker: 'Team strength', title: 'Who’s good, and how', sub: 'Our offence and defence ratings in points per game against an average team; up and right is better.', actions: '<a class="qk-more" href="' + GI.standingsHref(S, 'ratings') + '">Power ratings</a>' }) +
        GI.grid(GI.card('Offence v defence', 'Points per game against an average team', GI.chartBox('ov-power', 440, 'Offence against defence rating, every team'), { span: 7 }) +
          GI.card('Rating through the season', 'The top eight teams, week by week', GI.chartBox('ov-trend', 440, 'Team rating by week'), { span: 5 })) + '</section>' +

      '<section class="qk-section">' + GI.secHead({ kicker: 'Playoff race', title: 'Who makes the playoffs', sub: 'Our chance of a playoff spot by conference, from the same 20,000 seasons.', actions: '<a class="qk-more" href="#/playoffs">Seeds and bracket</a>' }) +
        GI.grid(GI.card('AFC', 'Our playoff chance', '<div id="ov-afc"></div>', { span: 6 }) + GI.card('NFC', 'Our playoff chance', '<div id="ov-nfc"></div>', { span: 6 })) + '</section>' +

      '<section class="qk-section">' + GI.secHead({ kicker: 'Standings', title: 'The divisions at a glance', sub: 'Record and our playoff chance; tap a team for its page.', actions: '<a class="qk-more" href="#/standings">Full standings</a>' }) +
        GI.card('', '', divisionsGrid(rows)) + '</section>' +

      '<section class="qk-section">' + GI.secHead({ kicker: 'Leaderboards', title: 'The top ten', sub: S + ' to date, qualified players. Percentiles with sample floors are on the Players page.', actions: '<a class="qk-more" href="#/leaders">Every leaderboard</a>' }) +
        GI.card('', '', '<div id="ov-ld-seg"></div>' + GI.chartBox('ov-leaders', 380, 'Leaderboard')) + '</section>';

    /* What to watch: our six picks (live first, then the closest calls with the most at stake), every game this week,
       or last week's results with our pre-game call; each card with its one-line reason, no market */
    const picks = games.filter(g => GI.isLive(g) || GI.isPre(g)).sort((a, b) => watchVal(b, po) - watchVal(a, po)).slice(0, 6);
    const NUM = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six'];
    const drawGames = w => {
      const list = w === 'all' || !picks.length && w === 'picks' ? all : w === 'results' ? (idx.recent || []) : picks;
      const n = list.length;
      GI.set('ov-gh', w === 'all' || !picks.length && w === 'picks' ? 'Every game in ' + esc(wk) : w === 'results' ? 'How last week went' : NUM[n] + ' game' + (n === 1 ? '' : 's') + '. Our calls.');
      GI.set('ov-games', n ? '<div class="qk-watch">' + list.map(g => GI.gameCard(g, { rows: byTeam, why: true, date: w === 'results', compact: w === 'results' })).join('') + '</div>' : QK.empty('No games this week', 'The schedule is being set.'));
    };
    drawGames('picks');
    GI.wireSeg(el, 'ov-when', drawGames);

    // who's hot: the black power list, the top name on five boards
    const hot = hotItems(L, G);
    GI.set('ov-hot', hot.length ? QK.band(QK.sectionHead({ kicker: 'Who’s hot', title: 'The leaders, board by board', sub: 'The top name on five of our leaderboards, qualified players only, and a line on what each number means.', actions: '<a class="qk-more" href="#/leaders">Every leaderboard</a>' }) + QK.hotRow(hot)) : '');

    /* We say it. Then we check it.: the game model's record from calibration.json (QK.howSure: big numbers and the
       we-said / it-happened bars); the full record is on the Model page */
    GI.load('calibration.json').then(cj => {
      const box = el.querySelector('#ov-sure'), hd = el.querySelector('#ov-sure-h');
      if (!box) return;
      const cb = QK.calib.find(GI.ok(cj) ? cj : null);
      if (!cb || !cb.bins.length) { box.innerHTML = ''; hd.innerHTML = ''; return; }
      const yrs = ((cj.game_model || {}).seasons || []).filter(isNum);
      hd.innerHTML = QK.sectionHead({ kicker: 'How sure are we?', title: 'We say it. Then we check it.', sub: 'Every NFL game we have forecast before kickoff, grouped by the chance we gave the home team. When the two bars match, our numbers mean what they say.',
        actions: '<a class="qk-more" href="#/calibration">The full record</a>' });
      QK.howSure(box, { calibration: cj, league: 'NFL', span: yrs.length ? yrs[0] + ' to ' + yrs[yrs.length - 1] : '', subject: 'the home team' });
    });

    /* Who's for real?: win % against the EPA-per-play margin (offence EPA a play less the EPA a play allowed) */
    const luck = rows.filter(r => r.w + r.l + (r.t || 0) > 0 && ratings[r.team] && isNum((ratings[r.team].values || {}).off_epa) && isNum((ratings[r.team].values || {}).def_epa));
    if (luck.length >= 8) {
      const pts = luck.map(r => { const v = ratings[r.team].values; return { x: v.off_epa - v.def_epa, y: 100 * (r.w + 0.5 * (r.t || 0)) / (r.w + r.l + (r.t || 0)), label: GI.teamAbbr(r.team), name: GI.teamName(r.team), sub: GI.record(r.w, r.l, r.t) + ' · EPA a play ' + GI.signed(v.off_epa, 3) + ' for, ' + GI.signed(v.def_epa, 3) + ' allowed', color: GI.teamInfo(r.team).colour || GI.teamColour(r.team), href: GI.teamHref(r.team) }; });
      const gps = luck.map(r => r.w + r.l + (r.t || 0)), g0 = Math.min.apply(null, gps), g1 = Math.max.apply(null, gps);
      QKC.quadrant('#ov-luck', { points: pts, xName: 'EPA per play margin (offence less defence)', yName: 'Win %', refX: 0, refY: 50, yMin: 0, yMax: 100,
        xFmt: v => GI.signed(v, 2), yFmt: v => Math.round(v) + '%', label: 'NFL teams: EPA per play margin against win percentage' });
      GI.set('ov-luck-cap', 'NFL ' + S + ', ' + (g0 === g1 ? g0 : g0 + '–' + g1) + ' games each. EPA per play margin: expected points added a play on offence, less what the defence allows. Dashed lines: an even margin and a .500 record. Tap a team for its page.');
    } else el.querySelector('#ov-luck').innerHTML = QK.empty('Not yet', 'The chart fills in after the first games.');

    // Super Bowl: our chance only (no market on the overview), each bar in the team's colours
    const chRow = (t, p) => ({ label: GI.teamShort(t), p: p, href: GI.teamHref(t), color: GI.teamInfo(t).colour, mark: { name: GI.teamName(t), abbr: GI.teamAbbr(t), colour: GI.teamInfo(t).colour } });
    const sbRows = Object.keys(po).filter(t => isNum(po[t].p_sb)).map(t => chRow(t, po[t].p_sb));
    GI.set('ov-sb', sbRows.length ? QK.chances(sbRows, { limit: 10, key: false }) : GI.muted('The season simulation has not run yet.'));
    const sb0 = sbRows.slice().sort((a, b) => b.p - a.p)[0];
    if (sb0) GI.set('ov-sb-lede', esc((sb0.p < 0.25 ? 'Nobody’s better than 1 in 4. The ' + sb0.label + ' lead our board at ' + GI.pct(sb0.p, 0) + '.' : 'The ' + sb0.label + ' lead at ' + GI.pct(sb0.p, 0) + '.') + ' From 20,000 simulated seasons.'));

    // projected wins: mean and the 90% range
    const rr = rows.filter(r => isNum(r.mean_wins) && isNum(r.w_p05) && isNum(r.w_p95)).sort((a, b) => b.mean_wins - a.mean_wins);
    if (rr.length) {
      const show = rr.slice(0, 16);
      const n = el.querySelector('#ov-range');
      if (n) {
        const c = QKC.range(n, { rows: show.map(r => ({ label: GI.teamName(r.team), lo: r.w_p05, hi: r.w_p95, mid: r.mean_wins, href: GI.teamHref(r.team), color: GI.teamColour(r.team), sub: GI.record(r.w, r.l, r.t) + ' now · ' + GI.pct(r.p_playoffs, 0) + ' to make the playoffs' })),
          fmt: v => GI.num(v, 1), loName: '5th', hiName: '95th percentile', midName: 'Projected wins', valName: 'Wins at season end', labelWidth: 150 });
        if (c) GI.onLeave(() => { try { c.dispose(); } catch (e) { /* gone */ } });
        n.insertAdjacentHTML('afterend', '<p class="qk-caption">The top sixteen by projected wins. Each bar spans the 5th to 95th percentile of the team’s wins across the simulated seasons.</p>');
      }
    } else GI.ch.none('ov-range', 'The projection appears once the season simulation has run.');

    // power map and trend
    const teams = Object.keys(ratings).filter(t => isNum((ratings[t].values || {}).off_rating));
    if (teams.length) {
      GI.ch.scatter('ov-power', { points: teams.map(t => ({ x: ratings[t].values.off_rating, y: ratings[t].values.def_rating, name: GI.teamName(t), label: t, color: GI.teamColour(t), href: GI.teamHref(t), size: 13 })),
        xName: 'Offence (pts/g)', yName: 'Defence (pts/g)', xFmt: v => GI.signed(v, 0), yFmt: v => GI.signed(v, 0), refX: 0, refY: 0, labelAll: true,
        quadrants: ['Defence carries', 'Contenders', 'Rebuilding', 'Offence carries'], label: 'Offence against defence rating' });
      const top = Object.keys(ratings).sort((a, b) => (ratings[b].values.rating || 0) - (ratings[a].values.rating || 0)).slice(0, 8);
      const weeks = {};
      top.forEach(t => (ratings[t].history || []).forEach(h => { weeks[h[0]] = 1; }));
      const wks = Object.keys(weeks).map(Number).sort((a, b) => a - b);
      GI.ch.line('ov-trend', { x: wks.map(w => 'W' + w), series: top.map(t => ({ name: t, color: GI.teamColour(t), data: wks.map(w => { const h = (ratings[t].history || []).find(r => r[0] === w); return h ? h[1] : null; }) })), yFmt: v => GI.signed(v, 1), xName: 'Week', yName: 'Rating (pts/g v average)', label: 'Team rating by week' });
    } else { GI.ch.none('ov-power', 'Ratings arrive with the first build.'); GI.ch.none('ov-trend', 'Ratings arrive with the first build.'); }

    // playoff race: our chance only
    GI.CONFERENCES.forEach(c => {
      const list = Object.keys(po).filter(t => GI.teamInfo(t).conference === c && isNum(po[t].p_playoffs)).map(t => chRow(t, po[t].p_playoffs));
      GI.set('ov-' + c.toLowerCase(), list.length ? QK.chances(list, { max: 1, key: false }) : GI.muted('The season simulation has not run yet.'));
    });

    // leaders
    const keys = Object.keys(L).filter(k => (L[k] || []).length);
    const segHost = el.querySelector('#ov-ld-seg');
    if (keys.length && segHost) {
      const lab = k => { const m = leaderMeta(k, G); return (m.pre ? m.pre + ' · ' : '') + m.label; };
      segHost.innerHTML = '<div class="qk-chips scroll gi-ld-chips" role="group" aria-label="Leaderboard">' + keys.map((k, i) => '<button type="button" class="qk-chip" data-value="' + esc(k) + '" aria-pressed="' + (i === 0) + '">' + esc(lab(k)) + '</button>').join('') + '</div>';
      const draw = k => {
        const m = leaderMeta(k, G);
        const list = (L[k] || []).slice(0, 10);
        GI.ch.bar('ov-leaders', { cats: list.map(r => GI.playerName(r[0]) + ' · ' + GI.teamAbbr(GI.player(r[0]).team)), series: [{ name: m.label, data: list.map(r => Number(r[1])) }], horizontal: true, labels: true,
          colors: list.map(r => GI.teamColour(GI.player(r[0]).team)), hrefs: list.map(r => GI.playerHref(r[0])), fmt: v => GI.fmtVal(v, m.fmt), labelWidth: 170, valName: m.label, label: m.label + ' leaders' });
      };
      QK.chips(segHost.firstChild, v => draw(v[0]));
      draw(keys[0]);
    } else GI.ch.none('ov-leaders', 'Leaderboards arrive with the first build.');

    if (live.length) GI.liveRefresh([], 60000);
  });
});


})(window.GI);
