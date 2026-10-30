/* The Quant Gridiron — Standings (#/standings[/<S>]?v=table|history|races), on Design System 2.0. Round 9: the section's
 * tabs are Table (here), Chances (playoffs.js: the season simulation boards, with the win totals and the draft order from
 * here through GI.STD), Bracket (playoffs.js), History (champions since 1999, history.json) and Races (awards.json);
 * power ratings moved to the Teams page, the performers to the Scouting Room's Leaders. Old views:
 *   head and stat tiles (best record, top-rated team, Super Bowl favourite, the tightest division race);
 *   table    divisions (or the conference seeding race): record, points, rating, schedule strength,
 *            our simulated playoff, division, bye and Super Bowl chances, magic numbers, clinch marks;
 *   ratings  power ratings: offence v defence map, unit heat table, rating by week per division;
 *   wins     simulated final win totals: mean and 90% range chart, full distribution heat table;
 *   draft    draft order odds. Reads <S>/season.json. GI.seasonRows is shared with playoffs.js. */
(function (GI) {
'use strict';

const esc = GI.esc, isNum = GI.isNum;
let TV = 'div';

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
/* The league module's options (docs/_design/league.js, QKL) from season.json["league"]: the teams, the race chart's
   groups (the two conferences, then the eight divisions; `group` picks the first shown) and the race log
   (data/race_log.json through the site's cached loader). null without the block or the module. */
function leagueOpts(d, S, group) {
  const L = d && d.league;
  if (!L || !window.QKL) return null;
  const rows = seasonRows(d), teams = {};
  rows.forEach(r => { teams[r.team] = { abbr: GI.teamAbbr(r.team), name: GI.teamName(r.team), colour: GI.teamColour(r.team), href: GI.teamHref(r.team, S) }; });
  const groups = GI.CONFERENCES.map(c => ({ key: c, label: c, teams: rows.filter(r => r.conference === c).map(r => r.team) }))
    .concat(GI.DIVISIONS.map(dv => ({ key: dv, label: dv, teams: rows.filter(r => r.division === dv).map(r => r.team) })));
  return { league: L, teams: teams, groups: groups, season: String(S), group: group || GI.CONFERENCES[0], loadLog: () => GI.load('race_log.json'),
    title: 'How the playoff race is shaping up', unitGames: 'games' };
}
GI.leagueOpts = leagueOpts;

function toggle(lo, t) { return lo ? QKL.toggle(t, GI.teamName(t)) : ''; }
function chipCell(lo, t) { return { html: QKL.chip(lo, t) || '<span class="qk-muted">—</span>', v: '' }; }
const PROFILE_COL = { label: 'Profile', sortable: false, title: 'What stands out about the team; + opens its card: strengths, weaknesses and the race' };
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
function doneTable(rows, S) {
  return GI.tableHTML([{ label: 'Team' }, { label: 'W-L', align: 'right' }, { label: 'Diff', align: 'right', title: 'Points for minus points against' },
    { label: 'Rating', align: 'right', title: 'Our team rating at the end of the season' }, { label: 'Seed', align: 'right', title: 'Playoff seed at the end of the regular season' }],
  rows.map(r => ({ _href: GI.teamHref(r.team, S), cells: [{ html: GI.teamLink(r.team, { short: true, season: S }) + clinchTag(r), v: r.team }, { html: GI.record(r.w, r.l, r.t), v: pctW(r) },
    { html: GI.deltaHTML(r.diff, 0), v: r.diff }, { html: isNum(r.rating) ? GI.signed(r.rating, 1) : '—', v: r.rating }, { html: isNum(r.seed) ? '<b>' + r.seed + '</b>' : '<span class="qk-muted">—</span>', v: isNum(r.seed) ? r.seed : 99 }] })), { sticky: true });
}
function divTable(rows, S, lo, done) {
  if (done) return doneTable(rows, S);
  return GI.tableHTML([{ label: 'Team' }, { label: 'W-L', align: 'right' }, { label: 'Diff', align: 'right', title: 'Points for minus points against' },
    { label: 'Rating', align: 'right', title: 'Our team rating: points better than an average team on a neutral field' },
    { label: 'Rem SOS', align: 'right', title: 'Strength of the remaining schedule (average opponent rating; played so far in the tooltip)' },
    { label: 'Playoffs', align: 'right', title: 'Our chance of making the playoffs (season simulation)' }, { label: 'Div', align: 'right', title: 'Our chance of winning the division' }, { label: 'Bye', align: 'right', title: 'Our chance of the No. 1 seed and the bye' },
    { label: 'SB', align: 'right', title: 'Our chance of winning the Super Bowl' }, { label: 'Magic', align: 'right', title: 'Magic numbers: P to clinch a playoff place, D to win the division' }].concat(lo ? [PROFILE_COL] : []),
  rows.map(r => ({ _href: GI.teamHref(r.team, S), cells: [
    { html: toggle(lo, r.team) + GI.teamLink(r.team, { short: true, season: S }) + clinchTag(r), v: r.team },
    { html: GI.record(r.w, r.l, r.t), v: pctW(r) },
    { html: '<span title="' + esc((isNum(r.pf) ? r.pf + ' for, ' + r.pa + ' against' : '')) + '">' + GI.deltaHTML(r.diff, 0) + '</span>', v: r.diff }, { html: isNum(r.rating) ? GI.signed(r.rating, 1) : '—', v: r.rating },
    { html: '<span title="' + esc(isNum(r.sos) ? 'played so far ' + GI.signed(r.sos, 1) : '') + '">' + (isNum(r.sos_rem) ? GI.signed(r.sos_rem, 1) : '—') + '</span>', v: r.sos_rem },
    oddsCell(r.p_playoffs, GI.tc(r.team)), { html: GI.pct(r.p_div, 0), v: r.p_div }, { html: GI.pct(r.p_bye, 0), v: r.p_bye },
    { html: GI.pct(r.p_sb, 1), v: r.p_sb }, magicCell(r)].concat(lo ? [chipCell(lo, r.team)] : []) })), { sticky: true });
}
function divisionsView(rows, S, lo, done) {
  return GI.grid(GI.DIVISIONS.map(div => {
    const list = rows.filter(r => r.division === div).sort((a, b) => (isNum(a.div_rank) && isNum(b.div_rank) ? a.div_rank - b.div_rank : done && (isNum(a.seed) || isNum(b.seed)) ? (isNum(a.seed) ? a.seed : 99) - (isNum(b.seed) ? b.seed : 99) || pctW(b) - pctW(a) : pctW(b) - pctW(a) || (b.p_div || 0) - (a.p_div || 0)));
    return list.length ? GI.card(div, '', divTable(list, S, lo, done), { span: lo ? 12 : 6, flush: true }) : '';
  }).join('')) + '<p class="gi-cap">' + (done ? 'z the No. 1 seed · y won the division · x a wild card · e missed the playoffs. Seeds as the regular season ended.' : 'x clinched a playoff place · y the division · z the bye · e eliminated. Chances from our season simulation of the remaining schedule with the NFL tiebreakers.') + '</p>';
}
function conferencesView(rows, S, lo, done) {
  if (done) return GI.grid(GI.CONFERENCES.map(conf => GI.card(conf + ' seeds', 'how the regular season finished · the line falls after the 7th seed', doneTable(rows.filter(r => r.conference === conf).sort((a, b) => (isNum(a.seed) ? a.seed : 99) - (isNum(b.seed) ? b.seed : 99) || pctW(b) - pctW(a)), S), { span: 6, flush: true })).join(''));
  return GI.grid(GI.CONFERENCES.map(conf => {
    const list = rows.filter(r => r.conference === conf).sort((a, b) => (isNum(a.seed) && isNum(b.seed) ? a.seed - b.seed : isNum(a.seed) ? -1 : isNum(b.seed) ? 1 : (num(b.p_playoffs) || 0) - (num(a.p_playoffs) || 0)));
    return GI.card(conf + ' seeding race', 'seeds as they stand · the line falls after the 7th seed', GI.tableHTML([{ label: '#', align: 'right' }, { label: 'Team' }, { label: 'W-L', align: 'right' }, { label: 'Div' }, { label: 'Playoffs', align: 'right' }, { label: 'Bye', align: 'right' }, { label: 'Conf', align: 'right' }, { label: 'SB', align: 'right' }].concat(lo ? [PROFILE_COL] : []),
      list.map((r, i) => ({ _class: i === 6 ? 'gi-cut' : '', _href: GI.teamHref(r.team, S), cells: [isNum(r.seed) ? r.seed : i + 1, { html: toggle(lo, r.team) + GI.teamLink(r.team, { short: true, season: S }) + clinchTag(r), v: r.team },
        { html: GI.record(r.w, r.l, r.t), v: pctW(r) }, String(r.division || '').replace(/^(AFC|NFC) /, ''), oddsCell(r.p_playoffs, GI.tc(r.team)),
        { html: GI.pct(r.p_bye, 0), v: r.p_bye }, { html: GI.pct(r.p_conf, 1), v: r.p_conf }, { html: GI.pct(r.p_sb, 1), v: r.p_sb }].concat(lo ? [chipCell(lo, r.team)] : []) })), { sticky: true }), { span: lo ? 12 : 6, flush: true });
  }).join(''));
}
function winsView(rows, S) {
  const list = rows.filter(r => r.win_dist).sort((a, b) => (num(b.proj_w) || 0) - (num(a.proj_w) || 0));
  if (!list.length) return GI.muted('Win distributions arrive with the season simulation.');
  let maxW = 0;
  list.forEach(r => { const wd = r.win_dist; (Array.isArray(wd) ? wd.map((_, i) => i) : Object.keys(wd).map(Number)).forEach(k => { if (k > maxW) maxW = k; }); });
  const ks = [];
  for (let k = 0; k <= maxW; k++) ks.push(k);
  const val = (wd, k) => (Array.isArray(wd) ? wd[k] : wd[String(k)]);
  /* round 9: the legacy wall (a 32 x 19 heat table first) rebuilt as the number, the chart, the table (folded), the explain strip */
  const top = list[0], wide = list.filter(r => isNum(r.w_p05) && isNum(r.w_p95)).sort((a, b) => (b.w_p95 - b.w_p05) - (a.w_p95 - a.w_p05))[0];
  const sure = list.filter(r => isNum(r.w_p05) && isNum(r.w_p95)).sort((a, b) => (a.w_p95 - a.w_p05) - (b.w_p95 - b.w_p05))[0];
  return GI.kpis([top ? GI.kpi('Most projected wins', esc(GI.teamAbbr(top.team)) + ' ' + GI.num(top.proj_w, 1), 'the average of 20,000 simulated seasons; ' + GI.record(top.w, top.l, top.t) + ' so far', { signal: true, href: GI.teamHref(top.team, S) }) : '',
      wide ? GI.kpi('Widest range', esc(GI.teamAbbr(wide.team)) + ' ' + GI.num(wide.w_p05, 0) + '–' + GI.num(wide.w_p95, 0), 'the middle 90% of its simulated seasons', { href: GI.teamHref(wide.team, S) }) : '',
      sure ? GI.kpi('Narrowest range', esc(GI.teamAbbr(sure.team)) + ' ' + GI.num(sure.w_p05, 0) + '–' + GI.num(sure.w_p95, 0), 'the most settled season so far', { href: GI.teamHref(sure.team, S) }) : '']) +
    GI.card('Projected wins', 'Our mean simulated wins (dot) and the middle 90% of simulations (bar); grey tick: wins so far', GI.chartBox('wn-range', Math.max(420, list.length * 22 + 40), 'Projected win totals')) +
    '<details class="gi-more-d"><summary class="qk-btn">Every win total, team by team (the full distribution)</summary>' +
    GI.card('Win distribution', '% of simulations ending on each win total · each row sums to 100%', GI.heatTable({
      cols: ks.map(String).concat(['Mean']), corner: 'Wins', center: 0, max: 0.3,
      rows: list.map(r => ({ label: GI.teamLink(r.team, { abbr: true, season: S }) + ' <span class="qk-muted">' + GI.record(r.w, r.l, r.t) + '</span>', values: ks.map(k => val(r.win_dist, k)).concat([r.proj_w]),
        fmts: ks.map(() => (v => (v >= 0.005 ? String(Math.round(v * 100)) : '·'))).concat([v => '<b>' + GI.num(v, 1) + '</b>']),
        titles: ks.map(k => GI.teamAbbr(r.team) + ' ' + k + ' wins: ' + GI.pct(val(r.win_dist, k), 1)).concat(['Mean']) })) })) + '</details>' +
    QK.explain('A team projected for <b>10.5 wins</b> ends the season with 10 or 11 more often than any other total, but the bar shows how wide it really is: an injury to the quarterback or a run of close games moves a season by three or four wins. The bars narrow as the games are played.', { title: 'What’s that number?' });
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
    fav && fav.p_sb >= 0.9995 ? GI.kpi('Super Bowl champions', esc(GI.teamAbbr(fav.team)), 'the season is decided', { signal: true, href: GI.teamHref(fav.team, S) })   /* round 11 */
      : GI.kpi('Super Bowl favourite', fav ? esc(GI.teamAbbr(fav.team)) + ' ' + GI.pct(fav.p_sb, 0) : '—', 'our chance, from the season simulation', { signal: true, href: fav ? GI.teamHref(fav.team, S) : null }),
    GI.kpi('Tightest division', race ? esc(race[0].division) : '—', race ? esc(GI.teamAbbr(race[0].team)) + ' ' + GI.pct(race[0].p_div, 0) + ' · ' + esc(GI.teamAbbr(race[1].team)) + ' ' + GI.pct(race[1].p_div, 0) : '', { text: true, tip: 'The division whose favourite has the lowest chance of winning it' })
  ]);
}

