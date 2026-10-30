/* The Quant Campus — Games (#/<L>/games) and the game centre (#/<L>/game/<gid>).
 * Games: by week (cfb: weeks, championship week, bowls, playoff) or by day (basketball), filters for ranked teams,
 * conference games, a conference, close lines and model-v-market gaps. Reads <L>/<S>/schedule.json.
 * Game centre (kit v4 "Broadcast", the Rink game page is the reference): the hero is QK.previewCard, the diagonal split
 * hero (away "at" home in the team colours with records, the clock when live, our chance for the favourite as a big blue number with a how-sure note, the
 * team-colour bar, the market as a quiet labelled reference before the game, how the teams match up from the
 * ratings); beside it the tiles and our forecast table (the market a reference column; "How our forecast is built",
 * the trial labelled as a trial); then win probability (model and ESPN), score flow, drives and EPA (cfb),
 * highest-leverage plays, box scores, team stats, leaders. Reads <L>/<S>/games/<gid>.json and falls back
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
/* A close game by our own forecast: neither side above 65%. */
function isClose(c) { var m = c.model || {}; return isNum(m.p_home) && Math.abs(m.p_home - 0.5) <= 0.15; }

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
    var flt = { ranked: false, conf: false, close: false, cid: q.conf || '' };
    var confs = {};
    cards.forEach(function (c) { [c.home, c.away].forEach(function (t) { var tm = CC.team(L, t); if (tm && tm.member && tm.conference) confs[tm.conference] = 1; }); });
    var confOpts = '<option value="">All conferences</option>' + Object.keys(confs).sort(function (x, y) { return CC.cname(L, x).localeCompare(CC.cname(L, y)); }).map(function (c) { return '<option value="' + esc(c) + '">' + esc(CC.cname(L, c)) + '</option>'; }).join('');
    var i = keys.indexOf(cur);
    var nav = '<div class="cc-pager"><button class="qk-btn" type="button" id="g-prev" aria-label="Previous"' + (i <= 0 ? ' disabled' : '') + '>←</button>' +
      '<select class="qk-select" id="g-key" aria-label="' + (fb ? 'Week' : 'Day') + '">' + keys.map(function (k) {
        var n = byKey[k].length; return '<option value="' + esc(k) + '"' + (k === cur ? ' selected' : '') + '>' + esc(fb ? wkLabel(k) : CC.date(k + 'T12:00:00Z')) + ' · ' + n + ' game' + (n > 1 ? 's' : '') + '</option>';
      }).join('') + '</select><button class="qk-btn" type="button" id="g-next" aria-label="Next"' + (i >= keys.length - 1 ? ' disabled' : '') + '>→</button></div>';
    var chips = QK.note('<b>How sure are we?</b> 70% means the underdog still wins a game like this about 3 times in 10. Toss-ups are the games we can barely split.') + '<div class="qk-chips scroll cc-filters" id="g-chips" role="group" aria-label="Filters">' +
      [['ranked', fb ? 'Ranked' : 'Ranked or seeded'], ['conf', 'Conference games'], ['close', 'Toss-ups (35–65%)']].map(function (x) {
        return '<button type="button" class="qk-chip" style="--ca:var(--signal)" data-value="' + x[0] + '" aria-pressed="false">' + esc(x[1]) + '</button>'; }).join('') + '</div>';
    el.innerHTML = U.head('Games', (fb ? 'Every game involving an FBS team, week by week' : 'Every game involving a Division I team, day by day') + ', with our chance for each side and a line on why it’s worth your time (the favourite in blue). Tap a game for its page.', U.kicker(L, S)) +
      '<div class="cc-toolbar">' + nav + '<select class="qk-select" id="g-conf" aria-label="Conference">' + confOpts + '</select></div>' + excitement(L, S, byKey[cur], a[1], fb) + chips + '<div id="g-sum" class="cc-note"></div><div id="g-list"></div>';
    QK.$('#g-conf', el).value = flt.cid;
    function paint() {
      var list = byKey[cur].filter(function (c) {
        if (flt.ranked && !(c.hr || c.ar || c.hseed || c.aseed)) return false;
        if (flt.conf && !c.conf_game) return false;
        if (flt.close && !isClose(c)) return false;
        if (flt.cid) { var h = CC.team(L, c.home) || {}, w = CC.team(L, c.away) || {}; if (String(h.conference) !== flt.cid && String(w.conference) !== flt.cid) return false; }
        return true;
      });
      var fin = list.filter(function (c) { return c.status === 'post' && c.result; });
      var right = fin.filter(function (c) { return c.result.model_correct === true; }).length;
      QK.$('#g-sum', el).innerHTML = list.length + ' game' + (list.length === 1 ? '' : 's') + (fin.length ? ' · our favourite won <b>' + right + ' of ' + fin.length + '</b>' : '');
      if (!list.length) { QK.$('#g-list', el).innerHTML = QK.empty('No games match', 'Clear a filter or pick another ' + (fb ? 'week' : 'day') + '.'); return; }
      var html = '', last = null;
      list.forEach(function (c) {
        var d = dayKey(CC.gameDate(c));
        if (d !== last) { if (last !== null) html += '</div>'; html += '<div class="cc-day">' + esc(CC.date(CC.gameDate(c))) + '</div><div class="cc-games">'; last = d; }
        html += CC.card(c, L, { why: true });
      });
      QK.$('#g-list', el).innerHTML = html + '</div>';
    }
    function go(k) { CC.go(CC.href(L, 'games', null, S, (fb ? 'w=' : 'd=') + k)); }
    QK.$('#g-key', el).addEventListener('change', function (e) { go(e.target.value); });
    QK.$('#g-prev', el).addEventListener('click', function () { if (i > 0) go(keys[i - 1]); });
    QK.$('#g-next', el).addEventListener('click', function () { if (i < keys.length - 1) go(keys[i + 1]); });
    QK.$('#g-conf', el).addEventListener('change', function (e) { flt.cid = e.target.value; paint(); });
    QK.chips(QK.$('#g-chips', el), function (v) { flt.ranked = v.indexOf('ranked') >= 0; flt.conf = v.indexOf('conf') >= 0; flt.close = v.indexOf('close') >= 0; paint(); }, true);
    paint();
  });
});

