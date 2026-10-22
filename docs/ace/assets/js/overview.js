/* The Quant Ace — Overview (#/ and #/<T>): the tour at a glance, charts first.
 *
 *   hero: the tour, year and the tournaments in play, with four headline numbers (World No. 1, Elo No. 1, the
 *         year-end No. 1 favourite, matches today and live);
 *   tournaments in play (level, surface, round, the model's favourite);
 *   matches: live, today, next and recent as the kit's match cards (model, market, edge, set scores);
 *   charts: title odds for the tournament in play (model v market), the Elo top 10 by surface, the race to the
 *           Finals (qualification odds, model v market), the biggest model-v-market gaps;
 *   past years: the season's champions at the Slams, the Finals and the 1000s.
 *
 * Reads index.json (tours[T]), <T>/markets.json, <T>/race.json and the in-play events' <T>/events/<id>.json.
 * Charts are the kit's (QKC on ECharts); each sits beside a list or table with the same numbers. */
(function (TA) {
'use strict';

const esc = TA.esc;
const isNum = TA.isNum;

function kpi(label, value, sub, tip) {
  return '<div class="qk-kpi"><div class="qk-kpi-label">' + (tip ? '<span data-tip="' + esc(tip) + '">' + esc(label) + '</span>' : esc(label)) + '</div>' +
    '<div class="qk-kpi-value is-text">' + value + '</div>' + (sub ? '<div class="qk-kpi-sub"><span class="qk-truncate">' + sub + '</span></div>' : '') + '</div>';
}
function chartCard(id, title, sub, h, span, foot, extra) {
  return '<section class="qk-card qk-span-' + span + '"><div class="qk-card-head"><div><div class="qk-card-title">' + esc(title) + '</div>' +
    (sub ? '<div class="qk-card-sub">' + sub + '</div>' : '') + '</div></div><div class="qk-card-body">' + (extra || '') + '<div id="' + id + '" style="--h:' + h + 'px"></div></div>' +
    (foot ? '<div class="qk-card-foot">' + foot + '</div>' : '') + '</section>';
}
function more(href, label) { return '<a href="' + href + '">' + esc(label) + ' →</a>'; }

function gapRows(T, cards, markets, race, evs) {
  const out = [], seen = {};
  cards.forEach(c => {
    if (!c || seen[c.id] || TA.isFinished(c)) return;
    seen[c.id] = 1;
    const m = c.model || {}, mk = c.market || {};
    if (!isNum(m.p1) || !isNum(mk.p1)) return;
    const up = m.p1 >= mk.p1, side = up ? c.p1 : c.p2;
    out.push({ label: TA.playerSurname(T, side) + ' to beat ' + TA.playerSurname(T, up ? c.p2 : c.p1), sub: TA.eventName(T, c.event) + ' · ' + TA.roundLabel(c.round, true),
      a: up ? m.p1 : 1 - m.p1, b: up ? mk.p1 : 1 - mk.p1, href: TA.matchHref(T, c.id) });
  });
  const fe = ((markets && markets.futures) || {}).events || {};
  Object.keys(fe).forEach(eid => {
    const pr = TA.titleProbs(fe[eid]);
    const ev = evs[eid];
    const sim = ev && ev.sim && ev.sim.players ? ev.sim.players : null;
    if (!sim) return;
    Object.keys(pr).forEach(pid => {
      const s = sim[pid];
      if (!s || !isNum(s.p_title) || (s.p_title < 0.01 && pr[pid] < 0.01)) return;
      out.push({ label: TA.playerSurname(T, pid) + ' to win ' + TA.eventName(T, eid), sub: 'Title odds', a: s.p_title, b: pr[pid], href: TA.eventHref(T, eid) });
    });
  });
  const rq = TA.titleProbs(((race || {}).market || {}).finals_qual);
  Object.keys(rq).forEach(pid => {
    const p = ((race || {}).finals_qual || {})[pid];
    if (!isNum(p) || (p < 0.01 && rq[pid] < 0.01) || (p > 0.995 && rq[pid] > 0.995)) return;
    out.push({ label: TA.playerSurname(T, pid) + ' to qualify for the Finals', sub: 'Season simulation', a: p, b: rq[pid], href: TA.href(T, 'race') });
  });
  out.forEach(r => { r.gap = r.a - r.b; });
  return out.sort((x, y) => Math.abs(y.gap) - Math.abs(x.gap)).slice(0, 8);
}

function champions(T, Y) {
  const ev = TA.EVENTS[T][String(Y)] || {};
  const ids = Object.keys(ev).filter(id => ['slam', 'finals', 'm1000'].indexOf(ev[id].level) >= 0 && ev[id].champion)
    .sort((a, b) => String(ev[a].start).localeCompare(String(ev[b].start)));
  if (!ids.length) return '';
  return TA.tableHTML([{ label: 'Tournament' }, { label: 'Level', cls: 'hide-sm' }, { label: 'Champion' }, { label: 'Runner-up', cls: 'hide-sm' }],
    ids.map(id => [{ v: ev[id].start, html: TA.eventLink(T, id, { surface: true }) }, { v: TA.levelRank(ev[id].level), html: esc(TA.levelLabel(ev[id].level, T)), cls: 'hide-sm' },
      { v: TA.playerName(T, ev[id].champion), html: TA.playerLink(T, ev[id].champion) }, { v: TA.playerName(T, ev[id].runner_up), html: ev[id].runner_up ? TA.playerLink(T, ev[id].runner_up) : '—', cls: 'hide-sm' }]), { compact: true });
}

function render(el, params) {
  const T = params.tour, Y = params.year;
  const info = TA.tourInfo(T);
  const isCurrent = Y === TA.currentYear(T);
  const evNow = isCurrent ? (info.events_now || []) : [];
  el.innerHTML = '<div class="ov">' + QK.skeleton('card', 3) + '</div>';
  return TA.loadAll([TA.tpath('markets.json', T), TA.tpath('race.json', T)].concat(evNow.map(e => TA.eventPath(T, e.event)))).then(arr => {
    if (!el.isConnected) return;
    const markets = isCurrent && TA.ok(arr[0]) ? arr[0] : null, race = isCurrent && TA.ok(arr[1]) ? arr[1] : null;
    const evs = {};
    evNow.forEach((e, i) => { if (TA.ok(arr[2 + i])) evs[e.event] = arr[2 + i]; });
    const live = isCurrent ? (info.live || []) : [], today = isCurrent ? (info.today || []) : [];
    const upcoming = isCurrent ? (info.upcoming || []) : [], recent = isCurrent ? (info.recent || []) : [];
    const rk = (info.race_top || [])[0];
    const elo1 = ((info.elo_top || {}).all || [])[0];
    let no1 = null;
    Object.keys(TA.NAMES[T]).forEach(pid => { if (TA.NAMES[T][pid].rank === 1) no1 = pid; });
    const gaps = isCurrent ? gapRows(T, live.concat(today, upcoming), markets, race, evs) : [];
    let yeFav = null;
    if (race && race.year_end_no1) Object.keys(race.year_end_no1).forEach(pid => { const p = race.year_end_no1[pid]; if (isNum(p) && (!yeFav || p > yeFav[1])) yeFav = [pid, p]; });
    if (!yeFav && rk && isNum(rk[2])) yeFav = [rk[0], rk[2]];

    // ── hero
    const kicker = [info.name || TA.tourName(T), isCurrent ? (evNow.length ? evNow.map(e => e.name || TA.eventName(T, e.event)).join(' · ') + ' in play' : 'between tournaments') : 'season review'].join(' · ');
    const lede = isCurrent
      ? 'Every match priced from serve and return ratings inferred from scores and surface Elo, every draw simulated, and both set against the betting and prediction markets.'
      : 'The ' + Y + ' season: the champions, the rankings and the ratings as they finished.';
    const k1 = kpi('World No. 1', no1 ? esc(TA.playerShort(T, no1)) : '—', no1 && TA.playerCountry(T, no1) ? esc(TA.playerCountry(T, no1)) + ' · official ranking' : 'official ranking');
    const k2 = kpi('Elo No. 1', elo1 ? esc(TA.playerShort(T, elo1[0])) : '—', elo1 ? '<span class="num">' + TA.num(elo1[1], 0) + '</span> surface-blended Elo' : '', 'Our rating from every tour-level result, weighted by surface');
    const k3 = isCurrent ? kpi('Year-end No. 1', yeFav ? esc(TA.playerShort(T, yeFav[0])) : '—', yeFav ? 'Model ' + TA.pct(yeFav[1], 0) + ' from simulating the season' : '', 'Probability of finishing the year ranked No. 1')
      : kpi('Tournaments', '<span class="num">' + Object.keys(TA.EVENTS[T][String(Y)] || {}).length + '</span>', 'in ' + Y);
    const k4 = isCurrent ? kpi(live.length ? 'Live now' : 'Matches today', '<span class="num">' + (live.length || today.length) + '</span>', live.length ? '<span class="qk-badge live">Live</span> ' + today.length + ' today' : (upcoming.length ? upcoming.length + ' scheduled next' : 'none scheduled'))
      : kpi('Elo leader', elo1 ? esc(TA.playerSurname(T, elo1[0])) : '—', '');
    let html = '<section class="ov-hero"><div class="ov-hero-main"><div class="qk-kicker">' + esc(kicker) + '</div><h1 class="ov-title">' + esc(TA.tourName(T)) + ' <span>' + Y + '</span></h1>' +
      '<p class="ov-lede">' + esc(lede) + '</p><div class="ov-hero-links">' +
      (evNow.length ? '<a class="qk-btn primary" href="' + TA.eventHref(T, evNow[0].event) + '">' + esc(evNow[0].name || TA.eventName(T, evNow[0].event)) + ' draw</a>' : '<a class="qk-btn primary" href="' + TA.href(T, 'calendar', Y) + '">Tournaments</a>') +
      '<a class="qk-btn" href="' + TA.href(T, 'rankings', Y) + '">Rankings</a>' + (isCurrent ? '<a class="qk-btn" href="' + TA.href(T, 'markets') + '">Odds board</a>' : '') + '</div></div>' +
      '<div class="ov-kpis">' + k1 + k2 + k3 + k4 + '</div></section>';

    if (evNow.length) {
      html += '<section class="qk-section"><div class="qk-section-head"><div><h2>In play</h2><div class="qk-sub">Open a tournament for the draw, every path and the title odds from simulating the rest of it.</div></div></div><div class="ov-events">' +
        evNow.map(e => {
          const inf = TA.eventInfo(T, e.event);
          const col = TA.surfaceColour(e.surface || inf.surface, inf.indoor);
          return '<a class="qk-card is-link ov-ev" href="' + TA.eventHref(T, e.event) + '" style="--sf:' + col + '"><span class="qk-kicker">' + esc(TA.levelLabel(e.level || inf.level, T)) + ' · ' + esc(TA.surfaceLabel(e.surface || inf.surface, inf.indoor)) + '</span>' +
            '<b>' + esc(e.name || TA.eventName(T, e.event)) + '</b><span class="ov-ev-meta">' + esc(TA.fmtRange(e.start, e.end)) + (e.round_now ? ' · ' + esc(TA.roundLabel(e.round_now)) : '') + '</span>' +
            (e.favourite && e.favourite[0] ? '<span class="ov-ev-fav">Favourite <b>' + esc(TA.playerShort(T, e.favourite[0])) + '</b> <span class="num">' + TA.pct(e.favourite[1], 0) + '</span></span>' : '') + '</a>';
        }).join('') + '</div></section>';
    }

    const shown = {};
    const pick = list => list.filter(c => c && !shown[c.id] && (shown[c.id] = 1));
    const order = pick(live).concat(pick(today.filter(c => !TA.isFinished(c)).sort((a, b) => String(a.date).localeCompare(String(b.date)))),
      pick(upcoming.slice().sort((a, b) => String(a.date).localeCompare(String(b.date)))),
      pick(today.filter(TA.isFinished).sort((a, b) => String(b.date).localeCompare(String(a.date)))), pick(recent.slice().sort((a, b) => String(b.date).localeCompare(String(a.date)))));
    if (order.length) {
      html += '<section class="qk-section"><div class="qk-section-head"><div><h2>' + (live.length ? 'Live and next' : 'Matches') + '</h2><div class="qk-sub">Model win probability beside each player; the strip compares the model (blue) with the de-vigged market (orange) before the first ball.</div></div>' +
        '<a class="qk-btn" href="' + TA.href(T, 'calendar', Y) + '">Every draw</a></div><div class="qk-auto" style="--min:280px">' + order.slice(0, 8).map(c => TA.matchCard(c, { tour: T })).join('') + '</div></section>';
    }

    // ── charts
    const ev0 = evNow.length ? evs[evNow[0].event] : null;
    const sim0 = ev0 && ev0.sim && ev0.sim.players ? ev0.sim.players : null;
    const mk0 = ev0 && markets && markets.futures && markets.futures.events ? TA.titleProbs(markets.futures.events[evNow[0].event]) : {};
    const titleRows = sim0 ? Object.keys(sim0).map(pid => ({ pid: pid, p: sim0[pid].p_title, m: mk0[pid] })).filter(r => isNum(r.p) && (r.p > 0.002 || (isNum(r.m) && r.m > 0.005))).sort((a, b) => b.p - a.p).slice(0, 10) : [];
    const raceRows = (info.race_top || []).filter(r => isNum(r[1])).slice(0, 12);
    const raceMk = TA.titleProbs(((race || {}).market || {}).finals_qual);
    const eloKeys = ['all', 'hard', 'clay', 'grass'].filter(k => ((info.elo_top || {})[k] || []).length);
    html += '<section class="qk-section"><div class="qk-section-head"><div><h2>The tour in charts</h2><div class="qk-sub">Tap a bar or a dot to open the player or the tournament.</div></div></div><div class="qk-grid ov-charts">';
    if (titleRows.length) html += chartCard('ov-title', 'Who wins ' + (evNow[0].name || TA.eventName(T, evNow[0].event)), titleRows.some(r => isNum(r.m)) ? 'Model title odds from simulating the draw (blue) against the de-vigged market (orange)' : 'Model title odds from simulating the rest of the draw', Math.max(360, titleRows.length * 34 + 40), 6, more(TA.eventHref(T, evNow[0].event), 'The draw and every path'));
    if (eloKeys.length) html += chartCard('ov-elo', 'Elo top 10', 'Our surface ratings from every tour-level result', 360, titleRows.length ? 6 : 6, more(TA.href(T, 'elo'), 'Elo tables and all-time peaks'),
      '<div class="qk-chips scroll" id="ov-sf" style="margin-bottom:8px">' + eloKeys.map((k, i) => '<button type="button" class="qk-chip" aria-pressed="' + (i === 0) + '" data-value="' + k + '">' + esc(k === 'all' ? 'Overall' : TA.surfaceLabel(k)) + '</button>').join('') + '</div>');
    if (isCurrent && raceRows.length) html += chartCard('ov-race', 'Race to the Finals', Object.keys(raceMk).length ? 'Chance to qualify: the season simulation (blue) against the market (orange)' : 'Chance to qualify, from simulating the rest of the season', Math.max(220, raceRows.length * 30 + 40), 6, more(TA.href(T, 'race'), 'The race and rank distributions'));
    if (gaps.length) html += chartCard('ov-gaps', 'Model v market', 'The biggest disagreements right now: matches, titles and the Finals race', Math.max(220, gaps.length * 40 + 40), 6, more(TA.href(T, 'markets'), 'Odds board'));
    html += '</div></section>';
    if (!isCurrent) {
      const ch = champions(T, Y);
      if (ch) html += '<section class="qk-section"><div class="qk-section-head"><div><h2>Champions</h2><div class="qk-sub">The Slams, the Finals and the 1000s in ' + Y + '</div></div><a class="qk-btn" href="' + TA.href(T, 'calendar', Y) + '">Every tournament</a></div><div class="qk-card">' + ch + '</div></section>';
    }
    html += '<section class="qk-section"><div class="qk-section-head"><div><h2>Explore</h2></div></div><div class="ov-explore">' + [
      [TA.href(T, 'players', Y), 'Players', 'Serve, return, clutch and percentiles for everyone'],
      [TA.href(T, 'h2h'), 'Head to head', 'Any two players, any surface'],
      [TA.href(T, 'value'), 'Value', 'Breakouts, luck, over- and undervalued players'],
      [TA.href(T, 'lab', Y), 'Lab', 'Scatter any two metrics; compare players'],
      [TA.href(T, 'calibration'), 'Calibration', 'Against the closing odds'],
      ['#/methodology', 'Model', 'How the ratings and simulations work']
    ].map(x => '<a class="qk-card is-link ov-x" href="' + x[0] + '"><b>' + esc(x[1]) + '</b><span>' + esc(x[2]) + '</span></a>').join('') + '</div></section>';

    el.innerHTML = '<div class="ov">' + html + '</div>';

    if (titleRows.length) {
      const top = Math.max.apply(null, titleRows.map(r => Math.max(r.p, r.m || 0)));
      if (titleRows.some(r => isNum(r.m))) QKC.dumbbell('#ov-title', { rows: titleRows.map(r => ({ label: TA.playerShort(T, r.pid), a: r.p, b: isNum(r.m) ? r.m : r.p, href: TA.playerHref(T, r.pid) })), aName: 'Model', bName: 'Market', valName: 'Title probability', labelWidth: 120, max: Math.min(1, Math.ceil(top * 10 + 0.5) / 10) });
      else QKC.bar('#ov-title', { cats: titleRows.map(r => TA.playerShort(T, r.pid)), series: [{ name: 'Title', data: titleRows.map(r => r.p) }], horizontal: true, labels: true, fmt: v => TA.pct(v, 0), hrefs: titleRows.map(r => TA.playerHref(T, r.pid)), labelWidth: 120, valName: 'Title probability' });
    }
    if (eloKeys.length) {
      const draw = k => {
        const rows = (info.elo_top || {})[k] || [];
        const lo = Math.min.apply(null, rows.map(r => r[1]));
        QKC.bar('#ov-elo', { cats: rows.map(r => TA.playerShort(T, r[0]) + (isNum(TA.playerRank(T, r[0])) ? ' · No. ' + TA.playerRank(T, r[0]) : '')), series: [{ name: (k === 'all' ? 'Overall' : TA.surfaceLabel(k)) + ' Elo', data: rows.map(r => Math.round(r[1])) }],
          horizontal: true, labels: true, fmt: v => TA.num(v, 0), min: Math.floor((lo - 120) / 50) * 50, colors: rows.map(() => k === 'all' ? null : TA.surfaceColour(k)).map(c => c || undefined),
          hrefs: rows.map(r => TA.playerHref(T, r[0])), labelWidth: 150, label: 'Elo top 10', valName: (k === 'all' ? 'Overall' : TA.surfaceLabel(k)) + ' Elo' });
      };
      draw(eloKeys[0]);
      QK.chips(document.getElementById('ov-sf'), v => { if (v && v[0]) draw(v[0]); });
    }
    if (isCurrent && raceRows.length) {
      if (Object.keys(raceMk).length) QKC.dumbbell('#ov-race', { rows: raceRows.map(r => ({ label: TA.playerShort(T, r[0]) + ' · ' + TA.num(r[3], 0) + ' pts', a: r[1], b: isNum(raceMk[r[0]]) ? raceMk[r[0]] : r[1], href: TA.playerHref(T, r[0]) })), aName: 'Model', bName: 'Market', valName: 'Chance to qualify', labelWidth: 170 });
      else QKC.bar('#ov-race', { cats: raceRows.map(r => TA.playerShort(T, r[0])), series: [{ name: 'Qualify', data: raceRows.map(r => r[1]) }], horizontal: true, labels: true, fmt: v => TA.pct(v, 0), max: 1, hrefs: raceRows.map(r => TA.playerHref(T, r[0])), labelWidth: 130, valName: 'Chance to qualify' });
    }
    if (gaps.length) QKC.dumbbell('#ov-gaps', { rows: gaps.map(g => ({ label: g.label, a: g.a, b: g.b, sub: g.sub, href: g.href })), aName: 'Model', bName: 'Market', labelWidth: 210 });
    if (live.length) TA.interval(() => { if (document.visibilityState === 'visible') TA.go(location.hash || '#/' + T); }, 90000);
    TA.setMeta(race && race.n_sims ? TA.num(race.n_sims, 0) + ' season simulations' : '');
  });
}

TA.route('hub', render);
})(window.TA);
