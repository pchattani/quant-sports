/* The Quant Gridiron — the game centre (#/game/<game_id>).
 *
 * Header: teams, score, quarter and clock, possession with down, distance and field position on a
 * field strip, live win probability (ours and ESPN's), the linescore by quarter, venue, weather,
 * officials. Tabs:
 *   Preview    model v market v line for win, spread and total, the projected score, margin and
 *              total distributions, injuries and QB status, weather and venue, unit matchups;
 *   Game flow  the win-probability chart (ours v ESPN, every 4th down marked and coloured by its
 *              grade, scoring plays, key plays numbered), the drive chart, the 4th-down decisions,
 *              key plays and the game's awards;
 *   Plays      play-by-play with team, quarter, play-type, EPA and WPA filters and a text search;
 *   Box score  passing, rushing, receiving, defence, kicking and team stats with advanced and Next
 *              Gen Stats columns.
 *
 * Reads data/<S>/games/<game_id>.json (PAYLOADS.md "games/<game_id>.json"): the GAME_CARD fields plus
 * pregame {model {p_home, spread, total, home_pts, away_pts, p_cover_home, p_over, margin_dist,
 * total_dist}, market, line}, injuries {home, away: [{pid|name, pos, status, detail, impact}]},
 * qb_status {home, away: {pid, status, value}}, weather, stadium, roof, surface, referee, coaches,
 * matchups [{label, home, away, home_pct, away_pct}], quarters [[away, home], ...], drives [...],
 * plays {cols, rows} (cols as PAYLOADS), wp {ours, espn} (else read from the plays), fourth_downs
 * [{i, qtr, clock, team, dist, yl100, choice, rec, wp_go, wp_punt, wp_fg, wp_lost, grade}],
 * scoring [{i, team, kind, desc}], key_plays [{i, desc, wpa, epa}], box {section: {cols, rows}},
 * ngs {section: {cols, rows}}, awards [{title, pid, team, coach, value, why}]. Every block is optional. */
