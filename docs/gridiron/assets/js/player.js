/* The Quant Gridiron — the player page (#/player/<pid>), position-aware.
 *
 * Every player: a header (team, position, age, college, draft), position tiles, Savant-style
 * percentile sliders over the season catalogue (against the group or the exact position), the
 * season game log, the career from 1999 with a value-by-season chart, projections, NGS and FTN
 * panels where they exist, and similar players.
 *   QB    EPA per play, CPOE, air yards, time to throw, pressure and turnover-worthy plays; the pass
 *         grid by depth and location (attempts, completion %, EPA per attempt, CPOE).
 *   RB    RYOE (ours against NGS's) by game, success and explosive rates, receiving.
 *   WR/TE target share, aDOT, separation (NGS), YAC over expected, catch rate over expected, drops,
 *         contested catches; the depth profile of targets.
 *   K/P   field goals over expected by distance; punting.
 *   DEF   what the public data allows (pass rush, tackles, takeaways).
 *
 * Data: data/players/<pid>.json (PAYLOADS "Per player"), data/<S>/players.json (values and
 * percentiles), data/players_index.json. Uses GI.fk. */
(function (GI) {
'use strict';

const K = () => GI.fk;

// ── labels and formats for keys that are not in a catalogue ────────────────

const LABEL = {
  season: 'Season', team: 'Team', games: 'G', g: 'G', gs: 'GS', week: 'Wk', opp: 'Opp', opponent: 'Opp', result: 'Result', date: 'Date', home: 'Home', snaps: 'Snaps', snap_pct: 'Snap%',
  att: 'Att', cmp: 'Cmp', comp: 'Cmp', completions: 'Cmp', attempts: 'Att', pass_att: 'Att', pass_yds: 'Pass yds', passing_yards: 'Pass yds', pass_yards: 'Pass yds', yds: 'Yds', yards: 'Yds',
  pass_td: 'Pass TD', passing_tds: 'Pass TD', td: 'TD', tds: 'TD', int: 'INT', ints: 'INT', interceptions: 'INT', sacks: 'Sacks', sack: 'Sacks', sack_yds: 'Sack yds', dropbacks: 'Dropbacks', plays: 'Plays',
  rush_att: 'Car', carries: 'Car', rush_yds: 'Rush yds', rushing_yards: 'Rush yds', rush_td: 'Rush TD', rushing_tds: 'Rush TD', ypc: 'Y/C', ypa: 'Y/A', anya: 'ANY/A', any_a: 'ANY/A',
  targets: 'Tgt', tgt: 'Tgt', rec: 'Rec', receptions: 'Rec', rec_yds: 'Rec yds', receiving_yards: 'Rec yds', rec_td: 'Rec TD', receiving_tds: 'Rec TD', routes: 'Routes', yprr: 'YPRR',
  air_yards: 'Air yds', ay: 'Air yds', adot: 'aDOT', yac: 'YAC', yac_oe: 'YAC OE', xyac: 'xYAC', target_share: 'Tgt share', air_yards_share: 'Air share', wopr: 'WOPR', racr: 'RACR',
  epa: 'EPA', epa_total: 'EPA', epa_per_play: 'EPA/play', epa_play: 'EPA/play', epa_per_db: 'EPA/db', epa_per_att: 'EPA/att', epa_per_rush: 'EPA/rush', epa_per_target: 'EPA/tgt', pass_epa: 'Pass EPA', rush_epa: 'Rush EPA', rec_epa: 'Rec EPA',
  cpoe: 'CPOE', cp: 'xComp%', comp_pct: 'Comp%', cmp_pct: 'Comp%', success_rate: 'Success', success: 'Success', explosive_rate: 'Explosive', explosive: 'Explosive',
  ryoe: 'RYOE', ryoe_ours: 'RYOE (ours)', ryoe_ngs: 'RYOE (NGS)', ryoe_per_att: 'RYOE/att', ryoe_per_att_ngs: 'RYOE/att (NGS)', ryoe_ngs_per_att: 'RYOE/att (NGS)', ry: 'Rush yds', xry: 'xRush yds',
  time_to_throw: 'Time to throw', ttt: 'Time to throw', avg_time_to_throw: 'Time to throw', pressure_rate: 'Pressure%', pressures: 'Pressures', p2s: 'Pressure→sack', pressure_to_sack: 'Pressure→sack', sack_rate: 'Sack%',
  twp: 'TWP', twp_rate: 'TWP%', turnover_worthy: 'TWP', int_worthy: 'INT-worthy', btt: 'Big-time throws', scrambles: 'Scrambles', scramble_epa: 'Scramble EPA', pa_rate: 'Play action%', play_action: 'Play action%', pa_epa: 'PA EPA/db',
  separation: 'Separation', avg_separation: 'Separation', cushion: 'Cushion', avg_cushion: 'Cushion', croe: 'CROE', catch_rate_oe: 'CROE', catch_rate: 'Catch%', drops: 'Drops', drop_rate: 'Drop%', contested: 'Contested', contested_rate: 'Contested%', contested_catch_rate: 'Contested catch%',
  fga: 'FGA', fgm: 'FGM', fg_att: 'FGA', fg_made: 'FGM', fg_pct: 'FG%', fg_oe: 'FG OE', fgoe: 'FG OE', fg_exp: 'xFGM', xfgm: 'xFGM', xpa: 'XPA', xpm: 'XPM', xp_pct: 'XP%', long: 'Long', fg_long: 'Long',
  punts: 'Punts', punt_avg: 'Gross', gross_avg: 'Gross', net_avg: 'Net', punt_net: 'Net', inside20: 'Inside 20', touchbacks: 'TB', epa_per_punt: 'EPA/punt',
  tackles: 'Tkl', solo: 'Solo', tfl: 'TFL', qb_hits: 'QB hits', pbu: 'PBU', pass_def: 'PD', ff: 'FF', fr: 'FR', def_int: 'INT', missed_tackles: 'Missed', missed_tackle_rate: 'Missed tkl%',
  value: 'Value', gv: 'Gridiron Value', value_per_play: 'Value/play', war: 'WAR', qbr: 'QBR', fantasy: 'Fantasy', fpts: 'Fantasy pts', age: 'Age',
  p10: '10th pct', p50: 'Median', p90: '90th pct', mean: 'Mean', proj: 'Projection',
  p_cmp: 'Cmp', p_att: 'Att', p_yds: 'Pass yds', p_td: 'Pass TD', p_ints: 'INT', p_sacks: 'Sacked', p_db: 'Dropbacks', p_epa: 'Pass EPA', p_epa_db: 'EPA/db',
  r_car: 'Car', r_yds: 'Rush yds', r_td: 'Rush TD', r_epa: 'Rush EPA', r_ryoe: 'RYOE', x_tgt: 'Tgt', x_rec: 'Rec', x_yds: 'Rec yds', x_td: 'Rec TD', x_epa: 'Rec EPA', x_air: 'Air yds',
  epa_db: 'EPA/db', composite: 'Composite', anya: 'ANY/A', rush_epa: 'EPA/carry', rec_epa: 'Rec EPA', rec_epa_tgt: 'EPA/tgt', yacoe: 'YACOE', pts_oe: 'Pts OE', fg_50: '50+ made', gross: 'Gross', net: 'Net', epa_punt: 'EPA/punt', pd: 'PD', def_value: 'Splash EPA',
  avg_time_to_throw: 'Time to throw', avg_completed_air_yards: 'Completed air yds', avg_intended_air_yards: 'Intended air yds', avg_air_yards_differential: 'Air yds differential', aggressiveness: 'Aggressiveness (tight windows)',
  max_completed_air_distance: 'Longest completed air distance', avg_air_yards_to_sticks: 'Air yds to the sticks', completion_percentage_above_expectation: 'CPOE (NGS)', expected_completion_percentage: 'Expected comp%', passer_rating: 'Passer rating',
  efficiency: 'Efficiency (distance per rush yd)', percent_attempts_gte_eight_defenders: '8+ in the box', avg_time_to_los: 'Time to the line', expected_rush_yards: 'Expected rush yds', rush_yards_over_expected: 'RYOE (NGS)',
  rush_yards_over_expected_per_att: 'RYOE / carry (NGS)', rush_pct_over_expected: 'Rushes over expected', avg_cushion: 'Cushion', percent_share_of_intended_air_yards: 'Share of team air yds', catch_percentage: 'Catch %', avg_yac: 'YAC', avg_expected_yac: 'Expected YAC', avg_yac_above_expectation: 'YAC over expected (NGS)',
  play_action: 'Play action', screen: 'Screens', out_of_pocket: 'Out of pocket', interception_worthy: 'INT-worthy throws', throw_aways: 'Throwaways', blitzed: 'Blitzed', catchable: 'Catchable targets', created: 'Created receptions', screens: 'Screens'
};
function label(k, meta) { if (/^plus_/.test(k)) return label(k.slice(5), meta) + '+'; if (meta && meta[k] && meta[k].label) return meta[k].label; return LABEL[k] || LABEL[String(k).toLowerCase()] || K().titleCase(String(k).replace(/_pct$/, ' %').replace(/_oe$/, ' OE').replace(/_per_/, '/')); }
function guessFmt(k, v, meta) {
  if (meta && meta[k] && meta[k].fmt) return meta[k].fmt;
  const key = String(k).toLowerCase(), isNum = K().isNum;
  if (!isNum(v)) return '';
  if (/^(season|week|wk|g|gs|games|age)$/.test(key)) return key === 'age' ? '0' : 'int';
  if (/^plus_/.test(key)) return '0';
  if (/^(p|r|x)_(epa|ryoe)$/.test(key)) return 'signed1';
  if (/^cpoe$/.test(key)) return 'signed1';
  if (/^(croe|catch_rate_oe)$/.test(key)) return Math.abs(v) < 0.5 ? 'pp' : 'signed1';
  if (/epa.*(per|play|_db|_att|rush|tgt|target|punt|dropback)|^epa_play/.test(key)) return 'signed3';
  if (/epa|value|^gv$|war|_oe$|^ryoe$|^ryoe_(ours|ngs)$|over_exp/.test(key)) return Math.abs(v) < 3 && /per|_att|rate/.test(key) ? 'signed2' : (Math.abs(v) < 1 ? 'signed3' : 'signed1');
  if (/ryoe.*att|per_att$|yprr|ypc|ypa|any_?a|adot|air_yards_per|separation|cushion|avg|net|gross|yds_per/.test(key)) return /ryoe/.test(key) ? 'signed2' : '1';
  if (/time_to_throw|^ttt$|time_to_los/.test(key)) return 'sec';
  if (/^(percent_|catch_percentage$|expected_completion_percentage$|completion_percentage_above)/.test(key)) return Math.abs(v) > 1.5 ? (/above/.test(key) ? 'signed1' : '1') : 'pct';
  if (/^(p|r|x)_(cmp|att|yds|td|ints|sacks|db|car|tgt|rec|air)$/.test(key)) return 'int';
  if (/^(aggressiveness|rush_pct_over_expected)$/.test(key)) return Math.abs(v) > 1.5 ? '1' : 'pct';
  if (/^(play_action|screen|out_of_pocket|blitzed)$/.test(key)) return 'pct';
  if (/rate$|pct$|_pct|share|^p_|prob|^success$|^explosive$|wopr/.test(key)) return Math.abs(v) <= 1.5 ? 'pct' : '1';
  if (Number.isInteger(Number(v))) return 'int';
  return Math.abs(v) < 1 ? '3' : '1';
}
function fv(k, v, meta) { return K().fmtV(v, guessFmt(k, v, meta)); }

// ── position kits ──────────────────────────────────────────────────────────

/* Tiles: [label, candidate keys, fmt (blank: guessed), sub]. Values from the catalogue first, then current, then the last season row. */
const TILES = {
  QB: [['QB composite', ['composite'], '1', '100 = average, 10 = one SD'], ['EPA per dropback', ['epa_db', 'epa_per_db', 'epa_per_play', 'epa_play', /^epa_per/], 'signed3', 'passes, sacks and scrambles'], ['CPOE', ['cpoe', /cpoe/], 'signed1', 'completion % over expected (pp)'],
    ['Gridiron Value', ['value', 'gv'], 'signed1', 'EPA credited, adjusted'], ['aDOT', ['adot', /adot|air_yards_per_att/], '1', 'air yards per attempt'], ['Time to throw', ['ttt', 'time_to_throw', /time_to_throw/], 'sec', 'NGS'],
    ['Turnover-worthy', ['twp_rate', /twp|turnover_worthy|int_worthy/], 'pct', 'FTN, per attempt']],
  RB: [['RYOE per carry', ['ryoe', 'ryoe_per_att', /ryoe.*att/], 'signed2', 'ours (NGS when ours is not ready)'], ['RYOE (NGS)', ['ryoe_ngs', 'ryoe_per_att_ngs', 'ryoe_ngs_per_att', /ryoe.*ngs/], 'signed2', 'Next Gen Stats'], ['EPA per carry', ['rush_epa', 'epa_per_rush'], 'signed3', 'designed runs'],
    ['Success rate', ['rush_success', 'success_rate', /success/], 'pct', 'carries with positive EPA'], ['Explosive rate', ['explosive', 'explosive_rate'], 'pct', '10+ yard carries'], ['Target share', ['target_share'], 'pct', 'receiving role'], ['Gridiron Value', ['value', 'gv'], 'signed1', 'rushing and receiving']],
  WR: [['Target share', ['target_share', /target_share|tgt_share/], 'pct', 'of team attempts in his games'], ['EPA per target', ['rec_epa_tgt', 'epa_per_target'], 'signed3', ''], ['aDOT', ['adot'], '1', 'average depth of target'], ['Separation', ['separation', 'avg_separation'], '1', 'yards, NGS'],
    ['YAC over expected', ['yacoe', 'yac_oe', /yac_?oe|yacoe/], 'signed2', 'per reception'], ['Catch rate OE', ['croe', 'catch_rate_oe'], 'pct', 'over expected, per target'], ['Drop rate', ['drop_rate'], 'pct', 'FTN, per catchable target'], ['Gridiron Value', ['value', 'gv'], 'signed1', 'receiving EPA credited']],
  K: [['FG over expected', ['fg_oe', 'fgoe', /fg_?oe/], 'signed2', 'makes above our model'], ['Points over expected', ['pts_oe'], 'signed1', 'field goals and extra points'], ['FG%', ['fg_pct'], 'pct', ''], ['50+ yards', ['fg_50_pct'], 'pct', 'made per attempt'], ['XP%', ['xp_pct'], 'pct', 'extra points'], ['Average attempt', ['avg_dist'], '1', 'yards']],
  P: [['EPA per punt', ['epa_punt', 'epa_per_punt'], 'signed3', 'for the punting team'], ['Net average', ['net', 'net_avg', 'punt_net'], '1', 'yards'], ['Gross average', ['gross', 'gross_avg', 'punt_avg'], '1', 'yards'], ['Inside the 20', ['inside20'], 'pct', 'of punts'], ['Touchback rate', ['touchback_rate'], 'pct', '']],
  DEF: [['Splash EPA', ['def_value'], 'signed1', 'EPA prevented on his credited plays'], ['Splash plays / game', ['splash_pg'], '2', ''], ['Sacks', ['sacks'], '1', ''], ['Sacks + hits / game', ['pressures_pg'], '2', ''], ['Interceptions', ['ints', 'def_int'], 'int', ''], ['Passes defensed', ['pd', 'pbu', 'pass_def'], 'int', '']]
};
TILES.TE = TILES.WR;

/* Career columns per group, in order; anything else numeric is appended up to a cap. */
const CAREER = {
  QB: ['season', 'team', 'games', 'cmp', 'att', 'pass_yds', 'passing_yards', 'pass_td', 'passing_tds', 'int', 'interceptions', 'sacks', 'any_a', 'anya', 'cpoe', 'adot', 'epa_per_play', 'epa_play', 'epa', 'success_rate', 'rush_yds', 'rushing_yards', 'qbr', 'value'],
  RB: ['season', 'team', 'games', 'carries', 'rush_att', 'rush_yds', 'rushing_yards', 'ypc', 'rush_td', 'rushing_tds', 'ryoe', 'ryoe_per_att', 'ryoe_ngs', 'success_rate', 'explosive_rate', 'targets', 'rec', 'receptions', 'rec_yds', 'receiving_yards', 'epa', 'value'],
  WR: ['season', 'team', 'games', 'targets', 'rec', 'receptions', 'rec_yds', 'receiving_yards', 'rec_td', 'receiving_tds', 'target_share', 'air_yards_share', 'adot', 'yprr', 'separation', 'yac_oe', 'croe', 'drops', 'epa', 'value'],
  K: ['season', 'team', 'games', 'fgm', 'fga', 'fg_made', 'fg_att', 'fg_pct', 'fg_long', 'long', 'fg_oe', 'xpm', 'xpa', 'xp_pct', 'value'],
  P: ['season', 'team', 'games', 'punts', 'gross_avg', 'punt_avg', 'net_avg', 'inside20', 'touchbacks', 'epa_per_punt', 'value'],
  DEF: ['season', 'team', 'games', 'snaps', 'tackles', 'solo', 'tfl', 'sacks', 'qb_hits', 'pressures', 'def_int', 'int', 'pbu', 'pass_def', 'ff', 'fr', 'value']
};
CAREER.TE = CAREER.WR;

// ── page ───────────────────────────────────────────────────────────────────

const ST = { basis: 'pct', grid: 'epa', gridDepth: null };

function render(el, params, state) {
  const k = K();
  const pid = String(params.id || (params.rest || [])[0] || '');
  el.innerHTML = k.muted('Loading…');
  if (!pid) { el.innerHTML = k.card('Player', '', k.muted('No player id. Find one on the <a href="#/players">players</a> page or with the search box.')); return; }
  return k.ready().then(() => {
    const S = k.S(params, state);
    return Promise.all([GI.load('players/' + pid + '.json'), k.loadY(S, 'players.json'), k.loadNames()]).then(res => ({ S: S, res: res }));
  }).then(o => {
    if (!k.alive(el)) return;
    const S = o.S, career = (o.res[0] && o.res[0].ok !== false) ? o.res[0] : null, cat = k.catOf(o.res[1]);
    if (cat) k.learnCat(cat);
    const cp = cat && cat.players[pid] ? cat.players[pid] : null;
    const info = k.NAMES[pid] || {};
    if (!career && !cp) {
      el.innerHTML = k.card('Player', '', k.notBuilt('The page for ' + (info.name || pid), o.res[0]) + '<div class="pg-note gq-note">' + (info.name ? k.esc(info.name) + (info.pos ? ', ' + k.esc(info.pos) : '') + (info.first ? ', ' + k.esc(info.first) + '–' + k.esc(info.last || '') : '') + '. ' : '') + 'Player pages are built for everyone who appears in a season catalogue. <a href="#/players">All players →</a></div>');
      return;
    }
    const c = career || {}, cur = c.current || {};
    const name = c.name || (cp && cp.name) || info.name || pid;
    k.learn(pid, { name: name, pos: c.pos || (cp && cp.pos) });
    const pos = c.pos || (cp && cp.pos) || info.pos || '';
    const group = k.groupOf(pos, (cp && cp.group) || c.group);
    const seasons = (c.seasons || []).map(flat).filter(r => r && k.isNum(r.season));
    const last = seasons.length ? seasons.slice().sort((a, b) => b.season - a.season)[0] : {};
    const team = (cp && cp.team) || c.team || last.team || info.team || '';
    const age = k.first(cp && cp.age, c.age, ageOf(c.birth_date || c.dob));
    const metrics = cat ? k.metricsFor(cat, group) : [];
    const meta = k.metaOf(metrics);
    const vals = Object.assign({}, flat(last), cur.values || {}, (cp && cp.values) || {});
    const ctx = { pid: pid, S: S, name: name, pos: pos, group: group, team: team, career: c, cur: cur, cp: cp, cat: cat, metrics: metrics, meta: meta, vals: vals, seasons: seasons };

    // header
    const dr = c.draft || {};
    const draftTxt = dr && (dr.season || dr.year) ? (dr.round ? 'Round ' + dr.round + (dr.pick ? ', pick ' + dr.pick : '') + ', ' : '') + (dr.season || dr.year) + (dr.team ? ' (' + k.esc(dr.team) + ')' : '') : (dr.undrafted ? 'Undrafted' : '');   // no draft shown before 2008 (those slots are PFR's) or when unknown
    const yrs = seasons.length ? seasons[0].season + '–' + seasons[seasons.length - 1].season : (info.first ? info.first + '–' + (info.last || '') : '');
    const sub = [pos ? '<span class="chip">' + k.esc(pos) + '</span>' : '', team ? k.teamChip(team, S) + ' <span>' + k.esc(k.teamName(team)) + '</span>' : '', k.isNum(age) ? '<span>Age ' + k.num(age, 0) + '</span>' : '',
      c.college ? '<span>' + k.esc(c.college) + '</span>' : '', draftTxt ? '<span>Draft: ' + draftTxt + '</span>' : '', yrs ? '<span class="muted-inline">' + k.esc(yrs) + '</span>' : '',
      c.height || c.weight ? '<span class="muted-inline">' + [c.height ? k.esc(fmtHeight(c.height)) : '', c.weight ? k.esc(c.weight) + ' lb' : ''].filter(Boolean).join(', ') + '</span>' : ''].filter(Boolean).join(' ');
    const links = ['<a href="' + k.compareHref(pid, '') + '">Compare →</a>', team ? '<a href="' + k.teamHref(team, S) + '">' + k.esc(k.teamNick(team)) + ' →</a>' : '', '<a href="' + k.withQ('#/players', S, { g: group }) + '">All ' + k.esc((k.GROUP_NAME[group] || 'players').toLowerCase()) + ' →</a>'].filter(Boolean).join('');
    let h = k.head(k.esc(name), sub, links, k.esc(pos || '?'), team ? k.teamColour(team) : null);

    // tiles
    const tl = (TILES[group] || []).map(t => {
      const key = k.pick(vals, t[1]);
      const v = key ? vals[key] : null;
      if (!k.isNum(v)) return '';
      const pc = cp && key ? ((ST.basis === 'pct_pos' ? cp.pct_pos : cp.pct) || {})[key] : null;
      return k.tile(t[0], k.fmtV(v, t[2] || guessFmt(key, v, meta)), (k.isNum(pc) ? k.pill(pc) + ' ' : '') + k.esc(t[3] || ''));
    }).filter(Boolean);
    if (tl.length) h += k.tiles(tl);
    if (group === 'OL') h += k.card('Offensive line', '', k.muted('Offensive linemen have no individual metrics in the public data: pass-block and run-block charting is not published. The team page carries the line\'s unit ratings.'));

    // percentiles
    if (cp && metrics.length) {
      h += '<div class="card"><div class="card-header">Percentiles <span class="card-sub">' + S + ' · against every qualified ' + k.esc(k.GROUP_ONE[group] || 'player') + ' (100 = best).' + (cp.qualified === false ? ' <strong>Below the sample floor</strong>: values only.' : '') + '</span><span class="gq-ctl">' +
        k.toggle('pp-basis', [['pct', 'Group'], ['pct_pos', 'Position']], ST.basis) + '</span></div><div class="gq-pad" id="pp-sl"></div></div>';
    }
    // position panels
    h += '<div id="pp-pos"></div>';
    // log
    h += '<div class="card"><div class="card-header">Game log <span class="card-sub">' + k.esc(cur.season || S) + ', every game played.</span></div><div id="pp-log"></div></div>';
    // career
    h += '<div class="card"><div class="card-header">Career <span class="card-sub">Every season on file from 1999; EPA from play-by-play, value is Gridiron Value (opponent and supporting-cast adjusted EPA credit). Columns ending in + are era-adjusted: 100 + 10 z against that season\'s qualified players at the position (qualified seasons only).</span></div><div id="pp-car-c" style="height:240px"></div><div id="pp-car"></div></div>';
    h += '<div class="grid-2"><div class="card"><div class="card-header">Projection <span class="card-sub">Rest of season and next season: each rate regressed by its stabilisation point, with aging; ranges are 10th–90th percentiles.</span></div><div id="pp-proj"></div></div>' +
      '<div class="card"><div class="card-header">Similar players <span class="card-sub">This season\'s nearest qualified players in the same group on the percentile profile; 100 would be identical.</span></div><div id="pp-sim"></div></div></div>';
    h += '<div class="grid-2"><div class="card"><div class="card-header">Next Gen Stats <span class="card-sub">NFL Next Gen Stats via nflverse (2016 on; informational, non-commercial use).</span></div><div id="pp-ngs"></div></div>' +
      '<div class="card"><div class="card-header">FTN charting <span class="card-sub">FTN Data via nflverse (CC-BY-SA 4.0; 2022 on).</span></div><div id="pp-ftn"></div></div></div>';
    el.innerHTML = h;
    k.setMeta(k.esc(name));
    if (cp && metrics.length) {
      const drawSl = () => {
        const pc = (ST.basis === 'pct_pos' ? (cp.pct_pos || cp.pct) : cp.pct) || {};
        k.set('pp-sl', k.sliders(metrics, cp.values || {}, pc, { note: (cp.qualified === false ? 'Below the sample floor for percentiles. ' : '') + 'Click a metric for its definition and stabilisation point.' }));
      };
      drawSl();
      k.wireToggle(el, 'pp-basis', v => { ST.basis = v; drawSl(); });
    }
    positionPanels(ctx);
    gameLog(ctx);
    careerPanel(ctx);
    projection(ctx);
    similar(ctx);
    facts('pp-ngs', cur.ngs || c.ngs, meta, 'No Next Gen Stats for this player this season (NGS covers qualifying passers, rushers and receivers from 2016).');
    facts('pp-ftn', cur.ftn || c.ftn, meta, 'No FTN charting for this player this season (FTN starts in 2022).');
  });
}

function flat(r) {
  if (!r || typeof r !== 'object') return {};
  const out = Object.assign({}, r);
  if (r.plus && typeof r.plus === 'object') Object.keys(r.plus).forEach(x => { out['plus_' + x] = r.plus[x]; });
  delete out.plus;
  ['stats', 'passing', 'rushing', 'receiving', 'kicking', 'punting', 'defense', 'defence', 'advanced', 'value_detail'].forEach(x => { if (r[x] && typeof r[x] === 'object' && !Array.isArray(r[x])) Object.keys(r[x]).forEach(kk => { if (out[kk] === undefined || out[kk] === r[x]) out[kk] = r[x][kk]; }); });
  return out;
}
function ageOf(dob) {
  if (!dob) return null;
  const d = new Date(String(dob).slice(0, 10) + 'T12:00:00Z');
  if (isNaN(d.getTime())) return null;
  return (Date.now() - d.getTime()) / (365.25 * 86400000);
}
function fmtHeight(h) { const n = Number(h); return K().isNum(n) && n > 50 && n < 90 ? Math.floor(n / 12) + '\'' + (n % 12) + '"' : String(h); }

// ── position panels ────────────────────────────────────────────────────────

function positionPanels(ctx) {
  const k = K(), host = document.getElementById('pp-pos');
  if (!host) return;
  const ch = ctx.cur.charts || {};
  const g = ctx.group;
  let h = '';
  if (g === 'QB') {
    h += '<div class="card"><div class="card-header">Pass grid <span class="card-sub">Throws by depth (air yards) and location; colour and numbers by the selected measure. Sacks, spikes and throwaways without a location are left out.</span><span class="gq-ctl" id="pg-ctl"></span></div><div id="pp-grid" class="gf-grid"></div><div class="pg-note gq-note" id="pp-grid-n"></div></div>';
    h += '<div class="card"><div class="card-header">Game by game <span class="card-sub">EPA per dropback and CPOE in each game.</span></div><div id="pp-trend" style="height:300px"></div></div>';
  } else if (g === 'RB') {
    h += '<div class="card"><div class="card-header">Rushing yards over expected <span class="card-sub">Ours (from box count, situation and the run\'s landmarks) against Next Gen Stats\' RYOE, per carry by game.</span></div><div id="pp-ryoe" style="height:320px"></div><div id="pp-ryoe-t"></div></div>';
  } else if (g === 'WR' || g === 'TE') {
    h += '<div class="card"><div class="card-header">Depth profile <span class="card-sub">Targets by depth of target, with catch rate and EPA per target in each band.</span></div><div id="pp-depth" style="height:320px"></div><div id="pp-depth-t"></div></div>';
  } else if (g === 'K') {
    h += '<div class="card"><div class="card-header">Field goals over expected by distance <span class="card-sub">Our make probability (distance, weather, altitude, roof, surface) against what happened, per distance band.</span></div><div id="pp-fg" style="height:320px"></div><div id="pp-fg-t"></div></div>';
  } else if (g === 'P') {
    h += '<div class="card"><div class="card-header">Punting <span class="card-sub">Gross, net and EPA per punt by field position.</span></div><div id="pp-punt"></div></div>';
  } else if (g === 'DEF') {
    h += '<div class="card"><div class="card-header">Defence <span class="card-sub">What the public data allows: pass rush from play-by-play and FTN (2022 on), tackles and takeaways. There is no individual coverage charting in-season, so a defensive back\'s coverage is not rated here.</span></div><div id="pp-def"></div></div>';
  }
  host.innerHTML = h;
  if (g === 'QB') { passGrid(ch.qb_grid || ch.qb || ch.pass_grid || ch.grid || ctx.cur.pass_grid, ctx); qbTrend(ctx); }
  if (g === 'RB') ryoe(ch.ryoe_by_game || ch.rb || ch.ryoe || ctx.cur.ryoe, ctx);
  if (g === 'WR' || g === 'TE') depth(ch.depth_profile || ch.receivers || ch.wr || ch.te || ch.depth || ctx.cur.depth, ctx);
  if (g === 'K') fieldGoals(ch.k || ch.kicker || ch.fg || ctx.cur.fg, ctx);
  if (g === 'P') { const P = ch.p || ch.punter || ch.punts; k.set('pp-punt', P ? rowsTable(P, ctx.meta, { first: 'Field position' }) : k.muted('No punting splits yet.')); }
  if (g === 'DEF') { const D = ch.def || ch.defense || ch.defence || ctx.cur.def; k.set('pp-def', D ? rowsTable(D, ctx.meta, { first: 'Split' }) : k.muted('Per-player charts are not published for defenders; the percentiles and game log above carry what there is.')); }
}

/* A pass grid in any of the shapes a payload may use -> {rows: depth labels (deep first), cols: location labels, m: {metric: [[...]]}}.
 * Accepted: {depth|rows|y: [...], loc|location|cols|x: [...], <metric>: [[...]]} ; [{depth, loc, att, cmp, epa, cpoe...}] ; {cols, rows} frame. */
const DEPTH_ORDER = ['20+', 'deep', '10-19', 'intermediate', '0-9', 'short', '<0', 'behind', 'behind los', 'screen'];
function gridOf(g) {
  const k = K();
  if (!g) return null;
  const isM = v => Array.isArray(v) && v.length && v.every(r => Array.isArray(r));
  if (!Array.isArray(g) && typeof g === 'object' && !(g.cols && g.rows && !isM(g.rows))) {
    const rows = g.depth || g.depths || g.rows || g.y || g.depth_bins;
    const cols = g.loc || g.location || g.locations || g.cols || g.x || g.loc_bins;
    const m = {};
    Object.keys(g).forEach(x => { if (isM(g[x]) && !/^(n|rows|cols)$/.test(x)) m[x] = g[x]; });
    if (isM(g.n) && !m.att) m.att = g.n;
    if (Array.isArray(rows) && Array.isArray(cols) && Object.keys(m).length) return { rows: rows.map(String), cols: cols.map(String), m: m, order: g.order || 'deep_first' };
  }
  const cells = k.listOf(g);
  if (!cells.length) return null;
  const dk = k.pick(cells[0], ['depth', 'depth_bin', 'air', 'air_bin', 'band', 'y']), lk = k.pick(cells[0], ['loc', 'location', 'side', 'pass_location', 'x']);
  if (!dk || !lk) return null;
  const rows = Array.from(new Set(cells.map(c => String(c[dk])))), cols = Array.from(new Set(cells.map(c => String(c[lk]))));
  const LO = ['left', 'l', 'middle', 'm', 'mid', 'right', 'r'];
  cols.sort((a, b) => LO.indexOf(a.toLowerCase()) - LO.indexOf(b.toLowerCase()));
  rows.sort((a, b) => depthRank(a) - depthRank(b));
  const m = {};
  Object.keys(cells[0]).filter(x => x !== dk && x !== lk && cells.some(c => k.isNum(c[x]))).forEach(x => { m[x] = rows.map(r => cols.map(cc => { const c = cells.find(z => String(z[dk]) === r && String(z[lk]) === cc); return c && k.isNum(c[x]) ? Number(c[x]) : null; })); });
  return { rows: rows, cols: cols, m: m, order: 'deep_first' };
}
function depthRank(s) {
  const x = String(s).toLowerCase();
  const i = DEPTH_ORDER.indexOf(x);
  if (i >= 0) return i;
  const n = parseFloat(x.replace(/[^\d.-]/g, ''));
  return K().isNum(n) ? 100 - n : 50;
}
const GRID_M = [['epa', 'EPA per attempt', 'signed2', 'div'], ['epa_per_att', 'EPA per attempt', 'signed2', 'div'], ['cpoe', 'CPOE', 'pp', 'div'], ['cmp_pct', 'Completion %', 'pct', 'seq'], ['comp_pct', 'Completion %', 'pct', 'seq'],
  ['att', 'Attempts', 'int', 'seq'], ['n', 'Attempts', 'int', 'seq'], ['share', 'Share of attempts', 'pct', 'seq'], ['ypa', 'Yards per attempt', '1', 'seq'], ['int', 'Interceptions', 'int', 'seq'], ['td', 'Touchdowns', 'int', 'seq'], ['success', 'Success rate', 'pct', 'seq'], ['success_rate', 'Success rate', 'pct', 'seq'], ['twp', 'Turnover-worthy', 'int', 'seq']];
function passGrid(raw, ctx) {
  const k = K();
  const node = document.getElementById('pp-grid'), note = document.getElementById('pp-grid-n'), ctl = document.getElementById('pg-ctl');
  if (!node) return;
  const shell = k.chart('passGrid');
  const G = gridOf(raw);
  if (!G) { node.innerHTML = k.muted('The pass grid is not available for this quarterback yet.'); return; }
  // derived measures
  if (G.m.cmp && G.m.att && !G.m.cmp_pct && !G.m.comp_pct) G.m.cmp_pct = G.m.att.map((r, i) => r.map((a, j) => (a ? G.m.cmp[i][j] / a : null)));
  if (G.m.att && !G.m.share) { const tot = k.sum([].concat.apply([], G.m.att)); if (tot) G.m.share = G.m.att.map(r => r.map(a => (k.isNum(a) ? a / tot : null))); }
  const ms = GRID_M.filter(x => G.m[x[0]]);
  Object.keys(G.m).forEach(x => { if (!ms.some(y => y[0] === x)) ms.push([x, label(x), guessFmt(x, k.mean([].concat.apply([], G.m[x]))), 'seq']); });
  const seen = {};
  const list = ms.filter(x => { if (seen[x[1]]) return false; seen[x[1]] = 1; return true; });
  if (!list.some(x => x[0] === ST.grid)) ST.grid = (list.find(x => /epa/.test(x[0])) || list[0])[0];
  if (ctl) ctl.innerHTML = k.select('pg-m', list.map(x => [x[0], x[1]]), ST.grid);
  const draw = () => {
    const sel = list.find(x => x[0] === ST.grid) || list[0];
    if (shell) {
      // The shell's grid wants depths nearest the line first (drawn bottom-up) and its own formats.
      const nn = G.m.att || G.m.n;
      const rev = a => (a ? a.slice().reverse() : null);
      const sf = { signed2: 'signed', pp: 'signed1', signed3: 'epa' }[sel[2]] || sel[2];
      try { shell(node, { depths: rev(G.rows).map(depthLabel), locs: G.cols.map(x => k.titleCase(x)), v: rev(G.m[sel[0]]), n: sel[0] === 'att' || sel[0] === 'n' ? null : rev(nn) }, { fmt: sf, scale: sel[3] === 'div' ? 'div' : 'seq', center: 0, label: sel[1], height: k.narrow(node) ? 260 : 300 }); note.innerHTML = gridNote(); return; } catch (e) { console.warn('passGrid', e); }
    }
    const z = G.m[sel[0]];
    const flatv = [].concat.apply([], z).filter(k.isNum);
    if (!flatv.length) { node.innerHTML = k.muted('No throws in this view.'); return; }
    let zmin = Math.min.apply(null, flatv), zmax = Math.max.apply(null, flatv);
    if (sel[3] === 'div') { const r = Math.max(Math.abs(zmin), Math.abs(zmax)) || 1; zmin = -r; zmax = r; }
    const nn = G.m.att || G.m.n;
    const ann = [];
    z.forEach((r, i) => r.forEach((v, j) => { if (k.isNum(v)) ann.push({ x: j, y: i, text: k.fmtV(v, sel[2]) + (nn && k.isNum(nn[i][j]) && sel[0] !== 'att' && sel[0] !== 'n' ? '<br><span style="font-size:9px">' + nn[i][j] + ' att</span>' : ''), showarrow: false, font: { size: k.narrow(node) ? 10 : 12, color: '#f0f3f6' } }); }));
    const hov = z.map((r, i) => r.map((v, j) => k.esc(G.rows[i]) + ' · ' + k.esc(G.cols[j]) + '<br>' + k.esc(sel[1]) + ': ' + (k.isNum(v) ? k.fmtV(v, sel[2]) : '—') + (nn && k.isNum(nn[i][j]) ? ' · ' + nn[i][j] + ' att' : '')));
    k.plot(node, [{ type: 'heatmap', x: G.cols.map((_, j) => j), y: G.rows.map((_, i) => i), z: z, zmin: zmin, zmax: zmax, colorscale: sel[3] === 'div' ? k.DIVERGE : [[0, '#16241b'], [0.5, '#2f6f4a'], [1, '#e08a3c']], xgap: 3, ygap: 3, showscale: false, text: hov, hoverinfo: 'text' }],
      k.layout({ margin: { l: 90, r: 10, t: 30, b: 10 }, annotations: ann,
        xaxis: { side: 'top', tickvals: G.cols.map((_, j) => j), ticktext: G.cols.map(x => k.titleCase(x)), showgrid: false, zeroline: false, fixedrange: true },
        yaxis: { tickvals: G.rows.map((_, i) => i), ticktext: G.rows.map(x => k.esc(depthLabel(x))), autorange: 'reversed', showgrid: false, zeroline: false, fixedrange: true } }));
    note.innerHTML = gridNote();
  };
  const gridNote = () => 'Rows are air yards at the catch point or target (deepest at the top); columns are where the ball was thrown, from the quarterback\'s view. EPA and CPOE use our expected-points and completion models. ' +
    (ctx.cur.season ? ctx.cur.season + ' season.' : '');
  const sel = document.getElementById('pg-m');
  if (sel) sel.onchange = e => { ST.grid = e.target.value; draw(); };
  draw();
}
function depthLabel(x) { const s = String(x); if (/^20\+$/.test(s)) return '20+ yds'; if (/^\d+-\d+$/.test(s)) return s + ' yds'; if (/^<0$|behind/i.test(s)) return 'Behind LOS'; return K().titleCase(s); }

function qbTrend(ctx) {
  const k = K(), node = document.getElementById('pp-trend');
  if (!node) return;
  const log = k.listOf(ctx.cur.log);
  const wk = r => k.first(r.week, r.wk);
  log.forEach(r => { if (k.isNum(r.p_epa) && k.isNum(r.p_db) && r.p_db > 0 && !k.isNum(r.p_epa_db)) r.p_epa_db = r.p_epa / r.p_db; });
  const ek = k.pick(log.find(r => k.isNum(r.p_epa_db)) || log[0] || {}, ['p_epa_db', 'epa_per_db', 'epa_per_play', 'epa_play', /epa.*(per|play)/]), ck = k.pick(log[0] || {}, ['cpoe']);
  const rows = log.filter(r => k.isNum(wk(r)) && (k.isNum(r[ek]) || k.isNum(r[ck])));
  if (rows.length < 2) { node.innerHTML = k.muted('Needs two or more games with EPA or CPOE in the log.'); node.style.height = 'auto'; return; }
  const tr = [];
  const tl = node.parentNode && node.parentNode.querySelector('.card-sub');
  if (tl && !ck) tl.textContent = 'EPA per dropback in each game (passes, sacks and scrambles).';
  if (ek) tr.push({ type: 'bar', name: 'EPA per dropback', x: rows.map(wk), y: rows.map(r => r[ek]), marker: { color: rows.map(r => (r[ek] >= 0 ? k.ACC : '#f85149')) }, hovertemplate: 'Week %{x}: %{y:+.3f} EPA per dropback<extra></extra>' });
  if (ck) { const cv = rows.map(r => r[ck]); const sc = cv.some(v => Math.abs(v) > 1) ? 1 : 100; tr.push({ type: 'scatter', mode: 'lines+markers', name: 'CPOE (pp)', x: rows.map(wk), y: cv.map(v => (k.isNum(v) ? v * sc : null)), yaxis: 'y2', line: { color: '#58a6ff', width: 2 }, hovertemplate: 'Week %{x}: CPOE %{y:+.1f}<extra></extra>' }); }
  k.plot(node, tr, k.layout(Object.assign({ margin: { l: 50, r: 50, t: 30, b: 36 }, xaxis: { title: 'Week', dtick: 1 }, yaxis: { title: 'EPA per dropback', zeroline: true }, yaxis2: { title: 'CPOE (pp)', overlaying: 'y', side: 'right', showgrid: false, zeroline: false } }, k.legendTop())));
}

/* RYOE by game: [[week, ours, ngs, carries]] or [{week, ryoe|ryoe_ours, ryoe_ngs, carries}] (totals or per carry: totals are divided by carries). */
function ryoe(raw, ctx) {
  const k = K(), node = document.getElementById('pp-ryoe'), tab = document.getElementById('pp-ryoe-t');
  if (!node) return;
  let rows = [];
  const carriesOf = {};
  k.listOf(ctx.cur.log).forEach(r => { const w = k.first(r.week, r.wk); if (k.isNum(w)) carriesOf[w] = k.first(r.r_car, r.carries, r.rush_att); });
  if (Array.isArray(raw) && raw.length && Array.isArray(raw[0])) rows = raw.map(r => ({ week: r[0], ours: r[1], ngs: r.length > 2 ? r[2] : null, n: k.isNum(r[3]) ? r[3] : carriesOf[r[0]], opp: r[4] }));
  else rows = k.listOf(raw).map(r => ({ week: k.first(r.week, r.wk), ours: k.first(r.ryoe_per_att, r.ryoe_ours_per_att, r.ours, r.ryoe, r.ryoe_ours), ngs: k.first(r.ryoe_per_att_ngs, r.ryoe_ngs_per_att, r.ngs, r.ryoe_ngs), n: k.first(r.carries, r.att, r.rush_att, r.n), opp: r.opp, perAtt: !!(r.ryoe_per_att || r.ours !== undefined) }));
  if (!rows.length) {
    // fall back to the game log
    rows = k.listOf(ctx.cur.log).map(r => ({ week: k.first(r.week, r.wk), ours: k.first(r.ryoe_per_att, r.ryoe), ngs: k.first(r.ryoe_per_att_ngs, r.ryoe_ngs), n: k.first(r.carries, r.rush_att, r.att), opp: r.opp }));
  }
  rows = rows.filter(r => k.isNum(r.week) && (k.isNum(r.ours) || k.isNum(r.ngs)));
  if (!rows.length) { node.innerHTML = k.muted('RYOE by game is not available for this back yet.'); node.style.height = 'auto'; return; }
  // Values above 3 in absolute size per game are totals: show per carry.
  const big = rows.every(r => k.isNum(r.n)) && (Array.isArray(raw) && raw.length && Array.isArray(raw[0]) ? true : rows.some(r => Math.abs(r.ours || 0) > 4 || Math.abs(r.ngs || 0) > 4));
  const per = (v, n) => (k.isNum(v) ? (big && k.isNum(n) && n > 0 ? v / n : v) : null);
  const tr = [{ type: 'scatter', mode: 'lines+markers', name: 'Ours', x: rows.map(r => r.week), y: rows.map(r => per(r.ours, r.n)), line: { color: k.ACC, width: 2 }, marker: { size: rows.map(r => (k.isNum(r.n) ? 5 + Math.sqrt(r.n) * 1.5 : 7)) }, hovertemplate: 'Week %{x}: %{y:+.2f} per carry (ours)<extra></extra>' }];
  if (rows.some(r => k.isNum(r.ngs))) tr.push({ type: 'scatter', mode: 'lines+markers', name: 'NGS', x: rows.map(r => r.week), y: rows.map(r => per(r.ngs, r.n)), line: { color: '#58a6ff', width: 2, dash: 'dot' }, hovertemplate: 'Week %{x}: %{y:+.2f} per carry (NGS)<extra></extra>' });
  k.plot(node, tr, k.layout(Object.assign({ margin: { l: 50, r: 10, t: 30, b: 36 }, xaxis: { title: 'Week', dtick: 1 }, yaxis: { title: 'RYOE per carry', zeroline: true, zerolinecolor: '#6e7681' } }, k.legendTop())));
  const both = rows.filter(r => k.isNum(r.ours) && k.isNum(r.ngs));
  const r = both.length >= 3 ? k.corr(both.map(x => per(x.ours, x.n)), both.map(x => per(x.ngs, x.n))) : null;
  const tot = (f) => { const nn = k.sum(rows.map(x => x.n)); const s = big ? k.sum(rows.map(f)) : k.sum(rows.map(x => (k.isNum(f(x)) && k.isNum(x.n) ? f(x) * x.n : null))); return { tot: s, per: nn ? s / nn : null, n: nn }; };
  const a = tot(x => x.ours), b = tot(x => x.ngs);
  const ng = ctx.cur.ngs || {};
  const ngsPer = k.first(ng.rush_yards_over_expected_per_att), ngsTot = k.first(ng.rush_yards_over_expected);
  tab.innerHTML = '<div class="pg-note gq-note">' + (a.n ? 'Season: ours ' + k.signed(a.tot, 1) + ' yards over expected on ' + k.int(a.n) + ' carries (' + k.signed(a.per, 2) + ' a carry)' + (rows.some(x => k.isNum(x.ngs)) ? '; NGS ' + k.signed(b.tot, 1) + ' (' + k.signed(b.per, 2) + ')' : (k.isNum(ngsPer) ? '; Next Gen Stats has ' + (k.isNum(ngsTot) ? k.signed(ngsTot, 1) + ' (' : '') + k.signed(ngsPer, 2) + ' a carry' + (k.isNum(ngsTot) ? ')' : '') + ' for the season (NGS publishes season rows, not games)' : '')) + '. ' : '') +
    (k.isNum(r) ? 'Game-by-game agreement between the two: r = ' + k.num(r, 2) + ' over ' + both.length + ' games. ' : '') +
    'NGS measures expected yards from player-tracking at the handoff (defenders\' positions and speeds); ours uses what play-by-play, FTN and participation data record (box count, down, distance, field position, formation), so the two will disagree on individual runs.</div>';
}

/* Receivers: [{depth|band, targets, rec|catches, yards, epa, ...}] or {bands|depth: [...], targets: [...], ...}. */
function depth(raw, ctx) {
  const k = K(), node = document.getElementById('pp-depth'), tab = document.getElementById('pp-depth-t');
  if (!node) return;
  let rows = [];
  if (raw && !Array.isArray(raw) && typeof raw === 'object' && Array.isArray(raw.bands || raw.depth || raw.depths) && !(raw.cols && raw.rows)) {
    const bands = raw.bands || raw.depth || raw.depths;
    rows = bands.map((b, i) => { const o = { band: String(b) }; Object.keys(raw).forEach(x => { if (Array.isArray(raw[x]) && raw[x] !== bands && raw[x].length === bands.length) o[x] = raw[x][i]; }); return o; });
  } else rows = k.listOf(raw).map(r => Object.assign({ band: String(r.depth !== undefined ? r.depth : (r.band !== undefined ? r.band : (r.bin !== undefined ? r.bin : ''))) }, r));
  rows = rows.filter(r => r.band !== '');
  if (!rows.length) { node.innerHTML = k.muted('The depth profile is not available for this receiver yet.'); node.style.height = 'auto'; return; }
  rows.sort((a, b) => depthRank(b.band) - depthRank(a.band));
  const tg = r => k.first(r.targets, r.tgt, r.n, r.att);
  const cr = r => k.first(r.catch, r.catch_rate, r.cmp_pct, k.isNum(k.first(r.rec, r.catches, r.receptions)) && tg(r) ? k.first(r.rec, r.catches, r.receptions) / tg(r) : null);
  const ep = r => k.first(r.epa_per_target, r.epa_per_tgt, k.isNum(r.epa) && tg(r) && Math.abs(r.epa) > 3 ? r.epa / tg(r) : r.epa);
  const x = rows.map(r => depthLabel(r.band));
  const tr = [{ type: 'bar', name: 'Targets', x: x, y: rows.map(tg), marker: { color: k.alpha(k.ACC, 0.75) }, hovertemplate: '%{x}: %{y} targets<extra></extra>' }];
  if (rows.some(r => k.isNum(ep(r)))) tr.push({ type: 'scatter', mode: 'lines+markers', name: 'EPA per target', x: x, y: rows.map(ep), yaxis: 'y2', line: { color: '#f97316', width: 2 }, hovertemplate: '%{x}: %{y:+.2f} EPA per target<extra></extra>' });
  if (rows.some(r => k.isNum(cr(r)))) tr.push({ type: 'scatter', mode: 'lines+markers', name: 'Catch rate', x: x, y: rows.map(cr), yaxis: 'y3', line: { color: '#58a6ff', width: 2, dash: 'dot' }, hovertemplate: '%{x}: %{y:.0%} caught<extra></extra>' });
  k.plot(node, tr, k.layout(Object.assign({ margin: { l: 44, r: 50, t: 30, b: 40 }, xaxis: { type: 'category', title: 'Depth of target' }, yaxis: { title: 'Targets' },
    yaxis2: { title: 'EPA/target', overlaying: 'y', side: 'right', showgrid: false, zeroline: true, zerolinecolor: '#3d444d' }, yaxis3: { overlaying: 'y', side: 'right', visible: false, range: [0, 1.05] } }, k.legendTop())));
  tab.innerHTML = rowsTable(rows.map(r => Object.assign({ name: depthLabel(r.band) }, r, { band: undefined, depth: undefined, bin: undefined })), ctx.meta, { first: 'Depth', keyLabel: v => v });
}

/* Kicks: by band [{band|dist, att, made, exp|xmade|p}] or every kick [[dist, made(0/1), p]]. */
function fieldGoals(raw, ctx) {
  const k = K(), node = document.getElementById('pp-fg'), tab = document.getElementById('pp-fg-t');
  if (!node) return;
  let bands = [];
  const kicks = raw && Array.isArray(raw.kicks) ? raw.kicks : (Array.isArray(raw) && raw.length && Array.isArray(raw[0]) ? raw : null);
  if (kicks) {
    const B = [[18, 29, '18–29'], [30, 39, '30–39'], [40, 49, '40–49'], [50, 54, '50–54'], [55, 70, '55+']];
    bands = B.map(b => { const ks = kicks.filter(x => x[0] >= b[0] && x[0] <= b[1]); return { band: b[2], att: ks.length, made: k.sum(ks.map(x => x[1])), exp: k.sum(ks.map(x => x[2])) }; }).filter(b => b.att);
  } else {
    bands = k.listOf(raw && (raw.bands || raw.by_distance) ? (raw.bands || raw.by_distance) : raw).map(r => ({ band: String(k.first(r.lo) !== null ? r.lo + '–' + r.hi : (r.band || r.dist || r.distance || '')), att: k.first(r.att, r.fga, r.n), made: k.first(r.made, r.fgm), exp: k.first(r.exp, r.xmade, r.expected, k.isNum(r.p) && k.isNum(k.first(r.att, r.fga, r.n)) ? r.p * k.first(r.att, r.fga, r.n) : null) }));
  }
  bands = bands.filter(b => b.band && k.isNum(b.att) && b.att > 0);
  if (!bands.length) { node.innerHTML = k.muted('Field goals by distance are not available for this kicker yet.'); node.style.height = 'auto'; return; }
  const x = bands.map(b => b.band);
  const tr = [{ type: 'bar', name: 'Made %', x: x, y: bands.map(b => (k.isNum(b.made) ? b.made / b.att : null)), marker: { color: k.alpha(k.ACC, 0.8) }, text: bands.map(b => b.made + '/' + b.att), textposition: 'outside', hovertemplate: '%{x}: %{y:.0%} made (%{text})<extra></extra>' }];
  if (bands.some(b => k.isNum(b.exp))) tr.push({ type: 'scatter', mode: 'markers+lines', name: 'Expected %', x: x, y: bands.map(b => (k.isNum(b.exp) ? b.exp / b.att : null)), line: { color: '#f97316', width: 2, dash: 'dot' }, marker: { size: 9, symbol: 'diamond' }, hovertemplate: '%{x}: %{y:.0%} expected<extra></extra>' });
  k.plot(node, tr, k.layout(Object.assign({ margin: { l: 50, r: 10, t: 30, b: 40 }, xaxis: { type: 'category', title: 'Distance (yards)' }, yaxis: { title: 'Made', tickformat: '.0%', range: [0, 1.12] } }, k.legendTop())));
  const oe = k.sum(bands.map(b => (k.isNum(b.exp) && k.isNum(b.made) ? b.made - b.exp : null)));
  tab.innerHTML = k.table([{ label: 'Distance' }, { label: 'Att', align: 'right' }, { label: 'Made', align: 'right' }, { label: 'Made %', align: 'right' }, { label: 'Expected', align: 'right' }, { label: 'Over expected', align: 'right' }],
    bands.map(b => [{ v: b.band, html: '<strong>' + k.esc(b.band) + '</strong>' }, { v: b.att, html: k.int(b.att) }, { v: b.made, html: k.int(b.made) }, { v: b.made / b.att, html: k.pct(b.made / b.att, 0) },
      { v: b.exp, html: k.isNum(b.exp) ? k.num(b.exp, 1) : '—' }, { v: k.isNum(b.exp) ? b.made - b.exp : null, html: k.isNum(b.exp) ? '<span class="' + (b.made - b.exp >= 0 ? 'gq-ok' : 'gq-no') + '">' + k.signed(b.made - b.exp, 1) + '</span>' : '—' }]), { compact: true }) +
    '<div class="pg-note gq-note">' + (k.isNum(oe) ? 'Total: ' + k.signed(oe, 1) + ' field goals over expected, about ' + k.signed(oe * 3, 1) + ' points. ' : '') + 'Expected makes add up our make probability for each attempt. Blocked kicks count as misses.</div>';
}

/* A table of named rows: {rowKey: {metric: v}} or [{name|split|band, ...}]. */
function rowsTable(obj, meta, opts) {
  const k = K(), o = opts || {};
  let rows = [];
  if (Array.isArray(obj)) rows = obj.map(r => ({ key: r.name || r.split || r.band || r.key || r.label || r.id || '', v: r }));
  else if (obj && typeof obj === 'object' && (obj.cols || obj.fields) && obj.rows) rows = k.colRows(obj).map(r => ({ key: r.name || r.split || r.band || r.key || '', v: r }));
  else if (obj && typeof obj === 'object') rows = Object.keys(obj).filter(x => obj[x] && typeof obj[x] === 'object' && !Array.isArray(obj[x])).map(x => ({ key: x, v: obj[x] }));
  if (!rows.length) return k.muted(o.empty || 'Not available yet.');
  const skip = /^(split|name|key|label|id|desc|note|band|depth|bin)$/;
  const keys = [];
  rows.forEach(r => Object.keys(r.v).forEach(x => { if (!skip.test(x) && k.isNum(r.v[x]) && keys.indexOf(x) < 0) keys.push(x); }));
  const cols = keys.slice(0, o.max || 14);
  return k.table([{ label: o.first || 'Split' }].concat(cols.map(c => ({ label: label(c, meta), align: 'right', title: (meta && meta[c] && meta[c].desc) || '' }))),
    rows.map(r => [{ v: r.key, html: '<strong>' + k.esc(o.keyLabel ? o.keyLabel(r.key) : k.titleCase(r.key)) + '</strong>' }].concat(cols.map(c => ({ v: r.v[c], html: fv(c, r.v[c], meta) })))), { compact: true });
}

// ── log, career, projection, similar, facts ────────────────────────────────

function gameLog(ctx) {
  const k = K(), host = document.getElementById('pp-log');
  if (!host) return;
  const log = k.listOf(ctx.cur.log);
  if (!log.length) { host.innerHTML = k.muted('No games logged this season yet.'); return; }
  const lead = ['week', 'wk', 'date', 'opp', 'opponent', 'home', 'result', 'game_id', 'team'];
  const LOGORDER = { QB: ['p_cmp', 'p_att', 'p_yds', 'p_td', 'p_ints', 'p_sacks', 'p_db', 'p_epa', 'p_epa_db', 'r_car', 'r_yds', 'r_td', 'r_epa'], RB: ['r_car', 'r_yds', 'r_td', 'r_epa', 'r_ryoe', 'x_tgt', 'x_rec', 'x_yds', 'x_td', 'x_epa'], WR: ['x_tgt', 'x_rec', 'x_yds', 'x_td', 'x_air', 'x_epa', 'r_car', 'r_yds'] };
  LOGORDER.TE = LOGORDER.WR;
  log.forEach(r => { if (k.isNum(r.p_epa) && k.isNum(r.p_db) && r.p_db > 0 && !k.isNum(r.p_epa_db)) r.p_epa_db = r.p_epa / r.p_db; });
  const order = (LOGORDER[ctx.group] || []).concat((CAREER[ctx.group] || []).filter(x => !/^(season|team|games)$/.test(x)));
  const keys = [];
  log.forEach(r => Object.keys(r).forEach(x => { if (lead.indexOf(x) < 0 && keys.indexOf(x) < 0 && k.isNum(r[x])) keys.push(x); }));
  keys.sort((a, b) => (order.indexOf(a) < 0 ? 99 : order.indexOf(a)) - (order.indexOf(b) < 0 ? 99 : order.indexOf(b)));
  const cols = keys.slice(0, 16);
  const S = ctx.S;
  host.innerHTML = k.table([{ label: 'Wk' }, { label: 'Opp' }, { label: 'Result' }].concat(cols.map(c => ({ label: label(c, ctx.meta), align: 'right', title: (ctx.meta[c] || {}).desc || '' }))),
    log.slice().sort((a, b) => (k.first(a.week, a.wk) || 0) - (k.first(b.week, b.wk) || 0)).map(r => {
      const opp = r.opp || r.opponent || '';
      const gg = k.parseGid(r.game_id || r.gid);
      const at = r.home === false || r.home === 0 || r.away === true ? '@ ' : (r.home === true || r.home === 1 ? 'v ' : (r.team && gg.home ? (r.team === gg.home ? 'v ' : '@ ') : ''));
      const res = r.result || (k.isNum(r.pf) && k.isNum(r.pa) ? (r.pf > r.pa ? 'W ' : r.pf < r.pa ? 'L ' : 'T ') + r.pf + '–' + r.pa : '');
      const gid = r.game_id || r.gid;
      return [{ v: k.first(r.week, r.wk), html: '<strong>' + k.esc(k.first(r.week, r.wk) === null ? '—' : k.first(r.week, r.wk)) + '</strong>' },
        { v: opp, html: opp ? k.esc(at) + k.teamChip(opp, S) : '—' },
        { v: res, html: gid ? '<a href="' + k.gameHref(gid, S) + '">' + k.esc(res || 'Game') + '</a>' : k.esc(res || '—') }].concat(cols.map(c => ({ v: r[c], html: fv(c, r[c], ctx.meta) })));
    }), { compact: true, sticky: true });
  k.sortable(host);
}

function careerPanel(ctx) {
  const k = K(), host = document.getElementById('pp-car'), chart = document.getElementById('pp-car-c');
  if (!host) return;
  const rows = ctx.seasons;
  if (!rows.length) { host.innerHTML = k.muted('No season lines on file yet.'); if (chart) { chart.style.display = 'none'; } return; }
  const order = CAREER[ctx.group] || ['season', 'team', 'games', 'epa', 'value'];
  const present = order.filter(c => rows.some(r => r[c] !== undefined && r[c] !== null));
  // one column per concept (aliases): keep the first present of each alias set
  const ALIAS = [['pass_yds', 'passing_yards'], ['pass_td', 'passing_tds'], ['int', 'interceptions'], ['carries', 'rush_att'], ['rush_yds', 'rushing_yards'], ['rush_td', 'rushing_tds'], ['rec', 'receptions'], ['rec_yds', 'receiving_yards'], ['rec_td', 'receiving_tds'], ['any_a', 'anya'], ['epa_per_play', 'epa_play'], ['fgm', 'fg_made'], ['fga', 'fg_att'], ['fg_long', 'long'], ['gross_avg', 'punt_avg'], ['def_int', 'int'], ['pbu', 'pass_def']];
  const cols = present.filter(c => !ALIAS.some(a => a.indexOf(c) > 0 && present.indexOf(a[0]) >= 0));
  const extra = [];
  rows.forEach(r => Object.keys(r).forEach(x => { if (cols.indexOf(x) < 0 && extra.indexOf(x) < 0 && k.isNum(r[x]) && !ALIAS.some(a => a.indexOf(x) >= 0) && !/^(age|week|pid|id)$/.test(x)) extra.push(x); }));
  extra.sort((a, b) => (/^plus_/.test(a) ? 1 : 0) - (/^plus_/.test(b) ? 1 : 0));
  const all = cols.concat(extra.slice(0, Math.max(0, 22 - cols.length)));
  const sorted = rows.slice().sort((a, b) => a.season - b.season);
  host.innerHTML = k.table(all.map(c => ({ label: label(c, ctx.meta), align: /season|team/.test(c) ? 'left' : 'right', title: (ctx.meta[c] || {}).desc || '' })),
    sorted.map(r => all.map(c => {
      const v = r[c];
      if (c === 'team') return { v: v, html: v ? k.teamChip(v, r.season) : '—' };
      if (c === 'season') return { v: v, html: '<strong>' + k.esc(v) + '</strong>' };
      return { v: v, html: fv(c, v, ctx.meta) };
    })), { compact: true, sticky: true });
  k.sortable(host);
  const vk = k.pick(sorted[0] || {}, ['value', 'gv']) || (sorted.some(r => k.isNum(r.value)) ? 'value' : null);
  const ek = sorted.some(r => k.isNum(r.epa)) ? 'epa' : null;
  if (!chart) return;
  if (sorted.length < 2 || (!vk && !ek)) { chart.style.display = 'none'; return; }
  const tr = [];
  if (vk) tr.push({ type: 'bar', name: 'Gridiron Value', x: sorted.map(r => String(r.season)), y: sorted.map(r => r[vk]), marker: { color: sorted.map(r => (r[vk] >= 0 ? k.alpha(k.ACC, 0.85) : 'rgba(248,81,73,0.8)')) }, hovertemplate: '%{x}: %{y:+.1f} value<extra></extra>' });
  if (ek) tr.push({ type: 'scatter', mode: 'lines+markers', name: 'EPA', x: sorted.map(r => String(r.season)), y: sorted.map(r => r.epa), line: { color: '#58a6ff', width: 2 }, yaxis: vk ? 'y2' : 'y', hovertemplate: '%{x}: %{y:+.1f} EPA<extra></extra>' });
  k.plot(chart, tr, k.layout(Object.assign({ margin: { l: 48, r: 48, t: 30, b: 34 }, xaxis: { type: 'category' }, yaxis: { title: vk ? 'Value' : 'EPA', zeroline: true }, yaxis2: { title: 'EPA', overlaying: 'y', side: 'right', showgrid: false, zeroline: false } }, k.legendTop())));
}

function projection(ctx) {
  const k = K(), host = document.getElementById('pp-proj');
  if (!host) return;
  const pr = ctx.cur.projection || ctx.career.projection;
  if (!pr || typeof pr !== 'object') { host.innerHTML = k.muted('No projection yet.'); return; }
  const blocks = [];
  const one = (obj, title) => {
    const keys = Object.keys(obj).filter(x => obj[x] && typeof obj[x] === 'object' && !Array.isArray(obj[x]) && [obj[x].p50, obj[x].mean, obj[x].proj, obj[x].value].some(k.isNum));
    const flatKeys = Object.keys(obj).filter(x => k.isNum(obj[x]) && !/^(season|n|games_left|age)$/.test(x));
    if (!keys.length && !flatKeys.length) return '';
    let h = title ? '<div class="gq-sub-head">' + k.esc(title) + '</div>' : '';
    if (keys.length) h += k.table([{ label: 'Metric' }, { label: 'Projection', align: 'right' }, { label: '10th–90th', align: 'right' }, { label: '', sortable: false }],
      keys.map(x => { const v = obj[x], m = [v.p50, v.proj, v.mean, v.value].find(k.isNum); const span = k.isNum(v.p10) && k.isNum(v.p90) && v.p90 > v.p10;
        const bar = span ? '<span class="gq-range"><span style="left:0;width:100%"></span><i style="left:' + Math.max(0, Math.min(100, 100 * (m - v.p10) / (v.p90 - v.p10))).toFixed(0) + '%"></i></span>' : '';
        return [{ v: x, html: '<strong>' + k.esc(label(x, ctx.meta)) + '</strong>' }, { v: m, html: fv(x, m, ctx.meta) }, { v: v.p10, html: span ? fv(x, v.p10, ctx.meta) + ' – ' + fv(x, v.p90, ctx.meta) : '—' }, { v: '', html: bar }]; }), { compact: true });
    if (flatKeys.length) h += k.tiles(flatKeys.slice(0, 6).map(x => k.tile(label(x, ctx.meta), fv(x, obj[x], ctx.meta), '')));
    return h;
  };
  ['ros', 'rest_of_season', 'next', 'next_season'].forEach(x => { if (pr[x] && typeof pr[x] === 'object') blocks.push(one(pr[x], /next/.test(x) ? 'Next season' : 'Rest of season')); });
  if (!blocks.length) blocks.push(one(pr, pr.season ? pr.season + ' projection' : ''));
  const html = blocks.filter(Boolean).join('');
  host.innerHTML = (html || k.muted('No projection yet.')) + (pr.note ? '<div class="pg-note gq-note">' + k.esc(pr.note) + '</div>' : '');
}

function similar(ctx) {
  const k = K(), host = document.getElementById('pp-sim');
  if (!host) return;
  const list = ctx.career.similar || ctx.cur.similar || [];
  const rows = (Array.isArray(list) ? list : []).map(r => (Array.isArray(r) ? (typeof r[1] === 'string' || r[1] === null ? { pid: String(r[0]), name: r[1], team: r[2], s: r[3] } : { pid: String(r[0]), d: r[1], season: r[2], name: r[3] }) : { pid: String(r.pid || r.id), d: k.first(r.distance, r.d), s: k.first(r.sim, r.score, r.similarity), season: r.season, name: r.name, team: r.team }));
  if (!rows.length) { host.innerHTML = k.muted('No similar players computed yet.'); return; }
  rows.forEach(r => { if (r.name) k.learn(r.pid, { name: r.name }); });
  const ds = rows.map(r => r.d).filter(k.isNum), dmax = ds.length ? Math.max.apply(null, ds) * 1.25 : 1;
  host.innerHTML = '<div class="gq-sim">' + rows.slice(0, 10).map(r => {
    const w = k.isNum(r.d) ? 100 * (1 - r.d / dmax) : (k.isNum(r.s) ? (r.s <= 1 ? 100 * r.s : r.s) : 0);
    return '<div class="gq-sim-row"><span><a href="' + k.playerHref(r.pid, r.season) + '">' + k.esc(r.name || k.name(r.pid)) + '</a>' + (r.team ? ' ' + k.teamChip(r.team, ctx.S) : '') + (r.season ? ' <span class="muted-inline">' + k.esc(r.season) + '</span>' : '') + '</span>' +
      '<span class="gq-sim-bar"><span style="width:' + Math.max(4, Math.min(100, w)).toFixed(0) + '%"></span></span><span class="gq-sim-v" title="' + (k.isNum(r.d) ? 'Distance in standard deviations (lower is closer)' : 'Similarity: 100 minus the root-mean-square percentile gap over the group\'s metrics (higher is closer)') + '">' + (k.isNum(r.d) ? k.num(r.d, 2) : k.isNum(r.s) ? k.num(r.s, 0) : '') + '</span>' +
      '<a class="gq-sim-cmp" href="' + k.compareHref(ctx.pid, r.pid) + '">compare</a></div>';
  }).join('') + '</div>';
}

function facts(id, obj, meta, empty) {
  const k = K(), host = document.getElementById(id);
  if (!host) return;
  if (!obj || typeof obj !== 'object' || !Object.keys(obj).length) { host.innerHTML = k.muted(empty); return; }
  const nested = Object.keys(obj).filter(x => obj[x] && typeof obj[x] === 'object' && !Array.isArray(obj[x]));
  const flatKeys = Object.keys(obj).filter(x => k.isNum(obj[x]) && !/^(season|week)$/.test(x));
  let h = '';
  if (flatKeys.length) h += '<div class="gq-cmp-facts gq-pad">' + flatKeys.map(x => '<div class="gq-fact"><span>' + k.esc(label(x, meta)) + '</span><strong>' + fv(x, obj[x], meta) + '</strong></div>').join('') + '</div>';
  if (nested.length) h += rowsTable(Object.assign.apply(null, [{}].concat(nested.map(x => ({ [x]: obj[x] })))), meta, { first: 'Split' });
  host.innerHTML = h || k.muted(empty);
}

// ── shared with team, compare and others ───────────────────────────────────

(function (F) { F.playerLabel = label; F.guessFmt = guessFmt; F.fv = fv; F.rowsTable = rowsTable; F.flat = flat; })(GI.fk = GI.fk || {});

if (typeof GI.route === 'function') {
  [['player', render], ['#/player/<pid>', render]].forEach(r => { try { GI.route(r[0], r[1]); } catch (e) { /* bound */ } });
}
})(window.GI || (window.GI = {}));
