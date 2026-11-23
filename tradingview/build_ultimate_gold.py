"""Build the two TradingView files from the single shared source.

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
SRC = HERE / "src" / "ultimate_gold.src.pine"
OUT = {"IND": HERE / "Ultimate_Gold_Indicator.pine", "STR": HERE / "Ultimate_Gold_Strategy.pine"}


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
    text = SRC.read_text()
    for kind, path in OUT.items():
        path.write_text(build(kind, text))
        print("wrote", path)
