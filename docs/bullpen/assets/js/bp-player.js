/* The Quant Bullpen — the player page (#/<L>/hitter/<pid>, #/<L>/pitcher/<pid>, #/player/<pid>) on kit v4 "Broadcast"
 * (the Rink player page is the reference, MIGRATION_V4.md).
 *
 * Overview, as the concept: a crumb; the full-bleed team-colour hero (QK.playerHeader: the alternate colour on a
 *   diagonal, the outlined initials, the name in Bebas, chips) with the black strip of five numbers (percentiles
 *   against the peers) and "The short version"; the LED percentile meters against the position (hitters: catchers,
 *   first base ... designated hitter) or role (starters, relievers), the spec's metric set (docs/METRICS_SPEC.md;
 *   BP.ui.SETS), the sample and the floor shown, early metrics dashed, a plain line per metric and a ▼ for last
 *   season (from the player file when the builder writes it, else last season's catalogue when the rail scrolls
 *   into view), with "How sure are we?" under them; beside them the tale of the tape against the closest match this
 *   season (chips switch between the three closest; verdicts under it); pitchers: the arsenal (pitch mix and the
 *   movement chart, in the pitch colours, against the league's averages for each type); what to watch tonight (the
 *   club's next game as the scoreboard bug, with the probable starters and how the clubs match up) beside the last
 *   game (the line score by inning and our win chance through it, from the game file); the form through the season
 *   and "Their type"; then among peers (peers.json when the build writes it), next season's projection with its 80%
 *   range, splits, movement, season by season.
 * Detail (?view=detail): the full pre-redesign page (every metric, spray chart, zones, bat tracking, tunnels ...).
 *
 * First load: data/players/<pid>.json (the current season's values, pct_role and samples are in it), glossary.json and
 * <L>/<S>/season.json (team games, for prorating the floor). The catalogue (hitters.json / pitchers.json) loads only for
 * the distribution, the compare and the Detail view. Older seasons and levels other than the player's current one open
 * Detail. */
(function (BP) {
'use strict';

const U = BP.ui, esc = BP.esc, isNum = BP.isNum;
const LEG = { hitter: BP.HANDLERS.hitter, pitcher: BP.HANDLERS.pitcher, player: BP.HANDLERS.player };
const DIST = { hitter: [['xwoba_n', 'xwOBA+'], ['war_600', 'WAR/600'], ['barrel_pct', 'Barrel%'], ['k_pct', 'K%'], ['chase_pct', 'Chase%']],
  pitcher: [['xwoba_n', 'xwOBA+ against'], ['stuff_plus', 'Stuff+'], ['k_bb_pct', 'K-BB%'], ['csw_pct', 'CSW%'], ['xfip', 'xFIP']] };
const NUMW = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten'];

function age(dob) { const d = BP.parseDate(dob); return d ? Math.floor((Date.now() - d.getTime()) / (365.25 * 864e5)) : null; }
function teamGames(season, tid) {
  const rows = BP.standingsRows ? BP.standingsRows(season || {}) : {};
  const r = rows[String(tid)];
  return r && isNum(r.w) && isNum(r.l) ? r.w + r.l : null;
}
function lc(x) { return /^[A-Z][a-z]/.test(x) ? x.charAt(0).toLowerCase() + x.slice(1) : x; }
/* An IntersectionObserver trigger (once), or straight away on old browsers. */
function onView(node, fn, margin) {
  if (!node) return;
  if (!window.IntersectionObserver) { fn(); return; }
  const io = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) { io.disconnect(); fn(); } }, { rootMargin: margin || '250px', threshold: 0.01 });
  /* observe once the web fonts have set the hero: before that the name is shorter and a box under the fold reads as in view */
  const go = () => { if (node.isConnected) io.observe(node); };
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => setTimeout(go, 50)); else go();
}

/* "Every game this season": current.log.<hitting|pitching> {cols, rows, best} (careers.game_logs), newest first, the best
   game as tr.hl. Hitting: PA, AB, H, total bases, HR, BB, K, xwOBA; pitching: innings, batters faced, H, R, BB, K, HR,
   pitches. Empty (no section) when the file has no log. */
function logSection(cur, kind, L, S) {
  const pit = kind === 'pitcher';
  const lg = ((cur && cur.log) || {})[pit ? 'pitching' : 'hitting'];
  if (!lg || !Array.isArray(lg.cols) || !Array.isArray(lg.rows) || !lg.rows.length) return '';
  const ix = {}; lg.cols.forEach((c, i) => { ix[c] = i; });
  const g = (r, k) => (ix[k] === undefined ? null : r[ix[k]]);
  const n = x => (isNum(x) ? String(x) : '—');
  const ip = o => (isNum(o) ? Math.floor(o / 3) + '.' + (o % 3) : '—');
  const best = isNum(lg.best) ? lg.best : -1, bR = lg.rows[best];
  const post = { F: 'Wild Card', D: 'Division Series', L: 'LCS', W: 'World Series' };
  const head = pit ? [['Innings', 'Innings pitched (.1 = one out)'], ['BF', 'Batters faced'], ['H', 'Hits allowed'], ['R', 'Runs allowed'], ['BB', 'Walks'], ['K', 'Strikeouts'], ['HR', 'Home runs allowed'], ['Pitches', 'Pitches thrown']]
    : [['PA', 'Plate appearances'], ['AB', 'At-bats'], ['H', 'Hits'], ['TB', 'Total bases'], ['HR', 'Home runs'], ['BB', 'Walks'], ['K', 'Strikeouts'], ['xwOBA', 'What the contact deserved, this game (about .320 is average)']];
  const cells = r => (pit ? [ip(g(r, 'outs')), n(g(r, 'bf')), n(g(r, 'h')), n(g(r, 'r')), n(g(r, 'bb')), n(g(r, 'k')), n(g(r, 'hr')), n(g(r, 'np'))]
    : [n(g(r, 'pa')), n(g(r, 'ab')), n(g(r, 'h')), n(g(r, 'tb')), n(g(r, 'hr')), n(g(r, 'bb')), n(g(r, 'k')), isNum(g(r, 'xwoba')) ? BP.fmtAvg(g(r, 'xwoba')) : '—']);
  const opp = r => (g(r, 'home') ? 'v ' : '@ ') + String(g(r, 'opp') || '');
  const bestTxt = bR ? (pit ? ip(g(bR, 'outs')) + ' innings, ' + n(g(bR, 'k')) + ' strikeouts and ' + n(g(bR, 'r')) + ' run' + (g(bR, 'r') === 1 ? '' : 's') : n(g(bR, 'h')) + ' hit' + (g(bR, 'h') === 1 ? '' : 's') + ' and ' + n(g(bR, 'tb')) + ' total bases') +
    ' ' + (g(bR, 'home') ? 'against ' : 'at ') + esc(String(g(bR, 'opp') || '')) + ' on ' + esc(BP.fmtDate(g(bR, 'date'), { year: false })) + ' is the best game so far (highlighted).' : '';
  /* the latest 15 games and the best one; the rest behind "Every game" */
  const SHOW = 15, nAll = lg.rows.length;
  const rows = lg.rows.map((r, i) => [r, i]).reverse().map((x, k) => {
    const r = x[0], t = g(r, 't'), gpk = g(r, 'gpk');
    const d = esc(BP.fmtDate(g(r, 'date'), { year: false }));
    const cls = [x[1] === best ? 'hl' : '', k >= SHOW && x[1] !== best ? 'bp-logmore' : ''].filter(Boolean).join(' ');
    return '<tr' + (cls ? ' class="' + cls + '"' + (/bp-logmore/.test(cls) ? ' hidden' : '') : '') + '><td>' + (gpk ? '<a href="' + esc(BP.gameHref(gpk, L, S)) + '">' + d + '</a>' : d) + (t && t !== 'R' && post[t] ? ' <span class="qk-tag">' + esc(post[t]) + '</span>' : '') + '</td><td>' + esc(opp(r)) + '</td><td>' + esc(g(r, 'res') || '') + (pit && g(r, 'gs') ? ' · start' : '') + '</td>' +
      cells(r).map((v, j) => '<td class="num">' + (j === (pit ? 5 : 3) ? '<b>' + esc(v) + '</b>' : esc(v)) + '</td>').join('') + '</tr>';
  }).join('');
  return '<section class="qk-section">' + QK.sectionHead({ kicker: 'Game log', title: 'Every game this season', sub: bestTxt || 'Every game this season, newest first.', html: true }) +
    '<article class="qk-card"><div class="qk-card-body flush"><div class="qk-table-wrap"><table class="qk-table dense"><thead><tr><th>Date</th><th>Opp</th><th>Result</th>' +
    head.map(hd => '<th class="num" data-tip="' + esc(hd[1]) + '">' + esc(hd[0]) + '</th>').join('') + '</tr></thead><tbody>' + rows + '</tbody></table></div>' +
    (nAll > SHOW + 1 ? '<div class="qk-card-foot"><span>Newest first · the latest ' + SHOW + ' and the best game</span><button type="button" class="qk-btn bp-logall">All ' + nAll + ' games</button></div>' : '') +
    '</div></article></section>';
}

