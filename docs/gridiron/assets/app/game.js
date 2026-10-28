/* The Quant Gridiron — the game centre (#/game/<game_id>), on kit v4 "Broadcast" (the Rink game page is the reference).
 * Top: the hero is QK.previewCard, the diagonal split hero (away "at" home in the team colours with records, the clock when live, our chance for the
 * favourite as a big blue number with a how-sure note, the team-colour bar, the market as a quiet labelled reference
 * before kickoff, how the teams match up from the season ratings), then the week, venue, weather, quarterbacks and
 * coaches, the field strip when live and the linescore; beside it the stat tiles, our forecast table (the market a
 * reference column) and, before kickoff, what the game means for each team's playoff chance.
 * Tabs: Preview (projected score, margin and points distributions, tale of the tape, unit matchups, injuries with their
 * impact, the week's status changes and the starters out, venue and weather) · Game flow (win probability ours v ESPN
 * with every 4th down graded, scoring and key plays; the drive chart; 4th-down decisions; awards) · Play-by-play
 * (filters, search) · Box score (with EPA and Next Gen Stats columns). Reads <S>/games/<game_id>.json and
 * <S>/season.json (records, ratings, playoff stakes); every block is optional. */
(function (GI) {
'use strict';

const QK = window.QK;
const esc = GI.esc, isNum = GI.isNum;
const R = x => GI.ch.rows(x);
const TAB = {}, FILT = {};

function pick(o, keys) { for (let i = 0; i < keys.length; i++) { const v = o[keys[i]]; if (v !== undefined && v !== null && v !== '') return v; } return null; }

// ── normalise ─────────────────────────────────────────────────────────────

function playsOf(g) {
  return R(g.plays).map((p, i) => ({
    i: isNum(p.i) ? Number(p.i) : i, play_id: pick(p, ['play_id']), qtr: pick(p, ['qtr', 'quarter']), clock: pick(p, ['clock', 'time']), team: pick(p, ['team', 'posteam', 'offense']),
    down: pick(p, ['down']), dist: pick(p, ['dist', 'ydstogo', 'distance']), yl100: pick(p, ['yl100', 'yardline_100']), type: String(pick(p, ['type', 'play_type']) || ''),
    desc: String(pick(p, ['desc', 'text', 'description']) || ''), epa: pick(p, ['epa']), wpa: pick(p, ['wpa']),
    wp: pick(p, ['wp_home_ours', 'wp_home', 'wp']), espn: pick(p, ['wp_home_espn', 'espn_wp', 'wp_espn']),
    nf: pick(p, ['wp_home_nflfastr']), hsc: pick(p, ['home_score']), asc: pick(p, ['away_score']), players: p.players || []
  })).filter(p => !/^(GAME|END GAME|END QUARTER \d|Two-Minute Warning)$/i.test(p.desc.trim()) || p.team);
}
function isScore(p) { return /touchdown|field goal is good|safety|extra point is good|two-point .*succeeds/i.test(p.desc) || /^(touchdown|field_goal_made)$/i.test(p.type); }
function isTurnover(p) { return /intercept|fumble/i.test(p.desc + ' ' + p.type) && !/recovered by (?:the )?same|no fumble/i.test(p.desc); }
function kindOf(p) {
  const t = p.type.toLowerCase();
  if (/punt|field_goal|kickoff|extra_point|kick/.test(t)) return 'special';
  if (/pass|sack|interception|scramble/.test(t)) return 'pass';
  if (/run|rush|fumble|kneel/.test(t)) return 'run';
  if (/penalty|no_play/.test(t)) return 'penalty';
  return 'other';
}
function wpSeries(g, plays, pre) {
  const w = g.wp || g.wp_chart || null;
  if (w && (w.ours || w.espn) && !w.cols) return { ours: GI.ch.wpRows(w.ours), espn: GI.ch.wpRows(w.espn), name: 'Our model' };
  if (w && (w.cols || w.fields)) {
    const P = {};
    plays.forEach(p => { P[p.i] = p; });
    const rows = R(w);
    const mk = key => rows.filter(r => isNum(r[key])).map((r, k) => { const i = isNum(r.play_index) ? Number(r.play_index) : k; const pl = P[i] || {}; return { i: i, qtr: pl.qtr, clock: pl.clock, p: Number(r[key]), desc: pl.desc || '' }; });
    const ours = mk('wp_home_ours'), nf = mk('wp_home_nflfastr'), espn = mk('wp_home_espn');
    return ours.length >= 2 || nf.length < 2 ? { ours: ours, espn: espn, name: 'Our model' } : { ours: nf, espn: espn, name: 'nflfastR' };
  }
  const ours = [], espn = [], nf = [];
  const p0 = pre && pre.model && isNum(pre.model.p_home) ? Number(pre.model.p_home) : null;
  if (p0 !== null && plays.length) ours.push({ i: -1, qtr: 1, clock: '15:00', p: p0, desc: 'Pre-game model' });
  plays.forEach(p => {
    if (isNum(p.wp)) ours.push({ i: p.i, qtr: p.qtr, clock: p.clock, p: Number(p.wp), desc: p.desc });
    if (isNum(p.espn)) espn.push({ i: p.i, qtr: p.qtr, clock: p.clock, p: Number(p.espn), desc: p.desc });
    if (isNum(p.nf)) nf.push({ i: p.i, qtr: p.qtr, clock: p.clock, p: Number(p.nf), desc: p.desc });
  });
  if (ours.length < 3 && nf.length >= 2) return { ours: nf, espn: espn, name: 'nflfastR' };
  return { ours: ours, espn: espn, name: 'Our model' };
}
function fourthOf(g, plays) {
  return R(g.fourth_downs || g.fourth || g.decisions).map(f => {
    let i = isNum(f.i) ? Number(f.i) : (isNum(f.play) ? Number(f.play) : null);
    if (i === null && isNum(f.play_id)) { const hit = plays.find(p => Number(p.play_id) === Number(f.play_id)); if (hit) i = hit.i; }
    if (i === null) { const hit = plays.find(p => Number(p.down) === 4 && String(p.qtr) === String(f.qtr) && String(p.clock) === String(f.clock)); if (hit) i = hit.i; }
    const pl = i !== null ? plays.find(p => p.i === i) : null;
    const wp = f.wp && typeof f.wp === 'object' ? f.wp : {};
    return Object.assign({}, f, { wp_go: isNum(f.wp_go) ? f.wp_go : wp.go, wp_punt: isNum(f.wp_punt) ? f.wp_punt : wp.punt, wp_fg: isNum(f.wp_fg) ? f.wp_fg : wp.fg,
      i: i, team: f.team || (pl ? pl.team : null), desc: f.desc || (pl ? pl.desc : ''), yl100: isNum(f.yl100) ? f.yl100 : (pl ? pl.yl100 : null),
      dist: isNum(f.dist) ? f.dist : (pl ? pl.dist : null), qtr: f.qtr || (pl ? pl.qtr : null), clock: f.clock || (pl ? pl.clock : null) });
  });
}
function scoringOf(g, plays) {
  const s = R(g.scoring || g.scoring_plays);
  if (s.length) return s;
  if (plays.some(p => isNum(p.hsc))) {
    const out = [];
    let h0 = 0, a0 = 0;
    plays.forEach(p => {
      if (!isNum(p.hsc) || !isNum(p.asc)) return;
      const dh = Number(p.hsc) - h0, da = Number(p.asc) - a0;
      if (dh > 0 || da > 0) { const d = Math.max(dh, da); out.push({ i: p.i, team: dh > 0 ? g.home : g.away, kind: d >= 6 ? 'TD' : d === 3 ? 'FG' : d === 2 ? 'Safety/2pt' : 'PAT', desc: p.desc }); }
      h0 = Number(p.hsc); a0 = Number(p.asc);
    });
    return out.filter(x => x.kind !== 'PAT');
  }
  return plays.filter(isScore).map(p => ({ i: p.i, team: p.team, kind: /touchdown/i.test(p.desc) ? 'TD' : /field goal/i.test(p.desc) ? 'FG' : 'Score', desc: p.desc }));
}
function keyPlaysOf(g, plays) {
  const k = R(g.key_plays);
  if (k.length) return k.map(x => {
    const p = isNum(x.i) ? plays.find(q => q.i === Number(x.i)) : (isNum(x.play_id) ? plays.find(q => Number(q.play_id) === Number(x.play_id)) : null);
    return Object.assign({}, p || {}, x, { i: p ? p.i : x.i });
  });
  return plays.filter(p => isNum(p.wpa)).sort((a, b) => Math.abs(b.wpa) - Math.abs(a.wpa)).slice(0, 5).sort((a, b) => a.i - b.i);
}

// ── header ────────────────────────────────────────────────────────────────

function fieldStrip(g) {
  if (!isNum(g.yl100) || !g.possession) return '';
  const pos = g.possession, opp = GI.otherTeam(g, pos);
  const x = 100 - Number(g.yl100);
  const toPct = y => (Math.max(0, Math.min(100, y))).toFixed(1) + '%';
  const ltg = isNum(g.dist) && Number(g.dist) < Number(g.yl100) ? '<b style="left:' + toPct(x) + ';width:' + Number(g.dist) + '%"></b>' : '';
  return '<div class="gi-field-strip" role="img" aria-label="' + esc(GI.teamAbbr(pos) + ' ball at ' + GI.fieldPos(g.yl100, pos, opp)) + '">' + ltg + '<i style="left:' + toPct(x) + '"></i>' +
    '<span style="left:4%">' + esc(GI.teamAbbr(pos)) + '</span><span style="left:50%">50</span><span style="left:96%">' + esc(GI.teamAbbr(opp)) + '</span></div>';
}
function heroMeta(g) {
  const S = GI.gameSeason(g.game_id) || GI.state.season;
  const w = isNum(g.week) ? Number(g.week) : GI.gameWeek(g.game_id);
  const qbs = g.qbs || {}, co = g.coaches || {};
  const qbOf = side => { const q = (g.qb_status || {})[side] || qbs[side]; return q ? GI.qbText(q) : ''; };
  const meta = [GI.weekLink(S, w), g.gtype && String(g.gtype).toUpperCase() !== 'REG' && GI.gtypeLabel(g.gtype) !== GI.weekLabel(w, S) ? esc(GI.gtypeLabel(g.gtype)) : '',
    GI.weatherText(g.weather, g.roof) ? esc(GI.weatherText(g.weather, g.roof)) : '', g.referee ? 'Referee ' + esc(g.referee) : ''].filter(Boolean);
  const qb = qbOf('away') || qbOf('home') ? 'Quarterbacks: ' + (qbOf('away') || '?') + ' and ' + (qbOf('home') || '?') : '';
  const hc = co.away || co.home ? 'Head coaches: ' + (co.away ? GI.coachLink(co.away) : '?') + ' and ' + (co.home ? GI.coachLink(co.home) : '?') : '';
  return '<div class="gi-hero-meta">' + meta.map(x => '<span>' + x + '</span>').join('') + '</div>' + (qb || hc ? '<div class="gi-hero-meta">' + [qb, hc].filter(Boolean).map(x => '<span>' + x + '</span>').join('') + '</div>' : '');
}
/* v4 (Broadcast) hero: QK.previewCard, the diagonal split, with the records and form from the standings, our chance (the live chance once it
   starts, our pre-game call after it ends), a how-sure note with the projected score, the market as a quiet reference
   line before kickoff (game detail is one of the two places it may appear) and how the teams match up so far. */
function hero(g, pre, season) {
  const st = GI.gameState(g), live = st === 'live' || st === 'half', fin = st === 'final';
  const m = (pre && pre.model) || g.model || {};
  const mk = (pre && pre.market) || g.market || {};
  const rows = {};
  ((season && season.standings) || []).forEach(d => (d.teams || []).forEach(t => { rows[GI.canonTeam(t.team)] = t; }));
  const cols = GI.pair(g.away, g.home);
  const G = GI.qkGame(Object.assign({}, g, { model: m }), rows);
  /* v4: the diagonal hero takes the raw kit colours, the alternates and the full names (QK.color.blockPair makes the
     blocks and resolves a clash); the lifted pair `cols` stays for the factors and the charts */
  G.home.colour = GI.teamInfo(g.home).colour || cols[1]; G.away.colour = GI.teamInfo(g.away).colour || cols[0];
  G.home.alt = GI.teamInfo(g.home).alt; G.away.alt = GI.teamInfo(g.away).alt; G.home.full = GI.teamName(g.home); G.away.full = GI.teamName(g.away);
  G.league = 'NFL';
  if (live && st === 'half') G.clock = 'Half';
  const extra = [];
  if (!fin && !live && isNum(m.home_pts) && isNum(m.away_pts)) extra.push('Our projected score is ' + GI.teamShort(g.away) + ' ' + GI.num(m.away_pts, 0) + ', ' + GI.teamShort(g.home) + ' ' + GI.num(m.home_pts, 0));
  if (!fin && !live && isNum(m.total)) extra.push('we expect about ' + Math.round(m.total) + ' points in all');
  const src = (mk.sources || []).map(GI.titleCase).join(' / ') || 'Kalshi / Polymarket';
  const venue = g.stadium_name || g.stadium || '';
  return '<div class="gi-preview">' + QK.previewCard(G, { kicker: 'NFL' + (venue ? ' · ' + venue : ''), nick: t => t.name, colors: cols, factors: [],   /* round 9: the match-up lives in the Tale of the tape below */
    /* round 6: the market quiet under the hero (small and grey, the sources on hover) */
    noteExtra: extra.length ? esc(extra.join(', and ') + '.') : '', market: st === 'pre' && isNum(mk.p_home) ? { p: Number(mk.p_home), src: mk.sources || null, label: src, quiet: true } : null }) + '</div>';
}
/* Before kickoff: what a win or a loss does to each team's playoff chance (season.json next_game, the simulation). */
function stakes(g, season) {
  const rows = {};
  ((season && season.standings) || []).forEach(d => (d.teams || []).forEach(t => { rows[GI.canonTeam(t.team)] = t; }));
  const line = t => {
    const r = rows[GI.canonTeam(t)], ng = r && r.next_game;
    if (!ng || ng.game_id !== g.game_id || !ng.if_win || !ng.if_loss || !isNum(r.p_playoffs)) return '';
    return '<li><b>' + esc(GI.teamShort(t)) + '</b>: ' + GI.pct(r.p_playoffs, 0) + ' now; a win takes it to <b>' + GI.pct(ng.if_win.p_playoffs, 0) + '</b>, a loss to <b>' + GI.pct(ng.if_loss.p_playoffs, 0) + '</b>.</li>';
  };
  const ls = [line(g.away), line(g.home)].filter(Boolean);
  return ls.length ? GI.card('What’s at stake', 'Each team’s playoff chance from 20,000 simulated seasons, with this game won or lost', '<ul class="gi-stakes">' + ls.join('') + '</ul>') : '';
}
/* Stat tiles under the hero: ours first (the signal), then what the game produced. */
function tiles(g, pre, plays) {
  const st = GI.gameState(g), live = st === 'live' || st === 'half', fin = st === 'final';
  const m = (pre && pre.model) || {};
  const out = [];
  if (isNum(m.p_home)) {
    const fav = m.p_home >= 0.5 ? g.home : g.away;
    out.push({ label: st === 'pre' ? 'Our win chance' : 'Our pre-game call', value: GI.teamAbbr(fav) + ' ' + GI.pct(Math.max(m.p_home, 1 - m.p_home), 0), signal: true,
      sub: isNum(GI.homeLine(m)) && Math.abs(GI.homeLine(m)) >= 0.5 ? 'by ' + GI.num(Math.abs(GI.homeLine(m)), 1) + ' points on average' : 'a toss-up on the margin', tip: 'Our pre-game win chance from the game model (team ratings, quarterbacks, starters out, rest, weather and home field)' });
  }
  if (live && isNum(g.wp_home)) { const f = g.wp_home >= 0.5 ? g.home : g.away; out.push({ label: 'Live win chance', value: GI.teamAbbr(f) + ' ' + GI.pct(Math.max(g.wp_home, 1 - g.wp_home), 0), signal: true, sub: 'our live model, every play' }); }
  if (st === 'pre' && isNum(m.home_pts) && isNum(m.away_pts)) out.push({ label: 'Projected score', value: GI.num(m.away_pts, 0) + '–' + GI.num(m.home_pts, 0), sub: GI.teamAbbr(g.away) + ' – ' + GI.teamAbbr(g.home) + ', average of our simulations' });
  if (st === 'pre' && isNum(m.total)) out.push({ label: 'Points expected', value: GI.num(m.total, 1), sub: 'both teams, our game simulations' });
  const epa = { home: [0, 0], away: [0, 0] };
  plays.forEach(p => { if (!isNum(p.epa) || !p.team || /^(special|other)$/.test(kindOf(p))) return; const sd = String(p.team) === String(g.home) ? 'home' : String(p.team) === String(g.away) ? 'away' : null; if (sd) { epa[sd][0] += Number(p.epa); epa[sd][1]++; } });
  if (st !== 'pre' && epa.home[1] > 10 && epa.away[1] > 10) out.push({ label: 'EPA per play', value: GI.signed(epa.away[0] / epa.away[1], 2) + ' / ' + GI.signed(epa.home[0] / epa.home[1], 2), sub: GI.teamAbbr(g.away) + ' / ' + GI.teamAbbr(g.home) + ', runs and passes', tip: 'Expected points added per offensive play, our expected-points model' });
  if (fin || live) {
    const big = plays.filter(p => isNum(p.wpa)).sort((a, b) => Math.abs(b.wpa) - Math.abs(a.wpa))[0];
    if (big) out.push({ label: 'Biggest swing', value: GI.signed(Math.abs(big.wpa) * 100, 0) + ' pts', sub: GI.clockText(big.qtr, big.clock) + ' · ' + (big.team ? GI.teamAbbr(big.team) + ' ball' : ''), tip: String(big.desc || '').slice(0, 160) });
  }
  return out.length ? '<div class="gi-stats">' + QK.stats(out) + '</div>' : '';
}

// ── preview ───────────────────────────────────────────────────────────────

function normCdf(z) {
  const t = 1 / (1 + 0.2316419 * Math.abs(z));
  const d = 0.3989423 * Math.exp(-z * z / 2);
  const p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))));
  return z > 0 ? 1 - p : p;
}
function normDist(mu, sd, lo, hi) { const out = {}; for (let k = lo; k <= hi; k++) out[k] = Math.round((normCdf((k + 0.5 - mu) / sd) - normCdf((k - 0.5 - mu) / sd)) * 10000) / 10000; return out; }
function fromLoP(x) { if (!x || !Array.isArray(x.p)) return null; const out = {}; x.p.forEach((p, k) => { out[(x.lo || 0) + k] = p; }); return out; }
function withDists(m0, ln) {
  const m = Object.assign({}, m0);
  const mu = isNum(m.margin) ? Number(m.margin) : (isNum(GI.homeLine(m)) ? -GI.homeLine(m) : null);
  m.approx = false;
  if (!m.margin_dist && m.dist && m.dist.margin) m.margin_dist = fromLoP(m.dist.margin);
  if (!m.total_dist && m.dist && m.dist.total) m.total_dist = fromLoP(m.dist.total);
  if (!m.margin_dist && isNum(mu) && isNum(m.sigma)) { m.margin_dist = normDist(mu, Number(m.sigma), Math.floor(mu - 3 * m.sigma), Math.ceil(mu + 3 * m.sigma)); m.approx = true; }
  if (!m.total_dist && isNum(m.total) && isNum(m.sigma_total)) { m.total_dist = normDist(Number(m.total), Number(m.sigma_total), Math.max(0, Math.floor(m.total - 3 * m.sigma_total)), Math.ceil(m.total + 3 * m.sigma_total)); m.approx = true; }
  const l = GI.homeLine(ln || {});
  if (!isNum(m.p_cover_home) && isNum(mu) && isNum(m.sigma) && isNum(l)) m.p_cover_home = 1 - normCdf((-l - mu) / Number(m.sigma));
  if (!isNum(m.p_over) && isNum(m.total) && isNum(m.sigma_total) && ln && isNum(ln.total)) m.p_over = 1 - normCdf((Number(ln.total) - m.total) / Number(m.sigma_total));
  return m;
}
function forecastBlock(g, pre) {
  const m = pre.model || {}, mk = pre.market || g.market || {}, ln = pre.line || g.line || {};
  const H = GI.teamAbbr(g.home), A = GI.teamAbbr(g.away);
  const fin = GI.isFinal(g);
  const lLine = GI.homeLine(ln.close && fin ? ln.close : ln);
  const lTot = ln.close && fin && isNum(ln.close.total) ? ln.close.total : ln.total;
  const mlP = isNum(ln.ml_home) && isNum(ln.ml_away) ? GI.devigAm([ln.ml_home, ln.ml_away]) : null;
  const mg = GI.homeLine(m);
  const srcs = (mk.sources || []).map(GI.titleCase).join(' / ');
  /* the market cell stays short (the column is narrow beside ours): the chance, with its source in the tooltip */
  const mkSrc = isNum(mk.p_home) ? 'Prediction markets: ' + (srcs || 'Kalshi / Polymarket') : isNum(mlP) ? 'The closing moneyline without the margin (' + (((ln.close || ln.open || {}).src) || 'a sportsbook') + ', via ESPN)' : '';
  const mkCell = isNum(mk.p_home) ? H + ' ' + GI.pct(mk.p_home, 0) : (isNum(mlP) ? H + ' ' + GI.pct(mlP, 0) : '—');
  const rows = [['Who wins', isNum(m.p_home) ? H + ' ' + GI.pct(m.p_home, 0) + ' · ' + A + ' ' + GI.pct(1 - m.p_home - (isNum(m.p_tie) ? m.p_tie : 0), 0) + (isNum(m.p_tie) && m.p_tie >= 0.001 ? ' · tie ' + GI.pct(m.p_tie, 1) : '') : '—', mkCell]];
  if (isNum(mg)) rows.push(['Projected margin', Math.abs(mg) < 0.5 ? 'even' : GI.teamAbbr(mg < 0 ? g.home : g.away) + ' by ' + GI.num(Math.abs(mg), 1) + ' points', '']);
  if (isNum(m.p_cover_home) && isNum(lLine) && Math.abs(lLine) >= 1) {
    const fav = lLine < 0 ? 'home' : 'away', need = Math.ceil(Math.abs(lLine));
    const p = fav === 'home' ? m.p_cover_home : 1 - m.p_cover_home;
    rows.push([GI.teamAbbr(g[fav]) + ' wins by ' + need + ' or more', GI.pct(p, 0), '']);
  }
  if (isNum(m.total)) rows.push(['Total points', GI.num(m.total, 1) + ' expected' + (isNum(m.p_over) && isNum(lTot) ? ' · ' + Math.ceil(Number(lTot)) + ' or more: ' + GI.pct(m.p_over, 0) : ''), '']);
  if (isNum(m.home_pts) && isNum(m.away_pts)) rows.push(['Projected score', A + ' ' + GI.num(m.away_pts, 1) + ' – ' + GI.num(m.home_pts, 1) + ' ' + H, '']);
  return '<div class="qk-table-wrap"><table class="qk-table dense gi-fc-t"><thead><tr><th>Question</th><th>Our forecast</th><th><span data-tip="The prediction-market chance or the closing line without the margin, a reference only, not our forecast">Market</span></th></tr></thead><tbody>' +
    rows.map((r, i) => '<tr><td>' + esc(r[0]) + '</td><td class="num gi-ours-cell">' + esc(r[1]) + '</td><td class="num qk-muted" style="text-align:left"' + (i === 0 && mkSrc ? ' data-tip="' + esc(mkSrc) + '" tabindex="0"' : '') + '>' + esc(r[2]) + '</td></tr>').join('') + '</tbody></table></div>' +
    (mkSrc ? '<p class="gi-cap">Market: ' + esc(mkSrc) + '.</p>' : '');
}
/* Tale of the tape: the two teams' season profile from the team-strength ratings (season.json ratings[team].values). */
function tape(season, g) {
  const R = (season && season.ratings) || {};
  const a = (R[g.away] || {}).values || {}, h = (R[g.home] || {}).values || {};
  const rows = [
    { label: 'Team rating (points a game)', a: a.rating, b: h.rating, fmt: v => GI.signed(v, 1), tip: 'Our rating: points a game better than an average team on a neutral field' },
    { label: 'Offence rating', a: a.off_rating, b: h.off_rating, fmt: v => GI.signed(v, 1) },
    { label: 'Defence rating', a: a.def_rating, b: h.def_rating, fmt: v => GI.signed(v, 1) },
    { label: 'Pass offence (EPA per dropback)', a: a.off_pass_epa, b: h.off_pass_epa, fmt: v => GI.signed(v, 3) },
    { label: 'Rush offence (EPA per carry)', a: a.off_rush_epa, b: h.off_rush_epa, fmt: v => GI.signed(v, 3) },
    { label: 'Pass defence (EPA per dropback allowed)', a: a.def_pass_epa, b: h.def_pass_epa, fmt: v => GI.signed(v, 3), better: 'low' },
    { label: 'Rush defence (EPA per carry allowed)', a: a.def_rush_epa, b: h.def_rush_epa, fmt: v => GI.signed(v, 3), better: 'low' },
    { label: 'Special teams (EPA a game)', a: a.st_epa_g, b: h.st_epa_g, fmt: v => GI.signed(v, 2) }
  ];
  if (!rows.some(r => isNum(r.a) && isNum(r.b))) return '';
  const cols = GI.pair(g.away, g.home);
  const A = { name: GI.teamShort(g.away), abbr: GI.teamAbbr(g.away), colour: cols[0] }, H = { name: GI.teamShort(g.home), abbr: GI.teamAbbr(g.home), colour: cols[1] };
  return QK.matchupBar({ left: A, right: H, rows: rows, colors: cols });
}
function projBlock(g, m) {
  let hp = m.home_pts, ap = m.away_pts;
  const ml = GI.homeLine(m);
  if ((!isNum(hp) || !isNum(ap)) && isNum(m.total) && isNum(ml)) { hp = (Number(m.total) - ml) / 2; ap = (Number(m.total) + ml) / 2; }
  if (!isNum(hp) || !isNum(ap)) return '';
  const cols = GI.pair(g.away, g.home);
  const t = (team, pts, c) => '<a class="gi-vs-team" href="' + GI.teamHref(team) + '">' + GI.mark(team, 'lg') + '<span class="p gi-disp" style="color:' + esc(c) + '">' + GI.num(pts, 1) + '</span><span class="qk-sub">' + esc(GI.teamShort(team)) + '</span></a>';
  return '<div class="gi-vs">' + t(g.away, ap, cols[0]) + '<div class="gi-vs-mid"><span>our projection</span><span class="sc">–</span></div>' + t(g.home, hp, cols[1]) + '</div>';
}
function injuriesBlock(g) {
  let inj = g.injuries || {};
  /* ESPN's lists keyed by team ({KC: [...]}): read them as home and away (the builder does this from 22 Oct 2026) */
  if (!inj.home && !inj.away && (inj[g.home] || inj[g.away])) {
    const keep = rows => R(rows).filter(x => String(x.status || '').toLowerCase() !== 'active');
    inj = { home: keep(inj[g.home]), away: keep(inj[g.away]), source: 'ESPN' };
  }
  const qb = g.qb_status || {};
  const av = g.availability || null;
  if (!R(inj.home).length && !R(inj.away).length && !qb.home && !qb.away && !av && !g.injury_changes) return '';
  const soLine = s => {
    const a = av && av[s];
    if (!a || (!a.off && !a.def)) return av ? '<p class="gi-cap">Starters out: none, so no adjustment.</p>' : '';
    return '<p class="gi-cap">Starters out: <b>' + GI.num(a.off, 2) + '</b> offence · <b>' + GI.num(a.def, 2) + '</b> defence (expected, depth-chart starters) → ' + GI.ptsEdge(a.pts, 1) + ' points in our forecast</p>';
  };
  const side = s => {
    const list = R(inj[s]).slice();
    const q = qb[s];
    const seen = {};
    list.forEach(x => { if (x && x.pid) seen[x.pid] = 1; });
    R(av && av[s] ? av[s].players : null).forEach(x => {
      if (x.pid && !seen[x.pid]) list.push({ pid: x.pid, pos: x.grp, status: x.by === 'inactives' ? 'Inactive' : 'Out', detail: x.by === 'inactives' ? 'game-day inactive' : 'not on this list', impact: x.pts });
    });
    return '<div><h4 class="gi-inj-h">' + GI.teamLink(g[s]) + '</h4>' + (q ? '<p class="gi-cap">QB: ' + GI.qbText(q) + (q.status ? ' · ' + esc(q.status) : '') + (isNum(q.value) ? ' · value ' + GI.signed(q.value, 3) + ' EPA/play' : '') + '</p>' : '') + soLine(s) +
      (list.length ? GI.tableHTML([{ label: 'Player' }, { label: 'Pos' }, { label: 'Status' }, { label: 'Detail' }, { label: 'Impact', align: 'right', title: 'Points of margin in our forecast (negative hurts this team)' }],
        list.map(x => [{ html: x.pid ? GI.playerLink(x.pid, x.name ? { name: x.name } : null) : esc(x.name || '—'), v: x.name || GI.playerName(x.pid) }, GI.posLabel(x.pos || GI.player(x.pid).pos || '—'),
          { html: GI.pill(x.status || '—', /out|ir|doubt/i.test(x.status || '') ? GI.BAD : /quest/i.test(x.status || '') ? GI.CLOSE : 'var(--ink-3)'), v: x.status }, x.detail || x.injury || '—',
          { html: isNum(x.impact) ? GI.ptsEdge(x.impact, 1) : '—', v: x.impact }])) : GI.muted('No injuries reported.')) + changes(s) + '</div>';
  };
  const ch = g.injury_changes || null;
  const changes = s => {
    const rows = R(ch && ch[s]);
    if (!ch) return '';
    if (!rows.length) return '<p class="gi-cap">No status changes on ESPN\'s list this week (checked hourly).</p>';
    return '<h4 class="gi-inj-h">Changes this week</h4>' + GI.tableHTML([{ label: 'First seen' }, { label: 'Player and change' }],
      rows.slice().reverse().map(x => [{ html: esc(GI.fmtDate(x.at, { year: false }) + ' ' + GI.fmtTime(x.at)), v: x.at },
        { html: (x.pid ? GI.playerLink(x.pid) : esc('ESPN #' + x.espn)) + '<br><span class="qk-sub">' + esc(x.from) + ' → ' + esc(x.to) + '</span>',
          v: x.pid ? GI.playerName(x.pid) : x.espn }]));
  };
  const src = inj.source ? esc(inj.source) : 'the injury report';
  let foot = '';
  if (av) {
    const H = esc(GI.teamAbbr(g.home));
    foot = '<p class="gi-cap">Net starters-out effect on the ' + H + ' margin: <b>' + GI.ptsEdge(av.net_home, 1) + '</b>. ' +
      (av.src === 'inactives' ? 'From the game-day inactives (an inactive starter counts 1).' : 'From the injury report (Out 1, Doubtful 0.85, Questionable 0.15 of a starter); the game-day inactives replace it about 90 minutes before kickoff, and our forecast moves with them.') +
      ' Each offensive starter out costs ' + GI.num(-av.coef.off, 2) + ' points and each defensive one ' + GI.num(-av.coef.def, 2) + '. Quarterbacks are modelled separately. A player costs 0 if not a starter on the depth chart for the team\'s previous game: a backup, or a starter who already missed that game, whose absence is already in the team ratings and earlier forecasts. <a href="#/methodology">How →</a></p>';
  }
  if (ch) foot += '<p class="gi-cap">Changes: ESPN’s injury list for each team, checked every hour since 22 October 2026; each change is dated by the first check that saw it (last check ' + esc(GI.fmtDate(ch.as_of, { year: false }) + ' ' + GI.fmtTime(ch.as_of)) + '). ESPN keeps no history of its own.</p>';
  return GI.card('Injuries and QB status', 'From ' + src + '; impact = points of margin in our forecast (negative hurts the team)', '<div class="qk-grid"><div class="qk-span-6">' + side('away') + '</div><div class="qk-span-6">' + side('home') + '</div></div>' + foot);
}
function contextBlock(g) {
  const w = g.weather || {}, c = g.coaches || {};
  const items = [['Stadium', esc(g.stadium_name || g.stadium || '')], ['Roof', esc(g.roof || '')], ['Surface', esc(g.surface || '')],
    ['Temperature', isNum(w.temp) ? Math.round(w.temp) + '°F' : ''], ['Wind', isNum(w.wind) ? Math.round(w.wind) + ' mph' : ''], ['Conditions', esc(w.desc || w.conditions || '')],
    ['Referee', esc(g.referee || '')], [GI.teamAbbr(g.away) + ' head coach', c.away ? GI.coachLink(c.away) : ''], [GI.teamAbbr(g.home) + ' head coach', c.home ? GI.coachLink(c.home) : ''],
    ['Rest', g.rest ? esc(GI.teamAbbr(g.away)) + ' ' + esc(g.rest.away) + 'd · ' + esc(GI.teamAbbr(g.home)) + ' ' + esc(g.rest.home) + 'd' : ''], ['Game ID', '<code>' + esc(g.game_id) + '</code>']].filter(x => x[1]);
  return GI.card('Venue, weather and officials', '', '<dl class="gi-dl">' + items.map(x => '<dt>' + esc(x[0]) + '</dt><dd>' + x[1] + '</dd>').join('') + '</dl>');
}
function rankPct(r) { return isNum(r) ? Math.max(2, Math.min(100, (33 - Number(r)) / 32 * 100)) : null; }
function matchupsBlock(g) {
  const m = g.matchups;
  if (!m || Array.isArray(m) || !(m.home_off || m.away_off)) return '';
  const rows = [];
  [['away_off', g.away, g.home], ['home_off', g.home, g.away]].forEach(x => {
    const o = m[x[0]];
    if (!o) return;
    ['pass', 'rush'].forEach(u => { const v = o[u]; if (v) rows.push({ label: GI.teamAbbr(x[1]) + ' ' + u + ' O v ' + GI.teamAbbr(x[2]) + ' ' + u + ' D', off: v.off, offR: v.off_rank, def: v.def, defR: v.def_rank, t: x[1], o: x[2] }); });
  });
  if (!rows.length) return '';
  return GI.card('Unit matchups', 'opponent-adjusted EPA per play and league rank (1 = best)', GI.chartBox('gm-units', Math.max(200, rows.length * 44 + 40), 'Unit matchups by league percentile') +
    GI.tableHTML([{ label: 'Matchup', sortable: false }, { label: 'Offence', align: 'right', sortable: false }, { label: 'Rank', align: 'right', sortable: false }, { label: 'Defence allows', align: 'right', sortable: false }, { label: 'Rank', align: 'right', sortable: false }],
      rows.map(r => [esc(r.label), { html: GI.signed(r.off, 3) }, { html: GI.ordinal(r.offR) }, { html: GI.signed(r.def, 3) }, { html: GI.ordinal(r.defR) }])), { span: 12 }) +
    '<script type="application/json" id="gm-units-data">' + JSON.stringify(rows).replace(/</g, '\\u003c') + '</script>';
}
function drawUnits(root) {
  const d = root.querySelector('#gm-units-data');
  if (!d) return;
  const rows = JSON.parse(d.textContent);
  GI.ch.mount('gm-units', T => {
    const cats = rows.map(r => r.label);
    const ya = GI.ch.ax(T, { type: 'category', data: cats, split: false, inverse: true });
    ya.axisLabel.color = T.ink2; ya.axisLabel.width = 170; ya.axisLabel.overflow = 'truncate';
    return {
      grid: { left: 8, right: 16, top: 28, bottom: 30, containLabel: true },
      legend: GI.ch.legend(T, { data: ['Offence percentile', 'Defence percentile'] }),
      xAxis: GI.ch.ax(T, { min: 0, max: 100, fmt: v => v + 'th', name: 'Percentile among teams', nameLocation: 'middle', nameGap: 26 }), yAxis: ya,
      tooltip: GI.ch.tip(T, { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: ps => { const r = rows[ps[0].dataIndex]; return GI.ch.thead(esc(r.label)) + GI.ch.trow(T.model, GI.teamAbbr(r.t) + ' offence', GI.signed(r.off, 3) + ' · ' + GI.ordinal(r.offR)) + GI.ch.trow(T.cat[1], GI.teamAbbr(r.o) + ' defence', GI.signed(r.def, 3) + ' · ' + GI.ordinal(r.defR)); } }),
      series: [{ type: 'bar', name: 'Offence percentile', data: rows.map(r => rankPct(r.offR)), barMaxWidth: 12, itemStyle: { color: T.model } },
        { type: 'bar', name: 'Defence percentile', data: rows.map(r => rankPct(r.defR)), barMaxWidth: 12, itemStyle: { color: T.cat[1] } }]
    };
  }, 'Unit matchups');
}
function previewTab(g, pre) {
  const m = pre.model;
  const hasModel = isNum(m.p_home) || isNum(m.total) || isNum(GI.homeLine(m));
  let h = '';
  if (hasModel) {
    h += GI.card('Projected score', 'The average of our game simulations', projBlock(g, m) || GI.muted('No projection.'));
    if (m.margin_dist || m.total_dist) {
      h += GI.grid(GI.card('Margin', 'Our chance of each final margin, ' + esc(GI.teamAbbr(g.home)) + ' points minus ' + esc(GI.teamAbbr(g.away)) + (m.approx ? ' · normal approximation' : ''), GI.chartBox('gm-md', 240, 'Margin distribution'), { span: 6 }) +
        GI.card('Total points', 'Our chance of each total, both teams; dashed: our mean' + (GI.isFinal(g) ? ' · white: the result' : ''), GI.chartBox('gm-td', 240, 'Total points distribution'), { span: 6 }));
    }
  }
  h += '<div id="gm-tape"></div>' + matchupsBlock(g) + injuriesBlock(g) + contextBlock(g);
  return { html: h, after: root => {
    if (m.margin_dist && root.querySelector('#gm-md')) GI.ch.distBars('gm-md', m.margin_dist, { signed: true, split: 0, colours: [GI.teamColour(g.home), GI.teamColour(g.away)],
      exp: isNum(GI.homeLine(m)) ? -GI.homeLine(m) : null, actual: GI.isFinal(g) && isNum(g.hs) ? g.hs - g.as : null, unit: 'pts', xName: GI.teamAbbr(g.home) + ' margin (pts)', yName: 'Chance' });
    if (m.total_dist && root.querySelector('#gm-td')) GI.ch.distBars('gm-td', m.total_dist, { exp: m.total, actual: GI.isFinal(g) && isNum(g.hs) ? Number(g.hs) + Number(g.as) : null, unit: 'pts', xName: 'Total points', yName: 'Chance' });
    drawUnits(root);
    /* tale of the tape: the season ratings */
    GI.loadYear('season.json', GI.gameSeason(g.game_id)).then(season => {
      const n = root.querySelector('#gm-tape');
      if (!n || !n.isConnected || !GI.ok(season)) return;
      const tp = tape(season, g);
      if (tp) n.innerHTML = GI.card('Tale of the tape', 'Season so far, opponent-adjusted: the stronger side of each bar is solid', tp);
    });
  } };
}

