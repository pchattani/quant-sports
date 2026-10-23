/* The Quant Bullpen — the player page (#/<L>/hitter/<pid>, #/<L>/pitcher/<pid>, #/player/<pid>) on Design System 2.0
 * (the Rink player page is the reference).
 *
 * Overview: the player card header (club band, position, age, bats/throws, headline line); stat tiles with percentile
 *   chips; the Savant-style percentile card against his position (hitters: catchers, first base ... designated hitter)
 *   or role (starters, relievers), the spec's metric set (docs/METRICS_SPEC.md; BP.ui.SETS), the sample and the floor
 *   shown, early metrics dashed; where he sits among his peers (loaded on request: the season catalogue is 4-7 MB);
 *   pitchers: the pitch mix and the movement chart against the league's averages for each type; hitters: rolling
 *   xwOBA+ against wOBA; next season's projection with its 80% range; splits; season by season; the most similar players.
 * Detail (?view=detail): the full pre-redesign page (every metric, spray chart, zones, bat tracking, tunnels ...).
 *
 * First load: data/players/<pid>.json (the current season's values, pct_role and samples are in it), glossary.json and
 * <L>/<S>/season.json (team games, for prorating the floor). The catalogue (hitters.json / pitchers.json) loads only for
 * the distribution and the Detail view. Older seasons and levels other than the player's current one open Detail. */
