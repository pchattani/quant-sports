/* The Quant Footballer — Players: find a player, leaders across competitions, and ONE page per player across every
 * competition he plays, season by season.
 *
 *   #/players                     search the people index (position, nationality, competition, club or name), the
 *                                 most-played players this season, leader cards (data/lab/leaders.json) and the value leaders
 *   #/players/leaders             one row per player over every competition, club football, his national team or one
 *                                 competition, this season, last season or a calendar window (data/lab/, UNIFIED_PAYLOADS
 *                                 14), raw and league-adjusted rates, percentiles
 *   #/player/<pid>[?tab=overview|seasons|matches|shots|transfers&scope=club|intl&c=<slug>&e=<era>]
 *                                 the player: hero, this season, season by season (years, each season's competitions
 *                                 nested, coverage chips), charts, value, the match log with form, percentiles and the
 *                                 shot map per competition, transfers. Filters live in the query.
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
    'One record per player, however many competitions he plays in: search the registry, see who has played most this season, and open any player for his season-by-season career.') +
    playersNav('find') +
    '<div id="pl-leadscope" class="fb-pl-leadscope"></div><div class="fb-pl-leadgrid" id="pl-leads">' + FB.card('Goals', 'This season, every competition', FB.loading('lines', 5)) + FB.card('Assists', '', FB.loading('lines', 5)) + FB.card('Rating', '450+ minutes', FB.loading('lines', 5)) + '</div>' +
    FB.card('Find a player', '<span id="pl-count">Loading the registry…</span>',
      '<div id="pl-tools"></div><div id="pl-table">' + FB.loading('lines', 8) + '</div>', { flush: false }) +
    FB.grid(FB.card('Value leaders', 'Goals above replacement (GAR) over the last 12 months of club football: the goals a player adds over a freely available replacement in his role. <a href="#/value">Full value leaderboard →</a>',
      FB.chartBox('pl-gar', 380, 'Top players by goals above replacement'), { span: 7 }) +
      FB.card('Most valuable', 'Sofascore market value (reference only), current squads.', '<div id="pl-mv">' + FB.loading('lines', 6) + '</div>', { span: 5 }));

  FB.load('lab/leaders.json').then(function (board) {
    if (!FB.alive(el)) return;
    if (board && board.scopes) { drawLeadCards(el, board, null); return; }
    FB.load('hub.json').then(function (h) { if (FB.alive(el)) drawLeadCards(el, null, h); });
  });
  var people = FB.peopleIndex().then(function (pi) {
    if (!FB.alive(el)) return;
    drawFinder(el, pi.list, q);
    drawMostValuable(el, pi.list);
  });
  FB.load('value/players.json').then(function (v) { if (FB.alive(el)) drawGar(el, v); });
  return people;
});

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
    sub = 'This season, his best competition';
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
  box.innerHTML =
    FB.card('Goals', esc(sub), list(L.goals, function (v) { return int(v); }, function (r) { return isNum(r.xg) ? 'xG ' + num(r.xg, 1) : ''; })) +
    FB.card('Assists', esc(sub), list(L.assists, function (v) { return int(v); }, function (r) { return isNum(r.xa) ? 'xA ' + num(r.xa, 1) : ''; })) +
    FB.card('Rating', '450+ minutes, minutes-weighted · ' + esc(sub.replace(/^This season, /, '')), list(L.rating, function (v) { return num(v, 2); }, function (r) { return int(r.minutes) + ' min'; }));
  if (scopes && segBox) FB.wireSeg(segBox, 'pl-lead-scope', function (v) { LEAD_SCOPE = v; drawLeadCards(el, board, hub); });
}

var FIND = { q: '', pos: '', nat: '', comp: '', min: 0 };
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
      return { id: r.id, name: r.name, pos: r.pos, age: FB.ageOf(r.dob), nat: r.nat, club: r.club, club_tid: r.club_tid, nt: r.nt, nt_tid: r.nt_tid, season: r.season, min: r.min || 0, mv: r.mv, nc: (r.comps || []).length, _n: out.length };
    });
  }
  function draw() {
    var rows = rowsNow();
    FB.set('pl-count', (rows.length ? int(rows[0]._n) : '0') + ' players match' + (rows.length && rows[0]._n > 300 ? ' (the 300 with most minutes this season shown)' : '') + ' · ' + int(list.length) + ' in the registry · minutes are each player’s own season (a calendar 2026 is near its end, a 2026/27 is weeks old)');
    var cols = [
      { key: 'name', label: 'Player', sticky: true, fmt: function (v, r) { return '<span class="fb-pl-who">' + FB.playerLink(r.id, v) + ' ' + FB.posBadge(r.pos) + '</span>'; } },
      { key: 'age', label: 'Age', num: true },
      { key: 'club', label: 'Club', fmt: function (v, r) { return v ? teamA(r.club_tid, v) : '<span class="qk-muted">—</span>'; } },
      { key: 'nt', label: 'National team', fmt: function (v, r) { return v ? teamA(r.nt_tid, v) : '<span class="qk-muted">' + esc(r.nat || '—') + '</span>'; } },
      { key: 'min', label: 'Minutes', num: true, tip: 'Minutes in the player\'s current season (his own frame: 2026/27 for a European, 2026 for a Brazilian), every competition.', fmt: function (v, r) { return int(v) + ' <span class="qk-muted fb-pl-era">' + esc(r.season || '') + '</span>'; } },
      { key: 'mv', label: 'Value', num: true, tip: 'Sofascore\'s market value, reference only.', fmt: function (v) { return isNum(v) ? FB.money(v) : '—'; } },
      { key: 'nc', label: 'Comps', num: true, tip: 'Competitions he has played in across the stores.' }
    ];
    if (handle) handle.setRows(rows); else handle = FB.table(el.querySelector('#pl-table'), cols, rows, { sort: { key: 'min', dir: 'desc' }, maxHeight: 620, caption: 'Players' });
  }
  draw();
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
    series: [{ name: 'Goals above replacement', data: rows.map(function (r) { return Math.round(r.gar * 10) / 10; }), color: QK.cssVar('--accent') }],
    hrefs: rows.map(function (r) { return FB.href.player(r.id); }), label: 'Goals above replacement, last 12 months'
  });
}

// ── #/players/leaders ─────────────────────────────────────────────────────

/* One row per player (data/lab/<window>/<scope>.json): every competition, club football, national-team football or
   one competition, this season, last season or a calendar window. Attacking rates can be league-adjusted (the row's
   minutes-weighted scoring factor); percentiles are against the same position in the view, over its floor. */
