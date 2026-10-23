/* The Quant Hardwood — Compare players (#/<L>/compare/players/<a>/<b>[/<c>]), on Design System 2.0 (the Rink
 * compare page is the reference).
 *
 * Two or three players side by side on the one metric set the player card uses (HW.ui.MSET, after the metrics
 * spec): value, a percentile bar against the role (guards, wings or bigs; qualified players), the better value in
 * bold, and for two players the difference. Players of the same role are ranked against that role; a guard with a
 * big falls back to every qualified player on the shared headline metrics, and the page says so. Below: where each
 * one sits in the peer distribution of a chosen metric. With one player picked, the other is his most similar
 * player this season (the spec's weighted method within the role); with none, the two best by total impact. Teams (#/<L>/compare/teams/...) and ?view=all open
 * the full pre-redesign comparison (every catalogue metric, radar, shot charts, careers).
 *
 * v3 (Matchday): the title asks the question ("Jokic, Wembanyama or Gilgeous-Alexander?"), the best value in each row
 * sits under the sun highlighter, the percentiles are coloured pills, and a verdict under the table names what each
 * player does best (QK.verdicts, the type from HW.ui.ARCHETYPE).
 *
 * Reads <L>/<S>/players.json (the catalogue), <L>/<S>/value.json (roles) and <L>/players/<pid>.json (similar). */
