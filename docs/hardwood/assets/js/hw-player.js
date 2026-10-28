/* The Quant Hardwood — the player page (#/<L>/player/<pid>), on kit v4 "Broadcast" (the Rink player page is the
 * reference, MIGRATION_V4.md).
 *
 * Top, as the concept: a crumb; the full-bleed team-colour hero (QK.playerHeader: the alternate colour on a diagonal,
 * the outlined number or initials, the name in Bebas, chips) with the black strip of five numbers (points, rebounds,
 * assists, total impact and WAR, percentiles against the role) and "The short version"; the LED percentile meters
 * against the role (guards, wings or bigs, qualified players, the sample named, metrics short of their reliability
 * sample dashed, a ▼ for last season from current.prev_pct_pos, else last season's catalogue) from the one metric set
 * (HW.ui.MSET), with "How sure are we?" under them, beside the tale of the tape against the closest match (chips
 * switch between the matches; a link opens all three in Compare) and one-line verdicts; what to watch tonight (the
 * scoreboard bug and how the teams match up, QK.previewCard layout 'bug') beside the last game (the line score by
 * quarter and the win-chance race from the game file); the game log (every game, the best night highlighted); game
 * by game and "Their type". Below, "More on the player": value tiles, among peers in the role's distribution,
 * season by season, splits, movement, the shot chart on the half court, value, the career table and awards.
 * Detail tab (?tab=detail): the pre-redesign player page in full (the whole catalogue, radar, on/off, clutch,
 * projection, lineups, game log table).
 * Data: <L>/players/<pid>.json (career; role_card and prev-season percentiles when the builder writes them),
 * <L>/<S>/players.json (catalogue), value.json (roles, WAR), valuation.json; last season's players.json and
 * value.json load only when the rail scrolls into view and the career file has no last-season percentiles. */
