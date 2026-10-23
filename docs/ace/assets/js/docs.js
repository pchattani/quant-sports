/* The Quant Ace — docs: the glossary (#/glossary, #/glossary/<key>, #/glossary/g:<group>) and the
 * methodology (#/methodology, #/methodology/<section>).
 *
 * The glossary reads data/glossary.json ({groups: [{name, entries: [{key, label, desc, fmt, lower,
 * scope, kind}]}], model: [{key, label, group, desc}]}); until that is published it is assembled
 * from both tours' player catalogues. The methodology is static text: every constant in it was read
 * from the Python under oddsmarkets/tennis/, its committed fits for both tours (models/fitted/*.json)
 * and the committed backtests (data/{atp,wta}/calibration.json), and each paragraph names its source
 * file. Uses TA.fk from players.js where present. */
(function (TA) {
'use strict';

const esc = s => (typeof TA.esc === 'function' ? TA.esc(s) : String(s === null || s === undefined ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'));
const muted = t => '<div class="muted">' + t + '</div>';
const fold = s => String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');

// ── glossary ───────────────────────────────────────────────────────────────

function slug(s) { return String(s || 'group').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''); }

function loadGlossary() {
  return TA.load('glossary.json').then(g => {
    if (g && g.ok !== false && (g.groups || []).length) return Object.assign({ source: 'payload' }, g);
    return Promise.all([TA.load('atp/players.json'), TA.load('wta/players.json')]).then(res => {
      const groups = [], seen = {};
      res.forEach((cat, i) => ((cat || {}).metrics || []).forEach(m => {
        if (seen[m.key]) return;
        seen[m.key] = 1;
        let grp = groups.find(x => x.name === (m.group || 'Other'));
        if (!grp) { grp = { name: m.group || 'Other', entries: [] }; groups.push(grp); }
        grp.entries.push(Object.assign({ kind: i ? 'WTA' : 'player' }, m));
      }));
      return { groups: groups, model: [], source: 'catalogue' };
    });
  });
}

function fmtHint(e) {
  const tags = [];
  const f = e.fmt;
  if (f === 'pct') tags.push(['rate', '']);
  else if (f === 'prob') tags.push(['probability', '']);
  else if (f === 'int') tags.push(['count', '']);
  else if (f === 'signed') tags.push(['over expected', '']);
  if (e.lower) tags.push(['lower is better', 'lower']);
  if (e.scope === 'wta_stats') tags.push(['WTA match stats', 'real']);
  else if (e.scope === 'charted') tags.push(['charted matches', 'charted']);
  else if (/inferred/i.test(e.group || '')) tags.push(['inferred from scores', 'inferred']);
  return tags.map(t => '<span class="gl-tag' + (t[1] ? ' ' + t[1] : '') + '">' + esc(t[0]) + '</span>').join('');
}

/* The glossary text comes from the builders (data/glossary.json); it is shown in the site's v2 copy (STYLE_GUIDE §8):
   our forecasts, never prices or edges. A display rewrite only; the builder wording is listed in REMAINING.md. */
const COPY = [[/match price's blend/g, 'match forecast’s blend'], [/a surface specialist's edge/g, 'a surface specialist’s advantage'],
  [/de-vigged closing prices/g, 'de-vigged closing lines'], [/de-vigged closing price/g, 'de-vigged closing line'], [/closing prices/g, 'closing lines'],
  [/A disagreement, not a value bet: the market is the better forecaster\./g, 'A disagreement, not a recommendation: the market is the sharper forecaster.'],
  [/\(used for pricing\)/g, '(used for the forecasts)'], [/each remaining match priced by the model/g, 'each remaining match forecast by the model'],
  [/\bpriced\b/g, 'forecast'], [/\bpricing\b/g, 'forecasting'], [/\bprices\b/g, 'forecasts'], [/\bprice\b/g, 'forecast'], [/\bedges?\b/g, 'advantage'], [/value bets?/g, 'recommendation']];
function copy(t) { let x = String(t || ''); COPY.forEach(r => { x = x.replace(r[0], r[1]); }); return x; }
function entryHTML(e, isModel) {
  const q = [e.label, e.key, e.desc, e.group, e.scope, isModel ? 'model' : ''].join(' ');
  return '<div class="gl-entry" id="gl-' + esc(e.key) + '" data-q="' + esc(fold(q)) + '" data-scope="' + esc(isModel ? 'model' : (e.scope || 'all')) + '">' +
    '<dt><span>' + esc(e.label || e.key) + ' <a class="doc-anchor" href="#/glossary/' + encodeURIComponent(e.key) + '" title="Link to this entry">#</a></span>' +
    '<span class="gl-tags"><span class="gl-key">' + esc(e.key) + '</span>' + (isModel ? '<span class="gl-tag model">model</span>' : fmtHint(e)) + '</span></dt>' +
    '<dd>' + (e.desc ? esc(copy(e.desc)) : '<span class="muted-inline">No definition yet.</span>') + '</dd></div>';
}

function renderGlossary(el, params) {
  const key = params.id || (params.rest || [])[0] || (params.query || {}).k || '';
  el.innerHTML = '<div id="glossary-root">' + muted('Loading the glossary…') + '</div>';
  return loadGlossary().then(g => {
    const root = document.getElementById('glossary-root');
    if (!root || !el.isConnected) return;
    const groups = g.groups || [];
    const modelGroups = [];
    (g.model || []).forEach(t => {
      const name = t.group || 'Model';
      let grp = modelGroups.find(x => x.name === name);
      if (!grp) { grp = { name: name, entries: [] }; modelGroups.push(grp); }
      grp.entries.push(t);
    });
    const nMetrics = groups.reduce((s, x) => s + (x.entries || []).length, 0);
    const nModel = modelGroups.reduce((s, x) => s + x.entries.length, 0);
    if (!nMetrics && !nModel) { root.innerHTML = '<div class="card"><div class="card-header">Glossary</div>' + muted('The glossary is not available yet.') + '</div>'; return; }
    const index = groups.map(x => '<a href="#/glossary/g:' + esc(slug(x.name)) + '" data-group="' + esc(slug(x.name)) + '">' + esc(x.name) + '</a>').join('') +
      modelGroups.map(x => '<a href="#/glossary/g:model-' + esc(slug(x.name)) + '" data-group="model-' + esc(slug(x.name)) + '">' + esc(x.name) + '</a>').join('');
    const cardOf = (name, sl, entries, isModel) => '<div class="card gl-group" data-group="' + esc(sl) + '"><div class="card-header">' + esc(name) + ' <span class="card-sub">' + entries.length + '</span></div><dl class="gl-list">' + entries.map(e => entryHTML(e, isModel)).join('') + '</dl></div>';
    root.innerHTML =
      '<div class="card"><div class="card-header">Glossary <span class="card-sub">Every metric the site computes for ATP and WTA players, and every model term it uses. How they are computed is in the <a href="#/methodology">methodology</a>.</span></div>' +
      '<div class="gl-top"><input id="gl-search" type="search" placeholder="Filter the glossary…" autocomplete="off" spellcheck="false">' +
      '<select id="gl-kind" class="af-gl-kind"><option value="">all sources</option><option value="all">scores and results (both tours)</option><option value="wta_stats">WTA match stats</option><option value="charted">charted matches</option>' + (nModel ? '<option value="model">model terms</option>' : '') + '</select>' +
      '<span class="gl-count" id="gl-count"></span></div>' +
      '<div class="gl-index">' + index + '</div>' +
      '<div class="doc-meta">' + nMetrics + ' metrics in ' + groups.length + ' groups' + (nModel ? ' and ' + nModel + ' model terms' : '') + (g.updated_at ? ' · updated ' + esc(TA.fmtStamp ? TA.fmtStamp(g.updated_at) : g.updated_at) : '') +
      (g.source === 'catalogue' ? ' · assembled from the ATP and WTA player catalogues until data/glossary.json is published' : '') + '</div></div>' +
      groups.map(x => cardOf(x.name, slug(x.name), x.entries || [], false)).join('') +
      modelGroups.map(x => cardOf('Model terms: ' + x.name, 'model-' + slug(x.name), x.entries, true)).join('') +
      '<div class="card gl-empty" id="gl-none" style="display:none">Nothing in the glossary matches that.</div>';
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
      cards.forEach(c => c.classList.toggle('hidden', !c.querySelector('.gl-entry:not(.hidden)')));
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
      if (grp) { grp.classList.remove('hidden'); grp.scrollIntoView({ block: 'start' }); }
      history.replaceState(null, '', a.getAttribute('href'));
    }));
    if (key) {
      if (key.indexOf('g:') === 0) {
        const grp = root.querySelector('.gl-group[data-group="' + key.slice(2).replace(/"/g, '') + '"]');
        if (grp) setTimeout(() => grp.scrollIntoView({ block: 'start' }), 0);
      } else {
        const e = document.getElementById('gl-' + key);
        if (e) { e.classList.add('hit'); setTimeout(() => e.scrollIntoView({ block: 'center' }), 50); setTimeout(() => e.scrollIntoView({ block: 'center' }), 400); }
        else { input.value = key; filter(); }
      }
    }
  });
}

// ── methodology ────────────────────────────────────────────────────────────
// Constants: models/fitted/{elo_params,predict,serve_return}_{atp,wta}.json (both tours are fitted), the
// backtests' data/{atp,wta}/calibration.json, and the module defaults named in each paragraph.

const SRC = f => '<span class="src">oddsmarkets/tennis/' + f + '</span>';

const METHOD_HTML = [
`<section id="m-overview"><h2>What the site does</h2>
<p>The Quant Ace forecasts every ATP and WTA tour-level singles match (Grand Slams, the Finals, the 1000s, 500s and 250s), every tournament draw and the season's races, sets those forecasts beside the prediction markets and the bookmakers' closing odds, and backs them with player analytics. Qualifying, Challenger and WTA 125 matches feed the ratings but are not forecast or scored.</p>
<p>Three ideas carry the models. <strong>Surface Elo</strong> rates who wins. A <strong>serve/return model fitted to game and set scores alone</strong> rates how each player wins: how often the player holds and breaks, on each surface, with an uncertainty. An <strong>exact Markov chain</strong> turns serve-point probabilities into match, set-score, total-games and live probabilities. The match forecast blends Elo and the chain, and the backtest scores it against Pinnacle's closing line.</p>
<p>Point-level statistics (aces, first-serve points won and so on) are public only for WTA matches, from the WTA's own API, and for matches the Match Charting Project has charted (both tours, about 600–800 a year, mostly big matches). For every other ATP match the serve and return figures on the site are inferred from scores; the <a href="#/wta/calibration">WTA calibration page</a> tests that inference against the real numbers.</p></section>`,

`<section id="m-data"><h2>Data sources and licences</h2>
<h3>tennis-data.co.uk: results and closing odds</h3>
<p>Every ATP match since 2000 and every WTA match since 2007 at tour level, with round, surface, best-of, set scores, ranks and points, the result status from the Comment column, and closing odds. The yearly workbooks sit under a prefix the site changes; the fetcher reads <code>data.php</code>, then <code>alldata.php</code>, and takes the first page whose links carry a prefix (pattern <code>[prefix/]YYYY[w]/YYYY.xls[x]</code>, a <code>w</code> after the year for the WTA). Files are <code>.xlsx</code> from 2013 and <code>.xls</code> before; a re-request sends If-Modified-Since and a 304 means unchanged. Odds kept, as decimal closing odds for both players, only when both exist and exceed 1: <strong>Pinnacle</strong> (<code>PS</code>), <strong>Bet365</strong> (<code>B365</code>), the market <strong>average</strong> and <strong>best</strong> odds (<code>Avg</code>, <code>Max</code>) and the <strong>Betfair Exchange</strong> (<code>BFE</code>). The file has no tiebreak points and no seeds, and before 2003 its date is the tournament's start. Results and odds are credited to tennis-data.co.uk.</p>${SRC('sources/tennisdata.py')}
<h3>ESPN: live scores, draws and rankings</h3>
<p>The public scoreboard (<code>site.api.espn.com/apis/site/v2/sports/tennis/{atp,wta}/scoreboard?dates=YYYYMMDD</code>, or a whole year with <code>?dates=YYYY</code>; the season scoreboards are empty before 2007, so seasons are read from 2007) gives every match grouped by draw and round with games per set, tiebreak points on 7-6 sets and the live status; <code>…/rankings</code> gives the top 150. ESPN has no match statistics, no point-by-point and does not say who served. The current season's days are re-read from three days ago to two ahead.</p>${SRC('sources/espn.py')}
<h3>The WTA API: draws, matches and serve statistics</h3>
<p><code>api.wtatennis.com/tennis</code> serves the calendar, each tournament's draw (seeds, qualifiers, wild cards, lucky losers) and matches, per-match statistics from 2016, and the rankings. The statistics kept per player, for the match and per set: aces, double faults, serve points, first serves in, first- and second-serve points won, service games, break points faced and saved, return points won, break points converted and played. Grand Slams are ITF events and carry no WTA statistics.</p>${SRC('sources/wta.py')}
<h3>The Match Charting Project: style profiles and charted match statistics</h3>
<p>Shot-by-shot records of volunteer-charted matches (Jeff Sackmann and contributors, Tennis Abstract), read from the project's GitHub files and parsed with its shot-code grammar: serve direction (4 wide, 5 body, 6 T) by serve and court side, rally length (a double fault is 0 shots, an ace 1), the last shot as winner, forced or unforced error, the wing (forehand or backhand), return depth (7 shallow to 9 deep) and net approaches. Per player the site keeps first-serve in and won, second-serve won, ace, double-fault, unreturned and serve-and-volley rates, the direction mix by court side, return points won and depth, rally-length buckets (1–3, 4–6, 7–9, 10+ shots) with points won in each, winners and unforced errors per point by wing, forced errors induced, net frequency and success, and an aggression index, (winners + unforced errors) / shots. The data is licensed <a href="https://creativecommons.org/licenses/by-nc-sa/4.0/" target="_blank" rel="noopener">CC BY-NC-SA 4.0</a>; the derived style tables are shared under the same licence, non-commercially, and the raw files are never committed. Charted matches are a selected sample, weighted to big matches and well-known players.</p>${SRC('sources/charting.py')}<span class="src">scripts/tn_charting.py</span>
<p>Charted match pages (the last two seasons): each charted match is placed on its store match by both players' names, the dates and the round, and its points give the match statistics (aces, double faults, first serves in and won, second serves won, service games, break points, return points won, per set too) and a deep dive (first-serve direction, points won by rally length, winners and errors, net points). Against the WTA's own statistics for the 650 matches that have both (2025–26), aces, double faults, serve and return points and break points agree exactly in 96–99% of matches and first serves in in 85% (within one in 96%).</p>${SRC('analytics/charted.py')}
<h3>Wikipedia: ATP Challenger results</h3>
<p>Main-draw singles of every ATP Challenger since 2009 (about 93,000 matches), read from Wikipedia's season pages ("2024 ATP Challenger Tour": the week, surface and the link to each Singles draw) and draw pages (the bracket templates' own parameters: players, seeds, set scores with tiebreak points, retirements and walkovers). Only article pages are read, at 1.5 s intervals, and each page is fetched once; the current season's recent weeks are re-read at most daily. A match is dated by its round from the week's Monday (final on the Sunday, semi-final Saturday, quarter-final Friday, second round Thursday, first round Wednesday), on or after the day it was played. Players are matched to the tour's registry by full name and flag (transliterations such as Đere → Djere, nicknames by surname, country and initial); about 2,200 who never reached the tour stay Challenger-only. The rows feed Elo, the game-share Elo, serve/return, the market rating and the schedule terms, carry each player's last tour rank (or 250 for a newcomer, chosen on 2012–2017), and are never forecast or scored. Results credited to Wikipedia contributors (CC BY-SA 4.0).</p>${SRC('sources/wikipedia.py')}${SRC('models/challengers.py')}
<h3>Prediction markets</h3>
<p>Kalshi (match series <code>KXATPMATCH</code> / <code>KXWTAMATCH</code>, tournament winners, Finals winner and qualification, year-end No. 1, next year's Slams) and Polymarket (tag "tennis": match winners, tournament winners, "player to qualify", year-end No. 1 and top 10). See <a href="#/methodology/markets">markets</a>.</p>${SRC('sources/markets.py')}
<h3>The client</h3>
<p>Every source goes through one paced client: 0.5 s between calls, up to 4 attempts, a call budget per run (2,000 by default), a 60 s timeout. After a network error it waits 3 s times the attempt; after HTTP 429 or a 5xx it waits for Retry-After, or 10 s times the attempt, at most 120 s. A bad answer is logged and skipped; running out of budget stops a backfill cleanly so the next run resumes.</p>${SRC('sources/_client.py')}</section>`,

`<section id="m-identity"><h2>Identity: one id per player and event</h2>
<p>A player's id is the ESPN athlete id, or <code>x:&lt;slug of the name&gt;</code> when ESPN does not know the player; when an <code>x:</code> player later gets an ESPN id, the record is renamed and the old id redirects to the new one. Sources are merged season by season, newest first: ESPN, then the WTA API, then tennis-data.co.uk, then the rankings.</p>
<p>Full names (ESPN, WTA, markets, charting) match on the WTA or ESPN id first, then on folded aliases (accents and punctuation removed, Chinese name order reversed), preferring players in the same draw, then a unique candidate, then country, then date of birth; different dates of birth mean namesakes. tennis-data.co.uk writes "Sinner J."; those are matched in this order: the overrides file, the event's own field of full names (score 3 for surname and every initial, 2 for surname and first initial, less for a reversed Chinese order or a dropped second surname), a unique earlier alias, the whole tour, the event's only player with that surname; anything left becomes a flagged new player and is reported as unresolved. tennis-data events are placed on stored events by the overlap of their matchups (at least 30% shared and a 20-point lead over the runner-up, within four days). A WTA-only and an ESPN-only profile are merged when the same match ties them and surname and first initial agree.</p>
<p>Tournaments get a canonical slug (<code>wimbledon</code>, <code>indian-wells</code>) from name patterns, city aliases or the city; an event is <code>&lt;tid&gt;-&lt;year&gt;</code>. Levels are <code>slam</code>, <code>finals</code>, <code>m1000</code> (ATP Masters and WTA 1000, including the WTA's Premier Mandatory and Premier 5 events of 2009–2020), <code>500</code>, <code>250</code>, <code>other</code> (Olympics, Elite Trophy), <code>ch</code> and <code>q</code>. Team events and exhibitions (United Cup, Davis and Billie Jean King Cups, Laver Cup, Six Kings, the Next Gen Finals) are skipped.</p>${SRC('canon.py')}${SRC('overrides.json')}
<h3>Ranking points and formats</h3>
<p>Points for losing in each round (W = the title), hand-entered from the 2025 rulebooks:</p>
<table class="tbl"><thead><tr><th>Level</th><th>W</th><th>F</th><th>SF</th><th>QF</th><th>R16</th><th>R32</th><th>R64</th><th>R128</th></tr></thead><tbody>
<tr><td>ATP Slam</td><td>2000</td><td>1300</td><td>800</td><td>400</td><td>200</td><td>100</td><td>50</td><td>10</td></tr>
<tr><td>ATP 1000</td><td>1000</td><td>650</td><td>400</td><td>200</td><td>100</td><td>50</td><td>30</td><td>10</td></tr>
<tr><td>ATP 500 (32)</td><td>500</td><td>330</td><td>200</td><td>100</td><td>50</td><td>0</td><td></td><td></td></tr>
<tr><td>ATP 250 (32)</td><td>250</td><td>165</td><td>100</td><td>50</td><td>25</td><td>0</td><td></td><td></td></tr>
<tr><td>WTA Slam</td><td>2000</td><td>1300</td><td>780</td><td>430</td><td>240</td><td>130</td><td>70</td><td>10</td></tr>
<tr><td>WTA 1000</td><td>1000</td><td>650</td><td>390</td><td>215</td><td>120</td><td>65</td><td>35</td><td>10</td></tr>
<tr><td>WTA 500 (32)</td><td>500</td><td>325</td><td>195</td><td>108</td><td>60</td><td>1</td><td></td><td></td></tr>
<tr><td>WTA 250</td><td>250</td><td>163</td><td>98</td><td>54</td><td>30</td><td>1</td><td></td><td></td></tr>
</tbody></table>
<p>56-draw 1000s and 48-draw 500s and 250s have their own tables. The Finals pay 200 per round-robin win, 400 for the semi-final and 500 for the final (1,500 at most). ATP Slam main draws are best of five; everything else best of three. The deciding set: the Australian Open plays advantage to 2018 and a tiebreak to 10 from 2019; Roland Garros advantage to 2021 and a tiebreak to 10 from 2022; Wimbledon advantage to 2018, a 7-point tiebreak at 12-12 in 2019–2021, a tiebreak to 10 from 2022; the US Open a 7-point tiebreak to 2021 and a tiebreak to 10 from 2022; the Olympics advantage final sets to 2012 and a 7-point tiebreak from 2016; every other event (the Finals included) a 7-point tiebreak at 6-6. No-ad scoring is not modelled.</p>${SRC('canon.py POINTS, final_set_rule')}</section>`,

`<section id="m-elo"><h2>Surface Elo</h2>
<p>Each player carries four ratings: overall, hard, clay and grass (carpet counts as hard). A match forecast uses a blend of the two that apply:</p>
<div class="eq">m<sub>i</sub> = w · R<sub>i,surface</sub> + (1 − w) · R<sub>i,all</sub>
P(i beats j) = 1 / (1 + 10<sup>−f · (m<sub>i</sub> − m<sub>j</sub>) / 400</sup>),   f = bo5 in a best-of-five match, else 1</div>
<p>After the match the overall rating moves by g · K(n<sub>all</sub>) · (S − E<sub>all</sub>), with E<sub>all</sub> computed from overall ratings only, and the surface rating by g · K(n<sub>surface</sub>) · (S − E<sub>surface</sub>), each with its own count of matches n. The step shrinks with experience:</p>
<div class="eq">K(n) = k<sub>a</sub> / (n + k<sub>b</sub>)<sup>k<sub>c</sub></sup></div>
<p>g = 1 for a completed match and <code>ret_k</code> for a retirement or default; walkovers are not rated. After more than <code>idle_days</code> without a match every rating is pulled towards 1500: R → 1500 + (R − 1500) · ρ<sup>(gap − idle_days)/365</sup>. A newcomer starts at c<sub>0</sub> − c<sub>1</sub> · ln(rank) from the rank at the first match, or at the unranked value. Qualifying and Challenger matches move the ratings; the constants are fitted by Nelder-Mead on the log-loss of completed tour-level matches in 2005–2019.</p>
<table class="tbl"><thead><tr><th>Constant</th><th>ATP (fitted)</th><th>WTA (fitted)</th><th>Code default</th></tr></thead><tbody>
<tr><td>k<sub>a</sub>, k<sub>b</sub>, k<sub>c</sub></td><td>115.56, 4.552, 0.2769</td><td>90.84, 0.5146, 0.2194</td><td>250, 5, 0.4</td></tr>
<tr><td>w (surface weight)</td><td>0.4593</td><td>0.2840</td><td>0.5</td></tr>
<tr><td>bo5 stretch f</td><td>1.3658</td><td>0.9958 (WTA Slams are best of three)</td><td>1.1</td></tr>
<tr><td>idle_days, ρ</td><td>60, 0.5801</td><td>60, 0.6580</td><td>60, 0.8</td></tr>
<tr><td>c<sub>0</sub>, c<sub>1</sub>, unranked</td><td>2000.0, 99.34, 1213.1</td><td>2088.6, 121.01, 1355.1</td><td>1900, 70, 1400</td></tr>
<tr><td>ret_k</td><td>0.8664</td><td>0.8987</td><td>0.5</td></tr></tbody></table>
<p>With the ATP values K is about 76 for a debut, 55 after 10 matches, 32 after 100 and 17 after 1,000; with the WTA values about 105, 54, 33 and 20. The ATP fit's log-loss is 0.5853 on 38,985 matches against 0.5884 with the defaults; the WTA fit's 0.6031 on 31,158 against 0.6068. The code defaults apply only to a tour without a committed fit. There is no indoor term and no shrinkage between seasons. All-time peaks on the <a href="#/atp/elo">Elo page</a> start in 2000 (ATP) and 2007 (WTA), the first years of results on file, so earlier careers are not covered.</p>${SRC('models/elo.py')}${SRC('models/fitted/elo_params_atp.json, elo_params_wta.json')}</section>`,

`<section id="m-serve-return"><h2>The serve/return model from scores</h2>
<p>This is the core novelty: serve and return strength estimated for every player from nothing but the game and set scores that every source publishes. The probability that player i holds serve against player j is</p>
<div class="eq">logit P(i holds v j) = μ + surface + indoor + best-of-5 + level + (s<sub>i</sub> + ds<sub>i,surface</sub>) − (r<sub>j</sub> + dr<sub>j,surface</sub>)</div>
<p>Each player has a serve strength s, a return strength r and a deviation of each for clay, grass and hard. The baseline terms are shared. The committed baselines through 1 October 2026: ATP μ = 1.092, clay −0.167, grass +0.322, indoor +0.151, best-of-5 −0.233, and by level Slam +0.132, Finals +0.135, 1000 +0.065, 500 +0.122, 250 +0.076, other −0.365, qualifying −0.109; WTA (with the point layer below) μ = 0.245, clay −0.128, grass +0.248, indoor +0.139, and by level Slam −0.119, Finals −0.107, 1000 +0.018, 500 0.000, 250 −0.067, other −0.083, WTA 125 −0.114, qualifying −0.161. The site's forecasts pass each match's indoor flag to the model, as the backtest does.</p>
<h3>From a hold probability to a set score: the likelihood</h3>
<p>A set score such as 6-4 or 7-6(5) is not a sequence of holds and breaks: the order is unknown, and so is who served first. The model therefore scores each set by summing over every order exactly, with a dynamic program over game scores. Let h<sub>A</sub> and h<sub>B</sub> be the two hold probabilities and let A serve the first game. Games alternate, so in game k (counting from 0) A serves when k is even. Write P(a, b) for the probability that the set passes through a games to b:</p>
<div class="eq">P(0, 0) = 1
P(a+1, b) += P(a, b) · (A serves game a+b ? h<sub>A</sub> : 1 − h<sub>B</sub>)
P(a, b+1) += P(a, b) · (A serves game a+b ? 1 − h<sub>A</sub> : h<sub>B</sub>)</div>
<p>swept up to 5-5. A score of 6-x with x ≤ 4 is P(5, x) times A winning the next game. From 5-5 the two next games are one service game each, so with W = P(A wins both), L = P(B wins both) and T = 1 − W − L:</p>
<div class="eq">P(7-5) = P(5,5) · W,   P(5-7) = P(5,5) · L,   P(6-6) = P(5,5) · T</div>
<p>A 7-6 or 6-7 set adds the tiebreak, which is played point by point. The hold probabilities are turned back into serve-point probabilities by inverting the game formula. A server who wins each point with probability p (q = 1 − p) holds with</p>
<div class="eq">G(p) = p<sup>4</sup> (1 + 4q + 10q<sup>2</sup>) + 20 p<sup>3</sup> q<sup>3</sup> · p<sup>2</sup> / (1 − 2pq)</div>
<p>(0.6 gives 0.736) and p = G<sup>−1</sup>(h) is found by 34 bisection steps and 3 Newton steps. In the tiebreak the set's first server serves point 0; then the serve changes every two points, so A serves point k when ⌊(k+1)/2⌋ is even. The tiebreak's own lattice is swept exactly to (N−1, N−1), where N is 7 or 10, and from a tie the next two points are one serve each, so with W = p<sub>A</sub>(1 − p<sub>B</sub>) and L = (1 − p<sub>A</sub>)p<sub>B</sub>, P(A wins from a tie) = W / (W + L). Exact tiebreak points are used when the source gives them and they are consistent; otherwise only who won. Advantage deciding sets follow the pairs of games to 20 each, and the Wimbledon 2019–2021 rule (tiebreak at 12-12) is handled.</p>
<p>Who serves first in the next set flips when the set had an odd number of games (a tiebreak counts as one). The first server of the match is unknown, so the match likelihood mixes the two openings:</p>
<div class="eq">L(match) = ½ ∏<sub>sets</sub> P(set | A served first) + ½ ∏<sub>sets</sub> P(set | B served first)</div>
<p>computed on the log scale. Only completed sets enter: a retirement keeps the sets finished before it, a walkover contributes nothing. Scorelines are parsed into regular sets (6-x), extended sets (7-5, and longer deciding sets under advantage) and tiebreak sets, the tiebreak's length (7 or 10) following the event's rule.</p>
<h3>Fitting</h3>
<p>The parameters maximise the time-weighted log-likelihood minus ridge penalties:</p>
<div class="eq">Σ<sub>m</sub> w<sub>m</sub> log L<sub>m</sub> − λ/2 (|s|² + |r|²) − λ<sub>d</sub>/2 (|ds|² + |dr|²) − λ<sub>b</sub>/2 |base|²,   w<sub>m</sub> = 0.5<sup>age/half-life</sup></div>
<p>by L-BFGS-B with an exact gradient, warm-started from the previous fit. Matches older than <code>window_days</code> are dropped. The ATP constants were tuned by forward validation (fit on 1 January and 1 July of 2014–2019, score the next 181 days of scorelines): ATP half-life 540 days, λ = 8, λ<sub>d</sub> = 64, λ<sub>b</sub> = 1, window 1,460 days; WTA (tuned the same way) 365 days, λ = 16, λ<sub>d</sub> = 64, λ<sub>b</sub> = 1, 1,460 days. The code defaults, used only without a committed fit, are 365 days, 2, 8 and 1. Standard errors come from a Laplace approximation on each player's block of the curvature (opponent and baseline uncertainty ignored), and they are the bands on the player pages.</p>
<p>What a player page shows: hold % = σ(μ<sub>surface</sub> + s − r̄) and break % = 1 − σ(μ<sub>surface</sub> + s̄ − r), both against the average tour-level opponent (s̄, r̄ = the mean serve and return strengths over tour-level appearances), and expected serve points won = G<sup>−1</sup>(hold). "All surfaces" uses the player's own mix of surfaces.</p>${SRC('models/serve_return.py')}${SRC('models/fitted/serve_return_atp.json, serve_return_wta.json')}</section>`,

`<section id="m-wta-points"><h2>The WTA point layer</h2>
<p>Where a WTA match has statistics, two extra terms enter the likelihood for each player: the serve points won, binomial with probability p<sub>o</sub> = σ(logit G<sup>−1</sup>(h) + k<sub>spw</sub>), and the service games held (service games minus breaks), binomial with probability σ(η + k<sub>hold</sub>), where η is the hold model's log-odds. Each needs at least 10 serve points and consistent counts, and both are weighted by <code>stats_weight</code> = 1. The two offsets let the real numbers sit where they sit. On the WTA's stats matches (2016–2025) the mean real hold (0.651) is in fact slightly above what G applied to the mean real serve-point rate gives (0.648), so the game formula alone is close to right on average; what sits lower is the chain-scale hold, the level at which independent points reproduce the scorelines: real holds run above it (fitted k<sub>hold</sub> ≈ +0.35, k<sub>spw</sub> ≈ +0.16 on the log-odds scale), because real scorelines are more lopsided than independent points at the real rates would make them. Scores and statistics describe the same match, so this counts some evidence twice; the code says so. The layer is on for the WTA only; the backtest's serve/return baseline and the validation switch it off.</p>${SRC('models/serve_return.py fit(stats=True)')}</section>`,

`<section id="m-match-chain"><h2>The match chain</h2>
<p>Given each player's probability of winning a point on serve, an exact Markov chain gives everything else: game → tiebreak → set → match, with best of 3 or 5 and the event's deciding-set rule (tiebreak to 7 at 6-6, to 10 at 6-6, to 7 at 12-12, or advantage, followed exactly to 30 games each and then closed with the exact win probability). From deuce a game is won with p<sup>2</sup>/(p<sup>2</sup> + q<sup>2</sup>); the tiebreak uses the same serve rotation as above. The first server is a coin toss. A forward pass over sets carries the set scores, the total-games and game-margin distributions and the probability of no tiebreak, so one call returns P(win), the set-score distribution ("2-0", "2-1" …), total games, the handicap distribution, P(at least one tiebreak), P(straight sets) and the expected games. A backward version (the live table) gives the win probability from any score.</p>
<p>A dispersion option averages the chain over a per-match swing e ~ N(0, σ²) applied as (p<sub>A</sub> + e, p<sub>B</sub> − e), with 7-point Gauss-Hermite quadrature (the pair clipped to [0.01, 0.99]). σ is fitted walk-forward by the backtest (the set-score likelihood on earlier years over a grid from 0 to 0.08) and committed with the blend: σ = 0.04 for both tours (predict_atp.json, predict_wta.json); 0.03 is the code default without a fit.</p>${SRC('models/match_chain.py')}</section>`,

`<section id="m-predict"><h2>The match forecast</h2>
<ol><li>The serve/return probability: each player's hold against this opponent from the fitted model (with the match's surface, level, best-of and indoor flag), turned into serve-point probabilities p = G<sup>−1</sup>(h), and the chain's P(win).</li>
<li>The Elo probability from the surface-blended ratings.</li>
<li>The blend, on the log-odds scale, with no intercept:<div class="eq">logit p = w<sub>Elo</sub> · logit p<sub>Elo</sub> + w<sub>SR</sub> · logit p<sub>SR</sub> + w<sub>G</sub> · (m<sub>A</sub> − m<sub>B</sub>)</div>where m is a <strong>game-share Elo</strong>, a margin-of-victory rating: each player's rating (overall and per surface, on the log-odds scale of the share of games won, starting at 0) moves after every match by 4k × (share of games won − share expected), with share = (games + 0.5) / (total + 1), k = K × (1 for a completed match, 0.5 for a retirement) × min(1, games / 18) × (1 + 3 / (1 + n / 20)) for n the fewer matches of the two, and m = w × surface rating + (1 − w) × overall (ATP K = 0.06, w = 0.4; WTA K = 0.12, w = 0.2); a player never rated contributes no difference. The weights fitted on every backtest year (2010–2026) and committed are ATP w<sub>Elo</sub> = 0.4924, w<sub>SR</sub> = 0.2110, w<sub>G</sub> = 1.0511 and WTA w<sub>Elo</sub> = 0.4661, w<sub>SR</sub> = 0.2896, w<sub>G</sub> = 0.7204. The game-share term was added on 2 October 2026 after a walk-forward test (constants chosen on 2012–2017, tested on 2018–2025) cut log-loss by 0.0024 (ATP) and 0.0046 (WTA); before it the weights were ATP 0.6569 / 0.2879 and WTA 0.7041 / 0.2985. The code defaults (ATP 0.55 and 0.45, WTA 0.6 and 0.4, no game-share term) apply only without a committed fit.</li>
<li><strong>Market rating</strong> (ATP since 21 October 2026, WTA since 22 October): a fourth term, + w<sub>M</sub> · s · (M<sub>A</sub> − M<sub>B</sub>), where M is each player's strength as the closing market rated it, learnt from the de-vigged closing lines (Pinnacle, else the Betfair exchange, else the bookmakers' average) and results of matches already finished, never the match's own closing line: a Kalman filter on the log-odds scale with an overall rating and a surface offset per player, uncertainty that grows while a player is idle, newcomers starting from their ranking, and every day forecast from the ratings at the end of the day before; s = 1.4 for best of five. The market rating takes over most of what Elo and serve/return carried (serve/return still shapes the scorelines); since 22 October the ATP's inputs include Challenger results, which cut the test log-loss by a further 0.0028 and halved the gap to the close on matches with a newcomer. In a walk-forward test (constants chosen on 2012–2017, tested on 2018–2025) it cut log-loss by 0.0115 (ATP) and 0.0049 (WTA), closing 45% and 32% of the gap to Pinnacle's close. It makes the model better informed, not better than the market: the close and Kalshi's quotes are still sharper. The head-to-head page uses it too, from each player's current market rating (published in <code>elo.json</code>).</li>
<li><strong>Schedule and form</strong> (ATP since 22 October 2026): + Σ w<sub>k</sub> x<sub>k</sub> over six differences between the players: rest (log of the days since the last match, 1 to 60), matches in the last 30 days (difference clipped to ±15, ÷ 5), log ranking points, form (a decayed mean of result minus the Elo expectation, half-life 8 matches, × 5), a retirement in the last match, and head to head ((wins − losses) / (meetings + 3)). Every level counts, Challengers included. In the walk-forward test it cut log-loss by a further 0.0015 on the ATP (2018–2025, CI −0.0024 to −0.0006) with calibration improving; on the WTA it also helped (−0.0012) but the calibration slope moved away from 1, so it is off there. The simulators do not know the day of a future round, so they assume both players played every earlier round of the event: rest and the retirement flag cancel and the rest is taken at the event's start (the test years keep about 70% of the gain that way). Committed ATP weights (fitted on every backtest year with Challengers in the inputs, 22 October 2026): rest −0.057, matches in 30 days 0.122, points 0.004, form −0.072, retirement −0.177, head to head 0.196, alongside w<sub>Elo</sub> = −0.014, w<sub>SR</sub> = 0.032, w<sub>G</sub> = 0.535, w<sub>M</sub> = 0.808. The production backtest (2010–2026, 39,012 matches with a Pinnacle close) scores 0.5794 against 0.5806 without these terms and 0.5831 for the 21 October model; Pinnacle's close 0.5703. The head-to-head page leaves these terms out (a matchup with no date).</li>
<li>The serve-point probabilities are shifted by δ, (p<sub>A</sub> + δ, p<sub>B</sub> − δ), with δ found by 40 bisection steps so that the chain reproduces the blended chance: this centre pair is the one the live probability uses. The set-score, games, handicap and tiebreak distributions come from the σ-mixture (σ = 0.04), with its own shift found the same way so that the mixture's P(win) is the blended chance.</li></ol>
<p>Without serve/return ratings the chain starts from the tour's base serve-point rate (ATP hard .645, clay .625, grass .665; WTA .565, .555, .58); without Elo the serve/return probability stands alone. The head-to-head page repeats this recipe in the browser from the published hold and break rates and the tour's constants in <code>data/&lt;tour&gt;/model.json</code>, so its forecasts can differ by a point or two from the match centre.</p>${SRC('models/predict.py')}${SRC('models/fitted/predict_atp.json, predict_wta.json')}</section>`,

`<section id="m-live"><h2>Live win probability</h2>
<p>The serve-point probabilities are fixed before the match; the live probability is the chain evaluated from the current score (sets, games, points when known, and the server). ESPN does not say who served, so the first server is the maximum-likelihood choice given the set scores, and when the order of games inside a set was not observed it is reconstructed by the most likely sequence of holds and breaks (flagged "reconstructed"). Leverage of a game is P(win | the game is won) − P(win | it is lost). Excitement is the sum of the absolute changes in win probability from the pre-match chance to the final 0 or 1. The comeback figure is the winner's lowest win probability on the way and where it came. Swings are the five largest moves.</p>${SRC('models/live.py')}</section>`,

`<section id="m-tournament"><h2>Tournament simulation</h2>
<p>Each draw is played 20,000 times on its real bracket: byes stay byes; an empty qualifier or lucky-loser slot is a placeholder rated 0.4 below the median opponent on the log-odds scale; finished matches are fixed. WTA draws come from the WTA's own draw endpoint, with seeds and entry types. ATP draws (and any event without a fetched draw) are rebuilt from ESPN, which publishes no bracket: before the draw is made its slots are all "TBD"; once it is made the first-round pairings appear by name, but no seed, no bracket position and no link from a first-round match to its second-round slot. A played or scheduled match therefore links its two players' earlier matches, and first-round pairings that no later round links yet are placed in date order. Until the second round is set, an ATP simulation's paths beyond the first round are approximate, and seeds are not shown. Match forecasts come from the blend (the event's surface, best-of and deciding-set rule). Outputs per player: P(title), P(final), P(semi-final), P(quarter-final), the probability of reaching each round, expected ranking points by exit round, and the next match's opponents with odds conditional on winning it. The Finals play their round robin: group order by wins, then the head-to-head when two are tied, then set and game percentages, then seed; semi-finals A1–B2 and B1–A2. Retirements are not simulated and player strength is held fixed within a run.</p>${SRC('models/tournament_sim.py')}</section>`,

`<section id="m-season"><h2>Season simulation: the Race and year-end No. 1</h2>
<p>The rest of the calendar is simulated 10,000 times for the top 120 players. Entry: mandatory events 92% (scaled down by a player's own 12-month Slam and 1000 participation unless the player played that event last season), events a player played last year 70%, a new 500 20%, a new 250 8% (halved for the top 10 at 250s); players in Race positions 6–20, chasing the last Finals places, enter a new 500 with 45% and a new 250 with 30%; at most one event a week. A player who has missed two or more Slams and 1000s since the last match is treated as absent (probably injured): in each simulation the player returns this season with probability 0.5, keeping the normal entries and the Finals if qualified, or plays nothing more (an absent qualifier is replaced by the first alternate). Fields are seeded in standard positions with byes to the top seeds; the rest of the field plays at the median strength of ranks 60–120. Year-end ranking points are the Race points plus the simulated points still to come plus the Finals points: the year-end ranking counts the 52 weeks back to the week after last season's Finals, so every one of last season's results has dropped by then. The Race counts this year's points only (Finals excluded). The route through the latest official ranking (minus last season's points that drop, plus points earned since and simulated) is reported only as a check. The Finals take the Race's top eight; on the ATP a season Slam champion ranked 9–20 replaces the eighth. Year-end No. 1 is the leader on points in each simulation. Simplifications the code publishes: every result counts (no best-18 rule), no injuries or withdrawals beyond random non-entry and the absence rule, no Finals alternates, no qualifying or Challenger points, strengths frozen at today's values, last season's calendar for events not yet listed, shifted 52 weeks plus the whole weeks by which this season has been running late or early (the median drift of the last six listed events, capped at two weeks; in 2026 the calendar ran a week late from the summer, which had put Basel and Vienna into Paris's week and kept the top ten out of Paris until the drift was measured), with an unlisted event that should have started more than three days ago dropped as past (Stockholm 2026), and every future match treated as a 500 with a 7-point final-set tiebreak.</p>${SRC('models/season_sim.py')}</section>`,

`<section id="m-markets"><h2>Markets and de-vig</h2>
<p>A two-sided market's number is the midpoint (bid + ask)/2, used only when 0 &lt; bid ≤ ask &lt; 1 and the spread is at most 0.12; last trades are never used. Field markets (tournament winner, year-end No. 1, Finals winner) average the sources per runner and are published only when enough runners are accounted for (at least max(4, half the field)) and the implied total lies in [0.8, 1.3]; otherwise they are flagged thin. They are de-vigged multiplicatively, p<sub>i</sub> = (1/o<sub>i</sub>) / Σ(1/o<sub>j</sub>). Per-player yes/no markets (to qualify for the Finals, top 10) are averaged and not de-vigged. A match's market number is the mean of the prediction-market sources, else Pinnacle's de-vigged close, else the average close. Names are matched against the event's field first and never guessed; unmatched labels are reported.</p>${SRC('sources/markets.py')}</section>`,

`<section id="m-backtest"><h2>Backtest and calibration</h2>
<p>Every completed tour-level match (Slams, Finals, 1000s, 500s, 250s) from 2010 is predicted walk-forward, with two warm-up years before. The serve/return model is refitted every 30 days through the day before; the blend weights for year Y are fitted on the years before Y (a year with nothing earlier uses the tour's own committed blend); Elo ratings walk forward, though its constants were fitted on 2005–2019, so 2010–2019 is in-sample for the constants (the backtest says so). Each match is oriented to a player chosen by a hash of its id. Forecasters scored: the match model, Elo alone, the serve/return chain alone, a ranking baseline P = σ(b · (ln rank<sub>2</sub> − ln rank<sub>1</sub>)) with unranked = 300 and b fitted on earlier years, and the de-vigged closing lines of Pinnacle, Bet365, the average and the best line. Metrics: log-loss (p clipped to [0.0001, 0.9999]), Brier and ten-bin reliability, overall, on the matches with a Pinnacle or average line, by year and by level. Retirements, walkovers and defaults are not scored.</p>
<p>Distribution checks: set-score calibration and multi-class log-loss, straight sets and tiebreak reliability, total games over/under lines (best of 3 at 19.5–25.5, best of 5 at 33.5–41.5) with a randomised PIT histogram, the game-handicap log-loss, and the live probability at each set boundary. Tournament checks simulate each draw 3,000 times before the first round and at the quarter-finals, and score title, final and semi-final odds. For the WTA the score-only model is validated against the real statistics in two ways. Per player over a two-year window (730 days, ending at the last completed match on or before the run date; 15+ matches with stats), the inferred hold and serve-points-won against the real ones, with Pearson and Spearman correlations, RMSE and bias: r ≈ 0.72 for hold and 0.73 for serve points won (151 players). Per player and season (2016–2025, 15+ stats matches), fitting through 31 December and comparing on that season (in sample) and on the next January–June (out of sample): single-season correlations are much weaker, 0.43 in sample and 0.28 out of sample for hold (0.43 and 0.29 for serve points won), because one season of scores carries little information about how a player holds. Everything is on the <a href="#/atp/calibration">calibration page</a>.</p>${SRC('models/backtest.py')}</section>`,

`<section id="m-analytics"><h2>The player catalogue</h2>
<p>138 metrics per player for the selected year: results (win %, against the top 10 and 20, titles, wins over the model's expectation), ratings (Elo by surface), inferred serve and return (hold %, break %, serve and return ratings, expected serve and return points won), the WTA's real serve and return statistics (ace and double-fault rates, first serves in, first- and second-serve points won, serve and return points won, dominance ratio, break points saved and converted), clutch (tiebreaks and deciding sets against the chain's expectation, wins from a set down, bagels), efficiency (games per set, straight-set wins), form (Elo change over 30, 90 and 365 days) and charted style. Percentiles rank a player against every qualified player on the tour (100 = best, lower-is-better metrics flipped), or against the players with enough matches on one surface; below the match floor values are shown without percentiles. Definitions are in the <a href="#/glossary">glossary</a>.</p></section>`,

`<section id="m-site"><h2>How the pages compute what they show</h2>
<ul><li><strong>The lab</strong> can shrink a rate towards the median of the players on screen with a prior of 15 matches: (matches × rate + 15 × median) / (matches + 15). Ratings, Elo, ranks and counts are never shrunk. A multi-year window sums counts and over-expected figures, averages rates weighted by matches and takes ratings from the latest year. Labelled players are the eight with the largest sum of standard scores on both axes in the better direction and the four with the smallest.</li>
<li><strong>Head to head</strong> forecasts the matchup in the browser with the model's recipe (above). A player's hold against this opponent is recovered from the published rates as logit h<sub>AB</sub> = logit hold<sub>A</sub> + logit(1 − break<sub>B</sub>) − logit h<sub>tour</sub>, where h<sub>tour</sub> is the matches-weighted average hold of the catalogue moved to the surface by the tour's own fitted surface terms; the chain is then run on the chain scale (minus the tour's k<sub>hold</sub>, plus the best-of-5 term in a best-of-five match). Every constant comes from <code>data/&lt;tour&gt;/model.json</code>, which the build writes from the committed fits. "Against the ratings" compares the wins in the listed meetings with the sum of the pre-match probabilities, with z = (wins − expected) / √Σp(1 − p).</li>
<li><strong>Compare</strong> counts a metric as won by the higher percentile, on the tour or one surface's pool, and lists the three largest gaps each way.</li>
<li><strong>The results log</strong> on a player page plots wins minus expected wins, cumulatively, and the log-loss of the model and the closing market on the matches both cover.</li>
<li><strong>Calibration</strong> bins show ±2 binomial standard errors, √(p(1 − p)/n); "skill v coin" is 1 − log-loss / ln 2.</li></ul></section>`,

`<section id="m-value"><h2>Value: breakouts, luck, and the ranking and the market against the model</h2>
<p>The Value pages (<a href="#/atp/value">#/value</a>) answer three questions with the models above. ${SRC('analytics/value.py')} Every number has a glossary entry (search "Value").</p>
<h3>One number per player: the model rating</h3>
<p>The match forecast is logit p = w<sub>Elo</sub> logit(Elo p) + w<sub>SR</sub> logit(serve/return p) + w<sub>g</sub> (game-share difference). Around an even best-of-three hard-court match it is a difference of one number per player, on the Elo scale: R = w<sub>Elo</sub> Elo + (400 / ln 10)(w<sub>SR</sub> β (s + r) + w<sub>g</sub> G), where s + r is the serve plus return rating and β = d logit(chain P) / d(s + r) at an even match (about 2.0 a unit). A constant is added so the active top 100 average the same as on Elo. Surface ratings use the surface-blended Elo and game-share Elo and the surface serve/return record. The <b>model rank</b> orders R among players with a rated match in the last year and 10+ rated matches; the <b>rank the model implies</b> hands the official ranks of the same players (those inside the top 300) out in the order of R. "Points at the implied rank" is what the player holding that rank has.</p>
<h3>Breakout and regression forecasts</h3>
<p>Quarterly snapshots (1 January, April, July, October) from 2008 (ATP) and 2009 (WTA); at each, the players whose latest official rank on a match in the 120 days before is 150 or better. The target is the change in log rank to the rank on record nearest 12 (or 6) months later, within 45 days; a player with none there (usually out of tour-level main draws, injured or retired) is "unobserved". Features, all from before the snapshot: the log rank; the gap between the official rank and the rank the model implies; age (and its square; dates of birth from the WTA API and ESPN); the Elo change and the rank change over six months; days since the last match; rated matches in 12 months; tour-level points that drop within the horizon and the tour-level share of the official points (the points calendar); close-match and draw luck per match over 12 months; and the closing market's rating of the player against Elo's. A ridge regression on standardised features is refitted every year on the snapshots whose outcome was known by 1 January of that year (walk-forward). The penalty (100) and the shrinkage of the gap (none) were chosen on 2010–2017 only; 2018–2025 are the test years. A breakout is a rank at least a third better and 5 places up; a regression a rank at least half worse and 5 places down, or unobserved. Their probabilities are logistic fits on the forecast's distance from the event's threshold at the player's rank and on the log rank, fitted the same way (so No. 1 needs a fall to No. 6 to have regressed). The likely range is the 10th–90th percentile of the model's past errors in the player's rank band; the reasons are the largest contributions (coefficient × standardised value).</p>
<p>Test years 2018–2025 (run of 15 October 2026), Spearman correlation of the forecast with the actual 12-month change: ATP 0.459 [0.42, 0.50], WTA 0.477 [0.44, 0.52], against 0.278 and 0.287 for the same model on the rank alone (regression to the mean) and 0.341 and 0.441 for rank plus the model gap. At 6 months: ATP 0.517, WTA 0.562. The ten likeliest breakouts at each snapshot broke out 44% (ATP) and 52% (WTA) of the time against base rates of 18% and 20%; the ten likeliest regressions regressed 71% of the time on both tours against 43%. Dropping a feature costs most for the model gap and age (ATP 0.05 and 0.07 of correlation; WTA 0.09 and 0.02); the points calendar matters at 6 months (0.02), luck and the trends add nothing measurable. The forecasts cover the official top 150 only, so a player returning from a long absence outside it is not forecast; Challenger and ITF points are not in the data, so the points calendar counts tour-level points only.</p>
<h3>Luck</h3>
<p>Per player, over the last 52 weeks or the current season (tour-level main draws, 10+ matches): <b>close-match luck</b> = wins − Σ P(win | share of games won in the match), the Pythagorean expectation s<sup>k</sup> / (s<sup>k</sup> + (1 − s)<sup>k</sup>) with k fitted on matches to 2017 (about 20 for best of three, 26 for best of five); <b>draw luck</b> = Σ [Elo P(win v the actual opponent) − the mean Elo P(win) v the typical opponents met at that level, round and seed band in earlier years, placed relative to the strength of the event's field] (averaging over the distribution, not using the mean opponent, keeps strong players from showing systematic bad luck); <b>free wins</b> = walkovers and opponents' retirements, each worth 1 − P(win at the stoppage). Their sum is the <b>wins above expectation</b>. Tiebreaks and deciding sets against the chain's odds show where close-match luck came from; on the WTA, break points saved and converted are set against the player's own serve and return points won outside break points (plus the tour's pressure offset, ±0.014). The points-to-games conversion (expected wins from games minus from points) is shown but not counted: it persists from one season to the next (r ≈ 0.5), so it is partly how a player's points turn into games, not luck. The strength of schedule (opponent Elo against the typical one, events chosen included) is reported apart for the same reason.</p>
<p>Evidence it is luck: season-to-season correlations for players with 20+ matches in both seasons (ATP 1,916 pairs, WTA 1,209): wins above expectation per match 0.08 [0.04, 0.13] (ATP) and 0.04 [−0.02, 0.10] (WTA); close-match luck 0.06 and 0.05; tiebreaks 0.04 and −0.02; break points saved −0.02 (WTA). Win % persists (0.67 and 0.57), as does the share of games won (0.72 and 0.64). The luck-adjusted win % predicts next season's win % better than the raw one: correlation 0.683 v 0.667 (ATP, difference +0.016 [0.007, 0.026]) and 0.582 v 0.570 (WTA, +0.012 [0.002, 0.024]); walk-forward error 9.8 v 10.1 points (ATP) and 10.7 v 10.8 (WTA).</p>
<h3>The market against the model</h3>
<p>For each player, the mean gap between the market's pre-match probability and the model's over the last 52 weeks, in Elo points (logit difference × 400 / ln 10): the de-vigged closing line (Pinnacle to January 2026, then the Betfair exchange, else the bookmakers' average) and, where the research cache has it, Kalshi's quote about 4 hours before the start (June 2025 – 1 October 2026). The page shows actual wins against both expectations and which forecaster scored better on the player's matches. Read the gaps as disagreements: the market beat the model in the backtest by about 0.02–0.03 in log-loss, our research found no model or feature that closes that, and blending the model into Kalshi's number made it worse.</p></section>`,

`<section id="m-limitations"><h2>Limitations</h2>
<ul><li><strong>Inferred, not measured.</strong> ATP serve and return figures come from scores alone. Scores say who held, not how many points it took, so two players with the same holds look alike even if one wins service games 40-0 and the other through deuce.</li>
<li><strong>Points are treated as independent</strong> apart from the σ dispersion. The chain uses one serve-point probability per player per match. In the backtest the model forecasts slightly more straight sets than happen (ATP 0.615 v 0.609, WTA 0.677 v 0.665) and fewer total games (ATP 22.8 v 23.4 in best of three and 35.2 v 36.4 in best of five; WTA 21.3 v 21.8). The larger miss is tiebreaks, which are under-predicted: P(at least one tiebreak) 0.324 forecast v 0.394 observed on the ATP, 0.188 v 0.222 on the WTA. The match-winner chance is much less affected than the score distributions.</li>
<li><strong>Single-season inferred ratings are noisy.</strong> On the WTA, where the real statistics exist, a single season's score-inferred hold correlates only 0.28 (out of sample) to 0.43 (in sample) with the real one; two-year averages are much better (0.72).</li>
<li><strong>Indoor</strong> is fitted in the serve/return model and passed with every match forecast; Elo has no indoor term.</li>
<li><strong>Charted style data is a selected sample</strong>, weighted to big matches and famous players.</li>
<li><strong>Simulations</strong> do not model retirements, injuries or withdrawals (beyond the season simulation's absence rule), freeze player strength for the rest of the event or season, treat every future season match as a 500 with a 7-point final-set tiebreak, and count every result (no best-N rule).</li>
<li><strong>Hand-entered tables</strong> (points, levels, draw sizes, deciding-set rules) are marked for verification in the code, and the current points tables apply to every year.</li>
<li>The market beats the model, as it should: the closing line knows things the model never sees.</li>
<li><strong>The Value forecasts</strong> are statistical tendencies: a 51% breakout list is wrong half the time, and the ranks of players outside tour-level main draws are only partly on record (ATP ranks below the ESPN top 150 come from the latest match).</li></ul></section>`
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
  const T = (TA.state && TA.state.tour) || 'atp';
  const toc = '<div class="doc-toc"><div class="doc-toc-head">Methodology</div><ol>' + secs.map(s => '<li><a href="#/methodology/' + esc(s.id) + '" data-target="method-' + esc(s.id) + '">' + esc(s.title) + '</a></li>').join('') +
    '</ol><div class="doc-toc-head" style="margin-top:10px">See also</div><ol><li><a href="#/glossary">Glossary</a></li><li><a href="#/' + T + '/calibration">Calibration</a></li><li><a href="#/disclaimer">Disclaimer and terms</a></li></ol></div>';
  const intro = '<div class="card"><div class="card-header">Methodology <span class="card-sub">Where the data comes from, how every model works, and where it is wrong. Every constant is the one in the code or its committed fit, and each paragraph names its file.</span></div>' +
    '<div class="doc-meta">' + secs.length + ' sections · the ATP\'s and the WTA\'s committed fits, with the code defaults that apply only without a fit</div></div>';
  el.innerHTML = '<div class="doc">' + toc + '<div class="doc-body">' + intro + secs.map((s, i) => '<div class="card" id="method-' + esc(s.id) + '"><div class="card-header">' + (i + 1) + '. ' + esc(s.title) +
    ' <a class="doc-anchor" href="#/methodology/' + esc(s.id) + '" title="Link to this section">#</a></div><div class="pad">' + s.html + '</div></div>').join('') + '</div></div>';
  el.querySelectorAll('.doc-toc a[data-target]').forEach(a => a.addEventListener('click', ev => {
    ev.preventDefault();
    const t = document.getElementById(a.dataset.target);
    if (t) t.scrollIntoView({ block: 'start' });
    history.replaceState(null, '', a.getAttribute('href'));
  }));
  if (want) { const t = document.getElementById('method-' + String(want).replace(/^m-/, '')); if (t) setTimeout(() => t.scrollIntoView({ block: 'start' }), 0); }
}

if (typeof TA.route === 'function') {
  TA.route('glossary', renderGlossary);
  TA.route('methodology', renderMethodology);
}
})(window.TA || (window.TA = {}));
