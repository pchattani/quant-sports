/* The Quant Footballer — Competitions (#/competitions, #/competition/<slug>[/<tab>][?s=<sid>&view=…]).
 *
 *   #/competitions[?f=<family>&q=<text>]   every competition by family: season, favourite, leader, scorer, progress
 *   #/competition/<slug>[/<tab>]           one competition, one header (season picker, meta line, banners) and tabs:
 *     overview   leader / favourite / scorer / progress; next fixtures and latest results; the race (bars and
 *                run by run); leaders; how the competition is modelled; every season
 *     table      standings with bands, groups / conferences / split, finishing-position heat map, upcoming;
 *                Liga Argentina: ?view=zones|anual|relegation
 *     fixtures   every match by day with status / stage-round / club filters and our full forecast (?view=played)
 *     bracket    knockout ladder, seeds, known ties, reach-each-round probabilities
 *     odds       "Chances": our chances from the simulated seasons; ?view=history (our chances after each model run,
 *                QKC.forecast). No market here: it appears only as a quiet reference on the match centre and Model.
 *     power      model strength, luck against xG, schedule, Elo over the season
 *     players    leaderboard (metric, position, club, minutes, qualified), top-scorer race, side-by-side compare,
 *                creation v finishing, shot maps
 *     analytics  team of the week and awards, best XIs, performers, team rankings and style map, attack v defence,
 *                points v xPts, form
 *     clubs      every club, linking to the one club page across competitions
 *     seasons    every edition on record with champion, source and coverage
 *   ?s=<sid>     a past edition (data/<slug>/s/<sid>/season.json): overview, table, fixtures (results), bracket,
 *                players (lines and leaders), seasons. No model tabs.
 * Reads only the files a competition writes (FB.compFile skips the rest). */
