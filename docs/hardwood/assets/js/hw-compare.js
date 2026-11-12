/* The Quant Hardwood — Compare players (#/<L>/compare/players/<a>/<b>[/<c>]), on kit v4 "Broadcast" (the Rink
 * compare page is the reference).
 *
 * Two or three players side by side on the one metric set the player card uses (HW.ui.MSET, after the metrics
 * spec): value, a percentile bar against the role (guards, wings or bigs; qualified players), the better value in
 * bold. Players of the same role are ranked against that role; a guard with a
 * big falls back to every qualified player on the shared headline metrics, and the page says so. Below: where each
 * one sits in the peer distribution of a chosen metric. With one player picked, the other is his most similar
 * player this season (the spec's weighted method within the role); with none, the two best by total impact. Teams (#/<L>/compare/teams/...) and ?view=all open
 * the full pre-redesign comparison (every catalogue metric, radar, shot charts, careers).
 *
 * v4 (Broadcast): the title asks the question ("Jokic, Wembanyama or Gilgeous-Alexander?"); two players are the tale
 * of the tape in their team colours (bars = percentile, the better number solid), three a table with the best value
 * under the volt stroke; a verdict under it names what each player does best (QK.verdicts, the type from
 * HW.ui.ARCHETYPE).
 *
 * Reads <L>/<S>/players.json (the catalogue), <L>/<S>/value.json (roles) and <L>/players/<pid>.json (similar). */
