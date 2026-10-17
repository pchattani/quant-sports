/* The Quant Paddock — the hub (#/).
 *
 *   header band: the next race, a live countdown to its next session, the weekend
 *                schedule in the viewer's local time, the last winner
 *   next race forecast (races/<next>.json), title odds against the market,
 *   standings with points sparklines, the championship chart, car pace at the
 *   latest round, quick links.
 *
 * Reads index.json, <year>/season.json, <year>/races/<next>.json, markets.json. */
(function (PD) {
'use strict';

const esc = PD.esc;
const SESSION_LABEL = { fp1: 'Practice 1', fp2: 'Practice 2', fp3: 'Practice 3', sprint_quali: 'Sprint qualifying', sprint_shootout: 'Sprint shootout',
  sprint: 'Sprint', quali: 'Qualifying', qualifying: 'Qualifying', race: 'Grand Prix' };
const SESSION_LEN_MIN = { fp1: 60, fp2: 60, fp3: 60, sprint_quali: 45, sprint_shootout: 45, sprint: 40, quali: 60, qualifying: 60, race: 120 };

function sessionsOf(next) {
  const s = (next && next.sessions) || {};
  return Object.keys(s).filter(k => s[k]).map(k => ({ key: k, label: SESSION_LABEL[k] || PD.titleCase(k), t: PD.parseDate(s[k]), iso: s[k] }))
    .filter(x => x.t).sort((a, b) => a.t - b.t);
}

/* An inline SVG sparkline of cumulative points. */
function spark(vals, colour, w, h) {
  const v = (vals || []).filter(PD.isNum);
  const W = w || 96, H = h || 22;
  if (v.length < 2) return '<svg class="spark" width="' + W + '" height="' + H + '"></svg>';
  const max = Math.max.apply(null, v) || 1;
  const pts = v.map((y, i) => (i * (W - 2) / (v.length - 1) + 1).toFixed(1) + ',' + (H - 2 - (y / max) * (H - 4)).toFixed(1)).join(' ');
  return '<svg class="spark" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '"><polyline fill="none" stroke="' + esc(colour) + '" stroke-width="1.6" stroke-linejoin="round" points="' + pts + '"/></svg>';
}

function tile(v, label) { return '<div class="hb-tile"><span class="hb-v">' + v + '</span><span class="hb-l">' + esc(label) + '</span></div>'; }

// ── header band ────────────────────────────────────────────────────────────

function renderBand(el, idx, season) {
  const next = idx && idx.next, last = idx && idx.last;
  let left;
  if (next) {
    const list = sessionsOf(next);
    const circ = next.circuit || {};
    left = '<div class="card"><div class="pad">' +
      '<div class="hb-kicker">Next up · ' + esc(next.year) + ' round ' + esc(next.round) + '</div>' +
      '<div class="hb-race"><a href="' + PD.raceHref(next.year, next.round) + '" style="color:inherit">' + esc(next.name) + '</a></div>' +
      '<div class="hb-circ">' + PD.circuitLink(circ.id, circ.name) + (circ.country ? ' · ' + esc(circ.country) : '') + '</div>' +
      '<div class="hb-main"><div class="cd-box" id="hub-countdown"></div>' +
      '<div><div class="sched" id="hub-sched"></div><div class="sched-tz">Times in your timezone (' + esc(tzName()) + ').</div></div></div>' +
      '</div></div>';
  } else {
    const champ = idx && idx.seasons_meta && idx.seasons_meta[String(idx.current_season)];
    left = '<div class="card"><div class="pad"><div class="hb-kicker">' + esc(idx ? idx.current_season : '') + ' season</div>' +
      '<div class="hb-race">The season is complete</div>' +
      (champ && champ.champion ? '<div class="hb-circ">Champion: ' + PD.driverLink(champ.champion) + (champ.constructors_champion ? ' · Constructors: ' + PD.teamLink(champ.constructors_champion) : '') + '</div>' : '') +
      '</div></div>';
  }
  let right = '<div class="card"><div class="card-header">Last race</div><div class="pad">';
  if (last && last.winner) {
    const team = last.winner_team || (PD.NAMES.drivers[last.winner] || {}).team;
    right += '<div class="hb-kicker">' + esc(last.name) + ' · ' + esc(PD.fmtDate(last.date, { year: false })) + '</div>' +
      '<div class="lw-name">' + (team ? PD.teamBar(team) : '') + PD.driverLink(last.winner) + '</div>' +
      '<div class="lw-sub">' + (team ? esc(PD.teamName(team)) + ' · ' : '') + 'winner · <a href="' + PD.raceHref(last.year, last.round) + '">race centre →</a></div>';
  } else {
    right += '<div class="muted-inline">No race run yet this season.</div>';
  }
  if (PD.ok(season)) {
    const st = (season.standings || {}).drivers || [];
    const ct = (season.standings || {}).constructors || [];
    const lead = st[0], second = st[1];
    right += '<div class="hub-mini-tiles">' +
      tile(lead ? esc(PD.driverCode(lead.driver)) + ' ' + PD.num(lead.points, 0) : '—', 'Drivers’ leader') +
      tile(lead && second ? '+' + PD.num(lead.points - second.points, 0) : '—', 'Lead over ' + (second ? PD.driverCode(second.driver) : 'P2')) +
      tile((season.rounds_done || 0) + ' / ' + (season.rounds_total || 0), 'Rounds run') +
      '</div>' + (ct[0] ? '<div class="lw-sub" style="margin-top:8px">Constructors: ' + PD.teamLink(ct[0].team) + ' ' + PD.num(ct[0].points, 0) + ' pts' + (ct[1] ? ', ' + PD.num(ct[0].points - ct[1].points, 0) + ' clear' : '') + '</div>' : '');
  }
  right += '</div></div>';
  el.innerHTML = left + right;
  if (next) {
    const list = sessionsOf(next);
    const tick = () => {
      const now = Date.now();
      const upcoming = list.find(s => s.t.getTime() > now);
      const live = list.find(s => s.t.getTime() <= now && now < s.t.getTime() + (SESSION_LEN_MIN[s.key] || 60) * 60000);
      const cd = document.getElementById('hub-countdown');
      if (!cd) return;
      if (live) {
        cd.innerHTML = '<div class="cd-label">Now</div><div class="cd-value cd-live"><span class="live-dot"></span> ' + esc(live.label) + '</div><div class="cd-when">Started ' + esc(PD.fmtTime(live.iso)) + '</div>';
      } else if (upcoming) {
        cd.innerHTML = '<div class="cd-label">' + esc(upcoming.label) + ' starts in</div><div class="cd-value">' + esc(PD.countdown(upcoming.iso, now)) + '</div>' +
          '<div class="cd-when">' + esc(PD.fmtDate(upcoming.iso, { year: false, time: true })) + '</div>';
      } else {
        cd.innerHTML = '<div class="cd-label">Weekend</div><div class="cd-value" style="font-size:1.2rem">Sessions complete</div><div class="cd-when">Results arrive with the next build.</div>';
      }
      const sch = document.getElementById('hub-sched');
      if (sch) sch.innerHTML = list.map(s => {
        const past = s.t.getTime() + (SESSION_LEN_MIN[s.key] || 60) * 60000 < now;
        const isNext = upcoming && s.key === upcoming.key;
        return '<div class="sched-row' + (past ? ' past' : '') + (isNext || (live && live.key === s.key) ? ' next' : '') + '"><span class="sched-day">' + esc(PD.fmtDate(s.iso, { year: false })) + '</span>' +
          '<span class="sched-name">' + esc(s.label) + '</span><span class="sched-time">' + esc(PD.fmtTime(s.iso)) + '</span></div>';
      }).join('') || '<div class="muted-inline">Session times not published yet.</div>';
    };
    tick();
    PD.interval(tick, 1000);
  }
}

function tzName() {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || 'local'; } catch (e) { return 'local'; }
}

// ── next race forecast ─────────────────────────────────────────────────────

function forecastTable(sim, teamOf, limit, market) {
  const ds = (sim && sim.drivers) || {};
  const ids = Object.keys(ds).sort((a, b) => (ds[b].p_win - ds[a].p_win) || (ds[a].exp_pos - ds[b].exp_pos));
  if (!ids.length) return PD.muted('No forecast for this race yet.');
  const maxW = Math.max.apply(null, ids.map(id => ds[id].p_win || 0)) || 1;
  const rows = ids.slice(0, limit || ids.length).map((id, i) => {
    const d = ds[id], team = teamOf(id), col = PD.teamColour(team);
    return { cells: [
      { v: i + 1, cls: 'num muted-inline' },
      { v: PD.driverName(id), html: PD.driverLink(id, { team: team }) + '<span class="drv-code">' + esc(PD.driverCode(id)) + '</span>' },
      { v: d.p_win, html: PD.probCell(d.p_win, col, Math.max(maxW, 0.25)) },
      { v: d.p_podium, html: PD.pct(d.p_podium), align: 'right' },
      { v: d.p_points, html: PD.pct(d.p_points), align: 'right' },
      { v: d.exp_pos, html: PD.num(d.exp_pos, 1), align: 'right' }
    ].concat(market ? [{ v: market[id], html: PD.isNum(market[id]) ? PD.pct(market[id]) : '<span class="muted-inline">—</span>', align: 'right' }] : []) };
  });
  return PD.tableHTML([{ label: '#', align: 'right' }, { label: 'Driver' }, { label: 'P(win)' }, { label: 'P(podium)', align: 'right' }, { label: 'P(points)', align: 'right' }, { label: 'Exp. pos', align: 'right', title: 'Expected finishing position' }]
    .concat(market ? [{ label: 'Market', align: 'right', title: 'Market price to win the race' }] : []), rows, { compact: true });
}

// ── title odds ─────────────────────────────────────────────────────────────

function titleRows(season, markets) {
  const ch = PD.ok(season) && season.championship ? season.championship.drivers || {} : {};
  const mk = (markets && markets.drivers_title) || {};
  const prices = mk.available ? (mk.prices || {}) : {};
  const ids = Object.keys(ch).filter(id => (ch[id].p_title || 0) >= 0.0005 || (prices[id] || 0) >= 0.001).sort((a, b) => (ch[b] ? ch[b].p_title : 0) - (ch[a] ? ch[a].p_title : 0));
  return ids.map(id => {
    const model = ch[id] ? ch[id].p_title : (mk.model || {})[id];
    const market = prices[id];
    let edge = (mk.edge || {})[id];
    if (!PD.isNum(edge) && PD.isNum(model) && PD.isNum(market) && market > 0) edge = model / market - 1;
    return { id: id, model: model, market: market, edge: edge, elim: !!(ch[id] && ch[id].eliminated), clinched: !!(ch[id] && ch[id].clinched) };
  });
}

function titleTable(rows, markets) {
  if (!rows.length) return PD.muted('The championship simulation has not run yet.');
  const hasMarket = rows.some(r => PD.isNum(r.market));
  const cols = [{ label: 'Driver' }, { label: 'Model' }].concat(hasMarket ? [{ label: 'Market', align: 'right' }, { label: 'Edge', align: 'right', title: 'Model against market, relative: model / market − 1' }] : []);
  const out = rows.slice(0, 10).map(r => {
    const team = (PD.NAMES.drivers[r.id] || {}).team;
    const cells = [
      { v: PD.driverName(r.id), html: PD.driverLink(r.id, { team: team }) + (r.clinched ? ' ' + PD.chip('champion', 'ok') : r.elim ? ' ' + PD.chip('out', 'bad') : '') },
      { v: r.model, html: PD.probCell(r.model, PD.teamColour(team)) }
    ];
    if (hasMarket) {
      cells.push({ v: r.market, html: PD.pct(r.market), align: 'right' });
      cells.push({ v: r.edge, html: PD.isNum(r.edge) ? '<span class="' + (r.edge >= 0 ? 'edge-pos' : 'edge-neg') + '">' + PD.signed(r.edge * 100, 0) + '%</span>' : '—', align: 'right' });
    }
    return { cells: cells };
  });
  const mk = (markets && markets.drivers_title) || {};
  return PD.tableHTML(cols, out, { compact: true }) +
    '<div class="section-note">' + (hasMarket ? 'Market: ' + esc((mk.sources || []).join(', ') || 'prediction markets') + (PD.isNum(mk.implied_total) ? '; prices sum to ' + PD.pct(mk.implied_total, 1) : '') + '. ' : 'No market price available. ') +
    '<a href="#/markets">Markets →</a></div>';
}

// ── standings with sparklines ──────────────────────────────────────────────

function standingsSnapshot(season, kind) {
  if (!PD.ok(season)) return PD.muted('Standings not built yet.');
  const isD = kind !== 'constructors';
  const list = ((season.standings || {})[isD ? 'drivers' : 'constructors'] || []).slice(0, 10);
  if (!list.length) return PD.muted('No standings yet.');
  const prog = ((season.progression || {})[isD ? 'drivers' : 'constructors']) || {};
  const leadPts = list[0].points;
  return list.map(r => {
    const id = isD ? r.driver : r.team;
    const team = isD ? r.team : r.team;
    return '<div class="st-row"><span class="st-rank">' + r.pos + '</span>' +
      '<span class="st-name">' + (isD ? PD.driverLink(id, { team: team }) : PD.teamLink(id)) + '</span>' +
      '<span>' + spark(prog[id], PD.teamColour(team)) + '</span>' +
      '<span class="st-pts">' + PD.num(r.points, 0) + (r.pos > 1 ? '<span class="st-gap">−' + PD.num(leadPts - r.points, 0) + '</span>' : '<span class="st-gap">leader</span>') + '</span></div>';
  }).join('') + '<a class="more-link" href="#/season/' + season.year + '">Full standings, title odds and magic numbers →</a>';
}

// ── car pace ───────────────────────────────────────────────────────────────

function paceRanking(season) {
  const cp = PD.ok(season) && season.car_pace ? season.car_pace.race || {} : {};
  let lastRound = 0;
  Object.keys(cp).forEach(t => (cp[t] || []).forEach(e => { if (e.round > lastRound && PD.isNum(e.effect)) lastRound = e.round; }));
  const rows = Object.keys(cp).map(t => { const e = (cp[t] || []).find(x => x.round === lastRound); return e && PD.isNum(e.effect) ? { team: t, effect: e.effect, se: e.se } : null; })
    .filter(Boolean).sort((a, b) => a.effect - b.effect);
  if (!rows.length) return { html: PD.muted('Car pace is estimated once a race has lap data.'), round: null };
  const max = Math.max.apply(null, rows.map(r => Math.abs(r.effect))) || 1;
  const html = rows.map((r, i) => {
    const w = Math.abs(r.effect) / max * 50;
    const left = r.effect < 0 ? 50 - w : 50;
    return '<div class="pace-row"><span class="st-rank">' + (i + 1) + '</span><span class="pace-name">' + PD.teamLink(r.team) + '</span>' +
      '<span class="pace-track"><span class="pace-mid"></span><span class="pace-fill" style="left:' + left.toFixed(1) + '%;width:' + w.toFixed(1) + '%;background:' + esc(PD.teamColour(r.team)) + '"></span></span>' +
      '<span class="pace-v ' + (r.effect < 0 ? 'edge-pos' : 'edge-neg') + '">' + PD.signed(r.effect, 2) + '%</span></div>';
  }).join('');
  return { html: html, round: lastRound };
}

// ── page ───────────────────────────────────────────────────────────────────

function render(el) {
  el.innerHTML = '<div class="hub-band" id="hub-band"><div class="card"><div class="muted">Loading…</div></div></div>' +
    '<div class="hub-grid"><div>' +
      '<div class="card" id="hub-forecast"><div class="card-header">Next race forecast <span class="card-sub" id="hub-forecast-sub"></span></div><div id="hub-forecast-body">' + PD.muted('Loading…') + '</div></div>' +
      '<div class="card"><div class="card-header">Championship <span class="card-sub">Probability of the drivers’ title; the white tick is the market.</span></div><div id="hub-champ-chart" style="min-height:240px"></div></div>' +
      '<div class="card"><div class="card-header">Car pace <span class="card-sub" id="hub-pace-sub">Race pace, % of a lap against the field; negative is faster.</span></div><div id="hub-pace" style="padding:6px 0"></div></div>' +
    '</div><div>' +
      '<div class="card"><div class="card-header">Title odds v market</div><div id="hub-title"></div></div>' +
      '<div class="card"><div class="card-header">Standings <span class="card-sub">Points progression in each sparkline.</span></div>' +
        '<div class="toggle-row"><button class="tbtn active" data-k="drivers">Drivers</button><button class="tbtn" data-k="constructors">Constructors</button></div><div id="hub-standings"></div></div>' +
      '<div class="card"><div class="card-header">Explore</div><div class="pad hub-links" id="hub-links"></div></div>' +
    '</div></div>';

  const idx = PD.index() || {};
  const year = idx.current_season || PD.currentSeason();
  PD.setMeta(esc(year) + ' season');
  const next = idx.next;
  const raceP = next ? PD.load(next.year + '/races/' + next.round + '.json') : Promise.resolve(null);
  const set = (id, html) => { const n = document.getElementById(id); if (n && el.isConnected) n.innerHTML = html; };

  set('hub-links', [
    ['#/season/' + year, 'Season ' + year, 'Standings, title odds, car pace, calendar'],
    ['#/races/' + year, 'Races', 'Every round with its race centre'],
    ['#/drivers', 'Drivers', 'Savant-style percentiles and race logs'],
    ['#/teams', 'Teams', 'Car pace, pit crews, reliability'],
    ['#/lab', 'Lab', 'Plot any two driver metrics'],
    ['#/compare', 'Compare', 'Two drivers or two teams side by side'],
    ['#/markets', 'Markets', 'The model against the prices'],
    ['#/calibration', 'Calibration', 'How good the forecasts have been'],
    ['#/circuits', 'Circuits', 'Profiles, history and records'],
    ['#/methodology', 'Methodology', 'How the models work']
  ].map(l => '<a href="' + l[0] + '"><b>' + esc(l[1]) + '</b><span>' + esc(l[2]) + '</span></a>').join(''));

  return Promise.all([PD.load(year + '/season.json'), PD.load('markets.json'), raceP]).then(arr => {
    if (!el.isConnected) return;
    const season = arr[0], markets = arr[1], race = arr[2];
    const band = document.getElementById('hub-band');
    if (band) renderBand(band, idx, season);

    // next race forecast
    const teamOf = id => (PD.NAMES.drivers[id] || {}).team || null;
    if (!next) set('hub-forecast-body', PD.muted('No race left this season.'));
    else if (!PD.ok(race) || !race.forecast) set('hub-forecast-body', PD.muted('The forecast for ' + esc(next.name) + ' is not built yet' + (race && race.reason ? ' (' + esc(race.reason) + ')' : '') + '.'));
    else {
      const post = race.forecast.post_quali;
      const sim = post && post.drivers && Object.keys(post.drivers).length ? post : race.forecast.pre_quali;
      set('hub-forecast-sub', esc(next.name) + ' · ' + (sim === post ? 'after qualifying' : 'before qualifying') + (PD.isNum(sim && sim.p_sc) ? ' · P(safety car) ' + PD.pct(sim.p_sc, 0) : ''));
      const nr = markets && markets.next_race;
      const mkt = nr && nr.available !== false && nr.year === next.year && nr.round === next.round && nr.prices && Object.keys(nr.prices).length ? nr.prices : null;
      set('hub-forecast-body', forecastTable(sim, teamOf, 10, mkt) + '<a class="more-link" href="' + PD.raceHref(next.year, next.round) + '">Full forecast and position distribution →</a>');
      PD.sortable(document.getElementById('hub-forecast-body'));
    }

    // title odds and chart
    const rows = titleRows(season, markets);
    if (PD.ok(season) && !season.championship) {
      set('hub-title', PD.muted('The ' + esc(year) + ' championship is decided.'));
      set('hub-champ-chart', PD.muted('No simulation for a finished season.'));
    } else {
      set('hub-title', titleTable(rows, markets));
      PD.sortable(document.getElementById('hub-title'));
      PD.charts.probBars('hub-champ-chart', rows.filter(r => (r.model || 0) >= 0.001).slice(0, 10).map(r => ({
        label: PD.driverSurname(r.id), p: r.model, market: r.market, colour: PD.teamColour((PD.NAMES.drivers[r.id] || {}).team)
      })), { emptyText: 'The championship simulation has not run yet.' });
    }

    // standings
    let kind = 'drivers';
    const draw = () => set('hub-standings', standingsSnapshot(season, kind));
    draw();
    el.querySelectorAll('.toggle-row .tbtn').forEach(b => b.addEventListener('click', () => {
      kind = b.dataset.k;
      el.querySelectorAll('.toggle-row .tbtn').forEach(x => x.classList.toggle('active', x === b));
      draw();
    }));

    // pace
    const pr = paceRanking(season);
    set('hub-pace', pr.html);
    if (pr.round) {
      const cal = (PD.ok(season) && season.calendar || []).find(c => c.round === pr.round);
      set('hub-pace-sub', 'Race pace at ' + esc(cal ? cal.name : 'round ' + pr.round) + ', % of a lap against the field; negative is faster.');
    }
  });
}

PD.route('hub', render);
PD.hub = { spark: spark, forecastTable: forecastTable, sessionsOf: sessionsOf };
})(window.PD);