/* ── round 9, Phase 4: "Games of the week", the excitement index ─────────────────────────────────────────────────
   For the games still to play on the week (football) or day (basketball) on screen: how close our call is (40%), how
   good the two teams are (35%: their average rating as a percentile of every team) and how much rides on it (25%:
   football, the playoff places the result moves in our simulations, season.json sim.stakes; basketball, how undecided
   both teams' NCAA chances are). 100 is a coin flip between two of the best teams with the most at stake. */
function excitement(L, S, cards, season, fb) {
  var pre = (cards || []).filter(function (c) { return c.status === 'pre' && c.model && isNum(c.model.p_home) && !QK.awaiting(CC.game(c, L)); });
  if (pre.length < 3 || !CC.ok(season)) return '';
  var R = season.ratings || {}, sim = (season.sim && season.sim.teams) || {};
  var all = Object.keys(R).map(function (t) { return R[t].rating; }).filter(isNum).sort(function (a, b) { return a - b; });
  var stakes = {}, smax = 0;
  ((season.sim && season.sim.stakes) || []).forEach(function (g) { if (isNum(g.swing)) { stakes[String(g.game)] = g.swing; if (g.swing > smax) smax = g.swing; } });
  var pk = fb ? 'p_cfp' : 'p_ncaa';
  var rows = pre.map(function (c) {
    var p = c.model.p_home, close = 1 - Math.abs(2 * p - 1);
    var rh = (R[String(c.home)] || {}).rating, ra = (R[String(c.away)] || {}).rating;
    var q = isNum(rh) && isNum(ra) && all.length ? QK.pctRank(all, (rh + ra) / 2) / 100 : 0;
    var st = 0;
    if (smax > 0 && isNum(stakes[String(c.id)])) st = stakes[String(c.id)] / smax;
    else { var a = (sim[String(c.home)] || {})[pk], b = (sim[String(c.away)] || {})[pk]; st = ((isNum(a) ? 4 * a * (1 - a) : 0) + (isNum(b) ? 4 * b * (1 - b) : 0)) / 2; }
    return { c: c, x: Math.round(100 * (0.4 * close + 0.35 * q + 0.25 * st)), close: close, q: q, st: st };
  }).sort(function (a, b) { return b.x - a.x; }).slice(0, 6);
  return U.card('Games of the ' + (fb ? 'week' : 'day'), 'Our excitement index, 0 to 100: how close our call is, how good the two teams are and how much rides on the result. Tap a game for its page.',
    '<ol class="cc-race-l cc-ex">' + rows.map(function (r, i) {
      var c = r.c, g = CC.game(c, L);
      return '<li><span class="cc-race-rk num">' + (i + 1) + '</span>' + QK.teamMark(U.mark(L, c.home), 'sm') + '<span class="cc-race-nm"><a href="' + esc(CC.gameHref(L, c.id, S)) + '">' + esc(g.away.name + ' at ' + g.home.name) + '</a><small>' +
        esc(CC.when(c) + ' · our call ' + (function (m) { var pa = isNum(m.p_away) ? m.p_away : 1 - m.p_home; /* hockey: a tie is possible */
          return CC.tabbr(L, m.p_home >= pa ? c.home : c.away) + ' ' + CC.pct(Math.max(m.p_home, pa)); })(c.model)) + '</small><span class="cc-race-why">' +
        esc('Closeness ' + Math.round(100 * r.close) + ' · quality ' + Math.round(100 * r.q) + ' · stakes ' + Math.round(100 * r.st)) + '</span></span><span class="cc-race-bar" aria-hidden="true"><i style="width:' + Math.max(3, r.x) + '%;background:var(--signal)"></i></span><b class="num">' + r.x + '</b></li>';
    }).join('') + '</ol>', { cls: 'cc-ex-card' });
}

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