(function (HW) {
'use strict';

const U = HW.ui, esc = HW.esc, isNum = HW.isNum;
const ECOL = ['var(--wp-a)', 'var(--wp-b)', 'var(--c-5)'];

function tabs(L, S, active, ids) {
  const sq = HW.sq(L, S);
  const base = '#/' + L + '/compare/players' + (ids && ids.length ? '/' + ids.map(encodeURIComponent).join('/') : '');
  return [{ key: 'compare', label: 'Players, side by side', href: base + (sq ? '?' + sq : '') },
    { key: 'all', label: 'Every metric (classic)', href: base + '?view=all' + (sq ? '&' + sq : '') },
    { key: 'teams', label: 'Teams', href: '#/' + L + '/compare/teams' + (sq ? '?' + sq : '') }];
}

/* The percentile of player id among the pool (qualified players of the given role, or all), oriented. */
function pctIn(cat, roles, pool, id, k) {
  const P = cat.players, v = ((P[id] || {}).values || {})[k];
  if (!isNum(v)) return null;
  const arr = pool.map(x => (x.values || {})[k]).filter(isNum);
  if (arr.length < 5) return null;
  let lo = 0, eq = 0;
  arr.forEach(x => { if (x < v) lo++; else if (x === v) eq++; });
  const pc = 100 * (lo + 0.5 * eq) / arr.length;
  return Math.round(U.mMeta(k).better === 'low' ? 100 - pc : pc);
}

function render(el, params) {
  const L = U.L(params), S = U.S(params);
  let ids = [params.a, params.b].concat(params.rest || []).filter(Boolean).map(String).slice(0, 3);
  const body = U.section(el, { title: 'Compare', kicker: U.kicker(L, S), sub: 'Two or three players side by side on the metrics that best describe and predict their play, ranked against their own role.',
    tabs: tabs(L, S, 'compare', ids), active: 'compare' });
  body.innerHTML = QK.skeleton('lines', 6);
  return Promise.all([U.catalogue(L, S), U.roles(L, S)]).then(res => {
    if (!U.alive(el)) return null;
    const cat = res[0].cat, S2 = res[0].S, roles = res[1];
    if (!U.ok(cat) || !Object.keys(cat.players || {}).length) { body.innerHTML = U.card2('Compare', '', QK.empty('The player catalogue is not built yet', 'Try again after the next update.')); return null; }
    const P = cat.players;
    let fill = Promise.resolve(ids.filter(id => P[id]));
    if (!ids.length) {
      const top = Object.keys(P).filter(id => P[id].qualified && isNum((P[id].values || {}).hpm)).sort((a, b) => P[b].values.hpm - P[a].values.hpm).slice(0, 2);
      fill = Promise.resolve(top);
    } else if (ids.length === 1 && P[ids[0]]) {
      fill = HW.load(L + '/players/' + ids[0] + '.json').then(c => {
        const sr = (c && Array.isArray(c.similar_role) ? c.similar_role : []).find(x => Number(x.season) === Number(S2) && P[String(x.id)] && String(x.id) !== ids[0]);
        if (sr) return ids.concat([String(sr.id)]);
        const sim = U.similarRole(L, cat, roles, ids[0], 1)[0];
        if (sim) return ids.concat([sim.id]);
        const r = U.roleOf(P[ids[0]], ids[0], roles), v0 = (P[ids[0]].values || {}).hpm;
        const near = Object.keys(P).filter(id => id !== ids[0] && P[id].qualified && U.roleOf(P[id], id, roles) === r && isNum((P[id].values || {}).hpm)).sort((a, b) => Math.abs(P[a].values.hpm - v0) - Math.abs(P[b].values.hpm - v0))[0];
        return near ? ids.concat([near]) : ids;
      });
    }
    return fill.then(list => { if (U.alive(el)) draw(body, L, S2, list.filter(id => P[id]), cat, roles, S2 !== S); });
  });
}

function picker(L, cat, roles, E) {
  const P = cat.players;
  const opts = Object.keys(P).filter(id => P[id] && P[id].name && (P[id].min || 0) >= 100).map(id => [id, P[id].name + ' (' + HW.teamAbbr(L, P[id].team) + ', ' + ((U.ROLE1 || {})[U.roleOf(P[id], id, roles)] || P[id].pos || '') + ')'])
    .sort((a, b) => a[1].localeCompare(b[1]));
  const lab = id => { const o = opts.find(x => x[0] === id); return o ? o[1] : ''; };
  return { opts: opts, html: '<div class="hw-cmp-pick">' + [0, 1, 2].map(i => '<label class="hw-cmp-slot" style="--ec:' + ECOL[i] + '"><span class="qk-kicker">' + (i === 2 ? 'Third player (optional)' : 'Player ' + (i + 1)) + '</span>' +
    '<input class="qk-input" list="cmp-names" data-i="' + i + '" value="' + esc(E[i] ? lab(E[i]) : '') + '" placeholder="Type a name" autocomplete="off"></label>').join('') +
    '<datalist id="cmp-names">' + opts.map(o => '<option value="' + esc(o[1]) + '"></option>').join('') + '</datalist></div>' };
}

function wire(body, L, S, pk) {
  body.querySelectorAll('.hw-cmp-pick input').forEach(inp => inp.addEventListener('change', () => {
    const ids = [0, 1, 2].map(i => {
      const v = (body.querySelector('.hw-cmp-pick input[data-i="' + i + '"]') || {}).value || '';
      const hit = pk.opts.find(o => o[1] === v) || pk.opts.find(o => v && o[1].toLowerCase().indexOf(v.toLowerCase()) === 0);
      return hit ? hit[0] : null;
    }).filter(Boolean);
    if (ids.length) HW.go(HW.href(L, 'compare/players/' + ids.map(encodeURIComponent).join('/'), S));
  }));
}

function draw(body, L, S, E, cat, roles, fellBack) {
  const P = cat.players;
  const pk = picker(L, cat, roles, E);
  if (E.length < 2) {
    body.innerHTML = U.card2('Pick players', 'Choose two or three players to compare', pk.html + QK.empty('Pick at least two players', 'Type a name in each box.'));
    wire(body, L, S, pk); return;
  }
  const rs = E.map(id => U.roleOf(P[id], id, roles));
  const same = rs[0] && rs.every(r => r === rs[0]);
  const role = same ? rs[0] : null;
  const set = U.MSET && U.MSET.roles[role || 'W'];
  const pool = same ? U.rolePeers(cat, roles, role) : Object.keys(P).filter(id => P[id].qualified).map(id => Object.assign({ id: id }, P[id]));
  const peer = same ? U.peerName(L, role) : 'every qualified ' + HW.leagueName(L) + ' player';
  const pc = (id, k) => (same ? U.rolePctl(cat, roles, id, k) : pctIn(cat, roles, pool, id, k));
  const keysOf = g => g[1];
  // mixed roles: the headline keys every role shares
  const shared = same ? null : ['G', 'W', 'B'].map(r => U.MSET.roles[r].groups.reduce((a, g) => a.concat(g[1]), [])).reduce((a, b) => a.filter(k => b.indexOf(k) >= 0));
  const groups = (same ? set.groups.concat([['More', set.more]]) : [['Shared headline metrics', shared]]).map(g => ({
    label: g[0],
    rows: keysOf(g).map(k => {
      const m = U.mMeta(k), pctFmt = m.fmt === 'pct';
      return { key: k, label: m.label, tip: m.desc, better: m.better, values: E.map(id => (P[id].values || {})[k]), pctls: E.map(id => pc(id, k)), fmt: x => U.fmtM(k, x),
        dfmt: pctFmt ? (x => (x > 0 ? '+' : x < 0 ? '−' : '±') + Math.abs(x * 100).toFixed(1) + ' pts') : null };
    })
  }));
  const ents = E.map(id => { const p = P[id]; return { name: p.name, href: HW.playerHref(L, id, S), abbr: QK.surname(p.name || ''),
    sub: [HW.teamAbbr(L, p.team), (U.ROLE1 || {})[U.roleOf(p, id, roles)] || p.pos, (p.gp || 0) + ' GP', Number(Math.round(p.min || 0)).toLocaleString('en-GB') + ' min'].join(' · ') }; });
  const short = E.filter(id => !P[id].qualified).map(id => P[id].name);
  /* verdicts: for each player, the metric where the player's percentile beats the others' by the most */
  const sn = E.map(id => QK.surname(P[id].name || ''));
  const verd = E.map((id, i) => {
    let bestRow = null, bestD = 0;
    groups.forEach(g => g.rows.forEach(r => {
      const mine = r.pctls[i]; if (!isNum(mine)) return;
      const d = mine - Math.max.apply(null, r.pctls.filter((_, j) => j !== i).map(x => (isNum(x) ? x : 0)));
      if (d > bestD) { bestD = d; bestRow = r; }
    }));
    return bestRow ? { title: U.ARCHETYPE[bestRow.key] || 'The standout', who: sn[i], text: 'best of the ' + E.length + ' on ' + bestRow.label.charAt(0).toLowerCase() + bestRow.label.slice(1) + ' (' + bestRow.fmt(bestRow.values[i]) + ', ' + QK.ordinal(Math.round(bestRow.pctls[i])) + ' percentile).' } : null;
  });
  const q = sn.length === 2 ? sn[0] + ' or ' + sn[1] + '?' : sn.slice(0, -1).join(', ') + ' or ' + sn[sn.length - 1] + '?';
  body.innerHTML = U.card2('Players', 'Ranked against ' + esc(peer) + ' in ' + esc(HW.seasonLabel(L, S)) + (fellBack ? ' (the latest season with a catalogue)' : ''), pk.html) +
    '<section class="qk-section" style="margin-top:var(--sp-8)">' + QK.sectionHead({ kicker: 'Side by side', title: q,
      sub: 'Value and percentile against ' + peer + ' (100 = best). The best in each row is highlighted' + (E.length === 2 ? '; the last column is ' + sn[0] + ' minus ' + sn[1] + ', green when ' + sn[0] + ' is better.' : '.') }) +
    U.card2(E.length + ' players, one metric set', 'The headline set for the role from our metrics spec: stable and predictive rates first',
      QK.compareView({ entities: ents, groups: groups }) + QK.verdicts(verd) +
      (short.length ? '<p class="qk-caption">' + esc(short.join(', ')) + (short.length > 1 ? ' are' : ' is') + ' short of the minutes floor (' + Number(cat.min_floor || 0).toLocaleString('en-GB') + '): read the percentiles as early.</p>' : '') +
      (!same ? '<p class="qk-caption">Different roles: percentiles are against every qualified player, on the headline metrics all three roles share, so role effects (bigs rebound more, guards pass more) stay in.</p>' : '')) + '</section>' +
    '<section class="qk-section">' + U.card2('Where they sit', 'The qualified ' + esc(same ? U.ROLE_NAME[role] : 'players') + ' this season, with each player marked', '<div class="qk-seg" id="cmp-dist-m" role="group" aria-label="Metric" style="margin-bottom:10px"></div>' + U.chart('cmp-dist', 260, 'Peer distribution with the players marked')) + '</section>';
  wire(body, L, S, pk);
  const opts = (same ? set.groups.reduce((a, g) => a.concat(g[1]), []) : shared).slice(0, 6);
  const seg = body.querySelector('#cmp-dist-m');
  seg.innerHTML = opts.map((o, i) => '<button type="button" aria-pressed="' + (i === 0) + '" data-value="' + o + '">' + esc(U.mMeta(o).label.replace(/ \(HPM\)$/, '')) + '</button>').join('');
  const dd = key => {
    const m = U.mMeta(key);
    const vals = pool.map(x => (x.values || {})[key]).filter(isNum).sort((a, b) => a - b);
    if (vals.length < 5) { body.querySelector('#cmp-dist').innerHTML = QK.empty('Too few qualified peers yet'); return; }
    QKC.distribution('#cmp-dist', { values: vals, binCount: 22, lowerBetter: m.better === 'low', fmt: x => U.fmtM(key, x), colorBy: 'flat', xName: m.label + ' · ' + vals.length + ' qualified peers', yName: 'Players',
      marks: E.map((id, i) => ({ x: (P[id].values || {})[key], label: QK.surname(P[id].name || ''), color: ['wpA', 'wpB', 'c5'][i] })).filter(x => isNum(x.x)), label: 'Distribution of ' + m.label });
  };
  if (opts.length) { dd(opts[0]); QK.seg(seg, dd); }
  HW.setMeta('');
}

HW.compareV2 = render;
HW.compareTabs = tabs;
})(window.HW);
