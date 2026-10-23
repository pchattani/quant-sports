/* The Quant Bullpen — teams: the catalogue (#/<L>/teams) and the team page (#/<L>/team/<tid>).
 *
 * Team page: record and ratings, playoff odds from the season simulation, the team catalogue as
 * percentile sliders, roster value (Bullpen WAR and projections), the projected lineup and
 * rotation, bullpen availability (recent pitch counts and rest), defensive alignment tendencies,
 * the home park's factors, and the schedule log set against the game model.
 *
 * Data: data/<L>/<S>/teams.json ({"metrics": [METRIC], "teams": {tid: {"name", "values", "pct",
 * "log", "roster", "park", ...}}}), data/<L>/<S>/season.json (standings, ratings, odds),
 * data/<L>/<S>/parks.json. Uses BP.gk. */
(function (BP) {
'use strict';

const K = () => BP.gk;
const TPREFS = ['rating', 'off_rpg', 'def_rpg', 'pit_rpg', 'war', 'xwoba_plus', 'pitching_plus', 'stuff_plus', 'fielding_runs', 'framing_runs'];

/* tid -> standings/odds row from season.json, whatever its arrangement. */
function seasonRows(season) {
  const k = K(), out = {};
  if (!season || season.ok === false) return out;
  const put = (tid, r) => { if (tid === undefined || tid === null || !r) return; out[String(tid)] = Object.assign({}, out[String(tid)] || {}, r); };
  const walk = list => (list || []).forEach(r => { if (r && typeof r === 'object') put(r.tid || r.team || r.id, r); });
  const st = season.standings;
  if (Array.isArray(st)) st.forEach(d => { if (d && Array.isArray(d.teams)) walk(d.teams.map(t => Object.assign({ division: d.division || d.name }, t))); else if (d && (d.tid || d.team)) put(d.tid || d.team, d); });
  else if (st && typeof st === 'object') Object.keys(st).forEach(div => { const v = st[div]; if (Array.isArray(v)) walk(v.map(t => Object.assign({ division: div }, t))); else if (v && Array.isArray(v.teams)) walk(v.teams.map(t => Object.assign({ division: div }, t))); });
  ['teams', 'odds', 'ratings', 'sim'].forEach(key => {
    const v = season[key];
    if (v && typeof v === 'object' && !Array.isArray(v)) Object.keys(v).forEach(t => { if (v[t] && typeof v[t] === 'object') put(t, key === 'ratings' ? { ratings: v[t] } : v[t]); });
    else if (Array.isArray(v)) walk(v);
  });
  Object.keys(out).forEach(t => { const r = out[t]; if (r.odds && typeof r.odds === 'object') Object.assign(r, r.odds); if (r.ratings && typeof r.ratings === 'object') Object.assign(r, r.ratings); });
  return out;
}
const ODDS = [['p_playoffs', 'Postseason', ['p_postseason', 'p_playoffs', 'p_playoff', 'make_playoffs']], ['p_division', 'Division', ['p_division', 'p_div']], ['p_wildcard', 'Wild card', ['p_wildcard', 'p_wc']], ['p_bye', 'Bye', ['p_bye']],
  ['p_ds', 'Division Series', ['p_ds', 'p_alds', 'p_nlds']], ['p_cs', 'LCS', ['p_lcs', 'p_cs']], ['p_pennant', 'Pennant', ['p_pennant', 'p_ws_app']], ['p_ws', 'World Series', ['p_ws', 'p_title']]];
function oddsOf(r) { const k = K(), o = {}; ODDS.forEach(x => { const v = k.val(r || {}, x[2]); if (k.isNum(v)) o[x[0]] = v; }); return o; }
function teamsOf(d) {
  if (!d || d.ok === false) return null;
  if (d.teams && typeof d.teams === 'object') return d;
  if (d.catalogue && d.catalogue.teams) return Object.assign({}, d, d.catalogue);
  return null;
}

// ── catalogue ──────────────────────────────────────────────────────────────

const ST = { extra: [], league: '', sort: null };

function renderTeams(el, params, state) {
  const k = K();
  const L = k.L(params, state);
  el.innerHTML = QK.sectionHead({ kicker: 'Teams · ' + k.LN(L), title: 'Every club', sub: 'Records, our ratings and chances, and each club’s percentile on the team metrics; add any metric as a column.' }) +
    QK.note('A <b>team rating of +1.0</b> means the club scores about one run a game more than it allows against an average opponent: over a season that is roughly 16 extra wins.') +
    '<div class="card"><div class="card-header">' + k.LN(L) + ' teams <span class="card-sub" id="tm-sub">Loading…</span></div>' +
    '<div class="lab-controls gq-controls"><label>League<select id="tm-lg"><option value="">Both leagues</option></select></label><label>Add a metric<select id="tm-extra"><option value="">—</option></select></label><label>&nbsp;<button type="button" class="gq-btn" id="tm-clear">Clear added</button></label></div>' +
    '<div id="tm-chips" class="gq-chips"></div><div id="tm-table">' + k.muted('Loading…') + '</div><div class="pg-note gq-note" id="tm-note"></div></div>' +
    '<div class="card"><div class="card-header">Run prevention against run scoring <span class="card-sub">Our team ratings in runs per game against an average team: offence from batting and baserunning runs, prevention from pitching (expected runs from xwOBA+ against) plus fielding and framing. Marker size is our postseason chance.</span></div><div id="tm-chart" style="height:440px"></div></div>';
  return k.ready().then(() => {
    const S = k.S(params, state);
    return Promise.all([k.loadY(L, S, 'teams.json'), k.loadY(L, S, 'season.json')]).then(res => ({ S: S, res: res }));
  }).then(o => {
    if (!k.alive(el)) return;
    const S = o.S, cat = teamsOf(o.res[0]), rows = seasonRows(o.res[1]);
    const $ = id => document.getElementById(id);
    if (!cat && !Object.keys(rows).length) { $('tm-table').innerHTML = k.notBuilt('The ' + k.LN(L) + ' ' + S + ' team catalogue', o.res[0]); $('tm-sub').textContent = ''; return; }
    const T = (cat && cat.teams) || {};
    Object.keys(T).forEach(t => k.learnTeam(t, T[t]));
    /* the catalogue labels its simulation columns "Postseason odds" / "World Series odds" (teams.py): our chance */
    const metrics = ((cat && cat.metrics) || []).map(m => (m && /\bodds\b/i.test(m.label || '') ? Object.assign({}, m, { label: m.label.replace(/\bodds\b/gi, 'chance') }) : m)), meta = k.metaOf(metrics);
    const ids = Array.from(new Set(Object.keys(T).concat(Object.keys(rows))));
    const lgs = Array.from(new Set(ids.map(t => k.team(t).league || (rows[t] || {}).league).filter(Boolean))).sort();
    $('tm-lg').innerHTML = '<option value="">' + (lgs.length > 1 ? 'Both leagues' : 'All teams') + '</option>' + lgs.map(x => '<option value="' + k.esc(x) + '"' + (x === ST.league ? ' selected' : '') + '>' + k.esc(x) + '</option>').join('');
    $('tm-extra').innerHTML = '<option value="">—</option>' + k.groups(metrics).map(g => '<optgroup label="' + k.esc(g.name) + '">' + g.items.map(m => '<option value="' + k.esc(m.key) + '">' + k.esc(m.label) + '</option>').join('') + '</optgroup>').join('');
    const heads = k.headline(metrics, TPREFS, 5);
    const draw = () => {
      const extras = ST.extra.map(x => meta[x]).filter(Boolean);
      const cols = heads.concat(extras.filter(m => heads.indexOf(m) < 0));
      const list = ids.filter(t => !ST.league || (k.team(t).league || (rows[t] || {}).league) === ST.league);
      const wl = t => { const r = rows[t] || {}, v = (T[t] || {}).values || {}; return { w: k.val(r, ['w', 'wins']) !== null ? k.val(r, ['w', 'wins']) : v.w, l: k.val(r, ['l', 'losses']) !== null ? k.val(r, ['l', 'losses']) : v.l }; };
      list.sort((a, b) => { const x = wl(a), y = wl(b); return ((y.w || 0) - (y.l || 0)) - ((x.w || 0) - (x.l || 0)); });
      const tbl = list.map((t, i) => {
        const r = rows[t] || {}, tv = T[t] || {}, v = tv.values || {}, pc = tv.pct || {}, od = oddsOf(Object.assign({}, v, r)), x = wl(t);
        const rd = [r.rd, r.run_diff, v.run_diff, k.isNum(r.rs) && k.isNum(r.ra) ? r.rs - r.ra : null].find(k.isNum);
        const xw = [r.exp_w, r.xw, r.pythag_w].find(k.isNum), xl = [r.exp_l, r.xl].find(k.isNum) !== undefined ? [r.exp_l, r.xl].find(k.isNum) : (k.isNum(xw) && k.isNum(x.w) ? x.w + x.l - xw : null);
        return { _href: k.teamHref(L, t, S), cells: [
          { v: i + 1, cls: 'pos-cell' }, { v: k.teamName(t), html: k.teamChip(L, t, S) + ' <a href="' + k.teamHref(L, t, S) + '">' + k.esc(k.teamName(t)) + '</a>' },
          { v: k.isNum(x.w) && k.isNum(x.l) ? x.w - x.l : null, html: k.isNum(x.w) ? x.w + '–' + x.l : '—', align: 'right' },
          { v: rd, html: k.isNum(rd) ? k.signed(rd, 0) : '—', align: 'right' },
          { v: xw, html: k.isNum(xw) && k.isNum(xl) ? k.num(xw, 0) + '–' + k.num(xl, 0) : '—', align: 'right', title: 'Expected record from our ratings (or Pythagorean)' },
          { v: od.p_playoffs, html: k.isNum(od.p_playoffs) ? k.pct(od.p_playoffs, 1) : '—', align: 'right' },
          { v: od.p_ws, html: k.isNum(od.p_ws) ? k.pct(od.p_ws, 1) : '—', align: 'right' }
        ].concat(cols.map(m => ({ v: k.isNum(v[m.key]) ? (m.lower ? -v[m.key] : v[m.key]) : -1e9, html: '<span class="gq-val">' + k.fmt(m, v[m.key]) + '</span> ' + k.pill(pc[m.key]), align: 'right' }))) };
      });
      $('tm-table').innerHTML = k.table([{ label: '#', sortable: false }, { label: 'Team' }, { label: 'W–L', align: 'right' }, { label: 'Run diff', align: 'right' }, { label: 'Expected', align: 'right' }, { label: 'Playoffs', align: 'right' }, { label: 'Title', align: 'right' }]
        .concat(cols.map(m => ({ label: k.shortLabel(m.label) + (m.lower ? ' ↓' : ''), align: 'right', title: m.desc || m.label }))), tbl, { compact: true, sticky: true });
      k.sortable($('tm-table'));
      $('tm-chips').innerHTML = extras.length ? 'Added: ' + extras.map(m => '<button type="button" class="gq-chip" data-rm="' + k.esc(m.key) + '">' + k.esc(m.label) + ' ×</button>').join(' ') : '';
      $('tm-sub').textContent = list.length + ' teams, ' + S + ' · sorted by record; click a header to sort';
      chart(L, S, list, T, rows);
    };
    $('tm-lg').onchange = e => { ST.league = e.target.value; draw(); };
    $('tm-extra').onchange = e => { const x = e.target.value; if (x && ST.extra.indexOf(x) < 0) ST.extra.push(x); e.target.value = ''; draw(); };
    $('tm-clear').onclick = () => { ST.extra = []; draw(); };
    $('tm-chips').onclick = ev => { const b = ev.target.closest('[data-rm]'); if (b) { ST.extra = ST.extra.filter(x => x !== b.dataset.rm); draw(); } };
    draw();
    $('tm-note').innerHTML = 'Pills are percentiles among the ' + ids.length + ' teams (100 = best). Our playoff and title chances come from the season simulation; expected records from our team ratings. The team catalogue has ' + metrics.length + ' metrics; every one is on each team page and in <a href="#/compare">compare</a>.';
  });
}

function chart(L, S, list, T, rows) {
  const k = K();
  const pts = list.map(t => {
    const r = rows[t] || {}, v = (T[t] || {}).values || {};
    const off = [r.off, v.off_rpg].find(k.isNum);
    const dfn = [r.def, v.def_rpg].find(k.isNum), pit = [r.pit, v.pit_rpg].find(k.isNum);
    const def = k.isNum(dfn) || k.isNum(pit) ? (dfn || 0) + (pit || 0) : null;
    return { t: t, x: off, y: def, p: oddsOf(Object.assign({}, v, r)).p_playoffs };
  }).filter(p => k.isNum(p.x) && k.isNum(p.y));
  const node = document.getElementById('tm-chart');
  if (!node) return;
  if (pts.length < 3) { node.innerHTML = k.muted('Team ratings are not available yet.'); node.style.height = 'auto'; return; }
  // Run prevention: higher is better if it is runs saved; if it is runs allowed per game, flip the axis.
  const allowed = pts.every(p => p.y > 2);
  k.plot(node, [{ type: 'scatter', mode: 'markers+text', x: pts.map(p => p.x), y: pts.map(p => p.y), text: pts.map(p => k.teamAbbr(p.t)), textposition: 'top center', textfont: { size: 10, color: k.C.text2 },
    customdata: pts.map(p => p.t), hovertemplate: '%{text}: offence %{x:.2f}, prevention %{y:.2f}<extra></extra>',
    marker: { size: pts.map(p => 8 + (k.isNum(p.p) ? 22 * p.p : 4)), color: pts.map(p => k.teamColour(p.t)), line: { color: '#0d1117', width: 1 } } }],
  k.layout({ margin: { l: 56, r: 12, t: 10, b: 46 }, xaxis: { title: 'Offence: batting + baserunning (runs per game v average)' }, yaxis: { title: allowed ? 'Runs allowed per game (better is up)' : 'Run prevention: pitching + fielding (runs/game v avg)', autorange: allowed ? 'reversed' : true },
    shapes: [{ type: 'line', x0: 0, x1: 0, yref: 'paper', y0: 0, y1: 1, line: { color: '#3d444d', dash: 'dot' } }, { type: 'line', y0: 0, y1: 0, xref: 'paper', x0: 0, x1: 1, line: { color: '#3d444d', dash: 'dot' } }] }));
  if (node.on) node.on('plotly_click', ev => { const t = ev.points && ev.points[0] && ev.points[0].customdata; if (t) location.hash = k.teamHref(L, t, S); });
}

// ── team page ──────────────────────────────────────────────────────────────

function renderTeam(el, params, state) {
  const k = K();
  const U = BP.ui;
  const L = k.L(params, state);
  const tid = String(params.id || (params.rest || [])[0] || '');
  el.innerHTML = QK.skeleton('card', 2);
  return k.ready().then(() => {
    const S = k.S(params, state);
    /* first load: teams.json, season.json and parks.json; the 11 MB player catalogues load only for the detailed lineup and
       rotation (button), the schedule is not needed (the team log carries our pre-game chance). */
    return Promise.all([k.loadY(L, S, 'teams.json'), k.loadY(L, S, 'season.json'), k.loadY(L, S, 'parks.json'), k.loadNames(), U.gloss()])
      .then(res => ({ S: S, res: res }));
  }).then(o => {
    if (!k.alive(el)) return;
    const S = o.S, res = o.res, gl = res[4];
    const cat = teamsOf(res[0]), rows = seasonRows(res[1]);
    const T = (cat && cat.teams) || {};
    Object.keys(T).forEach(t => k.learnTeam(t, T[t]));
    const tm = T[tid] || null, r = rows[tid] || {};
    if (!tm && !rows[tid]) { el.innerHTML = k.card('Team', '', k.notBuilt('The page for ' + k.teamName(tid), res[0]) + '<div class="pg-note gq-note"><a href="' + k.href(L, 'teams', S) + '">All teams →</a></div>'); return; }
    if (BP.setRecords) BP.setRecords(U.records(res[1] || {}));
    const t = tm || {}, v = t.values || {}, pc = t.pct || {}, meta = k.metaOf((cat || {}).metrics);
    const od = oddsOf(Object.assign({}, v, t.odds || {}, r));
    const w = [r.w, v.w].find(k.isNum), l = [r.l, v.l].find(k.isNum);
    const rd = [r.rd, v.rd].find(k.isNum);
    const info = k.team(tid);
    const vid = t.park || info.venue;
    const xw = [r.exp_w, v.exp_w].find(k.isNum), xl = k.isNum(xw) && k.isNum(w) ? w + l - xw : null, pw = [r.pythag_w, v.pythag_w].find(k.isNum);
    const rt = { off: [r.off, v.off_rpg].find(k.isNum), def: [r.def, v.def_rpg].find(k.isNum), pit: [r.pit, v.pit_rpg].find(k.isNum), tot: [r.rating, v.rating].find(k.isNum) };
    document.title = k.teamName(tid) + ' · ' + BP.SITE;
    const hero = QK.playerHeader({ name: k.teamName(tid), split: false, pos: [info.league, info.division].filter(Boolean).join(' · '), kicker: k.LN(L) + ' ' + S + (k.isNum(r.div_rank) ? ' · ' + k.ordinal(r.div_rank) + ' in the division' : ''),
      team: { name: k.teamAbbr(tid), abbr: k.teamAbbr(tid), colour: (BP.teamInfo(tid) || {}).colour },
      meta: [vid ? ['Home park', k.parkName(vid)] : null, k.isNum(pw) ? ['Pythagorean', k.num(pw, 0) + ' wins'] : null],
      stats: [{ label: 'Record', value: k.isNum(w) ? w + '-' + l : '—' }, { label: 'Run diff', value: k.isNum(rd) ? k.signed(rd, 0) : '—' }, { label: 'Rating', value: k.isNum(rt.tot) ? k.signed(rt.tot, 2) : '—' }] });
    const tiles = [];
    if (k.isNum(od.p_ws)) tiles.push({ label: 'World Series chance', value: k.pct(od.p_ws, 1), signal: true, sub: k.isNum(od.p_pennant) ? 'pennant ' + k.pct(od.p_pennant, 1) : 'season simulation', tip: 'Our chance from simulating the rest of the season and the bracket' });
    if (k.isNum(od.p_playoffs)) tiles.push({ label: 'Postseason chance', value: k.pct(od.p_playoffs, 1), signal: !k.isNum(od.p_ws), sub: k.isNum(od.p_division) ? 'division ' + k.pct(od.p_division, 1) : (r.clinched ? 'clinched' : '') });
    tiles.push({ label: 'Team rating', value: k.isNum(rt.tot) ? k.signed(rt.tot, 2) : '—', pctl: pc.rating, sub: 'offence ' + k.signed(rt.off, 2) + ' · pitching ' + k.signed(rt.pit, 2) + ' · fielding ' + k.signed(rt.def, 2), tip: 'Runs a game better than an average club' });
    tiles.push({ label: 'Expected record', value: k.isNum(xw) ? k.num(xw, 0) + '-' + k.num(xl, 0) : '—', sub: 'from our ratings' });
    if (k.isNum(v.war)) tiles.push({ label: 'Roster WAR', value: k.signed(v.war, 1), pctl: pc.war, sub: 'Bullpen WAR, hitters and pitchers' });
    const stages = [['p_playoffs', 'Postseason'], ['p_division', 'Win the division'], ['p_bye', 'A first-round bye'], ['p_pennant', 'Win the pennant'], ['p_ws', 'Win the World Series']].filter(x => k.isNum(od[x[0]]));
    const tGroups = U.pctGroups({ values: v, pct_role: pc, n: { g: v.g } }, 'team', 'TEAM', gl, 'head');
    const links = '<a class="qk-btn" href="' + k.compareHref('t' + tid, '') + '?view=classic">Compare</a>' + (vid ? '<a class="qk-btn" href="' + k.parkHref(vid) + '">' + k.esc(k.parkName(vid)) + '</a>' : '') + '<a class="qk-btn" href="' + k.href(L, 'teams', S) + '">All teams</a>';
    let h = '<div class="qk-kicker" style="margin-bottom:10px"><a href="' + k.href(L, 'teams', S) + '">← Teams</a></div>' + hero + '<div class="bp-flexrow" style="justify-content:flex-end">' + links + '</div>' +
      '<div class="bp-kpis" style="margin-top:var(--sp-5)">' + QK.stats(tiles) + '</div>';
    h += '<div class="qk-grid"><div class="qk-span-5"><div class="bp-stack">' +
      (stages.length ? U.card2('Season simulation', 'Our chance of reaching each stage' + (k.isNum(r.magic) ? ' · magic number ' + k.esc(r.magic) : ''), QK.chances(stages.map(x => ({ label: x[1], p: od[x[0]], color: (BP.teamInfo(tid) || {}).colour })), { sort: false, max: 1, key: false })) : '') +
      QK.pctCard({ title: 'Team profile', peer: 'MLB clubs', sample: k.isNum(v.g) ? v.g + ' games' : '', groups: tGroups, foot: '<span>Percentiles among the ' + Object.keys(T).length + ' clubs; 100 = best</span><a href="' + k.compareHref('t' + tid, '') + '?view=classic">Every metric →</a>' }) +
      '</div></div><div class="qk-span-7">' + U.card2('Roster value', 'Bullpen WAR this season for everyone who played for the club (latest team), with the 40-man roster and injured list where recorded', '' + BP.ui.chart('tm-war', 330, 'Roster WAR') + '<div id="tm-roster" style="margin-top:12px"></div>') + '</div></div>';
    h += '<div id="tm-mv"></div><div id="tm-value"></div>';
    h += '<div id="tm-moves"></div>';
    h += '<div class="qk-grid" style="margin-top:var(--sp-4)"><div class="qk-span-6">' + U.card2('Regular lineup', 'The nine with the most plate appearances, by xwOBA+ (our expected wOBA); our game forecast uses the posted lineup', '<div id="tm-lineup"></div>') + '</div>' +
      '<div class="qk-span-6">' + U.card2('Rotation', 'Starters by innings, with runs allowed per nine and Stuff+', '<div id="tm-rot"></div>') + '</div></div>' +
      '<p class="bp-note"><button type="button" class="qk-btn" id="tm-more">Load splits and pitch-model columns</button> Platoon splits, projections and Pitching+ come from the season catalogues (about 11 MB).</p>';
    h += '<div class="grid-2"><div class="card"><div class="card-header">Bullpen <span class="card-sub">Relievers by appearances, with their leverage (gmLI) and quality. On game day our forecast makes a reliever unavailable after 30+ pitches the day before or pitching on both of the last two days, and half-available after pitching yesterday; the game centre shows that day\'s availability.</span></div><div id="tm-pen"></div></div>' +
      '<div class="card"><div class="card-header">Defence <span class="card-sub">Our fielding runs and outs above expected beside Savant\'s OAA, and framing.</span></div><div id="tm-def"></div></div></div>';
    h += '<div class="card"><div class="card-header">Home park <span class="card-sub">Our park factors (100 = neutral) by batter hand and batted-ball type.</span></div><div id="tm-park"></div></div>';
    h += U.card2('Schedule and results', 'Every game with our pre-game win chance; the line is wins minus the wins we expected', U.chart('tm-logc', 260, 'Wins minus expected wins') + '<div id="tm-log"></div>');
    el.innerHTML = h;
    roster(L, S, t, tid, meta);
    lineupLite(L, S, t);
    bullpen(L, S, t, tid, null);
    defence(t, meta);
    park(res[2], vid);
    logTable(L, S, t, tid);
    const more = document.getElementById('tm-more');
    const rr = rosterRows(t);
    if (more && rr.some(x => k.isNum(x.woba_vl)) && rr.some(x => k.isNum(x.pitching_plus))) more.parentNode.style.display = 'none';
    if (more) more.onclick = () => {
      more.disabled = true; more.textContent = 'Loading…';
      Promise.all([k.loadY(L, S, 'hitters.json'), k.loadY(L, S, 'pitchers.json')]).then(cs => {
        if (!k.alive(el)) return;
        const hcat = k.catOf(cs[0], 'hitters'), pcat = k.catOf(cs[1], 'pitchers');
        [hcat, pcat].forEach(cc => { if (cc) k.learnCat(cc); });
        lineup(L, S, t, tid, hcat);
        rotation(L, S, t, tid, pcat);
        if (!(t.bullpen || t.pen)) bullpen(L, S, t, tid, pcat);
        more.parentNode.style.display = 'none';
      });
    };
    if (typeof BP.valueTeam === 'function') BP.valueTeam(document.getElementById('tm-value'), L, S, tid);   // value.js: strengths and needs
    if (typeof BP.movesTeam === 'function') BP.movesTeam(document.getElementById('tm-moves'), L, S, tid);   // moves.js: trades and moves
    if (BP.moves) BP.moves.teamCards(document.getElementById('tm-mv'), tid, L, S);   // bp-moves.js: outlook and targets
    if (typeof BP.setMeta === 'function') { try { BP.setMeta(k.esc(k.teamName(tid))); } catch (e) { /* optional */ } }
  });
}
/* Lineup and rotation from the team's roster rows (teams.json): no catalogue needed. */
function lineupLite(L, S, t) {
  const k = K();
  const rows = rosterRows(t);
  const hit = rows.filter(r => r.kind === 'hitter' && k.isNum(r.pa)).sort((a, b) => b.pa - a.pa).slice(0, 9).sort((a, b) => (b.xwoba_plus || 0) - (a.xwoba_plus || 0));
  const pit = rows.filter(r => r.kind === 'pitcher' && String(r.pos).toUpperCase() === 'SP' && k.isNum(r.ip)).sort((a, b) => b.ip - a.ip).slice(0, 6);
  const lu = document.getElementById('tm-lineup'), ro = document.getElementById('tm-rot');
  const has = (list, f) => list.some(x => k.isNum(x[f]));
  if (lu) QK.leaderboard(lu, { dense: true, rank: true, columns: [
    { key: 'name', label: 'Hitter', type: 'entity', sub: 'pos', href: x => k.hitterHref(L, x.pid, S) },
    { key: 'pa', label: 'PA', num: true }, { key: 'woba', label: 'wOBA', num: true, fmt: x => k.rate3(x) }, { key: 'xwoba_plus', label: 'xwOBA+', num: true, fmt: x => k.rate3(x) }]
    .concat(has(hit, 'woba_vl') ? [{ key: 'woba_vl', label: 'v LHP', num: true, fmt: x => k.rate3(x), tip: 'wOBA against left-handed pitching this season' }, { key: 'woba_vr', label: 'v RHP', num: true, fmt: x => k.rate3(x) }] : [])
    .concat(has(hit, 'proj_woba') ? [{ key: 'proj_woba', label: 'Proj. wOBA', num: true, fmt: x => k.rate3(x), tip: 'Next-season projection' }] : [])
    .concat([{ key: 'war', label: 'WAR', type: 'bar', fmt: x => (k.isNum(x) ? k.signed(x, 1) : '—') }]), rows: hit.map(x => Object.assign({ name: x.name || k.name(x.pid) }, x)), sort: { key: 'xwoba_plus', dir: 'desc' } });
  if (lu && !hit.length) lu.innerHTML = QK.empty('No lineup yet');
  if (ro) QK.leaderboard(ro, { dense: true, columns: [
    { key: 'name', label: 'Starter', type: 'entity', href: x => k.pitcherHref(L, x.pid, S) },
    { key: 'ip', label: 'IP', num: true, fmt: x => k.num(x, 1) }].concat(has(pit, 'gs') ? [{ key: 'gs', label: 'GS', num: true }] : [])
    .concat([{ key: 'ra9', label: 'RA9', num: true, fmt: x => k.num(x, 2) }]).concat(has(pit, 'xra9') ? [{ key: 'xra9', label: 'xRA9', num: true, fmt: x => k.num(x, 2), tip: 'Expected runs per nine from xwOBA+ against' }] : [])
    .concat([{ key: 'stuff_plus', label: 'Stuff+', num: true, fmt: x => k.fmtV(x, 'plus') }]).concat(has(pit, 'pitching_plus') ? [{ key: 'pitching_plus', label: 'Pitching+', num: true, fmt: x => k.fmtV(x, 'plus') }] : [])
    .concat(has(pit, 'p_start') ? [{ key: 'p_start', label: 'Pitches/start', num: true, fmt: x => k.num(x, 0) }] : [])
    .concat([{ key: 'war', label: 'WAR', type: 'bar', fmt: x => (k.isNum(x) ? k.signed(x, 1) : '—') }]), rows: pit.map(x => Object.assign({ name: x.name || k.name(x.pid) }, x)), sort: { key: 'ip', dir: 'desc' } });
  if (ro && !pit.length) ro.innerHTML = QK.empty('No starters yet');
}

function rosterRows(t) {
  const k = K();
  const raw = t.roster || [];
  return (Array.isArray(raw) ? raw : Object.keys(raw).map(p => Object.assign({ pid: p }, raw[p]))).map(r => (Array.isArray(r) ? { pid: String(r[0]), pos: r[1], war: r[2], proj: r[3] } : Object.assign({}, r, { pid: String(r.pid || r.id) })))
    .filter(r => r.pid);
}
function roster(L, S, t, tid, meta) {
  const k = K();
  const rows = rosterRows(t);
  const host = document.getElementById('tm-roster');
  if (!rows.length) { host.innerHTML = QK.empty('No roster yet', 'The roster is not available yet.'); document.getElementById('tm-war').style.display = 'none'; return; }
  rows.forEach(r => { if (r.name) k.learn(r.pid, { name: r.name, pos: r.pos }); });
  const war = r => k.val(r, ['war']);
  const role = r => (r.kind === 'pitcher' ? 'pitcher' : r.kind === 'hitter' ? 'hitter' : null);
  const stat = r => (r.kind === 'pitcher' ? (k.isNum(r.ra9) ? k.num(r.ra9, 2) + ' RA9' : '') + (k.isNum(r.stuff_plus) ? ' · Stuff+ ' + Math.round(r.stuff_plus) : '')
    : r.kind === 'hitter' ? (k.isNum(r.woba) ? k.rate3(r.woba) + ' wOBA' : '') + (k.isNum(r.xwoba_plus) ? ' · ' + k.rate3(r.xwoba_plus) + ' xwOBA+' : '') : '');
  const inj = r => (Array.isArray(r.injured) && r.injured.length ? r.injured.filter(Boolean).join(': ') : (typeof r.injured === 'string' ? r.injured : ''));
  rows.sort((a, b) => (war(b) === null ? -99 : war(b)) - (war(a) === null ? -99 : war(a)));
  const drawRoster = mv => QK.leaderboard(host.querySelector('.bp-roster-t') || host, { dense: true, maxHeight: 420, sort: mv ? { key: 'p_move', dir: 'desc' } : null, columns: [
    { key: 'name', label: 'Player', type: 'entity', sub: 'pos', href: r => (role(r) ? (role(r) === 'pitcher' ? k.pitcherHref(L, r.pid, S) : k.hitterHref(L, r.pid, S)) : null) },
    { key: 'pa_ip', label: 'PA / IP', num: true, fmt: (x, r) => (k.isNum(r.pa) ? k.int(r.pa) : k.isNum(r.ip) ? k.num(r.ip, 1) : '—') },
    { key: 'war', label: 'WAR', type: 'bar', fmt: x => (k.isNum(x) ? k.signed(x, 1) : '—') },
    { key: 'line', label: 'Line', sort: false, fmt: (x, r) => '<span class="qk-muted">' + stat(r) + '</span>' },
    { key: 'status', label: 'Status', fmt: (x, r) => (inj(r) ? QK.tag(inj(r)) : (r.kind === '40man' ? '<span class="qk-muted">40-man</span>' : '')) }].concat(mv ? [mv.col] : []),
    rows: rows.map(r => Object.assign({ name: r.name || k.name(r.pid), pa_ip: k.isNum(r.pa) ? r.pa : r.ip, status: inj(r) }, r, mv ? { _mv: mv.rowOf(r.pid), p_move: mv.pOf(r.pid) } : {})) });
  host.innerHTML = '<div class="bp-roster-l"></div><div class="bp-roster-t"></div>';
  drawRoster(null);
  /* who moves next (bp-moves.js): the roster gets a "Chance of moving" column once mlb/movement.json is in */
  if (L === 'mlb' && Number(S) === BP.currentSeason('mlb') && BP.moves) BP.moves.load().then(m => {
    if (!m || !host.isConnected) return;
    const mv = BP.moves.rosterColumn(m);
    if (!mv) return;
    host.querySelector('.bp-roster-l').innerHTML = mv.legend;
    drawRoster(mv);
  });
  const top = rows.filter(r => k.isNum(war(r))).slice(0, 12);
  if (top.length) QKC.bar('#tm-war', { cats: top.map(r => k.surname(r.name || k.name(r.pid))), series: [{ name: 'Bullpen WAR', data: top.map(war) }], horizontal: true, labels: true, fmt: x => k.signed(x, 1),
    colors: top.map(r => (r.kind === 'pitcher' ? QK.cssVar('--c-3') : (BP.teamInfo(tid) || {}).colour)), hrefs: top.map(r => (role(r) === 'pitcher' ? k.pitcherHref(L, r.pid, S) : k.hitterHref(L, r.pid, S))), labelWidth: 110,
    valName: 'Bullpen WAR this season', catName: 'Player', legendItems: [{ name: 'Hitters', color: (BP.teamInfo(tid) || {}).colour || QK.cssVar('--c-1') }, { name: 'Pitchers', color: QK.cssVar('--c-3') }], label: 'Roster WAR' });
  else document.getElementById('tm-war').style.display = 'none';
}

function listOf(x) { return Array.isArray(x) ? x : (x && typeof x === 'object' ? Object.keys(x).map(p => Object.assign({ pid: p }, x[p])) : []); }
/* The regulars from the hitter catalogue (the team's top nine by plate appearances), ordered by projected wOBA. */
function lineup(L, S, t, tid, hcat) {
  const k = K(), host = document.getElementById('tm-lineup');
  const given = listOf(t.lineup || (t.projections || {}).lineup);
  let rows = given.map(r => Object.assign({}, r, { pid: String(r.pid || r.id) }));
  if (!rows.length && hcat) {
    rows = Object.keys(hcat.players).filter(pid => String(hcat.players[pid].team) === String(tid)).map(pid => Object.assign({ pid: pid }, hcat.players[pid]))
      .sort((a, b) => (b.pa || 0) - (a.pa || 0)).slice(0, 9);
    rows.sort((a, b) => (((b.values || {}).proj_woba) || ((b.values || {}).woba) || 0) - (((a.values || {}).proj_woba) || ((a.values || {}).woba) || 0));
  }
  if (!rows.length) { host.innerHTML = k.muted('No lineup yet.'); return; }
  const vv = (r, key) => (r.values || r)[key];
  host.innerHTML = k.table([{ label: '#', sortable: false }, { label: 'Hitter' }, { label: 'Pos' }, { label: 'PA', align: 'right' }, { label: 'Proj. wOBA', align: 'right', title: 'Next-season projection' }, { label: 'v LHP', align: 'right', title: 'wOBA against left-handed pitching this season' }, { label: 'v RHP', align: 'right' }, { label: 'WAR', align: 'right' }],
    rows.map((r, i) => [{ v: i + 1, html: String(i + 1) }, { v: r.name || k.name(r.pid), html: k.playerLink(L, r.pid, r.name, S, 'hitter') }, { v: r.pos || '', html: k.esc(r.pos || '—') }, { v: r.pa, html: k.int(r.pa) },
      { v: vv(r, 'proj_woba'), html: k.rate3(vv(r, 'proj_woba')) }, { v: vv(r, 'woba_vl'), html: k.rate3(vv(r, 'woba_vl')) }, { v: vv(r, 'woba_vr'), html: k.rate3(vv(r, 'woba_vr')) },
      { v: vv(r, 'war'), html: k.isNum(vv(r, 'war')) ? k.signed(vv(r, 'war'), 1) : '—' }]), { compact: true });
}

function rotation(L, S, t, tid, pcat) {
  const k = K(), host = document.getElementById('tm-rot');
  let rows = listOf(t.rotation).map(r => Object.assign({}, r, { pid: String(r.pid || r.id) }));
  if (!rows.length && pcat) rows = Object.keys(pcat.players).filter(pid => String(pcat.players[pid].team) === String(tid) && ((pcat.players[pid].values || {}).gs || 0) > 0)
    .map(pid => Object.assign({ pid: pid }, pcat.players[pid])).sort((a, b) => ((b.values || {}).gs || 0) - ((a.values || {}).gs || 0)).slice(0, 7);
  if (!rows.length) { host.innerHTML = k.muted('No starters yet.'); return; }
  const vv = (r, key) => (r.values || r)[key];
  host.innerHTML = k.table([{ label: 'Starter' }, { label: 'GS', align: 'right' }, { label: 'IP', align: 'right' }, { label: 'RA9', align: 'right' }, { label: 'xRA9', align: 'right', title: 'Expected runs per nine from xwOBA+ against' }, { label: 'Pitching+', align: 'right' }, { label: 'Pitches/start', align: 'right' }, { label: 'WAR', align: 'right' }],
    rows.map(r => [{ v: r.name || k.name(r.pid), html: k.playerLink(L, r.pid, r.name, S, 'pitcher') + ((k.NAMES[r.pid] || {}).throws ? ' <span class="muted-inline">' + k.esc(k.NAMES[r.pid].throws) + 'HP</span>' : '') },
      { v: vv(r, 'gs'), html: k.int(vv(r, 'gs')) }, { v: vv(r, 'ip'), html: k.num(vv(r, 'ip'), 1) }, { v: vv(r, 'ra9'), html: k.num(vv(r, 'ra9'), 2) }, { v: vv(r, 'xra9'), html: k.num(vv(r, 'xra9'), 2) },
      { v: vv(r, 'pitching_plus'), html: k.fmtV(vv(r, 'pitching_plus'), 'plus') }, { v: vv(r, 'p_start'), html: k.num(vv(r, 'p_start'), 0) }, { v: vv(r, 'war'), html: k.isNum(vv(r, 'war')) ? k.signed(vv(r, 'war'), 1) : '—' }]), { compact: true });
  k.sortable(host);
}

function bullpen(L, S, t, tid, pcat) {
  const k = K(), host = document.getElementById('tm-pen');
  let rows = listOf(t.bullpen || t.pen).map(r => Object.assign({}, r, { pid: String(r.pid || r.id) }));
  const given = rows.length > 0;
  if (!rows.length && pcat) rows = Object.keys(pcat.players).filter(pid => String(pcat.players[pid].team) === String(tid) && k.roleOf(pcat.players[pid]) === 'RP')
    .map(pid => Object.assign({ pid: pid }, pcat.players[pid])).sort((a, b) => ((b.values || {}).g || 0) - ((a.values || {}).g || 0)).slice(0, 12);
  if (!rows.length) { host.innerHTML = k.muted('No relievers yet.'); return; }
  const vv = (r, key) => (r.values || r)[key];
  if (given) {
    host.innerHTML = k.table([{ label: 'Reliever' }, { label: 'Available', align: 'right' }, { label: 'Pitches, last 3 days', align: 'right' }, { label: 'Rest', align: 'right' }],
      rows.map(r => { const a = [r.available, r.avail, r.availability].find(x => x !== undefined && x !== null); return [{ v: k.name(r.pid), html: k.playerLink(L, r.pid, r.name, S, 'pitcher') }, { v: a, html: k.isNum(a) ? k.pct(a, 0) : k.esc(a === true ? 'yes' : a === false ? 'no' : '—') }, { v: r.pitches_3d, html: k.int(r.pitches_3d) }, { v: r.rest, html: k.isNum(r.rest) ? r.rest + ' d' : '—' }]; }), { compact: true });
    return;
  }
  host.innerHTML = k.table([{ label: 'Reliever' }, { label: 'G', align: 'right' }, { label: 'IP', align: 'right' }, { label: 'gmLI', align: 'right', title: 'Mean leverage on entering (1 = average)' }, { label: 'RA9', align: 'right' }, { label: 'K−BB%', align: 'right' }, { label: 'Pitching+', align: 'right' }, { label: 'WAR', align: 'right' }],
    rows.map(r => [{ v: r.name || k.name(r.pid), html: k.playerLink(L, r.pid, r.name, S, 'pitcher') }, { v: vv(r, 'g'), html: k.int(vv(r, 'g')) }, { v: vv(r, 'ip'), html: k.num(vv(r, 'ip'), 1) },
      { v: vv(r, 'gmli'), html: k.num(vv(r, 'gmli'), 2) }, { v: vv(r, 'ra9'), html: k.num(vv(r, 'ra9'), 2) }, { v: vv(r, 'k_bb_pct'), html: k.fmtV(vv(r, 'k_bb_pct'), 'pct') },
      { v: vv(r, 'pitching_plus'), html: k.fmtV(vv(r, 'pitching_plus'), 'plus') }, { v: vv(r, 'war'), html: k.isNum(vv(r, 'war')) ? k.signed(vv(r, 'war'), 1) : '—' }]), { compact: true });
  k.sortable(host);
}

function defence(t, meta) {
  const k = K(), host = document.getElementById('tm-def');
  const v = t.values || {}, pc = t.pct || {};
  const tiles = [];
  [['fielding_runs', 'Fielding runs', 'signed'], ['oaa', 'Outs above expected', 'signed'], ['oaa_savant', 'Savant OAA', 'signed'], ['framing_runs', 'Framing runs', 'signed'], ['def_rpg', 'Defence (runs/game)', 'signed2']].forEach(x => {
    if (k.isNum(v[x[0]])) tiles.push(k.tile(x[1], k.fmtV(v[x[0]], x[2]), k.isNum(pc[x[0]]) ? k.ordinal(pc[x[0]]) + ' percentile' : ''));
  });
  const d = t.defence || t.alignment;
  let extra = '';
  if (d && typeof d === 'object') {
    ['if', 'of'].forEach(side => {
      const a = d[side];
      if (!a || typeof a !== 'object') return;
      const keys = Object.keys(a).filter(x => k.isNum(a[x]));
      const tot = keys.reduce((s0, y) => s0 + a[y], 0) || 1;
      if (keys.length) extra += '<div class="gq-sub-head">' + (side === 'if' ? 'Infield' : 'Outfield') + ' alignment</div><div class="gq-stack">' + keys.map((x, i) => '<span style="width:' + (100 * a[x] / tot).toFixed(1) + '%;background:' + k.PALETTE[i % k.PALETTE.length] + '" title="' + k.esc(k.titleCase(x)) + ' ' + k.pct(a[x] / tot, 1) + '">' + k.esc(k.titleCase(x)) + '</span>').join('') + '</div>';
    });
  }
  host.innerHTML = (tiles.length ? '<div class="kpi-grid gq-tiles gq-tiles-3">' + tiles.join('') + '</div>' : k.muted('Defensive numbers are not available yet.')) + extra +
    (extra ? '' : '<div class="pg-note gq-note">Infield and outfield alignment rates are not in the team payload yet; the catch-probability model reads each ball\'s alignment from Statcast when it values the play.</div>');
}

function park(parks, vid) {
  const k = K(), host = document.getElementById('tm-park');
  const P = parks && parks.ok !== false ? (parks.parks || parks) : {};
  const p = vid ? P[vid] : null;
  if (!p) { host.innerHTML = k.muted('Park factors are not available yet.') + (vid ? '<div class="pg-note gq-note"><a href="' + k.parkHref(vid) + '">' + k.esc(k.parkName(vid)) + ' →</a></div>' : ''); return; }
  const BP_ = BP.gk.parkFactorTable;
  host.innerHTML = '<div class="gq-pad"><a href="' + k.parkHref(vid) + '"><strong>' + k.esc(p.name || k.parkName(vid)) + '</strong></a>' + (p.city ? ' · ' + k.esc(p.city) : '') + '</div>' + (typeof BP_ === 'function' ? BP_(p) : k.muted('Park factors on the park page.'));
}
/* E's log rows [gpk, date, gtype, opp, home (1/0), runs for, runs against, "W"|"L"|status]; the model's pre-game
 * probability and the market's come from schedule.json (GAME_CARD model.p_home / market.p_home). */
function logTable(L, S, t, tid) {
  const k = K();
  const log = (t.log || []).map(r => (Array.isArray(r) ? { gpk: String(r[0]), date: r[1], gtype: r[2], opp: r[3], home: !!r[4], rs: r[5], ra: r[6], res: r[7], p: r[8] } : r));
  const host = document.getElementById('tm-log'), ch = document.getElementById('tm-logc');
  if (!log.length) { host.innerHTML = QK.empty('No games yet', 'The schedule log is not available yet.'); ch.style.display = 'none'; return; }
  const pOf = r => (k.isNum(r.p) ? Number(r.p) : null);
  const res = r => (r.res === 'W' ? 1 : r.res === 'L' ? 0 : null);
  let cw = 0, ce = 0;
  const xs = [], ys = [];
  log.filter(r => r.gtype === 'R' || !r.gtype).forEach(r => { const w = res(r), p = pOf(r); if (w === null || !k.isNum(p)) return; cw += w; ce += p; xs.push(r.date); ys.push(Math.round((cw - ce) * 10) / 10); });
  if (xs.length) QKC.line('#tm-logc', { x: xs, xType: 'time', series: [{ name: 'Wins minus expected', data: ys, color: (BP.teamInfo(tid) || {}).colour, area: true }], yFmt: x => k.signed(x, 0), yName: 'Wins minus our expected wins', xName: 'Date', ref: { y: 0, label: '' }, endLabels: true, label: 'Wins minus expected wins' });
  else ch.style.display = 'none';
  const ll = log.filter(r => res(r) !== null && k.isNum(pOf(r)));
  const lossOf = rs => (rs.length ? -rs.reduce((s0, r) => { const p = Math.min(0.999, Math.max(0.001, pOf(r))); return s0 + (res(r) ? Math.log(p) : Math.log(1 - p)); }, 0) / rs.length : null);
  const GT = { R: '', F: 'WC', D: 'DS', L: 'LCS', W: 'WS', C: 'Champ' };
  host.innerHTML = (ll.length ? '<p class="bp-note">' + ll.length + ' finished games with our forecast: ' + ll.filter(r => res(r)).length + ' wins against ' + k.num(ll.reduce((s0, r) => s0 + pOf(r), 0), 1) + ' expected; log loss ' + k.num(lossOf(ll), 3) + ' (a coin flip scores 0.693). Past games carry the walk-forward backtest forecast.</p>' : '') + '<div id="tm-log-t"></div>';
  QK.table(document.getElementById('tm-log-t'), { dense: true, maxHeight: 420, sort: { key: 'date', dir: 'desc' }, rowHref: r => (r.gpk ? k.href(L, 'game/' + r.gpk, S) : null), columns: [
    { key: 'date', label: 'Date', fmt: x => k.esc(k.short(x)) }, { key: 'oppn', label: 'Opponent', fmt: (x, r) => (r.home ? 'v ' : '@ ') + k.teamChip(L, r.opp, S) },
    { key: 'w', label: 'Result', fmt: (x, r) => (x === null ? '<span class="qk-muted">' + k.esc(r.res || 'scheduled') + '</span>' : '<span class="' + (x ? 'gq-ok' : 'gq-no') + '">' + (x ? 'W' : 'L') + ' ' + r.rs + '–' + r.ra + '</span>') },
    { key: 'p', label: 'Our chance', num: true, fmt: x => (k.isNum(x) ? k.pct(x, 0) : '—'), tip: 'Our pre-game win chance for this club' },
    { key: 'gt', label: '', sort: false, fmt: (x, r) => (GT[r.gtype] ? '<span class="chip">' + GT[r.gtype] + '</span>' : '') }],
    rows: log.filter(r => !(r.gtype && r.gtype !== 'R' && String(r.res || '').toLowerCase() === 'cancelled')).map(r => Object.assign({ oppn: k.teamAbbr(r.opp), w: res(r), gt: r.gtype }, r)) });
}

if (typeof BP.route === 'function') {
  [['teams', renderTeams], ['#/<L>/teams', renderTeams], ['team', renderTeam], ['#/<L>/team/<tid>', renderTeam]].forEach(r => { try { BP.route(r[0], r[1]); } catch (e) { /* bound */ } });
}
})(window.BP || (window.BP = {}));
