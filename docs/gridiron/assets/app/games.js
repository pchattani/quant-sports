/* The Quant Gridiron — Games (#/games/<S>/<w>): a week of games (old #/week), on Design System 2.0.
 * Week strip, every game as a v2 game card grouped by day, our chance for every home side (the market a grey ring),
 * our forecast game by game (projected score, margin, points; the market a reference column), and once games are
 * final how our forecast did.
 * Reads <S>/weeks/<w>.json, falling back to <S>/schedule.json. Refreshes every minute while a game is live. */
(function (GI) {
'use strict';

const esc = GI.esc, isNum = GI.isNum;

function strip(S, w) {
  const cur = S === GI.currentSeason() ? GI.currentWeek() : null;
  return '<nav class="gi-weekstrip" aria-label="Weeks">' + GI.weeksOf(S).map(x =>
    '<a href="' + GI.weekHref(S, x.w) + '" class="' + [x.w === w ? 'on' : '', x.w === cur ? 'cur' : '', x.type !== 'REG' ? 'post' : ''].filter(Boolean).join(' ') + '" title="' + esc(x.label) + '"' + (x.w === w ? ' aria-current="page"' : '') + '>' +
    esc(x.type === 'REG' ? String(x.w) : x.short) + '</a>').join('') + '</nav>';
}

/* Our forecast for every game, one row per game: our win chance for the side we favour, the projected score, margin and
 * points, and the market's number as a quiet reference column. */
function forecastTable(cards) {
  const list = (cards || []).filter(Boolean);
  if (!list.length) return GI.muted('No games this week.');
  const cols = [
    { label: 'Game', sortable: false }, { label: 'Status' },
    { label: 'Our chance', align: 'right', title: 'Our pre-game win chance for the side we favour (live: our live win chance)' },
    { label: 'Projected score', align: 'right', title: 'The average score of our game simulations' },
    { label: 'Margin', align: 'right', title: 'Our projected winning margin, points' },
    { label: 'Points', align: 'right', title: 'Total points we expect' },
    { label: 'Market', align: 'right', title: 'The prediction-market probability (Kalshi / Polymarket) for the same side, shown as a reference' }
  ];
  const rows = list.map(g => {
    const m = g.model || {}, mk = g.market || {};
    const st = GI.gameState(g), live = st === 'live' || st === 'half', fin = st === 'final';
    const pH = live && isNum(g.wp_home) ? Number(g.wp_home) : (isNum(m.p_home) ? Number(m.p_home) : null);
    const fav = pH === null ? 'home' : (pH >= 0.5 ? 'home' : 'away');
    const mp = pH === null ? null : (fav === 'home' ? pH : 1 - pH);
    const kp = isNum(mk.p_home) && !fin && !live ? (fav === 'home' ? Number(mk.p_home) : 1 - Number(mk.p_home)) : null;
    const mg = GI.homeLine(m);
    const status = fin ? '<b>' + esc(GI.teamAbbr(g.away)) + ' ' + esc(g.as) + ', ' + esc(GI.teamAbbr(g.home)) + ' ' + esc(g.hs) + '</b>' + (GI.isOT(g) ? ' OT' : '')
      : live ? '<span class="qk-badge live">' + esc(GI.clockText(g.qtr, g.clock) || 'Live') + '</span>' : esc(GI.fmtDate(g.kickoff, { year: false })) + ' ' + esc(GI.fmtTime(g.kickoff));
    return { _href: GI.gameHref(g.game_id), cells: [
      { html: GI.matchupLink(g.game_id, g.away, g.home), v: g.game_id },
      { html: status, v: g.kickoff || '' },
      { html: mp === null ? '—' : esc(GI.teamAbbr(g[fav])) + ' <b class="gi-ours">' + GI.pct(mp, 0) + '</b>', v: mp },
      { html: isNum(m.home_pts) && isNum(m.away_pts) ? esc(GI.teamAbbr(g.away)) + ' ' + GI.num(m.away_pts, 0) + '–' + GI.num(m.home_pts, 0) + ' ' + esc(GI.teamAbbr(g.home)) : '—', v: isNum(m.home_pts) ? m.home_pts - m.away_pts : null },
      { html: isNum(mg) ? (Math.abs(mg) < 0.5 ? 'even' : esc(GI.teamAbbr(mg < 0 ? g.home : g.away)) + ' by ' + GI.num(Math.abs(mg), 1)) : '—', v: isNum(mg) ? Math.abs(mg) : null },
      { html: GI.num(m.total, 1), v: m.total },
      { html: kp === null ? '<span class="qk-muted">—</span>' : '<span class="qk-muted">' + GI.pct(kp, 0) + '</span>', v: kp }
    ] };
  });
  return GI.tableHTML(cols, rows, { sticky: true });
}
GI.forecastTable = forecastTable;

/* How our forecast did this week: favourites straight up, and how far the projected margin and points were from the result. */
function review(games) {
  const fin = games.filter(g => GI.isFinal(g) && isNum(g.hs) && isNum(g.as));
  if (!fin.length) return '';
  let su = 0, suN = 0, mAbs = 0, mN = 0, tAbs = 0, tN = 0;
  fin.forEach(g => {
    const m = g.model || {};
    const margin = Number(g.hs) - Number(g.as);
    if (isNum(m.p_home) && Math.abs(m.p_home - 0.5) > 1e-9 && margin !== 0) { suN++; if ((m.p_home > 0.5) === (margin > 0)) su++; }
    const mg = GI.homeLine(m);
    if (isNum(mg)) { mAbs += Math.abs(margin + mg); mN++; }
    if (isNum(m.total)) { tAbs += Math.abs(Number(g.hs) + Number(g.as) - m.total); tN++; }
  });
  return GI.card('How our forecast did', fin.length + ' final' + (fin.length === 1 ? '' : 's') + ' · one week is a small sample; the season record is on the <a href="#/calibration">Model page</a>',
    GI.kpis([GI.kpi('Favourites, straight up', suN ? su + '–' + (suN - su) : '—', suN ? GI.pct(su / suN, 0) + ' of games with a favourite' : 'no games yet', { signal: true }),
      GI.kpi('Margin miss', mN ? GI.num(mAbs / mN, 1) : '—', mN ? 'points, average distance from our projected margin' : '', { unit: mN ? 'pts' : '' }),
      GI.kpi('Points miss', tN ? GI.num(tAbs / tN, 1) : '—', tN ? 'points, average distance from our expected total' : '', { unit: tN ? 'pts' : '' })]));
}

GI.route('games', function (el, params) {
  const S = Number(params.season);
  const w = isNum(params.week) ? Number(params.week) : (S === GI.currentSeason() ? GI.currentWeek() : 1);
  /* future playoff rounds of the current season have no week file yet: go straight to the schedule */
  const noWeek = S === GI.currentSeason() && w > GI.regWeeks(S) && w > GI.currentWeek();
  return (noWeek ? Promise.resolve(null) : GI.loadWeek(w, S)).then(d => {
    if (GI.ok(d) && (d.games || []).length) return d;
    return GI.loadYear('schedule.json', S).then(sch => {
      if (!GI.ok(sch)) return d && d.ok === false ? d : sch;
      return { ok: true, games: (sch.games || []).filter(g => Number(g.week) === w), fromSchedule: true };
    });
  }).then(d => {
    if (!el.isConnected) return;
    const label = GI.weekLabel(w, S);
    if (!GI.ok(d)) { el.innerHTML = GI.pageHead('Games · ' + S, label, GI.gtypeLabel(GI.weekType(w, S)), GI.weekNav(S, w)) + strip(S, w) + GI.notBuilt('The ' + S + ' schedule', d); return; }
    const games = (d.games || []).slice().sort((a, b) => String(a.kickoff).localeCompare(String(b.kickoff)) || String(a.game_id).localeCompare(String(b.game_id)));
    const days = [];
    games.forEach(g => { const day = GI.localDay(g.kickoff) || 'TBD'; let x = days.find(z => z.day === day); if (!x) { x = { day: day, games: [] }; days.push(x); } x.games.push(g); });
    const span = days.length ? GI.fmtDate(days[0].day, { year: false }) + (days.length > 1 ? ' – ' + GI.fmtDate(days[days.length - 1].day, { year: false }) : '') : '';
    const live = games.filter(GI.isLive);
    const pre = games.filter(g => GI.isPre(g) && isNum((g.model || {}).p_home));
    el.innerHTML = GI.pageHead('Games · ' + S + ' · ' + GI.gtypeLabel(GI.weekType(w, S)), label, [span, games.length + ' game' + (games.length === 1 ? '' : 's'), live.length ? live.length + ' live' : ''].filter(Boolean).join(' · '), GI.weekNav(S, w)) +
      strip(S, w) +
      (games.length ? days.map(x => '<div class="gi-day">' + esc(x.day === 'TBD' ? 'Kickoff to be set' : GI.fmtDate(x.day)) + '</div><div class="qk-auto gi-games" style="--min:290px">' + x.games.map(g => GI.gameCard(g)).join('') + '</div>').join('')
        : QK.empty('No games this week', GI.weekType(w, S) === 'REG' ? 'A bye week for everyone?' : 'The round is not set yet.')) +
      (pre.length ? '<section class="qk-section">' + GI.card('Our chance for every home side', 'Violet: our win chance. Grey ring: the market (Kalshi / Polymarket), for reference', GI.chartBox('gw-chance', Math.max(220, pre.length * 34 + 50), 'Our home win chance, with the market for reference')) + '</section>' : '') +
      (games.length ? GI.card('Our forecast, game by game', label + ' · our win chance, the projected score, margin and points; the market column is a reference', forecastTable(games) +
        '<p class="gi-cap">Projections are the average of our game simulations. How the game model scores over many seasons is on the <a href="#/calibration">Model page</a>.</p>') : '') +
      review(games);
    GI.sortable(el);
    if (pre.length) {
      const withMk = pre.filter(g => isNum((g.market || {}).p_home));
      if (withMk.length) GI.ch.dumbbell('gw-chance', { rows: pre.map(g => ({ label: GI.teamAbbr(g.away) + ' @ ' + GI.teamAbbr(g.home), a: g.model.p_home, b: isNum((g.market || {}).p_home) ? g.market.p_home : g.model.p_home, href: GI.gameHref(g.game_id), sub: GI.fmtDate(g.kickoff, { year: false }) + ' ' + GI.fmtTime(g.kickoff) + (isNum((g.market || {}).p_home) ? '' : ' · no market') })), aName: 'Our chance', bName: 'Market', labelWidth: 90, valName: 'Home win chance', min: 0, max: 1 });
      else GI.ch.probBars('gw-chance', pre.map(g => ({ label: GI.teamAbbr(g.away) + ' @ ' + GI.teamAbbr(g.home), p: g.model.p_home, colour: GI.teamColour(g.home), href: GI.gameHref(g.game_id) })), { top: 20, labelWidth: 90, valName: 'Home win chance' });
    }
    if (live.length) GI.liveRefresh([GI.weekPath(w, S), GI.ypath('schedule.json', S)], 60000);
  });
});

})(window.GI);