function render(el, params, state, route) {
  const pid = String(params.id || '');
  const L = params.level, S = params.season;
  const vq = (params.query || {}).view;
  const view = vq === 'detail' || vq === 'progression' ? vq : 'overview';
  if (view === 'progression' && BP.progression) return BP.progression.tab(el, params, route);   /* bp-progression.js (round 6) */
  const legacy = () => (LEG[route] ? LEG[route](el, params, state) : null);
  if (view === 'detail') {
    const box = document.createElement('div');
    el.innerHTML = '';
    el.appendChild(box);
    return Promise.resolve(LEG[route] ? LEG[route](box, params, state) : null).then(() => {
      if (!U.alive(el)) return;
      const back = document.createElement('div');
      back.innerHTML = '<nav class="qk-tabs bp-tabs2" aria-label="Player views"><a class="qk-tab" href="' + esc(BP.playerHref(pid, { level: L, role: route === 'player' ? null : route, season: S })) + '" aria-selected="false">Overview</a>' +
        '<a class="qk-tab" href="javascript:void(0)" aria-selected="true" aria-current="page">Detail: every metric, spray, zones, tunnels</a></nav>';
      el.insertBefore(back.firstChild, el.firstChild);
    });
  }
  el.innerHTML = QK.skeleton('card', 1) + QK.skeleton('chart', 1);
  return Promise.all([BP.load('players/' + pid + '.json'), U.gloss(), BP.loadYear('season.json', L, S)]).then(res => {
    if (!U.alive(el)) return null;
    const p = BP.ok(res[0]) ? res[0] : null, gl = res[1], season = BP.ok(res[2]) ? res[2] : null;
    const cur = (p && p.current) || {};
    if (!p || Number(cur.season) !== Number(S) || String(cur.level || 'mlb') !== String(L)) return legacy();
    const posU = String(p.pos || '').toUpperCase();
    let kind = route === 'pitcher' ? 'pitcher' : route === 'hitter' ? 'hitter' : ((posU === 'P' || posU === 'SP' || posU === 'RP') ? 'pitcher' : 'hitter');
    if (kind === 'pitcher' && !cur.pitching && cur.hitting) kind = 'hitter';
    if (kind === 'hitter' && !cur.hitting && cur.pitching) kind = 'pitcher';
    const blk = kind === 'pitcher' ? cur.pitching : cur.hitting;
    if (!blk || !blk.values) return legacy();
    const twoWay = !!(cur.hitting && cur.pitching);
    draw(el, { pid: pid, L: L, S: S, p: p, cur: cur, blk: blk, kind: kind, gl: gl, season: season, twoWay: twoWay, route: route });
    return null;
  });
}