(function (FB) {
'use strict';

var QK = window.QK, QKC = window.QKC;
var esc = FB.esc, isNum = FB.isNum, pct = FB.pct, num = FB.num, signed = FB.signed;

/* The open competition is a national-team one: "Team" not "Club", "tournament" not "season" (set on each render). */
var INTL = false;
function clubW() { return INTL ? 'Team' : 'Club'; }
var FAM_LABEL = {};
FB.FAMILIES.forEach(function (f) { FAM_LABEL[f.key] = f.label; });
var METHOD_LABELS = { pooled: 'the pooled fit over every league and club cup', global: 'the parameter set shared across leagues', 'per-league': 'this competition\'s own tuned fit', 'default': 'the untuned defaults', 'international fit': 'the international fit (national teams)' };
var CUP_KIND_TEXT = {
  swiss: 'a 36-club league phase; places 1–8 go straight to the Round of 16, places 9–24 play a two-legged play-off, then a fixed two-legged bracket and a single-match neutral final',
  groups: 'groups whose top two go through; the first knockout round pairs group winners with runners-up from other groups, drawn at random per simulation',
  regional_swiss: 'two regional leagues of 16; the top 8 of each play a two-legged Round of 16 within the region, then West meets East at random from the quarter-finals',
  knockout: 'a straight knockout read from the draw: pairs come from the draw where known and from a random pairing of the survivors otherwise',
  fixed: 'ties fixed by the competition\'s rules; a slot held by another cup\'s champion is drawn per simulation from that cup\'s winner distribution',
  international: 'national-team competition: not simulated; tables and the knockout ladder are as played and each fixture carries the international fit\'s line'
};
/* The players tab compares on the role sets (FB.MSET in core.js, from the metrics spec): peers are his formation-role
   group in this competition over max(the group's minimum, the competition's floor). These two letter-based sets are the
   fallback only, when this season's roles (value/lines.json) cannot be read. */
var CMP_OUT = [
  { key: 'npxg_90', label: 'npxG/90' }, { key: 'shots_90', label: 'Shots/90' }, { key: 'xa_90', label: 'xA/90' },
  { key: 'key_passes_90', label: 'Key passes/90' }, { key: 'pass_pct', label: 'Pass %' }, { key: 'dribbles_90', label: 'Dribbles/90' },
  { key: 'prog_carries_90', label: 'Prog. carries/90' }, { key: 'tackles_90', label: 'Tackles/90' }, { key: 'interceptions_90', label: 'Interceptions/90' },
  { key: 'aerial_pct', label: 'Aerial %' }, { key: 'recoveries_90', label: 'Recoveries/90' }, { key: 'rating', label: 'Rating' }
];
var CMP_GK = [
  { key: 'saves_90', label: 'Saves/90' }, { key: 'save_pct', label: 'Save %' }, { key: 'goals_prevented_90', label: 'Goals prevented/90' },
  { key: 'conceded_90', label: 'Conceded/90' }, { key: 'sweeper_90', label: 'Sweeper/90' }, { key: 'high_claims_90', label: 'High claims/90' },
  { key: 'pass_pct', label: 'Pass %' }, { key: 'long_ball_pct', label: 'Long-ball %' }, { key: 'rating', label: 'Rating' }
];
var LEADER_LABELS = {
  goals: ['Goals', 'int'], assists: ['Assists', 'int'], goalsAssistsSum: ['Goals + assists', 'int'], rating: ['Rating', '2'],
  expectedGoals: ['Expected goals', '2'], expectedAssists: ['Expected assists', '2'], scoringFrequency: ['Minutes per goal', 'int', true],
  totalShots: ['Shots', 'int'], shotsOnTarget: ['Shots on target', 'int'], bigChancesCreated: ['Big chances created', 'int'], bigChancesMissed: ['Big chances missed', 'int'],
  keyPasses: ['Key passes', 'int'], accuratePasses: ['Accurate passes', 'int'], accurateLongBalls: ['Accurate long balls', 'int'], successfulDribbles: ['Dribbles', 'int'],
  tackles: ['Tackles', 'int'], interceptions: ['Interceptions', 'int'], clearances: ['Clearances', 'int'], possessionLost: ['Possession lost', 'int'],
  saves: ['Saves', 'int'], cleanSheet: ['Clean sheets', 'int'], goalsPrevented: ['Goals prevented', '2'], leastConceded: ['Fewest conceded', 'int'], mostConceded: ['Most conceded', 'int'],
  penaltyGoals: ['Penalty goals', 'int'], penaltyWon: ['Penalties won', 'int'], freeKickGoal: ['Free-kick goals', 'int'],
  yellowCards: ['Yellow cards', 'int'], redCards: ['Red cards', 'int'], topSpeed: ['Top speed (km/h)', '1'],
  kilometersCoveredPer90: ['Distance per 90 (km)', '1'], numberOfSprintsPer90: ['Sprints per 90', '1']
};
var LEADER_ORDER = ['goals', 'assists', 'goalsAssistsSum', 'rating', 'expectedGoals', 'expectedAssists', 'bigChancesCreated', 'keyPasses', 'successfulDribbles',
  'totalShots', 'shotsOnTarget', 'scoringFrequency', 'tackles', 'interceptions', 'clearances', 'saves', 'cleanSheet', 'goalsPrevented', 'accuratePasses',
  'accurateLongBalls', 'penaltyGoals', 'freeKickGoal', 'yellowCards', 'redCards'];
var AWARD_LABELS = { finisher: 'Finisher', creator: 'Creator', wall: 'The wall', engine: 'Engine', ball_winner: 'Ball winner' };
var TEAM_AWARD_LABELS = { best_xg_diff: 'Best xG difference', luckiest: 'Luckiest', unluckiest: 'Unluckiest', smash_and_grab: 'Smash and grab' };
var BASIS_LABELS = { rating: 'Rating', output: 'Output', defence: 'Defence', form: 'Form' };
/* The clubs' headline set from the metrics spec (docs/_design/metrics/football.json, group "clubs"): the most stable
   and predictive team rates, then expected points. Minimum 5 matches; flagged under 10. */
var STYLE_KEYS = ['xg_diff', 'xg_for', 'xg_against', 'sot_diff', 'field_tilt', 'big_chances', 'possession', 'ppda', 'xpts_per_match'];
var CLUB_MIN = 5, CLUB_SMALL = 10;
var ROUND_ORDER = ['prelim', 'q1', 'q2', 'q3', 'q4', 'po', 'playoff', 'play_in', 'wc', 'r1', 'r2', 'r3', 'r4', 'r5', 'r6', 'r7', 'r8', 'r64', 'r32', 'r16', 'csf', 'qf', 'cf', 'sf', '3rd', 'final'];
var UP_COL = ['var(--c-3)', 'var(--c-1)', 'var(--c-7)', 'var(--c-4)', 'var(--c-6)'];
var DOWN_COL = ['var(--c-2)', 'var(--c-8)'];

// ── small helpers ─────────────────────────────────────────────────────────

function $(root, id) { return root.querySelector('#' + id); }
function has(v) { return v !== undefined && v !== null && !(typeof v === 'number' && isNaN(v)); }
function lc(s) { return String(s || '').toLowerCase(); }
function norm(s) { return lc(s).normalize ? lc(s).normalize('NFD').replace(/[̀-ͯ]/g, '') : lc(s); }
function foldName(s) { return norm(s).replace(/&/g, ' and ').replace(/\b(fc|afc|cf|sc|ac|cd|sv|fk|club)\b/g, ' ').replace(/[^a-z0-9]+/g, ' ').trim(); }
function uniq(a) { var o = [], s = {}; a.forEach(function (x) { if (!s[x]) { s[x] = 1; o.push(x); } }); return o; }
function hexOf(v) { var m = /var\((--[^)]+)\)/.exec(v); return m ? QK.cssVar(m[1]) : v; }
function cardMsg(t) { return FB.muted(t); }
function pctCell(v, strong) { return isNum(v) ? (strong ? '<b class="fb-num">' + pct(v, v < 0.1 && v > 0 ? 1 : 0) + '</b>' : '<span class="fb-num">' + pct(v, v < 0.1 && v > 0 ? 1 : 0) + '</span>') : '<span class="qk-muted">—</span>'; }
/* a probability cell washed in the accent, for reach / probability grids */
function heatPct(v, colour) {
  if (!isNum(v)) return '<span class="qk-muted">—</span>';
  var a = Math.round(Math.min(1, v) * 45);   // capped so white type keeps AA on the fullest cell
  return '<span class="fb-co-hp" style="background:color-mix(in srgb, ' + (colour || 'var(--signal)') + ' ' + a + '%, transparent)">' + pct(v, v < 0.1 && v > 0 ? 1 : 0) + '</span>';
}
function pctFmt(v) { return isNum(v) ? pct(v, v < 0.1 && v > 0 ? 1 : 0) : '—'; }
/* A club's mark for the chance bars (crest where there is one, else the monogram). */
function markOf(ctx, team) { var id = ctx.tidOf(team); return { name: team, logo: id ? FB.crestUrl(id) : null, colour: id ? FB.clubColour(id) : null }; }
/* Our chances as 538-style bars (v4: club-colour blocks with the name inside when clubs_index.json has the colour, else
   ours in blue): rows [{team, p}] (sorted here). */
function chanceList(ctx, c, rows, opts) {
  var o = opts || {};
  var rs = rows.filter(function (r) { return isNum(r.p) && r.p > 0; });
  if (!rs.length) return cardMsg(o.empty || 'Nothing to show yet.');
  return FB.chances(rs.map(function (r) { var id = ctx.tidOf(r.team); return { label: r.team, sub: r.sub, p: r.p, mark: markOf(ctx, r.team), color: id ? FB.clubColour(id) : null, href: id ? FB.href.club(id, { c: c.slug }) : null }; }),
    { limit: o.limit || 10, oursName: o.oursName || 'Our chance' });
}
function riskPct(v) { return heatPct(v, 'var(--c-8)'); }
function rowsSorted(list, key, desc) { return list.slice().sort(function (a, b) { var x = a[key], y = b[key]; x = isNum(x) ? x : -1e9; y = isNum(y) ? y : -1e9; return desc === false ? x - y : y - x; }); }

/* Club names -> ids: the competition's teams.json, then the club index (exact, then folded). */
var NAMEIDX = null;
function nameIndex() {
  if (NAMEIDX) return Promise.resolve(NAMEIDX);
  return FB.clubsIndex().then(function (ci) {
    var club = {}, nat = {}, fold = {};
    ci.list.forEach(function (r) {
      var m = r.national ? nat : club;
      if (!(r.name in m)) m[r.name] = r.id;
      var f = foldName(r.name);
      if (f && !(f in fold)) fold[f] = r.id;
    });
    NAMEIDX = { club: club, nat: nat, fold: fold };
    return NAMEIDX;
  });
}
function makeCtx(c, d) {
  var teams = ((d && d.teams) || {}).teams || {};
  var intl = c.scope === 'international' || FB.familyOf(c) === 'international';
  var idx = NAMEIDX || { club: {}, nat: {}, fold: {} };
  var cache = {};
  function tidOf(name) {
    if (!name) return null;
    if (name in cache) return cache[name];
    var t = teams[name] && teams[name].team_id ? teams[name].team_id : null;
    if (!t) t = intl ? (idx.nat[name] || idx.club[name]) : (idx.club[name] || idx.nat[name]);
    if (!t) {
      var f = foldName(name);
      var hit = Object.keys(teams).filter(function (n) { return teams[n].team_id && foldName(n) === f; })[0];
      t = hit ? teams[hit].team_id : (idx.fold[f] || null);
    }
    cache[name] = t || null;
    return cache[name];
  }
  return {
    slug: c.slug, c: c, d: d || {}, tidOf: tidOf,
    club: function (name, tid, size) { if (!name) return '<span class="qk-muted">—</span>'; return FB.clubLink(tid || tidOf(name), name, { q: { c: c.slug }, size: size || 'sm' }); },
    withIds: function (f) { var o = FB.merge(f, {}); if (!o.home_id) o.home_id = tidOf(f.home); if (!o.away_id) o.away_id = tidOf(f.away); return o; }
  };
}

/* Where a competition's chances boards live since Chances stopped being a tab: the Race tab (plain leagues), else the
   Table tab, else the Knockout tab, else the overview. */
function chancesHome(c) {
  if (FB.race && FB.race.eligible(c)) return 'race';
  var tabs = liveTabs(c, 0);
  return tabs.indexOf('table') >= 0 ? 'table' : tabs.indexOf('bracket') >= 0 ? 'bracket' : 'overview';
}
/* the chances boards appended to a tab: our chance of winning, of the drop or the final, and every club's chances */
function chancesSection(el, body, c, d0, q, embed) {
  if (!FB.hasFile(c.slug, 'probs') || FB.isLastEdition(c) || chancesHome(c) !== embed) return;
  var host = document.createElement('section');
  host.className = 'qk-section fb-co-sec';
  host.id = 'co-chances';
  host.innerHTML = QK.sectionHead({ kicker: 'Chances', title: 'Who finishes where', sub: 'Our chances from the simulated seasons' + (c.kind === 'cup' ? ' of the rest of the competition' : '') + ': the winner, ' + (c.kind === 'cup' ? 'the final' : 'the drop or the play-offs') + ', and every ' + clubW().toLowerCase() + '.' }) + '<div id="co-chb"></div>';
  body.appendChild(host);
  LIVE.odds(el, host.querySelector('#co-chb'), c, d0, q, embed);
}
/* The competition's kind words. */
function tabLabel(c, t) {
  var k = c.kind, fam = FB.familyOf(c);
  if (t === 'table') {
    if (k === 'liga') return 'Zones';
    if (k === 'conference') return 'Conferences';
    if (k === 'cup') return c.cup_kind === 'groups' || c.cup_kind === 'international' ? 'Groups' : c.cup_kind === 'regional_swiss' ? 'Regions' : 'League phase';
    return 'Table';
  }
  if (t === 'bracket') return k === 'playoff' ? 'Liguilla' : k === 'liga' || k === 'conference' ? 'Playoffs' : 'Knockout';
  if (t === 'teams') return fam === 'international' ? 'Nations' : 'Teams';
  if (t === 'fixtures') return 'Fixtures & results';
  return { overview: 'Overview', race: 'Race', odds: 'Chances', players: 'Players', analytics: 'Analytics', races: 'Golden Boot', seasons: 'History' }[t] || t;
}
/* The tabs a live competition has, from its manifest tabs. */
function liveTabs(c, nSeasons) {
  var on = { overview: 1 };
  (c.tabs || []).forEach(function (t) {
    if (t === 'methodology') return;
    var m = FB.COMP_TAB_MAP[t];
    if (m) on[m[0]] = 1;
  });
  /* round 9: Chances is no tab of its own (its boards sit at the foot of the Race tab, or the Table / Knockout tab) */
  delete on.odds;
  if (FB.race && FB.race.eligible(c)) on.race = 1;     // the Race tab (race.js): plain leagues
  if (FB.hasFile(c.slug, 'player_leaders')) on.races = 1;   // the Golden Boot race and the leaders
  if (nSeasons > 1) on.seasons = 1;
  return FB.COMP_TABS.filter(function (t) { return on[t]; });
}
function pastTabs(doc) {
  var t = ['overview'];
  if ((doc.standings || []).length) t.push('table');
  if ((doc.fixtures || []).length) t.push('fixtures');
  if ((doc.bracket || []).length) t.push('bracket');
  if ((doc.players || []).length || Object.keys(doc.leaders || {}).length) t.push('players');
  t.push('seasons');
  return t;
}
function favKeyOf(c) { return c.kind === 'conference' || c.kind === 'playoff' || c.kind === 'cup' ? 'p_cup' : 'p_title'; }
/* What the favourite wins, as a fan says it: "the title" (a league), "the Champions League" / "the FA Cup" (a cup whose
   label is the generic Winner or Champion: its short name), "MLS Cup", "the Liguilla". Never "Who wins Winner?". */
function winnerWord(c) {
  var l = c.favourite_label || '';
  if (l === 'Title' || (!l && c.kind !== 'cup')) return 'the title';
  if (!l || l === 'Winner' || l === 'Champion') return 'the ' + (c.short_name || c.name || 'trophy');
  return /^[A-Z]{2,}/.test(l) ? l : 'the ' + l;
}
/* A simulated competition: the race cards, "from N simulated seasons" and the favourite tile need a simulation behind
   them (national-team competitions and a draw not yet made have none). */
function simulated(m) { return !!(m && isNum(m.n_sims) && m.n_sims > 0 && !m.unsimulated); }
var detailNow = FB.detailNow, dataAgeHours = FB.dataAge;
function bandColour(bands, key) {
  var up = 0, down = 0;
  for (var i = 0; i < (bands || []).length; i++) {
    var b = bands[i];
    if (b.key === key) return b.kind === 'down' ? DOWN_COL[Math.min(down, 1)] : UP_COL[Math.min(up, 4)];
    if (b.kind === 'down') down++; else up++;
  }
  return null;
}
function bandAt(bands, pos) {
  for (var i = 0; i < (bands || []).length; i++) if (pos >= bands[i].first && pos <= bands[i].last) return bands[i];
  return null;
}
function posCell(pos, bands) {
  var b = bandAt(bands, pos);
  var col = b ? bandColour(bands, b.key) : null;
  return '<span class="fb-co-pos"' + (col ? ' style="--b:' + col + '" title="' + esc(b.label) + '"' : '') + '>' + esc(pos) + '</span>';
}
function legend(bands) {
  if (!(bands || []).length) return '';
  return '<div class="qk-legend fb-co-legend">' + bands.map(function (b) {
    return '<span><i style="--k:' + bandColour(bands, b.key) + '"></i>' + esc(b.label) + ' <span class="qk-muted fb-num">' + (b.first === b.last ? b.first : b.first + '–' + b.last) + '</span></span>';
  }).join('') + '</div>';
}
function noteChip(note) {
  if (!note) return '';
  var n = String(note);
  var cls = /releg|descen/i.test(n) ? 'bad' : /champion|title|winner|promot|playoff|qualif|europa|conference|libertadores|sudamericana|copa/i.test(n) ? 'good' : '';
  return '<span class="fb-co-note ' + cls + '">' + esc(n) + '</span>';
}

// ── the directory ─────────────────────────────────────────────────────────

FB.route('competitions', function (el, p) {
  var q = p.query || {};
  var fam = q.f && FAM_LABEL[q.f] ? q.f : 'all';
  var text = q.q || '';
  var all = FB.comps();
  var okN = all.filter(function (c) { return c.ok; }).length;
  el.innerHTML = FB.pageHead('Competitions', 'Every competition', okN + ' leagues, cups and national-team competitions. Pick one for its table, fixtures, our chances, players and every past season.') +
    '<div class="fb-co-dirbar"><div class="qk-chips scroll" id="co-fam" role="group" aria-label="Family">' +
      /* the super cups fold into their host competition's page (round 9): no chip of their own; a search still finds them */
      [['all', 'All']].concat(FB.FAMILIES.filter(function (f) { return f.key !== 'super'; }).map(function (f) { return [f.key, f.label]; })).map(function (f) {
        var n = all.filter(function (c) { return c.ok && FB.familyOf(c) !== 'super' && (f[0] === 'all' || FB.familyOf(c) === f[0]); }).length;
        return '<button class="qk-chip" type="button" data-value="' + f[0] + '" aria-pressed="' + (f[0] === fam) + '">' + esc(f[1]) + ' <span class="n">' + n + '</span></button>';
      }).join('') + '</div>' +
      '<input class="qk-input fb-co-find" id="co-q" type="search" placeholder="Find a competition or country…" aria-label="Find a competition" value="' + esc(text) + '"></div>' +
    '<div id="co-dir"></div>';
  QK.chips($(el, 'co-fam'), function (v) { fam = v[0] || 'all'; FB.setQuery({ f: fam === 'all' ? null : fam }); draw(); });
  var inp = $(el, 'co-q');
  inp.addEventListener('input', function () { text = inp.value; FB.setQuery({ q: text || null }); draw(); });
  function draw() {
    var t = norm(text).trim();
    var list = all.filter(function (c) { return (fam === 'all' || FB.familyOf(c) === fam) && (!t || norm(c.name + ' ' + (c.short_name || '') + ' ' + (c.country || '')).indexOf(t) >= 0); });
    var groups = FB.FAMILIES.filter(function (f) { return (fam === 'all' || f.key === fam) && (f.key !== 'super' || t); }).map(function (f) {
      var live = list.filter(function (c) { return c.ok && FB.familyOf(c) === f.key; });
      if (!live.length) return '';
      return '<section class="fb-sec fb-co-fam">' + FB.secHead(esc(f.label), live.length + ' competition' + (live.length === 1 ? '' : 's')) +
        '<div class="fb-co-cards">' + live.map(dirCard).join('') + '</div></section>';
    }).join('');
    var soon = list.filter(function (c) { return !c.ok; });
    $(el, 'co-dir').innerHTML = (groups || FB.empty('No competition matches', 'Try another name or family.')) +
      (soon.length ? '<section class="fb-sec"><div class="qk-kicker">Coming as the data arrives</div><div class="fb-co-soon">' + soon.map(function (c) { return '<span class="qk-badge">' + esc(c.name) + '</span>'; }).join('') + '</div></section>' : '');
  }
  draw();
});

function dirCard(c) {
  var cs = FB.currentSeason(c), last = FB.isLastEdition(c);
  var frac = c.games_total ? Math.min(1, (c.games_played || 0) / c.games_total) : null;
  var won = c.winner && c.winner.team ? c.winner : (c.favourite && (c.complete || (c.p_favourite || 0) >= 0.995) ? { team: c.favourite } : null);
  var chips = [];
  if (c.phase === 'pre') chips.push(FB.badge('Not started'));
  if (last) chips.push(FB.badge('Between editions', '', 'The latest edition in the data has finished; the next appears once its fixtures are published.'));
  else if (c.complete) chips.push(FB.badge('Complete'));
  if (c.store_fresh === false) chips.push(FB.badge('Stale data', 'live'));
  if (c.synthetic) chips.push(FB.badge('Sample data', 'live'));
  if (c.unsimulated) chips.push(FB.badge('Not simulated', '', 'National-team competitions show tables and ties as played; each fixture carries our chance from the international model.'));
  var fav = last
    ? '<div class="fb-co-fav"><span class="qk-kicker">Last edition · ' + esc(cs.season) + '</span><b>' + (won ? FB.crest(won.tid, won.team, 'sm') + ' ' + esc(won.team) : '<span class="qk-muted">no winner on record</span>') + '</b></div>'
    : c.field_partial ? '<div class="fb-co-fav"><span class="qk-muted">Winner chances once the top flight enters</span></div>'
    : c.favourite ? '<div class="fb-co-fav"><span class="qk-kicker">' + esc(c.favourite_label || 'Title') + ' favourite · our chance</span><b>' + esc(c.favourite) + ' <span class="fb-num">' + pct(c.p_favourite) + '</span></b>' +
      '<span class="fb-co-bar"><i style="width:' + ((c.p_favourite || 0) * 100).toFixed(1) + '%"></i></span></div>'
    : '<div class="fb-co-fav"><span class="qk-muted">' + esc(c.unsimulated ? 'Tables as played' : 'No simulation yet') + '</span></div>';
  var facts = [];
  if (c.leader) facts.push('<span>Leader <b>' + esc(c.leader.team) + '</b> <span class="fb-num">' + c.leader.pts + '</span></span>');
  if (c.top_scorer) facts.push('<span>Top scorer <b>' + esc(c.top_scorer.name) + '</b> <span class="fb-num">' + c.top_scorer.goals + '</span></span>');
  if (c.next && !last) facts.push('<span>Next <b>' + esc(c.next.home) + ' v ' + esc(c.next.away) + '</b> ' + esc(FB.fmtDate(c.next.date)) + '</span>');
  var tabs = liveTabs(c, 0).filter(function (t) { return t !== 'overview'; }).slice(0, 4);
  var sup = superOf(c);
  if (sup && (sup.next || sup.last)) facts.push('<span>' + esc(sup.short_name || sup.name) + ' <b><a href="' + esc(FB.href.comp(sup.slug)) + '">' + esc((sup.next || sup.last).home + ' v ' + (sup.next || sup.last).away) + '</a></b>' + (isNum((sup.next || sup.last).hs) ? ' <span class="fb-num">' + (sup.next || sup.last).hs + '–' + (sup.next || sup.last).as + '</span>' : ' ' + esc(FB.fmtDate((sup.next || sup.last).date))) + '</span>');
  return '<article class="qk-card fb-co-card" style="--k:' + FB.kindColor(FB.kindOf(c.slug)) + '">' +
    '<a class="fb-co-card-head" href="' + esc(FB.href.comp(c.slug)) + '"><span class="qk-kicker">' + esc(c.country || FAM_LABEL[FB.familyOf(c)] || '') + ' · ' + esc(last ? 'last: ' + cs.season : cs.season) + '</span>' +
    '<span class="fb-co-card-name">' + esc(c.name) + '</span></a>' + fav +
    (isNum(frac) && !last ? '<div class="fb-co-prog" title="' + (c.games_played || 0) + ' of ' + c.games_total + ' matches played"><span><i style="width:' + (frac * 100).toFixed(1) + '%"></i></span><b class="fb-num">' + (c.games_played || 0) + '/' + c.games_total + '</b></div>' : '') +
    (facts.length ? '<div class="fb-co-facts">' + facts.join('') + '</div>' : '') +
    '<div class="fb-co-links">' + tabs.map(function (t) { return '<a href="' + esc(FB.href.comp(c.slug, t)) + '">' + esc(tabLabel(c, t)) + '</a>'; }).join('') + chips.join('') + '</div></article>';
}

// ── one competition ───────────────────────────────────────────────────────

FB.route('competition', function (el, p) {
  var c = FB.comp(p.slug);
  var q = p.query || {};
  if (!c) {
    el.innerHTML = FB.pageHead('Competitions', 'Unknown competition', 'There is no competition called “' + esc(p.slug) + '”.') + '<p><a class="qk-btn" href="#/competitions">Every competition →</a></p>';
    return;
  }
  FB.setCompPicker(c.slug);
  INTL = c.scope === 'international' || FB.familyOf(c) === 'international';
  /* round 9: Power, Analytics and Clubs are one Teams tab; their old addresses land on it */
  if (p.tab === 'power' || p.tab === 'analytics' || p.tab === 'clubs') { p.tab = 'teams'; FB.setHashQuiet(FB.href.comp(c.slug, 'teams', q)); }
  if (p.tab === 'odds') { p.tab = chancesHome(c); FB.setHashQuiet(FB.href.comp(c.slug, p.tab, q)); }
  var tab = p.tab && FB.COMP_TABS.indexOf(p.tab) >= 0 ? p.tab : 'overview';
  el.innerHTML = '<div id="co-head">' + headHTML(c, null, []) + '</div><div id="co-tabs"></div><div id="co-body" class="fb-co-body">' + FB.loading('lines', 6) + '</div>';
  var cur = FB.currentSeason(c);
  var sid = q.s && String(q.s) !== cur.sid ? String(q.s) : null;
  return Promise.all([FB.seasonsOf(c), nameIndex()]).then(function (res) {
    if (!FB.alive(el)) return;
    var seasons = res[0] || [];
    if (sid) return openPast(el, c, seasons, sid, tab, q);
    if (!c.ok) {
      $(el, 'co-head').innerHTML = headHTML(c, null, seasons);
      wirePicker(el, c, seasons, tab);
      $(el, 'co-body').innerHTML = FB.empty(c.name + ' is not available yet', c.reason || 'Its first data fetch has not run.');
      return;
    }
    return FB.compFiles(c.slug, ['meta', 'teams', 'fixtures']).then(function (d0) {
      if (!FB.alive(el)) return;
      var tabs = liveTabs(c, seasons.length);
      if (tabs.indexOf(tab) < 0) tab = 'overview';
      $(el, 'co-head').innerHTML = headHTML(c, d0, seasons);
      wirePicker(el, c, seasons, tab);
      $(el, 'co-tabs').innerHTML = FB.subnav(tabs.map(function (t) { return [FB.href.comp(c.slug, t), tabLabel(c, t), t]; }), tab, c.name) + tabHead(c, tab);
      document.title = tabLabel(c, tab) + ' · ' + c.name + ' · The Quant Footballer';
      var fn = LIVE[tab];
      return fn(el, $(el, 'co-body'), c, d0, q, seasons);
    });
  });
});

/* v4: each tab opens with a Broadcast section head (the volt tag says the tab, the Bebas title the story); the
   overview carries its own heads. */
var TAB_HEAD = {
  table: function (c) { return ['The table', 'Where every ' + (c.scope === 'international' ? 'side' : 'club') + ' stands now. Points decide it; the coloured bands show what each place is worth.']; },
  fixtures: function () { return ['Every match. Our call on each.', 'Our home, draw and away chance before kick-off; the score and xG after it. Kick-off in your time zone.']; },
  bracket: function (c) { return ['The road to the final', c.unsimulated || c.scope === 'international' ? 'Every knockout tie as it was played, round by round, with the scores.' : 'The ties as drawn, and our chance of each side reaching each round.']; },
  odds: function (c) { return ['Who finishes where', 'Our chances from the simulated seasons' + (c.kind === 'cup' ? ' of the rest of the competition' : '') + ', and how they have moved run by run.']; },
  /* teams: the Teams tab carries its own section heads (teams.js) */
  races: function (c) { return ['The Golden Boot', 'Who scores the most' + (c.scope === 'international' ? ' this edition' : ' this season') + ', who sets them up, and our chance of each finishing top.']; },
  players: function () { return ['The players behind it', 'Leaders, rates against the same role and the top-scorer race. Percentiles compare like with like: centre-backs with centre-backs.']; },
  analytics: function () { return ['The numbers behind the results', 'Team of the week, the best XIs, styles, attack against defence, and points against expected points.']; },
  clubs: function (c) { return ['Every ' + (c.scope === 'international' ? 'side' : 'club'), 'One page for each, across every competition it plays.']; },
  seasons: function () { return ['The history', 'Every edition on record: the champions, the titles leaderboard, and how complete each season is.']; }
};
function tabHead(c, tab) {
  var f = TAB_HEAD[tab];
  if (!f) return '';
  var t = f(c);
  return '<div class="fb-co-tabhead">' + QK.sectionHead({ kicker: tabLabel(c, tab), title: t[0], sub: t[1] }) + '</div>';
}

/* The header: name, kind, season picker, meta line, banners. d = {meta, fixtures} for a live season, doc for a past one. */
function headHTML(c, d, seasons, doc) {
  var cs = FB.currentSeason(c), last = FB.isLastEdition(c);
  var m = (d && d.meta) || {};
  var sub = [];
  var banners = [];
  if (doc) {
    sub.push(esc(doc.season || (doc.meta || {}).season || ''));
    sub.push(doc.source === 'store' ? 'past season from the match store' : 'past season from the archive');
    var ch = (doc.meta || {}).champion;
    if (ch && ch.team) sub.push((c.kind === 'cup' ? 'won by ' : 'champion ') + esc(ch.team));
    if (doc.coverage === 'partial') banners.push('Line-ups exist for only part of this edition (' + (doc.detail_matches || 0) + ' matches with player data): player lines are lower bounds and the backfill is filling the rest.');
  } else {
    var played = isNum(m.games_played) ? m.games_played : c.games_played, total = isNum(m.games_total) ? m.games_total : c.games_total;
    var fx = ((d && d.fixtures) || {}).matches;
    if (c.kind === 'cup' && fx && fx.length) {
      var real = fx.filter(function (f) { return f.status !== 'cancelled' && f.status !== 'postponed'; });
      played = real.filter(function (f) { return f.status === 'finished'; }).length; total = real.length;
    }
    var season = c.kind === 'liga' ? 'Torneo ' + (cs.season || (m.phase === 'clausura' ? 'Clausura' : 'Apertura')) : (cs.season || m.season || c.season || '');
    sub.push((last ? 'Last edition: ' : '') + esc(season));
    if (total) sub.push('<b class="fb-num">' + (played || 0) + '/' + total + '</b> matches played');
    if (m.n_sims && !last && total && played < total && !m.unsimulated) sub.push('<b class="fb-num">' + FB.int(m.n_sims) + '</b> simulated seasons');
    if (m.updated_at) sub.push('updated ' + esc(FB.fmtStamp(m.updated_at)));
    var near = function (x) { var t = x ? Date.parse(x) : NaN; return !isNaN(t) && Math.abs(t - Date.now()) <= 7 * 864e5; };
    var dormant = !near((c.next || {}).date) && !near((c.last || {}).date);
    if (m.synthetic) banners.push('Sample data generated to exercise the site. These are not real results.');
    if (m.store_fresh === false && !(dormant && m.store_age_hours && m.store_age_hours < 50)) banners.push('The Sofascore data could not be refreshed' + (m.store_age_hours ? ' (last good data ' + m.store_age_hours + ' h ago)' : '') + '. Showing the last good data.');
    if (last) banners.push('The ' + esc(cs.season || season) + ' edition is the latest in the data and it has finished' + (c.winner && c.winner.team ? ' (won by ' + esc(c.winner.team) + ')' : '') + '. The next edition appears once its fixtures are published; earlier editions are in the season picker.');
    else if (m.phase === 'pre') banners.push(esc(m.phase_note || 'The main phase has not started.'));
    else if (m.season_stale) banners.push(c.complete ? 'This edition is complete; the next one is simulated once its draw is known.' : 'The most recent recorded match is old. The configured season may be out of date.');
    if (m.league_complete && c.kind === 'league') banners.push('The league season is complete; probabilities reflect the final table.');
    if (m.unsimulated) banners.push('National-team competitions are not simulated: tables and the knockout ladder are as played; our chance on each fixture comes from the international fit.');
  }
  var picker = (seasons || []).length > 1 ? '<label class="fb-field fb-co-season"><span>Season</span>' + FB.select('co-season', seasons.map(function (s) {
    return [s.sid, (s.season || s.name || s.sid) + (s.source === 'live' ? (s.status === 'last_edition' ? ' · last edition' : ' · current') : s.source === 'archive' ? ' · archive' : '')];
  }), doc ? String(doc.sid) : cs.sid, 'Season') + '</label>' : '';
  var acts = picker + (doc ? '<a class="qk-btn" href="' + esc(FB.href.comp(c.slug)) + '">Current season →</a>' : '');
  return '<header class="qk-sh lg fb-head fb-co-head" style="--k:' + FB.kindColor(FB.kindOf(c.slug)) + '"><div class="qk-sh-main"><div class="qk-sh-kicker"><a href="#/competitions">Competitions</a> · ' + FB.kindChip(FB.kindOf(c.slug)) + ' ' + esc(c.country || FAM_LABEL[FB.familyOf(c)] || '') + '</div>' +
    '<h1 class="qk-sh-title">' + esc(c.name) + '</h1><p class="qk-sh-sub fb-co-meta">' + sub.join(' · ') + '</p></div>' + (acts ? '<div class="qk-sh-actions">' + acts + '</div>' : '') + '</header>' +
    (banners.length ? '<div class="fb-co-banners">' + banners.map(function (b) { return FB.note(b); }).join('') + '</div>' : '');
}
function wirePicker(el, c, seasons, tab) {
  var sel = $(el, 'co-season');
  if (!sel) return;
  sel.addEventListener('change', function () {
    var s = seasons.filter(function (x) { return x.sid === sel.value; })[0];
    if (!s) return;
    if (s.source === 'live') FB.go(FB.href.comp(c.slug, tab === 'players' || tab === 'table' || tab === 'fixtures' || tab === 'bracket' || tab === 'seasons' ? tab : null));
    else FB.go(FB.href.comp(c.slug, ['table', 'fixtures', 'bracket', 'players', 'seasons'].indexOf(tab) >= 0 ? tab : null, { s: s.sid }));
  });
}

// ── live tabs ─────────────────────────────────────────────────────────────

var LIVE = {};

/* The Race tab (race.js): the race over time, what is settled, the stakes, team cards and the shape of the league. */
LIVE.race = function (el, body, c, d0) {
  body.innerHTML = FB.loading('lines', 6);
  return FB.compFiles(c.slug, ['table', 'probs', 'history', 'strength', 'analytics']).then(function (d1) {
    if (!FB.alive(el)) return;
    var d = FB.merge(d0, d1);
    FB.race.render(el, body, c, d, makeCtx(c, d));
    chancesSection(el, body, c, d0, {}, 'race');
  });
};

LIVE.overview = function (el, body, c, d0, q, seasons) {
  var names = ['probs', 'players_live', 'history'].concat(c.kind === 'liga' ? ['zones'] : ['table']);
  body.innerHTML = FB.loading('lines', 6);
  return FB.compFiles(c.slug, names).then(function (d1) {
    if (!FB.alive(el)) return;
    var d = FB.merge(d0, d1);
    var ctx = makeCtx(c, d);
    var m = d.meta || {};
    var fx = ((d.fixtures || {}).matches || []).map(ctx.withIds);
    var players = (d.players_live || {}).players || [];
    var probs = (d.probs || {}).teams || [];
    var t = d.table || {};
    var last = FB.isLastEdition(c);
    // leader
    var leadLabel = 'Leader', leadHTML = '—', leadSub = '';
    var standings = t.standings || t.overall || [];
    if (c.kind === 'liga' && d.zones) {
      var zs = d.zones.zones || {};
      var tops = Object.keys(zs).map(function (z) { return (zs[z].standings || [])[0]; }).filter(Boolean);
      leadHTML = tops.map(function (r) { return ctx.club(r.team); }).join(' ');
      leadSub = 'top of each zone · ' + tops.map(function (r) { return r.pts + ' pts'; }).join(' · ');
    } else if (standings.length && !t.conferences) {
      leadHTML = ctx.club(standings[0].team); leadSub = standings[0].pts + ' pts from ' + standings[0].played;
    } else if (t.conferences) {
      var ct = Object.keys(t.conferences).map(function (g) { return (t.conferences[g] || [])[0]; }).filter(Boolean);
      leadHTML = ct.slice(0, 2).map(function (r) { return ctx.club(r.team); }).join(' ');
      leadSub = 'top of each ' + lc(t.group_label || (c.kind === 'cup' ? 'group' : 'conference'));
    }
    if (leadHTML === '—' && fx.length) {
      var nx = fx.filter(function (f) { return f.status === 'scheduled' || f.status === 'live'; })[0];
      var pv = fx.filter(function (f) { return f.status === 'finished'; }).slice(-1)[0];
      var f0 = nx || pv;
      if (f0) { leadLabel = 'Stage'; leadHTML = esc(FB.roundText(f0, c.slug) || '—'); leadSub = nx ? 'next match ' + esc(FB.fmtDate(nx.date)) : 'latest round played'; }
    }
    var fk = favKeyOf(c);
    var fav = probs.slice().sort(function (a, b) { return (b[fk] || b.p_title || 0) - (a[fk] || a.p_title || 0); })[0];
    var scorer = players.slice().sort(function (a, b) { return (b.goals - a.goals) || (b.xg - a.xg); })[0];
    var fin = last ? fx.filter(function (f) { return f.round === 'final' && f.status === 'finished'; }).slice(-1)[0] : null;
    var champ = last && c.winner && c.winner.team ? c.winner.team : fin ? (fin.winner || fin.agg_winner || (fin.hs > fin.as ? fin.home : fin.as > fin.hs ? fin.away : null)) : null;
    var real = fx.filter(function (f) { return f.status !== 'cancelled' && f.status !== 'postponed'; });
    var gp = c.kind === 'cup' && real.length ? real.filter(function (f) { return f.status === 'finished'; }).length : (m.games_played || 0);
    var gt = c.kind === 'cup' && real.length ? real.length : (m.games_total || 0);
    var sim = simulated(m);
    /* a finished knockout: the runner-up in the first tile, not the group leaders of months ago */
    if (last && fin && champ) { var ru = fin.home === champ ? fin.away : fin.home; leadLabel = 'Runner-up'; leadHTML = ctx.club(ru); leadSub = 'lost the final ' + Math.min(fin.hs, fin.as) + '–' + Math.max(fin.hs, fin.as); }
    var kp = [
      FB.kpi(leadLabel, leadHTML, { text: true, sub: esc(leadSub) }),
      last ? FB.kpi('Winner', champ ? ctx.club(champ, c.winner && c.winner.tid) : '—', { text: true, sub: 'last edition, ' + esc(FB.currentSeason(c).season) })
        : m.field_partial ? FB.kpi('Winner favourite', '—', { text: true, sub: 'shown once the top-flight clubs enter', tip: 'The clubs in the draw so far are from the lower divisions; the top flight joins in a later round.' })
        : !sim ? goalsTile(fx)
        : FB.kpi((c.favourite_label === 'Winner' || c.favourite_label === 'Champion' || !c.favourite_label ? (c.kind === 'cup' ? 'Winner' : 'Title') : c.favourite_label) + ' favourite', fav && (fav[fk] || fav.p_title) ? ctx.club(fav.team) : '—', { text: true, signal: true, tip: 'Our chance of winning, from the season simulation', sub: fav && (fav[fk] || fav.p_title) ? 'our chance <b class="fb-co-sig">' + pct(fav[fk] || fav.p_title) + '</b> · ' + FB.int(m.n_sims) + ' simulated seasons' : '' }),
      FB.kpi('Top scorer', scorer && scorer.goals ? FB.playerLink(scorer.player_id, scorer.name) : '—', { text: true, sub: scorer && scorer.goals ? scorer.goals + ' goals · xG ' + num(scorer.xg, 1) + ' · ' + esc(scorer.team) : '' }),
      FB.kpi('Season', '<span class="fb-num">' + gp + '<span class="qk-muted">/' + gt + '</span></span>', { sub: isNum(detailNow(m, gp)) ? detailNow(m, gp) + ' of ' + gp + ' played with line-ups' : 'matches played', spark: gt ? '<span class="fb-co-kbar"><i style="width:' + Math.round(100 * gp / gt) + '%"></i></span>' : '' })
    ];
    var played = fx.filter(function (f) { return f.status === 'finished'; });
    var upcoming = fx.filter(function (f) { return f.status === 'scheduled' || f.status === 'live'; });
    var finishedHTML = last ? howItFinished(c, ctx, fx, players, champ, standings) : '';
    body.innerHTML = FB.kpis(kp) + finishedHTML +
      '<section class="qk-section fb-co-sec">' + QK.sectionHead({ kicker: 'Matches', title: 'Next up. Just played.', sub: 'Our home, draw and away chance for each match to come; the score and xG for each one played.' }) +
      FB.grid(
        (last && !upcoming.length ? '' : FB.card('Coming up', 'Our home, draw and away chance for each; kick-off in your time zone.', upcoming.length ? '<div class="fb-fxlist">' + upcoming.slice(0, 8).map(function (f) { return FB.fixtureRow(f, { slug: c.slug, date: true, round: true }); }).join('') + '</div>' : cardMsg('No fixtures scheduled.'), { span: 6, foot: '<span></span><a href="' + esc(FB.href.comp(c.slug, 'fixtures')) + '">All fixtures →</a>' })) +
        FB.card('Latest results', 'Score and xG; the score opens the match centre.', played.length ? '<div class="fb-fxlist">' + played.slice(-8).reverse().map(function (f) { return FB.fixtureRow(f, { slug: c.slug, date: true, round: true }); }).join('') + '</div>' : cardMsg('No results yet.'), { span: last && !upcoming.length ? 12 : 6, foot: '<span></span><a href="' + esc(FB.href.comp(c.slug, 'fixtures', { view: 'played' })) + '">All results →</a>' })
      ) + '</section>' +
      (sim && !last ? '<section class="qk-section fb-co-sec">' + QK.sectionHead({ kicker: last ? 'Last edition' : 'Title race', title: last ? 'How it finished' : 'Who wins ' + winnerWord(c) + '?', sub: last ? '' : 'Our chances from ' + FB.int(m.n_sims) + ' simulated seasons.' }) +
      FB.grid(
        FB.card('Who wins ' + esc(winnerWord(c)), last ? 'This edition is over.' : 'Our chance of winning ' + esc(winnerWord(c)) + ', from ' + FB.int(m.n_sims) + ' simulated seasons.', '<div id="co-race"></div>', { span: superCard(c, 5) ? 7 : 12, foot: last ? '' : '<span>Top ten</span><span class="fb-co-links2">' + (FB.race && FB.race.eligible(c) ? '<a href="' + esc(FB.href.comp(c.slug, 'race')) + '">How the race is shaping up →</a>' : '') + '<a href="' + esc(FB.href.comp(c.slug, 'odds')) + '">Every club\'s chances →</a></span>' }) +
        superCard(c, 5)
      )
      : '') +
      '<div id="co-hist-wrap"></div>' + (sim && !last ? '</section>' : '') +
      (!(sim && !last) && superCard(c, 12) ? '<section class="qk-section fb-co-sec">' + FB.grid(superCard(c, 12)) + '</section>' : '') +
      '<section class="qk-section fb-co-sec">' + QK.sectionHead({ kicker: 'More', title: 'Players, history and the model' }) +
      '<div class="fb-co-more">' +
        '<a class="qk-card is-link fb-co-morel" href="' + esc(FB.href.comp(c.slug, 'races')) + '"><b>The Golden Boot</b><span>Goals, assists, xG and the top-scorer race' + (sim ? ', with our chances' : '') + '.</span></a>' +
        '<a class="qk-card is-link fb-co-morel" href="' + esc('#/scout?view=leaders&c=' + FB.enc(c.slug)) + '"><b>Leaders in the Scouting Room</b><span>Every player in ' + esc(c.short_name || c.name) + ', the top five and bottom three on each position’s key numbers.</span></a>' +
        '<a class="qk-card is-link fb-co-morel" href="' + esc(FB.href.comp(c.slug, 'seasons')) + '"><b>History</b><span>' + seasons.length + ' edition' + (seasons.length === 1 ? '' : 's') + ' on record, the champions and the titles leaderboard.</span></a>' +
        '<a class="qk-card is-link fb-co-morel" href="' + esc('#/model/methodology?c=' + FB.enc(c.slug)) + '"><b>How we model it</b><span>The settings, the calibration and the format behind ' + esc(c.short_name || c.name) + '’s pages.</span></a>' +
      '</div></section>';
    // race
    var race = probs.map(function (pp) { return { team: pp.team, p: has(pp[fk]) ? pp[fk] : (pp.p_title || 0) }; }).sort(function (a, b) { return b.p - a.p; }).filter(function (r) { return r.p > 0; }).slice(0, 10);
    var rb = $(el, 'co-race');
    if (!rb) { /* not simulated: no race card */ }
    else if (last) rb.innerHTML = cardMsg('This edition is over' + (champ ? ': ' + esc(champ) + ' won it' : '') + '. The next edition is not in the data yet, so there is nothing to simulate.');
    else if (m.field_partial) rb.innerHTML = cardMsg('Winner chances appear once the top flight is in the draw.');
    else if (race.length) rb.innerHTML = chanceList(ctx, c, race, { limit: 10, oursName: 'Our chance of winning ' + winnerWord(c) }) +
      FB.note(race[0].p >= 0.5 ? 'Even at ' + FB.pct(race[0].p) + ', ' + esc(race[0].team) + ' miss out about ' + Math.max(1, Math.round(10 * (1 - race[0].p))) + (Math.max(1, Math.round(10 * (1 - race[0].p))) === 1 ? ' time' : ' times') + ' in 10. The bars are our chances from the simulated seasons.'
        : 'No one is better than a coin flip yet: ' + esc(race[0].team) + ' lead the way at ' + FB.pct(race[0].p) + '. The bars are our chances from the simulated seasons.');
    else rb.innerHTML = cardMsg(m.unsimulated ? 'National-team competitions are not simulated.' : 'No simulation for this competition yet.');
    // leaders
    var mini = function (key, label, fmt) {
      var rs = players.filter(function (pp) { return has(pp[key]) && (key !== 'rating' ? pp[key] > 0 : pp.qualified); }).sort(function (a, b) { return b[key] - a[key]; }).slice(0, 5);
      if (!rs.length) return '';
      return '<div class="fb-co-mini"><div class="qk-kicker">' + esc(label) + '</div><ol>' + rs.map(function (pp) {
        return '<li>' + FB.playerLink(pp.player_id, pp.name) + '<span class="qk-muted fb-co-mt">' + esc(pp.team) + '</span><b class="fb-num">' + FB.fmtMetric(pp[key], fmt) + '</b></li>';
      }).join('') + '</ol></div>';
    };
    var minis = [mini('goals', 'Goals', 'int'), mini('assists', 'Assists', 'int'), mini('xg', 'Expected goals', '1'), mini('rating', 'Rating', '2')].filter(Boolean).join('');
    void minis;
    // run-by-run
    var snaps = ((d.history || {}).snapshots || []).filter(function (s) { return s.title; });
    if (snaps.length >= 2 && !last) {
      $(el, 'co-hist-wrap').innerHTML = '<div class="fb-mt">' + FB.card('How the race has moved', 'Our chance of winning ' + esc(winnerWord(c)) + ' after each model run (hourly), the six likeliest clubs.', FB.chartBox('co-hist', 300, 'Our title chances over time'), { foot: '<span>' + snaps.length + ' model runs</span><a href="' + esc(FB.href.comp(c.slug, 'odds', { view: 'history' })) + '">Every series →</a>' }) + '</div>';
      historyChart($(el, 'co-hist'), snaps, 'title', 6, 'Chance of winning');
    }
  });
};

/* The super cups fold into their host's page as a fixture (round 9): a national super cup into its country's league,
   the continental ones into their club competition. */
var SUPER_HOST = { 'uefa-super-cup': 'champions-league', 'recopa-sudamericana': 'libertadores', 'campeones-cup': 'mls', 'campeon-de-campeones': 'liga-mx', 'supercopa-argentina': 'liga-argentina' };
function superOf(c) {
  var out = null;
  FB.comps().forEach(function (s) {
    if (out || !s.ok || FB.familyOf(s) !== 'super') return;
    var host = SUPER_HOST[s.slug];
    if (!host) { var l = FB.comps().filter(function (x) { return x.kind !== 'cup' && x.country === s.country; })[0]; host = l ? l.slug : null; }
    if (host === c.slug) out = s;
  });
  return out;
}
FB.superOf = superOf;
function superCard(c, span) {
  var s = superOf(c);
  if (!s) return '';
  var f = s.next || s.last;
  if (!f) return '';
  var done = isNum(f.hs) && isNum(f.as);
  var row = FB.fixtureRow(FB.merge(f, { status: f.status || (done ? 'finished' : 'scheduled') }), { slug: s.slug, date: true });
  return FB.card(esc(s.name), done ? 'The latest edition: who lifted it.' : 'The next edition: our home, draw and away chance.', '<div class="fb-fxlist">' + row + '</div>', { span: span, foot: '<span></span><a href="' + esc(FB.href.comp(s.slug)) + '">' + esc(s.short_name || s.name) + ' page →</a>' });
}
/* The Golden Boot tab: the top-scorer race (our chance from the simulated seasons, where the competition is simulated)
   beside the leaders on goals, assists, expected goals and the match rating; everything else on players lives in the
   Scouting Room (a link). */
LIVE.races = function (el, body, c, d0) {
  body.innerHTML = FB.loading('lines', 6);
  return FB.compFiles(c.slug, ['player_leaders', 'players_live']).then(function (d1) {
    if (!FB.alive(el)) return;
    var race = ((d1.player_leaders || {}).top_scorer || []).filter(function (r) { return isNum(r.model); });
    var players = (d1.players_live || {}).players || [];
    var goals = players.filter(function (p) { return p.goals > 0; }).sort(function (a, b) { return (b.goals - a.goals) || ((b.xg || 0) - (a.xg || 0)); }).slice(0, 12);
    body.innerHTML = FB.grid(
      FB.card(race.length ? 'Who wins the Golden Boot?' : 'The scoring chart', race.length ? 'Our chance of finishing as the top scorer, from the same simulated seasons as the table.' : 'Goals so far, and the expected goals behind them.', '<div id="co-gb"></div>', { span: 6 }) +
      leadersCard(c, 6)) +
      '<p class="fb-cap fb-mt">Every player, every metric, against the same position: <a href="' + esc('#/scout?view=leaders&c=' + FB.enc(c.slug)) + '">the Scouting Room’s leaders for ' + esc(c.short_name || c.name) + ' →</a></p>';
    var gb = $(el, 'co-gb');
    if (race.length) gb.innerHTML = FB.chances(race.map(function (r) { return { label: r.name, sub: r.goals + ' goals', p: r.model, href: r.id ? FB.href.player(r.id) : null }; }), { limit: 12, oursName: 'Our chance of finishing top scorer' });
    else gb.innerHTML = goals.length ? '<ol class="fb-co-perf">' + goals.map(function (p) { return '<li>' + FB.playerLink(p.player_id, p.name) + '<span class="qk-muted fb-co-mt">' + esc(p.team) + '</span><b class="fb-num">' + p.goals + '</b><span class="qk-muted fb-num">xG ' + num(p.xg, 1) + '</span></li>'; }).join('') + '</ol>' : cardMsg('No goals yet.');
    $(el, 'co-leaders').innerHTML = leadersMinis(players) || cardMsg('No player data yet.');
    raceOverTime(el, body, c, d0, players);
  });
};
/* Round 9, Phase 4: the Golden Boot and the assists race over time, from the clubs' match logs
   (data/<slug>/players/<club-slug>.json, which the competition already writes): the leading six, goals or assists
   added up match by match, on the calendar. */
function raceOverTime(el, body, c, d0, players) {
  var tm = (d0.teams || {}).teams || {};
  var host = document.createElement('section');
  host.className = 'qk-section fb-co-sec';
  body.appendChild(host);
  var draw = function (key) {
    var top = players.filter(function (p) { return (p[key] || 0) > 0 && tm[p.team] && tm[p.team].slug; }).sort(function (a, b) { return (b[key] - a[key]) || ((b.xg || 0) - (a.xg || 0)); }).slice(0, 6);
    if (top.length < 2) { host.innerHTML = ''; return; }
    var slugs = uniq(top.map(function (p) { return tm[p.team].slug; }));
    Promise.all(slugs.map(function (s) { return FB.load(c.slug + '/players/' + s + '.json'); })).then(function (docs) {
      if (!FB.alive(el)) return;
      var logs = {};
      docs.forEach(function (d) { var ps = (d || {}).players || {}; Object.keys(ps).forEach(function (id) { logs[String(id)] = ps[id].matches || []; }); });
      var field = key === 'goals' ? 'g' : 'a';
      var series = top.map(function (p, i) {
        var ms = (logs[String(p.player_id)] || []).slice().sort(function (a, b) { return String(a.date).localeCompare(String(b.date)); });
        var s = 0, data = [];
        ms.forEach(function (m) { s += m[field] || 0; var t = FB.parseDate(m.date); if (t) data.push([t.getTime(), s]); });
        return { name: FB.surname(p.name), label: FB.surname(p.name) + ' ' + s, data: data, step: true };
      }).filter(function (x) { return x.data.length; });
      host.innerHTML = QK.sectionHead({ kicker: key === 'goals' ? 'The race' : 'The assists race', title: key === 'goals' ? 'The Golden Boot race, match by match' : 'Who sets them up, match by match',
        sub: 'The leading six, their ' + (key === 'goals' ? 'goals' : 'assists') + ' in this competition added up after each match, from the clubs’ match logs.', actions: FB.seg('co-gbk', [['goals', 'Goals'], ['assists', 'Assists']], key, 'Race') }) +
        '<div class="qk-card"><div class="qk-card-body"><div id="co-gbr" class="qk-chart" style="--h:400px" role="img" aria-label="The race over time"></div></div></div>';
      QKC.line(host.querySelector('#co-gbr'), { xType: 'time', series: series, step: 'end', endLabels: true, yMin: 0,
        xFmt: function (v) { var d = new Date(v); return d.getDate() + ' ' + FB.MONTHS[d.getMonth()]; }, xName: 'Date', yName: key === 'goals' ? 'Goals' : 'Assists', label: 'The race over time' });
      FB.wireSeg(host, 'co-gbk', function (v) { draw(v); });
    });
  };
  draw('goals');
}
/* A finished edition leads with how it finished: the final (or the champions' table), the champions' road through
   the knockout with the scores, and the Golden Boot podium. */
function howItFinished(c, ctx, fx, players, champ, standings) {
  var done = (fx || []).filter(function (f) { return f.status === 'finished' && isNum(f.hs) && isNum(f.as); });
  var fin = done.filter(function (f) { return f.round === 'final'; }).slice(-1)[0] || null;
  var winner = champ || (fin ? (fin.hs > fin.as ? fin.home : fin.as > fin.hs ? fin.away : null) : (standings[0] || {}).team);
  if (!winner) return '';
  var hero = '';
  if (fin) {
    var g = FB.heroGame(FB.toGame(ctx.withIds(fin), c.slug));
    hero = QK.splitHero(g, { tag: 'The final', chip: FB.fmtDate(fin.date, { year: true }), compact: true, note: false });
  }
  var road = done.filter(function (f) { return (f.home === winner || f.away === winner) && f.stage && f.stage !== 'league' && f.stage !== 'group' && f.stage !== 'qualifying'; });
  var top = (players || []).filter(function (p) { return p.goals > 0; }).sort(function (a, b) { return (b.goals - a.goals) || (b.assists - a.assists) || ((a.minutes || 0) - (b.minutes || 0)); }).slice(0, 3);
  var podium = top.length ? '<ol class="fb-co-podium">' + top.map(function (p, i) {
    return '<li><span class="qk-outline num">' + (i + 1) + '</span><span class="nm">' + FB.playerLink(p.player_id, p.name) + '<small>' + esc(p.team) + '</small></span><b class="fb-num">' + p.goals + '</b><span class="qk-muted fb-num">' + (p.assists || 0) + ' ast</span></li>';
  }).join('') + '</ol>' : cardMsg('No goals recorded.');
  var table = !fin && standings.length ? '<ol class="fb-co-podium">' + standings.slice(0, 4).map(function (r, i) { return '<li><span class="qk-outline num">' + (i + 1) + '</span><span class="nm">' + ctx.club(r.team) + '</span><b class="fb-num">' + r.pts + '</b><span class="qk-muted">pts</span></li>'; }).join('') + '</ol>' : '';
  return '<section class="qk-section fb-co-sec">' + QK.sectionHead({ kicker: 'How it finished', title: winner + (fin ? ' won it' : ' are champions'), sub: (fin ? 'The final, ' : 'The top of the final table, ') + 'the road there and the top scorers of the ' + esc(FB.currentSeason(c).season || '') + ' edition.' }) +
    (hero ? '<div class="fb-co-finhero">' + hero + '</div>' : '') +
    FB.grid(
      FB.card(fin ? 'The road to the title' : 'The final table', fin ? esc(winner) + '’s knockout matches, oldest first.' : 'Points, the champions first.', fin ? (road.length ? '<div class="fb-fxlist">' + road.map(function (f) { return FB.fixtureRow(ctx.withIds(f), { slug: c.slug, date: true, round: true }); }).join('') + '</div>' : cardMsg('No knockout matches on record.')) : table, { span: 7, foot: '<span></span><a href="' + esc(FB.href.comp(c.slug, fin ? 'bracket' : 'table')) + '">' + (fin ? 'The whole bracket →' : 'The whole table →') + '</a>' }) +
      FB.card('The Golden Boot', 'The top scorers of the edition.', podium, { span: 5, foot: '<span></span><a href="' + esc(FB.href.comp(c.slug, 'races')) + '">Every scorer →</a>' })
    ) + '</section>';
}
function leadersMinis(players) {
  var mini = function (key, label, fmt) {
    var rs = players.filter(function (pp) { return has(pp[key]) && (key !== 'rating' ? pp[key] > 0 : pp.qualified); }).sort(function (a, b) { return b[key] - a[key]; }).slice(0, 5);
    if (!rs.length) return '';
    return '<div class="fb-co-mini"><div class="qk-kicker">' + esc(label) + '</div><ol>' + rs.map(function (pp) {
      return '<li>' + FB.playerLink(pp.player_id, pp.name) + '<span class="qk-muted fb-co-mt">' + esc(pp.team) + '</span><b class="fb-num">' + FB.fmtMetric(pp[key], fmt) + '</b></li>';
    }).join('') + '</ol></div>';
  };
  return [mini('goals', 'Goals', 'int'), mini('assists', 'Assists', 'int'), mini('xg', 'Expected goals', '1'), mini('rating', 'Rating', '2')].filter(Boolean).join('');
}
function leadersCard(c, span) {
  return FB.card('Leaders', 'This ' + (c.scope === 'international' ? 'edition' : 'season') + ', every player in the competition.', '<div id="co-leaders" class="fb-co-minis"></div>', { span: span, foot: '<span></span><a href="' + esc(FB.href.comp(c.slug, 'players')) + '">All players →</a>' });
}
/* In place of the favourite on a competition with no simulation: goals per match, from the matches played. */
function goalsTile(fx) {
  var done = (fx || []).filter(function (f) { return f.status === 'finished' && isNum(f.hs) && isNum(f.as); });
  var g = done.reduce(function (a, f) { return a + f.hs + f.as; }, 0);
  return FB.kpi('Goals per match', done.length ? num(g / done.length, 2) : '—', { sub: done.length ? FB.int(g) + ' goals in ' + done.length + ' matches' : 'no match played yet' });
}

/* Top and bottom performers (QKL.leaders): all players on our value model, then each position group on its spec
   headline set, then the clubs (data/<slug>/performers.json, oddsmarkets/football/analytics/performers.py: qualified
   players only, the spec's 450 minutes, 900 for goalkeepers, and the competition's floor). The section is left out
   while nobody qualifies (a cup early in its run). */
function performers(host, c) {
  if (!host || !window.QKL || !QKL.leaders || !FB.hasFile(c.slug, 'players_live')) return;
  Promise.all([FB.load(c.slug + '/performers.json'), FB.clubsIndex()]).then(function (arr) {
    var pf = arr[0];
    if (!FB.alive(host) || !pf || !(pf.views || []).length) return;
    QKL.leaders(host, { data: pf, title: c.kind === 'cup' ? (c.scope === 'international' ? 'Who stands out, and who is struggling' : 'Who leads the competition, and who is struggling') : 'Who leads the league, and who is struggling',
      sub: 'The top five and the bottom five on each key number: every player on our value model first, then each position on the numbers that matter for it, and the clubs. Qualified players only; each name opens the player page.',
      team: function (k) {
        if (!/^\d+$/.test(String(k))) return { name: k, abbr: FB.clubCode(k) };
        var nm = FB.clubName(k);
        return { name: nm, abbr: nm ? FB.clubCode(nm) : '', colour: FB.clubColour(k), logo: FB.crestUrl(k), href: FB.href.club(k, { c: c.slug }) };
      },
      href: function (id) { return FB.href.player(id, { c: c.slug }); } });
  });
}

/* Our chances after each model run, 538-style (QKC.forecast): one line per club labelled at its end, no legend. */
function historyChart(box, snaps, key, n, yName) {
  var lastS = snaps[snaps.length - 1][key] || {};
  var teams = Object.keys(lastS).sort(function (a, b) { return lastS[b] - lastS[a]; }).filter(function (t) { return lastS[t] > 0.003; }).slice(0, n || 8);
  if (!teams.length) teams = Object.keys(lastS).slice(0, 3);
  if (!teams.length) { box.style.height = 'auto'; box.innerHTML = cardMsg('Nothing recorded for this series.'); return; }
  var shortName = function (t) { var w = String(t).split(' '); return t.length > 12 && w.length > 1 ? w.slice(0, -1).map(function (x) { return x.charAt(0) + '.'; }).join(' ') + ' ' + w[w.length - 1] : t; };
  var series = teams.map(function (t) { return { name: t, label: shortName(t), data: snaps.map(function (s) { return isNum((s[key] || {})[t]) ? s[key][t] : 0; }) }; });
  var top = Math.max.apply(null, series.map(function (x) { return Math.max.apply(null, x.data.concat([0])); }).concat([0.01]));
  QKC.forecast(box, {
    x: snaps.map(function (s) { return s.ts; }), xType: 'time', xLabel: function (v) { return FB.fmtStamp(new Date(v)); },
    xFmt: function (v) { var dd = new Date(v); return isNaN(dd.getTime()) ? '' : dd.getDate() + ' ' + FB.MONTHS[dd.getMonth()]; },
    yMax: top < 0.6 ? 'auto' : 1, xName: 'Model run (date)', yName: yName || 'Our chance', label: 'Our chances after each model run',
    series: series
  });
}

function modelCard(c, d) {
  var m = d.meta || {}, model = m.model || {}, cal = m.calibration || {}, t = d.table || {};
  var tiles = [
    FB.kpi('Simulations', simulated(m) ? FB.int(m.n_sims) : 'none', { sub: m.unsimulated ? 'national teams are not simulated' : !simulated(m) ? 'nothing to simulate yet' : (isNum(m.runtime_s) ? 'run in ' + num(m.runtime_s, 1) + ' s' : '') }),
    FB.kpi('Training matches', isNum(m.training_matches) ? FB.int(m.training_matches) : '—', { sub: model.params_method ? esc(METHOD_LABELS[model.params_method] || model.params_method) : '' }),
    FB.kpi('Match detail', isNum(detailNow(m, m.games_played)) ? FB.int(detailNow(m, m.games_played)) : '—', { sub: 'matches with line-ups this ' + (c.scope === 'international' ? 'edition' : 'season') + (isNum(m.detail_matches) ? ' · ' + FB.int(m.detail_matches) + ' in the store' : '') }),
    dataTile(m)
  ];
  var kv = [];
  if (isNum(model.dc_xi)) kv.push(['Time decay', model.dc_xi + ' per day (half-life ' + Math.round(Math.log(2) / model.dc_xi) + ' days)']);
  if (isNum(model.dc_weight)) kv.push(['Dixon-Coles weight', model.dc_weight + (model.dc_weight >= 1 ? ' (Elo only for clubs the fit does not know)' : ' (the rest Elo)')]);
  if (isNum(model.elo_home_advantage)) kv.push(['Elo home advantage', model.elo_home_advantage + ' points']);
  if (isNum(model.elo_k_league)) kv.push(['Elo K', String(model.elo_k_league)]);
  if (model.dc_fitted === false) kv.push(['Dixon-Coles', 'not fitted: too few matches, Elo only']);
  if (isNum(cal.draw_rate)) kv.push(['Measured draw rate', pct(cal.draw_rate)]);
  if (isNum(cal.mean_goals)) kv.push(['Goals per team per match', num(cal.mean_goals, 2)]);
  if (isNum(cal.home_win_rate)) kv.push(['Home wins', pct(cal.home_win_rate)]);
  var fmt = [];
  if (c.kind === 'liga') fmt.push('30 clubs in two zones; the top 8 of each zone reach a single-match Round of 16. The Tabla Anual decides the continental berths; the worst three-season promedio and the last club in the Tabla Anual go down.');
  else if (c.kind === 'cup' && CUP_KIND_TEXT[c.cup_kind]) fmt.push('Format: ' + CUP_KIND_TEXT[c.cup_kind] + '.');
  else if (t.conferences) fmt.push(Object.keys(t.conferences).length + ' ' + lc(t.group_label || 'conference') + 's' + (t.matches_per_team ? ', ' + t.matches_per_team + ' matches per club' : '') + '.');
  else if (t.matches_per_team) fmt.push('One table, ' + t.matches_per_team + ' matches per club.');
  if (t.split) fmt.push('Split season: after the regular season the table splits into groups of ' + t.split.top + ', ' + t.split.europe + ' and ' + t.split.relegation + (t.split.halve_points ? ', carrying half their points' : '') + '.');
  if (t.h2h_tiebreak || m.h2h_tiebreak) fmt.push('The real rules break level points on head-to-head first; the simulation uses goal difference.');
  return FB.kpis(tiles, 'fb-co-k4') + (kv.length ? '<dl class="fb-co-kv">' + kv.map(function (x) { return '<dt>' + esc(x[0]) + '</dt><dd>' + esc(x[1]) + '</dd>'; }).join('') + '</dl>' : '') +
    (fmt.length ? '<ul class="fb-co-fmt">' + fmt.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul>' : '');
}

function dataTile(m) { return FB.dataTile(m, 'Data'); }

function seasonPills(c, list, activeSid) {
  if (!list.length) return cardMsg('No other season on record.');
  return '<div class="fb-co-pills">' + list.map(function (s) {
    var h = s.source === 'live' ? FB.href.comp(c.slug) : FB.href.comp(c.slug, 'table', { s: s.sid });
    var who = s.champion && s.champion.team ? (s.champion.tid && FB.clubName(s.champion.tid)) || s.champion.team : '';
    return '<a class="fb-co-pill' + (String(s.sid) === String(activeSid) ? ' on' : '') + '" href="' + esc(h) + '"><b>' + esc(s.season || s.name || s.sid) + '</b><span>' +
      (s.source === 'live' ? (s.status === 'last_edition' ? 'last edition' : 'current') : esc(who || s.source)) + '</span></a>';
  }).join('') + '</div>';
}

// ── table ─────────────────────────────────────────────────────────────────

LIVE.table = function (el, body, c, d0, q) {
  if (c.kind === 'liga') return ligaTable(el, body, c, d0, q);
  var prof = FB.race && FB.race.eligible(c);
  return FB.compFiles(c.slug, ['table', 'probs', 'strength'].concat(prof ? ['analytics'] : [])).then(function (d1) {
    if (!FB.alive(el)) return;
    var d = FB.merge(d0, d1), ctx = makeCtx(c, d), t = d.table;
    var formOf = {};
    ((d.strength || {}).rows || []).forEach(function (r) { if ((r.form_results || []).length) formOf[r.team] = r.form_results; });
    ctx.form = formOf;
    /* each club's two strongest strengths-and-weak-spots chips (race.js), linking to its team card on the Race tab */
    if (prof && d.analytics && t) {
      var RM = FB.race.model(c, d);
      ctx.chips = {};
      (t.standings || []).forEach(function (r) { ctx.chips[r.team] = FB.race.topChips(FB.race.chipsFor(RM, r.team), 2); });
    }
    if (!t || (!(t.standings || []).length && !t.conferences)) { body.innerHTML = FB.empty('No table', 'This competition has no table: see its knockout and fixtures.'); return; }
    var isCup = c.kind === 'cup';
    var sub = esc(t.season || '') + ' · ' + t.games_played + '/' + t.total_games + ' matches' + (t.h2h_tiebreak ? ' · level points broken by goal difference here (the league uses head-to-head)' : '');
    var html = '';
    if (t.conferences) {
      var label = t.group_label || (isCup ? 'Group' : 'Conference');
      var names = Object.keys(t.conferences);
      html += legend(t.bands) + '<div class="fb-co-groups' + (names.length > 2 ? ' many' : '') + '">' + names.map(function (g, i) {
        return FB.card(isCup ? label + ' ' + esc(g) : esc(g) + ' Conference', null, '<div id="co-tg-' + i + '"></div>', { flush: true });
      }).join('') + '</div>';
      if ((t.overall || []).length) html += '<div class="fb-mt">' + FB.card(esc(t.overall_label || 'Overall'), 'Every club on one table.', '<div id="co-tov"></div>', { flush: true }) + '</div>';
    } else {
      html += FB.card('Standings', sub, legend(t.bands) + '<div id="co-tmain"></div>', { flush: false, cls: 'fb-co-tcard' });
    }
    var rows = t.standings || t.overall || [];
    var heat = !t.unsimulated && rows.length && (rows[0].p_final_pos || rows[0].p_pos || []).length && !(t.conferences && isCup && c.cup_kind === 'groups');
    html += '<div class="fb-mt">' + FB.card('Where they will finish', t.split ? 'Our chance of each final position after the split, from the simulated seasons.' : 'Our chance of each final position, from the simulated seasons.',
      heat || t.conferences ? '<div id="co-heat"></div>' : cardMsg(t.unsimulated ? 'Not simulated: national-team competitions show the tables as played.' : 'No distribution for this competition.')) + '</div>';
    var up = (t.fixtures || []).filter(function (f) { return !f.done; }).sort(function (a, b) { return String(a.date || '').localeCompare(String(b.date || '')); });
    html += '<div class="fb-mt">' + FB.card('Still to play', up.length + ' match' + (up.length === 1 ? '' : 'es') + ' left in the table.', '<div id="co-up"></div>', { flush: true }) + '</div>';
    body.innerHTML = html;
    var plain = !!t.unsimulated;
    if (t.conferences) {
      Object.keys(t.conferences).forEach(function (g, i) { standings($(el, 'co-tg-' + i), ctx, t.conferences[g], t.bands, { titleLabel: null, maxUp: 2, plain: plain, compact: true }); });
      if ((t.overall || []).length) standings($(el, 'co-tov'), ctx, t.overall, [], { titleLabel: 'Shield', maxUp: 0 });
    } else if (t.split) {
      standings($(el, 'co-tmain'), ctx, t.standings, t.bands, { titleLabel: 'Title', extra: [{ label: 'Top ' + t.split.top, key: 'p_top_group', tip: 'Reaches the championship group' }] });
    } else {
      standings($(el, 'co-tmain'), ctx, t.standings, t.bands, { titleLabel: isCup ? 'Winner' : 'Title', plain: plain });
    }
    if (heat && !t.conferences) posHeat($(el, 'co-heat'), rows, function (r) { return t.split ? (r.p_final_pos || r.p_pos) : r.p_pos; }, t.bands);
    else if (t.conferences && !plain && !(isCup && c.cup_kind === 'groups')) {
      var hb = $(el, 'co-heat');
      var cn = Object.keys(t.conferences).filter(function (n) { return (t.conferences[n] || []).length && (t.conferences[n][0].p_pos || []).length; });
      if (!cn.length) hb.innerHTML = cardMsg('No distribution for this competition.');
      else {
        hb.innerHTML = '<div class="fb-co-groups">' + cn.map(function (n, i) { return '<div><div class="qk-kicker">' + esc(n) + '</div><div id="co-heat-' + i + '"></div></div>'; }).join('') + '</div>';
        cn.forEach(function (n, i) { posHeat($(el, 'co-heat-' + i), t.conferences[n], function (r) { return r.p_pos; }, t.bands); });
      }
    } else if (t.conferences) $(el, 'co-heat').innerHTML = cardMsg(plain ? 'Not simulated: tables as played.' : 'Each group table carries our qualification chances.');
    upcomingTable($(el, 'co-up'), ctx, up);
    chancesSection(el, body, c, d0, q, 'table');
  });
};

/* The standings as a v2 leaderboard: the table as it stands, then our projection and our chances as inline bars
   (0-100%, the bar is the chance). */
function standings(box, ctx, rows, bands, o) {
  o = o || {};
  var ups = (bands || []).filter(function (b) { return b.kind === 'up'; }).slice(0, o.maxUp === undefined ? 2 : o.maxUp);
  var downs = (bands || []).filter(function (b) { return b.kind === 'down'; });
  var form = ctx.form || {};
  var hasForm = !o.compact && (rows || []).some(function (r) { return (form[r.team] || []).length; });
  var cols = [
    { key: 'pos', label: '#', num: true, fmt: function (v) { return posCell(v, bands); } },
    { key: 'team', label: clubW(), sticky: true, fmt: function (v, r) { return ctx.club(v, r.tid); } },
    { key: 'played', label: 'P', num: true }, { key: 'w', label: 'W', num: true }, { key: 'd', label: 'D', num: true }, { key: 'l', label: 'L', num: true },
    { key: 'gf', label: 'GF', num: true }, { key: 'ga', label: 'GA', num: true },
    { key: 'gd', label: 'GD', num: true, fmt: function (v) { return isNum(v) ? signed(v, 0) : '—'; } },
    { key: 'pts', label: 'Pts', num: true, fmt: function (v) { return '<b>' + (isNum(v) ? v : '—') + '</b>'; } }
  ];
  if (o.compact) cols.splice(6, 2);
  if (hasForm) cols.push({ key: '_form', label: 'Form', sort: false, tip: 'Last five results, oldest first', fmt: function (v, r) { return QK.formDots((form[r.team] || []).slice(-5)); } });
  var bar = function (key, label, tip) { return { key: key, label: label, type: 'bar', max: 1, tip: tip, fmt: function (v) { return pctFmt(v); } }; };
  if (!o.plain) {
    cols.push({ key: 'exp_pts', label: 'Proj.', num: true, tip: 'Our projected final points (mean of the simulated seasons)', fmt: function (v) { return num(v, 1); } });
    if (!o.compact) cols.push({ key: 'p50', label: 'Range', num: true, sort: false, tip: 'Our 90% range of final points: 5th to 95th percentile of the simulated seasons', fmt: function (v, r) { return rangeBar(r); } });
    if (o.titleLabel !== null) cols.push(bar('p_title', o.titleLabel || 'Title', 'Our chance'));
    (o.extra || []).forEach(function (x) { cols.push(bar(x.key, x.label, x.tip)); });
    ups.forEach(function (b) { cols.push(bar('_b_' + b.key, b.label, 'Our chance of finishing in this band')); });
    if (downs.length) cols.push(bar('_drop', downs.length > 1 ? 'Drop' : downs[0].label, 'Our chance: ' + downs.map(function (b) { return b.label; }).join(' + ')));
  }
  /* the strengths chips live on the Teams tab (strengths and weaknesses): the table stays inside its card at 1440 */
  if (ctx.chips && !o.compact && o.chips) cols.push({ key: '_prof', label: 'Profile', sort: false, tip: 'The club\'s biggest strength and weak spot against the rest of the league; open the Race tab for its team card', fmt: function (v, r) {
    var ch = ctx.chips[r.team] || [];
    return ch.length ? '<a class="fb-rc-chips tbl" href="' + esc(FB.href.comp(ctx.slug, 'race', { club: r.team })) + '">' + ch.map(FB.race.chipHTML).join('') + '</a>' : '<span class="qk-muted">—</span>';
  } });
  var list = (rows || []).map(function (r) {
    var o2 = FB.merge(r, {});
    ups.forEach(function (b) { o2['_b_' + b.key] = (r.bands || {})[b.key]; });
    o2._drop = downs.reduce(function (s, b) { return s + ((r.bands || {})[b.key] || 0); }, 0);
    return o2;
  });
  QK.leaderboard(box, { columns: cols, rows: list, dense: true, caption: 'Standings' });
}
function rangeBar(r) {
  if (!isNum(r.p05) || !isNum(r.p95)) return '—';
  return '<span class="fb-num qk-muted">' + num(r.p05, 0) + '–' + num(r.p95, 0) + '</span>';
}
function posHeat(box, rows, get, bands) {
  var teams = rows.map(function (r) { return r.team; });
  var n = (get(rows[0]) || []).length;
  if (!n) { box.innerHTML = cardMsg('No distribution data.'); return; }
  var data = [];
  rows.forEach(function (r, yi) { (get(r) || []).forEach(function (v, xi) { if (v >= 0.001) data.push([xi, yi, v]); }); });
  var xs = []; for (var i = 1; i <= n; i++) xs.push(String(i));
  box.classList.add('fb-chart');
  box.style.setProperty('--h', Math.max(220, teams.length * (teams.length > 24 ? 19 : 24) + 90) + 'px');
  QKC.heatmap(box, { x: xs, y: teams, data: data, min: 0, max: 1, fmt: function (v) { return pct(v, v < 0.1 ? 1 : 0); }, cellLabels: n <= 20, xName: 'Finishing position', yName: 'Team', label: 'Finishing-position distribution' });
}
function upcomingTable(box, ctx, list) {
  if (!list.length) { box.innerHTML = '<div class="qk-card-body">' + cardMsg('No matches left to play.') + '</div>'; return; }
  FB.table(box, [
    { key: 'date', label: 'Date', fmt: function (v) { return esc(v ? FB.fmtDate(v) : '—'); } },
    { key: 'round', label: 'Round', num: true, fmt: function (v) { return esc(v || ''); } },
    { key: 'home', label: 'Home', fmt: function (v) { return ctx.club(v); } },
    { key: 'away', label: 'Away', fmt: function (v) { return ctx.club(v); } }
  ], list.slice(0, 30), { maxHeight: 420 });
}

function ligaTable(el, body, c, d0, q) {
  var view = ['zones', 'anual', 'relegation'].indexOf(q.view) >= 0 ? q.view : 'zones';
  var tabs = (c.tabs || []);
  var opts = [['zones', 'Zones']].concat(tabs.indexOf('anual') >= 0 ? [['anual', 'Tabla Anual']] : []).concat(tabs.indexOf('relegation') >= 0 ? [['relegation', 'Relegation']] : []);
  return FB.compFiles(c.slug, ['zones', 'anual', 'relegation']).then(function (d1) {
    if (!FB.alive(el)) return;
    var d = FB.merge(d0, d1), ctx = makeCtx(c, d);
    body.innerHTML = '<div class="fb-toolbar">' + FB.seg('co-lview', opts, view, 'Table') + '</div><div id="co-lbody" class="fb-mt"></div>';
    FB.wireSeg(body, 'co-lview', function (v) { FB.setQuery({ view: v === 'zones' ? null : v }, true); });
    var b = $(el, 'co-lbody');
    if (view === 'anual') return ligaAnual(el, b, ctx, d.anual);
    if (view === 'relegation') return ligaReleg(el, b, ctx, d.relegation);
    var z = d.zones;
    if (!z) { b.innerHTML = FB.empty('No zone tables yet'); return; }
    var cut = z.qualifiers_per_zone || 8;
    var keys = Object.keys(z.zones || {});
    b.innerHTML = '<p class="fb-cap">' + (z.tournament === 'clausura' ? 'Torneo Clausura' : 'Torneo Apertura') + '. The top ' + cut + ' of each zone reach the Round of 16 (the line marks the cut).</p>' +
      '<div class="fb-co-groups">' + keys.map(function (k, i) { var zz = z.zones[k]; return FB.card('Zona ' + esc(k), zz.games_played + '/' + zz.total_games + ' matches', '<div id="co-z-' + i + '"></div>', { flush: true }); }).join('') + '</div>' +
      '<div class="fb-mt">' + FB.card('Still to play', null, '<div id="co-up"></div>', { flush: true }) + '</div>';
    keys.forEach(function (k, i) {
      FB.table($(el, 'co-z-' + i), [
        { key: 'pos', label: '#', num: true, fmt: function (v) { return '<span class="fb-co-pos' + (v <= cut ? '' : ' out') + '"' + (v <= cut ? ' style="--b:var(--c-3)"' : '') + '>' + v + '</span>'; } },
        { key: 'team', label: clubW(), sticky: true, fmt: function (v) { return ctx.club(v); } },
        { key: 'played', label: 'P', num: true }, { key: 'gd', label: 'GD', num: true, fmt: function (v) { return signed(v, 0); } },
        { key: 'pts', label: 'Pts', num: true, fmt: function (v) { return '<b>' + v + '</b>'; } },
        { key: 'exp_pts', label: 'Proj.', num: true, fmt: function (v) { return num(v, 1); } },
        { key: 'p_top8', label: 'Top 8', num: true, fmt: function (v) { return heatPct(v, 'var(--c-3)'); } },
        { key: 'p_zone_win', label: 'Zone', num: true, tip: 'Wins the zone', fmt: function (v) { return heatPct(v, 'var(--signal)'); } }
      ], z.zones[k].standings || [], { caption: 'Zona ' + k });
    });
    var up = [];
    keys.forEach(function (k) { (z.zones[k].fixtures || []).filter(function (f) { return !f.done; }).forEach(function (f) { up.push(f); }); });
    up.sort(function (a, b2) { return String(a.date || '').localeCompare(String(b2.date || '')); });
    upcomingTable($(el, 'co-up'), ctx, up);
  });
}
/* Argentina's places as they stand (anual.json rows[].berth_now, build_site_liga.berths_now): the champions and the
   cup winner first, the rest of the six Libertadores places down the table (a title still to decide holds one open),
   six Sudamericana places after, and the two relegations (last place, the worst promedio). */
var LIGA_BERTH = {
  lib_auto: ['var(--c-3)', 'Libertadores (a champion)'], lib: ['var(--c-3)', 'Libertadores'],
  lib_open: ['var(--c-4)', 'Libertadores or Sudamericana (an open title)'], sud: ['var(--c-1)', 'Sudamericana'],
  sud_open: ['var(--c-5)', 'Sudamericana if an open title goes to a club already in'],
  down_anual: ['var(--c-8)', 'Down: last in the table'], down_promedio: ['var(--c-2)', 'Down: worst promedio']
};
function ligaAnual(el, b, ctx, a) {
  if (!a) { b.innerHTML = FB.empty('No Tabla Anual yet'); return; }
  var lib = a.berths.libertadores, sud = a.berths.sudamericana, nowB = a.berths.now || {};
  var autos = (nowB.autos || []).map(function (x) { return esc(x.team) + ' (' + esc(x.why) + ')'; });
  var legend = '<div class="qk-legend fb-co-legend">' + ['lib', 'lib_open', 'sud', 'sud_open', 'down_anual', 'down_promedio'].filter(function (k) { return a.rows.some(function (r) { return r.berth_now === k || (k === 'lib' && r.berth_now === 'lib_auto'); }); })
    .map(function (k) { return '<span><i style="--k:' + LIGA_BERTH[k][0] + '"></i>' + esc(LIGA_BERTH[k][1]) + '</span>'; }).join('') + '</div>';
  var sub = 'If the season ended today: ' + lib + ' Libertadores places' + (autos.length ? ', ' + autos.join(', ') + ' already in' : '') +
    (nowB.open_titles ? ', ' + nowB.open_titles + ' held open for titles still to decide' : '') + '; ' + sud + ' Sudamericana; two clubs down.';
  b.innerHTML = FB.card('Tabla Anual', sub, '<p class="fb-cap">' + esc(a.berths.note_en || a.berths.note || '') + '</p>' + legend + '<div id="co-an"></div>') +
    '<div class="fb-mt">' + FB.card('Where they will finish in the Tabla Anual', 'Our chance of each final position.', '<div id="co-anh"></div>') + '</div>';
  var n = a.rows.length;
  var col = function (pos) { return pos <= lib ? 'var(--c-3)' : pos <= lib + sud ? 'var(--c-1)' : pos === n ? 'var(--c-8)' : null; };
  var colOf = function (r) { var k = r.berth_now; return k && LIGA_BERTH[k] ? LIGA_BERTH[k][0] : (k === undefined ? col(r.pos) : null); };
  FB.table($(el, 'co-an'), [
    { key: 'pos', label: '#', num: true, fmt: function (v, r) { var cc = colOf(r); return '<span class="fb-co-pos"' + (cc ? ' style="--b:' + cc + '"' : '') + (r.berth_now && LIGA_BERTH[r.berth_now] ? ' title="' + esc(LIGA_BERTH[r.berth_now][1]) + '"' : '') + '>' + v + '</span>'; } },
    { key: 'team', label: clubW(), sticky: true, fmt: function (v) { return ctx.club(v); } },
    { key: 'played', label: 'P', num: true },
    { key: 'w', label: 'W', num: true }, { key: 'd', label: 'D', num: true }, { key: 'l', label: 'L', num: true },
    { key: 'gd', label: 'GD', num: true, fmt: function (v) { return isNum(v) ? signed(v, 0) : '—'; } },
    { key: 'pts_now', label: 'Pts', num: true, fmt: function (v) { return '<b>' + v + '</b>'; } },
    { key: 'exp_pts', label: 'Proj.', num: true, fmt: function (v) { return num(v, 1); } },
    { key: 'p_champion', label: 'Top', num: true, tip: 'Our chance of finishing top of the Tabla Anual', fmt: function (v) { return heatPct(v, 'var(--signal)'); } },
    { key: 'p_libertadores', label: 'Libertadores', num: true, fmt: function (v) { return heatPct(v, 'var(--c-3)'); } },
    { key: 'p_sudamericana', label: 'Sudamericana', num: true, fmt: function (v) { return heatPct(v, 'var(--c-1)'); } }
  ], a.rows, { caption: 'Tabla Anual' });
  posHeat($(el, 'co-anh'), a.rows, function (r) { return r.p_pos; });
}
function ligaReleg(el, b, ctx, r) {
  if (!r) { b.innerHTML = FB.empty('No relegation data yet'); return; }
  b.innerHTML = FB.grid(FB.card('Relegation', r.rules.places + ' clubs go down.', '<p class="fb-cap">' + esc(r.rules.note_en || r.rules.note || '') + '</p><div id="co-rel"></div>', { span: 7, flush: false }) +
    FB.card('Relegation risk', 'Our chance of going down, by route: the promedio (three-season points per match) or last in the Tabla Anual.', FB.chartBox('co-relc', 420, 'Relegation risk'), { span: 5 }));
  var lo = Math.min.apply(null, r.rows.map(function (x) { return x.p05; }).concat([0.5]));
  var hi = Math.max.apply(null, r.rows.map(function (x) { return x.p95; }).concat([2.5]));
  var span = (hi - lo) || 1;
  FB.table($(el, 'co-rel'), [
    { key: 'pos', label: '#', num: true },
    { key: 'team', label: clubW(), sticky: true, fmt: function (v) { return ctx.club(v); } },
    { key: 'promedio_now', label: 'Promedio', num: true, fmt: function (v) { return num(v, 3); } },
    { key: 'p50', label: 'Projection', sort: false, tip: '5th–95th percentile of the final promedio; the tick is the median', fmt: function (v, x) {
      return '<span class="fb-co-range"><i style="left:' + ((x.p05 - lo) / span * 100).toFixed(1) + '%;width:' + Math.max((x.p95 - x.p05) / span * 100, 1.5).toFixed(1) + '%"></i><b style="left:' + ((x.p50 - lo) / span * 100).toFixed(1) + '%"></b></span>'; } },
    { key: 'p_promedio', label: 'Via promedio', num: true, fmt: function (v) { return riskPct(v); } },
    { key: 'p_anual', label: 'Via anual', num: true, fmt: function (v) { return riskPct(v); } },
    { key: 'p_any', label: 'Relegated', num: true, fmt: function (v) { return '<b>' + riskPct(v) + '</b>'; } }
  ], r.rows, { caption: 'Relegation' });
  var risky = r.rows.filter(function (x) { return x.p_any > 0.001; }).sort(function (a, b2) { return b2.p_any - a.p_any; }).slice(0, 14);
  var box = $(el, 'co-relc');
  if (!risky.length) { box.style.height = 'auto'; box.innerHTML = cardMsg('No club at appreciable risk.'); return; }
  QKC.bar(box, { horizontal: true, stack: true, legend: true, labelWidth: 120, fmt: function (v) { return pct(v); }, valName: 'Our relegation chance', catName: clubW(),
    cats: risky.map(function (x) { return x.team; }), series: [{ name: 'Via promedio', data: risky.map(function (x) { return x.p_promedio; }), color: hexOf('var(--c-2)') }, { name: 'Via Tabla Anual', data: risky.map(function (x) { return x.p_anual; }), color: hexOf('var(--c-7)') }],
    label: 'Relegation risk by route' });
}

// ── fixtures ──────────────────────────────────────────────────────────────

LIVE.fixtures = function (el, body, c, d0, q) {
  var ctx = makeCtx(c, d0);
  var all = ((d0.fixtures || {}).matches || []).map(ctx.withIds);
  if (!all.length) { body.innerHTML = FB.empty('No fixtures yet'); return; }
  fixtureBrowser(el, body, c, ctx, all, q, false);
  calledRound(el, body, c, ctx, all);
};
/* Round 9, Phase 4: "How we called the round": the latest round with three or more finished matches whose chance we
   froze before kick-off (forecast_log.json: id -> [home, draw, away, kick-off, competition]): how often our favourite
   won against how often we expected it to, the biggest surprise, and each match with the chance we gave the result. */
function calledRound(el, body, c, ctx, all) {
  FB.load('forecast_log.json').then(function (log) {
    if (!FB.alive(el) || !log) return;
    var done = all.filter(function (f) { return f.status === 'finished' && isNum(f.hs) && isNum(f.as) && log[String(f.id)]; });
    var rounds = {};
    done.forEach(function (f) { var k = (f.stage || 'league') + '|' + f.round; (rounds[k] = rounds[k] || []).push(f); });
    var keys = Object.keys(rounds).filter(function (k) { return rounds[k].length >= 3; })
      .sort(function (a, b) { var la = rounds[a].map(function (f) { return f.date; }).sort().pop(), lb = rounds[b].map(function (f) { return f.date; }).sort().pop(); return String(lb).localeCompare(String(la)); });
    if (!keys.length) return;
    var ms = rounds[keys[0]].map(function (f) {
      var l = log[String(f.id)], p = [l[0], l[1], l[2]], res = f.hs > f.as ? 0 : f.hs === f.as ? 1 : 2, fav = p.indexOf(Math.max.apply(null, p));
      return { f: f, p: p, res: res, fav: fav, pres: p[res] };
    });
    var hits = ms.filter(function (m) { return m.fav === m.res; }).length;
    var exp = ms.reduce(function (s, m) { return s + m.p[m.fav]; }, 0);
    var upset = ms.slice().sort(function (a, b) { return a.pres - b.pres; })[0];
    var who = function (m) { return m.res === 1 ? 'A draw' : (m.res === 0 ? m.f.home : m.f.away) + ' won'; };
    var host = document.createElement('section');
    host.className = 'qk-section fb-co-sec';
    host.innerHTML = QK.sectionHead({ kicker: 'How we called it', title: 'How we called ' + (FB.roundText(ms[0].f, c.slug) || 'the latest round').replace(/^R(\d)/, 'round $1').toLowerCase(), sub: 'Our chances frozen before kick-off for the ' + ms.length + ' matches of the latest round we logged, against the results.' }) +
      FB.kpis([
        FB.kpi('Our favourite won', hits + ' of ' + ms.length, { signal: true, sub: 'we expected about ' + num(exp, 1) + ' of ' + ms.length }),
        FB.kpi('Biggest surprise', esc(who(upset)), { text: true, sub: esc(upset.f.home + ' ' + upset.f.hs + '–' + upset.f.as + ' ' + upset.f.away) + ': we gave that ' + pct(upset.pres) })
      ]) +
      '<div class="qk-card fb-mt"><div class="qk-card-body"><div class="fb-fxlist">' + ms.map(function (m) {
        return '<div class="fb-co-called' + (m.fav === m.res ? ' hit' : '') + '">' + FB.fixtureRow(m.f, { slug: c.slug, date: true }) + '<span class="fb-co-calledp" title="Our chance of this result before kick-off">' + (m.fav === m.res ? '✓ ' : '') + pct(m.pres) + '</span></div>';
      }).join('') + '</div><p class="fb-cap">The number is the chance we gave the result that happened; a tick marks our favourite winning. A 60% favourite should still lose four times in ten. Our full record: <a href="#/model/calibration">How we’re doing</a>.</p></div></div>';
    body.insertBefore(host, body.firstChild);
  });
}
function fixtureBrowser(el, body, c, ctx, all, q, past) {
  var stages = uniq(all.map(function (f) { return f.stage || 'league'; }));
  var first = {};
  all.forEach(function (f) { var r = String(has(f.round) ? f.round : ''); var dt = String(f.date || '9999'); if (r && (!(r in first) || dt < first[r])) first[r] = dt; });
  var rounds = Object.keys(first).sort(function (a, b) { return first[a].localeCompare(first[b]) || a.localeCompare(b); });
  var teams = uniq(all.map(function (f) { return f.home; }).concat(all.map(function (f) { return f.away; }))).filter(Boolean).sort(function (a, b) { return a.localeCompare(b); });
  var hasUp = all.some(function (f) { return f.status !== 'finished'; });
  var status = past ? 'played' : q.view === 'played' ? 'played' : q.view === 'all' ? 'all' : hasUp ? 'upcoming' : 'played';
  var stageOpts = [['', 'All stages']].concat(stages.length > 1 ? stages.map(function (s) { return [s, FB.stageLabel(s, c.slug)]; }) : []);
  if (rounds.length > 1) stageOpts.push({ group: 'Rounds', items: rounds.map(function (r) { var f0 = all.filter(function (f) { return String(f.round) === r; })[0] || { round: r }; return ['round:' + r, FB.roundText(f0, c.slug)]; }) });
  body.innerHTML = FB.card(past ? 'Results' : 'Fixtures and results', '<span id="co-fxn"></span>',
    FB.toolbar([
      past ? '' : FB.seg('co-fxs', [['upcoming', 'Upcoming'], ['played', 'Played'], ['all', 'All']], status, 'Status'),
      FB.field('Stage or round', FB.select('co-fxst', stageOpts, '', 'Stage or round')),
      FB.field(clubW(), FB.select('co-fxt', [['', 'All ' + clubW().toLowerCase() + 's']].concat(teams.map(function (t) { return [t, t]; })), '', 'Club')),
      past ? '<label class="fb-check"><input type="checkbox" id="co-fxd"> With a match page only</label>' : ''
    ]) + '<div id="co-fxl"></div>');
  var st = $(el, 'co-fxst'), tm = $(el, 'co-fxt'), det = $(el, 'co-fxd');
  FB.wireSeg(body, 'co-fxs', function (v) { status = v; FB.setQuery({ view: v === (hasUp ? 'upcoming' : 'played') ? null : v }); draw(); });
  st.addEventListener('change', draw); tm.addEventListener('change', draw); if (det) det.addEventListener('change', draw);
  function draw() {
    var sv = st.value, tv = tm.value;
    var list = all.filter(function (f) {
      if (sv && sv.indexOf('round:') === 0 && String(f.round) !== sv.slice(6)) return false;
      if (sv && sv.indexOf('round:') !== 0 && (f.stage || 'league') !== sv) return false;
      if (tv && f.home !== tv && f.away !== tv) return false;
      if (status === 'played' && f.status !== 'finished') return false;
      if (status === 'upcoming' && (f.status === 'finished')) return false;
      if (det && det.checked && !f.detail) return false;
      return true;
    });
    list.sort(function (a, b) { return String(a.date || '').localeCompare(String(b.date || '')); });
    if (status === 'played' && !past) list.reverse();
    var cap = 160, shown = list.slice(0, cap);
    $(el, 'co-fxn').textContent = list.length + ' of ' + all.length + ' matches' + (list.length > cap ? ' (first ' + cap + ' shown: narrow with a round or club)' : '');
    if (!shown.length) { $(el, 'co-fxl').innerHTML = FB.empty('No matches', 'Nothing matches the filters.'); return; }
    var html = '', lastDay = null, t = FB.today();
    shown.forEach(function (f) {
      var day = FB.localDay(f.date) || 'TBD';
      if (day !== lastDay) { html += '<div class="fb-co-day' + (day === t ? ' today' : '') + '">' + esc(f.date ? FB.fmtDate(f.date, { year: true }) : 'Date to be confirmed') + (day === t ? ' ' + FB.badge('Today', 'accent') : '') + '</div>'; lastDay = day; }
      html += FB.fixtureRow(f, { slug: c.slug, round: true }) + modelLine(f);
    });
    $(el, 'co-fxl').innerHTML = '<div class="fb-fxlist fb-co-fxl">' + html + '</div>';
  }
  draw();
}
/* Our full forecast for a match still to play: expected goals, the likeliest score, three or more goals, both score. */
function modelLine(f) {
  var m = f.model;
  if (!m || f.status === 'finished' || f.status === 'live') return '';
  var bits = [];
  if (isNum(m.lh)) bits.push('<span data-tip="Our expected goals for each side">Expected goals ' + num(m.lh, 2) + '–' + num(m.la, 2) + '</span>');
  if (m.score) bits.push('<span>Likeliest score ' + esc(m.score) + (isNum(m.p_score) ? ' (' + pct(m.p_score) + ')' : '') + '</span>');
  if (isNum(m.o25)) bits.push('<span>3 or more goals ' + pct(m.o25) + '</span>');
  if (isNum(m.btts)) bits.push('<span>Both score ' + pct(m.btts) + '</span>');
  return bits.length ? '<div class="fb-co-ml">' + bits.join('') + '</div>' : '';
}

// ── bracket ───────────────────────────────────────────────────────────────

LIVE.bracket = function (el, body, c, d0, q) {
  return FB.compFiles(c.slug, ['bracket', 'table', 'probs']).then(function (d1) {
    if (!FB.alive(el)) return;
    setTimeout(function () { if (FB.alive(el)) chancesSection(el, body, c, d0, q, 'bracket'); }, 0);
    var d = FB.merge(d0, d1), ctx = makeCtx(c, d), b = d.bracket;
    if (!b || !(b.rounds || []).length) { body.innerHTML = FB.empty('No knockout picture yet', (b || {}).note || 'The bracket appears once the knockout phase is known.'); return; }
    if (c.kind === 'liga') return ligaBracket(el, body, ctx, b);
    var k = c.kind;
    var labels = FB.merge(FB.ROUND_LABELS, b.round_labels || {});
    var f = b.format || {};
    var sub = k === 'conference' ? (b.confirmed ? 'Seeds confirmed' : 'Seeds as the table stands') + ' · top ' + f.direct_per_conference + ' qualify directly, seeds ' + (f.wildcard_seeds || []).join(' and ') + ' play a wild card'
      : k === 'playoff' ? (b.confirmed ? 'Seeds confirmed' : 'Seeds as the table stands') + ' · top ' + f.direct + ' qualify directly, ' + (f.play_in || []).join('–') + ' play the play-in'
      : (b.confirmed ? 'Ties known from the draw and the results' : 'The bracket as the tables stand');
    var known = b.known || {};
    var rIdx = function (r) { var i = b.rounds.indexOf(r); return i < 0 ? 99 : i; };   // a third-place match after the final
    var kr = Object.keys(known).filter(function (r) { return (known[r] || []).length; }).sort(function (x, y) { return rIdx(x) - rIdx(y); });
    /* each round's ties in the order of the ties they came from, so the road reads across like a bracket */
    known = FB.merge(known, {});
    kr.forEach(function (r, i) {
      if (!i || rIdx(r) === 99) return;
      var prev = known[kr[i - 1]] || [];
      var at = function (pr) { var best = 1e9; prev.forEach(function (q2, j) { if (q2.indexOf(pr[0]) >= 0 || q2.indexOf(pr[1]) >= 0) best = Math.min(best, j); }); return best; };
      known[r] = known[r].slice().sort(function (a, z) { return at(a) - at(z); });
    });
    /* round 9: an unsimulated bracket (national teams) or a finished one is the full road to the final with the scores;
       a simulated one keeps the latest three rounds with our chance of going through on the open ties */
    var unsim = !Object.keys(b.p_cup || {}).length && !Object.keys(b.reach || {}).length;
    var shownRounds = unsim ? kr : kr.slice(-3);
    var fxAll = ((d.fixtures || {}).matches || []).filter(function (f) { return f.status === 'finished' && isNum(f.hs) && isNum(f.as); });
    var tieGoals = function (r, a, bb) {
      var ms = fxAll.filter(function (f) { return String(f.round) === String(r) && ((f.home === a && f.away === bb) || (f.home === bb && f.away === a)); });
      if (!ms.length) ms = fxAll.filter(function (f) { return f.stage !== 'league' && f.stage !== 'group' && ((f.home === a && f.away === bb) || (f.home === bb && f.away === a)); });
      if (!ms.length) return null;
      var ga = 0, gb = 0;
      ms.forEach(function (f) { if (f.home === a) { ga += f.hs; gb += f.as; } else { ga += f.as; gb += f.hs; } });
      return { a: ga, b: gb, legs: ms.length, id: ms[ms.length - 1].id };
    };
    var html = (b.note && !unsim ? FB.note(esc(b.note)) : '');
    if (shownRounds.length) {
      html += '<div class="fb-mt">' + FB.card(unsim ? 'The road to the final' : 'Ties', unsim ? 'Every knockout tie as it was played: the score (two legs added up), the side that went through in bold. Tap a score for the match.' : sub + (kr.length > shownRounds.length ? ' · the latest ' + shownRounds.length + ' rounds' : '') + '. The number is our chance of going through; a decided tie shows its score.',
        '<div class="fb-co-ladder' + (unsim ? ' road' : '') + '">' + shownRounds.map(function (r) {
          var nxt = b.rounds.indexOf(r) >= 0 && b.rounds.indexOf(r) + 1 < b.rounds.length ? b.rounds[b.rounds.indexOf(r) + 1] : 'win';
          var thr = function (t) { return nxt === 'win' ? (b.p_cup || {})[t] : ((b.reach || {})[t] || {})[nxt]; };
          return '<div class="fb-co-round"><div class="qk-kicker">' + esc(labels[r] || r) + ' <span class="fb-num">' + known[r].length + '</span></div>' + known[r].map(function (pr) {
            var w = (b.forced || {})[[pr[0], pr[1]].sort().join(' v ')];
            var sc = w ? tieGoals(r, pr[0], pr[1]) : null;
            var cell = function (i) {
              if (sc) { var g = i === 0 ? sc.a : sc.b; return '<a class="fb-num fb-co-tsc" href="' + esc(FB.href.match(c.slug, sc.id)) + '" title="' + (sc.legs > 1 ? 'Aggregate over ' + sc.legs + ' legs' : 'Final score') + '">' + g + (w === pr[i] && (sc.a === sc.b) ? '<small> p</small>' : '') + '</a>'; }
              return '<b class="fb-num">' + (w ? (w === pr[i] ? '✓' : '') : (unsim ? '' : pct(thr(pr[i])))) + '</b>';
            };
            return '<div class="fb-co-tie">' + [0, 1].map(function (i) {
              return '<div class="fb-co-side' + (w === pr[i] ? ' win' : w ? ' out' : '') + '">' + ctx.club(pr[i]) + cell(i) + '</div>';
            }).join('') + '</div>';
          }).join('') + '</div>';
        }).join('') + '</div>') + '</div>';
    }
    var seeds = b.seeds || {};
    var sk = Array.isArray(seeds) ? [] : Object.keys(seeds);
    if (sk.length) {
      html += '<div class="fb-co-groups fb-mt">' + sk.map(function (s, i) { return FB.card(esc(s) + (k === 'conference' ? ' Conference' : '') + ' seeds', 'Solid: qualifies directly; faded: plays the ' + (k === 'playoff' ? 'play-in' : 'wild card') + '.', '<div id="co-sd-' + i + '"></div>', { flush: true }); }).join('') + '</div>';
    }
    var teams = Object.keys(b.reach || {});
    if (unsim) {
      /* nothing simulated: no "who wins it" or "reaching each round" boards (they would be empty) */
      body.innerHTML = html;
      return;
    }
    var cupLabel = k === 'conference' ? 'MLS Cup' : k === 'playoff' ? 'Champion' : 'Winner';
    var alive = teams.filter(function (t) { return (b.p_cup || {})[t] > 0 || b.rounds.slice(1).some(function (r) { return ((b.reach[t] || {})[r] || 0) > 0.0001; }); });
    if (!alive.length) alive = teams;
    alive.sort(function (x, y) { return ((b.p_cup || {})[y] || 0) - ((b.p_cup || {})[x] || 0); });
    html += '<div class="fb-mt">' + FB.grid(
      (b.field_partial ? FB.card('Who wins it', 'Not yet: the top-flight clubs enter in a later round.', cardMsg('Winner chances appear once the top flight is in the draw.'), { span: 5 })
        : FB.card('Who wins it', 'Our chance of winning, from the simulated seasons.', '<div id="co-bwin"></div>', { span: 5 })) +
      FB.card('Reaching each round', 'Our chance of reaching each round · ' + alive.length + ' club' + (alive.length === 1 ? '' : 's') + ' still able to go through' + (alive.length < teams.length ? ' (of ' + teams.length + ')' : '') + '.', '<div id="co-reach"></div>', { span: 7, flush: true })
    ) + '</div>';
    body.innerHTML = html;
    sk.forEach(function (s, i) {
      FB.table($(el, 'co-sd-' + i), [
        { key: 'seed', label: 'Seed', num: true, fmt: function (v, r) { return '<span class="fb-co-pos" style="--b:' + (r.direct ? 'var(--c-3)' : 'var(--c-4)') + '">' + v + '</span>'; } },
        { key: 'team', label: clubW(), fmt: function (v, r) { return v ? '<span class="' + (r.direct ? '' : 'fb-co-faded') + '">' + ctx.club(v) + '</span>' : '<span class="qk-muted">—</span>'; } },
        { key: '_po', label: k === 'playoff' ? 'Liguilla' : 'Playoffs', num: true, fmt: function (v) { return heatPct(v, 'var(--c-3)'); } },
        { key: '_cup', label: cupLabel, num: true, fmt: function (v) { return heatPct(v, 'var(--signal)'); } }
      ], seeds[s].map(function (x) { return FB.merge(x, { _po: x.team ? (b.p_playoffs || {})[x.team] : null, _cup: x.team ? (b.p_cup || {})[x.team] : null }); }), { sort: null });
    });
    var top = alive.slice(0, 12).filter(function (t) { return ((b.p_cup || {})[t] || 0) > 0; });
    var wb = $(el, 'co-bwin');
    if (wb) wb.innerHTML = top.length ? chanceList(ctx, c, top.map(function (t) { return { team: t, p: b.p_cup[t] }; }), { limit: 12, oursName: 'Our chance of winning' }) : cardMsg('Decided, or not simulated.');
    var cols = [{ key: 'team', label: clubW(), sticky: true, fmt: function (v) { return ctx.club(v); } }];
    if (k === 'conference' || k === 'playoff') cols.push({ key: '_po', label: k === 'playoff' ? 'Liguilla' : 'Playoffs', num: true, fmt: function (v) { return heatPct(v, 'var(--c-3)'); } });
    b.rounds.forEach(function (r) { cols.push({ key: '_r_' + r, label: labels[r] || r, num: true, fmt: function (v) { return heatPct(v); } }); });
    cols.push({ key: '_cup', label: cupLabel, num: true, fmt: function (v) { return '<b>' + heatPct(v, 'var(--signal)') + '</b>'; } });
    FB.table($(el, 'co-reach'), cols, alive.slice(0, 120).map(function (t) {
      var o = { team: t, _po: (b.p_playoffs || {})[t], _cup: (b.p_cup || {})[t] };
      b.rounds.forEach(function (r) { o['_r_' + r] = (b.reach[t] || {})[r]; });
      return o;
    }), { maxHeight: 520, caption: 'Reach each round' });
  });
};
function ligaBracket(el, body, ctx, b) {
  var labels = FB.merge(FB.ROUND_LABELS, b.round_labels || {});
  var seeds = Array.isArray(b.seeds) ? b.seeds : [];
  var pairs = [];
  for (var i = 0; i < seeds.length; i += 2) pairs.push([seeds[i], seeds[i + 1]]);
  var res = b.results || {};
  body.innerHTML = FB.card('Round of 16', 'Single-leg ties on a fixed tree: A1 v B8, A2 v B7 and so on. Shown: the club most likely to hold each seed, and our chance of it reaching the Round of 16.',
    '<div class="fb-co-ladder">' + b.rounds.map(function (r) {
      var n = { r16: 8, qf: 4, sf: 2, final: 1 }[r] || 1;
      var cards = '';
      for (var s = 0; s < n; s++) {
        var forced = res[r + ':' + s];
        if (r === 'r16' && pairs[s]) cards += '<div class="fb-co-tie">' + pairs[s].map(function (sd) {
          if (!sd) return '';
          var t = sd.likely;
          return '<div class="fb-co-side' + (forced && forced === t ? ' win' : '') + '"><span class="fb-co-seed">' + esc(sd.label) + '</span>' + (t ? ctx.club(t) : '<span class="qk-muted">—</span>') + '<b class="fb-num">' + (t ? pct((b.reach[t] || {}).r16) : '') + '</b></div>';
        }).join('') + '</div>';
        else cards += '<div class="fb-co-tie"><div class="fb-co-side' + (forced ? ' win' : '') + '">' + (forced ? ctx.club(forced) : '<span class="qk-muted">To be decided</span>') + '</div></div>';
      }
      return '<div class="fb-co-round"><div class="qk-kicker">' + esc(labels[r] || r) + '</div>' + cards + '</div>';
    }).join('') + '</div>') +
    '<div class="fb-mt">' + FB.card('Reaching each round', 'Our chance of reaching each round, from the simulated seasons.', '<div id="co-reach"></div>', { flush: true }) + '</div>';
  var teams = Object.keys(b.reach || {}).sort(function (x, y) { return ((b.p_title || {})[y] || 0) - ((b.p_title || {})[x] || 0); });
  var cols = [{ key: 'team', label: clubW(), sticky: true, fmt: function (v) { return ctx.club(v); } }];
  b.rounds.forEach(function (r) { cols.push({ key: '_r_' + r, label: labels[r] || r, num: true, fmt: function (v) { return heatPct(v); } }); });
  cols.push({ key: '_t', label: 'Champion', num: true, fmt: function (v) { return '<b>' + heatPct(v, 'var(--signal)') + '</b>'; } });
  FB.table($(el, 'co-reach'), cols, teams.map(function (t) { var o = { team: t, _t: (b.p_title || {})[t] }; b.rounds.forEach(function (r) { o['_r_' + r] = (b.reach[t] || {})[r]; }); return o; }), { maxHeight: 560 });
}

// ── chances (route key: odds) ─────────────────────────────────────────────

LIVE.odds = function (el, body, c, d0, q, embed) {
  var tabs = c.tabs || [];
  q = q || {};
  var views = [['summary', 'Our chances']].concat(tabs.indexOf('history') >= 0 && embed !== 'race' ? [['history', 'Over time']] : []);
  var vq = embed ? q.cview : q.view;
  var view = views.some(function (v) { return v[0] === vq; }) ? vq : 'summary';
  body.innerHTML = (views.length > 1 ? '<div class="fb-toolbar">' + FB.seg('co-oview', views, view, 'Chances view') + '</div>' : '') + '<div id="co-obody" class="fb-mt">' + FB.loading('lines', 5) + '</div>';
  FB.wireSeg(body, 'co-oview', function (v) { var pq = {}; pq[embed ? 'cview' : 'view'] = v === 'summary' ? null : v; FB.setQuery(pq); LIVE.odds(el, body, c, d0, FB.merge(q, pq), embed); });
  var ob = $(el, 'co-obody');
  if (view === 'history') return oddsHistory(el, ob, c, d0);
  return FB.compFiles(c.slug, ['probs', 'table']).then(function (d1) {
    if (!FB.alive(el)) return;
    var d = FB.merge(d0, d1), ctx = makeCtx(c, d), p = d.probs || {};
    var teams = p.teams || [];
    if (!teams.length) { ob.innerHTML = FB.empty('No simulation for this competition yet', (d.meta || {}).unsimulated ? 'National-team competitions are not simulated.' : ''); return; }
    var k = c.kind, cols, fk = favKeyOf(c);
    var tl = function (v) { return ctx.club(v); };
    if (k === 'liga') {
      cols = [{ key: 'team', label: clubW(), sticky: true, fmt: tl }, { key: 'zone', label: 'Zone' }, { key: 'exp_pts', label: 'Proj. pts', num: true, fmt: function (v) { return num(v, 1); } },
        { key: 'p_top8', label: 'Top 8', num: true, fmt: function (v) { return heatPct(v, 'var(--c-3)'); } }, { key: 'p_title', label: 'Champion', num: true, fmt: function (v) { return heatPct(v, 'var(--signal)'); } },
        { key: 'p_anual', label: 'Anual', num: true, fmt: function (v) { return heatPct(v); } }, { key: 'p_libertadores', label: 'Libertadores', num: true, fmt: function (v) { return heatPct(v, 'var(--c-3)'); } },
        { key: 'p_sudamericana', label: 'Sudamericana', num: true, fmt: function (v) { return heatPct(v); } }, { key: 'p_relegation', label: 'Relegation', num: true, fmt: riskPct }];
    } else if (k === 'conference') {
      cols = [{ key: 'team', label: clubW(), sticky: true, fmt: tl }, { key: 'conference', label: 'Conf.', fmt: function (v) { return esc(String(v || '').slice(0, 4)); } },
        { key: 'exp_pts', label: 'Proj. pts', num: true, fmt: function (v) { return num(v, 1); } }, { key: 'p_title', label: 'Shield', num: true, tip: 'Supporters\' Shield: best regular-season record', fmt: function (v) { return heatPct(v); } },
        { key: 'p_playoffs', label: 'Playoffs', num: true, fmt: function (v) { return heatPct(v, 'var(--c-3)'); } }, { key: 'p_conference', label: 'Conf. title', num: true, fmt: function (v) { return heatPct(v); } },
        { key: 'p_cup', label: 'MLS Cup', num: true, fmt: function (v) { return '<b>' + heatPct(v, 'var(--signal)') + '</b>'; } }];
    } else {
      var bands = p.bands || [];
      var isCup = k === 'cup' || k === 'playoff';
      var showPts = !(k === 'cup') || ['swiss', 'groups', 'regional_swiss'].indexOf(c.cup_kind) >= 0;
      cols = [{ key: 'team', label: clubW(), sticky: true, fmt: tl }];
      if (k === 'cup' && teams.some(function (t) { return t.conference; })) cols.push({ key: 'conference', label: (d.table || {}).group_label || 'Group' });
      if (showPts) cols.push({ key: 'exp_pts', label: 'Proj. pts', num: true, fmt: function (v) { return num(v, 1); } });
      if (!isCup) cols.push({ key: 'p_title', label: 'Title', num: true, fmt: function (v) { return '<b>' + heatPct(v, 'var(--signal)') + '</b>'; } });
      bands.forEach(function (bd) { cols.push({ key: '_b_' + bd.key, label: bd.label, num: true, fmt: function (v) { return bd.kind === 'down' ? riskPct(v) : heatPct(v, bandColour(bands, bd.key)); } }); });
      if (isCup) cols.push({ key: 'p_conference', label: k === 'cup' ? 'Reaches final' : 'Final', num: true, fmt: function (v) { return heatPct(v); } }, { key: 'p_cup', label: k === 'cup' ? 'Winner' : 'Champion', num: true, fmt: function (v) { return '<b>' + heatPct(v, 'var(--signal)') + '</b>'; } });
    }
    var list = teams.map(function (t) { var o = FB.merge(t, {}); ((p.bands || [])).forEach(function (bd) { o['_b_' + bd.key] = (t.bands || {})[bd.key]; }); return o; });
    var downs = (p.bands || []).filter(function (bd) { return bd.kind === 'down'; });
    ob.innerHTML = (p.field_partial ? FB.note('The top-flight clubs have not entered this edition yet, so winner and final chances are not shown; they appear once the top flight is in the draw.') : '') + FB.grid(
      FB.card('Who wins ' + esc(winnerWord(c)), 'Our chance, the top ten' + (simulated(d.meta) ? ', from ' + FB.int(d.meta.n_sims) + ' simulated seasons' : '') + '.', p.field_partial ? cardMsg('Winner chances appear once the top flight is in the draw.') : '<div id="co-oc1"></div>', { span: 6 }) +
      FB.card(downs.length ? 'Who goes down' : (k === 'cup' ? 'Who reaches the final' : 'Who makes the play-offs'), 'Our chance' + (downs.length ? ': ' + esc(downs.map(function (bd) { return bd.label; }).join(' + ')) : '') + ', the top ten.', '<div id="co-oc2"></div>', { span: 6 })
    ) + '<div class="fb-mt">' + FB.card('Every club', 'Our chances from the simulated seasons; sortable.', '<div id="co-ot"></div>', { flush: true }) + '</div>';
    FB.table($(el, 'co-ot'), cols, list, { sort: { key: has(teams[0][fk]) ? fk : 'p_title', dir: 'desc' }, caption: 'Our chances' });
    var bar = function (box, getter, name) {
      if (!box) return;
      box.innerHTML = chanceList(ctx, c, teams.map(function (t) { return { team: t.team, p: getter(t) }; }).sort(function (a, b2) { return (b2.p || 0) - (a.p || 0); }), { limit: 10, oursName: name });
    };
    var wk = has(teams[0][fk]) ? fk : 'p_title';
    bar($(el, 'co-oc1'), function (t) { return t[wk]; }, 'Our chance of winning');
    if (downs.length) bar($(el, 'co-oc2'), function (t) { return downs.reduce(function (s, bd) { return s + ((t.bands || {})[bd.key] || 0); }, 0); }, 'Our chance of going down');
    else bar($(el, 'co-oc2'), function (t) { return t[k === 'cup' ? 'p_conference' : 'p_playoffs']; }, k === 'cup' ? 'Our chance of reaching the final' : 'Our play-off chance');
  });
};
function oddsHistory(el, ob, c, d0) {
  return FB.compFiles(c.slug, ['history', 'table', 'probs']).then(function (d1) {
    if (!FB.alive(el)) return;
    var d = FB.merge(d0, d1), snaps = (d.history || {}).snapshots || [];
    var k = c.kind, opts;
    var bands = (d.table || {}).bands || (d.probs || {}).bands || [];
    var firstUp = bands.filter(function (b) { return b.kind === 'up'; })[0];
    if (k === 'liga') opts = [['title', 'Torneo champion'], ['anual', 'Tabla Anual'], ['relegation', 'Relegation']];
    else if (k === 'conference') opts = [['title', 'MLS Cup'], ['shield', 'Supporters\' Shield']];
    else if (k === 'cup') opts = [['title', 'Winner']].concat(firstUp ? [['band', firstUp.label]] : []);
    else if (k === 'playoff') opts = [['title', 'Champion'], ['band', 'Liguilla']];
    else opts = [['title', 'Title']].concat(firstUp ? [['band', firstUp.label]] : []).concat(bands.some(function (b) { return b.kind === 'down'; }) ? [['relegation', 'Relegation']] : []);
    opts = opts.filter(function (o) { return snaps.some(function (s) { return s[o[0]]; }); });
    if (snaps.length < 2 || !opts.length) { ob.innerHTML = FB.empty('Not enough history yet', 'The chart appears after a few hourly model runs.'); return; }
    var key = opts[0][0];
    ob.innerHTML = FB.card('Our chances over time', 'After each model run (hourly): ' + snaps.length + ' runs from ' + esc(FB.fmtDate(snaps[0].ts)) + '. Each line ends with its latest value.',
      '<div class="fb-toolbar">' + FB.seg('co-hs', opts, key, 'Series') + '</div>' + FB.chartBox('co-hc', 420, 'Our chances after each model run'));
    var draw = function () { historyChart($(el, 'co-hc'), snaps, key, 8, key === 'title' ? 'Our chance of winning' : key === 'relegation' ? 'Our relegation chance' : key === 'anual' ? 'Our chance of topping the Anual' : key === 'shield' ? 'Our Supporters\' Shield chance' : key === 'band' && firstUp ? 'Our ' + firstUp.label + ' chance' : 'Our chance'); };
    FB.wireSeg(ob, 'co-hs', function (v) { key = v; draw(); });
    draw();
  });
}

// ── power ─────────────────────────────────────────────────────────────────

LIVE.power = function (el, body, c, d0) {
  return FB.compFiles(c.slug, ['strength']).then(function (d1) {
    if (!FB.alive(el)) return;
    var ctx = makeCtx(c, d0), st = d1.strength || {}, rows = st.rows || [];
    if (!rows.length) { body.innerHTML = FB.empty('No strength data yet'); return; }
    var n = st.notes_en || st.notes || {};
    var played = rows.filter(function (r) { return r.played > 0; });
    var hasXg = played.some(function (r) { return r.expected_points > 0; });
    var hasZone = rows.some(function (r) { return r.zone || r.conference; });
    var cols = [
      { key: 'strength_rank', label: '#', num: true },
      { key: 'team', label: clubW(), sticky: true, fmt: function (v) { return ctx.club(v); } }
    ];
    if (hasZone) cols.push({ key: '_z', label: c.kind === 'liga' ? 'Zone' : 'Conf.' });
    cols.push(
      { key: 'strength_ppg', label: 'Strength', num: true, tip: n.strength_ppg || 'Expected points per game against an average opponent at a neutral venue', fmt: function (v) { return '<b>' + num(v, 2) + '</b>'; } },
      { key: 'elo', label: 'Elo', num: true, fmt: function (v) { return num(v, 0); } },
      { key: 'table_rank', label: 'Pos.', num: true },
      { key: 'rank_delta', label: 'Δ', num: true, tip: n.rank_delta || 'Table position minus strength rank', fmt: function (v) { return v === 0 ? '—' : '<span class="' + (v > 0 ? 'fb-down' : 'fb-up') + '">' + signed(v, 0) + '</span>'; } },
      { key: 'ppg', label: 'PPG', num: true, fmt: function (v) { return num(v, 2); } },
      { key: 'form_ppg', label: 'Form', num: true, fmt: function (v, r) { return FB.formChips(r.form_results) + ' <span class="fb-num">' + num(v, 2) + '</span>'; } },
      { key: 'xg_diff', label: 'xG diff', num: true, fmt: function (v) { return signed(v, 1); } },
      { key: 'luck', label: 'Luck', num: true, tip: n.luck || 'Points minus the points the xG deserved', fmt: function (v) { return hasXg ? signed(v, 1) : '—'; } },
      { key: 'sos_delta', label: 'Schedule', num: true, tip: n.sos_delta || 'Opponents still to play minus those played (positive: harder run-in)', fmt: function (v) { return signed(v, 2); } }
    );
    var avgS = rows.reduce(function (s2, r) { return s2 + (r.strength_ppg || 0); }, 0) / rows.length;
    var hasProc = played.some(function (r) { return isNum(r.xg_diff) && r.played > 0; });
    body.innerHTML = FB.grid(
        FB.card('Power ratings', 'Our rating: expected points a game against an average opponent at a neutral venue, shown against this competition\'s average club.', FB.chartBox('co-pr', Math.max(300, rows.length * 20 + 50), 'Power ratings'), { span: 5 }) +
        FB.card('Results v process', 'Points a game against expected-goal difference a game. Right of centre: creates more than it concedes; above the line: wins more than the average club.', hasProc ? FB.chartBox('co-rvp', 420, 'Points per game against xG difference per game') : cardMsg('No xG coverage for this season yet.'), { span: 7 })
      ) +
      '<div class="fb-mt">' + FB.note('<b>Our rating</b> is the points a game we would expect a club to take against an average side in this competition at a neutral ground: roughly 2 is title form and 1 a relegation fight. <b>Luck</b> is points won minus the points the chances (xG) deserved; it rarely lasts.') + '</div>' +
      '<div class="fb-mt">' + FB.card('Ratings table', esc(n.strength_ppg || 'Expected points per game against an average opponent at a neutral venue.'), '<div id="co-pw"></div>', { flush: true }) + '</div>' +
      '<div class="fb-mt">' + FB.grid(
        FB.card('Luck: points against what the xG deserved', 'Right of zero: more points than the chances deserved; left: fewer.', FB.chartBox('co-luck', Math.max(300, played.length * 20 + 40), 'Luck'), { span: 6 }) +
        FB.card('Schedule', 'Mean strength of opponents already played against those still to come.', FB.chartBox('co-sos', Math.max(300, played.length * 24 + 60), 'Schedule strength'), { span: 6 })
      ) + '</div>' +
      '<div class="fb-mt">' + FB.card(INTL ? 'Elo through the tournament' : 'Elo over the season', 'The eight strongest ' + clubW().toLowerCase() + 's, match by match.', FB.chartBox('co-elo', 380, 'Elo over the season')) + '</div>';
    FB.table($(el, 'co-pw'), cols, rows.map(function (r) { return FB.merge(r, { _z: r.zone || (r.conference ? String(r.conference).slice(0, 4) : '') }); }), { sort: { key: 'strength_rank', dir: 'asc' }, caption: 'Power ranking' });
    var pr = rowsSorted(rows, 'strength_ppg');
    QKC.bar($(el, 'co-pr'), { horizontal: true, diverging: true, labelWidth: 120, fmt: function (v) { return signed(v, 2); }, valName: 'Points a game v the average club', catName: clubW(),
      cats: pr.map(function (r) { return r.team; }), series: [{ name: 'Rating', color: 'model', data: pr.map(function (r) { return Math.round((r.strength_ppg - avgS) * 1000) / 1000; }) }],
      hrefs: pr.map(function (r) { var id = ctx.tidOf(r.team); return id ? FB.href.club(id, { c: c.slug }) : null; }), label: 'Power ratings' });
    if (hasProc) {
      var pp2 = played.filter(function (r) { return isNum(r.xg_diff) && r.played > 0; });
      QKC.scatter($(el, 'co-rvp'), { points: pp2.map(function (r) { var id = ctx.tidOf(r.team); return { x: r.xg_diff / r.played, y: r.ppg, name: r.team + ' · ' + r.points + ' pts in ' + r.played, label: r.team, size: 11, href: id ? FB.href.club(id, { c: c.slug }) : null }; }),
        xName: 'xG difference a game', yName: 'Points a game', xFmt: function (v) { return signed(v, 1); }, yFmt: function (v) { return num(v, 1); }, refX: 0, refY: FB.median(pp2.map(function (r) { return r.ppg; })), labelTop: 12,
        quadrants: ['Winning more than its play', 'Good and winning', 'Struggling', 'Better than its record'], label: 'Results v process' });
    }
    var lb = $(el, 'co-luck');
    if (hasXg) {
      var byLuck = played.slice().sort(function (a, b) { return b.luck - a.luck; });
      QKC.bar(lb, { horizontal: true, diverging: true, labelWidth: 120, fmt: function (v) { return signed(v, 1); }, valName: 'Points minus expected points', catName: clubW(), cats: byLuck.map(function (r) { return r.team; }), series: [{ name: 'Points v xPts', data: byLuck.map(function (r) { return Math.round(r.luck * 100) / 100; }) }], label: 'Luck' });
    } else { lb.style.height = 'auto'; lb.innerHTML = cardMsg('No xG coverage for this season yet.'); }
    var bySos = played.slice().sort(function (a, b) { return b.sos_delta - a.sos_delta; });
    QKC.bar($(el, 'co-sos'), { horizontal: true, legend: true, labelWidth: 120, fmt: function (v) { return num(v, 2); }, cats: bySos.map(function (r) { return r.team; }),
      series: [{ name: 'Played', data: bySos.map(function (r) { return r.sos_played; }), color: hexOf('var(--ink-4)') }, { name: 'To play', data: bySos.map(function (r) { return r.sos_remaining; }), color: hexOf('var(--c-1)') }], min: 0, valName: 'Mean opponent strength', catName: clubW(), label: 'Schedule' });
    var hist = st.elo_history || {};
    var top = rowsSorted(rows, 'strength_ppg').slice(0, 8).filter(function (r) { return (hist[r.team] || []).length > 1; });
    var eb = $(el, 'co-elo');
    if (top.length) {
      QKC.mount(eb, function (T) {
        return {
          grid: { left: 8, right: 110, top: 30, bottom: 30, containLabel: true },
          xAxis: QKC.axis(T, { type: 'time', split: false, line: true, name: 'Date', nameLocation: 'middle', nameGap: 26 }), yAxis: QKC.axis(T, { scale: true, name: 'Elo rating', nameAlign: 'left' }),
          tooltip: QKC.tooltip(T, { trigger: 'axis' }),
          series: top.map(function (r, i) {
            var col = T.cat[i % 8];
            return { type: 'line', name: r.team, showSymbol: false, data: hist[r.team].map(function (x) { return [x.date, Math.round(x.elo)]; }), lineStyle: { width: 2, color: col }, itemStyle: { color: col },
              endLabel: { show: true, formatter: r.team, color: T.ink2, fontSize: 11, fontWeight: 600 }, labelLayout: { moveOverlap: 'shiftY' }, emphasis: { focus: 'series' } };
          })
        };
      }, { label: 'Elo over the season' });
    } else { eb.style.height = 'auto'; eb.innerHTML = cardMsg('Not enough matches played yet.'); }
  });
};

// ── players ───────────────────────────────────────────────────────────────

LIVE.players = function (el, body, c, d0) {
  /* the rows' own role and gar90 when the payload carries them; else the value/lines.json join (FB.rolesFor) */
  return FB.compFiles(c.slug, ['players_live', 'player_leaders', 'shots']).then(function (d) {
    return FB.rolesFor((((d || {}).players_live || {}).players || []).some(function (x) { return x.role !== undefined; })).then(function (R0) { return [d, R0]; });
  }).then(function (res) {
    if (!FB.alive(el)) return;
    var d1 = res[0], R = res[1] || {};
    var ctx = makeCtx(c, d0), live = d1.players_live || {}, all0 = live.players || [], metrics = (live.metrics || []).slice();
    if (!all0.length) { body.innerHTML = FB.empty('No player data yet', 'Player lines arrive with the first matches that have line-ups.'); return; }
    /* ── role peers (METRICS_SPEC): each row's formation role this season in this competition and its value added */
    var roleOk = !!R.ok;
    var all = all0.map(function (p0) {
      var p = FB.merge(p0, {});
      if (roleOk) {
        p._role = FB.rowRole(R, p0.role, p.player_id, c.slug);
        p._grp = FB.peerGroup(p._role);
        p.gar90 = FB.rowGar(R, p0.gar90, p.player_id, c.slug);
        if (!isNum(p.gar90)) p.gar90 = null;
      }
      return p;
    });
    if (roleOk && all.some(function (p) { return isNum(p.gar90); }) && !metrics.some(function (m) { return m.key === 'gar90'; })) {
      metrics.unshift({ key: 'gar90', label: 'Value added (GAR/90)', group: 'Value', fmt: 'gar', pct: true, scope: 'all', desc: (FB.metricInfo('gar90') || {}).tip || '' });
    }
    var floor0 = live.minutes_floor || 0;
    var where = c.name + ' ' + (FB.currentSeason(c).season || '');
    var PP = roleOk ? FB.peerPct({ rows: all, minutes: function (r) { return r.minutes || 0; }, role: function (r) { return r._role; }, val: function (r, k) { return r[k]; }, floor: floor0 }) : null;
    var metaOf = {};
    metrics.forEach(function (m) { metaOf[m.key] = m; });
    var lowerOf = function (k) { var mi = FB.metricInfo(k); return mi ? !!mi.lower : !!(metaOf[k] || {}).lower; };
    /* his percentile on any metric against his role group (null: no group, under the minimum, or too few peers) */
    var rolePct = function (r, k) {
      var g = r._grp;
      if (!PP || !g || (r.minutes || 0) < PP.min(g) || !isNum(r[k])) return null;
      var vals = PP.values(g, k);
      if (vals.length < 5) return null;
      var v = r[k], lo = 0, hi = vals.length;
      while (lo < hi) { var mid = (lo + hi) >> 1; if (vals[mid] < v) lo = mid + 1; else hi = mid; }
      var up = lo; while (up < vals.length && vals[up] === v) up++;
      var rank = (lo + 0.5 * (up - lo)) / vals.length;
      return Math.round(100 * (lowerOf(k) ? 1 - rank : rank));
    };
    var fmtK = function (k, v) { return FB.fmtSet(k, v, k === 'gar90' ? null : (metaOf[k] || {}).fmt); };
    var GROUPS = FB.MSET.groups;
    var roleText = function (p) { return p._grp ? p._role : (p._role ? p._role + ' (no peer group)' : (p.position || '')); };
    var shotPlayers = (d1.shots || {}).players || {};
    var shotNames = Object.keys(shotPlayers).sort(function (a, b) { return ((shotPlayers[b] || {}).shots || []).length - ((shotPlayers[a] || {}).shots || []).length; });
    var pool = all.filter(function (p) { return p.qualified; }).sort(function (a, b) { return (b.goals + b.assists) - (a.goals + a.assists) || b.minutes - a.minutes; });
    var teams = uniq(all.map(function (p) { return p.team; })).sort(function (a, b) { return a.localeCompare(b); });
    var heatLine = roleOk
      ? 'Heat: percentile v the role group in ' + esc(where) + ' (centre-backs, full-backs, DMs and CMs, AMs and wingers, strikers, goalkeepers), ' + FB.int(FB.peerMin(null, floor0)) + '+ min (' + FB.int(FB.peerMin(GROUPS.filter(function (g) { return g.id === 'gk'; })[0], floor0)) + '+ for goalkeepers); no cell under that or without a formation role.'
      : 'Heat: percentile v position (G, D, M, F) in this competition, ' + floor0 + '+ min: this season\'s formation roles could not be read.';
    var roleOpts = roleOk ? [['', 'All roles']].concat(GROUPS.map(function (g) { return [g.id, g.codes.join('/') + ' · ' + g.name.charAt(0).toUpperCase() + g.name.slice(1)]; }))
      : [['', 'All positions'], ['G', 'Goalkeepers'], ['D', 'Defenders'], ['M', 'Midfielders'], ['F', 'Forwards']];
    /* round 9, a legacy tab rebuilt: the headline numbers first, then the chart, then the table, then what it means */
    var lead = function (key, label, fmt, unit) {
      var r = all.filter(function (p) { return isNum(p[key]) && (key === 'rating' ? p.qualified : p[key] > 0); }).sort(function (a, b) { return b[key] - a[key]; })[0];
      return r ? FB.kpi(label, FB.playerLink(r.player_id, r.name), { text: true, sub: '<b class="fb-num">' + FB.fmtMetric(r[key], fmt) + '</b> ' + unit + ' · ' + esc(r.team) }) : '';
    };
    var heads = [lead('goals', 'Most goals', 'int', 'goals'), lead('xg', 'Most expected goals', '1', 'xG'), lead('xa', 'Most chances created', '1', 'xA'), lead('rating', 'Best match rating', '2', 'average, qualified')].filter(Boolean);
    body.innerHTML = (heads.length ? FB.kpis(heads) : '') +
      '<div class="fb-mt">' + FB.grid(
        FB.card('Creation against finishing', 'Qualified outfield players: non-penalty xG and xA per 90; size by goals, colour by rating. The top-scorer race is on the <a href="' + esc(FB.href.comp(c.slug, 'races')) + '">Golden Boot</a> tab.', FB.chartBox('co-sc', 380, 'Creation against finishing'), { span: 12 })
      ) + '</div><div class="fb-mt">' +
      FB.card('Leaderboard', all.length + ' players · ' + (live.matches_covered || 0) + ' matches with player data. ' + heatLine,
      FB.toolbar([
        FB.field('Metric', '<select class="qk-select" id="co-pm" aria-label="Metric"></select>'),
        FB.field(roleOk ? 'Role' : 'Position', FB.select('co-pp', roleOpts, '', roleOk ? 'Role group' : 'Position')),
        FB.field(clubW(), FB.select('co-pt', [['', 'All ' + clubW().toLowerCase() + 's']].concat(teams.map(function (t) { return [t, t]; })), '', 'Club')),
        FB.field('Min. minutes', '<input class="qk-input fb-co-num" id="co-pmin" type="number" min="0" step="90" value="' + (live.minutes_floor || 270) + '" aria-label="Minimum minutes">'),
        '<label class="fb-check"><input type="checkbox" id="co-pq"> Qualified only</label>'
      ]) + '<div id="co-pl"></div>', { flush: false }) + '</div>' +
      '<div class="fb-mt">' + QK.explain('A <b>percentile</b> ranks a player against the same role in this competition (centre-backs with centre-backs). <b>npxG + xA</b> per 90 is the quality of the chances a player takes and sets up, whatever the finish; on the chart, the higher a player sits the more they create, the further right the more they shoot. Every player in every competition, on every metric: <a href="' + esc('#/scout?c=' + FB.enc(c.slug)) + '">the Scouting Room</a>.', { title: 'What’s that number?' }) + '</div>' +
      '<div class="fb-mt">' + FB.grid(
        FB.card('Compare two players', '<span id="co-cmp-sub">Side by side on one metric set; the better value is bold.</span>', FB.toolbar([FB.field('Player A', '<select class="qk-select" id="co-ca" aria-label="Player A"></select>'), FB.field('Player B', '<select class="qk-select" id="co-cb" aria-label="Player B"></select>')]) + '<div id="co-rad"></div>', { span: 6 }) +
        FB.card('Shot map', 'Every shot this season; size by xG.', shotNames.length ? FB.toolbar([FB.field('Player', FB.select('co-shp', shotNames.map(function (n) { return [n, n + ' (' + (shotPlayers[n].shots || []).length + ')']; }), shotNames[0], 'Player'))]) + '<div id="co-shm" class="fb-co-shm"></div><p class="fb-cap" id="co-shs"></p>' : cardMsg('No shot data yet.'), { span: 6 })
      ) + '</div>';
    // leaderboard
    var ms = $(el, 'co-pm'), ps = $(el, 'co-pp'), ts = $(el, 'co-pt'), mn = $(el, 'co-pmin'), qo = $(el, 'co-pq');
    var grpSel = function () { return roleOk ? GROUPS.filter(function (g) { return g.id === ps.value; })[0] || null : null; };
    function fillMetrics(fromRole) {
      var gsel = grpSel();
      var scope = roleOk ? (gsel ? (gsel.id === 'gk' ? 'gk' : 'out') : 'all') : (ps.value === 'G' ? 'gk' : ps.value ? 'out' : 'all');
      var keep = ms.value;
      if (fromRole && gsel) keep = FB.groupKeys(gsel, 'headline').filter(function (k) { return metaOf[k]; })[0] || keep;
      var groups = [];
      metrics.filter(function (m) { return scope === 'all' || m.scope === 'all' || m.scope === scope; }).forEach(function (m) {
        var g = groups.filter(function (x) { return x.name === m.group; })[0];
        if (!g) { g = { name: m.group, items: [] }; groups.push(g); }
        g.items.push(m);
      });
      ms.innerHTML = groups.map(function (g) { return '<optgroup label="' + esc(g.name) + '">' + g.items.map(function (m) { return '<option value="' + esc(m.key) + '">' + esc(m.label) + '</option>'; }).join('') + '</optgroup>'; }).join('');
      var opts = Array.prototype.map.call(ms.options, function (o) { return o.value; });
      ms.value = opts.indexOf(keep) >= 0 ? keep : (scope === 'gk' ? 'saves_90' : 'goals');
      if (!ms.value && opts.length) ms.value = opts[0];
    }
    function drawTable() {
      var metric = metrics.filter(function (m) { return m.key === ms.value; })[0] || metrics[0];
      var key = metric.key;
      var pk = metric.pct ? key : (metrics.some(function (m) { return m.key === key + '_90' && m.pct; }) ? key + '_90' : null);
      var floor = parseInt(mn.value, 10) || 0;
      var gsel = grpSel();
      var inPos = function (p) { return !ps.value || (roleOk ? p._grp === gsel : (ps.value === 'G' ? p.is_gk : p.position === ps.value)); };
      var rows = all.filter(function (p) { return p.minutes >= floor && (!ts.value || p.team === ts.value) && inPos(p) && (!qo.checked || p.qualified) && has(p[key]); })
        .sort(function (a, b) { return metric.lower ? a[key] - b[key] : b[key] - a[key]; }).slice(0, 100)
        .map(function (p) { var o = FB.merge(p, {}); o._v = p[key]; o._p = pk ? (roleOk ? rolePct(p, pk) : (p.pct || {})[pk]) : null; return o; });
      QK.leaderboard($(el, 'co-pl'), { dense: true, rank: true, maxHeight: 620, caption: 'Player leaderboard', columns: [
        { key: 'name', label: 'Player', sticky: true, fmt: function (v, r) { return FB.playerLink(r.player_id, v) + (r.current === false ? ' <span class="qk-muted" data-tip="Has since left the club">left</span>' : ''); } },
        { key: 'team', label: clubW(), fmt: function (v) { return ctx.club(v); } },
        roleOk ? { key: '_role', label: 'Role', fmt: function (v, r) { return v ? '<span class="fb-co-role' + (r._grp ? '' : ' coarse') + '"' + (r._grp ? '' : ' data-tip="Substitute appearances only this season: no formation role, so no peer group"') + '>' + esc(v) + '</span>' : FB.posBadge(r.position || (r.is_gk ? 'G' : '')); } }
          : { key: 'position', label: 'Pos', fmt: function (v, r) { return FB.posBadge(v || (r.is_gk ? 'G' : '')); } },
        { key: 'age', label: 'Age', num: true },
        { key: 'minutes', label: 'Min', num: true },
        { key: '_v', label: metric.label, type: 'pctl', pctl: '_p', tip: (metric.desc ? metric.desc + ' ' : '') + (roleOk ? 'Cell colour: percentile v the player\'s role group in this competition, over the group\'s minimum minutes.' : 'Cell colour: percentile v the player\'s position group in this competition (' + floor0 + '+ min).'), fmt: function (v) { return '<b>' + fmtK(key, v) + '</b>'; } },
        { key: 'goals', label: 'G', num: true }, { key: 'assists', label: 'A', num: true },
        { key: 'xg', label: 'xG', num: true, fmt: function (v) { return num(v, 1); } }, { key: 'xa', label: 'xA', num: true, fmt: function (v) { return num(v, 1); } },
        { key: 'rating', label: 'Rating', num: true, fmt: function (v) { return isNum(v) ? num(v, 2) : '—'; } }
      ], rows: rows });
    }
    fillMetrics(); drawTable();
    ms.addEventListener('change', drawTable); ts.addEventListener('change', drawTable); qo.addEventListener('change', drawTable); mn.addEventListener('input', drawTable);
    ps.addEventListener('change', function () { fillMetrics(true); drawTable(); });
    // scatter
    var sc = all.filter(function (p) { return p.qualified && !p.is_gk; });
    var sb = $(el, 'co-sc');
    if (sc.length) QKC.scatter(sb, { points: sc.map(function (p) { return { x: p.npxg_90 || 0, y: p.xa_90 || 0, name: p.name + ' (' + p.team + ')', label: FB.surname(p.name), size: 7 + Math.min(p.goals || 0, 14) * 1.3, color: FB.charts.ratingColor(p.rating), href: FB.href.player(p.player_id) }; }),
      xName: 'npxG per 90', yName: 'xA per 90', xFmt: function (v) { return num(v, 2); }, yFmt: function (v) { return num(v, 2); }, labelTop: 8, label: 'Creation against finishing' });
    else { sb.style.height = 'auto'; sb.innerHTML = cardMsg('Not enough minutes played yet.'); }
    // compare
    var ca = $(el, 'co-ca'), cb = $(el, 'co-cb');
    var opt = pool.slice(0, 400).map(function (p) { var rl = roleOk ? p._role : p.position; return '<option value="' + esc(p.player_id) + '">' + esc(p.name + ' — ' + p.team + (rl ? ' (' + rl + ')' : '')) + '</option>'; }).join('');
    ca.innerHTML = opt; cb.innerHTML = opt;
    if (pool.length > 1) cb.selectedIndex = 1;
    var POSN = { G: 'goalkeepers', D: 'defenders', M: 'midfielders', F: 'forwards' };
    function drawCmpRoles(a, b, rb) {
      var E = [a, b].filter(Boolean);
      var gA = a._grp, gB = b ? b._grp : gA;
      var gkMix = E.some(function (p) { return p._grp && p._grp.id === 'gk'; }) && E.some(function (p) { return p._grp && p._grp.id !== 'gk'; });
      var g = gA || gB;
      var same = !!gA && gA === gB;
      var sub = $(el, 'co-cmp-sub');
      if (!g) { if (sub) sub.textContent = 'Side by side on the role group\'s metric set.'; rb.innerHTML = cardMsg('Neither player has a formation role this season (substitute appearances only), so there is no peer group to compare on.'); return; }
      if (gkMix) { if (sub) sub.textContent = 'Side by side on the role group\'s metric set.'; rb.innerHTML = cardMsg('A goalkeeper and an outfield player share no metric set: pick two goalkeepers or two outfield players.'); return; }
      if (sub) sub.innerHTML = 'Value · percentile ' + esc(same ? FB.peerLine(g, where, PP.min(g)) : 'each v their own role group in ' + where + ', ' + FB.int(FB.peerMin(null, floor0)) + '+ min') + ' · 100 = best · the better value in bold. The metric set is the ' + esc(g.name) + '\' (the metrics spec): stable and predictive rates for the role.';
      var row = function (k) {
        var mi = FB.metricInfo(k) || {}, mm = metaOf[k] || {};
        return { label: mi.label || mm.label || k, tip: mi.tip || mm.desc || '', better: lowerOf(k) ? 'low' : 'high', values: E.map(function (p) { return isNum(p[k]) ? p[k] : null; }),
          pctls: E.map(function (p) { return rolePct(p, k); }), fmt: function (v) { return fmtK(k, v); } };
      };
      var keysOf = function (which) { return FB.groupKeys(g, which).filter(function (k) { return metaOf[k] || k === 'gar90'; }); };
      var notes = [];
      if (!same) notes.push('Different roles (' + E.map(function (p) { return p.name + ': ' + roleText(p); }).join(', ') + '): the set is the ' + g.name + '\', and each percentile is against the player\'s own group, so read the values, not just the colours.');
      E.forEach(function (p) {
        if (!p._grp) notes.push(p.name + ' has no formation role this season (substitute appearances only): no percentiles.');
        else if ((p.minutes || 0) < PP.min(p._grp)) notes.push(p.name + ' is under the ' + FB.int(PP.min(p._grp)) + '-minute minimum for ' + p._grp.short + ': no percentiles yet.');
        else if ((p.minutes || 0) < p._grp.small) notes.push(p.name + ' has under ' + FB.int(p._grp.small) + ' minutes: a small sample, read those percentiles as early.');
      });
      rb.innerHTML = QK.compareView({
        entities: E.map(function (p) { return { name: p.name, sub: p.team + ' · ' + roleText(p) + ' · ' + FB.int(p.minutes) + ' min', href: FB.href.player(p.player_id, { c: c.slug }) }; }),
        metricLabel: 'Metric · value · percentile',
        groups: [{ label: 'Headline', rows: keysOf('headline').map(row) }, { label: 'More', rows: keysOf('more').map(row) }]
      }) + (notes.length ? '<p class="fb-cap">' + notes.map(esc).join(' ') + '</p>' : '');
    }
    function drawCmp() {
      var a = pool.filter(function (p) { return p.player_id === ca.value; })[0], b = pool.filter(function (p) { return p.player_id === cb.value; })[0];
      var rb = $(el, 'co-rad');
      if (!a) { rb.innerHTML = cardMsg('Not enough qualified players yet.'); return; }
      if (roleOk) { drawCmpRoles(a, b, rb); return; }
      var sub0 = $(el, 'co-cmp-sub');
      if (sub0) sub0.textContent = 'Side by side on one metric set. Each percentile is against the player\'s own position (G, D, M, F) in this competition (' + floor0 + '+ min): this season\'s formation roles could not be read. The better value is bold.';
      var E = [a, b].filter(Boolean);
      var gk = E.every(function (p) { return p.is_gk; });
      var set = gk ? CMP_GK : CMP_OUT;
      var meta = {}; metrics.forEach(function (mm) { meta[mm.key] = mm; });
      var posOf = function (p) { return p.is_gk ? 'G' : p.position; };
      var same = E.length < 2 || posOf(E[0]) === posOf(E[1]);
      var peer = same ? 'v ' + (POSN[posOf(a)] || 'the position') + ' in ' + c.name + ', ' + floor0 + '+ min' : 'each v their own position group in ' + c.name + ', ' + floor0 + '+ min';
      rb.innerHTML = QK.compareView({
        entities: E.map(function (p) { return { name: p.name, sub: p.team + ' · ' + (FB.POS_LABEL[posOf(p)] || '') + ' · ' + FB.int(p.minutes) + ' min', href: FB.href.player(p.player_id, { c: c.slug }) }; }),
        metricLabel: 'Metric · value · percentile',
        groups: [{ label: 'Percentiles ' + peer, rows: set.map(function (x) {
          var mm = meta[x.key] || {};
          return { label: x.label, values: E.map(function (p) { return p[x.key]; }), pctls: E.map(function (p) { return (p.pct || {})[x.key]; }), better: mm.lower ? 'low' : 'high', tip: mm.desc || '',
            fmt: function (v) { return FB.fmtMetric(v, mm.fmt || '2'); } };
        }) }]
      }) + (same ? '' : '<p class="fb-cap">Different positions: each percentile is against the player\'s own position group, so read the values, not just the colours.</p>');
    }
    ca.addEventListener('change', drawCmp); cb.addEventListener('change', drawCmp); drawCmp();
    // shots
    var shp = $(el, 'co-shp');
    if (shp) {
      var drawShots = function () {
        var name = shp.value, sh = ((shotPlayers[name] || {}).shots || []);
        FB.charts.shotMap($(el, 'co-shm'), sh.map(function (s) { return FB.merge(s, { name: name, href: s.gid ? FB.href.match(c.slug, s.gid) : null }); }), { surface: 'half', label: 'Shots by ' + name });
        var g = sh.filter(function (s) { return FB.charts.outcomeOf(s) === 'goal'; }).length, xg = sh.reduce(function (s, x) { return s + (x.xg || 0); }, 0);
        $(el, 'co-shs').textContent = sh.length + ' shots · ' + g + ' goals · ' + num(xg, 2) + ' xG · ' + num(sh.length ? xg / sh.length : 0, 2) + ' xG per shot';
      };
      shp.addEventListener('change', drawShots); drawShots();
    }
  });
};

// ── analytics ─────────────────────────────────────────────────────────────

/* The Teams tab (teams.js): the power board, the team profile grid, the style map, strengths and weaknesses, head to
   head and the season so far, then the team of the week and the best XIs (the old Analytics tab's, part 'xi'). */
LIVE.teams = function (el, body, c, d0, q) {
  body.innerHTML = FB.loading('lines', 6);
  return FB.compFiles(c.slug, ['strength', 'analytics', 'probs', 'table']).then(function (d1) {
    if (!FB.alive(el)) return;
    var d = FB.merge(d0, d1);
    FB.teamsTab(el, body, c, d, makeCtx(c, d), q, function (el2, host) {
      host.innerHTML = QK.sectionHead({ kicker: 'Teams of the week', title: 'The best XIs', sub: 'The round’s best XI by match rating, the player and team of the round, and the best XIs of the season.' }) + '<div id="tm-xi-b"></div>';
      LIVE.analytics(el2, document.getElementById('tm-xi-b'), c, d0, 'xi');
    });
  });
};
LIVE.analytics = function (el, body, c, d0, part) {
  var xiOnly = part === 'xi';
  return FB.compFiles(c.slug, ['analytics', 'table']).then(function (d1) {
    if (!FB.alive(el)) return;
    var ctx = makeCtx(c, d0), an = d1.analytics;
    if (!an || (!(an.rounds || []).length && !Object.keys(an.teams || {}).length && !Object.keys((an.performers || {}).players || {}).length)) {
      body.innerHTML = FB.empty('No analytics yet', 'It needs played matches with player data.'); return;
    }
    var rounds = an.rounds || [], sx = an.season_xi || {}, pp = (an.performers || {}).players || {}, pt = (an.performers || {}).teams || {};
    var meta = [];
    if (an.season) meta.push(esc(an.season));
    if (an.minutes_floor) meta.push('percentiles over ' + an.minutes_floor + '+ minutes');
    if (an.updated_at) meta.push('updated ' + esc(FB.fmtStamp(an.updated_at)));
    var pmDefs = an.player_metrics || [];
    var perfGroups = [];
    Object.keys(pp).forEach(function (k) {
      var def = pmDefs.filter(function (m) { return m.key === k; })[0] || { group: 'Other', label: pp[k].label || k };
      var g = perfGroups.filter(function (x) { return x.group === (def.group || 'Other'); })[0];
      if (!g) { g = { group: def.group || 'Other', items: [] }; perfGroups.push(g); }
      g.items.push([k, pp[k].label || def.label || k]);
    });
    var tkeys = (an.team_metrics || []).map(function (m) { return m.key; }).filter(function (k) { return pt[k]; });
    Object.keys(pt).forEach(function (k) { if (tkeys.indexOf(k) < 0) tkeys.push(k); });
    var tdef = function (k) { return (an.team_metrics || []).filter(function (m) { return m.key === k; })[0] || { group: 'Other', label: (pt[k] || {}).label || k }; };
    var tGroups = [];
    tkeys.forEach(function (k) { var dd = tdef(k); var g = tGroups.filter(function (x) { return x.group === (dd.group || 'Other'); })[0]; if (!g) { g = { group: dd.group || 'Other', items: [] }; tGroups.push(g); } g.items.push([k, dd.label || k]); });
    body.innerHTML = '<p class="fb-cap">' + meta.join(' · ') + '</p>' +
      FB.grid(
        FB.card('Team of the week', 'The round\'s best XI by match rating; colour is the rating.', rounds.length ? FB.toolbar([FB.field('Round', FB.select('co-ar', rounds.map(function (r) { return [String(r.round), r.label || 'Round ' + r.round]; }), String(rounds[0].round), 'Round'))]) + '<div id="co-ahead" class="fb-cap"></div><div id="co-axi"></div><div id="co-abench" class="fb-co-bench"></div>' : cardMsg('No completed round yet.'), { span: 6 }) +
        FB.card('Player and team of the round', 'Awards from the same round.', '<div id="co-aaw"></div>', { span: 6 })
      ) +
      '<div class="fb-mt">' + FB.card('Best XIs of the season', 'Season totals: the basis picks the XI, the colour is the season rating.', Object.keys(sx).length ?
        FB.toolbar([FB.seg('co-ab', Object.keys(sx).map(function (k) { return [k, BASIS_LABELS[k] || k]; }), Object.keys(sx)[0], 'Basis')]) + '<div class="qk-grid"><div class="qk-span-6"><div id="co-sxh" class="fb-cap"></div><div id="co-sxi"></div></div><div class="qk-span-6" id="co-sxt"></div></div>'
        : cardMsg('No season XI yet: not enough minutes played.')) + '</div>' +
      (xiOnly ? '' : '<div class="fb-mt">' + FB.card('Top and bottom performers', 'Qualified players; the chip is the percentile against positional peers.', perfGroups.length ?
        FB.toolbar([FB.field('Metric', FB.select('co-apm', perfGroups.map(function (g) { return { group: g.group, items: g.items }; }), pp.rating ? 'rating' : (pp.npxg_xa_90 ? 'npxg_xa_90' : Object.keys(pp)[0]), 'Metric'))]) + '<p class="fb-cap" id="co-apd"></p><div class="qk-grid"><div class="qk-span-6" id="co-apt"></div><div class="qk-span-6" id="co-apb"></div></div>'
        : cardMsg('No player leaderboards yet.')) + '</div>' +
      '<div class="fb-mt">' + FB.card('Team rankings', 'Every club on one metric.', tkeys.length ?
        FB.toolbar([FB.field('Metric', FB.select('co-atm', tGroups.map(function (g) { return { group: g.group, items: g.items }; }), pt.xg_for ? 'xg_for' : tkeys[0], 'Team metric'))]) + '<p class="fb-cap" id="co-atd"></p><div id="co-atc" class="fb-chart"></div>'
        : cardMsg('No team rankings yet.')) + '</div>' +
      '<div class="fb-mt">' + FB.card('Team profile', 'Each club’s percentile in this competition on the spec’s headline team metrics, 100 = best (fewer xG against and a lower PPDA count as better). Clubs with 5+ matches; under 10 is a small sample (in italics). Hover a cell for the value.', '<div id="co-asm"></div>', { flush: true }) + '</div>' +
      '<div class="fb-mt">' + FB.grid(
        FB.card('Attack against defence', 'xG for and against per match; size by points; lines at the medians.', FB.chartBox('co-aad', 420, 'Attack against defence'), { span: 6 }) +
        FB.card('Points against expected points', 'Points won and the xPts the chances deserved; sorted luckiest first.', FB.chartBox('co-axp', 420, 'Points against expected points'), { span: 6 })
      ) + '</div>' +
      '<div class="fb-mt">' + FB.card('Form', 'The last six matches, oldest to newest: points, expected points and the xG difference over that window.', '<div id="co-afm"></div>', { flush: true }) + '</div>');
    // team of the week
    var drawRound = function () {
      var sel = $(el, 'co-ar');
      if (!sel) { $(el, 'co-aaw').innerHTML = cardMsg('No awards yet.'); return; }
      var r = rounds.filter(function (x) { return String(x.round) === sel.value; })[0] || rounds[0];
      var tw = r.team_of_week || {}, xi = tw.xi || [];
      $(el, 'co-ahead').innerHTML = (tw.formation ? '<b>' + esc(tw.formation) + '</b> · ' : '') + (r.dates && r.dates[0] ? esc(FB.fmtDate(r.dates[0])) + (r.dates[1] && FB.localDay(r.dates[1]) !== FB.localDay(r.dates[0]) ? ' – ' + esc(FB.fmtDate(r.dates[1])) : '') : '') + (r.matches ? ' · ' + r.matches + ' matches' : '');
      xiDraw($(el, 'co-axi'), xi, tw.formation, function (p) { return FB.surname(p.name); }, function (p) { return isNum(p.rt) ? num(p.rt, 1) : ''; });
      var bench = tw.bench || [];
      $(el, 'co-abench').innerHTML = bench.length ? '<span class="qk-kicker">Bench</span>' + bench.map(function (p) { return '<span>' + FB.posBadge(p.pos) + ' ' + FB.playerLink(p.id, p.name) + (isNum(p.rt) ? ' <b class="fb-num fb-co-rt sm" style="background:' + FB.charts.ratingColor(p.rt) + ';color:' + FB.charts.ratingInk(p.rt) + '">' + num(p.rt, 1) + '</b>' : '') + '</span>'; }).join('') : '';
      var html = '';
      var potw = r.player_of_week;
      if (potw) html += '<div class="fb-co-potw"><span class="fb-co-rt" style="background:' + FB.charts.ratingColor(potw.rt) + ';color:' + FB.charts.ratingInk(potw.rt) + '">' + (isNum(potw.rt) ? num(potw.rt, 1) : '—') + '</span><div><div class="qk-kicker">Player of the week</div><div class="fb-co-potw-n">' + FB.playerLink(potw.id, potw.name) + ' ' + FB.posBadge(potw.pos) + '</div>' +
        '<div class="fb-cap">' + ctx.club(potw.team) + (potw.opp ? ' · ' + matchLine(c, potw) : '') + '</div>' + (potw.why ? '<div class="fb-cap">' + esc(potw.why) + '</div>' : '') + '</div></div>';
      var aw = r.awards || {};
      var tiles = Object.keys(AWARD_LABELS).filter(function (k) { return aw[k]; }).map(function (k) {
        var p = aw[k];
        return '<div class="fb-co-aw"><div class="qk-kicker">' + esc(AWARD_LABELS[k]) + '</div><div class="fb-co-aw-n">' + FB.playerLink(p.id, p.name) + '</div><div class="fb-cap">' + esc(p.team || '') + '</div>' +
          (isNum(p.value) ? '<div><b class="fb-num">' + num(p.value, 2) + '</b> <span class="qk-muted">' + esc(p.label || '') + '</span></div>' : '') + (p.opp ? '<div class="fb-cap">' + matchLine(c, p) + '</div>' : '') + '</div>';
      });
      var ta = r.team_awards || {};
      Object.keys(TEAM_AWARD_LABELS).filter(function (k) { return ta[k]; }).forEach(function (k) {
        var t = ta[k];
        tiles.push('<div class="fb-co-aw"><div class="qk-kicker">' + esc(TEAM_AWARD_LABELS[k]) + '</div><div class="fb-co-aw-n">' + ctx.club(t.team) + '</div>' +
          '<div class="fb-cap">' + matchLine(c, { gid: t.gid, opp: t.opp, ha: t.ha, gf: t.gf, ga: t.ga }) + (isNum(t.xg) ? ' · xG ' + num(t.xg, 1) + '–' + num(t.xga, 1) : '') + '</div>' +
          (isNum(t.value) ? '<div><b class="fb-num">' + signed(t.value, 2) + '</b> <span class="qk-muted">' + (k === 'best_xg_diff' ? 'xG difference' : 'points above xG') + '</span></div>' : '') + '</div>');
      });
      $(el, 'co-aaw').innerHTML = html + (tiles.length ? '<div class="fb-co-aws">' + tiles.join('') + '</div>' : '') || cardMsg('No awards for this round.');
    };
    var ar = $(el, 'co-ar'); if (ar) ar.addEventListener('change', drawRound);
    drawRound();
    // season XI
    var basis = Object.keys(sx)[0];
    var drawSX = function () {
      var b = sx[basis];
      if (!b) return;
      var xi = b.xi || [];
      var vlab = (b.basis && b.basis.length < 28) ? b.basis : (BASIS_LABELS[basis] || 'Value');
      $(el, 'co-sxh').innerHTML = (b.formation ? '<b>' + esc(b.formation) + '</b> · ' : '') + esc(b.basis || '');
      xiDraw($(el, 'co-sxi'), xi, b.formation, function (p) { return FB.surname(p.name); }, function (p) { return isNum(p.value) ? num(p.value, basis === 'rating' || basis === 'form' ? 1 : 2) : ''; });
      FB.table($(el, 'co-sxt'), [
        { key: 'name', label: 'Player', fmt: function (v, r) { return FB.playerLink(r.id, v); } },
        { key: 'team', label: clubW(), fmt: function (v) { return ctx.club(v); } },
        { key: 'pos', label: 'Pos', fmt: function (v) { return FB.posBadge(v); } },
        { key: 'min', label: 'Min', num: true, fmt: function (v) { return isNum(v) ? String(Math.round(v)) : '—'; } },
        { key: 'value', label: vlab, num: true, fmt: function (v) { return '<b>' + (isNum(v) ? num(v, 2) : '—') + '</b>'; } },
        { key: 'g', label: 'G', num: true }, { key: 'a', label: 'A', num: true }
      ], xi, { caption: 'Season XI' });
    };
    if (Object.keys(sx).length) { FB.wireSeg(body, 'co-ab', function (v) { basis = v; drawSX(); }); drawSX(); }
    // performers
    var apm = xiOnly ? null : $(el, 'co-apm');
    var drawPerf = function () {
      var key = apm.value, m = pp[key];
      if (!m) return;
      var def = pmDefs.filter(function (x) { return x.key === key; })[0] || {};
      $(el, 'co-apd').innerHTML = '<b>' + esc(m.label || def.label || key) + '</b>' + (def.desc ? ' — ' + esc(def.desc) : '') + ' · ' + (m.lower ? 'lower is better' : 'higher is better') + (m.scope === 'gk' ? ' · goalkeepers' : m.scope === 'out' ? ' · outfield players' : '');
      var list = function (box, rs, title) {
        box.innerHTML = '<div class="qk-kicker">' + title + '</div>' + ((rs || []).length ? '<ol class="fb-co-perf">' + rs.map(function (p) {
          return '<li>' + FB.playerLink(p.id, p.name) + ' ' + FB.posBadge(p.pos) + '<span class="qk-muted fb-co-mt">' + esc(p.team) + '</span><b class="fb-num" title="' + (isNum(p.minutes) ? Math.round(p.minutes) + ' minutes' : '') + '">' + FB.fmtMetric(p.value, m.fmt) + '</b>' + FB.pctl(p.pct) + '</li>';
        }).join('') + '</ol>' : cardMsg('Nobody qualifies yet.'));
      };
      list($(el, 'co-apt'), m.top, 'Top 8'); list($(el, 'co-apb'), m.bottom, 'Bottom 8');
    };
    if (apm) { apm.addEventListener('change', drawPerf); drawPerf(); }
    // team rankings
    var atm = $(el, 'co-atm');
    var drawTeamRank = function () {
      var key = atm.value, r = pt[key];
      if (!r) return;
      var dd = tdef(key), rs = r.ranking || [];
      $(el, 'co-atd').innerHTML = '<b>' + esc(r.label || dd.label || key) + '</b>' + (dd.desc ? ' — ' + esc(dd.desc) : '') + ' · ' + (r.lower || dd.lower ? 'lower is better' : 'higher is better');
      var box = $(el, 'co-atc');
      box.style.setProperty('--h', Math.max(240, rs.length * 22 + 40) + 'px');
      var good = function (p) { if (!isNum(p)) return 50; return goodnessFlip(pt, key) ? 100 - p : p; };
      QKC.bar(box, { horizontal: true, labels: true, labelWidth: 120, fmt: function (v) { return FB.fmtMetric(v, r.fmt); }, cats: rs.map(function (x) { return x.team; }),
        valName: r.label || dd.label || key, series: [{ name: r.label || key, data: rs.map(function (x) { return x.value; }) }],
        colors: rs.map(function (x) { return QK.pctHex(good(x.pct)); }), catName: clubW(),
        hrefs: rs.map(function (x) { var id = ctx.tidOf(x.team); return id ? FB.href.club(id, { c: c.slug }) : null; }), label: 'Team ranking' });
    };
    if (xiOnly) return;
    if (atm) { atm.addEventListener('change', drawTeamRank); drawTeamRank(); }
    styleMap($(el, 'co-asm'), ctx, an, pt);
    attackDefence($(el, 'co-aad'), ctx, an, pt, d1.table);
    xptsChart($(el, 'co-axp'), an, d1.table);
    formTable($(el, 'co-afm'), ctx, an);
  });
};
/* Whether a lower-is-better metric's percentile is raw (higher pct = more of it). */
function goodnessFlip(pt, key) {
  var r = (pt[key] || {}).ranking || [];
  if (!(pt[key] || {}).lower || r.length < 2) return false;
  return (r[0].pct || 0) < (r[r.length - 1].pct || 0);
}
function matchLine(c, p) {
  if (!p || !p.opp) return '';
  var s = (p.ha === 'A' ? '@ ' : 'v ') + esc(p.opp) + (isNum(p.gf) ? ' ' + p.gf + '–' + p.ga : '');
  return p.gid ? '<a class="fb-link" href="' + esc(FB.href.match(c.slug, p.gid)) + '">' + s + '</a>' : s;
}
function xiDraw(box, xi, formation, label, sub) {
  if (!box) return;
  if (!(xi || []).length) { box.innerHTML = cardMsg('No line-up to draw.'); return; }
  FB.charts.formation(box, { surface: 'half', label: 'Team drawn on the pitch', points: FB.charts.xiPoints(xi, formation).map(function (q) {
    var p = q.p;
    return { x: q.x, y: q.y, label: label(p), sub: sub(p), rt: p.rt, mark: '', href: p.id ? FB.href.player(p.id) : null,
      tip: p.name + ' · ' + (p.team || '') + (isNum(p.rt) ? ' · rating ' + num(p.rt, 2) : '') + (p.g || p.a ? ' · ' + (p.g || 0) + ' G ' + (p.a || 0) + ' A' : '') };
  }) });
}
function styleMap(box, ctx, an, pt) {
  var keys = STYLE_KEYS.filter(function (k) { return pt[k] && (pt[k].ranking || []).length; });
  if (keys.length < 4) keys = (an.team_metrics || []).map(function (m) { return m.key; }).filter(function (k) { return pt[k] && (pt[k].ranking || []).length; }).slice(0, 10);
  if (!keys.length) { box.innerHTML = '<div class="qk-card-body">' + cardMsg('No team metrics yet.') + '</div>'; return; }
  var names = Object.keys(an.teams || {});
  if (!names.length) names = pt[keys[0]].ranking.map(function (r) { return r.team; });
  var look = {};
  keys.forEach(function (k) { look[k] = {}; pt[k].ranking.forEach(function (r) { look[k][r.team] = r; }); });
  var cols = [{ key: 'team', label: clubW(), sticky: true, fmt: function (v) { return ctx.club(v); } }];
  keys.forEach(function (k) {
    var lab = pt[k].label || k;
    cols.push({ key: '_' + k, label: lab.length > 12 ? lab.slice(0, 11) + '…' : lab, num: true, tip: lab, fmt: function (v, r) {
      if (!isNum(v)) return '<span class="qk-muted">—</span>';
      return '<span class="fb-co-heat' + (r._small ? ' small' : '') + '" style="background:' + QK.pctColor(v) + ';color:' + QK.pctInk(v) + '" title="' + esc(lab + ': ' + FB.fmtMetric(r['__' + k], pt[k].fmt) + ' · ' + QK.ordinal(Math.round(v)) + ' percentile') + '">' + Math.round(v) + '</span>';
    } });
  });
  var rows = names.filter(function (t) { var pl = ((an.teams || {})[t] || {}).played; return !isNum(pl) || pl >= CLUB_MIN; }).map(function (t) {
    var o = { team: t }, tm = (an.teams || {})[t] || {}, prof = tm.profile || {};
    o._small = isNum(tm.played) && tm.played < CLUB_SMALL;
    keys.forEach(function (k) {
      var r = look[k][t] || (prof[k] ? { value: prof[k].v, pct: prof[k].pct } : null);
      var p = r ? r.pct : null;
      if (isNum(p) && pt[k].lower && goodnessFlip(pt, k)) p = 100 - p;   /* 100 = best (the spec's direction) */
      o['_' + k] = p; o['__' + k] = r ? r.value : null;
    });
    return o;
  });
  FB.table(box, cols, rows, { sort: { key: 'team', dir: 'asc' }, caption: 'Style map' });
}
function teamPts(an, table) {
  var out = {};
  Object.keys(an.teams || {}).forEach(function (t) {
    var rds = (an.teams[t] || {}).rounds || [];
    out[t] = { pts: rds.reduce(function (s, r) { return s + (r.pts || 0); }, 0), xpts: rds.reduce(function (s, r) { return s + (r.xpts || 0); }, 0), n: rds.length };
  });
  ((table || {}).standings || (table || {}).overall || []).forEach(function (r) { if (!out[r.team] || !out[r.team].n) out[r.team] = { pts: r.pts || 0, xpts: null, n: r.played || 0 }; });
  return out;
}
function attackDefence(box, ctx, an, pt, table) {
  var xf = (pt.xg_for || {}).ranking || [], xa = (pt.xg_against || {}).ranking || [];
  if (!xf.length || !xa.length) { box.style.height = 'auto'; box.innerHTML = cardMsg('xG for and against are not both available yet.'); return; }
  var A = {}, D = {};
  xf.forEach(function (r) { A[r.team] = r.value; }); xa.forEach(function (r) { D[r.team] = r.value; });
  var pts = teamPts(an, table);
  var teams = Object.keys(A).filter(function (t) { return isNum(D[t]); });
  var maxP = Math.max.apply(null, teams.map(function (t) { return (pts[t] || {}).pts || 0; }).concat([1]));
  QKC.scatter(box, { points: teams.map(function (t) { var id = ctx.tidOf(t); return { x: A[t], y: D[t], name: t + ' · ' + ((pts[t] || {}).pts || 0) + ' pts', label: t, size: 8 + 18 * (((pts[t] || {}).pts || 0) / maxP), href: id ? FB.href.club(id, { c: ctx.slug }) : null }; }),
    xName: 'xG for per match', yName: 'xG against per match', xFmt: function (v) { return num(v, 2); }, yFmt: function (v) { return num(v, 2); },
    refX: FB.median(teams.map(function (t) { return A[t]; })), refY: FB.median(teams.map(function (t) { return D[t]; })), labelTop: 10,
    quadrants: ['Leaky, blunt', 'Open games', 'Tight, blunt', 'Strong both ways'], label: 'Attack against defence' });
}
function xptsChart(box, an, table) {
  var pts = teamPts(an, table);
  var teams = Object.keys(pts).filter(function (t) { return isNum(pts[t].xpts) && pts[t].n > 0; });
  if (!teams.length) { box.style.height = 'auto'; box.innerHTML = cardMsg('No expected points yet.'); return; }
  teams.sort(function (a, b) { return (pts[b].pts - pts[b].xpts) - (pts[a].pts - pts[a].xpts); });
  box.style.setProperty('--h', Math.max(300, teams.length * 22 + 60) + 'px');
  QKC.bar(box, { horizontal: true, legend: true, labelWidth: 120, fmt: function (v) { return num(v, 1); }, valName: 'Points', cats: teams,
    catName: clubW(), series: [{ name: 'Points', data: teams.map(function (t) { return pts[t].pts; }), color: hexOf('var(--c-actual)') || hexOf('var(--volt)') }, { name: 'Expected points (our xG)', data: teams.map(function (t) { return Math.round(pts[t].xpts * 10) / 10; }), color: hexOf('var(--signal)') }],
    label: 'Points against expected points' });
}
function formTable(box, ctx, an) {
  var teams = Object.keys(an.teams || {}).filter(function (t) { return ((an.teams[t] || {}).form || []).length; });
  if (!teams.length) { box.innerHTML = '<div class="qk-card-body">' + cardMsg('No recent matches yet.') + '</div>'; return; }
  var rows = teams.map(function (t) {
    var f = (an.teams[t].form || []).slice(0, 6), chron = f.slice().reverse();
    var sm = function (k) { return f.reduce(function (s, m) { return s + (isNum(m[k]) ? m[k] : 0); }, 0); };
    var p = f.reduce(function (s, m) { return s + (isNum(m.pts) ? m.pts : (m.res === 'W' ? 3 : m.res === 'D' ? 1 : 0)); }, 0);
    var xp = f.some(function (m) { return isNum(m.xpts); }) ? sm('xpts') : null;
    var xgd = f.some(function (m) { return isNum(m.xg) && isNum(m.xga); }) ? sm('xg') - sm('xga') : null;
    return { team: t, chron: chron, n: f.length, pts: p, xpts: xp, luck: isNum(xp) ? p - xp : null, xgd: xgd, spark: chron.map(function (m) { return isNum(m.xg) && isNum(m.xga) ? m.xg - m.xga : 0; }) };
  });
  FB.table(box, [
    { key: 'team', label: clubW(), sticky: true, fmt: function (v) { return ctx.club(v); } },
    { key: 'pts', label: 'Last six', sort: false, fmt: function (v, r) { return FB.formChips(r.chron.map(function (m) { return m.res || 'D'; })); } },
    { key: 'n', label: 'P', num: true }, { key: 'pts', label: 'Pts', num: true, fmt: function (v) { return '<b>' + v + '</b>'; } },
    { key: 'xpts', label: 'xPts', num: true, fmt: function (v) { return num(v, 1); } },
    { key: 'luck', label: 'Luck', num: true, tip: 'Points minus expected points over the window', fmt: function (v) { return isNum(v) ? '<span class="' + (v >= 1 ? 'fb-up' : v <= -1 ? 'fb-down' : '') + '">' + signed(v, 1) + '</span>' : '—'; } },
    { key: 'xgd', label: 'xG diff', num: true, fmt: function (v) { return signed(v, 2); } },
    { key: 'spark', label: 'xG diff by match', sort: false, fmt: function (v) { return QK.spark(v, { w: 90, h: 22, base: 0, color: 'var(--c-1)', label: 'xG difference by match' }); } }
  ], rows, { sort: { key: 'pts', dir: 'desc' }, caption: 'Form' });
}

// ── clubs ─────────────────────────────────────────────────────────────────

LIVE.clubs = function (el, body, c, d0) {
  var names = ['probs', 'strength', 'team_stats'].concat(c.kind === 'liga' ? ['zones'] : ['table']);
  return FB.compFiles(c.slug, names).then(function (d1) {
    if (!FB.alive(el)) return;
    var d = FB.merge(d0, d1), ctx = makeCtx(c, d);
    var teamsMap = (d.teams || {}).teams || {};
    var probs = (d.probs || {}).teams || [];
    var list = Object.keys(teamsMap).length ? Object.keys(teamsMap) : probs.map(function (p) { return p.team; });
    if (!list.length) { body.innerHTML = FB.empty('No clubs yet'); return; }
    var strength = {}; ((d.strength || {}).rows || []).forEach(function (r) { strength[r.team] = r; });
    var stats = (d.team_stats || {}).teams || {};
    var rank = {}, t = d.table || {};
    (t.standings || t.overall || []).forEach(function (r) { rank[r.team] = r; });
    if (t.conferences) Object.keys(t.conferences).forEach(function (g) { t.conferences[g].forEach(function (r) { rank[r.team] = r; }); });
    if (d.zones) Object.keys(d.zones.zones || {}).forEach(function (z) { (d.zones.zones[z].standings || []).forEach(function (r) { rank[r.team] = FB.merge(r, { zone: z }); }); });
    var pBy = {}; probs.forEach(function (p) { pBy[p.team] = p; });
    var order = list.slice().sort(function (a, b) { return ((rank[a] || {}).pos || 99) - ((rank[b] || {}).pos || 99) || a.localeCompare(b); });
    var intl = FB.familyOf(c) === 'international';
    body.innerHTML = '<p class="fb-cap">' + order.length + ' ' + (intl ? 'national teams' : 'clubs') + '. Each opens its one page across every competition it plays, filtered to ' + esc(c.name) + '.</p><div class="fb-co-clubs">' + order.map(function (team) {
      var tid = ctx.tidOf(team), r = rank[team], s = strength[team] || {}, season = (stats[team] || {}).season || {};
      var lines = headline(c, d, pBy[team]).map(function (x) { return '<span><span class="qk-muted">' + esc(x[0]) + '</span><b class="fb-num">' + pct(x[1]) + '</b></span>'; }).join('');
      var hrefC = tid ? FB.href.club(tid, { c: c.slug }) : null;
      return '<' + (hrefC ? 'a href="' + esc(hrefC) + '"' : 'div') + ' class="qk-card is-link fb-co-club">' +
        '<div class="fb-co-club-h">' + FB.crest(tid, team, 'lg') + '<div><div class="fb-co-club-n">' + esc(team) + '</div><div class="fb-cap">' +
        (r ? FB.ordinal(r.pos) + (r.zone ? ' in zone ' + esc(r.zone) : '') + ' · ' + r.pts + ' pts' : esc((teamsMap[team] || {}).conference || '')) + '</div>' + (s.form_results ? FB.formChips(s.form_results) : '') + '</div></div>' +
        (lines ? '<div class="fb-co-club-p">' + lines + '</div>' : '') +
        '<div class="fb-co-club-s"><span>Strength <b class="fb-num">' + num(s.strength_ppg, 2) + '</b></span><span>xG diff <b class="fb-num">' + (isNum(season.xg_diff) ? signed(season.xg_diff, 2) : '—') + '</b></span><span>Luck <b class="fb-num">' + (isNum(s.luck) ? signed(s.luck, 1) : '—') + '</b></span></div>' +
        '</' + (hrefC ? 'a' : 'div') + '>';
    }).join('') + '</div>';
  });
};
function headline(c, d, p) {
  if (!p) return [];
  var k = c.kind;
  if (k === 'liga') return [['Champion', p.p_title], ['Top 8', p.p_top8], ['Relegation', p.p_relegation]];
  if (k === 'conference') return [['MLS Cup', p.p_cup], ['Playoffs', p.p_playoffs], ['Shield', p.p_title]];
  if (k === 'playoff') return [['Champion', p.p_cup], ['Liguilla', p.p_playoffs]];
  if (k === 'cup') return [['Winner', p.p_cup], ['Final', p.p_conference]];
  var bands = (d.probs || {}).bands || [];
  var up = bands.filter(function (b) { return b.kind === 'up'; })[0], downs = bands.filter(function (b) { return b.kind === 'down'; });
  var out = [['Title', p.p_title]];
  if (up) out.push([up.label, (p.bands || {})[up.key]]);
  if (downs.length) out.push(['Relegation', downs.reduce(function (s, b) { return s + ((p.bands || {})[b.key] || 0); }, 0)]);
  return out;
}

// ── seasons ───────────────────────────────────────────────────────────────

LIVE.seasons = function (el, body, c, d0, q, seasons) { seasonsTable(el, body, c, seasons, FB.currentSeason(c).sid); };
/* The History tab (round 9): the roll of honour since the competition began (Wikidata, CC0: data/champions.json, from
   scripts/football_champions_wikidata.py), the titles leaderboard and the records it gives, then every edition the
   site holds (with its own pages). The site's own editions win where both have a season. */
function clubNameFold(s) { return foldName(String(s || '').replace(/\b(F\.?C\.?|C\.?F\.?|A\.?C\.?|S\.?C\.?|A\.?F\.?C\.?|S\.?S\.?C\.?|C\.?D\.?|S\.?L\.?|SAD|e\.?V\.?|national (association )?football team|men's national (association )?football team)\b/gi, ' ')); }
function championName(n) { return String(n || '').replace(/\s+(F\.?C\.?|A\.?F\.?C\.?|C\.?F\.?)$/i, '').replace(/ (men's )?national (association )?football team$/i, '').trim(); }
function historySection(el, host, c, seasons) {
  return Promise.all([FB.load('champions.json'), nameIndex()]).then(function (arr) {
    if (!FB.alive(el)) return;
    var ch = (((arr[0] || {}).competitions || {})[c.slug]) || null;
    var idx = arr[1] || { fold: {}, club: {}, nat: {} };
    /* Wikidata's names to the site's clubs: the folded name, a few hand aliases, else the club whose every word is in
       the Wikidata name ("Real Madrid" in "Real Madrid Club de Fútbol"), the longest such name winning */
    var ALIAS = { 'bayern munich': 'bayern munchen', 'inter milan': 'inter', 'internazionale': 'inter', 'sporting cp': 'sporting' };
    var folds = Object.keys(idx.fold).map(function (f) { return { f: f, w: f.split(' ').filter(Boolean), id: idx.fold[f] }; }).filter(function (x) { return x.w.length; });
    var memo = {};
    var tidOf = function (n) {
      var f = clubNameFold(n);
      if (f in memo) return memo[f];
      var hit = idx.fold[ALIAS[f] || f] || idx.fold[foldName(championName(n))] || null;
      if (!hit) {
        var ws = f.split(' '), best = null;
        folds.forEach(function (x) { if (x.w.length >= 1 && x.w.every(function (w) { return ws.indexOf(w) >= 0; }) && (!best || x.f.length > best.f.length) && x.f.length >= 4) best = x; });
        hit = best ? best.id : null;
      }
      memo[f] = hit;
      return hit;
    };
    var shortSeason = function (sn) { var m = /^(\d{4}(?:[–-]\d{2,4})?)/.exec(String(sn || '')); return m ? m[1] : String(sn || ''); };
    /* the roll: Wikidata's editions, then the site's own champions for seasons it does not list */
    var roll = ((ch || {}).editions || []).map(function (e) { return { season: shortSeason(e[0]), year: e[1], name: championName(e[2]), raw: e[2] }; });
    var known = {}; roll.forEach(function (r) { known[r.year] = 1; });
    seasons.forEach(function (s) {
      if (!(s.champion && s.champion.team)) return;
      var y = parseInt(String(s.era || s.season || '').slice(0, 4), 10);
      if (isNum(y) && !known[y] && !known[y - 1]) roll.push({ season: s.season || s.name, year: y, name: (s.champion.tid && FB.clubName(s.champion.tid)) || s.champion.team, tid: s.champion.tid, ours: true });
    });
    roll.forEach(function (r) { if (!r.tid) r.tid = tidOf(r.raw || r.name); if (r.tid && FB.clubName(r.tid)) r.name = FB.clubName(r.tid); });
    roll.sort(function (a, b) { return (a.year || 0) - (b.year || 0); });
    if (roll.length < 3) { host.innerHTML = ''; return; }
    var count = {}, order = [];
    roll.forEach(function (r) { var k = r.tid || r.name; if (!count[k]) { count[k] = { name: r.name, tid: r.tid, n: 0, last: r.season, first: r.season }; order.push(k); } count[k].n++; count[k].last = r.season; });
    var board = order.map(function (k) { return count[k]; }).sort(function (a, b) { return b.n - a.n || String(a.name).localeCompare(String(b.name)); });
    /* records: the longest run of titles in a row, the first and the latest champion, how many different champions */
    var best = { n: 0 }, run = 0;
    roll.forEach(function (r, i) { run = i && (roll[i - 1].tid || roll[i - 1].name) === (r.tid || r.name) ? run + 1 : 1; if (run > best.n) best = { n: run, name: r.name, tid: r.tid, to: r.season, from: roll[i - run + 1].season }; });
    var latest = roll[roll.length - 1], first = roll[0];
    var mark = function (r) { return FB.crest(r.tid, r.name, 'sm'); };
    var link = function (r) { return r.tid ? '<a href="' + esc(FB.href.club(r.tid, { c: c.slug })) + '">' + esc(r.name) + '</a>' : esc(r.name); };
    var kp = FB.kpis([
      FB.kpi('Most titles', link(board[0]), { text: true, sub: board[0].n + ' since ' + esc(first.season) }),
      FB.kpi('Different champions', String(board.length), { sub: 'in ' + roll.length + ' editions' }),
      FB.kpi('Longest run', best.n + ' in a row', { text: true, sub: esc(best.name) + ', ' + esc(best.from) + (best.n > 1 ? ' to ' + esc(best.to) : '') }),
      FB.kpi('Latest champion', link(latest), { text: true, sub: esc(latest.season) })
    ]);
    var top = board.slice(0, 14);
    host.innerHTML = '<section class="qk-section fb-co-sec">' + QK.sectionHead({ kicker: 'Roll of honour', title: roll.length + ' editions, ' + board.length + ' champions', sub: 'Every champion since ' + esc(first.season) + ', the titles leaderboard and the records it gives. Source: Wikidata (CC0) for the full list, our own data for the seasons we hold.' }) + kp +
      '<div class="fb-mt">' + FB.grid(
        FB.card('The titles leaderboard', 'Titles won, the most first.', FB.chartBox('co-hroll', Math.max(220, top.length * 26 + 50), 'Titles leaderboard'), { span: 5 }) +
        FB.card('Every champion', 'Newest first. A crest marks a club with its own page here.', '<div class="fb-co-roll">' + roll.slice().reverse().map(function (r) {
          return '<div class="fb-co-rolli"><span class="s fb-num">' + esc(r.season) + '</span>' + mark(r) + '<span class="n">' + link(r) + '</span><span class="k fb-num">' + count[r.tid || r.name].n + '</span></div>';
        }).join('') + '</div>', { span: 7 })
      ) + '</div></section>';
    QKC.bar(host.querySelector('#co-hroll'), { horizontal: true, labels: true, labelWidth: 140, fmt: function (v) { return String(v); }, cats: top.map(function (t) { return t.name; }),
      series: [{ name: 'Titles', data: top.map(function (t) { return t.n; }) }], colors: top.map(function (t) { return (t.tid && FB.clubColour(t.tid)) || QK.cssVar('--signal'); }),
      hrefs: top.map(function (t) { return t.tid ? FB.href.club(t.tid, { c: c.slug }) : null; }), valName: 'Titles', catName: clubW(), label: 'Titles leaderboard' });
    /* the full leaderboard makes the held-seasons one a duplicate */
    var sw = el.querySelector('#co-swin');
    var swc = sw ? sw.closest('.qk-card') : null;
    if (swc) { var prev = swc.previousElementSibling; swc.remove(); if (prev) { prev.classList.remove('qk-span-8'); prev.classList.add('qk-span-12'); } }
  });
}
function seasonsTable(el, body, c, seasons, activeSid) {
  var hHost = document.createElement('div');
  var titled = seasons.filter(function (s) { return s.champion && s.champion.team; });
  var counts = {};
  titled.forEach(function (s) { var k = s.champion.tid || s.champion.team; counts[k] = counts[k] || { team: (s.champion.tid && FB.clubName(s.champion.tid)) || s.champion.team, tid: s.champion.tid, n: 0 }; counts[k].n++; });
  var most = Object.keys(counts).map(function (k) { return counts[k]; }).sort(function (a, b) { return b.n - a.n; }).slice(0, 10);
  body.innerHTML = FB.grid(
    FB.card('Every edition we hold', seasons.length + ' with their own pages here. Store seasons have every result; archive seasons the official table and leaders. Coverage: how many finished matches have line-ups (player data).', '<div id="co-sl"></div>', { span: most.length ? 8 : 12, flush: true }) +
    (most.length ? FB.card(c.kind === 'cup' ? 'Most wins on record' : 'Most titles on record', 'Within the editions the site holds.', FB.chartBox('co-swin', Math.max(200, most.length * 26 + 40), 'Titles'), { span: 4 }) : '')
  );
  body.insertBefore(hHost, body.firstChild);
  historySection(el, hHost, c, seasons);
  FB.table($(el, 'co-sl'), [
    { key: 'season', label: 'Season', fmt: function (v, s) { var h = s.source === 'live' ? FB.href.comp(c.slug) : FB.href.comp(c.slug, 'table', { s: s.sid }); return '<a class="fb-link" href="' + esc(h) + '">' + esc(v || s.name || s.sid) + '</a>' + (String(s.sid) === String(activeSid) ? ' ' + FB.badge('Shown', 'accent') : ''); } },
    { key: 'source', label: 'Source', fmt: function (v, s) { return v === 'live' ? FB.badge(s.status === 'last_edition' ? 'Last edition' : 'Current', 'accent') : FB.badge(v === 'store' ? 'Match store' : 'Archive'); } },
    { key: '_ch', label: c.kind === 'cup' ? 'Winner' : 'Champion', fmt: function (v, s) { return s.champion && s.champion.team ? FB.clubLink(s.champion.tid, s.champion.team, { q: { c: c.slug } }) : '<span class="qk-muted">' + (s.source === 'live' ? 'in progress' : '—') + '</span>'; } },
    { key: 'finished', label: 'Results', num: true, fmt: function (v, s) { return isNum(s.matches) ? (isNum(v) ? v : 0) + '/' + s.matches : '—'; } },
    { key: 'detail', label: 'Line-ups', num: true, tip: 'Finished matches with line-ups (player data)', fmt: function (v, s) {
      if (!isNum(v) || !isNum(s.finished)) return '—';
      var chip = s.coverage === 'partial' ? ' <span class="fb-cov partial" data-tip="' + esc((s.unavailable ? s.unavailable + ' matches have no line-ups at Sofascore; ' : '') + 'player lines for this edition are lower bounds.') + '">Partial</span>' : s.coverage === 'full' ? '' : (v === 0 && s.source !== 'live' ? ' <span class="fb-cov none">None</span>' : '');
      return v + chip;
    } }
  ], seasons.map(function (s) { return FB.merge(s, { _ch: s.champion ? s.champion.team : '' }); }), { caption: 'Every edition' });
  if (most.length) QKC.bar($(el, 'co-swin'), { horizontal: true, labels: true, labelWidth: 120, fmt: function (v) { return String(v); }, cats: most.map(function (m) { return m.team; }), valName: 'Titles', series: [{ name: 'Titles', data: most.map(function (m) { return m.n; }) }],
    hrefs: most.map(function (m) { return m.tid ? FB.href.club(m.tid, { c: c.slug }) : null; }), label: 'Titles on record' });
}

// ── a past season ─────────────────────────────────────────────────────────

function openPast(el, c, seasons, sid, tab, q) {
  return FB.loadPastSeason(c, sid).then(function (doc) {
    if (!FB.alive(el)) return;
    if (!doc) {
      $(el, 'co-head').innerHTML = headHTML(c, null, seasons);
      wirePicker(el, c, seasons, tab);
      $(el, 'co-body').innerHTML = FB.empty('No data for this season', 'Pick another edition, or go back to the current one.') + '<p><a class="qk-btn" href="' + esc(FB.href.comp(c.slug)) + '">Current season →</a></p>';
      return;
    }
    return FB.compFile(c.slug, 'teams').then(function (teams) {
      if (!FB.alive(el)) return;
      var ctx = makeCtx(c, { teams: teams });
      var tabs = pastTabs(doc);
      if (tabs.indexOf(tab) < 0) tab = tabs.indexOf('table') >= 0 && tab !== 'overview' ? 'table' : 'overview';
      $(el, 'co-head').innerHTML = headHTML(c, null, seasons, doc);
      wirePicker(el, c, seasons, tab);
      $(el, 'co-tabs').innerHTML = FB.subnav(tabs.map(function (t) { return [FB.href.comp(c.slug, t, { s: sid }), t === 'fixtures' ? 'Results' : tabLabel(c, t), t]; }), tab, c.name + ' ' + (doc.season || ''));
      document.title = (doc.name || c.name) + ' · The Quant Footballer';
      var body = $(el, 'co-body');
      if (tab === 'overview') return pastOverview(el, body, c, ctx, doc);
      if (tab === 'table') { body.innerHTML = FB.card((doc.groups || []).length > 1 ? 'Groups' : 'Final table', doc.standings_source === 'computed' ? 'Computed from the results in the store (points, goal difference, goals scored).' : 'The official table as Sofascore published it.', '<div id="co-pst"></div>', { flush: true }); pastStandings($(el, 'co-pst'), ctx, doc); return; }
      if (tab === 'fixtures') { fixtureBrowser(el, body, c, ctx, (doc.fixtures || []).slice(), q, true); return; }
      if (tab === 'bracket') { body.innerHTML = pastBracket(ctx, doc); return; }
      if (tab === 'players') return pastPlayers(el, body, c, ctx, doc, q);
      if (tab === 'seasons') return seasonsTable(el, body, c, seasons, sid);
    });
  });
}
function pastOverview(el, body, c, ctx, doc) {
  var m = doc.meta || {};
  var champ = m.champion && m.champion.team ? m.champion : null;
  var st = (doc.standings || []).slice().sort(function (a, b) { return (a.pos || 99) - (b.pos || 99); });
  var tiles = [];
  if (champ) tiles.push(FB.kpi(c.kind === 'cup' ? 'Winner' : 'Champion', ctx.club(champ.team, champ.tid), { text: true, sub: esc(doc.season || '') }));
  if (st.length && !(doc.groups || []).length) {
    if (!champ) tiles.push(FB.kpi(c.kind === 'cup' ? 'Top of the league phase' : 'Top of the table', ctx.club(st[0].team, st[0].tid), { text: true, sub: isNum(st[0].pts) ? st[0].pts + ' pts' : '' }));
    if (st[1] && c.kind !== 'cup') tiles.push(FB.kpi('Runner-up', ctx.club(st[1].team, st[1].tid), { text: true, sub: isNum(st[1].pts) ? st[1].pts + ' pts' : '' }));
  }
  var fin = (doc.bracket || []).filter(function (t) { return t.round === 'final'; }).slice(-1)[0];
  if (fin && champ && c.kind === 'cup') {
    var loser = fin.home === champ.team ? fin.away : fin.away === champ.team ? fin.home : null;
    if (loser) tiles.push(FB.kpi('Runner-up', ctx.club(loser, fin.home === champ.team ? fin.away_id : fin.home_id), { text: true, sub: 'final ' + (fin.home === champ.team ? fin.hs + '–' + fin.as : fin.as + '–' + fin.hs) }));
  }
  var g = ((doc.leaders || {}).goals || [])[0];
  if (g) tiles.push(FB.kpi('Top scorer', g.id ? FB.playerLink(g.id, g.name) : esc(g.name), { text: true, sub: (g.value || 0) + ' goals · ' + esc(g.team || '') }));
  if ((doc.fixtures || []).length) tiles.push(FB.kpi('Matches', String((doc.fixtures || []).filter(function (f) { return f.status === 'finished'; }).length), { sub: (isNum(doc.detail_matches) ? doc.detail_matches + ' with line-ups' : 'results') }));
  var holds = [];
  if (st.length) holds.push(doc.standings_source === 'computed' ? 'a table computed from the results' : 'the official final table');
  if ((doc.fixtures || []).length) holds.push('every result');
  if ((doc.players || []).length) holds.push('player lines from ' + (doc.detail_matches || 0) + ' matches with line-ups');
  if (Object.keys(doc.leaders || {}).length) holds.push('the season\'s leaders');
  body.innerHTML = (tiles.length ? FB.kpis(tiles) : '') +
    '<p class="fb-cap">' + (doc.source === 'store' ? 'From the match store' : 'From the archive') + ': ' + esc(holds.join(', ') || 'the season name only') + '.' + (doc.coverage === 'partial' ? ' Coverage is partial: player lines are lower bounds.' : '') + '</p>' +
    FB.grid(
      (st.length ? FB.card((doc.groups || []).length > 1 ? 'Groups' : 'Final table', null, '<div id="co-pst"></div>', { span: 7, flush: true }) : '') +
      FB.card('Leaders', 'Sofascore\'s season leaderboards.', '<div class="fb-co-minis" id="co-pld"></div>', { span: st.length ? 5 : 12, foot: '<span></span><a href="' + esc(FB.href.comp(c.slug, 'players', { s: doc.sid })) + '">Every leaderboard →</a>' })
    , 'fb-mt');
  if (st.length) pastStandings($(el, 'co-pst'), ctx, doc);
  /* a recap, not an empty template (round 9): the knockout with its scores, and our calls against what happened */
  var rec = document.createElement('div');
  rec.className = 'fb-mt';
  body.appendChild(rec);
  var ko = (doc.bracket || []).length ? '<div class="fb-mt">' + FB.card('The knockout', 'Every tie with its score; the side that went through in bold.', pastBracket(ctx, doc), {}) + '</div>' : '';
  FB.load('forecast_log.json').then(function (log) {
    if (!FB.alive(el)) return;
    var done = (doc.fixtures || []).filter(function (f) { return f.status === 'finished' && isNum(f.hs) && isNum(f.as); });
    var n = 0, hit = 0, exp = 0;
    done.forEach(function (f) {
      var l = (log || {})[String(f.id)];
      if (!l || !isNum(l[0])) return;
      n++;
      var p = [l[0], l[1], l[2]], res = f.hs > f.as ? 0 : f.hs === f.as ? 1 : 2, fav = p.indexOf(Math.max.apply(null, p));
      if (fav === res) hit++;
      exp += Math.max.apply(null, p);
    });
    var calls = n >= 10 ? FB.card('Our calls against what happened', n + ' of the edition’s matches had our chance logged before kick-off.',
      FB.kpis([FB.kpi('Our favourite won', pct(hit / n), { signal: true, sub: hit + ' of ' + n + ' matches' }), FB.kpi('We expected', pct(exp / n), { sub: 'the average chance we gave our favourite' })]) +
      QK.explain('When the two numbers are close, our chances meant what they said: a 60% favourite should win about 6 times in 10.', { title: 'What’s that number?' }), {})
      : FB.card('Our calls against what happened', '', FB.muted('Our chances for this edition were not logged before kick-off: the frozen pre-match log starts in October 2026. Every match from then on is checked in <a href="#/model/calibration">How we’re doing</a>.'), {});
    rec.innerHTML = ko + '<div class="fb-mt">' + calls + '</div>';
  });
  var L = doc.leaders || {};
  $(el, 'co-pld').innerHTML = ['goals', 'assists', 'rating', 'expectedGoals'].filter(function (k) { return (L[k] || []).length; }).map(function (k) { return leaderMini(ctx, k, L[k].slice(0, 5)); }).join('') || cardMsg('No leaders recorded for this season.');
}
function leaderMini(ctx, k, rows) {
  var def = LEADER_LABELS[k] || [k, '2'];
  return '<div class="fb-co-mini"><div class="qk-kicker">' + esc(def[0]) + (def[2] ? ' (lower is better)' : '') + '</div><ol>' + rows.map(function (p) {
    return '<li>' + (p.id ? FB.playerLink(p.id, p.name) : esc(p.name)) + '<span class="qk-muted fb-co-mt">' + esc(p.team || '') + '</span><b class="fb-num">' + FB.fmtMetric(p.value, Math.round(p.value) === p.value ? 'int' : def[1]) + '</b></li>';
  }).join('') + '</ol></div>';
}
function pastStandings(box, ctx, doc) {
  var st = (doc.standings || []).slice().sort(function (a, b) { return (a.pos || 99) - (b.pos || 99); });
  if (!st.length) { box.innerHTML = '<div class="qk-card-body">' + cardMsg('No final table for this season.') + '</div>'; return; }
  var full = st.some(function (r) { return has(r.w); });
  var cols = [{ key: 'pos', label: '#', num: true }, { key: 'team', label: clubW(), sticky: true, fmt: function (v, r) { return ctx.club(v, r.tid); } }, { key: 'played', label: 'P', num: true }];
  if (full) cols = cols.concat([{ key: 'w', label: 'W', num: true }, { key: 'd', label: 'D', num: true }, { key: 'l', label: 'L', num: true }, { key: 'gf', label: 'GF', num: true }, { key: 'ga', label: 'GA', num: true }, { key: 'gd', label: 'GD', num: true, fmt: function (v) { return isNum(v) ? signed(v, 0) : '—'; } }]);
  cols.push({ key: 'pts', label: 'Pts', num: true, fmt: function (v) { return '<b>' + (isNum(v) ? v : '—') + '</b>'; } }, { key: 'note', label: 'Outcome', sort: false, fmt: function (v) { return noteChip(v); } });
  var groups = (doc.groups || []).length ? doc.groups : uniq(st.map(function (r) { return r.group; }).filter(Boolean));
  if (groups.length > 1) {
    box.innerHTML = '<div class="fb-co-groups many fb-co-pad">' + groups.map(function (gname, i) { return '<div><div class="qk-kicker">' + esc(gname) + '</div><div id="co-pg-' + i + '"></div></div>'; }).join('') + '</div>';
    groups.forEach(function (gname, i) { FB.table(box.querySelector('#co-pg-' + i), cols, st.filter(function (r) { return r.group === gname; })); });
  } else FB.table(box, cols, st, { caption: 'Final table' });
}
function pastBracket(ctx, doc) {
  var ties = [], byKey = {};
  (doc.bracket || []).forEach(function (m) {
    var k = m.round + '|' + [m.home, m.away].sort().join('|');
    var t = byKey[k];
    if (!t) { t = { round: m.round, a: m.home, aid: m.home_id, b: m.away, bid: m.away_id, ga: 0, gb: 0, legs: 0, winner: null }; byKey[k] = t; ties.push(t); }
    var aHome = m.home === t.a;
    if (isNum(m.hs)) { t.ga += aHome ? m.hs : m.as; t.gb += aHome ? m.as : m.hs; t.legs++; }
    if (m.agg_winner || m.winner) t.winner = m.agg_winner || m.winner;
  });
  ties.forEach(function (t) { if (!t.winner && t.legs) t.winner = t.ga > t.gb ? t.a : t.gb > t.ga ? t.b : null; });
  var rounds = uniq(ties.map(function (t) { return t.round; })).sort(function (a, b) { return ROUND_ORDER.indexOf(a) - ROUND_ORDER.indexOf(b); });
  return FB.card('Knockout ties', 'Aggregate over both legs where there were two; the winner is highlighted (penalties count where the payload records them).',
    '<div class="fb-co-ladder">' + rounds.map(function (r) {
      return '<div class="fb-co-round"><div class="qk-kicker">' + esc(FB.ROUND_LABELS[r] || r) + '</div>' + ties.filter(function (t) { return t.round === r; }).map(function (t) {
        var side = function (team, id, gg) { return '<div class="fb-co-side' + (t.winner && t.winner === team ? ' win' : t.winner ? ' out' : '') + '">' + ctx.club(team, id) + '<b class="fb-num">' + (t.legs ? gg : '') + '</b></div>'; };
        return '<div class="fb-co-tie"' + (t.legs > 1 ? ' title="' + t.legs + ' legs"' : '') + '>' + side(t.a, t.aid, t.ga) + side(t.b, t.bid, t.gb) + '</div>';
      }).join('') + '</div>';
    }).join('') + '</div>');
}
function pastPlayers(el, body, c, ctx, doc, q) {
  var all = doc.players || [], metrics = doc.metrics || [];
  var L = doc.leaders || {};
  var lk = LEADER_ORDER.filter(function (k) { return (L[k] || []).length; }).concat(Object.keys(L).filter(function (k) { return LEADER_ORDER.indexOf(k) < 0 && (L[k] || []).length; }));
  var leadersCard = FB.card('Season leaders', 'Sofascore\'s season leaderboards' + (doc.source === 'store' ? '' : ' from the archive') + '.', lk.length ? '<div class="fb-co-minis wide">' + lk.map(function (k) { return leaderMini(ctx, k, L[k].slice(0, 8)); }).join('') + '</div>' : cardMsg('No leaders recorded for this season.'));
  var linesCard = all.length ? FB.card('Player lines', all.length + ' players · lines from ' + (doc.detail_matches || 0) + ' matches with line-ups' + ((doc.detail_matches || 0) < 50 ? ' (a small sample: read rates with care)' : '') + (doc.coverage === 'partial' ? ' · coverage is partial, so totals are lower bounds' : '') + '. Percentiles within this season.',
    FB.toolbar([
      FB.field('Metric', FB.select('co-ppm', (metrics.length ? metrics : [{ key: 'goals', label: 'Goals' }, { key: 'assists', label: 'Assists' }, { key: 'rating', label: 'Rating' }]).map(function (m) { return [m.key, m.label]; }), 'goals', 'Metric')),
      FB.field('Position', FB.select('co-ppp', [['', 'All positions'], ['G', 'Goalkeepers'], ['D', 'Defenders'], ['M', 'Midfielders'], ['F', 'Forwards']], '', 'Position')),
      FB.field('Min. minutes', '<input class="qk-input fb-co-num" id="co-ppmin" type="number" min="0" step="90" value="90" aria-label="Minimum minutes">')
    ]) + '<div id="co-ppl"></div>') : '';
  body.innerHTML = q.view === 'leaders' || !all.length ? leadersCard + (linesCard ? '<div class="fb-mt">' + linesCard + '</div>' : '') : linesCard + '<div class="fb-mt">' + leadersCard + '</div>';
  if (!all.length) return;
  var opts = metrics.length ? metrics : [{ key: 'goals', label: 'Goals', fmt: 'int' }, { key: 'assists', label: 'Assists', fmt: 'int' }, { key: 'rating', label: 'Rating', fmt: '2' }];
  var ms = $(el, 'co-ppm'), ps = $(el, 'co-ppp'), mm = $(el, 'co-ppmin');
  var draw = function () {
    var m = opts.filter(function (x) { return x.key === ms.value; })[0] || opts[0], key = m.key, floor = parseInt(mm.value, 10) || 0;
    var rows = all.filter(function (p) { return (p.minutes || 0) >= floor && (!ps.value || (ps.value === 'G' ? p.is_gk : p.position === ps.value)) && has(p[key]); })
      .sort(function (a, b) { return m.lower ? a[key] - b[key] : b[key] - a[key]; }).slice(0, 100).map(function (p) { return FB.merge(p, { _v: p[key], _p: (p.pct || {})[key] }); });
    FB.table($(el, 'co-ppl'), [
      { key: 'name', label: 'Player', sticky: true, fmt: function (v, r) { return FB.playerLink(r.player_id, v, { q: { c: c.slug } }); } },
      { key: 'team', label: clubW(), fmt: function (v) { return ctx.club(v); } },
      { key: 'position', label: 'Pos', fmt: function (v) { return FB.posBadge(v); } },
      { key: 'minutes', label: 'Min', num: true },
      { key: '_v', label: m.label, num: true, pctl: '_p', fmt: function (v) { return '<b>' + FB.fmtMetric(v, m.fmt) + '</b>'; } },
      { key: 'goals', label: 'G', num: true }, { key: 'assists', label: 'A', num: true },
      { key: 'rating', label: 'Rating', num: true, fmt: function (v) { return isNum(v) ? num(v, 2) : '—'; } }
    ], rows, { rank: true, maxHeight: 620, caption: 'Season player lines' });
  };
  ms.addEventListener('change', draw); ps.addEventListener('change', draw); mm.addEventListener('input', draw);
  draw();
}

FB.competition = { tabLabel: tabLabel, liveTabs: liveTabs, makeCtx: makeCtx, nameIndex: nameIndex };
})(window.FB);