/* A finished season: the final seeds and how each team's season ended, from the seeds and the bracket (seasons before
   the clinch flags were kept carry seed_today, the seeding at the end of the regular season). */
function finished(d) { return !!d && (String(d.phase || '') === 'offseason' || String(d.phase || '') === 'post') && !(d.sim && d.sim.available && String(d.phase) === 'regular'); }
function seedFlags(rows) {
  rows.forEach(r => {
    if (r.clinched && typeof r.clinched === 'object' && Object.keys(r.clinched).some(k => r.clinched[k] === true)) return;
    const s = num(r.seed);
    r.clinched = { playoffs: isNum(s) && s <= 7, division: isNum(s) && s <= 4, top_seed: s === 1 };
    r.eliminated = { playoffs: !isNum(s) };
  });
}

/* The games that matter this week: each team's next game (season.json next_game) with its playoff chance after a win
   and after a loss; a game's weight is how far one result moves the two teams together. */
function gamesThatMatter(rows, S) {
  const by = {};
  rows.forEach(r => {
    const ng = r.next_game;
    if (!ng || !ng.game_id || !ng.if_win || !ng.if_loss || !isNum(r.p_playoffs)) return;
    const g = by[ng.game_id] || (by[ng.game_id] = { id: ng.game_id, week: ng.week, sides: [] });
    g.sides.push({ team: r.team, home: !!ng.home, now: r.p_playoffs, w: ng.if_win.p_playoffs, l: ng.if_loss.p_playoffs, p: ng.p_win });
  });
  const list = Object.keys(by).map(k => by[k]).map(g => Object.assign(g, { swing: g.sides.reduce((s, x) => s + Math.abs((x.w || 0) - (x.l || 0)), 0) })).filter(g => g.swing > 0.02)
    .sort((a, b) => b.swing - a.swing).slice(0, 6);
  if (!list.length) return '';
  const side = x => '<div class="gi-gm-s"><span class="gi-gm-t">' + GI.teamLink(x.team, { abbr: true, season: S }) + '</span><span class="gi-gm-b" role="img" aria-label="' + esc(GI.teamAbbr(x.team) + ': ' + GI.pct(x.now, 0) + ' now, ' + GI.pct(x.w, 0) + ' with a win, ' + GI.pct(x.l, 0) + ' with a loss') + '">' +
    '<i class="l" style="left:' + (100 * Math.min(x.l, x.w)).toFixed(1) + '%;width:' + Math.max(0.8, 100 * Math.abs(x.w - x.l)).toFixed(1) + '%"></i><b style="left:' + (100 * x.now).toFixed(1) + '%"></b></span>' +
    '<span class="gi-gm-n num">' + GI.pct(x.l, 0) + ' → ' + GI.pct(x.w, 0) + '</span></div>';
  return '<section class="qk-section">' + QK.sectionHead({ kicker: 'Games that matter', title: 'This week’s biggest swings', sub: 'Each team’s playoff chance after a loss and after a win (the bar), with the tick where it stands now. Ranked by how far the result moves the two teams together, from 20,000 simulated seasons.' }) +
    '<div class="gi-gm">' + list.map(g => {
      const s = g.sides.slice().sort((a, b) => (a.home ? 1 : 0) - (b.home ? 1 : 0));
      return '<a class="qk-card gi-gm-c" href="' + GI.gameHref(g.id) + '"><span class="gi-gm-h">' + esc(GI.weekLabel(g.week, S)) + ' · ' + esc(s.map(x => GI.teamAbbr(x.team)).join(' at ')) + '<b>' + GI.num(100 * g.swing, 0) + ' pts at stake</b></span>' + s.map(side).join('') + '</a>';
    }).join('') + '</div></section>';
}

