/* The Quant Hardwood — Games (#/<L>/games[/<date>]) and the game centre (#/<L>/game/<gid>), on kit v4 "Broadcast"
 * (the Rink games and game pages are the reference, MIGRATION_V4.md).
 *
 * Games: a strip of game days around the chosen one, a date picker and month jump, the day's games as game cards
 * (our chance, a one-line reason, no market), our chance for every home side (the market a quiet ring: game detail
 * only), and how our forecasts did on the day's finished games.
 * Game centre (Summary tab): the QK.previewCard diagonal hero (away "at" home with records, the clock when live, our
 * chance for the favourite with a how-sure note, the match-up factors, the market as a quiet labelled line before
 * tip-off) with stat tiles and our forecast table beside it; then the line score, what goes into our forecast,
 * availability before tip-off (the injury report and each team's availability term), the tale of the tape, win
 * chance through the game, the margin flow, both teams' shot charts on the half court, four factors, game awards and
 * the box score.
 * Detail tab (?tab=detail): the full pre-redesign game centre (lineups, rotations, key plays, shot modes).
 * Data: <L>/<S>/games/<gid>.json, <L>/<S>/schedule.json, <L>/<S>/season.json (records, the tale of the tape),
 * teams.json logs, index.json cards (game.js helpers). */
