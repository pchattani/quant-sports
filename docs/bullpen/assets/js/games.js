/* The Quant Bullpen — games of a day (#/<L>/games[/<date>]).
 *
 *   a date picker (input, previous/next game day, a strip of nearby game days);
 *   the day's games as cards (model · market · DraftKings line · live win probability) or as a
 *   table (model against market against the line, the result, and whether the model's
 *   favourite won); a one-line summary of the day for the model.
 *
 * Reads <L>/<S>/schedule.json ({"games": [GAME_CARD]}) and, for today, the fresher cards in index.json. */
(function (BP) {
'use strict';

const esc = BP.esc;
const isNum = BP.isNum;
let VIEW = 'cards';
try { const v = window.localStorage.getItem('qb-games-view'); if (v === 'cards' || v === 'table') VIEW = v; } catch (e) { /* private mode */ }

function gamesOf(d) {
  if (!d) return [];
  if (Array.isArray(d)) return d;
  if (Array.isArray(d.games)) return d.games;
  if (d.games && typeof d.games === 'object') return Object.keys(d.games).map(k => d.games[k]);
  return [];
}
function pickDate(dates, want, isCurrent) {
  if (!dates.length) return want || BP.todayISO();
  if (want && dates.indexOf(want) >= 0) return want;
  const ref = want || (isCurrent ? BP.todayISO() : dates[dates.length - 1]);
  if (dates.indexOf(ref) >= 0) return ref;
  const after = dates.find(d => d >= ref);
  if (want) return after || dates[dates.length - 1];
  // with no date asked for: the next game day if it is close, else the latest one played
  const before = dates.filter(d => d <= ref).pop();
  return after && (!before || BP.parseDate(after) - BP.parseDate(ref) <= 3 * 86400000) ? after : (before || after);
}

function summary(list) {
  const fin = list.filter(c => BP.isFinal(c) && isNum((c.model || {}).p_home) && isNum(c.hs) && isNum(c.as) && c.hs !== c.as);
  if (!fin.length) return '';
  let right = 0, ll = 0, mright = 0, mn = 0;
  fin.forEach(c => {
    const p = c.model.p_home, homeWon = c.hs > c.as;
    if ((p >= 0.5) === homeWon) right++;
    ll += -Math.log(Math.max(1e-6, homeWon ? p : 1 - p));
    const m = (c.market || {}).p_home;
    if (isNum(m)) { mn++; if ((m >= 0.5) === homeWon) mright++; }
  });
  return 'Model favourites won ' + right + ' of ' + fin.length + ' (log loss ' + BP.num(ll / fin.length, 3) + ')' +
    (mn ? ' · market favourites ' + mright + ' of ' + mn : '') + '.';
}

function tableView(list, L, S) {
  const rows = list.map(c => {
    const m = c.model || {}, k = c.market || {}, ln = c.line || {};
    const ml = Array.isArray(ln.ml) ? ln.ml : null;
    const pL = ml ? BP.devigAm(ml) : null;
    const fin = BP.isFinal(c);
    const homeWon = fin && c.hs > c.as;
    const fav = isNum(m.p_home) ? (m.p_home >= 0.5 ? 'home' : 'away') : null;
    const hit = fin && fav ? ((fav === 'home') === homeWon) : null;
    const tot = ln.total && typeof ln.total === 'object' ? ln.total.line : ln.total;
    return { _href: BP.gameHref(c.gpk, L, S), cells: [
      { v: c.start || c.date, html: BP.statusChip(c), cls: 'hide-sm' },
      { v: BP.teamAbbr(c.away) + ' @ ' + BP.teamAbbr(c.home), html: BP.teamLink(c.away, { abbr: true, level: L }) + ' <span class="muted-inline">@</span> ' + BP.teamLink(c.home, { abbr: true, level: L }) +
        (c.series ? '<div class="sub-line">' + esc(BP.seriesText(c.series, true)) + '</div>' : '') },
      { v: fin || BP.isLive(c) ? (c.as + '-' + c.hs) : '', html: fin || BP.isLive(c) ? '<b>' + esc(c.as) + '-' + esc(c.hs) + '</b>' + (BP.isLive(c) ? ' <span class="live-dot"></span>' : '') : '<span class="muted-inline">—</span>' },
      { v: m.p_home, html: isNum(m.p_home) ? BP.pct(m.p_home, 0) : '—', align: 'right', title: 'Model home win probability' },
      { v: k.p_home, html: isNum(k.p_home) ? BP.pct(k.p_home, 0) + ' <span class="rk-sub">' + BP.edgeHTML(m.p_home, k.p_home, 0) + '</span>' : '—', align: 'right' },
      { v: pL, html: ml ? BP.fmtOdds(ml[0]) + ' <span class="muted-inline">(' + BP.pct(pL, 0) + ')</span>' : '—', align: 'right', cls: 'hide-sm' },
      { v: m.total, html: isNum(m.total) ? BP.num(m.total, 1) + (isNum(tot) ? ' <span class="muted-inline">v ' + BP.num(tot, 1) + '</span>' : '') : '—', align: 'right', cls: 'hide-sm' },
      { v: hit === null ? '' : (hit ? 1 : 0), html: hit === null ? '' : (hit ? '<span class="edge-pos">✓</span>' : '<span class="edge-neg">✗</span>'), align: 'center', title: "Did the model's favourite win?" }
    ] };
  });
  return BP.tableHTML([{ label: 'Status', cls: 'hide-sm' }, { label: 'Game' }, { label: 'Score' }, { label: 'Model home', align: 'right' },
    { label: 'Market', align: 'right', title: 'De-vigged market home probability and the gap to the model (points)' },
    { label: 'DK home', align: 'right', cls: 'hide-sm', title: 'DraftKings moneyline for the home team (de-vigged probability)' },
    { label: 'Total', align: 'right', cls: 'hide-sm', title: 'Model expected total runs v the line' }, { label: 'Fav', align: 'center' }], rows, { compact: true });
}

function render(el, params) {
  const L = params.level, S = params.season;
  const isCurrent = S === BP.currentSeason(L);
  el.innerHTML = BP.pageHead(BP.levelName(L) + ' games', 'Every game priced by the model against the market and the DraftKings line', '') + '<div id="gm-body"><div class="muted">Loading…</div></div>';
  return BP.loadYear('schedule.json', L, S).then(d => {
    if (!el.isConnected) return;
    const body = document.getElementById('gm-body');
    let list = gamesOf(d);
    // today's cards in index.json are fresher (live scores, win probability)
    const idx = BP.index() || {};
    const src = L === 'mlb' ? idx : BP.levelInfo(L);
    if (isCurrent) {
      const fresh = {};
      [].concat(src.today || [], src.recent || [], src.upcoming || []).forEach(c => { if (c && c.gpk) fresh[c.gpk] = c; });
      list = list.map(c => fresh[c.gpk] || c);
      Object.keys(fresh).forEach(k => { if (!list.find(c => c.gpk === k)) list.push(fresh[k]); });
    }
    if (!list.length) { body.innerHTML = BP.card('Games', '', BP.notBuilt('The ' + S + ' schedule', d)); return; }
    const byDate = {};
    list.forEach(c => { if (c && c.date) (byDate[c.date] = byDate[c.date] || []).push(c); });
    const dates = Object.keys(byDate).sort();
    const day = pickDate(dates, params.date, isCurrent);
    const i = dates.indexOf(day);
    const prev = i > 0 ? dates[i - 1] : null, next = i >= 0 && i + 1 < dates.length ? dates[i + 1] : null;
    const strip = dates.slice(Math.max(0, i - 3), Math.min(dates.length, i + 4));
    const games = (byDate[day] || []).slice().sort((a, b) => String(a.start || '').localeCompare(String(b.start || '')));
    const nav = '<div class="gd-nav">' +
      (prev ? '<a class="gd-arrow" href="' + BP.href('games/' + prev, L, S) + '" title="Previous game day">‹</a>' : '<span class="gd-arrow off">‹</span>') +
      '<input type="date" id="gd-date" value="' + esc(day) + '" min="' + esc(dates[0]) + '" max="' + esc(dates[dates.length - 1]) + '">' +
      (next ? '<a class="gd-arrow" href="' + BP.href('games/' + next, L, S) + '" title="Next game day">›</a>' : '<span class="gd-arrow off">›</span>') +
      '<div class="gd-strip">' + strip.map(x => '<a class="gd-day' + (x === day ? ' on' : '') + (x === BP.todayISO() ? ' today' : '') + '" href="' + BP.href('games/' + x, L, S) + '"><b>' +
        esc(BP.fmtDate(x, { year: false, weekday: false })) + '</b><span>' + byDate[x].length + ' game' + (byDate[x].length > 1 ? 's' : '') + '</span></a>').join('') + '</div>' +
      (isCurrent && dates.indexOf(BP.todayISO()) >= 0 && day !== BP.todayISO() ? '<a class="gd-today" href="' + BP.href('games/' + BP.todayISO(), L, S) + '">Today</a>' : '') +
      '<span class="pg-toggle gd-view" id="gd-view"><button type="button" data-v="cards"' + (VIEW === 'cards' ? ' class="on"' : '') + '>Cards</button><button type="button" data-v="table"' + (VIEW === 'table' ? ' class="on"' : '') + '>Table</button></span></div>';
    const sum = summary(games);
    body.innerHTML = '<div class="card">' + nav + '<div class="card-header">' + esc(BP.fmtDate(day)) + ' <span class="card-sub">' + games.length + ' game' + (games.length === 1 ? '' : 's') +
      (sum ? ' · ' + esc(sum) : '') + '</span></div><div id="gd-list"></div></div>' +
      '<div class="section-note">Model: the plate-appearance simulation with the probable starters (home win %, expected total, home -1.5). Market: Kalshi and Polymarket, de-vigged; the figure in brackets is the model minus the market in points. DraftKings lines as ESPN shows them. 18+.</div>';
    const draw = () => {
      const box = document.getElementById('gd-list');
      if (!box) return;
      if (!games.length) { box.innerHTML = BP.muted('No games on this date.'); return; }
      if (VIEW === 'table') { box.innerHTML = tableView(games, L, S); BP.sortable(box); return; }
      const live = games.filter(BP.isLive), pre = games.filter(c => BP.gameState(c) === 'pre'), fin = games.filter(BP.isFinal);
      const other = games.filter(c => live.indexOf(c) < 0 && pre.indexOf(c) < 0 && fin.indexOf(c) < 0);
      const block = (t, l) => (l.length ? '<div class="day-head">' + esc(t) + '</div><div class="gc-grid">' + l.map(c => BP.gameCard(c, { level: L, season: S })).join('') + '</div>' : '');
      box.innerHTML = block('Live', live) + block('Still to play', pre) + block('Final', fin) + block('Postponed or suspended', other);
    };
    draw();
    document.querySelectorAll('#gd-view button').forEach(b => b.addEventListener('click', () => {
      VIEW = b.dataset.v;
      try { window.localStorage.setItem('qb-games-view', VIEW); } catch (e) { /* private mode */ }
      document.querySelectorAll('#gd-view button').forEach(x => x.classList.toggle('on', x === b));
      draw();
    }));
    const inp = document.getElementById('gd-date');
    if (inp) inp.addEventListener('change', () => { if (/^\d{4}-\d\d-\d\d$/.test(inp.value)) BP.go(BP.href('games/' + inp.value, L, S)); });
    if (isCurrent && games.some(BP.isLive)) BP.liveRefresh([BP.ypath('schedule.json', L, S)], 90000);
    BP.setMeta(d && d.updated_at ? 'Schedule ' + esc(BP.fmtStamp(d.updated_at)) : '');
  });
}

BP.route('games', render);
})(window.BP);
