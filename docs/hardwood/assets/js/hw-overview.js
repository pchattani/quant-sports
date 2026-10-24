/* The Quant Hardwood — Overview (#/<L>), on kit v4 "Broadcast" (the Rink overview is the reference, MIGRATION_V4.md).
 *
 *   the black score ticker; the greeting (QK.greeting: the date tag, the line, buttons) over the game to watch as the
 *     diagonal split hero (QK.featureCard -> QK.splitHero, the teams' full names and alternate colours); the black
 *     stat strip: the title favourite (ours), the best team, the MVP favourite, the next tip-off or live games, the
 *     closest call coming up;
 *   "N games. Our calls.": live, today's, next and recent games as game cards with a one-line reason, no market;
 *   the black power list (QK.band + QK.hotRow: the top qualified name on five boards);
 *   "We say it. Then we check it." (QK.howSure from <L>/calibration.json) beside "Who's for real?" (QKC.quadrant:
 *     win % against net rating); "What's that number?";
 *   series in progress (playoffs); the title race in team colours (our chance only: no market anywhere on the
 *     overview) beside the award races; projected wins with the simulation's 90% range and power ratings; the
 *     playoff picture; most valuable players (projected WAR), the games that matter most; leaders (qualified only).
 * A past season shows its champion, "Who's for real?", final standings and leaders.
 * Reads index.json, <L>/<S>/season.json, <L>/calibration.json, <L>/<S>/awards.json, <L>/<S>/valuation.json, <L>/history.json. */
