/* The Quant Hardwood — teams: the index (#/<L>/teams) and the team page (#/<L>/team/<tid>).
 *
 * Data: data/<L>/<S>/teams.json (catalogue, percentiles, game log, roster, lineups,
 * rotation, on/off, shot profile for and against, injuries, odds), data/<L>/<S>/season.json
 * (ratings with standard errors, rating paths, standings, the season simulation, Elo,
 * win totals, schedule difficulty), data/<L>/<S>/players.json (names, HPM). */
(function (HW) {
'use strict';

const FX = () => HW.fx;
const HEAD_PREFS = ['net', 'net_rtg', /^net/, 'ortg', /^o_?rtg|^off_?rtg/, 'drtg', /^d_?rtg|^def_?rtg/, 'pace', /pace/, 'efg', /efg/, 'xpts_diff', /xpts|luck/, 'clutch_net', /clutch/];

function simOf(season) { const s = (season || {}).sim || {}; return s.teams && typeof s.teams === 'object' ? s.teams : s; }
function standOf(season) {
  const out = {};
  const st = (season || {}).standings || {};
  Object.keys(st).forEach(conf => (Array.isArray(st[conf]) ? st[conf] : []).forEach(r => { if (r && r.team) out[r.team] = Object.assign({ conf: conf }, r); }));
  return out;
}
function ratingOf(season, tid) { return (((season || {}).ratings) || {})[tid] || {}; }
function eloOf(season, tid) { const e = (((season || {}).elo) || {})[tid]; return FX().isNum(e) ? e : (e && FX().isNum(e.elo) ? e.elo : e && FX().isNum(e.rating) ? e.rating : null); }

// ── index ──────────────────────────────────────────────────────────────────

function renderTeams(el, params, state) {
  const fx = FX(), L = fx.L(params, state);
  return fx.ready().then(() => {
    const S = fx.S(params, state, L);
    el.innerHTML = '<div id="tm-cards">' + fx.muted('Loading…') + '</div>' +
      '<div class="grid-2"><div class="card"><div class="card-header">Offence against defence <span class="card-sub">Opponent- and venue-adjusted points per 100 possessions. Up and right is better; the diagonals are net rating.</span></div><div id="tm-od" style="height:440px"></div></div>' +
      '<div class="card"><div class="card-header">Net rating through the season <span class="card-sub">The Kalman path after each game.</span></div><div id="tm-paths" style="height:440px"></div></div></div><div id="tm-table"></div>';
    return fx.season(L, S).then(res => {
      if (!fx.alive(el)) return;
      const teams = res[1], season = res[2];
      const T = (fx.ok(teams) && teams.teams) || {};
      const R = (fx.ok(season) && season.ratings) || {};
      const SIM = simOf(season), ST = standOf(season);
      const ids = Array.from(new Set(Object.keys(T).concat(Object.keys(R)).concat(Object.keys(ST)))).filter(id => !/^-/.test(id) && (T[id] || R[id] || ((ST[id] || {}).w || 0) + ((ST[id] || {}).l || 0) > 0));
      if (!ids.length) { document.getElementById('tm-cards').innerHTML = fx.card('Teams ' + fx.seasonLabel(L, S), '', fx.notBuilt('The ' + fx.seasonLabel(L, S) + ' team catalogue', teams)); return; }
      const net = id => (fx.isNum((R[id] || {}).net) ? R[id].net : fx.isNum(((T[id] || {}).values || {}).net) ? T[id].values.net : -99);
      ids.sort((a, b) => net(b) - net(a));
      document.getElementById('tm-cards').innerHTML = '<div class="card"><div class="card-header">Teams ' + fx.esc(fx.seasonLabel(L, S)) + ' <span class="card-sub">Ordered by net rating. Chances from the season simulation' + (fx.isNum(((season || {}).sim || {}).n_sims) ? ' (' + Number(season.sim.n_sims).toLocaleString() + ' runs)' : '') + '.</span></div>' +
        '<div class="pg-grid-cards hf-cards">' + ids.map((id, i) => {
          const t = T[id] || {}, r = R[id] || {}, s = ST[id] || {}, sim = SIM[id] || {};
          return '<a class="pg-card" href="' + fx.teamHref(L, id) + '" style="--team:' + fx.esc(fx.teamColour(L, id)) + '"><div class="pg-card-name">' + (i + 1) + '. ' + fx.esc(t.name || fx.teamName(L, id)) + '</div>' +
            '<div class="pg-card-sub">' + (fx.has(s.w) ? s.w + '-' + s.l : '0-0') + (s.conf ? ' · ' + fx.esc(s.conf) : '') + (fx.isNum(s.seed) ? ' · seed ' + s.seed : '') + '</div>' +
            '<div class="pg-card-stats"><span>Net<strong>' + fx.signed(r.net, 1) + '</strong></span><span>ORtg<strong>' + fx.num(r.off, 1) + '</strong></span><span>DRtg<strong>' + fx.num(r.def, 1) + '</strong></span>' +
            (fx.isNum(sim.p_playoffs) ? '<span>Playoffs<strong>' + fx.pct(sim.p_playoffs, 0) + '</strong></span>' : '') + (fx.isNum(sim.p_title) ? '<span>Title<strong>' + fx.pct(sim.p_title) + '</strong></span>' : '') + '</div></a>';
        }).join('') + '</div></div>';
      // Offence v defence scatter.
      const withR = ids.filter(id => fx.isNum((R[id] || {}).off) && fx.isNum((R[id] || {}).def));
      if (withR.length) {
        const xs = withR.map(id => R[id].off), ys = withR.map(id => R[id].def);
        QKC.scatter('#tm-od', { points: withR.map(id => ({ x: R[id].off, y: R[id].def, name: fx.teamName(L, id) + ': net ' + fx.signed(R[id].net, 1) + (fx.isNum(R[id].se_net) ? ' ± ' + fx.num(R[id].se_net, 1) : ''),
          label: fx.teamAbbr(L, id), color: fx.teamColour(L, id), href: fx.teamHref(L, id), size: 13 })), labelAll: true, yInverse: true, diagonal: true,
          xName: 'Offensive rating (points per 100)', yName: 'Defensive rating (allowed per 100; better is higher)', xFmt: v => fx.num(v, 0), yFmt: v => fx.num(v, 0), label: 'Offence against defence' });
      } else document.getElementById('tm-od').innerHTML = fx.muted('No ratings yet.');
      const paths = (season || {}).rating_paths || {};
      const ptr = ids.filter(id => (paths[id] || []).length);
      if (ptr.length) QKC.line('#tm-paths', { xType: 'time', series: ptr.map(id => ({ name: fx.teamAbbr(L, id), color: fx.teamColour(L, id), width: 1.6, data: paths[id].map(r => [Date.parse(r.date), r.net]) })),
        xName: 'Date', yName: 'Net rating (points per 100 possessions)', xFmt: fx.dateFmt, xLabel: fx.dateFmt, yFmt: v => fx.signed(v, 1), ref: { y: 0 }, endLabels: ptr.length <= 16, label: 'Net rating through the season' });
      else document.getElementById('tm-paths').innerHTML = fx.muted('No rating paths yet: they start with the first games.');
      // Metric table.
      const metrics = ((teams && teams.metrics) || []).filter(m => !HW.ui.HIDE_TEAM[m.key]);
      const heads = fx.headline(metrics, HEAD_PREFS, 9, true);
      if (Object.keys(T).length && heads.length) {
        document.getElementById('tm-table').innerHTML = fx.card('Team metrics', 'Value and league percentile (100 = best; ↓ metrics already flipped) on headline metrics. The full catalogue of ' + metrics.length + ' metrics is on each team page.',
          HW.tableHTML([{ label: '#', align: 'right' }, { label: 'Team' }, { label: 'W-L', align: 'right' }].concat(heads.map(m => ({ label: fx.shortLabel(m.label) + (m.lower ? ' ↓' : ''), align: 'right', title: m.desc || m.label }))),
            ids.filter(id => T[id]).map((id, i) => ({ _href: fx.teamHref(L, id), cells: [i + 1, { v: fx.teamName(L, id), html: fx.teamLink(L, id) }, { v: (ST[id] || {}).w || 0, html: fx.has((ST[id] || {}).w) ? ST[id].w + '-' + ST[id].l : '—' }]
              .concat(heads.map(m => ({ v: fx.isNum((T[id].values || {})[m.key]) ? T[id].values[m.key] : -1e9, html: '<span class="hf-val">' + fx.fmt(m, (T[id].values || {})[m.key]) + '</span> ' + fx.pill((T[id].pct || {})[m.key]) }))) })), { compact: true, sticky: true }));
        HW.sortable('tm-table');
      }
    });
  });
}

// ── team page ──────────────────────────────────────────────────────────────

function renderTeam(el, params, state) {
  const fx = FX(), L = fx.L(params, state);
  const tid = String(params.id || (params.rest || [])[0] || '');
  el.innerHTML = fx.muted('Loading…');
  return fx.ready().then(() => {
    const S = fx.S(params, state, L);
    const embed = ((params.query || {}).embed) === 'detail';
    return fx.season(L, S).then(res => { if (fx.alive(el)) drawTeam(el, L, S, tid, res[0], res[1], res[2], embed); });
  });
}

function drawTeam(el, L, S, tid, cat, teams, season, embed) {
  const fx = FX(), C = fx.C;
  const T = (fx.ok(teams) && teams.teams) || {};
  const t = T[tid] || null;
  const metrics = ((teams || {}).metrics || []).filter(m => !HW.ui.HIDE_TEAM[m.key]);
  const name = (t && t.name) || fx.teamName(L, tid);
  const colour = fx.teamColour(L, tid);
  const info = fx.team(L, tid) || {};
  const R = (fx.ok(season) && season.ratings) || {};
  const r = R[tid] || {};
  const ST = standOf(season), s = ST[tid] || {};
  const sim = simOf(season)[tid] || {};
  const odds = (t && t.odds) || {};
  const mk = odds.market || {};
  const P = (fx.ok(cat) && cat.players) || {};
  const rivals = Object.keys(R).filter(k => k !== tid && fx.isNum(R[k].net) && fx.isNum(r.net)).sort((a, b) => Math.abs(R[a].net - r.net) - Math.abs(R[b].net - r.net));

  let h = '<div class="pg-head" style="--team:' + fx.esc(colour) + '"><div class="pg-num" style="font-size:1.05rem">' + fx.esc(fx.teamAbbr(L, tid)) + '</div><div class="pg-body"><h2>' + fx.esc(name) + '</h2>' +
    '<div class="pg-sub">' + (info.conference || s.conf ? '<span>' + fx.esc(info.conference || s.conf) + (info.division ? ' · ' + fx.esc(info.division) : '') + '</span>' : '') +
    (fx.has(s.w) ? '<span>' + s.w + '-' + s.l + (fx.isNum(s.seed) ? ', seed ' + s.seed : '') + '</span>' : '') + '<span class="chip">' + fx.esc(L.toUpperCase() + ' ' + fx.seasonLabel(L, S)) + '</span></div></div>' +
    '<div class="pg-links">' + (rivals[0] ? '<a href="' + fx.href(L, 'compare/teams/' + encodeURIComponent(tid) + '/' + encodeURIComponent(rivals[0])) + '">Compare with ' + fx.esc(fx.teamAbbr(L, rivals[0])) + ' →</a>' : '') +
    '<a href="' + fx.href(L, 'season/' + S) + '">Standings →</a><a href="' + fx.href(L, 'teams') + '">All teams →</a></div></div>';
  if (!t && !r.games && !s.team) { el.innerHTML = h + fx.card('This season', '', fx.muted(fx.esc(name) + ' is not in the ' + fx.esc(fx.seasonLabel(L, S)) + ' data' + (fx.ok(teams) ? '' : ' (the team catalogue is not built yet)') + '.')); return; }

  const vals = (t && t.values) || {};
  const pace = fx.isNum(r.pace) ? r.pace : vals[fx.pick(vals, ['pace', /pace/]) || ''];
  h += '<div class="kpi-grid six">' + [
    fx.tile('Record', fx.has(s.w) ? s.w + '-' + s.l : '—', [fx.isNum(s.seed) ? fx.ordinal(s.seed) + ' in the ' + fx.esc(s.conf || 'conference') : '', fx.isNum(sim.exp_w) ? 'projected ' + fx.num(sim.exp_w, 1) + ' wins (' + fx.num(sim.w_p05, 0) + '–' + fx.num(sim.w_p95, 0) + ')' : ''].filter(Boolean).join(' · ')),
    fx.tile('Net rating', fx.signed(r.net, 1) + (fx.isNum(r.se_net) ? ' <span class="hf-se">± ' + fx.num(r.se_net, 1) + '</span>' : ''), fx.isNum(r.rank) ? fx.ordinal(r.rank) + ' in the league · ' + (r.games || 0) + ' games' : 'per 100 possessions'),
    fx.tile('Offence', fx.num(r.off, 1), 'points per 100, adjusted'),
    fx.tile('Defence', fx.num(r.def, 1), 'allowed per 100, adjusted'),
    fx.tile('Pace', fx.num(pace, 1), 'possessions per 48' + (L === 'wnba' ? ' (40 in the WNBA)' : '')),
    fx.tile('Title', fx.pct(fx.has(sim.p_title) ? sim.p_title : odds.p_title), 'playoffs ' + fx.pct(fx.has(sim.p_playoffs) ? sim.p_playoffs : odds.p_playoffs, 0))
  ].join('') + '</div>';
  const curS = fx.current(L);
  h += '<div class="card"><div class="card-header">Strengths and needs <span class="card-sub">' + (Number(S) === Number(curS) ? 'Each position group and unit graded against the league on projected value (rest-of-season HPM × projected minutes, in WAR over a full season); the three strongest and weakest, with ranked trade targets for each weakness.' : 'Built for the current season (' + fx.esc(fx.seasonLabel(L, curS)) + ') only.') + '</span></div><div id="tp-needs">' + fx.muted(Number(S) === Number(curS) ? 'Loading…' : '<a href="' + fx.teamHref(L, tid, curS) + '">' + fx.esc(name) + ' in ' + fx.esc(fx.seasonLabel(L, curS)) + ' →</a>') + '</div></div>';
  if (Number(S) === Number(curS)) h += '<div class="card"><div class="card-header">Ledger <span class="card-sub">This team\'s trades in the last 12 months, rated on four-season value (at the time, realised since, today\'s view), and every transaction ESPN lists.</span></div><div id="tp-ledger">' + fx.muted('Loading…') + '</div></div>';
  h += '<div class="card"><div class="card-header">Rating path <span class="card-sub">Net rating per 100 after each game from the Kalman filter, ±1 standard error shaded; dots are game results (green won, red lost).</span></div><div id="tp-path" style="height:320px"></div></div>';
  h += '<div class="grid-2"><div class="card"><div class="card-header">Four factors <span class="card-sub">Both ends, with league percentile and the league median.</span></div><div id="tp-ff"></div></div>' +
    '<div class="card"><div class="card-header">Season chances <span class="card-sub">Our chances from the season simulation.</span></div><div id="tp-odds"></div></div></div>';
  h += '<div class="card"><div class="card-header">Shot profile <span class="card-sub">Share of shots and points per shot by zone, coloured against the league average (red better for the side shown). Left: their shots. Right: what they allow.</span></div>' +
    '<div class="grid-2"><div><div id="tp-sp-for" class="hf-court"></div><div id="tp-sp-for-t"></div></div><div><div id="tp-sp-ag" class="hf-court"></div><div id="tp-sp-ag-t"></div></div></div></div>';
  h += '<div class="card"><div class="card-header">Roster <span class="card-sub">Everyone who played, by minutes. HPM per 100 possessions, offence and defence.</span></div><div id="tp-roster"></div></div>';
  h += '<div class="grid-2"><div class="card"><div class="card-header">Lineups <span class="card-sub">Five-man units by possessions; shrunk net pulls small samples towards the sum of the players\' HPM.</span></div><div id="tp-lineups"></div></div>' +
    '<div class="card"><div class="card-header">On / off <span class="card-sub">Team net per 100 with each player on and off the floor.</span></div><div id="tp-onoff"></div></div></div>';
  h += '<div class="card"><div class="card-header">Rotation <span class="card-sub">Minutes per player per game, in date order. Darker is more minutes; blank is did not play.</span></div><div id="tp-rot" style="height:420px"></div></div>';
  h += '<div class="card"><div class="card-header">Schedule and results <span class="card-sub">Every game: score, efficiency at both ends, and the net rating after it.</span></div><div id="tp-log"></div></div>';
  h += '<div class="grid-2"><div class="card"><div class="card-header">Seed distribution <span class="card-sub">Share of simulated seasons finishing in each seed.</span></div><div id="tp-seed" style="height:260px"></div></div>' +
    '<div class="card"><div class="card-header">Injuries <span class="card-sub">From the latest ESPN report; impact is the model\'s estimate of points per game.</span></div><div id="tp-inj"></div></div></div>';
  // the spec's team comparison (METRICS_SPEC: adjusted ratings, then the four factors at both ends; pace is style)
  const TS = (HW.ui.MSET && HW.ui.MSET.teams) || null;
  if (TS && t) {
    const games = (fx.has(s.w) ? s.w + s.l : 0) || r.games || 0;
    const mm = {}; metrics.forEach(m => { mm[m.key] = m; });
    const rowT = k => { const m = HW.ui.mMeta(k), pc = ((t.pct || {})[k]); return fx.isNum(pc) && !m.style ? { label: m.label, pctl: pc, value: String(fx.fmt(mm[k] || { fmt: m.fmt }, vals[k])).replace(/<[^>]*>/g, ''), tip: m.desc, early: games < TS.min_games } : null; };
    const styleT = TS.headline.concat(TS.more).filter(k => HW.ui.mMeta(k).style && fx.isNum(vals[k]));
    h += QK.pctCard({ title: 'How they compare', peer: 'every ' + L.toUpperCase() + ' team', sample: games + ' games · percentiles from ' + TS.min_games + ' games',
      groups: [{ label: 'Headline', rows: TS.headline.map(rowT).filter(Boolean) }, { label: 'More', rows: TS.more.map(rowT).filter(Boolean) }],
      note: styleT.length ? 'Style, not better or worse: ' + styleT.map(k => HW.ui.mMeta(k).label + ' ' + String(fx.fmt(mm[k] || {}, vals[k])).replace(/<[^>]*>/g, '')).join(' · ') + '.' : '', cls: 'hw-tpc' });
  }
  h += '<div class="card"><div class="card-header">Percentiles <span class="card-sub">The whole team catalogue, ' + metrics.length + ' metrics, against the league this season.</span></div><div id="tp-pct"></div></div>';
  el.innerHTML = h;
  if (embed) {
    // inside the team page's detail tab: the overview already has the header, tiles, needs, rating path, chances, roster and seeds
    el.querySelectorAll('.pg-head, .kpi-grid').forEach(n => { n.hidden = true; });
    ['tp-needs', 'tp-path', 'tp-odds', 'tp-roster', 'tp-seed'].forEach(id => { const n = document.getElementById(id); const c = n && n.closest('.card'); if (c) c.hidden = true; });
  }
  if (Number(S) === Number(curS)) HW.load(fx.path(L, S, 'needs/' + tid + '.json')).then(nd => { if (fx.alive(el)) drawNeeds(L, S, tid, nd); });
  if (Number(S) === Number(curS) && HW.movesLedger) HW.movesLedger(document.getElementById('tp-ledger'), L, S, tid);

  // Rating path.
  const path = (((season || {}).rating_paths) || {})[tid] || [];
  const log = ((t && t.log) || []).slice().sort((a, b) => String(a.date).localeCompare(String(b.date)));
  if (path.length) {
    fx.pathChart('tp-path', [{ name: 'Net rating', colour: colour, rows: path.map(p => ({ x: p.date, y: p.net, se: p.se })) }], { label: 'Net rating through the season, ± one standard error' });
  } else document.getElementById('tp-path').innerHTML = fx.muted('No rating path yet.');

  // Four factors.
  const ffMetrics0 = metrics.filter(m => /four/i.test(m.group || ''));
  const ffMetrics = ffMetrics0.length ? ffMetrics0 : metrics.filter(m => /(^|_)(efg|tov|orb|drb|ftr|ft_rate)/.test(m.key));
  const med = k => fx.median(Object.keys(T).map(x => (T[x].values || {})[k]));
  document.getElementById('tp-ff').innerHTML = ffMetrics.length ? HW.tableHTML([{ label: 'Factor' }, { label: name, align: 'right' }, { label: 'Pct', align: 'center' }, { label: 'League median', align: 'right' }, { label: 'Rank', align: 'right' }],
    ffMetrics.map(m => [{ v: m.label, html: fx.glossLink(m.key, fx.esc(m.label)) + (m.lower ? ' <span class="muted-inline">↓</span>' : '') }, { v: vals[m.key], html: '<strong>' + fx.fmt(m, vals[m.key]) + '</strong>' },
      { v: ((t || {}).pct || {})[m.key], html: fx.pill(((t || {}).pct || {})[m.key]) }, { v: med(m.key), html: fx.fmt(m, med(m.key)) }, { v: ((t || {}).rank || {})[m.key], html: fx.isNum(((t || {}).rank || {})[m.key]) ? fx.ordinal(t.rank[m.key]) : '—' }]), { compact: true })
    : fx.muted('No four-factor metrics in the catalogue.');

  // Odds.
  const oddsRows = [['Make the playoffs', 'p_playoffs'], ['Play-in', 'p_playin'], ['Top six seed', 'p_top6'], ['Win the division', 'p_div'], ['Reach the Finals', 'p_conf'], ['Win the title', 'p_title']]
    .map(x => [x[0], fx.has(sim[x[1]]) ? sim[x[1]] : odds[x[1]], mk[x[1]]]).filter(x => fx.isNum(x[1]) || fx.isNum(x[2]));
  const wt = (((season || {}).win_totals) || {})[tid];
  let oh = oddsRows.filter(x => fx.isNum(x[1])).length ? QK.chances(oddsRows.filter(x => fx.isNum(x[1])).map(x => ({ label: x[0], p: x[1], color: colour })), { sort: false, max: 1, key: false }) : fx.muted('No simulation yet.');
  const sd = (((season || {}).schedule_difficulty) || {})[tid];
  if (sd) oh += '<div class="mk-line"><strong>Schedule</strong>: opponents so far average ' + fx.signed(sd.played, 1) + ' net, the rest ' + fx.signed(sd.remaining, 1) + '.</div>';
  const elo = eloOf(season, tid);
  if (fx.isNum(elo)) oh += '<div class="mk-line"><strong>Elo</strong> ' + fx.num(elo, 0) + '</div>';
  document.getElementById('tp-odds').innerHTML = oh;

  // Shot profile.
  const sp = (t && t.shot_profile) || {};
  const swapAgainst = z => { const o = {}; Object.keys(z || {}).forEach(k => { const x = z[k] || {}; o[k] = Object.assign({}, x, { pps: fx.isNum(x.league_pps) && fx.isNum(x.pps) ? 2 * x.league_pps - x.pps : x.pps, _pps: x.pps }); }); return o; };
  fx.zoneMap('tp-sp-for', L, sp['for'], { title: 'Their shots' });
  document.getElementById('tp-sp-for-t').innerHTML = fx.zoneTable(sp['for']);
  // Colour the defensive map so red is good for the defence (pps allowed below the league).
  fx.zoneMap('tp-sp-ag', L, swapAgainst(sp.against), { title: 'Allowed (red = below league pts/shot)' });
  document.getElementById('tp-sp-ag-t').innerHTML = fx.zoneTable(sp.against);

  // Roster.
  const roster = ((t && t.roster) || []).slice().sort((a, b) => (b.min || 0) - (a.min || 0));
  document.getElementById('tp-roster').innerHTML = roster.length ? HW.tableHTML([{ label: 'Player' }, { label: 'Pos' }, { label: 'GP', align: 'right' }, { label: 'Min', align: 'right' }, { label: 'MPG', align: 'right' }, { label: 'HPM', align: 'right' }, { label: 'O', align: 'right' }, { label: 'D', align: 'right' }, { label: 'Pct', align: 'center', title: 'HPM percentile against the league' }],
    roster.map(p => { const c = P[p.id] || {}; const hk = fx.pick((c.pct || {}), ['hpm', 'hpm_t', /^hpm$/]);
      return { _href: fx.playerHref(L, p.id), cells: [{ v: p.name, html: fx.playerLink(L, p.id, p.name || c.name) }, p.pos || c.pos || '', p.gp, { v: p.min, html: fx.num(p.min, 0) }, { v: p.gp ? p.min / p.gp : 0, html: fx.num(p.gp ? p.min / p.gp : null, 1) },
        { v: p.hpm, html: '<strong>' + fx.signed(p.hpm, 1) + '</strong>' }, { v: p.o, html: fx.signed(p.o, 1) }, { v: p.d, html: fx.signed(p.d, 1) }, { v: hk ? c.pct[hk] : null, html: fx.pill(hk ? c.pct[hk] : null) }] }; }), { compact: true })
    : fx.muted('No roster.');
  HW.sortable('tp-roster');

  // Lineups.
  const lus = ((t && t.lineups) || []).slice().sort((a, b) => (b.poss || 0) - (a.poss || 0));
  const nm = id => fx.surname((P[id] || {}).name || fx.playerName(L, id));
  document.getElementById('tp-lineups').innerHTML = lus.length ? HW.tableHTML([{ label: 'Lineup' }, { label: 'Poss', align: 'right' }, { label: 'ORtg', align: 'right' }, { label: 'DRtg', align: 'right' }, { label: 'Net', align: 'right' }, { label: 'Shrunk', align: 'right' }],
    lus.slice(0, 25).map(u => [{ v: '', html: (u.players || []).map(x => fx.playerLink(L, x, nm(x))).join(' · ') }, { v: u.poss, html: fx.num(u.poss, 0) }, { v: u.ortg, html: fx.num(u.ortg, 1) }, { v: u.drtg, html: fx.num(u.drtg, 1) },
      { v: u.net, html: fx.signed(u.net, 1) }, { v: u.shrunk_net, html: '<strong>' + fx.signed(u.shrunk_net, 1) + '</strong>' }]), { compact: true }) : fx.muted('No lineup data (play-by-play seasons only).');
  HW.sortable('tp-lineups');

  // On/off.
  const oo = (t && t.on_off) || {};
  const ooIds = Object.keys(oo).sort((a, b) => ((oo[b] || {}).diff || -99) - ((oo[a] || {}).diff || -99));
  document.getElementById('tp-onoff').innerHTML = ooIds.length ? HW.tableHTML([{ label: 'Player' }, { label: 'Poss on', align: 'right' }, { label: 'On', align: 'right' }, { label: 'Off', align: 'right' }, { label: 'Diff', align: 'right' }],
    ooIds.map(id => { const o = oo[id] || {}; return { _href: fx.playerHref(L, id), cells: [{ v: nm(id), html: fx.playerLink(L, id, (P[id] || {}).name) }, { v: o.poss_on, html: fx.num(o.poss_on, 0) }, { v: o.on_net, html: fx.signed(o.on_net, 1) }, { v: o.off_net, html: fx.signed(o.off_net, 1) },
      { v: o.diff, html: '<span class="' + (o.diff > 0 ? 'pg-up' : o.diff < 0 ? 'pg-down' : '') + '">' + fx.signed(o.diff, 1) + '</span>' }] }; }), { compact: true }) : fx.muted('No on/off data (play-by-play seasons only).');
  HW.sortable('tp-onoff');

  // Rotation heatmap.
  const rot = (t && t.rotation) || {};
  const rp = rot.players || [], rg = rot.games || [], rm = rot.minutes || [];
  if (rp.length && rg.length && rm.length) {
    const byPlayer = rm.length === rp.length;
    const z = byPlayer ? rm : rp.map((p, i) => rg.map((g, j) => (rm[j] || [])[i]));
    const order = rp.map((p, i) => i).sort((a, b) => z[b].reduce((s, v) => s + (v || 0), 0) - z[a].reduce((s, v) => s + (v || 0), 0));
    const gameLab = rg.map((g, j) => { const lg = log.find(x => String(x.game) === String(g)); return lg ? fx.fmtDate(lg.date, { year: false, weekday: false }) + ' ' + (lg.home ? 'v ' : '@ ') + fx.teamAbbr(L, lg.opp) : 'G' + (j + 1); });
    const node = document.getElementById('tp-rot');
    node.style.height = ''; node.style.setProperty('--h', Math.max(280, 22 * order.length + 120) + 'px');
    const data = [];
    order.forEach((i, yi) => z[i].forEach((v, xi) => { if (fx.isNum(v) && v > 0) data.push([xi, yi, v]); }));
    QKC.heatmap(node, { x: rg.map((g, j) => String(j + 1)), y: order.map(i => nm(rp[i])), data: data, min: 0, max: L === 'wnba' ? 40 : 48, fmt: v => fx.num(v, 0), cellLabels: false,
      xName: 'Game of the season', yName: 'Player', label: 'Minutes per player per game' });
  } else document.getElementById('tp-rot').innerHTML = fx.muted('No rotation data yet.');

  // Schedule log.
  document.getElementById('tp-log').innerHTML = log.length ? HW.tableHTML([{ label: 'Date' }, { label: 'Opponent' }, { label: 'Result' }, { label: 'Score', align: 'right' }, { label: 'ORtg', align: 'right' }, { label: 'DRtg', align: 'right' }, { label: 'Pace', align: 'right' }, { label: 'Net after', align: 'right' }]
    .concat(log.some(g => fx.isNum(g.p_win) || fx.isNum(g.model_p)) ? [{ label: 'Model p', align: 'right', title: 'Pregame win probability from the game model' }] : []),
    log.slice().reverse().map(g => ({ _href: g.game ? fx.gameHref(L, g.game, S) : undefined, cells: [{ v: g.date, html: fx.fmtDate(g.date, { year: false }) }, { v: fx.teamName(L, g.opp), html: (g.home ? 'v ' : '@ ') + fx.teamLink(L, g.opp) },
      { v: g.res, html: '<span class="' + (String(g.res).charAt(0) === 'W' ? 'pg-up' : 'pg-down') + '">' + fx.esc(g.res || '') + '</span>' }, { v: (g.pts || 0) - (g.opp_pts || 0), html: (g.pts || 0) + '-' + (g.opp_pts || 0) },
      { v: g.ortg, html: fx.num(g.ortg, 1) }, { v: g.drtg, html: fx.num(g.drtg, 1) }, { v: g.pace, html: fx.num(g.pace, 1) }, { v: g.net_rating_after, html: fx.signed(g.net_rating_after, 1) }]
      .concat(log.some(x => fx.isNum(x.p_win) || fx.isNum(x.model_p)) ? [{ v: fx.has(g.p_win) ? g.p_win : g.model_p, html: fx.pct(fx.has(g.p_win) ? g.p_win : g.model_p, 0) }] : []) })), { compact: true, sticky: true })
    : fx.muted('No games yet.');
  HW.sortable('tp-log');

  // Seed distribution.
  const seeds = sim.seed_dist || [];
  if (seeds.length) QKC.bar('#tp-seed', { cats: seeds.map((v, i) => String(i + 1)), series: [{ name: 'Chance', color: 'model', data: seeds }], fmt: v => fx.pct(v, v < 0.1 ? 1 : 0),
    catName: 'Final seed', valName: 'Our chance', label: 'Chance of each final seed' });
  else document.getElementById('tp-seed').innerHTML = fx.muted('No simulation yet.');

  // Injuries.
  const inj = (t && t.injuries) || [];
  document.getElementById('tp-inj').innerHTML = inj.length ? HW.tableHTML([{ label: 'Player' }, { label: 'Status' }, { label: 'Detail' }, { label: 'Impact', align: 'right' }],
    inj.map(x => { const o = Array.isArray(x) ? { id: x[0], status: x[1], detail: x[2] } : x; const id = o.id || o.player;
      return [{ v: fx.playerName(L, id), html: fx.isNum(id) || /^\d+$/.test(String(id)) ? fx.playerLink(L, id, o.name) : fx.esc(id) }, fx.esc(o.status || ''), fx.esc(o.detail || ''), { v: o.impact, html: fx.signed(o.impact, 1) }]; }), { compact: true })
    : fx.muted('No injuries listed.');

  document.getElementById('tp-pct').innerHTML = t ? fx.pctPanel(metrics, vals, t.pct, { note: 'League percentile, 100 = best; ↓ marks metrics where lower is better. Hover a row for the definition.' }) : fx.muted('Not in the catalogue.');
}

// ── strengths and needs (data/<L>/<S>/needs/<tid>.json, analytics/value.py needs_payloads) ──────────────

const ROLE_ONE = { G: 'Guard', W: 'Wing', B: 'Big' };
function gradePill(g) { return g ? '<span class="nd-grade nd-' + String(g).toLowerCase() + '">' + FX().esc(g) + '</span>' : '—'; }

function drawNeeds(L, S, tid, nd) {
  const fx = FX();
  const box = document.getElementById('tp-needs');
  if (!box) return;
  if (!fx.ok(nd) || !nd.grades) { box.innerHTML = fx.notBuilt('Strengths and needs', nd); return; }
  const full = nd.games_left !== undefined && nd.games_left !== null && nd.games_left === nd.games;
  let h = '<div class="grid-2 nd-top"><div>' + HW.tableHTML([{ label: 'Area' }, { label: 'Grade', align: 'center' }, { label: 'WAR', align: 'right', title: 'Projected WAR over a full season' }, { label: 'Rank', align: 'right' }, { label: 'Pct', align: 'center' }],
    nd.grades.map(g => [{ v: g.label, html: fx.esc(g.label) }, { v: g.pct, html: gradePill(g.grade) }, { v: g.value, html: fx.num(g.value, 1) }, { v: g.rank, html: fx.ordinal(g.rank) + ' of ' + g.n }, { v: g.pct, html: fx.pill(g.pct) }]), { compact: true }) + '</div><div class="nd-list">' +
    '<div class="nd-h">Strengths</div>' + (nd.strengths || []).map(s => '<div class="nd-item">' + gradePill(s.grade) + ' <strong>' + fx.esc(s.label) + (s.relative ? ' <span class="muted-inline">(relative: below the league median)</span>' : '') + '</strong> <span class="muted-inline">' + fx.esc(s.evidence) + '</span></div>').join('') +
    '<div class="nd-h">Weaknesses</div>' + (nd.weaknesses || []).map(s => '<div class="nd-item">' + gradePill(s.grade) + ' <strong>' + fx.esc(s.label) + (s.relative ? ' <span class="muted-inline">(relative: above the league median)</span>' : '') + '</strong> <span class="muted-inline">' + fx.esc(s.evidence) + '</span></div>').join('') + '</div></div>';
  (nd.weaknesses || []).forEach(w => {
    const tg = w.targets || [];
    const unit = w.key === 'off' ? 'offence' : w.key === 'def' ? 'defence' : 'net';
    h += '<div class="nd-ways"><div class="nd-h">Ways to improve: ' + fx.esc(w.label) + '</div>' + (tg.length ? '<div class="nd-tgs">' + tg.map(c => {
      const pp = (x, lab) => (fx.isNum(x) && Math.abs(x) >= 0.0005 ? ' · ' + lab + ' ' + fx.signed(100 * x, 1) + ' pp' : '');
      return '<div class="nd-tg' + (c.attainable ? ' nd-att' : '') + '"><div class="nd-tg-h">' + fx.playerLink(L, c.id, c.name) + ' <span class="muted-inline">' + fx.esc(fx.teamAbbr(L, c.team)) + ' · ' + fx.esc(ROLE_ONE[c.role] || c.role || '') + (fx.isNum(c.age) ? ' · ' + fx.num(c.age, 0) : '') + ' · ' + fx.num(c.mpg, 0) + ' min · HPM ' + fx.signed(c.rate, 1) + '</span>' + (c.attainable ? ' <span class="chip ok">attainable</span>' : '') + '</div>' +
        '<div class="nd-tg-v"><strong>' + fx.signed(c.gain, 1) + '</strong> ' + unit + ' per 100' + (unit !== 'net' ? ' (' + fx.signed(c.gain_net, 1) + ' net)' : '') + ' · ' + fx.signed(c.wins, 1) + (full ? ' wins a season' : ' wins') + pp(c.d_playoffs, 'playoffs') + pp(c.d_title, 'title') + '</div>' +
        ((c.hints || []).length ? '<div class="nd-hints">' + (c.hints || []).map(fx.esc).join('; ') + '</div>' : '') +
        '<div class="nd-tg-a"><a href="#/' + L + '/trade?t=' + encodeURIComponent(tid) + ',' + encodeURIComponent(c.team) + '&m=' + encodeURIComponent(c.id) + '-' + encodeURIComponent(tid) + '">Try in the trade simulator →</a></div></div>';
    }).join('') + '</div>'
      : fx.muted('No player on another team would add value here.')) + '</div>';
  });
  h += '<div class="pg-note">' + fx.esc(nd.note || '') + ' Free agents: ' + fx.esc(nd.free_agents || 'not identified.') + ' Targets are ranked by what each would add in the team\'s rotation (displacing its lowest-rated minutes at that position); "attainable" marks a seller out of contention or with depth at the position, and not one of its two most valuable players. ' + (full ? 'Wins are over a full season (no season simulation now).' : 'Wins and playoff chances come from the season simulation\'s sensitivity curves.') + '</div>';
  box.innerHTML = h;
  HW.sortable(box);
}

HW.route('teams', renderTeams);
HW.route('team', renderTeam);
})(window.HW);
