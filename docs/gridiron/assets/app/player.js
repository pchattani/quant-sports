/* The Quant Gridiron — the player page (#/player/<pid>), position-aware, on Design System 2.0 (the Rink player page is
 * the reference). Player card header (team band, position, age, size, college, draft, headline numbers) · stat tiles
 * with percentile chips · the Savant-style percentile card on the metrics spec's headline set against his group (QB, RB,
 * WR, TE, outside pass rushers, interior linemen, LB, CB, S, K, P; spec.js), with the sample, the minimum and the caveats beside where he sits in the peer distribution (players.json,
 * loaded after the first paint) · value (projected points above replacement,
 * with its band and by-season projection, current season) · similar players · position charts (QB pass
 * grid and EPA by game; RB RYOE by game; WR/TE depth profile; K field goals by distance; defenders'
 * splash plays by game) · season by season (value and EPA chart, table with era-adjusted + columns) ·
 * game log · Next Gen Stats and FTN splits. Reads players/<pid>.json, glossary.json (metric labels) and,
 * for the current season, <S>/valuation.json; <S>/players.json for the peer distribution. */
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

GI.route('player', function (el, params) {
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
        GI.notBuilt('The page for ' + (info.name || pid), res[0]) + GI.muted('Player pages are built for everyone who appears in a season catalogue since 1999. <a href="#/players">All players →</a>');
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
    const col = team ? GI.tc(team) : 'var(--signal)';
    const dr = c.draft || {};
    const draftTxt = dr.year || dr.season ? (dr.round ? 'Round ' + dr.round + (dr.pick ? ', pick ' + dr.pick : '') + ', ' : '') + (dr.year || dr.season) + (dr.team ? ' (' + dr.team + ')' : '') : '';
    const ht = isNum(c.height) && c.height > 50 ? Math.floor(c.height / 12) + '′' + (c.height % 12) + '″' : '';
    const peerRow = pctS ? { pos: pos, group: group, role: pctS.role, values: pctS.values || {}, pct: pctS.pct || {}, pct_pos: pctS.pct_pos || {}, pct_role: pctS.pct_role, games: viewSeason.games, qualified: viewSeason.qualified } : null;
    const g0 = GI.SP.groupOf(peerRow || { pos: pos, group: group }, pid, null);
    const tiles = (TILES[group] || []).map(t => { const key = GI.pickKey(vals, t[1]); return key && isNum(vals[key]) ? { label: t[0], key: key, v: vals[key], sub: t[2] } : null; }).filter(Boolean);
    const status = valn && valn.status && valn.status !== 'ACT' ? ({ RES: 'Injured reserve', DEV: 'Practice squad', INA: 'Inactive', FA: 'Free agent' }[valn.status] || valn.status) : '';
    const tags = [];
    if (pctS && viewSeason.qualified) tags.push(QK.tag('Qualified for percentiles', 'signal'));
    if (status) tags.push(QK.tag(status));
    let h = QK.playerHeader({ name: c.name, pos: GI.posLong(pos) || pos, kicker: (pctS ? S : (last.season || S)) + ' season',
      team: team ? { name: GI.teamName(team), abbr: GI.teamAbbr(team), colour: GI.teamInfo(team).colour, href: GI.teamHref(team, S) } : null,
      meta: [isNum(age) ? ['Age', GI.num(age, 0)] : null, ht ? ['Size', ht + (c.weight ? ' · ' + c.weight + ' lb' : '')] : null, c.college ? ['College', c.college] : null, draftTxt ? ['Draft', draftTxt] : null,
        seasons.length ? ['Seasons', seasons[0].season + '–' + last.season] : null],
      stats: tiles.slice(0, 4).map(t => ({ label: t.label, value: fv(t.key, t.v) })), tags: tags });
    h += '<div class="gi-toolbar" style="margin-top:12px"><a class="qk-btn primary" href="' + GI.compareHref(pid) + '">Compare</a><a class="qk-btn" href="' + GI.ghref('players', S, { g: g0 ? g0.code : group }) + '">All ' + esc((g0 ? g0.name : (GI.GROUP_NAME[group] || 'players')).toLowerCase()) + '</a>' +
      (team ? '<a class="qk-btn" href="' + GI.teamHref(team, S) + '">' + esc(GI.teamShort(team)) + '</a>' : '') + '</div>';
    const tl = [];
    if (valn) tl.push(GI.kpi('Projected value', GI.num(valn.value, 0), 'points above replacement, this season and the next three · likely range ' + GI.num(valn.lo, 0) + '–' + GI.num(valn.hi, 0), { signal: true, tip: 'Our player-value model: projected points above a replacement player, discounted 10% a season; the range is the 10th to 90th percentile' }));
    tiles.slice(0, valn ? 4 : 5).forEach(t => tl.push(GI.kpi(t.label, fv(t.key, t.v), esc(t.sub), { pctl: GI.SP.pctSync(peerRow, g0, t.key), tip: (META[t.key] || {}).desc })));
    if (tl.length) h += GI.kpis(tl);
    if (group === 'OL') h += GI.note('Offensive linemen have no individual metrics in the public data. The team page carries the line\'s unit ratings.');
    if (pctS && g0) {
      h += GI.grid('<div class="qk-span-5" id="pp-pcard">' + GI.card('Percentile rankings', 'Against ' + esc(g0.peer) + ', loading the peer group…', QK.skeleton('lines', 6)) + '</div>' +
        '<div class="qk-span-7"><div class="gi-stack">' + GI.card('Where he sits', '<span id="pp-dist-sub">Every qualified player in his peer group (' + esc(g0.peer.replace(/^NFL /, '')) + ') this season; bars coloured by percentile</span>',
          '<div class="qk-seg" id="pp-dist-m" role="group" aria-label="Metric" style="margin-bottom:10px"></div>' + GI.chartBox('pp-dist', 250, 'Distribution of the peer group')) +
        '<div id="pp-style"></div>' + ((c.similar || []).length ? GI.card('Most similar', 'Nearest on this season\'s profile among his peers', '<div id="pp-sim"></div>', { flush: true }) : '') + '</div></div>');
    } else {
      if (pctS && !g0 && group !== 'OL') h += GI.note('No comparison group for his position (' + esc(GI.posLong(pos) || pos) + '): percentiles are kept for QB, RB, WR, TE, the five defensive roles, K and P.');
      if ((c.similar || []).length) h += GI.card('Most similar', 'Nearest on this season\'s profile among his peers', '<div id="pp-sim"></div>', { flush: true });
    }
    if (valn) h += GI.card('Value', 'Projected points above a replacement player: rest of this season and the next three, discounted 10% a season · band 10th–90th percentile', '<div id="pp-val"></div>' + GI.chartBox('pp-valc', 220, 'Projected value by season'));
    const ch = now.charts || {};
    if (cur) h += '<div id="pp-moves"></div>';
    h += '<div id="pp-pos"></div>';
    h += GI.card('Season by season', 'every season on file since 1999 · value is Gridiron Value; columns ending + are era-adjusted (100 = average for that season, 10 = one SD)', (seasons.length > 1 ? GI.chartBox('pp-car-c', 260, 'Value and EPA by season') : '') + '<div id="pp-car"></div>', { id: 'career' });
    h += GI.card('Game log', (now.season || S) + ' · every game played', '<div id="pp-log"></div>', { flush: true });
    if (now.ngs || now.ftn) h += GI.grid(GI.card('Next Gen Stats', 'via nflverse; informational, non-commercial use', factsTable(now.ngs, 'No Next Gen Stats this season (qualifying passers, rushers and receivers only).'), { span: 6 }) +
      GI.card('FTN charting', 'FTN Data via nflverse (CC BY-SA 4.0)', factsTable(now.ftn, 'No FTN charting this season.'), { span: 6 }));
    el.innerHTML = h;

    // percentile card, style and where he sits: the season catalogue and value table (after the first paint), the spec's
    // group, metric set and peers (spec.js)
    if (pctS && g0) {
      GI.ch.none('pp-dist', 'Loading the peer group…');
      GI.loadAll([GI.ypath('players.json', S), GI.ypath('value.json', S)]).then(res2 => {
        if (!el.isConnected) return;
        const cat = GI.catOf(res2[0]);
        if (!cat) { GI.set('pp-pcard', GI.card('Percentile rankings', '', GI.muted('The season catalogue is not built yet.'))); GI.ch.none('pp-dist', 'The season catalogue is not built yet.'); return; }
        const cx = GI.SP.ctx(cat, GI.ok(res2[1]) ? res2[1] : null);
        const row = cat.players[pid] || peerRow;
        const g = GI.SP.groupOf(row, pid, cx) || g0;
        const rowsP = GI.SP.headline(g).map(m => { const v = GI.SP.value(row, pid, m, cx); return { label: m[1] + (m[3] ? ' ↓' : ''), pctl: GI.SP.pct(row, pid, g, m, cx), value: isNum(v) ? GI.SP.fmt(m, v, cx) : '—', tip: m[5] }; });
        const qualified = row.qualified !== false;
        GI.set('pp-pcard', QK.pctCard({ title: 'Percentile rankings', peer: g.peer + ', qualified', sample: [GI.SP.sample(row, g), 'qualified: ' + GI.SP.minLine(g)].filter(Boolean).join(' · '), groups: [{ label: '', rows: rowsP }],
          note: (GI.SP.NOTE[g.id] ? GI.SP.NOTE[g.id] + ' ' : '') + '100 = best among his peers; ↓ metrics are flipped so a high percentile is always good.',
          emptyText: qualified ? 'No percentiles for his group yet.' : 'He is short of the qualifying minimum (' + GI.SP.minLine(g) + '): no percentiles yet.',
          foot: '<span>' + esc(S) + ' · the metric set from our metrics study</span><a href="' + GI.compareHref(pid) + '">Compare →</a>' }));
        const st = GI.SP.style(g).map(m => { const v = GI.SP.value(row, pid, m, cx); const r = GI.SP.pct(row, pid, g, [m[0], m[1], m[2], m[3], 0, m[5], m[6]], cx); return isNum(v) ? '<dt data-tip="' + esc(m[5]) + '" tabindex="0">' + esc(m[1]) + '</dt><dd class="gi-num">' + GI.SP.fmt(m, v, cx) + (isNum(r) ? ' <span class="qk-muted">· ' + GI.ordinal(r) + ' of his peers</span>' : '') + '</dd>' : ''; }).join('');
        GI.set('pp-style', st ? GI.card('How he plays', 'Style, not quality: where he sits among his peers, with no better or worse', '<dl class="gi-dl">' + st + '</dl>') : '');
        const peers = GI.SP.members(cx, g.id).filter(id => cat.players[id].qualified !== false);
        GI.set('pp-dist-sub', 'Every qualified player in his peer group (' + esc(g.peer.replace(/^NFL /, '')) + ') this season; bars coloured by percentile');
        const keys = GI.SP.headline(g).filter(m => isNum(GI.SP.value(row, pid, m, cx))).slice(0, 4);
        const segEl = el.querySelector('#pp-dist-m');
        if (!keys.length || !segEl) { GI.ch.none('pp-dist', 'No metric to place him on yet.'); return; }
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
    if ((c.similar || []).length) {
      const sim = c.similar.map(r => (Array.isArray(r) ? { pid: String(r[0]), name: r[1], team: r[2], s: r[3] } : { pid: String(r.pid), name: r.name, team: r.team, s: first(r.sim, r.score) }));
      GI.set('pp-sim', GI.tableHTML([{ label: 'Player', sortable: false }, { label: 'Team', sortable: false }, { label: 'Similarity', align: 'right', sortable: false }, { label: '', sortable: false }],
        sim.slice(0, 8).map(r => [{ html: GI.playerLink(r.pid, r.name) }, { html: r.team ? GI.teamChip(r.team) : '' }, { html: isNum(r.s) ? '<span class="gi-pbar"><span class="gi-pbar-t"><span style="width:' + Math.max(0, Math.min(100, r.s)) + '%;background:var(--signal)"></span></span><span class="gi-pbar-v">' + GI.num(r.s, 0) + '</span></span>' : '—', v: r.s }, { html: '<a class="gi-more" href="' + GI.compareHref(pid, r.pid) + '">Compare</a>' }])) +
        (sim.length > 1 ? '<div class="qk-card-foot"><span></span><a href="' + GI.compareHref(pid, sim[0].pid, sim[1].pid) + '">Compare the top two →</a></div>' : ''));
    }
    // position panels
    const log = GI.listOf(now.log).slice().sort((a, b) => (a.week || 0) - (b.week || 0));
    const pp = [];
    if (group === 'QB' && Array.isArray(ch.qb_grid) && ch.qb_grid.length) pp.push(GI.card('Pass grid', 'throws by depth and direction (from the quarterback\'s view) · ' + (now.season || S), '<div class="gi-toolbar" style="margin-bottom:8px">' + GI.seg('pg-m', [['epa', 'EPA per attempt'], ['cmp_pct', 'Completion %'], ['att', 'Attempts']], ST.grid, 'Measure') + '</div>' + GI.chartBox('pp-grid', 300, 'Pass grid'), { span: 6 }));
    if (group === 'QB' && log.some(r => isNum(r.p_epa))) pp.push(GI.card('Game by game', 'EPA per dropback in each game', GI.chartBox('pp-trend', 300, 'EPA per dropback by game'), { span: 6 }));
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
    if (document.getElementById('pp-trend')) {
      const r = log.filter(x => isNum(x.p_epa) && x.p_db);
      GI.ch.bar('pp-trend', { cats: r.map(x => 'W' + x.week + ' ' + (x.opp || '')), series: [{ name: 'EPA per dropback', data: r.map(x => Math.round(x.p_epa / x.p_db * 1000) / 1000) }], diverging: true, labels: true, fmt: v => GI.signed(v, 2), catName: 'Week and opponent', valName: 'EPA per dropback' });
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
        series: [{ type: 'bar', name: 'Targets', data: r.map(x => first(x.tgt, x.targets)), barMaxWidth: 36, itemStyle: { color: T.model, borderRadius: [4, 4, 0, 0] } },
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
        series: [{ type: 'bar', name: 'Value', data: seasons.map(r => ({ value: r.value, itemStyle: { color: GI.ch.lift(GI.teamColour(r.team), T), borderRadius: [3, 3, 0, 0] } })), barMaxWidth: 26 },
          { type: 'line', name: 'EPA', yAxisIndex: 1, data: seasons.map(r => r.epa), symbolSize: 6, lineStyle: { color: T.cat[1], width: 2 }, itemStyle: { color: T.cat[1] } }]
      }), 'Value and EPA by season');
    } else GI.set('pp-car', GI.muted('No season lines on file yet.'));
    // game log
    if (log.length) {
      const lead = ['week', 'opp', 'game_id', 'team'];
      const keys = [];
      log.forEach(r => Object.keys(r).forEach(k => { if (lead.indexOf(k) < 0 && keys.indexOf(k) < 0 && isNum(r[k])) keys.push(k); }));
      GI.set('pp-log', GI.tableHTML([{ label: 'Wk', align: 'right' }, { label: 'Opp' }].concat(keys.map(k => ({ label: label(k), align: 'right' }))),
        log.map(r => { const g = GI.parseGameId(r.game_id) || {}; const at = r.team && g.home ? (r.team === g.home ? 'v ' : '@ ') : '';
          return [{ html: r.game_id ? '<a class="gi-link" href="' + GI.gameHref(r.game_id) + '">' + r.week + '</a>' : String(r.week), v: r.week }, { html: r.opp ? at + GI.teamChip(r.opp) : '—', v: r.opp }].concat(keys.map(k => ({ html: fv(k, r[k]), v: r[k] }))); }), { sticky: true }));
    } else GI.set('pp-log', GI.muted('No games logged this season.'));
    GI.sortable(el);
  });
});

GI.playerLabel = label;
})(window.GI);
