/* The Quant Ace — the calendar (#/<T>/calendar).
 *
 * Every tournament of the year by month: dates, level, surface, place, draw size, status,
 * champion and runner-up; tournaments in play are highlighted and the next one marked.
 * Filters: level (all tour-level, Slams and 1000s, or including Challengers / WTA 125s) and surface.
 * ?y=<year> shows another year. Reads <T>/<Y>/events.json. */
(function (TA) {
'use strict';

const esc = TA.esc;
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

function render(el, params) {
  const T = params.tour, Y = params.year;
  el.innerHTML = TA.pageHead(TA.tourName(T) + ' calendar ' + Y, 'Every tournament of the year: level, surface, status and champion',
    '<a href="' + TA.href(T, 'rankings') + '">Rankings</a><a href="' + TA.href(T, 'race') + '">Race</a>') + '<div id="cal-body"><div class="muted">Loading…</div></div>';
  return TA.loadYear('events.json', T, Y).then(raw => {
    if (!el.isConnected) return;
    const evs = TA.ok(raw) ? TA.eventsOf(raw) : raw;
    const body = document.getElementById('cal-body');
    if (!TA.ok(evs) || !Object.keys(evs).length) { body.innerHTML = TA.card('Calendar', '', TA.notBuilt('The ' + Y + ' calendar', evs)); return; }
    const all = Object.keys(evs).map(id => Object.assign({ id: id }, evs[id])).filter(e => e.level !== 'q')
      .sort((a, b) => String(a.start).localeCompare(String(b.start)) || TA.levelRank(a.level) - TA.levelRank(b.level));
    let lev = 'tour', sf = 'all';
    const today = TA.todayISO();
    const nextId = (all.find(e => String(e.start) > today && e.level !== 'ch') || {}).id;
    const done = all.filter(e => e.level !== 'ch' && e.level !== 'other' && e.champion);
    const counts = {};
    done.forEach(e => { counts[e.champion] = (counts[e.champion] || 0) + 1; });
    const leaders = Object.keys(counts).sort((a, b) => counts[b] - counts[a]).slice(0, 3);
    const slams = all.filter(e => e.level === 'slam');
    const liveNow = all.filter(e => e.status === 'live' && e.level !== 'ch').slice(0, 3);
    body.innerHTML = '<div class="kpi-grid">' +
      TA.statTile('Tour-level events', String(all.filter(e => TA.levelRank(e.level) <= 5).length), done.length + ' finished') +
      TA.statTile('Most titles', leaders.length ? leaders.map(p => esc(TA.playerSurname(T, p)) + ' ' + counts[p]).join(' · ') : '—', 'tour-level, this year') +
      TA.statTile('Grand Slams', slams.length ? slams.map(e => e.champion ? esc(TA.playerSurname(T, e.champion)) : '—').join(' · ') : '—', 'champions in calendar order') +
      (liveNow.length ? TA.statTile('In play', liveNow.map(e => TA.eventLink(T, e.id)).join(' · '), liveNow.map(e => esc(TA.levelLabel(e.level, T))).join(' · '))
        : TA.statTile('Next up', nextId ? TA.eventLink(T, nextId) : '—', nextId ? esc(TA.fmtRange(evs[nextId].start, evs[nextId].end)) : '')) + '</div>' +
      '<div class="card"><div class="ctl-row"><span>Level</span>' +
      TA.toggles([{ key: 'tour', label: 'Tour-level' }, { key: 'big', label: 'Slams, Finals & 1000s' }, { key: 'all', label: T === 'atp' ? 'With Challengers' : 'With WTA 125s' }], lev, 'data-lv') +
      '<span style="margin-left:8px">Surface</span>' + TA.toggles([{ key: 'all', label: 'All' }, { key: 'hard', label: 'Hard' }, { key: 'clay', label: 'Clay' }, { key: 'grass', label: 'Grass' }], sf, 'data-sf') +
      '</div><div id="cal-list"></div></div>';
    const draw = () => {
      const list = all.filter(e => (lev === 'all' ? true : lev === 'big' ? ['slam', 'finals', 'm1000'].indexOf(e.level) >= 0 : e.level !== 'ch') && (sf === 'all' || e.surface === sf));
      const byM = {};
      list.forEach(e => { const d = TA.parseDate(e.start); const m = d ? d.getUTCMonth() : 12; (byM[m] = byM[m] || []).push(e); });
      const html = Object.keys(byM).map(Number).sort((a, b) => a - b).map(m => '<div class="cal-month">' + esc(MONTHS[m] || 'Date to be confirmed') + '</div>' +
        TA.tableHTML([{ label: 'Dates' }, { label: 'Tournament' }, { label: 'Level', cls: 'hide-sm' }, { label: 'Surface', cls: 'hide-sm' }, { label: 'Place', cls: 'hide-sm' },
          { label: 'Draw', align: 'right', cls: 'hide-sm' }, { label: 'Champion' }, { label: 'Runner-up', cls: 'hide-sm' }],
        byM[m].map(e => {
          const st = String(e.status || '');
          const stHtml = st === 'live' ? '<span class="chip st-live"><span class="live-dot"></span> In play</span>' : e.id === nextId ? '<span class="chip info">Next</span>' : (st === 'upcoming' ? '<span class="muted-inline">upcoming</span>' : '<span class="muted-inline">—</span>');
          return { _href: TA.eventHref(T, e.id), _class: st === 'live' ? 'ev-live' : e.id === nextId ? 'ev-next' : '', cells: [
            { v: e.start, html: esc(TA.fmtRange(e.start, e.end)) },
            { v: e.name, html: TA.eventLink(T, e.id, { surface: true }) + (e.level === 'slam' ? ' <span class="chip lv-chip lv-slam">GS</span>' : '') },
            { v: TA.levelRank(e.level), html: esc(TA.levelLabel(e.level, T)) },
            { v: e.surface, html: '<span style="color:' + TA.surfaceColour(e.surface, e.indoor) + '">' + esc(TA.surfaceLabel(e.surface, e.indoor)) + '</span>' },
            { v: e.city, html: esc([e.city, e.country].filter(Boolean).join(', ')) },
            { v: e.draw_size, html: TA.isNum(e.draw_size) ? String(e.draw_size) : '—' },
            { v: e.champion ? TA.playerName(T, e.champion) : '', html: e.champion ? '🏆 ' + TA.playerLink(T, e.champion) : stHtml },
            { v: e.runner_up ? TA.playerName(T, e.runner_up) : '', html: e.runner_up ? TA.playerLink(T, e.runner_up) : '—' }
          ] };
        }), { compact: true, cls: 'cal-table' })).join('');
      const node = document.getElementById('cal-list');
      node.innerHTML = html || TA.muted('No tournaments match the filters.');
      TA.sortable(node);
    };
    draw();
    TA.wireToggles(body.querySelector('.ctl-row'), 'data-lv', k => { lev = k; draw(); });
    TA.wireToggles(body.querySelector('.ctl-row'), 'data-sf', k => { sf = k; draw(); });
    TA.setMeta(all.length + ' tournaments');
  });
}

TA.route('calendar', render);
})(window.TA);