/* Two teams' colours that can be told apart (kit rule QK.color.distinct; the second falls back to the win-probability orange). */
CC.pair = function (L, a, h) {
  var ca = CC.tcol(L, a), ch = CC.tcol(L, h);
  var ok = function (x, y) { return QK.color.distinct ? QK.color.distinct(x, y) : QK.color.contrast(x, y) >= 1.6; };
  if (!ok(ca, ch)) { ch = QK.cssVar('--wp-b'); if (!ok(ca, ch)) ch = QK.cssVar('--wp-a'); }
  return [ca, ch];
};
function pickOf(L, g, margin) { return isNum(margin) ? (Math.abs(margin) < 0.05 ? 'Even' : CC.tabbr(L, margin > 0 ? g.home : g.away) + ' by ' + CC.f(Math.abs(margin), 1)) : '—'; }

/* v4 (Broadcast) hero: QK.previewCard, the diagonal split, with records, our chance (the live curve's last point once it starts, our
   pre-game call after it ends), a how-sure note with the projected score and the margin's spread, the market as a
   quiet reference line before the game (game detail is one of the two places it may appear) and how the teams match
   up from the season ratings. */
function hero(L, g, season) {
  var st = CC.status(g), live = st === 'live', pre = st === 'pre';
  var pg = g.pregame || {}, m = pg.model || g.model || {}, mk = pg.market || g.market || {};
  var cols = CC.pair(L, g.away, g.home);
  var G = CC.game(g, L);
  /* v4: the diagonal hero takes the raw kit colours and the alternates (CC.side: alt and full; QK.color.blockPair makes
     the blocks and resolves a clash, slate when no alternate is there yet); the lifted pair stays for the factors */
  G.home.colour = CC.traw(L, g.home) || cols[1]; G.away.colour = CC.traw(L, g.away) || cols[0];
  G.home.record = CC.rec(L, g.season, g.home); G.away.record = CC.rec(L, g.season, g.away);
  var wpm = g.wp && g.wp.model && g.wp.model.length ? g.wp.model[g.wp.model.length - 1][1] : null;
  if (live && isNum(wpm)) { G.wp_home = wpm; G.pre_only = undefined; }
  if (isNum(m.p_home)) G.p_home = m.p_home;
  var R = (season && season.ratings) || {}, ra = R[String(g.away)] || {}, rh = R[String(g.home)] || {}, fb = CC.fb(L), hk = CC.hk(L);
  var fx = [];
  var add = function (label, x, y, f, low) { if (isNum(x) && isNum(y)) fx.push({ label: label, a: f(x), b: f(y), better: Math.abs(x - y) < 1e-9 ? null : ((x > y) !== !!low ? 'a' : 'b') }); };
  if (hk) {
    add('Rating, goals v average', ra.rating, rh.rating, function (v) { return CC.signed(v, 2); });
    add('Attack, goals a game above average', ra.off, rh.off, function (v) { return CC.signed(v, 2); });
    add('Defence, goals a game kept out', ra.def, rh.def, function (v) { return CC.signed(v, 2); });
    add('Power play', ra.pp_pct, rh.pp_pct, function (v) { return CC.pct(v, 1); });
    add('Penalty kill', ra.pk_pct, rh.pk_pct, function (v) { return CC.pct(v, 1); });
  } else
  add(fb ? 'Rating, points v average' : 'Rating, margin per 100', ra.rating, rh.rating, function (v) { return CC.signed(v, 1); });
  if (!hk) {
  add(fb ? 'Offence, points a game' : 'Offence, points per 100', ra.off, rh.off, function (v) { return CC.f(v, 1); });
  add(fb ? 'Defence, points prevented' : 'Defence, allowed per 100', ra.def, rh.def, function (v) { return CC.f(v, 1); }, !fb);
  if (fb) add('Offensive EPA a play', ra.epa_off, rh.epa_off, function (v) { return CC.signed(v, 2); });
  }
  add('Strength of schedule', ra.sos, rh.sos, function (v) { return CC.signed(v, hk ? 2 : 1); });
  var extra = [];
  if (pre && hk && isNum(m.xg_home)) extra.push('We expect ' + CC.tshort(L, g.away) + ' ' + CC.f(m.xg_away, 1) + ' goals and ' + CC.tshort(L, g.home) + ' ' + CC.f(m.xg_home, 1) + (isNum(m.p_tie) && g.stype !== 'ncaa' && g.stype !== 'conf' ? '; a tie ' + CC.pct(m.p_tie) : ''));
  else if (pre && isNum(m.margin) && isNum(m.total)) { var hs = (m.total + m.margin) / 2, as = (m.total - m.margin) / 2; extra.push('Our projected score is ' + CC.tshort(L, g.away) + ' ' + CC.f(as, 0) + ', ' + CC.tshort(L, g.home) + ' ' + CC.f(hs, 0)); }
  if (pre && isNum(m.sd)) extra.push('the final margin usually lands within ' + CC.f(m.sd, 0) + ' points of that');
  var tag = CC.roundLabel(g) || (g.conf_game ? 'Conference game' : 'Non-conference');
  var venue = g.venue && g.venue.name ? g.venue.name : '';
  var src = CC.mkSource(mk);
  if (hk && isNum(m.p_tie) && g.stype !== 'ncaa' && g.stype !== 'conf') { G.p_draw = m.p_tie; G.p_away = m.p_away; }
  return '<div class="cc-preview">' + (hk ? CC.tieWords : String)(QK.previewCard(G, { kicker: CC.LSHORT[L] + ' · ' + tag + (venue ? ' · ' + venue : ''), nick: function (x) { return x.name; }, colors: cols, factors: fx, factorsTitle: CC.isCur(L, g.season) ? 'How they match up this season' : 'How they matched up', vs: g.neutral ? 'v' : undefined,
    noteExtra: extra.length ? esc(extra.join(', and ') + '.') : '', market: pre && isNum(mk.p_home) ? { p: mk.p_home, src: src || undefined, quiet: true } : null })) + '</div>';
}
function heroMeta(L, g) {
  var venue = g.venue && g.venue.name ? g.venue.name + (g.venue.city ? ', ' + g.venue.city : '') + (g.venue.state ? ', ' + g.venue.state : '') : '';
  var meta = [CC.when(g), venue ? venue + (g.neutral ? ' (neutral)' : '') : '', isNum(g.attendance) ? QK.fmt.num(g.attendance) + ' fans' : '', isNum(g.week) && g.stype === 'reg' ? 'Week ' + g.week : '', g.note && g.stype === 'reg' ? g.note : ''].filter(Boolean);
  return '<div class="cc-hero-meta2">' + meta.map(function (x) { return '<span>' + esc(x) + '</span>'; }).join('') + '</div>';
}

