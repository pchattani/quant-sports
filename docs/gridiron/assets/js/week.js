/* The Quant Gridiron — a week of games (#/week, #/week/<S>/<w>).
 *
 * Every game of the week as a card (grouped by day), the model v market v line table
 * (GI.mvmTable from hub.js), the week's key matchups, and — once games are final — how the
 * model's favourites and its side against the line did.
 *
 * Reads data/<S>/weeks/<w>.json ({games: [GAME_CARD], matchups}); falls back to the week's games
 * in data/<S>/schedule.json. Refreshes every minute while a game is live. */
(function (GI) {
'use strict';

const esc = GI.esc;
const isNum = GI.isNum;

function strip(S, w) {
  const cur = S === GI.currentSeason() ? GI.currentWeek() : null;
  return '<div class="wk-strip">' + GI.weeksOf(S).map(x =>
    '<a href="' + GI.weekHref(S, x.w) + '" class="' + [x.w === w ? 'on' : '', x.w === cur ? 'cur' : '', x.type !== 'REG' ? 'post' : ''].filter(Boolean).join(' ') + '" title="' + esc(x.label) + '">' +
    esc(x.type === 'REG' ? String(x.w) : x.short) + '</a>').join('') + '</div>';
}

/* Matchups: [{game_id, label, text}] | [string] | {game_id: [..]}. */
function matchupsBlock(m) {
  let list = [];
  if (Array.isArray(m)) list = m;
  else if (m && typeof m === 'object') Object.keys(m).forEach(k => (Array.isArray(m[k]) ? m[k] : [m[k]]).forEach(x => list.push(typeof x === 'string' ? { game_id: k, text: x } : Object.assign({ game_id: k }, x))));
  list = list.filter(Boolean);
  if (!list.length) return '';
  return GI.card('Key matchups', 'where the units meet', '<div class="mu-list">' + list.slice(0, 24).map(x => {
    if (typeof x === 'string') return '<div class="mu-row"><span class="mu-g"></span><span class="mu-t">' + esc(x) + '</span></div>';
    return '<div class="mu-row"><span class="mu-g">' + (x.game_id ? GI.matchupLink(x.game_id) : '') + '</span><span class="mu-t">' + (x.label ? '<b>' + esc(x.label) + ':</b> ' : '') + esc(x.text || x.desc || '') + '</span></div>';
  }).join('') + '</div>');
}

/* How the model did this week: favourites straight up, its side against the closing line, totals. */
function reviewBlock(games) {
  const fin = games.filter(g => GI.isFinal(g) && isNum(g.hs) && isNum(g.as));
  if (!fin.length) return '';
  let su = 0, suN = 0, ats = 0, atsN = 0, atsPush = 0, ou = 0, ouN = 0;
  fin.forEach(g => {
    const m = g.model || {}, ln = g.line || {};
    const margin = Number(g.hs) - Number(g.as);
    if (isNum(m.p_home) && Math.abs(m.p_home - 0.5) > 1e-9 && margin !== 0) { suN++; if ((m.p_home > 0.5) === (margin > 0)) su++; }
    const close = ln.close && isNum(GI.homeLine(ln.close)) ? GI.homeLine(ln.close) : GI.homeLine(ln);
    const lean = GI.lineLean ? GI.lineLean(g, GI.homeLine(m), close) : null;
    if (lean && lean.team && isNum(close)) {
      const cover = margin + close;                       // > 0: home covered
      if (Math.abs(cover) < 1e-9) atsPush++;
      else { atsN++; if ((cover > 0) === (lean.team === g.home)) ats++; }
    }
    const tl = ln.close && isNum(ln.close.total) ? ln.close.total : ln.total;
    if (isNum(m.total) && isNum(tl) && Math.abs(m.total - tl) > 0.05) {
      const pts = Number(g.hs) + Number(g.as);
      if (pts !== Number(tl)) { ouN++; if ((m.total > tl) === (pts > tl)) ou++; }
    }
  });
  const t = (k, n, label, sub) => GI.statTile(label, n ? k + '–' + (n - k) : '—', n ? GI.pct(k / n, 0) + (sub || '') : 'no games yet');
  return GI.card('How the model did', fin.length + ' final' + (fin.length === 1 ? '' : 's') + ' · small samples: one week says little',
    '<div class="kpi-grid three pad">' + t(su, suN, 'Favourites, straight up') + t(ats, atsN, 'Side against the line', atsPush ? ' · ' + atsPush + ' push' + (atsPush > 1 ? 'es' : '') : '') + t(ou, ouN, 'Over/under against the line') + '</div>');
}

GI.route('week', function (el, params) {
  const S = Number(params.season);
  const w = isNum(params.week) ? Number(params.week) : (S === GI.currentSeason() ? GI.currentWeek() : 1);
  return GI.loadWeek(w, S).then(d => {
    if (GI.ok(d) && (d.games || []).length) return d;
    return GI.loadYear('schedule.json', S).then(sch => {
      if (!GI.ok(sch)) return d && d.ok === false ? d : sch;
      return { ok: true, games: (sch.games || []).filter(g => Number(g.week) === w), fromSchedule: true };
    });
  }).then(d => {
    if (!el.isConnected) return;
    const label = GI.weekLabel(w, S);
    const head = GI.pageHead(S + ' ' + label, GI.gtypeLabel(GI.weekType(w, S)), GI.weekNav(S, w));
    if (!GI.ok(d)) { el.innerHTML = head + GI.card('', '', strip(S, w)) + GI.notBuilt('The ' + S + ' schedule', d); return; }
    const games = (d.games || []).slice().sort((a, b) => String(a.kickoff).localeCompare(String(b.kickoff)) || String(a.game_id).localeCompare(String(b.game_id)));
    const days = [];
    games.forEach(g => { const day = GI.localDay(g.kickoff) || 'TBD'; let x = days.find(z => z.day === day); if (!x) { x = { day: day, games: [] }; days.push(x); } x.games.push(g); });
    const span = days.length ? GI.fmtDate(days[0].day, { year: false }) + (days.length > 1 ? ' – ' + GI.fmtDate(days[days.length - 1].day, { year: false }) : '') : '';
    const live = games.filter(GI.isLive);
    el.innerHTML = GI.pageHead(S + ' ' + label, [GI.gtypeLabel(GI.weekType(w, S)), span, games.length + ' game' + (games.length === 1 ? '' : 's')].filter(Boolean).join(' · '), GI.weekNav(S, w)) +
      GI.card('', '', strip(S, w) + (games.length ? days.map(x => '<div class="day-head">' + esc(x.day === 'TBD' ? 'Kickoff to be set' : GI.fmtDate(x.day)) + '</div><div class="gc-grid">' +
        x.games.map(g => GI.gameCard(g)).join('') + '</div>').join('') : GI.muted('No games this week' + (GI.weekType(w, S) === 'REG' ? ' (bye week for everyone?).' : ': the round is not set yet.')))) +
      (games.length ? GI.card('Model v market v line', label + ' · our price, the de-vigged market and the spread and total',
        GI.mvmTable(games) + '<div class="chart-note">Spreads are shown for the favourite. Final games show the closing line. For information only: not betting advice.</div>') : '') +
      reviewBlock(games) + matchupsBlock(d.matchups);
    GI.sortable(el);
    GI.setMeta(live.length ? '<span class="live-dot"></span> ' + live.length + ' live' : '');
    if (live.length) GI.liveRefresh([GI.weekPath(w, S), GI.ypath('schedule.json', S)], 60000);
  });
});

})(window.GI);
