"""בדיקת ערוץ סיגנלים ציבורי בטלגרם: קוראים את כל ההודעות מ-t.me/s/<ערוץ>, מפענחים סיגנלים,
ובודקים כל אחד מול נרות דקה אמיתיים של XAU/USD (HistData). עונה גם על "למה בשעה הזאת".
"""
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

from app.signals import channel_signals, evaluate, fetch_channel
from research import histdata


def report(name: str, cache: Path, hours: float = 24, cost: float = 0.35) -> str:
    msgs = fetch_channel(name, max_pages=200)
    sigs = channel_signals(msgs)
    lines = [f"### 📡 ערוץ {name}: {len(msgs)} הודעות, {len(sigs)} סיגנלי זהב מפוענחים"]
    if not msgs:
        return "\n".join(lines + ["לא הצלחתי לקרוא הודעות (אולי התצוגה הציבורית סגורה)."])
    lines.append(f"טווח: {msgs[0]['t'][:10]} עד {msgs[-1]['t'][:10]}")
    if not sigs:
        sample = [m["text"][:120].replace("\n", " | ") for m in msgs[-8:]]
        return "\n".join(lines + ["", "דוגמאות להודעות (לא זוהו כסיגנל):"] + [f"- {x}" for x in sample])
    t0 = pd.Timestamp(sigs[0]["t"]).date() - dt.timedelta(days=1)
    m1 = histdata.fetch_minutes(t0, dt.date.today(), cache)
    data_end = m1.index[-1]
    rows = []
    for s in sigs:
        t = pd.Timestamp(s["t"])
        if t + pd.Timedelta(hours=hours) > data_end:
            rows.append((s, None))
            continue
        bars = m1[(m1.index >= t) & (m1.index < t + pd.Timedelta(hours=hours))]
        r = evaluate(s, bars, hours)
        if r.get("filled"):
            r["r_cost"] = r["r_split"] - cost / r["risk"]
        rows.append((s, r))
    done = [(s, r) for s, r in rows if r and r.get("filled")]
    nofill = sum(1 for s, r in rows if r and not r.get("filled"))
    pend = sum(1 for s, r in rows if r is None)
    lines += [f"נבדקו מול נתוני דקה עד {data_end:%Y-%m-%d}: {len(done)} התמלאו, {nofill} לא התמלאו, {pend} אחרי סוף הנתונים", ""]
    if done:
        R = np.array([r["r_split"] for _, r in done])
        RB = np.array([r["r_be"] for _, r in done])
        RC = np.array([r["r_cost"] for _, r in done])
        tp1 = np.mean([r["tp_hits"] > 0 for _, r in done])
        allt = np.mean([r["tp_hits"] == len(s["tps"]) for s, r in done])
        sl = np.mean([r["stopped"] for _, r in done])
        rr1 = np.mean([r["rr"][0] for _, r in done])
        rrl = np.mean([r["rr"][-1] for _, r in done])
        risk = np.mean([r["risk"] for _, r in done])
        t = R.mean() / R.std(ddof=1) * np.sqrt(len(R)) if len(R) > 2 else 0
        lines += ["| מדד | ערך |", "|---|---|",
                  f"| TP1 הושג | **{100 * tp1:.0f}%** |", f"| כל היעדים הושגו | {100 * allt:.0f}% |",
                  f"| הסטופ נלקח | **{100 * sl:.0f}%** |",
                  f"| יחס ממוצע TP1 / יעד אחרון (מהכניסה) | 1:{rr1:.2f} / 1:{rrl:.2f} |",
                  f"| סטופ ממוצע | {risk:.1f}$ |",
                  f"| סך הכל, חלוקה שווה בין היעדים | **{R.sum():+.1f}R** (ממוצע {R.mean():+.3f}, t {t:+.1f}) |",
                  f"| עם עמלה 0.35$ | {RC.sum():+.1f}R |",
                  f"| עם סטופ לכניסה אחרי TP1 | {RB.sum():+.1f}R |",
                  f"| רק TP1 (סוגרים הכל ביעד הראשון) | {sum(r['r_tp1_only'] for _, r in done):+.1f}R |", ""]
        df = pd.DataFrame([{"t": pd.Timestamp(s["t"]), "d": s["direction"], "r": r["r_split"]} for s, r in done])
        il = df.t.dt.tz_convert("Asia/Jerusalem")
        ny = df.t.dt.tz_convert("America/New_York")
        lines.append("**לפי שעה (שעון ישראל):** " + " · ".join(
            f"{h:02d}: {len(g)} עסק' {g.r.sum():+.1f}R" for h, g in df.groupby(il.dt.hour)))
        lines.append("**לפי שעה (ניו יורק):** " + " · ".join(
            f"{h:02d}: {len(g)}" for h, g in df.groupby(ny.dt.hour)))
        lines.append(f"**לונג/שורט:** {(df.d == 1).sum()} קניות {df[df.d == 1].r.sum():+.1f}R · "
                     f"{(df.d == -1).sum()} מכירות {df[df.d == -1].r.sum():+.1f}R")
        by_m = df.groupby(df.t.dt.strftime("%Y-%m"))["r"].agg(["count", "sum"])
        lines.append("**לפי חודש:** " + " · ".join(f"{m}: {int(r['count'])} {r['sum']:+.1f}R" for m, r in by_m.iterrows()))
        lines += ["", "**20 האחרונים:**"]
        for s, r in done[-20:]:
            w = pd.Timestamp(s["t"]).tz_convert("Asia/Jerusalem").strftime("%d/%m %H:%M")
            lines.append(f"- {w} {'קנייה' if s['direction'] == 1 else 'מכירה'} {s['zone_lo']:g}-{s['zone_hi']:g} SL {s['sl']:g} "
                         f"→ TP {r['tp_hits']}/{len(s['tps'])}{' · סטופ' if r['stopped'] else ''} · {r['r_split']:+.2f}R")
    return "\n".join(lines)