(function (BP) {
'use strict';

const U = BP.ui, esc = BP.esc, isNum = BP.isNum;
const LEG = { hitter: BP.HANDLERS.hitter, pitcher: BP.HANDLERS.pitcher, player: BP.HANDLERS.player };
const DIST = { hitter: [['xwoba_n', 'xwOBA+'], ['war_600', 'WAR/600'], ['barrel_pct', 'Barrel%'], ['k_pct', 'K%'], ['chase_pct', 'Chase%']],
  pitcher: [['xwoba_n', 'xwOBA+ against'], ['stuff_plus', 'Stuff+'], ['k_bb_pct', 'K-BB%'], ['csw_pct', 'CSW%'], ['xfip', 'xFIP']] };

function age(dob) { const d = BP.parseDate(dob); return d ? Math.floor((Date.now() - d.getTime()) / (365.25 * 864e5)) : null; }
function teamGames(season, tid) {
  const rows = BP.standingsRows ? BP.standingsRows(season || {}) : {};
  const r = rows[String(tid)];
  return r && isNum(r.w) && isNum(r.l) ? r.w + r.l : null;
}

function render(el, params, state, route) {
  const pid = String(params.id || '');
  const L = params.level, S = params.season;
  const view = ((params.query || {}).view) === 'detail' ? 'detail' : 'overview';
  const legacy = () => (LEG[route] ? LEG[route](el, params, state) : null);
  if (view === 'detail') {
    const box = document.createElement('div');
    el.innerHTML = '';
    el.appendChild(box);
    return Promise.resolve(LEG[route] ? LEG[route](box, params, state) : null).then(() => {
      if (!U.alive(el)) return;
      const back = document.createElement('div');
      back.innerHTML = '<nav class="qk-tabs bp-tabs2" aria-label="Player views"><a class="qk-tab" href="' + esc(BP.playerHref(pid, { level: L, role: route === 'player' ? null : route, season: S })) + '" aria-selected="false">Overview</a>' +
        '<a class="qk-tab" href="javascript:void(0)" aria-selected="true">Detail: every metric, spray, zones, tunnels</a></nav>';
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
  document.title = p.name + ' · ' + BP.SITE;
  const posName = pit ? (blk.role === 'RP' ? 'Relief pitcher' : 'Starting pitcher') : ({ C: 'Catcher', '1B': 'First base', '2B': 'Second base', '3B': 'Third base', SS: 'Shortstop', LF: 'Left field', CF: 'Centre field', RF: 'Right field', DH: 'Designated hitter', TWP: 'Two-way player' }[String(blk.pos || p.pos)] || blk.pos || p.pos);
  const a = isNum(blk.age) ? Math.floor(blk.age) : age(p.dob);
  const stats = pit
    ? [{ label: 'IP', value: isNum(v.ip) ? BP.fmtIP(v.ip) : '—' }, { label: 'K%', value: isNum(v.k_pct) ? BP.fmtVal(v.k_pct, 'pct') : '—' }, { label: 'RA9', value: isNum(v.ra9) ? BP.num(v.ra9, 2) : '—' }, { label: 'WAR', value: isNum(v.war) ? BP.num(v.war, 1) : '—' }]
    : [{ label: 'PA', value: isNum(v.pa) ? String(v.pa) : '—' }, { label: 'HR', value: isNum(v.hr) ? String(v.hr) : '—' }, { label: 'AVG/OBP/SLG', value: isNum(v.avg) ? BP.fmtAvg(v.avg) + '/' + BP.fmtAvg(v.obp) + '/' + BP.fmtAvg(v.slg) : '—' }, { label: 'WAR', value: isNum(v.war) ? BP.num(v.war, 1) : '—' }];
  const tags = [];
  if (ok) tags.push(QK.tag('Ranked against ' + peer, 'signal'));
  else if (fl) tags.push(QK.tag('Short of the ' + fl.value + ' ' + fl.unit + ' floor'));
  const hero = QK.playerHeader({ name: p.name, pos: posName, kicker: BP.levelName(L) + ' ' + S,
    team: tid ? { name: BP.teamName(tid), abbr: BP.teamAbbr(tid), colour: (BP.teamInfo(tid) || {}).colour, href: BP.teamHref(tid, L, S) } : null,
    meta: [isNum(a) ? ['Age', String(a)] : null, ['Bats / throws', (p.bats || '—') + ' / ' + (p.throws || '—')], p.debut ? ['MLB debut', BP.fmtDate(p.debut, { year: true })] : null], stats: stats, tags: tags });
  const role = c.route === 'player' ? null : c.route;
  const base = BP.playerHref(pid, { level: L, role: role, season: S });
  const tabs = [['overview', 'Overview', base], ['detail', 'Detail: every metric, spray, zones' + (pit ? ', tunnels' : ', bat tracking'), base + (base.indexOf('?') >= 0 ? '&' : '?') + 'view=detail']];
  let twoTabs = '';
  if (c.twoWay) twoTabs = '<div class="qk-seg" role="group" aria-label="Side" style="margin-left:auto"><a class="qk-btn' + (pit ? '' : ' primary') + '" href="' + esc(BP.playerHref(pid, { level: L, role: 'hitter', season: S })) + '">Hitting</a><a class="qk-btn' + (pit ? ' primary' : '') + '" href="' + esc(BP.playerHref(pid, { level: L, role: 'pitcher', season: S })) + '">Pitching</a></div>';

  // stat tiles: ours first, with the percentile against his peers
  const pc = k => (ok && isNum(pr[k]) ? pr[k] : null);
  const k = [];
  if (pit) {
    if (isNum(v.war)) k.push({ label: 'Bullpen WAR', value: BP.num(v.war, 1), pctl: pc('war'), signal: true, sub: isNum(v.war_x) ? 'from xwOBA+ against ' + BP.num(v.war_x, 1) : 'runs allowed basis', tip: 'Our wins above replacement for a pitcher, from the runs allowed (RA9) against a replacement-level arm' });
    if (isNum(v.pitching_plus)) k.push({ label: 'Pitching+', value: String(Math.round(v.pitching_plus)), pctl: pc('pitching_plus'), sub: 'stuff, location and sequence · 100 = average', tip: 'Our pitch model: expected run value from the pitch, where it went and the count' });
    if (isNum(v.stuff_plus)) k.push({ label: 'Stuff+', value: String(Math.round(v.stuff_plus)), pctl: pc('stuff_plus'), sub: 'the physics of the pitches · 100 = average' });
    if (isNum(v.xfip)) k.push({ label: 'xFIP', value: BP.num(v.xfip, 2), pctl: pc('xfip'), sub: 'RA9 ' + BP.num(v.ra9, 2) + ' · FIP ' + BP.num(v.fip, 2) });
    if (isNum(v.k_bb_pct)) k.push({ label: 'K-BB%', value: BP.fmtVal(v.k_bb_pct, 'pct'), pctl: pc('k_bb_pct'), sub: 'strikeouts minus walks per batter' });
  } else {
    if (isNum(v.war)) k.push({ label: 'Bullpen WAR', value: BP.num(v.war, 1), pctl: pc('war_600'), signal: true, sub: isNum(v.war_600) ? BP.num(v.war_600, 1) + ' per 600 PA (the percentile)' : '', tip: 'Our wins above replacement: batting, baserunning, fielding and position' });
    if (isNum(v.xwoba_n)) k.push({ label: 'xwOBA+ (park-neutral)', value: BP.fmtAvg(v.xwoba_n), pctl: pc('xwoba_n'), sub: 'our expected wOBA · Savant ' + BP.fmtAvg(v.xwoba_savant), tip: (U.MDESC.hitter.xwoba_n || [])[1] });
    if (isNum(v.woba)) k.push({ label: 'wOBA', value: BP.fmtAvg(v.woba), pctl: pc('woba'), sub: 'OPS ' + BP.fmtAvg(v.ops) });
    if (isNum(v.barrel_pct)) k.push({ label: 'Barrel%', value: BP.fmtVal(v.barrel_pct, 'pct'), pctl: pc('barrel_pct'), sub: 'hard-hit ' + BP.fmtVal(v.hard_pct, 'pct') });
    if (isNum(v.bat_speed)) k.push({ label: 'Bat speed', value: BP.num(v.bat_speed, 1), unit: 'mph', pctl: pc('bat_speed'), sub: isNum(v.sprint_speed) ? 'sprint ' + BP.num(v.sprint_speed, 1) + ' ft/s' : '' });
  }

  const groups = ok ? U.pctGroups(blk, kind, setKey, gl, 'head', tg) : [];
  const more = ok ? U.pctGroups(blk, kind, setKey, gl, 'more', tg) : [];
  const pcard = (which, g) => QK.pctCard({ id: 'pp-pcard', title: which === 'more' ? 'More percentiles' : 'Percentile rankings', peer: peer, sample: U.sampleLine(blk, kind, setKey, tg), groups: g,
    right: more.length ? U.seg('pp-pset', 'Metric set', [['head', 'Core'], ['more', 'More']], which) : '',
    emptyTitle: 'Not ranked yet', emptyText: fl ? 'The player is short of the ' + fl.value + ' ' + fl.unit + ' floor for ' + peer + ' this season.' : 'No ranking this season.',
    foot: '<span>Peers: ' + esc(peer) + ' in ' + esc(BP.levelName(L)) + ' ' + S + '; 100 = best</span><a href="' + esc(BP.compareHref(pid)) + '">Compare →</a>' });

  let h = '<div class="qk-kicker" style="margin-bottom:10px"><a href="' + esc(BP.href(pit ? 'pitchers' : 'hitters', L, S)) + '">← ' + (pit ? 'Pitchers' : 'Hitters') + '</a></div>' + hero +
    '<div class="bp-flexrow">' + '<nav class="qk-tabs bp-tabs2" aria-label="Player views">' + tabs.map(t => '<a class="qk-tab" href="' + esc(t[2]) + '" aria-selected="' + (t[0] === 'overview') + '">' + esc(t[1]) + '</a>').join('') + '</nav>' + twoTabs + '</div>' +
    (k.length ? '<div class="bp-kpis">' + QK.stats(k) + '</div>' : '') +
    '<div class="qk-grid"><div class="qk-span-5" id="pp-pwrap">' + pcard('head', groups) + '</div><div class="qk-span-7"><div class="bp-stack">' +
    U.card2('Among peers', 'Every ' + peer.replace(/^MLB /, '') + ' past the floor this season; bars coloured by percentile', '<div id="pp-dist-m" style="margin-bottom:10px">' + U.seg('pp-dseg', 'Metric', DIST[kind], '') + '</div><div id="pp-dist">' +
      QK.empty('Pick a metric', 'The peer group loads on request (the season catalogue is several megabytes).') + '</div>') +
    (pit ? U.card2('Pitch mix', 'Each pitch type this season: usage, speed, Stuff+ and whiffs; the heat cells are percentiles among pitches of the same type', '<div id="pp-mix"></div>') +
      U.card2('Movement', 'Average induced vertical break against horizontal break towards the arm side, in inches; size is usage', U.chart('pp-mov', 360, 'Pitch movement') + '<div class="bp-note" id="pp-mov-cap"></div>')
      : (Array.isArray(cur.rolling) && cur.rolling.length > 5 ? U.card2('Form through the season', 'Rolling xwOBA+ (our expected wOBA, violet) against wOBA (what happened)', U.chart('pp-roll', 260, 'Rolling xwOBA+ and wOBA')) : '')) +
    '</div></div></div>';

  // projection, splits, career, similar
  h += '<section class="qk-section"><div class="qk-grid">';
  const pj = cur.projection;
  if (pj && pj.components) h += '<div class="qk-span-6">' + U.card2('Next season', 'Our ' + (pj.season || '') + ' projection with its 80% range (10th to 90th percentile)', '<div id="pp-proj"></div>', { flush: true }) + '</div>';
  const sp = (cur.splits || {})[pit ? 'pitcher' : 'batter'];
  if (sp) h += '<div class="qk-span-6">' + U.card2('Splits', 'This season' + (pit ? ', batters faced' : ''), '<div id="pp-splits"></div>', { flush: true }) + '</div>';
  h += '</div></section>';
  h += '<section class="qk-section" id="pp-mv"></section>';
  h += '<section class="qk-section">' + U.card2('Season by season', 'Every ' + (pit ? 'pitching' : 'hitting') + ' season in the data, all levels', '<div id="pp-career"></div>', { flush: true }) + '</section>';
  const sim = (p.similar || []).slice(0, 6);
  if (sim.length) h += '<section class="qk-section"><div class="qk-grid"><div class="qk-span-6">' + U.card2('Most similar', 'The nearest player-seasons since 2015 in the same ' + (pit ? 'role' : 'position') + ' group, on the spec’s weighted metrics', '<ul class="bp-list">' + sim.map(m =>
    '<li>' + U.playerEnt(m.pid, L, String(m.season) + (m.team ? ' · ' + BP.teamAbbr(m.team) : ''), kind) + '<a class="v bp-link" href="' + esc(BP.compareHref(pid, m.pid)) + '">Compare</a></li>').join('') + '</ul>', { flush: true }) + '</div></div></section>';
  el.innerHTML = h;

  // the percentile card's metric-set switch
  const wireSet = () => {
    const seg = el.querySelector('#pp-pset');
    if (seg) QK.seg(seg, w => { el.querySelector('#pp-pwrap').innerHTML = pcard(w, w === 'more' ? more : groups); wireSet(); });
  };
  wireSet();

  // where he sits: the peer group loads on request
  const dseg = el.querySelector('#pp-dseg');
  QK.seg(dseg, key => {
    const box = el.querySelector('#pp-dist');
    box.innerHTML = QK.skeleton('chart', 1);
    const slim = peerValues(blk, cur, key);
    (slim ? Promise.resolve(null) : BP.loadYear(pit ? 'pitchers.json' : 'hitters.json', L, S)).then(cat => {
      if (!U.alive(el)) return;
      if (!slim && (!BP.ok(cat) || !cat.players)) { box.innerHTML = QK.empty('Not available', 'The season catalogue did not load.'); return; }
      const m = U.metaOf(kind, key, gl);
      const vals = (slim || Object.keys(cat.players).map(id => cat.players[id]).filter(x => x && U.setFor(kind, x) === setKey && U.meets(x, setKey, cat.team_games)).map(x => (x.values || {})[key])).filter(isNum).sort((x, y) => x - y);
      if (vals.length < 5) { box.innerHTML = QK.empty('Too few peers yet', 'Fewer than five ' + peer + ' have reached the floor.'); return; }
      box.innerHTML = U.chart('pp-dist-c', 240, 'Distribution of ' + m.label);
      if (pit && cat && cat.league_types) drawMovement(el, Object.keys(cur.arsenal || {}).map(pt => Object.assign({ pt: pt }, cur.arsenal[pt])).filter(r => r.pt !== 'all' && isNum(r.usage) && (r.n || 0) >= MIX_MIN), cat.league_types);
      const mine = v[key];
      const med = vals[Math.floor(vals.length / 2)];
      QKC.distribution('#pp-dist-c', { values: vals, binCount: 22, lowerBetter: m.lower, fmt: x => U.fmtBy(m, x).replace(' mph', ''), xName: m.label + ' · ' + vals.length + ' ' + peer,
        yName: 'Players', marks: (isNum(mine) ? [{ x: mine, label: BP.playerSurname(pid) }] : []).concat([{ x: med, label: 'Median' }]), label: 'Distribution of ' + m.label });
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
