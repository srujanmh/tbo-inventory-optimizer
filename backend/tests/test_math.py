"""Run:  cd backend && python -m pytest -q tests
Verifies the optimizer's numbers independently and checks what-if behaviour."""
import json
import pickle

import numpy as np
import pytest

from pipeline.config import ART_DIR
from pipeline.optimizer import Optimizer
from pipeline import verify, whatif

C = pickle.load(open(ART_DIR / "candidates.pkl", "rb"))
S = json.loads((ART_DIR / "summary.json").read_text())
SER = pickle.load(open(ART_DIR / "series.pkl", "rb"))
OPT = Optimizer(C["cands"], C["blocks"])


@pytest.mark.parametrize("budget,lam,share", [(75e7, 0.3, 0.3), (25e7, 0.0, 0.3), (150e7, 0.8, 0.2), (75e7, 0.5, 0.15)])
def test_plan_numbers_verified(budget, lam, share):
    res = OPT.solve(budget, lam=lam, max_dest_share=share)
    out = verify.run_all(OPT, res, budget, lam, max(share, 0.1), S["forecast_backtest"]["table"], SER["validation"])
    failed = [c for c in out["checks"] if not c["passed"]]
    assert not failed, failed


def test_no_shock_reproduces_base_plan():
    base = OPT.solve(75e7, lam=0.3, max_dest_share=0.3)
    rp = whatif.replan(C["cands"], C["blocks"], base["plan"], [], dict(budget=75e7, lam=0.3, max_dest_share=0.3))
    assert rp["result"]["stats"]["expected_profit"] == base["stats"]["expected_profit"]
    assert rp["keep_plan"]["expected_profit"] == pytest.approx(base["stats"]["expected_profit"], rel=1e-4)  # z stored as float32
    assert rp["diff"]["n_changes"] == 0


def test_whatif_directions():
    kw = dict(budget=75e7, lam=0.3, max_dest_share=0.3)
    base = OPT.solve(**kw)
    p0 = base["stats"]["expected_profit"]
    up = whatif.replan(C["cands"], C["blocks"], base["plan"], [dict(kind="demand", change=0.15)], kw)
    down = whatif.replan(C["cands"], C["blocks"], base["plan"], [dict(kind="demand", change=-0.15)], kw)
    cost = whatif.replan(C["cands"], C["blocks"], base["plan"], [dict(kind="supplier_cost", change=0.10)], kw)
    canc = whatif.replan(C["cands"], C["blocks"], base["plan"], [dict(kind="cancellation", change=0.5)], kw)
    assert up["result"]["stats"]["expected_profit"] > p0 > down["result"]["stats"]["expected_profit"]
    assert cost["result"]["stats"]["expected_profit"] < p0
    assert canc["result"]["stats"]["expected_profit"] < p0
    # re-optimising can never be worse than keeping the old plan (up to solver tolerance)
    for r in (up, down, cost, canc):
        assert r["result"]["stats"]["expected_profit"] >= r["keep_plan"]["expected_profit"] * 0.995 or r["keep_plan"]["invested"] > 75e7


def test_unused_budget_explained():
    res = OPT.solve(150e7, lam=0.3, max_dest_share=0.3)
    u = res["unused_budget"]
    assert u["unused"] == pytest.approx(150e7 - res["stats"]["invested"], abs=1)
    assert u["unused"] > 0 and len(u["summary"]) > 20
    res = OPT.solve(75e7, lam=0.3, max_dest_share=0.3, destinations=["Goa"])
    assert any(r["code"] == "filtered" for r in res["unused_budget"]["reasons"])


def test_metric_definitions():
    t = S["forecast_backtest"]["table"]
    assert t["weekly_model"]["accuracy"] == pytest.approx(1 - S["forecast_backtest"]["weekly_wape"], abs=1e-4)
    assert t["weekly_model"]["wape"] < t["weekly_naive"]["wape"]
    y = np.array([r["y"] for r in SER["validation"]])
    p = np.array([r["median"] for r in SER["validation"]])
    assert np.sqrt(((p - y) ** 2).mean()) == pytest.approx(t["weekly_model"]["rmse"], abs=0.05)
