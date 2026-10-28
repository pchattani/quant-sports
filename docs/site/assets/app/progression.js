/* The Quant Footballer — progression (round 6): the player page's "Progression" view (#/player/<pid>?view=progression
 * [&scope=club|intl]) and Compare progression (#/compare/progression/<a>/<b>[/<c>/<d>]?scope=&m=&x=&y=).
 *
 * The Footballer adapter for the kit module assets/qk/progression.js (MIGRATION_V4.md "Progression"), laid out by
 * assets/app/qk-progview.js (QPV). Reads people/<pid>.json `progression`: one row per season and scope (club or
 * international) with dv / dp / pg / kd (oddsmarkets/football/analytics/progression.py): every season carries the box
 * set from the person's own competition lines (goals, assists, xG and xA per 90, shots, key passes, the rating); the
 * seasons the Lab covers (this season and last) add the role group's deep set (GAR/90, npxG + xA, progressive actions,
 * tackles and interceptions, aerials ...). The key lists and each season's peer quantiles are in
 * data/progression_ref.json (`prog.keys`, `seasons`). Pools are per scope and season, every competition the site
 * follows pooled. */
(function (FB) {
'use strict';
if (!FB || !window.QPV) return;
var QK = window.QK, QPV = window.QPV, esc = FB.esc, isNum = FB.isNum;
var REF_P = null;
function refJson() { if (!REF_P) REF_P = FB.load('progression_ref.json'); return REF_P; }
var PEER = { cb: 'centre-backs', fb: 'full-backs', dm_cm: 'central midfielders', am_w: 'attacking midfielders and wingers', st: 'strikers', gk: 'goalkeepers' };
var LABELS = { xg_xa_90: 'xG + xA per 90', goals_90: 'Goals per 90', assists_90: 'Assists per 90', ga_90: 'Goals + assists per 90', xg_90: 'xG per 90',
  xa_90: 'xA per 90', shots_90: 'Shots per 90', key_passes_90: 'Key passes per 90', rating: 'Match rating' };
var SCOPE = { club: 'Club', intl: 'International' };

['compare/progression', 'compare/progression/:a', 'compare/progression/:a/:b', 'compare/progression/:a/:b/:c', 'compare/progression/:a/:b/:c/:d'].forEach(function (p) {
  FB.ROUTES.unshift({ segs: p.split('/'), name: 'compare-progression', section: 'lab' });
});
function compareHref(scope) {
  var h = QPV.hrefFor('#/compare/progression/');
  return function (ids, q) { return h(ids, (scope && scope !== 'club' ? 'scope=' + scope + (q ? '&' : '') : '') + (q || '')); };
}
/* a row's scope and season: from its key ("club:2025/26"), which is all the file keeps since 28 Oct 2026 */
function scopeOf(r) { return r.scope || String(r.key || '').split(':')[0]; }
function eraOf(r) { return r.era || String(r.key || '').split(':').slice(1).join(':'); }
/* the season axis: a split season by the year it ends (2025/26 -> 2026), a calendar one by itself */
function eraX(era) { var s = String(era || ''), y = parseInt(s.slice(0, 4), 10); return isNaN(y) ? null : (s.indexOf('/') >= 0 ? y + 1 : y); }

function toP(doc, scope, keysOf) {
  var curEra = ((doc.years || [])[0] || {}).era;
  var rows = (doc.progression || []).filter(function (r) { return scopeOf(r) === scope; });
  var byX = {};
  rows.forEach(function (r) {
    var x = eraX(eraOf(r));
    if (x === null) return;
    if (!byX[x] || (r.min || 0) > (byX[x].min || 0)) byX[x] = r;     /* a move between a split and a calendar frame: the longer season */
  });
  var xs = Object.keys(byX).map(Number).sort(function (a, b) { return a - b; });
  return { id: String(doc.id), name: doc.name, short: FB.surname(doc.name || '') || doc.name, scope: scope,
    seasons: xs.map(function (x, i) {
      var r = byX[x], ks = keysOf[r.kd] || [];
      var nm = r.team || (r.tid ? FB.clubName(r.tid) : '');
      var tot = isNum(r.st) && r.st >= 0.5;     /* mostly Sofascore's season totals (no line-ups behind them) */
      var era = eraOf(r);
      return { key: r.key, x: x, label: era, age: QPV.ageAt(doc.dob, x, String(era).indexOf('/') >= 0 ? 0 : 6), cy: i + 1,
        team: nm ? { abbr: FB.clubCode(nm), name: nm, colour: r.tid ? FB.clubColour(r.tid) : null } : null, teams: (r.teams || []).length > 1 ? r.teams.map(function (t) { return FB.clubCode(FB.clubName(t) || String(t)); }) : null,
        group: r.pg || null, n: r.min, nUnit: tot ? 'minutes · Sofascore season totals' : 'minutes', small: !(r.dp && r.dp.length), values: QPV.zip(ks, r.dv), pct: QPV.zip(ks, r.dp), kd: r.kd,
        totals: tot, partial: !!curEra && era === curEra };
    }) };
}
function mainKind(doc, scope) {
  var ks = (doc.progression || []).filter(function (r) { return scopeOf(r) === scope; }).map(function (r) { return r.kd; });
  return ks.indexOf('gk') >= 0 ? 'gk' : ks.indexOf('out') >= 0 ? 'out' : 'box';
}
function groupOf(P) { return (P.seasons.slice().reverse().filter(function (s) { return s.group; })[0] || {}).group; }
/* which seasons are Sofascore's season totals: "12 seasons (2008/09 to 2019/20)" or '' */
function totalsText(P) {
  var t = P.seasons.filter(function (s) { return s.totals; });
  if (!t.length) return '';
  return t.length + ' season' + (t.length === 1 ? '' : 's') + ' (' + esc(t[0].label) + (t.length > 1 ? ' to ' + esc(t[t.length - 1].label) : '') + ')';
}
function metricsFor(keys, cat, grp) { return QPV.metrics(keys, cat, { head: cat && grp ? cat.headline(grp) : [], labels: LABELS }); }
function scopeSeg(base, scope, has) {
  return '<div class="qk-seg" role="group" aria-label="Scope">' + ['club', 'intl'].map(function (s) {
    return has[s] ? '<a class="qk-btn' + (s === scope ? ' primary' : '') + '" href="' + esc(base(s)) + '">' + SCOPE[s] + '</a>' : '';
  }).join('') + '</div>';
}

function tab(el, p) {
  var pid = String(p.pid || ''), q = p.query || {};
  el.innerHTML = QK.skeleton('card', 1) + QK.skeleton('chart', 1);
  return Promise.all([FB.load('people/' + pid + '.json'), refJson(), QK.spec.load('football'), FB.clubsIndex()]).then(function (res) {
    if (!FB.alive(el)) return;
    var doc = res[0], ref = res[1] || {}, cat = res[2];
    if (!doc || !doc.id) { el.innerHTML = QK.empty('Player not found', 'Search for a player with /.'); return; }
    var has = { club: false, intl: false };
    (doc.progression || []).forEach(function (r) { has[scopeOf(r)] = true; });
    var scope = q.scope === 'intl' && has.intl ? 'intl' : (has.club ? 'club' : (has.intl ? 'intl' : 'club'));
    document.title = doc.name + ' · Progression · The Quant Footballer';
    var keysOf = ((ref.prog || {}).keys) || {};
    var P = toP(doc, scope, keysOf), grp = groupOf(P), peer = PEER[grp] || 'players';
    var kind = mainKind(doc, scope);
    var ms = metricsFor(keysOf[kind] || [], cat, grp);
    var head = (cat && grp ? cat.headline(grp) : []).map(function (k) { return ms.filter(function (m) { return m.id === k; })[0]; }).filter(Boolean);
    if (head.length < 3) head = ms.filter(function (m) { return ['xg_xa_90', 'ga_90', 'goals_90', 'assists_90', 'xa_90', 'key_passes_90', 'rating'].indexOf(m.id) >= 0; });
    var R = QK.prog.ref(ref);
    var base = FB.href.player(doc.id);
    var deepN = P.seasons.filter(function (s) { return s.kd !== 'box'; }).length;
    var totT = totalsText(P);
    QPV.tab(el, { P: P, metrics: ms, head: head, cat: cat, peer: peer, nUnit: 'minutes',
      tabs: [['overview', 'Overview', base], ['progression', 'Progression', base + '?view=progression']],
      kicker: 'Progression · ' + SCOPE[scope] + (doc.current_club && doc.current_club.name && scope === 'club' ? ' · ' + doc.current_club.name : (doc.national_team && scope === 'intl' ? ' · ' + doc.national_team.name : '')),
      title: esc(doc.name),
      sub: P.seasons.length + ' season' + (P.seasons.length === 1 ? '' : 's') + ' (' + SCOPE[scope].toLowerCase() + ' football) in the data, each against that season’s ' + esc(peer) + ' with 450+ minutes (goalkeepers 900), every competition we follow pooled. Every season has the box numbers (goals, assists, xG, xA, shots, the rating); ' +
        (deepN ? 'the ' + deepN + ' season' + (deepN === 1 ? '' : 's') + ' our Lab covers add the full set: GAR/90, npxG + xA, progressive actions, duels and more.' : 'the full set (GAR/90, npxG + xA, progressive actions) starts with the seasons our Lab covers.') +
        (totT ? ' ' + totT + ' come from Sofascore’s season totals, not our line-ups: box numbers only, with xG, shots and the rating only where Sofascore has them for that season.' : ''),
      actions: scopeSeg(function (s) { return base + '?view=progression' + (s === 'intl' ? '&scope=intl' : ''); }, scope, has),
      key: ms.filter(function (m) { return m.id === 'gar90'; })[0] || ms.filter(function (m) { return m.id === 'xg_xa_90'; })[0] || null,
      ref: function (S, k) { return S.group ? R(S.group, S.key, k) : null; },
      note: 'Seasons follow the player’s own calendar: “2025/26” in Europe, “2025” in the Americas.' + (totT ? ' Seasons marked “Sofascore season totals” in the tooltips have no match log behind them.' : ''),
      compare: { sims: [], href: compareHref(scope) },
      empty: 'No ' + SCOPE[scope].toLowerCase() + ' seasons with 90+ minutes in the data.' });
  });
}

function compare(el, p) {
  var q = p.query || {}, scope = q.scope === 'intl' ? 'intl' : 'club';
  var ids = [p.a, p.b, p.c, p.d].filter(Boolean).map(String);
  ids = ids.filter(function (x, i) { return ids.indexOf(x) === i; }).slice(0, 4);
  if (!ids.length) ids = ['839956', '826643'];
  el.innerHTML = QK.skeleton('chart', 1);
  return Promise.all([Promise.all(ids.map(function (x) { return FB.load('people/' + x + '.json'); })), refJson(), QK.spec.load('football'), FB.load('people_names.json'), FB.clubsIndex()]).then(function (res) {
    if (!FB.alive(el)) return;
    var docs = res[0].filter(function (d) { return d && d.id && !d.merged_into; }), ref = res[1] || {}, cat = res[2];
    var keysOf = ((ref.prog || {}).keys) || {};
    var Ps = docs.map(function (d) { return toP(d, scope, keysOf); });
    var kind = docs.some(function (d) { return mainKind(d, scope) === 'gk'; }) ? 'gk' : docs.some(function (d) { return mainKind(d, scope) === 'out'; }) ? 'out' : 'box';
    var grp = Ps.length ? groupOf(Ps[0]) : null;
    var ms = metricsFor(keysOf[kind] || keysOf.box || [], cat, grp), hd = cat && grp ? cat.headline(grp) : [];
    var R = QK.prog.ref(ref);
    var href = compareHref(scope);
    var nd = res[3] || {}, f = nd.fields || [], rows = nd.rows || [];
    var iId = f.indexOf('id'), iN = f.indexOf('name'), iC = f.indexOf('club');
    var names = rows.slice(0, 5000).map(function (r) { return [String(r[iId]), r[iN] + (iC >= 0 && r[iC] ? ' (' + r[iC] + ')' : '')]; });
    names.sort(function (a, b) { return a[1].localeCompare(b[1]); });
    var first = ['xg_xa_90', 'gar90', 'npxg_xa_90'].filter(function (k) { return ms.some(function (m) { return m.id === k; }); })[0] || hd.filter(function (k) { return ms.some(function (m) { return m.id === k; }); })[0];
    document.title = 'Compare progression · The Quant Footballer';
    QPV.compare(el, { players: Ps, metrics: ms, cat: cat, metric: q.m || first || (ms[0] || {}).id, x: q.x, y: q.y,
      ref: function (P, S, k) { return S.group ? R(S.group, S.key, k) : null; }, peerName: function (P) { return PEER[groupOf(P)] || 'players'; },
      cyNote: 'Career year counts seasons in our data (' + SCOPE[scope].toLowerCase() + ' football, 90+ minutes).', kicker: 'Compare progression · ' + SCOPE[scope] + ' football',
      actions: '<div class="qk-seg" role="group" aria-label="Scope">' + ['club', 'intl'].map(function (s) { return '<a class="qk-btn' + (s === scope ? ' primary' : '') + '" href="' + esc(compareHref(s)(Ps.map(function (P) { return P.id; }), '')) + '">' + SCOPE[s] + '</a>'; }).join('') + '</div>',
      href: href, names: names,
      sub: 'Two to four careers on one chart: by season, by age or by career year, club or international football, as the value or as a percentile against that season’s peers. The deep numbers (GAR/90, npxG + xA ...) cover the seasons our Lab holds; goals, assists, xG and xA go back further, the older seasons from Sofascore’s season totals (marked in the tooltips).' });
  });
}

FB.route('compare-progression', compare);
FB.progression = { tab: tab, compare: compare, toP: toP };
})(window.FB);
