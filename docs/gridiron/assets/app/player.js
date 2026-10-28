/* The Quant Gridiron — the player page (#/player/<pid>), position-aware, on kit v4 "Broadcast" (the Rink player page is
 * the reference, MIGRATION_V4.md). Top, as the concept: a crumb; the full-bleed team-colour hero (QK.playerHeader: the
 * alternate colour on the diagonal, the outlined number or initials, the name in Bebas, chips) with the black strip of
 * five numbers (percentile chips) and "The short version" in plain English from this season's percentiles; the LED
 * percentile meters on the metrics spec's headline set against the player's role (QB, RB, WR, TE, outside pass
 * rushers, interior linemen, LB, CB, S, K, P; spec.js), with a plain line per metric, early-sample markers and last
 * season's ▼ (the payload's current.prev_pct_pos, else last season's catalogue when the rail scrolls into view), and
 * "How sure are we?" under them (when the numbers settle at this workload, from the spec's M50 samples); beside them
 * the tale of the tape against the closest match in the role (chips switch, "All three in Compare") with verdicts;
 * what to watch next (the scoreboard bug and how the teams match up, season.json) beside the last game (the score by
 * quarter with team totals and the win-chance race, from the game file); the game log (the best game highlighted);
 * game by game and "Their type". Below, "More on the player": playing style, where the player sits among peers, value
 * and movement, the position charts (QB pass grid; RB RYOE by game; WR/TE depth profile; K field goals by distance;
 * defenders' splash plays), season by season, Next Gen Stats and FTN splits. Reads players/<pid>.json, glossary.json
 * (metric labels), <S>/valuation.json (current season), <S>/players.json and <S>/value.json (peers), last season's two
 * for the ▼, <S>/season.json (the next game) and the last game's file. */
