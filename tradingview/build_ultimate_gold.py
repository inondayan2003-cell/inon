"""Build the TradingView files (indicator + strategy) from each shared source.

    python tradingview/build_ultimate_gold.py

src/ultimate_gold.src.pine markers:
  //#IND <line>   -> line kept (uncommented) only in the indicator
  //#STR <line>   -> line kept only in the strategy
  //#BEGIN IND ... //#END   -> block kept only in the indicator
  //#BEGIN STR ... //#END   -> block kept only in the strategy
Everything else is shared, so both scripts run exactly the same logic.
"""
from pathlib import Path

HERE = Path(__file__).parent
SOURCES = {
    # 4H swing system (base version)
    HERE / "src" / "ultimate_gold.src.pine": {"IND": HERE / "Ultimate_Gold_Indicator.pine",
                                               "STR": HERE / "Ultimate_Gold_Strategy.pine"},
    # intraday multi-timeframe system (4H / 1H / 15M / 5M)
    HERE / "src" / "ultimate_gold_intraday.src.pine": {"IND": HERE / "Ultimate_Gold_Intraday_Indicator.pine",
                                                        "STR": HERE / "Ultimate_Gold_Intraday_Strategy.pine"},
}


def build(kind: str, text: str) -> str:
    out, block = [], None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("//#BEGIN "):
            block = s.split()[1]
            continue
        if s == "//#END":
            block = None
            continue
        if block is not None and block != kind:
            continue
        if s.startswith("//#IND ") or s.startswith("//#STR "):
            if s[3:6] == kind:
                out.append(s[7:])
            continue
        out.append(line)
    return "\n".join(out).rstrip() + "\n"


if __name__ == "__main__":
    for src, outs in SOURCES.items():
        text = src.read_text()
        for kind, path in outs.items():
            path.write_text(build(kind, text))
            print("wrote", path)
