/* The Quant Rink — a day of games (#/games, #/games/<YYYY-MM-DD>).
 *
 * A strip of game days, every game of the day as a card, the model v market v line table
 * (RK.mvmTable from hub.js) and — once games are final — how the model's favourites, its side of
 * the puck line and its totals did.
 *
 * Reads data/<S>/schedule.json ({games: [GAME_CARD]}) for the season of the day (a date from
 * September on belongs to that season); today's cards are taken from index.json when they are fresher.
 * With no date: today when there are games, else the next day with games, else the season's last. */
(function (RK) {
'use strict';

const esc = RK.esc;
const isNum = RK.isNum;

function dayOf(g) { return g.date || RK.localDay(g.start) || ''; }

function strip(days, day) {
  if (!days.length) return '';
  const i = Math.max(0, days.indexOf(day));
  const lo = Math.max(0, i - 6), hi = Math.min(days.length, lo + 13);
  const today = RK.todayISO();
  return '<div class="day-strip">' + days.slice(lo, hi).map(d => {
    const dt = RK.parseDate(d);
    return '<a href="' + RK.gamesHref(d) + '" class="' + [d === day ? 'on' : '', d === today ? 'cur' : ''].filter(Boolean).join(' ') + '">' +
      '<span class="ds-w">' + esc(dt ? ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][dt.getUTCDay()] : '') + '</span><span class="ds-d">' + esc(RK.fmtDate(d, { year: false, weekday: false })) + '</span></a>';
  }).join('') + '</div>';
}

/* How the model did on the day: favourites straight up, the puck-line side, totals against the line. */
function reviewBlock(games) {
  const fin = games.filter(g => RK.isFinal(g) && isNum(g.hs) && isNum(g.as));
  if (!fin.length) return '';
  let su = 0, suN = 0, pl = 0, plN = 0, ou = 0, ouN = 0, ouPush = 0, brier = 0, bN = 0;
  fin.forEach(g => {
    const m = g.model || {};
    const ln = RK.lineNow(g);
    const margin = Number(g.hs) - Number(g.as);
    if (isNum(m.p_home) && Math.abs(m.p_home - 0.5) > 1e-9 && margin !== 0) {
      suN++; if ((m.p_home > 0.5) === (margin > 0)) su++;
      brier += Math.pow(Number(m.p_home) - (margin > 0 ? 1 : 0), 2); bN++;
    }
    const pc = RK.puckCover(g, m, ln);
    if (pc && isNum(pc.p) && Math.abs(pc.p - 0.5) > 1e-9) {
      // the model takes the favourite's -1.5 when it gives it more than 50%, else the dog's +1.5
      const favMargin = String(pc.team) === String(g.home) ? margin : -margin;
      const favCovers = favMargin + pc.line > 0;
      plN++; if ((pc.p > 0.5) === favCovers) pl++;
    }
    if (isNum(m.total) && isNum(ln.total) && Math.abs(m.total - ln.total) > 0.05) {
      const goals = Number(g.hs) + Number(g.as);
      if (goals === Number(ln.total)) ouPush++;
      else { ouN++; if ((m.total > ln.total) === (goals > ln.total)) ou++; }
    }
  });
  const t = (k, n, label, sub) => RK.statTile(label, n ? k + '–' + (n - k) : '—', n ? RK.pct(k / n, 0) + (sub || '') : 'no games yet');
  return RK.card('How the model did', fin.length + ' final' + (fin.length === 1 ? '' : 's') + ' · one day says little: see <a href="#/calibration">calibration</a> for the long run',
    '<div class="kpi-grid four pad">' + t(su, suN, 'Favourites, straight up') + t(pl, plN, 'Puck-line side') + t(ou, ouN, 'Totals against the line', ouPush ? ' · ' + ouPush + ' push' + (ouPush > 1 ? 'es' : '') : '') +
    RK.statTile('Brier score', bN ? RK.num(brier / bN, 3) : '—', bN ? 'win probability; 0.25 = a coin flip' : '') + '</div>');
}

function pickDay(days, S) {
  const today = RK.todayISO();
  if (S === RK.currentSeason()) {
    if (days.indexOf(today) >= 0) return today;
    const idx = RK.index() || {};
    const t0 = (idx.today || [])[0];
    if (t0 && days.indexOf(dayOf(t0)) >= 0) return dayOf(t0);
    const nxt = days.find(d => d >= today);
    if (nxt) return nxt;
  }
  return days[days.length - 1];
}

RK.route('games', function (el, params) {
  const S = params.date ? (RK.seasonOfDate(params.date) || params.season) : params.season;
  return RK.loadYear('schedule.json', S).then(sch => {
    if (!el.isConnected) return;
    const idx = RK.index() || {};
    let games = RK.ok(sch) ? (sch.games || []).filter(Boolean) : [];
    // fresher cards from index.json (today, live, recent, upcoming) replace the schedule's
    const fresh = {};
    ['today', 'live', 'recent', 'upcoming'].forEach(k => (idx[k] || []).forEach(c => { if (c && c.game_id) fresh[c.game_id] = c; }));
    if (S === RK.currentSeason()) {
      games = games.map(g => fresh[g.game_id] || g);
      Object.keys(fresh).forEach(id => { if (!games.some(g => g.game_id === id)) games.push(fresh[id]); });
    }
    const days = [];
    games.forEach(g => { const d = dayOf(g); if (d && days.indexOf(d) < 0) days.push(d); });
    days.sort();
    const day = params.date || (days.length ? pickDay(days, S) : RK.todayISO());
    const list = games.filter(g => dayOf(g) === day).sort((a, b) => String(a.start).localeCompare(String(b.start)) || String(a.game_id).localeCompare(String(b.game_id)));
    const di = days.indexOf(day);
    const prev = di > 0 ? days[di - 1] : (di < 0 ? days.filter(d => d < day).pop() : null);
    const next = di >= 0 && di + 1 < days.length ? days[di + 1] : (di < 0 ? days.find(d => d > day) : null);
    const nav = (prev ? '<a href="' + RK.gamesHref(prev) + '">← ' + esc(RK.fmtDate(prev, { year: false })) + '</a>' : '<span class="disabled">←</span>') +
      (next ? '<a href="' + RK.gamesHref(next) + '">' + esc(RK.fmtDate(next, { year: false })) + ' →</a>' : '<span class="disabled">→</span>') +
      '<label class="date-jump"><input type="date" id="gd-jump" value="' + esc(day) + '" aria-label="Go to a date"></label>';
    const live = list.filter(RK.isLive);
    const pg = list.map(g => RK.parseGameId(g.game_id)).filter(Boolean);
    const kind = pg.length && pg.every(x => x.playoff) ? 'Playoffs' : (pg.length && pg.every(x => x.type === '01') ? 'Preseason' : '');
    document.title = 'Games · ' + RK.fmtDate(day, { year: false }) + ' · ' + RK.SITE;
    const head = RK.pageHead(RK.fmtDate(day), [RK.seasonLabel(S), kind, list.length ? list.length + ' game' + (list.length === 1 ? '' : 's') : ''].filter(Boolean).join(' · '), nav);
    if (!RK.ok(sch) && !list.length) {
      el.innerHTML = head + RK.notBuilt('The ' + RK.seasonLabel(S) + ' schedule', sch);
    } else {
      el.innerHTML = head + RK.card('', '', strip(days, day) + (list.length ? '<div class="gc-grid">' + list.map(g => RK.gameCard(g, { goalies: RK.isPre(g) })).join('') + '</div>'
        : RK.muted('No games on ' + esc(RK.fmtDate(day)) + '.' + (next ? ' Next: <a href="' + RK.gamesHref(next) + '">' + esc(RK.fmtDate(next, { year: false })) + '</a>.' : '')))) +
        (list.length ? RK.card('Model v market v line', esc(RK.fmtDate(day, { year: false })) + ' · our price, the de-vigged market, the moneyline, puck line and total',
          RK.mvmTable(list) + '<div class="chart-note">Final games show the closing line. Win probabilities include overtime and the shootout. For information only: not betting advice.</div>') : '') +
        reviewBlock(list);
    }
    const jump = el.querySelector('#gd-jump');
    if (jump) jump.addEventListener('change', () => { if (/^\d{4}-\d\d-\d\d$/.test(jump.value)) RK.go(RK.gamesHref(jump.value)); });
    RK.sortable(el);
    RK.setMeta(live.length ? '<span class="live-dot"></span> ' + live.length + ' live' : '');
    if (live.length) RK.liveRefresh([RK.ypath('schedule.json', S)], 60000);
  });
});

})(window.RK);
