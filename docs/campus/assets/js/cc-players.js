/* The Quant Campus — Players (#/<L>/players) and the player page (#/<L>/player/<pid>).
 * Catalogue: every player with the payload's metrics and percentiles (all players or within the position),
 * position chips, team search, the qualified-only floor. Player page: season-by-season, this season's game log with a
 * value-per-game chart, percentile bars, value row, inferred moves and similar players.
 * Reads <L>/<S>/players.json, <L>/players/<pid>.json (career). */
(function (CC) {
'use strict';
var U = CC.ui, esc = CC.esc, isNum = CC.isNum;

CC.route('players', function (el, p) {
  var L = p.L, S = p.S, fb = CC.fb(L), q0 = p.query || {};
  el.innerHTML = U.head('Players', '', U.kicker(L, S)) + QK.skeleton('lines', 8);
  return Promise.all([CC.load(CC.path(L, S, 'players.json')), CC.season(L, S)]).then(function (a) {
    if (!U.alive(el)) return;
    var cat = a[0];
    if (!CC.ok(cat) || !Object.keys(cat.players || {}).length) { el.innerHTML = U.head('Players', '', U.kicker(L, S)) + (CC.ok(cat) ? QK.empty('No player stats yet', 'Player numbers appear once games have been played this season. Try last season with the season picker.') : U.missing('The player catalogue', cat)); return; }
    CC.addPlayers(L, cat.players);
    Object.keys(cat.players).forEach(function (k) { var nm = String(cat.players[k].name || '').trim(); if (!nm || nm === 'Team' || nm === 'TEAM') delete cat.players[k]; });
    var mets = (cat.metrics || []).slice(0, 9), P = cat.players, ids = Object.keys(P);
    var pos = Object.keys(cat.positions || {}).sort(function (x, y) { return ((cat.positions[y] || {}).n || 0) - ((cat.positions[x] || {}).n || 0); });
    var st = { pos: q0.pos || 'all', q: '', qual: true, within: false, sort: mets[0] ? mets[0].key : null };
    el.innerHTML = U.head('Players', 'Season numbers with percentiles against qualified players (or within the position). ' + esc(Object.keys(P).length + ' players') + '.', U.kicker(L, S)) +
      '<div class="cc-toolbar"><input class="qk-input" type="search" id="pl-q" placeholder="Find a player or team" aria-label="Find a player or team">' +
      '<label class="cc-check"><input type="checkbox" id="pl-qual" checked> Qualified only</label><label class="cc-check"><input type="checkbox" id="pl-within"> Percentiles within position</label></div>' +
      '<div class="qk-chips scroll cc-filters" id="pl-pos" role="group" aria-label="Position">' + ['all'].concat(pos).map(function (k) {
        return '<button type="button" class="qk-chip" style="--ca:var(--accent)" data-value="' + esc(k) + '" aria-pressed="' + (k === st.pos) + '">' + esc(k === 'all' ? 'All' : ((cat.positions[k] || {}).label || k)) + (k !== 'all' ? ' <span class="n">' + ((cat.positions[k] || {}).n || '') + '</span>' : '') + '</button>'; }).join('') + '</div>' +
      '<div id="pl-table"></div>';
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
      var cols = ['Player', 'Team', 'Pos', 'Class', { label: 'GP', align: 'right' }].concat(mets.map(function (m) { return { label: m.label, align: 'right', title: m.desc || '' }; }));
      QK.$('#pl-table', el).innerHTML = U.card(rs.length + ' players', rs.length > shown.length ? 'Showing the top 400 by ' + esc((mets[0] || {}).label || 'value') + '; search to find anyone.' : '', U.table(cols, shown.map(function (k) {
        var x = P[k], pc = st.within ? (x.pct_pos || {}) : (x.pct || {});
        return { cells: [{ html: '<a href="' + esc(CC.playerHref(L, k, S)) + '">' + esc(x.name) + '</a>', v: x.name }, { html: U.teamEnt(L, x.team, { season: S, abbr: true }), v: CC.tname(L, x.team) }, esc(x.pos || '—'), esc(x['class'] || '—'), isNum(x.gp) ? x.gp : '—'].concat(mets.map(function (m) {
          var v = (x.values || {})[m.key];
          return { v: isNum(v) ? v : null, html: '<span class="cc-num">' + CC.fmtMetric(m, v) + '</span>' + (isNum(pc[m.key]) ? QK.pctlChip(pc[m.key]) : '') };
        })), _href: CC.playerHref(L, k, S) };
      }), { maxHeight: 760 }));
      U.wire(QK.$('#pl-table', el));
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

CC.route('player', function (el, p) {
  var L = p.L, S = p.S, pid = p.id, fb = CC.fb(L);
  el.innerHTML = QK.skeleton('lines', 8);
  return Promise.all([CC.load(CC.lpath(L, 'players/' + pid + '.json')), CC.load(CC.path(L, S, 'players.json')), CC.season(L, S)]).then(function (a) {
    if (!U.alive(el)) return;
    var d = CC.ok(a[0]) ? a[0] : null, cat = CC.ok(a[1]) ? a[1] : null;
    var cp = cat && cat.players ? cat.players[pid] : null;
    if (!d && !cp) { el.innerHTML = U.head('Player', '', U.kicker(L, S)) + QK.empty('Player not found', 'No career file for this player (careers are kept for players with a game in the last two seasons).'); return; }
    var cur = (d && d.current) || {};
    var team = cur.team || (cp && cp.team) || null;
    var t = team ? CC.team(L, team) : null;
    var name = (d && d.name) || (cp && cp.name) || ('Player ' + pid);
    var hgt = d && isNum(d.height_in) ? Math.floor(d.height_in / 12) + '′' + (d.height_in % 12) + '″' : null;
    var meta = [(d && d.pos) || (cp && cp.pos), (d && d['class']) || (cp && cp['class']), hgt, d && isNum(d.weight_lb) ? d.weight_lb + ' lb' : null, d && d.hometown ? d.hometown : null].filter(Boolean);
    var vr = cur.value || null;
    var html = '<section class="qk-hero cc-hero"' + (t && QK.color.parse(t.colour) ? ' style="--tc:' + esc(t.colour) + '"' : '') + '><div class="qk-hero-in"><span class="qk-avatar cc-avatar" aria-hidden="true">' + esc(QK.fmt.initials(name)) + '</span><div class="cc-hero-id"><div class="qk-kicker">' + esc(CC.LNAME[L]) + '</div><h1>' + esc(name) + '</h1>' +
      '<div class="qk-hero-meta">' + (team ? '<span>' + U.teamEnt(L, team, { season: cur.season || S }) + '</span>' : '') + meta.map(function (m) { return '<span>' + esc(m) + '</span>'; }).join('') + '</div></div>' +
      (vr ? '<div class="qk-hero-stats"><div class="qk-hero-stat"><div class="v">' + CC.f(vr.value, fb ? 1 : 2) + '</div><div class="l">' + (fb ? 'EPA above repl.' : 'Value') + '</div></div><div class="qk-hero-stat"><div class="v">' + (isNum(vr.pctl) ? Math.round(vr.pctl) : '—') + '</div><div class="l">Percentile</div></div><div class="qk-hero-stat"><div class="v">' + (isNum(vr.gp) ? vr.gp : '—') + '</div><div class="l">Games</div></div></div>' : '') + '</div></section>';
    if (vr && vr.why) html += '<p class="cc-note">' + esc(vr.why) + '</p>';
    if (!d) {
      html += '<p class="cc-note">Career pages are kept for players with a game in the last two seasons; this season’s catalogue numbers are shown.</p>';
      if (cp && cat.metrics) html += U.card(CC.seasonLabel(L, S) + ' season', (isNum(cp.gp) ? cp.gp + ' games' : '') + (cp.qualified === false ? ' · below the qualifying floor' : ''),
        U.table(['Stat', { label: 'Value', align: 'right' }, { label: 'Pctl', align: 'right' }], cat.metrics.filter(function (m) { return isNum((cp.values || {})[m.key]); }).map(function (m) {
          var pc = (cp.pct || {})[m.key];
          return [{ html: esc(m.label) + (m.desc ? ' <span class="qk-muted">' + esc(m.desc) + '</span>' : ''), v: m.label }, { v: cp.values[m.key], html: CC.fmtMetric(m, cp.values[m.key]) }, isNum(pc) ? { v: pc, html: QK.pctlChip(pc) } : '—'];
        }), { sticky: false }));
    }
    // percentiles from the catalogue
    var hasPct = cp && cp.pct && Object.keys(cp.pct).length;
    if (cp && cat.metrics && hasPct) {
      var bars = cat.metrics.filter(function (m) { return isNum((cp.pct || {})[m.key]); }).map(function (m) { return { label: m.label, pctl: cp.pct[m.key], value: CC.fmtMetric(m, (cp.values || {})[m.key]) }; });
      var barsPos = cat.metrics.filter(function (m) { return isNum((cp.pct_pos || {})[m.key]); }).map(function (m) { return { label: m.label, pctl: cp.pct_pos[m.key], value: CC.fmtMetric(m, (cp.values || {})[m.key]) }; });
      html += '<div class="qk-grid cc-grid"><div class="qk-span-6">' + U.card('Percentiles', 'Against qualified players' + (cp.qualified === false ? ' (below the qualifying floor: read with care)' : '') + '.', bars.length ? QK.pctlBars(bars) : QK.empty('No percentiles', '')) + '</div>' +
        '<div class="qk-span-6">' + U.card('Within the position', esc(cp.pos || ''), barsPos.length ? QK.pctlBars(barsPos) : QK.empty('No position percentiles', '')) + '</div></div>';
    }
    var log = cur.log || [];
    if (log.length) {
      var lk = [];
      log.forEach(function (g) { Object.keys(g).forEach(function (k) { if (lk.indexOf(k) < 0 && ['game', 'date', 'opp', 'home', 'res'].indexOf(k) < 0 && isNum(g[k])) lk.push(k); }); });
      lk = lk.slice(0, 10);
      var LOGK = { value: 'Value', epa: 'EPA', pts: 'Points', pass_yds: 'Passing yards', rush_yds: 'Rushing yards', rec_yds: 'Receiving yards', tkl: 'Tackles', sacks: 'Sacks', fgm: 'Field goals' };
      var tot = function (k) { return log.reduce(function (a, g) { return a + (isNum(g[k]) ? Math.abs(g[k]) : 0); }, 0); };
      var vk = ['value', 'epa', 'pts', 'pass_yds', 'rush_yds', 'rec_yds', 'tkl', 'sacks', 'fgm'].filter(function (k) { return lk.indexOf(k) >= 0 && tot(k) > 0; })[0] || null;
      html += '<div class="qk-grid cc-grid"><div class="qk-span-5">' + U.card(vk ? LOGK[vk] + ' game by game' : 'Game by game', CC.seasonLabel(L, cur.season || S), vk ? U.chart('pp-log', 240, (LOGK[vk] || vk) + ' per game this season') : QK.empty('No per-game numbers', '')) + '</div><div class="qk-span-7">' +
        U.card('Game log', '', U.table(['Date', 'Opp', 'Result'].concat(lk.map(function (k) { return { label: k.replace(/_/g, ' ').toUpperCase(), align: 'right' }; })), log.slice().reverse().map(function (g) {
          return { cells: [{ v: g.date, html: esc(CC.date(g.date)) }, { html: (g.home ? '' : '@ ') + U.teamEnt(L, g.opp, { season: cur.season || S, abbr: true }), v: CC.tname(L, g.opp) }, { html: '<a href="' + esc(CC.gameHref(L, g.game, cur.season || S)) + '">' + esc(g.res || '') + '</a>', v: g.res }].concat(lk.map(function (k) { return isNum(g[k]) ? (Math.round(g[k] * 100) / 100) : '—'; })), _href: CC.gameHref(L, g.game, cur.season || S) };
        }), { maxHeight: 420 })) + '</div></div>';
    }
    var seasons = ((d && d.seasons) || []).map(flat);
    if (seasons.length) {
      var C = (fb ? SEASON_COLS.cfb : SEASON_COLS.bb).filter(function (c) { return seasons.some(function (r) { return isNum(r[c[0]]); }); });
      html += U.card('Season by season', '', U.table([{ label: 'Season', align: 'right' }, 'Team'].concat(C.map(function (c) { return { label: c[1], align: 'right' }; })), seasons.slice().sort(function (x, y) { return y.season - x.season; }).map(function (r) {
        return [{ v: r.season, html: esc(CC.seasonLabel(L, r.season)) }, { html: U.teamEnt(L, r.team, { season: r.season, abbr: true }), v: CC.tname(L, r.team) }].concat(C.map(function (c) {
          var v = r[c[0]];
          return !isNum(v) ? '—' : (c[2] === 'pct' ? { v: v, html: CC.pct(v, 1) } : (Math.round(v) === v ? v : { v: v, html: CC.f(v, c[0] === 'epa_play' || c[0] === 'value_pg' ? 3 : 1) }));
        }));
      })));
    }
    var mv = (d && d.moves) || [];
    var sim = (d && d.similar) || [];
    if (mv.length || sim.length) {
      html += '<div class="qk-grid cc-grid">' + (mv.length ? '<div class="qk-span-6">' + U.card('Moves', 'Inferred from box scores and rosters; not the official transfer portal.', U.table([{ label: 'Season', align: 'right' }, 'From', 'To', { label: 'Value before', align: 'right' }, { label: 'After', align: 'right' }], mv.map(function (m) {
        return [{ v: m.season, html: m.season ? esc(CC.seasonLabel(L, m.season)) : '—' }, { html: U.teamEnt(L, m.from, { abbr: true }), v: CC.tname(L, m.from) }, { html: U.teamEnt(L, m.to, { abbr: true }), v: CC.tname(L, m.to) }, CC.f(m.value_before, 1), CC.f(m.value_after, 1)];
      }), { sticky: false })) + '</div>' : '') + (sim.length ? '<div class="qk-span-6">' + U.card('Similar players', 'Closest statistical profiles.', '<ul class="cc-list">' + sim.map(function (s) {
        return '<li><a href="' + esc(CC.playerHref(L, s.id, s.season)) + '">' + esc(s.name || CC.pname(L, s.id)) + '</a><span class="s">' + esc(CC.seasonLabel(L, s.season)) + '</span><span class="v">' + CC.f(s.distance, 2) + '</span></li>'; }).join('') + '</ul>') + '</div>' : '') + '</div>';
    }
    el.innerHTML = html;
    U.wire(el);
    if (log.length && QK.$('#pp-log', el)) {
      if (vk) QKC.bar('#pp-log', { cats: log.map(function (g) { return CC.tabbr(L, g.opp); }), series: [{ name: LOGK[vk] || vk, data: log.map(function (g) { return isNum(g[vk]) ? g[vk] : 0; }) }], diverging: vk === 'value' || vk === 'epa', valName: LOGK[vk] || vk, fmt: function (v) { return CC.f(v, 1); }, hrefs: log.map(function (g) { return CC.gameHref(L, g.game, cur.season || S); }) });
    }
  });
});

})(window.CC);
