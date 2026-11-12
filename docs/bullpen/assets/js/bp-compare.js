/* The Quant Bullpen — compare (#/compare/<a>/<b>?c=<third>), on kit v4 "Broadcast" (the Rink compare page is the
 * reference): two or three hitters or pitchers side by side on the spec's metric set (BP.ui.SETS), the better value
 * solid, and where each sits in the peer distribution (loaded on request).
 *
 * Peers: when every player is in the same position group (hitters) or role (pitchers), the percentiles are against that
 * group (pct_role) and the set is the group's; hitters of different positions are against all MLB hitters (pct) on the
 * all-hitters set. Starters and relievers are never pooled: a starter beside a reliever is each against his own role
 * (pct_role) on the first player's role set, and the distribution shows that role, as the page says. Data: data/players/<pid>.json for each
 * (the current season's values, pct and pct_role are in the player file), glossary.json; the season catalogue loads only
 * for the distribution. Teams, other levels and seasons, and the classic every-metric view: ?view=classic.
 *
 * v4 (Broadcast): the title asks the question ("Judge, Ohtani or Soto?"); two players are the tale of the tape in their
 * club colours (bars = percentile, the better number solid), three a table with the best value under the volt stroke;
 * a verdict under it names what each player does best (QK.verdicts, the type from BP.ui.ARCHETYPE).
 *
 * Position first (12 Nov): a chip per peer group of the spec (hitters by position, pitchers by role: starters and
 * relievers never pooled) loads that group's top two by WAR among the qualified (#/compare?g=<group>); the active chip is
 * the group on screen, and a line under the chips names its headline metrics. Defaults come from the season's lab.json
 * (shared with the Scouting Room): nobody picked, the top two of the group the season's best hitter plays in (starters
 * with ?kind=pitcher); one picked, his most similar player in his own group (QK.within.similar on the group's headline
 * metrics). Players from different groups get "Compare <A> with a <group> instead" links; a group with fewer than ten
 * qualified players says so and offers last season. The name boxes suggest the active group first. */
