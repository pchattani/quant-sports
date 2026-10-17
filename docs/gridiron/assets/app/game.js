/* The Quant Gridiron — the game centre (#/game/<game_id>).
 * Header: teams, score, clock, possession on a field strip, live win probability, the linescore.
 * Tabs: Preview (model v market v line, projected score, margin and total distributions, unit matchups,
 * injuries, venue and weather) · Game flow (win probability ours v ESPN with every 4th down graded,
 * scoring and key plays; the drive chart; 4th-down decisions; awards) · Play-by-play (filters, search) ·
 * Box score (with EPA and Next Gen Stats columns). Reads <S>/games/<game_id>.json; every block is optional. */
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
function header(g, pre, plays) {
  const st = GI.gameState(g);
  const live = st === 'live' || st === 'half', fin = st === 'final';
  const S = GI.gameSeason(g.game_id) || GI.state.season;
  const w = isNum(g.week) ? Number(g.week) : GI.gameWeek(g.game_id);
  const hs = isNum(g.hs) ? Number(g.hs) : null, as = isNum(g.as) ? Number(g.as) : null;
  const m = (pre && pre.model) || g.model || {};
  const pre0 = isNum(m.p_home) ? Number(m.p_home) : null;
  const pNow = live && isNum(g.wp_home) ? Number(g.wp_home) : pre0;
  const coaches = g.coaches || {};
  const qbs = g.qbs || {};
  const qbOf = side => { const q = (g.qb_status || {})[side] || qbs[side]; return q ? GI.qbText(q) : ''; };
  const side = (t, s, score, lost) => {
    const p = pNow === null ? null : (s === 'home' ? pNow : 1 - pNow);
    const sub = [s === 'home' ? 'Home' : 'Away', qbOf(s) ? 'QB ' + qbOf(s) : '', coaches[s] ? 'HC ' + GI.coachLink(coaches[s]) : ''].filter(Boolean).join(' · ');
    return '<div class="gi-score-team ' + s + (fin && lost ? ' lost' : '') + '">' + GI.mark(t, 'lg') +
      '<div style="min-width:0"><a class="nm gi-link" href="' + GI.teamHref(t, S) + '">' + esc(GI.teamName(t)) + '</a>' + (live && String(g.possession) === String(t) ? ' <span class="gi-poss" title="Possession" style="color:var(--brand)">●</span>' : '') +
      '<div class="rec">' + sub + '</div>' + (p !== null ? '<div class="rec">' + (fin ? 'pre-game ' : live ? 'live ' : '') + 'win <b style="color:var(--ink-1);font-family:var(--font-num)">' + GI.pct(fin ? (s === 'home' ? pre0 : 1 - pre0) : p, 0) + '</b></div>' : '') + '</div>' +
      '<span class="sc">' + (score === null || st === 'pre' ? '' : esc(score)) + '</span></div>';
  };
  let mid;
  if (live) {
    const sit = g.down ? GI.downDist(g.down, g.dist, g.yl100) + (isNum(g.yl100) ? ' at ' + GI.fieldPos(g.yl100, g.possession, GI.otherTeam(g, g.possession)) : '') : '';
    mid = '<span class="qk-badge live">' + esc(st === 'half' ? 'Halftime' : (GI.clockText(g.qtr, g.clock) || 'Live')) + '</span>' + (sit ? '<span>' + esc(GI.teamAbbr(g.possession)) + ' ball · ' + esc(sit) + '</span>' : '');
  } else if (fin) mid = '<span class="qk-badge final">Final' + (GI.isOT(g) ? '/OT' : '') + '</span>';
  else mid = '<span class="qk-badge">' + esc(GI.fmtDate(g.kickoff || g.date, { year: false })) + ' ' + esc(GI.fmtTime(g.kickoff)) + '</span>' + (GI.countdown(g.kickoff) ? '<span>kickoff in ' + esc(GI.countdown(g.kickoff)) + '</span>' : '');
  const T = t => ({ name: GI.teamName(t), abbr: GI.teamAbbr(t), colour: GI.teamInfo(t).colour });
  const meta = [GI.weekLink(S, w), g.gtype && String(g.gtype).toUpperCase() !== 'REG' ? esc(GI.gtypeLabel(g.gtype)) : '', g.stadium_name || g.stadium ? esc(g.stadium_name || g.stadium) : '',
    GI.weatherText(g.weather, g.roof) ? esc(GI.weatherText(g.weather, g.roof)) : '', g.referee ? 'Referee ' + esc(g.referee) : ''].filter(Boolean);
  const qs = GI.ch.quartersOf(g);
  return '<section class="qk-hero gi-hero-ent" style="--tc:' + esc(GI.tc(g.home)) + '"><div class="qk-hero-in" style="display:block">' +
    '<div class="qk-kicker">' + meta.join(' · ') + '</div>' +
    '<div class="gi-score" style="margin-top:14px">' + side(g.away, 'away', as, fin && as !== null && hs !== null && as < hs) + '<div class="gi-score-mid">' + mid + '</div>' + side(g.home, 'home', hs, fin && as !== null && hs !== null && hs < as) + '</div>' +
    (!fin && pNow !== null ? '<div style="margin-top:14px">' + QK.probBar(1 - pNow, null, pNow, T(g.away), T(g.home)) + '</div>' : '') +
    (live ? fieldStrip(g) : '') + (qs.length ? '<div style="margin-top:14px;max-width:560px">' + GI.ch.linescore(g) + '</div>' : '') + '</div></section>';
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
function mvmBlock(g, pre) {
  const m = pre.model || {}, mk = pre.market || g.market || {}, ln = pre.line || g.line || {};
  const H = GI.teamAbbr(g.home), A = GI.teamAbbr(g.away);
  const mLine = GI.homeLine(m), kLine = GI.homeLine(mk), lLine = GI.homeLine(ln.close && GI.isFinal(g) ? ln.close : ln), oLine = ln.open ? GI.homeLine(ln.open) : null;
  const lTot = ln.close && GI.isFinal(g) && isNum(ln.close.total) ? ln.close.total : ln.total;
  const mlP = isNum(ln.ml_home) && isNum(ln.ml_away) ? GI.devigAm([ln.ml_home, ln.ml_away]) : null;
  const lean = GI.lineLean(g, mLine, lLine);
  const strips = [];
  if (isNum(m.p_home) && isNum(mk.p_home)) strips.push(QK.mvm(m.p_home, mk.p_home, H + ' win · market'));
  if (isNum(m.p_home) && isNum(mlP)) strips.push(QK.mvm(m.p_home, mlP, H + ' win · moneyline'));
  const rows = [
    [{ html: '<b>Win (' + esc(H) + ')</b>' }, { html: '<b>' + GI.pct(m.p_home) + '</b>' }, { html: GI.pct(mk.p_home) + (mk.sources ? '<span class="gi-sub-line">' + esc(mk.sources.join(' · ')) + '</span>' : '') },
      { html: isNum(ln.ml_home) ? esc(H) + ' ' + GI.fmtOdds(ln.ml_home) + ' / ' + esc(A) + ' ' + GI.fmtOdds(ln.ml_away) + (mlP !== null ? '<span class="gi-sub-line">no-vig ' + GI.pct(mlP) + '</span>' : '') : '—' },
      { html: GI.gapHTML(m.p_home, isNum(mk.p_home) ? mk.p_home : mlP) }],
    [{ html: '<b>Spread</b>' }, { html: '<b>' + esc(GI.spreadText(g.home, g.away, mLine)) + '</b>' + (isNum(m.p_cover_home) && isNum(lLine) ? '<span class="gi-sub-line">' + esc(H) + ' covers ' + esc(GI.fmtLine(lLine)) + ': ' + GI.pct(m.p_cover_home, 0) + '</span>' : '') },
      { html: esc(GI.spreadText(g.home, g.away, kLine)) }, { html: esc(GI.spreadText(g.home, g.away, lLine)) + (isNum(oLine) ? '<span class="gi-sub-line">open ' + esc(GI.spreadText(g.home, g.away, oLine)) + '</span>' : '') },
      { html: lean ? (lean.team ? esc(GI.teamAbbr(lean.team)) + ' by ' + GI.num(lean.pts, 1) : 'none') : '—' }],
    [{ html: '<b>Total</b>' }, { html: '<b>' + GI.num(m.total, 1) + '</b>' + (isNum(m.p_over) && isNum(lTot) ? '<span class="gi-sub-line">over ' + GI.num(lTot, 1) + ': ' + GI.pct(m.p_over, 0) + '</span>' : '') },
      { html: GI.num(mk.total, 1) }, { html: GI.num(lTot, 1) + (ln.open && isNum(ln.open.total) ? '<span class="gi-sub-line">open ' + GI.num(ln.open.total, 1) + '</span>' : '') },
      { html: isNum(m.total) && isNum(lTot) ? GI.gapPts(m.total - lTot) : '—' }]
  ];
  return (strips.length ? '<div class="gi-mvm-rows" style="margin-bottom:12px">' + strips.join('') + '</div>' : '') +
    GI.tableHTML([{ label: '', sortable: false }, { label: 'Model', sortable: false }, { label: 'Market', sortable: false }, { label: 'Line', sortable: false }, { label: 'Model − line', sortable: false, title: 'A disagreement, not a recommendation' }], rows);
}
function projBlock(g, m) {
  let hp = m.home_pts, ap = m.away_pts;
  const ml = GI.homeLine(m);
  if ((!isNum(hp) || !isNum(ap)) && isNum(m.total) && isNum(ml)) { hp = (Number(m.total) - ml) / 2; ap = (Number(m.total) + ml) / 2; }
  if (!isNum(hp) || !isNum(ap)) return '';
  const t = (team, pts) => '<a class="gi-vs-team" href="' + GI.teamHref(team) + '">' + GI.mark(team, 'lg') + '<span class="p" style="color:' + esc(GI.tc(team)) + '">' + GI.num(pts, 1) + '</span><span class="qk-sub">' + esc(GI.teamShort(team)) + '</span></a>';
  return '<div class="gi-vs">' + t(g.away, ap) + '<div class="gi-vs-mid"><span>projected</span><span class="sc">–</span></div>' + t(g.home, hp) + '</div>';
}
function injuriesBlock(g) {
  const inj = g.injuries || {};
  const qb = g.qb_status || {};
  if (!R(inj.home).length && !R(inj.away).length && !qb.home && !qb.away) return '';
  const side = s => {
    const list = R(inj[s]);
    const q = qb[s];
    return '<div><h4 class="gi-inj-h">' + GI.teamLink(g[s]) + '</h4>' + (q ? '<p class="gi-cap">QB: ' + GI.qbText(q) + (q.status ? ' · ' + esc(q.status) : '') + (isNum(q.value) ? ' · value ' + GI.signed(q.value, 3) + ' EPA/play' : '') + '</p>' : '') +
      (list.length ? GI.tableHTML([{ label: 'Player' }, { label: 'Pos' }, { label: 'Status' }, { label: 'Detail' }, { label: 'Impact', align: 'right', title: 'Model points of margin (negative hurts this team)' }],
        list.map(x => [{ html: x.pid ? GI.playerLink(x.pid, x.name ? { name: x.name } : null) : esc(x.name || '—'), v: x.name || GI.playerName(x.pid) }, x.pos || GI.player(x.pid).pos || '—',
          { html: GI.pill(x.status || '—', /out|ir|doubt/i.test(x.status || '') ? GI.BAD : /quest/i.test(x.status || '') ? GI.CLOSE : 'var(--ink-3)'), v: x.status }, x.detail || x.injury || '—',
          { html: isNum(x.impact) ? GI.ptsEdge(x.impact, 1) : '—', v: x.impact }])) : GI.muted('No injuries reported.')) + '</div>';
  };
  return GI.card('Injuries and QB status', 'from the injury report; impact is our model\'s', '<div class="qk-grid"><div class="qk-span-6">' + side('away') + '</div><div class="qk-span-6">' + side('home') + '</div></div>');
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
      grid: { left: 8, right: 16, top: 28, bottom: 6, containLabel: true },
      legend: GI.ch.legend(T, { data: ['Offence percentile', 'Defence percentile'] }),
      xAxis: GI.ch.ax(T, { min: 0, max: 100, fmt: v => v + 'th' }), yAxis: ya,
      tooltip: GI.ch.tip(T, { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: ps => { const r = rows[ps[0].dataIndex]; return GI.ch.thead(esc(r.label)) + GI.ch.trow(T.model, GI.teamAbbr(r.t) + ' offence', GI.signed(r.off, 3) + ' · ' + GI.ordinal(r.offR)) + GI.ch.trow(T.market, GI.teamAbbr(r.o) + ' defence', GI.signed(r.def, 3) + ' · ' + GI.ordinal(r.defR)); } }),
      series: [{ type: 'bar', name: 'Offence percentile', data: rows.map(r => rankPct(r.offR)), barMaxWidth: 12, itemStyle: { color: T.model, borderRadius: [0, 3, 3, 0] } },
        { type: 'bar', name: 'Defence percentile', data: rows.map(r => rankPct(r.defR)), barMaxWidth: 12, itemStyle: { color: T.market, borderRadius: [0, 3, 3, 0] } }]
    };
  }, 'Unit matchups');
}
function previewTab(g, pre0) {
  const pre = Object.assign({}, pre0, { model: withDists(pre0.model || {}, pre0.line || g.line) });
  const m = pre.model;
  const hasModel = isNum(m.p_home) || isNum(m.total) || isNum(GI.homeLine(m));
  let h = '';
  if (hasModel) {
    h += GI.grid(GI.card('Model v market v line', (pre.priced_at || m.priced_at ? 'priced ' + esc(GI.fmtStamp(pre.priced_at || m.priced_at)) : '') + (GI.isPre(g) ? '' : ' · frozen at kickoff'), mvmBlock(g, pre) +
      '<p class="gi-cap">Spreads are shown for the favourite (negative = favoured). The market is the de-vigged prediction-market price; the line is the sportsbook line as ESPN shows it. For information only.</p>', { span: 7 }) +
      GI.card('Projected score', 'model mean', projBlock(g, m) || GI.muted('No projection.'), { span: 5 }));
    if (m.margin_dist || m.total_dist) {
      h += GI.grid(GI.card('Margin', esc(GI.teamAbbr(g.home)) + ' points minus ' + esc(GI.teamAbbr(g.away)) + (m.approx ? ' · normal approximation' : ''), GI.chartBox('gm-md', 240, 'Margin distribution'), { span: 6 }) +
        GI.card('Total points', 'dashed: the line and our mean', GI.chartBox('gm-td', 240, 'Total points distribution'), { span: 6 }));
    }
  } else h += GI.card('Model v market v line', '', GI.muted('The pre-game price is not available for this game.'));
  h += matchupsBlock(g) + injuriesBlock(g) + contextBlock(g);
  return { html: h, after: root => {
    const ln = pre.line || g.line || {};
    const lLine = GI.homeLine(ln);
    if (m.margin_dist && root.querySelector('#gm-md')) GI.ch.distBars('gm-md', m.margin_dist, { signed: true, split: 0, colours: [GI.teamColour(g.home), GI.teamColour(g.away)],
      line: isNum(lLine) ? -lLine : null, exp: isNum(GI.homeLine(m)) ? -GI.homeLine(m) : null, actual: GI.isFinal(g) && isNum(g.hs) ? g.hs - g.as : null, unit: 'pts', xName: GI.teamAbbr(g.home) + ' margin' });
    if (m.total_dist && root.querySelector('#gm-td')) GI.ch.distBars('gm-td', m.total_dist, { line: ln.total, exp: m.total, actual: GI.isFinal(g) && isNum(g.hs) ? Number(g.hs) + Number(g.as) : null, unit: 'pts', xName: 'Total points' });
    drawUnits(root);
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
    GI.tableHTML([{ label: 'When' }, { label: 'Team' }, { label: 'Situation' }, { label: 'Call' }, { label: 'Model' }, { label: 'WP go · punt · FG', sortable: false, title: 'Our win probability for the team on fourth down, by option' },
      { label: 'WP lost', align: 'right', title: 'Win probability given up against the best option, percentage points' }, { label: 'Grade' }, { label: 'Play', sortable: false }], rows) +
    '<div class="gi-legend" style="margin-top:10px"><span><i style="background:' + GI.GOOD + '"></i>Right call (≤ 1.5 pts lost)</span><span><i style="background:' + GI.CLOSE + '"></i>Close call (1.5–3)</span><span><i style="background:' + GI.BAD + '"></i>Mistake (&gt; 3)</span></div>');
}
function keyPlaysBlock(g, kp) {
  if (!kp.length) return '';
  return GI.card('Key plays', 'by win probability added for ' + esc(GI.teamAbbr(g.home)) + ' (numbered on the chart)', GI.tableHTML([{ label: '#', align: 'right', sortable: false }, { label: 'When', sortable: false }, { label: 'Team', sortable: false }, { label: 'Play', sortable: false }, { label: 'EPA', align: 'right', sortable: false }, { label: 'WPA', align: 'right', sortable: false }],
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
function flowTab(g, pre, plays) {
  const fd = fourthOf(g, plays), sc = scoringOf(g, plays), kp = keyPlaysOf(g, plays), wp = wpSeries(g, plays, pre);
  const hasWp = wp.ours.length >= 2 || wp.espn.length >= 2;
  const hasDrives = GI.ch.driveRows(g.drives).length > 0;
  let h = GI.card('Win probability', esc(GI.teamAbbr(g.home)) + ' (home) · ' + (wp.name === 'Our model' ? 'our model' : esc(wp.name)) + ' solid' + (wp.espn.length ? ', ESPN dotted' : '') + ' · ◆ 4th downs by grade · ● scores · numbers: key plays' +
    (wp.name !== 'Our model' ? ' · our WP model is not fitted for this game, so nflfastR\'s published WP is shown' : ''),
    hasWp ? GI.chartBox('gm-wp', 360, 'Win probability through the game') : GI.muted(GI.isPre(g) ? 'The win-probability chart starts at kickoff.' : 'No win-probability path for this game yet.'));
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
      '<th class="num"><span data-tip="Home win probability added, points">WPA</span></th><th class="num"><span data-tip="Home win probability after the play: ours (ESPN below)">WP</span></th></tr></thead><tbody>' + body + '</tbody></table></div>' : GI.muted('No plays match these filters.');
  };
  return { html: GI.card('Play-by-play', 'EPA for the offence · WPA and WP from ' + esc(GI.teamAbbr(g.home)) + '\'s side', ctl + '<div id="pbp-wrap"></div>'), after: root => {
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
  return { html: keys.map(k => boxSection(g, k, box[k], /passing|rushing|receiving/.test(k) ? 'with EPA and our advanced columns' : '')).join('') +
    Object.keys(ngs).map(k => boxSection(g, k, ngs[k], 'NFL Next Gen Stats (via nflverse), credited; informational, non-commercial use')).join('') +
    '<p class="gi-cap">EPA is our expected points added. Columns with an NGS tooltip are NFL Next Gen Stats; charting columns are FTN Data via nflverse (CC BY-SA 4.0).</p>' };
}

// ── page ──────────────────────────────────────────────────────────────────

GI.route('game', function (el, params) {
  const id = params.id;
  return GI.loadGame(id).then(g0 => {
    if (!el.isConnected) return;
    const meta = GI.parseGameId(id);
    if (!GI.ok(g0)) {
      const idx = GI.index() || {};
      const c = ['games', 'live', 'recent'].reduce((acc, k) => acc || (idx[k] || []).find(x => x && x.game_id === id), null);
      el.innerHTML = GI.pageHead(meta ? GI.weekLink(meta.season, meta.week) : 'Game', meta ? GI.teamName(meta.away) + ' at ' + GI.teamName(meta.home) : 'Game ' + id, '', meta ? GI.weekNav(meta.season, meta.week) : '') +
        (c ? '<div style="max-width:380px">' + GI.gameCard(c) + '</div>' : '') +
        GI.notBuilt('The game centre for this game', g0) + (meta && meta.season < GI.currentSeason() - 1 ? GI.muted('Game centres are kept for the current and the previous season; the week pages keep every result.') : '');
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
    if (!g.quarters && g.score && Array.isArray(g.score.home)) g.quarters = g.score.home.map((h, i) => [g.score.away[i], h]);
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
    el.innerHTML = header(g, pre, plays) +
      '<div class="qk-tabs" role="tablist" aria-label="Game centre">' + tabs.map(t => '<button type="button" class="qk-tab" role="tab" data-tab="' + t[0] + '" aria-selected="' + (t[0] === tab) + '">' + esc(t[1]) + '</button>').join('') + '</div><div id="gm-body" class="gi-page"></div>';
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