(function (HW) {
'use strict';

const U = HW.ui, esc = HW.esc, isNum = HW.isNum;
const GC = () => HW.gameCentre;

// ── games list ─────────────────────────────────────────────────────────────

function renderGames(el, params) {
  const L = U.L(params), S = U.S(params);
  el.innerHTML = U.secHead('Games', 'Every game with our win chance; tap a game for the game centre.', null, null, U.kicker(L, S)) + QK.skeleton('card', 6);
  return Promise.all([GC().seasonGames(L, S), HW.load(HW.path('season.json', L, S))]).then(res => {
    if (!U.alive(el)) return;
    const list = res[0] || [], recs = U.records(U.ok(res[1]) ? res[1] : null);
    const byDay = {};
    list.forEach(g => { const d = HW.localDay(g.date); (byDay[d] || (byDay[d] = [])).push(g); });
    const days = Object.keys(byDay).sort();
    if (!days.length) { el.innerHTML = U.secHead('Games', '', null, null, U.kicker(L, S)) + U.empty('No games yet', 'The schedule for this season has not been published.'); return; }
    const todayStr = HW.localDay(new Date().toISOString());
    let day = params.date && byDay[params.date] ? params.date : null;
    if (!day && params.date) day = days.find(d => d >= params.date) || days[days.length - 1];
    if (!day) day = days.find(d => d >= todayStr) || days[days.length - 1];
    const i = days.indexOf(day);
    const strip = days.slice(Math.max(0, i - 6), i + 7);
    const games = byDay[day].slice().sort((a, b) => String(a.date).localeCompare(String(b.date)));
    const pre = games.filter(g => HW.gameState(g) === 'pre');
    const fin = games.filter(g => HW.gameState(g) === 'post');
    const months = {};
    days.forEach(x => { const m = x.slice(0, 7); if (!months[m]) months[m] = x; });
    const dl = d => HW.href(L, 'games/' + d, S);
    let h = U.secHead('Games', HW.leagueName(L) + ' ' + esc(HW.seasonLabel(L, S)) + ' · ' + list.length + ' games. Every card has our chance for each side and a line on why it’s worth a look; tap one for the game centre.', null, null, U.kicker(L, S));
    h += '<div class="hw-flex" style="margin-bottom:12px">' + (days[i - 1] ? '<a class="qk-btn" href="' + esc(dl(days[i - 1])) + '" aria-label="Previous game day">←</a>' : '') +
      '<nav class="hw-strip" aria-label="Game days">' + strip.map(d => '<a href="' + esc(dl(d)) + '"' + (d === day ? ' aria-current="page"' : '') + '><span>' + esc(HW.fmtDate(d, { year: false }).split(' ')[0]) + '</span><b>' + esc(d.slice(8)) + '</b><span class="n">' + byDay[d].length + '</span></a>').join('') + '</nav>' +
      (days[i + 1] ? '<a class="qk-btn" href="' + esc(dl(days[i + 1])) + '" aria-label="Next game day">→</a>' : '') +
      '<input type="date" class="qk-input" id="gl-date" aria-label="Pick a date" value="' + esc(day) + '" min="' + esc(days[0]) + '" max="' + esc(days[days.length - 1]) + '">' +
      '<select class="qk-select" id="gl-month" aria-label="Jump to month"><option value="">Jump to month…</option>' + Object.keys(months).map(m => '<option value="' + months[m] + '">' + esc(HW.fmtDate(m + '-15', { weekday: false }).replace(/^\d+ /, '')) + '</option>').join('') + '</select></div>';
    h += '<div class="hw-day"><b>' + esc(HW.fmtDate(day)) + '</b> · ' + games.length + ' game' + (games.length === 1 ? '' : 's') + '</div><div class="qk-watch">' + games.map(g => U.card(g, L, { season: S, records: recs, why: true })).join('') + '</div>';
    /* round 6: the market sits quietly on each card; the day's results list our pre-game call, with no scorecard (our
       record lives on the Model page's "How we're doing" tab) */
    if (fin.length) {
      h += '<div class="qk-grid hw-sec">' + U.card2('Results of the day', 'The final score and our pre-game call', '<ul class="hw-list">' + fin.map(g => {
        const p = (g.model || {}).p_home;
        const fav = isNum(p) ? (p >= 0.5 ? g.home : g.away) : null, pf = isNum(p) ? Math.max(p, 1 - p) : null;
        return '<li><a class="hw-ent" href="' + esc(HW.gameHref(L, g.id, S)) + '"><span class="nm">' + esc(HW.teamAbbr(L, g.away) + ' ' + g.as + ' – ' + g.hs + ' ' + HW.teamAbbr(L, g.home)) + '</span></a>' +
          '<span class="s">' + (fav ? 'ours before the tip: ' + esc(HW.teamAbbr(L, fav)) + ' ' + U.pct(pf) : '') + '</span></li>';
      }).join('') + '</ul>', { cls: 'qk-span-12', flush: true }) + '</div>';
    }
    el.innerHTML = h;
    const go = v => { if (v) HW.go(dl(v)); };
    document.getElementById('gl-date').addEventListener('change', e => go(e.target.value));
    document.getElementById('gl-month').addEventListener('change', e => go(e.target.value));
    const cur = el.querySelector('.hw-strip a[aria-current]');
    if (cur && cur.scrollIntoView) { try { cur.scrollIntoView({ inline: 'center', block: 'nearest' }); } catch (e) { /* old */ } }
    HW.setMeta('');
  });
}

// ── game centre ────────────────────────────────────────────────────────────

const PERIOD_S = L => (L === 'wnba' ? 600 : 720);
const srcLabel = src => U.srcLabel(src);
/* Standard normal CDF (Abramowitz and Stegun 7.1.26): our margin forecast is normal with the model's sd. */
function phi(z) {
  const t = 1 / (1 + 0.3275911 * Math.abs(z) / Math.SQRT2);
  const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-z * z / 2);
  return z >= 0 ? (1 + y) / 2 : (1 - y) / 2;
}
function tLabel(L, t) {
  const n = PERIOD_S(L), reg = 4 * n;
  if (t < reg) { const p = Math.floor(t / n) + 1; const left = n - (t - (p - 1) * n); return 'Q' + p + ' ' + Math.floor(left / 60) + ':' + ('0' + Math.round(left % 60)).slice(-2); }
  const o = Math.floor((t - reg) / 300) + 1; const left = 300 - (t - reg - (o - 1) * 300);
  return 'OT' + (o > 1 ? o : '') + ' ' + Math.floor(left / 60) + ':' + ('0' + Math.round(left % 60)).slice(-2);
}
function minutesOf(v) { return isNum(v) ? (Number(v) > 70 ? Number(v) / 60 : Number(v)) : null; }

function boxRows(L, g, tid) {
  const b = (g.box || {})[tid];
  if (!b || !(b.players || []).length) return null;
  return b.players.slice().sort((a, x) => ((x.starter ? 1 : 0) - (a.starter ? 1 : 0)) || ((minutesOf(x.min) || 0) - (minutesOf(a.min) || 0)))
    .map(p => Object.assign({}, p, { mins: minutesOf(p.min), fg: p.fgm, tp: p.tpm, ft: p.ftm, wpa100: isNum(p.wpa) ? p.wpa * (Math.abs(p.wpa) <= 1 ? 100 : 1) : null }));
}
function boxTable(node, L, g, tid, S) {
  const rows = boxRows(L, g, tid);
  if (!rows) { node.innerHTML = U.empty('No box score', 'This game has no box score yet.'); return; }
  const has = k => rows.some(p => isNum(p[k]));
  const cols = [
    { key: 'name', label: 'Player', sticky: true, fmt: (v, p) => U.playerEnt(L, p.id, p.name, null, (p.starter ? 'S · ' : '') + (p.pos || ''), S) },
    { key: 'mins', label: 'Min', num: true, fmt: v => (isNum(v) ? HW.fmtMin(v) : '—') },
    { key: 'pts', label: 'Pts', num: true, fmt: v => '<b>' + (isNum(v) ? v : '—') + '</b>' },
    { key: 'reb', label: 'Reb', num: true }, { key: 'ast', label: 'Ast', num: true }, { key: 'stl', label: 'Stl', num: true }, { key: 'blk', label: 'Blk', num: true }, { key: 'tov', label: 'TO', num: true },
    { key: 'fg', label: 'FG', num: true, fmt: (v, p) => (isNum(p.fga) ? p.fgm + '-' + p.fga : '—') },
    { key: 'tp', label: '3P', num: true, fmt: (v, p) => (isNum(p.tpa) ? p.tpm + '-' + p.tpa : '—') },
    { key: 'ft', label: 'FT', num: true, fmt: (v, p) => (isNum(p.fta) ? p.ftm + '-' + p.fta : '—') },
    { key: 'pm', label: '+/-', num: true, fmt: v => U.sgnHTML(v, 0) }
  ];
  if (has('ts')) cols.push({ key: 'ts', label: 'TS%', num: true, fmt: v => HW.fmtVal(v, 'pct'), tip: 'True shooting' });
  if (has('game_score')) cols.push({ key: 'game_score', label: 'GmSc', num: true, fmt: v => U.f(v, 1), tip: 'Game score (Hollinger)' });
  if (has('wpa')) cols.push({ key: 'wpa100', label: 'WPA', num: true, fmt: v => U.sgnHTML(v, 1), tip: 'Win probability added, percentage points (own team)' });
  if (has('pox')) cols.push({ key: 'pox', label: 'POX', num: true, fmt: v => U.sgnHTML(v, 1), tip: 'Points over expected on the player\'s shots' });
  QK.table(node, { columns: cols, rows: rows, dense: true });
}

/* v4 (Broadcast) hero: QK.previewCard, the diagonal split — away "at" home with records, the clock when live, our
   chance for the favourite, a plain-English note (the margin and total we expect), the market as a quiet reference
   line before tip-off (game detail is one of the two places it may appear), and how the teams match up. The hero
   takes the raw kit colours, the alternates and the full names (QK.color.blockPair makes them blocks with white type
   and resolves a clash; the city line comes from the full name); the charts keep the lifted pair [ca, ch]. */
function headHTML(L, g, S, season) {
  const st = U.status(g);
  const fin = st === 'final', live = st === 'live', pre = st === 'pre';
  const pc = U.pair(L, g.away, g.home), ca = pc[0], ch = pc[1];
  /* the market: the game file's pre-game market, else the scoreboard card's (index.json), which a game file built
     earlier may lack */
  const card = ((HW.leagueInfo(L) || {}).today || []).concat((HW.leagueInfo(L) || {}).next_games || []).filter(c => String(c.id) === String(g.id))[0];
  const m = (g.pregame || {}).model || {}, mk = (g.pregame || {}).market || (card && card.market) || {};
  const wpl = ((g.wp || {}).model || []);
  const pLive = live && wpl.length ? wpl[wpl.length - 1][1] : null;
  const recs = U.records(season);
  const rec = t => recs[String(t)] || '';
  const A = Object.assign(U.team(L, g.away), { colour: HW.teamColourRaw(L, g.away) || ca, record: rec(g.away) }), H = Object.assign(U.team(L, g.home), { colour: HW.teamColourRaw(L, g.home) || ch, record: rec(g.home) });
  const tag = g.series && (g.series.summary || g.series.round) ? (g.series.summary || g.series.round) + (g.series.game ? ' · Game ' + g.series.game : '') : (g.stype && g.stype !== 'reg' ? HW.stypeLabel(g.stype) : '');
  /* round 6: the market's chance sits quietly under the hero (market: 'quiet'), the source on hover */
  const G0 = { market_home: pre && isNum(mk.p_home) ? Number(mk.p_home) : null, market_src: srcLabel(mk.sources), sport: 'basketball', id: g.id, start: g.date, status: st, league: HW.leagueName(L) + (tag ? ' · ' + tag : ''), home: H, away: A,
    hs: isNum(g.hs) ? Number(g.hs) : null, as: isNum(g.as) ? Number(g.as) : null,
    p_home: live && isNum(pLive) ? Number(pLive) : (isNum(m.p_home) ? Number(m.p_home) : null), wp_home: live && isNum(pLive) ? Number(pLive) : null,
    p_pre: live && isNum(m.p_home) ? Number(m.p_home) : null, pre_only: live && !isNum(pLive) ? true : undefined,
    period: isNum(g.period) ? Number(g.period) : (isNum(g.periods) ? Number(g.periods) : null), clock: g.clock, note: fin && Number(g.periods) > 4 ? 'OT' : '' };
  const G = QK.settle ? QK.settle(G0) : G0;
  if (G.status === 'awaiting') G.market_home = null;
  const R = (season && season.ratings) || {};
  const ra = R[String(g.away)] || {}, rh = R[String(g.home)] || {};
  const fx = [];
  const add = (label, a, b, f, low) => { if (isNum(a) && isNum(b)) fx.push({ label: label, a: f(a), b: f(b), better: Math.abs(a - b) < 1e-9 ? null : ((a > b) !== !!low ? 'a' : 'b') }); };
  add('Net rating, per 100 trips', ra.net, rh.net, v => U.signed(v, 1));
  add('Points scored per 100', ra.off, rh.off, v => U.f(v, 1));
  add('Points allowed per 100', ra.def, rh.def, v => U.f(v, 1), true);
  const extra = [];
  if (pre && isNum(m.margin)) extra.push('we expect ' + esc(HW.teamAbbr(L, m.margin >= 0 ? g.home : g.away)) + ' by about ' + Math.max(1, Math.round(Math.abs(m.margin))) + (isNum(m.sd) ? ', give or take ' + Math.round(m.sd) + ' points' : ''));
  if (pre && isNum(m.total)) extra.push('about ' + Math.round(m.total) + ' points in all');
  const venue = g.venue ? (typeof g.venue === 'object' ? g.venue.name : g.venue) : '';
  const meta = [HW.fmtDate(g.date, { time: true }), g.venue && typeof g.venue === 'object' && g.venue.city ? [g.venue.name, g.venue.city].filter(Boolean).join(', ') : '',
    isNum(g.attendance) && g.attendance > 0 ? Number(g.attendance).toLocaleString('en-GB') + ' fans' : ''].filter(Boolean);
  return '<div class="hw-preview">' + QK.previewCard(G, { kicker: tag ? (tag.indexOf(HW.leagueName(L)) === 0 ? tag : HW.leagueName(L) + ' · ' + tag) : HW.leagueName(L) + (venue ? ' · ' + venue : ''), nick: t => U.nick(L, t === A ? g.away : g.home), colors: [ca, ch], factors: fx,
    factorsTitle: 'How they match up this season', noteExtra: extra.length ? 'This time ' + extra.join(', and ') + '.' : '',
    market: 'quiet' }) +
    '<div class="hw-hero-meta">' + meta.map(x => '<span>' + esc(x) + '</span>').join('') + '</div></div>';
}

function pregameKpis(L, g) {
  const pre = g.pregame || {}, m = pre.model || {};
  const st = U.status(g);
  const out = [];
  const H = HW.teamAbbr(L, g.home), A = HW.teamAbbr(L, g.away);
  if (isNum(m.p_home)) {
    const fav = m.p_home >= 0.5 ? H : A;
    out.push({ label: st === 'pre' ? 'Our win chance' : 'Our pre-game call', value: fav + ' ' + U.pct(Math.max(m.p_home, 1 - m.p_home)), signal: true, sub: 'our pre-game model, overtime included', tip: 'Our pre-game chance that the favourite wins' });
  }
  if (st === 'live') {
    const wpl = ((g.wp || {}).model || []);
    const p = wpl.length ? wpl[wpl.length - 1][1] : null;
    if (isNum(p)) out.push({ label: 'Live win chance', value: (p >= 0.5 ? H : A) + ' ' + U.pct(Math.max(p, 1 - p)), signal: true, sub: 'our live model, every possession' });
  }
  if (isNum(m.margin)) out.push({ label: 'Projected margin', value: (m.margin >= 0 ? H : A) + ' by ' + U.f(Math.abs(m.margin), 1), sub: isNum(m.sd) ? '± ' + U.f(m.sd, 1) + ' points (one standard deviation)' : '', tip: 'Our expected winning margin; games vary around it by the standard deviation shown' });
  if (isNum(m.total)) out.push({ label: 'Projected total', value: U.f(m.total, 1), unit: 'pts', sub: isNum(m.pts_home) ? A + ' ' + U.f(m.pts_away, 0) + ' · ' + H + ' ' + U.f(m.pts_home, 0) : '' });
  if (isNum(pre.elo_p_home)) out.push({ label: 'Elo alone', value: (pre.elo_p_home >= 0.5 ? H : A) + ' ' + U.pct(Math.max(pre.elo_p_home, 1 - pre.elo_p_home)), sub: 'a simpler rating, for comparison', tip: 'The win chance from our Elo ratings alone (results only, no box score or availability)' });
  return out.length ? '<div class="hw-kpis">' + QK.stats(out) + '</div>' : '';
}

/* Our pre-game forecast with the market as a quiet reference column (game detail is one of the two places it may appear). */
function forecastTable(L, g) {
  const pre = g.pregame || {}, m = pre.model || {}, mk = pre.market || {};
  if (!isNum(m.p_home)) return '';
  const H = HW.teamAbbr(L, g.home), A = HW.teamAbbr(L, g.away);
  const by = (t, n) => (isNum(m.margin) && isNum(m.sd) && m.sd > 0 ? U.pct(t === 'h' ? 1 - phi((n - 0.5 - m.margin) / m.sd) : phi((-(n - 0.5) - m.margin) / m.sd)) : '—');
  const mkSp = isNum(mk.spread_home) ? (mk.spread_home <= 0 ? H + ' by ' + U.f(-mk.spread_home, 1) : A + ' by ' + U.f(mk.spread_home, 1)) : '';
  const rows = [
    ['Win (overtime included)', H + ' ' + U.pct(m.p_home) + ' · ' + A + ' ' + U.pct(1 - m.p_home), isNum(mk.p_home) ? H + ' ' + U.pct(mk.p_home) : '—'],
    ['Projected margin', isNum(m.margin) ? (m.margin >= 0 ? H : A) + ' by ' + U.f(Math.abs(m.margin), 1) + (isNum(m.sd) ? ' (± ' + U.f(m.sd, 1) + ')' : '') : '—', mkSp || '—'],
    [H + ' wins by 6 or more', by('h', 6), ''],
    [A + ' wins by 6 or more', by('a', 6), ''],
    ['Total points', isNum(m.total) ? U.f(m.total, 1) + ' expected' : '—', isNum(mk.total) ? U.f(mk.total, 1) : '—'],
    ['Projected score', isNum(m.pts_home) ? A + ' ' + U.f(m.pts_away, 0) + ' – ' + U.f(m.pts_home, 0) + ' ' + H : '—', '']
  ];
  return '<div class="qk-table-wrap"><table class="qk-table dense"><thead><tr><th>Question</th><th>Our forecast</th><th><span data-tip="The prediction-market or sportsbook number with the margin removed, shown as a reference">Market (' + esc(srcLabel(mk.sources)) + ')</span></th></tr></thead><tbody>' +
    rows.map(r => '<tr><td>' + esc(r[0]) + '</td><td class="num" style="text-align:left;color:var(--ink-1);font-weight:600">' + esc(r[1]) + '</td><td class="num qk-muted" style="text-align:left">' + esc(r[2]) + '</td></tr>').join('') + '</tbody></table></div>';
}

/* Tale of the tape: the two teams' season profile (season.json ratings and standings). */
function tape(L, g, season) {
  const R = (season && season.ratings) || {};
  const a = R[String(g.away)] || {}, h = R[String(g.home)] || {};
  const st = {}; const sd = (season && season.standings) || {};
  Object.keys(sd).forEach(c => (sd[c] || []).forEach(r => { st[String(r.team)] = r; }));
  const sa = st[String(g.away)] || {}, sh = st[String(g.home)] || {};
  const rows = [
    { label: 'Net rating (per 100 possessions)', a: a.net, b: h.net, fmt: v => U.signed(v, 1), tip: 'Our opponent-adjusted net rating: points per 100 possessions better than an average team' },
    { label: 'Offensive rating', a: a.off, b: h.off, fmt: v => U.f(v, 1), tip: 'Points scored per 100 possessions, opponent-adjusted' },
    { label: 'Defensive rating', a: a.def, b: h.def, fmt: v => U.f(v, 1), better: 'low', tip: 'Points allowed per 100 possessions, opponent-adjusted (lower is better)' },
    { label: 'Win %', a: sa.w + sa.l > 0 ? sa.pct : null, b: sh.w + sh.l > 0 ? sh.pct : null, fmt: v => U.pct(v, 1) },
    { label: 'Point differential', a: sa.w + sa.l > 0 ? sa.pd : null, b: sh.w + sh.l > 0 ? sh.pd : null, fmt: v => U.signed(v, 0) }
  ];
  if (!rows.some(r => isNum(r.a) && isNum(r.b))) return '';
  const pc = U.pair(L, g.away, g.home);
  /* v4: the tape's blocks take the raw kits (and alternates); its bars the lifted, distinct chart pair */
  const A = U.team(L, g.away), H = U.team(L, g.home);
  return QK.matchupBar({ left: A, right: H, rows: rows, colors: pc });
}

// Pre-game availability: ESPN's injury report as of the last fetch before tip-off, and (NBA informed model) each
// team's availability term in points of its own margin. Out = counted as not playing; Day-To-Day and the rest keep
// the rate implied by recent games played.
function availabilityHTML(L, g, S) {
  const pre = g.pregame || {}, inj = pre.injuries || {}, m = pre.model || {}, det = m.detail || {};
  const H = String(g.home), A = String(g.away);
  const informed = m.model === 'informed' && isNum(det.injury_home) && isNum(det.injury_away);
  const own = { };
  if (informed) { own[H] = det.injury_home; own[A] = -det.injury_away; }
  const listed = [A, H].filter(t => (inj[t] || []).length);
  if (!listed.length && !informed) return '';
  const order = s => { const x = String(s || '').toLowerCase(); return x === 'out' ? 0 : x.indexOf('day') === 0 || x === 'questionable' ? 1 : 2; };
  const block = t => {
    const rows = (inj[t] || []).slice().sort((x, y) => order(x.status) - order(y.status) || (isNum(y.impact) ? y.impact : -1) - (isNum(x.impact) ? x.impact : -1));
    const head = '<div class="hw-av-head">' + U.teamEnt(L, t, { season: S }) + (informed ? '<span class="v" data-tip="Points of ' + esc(HW.teamAbbr(L, t)) + ' margin from who is expected to play, against what its rating already reflects">' + U.sgnHTML(own[t], 1) + ' pts</span>' : '') + '</div>';
    const items = rows.map(r => {
      const o = order(r.status) === 0;
      return '<li><div class="hw-av-p">' + U.playerEnt(L, r.player, r.name, null, null, S) + (r.detail ? '<div class="s">' + esc(r.detail) + '</div>' : '') + '</div>' +
        '<span class="hw-inj' + (o ? '' : ' q') + '">' + esc(r.status || '—') + '</span>' +
        '<span class="v" data-tip="Points per 100 possessions the team loses without the player (projected rate above replacement x minutes)">' + (isNum(r.impact) ? U.f(r.impact, 1) : '—') + '</span></li>';
    });
    return '<div>' + head + (items.length ? '<ul class="hw-list">' + items.join('') + '</ul>' : '<p class="hw-quiet" style="padding:8px 16px">Nobody listed.</p>') + '</div>';
  };
  const st = U.status(g);
  const sub = (st === 'pre' ? 'ESPN’s injury report, updated every run until tip-off.' : 'ESPN’s injury report as last fetched for this game.') +
    ' The model counts players listed Out as not playing; Day-To-Day players keep the rate their recent games imply.' +
    (informed ? ' Each team’s figure is its availability term: points of its own margin from the expected rotation against what its rating already reflects (net ' + U.signed(det.injury, 1) + ' for ' + esc(HW.teamAbbr(L, H)) + ').' : '') +
    ' The right-hand column is the points per 100 possessions each player is worth to the team.';
  return U.card2('Availability before tip-off', sub, '<div class="grid-2 hw-av">' + [A, H].map(block).join('') + '</div>', { flush: true, cls: 'qk-span-12' });
}

function awardsHTML(L, g, S) {
  const a = g.awards || {};
  const defs = [['player_of_game', 'Player of the game'], ['biggest_swing', 'Biggest swing'], ['shot_maker', 'Shot maker'], ['stopper', 'Stopper'], ['unluckiest', 'Unluckiest']];
  const items = defs.filter(d => a[d[0]] && (a[d[0]].player || a[d[0]].team)).map(d => {
    const x = a[d[0]];
    return '<li class="hw-pick"><div style="min-width:0"><div class="qk-kicker">' + esc(d[1]) + '</div><div>' + (x.player ? U.playerEnt(L, x.player, null, x.team, null, S) : U.teamEnt(L, x.team, { season: S })) + '</div>' +
      (x.why ? '<div class="why">' + esc(x.why) + '</div>' : '') + '</div></li>';
  });
  const extra = [];
  if (isNum(a.excitement)) extra.push('Excitement <b>' + U.f(a.excitement, 1) + '</b> / 10');
  if (isNum(a.comeback)) extra.push('The winner was down to <b>' + U.pct(a.comeback) + '</b> win probability');
  if (!items.length && !extra.length) return '';
  return U.card2('Game awards', extra.join(' · '), '<ul class="hw-list">' + items.join('') + '</ul>', { flush: true, cls: 'qk-span-5' });
}

/* round 9: a game file is rebuilt only inside the build window, so a finished game can still say "pre" (or "in") in its
   own file. The season's schedule.json (rebuilt every run) wins for the status and the score, and fills the
   pre-game market and model when the game file has none; a game the data still calls upcoming hours after its start
   reads "Result to come" (QK.settle), never a pre-game hero. */
function withSchedule(g, sch) {
  const row = sch ? (sch.games || []).find(x => String(x.id) === String(g.id)) : null;
  if (!row) return g;
  const out = Object.assign({}, g);
  if (row.status === 'post' && g.status !== 'post' && isNum(row.hs) && isNum(row.as)) {
    out.status = 'post'; out.hs = row.hs; out.as = row.as;
    if (isNum(row.period)) out.periods = row.period;
    out.clock = null;
  }
  const pre = Object.assign({}, g.pregame || {});
  if (!pre.market && row.market) pre.market = row.market;
  if (!(pre.model && isNum(pre.model.p_home)) && row.model && isNum(row.model.p_home)) pre.model = Object.assign({}, row.model);
  out.pregame = pre;
  if (!out.series && row.series) out.series = row.series;
  return out;
}

function renderGame(el, params) {
  const L = U.L(params), gid = params.id;
  const tab = U.tab(params, ['summary', 'detail'], 'summary');
  el.innerHTML = QK.skeleton('lines', 6);
  return GC().loadGame(L, params.season, gid).then(res => (res && U.ok(res.d) ? Promise.all([HW.load(HW.path('season.json', L, res.s)), HW.load(HW.path('schedule.json', L, res.s))]).then(a => {
    res.season = U.ok(a[0]) ? a[0] : null;
    res.d = withSchedule(res.d, U.ok(a[1]) ? a[1] : null);
    return res;
  }) : res)).then(res => {
    if (!U.alive(el)) return;
    if (!res || !U.ok(res.d)) { el.innerHTML = U.secHead('Game', '', null, null, U.kicker(L, U.S(params))) + U.empty('Game not available', 'This game page has not been built yet.') + '<p>' + U.link(HW.href(L, 'games'), 'All games') + '</p>'; return; }
    const g = res.d, S = res.s;
    if (S !== HW.state.season) HW.state.season = S;
    const st = U.status(g);
    const H = String(g.home), A = String(g.away);
    document.title = HW.teamAbbr(L, A) + ' @ ' + HW.teamAbbr(L, H) + ' · ' + HW.leagueName(L) + ' · The Quant Hardwood';
    const tabs = [{ key: 'summary', label: 'Summary', href: HW.gameHref(L, gid, S) }, { key: 'detail', label: 'Lineups, rotations and plays', href: HW.gameHref(L, gid, S) + (HW.sq(L, S) ? '&' : '?') + 'tab=detail' }];
    const fc = forecastTable(L, g);
    let h = '<nav class="hw-crumb" aria-label="Breadcrumb"><a href="' + esc(HW.href(L, 'games/' + HW.localDay(g.date), S)) + '">← ' + esc(HW.fmtDate(g.date, { year: false })) + ' games</a></nav>' +
      '<div class="hw-gtop">' + headHTML(L, g, S, res.season) + '<div class="hw-gside hw-stack2">' + pregameKpis(L, g) +
      (fc ? U.card2(st === 'pre' ? 'Our forecast' : 'Our pre-game forecast', 'Chances from our game model; the market column is a reference, not our forecast', fc, { flush: true }) : '') + '</div></div>' +
      '<div style="margin-top:var(--sp-6)">' + U.tabsHTML(tabs, tab) + '</div>';
    if (tab === 'detail') {
      el.innerHTML = h + '<div class="hw-sub"></div>';
      return U.legacy('game', el.querySelector('.hw-sub'), params, null, { embed: 'detail' });
    }
    const ln = g.line || {};
    const la = ln.away || [], lh = ln.home || [];
    const hasBox = Object.keys(g.box || {}).some(t => ((g.box[t] || {}).players || []).length);
    const shots = g.shots && g.shots.rows ? U.rowsOf(g.shots) : [];
    const det = ((g.pregame || {}).model || {}).detail || {};
    const parts = ['rating', 'hca', 'rest', 'b2b', 'travel', 'tz', 'altitude', 'injury'].filter(k => isNum(det[k]) && Math.abs(det[k]) > 0.05);
    h += '<div class="qk-grid hw-sec">';
    if (la.length || lh.length) {
      h += U.card2('Line score', '', '<div id="gm-ls"></div>', { cls: 'qk-span-' + (parts.length ? '7' : '12'), flush: true });
    }
    if (parts.length) h += U.card2('What goes into our forecast', 'Points of ' + esc(HW.teamAbbr(L, H)) + ' margin from each part', U.chart('gm-parts', 30 * parts.length + 60, 'What goes into our forecast'), { cls: 'qk-span-' + (la.length || lh.length ? '5' : '12') });
    if (g.wp && (g.wp.model || []).length) h += U.card2('Win chance through the game', 'Our live model for ' + esc(HW.teamName(L, H)) + ' after every possession; the numbered dots are the biggest swings' + ((g.wp.espn || []).length ? ' (ESPN’s own number dotted)' : ''), U.chart('gm-wp', 300, 'Win chance through the game'), { cls: 'qk-span-12' });
    if (g.flow && g.flow.length) h += U.card2('Margin', esc(HW.teamAbbr(L, H)) + ' lead through the game', U.chart('gm-flow', 220, 'Margin flow'), { cls: 'qk-span-7' });
    const ff = g.four_factors || {};
    if (ff[A] && ff[H]) h += U.card2('Four factors', 'Shooting, turnovers (lower is better), offensive rebounds, free throws', U.chart('gm-ff', 220, 'Four factors'), { cls: 'qk-span-5' });
    if (shots.length) {
      const sq = g.shot_quality || {};
      const sqTxt = t => (sq[t] && isNum(sq[t].xpts) ? 'xPTS ' + U.f(sq[t].xpts, 1) + ', scored ' + U.f(sq[t].pts, 0) + ' (' + U.signed(sq[t].pts - sq[t].xpts, 1) + ' shot-making)' : '');
      h += U.card2(HW.teamName(L, A) + ' shots', esc(sqTxt(A)) + (sqTxt(A) ? ' · ' : '') + 'size is expected points', '<div id="gm-sh-a"></div>', { cls: 'qk-span-6' }) +
        U.card2(HW.teamName(L, H) + ' shots', esc(sqTxt(H)) + (sqTxt(H) ? ' · ' : '') + 'size is expected points', '<div id="gm-sh-h"></div>', { cls: 'qk-span-6' });
    }
    h += availabilityHTML(L, g, S);
    const tp = tape(L, g, res.season);
    if (tp) h += U.card2('Tale of the tape', 'Season so far: the stronger side of each bar is solid', tp, { cls: 'qk-span-12' });
    h += awardsHTML(L, g, S);
    if (hasBox) {
      h += U.card2('Box score', 'Advanced columns where play-by-play exists. Sort any column.', '<div class="qk-seg hw-boxtabs" id="gm-bx-seg" role="group" aria-label="Team">' +
        [A, H].map((t, i) => '<button type="button" data-value="' + esc(t) + '" aria-pressed="' + (i === 0) + '">' + esc(HW.teamName(L, t)) + '</button>').join('') + '</div><div id="gm-box"></div>', { cls: 'qk-span-' + (awardsHTML(L, g, S) ? '7' : '12') });
    }
    if (st === 'pre' && !parts.length && !isNum(((g.pregame || {}).model || {}).p_home)) h += U.card2('Preview', '', U.empty('Forecast not ready', 'Our forecast appears once the game is inside the build window.'), { cls: 'qk-span-12' });
    h += '</div>';
    if (st !== 'pre' && !(g.flow && g.flow.length) && hasBox) h += '<p class="hw-note">No play-by-play for this game: win probability, shots, lineups and rotations need it (seasons before about 2017 are box score only).</p>';
    h += '<p class="hw-flex">' + U.link(HW.href(L, 'games/' + HW.localDay(g.date), S), 'Games that day') + U.link(HW.teamHref(L, A, S), HW.teamName(L, A)) + U.link(HW.teamHref(L, H, S), HW.teamName(L, H)) + '</p>';
    el.innerHTML = h;

    if (document.getElementById('gm-ls')) {
      const n = Math.max(la.length, lh.length);
      const cols = [{ key: 't', label: 'Team', sort: false, fmt: v => U.teamEnt(L, v, { abbr: true, season: S }) }];
      for (let i = 0; i < n; i++) cols.push({ key: 'p' + i, label: HW.periodLabel(L, i + 1), num: true, sort: false });
      cols.push({ key: 'tot', label: 'T', num: true, sort: false, fmt: v => '<b>' + (isNum(v) ? v : '—') + '</b>' });
      const row = (t, arr, tot) => { const o = { t: t, tot: tot }; for (let i = 0; i < n; i++) o['p' + i] = arr[i]; return o; };
      QK.table(document.getElementById('gm-ls'), { columns: cols, rows: [row(A, la, g.as), row(H, lh, g.hs)], dense: true });
    }
    if (document.getElementById('gm-parts')) {
      const LBL = { rating: 'Team ratings', hca: 'Home court', rest: 'Rest', b2b: 'Back-to-back', travel: 'Travel', tz: 'Time zones', altitude: 'Altitude', injury: 'Injuries' };
      QKC.bar('#gm-parts', { cats: parts.map(k => LBL[k]), series: [{ name: 'Points', data: parts.map(k => Math.round(det[k] * 10) / 10) }], horizontal: true, labels: true, diverging: true, fmt: v => U.signed(v, 1), labelWidth: 100, valName: HW.teamAbbr(L, H) + ' margin (points)', catName: 'Part' });
    }
    if (document.getElementById('gm-wp')) {
      const pts = g.wp.model, espn = g.wp.espn || [];
      const top = (g.plays || []).filter(p => isNum(p.dwp_home) || isNum(p.wpa)).slice().sort((x, y) => Math.abs(y.dwp_home || y.wpa) - Math.abs(x.dwp_home || x.wpa)).slice(0, 5);
      const tMax = Math.max(pts[pts.length - 1][0], 4 * PERIOD_S(L));
      const per = []; for (let t = PERIOD_S(L); t < tMax; t += t < 4 * PERIOD_S(L) ? PERIOD_S(L) : 300) per.push(t);
      const hc = U.pair(L, H, A);
      QKC.winProb('#gm-wp', {
        t: pts.map(x => x[0]), p: pts.map(x => x[1]), step: true, tMin: 0, tMax: tMax, interval: PERIOD_S(L), periods: per,
        home: { name: HW.teamName(L, H), abbr: HW.teamAbbr(L, H), colour: hc[0] }, away: { name: HW.teamName(L, A), abbr: HW.teamAbbr(L, A), colour: hc[1] },
        tFmt: v => (v < 4 * PERIOD_S(L) ? 'Q' + (Math.round(v / PERIOD_S(L)) + 1) : ''), tLabel: t => tLabel(L, t),
        events: top.map((x, i) => ({ t: x.t, p: isNum(x.wp) ? x.wp : undefined, label: String(i + 1) })),
        compare: espn.length ? { name: 'ESPN', t: espn.map(x => x[0]), p: espn.map(x => x[1]) } : null
      });
    }
    if (document.getElementById('gm-flow')) {
      const fl = g.flow;
      QKC.mount('#gm-flow', T => {
        const hc = U.pair(L, H, A);
        return {
          grid: { left: 8, right: 16, top: 30, bottom: 30, containLabel: true },
          xAxis: QKC.axis(T, { name: 'Game time', nameLocation: 'middle', nameGap: 26, type: 'value', min: 0, max: fl[fl.length - 1][0], split: false, line: true, fmt: v => (v % PERIOD_S(L) === 0 && v <= 4 * PERIOD_S(L) ? 'Q' + (v / PERIOD_S(L) + 1) : ''), interval: PERIOD_S(L) }),
          yAxis: QKC.axis(T, { fmt: v => (v > 0 ? '+' : '') + v, name: HW.teamAbbr(L, H) + ' lead (points)', nameAlign: 'left' }),
          tooltip: QKC.tooltip(T, { trigger: 'axis', formatter: ps => { const m = (ps[0].value[1] || 0) + ((ps[1] || { value: [0, 0] }).value[1] || 0); return '<div style="color:' + T.ink3 + ';font-size:11px">' + esc(tLabel(L, ps[0].value[0])) + '</div>' + (m === 0 ? 'Tied' : QKC.tipRow(m > 0 ? hc[0] : hc[1], (m > 0 ? HW.teamAbbr(L, H) : HW.teamAbbr(L, A)) + ' lead', String(Math.abs(m)))); } }),
          series: [0, 1].map(k => ({ type: 'line', step: 'end', showSymbol: false, name: k ? HW.teamAbbr(L, A) : HW.teamAbbr(L, H),
            data: fl.map(x => [x[0], k ? Math.min(0, x[1]) : Math.max(0, x[1])]), lineStyle: { width: 1.6, color: hc[k] }, itemStyle: { color: hc[k] }, areaStyle: { color: QKC.hexA(hc[k], 0.2) },
            markLine: k ? undefined : { silent: true, symbol: 'none', lineStyle: { color: T.axis, type: [3, 3] }, label: { show: false }, data: [{ yAxis: 0 }] } }))
        };
      }, { label: 'Margin through the game' });
    }
    if (document.getElementById('gm-ff')) {
      const K = [['efg', 'eFG%'], ['tov', 'TOV%'], ['orb', 'ORB%'], ['ftr', 'FT rate']];
      QKC.bar('#gm-ff', { catName: 'Factor', cats: K.map(k => k[1]), series: [{ name: HW.teamAbbr(L, A), data: K.map(k => Math.round(ff[A][k[0]] * 1000) / 10) }, { name: HW.teamAbbr(L, H), data: K.map(k => Math.round(ff[H][k[0]] * 1000) / 10) }], labels: true, fmt: v => U.f(v, 1), legend: true, valName: 'Rate (%)',
        max: v => Math.min(100, Math.ceil(v.max * 1.2 / 10) * 10) });
    }
    if (shots.length) {
      [[A, 'gm-sh-a'], [H, 'gm-sh-h']].forEach(x => {
        const list = shots.filter(s => String(s.team) === String(x[0]) && isNum(s.x) && isNum(s.y) && s.y <= 41.5);
        const nm = id => { let n = null; Object.keys(g.box || {}).forEach(t => ((g.box[t] || {}).players || []).forEach(p => { if (String(p.id) === String(id)) n = p.name; })); return n || HW.playerName(L, id); };
        QKC.shotMap('#' + x[1], { surface: 'court', sizeScale: 18, vName: 'xPTS', madeLabel: 'Made', missLabel: 'Missed', colorMade: U.tcol(L, x[0]), colorMiss: QK.cssVar('--c-other'),
          shots: list.map(s => ({ x: s.x, y: s.y, v: isNum(s.xpts) ? s.xpts / 3 : 0.3, made: !!s.made, name: nm(s.player) + ' · ' + (s.value === 3 ? '3PT ' : '') + (s.type || '') + ' · ' + tLabel(L, s.t) })) , label: HW.teamName(L, x[0]) + ' shot chart' });
        // the legend takes the series colour: give it the same colours as the points
        const e = document.getElementById(x[1]).__qkc;
        if (e) { const b0 = e.build; e.build = (T, en) => { const o = b0(T, en); o.series[0].itemStyle = { color: T.other }; o.series[1].itemStyle = { color: U.tcol(L, x[0]) }; return o; }; e.paint(); }
      });
    }
    if (hasBox) {
      const drawBox = t => boxTable(document.getElementById('gm-box'), L, g, t, S);
      drawBox(A);
      QK.seg(document.getElementById('gm-bx-seg'), drawBox);
    }
    HW.setMeta(g.updated_at ? 'Game built ' + esc(HW.fmtStamp(g.updated_at)) : '');
  });
}

HW.page('games', renderGames);
HW.page('game', renderGame);
})(window.HW);