function draw(el, c) {
  const { pid, L, S, p, cur, blk, kind, gl } = c;
  const v = blk.values || {}, pr = blk.pct_role || {};
  const pit = kind === 'pitcher';
  const tid = blk.team || (BP.player(pid) || {}).team;
  const setKey = U.setFor(kind, blk);
  const tg = teamGames(c.season, tid);
  const fl = U.floorOf(setKey, tg);
  const ok = U.meets(blk, setKey, tg);
  const peer = U.peerName(setKey);
  const peerShort = peer.replace(/^MLB /, '');
  const sur = BP.playerSurname(pid) || QK.surname(p.name);
  const n = blk.n || {};
  document.title = p.name + ' · ' + BP.SITE;
  const posName = pit ? (blk.role === 'RP' ? 'Relief pitcher' : 'Starting pitcher') : ({ C: 'Catcher', '1B': 'First base', '2B': 'Second base', '3B': 'Third base', SS: 'Shortstop', LF: 'Left field', CF: 'Centre field', RF: 'Right field', DH: 'Designated hitter', TWP: 'Two-way player' }[String(blk.pos || p.pos)] || blk.pos || p.pos);
  const a = isNum(blk.age) ? Math.floor(blk.age) : age(p.dob);
  const tags = [];
  if (ok) tags.push(QK.tag('Ranked against ' + peer, 'signal'));
  else if (fl) tags.push(QK.tag('Short of the ' + fl.value + ' ' + fl.unit + ' floor'));
  const pcs = (setKey === 'ALL' ? blk.pct : pr) || {};

  /* "The short version": what the numbers say, in plain English, from this season's percentiles */
  function shortVersion() {
    let t;
    if (pit) t = sur + ' has ' + (isNum(v.ip) ? 'thrown ' + BP.fmtIP(v.ip) + ' innings' : 'pitched') + (isNum(v.ra9) ? ' with ' + BP.num(v.ra9, 2) + ' runs allowed per nine' : '') + (isNum(v.k_pct) ? ' and a ' + BP.fmtVal(v.k_pct, 'pct') + ' strikeout rate' : '') + '.';
    else t = sur + ' has ' + (isNum(v.pa) ? v.pa + ' trips to the plate' : 'batted') + (isNum(v.avg) ? ', hitting ' + BP.fmtAvg(v.avg) + '/' + BP.fmtAvg(v.obp) + '/' + BP.fmtAvg(v.slg) : '') + (isNum(v.hr) ? ' with ' + v.hr + ' home run' + (v.hr === 1 ? '' : 's') : '') + '.';
    if (!ok) return t + ' Not enough of a sample yet to rank against ' + peerShort + '.';
    const rows = U.flat(setKey, 'head').map(x => x[0]).filter(k => isNum(pcs[k]) && isNum(v[k]) && U.metricOk(blk, k, setKey, tg)).map(k => [k, pcs[k], U.metaOf(kind, k, gl).label]);
    const top = rows.filter(r => r[1] >= 90).sort((x, y) => y[1] - x[1]).slice(0, 2);
    const low = rows.slice().sort((x, y) => x[1] - y[1])[0];
    if (top.length) t += ' In the top ' + Math.max(1, Math.round(100 - Math.min(top[0][1], top[top.length - 1][1]))) + '% of ' + peerShort + ' for ' + top.map(r => r[2]).join(' and ') + '.';
    else if (rows.length) { const avg = rows.reduce((x, r) => x + r[1], 0) / rows.length; t += avg >= 60 ? ' Above the middle of the pack among ' + peerShort + ' on most of the numbers that matter.' : avg >= 40 ? ' Around the middle of the pack among ' + peerShort + '.' : ' Below the middle of the pack among ' + peerShort + ' so far.'; }
    if (low && low[1] <= 30 && !(top[0] && top[0][0] === low[0])) t += ' The weak spot: ' + low[2] + ' sits in the ' + QK.ordinal(Math.round(low[1])) + ' percentile.';
    const samp = pit ? n.bf : n.pa;
    if (isNum(samp) && samp < 150) t += ' Early days, so read it lightly.';
    return t;
  }
  /* the hero is built after the five numbers below (its black strip) */
  const heroOf = strip => QK.playerHeader({ name: p.name, number: p.number, pos: posName, kicker: BP.levelName(L) + ' · ' + S + (pit ? (isNum(n.games) ? ' · ' + n.games + ' games' : '') : (isNum(v.pa) ? ' · ' + v.pa + ' PA' : '')),
    team: tid ? { name: BP.teamName(tid), abbr: BP.teamAbbr(tid), colour: U.raw(tid), alt: U.alt(tid), href: BP.teamHref(tid, L, S) } : null,
    meta: [isNum(a) ? a + ' years old' : null, 'Bats ' + (p.bats || '—') + ', throws ' + (p.throws || '—'), p.debut ? 'MLB debut ' + BP.fmtDate(p.debut, { year: true }) : null], tags: tags, strip: strip, short: shortVersion() });
  const role = c.route === 'player' ? null : c.route;
  const base = BP.playerHref(pid, { level: L, role: role, season: S });
  const tabs = [['overview', 'Overview', base], ['progression', 'Progression', base + (base.indexOf('?') >= 0 ? '&' : '?') + 'view=progression' + (c.twoWay ? '&kind=' + kind : '')], ['detail', 'Detail: every metric, spray, zones' + (pit ? ', tunnels' : ', bat tracking'), base + (base.indexOf('?') >= 0 ? '&' : '?') + 'view=detail']];
  let twoTabs = '';
  if (c.twoWay) twoTabs = '<div class="qk-seg" role="group" aria-label="Side" style="margin-left:auto"><a class="qk-btn' + (pit ? '' : ' primary') + '" href="' + esc(BP.playerHref(pid, { level: L, role: 'hitter', season: S })) + '">Hitting</a><a class="qk-btn' + (pit ? ' primary' : '') + '" href="' + esc(BP.playerHref(pid, { level: L, role: 'pitcher', season: S })) + '">Pitching</a></div>';

  /* v4: the black strip of five numbers under the hero, the plain one first, then ours, each with its percentile
     against the peers where there is one */
  const pc = k => (ok && isNum(pr[k]) ? pr[k] : null);
  const k = [];
  if (pit) {
    if (isNum(v.ip)) k.push({ label: 'Innings', value: BP.fmtIP(v.ip), sub: (isNum(v.ra9) ? BP.num(v.ra9, 2) + ' runs allowed per nine' : '') + (isNum(n.games) ? (isNum(v.ra9) ? ', ' : '') + n.games + ' games' : '') });
    if (isNum(v.war)) k.push({ label: 'Bullpen WAR', value: BP.num(v.war, 1), pctl: pc('war'), signal: true, sub: 'wins above a replacement-level arm', tip: 'Our wins above replacement for a pitcher, from the runs allowed (RA9) against a replacement-level arm' + (isNum(v.war_x) ? '; from xwOBA+ against it would be ' + BP.num(v.war_x, 1) : '') });
    if (isNum(v.stuff_plus)) k.push({ label: 'Stuff+', value: String(Math.round(v.stuff_plus)), pctl: pc('stuff_plus'), sub: 'the physics of the pitches · 100 = average', tip: 'Speed, movement, spin and release of every pitch, scored against the league: 100 is average, 110 excellent' + (isNum(v.pitching_plus) ? '. Pitching+ (location and count too): ' + Math.round(v.pitching_plus) : '') });
    if (isNum(v.xfip)) k.push({ label: 'xFIP', value: BP.num(v.xfip, 2), pctl: pc('xfip'), sub: 'runs a nine from what the pitcher controls', tip: 'Fielding-independent pitching with a league-average home-run rate: strikeouts, walks and fly balls only. RA9 ' + BP.num(v.ra9, 2) + ' · FIP ' + BP.num(v.fip, 2) });
    if (isNum(v.k_bb_pct)) k.push({ label: 'K-BB%', value: BP.fmtVal(v.k_bb_pct, 'pct'), pctl: pc('k_bb_pct'), sub: 'strikeouts minus walks per batter' });
    if (k.length < 5 && isNum(v.pitching_plus)) k.push({ label: 'Pitching+', value: String(Math.round(v.pitching_plus)), pctl: pc('pitching_plus'), sub: 'stuff, location and count · 100 = average' });
  } else {
    if (isNum(v.hr)) k.push({ label: 'Home runs', value: String(v.hr), sub: isNum(v.avg) ? BP.fmtAvg(v.avg) + ' / ' + BP.fmtAvg(v.obp) + ' / ' + BP.fmtAvg(v.slg) : '', tip: 'Batting average / on-base / slugging' });
    if (isNum(v.war)) k.push({ label: 'Bullpen WAR', value: BP.num(v.war, 1), pctl: pc('war_600'), signal: true, sub: isNum(v.war_600) ? BP.num(v.war_600, 1) + ' per 600 trips to the plate' : 'wins above replacement', tip: 'Our wins above replacement: batting, baserunning, fielding and position. The percentile is per 600 plate appearances.' });
    if (isNum(v.xwoba_n)) k.push({ label: 'xwOBA+', value: BP.fmtAvg(v.xwoba_n), pctl: pc('xwoba_n'), sub: 'what the contact deserved · .320 is average', tip: (U.MDESC.hitter.xwoba_n || [])[1] + (isNum(v.xwoba_savant) ? ' Savant’s xwOBA: ' + BP.fmtAvg(v.xwoba_savant) + '.' : '') });
    if (isNum(v.woba)) k.push({ label: 'wOBA', value: BP.fmtAvg(v.woba), pctl: pc('woba'), sub: 'what happened · OPS ' + BP.fmtAvg(v.ops) });
    if (isNum(v.barrel_pct)) k.push({ label: 'Barrel%', value: BP.fmtVal(v.barrel_pct, 'pct'), pctl: pc('barrel_pct'), sub: 'the best kind of contact · hard-hit ' + BP.fmtVal(v.hard_pct, 'pct') });
    if (k.length < 5 && isNum(v.bat_speed)) k.push({ label: 'Bat speed', value: BP.num(v.bat_speed, 1), unit: 'mph', pctl: pc('bat_speed'), sub: isNum(v.sprint_speed) ? 'sprint ' + BP.num(v.sprint_speed, 1) + ' ft/s' : '' });
  }
  const hero = heroOf(k.slice(0, 5));

  // the rail, with last season's ring (from the player file when written, else the catalogue on view)
  // current.hitting / current.pitching carry prev_pct_pos and prev_peer {level, season, group, pa | bf} (4b41ed54)
  const pf = blk.prev_pct_pos || blk.prev_pct_role || cur.prev_pct_pos || null, ppeer = blk.prev_peer || {};
  let prevPct = pf ? (pf.pct || pf.pct_role || pf) : null;
  if (prevPct && !Object.keys(prevPct).length) prevPct = null;
  let prevN = isNum(pit ? ppeer.bf : ppeer.pa) ? (pit ? ppeer.bf : ppeer.pa) : (pf && isNum(pf.n) ? pf.n : null);
  let which = 'head';
  const more = ok ? U.pctGroups(blk, kind, setKey, gl, 'more', tg) : [];
  const railHTML = () => QK.pctRail({ id: 'pp-pcard', kicker: 'How they stack up', title: which === 'more' ? 'More percentiles' : 'Percentiles: how the player ranks', peer: peer, sample: U.sampleLine(blk, kind, setKey, tg),
    groups: ok ? U.pctGroups(blk, kind, setKey, gl, which, tg, prevPct) : [], ringLabel: 'last season' + (isNum(prevN) ? ' (' + prevN + (pit ? ' batters faced' : ' PA') + ')' : ''),
    emptyTitle: 'Not ranked yet', emptyText: fl ? 'The player is short of the ' + fl.value + ' ' + fl.unit + ' floor for ' + peer + ' this season.' : 'No ranking this season.',
    foot: (more.length ? U.seg('pp-pset', 'Metric set', [['head', 'The core set'], ['more', 'More']], which) : '<span></span>') + '<a href="' + esc(BP.compareHref(pid)) + '">Compare →</a>' });
  // how sure: when the core numbers settle, at this sample
  const settle = [];
  const flat = U.flat(setKey, 'head');
  const at = id => { const x = flat.filter(y => y[0] === id)[0]; return x && isNum(x[1]) ? x : null; };
  (pit ? ['k_pct', 'xwoba_n', 'stuff_plus'] : ['k_pct', 'bb_pct', 'xwoba_n']).forEach(id => { const x = at(id); if (x) settle.push(U.metaOf(kind, id, gl).label + ' after about <b>' + QK.fmt.num(Math.round(x[1])) + ' ' + esc(U.UNIT[x[2]] || x[2]) + '</b>'); });
  const samp = pit ? n.bf : n.pa, unit = pit ? 'batters faced' : 'trips to the plate';
  const small = !isNum(samp) || samp < 300;
  /* v4: "How sure are we?" sits under the meters as the explain strip */
  const settleNote = '<b>How sure are we?</b> ' + esc(isNum(samp) ? (small ? (samp < 11 ? NUMW[samp] : QK.fmt.num(Math.round(samp))) + ' ' + unit + ' is a small sample.' : QK.fmt.num(Math.round(samp)) + ' ' + unit + ': the picture is settling.') : 'No games yet this season.') + ' ' +
    (pit ? 'Strikeouts and Stuff+ settle fast; runs allowed and results on balls in play take far longer, so lean on the first two early on. ' : 'Strikeouts and walks settle within weeks; batting average on balls in play takes seasons, which is why the meters lean on what the contact deserved. ') +
    (settle.length ? 'For ' + esc(peerShort) + ': ' + settle.join(', ').replace(/, ([^,]*)$/, ', and $1') + '. ' : '') + 'The ▼ on a meter marks last season, where there was one.';
  const roll = !pit && Array.isArray(cur.rolling) && cur.rolling.length > 5;
  const formCard = roll ? U.card2('Form through the season', 'Rolling xwOBA+ (what the contact deserved, blue) against wOBA (what happened)', U.chart('pp-roll', 240, 'Rolling xwOBA+ and wOBA')) : '';
  const simAll = (p.similar || []).filter(m => String(m.pid) !== pid);
  const seenS = {}, simU = simAll.filter(m => (seenS[m.pid] ? false : (seenS[m.pid] = 1))).slice(0, 4);
  const typeCard = simU.length ? '<article class="qk-card"><div class="qk-card-body"><div class="qk-kicker">Their type</div><h4 class="bp-h4">Plays most like</h4><ul class="bp-list bp-type">' +
    simU.map(m => '<li>' + U.playerEnt(m.pid, L, String(m.season) + (m.team ? ' · ' + BP.teamAbbr(m.team) : ''), kind) + '<a class="v bp-link" href="' + esc(BP.compareHref(pid, m.pid)) + '">Compare</a></li>').join('') + '</ul>' +
    '<div class="qk-aside" style="margin-top:10px">The nearest player-seasons since 2015 in the same ' + (pit ? 'role' : 'position') + ' group, on the spec’s weighted metrics.</div></div></article>' : '';

  const crumb = '<nav class="bp-crumb" aria-label="Breadcrumb"><a href="' + esc(BP.href(pit ? 'pitchers' : 'hitters', L, S)) + '">' + esc(BP.levelName(L)) + ' ' + (pit ? 'pitchers' : 'hitters') + '</a><span aria-hidden="true">›</span>' +
    (tid ? '<a href="' + esc(BP.teamHref(tid, L, S)) + '">' + esc(BP.teamName(tid)) + '</a><span aria-hidden="true">›</span>' : '') + esc(p.name) + '</nav>';
  /* v4: the hero carries the black strip; then the meters (7) beside the tale of the tape against the closest match (5) */
  const tapeOn = ok;
  let h = crumb + hero +
    '<div class="bp-flexrow">' + '<nav class="qk-tabs bp-tabs2" aria-label="Player views">' + tabs.map(t => '<a class="qk-tab" href="' + esc(t[2]) + '" aria-selected="' + (t[0] === 'overview') + '"' + (t[0] === 'overview' ? ' aria-current="page"' : '') + '>' + esc(t[1]) + '</a>').join('') + '</nav>' + twoTabs + '</div>' +
    '<section class="qk-section bp-sec1"><div class="qk-g75"><div><div id="pp-pwrap">' + railHTML() + '</div>' + QK.explain(settleNote, { cls: 'bp-settle' }) + '</div><div class="bp-stack">' +
    (tapeOn ? '<div id="pp-tape-h"></div><div class="qk-chips bp-pick" id="pp-tape-pick" role="group" aria-label="Compare with"></div><div id="pp-tape">' + QK.skeleton('lines', 6) + '</div><div id="pp-verd"></div>' : formCard + typeCard) + '</div></div></section>';
  if (pit) h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'The arsenal', title: 'What the player throws', sub: 'Every pitch type thrown ten times or more this season, in the same colours on every chart.' }) +
    '<div class="qk-grid"><div class="qk-span-6">' + U.card2('Pitch mix', 'Usage, speed, Stuff+ and whiffs; the heat cells are percentiles among pitches of the same type', '<div id="pp-mix"></div>') + '</div>' +
    '<div class="qk-span-6">' + U.card2('Movement', 'Average induced vertical break against horizontal break towards the arm side, in inches; size is usage', U.chart('pp-mov', 360, 'Pitch movement') + '<div class="bp-note" id="pp-mov-cap"></div>') + '</div></div></section>';
  // the club's next game (the scoreboard bug) and its last game (the line score and our win chance through it)
  const idx = BP.index() || {};
  const src = L === 'mlb' ? idx : BP.levelInfo(L);
  const isCur = Number(S) === Number(BP.currentSeason(L));
  const mine = x => x && (String(x.home) === String(tid) || String(x.away) === String(tid));
  const nxt = isCur ? [].concat(src.today || [], src.upcoming || []).filter(x => mine(x) && !BP.isFinal(x) && U.fresh(x)).sort((x, y) => String(x.start).localeCompare(String(y.start)))[0] : null;
  const lastG = isCur ? (src.recent || []).filter(x => mine(x) && BP.isFinal(x)).sort((x, y) => String(y.start).localeCompare(String(x.start)))[0] : null;
  if (nxt || lastG) {
    h += '<section class="qk-section"><div class="qk-g2">';
    if (nxt) {
      const g = BP.kitGame(nxt, L);
      g.league = L === 'aaa' ? 'Triple-A' : 'MLB';
      g.home.record = BP.RECORDS[String(nxt.home)] || ''; g.away.record = BP.RECORDS[String(nxt.away)] || '';
      /* how the clubs match up: our team ratings (season.json), as on the game page */
      const rows0 = BP.standingsRows ? BP.standingsRows(c.season || {}) : {};
      const ra = (rows0[String(nxt.away)] || {}).rating || {}, rh = (rows0[String(nxt.home)] || {}).rating || {};
      const fx = [];
      const add = (label, x1, x2, f, low) => { if (isNum(x1) && isNum(x2)) fx.push({ label: label, a: f(x1), b: f(x2), better: Math.abs(x1 - x2) < 1e-9 ? null : ((x1 > x2) !== !!low ? 'a' : 'b') }); };
      add('Team rating, runs a game', ra.net, rh.net, x => U.signed(x, 2));
      add('Offence, runs a game', ra.off, rh.off, x => U.signed(x, 2));
      add('Run prevention, runs a game', (ra.def || 0) + (ra.pitch || 0), (rh.def || 0) + (rh.pitch || 0), x => U.signed(x, 2));
      const prob = nxt.probables || {};
      const spTxt = !BP.isLive(nxt) && (prob.home || prob.away) ? 'Probable starters: ' + (prob.away ? BP.playerSurname(prob.away) : 'TBD') + ' v ' + (prob.home ? BP.playerSurname(prob.home) : 'TBD') + '.' : '';
      const occ = nxt.series ? BP.seriesText(nxt.series, true) : '';
      h += '<div>' + QK.sectionHead({ kicker: BP.isLive(nxt) ? 'Live now' : (QK.fmt.relDay(nxt.start || nxt.date) === 'Today' ? 'What to watch tonight' : 'Next up'), title: BP.teamShort(nxt.away) + ' at ' + BP.teamShort(nxt.home), sub: occ ? esc(occ) : '', html: true }) +
        QK.previewCard(g, { layout: 'bug', nick: t => t.short || t.name, factors: fx, factorsTitle: 'How they match up this season', noteExtra: esc(spTxt) }) + '</div>';
    }
    if (lastG) {
      const w = lastG.hs >= lastG.as ? [lastG.home, lastG.hs, lastG.away, lastG.as] : [lastG.away, lastG.as, lastG.home, lastG.hs];
      const ttl = isNum(lastG.hs) && isNum(lastG.as) ? BP.teamAbbr(w[0]) + ' ' + w[1] + ', ' + BP.teamAbbr(w[2]) + ' ' + w[3] : BP.teamShort(lastG.away) + ' at ' + BP.teamShort(lastG.home);
      h += '<div>' + QK.sectionHead({ kicker: 'Last game', title: ttl, sub: esc([BP.fmtDate(lastG.date, { year: false }), lastG.series ? BP.seriesText(lastG.series, true) : ''].filter(Boolean).join(' · ')), html: true,
        actions: '<a class="qk-more" href="' + esc(BP.gameHref(lastG.gpk, L, S)) + '">The game centre</a>' }) +
        '<article class="qk-card"><div class="qk-card-body"><div id="pp-box">' + BP.gameCard(lastG, { level: L, date: true }) + '</div><div id="pp-race"></div></div></article></div>';
    }
    h += '</div></section>';
  }
  /* the game log: every game this season (current.log, written by the build), newest first, the best one highlighted */
  h += logSection(cur, kind, L, S);
  /* game by game (the form through the season) and their type, when the tape took the side column */
  if (tapeOn && formCard && typeCard) h += '<section class="qk-section"><div class="qk-gside"><div>' + formCard + '</div><div>' + typeCard + '</div></div></section>';
  else if (tapeOn && (formCard || typeCard)) h += '<section class="qk-section">' + formCard + typeCard + '</section>';
  // ── more on the player
  h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'More on the player', title: 'Peers, projection and the long view', sub: 'Where the player sits among ' + esc(peerShort) + ', what we expect next season, the splits and every season in the data.' }) +
    U.card2('Among peers', 'Every ' + esc(peerShort) + ' past the floor this season; bars coloured by percentile', '<div id="pp-dist-m" style="margin-bottom:10px">' + U.seg('pp-dseg', 'Metric', DIST[kind], '') + '</div><div id="pp-dist">' +
      QK.empty('Pick a metric', 'The peer group loads on request (the season catalogue is several megabytes).') + '</div>');
  h += '<div class="qk-grid" style="margin-top:var(--sp-4)">';
  const pj = cur.projection;
  if (pj && pj.components) h += '<div class="qk-span-6">' + U.card2('Next season', 'Our ' + (pj.season || '') + ' projection with its 80% range (10th to 90th percentile)', '<div id="pp-proj"></div>', { flush: true }) + '</div>';
  const sp = (cur.splits || {})[pit ? 'pitcher' : 'batter'];
  if (sp) h += '<div class="qk-span-6">' + U.card2('Splits', 'This season' + (pit ? ', batters faced' : ''), '<div id="pp-splits"></div>', { flush: true }) + '</div>';
  h += '</div></section>';
  h += '<section class="qk-section" id="pp-mv"></section>';
  h += '<section class="qk-section">' + U.card2('Season by season', 'Every ' + (pit ? 'pitching' : 'hitting') + ' season in the data, all levels', '<div id="pp-career"></div>', { flush: true }) + '</section>';
  el.innerHTML = h;
  const logAll = el.querySelector('.bp-logall');
  if (logAll) logAll.addEventListener('click', () => { const t = logAll.closest('.qk-card'); t.querySelectorAll('tr.bp-logmore').forEach(r => { r.hidden = false; }); logAll.remove(); });

  // the rail's metric-set switch
  const repaint = () => { const w = el.querySelector('#pp-pwrap'); if (w) { w.innerHTML = railHTML(); wireSet(); } };
  const wireSet = () => {
    const seg = el.querySelector('#pp-pset');
    if (seg) QK.seg(seg, w => { which = w; repaint(); });
  };
  wireSet();
  // last season's ring: last season's catalogue, same peer group only, when the rail comes into view
  const catFile = pit ? 'pitchers.json' : 'hitters.json';
  const prevS = Number(S) - 1;
  if (ok && !prevPct && (p.seasons || []).some(s => s && s.kind === kind && Number(s.season) === prevS && String(s.level || 'mlb') === String(L))) {
    onView(el.querySelector('#pp-pwrap'), () => BP.loadYear(catFile, L, prevS).then(cat => {
      const row = BP.ok(cat) && cat.players ? cat.players[pid] : null;
      if (!row || !U.alive(el) || U.setFor(kind, row) !== setKey) return;
      const src2 = setKey === 'ALL' ? row.pct : row.pct_role;
      if (!src2 || !Object.keys(src2).length) return;
      prevPct = src2; prevN = pit ? (row.n || {}).bf : row.pa; repaint();
    }));
  }

  // the tale of the tape: the player against one of the three closest matches this season (chips switch)
  /* the season catalogue (4-7 MB) loads only once the tape is 160 px into the screen (at 1440 px it sits at the fold) */
  onView(el.querySelector('#pp-tape'), () => BP.loadYear(catFile, L, S).then(cat => {
    const box = el.querySelector('#pp-tape');
    if (!box || !U.alive(el)) return;
    const none = () => { el.querySelector('#pp-tape-h').innerHTML = QK.sectionHead({ kicker: 'Tale of the tape', title: 'Closest matches' }); box.innerHTML = QK.empty('No comparison yet', 'The closest matches appear once the season catalogue has them.'); };
    if (!BP.ok(cat) || !cat.players || !ok) { none(); return; }
    const P = cat.players, me = P[pid];
    if (!me) { none(); return; }
    const keys = U.flat(setKey, 'head').map(x => x[0]);
    const pcOf = r => (setKey === 'ALL' ? r.pct : r.pct_role) || {};
    const mp = pcOf(me);
    const want = {}; simAll.filter(m => Number(m.season) === Number(S)).forEach(m => { want[m.pid] = 1; });
    const cands = Object.keys(P).filter(id => id !== pid && P[id] && U.setFor(kind, P[id]) === setKey && U.meets(P[id], setKey, cat.team_games)).map(id => {
      const q = pcOf(P[id]); let d = 0, m = 0;
      keys.forEach(kk => { if (isNum(mp[kk]) && isNum(q[kk])) { d += (mp[kk] - q[kk]) * (mp[kk] - q[kk]); m++; } });
      return { id: id, d: m >= 4 ? Math.sqrt(d / m) - (want[id] ? 1000 : 0) : null };
    }).filter(x => isNum(x.d)).sort((x, y) => x.d - y.d).slice(0, 3);
    if (!cands.length) { none(); return; }
    const drawTape = oid => {
      const ids = [pid, oid];
      const E = ids.map(id => P[id]);
      const best = {};
      const groups = ((U.SETS[setKey] || {}).head || []).map(g => ({ label: g[0], rows: g[1].map(x => x[0]).filter(kk => U.metricOk(me, kk, setKey, cat.team_games)).map(kk => {
        const m = U.metaOf(kind, kk, gl), pcl = E.map(e => pcOf(e)[kk]);
        pcl.forEach((x, i) => { const o = pcl[1 - i]; const d = isNum(x) ? x - (isNum(o) ? o : 0) : null; if (isNum(d) && (!best[i] || d > best[i].d)) best[i] = { k: kk, d: d, v: (E[i].values || {})[kk], m: m }; });
        return { label: m.label, tip: m.tip, better: m.lower ? 'low' : 'high', values: E.map(e => (e.values || {})[kk]), pctls: pcl, fmt: z => U.fmtBy(m, z) };
      }) })).filter(g => g.rows.length);
      const names = ids.map(id => BP.playerSurname(id) || QK.surname((P[id] || {}).name || ''));
      el.querySelector('#pp-tape-h').innerHTML = QK.sectionHead({ kicker: 'Tale of the tape', title: names[0] + ' or ' + names[1] + '?',
        sub: 'Bar length = percentile against ' + esc(peer) + ' (100 = best). The better number in each row is solid.', html: true });
      const ents = E.map((e, i) => ({ name: e.name, short: names[i], href: BP.playerHref(ids[i], { level: L, role: kind }), colour: U.raw(e.team), alt: U.alt(e.team),
        sub: [BP.teamShort(e.team), pit ? (isNum((e.n || {}).bf) ? Math.round(e.n.bf) + ' batters faced' : '') : (isNum(e.pa) ? e.pa + ' PA' : '')].filter(Boolean).join(' · ') }));
      box.innerHTML = QK.compareView({ entities: ents, groups: groups });
      el.querySelector('#pp-verd').innerHTML = QK.verdicts(E.map((e, i) => (best[i] && best[i].d > 0 ? { title: ((U.ARCHETYPE || {})[kind] || {})[best[i].k] || 'The standout', who: names[i], text: 'the better of the two on ' + lc(best[i].m.label) + ' (' + U.fmtBy(best[i].m, best[i].v) + ').' } : null)));
      const lk = el.querySelector('#pp-tape-cmp');
      if (lk) lk.setAttribute('href', BP.compareHref(pid, oid));
    };
    const pick = el.querySelector('#pp-tape-pick');
    pick.innerHTML = cands.map((x, i) => '<button type="button" class="qk-chip" data-value="' + esc(x.id) + '" aria-pressed="' + (i === 0) + '">' + esc(BP.playerSurname(x.id) || QK.surname((P[x.id] || {}).name || '')) + '</button>').join('') +
      '<a class="qk-chip" id="pp-tape-cmp" href="' + esc(BP.compareHref(pid, cands[0].id)) + '">Open in Compare</a>';
    pick.querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
      pick.querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', x === b ? 'true' : 'false'));
      drawTape(b.getAttribute('data-value'));
    }));
    drawTape(cands[0].id);
  }), '0px 0px -160px 0px');

  // the last game: the line score by inning (runs, hits, errors) and our win chance through it (the game file)
  if (lastG && el.querySelector('#pp-race')) {
    BP.loadGame(lastG.gpk, L, S).then(d => {
      if (!BP.ok(d) || !U.alive(el)) return;
      const ls = Array.isArray(d.linescore) ? d.linescore : (d.linescore && d.linescore.innings) || [];
      if (ls.length) {
        const tot = d.linescore_totals || {};
        const n9 = Math.max(9, ls.length);
        const mine = String(tid);
        const row = (t, kx, runs) => '<tr' + (String(t) === mine ? ' class="hl"' : '') + '><td>' + BP.teamMark(t, 'sm') + '</td>' +
          Array.apply(null, Array(n9)).map((_, i) => '<td class="num">' + (ls[i] && isNum(ls[i][kx]) ? ls[i][kx] : (ls[i] ? 'x' : '')) + '</td>').join('') +
          '<td class="num"><b>' + (isNum(runs) ? runs : '–') + '</b></td>' + (tot.h ? '<td class="num">' + (isNum(tot.h[kx]) ? tot.h[kx] : '–') + '</td>' : '') + (tot.e ? '<td class="num">' + (isNum(tot.e[kx]) ? tot.e[kx] : '–') + '</td>' : '') + '</tr>';
        el.querySelector('#pp-box').innerHTML = '<div class="qk-table-wrap"><table class="qk-table dense bp-ls"><thead><tr><th>Club</th>' + Array.apply(null, Array(n9)).map((_, i) => '<th class="num">' + (i + 1) + '</th>').join('') +
          '<th class="num" data-tip="Runs">R</th>' + (tot.h ? '<th class="num" data-tip="Hits">H</th>' : '') + (tot.e ? '<th class="num" data-tip="Errors">E</th>' : '') + '</tr></thead><tbody>' + row(d.away, 0, d.as) + row(d.home, 1, d.hs) + '</tbody></table></div>';
      }
      /* wp.ours rows [play, inning, half (0 top, 1 bottom), our home win chance]: placed by inning and half */
      const wr = (((d.wp || {}).ours) || (Array.isArray(d.wp) ? d.wp : [])).filter(r => Array.isArray(r) && isNum(r[1]) && isNum(r[3]));
      if (wr.length > 4) {
        const cnt = {}, seen = {};
        wr.forEach(r => { const kk = r[1] + ':' + (r[2] ? 1 : 0); cnt[kk] = (cnt[kk] || 0) + 1; });
        const t = wr.map(r => { const kk = r[1] + ':' + (r[2] ? 1 : 0); const j = seen[kk] = (seen[kk] || 0) + 1; return (r[1] - 1) + (r[2] ? 0.5 : 0) + 0.5 * (j - 1) / cnt[kk]; });
        const innN = Math.max(9, Math.ceil(t[t.length - 1]));
        const per = []; for (let i = 1; i < innN; i++) per.push(i);
        const hc = U.pair(d.home, d.away);
        el.querySelector('#pp-race').innerHTML = U.chart('pp-race-c', 230, 'Our win chance through the last game');
        QKC.winProb('#pp-race-c', { t: t, p: wr.map(r => r[3]), step: true, tMin: 0, tMax: innN, interval: 1, periods: per,
          home: { name: BP.teamName(d.home), abbr: BP.teamAbbr(d.home), colour: hc[0] }, away: { name: BP.teamName(d.away), abbr: BP.teamAbbr(d.away), colour: hc[1] },
          tFmt: x => (x < innN ? String(Math.round(x) + 1) : ''), tLabel: x => (x % 1 >= 0.5 ? 'Bottom ' : 'Top ') + (Math.floor(x) + 1),
          tName: 'Inning', yName: BP.teamAbbr(d.home) + ' win chance (ours)' });
      }
    });
  }

  // where the player sits: the peer group loads on request
  let PEERS = null;   // <L>/<S>/peers.json once fetched (false: not built)
  const dseg = el.querySelector('#pp-dseg');
  QK.seg(dseg, key => {
    const box = el.querySelector('#pp-dist');
    box.innerHTML = QK.skeleton('chart', 1);
    const slim = peerValues(blk, cur, key);
    /* peers.json (the build's per-group sorted values) first, then the player file's peers, then the catalogue */
    const peerFile = kk => { const g = PEERS && PEERS.groups ? PEERS.groups[setKey] : null; return g && Array.isArray(g[kk]) ? g[kk] : null; };
    (slim ? Promise.resolve(null) : (PEERS !== null ? Promise.resolve(PEERS) : BP.loadYear('peers.json', L, S).then(x => { PEERS = BP.ok(x) && x.groups ? x : false; return PEERS; }))
      .then(() => (peerFile(key) ? null : BP.loadYear(catFile, L, S)))).then(cat => {
      if (!U.alive(el)) return;
      if (!slim && !peerFile(key) && (!BP.ok(cat) || !cat.players)) { box.innerHTML = QK.empty('Not available', 'The season catalogue did not load.'); return; }
      const m = U.metaOf(kind, key, gl);
      const vals = (slim || peerFile(key) || Object.keys(cat.players).map(id => cat.players[id]).filter(x => x && U.setFor(kind, x) === setKey && U.meets(x, setKey, cat.team_games)).map(x => (x.values || {})[key])).filter(isNum).sort((x, y) => x - y);
      if (vals.length < 5) { box.innerHTML = QK.empty('Too few peers yet', 'Fewer than five ' + peer + ' have reached the floor.'); return; }
      box.innerHTML = U.chart('pp-dist-c', 240, 'Distribution of ' + m.label);
      if (pit && cat && cat.league_types) drawMovement(el, Object.keys(cur.arsenal || {}).map(pt => Object.assign({ pt: pt }, cur.arsenal[pt])).filter(r => r.pt !== 'all' && isNum(r.usage) && (r.n || 0) >= MIX_MIN), cat.league_types);
      const mineV = v[key];
      const med = vals[Math.floor(vals.length / 2)];
      QKC.distribution('#pp-dist-c', { values: vals, binCount: 22, lowerBetter: m.lower, fmt: x => U.fmtBy(m, x).replace(' mph', ''), xName: m.label + ' · ' + vals.length + ' ' + peer,
        yName: 'Players', marks: (isNum(mineV) ? [{ x: mineV, label: sur }] : []).concat([{ x: med, label: 'Median' }]), label: 'Distribution of ' + m.label });
    });
  });

  if (pit) pitchMix(el, cur, v);
  else rollingChart(el, cur);
  if (pj && pj.components) projection(el, pj, pit);
  if (sp) splits(el, sp);
  career(el, p, kind, L);
  if (BP.moves) BP.moves.playerCard(el.querySelector('#pp-mv'), pid, L, S);   // bp-moves.js: who moves next
  BP.setMeta(p.updated_at ? 'Player file ' + esc(BP.fmtStamp(p.updated_at)) : '');
}

