/* The Quant Gridiron — fantasy football (#/fantasy).
 *
 * PPR / half-PPR / standard projections for the coming week and the rest of the season from our play-level usage
 * model and the game model's implied totals (analytics/fantasy.py). Tabs: our picks (with reasons), this week's
 * rankings with tiers and floor/ceiling, rest of season with value over replacement, start/sit (a head-to-head
 * chance from the projection bands), buy-low / sell-high (points v expected points from usage), streaming D/ST and
 * kickers, schedule strength, and the walk-forward backtest.
 *
 * Address: #/fantasy?f=ppr|half|std&tab=<tab>&pos=<POS>. Data: data/<S>/fantasy.json, data/fantasy_backtest.json.
 * Uses GI.fk. */
(function (GI) {
'use strict';

const K = () => GI.fk;
const FMTS = [['ppr', 'PPR'], ['half', 'Half PPR'], ['std', 'Standard']];
const TABS = [['picks', 'Our picks'], ['week', 'This week'], ['ros', 'Rest of season'], ['startsit', 'Start / sit'], ['luck', 'Buy & sell'],
  ['stream', 'Streaming'], ['sched', 'Schedule'], ['bt', 'Backtest']];
const POS = ['QB', 'RB', 'WR', 'TE'];
const ST = { f: 'ppr', tab: 'picks', pos: 'ALL', q: '', cmp: [] };
let D = null, BT = null, S = null, ROWS = [], BY = {};

function rowsOf(d) {
  return (d.rows || []).map(r => { const o = {}; d.cols.forEach((c, i) => { o[c] = r[i]; }); return o; });
}
function fmtKey(base) { return ST.f === 'ppr' ? base : (base === 'ppr' ? ST.f : base.replace('ppr', ST.f)); }
function proj(r) { return r[ST.f]; }
function ros(r) { return r['ros_' + ST.f]; }
function scaleBand(r, v) {
  const k = K();
  if (!k.isNum(v) || !k.isNum(r.ppr) || r.ppr <= 0) return v;
  return v * (r[ST.f] / r.ppr);
}
/* Tiers: a new tier where the drop to the next player is at least 1.5 x the median drop among the top n. */
function tiers(vals, n) {
  const out = [], gaps = [];
  for (let i = 1; i < Math.min(vals.length, n); i++) gaps.push(vals[i - 1] - vals[i]);
  const s = gaps.slice().sort((a, b) => a - b);
  const med = s.length ? s[Math.floor(s.length / 2)] : 0;
  const cut = Math.max(0.4, 1.5 * med);
  let t = 1;
  vals.forEach((v, i) => { if (i > 0 && vals[i - 1] - v >= cut) t++; out.push(t); });
  return out;
}
function injTag(r) {
  const k = K();
  if (r.status === 'RES') return ' <span class="gq-tag gf-inj">IR</span>';
  if (r.inj) return ' <span class="gq-tag gf-inj" title="Injury report">' + k.esc(r.inj === 'Questionable' ? 'Q' : r.inj === 'Doubtful' ? 'D' : r.inj) + '</span>';
  return '';
}
function oppCell(r) {
  const k = K();
  if (!r.opp) return '<span class="muted-inline">bye</span>';
  const f = r.opp_f;
  const cls = k.isNum(f) ? (f >= 1.08 ? 'gf-good' : f <= 0.92 ? 'gf-bad' : '') : '';
  return (r.home === false ? '@' : '') + k.esc(r.opp) + (k.isNum(f) ? ' <span class="gf-mf ' + cls + '" title="Fantasy points the defence allows to the position v average">' + (f >= 1 ? '+' : '') + Math.round((f - 1) * 100) + '%</span>' : '');
}
function line(r) {
  const k = K();
  const p = [];
  if (r.pos === 'QB') p.push(k.num(r.pass_yds, 0) + ' pass yds', k.num(r.pass_td, 1) + ' pass TD');
  if (k.isNum(r.car) && r.car >= 1) p.push(k.num(r.car, 1) + ' car', k.num(r.rush_yds, 0) + ' rush yds');
  if (r.pos !== 'QB' && k.isNum(r.tgt)) p.push(k.num(r.tgt, 1) + ' tgt', k.num(r.rec, 1) + ' rec', k.num(r.rec_yds, 0) + ' rec yds');
  const td = (r.rec_td || 0) + (r.rush_td || 0);
  if (r.pos !== 'QB' || td > 0.05) p.push(k.num(td, 2) + ' TD');
  return p.join(' · ');
}
function nm(r) { return K().playerLink(r.pid, r.name, S) + ' ' + K().teamChip(r.team, S) + injTag(r); }

function render(el, params, state) {
  const k = K();
  const qy = params.query || {};
  if (qy.f && FMTS.some(x => x[0] === qy.f)) ST.f = qy.f;
  if (qy.tab && TABS.some(x => x[0] === qy.tab)) ST.tab = qy.tab;
  if (qy.pos) ST.pos = String(qy.pos).toUpperCase();
  el.innerHTML = k.muted('Loading…');
  return k.ready().then(() => {
    S = k.curSeason ? k.curSeason() : k.S(params, state);
    return Promise.all([k.loadY(S, 'fantasy.json'), GI.load('fantasy_backtest.json'), k.loadNames()]);
  }).then(res => {
    if (!k.alive(el)) return;
    D = res[0]; BT = res[1];
    if (!k.ok(D) || !D.rows) {
      el.innerHTML = k.head('Fantasy', String(S)) + k.card('Fantasy', '', '<div class="gq-pad">' + k.notBuilt('The fantasy projections', D) + '</div>') +
        (k.ok(BT) ? '<div id="gf-body"></div>' : '');
      if (k.ok(BT)) { ST.tab = 'bt'; k.set('gf-body', backtest()); }
      return;
    }
    ROWS = rowsOf(D); BY = {};
    ROWS.forEach(r => { BY[r.pid] = r; });
    let h = k.head('Fantasy', 'Week ' + D.week + ' · ' + S + ' · projections from our usage model and game model',
      '<a href="#/value">Player value →</a><a href="#/methodology/fantasy">How it works →</a>');
    h += '<div class="card"><div class="gq-pad gf-intro"><div class="gf-ctl">' + k.toggle('gf-fmt', FMTS, ST.f) + '</div>' +
      '<div class="gf-tabs">' + k.toggle('gf-tab', TABS, ST.tab) + '</div>' +
      '<p class="muted-inline">' + k.esc((D.notes || {}).waiver || '') + ' ' + k.esc((D.notes || {}).left_out || '') + '</p></div></div>';
    h += '<div id="gf-body"></div>';
    el.innerHTML = h;
    k.setMeta('Fantasy · week ' + D.week + ' · ' + S);
    k.wireToggle(el, 'gf-fmt', v => { ST.f = v; draw(); });
    k.wireToggle(el, 'gf-tab', v => { ST.tab = v; draw(); });
    draw();
  });
}

function sync() {
  const q = ['f=' + ST.f, 'tab=' + ST.tab];
  if (ST.pos && ST.pos !== 'ALL') q.push('pos=' + ST.pos);
  try { history.replaceState(null, '', '#/fantasy?' + q.join('&')); } catch (e) { /* ok */ }
}

function draw() {
  const k = K();
  sync();
  const f = { picks: picks, week: week, ros: rest, startsit: startSit, luck: luck, stream: stream, sched: sched, bt: backtest }[ST.tab] || picks;
  k.set('gf-body', f());
  const body = k.$('gf-body');
  if (!body) return;
  body.querySelectorAll('.table-wrap').forEach(t => k.sortable(t));
  k.wireToggle(body, 'gf-pos', v => { ST.pos = v; draw(); });
  const q = k.$('gf-q');
  if (q) { q.value = ST.q; q.oninput = e => { ST.q = e.target.value; const p = q.selectionStart; draw(); const n = k.$('gf-q'); if (n) { n.focus(); try { n.setSelectionRange(p, p); } catch (er) { /* ok */ } } }; }
  if (ST.tab === 'startsit') wireStartSit();
}

function posToggle(extra) {
  const k = K();
  const opts = [['ALL', 'All']].concat(POS.map(p => [p, p])).concat(extra || []);
  return '<div class="gf-pos">' + k.toggle('gf-pos', opts, ST.pos) + ' <label class="gf-find">Find <input id="gf-q" type="search" placeholder="name" autocomplete="off"></label></div>';
}
function filtered() {
  const k = K();
  const q = k.fold(ST.q.trim());
  return ROWS.filter(r => (ST.pos === 'ALL' || r.pos === ST.pos) && (!q || k.fold(r.name).indexOf(q) >= 0));
}

/* ── Our picks ─────────────────────────────────────────────────────────── */
function picks() {
  const k = K();
  const P = D.picks || {};
  const box = (title, sub, list, fn) => '<div class="card gf-pick"><div class="card-header">' + k.esc(title) + ' <span class="card-sub">' + sub + '</span></div><div class="gq-pad">' +
    (list && list.length ? list.map(fn).join('') : k.muted('None this week.')) + '</div></div>';
  const ply = z => {
    const r = BY[z.pid] || {};
    return '<div class="gf-pk"><div class="gf-pk-h">' + nm(r) + ' <span class="gq-tag">' + k.esc(z.pos) + '</span>' +
      (k.isNum(r[ST.f]) ? ' <span class="gf-pk-v">' + k.num(r[ST.f], 1) + ' this week · ' + k.num(ros(r), 0) + ' rest of season</span>' : '') + '</div>' +
      '<div class="gf-pk-w">' + k.esc(z.why) + '</div></div>';
  };
  const tm = z => '<div class="gf-pk"><div class="gf-pk-h">' + k.teamChip(z.team, S) + ' v ' + k.esc(z.opp || '') + ' <span class="gf-pk-v">' + k.num(z.proj, 1) + '</span></div><div class="gf-pk-w">' + k.esc(z.why) + '</div></div>';
  return '<div class="gf-picks">' +
    box('Start', 'projected well above where his season so far ranks him (PPR)', P.start, ply) +
    box('Waiver targets', 'likely available (outside the top scorers at the position); rest-of-season points a game, rising usage', P.waiver, ply) +
    box('Buy low', 'usage worth more points than he has scored', P.buy_low, ply) +
    box('Sell high', 'scoring on touchdowns his usage does not support', P.sell_high, ply) +
    box('Breakouts', 'usage up over the last three games', P.breakout, ply) +
    box('Stream a D/ST', 'this week, with the next four', P.dst, tm) +
    box('Stream a kicker', 'this week, with the next four', P.k, tm) + '</div>' +
    '<div class="pg-note gq-note">Picks are computed in PPR from the same projections as the tables; the reasons are the model\'s inputs, not news. Model suggestions only.</div>';
}

/* ── This week ─────────────────────────────────────────────────────────── */
function week() {
  const k = K();
  if (ST.pos === 'K' || ST.pos === 'DST') return posToggle([['K', 'K'], ['DST', 'D/ST']]) + teamTable(ST.pos === 'K' ? D.k : D.dst, ST.pos, true);
  let list = filtered().filter(r => r.opp && k.isNum(proj(r)));
  list.sort((a, b) => proj(b) - proj(a));
  list = list.slice(0, ST.pos === 'ALL' ? 200 : 120);
  const byPos = {};
  const tierOf = {};
  POS.forEach(p => {
    const xs = list.filter(r => r.pos === p);
    const ts = tiers(xs.map(proj), 60);
    xs.forEach((r, i) => { tierOf[r.pid] = ts[i]; byPos[r.pid] = i + 1; });
  });
  const rows = list.map((r, i) => ({ cells: [{ v: i + 1, cls: 'pos-cell' }, { v: r.name, html: nm(r) }, { v: r.pos, html: k.esc(r.pos) + byPos[r.pid] },
    { v: tierOf[r.pid], html: '<span class="gf-tier gf-t' + Math.min(tierOf[r.pid], 8) + '">' + tierOf[r.pid] + '</span>' }, { v: r.opp, html: oppCell(r) },
    { v: r.imp, html: k.num(r.imp, 1) }, { v: proj(r), html: '<strong>' + k.num(proj(r), 1) + '</strong>' },
    { v: r.floor, html: k.num(scaleBand(r, r.floor), 1) + '–' + k.num(scaleBand(r, r.ceil), 1) }, { v: '', html: '<span class="gf-line">' + k.esc(line(r)) + '</span>' }] }));
  return posToggle([['K', 'K'], ['DST', 'D/ST']]) + k.card('Week ' + D.week + ' projections', FMTS.find(x => x[0] === ST.f)[1] + ' · tiers break where the drop to the next player is unusually large', k.table(
    [{ label: '#', sortable: false }, { label: 'Player' }, { label: 'Pos' }, { label: 'Tier', align: 'right' }, { label: 'Opp' }, { label: 'Team total', align: 'right', title: 'Implied points from our game model' },
      { label: 'Proj', align: 'right' }, { label: '10th–90th', align: 'right' }, { label: 'Projected line', sortable: false }], rows, { compact: true, sticky: true })) +
    '<div class="pg-note gq-note">Projections allow for this week\'s injury report: out players are at zero, doubtful and questionable ones at the rate such players have played (' +
    k.num(100 * ((D.params || {}).P_D || 0), 0) + '% and ' + k.num(100 * ((D.params || {}).P_Q || 0), 0) + '%), and their targets and carries are shared among team-mates. Matchup: points the opponent allows to the position against average (recency-weighted, shrunk). Band: 10th to 90th percentile.</div>';
}

function teamTable(tab, what, weekOnly) {
  const k = K();
  const list = Object.keys(tab || {}).map(t => Object.assign({ team: t }, tab[t])).filter(x => !weekOnly || k.isNum(x.next));
  list.sort((a, b) => (weekOnly ? (b.next - a.next) : (b.ros - a.ros)));
  return k.card(what === 'K' ? 'Kickers' : 'Defence / special teams', 'by team · the next four weeks and the rest of the season', k.table(
    [{ label: '#', sortable: false }, { label: 'Team' }, { label: 'This week', align: 'right' }, { label: 'Next four', sortable: false }, { label: 'Rest of season', align: 'right' }],
    list.map((x, i) => ({ cells: [{ v: i + 1, cls: 'pos-cell' }, { v: x.team, html: k.teamChip(x.team, S) }, { v: x.next, html: '<strong>' + k.num(x.next, 1) + '</strong>' },
      { v: '', html: (x.weeks || []).map(w => '<span class="gf-wk" title="Week ' + w[0] + '">' + k.esc(w[1]) + ' ' + k.num(w[2], 1) + '</span>').join(' ') },
      { v: x.ros, html: k.num(x.ros, 0) }] })), { compact: true }));
}

/* ── Rest of season ─────────────────────────────────────────────────────── */
function repl(pos) {
  const n = { QB: 12, RB: 30, WR: 42, TE: 12 }[pos] || 24;
  const xs = ROWS.filter(r => r.pos === pos).map(ros).filter(v => v !== null && v !== undefined).sort((a, b) => b - a);
  return xs.length > n ? xs[n] : (xs.length ? xs[xs.length - 1] : 0);
}
function rest() {
  const k = K();
  const R = {};
  POS.forEach(p => { R[p] = repl(p); });
  let list = filtered().filter(r => k.isNum(ros(r)));
  list.forEach(r => { r._vor = ros(r) - R[r.pos]; });
  list.sort((a, b) => (ST.pos === 'ALL' ? b._vor - a._vor : ros(b) - ros(a)));
  list = list.slice(0, 200);
  const ts = tiers(list.map(r => (ST.pos === 'ALL' ? r._vor : ros(r))), 80);
  const rows = list.map((r, i) => ({ cells: [{ v: i + 1, cls: 'pos-cell' }, { v: r.name, html: nm(r) }, { v: r.pos, html: k.esc(r.pos) },
    { v: ts[i], html: '<span class="gf-tier gf-t' + Math.min(ts[i], 8) + '">' + ts[i] + '</span>' }, { v: ros(r), html: '<strong>' + k.num(ros(r), 0) + '</strong>' },
    { v: r.ros_g, html: k.num(r.ros_g, 1) }, { v: r._vor, html: k.signed(r._vor, 0) }, { v: r.pts_ppr, html: k.num(r['pts_' + ST.f], 0) + (r.g ? ' <span class="muted-inline">(' + r.g + ' g)</span>' : '') },
    { v: r.sos, html: sosCell(r.sos) }, { v: '', html: (r.next4 || []).map(w => '<span class="gf-wk" title="Week ' + w[0] + ' (PPR)">' + k.esc(w[1]) + ' ' + k.num(w[2], 1) + '</span>').join(' ') }] }));
  return posToggle() + k.card('Rest of season', FMTS.find(x => x[0] === ST.f)[1] + ' · value over replacement = points above the 13th QB, 31st RB, 43rd WR and 13th TE (a 12-team league)', k.table(
    [{ label: '#', sortable: false }, { label: 'Player' }, { label: 'Pos' }, { label: 'Tier', align: 'right' }, { label: 'Points', align: 'right' }, { label: 'Games', align: 'right', title: 'Expected games, availability-weighted' },
      { label: 'Over repl.', align: 'right' }, { label: 'So far', align: 'right' }, { label: 'Schedule', align: 'right', title: 'Average matchup factor of the remaining games' }, { label: 'Next four (PPR)', sortable: false }],
    rows, { compact: true, sticky: true }));
}
function sosCell(v) {
  const k = K();
  if (!k.isNum(v)) return '—';
  const cls = v >= 1.04 ? 'gf-good' : v <= 0.96 ? 'gf-bad' : '';
  return '<span class="' + cls + '">' + (v >= 1 ? '+' : '') + Math.round((v - 1) * 100) + '%</span>';
}

/* ── Start / sit ─────────────────────────────────────────────────────────── */
function sdOf(r) {
  const k = K();
  const fl = scaleBand(r, r.floor), ce = scaleBand(r, r.ceil);
  return k.isNum(fl) && k.isNum(ce) ? Math.max(1.0, (ce - fl) / 2.563) : 6;
}
function phi(z) { const t = 1 / (1 + 0.2316419 * Math.abs(z)); const d = 0.3989423 * Math.exp(-z * z / 2); const p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274)))); return z > 0 ? 1 - p : p; }
function startSit() {
  const k = K();
  const opts = ROWS.filter(r => r.opp && k.isNum(proj(r)) && proj(r) > 1).sort((a, b) => proj(b) - proj(a));
  const sel = (i) => '<select id="gf-cmp' + i + '"><option value="">Pick a player…</option>' + opts.map(r => '<option value="' + k.esc(r.pid) + '"' + (ST.cmp[i] === r.pid ? ' selected' : '') + '>' +
    k.esc(r.name + ' (' + r.pos + ', ' + r.team + ' v ' + r.opp + ')') + '</option>').join('') + '</select>';
  let h = k.card('Who should I start?', 'pick two to four players · chance each outscores the others, from the projection bands', '<div class="gq-pad"><div class="gf-cmp">' +
    [0, 1, 2, 3].map(sel).join('') + '</div><div id="gf-cmp-out"></div></div>');
  const n = D.start_n || { QB: 12, RB: 24, WR: 36, TE: 12 };
  const blocks = POS.map(p => {
    const xs = ROWS.filter(r => r.pos === p && r.opp && k.isNum(proj(r))).sort((a, b) => proj(b) - proj(a)).slice(0, Math.round(n[p] * 1.75));
    return '<div class="gq-mini gf-ss"><div class="gq-mini-h">' + p + ' <span class="muted-inline">start top ' + n[p] + '</span></div>' + xs.map((r, i) => {
      const lab = i < n[p] ? ['Start', 'gf-good'] : (i < n[p] * 1.5 && p !== 'QB' ? ['Flex', ''] : ['Sit', 'gf-bad']);
      return '<div class="gq-mini-r gf-ss-r"><span class="gq-mini-n">' + (i + 1) + '</span><span class="gv-nm">' + nm(r) + '</span><span class="gq-mini-v">' + k.num(proj(r), 1) +
        ' <span class="gf-lab ' + lab[1] + '">' + lab[0] + '</span></span></div>';
    }).join('') + '</div>';
  });
  h += k.card('Start / flex / sit by position', 'this week · a 12-team league with one flex', '<div class="gq-glance gf-ss-grid">' + blocks.join('') + '</div>');
  return h;
}
function wireStartSit() {
  const k = K();
  [0, 1, 2, 3].forEach(i => { const s = k.$('gf-cmp' + i); if (s) s.onchange = e => { ST.cmp[i] = e.target.value; cmpOut(); }; });
  cmpOut();
}
function cmpOut() {
  const k = K();
  const xs = ST.cmp.filter(Boolean).map(p => BY[p]).filter(Boolean);
  if (xs.length < 2) { k.set('gf-cmp-out', k.muted('Pick at least two players.')); return; }
  // chance each is the top scorer: 4,000 draws from normals with the projection and band
  const n = 4000, wins = xs.map(() => 0);
  let seed = 12345;
  const rnd = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; };
  const gauss = () => { const u = Math.max(rnd(), 1e-9), v = rnd(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); };
  for (let j = 0; j < n; j++) {
    let best = -1e9, bi = 0;
    xs.forEach((r, i) => { const v = Math.max(0, proj(r) + sdOf(r) * gauss()); if (v > best) { best = v; bi = i; } });
    wins[bi]++;
  }
  const order = xs.map((r, i) => ({ r: r, p: wins[i] / n })).sort((a, b) => b.p - a.p);
  const pair = xs.length === 2 ? phi((proj(xs[0]) - proj(xs[1])) / Math.sqrt(sdOf(xs[0]) * sdOf(xs[0]) + sdOf(xs[1]) * sdOf(xs[1]))) : null;
  k.set('gf-cmp-out', '<div class="gf-cmp-res">' + order.map((o, i) => '<div class="gf-cmp-row"><span>' + (i === 0 ? '<strong>Start</strong> ' : '') + nm(o.r) + ' ' + oppCell(o.r) + '</span><span>' +
    k.num(proj(o.r), 1) + ' (' + k.num(scaleBand(o.r, o.r.floor), 1) + '–' + k.num(scaleBand(o.r, o.r.ceil), 1) + ') · <strong>' + Math.round(100 * o.p) + '%</strong> to score most</span></div>').join('') +
    (pair !== null ? '<div class="muted-inline">Normal approximation: ' + k.esc(xs[0].name) + ' outscores ' + k.esc(xs[1].name) + ' ' + Math.round(100 * pair) + '% of the time.</div>' : '') + '</div>');
}