function tiles(L, g) {
  var st = CC.status(g), pg = g.pregame || {}, m = pg.model || g.model || {};
  var out = [];
  if (isNum(m.p_home)) {
    /* hockey can end level: the away side's chance is p_away, not 1 - p_home */
    var pAw = CC.hk(L) && isNum(m.p_away) ? m.p_away : 1 - m.p_home;
    var hf = m.p_home >= pAw;
    out.push({ label: st === 'pre' ? 'Our win chance' : 'Our pre-game call', value: CC.tabbr(L, hf ? g.home : g.away) + ' ' + CC.pct(hf ? m.p_home : pAw), signal: true,
      sub: isNum(m.margin) ? 'projected margin: ' + pickOf(L, g, m.margin) : '', tip: CC.hk(L) ? 'Our pre-game chance of winning, from the two teams’ ratings and home ice' : 'Our pre-game chance of winning, from the two teams’ ratings, home field and rest' });
  }
  var wpm = g.wp && g.wp.model && g.wp.model.length ? g.wp.model[g.wp.model.length - 1][1] : null;
  if (st === 'live' && isNum(wpm)) out.push({ label: 'Live win chance', value: CC.tabbr(L, wpm >= 0.5 ? g.home : g.away) + ' ' + CC.pct(Math.max(wpm, 1 - wpm)), signal: true, sub: 'our in-game model, every play' });
  if (CC.hk(L) && isNum(m.p_tie) && m.p_tie > 0.001 && g.stype !== 'ncaa' && g.stype !== 'conf') out.push({ label: st === 'pre' ? 'Tie chance' : 'Our tie chance', value: CC.pct(m.p_tie), sub: 'level after overtime: a tie in the record' });
  if (CC.hk(L) && isNum(m.xg_home) && st === 'pre') out.push({ label: 'Expected goals (ours)', value: CC.f(m.xg_away, 1) + '–' + CC.f(m.xg_home, 1), sub: CC.tabbr(L, g.away) + ' – ' + CC.tabbr(L, g.home) + ' · from the two ratings' });
  else if (isNum(m.margin) && isNum(m.total) && st === 'pre') {
    var hs = (m.total + m.margin) / 2, as = (m.total - m.margin) / 2;
    out.push({ label: 'Projected score', value: CC.f(as, 0) + '–' + CC.f(hs, 0), sub: CC.tabbr(L, g.away) + ' – ' + CC.tabbr(L, g.home) + ' · ' + CC.f(m.total, 1) + ' points expected' });
  }
  if (isNum(m.sd)) out.push({ label: 'Margin uncertainty', value: '± ' + CC.f(m.sd, 1), unit: 'pts', sub: 'one standard deviation of the final margin', tip: 'How far the final margin typically lands from our projection' });
  if (st === 'final' && (g.plays || []).length) {
    var top = g.plays.slice().sort(function (x, y) { return Math.abs(y.wpa || 0) - Math.abs(x.wpa || 0); })[0];
    if (top && isNum(top.wpa)) out.push({ label: 'Biggest swing', value: Math.round(Math.abs(top.wpa) * 100) + ' pts', sub: perLabel(L, g.season, top.period) + (top.team ? ' · ' + CC.tabbr(L, top.team) : '') + ' · the largest win-chance move in one play' });
  }
  if (st === 'final' && g.result && g.result.model_correct !== undefined && g.result.model_correct !== null) out.push({ label: 'Our pick', value: g.result.model_correct ? 'Right' : 'Wrong', text: true, sub: g.result.model_correct ? 'our favourite won' : 'our favourite lost' });
  return out.length ? U.stats(out) : '';
}

