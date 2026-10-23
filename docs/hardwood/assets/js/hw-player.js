/* The Quant Hardwood — the player page (#/<L>/player/<pid>), on Design System 2.0 (the Rink player page is the
 * reference).
 *
 * Overview tab: the player card header (team band, role, age, the season line); stat tiles with percentile chips
 * (impact, WAR, projected WAR, scoring, award chance); the Savant-style percentile card against his role (guards,
 * wings or bigs, qualified players, the sample shown, metrics short of their reliability sample dashed) from the one
 * metric set (HW.ui.MSET); among peers in the role's distribution; season by season; the game log and splits; the
 * shot chart on the half court; value; the career table; similar players (with compare links) and awards.
 * Detail tab (?tab=detail): the pre-redesign player page in full (the whole catalogue, radar, on/off, clutch,
 * projection, lineups, game log table).
 * Data: <L>/players/<pid>.json (career), <L>/<S>/players.json (catalogue), value.json (roles, WAR), valuation.json. */
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

function render(el, params) {
  const L = U.L(params), pid = String(params.id || '');
  const tab = U.tab(params, ['overview', 'detail'], 'overview');
  let S = U.S(params);
  const curS = HW.currentSeason(L);
  el.innerHTML = QK.skeleton('lines', 6);
  return HW.load(L + '/players/' + pid + '.json').then(career => {
    if (!U.alive(el)) return null;
    const seasons = ((career && career.seasons) || []).map(x => x.season);
    // a season he did not play: show his latest one before it (the header says so)
    let asked = null;
    if (seasons.length && seasons.indexOf(S) < 0) { const prev = seasons.filter(x => x <= S).sort((a, b) => b - a)[0] || Math.max.apply(null, seasons); if (prev !== S) { asked = S; S = prev; } }
    const isCurS = U.isCur(L, S);
    // the career file's role_card (players/<pid>.json) carries the role percentiles: then the 3.8 MB season catalogue
    // is not needed (it loads only if the reader asks for the peer distribution); otherwise the page computes them
    const rc = career && career.role_card && Number(career.role_card.season) === Number(S) && career.role_card.pct_role ? career.role_card : null;
    return Promise.all([rc ? Promise.resolve(rcCatalogue(career, rc, pid, S)) : HW.load(HW.path('players.json', L, S)), HW.load(HW.path('value.json', L, S)), HW.load(HW.path('valuation.json', L, curS)), U.movement(L)]).then(a => {
      if (!U.alive(el)) return;
      draw(el, L, S, pid, career, U.ok(a[0]) ? a[0] : null, U.ok(a[1]) ? a[1] : null, U.ok(a[2]) ? a[2] : null, asked, tab, params, a[3]);
    });
  });
}

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
  const team = (vrow && vrow.team) || (p && p.team) || srow.team || null;
  const col = team ? U.tcol(L, team) : QK.cssVar('--signal');
  const v = (p && p.values) || {};
  const pos = (p && p.pos) || (career && career.pos) || (vrow && vrow.pos) || '';
  const role = U.roleOf(p, pid, roles) || (swar && swar.role) || null;
  const age = p && isNum(p.age) ? Math.floor(p.age) : vrow && isNum(vrow.age) ? Math.floor(vrow.age) : null;
  document.title = name + ' · ' + HW.leagueName(L) + ' · The Quant Hardwood';
  const line = [['PPG', v.pts_g, '1'], ['RPG', v.reb_g, '1'], ['APG', v.ast_g, '1'], ['TS%', v.ts, 'pct']].filter(x => isNum(x[1]));
  const lineFallback = !line.length && srow.season ? [['PPG', srow.pts, '1'], ['RPG', srow.reb, '1'], ['APG', srow.ast, '1'], ['TS%', srow.ts, 'pct']].filter(x => isNum(x[1])) : [];
  const tags = [];
  if (p && p.qualified) tags.push(QK.tag('Qualified for percentiles', 'signal'));
  else if (p) tags.push(QK.tag('Short of the minutes floor'));
  if (vrow && vrow.inj) tags.push('<span class="qk-tag hw-inj">' + esc(vrow.inj) + '</span>');
  if (asked) tags.push(QK.tag('No ' + HW.seasonLabel(L, asked) + ' games yet: showing ' + HW.seasonLabel(L, S)));
  let h = '<div class="qk-kicker" style="margin-bottom:10px"><a href="' + esc(HW.href(L, 'players', S)) + '">← Players</a></div>' +
    QK.playerHeader({ name: name, pos: role ? (U.ROLE1 || {})[role] || role : pos, kicker: HW.leagueName(L) + ' · ' + HW.seasonLabel(L, S),
      team: team ? { name: HW.teamName(L, team), abbr: HW.teamAbbr(L, team), colour: HW.teamColourRaw(L, team), href: HW.teamHref(L, team, S) } : { name: 'Free agent' },
      meta: [age !== null ? ['Age', String(age)] : null, pos ? ['Listed', pos] : null, p ? ['Minutes', Number(Math.round(p.min || 0)).toLocaleString('en-GB') + ' in ' + (p.gp || 0) + ' games'] : null],
      stats: line.concat(lineFallback).map(x => ({ label: x[0], value: HW.fmtVal(x[1], x[2]) })), tags: tags });
  const base = HW.playerHref(L, pid, S);
  h += '<div style="margin-top:var(--sp-4)"></div>' + U.tabsHTML([{ key: 'overview', label: 'Overview', href: base }, { key: 'detail', label: 'Detail: the whole catalogue, on/off and lineups', href: base + (base.indexOf('?') >= 0 ? '&' : '?') + 'tab=detail' }], tab);
  if (tab === 'detail') { el.innerHTML = h + '<div class="hw-sub"></div>'; U.legacy('player', el.querySelector('.hw-sub'), params, null, { embed: 'detail' }); return; }
  // stat tiles: ours first, each with its percentile against his role where there is one
  const k = [];
  const hpm = isNum(v.hpm) ? v.hpm : srow.hpm;
  if (isNum(hpm)) k.push({ label: 'Total impact (HPM)', value: U.signed(hpm, 1), signal: true, pctl: p ? U.rolePctl(cat, roles, pid, 'hpm') : null, sub: 'offence ' + U.signed(isNum(v.hpm_o) ? v.hpm_o : srow.o, 1) + ' · defence ' + U.signed(isNum(v.hpm_d) ? v.hpm_d : srow.d, 1) + ' per 100', tip: 'Hardwood Plus-Minus: points per 100 possessions the player adds to the team’s margin over an average player (play-by-play on/off blended with the box score)' });
  if (swar && isNum(swar.war)) k.push({ label: 'Wins above replacement', value: U.f(swar.war, 1), pctl: isNum(swar.pct_role) ? swar.pct_role : null, sub: HW.seasonLabel(L, S) + (role ? ' · percentile among ' + U.ROLE_NAME[role] : ''), tip: 'Our wins above a replacement-level player this season, from HPM and minutes' });
  if (vrow) k.push({ label: 'Projected WAR', value: U.f(vrow.w0, 1), sub: 'rest of ' + HW.seasonLabel(L, HW.currentSeason(L)) + (isNum(vrow.p10) ? ' · four seasons ' + U.f(vrow.v, 1) + ' (80%: ' + U.f(vrow.p10, 1) + ' to ' + U.f(vrow.p90, 1) + ')' : ''), tip: 'Our projection of the player’s wins above replacement; the four-season value is discounted, with its 80% range' });
  if (isNum(v.pts100)) k.push({ label: 'Points per 100', value: U.f(v.pts100, 1), pctl: p ? U.rolePctl(cat, roles, pid, 'pts100') : null, sub: 'true shooting ' + HW.fmtVal(v.ts, 'pct') });
  const aw = cur.awards || {};
  const best = Object.keys(aw).filter(x => isNum(aw[x]) || (aw[x] && isNum(aw[x].p))).sort((a, b) => (isNum(aw[b]) ? aw[b] : aw[b].p) - (isNum(aw[a]) ? aw[a] : aw[a].p))[0];
  if (best) k.push({ label: 'Our ' + (best === 'mvp' ? 'MVP' : best.toUpperCase()) + ' chance', value: U.pct(isNum(aw[best]) ? aw[best] : aw[best].p), sub: 'from the award model' });
  if (k.length) h += '<div class="hw-kpis">' + QK.stats(k) + '</div>';

  const groups = p ? U.pctGroups(L, cat, roles, pid) : [];
  const peer = role ? U.peerName(L, role) : '';
  const set = role && U.MSET ? U.MSET.roles[role] : null;
  const style = set ? set.style.filter(x => isNum(v[x])) : [];
  const pcard = QK.pctCard({ title: 'Percentile rankings', peer: peer, sample: p ? U.sampleLine(L, cat, p) + (cat && cat.__rc && isNum(cat.__rc.n) ? ' · ' + cat.__rc.n + ' qualified ' + (U.ROLE_NAME[role] || 'peers') : '') : '', groups: groups,
    note: style.length ? 'Style, not better or worse: ' + style.map(x => U.mMeta(x).label + ' ' + U.fmtM(x, v[x])).join(' · ') + '.' : '',
    emptyText: p ? 'No role yet for this player: percentiles appear once the player has a role in the value table.' : 'No numbers for this season yet.' });
  const log = (cur.log || []).slice().sort((a, b) => String(a.date).localeCompare(String(b.date)));
  const cells = cur.shots && cur.shots.grid ? U.rowsOf(cur.shots.grid).filter(c => isNum(c.x) && isNum(c.y) && c.y <= 41.5) : [];
  h += '<div class="qk-grid"><div class="qk-span-5">' + pcard + '</div><div class="qk-span-7"><div class="hw-stack2">' +
    (groups.length ? U.card2('Among peers', 'Every qualified ' + esc(peer.replace(HW.leagueName(L) + ' ', '')) + ' this season; bars coloured by percentile', '<div class="qk-seg" id="pp-dist-m" role="group" aria-label="Metric" style="margin-bottom:10px"></div>' + U.chart('pp-dist', 240, 'Among peers: the role’s distribution')) : '') +
    (cs.length > 1 ? U.card2('Season by season', 'Impact per 100 possessions: total, offence and defence', U.chart('pp-career', 280, 'Impact by season')) : '') + '</div></div></div>';
  if (log.length) {
    h += '<div class="qk-grid hw-sec"><div class="qk-span-7">' + U.card2('Game by game', 'Game score per game (Hollinger); green when the team was ahead with this player on the floor', U.chart('pp-log', 240, 'Game score per game')) + '</div>' +
      '<div class="qk-span-5">' + U.card2('Splits', 'Per game', '<div id="pp-splits"></div>', { flush: true }) + '</div></div>';
  }
  // Who moves next: only where the block passed its held-out test (published); never a placeholder
  const mr = mv && mv.pub.next ? mv.by[pid] : null;
  if (mr && isNum(mr.p_next)) {
    const m = mv.m;
    h += '<div class="qk-grid hw-sec"><div class="qk-span-12">' + U.card2('Movement', 'Our chance the player has left the team ' + esc(U.mvHorizon(mv)) + ', and how. No contract data is used (Model page).',
      '<div class="hw-mvcard">' + QK.stats([{ label: 'Chance of moving', value: U.pctMv(mr.p_next), signal: true, sub: U.mvHorizon(mv), tip: (m.notes || [])[0] || '' },
        mv.pub.deadline && isNum(mr.p_dl) ? { label: 'Before the deadline', value: U.pctMv(mr.p_dl), sub: (m.deadline_label || 'traded or claimed') + ' by ' + HW.fmtDate(String((m.horizons || {}).deadline || ''), { weekday: false }) } : null]) +
      '<div style="margin-top:12px">' + U.mvBar(mv, mr) + '</div><div style="margin-top:8px">' + U.mvKeys(mv) + '</div>' +
      '<div class="hw-mvctx">' + esc([isNum(mr.age) && !/\bage\b/.test(mr.why || '') ? 'Age ' + Math.floor(mr.age) : '', isNum(mr.yrs) && !/seasons in the league/.test(mr.why || '') ? mr.yrs + ' seasons in the league' : '', isNum(mr.value) ? U.f(mr.value, 1) + ' WAR (last two seasons, 3:2)' : '', mr.why || ''].filter(Boolean).join(' · ')) + '</div></div>') + '</div></div>';
  }
  if (cells.length || vrow) {
    h += '<div class="qk-grid hw-sec">';
    if (cells.length) h += '<div class="qk-span-' + (vrow ? 6 : 12) + '">' + U.card2('Shot chart', 'Size is volume; colour is points per shot against the league from the same spot', '<div id="pp-shots" class="hw-court-max"></div>') + '</div>';
    if (vrow) h += '<div class="qk-span-' + (cells.length ? 6 : 12) + '">' + U.card2('Value', 'Projected WAR by season (mean path; ageing and survival included). Four-season value ' + U.f(vrow.v, 1) + ' (80% range ' + U.f(vrow.p10, 1) + ' to ' + U.f(vrow.p90, 1) + ')',
      U.chart('pp-val', 260, 'Projected WAR by season'), { foot: '<span></span>' + U.link(HW.href(L, 'value'), 'Value & Moves') }) + '</div>';
    h += '</div>';
  }
  h += '<section class="qk-section">' + U.head({ kicker: 'History', title: 'Career', sub: 'Box scores from 1997, play-by-play numbers (RAPM, WPA) from about 2017.' }) + '<div class="qk-card"><div id="pp-ctab"></div></div></section>';
  const awards = (career && career.career_awards) || [];
  const simR = (career && Array.isArray(career.similar_role) && career.similar_role.length) ? career.similar_role.filter(x => Number(x.season) === Number(S)).map(x => ({ id: String(x.id), name: x.name, d: x.distance }))
    : (p && p.qualified ? U.similarRole(L, cat, roles, pid, 5) : []);
  if (simR.length || awards.length) {
    h += '<div class="qk-grid hw-sec">' + (simR.length ? '<div class="qk-span-' + (awards.length ? 7 : 12) + '">' + U.card2('Most similar this season', 'Other qualified ' + esc((U.ROLE_NAME || {})[role] || 'players') + ', on the role\'s headline profile (each metric weighted by how stable it is)', '<ul class="hw-list">' + simR.map(x => '<li>' + U.playerEnt(L, x.id, x.name || HW.playerName(L, x.id), (P[x.id] || {}).team, null, S) +
      '<span class="s">distance ' + U.f(x.d, 2) + '</span><a class="v hw-link" href="' + esc(HW.href(L, 'compare/players/' + encodeURIComponent(pid) + '/' + encodeURIComponent(x.id), S)) + '">Compare</a></li>').join('') + '</ul>',
      { flush: true, foot: '<span></span>' + U.link(HW.href(L, 'compare/players/' + encodeURIComponent(pid) + '/' + simR.slice(0, 2).map(x => encodeURIComponent(x.id)).join('/'), S), 'Compare the top two') }) + '</div>' : '') +
      (awards.length ? '<div class="qk-span-' + (simR.length ? 5 : 12) + '">' + U.card2('Awards', '', '<div class="hw-pills">' + awards.slice().sort((a, b) => b[0] - a[0]).map(x => QK.tag(HW.seasonLabel(L, x[0]) + ' ' + (String(x[1]).length <= 5 ? String(x[1]).toUpperCase() : x[1]), 'signal')).join('') + '</div>') + '</div>' : '') + '</div>';
  }
  if (!p && !cs.length) h += U.empty('No numbers', 'This player has no games in the data yet.');
  el.innerHTML = h;

  // where he sits: the peer distribution of one metric of his role's set, with him and the median marked
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
  function drawAmong(cat) {
    if (!document.getElementById('pp-dist')) return;
    const pv = ((cat.players || {})[pid] || {}).values || v;
    const peers = U.rolePeers(cat, roles, role);
    const opts = set.groups.reduce((a, g) => a.concat(g[1]), []).filter(x => isNum(pv[x])).slice(0, 6);
    const segEl = document.getElementById('pp-dist-m');
    segEl.innerHTML = opts.map((o, i) => '<button type="button" aria-pressed="' + (i === 0) + '" data-value="' + o + '">' + esc(U.mMeta(o).label.replace(/ \(HPM\)$/, '')) + '</button>').join('');
    const drawDist = key => {
      const m = U.mMeta(key);
      const vals = peers.map(x => (x.values || {})[key]).filter(isNum).sort((a, b) => a - b);
      if (vals.length < 5) { document.getElementById('pp-dist').innerHTML = QK.empty('Too few qualified peers yet'); return; }
      const med = vals[Math.floor(vals.length / 2)];
      QKC.distribution('#pp-dist', { values: vals, binCount: 22, lowerBetter: m.better === 'low', fmt: x => U.fmtM(key, x), xName: m.label + ' · ' + vals.length + ' qualified ' + U.ROLE_NAME[role], yName: 'Players',
        marks: (isNum(pv[key]) ? [{ x: pv[key], label: name.split(' ').slice(-1)[0] }] : []).concat([{ x: med, label: 'Median' }]), label: 'Distribution of ' + m.label });
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
    QKC.mount('#pp-log', T => ({
      grid: { left: 8, right: 12, top: 28, bottom: 30, containLabel: true },
      xAxis: QKC.axis(T, { type: 'category', data: log.map(r => HW.fmtDate(r.date, { year: false, weekday: false })), split: false, line: true, name: 'Game date', nameLocation: 'middle', nameGap: 26 }),
      yAxis: QKC.axis(T, { name: 'Game score', nameAlign: 'left' }),
      tooltip: QKC.tooltip(T, { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: ps => { const r = log[ps[0].dataIndex];
        return '<div style="font-weight:600">' + esc(HW.fmtDate(r.date, { year: false }) + ' ' + (r.home ? 'v ' : '@ ') + HW.teamAbbr(L, r.opp)) + '</div>' + QKC.tipRow(ps[0].color, 'Game score', U.f(r.game_score, 1)) +
          QKC.tipRow(T.other, 'Line', (r.pts || 0) + ' pts · ' + (r.reb || 0) + ' reb · ' + (r.ast || 0) + ' ast') + QKC.tipRow(T.other, '+/-', U.signed(r.pm, 0)); } }),
      series: [{ type: 'bar', barMaxWidth: 14, data: log.map(r => ({ value: isNum(r.game_score) ? Math.round(r.game_score * 10) / 10 : 0, href: r.game ? HW.gameHref(L, r.game, S) : undefined,
        itemStyle: { color: r.pm > 0 ? T.up : r.pm < 0 ? T.down : T.other, borderRadius: [3, 3, 0, 0] } })) }]
    }), { label: 'Game score per game' });
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
