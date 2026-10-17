/* The Quant Rink — history (#/history): every Stanley Cup champion since the NHL's first season
 * (1917–18), titles by franchise, the league's scoring environment by era, and season leaders.
 *
 * Data: data/history.json. Accepted shapes: {"champions": [{season, champion|team, runner_up|finalist,
 * result|series, conn_smythe, coach, note}] | {cols, rows}, "env"|"league"|"seasons": [{season, gpg, ...}] |
 * {S: {...}}, "season_leaders"|"leaders": {S: {metric: [[pid, name, team, value]]}} | [{season, metric, pid,
 * name, team, value}], "eras": [{from, to, name, note}]}. Uses RK.fk. */
(function (RK) {
'use strict';

const K = () => RK.fk;
const ST = { q: '', decade: '', env: '', season: '', board: '' };
/* The league's eras (start-year ranges), drawn as bands behind the scoring chart when the payload has none. */
const ERAS = [[1917, 1941, 'Early NHL', 'Two to ten teams; forward passing allowed in all zones only from 1929–30.'], [1942, 1966, 'Original Six', 'Six teams from 1942–43 to 1966–67.'],
  [1967, 1978, 'Expansion', 'Twelve teams in 1967–68, eighteen by 1974–75; the WHA competes from 1972.'], [1979, 1992, 'High scoring', 'Four WHA teams join in 1979; scoring peaks in the early 1980s.'],
  [1993, 2004, 'Dead puck', 'Trap systems and bigger goalies; scoring falls; the 2004–05 season is cancelled by a lockout.'], [2005, 2012, 'Post-lockout', 'Shootouts, the two-line pass removed, the salary cap.'],
  [2013, 2019, 'Analytics era', 'Possession and expected goals enter front offices; the 2012–13 season is cut to 48 games.'], [2020, 2100, 'Modern', '2019–20 paused and finished in bubbles; 2020–21 is 56 games in realigned divisions; 84 games from 2026–27.']];
const ENV_LABEL = { games: 'Regular-season games per team', gpg: 'Goals per team game', goals_pg: 'Goals per team game', gf_pg: 'Goals per team game', sv_pct: 'Save %', sh_pct: 'Shooting %', pp_pct: 'Power-play %', shots_pg: 'Shots per team game', sog_pg: 'Shots per team game',
  pim_pg: 'Penalty minutes per team game', ot_pct: 'Games to overtime', so_pct: 'Games to a shootout', home_win: 'Home win rate', teams: 'Teams', xg_pg: 'Expected goals per team game', pp_per_game: 'Power plays per team game' };

const startYear = s => { const v = K().sid(s); return v ? Math.floor(v / 10000) : null; };

function championsOf(d) {
  const k = K();
  const C = d.champions || d.cup || d.stanley_cup || d.winners;
  let rows = [];
  if (Array.isArray(C) && C.length && Array.isArray(C[0])) rows = C.map(r => ({ season: r[0], champion: r[1], runner_up: r[2], result: r[3], conn_smythe: r[4] }));
  else if (C && !Array.isArray(C) && !C.cols && typeof C === 'object') rows = Object.keys(C).map(s => Object.assign({ season: s }, typeof C[s] === 'string' ? { champion: C[s] } : C[s]));
  else rows = k.listOf(C);
  return rows.map(r => ({ S: k.sid(r.season || r.year), champion: r.champion_abbr || r.champion || r.winner || r.team || null, champName: r.champion_abbr ? r.champion : (r.champion_name || r.winner_name || null), runner: r.finalist_abbr || r.runner_up || r.finalist || r.loser || r.opponent || null, runnerName: r.finalist_abbr ? r.finalist : (r.runner_up_name || r.finalist_name || null), series: r.series,
    result: r.result || (typeof r.series === 'string' ? r.series : '') || r.score || '', conn: r.conn_smythe || r.mvp || null, connName: r.conn_smythe_name || null, coach: r.coach || '', note: r.note || (r.champion === null ? 'Not awarded' : '') }))
    .filter(r => r.S).sort((a, b) => b.S - a.S);
}
function envOf(d) {
  const k = K();
  const E = d.env || d.environment || d.league || d.seasons;
  if (!E) return [];
  const rows = Array.isArray(E) || (E.cols && E.rows) ? k.listOf(E) : Object.keys(E).map(s => Object.assign({ season: s }, E[s]));
  return rows.map(r => Object.assign({}, r, { S: k.sid(r.season) })).filter(r => r.S).sort((a, b) => a.S - b.S);
}
function leadersOf(d) {
  const k = K();
  const L = d.season_leaders || d.leaders || d.boards;
  const out = {};   // S -> metric -> [{pid, name, team, value}]
  if (!L) return out;
  const push = (S, m, r) => { const s = k.sid(S); if (!s) return; out[s] = out[s] || {}; (out[s][m] = out[s][m] || []).push(r); };
  const norm = r => (Array.isArray(r) ? { pid: r[0], name: r[1], team: r[2], value: r[3] } : { pid: r.pid || r.id, name: r.name, team: r.team, value: k.first(r.value, r.v, r.total), label: r.label });
  if (Array.isArray(L) || (L.cols && L.rows)) k.listOf(L).forEach(r => push(r.season, r.metric || r.key || r.stat, norm(r)));
  else Object.keys(L).forEach(a => {
    const x = L[a];
    if (k.sid(a) && x && typeof x === 'object' && !Array.isArray(x)) Object.keys(x).forEach(m => (Array.isArray(x[m]) ? x[m] : (x[m] && typeof x[m] === 'object' ? [x[m]] : [])).forEach(r => push(a, m, norm(r))));
    else if (x && typeof x === 'object' && !Array.isArray(x)) Object.keys(x).forEach(s => (Array.isArray(x[s]) ? x[s] : []).forEach(r => push(s, a, norm(r))));
  });
  return out;
}

function render(el) {
  const k = K();
  el.innerHTML = '<div class="card"><div class="card-header">Stanley Cup champions <span class="card-sub" id="hi-sub">Loading…</span></div>' +
    '<div class="lab-controls gq-controls"><label>Search<input id="hi-q" class="gq-search" type="search" placeholder="team or player…"></label><label>Decade<select id="hi-dec"><option value="">All</option></select></label></div>' +
    '<div id="hi-table">' + k.muted('Loading…') + '</div><div class="pg-note gq-note" id="hi-note"></div></div>' +
    '<div class="grid-2"><div class="card"><div class="card-header">Titles by franchise <span class="card-sub">Cups won since 1917–18, with renamed and relocated clubs folded into today\'s franchise (Toronto Arenas and St. Patricks into the Maple Leafs, the North Stars into the Stars); the original Ottawa Senators (1917–34) are a different club from today\'s; Victoria\'s 1925 Cup (a WCHL club) is not counted.</span></div><div id="hi-titles" class="gf-chart-lg"></div></div>' +
    '<div class="card"><div class="card-header">The league by era <span class="card-sub">The league\'s eras and what changed, with the regular season\'s length (and league rates where the payload carries them) by season.</span><span class="gq-ctl" id="hi-env-ctl"></span></div><div id="hi-env" class="gf-chart-lg"></div><div class="pg-note gq-note" id="hi-env-n"></div></div></div>' +
    '<div class="card"><div class="card-header">Season leaders <span class="card-sub" id="hi-ld-sub">The league leaders in each season on file.</span><span class="gq-ctl" id="hi-ld-ctl"></span></div><div id="hi-ld"></div></div>';
  return k.ready().then(() => Promise.all([RK.load('history.json'), k.loadNames()])).then(res => {
    if (!k.alive(el)) return;
    const d = res[0], $ = k.$;
    if (!d || d.ok === false) { $('hi-table').innerHTML = k.notBuilt('The history file', d); k.set('hi-sub', ''); ['hi-titles', 'hi-env'].forEach(x => k.empty(x, '')); k.set('hi-ld', ''); return; }
    const champs = championsOf(d), env = envOf(d), leaders = leadersOf(d);
    const eras = k.listOf(d.eras).map(e => [startYear(e.from) || e.from, startYear(e.to) || e.to, e.name, e.note || '']).filter(e => k.isNum(e[0]));
    // champions
    const decs = Array.from(new Set(champs.map(r => Math.floor(startYear(r.S) / 10) * 10))).sort((a, b) => b - a);
    $('hi-dec').innerHTML = '<option value="">All</option>' + decs.map(x => '<option value="' + x + '"' + (String(x) === ST.decade ? ' selected' : '') + '>' + x + 's</option>').join('');
    $('hi-q').value = ST.q;
    const draw = () => drawChamps(champs);
    let t = null;
    $('hi-q').oninput = e => { ST.q = e.target.value; clearTimeout(t); t = setTimeout(draw, 150); };
    $('hi-dec').onchange = e => { ST.decade = e.target.value; draw(); };
    draw();
    titles(champs);
    envChart(env, eras.length ? eras : ERAS);
    seasonLeaders(leaders);
  });
}

function drawChamps(champs) {
  const k = K();
  const q = k.fold(ST.q.trim());
  const nm = (t, n) => (t ? k.teamName(t) : (n || ''));
  const rows = champs.filter(r => (!ST.decade || Math.floor(startYear(r.S) / 10) * 10 === Number(ST.decade)) &&
    (!q || k.fold([r.champion, nm(r.champion, r.champName), r.runner, nm(r.runner, r.runnerName), r.connName || (r.conn ? k.name(r.conn) : ''), r.coach].join(' ')).indexOf(q) >= 0));
  const team = (t, n, S) => (t && /^[A-Z]{2,3}$/.test(String(t)) ? k.teamChip(t, S) + ' ' + k.esc(n || k.teamName(t)) : k.esc(n || t || '—'));
  // the series score and the Conn Smythe only when the payload carries them (history.json has neither today)
  const hasRes = champs.some(r => r.result), hasConn = champs.some(r => r.conn || r.connName);
  k.set('hi-table', rows.length ? k.table([{ label: 'Season' }, { label: 'Champion' }, { label: 'Runner-up' }].concat(hasRes ? [{ label: 'Final' }] : []).concat(hasConn ? [{ label: 'Conn Smythe', title: 'Playoff MVP (awarded from 1964–65)' }] : []),
    rows.map(r => [{ v: r.S, html: '<strong>' + k.esc(k.sLabel(r.S)) + '</strong>' }, { v: nm(r.champion, r.champName), html: r.champion || r.champName ? team(r.champion, r.champName, r.S) : '<span class="muted-inline">' + k.esc(r.note || 'Not awarded') + '</span>' },
      { v: nm(r.runner, r.runnerName), html: r.runner || r.runnerName ? team(r.runner, r.runnerName, r.S) : '—' }].concat(hasRes ? [{ v: r.result, html: k.esc(r.result || '—') }] : [])
      .concat(hasConn ? [{ v: r.connName || r.conn || '', html: r.conn && /^\d+$/.test(String(r.conn)) ? k.playerLink(String(r.conn), r.connName) : k.esc(r.connName || r.conn || '—') }] : [])), { compact: true, sticky: true })
    : k.muted('No champion matches.'));
  k.sortable(k.$('hi-table'));
  const first = champs.length ? champs[champs.length - 1].S : null;
  k.set('hi-sub', rows.length + ' of ' + champs.length + ' seasons' + (first ? ' since ' + k.sLabel(first) : ''));
  k.set('hi-note', 'The Cup was not awarded in 1918–19 (the Final was abandoned in the influenza pandemic) or in 2004–05 (the season was cancelled by a lockout). Before 1926–27 the Cup was contested with other leagues; the table lists the NHL\'s participation as the payload records it. Franchise codes follow the current club (relocations keep their history).');
}

/* Franchise of a champion as engraved: name changes and relocations folded into the club that carries the history today. */
const FRANCHISE = { 'Toronto Arenas': 'Toronto Maple Leafs', 'Toronto St. Patricks': 'Toronto Maple Leafs', 'Chicago Black Hawks': 'Chicago Blackhawks', 'Mighty Ducks of Anaheim': 'Anaheim Ducks',
  'Minnesota North Stars': 'Dallas Stars', 'Quebec Nordiques': 'Colorado Avalanche', 'Hartford Whalers': 'Carolina Hurricanes', 'Atlanta Flames': 'Calgary Flames', 'Kansas City Scouts': 'New Jersey Devils', 'Colorado Rockies': 'New Jersey Devils' };
function franchiseOf(r) {
  const nm = r.champName || r.champion;
  if (!nm) return null;
  if (/^[A-Z]{2,3}$/.test(String(r.champion))) return K().teamName(r.champion);
  if (nm === 'Ottawa Senators' && startYear(r.S) < 1935) return 'Ottawa Senators (1917–34)';
  return FRANCHISE[nm] || nm;
}
function titles(champs) {
  const k = K(), node = k.$('hi-titles');
  if (!node) return;
  const by = {};
  champs.forEach(r => { const f = franchiseOf(r); if (f && !/Victoria Cougars/.test(f)) by[f] = (by[f] || 0) + 1; });
  const list = Object.keys(by).sort((a, b) => by[b] - by[a] || a.localeCompare(b));
  if (!list.length) { k.empty(node, 'No champions on file.'); return; }
  const abbr = n => Object.keys(k.NHL).find(t => k.NHL[t][0] === n || k.teamName(t) === n);
  node.style.height = Math.max(300, 22 * list.length + 60) + 'px';
  k.plot(node, [{ type: 'bar', orientation: 'h', y: list, x: list.map(t => by[t]), marker: { color: list.map(t => (abbr(t) ? k.teamColour(abbr(t)) : '#6e7681')) }, customdata: list.map(t => (abbr(t) ? k.teamHref(abbr(t)) : '')), text: list.map(t => String(by[t])), textposition: 'outside', cliponaxis: false, hovertemplate: '%{y}: %{x} Cups<extra></extra>' }],
    k.layout({ margin: { l: 170, r: 30, t: 10, b: 30 }, yaxis: { autorange: 'reversed', automargin: true, tickfont: { size: 10 } }, xaxis: { title: 'Stanley Cups', dtick: 5 } }));
  k.clickThrough(node);
}

function envChart(env, eras) {
  const k = K(), node = k.$('hi-env'), ctl = k.$('hi-env-ctl');
  if (!node) return;
  if (env.length < 2) { k.empty(node, 'The league environment by season is not available yet.'); return; }
  const keys = Object.keys(ENV_LABEL).filter(x => env.some(r => k.isNum(r[x])));
  Object.keys(env[0]).forEach(x => { if (!/^(season|S)$/.test(x) && keys.indexOf(x) < 0 && env.some(r => k.isNum(r[x]))) keys.push(x); });
  if (!keys.length) { k.empty(node, 'No league rates.'); return; }
  if (!ST.env || keys.indexOf(ST.env) < 0) ST.env = ['gpg', 'goals_pg', 'gf_pg', 'games'].find(x => keys.indexOf(x) >= 0) || keys[0];
  if (ctl) ctl.innerHTML = k.select('hi-env-k', keys.map(x => [x, ENV_LABEL[x] || k.titleCase(x)]), ST.env);
  const draw = () => {
    const xs = env.map(r => startYear(r.S)), vs = env.map(r => r[ST.env]);
    const pctLike = /pct|rate|win/.test(ST.env) && vs.filter(k.isNum).every(v => Math.abs(v) <= 1.5);
    const shapes = [], ann = [];
    const x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs);
    eras.forEach((e, i) => { const a = Math.max(e[0], x0), b = Math.min(e[1] + 1, x1 + 1); if (a >= b) return; shapes.push({ type: 'rect', xref: 'x', yref: 'paper', x0: a - 0.5, x1: b - 0.5, y0: 0, y1: 1, fillcolor: i % 2 ? 'rgba(92,198,242,0.05)' : 'rgba(255,255,255,0.02)', line: { width: 0 }, layer: 'below' });
      ann.push({ x: (a + b - 1) / 2, y: 1, yref: 'paper', yanchor: 'bottom', text: k.esc(e[2]), showarrow: false, font: { size: 9, color: '#8b949e' }, textangle: k.narrow(node) ? -90 : 0, hovertext: k.esc(e[3]) }); });
    k.plot(node, [{ type: 'scatter', mode: 'lines+markers', x: xs, y: vs, text: env.map(r => k.sLabel(r.S)), line: { color: K().ACC, width: 2 }, marker: { size: 4 }, connectgaps: false, hovertemplate: '%{text}: %{y' + (pctLike ? ':.1%' : ':.2f') + '}<extra></extra>' }],
      k.layout({ margin: { l: 56, r: 10, t: 34, b: 36 }, shapes: shapes, annotations: ann, xaxis: { title: 'Season (start year)', dtick: 10 }, yaxis: { title: ENV_LABEL[ST.env] || k.titleCase(ST.env), tickformat: pctLike ? '.1%' : '' } }));
  };
  draw();
  const sel = k.$('hi-env-k');
  if (sel) sel.onchange = e => { ST.env = e.target.value; draw(); };
  const last = env[env.length - 1], peak = env.slice().sort((a, b) => (b[ST.env] || 0) - (a[ST.env] || 0))[0];
  k.set('hi-env-n', 'Shaded bands are the league\'s eras (hover for what changed). ' + (k.isNum((peak || {})[ST.env]) ? 'Highest ' + k.esc((ENV_LABEL[ST.env] || ST.env).toLowerCase()) + ' on file: ' + k.esc(k.sLabel(peak.S)) + '. ' : '') +
    'Shortened seasons (1994–95, 2012–13, 2019–20, 2020–21) are rates, so they compare directly' + (last ? '; the latest season on file is ' + k.esc(k.sLabel(last.S)) : '') + '. Shot-based rates (save and shooting percentage) are incomplete in the league\'s early records: read them from the 1980s on.');
}

function seasonLeaders(L) {
  const k = K(), host = k.$('hi-ld'), ctl = k.$('hi-ld-ctl');
  if (!host) return;
  const seasons = Object.keys(L).map(Number).sort((a, b) => b - a);
  if (!seasons.length) { host.innerHTML = k.muted('Season leaders are not in the history file yet.'); return; }
  if (!ST.season || seasons.indexOf(Number(ST.season)) < 0) ST.season = String(seasons[0]);
  if (ctl) ctl.innerHTML = k.select('hi-ld-s', seasons.map(s => [String(s), k.sLabel(s)]), ST.season);
  const LBL = { g: 'Goals', goals: 'Goals', a: 'Assists', assists: 'Assists', pts: 'Points', points: 'Points', pm: 'Plus-minus', ppg: 'Power-play goals', sv_pct: 'Save %', gaa: 'Goals against average', w: 'Wins', wins: 'Wins', so: 'Shutouts', gsax: 'GSAx', ixg: 'Individual xG', value: 'Rink value' };
  const draw = () => {
    const B = L[Number(ST.season)] || {};
    const ms = Object.keys(B);
    host.innerHTML = ms.length ? '<div class="gq-glance">' + ms.map(m => '<div class="gq-mini"><div class="gq-mini-h">' + k.esc((B[m][0] || {}).label || LBL[m] || k.titleCase(m)) + '</div>' +
      B[m].slice(0, 10).map((r, i) => '<div class="gq-mini-r"><span class="gq-mini-n">' + (i + 1) + '</span>' + (r.pid ? k.playerLink(String(r.pid), r.name, Number(ST.season)) : k.esc(r.name || '')) + (r.team ? ' ' + k.teamChip(r.team, Number(ST.season)) : '') +
        '<span class="gq-mini-v">' + (/sv_pct/.test(m) ? k.svp(r.value) : /xgf_pct/.test(m) ? k.pct(r.value, 1) : /gaa/.test(m) ? k.num(r.value, 2) : /gsax|ixg|value|gar|war/.test(m) ? k.num(r.value, 1) : k.fmtV(r.value, 'int')) + '</span></div>').join('') + '</div>').join('') + '</div>' : k.muted('No leaders for this season.');
  };
  draw();
  const sel = k.$('hi-ld-s');
  if (sel) sel.onchange = e => { ST.season = e.target.value; draw(); };
  k.set('hi-ld-sub', seasons.length + ' seasons on file, ' + k.esc(k.sLabel(seasons[seasons.length - 1])) + ' to ' + k.esc(k.sLabel(seasons[0])) + '; the league\'s official season totals.');
}

if (typeof RK.route === 'function') { try { RK.route('history', render); } catch (e) { /* bound */ } }
})(window.RK || (window.RK = {}));