(function (GI) {
'use strict';

const QK = window.QK, QKC = window.QKC;
const esc = GI.esc, isNum = GI.isNum, first = GI.first;

const LABEL = {
  season: 'Season', team: 'Team', games: 'G', att: 'Att', cmp: 'Cmp', pass_yds: 'Pass yds', pass_td: 'Pass TD', ints: 'INT', int: 'INT', sacks: 'Sacks', anya: 'ANY/A', any_a: 'ANY/A',
  carries: 'Car', rush_yds: 'Rush yds', rush_td: 'Rush TD', ypc: 'Y/C', targets: 'Tgt', rec: 'Rec', rec_yds: 'Rec yds', rec_td: 'Rec TD', epa: 'EPA', epa_db: 'EPA/db', epa_total: 'EPA',
  cpoe: 'CPOE', success: 'Success', composite: 'Composite', value: 'Value', rush_epa: 'EPA/carry', ryoe: 'RYOE/carry', rec_epa: 'Rec EPA', rec_epa_tgt: 'EPA/tgt', target_share: 'Tgt share',
  adot: 'aDOT', yacoe: 'YACOE', fga: 'FGA', fgm: 'FGM', fg_pct: 'FG%', fg_oe: 'FG OE', pts_oe: 'Pts OE', fg_50: '50+ made', xp_pct: 'XP%', punts: 'Punts', gross: 'Gross', net: 'Net', epa_punt: 'EPA/punt',
  tackles: 'Tkl', tfl: 'TFL', qb_hits: 'QB hits', pd: 'PD', ff: 'FF', def_value: 'Splash EPA', sack_rate: 'Sack%', age: 'Age',
  p_cmp: 'Cmp', p_att: 'Att', p_yds: 'Pass yds', p_td: 'Pass TD', p_ints: 'INT', p_sacks: 'Sacked', p_db: 'Dropbacks', p_epa: 'Pass EPA', p_epa_db: 'EPA/db',
  r_car: 'Car', r_yds: 'Rush yds', r_td: 'Rush TD', r_epa: 'Rush EPA', r_ryoe: 'RYOE', x_tgt: 'Tgt', x_rec: 'Rec', x_yds: 'Rec yds', x_td: 'Rec TD', x_epa: 'Rec EPA', x_air: 'Air yds',
  k_fga: 'FGA', k_fgm: 'FGM', k_xpa: 'XPA', k_xpm: 'XPM', d_sacks: 'Sacks', d_hits: 'QB hits', d_tkl: 'Tkl', d_int: 'INT', d_pd: 'PD',
  avg_time_to_throw: 'Time to throw', avg_completed_air_yards: 'Completed air yds', avg_intended_air_yards: 'Intended air yds', avg_air_yards_differential: 'Air yds differential', aggressiveness: 'Aggressiveness',
  max_completed_air_distance: 'Longest completed air', avg_air_yards_to_sticks: 'Air yds to the sticks', completion_percentage_above_expectation: 'CPOE (NGS)', expected_completion_percentage: 'Expected comp%', passer_rating: 'Passer rating',
  efficiency: 'Efficiency', percent_attempts_gte_eight_defenders: '8+ in the box', avg_time_to_los: 'Time to the line', expected_rush_yards: 'Expected rush yds', rush_yards_over_expected: 'RYOE (NGS)',
  rush_yards_over_expected_per_att: 'RYOE/carry (NGS)', rush_pct_over_expected: 'Rushes over expected', avg_cushion: 'Cushion', avg_separation: 'Separation', percent_share_of_intended_air_yards: 'Share of team air yds', catch_percentage: 'Catch %',
  avg_yac: 'YAC', avg_expected_yac: 'Expected YAC', avg_yac_above_expectation: 'YAC over expected (NGS)', play_action: 'Play action', screen: 'Screens', out_of_pocket: 'Out of pocket',
  interception_worthy: 'INT-worthy throws', throw_aways: 'Throwaways', blitzed: 'Blitzed', catchable: 'Catchable targets', created: 'Created receptions', drops: 'Drops', contested: 'Contested'
};
let META = {};
function label(k) { if (/^plus_/.test(k)) return label(k.slice(5)) + '+'; return (META[k] && META[k].label) || LABEL[k] || GI.titleCase(String(k).replace(/_pct$/, ' %').replace(/_oe$/, ' OE').replace(/_per_/, '/')); }
function guessFmt(k, v) {
  if (META[k] && META[k].fmt) return META[k].fmt;
  const key = String(k).toLowerCase();
  if (!isNum(v)) return '';
  if (/^(season|week|games|g)$/.test(key)) return 'int';
  if (/sacks$/.test(key)) return Number(v) % 1 ? '1' : 'int';
  if (key === 'age') return '1';
  if (/^plus_/.test(key)) return '0';
  if (/^(p|r|x)_(epa|ryoe)$/.test(key)) return 'signed1';
  if (key === 'cpoe' || key === 'completion_percentage_above_expectation') return 'signed1';
  if (/epa.*(per|play|_db|tgt|punt)|^epa_/.test(key)) return 'signed3';
  if (/epa|value|_oe$|^ryoe/.test(key)) return Math.abs(v) < 1 ? 'signed3' : 'signed1';
  if (/time_to|ttt/.test(key)) return 'sec';
  if (/^(percent_|catch_percentage|expected_completion)/.test(key)) return Math.abs(v) > 1.5 ? '1' : 'pct';
  if (/rate$|pct$|_pct|share|^success$|^play_action$|^screen$|^out_of_pocket$|^blitzed$|^catch$/.test(key)) return Math.abs(v) <= 1.5 ? 'pct' : '1';
  if (Number.isInteger(Number(v))) return 'int';
  return Math.abs(v) < 1 ? '3' : '1';
}
function fv(k, v) { return GI.fmtVal(v, guessFmt(k, v)); }
function flat(r) {
  if (!r || typeof r !== 'object') return {};
  const out = Object.assign({}, r);
  if (r.plus && typeof r.plus === 'object') Object.keys(r.plus).forEach(x => { out['plus_' + x] = r.plus[x]; });
  delete out.plus;
  return out;
}
const TILES = {
  QB: [['QB composite', ['composite'], '100 = average, 10 = one SD'], ['EPA per dropback', ['epa_db', 'epa_play'], 'passes, sacks and scrambles'], ['CPOE', ['cpoe'], 'completion % over expected'], ['Success rate', ['success'], ''], ['aDOT', ['adot'], 'air yards per attempt'], ['Time to throw', ['ttt'], 'seconds']],
  RB: [['RYOE per carry', ['ryoe'], 'rush yards over expected'], ['EPA per carry', ['rush_epa'], 'designed runs'], ['Yards per carry', ['ypc'], ''], ['Success rate', ['rush_success', 'success'], ''], ['Explosive rate', ['explosive'], '10+ yard carries'], ['Target share', ['target_share'], '']],
  WR: [['Target share', ['target_share'], 'of team attempts'], ['EPA per target', ['rec_epa_tgt'], ''], ['aDOT', ['adot'], 'depth of target'], ['YAC over expected', ['yacoe'], 'per reception'], ['Catch rate OE', ['croe'], ''], ['Drop rate', ['drop_rate'], 'FTN']],
  K: [['FG over expected', ['fg_oe'], 'makes above our model'], ['Points over expected', ['pts_oe'], 'FGs and extra points'], ['FG%', ['fg_pct'], ''], ['50+ made', ['fg_50'], ''], ['XP%', ['xp_pct'], '']],
  P: [['EPA per punt', ['epa_punt'], ''], ['Net average', ['net'], 'yards'], ['Gross average', ['gross'], 'yards'], ['Inside the 20', ['inside20'], ''], ['Touchback rate', ['touchback_rate'], '']],
  DEF: [['Splash EPA', ['def_value'], 'EPA on credited plays'], ['Sacks', ['sacks'], ''], ['QB hits', ['qb_hits'], ''], ['Tackles for loss', ['tfl'], ''], ['Interceptions', ['ints'], ''], ['Passes defensed', ['pd'], '']]
};
TILES.TE = TILES.WR;
const CAREER = {
  QB: ['season', 'team', 'games', 'att', 'pass_yds', 'pass_td', 'ints', 'anya', 'cpoe', 'epa_db', 'success', 'composite', 'value'],
  RB: ['season', 'team', 'games', 'carries', 'rush_yds', 'ypc', 'rush_td', 'ryoe', 'rush_epa', 'targets', 'rec', 'rec_yds', 'value'],
  WR: ['season', 'team', 'games', 'targets', 'rec', 'rec_yds', 'rec_td', 'target_share', 'adot', 'rec_epa_tgt', 'yacoe', 'value'],
  K: ['season', 'team', 'games', 'fga', 'fgm', 'fg_pct', 'fg_50', 'fg_oe', 'pts_oe', 'xp_pct', 'value'],
  P: ['season', 'team', 'games', 'punts', 'gross', 'net', 'epa_punt', 'value'],
  DEF: ['season', 'team', 'games', 'tackles', 'tfl', 'sacks', 'qb_hits', 'ints', 'pd', 'ff', 'def_value', 'value']
};
CAREER.TE = CAREER.WR;
const ST = { grid: 'epa', dist: null };
const DEPTH_RANK = ['behind', 'behind los', '<0', 'short', '0-9', 'intermediate', '10-19', 'deep', '20+'];
const dRank = d => { const i = DEPTH_RANK.indexOf(String(d).toLowerCase()); return i < 0 ? 50 : i; };
const dLabel = d => ({ behind: 'Behind LOS', short: 'Short (0–9)', intermediate: 'Intermediate (10–19)', deep: 'Deep (20+)' })[String(d).toLowerCase()] || GI.titleCase(d);

function factsTable(obj, empty) {
  if (!obj || typeof obj !== 'object' || !Object.keys(obj).length) return GI.muted(empty);
  const keys = Object.keys(obj).filter(x => isNum(obj[x]) && !/^(season|week)$/.test(x));
  if (!keys.length) return GI.muted(empty);
  return '<dl class="gi-dl">' + keys.map(x => '<dt>' + esc(label(x)) + '</dt><dd class="gi-num">' + fv(x, obj[x]) + '</dd>').join('') + '</dl>';
}

/* Game by game: one plain chart per role from the player's game log, the best game annotated. */
function gameByGame(group, log) {
  const has = k => log.some(r => isNum(r[k]));
  if (!log.length) return null;
  if (group === 'QB' && has('p_epa')) return { title: 'Passing, game by game', sub: 'Expected points added on dropbacks in each game: above zero beats an average passer', y: 'Passing EPA in the game', s: [['p_epa', 'Passing EPA', 'signal']], signed: true };
  if (group === 'RB' && has('r_yds')) return { title: 'Yards, game by game', sub: 'Rushing and receiving yards in each game', y: 'Yards from scrimmage', s: [['r_yds', 'Rushing', 'coral'], ['x_yds', 'Receiving', 'sky']] };
  if ((group === 'WR' || group === 'TE') && has('x_yds')) return { title: 'Receiving, game by game', sub: 'Receiving yards in each game; catches and targets in the tooltip', y: 'Receiving yards', s: [['x_yds', 'Receiving yards', 'signal']] };
  if (group === 'DEF' && has('d_tkl')) return { title: 'Tackles, game by game', sub: 'Tackles in each game; sacks, interceptions and passes defensed in the tooltip', y: 'Tackles in the game', s: [['d_tkl', 'Tackles', 'signal']] };
  if (group === 'K' && has('k_fga')) return { title: 'Field goals, game by game', sub: 'Made and missed field goals in each game', y: 'Field-goal tries', s: [['k_fgm', 'Made', 'signal'], ['k_miss', 'Missed', 'coral']] };
  if (group === 'P' && has('u_punts')) return { title: 'Punts, game by game', sub: 'Punts in each game; net average in the tooltip', y: 'Punts in the game', s: [['u_punts', 'Punts', 'signal']] };
  return null;
}
function drawGameByGame(id, spec, log) {
  const rows = log.map(r => Object.assign({}, r, { k_miss: isNum(r.k_fga) && isNum(r.k_fgm) ? r.k_fga - r.k_fgm : null }));
  const cats = rows.map(r => 'W' + r.week + '\n' + ((GI.parseGameId(r.game_id) || {}).home === r.team ? 'v ' : '@ ') + (r.opp || ''));
  const tot = r => spec.s.reduce((a, x) => a + (isNum(r[x[0]]) ? Number(r[x[0]]) : 0), 0);
  let bi = -1, bv = -1e9;
  rows.forEach((r, i) => { const v = tot(r); if (v > bv) { bv = v; bi = i; } });
  const fmt = v => (spec.signed ? GI.signed(v, 1) : GI.num(v, v % 1 ? 1 : 0));
  QKC.mount('#' + id, T => {
    const xa = QKC.axis(T, { type: 'category', data: cats, split: false, line: true });
    xa.axisLabel.interval = rows.length > 12 ? 'auto' : 0; xa.axisLabel.lineHeight = 14; xa.axisLabel.fontSize = rows.length > 10 ? 10 : 11.5;
    const ya = QKC.axis(T, { fmt: v => (spec.signed ? GI.signed(v, 0) : String(v)) });
    ya.max = function (v) { if (!(v.max > 0)) return 1; var x = v.max * 1.2, p = Math.pow(10, Math.floor(Math.log(x) / Math.LN10)), n = [1, 2, 2.5, 5, 10].filter(function (k) { return k * p >= x; })[0]; return n * p; }; /* headroom for the best-game note, on a round number */
    const gB = 26 + QKC.nameAxis(xa, 'Week and opponent', 'bottom'), gT = 26 + QKC.nameAxis(ya, spec.y, 'side');
    xa.nameGap = 40;
    const col = k => (k === 'coral' ? T.coral : k === 'sky' ? T.sky : T.model);
    const tip = QKC.tooltip(T, { trigger: 'axis', axisPointer: { type: 'shadow', shadowStyle: { color: 'rgba(125,147,255,.10)' } }, formatter: ps => {
      const r = rows[ps[0].dataIndex];
      const extra = spec.s[0][0] === 'x_yds' ? QKC.tipRow(T.ink3, 'Catches / targets', (r.x_rec || 0) + ' / ' + (r.x_tgt || 0)) + QKC.tipRow(T.ink3, 'Touchdowns', r.x_td || 0)
        : spec.s[0][0] === 'd_tkl' ? QKC.tipRow(T.ink3, 'Sacks', r.d_sacks || 0) + QKC.tipRow(T.ink3, 'Interceptions', r.d_int || 0) + QKC.tipRow(T.ink3, 'Passes defensed', r.d_pd || 0)
        : spec.s[0][0] === 'p_epa' ? QKC.tipRow(T.ink3, 'Completions', (r.p_cmp || 0) + ' of ' + (r.p_att || 0)) + QKC.tipRow(T.ink3, 'Yards', r.p_yds || 0) + QKC.tipRow(T.ink3, 'TD / INT', (r.p_td || 0) + ' / ' + (r.p_ints || 0))
        : spec.s[0][0] === 'u_punts' ? QKC.tipRow(T.ink3, 'Net average', GI.num(r.u_net, 1)) : '';
      return '<b>' + esc('Week ' + r.week + ' · ' + ((GI.parseGameId(r.game_id) || {}).home === r.team ? 'v ' : 'at ') + GI.teamName(r.opp)) + '</b>' + spec.s.map(x => QKC.tipRow(col(x[2]), x[1], fmt(isNum(r[x[0]]) ? r[x[0]] : 0))).join('') + extra;
    } });
    const series = spec.s.map((x, si) => ({ type: 'bar', name: x[1], stack: spec.s.length > 1 ? 'g' : undefined, barMaxWidth: 30,
      data: rows.map((r, i) => {
        const v = isNum(r[x[0]]) ? Number(r[x[0]]) : 0;
        const last = si === spec.s.length - 1;
        const o = { value: v, itemStyle: { color: spec.signed && v < 0 ? T.coral : col(x[2]), borderColor: T.s1, borderWidth: spec.s.length > 1 ? 1 : 0 } };
        if (last && i === bi && bv > 0 && rows.length >= 3) o.label = Object.assign(QKC.annot(T), { show: true, position: 'top', formatter: 'best: ' + fmt(bv) });
        return o;
      }) }));
    return { grid: { left: 8, right: 12, top: gT, bottom: gB, containLabel: true }, xAxis: xa, yAxis: ya, tooltip: tip, series: series,
      legend: spec.s.length > 1 ? { top: 0, right: 0, itemWidth: 12, itemHeight: 12, icon: 'rect', textStyle: { color: T.ink2, fontFamily: T.fontCond, fontSize: 13, fontWeight: 700 } } : undefined };
  }, { label: spec.title });
}

/* v3 (Matchday): a plain-English line under each metric on the percentile rail, and the type a player's best metric
   suggests (compare verdicts). Metric ids are the spec's (spec.js). */
const SUB = {
  composite: 'Our all-round passing grade, built to forecast next season.',
  epa_db: 'Points added each time the quarterback drops back.',
  cpoe: 'Completions beyond what the throws themselves predict.',
  sack_rate: 'How rarely a dropback ends in a sack.',
  int_rate: 'How rarely a throw is picked off. Very noisy.',
  pressure_rate: 'How rarely the pocket collapses.',
  gvar_pg: 'Value above a replacement player, per game.',
  ryoe: 'Yards a carry beyond what the blocking gave.',
  rush_success: 'Carries that keep the offence on schedule.',
  explosive: 'Carries of 10 yards or more: the steadiest running number.',
  rush_epa: 'Points added per designed run.',
  stuff_rate: 'How rarely a carry is stopped at or behind the line.',
  target_share: 'Share of the team’s throws that go the player’s way.',
  yptpa: 'Receiving yards for every team pass: a stand-in for yards per route.',
  rec_epa_tgt: 'Points added when the player is the target.',
  croe: 'Catches beyond what the throws predict.',
  yac_rec: 'Yards after the catch, per catch.',
  pressures_pg: 'Sacks and quarterback hits per game.',
  tfl_pg: 'Tackles behind the line per game.',
  tackles_pg: 'Tackles per game: involvement, not quality.',
  ff_pg: 'Forced fumbles per game. Very noisy.',
  pd_pg: 'Passes broken up or picked off per game.',
  ints_pg: 'Interceptions per game. Mostly luck year to year.',
  splash_pg: 'Sacks, takeaways, break-ups and tackles for loss per game.',
  fg_oe: 'Field goals made beyond what the distances predict.',
  fg_50_pct: 'Make rate from 50 yards and beyond.',
  xp_pct: 'Extra points made.',
  fg_50: 'Field goals of 50+ yards made.',
  epa_punt: 'Points gained per punt, returns included.',
  net: 'Distance less returns and touchbacks.',
  gross: 'Raw distance: the steadiest punting number.',
  inside20: 'Punts that pin the opponent inside the 20.',
  touchback_rate: 'How rarely a punt rolls into the end zone.'
};
const ARCHETYPE = { composite: 'The all-round passer', epa_db: 'The efficient passer', cpoe: 'The accurate passer', sack_rate: 'The sack-dodger', int_rate: 'The ball-protector', pressure_rate: 'The quick processor',
  gvar_pg: 'The most valuable', ryoe: 'The elusive runner', rush_success: 'The steady runner', explosive: 'The home-run hitter', rush_epa: 'The efficient runner', stuff_rate: 'The tough runner', target_share: 'The go-to target',
  yptpa: 'The yardage machine', rec_epa_tgt: 'The efficient target', croe: 'The sure hands', yac_rec: 'The YAC threat', pressures_pg: 'The pass rusher', tfl_pg: 'The backfield wrecker', tackles_pg: 'The tackler',
  ff_pg: 'The strip specialist', pd_pg: 'The ball hawk', ints_pg: 'The ball hawk', splash_pg: 'The playmaker', fg_oe: 'The accurate kicker', fg_50_pct: 'The big leg', xp_pct: 'The steady kicker', fg_50: 'The big leg',
  epa_punt: 'The field flipper', net: 'The field flipper', gross: 'The big leg', inside20: 'The pin-it-deep punter', touchback_rate: 'The precise punter' };
const NUMW = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten'];
function lc(x) { return /^[A-Z][a-z]/.test(x) ? x.charAt(0).toLowerCase() + x.slice(1) : x; }
function plural(n, w) { return n + ' ' + w + (n === 1 ? '' : 's'); }

GI.route('player', function (el, params) {
  if ((params.query || {}).view === 'progression' && GI.progression) return GI.progression.tab(el, params);
  const pid = String(params.id || '');
  const S = Number(params.season);
  const cur = S === GI.currentSeason();
  return GI.loadAll(['players/' + pid + '.json', 'glossary.json'].concat(cur ? [GI.ypath('valuation.json', S)] : [])).then(res => {
    if (!el.isConnected) return;
    const c = GI.ok(res[0]) ? res[0] : null;
    META = {};
    ((res[1] || {}).groups || []).forEach(g => { if (/^Players/.test(g.name)) (g.entries || []).forEach(e => { if (!META[e.key]) META[e.key] = Object.assign({ family: g.name.replace(/^Players: /, '') }, e); }); });
    const info = GI.player(pid);
    if (!c) {
      el.innerHTML = GI.pageHead('Players', info.name || 'Player', [info.pos, info.team ? GI.teamName(info.team) : '', isNum(info.first) ? info.first + '–' + (info.last || '') : ''].filter(Boolean).map(esc).join(' · ')) +
        GI.notBuilt('The page for ' + (info.name || pid), res[0]) + GI.muted('Player pages are built for everyone who appears in a season catalogue since 1999. <a href="#/scout">The Scouting Room →</a>');
      return;
    }
    const now = c.current || {};
    const seasons = (c.seasons || []).map(flat).filter(r => isNum(r.season)).sort((a, b) => a.season - b.season);
    const last = seasons[seasons.length - 1] || {};
    const viewSeason = seasons.find(r => r.season === S) || last;
    const pos = c.pos || info.pos || '';
    const group = GI.groupOf(pos, c.group || last.group);
    const team = (cur ? (info.team || last.team) : viewSeason.team) || c.team || '';
    const vals = Object.assign({}, viewSeason, now.season === S || (cur && !viewSeason.season) ? now.values || {} : {});
    const pctS = now.season === S ? now : null;
    const valn = cur && GI.ok(res[2]) ? (() => { const cols = res[2].cols || []; const r = (res[2].rows || []).find(x => x[cols.indexOf('pid')] === pid); if (!r) return null; const o = {}; cols.forEach((k, i) => { o[k] = r[i]; }); return o; })() : null;
    const age = first(valn && valn.age, isNum(viewSeason.age) ? viewSeason.age : null);
    document.title = (c.name || pid) + ' · ' + GI.SITE;
    const dr = c.draft || {};
    const draftTxt = dr.year || dr.season ? (dr.round ? 'round ' + dr.round + (dr.pick ? ', pick ' + dr.pick : '') + ', ' : '') + (dr.year || dr.season) + (dr.team ? ' (' + dr.team + ')' : '') : '';
    const ht = isNum(c.height) && c.height > 50 ? Math.floor(c.height / 12) + '′' + (c.height % 12) + '″' : '';
    const peerRow = pctS ? { pos: pos, group: group, role: pctS.role, values: pctS.values || {}, pct: pctS.pct || {}, pct_pos: pctS.pct_pos || {}, pct_role: pctS.pct_role, games: viewSeason.games, qualified: viewSeason.qualified } : null;
    const g0 = GI.SP.groupOf(peerRow || { pos: pos, group: group }, pid, null);
    const tiles = (TILES[group] || []).map(t => { const key = GI.pickKey(vals, t[1]); return key && isNum(vals[key]) ? { label: t[0], key: key, v: vals[key], sub: t[2] } : null; }).filter(Boolean);
    const status = valn && valn.status && valn.status !== 'ACT' ? ({ RES: 'Injured reserve', DEV: 'Practice squad', INA: 'Inactive', FA: 'Free agent' }[valn.status] || valn.status) : '';
    const log = GI.listOf(now.log).slice().sort((a, b) => (a.week || 0) - (b.week || 0));
    const gpNow = isNum(viewSeason.games) ? Number(viewSeason.games) : (pctS ? log.length : 0);
    const sur = GI.surnameOf(c.name || '') || c.name || '';
    /* the role's name: from the roster position first, then (once the catalogue and value table are in) the spec's role */
    let peerShort = g0 ? g0.name.toLowerCase() : (GI.GROUP_NAME[group] || 'players').toLowerCase();
    const tags = [];
    if (pctS && viewSeason.qualified) tags.push(QK.tag('Qualified for percentiles', 'signal'));
    if (status) tags.push(QK.tag(status));

    /* "The short version": what this season's numbers say, in plain English (percentiles against the role's peers) */
    function lead() {
      const v = vals, gp = gpNow ? ' in ' + plural(gpNow, 'game') : '';
      const n = x => GI.int(x);
      if (group === 'QB' && isNum(v.pass_yds)) return sur + ' has thrown for ' + n(v.pass_yds) + ' yards and ' + plural(Number(v.pass_td) || 0, 'touchdown') + gp + '.';
      if (group === 'RB' && isNum(v.rush_yds)) return sur + ' has run for ' + n(v.rush_yds) + ' yards' + (isNum(v.carries) ? ' on ' + n(v.carries) + ' carries' : '') + gp + (isNum(v.rec_yds) && v.rec_yds > 0 ? ', with ' + n(v.rec_yds) + ' more through the air' : '') + '.';
      if ((group === 'WR' || group === 'TE') && isNum(v.rec_yds)) return sur + ' has ' + plural(Number(v.rec) || 0, 'catch').replace('catchs', 'catches') + ' for ' + n(v.rec_yds) + ' yards' + (isNum(v.rec_td) ? ' and ' + plural(Number(v.rec_td), 'touchdown') : '') + gp + '.';
      if (group === 'DEF' && isNum(v.tackles)) return sur + ' has ' + plural(Number(v.tackles), 'tackle') + (isNum(v.sacks) && v.sacks > 0 ? ' and ' + GI.num(v.sacks, v.sacks % 1 ? 1 : 0) + ' sack' + (v.sacks === 1 ? '' : 's') : '') + gp + '.';
      if (group === 'K' && isNum(v.fga)) return sur + ' has made ' + n(v.fgm) + ' of ' + plural(Number(v.fga), 'field-goal try').replace('trys', 'tries') + gp + '.';
      if (group === 'P' && isNum(v.punts)) return sur + ' has punted ' + plural(Number(v.punts), 'time') + (isNum(v.net) ? ', netting ' + GI.num(v.net, 1) + ' yards a punt' : '') + gp + '.';
      return gpNow ? sur + ' has played ' + plural(gpNow, 'game') + ' this season.' : '';
    }
    function shortText(rows) {
      let t = lead();
      const top = rows.filter(r => r[1] >= 90).sort((x, y) => y[1] - x[1]).slice(0, 2);
      const low = rows.slice().sort((x, y) => x[1] - y[1])[0];
      if (top.length) t += ' In the top ' + Math.max(1, Math.round(100 - Math.min(top[0][1], top[top.length - 1][1]))) + '% of ' + peerShort + ' for ' + top.map(r => lc(r[2])).join(' and ') + '.';
      else if (rows.length) { const avg = rows.reduce((x, r) => x + r[1], 0) / rows.length; t += avg >= 60 ? ' Above the middle of the pack on most of the numbers that matter.' : avg >= 40 ? ' Around the middle of the pack among ' + peerShort + '.' : ' Below the middle of the pack among ' + peerShort + ' so far.'; }
      if (low && low[1] <= 30 && !(top[0] && top[0][0] === low[0])) t += ' The weak spot: ' + lc(low[2]) + ' sits in the ' + QK.ordinal(Math.round(low[1])) + ' percentile.';
      if (gpNow && gpNow < 6) t += ' Early days, so read it lightly.';
      return t.trim();
    }
    const syncRows = g0 && peerRow ? GI.SP.headline(g0).map(m => { const p = GI.SP.pctSync(peerRow, g0, m[0]); return isNum(p) ? [m[0], p, m[1]] : null; }).filter(Boolean) : [];
    const short0 = pctS ? shortText(syncRows) : '';

    /* v4 (Broadcast): the full-bleed team-colour hero (the alternate colour on the diagonal, the outlined number or
       initials) with the black strip of five numbers and "The short version" under it */
    const tl = [];
    if (valn) tl.push(GI.kpi('Projected value', GI.num(valn.value, 0), 'points above replacement, this season and the next three · likely range ' + GI.num(valn.lo, 0) + '–' + GI.num(valn.hi, 0), { signal: true, tip: 'Our player-value model: projected points above a replacement player, discounted 10% a season; the range is the 10th to 90th percentile' }));
    tiles.slice(0, valn ? 4 : 5).forEach(t => tl.push(GI.kpi(t.label, fv(t.key, t.v), esc(t.sub), { pctl: GI.SP.pctSync(peerRow, g0, t.key), tip: (META[t.key] || {}).desc })));
    const hero = QK.playerHeader({ name: c.name, number: isNum(c.number) ? c.number : (isNum(c.jersey) ? c.jersey : null), pos: GI.posLong(pos) || pos, kicker: 'NFL · ' + (pctS ? S : (last.season || S)) + ' season' + (gpNow ? ' · ' + plural(gpNow, 'game') + ' in' : ''),
      team: team ? { name: GI.teamName(team), abbr: GI.teamAbbr(team), colour: GI.teamInfo(team).colour, alt: GI.teamInfo(team).alt, href: GI.teamHref(team, S) } : null,
      meta: [isNum(age) ? GI.num(age, 0) + ' years old' : null, ht ? ht + (c.weight ? ', ' + c.weight + ' lb' : '') : null, c.college ? c.college : null, draftTxt ? 'Drafted ' + draftTxt : null,
        seasons.length > 1 ? 'Seasons ' + seasons[0].season + '–' + last.season : null],
      strip: tl, tags: tags, short: short0 || null });
    const NL = {};   /* the next and the last game, for fillNext / fillLast after the first paint */
    const crumb = '<nav class="gi-crumb" aria-label="Breadcrumb"><a href="#/scout">Scouting Room</a><span aria-hidden="true">›</span>' + (team ? '<a href="' + esc(GI.teamHref(team, S)) + '">' + esc(GI.teamName(team)) + '</a><span aria-hidden="true">›</span>' : '') + esc(c.name || pid) + '</nav>';
    let h = crumb + (window.QPV ? window.QPV.tabsNav([['overview', 'Overview', GI.playerHref(pid, S)], ['progression', 'Progression', GI.playerHref(pid) + '?view=progression']], 'overview') : '') + hero;
    h += '<div class="gi-toolbar" style="margin-top:var(--sp-6)"><a class="qk-btn primary" href="' + GI.compareHref(pid) + '">Compare</a><a class="qk-btn" href="#/compare/progression/' + encodeURIComponent(pid) + '">Compare progression</a><a class="qk-btn" id="pp-all" href="' + GI.scoutHref(g0 ? g0.code : group, S) + '">All ' + esc(peerShort) + '</a></div>';
    if (group === 'OL') h += GI.note('Offensive linemen have no individual metrics in the public data. The team page carries the line\'s unit ratings.');

    /* How sure are we (filled once the metric spec's M50 samples are in) */
    const small = gpNow < 8;
    /* v4: "How sure are we?" is the explain strip under the meters: the sample, when the headline numbers settle at
       this workload (filled once the spec's M50 samples are in, #pp-settle) and what the ▼ means */
    const sampleWords = gpNow ? (small ? (gpNow <= 10 ? NUMW[gpNow] : gpNow) + ' game' + (gpNow === 1 ? ' is' : 's is') + ' a small sample.' : gpNow + ' games: the picture is settling.') : 'No games yet this season.';
    const settleNote = '<b>How sure are we?</b> ' + esc(sampleWords) + ' ' + (group === 'K' || group === 'P' ? 'Kicking and punting numbers are close to noise over a season: read them as a rough guide. ' : (small ? 'Football seasons are short, and rates swing a lot over a handful of games. ' : '')) +
      '<span id="pp-settle"></span>The ▼ on each meter is last season in the same role, where there was one: rows that sit on it are the steady part of the profile; the ones far from it are the ones to watch.';
    const sim = (c.similar || []).map(r => (Array.isArray(r) ? { pid: String(r[0]), name: r[1], team: r[2], s: r[3] } : { pid: String(r.pid), name: r.name, team: r.team, s: first(r.sim, r.score) }));
    const typeCard = sim.length ? '<article class="qk-card"><div class="qk-card-body"><div class="qk-kicker">Their type</div><h4 class="gi-h4">Plays most like</h4><ul class="gi-type">' +
      sim.slice(0, 4).map(r => '<li><span>' + GI.playerLink(r.pid, r.name) + (r.team ? ' <span class="qk-sub">' + esc(GI.teamAbbr(r.team)) + '</span>' : '') + '</span><a class="v" href="' + GI.compareHref(pid, r.pid) + '">Compare' + (isNum(r.s) ? ' · ' + GI.num(r.s, 0) + '% alike' : '') + '</a></li>').join('') + '</ul>' +
      '<div class="qk-aside" style="margin-top:10px">Closest matches on this season’s profile among <span class="gi-peer-name">' + esc(peerShort) + '</span>.</div></div></article>' : '';
    const gbgSpec = gameByGame(group, log);
    const gbg = gbgSpec ? GI.card(gbgSpec.title, gbgSpec.sub, GI.chartBox('pp-gbg', 260, gbgSpec.title)) : '';

    /* 1. the LED meters (7) with "How sure are we?" under them, beside the tale of the tape against the closest match
          (5; chips switch between the matches), as the concept */
    const tape = !!(pctS && g0 && sim.length);
    if (pctS && g0) {
      h += '<section class="qk-section gi-sec1"><div class="qk-g75"><div><div id="pp-pcard">' + GI.card('Percentiles: how the player ranks', 'Against ' + esc(g0.peer) + ', loading the peer group…', QK.skeleton('lines', 6)) + '</div>' +
        QK.explain(settleNote, { cls: 'gi-settle' }) + '</div>' +
        '<div class="gi-stack">' + (tape ? '<div><div id="pp-tape-h">' + QK.sectionHead({ kicker: 'Tale of the tape', title: esc(sur) + ' or …?', html: true }) + '</div><div class="qk-chips gi-pick" id="pp-tape-pick" role="group" aria-label="Compare with"></div><div id="pp-tape">' + QK.skeleton('lines', 6) + '</div><div id="pp-verd"></div></div>' : gbg + typeCard) + '</div></div></section>';
    } else {
      if (pctS && !g0 && group !== 'OL') h += GI.note('No comparison group for this position (' + esc(GI.posLong(pos) || pos) + '): percentiles are kept for QB, RB, WR, TE, the five defensive roles, K and P.');
    }
    /* 2. what to watch (the scoreboard bug and the match-up) beside the last game (the box score by quarter and the
          win-chance race from the game file) */
    h += nextLast();
    /* 3. the game log: every game this season, the best game highlighted */
    if (log.length) h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Game log', title: 'Every game this season', sub: '<span id="pp-log-sub">' + esc((now.season || S) + ', every game played.') + '</span>', html: true }) + GI.card('', '', '<div id="pp-log"></div>', { flush: true }) + '</section>';
    /* 4. game by game and their type (when the tape took the right column), or both when there is no rail */
    if ((tape || !(pctS && g0)) && (gbg || typeCard)) h += '<section class="qk-section"><div class="qk-gside"><div>' + gbg + '</div><div>' + typeCard + '</div></div></section>';
    // ── more on the player
    h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'More on the player', title: 'Value, peers and the long view', sub: 'How much the player is worth, where the player sits among <span class="gi-peer-name">' + esc(peerShort) + '</span>, and every season on file since 1999.', html: true }) + '<div id="pp-style"></div>';
    if (pctS && g0) h += GI.card('Among peers', '<span id="pp-dist-sub">Every qualified player in the same peer group (' + esc(g0.peer.replace(/^NFL /, '')) + ') this season; bars coloured by percentile</span>',
      '<div class="qk-seg" id="pp-dist-m" role="group" aria-label="Metric" style="margin-bottom:10px"></div>' + GI.chartBox('pp-dist', 250, 'Distribution of the peer group'));
    if (valn || cur) h += GI.grid((valn ? GI.card('Value', 'Projected points above a replacement player: rest of this season and the next three, discounted 10% a season · band 10th–90th percentile', '<div id="pp-val"></div>' + GI.chartBox('pp-valc', 220, 'Projected value by season'), { span: cur ? 7 : 12 }) : '') +
      (cur ? '<div class="qk-span-' + (valn ? 5 : 12) + '" id="pp-moves"></div>' : ''));
    h += '</section>';
    const ch = now.charts || {};
    h += '<div id="pp-pos"></div>';
    h += GI.card('Season by season', 'every season on file since 1999 · value is Gridiron Value; columns ending + are era-adjusted (100 = average for that season, 10 = one SD)', (seasons.length > 1 ? GI.chartBox('pp-car-c', 260, 'Value and EPA by season') : '') + '<div id="pp-car"></div>', { id: 'career' });
    if (now.ngs || now.ftn) h += GI.grid(GI.card('Next Gen Stats', 'via nflverse; informational, non-commercial use', factsTable(now.ngs, 'No Next Gen Stats this season (qualifying passers, rushers and receivers only).'), { span: 6 }) +
      GI.card('FTN charting', 'FTN Data via nflverse (CC BY-SA 4.0)', factsTable(now.ftn, 'No FTN charting this season.'), { span: 6 }));
    el.innerHTML = h;
    fillNext(); fillLast();

    /* next game (QK.previewCard) and last time out (the game card with the player's line) */
    function nextLast() {
      if (!cur || !team) return '';
      const idx = GI.index() || {};
      const T = GI.canonTeam(team);
      const games = [].concat(idx.live || [], idx.games || []).filter(x => x && (GI.canonTeam(x.home) === T || GI.canonTeam(x.away) === T));
      const nxt = games.filter(x => (GI.isPre(x) || GI.isLive(x)) && !GI.isStale(x)).sort((a, b) => String(a.kickoff).localeCompare(String(b.kickoff)))[0];
      const lastG = log.length ? log[log.length - 1] : null;
      if (!nxt && !lastG) return '';
      let out = '<section class="qk-section"><div class="qk-g2">';
      NL.nxt = nxt; NL.last = lastG;
      if (nxt) {
        const soon = GI.isLive(nxt) ? 'Live now' : (QK.fmt.relDay(nxt.kickoff) === 'Today' ? 'What to watch tonight' : 'What to watch next');
        out += '<div>' + QK.sectionHead({ kicker: soon, title: GI.teamShort(nxt.away) + ' at ' + GI.teamShort(nxt.home) }) + '<div id="pp-next">' + QK.skeleton('card', 1) + '</div></div>';
      }
      if (lastG) {
        const gm = [].concat(idx.recent || [], idx.games || []).filter(x => x && x.game_id === lastG.game_id && GI.isFinal(x))[0];
        NL.gm = gm || null;
        const L = lastG;
        const bits = group === 'QB' ? [isNum(L.p_att) ? L.p_cmp + ' of ' + L.p_att : '', isNum(L.p_yds) ? L.p_yds + ' yards' : '', isNum(L.p_td) ? plural(L.p_td, 'touchdown') : '', isNum(L.p_ints) && L.p_ints ? plural(L.p_ints, 'interception') : '', isNum(L.p_epa) ? GI.signed(L.p_epa, 1) + ' EPA passing' : '']
          : group === 'RB' ? [isNum(L.r_car) ? plural(L.r_car, 'carry').replace('carrys', 'carries') + ' for ' + L.r_yds + ' yards' : '', isNum(L.x_rec) && L.x_rec ? L.x_rec + ' catches for ' + L.x_yds : '', isNum(L.r_td) && L.r_td ? plural(L.r_td, 'rushing touchdown') : '']
          : group === 'WR' || group === 'TE' ? [isNum(L.x_tgt) ? L.x_rec + ' catches on ' + plural(L.x_tgt, 'target') : '', isNum(L.x_yds) ? L.x_yds + ' yards' : '', isNum(L.x_td) && L.x_td ? plural(L.x_td, 'touchdown') : '']
          : group === 'DEF' ? [isNum(L.d_tkl) ? plural(L.d_tkl, 'tackle') : '', isNum(L.d_sacks) && L.d_sacks ? GI.num(L.d_sacks, L.d_sacks % 1 ? 1 : 0) + (L.d_sacks === 1 ? ' sack' : ' sacks') : '', isNum(L.d_int) && L.d_int ? plural(L.d_int, 'interception') : '', isNum(L.d_pd) && L.d_pd ? plural(L.d_pd, 'pass') + ' defensed' : '']
          : group === 'K' ? [isNum(L.k_fga) ? L.k_fgm + ' of ' + L.k_fga + ' field goals' : '', isNum(L.k_xpa) ? L.k_xpm + ' of ' + L.k_xpa + ' extra points' : '']
          : group === 'P' ? [isNum(L.u_punts) ? plural(L.u_punts, 'punt') : '', isNum(L.u_net) ? GI.num(L.u_net, 1) + ' net average' : ''] : [];
        const line = bits.filter(Boolean).join(', ').replace('passs', 'passes');
        /* v4: the last game titled with the score ("DEN 17, SEA 14"), the box score by quarter with the team totals and
           the win-chance race from the game file; the index card until it loads */
        const where = ((GI.parseGameId(L.game_id) || {}).home === L.team ? 'v ' : 'at ') + GI.teamName(L.opp);
        out += '<div><div id="pp-last-h">' + QK.sectionHead({ kicker: 'Last game', title: gm && isNum(gm.hs) && isNum(gm.as) ? scoreTitle(gm) : esc(where), html: true, actions: '<a class="qk-more" href="' + esc(GI.gameHref(L.game_id)) + '">Game centre</a>' }) + '</div>' +
          '<article class="qk-card"><div class="qk-card-body"><div id="pp-box">' + (gm ? GI.gameCard(gm, { why: true, date: true, compact: true }) : '') + '</div>' +
          (line ? '<p style="margin:12px 0 0;color:var(--ink-2);font-size:15px"><b style="color:var(--ink-1)">' + esc(sur) + ':</b> ' + esc(line) + '.</p>' : '') + '<div id="pp-race"></div></div></article></div>';
      }
      return out + '</div></section>';
    }
    /* "DEN 17, SEA 14": the winner first (a tie in the home-away order) */
    function scoreTitle(x) {
      const a = [GI.teamAbbr(x.away), x.as], b = [GI.teamAbbr(x.home), x.hs], w = x.as > x.hs ? [a, b] : [b, a];
      return esc(w[0][0] + ' ' + w[0][1] + ', ' + w[1][0] + ' ' + w[1][1]) + (GI.isOT(x) ? ' (OT)' : '');
    }
    /* what to watch: the scoreboard bug with the bar and how the teams match up this season (season.json ratings) */
    function fillNext() {
      const nxt = NL.nxt;
      if (!nxt || !document.getElementById('pp-next')) return;
      GI.loadYear('season.json', GI.gameSeason(nxt.game_id) || S).then(sj => {
        const box = document.getElementById('pp-next');
        if (!box || !el.isConnected) return;
        const season = GI.ok(sj) ? sj : {};
        const rows = {};
        (season.standings || []).forEach(d => (d.teams || []).forEach(t => { rows[GI.canonTeam(t.team)] = t; }));
        const G = GI.qkGame(nxt, rows);
        G.league = GI.weekLabel(nxt.week, GI.gameSeason(nxt.game_id));
        const Rt = season.ratings || {}, ua = (Rt[nxt.away] || {}).values || {}, uh = (Rt[nxt.home] || {}).values || {};
        const fx = [];
        const add = (lab, a, b, f, low) => { if (isNum(a) && isNum(b)) fx.push({ label: lab, a: f(a), b: f(b), better: Math.abs(a - b) < 1e-9 ? null : ((a > b) !== !!low ? 'a' : 'b') }); };
        add('Team rating, points a game', ua.rating, uh.rating, v => GI.signed(v, 1));
        add('Offence rating', ua.off_rating, uh.off_rating, v => GI.signed(v, 1));
        add('Defence rating', ua.def_rating, uh.def_rating, v => GI.signed(v, 1));
        add('Pass offence, EPA a dropback', ua.off_pass_epa, uh.off_pass_epa, v => GI.signed(v, 2));
        const m = nxt.model || {};
        const extra = isNum(m.home_pts) && isNum(m.away_pts) ? 'Our projected score: ' + GI.teamAbbr(nxt.away) + ' ' + GI.num(m.away_pts, 0) + ', ' + GI.teamAbbr(nxt.home) + ' ' + GI.num(m.home_pts, 0) + '.' : '';
        box.innerHTML = QK.previewCard(G, { layout: 'bug', nick: t => t.name, factors: fx, factorsTitle: 'How they match up this season', noteExtra: esc(extra) });
      });
    }
    /* the last game: the score by quarter with the team totals (yards, EPA a play, turnovers) and the player's team's
       win chance through the game (our model, else nflfastR's), from the game file */
    function fillLast() {
      const L = NL.last;
      if (!L || !document.getElementById('pp-race')) return;
      GI.loadGame(L.game_id).then(d => {
        if (!GI.ok(d) || !el.isConnected) return;
        const x = Object.assign({}, d.card || {}, d);
        if (!x.home) { const pg = GI.parseGameId(L.game_id) || {}; x.home = pg.home; x.away = pg.away; }
        if (isNum(x.hs) && isNum(x.as)) GI.set('pp-last-h', QK.sectionHead({ kicker: 'Last game', title: scoreTitle(x), html: true, actions: '<a class="qk-more" href="' + esc(GI.gameHref(L.game_id)) + '">Game centre</a>' }));
        const qs = GI.ch.quartersOf(x);
        const bt = side => ((d.box || {})[side] || {}).team || {};
        if (qs.length) {
          const n = Math.max(4, qs.length), mine = GI.canonTeam(L.team);
          const row = (t, k, sd) => { const b = bt(sd); return '<tr' + (GI.canonTeam(t) === mine ? ' class="hl"' : '') + '><td>' + GI.mark(t, 'sm') + '</td>' + Array.apply(null, Array(n)).map((_, i) => '<td class="num">' + (qs[i] && isNum(qs[i][k]) ? qs[i][k] : '–') + '</td>').join('') +
            '<td class="num"><b>' + qs.reduce((s, r) => s + (Number(r[k]) || 0), 0) + '</b></td><td class="num">' + (isNum(b.yards) ? b.yards : '–') + '</td><td class="num">' + (isNum(b.epa_play) ? GI.signed(b.epa_play, 2) : '–') + '</td><td class="num">' + (isNum(b.turnovers) ? b.turnovers : '–') + '</td></tr>'; };
          GI.set('pp-box', '<div class="qk-table-wrap"><table class="qk-table dense"><thead><tr><th>Team</th>' + Array.apply(null, Array(n)).map((_, i) => '<th class="num">' + (i < 4 ? 'Q' + (i + 1) : 'OT') + '</th>').join('') +
            '<th class="num">Pts</th><th class="num">Yards</th><th class="num" data-tip="Expected points added a play: above zero beats an average play">EPA/play</th><th class="num">TO</th></tr></thead><tbody>' + row(x.away, 0, 'away') + row(x.home, 1, 'home') + '</tbody></table></div>');
        }
        const w = d.wp && d.wp.cols ? GI.colRows(d.wp) : [];
        const key = w.filter(r => isNum(r.wp_home_ours)).length > 10 ? 'wp_home_ours' : 'wp_home_nflfastr';
        const pts = w.filter(r => isNum(r[key]) && isNum(r.game_seconds_remaining));
        if (pts.length > 10) {
          const home = GI.canonTeam(L.team) === GI.canonTeam(x.home), me = GI.teamAbbr(L.team);
          const col = GI.tc(L.team);
          const data = pts.map(r => [Math.max(0, (3600 - Number(r.game_seconds_remaining)) / 60), 100 * (home ? Number(r[key]) : 1 - Number(r[key]))]);
          /* the model's last play is a few seconds before the end: close the line at the result (100, 0 or 50 on a tie) */
          if (GI.isFinal(x) && isNum(x.hs) && isNum(x.as)) {
            const my = home ? x.hs - x.as : x.as - x.hs, endMin = Math.max(60, data[data.length - 1][0]);
            data.push([endMin, my > 0 ? 100 : my < 0 ? 0 : 50]);
          }
          GI.set('pp-race', GI.chartBox('pp-race-c', 240, me + ' chance to win through the last game'));
          GI.ch.mount('pp-race-c', T => {
            const xa = QKC.axis(T, { type: 'value', min: 0, max: Math.max(60, Math.ceil(data[data.length - 1][0] / 15) * 15), interval: 15, split: false, line: true });
            const ya = QKC.axis(T, { min: 0, max: 100, interval: 25, fmt: v => v + '%' });
            const gB = 8 + QKC.nameAxis(xa, 'Minutes played', 'bottom'), gT = 14 + QKC.nameAxis(ya, me + ' chance to win (%)', 'side');
            return { grid: { left: 8, right: 64, top: gT, bottom: gB, containLabel: true }, xAxis: xa, yAxis: ya,
              tooltip: QKC.tooltip(T, { trigger: 'axis', formatter: ps => '<div>Minute ' + esc(GI.num(ps[0].value[0], 0)) + '</div>' + QKC.tipRow(col, me, GI.num(ps[0].value[1], 0) + '%') }),
              series: [{ type: 'line', name: me, step: 'end', showSymbol: false, data: data, lineStyle: { width: 3, color: col }, itemStyle: { color: col }, areaStyle: { color: QKC.hexA(col, 0.12), origin: 50 },
                markLine: { silent: true, symbol: 'none', lineStyle: { color: T.axis, type: [4, 4], width: 1 }, label: { show: false }, data: [{ yAxis: 50 }] },
                endLabel: { show: true, formatter: p => me + ' ' + Math.round(p.value[1]) + '%', color: T.ink1, fontFamily: T.fontDisplay, fontSize: 20 } }] };
          }, me + ' chance to win through the last game');
          document.getElementById('pp-race').insertAdjacentHTML('beforeend', '<p class="qk-caption">' + esc(me) + '’s chance to win after every play, from ' + (key === 'wp_home_ours' ? 'our win-probability model' : 'nflfastR’s published model') + '. Dashed: 50%.</p>');
        }
      });
    }

    // game by game
    if (gbgSpec && document.getElementById('pp-gbg')) drawGameByGame('pp-gbg', gbgSpec, log);

    // the rail, the short version, how sure, style, where the player sits and the compare: the season catalogue and
    // value table (after the first paint), the spec's group, metric set and peers (spec.js)
    if (pctS && g0) {
      GI.ch.none('pp-dist', 'Loading the peer group…');
      Promise.all([GI.loadAll([GI.ypath('players.json', S), GI.ypath('value.json', S)]), GI.SP.ready()]).then(all2 => {
        const res2 = all2[0];
        if (!el.isConnected) return;
        const cat = GI.catOf(res2[0]);
        if (!cat) { GI.set('pp-pcard', GI.card('Percentiles: how the player ranks', '', GI.muted('The season catalogue is not built yet.'))); GI.ch.none('pp-dist', 'The season catalogue is not built yet.'); return; }
        const cx = GI.SP.ctx(cat, GI.ok(res2[1]) ? res2[1] : null);
        const row = cat.players[pid] || peerRow;
        const g = GI.SP.groupOf(row, pid, cx) || g0;
        const qualified = row.qualified !== false;
        if (g !== g0) {
          peerShort = g.name.toLowerCase();
          const ab = document.getElementById('pp-all');
          if (ab) { ab.textContent = 'All ' + peerShort; ab.setAttribute('href', GI.scoutHref(g.code, S)); }
          el.querySelectorAll('.gi-peer-name').forEach(n => { n.textContent = peerShort; });
        }
        // last season's ring from the player file (careers.add_prev_pct): the pool the rail ranks in this season, so
        // QB, RB, K, P, WR and TE read prev_pct_pos (their pct / pct_pos pool), defenders prev_pct_role; prev_peer has
        // last season's games. Without them, last season's catalogue below.
        let prevPct = null, prevGp = null;
        const pp0 = /^(qb|rb|k|p|wr|te)$/.test(g.id) ? now.prev_pct_pos : now.prev_pct_role;
        if (pp0 && typeof pp0 === 'object' && Object.keys(pp0).length) { prevPct = pp0; prevGp = now.prev_peer && isNum(now.prev_peer.games) ? now.prev_peer.games : null; }
        const railRows = () => GI.SP.headline(g).map(m => { const v = GI.SP.value(row, pid, m, cx); const pv = prevPct && isNum(prevPct[m[0]]) ? Number(prevPct[m[0]]) : null;
          return { label: m[1] + (m[3] ? ' ↓' : ''), sub: SUB[m[0]] || '', pctl: GI.SP.pct(row, pid, g, m, cx), prev: pv, value: isNum(v) ? GI.SP.fmt(m, v, cx) : '—', tip: m[5] + ' ' + GI.SP.m50Text(m), early: GI.SP.early(row, m) }; });
        const rail = () => QK.pctRail({ kicker: 'How they stack up', title: 'Percentiles: how the player ranks', peer: g.peer + ', qualified', sample: [GI.SP.sample(row, g), 'qualified: ' + GI.SP.minLine(g)].filter(Boolean).join(' · '),
          groups: [{ label: '', rows: railRows() }], ringLabel: 'last season' + (isNum(prevGp) ? ' (' + plural(prevGp, 'game') + ')' : ''),
          note: (GI.SP.NOTE[g.id] ? GI.SP.NOTE[g.id] + ' ' : '') + '100 = best among peers; ↓ metrics are flipped so a high percentile is always good. A metric is marked early until the player\'s sample reaches the point where it is half signal (M50, our metrics study).',
          emptyText: qualified ? 'No percentiles for this group yet.' : 'Short of the qualifying minimum (' + GI.SP.minLine(g) + '): no percentiles yet.',
          foot: '<span>' + esc(S) + ' · the metric set from our metrics study</span><a href="' + GI.compareHref(pid) + '">Compare →</a>' });
        GI.set('pp-pcard', rail());
        // the short version, now with every percentile in the role's pool
        const full = GI.SP.headline(g).map(m => { const p = GI.SP.pct(row, pid, g, m, cx); return isNum(p) ? [m[0], p, m[1]] : null; }).filter(Boolean);
        const sv = el.querySelector('.qk-short p');
        if (sv && full.length) sv.textContent = shortText(full);
        // how sure: when the headline numbers settle at this workload (the spec's M50 samples, converted to games)
        const settle = GI.SP.headline(g).filter(m => isNum(m[7]) && m[8]).map(m => {
          const n = GI.SP.sampleIn(row, m[8]);
          if (m[8] === 'games') return [m[1], Math.round(m[7])];
          return isNum(n) && n > 0 && gpNow ? [m[1], Math.round(m[7] / (n / gpNow))] : null;
        }).filter(x => x && x[1] > 0 && x[1] < 200).slice(0, 3);
        if (settle.length) GI.set('pp-settle', 'At this workload, ' + settle.map(x => esc(lc(x[0])) + ' is half signal after about <b>' + plural(x[1], 'game') + '</b>').join('; ') + '. ');
        // playing style
        const st = GI.SP.style(g).map(m => { const v = GI.SP.value(row, pid, m, cx); const r = GI.SP.pct(row, pid, g, [m[0], m[1], m[2], 0, 0, m[5], m[6]], cx); return isNum(v) && isNum(r) ? { label: m[1], pctl: m[3] ? 100 - r : r, value: GI.SP.fmt(m, v, cx), tip: m[5] + ' ' + GI.SP.m50Text(m), style: true, early: GI.SP.early(row, m) } : null; }).filter(Boolean);
        GI.set('pp-style', st.length ? GI.card('Playing style', 'How the player plays, not how well: rank among peers from low to high, in neutral grey', QK.pctlBars(st)) : '');
        // last season's ring: the payload's prev_pct_pos / prev_pct_role when it has them, else (fallback) last season's
        // catalogue when the rail comes into view
        if (!prevPct) {
          const host = document.getElementById('pp-pcard');
          let fired = false;
          const go = () => {
            if (fired) return; fired = true;
            GI.loadAll([GI.ypath('players.json', S - 1), GI.ypath('value.json', S - 1)]).then(pr => {
              const pc = GI.catOf(pr[0]);
              if (!pc || !el.isConnected) return;
              const px = GI.SP.ctx(pc, GI.ok(pr[1]) ? pr[1] : null);
              const prow = pc.players[pid];
              const pg = prow ? GI.SP.groupOf(prow, pid, px) : null;
              if (!prow || !pg || pg.id !== g.id || prow.qualified === false) return;
              const o = {};
              GI.SP.headline(g).forEach(m => { const p = GI.SP.pct(prow, pid, pg, m, px); if (isNum(p)) o[m[0]] = p; });
              if (!Object.keys(o).length) return;
              prevPct = o; prevGp = isNum(prow.games) ? prow.games : null;
              GI.set('pp-pcard', rail());
            });
          };
          if (host && window.IntersectionObserver) { const io = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) { io.disconnect(); go(); } }, { rootMargin: '200px' }); io.observe(host); GI.onLeave(() => io.disconnect()); } else go();
        }
        /* the tale of the tape: the player against one of the closest matches in the same role (chips switch), on the
           role's metric set; the better number in each row solid, verdicts under it */
        const others = sim.map(r => r.pid).filter(id => id !== pid && cat.players[id] && GI.SP.groupOf(cat.players[id], id, cx) && GI.SP.groupOf(cat.players[id], id, cx).id === g.id).slice(0, 3);
        if (document.getElementById('pp-tape')) {
          if (!others.length) {
            GI.set('pp-tape-h', QK.sectionHead({ kicker: 'Tale of the tape', title: 'Pick a match-up' }));
            GI.set('pp-tape', QK.empty('No close match in the role yet', 'The closest matches appear once they qualify in the same role.') + '<p style="margin:12px 0 0"><a class="qk-more" href="' + esc(GI.compareHref(pid)) + '">Pick a player to compare</a></p>');
          } else {
            const drawTape = oid => {
              const E = [pid, oid].map(id => ({ id: id, p: cat.players[id] }));
              const best = {};
              const rowsC = GI.SP.headline(g).filter(m => E.some(e => isNum(GI.SP.value(e.p, e.id, m, cx)))).map(m => {
                const pcs = E.map(e => GI.SP.pct(e.p, e.id, g, m, cx));
                pcs.forEach((v, i) => { const o = pcs[1 - i]; const d = isNum(v) ? v - (isNum(o) ? o : 0) : null; if (isNum(d) && (!best[i] || d > best[i].d)) best[i] = { m: m, d: d, v: GI.SP.value(E[i].p, E[i].id, m, cx) }; });
                return { label: m[1] + (m[3] ? ' ↓' : ''), tip: m[5], better: m[3] ? 'low' : 'high', values: E.map(e => GI.SP.value(e.p, e.id, m, cx)), pctls: pcs, fmt: v => GI.SP.fmt(m, v, cx) };
              });
              const names = E.map(e => GI.surnameOf(e.p.name || '') || e.p.name);
              GI.set('pp-tape-h', QK.sectionHead({ kicker: 'Tale of the tape', title: names[0] + ' or ' + names[1] + '?',
                sub: 'Bar length = percentile against ' + g.peer + ' (100 = best; ↓ metrics flipped). The better number in each row is solid.' }));
              const ents = E.map((e, i) => ({ name: e.p.name || GI.playerName(e.id), short: names[i], href: GI.playerHref(e.id, S), colour: GI.teamInfo(e.p.team).colour, alt: GI.teamInfo(e.p.team).alt,
                sub: [GI.teamName(e.p.team), GI.SP.sample(e.p, g)].filter(Boolean).join(' · ') }));
              GI.set('pp-tape', QK.compareView({ entities: ents, groups: [{ label: '', rows: rowsC }] }));
              const verd = E.map((e, i) => best[i] && best[i].d > 0 ? { title: ARCHETYPE[best[i].m[0]] || 'The standout', who: names[i], text: 'the better of the two on ' + lc(best[i].m[1]) + ' (' + GI.SP.fmt(best[i].m, best[i].v, cx) + ').' } : null);
              GI.set('pp-verd', QK.verdicts(verd));
            };
            const pick = el.querySelector('#pp-tape-pick');
            if (pick) {
              pick.innerHTML = others.map((id, i) => '<button type="button" class="qk-chip" data-value="' + esc(id) + '" aria-pressed="' + (i === 0) + '">' + esc(GI.surnameOf(cat.players[id].name || '') || cat.players[id].name || id) + '</button>').join('') +
                (others.length > 1 ? '<a class="qk-chip" href="' + esc(GI.compareHref(pid, others[0], others[1])) + '">All three in Compare</a>' : '<a class="qk-chip" href="' + esc(GI.compareHref(pid)) + '">Pick a player</a>');
              pick.querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
                pick.querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', x === b ? 'true' : 'false'));
                drawTape(b.getAttribute('data-value'));
              }));
            }
            drawTape(others[0]);
          }
        }
        // where the player sits among peers
        const peers = GI.SP.members(cx, g.id).filter(id => cat.players[id].qualified !== false);
        GI.set('pp-dist-sub', 'Every qualified player in the same peer group (' + esc(g.peer.replace(/^NFL /, '')) + ') this season; bars coloured by percentile');
        const keys = GI.SP.headline(g).filter(m => isNum(GI.SP.value(row, pid, m, cx))).slice(0, 4);
        const segEl = el.querySelector('#pp-dist-m');
        if (!keys.length || !segEl) { GI.ch.none('pp-dist', 'No metric to place this player on yet.'); return; }
        if (!ST.dist || !keys.some(m => m[0] === ST.dist)) ST.dist = keys[0][0];
        segEl.innerHTML = keys.map(m => '<button type="button" aria-pressed="' + (m[0] === ST.dist) + '" data-value="' + esc(m[0]) + '">' + esc(GI.shortLabel(m[1])) + '</button>').join('');
        const drawDist = key => {
          ST.dist = key;
          const m = g.m.find(x => x[0] === key);
          const vs = peers.map(id => GI.SP.value(cat.players[id], id, m, cx)).filter(isNum).sort((a, b) => a - b);
          const mine = GI.SP.value(row, pid, m, cx);
          if (vs.length < 5) { GI.ch.none('pp-dist', 'Too few qualified peers yet.'); return; }
          const med = vs[Math.floor(vs.length / 2)];
          const n = document.getElementById('pp-dist');
          if (!n) return;
          n.classList.remove('gi-chart-empty'); n.innerHTML = '';
          const c2 = QKC.distribution(n, { values: vs, binCount: 22, lowerBetter: !!m[3], fmt: v => GI.SP.fmt(m, v, cx), xName: m[1] + ' · ' + vs.length + ' qualified ' + g.peer.replace(/^NFL /, ''), yName: 'Players',
            marks: (isNum(mine) ? [{ x: mine, label: GI.surnameOf(c.name) }] : []).concat([{ x: med, label: 'Median' }]), label: 'Distribution of ' + m[1] });
          if (c2) GI.onLeave(() => { try { c2.dispose(); } catch (e) { /* gone */ } });
        };
        drawDist(ST.dist);
        QK.seg(segEl, drawDist);
      });
    }
    if (cur && GI.MV) GI.MV.load().then(md => { const host = document.getElementById('pp-moves'); if (host && el.isConnected) host.innerHTML = GI.MV.playerCard(md, pid); });
    // value
    if (valn) {
      GI.set('pp-val', GI.kpis([isNum(valn.wins) ? GI.kpi('Wins', GI.signed(valn.wins, 2), 'the projected value in wins', { signal: true }) : '',
        isNum(valn.now_pg) ? GI.kpi('This season, per game', GI.signed(valn.now_pg, 2), 'points above replacement') : '', isNum(valn.lvl) ? GI.kpi('Level now', GI.signed(valn.lvl, 2), 'per game, this season\'s form') : '']));
      const seasonsV = (res[2].seasons || []).slice(0, (valn.proj || []).length);
      if ((valn.proj || []).length) GI.ch.bar('pp-valc', { cats: seasonsV.map(String), series: [{ name: 'Per game', data: valn.proj }, { name: 'Expected games', data: valn.games || [] }], legend: true, fmt: v => GI.num(v, 1), catName: 'Season', valName: 'Value per game; games', label: 'Projected value per game and games by season' });
    }
    // position panels
    const pp = [];
    if (group === 'QB' && Array.isArray(ch.qb_grid) && ch.qb_grid.length) pp.push(GI.card('Pass grid', 'throws by depth and direction (from the quarterback\'s view) · ' + (now.season || S), '<div class="gi-toolbar" style="margin-bottom:8px">' + GI.seg('pg-m', [['epa', 'EPA per attempt'], ['cmp_pct', 'Completion %'], ['att', 'Attempts']], ST.grid, 'Measure') + '</div>' + GI.chartBox('pp-grid', 300, 'Pass grid'), { span: 6 }));
    if (group === 'RB' && Array.isArray(ch.ryoe_by_game) && ch.ryoe_by_game.length) pp.push(GI.card('Rush yards over expected', 'by game · total and per carry', GI.chartBox('pp-ryoe', 280, 'RYOE by game'), { span: 6 }));
    if (Array.isArray(ch.depth_profile) && ch.depth_profile.length) pp.push(GI.card('Depth profile', 'targets by depth, with EPA per target', GI.chartBox('pp-depth', 280, 'Targets by depth'), { span: 6 }));
    if (group === 'K' && Array.isArray(ch.fg) && ch.fg.length) pp.push(GI.card('Field goals by distance', 'made against our expected makes', GI.chartBox('pp-fg', 280, 'Field goals by distance'), { span: 12 }));
    if (Array.isArray(ch.splash_by_game) && ch.splash_by_game.length) pp.push(GI.card('Splash plays by game', 'sacks, QB hits and passes defensed', GI.chartBox('pp-splash', 280, 'Splash plays by game'), { span: 12 }));
    if (pp.length) GI.set('pp-pos', GI.grid(pp.join('')));
    if (document.getElementById('pp-grid')) {
      const drawG = () => {
        const m = ST.grid;
        const rows = ch.qb_grid.slice().sort((a, b) => dRank(a.depth) - dRank(b.depth)).map(r => ({ depth: dLabel(r.depth), loc: r.loc, value: r[m], n: r.att }));
        GI.ch.passGrid('pp-grid', rows, { fmt: m === 'epa' ? 'signed2' : m === 'cmp_pct' ? 'pct0' : 'int', scale: m === 'epa' ? 'div' : 'seq', center: m === 'epa' ? 0 : undefined, label: 'Pass grid' });
      };
      drawG();
      GI.wireSeg(el, 'pg-m', v => { ST.grid = v; drawG(); });
    }
    if (document.getElementById('pp-ryoe')) {
      const car = {};
      log.forEach(x => { car[x.week] = x.r_car; });
      const r = ch.ryoe_by_game.map(x => ({ w: x[0], t: x[1], n: car[x[0]] }));
      GI.ch.bar('pp-ryoe', { cats: r.map(x => 'W' + x.w), series: [{ name: 'RYOE (total)', data: r.map(x => x.t) }], diverging: true, labels: true, fmt: v => GI.signed(v, 1), catName: 'Week', valName: 'Rush yards over expected', label: 'RYOE by game' });
    }
    if (document.getElementById('pp-depth')) {
      const r = ch.depth_profile.slice().sort((a, b) => dRank(a.depth) - dRank(b.depth));
      GI.ch.mount('pp-depth', T => ({
        grid: { left: 8, right: 8, top: 44, bottom: 30, containLabel: true },
        legend: GI.ch.legend(T, { data: ['Targets', 'EPA per target'] }),
        xAxis: GI.ch.ax(T, { type: 'category', data: r.map(x => dLabel(x.depth)), split: false, line: true, name: 'Air yards', nameLocation: 'middle', nameGap: 26 }),
        yAxis: [GI.ch.ax(T, { name: 'Targets', nameAlign: 'left' }), Object.assign(GI.ch.ax(T, { name: 'EPA per target', nameAlign: 'right', fmt: v => GI.signed(v, 1), split: false }), { position: 'right' })],
        tooltip: GI.ch.tip(T, { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: ps => { const x = r[ps[0].dataIndex]; return GI.ch.thead(esc(dLabel(x.depth))) + GI.ch.trow(T.model, 'Targets', String(first(x.tgt, x.targets))) + GI.ch.trow(T.cat[1], 'EPA per target', GI.signed(x.epa, 2)) + (isNum(x.catch) ? GI.ch.trow(T.ink3, 'Caught', GI.pct(x.catch, 0)) : ''); } }),
        series: [{ type: 'bar', name: 'Targets', data: r.map(x => first(x.tgt, x.targets)), barMaxWidth: 36, itemStyle: { color: T.model } },
          { type: 'line', name: 'EPA per target', yAxisIndex: 1, data: r.map(x => x.epa), symbolSize: 8, lineStyle: { color: T.cat[1], width: 2 }, itemStyle: { color: T.cat[1] } }]
      }), 'Targets by depth');
    }
    if (document.getElementById('pp-fg')) {
      const b = ch.fg.filter(x => x.att);
      GI.ch.bar('pp-fg', { cats: b.map(x => x.lo + '–' + (x.hi >= 60 ? '' : x.hi) + ' yds'), series: [{ name: 'Made', data: b.map(x => x.made) }, { name: 'Expected', data: b.map(x => Math.round(x.exp * 10) / 10) }], legend: true, labels: true, fmt: v => GI.num(v, 1), catName: 'Kick distance', valName: 'Field goals' });
    }
    if (document.getElementById('pp-splash')) {
      const cols = ch.splash_cols || ['week', 'tackles', 'sacks', 'qb_hits', 'int_pd'];
      const rows = GI.colRows({ cols: cols, rows: ch.splash_by_game });
      GI.ch.bar('pp-splash', { cats: rows.map(x => 'W' + x.week), series: cols.slice(1).map(k => ({ name: label(k === 'int_pd' ? 'pd' : k).replace('PD', 'INT + PD'), data: rows.map(x => x[k]) })), stack: true, legend: true, fmt: v => GI.num(v, 1), catName: 'Week', valName: 'Plays' });
    }
    // career
    if (seasons.length) {
      const order = CAREER[group] || ['season', 'team', 'games', 'epa', 'value'];
      const cols = order.filter(k => seasons.some(r => r[k] !== undefined && r[k] !== null));
      const plus = [];
      seasons.forEach(r => Object.keys(r).forEach(k => { if (/^plus_/.test(k) && plus.indexOf(k) < 0) plus.push(k); }));
      const all = cols.concat(plus.slice(0, 6));
      GI.set('pp-car', GI.tableHTML(all.map(k => ({ label: label(k), align: /^(season|team)$/.test(k) ? null : 'right', title: (META[k] || {}).desc })),
        seasons.slice().reverse().map(r => all.map(k => (k === 'team' ? { html: r.team ? GI.teamChip(r.team, r.season) : '—', v: r.team } : k === 'season' ? { html: '<b>' + r.season + '</b>', v: r.season } : { html: fv(k, r[k]), v: r[k] }))), { sticky: true }));
      if (seasons.length > 1) GI.ch.mount('pp-car-c', T => ({
        grid: { left: 8, right: 8, top: 44, bottom: 30, containLabel: true },
        legend: GI.ch.legend(T, { data: ['Value', 'EPA'] }),
        xAxis: GI.ch.ax(T, { type: 'category', data: seasons.map(r => String(r.season)), split: false, line: true, name: 'Season', nameLocation: 'middle', nameGap: 26 }),
        yAxis: [GI.ch.ax(T, { name: 'Value', nameAlign: 'left' }), Object.assign(GI.ch.ax(T, { name: 'EPA', nameAlign: 'right', split: false }), { position: 'right' })],
        tooltip: GI.ch.tip(T, { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: ps => { const r = seasons[ps[0].dataIndex]; return GI.ch.thead(r.season + ' · ' + esc(GI.teamAbbr(r.team))) + GI.ch.trow(T.model, 'Value', GI.signed(r.value, 1)) + GI.ch.trow(T.cat[1], 'EPA', GI.signed(r.epa, 1)) + GI.ch.trow(T.ink3, 'Games', String(r.games || '—')); } }),
        series: [{ type: 'bar', name: 'Value', data: seasons.map(r => ({ value: r.value, itemStyle: { color: GI.ch.lift(GI.teamColour(r.team), T) } })), barMaxWidth: 26 },
          { type: 'line', name: 'EPA', yAxisIndex: 1, data: seasons.map(r => r.epa), symbolSize: 6, lineStyle: { color: T.cat[1], width: 2 }, itemStyle: { color: T.cat[1] } }]
      }), 'Value and EPA by season');
    } else GI.set('pp-car', GI.muted('No season lines on file yet.'));
    // game log
    if (log.length) {
      const lead = ['week', 'opp', 'game_id', 'team'];
      const keys = [];
      log.forEach(r => Object.keys(r).forEach(k => { if (lead.indexOf(k) < 0 && keys.indexOf(k) < 0 && isNum(r[k])) keys.push(k); }));
      /* v4: the best game (by the game-by-game measure: passing EPA, scrimmage or receiving yards, tackles ...) is the
         highlighted row; newest first */
      let bestI = -1, bestV = -1e9;
      if (gbgSpec) log.forEach((r, i) => { const v = gbgSpec.s.reduce((a2, x) => a2 + (isNum(r[x[0]]) ? Number(r[x[0]]) : 0), 0); if (v > bestV) { bestV = v; bestI = i; } });
      const bestR = bestI >= 0 && bestV > 0 && log.length >= 2 ? log[bestI] : null;
      if (bestR) GI.set('pp-log-sub', esc('Week ' + bestR.week + ' ' + ((GI.parseGameId(bestR.game_id) || {}).home === bestR.team ? 'against ' : 'at ') + GI.teamName(bestR.opp) + ' is the best game so far (highlighted): ' +
        (gbgSpec.signed ? GI.signed(bestV, 1) : GI.num(bestV, bestV % 1 ? 1 : 0)) + ' ' + lc(gbgSpec.y).replace(/ in the game$/, '') + '. Newest first.'));
      GI.set('pp-log', GI.tableHTML([{ label: 'Wk', align: 'right' }, { label: 'Opp' }].concat(keys.map(k => ({ label: label(k), align: 'right' }))),
        log.map((r, i) => { const g = GI.parseGameId(r.game_id) || {}; const at = r.team && g.home ? (r.team === g.home ? 'v ' : '@ ') : '';
          return { _class: bestR && i === bestI ? 'hl' : '', cells: [{ html: r.game_id ? '<a class="gi-link" href="' + GI.gameHref(r.game_id) + '">' + r.week + '</a>' : String(r.week), v: r.week }, { html: r.opp ? at + GI.teamChip(r.opp) : '—', v: r.opp }].concat(keys.map(k => ({ html: fv(k, r[k]), v: r[k] }))) }; }).reverse(), { sticky: true }));
    } else GI.set('pp-log', GI.muted('No games logged this season.'));
    GI.sortable(el);
  });
});

GI.playerLabel = label;
})(window.GI);
