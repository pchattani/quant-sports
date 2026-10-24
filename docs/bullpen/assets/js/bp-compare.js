/* The Quant Bullpen — compare (#/compare/<a>/<b>?c=<third>), on kit v4 "Broadcast" (the Rink compare page is the
 * reference): two or three hitters or pitchers side by side on the spec's metric set (BP.ui.SETS), the better value
 * solid, and where each sits in the peer distribution (loaded on request).
 *
 * Peers: when every player is in the same position group (hitters) or role (pitchers), the percentiles are against that
 * group (pct_role) and the set is the group's; otherwise against all MLB hitters (or all starters / relievers mixed:
 * the payload's league-wide pct) on the all-hitters set, and the page says so. Data: data/players/<pid>.json for each
 * (the current season's values, pct and pct_role are in the player file), glossary.json; the season catalogue loads only
 * for the distribution. Teams, other levels and seasons, and the classic every-metric view: ?view=classic.
 *
 * v4 (Broadcast): the title asks the question ("Judge, Ohtani or Soto?"); two players are the tale of the tape in their
 * club colours (bars = percentile, the better number solid), three a table with the best value under the volt stroke;
 * a verdict under it names what each player does best (QK.verdicts, the type from BP.ui.ARCHETYPE). */
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

function render(el, params, state) {
  const q = params.query || {};
  const L = params.level, S = params.season;
  const ids = [params.a, params.b, q.c].filter(x => x && /^\d+$/.test(String(x)));
  if (q.view === 'classic' || L === 'npb' || (params.a && /^t/.test(String(params.a)))) return LEG ? LEG(el, params, state) : null;
  if (ids.length) KIND = BP.isPitcher(ids[0]) && String(BP.player(ids[0]).pos).toUpperCase() !== 'TWP' ? 'pitcher' : 'hitter';
  if (q.kind === 'pitcher' || q.kind === 'hitter') KIND = q.kind;
  el.innerHTML = QK.skeleton('card', 2);
  return Promise.all(ids.map(id => BP.load('players/' + id + '.json')).concat([U.gloss(), BP.loadYear('season.json', L, S)])).then(res => {
    if (!U.alive(el)) return;
    const gl = res[ids.length], season = BP.ok(res[ids.length + 1]) ? res[ids.length + 1] : null;
    const P = ids.map((id, i) => ({ id: id, p: BP.ok(res[i]) ? res[i] : null })).map(x => Object.assign(x, { b: blockOf(x.p, KIND, L, S) }));
    const E = P.filter(x => x.b && x.b.values);
    const sets = E.map(x => U.setFor(KIND, x.b));
    const same = sets.length && sets.every(s => s === sets[0]);
    const setKey = same ? sets[0] : (KIND === 'pitcher' ? 'SP' : 'ALL');
    const peer = same ? U.peerName(setKey) : (KIND === 'pitcher' ? 'all MLB pitchers' : 'all MLB hitters');
    const why = same ? '' : ' (they play different ' + (KIND === 'pitcher' ? 'roles' : 'positions') + ', so the percentiles are league-wide)';
    const href = (a, b, c) => BP.compareHref(a, b) + (c ? '?c=' + encodeURIComponent(c) : '');
    const sn = E.map(x => BP.playerSurname(x.id));
    let h = U.head({ kicker: 'Compare · ' + BP.levelName(L) + ' ' + S, title: E.length >= 2 ? sn.slice(0, -1).join(', ') + ' or ' + sn[sn.length - 1] + '?' : 'Compare players',
      sub: 'Two or three ' + (KIND === 'pitcher' ? 'pitchers' : 'hitters') + ' on the metrics that are stable from year to year and predict next season, chosen for their position or role.',
      actions: U.seg('cmp-kind', 'Kind', [['hitter', 'Hitters'], ['pitcher', 'Pitchers']], KIND) + '<a class="qk-btn" href="' + esc(href(params.a || '', params.b || '', q.c) + (q.c ? '&' : '?') + 'view=classic') + '">Every metric (classic)</a>' }) +
      '<section class="qk-card"><div class="qk-card-body"><div class="bp-cmp-pick">' + [0, 1, 2].map(i => '<div class="bp-cmp-slot" style="--ec:' + COLS[i] + '"><span class="qk-kicker" style="margin:0">' + (i === 2 ? 'Third (optional)' : i ? 'Second' : 'First') + '</span><div id="cmp-p' + i + '"></div></div>').join('') + '</div></div></section>';
    if (E.length < 2) h += '<div style="margin-top:var(--sp-4)">' + QK.empty('Pick two ' + KIND + 's', ids.length && !E.length ? 'No ' + S + ' ' + BP.levelName(L) + ' ' + KIND + ' season on file for that player: try the classic view.' : 'Type a name above.') + '</div>';
    else {
      const which = 'head';
      const flat = U.flat(setKey, which).concat(U.flat(setKey, 'more').filter(x => ['war', 'xfip', 'ra9', 'fip', 'iso', 'ev90', 'whiff_pct', 'oaa', 'location_plus'].indexOf(x[0]) >= 0)).filter(x => same || !U.FIELDING[x[0]]);
      const groups = [];
      ((U.SETS[setKey] || {})[which] || []).forEach(g => groups.push({ label: g[0], keys: g[1].map(x => x[0]) }));
      const extra = flat.filter(x => !groups.some(g => g.keys.indexOf(x[0]) >= 0)).map(x => x[0]);
      if (extra.length) groups.push({ label: 'More', keys: extra });
      const pk = same ? 'pct_role' : 'pct';
      const cgroups = groups.map(g => ({ label: g.label, rows: g.keys.map(k => {
        const m = U.metaOf(KIND, k, gl);
        return { key: k, label: m.label, tip: m.tip, values: E.map(x => (x.b.values || {})[k]), pctls: E.map(x => (U.metricOk(x.b, k, same ? setKey : 'ALL', null) && U.meets(x.b, U.setFor(KIND, x.b), null) ? (x.b[pk] || {})[k] : null)), better: m.lower ? 'low' : 'high', fmt: val => U.fmtBy(m, val) };
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
        '<div class="qk-span-5"><div class="bp-stack">' + U.card2('Where they sit', 'Every ' + esc(peer.replace(/^MLB /, '')) + ' past the floor this season', U.seg('cmp-dseg', 'Metric', flat.slice(0, 5).map(x => [x[0], U.metaOf(KIND, x[0], gl).label]), '') + '<div id="cmp-dist" style="margin-top:10px">' + QK.empty('Pick a metric', 'The peer group loads on request (the season catalogue is several megabytes).') + '</div>') +
        U.card2('Samples', 'Percentiles need ' + (U.floorOf(setKey, null) || {}).full + '+ ' + ((U.floorOf(setKey, null) || {}).unit || '') + ' over a full season (prorated in season)', '<ul class="bp-list">' + E.map((x, i) => '<li><span class="bp-dot" style="background:' + COLS[i] + '"></span>' + U.playerEnt(x.id, L, null, KIND) + '<span class="v" style="font:600 var(--fs-xs) var(--font-num)">' + esc(U.sampleLine(x.b, KIND, U.setFor(KIND, x.b), null).split(' · peers')[0]) + '</span></li>').join('') + '</ul>', { flush: true }) +
        '</div></div></div></section>';
    }
    el.innerHTML = h;
    QK.seg(el.querySelector('#cmp-kind'), v => { KIND = v; location.hash = '#/compare?kind=' + v; });
    const cur = [params.a || '', params.b || '', q.c || ''];
    [0, 1, 2].forEach(i => {
      const host = el.querySelector('#cmp-p' + i);
      if (!host || !BP.gk || !BP.gk.picker) return;
      BP.gk.picker(host, { value: cur[i] || null, label: cur[i] ? BP.playerName(cur[i]) : '', placeholder: 'Type a ' + KIND + '…',
        filter: id => (KIND === 'pitcher' ? BP.isPitcher(id) : (!BP.isPitcher(id) || String(BP.player(id).pos).toUpperCase() === 'TWP')),
        onPick: id => { const n = cur.slice(); n[i] = id; location.hash = href(n[0], n[1], n[2]); } });
    });
    const dseg = el.querySelector('#cmp-dseg');
    if (dseg) QK.seg(dseg, key => {
      const box = el.querySelector('#cmp-dist');
      box.innerHTML = QK.skeleton('chart', 1);
      BP.loadYear(KIND === 'pitcher' ? 'pitchers.json' : 'hitters.json', L, S).then(cat => {
        if (!U.alive(el)) return;
        if (!BP.ok(cat) || !cat.players) { box.innerHTML = QK.empty('Not available', 'The season catalogue did not load.'); return; }
        const peers = Object.keys(cat.players).map(id => cat.players[id]).filter(x => x && (!same || U.setFor(KIND, x) === setKey) && U.meets(x, U.setFor(KIND, x), cat.team_games));
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
