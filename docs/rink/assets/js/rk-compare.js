/* The Quant Rink — Compare (#/compare/<a>/<b>[/<c>]), the v4 reference compare page.
 *
 * Two or three skaters (or goalies) side by side on the one metric set the player card uses (RK.ui.SK_SET / G_SET,
 * after docs/METRICS_SPEC.md): value, a percentile bar against the position group, the better value in bold, and
 * for two players the difference. Players from the same position group are ranked against that group (pct_pos);
 * a forward with a defenceman falls back to all skaters, and the page says so. Below: where each one sits in the
 * peer distribution of a chosen metric. With one player picked, the other is his most similar player; with none,
 * the two points leaders. Teams (t:TOR) and ?view=all open the full pre-redesign comparison (every metric).
 *
 * v4 (Broadcast): the title asks the question ("MacKinnon, McDavid or Kucherov?"); two players are the tale of the
 * tape in their team colours (bars = percentile, the better number solid), three a table with the best value under the
 * volt stroke; a verdict under it names what each player does best (QK.verdicts, the archetype from RK.ui.ARCHETYPE).
 *
 * Position first (12 Nov): chips Forwards / Defence / Goalies (the spec's peer groups) load the group's top two
 * qualified players by value (GAR for skaters, GSAx for goalies; #/compare?g=F|D|G); the active chip is the group on
 * screen and a line under the chips names its headline metrics. Nobody picked: the top two forwards. A forward with a
 * defenceman (or a skater with a goalie) gets "Compare <A> with a <group> instead" links; a group with fewer than ten
 * qualified players says so and offers last season. The name list offers the active group first.
 *
 * Reads <S>/skaters.json and <S>/goalies.json (and players/<pid>.json for the most similar player). */
