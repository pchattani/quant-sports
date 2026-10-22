/* The Quant Bullpen — Nippon Professional Baseball (the npb level).
 *
 * Every page of the level, registered with BP.routeNpb: while the level is npb these take over the route names
 * (core.js handlerFor); routes the level does not have (umpires, parks, prospects, awards, markets) fall back to a
 * short note. The lab and compare (lab.js, compare.js, reading npb/<S>/lab.json) and the value and trade pages
 * (value.js) register their own npb handlers; the team page calls value.js's BP.valueTeam for "Strengths and needs".
 *
 *   #/npb                     hub: the season, the Climax Series and Japan Series bracket with odds, games, leaders
 *   #/npb/games[/<date>]      a day's games: score, the model's home / tie / away, Kalshi
 *   #/npb/game/<gpk>          line score, box score, decisions, home runs, the pre-game model, Kalshi
 *   #/npb/standings           Central and Pacific: W-L-T, PCT (W/(W+L)), GB, runs, Pythagorean, ratings, odds, head to head
 *   #/postseason              the Climax Series (with the pennant winner's advantage) and the Japan Series
 *   #/npb/hitters, pitchers   season tables with WAR-lite, wOBA, wRC+, FIP
 *   #/npb/player/<pid>        profile and career, Japanese name and reading
 *   #/npb/teams, team/<tid>   clubs: record, rating, results against the model, leading players, names over time
 *   #/npb/leaders             league leaders
 *   #/history                 champions by year from 1950, standings and awards, all-time leaders, club names
 *   #/calibration             the walk-forward backtest (three-way: home, tie, away) and Kalshi
 *
 * Data: data/npb/<S>/{season,schedule,players,teams}.json, data/npb/<S>/games/<gpk>.json, data/npb/history.json,
 * data/npb/careers/<NN>.json, data/npb/names.json, data/npb/calibration.json; index.json levels.npb.
 * No optional chaining or nullish coalescing (older browsers). */
