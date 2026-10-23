/* The Quant Rink — the player page (#/player/<pid>), skaters and goaltenders.
 *
 * Skaters: a header (team, position, shoots, age, size), tiles, Savant-style percentile sliders over the
 * season catalogue (against the position pool or the league), the shot heatmap against the league and the
 * shot map, the RAPM impact quadrant with standard errors, on-ice rates by strength, NHL EDGE skating and
 * shot speed, deployment (zone starts, quality of competition and teammates), linemates, the game log,
 * the career, a projection and similar players.
 * Goaltenders: tiles, percentiles among goalies, GSAx by danger and by location, save percentage by shot
 * type against expected, workload, the game log and the career.
 *
 * Data: data/players/<pid>.json (PAYLOADS "Per player": {"id","name","pos","shoots","dob","height","weight",
 * "seasons","current":{"log","shots","onice","rapm","edge","linemates","deployment","projection"},"similar"}),
 * data/<S>/skaters.json or goalies.json (values and percentiles), data/players_index.json. Uses RK.fk. */
(function (RK) {
'use strict';

const K = () => RK.fk;

// ── labels and formats for keys that are not in a catalogue ────────────────

const LABEL = {
  season: 'Season', team: 'Team', gp: 'GP', games: 'GP', gs: 'GS', date: 'Date', opp: 'Opp', result: 'Result', home: 'Home', age: 'Age',
  g: 'G', goals: 'G', a: 'A', assists: 'A', a1: 'A1', a2: 'A2', pts: 'P', points: 'P', p: 'P', pm: '+/−', plus_minus: '+/−', pim: 'PIM',
  toi: 'TOI', toi_gp: 'TOI/GP', toi_pg: 'TOI/GP', toi_5v5: '5v5 TOI', toi_pp: 'PP TOI', toi_pk: 'PK TOI', toi_ev: 'EV TOI', shifts: 'Shifts',
  s: 'Shots', sog: 'Shots', shots: 'Shots', ixg: 'ixG', xg: 'xG', ixg60: 'ixG/60', isf: 'iSF', icf: 'iCF', att: 'Attempts', sh_pct: 'Sh%', shooting_pct: 'Sh%',
  hits: 'Hits', blk: 'Blocks', blocks: 'Blocks', gv: 'Giveaways', giveaways: 'Giveaways', tk: 'Takeaways', takeaways: 'Takeaways', fow: 'FOW', fol: 'FOL', fo_pct: 'FO%', faceoff_pct: 'FO%',
  ppg: 'PPG', ppa: 'PPA', ppp: 'PPP', shg: 'SHG', shp: 'SHP', gwg: 'GWG', otg: 'OTG',
  cf: 'CF', ca: 'CA', cf_pct: 'CF%', ff: 'FF', fa: 'FA', ff_pct: 'FF%', sf: 'SF', sa: 'SA', sf_pct: 'SF%', xgf: 'xGF', xga: 'xGA', xgf_pct: 'xGF%', gf: 'GF', ga: 'GA', gf_pct: 'GF%',
  cf60: 'CF/60', ca60: 'CA/60', ff60: 'FF/60', fa60: 'FA/60', sf60: 'SF/60', sa60: 'SA/60', xgf60: 'xGF/60', xga60: 'xGA/60', gf60: 'GF/60', ga60: 'GA/60',
  g60: 'G/60', a60: 'A/60', pts60: 'P/60', p60: 'P/60', a160: 'A1/60', ixg_60: 'ixG/60', pdo: 'PDO', on_sh_pct: 'On-ice Sh%', on_sv_pct: 'On-ice Sv%',
  rel_xgf_pct: 'Rel xGF%', rel_cf_pct: 'Rel CF%', xgf_pct_rel: 'Rel xGF%', gax: 'Goals above xG', g_minus_ixg: 'G − ixG',
  value: 'Rink value', gar: 'GAR', war: 'WAR', ev_off: 'EV offence', ev_def: 'EV defence', pp_value: 'PP', pk_value: 'PK', pen_value: 'Penalties',
  rapm_off: 'RAPM offence', rapm_def: 'RAPM defence', off: 'Offence', def: 'Defence', off_se: 'Offence SE', def_se: 'Defence SE',
  oz_start_pct: 'OZ start %', dz_start_pct: 'DZ start %', nz_start_pct: 'NZ start %', ozs_pct: 'OZ start %', oz_starts: 'OZ starts', dz_starts: 'DZ starts', nz_starts: 'NZ starts', otf: 'On-the-fly starts', otf_pct: 'On-the-fly %',
  qoc: 'Quality of competition', qot: 'Quality of teammates', qoc_xg: 'QoC (xGF%)', qot_xg: 'QoT (xGF%)', qoc_toi: 'QoC (TOI)', qot_toi: 'QoT (TOI)',
  w: 'W', l: 'L', otl: 'OTL', t: 'T', sv: 'Saves', so: 'SO', shutouts: 'SO', sv_pct: 'Sv%', save_pct: 'Sv%', gaa: 'GAA', xsv_pct: 'xSv%', dsv_pct: 'dSv%',
  gsax: 'GSAx', gsax60: 'GSAx/60', gsax_low: 'GSAx low', gsax_med: 'GSAx med', gsax_high: 'GSAx high', hd_sv_pct: 'HD Sv%', md_sv_pct: 'MD Sv%', ld_sv_pct: 'LD Sv%',
  shots_faced: 'Shots faced', xga_faced: 'xG faced', qs: 'Quality starts', qs_pct: 'QS%', rbs: 'Really bad starts', starts: 'Starts', b2b: 'Back-to-backs', rest: 'Days rest',
  max_speed: 'Max skating speed', top_speed: 'Max skating speed', bursts_18: 'Bursts 18+ mph', bursts_20: 'Bursts 20+ mph', bursts_22: 'Bursts 22+ mph', distance: 'Distance skated', distance_60: 'Distance per 60',
  max_shot_speed: 'Max shot speed', top_shot_speed: 'Max shot speed', avg_shot_speed: 'Average shot speed', shots_70: 'Shots 70+ mph', shots_80: 'Shots 80+ mph', shots_90: 'Shots 90+ mph',
  toi5: '5v5 TOI', gs_score: 'Game score', plus_minus: '+/−', ppp: 'PPP', fa: 'Unblocked faced', proj_pts: 'Projected points (full season)', proj_g: 'Projected goals (full season)', proj_xgf_pct: 'Projected xGF%', pts_pace: 'Points pace',
  edge_max_speed: 'Top speed', edge_bursts_20: '20+ mph bursts', edge_bursts_22: '22+ mph bursts', edge_shot_speed: 'Hardest shot', edge_avg_shot_speed: 'Average shot speed', edge_distance: 'Distance skated', edge_distance60: 'Distance / 60', edge_oz_time: 'OZ time %',
  p10: '10th pct', p50: 'Median', p90: '90th pct', mean: 'Mean', proj: 'Projection'
};
function label(k, meta) { if (/^plus_/.test(k)) return label(k.slice(5), meta) + '+'; if (meta && meta[k] && meta[k].label) return meta[k].label; return LABEL[k] || LABEL[String(k).toLowerCase()] || K().titleCase(String(k).replace(/_pct$/, ' %').replace(/60$/, '/60').replace(/_per_/, '/')); }
function guessFmt(k, v, meta) {
  if (meta && meta[k] && meta[k].fmt) return meta[k].fmt;
  const key = String(k).toLowerCase(), isNum = K().isNum;
  if (!isNum(v)) return '';
  if (/^(season|gp|games|gs|age|w|l|otl|so|shutouts)$/.test(key)) return key === 'age' ? '0' : 'int';
  if (/^(sv_pct|save_pct|xsv_pct|[hml]d_sv_pct|sv_pct_.*|.*_sv_pct|on_sv_pct)$/.test(key)) return Math.abs(v) <= 1.5 ? 'sv' : '1';
  if (/^toi_?(gp|pg|per_game)$|^toi$|^toi\d/.test(key)) return v < 40 ? 'toi' : 'int';
  if (/^edge_.*speed/.test(key)) return 'mph';
  if (/^plus_/.test(key)) return 'int';
  if (/^toi_/.test(key)) return v < 40 ? 'toi' : 'int';
  if (/gaa|60$|_60|per60|pdo/.test(key)) return '2';
  if (/rapm|value|gar|war|gsax|gax|_rel|^rel_|qoc|qot|^off$|^def$|_se$/.test(key)) return Math.abs(v) < 1 ? '3' : (/se$/.test(key) ? '2' : 'signed2');
  if (/speed/.test(key)) return '1';
  if (/pct|share|rate$|%/.test(key)) return Math.abs(v) <= 1.5 ? 'pct' : '1';
  if (/^(ixg|xg|xgf|xga|ixg_.*|xg_.*)$/.test(key)) return Math.abs(v) < 10 ? '2' : '1';
  if (Number.isInteger(Number(v))) return 'int';
  return Math.abs(v) < 1 ? '3' : '1';
}
function fv(k, v, meta) { return K().fmtV(v, guessFmt(k, v, meta)); }

/* A strength label: "5v5", "pp" -> "Power play" … */
const STRENGTH = { all: 'All situations', '5v5': '5 on 5', ev: 'Even strength', pp: 'Power play', '5v4': '5 on 4', pk: 'Penalty kill', '4v5': '4 on 5', sh: 'Shorthanded', '4v4': '4 on 4', '3v3': '3 on 3', en: 'Empty net', other: 'Other' };
const strengthLabel = s => STRENGTH[String(s).toLowerCase()] || String(s);

// ── page ───────────────────────────────────────────────────────────────────

const ST = { basis: 'pct_pos', shots: 'diff', strength: '' };

function render(el, params, state) {
  const k = K();
  const pid = String(params.id || (params.rest || [])[0] || '');
  el.innerHTML = k.muted('Loading…');
  if (!pid) { el.innerHTML = k.card('Player', '', k.muted('No player id. Find one on the <a href="#/skaters">skaters</a> or <a href="#/goalies">goalies</a> pages or with the search box.')); return; }
  return k.ready().then(() => {
    const S = k.S(params, state);
    return Promise.all([RK.load('players/' + pid + '.json'), k.loadY(S, 'skaters.json'), k.loadY(S, 'goalies.json'), k.loadNames(), k.loadY(S, 'teams.json')]).then(res => ({ S: S, res: res }));
  }).then(o => {
    if (!k.alive(el)) return;
    const S = o.S;
    const career = (o.res[0] && o.res[0].ok !== false) ? o.res[0] : null;
    const sk = k.catOf(o.res[1]), gk = k.catOf(o.res[2]);
    if (sk) k.learnCat(sk);
    if (gk) k.learnCat(gk);
    const info = k.NAMES[pid] || {};
    const pos0 = (career && career.pos) || ((sk && sk.players[pid]) || (gk && gk.players[pid]) || {}).pos || info.pos || '';
    const goalie = k.groupOf(pos0) === 'G' || (!!gk && !!gk.players[pid] && !(sk && sk.players[pid]));
    if (goalie) RK.markNav('goalies');
    const cat = goalie ? gk : sk;
    const cp = cat && cat.players[pid] ? cat.players[pid] : null;
    if (!career && !cp) {
      el.innerHTML = k.card('Player', '', k.notBuilt('The page for ' + (info.name || pid), o.res[0]) + '<div class="pg-note gq-note">' + (info.name ? k.esc(info.name) + (info.pos ? ', ' + k.esc(k.posLabel(info.pos)) : '') + (info.first ? ', ' + k.esc(k.sLabel(info.first)) + ' to ' + k.esc(k.sLabel(info.last || '')) : '') + '. ' : '') + 'Player pages are built for everyone who appears in a season catalogue. <a href="#/skaters">Skaters →</a> · <a href="#/goalies">Goalies →</a></div>');
      return;
    }
    const c = career || {}, cur = c.current || {};
    const name = c.name || (cp && cp.name) || info.name || pid;
    k.learn(pid, { name: name, pos: pos0 });
    const group = goalie ? 'G' : k.groupOf(pos0);
    const seasons = k.listOf(c.seasons).map(flat).filter(r => k.isNum(k.sid(r.season)));
    seasons.forEach(r => { r.season = k.sid(r.season); });
    const last = seasons.length ? seasons.slice().sort((a, b) => b.season - a.season)[0] : {};
    const team = (cp && cp.team) || c.team || last.team || info.team || '';
    const age = k.first(cp && cp.age, c.age, ageOf(c.dob || c.birth_date));
    const metrics = cat ? (goalie ? k.allMetrics(cat) : k.metricsFor(cat, group)) : [];
    const meta = k.metaOf(cat ? k.allMetrics(cat) : []);
    const vals = Object.assign({}, flat(last), cur.values || {}, (cp && cp.values) || {});
    const tj = o.res[4] && o.res[4].ok !== false ? o.res[4] : {};
    const ctx = { pid: pid, S: S, name: name, pos: pos0, group: group, goalie: goalie, team: team, career: c, cur: cur, cp: cp, cat: cat, metrics: metrics, meta: meta, vals: vals, seasons: seasons, grid: tj.grid || null, leagueMap: tj.league_map || null };

    // header
    const yrs = seasons.length ? k.sLabel(seasons[0].season) + ' to ' + k.sLabel(seasons[seasons.length - 1].season) : (info.first ? k.sLabel(info.first) + ' to ' + k.sLabel(info.last || '') : '');
    const shoots = c.shoots || c.catches;
    const sub = [pos0 ? '<span class="chip">' + k.esc(goalie ? 'Goaltender' : ({ C: 'Centre', L: 'Left wing', R: 'Right wing', D: 'Defence' })[String(pos0).toUpperCase()] || pos0) + '</span>' : '',
      team ? k.teamChip(team, S) + ' <span>' + k.esc(k.teamName(team)) + '</span>' : '', k.isNum(age) ? '<span>Age ' + k.num(age, 0) + '</span>' : '',
      shoots ? '<span>' + (goalie ? 'Catches ' : 'Shoots ') + k.esc(String(shoots).toUpperCase() === 'L' ? 'left' : String(shoots).toUpperCase() === 'R' ? 'right' : shoots) + '</span>' : '',
      c.height || c.weight ? '<span class="muted-inline">' + [c.height ? k.esc(fmtHeight(c.height)) : '', c.weight ? k.esc(c.weight) + ' lb' : ''].filter(Boolean).join(', ') + '</span>' : '',
      c.number || c.sweater ? '<span class="muted-inline">#' + k.esc(c.number || c.sweater) + '</span>' : '', yrs ? '<span class="muted-inline">' + k.esc(yrs) + '</span>' : ''].filter(Boolean).join(' ');
    const links = ['<a href="' + k.compareHref(pid, '') + k.sq(S) + '">Compare →</a>', team ? '<a href="' + k.teamHref(team, S) + '">' + k.esc(k.teamNick(team)) + ' →</a>' : '',
      '<a href="' + k.withQ(goalie ? '#/goalies' : '#/skaters', S, goalie ? {} : { p: group }) + '">All ' + (goalie ? 'goalies' : (group === 'D' ? 'defencemen' : 'forwards')) + ' →</a>'].filter(Boolean).join('');
    let h = k.head(k.esc(name), sub, links, k.esc(goalie ? 'G' : k.posLabel(pos0) || '?'), team ? k.teamColour(team) : null);
    h += tiles(ctx);
    if (cp && metrics.length) {
      h += '<div class="card"><div class="card-header">Percentiles <span class="card-sub" id="pp-sl-sub"></span><span class="gq-ctl">' +
        (goalie ? '' : k.toggle('pp-basis', [['pct_pos', group === 'D' ? 'Defencemen' : 'Forwards'], ['pct', 'League']], ST.basis)) + '</span></div><div class="gq-pad" id="pp-sl"></div></div>';
    }
    if (goalie) h += goalieCards();
    else h += skaterCards(ctx);
    h += '<div class="card"><div class="card-header">Game log <span class="card-sub">' + k.esc(k.sLabel(cur.season || S)) + ', every game played.</span></div><div id="pp-log"></div></div>';
    h += '<div class="card"><div class="card-header">Career <span class="card-sub">Every NHL season since the debut (the league\'s season totals); shot, on-ice and model columns start in 2009–10, when the play-by-play does' + (goalie ? '' : ' (shifts from 2010–11)') + '.</span></div><div id="pp-car-c" style="height:240px"></div><div id="pp-car"></div></div>';
    h += '<div class="grid-2"><div class="card"><div class="card-header">Projection <span class="card-sub">Rest of season and next season: each rate regressed towards the mean by its stabilisation point, with ageing; ranges are 10th–90th percentiles.</span></div><div id="pp-proj"></div></div>' +
      '<div class="card"><div class="card-header">Similar players <span class="card-sub">This season\'s nearest qualified ' + (goalie ? 'goalies' : 'skaters at the position') + ' on the percentile profile; 100 would be identical.</span></div><div id="pp-sim"></div></div></div>';
    el.innerHTML = h;
    k.setMeta(k.esc(name));
    if (cp && metrics.length) {
      const drawSl = () => {
        const pc = goalie ? (cp.pct || cp.pct_pos || {}) : ((ST.basis === 'pct_pos' ? (cp.pct_pos || cp.pct) : cp.pct) || {});
        // the catalogue's games floor: counts, GSAx, RAPM and value get a percentile only past it (rates have their own floors)
        const gpFloor = k.isNum(((cat.reference || {}).floors || {}).gp) ? Number(cat.reference.floors.gp) : null;
        const gp = k.gpOf(cp);
        const early = gpFloor !== null && k.isNum(gp) && gp < gpFloor;
        const floorNote = cp.qualified === false ? '<strong>Below the ice-time floor</strong>: values only, no percentiles. '
          : early ? '<strong>' + k.int(gp) + (gp === 1 ? ' game' : ' games') + ' played, below the sample floor</strong>: counting stats, ' + (goalie ? 'GSAx' : 'RAPM') + ' and value get percentiles from ' + k.int(gpFloor) + ' games, rates from their own floors (hover a metric); until then the values stand alone. ' : '';
        k.set('pp-sl', k.sliders(metrics, cp.values || {}, pc, { unit: goalie ? 'shots' : 'minutes', note: floorNote + 'Click a metric for its definition and stabilisation point.' }));
        k.set('pp-sl-sub', k.esc(k.sLabel(S)) + ' · against every qualified ' + (goalie ? 'goaltender' : (ST.basis === 'pct_pos' ? (group === 'D' ? 'defenceman' : 'forward') : 'skater')) + ' (100 = best).' +
          (early ? ' <strong>' + k.int(gp) + (gp === 1 ? ' game' : ' games') + ' played: below the sample floor</strong> (percentiles start at ' + k.int(gpFloor) + ' games; rates at their own floors), so values only for now.' : ''));
      };
      drawSl();
      k.wireToggle(el, 'pp-basis', v => { ST.basis = v; drawSl(); });
    }
    if (goalie) { goalieDanger(ctx); goalieTypes(ctx); workload(ctx); }
    else { shotsPanel(ctx); impact(ctx); onIce(ctx); edge(ctx); deployment(ctx); linemates(ctx); }
    gameLog(ctx);
    careerPanel(ctx);
    projection(ctx);
    similar(ctx);
  });
}

function flat(r) {
  if (!r || typeof r !== 'object') return {};
  const out = Object.assign({}, r);
  if (r.plus && typeof r.plus === 'object') Object.keys(r.plus).forEach(x => { out['plus_' + x] = r.plus[x]; });
  delete out.plus;
  ['values', 'stats', 'totals', 'advanced', 'onice', 'model', 'value_detail', 'regular'].forEach(x => { if (r[x] && typeof r[x] === 'object' && !Array.isArray(r[x])) Object.keys(r[x]).forEach(kk => { if (out[kk] === undefined || out[kk] === r[x]) out[kk] = r[x][kk]; }); });
  return out;
}
function ageOf(dob) {
  if (!dob) return null;
  const d = new Date(String(dob).slice(0, 10) + 'T12:00:00Z');
  if (isNaN(d.getTime())) return null;
  return (Date.now() - d.getTime()) / (365.25 * 86400000);
}
function fmtHeight(h) { const n = Number(h); if (K().isNum(n) && n > 50 && n < 90) return Math.floor(n / 12) + '\'' + (n % 12) + '"'; if (K().isNum(n) && n > 140 && n < 230) return n + ' cm'; return String(h); }

// ── tiles ──────────────────────────────────────────────────────────────────

function tiles(ctx) {
  const k = K(), v = ctx.vals, cp = ctx.cp || {}, pc = (ctx.goalie ? cp.pct : (ST.basis === 'pct_pos' ? cp.pct_pos : cp.pct)) || {};
  const T = ctx.goalie
    ? [['Games', ['gp', 'games'], 'int', ''], ['Save %', ['sv_pct', 'save_pct'], 'sv', 'all situations'], ['GSAx', ['gsax', /^gsax$/], 'signed1', 'goals saved above expected'], ['GSAx / 60', ['gsax60', /gsax.*60/], 'signed2', ''],
      ['xSv%', ['xsv_pct', /xsv/], 'sv', 'expected from the shots faced'], ['Quality starts', ['qs_pct', /qs_pct|quality/], 'pct', 'save % above the league median in the game'], ['GAA', ['gaa'], '2', 'goals against per 60']]
    : [['Games', ['gp', 'games'], 'int', ''], ['Goals', ['g', 'goals'], 'int', ''], ['Points', ['pts', 'points', 'p'], 'int', ''], ['TOI / game', ['toi_gp', 'toi_pg', /toi.*(gp|pg|game)/], 'toi', 'all situations'],
      ['ixG', ['ixg', /^ixg$|individual_xg/], '1', 'individual expected goals'], ['xGF%', ['xgf_pct', /xgf_?pct/], 'pct', '5 on 5, on ice'], ['Rink value', ['value', 'gar', 'war', /^(rink_)?value/], 'signed1', 'goals above replacement']];
  const out = T.map(t => {
    const key = k.pick(v, t[1]);
    const x = key ? v[key] : null;
    if (!k.isNum(x)) return '';
    const p = key ? pc[key] : null;
    return k.tile(t[0], k.fmtV(x, (ctx.meta[key] || {}).fmt || t[2]), (k.isNum(p) ? k.pill(p) + ' ' : '') + k.esc(t[3]));
  });
  return k.tiles(out);
}

// ── skater panels ──────────────────────────────────────────────────────────

function skaterCards(ctx) {
  return '<div class="card"><div class="card-header">Shots <span class="card-sub" id="pp-shot-sub">Where the unblocked shots come from.</span><span class="gq-ctl"><select id="pp-shot-str"></select>' + K().toggle('pp-shot-m', [['diff', 'v league'], ['raw', 'Raw rate']], ST.shots) + '</span></div>' +
    '<div class="grid-2 gf-shots"><div id="pp-shot-a" class="gf-rink"></div><div id="pp-shot-b" class="gf-rink"></div></div><div class="pg-note gq-note" id="pp-shot-n"></div></div>' +
    '<div class="grid-2"><div class="card"><div class="card-header">On-ice impact (RAPM) <span class="card-sub">Regularised adjusted plus-minus: the player\'s effect on expected goals for and against per 60 at 5 on 5, isolated from teammates, opponents, zone starts and score. Every qualified skater in grey; the cross is ±1 standard error.</span></div><div id="pp-rapm" class="gf-chart"></div><div class="pg-note gq-note" id="pp-rapm-n"></div></div>' +
    '<div class="card"><div class="card-header">Deployment <span class="card-sub">Where and against whom the player starts: zone starts, quality of competition and of teammates, ice time by strength.</span></div><div id="pp-dep"></div></div></div>' +
    '<div class="card"><div class="card-header">On ice by strength <span class="card-sub">Team rates per 60 with the player on the ice, score and venue adjusted where the label says so; xGF% = xGF / (xGF + xGA).</span></div><div id="pp-onice"></div></div>' +
    '<div class="grid-2"><div class="card"><div class="card-header">Skating and shot tracking <span class="card-sub">Skating and shot speed from the league\'s puck and player tracking, as the NHL publishes it: season aggregates only (2021–22 on), with the league\'s own percentiles where given.</span></div><div id="pp-edge"></div></div>' +
    '<div class="card"><div class="card-header">Linemates <span class="card-sub">Most frequent linemates at 5 on 5, with the pair\'s on-ice results together.</span></div><div id="pp-mates"></div></div></div>';
}

/* A grid in the catalogues' compact form ({grid: {x0, dx, nx, y0, dy, ny}, <layer>: [flat, row-major by y]}) -> {x, y, v}. */
function flatGrid(spec, arr) {
  const k = K();
  if (!spec || !Array.isArray(arr) || !k.isNum(spec.nx) || !k.isNum(spec.ny) || arr.length < spec.nx * spec.ny) return null;
  const xs = [], ys = [], v = [];
  for (let i = 0; i < spec.nx; i++) xs.push(spec.x0 + spec.dx * (i + 0.5));
  for (let j = 0; j < spec.ny; j++) { ys.push(spec.y0 + spec.dy * (j + 0.5)); v.push(arr.slice(j * spec.nx, (j + 1) * spec.nx).map(Number)); }
  return { x: xs, y: ys, v: v };
}
/* A matrix smoothed with a 3x3 binomial kernel (counts on a 5 ft grid are spiky). */
function smooth(v) {
  const W = [[1, 2, 1], [2, 4, 2], [1, 2, 1]];
  return v.map((row, j) => row.map((_, i) => { let s0 = 0, w0 = 0; for (let a = -1; a <= 1; a++) for (let b = -1; b <= 1; b++) { const r = v[j + a]; if (!r || r[i + b] === undefined || r[i + b] === null) continue; s0 += W[a + 1][b + 1] * r[i + b]; w0 += W[a + 1][b + 1]; } return w0 ? s0 / w0 : null; }));
}
/* The player's location profile: raw = unblocked attempts per 60 by cell; v league = his share of attempts from each cell minus the
 * league's share (percentage points), so the map shows where he shoots from, not how much. */
function shotGrids(ctx, sh) {
  const k = K();
  const spec = sh.grid && k.isNum(sh.grid.nx) ? sh.grid : null;
  if (!spec) return null;
  const att = flatGrid(spec, sh.att || sh.n || sh.v);
  if (!att) return null;
  const toi = k.first((ctx.cp || {}).toi, ctx.vals.toi);
  const per60 = toi ? 60 / toi : null;
  const tot = k.sum([].concat.apply([], att.v));
  const raw = { x: att.x, y: att.y, v: smooth(att.v.map(r => r.map(c => (per60 ? c * per60 : c)))) };
  let diff = null;
  const LM = ctx.leagueMap && ctx.grid && ctx.grid.nx === spec.nx && ctx.grid.ny === spec.ny ? flatGrid(ctx.grid, ctx.leagueMap.att60 || ctx.leagueMap.att) : null;
  if (LM && tot > 0) {
    const ltot = k.sum([].concat.apply([], LM.v));
    if (ltot > 0) diff = { x: att.x, y: att.y, v: smooth(att.v.map((r, j) => r.map((c, i) => 100 * (c / tot - LM.v[j][i] / ltot)))) };
  }
  return { raw: raw, diff: diff, per60: !!per60, n: tot };
}
function shotsPanel(ctx) {
  const k = K(), sh = ctx.cur.shots || {};
  const a = k.$('pp-shot-a'), b = k.$('pp-shot-b'), sel = k.$('pp-shot-str'), note = k.$('pp-shot-n');
  if (!a) return;
  if (sel) sel.style.display = 'none';
  const ptsRaw = sh.points || sh.shots || sh.list || null;
  const pts = k.shotsOf(ptsRaw, sh.point_cols || sh.cols_points);
  const G = shotGrids(ctx, sh);
  const generic = !G ? (sh.grid && !k.isNum((sh.grid || {}).nx) ? sh.grid : (sh.x && sh.y ? sh : null)) : null;
  if (!pts.length && !G && !generic) { a.parentNode.innerHTML = k.muted('No shot locations for this skater this season.'); return; }
  const drawHeat = () => {
    if (G) {
      if (ST.shots === 'raw' || !G.diff) k.shotHeatmap(a, G.raw, 'raw', { title: 'Unblocked attempts' + (G.per60 ? ' per 60' : '') + ' by area', label: G.per60 ? 'per 60' : 'attempts', fmt: '2' });
      else k.shotHeatmap(a, G.diff, 'diff', { rel: true, title: 'Share of attempts from each area v the league (pp)', label: 'pp', fmt: '1' });
    } else k.shotHeatmap(a, generic, ST.shots === 'raw' ? 'raw' : 'diff', { title: 'Unblocked shot rate', label: '', empty: 'No shot-rate grid for this skater yet.' });
  };
  drawHeat();
  k.shotMap(b, pts, { team: ctx.team, colour: k.teamColour(ctx.team), empty: 'No shots on file for this skater this season.' });
  const lim = pts.length >= 400 ? ' The map shows the latest 400 attempts.' : '';
  if (note) note.innerHTML = 'Attacking right; the goal line is 11 ft from the end boards. ' + (G ? 'The heatmap is ' + k.int(G.n) + ' unblocked attempts (all situations, regular season) on a 5 ft grid, lightly smoothed; against the league it is the share of the player\'s attempts from each area minus the league\'s share at 5 on 5 (red: more attempts from there than the league), so it shows where the player shoots from, not how much. ' : '') +
    'On the map, dots are sized by xG and filled dots are goals; the filters above it pick the strength and period.' + lim + ' Before 2023–24, NHL shot coordinates carry arena scorer bias and are arena-adjusted (see the <a href="#/methodology/limitations">limitations</a>).';
  k.wireToggle(document, 'pp-shot-m', v => { ST.shots = v; drawHeat(); });
}

/* RAPM: the player's {off, def, off_se, def_se} over every skater in the catalogue with RAPM values. */
function rapmOf(r) {
  const k = K();
  if (!r || typeof r !== 'object') return null;
  const off = k.first(r.off, r.offence, r.offense, r.xgf, r.xgf60, r.rapm_off, r.o);
  const defKey = ['def', 'defence', 'defense', 'rapm_def', 'd'].find(x => k.isNum(r[x]));
  const xga = k.first(r.xga, r.xga60);
  let def = defKey ? Number(r[defKey]) : null, inverted = false;
  if (!k.isNum(def) && k.isNum(xga)) { def = -xga; inverted = true; }
  return { off: off, def: def, offSe: k.first(r.off_se, r.se_off, r.offence_se, r.xgf_se), defSe: k.first(r.def_se, r.se_def, r.defence_se, r.xga_se), net: k.first(r.net, r.total), inverted: inverted, strength: r.strength || '5v5', seasons: r.seasons || r.window, raw: r };
}
function impact(ctx) {
  const k = K(), node = k.$('pp-rapm'), note = k.$('pp-rapm-n');
  if (!node) return;
  const me = rapmOf(ctx.cur.rapm);
  const ms = ctx.cat ? k.allMetrics(ctx.cat) : [];
  const oK = k.pick(ms, ['rapm_off', 'rapm_xgf', /rapm.*(off|xgf)|(off|xgf).*rapm/]), dK = k.pick(ms, ['rapm_def', 'rapm_xga', /rapm.*(def|xga)|(def|xga).*rapm/]);
  const dLower = dK && (ctx.meta[dK] || {}).lower || (dK && /xga/.test(dK) && !/def/.test(dK));
  const P = (ctx.cat || {}).players || {};
  const others = Object.keys(P).filter(id => id !== ctx.pid && P[id].qualified !== false && k.isNum(((P[id].values || {})[oK])) && k.isNum(((P[id].values || {})[dK])));
  const myO = me && k.isNum(me.off) ? me.off : (oK ? ctx.vals[oK] : null);
  let myD = me && k.isNum(me.def) ? me.def : (dK ? ctx.vals[dK] : null);
  if (!(me && k.isNum(me.def)) && dLower && k.isNum(myD)) myD = -myD;
  if (!k.isNum(myO) || !k.isNum(myD)) { k.empty(node, 'No RAPM estimate for this skater yet (it needs enough 5-on-5 shifts).'); if (note) note.innerHTML = ''; return; }
  const pts = others.map(id => ({ id: id, x: P[id].values[oK], y: dLower ? -P[id].values[dK] : P[id].values[dK], g: (P[id].group || k.groupOf(P[id].pos)) }));
  const mine = { id: ctx.pid, name: ctx.name, x: myO, y: myD, xse: me ? me.offSe : null, yse: me ? me.defSe : null };
  drawImpact(node, pts, mine, ctx);   // our own quadrant: the shell's impactChart has no standard-error cross
  const same = pts.filter(p => p.g === ctx.group);
  const pOf = (arr, v) => (arr.length ? 100 * arr.filter(x => x < v).length / arr.length : null);
  const po = pOf(same.map(p => p.x), myO), pd = pOf(same.map(p => p.y), myD);
  const sig = (v, se) => (k.isNum(se) && se > 0 ? Math.abs(v) / se : null);
  const so = sig(myO, mine.xse), sd = sig(myD, mine.yse);
  if (note) note.innerHTML = 'Offence ' + k.signed(myO, 3) + (k.isNum(mine.xse) ? ' ± ' + k.num(mine.xse, 3) : '') + ', defence ' + k.signed(myD, 3) + (k.isNum(mine.yse) ? ' ± ' + k.num(mine.yse, 3) : '') + ' expected goals per 60 against an average skater' +
    (k.isNum(po) && same.length > 10 ? ' (' + k.ordinal(po) + ' and ' + k.ordinal(pd) + ' percentile among ' + (ctx.group === 'D' ? 'defencemen' : 'forwards') + ')' : '') + '. ' +
    (k.isNum(so) && k.isNum(sd) ? (so < 1 && sd < 1 ? 'Both are within one standard error of zero: on this sample the player is <strong>indistinguishable from average</strong> at either end. ' : (so >= 2 || sd >= 2 ? 'At least one is two or more standard errors from zero. ' : 'Neither is two standard errors from zero, so read them as leanings, not verdicts. ')) : '') +
    'Defence is shown so that up is better (fewer expected goals against). ' + (me && me.seasons ? 'Window: ' + k.esc(Array.isArray(me.seasons) ? me.seasons.map(k.sLabel).join(', ') : me.seasons) + '. ' : '') + '<a href="#/methodology/rapm">How RAPM is fitted →</a>';
}
function drawImpact(node, pts, me, ctx) {
  const k = K();
  const tr = [{ type: 'scatter', mode: 'markers', name: 'Skaters', x: pts.map(p => p.x), y: pts.map(p => p.y), customdata: pts.map(p => k.playerHref(p.id, ctx.S)), text: pts.map(p => k.esc(k.name(p.id))), hovertemplate: '%{text}<br>offence %{x:+.3f}, defence %{y:+.3f}<extra></extra>', marker: { size: 5, color: pts.map(p => (p.g === ctx.group ? 'rgba(139,148,158,0.55)' : 'rgba(110,118,129,0.25)')) } },
    { type: 'scatter', mode: 'markers+text', name: ctx.name, x: [me.x], y: [me.y], text: [k.esc(k.surname(ctx.name))], textposition: 'top center', textfont: { color: '#e6edf3', size: 11 },
      error_x: k.isNum(me.xse) ? { type: 'constant', value: me.xse, color: k.teamColour(ctx.team), thickness: 1.5, width: 3 } : undefined,
      error_y: k.isNum(me.yse) ? { type: 'constant', value: me.yse, color: k.teamColour(ctx.team), thickness: 1.5, width: 3 } : undefined,
      marker: { size: 13, color: k.teamColour(ctx.team), line: { color: '#0d1117', width: 1.5 } }, hovertemplate: k.esc(ctx.name) + '<br>offence %{x:+.3f}, defence %{y:+.3f}<extra></extra>' }];
  const xs = pts.map(p => p.x).concat([me.x]), ys = pts.map(p => p.y).concat([me.y]);
  const rx = Math.max.apply(null, xs.map(Math.abs).concat([Math.abs(me.x) + (me.xse || 0)])) * 1.1 || 0.5, ry = Math.max.apply(null, ys.map(Math.abs).concat([Math.abs(me.y) + (me.yse || 0)])) * 1.1 || 0.5;
  const ann = [['Good at both', 1, 1], ['Offence only', 1, -1], ['Defence only', -1, 1], ['Neither', -1, -1]].map(a => ({ x: a[1] * rx * 0.95, y: a[2] * ry * 0.95, text: a[0], showarrow: false, font: { size: 10, color: '#6e7681' }, xanchor: a[1] > 0 ? 'right' : 'left' }));
  k.plot(node, tr, k.layout({ margin: { l: 56, r: 10, t: 10, b: 44 }, annotations: ann, xaxis: { title: 'Offence: xGF/60 added', range: [-rx, rx], zeroline: true, zerolinecolor: '#6e7681' }, yaxis: { title: 'Defence: xGA/60 prevented', range: [-ry, ry], zeroline: true, zerolinecolor: '#6e7681' } }));
  k.clickThrough(node);
}

function onIce(ctx) {
  const k = K(), host = k.$('pp-onice');
  if (!host) return;
  const oi = ctx.cur.onice || ctx.cur.on_ice;
  let rows = [];
  if (Array.isArray(oi) || (oi && oi.cols)) rows = k.listOf(oi).map(r => Object.assign({ s: r.strength || r.state || r.situation || r.name || '' }, r));
  else if (oi && typeof oi === 'object') {
    const nested = Object.keys(oi).filter(s0 => s0 !== 'pct' && oi[s0] && typeof oi[s0] === 'object' && !Array.isArray(oi[s0]));
    if (nested.length) rows = nested.map(s0 => Object.assign({ s: s0 }, oi[s0]));
    else rows = [Object.assign({ s: '5v5' }, oi)];   // the career file's flat 5v5 block
  }
  rows = rows.filter(r => Object.keys(r).some(x => x !== 's' && x !== 'pct' && k.isNum(r[x])));
  if (!rows.length) { host.innerHTML = k.muted('On-ice rates are not available for this skater yet (shift data starts in 2010–11).'); return; }
  const ORDER = ['5v5', 'ev', 'all', 'pp', '5v4', 'pk', '4v5', '4v4', '3v3'];
  rows.sort((a, b) => (ORDER.indexOf(String(a.s).toLowerCase()) < 0 ? 99 : ORDER.indexOf(String(a.s).toLowerCase())) - (ORDER.indexOf(String(b.s).toLowerCase()) < 0 ? 99 : ORDER.indexOf(String(b.s).toLowerCase())));
  const PREF = ['toi5', 'toi', 'cf60', 'ca60', 'cf_pct', 'xgf60', 'xga60', 'xgf_pct', 'adj_xgf60', 'adj_xga60', 'adj_xgf_pct', 'gf60', 'ga60', 'gf_pct', 'on_sh_pct', 'on_sv_pct', 'pdo', 'xgf_pct_rel', 'cf_pct_rel'];
  if (rows.length === 1) {
    // one strength: a fact grid with percentiles, grouped raw / adjusted / relative
    const r = rows[0], pc = r.pct || {};
    const keys = Object.keys(r).filter(x => x !== 's' && x !== 'pct' && k.isNum(r[x])).sort((a, b) => (PREF.indexOf(a) < 0 ? 99 : PREF.indexOf(a)) - (PREF.indexOf(b) < 0 ? 99 : PREF.indexOf(b)));
    host.innerHTML = '<div class="gq-cmp-facts gq-pad gf-facts">' + keys.map(x => { const v = r[x]; const good = /xgf_pct$|cf_pct$|gf_pct$/.test(x) && k.isNum(v) ? (v > 0.5 ? ' gq-ok' : v < 0.5 ? ' gq-no' : '') : '';
      return '<div class="gq-fact" title="' + k.esc(k.cleanDesc((ctx.meta[x] || {}).desc || '')) + '"><span>' + k.esc(label(x, ctx.meta)) + '</span><strong class="' + good + '">' + fv(x, v, ctx.meta) + '</strong>' + (k.isNum(pc[x]) ? ' ' + k.pill(pc[x]) : '') + '</div>'; }).join('') + '</div>' +
      '<div class="pg-note gq-note">5 on 5 with the player on the ice. Adjusted rates are score- and venue-adjusted; "rel" is on ice minus the team without the player. Pills are league percentiles among qualified skaters.</div>';
    return;
  }
  const keys = [];
  rows.forEach(r => Object.keys(r).forEach(x => { if (x !== 's' && x !== 'strength' && x !== 'pct' && k.isNum(r[x]) && keys.indexOf(x) < 0) keys.push(x); }));
  keys.sort((a, b) => (PREF.indexOf(a) < 0 ? 99 : PREF.indexOf(a)) - (PREF.indexOf(b) < 0 ? 99 : PREF.indexOf(b)));
  const cols = keys.slice(0, 16);
  host.innerHTML = k.table([{ label: 'Strength' }].concat(cols.map(c => ({ label: label(c, ctx.meta), align: 'right', title: (ctx.meta[c] || {}).desc || '' }))),
    rows.map(r => [{ v: r.s, html: '<strong>' + k.esc(strengthLabel(r.s)) + '</strong>' }].concat(cols.map(c => { const v = r[c]; const good = /xgf_pct|cf_pct|gf_pct/.test(c) && k.isNum(v) ? (v > 0.5 ? ' gq-ok' : v < 0.5 ? ' gq-no' : '') : '';
      return { v: v, html: '<span class="' + good + '">' + fv(c, v, ctx.meta) + '</span>' }; }))), { compact: true });
  k.sortable(host);
}

/* EDGE: the career file's flat block ({season, edge_max_speed, ...}) with percentiles from the catalogue when it carries the
 * same keys; or {key: {value, pct}}. */
function edge(ctx) {
  const k = K(), host = k.$('pp-edge');
  if (!host) return;
  const E = ctx.cur.edge;
  if (!E || typeof E !== 'object' || !Object.keys(E).length || E.ok === false) { host.innerHTML = k.muted('No tracking data for this skater (it covers 2021–22 on and is published as season aggregates).'); return; }
  const cpP = ctx.cp ? ((ST.basis === 'pct_pos' ? ctx.cp.pct_pos : ctx.cp.pct) || ctx.cp.pct || {}) : {};
  const P = E.pct || E.percentiles || E.percentile || {};
  const AVG = E.league || E.league_avg || E.avg || {};
  const items = [];
  Object.keys(E).forEach(x => {
    if (/^(pct|percentiles?|league|league_avg|avg|season|note|source|units?|updated_at)$/.test(x)) return;
    const v = E[x];
    if (k.isNum(v)) items.push({ key: x, v: Number(v), p: k.first(P[x], cpP[x]), avg: k.first(AVG[x]) });
    else if (v && typeof v === 'object' && k.isNum(k.first(v.value, v.v, v.max, v.avg))) items.push({ key: x, v: k.first(v.value, v.v, v.max, v.avg), p: k.first(v.pct, v.percentile, v.p, cpP[x]), avg: k.first(v.league, v.league_avg, v.avg_league) });
  });
  if (!items.length) { host.innerHTML = k.muted('No tracking figures for this skater.'); return; }
  const ORDER = ['edge_max_speed', 'max_speed', 'edge_bursts_22', 'edge_bursts_20', 'edge_distance60', 'edge_distance', 'edge_shot_speed', 'edge_avg_shot_speed', 'edge_oz_time'];
  items.sort((a, b) => (ORDER.indexOf(a.key) < 0 ? 99 : ORDER.indexOf(a.key)) - (ORDER.indexOf(b.key) < 0 ? 99 : ORDER.indexOf(b.key)));
  const val = i => (/speed/.test(i.key) ? k.num(i.v, 1) + ' mph' : /oz_time|pct/.test(i.key) ? k.pct(i.v, 1) : /distance60/.test(i.key) ? k.num(i.v, 2) + ' mi' : /distance/.test(i.key) ? k.num(i.v, 1) + ' mi' : k.int(i.v));
  const anyP = items.some(i => k.isNum(i.p));
  if (anyP) host.innerHTML = '<div class="gq-pad">' + items.map(i => k.slider(label(i.key, ctx.meta), i.p, val(i), (k.isNum(i.avg) ? 'League average ' + k.num(i.avg, 1) + '. ' : '') + k.cleanDesc((ctx.meta[i.key] || {}).desc || ''), '#/glossary/' + encodeURIComponent(i.key))).join('') + '</div>';
  else host.innerHTML = '<div class="gq-cmp-facts gq-pad">' + items.map(i => '<div class="gq-fact"><span>' + k.esc(label(i.key, ctx.meta)) + '</span><strong>' + val(i) + '</strong>' + (k.isNum(i.avg) ? '<span>league ' + k.num(i.avg, 1) + '</span>' : '') + '</div>').join('') + '</div>';
  host.innerHTML += '<div class="pg-note gq-note">NHL EDGE data as the NHL publishes it, for informational, non-commercial use: season aggregates only, so tracking never enters our play-level models. ' + (anyP ? 'Percentiles are among this season\'s qualified skaters in our catalogue (tracking values are not shrunk).' : '') + '</div>';
}

function deployment(ctx) {
  const k = K(), host = k.$('pp-dep');
  if (!host) return;
  const D = ctx.cur.deployment;
  if (!D || typeof D !== 'object' || !Object.keys(D).some(x => k.isNum(D[x]))) { host.innerHTML = k.muted('Deployment is not available for this skater yet (shift data starts in 2010–11).'); return; }
  const v = Object.assign({}, D, D.zone_starts || D.zones || {});
  const fr = x => (k.isNum(x) ? (Math.abs(x) > 1.5 ? x / 100 : Number(x)) : null);
  let h = '';
  const oz = fr(k.first(v.ozs_pct, v.oz_start_pct, v.oz_pct)), dz = fr(k.first(v.dzs_pct, v.dz_start_pct)), nz = fr(k.first(v.nzs_pct, v.nz_start_pct));
  if (k.isNum(oz)) {
    const z = k.isNum(dz) ? [oz, nz || 0, dz] : [oz, 0, 1 - oz];
    h += '<div class="gq-sub-head">5v5 faceoff starts, offensive against defensive zone</div><div class="gq-stack"><span style="width:' + (z[0] * 100).toFixed(1) + '%;background:#3fb950">OZ ' + k.pct(z[0], 0) + '</span>' +
      (z[1] > 0 ? '<span style="width:' + (z[1] * 100).toFixed(1) + '%;background:#8b949e">NZ ' + k.pct(z[1], 0) + '</span>' : '') + '<span style="width:' + (z[2] * 100).toFixed(1) + '%;background:#58a6ff">DZ ' + k.pct(z[2], 0) + '</span></div>' +
      '<div class="pg-note gq-note">Offensive-zone share of the 5v5 offensive and defensive faceoffs taken with the player on the ice' + (k.isNum(fr(v.dzs_share)) ? '; ' + k.pct(fr(v.dzs_share), 0) + ' of all the player\'s 5v5 on-ice faceoffs were in the defensive zone' : '') + '. Around 50% is neutral usage.</div>';
  }
  const F = [['toi_gp', 'TOI / game', 'mmss'], ['toi5_gp', '5v5 TOI / game', 'mmss'], ['toi_pp_gp', 'PP TOI / game', 'mmss'], ['toi_sh_gp', 'PK TOI / game', 'mmss'], ['toi_share', '5v5 share of team time', 'pct'],
    ['qoc_toi', 'Quality of competition (TOI)', 'mmss'], ['qot_toi', 'Quality of teammates (TOI)', 'mmss'], ['qoc_xgf', 'Quality of competition (xGF%)', 'pct'], ['qot_xgf', 'Quality of teammates (xGF%)', 'pct'],
    ['shift_len', 'Average shift', 'sec'], ['shifts_gp', 'Shifts / game', '1']];
  const facts = F.filter(f => k.isNum(v[f[0]])).map(f => '<div class="gq-fact" title="' + k.esc(k.cleanDesc((ctx.meta[f[0]] || {}).desc || '')) + '"><span>' + k.esc(f[1]) + '</span><strong>' +
    (f[2] === 'mmss' ? k.mmss(v[f[0]]) : f[2] === 'pct' ? k.pct(fr(v[f[0]]), 1) : f[2] === 'sec' ? k.num(v[f[0]], 0) + ' s' : k.num(v[f[0]], 1)) + '</strong></div>');
  if (facts.length) h += '<div class="gq-cmp-facts gq-pad">' + facts.join('') + '</div>';
  if (k.isNum(v.qoc_toi) || k.isNum(v.qoc_xgf)) h += '<div class="pg-note gq-note">Quality of competition and of teammates are time-weighted means over the skaters on the ice with the player at 5v5: their 5v5 minutes per game, or their on-ice xGF%. Differences between regulars are usually small.</div>';
  const S0 = v.by_strength || v.toi_by_strength;
  if (S0 && typeof S0 === 'object') h += rowsTable(S0, ctx.meta, { first: 'Strength', keyLabel: strengthLabel });
  host.innerHTML = h || k.muted('Deployment is not available for this skater yet.');
}

function linemates(ctx) {
  const k = K(), host = k.$('pp-mates');
  if (!host) return;
  const raw = ctx.cur.linemates;
  const rows = (Array.isArray(raw) ? raw : k.listOf(raw)).map(r => (Array.isArray(r)
    ? (typeof r[1] === 'string' || r[1] === null ? { pid: String(r[0]), name: r[1], toi: r[2], xgf_pct: r[3], gf: r[4], ga: r[5] } : { pid: String(r[0]), toi: r[1], xgf_pct: r[2] })
    : Object.assign({}, r, { pid: String(r.pid || r.id || r.player || '') }))).filter(r => r.pid);
  if (!rows.length) { host.innerHTML = k.muted('No linemates on file (shift data starts in 2010–11).'); return; }
  rows.forEach(r => { if (r.name) k.learn(r.pid, { name: r.name, pos: r.pos }); });
  rows.sort((a, b) => (k.first(b.toi, b.toi_5v5) || 0) - (k.first(a.toi, a.toi_5v5) || 0));
  const top = rows.slice(0, 12);
  const hasX = top.some(r => k.isNum(k.first(r.xgf_pct, r.xgf_share))), hasG = top.some(r => k.isNum(r.gf)), hasC = top.some(r => k.isNum(r.cf_pct));
  const maxT = Math.max.apply(null, top.map(r => k.first(r.toi, r.toi_5v5) || 0).concat([1]));
  host.innerHTML = k.table([{ label: 'With' }, { label: 'Pos' }, { label: '5v5 TOI together', align: 'right', title: 'Minutes at 5 on 5 with both on the ice' }, { label: '', sortable: false }]
    .concat(hasX ? [{ label: 'xGF%', align: 'right', title: 'Expected goals share with both on the ice' }] : []).concat(hasG ? [{ label: 'GF–GA', align: 'right' }] : []).concat(hasC ? [{ label: 'CF%', align: 'right' }] : []).concat([{ label: '', sortable: false }]),
    top.map(r => { const t = k.first(r.toi, r.toi_5v5), x = k.first(r.xgf_pct, r.xgf_share), cf = k.first(r.cf_pct);
      return { _href: k.playerHref(r.pid, ctx.S), cells: [{ v: r.name || k.name(r.pid), html: k.playerLink(r.pid, r.name, ctx.S) }, { v: r.pos || '', html: k.esc(k.posLabel(r.pos || (k.NAMES[r.pid] || {}).pos || '')) }, { v: t, html: k.isNum(t) ? k.int(t) : '—' },
        { v: t, html: '<span class="gf-hbar"><i style="left:0;width:' + (100 * (t || 0) / maxT).toFixed(1) + '%"></i></span>' }]
        .concat(hasX ? [{ v: x, html: k.isNum(x) ? '<span class="' + (x > 0.5 ? 'gq-ok' : x < 0.5 ? 'gq-no' : '') + '">' + k.pct(x, 1) + '</span>' : '—' }] : []).concat(hasG ? [{ v: k.isNum(r.gf) ? r.gf - r.ga : null, html: k.isNum(r.gf) ? k.int(r.gf) + '–' + k.int(r.ga) : '—' }] : []).concat(hasC ? [{ v: cf, html: k.isNum(cf) ? k.pct(cf, 1) : '—' }] : [])
        .concat([{ v: '', html: '<a class="gq-sim-cmp" href="' + k.compareHref(ctx.pid, r.pid) + k.sq(ctx.S) + '">compare</a>' }]) }; }), { compact: true });
  host.innerHTML += '<div class="pg-note gq-note">Minutes shared at 5 on 5 from the NHL\'s shift charts (any line combination containing both). On-ice results for a pair are noisy below a few hundred minutes; the <a href="' + k.withQ('#/lines', ctx.S, { team: ctx.team }) + '">lines page</a> shrinks full units towards their team.</div>';
}

// ── goalie panels ──────────────────────────────────────────────────────────

function goalieCards() {
  return '<div class="grid-2"><div class="card"><div class="card-header">GSAx by danger <span class="card-sub">Goals saved above expected on low-, medium- and high-danger shots, with the shots and expected goals behind each.</span></div><div id="pp-gdan" class="gf-chart"></div><div id="pp-gdan-t"></div></div>' +
    '<div class="card"><div class="card-header">By location <span class="card-sub">Where the goalie saved more (red) or fewer (blue) than expected, from the shooter\'s side: attacking right, the net on the right.</span></div><div id="pp-gloc" class="gf-rink"></div><div class="pg-note gq-note" id="pp-gloc-n"></div></div></div>' +
    '<div class="card"><div class="card-header">Save percentage by shot type <span class="card-sub">Actual against expected (from our xG on the same shots).</span></div><div class="grid-2"><div id="pp-gtype" class="gf-chart"></div><div id="pp-gtype-t"></div></div></div>' +
    '<div class="card"><div class="card-header">Workload <span class="card-sub">Starts, shots and expected goals faced, rest, and the season game by game.</span></div><div id="pp-gwork"></div><div id="pp-gwork-c" class="gf-chart"></div></div>';
}
/* Goalie blocks in current: gsax {by_danger|danger, by_type|shot_type|types, location|grid}, workload {...}; or flat keys in the catalogue. */
function gBlock(ctx) { const c = ctx.cur; return Object.assign({}, c.goalie || {}, c.gsax && typeof c.gsax === 'object' ? c.gsax : {}); }
function goalieDanger(ctx) {
  const k = K(), node = k.$('pp-gdan'), tab = k.$('pp-gdan-t');
  if (!node) return;
  const B = gBlock(ctx);
  let rows = [];
  const D = B.by_danger || B.danger || B.dangers;
  if (D) rows = k.listOf(D, 'band').map(r => ({ band: String(r.band || r.danger || r.name || ''), shots: k.first(r.shots, r.sa, r.n), ga: k.first(r.ga, r.goals), xg: k.first(r.xga, r.xg, r.xg_faced), gsax: k.first(r.gsax), sv: k.first(r.sv_pct), xsv: k.first(r.xsv_pct) }));
  else {
    [['low', 'Low'], ['med', 'Medium'], ['high', 'High']].forEach(d => { const g = K().first(ctx.vals['gsax_' + d[0]], ctx.vals[d[0] + '_gsax'], ctx.vals[d[0][0] + 'd_gsax']); if (k.isNum(g)) rows.push({ band: d[1], gsax: g, sv: k.first(ctx.vals[d[0][0] + 'd_sv_pct'], ctx.vals['sv_pct_' + d[0]]) }); });
  }
  rows = rows.filter(r => r.band && (k.isNum(r.gsax) || (k.isNum(r.xg) && k.isNum(r.ga))));
  rows.forEach(r => { if (!k.isNum(r.gsax)) r.gsax = r.xg - r.ga; });
  if (!rows.length) { k.empty(node, 'GSAx by danger is not available for this goalie yet.'); return; }
  const COL = b => (/hi|high/i.test(b) ? '#f85149' : /med|mid/i.test(b) ? '#d29922' : '#79c0ff');
  k.plot(node, [{ type: 'bar', x: rows.map(r => k.titleCase(r.band)), y: rows.map(r => r.gsax), marker: { color: rows.map(r => COL(r.band)) }, text: rows.map(r => k.signed(r.gsax, 1)), textposition: 'outside', hovertemplate: '%{x}: %{y:+.2f} GSAx<extra></extra>' }],
    k.layout({ margin: { l: 50, r: 10, t: 20, b: 34 }, yaxis: { title: 'GSAx', zeroline: true, zerolinecolor: '#8b949e' }, xaxis: { type: 'category', title: 'Shot danger' } }));
  if (tab) tab.innerHTML = k.table([{ label: 'Danger' }, { label: 'Shots', align: 'right' }, { label: 'xGA', align: 'right' }, { label: 'GA', align: 'right' }, { label: 'GSAx', align: 'right' }, { label: 'Sv%', align: 'right' }, { label: 'xSv%', align: 'right' }],
    rows.map(r => [{ v: r.band, html: '<strong>' + k.esc(k.titleCase(r.band)) + '</strong>' }, { v: r.shots, html: k.int(r.shots) }, { v: r.xg, html: k.num(r.xg, 1) }, { v: r.ga, html: k.int(r.ga) }, { v: r.gsax, html: '<span class="' + (r.gsax >= 0 ? 'gq-ok' : 'gq-no') + '">' + k.signed(r.gsax, 1) + '</span>' }, { v: r.sv, html: k.svp(r.sv) }, { v: r.xsv, html: k.svp(r.xsv) }]), { compact: true });
  locationGrid(ctx, B);
}
function locationGrid(ctx, B) {
  const k = K(), node = k.$('pp-gloc'), note = k.$('pp-gloc-n');
  if (!node) return;
  const sh = ctx.cur.shots || {};
  let G = B.location || B.grid || B.by_location || null;
  let n = null;
  if (!G && sh.grid && k.isNum(sh.grid.nx) && Array.isArray(sh.xg) && Array.isArray(sh.g)) {
    const xg = flatGrid(sh.grid, sh.xg), gl = flatGrid(sh.grid, sh.g);
    if (xg && gl) { G = { x: xg.x, y: xg.y, v: smooth(xg.v.map((r, j) => r.map((c, i) => c - gl.v[j][i]))) }; n = k.sum(sh.att || []); }
  }
  if (!G || !k.gridOf(G)) { k.empty(node, 'GSAx by location is not available for this goalie yet.'); return; }
  k.shotHeatmap(node, G, 'diff', { rel: true, title: 'Goals saved above expected by area', label: 'GSAx', fmt: 'signed', empty: 'GSAx by location is not available for this goalie yet.' });
  if (note) note.innerHTML = (n ? k.int(n) + ' unblocked attempts faced, ' : 'Unblocked attempts faced, ') + 'binned on a 5 ft grid by where they were taken (attacking right, the goalie\'s net on the right) and lightly smoothed: each area is expected goals minus goals allowed from there. Small areas carry few shots; read the broad pattern, not single cells. Pre-2020–21 coordinates were hand-recorded and are arena-adjusted.';
}

function goalieTypes(ctx) {
  const k = K(), node = k.$('pp-gtype'), tab = k.$('pp-gtype-t');
  if (!node) return;
  const B = gBlock(ctx);
  let rows = k.listOf(B.by_type || B.shot_type || B.types || B.by_shot_type, 'type').map(r => ({ type: String(r.type || r.shot_type || r.name || ''), shots: k.first(r.shots, r.sa, r.n), sv: k.first(r.sv_pct, r.sv), xsv: k.first(r.xsv_pct, r.xsv), gsax: k.first(r.gsax), ga: k.first(r.ga), xg: k.first(r.xga, r.xg) }));
  if (!rows.length) {
    const TY = ['wrist', 'snap', 'slap', 'back', 'backhand', 'tip', 'deflect', 'wrap'];
    TY.forEach(t => { const sv = k.first(ctx.vals['sv_pct_' + t], ctx.vals[t + '_sv_pct']), gs = k.first(ctx.vals['gsax_' + t], ctx.vals[t + '_gsax']); if (k.isNum(sv) || k.isNum(gs)) rows.push({ type: t, sv: sv, gsax: gs, xsv: k.first(ctx.vals['xsv_pct_' + t]) }); });
  }
  rows = rows.filter(r => r.type && (k.isNum(r.sv) || k.isNum(r.gsax)));
  rows.forEach(r => { if (!k.isNum(r.sv) && k.isNum(r.shots) && k.isNum(r.ga) && r.shots > 0) r.sv = 1 - r.ga / r.shots; if (!k.isNum(r.xsv) && k.isNum(r.shots) && k.isNum(r.xg) && r.shots > 0) r.xsv = 1 - r.xg / r.shots; });
  if (!rows.length) { k.empty(node, 'Splits by shot type are not available for this goalie yet.'); return; }
  rows.sort((a, b) => (b.shots || 0) - (a.shots || 0));
  const x = rows.map(r => k.titleCase(r.type));
  const tr = [];
  if (rows.some(r => k.isNum(r.sv))) tr.push({ type: 'bar', name: 'Save %', x: x, y: rows.map(r => r.sv), marker: { color: k.alpha(K().ACC, 0.8) }, hovertemplate: '%{x}: %{y:.3f}<extra>Save %</extra>' });
  if (rows.some(r => k.isNum(r.xsv))) tr.push({ type: 'scatter', mode: 'markers', name: 'Expected', x: x, y: rows.map(r => r.xsv), marker: { symbol: 'line-ew-open', size: 26, color: '#e6edf3', line: { width: 3, color: '#e6edf3' } }, hovertemplate: '%{x}: %{y:.3f}<extra>Expected</extra>' });
  const ys = rows.map(r => r.sv).concat(rows.map(r => r.xsv)).filter(k.isNum);
  if (tr.length) k.plot(node, tr, k.layout(Object.assign({ margin: { l: 50, r: 10, t: 30, b: 50 }, xaxis: { type: 'category', title: 'Shot type' }, yaxis: { title: 'Save %', tickformat: '.3f', range: [Math.max(0.5, Math.min.apply(null, ys) - 0.03), Math.min(1, Math.max.apply(null, ys) + 0.015)] } }, k.legendTop())));
  else k.empty(node, 'No save percentages by type.');
  if (tab) tab.innerHTML = k.table([{ label: 'Shot type' }, { label: 'Shots', align: 'right' }, { label: 'Sv%', align: 'right' }, { label: 'xSv%', align: 'right' }, { label: 'GSAx', align: 'right' }],
    rows.map(r => [{ v: r.type, html: '<strong>' + k.esc(k.titleCase(r.type)) + '</strong>' }, { v: r.shots, html: k.int(r.shots) }, { v: r.sv, html: k.svp(r.sv) }, { v: r.xsv, html: k.svp(r.xsv) }, { v: r.gsax, html: k.isNum(r.gsax) ? '<span class="' + (r.gsax >= 0 ? 'gq-ok' : 'gq-no') + '">' + k.signed(r.gsax, 1) + '</span>' : '—' }]), { compact: true });
}
function workload(ctx) {
  const k = K(), host = k.$('pp-gwork'), node = k.$('pp-gwork-c');
  if (!host) return;
  const W = Object.assign({}, ctx.cur.workload || gBlock(ctx).workload || {});
  const v = ctx.vals;
  const facts = [['Starts', k.first(W.starts, W.gs, v.gs, v.starts), 'int'], ['Shots faced', k.first(W.shots_faced, W.sa, v.shots_faced, v.sa), 'int'], ['Shots / 60', k.first(W.sa60, W.shots60, v.sa60), '2'], ['xG faced / 60', k.first(W.xga60, v.xga60), '2'],
    ['High-danger share', k.first(W.hd_share, W.high_danger_share, v.hd_share), 'pct'], ['Back-to-back starts', k.first(W.b2b, W.back_to_back, W.b2b_starts, v.b2b_starts, v.b2b), 'int'], ['Average rest', k.first(W.rest, W.avg_rest, v.rest), '1'], ['Team share of starts', k.first(W.start_share, v.start_share), 'pct']]
    .filter(f => k.isNum(f[1]));
  let h = facts.length ? '<div class="gq-cmp-facts gq-pad">' + facts.map(f => '<div class="gq-fact"><span>' + k.esc(f[0]) + '</span><strong>' + k.fmtV(f[1], f[2]) + (f[0] === 'Average rest' ? ' days' : '') + '</strong></div>').join('') + '</div>' : '';
  host.innerHTML = h || '';
  const log = k.listOf(ctx.cur.log).filter(r => k.isNum(k.first(r.gsax, r.sa, r.shots_faced)));
  if (log.length < 2) { if (node) k.empty(node, facts.length ? '' : 'Workload is not available for this goalie yet.'); return; }
  log.sort((a, b) => String(a.date || a.game_id).localeCompare(String(b.date || b.game_id)));
  let cum = 0;
  const xs = log.map((r, i) => r.date || i + 1);
  const cumY = log.map(r => { cum += k.first(r.gsax) || 0; return cum; });
  const tr = [{ type: 'bar', name: 'Shots faced', x: xs, y: log.map(r => k.first(r.sa, r.shots_faced, r.shots)), marker: { color: 'rgba(139,148,158,0.35)' }, yaxis: 'y2', hovertemplate: '%{x}: %{y} shots<extra></extra>' }];
  if (log.some(r => k.isNum(r.gsax))) tr.push({ type: 'scatter', mode: 'lines', name: 'Cumulative GSAx', x: xs, y: cumY, line: { color: K().ACC, width: 2.5 }, hovertemplate: '%{x}: %{y:+.1f} GSAx to date<extra></extra>' });
  k.plot(node, tr, k.layout(Object.assign({ margin: { l: 50, r: 50, t: 30, b: 40 }, xaxis: { title: log.every(r => r.date) ? 'Game date' : 'Game' }, yaxis: { title: 'Cumulative GSAx', zeroline: true, zerolinecolor: '#6e7681' }, yaxis2: { title: 'Shots', overlaying: 'y', side: 'right', showgrid: false, rangemode: 'tozero' } }, k.legendTop())));
}

/* A table of named rows: {rowKey: {metric: v}} or [{name|split|strength, ...}]. */
function rowsTable(obj, meta, opts) {
  const k = K(), o = opts || {};
  let rows = [];
  if (Array.isArray(obj)) rows = obj.map(r => ({ key: r.name || r.split || r.strength || r.key || r.label || r.id || '', v: r }));
  else if (obj && typeof obj === 'object' && (obj.cols || obj.fields) && obj.rows) rows = k.colRows(obj).map(r => ({ key: r.name || r.split || r.strength || r.key || '', v: r }));
  else if (obj && typeof obj === 'object') rows = Object.keys(obj).filter(x => obj[x] && typeof obj[x] === 'object' && !Array.isArray(obj[x])).map(x => ({ key: x, v: obj[x] }));
  if (!rows.length) return k.muted(o.empty || 'Not available yet.');
  const skip = /^(split|name|key|label|id|desc|note|strength)$/;
  const keys = [];
  rows.forEach(r => Object.keys(r.v).forEach(x => { if (!skip.test(x) && k.isNum(r.v[x]) && keys.indexOf(x) < 0) keys.push(x); }));
  const cols = keys.slice(0, o.max || 14);
  return k.table([{ label: o.first || 'Split' }].concat(cols.map(c => ({ label: label(c, meta), align: 'right', title: (meta && meta[c] && meta[c].desc) || '' }))),
    rows.map(r => [{ v: r.key, html: '<strong>' + k.esc(o.keyLabel ? o.keyLabel(r.key) : k.titleCase(r.key)) + '</strong>' }].concat(cols.map(c => ({ v: r.v[c], html: fv(c, r.v[c], meta) })))), { compact: true });
}

// ── log, career, projection, similar ───────────────────────────────────────

function gameLog(ctx) {
  const k = K(), host = document.getElementById('pp-log');
  if (!host) return;
  const raw = ctx.cur.log;
  const log = Array.isArray(raw) && raw.length && Array.isArray(raw[0]) && ctx.cur.log_cols ? k.colRows({ cols: ctx.cur.log_cols, rows: raw }) : k.listOf(raw);
  if (!log.length) { host.innerHTML = k.muted('No games logged this season yet.'); return; }
  const lead = ['date', 'opp', 'opponent', 'home', 'result', 'game_id', 'team', 'season', 'decision'];
  const ORDER = ctx.goalie ? ['toi', 'sa', 'shots_faced', 'sv', 'ga', 'sv_pct', 'xga', 'gsax', 'hd_sa', 'hd_ga'] : ['toi', 'g', 'a', 'pts', 'pm', 'shots', 'sog', 'ixg', 'icf', 'hits', 'blk', 'blocks', 'pim', 'toi_pp', 'toi_pk', 'cf_pct', 'xgf_pct', 'xgf', 'xga'];
  const keys = [];
  log.forEach(r => Object.keys(r).forEach(x => { if (lead.indexOf(x) < 0 && keys.indexOf(x) < 0 && k.isNum(r[x])) keys.push(x); }));
  keys.sort((a, b) => (ORDER.indexOf(a) < 0 ? 99 : ORDER.indexOf(a)) - (ORDER.indexOf(b) < 0 ? 99 : ORDER.indexOf(b)));
  const cols = keys.slice(0, 16);
  const S = ctx.S;
  const sorted = log.slice().sort((a, b) => String(a.date || a.game_id || '').localeCompare(String(b.date || b.game_id || '')));
  const hasDec = ctx.goalie && log.some(r => r.decision);
  host.innerHTML = k.table([{ label: 'Date' }, { label: 'Opp' }, { label: 'Result' }].concat(hasDec ? [{ label: 'Dec' }] : []).concat(cols.map(c => ({ label: label(c, ctx.meta), align: 'right', title: (ctx.meta[c] || {}).desc || '' }))),
    sorted.map(r => {
      const opp = r.opp || r.opponent || '';
      const at = r.home === false || r.home === 0 ? '@ ' : (r.home === true || r.home === 1 ? 'v ' : '');
      const gid = r.game_id || r.gid;
      const res = r.result || '';
      return [{ v: r.date || gid, html: '<strong>' + k.esc(r.date ? k.fmtDate(r.date, { year: false }) : (gid || '—')) + '</strong>' }, { v: opp, html: opp ? k.esc(at) + k.teamChip(opp, S) : '—' },
        { v: res, html: gid ? '<a href="' + k.gameHref(gid) + '">' + k.esc(res || 'Game') + '</a>' : k.esc(res || '—') }].concat(hasDec ? [{ v: r.decision || '', html: r.decision ? k.esc(r.decision) : '<span class="muted-inline" title="No decision: the goalie of record was the other one">—</span>' }] : [])
        .concat(cols.map(c => ({ v: r[c], html: c === 'toi' ? (r[c] < 100 ? k.mmss(r[c]) : k.mmss(r[c] / 60)) : fv(c, r[c], ctx.meta) })));
    }), { compact: true, sticky: true });
  k.sortable(host);
}

function careerPanel(ctx) {
  const k = K(), host = document.getElementById('pp-car'), chart = document.getElementById('pp-car-c');
  if (!host) return;
  const rows = ctx.seasons;
  if (!rows.length) { host.innerHTML = k.muted('No season lines on file yet.'); if (chart) chart.style.display = 'none'; return; }
  const order = ctx.goalie ? ['season', 'team', 'gp', 'gs', 'w', 'l', 'otl', 'sa', 'shots_faced', 'ga', 'sv_pct', 'gaa', 'so', 'xga', 'gsax', 'gsax60', 'gsax_high', 'sv_pct_high', 'xsv_pct', 'qs_pct', 'gar', 'war']
    : ['season', 'team', 'gp', 'g', 'a', 'p', 'pts', 'plus_minus', 'pm', 'pim', 'toi_gp', 'shots', 'sh_pct', 'ppp', 'ixg', 'xgf_pct', 'cf_pct', 'rapm_off', 'rapm_def', 'value', 'gar', 'war'];
  const present = order.filter(c => rows.some(r => r[c] !== undefined && r[c] !== null));
  const extra = [];
  rows.forEach(r => Object.keys(r).forEach(x => { if (present.indexOf(x) < 0 && extra.indexOf(x) < 0 && k.isNum(r[x]) && !/^(age|pid|id|playoffs?|season)$/.test(x)) extra.push(x); }));
  extra.sort((a, b) => (/^plus_/.test(a) ? 1 : 0) - (/^plus_/.test(b) ? 1 : 0));
  const all = present.concat(extra.slice(0, Math.max(0, 22 - present.length)));
  const sorted = rows.slice().sort((a, b) => a.season - b.season || String(a.team).localeCompare(String(b.team)));
  host.innerHTML = k.table(all.map(c => ({ label: label(c, ctx.meta), align: /season|team/.test(c) ? 'left' : 'right', title: (ctx.meta[c] || {}).desc || '' })),
    sorted.map(r => all.map(c => {
      const v = r[c];
      if (c === 'team') return { v: v, html: v ? (Array.isArray(v) ? v.map(t => k.teamChip(t, r.season)).join(' ') : String(v).split(/[\/,]/).map(t => k.teamChip(t.trim(), r.season)).join(' ')) : '—' };
      if (c === 'season') return { v: v, html: '<strong>' + k.esc(k.sLabel(v)) + '</strong>' };
      return { v: v, html: fv(c, v, ctx.meta) };
    })), { compact: true, sticky: true });
  k.sortable(host);
  if (!chart) return;
  const yk = ctx.goalie ? (sorted.some(r => k.isNum(r.gsax)) ? 'gsax' : 'sv_pct') : (sorted.some(r => k.isNum(r.p)) ? 'p' : sorted.some(r => k.isNum(r.pts)) ? 'pts' : 'g');
  const vk = k.pick(sorted.find(r => k.isNum(r.gar) || k.isNum(r.value)) || {}, ['gar', 'value', 'war']);
  // one point per season (sum across teams)
  const by = {};
  sorted.forEach(r => { const s = r.season; by[s] = by[s] || { s: s, y: 0, v: 0, gp: 0, n: 0, sv: [] }; if (k.isNum(r[yk])) { if (yk === 'sv_pct') by[s].sv.push([r[yk], r.gp || 1]); else by[s].y += Number(r[yk]); } if (vk && k.isNum(r[vk])) by[s].v += Number(r[vk]); by[s].gp += Number(r.gp || 0); by[s].n++; });
  const pts = Object.keys(by).map(Number).sort((a, b) => a - b).map(s => by[s]);
  if (pts.length < 2) { chart.style.display = 'none'; return; }
  pts.forEach(p => { if (yk === 'sv_pct') { const w = k.sum(p.sv.map(z => z[1])); p.y = w ? k.sum(p.sv.map(z => z[0] * z[1])) / w : null; } });
  const tr = [{ type: 'bar', name: label(yk, ctx.meta), x: pts.map(p => k.sLabel(p.s)), y: pts.map(p => p.y), marker: { color: pts.map(p => (yk === 'gsax' && p.y < 0 ? 'rgba(248,81,73,0.8)' : k.alpha(K().ACC, 0.85))) }, hovertemplate: '%{x}: %{y' + (yk === 'sv_pct' ? ':.3f' : yk === 'gsax' ? ':+.1f' : '') + '}<extra></extra>' }];
  if (vk) tr.push({ type: 'scatter', mode: 'lines+markers', name: label(vk, ctx.meta), x: pts.map(p => k.sLabel(p.s)), y: pts.map(p => p.v), yaxis: 'y2', line: { color: '#f97316', width: 2 }, hovertemplate: '%{x}: %{y:+.1f}<extra>' + k.esc(label(vk, ctx.meta)) + '</extra>' });
  k.plot(chart, tr, k.layout(Object.assign({ margin: { l: 48, r: 48, t: 30, b: 40 }, xaxis: { type: 'category', title: 'Season' }, yaxis: { title: label(yk, ctx.meta), zeroline: true }, yaxis2: { title: vk ? label(vk, ctx.meta) : '', overlaying: 'y', side: 'right', showgrid: false, zeroline: false } }, k.legendTop())));
}

function projection(ctx) {
  const k = K(), host = document.getElementById('pp-proj');
  if (!host) return;
  const pr = ctx.cur.projection || ctx.career.projection;
  if (RK.valuation && RK.valuation.playerLine) {
    RK.valuation.playerLine(ctx.pid).then(r => {
      if (!r || !host.isConnected) return;
      host.insertAdjacentHTML('beforeend', '<div class="pg-note gq-note"><strong>Multi-season valuation</strong>: ' + k.num(r.total, 1) + ' WAR over the rest of this season and the next three, discounted (10th–90th percentile ' + k.num(r.p10, 1) + ' to ' + k.num(r.p90, 1) + '); ' + k.num(r.now, 2) + ' this season, ' + k.num(r.next, 2) + ' next; ' + k.num(r.vorp, 1) + ' over replacement at that position. <a href="#/value?tab=val">Valuation →</a></div>');
    }, () => { /* no valuation payload */ });
  }
  if (!pr || typeof pr !== 'object' || pr.ok === false) { host.innerHTML = k.muted('No projection yet.'); return; }
  const blocks = [];
  const one = (obj, title) => {
    const keys = Object.keys(obj).filter(x => obj[x] && typeof obj[x] === 'object' && !Array.isArray(obj[x]) && [obj[x].p50, obj[x].mean, obj[x].proj, obj[x].value].some(k.isNum));
    const flatKeys = Object.keys(obj).filter(x => k.isNum(obj[x]) && !/^(season|n|games_left|gp_left|age)$/.test(x));
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
  if (!blocks.length) blocks.push(one(pr, pr.season ? k.sLabel(pr.season) + ' projection' : ''));
  const html = blocks.filter(Boolean).join('');
  host.innerHTML = (html || k.muted('No projection yet.')) + (pr.note ? '<div class="pg-note gq-note">' + k.esc(k.cleanDesc(pr.note)) + '</div>' : '');
}

function similar(ctx) {
  const k = K(), host = document.getElementById('pp-sim');
  if (!host) return;
  const list = ctx.career.similar || ctx.cur.similar || [];
  // the career file writes [pid, name, team, distance] (Euclidean on standardised headline metrics, lower is closer)
  const rows = (Array.isArray(list) ? list : []).map(r => (Array.isArray(r) ? (typeof r[1] === 'string' || r[1] === null ? { pid: String(r[0]), name: r[1], team: r[2], d: r[3] } : { pid: String(r[0]), d: r[1], season: r[2], name: r[3] }) : { pid: String(r.pid || r.id), d: k.first(r.distance, r.d), s: k.first(r.sim, r.score, r.similarity), season: r.season, name: r.name, team: r.team }));
  if (!rows.length) { host.innerHTML = k.muted('No similar players computed yet (it needs a qualified season).'); return; }
  rows.forEach(r => { if (r.name) k.learn(r.pid, { name: r.name }); });
  const ds = rows.map(r => r.d).filter(k.isNum), dmax = ds.length ? Math.max.apply(null, ds) * 1.25 : 1;
  host.innerHTML = '<div class="gq-sim">' + rows.slice(0, 10).map(r => {
    const w = k.isNum(r.d) ? 100 * (1 - r.d / dmax) : (k.isNum(r.s) ? (r.s <= 1 ? 100 * r.s : r.s) : 0);
    const sv = k.sid(r.season);
    return '<div class="gq-sim-row"><span><a href="' + k.playerHref(r.pid, sv || ctx.S) + '">' + k.esc(r.name || k.name(r.pid)) + '</a>' + (r.team ? ' ' + k.teamChip(r.team, ctx.S) : '') + (sv ? ' <span class="muted-inline">' + k.esc(k.sLabel(sv)) + '</span>' : '') + '</span>' +
      '<span class="gq-sim-bar"><span style="width:' + Math.max(4, Math.min(100, w)).toFixed(0) + '%"></span></span><span class="gq-sim-v" title="' + (k.isNum(r.d) ? 'Distance in standard deviations over the profile metrics (lower is closer)' : 'Similarity (higher is closer)') + '">' + (k.isNum(r.d) ? k.num(r.d, 2) : k.isNum(r.s) ? k.num(r.s <= 1 ? r.s * 100 : r.s, 0) : '') + '</span>' +
      '<a class="gq-sim-cmp" href="' + k.compareHref(ctx.pid, r.pid) + k.sq(ctx.S) + '">compare</a></div>';
  }).join('') + '</div><div class="pg-note gq-note">' + (ctx.goalie ? 'Profile: save %, GSAx per 60, high- and low-danger save %, shot quality faced, rebounds and start share.' : 'Profile: points, ixG, attempts and on-ice xG for and against per 60, CF%, hits, blocks, ice time, zone starts, penalties drawn and shot distance.') + ' The number is the distance in standard deviations: lower is closer.</div>';
}

// ── shared with team, compare and others ───────────────────────────────────

(function (F) { F.playerLabel = label; F.guessFmt = guessFmt; F.fv = fv; F.rowsTable = rowsTable; F.flat = flat; F.strengthLabel = strengthLabel; F.rapmOf = rapmOf; })(RK.fk = RK.fk || {});

if (typeof RK.route === 'function') {
  [['player', render], ['#/player/<pid>', render]].forEach(r => { try { RK.route(r[0], r[1]); } catch (e) { /* bound */ } });
}
})(window.RK || (window.RK = {}));
