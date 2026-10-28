/* The Quant Gridiron — the Model section's text pages: Methodology (#/methodology[/<sec>]), Glossary
 * (#/glossary[/<key> | g:<group>]) and the Disclaimer (#/disclaimer). Calibration lives in calibration.js.
 * The text is GI.METHOD (method-text.js); old links inside it are rewritten through GI.fixLinks.
 * Reads glossary.json. */
(function (GI) {
'use strict';

const esc = GI.esc, isNum = GI.isNum;
function slug(s) { return String(s || 'group').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''); }


/* "How it works" for fans (round 9): what the site does, then one diagram per model in plain words (what goes in, what
   comes out, what it is for), then the technical detail folded away (the full methodology: code paths, constants, the
   stabilisation points). The opening never leads with closing lines or markets. */
const FANS = [
  ['game', 'Who wins each game', 'The game model', ['Team ratings', 'The quarterbacks', 'Starters out', 'Rest and travel', 'Weather', 'Home field'], 'Our win chance and projected score', 'Every game card, the game pages and the season simulation start here.', 'game'],
  ['wp', 'Who is winning right now', 'Win probability', ['The score', 'The clock', 'Down and distance', 'Field position', 'Timeouts', 'The pre-game spread'], 'The chance to win after every play', 'The line through every game page, and the yardstick for the biggest plays.', 'wp'],
  ['ep', 'What a play was worth', 'Expected points (EPA)', ['Down', 'Distance', 'Yard line', 'Time left'], 'Points the next score is worth, before and after the snap', 'EPA per play is the efficiency number behind the team ratings and the player pages.', 'ep'],
  ['fourth', 'Go, punt or kick?', 'The fourth-down model', ['Chance to convert', 'Punt distance', 'Field-goal make chance', 'Win probability after each'], 'The best call and how much win chance a choice gave up', 'Grades every fourth down: under 1.5 points lost is the right call.', 'fourth'],
  ['strength', 'How good each team is', 'Team ratings', ['EPA on offence and defence', 'Opponents faced', 'Last season, fading as games come in'], 'Points a game better than an average team', 'The power board, the Tale of the tape and the game model read them.', 'strength'],
  ['season', 'Who makes the playoffs', 'The season simulation', ['The game model', 'The schedule left', 'The NFL tiebreakers', '20,000 seasons'], 'Playoff, division, No. 1 seed and Super Bowl chances', 'Chances, the race over time and "what\u2019s at stake" in each game.', 'season'],
  ['value', 'What a player is worth', 'Gridiron Value', ['EPA credited on each play', 'The position\u2019s replacement level', 'The opponent'], 'Points above a replacement player (about 40 a win)', 'Value & Moves, the trade simulator and the Scouting Room\u2019s value columns.', 'value'],
  ['fantasy', 'Who to start', 'The fantasy model', ['Each player\u2019s share of targets and carries', 'Team volume and game script', 'The opponent'], 'Projected points with a range', 'The Fantasy pages: projections, start or sit, waivers.', 'fantasy']
];
function fansHTML() {
  const flow = f => '<div class="gi-flow" role="img" aria-label="' + esc(f[2] + ': ' + f[3].join(', ') + ' go in; ' + f[4] + ' comes out') + '"><div class="gi-flow-in">' + f[3].map(x => '<span>' + esc(x) + '</span>').join('') + '</div>' +
    '<div class="gi-flow-m"><b>' + esc(f[2]) + '</b></div><div class="gi-flow-out"><span>' + esc(f[4]) + '</span></div></div>';
  return '<section class="qk-section">' + QK.sectionHead({ kicker: 'What this site does', title: 'Football by the numbers, explained', sub: 'The Quant Gridiron puts a number on every NFL game, team and player: our chance for every game, the playoff race from 20,000 simulated seasons, every fourth down graded, and percentiles for every player against the others in the same role. Each model below in one picture: what goes in, what comes out, and where you see it.' }) +
    '<div class="gi-fans">' + FANS.map(f => '<article class="qk-card gi-fan"><div class="qk-card-body"><span class="qk-kicker">' + esc(f[1]) + '</span>' + flow(f) + '<p>' + esc(f[5]) + ' <a href="#/methodology/' + esc(f[6]) + '">Technical detail →</a></p></div></article>').join('') + '</div></section>';
}

GI.route('methodology', function (el, params) {
  const M = GI.METHOD || {};
  const tmp = document.createElement('div');
  tmp.innerHTML = GI.fixLinks(M.HTML || '');
  const secs = Array.prototype.slice.call(tmp.querySelectorAll('section[id]')).map(s => {
    const h2 = s.querySelector('h2');
    const title = h2 ? h2.textContent : s.id;
    if (h2) h2.parentNode.removeChild(h2);
    return { id: s.id.replace(/^m-/, ''), title: title, html: s.innerHTML };
  });
  const want0 = params.sec || '';
  el.innerHTML = GI.pageHead('Model', 'How it works', 'What every number on the site means and where it comes from, in plain words first; the full technical detail is folded under it.') + GI.sectionNav('model', 'methodology') + fansHTML() +
    '<details class="gi-tech" id="gi-tech"' + (want0 ? ' open' : '') + '><summary><span class="qk-kicker">Technical detail</span><b>The full methodology</b><span class="qk-sub">Data sources, every model, the constants in the code (1 October 2026), the source files under oddsmarkets/nfl/, the stabilisation points and the known weak spots.</span></summary>' +
    '<div id="gi-stab"></div><div class="gi-doc"><nav class="qk-card gi-toc" aria-label="Sections"><b>Contents</b><ol>' + secs.map(s => '<li><a href="#/methodology/' + esc(s.id) + '" data-target="method-' + esc(s.id) + '">' + esc(s.title) + '</a></li>').join('') + '</ol></nav>' +
    '<div class="gi-doc-body">' + secs.map((s, i) => '<section class="qk-card gi-prose" id="method-' + esc(s.id) + '"><div class="qk-card-body"><h2><span class="gi-num" style="color:var(--signal)">' + (i + 1) + '</span> ' + esc(s.title) + '</h2>' + s.html + '</div></section>').join('') + '</div></div></details>';
  /* the stabilisation points (moved from the Glossary): the sample at which each metric is 70% signal */
  GI.load('glossary.json').then(g => {
    if (!el.isConnected || !GI.ok(g)) return;
    const stab = [];
    (g.groups || []).forEach(x => (x.entries || []).forEach(e => { if (isNum(e.stabilises_at) && !stab.some(r => r.key === e.key)) stab.push(e); }));
    stab.sort((a, b) => a.stabilises_at - b.stabilises_at);
    if (!stab.length) return;
    const top = stab.slice(0, 30);
    GI.set('gi-stab', GI.card('Stabilisation points', 'The sample at which a metric is 70% signal: with r(n) = n/(n + k), n₀.₇ = 7k/3; the catalogue shrinks each value by (n·x + k·mean)/(n + k)', GI.chartBox('gl-stab', Math.max(300, top.length * 20 + 40), 'Stabilisation points')));
    GI.ch.bar('gl-stab', { cats: top.map(e => e.label + ' (' + (e.unit || 'plays') + ')'), series: [{ name: 'Stabilises at', data: top.map(e => Math.round(e.stabilises_at)) }], horizontal: true, labels: true, fmt: v => GI.int(v), labelWidth: 200, valName: 'Sample at 70% signal', hrefs: top.map(e => '#/glossary/' + encodeURIComponent(e.key)) });
  });
  el.querySelectorAll('.gi-toc a[data-target]').forEach(a => a.addEventListener('click', ev => {
    ev.preventDefault();
    const t = document.getElementById(a.dataset.target);
    if (t) t.scrollIntoView({ block: 'start' });
    GI.setHashQuiet(a.getAttribute('href'));
  }));
  const want = want0;
  if (want) { const t = document.getElementById('method-' + String(want).replace(/^m-/, '')); if (t) setTimeout(() => t.scrollIntoView({ block: 'start' }), 30); }
});

GI.route('glossary', function (el, params) {
  const key = params.id || (params.query || {}).k || '';
  return GI.load('glossary.json').then(g => {
    if (!el.isConnected) return;
    const M = GI.METHOD || {};
    const groups = GI.ok(g) ? (g.groups || []) : [];
    const MT = (M.MODEL_TERMS || []).map(x => [x[0], x[1].slice()]);
    ((g || {}).model || []).forEach(t => { let grp = MT.find(x => x[0] === (t.group || 'Models')); if (!grp) { grp = [t.group || 'Models', []]; MT.push(grp); } if (!grp[1].some(y => y[1] === t.label)) grp[1].push([t.key + '_model', t.label, t.desc]); });
    const used = {};
    const entry = (e, isModel) => {
      let id = e.key;
      if (used[e.key]) { id = e.key + '-' + used[e.key]; used[e.key]++; } else used[e.key] = 1;
      const tags = [];
      if (isModel) tags.push('model term');
      else {
        if (e.lower) tags.push('lower is better');
        if (e.scope && e.scope !== 'all') tags.push(e.scope === 'style' ? 'tendency' : String(e.scope));
        if (isNum(e.stabilises_at)) tags.push('stabilises ~' + GI.int(e.stabilises_at) + ' ' + (e.unit || 'plays'));
      }
      return '<div class="gi-gl-e" id="gl-' + esc(id) + '" data-q="' + esc(GI.fold([e.label, e.key, e.desc, e.group, e.scope].join(' '))) + '" data-scope="' + (isModel ? 'model' : 'metric') + '"><dt><a href="#/glossary/' + encodeURIComponent(e.key) + '">' + esc(e.label || e.key) + '</a>' +
        tags.map(t => '<span class="qk-badge">' + esc(t) + '</span>').join('') + '</dt><dd>' + (e.desc ? esc(GI.copyText(GI.cleanDesc(e.desc))) : '<span class="qk-muted">No definition yet.</span>') + '</dd></div>';
    };
    const cards = groups.map(x => ({ name: x.name, sl: slug(x.name), html: (x.entries || []).map(e => entry(e, false)).join(''), n: (x.entries || []).length }))
      .concat(MT.map(x => ({ name: 'Terms: ' + x[0], sl: 'model-' + slug(x[0]), html: x[1].map(t => entry({ key: t[0], label: t[1], desc: t[2] }, true)).join(''), n: x[1].length })));
    const stab = [];
    groups.forEach(x => (x.entries || []).forEach(e => { if (isNum(e.stabilises_at) && !stab.some(r => r.key === e.key)) stab.push(Object.assign({ _g: x.name }, e)); }));
    stab.sort((a, b) => a.stabilises_at - b.stabilises_at);
    const N = (g || {}).notices || {};
    el.innerHTML = GI.pageHead('Model', 'Glossary', 'Every metric the site computes for players and teams, and the terms the pages use. Search first; the definitions are grouped below.') + GI.sectionNav('model', 'glossary') +
      '<div class="gi-gl-search"><input id="gl-search" class="qk-input" type="search" placeholder="Search the glossary: EPA, CPOE, value, pressure…" aria-label="Search the glossary"></div><div class="gi-toolbar">' + GI.field('Show', GI.select('gl-kind', [['', 'Metrics and terms'], ['metric', 'Catalogue metrics'], ['model', 'Terms and models']], '', 'Show')) + '<span class="qk-sub" id="gl-count"></span></div>' +
      '<div class="qk-chips scroll gi-gl-index" style="margin-top:10px">' + cards.map(c => '<a class="qk-chip" href="#/glossary/g:' + esc(c.sl) + '" data-group="' + esc(c.sl) + '">' + esc(c.name) + ' <span class="n">' + c.n + '</span></a>').join('') + '</div>' +
      '<p class="gi-cap">How many plays each metric needs before it means much: the stabilisation points are under <a href="#/methodology">How it works › Technical detail</a>.</p>' +
      cards.map(c => '<section class="qk-card gi-gl-group gi-mt" data-group="' + esc(c.sl) + '" id="glg-' + esc(c.sl) + '"><div class="qk-card-head"><div class="gi-card-titles"><h3 class="qk-card-title">' + esc(c.name) + '</h3><div class="qk-card-sub">' + c.n + '</div></div></div><div class="qk-card-body"><dl class="gi-gl-list">' + c.html + '</dl></div></section>').join('') +
      '<div id="gl-none" hidden>' + QK.empty('Nothing matches', 'Try a shorter word.') + '</div>' +
      GI.card('Data credits', '', '<div class="gi-prose"><p>' + esc(N.nflverse || M.NFLVERSE || '') + '</p><p>' + esc(N.ftn || M.FTN || '') + '</p><p>' + esc(N.ngs || M.NGS || '') + '</p></div>', { cls: 'gi-mt' });
    const input = el.querySelector('#gl-search'), kind = el.querySelector('#gl-kind'), count = el.querySelector('#gl-count');
    const entries = Array.prototype.slice.call(el.querySelectorAll('.gi-gl-e')), groupsEl = Array.prototype.slice.call(el.querySelectorAll('.gi-gl-group'));
    const filter = () => {
      const needle = GI.fold(input.value.trim()), kd = kind.value;
      let shown = 0;
      entries.forEach(e => { const hit = (!needle || needle.split(/\s+/).every(w => e.dataset.q.indexOf(w) >= 0)) && (!kd || e.dataset.scope === kd); e.hidden = !hit; if (hit) shown++; });
      groupsEl.forEach(c => { c.hidden = !c.querySelector('.gi-gl-e:not([hidden])'); });
      el.querySelector('#gl-none').hidden = !!shown;
      count.textContent = needle || kd ? shown + ' of ' + entries.length + ' entries' : entries.length + ' entries';
    };
    input.addEventListener('input', filter);
    kind.addEventListener('change', filter);
    filter();
    el.querySelectorAll('.gi-gl-index a').forEach(a => a.addEventListener('click', ev => { ev.preventDefault(); const t = el.querySelector('#glg-' + a.dataset.group); if (t) { t.hidden = false; t.scrollIntoView({ block: 'start' }); } GI.setHashQuiet(a.getAttribute('href')); }));
    if (key) {
      if (key.indexOf('g:') === 0) { const t = el.querySelector('#glg-' + key.slice(2).replace(/[^a-z0-9-]/g, '')); if (t) setTimeout(() => t.scrollIntoView({ block: 'start' }), 30); }
      else {
        const e = document.getElementById('gl-' + key);
        if (e) { e.classList.add('gi-hit'); setTimeout(() => e.scrollIntoView({ block: 'center' }), 60); }
        else { input.value = key.replace(/_/g, ' '); filter(); }
      }
    }
  });
});

GI.route('disclaimer', function (el) {
  const t = document.getElementById('disclaimer-template');
  el.innerHTML = GI.pageHead('Model', 'Disclaimer and terms', '') + GI.sectionNav('model', 'disclaimer') + GI.card('', '', '<div class="gi-prose">' + (t ? t.innerHTML : '') + '</div>');
});

})(window.GI);
