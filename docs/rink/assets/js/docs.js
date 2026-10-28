/* The Quant Rink — docs: the glossary (#/glossary, #/glossary/<key>, #/glossary/g:<group>) and the methodology
 * (#/methodology, #/methodology/<section>).
 *
 * The glossary reads data/glossary.json ({groups: [{name, entries: [METRIC + kind, unit]}], model: [{key, label, group,
 * desc}], notices}); until that is published it is assembled from the season's skater and goalie catalogues. The
 * methodology is static text: every constant in it was read from the Python under oddsmarkets/nhl/ (canon.py, derive.py,
 * sources/*.py, models/*.py, analytics/*.py) on 1 October 2026, and each section names its source files. Fitted values
 * (the gradient-boosted xG model, ridge penalties chosen by cross-validation, stabilisation constants, the game model's
 * coefficients) are refitted with the models and shown on the pages and the calibration page. Uses RK.fk where present. */
(function (RK) {
'use strict';

const K = () => RK.fk;
const esc = s => (typeof RK.esc === 'function' ? RK.esc(s) : String(s === null || s === undefined ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'));
const muted = t => '<div class="muted">' + t + '</div>';
const fold = s => String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
const clean = s => (K() && K().cleanDesc ? K().cleanDesc(s) : String(s || ''));
const MP = () => (RK.MONEYPUCK_CREDIT || 'xG benchmark data from MoneyPuck.com');
const NHL_NOTE = 'NHL data (play-by-play, shift charts, boxscores, standings, rosters and NHL EDGE tracking aggregates) is shown for informational, non-commercial use. The Quant Rink has no affiliation with the NHL, the NHLPA, any team or player, ESPN or any bookmaker, and uses no logos.';

/* Fitted values quoted in the methodology: FV('game.tie_k', '0.40', '2') renders the committed value as written at
 * publication and is refreshed from calibration.json's "fitted" block (the committed fits the site runs on), so the
 * text follows every refit. Formats: a digit = decimals, 'int' = thousands separators, 'pct' = percent (1 dp),
 * 'signed2' / 'signed3' = with a sign, 'season' = 2025–26. */
const FV = (path, fallback, fmt) => '<span class="fitv" data-fit="' + path + '"' + (fmt ? ' data-fmt="' + fmt + '"' : '') + '>' + fallback + '</span>';
function fitGet(o, path) { return String(path).split('.').reduce((a, k) => (a !== null && a !== undefined && typeof a === 'object' ? a[k] : undefined), o); }
function fitFmt(v, f) {
  if (typeof v !== 'number' || !isFinite(v)) return String(v);
  if (f === 'int') return Math.round(v).toLocaleString('en-GB');
  if (f === 'pct') return (100 * v).toFixed(1) + '%';
  if (f === 'season') { const y = Math.floor(v / 10000); return y + '–' + String((y + 1) % 100).padStart(2, '0'); }
  const sg = /^signed(\d)$/.exec(f || '');
  if (sg) return (v < 0 ? '−' : '+') + Math.abs(v).toFixed(+sg[1]);
  if (/^\d$/.test(f || '')) return v.toLocaleString('en-GB', { minimumFractionDigits: +f, maximumFractionDigits: +f });
  return String(v);
}
function fillFitted(root) {
  if (typeof RK.load !== 'function' || !root.querySelector('[data-fit]')) return;
  Promise.resolve(RK.load('calibration.json')).then(d => {
    const F = d && d.fitted;
    if (!F) return;
    root.querySelectorAll('[data-fit]').forEach(sp => {
      const v = fitGet(F, sp.dataset.fit);
      if (v === undefined || v === null || typeof v === 'object') return;
      sp.textContent = fitFmt(v, sp.dataset.fmt);
    });
  }).catch(() => { /* the published text stands */ });
}

// ── glossary ───────────────────────────────────────────────────────────────

/* Terms the pages use that are not catalogue metrics (the build's own "model" entries are merged in). */
const MODEL_TERMS = [
  ['Hockey basics', [
    ['corsi_term', 'Corsi (shot attempts, CF / CA)', 'Every shot attempt: goals, shots on goal, missed shots and blocked shots. CF% is a team\'s share of the attempts while a player (or line) is on the ice.'],
    ['fenwick_term', 'Fenwick (unblocked attempts, FF / FA)', 'Shot attempts that were not blocked: goals, shots on goal and misses. Expected goals are computed on these.'],
    ['strength_term', 'Strength states', '5v5: five skaters a side with both goalies in net. PP (power play) / SH or PK (short-handed): the team has more / fewer skaters. 4v4, 3v3 and empty-net time are counted separately. Regular-season shootouts are excluded from every count.'],
    ['toi_term', 'TOI (time on ice)', 'Minutes on the ice from the NHL\'s shift charts (2010–11 on). Per-60 rates divide a count by TOI and multiply by 60.'],
    ['zone_starts_term', 'Zone starts', 'The zone of the faceoff that starts a shift: offensive (OZ), neutral or defensive (DZ); shifts that begin during play are "on the fly". OZ start % = OZ / (OZ + DZ) faceoffs with the player on the ice.'],
    ['pdo_term', 'PDO', 'On-ice shooting percentage plus on-ice save percentage. It averages 1.000 (or 100) and regresses hard towards it: a team or player far above it is usually riding luck.']
  ]],
  ['Models', [
    ['xg_term', 'Expected goals (xG)', 'The probability that an unblocked attempt becomes a goal, from where and how it was taken and what happened just before it. Summed over shots, it is the number of goals an average shooter would have scored on them.'],
    ['ixg_term', 'ixG (individual expected goals)', 'The sum of the xG of a player\'s own unblocked attempts: the quality and quantity of the chances the player takes.'],
    ['gax_term', 'Goals above expected (GAx)', 'Goals minus ixG. Most of a season\'s GAx is noise; the shooting-talent estimate regresses it by the stabilisation constant of finishing.'],
    ['gsax_term', 'GSAx (goals saved above expected)', 'The xG of the unblocked attempts a goalie faced minus the goals allowed (empty-net goals excluded). Positive is better than an average goalie on the same shots.'],
    ['danger_term', 'Danger bands', 'Unblocked attempts with xG under 0.08 are low danger, 0.08 to 0.20 medium, 0.20 or more high (MoneyPuck\'s bands).'],
    ['rapm_term', 'RAPM', 'Regularised adjusted plus-minus: a ridge regression on every 5-on-5 stint that gives each skater an offence and a defence coefficient (xG per 60 added for the team and taken away from the opponent), with team-mates, opponents, zone starts, score, home ice and back-to-backs controlled.'],
    ['gar_term', 'Rink value (GAR / WAR)', 'Goals above replacement: RAPM at 5 on 5 (with a box-score prior), the power play and penalty kill, shooting talent and penalties, against a replacement-level player; WAR divides by the goals a win costs. Goalies: GSAx against replacement goaltending.']
  ]],
  ['Statistics on the pages', [
    ['percentile_term', 'Percentile', 'Where a player ranks against the qualified pool (100 = best, reversed where less is better), after shrinking the value towards the pool mean by the metric\'s stabilisation constant. Each metric needs its sample floor first (counts, GSAx, RAPM and value: 5 games; goalies 3). The position pool compares forwards with forwards and defencemen with defencemen.'],
    ['stabilisation_term', 'Stabilisation point', 'The sample at which a metric\'s split-half reliability reaches 0.7: with r(n) = n / (n + k), n₀.₇ = 7k/3. Before it, the number is mostly noise.'],
    ['qualified_term', 'Qualified', 'Skaters: at least 250 minutes at 5 on 5 per 82 team games (prorated during the season). Goalies: at least a quarter of the team\'s minutes. Others show values without percentiles.'],
    ['era_term', 'Era-adjusted (+)', '100 + 10 z against that season\'s qualified players in the same position group, so seasons are compared with their own league.'],
    ['devig', 'De-vig', 'Removing the bookmaker\'s margin: the implied probabilities are scaled so that they sum to one.'],
    ['log_loss', 'Log-loss', '−mean(y ln p + (1 − y) ln(1 − p)); lower is better; a coin scores ln 2 = 0.693.'],
    ['brier_term', 'Brier score', 'mean((p − y)²); lower is better; a coin scores 0.25.']
  ]]
];

function slug(s) { return String(s || 'group').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''); }

function loadGlossary() {
  return RK.load('glossary.json').then(g => {
    if (g && g.ok !== false && ((g.groups || []).length || (g.metrics || []).length)) {
      if (!(g.groups || []).length) {
        const groups = [];
        g.metrics.forEach(m => { let grp = groups.find(x => x.name === (m.group || 'Other')); if (!grp) { grp = { name: m.group || 'Other', entries: [] }; groups.push(grp); } grp.entries.push(m); });
        return Object.assign({ source: 'payload' }, g, { groups: groups });
      }
      return Object.assign({ source: 'payload' }, g);
    }
    const k = K(), S = k ? k.S({}, RK.state) : null;
    return Promise.all([RK.load(S + '/skaters.json'), RK.load(S + '/goalies.json')]).then(res => {
      const groups = [];
      res.forEach((cat, i) => ((cat || {}).metrics || []).forEach(m => {
        const gname = (['Skaters', 'Goalies'][i]) + ': ' + (m.group || 'Other');
        let grp = groups.find(x => x.name === gname);
        if (!grp) { grp = { name: gname, entries: [] }; groups.push(grp); }
        grp.entries.push(Object.assign({}, m, { kind: ['skater', 'goalie'][i] }));
      }));
      return { groups: groups, source: 'catalogue' };
    });
  });
}

function tagsOf(e) {
  const tags = [];
  const f = e.fmt;
  if (f === 'pct') tags.push(['rate', '']);
  else if (f === 'prob') tags.push(['probability', '']);
  else if (f === 'int') tags.push(['count', '']);
  else if (f === 'p60') tags.push(['per 60', '']);
  else if (f === 'goals') tags.push(['goals', 'model']);
  if (e.lower) tags.push(['lower is better', 'lower']);
  if (e.scope && !/^(all)$/.test(e.scope)) tags.push([String(e.scope), 'out']);
  if (typeof e.stabilises_at === 'number') tags.push(['stabilises ~' + Math.round(e.stabilises_at).toLocaleString('en-GB') + ' ' + (e.unit || 'minutes'), 'gk']);
  return tags.map(t => '<span class="gl-tag' + (t[1] ? ' ' + t[1] : '') + '">' + esc(t[0]) + '</span>').join('');
}
let USED_IDS = {};
function entryHTML(e, isModel) {
  const q = [e.label, e.key, e.desc, e.group, e.scope, e.kind, isModel ? 'model' : ''].join(' ');
  let id = e.key;
  if (USED_IDS[e.key]) { id = e.key + '-' + (e.kind || 'x') + '-' + USED_IDS[e.key]; USED_IDS[e.key] += 1; } else USED_IDS[e.key] = 1;
  return '<div class="gl-entry" id="gl-' + esc(id) + '" data-q="' + esc(fold(q)) + '" data-scope="' + esc(isModel ? 'model' : 'metric') + '">' +
    '<dt><span>' + esc(e.label || e.key) + ' <a class="doc-anchor" href="#/glossary/' + encodeURIComponent(e.key) + '" title="Link to this entry">#</a></span>' +
    '<span class="gl-tags">' + (isModel ? '<span class="gl-tag model">model term</span>' : tagsOf(e)) + (e.kind && !isModel ? '<span class="gl-tag">' + esc(e.kind) + '</span>' : '') + '</span></dt>' +
    '<dd>' + (e.desc ? esc(clean(e.desc)) : '<span class="muted-inline">No definition yet.</span>') + '</dd></div>';
}

function renderGlossary(el, params) {
  const key = params.id || (params.rest || [])[0] || (params.query || {}).k || '';
  el.innerHTML = '<div id="glossary-root">' + muted('Loading the glossary…') + '</div>';
  return loadGlossary().then(g => {
    const root = document.getElementById('glossary-root');
    if (!root || !el.isConnected) return;
    const groups = (g.groups || []).map(x => ({ name: x.name, entries: (x.entries || []).filter(e => e && e.key) })).filter(x => x.entries.length);
    USED_IDS = {};
    const MT = MODEL_TERMS.map(x => [x[0], x[1].slice()]);
    (g.model || []).forEach(t => { let grp = MT.find(x => x[0] === 'Models: ' + (t.group || 'Other')); if (!grp) { grp = ['Models: ' + (t.group || 'Other'), []]; MT.push(grp); } grp[1].push([t.key + '_model', t.label, clean(t.desc)]); });
    const nMetrics = groups.reduce((s, x) => s + x.entries.length, 0);
    const nModel = MT.reduce((s0, x) => s0 + x[1].length, 0);
    const nStab = groups.reduce((s, x) => s + x.entries.filter(e => typeof e.stabilises_at === 'number').length, 0);
    const index = groups.map(x => '<a href="#/glossary/g:' + esc(slug(x.name)) + '" data-group="' + esc(slug(x.name)) + '">' + esc(x.name) + '</a>').join('') +
      MT.map(x => '<a href="#/glossary/g:model-' + esc(slug(x[0])) + '" data-group="model-' + esc(slug(x[0])) + '">' + esc(x[0]) + '</a>').join('');
    /* round 9: each group folds (the page ran to 20,000 px); a search opens the groups it finds */
    const cardOf = (name, sl, entries, isModel) => '<details class="card gl-group rk-glg" data-group="' + esc(sl) + '"><summary class="card-header">' + esc(String(name).replace(/EDGE tracking/, 'Puck and player tracking')) + ' <span class="card-sub">' + entries.length + '</span></summary><dl class="gl-list">' + entries.map(e => entryHTML(e, isModel)).join('') + '</dl></details>';
    const N = g.notices || {};
    /* Round 9 (28 Oct 2026): search first, then the groups; the stabilisation table lives on Model › How it works */
    root.innerHTML =
      '<div class="gl-top gl-first"><input id="gl-search" type="search" placeholder="Search every metric and term: xG, RAPM, save %…" autocomplete="off" spellcheck="false" aria-label="Search the glossary">' +
      '<select id="gl-kind" aria-label="Show"><option value="">Metrics and terms</option><option value="metric">Metrics</option><option value="model">Terms and models</option></select><span class="gl-count" id="gl-count"></span></div>' +
      '<div class="gl-index">' + index + '</div>' +
      '<p class="doc-meta">' + nMetrics + ' metrics in ' + groups.length + ' groups and ' + nModel + ' terms. How many games each number needs before it means something is on <a class="qk-link" href="#/model?tab=methodology&go=stab">How it works</a>.</p>' +
      groups.map(x => cardOf(x.name, slug(x.name), x.entries, false)).join('') +
      MT.map(x => cardOf('Terms: ' + x[0], 'model-' + slug(x[0]), x[1].map(t => ({ key: t[0], label: t[1], desc: t[2] })), true)).join('') +
      '<div class="card gl-empty" id="gl-none" style="display:none">Nothing in the glossary matches that.</div>' +
      '<div class="card"><div class="card-header">Data credits</div><div class="gq-read"><p>' + esc(N.nhl || NHL_NOTE) + '</p><p>' + esc(N.moneypuck || MP()) + ' (used only as a benchmark for our own expected-goals model, non-commercially and with credit).</p><p>Betting lines and the probable starting goalies before each game from ESPN\'s public feeds; prediction-market numbers from Kalshi and Polymarket\'s public APIs.</p></div></div>';
    const input = document.getElementById('gl-search'), kindSel = document.getElementById('gl-kind'), count = document.getElementById('gl-count');
    const entries = Array.prototype.slice.call(root.querySelectorAll('.gl-entry'));
    const cards = Array.prototype.slice.call(root.querySelectorAll('.gl-group'));
    const total = entries.length;
    const filter = () => {
      const needle = fold(input.value.trim()), kind = kindSel.value;
      let shown = 0;
      entries.forEach(e => {
        const hit = (!needle || needle.split(/\s+/).every(w => e.dataset.q.indexOf(w) >= 0)) && (!kind || e.dataset.scope === kind);
        e.classList.toggle('hidden', !hit); if (hit) shown++;
      });
      cards.forEach(c => { c.classList.toggle('hidden', !c.querySelector('.gl-entry:not(.hidden)')); if (needle) c.open = !c.classList.contains('hidden') && shown <= 60; });
      document.getElementById('gl-none').style.display = shown ? 'none' : '';
      count.textContent = needle || kind ? shown + ' of ' + total + ' entries' : total + ' entries';
    };
    input.addEventListener('input', filter);
    input.addEventListener('keydown', ev => { if (ev.key === 'Escape') { input.value = ''; filter(); } });
    kindSel.addEventListener('change', filter);
    filter();
    root.querySelectorAll('.gl-index a').forEach(a => a.addEventListener('click', ev => {
      ev.preventDefault();
      const grp = root.querySelector('.gl-group[data-group="' + a.dataset.group + '"]');
      if (grp) { grp.classList.remove('hidden'); grp.open = true; grp.scrollIntoView({ block: 'start' }); }
      try { history.replaceState(null, '', a.getAttribute('href')); } catch (e) { /* ok */ }
    }));
    if (key) {
      if (key.indexOf('g:') === 0) {
        const grp = root.querySelector('.gl-group[data-group="' + key.slice(2).replace(/"/g, '') + '"]');
        if (grp) { grp.open = true; setTimeout(() => grp.scrollIntoView({ block: 'start' }), 0); }
      } else {
        const e = document.getElementById('gl-' + key);
        if (e) { if (e.closest('details')) e.closest('details').open = true; e.classList.add('hit'); setTimeout(() => e.scrollIntoView({ block: 'center' }), 50); setTimeout(() => e.scrollIntoView({ block: 'center' }), 400); }
        else { input.value = key.replace(/_/g, ' '); filter(); }
      }
    }
  });
}

// ── methodology ────────────────────────────────────────────────────────────

const SRC = f => '<span class="src">oddsmarkets/nhl/' + f + '</span>';

const METHOD_HTML = [
`<section id="m-overview"><h2>What the site does</h2>
<p>The Quant Rink forecasts every NHL game, the season and the playoffs with its own models, checks those forecasts against the closing lines and the prediction markets, and backs them with play-level analytics from 2009–10: our own expected goals, goaltending against expected, on-ice rates adjusted for score and venue, regularised adjusted plus-minus, player value, lines and deployment.</p>
<p>Five layers carry it. <strong>Data</strong>: the NHL's play-by-play and shift charts become one table of events and one of stints (stretches of play with the same players on the ice). <strong>Shot and player models</strong>: expected goals, finishing, goaltending, on-ice rates, RAPM, Rink value, lines and stabilisation. <strong>Catalogues</strong>: every skater and goalie rated on ${FV('catalogues.skaters.metrics', '138', 'int')} and ${FV('catalogues.goalies.metrics', '45', 'int')} metrics with stabilisation-aware percentiles. <strong>Team strength and the game model</strong> turn units into goal expectations and a score distribution for every game, and a <strong>season simulation</strong> plays out the rest of the schedule with the NHL's tiebreakers and playoff format. A walk-forward <strong>backtest</strong> scores it all on the <a href="#/calibration">calibration page</a>.</p>
<p>Every constant below is the value in the code on 1 October 2026; each section names its source files. Fitted quantities (the expected-goals model, ridge penalties chosen by cross-validation, stabilisation constants, the game model's coefficients) are refitted and shown on the pages and the calibration page.</p></section>`,

`<section id="m-data"><h2>Data sources and terms</h2>
<h3>The NHL</h3>
<p><strong>api-web.nhle.com/v1</strong> (no key): the schedule (<code>/schedule/{date}</code>, a week from the date), play-by-play (<code>/gamecenter/{id}/play-by-play</code>: every event with its period time, the situation code, coordinates, shot type and the players involved), boxscores (starting goalies, ice time), standings, rosters, player landing pages and the DraftKings partner odds for today's games. Only dated URLs are called ("now" and "current" forms answer 307 to a dated form). <strong>api.nhle.com/stats/rest/en</strong>: the shift charts (one row per shift, 2010–11 on; 2009–10 answers empty), season reports for skaters, goalies and teams (totals back to each player's debut) and the season list. <strong>NHL EDGE</strong> (<code>/v1/edge/...</code>, 2021–22 on): skating speed and bursts, distance, shot speed and zone time per skater, goalie shot-location summaries and team tracking, as season aggregates with the league's own percentiles; a page answers 404 for 2020–21 and earlier and for players with no tracked games.</p>
<p class="doc-note">${esc(NHL_NOTE)}</p>${SRC('sources/nhl.py')}${SRC('sources/stats.py')}${SRC('sources/edge.py')}
<h3>MoneyPuck (benchmark only)</h3>
<p>MoneyPuck's season shot files (<code>shots_{YYYY}.zip</code>, 2007–08 on, linked from moneypuck.com/data.htm) are downloaded at most nightly, never scraped, slimmed to the columns used and joined to our events on game, elapsed second and shooter (99.8% of 2026–27's first rows match). Their xGoal is used only to benchmark our model on the same shots.</p>
<p class="doc-note">${esc(MP())}. Free for non-commercial use with credit.</p>${SRC('sources/moneypuck.py')}
<h3>ESPN</h3>
<p>The public scoreboard and game summaries (DraftKings moneyline, puck line and total with opening and closing blocks) and ESPN's core odds endpoint (several books per game: international books from 2019–20, US books with open and close blocks from 2022–23). The puck line is stored as the home team's line, negative when the home side is favoured (checked on three dated games). In-play rows ("Live Odds") are dropped; a book whose quoted numbers look like in-play captures (a moneyline overround outside 1.00–1.15, or a total a goal from the median) is flagged and never chosen as the main line. ESPN events map to NHL games by the two teams and the nearest start within 30 hours. Requests are paced at most one a second.</p>
<p>The same scoreboard lists each team's probable starting goalie ("Expected", then "Confirmed") until the game starts. Every read before the start is kept with its time (first seen, first confirmed, each change), because ESPN rewrites the field to the actual starter afterwards; it costs no extra request. Upcoming games are forecast with these starters when the name maps to an NHL id (otherwise with the team's usual starter), and the game page shows the effect against each team's usual starter. In 256 archived pre-game scoreboards (Wayback Machine snapshots, 2024–26) ESPN's projected starter was right 78% of the time and its confirmed starter 98%, against 70% for the expected-starter rule of our backtests (the most frequent recent starter, the other goalie on the second night of a back-to-back) on the same games.</p>${SRC('sources/espn.py')}
<h3>Prediction markets</h3>
<p>Kalshi (Stanley Cup, conference and division winners, playoffs, the Presidents' Trophy, season points ladders, awards, and game winner, spread, total and overtime markets) and Polymarket (tag "nhl" futures and the per-game series). See <a href="#/methodology/markets">markets and de-vig</a>.</p>${SRC('sources/markets.py')}
<h3>The client</h3>
<p>One paced client serves every source: requests are spaced per host (0.25 s for the NHL hosts, 1 s for ESPN), retried with back-off on network errors, HTTP 429 and server errors (honouring Retry-After), counted against a budget so a backfill stops cleanly and resumes, and never raise on a bad answer; a 404 is an answer. A 120 s timeout. Its user agent names the site and says it is non-commercial.</p>${SRC('sources/_client.py')}</section>`,

`<section id="m-identity"><h2>Identity, coverage and conventions</h2>
<p>Seasons are the NHL's ids (<code>20262027</code>, shown 2026–27). Games are NHL gameIds (<code>2026020009</code>: the season's start year, the type, 02 regular season or 03 playoffs, and the number); players NHL playerIds; teams the tri-codes the NHL used that season. Relocations and renames: Atlanta to Winnipeg (ATL to WPG, 2011–12), Phoenix renamed Arizona (PHX to ARI, 2014–15), Arizona's hockey assets to Utah (UTA, 2024–25; the NHL lists Utah as a new franchise); Vegas joined in 2017–18 and Seattle in 2021–22. Model priors carry a club's history across these moves (ATL to WPG, PHX and ARI to UTA).</p>
<p>Formats: 82 games (48 in 2012–13, 56 in 2020–21, 2019–20 paused at 68 to 71 games), 84 from 2026–27. Points: a win 2, an overtime or shootout loss 1. Regular-season overtime is five minutes (4-on-4 to 2014–15, 3-on-3 from 2015–16) then a shootout; the NHL credits the shootout winner with one goal. Playoff overtime is 20-minute periods at 5 on 5. Divisions: six to 2012–13, four from 2013–14, four realigned COVID divisions without conferences in 2020–21, Seattle in the Pacific and Arizona (then Utah) in the Central from 2021–22.</p>
<p>Coverage: play-by-play with coordinates from 2009–10; shift charts (and so time on ice, on-ice rates, RAPM, lines, deployment) from 2010–11; NHL EDGE from 2021–22; ESPN lines by book from 2019–20, with opening and closing lines from 2022–23; MoneyPuck shots from 2007–08. Payloads round probabilities to 4 decimals and rates per 60 to 2; fractions are stored 0–1. The puck line is always the home team's line.</p>${SRC('canon.py')}${SRC('store.py')}${SRC('analytics/__init__.py')}</section>`,

`<section id="m-events"><h2>Events, shifts and stints</h2>
<p>Every play-by-play event becomes one row: period, seconds into the period and elapsed game seconds, type, the event's team (the shooting team for every shot, blocked shots included; the faceoff winner; the hitter; the penalised club), coordinates as published and <strong>normalised so the event team attacks +x</strong>, the zone (blue lines at ±25 ft), shot type, shooter, goalie in net, assists, the situation code decoded into skaters and goalies per side, the strength from the event team's view (5v4 and so on), the score before the event, and the players on the ice from the shift charts.</p>
<p><strong>Direction</strong>: per period, the home team's attacking direction is the majority sign of x over unblocked shots taken more than 25 ft from centre (home shots positive, away shots negative); a period without such shots falls back to the published defending side (about 2019–20 on), then to the opposite of the previous period. Every normalised shot zone is checked against the NHL's own zone code.</p>
<p><strong>On ice</strong> at an event at second t: a player whose shift satisfies start &lt; t ≤ end (players leaving at a stoppage were on for the event, those arriving were not); faceoffs and period starts take start ≤ t &lt; end (the new players take the draw). Counts are checked against the situation code; for penalties and stoppages the players just after the call are also accepted, because the published code often already shows the post-call state.</p>
<p><strong>Stints</strong>: each period is cut at every shift start and end, and consecutive pieces with the same skaters and goalies on both sides are merged. Each stint carries its duration, the players, the strength (home view), the score at its start, the zone of a faceoff at its first second (or on the fly), both teams' back-to-back flags and the counts for and against: attempts (Corsi), unblocked attempts (Fenwick), shots on goal, goals and expected goals. An event belongs to the stint whose players were on the ice for it, by the same rule.</p>${SRC('derive.py')}${SRC('models/_stints.py')}</section>`,

`<section id="m-xg"><h2>Expected goals</h2>
<p>Rows: every unblocked attempt (goals, shots on goal, misses) with coordinates, outside the shootout and penalty shots. Label: goal. Features, all from the shooter's frame (attacking +x towards the net at (89, 0)): distance; angle (degrees off the goal-line normal, above 90 behind the net); x and |y|; shot type; <strong>rebound</strong> (the previous event an attempt by the same team within 3 s) and the angle change on it; <strong>rush</strong> (the previous event in the neutral or defensive zone within 4 s); seconds and feet since the previous event and its speed, its type and its x; skaters for and against; an empty net; the score state (the shooter's lead clipped to ±3); home; period and game seconds; and the shooter's <strong>handedness</strong> as hand_y = y for a left shot and −y for a right shot (positive = shooting from the off wing; a skater's hand is read from any season's roster, because some seasons' rosters miss it). Since October 2026 also: the previous event's y and whether it was the shooting team's; the type of, and seconds since, the event two back; seconds since the period's last faceoff and its zone from the shooter's side; attempts by the shooting team and by the other team in the previous 10 seconds; seconds since the strength state changed; whether the shooter is a defenceman; and, from the shift charts, how long the shooter has been on the ice in the current shift and the mean current-shift time of the shooting and the defending skaters. Attempts at an empty net are scored by a separate small logistic regression (distance, angle), not the boosted model.</p>
<p><strong>Arena adjustment</strong>: coordinates before 2023–24 carry rink-specific biases. Per arena and season, the distances of all attempts in a team's home games are mapped through their empirical distribution onto the quantiles of the distances in the same team's road games (its shots and its opponents', recorded by other rinks' scorers), at the 1st to 99th percentiles, two passes so the reference rinks are themselves adjusted, for arenas with at least 300 shots; the angle is kept and (x, y) recomputed at the new distance. Seasons from 2023–24 are left alone. The cut-off comes from the data, not the calendar of the NHL's tracking roll-out (2020–21): the spread of arenas' home-to-road distance ratios is about 0.07 (standard deviation) through 2021–22 and 0.04 in 2022–23, and falls to the sampling noise (about 0.025) only in 2023–24.</p>
<p><strong>Model</strong>: LightGBM binary (learning rate 0.04, 31 leaves, at least 300 shots per leaf, L2 10, feature fraction 0.85), <strong>walk-forward</strong>: each season is scored by a model trained only on the seasons before it, with each earlier season weighted 0.5<sup>(years back)</sup> (a one-season half-life: how shots turn into goals drifts, and the latest seasons say most about the next), early-stopped on a 10% holdout of games and Platt-recalibrated (a + b·logit p) on that holdout. The current season is scored by the model trained on every completed season, weighted the same way from the last one. Tested on 2025–26, held out, this model's shot log-loss is 0.2186 against 0.2257 for the October 2026 model trained the same way (difference −0.0071, 95% CI −0.0077 to −0.0065), and its calibration is better. Danger bands: low under 0.08, medium 0.08 to 0.20, high 0.20 or more.</p>
<div class="eq">xG(shot) = σ(a + b · logit f(features))      ixG = Σ xG over a player's unblocked attempts      GAx = goals − ixG</div>
<p><strong>Benchmark</strong>: MoneyPuck's xGoal on the same shots (matched on game, period, second and shooter): log-loss and AUC on the matched shots, and team-season and player-season correlations of summed xG. MoneyPuck's model was trained on earlier seasons, so on those seasons its numbers are in-sample; 2026–27 is out of sample for both, and there MoneyPuck's was 0.011 better a shot than our October model and is 0.003 better than this one (95% CI 0.000 to 0.006, 9,841 shots to 17 October). When our model does not score a season the build falls back to a ridge-penalised logistic regression on the season's own attempts (distance, its log and square, angle, distance × angle, shot type, rebound, rush, strength) and says so (<code>xg_source</code>).</p>${SRC('models/xg.py')}${SRC('analytics/xgfallback.py')}</section>`,

`<section id="m-shooting"><h2>Shooting talent</h2>
<p>On a manned net (empty-net attempts carry no finishing signal), per shooter and season: unblocked attempts, shots on goal, goals, ixG and GAx = goals − ixG. Finishing talent is GAx per attempt regressed to the league (zero) by the stabilisation constant k of finishing, the posterior mean under a normal prior on skill:</p>
<div class="eq">talent = GAx / (attempts + k)      GAx shrunk = attempts × talent = GAx × attempts / (attempts + k)</div>
<p>Shooting percentage is also shown raw and shrunk by its own constant. Most of a season's goals above expected is noise: k for finishing is in the thousands of attempts (the default before fitting is 1,500), against a few hundred for most shooters in a season.</p>${SRC('models/shooting.py')}</section>`,

`<section id="m-goalies"><h2>Goaltending</h2>
<p>Every unblocked attempt on a manned net is charged to the goalie in it. Per goalie and season: attempts faced (fa), shots on goal faced (sa), goals against and summed xG against:</p>
<div class="eq">GSAx = xGA − GA      GSAx/100 = 100 · GSAx / fa      xSv% = 1 − xG on shots on goal / shots on goal      dSv% = Sv% − xSv%
talent = GSAx / (fa + k),  GSAx shrunk = fa · talent</div>
<p>GSAx is split by danger band (low, medium, high) and by shot type (wrist, snap, slap, backhand, tip-in, deflected, wrap-around, other), and by rebound and rush; the bands and the types partition the attempts, so each set sums to the total exactly. Empty-net goals are excluded. Rebounds a goalie allows are themselves attempts and count against the goalie. The catalogue's qualified pool is goalies with a quarter of their team's minutes; a percentile needs 100 unblocked attempts faced. Save percentage takes thousands of shots to stabilise, which is why the site leads with GSAx and shrinks it.</p>${SRC('models/goalies.py')}${SRC('analytics/goalies.py')}</section>`,

`<section id="m-onice"><h2>On-ice rates and score and venue adjustment</h2>
<p>For every skater and strength role (5v5; the power play, the skater's side with more skaters and both nets manned; the penalty kill, the reverse): time on ice and the on-ice counts for and against (CF/CA, FF/FA, SF/SA, GF/GA, xGF/xGA) as per-60 rates and shares (CF%, FF%, xGF%, GF%).</p>
<p><strong>Score and venue adjustment</strong> (McCurdy-style): at 5v5 an event by a side leading by d (clipped to ±3) at venue v gets weight 0.5 / s(d, v), with s the league's share of that metric taken by such sides that season (goals take the xG weights), clipped to [0.7, 1.4]. Trailing teams shoot more and home scorers are generous; the weights take both out.</p>
<p><strong>Relative to team</strong> (5v5): off-ice = the team's 5v5 totals minus the player's on-ice totals; rel per 60 = on − off, rel % = on% − off%; a traded player's values are weighted by ice time across the player's teams. <strong>Deployment</strong>: OZ start % = offensive-zone faceoff starts / (offensive + defensive) over the stints the player started; quality of competition and of teammates are time-weighted means of the opponents' and teammates' 5v5 minutes per game, or their on-ice xGF%.</p>${SRC('models/onice.py')}${SRC('models/_stints.py')}${SRC('analytics/skaters.py')}</section>`,

`<section id="m-rapm"><h2>RAPM</h2>
<p>Each 5v5 stint (both nets manned, five skaters a side) gives two observations, one per attacking side, weighted by its duration in minutes:</p>
<div class="eq">y = 3600 · metric_for / duration
  = μ + Σ<sub>attackers</sub> O<sub>i</sub> − Σ<sub>defenders</sub> D<sub>j</sub> + h · home + z<sub>O</sub>·OZ start + z<sub>D</sub>·DZ start + z<sub>N</sub>·NZ start
    + Σ<sub>s</sub> c<sub>s</sub> · [attacking lead = s] + b<sub>a</sub> · attacker on a back-to-back + b<sub>d</sub> · defender on a back-to-back + ε</div>
<p>O<sub>i</sub> is the xG per 60 a skater adds to the team and D<sub>j</sub> the xG per 60 the skater takes away from the opponent (positive is good defence); net = O + D. The faceoff zone is from the attacking side's view (on the fly is the baseline), the lead states are −2 or worse, −1, +1, +2 or better (tied is the baseline). Ridge (Bayesian) least squares: O<sub>i</sub>, D<sub>i</sub> ~ N(m<sub>i</sub>, σ²/λ) with m = 0.7 × last season's estimate (sequential multi-season fits up to six seasons back; a new player centres on zero), the controls nearly unpenalised (10<sup>−3</sup>). λ is chosen from 60 to 16,000 by five-fold cross-validation over games. The normal equations are solved by Cholesky; the posterior covariance σ²(X'WX + Λ)<sup>−1</sup> gives standard errors for O, D and net. Three targets: xG (the headline), goals (with the defending goalie as an extra defence-only column, so skaters are not charged for goaltending) and shot attempts. Stints shorter than a second are dropped.</p>
<p>Read RAPM with its standard error: most skaters are within one or two standard errors of zero on one season's minutes.</p>${SRC('models/rapm.py')}</section>`,

`<section id="m-value"><h2>Rink value (GAR and WAR)</h2>
<p><strong>Skaters.</strong> (1) A <strong>box prior</strong>: a ridge regression (penalty 5), weighted by ice time and pooled over every season on disk, of 5v5 xG RAPM offence and defence on standardised individual rates: 5v5 individual xG, attempts, primary and secondary assists per 60, minor penalties drawn and taken per 60, net faceoff wins per 60, hits and blocks per 60 and a defenceman flag (players with 150+ 5v5 minutes, weights capped at 1,200). Its residual variance τ² (floored at 0.0025) is the prior's variance. (2) The season's 5v5 xG RAPM is refitted with each skater centred at the box prediction instead of zero, so a player sits on that profile until enough minutes move the estimate. (3) Components, in goals above average:</p>
<div class="eq">EV offence = O × 5v5 TOI / 60      EV defence = D × 5v5 TOI / 60
PP = share × (on-ice PP xGF/60 − league) × PP TOI / 60 / 5      PK = share × (league − on-ice PK xGA/60) × PK TOI / 60 / 4
     share = TOI / (TOI + 150 min)
shooting = GAx shrunk      penalties = (minors drawn − minors taken) × goals per minor</div>
<p>(4) <strong>Replacement</strong>: per position group, the time-weighted goals above average per 60 of players outside each team's top 13 forwards and 7 defencemen by ice time; GAR = GAA − replacement rate × TOI / 60. (5) <strong>Wins</strong>: WAR = GAR / goals per win, with goals per win = 4g / x, the derivative of the Pythagorean expectation at g goals per team-game (x fitted on every team-season on disk; 2.0 without enough). Faceoffs enter only through the box prior, because their value is already in the xG RAPM.</p>
<p><strong>Goalies.</strong> GAR = GSAx − replacement GSAx per attempt × attempts faced, replacement being goalies outside the top two per team by attempts faced; WAR as above.</p>${SRC('models/value.py')}</section>`,

`<section id="m-trade"><h2>Player value, strengths and needs, and the trade simulator</h2>
<p>The <a href="#/value">Value</a> page, each team page's "Strengths and needs" and the <a href="#/trade">Trade</a> page use Rink value (above) as their currency: GAR and WAR for the season, GAR per 60 as the rate, goalies ranked separately. Percentiles place WAR among the season's qualified players (the catalogues' floors: skaters 250 five-on-five minutes per 82 team games, prorated; goalies a quarter of the team's minutes); "best at each position" lists the top ten qualified players at C, LW, RW, D and G with the two largest parts of each skater's GAR. The trend column is the change in GAR per 60 from last season.</p>
<p><strong>Rest-of-season value.</strong> For the current season each rostered player gets rate = (GAR this season + 0.7 × GAR last season) / (minutes this season + 0.7 × minutes last season + K) × 60, last season at the RAPM prior's carry (0.7) and K of replacement-level play (300 minutes for skaters, 1,500 for goalies) so a call-up with a few games sits near replacement; the parts of GAR likewise. A skater's minutes a game are (this season's minutes + 10 × last season's minutes a game) / (games + 10); a goalie's are a share of the team's goalie minutes blended the same way. Next season adds an aging step: the change in GAR per 60 between consecutive seasons by age (the delta method on every pair of seasons on disk; skaters with 400+ minutes in both, goalies 1,000+; harmonic-mean minute weights), centred on the all-ages mean change, shrunk towards zero and smoothed over neighbouring ages.</p>
<p><strong>The depth chart.</strong> A game has a forward budget (the league's forward minutes per team game last season, about 181), a defence budget (about 117) and 60 goalie minutes; each player is capped (forwards 22, defence 26, goalies 60) and the projected minutes are handed out most first within each group, any shortfall at replacement level (GAR 0). Team value = Σ rate × minutes / 60, goals a game above replacement. In a trade the outgoing players' minutes open up at their position; each incoming player takes the projected minutes first from open minutes at that position, then from the new team's lowest-rated minutes there (replacement minutes count when lower), then at the neighbouring positions (centre and the two wings neighbour each other; defence and goal have none), never from a better player; a goalie who is better than a team's goalies takes their starts. Open minutes left over go to the best remaining players at the position, each at most 4 more minutes (defence 5; a backup goalie all 60) and up to the cap, then the neighbours, then replacement. The change in team value is the change in the club's net rating, in goals a game, for the rest of the season.</p>
<p><strong>Grades, strengths and needs.</strong> Each club's centres, left wings, right wings, defence and goalies, and its 5v5 offence, 5v5 defence, power play and penalty kill (the parts of GAR), are valued as projected GAR over a full season and placed against the league: A for the top 20 %, then B, C, D and F for the bottom 20 %. The three highest percentiles are the strengths and the three lowest the weaknesses, with value, rank and the player behind each. Trade targets for a weakness are the players on other clubs who would add the most there, each added to the depth chart with nobody going back (a unit's targets ranked by that part of GAR). Hints come from the data only: the seller's playoff odds (below 15 %: out of contention), what losing the player does to the seller (depth), whether the player is one of the seller's two most valuable, and age with the aging step. "Attainable" marks a seller out of contention or with depth, and not a franchise player. Free agents are not identified, and there are no salaries: no free, legitimate source is used, so the cap is not checked.</p>
<p><strong>Sensitivity curves.</strong> For every club the build re-runs the season simulation (1,000 runs a point with the same random numbers) with that club alone shifted by −0.75, −0.4, −0.15, 0, +0.15, +0.4 and +0.75 goals a game (net) for the rest of the season: the shift is added to the club's season-level strength draw, so it moves every remaining game's goal rates and its playoff series. Expected points and the playoff, division, conference, Cup and first-pick odds are made monotone outward from zero; the trade page reads each club's curve at its rating change (linearly between points, the end value beyond ±0.75) and adds the difference from the zero point to the full simulation's odds. Each curve holds the other clubs at their ratings, so the effect of the trading clubs meeting each other is left out. The curves are cached on the simulation's inputs.</p>${SRC('analytics/value.py')}${SRC('models/season_sim.py')}</section>`,

`<section id="m-valuation"><h2>Valuation (multi-season)</h2>
<p>The <a href="#/value?tab=val">Valuation</a> tab of the Value page projects every rostered player's on-field value in WAR over the rest of this season and the next three, each season discounted by 0.9 (a season ahead counts 90 %, two seasons 81 %, three 73 %):</p>
<p class="formula">V = Σ<sub>k=0..3</sub> 0.9<sup>k</sup> × S<sub>k</sub> × r<sub>k</sub> × m × a × n<sub>k</sub> / 60 / goals per win</p>
<p><strong>Rate</strong> r<sub>0</sub> is the rest-of-season GAR per 60 above (this season's and last season's GAR at 0.7, with 300 minutes of replacement-level play; goalies 1,500); r<sub>k</sub> = r<sub>k−1</sub> + the ageing curve's change at the player's age. <strong>Minutes</strong> m: projected minutes a game when playing (goalies: minutes per team game, the share of the goalie minutes). <strong>Availability</strong> a (skaters): (games this season + last + two seasons ago + 30 × the league's mean share of regulars, 0.786) / (the team games of the seasons the player appeared in + 30); this season's games are cut by an injury's expected games (ESPN status and return date; without a date day-to-day 1 game, out 3, injured reserve 7, long-term 25). <strong>Games</strong> n<sub>k</sub>: the team's games left, then 84 a season. <strong>Survival</strong> S<sub>k</sub>: the chance the player is still an NHL regular (games ≥ 25 % of team games; goalies 12 %) k seasons ahead, the product of yearly probabilities from a logistic regression on age, age², the shrunk GAR per 60 and minutes a game over every pair of completed seasons (skaters: 9,949 pairs, 83.5 % stay, log-loss 0.367 against 0.449 for the base rate; goalies 1,015, 83.1 %).</p>
<p><strong>Uncertainty</strong> (the p10–p90 band, 400 simulated careers with the same random numbers every run): the rate starts at N(r<sub>0</sub>, se²) with se² = 1 / (1/τ² + T/(60σ²)), T = this season's minutes + 0.7 × last season's; it then drifts by N(0, δ²) a season; log minutes take a random-walk step with sd 0.356 (goalies 0.442: the sd of the change in minutes per team game between consecutive seasons among regulars), this season's step scaled by the share of the season left; each season the player stays with the survival probability. σ², δ² and τ² come from consecutive seasons: E[(r₂ − r₁ − ageing)²] = σ²(60/T₁ + 60/T₂) + δ² (weighted least squares on 15 bins of pairs) and τ² = cov(r₁, r₂) for 400+ minutes in both. Skaters: σ² = 0.072 per 60 minutes, τ² = 0.019, δ² = 0.020 (a rate is half signal at 231 minutes); goalies: σ² = 2.37, τ² = 0.008, δ² = 0.135 (half signal at about 18,000 minutes: a goalie's GAR rate is mostly noise for years). The point value is the analytic expectation; the band comes from the draws.</p>
<p><strong>Position scarcity.</strong> Replacement level at C, LW, RW, D and G: the minute-weighted GAR per 60 of players at that position outside the league's top N by ice time, N = the position's share of the top 13 forwards, 7 defence and 2 goalies per team, pooled over the last three completed seasons. VORP replaces r<sub>k</sub> by r<sub>k</sub> − replacement. The scarcity index is (the top N's GAR per 60 − replacement) / the same gap for all skaters: with 2023–24 to 2025–26, left wings 1.28, centres 1.17, right wings 1.03, defence 0.76. Values are on-field only: contracts and the salary cap are not modelled (no free, legitimate salary source).</p>${SRC('analytics/valuation.py')}</section>`,

`<section id="m-moves"><h2>Transactions, trade grades and the pick-value curve</h2>
<p><strong>Source.</strong> ESPN's public NHL transactions feed (free text, one row per club per day; each side of a trade is its own row), the last twelve months, refreshed each hour (the first two pages); the NHL's api-web has no transactions endpoint. Draft picks: records.nhl.com (every pick with its player id); names no local list knows: the NHL's own player search. Not used: CapFriendly, PuckPedia and Spotrac (contracts and the cap; their terms), and any fantasy platform's data.</p>
<p><strong>Parsing.</strong> Each row is split into sentences (not at "St.", "N.Y.", "No." or initials) and typed: trade, signing, waiver claim, waivers, release, recall/assignment, injured reserve or other. A trade sentence is "Acquired A from club for B", "Traded A to club for B" or "Sent A to an NHL club in exchange for B" (an AHL club makes it an assignment). Assets: players (position prefixes such as C, LW, D, G, "Fs", "C/RW"), picks ("a 2028 first and second-round pick", "two 2026 third-round picks (No. 73 and 76)", "a third-round pick in the 2027 NHL Draft", typos such as "20227" and "thrid" corrected; a pick with no year is the next draft), conditional picks (valued at face, flagged), future considerations and cash (0), and "the rights to" a player. Names are matched on a normalised form (accents, punctuation and Jr. removed) to the players index, the season stores and the draft records, with the clubs involved breaking ties, then a close spelling at those clubs, then the NHL search; a name that still fails is listed as unmatched, never guessed.</p>
<p><strong>Deals.</strong> Trade sentences at most one day apart are one deal when the two clubs name each other or a player crosses between them; a group in which one club would appear on two different days is never merged, so deadline chains stay separate. Three-club trades become one deal with three sides. Both clubs' descriptions are merged (each pick counted once).</p>
<p><strong>Values</strong> (WAR, discounted 0.9 a season to the trade's season). <em>At the time</em>: the valuation above computed as of the trade date with no hindsight: GAR rates from the seasons completed before the date, aged a season; minutes and availability from games before the date; the games the new club had left; survival and ageing. Model parameters (ageing, survival, reliability, the pick curve) are the ones fitted on all completed seasons. A pick: the pick-value curve at its slot when the text gives one, else its round's average, × 0.9<sup>(draft year − the trade season's start year)</sup>. A prospect with no NHL games: the curve at the draft slot. <em>Realised since</em>: Σ over regular-season games for the new club after the trade date, of the player's GAR per 60 that season × minutes / 60 / goals per win. <em>Now</em>: realised + what our valuation still projects inside the original window (rest of the trade season and three more), while the player is still with that club. Each asset counts at max(0, value): a club can always replace a below-replacement player.</p>
<p><strong>Grades.</strong> A side's share of the value the deal moved, rescaled to two sides (share × sides / 2): A ≥ 0.65, B ≥ 0.55, C 0.45–0.55, D ≥ 0.35, F below; deals moving under 0.25 WAR in total are "minor". The winner has the largest share, unless the deal is even (C) or minor. The league table nets value received against value sent for every club over the twelve months.</p>
<p><strong>The pick-value curve.</strong> Every pick of the 2010 to 2019 drafts (2,126 picks): WAR over its first four NHL seasons within the first seven after the draft (the same four-season window as a player's value; prospects often arrive two or three years after the draft), season k after the draft weighted 0.9<sup>k</sup>, floored at zero a season and scaled to an 82-game season, picks who never played counting zero; averaged by overall pick, made non-increasing by pooling adjacent violators and fitted with v(p) = a (p + b)<sup>−c</sup> by weighted least squares: a = 5.13, b = 0.70, c = 0.649 (R² 0.62 on the 224 noisy slot means, 0.96 on 16-pick bins). The 1st pick is worth 3.6 WAR, the 16th 0.83, the 32nd 0.53, the 64th 0.34; round averages 1.07, 0.42, 0.30, 0.24, 0.20, 0.18 and 0.16 (observed 1.05, 0.49, 0.33, 0.21, 0.20, 0.11, 0.08; 87 % of first-round picks and 16 % of seventh-round picks produced any WAR). Until October 2026 all seven seasons counted, which valued picks on a longer window than players.</p>${SRC('analytics/moves.py')}${SRC('sources/moves.py')}</section>`,

`<section id="m-fantasy"><h2>Fantasy projections and the backtest</h2>
<p>The <a href="#/fantasy">Fantasy</a> page projects the standard categories (skaters G, A, +/-, PPP, SOG, HIT, BLK; goalies W, GA, SV, SO, with GAA and SV%) from our own data only; no fantasy platform's ownership, ADP, rankings or salaries are used. Default points are our own: G 2, A 1.5, +/- 0.5, PPP 0.5, SOG 0.3, HIT 0.2, BLK 0.4; W 4, GA −1, SV 0.2, SO 3; every weight can be changed on the page.</p>
<p><strong>Skaters</strong>, per game played. History: regular-season games of this season and the two before, each weighted 0.5<sup>n/HL</sup> (n = the player's games since). Ice time: even-strength and power-play minutes (HL 10 games, 2 pseudo-games at the position group's mean); PP unit: rank of the player's weighted PP minutes on the club (1–5 PP1, 6–10 PP2). Goals: (ixG at even strength per 60 × even-strength minutes + ixG on the power play per 60 × PP minutes) / 60 × finishing × the league's goals per ixG, the rates over HL 40 games regressed to the position mean with 300 (PP 60) pseudo-minutes, finishing = (career goals + 40 expected goals) / (career ixG + 40). Even-strength assists: on-ice 5v5 xGF per 60 (300 pseudo-minutes) × the league's 5v5 goals per xG × the player's share of team-mates' 5v5 goals while on the ice (15 pseudo-goals) × even-strength minutes; PP assists per PP minute (60). PPP = PP goals + PP assists. +/-: (on-ice 5v5 xGF − xGA per 60) × even-strength minutes. SOG, hits and blocks per 60 of all minutes (200 pseudo-minutes). Opponents: scoring × the opponent's goals-against factor (its goals and xG against per game, recency-weighted over this and last season, 10 pseudo-games, over the league's); shots × its shots-against factor.</p>
<p><strong>Goalies</strong>, per start: goals against = the club's xG against per game × the opponent's xG-for factor × (1 − save talent) × the league's goals per xG, save talent = Σ(xGA − GA) / (Σ xGA + 150) over the goalie's games (HL 80); shots against from the club and the opponent; wins = the game model's P(club wins) × 0.97; shutout = exp(−goals against). Start probability: the goalie's share of the club's starts (HL 10 club games); the second game of a back-to-back moves the No. 1's share by the fitted ratio (the No. 1's start rate there over the rate otherwise, about 0.55) and gives the rest to the others; an injured goalie gets none.</p>
<p><strong>Rankings.</strong> Rest-of-season points = games left after injuries × points a game (goalies: Σ P(start) × points a start). Tiers break where the drop to the next player is in the largest 10 % of drops in the top 240. Value over replacement: the best player left at each position after a greedy draft of twelve rosters of C 2, LW 2, RW 2, D 4, UTIL 1, G 2 and bench 4. Categories: the sum of z-scores over the top 240 skaters or 48 goalies. Adds: outside our season-start top 150 (the projection made before the first game) and inside it now; drops the reverse. Breakouts: 24 or younger in our top 300 with 2+ more minutes or 1+ more PP minute a game over the player's last five games than last season. Buy low / sell high (6+ games, top 300): projection − points a game so far ≥ 0.4 with goals 2+ below finishing-adjusted expected goals or an on-ice 5v5 PDO ≤ 0.950 (sell: the mirror); goalies (3+ games, 30 %+ of starts) with GSAx 4+ goals from talent × xG faced. Fantasy weeks run Monday to Sunday.</p>
<p><strong>Backtest.</strong> At every weekly checkpoint of the last five completed seasons the projection is made from games before that day only and compared with what followed over the next week and the rest of the season, beside two baselines: the season-to-date average a game (fewer than 3 games: last season's, with 10+ games; else the position mean) and last season's average (fewer than 10 games: season to date; else the position mean). MAE is per player-game (skaters, per game played; goalies, per club game), games-weighted; Spearman is the rank correlation across players with 2+ games (next week) or 10+ (rest of season), averaged over checkpoints. Default points:</p>
<div id="m-fy-bt">Loading the backtest…</div>${SRC('analytics/fantasy.py')}${SRC('analytics/gamelog.py')}</section>`,

`<section id="m-lines"><h2>Lines and pairs</h2>
<p>From the 5v5 stints, each side's skaters are split by position: a side with exactly three forwards and two defencemen contributes its trio and its pair. Per team and unit: time together, on-ice xGF and xGA (and attempts and goals), raw shares and a <strong>shrunk</strong> share:</p>
<div class="eq">xGF% shrunk = (xGF + m · p<sub>team</sub>) / (xGF + xGA + m)</div>
<p>with p<sub>team</sub> the team's 5v5 xGF% and m the pseudo-expected-goals of the xGF% stabilisation constant (k in seconds times the league's 5v5 xG rate per second, both sides): a unit stays near its team's share until its own sample of chances is comparable with m. Units with fewer than 20 minutes together are left out. On a player's page, linemates are ranked by 5v5 minutes shared in any unit.</p>${SRC('models/lines.py')}${SRC('analytics/teams.py')}${SRC('analytics/leaders.py')}</section>`,

`<section id="m-stabilisation"><h2>Stabilisation, percentiles and the catalogues</h2>
<p>Every metric is a ratio of sums over an entity's units (games, shots, faceoffs), with a sample in its own denominator: events, or time on ice in seconds for per-60 rates and on-ice shares. For each sample size n on a grid (25 to 3,000 events; 20 to 800 minutes) every entity with at least 2n of denominator keeps its first 2n in game order, deals the units alternately into two halves, and the half values are correlated across entities (at least 20). Under the Spearman–Brown model:</p>
<div class="eq">r(n) = n / (n + k)      n₀.₇ = 0.7k / 0.3 = 7k/3 ("stabilises at")      shrunk = (n·x + k·m) / (n + k)</div>
<p>k is fitted by weighted least squares per season and pooled across seasons as an entity-weighted geometric mean. Defaults before a fit include finishing 1,500 attempts, shooting % 375 shots, save % 2,000 attempts faced, GSAx per attempt 1,200, faceoff % 140, points per 60 400 minutes, xGF% 500 minutes at 5v5 and GF% 1,500. The glossary lists every metric's point and unit.</p>
<p><strong>Percentiles</strong> place a player's shrunk value (m is the qualified pool's mean) against the qualified pool, rank = (below + ½ ties)/n, reversed where less is better, so 100 is always best; displayed values are never shrunk. <strong>Qualified</strong>: skaters with 250 minutes at 5v5 per 82 team games (prorated); goalies with a quarter of the team's minutes. A metric needs its own sample floor before a player gets a percentile on it (50 minutes at 5v5, 100 minutes overall, 20 shots or unblocked attempts, 50 faceoffs, 20 minutes on the power play or penalty kill, 5 games; goalies 100 attempts faced). Metrics with no denominator (goals, points and other counts, GSAx, RAPM, Rink value) need 5 games played (goalies 3) and are ranked among the players past that floor, so in the first week of a season the pages show values with no percentiles rather than one game's goals ranked against everyone's. The position percentile compares forwards with forwards and defencemen with defencemen once five share the pool.</p>
<p><strong>Careers</strong> reduce each season's catalogues to compact rows; era-adjusted columns (marked +) are 100 + 10z within that season's qualified pool at the position group. <strong>Similar players</strong> are the nearest qualified players in the same group by Euclidean distance on standardised profile metrics (lower is closer). <strong>Projections</strong> regress per-game rates towards the position group's mean with 30 games of prior for points and 45 for goals, and 5v5 xGF% towards 50% by its stabilisation constant. <strong>Game score</strong>: 0.75 G + 0.7 A1 + 0.55 A2 + 0.075 SOG + 0.05 blocks + 0.15 penalties drawn − 0.15 taken + 0.01 FOW − 0.01 FOL + 0.05 CF − 0.05 CA + 0.15 GF − 0.15 GA (on-ice terms at 5v5).</p>${SRC('models/stabilise.py')}${SRC('analytics/__init__.py')}${SRC('analytics/skaters.py')}${SRC('analytics/goalies.py')}${SRC('analytics/careers.py')}${SRC('analytics/games.py')}</section>`,

`<section id="m-strength"><h2>Team strength</h2>
<p>One weighted ridge per unit, on rows of team-games, weights = minutes × 0.5<sup>age / H</sup> (age in days before the fit date, half-life H = 110 days):</p>
<div class="eq">5v5 xG       xGF60<sub>g,t</sub>  = μ<sub>ev</sub> + O<sub>t</sub> + D<sub>o</sub> + e       (O: created above the league; D: allowed above the league, + = worse)
5v5 shots    FF60<sub>g,t</sub>   = μ<sub>ff</sub> + SO<sub>t</sub> + SD<sub>o</sub> + e
power play   PPxG60<sub>g,t</sub> = μ<sub>pp</sub> + PP<sub>t</sub> + PK<sub>o</sub> + e
penalties    PPmin<sub>g,t</sub>  = μ<sub>pen</sub> + DR<sub>t</sub> + TK<sub>o</sub> + e
goals        GF<sub>g,t</sub>     = μ<sub>g</sub> + A<sub>t</sub> + G<sub>o</sub> + e
minimise Σ w<sub>i</sub>(y<sub>i</sub> − x<sub>i</sub>b)² + Σ λ<sub>j</sub>(b<sub>j</sub> − m<sub>j</sub>)²</div>
<p>Penalties λ (in the row weight's unit): 5v5 xG 1,500 minutes, shots 900, power play 260, penalties 30 games, goals 45 games. The 5v5 rates are already score- and venue-adjusted. <strong>Finishing</strong> and <strong>goaltending</strong> are decayed sums shrunk towards the prior (k 160 and 110 expected goals): a goalie's value is goals allowed per expected goal above the league (negative is better), and the <strong>starter is an input</strong>, by default the team's most frequent starter in its last ten games; new goalies start at +0.03. Priors for a season are carry × last season's end value (5v5 0.6, shots 0.65, power play 0.45, penalty kill 0.4, penalties 0.5, goals 0.5, finishing 0.35, goalies 0.7 per idle season), mapped across relocations. Expected goals for a game:</p>
<div class="eq">PPmin<sub>h</sub> = clip(μ<sub>pen</sub> + DR<sub>h</sub> + TK<sub>a</sub>, 1, 12),   EVmin = 60 − PPmin<sub>h</sub> − PPmin<sub>a</sub>
xG<sub>h</sub> = EVmin/60 · (μ<sub>ev</sub> + O<sub>h</sub> + D<sub>a</sub>) + PPmin<sub>h</sub>/60 · (μ<sub>pp</sub> + PP<sub>h</sub> + PK<sub>a</sub>) + PPmin<sub>a</sub>/60 · μ<sub>sh</sub>
G<sub>h</sub> = conv · xG<sub>h</sub> · (1 + fin<sub>h</sub>) · (1 + val<sub>starter a</sub>)</div>
<p>The net rating is goals per game against a league-average team and goalie. League means before fitting: 2.45 5v5 xG per 60, 6.6 power-play xG per 60, 4.6 power-play minutes, 2.95 goals per game. On the team pages, until the model answers, units come from the season's own per-60 counts.</p>${SRC('models/team_strength.py')}${SRC('models/_cdata.py')}${SRC('analytics/teams.py')}</section>`,

`<section id="m-game"><h2>The game model</h2>
<p>Expected goals become a score distribution (bivariate Poisson with a late-game empty-net chain), then overtime and the shootout:</p>
<div class="eq">log μ<sub>h</sub> = b<sub>0</sub> + b<sub>xg</sub> log G<sup>xg</sup><sub>h</sub> + b<sub>p</sub> log G<sup>p</sup><sub>h</sub> + b<sub>g</sub> log G<sup>g</sup><sub>h</sub> + home · [not neutral] + ½ s · f
log μ<sub>a</sub> = b<sub>0</sub> + b<sub>xg</sub> log G<sup>xg</sup><sub>a</sub> + b<sub>p</sub> log G<sup>p</sup><sub>a</sub> + b<sub>g</sub> log G<sup>g</sup><sub>a</sub>                    − ½ s · f</div>
<p>G<sup>xg</sup> is team strength's expected goals (with the <strong>opposing starter's</strong> goaltending), G<sup>p</sup> the same with its 5-on-5 term built from the <strong>players</strong> instead of the team (since October 2026): each team's skaters in its latest game, each rated by a walk-forward RAPM on 5-on-5 xG (the season's games so far, centred on 0.7 × the skater's previous-season estimate, ridge 1,000) and weighted by 5 × the skater's share of the lineup's expected 5-on-5 ice time (the average over the last ten games), so the 5-on-5 xG rate is the league's + the lineup's offence − the opponents' defence; G<sup>g</sup> the goals-only ratings, f the schedule features home minus away (back-to-back, rest days capped at 3, travel in 1,000 km, time-zone change). Minutes 0–57: X = U + W, Y = V + W with U ~ P(μ'<sub>h</sub> − λ<sub>3</sub>), V ~ P(μ'<sub>a</sub> − λ<sub>3</sub>), W ~ P(λ<sub>3</sub>), μ' = μ · 57/60 and λ<sub>3</sub> = θ · min(μ'<sub>h</sub>, μ'<sub>a</sub>). Minutes 57–60: a Markov chain on the score in 10-second steps: tied, both rates × 0.85 (teams play for the point); trailing by one with two minutes left or by two with three left, the goalie is pulled (its rate × 2.2, the leader adds 0.22 empty-net goals a minute). Overtime: five minutes, P(goal) = 1 − exp(−5 k<sub>ot</sub> (μ<sub>h</sub> + μ<sub>a</sub>)/60) with k<sub>ot</sub> 1.85 at 3-on-3 and 1.2 at 4-on-4, the scorer home with probability μ<sub>h</sub>/(μ<sub>h</sub> + μ<sub>a</sub>); otherwise a shootout won by the home side half the time. Playoffs: sudden-death 5-on-5. The shootout winner is credited one goal, so an overtime game never covers −1.5.</p>
<p>Defaults before the walk-forward fit: b<sub>xg</sub> 1, b<sub>g</sub> 0, home 0.045 (log scale), back-to-back −0.06, rest +0.01 a day, travel −0.01 per 1,000 km, time zones −0.01, θ 0.08. Outputs: P(home win), regulation win and loss, P(overtime), P(shootout), the puck line (P(final margin ≥ 2)), the totals distribution and expected goals. Market numbers are de-vigged multiplicatively.</p>${SRC('models/game.py')}</section>`,

`<section id="m-live"><h2>Live win probability</h2>
<p>The rest of regulation is a Markov chain on the goal difference (home minus away, −10 to 10) in 10-second steps, with the game model's pre-game regulation means as the base rates, so pre-game strength fades exactly as the clock runs down. Rates are μ/60 per minute times a strength multiplier: on a 5v4 or 4v3 power play the attacking side × 2.4 and the short-handed side × 0.3 for the penalty time left; on a 5v3 × 4.0 and × 0.2; at 4v4 or 3v3 both × 1.15. The late-game rules are the game model's (tied: both × 0.85; trailing by one with two minutes left or by two with three, the goalie is pulled), and an empty net reported now is honoured for the next minute whatever the clock. A tie at the end of regulation goes to the game model's overtime and shootout (playoffs: sudden death). When only a pre-game win probability is known, the means are solved for at a six-goal total.</p>${SRC('models/live.py')}${SRC('analytics/games.py')}</section>`,

`<section id="m-season"><h2>Season and playoff simulation</h2>
<p>20,000 simulations of the rest of the regular season, vectorised in chunks of 1,000. Each simulated game uses the game model's regulation means with each team's usual starter, home ice, rest, back-to-backs, travel and time zones, perturbed by the teams' strength errors:</p>
<div class="eq">μ<sub>h,s</sub> = μ<sub>h,g</sub> · exp(+(x<sub>s,h</sub> − x<sub>s,a</sub>) / (2Ḡ))      μ<sub>a,s</sub> = μ<sub>a,g</sub> · exp(−(x<sub>s,h</sub> − x<sub>s,a</sub>) / (2Ḡ))
x<sub>s,t</sub> = z<sub>s,t</sub> + Σ<sub>k ≤ week</sub> u<sub>s,t,k</sub>,   z ~ N(0, se<sub>t</sub>²),   u ~ N(0, 0.035²)</div>
<p>with Ḡ the league's goals per team-game, se<sub>t</sub> the team-strength standard error and u a weekly random walk, so uncertainty grows with the horizon. Scores come from the same bivariate-Poisson and empty-net process, then 3-on-3 overtime and the shootout, so wins, regulation wins, regulation-plus-overtime wins, points, goals and head-to-head points are exact in every simulation.</p>
<p><strong>Tiebreakers</strong> (NHL.com, "Tie-Breaking Procedure", read 1 October 2026), from 2019–20: fewer games played (higher points percentage), more regulation wins, more regulation and overtime wins, more wins in any manner, more points in games among the tied clubs (the odd game excluded), greater goal differential, more goals scored; then, in simulations only, a random draw. Steps run in order on each group still tied and a still-tied subgroup carries on from the next step. 2010–11 to 2018–19: games played, ROW, head-to-head, goal differential; before: wins first.</p>
<p><strong>Playoffs</strong>: from 2013–14 the top three of each division and two wild cards per conference; the division winner with the better record meets the second wild card; home ice in every series goes to the better regular-season record. Series are best of seven (2-2-1-1-1), the home side of each game winning with probability logistic(logit P<sub>0</sub> + k<sub>po</sub>(x<sub>h</sub> − x<sub>a</sub>)). Earlier formats (seeded 1–8 to 2012–13; the 2020–21 divisional bracket) are simulated as they were.</p>
<p><strong>Draft lottery</strong> (the current format, verified 1 October 2026): the 16 non-playoff clubs in reverse order, first-draw odds 18.5, 13.5, 11.5, 9.5, 8.5, 7.5, 6.5, 6.0, 5.0, 3.5, 3.0, 2.5, 2.0, 1.5, 0.5, 0.5%; two draws; a club may move up at most ten places. <strong>Magic numbers</strong> are in points with tiebreaks assumed lost: magic = the k-th largest (P<sub>j</sub> + 2R<sub>j</sub> − P<sub>i</sub> + 1) over rivals; clinched at zero. <strong>Next-game odds</strong> are interventional: each simulation is reweighted by 1/P(result) so "if they win" isolates the game's own effect.</p>${SRC('models/season_sim.py')}${SRC('canon.py')}${SRC('analytics/season.py')}</section>`,

`<section id="m-awards"><h2>Award races</h2>
<p>The Hart, Vezina, Norris, Calder and Selke use a <strong>conditional logit</strong> per award, P(i wins) = exp(x<sub>i</sub>b) / Σ<sub>j</sub> exp(x<sub>j</sub>b), with features z-scored within each season's candidates and b by ridge-penalised maximum likelihood (ridge 0.1) on the verified winners of 2009–10 to 2025–26. Candidates and features: Hart, the top 30 skaters by points and top 5 goalies by GSAx (points, goals, team points percentage, Rink value, a goalie's GSAx); Vezina, goalies with 40% of their team's games, top 20 by GSAx (GSAx, share of games, team points percentage, save %); Norris, the top 25 defencemen by points (points, value, ice time, plus-minus); Calder, the top 25 rookie skaters and top 5 rookie goalies (no earlier season of more than 25 games, aged 26 or under on 15 September); Selke, the top 50 forwards by points with 40% of games (defensive value, plus-minus, points, centre). In season, counting features are projected to the end of the season and the utilities are multiplied by 0.5 + 0.5 × the share of the season played, flattening early odds.</p>
<p>The Art Ross and Rocket Richard are simulated: the top 40 by projected total, each player's remaining points (goals) Poisson with rate × games left × 0.93 availability, the rate shrunk towards last season's with 20 games' weight; 20,000 draws; Ross ties go to more goals, Richard ties are shared. Until the model answers, the awards page ranks each trophy's usual criteria and says so.</p>${SRC('models/awards.py')}${SRC('analytics/leaders.py')}</section>`,

`<section id="m-markets"><h2>Markets and de-vig</h2>
<p>A prediction-market number is the midpoint of a live two-sided quote, (bid + ask)/2, used only when 0 &lt; bid ≤ ask &lt; 1 and the spread is at most 0.12; a last trade is never used. A field market (Cup, conference, division, Presidents' Trophy) is published only when at least max(4, half the field) runners are accounted for and the implied total lies within 0.8–1.3, then de-vigged multiplicatively, p<sub>i</sub> = (1/o<sub>i</sub>) / Σ(1/o<sub>j</sub>); award fields are de-vigged per source (implied total 0.8–1.3, or up to 1.6 with 20 or more quoted runners) and averaged across sources. Two-way game markets are de-vigged across their two sides; Kalshi spread, total and overtime ladders are shown as quoted mids. Bookmaker moneylines: q = 100/(ml + 100) for positive lines and −ml/(−ml + 100) for negative, p<sub>home</sub> = q<sub>home</sub>/(q<sub>home</sub> + q<sub>away</sub>). Where ours and the market differ, that is disagreement, not a recommendation. Nothing here is advice; 18+.</p>${SRC('sources/markets.py')}${SRC('models/game.py')}</section>`,

`<section id="m-backtest"><h2>Backtest and calibration</h2>
<p>Every regular-season and playoff game with a result from 2009–10 is forecast walk-forward (2009–10, with no earlier season to fit on, is a warm-up forecast with the code defaults): team strength is refitted every seven days from that season's earlier games (the preseason prior chained from the season before), and the game model's coefficients for season S are fitted on earlier seasons only. Predictors of P(home wins, any manner): the game model; an <strong>xG baseline</strong>, logistic(a + b(xev<sub>h</sub> − xev<sub>a</sub>)) on 5v5 xG ratings, refitted each season on earlier ones; <strong>Elo</strong> in the FiveThirtyEight style (K = 6, home ice 50 points, margin multiplier 0.6686 ln(margin) + 0.8048 times 2.05/(0.001 ΔElo<sub>winner</sub> + 2.05), playoff differences × 1.25, a third of the way back to 1505 between seasons, shootouts counted as a one-goal margin); and the <strong>closing moneyline</strong> (ESPN, 2019–20 on: the closing block where ESPN has one, 2022–23 on, else the last line it lists after the game), de-vigged. The first season, with no earlier seasons to fit on, is a warm-up forecast with the code's defaults and flagged as such. Scores: log-loss and Brier (probabilities clipped at 10<sup>−4</sup>) and ten-bin reliability; every predictor is also scored on just the games with a closing line. Regulation, the puck line (margin of two or more) and totals (pushes dropped) are calibrated the same way.</p>
<p>Against the markets (research of October 2026, test seasons 2023–24 to 2025–26): the game model trails the closing moneyline by about 0.006 in log-loss a game, the opening line by about 0.003 and Kalshi's 08:00 number by about 0.005, and the market's own over/under number is better than the model's probability on totals (the model's totals probabilities are also too spread out). Ratings implied by past closing lines, the skaters who dressed and stacked recalibrations all helped on 2020–21 to 2022–23 and not on the three test seasons, so the site's game model is unchanged; the details are in the repository's <code>docs/research/nhl_edge.md</code>.</p>
<p>Season odds: checkpoints at each season's first game and after 60 and 120 days of the completed seasons 2013–14 to 2025–26 (not 2019–20 or 2020–21), 1,000 simulations each with ratings and coefficients fitted strictly before, scored for the playoffs, the division, the Presidents' Trophy, the conference and the Cup. Our expected goals are scored against MoneyPuck's on the same shots. The <a href="#/calibration">calibration page</a> writes its reading from those numbers and calls a difference smaller than the noise a tie.</p>${SRC('models/backtest.py')}${SRC('models/xg.py')}</section>`,

`<section id="m-site"><h2>How the pages compute what they show</h2>
<ul><li><strong>Percentiles</strong> place a player's shrunk value against the qualified pool of the player's position group (or the league), 100 = best; players below the floor show values without percentiles.</li>
<li><strong>Shot heatmaps</strong> bin unblocked attempts on a 5 ft grid of the offensive zone (x 25–95 ft, the full width), lightly smoothed. A skater's map against the league is the skater's share of attempts from each area minus the league's share at 5 on 5 (where the skater shoots from, not how much); a team's is its rate per 60 from each area minus the league's.</li>
<li><strong>The RAPM quadrant</strong> plots every qualified skater's offence against defence with the selected player's ±1 standard error when it is published.</li>
<li><strong>Compare</strong> counts a metric as won by the higher percentile and lists the three largest gaps each way; two skaters from the same pool use position-pool percentiles, a forward with a defenceman league percentiles. With one side picked, the other defaults to the nearest player on the headline percentiles.</li>
<li><strong>The lab</strong> ranks by the sum of standard scores on both axes in the better direction, and can shrink rates towards the median of the players on screen by each metric's stabilisation constant; totals, RAPM, values and NHL EDGE tracking figures are never shrunk there.</li>
<li><strong>Team schedules</strong> plot points minus the model's expected points, 2·P(win) + P(overtime)/2.</li></ul>${SRC('analytics/careers.py')}${SRC('analytics/leaders.py')}</section>`,

`<section id="m-limitations"><h2>Limitations</h2>
<ul><li><strong>NHL EDGE is aggregates only.</strong> The NHL publishes season summaries (top speed, bursts, distance, shot speed, zone time) with its own percentiles, not per-play tracking, so tracking never enters the play-level models; it starts in 2021–22.</li>
<li><strong>Shot locations before 2023–24 carry rink biases</strong> (recorded by each arena's scorers, and still measurably biased in the first tracking seasons); they are arena-adjusted by quantile matching, which removes systematic distance bias but not individual errors.</li>
<li><strong>Shift data starts in 2010–11.</strong> Time on ice, on-ice rates, RAPM, lines, deployment and Rink value are not available for 2009–10, whose play-by-play has coordinates but no shift charts; career rows before 2009–10 are the league's season totals.</li>
<li><strong>The closing line is sharper than the model</strong>, as it should be: it knows confirmed starting goalies, injuries and money that the model reads late or not at all. Starting goalies are an input to the game model and are often confirmed only on the morning of a game.</li>
<li><strong>Hockey is close to a coin flip.</strong> Even strong teams win about 60% of games and a season's standings carry a lot of luck; forecasters differ in the third decimal of log-loss.</li>
<li><strong>Goaltending and finishing are noisy.</strong> Save percentage and goals above expected take thousands of shots to stabilise; one season of GSAx or GAx is mostly noise and is shrunk before ranking.</li>
<li><strong>RAPM</strong> separates teammates only as far as coaches mix them: players who always share the ice (a top pair, a set line) are hard to tell apart, and the standard errors say so.</li>
<li><strong>Scorer-recorded events</strong> (hits, giveaways, takeaways, blocked shots) vary between arenas and are not adjusted.</li>
<li><strong>Coverage by source</strong>: ESPN lines by book from 2019–20, opening and closing lines from 2022–23; MoneyPuck shots from 2007–08.</li>
<li><strong>Simulations</strong> hold team strength to a random walk and use each team's usual starter; they do not model injuries, trades or call-ups beyond what the ratings already show.</li></ul></section>`,

`<section id="m-terms"><h2>Data terms and credits</h2>
<p>${esc(NHL_NOTE)} Names, statistics and tri-codes are used to identify clubs and players only.</p>
<p>${esc(MP())}: used only as a benchmark for our expected-goals model, with credit, non-commercially, from the files MoneyPuck publishes for download.</p>
<p>Betting lines are ESPN's public odds feeds (DraftKings and other books as ESPN lists them); prediction-market numbers are Kalshi's and Polymarket's public APIs. No odds on this site are offers; model probabilities carry no margin and cannot be wagered here. 18+ where gambling is discussed; see the <a href="#/disclaimer">disclaimer</a>.</p>
<p>Transactions and injury status are ESPN's public site data; draft records are the NHL's records site; prospect names are looked up with the NHL's public player search. Left out because their terms do not allow our use: CapFriendly, PuckPedia and Spotrac (contracts and the cap) and fantasy platforms' ownership, ADP, rankings and salaries.</p></section>`

].join('\n');

function renderMethodology(el, params) {
  const want = (params.rest || [])[0] || params.id || '';
  const tmp = document.createElement('div');
  tmp.innerHTML = METHOD_HTML;
  const secs = Array.prototype.slice.call(tmp.querySelectorAll('section[id]')).map(s => {
    const h2 = s.querySelector('h2');
    const title = h2 ? h2.textContent : s.id;
    if (h2) h2.parentNode.removeChild(h2);
    return { id: s.id.replace(/^m-/, ''), title: title, html: s.innerHTML };
  });
  const toc = '<div class="doc-toc"><div class="doc-toc-head">Methodology</div><ol>' + secs.map(s => '<li><a href="#/methodology/' + esc(s.id) + '" data-target="method-' + esc(s.id) + '">' + esc(s.title) + '</a></li>').join('') +
    '</ol><div class="doc-toc-head" style="margin-top:10px">See also</div><ol class="plain"><li><a href="#/glossary">Glossary</a></li><li><a href="#/calibration">Calibration</a></li><li><a href="#/scout?view=chart">Scouting Room charts</a></li><li><a href="#/disclaimer">Disclaimer and terms</a></li></ol></div>';
  const intro = '<div class="card"><div class="card-header">Methodology <span class="card-sub">Where the data comes from, how every model works, and where it is wrong. Every constant is the one in the code on 1 October 2026, and each section names its file under <code>oddsmarkets/nhl/</code>.</span></div>' +
    '<div class="doc-meta">' + secs.length + ' sections · fitted values (the xG model, ridge penalties, stabilisation constants, the game model\'s coefficients) are refitted with the models and shown on the pages and the <a href="#/calibration">calibration page</a></div></div>';
  el.innerHTML = '<div class="doc gq-doc">' + toc + '<div class="doc-body">' + intro + secs.map((s, i) => '<div class="card" id="method-' + esc(s.id) + '"><div class="card-header">' + (i + 1) + '. ' + esc(s.title) +
    ' <a class="doc-anchor" href="#/methodology/' + esc(s.id) + '" title="Link to this section">#</a></div><div class="pad">' + s.html + '</div></div>').join('') + '</div></div>';
  el.querySelectorAll('.doc-toc a[data-target]').forEach(a => a.addEventListener('click', ev => {
    ev.preventDefault();
    const t = document.getElementById(a.dataset.target);
    if (t) t.scrollIntoView({ block: 'start' });
    try { history.replaceState(null, '', a.getAttribute('href')); } catch (e) { /* ok */ }
  }));
  if (want) { const t = document.getElementById('method-' + String(want).replace(/^m-/, '')); if (t) setTimeout(() => t.scrollIntoView({ block: 'start' }), 0); }
  fillFitted(el);
  fillBacktest(el);
}

/* The fantasy backtest's headline numbers (data/fantasy_backtest.json) inside the methodology. */
function fillBacktest(root) {
  const host = root.querySelector('#m-fy-bt');
  if (!host || typeof RK.load !== 'function') return;
  Promise.resolve(RK.load('fantasy_backtest.json')).then(bt => {
    if (!bt || !bt.rows) { host.textContent = 'The backtest has not been computed yet.'; return; }
    const R = {};
    bt.rows.forEach(r => { R[r.slice(0, 4).join('|')] = r; });
    const f = (v, d) => (typeof v === 'number' ? v.toFixed(d) : '—');
    const line = (kind, hz, lab) => '<tr><td>' + lab + '</td>' + ['model', 'std', 'last'].map(w => '<td style="text-align:right">' + f((R[kind + '|' + hz + '|pts|' + w] || [])[4], 3) + '</td>').join('') +
      ['model', 'std', 'last'].map(w => '<td style="text-align:right">' + f((R[kind + '|' + hz + '|pts|' + w] || [])[5], 3) + '</td>').join('') + '</tr>';
    host.innerHTML = '<div class="table-wrap compact"><table class="wc-table"><thead><tr><th>Points</th><th>MAE ours</th><th>to date</th><th>last season</th><th>ρ ours</th><th>to date</th><th>last season</th></tr></thead><tbody>' +
      line('S', 'week', 'Skaters, next week') + line('S', 'ros', 'Skaters, rest of season') + line('G', 'week', 'Goalies, next week') + line('G', 'ros', 'Goalies, rest of season') +
      '</tbody></table></div><p class="muted-inline">' + esc((bt.seasons || []).join(', ')) + '; ' + (bt.checkpoints || 0) + ' checkpoints. Per-category numbers are on the <a href="#/fantasy">Fantasy</a> page.</p>';
  }).catch(() => { host.textContent = 'The backtest could not be loaded.'; });
}

if (typeof RK.route === 'function') {
  [['glossary', renderGlossary], ['methodology', renderMethodology]].forEach(r => { try { RK.route(r[0], r[1]); } catch (e) { /* bound */ } });
}
})(window.RK || (window.RK = {}));
