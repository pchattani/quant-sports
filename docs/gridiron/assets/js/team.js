/* The Quant Gridiron — the team page (#/team/<abbr>).
 *
 * Record, rating and odds tiles; playoff paths (the odds of each stage, the seed and win
 * distributions); unit ratings week by week; the team profile as percentiles; tendencies (PROE by
 * situation, play action, RPO, motion, personnel, formation) and pace; fourth-down aggressiveness
 * with the team's own fourth downs graded; the schedule against the model and the market; the QB
 * situation; roster value from the player catalogue; strengths and needs (unit and position grades
 * against the league, the top three strengths and weaknesses, and ways to improve: trade targets and
 * unsigned players ranked by what they would add, with links into the trade simulator).
 *
 * Data: data/<S>/teams.json, season.json, fourth_downs.json, schedule.json, players.json,
 * needs/<abbr>.json (current season). Uses GI.fk
 * and GI.fk.T (teams.js). */
(function (GI) {
'use strict';

const K = () => GI.fk;
const T = () => GI.fk.T;

function render(el, params, state) {
  const k = K();
  const abbr = String(params.id || (params.rest || [])[0] || '').toUpperCase();
  el.innerHTML = k.muted('Loading…');
  return k.ready().then(() => {
    const S = k.S(params, state);
    return Promise.all([k.loadY(S, 'teams.json'), k.loadY(S, 'season.json'), k.loadY(S, 'fourth_downs.json'), k.loadY(S, 'schedule.json'), k.loadY(S, 'players.json'), k.loadNames()])
      .then(res => ({ S: S, res: res }));
  }).then(o => {
    if (!k.alive(el)) return;
    const S = o.S, res = o.res, t = T();
    const cat = t.teamsOf(res[0]), rows = t.seasonRows(res[1]);
    const TM = (cat && cat.teams) || {};
    const tm = TM[abbr] || null, row = rows[abbr] || null;
    if (!tm && !row && !k.NFL[abbr]) { el.innerHTML = k.card('Team', '', k.muted('There is no team <code>' + k.esc(abbr) + '</code>. <a href="#/teams">All teams →</a>')); return; }
    const x = tm || {}, r = row || {};
    const info = k.team(abbr);
    const rc = t.recordOf(x, r), R = t.ratingsOf(x, r), od = t.oddsOf(r, r.odds, x.sim, x.odds);
    const colour = k.teamColour(abbr);
    const sub = [info.division ? '<span class="chip">' + k.esc(info.division) + '</span>' : '', k.isNum(rc.w) ? '<strong>' + t.recText(rc) + '</strong>' : '',
      k.isNum(r.div_rank) ? '<span>' + k.ordinal(r.div_rank) + ' in the division</span>' : '', k.isNum(r.seed) ? '<span>' + k.ordinal(r.seed) + ' seed now</span>' : '',
      x.coach || r.coach ? '<span>Head coach ' + k.coachLink(x.coach || r.coach, S) + '</span>' : '', '<span class="chip">' + S + '</span>'].filter(Boolean).join(' ');
    const links = ['<a href="' + k.compareHref('t:' + abbr, '') + '">Compare →</a>', '<a href="' + (k.has('standingsHref') ? GI.standingsHref(S) : '#/standings') + '">Standings →</a>', '<a href="' + k.withQ('#/teams', S) + '">All teams →</a>'].join('');
    let h = k.head(k.esc(k.teamName(abbr)), sub, links, k.esc(abbr), colour);
    if (!tm && !row) h += '<div class="card"><div class="pad muted-inline">' + k.notBuilt('The ' + S + ' page for ' + k.teamName(abbr), res[0]) + '</div></div>';
    const ag = t.aggOf(x);
    const pw = k.first(r.mean_wins, (r.odds || {}).mean_wins, (x.sim || {}).mean_wins, r.proj_wins);
    h += k.tiles([
      k.tile('Record', t.recText(rc), k.isNum(rc.diff) ? 'point differential ' + k.signed(rc.diff, 0) : ''),
      k.tile('Rating', k.isNum(R.overall) ? k.signed(R.overall, 1) : '—', 'points per game v an average team'),
      k.tile('Offence', k.isNum(R.off) ? k.signed(R.off, 1) : '—', (k.isNum(R.off_epa) ? k.fmtV(R.off_epa, 'epa') + ' EPA per play' : 'points per game v average') + pillOf(x, 'off_rating')),
      k.tile('Defence', k.isNum(R.def) ? k.signed(R.def, 1) : '—', (k.isNum(R.def_epa) ? k.fmtV(R.def_epa, 'epa') + ' EPA per play allowed' : 'points per game v average') + pillOf(x, 'def_rating')),
      k.tile('Playoffs', k.isNum(od.p_playoffs) ? k.pct(od.p_playoffs, 1) : '—', k.isNum(pw) ? k.num(pw, 1) + ' wins projected' : 'season simulation'),
      k.tile('Super Bowl', k.isNum(od.p_sb) ? k.pct(od.p_sb, 1) : '—', k.isNum(od.p_conf) ? 'conference ' + k.pct(od.p_conf, 1) : ''),
      k.isNum(ag.go) ? k.tile('4th-down go rate', k.pct(ag.go, 0), k.isNum(ag.goWhen) ? 'went ' + k.pct(ag.goWhen, 0) + ' of the times the model said go' : '') : ''
    ]);
    h += '<div class="grid-2"><div class="card"><div class="card-header">Playoff paths <span class="card-sub">Season simulation: the share of runs in which the team reaches each stage, the seed it finishes with, and its final win total.' + magicText(r) + '</span></div><div id="tp-odds"></div><div id="tp-seed" style="height:220px"></div><div id="tp-wins" style="height:200px"></div></div>' +
      '<div class="card"><div class="card-header">QB situation <span class="card-sub">The starter, who is behind him and what a change would mean for the rating; injuries from the latest report.</span></div><div id="tp-qb"></div></div></div>';
    h += '<div class="card"><div class="card-header">Unit ratings through the season <span class="card-sub">Opponent-adjusted EPA per play by unit after each week (time-decayed, with last season\'s regressed prior early on).</span><span class="gq-ctl" id="tp-hist-ctl"></span></div><div id="tp-hist" class="gf-chart"></div></div>';
    h += '<div class="card" id="tp-needs-card"><div class="card-header">Strengths and needs <span class="card-sub" id="tp-needs-sub">Loading…</span></div><div id="tp-needs" class="gq-pad"></div></div>';
    if (cat && cat.metrics && cat.metrics.length && x.pct) h += '<div class="card"><div class="card-header">Team profile <span class="card-sub">Percentiles among the 32 teams on the team catalogue (100 = best).</span></div><div class="gq-pad">' + k.sliders(cat.metrics.filter(m => m.scope !== 'style' && k.isNum((x.pct || {})[m.key])), x.values || {}, x.pct || {}, {}) + '</div></div>';
    h += '<div class="card"><div class="card-header">Tendencies and pace <span class="card-sub">Pass rate over expected by situation; play action, RPO and motion from FTN charting (2022 on); personnel and formation from participation data (2016–2025) or FTN.</span></div><div id="tp-tend"></div></div>';
    h += '<div class="card"><div class="card-header">Fourth downs <span class="card-sub">Every fourth down the team faced, with what our model recommended and the win probability each choice was worth.</span></div><div id="tp-4th"></div></div>';
    h += '<div class="card"><div class="card-header">Schedule against the model <span class="card-sub">Every game with our pre-game win probability and spread beside the closing line; the chart is wins minus the model\'s expected wins.</span></div><div id="tp-sched-c" style="height:220px"></div><div id="tp-sched"></div></div>';
    h += '<div class="card"><div class="card-header">Roster value <span class="card-sub">Gridiron Value this season for the team\'s players in the catalogue (latest team). Click a player for his page.</span></div><div class="grid-2"><div id="tp-roster"></div><div id="tp-roster-c" style="height:380px"></div></div></div>';
    el.innerHTML = h;
    k.setMeta(k.esc(k.teamName(abbr)));
    playoffPaths(x, r, od, colour);
    qbSituation(x, r, S);
    unitHistory(x, r, colour);
    tendencies(x);
    fourth(abbr, x, res[2], S);
    schedule(abbr, x, res[3], S);
    roster(abbr, res[4], S, colour);
    needs(abbr, S);
  });
}

/* Magic numbers and clinch flags: a number or {division, top_seed, playoffs}. */
function magicText(r) {
  const k = K(), L = { division: 'the division', top_seed: 'the 1 seed', playoffs: 'a playoff place', div: 'the division' };
  const parts = [];
  const m = r.magic;
  if (k.isNum(m)) parts.push('Magic number ' + m + '.');
  else if (m && typeof m === 'object') { const xs = Object.keys(m).filter(z => k.isNum(m[z])).map(z => k.esc(L[z] || z) + ' ' + m[z]); if (xs.length) parts.push('Magic numbers: ' + xs.join(', ') + '.'); }
  const flags = (o, word) => { if (o === true) return word + '.'; if (o && typeof o === 'object') { const xs = Object.keys(o).filter(z => o[z] === true).map(z => L[z] || z); return xs.length ? word + ' ' + xs.join(', ') + '.' : ''; } return typeof o === 'string' && o ? word + ' ' + k.esc(o) + '.' : ''; };
  parts.push(flags(r.clinched, 'Clinched'), flags(r.eliminated, 'Eliminated from'));
  const t = parts.filter(Boolean).join(' ');
  return t ? ' ' + t : '';
}
function pillOf(x, key) { const k = K(), pc = ((x || {}).pct || {})[key]; return k.isNum(pc) ? ' ' + k.pill(pc) : ''; }

function playoffPaths(x, r, od, colour) {
  const k = K(), t = T();
  const host = k.$('tp-odds');
  if (!host) return;
  const list = t.ODDS.filter(o => k.isNum(od[o[0]]));
  host.innerHTML = list.length ? '<div class="gq-odds">' + list.map(o => '<div class="gq-odd"><span>' + k.esc(o[1]) + '</span><div class="gq-odd-bar"><i style="width:' + (100 * od[o[0]]).toFixed(1) + '%;background:' + colour + '"></i></div><strong>' + k.pct(od[o[0]], 1) + '</strong></div>').join('') + '</div>'
    : k.muted('Simulation odds are not available yet.');
  const sim = Object.assign({}, x.sim || {}, x.odds || {}, r.odds || {}, r);
  const sd = sim.seed_dist || sim.seeds || x.seed_dist || r.seed_dist;
  const seedNode = k.$('tp-seed');
  const distOf = d => (Array.isArray(d) ? d.map((p, i) => [i + 1, p]) : (d && typeof d === 'object' ? Object.keys(d).map(s => [s, d[s]]) : []));
  const sv = distOf(sd).filter(z => k.isNum(z[1]));
  if (sv.length) {
    const label = s => (/^(0|out|none|miss|8|9|1[0-6])$/.test(String(s)) && !/^[1-7]$/.test(String(s)) ? 'Out' : 'Seed ' + s);
    k.plot(seedNode, [{ type: 'bar', x: sv.map(z => label(z[0])), y: sv.map(z => z[1]), marker: { color: sv.map(z => (label(z[0]) === 'Out' ? '#6e7681' : colour)) }, hovertemplate: '%{x}: %{y:.1%}<extra></extra>' }],
      k.layout({ margin: { l: 44, r: 10, t: 24, b: 30 }, title: { text: 'Final seed', font: { size: 11, color: k.C.text2 }, x: 0.02 }, yaxis: { tickformat: '.0%' }, xaxis: { type: 'category' } }));
  } else seedNode.style.display = 'none';
  const wd = sim.win_dist || sim.wins_dist || x.win_dist || r.win_dist;
  const wv = distOf(wd).map(z => [Number(Array.isArray(wd) ? z[0] - 1 : z[0]), z[1]]).filter(z => k.isNum(z[0]) && k.isNum(z[1]));
  const wNode = k.$('tp-wins');
  if (wv.length) {
    const line = k.first((x.market || {}).win_total, (x.markets || {}).win_total, r.win_total_line);
    k.plot(wNode, [{ type: 'bar', x: wv.map(z => z[0]), y: wv.map(z => z[1]), marker: { color: k.alpha(colour, 0.75) }, hovertemplate: '%{x} wins: %{y:.1%}<extra></extra>' }],
      k.layout({ margin: { l: 44, r: 10, t: 24, b: 30 }, title: { text: 'Final wins' + (k.isNum(line) ? ' (dashed: market win total ' + line + ')' : ''), font: { size: 11, color: k.C.text2 }, x: 0.02 }, yaxis: { tickformat: '.0%' }, xaxis: { dtick: 1 },
        shapes: k.isNum(line) ? [{ type: 'line', x0: line, x1: line, yref: 'paper', y0: 0, y1: 1, line: { color: '#e6edf3', dash: 'dash', width: 1 } }] : [] }));
  } else wNode.style.display = 'none';
}

function qbSituation(x, r, S) {
  const k = K(), host = k.$('tp-qb');
  if (!host) return;
  const q = x.qb || x.qb_situation || x.qbs || r.qb || null;
  if (!q || (Array.isArray(q) && !q.length)) { host.innerHTML = k.muted('The QB situation is not available yet.'); return; }
  let h = '';
  const list = Array.isArray(q) ? q : (q.depth || q.qbs || q.list || []);
  const sl = list.find(p => p && p.started_last);
  const starter = q.starter || q.current || (sl && (sl.pid || sl.id)) || (list[0] && (list[0].pid || list[0].id));
  const sid = typeof starter === 'object' && starter ? (starter.pid || starter.id) : starter;
  const tiles = [];
  if (sid) tiles.push(k.tile('Starter', k.playerLink(sid, (starter && starter.name) || null, S), [q.status ? k.esc(q.status) : '', k.isNum(q.games_started) ? q.games_started + ' starts' : ''].filter(Boolean).join(' · ')));
  [['value', 'QB value', 'signed1', 'points per game v average'], ['rating', 'QB component', 'signed1', 'of the team rating'], ['change_impact', 'If the backup starts', 'signed1', 'change in the spread (points)'], ['backup_drop', 'Backup drop-off', 'signed1', 'points per game']].forEach(z => {
    const v = k.first(q[z[0]]); if (k.isNum(v)) tiles.push(k.tile(z[1], k.fmtV(v, z[2]), z[3]));
  });
  if (tiles.length) h += k.tiles(tiles);
  const L = k.listOf(list).map(p => Object.assign({ pid: p.pid || p.id || p.gsis_id }, p));
  if (L.length) {
    h += k.table([{ label: 'QB' }, { label: 'Role' }, { label: 'Games', align: 'right' }, { label: 'Dropbacks', align: 'right' }, { label: 'EPA/db', align: 'right' }, { label: 'Composite', align: 'right', title: 'QB composite, 100 = average' }, { label: 'CPOE', align: 'right' }, { label: 'Value', align: 'right' }, { label: 'Status' }],
      L.map(p => [{ v: p.name || k.name(p.pid), html: k.playerLink(p.pid, p.name, S) }, { v: p.role || p.depth || '', html: k.esc(p.role || (p.started_last ? 'Started last game' : (k.isNum(p.depth) ? 'QB' + p.depth : p.depth || ''))) },
        { v: k.first(p.starts, p.gs, p.games), html: k.int(k.first(p.starts, p.gs, p.games)) }, { v: k.first(p.dropbacks, p.db), html: k.int(k.first(p.dropbacks, p.db)) },
        { v: k.first(p.epa_db, p.epa_per_db, p.epa_play), html: k.fmtV(k.first(p.epa_db, p.epa_per_db, p.epa_play), 'epa') }, { v: p.composite, html: k.isNum(p.composite) ? k.num(p.composite, 0) : '—' }, { v: p.cpoe, html: k.fmtV(p.cpoe, 'signed1') },
        { v: k.first(p.value), html: k.fmtV(k.first(p.value), 'signed1') }, { v: p.status || p.injury || '', html: p.status || p.injury ? '<span class="chip' + (/out|ir|doubt/i.test(p.status || p.injury) ? ' warn' : '') + '">' + k.esc(p.status || p.injury) + '</span>' : '' }]), { compact: true });
  }
  const inj = k.listOf(x.injuries || q.injuries);
  if (inj.length) h += '<div class="gq-sub-head">Injury report</div>' + k.table([{ label: 'Player' }, { label: 'Pos' }, { label: 'Status' }, { label: 'Injury' }],
    inj.slice(0, 20).map(p => [{ v: p.name || '', html: p.pid || p.gsis_id ? k.playerLink(p.pid || p.gsis_id, p.name, S) : k.esc(p.name || '') }, { v: p.pos || '', html: k.esc(p.pos || '') }, { v: p.status || '', html: k.esc(p.status || p.report_status || '') }, { v: p.injury || '', html: k.esc(p.injury || p.body_part || '') }]), { compact: true });
  if (q.note) h += '<div class="pg-note gq-note">' + k.esc(q.note) + '</div>';
  host.innerHTML = h || k.muted('The QB situation is not available yet.');
}

function unitHistory(x, r, colour) {
  const k = K(), t = T(), node = k.$('tp-hist'), ctl = k.$('tp-hist-ctl');
  if (!node) return;
  const raw = x.history || x.ratings_history || (x.ratings || {}).history || r.history;
  let rows = [];
  if (raw && !Array.isArray(raw) && typeof raw === 'object' && !(raw.cols || raw.fields) && Object.keys(raw).some(u => Array.isArray(raw[u]))) {
    // {week: [...], off: [...], def: [...]}
    const wk = raw.week || raw.weeks || raw.x;
    if (Array.isArray(wk)) rows = wk.map((w, i) => { const o = { week: w }; Object.keys(raw).forEach(u => { if (Array.isArray(raw[u]) && raw[u] !== wk) o[u] = raw[u][i]; }); return o; });
  } else if (Array.isArray(raw) && raw.length && Array.isArray(raw[0])) {
    const hc = x.history_cols || r.history_cols || ['week', 'net', 'off', 'def'];
    rows = raw.map(a => { const o = {}; hc.forEach((c, i) => { o[c] = a[i]; }); return o; });
  } else rows = k.listOf(raw);
  rows = rows.map(z => Object.assign({ week: k.first(z.week, z.wk, z.w) }, t.unitsOf(z))).filter(z => k.isNum(z.week)).sort((a, b) => a.week - b.week);
  if (rows.length < 2) { node.innerHTML = k.muted('Rating history starts after week 2.'); node.style.height = 'auto'; return; }
  const sets = { main: ['off', 'def', 'st'], overall: ['overall'], pass: ['pass_off', 'pass_def'], rush: ['rush_off', 'rush_def'] };
  const avail = Object.keys(sets).filter(s => sets[s].some(u => rows.some(z => k.isNum(z[u]))));
  if (ctl) ctl.innerHTML = k.toggle('tp-hist-t', avail.map(s => [s, { main: 'Units', pass: 'Pass', rush: 'Rush', overall: 'Overall' }[s]]), avail[0]);
  const COL = { off: colour, def: '#58a6ff', st: '#d29922', pass_off: colour, pass_def: '#58a6ff', rush_off: colour, rush_def: '#58a6ff', overall: colour };
  const draw = s => {
    const us = sets[s].filter(u => rows.some(z => k.isNum(z[u])));
    k.plot(node, us.map(u => ({ type: 'scatter', mode: 'lines+markers', name: (t.UNITS.find(z => z[0] === u) || [u, u])[1], x: rows.map(z => z.week), y: rows.map(z => z[u]), line: { color: COL[u], width: 2, dash: /def/.test(u) ? 'dot' : 'solid' }, hovertemplate: 'Week %{x}: %{y:+.3f}<extra>%{fullData.name}</extra>' })),
      k.layout(Object.assign({ margin: { l: 50, r: 10, t: 30, b: 36 }, xaxis: { title: 'Week', dtick: 1 }, yaxis: { title: s === 'overall' || s === 'main' ? 'Points per game v average' : 'EPA per play', zeroline: true, zerolinecolor: '#6e7681' } }, k.legendTop())));
  };
  draw(avail[0]);
  k.wireToggle(document, 'tp-hist-t', draw);
}

const SIT_LABEL = { proe: 'All plays', proe_neutral: 'Neutral early downs', proe_3rd: '3rd down', proe_rz: 'Red zone', proe_lead: 'Leading by 8+', proe_trail: 'Trailing by 8+', all: 'All plays', early: 'Early downs', early_down: 'Early downs', first: '1st down', second: '2nd down', third: '3rd down', third_long: '3rd and long', red_zone: 'Red zone', rz: 'Red zone', leading: 'Leading', trailing: 'Trailing', neutral: 'Neutral (WP 20–80%)', two_minute: 'Two-minute', q4: '4th quarter', '1st_down': '1st down', '2nd_down': '2nd down', '3rd_down': '3rd down', '2nd_long': '2nd and long', '2nd_short': '2nd and short' };
function tendencies(x) {
  const k = K(), host = k.$('tp-tend');
  if (!host) return;
  const td = Object.assign({}, x.tendencies || x.tendency || {});
  const v = x.values || {};
  let h = '';
  const tiles = [];
  [['proe', 'PROE', 'pct', 'pass rate over expected, all plays'], ['proe_neutral', 'PROE (neutral)', 'pct', 'early downs, WP 20–80%'], ['pass_rate', 'Pass rate', 'pct', ''], ['pa_rate', 'Play action', 'pct', 'per dropback, FTN'], ['rpo_rate', 'RPO', 'pct', 'per play, FTN'], ['motion_rate', 'Motion', 'pct', 'per play, FTN'], ['screen_rate', 'Screens', 'pct', 'per attempt, FTN'],
    ['shotgun', 'Shotgun', 'pct', ''], ['no_huddle', 'No huddle', 'pct', ''], ['sec_per_play_neutral', 'Seconds per play', '1', 'neutral situations'], ['sec_per_play', 'Seconds per play (all)', '1', ''], ['plays_pg', 'Plays per game', '1', ''],
    ['blitz_rate', 'Blitz rate (defence)', 'pct', 'FTN'], ['box_avg', 'Box count (defence)', '2', 'average defenders'], ['man_rate', 'Man coverage (defence)', 'pct', 'participation']].forEach(z => {
    const val = k.first(td[z[0]], (td.pace || {})[z[0]], (x.pace || {})[z[0]], v[z[0]]);
    const rk = (x.rank || {})[z[0]];
    if (k.isNum(val)) tiles.push(k.tile(z[1], /^proe/.test(z[0]) ? k.signed(val * 100, 1) + '<span class="kpi-dim"> pp</span>' : k.fmtV(val, z[2]), z[3] + (k.isNum(rk) ? ' · <span class="gf-rank">#' + rk + '</span>' : '')));
  });
  if (tiles.length) h += k.tiles(tiles);
  let sit = td.proe_by_situation || td.proe_situation || td.by_situation || td.proe_sit;
  if (!sit) { const o = {}; ['proe', 'proe_neutral', 'proe_3rd', 'proe_rz', 'proe_lead', 'proe_trail'].forEach(z => { if (k.isNum(v[z])) o[z] = v[z]; }); if (Object.keys(o).length > 1) sit = o; }
  if (sit && typeof sit === 'object') h += '<div id="tp-proe" style="height:260px"></div>';
  const tab = (obj, first, fmtc) => {
    const rows = k.listOf(obj, 'name').map(z => Object.assign({}, z, { name: z.name || z.group || z.key || '' }, { group: undefined }));
    if (!rows.length && obj && typeof obj === 'object') { Object.keys(obj).forEach(n => { if (k.isNum(obj[n])) rows.push({ name: n, rate: obj[n] }); }); }
    if (!rows.length) return '';
    const keys = [];
    rows.forEach(z => Object.keys(z).forEach(c => { if (c !== 'name' && k.isNum(z[c]) && keys.indexOf(c) < 0) keys.push(c); }));
    return k.table([{ label: first }].concat(keys.map(c => ({ label: tLabel(c), align: 'right' }))), rows.map(z => [{ v: z.name, html: '<strong>' + k.esc(fmtc ? fmtc(z.name) : z.name) + '</strong>' }].concat(keys.map(c => ({ v: z[c], html: k.fmtV(z[c], tFmt(c, z[c])) })))), { compact: true });
  };
  const pers = tab(td.personnel || x.personnel, 'Personnel', n => (/^\d\d$/.test(n) ? n + ' (' + n.charAt(0) + ' RB, ' + n.charAt(1) + ' TE)' : n));
  const form = tab(td.formation || td.formations || x.formation, 'Formation', n => K().titleCase(n));
  const pa = tab(td.play_action_detail || td.pa || null, 'Play action', n => K().titleCase(n));
  if (pers || form) h += '<div class="grid-2"><div>' + (pers ? '<div class="gq-sub-head">Personnel</div>' + pers : '') + '</div><div>' + (form ? '<div class="gq-sub-head">Formation</div>' + form : '') + '</div></div>';
  if (pa) h += '<div class="gq-sub-head">Play action</div>' + pa;
  host.innerHTML = h || k.muted('Tendencies are not available yet.');
  if (sit && typeof sit === 'object') {
    const rows = k.listOf(sit, 'name').map(z => ({ name: z.name || z.situation || z.key, v: k.first(z.proe, z.value, z.v, z.rate), n: k.first(z.n, z.plays) }));
    if (!rows.length) Object.keys(sit).forEach(n => { if (k.isNum(sit[n])) rows.push({ name: n, v: sit[n] }); });
    const ok = rows.filter(z => k.isNum(z.v));
    if (ok.length) k.plot('tp-proe', [{ type: 'bar', orientation: 'h', y: ok.map(z => SIT_LABEL[z.name] || k.titleCase(z.name)), x: ok.map(z => z.v * 100), marker: { color: ok.map(z => (z.v >= 0 ? K().ACC : '#58a6ff')) }, text: ok.map(z => (k.isNum(z.n) ? z.n + ' plays' : '')), hovertemplate: '%{y}: %{x:+.1f} pp<br>%{text}<extra></extra>' }],
      k.layout({ margin: { l: 130, r: 16, t: 24, b: 34 }, title: { text: 'Pass rate over expected by situation (pp; pass-heavy right)', font: { size: 11, color: k.C.text2 }, x: 0.02 }, xaxis: { zeroline: true, zerolinecolor: '#6e7681', ticksuffix: '' }, yaxis: { autorange: 'reversed', automargin: true } }));
  }
}
function tLabel(c) { return { rate: 'Rate', share: 'Share', n: 'Plays', plays: 'Plays', epa: 'EPA/play', epa_play: 'EPA/play', success: 'Success', pass_rate: 'Pass rate', proe: 'PROE', ypp: 'Yds/play' }[c] || K().titleCase(c); }
function tFmt(c, v) { if (/^(n|plays|count)$/.test(c)) return 'int'; if (/epa/.test(c)) return 'epa'; if (/proe/.test(c)) return 'pp'; if (/rate|share|success|pct/.test(c) && Math.abs(v) <= 1.5) return 'pct'; return '2'; }

function fourth(abbr, x, fd, S) {
  const k = K(), host = k.$('tp-4th');
  if (!host) return;
  const t = T(), ag = t.aggOf(x);
  const F = GI.fk.F;
  let h = '';
  const tiles = [];
  if (k.isNum(ag.go)) tiles.push(k.tile('Went for it', k.pct(ag.go, 0), 'of fourth downs (not end-of-half or desperation)' + pillOf(x, 'go_rate')));
  if (k.isNum(ag.goWhen)) tiles.push(k.tile('Went when the model said go', k.pct(ag.goWhen, 0), pillOf(x, 'go_rate_rec')));
  if (k.isNum(ag.goe)) tiles.push(k.tile('Go rate over expected', k.signed(ag.goe * 100, 1) + '<span class="kpi-dim"> pp</span>', 'against the league in the same situations'));
  if (k.isNum(ag.lost)) tiles.push(k.tile('Win probability lost', k.num(ag.lost * 100, 1) + '<span class="kpi-dim"> pp</span>', 'summed, against the best choice each time' + pillOf(x, 'fd_wp_lost')));
  if (tiles.length) h += k.tiles(tiles);
  const plays = F && typeof F.playsOf === 'function' ? F.playsOf(fd).filter(p => p.team === abbr) : [];
  if (plays.length) {
    h += '<div id="tp-4th-t"></div>';
    host.innerHTML = h;
    F.table(k.$('tp-4th-t'), plays, S, { team: false, max: 60 });
  } else host.innerHTML = h + k.muted(fd && fd.ok !== false ? 'No fourth downs for this team yet.' : 'The fourth-down file is not available yet.');
}

function schedule(abbr, x, sch, S) {
  const k = K(), host = k.$('tp-sched'), cnode = k.$('tp-sched-c');
  if (!host) return;
  let games = k.listOf(x.schedule || x.games);
  if (!games.length && sch && sch.ok !== false) games = k.listOf(sch.games || sch).filter(g => g.home === abbr || g.away === abbr);
  if (!games.length) { host.innerHTML = k.muted('The schedule is not available yet.'); cnode.style.display = 'none'; return; }
  const rows = games.map(g => {
    const home = g.home !== undefined ? g.home === abbr || g.home === true : (g.side === 'home' || g.is_home === true);
    const opp = g.opp || g.opponent || (g.home === abbr ? g.away : g.home);
    const m = g.model || {}, mk = g.market || {}, ln = k.isNum(g.line) ? { spread_home: g.line } : (g.line || g.lines || {});
    const pTeam = k.first(g.p_win, g.model_p, k.isNum(m.p_home) ? (home ? m.p_home : 1 - m.p_home) : null);
    const pMk = k.first(g.market_p, k.isNum(mk.p_home) ? (home ? mk.p_home : 1 - mk.p_home) : null);
    const spHome = k.first(ln.spread_home, (ln.close || {}).spread_home, g.spread_home);
    const close = k.isNum(spHome) ? (home ? spHome : -spHome) : k.first(g.spread, g.line_team);
    const mSp = k.first(g.model_spread, k.isNum(m.spread) ? (home ? m.spread : -m.spread) : null);
    const pf = k.first(g.pf, g.team_score, home ? g.hs : g.as), pa = k.first(g.pa, g.opp_score, home ? g.as : g.hs);
    const fin = k.isNum(pf) && k.isNum(pa) && (g.status === undefined || /final|post|done|complete/i.test(String(g.status)) || g.result);
    return { gid: g.game_id || g.id, week: k.first(g.week, k.parseGid(g.game_id).week), home: home, opp: opp, p: pTeam, pm: pMk, close: close, msp: mSp, pf: pf, pa: pa, fin: !!fin, gtype: g.gtype };
  }).sort((a, b) => (a.week || 0) - (b.week || 0));
  const res = z => (!z.fin ? '' : (z.pf > z.pa ? 'W' : z.pf < z.pa ? 'L' : 'T') + ' ' + z.pf + '–' + z.pa);
  host.innerHTML = k.table([{ label: 'Wk' }, { label: 'Opponent' }, { label: 'Model', align: 'right', title: 'Our pre-game win probability' }, { label: 'Market', align: 'right', title: 'De-vigged market win probability' }, { label: 'Model line', align: 'right', title: 'Our spread for this team (negative = favoured)' }, { label: 'Close', align: 'right', title: 'Closing spread for this team' }, { label: 'Result' }, { label: 'v close', align: 'right', title: 'Margin against the closing spread (positive = covered)' }],
    rows.map(z => { const ats = z.fin && k.isNum(z.close) ? (z.pf - z.pa) + z.close : null;
      return [{ v: z.week, html: '<strong>' + k.esc(z.week === null ? '—' : z.week) + '</strong>' }, { v: z.opp, html: (z.home ? 'v ' : '@ ') + k.teamChip(z.opp, S) },
        { v: z.p, html: k.isNum(z.p) ? k.pct(z.p, 0) : '—' }, { v: z.pm, html: k.isNum(z.pm) ? k.pct(z.pm, 0) : '—' }, { v: z.msp, html: k.isNum(z.msp) ? k.signed(z.msp, 1) : '—' }, { v: z.close, html: k.isNum(z.close) ? k.signed(z.close, 1) : '—' },
        { v: res(z), html: z.gid ? '<a href="' + k.gameHref(z.gid, S) + '">' + k.esc(res(z) || 'Preview') + '</a>' : k.esc(res(z)) },
        { v: ats, html: k.isNum(ats) ? '<span class="' + (ats > 0 ? 'gq-ok' : ats < 0 ? 'gq-no' : '') + '">' + k.signed(ats, 1) + '</span>' : '' }]; }), { compact: true });
  k.sortable(host);
  const done = rows.filter(z => z.fin && k.isNum(z.p));
  if (done.length < 2) { cnode.style.display = 'none'; return; }
  let cw = 0, ce = 0;
  const xs = [], ys = [], ts = [];
  done.forEach(z => { cw += z.pf > z.pa ? 1 : z.pf === z.pa ? 0.5 : 0; ce += z.p; xs.push(z.week); ys.push(cw - ce); ts.push('Week ' + z.week + ' ' + (z.home ? 'v ' : '@ ') + z.opp + ': ' + res(z) + ' · model ' + k.pct(z.p, 0)); });
  k.plot(cnode, [{ type: 'scatter', mode: 'lines+markers', x: xs, y: ys, text: ts, hovertemplate: '%{text}<br>wins over expected %{y:+.2f}<extra></extra>', line: { color: k.ACC, width: 2, shape: 'hv' }, fill: 'tozeroy', fillcolor: k.alpha(k.ACC, 0.12) }],
    k.layout({ margin: { l: 50, r: 10, t: 10, b: 34 }, xaxis: { title: 'Week', dtick: 1 }, yaxis: { title: 'Wins − expected', zeroline: true, zerolinecolor: '#6e7681' } }));
}

function roster(abbr, raw, S, colour) {
  const k = K(), host = k.$('tp-roster'), cnode = k.$('tp-roster-c');
  if (!host) return;
  const cat = k.catOf(raw);
  if (!cat) { host.innerHTML = k.notBuilt('The player catalogue', raw); cnode.style.display = 'none'; return; }
  k.learnCat(cat);
  const P = cat.players;
  const mine = Object.keys(P).filter(id => P[id].team === abbr).map(id => ({ id: id, p: P[id], g: k.groupOf(P[id].pos, P[id].group), v: k.first((P[id].values || {}).value, (P[id].values || {}).def_value, (P[id].values || {}).pts_oe) }));
  if (!mine.length) { host.innerHTML = k.muted('No players for this team in the catalogue yet.'); cnode.style.display = 'none'; return; }
  mine.sort((a, b) => (k.isNum(b.v) ? b.v : -1e9) - (k.isNum(a.v) ? a.v : -1e9));
  host.innerHTML = k.table([{ label: 'Player' }, { label: 'Pos' }, { label: 'G', align: 'right' }, { label: 'Value', align: 'right', title: 'Gridiron Value (EPA credited, adjusted); defenders: splash EPA; kickers: points over expected' }, { label: 'Pct', align: 'right', title: 'Percentile in his group' }],
    mine.slice(0, 30).map(z => ({ _href: k.playerHref(z.id, S), cells: [{ v: z.p.name || k.name(z.id), html: k.playerLink(z.id, z.p.name, S) }, { v: z.p.pos || z.g, html: k.esc(z.p.pos || z.g) }, { v: z.p.games, html: k.int(z.p.games) },
      { v: z.v, html: k.isNum(z.v) ? k.signed(z.v, 1) : '—' }, { v: k.first((z.p.pct || {}).value, (z.p.pct || {}).def_value, (z.p.pct || {}).pts_oe), html: k.pill(k.first((z.p.pct || {}).value, (z.p.pct || {}).def_value, (z.p.pct || {}).pts_oe)) }] })), { compact: true, sticky: true });
  k.sortable(host);
  const by = {};
  mine.forEach(z => { if (k.isNum(z.v)) by[z.g] = (by[z.g] || 0) + z.v; });
  const gs = k.GROUPS.filter(g => k.isNum(by[g]));
  if (!gs.length) { cnode.style.display = 'none'; return; }
  const top = mine.filter(z => k.isNum(z.v)).slice(0, 12);
  k.plot(cnode, [{ type: 'bar', orientation: 'h', y: top.map(z => k.surname(z.p.name || k.name(z.id)) + ' (' + (z.p.pos || z.g) + ')'), x: top.map(z => z.v), customdata: top.map(z => k.playerHref(z.id, S)),
    marker: { color: top.map(z => (z.v >= 0 ? k.alpha(colour, 0.85) : 'rgba(248,81,73,0.8)')) }, hovertemplate: '%{y}: %{x:+.1f}<extra></extra>' }],
    k.layout({ margin: { l: 130, r: 16, t: 24, b: 34 }, title: { text: 'Top contributors (value)', font: { size: 11, color: k.C.text2 }, x: 0.02 }, yaxis: { autorange: 'reversed', automargin: true }, xaxis: { zeroline: true, zerolinecolor: '#6e7681' } }));
  k.clickThrough(cnode);
}

/* Strengths and needs: data/<S>/needs/<abbr>.json (the current season only). */
const GRADE_COLOUR = { A: '#3fb950', B: '#7ee787', C: '#d29922', D: '#f97316', F: '#f85149' };
function gradeChip(g) { return g ? '<span class="gt-grade" style="background:' + (GRADE_COLOUR[g] || '#30363d') + '">' + g + '</span>' : '<span class="muted-inline">—</span>'; }
function needs(abbr, S) {
  const k = K();
  const card = k.$('tp-needs-card');
  k.loadY(S, 'needs/' + abbr + '.json').then(d => {
    if (!k.$('tp-needs')) return;
    if (!k.ok(d) || !d.units) {
      if (card) card.style.display = 'none';
      return;
    }
    const fmtU = u => (u.fmt === 'pct' ? k.pct(u.value, 1) : u.fmt === 'epa' ? k.signed(u.value, 3) : k.signed(u.value, 2));
    const units = k.table([{ label: 'Unit', sortable: false }, { label: 'Value', align: 'right' }, { label: 'Pct', align: 'right' }, { label: 'Grade', align: 'right' }, { label: 'Measured as', sortable: false }],
      d.units.map(u => ({ cells: [{ v: u.label, html: k.esc(u.label) }, { v: u.value, html: fmtU(u) }, { v: u.pct, html: k.pill(u.pct) }, { v: u.grade || '', html: gradeChip(u.grade) },
        { v: '', html: '<span class="muted-inline">' + k.esc(u.stat || '') + (u.lower ? ' (lower is better)' : '') + '</span>' }] })), { compact: true });
    const pos = k.table([{ label: 'Position', sortable: false }, { label: 'Value', align: 'right', title: 'Points a game above replacement among the starters (QB: the model QB term)' }, { label: 'Pct', align: 'right' }, { label: 'Grade', align: 'right' }, { label: 'Starters (value a game)', sortable: false }],
      d.positions.map(x => ({ cells: [{ v: x.label, html: k.esc(x.label) }, { v: x.value, html: k.signed(x.value, 2) }, { v: x.pct, html: k.pill(x.pct) }, { v: x.grade || '', html: gradeChip(x.grade) },
        { v: '', html: (x.players || []).map(p => k.playerLink(p[0], p[1], S) + ' <span class="muted-inline">' + (x.pos === 'QB' ? (k.isNum(p[3]) ? k.signed(p[3], 3) + ' EPA/db' : '') : (k.isNum(p[2]) ? k.signed(p[2], 2) : '')) + '</span>').join(', ') +
          ((x.ir || []).length ? ' <span class="gq-tag">IR: ' + x.ir.map(p => k.esc(p[1])).join(', ') + '</span>' : '') }] })).concat([{ cells: [{ v: 'OL', html: 'Offensive line' }, { v: '', html: '—' }, { v: '', html: '—' }, { v: '', html: '<span class="muted-inline">n/a</span>' },
        { v: '', html: '<span class="muted-inline">' + k.esc((d.ol || {}).note || '') + '</span>' }] }]), { compact: true });
    const sw = (list, cls) => list.length ? list.map(z => '<div class="tn-item ' + cls + '">' + gradeChip(z.grade) + ' <strong>' + k.esc(z.label) + '</strong> <span class="muted-inline">' + k.ordinal(z.pct) + ' percentile</span><div class="tn-ev">' + k.esc(z.evidence || '') + '</div></div>').join('') : k.muted('None stands out.');
    const imp = (d.improve || []).map(w => {
      const head = '<div class="tn-imp-h">To improve: <strong>' + k.esc(w.label) + '</strong></div>';
      if (w.note) return head + k.muted(k.esc(w.note));
      const tradeHref = c => '#/trade?t=' + abbr + ',' + c.team + '&m=' + encodeURIComponent(c.pid) + ':' + abbr;
      const rowsOf = (list, free) => list.map(c => ({ cells: [{ v: c.name, html: k.playerLink(c.pid, c.name, S) + ' <span class="muted-inline">' + k.esc(c.pos) + '</span>' },
        { v: c.team || '', html: free ? '<span class="muted-inline">unsigned' + (c.last_season ? ' (values from ' + c.last_season + ')' : '') + '</span>' : k.teamChip(c.team, S) },
        { v: c.age, html: k.num(c.age, 0) }, { v: c.gain_pg, html: '<strong>' + k.signed(c.gain_pg, 2) + '</strong>' }, { v: c.d_wins, html: k.isNum(c.d_wins) ? k.signed(c.d_wins, 2) : '—' },
        { v: c.d_playoffs, html: k.isNum(c.d_playoffs) ? k.signed(100 * c.d_playoffs, 1) + ' pp' : '—' },
        { v: c.seller_cost_pg, html: free ? '—' : k.signed(-c.seller_cost_pg, 2) },
        { v: '', html: '<span class="muted-inline">' + k.esc((c.hints || []).join('; ')) + '</span>' + (k.isNum(c.cap_hit) ? ' <span class="muted-inline">cap $' + k.num(c.cap_hit, 1) + 'M</span>' : '') + (free ? '' : ' <a href="' + tradeHref(c) + '">Simulate →</a>') }] }));
      const cols = [{ label: 'Player', sortable: false }, { label: 'Team' }, { label: 'Age', align: 'right' }, { label: 'Gain', align: 'right', title: 'Points a game this team would gain (k_resp x the change in position value)' },
        { label: 'Wins', align: 'right', title: 'Change in expected wins over the rest of the season' }, { label: 'Playoffs', align: 'right' }, { label: 'Seller', align: 'right', title: 'Points a game his team would lose' }, { label: 'Notes', sortable: false }];
      const all = rowsOf(w.candidates || [], false).concat(rowsOf(w.unsigned || [], true));
      return head + (all.length ? k.table(cols, all, { compact: true }) : k.muted('No player on another roster would improve the position by our values.'));
    }).join('');
    k.set('tp-needs', '<div class="tn-label">' + k.esc(d.label || '') + '</div>' +
      '<div class="grid-2"><div><div class="gt-sub">Top strengths</div>' + sw(d.strengths || [], 'tn-good') + '</div><div><div class="gt-sub">Top weaknesses</div>' + sw(d.weaknesses || [], 'tn-bad') + '</div></div>' +
      '<div class="gt-sub">Units against the league</div>' + units + '<div class="gt-sub">Positions against the league</div>' + pos +
      '<div class="gt-sub">Ways to improve</div>' + (imp || k.muted('No weakness below the 40th percentile.')) +
      '<div class="pg-note gq-note">Grades: A from the 80th percentile, B 60th, C 40th, D 20th, F below, among the 32 teams. Positions are graded on the per-game value above replacement of the current starters (latest nflverse roster; injured reserve left out). ' +
      'Gain: what the player adds here (he replaces the weakest starter if he is better) times the game model\'s response (' + k.num(d.k_resp, 2) + '); wins and playoff odds from the season simulation\'s sensitivity curve' + (k.isNum(d.remaining) ? ', ' + d.remaining + ' games left' : '') + '. ' +
      (d.contracts && !d.contracts.enabled ? k.esc(d.contracts.note || '') : '') + ' <a href="#/value">Player value →</a> · <a href="#/trade?t=' + abbr + '">Trade simulator →</a></div>');
    k.set('tp-needs-sub', 'Grades against the league, the three biggest strengths and weaknesses, and who could help' + (d.basis_season && d.basis_season !== S ? ' (on ' + d.basis_season + ' values)' : ''));
  });
}

if (typeof GI.route === 'function') { try { GI.route('team', render); } catch (e) { /* bound */ } }
})(window.GI || (window.GI = {}));
