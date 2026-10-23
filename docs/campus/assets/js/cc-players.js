/* The Quant Campus — Players (#/<L>/players) and the player page (#/<L>/player/<pid>), Design System 2.0.
 * Catalogue: a leaderboard with heat cells on the percentile against the position group (the payload's position
 * pools; or all qualified players), position chips, search and the qualified-only floor.
 * Player page: player card header (team band), stat tiles (our value first, with its percentile), a Savant-style
 * percentile card against his position group with the sample and the floor named, where he sits in the position's
 * distribution, this season game by game, season by season, who moves next (movement.json, when published), inferred
 * moves and similar players.
 * Percentiles: the payload's pct_pos (position pool) and pct (all qualified). Where a payload carries none (basketball
 * catalogues are compact), they are computed here from the same catalogue: qualified players at his position, the
 * payload's own floor (min_floor), lower-is-better metrics flipped.
 * Reads <L>/<S>/players.json, <L>/players/<pid>.json (career), then <L>/<S>/movement.json (lazy). */
(function (CC) {
'use strict';
var U = CC.ui, esc = CC.esc, isNum = CC.isNum;

/* Percentiles within the position pool when the payload has none: the share of qualified peers at or below, 0-100. */
function fillPct(cat) {
  var P = cat.players || {}, ids = Object.keys(P), mets = cat.metrics || [];
  var any = ids.some(function (k) { var x = P[k]; return x && x.pct_pos && Object.keys(x.pct_pos).length; });
  if (any || !ids.length) return false;
  var byPos = {};
  ids.forEach(function (k) { var x = P[k]; if (x && x.qualified !== false && x.pos) (byPos[x.pos] = byPos[x.pos] || []).push(x); });
  mets.forEach(function (m) {
    Object.keys(byPos).forEach(function (ps) {
      var vals = byPos[ps].map(function (x) { return (x.values || {})[m.key]; }).filter(isNum).sort(function (a, b) { return a - b; });
      if (vals.length < 10) return;
      byPos[ps].forEach(function (x) {
        var v = (x.values || {})[m.key];
        if (!isNum(v)) return;
        var lo = 0, hi = vals.length;
        while (lo < hi) { var mid = (lo + hi) >> 1; if (vals[mid] <= v) lo = mid + 1; else hi = mid; }
        var p = 100 * (lo - 0.5) / vals.length;
        x.pct_pos = x.pct_pos || {};
        x.pct_pos[m.key] = Math.round(m.lower ? 100 - p : p);
      });
    });
  });
  return true;
}
/* Catalogue hygiene before any percentile is shown: ESPN team rows (negative ids, name "Team") are not players, and
 * a lower-is-better metric whose published percentile rises with the value (cfb pass_int ranks ascending today) is
 * turned round so 100 is always best. The check is on the data, so a fixed payload is left as it is. */
function clean(cat) {
  if (!cat || cat._clean) return;
  cat._clean = true;
  var P = cat.players || {};
  Object.keys(P).forEach(function (k) { var nm = String((P[k] || {}).name || '').trim(); if (!nm || /^team$/i.test(nm) || Number(k) < 0) delete P[k]; });
  (cat.metrics || []).filter(function (m) { return m.lower; }).forEach(function (m) {
    ['pct', 'pct_pos'].forEach(function (pk) {
      var xs = [], ys = [];
      Object.keys(P).forEach(function (k) { var x = P[k], v = (x.values || {})[m.key], q = (x[pk] || {})[m.key]; if (isNum(v) && isNum(q)) { xs.push(v); ys.push(q); } });
      if (xs.length < 20) return;
      var mx = xs.reduce(function (a0, b0) { return a0 + b0; }, 0) / xs.length, my = ys.reduce(function (a0, b0) { return a0 + b0; }, 0) / ys.length, c = 0;
      for (var i = 0; i < xs.length; i++) c += (xs[i] - mx) * (ys[i] - my);
      if (c > 0) Object.keys(P).forEach(function (k) { var q = P[k][pk]; if (q && isNum(q[m.key])) q[m.key] = 100 - q[m.key]; });
    });
  });
}
/* The qualifying floor in words, from the payload's min_floor. */
function floorText(L, cat, pos) {
  var f = (cat && cat.min_floor) || {};
  if (f.games && isNum(f.games[pos])) return f.games[pos] + '+ games';
  if (isNum(f.gp)) return f.gp + '+ games' + (isNum(f.mpg) ? ', ' + f.mpg + '+ min a game' : '');
  return '';
}
function posLabel(cat, pos) { var x = ((cat && cat.positions) || {})[pos]; return x && x.label ? x.label : pos; }

CC.route('players', function (el, p) {
  var L = p.L, S = p.S, fb = CC.fb(L), q0 = p.query || {};
  el.innerHTML = U.head('Players', '', U.kicker(L, S)) + QK.skeleton('lines', 8);
  return Promise.all([CC.load(CC.path(L, S, 'players.json')), CC.season(L, S), CC.metrics()]).then(function (a) {
    if (!U.alive(el)) return;
    var cat = a[0];
    if (!CC.ok(cat) || !Object.keys(cat.players || {}).length) {
      el.innerHTML = U.head('Players', '', U.kicker(L, S)) + (CC.ok(cat) ? QK.empty('No player numbers yet', 'They appear once games have been played this season. Pick last season in the season menu above.') : U.missing('The player catalogue', cat));
      return;
    }
    clean(cat);
    CC.addPlayers(L, cat.players);
    var computed = fillPct(cat);
    var mets = (cat.metrics || []).slice(0, 9), P = cat.players, ids = Object.keys(P);
    var pos = Object.keys(cat.positions || {}).sort(function (x, y) { return ((cat.positions[y] || {}).n || 0) - ((cat.positions[x] || {}).n || 0); });
    var st = { pos: q0.pos || 'all', q: '', qual: true, within: true, sort: mets[0] ? mets[0].key : null };
    el.innerHTML = U.head('Players', 'Season numbers, each cell coloured by its percentile against qualified players at the same position (blue low, red high; flipped where lower is better). ' + esc(QK.fmt.num(ids.length) + ' players') + '.', U.kicker(L, S)) +
      '<div class="cc-toolbar"><input class="qk-input" type="search" id="pl-q" placeholder="Find a player or team" aria-label="Find a player or team">' +
      '<label class="cc-check"><input type="checkbox" id="pl-qual" checked> Qualified only</label><label class="cc-check"><input type="checkbox" id="pl-within" checked> Percentiles within the position</label></div>' +
      '<div class="qk-chips scroll cc-filters" id="pl-pos" role="group" aria-label="Position">' + ['all'].concat(pos).map(function (k) {
        return '<button type="button" class="qk-chip" style="--ca:var(--signal)" data-value="' + esc(k) + '" aria-pressed="' + (k === st.pos) + '">' + esc(k === 'all' ? 'All' : posLabel(cat, k)) + (k !== 'all' ? ' <span class="n">' + ((cat.positions[k] || {}).n || '') + '</span>' : '') + '</button>'; }).join('') + '</div>' +
      U.card('', '', '<div class="cc-lbh" id="pl-n"></div>' + U.lb('pl-table'), { flush: true });
    function paint() {
      var q = st.q.toLowerCase();
      var rs = ids.filter(function (k) {
        var x = P[k];
        if (st.qual && x.qualified === false) return false;
        if (st.pos !== 'all' && x.pos !== st.pos) return false;
        if (q && String(x.name || '').toLowerCase().indexOf(q) < 0 && CC.tname(L, x.team).toLowerCase().indexOf(q) < 0) return false;
        return true;
      });
      var k0 = st.sort;
      rs.sort(function (x, y) { var vx = (P[x].values || {})[k0], vy = (P[y].values || {})[k0]; return (isNum(vy) ? vy : -1e9) - (isNum(vx) ? vx : -1e9); });
      var shown = rs.slice(0, 400);
      /* a position picked: the spec's headline set for its peer group, when the payload carries it */
      var G = null, cols = mets.map(function (m) { return { key: m.key, label: m.label, desc: m.desc, lower: m.lower, meta: m }; }), pk = null;
      if (st.pos !== 'all' && rs.length) {
        G = CC.group(L, 'player', P[rs[0]]);
        var hs = G ? G.m.filter(function (m) { return m.set === 'h' && rs.some(function (k) { return isNum(((P[k] || {}).values || {})[m.id]) && isNum(((P[k] || {})[G.pct] || {})[m.id]); }); }) : [];
        if (hs.length >= 3) { var mm0 = {}; mets.forEach(function (m) { mm0[m.key] = m; }); cols = hs.map(function (m) { return { key: m.id, label: m.d, desc: m.x, lower: m.low, style: m.style, meta: mm0[m.id] || { fmt: '2' } }; }); pk = G.pct; }
        else G = null;
      }
      var peer = G ? G.d.toLowerCase() + ' (the spec’s headline set)' : st.within ? (st.pos === 'all' ? 'each player’s position' : posLabel(cat, st.pos).toLowerCase()) : 'all qualified players';
      QK.$('#pl-n', el).innerHTML = '<b>' + esc(QK.fmt.num(rs.length)) + ' players</b> · percentiles v ' + esc(peer) + (computed ? ' (computed from this catalogue)' : '') + (rs.length > shown.length ? ' · showing the top 400 by ' + esc((mets[0] || {}).label || 'value') + '; search to find anyone' : '');
      var rows = shown.map(function (k) {
        var x = P[k], pc = pk ? (x[pk] || {}) : st.within ? (x.pct_pos || {}) : (x.pct || {});
        var o = { id: k, name: x.name, team: x.team, sub: [CC.tabbr(L, x.team), x.pos, x['class']].filter(Boolean).join(' · '), gp: x.gp };
        cols.forEach(function (m) { o[m.key] = (x.values || {})[m.key]; o['p_' + m.key] = pc[m.key]; });
        return o;
      });
      QK.leaderboard(QK.$('#pl-table', el), { dense: true, maxHeight: 760, rowHref: function (r) { return CC.playerHref(L, r.id, S); }, columns: [
        { key: 'name', label: 'Player', type: 'entity', sub: 'sub', mark: function (r) { return U.mark(L, r.team); }, href: function (r) { return CC.playerHref(L, r.id, S); } },
        { key: 'gp', label: 'GP', num: true }
      ].concat(cols.map(function (m) { return { key: m.key, label: m.label, type: 'pctl', pctl: 'p_' + m.key, style: !!m.style, tip: (m.desc || m.label) + (m.lower ? ' (lower is better; the colour is flipped)' : '') + (m.style ? ' (style: shown in grey)' : ''), fmt: function (v) { return CC.fmtMetric(m.meta, v); } }; })), rows: rows });
    }
    QK.$('#pl-q', el).addEventListener('input', function (e) { st.q = e.target.value || ''; paint(); });
    QK.$('#pl-qual', el).addEventListener('change', function (e) { st.qual = e.target.checked; paint(); });
    QK.$('#pl-within', el).addEventListener('change', function (e) { st.within = e.target.checked; paint(); });
    QK.chips(QK.$('#pl-pos', el), function (v) { st.pos = v[0] || 'all'; paint(); });
    paint();
  });
});

var SEASON_COLS = {
  cfb: [['gp', 'GP'], ['cmp', 'Cmp'], ['att', 'Att'], ['pass_yds', 'Pass yds', 'yds'], ['pass_td', 'Pass TD', 'td'], ['int', 'INT'], ['car', 'Car'], ['rush_yds', 'Rush yds'], ['rush_td', 'Rush TD'], ['rec', 'Rec'], ['rec_yds', 'Rec yds'], ['rec_td', 'Rec TD'],
    ['tkl', 'Tkl'], ['tfl', 'TFL'], ['sacks', 'Sacks'], ['pd', 'PD'], ['epa', 'EPA'], ['epa_play', 'EPA/play'], ['value', 'Value']],
  bb: [['gp', 'GP'], ['min', 'MIN'], ['pts', 'PTS'], ['reb', 'REB'], ['ast', 'AST'], ['stl', 'STL'], ['blk', 'BLK'], ['tov', 'TOV'], ['fg_pct', 'FG%', 'pct'], ['tp_pct', '3P%', 'pct'], ['ft_pct', 'FT%', 'pct'], ['ts', 'TS%', 'pct'], ['usg', 'USG%'], ['ortg', 'ORtg'], ['value', 'Value'], ['value_pg', 'Value/G']]
};
/* Football season rows may nest passing / rushing / receiving / defense objects (PAYLOADS.md lists them as groups). */
function flat(r) {
  var o = {};
  Object.keys(r || {}).forEach(function (k) {
    var v = r[k];
    if (v && typeof v === 'object' && !Array.isArray(v)) {
      var pre = { passing: 'pass_', rushing: 'rush_', receiving: 'rec_', defense: '' }[k];
      Object.keys(v).forEach(function (kk) {
        var key = kk;
        if (pre === 'pass_' && (kk === 'yds' || kk === 'td')) key = 'pass_' + kk;
        else if (pre === 'rush_' && (kk === 'yds' || kk === 'td')) key = 'rush_' + kk;
        else if (pre === 'rec_' && (kk === 'yds' || kk === 'td')) key = 'rec_' + kk;
        else if (pre === '' && kk === 'int') key = 'def_int';
        o[key] = v[kk];
      });
    } else o[k] = v;
  });
  return o;
}
/* Headline numbers by position for the card header. */
var HEAD = {
  QB: [['pass_yds', 'Pass yds'], ['pass_td', 'Pass TD'], ['rush_yds', 'Rush yds']], RB: [['rush_yds', 'Rush yds'], ['rush_td', 'Rush TD'], ['rec_yds', 'Rec yds']],
  WR: [['rec', 'Rec'], ['rec_yds', 'Rec yds'], ['rec_td', 'Rec TD']], TE: [['rec', 'Rec'], ['rec_yds', 'Rec yds'], ['rec_td', 'Rec TD']],
  DL: [['tkl', 'Tackles'], ['tfl', 'TFL'], ['sacks', 'Sacks']], LB: [['tkl', 'Tackles'], ['tfl', 'TFL'], ['sacks', 'Sacks']], DB: [['tkl', 'Tackles'], ['pd', 'PD'], ['def_int', 'INT']],
  bb: [['pts', 'PTS'], ['reb', 'REB'], ['ast', 'AST']]
};

/* Who moves next: the player-page Movement card (MOVES_VIEWS.md, college), from movement.json when published. */
function movementCard(L, S, pid, team, node) {
  if (!node || !team || !CC.isCur(L, S)) return;
  /* the team page says whether the movement payload is published (its `movement` key), so nothing is fetched before */
  CC.load(CC.path(L, S, 'teams/' + team + '.json')).then(function (tp) {
    if (!CC.ok(tp) || !tp.movement) return null;
    return CC.load(CC.path(L, S, 'movement.json'));
  }).then(function (mvj) {
    if (!mvj || !U.alive(node) || !CC.ok(mvj)) return;
    var me = ((mvj.players || []).filter ? (mvj.players || []).filter(function (x) { return String(x.id) === String(pid); })[0] : null);
    if (!me || !isNum(me.p)) return;
    var meta = mvj.meta || {}, nx = meta.next_season ? CC.seasonLabel(L, meta.next_season) : 'next season';
    var pt = isNum(me.p_transfer) ? me.p_transfer : 0, pg = isNum(me.p_gone) ? me.p_gone : Math.max(0, me.p - pt);
    var ctx = [isNum(me.exp) ? (me.exp >= 4 ? '4+' : me.exp) + ' earlier season' + (me.exp === 1 ? '' : 's') + ' in our box scores' : '', me['class'] ? 'class: ' + me['class'] : '', me.new_in ? 'transferred in this season' : ''].filter(Boolean).join(' · ');
    node.innerHTML = U.card('Movement: before ' + nx, QK.tag('Inferred from box scores, not the official transfer portal'),
      U.stats([{ label: 'Chance of leaving', value: CC.pct(me.p), signal: true, sub: ctx, tip: 'Our chance the player is not with this team next season: an inferred transfer or no box-score line. ' + (meta.method ? String(meta.method).slice(0, 220) : '') }]) +
      '<div class="cc-split" role="img" aria-label="' + esc('Transfer ' + CC.pct(pt) + ', no line next season ' + CC.pct(pg)) + '"><span style="flex:' + pt + ';background:var(--signal)"></span><span style="flex:' + pg + ';background:var(--c-3)"></span><span style="flex:' + Math.max(0, 1 - pt - pg) + '"></span></div>' +
      QK.keys([{ name: 'Transfer ' + CC.pct(pt), color: 'var(--signal)', kind: 'dot' }, { name: 'No box-score line next season ' + CC.pct(pg) + ' (graduation, the pros, a lower division, injury or not playing)', color: 'var(--c-3)', kind: 'dot' }]));
  });
}

CC.route('player', function (el, p) {
  var L = p.L, S = p.S, pid = p.id, fb = CC.fb(L);
  el.innerHTML = QK.skeleton('card', 1) + QK.skeleton('lines', 6);
  return Promise.all([CC.load(CC.lpath(L, 'players/' + pid + '.json')), CC.load(CC.path(L, S, 'players.json')), CC.season(L, S), CC.metrics()]).then(function (a) {
    if (!U.alive(el)) return;
    var d = CC.ok(a[0]) ? a[0] : null, cat = CC.ok(a[1]) ? a[1] : null;
    if (cat) { clean(cat); fillPct(cat); }
    var cp = cat && cat.players ? cat.players[pid] : null;
    if (!d && !cp) { el.innerHTML = U.head('Player', '', U.kicker(L, S)) + QK.empty('Player not found', 'No career file for this player (careers are kept for players with a game in the last two seasons).'); return; }
    var cur = (d && d.current) || {};
    var team = cur.team || (cp && cp.team) || null;
    var t = team ? CC.team(L, team) : null;
    var name = (d && d.name) || (cp && cp.name) || ('Player ' + pid);
    var pos = (cp && cp.pos) || (d && d.pos) || '';
    var hgt = d && isNum(d.height_in) ? Math.floor(d.height_in / 12) + '′' + (d.height_in % 12) + '″' : null;
    var vr = cur.value || null;
    var vals = (cp && cp.values) || {}, pp = (cp && (cp.pct_pos || cp.pct)) || {};
    document.title = name + ' · The Quant Campus';
    var hstats = (fb ? (HEAD[pos] || []) : HEAD.bb).filter(function (h0) { return isNum(vals[h0[0]]); }).map(function (h0) { return { label: h0[1], value: fb ? fmtInt(vals[h0[0]]) : CC.f(vals[h0[0]], 1) }; });
    if (cp && isNum(cp.gp)) hstats.unshift({ label: 'GP', value: String(cp.gp) });
    var html = '<div class="qk-kicker" style="margin-bottom:10px"><a href="' + esc(CC.href(L, 'players', null, S)) + '">← Players</a></div>' +
      QK.playerHeader({ name: name, pos: posLabel(cat, pos) || pos, kicker: CC.LNAME[L] + ' · ' + CC.seasonLabel(L, cur.season || S),
        team: t ? { name: t.short || t.name, abbr: t.abbr, colour: t.colour, href: CC.teamHref(L, team, cur.season || S) } : null,
        meta: [(d && d['class']) || (cp && cp['class']) ? ['Class', (d && d['class']) || cp['class']] : null, hgt ? ['Height', hgt + (d && isNum(d.weight_lb) ? ' · ' + d.weight_lb + ' lb' : '')] : null, d && d.hometown ? ['From', d.hometown] : null],
        stats: hstats.slice(0, 4), tags: cp && cp.qualified !== false ? [QK.tag('Qualified for percentiles', 'signal')] : [] });
    // stat tiles: ours first
    var k = [];
    if (vr) k.push({ label: fb ? 'Value (EPA above replacement)' : 'Value above replacement', value: CC.f(vr.value, fb ? 1 : 1), signal: true, pctl: isNum(pp.value) ? pp.value : (isNum(vr.pctl) ? vr.pctl : null), sub: isNum(vr.gp) ? vr.gp + ' games · ' + CC.f(vr.value_pg, 2) + ' a game' : '', tip: 'Our value model this season; the chip is the percentile against the same position' });
    if (isNum(vals.epa_play)) k.push({ label: 'EPA per play', value: CC.signed(vals.epa_play, 3), pctl: pp.epa_play, sub: 'expected points added per credited play' });
    if (!fb && isNum(vals.ts)) k.push({ label: 'True shooting', value: CC.pct(vals.ts, 1), pctl: pp.ts, sub: 'points per shooting chance' });
    if (!fb && isNum(vals.r)) k.push({ label: 'Rating per 100', value: CC.signed(vals.r, 1), pctl: pp.r, sub: 'on-court margin per 100 possessions v average' });
    if (vr && isNum(vr.pctl)) k.push({ label: 'Value percentile', value: QK.ordinal(vr.pctl), text: true, sub: 'against every qualified player' });
    if (cur.fantasy && isNum(cur.fantasy.proj)) k.push({ label: 'Fantasy projection', value: CC.f(cur.fantasy.proj, 1), sub: 'points next ' + (fb ? 'week' : 'period') });
    html += '<div style="margin-top:var(--sp-4)">' + (k.length ? U.stats(k) : '') + '</div>';
    if (vr && vr.why) html += '<p class="cc-note"><b>Why:</b> ' + esc(vr.why) + '</p>';
    // percentile card + where he sits
    var mets = (cat && cat.metrics) || [];
    var fl = floorText(L, cat, pos);
    /* the spec's peer group and headline set (METRICS_SPEC.md) where the payload carries them; else the payload's own
       position pools and metric list */
    var meta = {}; mets.forEach(function (m) { meta[m.key] = m; });
    var G = cp ? CC.group(L, 'player', cp) : null;
    var qualOf = function (x) { return G && G.min && G.min.f && x[G.min.f] !== undefined ? x[G.min.f] !== false : x.qualified !== false; };
    var head = G ? CC.specRows(G, cp, 'h', meta) : [];
    var useSpec = !!G && head.length >= 2;
    var inPeer = function (x) { return x && (useSpec ? x[G.pf] === cp[G.pf] : x.pos === pos) && qualOf(x); };
    var peerN = cat ? Object.keys(cat.players).filter(function (k0) { return inPeer(cat.players[k0]); }).length : 0;
    var groupsPc;
    if (useSpec) {
      var used = {}; head.forEach(function (r) { used[r.m.id] = 1; });
      var sec = CC.specRows(G, cp, 's', meta).filter(function (r) { return !used[r.m.id]; });
      sec.forEach(function (r) { used[r.m.id] = 1; });
      /* the spec ranks on rates only: season counts stay in the tables, not in the card */
      groupsPc = [{ label: 'Headline: the most stable and predictive', rows: head }, { label: 'More', rows: sec.slice(0, 8) }];
    } else {
      var rowsPc = mets.filter(function (m) { return isNum(pp[m.key]); }).map(function (m) { return { label: m.label, pctl: pp[m.key], value: CC.fmtMetric(m, vals[m.key]), tip: (m.desc || '') + (m.lower ? ' Lower is better; the bar is flipped.' : '') }; });
      groupsPc = [{ label: 'Value and efficiency', rows: rowsPc.slice(0, 7) }, { label: 'Production', rows: rowsPc.slice(7) }];
    }
    var peerName = useSpec ? G.d + (CC.groupFloor(G) ? ', ' + CC.groupFloor(G) : '') : (posLabel(cat, pos) || 'same position') + (fl ? ', ' + fl : '');
    var pcard = QK.pctCard({ title: 'Percentile rankings', peer: peerName, sample: (cp && isNum(cp.gp) ? cp.gp + ' games' : '') + (peerN ? ' · ' + peerN + ' qualified peers' : '') + ' · ' + CC.seasonLabel(L, S),
      groups: groupsPc,
      note: cp && cp.qualified === false ? 'Below the qualifying floor: read these as early.' : (useSpec && head.length < G.m.filter(function (m) { return m.set === 'h'; }).length ? 'More of the headline rates (per dropback, carry or target) arrive with the next data build.' : ''), emptyText: cp ? 'No percentiles for this season yet.' : 'No current-season profile yet.' });
    html += '<div class="qk-grid cc-grid"><div class="qk-span-5">' + pcard + '</div><div class="qk-span-7"><div class="qk-stack">' +
      (cp && peerN >= 10 ? U.card('Among peers', 'Every qualified ' + esc((useSpec ? G.d : (posLabel(cat, pos) || 'player')).toLowerCase()) + ' this season, coloured by percentile', '<div class="qk-seg" id="pp-dist-m" role="group" aria-label="Metric" style="margin-bottom:10px"></div>' + U.chart('pp-dist', 240, 'Distribution of the position group')) : '') +
      '<div id="pp-log-card"></div><div id="pp-move"></div></div></div></div>';
    if (!d) html += '<p class="cc-note">Career pages are kept for players with a game in the last two seasons; this season’s catalogue numbers are shown.</p>';
    var log = cur.log || [];
    var vkLog = null, LOGK = { value: 'Value', epa: 'EPA', pts: 'Points', pass_yds: 'Passing yards', rush_yds: 'Rushing yards', rec_yds: 'Receiving yards', tkl: 'Tackles', sacks: 'Sacks', fgm: 'Field goals' }, lk = [];
    if (log.length) {
      log.forEach(function (g) { Object.keys(g).forEach(function (k2) { if (lk.indexOf(k2) < 0 && ['game', 'date', 'opp', 'home', 'res'].indexOf(k2) < 0 && isNum(g[k2])) lk.push(k2); }); });
      lk = lk.slice(0, 10);
      var tot = function (k2) { return log.reduce(function (a0, g) { return a0 + (isNum(g[k2]) ? Math.abs(g[k2]) : 0); }, 0); };
      vkLog = ['value', 'epa', 'pts', 'pass_yds', 'rush_yds', 'rec_yds', 'tkl', 'sacks', 'fgm'].filter(function (k2) { return lk.indexOf(k2) >= 0 && tot(k2) > 0; })[0] || null;
      html += U.section('Game log', CC.seasonLabel(L, cur.season || S) + ', newest first.', U.card('', '', U.table(['Date', 'Opp', 'Result'].concat(lk.map(function (k2) { return { label: k2.replace(/_/g, ' ').toUpperCase(), align: 'right' }; })), log.slice().reverse().map(function (g) {
        return { cells: [{ v: g.date, html: esc(CC.date(g.date)) }, { html: (g.home ? '' : '@ ') + U.teamEnt(L, g.opp, { season: cur.season || S, abbr: true }), v: CC.tname(L, g.opp) }, { html: '<a href="' + esc(CC.gameHref(L, g.game, cur.season || S)) + '">' + esc(g.res || '') + '</a>', v: g.res }].concat(lk.map(function (k2) { return isNum(g[k2]) ? (Math.round(g[k2] * 100) / 100) : '—'; })), _href: CC.gameHref(L, g.game, cur.season || S) };
      }), { maxHeight: 420 })), '', 'This season');
    }
    var seasons = ((d && d.seasons) || []).map(flat);
    if (seasons.length) {
      var C = (fb ? SEASON_COLS.cfb : SEASON_COLS.bb).filter(function (c) { return seasons.some(function (r) { return isNum(r[c[0]]); }); });
      html += U.section('Season by season', '', U.card('', '', U.table([{ label: 'Season', align: 'right' }, 'Team'].concat(C.map(function (c) { return { label: c[1], align: 'right' }; })), seasons.slice().sort(function (x, y) { return y.season - x.season; }).map(function (r) {
        return [{ v: r.season, html: esc(CC.seasonLabel(L, r.season)) }, { html: U.teamEnt(L, r.team, { season: r.season, abbr: true }), v: CC.tname(L, r.team) }].concat(C.map(function (c) {
          var v = r[c[0]];
          return !isNum(v) ? '—' : (c[2] === 'pct' ? { v: v, html: CC.pct(v, 1) } : (Math.round(v) === v ? v : { v: v, html: CC.f(v, c[0] === 'epa_play' || c[0] === 'value_pg' ? 3 : 1) }));
        }));
      }))), '', 'Career');
    }
    var mv = (d && d.moves) || [];
    var sim = (d && d.similar) || [];
    if (mv.length || sim.length) {
      html += '<div class="qk-grid cc-grid">' + (mv.length ? '<div class="qk-span-6">' + U.card('Moves', QK.tag('Inferred from box scores, not the official transfer portal'), U.table([{ label: 'Season', align: 'right' }, 'From', 'To', { label: 'Value before', align: 'right' }, { label: 'After', align: 'right' }], mv.map(function (m) {
        return [{ v: m.season, html: m.season ? esc(CC.seasonLabel(L, m.season)) : '—' }, { html: U.teamEnt(L, m.from, { abbr: true }), v: CC.tname(L, m.from) }, { html: U.teamEnt(L, m.to, { abbr: true }), v: CC.tname(L, m.to) }, CC.f(m.value_before, 1), CC.f(m.value_after, 1)];
      }), { sticky: false })) + '</div>' : '') + (sim.length ? '<div class="qk-span-6">' + U.card('Most similar', 'Closest statistical profiles (smaller distance is closer).', '<ul class="cc-list">' + sim.map(function (s0) {
        return '<li><a href="' + esc(CC.playerHref(L, s0.id, s0.season)) + '">' + esc(s0.name || CC.pname(L, s0.id)) + '</a><span class="s">' + esc(CC.seasonLabel(L, s0.season)) + '</span><span class="v">' + CC.f(s0.distance, 2) + '</span></li>'; }).join('') + '</ul>', { flush: true, foot: '<span></span>' + U.link(CC.href(L, 'lab', null, S, 'kind=compare&p=' + [pid].concat(sim.filter(function (s0) { return Number(s0.season) === Number(S); }).slice(0, 2).map(function (s0) { return s0.id; })).join(',')), 'Compare side by side') }) + '</div>' : '') + '</div>';
    }
    el.innerHTML = html;
    U.wire(el);
    // where he sits
    if (cp && QK.$('#pp-dist', el)) {
      var peers = Object.keys(cat.players).map(function (k0) { return cat.players[k0]; }).filter(inPeer);
      var opts = useSpec ? head.filter(function (r) { return !r.style; }).map(function (r) { return { key: r.m.id, label: r.m.d, lower: !!r.m.low, fmt: (meta[r.m.id] || {}).fmt }; }).slice(0, 4) : mets.filter(function (m) { return isNum(vals[m.key]); }).slice(0, 4);
      var segEl = QK.$('#pp-dist-m', el);
      segEl.innerHTML = opts.map(function (o, i) { return '<button type="button" aria-pressed="' + (i === 0) + '" data-value="' + esc(o.key) + '">' + esc(o.label) + '</button>'; }).join('');
      var drawDist = function (key) {
        var mm = opts.filter(function (o) { return o.key === key; })[0] || {};
        var vs = peers.map(function (x) { return (x.values || {})[key]; }).filter(isNum).sort(function (x, y) { return x - y; });
        if (vs.length < 10) { QK.$('#pp-dist', el).innerHTML = QK.empty('Too few qualified peers yet', 'The distribution appears with ten or more.'); return; }
        var med = vs[Math.floor(vs.length / 2)];
        QKC.distribution('#pp-dist', { values: vs, binCount: 22, lowerBetter: !!mm.lower, fmt: function (v) { return CC.fmtMetric(mm, v); }, xName: (mm.label || key) + ' · ' + vs.length + ' qualified peers', yName: 'Players',
          marks: (isNum(vals[key]) ? [{ x: vals[key], label: String(name).split(' ').slice(-1)[0] }] : []).concat([{ x: med, label: 'Median' }]), label: 'Distribution of ' + (mm.label || key) });
      };
      if (opts.length) { drawDist(opts[0].key); QK.seg(segEl, drawDist); }
    }
    if (log.length && vkLog) {
      QK.$('#pp-log-card', el).innerHTML = U.card(LOGK[vkLog] + ' game by game', CC.seasonLabel(L, cur.season || S), U.chart('pp-log', 220, (LOGK[vkLog] || vkLog) + ' per game this season'));
      QKC.bar('#pp-log', { cats: log.map(function (g) { return CC.tabbr(L, g.opp); }), series: [{ name: LOGK[vkLog] || vkLog, color: 'model', data: log.map(function (g) { return isNum(g[vkLog]) ? g[vkLog] : 0; }) }], diverging: vkLog === 'value' || vkLog === 'epa', valName: LOGK[vkLog] || vkLog, catName: 'Opponent', fmt: function (v) { return CC.f(v, 1); }, hrefs: log.map(function (g) { return CC.gameHref(L, g.game, cur.season || S); }) });
    }
    movementCard(L, S, pid, team, QK.$('#pp-move', el));
  });
});
function fmtInt(v) { return isNum(v) ? String(Math.round(v)) : '—'; }

})(window.CC);
