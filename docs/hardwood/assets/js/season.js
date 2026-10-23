/* The Quant Hardwood — the season page (#/<L>/season/<S>).
 *
 *   champion banner (finished seasons, from history.json / index champions);
 *   standings per conference with projected wins, playoff / play-in / title chances and magic numbers;
 *   seed distribution heatmap; team ratings (offence, defence, net ± se, pace, Elo);
 *   power-rating paths (Kalman filter, ± one standard error band for the picked team);
 *   win totals: our simulated distribution and range (the market's line is on the Model page);
 *   schedule difficulty; statistical leaders.
 *
 * Reads <L>/<S>/season.json, <L>/<S>/players.json (names), <L>/history.json. */
(function (HW) {
'use strict';

const esc = HW.esc;
const LEADER_LABEL = { pts: 'Points', reb: 'Rebounds', ast: 'Assists', stl: 'Steals', blk: 'Blocks', '3pm': '3-pointers made', tpm: '3-pointers made',
  hpm: 'Hardwood +/- (HPM)', ts: 'True shooting %' };

/* Cut lines: seeds 1..direct go straight to the playoffs, direct+1..playin play in. */
function cuts(L, fmt) {
  const f = fmt || {};
  const pin = !!f.playin;
  const direct = HW.isNum(f.direct) ? f.direct : (pin ? (f.playin_seeds ? f.playin_seeds[0] - 1 : 6) : (f.playoff_teams || (L === 'nba' ? 8 : 8)));
  const last = pin ? (f.playin_seeds ? f.playin_seeds[1] : 10) : direct;
  return { direct: direct, playin: last };
}

function magicCell(s) {
  if (!s) return { v: null, html: '—' };
  const cl = s.clinched || {}, el = s.eliminated || {}, mg = s.magic || {};
  const tags = [];
  if (cl.top_seed) tags.push('<span class="clinch" title="Clinched the top seed">z</span>');
  else if (cl.division) tags.push('<span class="clinch" title="Clinched the division">y</span>');
  if (cl.postseason || cl.playoffs) tags.push('<span class="clinch" title="Clinched a postseason place">x</span>');
  else if (cl.top6) tags.push('<span class="clinch" title="Clinched a top-6 seed">x</span>');
  if (el.postseason || el.playoffs) return { v: 999, html: '<span class="elim" title="Eliminated from the postseason">e</span>' };
  const k = ['postseason', 'playoffs', 'top6'].find(x => HW.isNum(mg[x]));
  if (tags.length) return { v: -1, html: tags.join('') };
  return k ? { v: mg[k], html: '<span class="magic" title="Magic number for a ' + esc(k.replace('top6', 'top-6 seed').replace('postseason', 'postseason place')) + '">' + mg[k] + '</span>' } : { v: null, html: '—' };
}

function standingsTable(L, rows, sim, fmt, opts) {
  const o = opts || {};
  const c = cuts(L, fmt);
  const live = Object.keys(sim).length > 0;
  const hasPin = !!(fmt && fmt.playin) || rows.some(r => HW.isNum((sim[r.team] || {}).p_playin) && sim[r.team].p_playin > 0);
  const hasTop6 = L === 'nba' && rows.some(r => HW.isNum((sim[r.team] || {}).p_top6));
  const cols = [{ label: '#', align: 'right' }, { label: 'Team' }, { label: 'W-L', align: 'right' }, { label: 'Pct', align: 'right' }, { label: 'GB', align: 'right' },
    { label: 'Conf', align: 'right', cls: 'hide-sm' }, { label: 'Home', align: 'right', cls: 'hide-sm' }, { label: 'Away', align: 'right', cls: 'hide-sm' },
    { label: 'L10', align: 'right', cls: 'hide-sm' }, { label: 'Strk', align: 'right', cls: 'hide-sm' }, { label: 'PD', align: 'right', title: 'Points differential' }];
  if (live) {
    cols.push({ label: 'Proj W', align: 'right', title: 'Projected wins (mean of the simulations), with the 5th-95th percentile range' });
    if (hasTop6) cols.push({ label: 'Top 6', align: 'right', title: 'Probability of a top-6 seed (no play-in)' });
    cols.push({ label: 'Playoffs', align: 'right', title: 'Probability of reaching the playoffs proper' });
    if (hasPin) cols.push({ label: 'Play-in', align: 'right', title: 'Probability of finishing in the play-in places' });
    if (!o.league) cols.push({ label: 'Conf title', align: 'right' });
    cols.push({ label: 'Title', align: 'right' });
    cols.push({ label: 'Magic', align: 'right', title: 'Magic number for a postseason place; x clinched, y division, z top seed, e eliminated' });
  }
  const pre = live && rows.length && rows.every(r => !r.w && !r.l);
  if (pre) rows = rows.slice().sort((a, b) => ((sim[b.team] || {}).exp_w || 0) - ((sim[a.team] || {}).exp_w || 0));
  const body = rows.map((r, i) => {
    const s = sim[r.team] || {};
    const seed = pre ? i + 1 : (r.seed || i + 1);
    const cells = [
      { v: seed, html: '<span class="seed-n">' + seed + '</span>' },
      { v: HW.teamName(L, r.team), html: HW.teamLink(L, r.team) },
      { v: r.w, html: HW.record(r.w, r.l) },
      { v: r.pct, html: HW.isNum(r.pct) ? HW.fmtVal(r.pct, '3') : '—' },
      { v: r.gb, html: HW.isNum(r.gb) ? (r.gb === 0 ? '—' : HW.num(r.gb, 1)) : esc(r.gb || '—') },
      { v: r.conf_w, html: HW.record(r.conf_w, r.conf_l) },
      { v: (r.home || [])[0], html: r.home ? HW.record(r.home[0], r.home[1]) : '—' },
      { v: (r.away || [])[0], html: r.away ? HW.record(r.away[0], r.away[1]) : '—' },
      { v: (r.l10 || [])[0], html: r.l10 ? HW.record(r.l10[0], r.l10[1]) : '—' },
      { v: r.streak, html: esc(r.streak || '—') },
      { v: r.pd, html: HW.isNum(r.pd) ? '<span class="' + (r.pd > 0 ? 'pos-up' : r.pd < 0 ? 'pos-down' : '') + '">' + HW.signed(r.pd, 0) + '</span>' : '—' }
    ];
    if (live) {
      cells.push({ v: s.exp_w, html: HW.isNum(s.exp_w) ? '<span title="' + esc(HW.num(s.w_p05, 0) + '–' + HW.num(s.w_p95, 0) + ' (90% range)') + '">' + HW.num(s.exp_w, 1) + '</span>' : '—' });
      if (hasTop6) cells.push({ v: s.p_top6, html: HW.probCell(s.p_top6) });
      cells.push({ v: s.p_playoffs, html: HW.probCell(s.p_playoffs) });
      if (hasPin) cells.push({ v: s.p_playin, html: HW.isNum(s.p_playin) ? HW.pct(s.p_playin, 0) : '—' });
      if (!o.league) cells.push({ v: s.p_conf, html: HW.isNum(s.p_conf) ? HW.pct(s.p_conf, 1) : '—' });
      cells.push({ v: s.p_title, html: HW.isNum(s.p_title) ? '<b>' + HW.pct(s.p_title, 1) + '</b>' : '—' });
      cells.push(magicCell(s));
    }
    const cls = i === c.direct ? 'seed-cut' + (hasPin ? '' : '') : (hasPin && i === c.playin ? 'seed-cut-pi' : '');
    return { cells: cells, _class: cls, _href: HW.teamHref(L, r.team) };
  });
  return HW.tableHTML(cols, body, { compact: true, cls: 'standings-table' });
}

function championBanner(L, S, hist, info) {
  const row = hist && (hist.seasons || []).find(x => Number(x.season) === Number(S));
  const fromIdx = (info.champions || []).find(c => Number(c[0]) === Number(S));
  const champ = row ? row.champion : (fromIdx ? fromIdx[1] : null);
  if (!champ) return '';
  const tl = id => (HW.NAMES[L].teams[String(id)] ? HW.teamLink(L, id) : esc(id));
  const pl = id => (id ? (HW.NAMES[L].players[String(id)] ? HW.playerLink(L, id) : esc(id)) : '—');
  return '<div class="champ-banner"><div><div class="cb-k">' + esc(HW.seasonLabel(L, S)) + ' champion</div><div class="cb-v">' + tl(champ) + '</div></div>' +
    (row && row.runner_up ? '<div><div class="cb-k">Runner-up</div><div>' + tl(row.runner_up) + '</div></div>' : '') +
    (row && row.mvp ? '<div><div class="cb-k">MVP</div><div>' + pl(row.mvp) + '</div></div>' : '') +
    (row && row.finals_mvp ? '<div><div class="cb-k">Finals MVP</div><div>' + pl(row.finals_mvp) + '</div></div>' : '') +
    (row && row.best_record ? '<div><div class="cb-k">Best record</div><div>' + tl(row.best_record[0]) + ' ' + HW.record(row.best_record[1], row.best_record[2]) + '</div></div>' : '') + '</div>';
}

function ratingsTable(L, season) {
  const rt = season.ratings || {}, elo = season.elo || {};
  const ids = Object.keys(rt).sort((a, b) => (rt[b].net || 0) - (rt[a].net || 0));
  if (!ids.length) return HW.muted('No ratings yet.');
  const elos = Object.keys(elo).length > 0;
  return HW.tableHTML([{ label: '#', align: 'right' }, { label: 'Team' }, { label: 'Net', align: 'right', title: 'Net rating: points per 100 possessions better than average, opponent-adjusted' },
    { label: '± se', align: 'right', title: 'One standard error of the net rating' }, { label: 'Off', align: 'right' }, { label: 'Def', align: 'right', title: 'Points allowed per 100 (lower is better)' },
    { label: 'Pace', align: 'right' }, { label: 'GP', align: 'right' }].concat(elos ? [{ label: 'Elo', align: 'right' }] : []),
  ids.map((t, i) => {
    const r = rt[t];
    return { cells: [{ v: r.rank || i + 1, html: String(r.rank || i + 1) }, { v: HW.teamName(L, t), html: HW.teamLink(L, t) },
      { v: r.net, html: '<b>' + HW.signed(r.net, 1) + '</b>' }, { v: r.se_net, html: HW.num(r.se_net, 1) }, { v: r.off, html: HW.num(r.off, 1) },
      { v: r.def, html: HW.num(r.def, 1) }, { v: r.pace, html: HW.num(r.pace, 1) }, { v: r.games, html: HW.isNum(r.games) ? String(r.games) : '—' }]
      .concat(elos ? [{ v: elo[t], html: HW.num(elo[t], 0) }] : []), _href: HW.teamHref(L, t) };
  }), { compact: true });
}

function drawPaths(el, L, season, teams, focus) {
  const paths = season.rating_paths || {};
  const ids = teams.filter(t => (paths[t] || []).length);
  if (!ids.length) { el.innerHTML = HW.muted('Rating paths arrive once games are played.'); return; }
  const series = ids.map(t => {
    const p = paths[t];
    const isF = focus && String(focus) === String(t);
    return { name: HW.teamAbbr(L, t), x: p.map(r => r.date), y: p.map(r => r.net), colour: HW.teamColour(L, t),
      width: isF ? 3 : (focus ? 1 : 1.8), dash: 'solid',
      band: isF ? [p.map(r => r.net - (r.se || 0)), p.map(r => r.net + (r.se || 0))] : null,
      hover: HW.esc(HW.teamName(L, t)) + ' · %{x}: %{y:+.1f}<extra></extra>' };
  });
  // Draw the focus team last so it sits on top.
  series.sort((a, b) => (a.band ? 1 : 0) - (b.band ? 1 : 0));
  HW.charts.lines(el, series, { height: 380, xTitle: 'Date', yTitle: 'Net rating', xaxis: { type: 'date' }, yaxis: { zeroline: true } });
}

function drawWinTotal(el, L, season, sim, tid) {
  const s = sim[tid] || {};
  const wd = s.win_dist || [];
  if (!wd.length) { el.innerHTML = HW.muted('No win distribution for this team.'); return; }
  const x = wd.map((_, i) => i), y = wd;
  const colour = HW.teamColour(L, tid);
  const lo = wd.findIndex(p => p > 0.001), hi = wd.length - 1 - wd.slice().reverse().findIndex(p => p > 0.001);
  const xs = x.slice(Math.max(0, lo - 1), hi + 2);
  el.style.setProperty('--h', '260px');
  QKC.bar(el, { cats: xs.map(String), series: [{ name: 'Chance', color: colour, data: xs.map(w => y[w]) }], fmt: v => HW.pct(v, 1), catName: 'Wins at season end', valName: 'Our chance',
    label: 'Our chance of each final win total' });
}

function winTotalsTable(L, season, sim) {
  const wt = season.win_totals || {};
  const pre = season.phase === 'preseason';
  const ids = Object.keys(sim).length ? Object.keys(sim) : Object.keys(wt);
  if (!ids.length) return '';
  const rows = ids.map(t => {
    const s = sim[t] || {}, w = wt[t] || {};
    return { cells: [
      { v: HW.teamName(L, t), html: HW.teamLink(L, t) },
      { v: s.exp_w, html: HW.num(s.exp_w, 1) },
      { v: s.w_p05, html: HW.isNum(s.w_p05) ? HW.num(s.w_p05, 0) + '–' + HW.num(s.w_p95, 0) : '—' },
      { v: s.p_playoffs, html: HW.isNum(s.p_playoffs) ? HW.pct(s.p_playoffs, 0) : '—' }
    ], _class: 'wt-row', _style: '' };
  }).sort((a, b) => (b.cells[1].v || 0) - (a.cells[1].v || 0));
  return HW.tableHTML([{ label: 'Team' }, { label: 'Proj W', align: 'right' }, { label: '90% range', align: 'right' }, { label: 'Playoffs', align: 'right', title: 'Our playoff chance' }], rows, { compact: true }) +
    (pre ? '<div class="section-note">Preseason projections are last season carried forward plus a roster term that counts rookies at replacement level.</div>' : '');
}

function scheduleTable(L, season) {
  const sd = season.schedule_difficulty || {};
  const ids = Object.keys(sd);
  if (!ids.length) return '';
  const rows = ids.map(t => [{ v: HW.teamName(L, t), html: HW.teamLink(L, t) },
    { v: sd[t].played, html: HW.signed(sd[t].played, 2) }, { v: sd[t].remaining, html: HW.signed(sd[t].remaining, 2) }]);
  rows.sort((a, b) => (b[2].v || 0) - (a[2].v || 0));
  return HW.charts.heatTable({ cols: [{ label: 'Played', title: 'Average net rating of the opponents faced (home court included)' }, { label: 'Remaining', title: 'Average net rating of the opponents still to play' }],
    rows: rows.map(r => ({ label: r[0].html, values: [r[1].v, r[2].v] })), fmt: v => HW.signed(v, 2), corner: 'Opponent strength', center: 0 });
}

function leadersHTML(L, season) {
  const ld = season.leaders || {};
  const keys = Object.keys(ld).filter(k => (ld[k] || []).length);
  if (!keys.length) return '';
  const fmt = k => (k === 'ts' ? 'pct' : k === 'hpm' ? 'pm' : '1');
  return '<div class="leaders-grid">' + keys.map(k => '<div class="ld-box"><div class="day-head">' + esc(LEADER_LABEL[k] || k.toUpperCase()) + '</div>' +
    HW.tableHTML([{ label: '#', align: 'right' }, { label: 'Player' }, { label: '', align: 'right' }], ld[k].slice(0, 5).map((r, i) =>
      [String(i + 1), { html: HW.playerLink(L, r[0], { team: (HW.NAMES[L].players[String(r[0])] || {}).team }) }, { v: r[1], html: '<b>' + HW.fmtVal(r[1], fmt(k)) + '</b>' }]), { compact: true }) + '</div>').join('') +
    '</div><a class="more-link" href="' + HW.href(L, 'leaders') + '">Full leaderboards →</a>';
}

function render(el, params) {
  const L = params.league, S = params.season;
  const info = HW.leagueInfo(L);
  const isCurrent = S === HW.currentSeason(L);
  el.innerHTML = HW.pageHead(HW.leagueName(L) + ' ' + HW.seasonLabel(L, S), 'Standings, our chances and ratings',
    '<a href="' + HW.href(L, 'playoffs', S) + '">Playoffs</a><a href="' + HW.href(L, 'games', S) + '">Games</a>') +
    '<div id="sn-body"><div class="muted">Loading the season…</div></div>';
  return HW.loadAll([HW.path('season.json', L, S), HW.lpath('history.json', L), HW.path('players.json', L, S), HW.lpath('markets.json', L)]).then(arr => {
    if (!el.isConnected) return;
    const season = arr[0], hist = HW.ok(arr[1]) ? arr[1] : null;
    // Win totals live in the league's markets.json (current season only).
    const mk = arr[3];
    if (HW.ok(season) && HW.ok(mk) && String(mk.season) === String(S) && mk.win_totals && !season.win_totals) season.win_totals = mk.win_totals;
    const body = document.getElementById('sn-body');
    if (!HW.ok(season)) { body.innerHTML = championBanner(L, S, hist, info) + HW.card('Season', '', HW.notBuilt('The ' + HW.seasonLabel(L, S) + ' season payload', season)); return; }
    const sim = HW.simTeams(season);
    const st = season.standings || {};
    const confs = Object.keys(st);
    const fmt = season.format || {};
    const finished = !isCurrent || season.phase === 'offseason';
    let html = finished ? championBanner(L, S, hist, info) : '';
    const leagueWide = L === 'wnba' && fmt.seeding === 'league';
    // standings
    const views = confs.map(c => ({ key: c, label: c }));
    if (confs.length > 1) views.push({ key: '__all', label: 'League' });
    html += HW.card(finished ? 'Final standings' : 'Standings', finished ? '' : (season.sim && season.sim.n_sims ? HW.num(season.sim.n_sims, 0) + ' simulations of the rest of the season' : ''),
      (views.length > 1 ? '<div class="toggle-row" id="sn-st-tabs">' + HW.toggles(views, leagueWide ? '__all' : views[0].key, 'data-st') + '</div>' : '') + '<div id="sn-st"></div>' +
      '<div class="section-note">Orange line: playoff cut' + (fmt.playin ? '; dashed: play-in cut' : '') + '. Click a row for the team page.</div>');
    const open = Object.keys(sim).some(t => HW.isNum(sim[t].w_p05) && sim[t].w_p95 > sim[t].w_p05);
    if (Object.keys(sim).length && open) {
      html += '<div class="grid-2">' + HW.card('Seed distribution', 'share of simulations finishing in each seed', (confs.length > 1 && !leagueWide ? '<div class="toggle-row" id="sn-seed-tabs">' + HW.toggles(confs.map(c => ({ key: c, label: c })), confs[0], 'data-sd') + '</div>' : '') + '<div id="sn-seed"></div>') +
        HW.card('Win totals', 'our chance of each final win total', '<div class="toggle-row"><label>Team <select id="sn-wt-team"></select></label></div><div id="sn-wt"></div>') + '</div>';
      html += HW.card('Projected wins', 'the mean of our simulated seasons, the range nine in ten land in, and our playoff chance', winTotalsTable(L, season, sim) || HW.muted('No simulation yet.'));
    }
    html += HW.card('Power-rating paths', 'net rating after each game (Kalman filter); pick a team for its ±1 se band',
      '<div class="toggle-row">' + (confs.length > 1 ? HW.toggles(confs.map(c => ({ key: c, label: c })).concat([{ key: '__all', label: 'All' }]), confs[0], 'data-rp') : '') +
      '<label style="margin-left:auto">Highlight <select id="sn-rp-team"><option value="">—</option></select></label></div><div id="sn-rp"></div>');
    html += '<div class="grid-2">' + HW.card('Team ratings', 'opponent-adjusted per 100 possessions', ratingsTable(L, season)) +
      HW.card('Schedule difficulty', 'average opponent net rating, played and remaining', scheduleTable(L, season) || HW.muted('Not available.')) + '</div>';
    const ld = leadersHTML(L, season);
    if (ld) html += HW.card('Leaders', 'per game; qualified players', ld);
    body.innerHTML = html;

    // standings view
    const allRows = () => {
      const list = [];
      confs.forEach(c => (st[c] || []).forEach(r => list.push(r)));
      return list.sort((a, b) => (leagueWide && HW.isNum(a.seed) && HW.isNum(b.seed) ? a.seed - b.seed : 0) || (b.pct || 0) - (a.pct || 0) || (b.w || 0) - (a.w || 0)).map((r, i) => Object.assign({}, r, { seed: leagueWide ? r.seed : i + 1 }));
    };
    const drawSt = k => {
      document.getElementById('sn-st').innerHTML = k === '__all' ? standingsTable(L, allRows(), sim, fmt, { league: true }) : standingsTable(L, st[k] || [], sim, fmt);
      HW.sortable(document.getElementById('sn-st'));
    };
    drawSt(leagueWide && views.length > 1 ? '__all' : (views[0] || {}).key);
    HW.wireToggles(document.getElementById('sn-st-tabs'), 'data-st', drawSt);

    if (Object.keys(sim).length && open) {
      const drawSeed = c => {
        const expSeed = d => d.reduce((a, p, i) => a + p * (i + 1), 0) / Math.max(1e-9, d.reduce((a, p) => a + p, 0));
        const rows = (leagueWide || !c ? allRows() : (st[c] || [])).map(r => ({ label: HW.teamAbbr(L, r.team), dist: (sim[r.team] || {}).seed_dist || [] }))
          .sort((a, b) => expSeed(a.dist) - expSeed(b.dist));
        HW.charts.posHeatmap('sn-seed', rows, { xName: 'seed' });
      };
      drawSeed(leagueWide ? null : confs[0]);
      HW.wireToggles(document.getElementById('sn-seed-tabs'), 'data-sd', drawSeed);
      const sel = document.getElementById('sn-wt-team');
      const ids = Object.keys(sim).sort((a, b) => (sim[b].exp_w || 0) - (sim[a].exp_w || 0));
      sel.innerHTML = ids.map(t => '<option value="' + esc(t) + '">' + esc(HW.teamName(L, t)) + '</option>').join('');
      const drawWt = () => drawWinTotal(document.getElementById('sn-wt'), L, season, sim, sel.value);
      sel.addEventListener('change', drawWt);
      drawWt();
    }
    // rating paths
    let rpConf = confs[0] || '__all', focus = '';
    const teamsOf = c => (c === '__all' || !c ? Object.keys(season.rating_paths || {}) : (st[c] || []).map(r => r.team));
    const rpSel = document.getElementById('sn-rp-team');
    const fillRp = () => {
      rpSel.innerHTML = '<option value="">—</option>' + teamsOf(rpConf).map(t => '<option value="' + esc(t) + '"' + (t === focus ? ' selected' : '') + '>' + esc(HW.teamName(L, t)) + '</option>').join('');
    };
    const drawRp = () => drawPaths(document.getElementById('sn-rp'), L, season, teamsOf(rpConf), focus);
    fillRp(); drawRp();
    rpSel.addEventListener('change', () => { focus = rpSel.value; drawRp(); });
    HW.wireToggles(body, 'data-rp', k => { rpConf = k; if (teamsOf(k).indexOf(focus) < 0) focus = ''; fillRp(); drawRp(); });
    HW.sortable(body);
    HW.setMeta(season.updated_at ? 'Season model ' + esc(HW.fmtStamp(season.updated_at)) : '');
  });
}

HW.route('season', render);
})(window.HW);
