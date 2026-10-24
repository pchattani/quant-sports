/* The Quant Rink — Fantasy (#/fantasy): projections for standard NHL fantasy categories and points, rankings and tiers,
 * value over replacement on a 12-team roster, the next four fantasy weeks (Monday to Sunday), streaming goalies,
 * waiver targets, buy-low / sell-high, breakouts, our picks, and the walk-forward backtest ("How good are these
 * projections?").
 *
 * Data: data/<S>/fantasy.json (analytics/fantasy.py build_current: cols/rows per player with per-game (pg_*) and
 * rest-of-season (ros_*) categories, w1..w4 [games, points] (goalies [games, starts, points]), flags, rank, tier, vor,
 * z, pre_rank; points (default weights), weeks, roster, teams (games per week, back-to-backs, opponent factor),
 * goalie_next {pid: [[date, opp, P(start), P(win), points]]}, picks, backtest summary) and data/fantasy_backtest.json.
 * Points weights are editable here and kept in this browser (localStorage, best effort); the defaults are our own, not
 * any platform's. No fantasy platform's ownership, ADP or rankings are used. Uses RK.fk (skaters.js). */
(function (RK) {
'use strict';

const K = () => RK.fk;
const POS_ONE = { C: 'C', L: 'LW', R: 'RW', D: 'D', G: 'G' };
const CS = ['g', 'a', 'pm', 'ppp', 'sog', 'hit', 'blk'];
const CG = ['w', 'ga', 'sv', 'so'];
const FLAG = { add: ['Add', 'ok'], drop: ['Drop', ''], buy: ['Buy low', 'ok'], sell: ['Sell high', 'warn'], breakout: ['Breakout', 'ok'] };
const FS = { pos: 'all', team: 'all', flag: 'all', fmt: 'pts', n: '100', inj: '1' };
const LS_KEY = 'qr-fantasy-weights-v1';

function rowsOf(d) {
  const cols = (d && d.cols) || [];
  return ((d && d.rows) || []).map(r => { const o = {}; cols.forEach((c, i) => { o[c] = r[i]; }); return o; });
}

function loadWeights(def) {
  let w = null;
  try { w = JSON.parse(window.localStorage.getItem(LS_KEY) || 'null'); } catch (e) { w = null; }
  const out = {};
  Object.keys(def).forEach(c => { out[c] = w && typeof w[c] === 'number' && isFinite(w[c]) ? w[c] : def[c]; });
  return out;
}
function saveWeights(w) { try { window.localStorage.setItem(LS_KEY, JSON.stringify(w)); } catch (e) { /* private mode */ } }

function pts(r, w, pre) {
  const cats = r.kind === 'G' ? CG : CS;
  let s = 0;
  cats.forEach(c => { const v = r[pre + c]; if (typeof v === 'number') s += (w[c] || 0) * v; });
  return s;
}

/* Tiers at natural gaps (fantasy.py tiers): a new tier where the drop is among the largest 10 % of drops in the top 240. */
function tiers(vals) {
  const top = vals.slice(0, 240);
  const drops = [];
  for (let i = 0; i + 1 < top.length; i++) drops.push(top[i] - top[i + 1]);
  const s = drops.slice().sort((a, b) => a - b);
  const cut = s.length >= 5 ? s[Math.min(s.length - 1, Math.floor(0.9 * (s.length - 1)))] : Infinity;
  const out = [];
  let t = 1, size = 0;
  for (let i = 0; i < vals.length; i++) {
    out.push(i < 240 ? t : null);
    size++;
    if (i + 1 < vals.length && i < 239 && size >= 3 && vals[i] - vals[i + 1] > cut && cut > 0) { t++; size = 0; }
  }
  return out.map(x => (x === null ? t + 1 : x));
}

/* Value over replacement (fantasy.py replacement): greedy 12-team draft by rest-of-season points. */
function replacement(list, roster, nTeams) {
  const slots = {};
  Object.keys(roster).forEach(p => { slots[p] = roster[p] * nTeams; });
  const taken = {};
  list.slice().sort((a, b) => b._ros - a._ros).forEach(p => {
    const opts = p.pos === 'G' ? ['G', 'BN'] : [p.pos, 'UTIL', 'BN'];
    for (let i = 0; i < opts.length; i++) if ((slots[opts[i]] || 0) > 0) { slots[opts[i]]--; taken[p.id] = 1; break; }
  });
  const rep = {};
  ['C', 'L', 'R', 'D', 'G'].forEach(pos => { const u = list.filter(p => p.pos === pos && !taken[p.id]).map(p => p._ros); rep[pos] = u.length ? Math.max.apply(null, u) : 0; });
  return rep;
}

function render(el) {
  const k = K();
  el.innerHTML = k.muted('Loading…');
  return k.ready().then(() => {
    const S = k.curSeason();
    return Promise.all([k.loadY(S, 'fantasy.json'), RK.load('fantasy_backtest.json'), k.loadNames()]).then(res => {
      if (!k.alive(el)) return;
      const d = res[0];
      const tabs = RK.valuation ? RK.valuation.tabs(S, 'fantasy') : '';
      if (!k.ok(d) || !(d.rows || []).length) { el.innerHTML = tabs + k.card('Fantasy', '', '<div class="pad">' + k.notBuilt('The fantasy projections', d) + '</div>'); return; }
      draw(el, S, d, res[1], tabs);
    });
  });
}

function flagChips(r) {
  const k = K();
  return (r.flags || []).map(f => '<span class="chip ' + ((FLAG[f] || [])[1] || '') + '">' + k.esc((FLAG[f] || [f])[0]) + '</span>').join(' ');
}

function draw(el, S, d, bt, tabs) {
  const k = K();
  const all = rowsOf(d);
  const W = loadWeights(d.points || {});
  const wk = d.weeks || [];
  let h = tabs + QK.explain('<b>What’s that number?</b> Every projection here is fantasy points under our default scoring (change any weight under Scoring and the rankings follow) over the games left on each club’s schedule. The backtest at the foot shows how close these projections came in past seasons.', { html: true }) +
    '<div class="card"><div class="card-header">Fantasy ' + k.esc(k.sLabel(S)) + ' <span class="card-sub">Projections for the standard NHL categories (skaters G, A, +/-, PPP, SOG, HIT, BLK; goalies W, GA, SV, SO, with GAA and SV%) from our own models: ice time and power-play role, individual expected goals × finishing, assists from on-ice chances, opponents\' goals- and shots-against, the schedule, goalie starts and the game model\'s win probabilities. As of ' + k.esc(k.fmtDate(d.asof)) + '. No fantasy platform\'s ownership, ADP or rankings are used (their terms do not allow it): "add" and "drop" come from our own season-start and current projections. <a href="#/methodology/fantasy">Method</a></span></div><div id="fy-tiles"></div></div>';
  h += '<div class="card"><div class="card-header">Our picks <span class="card-sub">A short list, each with the data behind it.</span></div><div id="fy-picks" class="fy-picks"></div></div>';
  h += '<div class="card"><div class="card-header">Scoring <span class="card-sub">Points per category (our default, not any platform\'s; change any weight, it stays in this browser) or categories (sum of z-scores over the top 240 skaters / 48 goalies, default categories).</span></div><div class="lab-controls vl-ctl fy-w">' +
    '<label>Format<select id="fy-fmt"><option value="pts">Points</option><option value="cat">Categories (z)</option></select></label>' +
    CS.concat(CG).map(c => '<label>' + k.esc((d.labels || {})[c] || c) + '<input type="number" step="0.1" id="fy-w-' + c + '" value="' + W[c] + '"></label>').join('') +
    '<button type="button" class="tbtn" id="fy-reset">Default weights</button></div></div>';
  const teams = Array.from(new Set(all.map(r => r.team).filter(Boolean))).sort();
  h += '<div class="card"><div class="card-header">Rankings <span class="card-sub" id="fy-sub"></span></div><div class="lab-controls vl-ctl">' +
    '<label>Position<select id="fy-pos"><option value="all">Everyone</option><option value="S">Skaters</option><option value="C">C</option><option value="L">LW</option><option value="R">RW</option><option value="D">D</option><option value="G">G</option></select></label>' +
    '<label>Team<select id="fy-team"><option value="all">All teams</option>' + teams.map(t => '<option value="' + k.esc(t) + '">' + k.esc(k.teamName(t)) + '</option>').join('') + '</select></label>' +
    '<label>Flag<select id="fy-flag"><option value="all">Any</option>' + Object.keys(FLAG).map(f => '<option value="' + f + '">' + FLAG[f][0] + '</option>').join('') + '</select></label>' +
    '<label>Injured<select id="fy-inj"><option value="1">Show</option><option value="0">Hide</option></select></label>' +
    '<label>Show<select id="fy-n"><option value="100">Top 100</option><option value="250">Top 250</option><option value="0">All</option></select></label></div><div id="fy-table"></div>' +
    '<div class="pg-note gq-note">Pts/G: projected points a game (goalies: a start). RoS: rest of season (games left × availability; goalies × projected starts). VOR: over the best player left after a 12-team draft of ' + Object.keys(d.roster || {}).map(p => (d.roster[p]) + ' ' + ({ L: 'LW', R: 'RW', BN: 'bench' }[p] || p)).join(', ') + '. Wk 1 is the rest of this week (Mon–Sun). Tiers break at the largest gaps in the top 240. Pre: our rank before the first game. Injuries: ESPN status and return date.</div></div>';
  h += '<div class="grid-2"><div class="card"><div class="card-header">Streaming goalies <span class="card-sub">This week\'s projected starts × matchups, goalies outside the top 24.</span></div><div id="fy-stream"></div></div>' +
    '<div class="card"><div class="card-header">Schedule <span class="card-sub">Games per fantasy week (back-to-backs) and the opponents\' goals-against factor (1.00 = league average; higher = easier to score on).</span></div><div id="fy-sched"></div></div></div>';
  h += '<div class="grid-2"><div class="card"><div class="card-header">Buy low / sell high <span class="card-sub">Shooting or goaltending far from what the underlying numbers support, with the expected change in points a game.</span></div><div id="fy-luck"></div></div>' +
    '<div class="card"><div class="card-header">Waiver targets and breakouts <span class="card-sub">Adds: outside our season-start top ' + d.top_n + ', inside it now (drops: the reverse). Breakouts: 24 or younger with more ice time or power-play time than last season.</span></div><div id="fy-adds"></div></div></div>';
  h += '<div class="card" id="fy-bt-card"><div class="card-header">How good are these projections? <span class="card-sub">A walk-forward backtest: at every weekly checkpoint of the last five completed seasons, the projection made from games before that day only, against what followed over the next week and the rest of the season, beside two naive baselines. MAE per player-game (skaters, per game played) or per club game (goalies), in default points; Spearman: rank correlation across players, averaged over checkpoints.</span></div><div id="fy-bt"></div></div>';
  el.innerHTML = h;
  const $ = id => document.getElementById(id);
  $('fy-fmt').value = FS.fmt; $('fy-pos').value = FS.pos; $('fy-team').value = teams.indexOf(FS.team) >= 0 ? FS.team : 'all'; $('fy-flag').value = FS.flag; $('fy-n').value = FS.n; $('fy-inj').value = FS.inj;
  function recompute() {
    const def = d.points || {};
    all.forEach(r => {
      r._pg = pts(r, W, 'pg_');
      r._ros = FS.fmt === 'cat' ? (r.z || 0) : pts(r, W, 'ros_');
      const dpg = r.pts_pg || 0;
      const scale = dpg > 0 ? pts(r, W, 'pg_') / pts(r, def, 'pg_') : 1;
      r._wk = [r.w1, r.w2, r.w3, r.w4].map(x => (x ? { g: x[0], s: x.length > 2 ? x[1] : null, p: (x.length > 2 ? x[2] : x[1]) * (isFinite(scale) ? scale : 1) } : { g: 0, s: null, p: 0 }));
    });
    const ord = all.slice().sort((a, b) => b._ros - a._ros);
    const tv = tiers(ord.map(r => r._ros));
    ord.forEach((r, i) => { r._rank = i + 1; r._tier = tv[i]; });
    const rep = replacement(all, d.roster || {}, d.n_teams || 12);
    all.forEach(r => { r._vor = r._ros - (rep[r.pos] || 0); });
  }
  function drawTable() {
    let list = all.filter(r => (FS.pos === 'all' || (FS.pos === 'S' ? r.kind === 'S' : r.pos === FS.pos)) && (FS.team === 'all' || r.team === FS.team) &&
      (FS.flag === 'all' || (r.flags || []).indexOf(FS.flag) >= 0) && (FS.inj === '1' || !r.inj));
    list.sort((a, b) => a._rank - b._rank);
    const total = list.length;
    if (Number(FS.n) > 0) list = list.slice(0, Number(FS.n));
    const goalies = FS.pos === 'G';
    $('fy-sub').textContent = total + ' players · ' + (FS.fmt === 'cat' ? 'categories (z-score total)' : 'points (your weights)');
    const head = [{ label: '#', align: 'right' }, { label: 'Tier', align: 'right' }, { label: 'Player' }, { label: 'Team' }, { label: 'Pos' }, { label: 'Pts/G', align: 'right' }, { label: FS.fmt === 'cat' ? 'Z' : 'RoS', align: 'right' }, { label: 'VOR', align: 'right' },
      { label: 'Wk 1', align: 'right', title: wk[0] ? wk[0][0] + ' to ' + wk[0][1] : '' }, { label: 'Wk 2', align: 'right', title: wk[1] ? wk[1][0] + ' to ' + wk[1][1] : '' }]
      .concat(goalies ? [{ label: 'Start %', align: 'right' }, { label: 'W', align: 'right', title: 'Per start' }, { label: 'GAA', align: 'right' }, { label: 'SV%', align: 'right' }, { label: 'SO', align: 'right', title: 'Per start' }]
        : [{ label: 'G', align: 'right', title: 'Per game' }, { label: 'A', align: 'right' }, { label: 'PPP', align: 'right' }, { label: 'SOG', align: 'right' }, { label: 'HIT', align: 'right' }, { label: 'BLK', align: 'right' }, { label: '+/-', align: 'right' }, { label: 'TOI', align: 'right' }, { label: 'PP', align: 'center', title: 'Power-play unit (from PP ice time on the club)' }])
      .concat([{ label: 'Pre', align: 'right', title: 'Our rank before the first game' }, { label: 'Flags' }]);
    $('fy-table').innerHTML = list.length ? k.table(head, list.map(r => ({ _href: k.playerHref(r.id), cells: [r._rank, r._tier, { v: r.name, html: k.playerLink(r.id, r.name) + (r.inj ? ' <span class="chip vv-inj" title="' + k.esc((r.inj[1] ? 'return ' + r.inj[1] : '')) + '">' + k.esc(r.inj[0]) + '</span>' : '') },
      { v: r.team, html: k.teamChip(r.team) }, POS_ONE[r.pos] || r.pos, { v: r._pg, html: k.num(r._pg, 2) }, { v: r._ros, html: '<strong>' + k.num(r._ros, FS.fmt === 'cat' ? 2 : 0) + '</strong>' }, { v: r._vor, html: k.num(r._vor, FS.fmt === 'cat' ? 2 : 0) },
      { v: r._wk[0].p, html: k.num(r._wk[0].p, 1) + ' <span class="muted-inline">' + r._wk[0].g + 'g</span>' }, { v: r._wk[1].p, html: k.num(r._wk[1].p, 1) + ' <span class="muted-inline">' + r._wk[1].g + 'g</span>' }]
      .concat(goalies ? [{ v: r.share, html: k.pct(r.share, 0) }, { v: r.pg_w, html: k.num(r.pg_w, 2) }, { v: r.gaa, html: k.num(r.gaa, 2) }, { v: r.svp, html: k.svp(r.svp) }, { v: r.pg_so, html: k.num(r.pg_so, 3) }]
        : (r.kind === 'G' ? [{ v: null, html: '<span class="muted-inline">goalie: ' + k.pct(r.share, 0) + ' of starts, GAA ' + k.num(r.gaa, 2) + ', SV% ' + k.svp(r.svp) + '</span>', cls: 'fy-gspan' }, '', '', '', '', '', '', '', ''] : [{ v: r.pg_g, html: k.num(r.pg_g, 2) }, { v: r.pg_a, html: k.num(r.pg_a, 2) }, { v: r.pg_ppp, html: k.num(r.pg_ppp, 2) }, { v: r.pg_sog, html: k.num(r.pg_sog, 2) }, { v: r.pg_hit, html: k.num(r.pg_hit, 2) },
          { v: r.pg_blk, html: k.num(r.pg_blk, 2) }, { v: r.pg_pm, html: k.signed(r.pg_pm, 2) }, { v: r.toi, html: k.num(r.toi, 1) }, r.pp_unit ? 'PP' + r.pp_unit : '—']))
      .concat([{ v: r.pre_rank, html: k.isNum(r.pre_rank) ? String(r.pre_rank) : '—' }, { v: (r.flags || []).join(' '), html: flagChips(r) }]) })), { compact: true, sticky: true }) : k.muted('No players match.');
    k.sortable('fy-table');
  }
  function drawTiles() {
    const sk = all.filter(r => r.kind === 'S').sort((a, b) => a._rank - b._rank)[0];
    const gl = all.filter(r => r.kind === 'G').sort((a, b) => a._rank - b._rank)[0];
    const add = all.filter(r => (r.flags || []).indexOf('add') >= 0).sort((a, b) => a._rank - b._rank)[0];
    const bs = (d.backtest || {}).pts || {};
    const m = (bs.S_ros || {}).model, b1 = (bs.S_ros || {}).std;
    $('fy-tiles').innerHTML = k.tiles([k.tile('Top skater', sk ? k.playerLink(sk.id, sk.name) : '—', sk ? k.num(sk._pg, 2) + ' points a game · ' + k.esc(sk.team) : ''),
      k.tile('Top goalie', gl ? k.playerLink(gl.id, gl.name) : '—', gl ? k.num(gl._pg, 2) + ' a start · ' + k.pct(gl.share, 0) + ' of starts' : ''),
      k.tile('Best add', add ? k.playerLink(add.id, add.name) : '—', add ? 'rank ' + add._rank + ' now, ' + (add.pre_rank || '—') + ' at the start' : ''),
      k.tile('Backtest, rest of season', m ? k.num(m[0], 3) : '—', m && b1 ? 'MAE a game v ' + k.num(b1[0], 3) + ' (season to date); Spearman ' + k.num(m[1], 2) : 'not computed yet')]);
  }
  function drawSide() {
    const gl = all.filter(r => r.kind === 'G').sort((a, b) => a._rank - b._rank);
    const top24 = {}; gl.slice(0, 24).forEach(r => { top24[r.id] = 1; });
    const st = gl.filter(r => !top24[r.id] && r._wk[0].g > 0).sort((a, b) => b._wk[0].p - a._wk[0].p).slice(0, 10);
    $('fy-stream').innerHTML = st.length ? k.table([{ label: 'Goalie' }, { label: 'Team' }, { label: 'Starts', align: 'right', title: 'Projected starts this week' }, { label: 'Pts', align: 'right', title: 'This week' }, { label: 'Next games', title: 'Date, opponent, P(start), P(club wins)' }],
      st.map(r => [{ v: r.name, html: k.playerLink(r.id, r.name) }, { v: r.team, html: k.teamChip(r.team) }, { v: r._wk[0].s, html: k.num(r._wk[0].s, 1) + ' / ' + r._wk[0].g }, { v: r._wk[0].p, html: '<strong>' + k.num(r._wk[0].p, 1) + '</strong>' },
        { v: '', html: '<span class="fy-next">' + ((d.goalie_next || {})[r.id] || []).slice(0, 3).map(x => k.esc(String(x[0]).slice(5)) + ' ' + k.esc(x[1]) + ' ' + k.pct(x[2], 0) + '/' + k.pct(x[3], 0)).join(' · ') + '</span>' }]), { compact: true }) : k.muted('No streaming options this week.');
    const tms = Object.keys(d.teams || {}).sort();
    $('fy-sched').innerHTML = k.table([{ label: 'Team' }, { label: 'Left', align: 'right' }].concat(wk.map((w, i) => ({ label: 'Wk ' + (i + 1), align: 'right', title: w[0] + ' to ' + w[1] }))).concat([{ label: 'Opp GA', align: 'right', title: 'Mean opponent goals-against factor over the four weeks' }]),
      tms.map(t => { const x = d.teams[t]; const fs = x.weeks.filter(w => k.isNum(w[2])).map(w => w[2]); return [{ v: t, html: k.teamChip(t) }, x.left].concat(x.weeks.map(w => ({ v: w[0], html: w[0] + (w[1] ? ' <span class="muted-inline">' + w[1] + ' b2b</span>' : '') }))).concat([{ v: fs.length ? k.mean(fs) : null, html: fs.length ? k.num(k.mean(fs), 2) : '—' }]); }), { compact: true, sticky: true });
    const lk = all.filter(r => (r.flags || []).indexOf('buy') >= 0 || (r.flags || []).indexOf('sell') >= 0).sort((a, b) => a._rank - b._rank).slice(0, 30);
    $('fy-luck').innerHTML = lk.length ? k.table([{ label: 'Player' }, { label: 'Call' }, { label: 'So far', align: 'right', title: 'Points a game so far (default weights); goalies: save % this season' }, { label: 'Proj', align: 'right', title: 'Projected points a game' },
      { label: 'Change', align: 'right', title: 'Expected change in points a game' }, { label: 'Luck', align: 'right', title: 'Skaters: goals − finishing-adjusted expected goals; goalies: GSAx − talent × xG faced' }, { label: 'PDO', align: 'right', title: 'On-ice 5v5 SH% + SV%' }],
    lk.map(r => [{ v: r.name, html: k.playerLink(r.id, r.name) + ' <span class="muted-inline">' + k.esc(r.team) + ' ' + (POS_ONE[r.pos] || '') + '</span>' }, { v: (r.flags || []).join(' '), html: flagChips({ flags: (r.flags || []).filter(f => f === 'buy' || f === 'sell') }) },
      { v: r.act_pg, html: k.num(r.act_pg, 2) }, { v: r.pts_pg, html: k.num(r.pts_pg, 2) }, { v: r.regress, html: k.isNum(r.regress) ? '<span class="' + (r.regress > 0 ? 'pg-up' : 'pg-down') + '">' + k.signed(r.regress, 2) + '</span>' : '—' },
      { v: r.luck, html: k.signed(r.luck, 1) }, { v: r.pdo ? r.pdo[0] : null, html: r.pdo ? k.num(r.pdo[0], 3) : '—' }]), { compact: true }) : k.muted('No strong buy-low or sell-high signals yet.');
    const ad = all.filter(r => ['add', 'drop', 'breakout'].some(f => (r.flags || []).indexOf(f) >= 0)).sort((a, b) => a._rank - b._rank).slice(0, 40);
    $('fy-adds').innerHTML = ad.length ? k.table([{ label: 'Player' }, { label: 'Call' }, { label: 'Rank', align: 'right' }, { label: 'Pre', align: 'right' }, { label: 'TOI (5)', align: 'right', title: 'Minutes a game, last five; last season in brackets' }, { label: 'PP (5)', align: 'right' }],
      ad.map(r => [{ v: r.name, html: k.playerLink(r.id, r.name) + ' <span class="muted-inline">' + k.esc(r.team) + ' ' + (POS_ONE[r.pos] || '') + (k.isNum(r.age) ? ', ' + k.num(r.age, 0) : '') + '</span>' },
        { v: (r.flags || []).join(' '), html: flagChips({ flags: (r.flags || []).filter(f => f === 'add' || f === 'drop' || f === 'breakout') }) }, r._rank, { v: r.pre_rank, html: k.isNum(r.pre_rank) ? String(r.pre_rank) : '—' },
        { v: r.toi5, html: k.isNum(r.toi5) ? k.num(r.toi5, 1) + (k.isNum(r.toi_prev) ? ' <span class="muted-inline">(' + k.num(r.toi_prev, 1) + ')</span>' : '') : '—' },
        { v: r.pp5, html: k.isNum(r.pp5) ? k.num(r.pp5, 1) + (k.isNum(r.pp_prev) ? ' <span class="muted-inline">(' + k.num(r.pp_prev, 1) + ')</span>' : '') : '—' }]), { compact: true }) : k.muted('No waiver signals yet.');
    k.sortable(el);
  }
  $('fy-picks').innerHTML = (d.picks || []).length ? (d.picks || []).map(p => '<div class="fy-pick"><span class="chip ' + (p.kind === 'Sell high' ? 'warn' : 'ok') + '">' + k.esc(p.kind) + '</span> ' + k.playerLink(p.id, p.name) +
    ' <span class="muted-inline">' + k.esc(p.team) + ' ' + k.esc(POS_ONE[p.pos] || p.pos) + '</span><div class="fy-why">' + k.esc(p.why) + '</div></div>').join('') : k.muted('No picks yet.');
  drawBacktest(bt);
  function all3() { recompute(); drawTiles(); drawTable(); drawSide(); }
  CS.concat(CG).forEach(c => { $('fy-w-' + c).onchange = e => { const v = Number(e.target.value); W[c] = isFinite(v) ? v : 0; saveWeights(W); all3(); }; });
  $('fy-reset').onclick = () => { Object.keys(d.points || {}).forEach(c => { W[c] = d.points[c]; const n = $('fy-w-' + c); if (n) n.value = W[c]; }); saveWeights(W); all3(); };
  $('fy-fmt').onchange = e => { FS.fmt = e.target.value; all3(); };
  ['pos', 'team', 'flag', 'n', 'inj'].forEach(x => { $('fy-' + x).onchange = e => { FS[x] = e.target.value; drawTable(); }; });
  all3();
}

function drawBacktest(bt) {
  const k = K();
  const host = document.getElementById('fy-bt');
  if (!host) return;
  if (!k.ok(bt) || !(bt.rows || []).length) { host.innerHTML = '<div class="pad">' + k.muted('The backtest has not been computed yet.') + '</div>'; return; }
  const R = {};
  bt.rows.forEach(r => { R[r[0] + '|' + r[1] + '|' + r[2] + '|' + r[3]] = r; });
  const who = [['model', 'Our projection'], ['std', 'Season to date'], ['last', 'Last season']];
  const cell = (key, j, nd, lowBetter) => {
    const vals = who.map(w => (R[key + '|' + w[0]] || [])[j]);
    const best = vals.filter(k.isNum).reduce((a, b) => (lowBetter ? Math.min(a, b) : Math.max(a, b)), lowBetter ? Infinity : -Infinity);
    return vals.map(v => ({ v: v, html: k.isNum(v) ? (v === best ? '<strong>' + k.num(v, nd) + '</strong>' : k.num(v, nd)) : '—' }));
  };
  const lines = [['S', 'week', 'Skaters, next week'], ['S', 'ros', 'Skaters, rest of season'], ['G', 'week', 'Goalies, next week'], ['G', 'ros', 'Goalies, rest of season']];
  let h = '<div class="grid-2"><div>' + k.table([{ label: 'Points' }, { label: 'MAE: ours', align: 'right' }, { label: 'to date', align: 'right' }, { label: 'last season', align: 'right' }, { label: 'ρ: ours', align: 'right' }, { label: 'to date', align: 'right' }, { label: 'last season', align: 'right' }],
    lines.map(l => [l[2]].concat(cell(l[0] + '|' + l[1] + '|pts', 4, 3, true)).concat(cell(l[0] + '|' + l[1] + '|pts', 5, 3, false))), { compact: true }) + '</div><div>';
  const cats = ['g', 'a', 'pm', 'ppp', 'sog', 'hit', 'blk'];
  h += k.table([{ label: 'Skater category (rest of season)' }, { label: 'MAE: ours', align: 'right' }, { label: 'to date', align: 'right' }, { label: 'last', align: 'right' }, { label: 'ρ: ours', align: 'right' }, { label: 'to date', align: 'right' }, { label: 'last', align: 'right' }],
    cats.map(c => [c.toUpperCase().replace('PM', '+/-')].concat(cell('S|ros|' + c, 4, 3, true)).concat(cell('S|ros|' + c, 5, 3, false))), { compact: true }) + '</div></div>';
  h += '<div class="pg-note gq-note">Seasons ' + (bt.seasons || []).map(s => k.sLabel(s)).join(', ') + '; ' + k.int(bt.checkpoints) + ' weekly checkpoints. Bold: the best of the three. Baselines: ' + k.esc((bt.baselines || {}).std || '') + '; ' + k.esc((bt.baselines || {}).last || '') + '.' + (bt.stale ? ' (Computed before the latest model change; it is refreshed by a separate run.)' : '') + ' Where a baseline wins, it is shown as it is.</div>';
  host.innerHTML = h;
}

RK.route('fantasy', render);
})(window.RK);
