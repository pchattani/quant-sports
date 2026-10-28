/* The Quant Rink — Model › How it works (round 9, 28 Oct 2026): the methodology for fans. It opens with what the site
 * does, then one diagram or chart per model in plain words (expected goals, team ratings, game chances, the season
 * simulation, player value, who moves next), then how long each number takes to mean something (the stabilisation
 * table, moved here from the Glossary). The technical detail (sources, code paths, constants, the fitted values) is the
 * old methodology document, folded under "Technical detail" (docs.js); #/methodology/<part> opens it at that part.
 * Reads <S>/season.json, <S>/value.json, glossary.json and calibration.json (all small or already cached). */
(function (RK) {
'use strict';

const U = RK.ui, esc = RK.esc, isNum = v => typeof v === 'number' && isFinite(v);

function flow(steps) {
  return '<div class="rk-flow" role="img" aria-label="' + esc(steps.map(s => s[0]).join(', then ')) + '">' + steps.map((s, i) => (i ? '<span class="rk-flow-a" aria-hidden="true">→</span>' : '') +
    '<div class="rk-flow-s' + (i === steps.length - 1 ? ' out' : '') + '"><b>' + esc(s[0]) + '</b>' + (s[1] ? '<span>' + esc(s[1]) + '</span>' : '') + '</div>').join('') + '</div>';
}
function model(o) {
  return '<article class="qk-card rk-hiw" id="' + esc(o.id) + '"><div class="qk-card-body"><div class="qk-kicker">' + esc(o.kicker) + '</div><h3 class="rk-hiw-t">' + esc(o.title) + '</h3>' +
    '<p class="rk-hiw-p">' + o.text + '</p>' + (o.visual || '') + (o.check ? '<p class="rk-hiw-c"><b>How we check it.</b> ' + o.check + '</p>' : '') +
    (o.more ? '<p class="rk-hiw-m"><a class="qk-link" href="' + esc(o.more[1]) + '">' + esc(o.more[0]) + ' →</a></p>' : '') + '</div></article>';
}

RK.howItWorks = function (node, params, state) {
  const S = RK.currentSeason();
  const part = (params && ((params.rest || [])[0] || params.id)) || '';
  const go = ((params && params.query) || {}).go || '';
  node.innerHTML = QK.skeleton('lines', 8);
  return Promise.all([RK.loadYear('season.json', S), RK.loadYear('value.json', S), RK.load('glossary.json'), RK.load('calibration.json')]).then(res => {
    if (!U.alive(node)) return;
    const sj = RK.ok(res[0]) ? res[0] : {}, vj = RK.ok(res[1]) ? res[1] : null, gj = RK.ok(res[2]) ? res[2] : {}, cj = RK.ok(res[3]) ? res[3] : {};
    const nSim = ((sj.sim || {}).n) || 20000;
    const gm = cj.game_model || {}, nG = gm.games || gm.n || null;
    const vrows = vj ? U.rowsOf(vj).filter(r => r.kind !== 'G' && r.q && isNum(r.gar)) : [];
    const topV = vrows.sort((a, b) => b.gar - a.gar)[0];
    const R = sj.ratings || {};
    const top8 = Object.keys(R).filter(t => isNum((R[t].units || {}).rating)).sort((a, b) => R[b].units.rating - R[a].units.rating).slice(0, 8);
    node.innerHTML =
      '<section class="rk-hiw-intro">' + QK.sectionHead({ kicker: 'How it works', title: 'Every number on this site, in plain words', sub: 'The Quant Rink turns the NHL’s free play-by-play into our own numbers: the chance of every shot going in, how good each club and player really is, the chance of every result tonight, and where the season ends up after we play it out ' + QK.fmt.num(nSim) + ' times. Here is how each piece works, with the code-level detail folded at the foot.' }) +
      '<nav class="tm-jump" aria-label="Models"><div class="qk-chips scroll">' + [['hw-xg', 'Expected goals'], ['hw-team', 'Team ratings'], ['hw-game', 'Game chances'], ['hw-season', 'The season'], ['hw-value', 'Player value'], ['hw-moves', 'Who moves next'], ['hw-stab', 'How sure'], ['hw-tech', 'Technical detail']].map(x => '<a class="qk-chip" href="#' + x[0] + '" data-jump="' + x[0] + '">' + x[1] + '</a>').join('') + '</div></nav></section>' +
      '<div class="rk-hiw-grid">' +
      model({ id: 'hw-xg', kicker: 'Model 1', title: 'Expected goals: how good was that chance?', text: 'Every unblocked shot gets a number between 0 and 1: how often a shot like it goes in. A tap-in at the crease might be 0.30, a wrist shot from the blue line 0.02. Add them up and you get a club’s or a player’s <b>expected goals</b> (xG), which tells you more about the next games than the goals do: goals swing on a few bounces, chances much less.',
        visual: flow([['The shot', 'from the play-by-play'], ['What it looked like', 'distance, angle, shot type, rebound, rush, strength, who took it'], ['Thousands of past shots', 'how often each kind went in'], ['Its xG', '0.02 to 0.60']]),
        check: 'Every season is scored by a model that never saw it, against MoneyPuck’s published xG on the same shots. MoneyPuck is a little sharper (it sees passes and screens the free data does not), and we say so on How we’re doing.', more: ['How we’re doing', '#/model?tab=calibration'] }) +
      model({ id: 'hw-team', kicker: 'Model 2', title: 'Team ratings: how good is each club?', text: 'Our rating is how many goals a game better (or worse) than an average club a team is. It is built from every game’s expected goals and goals at 5-on-5, on the power play and the penalty kill, and from its goaltending, each part weighted towards recent games, with last season as a starting point that fades as the games come in.',
        visual: '<div class="rk-hiw-chart" id="hw-team-c"></div>' + flow([['Every game', 'xG and goals, by situation'], ['Attack and defence', '5-on-5, power play, penalty kill'], ['Goaltending', 'saves above expected'], ['Our rating', 'goals a game v average']]),
        check: 'The ratings drive the game chances below, so they are checked through them.', more: ['The power board on Teams', '#/teams'] }) +
      model({ id: 'hw-game', kicker: 'Model 3', title: 'Game chances: who wins tonight?', text: 'For each game we turn the two clubs’ ratings into the goals each side should score, adjusted for home ice, rest and travel and the starting goalies, then play the game out: three periods, overtime and a shootout. The share of results each club wins is <b>our chance</b>. Hockey is close to a coin flip, so even a strong favourite sits near 60%.',
        visual: flow([['Two ratings', 'attack, defence, special teams'], ['Tonight’s details', 'home ice, back-to-backs, travel, the goalies'], ['Goals each side', 'expected for the night'], ['Play it out', 'regulation, overtime, shootout'], ['Our chance', 'to win, to go to overtime']]),
        check: (isNum(nG) ? 'Every game since 2009–10 (' + QK.fmt.num(nG) + ' of them) forecast with only what was known before it, ' : 'Every game since 2009–10 forecast with only what was known before it, ') + 'grouped by the chance we gave, against how often it happened.', more: ['How we’re doing', '#/model?tab=calibration'] }) +
      model({ id: 'hw-season', kicker: 'Model 4', title: 'The season: who makes the playoffs and lifts the Cup?', text: 'We take every game left on the schedule and play it ' + QK.fmt.num(nSim) + ' times with the game chances, keeping the real tie-breakers, the wild cards, the bracket and four best-of-seven rounds. How often a club makes the playoffs, wins its division or lifts the Cup across those seasons is our chance. Early in the season the ranges are wide; they narrow with every game day.',
        visual: '<div class="rk-hiw-chart" id="hw-season-c"></div>' + flow([['Game chances', 'every game left'], ['Play the season', QK.fmt.num(nSim) + ' times'], ['Standings and seeds', 'with the real tie-breakers'], ['The playoffs', 'four best-of-seven rounds'], ['Our chances', 'playoffs, division, Cup']]),
        check: 'At fixed points of past seasons, our playoff and Cup chances against what happened.', more: ['Standings › Chances', '#/standings?tab=chances'] }) +
      model({ id: 'hw-value', kicker: 'Model 5', title: 'Player value: what is a player worth?', text: '<b>Goals above replacement</b> (GAR) adds up everything a player gives a club beyond a call-up from the minors: driving the play at even strength at both ends, the power play and the penalty kill, finishing chances, and drawing or taking penalties (goalies: goals saved above expected). Divide by the goals a win costs and you get <b>wins above replacement</b> (WAR).',
        visual: '<div class="rk-hiw-chart" id="hw-value-c"></div>', check: 'Each part is built from models that adjust for team-mates and opponents (RAPM), shrunk by how fast it stabilises.', more: ['Value & Moves', '#/value'] }) +
      model({ id: 'hw-moves', kicker: 'Model 6', title: 'Who moves next, and what a player is worth over four seasons', text: 'From every player’s age, value, role, years in the league and time with the club (no contract data: no free source allows it), a model fitted on who moved in every season since 2009–10 gives the chance a player is not in the same lineup next season. A separate projection carries each player’s value over this season and the next three with an ageing curve. A model is shown only when it beat the plain league rate on seasons it never saw.',
        visual: flow([['The player', 'age, value, ice time, years in the league'], ['Past careers', 'who moved, who aged how'], ['Next season', 'the chance of moving'], ['Four seasons', 'projected wins above replacement']]),
        check: 'Validated on sealed seasons; the scores are on the Who moves next tab.', more: ['Who moves next', '#/model?tab=moves'] }) +
      '</div>' +
      '<section class="qk-section" id="hw-stab">' + QK.sectionHead({ kicker: 'How sure are the numbers?', title: 'How long until a number means something', sub: 'The sample at which each metric is mostly signal (split-half reliability of 0.7): before it, read the number lightly. Shot attempts settle in days; save percentage takes seasons.' }) +
      '<div class="qk-card"><div class="qk-card-body"><div id="hw-stab-t"></div></div></div></section>' +
      '<details class="rk-fold" id="hw-tech"' + (part ? ' open' : '') + '><summary>Technical detail: sources, code paths, constants and the fitted values</summary><div class="rk-fold-b"><div id="md-tab"></div></div></details>';
    /* charts */
    if (top8.length) QKC.bar('#hw-team-c', { cats: top8.map(t => RK.teamName(t)), series: [{ name: 'Our rating', data: top8.map(t => R[t].units.rating) }], horizontal: true, labels: true, fmt: x => U.signed(x, 2), colors: top8.map(t => RK.teamColourRaw(t)), hrefs: top8.map(t => RK.teamHref(t)), labelWidth: 140, valName: 'Our rating today: goals a game v an average club' });
    else node.querySelector('#hw-team-c').remove();
    const simT = (sj.sim || {}).teams || {};
    const cups = Object.keys(simT).filter(t => isNum(simT[t].p_cup)).sort((a, b) => simT[b].p_cup - simT[a].p_cup).slice(0, 6);
    if (cups.length) node.querySelector('#hw-season-c').innerHTML = QK.chances(cups.map(t => ({ label: RK.teamName(t), p: simT[t].p_cup, href: RK.teamHref(t), mark: U.team(t), color: RK.teamColourRaw(t) })), { key: false, oursName: 'Our Cup chance today' });
    else node.querySelector('#hw-season-c').remove();
    const parts = [['ev_off', 'Even-strength offence'], ['ev_def', 'Even-strength defence'], ['pp', 'Power play'], ['pk', 'Penalty kill'], ['shooting', 'Finishing'], ['pen', 'Penalties']];
    /* the example: the most valuable skater with at least three parts of the game counted (early in a season most parts
       are still near zero, so last season's leader stands in, said so) */
    const full = r => r && parts.filter(p => isNum(r[p[0]]) && Math.abs(r[p[0]]) >= 0.05).length >= 3;
    const example = (r, SS) => {
      const host = node.querySelector('#hw-value-c');
      if (!host) return;
      if (!r) { host.remove(); return; }
      host.innerHTML = '<p class="rk-hiw-x">For example, <a class="qk-link" href="' + esc(RK.playerHref(r.id)) + '">' + esc(r.name) + '</a> (' + esc(RK.teamAbbr(r.team)) + '), the most valuable skater ' + (SS === S ? 'so far' : 'of ' + RK.seasonLabel(SS)) + ': ' + U.f(r.gar, 1) + ' goals above replacement, ' + U.f(r.war, 2) + ' wins.</p><div id="hw-value-b" class="qk-chart" style="--h:240px"></div>';
      QKC.bar('#hw-value-b', { cats: parts.map(p => p[1]), series: [{ name: 'GAR', data: parts.map(p => (isNum(r[p[0]]) ? r[p[0]] : 0)) }], horizontal: true, diverging: true, labels: true, fmt: x => U.signed(x, 1), labelWidth: 150, valName: 'Goals above replacement, by part of the game' });
    };
    if (full(topV)) example(topV, S);
    else RK.loadYear('value.json', S - 10001).then(pv => { const rs = RK.ok(pv) ? U.rowsOf(pv).filter(r => r.kind !== 'G' && r.q && isNum(r.gar)).sort((a, b) => b.gar - a.gar) : []; example(rs.filter(full)[0] || null, S - 10001); });
    /* the stabilisation table */
    const st = [];
    ((gj.groups || [])).forEach(g => (g.entries || []).forEach(e => { if (isNum(e.stabilises_at) && !st.some(x => x.key === e.key && x.kind === e.kind)) st.push(Object.assign({ grp: String(g.name || '').replace(/^(Skaters|Goalies|Teams): /, '') }, e)); }));
    st.sort((a, b) => String(a.kind || '').localeCompare(String(b.kind || '')) || a.stabilises_at - b.stabilises_at);
    const fix = t => String(t || '').replace(/^EDGE /, 'Tracked ');
    QK.leaderboard(node.querySelector('#hw-stab-t'), { dense: true, maxHeight: 560, columns: [
      { key: 'label', label: 'Metric', fmt: (x, r) => '<a class="qk-link" href="#/glossary/' + encodeURIComponent(r.key) + '">' + esc(fix(x || r.key)) + '</a>' },
      { key: 'who', label: 'For', sort: false }, { key: 'grp', label: 'Group' },
      { key: 'stabilises_at', label: 'Mostly signal after', num: true, fmt: (x, r) => '<b>' + QK.fmt.num(x) + '</b> ' + esc(r.unit || 'minutes') }],
      rows: st.map(e => Object.assign({}, e, { who: e.kind === 'goalie' ? 'Goalies' : 'Skaters' })) });
    node.querySelectorAll('[data-jump]').forEach(a => a.addEventListener('click', ev => {
      ev.preventDefault();
      const t = document.getElementById(a.getAttribute('data-jump'));
      if (!t) return;
      if (t.tagName === 'DETAILS') t.open = true;
      const off = ['.qk-topbar', '.qk-secnav'].reduce((z, q) => z + ((document.querySelector(q) || {}).offsetHeight || 0), 0) + 12;
      window.scrollTo({ top: t.getBoundingClientRect().top + window.scrollY - off, behavior: 'smooth' });
    }));
    const tech = node.querySelector('#md-tab');
    const r = U.legacy('methodology', tech, params, state);
    if (go === 'stab') setTimeout(() => { const t = document.getElementById('hw-stab'); if (t) t.scrollIntoView({ block: 'start' }); }, 80);
    return r;
  });
};
})(window.RK);