/* History: every season since 1999 (history.json champions): the champions as team-colour blocks, titles per team,
   the best regular seasons, and the longest waits for a playoff place. */
function historyView(h, S) {
  const C = h && h.champions;
  if (!C || !(C.seasons || []).length) return GI.notBuilt('The champions list', h);
  const seasons = C.seasons.filter(x => x.sb);
  const blk = t => { const b = QK.color.block(GI.teamInfo(t).colour || null); return 'background:' + b.bg + (b.edge ? ';box-shadow:inset 0 -5px 0 ' + b.edge : ''); };
  const strip = '<div class="gi-champs">' + seasons.slice().reverse().map(x => '<a class="gi-champ" href="' + GI.teamHref(x.sb[0], x.season) + '" style="' + blk(x.sb[0]) + '" title="' + esc(x.season + ': ' + GI.teamName(x.sb[0]) + ' ' + x.sb[2] + '–' + x.sb[3] + ' ' + GI.teamName(x.sb[1])) + '">' +
    '<span class="y">' + x.season + '</span><b>' + esc(GI.teamAbbr(x.sb[0])) + '</b><span class="s">' + x.sb[2] + '–' + x.sb[3] + ' v ' + esc(GI.teamAbbr(x.sb[1])) + '</span></a>').join('') + '</div>';
  const titles = {}, apps = {}, conf = {};
  seasons.forEach(x => { titles[x.sb[0]] = (titles[x.sb[0]] || []).concat([x.season]); apps[x.sb[0]] = (apps[x.sb[0]] || 0) + 1; apps[x.sb[1]] = (apps[x.sb[1]] || 0) + 1; });
  C.seasons.forEach(x => ['afc', 'nfc'].forEach(k => { if (x[k]) conf[x[k]] = (conf[x[k]] || 0) + 1; }));
  const board = Object.keys(apps).sort((a, b) => ((titles[b] || []).length - (titles[a] || []).length) || (apps[b] - apps[a])).map(t => '<div class="gi-ttl"><span class="gi-ttl-t">' + GI.teamLink(t, { short: true }) + '</span>' +
    '<span class="gi-ttl-b">' + (titles[t] || []).map(y => '<i style="' + blk(t) + '" title="' + y + '">' + String(y).slice(2) + '</i>').join('') + '</span><span class="gi-ttl-n num">' + (titles[t] || []).length + ' of ' + apps[t] + ' Super Bowls · ' + (conf[t] || 0) + ' conference titles</span></div>').join('');
  const all = [];
  Object.keys(C.teams || {}).forEach(t => (C.teams[t] || []).forEach(r => { if (r[0] < S || !finishedSeason(C, r[0])) { const g = r[1] + r[2] + r[3]; if (g >= 10) all.push({ t: t, s: r[0], w: r[1], l: r[2], ti: r[3], pct: (r[1] + 0.5 * r[3]) / g, d: r[4] - r[5], far: r[6], as: r[7] }); } }));
  const best = all.filter(x => finishedSeason(C, x.s)).sort((a, b) => b.pct - a.pct || b.d - a.d).slice(0, 10);
  const lastDone = Math.max.apply(null, C.seasons.filter(x => x.sb).map(x => x.season));
  const drought = Object.keys(C.teams || {}).map(t => {
    const rs = (C.teams[t] || []).filter(r => r[0] <= lastDone);
    const lastIn = rs.filter(r => r[6] > 0).map(r => r[0]), lastWin = rs.filter(r => r[6] >= 2).map(r => r[0]);
    return { t: t, since: lastIn.length ? lastDone - Math.max.apply(null, lastIn) : null, winSince: lastWin.length ? lastDone - Math.max.apply(null, lastWin) : null, first: rs.length ? rs[0][0] : 1999 };
  }).filter(x => isNum(x.winSince) || isNum(x.since)).sort((a, b) => (b.winSince === null ? 99 : b.winSince) - (a.winSince === null ? 99 : a.winSince)).slice(0, 8);
  const far = C.far || {};
  return '<section class="qk-section">' + QK.sectionHead({ kicker: 'Champions', title: 'Every Super Bowl since ' + seasons[0].season, sub: 'The winner in its colours, the score and the team it beat. Tap a season for that team’s page.' }) + strip + '</section>' +
    '<section class="qk-section">' + QK.sectionHead({ kicker: 'Dynasties', title: 'Titles since ' + seasons[0].season, sub: 'Each block is a Super Bowl win; the line counts the trips and the conference titles.' }) + '<div class="qk-card"><div class="qk-card-body gi-ttls">' + board + '</div></div></section>' +
    GI.grid(GI.card('The best regular seasons', 'Win % since ' + C.seasons[0].season + ', and how each one ended', GI.tableHTML([{ label: 'Season', align: 'right' }, { label: 'Team' }, { label: 'W-L', align: 'right' }, { label: 'Point diff', align: 'right' }, { label: 'How it ended' }],
      best.map(x => [x.s, { html: GI.teamLink(x.t, { short: true, season: x.s }) + (x.as ? ' <span class="gi-tag">' + esc(x.as) + '</span>' : ''), v: x.t }, { html: GI.record(x.w, x.l, x.ti), v: x.pct }, { html: GI.signed(x.d, 0), v: x.d }, esc(far[x.far] || '')]), { sticky: true }), { span: 7, flush: true }) +
      GI.card('The longest waits', 'Seasons since a team last won a playoff game (and since its last playoff place), through ' + lastDone, GI.tableHTML([{ label: 'Team' }, { label: 'Since a playoff win', align: 'right' }, { label: 'Since a playoff place', align: 'right' }],
        drought.map(x => [{ html: GI.teamLink(x.t, { short: true }), v: x.t }, { html: x.winSince === null ? 'none since ' + x.first : x.winSince === 0 ? 'won one in ' + lastDone : x.winSince + ' seasons', v: x.winSince === null ? 99 : x.winSince }, { html: x.since === null ? 'none since ' + x.first : x.since === 0 ? 'in, ' + lastDone : x.since + ' seasons', v: x.since === null ? 99 : x.since }])), { span: 5, flush: true })) +
    '<p class="gi-cap">From the play-by-play era (1999 on) in our data. Teams that moved are listed under today’s name, with the old abbreviation as a tag (Oakland, San Diego, St. Louis).</p>';
}
function finishedSeason(C, s) { return (C.seasons || []).some(x => x.season === s && x.sb); }