function pregame(L, g) {
  var pg = g.pregame || {}, m = pg.model || g.model || {}, mk = pg.market || g.market || null;
  var h = CC.tabbr(L, g.home), a = CC.tabbr(L, g.away), hs = CC.tshort(L, g.home), as = CC.tshort(L, g.away);
  if (!isNum(m.p_home)) return U.card('Our forecast', '', QK.empty('No forecast for this game', 'Our forecast covers games between two rated teams.'));
  if (CC.hk(L)) {
    var tieOk = isNum(m.p_tie) && g.stype !== 'ncaa' && g.stype !== 'conf';
    var hr = [['Win', h + ' ' + CC.pct(m.p_home) + (tieOk ? ' · tie ' + CC.pct(m.p_tie) : '') + ' · ' + a + ' ' + CC.pct(isNum(m.p_away) ? m.p_away : 1 - m.p_home)],
      ['Expected goals', isNum(m.xg_home) ? a + ' ' + CC.f(m.xg_away, 1) + ' · ' + h + ' ' + CC.f(m.xg_home, 1) : '—'], ['Total goals', isNum(m.total) ? CC.f(m.total, 1) + ' expected' : '—']];
    return U.card(CC.status(g) === 'pre' ? 'Our forecast' : 'Our pre-game forecast', 'From our game model: the two teams’ attack and defence ratings and home ice. ' + (tieOk ? 'A regular-season game level after five minutes of overtime is a tie.' : 'A tournament game is played until someone scores.'),
      '<div class="qk-table-wrap"><table class="qk-table dense"><thead><tr><th>Question</th><th>Our forecast</th></tr></thead><tbody>' + hr.map(function (r) { return '<tr><td>' + esc(r[0]) + '</td><td class="num" style="text-align:left;color:var(--ink-1);font-weight:600">' + esc(r[1]) + '</td></tr>'; }).join('') + '</tbody></table></div>');
  }
  var mkM = mk && isNum(mk.spread_home) ? -mk.spread_home : null;
  var rows = [
    ['Win', h + ' ' + CC.pct(m.p_home) + ' · ' + a + ' ' + CC.pct(1 - m.p_home), mk && isNum(mk.p_home) ? h + ' ' + CC.pct(mk.p_home) : '—'],
    ['Winning margin', pickOf(L, g, m.margin) + (isNum(m.sd) ? ' (± ' + CC.f(m.sd, 1) + ')' : ''), isNum(mkM) ? pickOf(L, g, mkM) : '—'],
    ['Total points', isNum(m.total) ? CC.f(m.total, 1) + ' expected' : '—', mk && isNum(mk.total) ? CC.f(mk.total, 1) : '—']
  ];
  var refs = [];
  if (isNum(pg.espn_predictor)) refs.push('ESPN predictor ' + h + ' ' + CC.pct(pg.espn_predictor));
  if (isNum(pg.elo_p_home)) refs.push('our Elo baseline ' + h + ' ' + CC.pct(pg.elo_p_home));
  var src = CC.mkSource(mk);
  var tbl = '<div class="qk-table-wrap"><table class="qk-table dense"><thead><tr><th>Question</th><th>Our forecast</th><th><span data-tip="The market’s numbers, shown as a reference next to ours">Market' + (src ? ' (' + esc(src) + ')' : '') + '</span></th></tr></thead><tbody>' +
    rows.map(function (r) { return '<tr><td>' + esc(r[0]) + '</td><td class="num" style="text-align:left;color:var(--ink-1);font-weight:600">' + esc(r[1]) + '</td><td class="num qk-muted" style="text-align:left">' + esc(r[2]) + '</td></tr>'; }).join('') + '</tbody></table></div>';
  var inf = m.informed || null, tri = m.trial || null, built = '';
  if (inf || tri) {
    var x = inf || tri, brows = [];
    var cell = function (mg, p) { return pickOf(L, g, mg) + (isNum(p) ? ' · ' + h + ' ' + CC.pct(p, 1) : ''); };
    brows.push(['Ratings model', cell(x.base_margin, x.base_p)]);
    if (isNum(x.mk_spread)) brows.push(['Market ratings', cell(-x.mk_spread, null)]);
    brows.push([inf ? 'Our forecast' : 'Trial forecast (on trial, not published)', cell(x.margin, x.p_home)]);
    if (mk && (isNum(mk.spread_home) || isNum(mk.p_home))) brows.push(['Market (reference)', cell(isNum(mk.spread_home) ? -mk.spread_home : null, mk.p_home)]);
    var moved = isNum(x.margin) && isNum(x.base_margin) ? x.margin - x.base_margin : null;
    var note = inf ? 'Our forecast stacks the ratings model with market ratings (team ratings learned from the market’s closing numbers on earlier games; adopted 22 Oct 2026 after a sealed test on 2021-26).'
      : 'A trial, not our published forecast: the ratings model stacked with market ratings (team ratings learned from the market’s closing numbers on earlier games), tested forward on 2026-27 before it can replace the forecast above.';
    if (isNum(moved)) note += ' Here it moves the margin ' + CC.f(Math.abs(moved), 1) + ' points toward ' + (moved > 0 ? hs : as) + '.';
    if (inf && inf.early) note += ' Early in the season the market part leans on last season’s market ratings and returning production.';
    built = '<div class="cc-sub">How our forecast is built' + (inf ? '' : ' <span class="qk-tag">Trial</span>') + '</div><div class="qk-table-wrap"><table class="qk-table dense"><thead><tr><th></th><th>Margin · ' + esc(h) + ' win chance</th></tr></thead><tbody>' +
      brows.map(function (r) { var ours = r[0] === 'Our forecast'; return '<tr><td>' + esc(r[0]) + '</td><td class="num" style="text-align:left' + (ours ? ';color:var(--signal);font-weight:700' : (/^Market/.test(r[0]) ? ';color:var(--ink-3)' : '')) + '">' + esc(r[1]) + '</td></tr>'; }).join('') +
      '</tbody></table></div>' + QK.note(esc(note));
  }
  return U.card(CC.status(g) === 'pre' ? 'Our forecast' : 'Our pre-game forecast', 'Chances from our game model; the market column is a reference, not our forecast.' + (refs.length ? ' Also: ' + esc(refs.join(', ')) + '.' : ''), '<div class="qk-stack">' + tbl + built + '</div>');
}

