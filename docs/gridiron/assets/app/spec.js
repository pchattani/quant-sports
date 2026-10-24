/* The Quant Gridiron — the comparison spec (docs/METRICS_SPEC.md, NFL; docs/_design/metrics/nfl.json, inlined below as
 * the headline sets). One place for the peer groups, the minimums and the metric sets that the percentile card, the
 * catalogue, the leaders, the compare page and the distributions all read.
 *
 * Groups: QB, RB, WR and TE (separate pools), five defensive roles (outside pass rushers ED, interior linemen IDL, LB,
 * CB, S) and K and P; no offensive-line group (no individual blocking data). Defensive roles come from players.json
 * `role` when it lands, else value.json `pos` by player (the spec's interim rule), else the roster position.
 * Percentiles: QB, RB, K, P from players.json `pct`; WR and TE from `pct_pos` (within WR or TE); defenders from
 * `pct_role` when the payload carries it, otherwise ranked here among the qualified players of the role; value per
 * game from value.json `pct` (within the position). Metrics marked `style` describe how a player plays, not how well:
 * they are shown with no colour and no "better". A metric the payload does not carry yet uses the spec's fallback
 * (the season count over games). Rows below the minimum (`qualified` false) get no percentile. */
(function (GI) {
'use strict';

const isNum = GI.isNum;
/* [id, display, unit, lower (1 = lower is better), style, explanation, fallback count id (not in the payload yet),
 *  then from assets/qk/metrics/nfl.json once loaded (ready()): M50 (the sample at which the metric is half signal), its
 *  unit, and the year-to-year r] */
const SPEC = [{"id":"qb","code":"QB","name":"Quarterbacks","peer":"NFL quarterbacks","entity":"player","pos":["QB"],"fb":[],"min":"14 attempts per team game (238 over 17 games); percentiles also need 50 dropbacks (the payload's sample floor)","unit":"pass attempts","m":[["composite","QB composite","rating (100 = average, 10 = 1 SD)",0,0,"Our all-round passing grade: EPA per dropback, accuracy, sack avoidance and turnovers blended into a forecast of next season's EPA per dropback.",null],["epa_db","EPA per dropback","EPA/dropback",0,0,"Expected points added per dropback, counting sacks and scrambles.",null],["cpoe","CPOE","pp",0,0,"Completion percentage over expected: completions above what our model expects for those throws.",null],["sack_rate","Sack rate","%",1,0,"Sacks per dropback; the most quarterback-driven part of pass protection.",null],["int_rate","Interception rate","%",1,0,"Interceptions per pass attempt. Very noisy year to year: read it with the sample size.",null],["pressure_rate","Pressure rate","%",1,0,"Share of dropbacks under pressure (line, play design and the quarterback's own hold time).",null],["adot","Average depth of target","yds",0,1,"Air yards per attempt: how far downfield the passes go (style, not quality).",null],["ttt","Time to throw","sec",1,1,"Next Gen Stats average time from snap to throw (2016 onward).",null],["scramble_rate","Scramble rate","%",0,1,"Scrambles per dropback: how often the quarterback escapes and runs (style).",null]],"sec":["success","anya","gvar_pg","comp_pct","deep_rate","aggressiveness","twp_rate","epa_pressure","epa_clean","pa_rate","epa_play","value","pass_yds","pass_td"]},{"id":"rb","code":"RB","name":"Running backs","peer":"NFL running backs","entity":"player","pos":["RB"],"fb":[],"min":"6.25 carries per team game (106 over 17)","unit":"carries","m":[["gvar_pg","Value per game","points/game",0,0,"Gridiron Value above a replacement back per game: rushing and receiving combined (value.json).",null],["ryoe","Rush yards over expected","yds/carry",0,0,"Yards per carry beyond what our model expects from the blocking, box and down and distance.",null],["rush_success","Rush success rate","%",0,0,"Share of carries that gain expected points.",null],["explosive","Explosive run rate","%",0,0,"Share of carries gaining 10+ yards; the most stable rushing efficiency number.",null],["rush_epa","EPA per carry","EPA/carry",0,0,"Expected points added per designed run.",null],["stuff_rate","Stuff rate","%",1,0,"Share of carries stopped for no gain or a loss.",null],["target_share","Target share","%",0,0,"Share of the team's pass attempts thrown to the player in the games played: the role in the passing game.",null]],"sec":["ypc","rec_epa_tgt","box8","rush_yds","rush_td","rec_yds"]},{"id":"wr","code":"WR","name":"Wide receivers","peer":"NFL wide receivers","entity":"player","pos":["WR"],"fb":[],"min":"3 targets per team game (51 over 17)","unit":"targets","m":[["gvar_pg","Value per game","points/game",0,0,"Gridiron Value above a replacement receiver at the same position per game (value.json).",null],["yptpa","Yards per team pass attempt","yds",0,0,"Receiving yards per team pass attempt in the games played: a route-free stand-in for yards per route run.",null],["target_share","Target share","%",0,0,"Share of the team's pass attempts thrown to the player in the games played: how often the player earns the ball.",null],["rec_epa_tgt","EPA per target","EPA/target",0,0,"Expected points added per target: what the offence gains when the player is the target.",null],["croe","Catch rate over expected","%",0,0,"Catches above what our completion model expects for these targets (depth, coverage, pressure).",null],["yac_rec","YAC per reception","yds",0,0,"Yards after the catch per reception.",null],["adot","Average depth of target","yds",0,1,"Air yards per target: how far downfield the player is used (role and style).",null]],"sec":["yacoe","air_share","wopr","catch_rate","drop_rate","contested_rate","separation","cushion","yprr","tprr","rec_yds","rec_td","rec_epa"]},{"id":"te","code":"TE","name":"Tight ends","peer":"NFL tight ends","entity":"player","pos":["TE"],"fb":[],"min":"2 targets per team game (34 over 17)","unit":"targets","m":[["gvar_pg","Value per game","points/game",0,0,"Gridiron Value above a replacement receiver at the same position per game (value.json).",null],["yptpa","Yards per team pass attempt","yds",0,0,"Receiving yards per team pass attempt in the games played: a route-free stand-in for yards per route run.",null],["target_share","Target share","%",0,0,"Share of the team's pass attempts thrown to the player in the games played: how often the player earns the ball.",null],["rec_epa_tgt","EPA per target","EPA/target",0,0,"Expected points added per target: what the offence gains when the player is the target.",null],["croe","Catch rate over expected","%",0,0,"Catches above what our completion model expects for these targets (depth, coverage, pressure).",null],["yac_rec","YAC per reception","yds",0,0,"Yards after the catch per reception.",null],["adot","Average depth of target","yds",0,1,"Air yards per target: how far downfield the player is used (role and style).",null]],"sec":["yacoe","air_share","wopr","catch_rate","drop_rate","contested_rate","separation","cushion","yprr","tprr","rec_yds","rec_td","rec_epa"]},{"id":"edge","code":"ED","name":"Outside pass rushers","peer":"NFL outside pass rushers","entity":"player","pos":["EDGE"],"fb":["DE","EDGE"],"min":"payload: half the team's games and 2.5 tackles-equivalent per team game; measured on players with 300+ defensive snaps (175+ pass snaps for EDGE/IDL), prorated to 17 games","unit":"games","m":[["gvar_pg","Value per game","points/game",0,0,"Splash EPA above a replacement outside pass rusher per game (value.json): the expected points saved by sacks, takeaways, pass break-ups and tackles for loss.",null],["pressures_pg","Sacks + QB hits per game","per game",0,0,"Sacks and quarterback hits per game: the steadiest individual pass-rush number in the data.",null],["tfl_pg","Tackles for loss per game","per game",0,0,"Tackles behind the line per game.","tfl"],["tackles_pg","Tackles per game","per game",0,0,"Solo and assisted tackles per game (involvement, not quality).","tackles"],["ff_pg","Forced fumbles per game","per game",0,0,"Forced fumbles per game. Unstable (r about 0.2).","ff"],["pd_pg","Passes defensed per game","per game",0,0,"Passes broken up or intercepted per game (batted balls for linemen).","pd"]],"sec":["splash_pg","sacks_pg","pass_rush_rate","tfl_run","sacks","qb_hits","def_value"]},{"id":"idl","code":"IDL","name":"Interior linemen","peer":"NFL interior linemen","entity":"player","pos":["DL"],"fb":["DT","NT","DL"],"min":"as EDGE; the payload minimum leaves out 52% of snap-regular interior linemen (see payload changes)","unit":"games","m":[["gvar_pg","Value per game","points/game",0,0,"Splash EPA above a replacement interior lineman per game (value.json): the expected points saved by sacks, takeaways, pass break-ups and tackles for loss.",null],["pressures_pg","Sacks + QB hits per game","per game",0,0,"Sacks and quarterback hits per game: the steadiest individual pass-rush number in the data.",null],["tfl_pg","Tackles for loss per game","per game",0,0,"Tackles behind the line per game.","tfl"],["tackles_pg","Tackles per game","per game",0,0,"Solo and assisted tackles per game (involvement, not quality).","tackles"],["ff_pg","Forced fumbles per game","per game",0,0,"Forced fumbles per game. Unstable (r about 0.2).","ff"],["pd_pg","Passes defensed per game","per game",0,0,"Passes broken up or intercepted per game (batted balls for linemen).","pd"]],"sec":["splash_pg","sacks_pg","pass_rush_rate","tfl_run","sacks","qb_hits","def_value"]},{"id":"lb","code":"LB","name":"Linebackers","peer":"NFL linebackers","entity":"player","pos":["LB"],"fb":["ILB","MLB","LB","OLB"],"min":"as EDGE (300+ defensive snaps when measured)","unit":"games","m":[["gvar_pg","Value per game","points/game",0,0,"Splash EPA above a replacement linebacker per game (value.json).",null],["tackles_pg","Tackles per game","per game",0,0,"Solo and assisted tackles per game: the linebacker's workload and range.","tackles"],["tfl_pg","Tackles for loss per game","per game",0,0,"Tackles behind the line per game.","tfl"],["pressures_pg","Sacks + QB hits per game","per game",0,0,"Sacks and quarterback hits per game (blitzing).",null],["pd_pg","Passes defensed per game","per game",0,0,"Passes broken up or intercepted per game: the only coverage credit in the data.","pd"],["splash_pg","Splash plays per game","per game",0,0,"Sacks, takeaways, forced fumbles, pass break-ups and tackles for loss per game.",null]],"sec":["ints_pg","ff_pg","tackle_snap","tackles","sacks","def_value"]},{"id":"cb","code":"CB","name":"Cornerbacks","peer":"NFL cornerbacks","entity":"player","pos":["CB"],"fb":["CB","DB"],"min":"as LB","unit":"games","m":[["gvar_pg","Value per game","points/game",0,0,"Splash EPA above a replacement cornerback per game (value.json).",null],["pd_pg","Passes defensed per game","per game",0,0,"Passes broken up or intercepted per game: the best coverage signal in public data, and still weak.","pd"],["ints_pg","Interceptions per game","per game",0,0,"Interceptions per game. Mostly luck from one season to the next.","ints"],["tackles_pg","Tackles per game","per game",0,0,"Solo and assisted tackles per game (for corners, partly a sign of being thrown at).","tackles"],["tfl_pg","Tackles for loss per game","per game",0,0,"Tackles behind the line per game (run support and blitzes).","tfl"],["ff_pg","Forced fumbles per game","per game",0,0,"Forced fumbles per game.","ff"]],"sec":["splash_pg","pressures_pg","ball_cov","ints","pd","def_value"]},{"id":"s","code":"S","name":"Safeties","peer":"NFL safeties","entity":"player","pos":["S"],"fb":["S","SAF","FS","SS"],"min":"as LB","unit":"games","m":[["gvar_pg","Value per game","points/game",0,0,"Splash EPA above a replacement safety per game (value.json).",null],["tackles_pg","Tackles per game","per game",0,0,"Solo and assisted tackles per game: run support and last-line tackling.","tackles"],["pd_pg","Passes defensed per game","per game",0,0,"Passes broken up or intercepted per game: the best coverage signal in public data, and still weak.","pd"],["ints_pg","Interceptions per game","per game",0,0,"Interceptions per game. Mostly luck from one season to the next.","ints"],["tfl_pg","Tackles for loss per game","per game",0,0,"Tackles behind the line per game (run support and blitzes).","tfl"],["splash_pg","Splash plays per game","per game",0,0,"Sacks, takeaways, forced fumbles, pass break-ups and tackles for loss per game.",null]],"sec":["ff_pg","pressures_pg","ball_cov","ints","pd","def_value"]},{"id":"k","code":"K","name":"Kickers","peer":"NFL kickers","entity":"player","pos":["K"],"fb":[],"min":"0.8 field-goal attempts per team game (14 over 17)","unit":"FGA","m":[["fg_oe","Field goals over expected","FG",0,0,"Field goals made minus what our model expects from the distances and conditions faced (season total).",null],["fg_50_pct","50+ yard %","%",0,0,"Field goals of 50+ yards made per attempt.",null],["xp_pct","Extra point %","%",0,0,"Extra points made per attempt.",null],["avg_dist","Average attempt distance","yds",0,1,"Average distance of field-goal tries (how far the coach trusts the kicker).",null],["fg_50","50+ yard makes","FG",0,0,"Field goals of 50+ yards made.",null]],"sec":["fg_pct","pts_oe","fga"]},{"id":"p","code":"P","name":"Punters","peer":"NFL punters","entity":"player","pos":["P"],"fb":[],"min":"2 punts per team game (34 over 17)","unit":"punts","m":[["epa_punt","EPA per punt","EPA/punt",0,0,"Expected points gained for the punting team per punt (field position flipped, returns included).",null],["net","Net average","yds",0,0,"Punt distance less return yards and 20 yards for each touchback.",null],["gross","Gross average","yds",0,0,"Average punt distance (the most stable punting number).",null],["inside20","Inside the 20","%",0,0,"Share of punts downed or returned inside the 20.",null],["touchback_rate","Touchback rate","%",1,0,"Touchbacks per punt.",null]],"sec":["net_oe","punts"]},{"id":"team","code":"","name":"Teams: overall","peer":"the 32 NFL teams","entity":"team","pos":[],"fb":[],"min":"none; early-season values are noisy (offence EPA reaches r 0.5 between halves after about 6 games, defence after about 16)","unit":"games","m":[["rating","Team rating","points/game",0,0,"Points per game better than an average team on a neutral field (our team-strength model).",null],["off_rating","Offence rating","points/game",0,0,"Offensive points per game above average.",null],["def_rating","Defence rating","points/game",0,0,"Defensive points per game above average (positive = better).",null],["off_epa","Offence EPA per play","EPA/play",0,0,"Opponent-adjusted expected points added per offensive play.",null],["def_epa","Defence EPA per play","EPA/play",1,0,"Opponent-adjusted expected points allowed per play.",null],["st_epa_g","Special teams EPA per game","EPA/game",0,0,"Net expected points per game on kicks, punts and returns.",null]],"sec":[]},{"id":"team_offence","code":"","name":"Teams: offence","peer":"the 32 NFL teams","entity":"team","pos":[],"fb":[],"min":"none; early-season values are noisy (offence EPA reaches r 0.5 between halves after about 6 games, defence after about 16)","unit":"games","m":[["off_epa","EPA per play","EPA/play",0,0,"Opponent-adjusted expected points added per play.",null],["off_pass_epa","Pass EPA per dropback","EPA/dropback",0,0,"Opponent-adjusted EPA per dropback: the most stable and predictive unit number.",null],["off_rush_epa","Rush EPA per carry","EPA/carry",0,0,"Opponent-adjusted EPA per designed run.",null],["off_success","Success rate","%",0,0,"Share of plays that gain expected points.",null],["pressure_allowed","Pressure rate allowed","%",1,0,"Share of dropbacks under pressure (the offensive line and quarterback together).",null],["off_rating","Offence rating","points/game",0,0,"Offensive points per game above average (team-strength model).",null]],"sec":["proe_neutral","sec_per_play_neutral","plays_pg","motion_rate","go_rate_rec"]},{"id":"team_defence","code":"","name":"Teams: defence","peer":"the 32 NFL teams","entity":"team","pos":[],"fb":[],"min":"none; early-season values are noisy (offence EPA reaches r 0.5 between halves after about 6 games, defence after about 16)","unit":"games","m":[["def_epa","EPA per play allowed","EPA/play",1,0,"Opponent-adjusted expected points allowed per play.",null],["def_pass_epa","Pass EPA allowed","EPA/dropback",1,0,"Opponent-adjusted EPA allowed per dropback.",null],["def_rush_epa","Rush EPA allowed","EPA/carry",1,0,"Opponent-adjusted EPA allowed per designed run.",null],["def_success","Success rate allowed","%",1,0,"Share of opponent plays that gain expected points.",null],["pressure_rate_def","Pressure rate","%",0,0,"Share of opponent dropbacks pressured.",null],["def_rating","Defence rating","points/game",0,0,"Defensive points per game above average (team-strength model).",null]],"sec":["blitz_rate","man_rate","box_avg"]}];
const BY = {};
SPEC.forEach(g => { BY[g.id] = g; });
const PLAYER = SPEC.filter(g => g.entity === 'player');
const DEF = ['edge', 'idl', 'lb', 'cb', 's'];
const ROLE = { EDGE: 'edge', ED: 'edge', DL: 'idl', IDL: 'idl', LB: 'lb', CB: 'cb', S: 's' };
const POS_FB = { DE: 'edge', EDGE: 'edge', DT: 'idl', NT: 'idl', DL: 'idl', ILB: 'lb', MLB: 'lb', LB: 'lb', OLB: 'lb', CB: 'cb', DB: 'cb', S: 's', SAF: 's', FS: 's', SS: 's' };
const NOTE = {
  rb: 'Running-back efficiency barely repeats from one season to the next (r 0.18 to 0.26); the explosive-run rate is the steadiest.',
  k: 'Kicking is close to noise: field goals over expected repeat at about r 0.08 a season on about 29 attempts. Read these as small samples, mostly luck.',
  edge: 'Public data credits defenders only for splash plays (sacks, hits, tackles, passes defensed): there is no individual pressure or coverage charting.',
  idl: 'Public data credits defenders only for splash plays (sacks, hits, tackles, passes defensed): there is no individual pressure or coverage charting.',
  lb: 'Public data credits defenders only for splash plays; passes defensed are the only coverage credit.',
  cb: 'Coverage is passes defensed and interceptions only, and both repeat weakly from year to year (r 0.2 to 0.3).',
  s: 'Coverage is passes defensed and interceptions only; a safety\'s value per game barely repeats from one season to the next (r 0.14).'
};

/* A context for one season's catalogue (players.json) and value table (value.json): roles, value rows, members, cache. */
function ctx(cat, vraw) {
  if (!cat) return null;
  const key = vraw ? '_spv' : '_sp';
  if (cat[key]) return cat[key];
  const v = {};
  if (vraw && vraw.rows) GI.colRows(vraw).forEach(r => { if (r && r.pid) v[String(r.pid)] = r; });
  const c = { cat: cat, v: v, mem: {}, cp: {}, meta: GI.metaOf(GI.allMetrics(cat)) };
  cat[key] = c;
  return c;
}
/* The spec group of one catalogue row: a group object or null (offensive linemen, unknown roles). */
function groupOf(p, pid, c) {
  if (!p) return null;
  const g = GI.groupOf(p.pos, p.group);
  if (g === 'QB' || g === 'RB' || g === 'WR' || g === 'TE' || g === 'K' || g === 'P') return BY[g.toLowerCase()];
  if (g !== 'DEF') return null;
  const vr = c && pid ? c.v[String(pid)] : null;
  const r = ROLE[String(p.role || (vr && vr.pos) || '').toUpperCase()] || POS_FB[String(p.pos || '').toUpperCase()];
  return r ? BY[r] : null;
}
function members(c, gid) {
  if (!c) return [];
  if (c.mem[gid]) return c.mem[gid];
  const P = c.cat.players || {};
  c.mem[gid] = Object.keys(P).filter(id => { const g = groupOf(P[id], id, c); return g && g.id === gid; });
  return c.mem[gid];
}
/* The value of a spec metric for a row: payload field, value.json for value per game, or the count over games. */
function value(p, pid, m, c) {
  const id = m[0];
  if (id === 'gvar_pg') { const vr = c && c.v[String(pid)]; return vr && isNum(vr.gvar_pg) ? Number(vr.gvar_pg) : null; }
  const vals = (p && p.values) || {};
  if (isNum(vals[id])) return Number(vals[id]);
  if (m[6] && isNum(vals[m[6]]) && isNum(p.games) && p.games > 0) return Number(vals[m[6]]) / Number(p.games);
  return null;
}
/* The percentile a payload carries for this group's pool, or undefined when it has none for the pool. */
function payloadPct(p, pid, g, id, c) {
  if (id === 'gvar_pg') { const vr = c && c.v[String(pid)]; return vr && vr.q && isNum(vr.pct) ? Number(vr.pct) : (vr ? null : undefined); }
  /* kickers: FG over expected is a season total; its percentile is the per-attempt rate's (fg_oe_att, 9d6e9722) */
  if (g.id === 'k' && id === 'fg_oe' && p && p.pct && isNum(p.pct.fg_oe_att)) return p.pct.fg_oe_att;
  if (g.id === 'qb' || g.id === 'rb' || g.id === 'k' || g.id === 'p') return ((p && p.pct) || {})[id];
  if (g.id === 'wr' || g.id === 'te') return ((p && p.pct_pos) || {})[id];
  return p && p.pct_role ? p.pct_role[id] : undefined;
}
/* Percentile 0-100 (100 = best) against the group, qualified players only; null when there is none. */
function pct(p, pid, g, m, c) {
  if (!p || !g || p.qualified === false || m[4]) return null;
  const pp = payloadPct(p, pid, g, m[0], c);
  if (pp !== undefined) return isNum(pp) ? Number(pp) : null;
  if (!c) return null;
  const k = g.id + '|' + m[0];
  if (!c.cp[k]) {
    const out = {};
    const P = c.cat.players || {};
    const pool = members(c, g.id).filter(id => P[id].qualified !== false).map(id => [id, value(P[id], id, m, c)]).filter(x => isNum(x[1]));
    const ref = pool.map(x => x[1]).sort((a, b) => a - b), n = ref.length;
    if (n >= 5) pool.forEach(x => {
      let lo = 0, hi = 0;
      ref.forEach(y => { if (y < x[1]) lo++; if (y <= x[1]) hi++; });
      const r = (lo + 0.5 * Math.max(0, hi - lo - 1)) / (n - 1);
      out[x[0]] = Math.max(0, Math.min(100, Math.round(100 * (m[3] ? 1 - r : r))));
    });
    c.cp[k] = out;
  }
  return isNum(c.cp[k][String(pid)]) ? c.cp[k][String(pid)] : null;
}
/* Without a context (the player file alone): the payload's own pool where it matches the group, else none. */
function pctSync(p, g, id) {
  if (!p || !g || p.qualified === false || id === 'gvar_pg') return null;
  const m = g.m.find(x => x[0] === id);
  if (m && m[4]) return null;
  const v = payloadPct(p, null, g, id, null);
  return isNum(v) ? Number(v) : null;
}
function fmtOf(m, c) {
  const meta = c && c.meta ? c.meta[m[0]] : null;
  if (meta && meta.fmt) return meta.fmt;
  const u = String(m[2] || '');
  if (m[0] === 'gvar_pg' || u === 'points/game') return 'signed2';
  if (u === 'per game') return '2';
  if (u === '%') return 'pct';
  if (u === 'pp') return 'signed1';
  if (/^EPA/.test(u)) return 'signed3';
  if (u === 'yds/carry') return 'signed2';
  if (u === 'sec') return 'sec';
  if (u === 'FG') return m[0] === 'fg_oe' ? 'signed1' : 'int';
  if (u === 'yds') return '1';
  return '1';
}
function fmt(m, v, c) { return GI.fmtVal(v, fmtOf(m, c)); }
function headline(g) { return (g ? g.m : []).filter(m => !m[4]); }
function style(g) { return (g ? g.m : []).filter(m => m[4]); }
function sample(p, g) {
  const unit = { qb: [['att', 'attempts']], rb: [['carries', 'carries'], ['rush_att', 'carries']], wr: [['targets', 'targets']], te: [['targets', 'targets']], k: [['fga', 'FG attempts']], p: [['punts', 'punts']] }[g ? g.id : ''] || [];
  const v = (p && p.values) || {};
  const s = unit.find(u => isNum(v[u[0]]));
  return [isNum((p || {}).games) ? p.games + ' G' : '', s ? GI.int(v[s[0]]) + ' ' + s[1] : ''].filter(Boolean).join(' · ');
}
/* The shipped spec JSON (design_kit.py copies docs/_design/metrics/nfl.json to assets/qk/metrics/nfl.json): each
 * metric's reliability (M50 and its unit) for the early-sample markers. Loaded once, with the catalogue. */
let readyP = null;
function ready() {
  if (readyP) return readyP;
  readyP = Promise.all([fetch('assets/qk/metrics/nfl.json', { cache: 'no-cache' }).then(r => (r.ok ? r.json() : null)).catch(() => null), specReady()]).then(a => a[0]).then(j => {
    ((j && j.groups) || []).forEach(g => {
      const G = BY[g.id];
      if (!G) return;
      (g.metrics || []).forEach(m => { const t = G.m.find(x => x[0] === m.id); const rel = m.reliability || {}; if (t) { t[7] = isNum(rel.m50) ? Number(rel.m50) : null; t[8] = rel.m50_unit || null; t[9] = isNum(rel.yoy_r) ? Number(rel.yoy_r) : null; } });
    });
    return j;
  });
  return readyP;
}
/* The player's sample in the unit the metric's M50 is measured in (dropbacks are attempts plus sacks, from the sack
 * rate; a 50+ attempt count is not in the payload, so that metric is never marked). */
function sampleIn(p, unit) {
  const v = (p && p.values) || {};
  switch (unit) {
    case 'games': return isNum(p.games) ? Number(p.games) : null;
    case 'attempts': return isNum(v.att) ? Number(v.att) : null;
    case 'dropbacks': return isNum(v.att) ? Number(v.att) / (1 - (isNum(v.sack_rate) && v.sack_rate < 0.5 ? Number(v.sack_rate) : 0)) : null;
    case 'carries': return isNum(v.carries) ? Number(v.carries) : null;
    case 'targets': return isNum(v.targets) ? Number(v.targets) : null;
    case 'receptions': return isNum(v.rec) ? Number(v.rec) : null;
    case 'punts': return isNum(v.punts) ? Number(v.punts) : null;
    case 'FGA': return isNum(v.fga) ? Number(v.fga) : null;
    default: return null;
  }
}
/* Early: his sample is still short of the metric's M50, so the number is more noise than signal. */
function early(p, m) { if (!m || !isNum(m[7])) return false; const n = sampleIn(p, m[8]); return isNum(n) && n < m[7]; }
function m50Text(m) { return m && isNum(m[7]) ? 'Half signal at about ' + GI.int(m[7]) + ' ' + (m[8] || '') + ' (M50, our metrics study).' : ''; }
function minLine(g) {
  if (!g) return '';
  let t = String(g.min || '');
  if (/^as (EDGE|LB)/.test(t)) t = String(BY.edge.min || '');
  return t.replace(/^payload:\s*/, '').replace(/;.*$/, '').replace(/\s*\(.*$/, '');
}

/* ── our models (round 5): the spec's `our_models` registry through the kit's QK.spec (assets/qk/metrics/nfl.labels.json).
 * specReady() -> Promise of the catalogue; ours(id) -> { name, about } | null; oursTag(id, short) the cobalt "Our model" tag;
 * specLabel(id, fallback, entity) the spec's display name; headIds(code) the spec's headline ids for a lab / catalogue
 * group code (QB, RB, WR, TE, K, P, DEF = the five defensive roles, TEAM = team, offence, defence); orderOpts(items, sel)
 * a metric picker: "Our models", "Box score · headline", then the items' groups; tagHeads(host, { colKey: id }) the tag
 * on a QK.table head (kept through re-sorts); oursNote([[id, label]]) the cobalt strip naming the models. Once loaded,
 * every spec explanation of ours ends "Our model: <name>." (the tooltips of the cards, compare and tables). */
let CAT = null, specP = null;
function specReady() {
  if (specP) return specP;
  specP = window.QK && QK.spec ? QK.spec.load('nfl').then(c => {
    if (!c) return null;
    CAT = c;
    SPEC.forEach(g => g.m.forEach(m => { m[5] = String(m[5] || '').replace(/\s*\((?:[a-z_]+\.json|leaderboards)\)/g, ''); const o = c.ours(m[0]); if (o && String(m[5] || '').indexOf('Our model:') < 0) m[5] = (m[5] ? m[5] + ' ' : '') + 'Our model: ' + o.name + '.'; }));
    return c;
  }) : Promise.resolve(null);
  return specP;
}
specReady();
function ours(id) { return CAT ? CAT.ours(id) : null; }
function oursTag(id, short) { const o = ours(id); return o ? QK.ours({ short: !!short, model: o.name, about: o.about }) : ''; }
function specLabel(id, fallback, entity) { return CAT ? CAT.label(id, entity || 'player', fallback) : (fallback || id); }
const CODE_GROUPS = { QB: ['qb'], RB: ['rb'], WR: ['wr'], TE: ['te'], K: ['k'], P: ['p'], DEF: DEF, TEAM: ['team', 'team_offence', 'team_defence'] };
function headIds(code) {
  const out = [];
  (CODE_GROUPS[String(code || '').toUpperCase()] || [String(code || '').toLowerCase()]).forEach(gid => ((BY[gid] || {}).m || []).forEach(m => { if (out.indexOf(m[0]) < 0) out.push(m[0]); }));
  return out;
}
function orderOpts(items, sel, heads) {
  const esc = GI.esc, pos = k => { const i = (heads || []).indexOf(k); return i < 0 ? 999 : i; };
  const opt = x => '<option value="' + esc(x.it.key) + '"' + (x.it.key === sel ? ' selected' : '') + '>' + esc(x.it.label) + (x.it.lower ? ' ↓' : '') + '</option>';
  const L = (items || []).map((it, i) => ({ it: it, i: i }));
  const by = (a, b) => (pos(a.it.key) - pos(b.it.key)) || (a.i - b.i);
  const grp = (label, list) => (list.length ? '<optgroup label="' + esc(label) + '">' + list.map(opt).join('') + '</optgroup>' : '');
  const our = L.filter(x => ours(x.it.key)).sort(by), head = L.filter(x => !ours(x.it.key) && pos(x.it.key) < 999).sort(by), rest = L.filter(x => !ours(x.it.key) && pos(x.it.key) === 999);
  let h = grp('Our models', our) + grp('Box score · headline', head);
  const names = [];
  rest.forEach(x => { const g = x.it.group || 'More'; if (names.indexOf(g) < 0) names.push(g); });
  names.forEach(g => { h += grp('Box score · ' + g, rest.filter(x => (x.it.group || 'More') === g)); });
  return h;
}
function tagHeads(host, map) {
  if (!host) return;
  const apply = () => Object.keys(map || {}).forEach(col => {
    const tag = oursTag(map[col], true);
    if (!tag) return;
    host.querySelectorAll('th[data-k="' + col + '"]').forEach(th => { if (!th.querySelector('.qk-ours')) (th.querySelector('button') || th).insertAdjacentHTML('beforeend', tag); });
  });
  apply();
  if (host._oursObs) host._oursObs.disconnect();
  if (window.MutationObserver) { host._oursObs = new MutationObserver(apply); host._oursObs.observe(host, { childList: true, subtree: true }); }
}
function oursNote(pairs) {
  const seen = {}, parts = [];
  (pairs || []).forEach(p => {
    const o = ours(p[0]);
    if (!o || seen[p[0]]) return;
    seen[p[0]] = 1;
    const m = CAT ? CAT.metric(p[0], p[2] || 'player') : null;
    const lab = p[1] || specLabel(p[0], p[0]);
    const txt = String((m && m.explain) || o.about).replace(/\s*Our model:.*$/, '').replace(/\s*\((?:[a-z_]+\.json|leaderboards)\)/g, '');
    parts.push('<b>' + GI.esc(lab) + '</b>' + (o.name !== lab ? ' · ' + GI.esc(o.name) : '') + '. ' + GI.esc(txt));
  });
  return parts.length ? QK.oursExplain(parts.join(' ')) : '';
}

GI.SP = { SPEC: SPEC, BY: BY, PLAYER: PLAYER, DEF: DEF, NOTE: NOTE, ctx: ctx, groupOf: groupOf, members: members, value: value, pct: pct, pctSync: pctSync, fmtOf: fmtOf, fmt: fmt,
  headline: headline, style: style, sample: sample, minLine: minLine, ready: ready, early: early, sampleIn: sampleIn, m50Text: m50Text,
  specReady: specReady, ours: ours, oursTag: oursTag, specLabel: specLabel, headIds: headIds, orderOpts: orderOpts, tagHeads: tagHeads, oursNote: oursNote };
})(window.GI);
