/* The Quant Rink — the player page (#/player/<pid>), the kit v4 "Broadcast" reference player page (MIGRATION_V4.md).
 *
 * Top, as the concept: a crumb; the full-bleed team-colour hero (QK.playerHeader: the alternate colour on a diagonal,
 * the outlined number, the name in Bebas, chips) with the black strip of five numbers and "The short version"; the
 * LED percentile meters against the position group (the sample named, early metrics dashed, a ▼ for last season
 * from the player file's current.prev_pct_pos, else loaded lazily from last season's catalogue) with "How sure are
 * we?" under them, beside the tale of the tape against the closest match (chips switch between the matches; a link
 * opens all three in Compare) and one-line verdicts; what to watch tonight (the scoreboard bug, the bar and how the
 * clubs match up, QK.previewCard layout 'bug') beside the last game (the box score by period and the
 * expected-goals race from the game file); the game log (every game, the best night highlighted); game by game and
 * "Their type". Below, "More on the player": value tiles, where the player sits among peers, season by season,
 * career, shot map, splits, movement and value. Detail (?view=detail): the full pre-redesign player page.
 *
 * Reads data/players/<pid>.json, data/glossary.json (labels), <S>/skaters.json or goalies.json (position-pool
 * percentiles, the metric catalogue and the peer distribution), <S>/value.json and <S>/valuation.json (current),
 * <S>/season.json (records and ratings for the next game) and <S>/games/<id>.json (the last game). */
