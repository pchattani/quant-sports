/* The Quant Campus — Players (#/<L>/players) and the player page (#/<L>/player/<pid>), on kit v3 "Matchday".
 * Catalogue: a leaderboard with heat cells on the percentile against the position group (the payload's position
 * pools; or all qualified players), position chips, search and the qualified-only floor.
 * Player page (the Rink reference, MIGRATION_V3.md): a crumb; the header with "The short version" in plain English
 * from this season's percentiles against the position (football) or role (basketball) group; tiles (our value
 * first); the percentile rail with a plain line per metric, early-sample markers and last season's hollow ring
 * (current.prev_pct_pos when the payload has it, else last season's catalogue when the rail scrolls into view) beside
 * "How sure are we?" (when the headline numbers are half signal at this playing time, from the spec's M50), game by
 * game and "Their type"; a compare of the player and the two closest matches with the highlighter and verdicts; next
 * up and last time out; then where the player sits among peers, the movement card, the game log, season by season
 * and inferred moves.
 * Percentiles: the payload's pct_pos (position pool) and pct (all qualified). Where a payload carries none (basketball
 * catalogues are compact), they are computed here from the same catalogue: qualified players at the position, the
 * payload's own floor (min_floor), lower-is-better metrics flipped.
 * Reads <L>/<S>/players.json, <L>/players/<pid>.json (career), <L>/<S-1>/players.json (the rings, lazy), then
 * <L>/<S>/movement.json (lazy). */
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

/* v3 (Matchday): a plain-English line under each metric on the percentile rail (spec ids and the catalogue's own keys),
   and the type a player's best metric suggests (compare verdicts). */
var SUB = {
  value_pg: 'Points added over a replacement-level player, per game.', epa_play: 'Points added on each of the player’s plays.', sr_db: 'Dropbacks that keep the offence on schedule.',
  cmp_pct: 'Passes caught.', ypa: 'Yards for every throw.', td_rate: 'Throws that end in a touchdown.', int_rate: 'How rarely a throw is picked off. Noisy.', rush_pg: 'How often the quarterback runs (style).',
  sr_rush: 'Carries that keep the offence on schedule.', ypc: 'Yards for every carry.', rush_share: 'Share of the team’s carries: the role in the run game.', tgt_share: 'Share of the team’s targets: how often the player earns the ball.',
  yptpa: 'Receiving yards for every team pass: a stand-in for yards per route.', ypr: 'Yards for every catch.', sr_tgt: 'Targets that gain expected points.',
  havoc_pg: 'Disruptive plays a game: tackles for loss, break-ups, picks and hurries.', sacks_pg: 'Sacks a game.', hurries_pg: 'Quarterback hurries a game.', tkl_pg: 'Tackles a game: involvement, not quality.',
  pd_pg: 'Passes broken up or picked off a game.', tfl_pg: 'Tackles behind the line a game.', def_int_pg: 'Interceptions a game. Mostly luck year to year.', fg_pct: 'Field goals made (no kick distances in the data).',
  xp_pct: 'Extra points made.', gross: 'Raw punt distance: the steadiest punting number.', in20_rate: 'Punts that pin the opponent inside the 20.', tb_rate: 'How rarely a punt rolls into the end zone.',
  r: 'Points per 100 possessions the player adds over an average D-I player.', pts100: 'Points scored per 100 possessions on the floor.', ts_add: 'Points gained by shooting better than average.',
  ast_pct: 'Team-mates’ baskets the player sets up.', tov_pct: 'How rarely a possession ends in a turnover.', fta100: 'Trips to the line: pressure on the rim.', stl_pct: 'Steals per opponent possession.',
  trb_pct: 'Share of the available rebounds.', orb_pct: 'Share of the available offensive rebounds.', blk_pct: 'Share of opponent twos blocked.',
  value: 'Value above a replacement-level player this season.', pts: 'Points a game.', reb: 'Rebounds a game.', ast: 'Assists a game.', ts: 'Points per shooting chance.', usg: 'Share of possessions the player finishes.', ortg: 'Points produced per 100 possessions used.'
};
/* basketball box-score keys that share a name with a football one */
var SUB_BB = { fg_pct: 'Shots made from the field.', tp_pct: 'Threes made.', ft_pct: 'Free throws made.', min: 'Minutes a game.', stl: 'Steals a game.', blk: 'Blocks a game.', tov: 'Turnovers a game (fewer is better).', value_pg: 'Value above a replacement-level player, per game.' };
var ARCHETYPE = { value_pg: 'The most valuable', epa_play: 'The efficient one', sr_db: 'The steady passer', cmp_pct: 'The accurate passer', ypa: 'The big-play passer', td_rate: 'The touchdown maker', int_rate: 'The ball-protector', rush_pg: 'The runner',
  sr_rush: 'The steady runner', ypc: 'The big-play runner', rush_share: 'The workhorse', tgt_share: 'The go-to target', yptpa: 'The yardage machine', ypr: 'The deep threat', sr_tgt: 'The reliable target',
  havoc_pg: 'The disruptor', sacks_pg: 'The pass rusher', hurries_pg: 'The pass rusher', tkl_pg: 'The tackler', pd_pg: 'The ball hawk', tfl_pg: 'The backfield wrecker', def_int_pg: 'The ball hawk',
  fg_pct: 'The accurate kicker', xp_pct: 'The steady kicker', gross: 'The big leg', in20_rate: 'The pin-it-deep punter', tb_rate: 'The precise punter',
  r: 'The difference-maker', pts100: 'The scorer', ts_add: 'The efficient scorer', ast_pct: 'The playmaker', tov_pct: 'The careful one', fta100: 'The rim attacker', stl_pct: 'The pickpocket', trb_pct: 'The rebounder', orb_pct: 'The glass cleaner', blk_pct: 'The rim protector' };