(function (GI) {
'use strict';

const esc = GI.esc;
const isNum = GI.isNum;
const R = x => GI.charts.rows(x);
const TAB = {};       // game_id -> tab shown (kept across live refreshes)
const FILT = {};      // game_id -> play-by-play filters

function pick(o, keys) { for (let i = 0; i < keys.length; i++) { const v = o[keys[i]]; if (v !== undefined && v !== null && v !== '') return v; } return null; }

// ── normalise ──────────────────────────────────────────────────────────────

function playsOf(g) {
  return R(g.plays).map((p, i) => ({
    i: isNum(p.i) ? Number(p.i) : i, play_id: pick(p, ['play_id']), qtr: pick(p, ['qtr', 'quarter']), clock: pick(p, ['clock', 'time']), team: pick(p, ['team', 'posteam', 'offense']),
    down: pick(p, ['down']), dist: pick(p, ['dist', 'ydstogo', 'distance']), yl100: pick(p, ['yl100', 'yardline_100']), type: String(pick(p, ['type', 'play_type']) || ''),
    desc: String(pick(p, ['desc', 'text', 'description']) || ''), epa: pick(p, ['epa']), wpa: pick(p, ['wpa']),
    wp: pick(p, ['wp_home_ours', 'wp_home', 'wp']), espn: pick(p, ['wp_home_espn', 'espn_wp', 'wp_espn']),
    nf: pick(p, ['wp_home_nflfastr']), hsc: pick(p, ['home_score']), asc: pick(p, ['away_score']),
    ep0: pick(p, ['ep_before', 'ep']), ep1: pick(p, ['ep_after']), players: p.players || []
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
  return t ? 'other' : 'other';
}
/* WP series: g.wp {ours, espn} | g.wp_chart, else from the plays. A pre-game point leads when the model price is known. */
function byIndex(plays) { const m = {}; plays.forEach(p => { m[p.i] = p; }); return m; }
function wpSeries(g, plays, pre) {
  const w = g.wp || g.wp_chart || null;
  if (w && (w.ours || w.espn) && !w.cols) return { ours: GI.charts.wpRows(w.ours), espn: GI.charts.wpRows(w.espn), name: 'Our model' };
  if (w && (w.cols || w.fields)) {
    const P = byIndex(plays);
    const rows = R(w);
    const mk = key => rows.filter(r => isNum(r[key])).map((r, k) => {
      const i = isNum(r.play_index) ? Number(r.play_index) : k;
      const pl = P[i] || {};
      return { i: i, qtr: pl.qtr, clock: pl.clock, p: Number(r[key]), desc: pl.desc || '' };
    });
    const ours = mk('wp_home_ours'), nf = mk('wp_home_nflfastr'), espn = mk('wp_home_espn');
    return ours.length >= 2 ? { ours: ours, espn: espn, name: 'Our model' } : { ours: nf, espn: espn, name: 'nflfastR' };
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
/* 4th downs with a play index (matched on quarter and clock when the payload has none). */
function fourthOf(g, plays) {
  return R(g.fourth_downs || g.fourth || g.decisions).map(f => {
    let i = isNum(f.i) ? Number(f.i) : (isNum(f.play) ? Number(f.play) : null);
    if (i === null && isNum(f.play_id)) { const hit = plays.find(p => Number(p.play_id) === Number(f.play_id)); if (hit) i = hit.i; }
    if (i === null) {
      const hit = plays.find(p => Number(p.down) === 4 && String(p.qtr) === String(f.qtr) && String(p.clock) === String(f.clock));
      if (hit) i = hit.i;
    }
    const pl = i !== null ? plays.find(p => p.i === i) : null;
    const wp = f.wp && typeof f.wp === 'object' ? f.wp : {};
    return Object.assign({}, f, { wp_go: isNum(f.wp_go) ? f.wp_go : wp.go, wp_punt: isNum(f.wp_punt) ? f.wp_punt : wp.punt, wp_fg: isNum(f.wp_fg) ? f.wp_fg : wp.fg }, { i: i, team: f.team || (pl ? pl.team : null), desc: f.desc || (pl ? pl.desc : ''), yl100: isNum(f.yl100) ? f.yl100 : (pl ? pl.yl100 : null),
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
      if (dh > 0 || da > 0) {
        const d = Math.max(dh, da);
        out.push({ i: p.i, team: dh > 0 ? g.home : g.away, kind: d >= 6 ? 'TD' : d === 3 ? 'FG' : d === 2 ? 'Safety/2pt' : 'PAT', desc: p.desc });
      }
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

// ── header ─────────────────────────────────────────────────────────────────

function fieldStrip(g) {
  if (!isNum(g.yl100) || !g.possession) return '';
  const pos = g.possession, opp = GI.otherTeam(g, pos);
  const x = 100 - Number(g.yl100);                       // yards from the offence's goal line
  const toPct = y => (8.33 + 83.34 * Math.max(0, Math.min(100, y)) / 100).toFixed(2) + '%';
  let lines = '';
  for (let y = 10; y < 100; y += 10) lines += '<i style="left:' + toPct(y) + '"></i>';
  const ltg = isNum(g.dist) && Number(g.dist) < Number(g.yl100) ? '<span class="gf-ltg" style="left:' + toPct(x + Number(g.dist)) + '" title="Line to gain"></span>' : '';
  return '<div class="gm-field" title="' + esc(GI.teamAbbr(pos)) + ' driving left to right">' + lines +
    '<span class="gf-ez" style="left:1%">' + esc(GI.teamAbbr(pos)) + '</span><span class="gf-ez" style="right:1%">' + esc(GI.teamAbbr(opp)) + '</span>' +
    '<span class="gf-los" style="left:' + toPct(x) + '"></span>' + ltg + '<span class="gf-ball" style="left:' + toPct(x) + '"></span></div>';
}
function header(g, pre, plays) {
  const st = GI.gameState(g);
  const live = st === 'live' || st === 'half', fin = st === 'final';
  const S = GI.gameSeason(g.game_id) || GI.state.season;
  const w = isNum(g.week) ? Number(g.week) : GI.gameWeek(g.game_id);
  const hs = isNum(g.hs) ? Number(g.hs) : null, as = isNum(g.as) ? Number(g.as) : null;
  const m = (pre && pre.model) || g.model || {};
  const pre0 = isNum(m.p_home) ? Number(m.p_home) : null;
  const lastEspn = plays.slice().reverse().find(p => isNum(p.espn));
  const pNow = live && isNum(g.wp_home) ? Number(g.wp_home) : pre0;
  const coaches = g.coaches || { home: g.home_coach, away: g.away_coach };
  const qbs = g.qbs || {};
  const qbOf = side => { const q = (g.qb_status || {})[side] || qbs[side]; return q ? GI.qbText(q) : ''; };
  const row = (t, side, score, win) => {
    const p = pNow === null || fin ? null : (side === 'home' ? pNow : 1 - pNow);
    const pf = pre0 === null ? null : (side === 'home' ? pre0 : 1 - pre0);
    const sub = [qbOf(side) ? 'QB ' + qbOf(side) : '', coaches && coaches[side] ? 'HC ' + GI.coachLink(coaches[side]) : ''].filter(Boolean).join(' · ');
    return '<div class="gm-team' + (fin && win === false ? ' lost' : '') + '"><span class="gm-sw" style="background:' + GI.teamColour(t) + '"></span>' +
      '<div class="gm-tn"><div class="gm-name">' + GI.teamLink(t, { bar: false, season: S }) + (live && String(g.possession) === String(t) ? '<span class="gm-poss" title="Possession">●</span>' : '') + '</div>' +
      '<div class="gm-tsub">' + (side === 'home' ? 'Home' : 'Away') + (sub ? ' · ' + sub : '') + '</div></div>' +
      '<div class="gm-score">' + (score === null || st === 'pre' ? '' : esc(score)) + '</div>' +
      '<div class="gm-p">' + (fin ? (pf !== null ? GI.pct(pf, 0) + '<small>pre-game</small>' : '') : (p !== null ? GI.pct(p, 0) + '<small>' + (live && isNum(g.wp_home) ? 'live win' : 'to win') + '</small>' : '')) + '</div></div>';
  };
  const kick = g.kickoff || g.date;
  const kv = [
    GI.weekLink(S, w), g.gtype && String(g.gtype).toUpperCase() !== 'REG' ? esc(GI.gtypeLabel(g.gtype)) : '',
    kick ? esc(GI.fmtDate(kick, { time: true })) : '', (g.stadium_name || g.stadium) ? esc(g.stadium_name || g.stadium) : '',
    [g.roof, g.surface].filter(Boolean).map(esc).join(', '), GI.weatherText(g.weather, g.roof) ? esc(GI.weatherText(g.weather, g.roof)) : '',
    g.referee ? 'Referee ' + esc(g.referee) : ''
  ].filter(Boolean);
  let liveRow = '';
  if (live) {
    const sit = g.down ? GI.downDist(g.down, g.dist, g.yl100) + (isNum(g.yl100) ? ' at ' + GI.fieldPos(g.yl100, g.possession, GI.otherTeam(g, g.possession)) : '') : '';
    liveRow = '<div class="gm-live"><span class="gm-clock">' + (st === 'half' ? 'Halftime' : esc(GI.clockText(g.qtr, g.clock) || 'Live')) + '</span>' +
      (sit ? '<span class="gm-sit">' + esc(GI.teamAbbr(g.possession)) + ' ball · ' + esc(sit) + '</span>' : '') +
      (isNum(g.wp_home) ? '<span class="gm-wp">' + esc(GI.teamAbbr(g.wp_home >= 0.5 ? g.home : g.away)) + ' ' + GI.pct(Math.max(g.wp_home, 1 - g.wp_home), 1) + ' to win' +
        (lastEspn ? '<small>ESPN ' + GI.pct(g.wp_home >= 0.5 ? lastEspn.espn : 1 - lastEspn.espn, 0) + '</small>' : '') + '</span>' : '') + '</div>' + fieldStrip(g);
  }
  const qs = GI.charts.quartersOf(g);
  return '<div class="gm-head"><div class="gm-kicker">' + GI.statusChip(g) + kv.join(' · ') + '</div>' +
    '<div class="gm-main"><div class="gm-board">' + row(g.away, 'away', as, fin && as !== null && hs !== null ? as > hs : null) + row(g.home, 'home', hs, fin && as !== null && hs !== null ? hs > as : null) + '</div>' +
    (qs.length ? '<div class="gm-ls">' + GI.charts.linescore(g) + '</div>' : '') + '</div>' + liveRow + '</div>';
}

// ── preview ────────────────────────────────────────────────────────────────

function mvmBig(g, pre) {
  const m = pre.model || {}, mk = pre.market || g.market || {}, ln = pre.line || g.line || {};
  const H = GI.teamAbbr(g.home), A = GI.teamAbbr(g.away);
  const mLine = GI.homeLine(m), kLine = GI.homeLine(mk), lLine = GI.homeLine(ln.close && GI.isFinal(g) ? ln.close : ln), oLine = ln.open ? GI.homeLine(ln.open) : null;
  const lTot = ln.close && GI.isFinal(g) && isNum(ln.close.total) ? ln.close.total : ln.total;
  const mlP = isNum(ln.ml_home) && isNum(ln.ml_away) ? GI.devigAm([ln.ml_home, ln.ml_away]) : null;
  const rows = [
    { cells: [{ html: 'Win (' + esc(H) + ')', cls: 'mv-k' }, { html: GI.pct(m.p_home), cls: 'mv-model' }, { html: GI.pct(mk.p_home) + (mk.sources ? '<span class="sub-line">' + esc(mk.sources.join(' · ')) + '</span>' : '') },
      { html: isNum(ln.ml_home) ? esc(H) + ' ' + GI.fmtOdds(ln.ml_home) + ' / ' + esc(A) + ' ' + GI.fmtOdds(ln.ml_away) + (mlP !== null ? '<span class="sub-line">no-vig ' + GI.pct(mlP) + '</span>' : '') : '—' },
      { html: GI.edgeHTML(m.p_home, isNum(mk.p_home) ? mk.p_home : mlP), title: 'Model minus market (or the de-vigged moneyline), percentage points' }] },
    { cells: [{ html: 'Spread', cls: 'mv-k' }, { html: esc(GI.spreadText(g.home, g.away, mLine)) + (isNum(m.p_cover_home) && isNum(lLine) ? '<span class="sub-line">' + esc(H) + ' covers ' + esc(GI.fmtLine(lLine)) + ': ' + GI.pct(m.p_cover_home, 0) + '</span>' : ''), cls: 'mv-model' },
      { html: esc(GI.spreadText(g.home, g.away, kLine)) }, { html: esc(GI.spreadText(g.home, g.away, lLine)) + (isNum(oLine) ? '<span class="sub-line">open ' + esc(GI.spreadText(g.home, g.away, oLine)) + '</span>' : '') },
      { html: (() => { const l = GI.lineLean(g, mLine, lLine); return l ? (l.team ? esc(GI.teamAbbr(l.team)) + ' by ' + GI.num(l.pts, 1) : 'none') : '—'; })(), title: 'The side our fair line prefers against the line, in points' }] },
    { cells: [{ html: 'Total', cls: 'mv-k' }, { html: GI.num(m.total, 1) + (isNum(m.p_over) && isNum(lTot) ? '<span class="sub-line">over ' + GI.num(lTot, 1) + ': ' + GI.pct(m.p_over, 0) + '</span>' : ''), cls: 'mv-model' },
      { html: GI.num(mk.total, 1) }, { html: GI.num(lTot, 1) + (ln.open && isNum(ln.open.total) ? '<span class="sub-line">open ' + GI.num(ln.open.total, 1) + '</span>' : '') },
      { html: isNum(m.total) && isNum(lTot) ? GI.gapPts(m.total - lTot) : '—', title: 'Model total minus the line, points' }] }
  ];
  return GI.tableHTML([{ label: '', sortable: false }, { label: 'Model', sortable: false }, { label: 'Market', sortable: false }, { label: 'Line', sortable: false }, { label: 'Model − line', sortable: false }], rows, { cls: 'mvm-big' });
}
function projBlock(g, m) {
  let hp = m.home_pts, ap = m.away_pts;
  const ml = GI.homeLine(m);
  if ((!isNum(hp) || !isNum(ap)) && isNum(m.total) && isNum(ml)) { hp = (Number(m.total) - ml) / 2; ap = (Number(m.total) + ml) / 2; }
  if (!isNum(hp) || !isNum(ap)) return '';
  const t = (team, pts) => '<div class="pj-t"><span class="pj-s" style="color:' + GI.teamColour(team) + '">' + GI.num(pts, 1) + '</span><span class="pj-n">' + esc(GI.teamShort(team)) + '</span></div>';
  return '<div class="proj">' + t(g.away, ap) + '<span class="pj-dash">–</span>' + t(g.home, hp) + '</div>';
}
function injuriesBlock(g) {
  const inj = g.injuries || {};
  const side = s => {
    const list = R(inj[s]);
    if (!list.length) return GI.muted('No injuries reported.');
    return GI.tableHTML([{ label: 'Player' }, { label: 'Pos' }, { label: 'Status' }, { label: 'Detail' }, { label: 'Impact', align: 'right', title: 'Model points of margin (negative hurts this team)' }],
      list.map(x => {
        const stc = String(x.status || '').toLowerCase();
        return [{ html: x.pid ? GI.playerLink(x.pid, x.name ? { name: x.name } : null) : esc(x.name || '—'), v: x.name || GI.playerName(x.pid) }, x.pos || GI.player(x.pid).pos || '—',
          { html: '<span class="inj-st ' + esc(stc.split(' ')[0]) + '">' + esc(x.status || '—') + '</span>', v: x.status }, x.detail || x.injury || '—',
          { html: isNum(x.impact) ? GI.ptsEdge(x.impact, 1) : '—', v: x.impact }];
      }), { compact: true, cls: 'inj-table' });
  };
  const qb = g.qb_status || {};
  const qbLine = s => { const q = qb[s]; if (!q) return ''; return '<div class="section-note">QB: ' + GI.qbText(q) + (q.status ? ' · ' + esc(q.status) : '') + (isNum(q.value) ? ' · value ' + GI.signed(q.value, 3) + ' EPA/play' : '') + '</div>'; };
  if (!R(inj.home).length && !R(inj.away).length && !qb.home && !qb.away) return '';
  return GI.card('Injuries and QB status', 'from the injury report; impact is our model\'s', '<div class="grid-2" style="gap:0">' +
    ['away', 'home'].map(s => '<div><div class="box-head">' + GI.teamBar(g[s]) + esc(GI.teamName(g[s])) + '</div>' + qbLine(s) + side(s) + '</div>').join('') + '</div>');
}
function contextBlock(g) {
  const kv = (k, v) => (v === null || v === undefined || v === '' ? '' : '<div class="gm-kv"><span>' + esc(k) + '</span><strong>' + v + '</strong></div>');
  const w = g.weather || {};
  const c = g.coaches || { home: g.home_coach, away: g.away_coach };
  const venue = kv('Stadium', esc(g.stadium_name || g.stadium || '')) + kv('Roof', esc(g.roof || '')) + kv('Surface', esc(g.surface || '')) + kv('Game ID', '<code>' + esc(g.game_id) + '</code>');
  const weather = kv('Temperature', isNum(w.temp) ? Math.round(w.temp) + '°F' : '') + kv('Wind', isNum(w.wind) ? Math.round(w.wind) + ' mph' : '') + kv('Conditions', esc(w.desc || w.conditions || '')) +
    kv('Effect on total', isNum(w.total_effect) ? GI.signed(w.total_effect, 1) + ' pts' : '');
  const people = kv('Referee', esc(g.referee || '')) + kv(GI.teamAbbr(g.away) + ' head coach', c && c.away ? GI.coachLink(c.away) : '') + kv(GI.teamAbbr(g.home) + ' head coach', c && c.home ? GI.coachLink(c.home) : '') +
    kv('Rest', g.rest ? esc(GI.teamAbbr(g.away)) + ' ' + esc(g.rest.away) + 'd · ' + esc(GI.teamAbbr(g.home)) + ' ' + esc(g.rest.home) + 'd' : '');
  if (!venue && !weather && !people) return '';
  return GI.card('Venue, weather and officials', '', '<div class="gm-ctx"><div><div class="gm-ctx-h">Venue</div>' + (venue || GI.muted('—')) + '</div><div><div class="gm-ctx-h">Weather</div>' +
    (GI.weatherText(g.weather, g.roof) === 'Dome' ? kv('Roof', 'Dome') : (weather || GI.muted('No forecast yet.'))) + '</div><div><div class="gm-ctx-h">People</div>' + (people || GI.muted('—')) + '</div></div>');
}
function rankPct(r) { return isNum(r) ? Math.max(2, Math.min(100, (33 - Number(r)) / 32 * 100)) : null; }
function matchupRows(g, m) {
  const H = GI.teamAbbr(g.home), A = GI.teamAbbr(g.away);
  const out = [];
  [['home_off', H, A], ['away_off', A, H]].forEach(x => {
    const o = m[x[0]];
    if (!o) return;
    ['pass', 'rush'].forEach(u => {
      const v = o[u];
      if (!v) return;
      const homeOff = x[0] === 'home_off';
      const offV = { v: v.off, pct: rankPct(v.off_rank), r: v.off_rank }, defV = { v: v.def, pct: rankPct(v.def_rank), r: v.def_rank };
      const hv = homeOff ? offV : defV, av = homeOff ? defV : offV;
      out.push({ label: x[1] + ' ' + u + ' O v ' + x[2] + ' ' + u + ' D', home: hv.v, home_pct: hv.pct, away: av.v, away_pct: av.pct,
        home_rank: hv.r, away_rank: av.r });
    });
  });
  return out;
}
function matchupsBlock(g) {
  let list = g.matchups && !Array.isArray(g.matchups) && (g.matchups.home_off || g.matchups.away_off) ? matchupRows(g, g.matchups) : R(g.matchups || g.unit_matchups);
  if (!list.length && g.units && g.units.home) {
    const lab = { pass_off: 'Pass offence', rush_off: 'Rush offence', pass_def: 'Pass defence', rush_def: 'Rush defence', st: 'Special teams' };
    list = Object.keys(lab).map(k => ({ label: lab[k], home: g.units.home[k], away: g.units.away[k] }));
  }
  if (!list.length) return '';
  const vals = [];
  list.forEach(x => { if (isNum(x.home)) vals.push(Math.abs(x.home)); if (isNum(x.away)) vals.push(Math.abs(x.away)); });
  const max = Math.max.apply(null, vals.concat([0.01]));
  const bar = (v, pc, colour, left) => {
    const w = isNum(pc) ? Math.max(3, Math.min(100, pc)) : (isNum(v) ? Math.max(3, 50 + 50 * v / max) : 0);
    return '<span class="um-bar' + (left ? ' l' : '') + '"><span style="width:' + w.toFixed(0) + '%;background:' + colour + '"></span></span>';
  };
  const fv = (v, f, r) => (isNum(v) ? (f ? GI.fmtVal(v, f) : GI.signed(v, Math.abs(v) < 1 ? 3 : 1)) : '—') + (isNum(r) ? '<span class="sub-line">' + GI.ordinal(r) + '</span>' : '');
  return GI.card('Unit matchups', 'opponent-adjusted EPA per play (bars: league percentile)', '<div class="um-row"><span class="um-v">' + GI.teamBar(g.away) + esc(GI.teamAbbr(g.away)) + '</span><span></span><span></span><span></span><span class="um-v r">' + esc(GI.teamAbbr(g.home)) + GI.teamBar(g.home) + '</span></div>' +
    list.map(x => '<div class="um-row"><span class="um-v">' + fv(x.away, x.fmt, x.away_rank) + '</span>' + bar(x.away, x.away_pct, GI.teamColour(g.away), true) + '<span class="um-lbl">' + esc(x.label || x.unit || '') + '</span>' +
      bar(x.home, x.home_pct, GI.teamColour(g.home), false) + '<span class="um-v r">' + fv(x.home, x.fmt, x.home_rank) + '</span></div>').join('') +
    '<div class="chart-note">EPA per play: offence gained, defence allowed (lower is better for a defence); small print: league rank; bars: rank as a percentile.</div>');
}
function normCdf(z) {
  const t = 1 / (1 + 0.2316419 * Math.abs(z));
  const d = 0.3989423 * Math.exp(-z * z / 2);
  const p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))));
  return z > 0 ? 1 - p : p;
}
function normDist(mu, sd, lo, hi) {
  const out = {};
  for (let k = lo; k <= hi; k++) out[k] = Math.round((normCdf((k + 0.5 - mu) / sd) - normCdf((k - 0.5 - mu) / sd)) * 10000) / 10000;
  return out;
}
/* Fill margin/total distributions and cover/over probabilities from sigma when the payload has only the moments. */
function withDists(m0, ln) {
  const m = Object.assign({}, m0);
  const mu = isNum(m.margin) ? Number(m.margin) : (isNum(GI.homeLine(m)) ? -GI.homeLine(m) : null);
  m.approx = false;
  if (!m.margin_dist && isNum(mu) && isNum(m.sigma)) { m.margin_dist = normDist(mu, Number(m.sigma), Math.floor(mu - 3 * m.sigma), Math.ceil(mu + 3 * m.sigma)); m.approx = true; }
  if (!m.total_dist && isNum(m.total) && isNum(m.sigma_total)) { m.total_dist = normDist(Number(m.total), Number(m.sigma_total), Math.max(0, Math.floor(m.total - 3 * m.sigma_total)), Math.ceil(m.total + 3 * m.sigma_total)); m.approx = true; }
  const l = GI.homeLine(ln || {});
  if (!isNum(m.p_cover_home) && isNum(mu) && isNum(m.sigma) && isNum(l)) m.p_cover_home = 1 - normCdf((-l - mu) / Number(m.sigma));
  if (!isNum(m.p_over) && isNum(m.total) && isNum(m.sigma_total) && ln && isNum(ln.total)) m.p_over = 1 - normCdf((Number(ln.total) - m.total) / Number(m.sigma_total));
  return m;
}
function previewTab(g, pre0) {
  const pre = Object.assign({}, pre0, { model: withDists(pre0.model || {}, pre0.line || g.line) });
  if (!pre.priced_at && pre.model.priced_at) pre.priced_at = pre.model.priced_at;
  const m = pre.model;
  const hasModel = isNum(m.p_home) || isNum(m.total) || isNum(GI.homeLine(m));
  const S = GI.gameSeason(g.game_id);
  let h = '';
  if (hasModel) {
    h += '<div class="grid-32"><div>' + GI.card('Model v market v line', pre.priced_at ? 'priced ' + esc(GI.fmtStamp(pre.priced_at)) + (GI.isPre(g) ? '' : ' · frozen at kickoff') : '', mvmBig(g, pre) +
      '<div class="chart-note">Spreads are shown for the favourite (negative = favoured). The market is the de-vigged prediction-market price; the line is the sportsbook line as ESPN shows it. For information only.</div>') + '</div>' +
      '<div>' + GI.card('Projected score', 'model mean', projBlock(g, m) || GI.muted('No projection.')) + '</div></div>';
    const md = m.margin_dist || m.margin, td = m.total_dist;
    if (md || td) {
      h += '<div class="grid-2">' +
        GI.card('Margin distribution', esc(GI.teamAbbr(g.home)) + ' points minus ' + esc(GI.teamAbbr(g.away)) + ' · dashed: the line' + (m.approx ? ' · normal approximation, sd ' + GI.num(m.sigma, 1) : ''), '<div id="gm-md"></div>') +
        GI.card('Total points distribution', 'dashed: the line · dotted: our mean' + (m.approx && isNum(m.sigma_total) ? ' · normal approximation, sd ' + GI.num(m.sigma_total, 1) : ''), '<div id="gm-td"></div>') + '</div>';
    }
  } else {
    h += GI.card('Model v market v line', '', GI.muted('The pre-game price is not available for this game.'));
  }
  h += injuriesBlock(g) + matchupsBlock(g) + contextBlock(g);
  if (!h) h = GI.muted('No preview for this game.');
  return { html: h, after: root => {
    const md = m.margin_dist || m.margin, td = m.total_dist;
    const ln = pre.line || g.line || {};
    const lLine = GI.homeLine(ln);
    if (md && root.querySelector('#gm-md')) GI.charts.distBars(root.querySelector('#gm-md'), md, { signed: true, split: 0, colours: [GI.teamColour(g.home), GI.teamColour(g.away)],
      line: isNum(lLine) ? -lLine : null, exp: isNum(GI.homeLine(m)) ? -GI.homeLine(m) : null, actual: GI.isFinal(g) && isNum(g.hs) ? g.hs - g.as : null, unit: 'pts', height: 230 });
    if (td && root.querySelector('#gm-td')) GI.charts.distBars(root.querySelector('#gm-td'), td, { line: ln.total, exp: m.total, actual: GI.isFinal(g) && isNum(g.hs) ? Number(g.hs) + Number(g.as) : null, unit: 'pts', height: 230 });
    void S;
  } };
}

// ── flow ───────────────────────────────────────────────────────────────────

function fourthTable(g, fd) {
  if (!fd.length) return '';
  const cols = [{ label: 'When' }, { label: 'Team' }, { label: 'Situation' }, { label: 'Call' }, { label: 'Model' }, { label: 'WP go · punt · FG', sortable: false, title: 'Our win probability for the team on fourth down, by option' },
    { label: 'WP lost', align: 'right', title: 'Win probability given up against the best option, percentage points' }, { label: 'Grade' }, { label: 'Play', sortable: false }];
  const wpv = (x, on) => (isNum(x) ? (on ? '<b>' + GI.pct(x, 0) + '</b>' : GI.pct(x, 0)) : '—');
  const rows = fd.map(f => {
    const opp = GI.otherTeam(g, f.team);
    const c = String(f.choice || '').toLowerCase();
    return { cells: [
      { html: esc(GI.clockText(f.qtr, f.clock)), v: (Number(f.qtr) || 0) * 10000 - (parseInt(String(f.clock).replace(':', ''), 10) || 0) },
      { html: GI.teamLink(f.team, { abbr: true }), v: f.team },
      { html: esc('4th & ' + (isNum(f.dist) ? Math.round(f.dist) : '?') + (isNum(f.yl100) ? ' at ' + GI.fieldPos(f.yl100, f.team, opp) : '')), v: f.dist },
      esc(GI.choiceLabel(f.choice)), esc(GI.choiceLabel(f.rec || f.recommendation)),
      { html: '<span class="fd-wp">' + wpv(f.wp_go, /^go|run|pass/.test(c)) + ' · ' + wpv(f.wp_punt, /punt/.test(c)) + ' · ' + wpv(f.wp_fg, /fg|field/.test(c)) + '</span>' },
      { html: isNum(f.wp_lost) ? GI.num(Math.abs(f.wp_lost) * 100, 1) : '—', v: f.wp_lost },
      { html: GI.gradePill(f.grade, f.wp_lost) || '—', v: GI.gradeOf(f.grade, f.wp_lost).key },
      { html: esc(String(f.desc || '').slice(0, 160)), cls: 'fd-desc' }
    ] };
  });
  return GI.card('Fourth downs', fd.length + ' decision' + (fd.length === 1 ? '' : 's') + ' · graded by win probability lost against the best option · <a href="#/fourth-downs">every 4th down this season →</a>',
    GI.tableHTML(cols, rows, { cls: 'fd-table', compact: true }) +
    '<div class="legend-row"><span><i class="legend-sw" style="background:' + GI.C.good + '"></i>Right call (A–B, ≤ 1.5 pp lost)</span><span><i class="legend-sw" style="background:' + GI.C.close + '"></i>Close (C, 1.5–3 pp)</span><span><i class="legend-sw" style="background:' + GI.C.bad + '"></i>Mistake (D–F, &gt; 3 pp)</span></div>');
}
function keyPlaysBlock(g, kp) {
  if (!kp.length) return '';
  return GI.card('Key plays', 'by win probability added (numbered on the chart)', '<div class="kp-list">' + kp.map((p, k) =>
    '<div class="kp-row"><span class="kp-n">' + (k + 1) + '</span><span class="kp-clk">' + esc(GI.clockText(p.qtr, p.clock)) + '</span><span class="kp-d">' + (p.team ? GI.teamBar(p.team) : '') + esc(p.desc || '') +
    (isNum(p.epa) ? ' <span class="muted-inline">· EPA ' + GI.signed(p.epa, 2) + '</span>' : '') + '</span><span class="kp-v ' + (isNum(p.wpa) && p.wpa > 0 ? 'edge-pos' : 'edge-neg') + '" title="Home win probability added">' +
    (isNum(p.wpa) ? GI.signed(p.wpa * 100, 1) + ' pp' : '') + '</span></div>').join('') + '</div><div class="chart-note">WPA is from ' + esc(GI.teamAbbr(g.home)) + '\'s side (home).</div>');
}
const AWARD_TITLE = { home_ball: 'Best player', away_ball: 'Best player', play_of_game: 'Play of the game', mvp: 'Player of the game', coach: 'Best 4th-down call' };
function awardsOf(g) {
  const a = g.awards;
  if (!a) return [];
  if (Array.isArray(a)) return a;
  return Object.keys(a).filter(k => a[k] && typeof a[k] === 'object').map(k => {
    const x = a[k];
    const side = /^home/.test(k) ? 'home' : /^away/.test(k) ? 'away' : null;
    const team = x.team || (side ? g[side] : null);
    const value = x.value !== undefined ? x.value : isNum(x.wpa) ? GI.signed(x.wpa * 100, 1) + ' pp WPA' : isNum(x.epa) ? GI.signed(x.epa, 2) + ' EPA' : null;
    return { title: x.title || ((AWARD_TITLE[k] || GI.titleCase(k)) + (side ? ' · ' + GI.teamAbbr(team) : '')), pid: x.pid, name: x.name, team: team, coach: x.coach,
      value: value, why: x.why || (x.pid ? '' : x.desc || '') };
  });
}
function awardsBlock(g) {
  const list = awardsOf(g);
  if (!list.length) return '';
  return GI.card('Awards', 'from our play values', '<div class="awards">' + list.map(a =>
    '<div class="award"' + (a.team ? ' style="border-top-color:' + GI.teamColour(a.team) + '"' : '') + '><span class="aw-title">' + esc(a.title || a.award || '') + '</span>' +
    '<span class="aw-who">' + (a.pid ? GI.playerLink(a.pid, a.name ? { name: a.name } : null) : a.coach ? GI.coachLink(a.coach) : a.team ? GI.teamLink(a.team) : esc(a.name || '')) + (a.pid && a.team ? '<span class="pl-team">' + esc(GI.teamAbbr(a.team)) + '</span>' : '') + '</span>' +
    (a.value !== undefined && a.value !== null ? '<span class="aw-val">' + esc(isNum(a.value) ? GI.signed(a.value, 2) : a.value) + '</span>' : '') + (a.why ? '<span class="aw-why">' + esc(String(a.why).slice(0, 200)) + '</span>' : '') + '</div>').join('') + '</div>');
}
function driveTable(g, drives) {
  const D = GI.charts.driveRows(drives);
  if (!D.length) return '';
  return GI.tableHTML([{ label: '#', align: 'right' }, { label: 'Team' }, { label: 'Start' }, { label: 'Field' }, { label: 'Plays', align: 'right' }, { label: 'Yds', align: 'right' }, { label: 'Time', align: 'right' },
    { label: 'Result' }, { label: 'EPA', align: 'right' }], D.map(d => {
    const r = GI.driveResult(d.result);
    const opp = GI.otherTeam(g, d.team);
    return [d.n, { html: GI.teamLink(d.team, { abbr: true }), v: d.team }, { html: esc(GI.clockText(d.qtr, d.clock)), v: d.n }, { html: esc(GI.fieldPos(d.start, d.team, opp)), v: d.start },
      isNum(d.plays) ? d.plays : '—', isNum(d.yards) ? Math.round(d.yards) : '—', d.time ? GI.fmtClock(d.time) : '—',
      { html: GI.pill(r.label, r.colour), v: r.label }, { html: isNum(d.epa) ? GI.signed(d.epa, 2) : '—', v: d.epa }];
  }), { compact: true });
}
function flowTab(g, pre, plays) {
  const fd = fourthOf(g, plays);
  const sc = scoringOf(g, plays);
  const kp = keyPlaysOf(g, plays);
  const wp = wpSeries(g, plays, pre);
  const drives = g.drives;
  const hasWp = wp.ours.length >= 2 || wp.espn.length >= 2;
  const hasDrives = GI.charts.driveRows(drives).length > 0;
  let h = '';
  h += GI.card('Win probability', esc(GI.teamAbbr(g.home)) + ' (home) · ' + (wp.name === 'Our model' ? 'ours' : esc(wp.name)) + ' solid' + (wp.espn.length ? ', ESPN dotted' : '') + ' · ◆ 4th downs by grade · ● scores' +
    (wp.name !== 'Our model' ? ' · our WP model is not fitted yet, so nflfastR\'s published WP is shown' : ''), hasWp ? '<div id="gm-wp"></div>' +
    '<div class="legend-row"><span><i class="legend-sw" style="background:' + GI.C.good + '"></i>4th down: right call</span><span><i class="legend-sw" style="background:' + GI.C.close + '"></i>close</span><span><i class="legend-sw" style="background:' + GI.C.bad + '"></i>mistake</span><span>numbers: key plays</span></div>'
    : GI.muted(GI.isPre(g) ? 'The win-probability chart starts at kickoff.' : 'No win-probability path for this game yet.'));
  h += GI.card('Drive chart', 'every drive from its start to its end, own goal line on the left; colour = result', hasDrives ? '<div id="gm-drives"></div><details class="pad0"><summary class="muted-inline">Drive table</summary>' + driveTable(g, drives) + '</details>'
    : GI.muted(GI.isPre(g) ? 'Drives appear at kickoff.' : 'No drives yet.'));
  h += fourthTable(g, fd) + keyPlaysBlock(g, kp) + awardsBlock(g);
  return { html: h, after: root => {
    if (hasWp && root.querySelector('#gm-wp')) GI.charts.wpChart(root.querySelector('#gm-wp'), wp.ours, { espn: wp.espn, mainName: wp.name, home: g.home, away: g.away, fourth: fd, scoring: sc, top: kp, height: 340,
      market: pre && pre.market && isNum(pre.market.p_home) ? pre.market.p_home : null });
    if (hasDrives && root.querySelector('#gm-drives')) GI.charts.driveChart(root.querySelector('#gm-drives'), drives, { home: g.home, away: g.away });
  } };
}

// ── play-by-play ───────────────────────────────────────────────────────────

function pbpTab(g, plays) {
  if (!plays.length) return { html: GI.card('Play-by-play', '', GI.muted(GI.isPre(g) ? 'Plays appear at kickoff.' : 'No plays yet.')), after: null };
  const f = FILT[g.game_id] = FILT[g.game_id] || { team: 'all', qtr: 'all', kind: 'all', epa: '0', wpa: '0', q: '' };
  const opt = (v, l, cur) => '<option value="' + esc(v) + '"' + (String(v) === String(cur) ? ' selected' : '') + '>' + esc(l) + '</option>';
  const qtrs = [];
  plays.forEach(p => { if (isNum(p.qtr) && qtrs.indexOf(Number(p.qtr)) < 0) qtrs.push(Number(p.qtr)); });
  const ctl = '<div class="pbp-ctl">' +
    '<label>Team<select data-f="team">' + opt('all', 'Both', f.team) + opt(g.away, GI.teamAbbr(g.away), f.team) + opt(g.home, GI.teamAbbr(g.home), f.team) + '</select></label>' +
    '<label>Quarter<select data-f="qtr">' + opt('all', 'All', f.qtr) + qtrs.map(q => opt(q, GI.qtrLabel(q), f.qtr)).join('') + '</select></label>' +
    '<label>Plays<select data-f="kind">' + [['all', 'All'], ['pass', 'Passes'], ['run', 'Runs'], ['special', 'Special teams'], ['score', 'Scoring'], ['fourth', '4th downs'], ['turnover', 'Turnovers'], ['penalty', 'Penalties']].map(x => opt(x[0], x[1], f.kind)).join('') + '</select></label>' +
    '<label>|EPA| at least<select data-f="epa">' + [['0', 'Any'], ['0.5', '0.5'], ['1', '1'], ['2', '2'], ['3', '3']].map(x => opt(x[0], x[1], f.epa)).join('') + '</select></label>' +
    '<label>|WPA| at least<select data-f="wpa">' + [['0', 'Any'], ['0.02', '2 pp'], ['0.05', '5 pp'], ['0.1', '10 pp']].map(x => opt(x[0], x[1], f.wpa)).join('') + '</select></label>' +
    '<label>Search<input type="search" data-f="q" value="' + esc(f.q) + '" placeholder="Player or word"></label><span class="pbp-count muted-inline"></span></div>';
  const html = GI.card('Play-by-play', 'EPA: expected points added for the offence · WPA and WP from ' + esc(GI.teamAbbr(g.home)) + '\'s side', ctl + '<div class="pbp-wrap"></div>');
  const draw = root => {
    const wrap = root.querySelector('.pbp-wrap');
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
      if (q) {
        const names = (Array.isArray(p.players) ? p.players : []).map(id => GI.playerName(id)).join(' ');
        if ((p.desc + ' ' + names).toLowerCase().indexOf(q) < 0) return false;
      }
      return true;
    });
    const cnt = root.querySelector('.pbp-count');
    if (cnt) cnt.textContent = list.length + ' of ' + plays.length + ' plays';
    let lastQ = null;
    let body = '';
    list.forEach(p => {
      if (String(p.qtr) !== String(lastQ)) { body += '<tr class="pbp-q"><td colspan="7">' + esc(GI.qtrLabel(p.qtr, true)) + '</td></tr>'; lastQ = p.qtr; }
      const opp = GI.otherTeam(g, p.team);
      const sit = p.down ? GI.downDist(p.down, p.dist, p.yl100) + (isNum(p.yl100) ? ' · ' + GI.fieldPos(p.yl100, p.team, opp) : '') : (isNum(p.yl100) ? GI.fieldPos(p.yl100, p.team, opp) : '');
      const cls = [isScore(p) ? 'pbp-score' : '', Number(p.down) === 4 ? 'pbp-4th' : '', isTurnover(p) ? 'pbp-to' : ''].filter(Boolean).join(' ');
      body += '<tr' + (cls ? ' class="' + cls + '"' : '') + '><td>' + esc(GI.fmtClock(p.clock)) + '</td><td>' + (p.team ? GI.teamBar(p.team) + esc(GI.teamAbbr(p.team)) : '') + '</td>' +
        '<td class="pbp-sit">' + esc(sit) + '</td><td class="pbp-desc">' + esc(p.desc) + '</td>' +
        '<td class="num ' + (isNum(p.epa) ? (p.epa > 0 ? 'edge-pos' : p.epa < 0 ? 'edge-neg' : '') : '') + '">' + (isNum(p.epa) ? GI.signed(p.epa, 2) : '—') + '</td>' +
        '<td class="num">' + (isNum(p.wpa) ? GI.signed(p.wpa * 100, 1) : '—') + '</td>' +
        '<td class="num">' + (isNum(p.wp) ? GI.pct(p.wp, 0) : '—') + (isNum(p.espn) ? '<span class="sub-line">ESPN ' + GI.pct(p.espn, 0) + '</span>' : '') + '</td></tr>';
    });
    wrap.innerHTML = list.length ? '<div class="table-wrap"><table class="wc-table pbp-table compact"><thead><tr><th>Clock</th><th>Team</th><th>Situation</th><th>Play</th><th class="num" title="Expected points added">EPA</th>' +
      '<th class="num" title="Home win probability added, pp">WPA</th><th class="num" title="Home win probability after the play: ours (ESPN below)">WP</th></tr></thead><tbody>' + body + '</tbody></table></div>'
      : GI.muted('No plays match these filters.');
  };
  return { html: html, after: root => {
    root.querySelectorAll('.pbp-ctl [data-f]').forEach(x => {
      const ev = x.tagName === 'INPUT' ? 'input' : 'change';
      x.addEventListener(ev, () => { f[x.dataset.f] = x.value; draw(root); });
    });
    draw(root);
  } };
}

// ── box score ──────────────────────────────────────────────────────────────

const BOX_ORDER = ['passing', 'rushing', 'receiving', 'defense', 'defence', 'kicking', 'punting', 'returns', 'team'];
const BOX_TITLE = { passing: 'Passing', rushing: 'Rushing', receiving: 'Receiving', defense: 'Defence', defence: 'Defence', kicking: 'Kicking', punting: 'Punting', returns: 'Returns', team: 'Team stats' };
const COL_LABEL = { pid: 'Player', player: 'Player', team: 'Team', cmp: 'Cmp', att: 'Att', yds: 'Yds', td: 'TD', int: 'Int', sacks: 'Sk', car: 'Car', rec: 'Rec', tgt: 'Tgt',
  epa: 'EPA', epa_per_play: 'EPA/play', epa_per_db: 'EPA/db', epa_per_target: 'EPA/tgt', epa_per_carry: 'EPA/car', cpoe: 'CPOE', ttt: 'Time to throw', adot: 'aDOT',
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
  const cols = sec.cols || sec.fields || sec.columns || (R(sec)[0] ? Object.keys(R(sec)[0]) : []);
  const list = R(sec);
  if (!list.length) return '';
  if (key === 'team' || (cols[0] === 'stat' && cols.indexOf('home') >= 0)) {
    return GI.card(BOX_TITLE[key] || GI.titleCase(key), note || '', GI.tableHTML([{ label: '' , sortable: false }, { label: GI.teamAbbr(g.away), align: 'right', sortable: false }, { label: GI.teamAbbr(g.home), align: 'right', sortable: false }],
      list.map(r => [{ html: esc(r.stat || r.label || '') }, { html: fmtBox(String(r.stat || '').toLowerCase().replace(/\s+/g, '_'), r.away), align: 'right' }, { html: fmtBox(String(r.stat || '').toLowerCase().replace(/\s+/g, '_'), r.home), align: 'right' }]), { compact: true, cls: 'box-table' }));
  }
  const show = cols.filter(c => c !== 'team' && c !== 'name');
  if (show.indexOf('pid') < 0 && cols.indexOf('name') >= 0) show.unshift('name');
  const teams = [g.away, g.home];
  const tbl = t => {
    const rows = list.filter(r => !r.team || String(r.team) === String(t));
    if (!rows.length) return '';
    return '<div class="box-head">' + GI.teamBar(t) + esc(GI.teamName(t)) + '</div>' + GI.tableHTML(show.map(c => ({ label: COL_LABEL[c] || GI.titleCase(c), align: c === 'pid' || c === 'player' ? null : 'right',
      title: NGS_COLS.test(c) ? 'NFL Next Gen Stats' : null })), rows.map(r => show.map(c => {
      if (c === 'name') return { html: esc(r.name), v: r.name };
      if (c === 'pid' || c === 'player') { const id = r.pid || r.player; return { html: /^\d\d-\d+/.test(String(id)) ? GI.playerLink(id, r.name ? { name: r.name } : null) : esc(r.name || id), v: r.name || GI.playerName(id) }; }
      return { html: fmtBox(c, r[c]), v: r[c] };
    })), { compact: true, cls: 'box-table' });
  };
  const hasTeam = list.some(r => r.team);
  return GI.card(BOX_TITLE[key] || GI.titleCase(key), note || '', hasTeam ? teams.map(tbl).join('') : tbl(null));
}
function boxBySection(g, b) {
  if (!b || !b.home || !b.away || typeof b.home !== 'object' || b.home.cols || Array.isArray(b.home)) return b || {};
  const out = {};
  ['away', 'home'].forEach(side => Object.keys(b[side] || {}).forEach(sec => {
    const rows = R(b[side][sec]).map(r => Object.assign({ team: g[side] }, r));
    out[sec] = (out[sec] || []).concat(rows);
  }));
  if (b.team) out.team = b.team;
  return out;
}
function boxTab(g) {
  const box = boxBySection(g, g.box);
  const ngs = g.ngs || {};
  const keys = Object.keys(box);
  if (!keys.length && !Object.keys(ngs).length) return { html: GI.card('Box score', '', GI.muted(GI.isPre(g) ? 'The box score fills in from kickoff.' : 'No box score yet.')), after: null };
  keys.sort((a, b) => { const ia = BOX_ORDER.indexOf(a), ib = BOX_ORDER.indexOf(b); return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib); });
  let h = keys.map(k => boxSection(g, k, box[k], /passing|rushing|receiving/.test(k) ? 'with EPA and our advanced columns' : '')).join('');
  h += Object.keys(ngs).map(k => boxSection(g, k, ngs[k], 'NFL Next Gen Stats (via nflverse), credited; informational, non-commercial use')).join('');
  return { html: h + '<div class="chart-note">EPA is our expected points added. Columns marked as NGS in their tooltip are NFL Next Gen Stats; charting columns are FTN Data via nflverse (CC BY-SA 4.0).</div>', after: null };
}

// ── page ───────────────────────────────────────────────────────────────────

GI.route('game', function (el, params) {
  const id = params.id;
  return GI.loadGame(id).then(g0 => {
    if (!el.isConnected) return;
    const meta = GI.parseGameId(id);
    if (!GI.ok(g0)) {
      const card = (GI.index() && ['games', 'live', 'recent'].reduce((acc, k) => acc || (GI.index()[k] || []).find(c => c && c.game_id === id), null)) || null;
      el.innerHTML = GI.pageHead(meta ? GI.teamName(meta.away) + ' at ' + GI.teamName(meta.home) : 'Game ' + id, meta ? GI.weekLink(meta.season, meta.week) : '', meta ? GI.weekNav(meta.season, meta.week) : '') +
        (card ? '<div class="gc-grid" style="padding:0 0 14px;max-width:360px">' + GI.gameCard(card) + '</div>' : '') +
        GI.notBuilt('The game centre for ' + id, g0) + (meta && meta.season < GI.currentSeason() - 1 ? GI.muted('Game pages are kept for the current and the previous season.') : '');
      return;
    }
    const g = Object.assign({}, g0.card || {}, g0);
    const gm = g0.game && typeof g0.game === 'object' ? g0.game : null;
    if (gm) {
      ['stadium', 'stadium_name', 'roof', 'surface', 'referee', 'overtime', 'div_game', 'espn_id', 'date'].forEach(k => { if ((g[k] === undefined || g[k] === null) && gm[k] !== undefined) g[k] = gm[k]; });
      g.weather = Object.assign({ temp: gm.temp, wind: gm.wind, roof: gm.roof }, (g.card || {}).weather || g.weather || {});
      if (!g.coaches) g.coaches = { home: gm.home_coach, away: gm.away_coach };
      if (!g.rest && isNum(gm.home_rest)) g.rest = { home: gm.home_rest, away: gm.away_rest };
    }
    if (!g.home && meta) { g.home = meta.home; g.away = meta.away; }
    if (!g.game_id) g.game_id = id;
    const pre = Object.assign({}, g.pregame || g.pre || { model: g.model, market: g.market, line: g.line });
    if (!pre.model) pre.model = g.model || {};
    if (!pre.market) pre.market = g.market || null;
    if (!pre.line) pre.line = g.line || null;
    const plays = playsOf(g);
    const st = GI.gameState(g);
    const live = st === 'live' || st === 'half';
    const tabs = [['preview', 'Preview'], ['flow', 'Game flow'], ['plays', 'Play-by-play'], ['box', 'Box score']];
    const q = (params.query || {}).tab;
    let tab = TAB[id] || (tabs.some(t => t[0] === q) ? q : (st === 'pre' ? 'preview' : 'flow'));
    document.title = GI.teamAbbr(g.away) + ' @ ' + GI.teamAbbr(g.home) + ' · ' + GI.SITE;
    el.innerHTML = header(g, pre, plays) + '<div class="seg-tabs gm-tabs">' + tabs.map(t => '<a data-tab="' + t[0] + '"' + (t[0] === tab ? ' class="active"' : '') + '>' + esc(t[1]) + '</a>').join('') + '</div><div id="gm-body"></div>';
    const body = el.querySelector('#gm-body');
    const show = k => {
      tab = k; TAB[id] = k;
      el.querySelectorAll('.gm-tabs a').forEach(a => a.classList.toggle('active', a.dataset.tab === k));
      const out = k === 'preview' ? previewTab(g, pre) : k === 'flow' ? flowTab(g, pre, plays) : k === 'plays' ? pbpTab(g, plays) : boxTab(g);
      if (typeof Plotly !== 'undefined') body.querySelectorAll('.js-plotly-plot').forEach(n => { try { Plotly.purge(n); } catch (e) { /* gone */ } });
      body.innerHTML = out.html;
      GI.sortable(body);
      if (out.after) out.after(body);
    };
    el.querySelectorAll('.gm-tabs a').forEach(a => a.addEventListener('click', () => show(a.dataset.tab)));
    show(tab);
    GI.setMeta(live ? '<span class="live-dot"></span> live · refreshed every 30 seconds' : '');
    if (live) GI.liveRefresh([GI.gamePath(id)], 30000);
  });
});

})(window.GI);
