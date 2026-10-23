/* The Quant Gridiron — Overview (#/), on Design System 2.0 (the Rink overview is the reference).
 *   head and stat tiles: games this week, the Super Bowl favourite (ours), the top-rated team, the EPA-per-dropback
 *              leader, the closest game of the week (no market headline);
 *   scoreboard ticker and the game of the week (our win chance in display numbers, the team-colour bar);
 *   this week's games as v2 game cards with records and form; who wins it all (our chances as bars, Kalshi /
 *   Polymarket as a quiet grey tick) beside projected wins with the simulation's 90% range; power map and rating
 *   trend; the playoff race by conference (chance bars); divisions at a glance; leaders; last week.
 * Reads index.json, <S>/season.json, <S>/markets.json, glossary.json (leader labels). */
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

/* The game of the week: live first, else the upcoming game with the most at stake and the closest call. */
function featured(games, po) {
  const live = games.filter(GI.isLive);
  if (live.length) return live[0];
  const pre = games.filter(GI.isPre);
  if (!pre.length) return games[games.length - 1] || null;
  let best = null, bs = -1;
  pre.forEach(g => {
    const p = isNum((g.model || {}).p_home) ? g.model.p_home : 0.5;
    const stake = ((po[g.home] || {}).p_playoffs || 0.5) + ((po[g.away] || {}).p_playoffs || 0.5);
    const s = stake * (1 - Math.abs(p - 0.5) * 1.6);
    if (s > bs) { bs = s; best = g; }
  });
  return best;
}
function featureCard(g, po, rows) {
  if (!g) return GI.card('Game of the week', '', GI.muted('No games scheduled.'));
  const st = GI.gameState(g), live = GI.isLive(g), fin = st === 'final';
  const m = g.model || {};
  const pH = live && isNum(g.wp_home) ? g.wp_home : m.p_home;
  const cols = GI.pair(g.away, g.home);
  const rec = t => { const r = rows[t]; return r && isNum(r.w) ? GI.record(r.w, r.l, r.t) : ''; };
  const side = (t, p, sc, c) => '<a class="gi-vs-team" href="' + GI.teamHref(t) + '">' + GI.mark(t, 'lg') + '<span class="nm">' + esc(GI.teamShort(t)) + '</span>' +
    '<span class="p gi-disp" style="color:' + esc(fin || live ? 'var(--ink-1)' : c) + '">' + (fin || live ? esc(isNum(sc) ? sc : '–') : (isNum(p) ? GI.pct(p, 0) : '')) + '</span>' +
    '<span class="qk-sub">' + esc([rec(t), po[t] ? 'playoffs ' + GI.pct(po[t].p_playoffs, 0) : ''].filter(Boolean).join(' · ')) + '</span></a>';
  const mid = '<div class="gi-vs-mid">' + (live ? '<span class="qk-badge live">' + esc(GI.clockText(g.qtr, g.clock) || 'Live') + '</span>'
    : fin ? '<span class="qk-badge final">Final</span>' : '<span>' + esc(GI.fmtDate(g.kickoff, { year: false })) + '</span><span class="sc gi-vs-t">' + esc(GI.fmtTime(g.kickoff)) + '</span><span>' + esc(GI.countdown(g.kickoff) ? 'in ' + GI.countdown(g.kickoff) : '') + '</span>') + '</div>';
  const A = { name: GI.teamShort(g.away), abbr: GI.teamAbbr(g.away), colour: cols[0] }, H = { name: GI.teamShort(g.home), abbr: GI.teamAbbr(g.home), colour: cols[1] };
  const facts = [];
  const mg = GI.homeLine(m);
  if (isNum(m.home_pts) && isNum(m.away_pts)) facts.push('Our projected score <b>' + esc(GI.teamAbbr(g.away)) + ' ' + GI.num(m.away_pts, 0) + '–' + GI.num(m.home_pts, 0) + ' ' + esc(GI.teamAbbr(g.home)) + '</b>');
  if (isNum(mg) && Math.abs(mg) >= 0.5) facts.push('Projected margin <b>' + esc(GI.teamAbbr(mg < 0 ? g.home : g.away)) + ' by ' + GI.num(Math.abs(mg), 1) + '</b>');
  if (isNum(m.total)) facts.push('Points expected <b>' + GI.num(m.total, 1) + '</b>');
  return '<section class="qk-card gi-feature" style="--fa:' + esc(cols[0]) + ';--fh:' + esc(cols[1]) + '"><div class="qk-card-body">' +
    '<div class="gi-feature-top"><span class="qk-kicker">' + (live ? 'Live now' : fin ? 'Final' : 'Game of the week') + '</span><a class="gi-more" href="' + GI.gameHref(g.game_id) + '">Game centre →</a></div>' +
    '<div class="gi-vs">' + side(g.away, isNum(pH) ? 1 - pH : null, g.as, cols[0]) + mid + side(g.home, pH, g.hs, cols[1]) + '</div>' +
    (!fin && isNum(pH) ? QK.wpBar(1 - pH, null, pH, A, H, { colors: cols, size: 'lg', label: live ? 'Our live win chance' : 'Our win chance' }) : '') +
    (facts.length ? '<div class="gi-feature-foot">' + facts.map(f => '<span>' + f + '</span>').join('') + '</div>' : '') + '</div></section>';
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
  return GI.loadAll([GI.ypath('season.json', S), GI.ypath('markets.json', S), 'glossary.json']).then(res => {
    if (!el.isConnected) return;
    const season = GI.ok(res[0]) ? res[0] : null, mkts = GI.ok(res[1]) ? res[1] : null, G = glossIndex(res[2]);
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

    el.innerHTML = tick +
      GI.pageHead(S + ' · ' + phaseText + ' · ' + wk, wk + ', by the numbers.', 'Our win chance for every game, playoff and Super Bowl chances from 20,000 simulated seasons, expected points, every fourth down graded and the players behind it all.',
        '<a class="qk-btn primary" href="' + GI.weekHref(S, W) + '">All ' + esc(wk) + ' games</a><a class="qk-btn" href="#/standings">Standings</a><a class="qk-btn" href="#/playoffs">Playoff picture</a>') +
      GI.kpis([
        GI.kpi(live.length ? 'Live now' : 'Games this week', String(live.length || all.length), live.length ? all.length + ' this week' : done ? done + ' final' + (games.length - done ? ' · ' + (games.length - done) + ' to play' : '') + (stale ? ' · ' + stale + ' awaiting results' : '') : (next ? 'first kickoff ' + esc(GI.fmtDate(next, { year: false })) : '')),
        GI.kpi('Super Bowl favourite', fav ? esc(GI.teamAbbr(fav)) + ' ' + GI.pct(po[fav].p_sb, 0) : '—', fav ? esc(GI.teamShort(fav)) + ' · from 20,000 simulated seasons' : '', { signal: true, href: fav ? GI.teamHref(fav) : null, tip: 'Our chance of winning the Super Bowl in the season simulation' }),
        GI.kpi('Top-rated team', topR ? esc(GI.teamAbbr(topR)) + ' ' + GI.signed((ratings[topR].values || {}).rating, 1) : '—', topR ? 'points a game better than an average team' : '', { href: topR ? GI.teamHref(topR) : null, tip: 'Our team-strength rating: points per game better than an average team on a neutral field' }),
        GI.kpi('Best passer so far', qb ? esc(GI.playerSurname(qb[0])) + ' ' + GI.signed(qb[1], 2) : '—', qb ? 'EPA per dropback · ' + esc(GI.teamAbbr(GI.player(qb[0]).team)) : '', { href: qb ? GI.playerHref(qb[0]) : null, tip: 'Expected points added per dropback (passes, sacks and scrambles), qualified quarterbacks' }),
        GI.kpi('Closest call', close ? esc(GI.teamAbbr(close.away)) + ' @ ' + esc(GI.teamAbbr(close.home)) : '—', close ? 'our chance ' + esc(GI.teamAbbr(close.model.p_home >= 0.5 ? close.home : close.away)) + ' ' + GI.pct(Math.max(close.model.p_home, 1 - close.model.p_home), 0) : 'no games to play this week', { text: true, href: close ? GI.gameHref(close.game_id) : null })
      ]) +

      '<section class="qk-section">' + GI.secHead({ kicker: 'Scoreboard', title: esc(wk) + ' games', html: true, sub: 'Our win chance on every card, the favourite in violet; records and the last five results beside each team. A grey tick on the bar marks the market, for reference.',
        actions: '<a class="qk-btn" href="' + GI.weekHref(S, W) + '">Week page →</a>' }) +
        GI.grid('<div class="qk-span-4">' + featureCard(feat, po, byTeam) + '</div><div class="qk-span-8">' + (games.length ? '<div class="qk-auto gi-games" style="--min:290px">' + games.filter(g => g !== feat).slice(0, 8).map(g => GI.gameCard(g, { rows: byTeam })).join('') + '</div>' : QK.empty('No games this week', 'The schedule is being set.')) + '</div>') +
        (stale ? '<p class="qk-caption">' + stale + ' game' + (stale === 1 ? '' : 's') + ' from ' + esc(wk) + ' ' + (stale === 1 ? 'is' : 'are') + ' waiting for ' + (stale === 1 ? 'its result' : 'their results') + ' in the next update; the <a href="' + GI.weekHref(S, W) + '">week page</a> keeps our pre-game forecast for each.</p>' : '') +
        (games.length > 9 ? '<div class="qk-auto gi-games" style="--min:290px;margin-top:var(--sp-4)">' + games.filter(g => g !== feat).slice(8).map(g => GI.gameCard(g, { rows: byTeam })).join('') + '</div>' : '') + '</section>' +

      '<section class="qk-section">' + GI.secHead({ kicker: 'Season simulation', title: 'Who wins it all', sub: 'Our chances from 20,000 simulated seasons, with each team’s projected wins and the range it lands in nine times out of ten.', actions: '<a class="qk-btn" href="#/futures">Every season forecast →</a>' }) +
        GI.grid(GI.card('Super Bowl chances', 'Our chance; the grey tick is the Kalshi / Polymarket number, for reference', '<div id="ov-sb"></div>', { span: 5, foot: '<span>Top twelve of 32</span><a href="#/playoffs">Bracket →</a>' }) +
          GI.card('Projected wins', 'Mean of the simulated seasons (dot) and its 90% range (bar)', GI.chartBox('ov-range', 520, 'Projected wins with a 90% range'), { span: 7, foot: '<span>Range: 5th to 95th percentile of 20,000 seasons</span><a href="' + GI.standingsHref(S, 'wins') + '">Win totals →</a>' })) + '</section>' +

      '<section class="qk-section">' + GI.secHead({ kicker: 'Team strength', title: 'Power map', sub: 'Our offence and defence ratings in points per game against an average team; up and right is better.', actions: '<a class="qk-btn" href="' + GI.standingsHref(S, 'ratings') + '">Power ratings →</a>' }) +
        GI.grid(GI.card('Offence v defence', 'Points per game against an average team', GI.chartBox('ov-power', 440, 'Offence against defence rating, every team'), { span: 7 }) +
          GI.card('Rating through the season', 'The top eight teams, week by week', GI.chartBox('ov-trend', 440, 'Team rating by week'), { span: 5 })) + '</section>' +

      '<section class="qk-section">' + GI.secHead({ kicker: 'Playoff race', title: 'Who makes the playoffs', sub: 'Our chance of a playoff spot by conference, with the market as a grey tick where one trades.', actions: '<a class="qk-btn" href="#/playoffs">Seeds and bracket →</a>' }) +
        GI.grid(GI.card('AFC', 'Our playoff chance', '<div id="ov-afc"></div>', { span: 6 }) + GI.card('NFC', 'Our playoff chance', '<div id="ov-nfc"></div>', { span: 6 })) + '</section>' +

      '<section class="qk-section">' + GI.secHead({ kicker: 'Standings', title: 'Divisions', sub: 'Record and our playoff chance; tap a team for its page.', actions: '<a class="qk-btn" href="#/standings">Full standings →</a>' }) +
        GI.card('', '', divisionsGrid(rows)) + '</section>' +

      '<section class="qk-section">' + GI.secHead({ kicker: 'Leaderboards', title: 'Leaders', sub: S + ' to date, qualified players. Percentiles with sample floors are on the Players page.', actions: '<a class="qk-btn" href="#/leaders">Every leaderboard →</a>' }) +
        GI.card('', '', '<div id="ov-ld-seg"></div>' + GI.chartBox('ov-leaders', 380, 'Leaderboard')) + '</section>' +

      ((idx.recent || []).length ? '<section class="qk-section">' + GI.secHead({ kicker: 'Results', title: 'Last week', sub: GI.weekLabel(Math.max(1, W - 1), S) + ' results, with our pre-game call on each.', actions: '<a class="qk-btn" href="' + GI.weekHref(S, Math.max(1, W - 1)) + '">Week page →</a>' }) +
        '<div class="qk-auto gi-games" style="--min:260px">' + idx.recent.map(g => GI.gameCard(g, { compact: true, date: true })).join('') + '</div></section>' : '');

    // Super Bowl: our chance, the market a tick
    const sbM = {};
    ((mkts && mkts.futures && mkts.futures.sb) || []).forEach(r => { if (r && r.team) sbM[r.team] = r.market; });
    const chRow = (t, p, mk) => ({ label: GI.teamName(t), p: p, market: isNum(mk) ? mk : null, color: GI.teamColour(t), href: GI.teamHref(t), mark: { name: GI.teamName(t), abbr: GI.teamAbbr(t), colour: GI.teamInfo(t).colour } });
    const sbRows = Object.keys(po).filter(t => isNum(po[t].p_sb)).map(t => chRow(t, po[t].p_sb, sbM[t]));
    GI.set('ov-sb', sbRows.length ? QK.chances(sbRows, { limit: 12, marketName: 'Market (Kalshi / Polymarket)' }) : GI.muted('The season simulation has not run yet.'));

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

    // playoff race
    const plM = {};
    ((mkts && mkts.futures && mkts.futures.playoffs) || []).forEach(r => { if (r && r.team) plM[r.team] = r.market; });
    GI.CONFERENCES.forEach(c => {
      const list = Object.keys(po).filter(t => GI.teamInfo(t).conference === c && isNum(po[t].p_playoffs)).map(t => chRow(t, po[t].p_playoffs, plM[t]));
      GI.set('ov-' + c.toLowerCase(), list.length ? QK.chances(list, { max: 1, oursName: 'Our playoff chance', marketName: 'Market (Kalshi / Polymarket)' }) : GI.muted('The season simulation has not run yet.'));
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