// ── game flow ─────────────────────────────────────────────────────────────

function fourthTable(g, fd) {
  if (!fd.length) return '';
  const wpv = (x, on) => (isNum(x) ? (on ? '<b>' + GI.pct(x, 0) + '</b>' : GI.pct(x, 0)) : '—');
  const rows = fd.map(f => {
    const opp = GI.otherTeam(g, f.team), c = String(f.choice || '').toLowerCase();
    return [{ html: esc(GI.clockText(f.qtr, f.clock)), v: (Number(f.qtr) || 0) * 10000 - (parseInt(String(f.clock).replace(':', ''), 10) || 0) },
      { html: GI.teamChip(f.team), v: f.team },
      { html: esc('4th & ' + (isNum(f.dist) ? Math.round(f.dist) : '?') + (isNum(f.yl100) ? ' at ' + GI.fieldPos(f.yl100, f.team, opp) : '')), v: f.dist },
      esc(GI.choiceLabel(f.choice)), esc(GI.choiceLabel(f.rec || f.recommendation)),
      { html: wpv(f.wp_go, /^go|run|pass/.test(c)) + ' · ' + wpv(f.wp_punt, /punt/.test(c)) + ' · ' + wpv(f.wp_fg, /fg|field/.test(c)) },
      { html: isNum(f.wp_lost) ? GI.num(Math.abs(f.wp_lost) * 100, 1) : '—', v: f.wp_lost },
      { html: GI.gradePill(f.grade, f.wp_lost) || '—', v: GI.gradeOf(f.grade, f.wp_lost).key },
      { html: '<span class="gi-play-desc">' + esc(String(f.desc || '').slice(0, 180)) + '</span>' }];
  });
  return GI.card('Fourth downs', fd.length + ' decision' + (fd.length === 1 ? '' : 's') + ' · graded by win probability lost against the best option · <a href="' + GI.ghref('fourth-downs', GI.gameSeason(g.game_id)) + '">every 4th down this season →</a>',
    GI.tableHTML([{ label: 'When' }, { label: 'Team' }, { label: 'Situation' }, { label: 'Call' }, { label: 'Our call', title: 'What our fourth-down model recommends' }, { label: 'WP go · punt · FG', sortable: false, title: 'Our win probability for the team on fourth down, by option' },
      { label: 'WP lost', align: 'right', title: 'Win probability given up against the best option, percentage points' }, { label: 'Grade' }, { label: 'Play', sortable: false }], rows) +
    '<div class="gi-legend" style="margin-top:10px"><span><i style="background:' + GI.GOOD + '"></i>Right call (≤ 1.5 pts lost)</span><span><i style="background:' + GI.CLOSE + '"></i>Close call (1.5–3)</span><span><i style="background:' + GI.BAD + '"></i>Mistake (&gt; 3)</span></div>');
}
function keyPlaysBlock(g, kp) {
  if (!kp.length) return '';
  return GI.card('Key plays', 'the biggest swings in win probability (numbered on the chart) · EPA and WPA are for the team with the ball', GI.tableHTML([{ label: '#', align: 'right', sortable: false }, { label: 'When', sortable: false }, { label: 'Team', sortable: false, title: 'The team with the ball' }, { label: 'Play', sortable: false }, { label: 'EPA', align: 'right', sortable: false, title: 'Expected points added for the team with the ball' }, { label: 'WPA', align: 'right', sortable: false, title: 'Win probability added for the team with the ball, percentage points' }],
    kp.map((p, k) => [k + 1, esc(GI.clockText(p.qtr, p.clock)), { html: p.team ? GI.teamChip(p.team) : '' }, { html: '<span class="gi-play-desc">' + esc(p.desc || '') + '</span>' },
      { html: isNum(p.epa) ? GI.signed(p.epa, 2) : '—' }, { html: isNum(p.wpa) ? GI.ptsEdge(p.wpa * 100, 1) : '—' }])));
}
const AWARD_TITLE = { home_ball: 'Best player', away_ball: 'Best player', play_of_game: 'Play of the game', mvp: 'Player of the game', coach: 'Best 4th-down call' };
function awardsBlock(g) {
  const a = g.awards;
  if (!a) return '';
  const list = Array.isArray(a) ? a : Object.keys(a).filter(k => a[k] && typeof a[k] === 'object').map(k => {
    const x = a[k];
    const side = /^home/.test(k) ? 'home' : /^away/.test(k) ? 'away' : null;
    const team = x.team || (side ? g[side] : null);
    const value = x.value !== undefined ? x.value : isNum(x.wpa) ? GI.signed(x.wpa * 100, 1) + ' pts WPA' : isNum(x.epa) ? GI.signed(x.epa, 2) + ' EPA' : null;
    return { title: x.title || ((AWARD_TITLE[k] || GI.titleCase(k)) + (side ? ' · ' + GI.teamAbbr(team) : '')), pid: x.pid, name: x.name, team: team, coach: x.coach, value: value, why: x.why || (x.pid ? '' : x.desc || '') };
  });
  if (!list.length) return '';
  return GI.card('Awards', 'from our play values', '<div class="gi-awards">' + list.map(x =>
    '<div class="gi-award" style="--tc:' + esc(x.team ? GI.tc(x.team) : 'var(--accent)') + '"><span class="qk-kicker">' + esc(x.title || '') + '</span>' +
    '<span class="gi-award-who">' + (x.pid ? GI.playerLink(x.pid, x.name ? { name: x.name } : null) : x.coach ? GI.coachLink(x.coach) : x.team ? GI.teamLink(x.team) : esc(x.name || '')) + '</span>' +
    (x.value !== undefined && x.value !== null ? '<span class="gi-award-v">' + esc(isNum(x.value) ? GI.signed(x.value, 2) : x.value) + '</span>' : '') + (x.why ? '<span class="gi-award-why">' + esc(String(x.why).slice(0, 200)) + '</span>' : '') + '</div>').join('') + '</div>');
}
function driveTable(g, drives) {
  const D = GI.ch.driveRows(drives);
  if (!D.length) return '';
  return GI.tableHTML([{ label: '#', align: 'right' }, { label: 'Team' }, { label: 'Start' }, { label: 'Field' }, { label: 'Plays', align: 'right' }, { label: 'Yds', align: 'right' }, { label: 'Time', align: 'right' }, { label: 'Result' }, { label: 'EPA', align: 'right' }],
    D.map(d => { const r = GI.driveResult(d.result); const opp = GI.otherTeam(g, d.team);
      return [d.n, { html: GI.teamChip(d.team), v: d.team }, { html: esc(GI.clockText(d.qtr, d.clock)), v: d.n }, { html: esc(GI.fieldPos(d.start, d.team, opp)), v: d.start },
        isNum(d.plays) ? d.plays : '—', isNum(d.yards) ? Math.round(d.yards) : '—', d.time ? GI.fmtClock(d.time) : '—', { html: GI.pill(r.label, r.colour), v: r.label }, { html: isNum(d.epa) ? GI.signed(d.epa, 2) : '—', v: d.epa }]; }), { maxHeight: 420 });
}
/* Pages built from ESPN's record while nflverse has not published the week: say so where the nflverse-only parts are missing. */
function espnNote(g) {
  return g.source === 'espn' ? GI.note('<b>Provisional.</b> Built from ESPN’s play-by-play and box score until nflverse publishes this week (usually within a day). Win probability and EPA are our models on ESPN’s play states (score before the snap, timeouts from the play log), so they can differ slightly from the final version; fourth-down grades, game balls and the advanced box columns fill in then.') : '';
}
function flowTab(g, pre, plays) {
  const fd = fourthOf(g, plays), sc = scoringOf(g, plays), kp = keyPlaysOf(g, plays), wp = wpSeries(g, plays, pre);
  const hasWp = wp.ours.length >= 2 || wp.espn.length >= 2;
  const hasDrives = GI.ch.driveRows(g.drives).length > 0;
  let h = espnNote(g) + GI.card('Win chance through the game', esc(GI.teamAbbr(g.home)) + ' (home) · ' + (wp.name === 'Our model' ? 'our model' : esc(wp.name)) + ' solid' + (wp.espn.length ? ', ESPN dotted' : '') + ' · ◆ 4th downs by grade · ● scores · numbers: key plays' +
    (wp.name !== 'Our model' ? ' · our WP model is not fitted for this game, so nflfastR\'s published WP is shown' : ''),
    hasWp ? (wp.espn.length && wp.ours.length >= 2 ? QK.keys([{ name: wp.name === 'Our model' ? 'Our model' : wp.name, color: 'var(--ink-1)' }, { name: 'ESPN', color: 'var(--ink-3)', kind: 'line' }]) : '') + GI.chartBox('gm-wp', 360, 'Win probability through the game') : GI.muted(GI.isPre(g) ? 'The win-probability chart starts at kickoff.' : 'No win-probability path for this game yet.'));
  /* the in-game model's prior is the closing spread (nflverse spread_line, models/wp.py), not our pre-game forecast, so its
     first number can sit away from our pre-game call: say so, with both numbers (SB 2025: our 47% for NE, 29% at the first snap) */
  const w0 = wp.name === 'Our model' && wp.ours[0] && isNum(wp.ours[0].p) ? wp.ours[0] : null, p0 = (pre.model || {}).p_home;
  if (hasWp && w0 && isNum(p0) && Math.abs(w0.p - p0) >= 0.05) {
    h += GI.note('<b>Why the line does not start at our pre-game call.</b> The in-game model starts from the closing spread (its pre-game information, as nflfastR’s does), not from our pre-game forecast: at the first snap it gave ' + esc(GI.teamAbbr(g.home)) + ' ' + GI.pct(w0.p, 0) + ', where our game model had ' + GI.pct(p0, 0) + '. From there it moves with the score, the clock, the down and the field position.');
  }
  h += GI.card('Drive chart', 'every drive from where it started to where it ended, own goal line on the left; colour is the result', hasDrives ? GI.chartBox('gm-drives', 400, 'Drive chart') +
    '<details style="margin-top:10px"><summary class="qk-sub">Drive table</summary>' + driveTable(g, g.drives) + '</details>' : GI.muted(GI.isPre(g) ? 'Drives appear at kickoff.' : 'No drives yet.'));
  h += fourthTable(g, fd) + keyPlaysBlock(g, kp) + awardsBlock(g);
  return { html: h, after: () => {
    if (hasWp) GI.ch.wpChart('gm-wp', wp.ours, { espn: wp.espn, home: g.home, away: g.away, fourth: fd, scoring: sc, top: kp });
    if (hasDrives) GI.ch.driveChart('gm-drives', g.drives, { home: g.home, away: g.away });
  } };
}

