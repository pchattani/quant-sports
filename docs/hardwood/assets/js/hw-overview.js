/* The Quant Hardwood — Overview (#/<L>), on Design System 2.0 (the Rink overview is the reference).
 *
 *   a scoreboard ticker; headline and stat tiles: the title favourite (ours), the best team, the MVP favourite,
 *     the next tip-off or live games, the closest call coming up (no market headline);
 *   live, today's, next and recent games as v2 game cards (our chance first, the market a quiet tick);
 *   who wins it all (chance bars, the market a grey tick) and the award races; projected wins with the
 *     simulation's 90% range and power ratings; the playoff picture (series when the playoffs are on); most
 *     valuable players (projected WAR), the games that matter most; leaders (qualified players only).
 * A past season shows its champion, final standings and leaders.
 * Reads index.json, <L>/<S>/season.json, <L>/markets.json, <L>/<S>/awards.json, <L>/<S>/valuation.json, <L>/history.json. */
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
    out.push({ id: nx.game, lev: swing(nx) + swing(other), date: card ? card.date : nx.date, home: nx.home ? tid : nx.opp, away: nx.home ? nx.opp : tid,
      p_home: nx.home ? nx.p_win : (isNum(nx.p_win) ? 1 - nx.p_win : null) });
  });
  return out.filter(x => x.lev > 0.005).sort((a, b) => b.lev - a.lev);
}

