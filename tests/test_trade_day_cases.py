"""The launcher's copies of the trade-day rule agree with the one table of cases (team review, 20 Nov 2026, architect
9): `task_runner.claim_day` with the IBKR cycle's claim_day (the run's rule) and `reminder.decision_date` (Start of
Day's). The table is IBKR's reference/trade_day_cases.json; tests/trade_day_cases.json is this repo's copy, for CI and
for a checkout without IBKR beside it, and must equal IBKR's whenever IBKR's is there.
Run from the launcher folder: .venv\\Scripts\\python.exe -m unittest discover tests"""
import json
import os
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import reminder
from config import MARCO_DIR, TaskConfig
from task_runner import claim_day

COPY = Path(__file__).resolve().parent / "trade_day_cases.json"
IBKRS = Path(os.environ.get("TRADE_DAY_CASES") or MARCO_DIR.parent / "IBKR" / "reference" / "trade_day_cases.json")
TABLE = json.loads((IBKRS if IBKRS.is_file() else COPY).read_text(encoding="utf-8"))
SYDNEY = ZoneInfo("Australia/Sydney")
PAPER = TaskConfig(id="ibkr-paper-cycle", label="IBKR paper cycle", cwd=".", cmd=["x"], claim="daily",
                   claim_day="18:00 America/New_York", timezone="Australia/Sydney")


def _now(case: dict) -> datetime:
    return datetime.fromisoformat(case["now"].replace("Z", "+00:00"))


class TradeDayCases(unittest.TestCase):
    def test_the_table(self):
        self.assertEqual(TABLE["schema"], "trade_day_cases/1")
        self.assertGreaterEqual(len(TABLE["cases"]), 20)

    def test_the_claim_day_is_the_runs_trade_day(self):
        for case in TABLE["cases"]:
            with self.subTest(case["sydney"]):
                self.assertEqual(claim_day(PAPER, _now(case)), case["run"]["trade_day"], case["why"])

    def test_the_reminders_decision_date_is_start_of_days(self):
        for case in TABLE["cases"]:
            with self.subTest(case["sydney"]):
                today = _now(case).astimezone(SYDNEY).date()
                self.assertEqual(reminder.decision_date(today), date.fromisoformat(case["sod"]["decision_date"]),
                                 case["why"])

    @unittest.skipUnless(IBKRS.is_file(), "IBKR's checkout is not beside this one")
    def test_this_repos_copy_is_ibkrs(self):
        self.assertEqual(json.loads(COPY.read_text(encoding="utf-8")), json.loads(IBKRS.read_text(encoding="utf-8")),
                         f"copy {IBKRS} over {COPY}")


if __name__ == "__main__":
    unittest.main()
