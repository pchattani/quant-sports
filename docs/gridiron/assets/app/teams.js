/* The Quant Gridiron — teams.json readers (GI.TM) for the team page and Compare. The Teams page itself (#/teams) is
 * gi-teams.js since round 9 (28 Oct 2026): the power board, the team profile grid, the style map, strengths and
 * weaknesses, head to head and through the season replaced the card wall and the table views that lived here. */
(function (GI) {
'use strict';

const isNum = GI.isNum;
const TM = {};
TM.of = d => {
  if (!d || d.ok === false) return null;
  GI.cleanMetrics(d.metrics);
  let teams = d.teams || null;
  if (Array.isArray(teams)) { const o = {}; teams.forEach(t => { const a = t.team || t.abbr; if (a) o[a] = t; }); teams = o; }
  if (!teams) return null;
  return { teams: teams, metrics: d.metrics || [], raw: d };
};
TM.history = x => {
  const raw = (x || {}).history || [];
  const hc = (x || {}).history_cols || ['week', 'net', 'off', 'def'];
  return raw.map(a => { if (!Array.isArray(a)) return a; const o = {}; hc.forEach((c, i) => { o[c] = a[i]; }); return o; }).filter(z => isNum(z.week)).sort((a, b) => a.week - b.week);
};
GI.TM = TM;

})(window.GI);