function tiles(L, S, d) {
  const out = [];
  const sim = d.sim, tT = Object.keys(sim).filter(t => isNum(sim[t].p_title)).sort((a, b) => sim[b].p_title - sim[a].p_title);
  if (d.isCur) {
    const fav = tT[0];
    out.push({ label: 'Title favourite', value: fav ? HW.teamAbbr(L, fav) + ' ' + U.pct(sim[fav].p_title) : '—', signal: true, href: fav ? HW.teamHref(L, fav) : null,
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
      out.push({ label: 'Closest call', value: HW.teamAbbr(L, fav) + ' ' + U.pct(Math.max(ph, 1 - ph)), href: HW.gameHref(L, close.id), sub: HW.teamAbbr(L, close.away) + ' @ ' + HW.teamAbbr(L, close.home) + ' · ' + HW.fmtDate(close.date, { year: false }), tip: 'The upcoming game nearest a coin flip by our chance' });
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
  return Promise.all([HW.load(HW.path('season.json', L, S)), HW.load(HW.lpath('markets.json', L)), HW.load(HW.path('awards.json', L, S)),
    isCur ? HW.load(HW.path('valuation.json', L, S)) : Promise.resolve(null), HW.load(HW.lpath('history.json', L)), HW.load(HW.path('value.json', L, S))]).then(arr => {
    if (!U.alive(el)) return;
    const season = U.ok(arr[0]) ? arr[0] : null, markets = U.ok(arr[1]) && String(arr[1].season) === String(S) ? arr[1] : null;
    const awards = U.ok(arr[2]) ? arr[2] : null, val = U.ok(arr[3]) ? arr[3] : null, hist = U.ok(arr[4]) ? arr[4] : null;
    const sim = HW.simTeams(season);
    const recs = U.records(season);
    const ph = isCur ? (info.phase || (season && season.phase)) : 'offseason';
    const today = isCur ? (info.today || []) : [], next = isCur ? (info.next_games || []) : [], last = isCur ? (info.last_games || []) : [];
    const upcoming = today.concat(next).filter(g => HW.gameState(g) === 'pre' && U.fresh(g)).sort((a, b) => String(a.date).localeCompare(String(b.date)));
    const mkTitle = HW.titleProbs(markets && markets.futures && markets.futures.champion);
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

    const title = isCur ? 'Every ' + HW.leagueName(L) + ' game, by the numbers.' : HW.leagueName(L) + ' ' + HW.seasonLabel(L, S) + ', by the numbers.';
    let h = (tickList.length ? '<div class="qk-ticker hw-ticker" aria-label="Scores and our chances">' + QK.ticker(tickList, { group: false, league: true }) + '</div>' : '') +
      U.secHead(title, esc(sub), null, null, U.kicker(L, S), '<a class="qk-btn" href="' + esc(HW.href(L, 'games')) + '">All games</a><a class="qk-btn" href="' + esc(HW.href(L, 'standings', S)) + '">Standings</a>') + tiles(L, S, d);
    let first = null;
    if (G.today.length || G.next.length || G.last.length) {
      first = G.today.length ? 'today' : G.next.length ? 'next' : 'results';
      const segB = [['today', 'Today', G.today], ['next', 'Next', G.next], ['results', 'Results', G.last]].filter(x => x[2].length);
      const seg = '<div class="qk-seg" id="ov-when" role="group" aria-label="Games">' + segB.map(x => '<button type="button" aria-pressed="' + (x[0] === first) + '" data-value="' + x[0] + '">' + x[1] + '</button>').join('') + '</div>';
      h += '<section class="qk-section hw-sec0">' + U.head({ kicker: 'Scoreboard', title: 'Games', sub: 'Our win chance on every card, the favourite in violet. A grey tick on the bar marks the market, for reference.', actions: seg }) +
        '<div class="hw-games hw-gc" id="ov-games"></div></section>';
    }
    if (liveSeries.length) {
      h += '<section class="qk-section">' + U.head({ kicker: 'Playoffs', title: 'Series in progress', sub: 'The bracket has every round and each team’s chance of reaching it.', actions: '<a class="qk-btn" href="' + esc(HW.href(L, 'standings') + '?tab=bracket') + '">Bracket →</a>' }) +
        '<div class="hw-mini-grid">' + liveSeries.map(x => seriesTile(L, x, sim)).join('') + '</div></section>';
    }
    const tTeams = Object.keys(sim).filter(t => isNum(sim[t].p_title) && sim[t].p_title > 0);
    const awKeys = awards ? (awards.keys || Object.keys(AWN)).filter(k => awards[k] && awards[k].model && Object.keys(awards[k].model).length) : [];
    if (isCur && (tTeams.length || awKeys.length)) {
      h += '<section class="qk-section">' + U.head({ kicker: 'Season simulation', title: 'Who wins it all', sub: 'Our title chances from ' + Number(nSims || 20000).toLocaleString('en-GB') + ' simulated seasons, and our chance for each award.' }) + '<div class="qk-grid">';
      if (tTeams.length) h += '<div class="qk-span-' + (awKeys.length ? 6 : 12) + '">' + U.card2('Title chances', Object.keys(mkTitle).length ? 'Our chance; the grey tick is the Kalshi / Polymarket number, for reference' : 'Our chance from the season simulation', '<div id="ov-title"></div>',
        { foot: '<span>Top twelve</span>' + U.link(HW.href(L, 'standings', S) + (HW.sq(L, S) ? '&' : '?') + 'tab=odds', 'Every season forecast') }) + '</div>';
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
      h += '<section class="qk-section">' + U.head({ kicker: 'Value', title: 'Who and what matters', sub: seasonWar ? 'Wins above replacement from HPM and minutes.' : 'Projected wins above replacement for the rest of the season, and the games that swing the most.', actions: '<a class="qk-btn" href="' + esc(HW.href(L, 'value')) + '">Value &amp; Moves →</a>' }) + '<div class="qk-grid">' +
        (vrows.length ? '<div class="qk-span-' + (lev.length ? 7 : 12) + '">' + U.card2('Most valuable players', seasonWar ? 'Wins above replacement over the season (qualified players)' : 'Projected WAR, rest of season (current rosters)', U.chart('ov-war', 28 * vrows.length + 60, 'Most valuable players')) + '</div>' : '') +
        (lev.length ? '<div class="qk-span-' + (vrows.length ? 5 : 12) + '">' + U.card2('Games that matter most', 'Combined swing in both teams’ ' + (ph === 'playoffs' ? 'title' : 'playoff') + ' chances between a win and a loss', '<ul class="hw-list hw-lead">' + lev.slice(0, 8).map(x =>
          '<li><a href="' + esc(HW.gameHref(L, x.id)) + '" class="hw-ent"><span class="nm">' + esc(HW.teamAbbr(L, x.away) + ' @ ' + HW.teamAbbr(L, x.home)) + '</span><span class="sb">' + esc(HW.fmtDate(x.date, { year: false })) + '</span></a>' +
          '<span class="s">' + (isNum(x.p_home) ? 'ours: ' + esc(HW.teamAbbr(L, x.home)) + ' ' + U.pct(x.p_home) : '') + '</span><span class="v">' + U.f(x.lev * 100, 1) + ' pts</span></li>').join('') + '</ul>', { flush: true }) + '</div>' : '') +
        '</div></section>';
    }
    if (ldKeys.length) {
      const LDL = { pts: 'Points', reb: 'Rebounds', ast: 'Assists', '3pm': 'Threes', stl: 'Steals', blk: 'Blocks', ts: 'True shooting', hpm: 'Total impact (HPM)' };
      h += '<section class="qk-section">' + U.head({ kicker: 'Leaderboards', title: 'Leaders', sub: 'Per game; qualified players only (the league’s minimum games and minutes).', actions: '<a class="qk-btn" href="' + esc(HW.href(L, 'players', S) + (HW.sq(L, S) ? '&' : '?') + 'tab=leaders') + '">Players →</a>' }) +
        '<div class="hw-leaders">' + ldKeys.map(k => '<div class="qk-card"><div class="qk-card-head"><div class="qk-card-title">' + esc(LDL[k]) + '</div></div><ul class="hw-list hw-lead">' +
          ld[k].slice(0, 5).map((r, i) => { const p = HW.NAMES[L].players[String(r[0])] || {};
            return '<li><span class="n">' + (i + 1) + '</span>' + U.playerEnt(L, r[0], p.name, p.team, null, S) + '<span class="v">' + HW.fmtVal(r[1], k === 'ts' ? 'pct' : k === 'hpm' ? 'pm' : '1') + '</span></li>'; }).join('') + '</ul></div>').join('') + '</div></section>';
    }
    el.innerHTML = h;

    // ── scoreboard
    if (first) {
      const draw = w => {
        const list = w === 'next' ? G.next : w === 'results' ? G.last : G.today;
        document.getElementById('ov-games').innerHTML = list.length ? list.map(g => U.card(g, L, { records: recs })).join('') : QK.empty('No games', 'Nothing to show yet.');
      };
      draw(first);
      QK.seg(document.getElementById('ov-when'), draw);
    }
    // ── charts
    if (document.getElementById('ov-title')) {
      document.getElementById('ov-title').innerHTML = QK.chances(tTeams.map(t => ({ label: HW.teamName(L, t), p: sim[t].p_title, market: isNum(mkTitle[t]) ? mkTitle[t] : null, color: HW.teamColourRaw(L, t), href: HW.teamHref(L, t), mark: U.team(L, t) })),
        { limit: 12, marketName: 'Market (Kalshi / Polymarket)', oursName: 'Our title chance' });
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
  return '<div class="hw-teamtile" style="--tc:' + esc(U.tcol(L, a)) + '"><div class="qk-kicker">' + esc(s.round || 'Series') + '</div>' +
    [a, b].map(x => '<div class="top">' + QK.teamMark(U.team(L, x), 'sm') + '<a class="nm" href="' + esc(HW.teamHref(L, x)) + '">' + esc(HW.teamName(L, x)) + '</a><span class="rec">' + (isNum(w[x]) ? w[x] : 0) + '</span></div>').join('') +
    '<div class="row"><span>' + esc(s.summary || '') + '</span><b>' + (isNum(pa) || isNum(pb) ? 'our title chance ' + esc(HW.teamAbbr(L, a)) + ' ' + U.pct(pa) + ' · ' + esc(HW.teamAbbr(L, b)) + ' ' + U.pct(pb) : '') + '</b></div></div>';
}

HW.page('hub', render);
})(window.HW);
