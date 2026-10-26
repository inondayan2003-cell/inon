"""סבב 4: מבחן על היסטוריה שאף חיפוש לא ראה (2018 עד תחילת חלון השנתיים).

כל המועמדים נבחרו על השנתיים האחרונות. כאן הם רצים כמו שהם, בלי שום כוונון, על השנים שלפני.
שיטה שמרוויחה גם כאן, בכל שנה או ברובן, ומעל הביקורת - היא כנראה אמיתית.
"""
import numpy as np
import pandas as pd

from app.indicators import atr as wilder_atr
from research import loop, loop2, loop3
from research.loop import _s


def _fixed(m1: pd.DataFrame, cost: float) -> dict:
    from app.data import resample
    h1, h2 = resample(m1, "1h"), resample(m1, "2h")
    a1 = wilder_atr(h1, 14).to_numpy()
    out = {
        "פתיחת אסיה: לונג 18:00 NY · 1:2": loop3.run_hours(h1, a1, {18: 1}, 2.0, 4, cost),
        "פתיחת אסיה: לונג 18:00 NY · 1:3": loop3.run_hours(h1, a1, {18: 1}, 3.0, 4, cost),
        "שורט 22:00 NY · 1:3": loop3.run_hours(h1, a1, {22: -1}, 3.0, 12, cost),
        "FVG 2H נגד מגמה (סבב 1 #1)": loop.run(h2, cost, entry_frac=1.0, stop="atr", rr=3.0, win=12, filt="anti", tf_min=120),
        "FVG 2H נגד מגמה c1 (סבב 1 #7)": loop.run(h2, cost, entry_frac=1.0, stop="c1", rr=3.0, win=24, filt="anti", tf_min=120),
        "FVG 1H לימיט באמצע · 1:3 (הקוד שלך)": loop.run(h1, cost, entry_frac=0.5, stop="mid", rr=3.0, win=12, tf_min=60),
        "פריצת 20 נרות 1H (סבב 2 #3)": loop2.simulate(h1, loop2.signals(h1, "donch", {"N": 20, "mode": 1}), a1, 2.0, 12, cost),
    }
    return out


def _london(m1: pd.DataFrame, cost: float) -> pd.DataFrame:
    from app.config import Settings
    from research.run import build, simulate
    from research.strategies import candidates
    rows = build(m1).to_dict("records")
    tr = simulate(rows, candidates(Settings())["london_short"])
    return pd.DataFrame({"t": [pd.Timestamp(t["opened_at"]) for t in tr],
                         "dir": [int(t["direction"]) for t in tr],
                         "r": [t["result_r"] - cost / abs(t["entry"] - t["sl"]) for t in tr]})


def report(m1: pd.DataFrame, cost: float, london: bool = True) -> str:
    from research.null import shuffle_within_day
    years = sorted(set(m1.index.year))
    real = _fixed(m1, cost)
    null = _fixed(shuffle_within_day(m1, 7), cost)
    if london:
        try:
            real["🇬🇧 שורט לונדון (הבוט)"] = _london(m1, cost)
            null["🇬🇧 שורט לונדון (הבוט)"] = _london(shuffle_within_day(m1, 7), cost)
        except Exception as e:  # noqa: BLE001
            print("london failed:", e, flush=True)
    lines = [f"### 🧪 סבב 4: מבחן על {m1.index[0]:%Y-%m} עד {m1.index[-1]:%Y-%m} (נתונים שלא נראו) · עלות {cost}$", "",
             "| שיטה | עסקאות/יום | הצלחה | R | t | " + " | ".join(str(y) for y in years) + " | שנים ברווח | ביקורת R | לונג/שורט |",
             "|" + "---|" * (8 + len(years))]
    days = m1.index.normalize().nunique()
    for name, tr in real.items():
        s = _s(tr)
        if not s["n"]:
            lines.append(f"| {name} | 0 |")
            continue
        per_y = [tr[tr.t.dt.year == y]["r"].sum() for y in years]
        pos = sum(x > 0 for x in per_y)
        lo, sh = tr[tr.dir == 1]["r"].sum(), tr[tr.dir == -1]["r"].sum()
        lines.append(f"| {name} | {s['n'] / days:.2f} | {s['win']:.0f}% | {s['sum']:+.0f} | {s['t']:+.1f} | "
                     + " | ".join(f"{x:+.0f}" for x in per_y)
                     + f" | {pos}/{len(years)} | {_s(null[name])['sum']:+.0f} | {lo:+.0f}/{sh:+.0f} |")
    from app.data import resample
    h1 = resample(m1, "1h")
    a = wilder_atr(h1, 14).to_numpy()
    ret = (h1["close"] - h1["open"]).to_numpy() / a
    hr = h1.index.tz_convert(loop3.NY).hour
    yr = h1.index.year
    lines += ["", "**פרופיל שעות (t של התנועה הממוצעת בשעה, לכל שנה):**", "",
              "| שעה NY | ישראל | " + " | ".join(str(y) for y in years) + " | הכל |", "|" + "---|" * (3 + len(years))]
    for h in range(24):
        cells = []
        for y in years + [None]:
            m = (hr == h) & ~np.isnan(ret) & ((yr == y) if y else True)
            x = ret[m]
            cells.append(f"{x.mean() / x.std(ddof=1) * np.sqrt(len(x)):+.1f}" if len(x) > 20 else "")
        lines.append(f"| {h:02d} | {(h + 7) % 24:02d} | " + " | ".join(cells) + " |")
    return "\n".join(lines)
