/* The Quant Hardwood — the player page (#/<L>/player/<pid>), on kit v3 "Matchday" (the Rink player page is the
 * reference, MIGRATION_V3.md).
 *
 * Top, as the concept: a crumb; the header (tilted tile, kicker, name, chips) with "The short version" in plain
 * English; stat tiles with percentile chips (impact, WAR, projected WAR, scoring, award chance); the percentile rail
 * against the role (guards, wings or bigs, qualified players, the sample named, metrics short of their reliability
 * sample dashed, a hollow ring for last season) from the one metric set (HW.ui.MSET), beside "How sure are we?"
 * (when the numbers settle at this playing time), game by game and "Their type" (most similar this season); a
 * compare of the player and the two closest matches with the highlighter and verdicts; the next game
 * (QK.previewCard) and the last one. Below, "More on the player": among peers in the role's distribution, season
 * by season, splits, movement, the shot chart on the half court, value, the career table and awards.
 * Detail tab (?tab=detail): the pre-redesign player page in full (the whole catalogue, radar, on/off, clutch,
 * projection, lineups, game log table).
 * Data: <L>/players/<pid>.json (career; role_card and prev-season percentiles when the builder writes them),
 * <L>/<S>/players.json (catalogue), value.json (roles, WAR), valuation.json; last season's players.json and
 * value.json load only when the rail scrolls into view and the career file has no last-season percentiles. */