(function (BP) {
'use strict';

const U = BP.ui, esc = BP.esc, isNum = BP.isNum;
const LEG = BP.HANDLERS.compare;
const COLS = ['var(--wp-a)', 'var(--wp-b)', 'var(--c-5)'];
let KIND = 'hitter';

function blockOf(p, kind, L, S) {
  const c = (p && p.current) || {};
  if (Number(c.season) !== Number(S) || String(c.level || 'mlb') !== String(L)) return null;
  return kind === 'pitcher' ? c.pitching : c.hitting;
}

/* ── peer groups from the season's lab.json ───────────────────────────────────────────────────────────── */
const GCODES = [['C', 'Catchers', 'catcher'], ['1B', 'First base', 'first baseman'], ['2B', 'Second base', 'second baseman'], ['3B', 'Third base', 'third baseman'],
  ['SS', 'Shortstops', 'shortstop'], ['CF', 'Centre field', 'centre fielder'], ['LF/RF', 'Corner outfield', 'corner outfielder'], ['DH', 'Designated hitters', 'designated hitter'],
  ['SP', 'Starters', 'starting pitcher'], ['RP', 'Relievers', 'reliever']];
const GOK = g => GCODES.some(x => x[0] === g);
const gKind = g => (g === 'SP' || g === 'RP' ? 'pitcher' : 'hitter');
const gInfo = g => GCODES.filter(x => x[0] === g)[0] || null;
/* lab.json -> { by: {kind: {id: row}}, q: {group: [qualified rows, best WAR first]}, top2(g), similar(id, kind), main(kind) }
   (a two-way player has a row of each kind) */
function labIndex(raw, TG) {
  const by = { hitter: {}, pitcher: {} }, q = {};
  GCODES.forEach(x => { q[x[0]] = []; });
  if (raw && raw.ok !== false && raw.rows && !Array.isArray(raw.rows)) Object.keys(raw.rows).forEach(kd => {
    const kk = /pit/.test(kd) ? 'pitcher' : 'hitter';
    const fields = (raw.fields || ['pid', 'name', 'team', 'pos', 'n']).concat(((raw.metrics || {})[kd] || []).map(m => m.key));
    const idx = {};
    fields.forEach((f, i) => { if (idx[f] === undefined) idx[f] = i; });
    (raw.rows[kd] || []).forEach(a => {
      const pos = String(a[idx.pos] || '').toUpperCase();
      const g = kk === 'pitcher' ? (pos === 'RP' ? 'RP' : 'SP') : (U.ROLE_OF_POS[pos] || null);
      if (!g) return;
      const r = { id: String(a[idx.pid]), name: a[idx.name] || '', team: a[idx.team], pos: pos, g: g, kind: kk, n: a[idx.n] || 0, a: a, idx: idx };
      by[kk][r.id] = r;
      const fl = U.floorOf(g, TG);
      if (!fl || r.n >= fl.value) q[g].push(r);
    });
  });
  const v = (r, k) => { const i = r.idx[k]; const x = i === undefined ? null : r.a[i]; return isNum(x) ? x : null; };
  Object.keys(q).forEach(g => q[g].sort((x, y) => (v(y, 'war') || 0) - (v(x, 'war') || 0)));
  const similar = (id, kind) => {
    const r = by[kind][String(id)];
    if (!r || !QK.within || !QK.within.similar) return null;
    const pool = q[r.g].indexOf(r) >= 0 ? q[r.g] : q[r.g].concat([r]);
    const keys = U.flat(r.g, 'head').map(x => x[0]).filter(k => r.idx[k] !== undefined);
    const near = QK.within.similar(pool, r, keys, v, 1);
    return near.length ? near[0].row.id : (q[r.g].filter(x => x !== r)[0] || {}).id || null;
  };
  return { by: by, q: q, similar: similar,
    top2: g => (q[g] || []).slice(0, 2).map(r => r.id),
    /* the hitters' main group: where the season's best qualified hitter plays; pitchers: the starters */
    main: kind => {
      if (kind === 'pitcher') return 'SP';
      let best = null;
      GCODES.filter(x => gKind(x[0]) === 'hitter').forEach(x => { const r = q[x[0]][0]; if (r && q[x[0]].length >= 2 && (!best || (v(r, 'war') || 0) > (v(best, 'war') || 0))) best = r; });
      return best ? best.g : 'SS';
    } };
}
function words(g, kind) {
  const ws = U.flat(g, 'head').map(x => U.metaOf(kind, x[0], null).label);
  return ws.length > 1 ? ws.slice(0, -1).join(', ') + ' and ' + ws[ws.length - 1] : ws.join('');
}
function chipHref(g, S, L) { return '#/compare?g=' + encodeURIComponent(g) + (Number(S) !== Number(BP.currentSeason(L)) ? '&s=' + S : ''); }
function groupStrip(active, S, L, LX, cross) {
  const chip = x => '<button type="button" class="qk-chip" data-cmp-go="' + esc(chipHref(x[0], S, L)) + '" aria-pressed="' + (x[0] === active ? 'true' : 'false') + '">' + esc(x[1]) + '</button>';
  const gi = gInfo(active);
  const n = LX && active ? (LX.q[active] || []).length : null;
  const thin = gi && isNum(n) && n < 10 ? '<p class="cmp-thin">Early in the season: only ' + n + ' qualified ' + esc(U.peerName(active).replace(/^MLB /, '')) + ' so far; percentiles settle as games are played.' +
    (Number(S) > 2015 ? ' <a href="' + esc('#/compare?g=' + encodeURIComponent(active) + '&s=' + (Number(S) - 1)) + '">Last season (' + (Number(S) - 1) + ')</a>' : '') + '</p>' : '';
  return '<div class="cmp-groups"><div class="qk-chips scroll" role="group" aria-label="Position or role">' +
    '<span class="cmp-glab">Hitters</span>' + GCODES.filter(x => gKind(x[0]) === 'hitter').map(chip).join('') +
    '<span class="cmp-glab">Pitchers</span>' + GCODES.filter(x => gKind(x[0]) === 'pitcher').map(chip).join('') + '</div>' +
    (gi ? '<p class="cmp-gline"><b>' + esc(gi[1]) + ':</b> ' + esc(words(active, gKind(active))) + ' — the metrics that best describe and predict a ' + esc(gi[2]) + '.</p>' : cross ? '<p class="cmp-gline">' + esc(cross) + '</p>' : '') + thin + '</div>';
}

function render(el, params, state) {
  if (params.a === 'progression' && BP.progression) return BP.progression.compare(el, params);  /* #/compare/progression/<ids> (bp-progression.js) */
  const q = params.query || {};
  const L = params.level, S = params.season;
  let ids = [params.a, params.b, q.c].filter(x => x && /^\d+$/.test(String(x)));
  if (q.view === 'classic' || L === 'npb' || (params.a && /^t/.test(String(params.a)))) return LEG ? LEG(el, params, state) : null;
  const g0 = GOK(q.g) ? q.g : null;
  if (ids.length) KIND = BP.isPitcher(ids[0]) && String(BP.player(ids[0]).pos).toUpperCase() !== 'TWP' ? 'pitcher' : 'hitter';
  if (q.kind === 'pitcher' || q.kind === 'hitter') KIND = q.kind;
  else if (!ids.length) KIND = g0 ? gKind(g0) : 'hitter';
  el.innerHTML = QK.skeleton('card', 2);
  el.addEventListener('click', ev => { const t = ev.target.closest ? ev.target.closest('[data-cmp-go]') : null; if (t) location.hash = t.getAttribute('data-cmp-go'); });
  return Promise.all([BP.loadYear('lab.json', L, S), BP.loadYear('season.json', L, S)]).then(r0 => {
    if (!U.alive(el)) return null;
    const LX = labIndex(r0[0], BP.ok(r0[1]) ? r0[1].team_games : null);
    let auto = false;
    if (!ids.length) {
      const g = g0 && LX.q[g0].length >= 2 ? g0 : LX.main(KIND);
      ids = LX.top2(g); auto = true;
      if (ids.length) KIND = gKind(g);
    } else if (ids.length === 1) { const sim = LX.similar(ids[0], KIND); if (sim) { ids.push(sim); auto = true; } }
    return draw(el, params, q, L, S, ids, LX, auto, g0);
  });
}

function draw(el, params, q, L, S, ids, LX, auto, g0) {
  return Promise.all(ids.map(id => BP.load('players/' + id + '.json')).concat([U.gloss(), BP.loadYear('season.json', L, S)])).then(res => {
    if (!U.alive(el)) return;
    const gl = res[ids.length], season = BP.ok(res[ids.length + 1]) ? res[ids.length + 1] : null;
    const P = ids.map((id, i) => ({ id: id, p: BP.ok(res[i]) ? res[i] : null })).map(x => Object.assign(x, { b: blockOf(x.p, KIND, L, S) }));
    const E = P.filter(x => x.b && x.b.values);
    const sets = E.map(x => U.setFor(KIND, x.b));
    const same = sets.length && sets.every(s => s === sets[0]);
    const pit = KIND === 'pitcher', byRole = same || pit;           // pitchers always rank within their own role
    const setKey = same ? sets[0] : (pit ? (sets[0] || 'SP') : 'ALL');
    const peer = same ? U.peerName(setKey) : (pit ? 'each pitcher\'s own role' : 'all MLB hitters');
    const why = same ? '' : pit ? ' (a starter and a reliever are never pooled: starters rank with starters, relievers with relievers, on the ' + U.peerName(setKey) + '\' set)' : ' (they play different positions, so the percentiles are against all hitters)';
    const kq = KIND === 'pitcher' ? 'kind=pitcher' : '';
    const href = (a, b, c) => BP.compareHref(a, b) + (c || kq ? '?' + [c ? 'c=' + encodeURIComponent(c) : '', kq].filter(Boolean).join('&') : '');
    const sn = E.map(x => BP.playerSurname(x.id));
    const lgOf = x => (LX.by[KIND][x.id] || {}).g || U.setFor(KIND, x.b);
    const active = E.length ? (same ? setKey : lgOf(E[0])) : (g0 || (ids.length ? (LX.by[KIND][ids[0]] || {}).g : null) || (KIND === 'pitcher' ? 'SP' : null));
    /* players from different groups: each one's own-group comparison, one click away */
    const instead = E.length >= 2 && !same ? '<p class="cmp-instead">' + E.slice(0, 3).map(x => { const sim = LX.similar(x.id, KIND), gi = gInfo(lgOf(x)); return sim && gi ? '<a href="' + esc(href(x.id, sim, '')) + '">Compare ' + esc(BP.playerSurname(x.id)) + ' with a ' + esc(gi[2]) + ' instead</a>' : ''; }).filter(Boolean).join('<span aria-hidden="true"> · </span>') + '</p>' : '';
    let h = U.head({ kicker: 'Compare · ' + BP.levelName(L) + ' ' + S, title: E.length >= 2 ? sn.slice(0, -1).join(', ') + ' or ' + sn[sn.length - 1] + '?' : 'Compare players',
      sub: 'Two or three ' + (KIND === 'pitcher' ? 'pitchers' : 'hitters') + ' on the metrics that are stable from year to year and predict next season, chosen for their position or role.',
      actions: '<a class="qk-btn" href="' + esc('#/compare/progression/' + ids.map(encodeURIComponent).join('/') + '?kind=' + KIND) + '">Careers: progression</a>' + '<a class="qk-btn" href="' + esc(BP.compareHref(ids[0] || '', ids[1] || '') + '?' + (ids[2] ? 'c=' + encodeURIComponent(ids[2]) + '&' : '') + 'view=classic') + '">Every metric (classic)</a>' }) +
      groupStrip(E.length >= 2 && !same ? null : active, S, L, LX, E.length >= 2 && !same ? (pit ? 'A starter and a reliever: each is ranked against his own role, on the ' + U.peerName(setKey) + '\' set.' : 'Different positions: both are ranked against all MLB hitters, on the set every hitter shares.') : '') + instead +
      '<section class="qk-card"><div class="qk-card-body"><div class="bp-cmp-pick">' + [0, 1, 2].map(i => '<div class="bp-cmp-slot" style="--ec:' + COLS[i] + '"><span class="qk-kicker" style="margin:0">' + (i === 2 ? 'Third (optional)' : i ? 'Second' : 'First') + '</span><div id="cmp-p' + i + '"></div></div>').join('') + '</div></div></section>';
    if (E.length < 2) h += '<div style="margin-top:var(--sp-4)">' + QK.empty('Pick two ' + KIND + 's', ids.length && !E.length ? 'No ' + S + ' ' + BP.levelName(L) + ' ' + KIND + ' season on file for that player: try the classic view or another season.' : 'Type a name above, or pick a position.') + '</div>';
    else {
      const which = 'head';
      const flat = U.flat(setKey, which).concat(U.flat(setKey, 'more').filter(x => ['war', 'xfip', 'ra9', 'fip', 'iso', 'ev90', 'whiff_pct', 'oaa', 'location_plus'].indexOf(x[0]) >= 0)).filter(x => same || !U.FIELDING[x[0]]);
      const groups = [];
      ((U.SETS[setKey] || {})[which] || []).forEach(g => groups.push({ label: g[0], keys: g[1].map(x => x[0]) }));
      const extra = flat.filter(x => !groups.some(g => g.keys.indexOf(x[0]) >= 0)).map(x => x[0]);
      if (extra.length) groups.push({ label: 'More', keys: extra });
      const pk = byRole ? 'pct_role' : 'pct';
      const cgroups = groups.map(g => ({ label: g.label, rows: g.keys.map(k => {
        const m = U.metaOf(KIND, k, gl);
        return { key: k, label: m.label, tip: m.tip, values: E.map(x => (x.b.values || {})[k]), pctls: E.map(x => (U.metricOk(x.b, k, same ? setKey : pit ? U.setFor(KIND, x.b) : 'ALL', null) && U.meets(x.b, U.setFor(KIND, x.b), null) ? (x.b[pk] || {})[k] : null)), better: m.lower ? 'low' : 'high', fmt: val => U.fmtBy(m, val) };
      }) }));
      /* verdicts: for each player, the metric where the player's percentile beats the others' by the most */
      const verd = E.map((x, i) => {
        let bestRow = null, bestD = 0;
        cgroups.forEach(g => g.rows.forEach(r => {
          const mine = r.pctls[i]; if (!isNum(mine)) return;
          const d = mine - Math.max.apply(null, r.pctls.filter((_, j) => j !== i).map(z => (isNum(z) ? z : 0)));
          if (d > bestD) { bestD = d; bestRow = r; }
        }));
        return bestRow ? { title: ((U.ARCHETYPE || {})[KIND] || {})[bestRow.key] || 'The standout', who: sn[i], text: 'best of the ' + E.length + ' on ' + bestRow.label + ' (' + bestRow.fmt(bestRow.values[i]) + ', ' + QK.ordinal(Math.round(bestRow.pctls[i])) + ' percentile).' } : null;
      });
      const cv = QK.compareView({
        entities: E.map((x, i) => ({ name: x.p.name, sub: [BP.teamAbbr(x.b.team), x.b.pos || x.b.role, U.sampleLine(x.b, KIND, U.setFor(KIND, x.b), null).split(' · ')[0]].filter(Boolean).join(' · '), colour: U.raw(x.b.team), alt: U.alt(x.b.team), short: sn[i], href: BP.playerHref(x.id, { level: L, role: KIND, season: S }) })),
        groups: cgroups
      }) + QK.verdicts(verd);
      h += '<section class="qk-section"><div class="qk-grid"><div class="qk-span-7">' + U.card2(E.length === 2 ? 'Tale of the tape' : 'Side by side', 'Peers: ' + esc(peer) + why + (E.length === 2 ? '. Bar length = percentile (100 = best); the better number in each row is solid.' : '. The pill is the percentile (100 = best); the best value in each row is highlighted.'), cv) + '</div>' +
        '<div class="qk-span-5"><div class="bp-stack">' + U.card2('Where they sit', 'All ' + esc((same ? peer : pit ? U.peerName(setKey) : peer).replace(/^MLB /, '')) + ' past the floor this season', U.seg('cmp-dseg', 'Metric', flat.slice(0, 5).map(x => [x[0], U.metaOf(KIND, x[0], gl).label]), '') + '<div id="cmp-dist" style="margin-top:10px">' + QK.empty('Pick a metric', 'The peer group loads on request (the season catalogue is several megabytes).') + '</div>') +
        U.card2('Samples', 'Percentiles need ' + (U.floorOf(setKey, null) || {}).full + '+ ' + ((U.floorOf(setKey, null) || {}).unit || '') + ' over a full season (prorated in season)', '<ul class="bp-list">' + E.map((x, i) => '<li><span class="bp-dot" style="background:' + COLS[i] + '"></span>' + U.playerEnt(x.id, L, null, KIND) + '<span class="v" style="font:600 var(--fs-xs) var(--font-num)">' + esc(U.sampleLine(x.b, KIND, U.setFor(KIND, x.b), null).split(' · peers')[0]) + '</span></li>').join('') + '</ul>', { flush: true }) +
        '</div></div></div></section>';
    }
    el.innerHTML = h;
    const cur = [ids[0] || '', ids[1] || '', ids[2] || ''];
    const rank = id => { const r = LX.by[KIND][id]; return r && r.g === active ? 0 : r ? 1 : 2; };
    [0, 1, 2].forEach(i => {
      const host = el.querySelector('#cmp-p' + i);
      if (!host || !BP.gk || !BP.gk.picker) return;
      BP.gk.picker(host, { value: cur[i] || null, label: cur[i] ? BP.playerName(cur[i]) : '', placeholder: 'Type a ' + KIND + '…',
        filter: id => (KIND === 'pitcher' ? BP.isPitcher(id) : (!BP.isPitcher(id) || String(BP.player(id).pos).toUpperCase() === 'TWP')), rank: rank,
        onPick: id => { const n = cur.slice(); n[i] = id; location.hash = href(n[0], n[1], n[2]); } });
    });
    const dseg = el.querySelector('#cmp-dseg');
    if (dseg) QK.seg(dseg, key => {
      const box = el.querySelector('#cmp-dist');
      box.innerHTML = QK.skeleton('chart', 1);
      BP.loadYear(KIND === 'pitcher' ? 'pitchers.json' : 'hitters.json', L, S).then(cat => {
        if (!U.alive(el)) return;
        if (!BP.ok(cat) || !cat.players) { box.innerHTML = QK.empty('Not available', 'The season catalogue did not load.'); return; }
        const peers = Object.keys(cat.players).map(id => cat.players[id]).filter(x => x && (!byRole || U.setFor(KIND, x) === setKey) && U.meets(x, U.setFor(KIND, x), cat.team_games));
        const m = U.metaOf(KIND, key, gl);
        const vals = peers.map(x => (x.values || {})[key]).filter(isNum).sort((a, b) => a - b);
        if (vals.length < 5) { box.innerHTML = QK.empty('Too few peers yet'); return; }
        box.innerHTML = U.chart('cmp-dist-c', 260, 'Distribution of ' + m.label);
        const T = QKC.tokens();
        const marks = E.map((x, i) => ({ x: (x.b.values || {})[key], label: BP.playerSurname(x.id), color: QK.cssVar(['--wp-a', '--wp-b', '--c-5'][i]) || T.cat[i] })).filter(mk => isNum(mk.x));
        marks.push({ x: vals[Math.floor(vals.length / 2)], label: 'Median', color: T.ink2 });
        QKC.distribution('#cmp-dist-c', { values: vals, binCount: 22, lowerBetter: m.lower, fmt: v => U.fmtBy(m, v), xName: m.label + ' · ' + vals.length + ' peers', yName: 'Players', marks: marks, label: 'Distribution of ' + m.label });
      });
    });
    BP.setMeta('');
  });
}

BP.route('compare', render);
})(window.BP);
