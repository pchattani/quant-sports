/* The Quant Hardwood — Games (#/<L>/games[/<date>]) and the game centre (#/<L>/game/<gid>).
 *
 * Games: a strip of game days around the chosen one, a date picker and month jump, the day's games as kit
 * match cards, the model against the market for the day's upcoming games, and how the model did on the
 * day's finished games.
 * Game centre (Summary tab): scoreboard, line score, model v market before tip-off (win %, spread, total) and
 * the margin broken into its parts; win probability (model, with the biggest swings marked), the margin
 * flow, both teams' shot charts on the half court, four factors, game awards and the box score.
 * Detail tab (?tab=detail): the full pre-redesign game centre (lineups, rotations, key plays, shot modes).
 * Data: <L>/<S>/games/<gid>.json, <L>/<S>/schedule.json, teams.json logs, index.json cards (game.js helpers). */
(function (HW) {
'use strict';

const U = HW.ui, esc = HW.esc, isNum = HW.isNum;
const GC = () => HW.gameCentre;

// ── games list ─────────────────────────────────────────────────────────────

function renderGames(el, params) {
  const L = U.L(params), S = U.S(params);
  el.innerHTML = U.secHead('Games', 'Scores, model lines and the market for every game of the season. Pick a day.', null, null, U.kicker(L, S)) + QK.skeleton('card', 6);
  return GC().seasonGames(L, S).then(list => {
    if (!U.alive(el)) return;
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
    const mm = pre.filter(g => isNum((g.model || {}).p_home) && isNum((g.market || {}).p_home));
    const months = {};
    days.forEach(x => { const m = x.slice(0, 7); if (!months[m]) months[m] = x; });
    const dl = d => HW.href(L, 'games/' + d, S);
    let h = U.secHead('Games', HW.leagueName(L) + ' ' + esc(HW.seasonLabel(L, S)) + ' · ' + list.length + ' games. Cards show the model’s win probability; blue and orange dots compare it with the market before tip-off.', null, null, U.kicker(L, S));
    h += '<div class="hw-flex" style="margin-bottom:12px">' + (days[i - 1] ? '<a class="qk-btn" href="' + esc(dl(days[i - 1])) + '" aria-label="Previous game day">←</a>' : '') +
      '<nav class="hw-strip" aria-label="Game days">' + strip.map(d => '<a href="' + esc(dl(d)) + '"' + (d === day ? ' aria-current="page"' : '') + '><span>' + esc(HW.fmtDate(d, { year: false }).split(' ')[0]) + '</span><b>' + esc(d.slice(8)) + '</b><span class="n">' + byDay[d].length + '</span></a>').join('') + '</nav>' +
      (days[i + 1] ? '<a class="qk-btn" href="' + esc(dl(days[i + 1])) + '" aria-label="Next game day">→</a>' : '') +
      '<input type="date" class="qk-input" id="gl-date" aria-label="Pick a date" value="' + esc(day) + '" min="' + esc(days[0]) + '" max="' + esc(days[days.length - 1]) + '">' +
      '<select class="qk-select" id="gl-month" aria-label="Jump to month"><option value="">Jump to month…</option>' + Object.keys(months).map(m => '<option value="' + months[m] + '">' + esc(HW.fmtDate(m + '-15', { weekday: false }).replace(/^\d+ /, '')) + '</option>').join('') + '</select></div>';
    h += '<div class="hw-day"><b>' + esc(HW.fmtDate(day)) + '</b> · ' + games.length + ' game' + (games.length === 1 ? '' : 's') + '</div><div class="hw-games">' + games.map(g => U.card(g, L, { season: S })).join('') + '</div>';
    if (mm.length || fin.length) {
      h += '<div class="qk-grid hw-sec">';
      if (mm.length) h += U.card2('Model v market', 'Home win probability: <b style="color:var(--c-model)">model</b> and the de-vigged <b style="color:var(--c-market)">market</b>', U.chart('gl-mm', 34 * mm.length + 50, 'Model against market'), { cls: fin.length ? 'qk-span-7' : 'qk-span-12' });
      if (fin.length) {
        const scored = fin.filter(g => isNum((g.model || {}).p_home) && isNum(g.hs) && isNum(g.as));
        const right = scored.filter(g => (g.model.p_home >= 0.5) === (g.hs > g.as)).length;
        const brier = scored.length ? scored.reduce((s, g) => s + Math.pow(g.model.p_home - (g.hs > g.as ? 1 : 0), 2), 0) / scored.length : null;
        h += U.card2('How the model did', scored.length ? right + ' of ' + scored.length + ' favourites won' + (isNum(brier) ? ' · Brier ' + brier.toFixed(3) + ' (0.25 = a coin flip)' : '') : 'Results of the day',
          '<ul class="hw-list">' + fin.map(g => {
            const p = (g.model || {}).p_home, hw = g.hs > g.as;
            const fav = isNum(p) ? (p >= 0.5 ? g.home : g.away) : null, pf = isNum(p) ? Math.max(p, 1 - p) : null;
            const ok = fav !== null && ((fav === g.home) === hw);
            return '<li><a class="hw-ent" href="' + esc(HW.gameHref(L, g.id, S)) + '"><span class="nm">' + esc(HW.teamAbbr(L, g.away) + ' ' + g.as + ' – ' + g.hs + ' ' + HW.teamAbbr(L, g.home)) + '</span></a>' +
              '<span class="s">' + (fav ? 'model: ' + esc(HW.teamAbbr(L, fav)) + ' ' + U.pct(pf) : '') + '</span><span class="v ' + (fav === null ? '' : ok ? 'pos' : 'neg') + '">' + (fav === null ? '' : ok ? '✓' : '✗') + '</span></li>';
          }).join('') + '</ul>', { cls: mm.length ? 'qk-span-5' : 'qk-span-12', flush: true });
      }
      h += '</div>';
    }
    el.innerHTML = h;
    if (mm.length) {
      QKC.dumbbell('#gl-mm', { rows: mm.map(g => ({ label: HW.teamAbbr(L, g.away) + ' @ ' + HW.teamName(L, g.home), a: g.model.p_home, b: g.market.p_home, href: HW.gameHref(L, g.id, S), sub: (g.market.sources || []).join(', ') })), aName: 'Model', bName: 'Market', labelWidth: 170 });
    }
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
  if (has('pox')) cols.push({ key: 'pox', label: 'POX', num: true, fmt: v => U.sgnHTML(v, 1), tip: 'Points over expected on his shots' });
  QK.table(node, { columns: cols, rows: rows, dense: true });
}

function headHTML(L, g, S) {
  const st = U.status(g);
  const fin = st === 'final';
  const side = (tid, home) => {
    const t = U.team(L, tid);
    return '<div class="side' + (home ? ' home' : '') + '">' + (home ? '' : QK.teamMark(t, 'lg')) + '<div><a class="nm" href="' + esc(HW.teamHref(L, tid, S)) + '">' + esc(HW.teamName(L, tid)) + '</a><div class="sb">' + (home ? 'Home' : 'Away') + '</div></div>' + (home ? QK.teamMark(t, 'lg') : '') + '</div>';
  };
  const sc = st === 'pre' ? '<div class="hw-quiet">' + esc(HW.fmtDate(g.date, { time: true })) + '</div>' :
    '<div class="hw-score"><span class="' + (fin && g.as < g.hs ? 'lost' : '') + '">' + (isNum(g.as) ? g.as : '–') + '</span><span class="dash">–</span><span class="' + (fin && g.hs < g.as ? 'lost' : '') + '">' + (isNum(g.hs) ? g.hs : '–') + '</span></div>';
  const badge = QK.statusBadge({ status: st, start: g.date, period: g.periods || g.period, sport: 'basketball', note: fin && Number(g.periods) > 4 ? 'OT' : '' });
  const meta = [HW.stypeLabel(g.stype), g.series && (g.series.summary || g.series.round) ? (g.series.summary || g.series.round) : '',
    st !== 'pre' ? HW.fmtDate(g.date, { time: true }) : '', g.venue ? (typeof g.venue === 'object' ? [g.venue.name, g.venue.city].filter(Boolean).join(', ') : g.venue) : '',
    isNum(g.attendance) && g.attendance > 0 ? Number(g.attendance).toLocaleString('en-GB') + ' fans' : ''].filter(Boolean);
  return '<div class="qk-hero" style="--tc:' + esc(U.tcol(L, g.home)) + '"><div class="hw-gh">' + side(g.away, false) + '<div class="mid">' + sc + badge + '</div>' + side(g.home, true) + '</div>' +
    '<div class="hw-hero-meta">' + meta.map(m => '<span>' + esc(m) + '</span>').join('') + '</div></div>';
}

function pregameKpis(L, g) {
  const pre = g.pregame || {}, m = pre.model || {}, mk = pre.market || null;
  if (!isNum(m.p_home)) return '';
  const H = HW.teamAbbr(L, g.home);
  const spread = isNum(m.spread_fair) ? m.spread_fair : (isNum(m.margin) ? -m.margin : null);
  const out = [
    QK.kpi({ label: H + ' win · model', value: U.pct(m.p_home), sub: 'fair ' + HW.american(m.p_home) + (mk && isNum(mk.p_home) ? ' · market ' + U.pct(mk.p_home) : ''), tip: 'Pregame model; the market is de-vigged' }),
    QK.kpi({ label: 'Spread · ' + H, value: HW.fmtSpread(spread), sub: 'margin ' + U.signed(m.margin, 1) + (isNum(m.sd) ? ' ± ' + U.f(m.sd, 1) : '') + (mk && isNum(mk.spread_home) ? ' · market ' + HW.fmtSpread(mk.spread_home) : '') }),
    QK.kpi({ label: 'Total', value: U.f(m.total, 1), sub: (isNum(m.pts_home) ? H + ' ' + U.f(m.pts_home, 0) + ' · ' + HW.teamAbbr(L, g.away) + ' ' + U.f(m.pts_away, 0) : '') + (mk && isNum(mk.total) ? ' · market ' + U.f(mk.total, 1) : '') })
  ];
  if (isNum(pre.elo_p_home)) out.push(QK.kpi({ label: 'Elo alone', value: U.pct(pre.elo_p_home), sub: H + ' win probability' }));
  return '<div class="qk-kpis hw-kpis">' + out.join('') + '</div>';
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

function renderGame(el, params) {
  const L = U.L(params), gid = params.id;
  const tab = U.tab(params, ['summary', 'detail'], 'summary');
  el.innerHTML = QK.skeleton('lines', 6);
  return GC().loadGame(L, params.season, gid).then(res => {
    if (!U.alive(el)) return;
    if (!res || !U.ok(res.d)) { el.innerHTML = U.secHead('Game', '', null, null, U.kicker(L, U.S(params))) + U.empty('Game not available', 'This game page has not been built yet.') + '<p>' + U.link(HW.href(L, 'games'), 'All games') + '</p>'; return; }
    const g = res.d, S = res.s;
    if (S !== HW.state.season) HW.state.season = S;
    const st = U.status(g);
    const H = String(g.home), A = String(g.away);
    document.title = HW.teamAbbr(L, A) + ' @ ' + HW.teamAbbr(L, H) + ' · ' + HW.leagueName(L) + ' · The Quant Hardwood';
    const tabs = [{ key: 'summary', label: 'Summary', href: HW.gameHref(L, gid, S) }, { key: 'detail', label: 'Lineups, rotations and plays', href: HW.gameHref(L, gid, S) + (HW.sq(L, S) ? '&' : '?') + 'tab=detail' }];
    let h = headHTML(L, g, S) + U.tabsHTML(tabs, tab);
    if (tab === 'detail') {
      el.innerHTML = h + '<div class="hw-sub"></div>';
      return U.legacy('game', el.querySelector('.hw-sub'), params);
    }
    const ln = g.line || {};
    const la = ln.away || [], lh = ln.home || [];
    const hasBox = Object.keys(g.box || {}).some(t => ((g.box[t] || {}).players || []).length);
    const shots = g.shots && g.shots.rows ? U.rowsOf(g.shots) : [];
    const det = ((g.pregame || {}).model || {}).detail || {};
    const parts = ['rating', 'hca', 'rest', 'b2b', 'travel', 'tz', 'altitude', 'injury'].filter(k => isNum(det[k]) && Math.abs(det[k]) > 0.05);
    h += pregameKpis(L, g);
    h += '<div class="qk-grid hw-sec">';
    if (la.length || lh.length) {
      h += U.card2('Line score', '', '<div id="gm-ls"></div>', { cls: 'qk-span-' + (parts.length ? '7' : '12'), flush: true });
    }
    if (parts.length) h += U.card2('How the model built the line', 'Points of ' + esc(HW.teamAbbr(L, H)) + ' margin from each part', U.chart('gm-parts', 30 * parts.length + 30, 'Margin parts'), { cls: 'qk-span-' + (la.length || lh.length ? '5' : '12') });
    if (g.wp && (g.wp.model || []).length) h += U.card2('Win probability', 'Our live model for ' + esc(HW.teamName(L, H)) + '; the numbered dots are the biggest swings' + ((g.wp.espn || []).length ? ' (ESPN’s line dotted)' : ''), U.chart('gm-wp', 300, 'Win probability'), { cls: 'qk-span-12' });
    if (g.flow && g.flow.length) h += U.card2('Margin', esc(HW.teamAbbr(L, H)) + ' lead through the game', U.chart('gm-flow', 220, 'Margin flow'), { cls: 'qk-span-7' });
    const ff = g.four_factors || {};
    if (ff[A] && ff[H]) h += U.card2('Four factors', 'Shooting, turnovers (lower is better), offensive rebounds, free throws', U.chart('gm-ff', 220, 'Four factors'), { cls: 'qk-span-5' });
    if (shots.length) {
      const sq = g.shot_quality || {};
      const sqTxt = t => (sq[t] && isNum(sq[t].xpts) ? 'xPTS ' + U.f(sq[t].xpts, 1) + ', scored ' + U.f(sq[t].pts, 0) + ' (' + U.signed(sq[t].pts - sq[t].xpts, 1) + ' shot-making)' : '');
      h += U.card2(HW.teamName(L, A) + ' shots', esc(sqTxt(A)) + (sqTxt(A) ? ' · ' : '') + 'size is expected points', '<div id="gm-sh-a"></div>', { cls: 'qk-span-6' }) +
        U.card2(HW.teamName(L, H) + ' shots', esc(sqTxt(H)) + (sqTxt(H) ? ' · ' : '') + 'size is expected points', '<div id="gm-sh-h"></div>', { cls: 'qk-span-6' });
    }
    h += awardsHTML(L, g, S);
    if (hasBox) {
      h += U.card2('Box score', 'Advanced columns where play-by-play exists. Sort any column.', '<div class="qk-seg hw-boxtabs" id="gm-bx-seg" role="group" aria-label="Team">' +
        [A, H].map((t, i) => '<button type="button" data-value="' + esc(t) + '" aria-pressed="' + (i === 0) + '">' + esc(HW.teamName(L, t)) + '</button>').join('') + '</div><div id="gm-box"></div>', { cls: 'qk-span-' + (awardsHTML(L, g, S) ? '7' : '12') });
    }
    if (st === 'pre' && !parts.length && !isNum(((g.pregame || {}).model || {}).p_home)) h += U.card2('Preview', '', U.empty('Line not ready', 'The model line appears once the game is inside the build window.'), { cls: 'qk-span-12' });
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
      QKC.bar('#gm-parts', { cats: parts.map(k => LBL[k]), series: [{ name: 'Points', data: parts.map(k => Math.round(det[k] * 10) / 10) }], horizontal: true, labels: true, diverging: true, fmt: v => U.signed(v, 1), labelWidth: 100 });
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
          grid: { left: 8, right: 16, top: 14, bottom: 8, containLabel: true },
          xAxis: QKC.axis(T, { type: 'value', min: 0, max: fl[fl.length - 1][0], split: false, line: true, fmt: v => (v % PERIOD_S(L) === 0 && v <= 4 * PERIOD_S(L) ? 'Q' + (v / PERIOD_S(L) + 1) : ''), interval: PERIOD_S(L) }),
          yAxis: QKC.axis(T, { fmt: v => (v > 0 ? '+' : '') + v }),
          tooltip: QKC.tooltip(T, { trigger: 'axis', formatter: ps => { const m = (ps[0].value[1] || 0) + ((ps[1] || { value: [0, 0] }).value[1] || 0); return '<div style="color:' + T.ink3 + ';font-size:11px">' + esc(tLabel(L, ps[0].value[0])) + '</div>' + (m === 0 ? 'Tied' : QKC.tipRow(m > 0 ? hc[0] : hc[1], (m > 0 ? HW.teamAbbr(L, H) : HW.teamAbbr(L, A)) + ' lead', String(Math.abs(m)))); } }),
          series: [0, 1].map(k => ({ type: 'line', step: 'end', showSymbol: false, name: k ? HW.teamAbbr(L, A) : HW.teamAbbr(L, H),
            data: fl.map(x => [x[0], k ? Math.min(0, x[1]) : Math.max(0, x[1])]), lineStyle: { width: 1.6, color: hc[k] }, itemStyle: { color: hc[k] }, areaStyle: { color: QKC.hexA(hc[k], 0.2) },
            markLine: k ? undefined : { silent: true, symbol: 'none', lineStyle: { color: T.axis, type: [3, 3] }, label: { show: false }, data: [{ yAxis: 0 }] } }))
        };
      }, { label: 'Margin through the game' });
    }
    if (document.getElementById('gm-ff')) {
      const K = [['efg', 'eFG%'], ['tov', 'TOV%'], ['orb', 'ORB%'], ['ftr', 'FT rate']];
      QKC.bar('#gm-ff', { cats: K.map(k => k[1]), series: [{ name: HW.teamAbbr(L, A), data: K.map(k => Math.round(ff[A][k[0]] * 1000) / 10) }, { name: HW.teamAbbr(L, H), data: K.map(k => Math.round(ff[H][k[0]] * 1000) / 10) }], labels: true, fmt: v => U.f(v, 1), legend: true });
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