var LD_WIN = [['season', 'This season'], ['last', 'Last season'], ['365', 'Last 12 months'], ['ytd', 'Calendar year so far']];
function renderLeaders(el, p) {
  var q = p.query || {};
  el.innerHTML = FB.pageHead('Players', 'Leaders across competitions',
    'Every player once: his minutes and rates over every competition he played, club football only, his national team only, or one competition. Attacking rates can be league-adjusted with the pooled model\'s scoring factors so output from different leagues sits on one footing.') +
    playersNav('leaders') +
    '<div id="ld-body">' + FB.card('Loading the board', '', FB.loading('lines', 10)) + '</div>';
  var st = { win: q.w || 'season', scope: q.c || q.scope || 'all', pos: q.pos || '', min: isNum(Number(q.min)) && q.min !== undefined && q.min !== '' ? Number(q.min) : null, key: q.m || 'npxg_90_adj' };
  return FB.labIndex().then(function (ix) {
    if (!FB.alive(el)) return;
    var body = el.querySelector('#ld-body');
    if (!ix || !ix.scopes) { body.innerHTML = FB.empty('No board yet', 'The leaderboards (data/lab/) are rebuilt with the site.'); return; }
    if (!ix.scopes[st.win]) st.win = 'season';
    var metrics = ix.metrics || [], adjusted = ix.adjusted_keys || [];
    body.innerHTML = FB.card('<span id="ld-title">Leaders</span>', '<span id="ld-sub"></span>',
      '<div id="ld-tools"></div>' + FB.chartBox('ld-chart', 420, 'Top 15 on the chosen metric') + '<div id="ld-table" class="fb-mt"></div>');
    var V = null;
    function single() { return !FB.LAB_SCOPES[st.scope]; }
    function metricOpts(scope) {
      var groups = [];
      metrics.filter(function (m) { return scope === 'all' || m.scope === 'all' || m.scope === scope; }).forEach(function (m) {
        var gr = groups.filter(function (x) { return x.group === m.group; })[0];
        if (!gr) { gr = { group: m.group, items: [] }; groups.push(gr); }
        gr.items.push([m.key, m.label]);
        if (adjusted.indexOf(m.key) >= 0 && !single()) gr.items.push([m.key + '_adj', m.label + ' (league-adjusted)']);
      });
      return groups;
    }
    function tools() {
      var scope = st.pos === 'G' ? 'gk' : st.pos ? 'out' : 'all';
      var groups = metricOpts(scope);
      var keys = [];
      groups.forEach(function (gr) { gr.items.forEach(function (i) { keys.push(i[0]); }); });
      if (keys.indexOf(st.key) < 0) st.key = keys.indexOf(st.key.replace(/_adj$/, '')) >= 0 ? st.key.replace(/_adj$/, '') : (scope === 'gk' ? 'saves_90' : (single() ? 'npxg_90' : 'npxg_90_adj'));
      el.querySelector('#ld-tools').innerHTML = FB.toolbar([
        FB.field('Season', FB.select('ld-w', LD_WIN.filter(function (w) { return ix.scopes[w[0]]; }), st.win, 'Season or window')),
        FB.field('Competitions', FB.select('ld-c', FB.labScopeOptions(ix, st.win), st.scope, 'Which competitions count', 'fb-pl-wide')),
        FB.field('Metric', FB.select('ld-m', groups, st.key, 'Metric', 'fb-pl-wide')),
        FB.field('Position', FB.seg('ld-pos', [['', 'All'], ['G', 'GK'], ['D', 'DEF'], ['M', 'MID'], ['F', 'FWD']], st.pos, 'Position')),
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
      return FB.labView(st.win, st.scope).then(function (v) {
        if (!FB.alive(el)) return;
        V = v;
        if (!V) { FB.set('ld-table', FB.empty('No board for this view', 'Try another season or set of competitions.')); return; }
        if (st.min === null) st.min = Math.max(90, single() ? V.floor : Math.min(V.floor, 450));
        tools(); sync(); draw();
      });
    }
    function draw() {
      if (!V) return;
      var I = V.idx, key = st.key, base = key.replace(/_adj$/, ''), adj = /_adj$/.test(key);
      var metric = metrics.filter(function (m) { return m.key === base; })[0] || { fmt: '2', label: key };
      var value = function (r) { var v = I[base] === undefined ? null : r[I[base]]; return isNum(v) ? (adj ? v * (r[I.factor] || 1) : v) : null; };
      var inPos = function (r) { return !st.pos || r[I.position] === st.pos; };
      var floorRows = V.rows.filter(function (r) { return (r[I.minutes] || 0) >= st.min && inPos(r) && isNum(value(r)); });
      var sorted = floorRows.map(value).sort(function (a, b) { return a - b; });
      var pctOf = function (v) {
        var lo = 0, hi = sorted.length; while (lo < hi) { var mid = (lo + hi) >> 1; if (sorted[mid] < v) lo = mid + 1; else hi = mid; }
        var up = lo; while (up < sorted.length && sorted[up] === v) up++;
        var rank = sorted.length ? (lo + 0.5 * (up - lo)) / sorted.length : null;
        return rank === null ? null : Math.round(100 * (metric.lower ? 1 - rank : rank));
      };
      var rows = floorRows.slice().sort(function (a, b) { return metric.lower ? value(a) - value(b) : value(b) - value(a); }).slice(0, 100);
      var per = function (r, k) { var v = r[I[k]]; return isNum(v) ? Math.round(v * (r[I.minutes] || 0) / 90) : null; };
      var data = rows.map(function (r, i) {
        var v = value(r);
        return { i: i + 1, id: r[I.player_id], name: r[I.name], team: r[I.team], tid: r[I.tid], comp: r[I.comp], mix: r[I.mix], pos: r[I.position], age: r[I.age], min: r[I.minutes],
          v: v, raw: r[I[base]], f: r[I.factor], pct: pctOf(v), g: per(r, 'goals_90'), a: per(r, 'assists_90'), rt: r[I.rating] };
      });
      var lab = (metric.label || key) + (adj ? ' (adj.)' : '');
      var W = (ix.windows || []).filter(function (w) { return w.key === st.win; })[0];
      FB.set('ld-title', esc(lab) + ': ' + esc(FB.labScopeName(st.scope, ix).toLowerCase()));
      FB.set('ld-sub', FB.int(floorRows.length) + ' players over ' + st.min + ' minutes · ' + esc(FB.labWindowText(W)) + ' · one row per player' +
        (single() ? '' : ', his minutes summed across ' + (st.scope === 'intl' ? 'national-team football' : st.scope === 'club' ? 'club competitions' : 'every competition')) +
        '. Percentiles are against the players shown (the same position when one is picked).');
      var personQ = single() ? { c: st.scope } : st.scope === 'club' ? { scope: 'club' } : st.scope === 'intl' ? { scope: 'intl' } : null;
      FB.table(el.querySelector('#ld-table'), [
        { key: 'i', label: '#', num: true },
        { key: 'name', label: 'Player', sticky: true, fmt: function (v, r) { return '<span class="fb-pl-who"><a class="fb-link" href="' + esc(FB.href.player(r.id, personQ)) + '">' + esc(v) + '</a> ' + FB.posBadge(r.pos) + '</span>'; } },
        { key: 'team', label: st.scope === 'intl' ? 'National team' : 'Club', fmt: function (v, r) { return teamA(r.tid, v); } },
        { key: 'mix', label: single() ? 'Competition' : 'Competitions (minutes)', fmt: function (v, r) { return single() ? FB.compLink(st.scope, { short: true }) : '<span class="qk-muted fb-lb-mix">' + esc(v || '') + '</span>'; } },
        { key: 'age', label: 'Age', num: true }, { key: 'min', label: 'Min', num: true },
        { key: 'v', label: lab, num: true, fmt: function (v) { return '<b>' + FB.fmtMetric(v, metric.fmt) + '</b>'; } },
        { key: 'raw', label: 'Raw', num: true, tip: 'Before the league adjustment', fmt: function (v) { return adj ? FB.fmtMetric(v, metric.fmt) : '—'; } },
        { key: 'f', label: 'Factor', num: true, tip: 'The scoring factor (pooled model), minutes-weighted over the competitions he played', fmt: function (v) { return nn(v, 2); } },
        { key: 'pct', label: 'Pctl', num: true, tip: 'Percentile among the players shown', fmt: function (v) { return isNum(v) ? FB.pctl(v) : '—'; } },
        { key: 'g', label: 'G', num: true }, { key: 'a', label: 'A', num: true }, { key: 'rt', label: 'Rating', num: true, fmt: function (v) { return nn(v, 2); } }
      ], data, { maxHeight: 640, caption: 'Leaders' });
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

  // hero
  var meta = [];
  if (doc.nat) meta.push('<span>' + esc(doc.nat) + '</span>');
  if (age) meta.push('<span>Age <b>' + age + '</b></span>');
  if (doc.height) meta.push('<span><b>' + doc.height + '</b> cm</span>');
  if (doc.foot) meta.push('<span>' + esc(doc.foot) + ' foot</span>');
  if (doc.shirt) meta.push('<span>Shirt <b>#' + esc(doc.shirt) + '</b></span>');
  if (doc.until) meta.push('<span data-tip="Contract end, as Sofascore lists it">Contract <b>' + esc(String(doc.until).slice(0, 7)) + '</b></span>');
  var clubLine = cc && cc.name
    ? monoLink(cc.tid, cc.name) + (cc.source === 'appearances' ? ' <span class="qk-muted" data-tip="From his latest club appearance, not a squad list">(latest appearance)</span>' : cc.source === 'profile' ? ' <span class="qk-muted" data-tip="From his Sofascore profile">(profile)</span>' : '')
    : '<span class="qk-muted">No current club on record</span>';
  var ntLine = nt && nt.name ? monoLink(nt.tid, nt.name) : '';
  var stats = [];
  if (isNum(doc.mv)) stats.push(['Market value', FB.money(doc.mv, doc.mvc)]);
  if (cur) { stats.push([curEra + ' goals', int(cur.g || 0)]); stats.push(['Assists', int(cur.a || 0)]); stats.push(['Minutes', int(cur.min || 0)]); }
  var hero = '<section class="qk-hero fb-pl-hero"><div class="qk-hero-in">' +
    '<div class="qk-avatar fb-pl-av">' + esc(FB.initials(doc.name)) + '</div>' +
    '<div class="fb-pl-hero-main"><div class="qk-kicker">' + esc(posLabel(doc.pos)) + (cc && cc.as_of ? ' · squad as of ' + esc(FB.fmtDate(cc.as_of, true)) : '') + '</div>' +
    '<h1>' + esc(doc.name || 'Player ' + doc.id) + '</h1>' +
    '<div class="fb-pl-clubs">' + clubLine + (ntLine ? '<span class="fb-pl-sep">·</span>' + ntLine + ' <span class="fb-kind" style="--k:' + FB.kindColor('international') + '">National team</span>' : '') + '</div>' +
    '<div class="qk-hero-meta">' + meta.join('') + '</div></div>' +
    (stats.length ? '<div class="qk-hero-stats">' + stats.map(function (s) { return '<div class="qk-hero-stat"><div class="v">' + esc(s[1]) + '</div><div class="l">' + esc(s[0]) + '</div></div>'; }).join('') + '</div>' : '') +
    '</div></section>';

  var base = '#/player/' + FB.enc(doc.id);
  var keepQs = function (t) { return base + FB.qs({ tab: t === 'overview' ? null : t, scope: q.scope, c: q.c, e: q.e }); };
  el.innerHTML = hero + FB.subnav(TABS.map(function (t) { return [keepQs(t[0]), t[1], t[0]]; }), tab, 'Player') +
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
  }
  redraw(q);
}

function linksLine(doc, R) {
  var best = R.seasons.filter(function (s) { return s.source === 'live' && compOk(s.comp); }).sort(function (a, b) { return (b.min || 0) - (a.min || 0); })[0];
  var bits = [];
  if (best) {
    bits.push('<a href="#/compare/players/' + esc(best.comp) + ':' + esc(doc.id) + '">Compare this player →</a>');
    bits.push('<a href="#/lab/' + esc(best.comp) + '/' + esc(doc.pos === 'G' ? 'G' : (doc.pos || 'M')) + '">Player lab →</a>');
  }
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
      rt: wavg(rr, 'rt'), intlMin: sum(intl, 'min'), clubMin: sum(rr, 'min') - sum(intl, 'min'),
      partial: rr.some(function (r) { return r.coverage === 'partial' || r.coverage === 'none'; }), totals: rr.some(function (r) { return r.coverage === 'totals'; })
    };
  }).sort(function (a, b) { return eraKey(b.era) - eraKey(a.era); });
}

// ── overview ──────────────────────────────────────────────────────────────

function drawOverview(el, body, doc, R, q) {
  var keep = keepQ(q);
  var rows = R.all.filter(keep);
  var filtered = !!(q.scope || q.c || q.e);
  var Y = byYear(rows);
  var curEra = q.e || ((doc.years || [])[0] || {}).era || (Y[0] || {}).era;
  var cy = Y.filter(function (y) { return y.era === curEra; })[0] || null;
  var label = filterLabel(q, doc.comps);
  var tiles = cy ? [
    FB.kpi('Appearances', int(cy.apps) + (cy.starts ? ' <span class="fb-pl-dim">' + cy.starts + ' st</span>' : ''), { sub: int(cy.min) + ' minutes' }),
    FB.kpi('Goals', int(cy.g), { sub: isNum(cy.xg) ? 'xG ' + num(cy.xg, 1) : '' }),
    FB.kpi('Assists', int(cy.a), { sub: isNum(cy.xa) ? 'xA ' + num(cy.xa, 1) : '' }),
    FB.kpi('G+A per 90', nn(per90(cy.g + cy.a, cy.min), 2), { sub: nn(per90(cy.g, cy.min), 2) + ' goals per 90' }),
    FB.kpi('Rating', nn(cy.rt, 2), { sub: 'minutes-weighted' }),
    FB.kpi('Club / international', int(cy.clubMin) + ' <span class="fb-pl-dim">/ ' + int(cy.intlMin) + '</span>', { sub: 'minutes · ' + cy.rows.length + ' competition' + (cy.rows.length === 1 ? '' : 's') })
  ] : [];
  body.innerHTML =
    '<div class="fb-pl-kpihead"><h2 class="fb-pl-h2">' + esc(curEra || 'This season') + '</h2><span class="qk-muted">' + esc(label) + (cy && (cy.partial || cy.totals) ? ' · ' : '') + (cy && cy.partial ? '<span class="fb-cov partial" data-tip="At least one competition this season is a lower bound: line-ups are missing for some of his team\'s matches.">Partial</span>' : '') + '</span></div>' +
    (tiles.length ? FB.kpis(tiles) : FB.empty('No season in the filter', 'Clear the filters to see his career.')) +
    FB.grid(
      FB.card('Goals and assists by season', 'Stacked by competition kind' + (filtered ? ', in the filter' : '') + '.', FB.chartBox('pl-ga', 300, 'Goals and assists by season'), { span: 6 }) +
      FB.card('Minutes by season', 'Where the minutes came from: league, continental, cups, international.', FB.chartBox('pl-min', 300, 'Minutes by season'), { span: 6 }) +
      FB.card('Goals against xG', 'Per season, where the stores carry xG (archive seasons are totals without xG).', FB.chartBox('pl-xg', 280, 'Goals and xG by season'), { span: 6 }) +
      FB.card('Rating by season', 'Minutes-weighted Sofascore rating across the season\'s competitions.', FB.chartBox('pl-rt', 280, 'Rating by season'), { span: 6 })
    ) +
    FB.card('Season by season', 'Every competition he played, summed per season' + (doc.frame === 'calendar' ? ' (calendar years, as his club football runs)' : ' (July to June; international matches count in the season they are played in)') +
      '. Open a season for its competitions. <a href="' + esc('#/player/' + FB.enc(doc.id) + FB.qs({ tab: 'seasons', scope: q.scope, c: q.c, e: q.e })) + '">Full career table →</a>', '<div id="pl-years"></div>', { flush: true }) +
    FB.grid(
      FB.card('Value', 'From the site\'s value model, last 12 months of club football. <a href="#/value">How it works →</a>', '<div id="pl-value">' + FB.loading('lines', 4) + '</div>', { span: 6 }) +
      FB.card('Profile', '<span id="pl-prof-sub">Percentiles against positional peers in his main competition this season.</span>', '<div id="pl-prof">' + FB.loading('chart', 1) + '</div>', { span: 6 })
    );
  yearsTable(body.querySelector('#pl-years'), Y, doc, 2);
  seasonCharts(body, Y);
  drawValue(body, doc);
  var main = R.seasons.filter(function (s) { return s.source === 'live' && compOk(s.comp) && FB.hasFile(s.comp, 'players_live'); }).sort(function (a, b) { return (b.min || 0) - (a.min || 0); });
  var pick = q.c ? main.filter(function (s) { return s.comp === q.c; })[0] : main[0];
  if (pick) profileCard(el, body.querySelector('#pl-prof'), doc, pick.comp, true);
  else body.querySelector('#pl-prof').innerHTML = FB.muted('No line in a competition with percentiles this season.');
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
      '<td>' + (gapThrough && eraKey(y.era) <= eraKey(gapThrough) ? '<span class="fb-cov partial" data-tip="His career list from Sofascore is still being backfilled: competitions from this season and older may be missing, so the season is a lower bound.">Partial</span>' : y.partial ? '<span class="fb-cov partial" data-tip="At least one competition this season is a lower bound (line-ups missing).">Partial</span>' : y.totals ? '<span class="fb-cov totals" data-tip="Includes Sofascore season totals where our line-ups were incomplete.">Totals</span>' : '<span class="fb-cov full">Full</span>') + '</td></tr>';
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
  QKC.line(boxes[2], { x: eras, legend: true, endLabels: false, yMin: 0, yFmt: function (v) { return num(v, 0); }, xName: 'Season', yName: 'Goals and xG', label: 'Goals against xG by season',
    series: [{ name: 'Goals', color: QK.cssVar('--accent'), data: ys.map(function (y) { return y.g; }) }].concat(xgOk ? [{ name: 'xG', color: QK.cssVar('--c-1'), dash: true, data: ys.map(function (y) { return isNum(y.xg) ? Math.round(y.xg * 10) / 10 : null; }) }] : []) });
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
        FB.kpi('GAR / 90', FB.signed(row.gar90, 2), { tip: 'Goals above replacement per 90 minutes, last 12 months of club football', sub: isNum(row.pct) ? FB.ordinal(row.pct) + ' percentile among ' + esc(roles[row.role] || row.role || '') + 's' : esc(roles[row.role] || row.role || '') }),
        FB.kpi('GAR', FB.signed(row.gar, 1), { sub: int(row.min) + ' min · PAR ' + FB.signed(row.par, 1) + ' pts' }),
        FB.kpi('Fair value', isNum(row.v2) ? num(row.v2, 1) : '—', { tip: 'Valuation v2: expected points above replacement over four seasons (10-90% band)', sub: isNum(row.v2lo) ? num(row.v2lo, 1) + '–' + num(row.v2hi, 1) + ' pts' : '' }),
        FB.kpi('Fair fee', isNum(row.fee) ? FB.money(row.fee) : '—', { tip: 'Fair fee to a buyer like his own club (fee model)', sub: isNum(row.feelo) ? FB.money(row.feelo) + '–' + FB.money(row.feehi) : (isNum(row.mv) ? 'market value ' + FB.money(row.mv) : '') })
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
    if (!p) { box.innerHTML = FB.muted('No line for him in ' + esc(FB.compName(slug)) + ' this season.'); return; }
    var metrics = (live.metrics || []).filter(function (m) { return m.pct && (m.scope === 'all' || m.scope === (p.is_gk ? 'gk' : 'out')); });
    var pos = (live.positions || {})[p.position] || (p.is_gk ? 'Goalkeeper' : 'Outfield player');
    var hasP = p.pct && Object.keys(p.pct).length;
    var sub = esc(FB.compName(slug)) + ' ' + esc(FB.currentSeason(FB.comp(slug)).season || '') + ' · against ' + esc(String(pos).toLowerCase()) + 's with ' + (live.minutes_floor || 0) + '+ minutes';
    if (!hasP) { box.innerHTML = '<p class="fb-cap">' + sub + '</p>' + FB.empty('Not enough minutes yet', 'Percentiles appear once he passes ' + (live.minutes_floor || 0) + ' minutes in this competition (' + int(p.minutes) + ' so far).'); return; }
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
      g.items.push({ label: m.label + (m.lower ? ' ↓' : ''), pctl: p.pct[m.key], value: FB.fmtMetric(p[m.key], m.fmt) });
    });
    box.innerHTML = '<p class="fb-cap fb-pl-cap0">' + sub + '. Higher is better; ↓ marks counts where fewer is better (already turned round).</p>' +
      '<div class="fb-pl-prof">' + '<div class="fb-pl-radarwrap">' + FB.chartBox('pl-radar', 360, 'Percentile profile') + '</div>' +
      '<div class="fb-pl-groups">' + groups.map(function (g) { return '<div class="fb-pl-group"><div class="qk-kicker">' + esc(g.name) + '</div>' + QK.pctlBars(g.items) + '</div>'; }).join('') + '</div></div>';
    if (radarAxes.length >= 3) FB.charts.radar(box.querySelector('#pl-radar'), { axes: radarAxes.map(function (a) { return { name: a[1], max: 100 }; }), series: [{ name: doc.name, values: radarAxes.map(function (a) { return p.pct[a[0]]; }), color: QK.cssVar('--accent') }], label: 'Percentile radar, ' + FB.compName(slug) });
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
    chartEmpty(body.querySelector('#pl-form'), 'No appearance in the filter', R.apps.length ? 'Clear the filters to see his match log.' : 'No match log in the stores for this player.');
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
      legend: { top: 0, left: 0, icon: 'roundRect', itemWidth: 12, itemHeight: 4, textStyle: { color: T.ink2 }, data: ['Rating', 'Rolling 5'] },
      xAxis: QKC.axis(T, { type: 'category', data: xs, split: false, line: true, name: 'Match date', nameLocation: 'middle', nameGap: 26 }),
      yAxis: QKC.axis(T, { min: 5, max: 10, fmt: function (v) { return num(v, 0); }, name: 'Sofascore rating', nameAlign: 'left' }),
      tooltip: QKC.tooltip(T, { trigger: 'axis', formatter: function (ps) { var i = ps[0].dataIndex; return '<div style="font-weight:600;margin-bottom:4px">' + esc(tip(i)) + '</div>' + ps.map(function (p) { return QKC.tipRow(p.color, p.seriesName, isNum(p.value) ? num(p.value, 2) : '—'); }).join(''); } }),
      series: [
        { type: 'bar', name: 'Rating', barMaxWidth: 14, data: rts.map(function (v) { return { value: v, itemStyle: { color: FB.charts.ratingColor(v), borderRadius: [3, 3, 0, 0] } }; }) },
        { type: 'line', name: 'Rolling 5', data: roll, showSymbol: false, lineStyle: { width: 2, color: T.ink1 }, itemStyle: { color: T.ink1 } }
      ]
    };
  }, { label: 'Rating per appearance and the rolling five-match mean' });
  QKC.mount(body.querySelector('#pl-formxg'), function (T) {
    return {
      grid: { left: 8, right: 12, top: 42, bottom: 30, containLabel: true },
      legend: { top: 0, left: 0, icon: 'roundRect', itemWidth: 10, itemHeight: 10, textStyle: { color: T.ink2 } },
      xAxis: QKC.axis(T, { type: 'category', data: xs, split: false, line: true, name: 'Match date', nameLocation: 'middle', nameGap: 26 }),
      yAxis: QKC.axis(T, { min: 0, fmt: function (v) { return num(v, 1); }, name: 'xG and goals', nameAlign: 'left' }),
      tooltip: QKC.tooltip(T, { trigger: 'axis', formatter: function (ps) { var i = ps[0].dataIndex; return '<div style="font-weight:600;margin-bottom:4px">' + esc(tip(i)) + '</div>' + ps.map(function (p) { return QKC.tipRow(p.color, p.seriesName, isNum(p.value) ? num(p.value, 2) : '—'); }).join(''); } }),
      series: [
        { type: 'bar', name: 'xG', barMaxWidth: 14, data: chron.map(function (r) { return isNum(r.xg) ? r.xg : 0; }), itemStyle: { color: T.model, borderRadius: [3, 3, 0, 0] } },
        { type: 'scatter', name: 'Goals', symbolSize: 9, data: chron.map(function (r) { return r.g ? r.g : null; }), itemStyle: { color: T.accent, borderColor: T.s1, borderWidth: 1.5 } }
      ]
    };
  }, { label: 'xG and goals per appearance' });
}

