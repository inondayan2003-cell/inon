"""הורדת נרות דקה של XAU/USD מ-HistData.com (ארכיון חינמי) עם מטמון מקומי.

כל שנה שהסתיימה = קובץ אחד; השנה הנוכחית = קובץ לכל חודש.
הזמנים בקבצים הם שעון ניו יורק כולל שעון קיץ (נבדק: הפתיחה היומית יוצאת 18:00 גם בינואר וגם ביולי).
"""
import datetime as dt
import io
import re
import time
import zipfile
from pathlib import Path

import httpx
import pandas as pd

BASE = "https://www.histdata.com"
PAGE = BASE + "/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes/{pair}/{period}"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36"}


def _form(html: str) -> dict:
    """שדות הטופס הנסתרים (tk, date, datemonth, platform, timeframe, fxpair) מתוך דף ההורדה."""
    form = re.search(r'<form[^>]*id="file_down"[^>]*>(.*?)</form>', html, re.S | re.I)
    body = form.group(1) if form else html
    fields = {}
    for tag in re.findall(r"<input[^>]+>", body, re.I):
        name = re.search(r'name="([^"]+)"', tag)
        value = re.search(r'value="([^"]*)"', tag)
        if name:
            fields[name.group(1)] = value.group(1) if value else ""
    return fields


def parse_csv(raw: bytes) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(raw), sep=";", header=None, names=["ts", "open", "high", "low", "close", "volume"])
    idx = pd.DatetimeIndex(pd.to_datetime(df.pop("ts"), format="%Y%m%d %H%M%S"))
    df.index = idx.tz_localize("America/New_York", ambiguous="NaT", nonexistent="shift_forward").tz_convert("UTC")
    df = df[df.index.notna()]
    return df[~df.index.duplicated()].sort_index().astype(float)


def _download(client: httpx.Client, pair: str, period: str) -> pd.DataFrame | None:
    url = PAGE.format(pair=pair.lower(), period=period)
    for attempt in range(4):
        try:
            page = client.get(url, headers=UA, timeout=60)
            fields = _form(page.text)
            if "tk" not in fields:
                return None  # אין קובץ לתקופה הזאת
            r = client.post(BASE + "/get.php", data=fields, headers={**UA, "Referer": url}, timeout=180)
            r.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
                return parse_csv(z.read(name))
        except (httpx.HTTPError, zipfile.BadZipFile, StopIteration):
            if attempt == 3:
                raise
            time.sleep(3 * (attempt + 1))


def fetch_minutes(start: dt.date, end: dt.date, cache: Path, pair: str = "XAUUSD") -> pd.DataFrame:
    cache.mkdir(parents=True, exist_ok=True)
    today = dt.date.today()
    periods = []
    for y in range(start.year, end.year + 1):
        if y < today.year:
            periods.append(str(y))
        else:
            periods += [f"{y}/{m}" for m in range(1, 13) if dt.date(y, m, 1) <= end]
    frames = []
    with httpx.Client(follow_redirects=True) as client:
        for p in periods:
            f = cache / f"hd2_{pair}_{p.replace('/', '-')}.parquet"
            done = not ("/" in p and int(p.split("/")[1]) >= today.month and int(p.split("/")[0]) == today.year)
            if f.exists() and done:
                frames.append(pd.read_parquet(f))
                continue
            df = _download(client, pair, p)
            if df is None or df.empty:
                print(f"  {p}: אין נתונים", flush=True)
                continue
            df.to_parquet(f)
            frames.append(df)
            print(f"  {p}: {len(df):,} דקות", flush=True)
    out = pd.concat(frames).sort_index()
    out = out[~out.index.duplicated(keep="last")]
    return out[(out.index.date >= start) & (out.index.date <= end)]