(function (RK) {
'use strict';

const U = RK.ui, esc = RK.esc, isNum = RK.isNum;
const teamId = s => /^t:?[A-Za-z]{2,3}$/.test(String(s || '')) || /^[A-Z]{2,3}$/.test(String(s || ''));
const ECOL = ['var(--wp-a)', 'var(--wp-b)', 'var(--c-5)'];

function head(el, S, active) {
  const sq = U.sq(S) ? '?' + U.sq(S) : '';
  return U.section(el, { section: 'scout', title: 'Compare', sub: 'Two or three players side by side on the metrics that best describe and predict their play, ranked against their own position group.',
    tabs: [{ key: 'lab', label: 'Scouting Room', href: '#/scout' + sq }, { key: 'compare', label: 'Compare', href: '#/compare' + sq }, { key: 'prog', label: 'Progression', href: '#/compare/progression' }, { key: 'all', label: 'Every metric (classic)', href: '#/compare?view=all' }], active: active });
}

/* ── peer groups (12 Nov) ──────────────────────────────────────────────────────────────────────────── */
const GRPS = [['F', 'Forwards', 'forward'], ['D', 'Defence', 'defenceman'], ['G', 'Goalies', 'goalie']];
const gOf = e => (e.kind === 'G' ? 'G' : (e.p.group === 'D' ? 'D' : 'F'));
const valKey = g => (g === 'G' ? 'gsax' : 'gar');
/* the group's qualified players, best value first: [id] */
function ranked(sk, gk, g) {
  const cat = g === 'G' ? gk : sk;
  if (!cat) return [];
  const k = valKey(g), v = id => ((cat.players[id].values || {})[k]);
  return Object.keys(cat.players).filter(id => { const p = cat.players[id]; return p && p.qualified && (g === 'G' || (p.group === 'D' ? 'D' : 'F') === g) && isNum(v(id)); })
    .sort((a, b) => v(b) - v(a));
}
/* his most similar qualified player in his own group (the group's headline metrics) */
function nearestIn(sk, gk, e) {
  const g = gOf(e), cat = g === 'G' ? gk : sk;
  const pool = ranked(sk, gk, g).map(id => Object.assign({ id: id }, cat.players[id]));
  const me = pool.filter(x => x.id === e.id)[0] || Object.assign({ id: e.id }, e.p);
  if (me && pool.indexOf(me) < 0) pool.push(me);
  const keys = (U.SETS[g] || []).reduce((a, x) => a.concat(x[1].map(y => y[0])), []);
  const near = QK.within && QK.within.similar ? QK.within.similar(pool, me, keys, (r, k) => { const x = (r.values || {})[k]; return isNum(x) ? x : null; }, 1) : [];
  return near.length ? near[0].row.id : (ranked(sk, gk, g).filter(id => id !== e.id)[0] || null);
}
function prevSeason(S) { const y = Number(String(S).slice(0, 4)); return y > 2000 ? String(y - 1) + String(y) : null; }
function groupStrip(sk, gk, S, active, cross) {
  const sq = U.sq(S);
  const gi = GRPS.filter(x => x[0] === active)[0];
  const words = gi ? (U.SETS[active] || []).reduce((a, x) => a.concat(x[1].map(y => y[0])), []).map(k => { const l = (U.SPEC[k] || {}).label || k; return /^[A-Z][a-z]/.test(l) ? l.charAt(0).toLowerCase() + l.slice(1) : l; }) : [];
  const n = gi ? ranked(sk, gk, active).length : null, pv = prevSeason(S);
  return '<div class="cmp-groups"><div class="qk-chips scroll" role="group" aria-label="Position">' + GRPS.map(x => '<button type="button" class="qk-chip" data-cmp-go="' + esc('#/compare?g=' + x[0] + (sq ? '&' + sq : '')) + '" aria-pressed="' + (x[0] === active ? 'true' : 'false') + '">' + x[1] + '</button>').join('') + '</div>' +
    (gi ? '<p class="cmp-gline"><b>' + esc(U.GROUP_NAME[active].replace(/^NHL /, '').replace(/^./, c => c.toUpperCase())) + ':</b> ' + esc(words.length > 1 ? words.slice(0, -1).join(', ') + ' and ' + words[words.length - 1] : words.join('')) + ' — the metrics that best describe and predict a ' + gi[2] + '.</p>' : cross ? '<p class="cmp-gline">' + esc(cross) + '</p>' : '') +
    (gi && n < 10 ? '<p class="cmp-thin">Early in the season: only ' + n + ' qualified ' + esc(U.PEER_SHORT[active]) + ' so far; percentiles settle as games are played.' + (pv ? ' <a href="' + esc('#/compare?g=' + active + '&s=' + pv) + '">Last season (' + esc(RK.seasonLabel(pv)) + ')</a>' : '') + '</p>' : '') + '</div>';
}

function render(el, params, state) {
  if (params.a === 'progression' && RK.progression) return RK.progression.compare(el, params);  /* #/compare/progression/<ids> (rk-progression.js) */
  const S = params.season || RK.currentSeason();
  let ids = [params.a, params.b].concat(params.rest || []).filter(Boolean).map(String).slice(0, 3);
  const all = ((params.query || {}).view) === 'all';
  const body = head(el, S, all ? 'all' : 'compare');
  if (all || ids.some(teamId)) return U.legacy('compare', body, params, state);
  body.innerHTML = QK.skeleton('lines', 6);
  return Promise.all([RK.loadYear('skaters.json', S), RK.loadYear('goalies.json', S)]).then(res => {
    if (!U.alive(el)) return;
    const sk = RK.ok(res[0]) ? res[0] : null, gk = RK.ok(res[1]) ? res[1] : null;
    if (!sk) { body.innerHTML = U.card2('Compare', '', QK.empty('The skater catalogue is not built yet', 'Try again after the next update.')); return; }
    const find = id => (sk.players[id] ? { cat: sk, p: sk.players[id], kind: 'S' } : gk && gk.players[id] ? { cat: gk, p: gk.players[id], kind: 'G' } : null);
    let fill = Promise.resolve(ids);
    const gq = String((params.query || {}).g || '').toUpperCase();
    if (!ids.length) {
      /* a chip (?g=), else the forwards: the group's top two by value */
      const g = ['F', 'D', 'G'].indexOf(gq) >= 0 && ranked(sk, gk, gq).length >= 2 ? gq : 'F';
      let top = ranked(sk, gk, g).slice(0, 2);
      if (top.length < 2) top = (((RK.index() || {}).leaders || {}).s_p || []).slice(0, 2).map(x => String(x[0]));
      fill = Promise.resolve(top);
    } else if (ids.length === 1) {
      /* one picked: his most similar player in his own group (the player file's list, else the group's headline metrics) */
      const e0 = find(ids[0]);
      fill = RK.loadPlayer(ids[0]).then(pf => {
        const sims = ((pf && pf.similar) || []).map(x => String(x[0])).filter(id => { const f = find(id); return f && e0 && gOf(Object.assign({ id: id }, f)) === gOf(Object.assign({ id: ids[0] }, e0)); });
        const sim = sims[0] || (e0 ? nearestIn(sk, gk, Object.assign({ id: ids[0] }, e0)) : null);
        return sim ? ids.concat([String(sim)]) : ids;
      });
    }
    return fill.then(list => {
      if (!U.alive(el)) return;
      ids = list.filter(id => find(id));
      const E = ids.map(id => Object.assign({ id: id }, find(id)));
      draw(body, E, sk, gk, S);
    });
  });
}

function picker(E, sk, gk) {
  const opts = [];
  /* the active group (the first player's) first in the list, then everyone */
  const act = E.length ? gOf(E[0]) : 'F';
  [[sk, 'S'], [gk, 'G']].forEach(x => { if (x[0]) Object.keys(x[0].players).forEach(id => { const p = x[0].players[id]; if (p && p.name) opts.push([id, p.name + ' (' + RK.teamAbbr(p.team) + ', ' + (x[1] === 'G' ? 'G' : p.pos) + ')', (x[1] === 'G' ? 'G' : p.group === 'D' ? 'D' : 'F') === act ? 0 : 1]); }); });
  opts.sort((a, b) => (a[2] - b[2]) || a[1].localeCompare(b[1]));
  const lab = id => { const o = opts.find(x => x[0] === id); return o ? o[1] : ''; };
  return { opts: opts, html: '<div class="rk-cmp-pick">' + [0, 1, 2].map(i => '<label class="rk-cmp-slot" style="--ec:' + ECOL[i] + '"><span class="qk-kicker">' + (i === 2 ? 'Third player (optional)' : 'Player ' + (i + 1)) + '</span>' +
    '<input class="qk-input" list="cmp-names" data-i="' + i + '" value="' + esc(E[i] ? lab(E[i].id) : '') + '" placeholder="Type a name" autocomplete="off"></label>').join('') +
    '<datalist id="cmp-names">' + opts.map(o => '<option value="' + esc(o[1]) + '"></option>').join('') + '</datalist></div>' };
}

function draw(body, E, sk, gk, S) {
  const pk = picker(E, sk, gk);
  body.onclick = ev => { const t = ev.target.closest ? ev.target.closest('[data-cmp-go]') : null; if (t) RK.go(t.getAttribute('data-cmp-go')); };
  const crossG = E.length >= 2 && E.some(e => gOf(e) !== gOf(E[0]));
  const sqq = U.sq(S) ? '?' + U.sq(S) : '';
  /* players from different groups: each one's own-group comparison, one click away */
  const instead = crossG ? '<p class="cmp-instead">' + E.map(e => { const n = nearestIn(sk, gk, e), gi = GRPS.filter(x => x[0] === gOf(e))[0]; return n ? '<a href="' + esc('#/compare/' + encodeURIComponent(e.id) + '/' + encodeURIComponent(n) + sqq) + '">Compare ' + esc(RK.playerSurname(e.id) || e.p.name) + ' with a ' + gi[2] + ' instead</a>' : ''; }).filter(Boolean).join('<span aria-hidden="true"> · </span>') + '</p>' : '';
  const strip = cross => groupStrip(sk, gk, S, crossG || !E.length ? null : gOf(E[0]), cross) + instead;
  if (E.length < 2) {
    body.innerHTML = strip('') + U.card2('Pick players', 'Choose two or three players to compare', pk.html + QK.empty('Pick at least two players', 'Type a name in each box, or pick a position.'));
    wire(body, pk, E); return;
  }
  const goalie = E[0].kind === 'G';
  const mixed = E.some(e => e.kind !== E[0].kind);
  if (mixed) { body.innerHTML = strip('A skater and a goalie share no metric set.') + U.card2('Pick players', '', pk.html + QK.empty('Skaters and goalies do not share a metric set', 'Compare skaters with skaters and goalies with goalies.')); wire(body, pk, E); return; }
  const cat = goalie ? gk : sk;
  const meta = U.metaMap(cat);
  const sameGroup = goalie || E.every(e => e.p.group === E[0].p.group);
  const peer = goalie ? U.GROUP_NAME.G : sameGroup ? U.GROUP_NAME[E[0].p.group] : 'all NHL skaters';
  const pcOf = e => (sameGroup && e.p.pct_pos ? e.p.pct_pos : e.p.pct) || {};
  const grp = goalie ? 'G' : sameGroup ? (E[0].p.group || 'F') : 'F';
  const groups = (U.SETS[grp] || U.SETS.F).map(g => ({
    label: g[0],
    rows: g[1].map(x => x[0]).filter(k => meta[k] && !meta[k].unavailable).map(k => {
      const m = meta[k], sp = U.SPEC[k] || {};
      const pctFmt = m.fmt === 'pct';
      const ours = RK.ours ? RK.ours.of(k) : null;
      return { key: k, label: sp.label || m.label || k, tip: (sp.tip || m.desc || '') + (ours ? ' Our model: ' + ours.name + '.' : ''), better: (m.lower || sp.lower) ? 'low' : 'high', values: E.map(e => (e.p.values || {})[k]), pctls: E.map(e => pcOf(e)[k]),
        fmt: v => U.fmtBy(m, v), dfmt: pctFmt ? (v => (v > 0 ? '+' : v < 0 ? '−' : '±') + Math.abs(v * 100).toFixed(1) + ' pts') : null };
    })
  }));
  /* v4: two players draw the tale of the tape in their team colours (QK.tape via QK.compareView); three keep the table */
  const ents = E.map((e, i) => ({ name: e.p.name, href: RK.playerHref(e.id), colour: RK.teamColourRaw(e.p.team), alt: RK.teamAlt(e.p.team), abbr: RK.playerSurname(e.id), short: RK.playerSurname(e.id),
    sub: [RK.teamAbbr(e.p.team), goalie ? 'G' : e.p.pos, e.p.gp + ' GP', U.f(e.p.toi, 0) + ' min'].join(' · ') }));
  const quals = E.filter(e => !e.p.qualified).map(e => e.p.name);
  /* verdicts: for each player, the metric where the player's percentile beats the others' by the most */
  const short = E.map(e => RK.playerSurname(e.id) || e.p.name);
  const verd = E.map((e, i) => {
    let bestK = null, bestD = 0, bestRow = null;
    groups.forEach(g => g.rows.forEach(r => {
      const mine = r.pctls[i]; if (!isNum(mine)) return;
      const others = r.pctls.filter((_, j) => j !== i).map(v => (isNum(v) ? v : 0));
      const d = mine - Math.max.apply(null, others);
      if (d > bestD) { bestD = d; bestK = r.key; bestRow = r; }
    }));
    return bestRow ? { title: U.ARCHETYPE[bestK] || 'The standout', who: short[i], text: 'best of the ' + E.length + ' on ' + bestRow.label.charAt(0).toLowerCase() + bestRow.label.slice(1) + ' (' + bestRow.fmt(bestRow.values[i]) + ', ' + QK.ordinal(Math.round(bestRow.pctls[i])) + ' percentile).' } : null;
  });
  const q = short.length === 2 ? short[0] + ' or ' + short[1] + '?' : short.slice(0, -1).join(', ') + ' or ' + short[short.length - 1] + '?';
  body.innerHTML = strip(sameGroup ? '' : 'A forward and a defenceman: both are ranked against all NHL skaters, on the forwards’ set.') + U.card2('Players', 'Ranked against ' + esc(peer) + ' this season (' + esc(RK.seasonLabel(S)) + ')', pk.html) +
    '<section class="qk-section" style="margin-top:var(--sp-8)">' + QK.sectionHead({ kicker: 'Side by side', title: q,
      sub: E.length === 2 ? 'Bar length = percentile against ' + peer + ' (100 = best). The better number in each row is solid.' : 'Value and percentile against ' + peer + ' (100 = best). The best in each row is highlighted.' }) +
    U.card2(E.length + ' players, one metric set', 'The headline set for the position from our metrics spec: stable and predictive rates first',
      QK.compareView({ entities: ents, groups: groups }) + QK.verdicts(verd) +
      (quals.length ? '<p class="qk-caption">' + esc(quals.join(', ')) + (quals.length > 1 ? ' are' : ' is') + ' short of the sample floors: read the percentiles as early.</p>' : '') +
      (!sameGroup ? '<p class="qk-caption">A forward and a defenceman: percentiles are against all skaters, so position effects (defencemen score less) stay in.</p>' : '')) + '</section>' +
    '<section class="qk-section">' + U.card2('Where they sit', 'The qualified ' + esc(peer.replace('NHL ', '')) + ' this season, with each player marked', '<div class="qk-seg" id="cmp-dist-m" role="group" aria-label="Metric" style="margin-bottom:10px"></div>' + U.chart('cmp-dist', 260, 'Peer distribution with the players marked')) + '</section>';
  wire(body, pk, E);
  const peers = Object.keys(cat.players).map(id => cat.players[id]).filter(x => x && x.qualified && (goalie || !sameGroup || x.group === E[0].p.group));
  const opts = grp === 'G' ? [['gsax100', 'GSAx / 100'], ['sv_pct', 'Save %'], ['qs_pct', 'Quality starts']] : grp === 'D' ? [['gar_60', 'Value / 60'], ['adj_xgf_pct', 'xG share'], ['rapm_def', 'RAPM defence'], ['p60', 'Points / 60']] : [['gar_60', 'Value / 60'], ['p60', 'Points / 60'], ['ixg60_all', 'ixG / 60'], ['adj_xgf_pct', 'xG share']];
  const seg = body.querySelector('#cmp-dist-m');
  seg.innerHTML = opts.map((o, i) => '<button type="button" aria-pressed="' + (i === 0) + '" data-value="' + o[0] + '">' + esc(o[1]) + '</button>').join('');
  const dd = key => {
    const m = meta[key] || {};
    const vals = peers.map(x => (x.values || {})[key]).filter(isNum).sort((a, b) => a - b);
    if (vals.length < 5) { body.querySelector('#cmp-dist').innerHTML = QK.empty('Too few qualified peers yet'); return; }
    const f = m.fmt === 'pct' ? (v => U.f(v * 100, 1) + '%') : (v => U.f(v, 2));
    const cols = ['wpA', 'wpB', 'c5'];
    QKC.distribution('#cmp-dist', { values: vals, binCount: 22, lowerBetter: !!m.lower, fmt: f, colorBy: 'flat', xName: (m.label || key) + ' · ' + vals.length + ' qualified peers', yName: 'Players',
      marks: E.map((e, i) => ({ x: (e.p.values || {})[key], label: RK.playerSurname(e.id), color: cols[i] })).filter(x => isNum(x.x)), label: 'Distribution of ' + (m.label || key) });
  };
  dd(opts[0][0]);
  QK.seg(seg, dd);
}

function wire(body, pk, E) {
  body.querySelectorAll('.rk-cmp-pick input').forEach(inp => {
    inp.addEventListener('change', () => {
      const ids = [0, 1, 2].map(i => {
        const v = (body.querySelector('.rk-cmp-pick input[data-i="' + i + '"]') || {}).value || '';
        const hit = pk.opts.find(o => o[1] === v) || pk.opts.find(o => v && o[1].toLowerCase().indexOf(v.toLowerCase()) === 0);
        return hit ? hit[0] : (E[i] && !v ? null : null);
      }).filter(Boolean);
      if (ids.length) RK.go('#/compare/' + ids.map(encodeURIComponent).join('/'));
    });
  });
}

RK.page('compare', render);
})(window.RK);
