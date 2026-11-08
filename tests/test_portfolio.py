import pandas as pd

from app import portfolio
from app.storage import Store


def trade(i, r, status, entry=4000.0, sl=3985.0, closed="2026-11-09T12:00:00+00:00"):
    return {"id": i, "direction": 1, "opened_at": "2026-11-09T07:20:00+00:00", "closed_at": closed,
            "entry": entry, "sl": sl, "exit_price": entry, "status": status, "result_r": r, "method": "channel_fade"}


def test_sizing_pnl_and_balance(tmp_path):
    store = Store(str(tmp_path / "p.db"))
    portfolio.reset(store, 10_000, 1)
    row = portfolio.record(store, trade(1, -1.0, "sl"))
    # סיכון 100$ על סטופ של 15$ -> 6.67 אונקיות -> 0.07 לוט (7 אונקיות)
    assert row["lots"] == 0.07 and row["pnl"] == round(-1.0 * 15 * 7 - 0.35 * 7, 2)
    assert portfolio.get(store)["balance"] == round(10_000 + row["pnl"], 2)
    assert portfolio.record(store, trade(1, -1.0, "sl")) is None          # אותה עסקה לא נרשמת פעמיים
    row2 = portfolio.record(store, trade(2, 1 / 3, "be"))
    assert row2["pnl"] > 0 and len(portfolio.get(store)["ledger"]) == 2


def test_report_today_and_totals(tmp_path):
    store = Store(str(tmp_path / "p.db"))
    portfolio.reset(store, 5_000, 2)
    portfolio.record(store, trade(1, 0.67, "tp2"))
    portfolio.record(store, trade(2, -1.0, "sl", closed="2026-11-08T12:00:00+00:00"))
    text = portfolio.report(store, "2026-11-09", open_trades=[{"id": 3, "direction": -1, "entry": 4010.0, "sl": 4025.0}])
    assert "עסקאות שנסגרו היום (1)" in text and "#1 BUY" in text and "#2" not in text.split("יתרה")[0]
    assert "פתוחה: #3 SELL" in text and "5,000$" in text and "2 עסקאות" in text
    assert "לא נסגרו עסקאות היום" in portfolio.report(store, "2026-11-10")


def test_replay_all_closed_trades(tmp_path):
    store = Store(str(tmp_path / "p.db"))
    store.save_trade(trade(2, -1.0, "sl", closed="2026-11-09T15:00:00+00:00"))
    store.save_trade(trade(1, 0.67, "tp2", closed="2026-11-09T09:00:00+00:00"))
    store.save_trade({"id": 3, "method": "channel_fade", "direction": 1, "opened_at": "x", "entry": 4000.0, "sl": 3985.0})
    portfolio.record(store, trade(9, 5.0, "tp2"))   # תיק ישן נמחק
    p = portfolio.replay(store, 10_000, 1)
    assert [x["id"] for x in p["ledger"]] == [1, 2] and p["start"] == 10_000
    assert p["balance"] == round(10_000 + sum(x["pnl"] for x in p["ledger"]), 2)
    assert "כל העסקאות (2)" in portfolio.history(store)