(function (HW) {
'use strict';

const U = HW.ui, esc = HW.esc, isNum = HW.isNum;
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
  const players = {}; players[pid] = p;
  return { ok: true, players: players, min_floor: rc.min_floor, metrics: [], __rc: rc };
}

/* Last season's percentiles in the same peer group, when the career file carries them (the data builders add
   current.prev_pct_pos or role_card.prev_pct_role): { pct: {key: percentile}, gp, role } or null. */
function prevFromFile(career) {
  const c = (career && career.current) || {}, rc = (career && career.role_card) || {};
  const pc = c.prev_pct_pos || c.prev_pct_role || rc.prev_pct_role || rc.prev_pct_pos;
  if (!pc || typeof pc !== 'object') return null;
  const m = pc.pct || pc.pct_role || pc;
  return { pct: m, gp: isNum(pc.gp) ? pc.gp : null, role: pc.role || null };
}

function render(el, params) {
  const L = U.L(params), pid = String(params.id || '');
  const tab = U.tab(params, ['overview', 'detail'], 'overview');
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
  const sur = String(name).split(' ').slice(-1)[0];
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
  let h = crumb + QK.playerHeader({ name: name, pos: role ? (U.ROLE1 || {})[role] || role : pos, kicker: HW.seasonLabel(L, S) + (gpNow ? ' · ' + gpNow + ' game' + (gpNow === 1 ? '' : 's') + ' in' : ''),
    team: team ? { name: HW.teamName(L, team), abbr: HW.teamAbbr(L, team), colour: HW.teamColourRaw(L, team), href: HW.teamHref(L, team, S) } : { name: 'Free agent' },
    meta: [age !== null ? age + ' years old' : null, pos ? 'Listed ' + pos : null, p ? Number(Math.round(p.min || 0)).toLocaleString('en-GB') + ' minutes' : null], tags: tags, short: shortVersion() });
  // stat tiles: ours first, each with its percentile against the role where there is one
  const k = [];
  const hpm = isNum(v.hpm) ? v.hpm : srow.hpm;
  if (isNum(hpm)) k.push({ label: 'Total impact (HPM)', value: U.signed(hpm, 1), signal: true, pctl: isNum(pcs.hpm) ? pcs.hpm : null, sub: 'points per 100 trips: offence ' + U.signed(isNum(v.hpm_o) ? v.hpm_o : srow.o, 1) + ', defence ' + U.signed(isNum(v.hpm_d) ? v.hpm_d : srow.d, 1), tip: 'Hardwood Plus-Minus: points per 100 possessions the player adds to the team’s margin over an average player (play-by-play on/off blended with the box score)' });
  if (swar && isNum(swar.war)) k.push({ label: 'Wins above replacement', value: U.f(swar.war, 1), pctl: isNum(swar.pct_role) ? swar.pct_role : null, sub: HW.seasonLabel(L, S) + (role ? ' · percentile among ' + U.ROLE_NAME[role] : ''), tip: 'Our wins above a replacement-level player this season, from HPM and minutes' });
  if (vrow) k.push({ label: 'Projected WAR', value: U.f(vrow.w0, 1), sub: 'rest of ' + HW.seasonLabel(L, HW.currentSeason(L)) + (isNum(vrow.p10) ? ' · four seasons ' + U.f(vrow.v, 1) + ' (likely range ' + U.f(vrow.p10, 1) + ' to ' + U.f(vrow.p90, 1) + ')' : ''), tip: 'Our projection of the player’s wins above replacement; the four-season value is discounted, with its 80% range' });
  if (isNum(v.pts100)) k.push({ label: 'Points per 100', value: U.f(v.pts100, 1), pctl: p ? U.rolePctl(cat, roles, pid, 'pts100') : null, sub: 'true shooting ' + HW.fmtVal(v.ts, 'pct') });
  const aw = cur.awards || {};
  const best = Object.keys(aw).filter(x => isNum(aw[x]) || (aw[x] && isNum(aw[x].p))).sort((a, b) => (isNum(aw[b]) ? aw[b] : aw[b].p) - (isNum(aw[a]) ? aw[a] : aw[a].p))[0];
  if (best) k.push({ label: 'Our ' + (best === 'mvp' ? 'MVP' : best.toUpperCase()) + ' chance', value: U.pct(isNum(aw[best]) ? aw[best] : aw[best].p), sub: 'from the award model' });
  if (k.length) h += '<div class="hw-tiles">' + QK.stats(k) + '</div>';
  const base = HW.playerHref(L, pid, S);
  h += '<div style="margin-top:var(--sp-6)">' + U.tabsHTML([{ key: 'overview', label: 'Overview', href: base }, { key: 'detail', label: 'Detail: the whole catalogue, on/off and lineups', href: base + (base.indexOf('?') >= 0 ? '&' : '?') + 'tab=detail' }], tab) + '</div>';
  if (tab === 'detail') { el.innerHTML = h + '<div class="hw-sub"></div>'; U.legacy('player', el.querySelector('.hw-sub'), params, null, { embed: 'detail' }); return; }

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
  const sureCard = '<article class="qk-card cream"><div class="qk-card-body"><div class="qk-kicker">How sure are we?</div><h3 style="margin:8px 0 6px">' +
    esc(gpNow ? (small ? (gpNow < 11 ? NUMW[gpNow] : gpNow) + ' game' + (gpNow === 1 ? ' is' : 's is') + ' a small sample' : gpNow + ' games: the picture is settling') : 'No games yet this season') + '</h3>' +
    '<p style="margin:0;color:var(--ink-2);font-size:15px">' + (small ? 'Shooting numbers swing a lot early on. ' : '') + 'The hollow rings on the rail show last season, where there was one: dots that sit next to their ring are the steady part of the profile; the ones far from it are the ones to watch.</p>' +
    (settle.length && isNum(mpg) ? QK.note('At ' + U.f(mpg, 1) + ' minutes a game, ' + settle.join(', ').replace(/, ([^,]*)$/, ', and $1') + '.') : '') + '</div></article>';
  const gbg = log.length ? U.card2('Game by game', 'Game score each game (Hollinger’s one-number box score); teal when the team won the player’s minutes', U.chart('pp-log', 240, 'Game score per game')) : '';
  const simR = (career && Array.isArray(career.similar_role) && career.similar_role.length) ? career.similar_role.filter(x => Number(x.season) === Number(S)).map(x => ({ id: String(x.id), name: x.name, d: x.distance }))
    : (p && p.qualified ? U.similarRole(L, cat, roles, pid, 5) : []);
  const typeCard = simR.length ? '<article class="qk-card"><div class="qk-card-body"><div class="qk-kicker">Their type</div><h4 class="hw-h4">Plays most like</h4><ul class="hw-list hw-type">' +
    simR.slice(0, 3).map(x => '<li>' + U.playerEnt(L, x.id, x.name || HW.playerName(L, x.id), (P[x.id] || {}).team, null, S) + '<a class="v hw-link" href="' + esc(HW.href(L, 'compare/players/' + encodeURIComponent(pid) + '/' + encodeURIComponent(x.id), S)) + '">Compare</a></li>').join('') + '</ul>' +
    '<div class="qk-aside" style="margin-top:10px">Closest match among ' + esc(peerShort) + ' on this season’s profile, each metric weighted by how stable it is.</div></div></article>' : '';
  h += '<section class="qk-section hw-sec1"><div class="qk-gside"><div>' + railHTML() + '</div><div class="hw-stack2">' + sureCard + gbg + typeCard + '</div></div></section>';
  // compare (filled once the catalogue is in)
  if (simR.length && p) h += '<div id="pp-cmp-sent"></div><section class="qk-section" id="pp-cmp-sec" hidden><div id="pp-cmp-h"></div><article class="qk-card"><div class="qk-card-body"><div id="pp-cmp"></div></div></article></section>';
  // next game and last time out
  const info = HW.leagueInfo(L) || {};
  const nxt = U.isCur(L, S) && team ? (info.today || []).concat(info.next_games || []).filter(g => (String(g.home) === String(team) || String(g.away) === String(team)) && HW.gameState(g) !== 'post' && U.fresh(g)).sort((x, y) => String(x.date).localeCompare(String(y.date)))[0] : null;
  const lastG = log.length ? log[log.length - 1] : null;
  if (nxt || lastG) {
    h += '<section class="qk-section"><div class="qk-g2">';
    if (nxt) {
      const g = U.game(nxt, L, {});
      h += '<div><div class="qk-kicker" style="margin-bottom:10px">' + (g.status === 'live' ? 'Live now' : (QK.fmt.relDay(nxt.date) === 'Today' ? 'What to watch tonight' : 'Next up')) + '</div>' +
        QK.previewCard(g, { kicker: HW.leagueName(L) + ' · ' + HW.teamName(L, nxt.away) + ' at ' + HW.teamName(L, nxt.home), nick: t => String(t.name || '').split(' ').slice(-1)[0] }) + '</div>';
    }
    if (lastG) {
      const line = (lastG.pts || 0) + ' points, ' + (lastG.reb || 0) + ' rebounds, ' + (lastG.ast || 0) + ' assists in ' + U.f(lastG.min, 0) + ' minutes' + (isNum(lastG.game_score) ? ', game score ' + U.f(lastG.game_score, 1) : '') + (isNum(lastG.pm) ? ', ' + U.signed(lastG.pm, 0) + ' on the floor' : '');
      const href = lastG.game ? HW.gameHref(L, lastG.game, S) : null;
      h += '<div><div class="qk-kicker" style="margin-bottom:10px">Last time out</div><' + (href ? 'a href="' + esc(href) + '"' : 'div') + ' class="qk-card hw-lastg"><div class="qk-card-body"><div class="qk-feature-meta"><span class="qk-pill">' + esc(HW.fmtDate(lastG.date, { year: false })) + '</span></div>' +
        '<h3 style="margin:12px 0 4px">' + esc((lastG.home ? 'v ' : 'at ') + HW.teamName(L, lastG.opp)) + '</h3>' + QK.note('<b>' + esc(sur) + ':</b> ' + esc(line) + '.') + '</div></' + (href ? 'a' : 'div') + '></div>';
    }
    h += '</div></section>';
  }

  // ── more on the player
  const cells = cur.shots && cur.shots.grid ? U.rowsOf(cur.shots.grid).filter(c => isNum(c.x) && isNum(c.y) && c.y <= 41.5) : [];
  const groupsAll = p ? U.pctGroups(L, cat, roles, pid) : [];
  h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'More on the player', title: 'Peers, splits and the long view', sub: 'Where the player sits among ' + esc(peerShort) + ', how the season splits, and every season in the data.' }) +
    '<div class="qk-grid">' + (groupsAll.length ? '<div class="qk-span-6">' + U.card2('Among peers', 'Every qualified ' + esc(peer.replace(HW.leagueName(L) + ' ', '')) + ' this season; bars coloured by percentile', '<div class="qk-seg" id="pp-dist-m" role="group" aria-label="Metric" style="margin-bottom:10px"></div>' + U.chart('pp-dist', 240, 'Among peers: the role’s distribution')) + '</div>' : '') +
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

  // compare: the player and the two closest matches, on the role's headline set, the best in each row highlighted
  const withFull = cb => (cat && !cat.__rc ? cb(cat) : HW.load(HW.path('players.json', L, S)).then(full => { if (U.ok(full) && full.players) cb(full); }));
  if (el.querySelector('#pp-cmp-sec')) {
    const host = el.querySelector('#pp-cmp-sec');
    const fill = () => withFull(full => {
      if (!U.alive(el)) return;
      const ids = [pid].concat(simR.map(x => x.id)).filter(id => full.players[id]).slice(0, 3);
      if (ids.length < 2 || !set) return;
      const E = ids.map(id => full.players[id]);
      const bestOf = {};
      const groups = set.groups.map(g => ({ label: g[0], rows: g[1].map(kk => {
        const m = U.mMeta(kk), pcl = ids.map(id => U.rolePctl(full, roles, id, kk));
        pcl.forEach((x, i) => { if (!isNum(x)) return; const d = x - Math.max.apply(null, pcl.filter((_, j) => j !== i).map(z => (isNum(z) ? z : 0))); if (!bestOf[i] || d > bestOf[i].d) bestOf[i] = { k: kk, d: d, v: (E[i].values || {})[kk] }; });
        return { label: m.label, tip: m.desc, better: m.better, values: E.map(e => (e.values || {})[kk]), pctls: pcl, fmt: x => U.fmtM(kk, x) };
      }) }));
      const names = E.map(e => String(e.name || '').split(' ').slice(-1)[0]);
      el.querySelector('#pp-cmp-h').innerHTML = QK.sectionHead({ kicker: 'Compare', title: names.slice(0, -1).join(', ') + ' or ' + names[names.length - 1] + '?',
        sub: 'The closest matches on this season’s profile, side by side against ' + esc(peer) + '. The best in each row is highlighted; the small pills are percentiles.',
        actions: '<a class="qk-more" href="' + esc(HW.href(L, 'compare/players/' + ids.map(encodeURIComponent).join('/'), S)) + '">Open in Compare</a>' });
      const ents = E.map((e, i) => ({ name: e.name, href: HW.playerHref(L, ids[i], S), sub: [HW.teamAbbr(L, e.team), (e.gp || 0) + ' GP'].join(' · ') }));
      const verd = E.map((e, i) => (bestOf[i] && bestOf[i].d > 0 ? { title: U.ARCHETYPE[bestOf[i].k] || 'The standout', who: names[i], text: 'best of the ' + E.length + ' on ' + lc(U.mMeta(bestOf[i].k).label) + ' (' + U.fmtM(bestOf[i].k, bestOf[i].v) + ').' } : null));
      el.querySelector('#pp-cmp').innerHTML = QK.compareView({ entities: ents, groups: groups, delta: false }) + QK.verdicts(verd);
      host.hidden = false;
    });
    const sent = el.querySelector('#pp-cmp-sent');
    if ((cat && !cat.__rc) || !window.IntersectionObserver || !sent) fill();
    else { const io = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) { io.disconnect(); fill(); } }, { rootMargin: '300px' }); io.observe(sent); }
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
        tooltip: QKC.tooltip(T, { trigger: 'axis', axisPointer: { type: 'shadow', shadowStyle: { color: 'rgba(255,201,77,.08)' } }, formatter: ps => { const r = log[ps[0].dataIndex];
          return '<div style="font-weight:600">' + esc(HW.fmtDate(r.date, { year: false }) + ' ' + (r.home ? 'v ' : '@ ') + HW.teamAbbr(L, r.opp)) + '</div>' + QKC.tipRow(ps[0].color, 'Game score', U.f(r.game_score, 1)) +
            QKC.tipRow(T.ink3, 'Line', (r.pts || 0) + ' pts · ' + (r.reb || 0) + ' reb · ' + (r.ast || 0) + ' ast') + QKC.tipRow(T.ink3, '+/-', U.signed(r.pm, 0)); } }),
        series: [{ type: 'bar', barMaxWidth: 26, data: log.map((r, i) => {
          const o = { value: isNum(r.game_score) ? Math.round(r.game_score * 10) / 10 : 0, href: r.game ? HW.gameHref(L, r.game, S) : undefined,
            itemStyle: { color: r.pm > 0 ? T.model : r.pm < 0 ? T.coral : T.ink3, borderRadius: [6, 6, 0, 0] } };
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