(function (HW) {
'use strict';

const U = HW.ui, esc = HW.esc, isNum = HW.isNum;
const GC = () => HW.gameCentre;
function splits(log) {
  const agg = list => {
    const n = list.length; if (!n) return null;
    const s = k => list.reduce((a, r) => a + (isNum(r[k]) ? Number(r[k]) : 0), 0);
    const tsa = s('fga') + 0.44 * s('fta');
    return { n: n, min: s('min') / n, pts: s('pts') / n, reb: s('reb') / n, ast: s('ast') / n, ts: tsa > 0 ? s('pts') / (2 * tsa) : null, pm: s('pm') / n, gs: s('game_score') / n };
  };
  const win = r => (isNum(r.pm) ? r.pm > 0 : null);
  return [['Season', log], ['Home', log.filter(r => r.home)], ['Away', log.filter(r => !r.home)], ['Team won', log.filter(r => win(r) === true)], ['Team lost', log.filter(r => win(r) === false)], ['Last 10', log.slice(-10)]]
    .map(x => Object.assign({ split: x[0] }, agg(x[1]) || {})).filter(x => x.n);
}

/* A one-player catalogue from the career file's role_card and season row (no season catalogue download). */
function rcCatalogue(career, rc, pid, S) {
  const row = ((career && career.seasons) || []).find(x => Number(x.season) === Number(S)) || {};
  const d = career.dob ? Date.parse(career.dob) : NaN;
  const p = { name: career.name, team: row.team, pos: career.pos, age: isFinite(d) ? (Date.now() - d) / (365.25 * 864e5) : null, gp: row.gp, min: row.min,
    qualified: !!rc.qualified, role: rc.role, pct_role: rc.pct_role,
    values: { hpm: row.hpm, hpm_o: row.o, hpm_d: row.d, ts: row.ts, pts_g: row.pts, reb_g: row.reb, ast_g: row.ast, rapm: row.rapm, box_impact: row.box_impact } };
  /* round 9: every meter row needs its value, not only the nine above: the season row's deep set (`dv`, aligned to
     prog.keys[kind], the progression fields every career file carries) fills the rest */
  const pk = (career.prog && career.prog.keys) || {};
  const ids = pk.player || pk[Object.keys(pk)[0]] || [];
  (row.dv || []).forEach((x, i) => { const k = ids[i]; if (k && isNum(x) && !isNum(p.values[k])) p.values[k] = x; });
  const players = {}; players[pid] = p;
  return { ok: true, players: players, min_floor: rc.min_floor, metrics: [], __rc: rc };
}

/* Last season's percentiles in the same peer group, when the career file carries them (02157d80: current.prev_pct_pos
   {key: 0-100} beside current.prev_peer {season, role (this season's role), label, gp, qualified}; role_card.prev_pct_role
   is read too): { pct: {key: percentile}, gp, role } or null. Without it the page loads last season's catalogue. */
function prevFromFile(career) {
  const c = (career && career.current) || {}, rc = (career && career.role_card) || {};
  const pc = c.prev_pct_pos || c.prev_pct_role || rc.prev_pct_role || rc.prev_pct_pos;
  if (!pc || typeof pc !== 'object') return null;
  const m = pc.pct || pc.pct_role || pc;
  if (!Object.keys(m).length) return null;
  const peer = (c.prev_pct_pos || c.prev_pct_role ? c.prev_peer : rc.prev_peer) || {};
  return { pct: m, gp: isNum(peer.gp) ? peer.gp : (isNum(pc.gp) ? pc.gp : null), role: peer.role || pc.role || null };
}

function render(el, params) {
  const L = U.L(params), pid = String(params.id || '');
  const tab = U.tab(params, ['overview', 'detail', 'progression'], 'overview');
  let S = U.S(params);
  const curS = HW.currentSeason(L);
  el.innerHTML = QK.skeleton('lines', 6);
  return HW.load(L + '/players/' + pid + '.json').then(career => {
    if (!U.alive(el)) return null;
    const seasons = ((career && career.seasons) || []).map(x => x.season);
    // a season the player did not play: show the latest one before it (the header says so)
    let asked = null;
    if (seasons.length && seasons.indexOf(S) < 0) { const prev = seasons.filter(x => x <= S).sort((a, b) => b - a)[0] || Math.max.apply(null, seasons); if (prev !== S) { asked = S; S = prev; } }
    // the career file's role_card (players/<pid>.json) carries the role percentiles: then the 3.8 MB season catalogue
    // is not needed (it loads only if the reader asks for the peer distribution); otherwise the page computes them
    const rc = career && career.role_card && Number(career.role_card.season) === Number(S) && career.role_card.pct_role ? career.role_card : null;
    return Promise.all([rc ? Promise.resolve(rcCatalogue(career, rc, pid, S)) : HW.load(HW.path('players.json', L, S)), HW.load(HW.path('value.json', L, S)), HW.load(HW.path('valuation.json', L, curS)), U.movement(L)]).then(a => {
      if (!U.alive(el)) return;
      draw(el, L, S, pid, career, U.ok(a[0]) ? a[0] : null, U.ok(a[1]) ? a[1] : null, U.ok(a[2]) ? a[2] : null, asked, tab, params, a[3]);
    });
  });
}

function lc(x) { return /^[A-Z][a-z]/.test(x) ? x.charAt(0).toLowerCase() + x.slice(1) : x; }
const NUMW = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten'];

function draw(el, L, S, pid, career, cat, sv, val, asked, tab, params, mv) {
  const P = (cat && cat.players) || {};
  const p = P[pid] || null;
  const roles = {};
  U.rowsOf(sv).forEach(r => { if (r.role) roles[String(r.id)] = r.role; });
  const cs = ((career && career.seasons) || []).slice().sort((a, b) => a.season - b.season);
  const srow = cs.find(x => x.season === S) || {};
  const cur = career && career.current && (!career.current.season || career.current.season === S) ? career.current : {};
  const vrow = U.rowsOf(val).find(x => String(x.id) === pid) || null;
  const swar = U.rowsOf(sv).find(x => String(x.id) === pid) || null;
  const name = (p && p.name) || (career && career.name) || (vrow && vrow.name) || HW.playerName(L, pid);
  const sur = QK.surname(name);
  const team = (vrow && vrow.team) || (p && p.team) || srow.team || null;
  const col = team ? U.tcol(L, team) : QK.cssVar('--signal');
  const v = (p && p.values) || {};
  const pos = (p && p.pos) || (career && career.pos) || (vrow && vrow.pos) || '';
  const role = U.roleOf(p, pid, roles) || (swar && swar.role) || null;
  const age = p && isNum(p.age) ? Math.floor(p.age) : vrow && isNum(vrow.age) ? Math.floor(vrow.age) : null;
  const gpNow = p && isNum(p.gp) ? p.gp : (isNum(srow.gp) ? srow.gp : 0);
  const mpg = p && gpNow ? (p.min || 0) / gpNow : (isNum(srow.min) && gpNow ? srow.min / gpNow : null);
  const set = role && U.MSET ? U.MSET.roles[role] : null;
  const peerShort = role ? (U.ROLE_NAME || {})[role] || 'players' : 'players';
  document.title = name + ' · ' + HW.leagueName(L) + ' · The Quant Hardwood';
  const tags = [];
  if (p && p.qualified) tags.push(QK.tag('Qualified for percentiles', 'signal'));
  else if (p) tags.push(QK.tag('Short of the minutes floor'));
  if (vrow && vrow.inj) tags.push('<span class="qk-tag hw-inj">' + esc(vrow.inj) + '</span>');
  if (asked) tags.push(QK.tag('No ' + HW.seasonLabel(L, asked) + ' games yet: showing ' + HW.seasonLabel(L, S)));
  const log = (cur.log || []).slice().sort((a, b) => String(a.date).localeCompare(String(b.date)));

  /* this season's role percentiles (for the short version, the tiles and the verdicts) */
  const headKeys = set ? set.groups.reduce((acc, g) => acc.concat(g[1]), []) : [];
  const pcs = {};
  if (p) headKeys.forEach(k => { const x = U.rolePctl(cat, roles, pid, k); if (isNum(x)) pcs[k] = x; });
  function shortVersion() {
    if (!gpNow) return null;
    const ppg = isNum(v.pts_g) ? v.pts_g : srow.pts, rpg = isNum(v.reb_g) ? v.reb_g : srow.reb, apg = isNum(v.ast_g) ? v.ast_g : srow.ast;
    let t = sur + (U.isCur(L, S) ? ' is averaging ' : ' averaged ') + (isNum(ppg) ? U.f(ppg, 1) + ' points' : '') + (isNum(rpg) ? ', ' + U.f(rpg, 1) + ' rebounds' : '') + (isNum(apg) ? ' and ' + U.f(apg, 1) + ' assists' : '') + ' in ' + gpNow + ' game' + (gpNow === 1 ? '' : 's') + '.';
    const rows = Object.keys(pcs).map(k => [k, pcs[k], U.mMeta(k).label.replace(/ \(HPM\)$/, '')]);
    const top = rows.filter(r => r[1] >= 90).sort((x, y) => y[1] - x[1]).slice(0, 2);
    const low = rows.slice().sort((x, y) => x[1] - y[1])[0];
    if (top.length) t += ' In the top ' + Math.max(1, Math.round(100 - Math.min(top[0][1], top[top.length - 1][1]))) + '% of ' + peerShort + ' for ' + top.map(r => lc(r[2])).join(' and ') + '.';
    else if (rows.length) { const avg = rows.reduce((x, r) => x + r[1], 0) / rows.length; t += avg >= 60 ? ' Above the middle of the pack among ' + peerShort + ' on most of the numbers that matter.' : avg >= 40 ? ' Around the middle of the pack among ' + peerShort + '.' : ' Below the middle of the pack among ' + peerShort + ' so far.'; }
    if (low && low[1] <= 30 && !(top[0] && top[0][0] === low[0])) t += ' The weak spot: ' + lc(low[2]) + ' sits in the ' + QK.ordinal(Math.round(low[1])) + ' percentile.';
    if (gpNow < 15) t += ' Early days, so read it lightly.';
    return t;
  }
  const crumb = '<nav class="hw-crumb" aria-label="Breadcrumb"><a href="' + esc(HW.href(L, 'players', S)) + '">' + esc(HW.leagueName(L)) + '</a><span aria-hidden="true">›</span>' +
    (team ? '<a href="' + esc(HW.teamHref(L, team, S)) + '">' + esc(HW.teamName(L, team)) + '</a><span aria-hidden="true">›</span>' : '') + esc(name) + '</nav>';
  /* v4 (Broadcast): the black strip of five numbers under the hero, each with its percentile against the role where
     there is one: the box-score three, then ours (total impact and wins above replacement) */
  const hpm = isNum(v.hpm) ? v.hpm : srow.hpm;
  const ppg = isNum(v.pts_g) ? v.pts_g : srow.pts, rpg = isNum(v.reb_g) ? v.reb_g : srow.reb, apg = isNum(v.ast_g) ? v.ast_g : srow.ast;
  const strip = [
    { label: 'Points', value: isNum(ppg) ? U.f(ppg, 1) : '—', sub: gpNow ? 'a game, in ' + gpNow + ' game' + (gpNow === 1 ? '' : 's') : 'a game' },
    { label: 'Rebounds', value: isNum(rpg) ? U.f(rpg, 1) : '—', sub: 'a game' },
    { label: 'Assists', value: isNum(apg) ? U.f(apg, 1) : '—', sub: 'a game' },
    { label: 'Total impact', value: isNum(hpm) ? U.signed(hpm, 1) : '—', signal: true, pctl: isNum(pcs.hpm) ? pcs.hpm : null, sub: 'points per 100 trips over an average player',
      tip: 'Hardwood Plus-Minus (HPM): points per 100 possessions the player adds to the team’s margin over an average player (play-by-play on/off blended with the box score). Offence ' + U.signed(isNum(v.hpm_o) ? v.hpm_o : srow.o, 1) + ', defence ' + U.signed(isNum(v.hpm_d) ? v.hpm_d : srow.d, 1) + '.' },
    swar && isNum(swar.war) ? { label: 'Wins above replacement', value: U.f(swar.war, 1), pctl: isNum(swar.pct_role) ? swar.pct_role : null, sub: 'this season, from impact and minutes', tip: 'Our wins above a replacement-level player this season, from HPM and minutes' }
      : { label: 'Minutes', value: isNum(mpg) ? U.f(mpg, 1) : '—', sub: 'a game' }];
  let h = crumb + QK.playerHeader({ name: name, number: career && /^\d{1,2}$/.test(String(career.number || '')) ? career.number : null, pos: role ? (U.ROLE1 || {})[role] || role : pos, kicker: HW.leagueName(L) + ' · ' + HW.seasonLabel(L, S) + (gpNow ? ' · ' + gpNow + ' game' + (gpNow === 1 ? '' : 's') : ''),
    team: team ? { name: HW.teamName(L, team), abbr: HW.teamAbbr(L, team), colour: HW.teamColourRaw(L, team), alt: HW.teamAlt(L, team), href: HW.teamHref(L, team, S) } : { name: 'Free agent' },
    meta: [age !== null ? age + ' years old' : null, pos ? 'Listed ' + pos : null, p ? Number(Math.round(p.min || 0)).toLocaleString('en-GB') + ' minutes' : null], tags: tags, strip: strip, short: shortVersion() });
  // value tiles (below the fold: "More on the player")
  const k = [];
  if (vrow) k.push({ label: 'Projected WAR', value: U.f(vrow.w0, 1), signal: true, sub: 'rest of ' + HW.seasonLabel(L, HW.currentSeason(L)) + (isNum(vrow.p10) ? ' · four seasons ' + U.f(vrow.v, 1) + ' (likely range ' + U.f(vrow.p10, 1) + ' to ' + U.f(vrow.p90, 1) + ')' : ''), tip: 'Our projection of the player’s wins above replacement; the four-season value is discounted, with its 80% range' });
  if (isNum(v.pts100)) k.push({ label: 'Points per 100', value: U.f(v.pts100, 1), pctl: p ? U.rolePctl(cat, roles, pid, 'pts100') : null, sub: 'possessions · true shooting ' + HW.fmtVal(v.ts, 'pct'), tip: 'Points scored per 100 possessions the player is on the floor for; true shooting counts threes and free throws' });
  const aw = cur.awards || {};
  const best = Object.keys(aw).filter(x => isNum(aw[x]) || (aw[x] && isNum(aw[x].p))).sort((a, b) => (isNum(aw[b]) ? aw[b] : aw[b].p) - (isNum(aw[a]) ? aw[a] : aw[a].p))[0];
  if (best) k.push({ label: 'Our ' + (best === 'mvp' ? 'MVP' : best.toUpperCase()) + ' chance', value: U.pct(isNum(aw[best]) ? aw[best] : aw[best].p), sub: 'from the award model' });
  const base = HW.playerHref(L, pid, S);
  h += '<div style="margin-top:var(--sp-6)">' + U.tabsHTML([{ key: 'overview', label: 'Overview', href: base }, { key: 'progression', label: 'Progression', href: base + (base.indexOf('?') >= 0 ? '&' : '?') + 'tab=progression' }, { key: 'detail', label: 'Detail: the whole catalogue, on/off and lineups', href: base + (base.indexOf('?') >= 0 ? '&' : '?') + 'tab=detail' }], tab) + '</div>';
  if (tab === 'detail') { el.innerHTML = h + '<div class="hw-sub"></div>'; U.legacy('player', el.querySelector('.hw-sub'), params, null, { embed: 'detail' }); return; }
  if (tab === 'progression') { el.innerHTML = h + '<div class="hw-sub"></div>'; if (HW.progression) HW.progression.tab(el.querySelector('.hw-sub'), L, career); return; }

  // ── the rail (with last season's ring), how sure, game by game, their type
  const peer = role ? U.peerName(L, role) : '';
  const style = set ? set.style.filter(x => isNum(v[x])) : [];
  const fileP = prevFromFile(career);
  let prevPct = fileP && (!fileP.role || fileP.role === role) ? fileP.pct : null, prevGp = fileP ? fileP.gp : null;
  const railHTML = () => QK.pctRail({ id: 'pp-pcard', kicker: 'How they stack up', title: 'Percentiles: how the player ranks', peer: peer,
    sample: p ? U.sampleLine(L, cat, p) + (cat && cat.__rc && isNum(cat.__rc.n) ? ' · ' + cat.__rc.n + ' qualified ' + (U.ROLE_NAME[role] || 'peers') : '') : '',
    groups: p ? U.pctGroups(L, cat, roles, pid, { prev: prevPct, more: false }) : [], ringLabel: 'last season' + (isNum(prevGp) ? ' (' + prevGp + ' games)' : ''),
    note: style.length ? 'Style, not better or worse: ' + style.map(x => U.mMeta(x).label + ' ' + U.fmtM(x, v[x])).join(' · ') + '.' : '',
    emptyText: p ? 'No role yet for this player: percentiles appear once the player has a role in the value table.' : 'No numbers for this season yet.' });
  const m50 = role ? (((U.MSET.m50 || {})[L] || {})[role] || {}) : {};
  const games = key => (isNum(m50[key]) && isNum(mpg) && mpg > 0 ? Math.round(m50[key] / mpg) : null);
  const settle = [];
  if (isNum(games('pts100'))) settle.push('scoring per 100 trips settles after about <b>' + games('pts100') + ' games</b>');
  if (isNum(games('ast_pct'))) settle.push('assist rate after about <b>' + games('ast_pct') + '</b>');
  if (isNum(games('hpm'))) settle.push('total impact after about <b>' + games('hpm') + '</b>');
  const small = gpNow < 30;
  const sampleWords = gpNow ? (small ? (gpNow < 11 ? NUMW[gpNow] : gpNow) + ' game' + (gpNow === 1 ? ' is' : 's is') + ' a small sample.' : gpNow + ' games: the picture is settling.') : 'No games yet this season.';
  /* v4: "How sure are we?" sits under the meters as the explain strip */
  const settleNote = '<b>How sure are we?</b> ' + esc(sampleWords) + ' ' + (small && gpNow ? 'Shooting numbers swing a lot early on. ' : '') +
    (settle.length && isNum(mpg) ? 'At ' + U.f(mpg, 1) + ' minutes a game, ' + settle.join(', ').replace(/, ([^,]*)$/, ', and $1') + '. ' : '') +
    (prevPct ? 'The ▼ marks last season: rows that sit on it are the steady part of the profile; the ones far from it are the ones to watch.' : 'The ▼ on a meter marks last season, where there was one.');
  const gbg = log.length ? U.card2('Game by game', 'Game score each game (Hollinger’s one-number box score); cyan when the team won the player’s minutes, red-orange when it lost them', U.chart('pp-log', 240, 'Game score per game')) : '';
  const simR = (career && Array.isArray(career.similar_role) && career.similar_role.length) ? career.similar_role.filter(x => Number(x.season) === Number(S)).map(x => ({ id: String(x.id), name: x.name, d: x.distance }))
    : (p && p.qualified ? U.similarRole(L, cat, roles, pid, 5) : []);
  const typeCard = simR.length ? '<article class="qk-card"><div class="qk-card-body"><div class="qk-kicker">Their type</div><h4 class="hw-h4">Plays most like</h4><ul class="hw-list hw-type">' +
    simR.slice(0, 3).map(x => '<li>' + U.playerEnt(L, x.id, x.name || HW.playerName(L, x.id), (P[x.id] || {}).team, null, S) + '<a class="v hw-link" href="' + esc(HW.href(L, 'compare/players/' + encodeURIComponent(pid) + '/' + encodeURIComponent(x.id), S)) + '">Compare</a></li>').join('') + '</ul>' +
    '<div class="qk-aside" style="margin-top:10px">Closest match among ' + esc(peerShort) + ' on this season’s profile, each metric weighted by how stable it is.</div></div></article>' : '';
  /* 1. the meters (7) beside the tale of the tape against the closest match (5), as the concept */
  const tapeOn = !!(simR.length && p && set);
  h += '<section class="qk-section hw-sec1"><div class="qk-g75"><div>' + railHTML() + QK.explain(settleNote, { cls: 'hw-settle' }) + '</div>' +
    '<div class="hw-stack2">' + (tapeOn ? '<div id="pp-tape-h"></div><div class="qk-chips hw-pick" id="pp-tape-pick" role="group" aria-label="Compare with"></div><div id="pp-tape">' + QK.skeleton('lines', 6) + '</div><div id="pp-verd"></div>'
      : gbg + typeCard) + '</div></div></section>';
  /* 2. what to watch tonight (the scoreboard bug and the match-up) beside the last game (line score, win-chance race) */
  const info = HW.leagueInfo(L) || {};
  const nxt = U.isCur(L, S) && team ? (info.today || []).concat(info.next_games || []).filter(g => (String(g.home) === String(team) || String(g.away) === String(team)) && HW.gameState(g) !== 'post' && U.fresh(g)).sort((x, y) => String(x.date).localeCompare(String(y.date)))[0] : null;
  const lastG = log.length ? log[log.length - 1] : null;
  if (nxt || lastG) {
    h += '<section class="qk-section"><div class="qk-g2">';
    if (nxt) {
      const st0 = U.status(nxt);
      h += '<div>' + QK.sectionHead({ kicker: st0 === 'live' ? 'Live now' : (QK.fmt.relDay(nxt.date) === 'Today' ? 'What to watch tonight' : 'Next up'), title: U.nick(L, nxt.away) + ' at ' + U.nick(L, nxt.home) }) +
        '<div id="pp-next">' + QK.skeleton('card', 1) + '</div></div>';
    }
    if (lastG) {
      const line = (lastG.pts || 0) + ' points, ' + (lastG.reb || 0) + ' rebounds, ' + (lastG.ast || 0) + ' assists in ' + U.f(lastG.min, 0) + ' minutes' + (isNum(lastG.game_score) ? ', game score ' + U.f(lastG.game_score, 1) : '') + (isNum(lastG.pm) ? ', ' + U.signed(lastG.pm, 0) + ' on the floor' : '');
      const href = lastG.game ? HW.gameHref(L, lastG.game, S) : null;
      h += '<div>' + QK.sectionHead({ kicker: 'Last game', title: '<span id="pp-last-t">' + esc((lastG.home ? 'v ' : 'at ') + HW.teamName(L, lastG.opp)) + '</span>', html: true, sub: esc(HW.fmtDate(lastG.date, { year: false })),
        actions: href ? '<a class="qk-more" href="' + esc(href) + '">The game centre</a>' : '' }) +
        '<article class="qk-card"><div class="qk-card-body"><div id="pp-box"></div>' +
        '<p class="hw-lastline"><b>' + esc(sur) + ':</b> ' + esc(line) + '.</p><div id="pp-race"></div></div></article></div>';
    }
    h += '</div></section>';
  }
  /* 3. the game log: every game this season, the best night (game score) highlighted */
  if (log.length) {
    let bi = -1, bv = -1e9; log.forEach((r, i) => { if (isNum(r.game_score) && r.game_score >= bv) { bv = r.game_score; bi = i; } });
    const bR = log[bi];
    const shot = (m, a) => (isNum(m) && isNum(a) ? m + '–' + a : '—');
    h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Game log', title: U.isCur(L, S) ? 'Every game this season' : 'Every game of ' + HW.seasonLabel(L, S),
      sub: bR ? esc((bR.pts || 0) + ' points ' + (bR.home ? 'against ' : 'at ') + HW.teamName(L, bR.opp) + ' is the best night so far (game score ' + U.f(bR.game_score, 1) + ', highlighted). Game score is Hollinger’s one-number box score: 10 is a solid night, 20 a big one.') : '', html: true }) +
      '<article class="qk-card"><div class="qk-card-body flush"><div class="qk-table-wrap hw-logwrap"><table class="qk-table hw-gamelog"><thead><tr><th>Date</th><th>Opp</th><th class="num">Min</th><th class="num">Pts</th><th class="num">Reb</th><th class="num">Ast</th><th class="num" data-tip="Field goals made–attempted">FG</th><th class="num" data-tip="Threes made–attempted">3P</th><th class="num" data-tip="Free throws made–attempted">FT</th><th class="num" data-tip="The team’s points margin with the player on the floor">+/-</th><th class="num" data-tip="Hollinger’s game score: one number for the box-score line">Game score</th></tr></thead><tbody>' +
      log.map((r, i) => [r, i]).reverse().map(x => { const r = x[0];
        return '<tr' + (x[1] === bi ? ' class="hl"' : '') + '><td>' + (r.game ? '<a class="hw-link" href="' + esc(HW.gameHref(L, r.game, S)) + '">' + esc(HW.fmtDate(r.date, { year: false })) + '</a>' : esc(HW.fmtDate(r.date, { year: false }))) + '</td><td>' + (r.home ? 'v ' : '@ ') + esc(HW.teamAbbr(L, r.opp)) + '</td>' +
          '<td class="num">' + U.f(r.min, 0) + '</td><td class="num"><b>' + (r.pts || 0) + '</b></td><td class="num">' + (r.reb || 0) + '</td><td class="num">' + (r.ast || 0) + '</td><td class="num">' + shot(r.fgm, r.fga) + '</td><td class="num">' + shot(r.tpm, r.tpa) + '</td><td class="num">' + shot(r.ftm, r.fta) + '</td>' +
          '<td class="num">' + U.sgnHTML(r.pm, 0) + '</td><td class="num">' + U.f(r.game_score, 1) + '</td></tr>'; }).join('') +
      '</tbody></table></div></div></article></section>';
  }
  /* 4. game by game and their type */
  if (tapeOn && (gbg || typeCard)) h += '<section class="qk-section"><div class="qk-gside"><div>' + gbg + '</div><div>' + typeCard + '</div></div></section>';

  // ── more on the player
  const cells = cur.shots && cur.shots.grid ? U.rowsOf(cur.shots.grid).filter(c => isNum(c.x) && isNum(c.y) && c.y <= 41.5) : [];
  const groupsAll = p ? U.pctGroups(L, cat, roles, pid) : [];
  h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'More on the player', title: 'Value, peers and the long view', sub: 'What the player is worth, where the player sits among ' + esc(peerShort) + ', how the season splits, and every season in the data.' }) +
    (k.length ? '<div class="hw-kpis">' + QK.stats(k) + '</div>' : '') +
    '<div class="qk-grid" style="margin-top:var(--sp-5)">' + (groupsAll.length ? '<div class="qk-span-6">' + U.card2('Among peers', 'Every qualified ' + esc(peer.replace(HW.leagueName(L) + ' ', '')) + ' this season; bars coloured by percentile', '<div class="qk-seg" id="pp-dist-m" role="group" aria-label="Metric" style="margin-bottom:10px"></div>' + U.chart('pp-dist', 240, 'Among peers: the role’s distribution')) + '</div>' : '') +
    (cs.length > 1 ? '<div class="qk-span-' + (groupsAll.length ? 6 : 12) + '">' + U.card2('Season by season', 'Impact per 100 possessions: total, offence and defence', U.chart('pp-career', 280, 'Impact by season')) + '</div>' : '') + '</div>';
  if (log.length) h += '<div class="qk-grid hw-sec"><div class="qk-span-12">' + U.card2('Splits', 'Per game', '<div id="pp-splits"></div>', { flush: true }) + '</div></div>';
  h += '</section>';
  // Who moves next: only where the block passed its held-out test (published); never a placeholder
  const mr = mv && mv.pub.next ? mv.by[pid] : null;
  if (mr && isNum(mr.p_next)) {
    const m = mv.m;
    h += '<div class="qk-grid hw-sec"><div class="qk-span-12">' + U.card2('Movement', 'Our chance the player has left the team ' + esc(U.mvHorizon(mv)) + ', and how. No contract data is used (Model page).',
      '<div class="hw-mvcard">' + QK.stats([{ label: 'Chance of moving', value: U.pctMv(mr.p_next), signal: true, sub: U.mvHorizon(mv), tip: (m.notes || [])[0] || '' },
        mv.pub.deadline && isNum(mr.p_dl) ? { label: 'Before the deadline', value: U.pctMv(mr.p_dl), sub: (m.deadline_label || 'traded or claimed') + ' by ' + HW.fmtDate(String((m.horizons || {}).deadline || ''), { weekday: false }) } : null]) +
      '<div style="margin-top:12px">' + U.mvBar(mv, mr) + '</div><div style="margin-top:8px">' + U.mvKeys(mv) + '</div>' +
      '<div class="hw-mvctx">' + esc([isNum(mr.age) && !/\bage\b/.test(mr.why || '') ? 'Age ' + Math.floor(mr.age) : '', isNum(mr.yrs) && !/seasons in the league/.test(mr.why || '') ? mr.yrs + ' seasons in the league' : '', isNum(mr.value) ? U.f(mr.value, 1) + ' WAR (last two seasons, 3:2)' : '', mr.why || ''].filter(Boolean).join(' · ')) + '</div>' +
      QK.note('<b>' + U.pctMv(mr.p_next) + '</b> means about ' + Math.max(1, Math.round(mr.p_next * 10)) + ' in 10 players in this position have left by then.') + '</div>') + '</div></div>';
  }
  if (cells.length || vrow) {
    h += '<div class="qk-grid hw-sec">';
    if (cells.length) h += '<div class="qk-span-' + (vrow ? 6 : 12) + '">' + U.card2('Shot chart', 'Size is volume; colour is points per shot against the league from the same spot', '<div id="pp-shots" class="hw-court-max"></div>') + '</div>';
    if (vrow) h += '<div class="qk-span-' + (cells.length ? 6 : 12) + '">' + U.card2('Value', 'Projected WAR by season (mean path; ageing and survival included). Four-season value ' + U.f(vrow.v, 1) + ' (likely range ' + U.f(vrow.p10, 1) + ' to ' + U.f(vrow.p90, 1) + ')',
      U.chart('pp-val', 260, 'Projected WAR by season') + QK.note('WAR is wins above a replacement-level player: <b>' + U.f(vrow.w0, 1) + '</b> means the team should win about ' + Math.max(0, Math.round(vrow.w0)) + ' more games with this player than with a fringe signing.'), { foot: '<span></span>' + U.link(HW.href(L, 'value'), 'Value & Moves') }) + '</div>';
    h += '</div>';
  }
  h += '<section class="qk-section">' + U.head({ kicker: 'History', title: 'Career', sub: 'Box scores from 1997, play-by-play numbers (RAPM, WPA) from about 2017.' }) + '<div class="qk-card"><div id="pp-ctab"></div></div></section>';
  const awards = (career && career.career_awards) || [];
  if (awards.length) h += '<div class="qk-grid hw-sec"><div class="qk-span-12">' + U.card2('Awards', '', '<div class="hw-pills">' + awards.slice().sort((a, b) => b[0] - a[0]).map(x => QK.tag(HW.seasonLabel(L, x[0]) + ' ' + (String(x[1]).length <= 5 ? String(x[1]).toUpperCase() : x[1]), 'signal')).join('') + '</div>') + '</div></div>';
  if (!p && !cs.length) h += U.empty('No numbers', 'This player has no games in the data yet.');
  el.innerHTML = h;

  // last season's ring: from the career file, else last season's catalogue when the rail scrolls into view
  const prevS = HW.seasons(L).filter(x => x < S).sort((a, b) => b - a)[0];
  const repaint = () => { const old = el.querySelector('#pp-pcard'); if (old) old.outerHTML = railHTML(); };
  if (p && role && !prevPct && prevS && cs.some(x => x.season === prevS) && el.querySelector('#pp-pcard')) {
    let fired = false;
    const go = () => {
      if (fired) return; fired = true;
      Promise.all([HW.load(HW.path('players.json', L, prevS)), U.roles(L, prevS)]).then(r => {
        const pc = U.ok(r[0]) ? r[0] : null, rl = r[1] || {};
        const pp = pc && pc.players ? pc.players[pid] : null;
        if (!pp || !pp.qualified || !U.alive(el) || U.roleOf(pp, pid, rl) !== role) return;
        const out = {};
        headKeys.concat(set.more).forEach(kk => { const x = U.rolePctl(pc, rl, pid, kk); if (isNum(x)) out[kk] = x; });
        if (!Object.keys(out).length) return;
        prevPct = out; prevGp = pp.gp; repaint();
      });
    };
    const host = el.querySelector('#pp-pcard');
    if (window.IntersectionObserver) { const io = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) { io.disconnect(); go(); } }, { rootMargin: '200px' }); io.observe(host); } else go();
  }

  // the tale of the tape: the player against one of the closest matches (chips switch), on the role's headline set
  const withFull = cb => (cat && !cat.__rc ? cb(cat) : HW.load(HW.path('players.json', L, S)).then(full => { if (U.ok(full) && full.players) cb(full); else cb(null); }));
  if (el.querySelector('#pp-tape')) {
    const box = el.querySelector('#pp-tape');
    const fill = () => withFull(full => {
      if (!U.alive(el)) return;
      const others = full ? simR.map(x => x.id).filter(id => id !== pid && full.players[id]).slice(0, 3) : [];
      if (!others.length || !full.players[pid]) { el.querySelector('#pp-tape-h').innerHTML = QK.sectionHead({ kicker: 'Tale of the tape', title: 'Closest matches' }); box.innerHTML = QK.empty('No comparison yet', 'The closest matches appear once the season catalogue has them.'); return; }
      const drawTape = oid => {
        const ids = [pid, oid], E = ids.map(id => full.players[id]);
        const best = {};
        const groups = set.groups.map(g => ({ label: g[0], rows: g[1].map(kk => {
          const m = U.mMeta(kk), pcl = ids.map(id => U.rolePctl(full, roles, id, kk));
          pcl.forEach((x, i) => { const o = pcl[1 - i]; const d = isNum(x) ? x - (isNum(o) ? o : 0) : null; if (isNum(d) && (!best[i] || d > best[i].d)) best[i] = { k: kk, d: d, v: (E[i].values || {})[kk] }; });
          return { label: m.label, tip: m.desc, better: m.better, values: E.map(e => (e.values || {})[kk]), pctls: pcl, fmt: x => U.fmtM(kk, x) };
        }) }));
        const names = E.map(e => QK.surname(e.name || ''));
        el.querySelector('#pp-tape-h').innerHTML = QK.sectionHead({ kicker: 'Tale of the tape', title: names[0] + ' or ' + names[1] + '?',
          sub: 'Bar length = percentile against ' + esc(peer) + ' (100 = best). The better number in each row is solid.', html: true });
        const ents = E.map((e, i) => ({ name: e.name, short: names[i], href: HW.playerHref(L, ids[i], S), colour: HW.teamColourRaw(L, e.team), alt: HW.teamAlt(L, e.team), sub: [HW.teamName(L, e.team), (e.gp || 0) + ' games'].join(' · ') }));
        box.innerHTML = QK.compareView({ entities: ents, groups: groups });
        el.querySelector('#pp-verd').innerHTML = QK.verdicts(E.map((e, i) => (best[i] && best[i].d > 0 ? { title: U.ARCHETYPE[best[i].k] || 'The standout', who: names[i], text: 'the better of the two on ' + lc(U.mMeta(best[i].k).label) + ' (' + U.fmtM(best[i].k, best[i].v) + ').' } : null)));
      };
      const pick = el.querySelector('#pp-tape-pick');
      pick.innerHTML = others.map((id, i) => '<button type="button" class="qk-chip" data-value="' + esc(id) + '" aria-pressed="' + (i === 0) + '">' + esc(QK.surname(full.players[id].name || '')) + '</button>').join('') +
        '<a class="qk-chip" href="' + esc(HW.href(L, 'compare/players/' + [pid].concat(others.slice(0, 2)).map(encodeURIComponent).join('/'), S)) + '">' + (others.length > 1 ? 'All three in Compare' : 'Open in Compare') + '</a>';
      pick.querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
        pick.querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', x === b ? 'true' : 'false'));
        drawTape(b.getAttribute('data-value'));
      }));
      drawTape(others[0]);
    });
    if ((cat && !cat.__rc) || !window.IntersectionObserver) fill();
    /* the season catalogue (about 4 MB) loads only once the tape is 160 px into the screen (at 1440 px it sits just under the fold) */
    else {
      const io = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) { io.disconnect(); fill(); } }, { rootMargin: '0px 0px -160px 0px', threshold: 0.01 });
      /* observe once the web fonts have set the hero (before that a box under the fold reads as in view) */
      const go = () => { if (box.isConnected) io.observe(box); };
      if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => setTimeout(go, 50)); else go();
    }
  }

  // what to watch tonight: the scoreboard bug, the bar and how the teams match up this season (season.json ratings)
  if (nxt && el.querySelector('#pp-next')) {
    HW.load(HW.path('season.json', L, S)).then(sn => {
      const box = el.querySelector('#pp-next');
      if (!box || !U.alive(box)) return;
      const season = U.ok(sn) ? sn : null;
      const g = U.game(nxt, L, { records: U.records(season) });
      const R = (season && season.ratings) || {}, ra = R[String(nxt.away)] || {}, rh = R[String(nxt.home)] || {};
      const fx = [];
      const add = (label, a, b, f, low) => { if (isNum(a) && isNum(b)) fx.push({ label: label, a: f(a), b: f(b), better: Math.abs(a - b) < 1e-9 ? null : ((a > b) !== !!low ? 'a' : 'b') }); };
      add('Net rating, per 100 trips', ra.net, rh.net, x => U.signed(x, 1));
      add('Points scored per 100', ra.off, rh.off, x => U.f(x, 1));
      add('Points allowed per 100', ra.def, rh.def, x => U.f(x, 1), true);
      const m = nxt.model || {};
      const extra = U.status(nxt) === 'pre' && isNum(m.margin) ? 'We expect ' + HW.teamAbbr(L, m.margin >= 0 ? nxt.home : nxt.away) + ' by about ' + Math.max(1, Math.round(Math.abs(m.margin))) + (isNum(m.total) ? ', with about ' + Math.round(m.total) + ' points in all' : '') + '.' : '';
      box.innerHTML = QK.previewCard(g, { layout: 'bug', nick: t => t.short || t.name, factors: fx, factorsTitle: 'How they match up this season', noteExtra: esc(extra), market: 'quiet' });
    });
  }

  // the last game: the line score by quarter and our win chance through it (the game file)
  if (lastG && lastG.game && el.querySelector('#pp-box')) {
    GC().loadGame(L, S, lastG.game).then(res => {
      if (!res || !U.ok(res.d) || !U.alive(el)) return;
      const d = res.d, H = String(d.home), A = String(d.away), mine = lastG.home ? H : A;
      if (isNum(d.hs) && isNum(d.as) && U.status(d) === 'final') {
        const w = d.hs >= d.as ? [H, d.hs, A, d.as] : [A, d.as, H, d.hs];
        const t = el.querySelector('#pp-last-t');
        if (t) t.textContent = HW.teamAbbr(L, w[0]) + ' ' + w[1] + ', ' + HW.teamAbbr(L, w[2]) + ' ' + w[3] + (Number(d.periods) > 4 ? ' (OT)' : '');
      }
      const ln = d.line || {}, la = ln.away || [], lh = ln.home || [];
      if (la.length && lh.length) {
        const n = Math.max(la.length, lh.length);
        const ql = i => (i < 4 ? 'Q' + (i + 1) : (n > 5 ? 'OT' + (i - 3) : 'OT'));
        const sum = a => a.reduce((s, x) => s + (isNum(x) ? x : 0), 0);
        const row = (tid, a) => '<tr' + (tid === mine ? ' class="hl"' : '') + '><td>' + QK.teamMark(U.team(L, tid), 'sm') + '</td>' + a.map(x => '<td class="num">' + (isNum(x) ? x : '–') + '</td>').join('') + '<td class="num"><b>' + sum(a) + '</b></td></tr>';
        el.querySelector('#pp-box').innerHTML = '<div class="qk-table-wrap"><table class="qk-table dense"><thead><tr><th>Team</th>' + la.map((_, i) => '<th class="num">' + ql(i) + '</th>').join('') + '<th class="num">Total</th></tr></thead><tbody>' + row(A, la) + row(H, lh) + '</tbody></table></div>';
      }
      const wp = ((d.wp || {}).model || []).filter(x => isNum(x[0]) && isNum(x[1]));
      if (wp.length > 4) {
        const PS = L === 'wnba' ? 600 : 720, tMax = Math.max(wp[wp.length - 1][0], 4 * PS);
        const per = []; for (let t = PS; t < tMax; t += t < 4 * PS ? PS : 300) per.push(t);
        const hc = U.pair(L, H, A);
        el.querySelector('#pp-race').innerHTML = U.chart('pp-race-c', 240, 'Our win chance through the last game');
        QKC.winProb('#pp-race-c', { t: wp.map(x => x[0]), p: wp.map(x => x[1]), step: true, tMin: 0, tMax: tMax, interval: PS, periods: per,
          home: { name: HW.teamName(L, H), abbr: HW.teamAbbr(L, H), colour: hc[0] }, away: { name: HW.teamName(L, A), abbr: HW.teamAbbr(L, A), colour: hc[1] },
          tFmt: x => (x < 4 * PS ? 'Q' + (Math.round(x / PS) + 1) : ''), tLabel: x => (x < 4 * PS ? 'Q' + (Math.floor(x / PS) + 1) : 'OT') + ' · ' + Math.floor((x % PS) / 60) + ' min in',
          tName: 'Game time (quarters)', yName: HW.teamAbbr(L, H) + ' win chance (ours)' });
      }
    });
  }

  // where the player sits: the peer distribution of one metric of the role's set, with the player and the median marked
  if (document.getElementById('pp-dist') && cat && cat.__rc) {
    const holder = document.getElementById('pp-dist');
    document.getElementById('pp-dist-m').hidden = true;
    holder.style.setProperty('--h', 'auto');
    holder.innerHTML = '<div class="hw-flex" style="padding:24px 0"><button type="button" class="qk-btn" id="pp-dist-go">Show the distribution</button><span class="hw-quiet">loads every player of the season (about 4 MB)</span></div>';
    document.getElementById('pp-dist-go').addEventListener('click', () => {
      holder.innerHTML = QK.skeleton('chart', 1);
      HW.load(HW.path('players.json', L, S)).then(full => {
        if (!U.alive(holder) || !U.ok(full)) return;
        holder.style.setProperty('--h', '240px'); holder.innerHTML = '';
        document.getElementById('pp-dist-m').hidden = false;
        drawAmong(full);
      });
    });
  } else if (document.getElementById('pp-dist')) drawAmong(cat);
  function drawAmong(cat2) {
    if (!document.getElementById('pp-dist')) return;
    const pv = ((cat2.players || {})[pid] || {}).values || v;
    const peers = U.rolePeers(cat2, roles, role);
    const opts = set.groups.reduce((a, g) => a.concat(g[1]), []).filter(x => isNum(pv[x])).slice(0, 6);
    const segEl = document.getElementById('pp-dist-m');
    segEl.innerHTML = opts.map((o, i) => '<button type="button" aria-pressed="' + (i === 0) + '" data-value="' + o + '">' + esc(U.mMeta(o).label.replace(/ \(HPM\)$/, '')) + '</button>').join('');
    const drawDist = key => {
      const m = U.mMeta(key);
      const vals = peers.map(x => (x.values || {})[key]).filter(isNum).sort((a, b) => a - b);
      if (vals.length < 5) { document.getElementById('pp-dist').innerHTML = QK.empty('Too few qualified peers yet'); return; }
      const med = vals[Math.floor(vals.length / 2)];
      QKC.distribution('#pp-dist', { values: vals, binCount: 22, lowerBetter: m.better === 'low', fmt: x => U.fmtM(key, x), xName: m.label + ' · ' + vals.length + ' qualified ' + U.ROLE_NAME[role], yName: 'Players',
        marks: (isNum(pv[key]) ? [{ x: pv[key], label: sur }] : []).concat([{ x: med, label: 'Median' }]), label: 'Distribution of ' + m.label });
    };
    if (opts.length) { drawDist(opts[0]); QK.seg(segEl, drawDist); }
  }
  if (document.getElementById('pp-career')) {
    QKC.line('#pp-career', { x: cs.map(x => HW.seasonLabel(L, x.season)), series: [
      { name: 'Total', data: cs.map(x => (isNum(x.hpm) ? Math.round(x.hpm * 10) / 10 : null)), color: QKC.tokens().model, width: 3 },
      { name: 'Offence', data: cs.map(x => (isNum(x.o) ? Math.round(x.o * 10) / 10 : null)), color: QKC.tokens().cat[1], dash: true },
      { name: 'Defence', data: cs.map(x => (isNum(x.d) ? Math.round(x.d * 10) / 10 : null)), color: QKC.tokens().cat[2], dash: true }], yFmt: v2 => U.signed(v2, 1), ref: { y: 0 }, xName: 'Season', yName: 'Impact (points per 100 possessions)', label: 'Impact by season' });
  }
  if (log.length) {
    let bi = -1, bv = -1e9; log.forEach((r, i) => { if (isNum(r.game_score) && r.game_score > bv) { bv = r.game_score; bi = i; } });
    QKC.mount('#pp-log', T => {
      const xa = QKC.axis(T, { type: 'category', data: log.map(r => HW.fmtDate(r.date, { year: false, weekday: false }) + '\n' + (r.home ? 'v ' : '@ ') + HW.teamAbbr(L, r.opp)), split: false, line: true });
      xa.axisLabel.interval = log.length > 12 ? 'auto' : 0; xa.axisLabel.lineHeight = 14; xa.axisLabel.fontSize = log.length > 8 ? 10 : 11.5;
      const ya = QKC.axis(T, {});
      const gB = 26 + QKC.nameAxis(xa, 'Game (date and opponent)', 'bottom'), gT = 26 + QKC.nameAxis(ya, 'Game score', 'side');
      xa.nameGap = 40;
      return {
        grid: { left: 8, right: 12, top: gT, bottom: gB, containLabel: true }, xAxis: xa, yAxis: ya,
        tooltip: QKC.tooltip(T, { trigger: 'axis', axisPointer: { type: 'shadow', shadowStyle: { color: 'rgba(125,147,255,.10)' } }, formatter: ps => { const r = log[ps[0].dataIndex];
          return '<div style="font-weight:600">' + esc(HW.fmtDate(r.date, { year: false }) + ' ' + (r.home ? 'v ' : '@ ') + HW.teamAbbr(L, r.opp)) + '</div>' + QKC.tipRow(ps[0].color, 'Game score', U.f(r.game_score, 1)) +
            QKC.tipRow(T.ink3, 'Line', (r.pts || 0) + ' pts · ' + (r.reb || 0) + ' reb · ' + (r.ast || 0) + ' ast') + QKC.tipRow(T.ink3, '+/-', U.signed(r.pm, 0)); } }),
        series: [{ type: 'bar', barMaxWidth: 26, data: log.map((r, i) => {
          const o = { value: isNum(r.game_score) ? Math.round(r.game_score * 10) / 10 : 0, href: r.game ? HW.gameHref(L, r.game, S) : undefined,
            itemStyle: { color: r.pm > 0 ? T.sky : r.pm < 0 ? T.coral : T.ink3 } };
          if (i === bi && bv >= 20) o.label = Object.assign(QKC.annot(T), { show: true, position: 'top', formatter: 'best: ' + U.f(bv, 1) });
          return o; }) }]
      };
    }, { label: 'Game score per game' });
    QK.table(document.getElementById('pp-splits'), { dense: true, rows: splits(log), columns: [{ key: 'split', label: 'Split', sort: false }, { key: 'n', label: 'G', num: true }, { key: 'min', label: 'Min', num: true, fmt: x => U.f(x, 1) },
      { key: 'pts', label: 'Pts', num: true, fmt: x => U.f(x, 1) }, { key: 'reb', label: 'Reb', num: true, fmt: x => U.f(x, 1) }, { key: 'ast', label: 'Ast', num: true, fmt: x => U.f(x, 1) }, { key: 'ts', label: 'TS%', num: true, fmt: x => HW.fmtVal(x, 'pct') }, { key: 'pm', label: '+/-', num: true, fmt: x => U.sgnHTML(x, 1) }] });
  }
  if (cells.length) HW.charts.cellChart('pp-shots', L, cells, { size: 1.55 });
  if (vrow) {
    const slots = val && Array.isArray(val.slots) && val.slots.length === 4 ? val.slots.map(x => String(x).replace(/^rest of /, 'Rest of ')) : ['Rest of season', '+1', '+2', '+3'];
    QKC.bar('#pp-val', { cats: slots, series: [{ name: 'WAR', data: [vrow.w0, vrow.w1, vrow.w2, vrow.w3].map(x => (isNum(x) ? Math.round(x * 10) / 10 : 0)) }], labels: true, fmt: x => U.f(x, 1), colors: [col, col, col, col], valName: 'Projected WAR', catName: 'Season',
      max: x => (x.max > 0 ? Math.ceil(x.max * 12) / 10 : 0) });
  }
  const ct = document.getElementById('pp-ctab');
  if (cs.length) {
    QK.table(ct, { dense: true, sort: { key: 'season', dir: 'desc' }, rows: cs, columns: [
      { key: 'season', label: 'Season', num: true, fmt: x => '<a class="hw-link" href="' + esc(HW.playerHref(L, pid, x)) + '">' + esc(HW.seasonLabel(L, x)) + '</a>' },
      { key: 'team', label: 'Team', fmt: x => U.teamEnt(L, x, { abbr: true }) }, { key: 'gp', label: 'GP', num: true }, { key: 'min', label: 'Min', num: true, fmt: x => U.f(x, 0) },
      { key: 'pts', label: 'Pts', num: true, fmt: x => U.f(x, 1) }, { key: 'reb', label: 'Reb', num: true, fmt: x => U.f(x, 1) }, { key: 'ast', label: 'Ast', num: true, fmt: x => U.f(x, 1) },
      { key: 'ts', label: 'TS%', num: true, fmt: x => HW.fmtVal(x, 'pct') }, { key: 'hpm', label: 'HPM', num: true, fmt: x => '<b>' + U.signed(x, 1) + '</b>' },
      { key: 'rapm', label: 'RAPM', num: true, fmt: x => U.signed(x, 1) }, { key: 'wpa', label: 'WPA', num: true, fmt: x => U.signed(x, 2) }] });
  } else ct.innerHTML = U.empty('No career file', 'The career history is built with the season catalogues.');
  HW.setMeta('');
}

HW.page('player', render);
})(window.HW);