// ── profile & shots ───────────────────────────────────────────────────────

function drawShots(el, body, doc, R, q) {
  var lives = [];
  R.seasons.forEach(function (s) { if (s.source === 'live' && compOk(s.comp) && FB.hasFile(s.comp, 'players_live') && lives.indexOf(s.comp) < 0) lives.push(s.comp); });
  lives.sort(function (a, b) { var ma = sum(R.seasons.filter(function (s) { return s.comp === a && s.source === 'live'; }), 'min'), mb = sum(R.seasons.filter(function (s) { return s.comp === b && s.source === 'live'; }), 'min'); return mb - ma; });
  if (!lives.length) { body.innerHTML = FB.empty('No current competition line', 'Percentiles and shot maps come from this season\'s competitions; he has no line in one this season.'); return; }
  var slug = q.c && lives.indexOf(q.c) >= 0 ? q.c : lives[0];
  body.innerHTML = '<div class="fb-pl-filter">' + (lives.length > 1 ? FB.seg('pl-live', lives.map(function (s) { return [s, FB.compName(s, true)]; }), slug, 'Competition') : '<span class="qk-muted">' + esc(FB.compName(slug)) + ' this season</span>') + '</div>' +
    FB.card('Percentile profile', 'Against positional peers in the competition.', '<div id="pl-prof2">' + FB.loading('chart', 1) + '</div>') +
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
    if (!shots.length) { box.innerHTML = FB.empty('No shots recorded', doc.pos === 'G' ? 'Goalkeepers rarely shoot.' : 'No shot locations for him in this competition yet.'); body.querySelector('#pl-shotsum').innerHTML = ''; return; }
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
  body.innerHTML = FB.card('Transfer history', 'Moves Sofascore lists for him in the last ~400 days involving a followed club, with the site\'s fair fee at the time and the deal grades (buyer, seller). <a href="#/value/transfers">Every transfer →</a>', '<div id="pl-tr">' + FB.loading('lines', 4) + '</div>', { flush: true });
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