/* Races: the award races from our models (awards.json): our chance for each candidate. The market stays on the Model page. */
const AWARDS = [['mvp', 'Most Valuable Player'], ['opoy', 'Offensive Player of the Year'], ['dpoy', 'Defensive Player of the Year'], ['oroy', 'Offensive Rookie of the Year'], ['droy', 'Defensive Rookie of the Year'], ['cpoy', 'Comeback Player of the Year'], ['coty', 'Coach of the Year']];
function racesView(a, S) {
  const A = (GI.ok(a) && a.awards) || {};
  const keys = AWARDS.filter(k => A[k[0]] && (A[k[0]].candidates || []).length);
  if (!keys.length) return QK.empty('No award races yet', S < GI.currentSeason() ? 'Award races are kept for the current season.' : 'The award races start once the season has a few weeks of games.');
  return '<section class="qk-section">' + QK.sectionHead({ kicker: 'Award races', title: 'Who wins the hardware?', sub: 'Our chance for each candidate, from our player models and the season simulation' + (isNum(a.share_played) ? ' with ' + GI.pct(a.share_played, 0) + ' of the season played' : '') + '. Voters are people, so a model of the votes is rougher than a model of the games.' }) +
    '<div class="qk-auto" style="--min:340px">' + keys.map(k => {
      const c = (A[k[0]].candidates || []).filter(x => isNum(x.p_model)).sort((x, y) => y.p_model - x.p_model).slice(0, 8);
      return GI.card(esc(A[k[0]].name || k[1]), 'Our chance', QK.chances(c.map(x => ({ label: x.name + (x.team ? ' · ' + GI.teamAbbr(x.team) : ''), p: x.p_model, href: x.pid ? GI.playerHref(x.pid, S) : (x.team ? GI.teamHref(x.team, S) : null), color: x.team ? GI.teamInfo(x.team).colour : null, mark: x.team ? { name: GI.teamName(x.team), abbr: GI.teamAbbr(x.team), colour: GI.teamInfo(x.team).colour } : null })), { limit: 8, key: false }));
    }).join('') + '</div></section>';
}

