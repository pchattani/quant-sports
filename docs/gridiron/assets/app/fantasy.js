/* The Quant Gridiron — Fantasy (#/fantasy?f=ppr|half|std&tab=&pos=), on Design System 2.0 (stat tiles, leaderboards with
 * team marks and inline bars, chance bars for start/sit).
 * PPR / half-PPR / standard projections from our play-level usage model and the game model's implied totals:
 * our picks (with reasons), this week (tiers, floor and ceiling, a range chart), rest of season (value over
 * replacement), start/sit (a head-to-head chance from the bands), buy & sell (points v expected points, as a
 * scatter), streaming D/ST and kickers, schedule strength, and the walk-forward backtest.
 * Reads <S>/fantasy.json and fantasy_backtest.json. */
(function (GI) {
'use strict';

const QK = window.QK;
const esc = GI.esc, isNum = GI.isNum;
const MARK = t => ({ name: GI.teamName(t), abbr: GI.teamAbbr(t), colour: GI.teamInfo(t).colour });
const ENT = (label) => ({ key: 'name', label: label || 'Player', type: 'entity', sub: 'sub', mark: r => MARK(r.team), href: r => GI.playerHref(r.pid) });
function lb(id, spec) { const n = document.getElementById(id); if (n) QK.leaderboard(n, Object.assign({ dense: true }, spec)); }
const subOf = r => [r.pos, GI.teamAbbr(r.team), r.status === 'RES' ? 'IR' : (r.inj || '')].filter(Boolean).join(' · ');
const FMTS = [['ppr', 'PPR'], ['half', 'Half PPR'], ['std', 'Standard']];
const TABS = [['picks', 'Our picks'], ['week', 'This week'], ['ros', 'Rest of season'], ['startsit', 'Start / sit'], ['luck', 'Buy & sell'], ['stream', 'Streaming'], ['sched', 'Schedule'], ['bt', 'Backtest']];
const POS = ['QB', 'RB', 'WR', 'TE'];
const TIERC = ['#2fb37b', '#7ee787', '#e3b341', '#e8833a', '#c95ac9', '#3987e5', '#46b9c9', '#7d8590'];
const ST = { f: 'ppr', tab: 'picks', pos: 'ALL', q: '', cmp: [] };
let D = null, BT = null, S = null, ROWS = [], BY = {};

const proj = r => r[ST.f];
const ros = r => r['ros_' + ST.f];
function scaleBand(r, v) { return !isNum(v) || !isNum(r.ppr) || r.ppr <= 0 ? v : v * (r[ST.f] / r.ppr); }
function tiers(vals, n) {
  const out = [], gaps = [];
  for (let i = 1; i < Math.min(vals.length, n); i++) gaps.push(vals[i - 1] - vals[i]);
  const s = gaps.slice().sort((a, b) => a - b);
  const cut = Math.max(0.4, 1.5 * (s.length ? s[Math.floor(s.length / 2)] : 0));
  let t = 1;
  vals.forEach((v, i) => { if (i > 0 && vals[i - 1] - v >= cut) t++; out.push(t); });
  return out;
}
const tierChip = t => '<span class="gi-tier" style="--tierc:' + TIERC[Math.min(t, 8) - 1] + '">' + t + '</span>';
function injTag(r) {
  if (r.status === 'RES') return ' <span class="qk-badge live">IR</span>';
  if (r.inj) return ' <span class="qk-badge" title="Injury report">' + esc(r.inj === 'Questionable' ? 'Q' : r.inj === 'Doubtful' ? 'D' : r.inj) + '</span>';
  return '';
}
function oppCell(r) {
  if (!r.opp) return '<span class="qk-muted">bye</span>';
  const f = r.opp_f;
  return (r.home === false ? '@' : '') + esc(r.opp) + (isNum(f) ? ' <span class="' + (f >= 1.08 ? 'gi-up' : f <= 0.92 ? 'gi-down' : 'qk-muted') + '" title="Fantasy points the defence allows to the position v average">' + (f >= 1 ? '+' : '') + Math.round((f - 1) * 100) + '%</span>' : '');
}
function line(r) {
  const p = [];
  if (r.pos === 'QB') p.push(GI.num(r.pass_yds, 0) + ' pass yds', GI.num(r.pass_td, 1) + ' pass TD');
  if (isNum(r.car) && r.car >= 1) p.push(GI.num(r.car, 1) + ' car', GI.num(r.rush_yds, 0) + ' rush yds');
  if (r.pos !== 'QB' && isNum(r.tgt)) p.push(GI.num(r.tgt, 1) + ' tgt', GI.num(r.rec, 1) + ' rec', GI.num(r.rec_yds, 0) + ' rec yds');
  const td = (r.rec_td || 0) + (r.rush_td || 0);
  if (r.pos !== 'QB' || td > 0.05) p.push(GI.num(td, 2) + ' TD');
  return p.join(' · ');
}
const nm = r => GI.playerLink(r.pid, r.name) + ' ' + GI.teamChip(r.team) + injTag(r);
function posBar(extra) {
  return '<div class="gi-toolbar" style="margin-bottom:12px">' + GI.seg('gf-pos', [['ALL', 'All']].concat(POS.map(p => [p, p])).concat(extra || []), ST.pos, 'Position') + GI.field('Find', '<input id="gf-q" class="qk-input" type="search" placeholder="Name">') + '</div>';
}
function filtered() { const q = GI.fold(ST.q.trim()); return ROWS.filter(r => (ST.pos === 'ALL' || r.pos === ST.pos) && (!q || GI.fold(r.name).indexOf(q) >= 0)); }

function picks() {
  const P = D.picks || {};
  const box = (title, sub, list, fn) => GI.card(esc(title), sub.charAt(0).toUpperCase() + sub.slice(1), list && list.length ? '<ol class="gi-pick-l">' + list.map(fn).join('') + '</ol>' : GI.muted('None this week.'), { span: 4 });
  const ply = z => { const r = BY[z.pid] || {}; return '<li><div class="gi-pick-top"><span>' + nm(r) + ' <span class="gi-tag">' + esc(z.pos) + '</span></span>' + (isNum(r[ST.f]) ? '<span class="gi-num">' + GI.num(r[ST.f], 1) + ' · ROS ' + GI.num(ros(r), 0) + '</span>' : '') + '</div><p class="gi-why">' + esc(z.why) + '</p></li>'; };
  const tm = z => '<li><div class="gi-pick-top"><span>' + GI.teamChip(z.team) + ' v ' + esc(z.opp || '') + '</span><span class="gi-num">' + GI.num(z.proj, 1) + '</span></div><p class="gi-why">' + esc(z.why) + '</p></li>';
  return GI.grid(box('Start', 'projected well above season rank (PPR)', P.start, ply) + box('Waiver targets', 'likely available; rising usage', P.waiver, ply) + box('Buy low', 'usage worth more points than scored so far', P.buy_low, ply) +
    box('Sell high', 'scoring on touchdowns the usage does not support', P.sell_high, ply) + box('Breakouts', 'usage up over the last three games', P.breakout, ply) +
    box('Stream a D/ST', 'this week, with the next four', P.dst, tm) + box('Stream a kicker', 'this week, with the next four', P.k, tm)) +
    '<p class="gi-cap">Picks are computed in PPR from the same projections as the tables; the reasons are the model\'s inputs, not news. Model suggestions only.</p>';
}
function teamTable(tab, what) {
  const list = Object.keys(tab || {}).map(t => Object.assign({ team: t }, tab[t])).filter(x => isNum(x.next)).sort((a, b) => b.next - a.next);
  const id = 'gf-tt-' + what;
  return { html: GI.card(what === 'K' ? 'Kickers' : 'Defence / special teams', 'By team · this week, the next four and the rest of the season', '<div id="' + id + '"></div>', { flush: true }),
    after: () => lb(id, { rank: true, maxHeight: 640, rowHref: r => GI.teamHref(r.team), rows: list.map(x => Object.assign({ name: GI.teamShort(x.team), sub: x.team }, x)),
      columns: [{ key: 'name', label: 'Team', type: 'entity', sub: 'sub', mark: r => MARK(r.team), href: r => GI.teamHref(r.team) }, { key: 'next', label: 'This week', type: 'bar', fmt: v => '<b>' + GI.num(v, 1) + '</b>' },
        { key: 'weeks', label: 'Next four', sort: false, fmt: v => (v || []).map(w => '<span class="gi-tag" title="Week ' + w[0] + '">' + esc(w[1]) + ' ' + GI.num(w[2], 1) + '</span>').join(' ') }, { key: 'ros', label: 'Rest of season', num: true, fmt: v => GI.num(v, 0) }] }) };
}
function week() {
  if (ST.pos === 'K' || ST.pos === 'DST') { const t = teamTable(ST.pos === 'K' ? D.k : D.dst, ST.pos); return { html: posBar([['K', 'K'], ['DST', 'D/ST']]) + t.html, after: t.after }; }
  let list = filtered().filter(r => r.opp && isNum(proj(r))).sort((a, b) => proj(b) - proj(a)).slice(0, ST.pos === 'ALL' ? 200 : 120);
  const rk = {}, tierOf = {};
  POS.forEach(p => { const xs = list.filter(r => r.pos === p); const ts = tiers(xs.map(proj), 60); xs.forEach((r, i) => { tierOf[r.pid] = ts[i]; rk[r.pid] = i + 1; }); });
  const top = list.slice(0, 20);
  const fname = FMTS.find(x => x[0] === ST.f)[1];
  return { html: posBar([['K', 'K'], ['DST', 'D/ST']]) + GI.card('The top 20 this week', esc(fname) + ' · dot: our projection · bar: the 10th to 90th percentile', GI.chartBox('gf-range', 560, 'Projection ranges')) +
    GI.card('Week ' + D.week + ' projections', esc(fname) + ' · tiers break where the drop to the next player is unusually large', '<div id="gf-week"></div>', { flush: true }) +
    '<p class="gi-cap">Projections allow for this week\'s injury report: out players are at zero, doubtful and questionable ones at the rate such players have played (' + GI.num(100 * ((D.params || {}).P_D || 0), 0) + '% and ' + GI.num(100 * ((D.params || {}).P_Q || 0), 0) + '%), with their targets and carries shared among team-mates. Matchup: points the opponent allows to the position against average.</p>',
  after: () => {
    lb('gf-week', { rank: true, maxHeight: 700, rowHref: r => GI.playerHref(r.pid), sort: { key: 'p', dir: 'desc' },
      rows: list.map(r => ({ pid: r.pid, name: r.name, team: r.team, sub: r.pos + rk[r.pid] + ' · ' + GI.teamAbbr(r.team) + (r.status === 'RES' ? ' · IR' : r.inj ? ' · ' + r.inj : ''), tier: tierOf[r.pid], opp: r.opp, oppR: r, imp: r.imp, p: proj(r), lo: scaleBand(r, r.floor), hi: scaleBand(r, r.ceil), line: line(r) })),
      columns: [ENT(), { key: 'tier', label: 'Tier', num: true, fmt: v => tierChip(v) }, { key: 'opp', label: 'Opp', fmt: (v, r) => oppCell(r.oppR) }, { key: 'imp', label: 'Team total', num: true, fmt: v => GI.num(v, 1), tip: 'Implied points from our game model' },
        { key: 'p', label: 'Projection', type: 'bar', fmt: v => '<b>' + GI.num(v, 1) + '</b>' }, { key: 'lo', label: '10th–90th', num: true, fmt: (v, r) => GI.num(r.lo, 1) + '–' + GI.num(r.hi, 1) }, { key: 'line', label: 'Projected line', sort: false, fmt: v => '<span class="gi-play-desc">' + esc(v) + '</span>' }] });
    GI.ch.mount('gf-range', T => {
      const cats = top.map(r => r.name + ' · ' + r.pos);
      const ya = GI.ch.ax(T, { type: 'category', data: cats, split: false, inverse: true });
      ya.axisLabel.color = T.ink2; ya.axisLabel.width = 170; ya.axisLabel.overflow = 'truncate';
      return { grid: { left: 8, right: 20, top: 8, bottom: 26, containLabel: true }, xAxis: GI.ch.ax(T, { name: 'Fantasy points', nameLocation: 'middle', nameGap: 24 }), yAxis: ya,
        tooltip: GI.ch.tip(T, { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: ps => { const r = top[ps[0].dataIndex]; return GI.ch.thead(esc(r.name)) + GI.ch.trow(T.model, 'Our projection', GI.num(proj(r), 1)) + GI.ch.trow(T.ink3, '10th–90th', GI.num(scaleBand(r, r.floor), 1) + '–' + GI.num(scaleBand(r, r.ceil), 1)) + GI.ch.trow(T.ink3, 'Opponent', r.opp || 'bye'); } }),
        series: [{ type: 'custom', silent: true, renderItem: (p, api) => { const i = api.value(0), a = api.coord([api.value(1), i]), b = api.coord([api.value(2), i]); return { type: 'rect', shape: { x: a[0], y: a[1] - 5, width: Math.max(2, b[0] - a[0]), height: 10, r: 5 }, style: { fill: QKC.hexA(GI.ch.lift(GI.teamColour(top[i].team), T), 0.35) } }; },
          data: top.map((r, i) => [i, scaleBand(r, r.floor), scaleBand(r, r.ceil)]), encode: { x: [1, 2], y: 0 } },
          { type: 'scatter', symbolSize: 11, data: top.map((r, i) => ({ value: [proj(r), i], href: GI.playerHref(r.pid), itemStyle: { color: T.model, borderColor: T.s1, borderWidth: 1.5 } })) }] };
    }, 'Projection ranges');
  } };
}
function repl(pos) {
  const n = { QB: 12, RB: 30, WR: 42, TE: 12 }[pos] || 24;
  const xs = ROWS.filter(r => r.pos === pos).map(ros).filter(isNum).sort((a, b) => b - a);
  return xs.length > n ? xs[n] : (xs.length ? xs[xs.length - 1] : 0);
}
const sosCell = v => (isNum(v) ? '<span class="' + (v >= 1.04 ? 'gi-up' : v <= 0.96 ? 'gi-down' : '') + '">' + (v >= 1 ? '+' : '') + Math.round((v - 1) * 100) + '%</span>' : '—');
function rest() {
  const R = {};
  POS.forEach(p => { R[p] = repl(p); });
  let list = filtered().filter(r => isNum(ros(r)));
  list.forEach(r => { r._vor = ros(r) - R[r.pos]; });
  list.sort((a, b) => (ST.pos === 'ALL' ? b._vor - a._vor : ros(b) - ros(a)));
  list = list.slice(0, 200);
  const ts = tiers(list.map(r => (ST.pos === 'ALL' ? r._vor : ros(r))), 80);
  return { html: posBar() + GI.card('Rest of season', esc(FMTS.find(x => x[0] === ST.f)[1]) + ' · value over replacement = points above the 13th QB, 31st RB, 43rd WR and 13th TE (12 teams)', '<div id="gf-ros"></div>', { flush: true }),
    after: () => lb('gf-ros', { rank: true, maxHeight: 700, rowHref: r => GI.playerHref(r.pid),
      rows: list.map((r, i) => ({ pid: r.pid, name: r.name, team: r.team, sub: subOf(r), tier: ts[i], pts: ros(r), g: r.ros_g, vor: r._vor, sofar: r['pts_' + ST.f], gp: r.g, sos: r.sos, next4: r.next4 })),
      columns: [ENT(), { key: 'tier', label: 'Tier', num: true, fmt: v => tierChip(v) }, { key: 'pts', label: 'Points', type: 'bar', fmt: v => '<b>' + GI.num(v, 0) + '</b>' }, { key: 'g', label: 'Games', num: true, fmt: v => GI.num(v, 1) },
        { key: 'vor', label: 'Over replacement', num: true, fmt: v => GI.signed(v, 0) }, { key: 'sofar', label: 'So far', num: true, fmt: (v, r) => GI.num(v, 0) + (r.gp ? ' <span class="qk-muted">(' + r.gp + ' g)</span>' : '') },
        { key: 'sos', label: 'Schedule', num: true, fmt: v => sosCell(v), tip: 'Average matchup of the remaining games' }, { key: 'next4', label: 'Next four (PPR)', sort: false, fmt: v => (v || []).map(w => '<span class="gi-tag" title="Week ' + w[0] + '">' + esc(w[1]) + ' ' + GI.num(w[2], 1) + '</span>').join(' ') }] }) };
}
function sdOf(r) { const fl = scaleBand(r, r.floor), ce = scaleBand(r, r.ceil); return isNum(fl) && isNum(ce) ? Math.max(1, (ce - fl) / 2.563) : 6; }
function startSit() {
  const opts = ROWS.filter(r => r.opp && isNum(proj(r)) && proj(r) > 1).sort((a, b) => proj(b) - proj(a));
  const n = D.start_n || { QB: 12, RB: 24, WR: 36, TE: 12 };
  return { html: GI.card('Who should I start?', 'pick two to four players · the chance each outscores the others, from the projection bands',
    '<div class="gi-toolbar">' + [0, 1, 2, 3].map(i => '<select class="qk-select" id="gf-cmp' + i + '" aria-label="Player ' + (i + 1) + '"><option value="">Pick a player…</option>' + opts.map(r => '<option value="' + esc(r.pid) + '"' + (ST.cmp[i] === r.pid ? ' selected' : '') + '>' + esc(r.name + ' (' + r.pos + ', ' + r.team + ' v ' + r.opp + ')') + '</option>').join('') + '</select>').join('') + '</div><div id="gf-cmp-out" style="margin-top:12px"></div>') +
    '<div class="qk-auto" style="--min:260px">' + POS.map(p => {
      const xs = ROWS.filter(r => r.pos === p && r.opp && isNum(proj(r))).sort((a, b) => proj(b) - proj(a)).slice(0, Math.round(n[p] * 1.75));
      return GI.card(p, 'start the top ' + n[p], '<ol class="gi-ldl">' + xs.map((r, i) => { const lab = i < n[p] ? ['Start', GI.GOOD] : (i < n[p] * 1.5 && p !== 'QB' ? ['Flex', GI.CLOSE] : ['Sit', GI.BAD]);
        return '<li>' + GI.playerLink(r.pid, r.name) + '<b class="gi-num">' + GI.num(proj(r), 1) + '</b> ' + GI.pill(lab[0], lab[1]) + '</li>'; }).join('') + '</ol>');
    }).join('') + '</div>', after: root => {
    const out = () => {
      const xs = ST.cmp.filter(Boolean).map(p => BY[p]).filter(Boolean);
      if (xs.length < 2) { GI.set('gf-cmp-out', GI.muted('Pick at least two players.')); return; }
      const N = 4000, wins = xs.map(() => 0);
      let seed = 12345;
      const rnd = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; };
      const gauss = () => { const u = Math.max(rnd(), 1e-9), v = rnd(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); };
      for (let j = 0; j < N; j++) { let best = -1e9, bi = 0; xs.forEach((r, i) => { const v = Math.max(0, proj(r) + sdOf(r) * gauss()); if (v > best) { best = v; bi = i; } }); wins[bi]++; }
      const order = xs.map((r, i) => ({ r: r, p: wins[i] / N })).sort((a, b) => b.p - a.p);
      GI.set('gf-cmp-out', QK.chances(order.map((o, i) => ({ label: o.r.name + (i === 0 ? ' · start' : ''), sub: o.r.pos + ' v ' + (o.r.opp || 'bye') + ' · ' + GI.num(proj(o.r), 1) + ' (' + GI.num(scaleBand(o.r, o.r.floor), 1) + '–' + GI.num(scaleBand(o.r, o.r.ceil), 1) + ')', p: o.p, color: GI.teamColour(o.r.team), mark: MARK(o.r.team), href: GI.playerHref(o.r.pid) })), { max: 1, sort: false, oursName: 'Our chance of scoring the most of these' }));
    };
    [0, 1, 2, 3].forEach(i => { const s = root.querySelector('#gf-cmp' + i); if (s) s.addEventListener('change', e => { ST.cmp[i] = e.target.value; out(); }); });
    out();
  } };
}
function luck() {
  const list = filtered().filter(r => r.pos !== 'QB' && r.g >= 2 && isNum(r.xfp)).map(r => Object.assign(r, { _d: (r.pts_ppr - r.xfp) / r.g })).sort((a, b) => a._d - b._d);
  const sc = list.filter(r => r.xfp / r.g >= 6);
  return { html: posBar() + GI.card('Points v expected points', 'PPR per game this season · below the line: usage worth more than the points scored (buy low) · above: scoring the usage does not support (sell high)', GI.chartBox('gf-luck', 460, 'Points against expected points')) +
    GI.card('The list', 'Buy low at the top, sell high at the bottom', '<div id="gf-luckt"></div>', { flush: true }) +
    '<p class="gi-cap">Expected points value every target by its yard line and air yards, and every carry by its yard line, at what such plays produced league-wide over the three previous seasons. Players far from expectation tend to come back to it.</p>',
  after: () => {
    lb('gf-luckt', { maxHeight: 640, rowHref: r => GI.playerHref(r.pid), rows: list.slice(0, 250).map(r => ({ pid: r.pid, name: r.name, team: r.team, sub: subOf(r), g: r.g, ppg: r.pts_ppr / r.g, xpg: r.xfp / r.g, d: r._d, td: r.td, xtd: r.xtd, recd: r.rec_yds_s - r.xrec_yds_s, rushd: r.rush_yds_s - r.xrush_yds_s, ts: r.tgt_sh, ts3: r.tgt_sh3 })),
      columns: [ENT(), { key: 'g', label: 'G', num: true }, { key: 'ppg', label: 'PPR/g', num: true, fmt: v => GI.num(v, 1) }, { key: 'xpg', label: 'Expected/g', num: true, fmt: v => GI.num(v, 1), tip: 'Expected PPR points from the player\'s targets and carries' },
        { key: 'd', label: 'Over exp./g', num: true, fmt: v => '<b>' + GI.ptsEdge(v, 1) + '</b>' }, { key: 'td', label: 'TD / exp.', num: true, fmt: (v, r) => GI.int(v) + ' / ' + GI.num(r.xtd, 1) },
        { key: 'recd', label: 'Rec yds v exp.', num: true, fmt: v => GI.signed(v, 0) }, { key: 'rushd', label: 'Rush yds v exp.', num: true, fmt: v => GI.signed(v, 0) }, { key: 'ts', label: 'Target share (last 3)', num: true, fmt: (v, r) => GI.num(100 * (v || 0), 0) + '% → ' + GI.num(100 * (r.ts3 || 0), 0) + '%' }] });
    if (sc.length) GI.ch.scatter('gf-luck', { points: sc.map(r => ({ x: r.xfp / r.g, y: r.pts_ppr / r.g, name: r.name + ' (' + r.pos + ')', label: GI.surnameOf(r.name), color: GI.teamColour(r.team), href: GI.playerHref(r.pid), size: 9 })), xName: 'Expected PPR per game', yName: 'PPR per game', labelTop: 14, xFmt: v => GI.num(v, 0), yFmt: v => GI.num(v, 0), diagonal: { label: 'as expected' }, quadrants: ['', 'Sell high?', 'Buy low?', ''] });
  } };
}
function sched() {
  const teams = Object.keys(D.sos || {}).sort();
  return { html: GI.card('Schedule strength', 'how much more (+) or less (−) the remaining opponents allow to each position than average · rest of season, then the next four weeks', GI.heatTable({ corner: 'Team', center: 1, fmt: v => (v >= 1 ? '+' : '') + Math.round((v - 1) * 100) + '%',
    cols: POS.map(p => p + ' ROS').concat(POS.map(p => p + ' next 4')), rows: teams.map(t => ({ label: GI.teamLink(t, { abbr: true }), values: POS.map(p => ((D.sos[t] || {})[p] || [])[0]).concat(POS.map(p => ((D.sos[t] || {})[p] || [])[1])) })) })) };
}
function backtest() {
  if (!GI.ok(BT) || !BT.backtest) return { html: GI.notBuilt('The backtest', BT) };
  const b = BT.backtest, fm = (b.formats || {})[ST.f] || {};
  const ps = ['QB', 'RB', 'WR', 'TE', 'ALL'].filter(p => fm[p]);
  const h = GI.grid(GI.card('Mean absolute error', 'Lower is better · our model v the season-to-date average v last season', GI.chartBox('bt-mae', 280, 'Mean absolute error by position'), { span: 6 }) +
      GI.card('Rank correlation', 'mean weekly Spearman ρ · higher is better', GI.chartBox('bt-rho', 280, 'Rank correlation by position'), { span: 6 })) +
    GI.card('Walk-forward backtest, ' + (b.seasons || [])[0] + '–' + (b.seasons || []).slice(-1)[0], esc(FMTS.find(x => x[0] === ST.f)[1]) + ' · every week projected from the games before it; tuned on ' + (BT.tune_seasons || []).join(', ') + ' only',
      GI.tableHTML([{ label: 'Pos' }, { label: 'Player-weeks', align: 'right' }, { label: 'MAE model', align: 'right' }, { label: 'MAE season-to-date', align: 'right' }, { label: 'MAE last season', align: 'right' }, { label: 'ρ model', align: 'right' }, { label: 'ρ season-to-date', align: 'right' }, { label: 'ρ last season', align: 'right' }],
        ps.map(p => { const r = fm[p]; return [{ html: '<b>' + p + '</b>' }, { v: r.n }, { html: GI.num(r.model.mae, 2) }, { html: GI.num(r.season_to_date.mae, 2) }, { html: GI.num(r.last_season.mae, 2) }, { html: GI.num(r.model.rho, 3) }, { html: GI.num(r.season_to_date.rho, 3) }, { html: GI.num(r.last_season.rho, 3) }]; })) +
      '<p class="gi-cap">Pool: players fantasy-relevant going in. Actual = 0 when a player did not play, which is where the injury report earns its keep.</p>');
  return { html: h, after: () => {
    GI.ch.bar('bt-mae', { cats: ps, catName: 'Position', series: [{ name: 'Our model', color: 'model', data: ps.map(p => fm[p].model.mae) }, { name: 'Season to date', data: ps.map(p => fm[p].season_to_date.mae) }, { name: 'Last season', data: ps.map(p => fm[p].last_season.mae) }], legend: true, fmt: v => GI.num(v, 2), valName: 'Mean absolute error (pts)' });
    GI.ch.bar('bt-rho', { cats: ps, catName: 'Position', series: [{ name: 'Our model', color: 'model', data: ps.map(p => fm[p].model.rho) }, { name: 'Season to date', data: ps.map(p => fm[p].season_to_date.rho) }, { name: 'Last season', data: ps.map(p => fm[p].last_season.rho) }], legend: true, fmt: v => GI.num(v, 2), valName: 'Spearman rank correlation' });
  } };
}

GI.route('fantasy', function (el, params) {
  S = GI.currentSeason();
  const qy = params.query || {};
  if (qy.f && FMTS.some(x => x[0] === qy.f)) ST.f = qy.f;
  if (qy.tab && TABS.some(x => x[0] === qy.tab)) ST.tab = qy.tab;
  if (qy.pos) ST.pos = String(qy.pos).toUpperCase();
  return GI.loadAll([GI.ypath('fantasy.json', S), 'fantasy_backtest.json']).then(res => {
    if (!el.isConnected) return;
    D = res[0]; BT = res[1];
    const ok = GI.ok(D) && D.rows;
    el.innerHTML = GI.pageHead('Fantasy · ' + S, ok ? 'Week ' + D.week + ' fantasy' : 'Fantasy', 'Projections from our play-level usage model and the game model\'s implied team totals. <a href="#/methodology/fantasy">How it works →</a>') +
      (ok ? '<div id="gf-tiles"></div><div class="gi-toolbar">' + GI.seg('gf-fmt', FMTS, ST.f, 'Scoring') + '</div><div class="qk-tabs" role="tablist" style="margin-top:12px">' + TABS.map(t => '<button type="button" class="qk-tab" role="tab" data-tab="' + t[0] + '" aria-selected="' + (t[0] === ST.tab) + '">' + t[1] + '</button>').join('') + '</div>' : GI.notBuilt('The fantasy projections', D)) +
      '<div id="gf-body" class="gi-page" style="margin-top:14px"></div>';
    if (!ok) { if (GI.ok(BT)) { const o = backtest(); GI.set('gf-body', o.html); if (o.after) o.after(); } return; }
    ROWS = GI.colRows(D); BY = {};
    ROWS.forEach(r => { BY[r.pid] = r; });
    const tilesF = () => GI.set('gf-tiles', GI.kpis(POS.map((p, i) => { const r = ROWS.filter(x => x.pos === p && x.opp && isNum(proj(x))).sort((a, b) => proj(b) - proj(a))[0];
      return r ? GI.kpi('Top ' + p + ' this week', esc(GI.surnameOf(r.name)) + ' ' + GI.num(proj(r), 1), esc(GI.teamAbbr(r.team)) + ' v ' + esc(r.opp) + ' · ' + esc(FMTS.find(x => x[0] === ST.f)[1]) + ' points', { signal: i === 0, href: GI.playerHref(r.pid), tip: 'Our projection for this week' }) : ''; })));
    const draw = () => {
      tilesF();
      try { history.replaceState(null, '', '#/fantasy' + GI.qs({ f: ST.f, tab: ST.tab, pos: ST.pos !== 'ALL' ? ST.pos : '' })); } catch (e) { /* ok */ }
      el.querySelectorAll('[data-tab]').forEach(b => b.setAttribute('aria-selected', b.getAttribute('data-tab') === ST.tab ? 'true' : 'false'));
      const f = { picks: () => ({ html: picks() }), week: week, ros: rest, startsit: startSit, luck: luck, stream: () => { const a = teamTable(D.dst, 'DST'), b = teamTable(D.k, 'K'); return { html: a.html + b.html, after: () => { a.after(); b.after(); } }; }, sched: sched, bt: backtest }[ST.tab] || (() => ({ html: picks() }));
      const o = f();
      const body = document.getElementById('gf-body');
      body.innerHTML = o.html;
      GI.sortable(body);
      GI.wireSeg(body, 'gf-pos', v => { ST.pos = v; draw(); });
      const q = document.getElementById('gf-q');
      if (q) { q.value = ST.q; q.addEventListener('input', e => { ST.q = e.target.value; const p = q.selectionStart; draw(); const n = document.getElementById('gf-q'); if (n) { n.focus(); try { n.setSelectionRange(p, p); } catch (er) { /* ok */ } } }); }
      if (o.after) o.after(body);
    };
    GI.wireSeg(el, 'gf-fmt', v => { ST.f = v; draw(); });
    el.querySelectorAll('[data-tab]').forEach(b => b.addEventListener('click', () => { ST.tab = b.getAttribute('data-tab'); draw(); }));
    draw();
  });
});

})(window.GI);