/* ── Buy & sell ─────────────────────────────────────────────────────────── */
function luck() {
  const k = K();
  const list = filtered().filter(r => r.pos !== 'QB' && r.g >= 2 && k.isNum(r.xfp)).map(r => Object.assign(r, { _d: (r.pts_ppr - r.xfp) / r.g }));
  list.sort((a, b) => a._d - b._d);
  const rows = list.slice(0, 250).map(r => ({ cells: [{ v: r.name, html: nm(r) }, { v: r.pos, html: k.esc(r.pos) }, { v: r.g, html: k.int(r.g) },
    { v: r.pts_ppr / r.g, html: k.num(r.pts_ppr / r.g, 1) }, { v: r.xfp / r.g, html: k.num(r.xfp / r.g, 1) }, { v: r._d, html: '<strong class="' + (r._d <= -2 ? 'gf-good' : r._d >= 2 ? 'gf-bad' : '') + '">' + k.signed(r._d, 1) + '</strong>' },
    { v: r.td - r.xtd, html: k.int(r.td) + ' / ' + k.num(r.xtd, 1) }, { v: r.rec_yds_s - r.xrec_yds_s, html: k.signed(r.rec_yds_s - r.xrec_yds_s, 0) },
    { v: r.rush_yds_s - r.xrush_yds_s, html: k.signed(r.rush_yds_s - r.xrush_yds_s, 0) }, { v: r.tgt_sh, html: k.num(100 * (r.tgt_sh || 0), 0) + '% → ' + k.num(100 * (r.tgt_sh3 || 0), 0) + '%' }] }));
  return posToggle() + k.card('Points v expected points', 'buy low near the top (usage worth more than he has scored), sell high near the bottom · PPR, this season', k.table(
    [{ label: 'Player' }, { label: 'Pos' }, { label: 'G', align: 'right' }, { label: 'PPR/g', align: 'right' }, { label: 'Expected/g', align: 'right', title: 'Expected PPR points from his targets and carries (where they were thrown and from where he ran)' },
      { label: 'Over exp./g', align: 'right' }, { label: 'TD / exp.', align: 'right' }, { label: 'Rec yds v exp.', align: 'right' }, { label: 'Rush yds v exp.', align: 'right' },
      { label: 'Target share (last 3)', align: 'right' }], rows, { compact: true, sticky: true })) +
    '<div class="pg-note gq-note">Expected points value every target by its yard line and air yards, and every carry by its yard line, at what such plays produced league-wide over the three previous seasons. A player far above expectation (especially on touchdowns) tends to come back to it; far below, the reverse.</div>';
}