var NUMW = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten'];
function lc(x) { x = String(x || ''); return /^[A-Z][a-z]/.test(x) ? x.charAt(0).toLowerCase() + x.slice(1) : x; }
function plural(n, w) { return n + ' ' + w + (n === 1 ? '' : 's'); }

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
    var sur = String(name).split(' ').filter(function (w) { return !/^(jr\.?|sr\.?|ii|iii|iv)$/i.test(w); }).slice(-1)[0] || name;
    var pos = (cp && cp.pos) || (d && d.pos) || '';
    var hgt = d && isNum(d.height_in) ? Math.floor(d.height_in / 12) + '′' + (d.height_in % 12) + '″' : null;
    var vr = cur.value || null;
    var vals = (cp && cp.values) || {}, pp = (cp && (cp.pct_pos || cp.pct)) || {};
    var gpNow = cp && isNum(cp.gp) ? cp.gp : (cur.log || []).length;
    document.title = name + ' · The Quant Campus';
    // the peer group and the rail rows (the spec's headline set where the payload carries it, else the payload's own pools)
    var mets = (cat && cat.metrics) || [];
    var fl = floorText(L, cat, pos);
    var meta = {}; mets.forEach(function (m) { meta[m.key] = m; });
    var G = cp ? CC.group(L, 'player', cp) : null;
    var qualOf = function (x) { return G && G.min && G.min.f && x[G.min.f] !== undefined ? x[G.min.f] !== false : x.qualified !== false; };
    var head = G ? CC.specRows(G, cp, 'h', meta) : [];
    var useSpec = !!G && head.length >= 2;
    var inPeer = function (x) { return x && (useSpec ? x[G.pf] === cp[G.pf] : x.pos === pos) && qualOf(x); };
    var peerN = cat ? Object.keys(cat.players).filter(function (k0) { return inPeer(cat.players[k0]); }).length : 0;
    var peerShort = (useSpec ? G.d : (posLabel(cat, pos) || 'players')).toLowerCase();
    var prevPct = null, prevGp = null;
    var pp0 = cur.prev_pct_pos;
    if (pp0 && typeof pp0 === 'object') { prevPct = pp0.pct && typeof pp0.pct === 'object' ? pp0.pct : pp0; prevGp = isNum(pp0.gp) ? pp0.gp : (isNum(pp0.games) ? pp0.games : null); }
    var withRing = function (rows, key) { return rows.map(function (r) { var k = key(r); return Object.assign({}, r, { sub: (!fb && SUB_BB[k]) || SUB[k] || '', prev: prevPct && isNum(prevPct[k]) ? prevPct[k] : null }); }); };
    var railGroups = function () {
      if (useSpec) {
        var used = {}; head.forEach(function (r) { used[r.m.id] = 1; });
        var sec = CC.specRows(G, cp, 's', meta).filter(function (r) { return !used[r.m.id]; });
        return [{ label: 'Headline: the most stable and predictive', rows: withRing(head, function (r) { return r.m.id; }) }, { label: 'More', rows: withRing(sec.slice(0, 8), function (r) { return r.m.id; }) }];
      }
      var rowsPc = mets.filter(function (m) { return isNum(pp[m.key]); }).map(function (m) { return { key: m.key, label: m.label, pctl: pp[m.key], value: CC.fmtMetric(m, vals[m.key]), tip: (m.desc || '') + (m.lower ? ' Lower is better; the bar is flipped.' : '') }; });
      return [{ label: 'Value and efficiency', rows: withRing(rowsPc.slice(0, 7), function (r) { return r.key; }) }, { label: 'Production', rows: withRing(rowsPc.slice(7), function (r) { return r.key; }) }];
    };
    var peerName = useSpec ? G.d + (CC.groupFloor(G) ? ', ' + CC.groupFloor(G) : '') : (posLabel(cat, pos) || 'same position') + (fl ? ', ' + fl : '');
    var rail = function () {
      return QK.pctRail({ id: 'pp-pcard', kicker: 'How they stack up', title: 'Percentiles: how the player ranks', peer: peerName, sample: (cp && isNum(cp.gp) ? cp.gp + ' games' : '') + (peerN ? ' · ' + peerN + ' qualified peers' : '') + ' · ' + CC.seasonLabel(L, S),
        groups: railGroups(), ringLabel: 'last season' + (isNum(prevGp) ? ' (' + plural(prevGp, 'game') + ')' : ''),
        note: cp && cp.qualified === false ? 'Below the qualifying floor: read these as early.' : (useSpec && head.length < G.m.filter(function (m) { return m.set === 'h'; }).length ? 'More of the headline rates (per dropback, carry or target) arrive with the next data build.' : ''), emptyText: cp ? 'No percentiles for this season yet.' : 'No current-season profile yet.' });
    };

    /* "The short version": what this season's numbers say, in plain English (percentiles against the peer group) */
    function lead() {
      var v = vals, gp = gpNow ? ' in ' + plural(gpNow, 'game') : '';
      var n = function (x) { return QK.fmt.num(Math.round(x)); };
      if (!fb && isNum(v.pts)) return sur + ' averages ' + CC.f(v.pts, 1) + ' points, ' + CC.f(v.reb, 1) + ' rebounds and ' + CC.f(v.ast, 1) + ' assists' + gp + '.';
      if (pos === 'QB' && isNum(v.pass_yds)) return sur + ' has thrown for ' + n(v.pass_yds) + ' yards and ' + plural(Number(v.pass_td) || 0, 'touchdown') + gp + '.';
      if (pos === 'RB' && isNum(v.rush_yds)) return sur + ' has run for ' + n(v.rush_yds) + ' yards and ' + plural(Number(v.rush_td) || 0, 'touchdown') + gp + '.';
      if ((pos === 'WR' || pos === 'TE') && isNum(v.rec_yds)) return sur + ' has ' + n(v.rec || 0) + ' catches for ' + n(v.rec_yds) + ' yards' + gp + '.';
      if ((pos === 'DL' || pos === 'LB' || pos === 'DB') && isNum(v.tkl)) return sur + ' has ' + plural(Number(v.tkl), 'tackle') + (isNum(v.sacks) && v.sacks > 0 ? ' and ' + CC.f(v.sacks, v.sacks % 1 ? 1 : 0) + ' sacks' : '') + gp + '.';
      return gpNow ? sur + ' has played ' + plural(gpNow, 'game') + ' this season.' : '';
    }
    function shortText() {
      var rows = railGroups()[0].rows.filter(function (r) { return isNum(r.pctl) && !r.style; }).map(function (r) { return [r.label, r.pctl]; });
      var tx = lead();
      var top = rows.filter(function (r) { return r[1] >= 90; }).sort(function (x, y) { return y[1] - x[1]; }).slice(0, 2);
      var low = rows.slice().sort(function (x, y) { return x[1] - y[1]; })[0];
      if (top.length) tx += ' In the top ' + Math.max(1, Math.round(100 - Math.min(top[0][1], top[top.length - 1][1]))) + '% of ' + peerShort + ' for ' + top.map(function (r) { return lc(r[0]); }).join(' and ') + '.';
      else if (rows.length) { var avg = rows.reduce(function (x, r) { return x + r[1]; }, 0) / rows.length; tx += avg >= 60 ? ' Above the middle of the pack on most of the numbers that matter.' : avg >= 40 ? ' Around the middle of the pack among ' + peerShort + '.' : ' Below the middle of the pack among ' + peerShort + ' so far.'; }
      if (low && low[1] <= 30 && !(top[0] && top[0][0] === low[0])) tx += ' The weak spot: ' + lc(low[0]) + ' sits in the ' + QK.ordinal(Math.round(low[1])) + ' percentile.';
      if (gpNow && gpNow < (fb ? 5 : 10)) tx += ' Early days, so read it lightly.';
      return tx.trim();
    }
    var hstats = (fb ? (HEAD[pos] || []) : HEAD.bb).filter(function (h0) { return isNum(vals[h0[0]]); }).map(function (h0) { return { label: h0[1], value: fb ? (vals[h0[0]] % 1 ? CC.f(vals[h0[0]], 1) : fmtInt(vals[h0[0]])) : CC.f(vals[h0[0]], 1) }; });
    if (cp && isNum(cp.gp)) hstats.unshift({ label: 'GP', value: String(cp.gp) });
    var short0 = cp ? shortText() : '';
    var crumb = '<nav class="cc-crumb" aria-label="Breadcrumb"><a href="' + esc(CC.href(L, 'players', null, S)) + '">' + esc(CC.LNAME[L]) + '</a><span aria-hidden="true">›</span>' +
      (t ? '<a href="' + esc(CC.teamHref(L, team, cur.season || S)) + '">' + esc(t.short || t.name) + '</a><span aria-hidden="true">›</span>' : '') + esc(name) + '</nav>';
    var html = crumb + QK.playerHeader({ name: name, pos: posLabel(cat, pos) || pos, kicker: CC.seasonLabel(L, cur.season || S) + (gpNow ? ' · ' + plural(gpNow, 'game') + ' in' : ''),
        team: t ? { name: t.short || t.name, abbr: t.abbr, colour: t.colour, href: CC.teamHref(L, team, cur.season || S) } : null,
        meta: [(d && d['class']) || (cp && cp['class']) ? (d && d['class']) || cp['class'] : null, hgt ? hgt + (d && isNum(d.weight_lb) ? ', ' + d.weight_lb + ' lb' : '') : null, d && d.hometown ? 'From ' + d.hometown : null],
        stats: short0 ? null : hstats.slice(0, 4), short: short0 || null, tags: cp && cp.qualified !== false ? [QK.tag('Qualified for percentiles', 'signal')] : [] });
    // stat tiles: ours first
    var k = [];
    if (vr) k.push({ label: fb ? 'Value (EPA above replacement)' : 'Value above replacement', value: CC.f(vr.value, fb ? 1 : 1), signal: true, pctl: isNum(pp.value) ? pp.value : (isNum(vr.pctl) ? vr.pctl : null), sub: isNum(vr.gp) ? vr.gp + ' games · ' + CC.f(vr.value_pg, 2) + ' a game' : '', tip: 'Our value model this season; the chip is the percentile against the same position' });
    if (isNum(vals.epa_play)) k.push({ label: 'EPA per play', value: CC.signed(vals.epa_play, 3), pctl: pp.epa_play, sub: 'expected points added per credited play' });
    if (!fb && isNum(vals.ts)) k.push({ label: 'True shooting', value: CC.pct(vals.ts, 1), pctl: pp.ts, sub: 'points per shooting chance' });
    if (!fb && isNum(vals.r)) k.push({ label: 'Rating per 100', value: CC.signed(vals.r, 1), pctl: pp.r, sub: 'on-court margin per 100 possessions v average' });
    hstats.filter(function (h0) { return h0.label !== 'GP'; }).slice(0, 5 - k.length - (cur.fantasy && isNum(cur.fantasy.proj) ? 1 : 0)).forEach(function (h0) { k.push({ label: h0.label, value: h0.value, sub: fb ? 'this season' : 'a game' }); });
    if (cur.fantasy && isNum(cur.fantasy.proj)) k.push({ label: 'Fantasy projection', value: CC.f(cur.fantasy.proj, 1), sub: 'points next ' + (fb ? 'week' : 'period') });
    html += k.length ? '<div class="cc-tiles">' + U.stats(k.slice(0, 5)) + '</div>' : '';
    if (vr && vr.why) html += QK.note('<b>Why:</b> ' + esc(vr.why));

    /* How sure are we: when the headline numbers are half signal at this playing time (the spec's M50 samples) */
    var small = gpNow < (fb ? 6 : 12);
    var settle = useSpec ? head.filter(function (r) { return r.m.m50 && r.m.mu && !r.style; }).map(function (r) {
      if (r.m.mu === 'games') return [r.label, Math.round(r.m.m50)];
      var n0 = CC.sampleIn(cp, r.m.mu);
      return isNum(n0) && n0 > 0 && gpNow ? [r.label, Math.round(r.m.m50 / (n0 / gpNow))] : null;
    }).filter(function (x) { return x && x[1] > 0 && x[1] < 400; }).slice(0, 3) : [];
    var sureCard = '<article class="qk-card cream"><div class="qk-card-body"><div class="qk-kicker">How sure are we?</div><h3 style="margin:8px 0 6px">' +
      esc(gpNow ? (small ? (gpNow <= 10 ? NUMW[gpNow] : gpNow) + ' game' + (gpNow === 1 ? ' is' : 's is') + ' a small sample' : gpNow + ' games: the picture is settling') : 'No games yet this season') + '</h3>' +
      '<p style="margin:0;color:var(--ink-2);font-size:15px">' + (small ? 'College seasons are short and schedules uneven, so rates swing a lot early on. ' : 'Schedules in college vary a lot, so read a rate with the opponents in mind. ') +
      'The hollow rings on the rail show last season, where the player had one in the same group: dots next to their ring are the steady part of the profile.</p>' +
      (settle.length ? QK.note('At this playing time, ' + settle.map(function (x) { return lc(x[0]) + ' is half signal after about <b>' + plural(x[1], 'game') + '</b>'; }).join('; ') + '.') : '') + '</div></article>';
    var sim = ((d && d.similar) || []).filter(function (s0) { return s0 && s0.id; });
    var typeCard = sim.length ? '<article class="qk-card"><div class="qk-card-body"><div class="qk-kicker">Their type</div><h4 class="cc-h4">Plays most like</h4><ul class="cc-type">' + sim.slice(0, 4).map(function (s0) {
      var same = Number(s0.season) === Number(S);
      return '<li><span><a href="' + esc(CC.playerHref(L, s0.id, s0.season)) + '">' + esc(s0.name || CC.pname(L, s0.id)) + '</a>' + (same ? '' : ' <span class="qk-sub">' + esc(CC.seasonLabel(L, s0.season)) + '</span>') + '</span>' +
        (same ? '<a class="v" href="' + esc(CC.href(L, 'lab', null, S, 'kind=compare&p=' + pid + ',' + s0.id)) + '">Compare</a>' : '<span class="v">distance ' + CC.f(s0.distance, 2) + '</span>') + '</li>'; }).join('') + '</ul>' +
      '<div class="qk-aside" style="margin-top:10px">Closest statistical profiles: a smaller distance is a closer match.</div></div></article>' : '';
    var log = cur.log || [];
    var vkLog = null, LOGK = { value: 'Value', epa: 'EPA', pts: 'Points', pass_yds: 'Passing yards', rush_yds: 'Rushing yards', rec_yds: 'Receiving yards', tkl: 'Tackles', sacks: 'Sacks', fgm: 'Field goals' }, lk = [];
    if (log.length) {
      log.forEach(function (g) { Object.keys(g).forEach(function (k2) { if (lk.indexOf(k2) < 0 && ['game', 'date', 'opp', 'home', 'res'].indexOf(k2) < 0 && isNum(g[k2])) lk.push(k2); }); });
      lk = lk.slice(0, 10);
      var tot = function (k2) { return log.reduce(function (a0, g) { return a0 + (isNum(g[k2]) ? Math.abs(g[k2]) : 0); }, 0); };
      vkLog = ['value', 'epa', 'pts', 'pass_yds', 'rush_yds', 'rec_yds', 'tkl', 'sacks', 'fgm'].filter(function (k2) { return lk.indexOf(k2) >= 0 && tot(k2) > 0; })[0] || null;
    }
    var gbg = log.length && vkLog ? U.card((LOGK[vkLog] || vkLog) + ', game by game', CC.seasonLabel(L, cur.season || S) + '; the best game is marked', U.chart('pp-log', 240, (LOGK[vkLog] || vkLog) + ' per game this season')) : '';
    html += '<section class="qk-section cc-sec1"><div class="qk-gside"><div>' + rail() + '</div><div class="qk-stack">' + sureCard + gbg + typeCard + '</div></div></section>';
    // compare: the player and the two closest matches of this season, the best in each row highlighted (filled below)
    html += '<section class="qk-section" id="pp-cmp-sec" hidden><div id="pp-cmp-h"></div><article class="qk-card"><div class="qk-card-body"><div id="pp-cmp"></div></div></article></section>';
    // next up and last time out
    html += nextLast();
    // ── more on the player
    html += '<section class="qk-section cc-sec">' + QK.sectionHead({ kicker: 'More on the player', title: 'Peers, the long view and moves', sub: 'Where the player sits among ' + esc(peerShort) + ', every game this season, every season on file, and inferred moves.', html: true }) +
      '<div class="qk-grid cc-grid"><div class="qk-span-' + (cp && peerN >= 10 ? 7 : 12) + '">' + (cp && peerN >= 10 ? U.card('Among peers', 'Every qualified ' + esc(peerShort) + ' this season, coloured by percentile', '<div class="qk-seg" id="pp-dist-m" role="group" aria-label="Metric" style="margin-bottom:10px"></div>' + U.chart('pp-dist', 240, 'Distribution of the position group')) : '') + '</div>' +
      '<div class="qk-span-' + (cp && peerN >= 10 ? 5 : 12) + '" id="pp-move"></div></div></section>';
    if (!d) html += '<p class="cc-note">Career pages are kept for players with a game in the last two seasons; this season’s catalogue numbers are shown.</p>';
    if (log.length) {
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
    if (mv.length) {
      html += U.card('Moves', QK.tag('Inferred from box scores, not the official transfer portal'), U.table([{ label: 'Season', align: 'right' }, 'From', 'To', { label: 'Value before', align: 'right' }, { label: 'After', align: 'right' }], mv.map(function (m) {
        return [{ v: m.season, html: m.season ? esc(CC.seasonLabel(L, m.season)) : '—' }, { html: U.teamEnt(L, m.from, { abbr: true }), v: CC.tname(L, m.from) }, { html: U.teamEnt(L, m.to, { abbr: true }), v: CC.tname(L, m.to) }, CC.f(m.value_before, 1), CC.f(m.value_after, 1)];
      }), { sticky: false }));
    }
    el.innerHTML = html;
    U.wire(el);

    /* next up (QK.previewCard) and last time out (the game card with the player's line) */
    function nextLast() {
      if (!team || !CC.isCur(L, S)) return '';
      var info = CC.info(L), T = String(team);
      var cut = Date.now() - 12 * 3600 * 1000;
      var nx = (info.today || []).concat(info.next_games || []).filter(function (c) { return (String(c.home) === T || String(c.away) === T) && c.status !== 'post' && (CC.tba(c) || !(new Date(c.date).getTime() < cut)); })
        .sort(function (x, y) { return String(x.date).localeCompare(String(y.date)); })[0];
      var lastG = log.length ? log[log.length - 1] : null;
      if (!nx && !lastG) return '';
      var out = '<section class="qk-section"><div class="qk-g2">';
      if (nx) {
        var g = CC.game(nx, L);
        g.home.record = CC.rec(L, S, nx.home); g.away.record = CC.rec(L, S, nx.away);
        out += '<div><div class="qk-kicker" style="margin-bottom:10px">' + (nx.status === 'in' ? 'Live now' : 'Next up') + '</div>' + QK.previewCard(g, { kicker: CC.LSHORT[L] + ' · ' + CC.when(nx), nick: function (x) { return x.name; } }) + '</div>';
      }
      if (lastG) {
        var gm = (info.last_games || []).concat(info.today || []).filter(function (c) { return String(c.id) === String(lastG.game) && c.status === 'post'; })[0];
        var Lg = lastG;
        var bits = !fb ? [isNum(Lg.pts) ? plural(Lg.pts, 'point') : '', isNum(Lg.reb) ? plural(Lg.reb, 'rebound') : '', isNum(Lg.ast) ? plural(Lg.ast, 'assist') : '', isNum(Lg.fga) ? Lg.fgm + ' of ' + Lg.fga + ' from the field' : '', isNum(Lg.min) ? CC.f(Lg.min, 0) + ' minutes' : '']
          : [isNum(Lg.pass_att) ? Lg.pass_cmp + ' of ' + Lg.pass_att + ' for ' + Lg.pass_yds + ' yards' : '', isNum(Lg.pass_td) && Lg.pass_td ? plural(Lg.pass_td, 'touchdown pass').replace('touchdown passs', 'touchdown passes') : '', isNum(Lg.rush_car) && Lg.rush_car ? Lg.rush_car + ' carries for ' + Lg.rush_yds + ' yards' : '',
            isNum(Lg.rec) && Lg.rec ? Lg.rec + ' catches for ' + Lg.rec_yds + ' yards' : '', isNum(Lg.tkl) && Lg.tkl ? plural(Lg.tkl, 'tackle') : '', isNum(Lg.sacks) && Lg.sacks ? CC.f(Lg.sacks, Lg.sacks % 1 ? 1 : 0) + ' sacks' : ''];
        var line = bits.filter(Boolean).join(', ');
        out += '<div><div class="qk-kicker" style="margin-bottom:10px">Last time out</div>' + (gm ? CC.card(gm, L, { why: true }) :
          '<article class="qk-card"><div class="qk-card-body"><div class="qk-feature-meta"><span class="qk-pill">' + esc(CC.date(Lg.date)) + '</span></div><h3 style="margin:12px 0 4px"><a href="' + esc(CC.gameHref(L, Lg.game, S)) + '">' + esc((Lg.home ? 'v ' : 'at ') + CC.tname(L, Lg.opp)) + ' · ' + esc(Lg.res || '') + '</a></h3></div></article>') +
          (line ? QK.note('<b>' + esc(sur) + ':</b> ' + esc(line) + '.') : '') + '</div>';
      }
      return out + '</div></section>';
    }

    // last season's ring: the payload's prev_pct_pos when it has one, else last season's catalogue when the rail scrolls into view
    var prevS = CC.seasons(L).filter(function (s0) { return s0 < Number(S); })[0];
    if (!prevPct && cp && prevS) {
      var host = QK.$('#pp-pcard', el), fired = false;
      var go = function () {
        if (fired) return; fired = true;
        CC.load(CC.path(L, prevS, 'players.json')).then(function (pc) {
          if (!U.alive(el) || !CC.ok(pc) || !pc.players) return;
          clean(pc); fillPct(pc);
          var pr = pc.players[pid];
          if (!pr || pr.qualified === false) return;
          var src = useSpec ? (CC.group(L, 'player', pr) === G ? pr[G.pct] : null) : (pr.pos === pos ? (pr.pct_pos || pr.pct) : null);
          if (!src || !Object.keys(src).length) return;
          prevPct = src; prevGp = isNum(pr.gp) ? pr.gp : null;
          var old = QK.$('#pp-pcard', el);
          if (old) old.outerHTML = rail();
        });
      };
      if (host && window.IntersectionObserver) { var io = new IntersectionObserver(function (es) { if (es.some(function (e) { return e.isIntersecting; })) { io.disconnect(); go(); } }, { rootMargin: '200px' }); io.observe(host); } else go();
    }
    // compare: the player and the two closest matches this season, on the group's headline set
    if (cp && useSpec) {
      var ids = [pid].concat(sim.filter(function (s0) { return Number(s0.season) === Number(S); }).map(function (s0) { return String(s0.id); })).filter(function (id) { return cat.players[id] && CC.group(L, 'player', cat.players[id]) === G; }).slice(0, 3);
      if (ids.length >= 2) {
        var E = ids.map(function (id) { return { id: id, p: cat.players[id] }; });
        var best = {};
        var hs = G.m.filter(function (m) { return m.set === 'h' && !m.style && E.some(function (e) { return isNum((e.p.values || {})[m.id]); }); });
        var rowsC = hs.map(function (m) {
          var mt = meta[m.id] || { fmt: /pct|rate|share/.test(m.id) ? 'pct' : '2' };
          var pcs = E.map(function (e) { return (e.p[G.pct] || {})[m.id]; });
          pcs.forEach(function (v, i) { if (!isNum(v)) return; var dd = v - Math.max.apply(null, pcs.filter(function (_, j) { return j !== i; }).map(function (z) { return isNum(z) ? z : 0; })); if (!best[i] || dd > best[i].d) best[i] = { m: m, d: dd, v: (E[i].p.values || {})[m.id], mt: mt }; });
          return { label: m.d, tip: m.x || '', better: m.low ? 'low' : 'high', values: E.map(function (e) { return (e.p.values || {})[m.id]; }), pctls: pcs, fmt: function (v) { return CC.fmtMetric(mt, v); } };
        });
        var names = E.map(function (e) { return String(e.p.name || '').split(' ').slice(-1)[0]; });
        QK.$('#pp-cmp-h', el).innerHTML = QK.sectionHead({ kicker: 'Compare', title: names.slice(0, -1).join(', ') + ' or ' + names[names.length - 1] + '?',
          sub: 'The closest matches on this season’s profile, side by side against ' + G.d.toLowerCase() + '. The best in each row is highlighted; the small pills are percentiles.',
          actions: '<a class="qk-more" href="' + esc(CC.href(L, 'lab', null, S, 'kind=compare&p=' + ids.join(','))) + '">Open in Compare</a>' });
        var ents = E.map(function (e) { return { name: e.p.name, href: CC.playerHref(L, e.id, S), sub: [CC.tabbr(L, e.p.team), e.p.pos, isNum(e.p.gp) ? e.p.gp + ' GP' : ''].filter(Boolean).join(' · ') }; });
        var verd = E.map(function (e, i) { return best[i] && best[i].d > 0 ? { title: ARCHETYPE[best[i].m.id] || 'The standout', who: names[i], text: 'best of the ' + E.length + ' on ' + lc(best[i].m.d) + ' (' + CC.fmtMetric(best[i].mt, best[i].v) + ').' } : null; });
        QK.$('#pp-cmp', el).innerHTML = QK.compareView({ entities: ents, groups: [{ label: '', rows: rowsC }], delta: false }) + QK.verdicts(verd);
        QK.$('#pp-cmp-sec', el).hidden = false;
      }
    }
    // where the player sits
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
          marks: (isNum(vals[key]) ? [{ x: vals[key], label: sur }] : []).concat([{ x: med, label: 'Median' }]), label: 'Distribution of ' + (mm.label || key) });
      };
      if (opts.length) { drawDist(opts[0].key); QK.seg(segEl, drawDist); }
    }
    // game by game, the best game marked
    if (log.length && vkLog && QK.$('#pp-log', el)) {
      var bi = -1, bv = -1e9;
      log.forEach(function (g, i) { var v = isNum(g[vkLog]) ? g[vkLog] : -1e9; if (v > bv) { bv = v; bi = i; } });
      var lab = LOGK[vkLog] || vkLog;
      QKC.mount('#pp-log', function (T) {
        var xa = QKC.axis(T, { type: 'category', data: log.map(function (g) { return (g.home ? 'v ' : '@ ') + CC.tabbr(L, g.opp); }), split: false, line: true });
        xa.axisLabel.interval = log.length > 14 ? 'auto' : 0; xa.axisLabel.fontSize = log.length > 10 ? 10 : 11.5;
        var ya = QKC.axis(T, { fmt: function (v) { return CC.f(v, 0); } });
        ya.max = function (v) { if (!(v.max > 0)) return 1; var x = v.max * 1.2, p = Math.pow(10, Math.floor(Math.log(x) / Math.LN10)), n = [1, 2, 2.5, 5, 10].filter(function (k) { return k * p >= x; })[0]; return n * p; };
        var gB = 26 + QKC.nameAxis(xa, 'Opponent, in date order', 'bottom'), gT = 26 + QKC.nameAxis(ya, lab + ' in the game', 'side');
        return { grid: { left: 8, right: 12, top: gT, bottom: gB, containLabel: true }, xAxis: xa, yAxis: ya,
          tooltip: QKC.tooltip(T, { trigger: 'axis', axisPointer: { type: 'shadow', shadowStyle: { color: 'rgba(255,201,77,.08)' } }, formatter: function (ps) { var g = log[ps[0].dataIndex]; return '<b>' + esc(CC.date(g.date) + ' · ' + (g.home ? 'v ' : 'at ') + CC.tname(L, g.opp) + ' · ' + (g.res || '')) + '</b>' + QKC.tipRow(T.model, lab, CC.f(g[vkLog], vkLog === 'value' || vkLog === 'epa' ? 1 : 0)); } }),
          series: [{ type: 'bar', name: lab, barMaxWidth: 30, data: log.map(function (g, i) {
            var v = isNum(g[vkLog]) ? g[vkLog] : 0;
            var o = { value: v, itemStyle: { color: v < 0 ? T.coral : T.model, borderRadius: v < 0 ? [0, 0, 6, 6] : [6, 6, 0, 0] } };
            if (i === bi && bv > 0 && log.length >= 3) o.label = Object.assign(QKC.annot(T), { show: true, position: 'top', formatter: 'best: ' + CC.f(bv, vkLog === 'value' || vkLog === 'epa' ? 1 : 0) });
            return o; }) }] };
      }, { label: lab + ' per game this season' });
    }
    movementCard(L, S, pid, team, QK.$('#pp-move', el));
  });
});
function fmtInt(v) { return isNum(v) ? String(Math.round(v)) : '—'; }

})(window.CC);
