/* The Quant Footballer — Players: find a player, leaders across competitions, and ONE page per player across every
 * competition he plays, season by season.
 *
 *   #/players                     search the people index (position, nationality, competition, club or name), the
 *                                 most-played players this season, leader cards (data/lab/leaders.json) and the value leaders
 *   #/players/leaders             one row per player over every competition, club football, his national team or one
 *                                 competition, this season, last season or a calendar window (data/lab/, UNIFIED_PAYLOADS
 *                                 14), raw and league-adjusted rates, percentiles
 *   #/player/<pid>[?tab=overview|seasons|matches|shots|transfers&scope=club|intl&c=<slug>&e=<era>]
 *                                 the player on kit v4 "Broadcast" (rk-player.js, MIGRATION_V4 step 4): the club-colour
 *                                 hero with the black strip of five numbers and the short version; the LED meters against
 *                                 the formation-role group in the main competition (peer group and sample stated, early
 *                                 metrics dashed, last season's ▼) with "How sure are we?", beside the tale of the tape
 *                                 against the closest match (chips switch); the next match as the scoreboard bug beside
 *                                 the last game (box score and xG race); the game log; game by game and their type;
 *                                 movement; then peers, season by season, charts and value (loaded when seen). Other
 *                                 tabs: the full career table, the match log with form, every percentile and the shot
 *                                 map per competition, transfers. Filters live in the query.
 *
 * Reads people/<pid>.json (docs/site/UNIFIED_PAYLOADS.md 2, 9-14), people_index.json, data/lab/, value/players.json,
 * value/lines.json, value/transfers.json and, per live competition, players_live.json and shots.json. */