(function (BP) {
'use strict';

const esc = BP.esc;
const isNum = BP.isNum;
const L = 'npb';
const LG_NAME = { CL: 'Central League', PL: 'Pacific League' };
const LG_JP = { CL: 'セ・リーグ', PL: 'パ・リーグ' };
const STAGE = { C1: 'First Stage', C2: 'Final Stage', J: 'Japan Series' };
const POS_EN = { C: 'C', '1B': '1B', '2B': '2B', '3B': '3B', SS: 'SS', LF: 'LF', CF: 'CF', RF: 'RF', DH: 'DH', P: 'P', IF: 'IF', OF: 'OF' };
const BOX_POS = { '投': 'P', '捕': 'C', '一': '1B', '二': '2B', '三': '3B', '遊': 'SS', '左': 'LF', '中': 'CF', '右': 'RF', '指': 'DH', '打': 'PH', '走': 'PR' };

/* A plate appearance as NPB prints it ("右中２", "三ゴロ", "四球", "左越本②") in English shorthand. */
const FLD = { '投': 'P', '捕': 'C', '一': '1B', '二': '2B', '三': '3B', '遊': 'SS', '左': 'LF', '中': 'CF', '右': 'RF' };
function paEn(x) {
  const t = String(x || '').replace(/\s+/g, '');
  const rbi = (t.match(/[①②③④]/) || [''])[0];
  const r = rbi ? ' ' + ('①②③④'.indexOf(rbi) + 1) + ' RBI' : '';
  const f = FLD[t.charAt(0)] || '';
  const where = f ? ' (' + f + ')' : '';
  if (t.indexOf('三振') >= 0) return 'K' + r;
  if (t.indexOf('四球') >= 0 || t.indexOf('敬遠') >= 0) return 'BB' + r;
  if (t.indexOf('死球') >= 0) return 'HBP' + r;
  if (t.indexOf('本') >= 0) return 'HR' + where + r;
  if (t.indexOf('犠飛') >= 0) return 'SF' + where + r;
  if (t.indexOf('犠打') >= 0) return 'SAC' + where + r;
  if (t.indexOf('併') >= 0) return 'GDP' + where + r;
  if (t.indexOf('野選') >= 0) return 'FC' + where + r;
  if (t.indexOf('失') >= 0) return 'E' + where + r;
  if (t.indexOf('妨') >= 0) return 'INT' + r;
  if (/[３3]/.test(t)) return '3B' + where + r;
  if (/[２2]/.test(t)) return '2B' + where + r;
  if (t.indexOf('安') >= 0) return '1B' + where + r;
  if (t.indexOf('ゴロ') >= 0) return 'GO' + where + r;
  if (t.indexOf('邪飛') >= 0) return 'FO' + where + r;
  if (t.indexOf('直') >= 0) return 'LO' + where + r;
  if (t.indexOf('飛') >= 0) return 'FO' + where + r;
  return t;
}

function S0(params) { return Number((params && params.season) || BP.currentSeason(L)); }
function y(file, S) { return 'npb/' + S + '/' + file; }
function pct(p, d) { return BP.pct(p, d === undefined ? 0 : d); }
function tl(tid, o) { return BP.teamLink(tid, Object.assign({ level: L }, o || {})); }
function jpOf(tid) { const x = BP.teamInfo(tid); return x.jp || ''; }
function phref(pid, S) { return BP.href('player/' + encodeURIComponent(pid), L, S); }
function plink(pid, name, S) {
  if (!pid) return esc(name || '—');
  return '<a class="ply-link" href="' + phref(pid, S) + '">' + esc(name || pid) + '</a>';
}
function ghref(gpk, S) { return BP.href('game/' + encodeURIComponent(gpk), L, S); }
function ipText(outs) { return isNum(outs) ? Math.floor(outs / 3) + (outs % 3 ? '.' + (outs % 3) : '') : '—'; }
function avg(v) { return BP.fmtAvg(v); }
function n1(v) { return BP.num(v, 1); }
function n2(v) { return BP.num(v, 2); }
function int(v) { return BP.int(v); }
function head(title, sub, right) { return BP.pageHead(title, sub, right); }
function note(t) { return '<div class="npb-note">' + t + '</div>'; }
function srcNote() { return note('Data: the NPB official site (npb.jp), facts and our own derived numbers only; prices: Kalshi. Unofficial; not affiliated with NPB or any club.'); }

/* A three-way bar: home | tie | away. */
function threeBar(m, home, away) {
  if (!m || !isNum(m.p_home)) return '';
  const h = m.p_home * 100, t = (m.p_tie || 0) * 100, a = (m.p_away || 0) * 100;
  return '<div class="npb-3bar" title="Model: ' + esc(BP.teamAbbr(home)) + ' ' + pct(m.p_home) + ', tie ' + pct(m.p_tie, 1) + ', ' + esc(BP.teamAbbr(away)) + ' ' + pct(m.p_away) + '">' +
    '<span style="width:' + a.toFixed(1) + '%;background:' + BP.teamColour(away) + '"></span>' +
    '<span class="tie" style="width:' + t.toFixed(1) + '%"></span>' +
    '<span style="width:' + h.toFixed(1) + '%;background:' + BP.teamColour(home) + '"></span></div>';
}

/* A game card (index.json levels.npb today/recent/upcoming, schedule.json): away over home, the model's away / tie /
 * home and Kalshi's prices. */
function card(g, opts) {
  const o = opts || {};
  if (!g) return '';
  const st = BP.gameState(g);
  const fin = st === 'final';
  const winH = fin && isNum(g.hs) && g.hs > g.as, winA = fin && isNum(g.as) && g.as > g.hs;
  const m = g.model || null, mk = g.market || null;
  const row = (tid, score, p, win, lose) => '<div class="gc-team' + (win ? ' gc-win' : '') + (lose ? ' gc-lose' : '') + '">' + BP.teamBar(tid) +
    '<span class="gc-name"><span class="gc-abbr">' + esc(BP.teamAbbr(tid)) + '</span> <span class="gc-full">' + esc(BP.teamShort(tid)) + '</span></span>' +
    (st === 'pre' || !isNum(score) ? '' : '<span class="gc-score">' + esc(score) + '</span>') +
    '<span class="gc-p">' + (isNum(p) ? pct(p) : '') + '</span></div>';
  let top = '';
  if (st === 'final') top = '<span class="chip st-ft">' + (g.tie ? 'Tie' : 'Final') + (g.inn && g.inn > 9 ? '/' + g.inn : '') + '</span>';
  else if (st === 'live') top = '<span class="chip st-live"><span class="live-dot"></span> Live</span>';
  else if (st === 'postponed' || st === 'cancelled') top = '<span class="chip warn">' + (st === 'postponed' ? 'Postponed' : 'Cancelled') + '</span>';
  else top = '<span class="chip st-time">' + esc(g.start ? BP.fmtTime(g.start) : 'TBD') + '</span>';
  if (o.date) top = '<span class="gc-date">' + esc(BP.fmtDate(g.date, { year: false })) + '</span> ' + top;
  const tag = g.series ? (g.series.desc || '') + (isNum(g.series.game) ? ' · G' + g.series.game : '') : (g.interleague ? 'Interleague' : '');
  const lines = [];
  if (m && isNum(m.p_home)) lines.push('<span class="gc-l"><b>Model</b> ' + esc(BP.teamAbbr(g.away)) + ' ' + pct(m.p_away) + ' · tie ' + pct(m.p_tie, 1) + ' · ' +
    esc(BP.teamAbbr(g.home)) + ' ' + pct(m.p_home) + (isNum(m.total) ? ' · ' + n1(m.total) + ' runs' : '') + '</span>');
  if (mk && (isNum(mk.p_home) || isNum(mk.p_away))) lines.push('<span class="gc-l"><b>Kalshi</b> ' + esc(BP.teamAbbr(g.away)) + ' ' + pct(mk.p_away) + ' · ' +
    esc(BP.teamAbbr(g.home)) + ' ' + pct(mk.p_home) + (m && isNum(m.p_home) && isNum(mk.p_home) ? ' (' + BP.edgeHTML(m.p_home, mk.p_home, 0) + ')' : '') + '</span>');
  if (st === 'pre' && g.probables_jp && (g.probables_jp.home || g.probables_jp.away)) lines.push('<span class="gc-l muted-inline">Starters ' + esc(g.probables_jp.away || '?') + ' v ' + esc(g.probables_jp.home || '?') + '</span>');
  if (g.dec && fin) lines.push('<span class="gc-l muted-inline">W ' + esc(g.dec.w || '—') + ' · L ' + esc(g.dec.l || '—') + (g.dec.s ? ' · S ' + esc(g.dec.s) : '') + '</span>');
  return '<a class="gc npb-gc' + (st === 'live' ? ' gc-live' : '') + '" href="' + ghref(g.gpk, o.season) + '">' +
    '<div class="gc-top">' + top + (tag ? '<span class="gc-tag">' + esc(tag) + '</span>' : '') + '</div>' +
    row(g.away, g.as, m ? m.p_away : null, winA, winH) + row(g.home, g.hs, m ? m.p_home : null, winH, winA) +
    (m && isNum(m.p_home) ? threeBar(m, g.home, g.away) : '') +
    (lines.length ? '<div class="gc-lines">' + lines.join('') + '</div>' : '') + '</a>';
}
function cards(list, opts) {
  if (!list || !list.length) return BP.muted('No games.');
  return '<div class="gc-grid">' + list.map(g => card(g, opts)).join('') + '</div>';
}

// ── the bracket ─────────────────────────────────────────────────────────────

function stageLine(stg, lg, sim, S) {
  if (!stg) return '';
  const hi = stg.high, lo = stg.low;
  const res = stg.results || [];
  const w = res.filter(r => r === 'W').length, l = res.filter(r => r === 'L').length, t = res.filter(r => r === 'T').length;
  const key = lg + '-' + stg.key + '-' + hi + '-' + lo;
  const p = sim && sim.stages && isNum(sim.stages[key]) ? sim.stages[key] : null;
  const advTxt = stg.adv ? ' <span class="npb-adv" title="The pennant winner starts with ' + stg.adv + (stg.adv > 1 ? ' wins' : ' win') + '">+' + stg.adv + '</span>' : '';
  const fmt = stg.games + ' games, first to ' + stg.need + (stg.adv ? ' (the pennant winner\'s ' + stg.adv + '-win advantage counts)' : '');
  const lowTxt = lo ? tl(lo, { short: true }) : '<span class="muted-inline">First Stage winner</span>';
  const won = stg.winner ? '<span class="npb-through">' + esc(BP.teamShort(stg.winner)) + ' through</span>' : '';
  const prob = !stg.winner && isNum(p) ? '<span class="npb-sp">' + esc(BP.teamAbbr(hi)) + ' ' + pct(p) + (lo ? ' · ' + esc(BP.teamAbbr(lo)) + ' ' + pct(1 - p) : '') + '</span>' : '';
  const games = (stg.gpks || []).map((g, i) => '<a href="' + ghref(g, S) + '" class="npb-gl ' + (res[i] === 'W' ? 'w' : res[i] === 'L' ? 'l' : 't') + '">' + (i + 1) + '</a>').join('');
  return '<div class="npb-stage"><div class="npb-st-h">' + esc(STAGE[stg.key] || stg.key) + ' <span class="muted-inline">' + esc(fmt) + '</span></div>' +
    '<div class="npb-st-row">' + tl(hi, { short: true }) + advTxt + ' <b>' + (w + (stg.adv || 0)) + '</b>–<b>' + l + '</b>' + (t ? ' <span class="muted-inline">(' + t + (t > 1 ? ' ties' : ' tie') + ')</span>' : '') + ' ' + lowTxt +
    ' ' + won + prob + '</div>' + (games ? '<div class="npb-gls">' + games + '</div>' : '') + '</div>';
}
function bracketHTML(br, sim, S) {
  if (!br || !br.leagues) return BP.muted('The postseason bracket is not available yet.');
  let h = '<div class="npb-bracket">';
  ['CL', 'PL'].forEach(lg => {
    const b = br.leagues[lg];
    if (!b) return;
    h += '<div class="npb-lgcol"><div class="npb-lg-h">' + esc(LG_NAME[lg]) + ' <span class="muted-inline">' + esc(LG_JP[lg]) + '</span></div>' +
      '<div class="npb-seeds">' + (b.seeds || []).map((t, i) => '<span>' + (i + 1) + '. ' + tl(t, { short: true }) + '</span>').join('') + '</div>' +
      ((b.stages || []).length ? b.stages.map(stg => stageLine(stg, lg, sim, S)).join('') : '<div class="muted">No Climax Series this season: the pennant winner went to the Japan Series.</div>') + '</div>';
  });
  const js = br.js || {};
  const res = js.results || [];
  const cw = res.filter(r => r === 'W').length, pw = res.filter(r => r === 'L').length, ties = res.filter(r => r === 'T').length;
  h += '<div class="npb-lgcol npb-js"><div class="npb-lg-h">Japan Series <span class="muted-inline">日本シリーズ</span></div>';
  if (js.cl && js.pl) {
    h += '<div class="npb-st-row">' + tl(js.cl, { short: true }) + ' <b>' + cw + '</b>–<b>' + pw + '</b> ' + tl(js.pl, { short: true }) +
      (ties ? ' <span class="muted-inline">(' + ties + (ties > 1 ? ' ties' : ' tie') + ')</span>' : '') + (js.winner ? ' <span class="npb-through">' + esc(BP.teamShort(js.winner)) + ' champions</span>' : '') + '</div>' +
      '<div class="npb-gls">' + (js.gpks || []).map((g, i) => '<a href="' + ghref(g, S) + '" class="npb-gl ' + (res[i] === 'W' ? 'w' : res[i] === 'L' ? 'l' : 't') + '">' + (i + 1) + '</a>').join('') + '</div>';
  } else h += '<div class="muted">Waiting for the two Climax Series winners.</div>';
  h += '<div class="npb-st-h muted-inline">Best of seven; games 1-7 can end tied after 12 innings, so a game 8 (no limit) is possible. Games 1, 2, 6, 7 at the ' +
    esc(js.home_league === 'CL' ? 'Central' : 'Pacific') + ' League champion\'s park; the DH only at the Pacific club\'s park.</div></div>';
  return h + '</div>';
}
function oddsTable(sim, fut, phase) {
  if (!sim || !sim.teams) return '';
  const rows = Object.keys(sim.teams).map(t => Object.assign({ tid: t }, sim.teams[t])).filter(r => r.p_cs > 0 || phase === 'regular')
    .sort((a, b) => b.p_champion - a.p_champion || b.p_js - a.p_js);
  const fp = (fut && fut.p) || {};
  const cols = [{ label: 'Club' }, { label: 'Lg' }];
  if (phase === 'regular') cols.push({ label: 'Pennant', align: 'right' }, { label: 'Top 3', align: 'right' });
  cols.push({ label: 'Final Stage', align: 'right' }, { label: 'Japan Series', align: 'right' }, { label: 'Champion', align: 'right' }, { label: 'Kalshi', align: 'right', title: 'Kalshi KXNPB mid' });
  const body = rows.map(r => {
    const c = [{ v: BP.teamName(r.tid), html: tl(r.tid) }, BP.teamInfo(r.tid).league || ''];
    if (phase === 'regular') c.push({ v: r.p_pennant, html: pct(r.p_pennant), align: 'right' }, { v: r.p_cs, html: pct(r.p_cs), align: 'right' });
    c.push({ v: r.p_final, html: pct(r.p_final), align: 'right' }, { v: r.p_js, html: pct(r.p_js), align: 'right' },
      { v: r.p_champion, html: BP.probCell(r.p_champion, BP.teamColour(r.tid)), align: 'right' },
      { v: fp[r.tid], html: isNum(fp[r.tid]) ? pct(fp[r.tid]) + ' ' + BP.edgeHTML(r.p_champion, fp[r.tid], 0) : '—', align: 'right' });
    return c;
  });
  return BP.tableHTML(cols, body, { compact: true });
}

// ── hub ─────────────────────────────────────────────────────────────────────

BP.routeNpb('hub', function (el, params) {
  const S = S0(params);
  const lv = BP.levelInfo(L);
  const cur = S === BP.currentSeason(L);
  return BP.loadAll([y('season.json', S), cur ? null : y('schedule.json', S)].filter(Boolean)).then(res => {
    const sp = res[0] || {};
    const sched = cur ? null : res[1];
    const phase = sp.phase || lv.phase || '';
    const sim = sp.sim;
    const fav = sim && sim.teams ? Object.keys(sim.teams).sort((a, b) => sim.teams[b].p_champion - sim.teams[a].p_champion)[0] : null;
    const br = sp.bracket || {};
    const champ = br.js && br.js.winner;
    const phaseTxt = { regular: 'Regular season', postseason: 'Postseason: Climax Series and Japan Series', offseason: 'Season complete', preseason: 'Before opening day' }[phase] || '';
    let h = '<div class="hub-band npb-band"><div><div class="hb-title">NPB ' + S + ' <span class="muted-inline">日本プロ野球</span></div>' +
      '<div class="hb-sub">' + esc(phaseTxt) + '. Nippon Professional Baseball: the Central and Pacific Leagues, the Climax Series and the Japan Series. ' +
      'Game odds are three-way, home, tie or away (games are called level after 12 innings), from team ratings learned from every result since 2005.</div></div>' +
      '<div class="hb-tiles">' +
      (champ ? '<div class="hb-tile"><span class="hb-v">' + tl(champ, { short: true }) + '</span><span class="hb-l">Japan Series champion</span></div>'
        : fav ? '<div class="hb-tile"><span class="hb-v">' + tl(fav, { short: true }) + '</span><span class="hb-l">Japan Series favourite</span><span class="hb-s">' + pct(sim.teams[fav].p_champion) + ' (model)</span></div>' : '') +
      ['CL', 'PL'].map(lg => { const b = (br.leagues || {})[lg]; return b ? '<div class="hb-tile"><span class="hb-v">' + tl(b.pennant, { short: true }) + '</span><span class="hb-l">' + esc(LG_NAME[lg]) + ' pennant</span></div>' : ''; }).join('') +
      '<div class="hb-tile"><span class="hb-v">' + int(((cur ? lv.today : []) || []).length) + '</span><span class="hb-l">Games today</span></div></div></div>';
    if (br.leagues && (phase !== 'regular')) h += BP.card('Climax Series and Japan Series', 'the bracket, with the model\'s odds of going through', '<div class="pad">' + bracketHTML(br, sim, S) + '</div>');
    if (sim) h += BP.card('Championship odds', esc(BP.int(sim.n)) + ' simulations of the rest of the season' + (sp.kalshi_futures ? ', against Kalshi' : ''), oddsTable(sim, sp.kalshi_futures, phase));
    if (cur) {
      if ((lv.today || []).length) h += BP.card('Today', '', cards(lv.today));
      if ((lv.upcoming || []).length) h += BP.card('Coming up', '', cards(lv.upcoming, { date: true }));
      if ((lv.recent || []).length) h += BP.card('Recent results', '', cards((lv.recent || []).slice().reverse(), { date: true }));
    } else if (sched && sched.games) {
      const post = sched.games.filter(g => g.gtype !== 'R');
      h += BP.card('Postseason games', '', cards(post, { date: true, season: S }));
    }
    const st = sp.standings || {};
    if (st.CL || st.PL) {
      h += '<div class="grid-2">' + ['CL', 'PL'].map(lg => BP.card(LG_NAME[lg], '', miniStandings(st[lg] || []))).join('') + '</div>';
    }
    const ld = lv.leaders || {};
    if (cur && Object.keys(ld).length) h += BP.card('Leaders', 'WAR-lite and the triple-crown numbers', leadersMini(ld));
    h += srcNote();
    el.innerHTML = h;
    BP.sortable(el);
    BP.setMeta('Nippon Professional Baseball');
  });
});
function miniStandings(rows) {
  return BP.tableHTML([{ label: '#' }, { label: 'Club' }, { label: 'W', align: 'right' }, { label: 'L', align: 'right' }, { label: 'T', align: 'right' },
    { label: 'PCT', align: 'right' }, { label: 'GB', align: 'right' }],
  rows.map(r => [r.rank, { v: BP.teamName(r.tid), html: tl(r.tid, { short: true }) }, { v: r.w, align: 'right' }, { v: r.l, align: 'right' }, { v: r.t, align: 'right' },
    { v: r.pct, html: avg(r.pct), align: 'right' }, { v: r.gb, html: r.gb ? n1(r.gb) : '—', align: 'right' }]), { compact: true });
}
function leadersMini(ld) {
  const lab = { bat_war: 'WAR-lite (batting)', bat_hr: 'Home runs', bat_wrc_plus: 'wRC+ (300+ PA)', pit_war: 'WAR-lite (pitching)', pit_era: 'ERA (100+ IP)', pit_so: 'Strikeouts' };
  return '<div class="npb-ld">' + Object.keys(lab).filter(k => (ld[k] || []).length).map(k => '<div class="npb-ld-col"><div class="npb-ld-h">' + esc(lab[k]) + '</div>' +
    (ld[k] || []).slice(0, 5).map(r => '<div class="npb-ld-r">' + plink(r[0], r[1]) + ' <span class="muted-inline">' + esc(BP.teamAbbr(r[2])) + '</span><b>' +
      (k === 'pit_era' ? n2(r[3]) : k.indexOf('war') >= 0 ? n1(r[3]) : int(r[3])) + '</b></div>').join('') + '</div>').join('') + '</div>';
}

// ── standings ───────────────────────────────────────────────────────────────

BP.routeNpb('standings', function (el, params) {
  const S = S0(params);
  return BP.load(y('season.json', S)).then(sp => {
    if (!BP.ok(sp)) { el.innerHTML = head('Standings', 'NPB ' + S) + BP.notBuilt('This season', sp); return; }
    const sim = sp.sim && sp.sim.teams ? sp.sim.teams : {};
    const rt = sp.ratings || {};
    let h = head('Standings', 'NPB ' + S + ' · ranked by winning percentage W/(W+L); ties do not count');
    ['CL', 'PL'].forEach(lg => {
      const rows = (sp.standings || {})[lg] || [];
      const cols = [{ label: '#' }, { label: 'Club' }, { label: 'G', align: 'right' }, { label: 'W', align: 'right' }, { label: 'L', align: 'right' }, { label: 'T', align: 'right' },
        { label: 'PCT', align: 'right' }, { label: 'GB', align: 'right' }, { label: 'RS', align: 'right' }, { label: 'RA', align: 'right' }, { label: 'Diff', align: 'right' },
        { label: 'Pyth', align: 'right', title: 'Pythagorean winning percentage (exponent 1.83)' }, { label: 'Home', align: 'right' }, { label: 'Road', align: 'right' },
        { label: 'Inter', align: 'right', title: 'Interleague record' }, { label: 'Strk', align: 'right' }];
      const hasR = Object.keys(rt).length > 0, hasS = Object.keys(sim).length > 0;
      if (hasR) cols.push({ label: 'Rating', align: 'right', title: 'Offence plus defence, log runs (0 = average)' });
      if (hasS) cols.push({ label: 'Top 3', align: 'right' }, { label: 'Champion', align: 'right' });
      const body = rows.map(r => {
        const c = [r.rank, { v: BP.teamName(r.tid), html: tl(r.tid) + ' <span class="npb-jp">' + esc(jpOf(r.tid)) + '</span>' }, { v: r.g, align: 'right' }, { v: r.w, align: 'right' },
          { v: r.l, align: 'right' }, { v: r.t, align: 'right' }, { v: r.pct, html: avg(r.pct), align: 'right' }, { v: r.gb, html: r.gb ? n1(r.gb) : '—', align: 'right' },
          { v: r.rs, align: 'right' }, { v: r.ra, align: 'right' }, { v: r.rs - r.ra, html: BP.signed(r.rs - r.ra, 0), align: 'right' },
          { v: r.pyth, html: avg(r.pyth), align: 'right' }, { v: r.hw, html: r.hw + '-' + r.hl + '-' + r.ht, align: 'right' }, { v: r.aw, html: r.aw + '-' + r.al + '-' + r.at, align: 'right' },
          { v: r.iw, html: r.iw + '-' + r.il + '-' + r.it, align: 'right' }, { v: r.streak || '', align: 'right' }];
        if (hasR) c.push({ v: (rt[r.tid] || {}).net, html: BP.signed((rt[r.tid] || {}).net, 3), align: 'right' });
        if (hasS) c.push({ v: (sim[r.tid] || {}).p_cs, html: pct((sim[r.tid] || {}).p_cs), align: 'right' }, { v: (sim[r.tid] || {}).p_champion, html: pct((sim[r.tid] || {}).p_champion, 1), align: 'right' });
        return c;
      });
      h += BP.card(LG_NAME[lg] + ' ' + LG_JP[lg], 'the top three play the Climax Series', BP.tableHTML(cols, body, { compact: true }));
      h += BP.card('Head to head · ' + LG_NAME[lg], 'W-L-T against each club this season, interleague included',
        BP.tableHTML([{ label: 'Club' }].concat(rows.map(r => ({ label: BP.teamAbbr(r.tid), align: 'right' }))), rows.map(r => [{ v: BP.teamName(r.tid), html: tl(r.tid, { short: true }) }].concat(rows.map(o => {
          if (o.tid === r.tid) return { v: '', html: '<span class="muted-inline">·</span>', align: 'right' };
          const x = (r.h2h || {})[o.tid] || [0, 0, 0];
          return { v: x[0] - x[1], html: x[0] + '-' + x[1] + (x[2] ? '-' + x[2] : ''), align: 'right' };
        }))), { compact: true }));
    });
    const rules = sp.rules || {};
    h += note('Tiebreakers on equal winning percentage. Central: more wins, head-to-head percentage, intra-league percentage, last season\'s rank. Pacific: head to head, intra-league percentage, last season\'s rank. ' +
      'Extra innings this season: up to ' + esc(rules.max_innings || 12) + (rules.time_limited ? ' (in practice a 3 h 30 min limit: no new inning after it)' : '') + '. DH: Pacific ' + (rules.dh && rules.dh.PL ? 'yes' : 'no') + ', Central ' + (rules.dh && rules.dh.CL ? 'yes' : 'no (from 2027)') + '.');
    el.innerHTML = h;
    BP.sortable(el);
  });
});

// ── postseason ──────────────────────────────────────────────────────────────

BP.routeNpb('postseason', function (el, params) {
  const S = S0(params);
  return BP.loadAll([y('season.json', S), y('schedule.json', S)]).then(res => {
    const sp = res[0], sch = res[1];
    if (!BP.ok(sp)) { el.innerHTML = head('Postseason', 'NPB ' + S) + BP.notBuilt('This season', sp); return; }
    let h = head('Postseason', 'NPB ' + S + ' · Climax Series and Japan Series');
    h += BP.card('The bracket', '', '<div class="pad">' + bracketHTML(sp.bracket, sp.sim, S) + '</div>');
    if (sp.sim) h += BP.card('Odds', BP.int(sp.sim.n) + ' simulations', oddsTable(sp.sim, sp.kalshi_futures, sp.phase));
    const post = ((sch || {}).games || []).filter(g => g.gtype !== 'R');
    if (post.length) h += BP.card('Games', '', cards(post, { date: true, season: S }));
    h += note('Climax Series (since 2007): the 2nd and 3rd clubs play a three-game First Stage at the 2nd club\'s park, first to two wins, level wins favour the 2nd club. ' +
      'The pennant winner hosts every game of the Final Stage and starts with a one-win advantage: six games, first to four. From 2026 the Final Stage is seven games with a two-win advantage, first to five, ' +
      'when the two clubs finished ten games or more apart or the First Stage winner finished below .500. Ties count for no one; level wins send the higher seed through. Games end tied after 12 innings.');
    el.innerHTML = h;
    BP.sortable(el);
  });
});

// ── games and the game page ─────────────────────────────────────────────────

BP.routeNpb('games', function (el, params) {
  const S = S0(params);
  return BP.load(y('schedule.json', S)).then(sch => {
    const games = (sch && sch.games) || [];
    if (!games.length) { el.innerHTML = head('Games', 'NPB ' + S) + BP.notBuilt('The schedule', sch); return; }
    const days = Array.from(new Set(games.map(g => g.date))).sort();
    const today = BP.todayISO();
    let d = params.date;
    if (!d || days.indexOf(d) < 0) {
      d = days.filter(x => x >= today)[0] || days[days.length - 1];
      if (String(today).slice(0, 4) !== String(S)) d = days[days.length - 1];
    }
    const i = days.indexOf(d);
    const nav = (i > 0 ? '<a href="' + BP.href('games/' + days[i - 1], L, S) + '">← ' + esc(BP.fmtDate(days[i - 1], { year: false })) + '</a>' : '') +
      (i < days.length - 1 ? ' <a href="' + BP.href('games/' + days[i + 1], L, S) + '">' + esc(BP.fmtDate(days[i + 1], { year: false })) + ' →</a>' : '');
    const list = games.filter(g => g.date === d);
    el.innerHTML = head('Games · ' + BP.fmtDate(d), 'NPB ' + S + ' · times are your local time', nav) + cards(list, { season: S }) +
      note('Model: P(away win), P(tie), P(home win) before the first pitch, from the ratings of earlier days; Kalshi: the mid of each club\'s "wins" market (a tie settles both No).');
  });
});

BP.routeNpb('game', function (el, params) {
  const S = S0(params);
  const gpk = params.id;
  const ys = String(gpk || '').slice(0, 4);
  const season = /^\d{4}$/.test(ys) ? Number(ys) : S;
  return BP.load(y('games/' + gpk + '.json', season)).then(d => {
    if (!BP.ok(d)) {
      return BP.load(y('schedule.json', season)).then(sch => {
        const g = ((sch && sch.games) || []).filter(x => x.gpk === gpk)[0];
        el.innerHTML = head('Game', 'NPB ' + season) + (g ? cards([g], { season: season }) + BP.muted('The full game page is kept for the current season only.') : BP.notBuilt('This game', d));
      });
    }
    const c = d.card || {};
    const home = c.home, away = c.away;
    const st = BP.gameState(c);
    const title = BP.teamShort(away) + ' ' + (isNum(c.as) ? c.as : '') + ' – ' + (isNum(c.hs) ? c.hs : '') + ' ' + BP.teamShort(home);
    let h = head(title, esc(BP.fmtDate(c.date)) + ' · ' + esc((d.venue && (d.venue.en || d.venue.jp)) || '') + (d.venue && d.venue.jp && d.venue.en ? ' <span class="npb-jp">' + esc(d.venue.jp) + '</span>' : '') +
      (c.series ? ' · ' + esc(c.series.desc + (isNum(c.series.game) ? ', game ' + c.series.game : '')) : c.interleague ? ' · interleague' : ''),
      '<a href="' + BP.href('games/' + c.date, L, season) + '">All games that day</a>');
    // line score
    const inn = d.innings || [];
    if (inn.length) {
      const n = Math.max(9, inn.length);
      const cols = [{ label: '' }];
      for (let i = 1; i <= n; i++) cols.push({ label: String(i), align: 'right', sortable: false });
      cols.push({ label: 'R', align: 'right', sortable: false }, { label: 'H', align: 'right', sortable: false }, { label: 'E', align: 'right', sortable: false });
      const rhe = d.rhe || {};
      const line = (side, idx) => {
        const r = [{ v: BP.teamName(c[side]), html: tl(c[side], { short: true }) }];
        for (let i = 0; i < n; i++) { const x = inn[i] ? inn[i][idx] : null; r.push({ v: x, html: isNum(x) ? String(x) : (inn[i] ? 'x' : ''), align: 'right' }); }
        const t = rhe[side] || [];
        r.push({ v: t[0], html: '<b>' + (isNum(t[0]) ? t[0] : (side === 'home' ? c.hs : c.as)) + '</b>', align: 'right' }, { v: t[1], align: 'right' }, { v: t[2], align: 'right' });
        return r;
      };
      h += BP.card('Line score', (c.tie ? 'a tie after ' + inn.length + ' innings · ' : '') + (isNum(d.att) ? int(d.att) + ' attendance · ' : '') + (isNum(d.dur) ? Math.floor(d.dur / 60) + ' h ' + (d.dur % 60) + ' min' : ''),
        BP.tableHTML(cols, [line('away', 0), line('home', 1)], { compact: true }));
    } else h += cards([c], { season: season });
    // model and market
    const m = d.model;
    if (m) {
      const k = d.kalshi || {};
      let mh = '<div class="pad"><div class="npb-3">' +
        ['away', 'tie', 'home'].map(s2 => '<div class="kpi"><div class="kpi-label">' + (s2 === 'tie' ? 'Tie' : esc(BP.teamShort(c[s2])) + ' win') + '</div><div class="kpi-value">' + pct(m['p_' + s2], s2 === 'tie' ? 1 : 0) + '</div>' +
          (s2 !== 'tie' && isNum(k[s2]) ? '<div class="kpi-sub">Kalshi ' + pct(k[s2]) + '</div>' : '') + '</div>').join('') + '</div>' +
        threeBar(m, home, away) +
        '<div class="npb-mrow">Expected runs: ' + esc(BP.teamAbbr(away)) + ' ' + n1(m.mu_away) + ', ' + esc(BP.teamAbbr(home)) + ' ' + n1(m.mu_home) + ' (total ' + n1(m.total) + ')' +
        (m.p_over ? ' · over 7.5 ' + pct(m.p_over['7.5']) + ' · over 8.5 ' + pct(m.p_over['8.5']) : '') + '</div>' +
        '<div class="chart-box npb-chart" id="npb-runs"></div>' +
        '<div class="muted-inline">' + (m.source === 'walk-forward' ? 'Priced before the game from the ratings of earlier days' : 'Priced from the current ratings') +
        (m.sp_home || m.sp_away ? '; starters ' + esc(m.sp_away || '?') + ' and ' + esc(m.sp_home || '?') : '') + '. Extra innings up to ' + esc((d.rules || {}).max_innings || 'no limit') +
        '; DH ' + ((d.rules || {}).dh ? 'used' : 'not used') + ' at this park.</div></div>';
      h += BP.card('The model', 'home, tie, away before the first pitch', mh);
    }
    // decisions and home runs
    const dec = d.decisions || {};
    const hr = d.hr || [];
    if (Object.keys(dec).length || hr.length) {
      h += BP.card('Decisions and home runs', '', '<div class="pad">' + ['w', 'l', 's'].filter(x => dec[x]).map(x => '<div><b>' + { w: 'Win', l: 'Loss', s: 'Save' }[x] + '</b> ' +
        plink(dec[x].pid, dec[x].en || dec[x].name, season) + (dec[x].en ? ' <span class="npb-jp">' + esc(dec[x].name) + '</span>' : '') + '</div>').join('') +
        (hr.length ? '<div class="npb-hr"><b>Home runs</b> ' + hr.map(x => esc(x.name) + (x.n ? ' (' + x.n + ')' : '') + (x.inning ? ', ' + x.inning + 'th inning, ' + x.runs + ' run' + (x.runs > 1 ? 's' : '') + ' off ' + esc(x.pitcher || '') : '')).join('; ') + '</div>' : '') + '</div>');
    }
    // box score
    if (d.box) {
      ['away', 'home'].forEach(side => {
        const bx = d.box[side] || {};
        const bat = bx.bat || [], pit = bx.pit || [];
        const rich = bat.some(r => isNum(r.r));
        const bcols = [{ label: 'Pos' }, { label: 'Batter' }, { label: 'AB', align: 'right' }].concat(rich ? [{ label: 'R', align: 'right' }] : [])
          .concat([{ label: 'H', align: 'right' }, { label: 'RBI', align: 'right' }]).concat(rich ? [{ label: 'SB', align: 'right' }] : [])
          .concat(rich ? [] : [{ label: 'BB', align: 'right' }, { label: 'HBP', align: 'right' }, { label: 'SO', align: 'right' }]);
        if (rich) bcols.push({ label: 'Plate appearances', sortable: false });
        const brows = bat.map(r => {
          const p0 = String(r.pos || '');
          const pos = p0.replace(/[()]/g, '').split('').map(ch => BOX_POS[ch] || ch).join('-');
          const c2 = [{ v: pos, html: '<span class="' + (p0.charAt(0) === '(' ? '' : 'muted-inline') + '">' + esc(pos) + '</span>' }, { v: r.en || r.name, html: plink(r.pid, r.en || r.name, season) + (r.en ? ' <span class="npb-jp">' + esc(r.name) + '</span>' : '') }, { v: r.ab, align: 'right' }];
          if (rich) c2.push({ v: r.r, align: 'right' });
          c2.push({ v: r.h, align: 'right' }, { v: r.rbi, align: 'right' });
          if (rich) c2.push({ v: r.sb, align: 'right' });
          if (!rich) c2.push({ v: r.bb, align: 'right' }, { v: r.hbp, align: 'right' }, { v: r.so, align: 'right' });
          if (rich) c2.push({ v: '', html: '<span class="npb-pa" title="' + esc((r.pa || []).join(' · ')) + '">' + esc((r.pa || []).map(paEn).join(' · ')) + '</span>' });
          return c2;
        });
        const pcols = [{ label: '' }, { label: 'Pitcher' }, { label: 'IP', align: 'right' }, { label: 'BF', align: 'right' }].concat(pit.some(r => isNum(r.np)) ? [{ label: 'NP', align: 'right' }] : [])
          .concat([{ label: 'H', align: 'right' }]).concat(pit.some(r => isNum(r.hr)) ? [{ label: 'HR', align: 'right' }] : [])
          .concat([{ label: 'BB', align: 'right' }, { label: 'HBP', align: 'right' }, { label: 'SO', align: 'right' }]).concat(pit.some(r => isNum(r.r)) ? [{ label: 'R', align: 'right' }] : [])
          .concat([{ label: 'ER', align: 'right' }]);
        const prows = pit.map(r => {
          const c2 = [{ v: r.dec || '', html: r.dec ? '<span class="npb-dec">' + esc(r.dec) + '</span>' : '' }, { v: r.en || r.name, html: plink(r.pid, r.en || r.name, season) + (r.en ? ' <span class="npb-jp">' + esc(r.name) + '</span>' : '') },
            { v: r.outs, html: ipText(r.outs), align: 'right' }, { v: r.bf, align: 'right' }];
          if (pit.some(x => isNum(x.np))) c2.push({ v: r.np, align: 'right' });
          c2.push({ v: r.h, align: 'right' });
          if (pit.some(x => isNum(x.hr))) c2.push({ v: r.hr, align: 'right' });
          c2.push({ v: r.bb, align: 'right' }, { v: r.hbp, align: 'right' }, { v: r.so, align: 'right' });
          if (pit.some(x => isNum(x.r))) c2.push({ v: r.r, align: 'right' });
          c2.push({ v: r.er, align: 'right' });
          return c2;
        });
        h += BP.card(BP.teamName(c[side]) + ' ' + jpOf(c[side]), 'box score (English names where the player is matched; NPB prints surnames)', BP.tableHTML(bcols, brows, { compact: true }) + BP.tableHTML(pcols, prows, { compact: true }));
      });
    }
    h += srcNote();
    el.innerHTML = h;
    BP.sortable(el);
    if (m && m.runs_home) {
      const xs = m.runs_home.map((_, i) => i);
      BP.plot('npb-runs', [{ x: xs, y: m.runs_away, type: 'bar', name: BP.teamAbbr(away), marker: { color: BP.teamColour(away) } },
        { x: xs, y: m.runs_home, type: 'bar', name: BP.teamAbbr(home), marker: { color: BP.teamColour(home) } }],
      { barmode: 'group', height: 240, margin: { l: 44, r: 10, t: 10, b: 36 }, showlegend: true, legend: { orientation: 'h', y: 1.15 },
        xaxis: { title: 'Runs in nine innings', dtick: 1 }, yaxis: { title: 'Probability', tickformat: '.0%' } });
    }
  });
});

// ── players ─────────────────────────────────────────────────────────────────

const BAT_COLS = [['g', 'G', 'int'], ['pa', 'PA', 'int'], ['avg', 'AVG', 'avg'], ['obp', 'OBP', 'avg'], ['slg', 'SLG', 'avg'], ['ops', 'OPS', 'avg'], ['hr', 'HR', 'int'],
  ['rbi', 'RBI', 'int'], ['sb', 'SB', 'int'], ['bb_pct', 'BB%', 'pct'], ['k_pct', 'K%', 'pct'], ['iso', 'ISO', 'avg'], ['woba', 'wOBA', 'avg'], ['wrc_plus', 'wRC+', 'int'],
  ['bat_runs', 'Bat runs', '1'], ['war', 'WAR', '1']];
const PIT_COLS = [['g', 'G', 'int'], ['w', 'W', 'int'], ['l', 'L', 'int'], ['sv', 'SV', 'int'], ['hld', 'HLD', 'int'], ['ip', 'IP', 'ip'], ['era', 'ERA', '2'], ['fip', 'FIP', '2'],
  ['whip', 'WHIP', '2'], ['k9', 'K/9', '1'], ['bb9', 'BB/9', '1'], ['k_pct', 'K%', 'pct'], ['bb_pct', 'BB%', 'pct'], ['hr', 'HR', 'int'], ['era_minus', 'ERA-', 'int'], ['fip_minus', 'FIP-', 'int'], ['war', 'WAR', '1']];

function fv(v, f) { return f === 'ip' ? BP.fmtIP(v) : BP.fmtVal(v, f); }
function playersPage(kind) {
  return function (el, params) {
    const S = S0(params);
    return BP.load(y('players.json', S)).then(d => {
      const ttl = kind === 'bat' ? 'Hitters' : 'Pitchers';
      if (!BP.ok(d)) { el.innerHTML = head(ttl, 'NPB ' + S) + BP.notBuilt('Player statistics', d); return; }
      const q = params.query || {};
      let lg = q.lg || 'all', min = isNum(q.min) ? Number(q.min) : (kind === 'bat' ? 200 : 40);
      const draw = () => {
        const rows = (d[kind] || []).filter(r => (lg === 'all' || r.league === lg) && (kind === 'bat' ? (r.pa || 0) >= min && !r.pitcher : (r.ip || 0) >= min))
          .sort((a, b) => (b.war || -99) - (a.war || -99));
        const COLS = kind === 'bat' ? BAT_COLS : PIT_COLS;
        const cols = [{ label: '#' }, { label: kind === 'bat' ? 'Hitter' : 'Pitcher' }, { label: 'Club' }, { label: kind === 'bat' ? 'Pos' : 'Role' }].concat(COLS.map(c => ({ label: c[1], align: 'right' })));
        const body = rows.map((r, i) => [i + 1, { v: r.name, html: plink(r.pid, r.name, S) + ' <span class="npb-jp">' + esc(r.jp || '') + '</span>' },
          { v: BP.teamAbbr(r.team), html: tl(r.team, { abbr: true }) }, kind === 'bat' ? (r.pos || '') : (r.role || '')]
          .concat(COLS.map(c => ({ v: r[c[0]], html: fv(r[c[0]], c[2]), align: 'right' }))));
        el.querySelector('#npb-tbl').innerHTML = BP.tableHTML(cols, body, { compact: true, sticky: true });
        BP.sortable(el.querySelector('#npb-tbl'));
      };
      const lc = d.league || {};
      el.innerHTML = head(ttl, 'NPB ' + S + ' · ' + (d[kind] || []).length + ' players') +
        '<div class="card"><div class="toggle-row"><span>League</span>' + BP.toggles([{ key: 'all', label: 'Both' }, { key: 'CL', label: 'Central' }, { key: 'PL', label: 'Pacific' }], lg, 'data-lg') +
        '<span>Minimum</span>' + BP.toggles((kind === 'bat' ? [50, 200, 400] : [10, 40, 100]).map(v => ({ key: v, label: (kind === 'bat' ? v + ' PA' : v + ' IP') })), min, 'data-min') + '</div>' +
        '<div id="npb-tbl"></div></div>' +
        BP.card('League constants', 'from each league\'s own season (the DH league and the pitcher-batting league kept apart)', BP.tableHTML(
          [{ label: 'League' }, { label: 'R/G', align: 'right' }, { label: 'wOBA', align: 'right' }, { label: 'Scale', align: 'right' }, { label: '1B', align: 'right' },
            { label: '2B', align: 'right' }, { label: '3B', align: 'right' }, { label: 'HR', align: 'right' }, { label: 'BB', align: 'right' }, { label: 'ERA', align: 'right' },
            { label: 'FIP const', align: 'right' }, { label: 'Runs/win', align: 'right' }],
          Object.keys(lc).map(k => { const c = lc[k], w = c.woba_weights || {}; return [LG_NAME[k], { v: c.r_per_game, html: n2(c.r_per_game), align: 'right' },
            { v: c.lg_woba, html: avg(c.lg_woba), align: 'right' }, { v: c.woba_scale, html: n2(c.woba_scale), align: 'right' }, { v: w['1b'], html: n2(w['1b']), align: 'right' },
            { v: w['2b'], html: n2(w['2b']), align: 'right' }, { v: w['3b'], html: n2(w['3b']), align: 'right' }, { v: w.hr, html: n2(w.hr), align: 'right' },
            { v: w.bb, html: n2(w.bb), align: 'right' }, { v: c.era, html: n2(c.era), align: 'right' }, { v: c.c_fip, html: n2(c.c_fip), align: 'right' },
            { v: c.rpw, html: n2(c.rpw), align: 'right' }]; }), { compact: true })) +
        note('WAR-lite: batting runs (wOBA from BaseRuns linear weights, park- and league-adjusted) plus base-stealing runs plus a positional adjustment (from box-score starts) plus replacement; ' +
          'pitchers from FIP on the run-average scale. No Statcast, no pitch tracking and no fielding data exist for NPB. English names from NPB\'s English pages where it prints them, else romanised from the Japanese reading.') + srcNote();
      BP.wireToggles(el, 'data-lg', k => { lg = k; draw(); });
      BP.wireToggles(el, 'data-min', k => { min = Number(k); draw(); });
      draw();
    });
  };
}
BP.routeNpb('hitters', playersPage('bat'));
BP.routeNpb('pitchers', playersPage('pit'));

BP.routeNpb('player', function (el, params) {
  const S = S0(params);
  const pid = params.id;
  const shard = String(pid || '').slice(-2);
  return BP.loadAll(['npb/careers/' + shard + '.json', y('players.json', S)]).then(res => {
    const cr = ((res[0] || {}).players || {})[pid];
    const pl = res[1] || {};
    const cb = (pl.bat || []).filter(r => r.pid === pid), cp = (pl.pit || []).filter(r => r.pid === pid);
    const name = (cr && cr.name) || (cb[0] || cp[0] || {}).name || pid;
    const jp = (cr && cr.jp) || (cb[0] || cp[0] || {}).jp || '';
    const bio = cr ? [cr.pos ? { P: 'Pitcher', C: 'Catcher', IF: 'Infielder', OF: 'Outfielder' }[cr.pos] || cr.pos : null, cr.bats ? 'bats ' + cr.bats : null,
      cr.throws ? 'throws ' + cr.throws : null, cr.born ? 'born ' + BP.fmtDate(cr.born) : null, cr.ht ? cr.ht + ' cm, ' + cr.wt + ' kg' : null, cr.draft || null].filter(Boolean).join(' · ') : '';
    let h = head(name, '<span class="npb-jp-big">' + esc(jp) + '</span>' + (cr && cr.kana ? ' <span class="muted-inline">' + esc(cr.kana) + '</span>' : '') + (bio ? '<br>' + esc(bio) : ''));
    const cur = cb.concat(cp);
    if (cur.length) {
      const r = cb[0], p = cp[0];
      h += '<div class="kpi-grid five">' + (r ? BP.statTile('WAR-lite (bat)', n1(r.war), S) + BP.statTile('wRC+', int(r.wrc_plus), 'wOBA ' + avg(r.woba)) +
        BP.statTile('AVG / OBP / SLG', avg(r.avg) + ' / ' + avg(r.obp) + ' / ' + avg(r.slg), r.pa + ' PA') : '') +
        (p ? BP.statTile('WAR-lite (pitch)', n1(p.war), S) + BP.statTile('ERA / FIP', n2(p.era) + ' / ' + n2(p.fip), BP.fmtIP(p.ip) + ' IP') : '') + '</div>';
    }
    if (cr && (cr.bat || []).length && (cr.bat || []).some(x => (x.pa || 0) > 0)) {
      const rows = cr.bat.map(x => {
        const ab = x.ab || 0, h1 = x.h || 0, obd = ab + (x.bb || 0) + (x.hbp || 0) + (x.sf || 0);
        const tb = h1 + (x.d || 0) + 2 * (x.t || 0) + 3 * (x.hr || 0);
        return [x.season, { v: x.team_jp, html: x.team ? tl(x.team, { abbr: true, season: x.season }) : esc(x.team_jp || '') }, { v: x.g, align: 'right' }, { v: x.pa, align: 'right' },
          { v: ab, align: 'right' }, { v: x.h, align: 'right' }, { v: x.d, align: 'right' }, { v: x.t, align: 'right' }, { v: x.hr, align: 'right' }, { v: x.rbi, align: 'right' },
          { v: x.sb, align: 'right' }, { v: x.bb, align: 'right' }, { v: x.so, align: 'right' },
          { v: ab ? h1 / ab : null, html: ab ? avg(h1 / ab) : '—', align: 'right' }, { v: obd ? (h1 + (x.bb || 0) + (x.hbp || 0)) / obd : null, html: obd ? avg((h1 + (x.bb || 0) + (x.hbp || 0)) / obd) : '—', align: 'right' },
          { v: ab ? tb / ab : null, html: ab ? avg(tb / ab) : '—', align: 'right' }];
      });
      h += BP.card('Batting by season', 'regular season, as NPB records it', BP.tableHTML(['Year', 'Club'].map(lb => ({ label: lb })).concat(['G', 'PA', 'AB', 'H', '2B', '3B', 'HR', 'RBI', 'SB', 'BB', 'SO', 'AVG', 'OBP', 'SLG'].map(lb => ({ label: lb, align: 'right' }))), rows, { compact: true }));
    }
    if (cr && (cr.pit || []).length) {
      const rows = cr.pit.map(x => {
        const ip = (x.outs || 0) / 3;
        return [x.season, { v: x.team_jp, html: x.team ? tl(x.team, { abbr: true, season: x.season }) : esc(x.team_jp || '') }, { v: x.g, align: 'right' }, { v: x.w, align: 'right' },
          { v: x.l, align: 'right' }, { v: x.sv, align: 'right' }, { v: x.hld, align: 'right' }, { v: x.outs, html: ipText(x.outs), align: 'right' }, { v: x.so, align: 'right' },
          { v: x.bb, align: 'right' }, { v: x.hr, align: 'right' }, { v: ip ? x.er / ip * 9 : null, html: ip ? n2(x.er / ip * 9) : '—', align: 'right' },
          { v: ip ? ((x.h || 0) + (x.bb || 0)) / ip : null, html: ip ? n2(((x.h || 0) + (x.bb || 0)) / ip) : '—', align: 'right' }];
      });
      h += BP.card('Pitching by season', 'regular season', BP.tableHTML(['Year', 'Club'].map(lb => ({ label: lb })).concat(['G', 'W', 'L', 'SV', 'HLD', 'IP', 'SO', 'BB', 'HR', 'ERA', 'WHIP'].map(lb => ({ label: lb, align: 'right' }))), rows, { compact: true }));
    }
    if (!cr) h += BP.muted('The career record of this player is not on the site yet (the career pages are filled in by the backfill).');
    h += note('Names: English as NPB prints it where it does, else romanised from the Japanese reading (macrons dropped). WAR-lite and wRC+ are for the season shown.') + srcNote();
    el.innerHTML = h;
    BP.sortable(el);
  });
});

// ── teams ───────────────────────────────────────────────────────────────────

BP.routeNpb('teams', function (el, params) {
  const S = S0(params);
  return BP.load(y('teams.json', S)).then(d => {
    if (!BP.ok(d)) { el.innerHTML = head('Teams', 'NPB ' + S) + BP.notBuilt('Teams', d); return; }
    const T = d.teams || {};
    const rows = Object.keys(T).map(t => Object.assign({ tid: t }, T[t])).sort((a, b) => ((b.record || {}).pct || 0) - ((a.record || {}).pct || 0));
    el.innerHTML = head('Teams', 'NPB ' + S + ' · twelve clubs, two leagues') + BP.card('', '', BP.tableHTML([{ label: 'Club' }, { label: 'Japanese' }, { label: 'Lg' }, { label: 'W-L-T', align: 'right' },
      { label: 'PCT', align: 'right' }, { label: 'RS', align: 'right' }, { label: 'RA', align: 'right' }, { label: 'Rating', align: 'right' }, { label: 'Park', align: 'right', title: 'Run park factor (halved)' },
      { label: 'WAR bat', align: 'right' }, { label: 'WAR pitch', align: 'right' }],
    rows.map(r => { const rc = r.record || {}; return [{ v: r.name, html: tl(r.tid) }, r.jp || '', r.league, { v: rc.w, html: rc.w + '-' + rc.l + '-' + rc.t, align: 'right' },
      { v: rc.pct, html: avg(rc.pct), align: 'right' }, { v: rc.rs, align: 'right' }, { v: rc.ra, align: 'right' }, { v: (r.rating || {}).net, html: r.rating ? BP.signed(r.rating.net, 3) : '—', align: 'right' },
      { v: r.park_factor, html: n2(r.park_factor), align: 'right' }, { v: r.war_bat, html: n1(r.war_bat), align: 'right' }, { v: r.war_pit, html: n1(r.war_pit), align: 'right' }]; }), { compact: true })) + srcNote();
    BP.sortable(el);
  });
});

BP.routeNpb('team', function (el, params) {
  const S = S0(params);
  const tid = params.id;
  return BP.loadAll([y('teams.json', S), y('season.json', S)]).then(res => {
    const d = res[0], sp = res[1] || {};
    const t = d && d.teams ? d.teams[tid] : null;
    if (!t) { el.innerHTML = head(BP.teamName(tid), 'NPB ' + S) + BP.notBuilt('This club', d); return; }
    const rc = t.record || {};
    let h = head(t.name, '<span class="npb-jp-big">' + esc(t.jp || '') + '</span> · ' + esc(LG_NAME[t.league] || '') + ' · ' + S);
    h += '<div class="kpi-grid five">' + BP.statTile('Record', rc.w + '-' + rc.l + '-' + rc.t, 'rank ' + (rc.rank || '—')) + BP.statTile('PCT', avg(rc.pct), 'Pythagorean ' + avg(rc.pyth)) +
      BP.statTile('Runs', (rc.rs || 0) + ' / ' + (rc.ra || 0), 'scored / allowed') + BP.statTile('Rating', t.rating ? BP.signed(t.rating.net, 3) : '—', t.rating ? 'off ' + BP.signed(t.rating.off, 3) + ' · def ' + BP.signed(t.rating.def, 3) : '') +
      BP.statTile('Park factor', n2(t.park_factor), 'runs, halved') + '</div>';
    const track = (sp.ratings_track || {})[tid];
    if (track && track.length > 5) h += BP.card('Rating through the season', 'offence plus defence on the log-runs scale', '<div class="chart-box npb-chart" id="npb-track"></div>');
    h += '<div class="grid-2">' + BP.card('Leading hitters', 'WAR-lite', BP.tableHTML([{ label: 'Hitter' }, { label: 'PA', align: 'right' }, { label: 'wRC+', align: 'right' }, { label: 'WAR', align: 'right' }],
      (t.top_bat || []).map(r => [{ v: r.name, html: plink(r.pid, r.name, S) }, { v: r.pa, align: 'right' }, { v: r.wrc_plus, align: 'right' }, { v: r.war, html: n1(r.war), align: 'right' }]), { compact: true })) +
      BP.card('Leading pitchers', 'WAR-lite', BP.tableHTML([{ label: 'Pitcher' }, { label: 'IP', align: 'right' }, { label: 'FIP', align: 'right' }, { label: 'WAR', align: 'right' }],
        (t.top_pit || []).map(r => [{ v: r.name, html: plink(r.pid, r.name, S) }, { v: r.ip, html: BP.fmtIP(r.ip), align: 'right' }, { v: r.fip, html: n2(r.fip), align: 'right' }, { v: r.war, html: n1(r.war), align: 'right' }]), { compact: true })) + '</div>';
    h += '<div id="npb-value"></div>';
    const res2 = (t.results || []).slice().reverse();
    h += BP.card('Games', 'every game, with the model\'s pre-game chance of winning', BP.tableHTML([{ label: 'Date' }, { label: 'Opponent' }, { label: 'Score', align: 'right' }, { label: 'Result' }, { label: 'Model', align: 'right' }, { label: 'Type' }],
      res2.map(r => { const fin = r[6] === 'final'; const resT = fin ? (r[4] > r[5] ? 'W' : r[4] < r[5] ? 'L' : 'T') : (r[6] || ''); return [{ v: r[1], html: '<a href="' + ghref(r[0], S) + '">' + esc(BP.fmtDate(r[1], { year: false })) + '</a>' },
        { v: BP.teamName(r[2]), html: (r[3] ? 'v ' : '@ ') + tl(r[2], { short: true }) }, { v: r[4], html: fin ? r[4] + '-' + r[5] : '—', align: 'right' },
        { v: resT, html: '<span class="npb-res ' + resT + '">' + esc(resT) + '</span>' }, { v: r[8], html: isNum(r[8]) ? pct(r[8]) : '—', align: 'right' }, STAGE[r[7]] || (r[7] === 'R' ? '' : r[7])]; }), { compact: true }));
    h += BP.card('Names', 'the franchise over time', '<div class="pad">' + (t.names || []).map(n => '<div>' + n.from + '–' + (n.to || '') + ' <b>' + esc(n.name) + '</b> <span class="npb-jp">' + esc(n.jp) + '</span></div>').join('') + '</div>');
    el.innerHTML = h + srcNote();
    BP.sortable(el);
    if (typeof BP.valueTeam === 'function') BP.valueTeam(document.getElementById('npb-value'), L, S, tid);   // value.js: strengths and needs
    if (track && track.length > 5) BP.plot('npb-track', [{ x: track.map(r => r[0]), y: track.map(r => r[1]), type: 'scatter', mode: 'lines', line: { color: BP.teamColour(tid), width: 2 } }],
      { height: 240, margin: { l: 50, r: 10, t: 10, b: 36 }, yaxis: { title: 'Rating (log runs)', zeroline: true } });
  });
});

// ── leaders ─────────────────────────────────────────────────────────────────

BP.routeNpb('leaders', function (el, params) {
  const S = S0(params);
  return BP.loadAll([y('players.json', S), y('season.json', S)]).then(res => {
    const d = res[0], sp = res[1] || {};
    if (!BP.ok(d)) { el.innerHTML = head('Leaders', 'NPB ' + S) + BP.notBuilt('Player statistics', d); return; }
    const games = {};
    ['CL', 'PL'].forEach(lg => ((sp.standings || {})[lg] || []).forEach(r => { games[r.tid] = r.g; }));
    const qPA = r => (r.pa || 0) >= 3.1 * (games[r.team] || 143), qIP = r => (r.ip || 0) >= (games[r.team] || 143);
    const boards = [['bat', 'war', 'WAR-lite', '1', false, null], ['bat', 'avg', 'Batting average (qualified)', 'avg', false, qPA], ['bat', 'hr', 'Home runs', 'int', false, null],
      ['bat', 'rbi', 'Runs batted in', 'int', false, null], ['bat', 'sb', 'Stolen bases', 'int', false, null], ['bat', 'ops', 'OPS (qualified)', 'avg', false, qPA],
      ['bat', 'wrc_plus', 'wRC+ (qualified)', 'int', false, qPA], ['pit', 'war', 'WAR-lite', '1', false, null], ['pit', 'era', 'ERA (qualified)', '2', true, qIP],
      ['pit', 'w', 'Wins', 'int', false, null], ['pit', 'sv', 'Saves', 'int', false, null], ['pit', 'hld', 'Holds', 'int', false, null], ['pit', 'so', 'Strikeouts', 'int', false, null],
      ['pit', 'fip', 'FIP (qualified)', '2', true, qIP]];
    let h = head('Leaders', 'NPB ' + S + ' · qualified: 3.1 plate appearances or 1 inning per club game');
    ['CL', 'PL'].forEach(lg => {
      h += '<div class="card"><div class="card-header">' + esc(LG_NAME[lg]) + ' <span class="card-sub">' + esc(LG_JP[lg]) + '</span></div><div class="npb-ld">' + boards.map(b => {
        const rows = (d[b[0]] || []).filter(r => r.league === lg && isNum(r[b[1]]) && (!b[5] || b[5](r)) && !(b[0] === 'bat' && r.pitcher)).sort((a, c) => b[4] ? a[b[1]] - c[b[1]] : c[b[1]] - a[b[1]]).slice(0, 10);
        return '<div class="npb-ld-col"><div class="npb-ld-h">' + esc(b[2]) + '</div>' + rows.map(r => '<div class="npb-ld-r">' + plink(r.pid, r.name, S) + ' <span class="muted-inline">' + esc(BP.teamAbbr(r.team)) +
          '</span><b>' + fv(r[b[1]], b[3]) + '</b></div>').join('') + '</div>';
      }).join('') + '</div></div>';
    });
    el.innerHTML = h + srcNote();
  });
});

// ── history ─────────────────────────────────────────────────────────────────

/* A club's name in a given season from history.json "franchises" (every name it has carried). */
function nameAt(fr, tid, season) {
  const rows = (fr || {})[tid] || [];
  let best = null;
  rows.forEach(r => { if (r.from <= season) best = r; });
  return best ? best.name : BP.teamName(tid);
}
BP.routeNpb('history', function (el, params) {
  return BP.load('npb/history.json').then(d => {
    if (!BP.ok(d)) { el.innerHTML = head('History', 'NPB') + BP.notBuilt('History', d); return; }
    const info = d.teams_info || {};
    Object.keys(info).forEach(t => { if (!BP.TEAMS[t] || !BP.TEAMS[t].name) BP.TEAMS[t] = Object.assign({}, info[t]); });
    const fr = d.franchises || {};
    const tlS = (tid, season, short) => { const nm = nameAt(fr, tid, season); return tl(tid, { name: short ? nm.split(' ').slice(-1)[0] : nm, season: season }); };
    const seasons = (d.seasons || []).slice().reverse();
    const body = seasons.map(r => {
      const js = r.js || {};
      const cl = (r.leagues || {}).CL || {}, pl = (r.leagues || {}).PL || {};
      const mvp = lg => ((r.leagues || {})[lg] || {}).awards ? (((r.leagues || {})[lg] || {}).awards || []).filter(a => a.award === 'MVP')[0] : null;
      const mvpC = mvp('CL'), mvpP = mvp('PL');
      return [{ v: r.season, html: '<a href="' + BP.href('', L, r.season) + '">' + r.season + '</a>' },
        { v: js.winner ? nameAt(fr, js.winner, r.season) : '', html: js.winner ? tlS(js.winner, r.season) + ' <span class="muted-inline">' + (js.wins || []).join('-') + (js.ties ? ', ' + js.ties + ' tie' + (js.ties > 1 ? 's' : '') : '') + '</span>' : '—' },
        { v: js.loser ? nameAt(fr, js.loser, r.season) : '', html: js.loser ? tlS(js.loser, r.season, true) : '—' },
        { v: cl.pennant || '', html: cl.pennant ? tlS(cl.pennant, r.season, true) : '—' }, { v: cl.cs_winner || '', html: cl.cs_winner ? tlS(cl.cs_winner, r.season, true) : '' },
        { v: pl.pennant || '', html: pl.pennant ? tlS(pl.pennant, r.season, true) : '—' }, { v: pl.cs_winner || '', html: pl.cs_winner ? tlS(pl.cs_winner, r.season, true) : '' },
        { v: mvpC ? mvpC.name : '', html: mvpC ? plink(mvpC.pid, mvpC.name) : '' }, { v: mvpP ? mvpP.name : '', html: mvpP ? plink(mvpP.pid, mvpP.name) : '' }];
    });
    let h = head('History', 'Nippon Professional Baseball since 1950 · the two-league era');
    h += BP.card('Champions', 'Japan Series, pennants (first place) and Climax Series winners, MVPs', BP.tableHTML([{ label: 'Year' }, { label: 'Japan Series' }, { label: 'Runner-up' }, { label: 'CL pennant' },
      { label: 'CL CS' }, { label: 'PL pennant' }, { label: 'PL CS' }, { label: 'CL MVP' }, { label: 'PL MVP' }], body, { compact: true, sticky: true }));
    const titles = d.titles || {};
    const tr = Object.keys(titles).map(t => [{ v: BP.teamName(t), html: tl(t) }, { v: titles[t].js || 0, align: 'right' }, { v: titles[t].pennants || 0, align: 'right' }])
      .sort((a, b) => b[1].v - a[1].v);
    h += '<div class="grid-2">' + BP.card('Titles since 1950', 'Japan Series wins and first-place finishes', BP.tableHTML([{ label: 'Club' }, { label: 'Japan Series', align: 'right' }, { label: 'Pennants', align: 'right' }], tr, { compact: true })) +
      BP.card('Club names', 'every name a franchise has carried', '<div class="pad npb-names">' + Object.keys(d.franchises || {}).map(t => '<div><b>' + esc(BP.teamName(t)) + '</b>: ' +
        (d.franchises[t] || []).map(n => esc(n.name) + ' <span class="npb-jp">' + esc(n.jp) + '</span> (' + n.from + '–' + (n.to || '') + ')').join(' → ') + '</div>').join('') + '</div>') + '</div>';
    const ld = d.leaders || {};
    if (Object.keys(ld).length) h += BP.card('All-time leaders', 'career totals, regular season', '<div class="npb-ld">' + Object.keys(ld).map(k => '<div class="npb-ld-col"><div class="npb-ld-h">' + esc(ld[k].label) + '</div>' +
      (ld[k].rows || []).slice(0, 15).map(r => '<div class="npb-ld-r">' + plink(r[0], r[1]) + ' <span class="muted-inline">' + (r[4] || '') + '–' + (r[5] || '') + '</span><b>' + int(r[3]) + '</b></div>').join('') + '</div>').join('') + '</div>');
    // a season's standings and awards
    const sel = '<select id="npb-hs">' + seasons.map(r => '<option value="' + r.season + '">' + r.season + '</option>').join('') + '</select>';
    h += '<div class="card"><div class="card-header">Season <span class="card-sub">' + sel + '</span></div><div id="npb-hseason"></div></div>';
    el.innerHTML = h + note('Standings, awards and title leaders from NPB\'s yearly league pages (1950 on); Japan Series results from NPB\'s series records; Climax Series from the box scores (2007 on).') + srcNote();
    BP.sortable(el);
    const show = sv => {
      const r = seasons.filter(x => String(x.season) === String(sv))[0];
      if (!r) return;
      el.querySelector('#npb-hseason').innerHTML = '<div class="grid-2">' + ['CL', 'PL'].map(lg => {
        const x = (r.leagues || {})[lg] || {};
        return '<div>' + BP.tableHTML([{ label: LG_NAME[lg] }, { label: 'W', align: 'right' }, { label: 'L', align: 'right' }, { label: 'T', align: 'right' }, { label: 'PCT', align: 'right' },
          { label: 'GB', align: 'right' }, { label: 'RS', align: 'right' }, { label: 'RA', align: 'right' }],
        (x.standings || []).map(s2 => [{ v: s2.name, html: s2.tid ? tl(s2.tid, { season: r.season, name: s2.name }) + ' <span class="npb-jp">' + esc(s2.jp) + '</span>' : esc(s2.jp) }, { v: s2.w, align: 'right' }, { v: s2.l, align: 'right' }, { v: s2.t, align: 'right' },
          { v: s2.pct, html: avg(s2.pct), align: 'right' }, { v: s2.gb, html: s2.gb ? n1(s2.gb) : '—', align: 'right' }, { v: s2.rs, align: 'right' }, { v: s2.ra, align: 'right' }]), { compact: true }) +
          '<div class="pad npb-aw">' + (x.awards || []).map(a => '<div><span class="muted-inline">' + esc(a.award) + '</span> ' + plink(a.pid, a.name) + (a.team ? ' <span class="muted-inline">' + esc(BP.teamAbbr(a.team)) + '</span>' : '') +
            (a.value ? ' <b>' + esc(a.value) + '</b>' : '') + '</div>').join('') + '</div></div>';
      }).join('') + '</div>';
    };
    const s = el.querySelector('#npb-hs');
    if (s) { s.addEventListener('change', () => show(s.value)); show(s.value); }
  });
});

// ── calibration ─────────────────────────────────────────────────────────────

BP.routeNpb('calibration', function (el) {
  return BP.load('npb/calibration.json').then(d => {
    if (!BP.ok(d)) { el.innerHTML = head('Calibration', 'NPB') + BP.notBuilt('The NPB backtest', d); return; }
    const G = d.games || {};
    const te = G.test || {}, tr = G.train || {};
    let h = head('Calibration', 'NPB · the walk-forward game backtest: three outcomes, home, tie, away');
    h += '<div class="kpi-grid five">' + BP.statTile('Games scored (test)', int(te.n), 'from ' + te.from) + BP.statTile('Log loss', BP.num(te.logloss, 4), 'baseline ' + BP.num(te.base_logloss, 4)) +
      BP.statTile('Skill', pct(te.skill_logloss, 1), 'log loss below the baseline') + BP.statTile('Brier', BP.num(te.brier, 4), 'baseline ' + BP.num(te.base_brier, 4)) +
      BP.statTile('Ties', pct(te.tie_pred, 1) + ' predicted', pct(te.tie_rate, 1) + ' actual') + '</div>';
    const bs = G.by_season || {};
    h += BP.card('By season', 'parameters chosen on ' + ((tr.seasons || []).join('–')) + '; later seasons out of sample', BP.tableHTML([{ label: 'Season' }, { label: 'Games', align: 'right' }, { label: 'Log loss', align: 'right' },
      { label: 'Baseline', align: 'right' }, { label: 'Brier', align: 'right' }, { label: 'Favourite right', align: 'right' }, { label: 'Ties pred.', align: 'right' }, { label: 'Ties', align: 'right' },
      { label: 'Total MAE', align: 'right' }, { label: 'Extra innings to', align: 'right' }],
    Object.keys(bs).sort().reverse().map(s => { const x = bs[s]; return [s, { v: x.n, align: 'right' }, { v: x.logloss, html: BP.num(x.logloss, 4), align: 'right' }, { v: x.base_logloss, html: BP.num(x.base_logloss, 4), align: 'right' },
      { v: x.brier, html: BP.num(x.brier, 4), align: 'right' }, { v: x.acc, html: pct(x.acc, 1), align: 'right' }, { v: x.tie_pred, html: pct(x.tie_pred, 1), align: 'right' },
      { v: x.tie_rate, html: pct(x.tie_rate, 1), align: 'right' }, { v: x.total_mae, html: n2(x.total_mae), align: 'right' }, { v: x.max_innings, align: 'right' }]; }), { compact: true }));
    h += BP.card('Calibration of P(home win)', 'test seasons, by decile', '<div class="chart-box npb-chart" id="npb-cal"></div>');
    const k = G.kalshi;
    if (k) h += BP.card('Against Kalshi', esc(k.n) + ' games with a pre-game price (2026)', '<div class="pad">' + BP.tableHTML([{ label: '' }, { label: 'Log loss', align: 'right' }, { label: 'Brier', align: 'right' }],
      [['Model', { v: k.model_logloss, html: BP.num(k.model_logloss, 4), align: 'right' }, { v: k.model_brier, html: BP.num(k.model_brier, 4), align: 'right' }],
        ['Kalshi', { v: k.kalshi_logloss, html: BP.num(k.kalshi_logloss, 4), align: 'right' }, { v: k.kalshi_brier, html: BP.num(k.kalshi_brier, 4), align: 'right' }],
        ['Average of the two', { v: k.blend_logloss, html: BP.num(k.blend_logloss, 4), align: 'right' }, '']], { compact: true }) +
      '<div class="muted-inline">' + esc(k.note || '') + '; mean absolute gap ' + pct(k.mean_abs_gap, 1) + ', correlation ' + n2(k.corr) + '.</div></div>');
    const ps = G.postseason_test;
    if (ps && ps.n) h += note('Postseason games in the test seasons: ' + ps.n + ', log loss ' + BP.num(ps.logloss, 4) + ' against ' + BP.num(ps.base_logloss, 4) + '.');
    const p = d.params || {};
    h += BP.card('Parameters', '', '<div class="pad"><code class="npb-code">' + esc(JSON.stringify(p.rating || {})) + '</code><br><code class="npb-code">' + esc(JSON.stringify(p.game || {})) + '</code></div>');
    h += note((d.notes || []).map(esc).join(' '));
    el.innerHTML = h;
    BP.sortable(el);
    const cal = G.calibration || [];
    if (cal.length) BP.plot('npb-cal', [{ x: [0.2, 0.8], y: [0.2, 0.8], mode: 'lines', line: { color: '#6e7681', dash: 'dot' } },
      { x: cal.map(b => b.pred), y: cal.map(b => b.actual), mode: 'markers+lines', marker: { size: 8, color: BP.C.clay }, text: cal.map(b => b.n + ' games'), hovertemplate: 'predicted %{x:.1%}<br>actual %{y:.1%}<br>%{text}<extra></extra>' }],
    { height: 300, margin: { l: 50, r: 10, t: 10, b: 40 }, xaxis: { title: 'Predicted P(home win)', tickformat: '.0%' }, yaxis: { title: 'Home wins', tickformat: '.0%' } });
  });
});

// ── routes the level does not have ──────────────────────────────────────────

BP.routeNpb('*', function (el) {
  const r = (BP.state || {}).route || '';
  el.innerHTML = head(BP.TITLES[r] || 'Not available', 'NPB') + '<div class="card"><div class="pad">' +
    '<p>This page is built from MLB and Triple-A pitch tracking (Statcast), which does not exist for Nippon Professional Baseball, so the NPB level does not have it.</p>' +
    '<p><a href="#/npb">NPB hub</a> · <a href="' + BP.href('standings', L) + '">Standings</a> · <a href="#/postseason">Postseason</a> · <a href="' + BP.href('hitters', L) + '">Hitters</a> · ' +
    '<a href="' + BP.href('pitchers', L) + '">Pitchers</a> · <a href="#/history">History</a> · <a href="#/calibration">Calibration</a> · <a href="#/mlb">MLB</a></p></div></div>';
});

BP.npb = { card: card, bracketHTML: bracketHTML };
})(window.BP);
