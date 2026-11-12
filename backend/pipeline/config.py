"""Global configuration for the TBO inventory optimization pipeline."""
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
ART_DIR = ROOT / "artifacts"

SEED = 42

# Planning clock: "today" is the day the planner runs the system.
TODAY = pd.Timestamp("2026-11-10")
HIST_START = pd.Timestamp("2024-01-01")
HIST_END = TODAY - pd.Timedelta(days=1)          # last day with observed data
HORIZON_START = pd.Timestamp("2026-11-16")       # next Monday
HORIZON_WEEKS = 13                                # ~ one quarter of travel weeks
HORIZON_END = HORIZON_START + pd.Timedelta(weeks=HORIZON_WEEKS) - pd.Timedelta(days=1)

# Search-signal lag window (days before the travel date). Must exceed the
# longest forecast horizon so the feature is always known at planning time.
SEARCH_LAG_MIN, SEARCH_LAG_MAX = 105, 135

QUANTILES = (0.1, 0.5, 0.9)
N_SCENARIOS = 1000          # Monte Carlo scenarios per candidate
N_BLOCKS = 10               # quantity blocks per candidate for the MILP
PRICE_GRID = (0.90, 0.95, 1.00, 1.05, 1.10, 1.15, 1.20)  # multipliers on market price (rate-parity guardrail: max +20%)
LEAD_OPTIONS = (120, 90, 60, 45, 30, 21, 14, 7)  # pre-buy lead times (days)
CVAR_ALPHA = 0.10           # tail used for block-level risk scores
# Elasticity measured from history is *market-level*. When TBO prices its own pre-bought
# stock above/below the market, agents switch wholesalers, so TBO's own demand reacts
# more strongly. Effective elasticity = market elasticity + this premium.
COMPETITIVE_ELASTICITY = 5.0