(function (FB) {
'use strict';

var QK = window.QK, QKC = window.QKC;
var esc = FB.esc, isNum = FB.isNum, num = FB.num, int = FB.int;

var KIND_ORDER = FB.KIND_ORDER, KIND_LABEL = FB.KIND_LABEL;
var NEUTRAL = { 'club-world-cup': 1, 'intercontinental-cup': 1 };
var RADAR_OUT = [
  ['npxg_90', 'npxG/90'], ['shots_90', 'Shots/90'], ['xa_90', 'xA/90'], ['key_passes_90', 'Key passes/90'], ['pass_pct', 'Pass %'], ['dribbles_90', 'Dribbles/90'],
  ['prog_carries_90', 'Prog. carries/90'], ['tackles_90', 'Tackles/90'], ['interceptions_90', 'Interceptions/90'], ['aerial_pct', 'Aerial %'], ['recoveries_90', 'Recoveries/90'], ['rating', 'Rating']
];
var RADAR_GK = [
  ['saves_90', 'Saves/90'], ['save_pct', 'Save %'], ['goals_prevented_90', 'Goals prevented/90'], ['conceded_90', 'Conceded/90'], ['sweeper_90', 'Sweeper/90'],
  ['high_claims_90', 'High claims/90'], ['pass_pct', 'Pass %'], ['long_ball_pct', 'Long-ball %'], ['rating', 'Rating']
];

/* ── The comparison metric sets: ONE place for the player card's percentiles, "Where he sits" and the compare page
   (lab.js reads FB.PLAYER_SETS). Until docs/METRICS_SPEC.md is committed the peer group is the position letter the
   payloads rank by (players_live / lab rows `position`: G, D, M, F) over each view's minutes floor, and the metrics
   are stable, predictive rates from the draft spec (docs/_design/metrics/football.json) that every payload already
   carries. The role sets (CB, FB, DM/CM, AM/W, ST, GK) replace these four once the spec and the role field land.
   PLAYER_SETS[letter] = [[group label, [metric keys]]]; PLAYER_DIST[letter] = the "Where he sits" choices. */
var PLAYER_SETS = {
  F: [['Shooting', ['npxg_90', 'shots_90', 'xg_per_shot', 'goals_90']], ['Creating', ['npxg_xa_90', 'xa_90', 'key_passes_90', 'shot_creation_90']],
    ['On the ball', ['dribbles_90', 'prog_actions_90', 'opp_half_passes_90', 'loss_per_100']], ['Overall', ['rating']]],
  M: [['Passing and progression', ['opp_half_passes_90', 'long_balls_90', 'pass_pct', 'prog_actions_90']], ['Creating', ['npxg_xa_90', 'xa_90', 'key_passes_90', 'shot_creation_90']],
    ['Defending', ['padj_tkl_int_90', 'recoveries_90', 'ball_wins_90', 'duel_pct']], ['Overall', ['rating']]],
  D: [['Defending', ['padj_tkl_int_90', 'aerials_won_90', 'aerial_pct', 'clearances_90', 'recoveries_90']], ['On the ball', ['opp_half_passes_90', 'pass_pct', 'long_ball_pct', 'prog_carries_90']],
    ['Attacking', ['npxg_xa_90', 'crosses_90', 'key_passes_90']], ['Overall', ['rating']]],
  G: [['Shot stopping', ['goals_prevented_90', 'save_pct', 'saves_90']], ['Command of the area', ['high_claims_90', 'sweeper_90']],
    ['Distribution', ['pass_pct', 'long_ball_pct', 'passes_90']], ['Overall', ['rating']]]
};
var PLAYER_DIST = { F: ['npxg_xa_90', 'npxg_90', 'shot_creation_90', 'rating'], M: ['npxg_xa_90', 'padj_tkl_int_90', 'opp_half_passes_90', 'rating'],
  D: ['padj_tkl_int_90', 'aerials_won_90', 'opp_half_passes_90', 'rating'], G: ['goals_prevented_90', 'save_pct', 'high_claims_90', 'rating'] };
var PEER_NAME = { G: 'goalkeepers', D: 'defenders', M: 'midfielders', F: 'forwards' };
/* A percentile is drawn as early (dashed) below these minutes: the draft spec flags a small sample under 900 minutes,
   and shot stopping needs 1,800. */
function earlyMin(letter, key) { return letter === 'G' && (key === 'goals_prevented_90' || key === 'save_pct' || key === 'saves_90') ? 1800 : 900; }
FB.PLAYER_SETS = PLAYER_SETS; FB.PLAYER_DIST = PLAYER_DIST; FB.PEER_NAME = PEER_NAME; FB.playerEarlyMin = earlyMin;

// ── small helpers ─────────────────────────────────────────────────────────

function sum(list, k) { return FB.sum(list, k); }
function wavg(list, k) { return FB.wavg(list, k, 'min'); }
function per90(v, m) { return m ? v * 90 / m : null; }
function eraKey(e) { return FB.eraKey(e); }
function eraOfSeason(s) {
  var t = String(s || '');
  var m = /(\d\d)\/(\d\d)/.exec(t);
  if (m) return '20' + m[1] + '/' + m[2];
  m = /(19|20)\d\d/.exec(t);
  return m ? m[0] : t;
}
/* A date's season in a player's frame: split seasons turn on 1 August, calendar seasons are the year. */
function frameEra(frame, date) {
  var d = String(date || '');
  if (d.length < 7) return null;
  var y = Number(d.slice(0, 4)), m = Number(d.slice(5, 7));
  if (frame !== 'split') return String(y);
  var s = m >= 8 ? y : y - 1;
  return s + '/' + ('0' + ((s + 1) % 100)).slice(-2);
}
/* A team link with a monogram mark: crest files exist for only some clubs (a missing one would 404). */
function monoLink(tid, name) {
  var mark = QK.teamMark({ name: name }, 'sm');
  if (tid && FB.clubRow(tid)) return '<a class="fb-ent" href="' + esc(FB.href.club(tid)) + '">' + mark + '<span class="fb-ent-n">' + esc(name) + '</span></a>';
  return '<span class="fb-ent">' + mark + '<span class="fb-ent-n">' + esc(name) + '</span></span>';
}
function compOk(slug) { var c = FB.comp(slug); return !!(c && c.ok); }
function compName(slug, names) { var c = FB.comp(slug); return c ? c.name : (((names || {})[slug] || {}).name || slug || '—'); }
function compShort(slug, names) { var c = FB.comp(slug); return c ? (c.short_name || c.name) : compName(slug, names); }
function kindOfSlug(slug, names) { return ((names || {})[slug] || {}).kind || FB.kindOf(slug); }
function scopeOfSlug(slug, names) { var s = ((names || {})[slug] || {}).scope; return s || (FB.kindOf(slug) === 'international' ? 'international' : 'club'); }
/* A club or national team link; crests are left to the hero (most clubs have no crest file). */
function teamA(tid, name) {
  if (!name && !tid) return '<span class="qk-muted">—</span>';
  if (tid && FB.clubRow(tid)) return FB.clubLink(tid, name || FB.clubName(tid));
  return '<span class="fb-pl-team">' + esc(name || '—') + '</span>';
}
/* The competition's season page: the live edition, or a past one with ?s=. */
function seasonHref(slug, sid, tab) {
  var c = FB.comp(slug);
  if (!c || !c.ok) return null;
  return String(sid) === FB.currentSeason(c).sid || !isNum(Number(sid)) || sid === null || sid === undefined ? FB.href.comp(slug, tab) : FB.href.comp(slug, tab, { s: sid });
}
/* A match page exists for the live edition and for matches in the last 365 days (UNIFIED_PAYLOADS 13.6). */
var PAGE_CUTOFF = new Date(Date.now() - 365 * 864e5).toISOString().slice(0, 10);
function hasMatchPage(r) {
  var c = FB.comp(r.comp);
  if (!c || !c.ok || !r.gid) return false;
  return String(FB.currentSeason(c).sid) === String(r.sid) || String(r.date || '') >= PAGE_CUTOFF;
}
function resClass(res) { var w = String(res || '').charAt(0); return w === 'W' ? 'w' : w === 'L' ? 'l' : w === 'D' ? 'd' : ''; }
function posLabel(p) { return FB.POS_LABEL[p] || 'Player'; }
function nn(v, d) { return isNum(v) ? num(v, d) : '—'; }
function chartEmpty(el, title, text) { if (!el) return; el.style.height = 'auto'; el.innerHTML = FB.empty(title, text); }
/* Run fn once node is near the viewport (heavy payloads such as value/players.json load only when their card is seen). */
function whenVisible(node, fn) {
  if (!node) return;
  if (!('IntersectionObserver' in window)) { fn(); return; }
  var io = new IntersectionObserver(function (es) {
    if (es.some(function (e) { return e.isIntersecting; })) { io.disconnect(); fn(); }
  }, { rootMargin: '240px' });
  io.observe(node);
}
function metaMap(list) { var m = {}; (list || []).forEach(function (x) { if (x && x.key) m[x.key] = x; }); return m; }
function cap1(t) { t = String(t || ''); return t.charAt(0).toUpperCase() + t.slice(1); }

// ── the person file, normalised ───────────────────────────────────────────

function personRows(doc) {
  var names = doc.comps || {};
  var seasons = (doc.seasons || []).map(function (s) {
    return FB.merge(s, { kind: s.kind || kindOfSlug(s.comp, names), scope: s.scope || scopeOfSlug(s.comp, names), era: s.era || eraOfSeason(s.season), cname: compName(s.comp, names) });
  });
  var pick = function (r, a, b) { return isNum(r[a]) ? r[a] : r[b]; };
  var archive = (doc.archive || []).map(function (s) {
    return FB.merge(s, {
      min: pick(s, 'min', 'minutes'), g: pick(s, 'g', 'goals'), a: pick(s, 'a', 'assists'), rt: pick(s, 'rt', 'rating'),
      kind: s.kind || (s.comp ? kindOfSlug(s.comp, names) : 'league'), scope: s.scope || (s.comp ? scopeOfSlug(s.comp, names) : 'club'),
      era: s.era || eraOfSeason(s.season), cname: s.comp ? compName(s.comp, names) : (s.tournament || '—'), source: 'archive'
    });
  });
  var eraBy = {};
  seasons.forEach(function (s) { eraBy[s.comp + '|' + s.sid] = s.era; });
  var f = doc.apps_fields || [];
  var apps = (doc.apps || []).map(function (r) {
    var o = {};
    for (var i = 0; i < f.length; i++) o[f[i]] = r[i];
    o.scope = scopeOfSlug(o.comp, names);
    o.kind = kindOfSlug(o.comp, names);
    o.era = ((o.scope === 'international' || NEUTRAL[o.comp]) && doc.frame ? frameEra(doc.frame, o.date) : null) || eraBy[o.comp + '|' + o.sid] || frameEra(doc.frame || 'split', o.date) || '';
    return o;
  });
  return { seasons: seasons, archive: archive, apps: apps, all: seasons.concat(archive) };
}
function keepQ(q) {
  return function (r) {
    return (!q.scope || r.scope === (q.scope === 'intl' ? 'international' : 'club')) && (!q.c || r.comp === q.c) && (!q.e || r.era === q.e);
  };
}
function filterLabel(q, names) {
  var bits = [q.c ? compName(q.c, names) : q.scope === 'club' ? 'Club football' : q.scope === 'intl' ? 'International football' : 'All competitions'];
  if (q.e) bits.push(q.e);
  return bits.join(' · ');
}

// ══ #/players ═════════════════════════════════════════════════════════════

function playersNav(active) {
  return FB.subnav([['#/players', 'Find a player', 'find'], ['#/players/leaders', 'Leaders across competitions', 'leaders']], active, 'Players');
}

FB.route('players', function (el, p) {
  if (p.tab === 'leaders') return renderLeaders(el, p);
  var q = p.query || {};
  el.innerHTML = FB.pageHead('Players', 'Every player, every competition',
    'One record per player, however many competitions: search the registry, see who has played most this season, and open any player for a season-by-season career.') +
    playersNav('find') + '<div id="pl-hot" class="fb-pl-hot"></div>' +
    '<div id="pl-leadscope" class="fb-pl-leadscope"></div><div class="fb-pl-leadgrid" id="pl-leads">' + FB.card('Value added', 'This season, every competition', FB.loading('lines', 5)) + FB.card('Goals', '', FB.loading('lines', 5)) + FB.card('Assists', '', FB.loading('lines', 5)) + FB.card('Rating', '450+ minutes', FB.loading('lines', 5)) + '</div>' +
    FB.card('Find a player', '<span id="pl-count">Loading the registry…</span>',
      '<div id="pl-tools"></div><div id="pl-table">' + FB.loading('lines', 8) + '</div>', { flush: false }) +
    FB.grid(FB.card('Value leaders', 'Goals above replacement (GAR) over the last 12 months of club football: the goals a player adds over a freely available replacement in the same role. <a href="#/value">Full value leaderboard →</a>',
      FB.chartBox('pl-gar', 380, 'Top players by goals above replacement') + QK.explain('<b>What’s that number?</b> A replacement-level player is the kind a club can sign cheaply at any time. +5 GAR means about five more goals, scored or saved, than that player would have managed in the same minutes and role.'), { span: 7 }) +
      FB.card('Most valuable', 'Sofascore market value (reference only), current squads.', '<div id="pl-mv">' + FB.loading('lines', 6) + '</div>', { span: 5 }));

  var boardP = FB.load('lab/leaders.json').then(function (board) {
    if (board && board.scopes) return { board: board };
    return FB.load('hub.json').then(function (h) { return { hub: h }; });
  });
  boardP.then(function (x) { if (FB.alive(el)) drawLeadCards(el, x.board || null, x.hub || null); });
  var people = FB.peopleIndex().then(function (pi) {
    if (!FB.alive(el)) return;
    drawFinder(el, pi.list, q);
    drawMostValuable(el, pi.list);
  });
  var valP = FB.load('value/players.json');
  valP.then(function (v) {
    if (!FB.alive(el)) return;
    drawGar(el, v);
    /* the finder's GAR column: our value model's last 12 months, joined on the person id */
    GAR_BY = {};
    FB.rows(v).forEach(function (z) { if (isNum(z.gar)) GAR_BY[String(z.id)] = [z.gar, z.gar90]; });
    if (FIND_REDRAW) FIND_REDRAW();
  });
  Promise.all([boardP, valP]).then(function (arr) { if (FB.alive(el)) drawHotBand(el, arr[0] || {}, arr[1]); });
  return people;
});

/* v4 "Who's hot": the black power list (QK.band + QK.hotRow), one name a board across every competition this season,
   and a line on what each number means. */
function leadLists(board, hub) {
  var scopes = (board || {}).scopes || null;
  if (scopes && scopes.all) return scopes.all;
  var once = function (rows) { var seen = {}; return (rows || []).filter(function (r) { if (seen[r.id]) return false; seen[r.id] = 1; return true; }); };
  var H = (hub || {}).leaders || {};
  return { goals: once(H.goals), assists: once(H.assists), rating: once((H.rating || []).filter(function (r) { return (r.minutes || 0) >= 450; })) };
}
function drawHotBand(el, x, v) {
  var box = el.querySelector('#pl-hot');
  if (!box) return;
  var L = leadLists(x.board, x.hub);
  var whereOf = function (r) { return [r.team || '', r.mix ? '' : (r.comp_name || (r.comp ? FB.compName(r.comp, true) : ''))].filter(Boolean).join(' · '); };
  var nextOf = function (list, f) { var n = list[1]; return n ? { name: n.name, value: f ? f(n.value) : n.value } : null; };
  var items = [], used = {};
  /* one name a card: a player already in the row gives way to the next on that board, and the card says who leads it */
  var take = function (list) { var r0 = (list || []).filter(function (z) { return z && !used[String(z.id)]; })[0]; if (r0) used[String(r0.id)] = 1; return r0; };
  var lead = function (list, me, f) { var t = (list || [])[0]; return t && t !== me ? 'Behind only ' + t.name + ' (' + (f ? f(t.value) : t.value) + '). ' : ''; };
  var g = take(L.goals), a = take(L.assists), r = take(L.rating);
  var top = function (list, me) { return (list || [])[0] === me; };
  if (g) items.push({ sport: 'football', kicker: whereOf(g) || 'Football', title: top(L.goals, g) ? 'Most goals' : 'Goals', name: g.name, value: g.value, href: FB.href.player(g.id), next: top(L.goals, g) ? nextOf(L.goals) : null,
    expl: lead(L.goals, g) + (isNum(g.xg) ? 'From shots worth ' + num(g.xg, 1) + ' expected goals: ' + (g.value - g.xg >= 2 ? 'finishing well above an average shooter.' : g.value - g.xg <= -2 ? 'unlucky or wasteful in front of goal.' : 'about what the chances were worth.') : 'Every competition this season.') });
  if (a) items.push({ sport: 'football', kicker: whereOf(a) || 'Football', title: top(L.assists, a) ? 'Most assists' : 'Assists', name: a.name, value: a.value, href: FB.href.player(a.id), next: top(L.assists, a) ? nextOf(L.assists) : null,
    expl: lead(L.assists, a) + (isNum(a.xa) ? 'Passes worth ' + num(a.xa, 1) + ' expected assists: the chances created, whatever the finish.' : 'Every competition this season.') });
  if (r) items.push({ sport: 'football', kicker: whereOf(r) || 'Football', title: top(L.rating, r) ? 'Best rating' : 'Rating', name: r.name, value: num(r.value, 2), href: FB.href.player(r.id), next: top(L.rating, r) ? nextOf(L.rating, function (z) { return num(z, 2); }) : null,
    expl: lead(L.rating, r, function (z) { return num(z, 2); }) + 'Out of 10, weighted by minutes' + (isNum(r.minutes) ? ' over ' + FB.int(r.minutes) + ' minutes' : '') + '. A 7 is a good game; above 8 is rare over a season.' });
  var gar = FB.rows(v).filter(function (z) { return isNum(z.gar) && (z.min || 0) >= 900 && !used[String(z.id)]; }).sort(function (p, q) { return q.gar - p.gar; });
  if (gar[0]) used[String(gar[0].id)] = 1;
  if (gar[0]) items.push({ sport: 'football', kicker: gar[0].club || 'Football', title: 'Most value added', name: gar[0].name, value: FB.signed(gar[0].gar, 1), href: FB.href.player(gar[0].id),
    next: gar[1] ? { name: gar[1].name, value: FB.signed(gar[1].gar, 1) } : null, expl: 'Goals above a replacement-level player in the same role over the last 12 months of club football, from our value model.' });
  var fin = (L.goals || []).filter(function (z) { return isNum(z.xg) && z.value >= 5 && !used[String(z.id)]; }).map(function (z) { return [z.value - z.xg, z]; }).sort(function (p, q) { return q[0] - p[0]; });
  if (fin[0] && fin[0][0] > 0) items.push({ sport: 'football', kicker: whereOf(fin[0][1]) || 'Football', title: 'Goals above expected', name: fin[0][1].name, value: '+' + num(fin[0][0], 1), href: FB.href.player(fin[0][1].id),
    next: fin[1] ? { name: fin[1][1].name, value: '+' + num(fin[1][0], 1) } : null, expl: fin[0][1].value + ' goals from ' + num(fin[0][1].xg, 1) + ' xG. Runs like this rarely last: finishing above xG mostly evens out.' });
  if (!items.length) { box.innerHTML = ''; return; }
  box.innerHTML = QK.band(QK.sectionHead({ kicker: 'Who’s hot', title: 'The leaders, board by board', sub: cap1(['no', 'one', 'two', 'three', 'four', 'five'][items.length]) + ' boards this season, every competition: one name a card, and a line on what the number means.' }) + QK.hotRow(items));
}

/* Goals, assists and rating leaders, one row per player (data/lab/leaders.json): every competition, club football
   or national-team football this season. Falls back to hub.json's per-competition lists, one row per player. */
var LEAD_SCOPE = 'all';
function drawLeadCards(el, board, hub) {
  var box = el.querySelector('#pl-leads');
  if (!box) return;
  var scopes = (board || {}).scopes || null;
  var L, sub;
  if (scopes && scopes[LEAD_SCOPE]) {
    L = scopes[LEAD_SCOPE];
    sub = 'This season, ' + (LEAD_SCOPE === 'club' ? 'club competitions' : LEAD_SCOPE === 'intl' ? 'national-team football' : 'every competition') + ' together';
  } else {
    // hub.json lists lines per competition: keep each player's best one.
    var once = function (rows) { var seen = {}; return (rows || []).filter(function (r) { if (seen[r.id]) return false; seen[r.id] = 1; return true; }); };
    var H = (hub || {}).leaders || {};
    L = { goals: once(H.goals), assists: once(H.assists), rating: once((H.rating || []).filter(function (r) { return (r.minutes || 0) >= 450; })) };
    sub = 'This season, each player\'s best competition';
  }
  function list(rows, fmt, extra) {
    if (!rows || !rows.length) return FB.muted('No player data yet.');
    return '<ol class="fb-pl-rank">' + rows.slice(0, 6).map(function (r, i) {
      var where = r.mix ? r.mix.split(' · ').slice(0, 2).join(' · ') + (r.mix.split(' · ').length > 2 ? ' …' : '') : (r.comp_name || FB.compName(r.comp, true));
      return '<li><span class="r">' + (i + 1) + '</span><span class="n">' + FB.playerLink(r.id, r.name) + '<span class="s">' + esc(r.team || '') + ' · ' + esc(where) + '</span></span>' +
        '<b class="fb-num">' + fmt(r.value) + '</b>' + (extra ? '<span class="x fb-num">' + extra(r) + '</span>' : '') + '</li>';
    }).join('') + '</ol>';
  }
  var segBox = el.querySelector('#pl-leadscope');
  if (segBox) segBox.innerHTML = scopes ? FB.toolbar([FB.field('Leaders over', FB.seg('pl-lead-scope', [['all', 'All competitions'], ['club', 'Club competitions'], ['intl', 'National team']], LEAD_SCOPE, 'Leaders over'))]) : '';
  var garL = (L.gar || []).filter(function (r) { return isNum(r.value); });
  box.innerHTML =
    (garL.length ? FB.card('Value added' + QK.ours({ model: 'Player value model' }), 'Goals above replacement (GAR), 450+ minutes · ' + esc(sub.replace(/^This season, /, '')) + '. <a href="#/players/leaders?m=gar90">Per 90 →</a>',
      list(garL, function (v) { return FB.signed(v, 1); }, function (r) { return isNum(r.gar90) ? FB.signed(r.gar90, 2) + '/90' : ''; })) : '') +
    FB.card('Goals', esc(sub), list(L.goals, function (v) { return int(v); }, function (r) { return isNum(r.xg) ? 'xG ' + num(r.xg, 1) : ''; })) +
    FB.card('Assists', esc(sub), list(L.assists, function (v) { return int(v); }, function (r) { return isNum(r.xa) ? 'xA ' + num(r.xa, 1) : ''; })) +
    FB.card('Rating', '450+ minutes, minutes-weighted · ' + esc(sub.replace(/^This season, /, '')), list(L.rating, function (v) { return num(v, 2); }, function (r) { return int(r.minutes) + ' min'; }));
  if (scopes && segBox) FB.wireSeg(segBox, 'pl-lead-scope', function (v) { LEAD_SCOPE = v; drawLeadCards(el, board, hub); });
}

var FIND = { q: '', pos: '', nat: '', comp: '', min: 0 };
var GAR_BY = null, FIND_REDRAW = null;
function drawFinder(el, list, q0) {
  if (q0 && q0.q) FIND.q = q0.q;
  var nats = {};
  list.forEach(function (r) { if (r.nat) nats[r.nat] = (nats[r.nat] || 0) + 1; });
  var natOpts = Object.keys(nats).sort(function (a, b) { return nats[b] - nats[a]; }).slice(0, 80).sort();
  var compsSeen = {};
  list.forEach(function (r) { (r.comps || []).forEach(function (c) { compsSeen[c] = 1; }); });
  var compOpts = FB.comps().filter(function (c) { return compsSeen[c.slug]; }).map(function (c) { return [c.slug, c.name]; });
  var tools = el.querySelector('#pl-tools');
  tools.innerHTML = FB.toolbar([
    FB.field('Name or club', '<input class="qk-input fb-pl-search" id="pl-q" type="search" placeholder="Mbappé, Boca Juniors…" value="' + esc(FIND.q) + '" autocomplete="off">'),
    FB.field('Position', FB.seg('pl-pos', [['', 'All'], ['G', 'GK'], ['D', 'DEF'], ['M', 'MID'], ['F', 'FWD']], FIND.pos, 'Position')),
    FB.field('Nationality', FB.select('pl-nat', [['', 'Any']].concat(natOpts.map(function (n) { return [n, n]; })), FIND.nat, 'Nationality')),
    FB.field('Competition', FB.select('pl-comp', [['', 'Any']].concat(compOpts), FIND.comp, 'Competition', 'fb-pl-wide')),
    FB.field('Minutes this season', FB.select('pl-min', [['0', 'Any'], ['450', '450+'], ['900', '900+'], ['1800', '1,800+'], ['2700', '2,700+']], String(FIND.min), 'Minimum minutes'))
  ]);
  var t = null;
  var handle = null;
  function rowsNow() {
    var nq = FIND.q ? norm(FIND.q) : '';
    var out = list.filter(function (r) {
      if (FIND.pos && r.pos !== FIND.pos) return false;
      if (FIND.nat && r.nat !== FIND.nat) return false;
      if (FIND.comp && (r.comps || []).indexOf(FIND.comp) < 0) return false;
      if (FIND.min && (r.min || 0) < FIND.min) return false;
      if (nq) { var s = r._s || (r._s = norm(r.name + ' ' + (r.club || '') + ' ' + (r.nt || ''))); if (s.indexOf(nq) < 0) return false; }
      return true;
    });
    return out.slice(0, 300).map(function (r) {
      var gv = GAR_BY ? GAR_BY[String(r.id)] : null;
      return { id: r.id, name: r.name, pos: r.pos, posName: posLabel(r.pos), age: FB.ageOf(r.dob), nat: r.nat, club: r.club, club_tid: r.club_tid, nt: r.nt, nt_tid: r.nt_tid, season: r.season, min: r.min || 0, mv: r.mv, nc: (r.comps || []).length, _n: out.length,
        gar: gv ? gv[0] : null, gar90: gv ? gv[1] : null };
    });
  }
  function draw() {
    var rows = rowsNow();
    FB.set('pl-count', (rows.length ? int(rows[0]._n) : '0') + ' players match' + (rows.length && rows[0]._n > 300 ? ' (the 300 with most minutes this season shown)' : '') + ' · ' + int(list.length) + ' in the registry · minutes are each player’s own season (a calendar 2026 is near its end, a 2026/27 is weeks old)');
    var cols = [
      { key: 'name', label: 'Player', type: 'entity', sub: 'posName', href: function (r) { return FB.href.player(r.id); } },
      { key: 'age', label: 'Age', num: true },
      { key: 'club', label: 'Club', fmt: function (v, r) { return v ? teamA(r.club_tid, v) : '<span class="qk-muted">—</span>'; } },
      { key: 'nt', label: 'National team', fmt: function (v, r) { return v ? teamA(r.nt_tid, v) : '<span class="qk-muted">' + esc(r.nat || '—') + '</span>'; } },
      { key: 'min', label: 'Minutes', num: true, tip: 'Minutes in the player\'s current season (their own frame: 2026/27 for a European, 2026 for a Brazilian), every competition.', fmt: function (v, r) { return int(v) + ' <span class="qk-muted fb-pl-era">' + esc(r.season || '') + '</span>'; } },
      { key: 'gar', label: 'GAR', num: true, ours: { name: 'Player value model', about: 'Goals above a replacement-level player in the same role over the last 12 months of club football.' },
        tip: 'Goals above replacement over the last 12 months of club football, from our player value model; GAR/90 under it.', fmt: function (v, r) { return isNum(v) ? '<b>' + FB.signed(v, 1) + '</b>' + (isNum(r.gar90) ? ' <span class="qk-muted">' + FB.signed(r.gar90, 2) + '/90</span>' : '') : '<span class="qk-muted">—</span>'; } },
      { key: 'mv', label: 'Market value', num: true, tip: 'Sofascore\'s market value, reference only.', fmt: function (v) { return isNum(v) ? FB.money(v) : '—'; } },
      { key: 'nc', label: 'Comps', num: true, tip: 'Competitions played in across the stores.' }
    ];
    if (handle) handle.setRows(rows); else handle = QK.leaderboard(el.querySelector('#pl-table'), { columns: cols, rows: rows, sort: { key: 'min', dir: 'desc' }, dense: true, maxHeight: 620, caption: 'Players' });
  }
  draw();
  FIND_REDRAW = function () { if (FB.alive(el)) draw(); };
  var input = el.querySelector('#pl-q');
  input.addEventListener('input', function () { clearTimeout(t); t = setTimeout(function () { FIND.q = input.value; FB.setQuery({ q: FIND.q || null }); draw(); }, 140); });
  FB.wireSeg(tools, 'pl-pos', function (v) { FIND.pos = v; draw(); });
  el.querySelector('#pl-nat').addEventListener('change', function (e) { FIND.nat = e.target.value; draw(); });
  el.querySelector('#pl-comp').addEventListener('change', function (e) { FIND.comp = e.target.value; draw(); });
  el.querySelector('#pl-min').addEventListener('change', function (e) { FIND.min = Number(e.target.value) || 0; draw(); });
}
function norm(s) { return String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, ''); }

function drawMostValuable(el, list) {
  var top = list.filter(function (r) { return isNum(r.mv); }).sort(function (a, b) { return b.mv - a.mv; }).slice(0, 10);
  var box = el.querySelector('#pl-mv');
  if (!box) return;
  if (!top.length) { box.innerHTML = FB.muted('No market values yet.'); return; }
  var max = top[0].mv;
  box.innerHTML = '<ol class="fb-pl-rank">' + top.map(function (r, i) {
    return '<li><span class="r">' + (i + 1) + '</span><span class="n">' + FB.playerLink(r.id, r.name) + '<span class="s">' + esc(r.club || '') + ' · ' + esc(r.pos || '') + '</span></span>' +
      '<span class="fb-rowbar"><i style="width:' + (r.mv / max * 100).toFixed(0) + '%"></i></span><b class="fb-num">' + FB.money(r.mv) + '</b></li>';
  }).join('') + '</ol>';
}
function drawGar(el, v) {
  var box = el.querySelector('#pl-gar');
  if (!box) return;
  var rows = FB.rows(v).filter(function (r) { return isNum(r.gar) && (r.min || 0) >= 900; }).sort(function (a, b) { return b.gar - a.gar; }).slice(0, 15);
  if (!rows.length) { chartEmpty(box, 'No value model yet', 'The value layer is rebuilt with the site.'); return; }
  QKC.bar(box, {
    horizontal: true, labels: true, labelWidth: 150, fmt: function (x) { return num(x, 1); }, valName: 'Goals above replacement',
    cats: rows.map(function (r) { return r.name + ' · ' + (r.club || ''); }),
    series: [{ name: 'Goals above replacement', data: rows.map(function (r) { return Math.round(r.gar * 10) / 10; }), color: 'model' }],
    hrefs: rows.map(function (r) { return FB.href.player(r.id); }), label: 'Goals above replacement, last 12 months'
  });
}

// ── #/players/leaders ─────────────────────────────────────────────────────

/* One row per player (data/lab/<window>/<scope>.json): every competition, club football, national-team football or
   one competition, this season, last season or a calendar window. Attacking rates can be league-adjusted (the row's
   minutes-weighted scoring factor). Percentiles are against his formation-role group (FB.MSET: CB, FB, DM/CM, AM/W, ST,
   GK) in the view, over max(the group's minimum, the minutes shown); the position letters when the role payload is
   missing. Our model metrics (GAR/90 and GAR, value_fields.py) lead the picker as "Our models" and are the default,
   then the spec's headline set for the role, then the box score by group; names from the spec (FB.labOurs, lab.js). */
var LD_WIN = [['season', 'This season'], ['last', 'Last season'], ['365', 'Last 12 months'], ['ytd', 'Calendar year so far']];
function renderLeaders(el, p) {
  var q = p.query || {};
  el.innerHTML = FB.pageHead('Players', 'Leaders across competitions',
    'Every player once: minutes and rates over every competition played, club football only, national-team football only, or one competition. Attacking rates can be league-adjusted with the pooled model\'s scoring factors so output from different leagues sits on one footing.') +
    playersNav('leaders') +
    '<div id="ld-body">' + FB.card('Loading the board', '', FB.loading('lines', 10)) + '</div>';
  var st = { win: q.w || 'season', scope: q.c || q.scope || 'all', pos: q.pos || '', min: isNum(Number(q.min)) && q.min !== undefined && q.min !== '' ? Number(q.min) : null, key: q.m || 'gar90' };
  var LO = FB.labOurs || null;
  return Promise.all([FB.labIndex(), LO ? LO.load() : null]).then(function (arr0) {
    var ix = arr0[0];
    if (!FB.alive(el)) return;
    var body = el.querySelector('#ld-body');
    if (!ix || !ix.scopes) { body.innerHTML = FB.empty('No board yet', 'The leaderboards (data/lab/) are rebuilt with the site.'); return; }
    if (!ix.scopes[st.win]) st.win = 'season';
    var adjusted = ix.adjusted_keys || [];
    var specL = function (k, f) { return LO ? LO.label(k, f) : f; };
    var oursOf = function (k) { return LO ? LO.oursOf(k) : null; };
    var OURS_M = ((LO && LO.metrics) || []).map(function (m) { return { key: m.key, label: specL(m.key, m.label), group: 'Our models', fmt: m.fmt, scope: 'all', ours: true, desc: LO && LO.explain ? LO.explain(m.key, m.tip) : m.tip }; });
    var BOX_M = (ix.metrics || []).map(function (m) { var c = {}, k; for (k in m) if (Object.prototype.hasOwnProperty.call(m, k)) c[k] = m[k]; c.label = specL(m.key, m.label); return c; });
    var metrics = BOX_M;
    body.innerHTML = FB.card('<span id="ld-title">Leaders</span>', '<span id="ld-sub"></span>',
      '<div id="ld-tools"></div><div id="ld-ours" class="fb-mt"></div>' + QK.explain('<b>What’s that number?</b> A <b>league-adjusted</b> rate multiplies an attacking number by the scoring factor of the leagues it came from (our pooled model), so 0.50 npxG per 90 in a league where goals come easily counts for less than the same in a tougher one. <b>Pctl</b> is the player’s percentile against the same formation role: 90 means better than 90 in 100.', { cls: 'fb-mt' }) +
      FB.chartBox('ld-chart', 420, 'Top 15 on the chosen metric') + '<div id="ld-table" class="fb-mt"></div>');
    var V = null, R = null;
    var ROLE_SEG = [['', 'All']].concat(FB.MSET.groups.map(function (g) { return [g.id, { gk: 'GK', cb: 'CB', fb: 'FB', dm_cm: 'DM/CM', am_w: 'AM/W', st: 'ST' }[g.id] || g.short]; }));
    function rolesOn() { return !!(R && R.ok); }
    function single() { return !FB.LAB_SCOPES[st.scope]; }
    function metricOpts(scope) {
      var groups = [];
      var ours = OURS_M.filter(function (m) { return V && V.idx[m.key] !== undefined; });
      if (ours.length) groups.push({ group: 'Our models', items: ours.map(function (m) { return [m.key, m.label]; }) });
      /* the spec's headline set for the role picked (every role's when none is), after our models */
      var cat = LO && QK.spec ? QK.spec.get('football') : null, head = {}, n = 0;
      (st.pos && FB.MSET.groups.some(function (g) { return g.id === st.pos; }) ? [st.pos] : ['cb', 'fb', 'dm_cm', 'am_w', 'st', 'gk']).forEach(function (gid) {
        (cat ? cat.headline(gid) : []).forEach(function (k) { if (head[k] === undefined) head[k] = n++; });
      });
      var key = { group: 'Box score · key numbers', items: [] };
      var shown = metrics.filter(function (m) { return scope === 'all' || m.scope === 'all' || m.scope === scope; });
      shown.filter(function (m) { return head[m.key] !== undefined; }).sort(function (a, b) { return head[a.key] - head[b.key]; }).forEach(function (m) {
        key.items.push([m.key, m.label]);
        if (adjusted.indexOf(m.key) >= 0 && !single()) key.items.push([m.key + '_adj', m.label + ' (league-adjusted)']);
      });
      if (key.items.length) groups.push(key);
      shown.filter(function (m) { return head[m.key] === undefined; }).forEach(function (m) {
        var gname = 'Box score · ' + m.group;
        var gr = groups.filter(function (x) { return x.group === gname; })[0];
        if (!gr) { gr = { group: gname, items: [] }; groups.push(gr); }
        gr.items.push([m.key, m.label]);
        if (adjusted.indexOf(m.key) >= 0 && !single()) gr.items.push([m.key + '_adj', m.label + ' (league-adjusted)']);
      });
      return groups;
    }
    function tools() {
      if (rolesOn() && st.pos && !FB.MSET.groups.some(function (g) { return g.id === st.pos; })) st.pos = { G: 'gk', D: 'cb', M: 'dm_cm', F: 'st' }[st.pos] || '';
      if (!rolesOn() && st.pos && ['G', 'D', 'M', 'F'].indexOf(st.pos) < 0) st.pos = '';
      var scope = st.pos === 'G' || st.pos === 'gk' ? 'gk' : st.pos ? 'out' : 'all';
      var groups = metricOpts(scope);
      var keys = [];
      groups.forEach(function (gr) { gr.items.forEach(function (i) { keys.push(i[0]); }); });
      if (keys.indexOf(st.key) < 0) st.key = keys.indexOf(st.key.replace(/_adj$/, '')) >= 0 ? st.key.replace(/_adj$/, '') : (keys.indexOf('gar90') >= 0 ? 'gar90' : scope === 'gk' ? 'saves_90' : (single() ? 'npxg_90' : 'npxg_90_adj'));
      el.querySelector('#ld-tools').innerHTML = FB.toolbar([
        FB.field('Season', FB.select('ld-w', LD_WIN.filter(function (w) { return ix.scopes[w[0]]; }), st.win, 'Season or window')),
        FB.field('Competitions', FB.select('ld-c', FB.labScopeOptions(ix, st.win), st.scope, 'Which competitions count', 'fb-pl-wide')),
        FB.field('Metric', FB.select('ld-m', groups, st.key, 'Metric', 'fb-pl-wide')),
        rolesOn() ? FB.field('Role', FB.seg('ld-pos', ROLE_SEG, st.pos, 'Formation role group')) : FB.field('Position', FB.seg('ld-pos', [['', 'All'], ['G', 'GK'], ['D', 'DEF'], ['M', 'MID'], ['F', 'FWD']], st.pos, 'Position')),
        FB.field('Min. minutes', '<input class="qk-input fb-pl-num" id="ld-min" type="number" min="0" step="90" value="' + st.min + '">')
      ]);
      el.querySelector('#ld-w').addEventListener('change', function (e) { st.win = e.target.value; st.min = null; load(); });
      el.querySelector('#ld-c').addEventListener('change', function (e) { st.scope = e.target.value; st.min = null; load(); });
      el.querySelector('#ld-m').addEventListener('change', function (e) { st.key = e.target.value; sync(); draw(); });
      FB.wireSeg(el, 'ld-pos', function (v) { st.pos = v; sync(); tools(); draw(); });
      el.querySelector('#ld-min').addEventListener('change', function (e) { st.min = Number(e.target.value) || 0; sync(); draw(); });
    }
    function sync() { FB.setQuery({ w: st.win === 'season' ? null : st.win, c: st.scope === 'all' ? null : st.scope, scope: null, m: st.key, pos: st.pos || null, min: st.min, all: null }); }
    function load() {
      var have = ix.scopes[st.win] || {};
      if (!have[st.scope]) st.scope = 'all';
      FB.set('ld-table', FB.loading('lines', 8));
      return FB.labView(st.win, st.scope).then(function (v0) {
        return FB.rolesFor(!!(v0 && v0.idx.role !== undefined)).then(function (R0) { return [v0, R0]; });
      }).then(function (arr) {
        if (!FB.alive(el)) return;
        V = arr[0]; R = arr[1];
        if (!V) { FB.set('ld-table', FB.empty('No board for this view', 'Try another season or set of competitions.')); return; }
        if (st.min === null) st.min = Math.max(90, single() ? V.floor : Math.min(V.floor, 450));
        tools(); sync(); draw();
      });
    }
    function draw() {
      if (!V) return;
      var I = V.idx, key = st.key, base = key.replace(/_adj$/, ''), adj = /_adj$/.test(key);
      var metric = OURS_M.concat(metrics).filter(function (m) { return m.key === base; })[0] || { fmt: '2', label: key };
      var our = oursOf(base), garOn = I.gar90 !== undefined && base !== 'gar90';
      var value = function (r) { var v = I[base] === undefined ? null : r[I[base]]; return isNum(v) ? (adj ? v * (r[I.factor] || 1) : v) : null; };
      /* his role group this season (in this competition for a one-competition view) */
      var roleR = function (r) { return FB.rowRole(R, I.role === undefined ? null : r[I.role], r[I.player_id], single() ? st.scope : null); };
      var grpOf = function (r) { return rolesOn() ? FB.peerGroup(roleR(r)) : null; };
      var inPos = function (r) { if (!st.pos) return true; if (!rolesOn()) return r[I.position] === st.pos; var g = grpOf(r); return !!g && g.id === st.pos; };
      var floorRows = V.rows.filter(function (r) { return (r[I.minutes] || 0) >= st.min && inPos(r) && isNum(value(r)); });
      /* the percentile: against his role group among the rows over max(the group's minimum, the minutes shown); with no
         role payload, against the rows shown (the same position when one is picked) */
      var SORT = {};
      var sortedFor = function (gid) {
        if (SORT[gid]) return SORT[gid];
        var g = gid === '_all' ? null : FB.MSET.groups.filter(function (x) { return x.id === gid; })[0];
        var mn = g ? FB.peerMin(g, st.min) : st.min;
        SORT[gid] = V.rows.filter(function (r) { var gg = grpOf(r); return (gid === '_all' ? inPos(r) : (gg && gg.id === gid)) && (r[I.minutes] || 0) >= mn && isNum(value(r)); }).map(value).sort(function (a, b) { return a - b; });
        SORT[gid].min = mn;
        return SORT[gid];
      };
      var pctOf = function (v, r) {
        var gid = '_all';
        if (rolesOn()) { var g = grpOf(r); if (!g || (r[I.minutes] || 0) < FB.peerMin(g, st.min)) return null; gid = g.id; }
        var sorted = sortedFor(gid);
        if (sorted.length < 5) return null;
        var lo = 0, hi = sorted.length; while (lo < hi) { var mid = (lo + hi) >> 1; if (sorted[mid] < v) lo = mid + 1; else hi = mid; }
        var up = lo; while (up < sorted.length && sorted[up] === v) up++;
        var rank = (lo + 0.5 * (up - lo)) / sorted.length;
        return Math.round(100 * (metric.lower ? 1 - rank : rank));
      };
      var rows = floorRows.slice().sort(function (a, b) { return metric.lower ? value(a) - value(b) : value(b) - value(a); }).slice(0, 100);
      var per = function (r, k) { var v = r[I[k]]; return isNum(v) ? Math.round(v * (r[I.minutes] || 0) / 90) : null; };
      var data = rows.map(function (r, i) {
        var v = value(r);
        var gg = grpOf(r), role = rolesOn() ? roleR(r) : null;
        return { i: i + 1, id: r[I.player_id], name: r[I.name], posName: role ? role + (gg ? '' : ' (no formation start)') : posLabel(r[I.position]), team: r[I.team], tid: r[I.tid], comp: r[I.comp], mix: r[I.mix], pos: r[I.position], age: r[I.age], min: r[I.minutes],
          v: v, raw: r[I[base]], f: r[I.factor], pct: pctOf(v, r), g: per(r, 'goals_90'), a: per(r, 'assists_90'), rt: r[I.rating], g90: I.gar90 !== undefined ? r[I.gar90] : null };
      });
      var lab = (metric.label || key) + (adj ? ' (adj.)' : '');
      var W = (ix.windows || []).filter(function (w) { return w.key === st.win; })[0];
      FB.set('ld-title', esc(lab) + (our ? QK.ours({ model: our.name, about: our.about }) : '') + ': ' + esc(FB.labScopeName(st.scope, ix).toLowerCase()));
      FB.set('ld-ours', our ? QK.oursExplain('<b>' + esc(lab) + '.</b> ' + esc(metric.desc || '') + ' ' +
        (st.win === 'season' ? 'This season’s value-model lines in ' + (single() ? 'this competition' : 'these competitions, added up') : st.win === 'last' ? 'Last season’s lines' : 'The value model’s last 12 months') +
        '; on one scale across leagues, so never league-adjusted. <a href="#/value">Value leaderboard →</a>') : '');
      FB.set('ld-sub', FB.int(floorRows.length) + ' players over ' + st.min + ' minutes · ' + esc(FB.labWindowText(W)) + ' · one row per player' +
        (single() ? '' : ', minutes summed across ' + (st.scope === 'intl' ? 'national-team football' : st.scope === 'club' ? 'club competitions' : 'every competition')) +
        (rolesOn() ? '. Heat and Pctl: percentile v the player\'s role group (CBs, full-backs, DMs and CMs, AMs and wingers, strikers, goalkeepers; the formation role this season) in this view, ' + FB.int(Math.max(450, st.min)) + '+ min (goalkeepers ' + FB.int(Math.max(900, st.min)) + '+); none for a player under it or without a formation start.'
          : '. Percentiles are against the players shown (the same position when one is picked).'));
      var personQ = single() ? { c: st.scope } : st.scope === 'club' ? { scope: 'club' } : st.scope === 'intl' ? { scope: 'intl' } : null;
      QK.leaderboard(el.querySelector('#ld-table'), { dense: true, maxHeight: 640, caption: 'Leaders', columns: [
        { key: 'i', label: '#', num: true },
        { key: 'name', label: 'Player', type: 'entity', sub: 'posName', href: function (r) { return FB.href.player(r.id, personQ); } },
        { key: 'team', label: st.scope === 'intl' ? 'National team' : 'Club', fmt: function (v, r) { return teamA(r.tid, v); } },
        { key: 'mix', label: single() ? 'Competition' : 'Competitions (minutes)', fmt: function (v, r) { return single() ? FB.compLink(st.scope, { short: true }) : '<span class="qk-muted fb-lb-mix">' + esc(v || '') + '</span>'; } },
        { key: 'age', label: 'Age', num: true }, { key: 'min', label: 'Min', num: true },
        { key: 'v', label: lab, type: 'pctl', pctl: 'pct', ours: our ? { name: our.name, about: our.about } : null, tip: rolesOn() ? 'Coloured by percentile against the player\'s role group (blue low, red high)' : 'Coloured by percentile among the players shown (blue low, red high)', fmt: function (v) { return '<b>' + FB.fmtMetric(v, metric.fmt) + '</b>'; } },
        { key: 'raw', label: 'Raw', num: true, tip: 'Before the league adjustment', fmt: function (v) { return adj ? FB.fmtMetric(v, metric.fmt) : '—'; } },
        { key: 'f', label: 'Factor', num: true, tip: 'The scoring factor (pooled model), minutes-weighted over the competitions played', fmt: function (v) { return nn(v, 2); } },
        { key: 'pct', label: 'Pctl', num: true, tip: rolesOn() ? 'Percentile against the player\'s role group in this view' : 'Percentile among the players shown', fmt: function (v) { return isNum(v) ? FB.pctl(v) : '—'; } },
        { key: 'g', label: 'G', num: true }, { key: 'a', label: 'A', num: true }, { key: 'rt', label: 'Rating', num: true, fmt: function (v) { return nn(v, 2); } }
      ].concat(garOn ? [{ key: 'g90', label: 'GAR/90', num: true, ours: oursOf('gar90') || 'Player value model', tip: LO ? LO.tip('gar90', '') : '', fmt: function (v) { return isNum(v) ? FB.signed(v, 2) : '—'; } }] : []), rows: data });
      var top = data.slice(0, 15);
      var box = el.querySelector('#ld-chart');
      if (!top.length) { chartEmpty(box, 'No player clears the filters'); return; }
      box.style.height = '420px';
      QKC.bar(box, {
        horizontal: true, labels: true, labelWidth: 150, fmt: function (x) { return FB.fmtMetric(x, metric.fmt); }, valName: lab,
        cats: top.map(function (r) { return r.name + ' · ' + (r.team || FB.compName(r.comp, true)); }),
        series: [{ name: lab, data: top.map(function (r) { return r.v; }) }],
        colors: top.map(function (r) { return FB.kindColorHex(FB.kindOf(r.comp)); }),
        hrefs: top.map(function (r) { return FB.href.player(r.id, personQ); }), label: lab + ': top 15'
      });
    }
    return load();
  });
}

// ══ #/player/<pid> ════════════════════════════════════════════════════════

var TABS = [['overview', 'Overview'], ['seasons', 'Season by season'], ['matches', 'Matches'], ['shots', 'Profile & shots'], ['transfers', 'Transfers']];

FB.route('player', function (el, p) {
  if ((p.query || {}).view === 'progression' && FB.progression) return FB.progression.tab(el, p);
  var pid = String(p.pid || '');
  var q = FB.merge(p.query || {}, {});
  el.innerHTML = FB.loading('card', 1) + FB.loading('lines', 6);
  return Promise.all([FB.load('people/' + pid + '.json'), FB.clubsIndex()]).then(function (arr) {
    if (!FB.alive(el)) return;
    var doc = arr[0];
    // A duplicate Sofascore id merged into the person (UNIFIED_PAYLOADS 14.4): his page is the person's.
    if (doc && doc.merged_into) { try { history.replaceState(null, '', FB.href.player(doc.merged_into, p.query || null)); } catch (e) { location.hash = FB.href.player(doc.merged_into); return; } FB.render(); return; }
    if (!doc || !doc.id) {
      el.innerHTML = FB.pageHead('Player', 'Player not found', 'No player with id ' + esc(pid) + ' is in the registry.') + FB.empty('Not in the registry', 'Search for a player with / or open the players directory.') +
        '<p class="fb-mt"><a class="qk-btn" href="#/players">Find a player →</a></p>';
      return;
    }
    document.title = doc.name + ' · The Quant Footballer';
    drawPerson(el, doc, q);
  });
});

function drawPerson(el, doc, q) {
  var R = personRows(doc);
  if (q.c && !R.all.some(function (r) { return r.comp === q.c; })) delete q.c;
  var tab = TABS.some(function (t) { return t[0] === q.tab; }) ? q.tab : 'overview';
  var names = doc.comps || {};
  var age = isNum(doc.age) ? doc.age : FB.ageOf(doc.dob);
  var cc = doc.current_club || null, nt = doc.national_team || null;
  var cur = (doc.years || [])[0] || null;
  var curEra = cur ? cur.era : null;

  /* v4 header (QK.playerHeader, rk-player.js): the full-bleed club-colour hero (the kit's cobalt when clubs_index.json
     has no colour yet), the outlined shirt number, the name on two lines, chips; the black strip of five numbers under
     it (this season's totals, every competition: the overview refines them with the filter and the percentiles) and
     "The short version" as the explain strip */
  var untilTxt = '';
  if (doc.until) { var ud = FB.parseDate(doc.until); untilTxt = ud ? FB.MONTHS[ud.getMonth()] + ' ' + ud.getFullYear() : String(doc.until).slice(0, 7); }
  var tags = [];
  if (nt && nt.name) tags.push(nt.tid && FB.clubRow(nt.tid) ? '<a class="qk-tag" href="' + esc(FB.href.club(nt.tid)) + '">' + esc(nt.name) + ' · national team</a>' : QK.tag(nt.name + ' · national team'));
  if (cc && cc.source === 'appearances') tags.push('<span class="qk-tag" data-tip="From the latest club appearance, not a squad list">Club from latest appearance</span>');
  else if (cc && cc.as_of) tags.push('<span class="qk-tag" data-tip="The squad list this club is read from">Squad as of ' + esc(FB.fmtDate(cc.as_of, true)) + '</span>');
  if (!cc || !cc.name) tags.push(QK.tag('No current club on record'));
  if (isNum(doc.mv)) tags.push('<span class="qk-tag" data-tip="Sofascore\'s market value, a reference only">Market value ' + esc(FB.money(doc.mv, doc.mvc)) + '</span>');
  var clubHref = cc && cc.tid && FB.clubRow(cc.tid) ? FB.href.club(cc.tid) : null;
  var cy0 = byYear(R.all).filter(function (y) { return y.era === curEra; })[0] || null;
  var hero = FB.crumb([['#/players', 'Football'], cc && cc.name ? [clubHref, cc.name] : null, doc.name || 'Player'].filter(Boolean)) + QK.playerHeader({
    name: doc.name || 'Player ' + doc.id, number: doc.shirt, pos: posLabel(doc.pos),
    kicker: (curEra || '') + (cur && cur.apps ? ' · ' + cur.apps + ' appearance' + (cur.apps === 1 ? '' : 's') + ' in' : ''),
    team: cc && cc.name ? { name: cc.name, href: clubHref, colour: cc.tid ? FB.clubColour(cc.tid) : null, alt: cc.tid ? FB.clubAlt(cc.tid) : null } : null,
    meta: [age ? age + ' years old' : null, doc.nat || null, doc.height ? doc.height + ' cm' : null, doc.foot ? cap1(doc.foot) + ' foot' : null,
      untilTxt ? 'Contract to ' + untilTxt : null],
    tags: tags, strip: stripTiles(doc, cy0, null), short: shortText(doc, R, null) }) +
    '<p class="fb-cap fb-pl-stripcap" id="pl-tiles-cap">' + esc(cy0 ? 'This season, every competition: ' + FB.int(cy0.min) + ' minutes.' : '') + '</p>';

  var base = '#/player/' + FB.enc(doc.id);
  var keepQs = function (t) { return base + FB.qs({ tab: t === 'overview' ? null : t, scope: q.scope, c: q.c, e: q.e }); };
  var progTab = doc.progression && doc.progression.length && FB.progression ? [[base + FB.qs({ view: 'progression', scope: q.scope === 'intl' ? 'intl' : null }), 'Progression', 'progression']] : [];
  el.innerHTML = hero + FB.subnav(TABS.map(function (t) { return [keepQs(t[0]), t[1], t[0]]; }).concat(progTab), tab, 'Player') +
    (tab === 'shots' || tab === 'transfers' ? '' : '<div id="pl-filter"></div>') + '<div id="pl-body" class="fb-pl-body"></div>' +
    '<p class="fb-cap fb-pl-links">' + linksLine(doc, R) + '</p>';

  function redraw(nq) {
    Object.keys(nq).forEach(function (k) { if (!nq[k]) delete nq[k]; });
    q = FB.merge(nq, { tab: tab === 'overview' ? null : tab });
    FB.setQuery({ scope: q.scope || null, c: q.c || null, e: q.e || null });
    var fbox = el.querySelector('#pl-filter');
    if (fbox) { fbox.innerHTML = filterBar(R, q, names); wireFilter(fbox, q, redraw); }
    var body = el.querySelector('#pl-body');
    if (tab === 'overview') drawOverview(el, body, doc, R, q);
    else if (tab === 'seasons') drawSeasons(el, body, doc, R, q);
    else if (tab === 'matches') drawMatches(el, body, doc, R, q);
    else if (tab === 'shots') drawShots(el, body, doc, R, q);
    else drawTransfers(el, body, doc, R);
    /* the other tabs: the strip's fourth number is value added, as on the overview, once the main competition's
       line is in (the hero's numbers stay this season's, every competition) */
    if (tab !== 'overview' && cy0) {
      var main = R.seasons.filter(function (s) { return s.source === 'live' && compOk(s.comp) && FB.hasFile(s.comp, 'players_live'); }).sort(function (a, b) { return (b.min || 0) - (a.min || 0); });
      var pick = q.c ? main.filter(function (s) { return s.comp === q.c; })[0] : main[0];
      stripInfo(doc, pick ? pick.comp : null, function (info) {
        if (!el.isConnected || !el.querySelector('.qk-strip')) return;
        setStrip(el, stripTiles(doc, cy0, info), esc('This season, every competition: ' + FB.int(cy0.min) + ' minutes.') +
          (info.pc && info.where ? ' ' + esc('The chips under the numbers are percentiles against ' + (info.g ? info.g.name : 'the same position') + ' in ' + info.where + ' (100 = best).') : ''));
      });
    }
  }
  redraw(q);
}
/* The strip's numbers for the tabs without the rail: the player's line in the main competition, its percentiles
   against the same peers as the overview's rail (pctPanel), and value added; nothing is drawn. done(info) only when
   there is a line. */
function stripInfo(doc, slug, done) {
  if (!slug) return;
  FB.compFile(slug, 'players_live').then(function (lv) {
    var players = (lv || {}).players || [];
    var p = players.filter(function (x) { return String(x.player_id) === String(doc.id); })[0];
    if (!p) return null;
    var where = FB.compName(slug) + ' ' + (FB.currentSeason(FB.comp(slug)).season || '');
    var plain = { p: p, where: where, pc: p.pct || {}, val: function (k) { return p[k]; } };
    if (!FB.roles) return plain;
    return FB.rolesFor(players.some(function (x) { return x.role !== undefined; })).then(function (R) {
      if (!R || !R.ok) return plain;
      var g = FB.peerGroup(FB.rowRole(R, p.role, doc.id, slug));
      var valOf = function (r, k) { return k === 'gar90' ? FB.rowGar(R, r.gar90, r.player_id, slug) : r[k]; };
      var val = function (k) { return valOf(p, k); };
      if (!g) return { p: p, where: where, val: val };
      var PP = FB.peerPct({ rows: players, minutes: function (r) { return r.minutes; }, role: function (r) { return FB.rowRole(R, r.role, r.player_id, slug); },
        val: valOf, floor: lv.minutes_floor });
      return { g: g, p: p, where: where, pc: PP.pct(p), val: val };
    });
  }).then(function (info) { if (info) done(info); }, function () {});
}

/* ── v3 plain-English pieces for the player page ─────────────────────────── */

/* A plain line under each metric on the percentile rail (QK.pctRail rows' sub), one per metric of FB.MSET. */
var SUB = {
  gar90: 'Goals added over a replacement-level player, per 90.', rating: 'The average match rating out of 10, by minutes.',
  aerials_won_90: 'Headers won per 90.', aerial_pct: 'Share of headers won.', padj_tkl_int_90: 'Tackles and interceptions, allowing for how much the team has the ball.',
  opp_half_passes_90: 'Passes completed in the opponent’s half, per 90.', pass_pct: 'Share of passes that find a team-mate.', long_ball_pct: 'Share of long passes that find a team-mate.',
  duels_won_90: 'Duels won per 90, on the ground and in the air.', duel_pct: 'Share of duels won.', recoveries_90: 'Loose balls won back per 90.',
  interceptions_90: 'Passes cut out per 90.', clearances_90: 'Clearances per 90: mostly how busy the defence is.', blocks_90: 'Shots and passes blocked per 90.',
  long_balls_90: 'Long passes completed per 90.', prog_carries_90: 'Carries that move the ball well upfield, per 90.', loss_per_100: 'Times the ball is lost per 100 touches (lower is better).',
  shot_creation_90: 'Shots taken plus shots set up, per 90.', npxg_xa_90: 'The quality of chances taken and set up, per 90, penalties out.',
  key_passes_90: 'Passes that lead straight to a shot, per 90.', crosses_90: 'Crosses that reach a team-mate, per 90.', prog_actions_90: 'Carries upfield plus take-ons, per 90.',
  xa_90: 'Chances created, by how likely each was to be scored.', dribbles_90: 'Defenders beaten with the ball, per 90.', hsr_km_90: 'Distance covered at high speed, per 90.',
  passes_90: 'Passes attempted per 90.', carries_90: 'Carries with the ball per 90.', ball_wins_90: 'Tackles won, interceptions and recoveries, per 90.',
  npxg_90: 'How good the player’s own shots are, per 90, penalties out.', big_chances_90: 'Clear-cut chances set up, per 90.', shots_90: 'Shots per 90.',
  ga_90: 'Goals plus assists per 90.', dribble_pct: 'Share of take-ons that work. Noisy.', touches_90: 'Touches of the ball per 90: how involved the player is.',
  finishing: 'Goals beyond the chances, per shot. Mostly luck in one season.', sot_90: 'Shots on target per 90.', xg_per_shot: 'How good the average shot is: high means good positions.',
  xgot_90: 'Shots on target, judged by where they were placed.', goals_90: 'Goals per 90, penalties in.', fouled_90: 'Fouls won per 90.',
  g_minus_xg: 'Goals minus expected goals. Mostly luck in one season.', goals_prevented_90: 'Goals kept out beyond an average keeper, per 90.',
  save_pct: 'Share of shots on target saved.', high_claims_90: 'Crosses caught or punched clear, per 90.', sweeper_90: 'Times off the line to clear up behind the defence, per 90.',
  saves_90: 'Saves per 90: mostly how busy the keeper is.', conceded_90: 'Goals let in per 90: mostly the team in front (lower is better).'
};
/* The type a player's standout metric suggests (compare verdicts). */
var ARCH = {
  gar90: 'The difference-maker', rating: 'The steady performer', aerials_won_90: 'The aerial threat', aerial_pct: 'The aerial threat', padj_tkl_int_90: 'The ball-winner',
  opp_half_passes_90: 'The hub', pass_pct: 'The safe pair of feet', long_ball_pct: 'The long passer', duels_won_90: 'The duel-winner', duel_pct: 'The duel-winner',
  recoveries_90: 'The sweeper-up', interceptions_90: 'The reader of the game', clearances_90: 'The last line', blocks_90: 'The blocker', long_balls_90: 'The long passer',
  prog_carries_90: 'The ball-carrier', loss_per_100: 'The tidy one', shot_creation_90: 'The chance-maker', npxg_xa_90: 'The attacking threat', key_passes_90: 'The creator',
  crosses_90: 'The crosser', prog_actions_90: 'The ball-carrier', xa_90: 'The creator', dribbles_90: 'The dribbler', hsr_km_90: 'The runner', passes_90: 'The metronome',
  carries_90: 'The ball-carrier', ball_wins_90: 'The ball-winner', npxg_90: 'The poacher', big_chances_90: 'The creator', shots_90: 'The volume shooter', ga_90: 'The end product',
  dribble_pct: 'The dribbler', touches_90: 'The hub', finishing: 'The finisher', sot_90: 'The marksman', xg_per_shot: 'The poacher', xgot_90: 'The marksman',
  goals_90: 'The goalscorer', fouled_90: 'The foul-winner', g_minus_xg: 'The finisher', goals_prevented_90: 'The shot-stopper', save_pct: 'The shot-stopper',
  high_claims_90: 'The commanding keeper', sweeper_90: 'The sweeper-keeper', saves_90: 'The busy keeper', conceded_90: 'The well-protected keeper'
};
FB.PLAYER_SUB = SUB; FB.PLAYER_ARCH = ARCH;
function lc1(x) { x = String(x || ''); return /^[A-Z][a-z]/.test(x) ? x.charAt(0).toLowerCase() + x.slice(1) : x; }
function nWord(n) { return n >= 0 && n <= 10 ? ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten'][n] : String(n); }
/* Last season's percentiles in the same peer group (the rail's hollow rings), when the person file carries them:
   current.prev_pct_pos { comp slug: { metric: 0-100 } } and current.prev_peer { comp slug: { sid, season, role, group,
   min } } (6df354ed; written only when last season's role group is this season's). */
function prevPctOf(doc, slug) {
  var c = doc.current || {};
  var pp = c.prev_pct_pos || null, peer = c.prev_peer || null;
  if (pp && slug && pp[slug] && typeof pp[slug] === 'object') { pp = pp[slug]; peer = peer && peer[slug] ? peer[slug] : null; }
  if (!pp || typeof pp !== 'object') return null;
  var ok = Object.keys(pp).some(function (k) { return isNum(pp[k]); });
  return ok ? { pct: pp, peer: peer && typeof peer === 'object' && !Array.isArray(peer) && (peer.season || isNum(peer.min)) ? peer : null } : null;
}

/* "The short version": the season so far, then (once the percentiles are in) what the player is best at against the
   peer group, the weak spot and whether the sample is small. info: { g, pc, where, minutes } or null. */
function shortText(doc, R, info) {
  var sur = FB.surname(doc.name || '') || doc.name;
  var cur = (doc.years || [])[0];
  var t;
  if (!cur || !cur.apps) t = sur + ' has no appearance on record yet this season.';
  else if (doc.pos === 'G') t = sur + ' has played ' + FB.int(cur.min) + ' minutes in ' + cur.apps + ' appearance' + (cur.apps === 1 ? '' : 's') + ' in ' + cur.era + (cur.rows > 1 ? ', across ' + cur.rows + ' competitions' : '') + '.';
  else t = sur + ' has ' + (cur.g || 0) + ' goal' + (cur.g === 1 ? '' : 's') + ' and ' + (cur.a || 0) + ' assist' + (cur.a === 1 ? '' : 's') + ' in ' + cur.apps + ' appearance' + (cur.apps === 1 ? '' : 's') + ' in ' + cur.era +
    (cur.rows > 1 ? ', across ' + cur.rows + ' competitions' : '') + (isNum(cur.xg) && cur.min >= 450 ? ', from chances worth ' + num(cur.xg, 1) + ' expected goals' : '') + '.';
  if (info && info.pc && info.g) {
    var rows = FB.groupKeys(info.g, 'headline').filter(function (k) { return isNum(info.pc[k]); }).map(function (k) { return [k, info.pc[k], (FB.metricInfo(k) || {}).label || k]; });
    var top = rows.filter(function (r) { return r[1] >= 90; }).sort(function (a, b) { return b[1] - a[1]; }).slice(0, 2);
    var low = rows.slice().sort(function (a, b) { return a[1] - b[1]; })[0];
    if (top.length) t += ' In the top ' + Math.max(1, Math.round(100 - Math.min(top[0][1], top[top.length - 1][1]))) + '% of ' + info.g.name + ' in ' + info.where + ' for ' + top.map(function (r) { return lc1(r[2]); }).join(' and ') + '.';
    else if (rows.length) { var avg = rows.reduce(function (s, r) { return s + r[1]; }, 0) / rows.length; t += avg >= 60 ? ' Above the middle of the pack among ' + info.g.name + ' in ' + info.where + ' on most of the numbers that matter.' : avg >= 40 ? ' Around the middle of the pack among ' + info.g.name + ' in ' + info.where + '.' : ' Below the middle of the pack among ' + info.g.name + ' in ' + info.where + ' so far.'; }
    if (low && low[1] <= 30 && !(top[0] && top[0][0] === low[0])) t += ' The weak spot: ' + lc1(low[2]) + ', in the ' + FB.ordinal(low[1]) + ' percentile.';
    if (isNum(info.minutes) && info.minutes < info.g.small) t += ' Under ' + FB.int(info.g.small) + ' minutes is a small sample, so read it lightly.';
  }
  return t;
}

function linksLine(doc, R) {
  var best = R.seasons.filter(function (s) { return s.source === 'live' && compOk(s.comp); }).sort(function (a, b) { return (b.min || 0) - (a.min || 0); })[0];
  var bits = [];
  if (best) {
    bits.push('<a href="#/compare/players/' + esc(best.comp) + ':' + esc(doc.id) + '">Compare this player →</a>');
    bits.push('<a href="#/lab/' + esc(best.comp) + '/' + esc(doc.pos === 'G' ? 'G' : (doc.pos || 'M')) + '">Player lab →</a>');
  }
  if (doc.progression && doc.progression.length) bits.push('<a href="#/compare/progression/' + esc(doc.id) + '">Compare progression →</a>');
  bits.push('<a href="#/value' + FB.qs({ q: doc.name }) + '">Player value →</a>');
  bits.push('<a href="#/value/simulator' + FB.qs({ p: doc.id }) + '">Transfer simulator →</a>');
  bits.push('<a href="#/model/glossary">Glossary →</a>');
  return bits.join(' &nbsp;·&nbsp; ');
}

function filterBar(R, q, names) {
  var all = R.all;
  var counts = { all: all.length, club: all.filter(function (r) { return r.scope === 'club'; }).length, intl: all.filter(function (r) { return r.scope === 'international'; }).length };
  var seen = {};
  all.forEach(function (r) { if (r.comp && !seen[r.comp]) seen[r.comp] = { slug: r.comp, name: r.cname, kind: r.kind }; });
  var comps = Object.keys(seen).map(function (k) { return seen[k]; }).sort(function (a, b) { return (KIND_ORDER[a.kind] - KIND_ORDER[b.kind]) || String(a.name).localeCompare(String(b.name)); });
  var eras = [];
  all.forEach(function (r) { if (r.era && eras.indexOf(r.era) < 0) eras.push(r.era); });
  eras.sort(function (a, b) { return eraKey(b) - eraKey(a); });
  var chip = function (v, label, n) { return '<button class="qk-chip" type="button" data-scope="' + v + '" aria-pressed="' + ((q.scope || '') === v) + '">' + esc(label) + ' <span class="n">' + n + '</span></button>'; };
  return '<div class="fb-pl-filter">' +
    '<div class="qk-chips" role="group" aria-label="Scope">' + chip('', 'All', counts.all) + chip('club', 'Club', counts.club) + chip('intl', 'International', counts.intl) + '</div>' +
    FB.select('pl-fc', [['', 'Every competition']].concat(comps.map(function (c) { return [c.slug, c.name]; })), q.c || '', 'Competition', 'fb-pl-wide') +
    FB.select('pl-fe', [['', 'Every season']].concat(eras.map(function (e) { return [e, e]; })), q.e || '', 'Season') +
    (q.c || q.e || q.scope ? '<button type="button" class="qk-btn" data-reset="1">Clear</button>' : '') +
    '</div>';
}
function wireFilter(box, q, onChange) {
  Array.prototype.forEach.call(box.querySelectorAll('[data-scope]'), function (b) { b.addEventListener('click', function () { onChange(FB.merge(q, { scope: b.getAttribute('data-scope') || null })); }); });
  box.querySelector('#pl-fc').addEventListener('change', function (e) { onChange(FB.merge(q, { c: e.target.value || null })); });
  box.querySelector('#pl-fe').addEventListener('change', function (e) { onChange(FB.merge(q, { e: e.target.value || null })); });
  var r = box.querySelector('[data-reset]');
  if (r) r.addEventListener('click', function () { onChange({}); });
}

/* Season x competition rows grouped by season (newest first), with totals. */
function byYear(rows) {
  var years = {};
  rows.forEach(function (r) {
    if (!r.era) return;
    var y = years[r.era] || (years[r.era] = { era: r.era, rows: [] });
    y.rows.push(r);
  });
  return Object.keys(years).map(function (k) {
    var y = years[k];
    var rr = y.rows, intl = rr.filter(function (r) { return r.scope === 'international'; });
    var xgRows = rr.filter(function (r) { return isNum(r.xg); });
    return {
      era: y.era, rows: rr.sort(function (a, b) { return (KIND_ORDER[a.kind] - KIND_ORDER[b.kind]) || (b.min || 0) - (a.min || 0); }),
      apps: sum(rr, 'apps'), starts: sum(rr, 'starts'), min: sum(rr, 'min'), g: sum(rr, 'g'), a: sum(rr, 'a'),
      xg: xgRows.length ? sum(xgRows, 'xg') : null, xa: rr.some(function (r) { return isNum(r.xa); }) ? sum(rr.filter(function (r) { return isNum(r.xa); }), 'xa') : null,
      /* goals and minutes in the rows that carry xG, so goals against xG compares the same matches (ACCURACY_AUDIT 4) */
      xg_g: xgRows.length ? sum(xgRows, 'g') : null, xg_min: xgRows.length ? sum(xgRows, 'min') : null,
      rt: wavg(rr, 'rt'), intlMin: sum(intl, 'min'), clubMin: sum(rr, 'min') - sum(intl, 'min'),
      partial: rr.some(function (r) { return r.coverage === 'partial' || r.coverage === 'none'; }), totals: rr.some(function (r) { return r.coverage === 'totals'; })
    };
  }).sort(function (a, b) { return eraKey(b.era) - eraKey(a.era); });
}

// ── overview (kit v4 "Broadcast", the Rink player page's pattern: MIGRATION_V4.md step 4) ─────────────

/* The black strip of five numbers under the hero (QK.playerHeader strip). cy: the season's totals in the filter
   (byYear); info: the main competition's line once the percentiles are in (pctPanel on the overview, stripInfo on
   the other tabs), else null. Until it arrives the fourth number is goals and assists per 90 (keepers: starts and
   minutes) rather than value added, which needs the competition line. */
function stripTiles(doc, cy, info) {
  if (!cy) return [];
  var pc = (info && info.pc) || {}, p = (info && info.p) || null, gk = doc.pos === 'G';
  var v = function (k) { return info && info.val ? info.val(k) : (p ? p[k] : null); };
  var t = [FB.kpi('Appearances', FB.int(cy.apps), { sub: (cy.starts ? cy.starts + ' starts · ' : '') + FB.int(cy.min) + ' minutes', text: false })];
  if (gk && p) {
    t.push(FB.kpi('Goals prevented', isNum(v('goals_prevented_90')) ? FB.signed(v('goals_prevented_90'), 2) : '—', { pctl: pc.goals_prevented_90, unit: 'per 90', signal: true, sub: 'beyond an average keeper, same shots', text: false, tip: 'Expected goals on target faced minus goals let in, per 90' }));
    t.push(FB.kpi('Save %', isNum(v('save_pct')) ? num(v('save_pct'), 1) + '%' : '—', { pctl: pc.save_pct, sub: 'shots on target saved', text: false }));
    t.push(FB.kpi('High claims', isNum(v('high_claims_90')) ? num(v('high_claims_90'), 2) : '—', { pctl: pc.high_claims_90, unit: 'per 90', sub: 'crosses caught or punched', text: false }));
  } else if (gk) {
    t.push(FB.kpi('Starts', FB.int(cy.starts || 0), { sub: 'of ' + FB.int(cy.apps) + ' appearances', text: false }));
    t.push(FB.kpi('Minutes', FB.int(cy.min), { sub: cy.apps ? FB.int(cy.min / cy.apps) + ' an appearance' : '', text: false }));
  } else {
    t.push(FB.kpi('Goals', FB.int(cy.g), { pctl: pc.goals_90, sub: isNum(cy.xg) ? 'from ' + num(cy.xg, 1) + ' expected goals' : '', text: false }));
    t.push(FB.kpi('Assists', FB.int(cy.a), { sub: isNum(cy.xa) ? 'from ' + num(cy.xa, 1) + ' expected assists' : '', text: false }));
    if (p) t.push(FB.kpi('Value added', isNum(v('gar90')) ? FB.signed(v('gar90'), 2) : '—', { pctl: pc.gar90, unit: 'per 90', signal: true, sub: 'goals over a replacement-level player', text: false, tip: 'Goals above replacement per 90 minutes in the main competition, from our player value model' }));
    else t.push(FB.kpi('Goals + assists', nn(per90((cy.g || 0) + (cy.a || 0), cy.min), 2), { unit: 'per 90', sub: 'every competition in the filter', text: false }));
  }
  t.push(FB.kpi('Rating', nn(cy.rt, 2), { pctl: pc.rating, sub: 'out of 10, minutes-weighted', text: false }));
  return t;
}
/* Swap the hero's strip in place (the filter changed, or the percentiles arrived) and its caption (HTML). */
function setStrip(el, list, cap) {
  var html = list.length ? QK.statStrip(list) : '';
  var s = el.querySelector('.qk-strip');
  if (s) { if (html) s.outerHTML = html; else s.parentNode.removeChild(s); }
  else if (html) { var ph = el.querySelector('.qk-ph'); if (ph) ph.insertAdjacentHTML('afterend', html); }
  var c = el.querySelector('#pl-tiles-cap');
  if (c) c.innerHTML = cap || '';
}

function drawOverview(el, body, doc, R, q) {
  var keep = keepQ(q);
  var rows = R.all.filter(keep);
  var filtered = !!(q.scope || q.c || q.e);
  var Y = byYear(rows);
  var curEra = q.e || ((doc.years || [])[0] || {}).era || (Y[0] || {}).era;
  var cy = Y.filter(function (y) { return y.era === curEra; })[0] || null;
  var label = filterLabel(q, doc.comps);
  var partial = cy && cy.partial ? ' <span class="fb-cov partial" data-tip="At least one competition this season is a lower bound: line-ups are missing for some of the team\'s matches.">Partial</span>' : '';
  body.innerHTML =
    /* 1. the LED meters with "How sure are we?" under them (7), beside the tale of the tape against the closest match (5) */
    '<section class="qk-section fb-pl-sec1"><div class="qk-g75"><div class="fb-pl-left"><div id="pl-pcard">' + QK.skeleton('lines', 8) + '</div><div id="pl-sure"></div></div>' +
      '<div class="fb-pl-stack"><div id="pl-tape-h"></div><div class="qk-chips fb-pl-pick" id="pl-tape-pick" role="group" aria-label="Compare with" hidden></div>' +
        '<div id="pl-tape">' + QK.skeleton('lines', 6) + '</div><div id="pl-verd"></div><div id="pl-sure-r"></div><div id="pl-type-r"></div></div></div></section>' +
    /* 2. what to watch (the scoreboard bug) beside the last game (box score and the xG race) */
    '<section class="qk-section" id="pl-nl" hidden><div class="qk-g2" id="pl-nl-g"></div></section>' +
    /* 3. the game log */
    '<section class="qk-section" id="pl-log-sec" hidden><div id="pl-log-h"></div><article class="qk-card"><div class="qk-card-body flush" id="pl-glog"></div></article></section>' +
    /* 4. game by game and their type */
    '<section class="qk-section"><div class="qk-gside"><div>' +
      FB.card('Game by game', '<span id="pl-gbg-sub">Goals and assists in every match this season.</span>', FB.chartBox('pl-gbg', 260, 'Goals and assists in every match this season'), { id: 'pl-gbgcard' }) +
      '</div><div id="pl-type"></div></div></section>' +
    '<div id="pl-move" class="fb-pl-move"></div>' +
    '<section class="qk-section">' + QK.sectionHead({ kicker: 'More on the player', title: 'Peers, seasons and value', sub: 'Where the player sits in the peer group, every season in the data, and what the player is worth to a team.' }) +
    /* a goalkeeper's own goals and xG are zeros, and the people files carry no goals conceded or xGOT faced by
       season, so a keeper's page drops the goals-against-xG card (its shot-stopping is in the rail and the lab) */
    '<div class="qk-grid"><div class="' + (doc.pos === 'G' ? 'qk-span-12' : 'qk-span-6') + '">' +
        FB.card('Among peers', '<span id="pl-dist-sub">The peer group in the player\'s main competition this season, with the player and the median marked.</span>',
          '<div id="pl-dist-seg" class="fb-pl-distseg"></div>' + FB.chartBox('pl-dist', 250, 'Among peers'), { id: 'pl-distcard' }) + '</div>' +
      (doc.pos === 'G' ? '' : '<div class="qk-span-6">' + FB.card('Goals against xG', '<span id="pl-xg-sub">Per season, where the stores carry xG (archive seasons are totals without xG).</span>', FB.chartBox('pl-xg', 250, 'Goals and xG by season') +
        QK.explain('<b>What’s that number?</b> xG is how many goals an average finisher would score from the same shots. Well above it is great finishing or good luck; one season rarely tells the two apart.')) + '</div>') + '</div>' +
    FB.grid(
      FB.card('Goals and assists by season', 'Stacked by competition kind' + (filtered ? ', in the filter' : '') + '.', FB.chartBox('pl-ga', 280, 'Goals and assists by season'), { span: 4 }) +
      FB.card('Minutes by season', 'Where the minutes came from: league, continental, cups, international.', FB.chartBox('pl-min', 280, 'Minutes by season'), { span: 4 }) +
      FB.card('Rating by season', 'Minutes-weighted Sofascore rating across the season\'s competitions.', FB.chartBox('pl-rt', 280, 'Rating by season'), { span: 4 }), 'fb-mt'
    ) +
    '<div class="fb-mt">' + FB.card('Season by season', 'Every competition played, summed per season' + (doc.frame === 'calendar' ? ' (calendar years, as the player\'s club football runs)' : ' (July to June; international matches count in the season they are played in)') +
      '. Open a season for its competitions. <a href="' + esc('#/player/' + FB.enc(doc.id) + FB.qs({ tab: 'seasons', scope: q.scope, c: q.c, e: q.e })) + '">Full career table →</a>', '<div id="pl-years"></div>', { flush: true }) + '</div>' +
    '<div class="fb-mt">' + FB.card('Value added', 'Our player value model: goals above a replacement-level player in the same role, last 12 months of club football. <a href="#/value">How it works →</a>', '<div id="pl-value">' + FB.loading('lines', 4) + '</div>') + '</div></section>';

  /* the hero's strip: the season's totals in the filter; the percentile chips arrive with the main competition's line */
  function tiles(info) {
    if (!cy) { setStrip(el, [], esc('No season in the filter: clear the filters to see the full career.')); return; }
    var cap = esc('Totals: ' + label + (curEra ? ', ' + curEra : '') + '.') + partial +
      (info && info.pc && info.where ? ' ' + esc('The chips under the numbers are percentiles against ' + (info.g ? info.g.name : 'the same position') + ' in ' + info.where + ' (100 = best).') : '');
    setStrip(el, stripTiles(doc, cy, info), cap);
  }
  tiles(null);
  yearsTable(body.querySelector('#pl-years'), Y, doc, 2);
  seasonCharts(body, Y);
  gameByGame(body, doc, R, curEra, q);
  gameLog(body, doc, R, curEra, q);
  nextLast(body, doc, R);
  /* value/players.json and value/lines.json are about 2 MB: they load only when the card is near the screen */
  whenVisible(body.querySelector('#pl-value'), function () { drawValue(body, doc); });
  /* who moves next (value.js, MOVES_VIEWS.md 4): the card draws only when the club's file has a movement block and the
     payload has a row for the player; otherwise the slot stays empty. Loaded when it nears the screen. */
  var mv = body.querySelector('#pl-move'), cc = doc.current_club || {};
  if (mv && FB.movementCard && cc.tid && !((FB.clubRow(cc.tid) || {}).national)) whenVisible(body.querySelector('#pl-value'), function () { FB.movementCard(mv, doc.id, { tid: cc.tid, until: doc.until }); });
  var main = R.seasons.filter(function (s) { return s.source === 'live' && compOk(s.comp) && FB.hasFile(s.comp, 'players_live'); }).sort(function (a, b) { return (b.min || 0) - (a.min || 0); });
  var pick = q.c ? main.filter(function (s) { return s.comp === q.c; })[0] : main[0];
  pctPanel(body, doc, pick ? pick.comp : null, function (info) {
    if (!FB.alive(body)) return;
    tiles(info);
    var sv = el.querySelector('.qk-short p');
    if (sv && info) sv.textContent = shortText(doc, R, info);
    if (info && info.g && info.PP) similarOf(info, 3);
    var tape = !!(info && info.sim && info.sim.length);
    sureBox(body, doc, info, tape);
    typeCard(body, doc, info, tape ? 'pl-type' : 'pl-type-r');
    if (tape) tapeSim(body, doc, info);
    else ['pl-tape-h', 'pl-tape', 'pl-verd'].forEach(function (id) { var n = body.querySelector('#' + id); if (n) n.innerHTML = ''; });
  });
}

/* How sure are we: when this player's numbers settle at this playing time (the spec's m50 minutes, METRICS_SPEC).
   With a tale of the tape on the right, it is the explain strip under the meters; otherwise the explained card on
   the right (as rk-player.js does for goalies). */
function sureBox(body, doc, info, strip) {
  var cur = (doc.years || [])[0] || {};
  var mins = info && isNum(info.minutes) ? info.minutes : cur.min || 0;
  var g = info && info.g;
  var small = g ? mins < g.small : mins < 900;
  var where = info && info.where ? ' in ' + info.where : ' this season';
  var head = !mins ? 'No minutes yet this season' : small ? FB.int(mins) + ' minutes' + where + ' is a small sample' : FB.int(mins) + ' minutes' + where + ': the picture is settling';
  var settle = '';
  if (g) {
    var list = g.headline.filter(function (x) { return isNum(x[1]); }).slice(0, 3);
    var bits = list.map(function (x) { return '<b>' + esc(lc1((FB.metricInfo(x[0]) || {}).label || x[0])) + '</b> after about ' + FB.int(x[1]) + ' minutes'; });
    if (bits.length) settle = 'For ' + esc(g.name) + ', ' + bits.join(', ').replace(/, ([^,]*)$/, ', and $1') + ' (when a season’s number is half signal, half noise).';
  }
  var gk = doc.pos === 'G';
  var line = gk ? 'Keeper numbers swing more than any other position: shot-stopping takes a few seasons to separate skill from luck.'
    : (small ? 'Rates swing a lot over a few hundred minutes.' : '');
  var prev = info && info.prev ? 'The ▼ marks last season in the same peer group: rows that sit on it are the steady part of the profile; the ones far from it are the ones to watch.' : '';
  var left = body.querySelector('#pl-sure'), right = body.querySelector('#pl-sure-r');
  if (strip) {
    if (left) left.innerHTML = QK.explain('<b>How sure are we?</b> ' + esc(head) + '.' + (line ? ' ' + esc(line) : '') + (settle ? ' ' + settle : '') + (prev ? ' ' + esc(prev) : ''), { cls: 'fb-pl-settle' });
    if (right) right.innerHTML = '';
    return;
  }
  if (left) left.innerHTML = '';
  if (right) right.innerHTML = '<article class="qk-card cream"><div class="qk-card-body"><div class="qk-kicker">How sure are we?</div><h3 style="margin:8px 0 6px">' + esc(head) + '</h3>' +
    (line || prev ? '<p style="margin:0;color:var(--ink-2);font-size:15px">' + esc([line, prev].filter(Boolean).join(' ')) + '</p>' : '') + (settle ? QK.note(settle) : '') + '</div></article>';
}

/* Game by game: goals and assists in every match of the season in the filter (the person file's appearances), the
   best one annotated. */
function gameByGame(body, doc, R, era, q) {
  var box = body.querySelector('#pl-gbg'), card = body.querySelector('#pl-gbgcard');
  if (!box) return;
  var keep = keepQ(FB.merge(q || {}, { e: null }));
  var all = R.apps.filter(function (r) { return r.era === era && keep(r); });
  var list = all.filter(function (r) { return (r.min || 0) > 0; }).sort(function (a, b) { return String(a.date).localeCompare(String(b.date)); });
  if (list.length > 24) list = list.slice(-24);
  if (!list.length) { if (card) card.hidden = true; return; }
  var gk = doc.pos === 'G';
  var lab = filterLabel(FB.merge(q || {}, { e: null }), doc.comps);
  FB.set('pl-gbg-sub', (gk ? 'Rating in every match' : 'Goals and assists in every match') + ' of ' + esc(era) + (all.length > 24 ? ' (the last 24)' : '') + ', ' + esc(lab === 'All competitions' ? 'every competition' : lab) + '.');
  var cats = list.map(function (r) { var d = FB.parseDate(r.date); return (d ? d.getDate() + ' ' + FB.MONTHS[d.getMonth()] : '') + '\n' + (r.home ? 'v ' : '@ ') + String(r.opp || '').split(' ').slice(0, 2).join(' '); });
  var best = -1, bi = -1;
  list.forEach(function (r, i) { var v = gk ? (r.rt || 0) : (r.g || 0) + (r.a || 0); if (v > best) { best = v; bi = i; } });
  QKC.mount(box, function (T) {
    var xa = QKC.axis(T, { type: 'category', data: cats, split: false, line: true });
    xa.axisLabel.interval = list.length > 12 ? 'auto' : 0; xa.axisLabel.lineHeight = 14; xa.axisLabel.fontSize = list.length > 8 ? 10 : 11.5;
    var ya = QKC.axis(T, gk ? { min: 5, max: 10, fmt: function (v) { return v.toFixed(0); } } : { min: 0, max: Math.max(3, best + 1), interval: 1 });
    var gB = 26 + QKC.nameAxis(xa, 'Match (date and opponent)', 'bottom'), gT = 26 + QKC.nameAxis(ya, gk ? 'Match rating (out of 10)' : 'Goals and assists in the match', 'side');
    xa.nameGap = 40;
    var tip = QKC.tooltip(T, { trigger: 'axis', axisPointer: { type: 'shadow', shadowStyle: { color: 'rgba(125,147,255,.10)' } }, formatter: function (ps) {
      var r = list[ps[0].dataIndex];
      return '<b>' + esc((r.home ? 'v ' : 'at ') + r.opp) + ' · ' + esc(r.res || '') + '</b><div style="color:' + T.ink3 + '">' + esc(compName(r.comp, doc.comps)) + ' · ' + esc(FB.fmtDate(r.date)) + '</div>' +
        (gk ? '' : QKC.tipRow(T.coral, 'Goals', r.g || 0) + QKC.tipRow(T.sky, 'Assists', r.a || 0)) + QKC.tipRow(T.ink3, 'Minutes', r.min) +
        (isNum(r.xg) ? QKC.tipRow(T.ink3, 'Expected goals', num(r.xg, 2)) : '') + (isNum(r.rt) ? QKC.tipRow(T.ink3, 'Rating', num(r.rt, 1)) : '');
    } });
    var grid = { left: 8, right: 12, top: gT, bottom: gB, containLabel: true };
    if (gk) return { grid: grid, xAxis: xa, yAxis: ya, tooltip: tip,
      series: [{ type: 'bar', name: 'Rating', barMaxWidth: 30, data: list.map(function (r, i) {
        var o = { value: isNum(r.rt) ? r.rt : null, itemStyle: { color: T.model } };
        if (i === bi && best >= 7.5) o.label = FB.merge(QKC.annot(T), { show: true, position: 'top', formatter: 'Best: ' + num(best, 1) });
        return o; }) }] };
    return { grid: grid, xAxis: xa, yAxis: ya, tooltip: tip,
      legend: { top: 0, right: 0, itemWidth: 12, itemHeight: 12, icon: 'rect', textStyle: { color: T.ink2, fontFamily: T.fontCond, fontSize: 13, fontWeight: 700 } },
      series: [{ type: 'bar', name: 'Goals', stack: 'p', barMaxWidth: 30, data: list.map(function (r) { return r.g || 0; }), itemStyle: { color: T.coral, borderColor: T.s1, borderWidth: 1 } },
        { type: 'bar', name: 'Assists', stack: 'p', barMaxWidth: 30, data: list.map(function (r, i) {
          var o = { value: r.a || 0, itemStyle: { color: T.sky, borderColor: T.s1, borderWidth: 1 } };
          if (i === bi && best >= 2) o.label = FB.merge(QKC.annot(T), { show: true, position: 'top', formatter: best + ' goal involvements' });
          return o; }) }] };
  }, { label: gk ? 'Rating in every match this season' : 'Goals and assists in every match this season' });
}

/* The game log: every game of the season in the filter, newest first, the best night highlighted (tr.hl). */
function gameLog(body, doc, R, era, q) {
  var sec = body.querySelector('#pl-log-sec');
  if (!sec) return;
  var keep = keepQ(FB.merge(q || {}, { e: null }));
  var list = R.apps.filter(function (r) { return r.era === era && keep(r) && (r.min || 0) > 0; }).sort(function (a, b) { return String(b.date).localeCompare(String(a.date)); });
  if (!list.length) { sec.hidden = true; return; }
  var gk = doc.pos === 'G', names = doc.comps || {};
  var score = function (r) { return gk ? (isNum(r.rt) ? r.rt : 0) : (r.g || 0) + (r.a || 0) + (isNum(r.rt) ? r.rt / 100 : 0); };
  var bi = -1, bs = -1;
  list.forEach(function (r, i) { var s = score(r); if (s > bs) { bs = s; bi = i; } });
  var b = list[bi];
  var involve = b ? (b.g || 0) + (b.a || 0) : 0;
  var plural = function (n, w) { return n + ' ' + w + (n === 1 ? '' : 's'); };
  var bestTxt = !b ? '' : gk ? (isNum(b.rt) && b.rt >= 7 ? 'A ' + num(b.rt, 1) + ' rating ' + (b.home ? 'against ' : 'at ') + b.opp + ' is the best night so far (highlighted).' : '')
    : involve > 0 ? [b.g ? plural(b.g, 'goal') : '', b.a ? plural(b.a, 'assist') : ''].filter(Boolean).join(' and ').replace(/^./, function (c) { return c.toUpperCase(); }) + ' ' + (b.home ? 'against ' : 'at ') + b.opp + ' (' + compShort(b.comp, names) + ') is the best night so far (highlighted).' : '';
  var cur = ((doc.years || [])[0] || {}).era;
  FB.set('pl-log-h', QK.sectionHead({ kicker: 'Game log', title: era && era !== cur ? 'Every game in ' + era : 'Every game this season', sub: esc(bestTxt || (list.length + ' appearances, newest first.')) + ' <a href="' + esc('#/player/' + FB.enc(doc.id) + FB.qs({ tab: 'matches', scope: q.scope, c: q.c, e: q.e })) + '">Full match log →</a>', html: true }));
  var hl = bestTxt ? bi : -1;
  var head = '<tr><th>Date</th><th>Competition</th><th>Opponent</th><th>Result</th><th class="num">Min</th>' + (gk ? '' : '<th class="num">G</th><th class="num">A</th><th class="num" data-tip="Expected goals from the player’s own shots">xG</th>') + '<th class="num">Rating</th></tr>';
  var res = function (r) { var t = '<span class="fb-pl-res ' + resClass(r.res) + '">' + esc(r.res || '—') + '</span>'; return hasMatchPage(r) ? '<a href="' + esc(FB.href.match(r.comp, r.gid)) + '" title="Match centre">' + t + '</a>' : t; };
  FB.set('pl-glog', '<div class="qk-table-wrap"><table class="qk-table dense fb-pl-glog"><caption class="qk-sr">Every game this season</caption><thead>' + head + '</thead><tbody>' + list.map(function (r, i) {
    return '<tr' + (i === hl ? ' class="hl"' : '') + '><td class="fb-num">' + esc(FB.fmtDate(r.date, { weekday: false })) + '</td><td><span class="fb-comp"><i style="--k:' + FB.kindColor(r.kind) + '"></i>' + esc(compShort(r.comp, names)) + '</span></td>' +
      '<td><span class="fb-pl-opp"><span class="qk-muted">' + (r.home ? 'v' : '@') + '</span>' + teamA(r.opp_tid, r.opp) + '</span></td><td>' + res(r) + '</td>' +
      '<td class="num">' + int(r.min || 0) + (r.start ? '' : ' <span class="fb-pl-dim" title="Came off the bench">sub</span>') + '</td>' +
      (gk ? '' : '<td class="num">' + (r.g || 0) + '</td><td class="num">' + (r.a || 0) + '</td><td class="num">' + nn(r.xg, 2) + '</td>') +
      '<td class="num">' + (isNum(r.rt) ? '<b>' + num(r.rt, 1) + '</b>' : '—') + '</td></tr>';
  }).join('') + '</tbody></table></div>');
  sec.hidden = false;
}

/* What to watch: the next match (the current club's file) as the scoreboard bug with how the sides match up (the
   competition's strength and table); the last game the player played (the person file), titled with the score home
   first, with the box score and the expected-goals race when the match has a detail file, else its game card. */
function nextLast(body, doc, R) {
  var sec = body.querySelector('#pl-nl'), box = body.querySelector('#pl-nl-g');
  if (!box) return;
  var cc = doc.current_club || {};
  var gk = doc.pos === 'G';
  var last = R.apps.filter(function (r) { return (r.min || 0) > 0; }).sort(function (a, b) { return String(b.date).localeCompare(String(a.date)); })[0] || null;
  var club = cc.tid && FB.clubRow(cc.tid) && !(FB.clubRow(cc.tid) || {}).national ? FB.load('clubs/' + cc.tid + '.json') : Promise.resolve(null);
  club.then(function (cd) {
    if (!FB.alive(box)) return;
    var now = Date.now();
    var nx = ((cd || {}).matches || []).filter(function (x) { var t = FB.parseDate(x.date); return x.status !== 'finished' && x.status !== 'postponed' && x.status !== 'cancelled' && t && t.getTime() > now - 2 * 3600e3; })
      .sort(function (a, b) { return String(a.date).localeCompare(String(b.date)); })[0];
    var h = '', nf = null;
    if (nx) {
      var home = nx.home === 1 || nx.home === true;
      nf = { id: nx.id, date: nx.date, comp: nx.comp, status: nx.status === 'live' ? 'live' : 'scheduled', round: nx.round, stage: nx.stage, model: nx.model,
        home: home ? cc.name : nx.opp, away: home ? nx.opp : cc.name, home_id: home ? cc.tid : nx.opp_tid, away_id: home ? nx.opp_tid : cc.tid };
      var rel = FB.relDay(nx.date), ev = new Date().getHours() >= 15;
      h += '<div>' + QK.sectionHead({ kicker: nf.status === 'live' ? 'Live now' : rel === 'Today' ? 'What to watch ' + (ev ? 'tonight' : 'today') : 'Next up', title: nf.home + ' v ' + nf.away }) +
        '<div id="pl-next">' + nextCard(nf, null) + '</div><p class="fb-cap"><a href="' + esc(FB.href.match(nx.comp, nx.id)) + '">The match centre →</a></p></div>';
    }
    var lf = null;
    if (last) {
      var hm = last.home === 1 || last.home === true;
      var sc = /(\d+)\D+(\d+)/.exec(String(last.res || ''));
      var gf = sc ? Number(sc[1]) : null, ga = sc ? Number(sc[2]) : null;
      var team = ((doc.teams || {})[String(last.tid)] || {}).name || FB.clubName(last.tid) || '';
      lf = { id: last.gid, date: last.date, comp: last.comp, status: 'finished', home: hm ? team : last.opp, away: hm ? last.opp : team,
        home_id: hm ? last.tid : last.opp_tid, away_id: hm ? last.opp_tid : last.tid, hs: hm ? gf : ga, as: hm ? ga : gf, detail: hasMatchPage(last) };
      var bits = [FB.int(last.min) + ' minutes'];
      if (!gk) bits.push((last.g || 0) + ' goal' + (last.g === 1 ? '' : 's') + ', ' + (last.a || 0) + ' assist' + (last.a === 1 ? '' : 's'));
      if (isNum(last.xg) && !gk) bits.push(num(last.xg, 2) + ' expected goals');
      if (isNum(last.rt)) bits.push('rating ' + num(last.rt, 1));
      var ttl = isNum(lf.hs) && isNum(lf.as) ? lf.home + ' ' + lf.hs + '–' + lf.as + ' ' + lf.away : (hm ? 'v ' : 'at ') + last.opp;
      h += '<div>' + QK.sectionHead({ kicker: 'Last game', title: ttl, sub: esc(compName(last.comp, doc.comps) + ' · ' + FB.fmtDate(last.date)), html: true }) +
        '<article class="qk-card"><div class="qk-card-body"><div id="pl-box">' + (lf.home && lf.away ? FB.matchCard(lf, last.comp, { league: compName(last.comp, doc.comps) + ' · ' + FB.fmtDate(last.date) }) : '') + '</div>' +
        '<p class="fb-pl-line"><b>' + esc(FB.surname(doc.name)) + ':</b> ' + esc(bits.join(' · ')) + '.' + (last.start === 0 ? ' Came off the bench.' : '') + '</p>' +
        '<div id="pl-race"></div></div></article></div>';
    }
    box.innerHTML = h;
    if (sec) sec.hidden = !h;
    if (nf) nextFactors(body, nf);
    if (lf && lf.detail) lastDetail(body, doc, last, lf);
  });
}
/* The next match as the scoreboard bug (QK.previewCard layout 'bug', home first), with records and factors when
   the competition's table and strength are in (side: { strength, table }). */
function nextCard(f, side) {
  var g = FB.heroGame(FB.toGame(f, f.comp));
  g.href = null;
  var fx = [];
  if (side) {
    var rows = {}, st = {};
    (((side.table || {}).standings) || []).forEach(function (r) { rows[r.team] = r; });
    (((side.strength || {}).rows) || []).forEach(function (r) { st[r.team] = r; });
    var rec = function (n) { var r = rows[n]; return r && isNum(r.w) ? r.w + '–' + r.d + '–' + r.l + (isNum(r.pts) ? ' · ' + r.pts + ' pts' : '') : ''; };
    g.home.record = rec(f.home); g.away.record = rec(f.away);
    var h = st[f.home] || {}, a = st[f.away] || {};
    var add = function (label, av, bv, fm, low) { if (isNum(av) && isNum(bv)) fx.push({ label: label, a: fm(av), b: fm(bv), better: Math.abs(av - bv) < 1e-9 ? null : ((av > bv) !== !!low ? 'a' : 'b') }); };
    add('Our rating (points a game)', a.strength_ppg, h.strength_ppg, function (v) { return num(v, 2); });
    add('Points a game', a.ppg, h.ppg, function (v) { return num(v, 2); });
    add('Elo', a.elo, h.elo, function (v) { return num(v, 0); });
  }
  return QK.previewCard(g, { layout: 'bug', homeFirst: true, vs: 'v', noun: 'match', nick: function (t) { return t.name; }, factors: fx, factorsTitle: 'How they match up this season',
    note: f.status === 'live' ? '<b>Our pre-match chance.</b> We have no live model for football; this is the call from before kick-off.' : undefined });
}
function nextFactors(body, f) {
  var c = FB.comp(f.comp);
  if (!c || !c.ok) return;
  FB.compFiles(f.comp, ['strength', 'table']).then(function (side) {
    var box = body.querySelector('#pl-next');
    if (!box || !FB.alive(box) || !side || (!side.strength && !side.table)) return;
    box.innerHTML = nextCard(f, side);
  });
}
/* The last game's box score and xG race: the competition's fixtures say whether the match has a detail file
   (matches/<id>.json); only then is it requested, so nothing 404s. */
function lastDetail(body, doc, last, lf) {
  var c = FB.comp(last.comp);
  if (!c || !c.ok || String(FB.currentSeason(c).sid) !== String(last.sid)) return;
  FB.compFile(last.comp, 'fixtures').then(function (fx) {
    var list = ((fx || {}).matches) || [];
    var hit = list.filter(function (x) { return String(x.id) === String(last.gid); })[0];
    if (!hit || !hit.detail) return null;
    return FB.load(last.comp + '/matches/' + last.gid + '.json');
  }).then(function (m) {
    var bx = body.querySelector('#pl-box');
    if (!m || !bx || !FB.alive(bx)) return;
    var ts = m.team_stats || {}, H = ts.home || {}, A = ts.away || {}, xg = m.xg || [];
    var hs = isNum(m.hs) ? m.hs : lf.hs, as = isNum(m.as) ? m.as : lf.as;
    var row = function (name, tid, g, x, S, side) {
      return '<tr' + (String(tid) === String(last.tid) ? ' class="hl"' : '') + '><td>' + (tid ? FB.clubLink(tid, name, { size: 'sm' }) : esc(name)) + '</td><td class="num"><b>' + (isNum(g) ? g : '–') + '</b></td>' +
        '<td class="num">' + nn(x, 2) + '</td><td class="num">' + (isNum(S.totalShotsOnGoal) ? S.totalShotsOnGoal : '—') + '</td><td class="num">' + (isNum(S.shotsOnGoal) ? S.shotsOnGoal : '—') + '</td>' +
        '<td class="num">' + (isNum(S.ballPossession) ? Math.round(S.ballPossession) + '%' : '—') + '</td></tr>';
    };
    bx.innerHTML = '<div class="qk-table-wrap"><table class="qk-table dense fb-pl-box"><caption class="qk-sr">Box score</caption><thead><tr><th>Team</th><th class="num">Goals</th><th class="num" data-tip="Expected goals: the chance quality of every shot, added up">xG</th><th class="num">Shots</th><th class="num">On target</th><th class="num">Possession</th></tr></thead><tbody>' +
      row(lf.home, lf.home_id, hs, xg[0], H, 'home') + row(lf.away, lf.away_id, as, xg[1], A, 'away') + '</tbody></table></div>' +
      '<p class="fb-cap"><a href="' + esc(FB.href.match(last.comp, last.gid)) + '">The match centre →</a></p>';
    /* the race: each side's expected goals added up shot by shot (stoppage time sits just after its minute) */
    var tx = function (s) { return s.time + (s.added_time ? Math.min(s.added_time, 9) / 10 : 0); };
    var shots = (m.shots || []).filter(function (s) { return isNum(s.xg) && isNum(s.time); }).sort(function (a, b) { return tx(a) - tx(b); });
    var host = body.querySelector('#pl-race');
    if (shots.length < 2 || !host) return;
    var end = Math.max(90, Math.ceil(tx(shots[shots.length - 1])));
    var line = function (isHome) {
      var cum = 0, pts = [[0, 0]], goals = [];
      shots.forEach(function (s) { if (!!s.is_home !== isHome) return; cum += s.xg; pts.push([tx(s), Math.round(cum * 100) / 100]); if (s.shot_type === 'goal') goals.push([tx(s), Math.round(cum * 100) / 100]); });
      pts.push([end, Math.round(cum * 100) / 100]);
      return { pts: pts, goals: goals };
    };
    var LH = line(true), LA = line(false);
    var hexH = lf.home_id ? FB.clubColour(lf.home_id) : null, hexA = lf.away_id ? FB.clubColour(lf.away_id) : null;
    /* club colours lifted to 3:1 when the data has them; else (or when the two clash) the kit's pair, the brighter
       --wp-a for the player's own side */
    var homeMine = String(lf.home_id) === String(last.tid);
    var ch = hexH ? QK.color.team(hexH) : null, ca = hexA ? QK.color.team(hexA) : null;
    if (!ch || !ca || ch === ca || !QK.color.distinct(ch, ca)) { ch = QK.cssVar(homeMine ? '--wp-a' : '--wp-b'); ca = QK.cssVar(homeMine ? '--wp-b' : '--wp-a'); }
    var codeH = FB.clubCode(lf.home, lf.away), codeA = FB.clubCode(lf.away, lf.home);
    host.innerHTML = FB.chartBox('pl-race-c', 240, 'Expected goals through the last game');
    QKC.mount(host.querySelector('#pl-race-c'), function (T) {
      var mk = function (L, col, code, mine) {
        return { type: 'line', name: code, step: 'end', showSymbol: false, data: L.pts, lineStyle: { width: 3, color: col }, itemStyle: { color: col },
          areaStyle: mine ? { color: QKC.hexA(col, 0.12) } : undefined,
          markPoint: { symbol: 'rect', symbolSize: 9, itemStyle: { color: col, borderColor: T.s1, borderWidth: 2 }, label: { show: false }, data: L.goals.map(function (p) { return { coord: p }; }) },
          endLabel: { show: true, formatter: function (p) { return code + ' ' + num(p.value[1], 1); }, color: T.ink1, fontFamily: T.fontDisplay, fontSize: 20 } };
      };
      var xa = QKC.axis(T, { type: 'value', min: 0, max: end, interval: 15, split: false, line: true });
      var ya = QKC.axis(T, { fmt: function (v) { return v.toFixed(1); } });
      var gB = 8 + QKC.nameAxis(xa, 'Minute', 'bottom'), gT = 14 + QKC.nameAxis(ya, 'Expected goals', 'side');
      return { grid: { left: 8, right: 80, top: gT, bottom: gB, containLabel: true }, xAxis: xa, yAxis: ya,
        tooltip: QKC.tooltip(T, { trigger: 'axis', formatter: function (ps) { return '<div>Minute ' + esc(num(ps[0].value[0], 0)) + '</div>' + ps.map(function (q) { return QKC.tipRow(q.color, q.seriesName, num(q.value[1], 2) + ' xG'); }).join(''); } }),
        series: [mk(LH, ch, codeH, String(lf.home_id) === String(last.tid)), mk(LA, ca, codeA, String(lf.away_id) === String(last.tid))] };
    }, { label: 'Expected goals through the last game' });
  });
}

/* Their type: the closest players in the same peer group on this season's headline percentiles. */
function similarOf(info, n) {
  var me = info.pc, g = info.g, PP = info.PP;
  var keys = FB.groupKeys(g, 'headline').filter(function (k) { return isNum(me[k]); });
  if (keys.length < 3) { info.sim = []; return []; }
  info.sim = PP.peers(g).filter(function (r) { return String(r.player_id) !== String(info.p.player_id); }).map(function (r) {
    var pc = PP.pct(r);
    if (!pc) return null;
    var d = 0, m = 0;
    keys.forEach(function (k) { if (isNum(pc[k])) { d += (pc[k] - me[k]) * (pc[k] - me[k]); m++; } });
    return m >= Math.max(3, keys.length - 1) ? [Math.sqrt(d / m), r, pc] : null;
  }).filter(Boolean).sort(function (a, b) { return a[0] - b[0]; }).slice(0, n || 3);
  return info.sim;
}
function typeCard(body, doc, info, id) {
  ['pl-type', 'pl-type-r'].forEach(function (x) { if (x !== id) FB.set(x, ''); });
  var sim = (info && info.sim) || [];
  if (!sim.length) { FB.set(id, ''); return; }
  FB.set(id, '<article class="qk-card"><div class="qk-card-body"><div class="qk-kicker">Their type</div><h4 class="fb-pl-h4">Plays most like</h4><ul class="fb-pl-type">' +
    sim.map(function (s) {
      var r = s[1];
      return '<li>' + FB.playerLink(r.player_id, r.name) + '<span class="s">' + esc(r.team || '') + '</span><a class="v" href="' + esc('#/compare/players/' + FB.enc(doc.id) + '/' + FB.enc(r.player_id)) + '">Compare</a></li>';
    }).join('') + '</ul>' + QK.aside('Closest match on this season’s profile among ' + info.g.name + ' in ' + info.where + ', on the headline numbers for the role.') + '</div></article>');
}
/* The tale of the tape: the player against one of the closest matches (chips switch, a link opens all three in
   Compare), on the role group's headline and secondary sets, percentiles against the role group; verdicts under it. */
function tapeSim(body, doc, info) {
  var sim = (info.sim || []).slice(0, 3);
  var hbox = body.querySelector('#pl-tape-h'), pick = body.querySelector('#pl-tape-pick'), tbox = body.querySelector('#pl-tape'), vbox = body.querySelector('#pl-verd');
  if (!hbox || !sim.length) return;
  var g = info.g;
  (info.slug ? FB.compFile(info.slug, 'teams') : Promise.resolve(null)).then(function (td) {
    if (!FB.alive(tbox)) return;
    var TM = (td || {}).teams || {};
    /* the row's own team id when the payload carries it (players_live `tid`), else the club found by name */
    var tidOf = function (r) { if (r && r.tid) return r.tid; var x = TM[r.team]; return x && x.team_id ? x.team_id : null; };
    var meTid = (doc.current_club || {}).tid || tidOf(info.p);
    var draw = function (i) {
      var s = sim[i];
      var E = [{ r: info.p, pc: info.pc, tid: meTid, id: String(doc.id), name: doc.name }, { r: s[1], pc: s[2], tid: tidOf(s[1]), id: String(s[1].player_id), name: s[1].name }];
      var best = [null, null];
      var rowOf = function (k) {
        var mi = FB.metricInfo(k) || {}, m = (info.meta || {})[k] || {};
        var pcs = E.map(function (e) { return e.pc[k]; });
        pcs.forEach(function (v, j) { var o = pcs[1 - j]; if (!isNum(v)) return; var d = v - (isNum(o) ? o : 0); if (!best[j] || d > best[j].d) best[j] = { k: k, d: d, v: info.valOf(E[j].r, k), fmt: m.fmt }; });
        return { label: mi.label || m.label || k, tip: mi.tip || m.desc || '', better: mi.lower ? 'low' : 'high', values: E.map(function (e) { return info.valOf(e.r, k); }), pctls: pcs, fmt: function (v) { return FB.fmtSet(k, v, m.fmt); } };
      };
      var groups = [{ label: 'Headline', rows: FB.groupKeys(g, 'headline').map(rowOf) }, { label: 'More', rows: FB.groupKeys(g, 'more').map(rowOf) }];
      var names = E.map(function (e) { return FB.surname(e.name) || e.name; });
      if (names[0] === names[1]) names = E.map(function (e) { return e.r.short_name || e.name; });
      hbox.innerHTML = QK.sectionHead({ kicker: 'Tale of the tape', title: names[0] + ' or ' + names[1] + '?', sub: 'Bar length = percentile against ' + g.name + ' in ' + info.where + '. The better number in each row is solid.' });
      var ents = E.map(function (e, j) {
        return { name: e.name, short: names[j], href: FB.href.player(e.id), colour: e.tid ? FB.clubColour(e.tid) : null, alt: e.tid ? FB.clubAlt(e.tid) : null,
          sub: [e.r.team || '', FB.int(e.r.minutes) + ' min'].filter(Boolean).join(' · ') };
      });
      tbox.innerHTML = QK.compareView({ entities: ents, groups: groups });
      vbox.innerHTML = QK.verdicts(E.map(function (e, j) {
        var b = best[j];
        return b && b.d > 0 ? { title: ARCH[b.k] || 'The standout', who: names[j], text: 'the better of the two on ' + lc1((FB.metricInfo(b.k) || {}).label || b.k) + ' (' + FB.fmtSet(b.k, b.v, b.fmt) + ').' } : null;
      }));
    };
    var ids = sim.map(function (s) { return String(s[1].player_id); });
    pick.innerHTML = sim.map(function (s, i) { return '<button type="button" class="qk-chip" data-i="' + i + '" aria-pressed="' + (i === 0) + '">' + esc(FB.surname(s[1].name) || s[1].name) + '</button>'; }).join('') +
      (ids.length > 1 ? '<a class="qk-chip" href="' + esc('#/compare/players/' + FB.enc(doc.id) + '/' + FB.enc(ids[0]) + '?p3=' + FB.enc(ids[1])) + '">All three in Compare</a>'
        : '<a class="qk-chip" href="' + esc('#/compare/players/' + FB.enc(doc.id) + '/' + FB.enc(ids[0])) + '">Open in Compare</a>');
    pick.hidden = false;
    Array.prototype.forEach.call(pick.querySelectorAll('button'), function (bt) {
      bt.addEventListener('click', function () {
        Array.prototype.forEach.call(pick.querySelectorAll('button'), function (x) { x.setAttribute('aria-pressed', x === bt ? 'true' : 'false'); });
        draw(Number(bt.getAttribute('data-i')) || 0);
      });
    });
    draw(0);
  });
}

/* The Savant-style percentile rail and "Among peers" for one live competition (players_live.json), against the
   player's formation-role group in that competition (FB.MSET, the metrics spec: centre-backs, full-backs, DM/CM, AM/W,
   strikers, goalkeepers) over max(the group's minimum, the competition's floor), on the group's headline and secondary
   sets; the peer group and sample always stated, metrics short of their m50 drawn early, last season's ring when the
   person file has it. Without the role payload (value/lines.json) it falls back to the position letter
   (pctPanelLetter). done(info) hands the page what it needs for the short version, the tiles, how sure, their type
   and the compare; done(null) when there is no line. */
function pctPanel(body, doc, slug, done) {
  done = done || function () {};
  var cardBox = body.querySelector('#pl-pcard'), distCard = body.querySelector('#pl-distcard');
  if (!slug || !FB.roles) return pctPanelLetter(body, doc, slug, done);
  /* the rows' own role and gar90 when the payload carries them (no extra file); else the value/lines.json join */
  return FB.compFile(slug, 'players_live').then(function (lv) {
    return FB.rolesFor(((lv || {}).players || []).some(function (x) { return x.role !== undefined; })).then(function (R0) { return [lv, R0]; });
  }).then(function (arr) {
    if (!cardBox.isConnected) return;
    var live = arr[0] || {}, R = arr[1];
    var players = live.players || [];
    var p = players.filter(function (x) { return String(x.player_id) === String(doc.id); })[0];
    if (!R || !R.ok || !p) return pctPanelLetter(body, doc, slug, done);
    var role = FB.rowRole(R, p.role, doc.id, slug), g = FB.peerGroup(role);
    var c = FB.comp(slug);
    var where = FB.compName(slug) + ' ' + (FB.currentSeason(c).season || '');
    if (!g) {
      cardBox.innerHTML = QK.pctRail({ kicker: 'How they stack up', title: 'Percentiles: how the player ranks', groups: [], emptyTitle: 'No peer group yet',
        emptyText: role ? 'No start in a formation role in ' + where + ' (substitute appearances only), so there is no position group to rank the player in.' : 'No formation role for the player in ' + where + ' yet.' });
      if (distCard) distCard.hidden = true;
      done({ p: p, where: where, minutes: p.minutes, slug: slug });
      return;
    }
    var meta = metaMap(live.metrics);
    var valOf = function (r, k) { return k === 'gar90' ? FB.rowGar(R, r.gar90, r.player_id, slug) : r[k]; };
    var PP = FB.peerPct({ rows: players, minutes: function (r) { return r.minutes; }, role: function (r) { return FB.rowRole(R, r.role, r.player_id, slug); },
      val: valOf, floor: live.minutes_floor });
    var min = PP.min(g), pc = PP.pct(p), peers = PP.peers(g);
    var val = function (k) { return valOf(p, k); };
    var prev = prevPctOf(doc, slug);
    var row = function (k) {
      var info = FB.metricInfo(k) || {}, m = meta[k] || {};
      if (!pc || !isNum(pc[k])) return null;
      return { label: info.label || m.label || k, sub: SUB[k] || '', pctl: pc[k], prev: prev && isNum(prev.pct[k]) ? prev.pct[k] : null, value: FB.fmtSet(k, val(k), m.fmt), tip: info.tip || m.desc || '', early: FB.isEarly(g, k, p.minutes) };
    };
    var groups = [{ label: 'Headline', rows: FB.groupKeys(g, 'headline').map(row).filter(Boolean) }, { label: 'More', rows: FB.groupKeys(g, 'more').map(row).filter(Boolean) }];
    var small = (p.minutes || 0) < g.small;
    var sample = FB.int(p.minutes) + ' min · ' + (p.matches || 0) + ' apps · ' + peers.length + ' ' + g.short + ' over ' + FB.int(min) + ' min' + (small ? ' · small sample' : '');
    var shotsHref = '#/player/' + FB.enc(doc.id) + FB.qs({ tab: 'shots', c: slug });
    var pv = prev && prev.peer ? prev.peer : null;
    cardBox.innerHTML = QK.pctRail({ id: 'pl-rail', kicker: 'How they stack up', title: 'Percentiles: how the player ranks', peer: cap1(g.name) + ' · ' + where, sample: sample, groups: groups,
      ringLabel: 'last season' + (pv ? ' (' + [pv.season || '', isNum(pv.min) ? FB.int(pv.min) + ' min' : ''].filter(Boolean).join(', ') + ')' : ''),
      emptyTitle: 'Not enough minutes yet', emptyText: 'Percentiles appear once the player passes ' + FB.int(min) + ' minutes as one of the ' + g.name + ' in ' + where + ' (' + FB.int(p.minutes) + ' so far).',
      note: FB.peerLine(g, where, min).replace(/^v /, 'Against ') + ' (formation role this season: ' + role + '). 100 is the best; where less is better the scale is already turned round. Value added is our player value model; the rest are per-90 rates from the competition line.',
      foot: '<span>' + esc(FB.compName(slug, true)) + '</span><a href="' + esc(shotsHref) + '">Every percentile and the shot map →</a>' });
    done(pc ? { g: g, pc: pc, p: p, PP: PP, where: where, minutes: p.minutes, val: val, valOf: valOf, meta: meta, prev: !!prev, slug: slug } : { g: g, p: p, where: where, minutes: p.minutes, val: val, slug: slug });
    // among peers: the role group's distribution of one headline metric
    var keys = FB.groupKeys(g, 'headline').filter(function (k) { return PP.values(g, k).length >= 8; }).slice(0, 4);
    var seg = body.querySelector('#pl-dist-seg');
    if (!distCard || !keys.length || peers.length < 8) { if (distCard) distCard.hidden = true; return; }
    distCard.hidden = false;
    seg.innerHTML = FB.seg('pl-dist-m', keys.map(function (k) { return [k, (FB.metricInfo(k) || {}).label || (meta[k] || {}).label || k]; }), keys[0], 'Metric');
    FB.set('pl-dist-sub', esc(cap1(g.name)) + ' in ' + esc(where) + ' over ' + FB.int(min) + ' minutes (' + peers.length + '), with the player and the median marked; bars coloured by percentile.');
    var draw = function (key) {
      var info = FB.metricInfo(key) || {}, m = meta[key] || {};
      var vals = PP.values(g, key);
      var box = body.querySelector('#pl-dist');
      if (!box || vals.length < 8) { chartEmpty(box, 'Too few peers with this metric'); return; }
      var mine = val(key);
      QKC.distribution(box, { values: vals, binCount: 20, lowerBetter: !!info.lower, fmt: function (v) { return FB.fmtSet(key, v, m.fmt); },
        xName: (info.label || m.label || key) + ' · ' + vals.length + ' ' + g.short, yName: 'Players',
        marks: (isNum(mine) ? [{ x: mine, label: FB.surname(doc.name) }] : []).concat([{ x: FB.median(vals), label: 'Median' }]), label: 'Distribution of ' + (info.label || key) });
    };
    draw(keys[0]);
    FB.wireSeg(seg, 'pl-dist-m', draw);
  });
}
/* The same rail against the position letter (G, D, M, F) the payloads rank by: the fallback when the role payload
   is missing. */
function pctPanelLetter(body, doc, slug, done) {
  done = done || function () {};
  var cardBox = body.querySelector('#pl-pcard'), distCard = body.querySelector('#pl-distcard');
  var noLine = function (txt) {
    cardBox.innerHTML = QK.pctRail({ kicker: 'How they stack up', title: 'Percentiles: how the player ranks', groups: [], emptyTitle: 'No percentiles this season', emptyText: txt });
    if (distCard) distCard.hidden = true;
    done(null);
  };
  if (!slug) { noLine('No line this season in a competition with player percentiles.'); return Promise.resolve(); }
  return FB.compFile(slug, 'players_live').then(function (live) {
    if (!cardBox.isConnected) return;
    var players = (live || {}).players || [];
    var p = players.filter(function (x) { return String(x.player_id) === String(doc.id); })[0];
    var c = FB.comp(slug);
    var where = FB.compName(slug) + ' ' + (FB.currentSeason(c).season || '');
    if (!p) { noLine('No line for the player in ' + where + '.'); return; }
    var L = p.is_gk ? 'G' : (PLAYER_SETS[p.position] ? p.position : (PLAYER_SETS[doc.pos] ? doc.pos : 'M'));
    var floor = (live || {}).minutes_floor || 0;
    var meta = metaMap(live.metrics);
    var pc = p.pct || {};
    var peer = PEER_NAME[L] + ' · ' + where;
    var sample = FB.int(p.minutes) + ' min · ' + (p.matches || 0) + ' apps · peers need ' + FB.int(floor) + '+ min';
    var groups = PLAYER_SETS[L].map(function (g) {
      return { label: g[0], rows: g[1].map(function (k) {
        var m = meta[k];
        if (!m || !isNum(pc[k])) return null;
        return { label: m.label || k, sub: SUB[k] || '', pctl: pc[k], value: FB.fmtMetric(p[k], m.fmt), tip: m.desc || '', early: (p.minutes || 0) < earlyMin(L, k) };
      }).filter(Boolean) };
    });
    var shotsHref = '#/player/' + FB.enc(doc.id) + FB.qs({ tab: 'shots', c: slug });
    cardBox.innerHTML = QK.pctRail({ kicker: 'How they stack up', title: 'Percentiles: how the player ranks', peer: peer, sample: sample, groups: groups,
      emptyTitle: 'Not enough minutes yet', emptyText: 'Percentiles appear once the player passes ' + FB.int(floor) + ' minutes in ' + where + ' (' + FB.int(p.minutes) + ' so far).',
      note: 'Against ' + PEER_NAME[L] + ' in ' + where + ' with ' + FB.int(floor) + '+ minutes; 100 is the best. Where less is better the scale is already turned round.',
      foot: '<span>' + esc(FB.compName(slug, true)) + '</span><a href="' + esc(shotsHref) + '">Every percentile and the shot map →</a>' });
    done({ p: p, where: where, minutes: p.minutes, pc: pc, val: function (k) { return p[k]; }, slug: slug });
    // among peers: the peer group's distribution of one metric
    var peers = players.filter(function (x) { return (L === 'G' ? x.is_gk : (!x.is_gk && x.position === L)) && (x.qualified || (x.minutes || 0) >= floor); });
    var keys = (PLAYER_DIST[L] || []).filter(function (k) { return meta[k]; });
    var seg = body.querySelector('#pl-dist-seg');
    if (!distCard || !keys.length || peers.length < 8) { if (distCard) distCard.hidden = true; return; }
    seg.innerHTML = FB.seg('pl-dist-m', keys.map(function (k) { return [k, meta[k].label || k]; }), keys[0], 'Metric');
    FB.set('pl-dist-sub', esc(cap1(PEER_NAME[L])) + ' in ' + esc(where) + ' over ' + FB.int(floor) + ' minutes (' + peers.length + '), with the player and the median marked; bars coloured by percentile.');
    var draw = function (key) {
      var m = meta[key] || {};
      var vals = peers.map(function (x) { return x[key]; }).filter(isNum).sort(function (a, b) { return a - b; });
      var box = body.querySelector('#pl-dist');
      if (!box || vals.length < 8) { chartEmpty(box, 'Too few peers with this metric'); return; }
      var med = FB.median(vals);
      var mine = p[key];
      QKC.distribution(box, { values: vals, binCount: 20, lowerBetter: !!m.lower, fmt: function (v) { return FB.fmtMetric(v, m.fmt); },
        xName: (m.label || key) + ' · ' + vals.length + ' ' + PEER_NAME[L], yName: 'Players',
        marks: (isNum(mine) ? [{ x: mine, label: FB.surname(doc.name) }] : []).concat([{ x: med, label: 'Median' }]), label: 'Distribution of ' + (m.label || key) });
    };
    draw(keys[0]);
    FB.wireSeg(seg, 'pl-dist-m', draw);
  });
}

function yearsTable(box, Y, doc, open) {
  if (!box) return;
  if (!Y.length) { box.innerHTML = FB.empty('No season in the filter'); return; }
  var gapThrough = doc && doc.career_gap ? doc.career_gap.through : null;
  var head = '<tr><th class="sticky-col">Season</th><th>Competition</th><th>Team</th><th class="num">Apps</th><th class="num">Min</th><th class="num">G</th><th class="num">A</th><th class="num">xG</th><th class="num">xA</th><th class="num">G+A/90</th><th class="num">Rating</th><th>Data</th></tr>';
  var bodies = Y.map(function (y, i) {
    var isOpen = i < open;
    var teams = [];
    y.rows.forEach(function (r) { if (r.scope === 'club' && r.team && teams.indexOf(r.team) < 0) teams.push(r.team); });
    var top = '<tr class="fb-pl-yr">' +
      '<td class="sticky-col"><button type="button" class="fb-pl-tog" aria-expanded="' + isOpen + '"><span class="fb-pl-car" aria-hidden="true">▸</span><b>' + esc(y.era) + '</b></button></td>' +
      '<td><span class="qk-muted">' + y.rows.length + ' competition' + (y.rows.length === 1 ? '' : 's') + (y.intlMin ? ' · ' + int(y.intlMin) + ' intl min' : '') + '</span></td>' +
      '<td>' + esc(teams.slice(0, 2).join(', ')) + '</td>' +
      '<td class="num">' + int(y.apps) + '</td><td class="num">' + int(y.min) + '</td><td class="num"><b>' + int(y.g) + '</b></td><td class="num"><b>' + int(y.a) + '</b></td>' +
      '<td class="num">' + nn(y.xg, 1) + '</td><td class="num">' + nn(y.xa, 1) + '</td><td class="num">' + nn(per90(y.g + y.a, y.min), 2) + '</td><td class="num">' + nn(y.rt, 2) + '</td>' +
      '<td>' + (gapThrough && eraKey(y.era) <= eraKey(gapThrough) ? '<span class="fb-cov partial" data-tip="The career list from Sofascore is still being backfilled: competitions from this season and older may be missing, so the season is a lower bound.">Partial</span>' : y.partial ? '<span class="fb-cov partial" data-tip="At least one competition this season is a lower bound (line-ups missing).">Partial</span>' : y.totals ? '<span class="fb-cov totals" data-tip="Includes Sofascore season totals where our line-ups were incomplete.">Totals</span>' : '<span class="fb-cov full">Full</span>') + '</td></tr>';
    var kids = y.rows.map(function (r) {
      var sh = r.comp ? seasonHref(r.comp, r.sid, 'players') : null;
      return '<tr class="fb-pl-sub"' + (isOpen ? '' : ' hidden') + '>' +
        '<td class="sticky-col"><span class="qk-muted fb-pl-indent">' + esc(r.season || '') + '</span></td>' +
        '<td>' + (sh ? '<a class="fb-link fb-comp" href="' + esc(sh) + '"><i style="--k:' + FB.kindColor(r.kind) + '"></i>' + esc(r.cname) + '</a>' : '<span class="fb-comp"><i style="--k:' + FB.kindColor(r.kind) + '"></i>' + esc(r.cname) + '</span>') + '</td>' +
        '<td>' + teamA(r.tid, r.team) + '</td>' +
        '<td class="num">' + int(r.apps || 0) + (isNum(r.starts) && r.starts !== r.apps ? ' <span class="fb-pl-dim">' + r.starts + '</span>' : '') + '</td><td class="num">' + int(r.min || 0) + '</td>' +
        '<td class="num">' + int(r.g || 0) + '</td><td class="num">' + int(r.a || 0) + '</td><td class="num">' + nn(r.xg, 2) + '</td><td class="num">' + nn(r.xa, 2) + '</td>' +
        '<td class="num">' + nn(per90((r.g || 0) + (r.a || 0), r.min), 2) + '</td><td class="num">' + nn(r.rt, 2) + '</td>' +
        '<td>' + (r.source === 'archive' ? '<span class="fb-cov totals" data-tip="An older season from the archive: Sofascore\'s season totals (no match log).">Archive</span>' : (FB.coverageChip(r) || (r.source === 'live' ? '<span class="qk-badge accent">Current</span>' : ''))) + '</td></tr>';
    }).join('');
    return '<tbody class="fb-pl-yb">' + top + kids + '</tbody>';
  }).join('');
  box.innerHTML = '<div class="qk-table-wrap"><table class="qk-table dense fb-pl-years"><caption class="qk-sr">Season by season</caption><thead>' + head + '</thead>' + bodies + '</table></div>';
  Array.prototype.forEach.call(box.querySelectorAll('.fb-pl-tog'), function (b) {
    b.addEventListener('click', function () {
      var on = b.getAttribute('aria-expanded') !== 'true';
      b.setAttribute('aria-expanded', on ? 'true' : 'false');
      Array.prototype.forEach.call(b.closest('tbody').querySelectorAll('.fb-pl-sub'), function (tr) { tr.hidden = !on; });
    });
  });
}

function seasonCharts(body, Y) {
  var ys = Y.slice().reverse();
  var eras = ys.map(function (y) { return y.era; });
  var boxes = ['pl-ga', 'pl-min', 'pl-xg', 'pl-rt'].map(function (id) { return body.querySelector('#' + id); });
  if (!eras.length) { boxes.forEach(function (b) { chartEmpty(b, 'No season in the filter'); }); return; }
  var kinds = Object.keys(KIND_ORDER).filter(function (k) { return ys.some(function (y) { return y.rows.some(function (r) { return r.kind === k; }); }); })
    .sort(function (a, b) { return KIND_ORDER[a] - KIND_ORDER[b]; });
  var perKind = function (k, f) { return ys.map(function (y) { var rr = y.rows.filter(function (r) { return r.kind === k; }); return f(rr); }); };
  QKC.bar(boxes[0], { cats: eras, stack: true, legend: true, fmt: function (v) { return int(v); }, catName: 'Season', valName: 'Goals plus assists', label: 'Goals and assists by season',
    series: kinds.map(function (k) { return { name: KIND_LABEL[k], color: FB.kindColorHex(k), data: perKind(k, function (rr) { return sum(rr, 'g') + sum(rr, 'a'); }) }; }) });
  QKC.bar(boxes[1], { cats: eras, stack: true, legend: true, fmt: function (v) { return int(v); }, catName: 'Season', valName: 'Minutes', label: 'Minutes by season',
    series: kinds.map(function (k) { return { name: KIND_LABEL[k], color: FB.kindColorHex(k), data: perKind(k, function (rr) { return sum(rr, 'min'); }) }; }) });
  var xgOk = ys.some(function (y) { return isNum(y.xg); });
  /* where xG covers only part of a season's minutes (xg_min < min), the goals scored in those same matches (xg_g) */
  var partXg = function (y) { return isNum(y.xg) && isNum(y.xg_g) && isNum(y.xg_min) && isNum(y.min) && y.xg_min < y.min; };
  var anyPart = ys.some(partXg);
  var xgSub = body.querySelector('#pl-xg-sub');
  if (xgSub && anyPart) xgSub.textContent = 'Per season, where the stores carry xG. Where xG covers only some of the player\'s matches, goals count those matches only, so the two compare like with like.';
  if (boxes[2]) QKC.line(boxes[2], { x: eras, legend: true, endLabels: false, yMin: 0, yFmt: function (v) { return num(v, 0); }, xName: 'Season', yName: 'Goals and xG', label: 'Goals against xG by season',
    series: [{ name: anyPart ? 'Goals (in matches with xG)' : 'Goals', color: QK.cssVar('--c-2'), data: ys.map(function (y) { return partXg(y) ? y.xg_g : y.g; }) }].concat(xgOk ? [{ name: 'xG', color: QK.cssVar('--c-1'), dash: true, data: ys.map(function (y) { return isNum(y.xg) ? Math.round(y.xg * 10) / 10 : null; }) }] : []) });
  var rts = ys.map(function (y) { return isNum(y.rt) ? Math.round(y.rt * 100) / 100 : null; });
  if (!rts.some(isNum)) chartEmpty(boxes[3], 'No ratings', 'No rated season in the filter.');
  else QKC.line(boxes[3], { x: eras, endLabels: false, yScale: true, yFmt: function (v) { return num(v, 2); }, xName: 'Season', yName: 'Sofascore rating', label: 'Rating by season', series: [{ name: 'Rating', color: QK.cssVar('--c-3'), data: rts, area: true }] });
}

function drawValue(body, doc) {
  Promise.all([FB.load('value/players.json'), FB.load('value/lines.json'), FB.load('value/meta.json')]).then(function (arr) {
    var box = body.querySelector('#pl-value');
    if (!box || !box.isConnected) return;
    var vp = arr[0], vl = arr[1], meta = arr[2] || {};
    var f = (vp || {}).fields || [];
    var row = null;
    ((vp || {}).rows || []).some(function (r) { if (String(r[0]) === String(doc.id)) { row = {}; f.forEach(function (k, i) { row[k] = r[i]; }); return true; } return false; });
    var lines = FB.rows(vl).filter(function (r) { return String(r.id) === String(doc.id); });
    if (!row && !lines.length) { box.innerHTML = FB.muted('No value line: under the minutes the value model needs in the last 12 months of club football.'); return; }
    var roles = meta.roles || {};
    var html = '';
    if (row) {
      html += FB.kpis([
        FB.kpi('Value added (GAR/90)', FB.signed(row.gar90, 2), { signal: true, pctl: isNum(row.pct) ? row.pct : null, tip: 'Goals above replacement per 90 minutes, last 12 months of club football, our value model', sub: isNum(row.pct) ? FB.ordinal(row.pct) + ' percentile among ' + esc(roles[row.role] || row.role || '') + 's' : esc(roles[row.role] || row.role || '') }),
        FB.kpi('GAR', FB.signed(row.gar, 1), { sub: int(row.min) + ' min · PAR ' + FB.signed(row.par, 1) + ' pts' }),
        FB.kpi('Fair value', isNum(row.v2) ? num(row.v2, 1) : '—', { tip: 'Valuation v2: expected points above replacement over four seasons (10-90% band)', sub: isNum(row.v2lo) ? num(row.v2lo, 1) + '–' + num(row.v2hi, 1) + ' pts' : '' }),
        FB.kpi('Fair fee', isNum(row.fee) ? FB.money(row.fee) : '—', { tip: 'Fair fee to a buyer like the player\'s own club (fee model)', sub: isNum(row.feelo) ? FB.money(row.feelo) + '–' + FB.money(row.feehi) : (isNum(row.mv) ? 'market value ' + FB.money(row.mv) : '') })
      ], 'fb-pl-kpis2');
    }
    if (lines.length) {
      html += '<div class="fb-mt" id="pl-vlines"></div>';
    }
    box.innerHTML = html;
    if (lines.length) {
      FB.table(box.querySelector('#pl-vlines'), [
        { key: 'comp', label: 'This season', fmt: function (v) { return FB.compLink(v, { short: true }); } },
        { key: 'min', label: 'Min', num: true },
        { key: 'gar90', label: 'GAR/90', num: true, fmt: function (v) { return FB.signed(v, 2); } },
        { key: 'pct', label: 'Pctl', num: true, fmt: function (v) { return isNum(v) ? FB.pctl(v) : '—'; } },
        { key: 'prev90', label: 'Last season', num: true, tip: 'GAR/90 last season in the same competition (450+ minutes)', fmt: function (v) { return isNum(v) ? FB.signed(v, 2) : '—'; } }
      ], lines.map(function (r) { return r; }), { sort: { key: 'min', dir: 'desc' } });
    }
  });
}

/* Percentile bars and radar for one live competition (players_live.json). */
function profileCard(el, box, doc, slug, compact) {
  if (!box) return Promise.resolve();
  return FB.compFile(slug, 'players_live').then(function (live) {
    if (!box.isConnected) return;
    var p = ((live || {}).players || []).filter(function (x) { return String(x.player_id) === String(doc.id); })[0];
    if (!p) { box.innerHTML = FB.muted('No line for the player in ' + esc(FB.compName(slug)) + ' this season.'); return; }
    var metrics = (live.metrics || []).filter(function (m) { return m.pct && (m.scope === 'all' || m.scope === (p.is_gk ? 'gk' : 'out')); });
    var pos = (live.positions || {})[p.position] || (p.is_gk ? 'Goalkeeper' : 'Outfield player');
    var hasP = p.pct && Object.keys(p.pct).length;
    var sub = esc(FB.compName(slug)) + ' ' + esc(FB.currentSeason(FB.comp(slug)).season || '') + ' · against ' + esc(String(pos).toLowerCase()) + 's with ' + (live.minutes_floor || 0) + '+ minutes';
    var L = p.is_gk ? 'G' : (PLAYER_SETS[p.position] ? p.position : 'M');
    if (!hasP) { box.innerHTML = '<p class="fb-cap">' + sub + '</p>' + FB.empty('Not enough minutes yet', 'Percentiles appear once the player passes ' + (live.minutes_floor || 0) + ' minutes in this competition (' + int(p.minutes) + ' so far).'); return; }
    var radarAxes = (p.is_gk ? RADAR_GK : RADAR_OUT).filter(function (a) { return isNum(p.pct[a[0]]); });
    if (compact) {
      var keyList = p.is_gk ? ['saves_90', 'save_pct', 'goals_prevented_90', 'pass_pct', 'long_ball_pct', 'rating'] : ['npxg_90', 'xa_90', 'shots_90', 'key_passes_90', 'dribbles_90', 'prog_carries_90', 'tackles_90', 'rating'];
      var bars = keyList.map(function (k) { var m = metrics.filter(function (x) { return x.key === k; })[0]; return m && isNum(p.pct[k]) ? { label: m.label, pctl: p.pct[k], value: FB.fmtMetric(p[k], m.fmt) } : null; }).filter(Boolean);
      box.innerHTML = '<p class="fb-cap fb-pl-cap0">' + sub + '. <a href="' + esc('#/player/' + FB.enc(doc.id) + FB.qs({ tab: 'shots', c: slug })) + '">Every percentile and the shot map →</a></p>' + QK.pctlBars(bars);
      return;
    }
    var groups = [];
    metrics.forEach(function (m) {
      if (!isNum(p.pct[m.key])) return;
      var g = groups.filter(function (x) { return x.name === m.group; })[0];
      if (!g) { g = { name: m.group, items: [] }; groups.push(g); }
      g.items.push({ label: m.label + (m.lower ? ' ↓' : ''), pctl: p.pct[m.key], value: FB.fmtMetric(p[m.key], m.fmt), early: (p.minutes || 0) < earlyMin(L, m.key) });
    });
    box.innerHTML = '<div class="fb-pl-prof">' + '<div class="fb-pl-radarwrap">' + FB.chartBox('pl-radar', 360, 'Percentile profile') + '</div>' +
      QK.pctCard({ title: 'Every percentile', peer: String(pos).toLowerCase() + 's · ' + FB.compName(slug) + ' ' + (FB.currentSeason(FB.comp(slug)).season || ''),
        sample: int(p.minutes) + ' min · peers need ' + int(live.minutes_floor || 0) + '+ min', cls: 'fb-pl-allpct',
        groups: groups.map(function (g) { return { label: g.name, rows: g.items }; }), note: 'Higher is better; ↓ marks counts where fewer is better (already turned round).' }) + '</div>';
    if (radarAxes.length >= 3) FB.charts.radar(box.querySelector('#pl-radar'), { axes: radarAxes.map(function (a) { return { name: a[1], max: 100 }; }), series: [{ name: doc.name, values: radarAxes.map(function (a) { return p.pct[a[0]]; }), color: QK.cssVar('--signal') }], label: 'Percentile radar, ' + FB.compName(slug) });
    else box.querySelector('#pl-radar').style.display = 'none';
  });
}

// ── season by season (full career table) ──────────────────────────────────

function drawSeasons(el, body, doc, R, q) {
  var rows = R.all.filter(keepQ(q)).sort(function (a, b) { return eraKey(b.era) - eraKey(a.era) || (KIND_ORDER[a.kind] - KIND_ORDER[b.kind]) || (b.min || 0) - (a.min || 0); });
  var Y = byYear(rows);
  body.innerHTML =
    FB.card('Year by year', 'All competitions in the filter summed per season: ' + esc(filterLabel(q, doc.comps)) + '. Open a season for its competitions.', '<div id="pl-years"></div>', { flush: true }) +
    FB.card('Career by competition and season', 'One row per competition, season and team. Store rows carry xG; archive rows are Sofascore\'s season totals; partial rows are lower bounds.', '<div id="pl-career"></div>', { flush: true }) +
    FB.card('By competition', 'Every season in the filter, summed per competition.', '<div id="pl-split"></div>', { flush: true });
  yearsTable(body.querySelector('#pl-years'), Y, doc, Y.length);
  FB.table(body.querySelector('#pl-career'), [
    { key: 'era', label: 'Season', sticky: true, fmt: function (v, r) { return '<b>' + esc(r.season || v || '—') + '</b>'; } },
    { key: 'cname', label: 'Competition', fmt: function (v, r) { var h = r.comp ? seasonHref(r.comp, r.sid, 'players') : null; return (h ? '<a class="fb-link" href="' + esc(h) + '">' + esc(v) + '</a>' : esc(v)) + ' ' + FB.kindChip(r.kind); } },
    { key: 'team', label: 'Team', fmt: function (v, r) { return teamA(r.tid, v); } },
    { key: 'apps', label: 'Apps', num: true }, { key: 'starts', label: 'St', num: true }, { key: 'min', label: 'Min', num: true },
    { key: 'g', label: 'G', num: true }, { key: 'a', label: 'A', num: true },
    { key: 'xg', label: 'xG', num: true, fmt: function (v) { return nn(v, 2); } }, { key: 'xa', label: 'xA', num: true, fmt: function (v) { return nn(v, 2); } },
    { key: 'ga90', label: 'G+A/90', num: true, fmt: function (v) { return nn(v, 2); } },
    { key: 'rt', label: 'Rating', num: true, fmt: function (v) { return nn(v, 2); } },
    { key: 'source', label: 'Data', fmt: function (v, r) { return v === 'archive' ? '<span class="fb-cov totals" data-tip="Sofascore season totals from the archive">Archive</span>' : (FB.coverageChip(r) || (v === 'live' ? '<span class="qk-badge accent">Current</span>' : '<span class="fb-cov full">Full</span>')); } }
  ], rows.map(function (r) { return FB.merge(r, { ga90: per90((r.g || 0) + (r.a || 0), r.min), _k: eraKey(r.era) }); }), { maxHeight: 640, caption: 'Career by season' });
  var by = {};
  rows.forEach(function (r) { var k = r.comp || r.cname; (by[k] = by[k] || { comp: r.comp, cname: r.cname, kind: r.kind, rows: [] }).rows.push(r); });
  var split = Object.keys(by).map(function (k) {
    var s = by[k], m = sum(s.rows, 'min'), g = sum(s.rows, 'g'), a = sum(s.rows, 'a');
    var eras = {}; s.rows.forEach(function (r) { eras[r.era] = 1; });
    return { comp: s.comp, cname: s.cname, kind: s.kind, n: Object.keys(eras).length, apps: sum(s.rows, 'apps'), min: m, g: g, a: a, ga90: per90(g + a, m), rt: wavg(s.rows, 'rt') };
  });
  FB.table(body.querySelector('#pl-split'), [
    { key: 'cname', label: 'Competition', sticky: true, fmt: function (v, r) { return '<b>' + esc(v) + '</b> ' + FB.kindChip(r.kind); } },
    { key: 'n', label: 'Seasons', num: true }, { key: 'apps', label: 'Apps', num: true }, { key: 'min', label: 'Min', num: true },
    { key: 'g', label: 'G', num: true }, { key: 'a', label: 'A', num: true }, { key: 'ga90', label: 'G+A/90', num: true, fmt: function (v) { return nn(v, 2); } },
    { key: 'rt', label: 'Rating', num: true, fmt: function (v) { return nn(v, 2); } },
    { key: 'comp', label: '', sort: false, fmt: function (v) { return v ? '<a class="fb-link" href="' + esc('#/player/' + FB.enc(doc.id) + FB.qs({ tab: 'seasons', c: v })) + '">only this →</a>' : ''; } }
  ], split, { sort: { key: 'min', dir: 'desc' }, caption: 'By competition' });
}

// ── matches ───────────────────────────────────────────────────────────────

function drawMatches(el, body, doc, R, q) {
  var apps = R.apps.filter(keepQ(q));
  var names = doc.comps || {};
  body.innerHTML =
    FB.card('Form', 'Rating per appearance (bars, coloured by rating) with the five-match rolling mean, and xG with goals per appearance: the latest ' + Math.min(apps.length, 60) + ' in the filter.',
      FB.chartBox('pl-form', 280, 'Rating per appearance') + FB.chartBox('pl-formxg', 220, 'xG and goals per appearance')) +
    FB.card('Match log', apps.length ? apps.length + ' appearances in the stores, newest first' + (R.archive.length ? '; seasons before the stores are season totals only (Season by season)' : '') + '. A score links to the match centre where a page exists.' : '', '<div id="pl-log"></div>', { flush: true });
  if (!apps.length) {
    chartEmpty(body.querySelector('#pl-form'), 'No appearance in the filter', R.apps.length ? 'Clear the filters to see the match log.' : 'No match log in the stores for this player.');
    body.querySelector('#pl-formxg').style.display = 'none';
    body.querySelector('#pl-log').innerHTML = '';
    return;
  }
  FB.table(body.querySelector('#pl-log'), [
    { key: 'date', label: 'Date', sticky: true, fmt: function (v) { return '<span class="fb-num">' + esc(FB.fmtDate(v, { year: true, weekday: false })) + '</span>'; } },
    { key: 'comp', label: 'Competition', fmt: function (v, r) { return '<span class="fb-comp"><i style="--k:' + FB.kindColor(r.kind) + '"></i>' + esc(compShort(v, names)) + '</span>'; } },
    { key: 'team', label: 'For', fmt: function (v, r) { return teamA(r.tid, v); } },
    { key: 'opp', label: 'Opponent', fmt: function (v, r) { return '<span class="qk-muted">' + (r.home ? 'v' : '@') + '</span> ' + teamA(r.opp_tid, v); } },
    { key: 'res', label: 'Result', fmt: function (v, r) { var t = '<span class="fb-pl-res ' + resClass(v) + '">' + esc(v || '—') + '</span>'; return hasMatchPage(r) ? '<a href="' + esc(FB.href.match(r.comp, r.gid)) + '" title="Match centre">' + t + '</a>' : t; } },
    { key: 'min', label: 'Min', num: true, fmt: function (v, r) { return int(v || 0) + (r.start ? '' : ' <span class="fb-pl-dim" title="Came off the bench">sub</span>'); } },
    { key: 'g', label: 'G', num: true }, { key: 'a', label: 'A', num: true },
    { key: 'xg', label: 'xG', num: true, fmt: function (v) { return nn(v, 2); } }, { key: 'xa', label: 'xA', num: true, fmt: function (v) { return nn(v, 2); } },
    { key: 'sh', label: 'Sh', num: true }, { key: 'kp', label: 'KP', num: true, tip: 'Key passes' },
    { key: 'rt', label: 'Rating', num: true, fmt: function (v) { return isNum(v) ? '<span class="fb-pl-rt" style="--rc:' + FB.charts.ratingColor(v) + '">' + num(v, 1) + '</span>' : '—'; } }
  ], apps.map(function (r) { return FB.merge(r, { team: ((doc.teams || {})[String(r.tid)] || {}).name || FB.clubName(r.tid) }); }), { sort: { key: 'date', dir: 'desc' }, maxHeight: 640, caption: 'Match log' });

  var chron = apps.slice(0, 60).reverse();
  var xs = chron.map(function (r) { return FB.fmtDate(r.date, { weekday: false }); });
  var rts = chron.map(function (r) { return isNum(r.rt) ? r.rt : null; });
  var roll = rts.map(function (v, k) { var w = rts.slice(Math.max(0, k - 4), k + 1).filter(isNum); return w.length ? Math.round(w.reduce(function (s, x) { return s + x; }, 0) / w.length * 100) / 100 : null; });
  var tip = function (i) { var r = chron[i]; return FB.fmtDate(r.date, true) + ' · ' + compShort(r.comp, names) + ' · ' + (r.home ? 'v ' : '@ ') + (r.opp || '') + ' ' + (r.res || ''); };
  QKC.mount(body.querySelector('#pl-form'), function (T) {
    return {
      grid: { left: 8, right: 12, top: 42, bottom: 30, containLabel: true },
      legend: { top: 0, left: 0, icon: 'rect', itemWidth: 12, itemHeight: 4, textStyle: { color: T.ink2, fontFamily: T.fontCond, fontSize: 13, fontWeight: 700 }, data: ['Rating', 'Rolling 5'] },
      xAxis: QKC.axis(T, { type: 'category', data: xs, split: false, line: true, name: 'Match date', nameLocation: 'middle', nameGap: 26 }),
      yAxis: QKC.axis(T, { min: 5, max: 10, fmt: function (v) { return num(v, 0); }, name: 'Sofascore rating', nameAlign: 'left' }),
      tooltip: QKC.tooltip(T, { trigger: 'axis', formatter: function (ps) { var i = ps[0].dataIndex; return '<div style="font-weight:600;margin-bottom:4px">' + esc(tip(i)) + '</div>' + ps.map(function (p) { return QKC.tipRow(p.color, p.seriesName, isNum(p.value) ? num(p.value, 2) : '—'); }).join(''); } }),
      series: [
        { type: 'bar', name: 'Rating', barMaxWidth: 14, data: rts.map(function (v) { return { value: v, itemStyle: { color: FB.charts.ratingColor(v) } }; }) },
        { type: 'line', name: 'Rolling 5', data: roll, showSymbol: false, lineStyle: { width: 2, color: T.ink1 }, itemStyle: { color: T.ink1 } }
      ]
    };
  }, { label: 'Rating per appearance and the rolling five-match mean' });
  QKC.mount(body.querySelector('#pl-formxg'), function (T) {
    return {
      grid: { left: 8, right: 12, top: 42, bottom: 30, containLabel: true },
      legend: { top: 0, left: 0, icon: 'rect', itemWidth: 10, itemHeight: 10, textStyle: { color: T.ink2, fontFamily: T.fontCond, fontSize: 13, fontWeight: 700 } },
      xAxis: QKC.axis(T, { type: 'category', data: xs, split: false, line: true, name: 'Match date', nameLocation: 'middle', nameGap: 26 }),
      yAxis: QKC.axis(T, { min: 0, fmt: function (v) { return num(v, 1); }, name: 'xG and goals', nameAlign: 'left' }),
      tooltip: QKC.tooltip(T, { trigger: 'axis', formatter: function (ps) { var i = ps[0].dataIndex; return '<div style="font-weight:600;margin-bottom:4px">' + esc(tip(i)) + '</div>' + ps.map(function (p) { return QKC.tipRow(p.color, p.seriesName, isNum(p.value) ? num(p.value, 2) : '—'); }).join(''); } }),
      series: [
        { type: 'bar', name: 'xG', barMaxWidth: 14, data: chron.map(function (r) { return isNum(r.xg) ? r.xg : 0; }), itemStyle: { color: T.cat[0] } },
        { type: 'scatter', name: 'Goals', symbolSize: 9, data: chron.map(function (r) { return r.g ? r.g : null; }), itemStyle: { color: T.cat[1], borderColor: T.s1, borderWidth: 1.5 } }
      ]
    };
  }, { label: 'xG and goals per appearance' });
}

// ── profile & shots ───────────────────────────────────────────────────────

function drawShots(el, body, doc, R, q) {
  var lives = [];
  R.seasons.forEach(function (s) { if (s.source === 'live' && compOk(s.comp) && FB.hasFile(s.comp, 'players_live') && lives.indexOf(s.comp) < 0) lives.push(s.comp); });
  lives.sort(function (a, b) { var ma = sum(R.seasons.filter(function (s) { return s.comp === a && s.source === 'live'; }), 'min'), mb = sum(R.seasons.filter(function (s) { return s.comp === b && s.source === 'live'; }), 'min'); return mb - ma; });
  if (!lives.length) { body.innerHTML = FB.empty('No current competition line', 'Percentiles and shot maps come from this season\'s competitions; this player has no line in one this season.'); return; }
  var slug = q.c && lives.indexOf(q.c) >= 0 ? q.c : lives[0];
  body.innerHTML = '<div class="fb-pl-filter">' + (lives.length > 1 ? FB.seg('pl-live', lives.map(function (s) { return [s, FB.compName(s, true)]; }), slug, 'Competition') : '<span class="qk-muted">' + esc(FB.compName(slug)) + ' this season</span>') + '</div>' +
    FB.card('Percentile profile', 'Against the same position in the competition this season: the radar on a dozen headline rates, the card on every metric.', '<div id="pl-prof2">' + FB.loading('chart', 1) + '</div>') +
    FB.grid(FB.card('Shot map', '<span id="pl-shot-sub">Every shot this season in the competition; size by xG.</span>', '<div id="pl-shotmap" class="fb-pl-shotmap"></div>', { span: 7 }) +
      FB.card('Shots by outcome', 'Count and xG by result.', '<div id="pl-shotsum"></div>', { span: 5 }));
  var segBox = body.querySelector('.fb-pl-filter');
  FB.wireSeg(segBox, 'pl-live', function (v) { FB.setQuery({ c: v }); drawShots(el, body, doc, R, FB.merge(q, { c: v })); });
  profileCard(el, body.querySelector('#pl-prof2'), doc, slug, false);
  var sp = FB.hasFile(slug, 'shots') ? FB.compFile(slug, 'shots') : Promise.resolve(null);
  sp.then(function (d) {
    var box = body.querySelector('#pl-shotmap');
    if (!box || !box.isConnected) return;
    var entry = null;
    var players = (d || {}).players || {};
    Object.keys(players).some(function (k) { if (String(players[k].player_id) === String(doc.id)) { entry = players[k]; return true; } return false; });
    var shots = entry ? (entry.shots || []).map(function (s) { return FB.merge(s, { name: s.match || doc.name, side: 'home' }); }) : [];
    if (!shots.length) { box.innerHTML = FB.empty('No shots recorded', doc.pos === 'G' ? 'Goalkeepers rarely shoot.' : 'No shot locations for the player in this competition yet.'); body.querySelector('#pl-shotsum').innerHTML = ''; return; }
    FB.charts.shotMap(box, shots, { surface: 'half', label: 'Shot map, ' + doc.name + ', ' + FB.compName(slug) });
    var tot = shots.reduce(function (s, x) { return s + (x.xg || 0); }, 0);
    var goals = shots.filter(function (s) { return FB.charts.outcomeOf(s) === 'goal'; }).length;
    FB.set('pl-shot-sub', shots.length + ' shots · ' + num(tot, 2) + ' xG · ' + goals + ' goals · ' + num(tot / shots.length, 2) + ' xG per shot');
    var by = FB.charts.OUTCOMES.map(function (o) { var ss = shots.filter(function (s) { return FB.charts.outcomeOf(s) === o[0]; }); return { o: o[1], n: ss.length, xg: ss.reduce(function (a, x) { return a + (x.xg || 0); }, 0) }; }).filter(function (x) { return x.n; });
    var sumBox = body.querySelector('#pl-shotsum');
    sumBox.innerHTML = FB.kpis([FB.kpi('Shots', String(shots.length)), FB.kpi('Goals', String(goals), { sub: 'xG ' + num(tot, 1) }), FB.kpi('xG per shot', num(tot / shots.length, 2))]) + '<div class="fb-mt" id="pl-shotbars"></div>';
    var sb = sumBox.querySelector('#pl-shotbars');
    sb.style.height = '220px';
    QKC.bar(sb, { horizontal: true, labels: true, cats: by.map(function (x) { return x.o; }), valName: 'Shots', series: [{ name: 'Shots', data: by.map(function (x) { return x.n; }) }], fmt: function (v) { return int(v); }, label: 'Shots by outcome' });
  });
}

// ── transfers ─────────────────────────────────────────────────────────────

function drawTransfers(el, body, doc) {
  body.innerHTML = FB.card('Transfer history', 'Moves Sofascore lists for the player in the last ~400 days involving a followed club, with the site\'s fair fee at the time and the deal grades (buyer, seller). <a href="#/value/transfers">Every transfer →</a>', '<div id="pl-tr">' + FB.loading('lines', 4) + '</div>', { flush: true });
  FB.load('value/transfers.json').then(function (t) {
    var box = body.querySelector('#pl-tr');
    if (!box || !box.isConnected) return;
    var rows = FB.rows(t).filter(function (r) { return String(r.pid) === String(doc.id); });
    (doc.transfers || []).forEach(function (x) {
      if (!rows.some(function (r) { return r.date === x.date && String(r.to) === String(x.to_tid); })) rows.push({ date: x.date, from: x.from_tid, from_name: x.from, to: x.to_tid, to_name: x.to, kind: x.type, fee: x.fee, fee_text: x.fee_text });
    });
    if (!rows.length) { box.innerHTML = '<div class="fb-pl-pad">' + FB.empty('No recorded move', 'No transfer involving a followed club in the window the site keeps.') + '</div>'; return; }
    var KL = { fee: 'Transfer', free: 'Free', undisclosed: 'Undisclosed fee', youth: 'From the youth side', loan: 'Loan', loan_end: 'Loan return' };
    FB.table(box, [
      { key: 'date', label: 'Date', sticky: true, fmt: function (v) { return '<span class="fb-num">' + esc(FB.fmtDate(v, { year: true, weekday: false })) + '</span>'; } },
      { key: 'from_name', label: 'From', fmt: function (v, r) { return teamA(r.from, v); } },
      { key: 'to_name', label: 'To', fmt: function (v, r) { return '→ ' + teamA(r.to, v); } },
      { key: 'kind', label: 'Type', fmt: function (v) { return esc(KL[v] || v || '—'); } },
      { key: 'fee', label: 'Fee', num: true, fmt: function (v, r) { return isNum(v) ? FB.money(v) : esc(r.fee_text && r.fee_text !== '-' ? r.fee_text : '—'); } },
      { key: 'fair', label: 'Fair fee', num: true, tip: 'The site\'s fair fee at the time of the move', fmt: function (v) { return isNum(v) ? FB.money(v) : '—'; } },
      { key: 'b_grade', label: 'Buyer', tip: 'Deal grade for the buying club', fmt: function (v) { return v ? '<span class="fb-pl-grade g-' + esc(v) + '">' + esc(v) + '</span>' : '—'; } },
      { key: 's_grade', label: 'Seller', tip: 'Deal grade for the selling club', fmt: function (v) { return v ? '<span class="fb-pl-grade g-' + esc(v) + '">' + esc(v) + '</span>' : '—'; } },
      { key: 'post_min', label: 'Min since', num: true, fmt: function (v) { return isNum(v) ? int(v) : '—'; } }
    ], rows, { sort: { key: 'date', dir: 'desc' }, caption: 'Transfers' });
  });
}

})(window.FB);