// ── play-by-play ──────────────────────────────────────────────────────────

function pbpTab(g, plays) {
  if (!plays.length) return { html: GI.card('Play-by-play', '', GI.muted(GI.isPre(g) ? 'Plays appear at kickoff.' : 'No plays yet.')) };
  const note = espnNote(g);
  const f = FILT[g.game_id] = FILT[g.game_id] || { team: 'all', qtr: 'all', kind: 'all', epa: '0', wpa: '0', q: '' };
  const qtrs = [];
  plays.forEach(p => { if (isNum(p.qtr) && qtrs.indexOf(Number(p.qtr)) < 0) qtrs.push(Number(p.qtr)); });
  const ctl = '<div class="gi-toolbar">' +
    GI.field('Team', GI.select('pf-team', [['all', 'Both'], [g.away, GI.teamAbbr(g.away)], [g.home, GI.teamAbbr(g.home)]], f.team, 'Team')) +
    GI.field('Quarter', GI.select('pf-qtr', [['all', 'All']].concat(qtrs.map(q => [q, GI.qtrLabel(q)])), f.qtr, 'Quarter')) +
    GI.field('Plays', GI.select('pf-kind', [['all', 'All'], ['pass', 'Passes'], ['run', 'Runs'], ['special', 'Special teams'], ['score', 'Scoring'], ['fourth', '4th downs'], ['turnover', 'Turnovers'], ['penalty', 'Penalties']], f.kind, 'Plays')) +
    GI.field('|EPA| at least', GI.select('pf-epa', [['0', 'Any'], ['0.5', '0.5'], ['1', '1'], ['2', '2'], ['3', '3']], f.epa, 'EPA')) +
    GI.field('|WPA| at least', GI.select('pf-wpa', [['0', 'Any'], ['0.02', '2 pts'], ['0.05', '5 pts'], ['0.1', '10 pts']], f.wpa, 'WPA')) +
    GI.field('Search', '<input type="search" class="qk-input" id="pf-q" value="' + esc(f.q) + '" placeholder="Player or word">') + '<span class="qk-sub" id="pf-count"></span></div>';
  const draw = root => {
    const wrap = root.querySelector('#pbp-wrap');
    if (!wrap) return;
    const q = String(f.q || '').toLowerCase().trim();
    const list = plays.filter(p => {
      if (f.team !== 'all' && String(p.team) !== String(f.team)) return false;
      if (f.qtr !== 'all' && String(p.qtr) !== String(f.qtr)) return false;
      if (f.kind === 'score' && !isScore(p)) return false;
      if (f.kind === 'fourth' && Number(p.down) !== 4) return false;
      if (f.kind === 'turnover' && !isTurnover(p)) return false;
      if (['pass', 'run', 'special', 'penalty'].indexOf(f.kind) >= 0 && kindOf(p) !== f.kind) return false;
      if (Number(f.epa) > 0 && !(isNum(p.epa) && Math.abs(p.epa) >= Number(f.epa))) return false;
      if (Number(f.wpa) > 0 && !(isNum(p.wpa) && Math.abs(p.wpa) >= Number(f.wpa))) return false;
      if (q) { const names = (Array.isArray(p.players) ? p.players : []).map(id => GI.playerName(id)).join(' '); if ((p.desc + ' ' + names).toLowerCase().indexOf(q) < 0) return false; }
      return true;
    });
    const cnt = root.querySelector('#pf-count');
    if (cnt) cnt.textContent = list.length + ' of ' + plays.length + ' plays';
    let lastQ = null, body = '';
    list.forEach(p => {
      if (String(p.qtr) !== String(lastQ)) { body += '<tr><td colspan="7" class="gi-pbp-q"><b>' + esc(GI.qtrLabel(p.qtr, true)) + '</b></td></tr>'; lastQ = p.qtr; }
      const opp = GI.otherTeam(g, p.team);
      const sit = p.down ? GI.downDist(p.down, p.dist, p.yl100) + (isNum(p.yl100) ? ' · ' + GI.fieldPos(p.yl100, p.team, opp) : '') : (isNum(p.yl100) ? GI.fieldPos(p.yl100, p.team, opp) : '');
      const flag = isScore(p) ? '<span class="qk-badge accent">Score</span> ' : isTurnover(p) ? '<span class="qk-badge live">Turnover</span> ' : Number(p.down) === 4 ? '<span class="qk-badge">4th</span> ' : '';
      body += '<tr><td class="num">' + esc(GI.fmtClock(p.clock)) + '</td><td>' + (p.team ? GI.teamChip(p.team) : '') + '</td><td>' + esc(sit) + '</td><td><span class="gi-play-desc">' + flag + esc(p.desc) + '</span></td>' +
        '<td class="num">' + (isNum(p.epa) ? GI.ptsEdge(p.epa, 2) : '—') + '</td><td class="num">' + (isNum(p.wpa) ? GI.signed(p.wpa * 100, 1) : '—') + '</td>' +
        '<td class="num">' + (isNum(p.wp) ? GI.pct(p.wp, 0) : '—') + (isNum(p.espn) ? '<span class="gi-sub-line">ESPN ' + GI.pct(p.espn, 0) + '</span>' : '') + '</td></tr>';
    });
    wrap.innerHTML = list.length ? '<div class="qk-table-wrap gi-plays"><table class="qk-table dense"><thead><tr><th class="num">Clock</th><th>Team</th><th>Situation</th><th>Play</th><th class="num"><span data-tip="Expected points added for the offence">EPA</span></th>' +
      '<th class="num"><span data-tip="Home win probability added, points">WPA</span></th><th class="num"><span data-tip="Home win probability before the snap: ours (ESPN below)">WP</span></th></tr></thead><tbody>' + body + '</tbody></table></div>' : GI.muted('No plays match these filters.');
  };
  return { html: note + GI.card('Play-by-play', 'EPA for the offence · WPA and WP from ' + esc(GI.teamAbbr(g.home)) + '\'s side', ctl + '<div id="pbp-wrap"></div>'), after: root => {
    [['pf-team', 'team'], ['pf-qtr', 'qtr'], ['pf-kind', 'kind'], ['pf-epa', 'epa'], ['pf-wpa', 'wpa']].forEach(x => { const n = root.querySelector('#' + x[0]); if (n) n.addEventListener('change', () => { f[x[1]] = n.value; draw(root); }); });
    const qn = root.querySelector('#pf-q');
    if (qn) qn.addEventListener('input', () => { f.q = qn.value; draw(root); });
    draw(root);
  } };
}

