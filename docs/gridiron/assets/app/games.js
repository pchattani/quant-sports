/* The Quant Gridiron — Games (#/games/<S>/<w>): a week of games (old #/week).
 * Week strip, every game as a card grouped by day, the model v market v line table, the model's
 * picks against the spread as a chart, and once games are final how the model did.
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

/* Model v market v line, one row per game. */
function mvmTable(cards) {
  const list = (cards || []).filter(Boolean);
  if (!list.length) return GI.muted('No games to price.');
  const cols = [
    { label: 'Game', sortable: false }, { label: 'Status' },
    { label: 'Model', align: 'right', title: 'Our pre-game win probability for the side we favour (live: our live win probability)' },
    { label: 'Market', align: 'right', title: 'De-vigged prediction-market probability for the same side' },
    { label: 'Gap', align: 'right', title: 'Model minus market, percentage points: a disagreement, not a recommendation' },
    { label: 'Model line', align: 'right', title: 'Our fair spread' }, { label: 'Line', align: 'right', title: 'The current (or closing) spread' },
    { label: 'Line gap', align: 'right', title: 'Where our fair line differs from the market line, in points' },
    { label: 'Model total', align: 'right' }, { label: 'O/U', align: 'right' }, { label: 'Total lean', align: 'right', title: 'Model total minus the line' }
  ];
  const rows = list.map(g => {
    const m = g.model || {}, mk = g.market || {}, ln = g.line || {};
    const st = GI.gameState(g), live = st === 'live' || st === 'half', fin = st === 'final';
    const pH = live && isNum(g.wp_home) ? Number(g.wp_home) : (isNum(m.p_home) ? Number(m.p_home) : null);
    const fav = pH === null ? 'home' : (pH >= 0.5 ? 'home' : 'away');
    const mp = pH === null ? null : (fav === 'home' ? pH : 1 - pH);
    const kp = isNum(mk.p_home) ? (fav === 'home' ? Number(mk.p_home) : 1 - Number(mk.p_home)) : null;
    const mLine = GI.homeLine(m), lLine = GI.homeLine(ln), oLine = ln.open ? GI.homeLine(ln.open) : null;
    const lean = GI.lineLean(g, mLine, lLine);
    const status = fin ? '<b>' + esc(GI.teamAbbr(g.away)) + ' ' + esc(g.as) + ', ' + esc(GI.teamAbbr(g.home)) + ' ' + esc(g.hs) + '</b>' + (GI.isOT(g) ? ' OT' : '')
      : live ? '<span class="qk-badge live">' + esc(GI.clockText(g.qtr, g.clock) || 'Live') + '</span>' : esc(GI.fmtDate(g.kickoff, { year: false })) + ' ' + esc(GI.fmtTime(g.kickoff));
    const tot = isNum(m.total) && isNum(ln.total) ? Number(m.total) - Number(ln.total) : null;
    return { _href: GI.gameHref(g.game_id), cells: [
      { html: GI.matchupLink(g.game_id, g.away, g.home), v: g.game_id },
      { html: status, v: g.kickoff || '' },
      { html: mp === null ? '—' : esc(GI.teamAbbr(g[fav])) + ' <b>' + GI.pct(mp, 0) + '</b>', v: mp },
      { html: kp === null ? '—' : GI.pct(kp, 0), v: kp },
      { html: fin || live ? '<span class="qk-muted">—</span>' : GI.gapHTML(mp, kp, 0), v: mp !== null && kp !== null ? mp - kp : null },
      { html: esc(GI.spreadText(g.home, g.away, mLine)), v: mLine },
      { html: esc(GI.spreadText(g.home, g.away, lLine)) + (isNum(oLine) && isNum(lLine) && oLine !== lLine ? '<span class="gi-sub-line">open ' + esc(GI.spreadText(g.home, g.away, oLine)) + '</span>' : ''), v: lLine },
      { html: lean ? (lean.team ? esc(GI.teamAbbr(lean.team)) + ' ' + GI.num(lean.pts, 1) : '—') : '—', v: lean ? lean.pts : null },
      { html: GI.num(m.total, 1), v: m.total },
      { html: GI.num(ln.total, 1), v: ln.total },
      { html: tot === null || Math.abs(tot) < 0.05 ? '—' : (tot > 0 ? 'Over ' : 'Under ') + GI.num(Math.abs(tot), 1), v: tot }
    ] };
  });
  return GI.tableHTML(cols, rows, { sticky: true });
}
GI.mvmTable = mvmTable;

