/* The Quant Hardwood — players: the catalogue (#/<L>/players) and the player page
 * (#/<L>/player/<pid>).
 *
 * Data: data/<L>/<S>/players.json (catalogue: values, league and position-pool
 * percentiles), data/<L>/players/<pid>.json (career, game log, shots, on/off, lineups,
 * clutch, projection, award odds, similar players), data/<L>/<S>/teams.json (team names
 * on lineups), data/<L>/<S>/awards.json (award odds when the career file has none). */
(function (HW) {
'use strict';

const FX = () => HW.fx;

// Headline metrics: candidates matched against catalogue keys, exact strings first.
const IDX_PREFS = ['hpm', 'hpm_t', /^hpm$/, 'rapm', /^rapm/, 'box_impact', /box/, 'wpa', /^wpa/, 'ts', /^ts/, 'usg', /usg|usage/];
const RADAR_PREFS = ['pts100', 'pts_100', /pts.*100/, 'ts', /^ts/, 'usg', /usg/, 'ast_pct', /ast.*pct|^ast%/, 'trb_pct', /reb.*pct|trb/, 'stl_pct', /stl/, 'blk_pct', /blk/, 'tov_pct', /tov/, 'hpm_o', /hpm.*o/, 'hpm_d', /hpm.*d/, 'pox100', 'pox', /pox|over.*exp/];
const K = {
  hpm: ['hpm', 'hpm_t', /^hpm$/, /^hpm_?tot/], hpm_o: ['hpm_o', 'o_hpm', /^hpm_?o(ff)?$/], hpm_d: ['hpm_d', 'd_hpm', /^hpm_?d(ef)?$/], hpm_se: ['hpm_se', 'se_hpm', /hpm.*se/],
  rapm: ['rapm', 'rapm_t', /^rapm$/], box: ['box_impact', 'bpm', /box/], wpa: ['wpa', /^wpa$/], mpg: ['mpg', 'min_g', /^min.*g$/]
};

// ── catalogue ──────────────────────────────────────────────────────────────

let IDXS = { pool: 'all', q: '', team: '', floor: null, basis: 'league', extra: '' };

function renderPlayers(el, params, state) {
  const fx = FX(), L = fx.L(params, state);
  return fx.ready().then(() => {
    const S = fx.S(params, state, L);
    el.innerHTML = '<div class="card"><div class="card-header">Players ' + fx.esc(fx.seasonLabel(L, S)) + ' <span class="card-sub" id="pl-sub">Loading…</span></div>' +
      '<div class="lab-controls hf-controls">' +
      '<label>Search<input id="pl-q" class="pg-search" type="search" placeholder="player or team…"></label>' +
      '<label>Position pool<select id="pl-pool"><option value="all">All</option><option value="G">Guards</option><option value="F">Forwards</option><option value="C">Centres</option></select></label>' +
      '<label>Team<select id="pl-team"><option value="">All teams</option></select></label>' +
      '<label>Minutes floor <span id="pl-floor-v"></span><input id="pl-floor" type="range" min="0" max="2000" step="25"></label>' +
      '<label>Percentiles' + fx.toggle('pl-basis', [['league', 'League'], ['pool', 'Position pool']], IDXS.basis) + '</label>' +
      '<label>Add a column<select id="pl-extra"><option value="">—</option></select></label>' +
      '</div><div id="pl-table">' + fx.muted('Loading…') + '</div><div class="pg-note" id="pl-note"></div></div>';
    return fx.season(L, S).then(res => {
      if (!fx.alive(el)) return;
      const cat = res[0];
      if (!fx.ok(cat) || !cat.players) { document.getElementById('pl-table').innerHTML = fx.notBuilt('The ' + fx.seasonLabel(L, S) + ' player catalogue', cat); document.getElementById('pl-sub').textContent = ''; return; }
      const P = cat.players, metrics = cat.metrics || [];
      const ids = Object.keys(P);
      const minMax = Math.max.apply(null, ids.map(id => P[id].min || 0).concat([100]));
      const floorEl = document.getElementById('pl-floor');
      floorEl.max = String(Math.ceil(minMax / 25) * 25);
      if (IDXS.floor === null || IDXS.floor > minMax) IDXS.floor = fx.isNum(cat.min_floor) ? Math.min(cat.min_floor, minMax) : 0;
      floorEl.value = IDXS.floor;
      document.getElementById('pl-floor-v').textContent = Math.round(IDXS.floor);
      const teams = Array.from(new Set(ids.map(id => P[id].team).filter(Boolean))).sort((a, b) => fx.teamName(L, a).localeCompare(fx.teamName(L, b)));
      document.getElementById('pl-team').innerHTML = '<option value="">All teams</option>' + teams.map(t => '<option value="' + fx.esc(t) + '"' + (t === IDXS.team ? ' selected' : '') + '>' + fx.esc(fx.teamName(L, t)) + '</option>').join('');
      document.getElementById('pl-pool').value = IDXS.pool;
      document.getElementById('pl-q').value = IDXS.q;
      document.getElementById('pl-extra').innerHTML = '<option value="">—</option>' + fx.groups(metrics).map(g => '<optgroup label="' + fx.esc(g.name) + '">' + g.items.map(m => '<option value="' + fx.esc(m.key) + '"' + (m.key === IDXS.extra ? ' selected' : '') + '>' + fx.esc(m.label) + '</option>').join('') + '</optgroup>').join('');
      const heads = fx.headline(metrics, IDX_PREFS, 6, true);
      const draw = () => drawIndex(L, S, cat, heads);
      document.getElementById('pl-q').oninput = e => { IDXS.q = e.target.value; clearTimeout(draw.t); draw.t = setTimeout(draw, 150); };
      document.getElementById('pl-pool').onchange = e => { IDXS.pool = e.target.value; draw(); };
      document.getElementById('pl-team').onchange = e => { IDXS.team = e.target.value; draw(); };
      floorEl.oninput = e => { IDXS.floor = Number(e.target.value); document.getElementById('pl-floor-v').textContent = IDXS.floor; };
      floorEl.onchange = draw;
      document.getElementById('pl-extra').onchange = e => { IDXS.extra = e.target.value; draw(); };
      fx.wireToggle(el, 'pl-basis', v => { IDXS.basis = v; draw(); });
      draw();
      document.getElementById('pl-note').innerHTML = 'Pills are percentiles (100 = best; ↓ metrics are already flipped) against ' +
        'the whole league or, with the toggle, the player\'s position pool (guards, forwards, centres). The qualification floor for percentiles is ' + fx.num(cat.min_floor, 0) + ' minutes. ' +
        'Headline columns: ' + heads.map(m => fx.glossLink(m.key, fx.esc(m.label))).join(' · ') + '. The full catalogue of ' + metrics.length + ' metrics is on every player page and in the <a href="#/' + L + '/lab">lab</a>.';
    });
  });
}

function drawIndex(L, S, cat, heads) {
  const fx = FX();
  const P = cat.players, meta = fx.metaOf(cat.metrics);
  const q = IDXS.q.trim().toLowerCase();
  const extra = IDXS.extra && meta[IDXS.extra] ? meta[IDXS.extra] : null;
  const cols = heads.concat(extra && heads.indexOf(extra) < 0 ? [extra] : []);
  const ids = Object.keys(P).filter(id => {
    const p = P[id];
    if ((p.min || 0) < IDXS.floor) return false;
    if (IDXS.pool !== 'all' && p.pool !== IDXS.pool) return false;
    if (IDXS.team && p.team !== IDXS.team) return false;
    if (q && (String(p.name || '') + ' ' + fx.teamName(L, p.team) + ' ' + fx.teamAbbr(L, p.team)).toLowerCase().indexOf(q) < 0) return false;
    return true;
  });
  const sortKey = (heads[0] || {}).key;
  ids.sort((a, b) => {
    const va = (P[a].values || {})[sortKey], vb = (P[b].values || {})[sortKey];
    return (fx.isNum(vb) ? vb : -1e9) - (fx.isNum(va) ? va : -1e9) || (P[b].min || 0) - (P[a].min || 0);
  });
  const src = p => (IDXS.basis === 'pool' ? p.pct_pool : p.pct) || {};
  const rows = ids.map((id, i) => {
    const p = P[id];
    return { _href: fx.playerHref(L, id), cells: [
      { v: i + 1, cls: 'pos-cell' },
      { v: p.name || id, html: fx.playerLink(L, id, p.name, p.team) + (p.qualified === false ? ' <span class="pg-tag" title="Below the minutes floor: percentiles are not shown">low min</span>' : '') },
      { v: fx.teamName(L, p.team), html: fx.teamLink(L, p.team, { abbr: true }) },
      { v: p.pos || p.pool || '', html: fx.esc(p.pos || p.pool || '') },
      { v: p.age, html: fx.isNum(p.age) ? fx.num(p.age, 0) : '—' },
      p.gp || 0, { v: p.min || 0, html: fx.num(p.min, 0) }
    ].concat(cols.map(m => {
      const v = (p.values || {})[m.key], pc = src(p)[m.key];
      return { v: fx.isNum(v) ? v : -1e9, html: '<span class="hf-val">' + fx.fmt(m, v) + '</span> ' + fx.pill(pc), align: 'right' };
    })) };
  });
  const host = document.getElementById('pl-table');
  host.innerHTML = rows.length ? HW.tableHTML([{ label: '#', sortable: false }, { label: 'Player' }, { label: 'Team' }, { label: 'Pos' }, { label: 'Age', align: 'right' }, { label: 'GP', align: 'right' }, { label: 'Min', align: 'right' }]
    .concat(cols.map(m => ({ label: fx.shortLabel(m.label) + (m.lower ? ' ↓' : ''), align: 'right', title: (m.desc || m.label) + (m.lower ? ' (lower is better)' : '') }))), rows, { sticky: true, compact: true })
    : fx.muted('No player matches these filters.');
  HW.sortable(host);
  document.getElementById('pl-sub').textContent = ids.length + ' of ' + Object.keys(P).length + ' players · sorted by ' + ((heads[0] || {}).label || 'minutes') + '; click a header to sort, a row to open the player';
}

// ── player page ────────────────────────────────────────────────────────────

function renderPlayer(el, params, state) {
  const fx = FX(), L = fx.L(params, state);
  const pid = String(params.id || params.pid || (params.rest || [])[0] || '');
  el.innerHTML = fx.muted('Loading…');
  return fx.ready().then(() => {
    let S = fx.S(params, state, L);
    return Promise.all([fx.season(L, S), HW.load(L + '/players/' + pid + '.json')]).then(res => {
      if (!fx.alive(el)) return null;
      const career = res[1];
      const inSeason = fx.ok(res[0][0]) && (res[0][0].players || {})[pid];
      if (!inSeason && career && (career.seasons || []).length) {
        const last = career.seasons.map(s => s.season).filter(fx.isNum).sort((a, b) => b - a)[0];
        if (last && last !== S) {
          const asked = S; S = last;
          return fx.season(L, S).then(r2 => { if (fx.alive(el)) drawPlayer(el, L, S, pid, r2, career, asked); });
        }
      }
      drawPlayer(el, L, S, pid, res[0], career, null);
      return null;
    });
  });
}

function drawPlayer(el, L, S, pid, seasonRes, career, askedS) {
  const fx = FX(), C = fx.C;
  const cat = seasonRes[0], teams = seasonRes[1];
  const P = (fx.ok(cat) && cat.players) || {};
  const p = P[pid] || null;
  const metrics = (cat || {}).metrics || [];
  const cur = (career && career.current && (!career.current.season || career.current.season === S)) ? career.current : {};
  const seasonsArr = ((career || {}).seasons || []).slice().sort((a, b) => a.season - b.season);
  const srow = seasonsArr.find(s => s.season === S) || {};
  const name = (p && p.name) || (career && career.name) || fx.playerName(L, pid);
  const team = (p && p.team) || srow.team || null;
  const colour = team ? fx.teamColour(L, team) : C.blue;
  const age = p && fx.isNum(p.age) ? Math.floor(p.age) : fx.ageOf(career && career.dob);
  const pos = (p && p.pos) || (career && career.pos) || '';
  const pool = (p && p.pool) || (career && career.pool) || '';
  const vals = (p && p.values) || {};
  const val = cands => { const k = fx.pick(vals, cands); return k ? vals[k] : null; };
  const mates = Object.keys(P).filter(k => k !== pid && P[k].team === team && (!pool || P[k].pool === pool)).sort((a, b) => (P[b].min || 0) - (P[a].min || 0));

  let h = '<div class="pg-head" style="--team:' + fx.esc(colour) + '"><div class="pg-num" style="font-size:1.05rem">' + fx.esc(team ? fx.teamAbbr(L, team) : (pool || '—')) + '</div><div class="pg-body"><h2>' + fx.esc(name) + '</h2>' +
    '<div class="pg-sub">' + (team ? fx.teamLink(L, team) : '') + (pos ? '<span>' + fx.esc(pos) + (pool && pool !== pos ? ' · ' + fx.esc(pool) + ' pool' : '') + '</span>' : '') + (age !== null ? '<span>age ' + age + '</span>' : '') +
    '<span class="chip">' + fx.esc(L.toUpperCase() + ' ' + fx.seasonLabel(L, S)) + '</span>' + (p && p.qualified === false ? '<span class="chip warn">below the minutes floor</span>' : '') +
    (askedS ? '<span class="chip warn">no ' + fx.esc(fx.seasonLabel(L, askedS)) + ' games: showing ' + fx.esc(fx.seasonLabel(L, S)) + '</span>' : '') + '</div></div>' +
    '<div class="pg-links">' + (mates[0] ? '<a href="#/' + L + '/compare/players/' + encodeURIComponent(pid) + '/' + encodeURIComponent(mates[0]) + '">Compare with ' + fx.esc(fx.surname(P[mates[0]].name)) + ' →</a>' : '') +
    '<a href="#/' + L + '/lab">Lab →</a>' + (team ? '<a href="' + fx.teamHref(L, team) + '">Team →</a>' : '') + '<a href="#/' + L + '/players">All players →</a></div></div>';

  if (!p) {
    h += fx.card('This season', '', fx.muted(fx.ok(cat) ? fx.esc(name) + ' has no game in ' + fx.esc(fx.seasonLabel(L, S)) + '.' : 'The ' + fx.esc(fx.seasonLabel(L, S)) + ' player catalogue is not built yet.'));
    h += '<div id="pp-career"></div>';
    el.innerHTML = h;
    drawCareer(L, pid, career);
    return;
  }

  // Tiles.
  const hpm = fx.has(val(K.hpm)) ? val(K.hpm) : srow.hpm, ho = fx.has(val(K.hpm_o)) ? val(K.hpm_o) : srow.o, hd = fx.has(val(K.hpm_d)) ? val(K.hpm_d) : srow.d;
  const se = val(K.hpm_se);
  const rapm = fx.has(val(K.rapm)) ? val(K.rapm) : srow.rapm, box = fx.has(val(K.box)) ? val(K.box) : srow.box_impact, wpa = fx.has(val(K.wpa)) ? val(K.wpa) : srow.wpa;
  const awardsP = cur.awards || {};
  const bestAward = Object.keys(awardsP).filter(k => fx.isNum(fx.pOf(awardsP[k]))).sort((a, b) => fx.pOf(awardsP[b]) - fx.pOf(awardsP[a]))[0];
  const mpg = p.gp ? p.min / p.gp : null;
  h += '<div class="kpi-grid six">' + [
    fx.tile('HPM', fx.signed(hpm, 1) + (fx.isNum(se) ? ' <span class="hf-se">± ' + fx.num(se, 1) + '</span>' : ''), 'offence ' + fx.signed(ho, 1) + ' · defence ' + fx.signed(hd, 1) + ' per 100'),
    fx.tile('RAPM', fx.signed(rapm, 1), fx.has(rapm) ? 'ridge on lineup stints, per 100' : 'needs play-by-play'),
    fx.tile('Box impact', fx.signed(box, 1), 'box-score estimate of impact'),
    fx.tile('WPA', fx.signed(wpa, 2), fx.has(wpa) ? 'win probability added, season' : 'needs play-by-play'),
    fx.tile('Minutes', fx.num(mpg, 1) + ' <span class="hf-se">mpg</span>', (p.gp || 0) + ' games · ' + fx.num(p.min, 0) + ' min'),
    fx.tile('Award odds', bestAward ? fx.pct(fx.pOf(awardsP[bestAward])) : '—', bestAward ? fx.esc(fx.awardName(bestAward, L)) + ' · <a href="#/' + L + '/awards">races →</a>' : 'not in a race')
  ].join('') + '</div>';

  h += '<div class="card"><div class="card-header">Percentiles <span class="card-sub">The whole catalogue, ' + metrics.length + ' metrics. League: against every qualified player. Position pool: only against ' + fx.esc(pool === 'G' ? 'guards' : pool === 'F' ? 'forwards' : pool === 'C' ? 'centres' : 'the same pool') + '.</span>' +
    fx.toggle('pp-pct-src', [['pool', 'Position pool'], ['league', 'League']], 'pool') + '</div><div id="pp-pct"></div></div>';
  h += '<div class="grid-2"><div class="card"><div class="card-header">Profile <span class="card-sub">Ten headline metrics as position-pool percentiles' + (mates[0] ? ', against ' + fx.esc(P[mates[0]].name) : '') + '.</span></div><div id="pp-radar" style="height:400px"></div></div>' +
    '<div class="card"><div class="card-header">Season line <span class="card-sub">Per game, from the game log.</span></div><div id="pp-line"></div></div></div>';
  h += '<div class="card"><div class="card-header">Shot chart <span class="card-sub">Every located shot this season. Colour is points per shot against the league average from the same spot (red above, blue below); size is volume.</span>' +
    fx.toggle('pp-shot-kind', [['hex', 'Hex'], ['zone', 'Zones']], 'hex') + '</div><div class="hf-shot"><div id="pp-shot" class="hf-court"></div><div><div class="cmp-group-head">Zones</div><div id="pp-zones"></div><div class="cmp-group-head">Shot types</div><div id="pp-types"></div></div></div></div>';
  h += '<div class="grid-3"><div class="card"><div class="card-header">On / off <span class="card-sub">Team net rating per 100 with and without him.</span></div><div id="pp-onoff"></div></div>' +
    '<div class="card"><div class="card-header">Clutch <span class="card-sub">Last 5 minutes, margin within 5.</span></div><div id="pp-clutch"></div></div>' +
    '<div class="card"><div class="card-header">Projection <span class="card-sub">Rates the game model uses for lineups and injuries.</span></div><div id="pp-proj"></div></div></div>';
  h += '<div class="card"><div class="card-header">Best lineups <span class="card-sub">Five-man units with him, by possessions; net per 100, and shrunk towards the sum of the five players\' HPM.</span></div><div id="pp-lineups"></div></div>';
  h += '<div class="card"><div class="card-header">Game log <span class="card-sub">Game score (Hollinger) per game; bar colour is the plus-minus sign.</span></div><div id="pp-gs" style="height:240px"></div><div id="pp-log"></div></div>';
  h += '<div id="pp-career"></div>';
  el.innerHTML = h;

  const drawPct = src => {
    document.getElementById('pp-pct').innerHTML = fx.pctPanel(metrics, vals, src === 'league' ? p.pct : (p.pct_pool || p.pct),
      { note: (src === 'league' ? 'League percentile' : 'Position-pool percentile') + ', 100 = best. ↓ marks metrics where lower is better; the bar already accounts for it. Play-by-play metrics (shot quality, on/off, RAPM, WPA) exist from about 2017. Hover a row for the definition.' });
  };
  drawPct('pool');
  fx.wireToggle(el, 'pp-pct-src', drawPct);

  const axes = fx.headline(metrics, RADAR_PREFS, 10, p.pct_pool || p.pct).map(m => ({ key: m.key, label: fx.shortLabel(m.label) }));
  const mrow = mates[0] ? P[mates[0]] : null;
  const pc = fx.pairColours(colour, C.orange);
  fx.radar('pp-radar', axes, [{ name: name, pct: p.pct_pool || p.pct, colour: pc[0] }].concat(mrow ? [{ name: mrow.name, pct: mrow.pct_pool || mrow.pct, colour: pc[1] }] : []));

  // Season line from the log (or the career row).
  const log = (cur.log || []).slice().sort((a, b) => String(a.date).localeCompare(String(b.date)));
  const sum = k => log.reduce((s, r) => s + (fx.isNum(r[k]) ? Number(r[k]) : 0), 0);
  const n = log.length;
  if (n) {
    const pg = k => sum(k) / n;
    const fga = sum('fga'), fta = sum('fta'), pts = sum('pts');
    const ts = fga + 0.44 * fta > 0 ? pts / (2 * (fga + 0.44 * fta)) : null;
    document.getElementById('pp-line').innerHTML = '<div class="hf-kv">' + [
      ['Games', n], ['Minutes', fx.num(pg('min'), 1)], ['Points', fx.num(pg('pts'), 1)], ['Rebounds', fx.num(pg('reb'), 1)], ['Assists', fx.num(pg('ast'), 1)], ['Steals', fx.num(pg('stl'), 1)], ['Blocks', fx.num(pg('blk'), 1)], ['Turnovers', fx.num(pg('tov'), 1)],
      ['FG', fx.num(pg('fgm'), 1) + '–' + fx.num(pg('fga'), 1)], ['FG%', fga ? fx.fmtV(sum('fgm') / fga, 'pct') : '—'], ['3P', fx.num(pg('tpm'), 1) + '–' + fx.num(pg('tpa'), 1)], ['3P%', sum('tpa') ? fx.fmtV(sum('tpm') / sum('tpa'), 'pct') : '—'],
      ['FT%', fta ? fx.fmtV(sum('ftm') / fta, 'pct') : '—'], ['TS%', fx.fmtV(ts, 'pct')], ['+/-', fx.signed(pg('pm'), 1)], ['Game score', fx.num(pg('game_score'), 1)]
    ].map(x => '<div class="hf-kv-i"><span>' + x[0] + '</span><strong>' + x[1] + '</strong></div>').join('') + '</div>';
  } else document.getElementById('pp-line').innerHTML = srow.season ? '<div class="hf-kv">' + [['Games', srow.gp], ['Minutes', fx.num(srow.min, 0)], ['Points', fx.num(srow.pts, 1)], ['Rebounds', fx.num(srow.reb, 1)], ['Assists', fx.num(srow.ast, 1)], ['TS%', fx.fmtV(srow.ts, 'pct')]]
    .map(x => '<div class="hf-kv-i"><span>' + x[0] + '</span><strong>' + x[1] + '</strong></div>').join('') + '</div>' : fx.muted('No game log.');

  // Shots.
  const shots = cur.shots || {};
  document.getElementById('pp-zones').innerHTML = fx.zoneTable(shots.zones);
  document.getElementById('pp-types').innerHTML = fx.typeTable(shots.types);
  const drawShot = kind => {
    const node = document.getElementById('pp-shot');
    if (kind === 'zone' || !fx.rowsOf(shots.grid).length) {
      if (shots.zones && Object.keys(shots.zones).length) fx.zoneMap(node, L, shots.zones);
      else node.innerHTML = fx.muted('No shot data for this season (play-by-play from about 2017).');
    } else fx.cellChart(node, L, shots.grid);
  };
  drawShot('hex');
  fx.wireToggle(el, 'pp-shot-kind', drawShot);

  // On/off, clutch, projection.
  const oo = cur.on_off || {};
  document.getElementById('pp-onoff').innerHTML = Object.keys(oo).length ? '<div class="kpi-grid hf-mini">' + [
    fx.tile('On', fx.signed(oo.on_net, 1), fx.isNum(oo.poss_on) ? fx.num(oo.poss_on, 0) + ' poss' : ''), fx.tile('Off', fx.signed(oo.off_net, 1), fx.isNum(oo.poss_off) ? fx.num(oo.poss_off, 0) + ' poss' : ''),
    fx.tile('Difference', '<span class="' + (oo.diff > 0 ? 'pg-up' : oo.diff < 0 ? 'pg-down' : '') + '">' + fx.signed(oo.diff, 1) + '</span>', 'on minus off')
  ].join('') + '</div>' + fx.kvTiles(oo, null, ['on_net', 'off_net', 'diff', 'poss_on', 'poss_off']) : fx.muted('No on/off split (needs play-by-play lineups).');
  const cl = cur.clutch || {};
  document.getElementById('pp-clutch').innerHTML = Object.keys(cl).length ? '<div class="hf-kv">' + [['Minutes', fx.num(cl.min, 0)], ['Points', fx.num(cl.pts, 0)], ['TS%', fx.fmtV(cl.ts, 'pct')], ['Net / 100', fx.signed(cl.net, 1)], ['WPA', fx.signed(cl.wpa, 2)]]
    .map(x => '<div class="hf-kv-i"><span>' + x[0] + '</span><strong>' + x[1] + '</strong></div>').join('') + '</div>' : fx.muted('No clutch minutes recorded.');
  const pr = cur.projection || null;
  document.getElementById('pp-proj').innerHTML = pr && typeof pr === 'object' ? projHTML(pr) : fx.muted('No projection for this player.');

  // Lineups.
  const lus = cur.lineups || [];
  document.getElementById('pp-lineups').innerHTML = lus.length ? HW.tableHTML([{ label: 'Lineup' }, { label: 'Poss', align: 'right' }, { label: 'ORtg', align: 'right' }, { label: 'DRtg', align: 'right' }, { label: 'Net', align: 'right' }, { label: 'Shrunk net', align: 'right', title: 'Net per 100 shrunk towards the sum of the five players\' HPM' }],
    lus.map(u => [{ v: '', html: (u.players || []).map(x => x === pid ? '<strong>' + fx.esc(fx.surname(fx.playerName(L, x))) + '</strong>' : fx.playerLink(L, x, fx.surname(fx.playerName(L, x)))).join(' · ') },
      { v: u.poss, html: fx.num(u.poss, 0) }, { v: u.ortg, html: fx.num(u.ortg, 1) }, { v: u.drtg, html: fx.num(u.drtg, 1) }, { v: u.net, html: fx.signed(u.net, 1) }, { v: u.shrunk_net, html: fx.signed(u.shrunk_net, 1) }]), { compact: true }) : fx.muted('No lineup data (play-by-play seasons only).');
  HW.sortable('pp-lineups');

  // Game log.
  if (log.length) {
    fx.plot('pp-gs', [{ type: 'bar', x: log.map((r, i) => i + 1), y: log.map(r => r.game_score), text: log.map(r => fx.fmtDate(r.date, { year: false }) + ' ' + (r.home ? 'v ' : '@ ') + fx.teamAbbr(L, r.opp) + ': ' + (r.pts || 0) + ' pts, +/- ' + fx.signed(r.pm, 0)),
      textposition: 'none', marker: { color: log.map(r => (r.pm > 0 ? C.green : r.pm < 0 ? C.red : C.text3)) }, hovertemplate: '%{text}<br>game score %{y:.1f}<extra></extra>' }],
    fx.layout({ margin: { l: 40, r: 10, t: 10, b: 30 }, xaxis: { title: 'Game', dtick: log.length > 40 ? 10 : 5 }, yaxis: { title: 'Game score' }, bargap: 0.15 }));
    document.getElementById('pp-log').innerHTML = HW.tableHTML([{ label: 'Date' }, { label: 'Opp' }, { label: 'Min', align: 'right' }, { label: 'Pts', align: 'right' }, { label: 'Reb', align: 'right' }, { label: 'Ast', align: 'right' }, { label: 'Stl', align: 'right' }, { label: 'Blk', align: 'right' }, { label: 'TO', align: 'right' },
      { label: 'FG', align: 'right' }, { label: '3P', align: 'right' }, { label: 'FT', align: 'right' }, { label: '+/-', align: 'right' }, { label: 'GmSc', align: 'right' }, { label: 'WPA', align: 'right' }],
      log.slice().reverse().map(r => ({ _href: r.game ? fx.gameHref(L, r.game) : undefined, cells: [{ v: r.date, html: fx.fmtDate(r.date, { year: false }) }, { v: fx.teamAbbr(L, r.opp), html: (r.home ? 'v ' : '@ ') + fx.teamLink(L, r.opp, { abbr: true }) },
        { v: r.min, html: fx.num(r.min, 0) }, r.pts, r.reb, r.ast, r.stl, r.blk, r.tov, { v: r.fgm, html: (r.fgm || 0) + '–' + (r.fga || 0) }, { v: r.tpm, html: (r.tpm || 0) + '–' + (r.tpa || 0) }, { v: r.ftm, html: (r.ftm || 0) + '–' + (r.fta || 0) },
        { v: r.pm, html: fx.signed(r.pm, 0) }, { v: r.game_score, html: '<strong>' + fx.num(r.game_score, 1) + '</strong>' }, { v: r.wpa, html: fx.signed(r.wpa, 2) }] })), { compact: true, sticky: true });
    HW.sortable('pp-log');
  } else { document.getElementById('pp-gs').style.display = 'none'; document.getElementById('pp-log').innerHTML = fx.muted('No game log in the career file.'); }

  drawCareer(L, pid, career);
}

function drawCareer(L, pid, career) {
  const fx = FX(), C = fx.C;
  const host = document.getElementById('pp-career');
  if (!host) return;
  if (!career || career.ok === false) { host.innerHTML = fx.card('Career', '', fx.notBuilt('The career file', career)); return; }
  const seasons = (career.seasons || []).slice().sort((a, b) => b.season - a.season);
  const awards = (career.career_awards || []).slice().sort((a, b) => b[0] - a[0]);
  const tot = k => seasons.reduce((s, r) => s + (fx.isNum(r[k]) ? (k === 'gp' || k === 'min' ? r[k] : r[k] * (r.gp || 0)) : 0), 0);
  const gp = tot('gp');
  let h = '<div class="card"><div class="card-header">Career <span class="card-sub">' + seasons.length + ' season' + (seasons.length === 1 ? '' : 's') + (seasons.length ? ', ' + fx.seasonLabel(L, seasons[seasons.length - 1].season) + ' to ' + fx.seasonLabel(L, seasons[0].season) : '') +
    ' · box scores from 1997, play-by-play (RAPM, WPA) from about 2017</span></div>' +
    '<div class="kpi-grid six" style="padding:12px 12px 0">' + [
      fx.tile('Seasons', seasons.length), fx.tile('Games', gp), fx.tile('Points', fx.num(tot('pts'), 0), gp ? fx.num(tot('pts') / gp, 1) + ' a game' : ''),
      fx.tile('Rebounds', fx.num(tot('reb'), 0), gp ? fx.num(tot('reb') / gp, 1) + ' a game' : ''), fx.tile('Assists', fx.num(tot('ast'), 0), gp ? fx.num(tot('ast') / gp, 1) + ' a game' : ''),
      fx.tile('Awards', awards.length, awards.length ? awards.slice(0, 3).map(a => fx.esc(a[1]) + ' ' + fx.esc(fx.seasonLabel(L, a[0]))).join(', ') : '')
    ].join('') + '</div>' +
    '<div class="pg-split"><div><div class="pct-group-head" style="padding:0 14px">Seasons</div>' + HW.tableHTML([{ label: 'Season' }, { label: 'Team' }, { label: 'GP', align: 'right' }, { label: 'Min', align: 'right' }, { label: 'Pts', align: 'right' }, { label: 'Reb', align: 'right' }, { label: 'Ast', align: 'right' }, { label: 'TS%', align: 'right' },
      { label: 'HPM', align: 'right' }, { label: 'O', align: 'right' }, { label: 'D', align: 'right' }, { label: 'RAPM', align: 'right' }, { label: 'Box', align: 'right' }, { label: 'WPA', align: 'right' }],
      seasons.map(s => [{ v: s.season, html: fx.esc(fx.seasonLabel(L, s.season)) }, { v: fx.teamName(L, s.team), html: fx.teamLink(L, s.team, { abbr: true }) }, s.gp, { v: s.min, html: fx.num(s.min, 0) }, { v: s.pts, html: fx.num(s.pts, 1) }, { v: s.reb, html: fx.num(s.reb, 1) }, { v: s.ast, html: fx.num(s.ast, 1) },
        { v: s.ts, html: fx.fmtV(s.ts, 'pct') }, { v: s.hpm, html: '<strong>' + fx.signed(s.hpm, 1) + '</strong>' }, { v: s.o, html: fx.signed(s.o, 1) }, { v: s.d, html: fx.signed(s.d, 1) }, { v: s.rapm, html: fx.signed(s.rapm, 1) }, { v: s.box_impact, html: fx.signed(s.box_impact, 1) }, { v: s.wpa, html: fx.signed(s.wpa, 2) }]), { compact: true }) + '</div>' +
    '<div><div id="pp-hpm-path" style="height:340px"></div>' + (awards.length ? '<div class="pct-group-head" style="padding:0 14px">Awards</div><div class="hf-awards">' + awards.map(a => '<span class="chip">' + fx.esc(fx.seasonLabel(L, a[0])) + ' ' + fx.esc(a[1]) + '</span>').join(' ') + '</div>' : '') + '</div></div>' +
    '<div class="pct-group-head" style="padding:6px 14px 0">Similar players <span class="muted-inline">(nearest neighbours on the percentile vector)</span></div><div id="pp-similar"></div></div>';
  host.innerHTML = h;
  HW.sortable(host);
  const asc = seasons.slice().reverse().filter(s => fx.isNum(s.hpm));
  if (asc.length) {
    const x = asc.map(s => s.season);
    fx.plot('pp-hpm-path', [
      { type: 'scatter', mode: 'lines+markers', name: 'HPM', x: x, y: asc.map(s => s.hpm), line: { color: C.blue, width: 2.5 }, marker: { size: 7 }, hovertemplate: '%{x}: HPM %{y:+.1f}<extra></extra>' },
      { type: 'scatter', mode: 'lines', name: 'Offence', x: x, y: asc.map(s => s.o), line: { color: C.green, width: 1.4, dash: 'dot' }, hovertemplate: '%{x}: O %{y:+.1f}<extra></extra>' },
      { type: 'scatter', mode: 'lines', name: 'Defence', x: x, y: asc.map(s => s.d), line: { color: C.orange, width: 1.4, dash: 'dot' }, hovertemplate: '%{x}: D %{y:+.1f}<extra></extra>' }
    ].concat(asc.some(s => fx.isNum(s.rapm)) ? [{ type: 'scatter', mode: 'markers', name: 'RAPM', x: x, y: asc.map(s => s.rapm), marker: { color: C.purple, size: 7, symbol: 'diamond' }, hovertemplate: '%{x}: RAPM %{y:+.1f}<extra></extra>' }] : []),
    fx.layout({ showlegend: true, legend: { orientation: 'h', y: 1.12, font: { color: C.text2 } }, margin: { l: 45, r: 10, t: 30, b: 40 }, xaxis: { title: 'Season', tickformat: 'd', dtick: asc.length > 10 ? 2 : 1 }, yaxis: { title: 'Per 100 possessions', zeroline: true, zerolinecolor: '#6e7681' } }));
  } else document.getElementById('pp-hpm-path').innerHTML = fx.muted('No HPM history.');
  const sim = career.similar || [];
  document.getElementById('pp-similar').innerHTML = sim.length ? '<div class="hf-similar">' + sim.map(s => '<a class="hf-sim" href="' + fx.playerHref(L, s.id) + '"><strong>' + fx.esc(s.name || fx.playerName(L, s.id)) + '</strong><span>' + fx.esc(fx.seasonLabel(L, s.season)) + ' · distance ' + fx.num(s.distance, 2) + '</span></a>').join('') + '</div>' : fx.muted('No similar players computed.');
}

/* Projection row (impact.projections): per-game rates, minutes, availability, HPM now and next season. */
function projHTML(pr) {
  const fx = FX(), r = pr.rates || {};
  const items = [['Minutes', fx.num(pr.min, 1)], ['Availability', fx.isNum(pr.avail) ? fx.pct(pr.avail, 0) : '—'], ['HPM', fx.signed(pr.hpm, 1)], ['HPM next season', fx.signed(pr.hpm_next, 1)]]
    .concat([['pts', 'Points'], ['ast', 'Assists'], ['dreb', 'Def reb'], ['oreb', 'Off reb'], ['stl', 'Steals'], ['blk', 'Blocks'], ['tov', 'Turnovers'], ['tpa', '3PA']].filter(x => fx.isNum(r[x[0]])).map(x => [x[1], fx.num(r[x[0]], 1)]));
  if (fx.isNum(pr.aging) && pr.aging) items.push(['Aging step', fx.signed(pr.aging, 2)]);
  return '<div class="hf-kv">' + items.map(x => '<div class="hf-kv-i"><span>' + x[0] + '</span><strong>' + x[1] + '</strong></div>').join('') + '</div>' +
    (fx.isNum(pr.games) ? '<div class="pg-note">Exponentially weighted over ' + pr.games + ' recent games, regressed to the position mean; rates per game at the projected minutes.</div>' : '');
}

HW.route('players', renderPlayers);
HW.route('player', renderPlayer);
})(window.HW);
