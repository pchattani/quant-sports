/* The Quant Bullpen — games of a day (#/<L>/games[/<date>]).
 *
 *   a date picker (input, previous/next game day, a strip of nearby game days);
 *   the day's games as v2 cards (our win chance, records and form as of that morning, a one-line reason; no market) or
 *   as a table (our favourite, expected runs, the result, and whether our favourite won); a one-line summary.
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
  let right = 0, ll = 0;
  fin.forEach(c => {
    const p = c.model.p_home, homeWon = c.hs > c.as;
    if ((p >= 0.5) === homeWon) right++;
    ll += -Math.log(Math.max(1e-6, homeWon ? p : 1 - p));
  });
  return 'Our favourites won ' + right + ' of ' + fin.length + ' (log loss ' + BP.num(ll / fin.length, 3) + ')';
}
/* Records (regular season) and last-five form for every club from the finals before a day: what was known that morning. */
function asOf(list, day) {
  const rec = {}, prior = list.filter(c => c && c.date < day && BP.isFinal(c) && isNum(c.hs) && isNum(c.as) && c.hs !== c.as);
  prior.filter(c => !c.gtype || c.gtype === 'R').forEach(c => {
    const hw = c.hs > c.as;
    [[c.home, hw], [c.away, !hw]].forEach(x => { const r = rec[x[0]] = rec[x[0]] || [0, 0]; r[x[1] ? 0 : 1]++; });
  });
  const out = {};
  Object.keys(rec).forEach(t => { out[t] = rec[t][0] + '-' + rec[t][1]; });
  BP.setRecords(out);
  BP.setForms(BP.ui.forms(prior));
}

function tableView(list, L, S) {
  const rows = list.map(c => {
    const m = c.model || {};
    const fin = BP.isFinal(c);
    const homeWon = fin && c.hs > c.as;
    const fav = isNum(m.p_home) ? (m.p_home >= 0.5 ? 'home' : 'away') : null;
    const hit = fin && fav ? ((fav === 'home') === homeWon) : null;
    const pf = fav ? (fav === 'home' ? m.p_home : 1 - m.p_home) : null;
    return { _href: BP.gameHref(c.gpk, L, S), cells: [
      { v: c.start || c.date, html: BP.statusChip(c), cls: 'hide-sm' },
      { v: BP.teamAbbr(c.away) + ' @ ' + BP.teamAbbr(c.home), html: BP.teamLink(c.away, { abbr: true, level: L }) + ' <span class="muted-inline">@</span> ' + BP.teamLink(c.home, { abbr: true, level: L }) +
        (c.series ? '<div class="sub-line">' + esc(BP.seriesText(c.series, true)) + '</div>' : '') },
      { v: fin || BP.isLive(c) ? (c.as + '-' + c.hs) : '', html: fin || BP.isLive(c) ? '<b>' + esc(c.as) + '-' + esc(c.hs) + '</b>' + (BP.isLive(c) ? ' <span class="live-dot"></span>' : '') : '<span class="muted-inline">—</span>' },
      { v: pf, html: fav ? '<b class="bp-ours">' + esc(BP.teamAbbr(c[fav])) + ' ' + BP.pct(pf, 0) + '</b>' : '—', align: 'right', title: 'Our pre-game favourite and its win chance' },
      { v: m.total, html: isNum(m.total) ? BP.num(m.total, 1) : '—', align: 'right', cls: 'hide-sm' },
      { v: hit === null ? '' : (hit ? 1 : 0), html: hit === null ? '' : (hit ? '<span class="edge-pos">✓</span>' : '<span class="edge-neg">✗</span>'), align: 'center', title: 'Did our favourite win?' }
    ] };
  });
  return BP.tableHTML([{ label: 'Status', cls: 'hide-sm' }, { label: 'Game' }, { label: 'Score' }, { label: 'Our favourite', align: 'right' },
    { label: 'Runs expected', align: 'right', cls: 'hide-sm', title: 'Our expected total runs' }, { label: 'Won?', align: 'center' }], rows, { compact: true });
}

function render(el, params) {
  const L = params.level, S = params.season;
  const isCurrent = S === BP.currentSeason(L);
  el.innerHTML = '<div id="gm-body">' + QK.skeleton('card', 3) + '</div>';
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
    const unneeded = BP.unneededIn(list);
    list = list.filter(c => !BP.notNeeded(c) && !unneeded(c));
    if (!list.length) { body.innerHTML = BP.card('Games', '', BP.notBuilt('The ' + S + ' schedule', d)); return; }
    const byDate = {};
    list.forEach(c => { if (c && c.date) (byDate[c.date] = byDate[c.date] || []).push(c); });
    const dates = Object.keys(byDate).sort();
    const day = pickDate(dates, params.date, isCurrent);
    const i = dates.indexOf(day);
    const prev = i > 0 ? dates[i - 1] : null, next = i >= 0 && i + 1 < dates.length ? dates[i + 1] : null;
    const strip = dates.slice(Math.max(0, i - 3), Math.min(dates.length, i + 4));
    asOf(list, day);
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
    body.innerHTML = QK.sectionHead({ kicker: 'Scoreboard · ' + BP.levelName(L), title: BP.fmtDate(day), sub: games.length + ' game' + (games.length === 1 ? '' : 's') + (sum ? ' · ' + sum : '') }) +
      '<div class="qk-card bp-daynav">' + nav + '</div><div id="gd-list"></div>' +
      '<p class="bp-note">Our chance comes from the plate-appearance simulation with the probable starters and the posted (or projected) lineups. Records and form are as they stood that morning. The italic line on each card says why it is worth a look.</p>';
    const draw = () => {
      const box = document.getElementById('gd-list');
      if (!box) return;
      if (!games.length) { box.innerHTML = BP.muted('No games on this date.'); return; }
      if (VIEW === 'table') { box.innerHTML = tableView(games, L, S); BP.sortable(box); return; }
      const live = games.filter(BP.isLive), pre = games.filter(c => BP.gameState(c) === 'pre'), fin = games.filter(BP.isFinal);
      const other = games.filter(c => live.indexOf(c) < 0 && pre.indexOf(c) < 0 && fin.indexOf(c) < 0);
      const block = (t, l) => (l.length ? '<div class="day-head">' + esc(t) + '</div><div class="bp-gc-grid">' + l.map(c => BP.gameCard(c, { level: L, season: S, why: true })).join('') + '</div>' : '');
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
