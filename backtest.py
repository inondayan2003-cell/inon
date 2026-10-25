"""בדיקה היסטורית מהמחשב:  python backtest.py [חודשים]   (עם TWELVEDATA_API_KEY בסביבה)"""
import re
import sys

from app.backtest import backtest_report
from app.config import load_settings

if __name__ == "__main__":
    months = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    print(re.sub(r"</?[bi]>", "", backtest_report(load_settings(), months)))
