# Silent pitch: on-screen captions only. (scene id, captions separated by |, visual)
SCENES = [
 ("s1", "Team Void presents TBO Inventory Intelligence | An AI system that tells TBO what travel inventory to pre-buy, how much, when and at what price | Every figure in this video comes from a synthetic dataset: simulated results, not actual TBO profit", "slide:cover"),
 ("s2", "Pre-buying is a bet under uncertainty | On 27% of days inventory sells out, so bookings hide real demand | 585 hotel-weeks and route-weeks compete for one budget | Unsold stock is only partly refundable, and bookings cancel", "slide:problem"),
 ("s3", "Five steps: recover hidden demand, forecast with uncertainty | predict prices, cancellations and supplier costs | simulate 1,000 futures | then a MILP optimizer splits the budget for the best risk-adjusted profit", "slide:pipeline"),
 ("s4", "The Budget Optimizer, with a ₹75 Cr budget | Expected profit ₹13.5 Cr: +28.5% vs last year's mix (forecast) | ₹7.6 Cr saved by buying at the right lead time", "live:optimizer"),
 ("s5", "Raise the budget to ₹200 Cr | The optimizer stops spending when no unit adds risk-adjusted profit | and explains why the rest of the budget stays uninvested", "live:budget"),
 ("s6", "Every position explains itself | quantity, buy-by date, selling price, cancellation risk | and a side-by-side comparison of the suppliers that could fill it", "live:explain"),
 ("s7", "What-if simulation: change demand, prices, supplier costs, availability or cancellations | The plan re-optimises and shows exactly what changes, and what re-planning is worth", "live:whatif"),
 ("s8", "Automated re-planning: market signals stream in | The system re-optimises after each one and switches plans only when it pays", "live:feed"),
 ("s9", "Supplier intelligence: 6 suppliers scored on price, availability, reliability, refunds and lead time | The cheapest quote does not always win", "live:suppliers"),
 ("s10", "Accuracy, measured one way everywhere: 1 − weekly WAPE on 13 unseen weeks | 87.5% accurate (naive 81.3%), with MAE, RMSE and WAPE for every model | Back-test from 11 Aug: ₹11.74 Cr realised profit, within 3% of prediction, +61% vs last year's mix | 24 independent maths checks verify every plan", "live:accuracy"),
 ("s11", "Ready for real data: a data contract, a file checker and one command to retrain | Live demo: tbo-inventory-optimizer-sggo.vercel.app | Code: github.com/srujanmh/tbo-inventory-optimizer", "live:data"),
 ("s12", "TBO Inventory Intelligence · Team Void | The right inventory, at the right time, within the right budget", "slide:end"),
]
def chunk_dur(c): return max(2.8, len(c) / 13.0 + 1.0)
def durs():
    return {sid: round(sum(chunk_dur(c.strip()) for c in cap.split('|')), 2) for sid, cap, _ in SCENES}
if __name__ == '__main__':
    d = durs(); print(d, round(sum(d.values()) + len(d), 1))