/* The peer group's values for one metric from the player file, when the builder writes them (current.peers or the
   block's peers: {metric: [values]} or {fields: [...], values: [[...]]}); null sends the page to the catalogue. */
function peerValues(blk, cur, key) {
  const P = (blk && blk.peers) || (cur && cur.peers) || null;
  if (!P) return null;
  if (Array.isArray(P[key])) return P[key];
  if (Array.isArray(P.fields) && Array.isArray(P.values)) { const i = P.fields.indexOf(key); return i >= 0 ? P.values.map(r => r[i]) : null; }
  return null;
}
const MIX_MIN = 10;
function pitchMix(el, cur, v) {
  const ars = Object.keys(cur.arsenal || {}).map(pt => Object.assign({ pt: pt }, cur.arsenal[pt])).filter(r => r.pt !== 'all' && isNum(r.usage) && (r.n || 0) >= MIX_MIN).sort((a, b) => b.usage - a.usage);
  const box = el.querySelector('#pp-mix');
  if (!ars.length) { box.innerHTML = QK.empty('No arsenal yet', 'The pitch mix appears after ten pitches of a type.'); }
  else {
    const cell = (val, p, f) => (isNum(val) ? (isNum(p) ? '<span class="qk-pcell" style="background:' + QK.pctColor(p) + ';color:' + QK.pctInk(p) + '" title="' + esc(QK.ordinal(p)) + ' percentile among this pitch type">' + f(val) + '</span>' : f(val)) : '—');
    box.innerHTML = '<div class="bp-mix" role="table" aria-label="Pitch mix"><div class="bp-mix-row h" role="row"><span>Pitch</span><span>Usage</span><span class="v">mph</span><span class="v">Stuff+</span><span class="v">Whiff%</span><span class="v">xwOBA</span></div>' +
      ars.map(r => '<div class="bp-mix-row" role="row" style="--k:' + esc(BP.pitchColour(r.pt)) + '"><span class="nm"><i aria-hidden="true"></i>' + esc(BP.pitchName(r.pt)) + '</span>' +
        '<span class="tr" title="' + esc(BP.fmtVal(r.usage, 'pct')) + ' of pitches"><b style="width:' + (100 * Math.min(1, r.usage)).toFixed(1) + '%"></b></span>' +
        '<span class="v">' + BP.fmtVal(r.usage, 'pct') + ' · ' + U.f(r.velo, 1) + '</span>' +
        '<span class="v">' + cell(r.stuff, r.stuff_pct, x => String(Math.round(x))) + '</span><span class="v">' + cell(r.whiff, r.whiff_pct_type, x => BP.fmtVal(x, 'pct')) + '</span>' +
        '<span class="v">' + (isNum(r.xwoba) ? BP.fmtAvg(r.xwoba) : '—') + '</span></div>').join('') + '</div>' +
      '<div class="bp-note">Ten or more of a type this season. Stuff+: 100 = league average for all pitches; heat cells rank against other pitchers throwing that type (100+ thrown).</div>';
  }
  drawMovement(el, ars, cur.league_types || (cur.pitching || {}).league_types || (BP.cached(BP.ypath('pitchers.json')) || {}).league_types || null);
}
/* Movement: his averages (pitch colours, size = usage); the league's average for each of his types (grey) once the season
   catalogue is in memory (it carries league_types; it loads with "Among peers" or the Detail view). */
