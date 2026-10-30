"""
College hockey player numbers and our value model (GAR: goals above replacement), from College Hockey News season
lines (every season), CHN's shot-attempt splits (men from 2013-14) and CHN box scores (2025 on: primary and
secondary assists, time on ice for men, per-game logs). Everything here is CHN-derived: with CHN switched off
(sources/chn.py) no player numbers exist.

Value (goals above a replacement-level player of the same position, level and season)
  skaters
    offence    goals created: GC = (G + 0.5 A) x team goals / (team G + 0.5 team A) (Hockey-Reference's split of a
               team's goals among its scorers), minus the replacement GC per game x GP. Replacement = the 20th
               percentile of GC per game among regulars of the position (10+ games).
    on-ice     0.25 x the player's +/- relative to his team (the team's goal difference per game x GP x 5/18, the
               share of a team's on-ice goals a skater is on for), shrunk by GP / (GP + 25): +/- is noisy and
               blind to usage, so it is a small, damped part.
    penalties  -0.17 goals per minor (PIM / 2), against the position's average rate per game.
    faceoffs   +0.01 goals per net faceoff win (men from 2013-14 and every box season).
  goalies      goals saved above an average goalie on the shots faced, (SV% - league SV%) x SA, shrunk by
               SA / (SA + 600), plus the replacement margin (a replacement goalie saves 1 point of SV% less than
               average) x SA.
  GAR / 6 = WAR (about six goals buy a win in college hockey: a team scores ~3 a game).
Limits (said on the site): no shot locations or on-ice shot data, so no expected-goals-based value; +/- and goals
created reward linemates and power-play time; time on ice only for men from 2025; women's lines are thinner (no
time on ice, no shot-attempt splits). Read the numbers as a production-based value, not a play-driving one.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Any

import numpy as np

GPW = 6.0
MINOR = 0.17
FO_GOAL = 0.01
PM_W = 0.25
PM_K = 25.0
G_K = 600.0
G_REPL = 0.010
POS = ("F", "D", "G")


def _f(x) -> float:
    try:
        return float(x) if x is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def box_lines(store: dict) -> dict[str, dict]:
    """Per-player totals from the season's box scores: {pid: {"gp_box", "a1", "a2", "toi", "toi_n", "fow", "fol",
    "sh_box", "ppg", "shg", "eng", "ppa", "log": [[gid, date, opp, home, res, g, a, pts, pm, sh, toi, pim]]}}"""
    ch = store.get("chn") or {}
    boxes = ch.get("boxes") or {}
    games = {g["id"]: g for g in store["games"]}
    out: dict[str, dict] = defaultdict(lambda: {"gp_box": 0, "a1": 0, "a2": 0, "toi": 0, "toi_n": 0, "fow": 0, "fol": 0,
                                                "ppg": 0, "shg": 0, "eng": 0, "ppa": 0, "evg": 0, "log": []})
    for gid, b in boxes.items():
        g = games.get(gid)
        if not g:
            continue
        for x in b.get("goals") or []:
            per, t, team, pid, name, a1p, a1, a2p, a2, sit, n = x
            sit = str(sit or "EV")
            if pid:
                if "PP" in sit:
                    out[pid]["ppg"] += 1
                elif "SH" in sit:
                    out[pid]["shg"] += 1
                else:
                    out[pid]["evg"] += 1
                if "EN" in sit:
                    out[pid]["eng"] += 1
            if a1p:
                out[a1p]["a1"] += 1
                if "PP" in sit:
                    out[a1p]["ppa"] += 1
            if a2p:
                out[a2p]["a2"] += 1
                if "PP" in sit:
                    out[a2p]["ppa"] += 1
        for r in b.get("skaters") or []:
            pid, team, name, gg, aa, pm, sh, toi, pim, fow, fol = r
            if not pid:
                continue
            o = out[pid]
            o["gp_box"] += 1
            if toi:
                o["toi"] += toi
                o["toi_n"] += 1
            o["fow"] += fow or 0
            o["fol"] += fol or 0
            home = team == g["home"]
            opp = g["away"] if home else g["home"]
            hs, as_ = g.get("hs"), g.get("as")
            res = None
            if hs is not None and as_ is not None:
                mine, theirs = (hs, as_) if home else (as_, hs)
                res = "W" if mine > theirs else "L" if mine < theirs else "T"
                if g.get("so"):
                    res = "T"
            o["log"].append([gid, str(g["date"])[:10], opp, 1 if home else 0, res, gg, aa,
                             (gg or 0) + (aa or 0), pm, sh, toi, pim])
    for o in out.values():
        o["log"].sort(key=lambda r: r[1])
    return dict(out)


def goalie_logs(store: dict) -> dict[str, list]:
    ch = store.get("chn") or {}
    games = {g["id"]: g for g in store["games"]}
    out: dict[str, list] = defaultdict(list)
    for gid, b in (ch.get("boxes") or {}).items():
        g = games.get(gid)
        if not g:
            continue
        for r in b.get("goalies") or []:
            pid, team, name, sv, ga, sec, en = r
            if not pid or en:
                continue
            home = team == g["home"]
            opp = g["away"] if home else g["home"]
            out[pid].append([gid, str(g["date"])[:10], opp, 1 if home else 0, sv, ga, sec])
    for v in out.values():
        v.sort(key=lambda r: r[1])
    return dict(out)


def team_totals(store: dict) -> dict[str, dict]:
    """Team goals, assists (from the players' lines), goal difference and games, per team."""
    ch = store.get("chn") or {}
    tot: dict[str, dict] = defaultdict(lambda: {"g": 0, "a": 0, "gf": 0, "ga": 0, "gp": 0, "sh": 0, "sa": 0})
    for p in (ch.get("players") or {}).values():
        t = tot[p["team"]]
        t["g"] += p.get("g") or 0
        t["a"] += p.get("a") or 0
    for g in store["games"]:
        if g.get("status") != "post" or g.get("hs") is None or g.get("stype") == "exh":
            continue
        for side, gf, ga in (("home", g["hs"], g["as"]), ("away", g["as"], g["hs"])):
            t = tot[g[side]]
            t["gf"] += gf
            t["ga"] += ga
            t["gp"] += 1
            sh = (g.get("chn") or {}).get("sh")
            if sh and sh[0] is not None and sh[1] is not None:
                t["sh"] += sh[0] if side == "home" else sh[1]
                t["sa"] += sh[1] if side == "home" else sh[0]
    return dict(tot)


def season_rows(store: dict) -> dict[str, dict]:
    """Every player's season row with derived rates and the value model. Keys described in PAYLOAD_KEYS."""
    ch = store.get("chn") or {}
    if not ch:
        return {}
    teams = team_totals(store)
    bx = box_lines(store)
    gl = goalie_logs(store)
    box_games = sum(1 for _ in (ch.get("boxes") or {}))
    rows: dict[str, dict] = {}
    for pid, p in (ch.get("players") or {}).items():
        gp = p.get("gp") or 0
        if gp <= 0:
            continue
        pos = p.get("pos") if p.get("pos") in ("F", "D") else ("D" if p.get("pos") == "D" else "F")
        t = teams.get(p["team"], {})
        r = {"id": pid, "name": p["name"], "team": p["team"], "pos": pos, "class": p.get("cls"), "gp": gp,
             "g": p.get("g") or 0, "a": p.get("a") or 0, "pts": p.get("pts") or 0, "sh": p.get("sh"),
             "pm": p.get("pm"), "pim": p.get("pim") or 0, "ppg": p.get("ppg"), "shg": p.get("shg"), "gwg": p.get("gwg")}
        adv = p.get("adv") or {}
        b = bx.get(pid)
        if b and b["gp_box"]:
            r["a1"] = b["a1"]
            r["a2"] = b["a2"]
            r["gp_box"] = b["gp_box"]
            if b["toi_n"]:
                r["toi_pg"] = round(b["toi"] / b["toi_n"] / 60.0, 2)
                r["toi_n"] = b["toi_n"]
            r["eng"] = b["eng"]
            r["ppa"] = b["ppa"]
        fw = adv.get("fow") if adv.get("fow") is not None else (b["fow"] if b else None)
        fl = adv.get("fol") if adv.get("fol") is not None else (b["fol"] if b else None)
        if fw is not None and fl is not None and (fw + fl) > 0:
            r["fow"], r["fol"] = int(fw), int(fl)
        if adv:
            r["tsa"] = adv.get("all_tsa")
            r["ev_tsa"] = adv.get("ev_tsa")
            r["pp_tsa"] = adv.get("pp_tsa")
            r["blk"] = adv.get("blk")
            r["sog"] = (adv.get("all_sv") or 0) + (adv.get("all_g") or 0) if adv.get("all_sv") is not None else None
            r["miss"] = adv.get("all_mi")
            r["blocked"] = adv.get("all_bl")
            r["ev_g"] = adv.get("ev_g")
            r["close_tsa"] = adv.get("close_tsa")
        r["_t"] = t
        r["bio"] = p.get("bio")
        rows[pid] = r
    for pid, p in (ch.get("goalies") or {}).items():
        gp = p.get("gp") or 0
        mins = p.get("min") or 0
        if gp <= 0 or mins <= 0:
            continue
        sv, ga = p.get("sv") or 0, p.get("ga") or 0
        r = {"id": pid, "name": p["name"], "team": p["team"], "pos": "G", "class": p.get("cls"), "gp": gp,
             "min": mins, "w": p.get("w"), "l": p.get("l"), "t": p.get("t"), "ga": ga, "sv": sv, "sa": sv + ga,
             "so": p.get("so"), "bio": p.get("bio"), "_t": teams.get(p["team"], {})}
        if pid in rows:                     # a goalie with a skater line (points): keep the goalie row
            r["g"], r["a"] = rows[pid].get("g"), rows[pid].get("a")
        rows[pid] = r
    _rates(rows)
    _value(rows)
    for r in rows.values():
        r.pop("_t", None)
    return rows


def _rates(rows: dict) -> None:
    for r in rows.values():
        gp = r["gp"]
        if r["pos"] == "G":
            sa = r.get("sa") or 0
            r["sv_pct"] = round(r["sv"] / sa, 4) if sa else None
            r["gaa"] = round(r["ga"] * 60.0 / r["min"], 3) if r.get("min") else None
            r["sa60"] = round(sa * 60.0 / r["min"], 2) if r.get("min") else None
            continue
        r["g_pg"] = round(r["g"] / gp, 3)
        r["a_pg"] = round(r["a"] / gp, 3)
        r["pts_pg"] = round(r["pts"] / gp, 3)
        if r.get("sh"):
            r["sh_pg"] = round(r["sh"] / gp, 3)
            r["sh_pct"] = round(r["g"] / r["sh"], 4) if r["sh"] > 0 else None
        r["pim_pg"] = round(r["pim"] / gp, 3)
        if r.get("ppg") is not None:
            r["ppg_pg"] = round((r["ppg"] or 0) / gp, 3)
        if r.get("a1") is not None and r.get("gp_box"):
            r["p1_pg"] = round((r["g"] / gp) + r["a1"] / r["gp_box"], 3)
            r["a1_share"] = round(r["a1"] / max(1, r["a1"] + r["a2"]), 3) if (r["a1"] + r["a2"]) else None
        if r.get("toi_pg"):
            m = r["toi_pg"]
            r["p60"] = round(r["pts_pg"] * 60.0 / m, 3) if m > 1 else None
            r["g60"] = round(r["g_pg"] * 60.0 / m, 3) if m > 1 else None
            if r.get("sh_pg") is not None:
                r["sh60"] = round(r["sh_pg"] * 60.0 / m, 3) if m > 1 else None
        if r.get("tsa") is not None:
            r["tsa_pg"] = round((r["tsa"] or 0) / gp, 3)
            r["ev_tsa_pg"] = round((r.get("ev_tsa") or 0) / gp, 3)
            if r.get("blk") is not None:
                r["blk_pg"] = round((r["blk"] or 0) / gp, 3)
            sog = r.get("sog")
            if sog and r.get("tsa"):
                r["on_net"] = round(sog / r["tsa"], 3)
        if r.get("fow") is not None:
            n = r["fow"] + r["fol"]
            r["fo_pct"] = round(r["fow"] / n, 4) if n else None
            r["fo_n"] = n
        t = r.get("_t") or {}
        if r.get("pm") is not None and t.get("gp"):
            gd_pg = (t["gf"] - t["ga"]) / t["gp"]
            r["pm_rel"] = round(r["pm"] - gd_pg * r["gp"] * 5.0 / 18.0, 2)
        if t.get("g"):
            r["pt_share"] = round((r["g"] + r["a"]) / max(1, t["g"]), 3)


def _value(rows: dict) -> None:
    sk = [r for r in rows.values() if r["pos"] != "G"]
    gk = [r for r in rows.values() if r["pos"] == "G"]
    # goals created
    for r in sk:
        t = r.get("_t") or {}
        den = (t.get("g") or 0) + 0.5 * (t.get("a") or 0)
        gf = t.get("gf") or t.get("g") or 0
        r["gc"] = (r["g"] + 0.5 * r["a"]) * gf / den if den else 0.0
    repl: dict[str, float] = {}
    pim_avg: dict[str, float] = {}
    for pos in ("F", "D"):
        reg = [r for r in sk if r["pos"] == pos and r["gp"] >= 10]
        if reg:
            repl[pos] = float(np.percentile([r["gc"] / r["gp"] for r in reg], 20))
            pim_avg[pos] = float(np.mean([r["pim"] / r["gp"] for r in reg]))
        else:
            repl[pos], pim_avg[pos] = 0.0, 0.0
    for r in sk:
        off = r["gc"] - repl[r["pos"]] * r["gp"]
        onice = PM_W * (r.get("pm_rel") or 0.0) * r["gp"] / (r["gp"] + PM_K)
        pen = -MINOR * ((r["pim"] / 2.0) - pim_avg[r["pos"]] / 2.0 * r["gp"])
        fo = FO_GOAL * ((r.get("fow") or 0) - (r.get("fol") or 0))
        gar = off + onice + pen + fo
        r["gar_off"] = round(off, 2)
        r["gar_onice"] = round(onice, 2)
        r["gar_pen"] = round(pen, 2)
        r["gar_fo"] = round(fo, 2)
        r["gar"] = round(gar, 2)
        r["gar_pg"] = round(gar / r["gp"], 3)
        r["war"] = round(gar / GPW, 2)
        r["gc"] = round(r["gc"], 2)
    sa_tot = sum(r.get("sa") or 0 for r in gk)
    lg = sum(r.get("sv") or 0 for r in gk) / sa_tot if sa_tot else 0.9
    for r in gk:
        sa = r.get("sa") or 0
        gsaa = ((r["sv"] / sa) - lg) * sa if sa else 0.0
        gsaa_s = gsaa * sa / (sa + G_K) if sa else 0.0
        repl_g = G_REPL * sa
        gar = gsaa_s + repl_g
        r["gsaa"] = round(gsaa, 2)
        r["gsaa_shrunk"] = round(gsaa_s, 2)
        r["sv_above"] = round((r["sv"] / sa - lg) if sa else 0.0, 4)
        r["gar"] = round(gar, 2)
        r["gar_pg"] = round(gar / r["gp"], 3) if r["gp"] else None
        r["war"] = round(gar / GPW, 2)
        r["lg_sv"] = round(lg, 4)


def why(r: dict) -> str:
    """A one-line reason for a player's value."""
    if r["pos"] == "G":
        if r.get("sv_pct") is None:
            return ""
        return (f"{r['sv_pct']:.3f} save percentage on {r.get('sa', 0)} shots, "
                f"{abs(r.get('gsaa', 0)):.1f} goals {'better' if (r.get('gsaa') or 0) >= 0 else 'worse'} than an average goalie")
    bits = [f"{r['g']} goal{'' if r['g'] == 1 else 's'}, {r['a']} assist{'' if r['a'] == 1 else 's'} in {r['gp']} game{'' if r['gp'] == 1 else 's'}"]
    if r.get("a1") is not None:
        bits.append(f"{r['a1']} primary assist{'' if r['a1'] == 1 else 's'}")
    if r.get("toi_pg"):
        bits.append(f"{r['toi_pg']:.1f} minutes a night")
    return ", ".join(bits)


def qualified(r: dict, max_gp: int) -> bool:
    """A regular: skaters with 40% of the season's most games (min 5); goalies with 25% of the team's minutes."""
    floor = max(5, int(0.4 * max_gp))
    if r["pos"] == "G":
        return (r.get("gp") or 0) >= max(3, int(0.25 * max_gp))
    return (r.get("gp") or 0) >= floor


def percentiles(rows: dict, keys_by_pos: dict[str, list[tuple[str, bool]]], max_gp: int) -> None:
    """pct (vs all qualified skaters / goalies) and pct_pos (within F / D / G) for each key; 100 = best."""
    for pos_group in (("F", "D"), ("F",), ("D",), ("G",)):
        sub = [r for r in rows.values() if r["pos"] in pos_group and qualified(r, max_gp)]
        if not sub:
            continue
        keys = keys_by_pos.get(pos_group[0] if len(pos_group) == 1 else "S") or []
        dest = "pct_pos" if len(pos_group) == 1 else "pct"
        for k, low in keys:
            vals = [(r[k], r["id"]) for r in sub if isinstance(r.get(k), (int, float))]
            if len(vals) < 5:
                continue
            arr = np.array([v for v, _ in vals], dtype=float)
            for v, pid in vals:
                p = (np.sum(arr < v) + 0.5 * np.sum(arr == v)) / len(arr)
                p = 1 - p if low else p
                rows[pid].setdefault(dest, {})[k] = int(round(100 * p))
