import asyncio

import numpy as np
import pandas as pd

from app.signals import evaluate, parse_signal

MSG = """Gold buy @ 4003 - 3995
Sl @ 3988
Tp1 @ 4006
Tp2 @ 4008
Tp3 @ 4011
Tp4 @ 4015

Enter slowly in the zones don't over leverage ✅"""


def bars(path):
    idx = pd.date_range("2026-10-27 06:22", periods=len(path), freq="1min", tz="UTC")
    p = np.array(path, float)
    return pd.DataFrame({"open": p, "high": p + 0.5, "low": p - 0.5, "close": p}, index=idx)


def test_parse_group_message():
    s = parse_signal(MSG)
    assert s == {"direction": 1, "zone_hi": 4003.0, "zone_lo": 3995.0, "sl": 3988.0, "tps": [4006.0, 4008.0, 4011.0, 4015.0]}
    sell = parse_signal("XAUUSD SELL NOW 4020/4025\nSL 4032\nTP 4015\nTP 4010")
    assert sell["direction"] == -1 and sell["zone_lo"] == 4020 and sell["sl"] == 4032 and sell["tps"] == [4015, 4010]
    assert parse_signal("gold looks bullish today") is None
    assert parse_signal("Gold buy @ 4003\nSl @ 4010\nTp1 @ 4006") is None   # סטופ בצד הלא נכון


def test_evaluate_tp1_then_stop():
    s = parse_signal(MSG)
    r = evaluate(s, bars([4005, 4003, 4004, 4006.5, 4002, 3995, 3987]))
    assert r["filled"] and r["entry"] == 4003 and r["tp_hits"] == 1 and r["stopped"]
    # TP1 = +3 מתוך סיכון 15 = 0.2R; שלושה חלקים בסטופ
    assert r["r_split"] == round((0.2 - 3) / 4, 2)
    assert r["r_be"] == round(0.2 / 4, 2)          # עם סטופ לכניסה אחרי TP1


def test_evaluate_all_targets_and_no_fill():
    s = parse_signal(MSG)
    r = evaluate(s, bars([4004, 4002.5, 4007, 4009, 4012, 4016]))
    assert r["tp_hits"] == 4 and not r["stopped"] and r["r_split"] > 0
    assert evaluate(s, bars([4010, 4012, 4015]))["filled"] is False


def test_bot_saves_forwarded_signal(tmp_path):
    from app.bot import Bot
    from app.config import Settings
    from app.storage import Store
    store = Store(str(tmp_path / "s.db"))
    bot = Bot(Settings(bot_token="x"), store, lambda: None)
    sent = []

    async def fake_send(chat_id, text, with_button=False):
        sent.append(text)

    bot.send = fake_send
    msg = {"chat": {"id": 1}, "from": {"id": 5}, "text": MSG, "date": 1793000000,
           "forward_origin": {"type": "channel", "date": 1792995720}}
    asyncio.run(bot.handle(msg))
    saved = store.get("group_signals")
    assert len(saved) == 1 and saved[0]["forwarded"] and saved[0]["sl"] == 3988
    assert saved[0]["t"] == pd.Timestamp(1792995720, unit="s", tz="UTC").isoformat()
    asyncio.run(bot.handle(msg))
    assert len(store.get("group_signals")) == 1 and "כבר שמור" in sent[-1]


def test_parse_channel_page():
    from app.signals import channel_signals, parse_channel_page
    page = ('<div class="tgme_widget_message_wrap js-widget_message_wrap"><div class="tgme_widget_message" data-post="Cryptonew84/812">'
            '<div class="tgme_widget_message_text js-message_text" dir="auto">Gold buy @ 4003 - 3995<br/>Sl @ 3988<br/>'
            'Tp1 @ 4006<br/>Tp2 @ 4008</div><a class="tgme_widget_message_date"><time datetime="2026-10-27T06:22:10+00:00" '
            'class="time">08:22</time></a></div></div>'
            '<div class="tgme_widget_message_wrap"><div class="tgme_widget_message" data-post="Cryptonew84/813">'
            '<div class="tgme_widget_message_text js-message_text" dir="auto">TP1 hit &#9989;</div>'
            '<time datetime="2026-10-27T07:00:00+00:00">09:00</time></div></div>')
    msgs = parse_channel_page(page)
    assert [m["id"] for m in msgs] == [812, 813] and msgs[0]["t"].startswith("2026-10-27T06:22:10")
    sigs = channel_signals(msgs)
    assert len(sigs) == 1 and sigs[0]["sl"] == 3988 and sigs[0]["tps"] == [4006, 4008]