function drawMovement(el, ars, lt) {
  const node = el.querySelector('#pp-mov');
  if (!node) return;
  const mine = ars.filter(r => isNum(r.hb) && isNum(r.ivb));
  if (!mine.length) { node.innerHTML = QK.empty('No movement data yet'); return; }
  const grey = QK.cssVar('--ink-3');
  const lg = lt ? mine.filter(r => lt[r.pt] && isNum(lt[r.pt].hb) && isNum(lt[r.pt].ivb)).map(r => ({ x: lt[r.pt].hb, y: lt[r.pt].ivb, name: 'League average ' + BP.pitchName(r.pt).toLowerCase(), label: 'lg ' + r.pt, color: grey, size: 9 })) : [];
  const pts = mine.map(r => ({ x: r.hb, y: r.ivb, name: BP.pitchName(r.pt) + ' · ' + BP.fmtVal(r.usage, 'pct') + ' · ' + U.f(r.velo, 1) + ' mph', label: r.pt, color: BP.pitchColour(r.pt), size: 10 + 34 * Math.sqrt(r.usage) }));
  QKC.scatter('#pp-mov', { points: lg.concat(pts), xName: 'Horizontal break, arm side + (in)', yName: 'Induced vertical break (in)', xFmt: x => U.f(x, 0), yFmt: x => U.f(x, 0), refX: 0, refY: 0, labelAll: true, label: 'Pitch movement' });
  const cap = el.querySelector('#pp-mov-cap');
  if (cap) cap.textContent = lg.length ? 'Grey: the league average for each pitch type thrown.' : 'Open "Among peers" to add the league average for each type.';
}

