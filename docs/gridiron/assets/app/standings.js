/* The Quant Gridiron — Standings (#/standings[/<S>]?v=table|ratings|wins|draft), on Design System 2.0.
 *   head and stat tiles (best record, top-rated team, Super Bowl favourite, the tightest division race);
 *   table    divisions (or the conference seeding race): record, points, rating, schedule strength,
 *            our simulated playoff, division, bye and Super Bowl chances, magic numbers, clinch marks;
 *   ratings  power ratings: offence v defence map, unit heat table, rating by week per division;
 *   wins     simulated final win totals: mean and 90% range chart, full distribution heat table;
 *   draft    draft order odds. Reads <S>/season.json. GI.seasonRows is shared with playoffs.js. */
(function (GI) {
'use strict';

const esc = GI.esc, isNum = GI.isNum;
let TV = 'div', RDIV = null;

function num(v) { return isNum(v) ? Number(v) : null; }
function distMean(wd) {
  if (!wd) return null;
  const ks = Array.isArray(wd) ? wd.map((_, i) => i) : Object.keys(wd).map(Number);
  let e = 0, t = 0;
  ks.forEach(k => { const v = Number(Array.isArray(wd) ? wd[k] : wd[String(k)]) || 0; e += k * v; t += v; });
  return t ? e / t : null;
}
function seasonRows(d) {
  if (!d) return [];
  const st = d.standings || d.table || {};
  let list = [];
  if (Array.isArray(st) && st.length && Array.isArray(st[0].teams)) st.forEach(grp => grp.teams.forEach(r => list.push(Object.assign({ division: grp.division, conference: grp.conference }, r))));
  else if (Array.isArray(st)) list = st.slice();
  else Object.keys(st).forEach(div => (Array.isArray(st[div]) ? st[div] : []).forEach(r => list.push(Object.assign({ division: div }, r))));
  const odds = d.odds || (d.sim && d.sim.teams) || {};
  return list.map((r0, k) => {
    const t = GI.canonTeam(r0.team || r0.abbr || r0.id);
    const r = Object.assign({}, odds[t] || {}, r0, { team: t });
    const info = GI.teamInfo(t);
    r.division = r.division || info.division || '';
    r.conference = r.conference || r.conf || info.conference || String(r.division).slice(0, 3);
    if (!isNum(r.diff) && isNum(r.pf) && isNum(r.pa)) r.diff = Number(r.pf) - Number(r.pa);
    if (!isNum(r.sos_rem) && isNum(r.sos_left)) r.sos_rem = r.sos_left;
    if (!isNum(r.seed) && isNum(r.seed_today)) r.seed = r.seed_today;
    if (!isNum(r.proj_w)) r.proj_w = isNum(r.mean_wins) ? r.mean_wins : distMean(r.win_dist);
    r._order = k;
    return r;
  });
}
GI.seasonRows = seasonRows;
function flag(o, k) { return o && typeof o === 'object' && o[k] === true; }
function pctW(r) { const g = (num(r.w) || 0) + (num(r.l) || 0) + (num(r.t) || 0); return g ? ((num(r.w) || 0) + 0.5 * (num(r.t) || 0)) / g : 0; }
function clinchTag(r) {
  const t = (c, tip, out) => ' <span class="qk-badge' + (out ? '' : ' accent') + '" data-tip="' + tip + '">' + c + '</span>';
  if (flag(r.eliminated, 'playoffs')) return t('e', 'Eliminated from playoff contention', true);
  if (flag(r.clinched, 'top_seed')) return t('z', 'Clinched the No. 1 seed and the bye');
  if (flag(r.clinched, 'division')) return t('y', 'Clinched the division');
  if (flag(r.clinched, 'playoffs')) return t('x', 'Clinched a playoff berth');
  return '';
}
function magicCell(r) {
  if (r.magic && typeof r.magic === 'object') {
    if (flag(r.eliminated, 'playoffs')) return { html: '<span class="qk-muted">out</span>', v: 999 };
    const m = r.magic, bits = [];
    if (isNum(m.playoffs)) bits.push('<span data-tip="Magic number to clinch a playoff place">P' + m.playoffs + '</span>');
    if (isNum(m.division) && !flag(r.eliminated, 'division')) bits.push('<span data-tip="Magic number to win the division">D' + m.division + '</span>');
    return { html: bits.join(' ') || '—', v: m.playoffs };
  }
  if (isNum(r.magic)) return { html: 'M' + Math.round(r.magic), v: r.magic };
  return { html: '—', v: null };
}
function oddsCell(p, colour) {
  if (!isNum(p)) return { html: '<span class="qk-muted">—</span>', v: null };
  if (p >= 0.9995) return { html: '<span class="gi-up">✓ in</span>', v: 1 };
  if (p <= 0.0005) return { html: '<span class="qk-muted">0%</span>', v: 0 };
  return { html: GI.probBar(p, colour), v: p };
}
function divTable(rows, S) {
  return GI.tableHTML([{ label: 'Team' }, { label: 'W-L', align: 'right' }, { label: 'Diff', align: 'right', title: 'Points for minus points against' },
    { label: 'Rating', align: 'right', title: 'Our team rating: points better than an average team on a neutral field' },
    { label: 'Rem SOS', align: 'right', title: 'Strength of the remaining schedule (average opponent rating; played so far in the tooltip)' },
    { label: 'Playoffs', align: 'right', title: 'Our chance of making the playoffs (season simulation)' }, { label: 'Div', align: 'right', title: 'Our chance of winning the division' }, { label: 'Bye', align: 'right', title: 'Our chance of the No. 1 seed and the bye' },
    { label: 'SB', align: 'right', title: 'Our chance of winning the Super Bowl' }, { label: 'Magic', align: 'right', title: 'Magic numbers: P to clinch a playoff place, D to win the division' }],
  rows.map(r => ({ _href: GI.teamHref(r.team, S), cells: [
    { html: GI.teamLink(r.team, { short: true, season: S }) + clinchTag(r), v: r.team },
    { html: GI.record(r.w, r.l, r.t), v: pctW(r) },
    { html: '<span title="' + esc((isNum(r.pf) ? r.pf + ' for, ' + r.pa + ' against' : '')) + '">' + GI.deltaHTML(r.diff, 0) + '</span>', v: r.diff }, { html: isNum(r.rating) ? GI.signed(r.rating, 1) : '—', v: r.rating },
    { html: '<span title="' + esc(isNum(r.sos) ? 'played so far ' + GI.signed(r.sos, 1) : '') + '">' + (isNum(r.sos_rem) ? GI.signed(r.sos_rem, 1) : '—') + '</span>', v: r.sos_rem },
    oddsCell(r.p_playoffs, GI.tc(r.team)), { html: GI.pct(r.p_div, 0), v: r.p_div }, { html: GI.pct(r.p_bye, 0), v: r.p_bye },
    { html: GI.pct(r.p_sb, 1), v: r.p_sb }, magicCell(r)] })), { sticky: true });
}
function divisionsView(rows, S) {
  return GI.grid(GI.DIVISIONS.map(div => {
    const list = rows.filter(r => r.division === div).sort((a, b) => (isNum(a.div_rank) && isNum(b.div_rank) ? a.div_rank - b.div_rank : pctW(b) - pctW(a) || (b.p_div || 0) - (a.p_div || 0)));
    return list.length ? GI.card(div, '', divTable(list, S), { span: 6, flush: true }) : '';
  }).join('')) + '<p class="gi-cap">x clinched a playoff place · y the division · z the bye · e eliminated. Chances from our season simulation of the remaining schedule with the NFL tiebreakers.</p>';
}
function conferencesView(rows, S) {
  return GI.grid(GI.CONFERENCES.map(conf => {
    const list = rows.filter(r => r.conference === conf).sort((a, b) => (isNum(a.seed) && isNum(b.seed) ? a.seed - b.seed : isNum(a.seed) ? -1 : isNum(b.seed) ? 1 : (num(b.p_playoffs) || 0) - (num(a.p_playoffs) || 0)));
    return GI.card(conf + ' seeding race', 'seeds as they stand · the line falls after the 7th seed', GI.tableHTML([{ label: '#', align: 'right' }, { label: 'Team' }, { label: 'W-L', align: 'right' }, { label: 'Div' }, { label: 'Playoffs', align: 'right' }, { label: 'Bye', align: 'right' }, { label: 'Conf', align: 'right' }, { label: 'SB', align: 'right' }],
      list.map((r, i) => ({ _class: i === 6 ? 'gi-cut' : '', _href: GI.teamHref(r.team, S), cells: [isNum(r.seed) ? r.seed : i + 1, { html: GI.teamLink(r.team, { short: true, season: S }) + clinchTag(r), v: r.team },
        { html: GI.record(r.w, r.l, r.t), v: pctW(r) }, String(r.division || '').replace(/^(AFC|NFC) /, ''), oddsCell(r.p_playoffs, GI.tc(r.team)),
        { html: GI.pct(r.p_bye, 0), v: r.p_bye }, { html: GI.pct(r.p_conf, 1), v: r.p_conf }, { html: GI.pct(r.p_sb, 1), v: r.p_sb }] })), { sticky: true }), { span: 6, flush: true });
  }).join(''));
}
function flatRatings(d) {
  const src = d.ratings || d.team_ratings || {};
  const hc = d.ratings_history_cols || ['week', 'net', 'off', 'def'];
  const ni = Math.max(1, hc.indexOf('net')), oi = hc.indexOf('off'), di = hc.indexOf('def');
  const out = {};
  Object.keys(src).forEach(t => {
    const x = src[t] || {}, v = x.values || x;
    const neg = k => (isNum(v[k]) ? -Number(v[k]) : null);
    out[GI.canonTeam(t)] = { overall: isNum(v.overall) ? v.overall : v.rating, off: v.off_rating, def: v.def_rating,
      pass_off: v.off_pass_epa, rush_off: v.off_rush_epa, pass_def: neg('def_pass_epa'), rush_def: neg('def_rush_epa'), st: v.st_epa_g,
      history: (x.history || []).map(r => (Array.isArray(r) ? { w: r[0], net: r[ni], off: oi >= 0 ? r[oi] : null, def: di >= 0 ? r[di] : null } : { w: r.week, net: isNum(r.overall) ? r.overall : r.rating })) };
  });
  return out;
}
function ratingsView(d, rows, S) {
  const rat = flatRatings(d);
  const teams = Object.keys(rat);
  if (!teams.length) return GI.muted('Ratings arrive with the first build.');
  const keys = [['overall', 'Overall', 'Points better than average on a neutral field', 1], ['off', 'Offence', 'Offence rating, points', 1], ['def', 'Defence', 'Defence rating, points', 1],
    ['pass_off', 'Pass off.', 'EPA per dropback, opponent-adjusted', 3], ['rush_off', 'Rush off.', 'EPA per carry', 3], ['pass_def', 'Pass def.', 'EPA per dropback allowed (flipped: positive = better)', 3],
    ['rush_def', 'Rush def.', 'EPA per carry allowed (flipped)', 3], ['st', 'Special teams', 'Special-teams EPA per game', 2]].filter(k => teams.some(t => isNum(rat[t][k[0]])));
  const sorted = teams.slice().sort((a, b) => (num(rat[b].overall) || 0) - (num(rat[a].overall) || 0));
  if (!RDIV) RDIV = GI.DIVISIONS[0];
  return GI.grid(GI.card('Power map', 'offence v defence rating, points per game against an average team', GI.chartBox('rt-map', 460, 'Offence against defence'), { span: 7 }) +
      GI.card('Rating by week', 'overall rating · pick a division', GI.seg('rt-div', GI.DIVISIONS.map(x => [x, x.replace(/ (East|West|North|South)$/, s => ' ' + s.trim().charAt(0))]), RDIV, 'Division') + GI.chartBox('rt-chart', 400, 'Rating by week'), { span: 5 })) +
    GI.card('Unit ratings', 'opponent-adjusted, with priors and time decay · red above the league median, blue below', GI.heatTable({ cols: keys.map(k => ({ label: k[1], title: k[2] })), corner: 'Team', center: 'col',
      rows: sorted.map(t => ({ label: GI.teamLink(t, { short: true, season: S }), values: keys.map(k => rat[t][k[0]]), fmts: keys.map(k => (v => GI.signed(v, k[3]))) })) }));
}
function drawRatings(el, d) {
  const rat = flatRatings(d);
  const teams = Object.keys(rat).filter(t => isNum(rat[t].off));
  if (!teams.length) return;
  GI.ch.scatter('rt-map', { points: teams.map(t => ({ x: rat[t].off, y: rat[t].def, name: GI.teamName(t), label: t, color: GI.teamColour(t), href: GI.teamHref(t), size: 13 })),
    xName: 'Offence (pts/g)', yName: 'Defence (pts/g)', refX: 0, refY: 0, labelAll: true, xFmt: v => GI.signed(v, 0), yFmt: v => GI.signed(v, 0), quadrants: ['Defence carries', 'Contenders', 'Rebuilding', 'Offence carries'] });
  const drawDiv = () => {
    const list = Object.keys(rat).filter(t => GI.teamInfo(t).division === RDIV);
    GI.ch.lines('rt-chart', list.map(t => ({ name: GI.teamAbbr(t), x: rat[t].history.map(h => h.w), y: rat[t].history.map(h => h.net), colour: GI.teamColour(t), symbol: true })), { xName: 'Week', yName: 'Rating (pts/g v average)', yFmt: v => GI.signed(v, 1), xLabel: x => 'Week ' + x, ref: { y: 0 } });
  };
  GI.wireSeg(el, 'rt-div', v => { RDIV = v; drawDiv(); });
  drawDiv();
}
function winsView(rows, S) {
  const list = rows.filter(r => r.win_dist).sort((a, b) => (num(b.proj_w) || 0) - (num(a.proj_w) || 0));
  if (!list.length) return GI.muted('Win distributions arrive with the season simulation.');
  let maxW = 0;
  list.forEach(r => { const wd = r.win_dist; (Array.isArray(wd) ? wd.map((_, i) => i) : Object.keys(wd).map(Number)).forEach(k => { if (k > maxW) maxW = k; }); });
  const ks = [];
  for (let k = 0; k <= maxW; k++) ks.push(k);
  const val = (wd, k) => (Array.isArray(wd) ? wd[k] : wd[String(k)]);
  return GI.card('Projected wins', 'Our mean simulated wins (dot) and the middle 90% of simulations (bar); grey tick: wins so far', GI.chartBox('wn-range', Math.max(420, list.length * 22 + 40), 'Projected win totals')) +
    GI.card('Win distribution', '% of simulations ending on each win total · each row sums to 100% · more on <a href="#/futures">Season forecasts</a>', GI.heatTable({
      cols: ks.map(String).concat(['Mean']), corner: 'Wins', center: 0, max: 0.3,
      rows: list.map(r => ({ label: GI.teamLink(r.team, { abbr: true, season: S }) + ' <span class="qk-muted">' + GI.record(r.w, r.l, r.t) + '</span>', values: ks.map(k => val(r.win_dist, k)).concat([r.proj_w]),
        fmts: ks.map(() => (v => (v >= 0.005 ? String(Math.round(v * 100)) : '·'))).concat([v => '<b>' + GI.num(v, 1) + '</b>']),
        titles: ks.map(k => GI.teamAbbr(r.team) + ' ' + k + ' wins: ' + GI.pct(val(r.win_dist, k), 1)).concat(['Mean']) })) }));
}
function drawWins(rows) {
  const list = rows.filter(r => r.win_dist).sort((a, b) => (num(b.proj_w) || 0) - (num(a.proj_w) || 0));
  if (!list.length) return;
  GI.ch.mount('wn-range', T => {
    const cats = list.map(r => GI.teamAbbr(r.team));
    const ya = GI.ch.ax(T, { type: 'category', data: cats, split: false, inverse: true });
    ya.axisLabel.color = T.ink2;
    return {
      grid: { left: 8, right: 20, top: 10, bottom: 26, containLabel: true },
      xAxis: GI.ch.ax(T, { min: 0, max: GI.regWeeks(GI.state.season), interval: 2, name: 'Wins', nameLocation: 'middle', nameGap: 24 }), yAxis: ya,
      tooltip: GI.ch.tip(T, { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: ps => { const r = list[ps[0].dataIndex]; return GI.ch.thead(esc(GI.teamName(r.team))) + GI.ch.trow(T.model, 'Mean wins', GI.num(r.proj_w, 1)) + GI.ch.trow(T.ink3, '90% range', GI.num(r.w_p05, 0) + '–' + GI.num(r.w_p95, 0)) + GI.ch.trow(T.ink3, 'Now', GI.record(r.w, r.l, r.t)); } }),
      series: [
        { type: 'custom', silent: true, renderItem: (p, api) => { const i = api.value(0), a = api.coord([api.value(1), i]), b = api.coord([api.value(2), i]); return { type: 'rect', shape: { x: a[0], y: a[1] - 4, width: Math.max(2, b[0] - a[0]), height: 8, r: 4 }, style: { fill: QKC.hexA(GI.ch.lift(GI.teamColour(list[i].team), T), 0.35) } }; },
          data: list.map((r, i) => [i, isNum(r.w_p05) ? r.w_p05 : r.proj_w, isNum(r.w_p95) ? r.w_p95 : r.proj_w]), encode: { x: [1, 2], y: 0 }, z: 1 },
        { type: 'scatter', symbol: 'rect', symbolSize: [2, 14], silent: true, data: list.map((r, i) => [num(r.w) || 0, i]), itemStyle: { color: T.ink3 }, z: 2 },
        { type: 'scatter', symbolSize: 10, data: list.map((r, i) => ({ value: [r.proj_w, i], href: GI.teamHref(r.team), itemStyle: { color: GI.ch.lift(GI.teamColour(r.team), T), borderColor: T.s1, borderWidth: 1.5 } })), z: 3 }
      ]
    };
  }, 'Projected win totals');
}
function draftView(d, rows, S) {
  let list = d.draft || d.draft_order || [];
  if (!Array.isArray(list)) list = Object.keys(list).map(t => Object.assign({ team: t }, list[t]));
  if (!list.length) return GI.muted('Draft-order odds arrive with the season simulation.');
  list = list.map(x => Object.assign({}, x, { team: GI.canonTeam(x.team), exp_pick: isNum(x.exp_pick) ? x.exp_pick : x.mean_pick, p_first: isNum(x.p_first) ? x.p_first : x.p_first_pick }))
    .sort((a, b) => (num(a.exp_pick) || num(a.pick_today) || 99) - (num(b.exp_pick) || num(b.pick_today) || 99));
  const rec = t => rows.find(r => r.team === t) || {};
  return GI.grid(GI.card('The No. 1 pick', 'chance of picking first, ' + (S + 1) + ' draft', GI.chartBox('dr-first', 360, 'Chance of the first pick'), { span: 5 }) +
    GI.card('Draft order', 'simulated, before trades · ' + (S + 1) + ' draft', GI.tableHTML([{ label: '#', align: 'right' }, { label: 'Team' }, { label: 'W-L', align: 'right' }, { label: 'Expected pick', align: 'right' }, { label: 'No. 1 pick', align: 'right' }, { label: 'Top 5', align: 'right' }, { label: 'Top 10', align: 'right' }],
      list.map((x, i) => ({ _href: GI.teamHref(x.team, S), cells: [isNum(x.pick_today) ? x.pick_today : i + 1, { html: GI.teamLink(x.team, { short: true, season: S }), v: x.team }, { html: GI.record(rec(x.team).w, rec(x.team).l, rec(x.team).t), v: pctW(rec(x.team)) },
        { html: GI.num(x.exp_pick, 1), v: x.exp_pick }, { html: GI.probBar(x.p_first, GI.tc(x.team)), v: x.p_first }, { html: GI.pct(x.p_top5, 0), v: x.p_top5 }, { html: GI.pct(x.p_top10, 0), v: x.p_top10 }] })), { maxHeight: 620, sticky: true }), { span: 7, flush: true }));
}

/* Stat tiles over the table: the best record, the top-rated team, our Super Bowl favourite, the tightest division race. */
function tiles(rows, S) {
  if (!rows.length) return '';
  const best = rows.slice().sort((a, b) => pctW(b) - pctW(a) || (num(b.diff) || 0) - (num(a.diff) || 0))[0];
  const top = rows.filter(r => isNum(r.rating)).sort((a, b) => b.rating - a.rating)[0];
  const fav = rows.filter(r => isNum(r.p_sb)).sort((a, b) => b.p_sb - a.p_sb)[0];
  let race = null;
  GI.DIVISIONS.forEach(dv => { const l = rows.filter(r => r.division === dv && isNum(r.p_div)).sort((a, b) => b.p_div - a.p_div); if (l.length > 1 && (!race || l[0].p_div < race[0].p_div)) race = l; });
  return GI.kpis([
    GI.kpi('Best record', best ? esc(GI.teamAbbr(best.team)) + ' ' + GI.record(best.w, best.l, best.t) : '—', best ? (isNum(best.diff) ? GI.signed(best.diff, 0) + ' point difference' : '') : '', { href: best ? GI.teamHref(best.team, S) : null }),
    GI.kpi('Top-rated team', top ? esc(GI.teamAbbr(top.team)) + ' ' + GI.signed(top.rating, 1) : '—', 'points a game better than an average team', { href: top ? GI.teamHref(top.team, S) : null, tip: 'Our team-strength rating on a neutral field' }),
    GI.kpi('Super Bowl favourite', fav ? esc(GI.teamAbbr(fav.team)) + ' ' + GI.pct(fav.p_sb, 0) : '—', 'our chance, from the season simulation', { signal: true, href: fav ? GI.teamHref(fav.team, S) : null }),
    GI.kpi('Tightest division', race ? esc(race[0].division) : '—', race ? esc(GI.teamAbbr(race[0].team)) + ' ' + GI.pct(race[0].p_div, 0) + ' · ' + esc(GI.teamAbbr(race[1].team)) + ' ' + GI.pct(race[1].p_div, 0) : '', { text: true, tip: 'The division whose favourite has the lowest chance of winning it' })
  ]);
}

GI.route('standings', function (el, params) {
  const S = Number(params.season);
  const v = String((params.query || {}).v || (params.query || {}).view || 'table');
  const view = ['ratings', 'wins', 'draft'].indexOf(v) >= 0 ? v : 'table';
  if (v === 'conf' || v === 'div') TV = v;
  return GI.loadYear('season.json', S).then(d => {
    if (!el.isConnected) return;
    const pager = (S > GI.FIRST_SEASON ? '<a class="qk-btn" href="' + GI.standingsHref(S - 1, view === 'table' ? null : view) + '">← ' + (S - 1) + '</a>' : '') + (S < GI.currentSeason() ? '<a class="qk-btn" href="' + GI.standingsHref(S + 1, view === 'table' ? null : view) + '">' + (S + 1) + ' →</a>' : '');
    const nav = GI.sectionNav('standings', view);
    if (!GI.ok(d)) { el.innerHTML = GI.pageHead('Standings', S + ' standings', '', pager) + nav + GI.notBuilt('The ' + S + ' standings', d); return; }
    const rows = seasonRows(d);
    const sim = d.sim || {};
    const nsim = isNum(sim.sims) ? sim.sims : sim.n;
    const sub = [isNum(d.week) ? 'through week ' + d.week : '', isNum(nsim) ? GI.int(nsim) + ' season simulations' : '', d.updated_at ? 'updated ' + GI.fmtStamp(d.updated_at) : ''].filter(Boolean).join(' · ');
    const title = { table: S + ' standings', ratings: S + ' power ratings', wins: S + ' win totals', draft: (S + 1) + ' draft order' }[view];
    el.innerHTML = GI.pageHead('Standings · ' + S, title, esc(sub), pager) + nav + (view === 'table' ? tiles(rows, S) : '') + '<div id="std-body"></div>';
    const body = el.querySelector('#std-body');
    if (view === 'table') {
      const draw = () => { body.innerHTML = '<div class="gi-toolbar" style="margin-bottom:12px">' + GI.seg('std-tv', [['div', 'Divisions'], ['conf', 'Conferences']], TV, 'Group by') + '</div>' + (TV === 'conf' ? conferencesView(rows, S) : divisionsView(rows, S)); GI.sortable(body); GI.wireSeg(body, 'std-tv', x => { TV = x; draw(); }); };
      draw();
    } else if (view === 'ratings') { body.innerHTML = ratingsView(d, rows, S); GI.sortable(body); drawRatings(body, d); }
    else if (view === 'wins') { body.innerHTML = winsView(rows, S); drawWins(rows); }
    else {
      body.innerHTML = draftView(d, rows, S); GI.sortable(body);
      const list = (Array.isArray(d.draft) ? d.draft : []).filter(x => isNum(x.p_first_pick) && x.p_first_pick > 0.001).sort((a, b) => b.p_first_pick - a.p_first_pick).slice(0, 10);
      GI.ch.probBars('dr-first', list.map(x => ({ label: GI.teamName(x.team), p: x.p_first_pick, colour: GI.teamColour(x.team), href: GI.teamHref(x.team) })), { keepHeight: true, labelWidth: 140, valName: 'First-pick probability', emptyText: 'No team has a real chance at the first pick yet.' });
    }
  });
});

})(window.GI);