(function (RK) {
'use strict';

const U = RK.ui, esc = RK.esc, isNum = RK.isNum;
let LABELS = null;
function labels() {
  if (LABELS) return Promise.resolve(LABELS);
  return RK.load('glossary.json').then(g => {
    LABELS = { skater: {}, goalie: {} };
    ((g && g.groups) || []).forEach(gr => (gr.entries || []).forEach(e => { const k = e.kind === 'goalie' ? 'goalie' : 'skater'; if (!LABELS[k][e.key]) LABELS[k][e.key] = e; }));
    return LABELS;
  });
}

function fmtBy(meta, v) { return U.fmtBy(meta, v); }
function age(dob) { const d = RK.parseDate(dob); if (!d) return null; return Math.floor((Date.now() - d.getTime()) / (365.25 * 864e5)); }

function render(el, params, state) {
  const pid = String(params.id);
  const view = ((params.query || {}).view) === 'detail' ? 'detail' : 'overview';
  const S = RK.currentSeason();
  el.innerHTML = QK.skeleton('card', 1) + QK.skeleton('chart', 1);
  const kindGuess = (RK.player(pid) || {}).pos === 'G' ? 'goalies.json' : 'skaters.json';
  /* The player file carries current.pct_pos and current.peer (accuracy audit, 725fadad): then the 2.7 MB catalogue
     loads only when the peer distribution scrolls into view. Older files without them load the catalogue first. */
  return Promise.all([RK.loadPlayer(pid), labels(), RK.loadYear('value.json', S), RK.loadYear('valuation.json', S), U.moves(S)]).then(res0 => {
    const pf = res0[0], cc = pf && pf.current;
    const fileP = !!(cc && cc.pct_pos && Object.keys(cc.pct_pos).length && cc.peer);
    return (fileP ? Promise.resolve(null) : RK.loadYear(pf && (pf.kind === 'goalie' || pf.pos === 'G') ? 'goalies.json' : kindGuess, S)).then(cat0 => res0.slice(0, 4).concat([cat0, fileP, res0[4]]));
  }).then(res => {
    if (!U.alive(el)) return;
    const p = res[0];
    if (!p || !p.name) { el.innerHTML = U.secHead('players', RK.playerName(pid), 'No career file for this player yet.', null, null, 'NHL · Player') + U.card2('Not found', '', QK.empty('No player ' + pid, 'Try the search.')); return; }
    const goalie = p.kind === 'goalie' || p.pos === 'G';
    const LB = res[1][goalie ? 'goalie' : 'skater'] || {};
    const c = p.current || null;
    const seasons = (p.seasons || []).slice().sort((a, b) => a.season - b.season);
    const last = seasons[seasons.length - 1] || {};
    const team = (c && last.season === c.season ? last.team : null) || last.team || RK.player(pid).team;
    const vrow = U.rowsOf(RK.ok(res[2]) ? res[2] : null).find(r => String(r.id) === pid) || null;
    const vv = U.rowsOf(RK.ok(res[3]) ? res[3] : null).find(r => String(r.id) === pid) || null;
    const curTeam = vv ? vv.team : team;
    const lv = last.values || {};
    document.title = p.name + ' · ' + RK.SITE;
    const a = age(p.dob);
    const ht = isNum(p.height) ? Math.floor(p.height / 12) + '′' + (p.height % 12) + '″' : '';
    const fileP = res[5];
    let catP = res[4] && res[4].players ? res[4].players[pid] : null;
    let cat = catP ? res[4] : null;
    if (fileP) {
      const pr = c.peer || {};
      catP = { name: p.name, team: last.team, group: pr.group || (goalie ? 'G' : null), gp: lv.gp, toi: lv.toi, qualified: !!pr.qualified, values: Object.assign({}, lv), pct_pos: c.pct_pos, pct: c.pct || {}, peerN: pr.n };
      cat = { reference: { floors: { gp: pr.min_gp } }, players: null, metrics: [] };
    }
    const meta = U.metaMap(cat);
    Object.keys(LB).forEach(k2 => { if (!meta[k2]) meta[k2] = LB[k2]; });
    const group = catP ? (goalie ? 'G' : catP.group) : (goalie ? 'G' : null);
    const posName = goalie ? 'Goalie' : ({ C: 'Centre', L: 'Left wing', R: 'Right wing', D: 'Defence' }[p.pos] || p.pos);
    const stats = goalie ? [{ label: 'GP', value: isNum(lv.gp) ? lv.gp : '—' }, { label: 'Save %', value: isNum(lv.sv_pct) ? RK.fmtVal(lv.sv_pct, '3') : '—' }, { label: 'GSAx', value: U.signed(lv.gsax, 1) }, { label: 'Record', value: isNum(lv.w) ? lv.w + '-' + (lv.l || 0) + '-' + (lv.otl || 0) : '—' }]
      : [{ label: 'GP', value: isNum(lv.gp) ? lv.gp : '—' }, { label: 'Goals', value: isNum(lv.g) ? lv.g : '—' }, { label: 'Assists', value: isNum(lv.a) ? lv.a : '—' }, { label: 'Points', value: isNum(lv.p) ? lv.p : '—' }];
    const tc = curTeam ? U.tcol(curTeam) : 'var(--signal)';
    const lg = c && c.log ? U.rowsOf(c.log) : [];
    const gpNow = isNum(lv.gp) ? lv.gp : (catP && isNum(catP.gp) ? catP.gp : 0);
    const sur = RK.playerSurname(pid) || p.name;
    const pp = (catP && (catP.pct_pos || catP.pct)) || {};
    const SETS = U.SETS[group] || U.SETS.F;
    const peerShort = goalie ? 'goalies' : (U.PEER_SHORT[group] || 'skaters');
    const prevS = String(Number(S) - 10001);
    const prevSeason = seasons.filter(x => String(x.season) === prevS)[0] || null;
    const tagsH = [];
    if (catP && catP.qualified) tagsH.push(QK.tag('Qualified for percentiles', 'signal'));
    if (vv && Array.isArray(vv.inj) && vv.inj[0]) tagsH.push('<span class="qk-tag rk-inj">' + esc(vv.inj[0]) + '</span>');
    const mates = c && (c.linemates || []).length ? c.linemates.slice(0, 2).map(m => RK.playerSurname(m[0]) || QK.surname(m[1])) : [];
    const hero = QK.playerHeader({ name: p.name, number: p.number, pos: posName,
      kicker: (last.season ? RK.seasonLabel(last.season) : '') + (gpNow ? ' · ' + gpNow + ' game' + (gpNow === 1 ? '' : 's') + ' in' : ''),
      team: curTeam ? { name: RK.teamName(curTeam), abbr: RK.teamAbbr(curTeam), colour: RK.teamColourRaw(curTeam), alt: RK.teamAlt(curTeam), href: RK.teamHref(curTeam) } : null,
      meta: [p.shoots ? (goalie ? 'Catches ' : 'Shoots ') + (p.shoots === 'L' ? 'left' : p.shoots === 'R' ? 'right' : p.shoots) : null, a ? a + ' years old' : null,
        ht ? ht + (isNum(p.weight) ? ', ' + p.weight + ' lb' : '') : null, mates.length === 2 && !goalie ? 'Lines up with ' + mates[0] + ' and ' + mates[1] : null],
      tags: tagsH, strip: tileList(), short: shortVersion() });
    const tabs = [{ key: 'overview', label: 'Overview', href: RK.playerHref(pid) }, { key: 'detail', label: 'Detail: every metric, shot maps, game log, on-ice, comparisons', href: RK.playerHref(pid) + '?view=detail' }];
    const crumb = '<nav class="rk-crumb" aria-label="Breadcrumb"><a href="#/players">Hockey</a><span aria-hidden="true">›</span>' + (curTeam ? '<a href="' + esc(RK.teamHref(curTeam)) + '">' + esc(RK.teamName(curTeam)) + '</a><span aria-hidden="true">›</span>' : '') + esc(p.name) + '</nav>';
    /* v4 (Broadcast): the hero is the full-bleed team-colour diagonal with the black strip of five numbers and
       "The short version" under it (QK.playerHeader strip / short) */
    el.innerHTML = crumb + hero + '<div style="margin-top:var(--sp-6)">' + U.tabsHTML(tabs, view) + '</div><div id="pp-body"></div>';
    const body = el.querySelector('#pp-body');
    if (view === 'detail') return U.legacy('player', body, params, state);

    /* "The short version": what the numbers say, in plain English, from this season's percentiles */
    function lc(x) { return /^[A-Z][a-z]/.test(x) ? x.charAt(0).toLowerCase() + x.slice(1) : x; }
    function shortVersion() {
      if (!catP || !gpNow) return null;
      const rows = [];
      SETS.forEach(g => g[1].forEach(x => { const k = x[0]; if (isNum(pp[k]) && U.SPEC[k]) rows.push([k, pp[k], U.SPEC[k].label]); }));
      const top = rows.filter(r => r[1] >= 90).sort((x, y) => y[1] - x[1]).slice(0, 2);
      const low = rows.slice().sort((x, y) => x[1] - y[1])[0];
      let t;
      if (goalie) {
        const gsx = (c && c.goalie && isNum(c.goalie.gsax)) ? c.goalie.gsax : lv.gsax;
        t = sur + ' has ' + (isNum(gsx) ? (gsx >= 0 ? 'saved ' + U.f(gsx, 1) + ' goals more than' : 'let in ' + U.f(-gsx, 1) + ' goals more than') + ' an average goalie would on the same shots' : 'played') + ' in ' + gpNow + ' game' + (gpNow === 1 ? '' : 's') + '.';
      } else {
        const pace = c && c.projection && isNum(c.projection.pts_pace) ? Math.round(c.projection.pts_pace) : (gpNow >= 3 && isNum(lv.p) ? Math.round(lv.p / gpNow * 82) : null);
        t = sur + ' has ' + (isNum(lv.p) ? lv.p : 0) + ' point' + (lv.p === 1 ? '' : 's') + ' in ' + gpNow + ' game' + (gpNow === 1 ? '' : 's') + (gpNow >= 3 && isNum(pace) ? ', on pace for ' + pace : '') + '.';
      }
      if (top.length) t += ' In the top ' + Math.max(1, Math.round(100 - Math.min(top[0][1], top[top.length - 1][1]))) + '% of ' + peerShort + ' for ' + top.map(r => lc(r[2])).join(' and ') + '.';
      else if (rows.length) { const avg = rows.reduce((x, r) => x + r[1], 0) / rows.length; t += avg >= 60 ? ' Above the middle of the pack on most of the numbers that matter.' : avg >= 40 ? ' Around the middle of the pack among ' + peerShort + '.' : ' Below the middle of the pack among ' + peerShort + ' so far.'; }
      if (low && low[1] <= 30 && !(top[0] && top[0][0] === low[0])) t += ' The weak spot: ' + lc(low[2]) + ' sits in the ' + QK.ordinal(Math.round(low[1])) + ' percentile.';
      if (gpNow < 15) t += ' Early days, so read it lightly.';
      return t;
    }
    /* five tiles, each with its percentile against the position group where there is one (the hero's strip) */
    function tileList() {
      const v = lv;
      const lastP = prevSeason && prevSeason.values ? prevSeason.values.p : null;
      const t = goalie ? [
        { label: 'Games', value: isNum(v.gp) ? String(v.gp) : '—', sub: isNum(v.w) ? v.w + '–' + (v.l || 0) + '–' + (v.otl || 0) + ' record' : '' },
        { label: 'Save %', value: isNum(v.sv_pct) ? RK.fmtVal(v.sv_pct, '3') : '—', pctl: pp.sv_pct, sub: 'saves per shot on goal' },
        { label: 'Goals saved above expected', value: U.signed(v.gsax, 1), pctl: pp.gsax, signal: true, sub: 'against an average goalie, same shots' },
        { label: 'Per 100 shots', value: U.signed(v.gsax100, 2), pctl: pp.gsax100, sub: 'goals saved above expected' },
        { label: 'Quality starts', value: isNum(v.qs_pct) ? U.pct(v.qs_pct) : '—', pctl: pp.qs_pct, sub: 'starts above an average save %' }]
      : [
        { label: 'Points', value: isNum(v.p) ? String(v.p) : '—', pctl: pp.p, sub: 'in ' + gpNow + ' game' + (gpNow === 1 ? '' : 's') },
        { label: 'Goals', value: isNum(v.g) ? String(v.g) : '—', pctl: pp.g, sub: isNum(v.sog) ? 'on ' + v.sog + ' shots' : '' },
        { label: 'Assists', value: isNum(v.a) ? String(v.a) : '—', pctl: pp.a, sub: gpNow ? U.f(v.a / gpNow, 1) + ' a game' : '' },
        { label: 'Points pace', value: c && c.projection && isNum(c.projection.pts_pace) ? String(Math.round(c.projection.pts_pace)) : '—', signal: true, sub: 'over 82 games.' + (isNum(lastP) ? ' Last season: ' + lastP + '.' : ''), tip: 'This season’s points per game over a full 82-game season. Early in a season it swings a lot.' },
        { label: 'Ice time', value: isNum(v.toi_gp) ? U.f(v.toi_gp, 1) : '—', pctl: pp.toi_gp, sub: 'minutes a game' }];
      return t.map(x => Object.assign(x, { pctl: isNum(x.pctl) ? x.pctl : null }));
    }

    // value tiles (moved below the fold: "More on the player")
    const k = [];
    if (vrow) k.push({ label: 'Rink value this season', value: U.f(vrow.war, 2), unit: 'WAR', sub: U.f(vrow.gar, 1) + ' goals above replacement', pctl: isNum(vrow.pct_pos) ? vrow.pct_pos : null, signal: true, tip: 'Wins and goals above replacement, our model' });
    if (vv) k.push({ label: 'Four-season value', value: U.f(vv.total, 1), unit: 'WAR', sub: 'likely range ' + U.f(vv.p10, 1) + ' to ' + U.f(vv.p90, 1), tip: 'Discounted WAR over the rest of this season and the next three; the range is the 10th to 90th percentile' });
    if (c && c.onice && isNum(c.onice.xgf_pct)) k.push({ label: '5v5 expected-goals share', value: U.f(c.onice.xgf_pct * 100, 1), unit: '%', pctl: pp.xgf_pct, sub: isNum(c.onice.xgf_pct_rel) ? U.signed(c.onice.xgf_pct_rel * 100, 1) + ' pts relative to the team' : '', tip: 'Of the expected goals at 5v5 with this player on the ice, the share that went the team’s way' });
    if (c && c.rapm && isNum(c.rapm.rapm_net)) k.push({ label: 'On-ice impact (RAPM)', value: U.signed(c.rapm.rapm_net, 2), pctl: pp.rapm_net, sub: '± ' + U.f(c.rapm.rapm_net_se, 2) + ' xG per 60 (one standard error)', tip: 'Regularised adjusted plus-minus: the player’s on-ice expected-goal impact after teammates and opponents' });
    if (!goalie && c && c.game_model && isNum(c.game_model.xgd60)) {
      const gm = c.game_model;
      k.push({ label: 'Weight in the game model', value: U.signed(gm.xgd60, 3), unit: 'xG/60', sub: 'to the team' + (isNum(gm.share) ? ' · on the ice for ' + Math.round(gm.share * 100) + '% of 5v5 time' : ''),
        tip: 'How much this skater moves the team’s game forecasts: walk-forward RAPM (offence ' + U.signed(gm.o, 3) + ', defence ' + U.signed(gm.d, 3) + ' xG/60) times the share of 5v5 time the lineup gives this player' + (isNum(gm.toi5) ? ' (' + U.f(gm.toi5 / 60, 1) + ' min a game)' : '') + '.' });
    }
    if (goalie && c && c.goalie) { const gg = c.goalie; k.push({ label: 'High-danger save %', value: RK.fmtVal(gg.sv_pct_high, '3'), pctl: pp.sv_pct_high, sub: 'expected ' + RK.fmtVal(gg.xfsv_pct, '3') + ' overall' }); }

    const peerOf = () => (catP ? (catP.pct_pos ? (U.GROUP_NAME[group] || 'the same position') + (isNum(catP.peerN) ? ' (' + catP.peerN + ' qualified)' : '') : 'all NHL skaters') : '');
    /* last season's ring: the player file's current.prev_pct_pos / prev_peer (same peer group; c99a4ba9), else last
       season's catalogue (about 4 MB), loaded only when the rail scrolls into view */
    let prevPct = c && c.prev_pct_pos && Object.keys(c.prev_pct_pos).length ? c.prev_pct_pos : null, prevGp = prevPct ? ((c.prev_peer || {}).gp) : null;
    const pcardHTML = () => QK.pctRail({ id: 'pp-pcard', kicker: 'How they stack up', title: 'Percentiles: how the player ranks', peer: peerOf(), sample: catP ? U.sampleLine(catP, cat.reference, goalie) : '',
      groups: catP ? U.pctGroups(catP, meta, SETS, null, prevPct) : [], ringLabel: 'last season' + (isNum(prevGp) ? ' (' + prevGp + ' games)' : ''),
      note: goalie && catP ? U.goalieNote(catP) : '', emptyText: catP ? 'This player is short of the sample floors for this season.' : 'No current-season profile yet.' });

    /* How sure are we: when the numbers settle at this ice time (the spec's M50 samples, docs/METRICS_SPEC.md) */
    function settleLine() {
      if (goalie || !catP || !gpNow) return '';
      const at = id => { let r = null; SETS.forEach(g => g[1].forEach(x => { if (x[0] === id) r = x; })); return r; };
      const per = unit => (unit === '5v5 minutes' ? (isNum((catP.values || {}).toi5) ? catP.values.toi5 / gpNow : (c && c.deployment ? c.deployment.toi5_gp : null)) : (isNum(lv.toi_gp) ? lv.toi_gp : null));
      const games = id => { const x = at(id); if (!x || !isNum(x[1])) return null; const m = per(x[2]); return isNum(m) && m > 0 ? Math.round(x[1] / m) : null; };
      const a1 = games('p60'), a2 = games('icf60'), a3 = games('adj_xgf_pct');
      const parts = [];
      if (isNum(a1)) parts.push('points per hour settle after about <b>' + a1 + ' games</b>');
      if (isNum(a2)) parts.push('shot attempts per hour after <b>' + a2 + '</b>');
      if (isNum(a3)) parts.push('the team’s chance share with the player on the ice after about <b>' + a3 + '</b>');
      return parts.length ? 'At this ice time, ' + parts.join(', ').replace(/, ([^,]*)$/, ', and $1') + '.' : '';
    }
    const nickOf = ab => (U.nick ? U.nick(ab) : RK.teamName(ab));
    const small = gpNow < 30;
    const NUMW = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten'];
    const sampleWords = gpNow ? (small ? (gpNow < 11 ? NUMW[gpNow] : gpNow) + ' game' + (gpNow === 1 ? ' is' : 's is') + ' a small sample.' : gpNow + ' games: the picture is settling.') : 'No games yet this season.';
    /* v4: "How sure are we?" sits under the meters as the explain strip (skaters); goalies keep the explained card */
    const settleNote = '<b>How sure are we?</b> ' + esc(sampleWords) + ' ' + (settleLine() ? settleLine() + ' ' : '') +
      (prevPct ? 'The ▼ marks last season: rows that sit on it are the steady part of the profile; the ones far from it are the ones to watch.' : '');
    const sureCard = '<article class="qk-card cream"><div class="qk-card-body"><div class="qk-kicker">How sure are we?</div><h3 style="margin:8px 0 6px">' + esc(sampleWords.replace(/\.$/, '')) + '</h3>' +
      '<p style="margin:0;color:var(--ink-2);font-size:15px">' + (goalie ? 'Goalie numbers swing more than any other position: a single season is a small sample, and save percentage needs thousands of shots to settle.'
        : (small ? 'Scoring rates swing a lot early on. ' : '') + 'The ▼ on each meter is last season, where there was one.') + '</p>' +
      (settleLine() ? QK.note(settleLine()) : '') + '</div></article>';

    const gbg = lg.length ? U.card2(goalie ? 'Goals saved above expected in every game' : 'Points in every game this season', goalie ? 'Goals saved above expected in each game' : 'Goals and assists, game by game', U.chart('pp-gbg', 260, 'Game by game'), { right: '' }) : '';
    const sim = (p.similar || []).slice(0, 3);
    const typeCard = (sim.length || (c && (c.linemates || []).length)) ? '<article class="qk-card"><div class="qk-card-body"><div class="qk-kicker">Their type</div>' +
      (sim.length ? '<h4 class="rk-h4">Plays most like</h4><ul class="rk-list rk-type">' + sim.map(m => '<li>' + U.playerEnt(m[0], m[1], m[2]) + '<a class="v rk-link" href="' + RK.compareHref(pid, m[0]) + '">Compare</a></li>').join('') + '</ul>' : '') +
      (c && (c.linemates || []).length && !goalie ? '<h4 class="rk-h4">Most time with</h4><ul class="rk-list rk-type">' + c.linemates.slice(0, 2).map(m => '<li>' + U.playerEnt(m[0], m[1]) + '<span class="v">' + U.f(m[2], 0) + ' min together at 5-on-5</span></li>').join('') + '</ul>' : '') +
      '<div class="qk-aside" style="margin-top:10px">Closest match on this season’s profile: value, scoring, shooting, play-driving and ice time.</div></div></article>' : '';

    /* 1. the meters (7) beside the tale of the tape against the closest match (5), as the concept */
    const tape = sim.length >= 1 && !goalie;
    let h = '<section class="qk-section rk-sec1"><div class="qk-g75"><div>' + pcardHTML() + (goalie ? '' : QK.explain(settleNote, { cls: 'rk-settle' })) + '</div>' +
      '<div class="rk-stack">' + (tape ? '<div id="pp-tape-h"></div><div class="qk-chips rk-pick" id="pp-tape-pick" role="group" aria-label="Compare with"></div><div id="pp-tape">' + QK.skeleton('lines', 6) + '</div><div id="pp-verd"></div>'
        : sureCard + typeCard) + '</div></div></section>';

    /* 2. what to watch tonight (the scoreboard bug and the match-up) beside the last game (box score, xG race) */
    const idx = RK.index() || {};
    const teamGames = [].concat(idx.live || [], idx.today || [], idx.upcoming || []).filter(x => x && (x.home === curTeam || x.away === curTeam));
    const nxt = teamGames.filter(x => U.status(x) !== 'final').sort((x, y) => String(x.start).localeCompare(String(y.start)))[0];
    const lastG = lg.length ? lg[lg.length - 1] : null;
    const recent = (idx.recent || []).concat(idx.today || []).filter(x => x && lastG && String(x.game_id) === String(lastG.game_id))[0];
    if (nxt || lastG) {
      h += '<section class="qk-section"><div class="qk-g2">';
      if (nxt) {
        const live = U.status(nxt) === 'live';
        h += '<div>' + QK.sectionHead({ kicker: live ? 'Live now' : (QK.fmt.relDay(nxt.start) === 'Today' ? 'What to watch tonight' : 'Next up'), title: nickOf(nxt.away) + ' at ' + nickOf(nxt.home) }) + '<div id="pp-next">' + QK.skeleton('card', 1) + '</div></div>';
      }
      if (lastG) {
        const rs = String(lastG.result || ''), m = /(\d+)-(\d+)/.exec(rs), won = /^W/.test(rs);
        const ttl = m ? (won ? RK.teamAbbr(curTeam) + ' ' + m[1] + ', ' + RK.teamAbbr(lastG.opp) + ' ' + m[2] : RK.teamAbbr(lastG.opp) + ' ' + m[2] + ', ' + RK.teamAbbr(curTeam) + ' ' + m[1]) + (/OT|SO/.test(rs) ? ' (' + (/SO/.test(rs) ? 'SO' : 'OT') + ')' : '') : (lastG.home ? 'v ' : 'at ') + RK.teamName(lastG.opp);
        const line = goalie ? (isNum(lastG.gsax) ? U.signed(lastG.gsax, 2) + ' goals saved above expected' : '') : lastG.g + ' G, ' + lastG.a + ' A · ' + lastG.sog + ' shots · ' + U.f(lastG.ixg, 2) + ' expected goals · ' + U.f(lastG.toi, 1) + ' minutes';
        h += '<div>' + QK.sectionHead({ kicker: 'Last game', title: ttl }) + '<article class="qk-card"><div class="qk-card-body"><div id="pp-box">' + (recent ? U.gc(recent, null, null, true) : '') + '</div>' +
          (line ? '<p style="margin:12px 0 0;color:var(--ink-2);font-size:15px"><b style="color:var(--ink-1)">' + esc(sur) + ':</b> ' + esc(line) + (isNum(lastG.gs) ? ', game score ' + U.f(lastG.gs, 2) : '') + '.</p>' : '') +
          '<div id="pp-race"></div></div></article></div>';
      }
      h += '</div></section>';
    }

    /* 3. the game log: every game this season, the best night highlighted */
    if (lg.length && !goalie) {
      let bestI = -1, bestP = -1; lg.forEach((r, i) => { const pt = (r.g || 0) + (r.a || 0); if (pt >= bestP) { bestP = pt; bestI = i; } });
      const bestR = lg[bestI];
      h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'Game log', title: 'Every game this season', sub: bestR && bestP > 0 ? bestP + ' point' + (bestP === 1 ? '' : 's') + ' ' + (bestR.home ? 'against ' : 'at ') + RK.teamName(bestR.opp) + ' is the best night so far (highlighted).' : 'Every game this season, newest first.' }) +
        '<article class="qk-card"><div class="qk-card-body flush"><div class="qk-table-wrap"><table class="qk-table"><thead><tr><th>Date</th><th>Opp</th><th>Result</th><th class="num">G</th><th class="num">A</th><th class="num">Pts</th><th class="num">Shots</th><th class="num" data-tip="Expected goals from the player’s own shots">Exp. goals</th><th class="num">Minutes</th></tr></thead><tbody>' +
        lg.map((r, i) => [r, i]).reverse().map(x => { const r = x[0]; return '<tr' + (x[1] === bestI && bestP > 0 ? ' class="hl"' : '') + '><td>' + esc(RK.fmtDate(r.date, { year: false })) + '</td><td>' + (r.home ? 'v ' : '@ ') + esc(RK.teamAbbr(r.opp)) + '</td><td>' + esc(r.result || '') + '</td><td class="num">' + (r.g || 0) + '</td><td class="num">' + (r.a || 0) + '</td><td class="num"><b>' + ((r.g || 0) + (r.a || 0)) + '</b></td><td class="num">' + (isNum(r.sog) ? r.sog : '—') + '</td><td class="num">' + U.f(r.ixg, 2) + '</td><td class="num">' + U.f(r.toi, 1) + '</td></tr>'; }).join('') +
        '</tbody></table></div></div></article></section>';
    }
    /* 4. game by game and their type */
    if (gbg || (tape && typeCard)) h += '<section class="qk-section"><div class="qk-gside"><div>' + gbg + '</div><div>' + (tape ? typeCard : '') + '</div></div></section>';
    // ── more on the player
    h += '<section class="qk-section">' + QK.sectionHead({ kicker: 'More on the player', title: 'Value, peers and the long view', sub: 'How much the player is worth to the team, where the player sits among ' + peerShort + ', and every season in the data.' }) +
      (k.length ? '<div class="rk-kpis">' + QK.stats(k) + '</div>' : '') +
      '<div class="qk-grid" style="margin-top:var(--sp-5)"><div class="qk-span-6">' +
      (catP ? U.card2('Among peers', 'Every qualified ' + (U.GROUP_NAME[group] || 'player').replace('NHL ', '') + ' this season; bars coloured by percentile', '<div class="qk-seg" id="pp-dist-m" role="group" aria-label="Metric" style="margin-bottom:10px"></div>' + U.chart('pp-dist', 260, 'Distribution of the peer group')) : '') + '</div>' +
      '<div class="qk-span-6">' + U.card2('Season by season', goalie ? 'Save % and goals saved above expected' : 'Points and value by season; 100 = average for a qualified player at the position', U.chart('pp-seasons', 300, 'Season by season')) + '</div></div></section>';

    // season table
    h += '<section class="qk-section">' + U.card2('Career', seasons.length + ' season' + (seasons.length === 1 ? '' : 's') + ' in the data', '<div id="pp-career"></div>', { flush: true }) + '</section>';

    // splits, shots, value, movement
    h += '<section class="qk-section"><div class="qk-grid">';
    if (c && c.shots && Array.isArray(c.shots.points) && c.shots.points.length) h += '<div class="qk-span-6">' + U.card2(goalie ? 'Shots faced' : 'Shot map', (goalie ? 'Unblocked shots faced' : 'Last ' + c.shots.points.length + ' unblocked attempts') + ', attacking right; filled = goal, size = xG', '<div id="pp-shots"></div>') + '</div>';
    h += '<div class="qk-span-6">' + U.card2('Splits', 'This season', '<div id="pp-splits"></div>', { flush: true }) + '</div>';
    h += '</div></section>';
    const side = [];
    if (vrow && (vrow.why || []).length) side.push('<div class="qk-span-6">' + U.card2('Where the value comes from', 'GAR by component this season', '<ul class="rk-list">' + vrow.why.map(w => '<li><span>' + esc(w[0]) + '</span><span class="v">' + esc(isNum(w[1]) ? (Math.abs(w[1]) < 1 && w[0].indexOf('%') >= 0 ? RK.fmtVal(w[1], '3') : U.signed(w[1], 2)) : '') + '</span></li>').join('') + '</ul>', { flush: true, foot: '<span></span><a href="#/value">Value leaderboard →</a>' }) + '</div>');
    // movement (MOVES_VIEWS.md §4): our chance the player is not in the lineup next season, the type split, the deadline base rate
    const M = res[6], mvr = M ? M.byPid[pid] : null;
    if (mvr && isNum(mvr.p_next)) {
      const ctx = [isNum(mvr.age) ? 'age ' + Math.floor(mvr.age) : '', isNum(mvr.yrs) ? mvr.yrs + ' seasons in the league' : '', isNum(mvr.value) ? U.signed(mvr.value, 2) + ' ' + (M.d.unit || 'WAR') + ' last season' : ''].filter(Boolean).join(' · ');
      side.unshift('<div class="qk-span-6">' + U.card2('Movement', 'By ' + esc(M.horizon), QK.stats([{ label: U.MOVE_HEAD, value: mvr.p_next < 0.01 ? '<1' : String(Math.round(mvr.p_next * 100)), unit: '%', signal: true, sub: mvr.why || '', tip: U.moveTip(M) }]) +
        '<div style="margin-top:10px">' + U.moveBar(mvr, M) + '</div><div style="margin-top:8px">' + U.moveKeys(M) + '</div>' + (ctx ? '<p class="rk-note" style="margin:8px 0 0">' + esc(ctx) + '</p>' : '') + U.deadlineLine(M).replace('rk-mv-line', 'rk-mv-line" style="margin-top:8px'), { foot: '<span>How it works</span><a href="#/model?tab=moves">Who moves next →</a>' }) + '</div>');
    }
    if (side.length) h += '<section class="qk-section"><div class="qk-grid">' + side.join('') + '</div></section>';
    body.innerHTML = h;

    // game by game: goals and assists stacked (skaters), GSAx (goalies), the best game annotated
    if (lg.length && body.querySelector('#pp-gbg')) {
      const cats = lg.map(r => RK.fmtDate(r.date, { year: false, weekday: false }) + '\n' + (r.home ? 'v ' : '@ ') + r.opp);
      let best = -1, bi = -1; lg.forEach((r, i) => { const v = (r.g || 0) + (r.a || 0); if (v > best) { best = v; bi = i; } });
      QKC.mount('#pp-gbg', T => {
        const xa = QKC.axis(T, { type: 'category', data: cats, split: false, line: true });
        xa.axisLabel.interval = lg.length > 12 ? 'auto' : 0; xa.axisLabel.lineHeight = 14; xa.axisLabel.fontSize = lg.length > 8 ? 10 : 11.5;
        const ya = QKC.axis(T, goalie ? { fmt: v => v.toFixed(1) } : { min: 0, max: Math.max(4, best + 1), interval: 1 });
        const gB = 26 + QKC.nameAxis(xa, 'Game (date and opponent)', 'bottom'), gT = 26 + QKC.nameAxis(ya, goalie ? 'Goals saved above expected' : 'Points in the game', 'side');
        xa.nameGap = 40;
        const tip = QKC.tooltip(T, { trigger: 'axis', axisPointer: { type: 'shadow', shadowStyle: { color: 'rgba(125,147,255,.10)' } }, formatter: ps => { const r = lg[ps[0].dataIndex]; return '<b>' + esc((r.home ? 'v ' : 'at ') + r.opp) + ' · ' + esc(r.result || '') + '</b>' + (goalie ? QKC.tipRow(T.model, 'GSAx', U.signed(r.gsax, 2)) : QKC.tipRow(T.coral, 'Goals', r.g) + QKC.tipRow(T.sky, 'Assists', r.a) + QKC.tipRow(T.ink3, 'Shots', r.sog) + QKC.tipRow(T.ink3, 'Expected goals', U.f(r.ixg, 2)) + QKC.tipRow(T.ink3, 'Minutes', U.f(r.toi, 1))); } });
        if (goalie) return { grid: { left: 8, right: 12, top: gT, bottom: gB, containLabel: true }, xAxis: xa, yAxis: ya, tooltip: tip,
          series: [{ type: 'bar', name: 'GSAx', barMaxWidth: 30, data: lg.map(r => ({ value: r.gsax, itemStyle: { color: r.gsax >= 0 ? T.model : T.coral } })) }] };
        return { grid: { left: 8, right: 12, top: gT, bottom: gB, containLabel: true }, xAxis: xa, yAxis: ya, tooltip: tip,
          legend: { top: 0, right: 0, itemWidth: 12, itemHeight: 12, icon: 'rect', textStyle: { color: T.ink2, fontFamily: T.fontCond, fontSize: 13, fontWeight: 700 } },
          series: [{ type: 'bar', name: 'Goals', stack: 'p', barMaxWidth: 30, data: lg.map(r => r.g || 0), itemStyle: { color: T.coral, borderColor: T.s1, borderWidth: 1 } },
            { type: 'bar', name: 'Assists', stack: 'p', barMaxWidth: 30, itemStyle: { color: T.sky }, data: lg.map((r, i) => {
              const o = { value: r.a || 0, itemStyle: { color: T.sky, borderColor: T.s1, borderWidth: 1 } };
              if (i === bi && best >= 3) o.label = Object.assign(QKC.annot(T), { show: true, position: 'top', formatter: best + ' points' });
              return o; }) }] };
      }, { label: 'Points in every game this season' });
    }

    // the catalogue (peer distribution, values for the compare) and last season's percentiles (the rings), lazily
    let catFull = cat && cat.players ? cat : null, catP0 = null;
    const withCat = cb => { if (catFull) { cb(catFull); return; } if (catP0) { catP0.then(cb); return; } catP0 = RK.loadYear(goalie ? 'goalies.json' : 'skaters.json', S).then(full => { catFull = full && full.players ? full : null; return catFull; }); catP0.then(cb); };
    const repaint = () => { const old = body.querySelector('#pp-pcard'); if (old) old.outerHTML = pcardHTML(); };
    if (catP && !prevPct && body.querySelector('#pp-pcard')) {
      const host = body.querySelector('#pp-pcard');
      let fired = false;
      const go = () => {
        if (fired) return; fired = true;
        RK.loadYear(goalie ? 'goalies.json' : 'skaters.json', prevS).then(prev => {
          const pr = prev && prev.players ? prev.players[pid] : null;
          if (!pr || !U.alive(body)) return;
          const pc = goalie ? (pr.pct_pos || pr.pct) : (pr.group === group ? pr.pct_pos : null);
          if (!pc) return;
          prevPct = pc; prevGp = pr.gp; repaint();
        });
      };
      if (window.IntersectionObserver) { const io = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) { io.disconnect(); go(); } }, { rootMargin: '200px' }); io.observe(host); } else go();
    }

    // the tale of the tape: the player against one of the closest matches (chips switch), on the card's metric set
    if (body.querySelector('#pp-tape')) {
      withCat(full => {
        if (!full || !U.alive(body)) return;
        const others = sim.map(m => String(m[0])).filter(id => full.players[id]);
        if (!others.length || !full.players[pid]) { body.querySelector('#pp-tape').innerHTML = QK.empty('No comparison yet', 'The closest matches appear once the catalogue has them.'); return; }
        const meta2 = U.metaMap(full);
        const drawTape = oid => {
          const ids = [pid, oid], E = ids.map(id => full.players[id]);
          const same = E[0].group === E[1].group, grp2 = same ? (E[0].group || 'F') : 'F';
          const pcOf = e => (same && e.pct_pos ? e.pct_pos : e.pct) || {};
          const best = {};
          const groups = (U.SETS[grp2] || U.SETS.F).map(g => ({ label: g[0], rows: g[1].map(x => x[0]).filter(kk => meta2[kk] && !meta2[kk].unavailable).map(kk => {
            const m = meta2[kk], spx = U.SPEC[kk] || {};
            const pcs = E.map(e => pcOf(e)[kk]);
            pcs.forEach((v, i) => { const o = pcs[1 - i]; const d = isNum(v) ? v - (isNum(o) ? o : 0) : null; if (isNum(d) && (!best[i] || d > best[i].d)) best[i] = { k: kk, d: d, v: (E[i].values || {})[kk] }; });
            return { label: spx.label || m.label || kk, tip: spx.tip || m.desc, better: (m.lower || spx.lower) ? 'low' : 'high', values: E.map(e => (e.values || {})[kk]), pctls: pcs, fmt: v => U.fmtBy(m, v) };
          }) }));
          const names = ids.map((id, i) => RK.playerSurname(id) || E[i].name);
          body.querySelector('#pp-tape-h').innerHTML = QK.sectionHead({ kicker: 'Tale of the tape', title: names[0] + ' or ' + names[1] + '?',
            sub: 'Bar length = percentile against ' + (same ? (U.GROUP_NAME[grp2] || 'the position') : 'all NHL skaters') + '. The better number in each row is solid.' });
          const ents = E.map((e, i) => ({ name: e.name, short: names[i], href: RK.playerHref(ids[i]), colour: RK.teamColourRaw(e.team), alt: RK.teamAlt(e.team), sub: [RK.teamName(e.team), e.gp + ' games'].join(' · ') }));
          body.querySelector('#pp-tape').innerHTML = QK.compareView({ entities: ents, groups: groups });
          const verd = E.map((e, i) => best[i] && best[i].d > 0 ? { title: U.ARCHETYPE[best[i].k] || 'The standout', who: names[i], text: 'the better of the two on ' + lc((U.SPEC[best[i].k] || {}).label || best[i].k) + ' (' + U.fmtBy(meta2[best[i].k], best[i].v) + ').' } : null);
          body.querySelector('#pp-verd').innerHTML = QK.verdicts(verd);
        };
        const pick = body.querySelector('#pp-tape-pick');
        pick.innerHTML = others.map((id, i) => '<button type="button" class="qk-chip" data-value="' + esc(id) + '" aria-pressed="' + (i === 0) + '">' + esc(RK.playerSurname(id) || full.players[id].name) + '</button>').join('') +
          (others.length > 1 ? '<a class="qk-chip" href="' + esc('#/compare/' + [pid].concat(others.slice(0, 2)).map(encodeURIComponent).join('/')) + '">All three in Compare</a>' : '<a class="qk-chip" href="' + esc('#/compare/' + pid) + '">Pick a player</a>');
        pick.querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
          pick.querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', x === b ? 'true' : 'false'));
          drawTape(b.getAttribute('data-value'));
        }));
        drawTape(others[0]);
      });
    }

    // what to watch tonight: the scoreboard bug, the bar and how the clubs match up so far (season.json ratings)
    if (nxt && body.querySelector('#pp-next')) {
      RK.loadYear('season.json', S).then(sj => {
        const box = body.querySelector('#pp-next');
        if (!box || !U.alive(box)) return;
        const season = RK.ok(sj) ? sj : {};
        const rows = {}; (((season.standings || {}).rows) || []).forEach(r => { rows[r.team] = r; });
        const g = U.gameV2(nxt, null, rows);
        g.away.alt = RK.teamAlt(nxt.away); g.home.alt = RK.teamAlt(nxt.home);
        const R = season.ratings || {}, ua = (R[nxt.away] || {}).units || {}, uh = (R[nxt.home] || {}).units || {};
        const fx = [];
        const add = (label, a, b, f, low) => { if (isNum(a) && isNum(b)) fx.push({ label: label, a: f(a), b: f(b), better: Math.abs(a - b) < 1e-9 ? null : ((a > b) !== !!low ? 'a' : 'b') }); };
        add('Goals for per game', ua.gf_g, uh.gf_g, v => U.f(v, 1));
        add('Goals against per game', ua.ga_g, uh.ga_g, v => U.f(v, 1), true);
        add('Chance share, 5-on-5', ua.xgf_pct5, uh.xgf_pct5, v => U.pct(v, 1));
        add('Team rating', (rows[nxt.away] || {}).rating, (rows[nxt.home] || {}).rating, v => U.signed(v, 2));
        const m = nxt.model || {};
        const extra = isNum(m.p_ot) ? 'Overtime: ' + U.pct(m.p_ot) + ' (about 1 in ' + Math.max(2, Math.round(1 / m.p_ot)) + ').' : '';
        box.innerHTML = QK.previewCard(g, { layout: 'bug', nick: t => nickOf(t.abbr), factors: fx, factorsTitle: 'How they match up so far', noteExtra: esc(extra) });
      });
    }

    // the last game: the box score by period (goals, shots, expected goals) and the expected-goals race
    if (lastG && body.querySelector('#pp-race')) {
      RK.loadGame(lastG.game_id).then(d => {
        if (!RK.ok(d) || !U.alive(body)) return;
        const ls = d.linescore || [], card = Object.assign({}, d.card || {});
        const home = card.home || (lastG.home ? curTeam : lastG.opp), away = card.away || (lastG.home ? lastG.opp : curTeam);
        if (ls.length) {
          const pl = RK.isPlayoffGame ? RK.isPlayoffGame(card) : false;
          const sum = (k) => ls.reduce((s, r) => s + (isNum(r[k]) ? r[k] : 0), 0);
          const row = (ab, side) => '<tr' + (ab === curTeam ? ' class="hl"' : '') + '><td>' + QK.teamMark(U.team(ab), 'sm') + '</td>' + ls.map(r => '<td class="num">' + (isNum(r['g_' + side]) ? r['g_' + side] : '–') + '</td>').join('') +
            '<td class="num"><b>' + sum('g_' + side) + '</b></td><td class="num">' + sum('s_' + side) + '</td><td class="num">' + U.f(sum('xg_' + side), 2) + '</td></tr>';
          body.querySelector('#pp-box').innerHTML = '<div class="qk-table-wrap"><table class="qk-table dense"><thead><tr><th>Team</th>' + ls.map(r => '<th class="num">' + esc(RK.periodLabel ? RK.periodLabel(r.period, { playoff: pl }) : r.period) + '</th>').join('') +
            '<th class="num">Goals</th><th class="num">Shots</th><th class="num" data-tip="Expected goals: the chance quality of every shot, added up">Exp. goals</th></tr></thead><tbody>' + row(away, 'away') + row(home, 'home') + '</tbody></table></div>';
        }
        const race = d.xg_race && Array.isArray(d.xg_race.rows) ? d.xg_race.rows : [];
        if (race.length > 1) {
          const ci = {}; (d.xg_race.cols || []).forEach((k, i) => { ci[k] = i; });
          const [ca, ch] = U.pair(away, home);
          const host = body.querySelector('#pp-race');
          host.innerHTML = U.chart('pp-race-c', 260, 'Expected goals through the last game');
          const x = race.map(r => r[ci.sec] / 60);
          QKC.mount('#pp-race-c', T => {
            const mk = (side, col, ab) => ({ type: 'line', name: RK.teamAbbr(ab), step: 'end', showSymbol: false, data: race.map((r, i) => [x[i], r[ci[side]]]), lineStyle: { width: 3, color: col }, itemStyle: { color: col },
              areaStyle: ab === curTeam ? { color: QKC.hexA(col, 0.12) } : undefined,
              markPoint: { symbol: 'rect', symbolSize: 9, itemStyle: { color: col, borderColor: T.s1, borderWidth: 2 }, label: { show: false },
                data: race.map((r, i) => (r[ci.goal] && String(r[ci.goal]) === String(ab) ? { coord: [x[i], r[ci[side]]] } : null)).filter(Boolean) },
              endLabel: { show: true, formatter: p => RK.teamAbbr(ab) + ' ' + U.f(p.value[1], 1), color: T.ink1, fontFamily: T.fontDisplay, fontSize: 20 } });
            const xa = QKC.axis(T, { type: 'value', min: 0, max: Math.max(60, Math.ceil(x[x.length - 1] / 5) * 5), interval: 20, split: false, line: true });
            const ya = QKC.axis(T, { fmt: v => v.toFixed(1) });
            const gB = 8 + QKC.nameAxis(xa, 'Minutes played', 'bottom'), gT = 14 + QKC.nameAxis(ya, 'Expected goals', 'side');
            return { grid: { left: 8, right: 80, top: gT, bottom: gB, containLabel: true }, xAxis: xa, yAxis: ya,
              tooltip: QKC.tooltip(T, { trigger: 'axis', formatter: ps => '<div>Minute ' + esc(U.f(ps[0].value[0], 0)) + '</div>' + ps.map(q => QKC.tipRow(q.color, q.seriesName, U.f(q.value[1], 2) + ' xG')).join('') }),
              series: [mk('away', ca, away), mk('home', ch, home)] };
          }, { label: 'Expected goals through the last game' });
        }
      });
    }

        // where he sits: the peer distribution of one metric (the spec's set), with him and the median marked. With the
    // player file's percentiles the catalogue loads only when this card comes into view; it then fills the values.
    if (catP && body.querySelector('#pp-dist')) {
      const OPTS = { F: [['gar_60', 'Value / 60'], ['p60', 'Points / 60'], ['ixg60_all', 'ixG / 60'], ['adj_xgf_pct', 'xG share']], D: [['gar_60', 'Value / 60'], ['adj_xgf_pct', 'xG share'], ['rapm_def', 'RAPM defence'], ['p60', 'Points / 60']],
        G: [['gsax100', 'GSAx / 100'], ['sv_pct', 'Save %'], ['qs_pct', 'Quality starts']] };
      const opts = OPTS[group] || OPTS.F;
      const segEl = body.querySelector('#pp-dist-m');
      segEl.innerHTML = opts.map((o, i) => '<button type="button" aria-pressed="' + (i === 0) + '" data-value="' + o[0] + '">' + esc(o[1]) + '</button>').join('');
      const start = full => {
        const peers = Object.keys(full.players || {}).map(id => full.players[id]).filter(x => x && x.qualified && (goalie || x.group === group));
        const me = (full.players || {})[pid];
        if (fileP && me) {
          catP.values = Object.assign({}, catP.values, me.values || {}); catP.toi = me.toi; catP.gp = me.gp;
          Object.assign(meta, U.metaMap(full));
          repaint();
        }
        const drawDist = key => {
          const mm = meta[key] || {}, sp = U.SPEC[key] || {};
          const vals = peers.map(x => (x.values || {})[key]).filter(isNum).sort((x, y) => x - y);
          const mine = (catP.values || {})[key];
          if (vals.length < 5) { body.querySelector('#pp-dist').innerHTML = QK.empty('Too few qualified peers yet', 'The distribution appears once five ' + (U.PEER_SHORT[group] || 'players') + ' reach the sample floor.'); return; }
          const med = vals[Math.floor(vals.length / 2)];
          const f = mm.fmt === 'pct' ? (v => U.f(v * 100, 1) + '%') : (v => U.f(v, 2));
          QKC.distribution('#pp-dist', { values: vals, binCount: 22, lowerBetter: !!(mm.lower || sp.lower), fmt: f, xName: (sp.label || mm.label || key) + ' · ' + vals.length + ' qualified peers', yName: 'Players',
            marks: (isNum(mine) ? [{ x: mine, label: RK.playerSurname(pid) }] : []).concat([{ x: med, label: 'Median' }]), label: 'Distribution of ' + (sp.label || mm.label || key) });
        };
        drawDist(opts[0][0]);
        QK.seg(segEl, drawDist);
      };
      if (cat && cat.players) start(cat);
      else {
        const host = body.querySelector('#pp-dist');
        host.innerHTML = QK.skeleton('chart', 1);
        let fired = false;
        const go = () => { if (fired) return; fired = true; withCat(full => { if (U.alive(host) && full && full.players) start(full); else if (U.alive(host)) host.innerHTML = QK.empty('The peer catalogue did not load'); }); };
        if (window.IntersectionObserver) { const io = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) { io.disconnect(); go(); } }, { rootMargin: '200px' }); io.observe(host); } else go();
      }
    }

    // season chart
    const sx = seasons.map(s => RK.seasonLabel(s.season, true));
    if (seasons.length) {
      if (goalie) {
        QKC.mount('#pp-seasons', T => ({
          grid: { left: 8, right: 8, top: 48, bottom: 30, containLabel: true },
          legend: { top: 0, left: 0, textStyle: { color: T.ink2 }, itemWidth: 12, itemHeight: 8 },
          xAxis: QKC.axis(T, { type: 'category', data: sx, split: false, line: true, name: 'Season', nameLocation: 'middle', nameGap: 26 }),
          yAxis: [QKC.axis(T, { fmt: v => v.toFixed(0), name: 'Goals saved above expected', nameAlign: 'left' }), QKC.axis(T, { fmt: v => v.toFixed(3), split: false, scale: true, name: 'Save %', nameAlign: 'right' })],
          tooltip: QKC.tooltip(T, { trigger: 'axis' }),
          series: [{ type: 'bar', name: 'GSAx', data: seasons.map(s => ({ value: (s.values || {}).gsax, itemStyle: { color: (s.values || {}).gsax >= 0 ? T.pos : T.neg, borderRadius: 3 } })), barMaxWidth: 26 },
            { type: 'line', name: 'Save %', yAxisIndex: 1, data: seasons.map(s => (s.values || {}).sv_pct), lineStyle: { color: T.cat[1], width: 2 }, itemStyle: { color: T.cat[1] }, symbolSize: 6 }]
        }), { label: 'Goalie seasons' });
      } else {
        QKC.mount('#pp-seasons', T => ({
          grid: { left: 8, right: 8, top: 48, bottom: 30, containLabel: true },
          legend: { top: 0, left: 0, textStyle: { color: T.ink2 }, itemWidth: 12, itemHeight: 8 },
          xAxis: QKC.axis(T, { type: 'category', data: sx, split: false, line: true, name: 'Season', nameLocation: 'middle', nameGap: 26 }),
          yAxis: [QKC.axis(T, { fmt: v => v.toFixed(0), name: 'Points', nameAlign: 'left' }), QKC.axis(T, { split: false, scale: true, name: 'Index (100 = average)', nameAlign: 'right' })],
          tooltip: QKC.tooltip(T, { trigger: 'axis' }),
          series: [{ type: 'bar', name: 'Points', barMaxWidth: 26, data: seasons.map(s => ({ value: (s.values || {}).p, itemStyle: { color: QK.color.ensure(RK.teamColourRaw(s.team) || T.model, T.s1, 3), borderRadius: [3, 3, 0, 0] } })) },
            { type: 'line', name: 'Points/60 index', yAxisIndex: 1, data: seasons.map(s => (s.plus || {}).p60), lineStyle: { color: T.cat[1], width: 2 }, itemStyle: { color: T.cat[1] }, symbolSize: 6, connectNulls: true },
            { type: 'line', name: 'xGF% index', yAxisIndex: 1, data: seasons.map(s => (s.plus || {}).xgf_pct), lineStyle: { color: T.cat[2], width: 2, type: 'dashed' }, itemStyle: { color: T.cat[2] }, symbolSize: 6, connectNulls: true,
              markLine: { silent: true, symbol: 'none', lineStyle: { color: T.axis, type: [3, 3] }, label: { show: false }, data: [{ yAxis: 100 }] } }]
        }), { label: 'Points and indexes by season' });
      }
    }
    // game log chart
    if (lg.length && body.querySelector('#pp-log')) {
      const lx = lg.map(r => RK.fmtDate(r.date, { year: false, weekday: false }));
      QKC.mount('#pp-log', T => ({
        grid: { left: 8, right: 8, top: 28, bottom: 30, containLabel: true },
        xAxis: QKC.axis(T, { type: 'category', data: lx, split: false, line: true, name: 'Game date', nameLocation: 'middle', nameGap: 26 }),
        yAxis: QKC.axis(T, { fmt: v => v.toFixed(1), name: goalie ? 'Goals saved above expected' : 'Game score and ixG', nameAlign: 'left' }),
        tooltip: QKC.tooltip(T, { trigger: 'axis', formatter: ps => { const r = lg[ps[0].dataIndex]; return '<b>' + esc((r.home ? 'v ' : '@ ') + r.opp) + ' · ' + esc(r.result || '') + '</b>' + ps.map(q => QKC.tipRow(q.color, q.seriesName, U.f(q.value, 2))).join('') + (goalie ? QKC.tipRow(T.other, 'Saves', (r.sa - r.ga) + '/' + r.sa) : QKC.tipRow(T.other, 'G-A', r.g + '-' + r.a)); } }),
        series: goalie ? [{ type: 'bar', name: 'GSAx', data: lg.map(r => ({ value: r.gsax, itemStyle: { color: r.gsax >= 0 ? T.pos : T.neg, borderRadius: 3 } })), barMaxWidth: 18 }]
          : [{ type: 'bar', name: 'Game score', data: lg.map(r => ({ value: r.gs, itemStyle: { color: QKC.hexA(tc.charAt(0) === '#' ? tc : T.model, 0.85), borderRadius: 3 } })), barMaxWidth: 18 },
            { type: 'line', name: 'ixG', data: lg.map(r => r.ixg), lineStyle: { color: T.cat[1], width: 2 }, itemStyle: { color: T.cat[1] }, symbolSize: 5 }]
      }), { label: 'Game log' });
    }
    // career table
    const cols = goalie
      ? [['gp', 'GP'], ['w', 'W'], ['sv_pct', 'SV%', v => RK.fmtVal(v, '3')], ['gaa', 'GAA', v => U.f(v, 2)], ['gsax', 'GSAx', v => U.signed(v, 1)], ['gsax60', 'GSAx/60', v => U.signed(v, 3)], ['qs_pct', 'QS%', v => U.pct(v)], ['war', 'WAR', v => U.f(v, 2)]]
      : [['gp', 'GP'], ['g', 'G'], ['a', 'A'], ['p', 'P'], ['p60', 'P/60', v => U.f(v, 2)], ['toi_gp', 'TOI/GP', v => RK.fmtTOI(v, { minutes: true })], ['ixg', 'ixG', v => U.f(v, 1)], ['sh_pct', 'Sh%', v => U.pct(v, 1)],
        ['xgf_pct', 'xGF%', v => U.pct(v, 1)], ['rapm_net', 'RAPM', v => U.signed(v, 2)], ['gar', 'GAR', v => U.f(v, 1)], ['war', 'WAR', v => U.f(v, 2)]];
    QK.table(body.querySelector('#pp-career'), { dense: true, sort: { key: 'season', dir: 'desc' }, columns: [
      { key: 'season', label: 'Season', sticky: true, fmt: (v, r) => '<b>' + esc(RK.seasonLabel(v)) + '</b>' }, { key: 'team', label: 'Club', fmt: (v, r) => (r.teams && r.teams.length > 1 ? r.teams.map(t => esc(RK.teamAbbr(t))).join(', ') : U.teamEnt(v, { abbr: true, season: r.season })) },
      { key: 'age', label: 'Age', num: true, fmt: v => U.f(v, 0) }]
      .concat(cols.map(cc => ({ key: cc[0], label: cc[1], num: true, fmt: cc[2] || (v => (isNum(v) ? String(v) : '—')) }))),
      rows: seasons.map(s => Object.assign({ season: s.season, team: s.team, teams: s.teams, age: s.age }, s.values || {})) });

    // shots
    const sn = body.querySelector('#pp-shots');
    if (sn) {
      const pcI = {}; (c.shots.point_cols || ['x', 'y', 'xg', 'goal']).forEach((kk, i) => { pcI[kk] = i; });
      sn.innerHTML = '<div id="pp-shots-c"></div>';
      QKC.shotMap('#pp-shots-c', { surface: 'rink', shots: c.shots.points.map(q => ({ x: q[pcI.x], y: q[pcI.y], v: q[pcI.xg], made: !!q[pcI.goal], name: (q[pcI.goal] ? 'Goal' : (goalie ? 'Save' : 'Attempt')) + ' · xG ' + U.f(q[pcI.xg], 2) })), madeLabel: goalie ? 'Goal against' : 'Goal', missLabel: goalie ? 'Saved / missed' : 'No goal', sizeScale: 30 });
    }
    // splits
    const sp = [];
    const bs = (c && c.onice && c.onice.by_strength) || {};
    Object.keys(bs).forEach(kk => { const b = bs[kk]; sp.push({ k: kk === 'pp' ? 'Power play' : kk === 'pk' ? 'Penalty kill' : kk, toi: b.toi, a: b.xgf_pct, b2: b.cf_pct, c2: b.gf_pct, d: b.xgf60, e: b.xga60 }); });
    const spEl = body.querySelector('#pp-splits');
    let sh = '';
    if (sp.length && !goalie) sh += '<div class="qk-table-wrap"><table class="qk-table dense"><thead><tr><th>On ice</th><th class="num">TOI</th><th class="num">xGF%</th><th class="num">CF%</th><th class="num">GF%</th><th class="num">xGF/60</th><th class="num">xGA/60</th></tr></thead><tbody>' +
      sp.map(r => '<tr><td>' + esc(r.k) + '</td><td class="num">' + U.f(r.toi, 0) + '</td><td class="num">' + U.pct(r.a, 1) + '</td><td class="num">' + U.pct(r.b2, 1) + '</td><td class="num">' + U.pct(r.c2, 1) + '</td><td class="num">' + U.f(r.d, 2) + '</td><td class="num">' + U.f(r.e, 2) + '</td></tr>').join('') + '</tbody></table></div>';
    if (lg.length) {
      const part = (name, list) => {
        const n = list.length;
        if (!n) return '';
        if (goalie) { const sa = list.reduce((s2, r) => s2 + (r.sa || 0), 0), ga = list.reduce((s2, r) => s2 + (r.ga || 0), 0), gs = list.reduce((s2, r) => s2 + (r.gsax || 0), 0); return '<tr><td>' + esc(name) + '</td><td class="num">' + n + '</td><td class="num">' + (sa ? RK.fmtVal(1 - ga / sa, '3') : '—') + '</td><td class="num">' + U.signed(gs, 2) + '</td><td class="num">' + U.f(ga / n, 2) + '</td></tr>'; }
        const g = list.reduce((s2, r) => s2 + (r.g || 0), 0), a2 = list.reduce((s2, r) => s2 + (r.a || 0), 0), x = list.reduce((s2, r) => s2 + (r.ixg || 0), 0), t = list.reduce((s2, r) => s2 + (r.toi || 0), 0);
        return '<tr><td>' + esc(name) + '</td><td class="num">' + n + '</td><td class="num">' + g + '-' + a2 + '</td><td class="num">' + U.f((g + a2) / n, 2) + '</td><td class="num">' + U.f(x / n, 2) + '</td><td class="num">' + RK.fmtTOI(t / n, { minutes: true }) + '</td></tr>';
      };
      const rows = part('Home', lg.filter(r => r.home)) + part('Away', lg.filter(r => !r.home)) + part('Last 5', lg.slice(-5)) + part('Season', lg);
      sh += '<div class="qk-table-wrap"><table class="qk-table dense"><thead><tr><th>Games</th><th class="num">GP</th>' + (goalie ? '<th class="num">SV%</th><th class="num">GSAx</th><th class="num">GA/GP</th>' : '<th class="num">G-A</th><th class="num">P/GP</th><th class="num">ixG/GP</th><th class="num">TOI</th>') + '</tr></thead><tbody>' + rows + '</tbody></table></div>';
    }
    spEl.innerHTML = sh || QK.empty('No splits yet');
    RK.setMeta(p.updated_at ? 'Player file ' + esc(RK.fmtStamp(p.updated_at)) : '');
  });
}

RK.page('player', render);
})(window.RK);