function rollingChart(el, cur) {
  const r = (cur.rolling || []).filter(x => Array.isArray(x) && isNum(x[1]));
  if (!el.querySelector('#pp-roll') || r.length < 6) return;
  const T = QKC.tokens();
  QKC.line('#pp-roll', { x: r.map(x => x[0]), xType: 'time', series: [{ name: 'xwOBA+', data: r.map(x => x[1]), color: T.model, width: 3 }, { name: 'wOBA', data: r.map(x => x[2]), color: T.cat[1] }],
    yFmt: x => BP.fmtAvg(x), yName: 'Rolling 100-PA rate (wOBA scale)', xName: 'Date', endLabels: true, label: 'Rolling xwOBA+ and wOBA' });
}

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const COMP = { K: ['Strikeout rate', 'pct'], BB: ['Walk rate', 'pct'], GB: ['Ground balls per ball in play', 'pct'], XWCON: ['xwOBA on contact', '3'], HRBIP: ['Home runs per ball in play', 'pct'], HITS: ['Hits per ball in play', '3'], XBH: ['Extra-base hits per hit', 'pct'] };
function projection(el, pj, pit) {
  const rows = Object.keys(COMP).filter(k => pj.components[k] && isNum(pj.components[k].proj)).map(k => {
    const c = pj.components[k], f = x => BP.fmtVal(x, COMP[k][1]);
    return '<li><span>' + esc(COMP[k][0] + (pit ? ' allowed' : '')) + '</span><span class="v">' + f(c.proj) + '</span><span class="s">' + (isNum(c.p10) ? f(c.p10) + '–' + f(c.p90) : '') + '</span></li>';
  });
  el.querySelector('#pp-proj').innerHTML = '<ul class="bp-list bp-proj">' + (isNum(pj.wOBA) ? '<li><span><b>wOBA' + (pit ? ' allowed' : '') + '</b></span><span class="v">' + BP.fmtAvg(pj.wOBA) + '</span><span class="s">ISO ' + BP.fmtAvg(pj.ISO) + ' · BABIP ' + BP.fmtAvg(pj.BABIP) + '</span></li>' : '') + rows.join('') + '</ul>' +
    '<div class="bp-note" style="padding:0 16px 12px">Regressed to the player\'s age and level with ' + BP.int(pj.n) + ' plate appearances of weight; the range is where the rate lands eight times out of ten.</div>';
}