(function (HW) {
'use strict';

const U = HW.ui, esc = HW.esc, isNum = HW.isNum;
const AWN = { mvp: 'MVP', roy: 'Rookie', dpoy: 'Defence', sixth: 'Sixth', mip: 'Most improved', clutch: 'Clutch' };

/* Upcoming games ranked by leverage: how far one result moves both teams' playoff (or title) chances. */
function leverage(sim, cards) {
  const seen = {}, out = [];
  const keyOf = (o, prefer) => { const ks = Object.keys(o || {}); for (let i = 0; i < prefer.length; i++) { const k = ks.find(x => x.indexOf(prefer[i]) >= 0); if (k) return k; } return ks[0]; };
  Object.keys(sim).forEach(tid => {
    const nx = sim[tid] && sim[tid].next;
    if (!nx || !nx.game || seen[nx.game]) return;
    const other = sim[nx.opp] && sim[nx.opp].next && sim[nx.opp].next.game === nx.game ? sim[nx.opp].next : null;
    const swing = n => {
      if (!n || !n.if_win || !n.if_loss) return 0;
      const k = keyOf(n.if_win, ['playoffs', 'postseason', 'title']);
      return isNum(n.if_win[k]) && isNum(n.if_loss[k]) ? Math.abs(n.if_win[k] - n.if_loss[k]) : 0;
    };
    seen[nx.game] = 1;
    const card = (cards || []).find(c => String(c.id) === String(nx.game));
    if (card ? !U.fresh(card) : (nx.date && !U.fresh({ date: nx.date, status: 'pre' }))) return;
    out.push({ id: nx.game, season: card && card.season ? card.season : null, lev: swing(nx) + swing(other), date: card ? card.date : nx.date, home: nx.home ? tid : nx.opp, away: nx.home ? nx.opp : tid,
      p_home: nx.home ? nx.p_win : (isNum(nx.p_win) ? 1 - nx.p_win : null) });
  });
  return out.filter(x => x.lev > 0.005).sort((a, b) => b.lev - a.lev);
}

function tiles(L, S, d) {
  const out = [];
  const sim = d.sim, tT = Object.keys(sim).filter(t => isNum(sim[t].p_title)).sort((a, b) => sim[b].p_title - sim[a].p_title);
  if (d.isCur) {
    const fav = tT[0];
    out.push({ label: 'Title favourite', value: fav ? HW.teamAbbr(L, fav) + ' ' + U.pct(sim[fav].p_title) : '—', signal: true, href: fav ? HW.teamHref(L, fav, S) : null,
      sub: fav ? 'from ' + Number(d.nSims || 20000).toLocaleString('en-GB') + ' simulated seasons' : 'no simulation yet', tip: 'Our chance of winning the title: the share of simulated seasons the team wins it' });
  } else {
    const ch = d.champ;
    out.push({ label: 'Champion', value: ch ? HW.teamName(L, ch) : '—', text: true, signal: true, href: ch ? HW.teamHref(L, ch, S) : null, sub: d.histRow && d.histRow.runner_up ? 'beat ' + HW.teamName(L, d.histRow.runner_up) : HW.seasonLabel(L, S) });
  }
  const pw = d.power[0];
  if (pw) out.push({ label: 'Best team', value: HW.teamAbbr(L, pw.tid) + ' ' + U.signed(pw.net, 1), href: HW.teamHref(L, pw.tid, S), sub: 'net points per 100 possessions' + (isNum(pw.se) ? ' ± ' + U.f(pw.se, 1) : ''), tip: 'Our opponent-adjusted net rating (a Kalman filter over every game); ± one standard error' });
  if (d.mvp) out.push({ label: d.isCur ? 'MVP favourite' : 'MVP', value: d.mvp.name, text: true, href: HW.playerHref(L, d.mvp.id, S), sub: d.isCur ? 'our chance ' + U.pct(d.mvp.p) : HW.seasonLabel(L, S), tip: d.isCur ? 'Our chance of winning the MVP vote' : null });
  if (d.isCur) {
    const live = d.today.filter(g => HW.gameState(g) === 'in' && U.fresh(g));
    const next = d.upcoming[0];
    if (live.length) out.push({ label: 'Live now', value: String(live.length), sub: live.map(g => HW.teamAbbr(L, g.away) + '–' + HW.teamAbbr(L, g.home)).join(' · ') });
    else if (next) out.push('<div class="qk-stat" id="ov-cd">' + cdHTML(L, next) + '</div>');
    else if (d.stale) out.push({ label: 'Next game', value: '—', sub: 'the next games arrive with the next data update' });
    else out.push({ label: 'Next game', value: d.phase === 'offseason' ? 'Offseason' : 'None soon', text: true, sub: 'the schedule returns with the next season' });
    const close = d.upcoming.filter(g => isNum((g.model || {}).p_home)).sort((a, b) => Math.abs(a.model.p_home - 0.5) - Math.abs(b.model.p_home - 0.5))[0];
    if (close) {
      const ph = close.model.p_home, fav = ph >= 0.5 ? close.home : close.away;
      out.push({ label: 'Closest call', value: HW.teamAbbr(L, fav) + ' ' + U.pct(Math.max(ph, 1 - ph)), href: HW.gameHref(L, close.id, close.season || S), sub: HW.teamAbbr(L, close.away) + ' @ ' + HW.teamAbbr(L, close.home) + ' · ' + HW.fmtDate(close.date, { year: false }), tip: 'The upcoming game nearest a coin flip by our chance' });
    }
  } else if (d.best) {
    out.push({ label: 'Best record', value: HW.teamAbbr(L, d.best[0]) + ' ' + HW.record(d.best[1], d.best[2]), href: HW.teamHref(L, d.best[0], S), sub: HW.teamName(L, d.best[0]) });
  }
  return '<div class="hw-kpis">' + QK.stats(out) + '</div>';
}
function cdHTML(L, g) {
  const cd = HW.countdown(g.date);
  return '<div class="qk-stat-label"><span>Next tip-off</span></div><div class="qk-stat-v">' + esc(cd ? cd.replace(/ \d+s$/, '') : HW.fmtTime(g.date)) + '</div>' +
    '<div class="qk-stat-sub"><span class="qk-truncate">' + esc(HW.teamAbbr(L, g.away) + ' @ ' + HW.teamAbbr(L, g.home) + ' · ' + HW.fmtDate(g.date, { time: true, year: false })) + '</span></div>';
}

/* Live and today's games, the next ones and the latest results (stale live/upcoming snapshots dropped). */
function gamesBlock(d) {
  const shown = {};
  const take = list => list.filter(g => U.fresh(g) && !shown[g.id] && (shown[g.id] = 1));
  const live = take(d.today.filter(g => HW.gameState(g) === 'in'));
  const today = live.concat(take(d.today));
  const next = take(d.next).slice(0, 9);
  const last = take(d.last.slice().sort((a, b) => String(b.date).localeCompare(String(a.date)))).slice(0, 9);
  return { today: today, next: next, last: last };
}

function render(el, params) {
  const L = U.L(params), S = U.S(params);
  const info = HW.leagueInfo(L);
  const isCur = U.isCur(L, S);
  el.innerHTML = U.secHead(HW.leagueName(L) + ' ' + HW.seasonLabel(L, S), '', null, null, U.kicker(L, S)) + QK.skeleton('lines', 4);
  return Promise.all([HW.load(HW.path('season.json', L, S)), Promise.resolve(null), HW.load(HW.path('awards.json', L, S)),
    isCur ? HW.load(HW.path('valuation.json', L, S)) : Promise.resolve(null), HW.load(HW.lpath('history.json', L)), HW.load(HW.path('value.json', L, S))]).then(arr => {
    if (!U.alive(el)) return;
    const season = U.ok(arr[0]) ? arr[0] : null;
    const awards = U.ok(arr[2]) ? arr[2] : null, val = U.ok(arr[3]) ? arr[3] : null, hist = U.ok(arr[4]) ? arr[4] : null;
    const sim = HW.simTeams(season);
    const recs = U.records(season);
    const ph = isCur ? (info.phase || (season && season.phase)) : 'offseason';
    const today = isCur ? (info.today || []) : [], next = isCur ? (info.next_games || []) : [], last = isCur ? (info.last_games || []) : [];
    const upcoming = today.concat(next).filter(g => HW.gameState(g) === 'pre' && U.fresh(g)).sort((a, b) => String(a.date).localeCompare(String(b.date)));
    const R = (season && season.ratings) || {};
    let power = ((season && season.power) || []).map(r => ({ tid: String(r[0]), net: r[1], chg: r[2], se: (R[String(r[0])] || {}).se_net }));
    if (!power.length) power = Object.keys(R).map(t => ({ tid: t, net: R[t].net, se: R[t].se_net })).filter(r => isNum(r.net)).sort((a, b) => b.net - a.net);
    const histRow = hist && (hist.seasons || []).find(x => Number(x.season) === Number(S));
    const champRow = (info.champions || []).find(c => Number(c[0]) === Number(S));
    // MVP favourite (ours) or the season's MVP
    let mvp = null;
    if (isCur && awards && awards.mvp && awards.mvp.model) {
      const m = awards.mvp.model;
      const top = Object.keys(m).sort((a, b) => (m[b] || 0) - (m[a] || 0))[0];
      if (top) mvp = { id: top, name: HW.playerShort(L, top), p: m[top] };
    } else if (histRow && histRow.mvp) mvp = { id: histRow.mvp, name: HW.NAMES[L].players[String(histRow.mvp)] ? HW.playerShort(L, histRow.mvp) : String(histRow.mvp) };
    const nSims = season && season.sim && season.sim.n_sims;
    const d = { isCur: isCur, sim: sim, power: power, mvp: mvp, today: today, next: next, last: last, upcoming: upcoming, phase: ph, nSims: nSims,
      stale: today.concat(next).some(g => !U.fresh(g)),
      champ: histRow ? histRow.champion : (champRow ? champRow[1] : null), histRow: histRow, best: histRow ? histRow.best_record : null };
    const P = { preseason: 'Projections from the preseason ratings until opening night; records start with the first game.', regular: 'Our chances update after every game from 20,000 simulations of the rest of the season.',
      playin: 'Play-in week: our chances update after every game.', playoffs: 'Series and title chances update after every game.', offseason: isCur ? 'The season is over; projections return with the next schedule.' : 'Final numbers for the season.' };
    const sub = (isCur ? 'Our win chance for every game, playoff and title chances from simulated seasons, team ratings and the players behind it all. ' : '') + (P[ph] || '');
    const openSim = Object.keys(sim).some(t => isNum(sim[t].w_p05) && sim[t].w_p95 > sim[t].w_p05);
    const series = (season && season.postseason && season.postseason.series) || [];
    const liveSeries = isCur && ph === 'playoffs' ? series.filter(x => !/wins series/i.test(x.summary || '')) : [];
    const lev = isCur ? leverage(sim, today.concat(next)) : [];
    const ld = (season && season.leaders) || {};
    const ldKeys = ['pts', 'reb', 'ast', '3pm', 'stl', 'blk', 'ts', 'hpm'].filter(k => (ld[k] || []).length);
    const G = isCur ? gamesBlock(d) : { today: [], next: [], last: [] };
    const tickList = G.today.concat(G.next.slice(0, 8), G.last.slice(0, 8)).map(g => U.game(g, L, { records: recs }));

    const LN = HW.leagueName(L);
    const evening = new Date(QK.now()).getHours() >= 15;
    const when = evening ? 'tonight' : 'today';
    /* the game to watch: live first, then the closest calls in the next two days (QK.watchScore) */
    const feat = G.today.concat(G.next).map(g => U.game(g, L, { records: recs })).filter(g => g.status !== 'final').map(g => [QK.watchScore(g), g]).filter(x => x[0] > -1e8).sort((a, b) => b[0] - a[0])[0];
    /* the split hero: the league on the status chip, the occasion (a series game) or our pick as the volt tag */
    const featHTML = fg => {
      const raw = G.today.concat(G.next).filter(x => String(x.id) === String(fg.id))[0] || {}, sr = raw.series || null;
      const occ = sr && sr.round ? sr.round + (sr.game ? ' · Game ' + sr.game : '') : '';
      return QK.featureCard(Object.assign({}, fg, { league: LN }), { scribble: occ || (fg.status === 'live' ? 'Live now!' : 'Our pick ' + when + '!'), nick: t => t.short || t.name });
    };
    let h = (tickList.length ? '<div class="qk-ticker hw-ticker" aria-label="Scores and our chances">' + QK.ticker(tickList, { group: false, league: true }) + '</div>' : '');
    if (isCur) {
      h += QK.greeting({ date: U.kicker(L, S),
        title: esc(QK.greet()) + '! Here’s what’s ' + QK.mark('worth watching') + ' in the ' + esc(LN) + ' ' + when + '.',
        lede: 'Our chance for every game, playoff and title chances from ' + Number(nSims || 20000).toLocaleString('en-GB') + ' simulated seasons, team ratings and the players behind it all, in plain English. ' + (P[ph] || ''),
        ctas: [{ label: 'All games', href: HW.href(L, 'games') }, { label: 'Standings', href: HW.href(L, 'standings', S), ghost: true }],
        side: feat ? featHTML(feat[1]) : '' });
    } else {
      h += U.secHead('How the ' + LN + ' ' + HW.seasonLabel(L, S) + ' season went', esc(sub), null, null, U.kicker(L, S), '<a class="qk-btn" href="' + esc(HW.href(L, 'standings', S)) + '">Final standings</a>');
    }
    h += '<div class="hw-tiles">' + tiles(L, S, d) + '</div>';
    let first = null;
    if (G.today.length || G.next.length || G.last.length) {
      first = G.today.length ? 'today' : G.next.length ? 'next' : 'results';
      const segB = [['today', 'Today', G.today], ['next', 'Next', G.next], ['results', 'Results', G.last]].filter(x => x[2].length);
      const seg = '<div class="qk-seg" id="ov-when" role="group" aria-label="Games">' + segB.map(x => '<button type="button" aria-pressed="' + (x[0] === first) + '" data-value="' + x[0] + '">' + x[1] + '</button>').join('') + '</div>';
      h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'What to watch ' + when, title: '<span id="ov-gh">Games</span>', html: true, sub: 'Our chance for each side, with a line on why it’s worth your time. Live games update as they go.', actions: seg }) +
        '<div class="qk-watch" id="ov-games"></div></section>';
    }
    // who's hot: the qualified leaders, one card each
    const HOT = [['pts', 'Most points', 'points a game', 'Per game, among players over the minutes floor.'], ['reb', 'Most rebounds', 'rebounds a game', 'Per game, among players over the minutes floor.'],
      ['ast', 'Most assists', 'assists a game', 'Per game, among players over the minutes floor.'], ['hpm', 'Biggest impact', 'points per 100 (HPM)', 'Points per 100 trips the player adds to the team’s margin over an average player.'],
      ['ts', 'Best shooter', 'true shooting', 'Points per shot, threes and free throws counted.']];
    const hot = HOT.filter(x => (ld[x[0]] || []).length).map(x => {
      const r = ld[x[0]][0], r2 = ld[x[0]][1], p = HW.NAMES[L].players[String(r[0])] || {}, p2 = r2 ? HW.NAMES[L].players[String(r2[0])] || {} : null;
      const fv = v => (x[0] === 'ts' ? HW.fmtVal(v, 'pct') : x[0] === 'hpm' ? U.signed(v, 1) : U.f(v, 1));
      return { sport: 'basketball', kicker: LN + (p.team ? ' · ' + HW.teamAbbr(L, p.team) : ''), title: x[1], name: p.name || HW.playerName(L, r[0]), value: fv(r[1]), unit: x[2], next: p2 ? { name: p2.name || HW.playerName(L, r2[0]), value: fv(r2[1]) } : null, expl: x[3], href: HW.playerHref(L, r[0], S) };
    });
    /* Who's hot: the black power list, the top qualified name on five boards */
    if (hot.length) h += QK.band(QK.sectionHead({ kicker: isCur ? 'Who’s hot' : 'The season’s best', title: isCur ? 'The leaders, stat by stat' : 'Who led the way',
      sub: 'The top name on five boards, the next best behind, and a line on what the number means. Qualified players only.',
      actions: '<a class="qk-more" href="' + esc(HW.href(L, 'players', S) + (HW.sq(L, S) ? '&' : '?') + 'tab=leaders') + '">Every leader</a>' }) + QK.hotRow(hot));
    /* We say it. Then we check it. (filled from calibration.json) beside Who's for real? (win % against net rating) */
    const realHTML = '<div class="hw-ov-real">' + QK.sectionHead({ kicker: 'Who’s for real?', title: 'Results v chances', sub: 'Teams top-left are winning more than their play suggests; bottom-right, the reverse. Luck, or something real?' }) +
      '<div class="qk-card"><div class="qk-card-body"><div id="ov-luck" class="qk-chart" role="img" aria-label="Win percentage against net rating"></div><p class="qk-caption" id="ov-luck-cap"></p></div></div></div>';
    h += isCur ? '<section class="qk-section qk-g75"><div><div id="ov-sure-h"></div><div id="ov-sure"></div></div>' + realHTML + '</section>' : '<section class="qk-section">' + realHTML + '</section>';
    if (isCur) h += '<section class="qk-section">' + QK.newHere({ items: [QK.NEW_HERE[0],
      'A <b>percentile</b> ranks a player against the same role (guards, wings or bigs): 90th means better than 90 in 100.',
      'Every forecast is checked against what happened. <a class="qk-link" href="' + esc(HW.href(L, 'model') + '?tab=calibration') + '">The record is on the Model page.</a>'] }) + '</section>';
    if (liveSeries.length) {
      h += '<section class="qk-section">' + U.head({ kicker: 'Playoffs', title: 'Series in progress', sub: 'The bracket has every round and each team’s chance of reaching it.', actions: '<a class="qk-btn" href="' + esc(HW.href(L, 'standings') + '?tab=bracket') + '">Bracket →</a>' }) +
        '<div class="hw-mini-grid">' + liveSeries.map(x => seriesTile(L, x, sim)).join('') + '</div></section>';
    }
    const tTeams = Object.keys(sim).filter(t => isNum(sim[t].p_title) && sim[t].p_title > 0);
    const awKeys = awards ? (awards.keys || Object.keys(AWN)).filter(k => awards[k] && awards[k].model && Object.keys(awards[k].model).length) : [];
    if (isCur && (tTeams.length || awKeys.length)) {
      h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Title race', title: 'Who lifts the trophy?', html: true,
        sub: '<span id="ov-title-lede">Our title chances from ' + Number(nSims || 20000).toLocaleString('en-GB') + ' simulated seasons, and our chance for each award.</span>',
        actions: '<a class="qk-more" href="' + esc(HW.href(L, 'standings', S) + (HW.sq(L, S) ? '&' : '?') + 'tab=odds') + '">Every season forecast</a>' }) + '<div class="qk-grid">';
      if (tTeams.length) h += '<div class="qk-span-' + (awKeys.length ? 6 : 12) + '">' + U.card2('Title chances', 'Our chance from the season simulation, in team colours', '<div id="ov-title"></div>',
        { foot: '<span>' + (tTeams.length > 10 ? 'Top ten of ' + tTeams.length : 'Every team still in it') + '</span>' + U.link(HW.href(L, 'standings', S) + (HW.sq(L, S) ? '&' : '?') + 'tab=odds', 'Every season forecast') }) + '</div>';
      if (awKeys.length) h += '<div class="qk-span-' + (tTeams.length ? 6 : 12) + '">' + U.card2('Award races', 'Our chance of winning each award', '<div class="qk-seg" id="ov-aw-seg" role="group" aria-label="Award" style="margin-bottom:10px">' + awKeys.map((k, i) => '<button type="button" data-value="' + k + '" aria-pressed="' + (i === 0) + '">' + esc(AWN[k] || k.toUpperCase()) + '</button>').join('') + '</div><div id="ov-aw"></div>',
        { foot: '<span></span>' + U.link(HW.href(L, 'players') + '?tab=awards', 'Every race with the reasoning') }) + '</div>';
      h += '</div></section>';
    }
    if (power.length || (isCur && openSim)) {
      h += '<section class="qk-section">' + U.head({ kicker: 'Team strength', title: isCur && openSim ? 'Ratings and projections' : 'Ratings', sub: isCur && openSim ? 'How good each team is per 100 possessions, and where the simulation thinks it finishes.' : 'How good each team was per 100 possessions, opponent-adjusted.' }) + '<div class="qk-grid">';
      if (isCur && openSim) h += '<div class="qk-span-7">' + U.card2('Projected wins', 'Mean of the simulated seasons (dot) and its 90% range (bar)', U.chart('ov-wins', Math.max(340, 22 * Object.keys(sim).length + 70), 'Projected wins with a 90% range'), { foot: '<span>Range: 5th to 95th percentile of the simulated seasons</span>' + U.link(HW.href(L, 'standings', S), 'Standings') }) + '</div>';
      if (power.length) h += '<div class="qk-span-' + (isCur && openSim ? 5 : 12) + '">' + U.card2('Power ratings', 'Net points per 100 possessions against an average team, opponent-adjusted', U.chart('ov-power', Math.max(280, 22 * power.length + 60), 'Power ratings'), { foot: '<span>All ' + power.length + ' teams</span>' + U.link(HW.href(L, 'teams', S), 'Every team') }) + '</div>';
      h += '</div></section>';
    }
    // playoff picture / standings
    const st = (season && season.standings) || {};
    const confs = Object.keys(st).filter(c => (st[c] || []).length);
    if (confs.length) {
      h += '<section class="qk-section">' + U.head({ kicker: 'Standings', title: ph === 'preseason' ? 'Projected standings' : isCur ? 'Playoff picture' : 'Final standings',
        sub: isCur ? 'Projected wins, our chance of a playoff place (play-in excluded) and of the title.' : 'Records and seeds.', actions: '<a class="qk-btn" href="' + esc(HW.href(L, 'standings', S)) + '">Full standings →</a>' }) + '<div class="qk-grid">' +
        confs.map((c, i) => '<div class="qk-span-6">' + U.card2(c, '', '<div id="ov-st-' + i + '"></div>', { flush: true }) + '</div>').join('') + '</div></section>';
    }
    // value and leverage
    const sv = U.ok(arr[5]) ? arr[5] : null;
    let vrows = U.rowsOf(val).filter(r => isNum(r.w0)).sort((a, b) => b.w0 - a.w0).slice(0, 12);
    const seasonWar = !vrows.length && sv;
    if (seasonWar) vrows = U.rowsOf(sv).filter(r => isNum(r.war) && r.q).sort((a, b) => b.war - a.war).slice(0, 12).map(r => Object.assign({}, r, { w0: r.war }));
    if (vrows.length || lev.length) {
      h += '<section class="qk-section">' + U.head({ kicker: 'Value', title: 'Who matters, and which games do', sub: seasonWar ? 'Wins above replacement from HPM and minutes.' : 'Projected wins above replacement for the rest of the season, and the games that swing the most.', actions: '<a class="qk-btn" href="' + esc(HW.href(L, 'value')) + '">Value &amp; Moves →</a>' }) + '<div class="qk-grid">' +
        (vrows.length ? '<div class="qk-span-' + (lev.length ? 7 : 12) + '">' + U.card2('Most valuable players', seasonWar ? 'Wins above replacement over the season (qualified players)' : 'Projected WAR, rest of season (current rosters)', U.chart('ov-war', 28 * vrows.length + 60, 'Most valuable players')) + '</div>' : '') +
        (lev.length ? '<div class="qk-span-' + (vrows.length ? 5 : 12) + '">' + U.card2('Games that matter most', 'Combined swing in both teams’ ' + (ph === 'playoffs' ? 'title' : 'playoff') + ' chances between a win and a loss', '<ul class="hw-list hw-lead">' + lev.slice(0, 8).map(x =>
          '<li><a href="' + esc(HW.gameHref(L, x.id, x.season || S)) + '" class="hw-ent"><span class="nm">' + esc(HW.teamAbbr(L, x.away) + ' @ ' + HW.teamAbbr(L, x.home)) + '</span><span class="sb">' + esc(HW.fmtDate(x.date, { year: false })) + '</span></a>' +
          '<span class="s">' + (isNum(x.p_home) ? 'our chance: ' + esc(HW.teamAbbr(L, x.home)) + ' ' + U.pct(x.p_home) : '') + '</span><span class="v">' + U.f(x.lev * 100, 1) + ' pts</span></li>').join('') + '</ul>' +
          '<div style="padding:4px 16px 16px">' + QK.note('A swing of <b>' + U.f(lev[0].lev * 100, 0) + ' pts</b> means a win instead of a loss moves the two teams’ ' + (ph === 'playoffs' ? 'title' : 'playoff') + ' chances by that many percentage points between them.') + '</div>', { flush: true }) + '</div>' : '') +
        '</div></section>';
    }
    if (ldKeys.length) {
      const LDL = { pts: 'Points', reb: 'Rebounds', ast: 'Assists', '3pm': 'Threes', stl: 'Steals', blk: 'Blocks', ts: 'True shooting', hpm: 'Total impact (HPM)' };
      h += '<section class="qk-section">' + U.head({ kicker: 'Leaderboards', title: 'Every leaderboard', sub: 'Per game; qualified players only (the league’s minimum games and minutes).', actions: '<a class="qk-btn" href="' + esc(HW.href(L, 'players', S) + (HW.sq(L, S) ? '&' : '?') + 'tab=leaders') + '">Players →</a>' }) +
        '<div class="hw-leaders">' + ldKeys.map(k => '<div class="qk-card"><div class="qk-card-head"><div class="qk-card-title">' + esc(LDL[k]) + '</div></div><ul class="hw-list hw-lead">' +
          ld[k].slice(0, 5).map((r, i) => { const p = HW.NAMES[L].players[String(r[0])] || {};
            return '<li><span class="n">' + (i + 1) + '</span>' + U.playerEnt(L, r[0], p.name, p.team, null, S) + '<span class="v">' + HW.fmtVal(r[1], k === 'ts' ? 'pct' : k === 'hpm' ? 'pm' : '1') + '</span></li>'; }).join('') + '</ul></div>').join('') + '</div></section>';
    }
    el.innerHTML = h;

    // ── scoreboard
    if (first) {
      const draw = w => {
        const list = w === 'next' ? G.next : w === 'results' ? G.last : G.today;
        const n = list.length;
        const ttl = document.getElementById('ov-gh');
        const W = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen'];
        if (ttl) ttl.textContent = w === 'next' ? 'Next up. Our calls.' : w === 'results' ? 'Latest results' : (W[n] || n) + ' game' + (n === 1 ? '' : 's') + '. Our calls.';
        document.getElementById('ov-games').innerHTML = list.length ? list.map(g => U.card(g, L, { records: recs, why: true })).join('') : QK.empty('No games', 'Nothing to show yet.');
      };
      draw(first);
      QK.seg(document.getElementById('ov-when'), draw);
    }
    // ── charts
    /* the title race in team colours, ours only (the market is on game pages and the Model page) */
    if (document.getElementById('ov-title')) {
      const tRows = tTeams.map(t => ({ label: HW.teamShort(L, t), p: sim[t].p_title, href: HW.teamHref(L, t, S), mark: U.team(L, t), color: HW.teamColourRaw(L, t) }));
      document.getElementById('ov-title').innerHTML = QK.chances(tRows, { limit: 10, key: false });
      const t0 = tRows.slice().sort((a, b) => b.p - a.p)[0], lede = document.getElementById('ov-title-lede');
      if (t0 && lede) lede.textContent = (t0.p < 0.2 ? 'Nobody’s better than 1 in 5. The ' + t0.label + ' lead our board at ' + U.pct(t0.p) + '.'
        : 'The ' + t0.label + ' lead at ' + U.pct(t0.p) + (t0.p >= 0.5 ? ': they win it in about ' + Math.round(t0.p * 10) + ' of 10 simulated seasons.' : '.')) +
        ' From ' + Number(nSims || 20000).toLocaleString('en-GB') + ' simulated seasons; our award chances beside it.';
    }
    /* Who's for real?: win % against our net rating (QKC.quadrant), the corners named */
    if (document.getElementById('ov-luck')) {
      const sRows = []; confs.forEach(c => (st[c] || []).forEach(r => sRows.push(r)));
      const luck = sRows.filter(r => isNum((R[String(r.team)] || {}).net) && isNum(r.w) && isNum(r.l) && r.w + r.l > 0);
      const pts = luck.map(r => ({ x: R[String(r.team)].net, y: r.w / (r.w + r.l) * 100, name: HW.teamName(L, r.team), sub: HW.record(r.w, r.l) + ' · net rating ' + U.signed(R[String(r.team)].net, 1),
        label: HW.teamAbbr(L, r.team), color: HW.teamColourRaw(L, r.team), href: HW.teamHref(L, r.team, S) }));
      if (pts.length >= 6) {
        const gps = luck.map(r => r.w + r.l), g0 = Math.min.apply(null, gps), g1 = Math.max.apply(null, gps);
        QKC.quadrant('#ov-luck', { points: pts, xName: 'Net rating (points per 100 possessions)', yName: 'Games won (%)', refX: 0, refY: 50,
          xFmt: v => U.signed(v, 0), yFmt: v => Math.round(v) + '%', label: LN + ' teams: net rating against games won' });
        document.getElementById('ov-luck-cap').textContent = LN + ' ' + HW.seasonLabel(L, S) + ', ' + (g0 === g1 ? g0 : g0 + '–' + g1) + ' games each. Net rating is our opponent-adjusted points per 100 possessions better than an average team. Dashed lines: an average team and a .500 record. Tap a team for its page.';
      } else document.getElementById('ov-luck').innerHTML = QK.empty('Not yet', 'The chart fills in after the first games.');
    }
    if (document.getElementById('ov-aw')) {
      const drawAw = k => {
        const a = awards[k];
        document.getElementById('ov-aw').innerHTML = QK.chances(Object.keys(a.model).map(id => {
          const tm = (HW.NAMES[L].players[String(id)] || {}).team;
          return { label: HW.playerName(L, id), p: a.model[id] || 0, color: tm ? HW.teamColourRaw(L, tm) : null, href: HW.playerHref(L, id), mark: tm ? U.team(L, tm) : null };
        }), { limit: 8, oursName: 'Our chance' });
      };
      drawAw(awKeys[0]);
      QK.seg(document.getElementById('ov-aw-seg'), drawAw);
    }
    if (document.getElementById('ov-wins')) {
      const rows = Object.keys(sim).filter(t => isNum(sim[t].exp_w) && isNum(sim[t].w_p05) && isNum(sim[t].w_p95)).sort((a, b) => sim[b].exp_w - sim[a].exp_w);
      QKC.range('#ov-wins', { rows: rows.map(t => ({ label: HW.teamName(L, t), lo: sim[t].w_p05, hi: sim[t].w_p95, mid: sim[t].exp_w, href: HW.teamHref(L, t, S), color: HW.teamColourRaw(L, t),
        sub: isNum(sim[t].p_playoffs) ? U.pct(sim[t].p_playoffs) + ' to make the playoffs' : '' })), fmt: v => U.f(v, 0), loName: '5th', hiName: '95th percentile', midName: 'Projected wins',
        valName: 'Wins at season end', labelWidth: 150, label: 'Projected wins with a 90% range' });
    }
    if (document.getElementById('ov-power')) {
      QKC.bar('#ov-power', { cats: power.map(r => HW.teamAbbr(L, r.tid)), series: [{ name: 'Net rating', data: power.map(r => Math.round(r.net * 10) / 10) }], horizontal: true, labels: true, fmt: v => U.signed(v, 1),
        colors: power.map(r => U.tcol(L, r.tid)), hrefs: power.map(r => HW.teamHref(L, r.tid, S)), labelWidth: 46, valName: 'Net rating (points per 100 possessions)', catName: 'Team' });
    }
    confs.forEach((c, i) => {
      const node = document.getElementById('ov-st-' + i);
      const pre = ph === 'preseason';
      const rows = (st[c] || []).map(r => Object.assign({}, r, { s: sim[r.team] || {} }));
      if (pre) rows.sort((a, b) => (b.s.exp_w || 0) - (a.s.exp_w || 0));
      rows.forEach((r, j) => { r.pp = r.s.p_playoffs; r.pt = r.s.p_title; r.exp = r.s.exp_w; r.nm = HW.teamShort(L, r.team); r.rk = pre ? j + 1 : (r.seed || j + 1); });
      const cols = [{ key: 'rk', label: '#', num: true },
        { key: 'nm', label: 'Team', type: 'entity', mark: r => U.team(L, r.team), href: r => HW.teamHref(L, r.team, S) },
        pre ? { key: 'exp', label: 'Proj W', num: true, fmt: v => U.f(v, 1), tip: 'Projected wins: mean of the simulated seasons' } : { key: 'w', label: 'W-L', num: true, fmt: (v, r) => HW.record(r.w, r.l) }];
      if (isCur && Object.keys(sim).length) {
        cols.push({ key: 'pp', label: 'Playoffs', type: 'bar', max: 1, fmt: v => U.pct(v), tip: 'Our chance of a playoff place (play-in excluded)' });
        cols.push({ key: 'pt', label: 'Title', num: true, fmt: v => U.pct(v), tip: 'Our title chance' });
      } else cols.push({ key: 'pd', label: 'Diff', num: true, fmt: v => U.sgnHTML(v, 0), tip: 'Points differential' });
      QK.leaderboard(node, { columns: cols, rows: rows.slice(0, 10), dense: true, rowHref: r => HW.teamHref(L, r.team, S) });
    });
    if (document.getElementById('ov-war')) {
      QKC.bar('#ov-war', { cats: vrows.map(r => r.name), series: [{ name: 'WAR', data: vrows.map(r => Math.round(r.w0 * 10) / 10) }], horizontal: true, labels: true, fmt: v => U.f(v, 1),
        colors: vrows.map(r => U.tcol(L, r.team)), hrefs: vrows.map(r => HW.playerHref(L, r.id)), labelWidth: 150, valName: seasonWar ? 'Wins above replacement' : 'Projected WAR, rest of season', catName: 'Player' });
    }
    /* We say it. Then we check it.: the game model's record from <L>/calibration.json (QK.howSure: big numbers and
       the we-said / it-happened bars); the full record is on the Model page */
    if (isCur) HW.load(L + '/calibration.json').then(cj => {
      const box = el.querySelector('#ov-sure'), hd = el.querySelector('#ov-sure-h');
      const cb = QK.calib.find(U.ok(cj) ? cj : null);
      if (!box || !hd) return;
      if (!cb || !cb.bins.length) { box.innerHTML = ''; hd.innerHTML = ''; return; }
      hd.innerHTML = QK.sectionHead({ kicker: 'How sure are we?', title: 'We say it. Then we check it.', sub: 'Every ' + LN + ' game we have forecast, grouped by the chance we gave the home team. When the two bars match, our numbers mean what they say.',
        actions: '<a class="qk-more" href="' + esc(HW.href(L, 'model') + '?tab=calibration') + '">The full record</a>' });
      QK.howSure(box, { calibration: cj, league: LN, subject: 'the home team' });
    });
    const nx = upcoming[0];
    if (nx && !today.some(g => HW.gameState(g) === 'in' && U.fresh(g))) HW.interval(() => { const n = document.getElementById('ov-cd'); if (n) n.innerHTML = cdHTML(L, nx); }, 30000);
    HW.setMeta(nSims ? Number(nSims).toLocaleString('en-GB') + ' season simulations' + (season.updated_at ? ' · model ' + esc(HW.fmtStamp(season.updated_at)) : '') : '');
  });
}

