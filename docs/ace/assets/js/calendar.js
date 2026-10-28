/* The Quant Ace — the calendar (#/<T>/calendar), Draws › Tournaments.
 *
 * Round 9 (28 Oct 2026, as the Paddock's race cards): every tournament of the year as a card grid by month: the level and
 * status, the name, dates, place and surface, then the champion (or the tournament in play, or the next one) and our
 * top-rated entrant going in, with a tick when that player won ("hit") or a cross when not ("miss"). Our top-rated
 * entrant is the main-draw player with the highest surface-blended Elo before their first match of the event
 * (favourites.json; nothing from the event itself enters). A strip counts the hits; "Table" keeps the old dense list
 * (draw size, runner-up). Filters: level (tour-level, Slams Finals and 1000s, with Challengers / WTA 125s) and surface.
 * ?y=<year> shows another year. Reads <T>/<Y>/events.json and <T>/favourites.json; the tournaments in play take our
 * live title favourite from index.json (events_now). */
(function (TA) {
'use strict';

const esc = TA.esc, isNum = TA.isNum;
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
let VIEW = 'cards';

function card(T, e, fav, nextId, now) {
  const st = String(e.status || '');
  const done = !!e.champion;
  const live = st === 'live' && !done;
  const badge = done ? '<span class="qk-badge final">Result</span>' : live ? '<span class="qk-badge live">In play</span>' : e.id === nextId ? '<span class="qk-badge accent">Next</span>' : '<span class="qk-badge">' + esc(TA.fmtRange(e.start, e.end)) + '</span>';
  let body = '';
  if (done) {
    body = '<div class="ta-cc-win"><span class="ta-cc-k">Champion</span><b>' + esc(TA.playerName(T, e.champion)) + '</b>' + (e.runner_up ? '<span class="ta-cc-s">beat ' + esc(TA.playerSurname(T, e.runner_up)) + ' in the final</span>' : '') + '</div>';
    if (fav) {
      const hit = String(fav[0]) === String(e.champion);
      body += '<div class="ta-cc-fav ' + (hit ? 'hit' : 'miss') + '"><span class="ta-cc-mark" aria-label="' + (hit ? 'Hit' : 'Miss') + '">' + (hit ? '✓' : '✗') + '</span><span>Our top-rated going in: <b>' + esc(TA.playerSurname(T, fav[0])) + '</b> <span class="ta-cc-s">Elo ' + TA.num(fav[1], 0) + '</span></span></div>';
    }
  } else if (live && now && now.favourite && now.favourite[0]) {
    body = '<div class="ta-cc-win"><span class="ta-cc-k">Our favourite now</span><b>' + esc(TA.playerName(T, now.favourite[0])) + '</b><span class="ta-cc-p">' + TA.pct(now.favourite[1], 0) + ' to win it</span></div>';
  } else if (fav) {
    body = '<div class="ta-cc-win"><span class="ta-cc-k">Our top-rated entrant</span><b>' + esc(TA.playerName(T, fav[0])) + '</b><span class="ta-cc-s">Elo ' + TA.num(fav[1], 0) + '</span></div>';
  } else body = '<div class="ta-cc-win qk-muted"><span class="ta-cc-s">' + (live ? 'Title chances on the tournament page' : 'The draw comes out the week before') + '</span></div>';
  return '<a class="qk-card is-link ta-cc' + (e.id === nextId ? ' is-next' : '') + (live ? ' is-live' : '') + '" href="' + TA.eventHref(T, e.id) + '" style="--sf:' + TA.surfaceColour(e.surface, e.indoor) + '">' +
    '<div class="ta-cc-top"><span class="ta-cc-lv">' + esc(TA.levelLabel(e.level, T)) + '</span>' + badge + '</div>' +
    '<div class="ta-cc-name">' + esc(e.name || TA.eventName(T, e.id)) + '</div>' +
    '<div class="ta-cc-sub">' + esc([TA.fmtRange(e.start, e.end), e.city, TA.surfaceLabel(e.surface, e.indoor)].filter(Boolean).join(' · ')) + '</div>' + body + '</a>';
}

function render(el, params) {
  const T = params.tour, Y = params.year;
  el.innerHTML = '<div id="cal-body">' + QK.skeleton('lines', 6) + '</div>';
  return Promise.all([TA.loadYear('events.json', T, Y), TA.loadTour('favourites.json', T)]).then(res => {
    if (!el.isConnected) return;
    const raw = res[0], FV = TA.ok(res[1]) ? (res[1].events || {}) : {};
    const evs = TA.ok(raw) ? TA.eventsOf(raw) : raw;
    const body = document.getElementById('cal-body');
    if (!TA.ok(evs) || !Object.keys(evs).length) { body.innerHTML = TA.card('Calendar', '', TA.notBuilt('The ' + Y + ' calendar', evs)); return; }
    const all = Object.keys(evs).map(id => Object.assign({ id: id }, evs[id])).filter(e => e.level !== 'q')
      .sort((a, b) => String(a.start).localeCompare(String(b.start)) || TA.levelRank(a.level) - TA.levelRank(b.level));
    const nowBy = {};
    (Y === TA.currentYear(T) ? (TA.tourInfo(T).events_now || []) : []).forEach(x => { nowBy[x.event] = x; });
    let lev = 'tour', sf = 'all';
    const today = TA.todayISO();
    const nextId = (all.find(e => String(e.start) > today && e.level !== 'ch') || {}).id;
    const done = all.filter(e => e.level !== 'ch' && e.level !== 'other' && e.champion);
    const counts = {};
    done.forEach(e => { counts[e.champion] = (counts[e.champion] || 0) + 1; });
    const leaders = Object.keys(counts).sort((a, b) => counts[b] - counts[a]).slice(0, 3);
    const slams = all.filter(e => e.level === 'slam');
    const liveNow = all.filter(e => e.status === 'live' && e.level !== 'ch' && !e.champion).slice(0, 3);
    const called = done.filter(e => FV[e.id]), hits = called.filter(e => String(FV[e.id][0]) === String(e.champion));
    body.innerHTML = '<div class="kpi-grid ta-kpis">' +
      TA.statTile('Tour-level events', String(all.filter(e => TA.levelRank(e.level) <= 5).length), done.length + ' finished') +
      TA.statTile('Our top-rated won', called.length ? hits.length + ' of ' + called.length : '—', called.length ? TA.pct(hits.length / called.length, 0) + ' of the finished events: one player against the whole draw' : 'no finished events yet') +
      TA.statTile('Most titles', leaders.length ? leaders.map(p => esc(TA.playerSurname(T, p)) + ' ' + counts[p]).join(' · ') : '—', 'tour-level, ' + Y) +
      TA.statTile('Grand Slams', slams.length ? slams.map(e => e.champion ? esc(TA.playerSurname(T, e.champion)) : '—').join(' · ') : '—', 'champions in calendar order') +
      (liveNow.length ? TA.statTile('In play', liveNow.map(e => TA.eventLink(T, e.id)).join(' · '), liveNow.map(e => esc(TA.levelLabel(e.level, T))).join(' · '))
        : TA.statTile('Next up', nextId ? TA.eventLink(T, nextId) : '—', nextId ? esc(TA.fmtRange(evs[nextId].start, evs[nextId].end)) : '')) + '</div>' +
      '<div class="card"><div class="ctl-row"><span>Level</span>' +
      TA.toggles([{ key: 'tour', label: 'Tour-level' }, { key: 'big', label: 'Slams, Finals & 1000s' }, { key: 'all', label: T === 'atp' ? 'With Challengers' : 'With WTA 125s' }], lev, 'data-lv') +
      '<span style="margin-left:8px">Surface</span>' + TA.toggles([{ key: 'all', label: 'All' }, { key: 'hard', label: 'Hard' }, { key: 'clay', label: 'Clay' }, { key: 'grass', label: 'Grass' }], sf, 'data-sf') +
      '<span style="margin-left:8px">Show</span>' + TA.toggles([{ key: 'cards', label: 'Cards' }, { key: 'table', label: 'Table' }], VIEW, 'data-vw') +
      '</div><div id="cal-list"></div></div>' +
      QK.explain('<b>Hit or miss.</b> Each finished card names our top-rated entrant going in: the main-draw player with the highest Elo for the surface before their first match there. ✓ means that player won the title, ✗ that someone else did. Even a clear favourite wins a 32-player draw well under half the time, so most cards are a ✗.');
    const draw = () => {
      const list = all.filter(e => (lev === 'all' ? true : lev === 'big' ? ['slam', 'finals', 'm1000'].indexOf(e.level) >= 0 : e.level !== 'ch') && (sf === 'all' || e.surface === sf));
      const byM = {};
      list.forEach(e => { const d = TA.parseDate(e.start); const m = d ? d.getUTCMonth() : 12; (byM[m] = byM[m] || []).push(e); });
      const months = Object.keys(byM).map(Number).sort((a, b) => a - b);
      const html = VIEW === 'cards'
        ? months.map(m => '<div class="cal-month">' + esc(MONTHS[m] || 'Date to be confirmed') + '</div><div class="ta-ccs">' + byM[m].map(e => card(T, e, FV[e.id], nextId, nowBy[e.id])).join('') + '</div>').join('')
        : months.map(m => '<div class="cal-month">' + esc(MONTHS[m] || 'Date to be confirmed') + '</div>' +
          TA.tableHTML([{ label: 'Dates' }, { label: 'Tournament' }, { label: 'Level', cls: 'hide-sm' }, { label: 'Surface', cls: 'hide-sm' }, { label: 'Place', cls: 'hide-sm' },
            { label: 'Draw', align: 'right', cls: 'hide-sm' }, { label: 'Champion' }, { label: 'Runner-up', cls: 'hide-sm' }, { label: 'Our top-rated', cls: 'hide-sm', title: 'The entrant with the highest surface Elo going in; ✓ when that player won' }],
          byM[m].map(e => {
            const st = String(e.status || ''), fv = FV[e.id];
            const stHtml = st === 'live' ? '<span class="chip st-live"><span class="live-dot"></span> In play</span>' : e.id === nextId ? '<span class="chip info">Next</span>' : (st === 'upcoming' ? '<span class="muted-inline">upcoming</span>' : '<span class="muted-inline">—</span>');
            return { _href: TA.eventHref(T, e.id), _class: st === 'live' ? 'ev-live' : e.id === nextId ? 'ev-next' : '', cells: [
              { v: e.start, html: esc(TA.fmtRange(e.start, e.end)) },
              { v: e.name, html: TA.eventLink(T, e.id, { surface: true }) + (e.level === 'slam' ? ' <span class="chip lv-chip lv-slam">GS</span>' : '') },
              { v: TA.levelRank(e.level), html: esc(TA.levelLabel(e.level, T)) },
              { v: e.surface, html: TA.surfaceDot(e.surface, e.indoor) + esc(TA.surfaceLabel(e.surface, e.indoor)) },
              { v: e.city, html: esc([e.city, e.country].filter(Boolean).join(', ')) },
              { v: e.draw_size, html: isNum(e.draw_size) ? String(e.draw_size) : '—' },
              { v: e.champion ? TA.playerName(T, e.champion) : '', html: e.champion ? TA.playerLink(T, e.champion) : stHtml },
              { v: e.runner_up ? TA.playerName(T, e.runner_up) : '', html: e.runner_up ? TA.playerLink(T, e.runner_up) : '—' },
              { v: fv ? TA.playerName(T, fv[0]) : '', html: fv ? TA.playerLink(T, fv[0], { surname: true }) + (e.champion ? (String(fv[0]) === String(e.champion) ? ' ✓' : ' ✗') : '') : '—' }
            ] };
          }), { compact: true, cls: 'cal-table' })).join('');
      const node = document.getElementById('cal-list');
      node.innerHTML = html || TA.muted('No tournaments match the filters.');
      TA.sortable(node);
    };
    draw();
    TA.wireToggles(body.querySelector('.ctl-row'), 'data-lv', k => { lev = k; draw(); });
    TA.wireToggles(body.querySelector('.ctl-row'), 'data-sf', k => { sf = k; draw(); });
    TA.wireToggles(body.querySelector('.ctl-row'), 'data-vw', k => { VIEW = k; draw(); });
    TA.setMeta(all.length + ' tournaments');
  });
}

TA.route('calendar', render);
})(window.TA);