function splits(el, sp) {
  const keys = [['vL', 'v left-handers'], ['vR', 'v right-handers'], ['home', 'Home'], ['away', 'Away']].filter(k => sp[k[0]]);
  const months = Object.keys(sp.months || {}).sort();
  const row = (lab, x) => '<tr><td>' + esc(lab) + '</td><td class="num">' + (isNum(x.pa) ? x.pa : '—') + '</td><td class="num">' + BP.fmtAvg(x.woba) + '</td><td class="num">' + BP.fmtVal(x.k_pct, 'pct') + '</td></tr>';
  el.querySelector('#pp-splits').innerHTML = '<div class="qk-table-wrap"><table class="qk-table dense"><thead><tr><th>Split</th><th class="num">PA</th><th class="num">wOBA</th><th class="num">K%</th></tr></thead><tbody>' +
    keys.map(k => row(k[1], sp[k[0]])).join('') + months.map(m => row(MONTHS[Number(m.slice(5, 7)) - 1] || m, sp.months[m])).join('') + '</tbody></table></div>';
}

function career(el, p, kind, L) {
  const pit = kind === 'pitcher';
  const rows = (p.seasons || []).filter(s => s && s.kind === kind);
  const box = el.querySelector('#pp-career');
  if (!rows.length) { box.innerHTML = QK.empty('No seasons on file'); return; }
  const cols = pit
    ? [['g', 'G', 'int'], ['gs', 'GS', 'int'], ['ip', 'IP', 'ip'], ['ra9', 'RA9', '2'], ['fip', 'FIP', '2'], ['k_pct', 'K%', 'pct'], ['bb_pct', 'BB%', 'pct'], ['csw_pct', 'CSW%', 'pct'], ['xwoba_plus', 'xwOBA+', '3'], ['fb_velo', 'FB mph', '1'], ['stuff_plus', 'Stuff+', 'plus'], ['pitching_plus', 'Pitching+', 'plus'], ['war', 'WAR', '1']]
    : [['g', 'G (with a PA)', 'int'], ['pa', 'PA', 'int'], ['hr', 'HR', 'int'], ['sb', 'SB', 'int'], ['avg', 'AVG', '3'], ['obp', 'OBP', '3'], ['slg', 'SLG', '3'], ['woba', 'wOBA', '3'], ['xwoba_plus', 'xwOBA+', '3'], ['k_pct', 'K%', 'pct'], ['bb_pct', 'BB%', 'pct'], ['barrel_pct', 'Barrel%', 'pct'], ['war', 'WAR', '1']];
  QK.table(box, { dense: true, sort: { key: 'season', dir: 'desc' }, columns: [
    { key: 'season', label: 'Season', sticky: true, year: true, fmt: (x, r) => '<b>' + esc(x) + '</b> <span class="qk-muted">' + esc(String(r.level || '').toUpperCase()) + '</span>' },
    { key: 'team', label: 'Club', fmt: (x, r) => (x ? BP.teamMark(x, 'sm') + ' ' + esc(BP.teamAbbr(x)) : '—') }]
    .concat(cols.filter(cc => rows.some(r => isNum(r[cc[0]]))).map(cc => ({ key: cc[0], label: cc[1], num: true, fmt: x => BP.fmtVal(x, cc[2]) }))),
    rows: rows.map(r => Object.assign({}, r)) });
}

['hitter', 'pitcher', 'player'].forEach(r => BP.route(r, (el, params, state) => render(el, params, state, r)));
})(window.BP);