// ── box score ─────────────────────────────────────────────────────────────

const BOX_ORDER = ['passing', 'rushing', 'receiving', 'defense', 'defence', 'kicking', 'punting', 'returns', 'team'];
const BOX_TITLE = { passing: 'Passing', rushing: 'Rushing', receiving: 'Receiving', defense: 'Defence', defence: 'Defence', kicking: 'Kicking', punting: 'Punting', returns: 'Returns', team: 'Team stats' };
const COL_LABEL = { pid: 'Player', player: 'Player', name: 'Player', team: 'Team', cmp: 'Cmp', att: 'Att', yds: 'Yds', td: 'TD', int: 'Int', sacks: 'Sk', car: 'Car', rec: 'Rec', tgt: 'Tgt',
  epa: 'EPA', epa_per_play: 'EPA/play', epa_per_db: 'EPA/db', epa_db: 'EPA/db', epa_per_target: 'EPA/tgt', epa_per_carry: 'EPA/car', cpoe: 'CPOE', ttt: 'Time to throw', adot: 'aDOT',
  ryoe: 'RYOE', ryoe_per_att: 'RYOE/att', separation: 'Separation', yac: 'YAC', yac_oe: 'YAC o/e', air_yards: 'Air yds', success_rate: 'Success', tackles: 'Tkl',
  pressures: 'Pressures', qb_hits: 'QB hits', fgm: 'FGM', fga: 'FGA', xpm: 'XPM', fg_oe: 'FG pts o/e', punts: 'Punts', net: 'Net', aggressiveness: 'Aggr.', cushion: 'Cushion', wpa: 'WPA' };