/* ── Streaming ─────────────────────────────────────────────────────────── */
function stream() { return teamTable(D.dst, 'DST', true) + teamTable(D.k, 'K', true); }

/* ── Schedule ─────────────────────────────────────────────────────────── */
function sched() {
  const k = K();
  const teams = Object.keys(D.sos || {}).sort();
  const rows = teams.map(t => ({ cells: [{ v: t, html: k.teamChip(t, S) }].concat(POS.map(p => { const v = ((D.sos[t] || {})[p] || [])[0]; return { v: v, html: sosCell(v) }; }))
    .concat(POS.map(p => { const v = ((D.sos[t] || {})[p] || [])[1]; return { v: v, html: sosCell(v) }; })) }));
  return k.card('Schedule strength', 'how much more (+) or less (−) the remaining opponents allow to each position than average; rest of season, then the next four weeks', k.table(
    [{ label: 'Team' }].concat(POS.map(p => ({ label: p + ' ROS', align: 'right' }))).concat(POS.map(p => ({ label: p + ' next 4', align: 'right' }))), rows, { compact: true, sticky: true }));
}

/* ── Backtest ─────────────────────────────────────────────────────────── */
function backtest() {
  const k = K();
  if (!k.ok(BT) || !BT.backtest) return k.card('Backtest', '', '<div class="gq-pad">' + k.notBuilt('The backtest', BT) + '</div>');
  const b = BT.backtest;
  const fm = (b.formats || {})[ST.f] || {};
  const cell = (x, best) => '<span' + (best ? ' class="gf-good"' : '') + '>' + k.num(x, 2) + '</span>';
  const rows = ['QB', 'RB', 'WR', 'TE', 'ALL'].filter(p => fm[p]).map(p => {
    const r = fm[p];
    const m = [r.model.mae, r.season_to_date.mae, r.last_season.mae];
    const lo = Math.min.apply(null, m.filter(k.isNum));
    const rh = [r.model.rho, r.season_to_date.rho, r.last_season.rho];
    const hi = Math.max.apply(null, rh.filter(k.isNum).concat([-1]));
    return { cells: [{ v: p, html: '<strong>' + p + '</strong>' }, { v: r.n, html: k.int(r.n) }].concat(m.map(x => ({ v: x, html: cell(x, x === lo) })))
      .concat(rh.map(x => ({ v: x, html: k.isNum(x) ? cell(x, x === hi) : '—' })))
      .concat([{ v: r.model.mae_played, html: k.num(r.model.mae_played, 2) + ' / ' + k.num(r.season_to_date.mae_played, 2) }]) };
  });
  let h = k.card('Walk-forward backtest, ' + (b.seasons || [])[0] + '–' + (b.seasons || []).slice(-1)[0], FMTS.find(x => x[0] === ST.f)[1] + ' · every week projected from the games before it; tuned on ' + (BT.tune_seasons || []).join(', ') + ' only',
    k.table([{ label: 'Pos' }, { label: 'Player-weeks', align: 'right' }, { label: 'MAE model', align: 'right' }, { label: 'MAE season-to-date', align: 'right' }, { label: 'MAE last season', align: 'right' },
      { label: 'ρ model', align: 'right', title: 'Mean weekly Spearman rank correlation' }, { label: 'ρ season-to-date', align: 'right' }, { label: 'ρ last season', align: 'right' },
      { label: 'MAE when played (model / s-t-d)', align: 'right' }], rows, { compact: true }) +
    '<div class="pg-note gq-note">Pool: players who were fantasy-relevant going in (top 32 QB, 64 RB, 96 WR, 32 TE by points per game so far or last season). Actual = 0 when a player did not play, which is where the injury report earns its keep; the last column restricts to players who played. Lower MAE and higher ρ are better; the best in each row is green.</div>');
  const kd = [['Kickers', b.k], ['D/ST', b.dst]].filter(x => x[1] && x[1].model).map(x => ({ cells: [{ v: x[0], html: x[0] }, { v: x[1].n, html: k.int(x[1].n) },
    { v: x[1].model.mae, html: k.num(x[1].model.mae, 2) }, { v: x[1].season_to_date.mae, html: k.num(x[1].season_to_date.mae, 2) }, { v: x[1].last_season.mae, html: k.num(x[1].last_season.mae, 2) },
    { v: x[1].model.rho, html: k.num(x[1].model.rho, 3) }, { v: x[1].season_to_date.rho, html: k.num(x[1].season_to_date.rho, 3) }] }));
  if (kd.length) h += k.card('Kickers and D/ST', 'team-weeks, the same walk-forward', k.table([{ label: '' }, { label: 'Team-weeks', align: 'right' }, { label: 'MAE model', align: 'right' },
    { label: 'MAE season-to-date', align: 'right' }, { label: 'MAE last season', align: 'right' }, { label: 'ρ model', align: 'right' }, { label: 'ρ season-to-date', align: 'right' }], kd, { compact: true }));
  const bs = b.by_season || {};
  const srows = Object.keys(bs).sort().map(s => ({ cells: [{ v: s, html: s }].concat(['QB', 'RB', 'WR', 'TE'].map(p => {
    const x = bs[s][p] || {};
    return { v: x.model, html: k.num(x.model, 2) + ' <span class="muted-inline">v ' + k.num(x.season_to_date, 2) + '</span>' };
  })) }));
  if (srows.length) h += k.card('By season (PPR MAE: model v season-to-date)', '', k.table([{ label: 'Season' }, { label: 'QB' }, { label: 'RB' }, { label: 'WR' }, { label: 'TE' }], srows, { compact: true }));
  const cur = BT.current;
  if (cur && cur.ppr) {
    const r = cur.ppr;
    h += k.card('This season so far (' + cur.season + ', weeks ' + (cur.weeks || []).join(', ') + ')', 'PPR, the same walk-forward', k.table([{ label: 'Pos' }, { label: 'n', align: 'right' }, { label: 'MAE model', align: 'right' }, { label: 'MAE season-to-date', align: 'right' }, { label: 'ρ model', align: 'right' }, { label: 'ρ season-to-date', align: 'right' }],
      ['QB', 'RB', 'WR', 'TE', 'ALL'].filter(p => r[p]).map(p => ({ cells: [p, { v: r[p].n, html: k.int(r[p].n) }, { v: r[p].model.mae, html: k.num(r[p].model.mae, 2) }, { v: r[p].season_to_date.mae, html: k.num(r[p].season_to_date.mae, 2) },
        { v: r[p].model.rho, html: k.num(r[p].model.rho, 3) }, { v: r[p].season_to_date.rho, html: k.num(r[p].season_to_date.rho, 3) }] })), { compact: true }));
  }
  return h;
}

if (typeof GI.route === 'function') { try { GI.route('fantasy', render); } catch (e) { /* bound */ } }
})(window.GI || (window.GI = {}));