/* Tale of the tape: the two teams' season profile from the ratings (season.json ratings[team]). */
function tape(L, g, season) {
  var R = (season && season.ratings) || {}, a = R[String(g.away)] || {}, h = R[String(g.home)] || {}, fb = CC.fb(L);
  var rows = CC.hk(L) ? [
    { label: 'Rating (goals v average)', a: a.rating, b: h.rating, fmt: function (v) { return CC.signed(v, 2); }, tip: 'Our rating: goals a game better than an average D-I team on neutral ice' },
    { label: 'Attack (goals above average)', a: a.off, b: h.off, fmt: function (v) { return CC.signed(v, 2); } },
    { label: 'Defence (goals kept out)', a: a.def, b: h.def, fmt: function (v) { return CC.signed(v, 2); } },
    { label: 'Shots for a game', a: a.sf_pg, b: h.sf_pg, fmt: function (v) { return CC.f(v, 1); } },
    { label: 'Shots against a game', a: a.sa_pg, b: h.sa_pg, fmt: function (v) { return CC.f(v, 1); }, better: 'low' },
    { label: 'Power play', a: a.pp_pct, b: h.pp_pct, fmt: function (v) { return CC.pct(v, 1); } },
    { label: 'Penalty kill', a: a.pk_pct, b: h.pk_pct, fmt: function (v) { return CC.pct(v, 1); } },
    { label: 'Save %', a: a.sv_pct, b: h.sv_pct, fmt: function (v) { return CC.f(v, 3).replace(/^0/, ''); } },
    { label: 'Strength of schedule', a: a.sos, b: h.sos, fmt: function (v) { return CC.signed(v, 2); } }
  ] : fb ? [
    { label: 'Rating (points v average)', a: a.rating, b: h.rating, fmt: function (v) { return CC.signed(v, 1); }, tip: 'Our rating: expected margin against an average FBS team on a neutral field' },
    { label: 'Offence (points added a game)', a: a.off, b: h.off, fmt: function (v) { return CC.f(v, 1); } },
    { label: 'Defence (points prevented a game)', a: a.def, b: h.def, fmt: function (v) { return CC.f(v, 1); } },
    { label: 'Offensive EPA per play', a: a.epa_off, b: h.epa_off, fmt: function (v) { return CC.signed(v, 3); } },
    { label: 'Defensive EPA per play allowed', a: a.epa_def, b: h.epa_def, fmt: function (v) { return CC.signed(v, 3); }, better: 'low' },
    { label: 'Offensive success rate', a: a.sr_off, b: h.sr_off, fmt: function (v) { return CC.pct(v, 1); } },
    { label: 'Strength of schedule', a: a.sos, b: h.sos, fmt: function (v) { return CC.signed(v, 1); } }
  ] : [
    { label: 'Rating (margin per 100)', a: a.rating, b: h.rating, fmt: function (v) { return CC.signed(v, 1); }, tip: 'Our rating: adjusted efficiency margin per 100 possessions' },
    { label: 'Offence (points per 100)', a: a.off, b: h.off, fmt: function (v) { return CC.f(v, 1); } },
    { label: 'Defence (points allowed per 100)', a: a.def, b: h.def, fmt: function (v) { return CC.f(v, 1); }, better: 'low' },
    { label: 'Strength of schedule', a: a.sos, b: h.sos, fmt: function (v) { return CC.signed(v, 1); } }
  ];
  if (!rows.some(function (r) { return isNum(r.a) && isNum(r.b); })) return '';
  var cols = CC.pair(L, g.away, g.home), A = U.mark(L, g.away), H = U.mark(L, g.home);
  A.colour = cols[0]; H.colour = cols[1];
  return U.card('Tale of the tape', 'Season ratings ' + (CC.isCur(L, g.season) ? 'so far' : 'at season end') + '; the stronger side of each bar is solid.', QK.matchupBar({ left: A, right: H, rows: rows, colors: cols }));
}