function probBar(p, c) {
  if (!isNum(p)) return '—';
  return '<span class="hw-pbar"><span style="width:' + Math.max(1, p * 100).toFixed(1) + '%;background:' + esc(c) + '"></span></span><span class="hw-pv">' + U.pct(p) + '</span>';
}
HW.ui.probBar = probBar;

function seriesTile(L, s, sim) {
  const t = s.teams || [];
  const w = s.wins || {};
  const a = t[0], b = t[1];
  const pa = (sim[a] || {}).p_title, pb = (sim[b] || {}).p_title;
  /* v4: a black block, each side on a team-colour edge with its series wins in Bebas */
  return '<div class="hw-series"><div class="hw-series-k">' + esc(s.round || 'Series') + '</div>' +
    [a, b].map(x => '<div class="hw-series-r" style="--tc:' + esc(U.tcol(L, x)) + '">' + QK.teamMark(U.team(L, x), 'sm') + '<a class="nm" href="' + esc(HW.teamHref(L, x)) + '">' + esc(HW.teamShort(L, x)) + '</a><b class="num">' + (isNum(w[x]) ? w[x] : 0) + '</b></div>').join('') +
    '<div class="hw-series-f">' + (s.summary ? esc(s.summary) + '. ' : '') + (isNum(pa) || isNum(pb) ? 'Our title chance: ' + esc(HW.teamAbbr(L, a)) + ' ' + U.pct(pa) + ', ' + esc(HW.teamAbbr(L, b)) + ' ' + U.pct(pb) + '.' : '') + '</div></div>';
}

HW.page('hub', render);
})(window.HW);