GI.route('standings', function (el, params) {
  const S = Number(params.season);
  const v = String((params.query || {}).v || (params.query || {}).view || 'table');
  const view = ['history', 'races'].indexOf(v) >= 0 ? v : 'table';
  if (v === 'conf' || v === 'div') TV = v;
  const extra = view === 'history' ? GI.load('history.json') : view === 'races' ? GI.loadYear('awards.json', S) : Promise.resolve(null);
  return Promise.all([GI.loadYear('season.json', S), extra]).then(res => {
    const d = res[0];
    if (!el.isConnected) return;
    const pager = (S > GI.FIRST_SEASON ? '<a class="qk-btn" href="' + GI.standingsHref(S - 1, view === 'table' ? null : view) + '">← ' + (S - 1) + '</a>' : '') + (S < GI.currentSeason() ? '<a class="qk-btn" href="' + GI.standingsHref(S + 1, view === 'table' ? null : view) + '">' + (S + 1) + ' →</a>' : '');
    const nav = GI.sectionNav('standings', view);
    if (view === 'history') { el.innerHTML = GI.pageHead('Standings', 'Champions since 1999', 'Every Super Bowl, the dynasties, the best regular seasons and the longest waits, from the play-by-play era in our data.') + nav + historyView(res[1], S); GI.sortable(el); return; }
    if (view === 'races') { el.innerHTML = GI.pageHead('Standings · ' + S, S + ' award races', '', pager) + nav + racesView(res[1], S); return; }
    if (!GI.ok(d)) { el.innerHTML = GI.pageHead('Standings', S + ' standings', '', pager) + nav + GI.notBuilt('The ' + S + ' standings', d); return; }
    const rows = seasonRows(d);
    const done = finished(d);
    if (done) seedFlags(rows);
    const sim = d.sim || {};
    const nsim = isNum(sim.sims) ? sim.sims : sim.n;
    const sub = [done ? 'final regular-season standings, with the seeds' : (isNum(d.week) ? 'through week ' + d.week : ''), !done && isNum(nsim) ? GI.int(nsim) + ' season simulations' : '', d.updated_at ? 'updated ' + GI.fmtStamp(d.updated_at) : ''].filter(Boolean).join(' · ');
    el.innerHTML = GI.pageHead('Standings · ' + S, S + ' standings', esc(sub), pager) + nav + (done && GI.recap ? '<div id="std-recap"></div>' : tiles(rows, S)) + '<div id="std-body"></div>' +
      (done ? '' : gamesThatMatter(rows, S)) +
      '<p class="gi-cap">The race over time, the movers and every team’s chances are on <a href="' + GI.playoffsHref(S) + '">Chances</a>; the leaders at every position are in the <a href="' + GI.ghref('scout', S, { view: 'leaders' }) + '">Scouting Room</a>.</p>';
    if (done && GI.recap) GI.recap(el.querySelector('#std-recap'), d, S, rows);
    const body = el.querySelector('#std-body');
    const lo = done ? null : leagueOpts(d, S, GI.DIVISIONS[0]);
    const draw = () => { body.innerHTML = '<div class="gi-toolbar" style="margin-bottom:12px">' + GI.seg('std-tv', [['div', 'Divisions'], ['conf', 'Conferences']], TV, 'Group by') + '</div>' + (TV === 'conf' ? conferencesView(rows, S, lo, done) : divisionsView(rows, S, lo, done)) +
      (lo ? '<p class="gi-cap">+ opens a team’s card: its strengths and weaknesses against the other 31 and where its race stands.</p>' : ''); GI.sortable(body); GI.wireSeg(body, 'std-tv', x => { TV = x; draw(); }); if (lo) QKL.wire(body, lo); };
    draw();
  });
});
GI.STD = { winsView: winsView, drawWins: drawWins, draftView: draftView, pctW: pctW, clinchTag: clinchTag, seedFlags: seedFlags, finished: finished };

})(window.GI);