function teamStats(L, g) {
  if (CC.hk(L)) return CC.hkTeamStats(L, g);
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
  var CATS = [['passing', 'Passing'], ['rushing', 'Rushing'], ['receiving', 'Receiving'], ['defensive', 'Defence'], ['interceptions', 'Interceptions'], ['kicking', 'Kicking'], ['punting', 'Punting'], ['kickReturns', 'Kick returns'], ['puntReturns', 'Punt returns'], ['fumbles', 'Fumbles']];
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
  /* a game page exists for the current season and the previous postseason (CC.hasPage): other games are the recap
     card from the schedule, with no request for a file that was never built */
  var cur = CC.isCur(L, S);
  return Promise.all([cur ? CC.load(CC.path(L, S, 'games/' + gid + '.json')) : Promise.resolve(null), CC.load(CC.path(L, S, 'schedule.json')), CC.season(L, S)]).then(function (a) {
    if (cur || !CC.ok(a[1])) return a;
    var c0 = (a[1].games || []).filter(function (c) { return String(c.id) === String(gid); })[0];
    if (c0 && !CC.hasPage(L, Object.assign({ season: S }, c0), S)) return a;
    return CC.load(CC.path(L, S, 'games/' + gid + '.json')).then(function (g) { a[0] = g; return a; });
  }).then(function (a) {
    if (!U.alive(el)) return;
    var g = CC.ok(a[0]) ? a[0] : null, sch = CC.ok(a[1]) ? a[1] : null;
    if (g && g.teams) CC.addTeams(L, g.teams);
    if (!g && sch) { g = (sch.games || []).filter(function (c) { return String(c.id) === String(gid); })[0] || null; if (g) g = Object.assign({ light: true }, g); }
    if (!g) { el.innerHTML = U.head('Game', '', U.kicker(L, S)) + QK.empty('Game not found', 'No game ' + gid + ' in ' + CC.seasonLabel(L, S) + '. Past regular-season games keep their result in the schedule only.'); return; }
    if (!g.season) g.season = S;
    var fb = CC.fb(L), st = CC.status(g);
    var season = CC.ok(a[2]) ? a[2] : null;
    var back = '<div class="qk-kicker" style="margin-bottom:10px"><a href="' + esc(CC.href(L, 'games', null, g.season, fb && isNum(g.week) && g.stype === 'reg' ? 'w=w' + g.week : '')) + '">← ' + esc(CC.LSHORT[L]) + ' games</a></div>';
    var html = back + '<div class="cc-gtop"><div class="qk-stack">' + hero(L, g, season) + heroMeta(L, g) + '</div><div class="qk-stack">' + tiles(L, g) + pregame(L, g) + '</div></div>';
    if (g.light) html += QK.note(st === 'pre' ? 'The full game page appears on game day.' : 'The recap: this game has no detailed page (game pages are kept for the current season and the last postseason), so the result and our pre-game numbers are above.');
    var tp = tape(L, g, season);
    /* before the game there is no win-chance path: the tale of the tape takes the row */
    html += st === 'pre' ? '<div style="margin-top:var(--sp-6)">' + tp + '<div id="gc-wpcard"></div></div><div>'
      : '<div class="qk-grid cc-grid" style="margin-top:var(--sp-6)"><div class="qk-span-7"><div class="qk-stack"><div id="gc-wpcard"></div></div></div><div class="qk-span-5"><div class="qk-stack">' + tp + '</div></div>';
    var wp = g.wp || null, flow = g.flow || null;
    html += '</div>';
    if (fb && (g.drives || g.epa)) html += '<div class="qk-grid cc-grid"><div class="qk-span-7" id="gc-drives"></div><div class="qk-span-5" id="gc-epa"></div></div>';
    if ((g.plays || []).length) g.plays = g.plays.slice().sort(function (x, y) { return Math.abs(y.wpa || 0) - Math.abs(x.wpa || 0); });
    if ((g.plays || []).length) html += U.card('Highest-leverage plays', 'The plays that moved our win chance most (win chance added for the home side, in points).', '<ol class="cc-plays">' + g.plays.slice(0, 8).map(function (x) {
      return '<li><span class="t">' + esc(perLabel(L, g.season, x.period) + ' ' + (isNum(x.clock) ? fmtClock(x.clock / 60) : (x.clock || ''))) + '</span><span class="tx">' + (x.team ? QK.teamMark(CC.team(L, x.team) || {}, 'sm') : '') + esc(x.text || '') + '</span><b class="' + CC.cls(x.wpa) + '">' + (isNum(x.wpa) ? QK.fmt.pp(x.wpa) : '') + '</b></li>'; }).join('') + '</ol>');
    if (CC.hk(L)) html += '<div class="qk-grid cc-grid"><div class="qk-span-7"><div class="qk-stack">' + CC.hkBox(L, g) + '</div></div><div class="qk-span-5"><div class="qk-stack">' + leadersBlock(L, g) + teamStats(L, g) + '</div></div></div>' + CC.hkSkaters(L, g) + CC.hkAttempts(L, g) + (g.source && g.source !== 'ESPN' ? CC.hkCredit(true) : '');
    else html += '<div class="qk-grid cc-grid"><div class="qk-span-8">' + (fb ? boxFootball(L, g) : boxHoops(L, g)) + '</div><div class="qk-span-4"><div class="qk-stack">' + leadersBlock(L, g) + teamStats(L, g) + '</div></div></div>';
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
    if (CC.hk(L)) { if (!CC.hkFlow(L, g, wpNode) && st !== 'pre') wpNode.innerHTML = U.card('Score flow', '', QK.empty('No goal-by-goal record', 'The scoring summary comes with the box score.')); return; }
    var hasWp = wp && ((wp.model && wp.model.length > 2) || (wp.espn && wp.espn.length > 2));
    var hasFlow = flow && flow.length > 2;
    if (hasWp || hasFlow) {
      wpNode.innerHTML = U.card(hasWp ? 'Win chance through the game' : 'Score flow', hasWp ? 'Our chance the home side wins, after each play' + (wp.espn && wp.espn.length && wp.model && wp.model.length ? '; dashed: ESPN’s, for reference.' : '.') : 'Home lead through the game.',
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
    } else wpNode.innerHTML = st === 'pre' ? '' : U.card('Win chance through the game', '', QK.empty('No play-by-play', 'ESPN has no play-by-play for this game.'));
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
        var cols2 = CC.pair(L, g.away, g.home);
        QKC.bar('#gc-epa-ch', { cats: ['EPA/play', 'Pass', 'Rush'], legend: true, valName: 'EPA per play', fmt: function (v) { return CC.signed(v, 2); },
          series: [{ name: CC.tabbr(L, g.away), data: [E[g.away].epa_play, E[g.away].pass_epa, E[g.away].rush_epa], color: cols2[0] }, { name: CC.tabbr(L, g.home), data: [E[g.home].epa_play, E[g.home].pass_epa, E[g.home].rush_epa], color: cols2[1] }] });
      }
      U.wire(dn);
    }
  });
});

})(window.CC);
