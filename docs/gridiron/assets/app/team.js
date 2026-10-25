/* The Quant Gridiron — the team page (#/team/<abbr>), on kit v3 "Matchday".
 * Header (team tile, record, coach) with "The short version" in plain English, then tiles (rating and our chances) · season path (our chance of each stage as chance bars, final
 * seed, final wins) · ratings through the
 * season · top performers (overall and by position against the league, QKL.performers) · strengths and needs (unit
 * and position grades; no potential signings or targets on the team page since round 5) ·
 * the current roster (latest roster and status from valuation.json, grouped by position, with value) and
 * recent moves (ledgers/<abbr>.json) · schedule with our chance and projected margin · QB situation ·
 * team profile percentiles (a percentile card against the 32 teams) · tendencies · fourth downs. Past seasons show what
 * their payloads carry. */
(function (GI) {
'use strict';

const QK = window.QK;
const esc = GI.esc, isNum = GI.isNum, first = GI.first;
const POS_ORDER = ['QB', 'RB', 'WR', 'TE', 'EDGE', 'DL', 'LB', 'CB', 'S', 'K', 'P'];
const POS_NAME = { QB: 'Quarterbacks', RB: 'Running backs', WR: 'Wide receivers', TE: 'Tight ends', EDGE: 'Outside rushers (ED)', DL: 'Interior line', LB: 'Linebackers', CB: 'Cornerbacks', S: 'Safeties', K: 'Kicker', P: 'Punter' };
const STATUS = { ACT: '', RES: 'IR', DEV: 'Practice squad', INA: 'Inactive', EXE: 'Exempt', FA: 'Free agent', PUP: 'PUP', SUS: 'Suspended' };
/* grades on the percentile scale (A hot, F cold), with the ink that reads on each */
const GRADE_P = { A: 92, B: 72, C: 50, D: 28, F: 8 };
function gradeChip(g) { const p = GRADE_P[g]; return g ? '<span class="gi-tier" style="--tierc:' + (isNum(p) ? QK.pctColor(p) : 'var(--ink-3)') + ';color:' + (isNum(p) ? QK.pctInk(p) : 'var(--s-ink)') + '">' + esc(g) + '</span>' : '<span class="qk-muted">—</span>'; }

function rosterBlock(abbr, val, S) {
  if (!GI.ok(val) || !Array.isArray(val.rows)) return '';
  const cols = val.cols || [];
  const ix = k => cols.indexOf(k);
  const mine = val.rows.filter(r => r[ix('team')] === abbr).map(r => ({ pid: r[ix('pid')], name: r[ix('name')], pos: r[ix('pos')], age: r[ix('age')], status: r[ix('status')], value: r[ix('value')], games: r[ix('games')], now: r[ix('now_pg')] }));
  if (!mine.length) return '';
  const by = {};
  mine.forEach(p => { (by[p.pos] = by[p.pos] || []).push(p); });
  const groups = POS_ORDER.filter(p => by[p]).concat(Object.keys(by).filter(p => POS_ORDER.indexOf(p) < 0));
  const ir = mine.filter(p => p.status && p.status !== 'ACT').length;
  return GI.card('Current roster', mine.length + ' players' + (ir ? ' · ' + ir + ' on reserve lists or the practice squad' : '') + ' · value: projected points above replacement, rest of this season and the next three · offensive linemen are not valued individually and are not listed',
    '<div class="gi-roster">' + groups.map(g => '<div class="gi-roster-g"><h4>' + esc(POS_NAME[g] || g) + '</h4>' + by[g].sort((a, b) => (a.status === 'ACT' ? 0 : 1) - (b.status === 'ACT' ? 0 : 1) || (b.value || 0) - (a.value || 0)).map(p =>
      '<div class="gi-roster-r"><span class="pos">' + esc(GI.posLabel(g)) + '</span><span class="qk-truncate">' + GI.playerLink(p.pid, p.name) + (STATUS[p.status] ? ' <span class="qk-badge">' + esc(STATUS[p.status] || p.status) + '</span>' : '') + '</span><span class="v" title="Projected value above replacement">' + (isNum(p.value) ? GI.num(p.value, 0) : '—') + '</span></div>').join('') + '</div>').join('') + '</div>',
    { id: 'roster' });
}
function movesBlock(led, S) {
  if (!GI.ok(led)) return '';
  const feed = GI.colRows({ cols: led.feed_cols || ['date', 'type', 'text', 'players'], rows: led.feed || [] }).slice(0, 14);
  const sm = led.summary || {};
  const trades = (led.trades || []).slice(0, 4);
  const TYPE = { trade: 'Trade', signing: 'Signed', release: 'Released', reserve: 'Reserve', practice: 'Practice squad', waiver: 'Waivers', activation: 'Activated' };
  return GI.card('Moves', 'the last twelve months of club transactions · <a href="#/transactions?tab=team&team=' + esc(led.team) + '">full ledger →</a>',
    (isNum(sm.trades) ? GI.kpis([GI.kpi('Trades', String(sm.trades), 'in the window'), GI.kpi('Trade value now', GI.signed(sm.net_now, 1), 'points above replacement, net', { tip: 'Realised plus projected value of what came in minus what went out' }),
      GI.kpi('Signed', isNum(sm.n_signed) ? String(sm.n_signed) : '—', isNum(sm.signed) ? GI.num(sm.signed, 0) + ' pts of value in' : ''), GI.kpi('Lost', isNum(sm.n_lost) ? String(sm.n_lost) : '—', isNum(sm.lost) ? GI.num(sm.lost, 0) + ' pts of value out' : '')], 'gi-kpis-4') : '') +
    (trades.length ? '<ul class="gi-moves" style="margin:12px 0">' + trades.map(t => '<li><span><b>' + esc(GI.fmtDate(t.date, { year: false, weekday: false })) + '</b> · trade with ' + (t.teams || []).filter(x => x !== led.team).map(x => GI.teamChip(x)).join(' ') + '</span><span class="gi-num">' +
      (((t.sides || []).find(s => s.team === led.team) || {}).gets || []).map(g => g.kind === 'player' ? esc(g.name) : esc(g.label || g.kind)).join(', ') + '</span></li>').join('') + '</ul>' : '') +
    (feed.length ? GI.tableHTML([{ label: 'Date', sortable: false }, { label: 'Type', sortable: false }, { label: 'Move', sortable: false }], feed.map(f => [esc(GI.fmtDate(f.date, { year: false, weekday: false })), GI.pill(TYPE[f.type] || GI.titleCase(f.type), f.type === 'reserve' || f.type === 'release' ? GI.BAD : f.type === 'trade' ? '#c95ac9' : GI.GOOD),
      { html: '<span class="gi-play-desc">' + esc(f.text) + '</span>' }]), { maxHeight: 360 }) : GI.muted('No moves in the window.')), { id: 'moves' });
}
function needsBlock(abbr, d, S) {
  if (!GI.ok(d) || !d.units) return '';
  const sw = (list, cls) => '<div class="' + cls + '"><h4>' + (cls === 's' ? 'Top strengths' : 'Top weaknesses') + '</h4>' + (list.length ? '<ul>' + list.map(z => '<li><span>' + gradeChip(z.grade) + ' <b>' + esc(GI.copyText(z.label)) + '</b><span class="gi-sub-line">' + esc(GI.copyText(z.evidence || '')) + '</span></span>' + QK.pctlChip(z.pct) + '</li>').join('') + '</ul>' : GI.muted('None stands out.')) + '</div>';
  /* the user (round 5): no potential signings on team pages; the "To improve" candidates (players they could get)
     are left out here, the grades and the strengths and weaknesses stay. Movement lives on Value & Moves. */
  const imp = [].map(w => {
    const head = '<h4 style="margin:16px 0 6px">To improve: ' + esc(GI.copyText(w.label)) + '</h4>';
    if (w.note) return head + GI.muted(esc(GI.copyText(w.note)));
    const all = (w.candidates || []).map(c => [c, false]).concat((w.unsigned || []).map(c => [c, true]));
    if (!all.length) return head + GI.muted('No player elsewhere would improve the position by our values.');
    return head + GI.tableHTML([{ label: 'Player', sortable: false }, { label: 'From' }, { label: 'Age', align: 'right' }, { label: 'Gain/g', align: 'right', title: 'Points a game this team would gain' }, { label: 'Wins', align: 'right' }, { label: 'Playoffs', align: 'right', title: 'Change in our playoff chance' }, { label: '', sortable: false }],
      all.slice(0, 8).map(x => { const c = x[0], free = x[1]; return [{ html: GI.playerLink(c.pid, c.name) + ' <span class="gi-tag">' + esc(GI.posLabel(c.pos)) + '</span>', v: c.name }, { html: free ? '<span class="qk-muted">unsigned</span>' : GI.teamChip(c.team), v: c.team || '' },
        { html: GI.num(c.age, 0), v: c.age }, { html: '<b>' + GI.signed(c.gain_pg, 2) + '</b>', v: c.gain_pg }, { html: GI.signed(c.d_wins, 2), v: c.d_wins }, { html: isNum(c.d_playoffs) ? GI.signed(100 * c.d_playoffs, 1) + ' pts' : '—', v: c.d_playoffs },
        { html: free ? '' : '<a class="gi-more" href="#/trade?t=' + abbr + ',' + esc(c.team) + '&m=' + encodeURIComponent(c.pid) + ':' + abbr + '">Simulate →</a>' }]; }));
  }).join('');
  return GI.card('Strengths and needs', esc(GI.copyText(d.label || '')) + (d.basis_season && d.basis_season !== S ? ' · on ' + d.basis_season + ' values' : '') + ' · percentiles against the 32 teams; grades A from the 80th percentile, B 60th, C 40th, D 20th',
    '<div class="gi-sn">' + sw(d.strengths || [], 's') + sw(d.weaknesses || [], 'w') + '</div>' +
    GI.grid(GI.card('', '', GI.chartBox('tp-pos', 340, 'Position grades: percentile against the league'), { span: 6, cls: 'gi-flat' }) + GI.card('', '', GI.chartBox('tp-units', 340, 'Unit grades: percentile against the league'), { span: 6, cls: 'gi-flat' })) +
    imp + '<p class="gi-cap">Positions are graded on the per-game value above replacement of the current starters (latest roster; injured reserve left out). <a href="#/value">Player value →</a> · <a href="#/trade?t=' + abbr + '">Trade simulator →</a></p>', { id: 'needs' });
}

/* Top performers (docs/_design/league.js QKL.performers): the team's best players by Gridiron Value (points above a
   replacement-level player at the position, our model; value.json), overall and by position, each ranked among the
   league's qualified players at that position (value.json q: the spec's minimums; kickers and punters left out). */
const TP_POS = [['QB', 'Quarterbacks'], ['RB', 'Running backs'], ['WR', 'Wide receivers'], ['TE', 'Tight ends'], ['EDGE', 'Outside pass rushers'], ['DL', 'Interior line'], ['LB', 'Linebackers'], ['CB', 'Cornerbacks'], ['S', 'Safeties']];
function topPerformers(abbr, vj, S) {
  if (!GI.ok(vj) || !Array.isArray(vj.rows) || !Array.isArray(vj.cols)) return null;
  const ix = {}; vj.cols.forEach((c, i) => { ix[c] = i; });
  const ok = TP_POS.map(p => p[0]);
  const all = vj.rows.map(r => ({ pid: r[ix.pid], name: r[ix.name], team: r[ix.team], pos: r[ix.pos], v: r[ix.gvar], q: r[ix.q] }))
    .filter(r => r.q && isNum(r.v) && ok.indexOf(r.pos) >= 0);
  const rankIn = list => { const sorted = list.slice().sort((a, b) => b.v - a.v), n = sorted.length, out = {};
    sorted.forEach((r, i) => { out[r.pid] = { rank: i + 1, n: n, pct: n > 1 ? Math.round(100 * (n - 1 - i) / (n - 1)) : 50 }; }); return out; };
  const byPos = {}; ok.forEach(p => { byPos[p] = rankIn(all.filter(r => r.pos === p)); });
  const overall = rankIn(all);
  const mine = all.filter(r => r.team === abbr).sort((a, b) => b.v - a.v);
  const row = (r, rk, peer) => ({ name: r.name, href: GI.playerHref(r.pid, S), pos: GI.posLabel(r.pos), value: GI.signed(r.v, 1), pct: rk.pct, rank: rk.rank, n: rk.n, peer: peer });
  const peerName = p => ((TP_POS.find(x => x[0] === p) || [])[1] || p).toLowerCase();
  return {
    kicker: 'Top performers', title: 'Who carries them, and how they compare',
    sub: 'The best players on the roster by our value model, overall and at each position, ranked against every qualified player in the league.',
    metric: { label: 'Gridiron Value', unit: 'points above replacement, season to date', model: 'Gridiron Value' },
    overall: mine.slice(0, 4).map(r => row(r, overall[r.pid], 'qualified players')),
    groups: TP_POS.map(p => ({ label: p[1], rows: mine.filter(r => r.pos === p[0]).slice(0, 2).map(r => row(r, byPos[p[0]][r.pid], peerName(p[0]))) })),
    note: 'The box is the league percentile by Gridiron Value among qualified players at the same position (the top cards: among all qualified players); the rank counts the same players. Qualified: the spec\u2019s minimums (attempts, carries or targets a team game; defenders half the team\u2019s games with a credited stat). Defensive values count only box-score splash plays, so they are a floor; offensive linemen are not valued one by one.',
    empty: 'Top performers appear once players reach the qualifying minimums.'
  };
}

GI.route('team', function (el, params) {
  const abbr = GI.canonTeam(params.id);
  const S = Number(params.season);
  const cur = S === GI.currentSeason();
  const paths = [GI.ypath('teams.json', S), GI.ypath('season.json', S), GI.ypath('fourth_downs.json', S)].concat(cur ? [GI.ypath('valuation.json', S), GI.ypath('needs/' + abbr + '.json', S), GI.ypath('ledgers/' + abbr + '.json', S)] : []);
  const vload = GI.load(GI.ypath('value.json', S)).catch(() => null);
  return GI.loadAll(paths).then(res => {
    if (!el.isConnected) return;
    const cat = GI.TM.of(res[0]);
    const rows = GI.ok(res[1]) ? GI.seasonRows(res[1]) : [];
    const x = cat && cat.teams[abbr] ? cat.teams[abbr] : null;
    const r = rows.find(z => z.team === abbr) || {};
    if (!x && !GI.NFL_TEAMS[abbr]) { el.innerHTML = GI.pageHead('Teams', 'Team not found', 'There is no team ' + esc(abbr) + '. <a href="#/teams">All teams →</a>'); return; }
    const info = GI.teamInfo(abbr);
    const v = (x || {}).values || {}, rec = (x || {}).record || {};
    const sim = Object.assign({}, (x || {}).sim || {}, r);
    const col = GI.tc(abbr);
    document.title = GI.teamName(abbr) + ' · ' + GI.SITE;
    const recTxt = GI.record(first(r.w, rec.w), first(r.l, rec.l), first(r.t, rec.t));
    const tags = [];
    if (Array.isArray(r.last5) && r.last5.length) tags.push(QK.formDots(r.last5));
    if (rec.streak || r.streak) tags.push(QK.tag('Streak ' + (r.streak || rec.streak)));
    /* The short version: the record, the rating and its rank, and what the simulation says */
    const allR = rows.filter(z => isNum(z.rating)).sort((a2, b2) => b2.rating - a2.rating);
    const rk = allR.findIndex(z => z.team === abbr) + 1;
    const nick = GI.teamShort(abbr);
    const shortTxt = (isNum(first(r.w, rec.w)) ? 'The ' + nick + ' are ' + recTxt + '. ' : '') +
      (isNum(v.rating) ? 'We rate them ' + GI.num(Math.abs(v.rating), 1) + ' points a game ' + (v.rating >= 0 ? 'better' : 'worse') + ' than an average team' + (rk ? ', ' + (rk === 1 ? 'the best in the league' : GI.ordinal(rk) + ' of 32') : '') + '. ' : '') +
      (isNum(sim.p_playoffs) ? 'Our simulations put them in the playoffs ' + (sim.p_playoffs >= 0.995 ? 'almost every time' : sim.p_playoffs < 0.005 ? 'almost never' : GI.pct(sim.p_playoffs, 0) + ' of the time') + (isNum(sim.p_sb) && sim.p_sb >= 0.01 ? ', with a ' + GI.pct(sim.p_sb, 0) + ' chance to win the Super Bowl' : '') + '.' : '');
    let h = '<nav class="gi-crumb" aria-label="Breadcrumb"><a href="#/teams">NFL teams</a><span aria-hidden="true">›</span>' + esc(info.division || '') + '<span aria-hidden="true">›</span>' + esc(GI.teamName(abbr)) + '</nav>' +
      QK.playerHeader({ name: GI.teamName(abbr), split: false, pos: info.conference || '', kicker: recTxt + ' · ' + S, face: abbr,
      team: { name: info.division || '', abbr: abbr, colour: info.colour, alt: info.alt, href: GI.standingsHref(S) },
      meta: [isNum(r.seed) ? ['Seed today', GI.ordinal(r.seed)] : null, (x || {}).coach ? '<span>Head coach <b>' + GI.coachLink(x.coach, S) + '</b></span>' : null, isNum(r.diff) ? ['Point difference', GI.signed(r.diff, 0)] : null],
      /* v4: the black strip of five numbers under the team-colour hero, then "The short version" */
      strip: [GI.kpi('Team rating', isNum(v.rating) ? GI.signed(v.rating, 1) : '—', 'points a game against an average team', { signal: true, tip: 'Our team-strength rating on a neutral field' }),
        GI.kpi('Make the playoffs', GI.pct(sim.p_playoffs, 0), 'from 20,000 simulated seasons'), GI.kpi('Win the division', GI.pct(sim.p_div, 0), ''), GI.kpi('Win the Super Bowl', GI.pct(sim.p_sb, 1), ''),
        GI.kpi('Projected wins', GI.num(sim.mean_wins, 1), isNum(sim.w_p05) ? 'likely ' + GI.num(sim.w_p05, 0) + ' to ' + GI.num(sim.w_p95, 0) : '')],
      tags: tags, short: shortTxt.trim() || null });
    h += '<nav class="qk-chips scroll" aria-label="On this page" style="margin-top:12px">' + [['#tp-season', 'How far they go'], ['#tp-top', 'Top performers'], ['#needs', 'Strengths and needs'], ['#tp-moves-host', 'Who moves next'], ['#roster', 'Roster'], ['#moves', 'Moves'], ['#tp-sched', 'Schedule'], ['#tp-profile', 'Profile'], ['#tp-4th', 'Fourth downs']]
      .map(a => '<button type="button" class="qk-chip" data-jump="' + a[0] + '">' + esc(a[1]) + '</button>').join('') + '<a class="qk-chip" href="' + GI.compareHref('t:' + abbr) + '">Compare</a></nav>';
    if (!x) h += GI.notBuilt('The ' + S + ' page for ' + GI.teamName(abbr), res[0]);
    // season path
    const stages = [['p_playoffs', 'Playoffs'], ['p_div', 'Win division'], ['p_bye', 'No. 1 seed'], ['p_conf', 'Win conference'], ['p_sb', 'Win Super Bowl']].filter(s => isNum(sim[s[0]]));
    h += '<div id="tp-season">' + GI.grid(GI.card('How far they go', 'Our chance of reaching each stage, from 20,000 simulated seasons', stages.length ? '<div id="tp-stages"></div>' : GI.muted('Our simulation chances are not available for this season.'), { span: 4 }) +
      GI.card('Final seed', 'Share of our simulated seasons', Array.isArray(sim.seed_dist) ? GI.chartBox('tp-seed', 230, 'Final seed distribution') : GI.muted('No seed distribution.'), { span: 4 }) +
      GI.card('Final wins', 'Our simulated regular-season wins' + (isNum(sim.mean_wins) ? ' · mean ' + GI.num(sim.mean_wins, 1) : ''), Array.isArray(sim.win_dist) ? GI.chartBox('tp-wins', 230, 'Final win distribution') : GI.muted('No win distribution.'), { span: 4 })) + '</div>';
    /* strengths, weaknesses and the race (docs/_design/league.js): the plain-English read, the race facts and our
       chances over the season (the percentile card stays further down, under Profile) */
    const lo = GI.leagueOpts && GI.ok(res[1]) ? GI.leagueOpts(res[1], S) : null;
    if (lo) h += '<div id="tp-league"></div>';
    h += '<div id="tp-top"></div>';
    const hist = GI.TM.history(x);
    h += GI.grid(GI.card('Ratings through the season', 'points per game against an average team, after each week', hist.length > 1 ? GI.chartBox('tp-hist', 300, 'Ratings by week') : GI.muted('Rating history starts after week 2.'), { span: 7 }) +
      GI.card('Wins against our forecast', 'Cumulative wins minus the wins our pre-game chances expected', GI.chartBox('tp-woe', 300, 'Wins over expected') +
        QK.note('Above zero, the team has won more games than our pre-game chances added up to: close wins, luck, or something we missed. Below zero, the opposite.'), { span: 5 }));
    if (cur) h += needsBlock(abbr, res[4], S) + '<div id="tp-moves-host"></div>';
    if (cur) h += GI.grid('<div class="qk-span-7">' + rosterBlock(abbr, res[3], S) + '</div><div class="qk-span-5">' + movesBlock(res[5], S) + '</div>');
    else h += GI.note('Rosters, moves and needs are kept for the current season. <a href="' + GI.teamHref(abbr) + '">' + esc(GI.teamName(abbr)) + ' now →</a>');
    // schedule
    const games = ((x || {}).schedule || []).slice().sort((a, b) => (a.week || 0) - (b.week || 0));
    h += GI.card('Schedule', 'Our pre-game win chance and projected margin for every game, and how the result compared', games.length ? '<div id="tp-sched-t"></div>' : GI.muted('No schedule for this season.'), { id: 'tp-sched', flush: true });
    // QB
    const qbs = (x || {}).qbs || [];
    if (qbs.length) h += GI.card('Quarterbacks', 'this season', GI.tableHTML([{ label: 'QB' }, { label: 'Games', align: 'right' }, { label: 'Dropbacks', align: 'right' }, { label: 'EPA/db', align: 'right' }, { label: 'Composite', align: 'right', title: '100 = average, 10 = one SD' }, { label: 'Role', sortable: false }],
      qbs.map(q => [{ html: GI.playerLink(q.pid, q.name), v: q.name }, { v: q.games }, { v: q.dropbacks }, { html: GI.signed(q.epa_db, 3), v: q.epa_db }, { html: GI.num(q.composite, 0), v: q.composite }, q.started_last ? 'Started last game' : ''])), { flush: true });
    // profile
    /* team profile: the metrics spec's team sets (overall, offence, defence) against the 32 teams (teams.json pct) */
    const tmeta = cat ? GI.metaOf(cat.metrics) : {};
    const tGroups = ['team', 'team_offence', 'team_defence'].map(id => GI.SP.BY[id]).filter(Boolean).map(g => ({ label: g.name.replace(/^Teams: /, '').replace(/^overall$/, 'Overall'),
      rows: GI.SP.headline(g).map(m => { const pv = ((x || {}).pct || {})[m[0]], vv = ((x || {}).values || {})[m[0]]; return isNum(pv) ? { label: m[1] + (m[3] ? ' ↓' : ''), pctl: pv, value: GI.fmtVal(vv, (tmeta[m[0]] || {}).fmt || '2'), tip: m[5] } : null; }).filter(Boolean) }));
    if (tGroups.some(g => g.rows.length)) h += '<div id="tp-profile" class="gi-pcols">' + QK.pctCard({ title: 'Team profile', peer: 'the 32 NFL teams', sample: (isNum(rec.w) || isNum(r.w) ? (first(r.w, rec.w) + first(r.l, rec.l) + (first(r.t, rec.t) || 0)) + ' games this season' : S + ' season') + ' · lower-is-better metrics flipped',
      groups: tGroups.map(g => ({ label: g.label.charAt(0).toUpperCase() + g.label.slice(1), rows: g.rows })), note: 'The metric set from our metrics study: the adjusted ratings first, then the per-play process numbers that predict results. Offence settles after about six games, defence after about sixteen, so early-season defensive numbers are noisy.' }) + '</div>';
    // tendencies
    const SIT = [['proe', 'All plays'], ['proe_neutral', 'Neutral'], ['proe_3rd', '3rd down'], ['proe_rz', 'Red zone'], ['proe_lead', 'Leading by 8+'], ['proe_trail', 'Trailing by 8+']].filter(s => isNum(v[s[0]]));
    const TEND = [['pa_rate', 'Play action', 'pct'], ['rpo_rate', 'RPO', 'pct'], ['motion_rate', 'Motion', 'pct'], ['screen_rate', 'Screens', 'pct'], ['shotgun', 'Shotgun', 'pct'], ['no_huddle', 'No huddle', 'pct'],
      ['sec_per_play_neutral', 'Sec per play', '1'], ['plays_pg', 'Plays per game', '1'], ['blitz_rate', 'Blitz rate (D)', 'pct'], ['man_rate', 'Man coverage (D)', 'pct']].filter(t => isNum(v[t[0]]));
    if (SIT.length || TEND.length) h += GI.grid(GI.card('Pass rate over expected', 'points above what the situation predicts; pass-heavy right', SIT.length ? GI.chartBox('tp-proe', 260, 'PROE by situation') : '', { span: 6 }) +
      GI.card('Tendencies and pace', 'rank among the 32 teams (#1 = highest)', GI.kpis(TEND.map(t => GI.kpi(t[1], GI.fmtVal(v[t[0]], t[2]), isNum(((x || {}).rank || {})[t[0]]) ? '#' + x.rank[t[0]] + ' of 32' : '')), 'gi-stats-sm'), { span: 6 }));
    h += GI.card('Fourth downs', 'every fourth down the team faced, graded · <a href="' + GI.ghref('fourth-downs', S, { team: abbr }) + '">in the fourth-down centre →</a>', '<div id="tp-4th-k"></div><div id="tp-4th-t"></div>', { id: 'tp-4th', flush: true });
    el.innerHTML = h;
    if (lo) QKL.team(el.querySelector('#tp-league'), Object.assign({}, lo, { meters: false }), abbr);
    if (window.QKL && QKL.performers) vload.then(vj => { const host = el.querySelector('#tp-top'), o = topPerformers(abbr, vj, S); if (host && el.isConnected && o) QKL.performers(host, o); });
    el.querySelectorAll('[data-jump]').forEach(a => a.addEventListener('click', () => { const n = el.querySelector(a.getAttribute('data-jump')); if (n && n.scrollIntoView) n.scrollIntoView({ behavior: 'smooth', block: 'start' }); }));

    // charts
    if (stages.length) GI.set('tp-stages', QK.chances(stages.map(s => ({ label: s[1], p: sim[s[0]], color: GI.teamColour(abbr) })), { max: 1, sort: false }));
    if (Array.isArray(sim.seed_dist)) {
      const sd = sim.seed_dist.slice(0, 7), out = Math.max(0, 1 - sd.reduce((a, b) => a + (b || 0), 0));
      GI.ch.bar('tp-seed', { cats: ['1', '2', '3', '4', '5', '6', '7', 'Out'], series: [{ name: 'Chance', data: sd.concat([out]) }], colors: sd.map(() => GI.teamColour(abbr)).concat(['#8a93a3']), fmt: v2 => GI.pct(v2, 0), labels: true, catName: 'Final seed', valName: 'Probability' });
    }
    if (Array.isArray(sim.win_dist)) GI.ch.distBars('tp-wins', sim.win_dist.map((p, k) => [k, p]), { colour: GI.teamColour(abbr), unit: 'wins', xName: 'Wins', yName: 'Chance', exp: sim.mean_wins });
    if (hist.length > 1) GI.ch.lines('tp-hist', [{ name: 'Overall', x: hist.map(z => z.week), y: hist.map(z => z.net), colour: GI.teamColour(abbr), width: 3, symbol: true }, { name: 'Offence', x: hist.map(z => z.week), y: hist.map(z => z.off), dash: true }, { name: 'Defence', x: hist.map(z => z.week), y: hist.map(z => z.def), dash: true }],
      { xName: 'Week', yName: 'Rating (pts/g v average)', yFmt: y => GI.signed(y, 1), ref: { y: 0 }, xLabel: w => 'Week ' + w });
    const done = games.filter(g => GI.isFinal(g) && isNum((g.model || {}).p_home));
    if (done.length > 1) {
      let cw = 0, ce = 0;
      const pts = done.map(g => { const home = g.home === abbr; const p = home ? g.model.p_home : 1 - g.model.p_home; const pf = home ? g.hs : g.as, pa = home ? g.as : g.hs; cw += pf > pa ? 1 : pf === pa ? 0.5 : 0; ce += p; return [g.week, cw - ce]; });
      GI.ch.lines('tp-woe', [{ name: 'Wins − expected', x: pts.map(p => p[0]), y: pts.map(p => p[1]), colour: GI.teamColour(abbr), step: true, area: true, symbol: true }], { xName: 'Week', yName: 'Wins minus expected', yFmt: y => GI.signed(y, 2), ref: { y: 0 }, legend: false, xLabel: w => 'Week ' + w });
    } else GI.ch.none('tp-woe', 'Needs two finished games.');
    if (games.length) {
      GI.set('tp-sched-t', GI.tableHTML([{ label: 'Wk', align: 'right' }, { label: 'Opponent' }, { label: 'Our chance', align: 'right', title: 'Our pre-game win chance' }, { label: 'Projected', align: 'right', title: 'Our projected margin for this team, points' }, { label: 'Result' }, { label: 'v ours', align: 'right', title: 'The actual margin minus our projected margin, points' }],
        games.map(g => { const home = g.home === abbr, opp = home ? g.away : g.home, m = g.model || {};
          const p = isNum(m.p_home) ? (home ? m.p_home : 1 - m.p_home) : null;
          const msp = isNum(GI.homeLine(m)) ? (home ? GI.homeLine(m) : -GI.homeLine(m)) : null;
          const fin = GI.isFinal(g) && isNum(g.hs);
          const pf = home ? g.hs : g.as, pa = home ? g.as : g.hs;
          const vs = fin && isNum(msp) ? (pf - pa) + msp : null;
          return { _href: GI.gameHref(g.game_id), cells: [g.week, { html: (home ? 'v ' : '@ ') + GI.teamLink(opp, { short: true, season: S }), v: opp }, { html: p === null ? '—' : GI.probBar(p, GI.tc(abbr)), v: p },
            { html: isNum(msp) ? GI.signed(-msp, 1) : '—', v: isNum(msp) ? -msp : null },
            { html: fin ? '<a class="gi-link" href="' + GI.gameHref(g.game_id) + '">' + (pf > pa ? 'W' : pf < pa ? 'L' : 'T') + ' ' + pf + '–' + pa + '</a>' : '<a class="gi-link" href="' + GI.gameHref(g.game_id) + '">' + esc(GI.fmtDate(g.kickoff, { year: false })) + '</a>', v: g.week },
            { html: isNum(vs) ? GI.ptsEdge(vs, 1) : '', v: vs }] }; })));
    }
    if (SIT.length) GI.ch.bar('tp-proe', { cats: SIT.map(s => s[1]), series: [{ name: 'PROE (pts)', data: SIT.map(s => Math.round(v[s[0]] * 1000) / 10) }], horizontal: true, diverging: true, labels: true, fmt: y => GI.signed(y, 1), labelWidth: 100 });
    // needs charts
    const nd = cur ? res[4] : null;
    if (GI.ok(nd) && nd.positions) {
      const pos = nd.positions.filter(p => isNum(p.pct));
      GI.ch.bar('tp-pos', { cats: pos.map(p => GI.copyText(p.label) + ' (' + p.grade + ')'), series: [{ name: 'Percentile', data: pos.map(p => p.pct) }], horizontal: true, labels: true, max: 100, colors: pos.map(p => QK.pctHex(p.pct)), fmt: y => GI.ordinal(y), labelWidth: 150, valName: 'Percentile v the 32 teams', label: 'Position grades' });
      const un = (nd.units || []).filter(u => isNum(u.pct));
      GI.ch.bar('tp-units', { cats: un.map(u => u.label.replace(/ \(.*\)$/, '') + ' (' + u.grade + ')'), series: [{ name: 'Percentile', data: un.map(u => u.pct) }], horizontal: true, labels: true, max: 100, colors: un.map(u => QK.pctHex(u.pct)), fmt: y => GI.ordinal(y), labelWidth: 150, valName: 'Percentile v the 32 teams', label: 'Unit grades' });
    }
    // fourth downs
    const plays = GI.F ? GI.F.playsOf(res[2]).filter(p => p.team === abbr) : [];
    const go = plays.filter(p => p.choice === 'go').length;
    /* who moves next: the movement payload, after the first paint (current season only) */
    if (cur && GI.MV) GI.MV.load().then(md => { const host = document.getElementById('tp-moves-host'); if (!host || !el.isConnected) return; host.innerHTML = GI.MV.teamSection(md && Object.assign({}, md, { published: Object.assign({}, md.published || {}, { targets: false }) }), abbr, GI.ok(res[4]) ? res[4] : null); GI.sortable(host); });
    GI.set('tp-4th-k', plays.length ? '<div style="padding:14px 16px 0">' + GI.kpis([GI.kpi('Fourth downs', String(plays.length), 'this season'), GI.kpi('Went for it', GI.pct(go / plays.length, 0), go + ' times'),
      isNum(v.go_rate_rec) ? GI.kpi('Went when our model said go', GI.pct(v.go_rate_rec, 0), '') : '', isNum(v.fd_wp_lost) ? GI.kpi('Win chance given away', GI.num(v.fd_wp_lost * 100, 1), 'percentage points, summed', { unit: 'pts' }) : '']) + '</div>' : '');
    if (plays.length) GI.F.table(document.getElementById('tp-4th-t'), plays, S, { team: false, max: 80, maxHeight: 420 });
    else GI.set('tp-4th-t', GI.muted('No fourth downs for this team yet.'));
    GI.sortable(el);
  });
});

})(window.GI);
