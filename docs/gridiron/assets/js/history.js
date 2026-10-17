/* The Quant Gridiron — history (#/history): leaders since 1999, raw and era-adjusted.
 *
 * Single-season and career boards from play-by-play since 1999 (EPA, CPOE, success, value, RYOE,
 * receiving, kicking), each available raw or era-adjusted (against that season's league: the
 * passing game of 2004 is not the passing game of 2024), filtered by seasons and searchable, with the
 * league environment by season (EPA per play, pass rate, scoring, completion %, fourth-down go rate).
 *
 * Data: data/history.json. Accepted shapes: {"boards": [BOARD] | {key: BOARD}, "env": [{season, ...}] |
 * {season: {...}}}; BOARD = {key, label, scope: "season"|"career", group, fmt, lower, desc, adj_desc,
 * rows: [{pid, name, season, team, value, adj, n}] | {cols, rows}}. Uses GI.fk. */
(function (GI) {
'use strict';

const K = () => GI.fk;
const ST = { board: '', adj: true, from: 1999, to: 2100, q: '', group: '' };
const ENV_LABEL = { ppg: 'Points per team game', home_win: 'Home win rate', penalties_pg: 'Penalties per game', epa_play: 'EPA per play', epa_per_play: 'EPA per play', pass_rate: 'Pass rate', pts_pg: 'Points per team game', points_pg: 'Points per team game', comp_pct: 'Completion %', cmp_pct: 'Completion %', ypa: 'Yards per attempt',
  sack_rate: 'Sack rate', int_rate: 'INT rate', go_rate: '4th-down go rate', success: 'Success rate', success_rate: 'Success rate', pass_epa: 'EPA per dropback', rush_epa: 'EPA per carry', fg_pct: 'FG %', fg_50_pct: '50+ FG %', xp_pct: 'XP %', hfa: 'Home-field advantage (pts)', plays_pg: 'Plays per team game', adot: 'aDOT', ttt: 'Time to throw' };

function boardsOf(d) {
  const k = K();
  if (!d || d.ok === false) return [];
  let B = d.boards || d.leaders || null;
  const out = [];
  const add = (key, b) => {
    if (!b || typeof b !== 'object') return;
    const rows = k.listOf(b.rows || b.data || b.leaders || (Array.isArray(b) ? b : null)).map(r => (Array.isArray(r) ? { pid: r[0], season: r[1], team: r[2], value: r[3], adj: r[4], n: r[5] } : r));
    out.push({ key: b.key || key, mkey: b.mkey || b.key || key, label: b.label || k.titleCase(b.key || key), scope: b.scope || (/career/i.test(key) ? 'career' : 'season'), group: b.group || b.pos || '', fmt: b.fmt || '', adjFmt: b.adj_fmt || b.fmt_adj || '',
      lower: !!b.lower, desc: b.desc || '', adjDesc: b.adj_desc || b.adjusted || '', unit: b.unit || '', rows: rows.map(r => ({ pid: String(r.pid || r.id || r.gsis_id || ''), name: r.name, season: k.first(r.season), first: k.first(r.first, r.from), last: k.first(r.last, r.to), team: r.team || r.teams,
        value: k.first(r.value, r.v, r.raw), adj: k.first(r.adj, r.era_adj, r.adjusted, r.plus, r.z), n: k.first(r.n, r.sample, r.att, r.plays) })) });
  };
  // builder D: season_leaders / career_leaders {id: {label, group, key, rows}} with season_cols / career_cols
  if (!B && (d.season_leaders || d.career_leaders)) {
    [['season_leaders', 'season_cols', 'season'], ['career_leaders', 'career_cols', 'career']].forEach(z => {
      const X = d[z[0]] || {}, cols = d[z[1]] || [];
      Object.keys(X).forEach(id => {
        const b = X[id] || {};
        const rows = (b.rows || []).map(r => { if (!Array.isArray(r)) return r; const o = {}; cols.forEach((c, i) => { o[c] = r[i]; }); return o; })
          .map(o => (z[2] === 'career' ? { pid: o.pid, name: o.name, first: o.first, last: o.last, value: o.total, n: o.seasons, team: o.team } : { pid: o.pid, name: o.name, season: o.season, team: o.team, value: o.value, adj: o.plus }));
        add(id, Object.assign({}, b, { key: id, mkey: b.key || id, scope: z[2], rows: rows, adj_desc: z[2] === 'season' ? (d.era_note || '') : '', adj_fmt: '0', unit: z[2] === 'career' ? 'seasons' : '' }));
      });
    });
  }
  if (Array.isArray(B)) B.forEach(b => add(b.key, b));
  else if (B && typeof B === 'object') Object.keys(B).forEach(x => add(x, B[x]));
  else ['seasons', 'careers', 'season', 'career'].forEach(sc => { const X = d[sc]; if (X && typeof X === 'object') Object.keys(X).forEach(x => add(x, Object.assign({ scope: /career/.test(sc) ? 'career' : 'season' }, Array.isArray(X[x]) ? { rows: X[x] } : X[x]))); });
  return out.filter(b => b.rows.length);
}
function envOf(d) {
  const k = K();
  const E = d && (d.env || d.environment || d.league);
  if (!E) return [];
  if (Array.isArray(E) || (E.cols && E.rows)) return k.listOf(E).filter(r => k.isNum(r.season));
  return Object.keys(E).filter(s => /^\d{4}$/.test(s)).map(s => Object.assign({ season: Number(s) }, E[s]));
}

function render(el, params) {
  const k = K();
  el.innerHTML = '<div class="card"><div class="card-header">History <span class="card-sub" id="hi-sub">Loading…</span><span class="gq-ctl">' + k.toggle('hi-adj', [['1', 'Era-adjusted'], ['0', 'Raw']], ST.adj ? '1' : '0') + '</span></div>' +
    '<div class="lab-controls gq-controls"><label>Board<select id="hi-board" class="gq-wide"></select></label><label>Group<select id="hi-group"><option value="">All groups</option></select></label>' +
    '<label>From<select id="hi-from"></select></label><label>To<select id="hi-to"></select></label><label>Search<input id="hi-q" class="gq-search" type="search" placeholder="player or team…"></label></div>' +
    '<div id="hi-table">' + k.muted('Loading…') + '</div><div class="pg-note gq-note" id="hi-note"></div></div>' +
    '<div class="card"><div class="card-header">The league since 1999 <span class="card-sub">League-wide rates by season from play-by-play: the environment the era adjustment works against.</span><span class="gq-ctl" id="hi-env-ctl"></span></div><div id="hi-env" class="gf-chart"></div></div>';
  return k.ready().then(() => Promise.all([GI.load('history.json'), k.loadNames(), k.loadY(k.curSeason(), 'players.json')])).then(res => {
    if (!k.alive(el)) return;
    const d = res[0], $ = k.$;
    const boards = boardsOf(d);
    const meta = k.metaOf(((k.catOf(res[2]) || {}).metrics) || []);
    boards.forEach(b => { const m = meta[b.mkey]; if (!m) return; if (!b.fmt) b.fmt = b.scope === 'career' && /^(pct|epa|2|3|yds|sec)$/.test(m.fmt) ? '1' : m.fmt; if (!b.desc) b.desc = (b.scope === 'career' ? 'Career total since 1999. ' : '') + (m.desc || ''); b.lower = b.lower || (b.scope === 'season' && !!m.lower); });
    const env = envOf(d);
    if (!boards.length) { k.set('hi-table', k.notBuilt('The history file', d)); k.set('hi-sub', ''); }
    else {
      const seasons = [];
      boards.forEach(b => b.rows.forEach(r => { [r.season, r.first, r.last].forEach(s => { if (k.isNum(s) && seasons.indexOf(s) < 0) seasons.push(s); }); }));
      seasons.sort((a, b) => a - b);
      const lo = seasons[0] || 1999, hi = seasons[seasons.length - 1] || k.curSeason();
      if (ST.from < lo) ST.from = lo; if (ST.to > hi) ST.to = hi;
      const yrs = []; for (let y = lo; y <= hi; y++) yrs.push(y);
      $('hi-from').innerHTML = yrs.map(y => '<option' + (y === ST.from ? ' selected' : '') + '>' + y + '</option>').join('');
      $('hi-to').innerHTML = yrs.map(y => '<option' + (y === ST.to ? ' selected' : '') + '>' + y + '</option>').join('');
      const groups = Array.from(new Set(boards.map(b => b.group).filter(Boolean)));
      $('hi-group').innerHTML = '<option value="">All groups</option>' + groups.map(g => '<option' + (g === ST.group ? ' selected' : '') + '>' + k.esc(g) + '</option>').join('');
      $('hi-group').parentNode.style.display = groups.length > 1 ? '' : 'none';
      const fillBoards = () => {
        const list = boards.filter(b => !ST.group || b.group === ST.group);
        if (!list.some(b => b.key + '|' + b.scope === ST.board)) ST.board = list.length ? list[0].key + '|' + list[0].scope : '';
        const sc = ['season', 'career'];
        $('hi-board').innerHTML = sc.map(s => { const bs = list.filter(b => b.scope === s); return bs.length ? '<optgroup label="' + (s === 'career' ? 'Careers' : 'Single seasons') + '">' + bs.map(b => '<option value="' + k.esc(b.key + '|' + b.scope) + '"' + (b.key + '|' + b.scope === ST.board ? ' selected' : '') + '>' + k.esc((b.group ? b.group + ' · ' : '') + b.label) + '</option>').join('') + '</optgroup>' : ''; }).join('');
      };
      fillBoards();
      $('hi-q').value = ST.q;
      const draw = () => drawBoard(boards.find(b => b.key + '|' + b.scope === ST.board) || boards[0], d);
      $('hi-board').onchange = e => { ST.board = e.target.value; draw(); };
      $('hi-group').onchange = e => { ST.group = e.target.value; fillBoards(); draw(); };
      $('hi-from').onchange = e => { ST.from = Number(e.target.value); draw(); };
      $('hi-to').onchange = e => { ST.to = Number(e.target.value); draw(); };
      let t = null;
      $('hi-q').oninput = e => { ST.q = e.target.value; clearTimeout(t); t = setTimeout(draw, 200); };
      k.wireToggle(el, 'hi-adj', v => { ST.adj = v === '1'; draw(); });
      draw();
    }
    envChart(env);
  });
}

function drawBoard(b, d) {
  const k = K();
  if (!b) return;
  const hasAdj = b.rows.some(r => k.isNum(r.adj));
  const useAdj = ST.adj && hasAdj;
  const q = k.fold(ST.q.trim());
  const inRange = r => (b.scope === 'career' ? (!k.isNum(r.last) || r.last >= ST.from) && (!k.isNum(r.first) || r.first <= ST.to) : (!k.isNum(r.season) || (r.season >= ST.from && r.season <= ST.to)));
  const rows = b.rows.filter(r => inRange(r) && (!q || k.fold((r.name || k.name(r.pid)) + ' ' + (r.team || '')).indexOf(q) >= 0));
  const key = useAdj ? 'adj' : 'value';
  rows.sort((x, y) => { const a = x[key], c = y[key]; const dd = (k.isNum(c) ? c : -1e9) - (k.isNum(a) ? a : -1e9); return b.lower && !useAdj ? -dd : dd; });
  const fmtA = b.adjFmt || (rows.some(r => k.isNum(r.adj) && Math.abs(r.adj) > 20) ? '0' : '2');
  const S = null;
  const hasN = rows.some(r => k.isNum(r.n));
  k.set('hi-table', rows.length ? k.table([{ label: '#', sortable: false }, { label: 'Player' }, { label: b.scope === 'career' ? 'Seasons' : 'Season' }, { label: 'Team' }, { label: b.scope === 'career' ? 'Seasons' : 'Sample', align: 'right', cls: hasN ? '' : 'gf-hide' }, { label: b.label + (b.lower ? ' ↓' : ''), align: 'right' }].concat(hasAdj ? [{ label: 'Era-adjusted', align: 'right', title: b.adjDesc || 'Against that season\'s league' }] : []),
    rows.slice(0, 200).map((r, i) => ({ _href: r.pid ? k.playerHref(r.pid, b.scope === 'season' ? r.season : null) : null, cells: [{ v: i + 1, cls: 'pos-cell' }, { v: r.name || k.name(r.pid), html: r.pid ? k.playerLink(r.pid, r.name, b.scope === 'season' ? r.season : null) : k.esc(r.name || '—') },
      { v: k.first(r.season, r.first), html: b.scope === 'career' ? k.esc((r.first || '') + '–' + (r.last || '')) : '<strong>' + k.esc(r.season) + '</strong>' },
      { v: r.team || '', html: Array.isArray(r.team) ? r.team.slice(0, 3).map(t => k.teamChip(t, S)).join(' ') : String(r.team || '').split('/').filter(Boolean).slice(0, 3).map(t => k.teamChip(t, S)).join(' ') || '—' },
      { v: r.n, html: k.int(r.n) }, { v: r.value, html: (useAdj ? '' : '<strong>') + k.fmtV(r.value, b.fmt) + (useAdj ? '' : '</strong>') }].concat(hasAdj ? [{ v: r.adj, html: (useAdj ? '<strong>' : '') + k.fmtV(r.adj, fmtA) + (useAdj ? '</strong>' : '') }] : []) })), { compact: true, sticky: true })
    : k.muted('Nobody on this board matches.'));
  k.sortable(k.$('hi-table'));
  k.set('hi-sub', rows.length + ' on the ' + (b.scope === 'career' ? 'career' : 'single-season') + ' board · ' + ST.from + '–' + ST.to + ' · sorted ' + (useAdj ? 'era-adjusted' : 'raw'));
  k.set('hi-note', (b.desc ? '<strong>' + k.esc(b.label) + '</strong>: ' + k.esc(b.desc) + ' ' : '') + (hasAdj ? '<strong>Era-adjusted</strong>: ' + k.esc(b.adjDesc || 'the value against that season\'s league average, so a season is measured against its own environment.') + ' ' : (ST.adj ? 'This board has no era-adjusted value. ' : '')) +
    (d.note ? k.esc(d.note) + ' ' : '') + 'Play-by-play from nflverse (1999 on); CPOE and air yards from 2006, when air yards were first charted; NGS from 2016; FTN from 2022.');
}

function envChart(env) {
  const k = K(), node = k.$('hi-env'), ctl = k.$('hi-env-ctl');
  if (!node) return;
  if (env.length < 2) { node.innerHTML = k.muted('The league environment by season is not available yet.'); node.style.height = 'auto'; return; }
  env.sort((a, b) => a.season - b.season);
  const keys = Object.keys(ENV_LABEL).filter(x => env.some(r => k.isNum(r[x])));
  Object.keys(env[0]).forEach(x => { if (x !== 'season' && keys.indexOf(x) < 0 && env.some(r => k.isNum(r[x]))) keys.push(x); });
  if (!keys.length) { node.innerHTML = k.muted('No league rates.'); return; }
  let cur = keys.indexOf('epa_play') >= 0 ? 'epa_play' : keys[0];
  if (ctl) ctl.innerHTML = k.select('hi-env-k', keys.map(x => [x, ENV_LABEL[x] || k.titleCase(x)]), cur);
  const draw = () => {
    const vs = env.map(r => r[cur]);
    const pctLike = /rate|pct|success/.test(cur) && vs.filter(k.isNum).every(v => Math.abs(v) <= 1.5);
    k.plot(node, [{ type: 'scatter', mode: 'lines+markers', x: env.map(r => r.season), y: vs, line: { color: k.ACC, width: 2 }, hovertemplate: '%{x}: %{y' + (pctLike ? ':.1%' : ':.3f') + '}<extra></extra>' }],
      k.layout({ margin: { l: 56, r: 10, t: 10, b: 36 }, xaxis: { dtick: 2 }, yaxis: { title: ENV_LABEL[cur] || k.titleCase(cur), tickformat: pctLike ? '.0%' : '' } }));
  };
  draw();
  const sel = k.$('hi-env-k');
  if (sel) sel.onchange = e => { cur = e.target.value; draw(); };
}

if (typeof GI.route === 'function') { try { GI.route('history', render); } catch (e) { /* bound */ } }
})(window.GI || (window.GI = {}));