const NGS_COLS = /ttt|time_to_throw|separation|cushion|ryoe|aggress|efficiency|cpoe_ngs|xyac|avg_speed|max_speed/;
function fmtBox(k, v) {
  if (!isNum(v)) return v === null || v === undefined || v === '' ? '—' : esc(v);
  const x = Number(v);
  if (/epa/.test(k)) return GI.signed(x, Math.abs(x) >= 10 ? 1 : 2);
  if (/^wpa$/.test(k)) return GI.signed(x * 100, 1);
  if (/cpoe/.test(k)) return GI.signed(Math.abs(x) < 1 ? x * 100 : x, 1);
  if (/rate|pct|share|success/.test(k)) return GI.pct(x, 0);
  if (/ttt|time_to_throw/.test(k)) return x.toFixed(2) + 's';
  if (/ryoe_per|adot|separation|cushion|yac_oe|net/.test(k)) return GI.num(x, 1);
  return Number.isInteger(x) ? String(x) : GI.num(x, 1);
}
function boxSection(g, key, sec, note) {
  const list = R(sec);
  if (!list.length) return '';
  const cols = sec.cols || sec.fields || sec.columns || Object.keys(list[0]);
  if (key === 'team' || (cols[0] === 'stat' && cols.indexOf('home') >= 0)) {
    return GI.card(BOX_TITLE[key] || GI.titleCase(key), note || '', GI.tableHTML([{ label: '', sortable: false }, { label: GI.teamAbbr(g.away), align: 'right', sortable: false }, { label: GI.teamAbbr(g.home), align: 'right', sortable: false }],
      list.map(r => { const k = String(r.stat || '').toLowerCase().replace(/\s+/g, '_'); return [esc(r.stat || r.label || ''), { html: fmtBox(k, r.away) }, { html: fmtBox(k, r.home) }]; })));
  }
  let show = cols.filter(c => c !== 'team' && c !== 'name');
  if (show.indexOf('pid') < 0 && cols.indexOf('name') >= 0) show.unshift('name');
  const tbl = t => {
    const rows = list.filter(r => !r.team || String(r.team) === String(t));
    if (!rows.length) return '';
    return '<h4 class="gi-inj-h">' + (t ? GI.teamLink(t) : '') + '</h4>' + GI.tableHTML(show.map(c => ({ label: COL_LABEL[c] || GI.titleCase(c), align: c === 'pid' || c === 'player' || c === 'name' ? null : 'right', title: NGS_COLS.test(c) ? 'NFL Next Gen Stats' : null })),
      rows.map(r => show.map(c => {
        if (c === 'name') return { html: esc(r.name), v: r.name };
        if (c === 'pid' || c === 'player') { const id = r.pid || r.player; return { html: /^\d\d-\d+/.test(String(id)) ? GI.playerLink(id, r.name ? { name: r.name } : null) : esc(r.name || id), v: r.name || GI.playerName(id) }; }
        return { html: fmtBox(c, r[c]), v: r[c] };
      })), { sticky: true });
  };
  const hasTeam = list.some(r => r.team);
  return GI.card(BOX_TITLE[key] || GI.titleCase(key), note || '', hasTeam ? [g.away, g.home].map(tbl).join('') : tbl(null));
}
function boxBySection(g, b) {
  if (!b || !b.home || !b.away || typeof b.home !== 'object' || b.home.cols || Array.isArray(b.home)) return b || {};
  const out = {};
  ['away', 'home'].forEach(side => Object.keys(b[side] || {}).forEach(sec => { out[sec] = (out[sec] || []).concat(R(b[side][sec]).map(r => Object.assign({ team: g[side] }, r))); }));
  if (b.team) out.team = b.team;
  return out;
}
function boxTab(g) {
  const box = boxBySection(g, g.box), ngs = g.ngs || {};
  const keys = Object.keys(box);
  if (!keys.length && !Object.keys(ngs).length) return { html: GI.card('Box score', '', GI.muted(GI.isPre(g) ? 'The box score fills in from kickoff.' : 'No box score yet.')) };
  keys.sort((a, b) => { const ia = BOX_ORDER.indexOf(a), ib = BOX_ORDER.indexOf(b); return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib); });
  const espn = g.source === 'espn';
  return { html: espnNote(g) + keys.map(k => boxSection(g, k, box[k], espn ? 'ESPN box score' : (/passing|rushing|receiving/.test(k) ? 'with EPA and our advanced columns' : ''))).join('') +
    Object.keys(ngs).map(k => boxSection(g, k, ngs[k], 'NFL Next Gen Stats (via nflverse), credited; informational, non-commercial use')).join('') +
    '<p class="gi-cap">EPA is our expected points added. Columns with an NGS tooltip are NFL Next Gen Stats; charting columns are FTN Data via nflverse (CC BY-SA 4.0).</p>' };
}

