/* The Quant Campus — Games (#/<L>/games) and the game centre (#/<L>/game/<gid>).
 * Games: by week (cfb: weeks, championship week, bowls, playoff) or by day (basketball), filters for ranked teams,
 * conference games, a conference, close lines and model-v-market gaps. Reads <L>/<S>/schedule.json.
 * Game centre: score and status, pregame model v market, win probability (model and ESPN), score flow, drives and
 * EPA (cfb), highest-leverage plays, box scores, team stats, leaders. Reads <L>/<S>/games/<gid>.json and falls back
 * to the schedule CARD when a game has no page (game pages exist for the current season and last postseason). */
(function (CC) {
'use strict';
var U = CC.ui, esc = CC.esc, isNum = CC.isNum;

function weekKey(c) {
  if (c.stype === 'cfp') return 'cfp';
  if (c.stype === 'bowl') return 'bowls';
  if (c.stype === 'conf') return 'champ';
  return isNum(c.week) ? 'w' + c.week : 'other';
}
var WK_LABEL = { cfp: 'Playoff', bowls: 'Bowls', champ: 'Championships', other: 'Other' };
function wkLabel(k) { return WK_LABEL[k] || ('Week ' + k.slice(1)); }
function dayKey(iso) { return QK.fmt.dayKey(iso); }
function isClose(c) {
  var mk = c.market || {}, m = c.model || {};
  if (isNum(mk.spread_home)) return Math.abs(mk.spread_home) <= (CC.fb(CC.state.L) ? 7 : 5);
  return isNum(m.p_home) && Math.abs(m.p_home - 0.5) <= 0.15;
}
function gap(c) { var mk = c.market || {}, m = c.model || {}; return isNum(mk.p_home) && isNum(m.p_home) ? m.p_home - mk.p_home : null; }

CC.route('games', function (el, p) {
  var L = p.L, S = p.S, fb = CC.fb(L), q = p.query || {};
  el.innerHTML = U.head('Games', '', U.kicker(L, S)) + QK.skeleton('card', 6);
  return Promise.all([CC.load(CC.path(L, S, 'schedule.json')), CC.season(L, S)]).then(function (a) {
    if (!U.alive(el)) return;
    var sch = a[0];
    if (!CC.ok(sch)) { el.innerHTML = U.head('Games', '', U.kicker(L, S)) + U.missing('The schedule', sch); return; }
    var cards = (sch.games || []).slice().sort(function (x, y) { return String(x.date).localeCompare(String(y.date)); });
    var keys = [], byKey = {};
    cards.forEach(function (c) { var k = fb ? weekKey(c) : dayKey(CC.gameDate(c)); if (!byKey[k]) { byKey[k] = []; keys.push(k); } byKey[k].push(c); });
    if (fb) {
      var ord = function (k) { return k.charAt(0) === 'w' ? Number(k.slice(1)) : { champ: 100, bowls: 101, cfp: 102, other: 103 }[k]; };
      keys.sort(function (x, y) { return ord(x) - ord(y); });
    }
    if (!keys.length) { el.innerHTML = U.head('Games', '', U.kicker(L, S)) + QK.empty('No games yet', 'The schedule for this season has not been published.'); return; }
    var info = CC.info(L), now = new Date();
    var dflt;
    if (fb) {
      dflt = CC.isCur(L, S) && isNum(info.week) && byKey['w' + info.week] ? 'w' + info.week : null;
      if (!dflt) { var pend = keys.filter(function (k) { return byKey[k].some(function (c) { return c.status !== 'post'; }); }); dflt = CC.isCur(L, S) && pend.length ? pend[0] : keys[keys.length - 1]; }
    } else {
      var td = dayKey(now.toISOString());
      dflt = byKey[td] ? td : (keys.filter(function (k) { return k >= td; })[0] || keys[keys.length - 1]);
      if (!CC.isCur(L, S)) dflt = keys[keys.length - 1];
    }
    var cur = q.w && byKey[q.w] ? q.w : (q.d && byKey[q.d] ? q.d : dflt);
    var flt = { ranked: false, conf: false, close: false, edge: false, cid: q.conf || '' };
    var confs = {};
    cards.forEach(function (c) { [c.home, c.away].forEach(function (t) { var tm = CC.team(L, t); if (tm && tm.member && tm.conference) confs[tm.conference] = 1; }); });
    var confOpts = '<option value="">All conferences</option>' + Object.keys(confs).sort(function (x, y) { return CC.cname(L, x).localeCompare(CC.cname(L, y)); }).map(function (c) { return '<option value="' + esc(c) + '">' + esc(CC.cname(L, c)) + '</option>'; }).join('');
    var i = keys.indexOf(cur);
    var nav = '<div class="cc-pager"><button class="qk-btn" type="button" id="g-prev" aria-label="Previous"' + (i <= 0 ? ' disabled' : '') + '>←</button>' +
      '<select class="qk-select" id="g-key" aria-label="' + (fb ? 'Week' : 'Day') + '">' + keys.map(function (k) {
        var n = byKey[k].length; return '<option value="' + esc(k) + '"' + (k === cur ? ' selected' : '') + '>' + esc(fb ? wkLabel(k) : CC.date(k + 'T12:00:00Z')) + ' · ' + n + ' game' + (n > 1 ? 's' : '') + '</option>';
      }).join('') + '</select><button class="qk-btn" type="button" id="g-next" aria-label="Next"' + (i >= keys.length - 1 ? ' disabled' : '') + '>→</button></div>';
    var chips = '<div class="qk-chips scroll cc-filters" id="g-chips" role="group" aria-label="Filters">' +
      [['ranked', fb ? 'Ranked' : 'Ranked or seeded'], ['conf', 'Conference games'], ['close', 'Close lines'], ['edge', 'Model v market gap']].map(function (x) {
        return '<button type="button" class="qk-chip" style="--ca:var(--accent)" data-value="' + x[0] + '" aria-pressed="false">' + esc(x[1]) + '</button>'; }).join('') + '</div>';
    el.innerHTML = U.head('Games', fb ? 'Every game involving an FBS team, week by week, with our pregame win probability and the market.' : 'Every game involving a Division I team, day by day, with our pregame win probability and the market.', U.kicker(L, S)) +
      '<div class="cc-toolbar">' + nav + '<select class="qk-select" id="g-conf" aria-label="Conference">' + confOpts + '</select></div>' + chips + '<div id="g-sum" class="cc-note"></div><div id="g-list"></div>';
    QK.$('#g-conf', el).value = flt.cid;
    function paint() {
      var list = byKey[cur].filter(function (c) {
        if (flt.ranked && !(c.hr || c.ar || c.hseed || c.aseed)) return false;
        if (flt.conf && !c.conf_game) return false;
        if (flt.close && !isClose(c)) return false;
        if (flt.edge) { var g = gap(c); if (!isNum(g) || Math.abs(g) < 0.05) return false; }
        if (flt.cid) { var h = CC.team(L, c.home) || {}, w = CC.team(L, c.away) || {}; if (String(h.conference) !== flt.cid && String(w.conference) !== flt.cid) return false; }
        return true;
      });
      var fin = list.filter(function (c) { return c.status === 'post' && c.result; });
      var right = fin.filter(function (c) { return c.result.model_correct === true; }).length;
      var ats = fin.filter(function (c) { return c.result.cover && c.result.cover !== 'push' && c.market; });
      QK.$('#g-sum', el).innerHTML = list.length + ' game' + (list.length === 1 ? '' : 's') + (fin.length ? ' · the model picked the winner in <b>' + right + ' of ' + fin.length + '</b>' : '') +
        (ats.length ? ' · lines on ' + ats.length : '');
      if (!list.length) { QK.$('#g-list', el).innerHTML = QK.empty('No games match', 'Clear a filter or pick another ' + (fb ? 'week' : 'day') + '.'); return; }
      var html = '', last = null;
      list.forEach(function (c) {
        var d = dayKey(CC.gameDate(c));
        if (d !== last) { if (last !== null) html += '</div>'; html += '<div class="cc-day">' + esc(CC.date(CC.gameDate(c))) + '</div><div class="cc-games">'; last = d; }
        html += CC.card(c, L);
      });
      QK.$('#g-list', el).innerHTML = html + '</div>';
    }
    function go(k) { CC.go(CC.href(L, 'games', null, S, (fb ? 'w=' : 'd=') + k)); }
    QK.$('#g-key', el).addEventListener('change', function (e) { go(e.target.value); });
    QK.$('#g-prev', el).addEventListener('click', function () { if (i > 0) go(keys[i - 1]); });
    QK.$('#g-next', el).addEventListener('click', function () { if (i < keys.length - 1) go(keys[i + 1]); });
    QK.$('#g-conf', el).addEventListener('change', function (e) { flt.cid = e.target.value; paint(); });
    QK.chips(QK.$('#g-chips', el), function (v) { flt.ranked = v.indexOf('ranked') >= 0; flt.conf = v.indexOf('conf') >= 0; flt.close = v.indexOf('close') >= 0; flt.edge = v.indexOf('edge') >= 0; paint(); }, true);
    paint();
  });
});

/* ── game centre ─────────────────────────────────────────────────────── */
function clockLabel(L, season, t) {
  if (!isNum(t)) return '';
  if (CC.fb(L)) { var q = Math.min(5, Math.floor(t / 15) + 1); return q > 4 ? 'OT' : 'Q' + q + ' ' + fmtClock(15 - (t - (q - 1) * 15)); }
  var halves = L === 'mbb' || Number(season) < 2016, len = halves ? 20 : 10, n = halves ? 2 : 4, reg = len * n;
  if (t >= reg) return 'OT';
  var k = Math.floor(t / len) + 1;
  return (halves ? 'H' : 'Q') + k + ' ' + fmtClock(len - (t - (k - 1) * len));
}
function perLabel(L, season, p) {
  if (!isNum(p)) return '';
  if (CC.fb(L)) return p > 4 ? 'OT' : 'Q' + p;
  var halves = L === 'mbb' || Number(season) < 2016, n = halves ? 2 : 4;
  return p > n ? 'OT' + (p - n > 1 ? p - n : '') : (halves ? 'H' : 'Q') + p;
}
function fmtClock(m) { m = Math.max(0, m); var s = Math.round(m * 60); return Math.floor(s / 60) + ':' + ('0' + (s % 60)).slice(-2); }
function breaks(L, season, tMax) {
  var out = [];
  if (CC.fb(L)) { [15, 30, 45, 60].forEach(function (x) { if (x < tMax) out.push(x); }); return out; }
  var halves = L === 'mbb' || Number(season) < 2016, len = halves ? 20 : 10, n = halves ? 2 : 4;
  for (var k = 1; k <= n; k++) if (k * len < tMax) out.push(k * len);
  for (var x = n * len + 5; x < tMax; x += 5) out.push(x);
  return out;
}
function ydLine(yte) { if (!isNum(yte)) return '—'; return yte > 50 ? 'Own ' + (100 - yte) : yte === 50 ? '50' : 'Opp ' + yte; }

function hero(L, g) {
  var st = CC.status(g), fin = st === 'final';
  var h = CC.team(L, g.home) || { name: 'Team ' + g.home }, a = CC.team(L, g.away) || { name: 'Team ' + g.away };
  var tag = CC.roundLabel(g) || (g.conf_game ? 'Conference game' : 'Non-conference');
  function side(t, tid, sc, won, rk) {
    return '<a class="cc-gh-team' + (fin && !won ? ' lost' : '') + '" href="' + esc(CC.teamHref(L, tid, g.season)) + '">' + QK.teamMark(t, 'lg') + '<span class="nm">' + esc(rk) + esc(t.short || t.name) + '</span>' +
      '<span class="sc">' + (st !== 'pre' && isNum(sc) ? sc : '') + '</span></a>';
  }
  var hw = isNum(g.hs) && isNum(g.as) ? g.hs > g.as : false;
  var rk = function (side0) { var s = side0 === 'home' ? g.hseed : g.aseed, r = side0 === 'home' ? g.hr : g.ar; return isNum(s) && (g.stype === 'ncaa' || g.stype === 'cfp') ? '(' + s + ') ' : (isNum(r) && r <= 25 ? '#' + r + ' ' : ''); };
  var badge = st === 'live' ? '<span class="qk-badge live">Live</span>' : fin ? '<span class="qk-badge final">Final' + (isNum(g.periods) && g.periods > (CC.fb(L) ? 4 : (L === 'mbb' ? 2 : 4)) ? '/OT' : '') + '</span>' : '<span class="qk-badge">' + esc(CC.when(g)) + '</span>';
  var venue = g.venue && g.venue.name ? g.venue.name + (g.venue.city ? ', ' + g.venue.city : '') + (g.venue.state ? ', ' + g.venue.state : '') : '';
  return '<section class="qk-hero cc-gh" style="--tc:' + esc(QK.color.parse(h.colour) ? h.colour : 'var(--accent)') + '"><div class="cc-gh-top"><span class="qk-kicker">' + esc(CC.LSHORT[L] + ' · ' + CC.seasonLabel(L, g.season) + ' · ' + tag + (isNum(g.week) && g.stype === 'reg' ? ' · Week ' + g.week : '')) + '</span>' + badge + '</div>' +
    '<div class="cc-gh-teams">' + side(a, g.away, g.as, !hw, rk('away')) + '<span class="cc-gh-at">' + (g.neutral ? 'v' : '@') + '</span>' + side(h, g.home, g.hs, hw, rk('home')) + '</div>' +
    '<div class="qk-hero-meta">' + (venue ? '<span>' + esc(venue) + (g.neutral ? ' (neutral)' : '') + '</span>' : '') + (isNum(g.attendance) ? '<span>Attendance <b>' + QK.fmt.num(g.attendance) + '</b></span>' : '') +
    (g.note && g.stype === 'reg' ? '<span>' + esc(g.note) + '</span>' : '') + '<span>' + esc(CC.when(g)) + '</span></div></section>';
}

function pregame(L, g) {
  var pg = g.pregame || {}, m = pg.model || g.model || {}, mk = pg.market || g.market || null;
  var h = CC.tshort(L, g.home), a = CC.tshort(L, g.away);
  var rows = [];
  rows.push(['Home win probability', CC.pct(m.p_home, 1), mk && isNum(mk.p_home) ? CC.pct(mk.p_home, 1) : '—']);
  var fair = isNum(m.spread_fair) ? m.spread_fair : (isNum(m.margin) ? -m.margin : null);
  rows.push(['Spread (' + h + ')', CC.spread(fair), mk && isNum(mk.spread_home) ? CC.spread(mk.spread_home) : '—']);
  rows.push(['Total points', CC.f(m.total, 1), mk && isNum(mk.total) ? CC.f(mk.total, 1) : '—']);
  if (isNum(pg.espn_predictor)) rows.push(['ESPN predictor (home)', CC.pct(pg.espn_predictor, 1), '']);
  if (isNum(pg.elo_p_home)) rows.push(['Elo baseline (home)', CC.pct(pg.elo_p_home, 1), '']);
  var tbl = U.table(['', { label: 'Model', align: 'right' }, { label: 'Market', align: 'right' }], rows, { sticky: false });
  var bar = isNum(m.p_home) ? QK.probBar(1 - m.p_home, null, m.p_home, CC.team(L, g.away), CC.team(L, g.home)) + '<div class="cc-pb-lab"><span>' + esc(a) + ' ' + CC.pct(1 - m.p_home) + '</span><span>' + esc(h) + ' ' + CC.pct(m.p_home) + '</span></div>' : '';
  var mvm = mk && isNum(mk.p_home) && isNum(m.p_home) ? QK.mvm(m.p_home, mk.p_home, h + ' win') : '';
  var res = '';
  if (g.result && CC.status(g) === 'final') {
    res = '<div class="cc-chips-row">' + (g.result.model_correct === true ? '<span class="qk-badge accent">Model picked the winner</span>' : g.result.model_correct === false ? '<span class="qk-badge">Model missed</span>' : '') +
      (g.result.cover ? '<span class="qk-badge">' + esc(g.result.cover === 'push' ? 'Push against the spread' : CC.tshort(L, g.result.cover === 'home' ? g.home : g.away) + ' covered') + '</span>' : '') + '</div>';
  }
  var src = mk && mk.source ? { kalshi: 'Kalshi', polymarket: 'Polymarket', espn_close: 'ESPN closing line', espn: 'ESPN line' }[mk.source] || mk.source : null;
  return U.card('Before the game', 'Model against the market' + (src ? ' (' + esc(src) + ')' : '') + '. ' + (isNum(m.sd) ? 'Margin uncertainty ± ' + CC.f(m.sd, 1) + ' points.' : ''), '<div class="qk-stack">' + bar + mvm + tbl + res + '</div>');
}

function teamStats(L, g) {
  var ts = g.team_stats || {}, bx = g.box || {};
  var H = (bx[g.home] && bx[g.home].team) || ts[g.home] || null, A = (bx[g.away] && bx[g.away].team) || ts[g.away] || null;
  if (!H || !A) return '';
  var lab = CC.fb(L) ? { first_downs: 'First downs', total_yards: 'Total yards', pass_yards: 'Passing yards', rush_yards: 'Rushing yards', rush_att: 'Rushes', pass_att: 'Pass attempts', turnovers: 'Turnovers', penalties: 'Penalties', penalty_yards: 'Penalty yards', third_conv: 'Third downs made', fourth_conv: 'Fourth downs made', possession_s: 'Possession' }
    : { fgm: 'Field goals', fga: 'FG attempts', tpm: 'Threes', tpa: '3PT attempts', ftm: 'Free throws', fta: 'FT attempts', oreb: 'Off. rebounds', dreb: 'Def. rebounds', reb: 'Rebounds', ast: 'Assists', stl: 'Steals', blk: 'Blocks', tov: 'Turnovers', pf: 'Fouls', pts_paint: 'Points in the paint', pts_fastbreak: 'Fast-break points', largest_lead: 'Largest lead' };
  var rows = Object.keys(lab).filter(function (k) { return isNum(H[k]) || isNum(A[k]); }).map(function (k) {
    var f = function (v) { return k === 'possession_s' && isNum(v) ? Math.floor(v / 60) + ':' + ('0' + (v % 60)).slice(-2) : (isNum(v) ? v : '—'); };
    return [{ v: A[k], html: '<b>' + f(A[k]) + '</b>', align: 'right' }, { html: esc(lab[k]), cls: 'cc-mid' }, { v: H[k], html: '<b>' + f(H[k]) + '</b>' }];
  });
  if (!rows.length) return '';
  return U.card('Team stats', '', U.table([{ label: CC.tabbr(L, g.away), align: 'right', sortable: false }, { label: '', sortable: false, cls: 'cc-mid' }, { label: CC.tabbr(L, g.home), sortable: false }], rows, { sticky: false, cls: 'cc-vs' }));
}

function boxFootball(L, g) {
  var bx = g.box || {};
  var tabs = [g.away, g.home].filter(function (t) { return bx[t] && bx[t].players; });
  if (!tabs.length) return '';
  var CATS = [['passing', 'Passing'], ['rushing', 'Rushing'], ['receiving', 'Receiving'], ['defensive', 'Defense'], ['interceptions', 'Interceptions'], ['kicking', 'Kicking'], ['punting', 'Punting'], ['kickReturns', 'Kick returns'], ['puntReturns', 'Punt returns'], ['fumbles', 'Fumbles']];
  var SHORT = { cmp: 'C', att: 'ATT', passing_yards: 'YDS', yards_per_pass_attempt: 'AVG', passing_touchdowns: 'TD', interceptions: 'INT', adj_qbr: 'QBR', rushing_attempts: 'CAR', rushing_yards: 'YDS', yards_per_rush_attempt: 'AVG',
    rushing_touchdowns: 'TD', long_rushing: 'LONG', receptions: 'REC', receiving_yards: 'YDS', yards_per_reception: 'AVG', receiving_touchdowns: 'TD', long_reception: 'LONG', total_tackles: 'TOT', solo_tackles: 'SOLO',
    sacks: 'SACKS', tackles_for_loss: 'TFL', passes_defended: 'PD', qb_hits: 'QB HITS', defensive_touchdowns: 'TD', fgm: 'FGM', fga: 'FGA', field_goal_pct: 'PCT', long_field_goal_made: 'LONG', extra_points: 'XP', total_kicking_points: 'PTS' };
  var html = '<div class="qk-tabs" role="tablist">' + tabs.map(function (t, i) { return '<button class="qk-tab" role="tab" aria-selected="' + (i === 0) + '" aria-controls="box-' + t + '">' + esc(CC.tshort(L, t)) + '</button>'; }).join('') + '</div>';
  tabs.forEach(function (t, i) {
    var P = bx[t].players, names = bx[t].names || {};
    html += '<div class="qk-tabpanel" role="tabpanel" id="box-' + t + '"' + (i ? ' hidden' : '') + '>';
    CATS.forEach(function (c) {
      var blk = P[c[0]];
      if (!blk || !blk.rows || !blk.rows.length) return;
      var named = typeof blk.rows[0][1] === 'string';
      var bc = (blk.cols || []).filter(function (k) { return k !== 'id' && k !== 'name' && k !== 'player_id'; });
      var cols = [{ label: c[1] }].concat(bc.map(function (k) { return { label: SHORT[k] || k.replace(/_/g, ' ').toUpperCase(), align: 'right' }; }));
      var rows = blk.rows.map(function (r) {
        var pid = r[0], nm = named ? r[1] : (names[pid] || CC.pname(L, pid)), vals = r.slice(named ? 2 : 1);
        return [{ html: '<a href="' + esc(CC.playerHref(L, pid, g.season)) + '">' + esc(nm) + '</a>', v: nm }].concat(vals.map(function (v) { return isNum(v) ? v : (v === null || v === undefined ? '—' : String(v)); }));
      });
      html += '<div class="cc-box-cat">' + U.table(cols, rows) + '</div>';
    });
    html += '</div>';
  });
  return U.card('Box score', 'Player lines as ESPN reports them.', html, { cls: 'cc-box' });
}
function boxHoops(L, g) {
  var bx = g.box || {};
  var tabs = [g.away, g.home].filter(function (t) { return bx[t] && bx[t].players && bx[t].players.length; });
  if (!tabs.length) return '';
  var C = ['player_id', 'starter', 'sec', 'pts', 'fgm', 'fga', 'tpm', 'tpa', 'ftm', 'fta', 'oreb', 'dreb', 'ast', 'stl', 'blk', 'tov', 'pf'];
  function obj(r, names) {
    if (!Array.isArray(r)) { if (r && r.id === undefined) r.id = r.player_id; if (r && !isNum(r.min) && isNum(r.sec)) r.min = Math.round(r.sec / 60); return r; }
    var o = {}; C.forEach(function (k, i) { o[k] = r[i]; }); o.id = o.player_id; o.min = isNum(o.sec) ? Math.round(o.sec / 60) : null;
    o.name = (names || {})[String(o.player_id)] || null;
    return o;
  }
  var html = '<div class="qk-tabs" role="tablist">' + tabs.map(function (t, i) { return '<button class="qk-tab" role="tab" aria-selected="' + (i === 0) + '" aria-controls="box-' + t + '">' + esc(CC.tshort(L, t)) + '</button>'; }).join('') + '</div>';
  tabs.forEach(function (t, i) {
    var rows = bx[t].players.map(function (r) { return obj(r, bx[t].names); });
    var cols = [{ label: 'Player' }, { label: 'MIN', align: 'right' }, { label: 'PTS', align: 'right' }, { label: 'FG', align: 'right' }, { label: '3PT', align: 'right' }, { label: 'FT', align: 'right' }, { label: 'REB', align: 'right' }, { label: 'AST', align: 'right' }, { label: 'STL', align: 'right' }, { label: 'BLK', align: 'right' }, { label: 'TO', align: 'right' }, { label: 'PF', align: 'right' }];
    var body = rows.map(function (o) {
      var nm = o.name || CC.pname(L, o.id), reb = isNum(o.reb) ? o.reb : (isNum(o.oreb) && isNum(o.dreb) ? o.oreb + o.dreb : null);
      return [{ html: '<a href="' + esc(CC.playerHref(L, o.id, g.season)) + '">' + esc(nm) + '</a>' + (o.starter ? ' <span class="qk-muted">S</span>' : ''), v: nm }, isNum(o.min) ? o.min : '—', isNum(o.pts) ? o.pts : '—',
        { v: o.fgm, html: (isNum(o.fgm) ? o.fgm + '-' + o.fga : '—') }, { v: o.tpm, html: (isNum(o.tpm) ? o.tpm + '-' + o.tpa : '—') }, { v: o.ftm, html: (isNum(o.ftm) ? o.ftm + '-' + o.fta : '—') },
        isNum(reb) ? reb : '—', isNum(o.ast) ? o.ast : '—', isNum(o.stl) ? o.stl : '—', isNum(o.blk) ? o.blk : '—', isNum(o.tov) ? o.tov : '—', isNum(o.pf) ? o.pf : '—'];
    });
    var dnp = (bx[t].dnp || []).map(function (x) { return Array.isArray(x) ? (typeof x[1] === 'string' && x.length > 2 ? x[1] : CC.pname(L, x[0])) : x.name; }).filter(Boolean);
    html += '<div class="qk-tabpanel" role="tabpanel" id="box-' + t + '"' + (i ? ' hidden' : '') + '>' + U.table(cols, body) + (dnp.length ? '<p class="cc-note">Did not play: ' + esc(dnp.join(', ')) + '</p>' : '') + '</div>';
  });
  return U.card('Box score', '', html, { cls: 'cc-box' });
}

function leadersBlock(L, g) {
  var ld = g.leaders || {};
  var ts = [g.away, g.home].filter(function (t) { return (ld[t] || []).length; });
  if (!ts.length) return '';
  return U.card('Leaders', '', '<div class="cc-two">' + ts.map(function (t) {
    return '<div><div class="cc-mini-h">' + U.teamEnt(L, t, { season: g.season }) + '</div><ul class="cc-list">' + ld[t].map(function (x) {
      return '<li><a href="' + esc(CC.playerHref(L, x.id, g.season)) + '">' + esc(x.name || CC.pname(L, x.id)) + '</a><span class="s">' + esc(x.line || '') + '</span></li>'; }).join('') + '</ul></div>';
  }).join('') + '</div>');
}

CC.route('game', function (el, p) {
  var L = p.L, S = p.S, gid = p.id;
  el.innerHTML = QK.skeleton('lines', 6);
  return Promise.all([CC.load(CC.path(L, S, 'games/' + gid + '.json')), CC.load(CC.path(L, S, 'schedule.json')), CC.season(L, S)]).then(function (a) {
    if (!U.alive(el)) return;
    var g = CC.ok(a[0]) ? a[0] : null, sch = CC.ok(a[1]) ? a[1] : null;
    if (g && g.teams) CC.addTeams(L, g.teams);
    if (!g && sch) { g = (sch.games || []).filter(function (c) { return String(c.id) === String(gid); })[0] || null; if (g) g = Object.assign({ light: true }, g); }
    if (!g) { el.innerHTML = U.head('Game', '', U.kicker(L, S)) + QK.empty('Game not found', 'No game ' + gid + ' in ' + CC.seasonLabel(L, S) + '. Past regular-season games keep their result in the schedule only.'); return; }
    if (!g.season) g.season = S;
    var fb = CC.fb(L), st = CC.status(g);
    var html = hero(L, g);
    if (g.light) html += '<p class="cc-note">' + (st === 'pre' ? 'The full game page appears on game day.' : 'This game has no detailed page (game pages are kept for the current season and the last postseason); the result and the pregame numbers are below.') + '</p>';
    html += '<div class="qk-grid cc-grid"><div class="qk-span-5">' + pregame(L, g) + '</div><div class="qk-span-7" id="gc-wpcard"></div>';
    var wp = g.wp || null, flow = g.flow || null;
    html += '</div>';
    if (fb && (g.drives || g.epa)) html += '<div class="qk-grid cc-grid"><div class="qk-span-7" id="gc-drives"></div><div class="qk-span-5" id="gc-epa"></div></div>';
    if ((g.plays || []).length) g.plays = g.plays.slice().sort(function (x, y) { return Math.abs(y.wpa || 0) - Math.abs(x.wpa || 0); });
    if ((g.plays || []).length) html += U.card('Highest-leverage plays', 'The plays that moved the win probability most (win probability added, home side).', '<ol class="cc-plays">' + g.plays.slice(0, 8).map(function (x) {
      return '<li><span class="t">' + esc(perLabel(L, g.season, x.period) + ' ' + (isNum(x.clock) ? fmtClock(x.clock / 60) : (x.clock || ''))) + '</span><span class="tx">' + (x.team ? QK.teamMark(CC.team(L, x.team) || {}, 'sm') : '') + esc(x.text || '') + '</span><b class="' + CC.cls(x.wpa) + '">' + (isNum(x.wpa) ? QK.fmt.pp(x.wpa) : '') + '</b></li>'; }).join('') + '</ol>');
    html += '<div class="qk-grid cc-grid"><div class="qk-span-8">' + (fb ? boxFootball(L, g) : boxHoops(L, g)) + '</div><div class="qk-span-4"><div class="qk-stack">' + leadersBlock(L, g) + teamStats(L, g) + '</div></div></div>';
    el.innerHTML = html;
    QK.$$('.qk-tabs[role="tablist"]', el).forEach(function (t) { QK.tabs(t.parentNode); });
    U.wire(el);
    // win probability and flow
    var wpNode = QK.$('#gc-wpcard', el);
    /* series times: minutes from tip-off / kick-off (PAYLOADS.md); payloads in seconds are converted */
    var toMin = function (arr) {
      if (!arr || !arr.length) return arr;
      var mx = Math.max.apply(null, arr.map(function (x) { return x[0]; }));
      return mx > 100 ? arr.map(function (x) { return [x[0] / 60, x[1]]; }) : arr;
    };
    if (wp) wp = { model: toMin(wp.model), espn: toMin(wp.espn) };
    flow = toMin(flow);
    var hasWp = wp && ((wp.model && wp.model.length > 2) || (wp.espn && wp.espn.length > 2));
    var hasFlow = flow && flow.length > 2;
    if (hasWp || hasFlow) {
      wpNode.innerHTML = U.card(hasWp ? 'Win probability' : 'Score flow', hasWp ? 'Chance the home side wins after each play' + (wp.espn && wp.espn.length && wp.model && wp.model.length ? '; dashed: ESPN.' : '.') : 'Home lead through the game.',
        (hasWp ? U.chart('gc-wp', 280, 'Win probability through the game') : '') + (hasFlow ? '<div class="cc-mini-h">Score margin (home minus away)</div>' + U.chart('gc-flow', 180, 'Score margin through the game') : ''));
      var home = CC.team(L, g.home) || {}, away = CC.team(L, g.away) || {};
      if (hasWp) {
        var main = wp.model && wp.model.length > 2 ? wp.model : wp.espn, cmp = main === wp.model && wp.espn && wp.espn.length > 2 ? wp.espn : null;
        var tMax = Math.max.apply(null, main.map(function (x) { return x[0]; }));
        QKC.winProb('#gc-wp', { t: main.map(function (x) { return x[0]; }), p: main.map(function (x) { return x[1]; }), home: { name: home.short || home.name, abbr: home.abbr, colour: home.colour }, away: { name: away.short || away.name, abbr: away.abbr, colour: away.colour },
          periods: breaks(L, g.season, tMax), tMin: 0, tMax: Math.max(tMax, fb ? 60 : (L === 'mbb' ? 40 : 40)), tFmt: function (v) { return Math.round(v) + '′'; }, tLabel: function (v) { return clockLabel(L, g.season, v); },
          compare: cmp ? { name: 'ESPN', t: cmp.map(function (x) { return x[0]; }), p: cmp.map(function (x) { return x[1]; }) } : null, step: true });
      }
      if (hasFlow) QKC.line('#gc-flow', { xType: 'value', xName: 'Game time', yName: 'Lead (pts)', series: [{ name: 'Home lead', data: flow, area: true, color: CC.tcol(L, g.home) }], step: 'end', yFmt: function (v) { return CC.signed(v, 0); }, xFmt: function (v) { return Math.round(v) + '′'; }, xLabel: function (v) { return clockLabel(L, g.season, v); }, ref: { y: 0 }, endLabels: false });
    } else wpNode.innerHTML = U.card('Win probability', '', QK.empty(st === 'pre' ? 'Not started' : 'No play-by-play', st === 'pre' ? 'The live curve appears once the game starts.' : 'ESPN has no play-by-play for this game.'));
    if (fb && (g.drives || g.epa)) {
      var dn = QK.$('#gc-drives', el);
      var dr = g.drives || [];
      dn.innerHTML = dr.length ? U.card('Drives', 'Every possession: start, plays, yards, result and expected points added.', U.table(['Team', { label: 'Q', align: 'right' }, 'Start', { label: 'Plays', align: 'right' }, { label: 'Yds', align: 'right' }, 'Result', { label: 'EPA', align: 'right' }],
        dr.map(function (d) { return [{ html: QK.teamMark(CC.team(L, d.team) || {}, 'sm') + ' ' + esc(CC.tabbr(L, d.team)), v: CC.tabbr(L, d.team) }, d.period, { v: d.start, html: esc(ydLine(d.start)) }, d.plays, d.yards, esc(d.result || ''), { v: d.epa, html: '<span class="' + CC.cls(d.epa) + '">' + CC.signed(d.epa, 2) + '</span>' }]; }), { maxHeight: 420 })) : '';
      var en = QK.$('#gc-epa', el), E = g.epa || {};
      var ks = [['epa_play', 'EPA per play', 3], ['sr', 'Success rate', 'pct'], ['pass_epa', 'Pass EPA/play', 3], ['rush_epa', 'Rush EPA/play', 3], ['explosive', 'Explosive play rate', 'pct']];
      if (E[g.home] && E[g.away]) {
        en.innerHTML = U.card('Efficiency', 'Expected points added per play and success rate, garbage time included.', U.chart('gc-epa-ch', 220, 'EPA per play by team') + U.table([{ label: '', sortable: false }, { label: CC.tabbr(L, g.away), align: 'right' }, { label: CC.tabbr(L, g.home), align: 'right' }], ks.map(function (k) {
          var f = function (v) { return k[2] === 'pct' ? CC.pct(v, 1) : CC.signed(v, k[2]); };
          return [k[1], { v: E[g.away][k[0]], html: f(E[g.away][k[0]]) }, { v: E[g.home][k[0]], html: f(E[g.home][k[0]]) }];
        }), { sticky: false }));
        U.wire(en);
        var cols2 = [CC.tcol(L, g.away), CC.tcol(L, g.home)];
        if (QK.color.contrast(cols2[0], cols2[1]) < 1.6) cols2 = [QK.cssVar('--c-2'), QK.cssVar('--c-1')];
        QKC.bar('#gc-epa-ch', { cats: ['EPA/play', 'Pass', 'Rush'], legend: true, valName: 'EPA per play', fmt: function (v) { return CC.signed(v, 2); },
          series: [{ name: CC.tabbr(L, g.away), data: [E[g.away].epa_play, E[g.away].pass_epa, E[g.away].rush_epa], color: cols2[0] }, { name: CC.tabbr(L, g.home), data: [E[g.home].epa_play, E[g.home].pass_epa, E[g.home].rush_epa], color: cols2[1] }] });
      }
      U.wire(dn);
    }
  });
});

})(window.CC);