(function (HW) {
'use strict';

const U = HW.ui, esc = HW.esc, isNum = HW.isNum;
const ECOL = ['var(--wp-a)', 'var(--wp-b)', 'var(--c-5)'];

/* The season as a query part ('s=2026'), empty for the current season. */
function sPart(L, S) { return S && Number(S) !== Number(HW.currentSeason(L)) ? 's=' + S : ''; }
function qs(parts) { const p = parts.filter(Boolean); return p.length ? '?' + p.join('&') : ''; }
/* The Scouting Room's tab strip (hw-scout.js draws the same one): the room, Compare, Progression. ?view=all keeps the
   classic every-metric comparison under the Compare tab. */
function tabs(L, S, active, ids) {
  const sp = sPart(L, S), path = ids && ids.length ? '/' + ids.map(encodeURIComponent).join('/') : '';
  return [{ key: 'scout', label: 'Scouting Room', href: '#/' + L + '/scout' + qs([sp]) },
    { key: 'compare', label: 'Compare', href: '#/' + L + '/compare/players' + path + qs([sp]) },
    { key: 'prog', label: 'Progression', href: '#/' + L + '/compare/progression' + path }];
}
const ROLES = ['G', 'W', 'B'];
const VAL = 'hpm';   // the site's value metric: total impact
const valOf = p => { const v = ((p || {}).values || {})[VAL]; return isNum(v) ? v : -Infinity; };
/* Players of a role, best first by total impact: the qualified ones, else (early season) everyone in the role by minutes. */
function inRole(P, roles, r, qualOnly) { return Object.keys(P).filter(id => U.roleOf(P[id], id, roles) === r && (!qualOnly || P[id].qualified)); }
function topOf(P, roles, r) {
  const q = inRole(P, roles, r, true).filter(id => isNum((P[id].values || {})[VAL])).sort((a, b) => valOf(P[b]) - valOf(P[a]));
  if (q.length >= 2) return q.slice(0, 2);
  return q.concat(inRole(P, roles, r, false).filter(id => q.indexOf(id) < 0).sort((a, b) => (P[b].min || 0) - (P[a].min || 0))).slice(0, 2);
}
/* The role with the most qualified players: the default chip. */
function mainRole(P, roles) {
  const n = ROLES.map(r => inRole(P, roles, r, true).length);
  return ROLES[n.indexOf(Math.max.apply(null, n))];
}
/* A player's most similar player in his own role this season: the catalogue's similar_role, else the spec's weighted
   method here, else the nearest total impact in the role. */
function simOf(L, cat, roles, id) {
  const P = cat.players, p = P[id];
  if (!p) return null;
  const r = U.roleOf(p, id, roles);
  const sr = (Array.isArray(p.similar_role) ? p.similar_role : []).map(x => String(x.id)).find(x => x !== id && P[x] && U.roleOf(P[x], x, roles) === r);
  if (sr) return sr;
  const sim = U.similarRole(L, cat, roles, id, 1)[0];
  if (sim) return String(sim.id);
  const v0 = valOf(p);
  const pool = inRole(P, roles, r, true).filter(x => x !== id);
  const pick = (pool.length ? pool : inRole(P, roles, r, false).filter(x => x !== id)).filter(x => isNum((P[x].values || {})[VAL]))
    .sort((a, b) => Math.abs(valOf(P[a]) - v0) - Math.abs(valOf(P[b]) - v0))[0];
  return pick || null;
}
function cmpHref(L, S, ids, g) { return '#/' + L + '/compare/players' + (ids && ids.length ? '/' + ids.map(encodeURIComponent).join('/') : '') + qs([g ? 'g=' + g : '', sPart(L, S)]); }
/* "total impact, offensive impact ... and steal rate": the role's headline set in words, from the spec's labels. */
function keyWords(r) {
  const set = U.MSET && U.MSET.roles[r];
  if (!set) return '';
  const w = set.groups.reduce((a, g) => a.concat(g[1]), []).map(k => {
    const l = U.mMeta(k).label.replace(/ \(HPM\)$/, '');
    return /^[A-Z][A-Z]/.test(l) ? l : l.charAt(0).toLowerCase() + l.slice(1);
  });
  return w.length > 1 ? w.slice(0, -1).join(', ') + ' and ' + w[w.length - 1] : w.join('');
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
  const gq = /^[GWB]$/.test(((params.query || {}).g) || '') ? params.query.g : null;
  const body = U.section(el, { title: 'Compare', kicker: U.kicker(L, S), sub: 'Two or three players side by side on the metrics that best describe and predict their play, ranked against their own role. Pick a role for its two best, or type any names.',
    tabs: tabs(L, S, 'compare', ids), active: 'compare' });
  body.innerHTML = QK.skeleton('lines', 6);
  return Promise.all([U.catalogue(L, S), U.roles(L, S)]).then(res => {
    if (!U.alive(el)) return null;
    const cat = res[0].cat, S2 = res[0].S, roles = res[1];
    if (!U.ok(cat) || !Object.keys(cat.players || {}).length) { body.innerHTML = U.card2('Compare', '', QK.empty('The player catalogue is not built yet', 'Try again after the next update.')); return null; }
    const P = cat.players;
    let fill = Promise.resolve(ids.filter(id => P[id]));
    const main = mainRole(P, roles);
    if (!ids.length) {
      /* nobody picked: the two best of the chosen role (?g=), else of the role with the most qualified players */
      fill = Promise.resolve(topOf(P, roles, gq || main));
    } else if (ids.length === 1 && P[ids[0]]) {
      /* one picked: his most similar player in his own role (the player file's similar_role for this season first) */
      const r0 = U.roleOf(P[ids[0]], ids[0], roles);
      fill = HW.load(L + '/players/' + ids[0] + '.json').then(c => {
        const sr = (c && Array.isArray(c.similar_role) ? c.similar_role : []).find(x => Number(x.season) === Number(S2) && P[String(x.id)] && String(x.id) !== ids[0] && U.roleOf(P[String(x.id)], String(x.id), roles) === r0);
        if (sr) return ids.concat([String(sr.id)]);
        const near = simOf(L, cat, roles, ids[0]);
        return near ? ids.concat([near]) : ids;
      }, () => { const near = simOf(L, cat, roles, ids[0]); return near ? ids.concat([near]) : ids; });
    }
    return fill.then(list => { if (U.alive(el)) draw(body, L, S2, list.filter(id => P[id]), cat, roles, S2 !== S, { gq: gq, main: main }); });
  });
}

/* The name boxes: the active role's players first (best first by total impact), then everyone else by name; each
   suggestion carries the team and the role. */
function picker(L, cat, roles, E, act) {
  const P = cat.players;
  const lab = id => P[id].name + ' (' + HW.teamAbbr(L, P[id].team) + ', ' + ((U.ROLE1 || {})[U.roleOf(P[id], id, roles)] || P[id].pos || '') + ')';
  const all = Object.keys(P).filter(id => P[id] && P[id].name && ((P[id].min || 0) >= 100 || P[id].qualified || E.indexOf(id) >= 0));
  const mine = act ? all.filter(id => U.roleOf(P[id], id, roles) === act).sort((a, b) => (P[b].qualified ? 1 : 0) - (P[a].qualified ? 1 : 0) || valOf(P[b]) - valOf(P[a])) : [];
  const rest = all.filter(id => mine.indexOf(id) < 0).sort((a, b) => String(P[a].name).localeCompare(String(P[b].name)));
  const opts = mine.concat(rest).map(id => [id, lab(id)]);
  return pickerHTML(opts, E);
}
function pickerHTML(opts, E) {
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

/* Position first: one chip per role (the spec's peer groups), each opening that role's two best; under it the role and
   its key metrics in words, and an early-season line when the role has few qualified players. */
function roleStrip(L, S, cat, roles, act, E) {
  const P = cat.players;
  const n = {};
  ROLES.forEach(r => { n[r] = inRole(P, roles, r, true).length; });
  const chips = '<div class="qk-chips hw-cmp-roles" role="group" aria-label="Compare within a role">' + ROLES.map(r =>
    '<button type="button" class="qk-chip" data-href="' + esc(cmpHref(L, S, [], r)) + '" aria-pressed="' + (r === act) + '" title="The two best ' + esc(U.ROLE_NAME[r]) + ' by total impact">' +
    esc(U.ROLE[r]) + ' <span class="n">' + n[r] + '</span></button>').join('') + '</div>';
  let line = '';
  if (act) {
    line = '<p class="hw-cmp-gline"><b>' + esc(U.ROLE[act]) + ':</b> ' + esc(keyWords(act)) + ' — the metrics that best describe and predict a ' + esc((U.ROLE1[act] || '').toLowerCase()) + '.</p>';
    if (n[act] < 10) {
      const prev = HW.seasons(L).filter(x => x < Number(S))[0];
      line += '<p class="hw-cmp-thin">Early in the season: only ' + n[act] + ' qualified ' + esc(U.ROLE_NAME[act]) + ' so far; percentiles settle as games are played.' +
        (prev ? ' <a class="qk-link" href="' + esc(cmpHref(L, prev, [], act)) + '">Last season (' + esc(HW.seasonLabel(L, prev)) + ') →</a>' : '') + '</p>';
    }
  } else if (E.length >= 2) {
    /* different roles: offer each player against his own kind */
    const links = E.slice(0, 2).map(id => {
      const r = U.roleOf(P[id], id, roles), sim = simOf(L, cat, roles, id);
      return r && sim ? '<a class="qk-link" href="' + esc(cmpHref(L, S, [id, sim])) + '">Compare ' + esc(QK.surname(P[id].name || '')) + ' with a ' + esc((U.ROLE1[r] || '').toLowerCase()) + ' instead →</a>' : '';
    }).filter(Boolean);
    line = '<p class="hw-cmp-gline"><b>Different roles.</b> Each role has its own key metrics; these players share only a few.' + '</p>' + (links.length ? '<p class="hw-cmp-alt">' + links.join('') + '</p>' : '');
  }
  return '<div class="hw-cmp-head">' + chips + line + '</div>';
}
function wireStrip(body) {
  QK.$$('.hw-cmp-roles [data-href]', body).forEach(b => b.addEventListener('click', () => HW.go(b.getAttribute('data-href'))));
}

function draw(body, L, S, E, cat, roles, fellBack, ctx) {
  const P = cat.players;
  const c = ctx || {};
  const rs = E.map(id => U.roleOf(P[id], id, roles));
  const same = rs[0] && rs.every(r => r === rs[0]);
  const role = same ? rs[0] : null;
  const act = E.length >= 2 ? role : (rs[0] || c.gq || c.main || null);
  const pk = picker(L, cat, roles, E, act || rs[0] || c.main);
  const strip = roleStrip(L, S, cat, roles, act, E);
  const more = '<p class="qk-caption hw-cmp-more">More ways to compare: <a class="qk-link" href="' + esc('#/' + L + '/compare/players' + (E.length ? '/' + E.map(encodeURIComponent).join('/') : '') + qs(['view=all', sPart(L, S)])) + '">every metric, radar and shot charts</a> · <a class="qk-link" href="' + esc('#/' + L + '/compare/progression' + (E.length ? '/' + E.map(encodeURIComponent).join('/') : '')) + '">progression, season by season</a> · <a class="qk-link" href="' + esc('#/' + L + '/teams' + qs([sPart(L, S)]) + '#tm-h2h') + '">teams head to head</a></p>';
  if (E.length < 2) {
    body.innerHTML = U.card2('Pick players', 'Choose a role for its two best, or type two or three names', strip + pk.html + QK.empty('Pick at least two players', 'Type a name in each box.'));
    wire(body, L, S, pk); wireStrip(body); return;
  }
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
      const ours = HW.ours ? HW.ours.of(k) : null;
      return { key: k, label: m.label, tip: m.desc + (ours ? ' Our model: ' + ours.name + '.' : ''), better: m.better, values: E.map(id => (P[id].values || {})[k]), pctls: E.map(id => pc(id, k)), fmt: x => U.fmtM(k, x),
        dfmt: pctFmt ? (x => (x > 0 ? '+' : x < 0 ? '−' : '±') + Math.abs(x * 100).toFixed(1) + ' pts') : null };
    })
  }));
  /* v4: two players draw the tale of the tape in their team colours (QK.tape via QK.compareView); three keep the table */
  const ents = E.map(id => { const p = P[id]; return { name: p.name, href: HW.playerHref(L, id, S), abbr: QK.surname(p.name || ''), short: QK.surname(p.name || ''), colour: HW.teamColourRaw(L, p.team), alt: HW.teamAlt(L, p.team),
    sub: [HW.teamAbbr(L, p.team), (U.ROLE1 || {})[U.roleOf(p, id, roles)] || p.pos, (p.gp || 0) + ' GP', Number(Math.round(p.min || 0)).toLocaleString('en-GB') + ' min'].join(' · ') }; });
  const short = E.filter(id => !P[id].qualified).map(id => P[id].name);
  /* verdicts: for each player, the metric where the player's percentile beats the others' by the most */
  const sn = E.map(id => QK.surname(P[id].name || ''));
  const verd = E.map((id, i) => {
    let bestRow = null, bestD = 0;
    /* the headline groups only: a standout on a 'More' row (a guard's block rate) is not what he is */
    groups.filter(g => g.label !== 'More').forEach(g => g.rows.forEach(r => {
      const mine = r.pctls[i]; if (!isNum(mine)) return;
      const d = mine - Math.max.apply(null, r.pctls.filter((_, j) => j !== i).map(x => (isNum(x) ? x : 0)));
      if (d > bestD) { bestD = d; bestRow = r; }
    }));
    return bestRow ? { title: U.ARCHETYPE[bestRow.key] || 'The standout', who: sn[i], text: 'best of the ' + E.length + ' on ' + bestRow.label.charAt(0).toLowerCase() + bestRow.label.slice(1) + ' (' + bestRow.fmt(bestRow.values[i]) + ', ' + QK.ordinal(Math.round(bestRow.pctls[i])) + ' percentile).' } : null;
  });
  const q = sn.length === 2 ? sn[0] + ' or ' + sn[1] + '?' : sn.slice(0, -1).join(', ') + ' or ' + sn[sn.length - 1] + '?';
  body.innerHTML = U.card2('Players', 'Ranked against ' + esc(peer) + ' in ' + esc(HW.seasonLabel(L, S)) + (fellBack ? ' (the latest season with a catalogue)' : ''), strip + pk.html) +
    '<section class="qk-section" style="margin-top:var(--sp-8)">' + QK.sectionHead({ kicker: E.length === 2 ? 'Tale of the tape' : 'Side by side', title: q,
      sub: E.length === 2 ? 'Bar length = percentile against ' + peer + ' (100 = best). The better number in each row is solid.' : 'Value and percentile against ' + peer + ' (100 = best). The best in each row is highlighted.' }) +
    U.card2(E.length + ' players, one metric set', 'The headline set for the role from our metrics spec: stable and predictive rates first',
      QK.compareView({ entities: ents, groups: groups }) + QK.verdicts(verd) +
      (short.length ? '<p class="qk-caption">' + esc(short.join(', ')) + (short.length > 1 ? ' are' : ' is') + ' short of the minutes floor (' + Number(cat.min_floor || 0).toLocaleString('en-GB') + '): read the percentiles as early.</p>' : '') +
      (!same ? '<p class="qk-caption">Different roles: percentiles are against every qualified player, on the headline metrics all three roles share, so role effects (bigs rebound more, guards pass more) stay in.</p>' : '')) + '</section>' +
    '<section class="qk-section">' + U.card2('Where they sit', 'The qualified ' + esc(same ? U.ROLE_NAME[role] : 'players') + ' this season, with each player marked', '<div class="qk-seg" id="cmp-dist-m" role="group" aria-label="Metric" style="margin-bottom:10px"></div>' + U.chart('cmp-dist', 260, 'Peer distribution with the players marked')) + more + '</section>';
  wire(body, L, S, pk); wireStrip(body);
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