// ── page ──────────────────────────────────────────────────────────────────

GI.route('game', function (el, params) {
  const id = params.id;
  const S0 = GI.gameSeason(id) || GI.state.season;
  return GI.loadAll([GI.gamePath(id), GI.ypath('season.json', S0)]).then(res0 => {
    const g0 = res0[0], season = GI.ok(res0[1]) ? res0[1] : null;
    if (!el.isConnected) return;
    const meta = GI.parseGameId(id);
    if (!GI.ok(g0)) {
      /* a page that failed to build (an {ok: false} stub) or is not built: the game's card from index.json or the week
         file (status, score, our chance), and a plain note; a failed page is unsigned in the build manifest, so the next
         build retries it */
      const idx = GI.index() || {};
      const c0 = ['live', 'games', 'recent'].reduce((acc, k) => acc || (idx[k] || []).find(x => x && x.game_id === id), null);
      const fromWeek = c0 || !meta ? Promise.resolve(c0) : GI.loadWeek(meta.week, meta.season).then(w => (GI.ok(w) ? (w.games || []).find(x => x && x.game_id === id) : null) || null);
      return fromWeek.then(c => {
        if (!el.isConnected) return;
        const failed = g0 && g0.ok === false;
        el.innerHTML = GI.pageHead(meta ? GI.weekLink(meta.season, meta.week) : 'Game', meta ? GI.teamName(meta.away) + ' at ' + GI.teamName(meta.home) : 'Game ' + id, '', meta ? GI.weekNav(meta.season, meta.week) : '') +
          (c ? '<div style="max-width:420px">' + GI.gameCard(c, { date: true }) + '</div>' : '') +
          (failed ? QK.empty('The game centre is being rebuilt', 'The play-by-play, win probability and box score for this game did not build on the last update. Every update retries it; the result and our pre-game call are above.')
            : GI.notBuilt('The game centre for this game', g0)) +
          (meta && meta.season < GI.currentSeason() - 1 ? GI.muted('Game centres are kept for the current and the previous season; the week pages keep every result.') : '');
      });
    }
    const g = Object.assign({}, g0.card || {}, g0);
    const gm = g0.game && typeof g0.game === 'object' ? g0.game : null;
    if (gm) {
      ['stadium', 'stadium_name', 'roof', 'surface', 'referee', 'overtime', 'div_game', 'espn_id', 'date'].forEach(k => { if ((g[k] === undefined || g[k] === null) && gm[k] !== undefined) g[k] = gm[k]; });
      g.weather = Object.assign({ temp: gm.temp, wind: gm.wind, roof: gm.roof }, (g.card || {}).weather || g.weather || {});
      if (!g.coaches) g.coaches = { home: gm.home_coach, away: gm.away_coach };
      if (!g.rest && isNum(gm.home_rest)) g.rest = { home: gm.home_rest, away: gm.away_rest };
    }
    if (!g.quarters && g.score && Array.isArray(g.score.home)) g.quarters = g.score.home.map((h, i) => [g.score.away[i], h]);
    if (!g.home && meta) { g.home = meta.home; g.away = meta.away; }
    if (!g.game_id) g.game_id = id;
    const pre = Object.assign({}, g.pregame || g.pre || { model: g.model, market: g.market, line: g.line });
    if (!pre.model) pre.model = g.model || {};
    if (!pre.market) pre.market = g.market || null;
    /* round 6: a game file built before the market was captured falls back to the index card's (the quiet market line) */
    if (!pre.market) { const ix = GI.index() || {}, ic = (ix.games || []).concat(ix.live || []).filter(x => x && x.game_id === id)[0]; if (ic && ic.market) pre.market = ic.market; }
    if (!pre.line) pre.line = g.line || null;
    pre.model = withDists(pre.model || {}, pre.line || g.line);
    const plays = playsOf(g);
    const st = GI.gameState(g);
    const live = st === 'live' || st === 'half';
    const tabs = [['preview', st === 'pre' ? 'Preview' : 'The matchup'], ['flow', 'Game flow'], ['plays', 'Play-by-play'], ['box', 'Box score']];
    const q = (params.query || {}).tab;
    let tab = TAB[id] || (tabs.some(t => t[0] === q) ? q : (st === 'pre' ? 'preview' : 'flow'));
    document.title = GI.teamAbbr(g.away) + ' @ ' + GI.teamAbbr(g.home) + ' · ' + GI.SITE;
    const m = pre.model || {};
    const hasModel = isNum(m.p_home) || isNum(m.total) || isNum(GI.homeLine(m));
    const qsx = GI.ch.quartersOf(g);
    const fc = hasModel ? GI.card(st === 'pre' ? 'Our forecast' : 'Our pre-game forecast', (pre.priced_at || m.priced_at ? 'made ' + esc(GI.fmtStamp(pre.priced_at || m.priced_at)) + (st === 'pre' ? '' : ', frozen at kickoff') + '. ' : '') + 'The market column is a reference, not our forecast',
      forecastBlock(g, pre) + QK.note('Our chances come from the game model: team ratings, the quarterbacks, starters out, rest, weather and home field. How it has done since 2006 is on the <a href="#/calibration">Model page</a>.'), { flush: false }) : '';
    el.innerHTML = '<div class="qk-kicker" style="margin-bottom:10px"><a href="' + GI.weekHref(GI.gameSeason(id), GI.gameWeek(id)) + '">← ' + esc(GI.weekLabel(GI.gameWeek(id), GI.gameSeason(id))) + ' games</a></div>' +
      '<div class="gi-gtop"><div class="gi-stack">' + hero(g, pre, season) + heroMeta(g) + (live ? fieldStrip(g) : '') + (qsx.length ? '<div class="gi-hero-ls">' + GI.ch.linescore(g) + '</div>' : '') + '</div>' +
      '<div class="gi-stack">' + tiles(g, pre, plays) + fc + (st === 'pre' ? stakes(g, season) : '') + '</div></div>' +
      '<div class="qk-tabs" role="tablist" aria-label="Game centre" style="margin-top:var(--sp-6)">' + tabs.map(t => '<button type="button" class="qk-tab" role="tab" data-tab="' + t[0] + '" aria-selected="' + (t[0] === tab) + '">' + esc(t[1]) + '</button>').join('') + '</div><div id="gm-body" class="gi-page" style="margin-top:var(--sp-4)"></div>';
    const body = el.querySelector('#gm-body');
    const show = k => {
      tab = k; TAB[id] = k;
      el.querySelectorAll('[data-tab]').forEach(a => a.setAttribute('aria-selected', a.dataset.tab === k ? 'true' : 'false'));
      const out = k === 'preview' ? previewTab(g, pre) : k === 'flow' ? flowTab(g, pre, plays) : k === 'plays' ? pbpTab(g, plays) : boxTab(g);
      body.innerHTML = out.html;
      GI.sortable(body);
      if (out.after) out.after(body);
    };
    el.querySelectorAll('[data-tab]').forEach(a => a.addEventListener('click', () => { show(a.dataset.tab); GI.setHashQuiet('#/game/' + encodeURIComponent(id) + '?tab=' + a.dataset.tab); }));
    show(tab);
    if (live) GI.liveRefresh([GI.gamePath(id)], 30000);
  });
});

})(window.GI);