/* How the model did this week: favourites straight up, its side against the closing line, totals. */
function review(games) {
  const fin = games.filter(g => GI.isFinal(g) && isNum(g.hs) && isNum(g.as));
  if (!fin.length) return '';
  let su = 0, suN = 0, ats = 0, atsN = 0, push = 0, ou = 0, ouN = 0;
  fin.forEach(g => {
    const m = g.model || {}, ln = g.line || {};
    const margin = Number(g.hs) - Number(g.as);
    if (isNum(m.p_home) && Math.abs(m.p_home - 0.5) > 1e-9 && margin !== 0) { suN++; if ((m.p_home > 0.5) === (margin > 0)) su++; }
    const close = ln.close && isNum(GI.homeLine(ln.close)) ? GI.homeLine(ln.close) : GI.homeLine(ln);
    const lean = GI.lineLean(g, GI.homeLine(m), close);
    if (lean && lean.team && isNum(close)) {
      const cover = margin + close;
      if (Math.abs(cover) < 1e-9) push++;
      else { atsN++; if ((cover > 0) === (lean.team === g.home)) ats++; }
    }
    const tl = ln.close && isNum(ln.close.total) ? ln.close.total : ln.total;
    if (isNum(m.total) && isNum(tl) && Math.abs(m.total - tl) > 0.05) { const pts = Number(g.hs) + Number(g.as); if (pts !== Number(tl)) { ouN++; if ((m.total > tl) === (pts > tl)) ou++; } }
  });
  const t = (k, n, label, sub) => GI.kpi(label, n ? k + '–' + (n - k) : '—', n ? GI.pct(k / n, 0) + (sub || '') : 'no games yet');
  return GI.card('How the model did', fin.length + ' final' + (fin.length === 1 ? '' : 's') + ' · one week is a small sample',
    GI.kpis([t(su, suN, 'Favourites, straight up'), t(ats, atsN, 'Side against the line', push ? ' · ' + push + ' push' : ''), t(ou, ouN, 'Over/under v the line')], 'gi-kpis-3'));
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
    const priced = games.filter(g => GI.isPre(g) && isNum(GI.homeLine(g.model || {})) && isNum(GI.homeLine(g.line || {})));
    el.innerHTML = GI.pageHead('Games · ' + S + ' · ' + GI.gtypeLabel(GI.weekType(w, S)), label, [span, games.length + ' game' + (games.length === 1 ? '' : 's'), live.length ? live.length + ' live' : ''].filter(Boolean).join(' · '), GI.weekNav(S, w)) +
      strip(S, w) +
      (games.length ? days.map(x => '<div class="gi-day">' + esc(x.day === 'TBD' ? 'Kickoff to be set' : GI.fmtDate(x.day)) + '</div><div class="qk-auto gi-games" style="--min:290px">' + x.games.map(g => GI.gameCard(g)).join('') + '</div>').join('')
        : QK.empty('No games this week', GI.weekType(w, S) === 'REG' ? 'A bye week for everyone?' : 'The round is not set yet.')) +
      (priced.length ? GI.card('Model line v market line', 'points: positive = the model likes the home side more than the line does', GI.chartBox('gw-lines', Math.max(220, priced.length * 30 + 30), 'Model spread against the line')) : '') +
      (games.length ? GI.card('Model v market v line', label + ' · our price, the de-vigged market, the spread and the total', mvmTable(games) +
        '<p class="gi-cap">Spreads are shown for the favourite. Final games show the closing line. A gap is a disagreement, not a recommendation: the model trails the closing line in the <a href="#/calibration">backtest</a>. Not betting advice.</p>') : '') +
      review(games);
    GI.sortable(el);
    if (priced.length) {
      const rows = priced.map(g => ({ label: GI.teamAbbr(g.away) + ' @ ' + GI.teamAbbr(g.home), v: GI.homeLine(g.line) - GI.homeLine(g.model), href: GI.gameHref(g.game_id) }));
      GI.ch.bar('gw-lines', { cats: rows.map(r => r.label), series: [{ name: 'Model v line (pts, home)', data: rows.map(r => Math.round(r.v * 10) / 10) }], horizontal: true, diverging: true, labels: true, hrefs: rows.map(r => r.href), fmt: v => GI.signed(v, 1), labelWidth: 90 });
    }
    if (live.length) GI.liveRefresh([GI.weekPath(w, S), GI.ypath('schedule.json', S)], 60000);
  });
});

})(window.GI);
