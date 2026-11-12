# TBO Inventory Intelligence — speaker notes (Team Void)

## Slide 1 · cover

Hi, we are Team Void. Our prototype, TBO Inventory Intelligence, answers the challenge's core question: given a maximum budget, what travel inventory should TBO pre-buy, how much, when, and at what selling price. Three numbers to remember: 87.5% weekly forecast accuracy, plus 61% realised profit versus copying last year's mix in a back-test, and it re-plans any budget in under a second.

## Slide 2 · problem

TBO can pre-buy hotel allotments and group flight seats cheaper than spot rates, and secure availability when the market sells out. But three things make it hard. First, sold-outs hide demand: on 27% of days the item was sold out, so bookings understate real demand by 36%. Second, every rupee competes: 585 item-weeks fight over one budget. Third, unsold stock is a loss: only 15 to 60% comes back if it doesn't sell, and bookings cancel.

## Slide 3 · solution

Here's the product in one line: one budget in, a ranked buy plan out. TBO sets the maximum budget, how much risk it's willing to take, a cap per destination, and which inventory types and destinations to consider. For every position, the platform returns what to buy, how many units, the buy-by date, the selling price, the expected and worst-case profit, and the reasons why.

## Slide 4 · pipeline

Under the hood there are five steps. One, recover true demand on sold-out days from search data. Two, forecast demand with uncertainty ranges. Three, model selling prices, price sensitivity, cancellations and supplier rates by lead time. Four, simulate a thousand possible futures with shared market and destination shocks. Five, an optimizer allocates the budget to maximise expected profit while protecting the downside.

## Slide 5 · models

These are the nine models and techniques. Gradient-boosted quantile models forecast demand with uncertainty. Separate models handle market prices, price sensitivity, cancellations and supplier rates by lead time. Monte Carlo simulation produces the risk picture, a newsvendor model sets per-item quantities, and a mixed-integer program allocates the budget. SHAP and the Claude API explain each decision.

## Slide 6 · alignment

This slide maps the brief's five key objectives to what we built, with evidence for each. Predict demand: 87.5% weekly accuracy. Identify opportunities: 532 profitable item-weeks scored and ranked. Optimize investments: 28.5% more expected profit than last year's mix. Maximize profitability: 7.6 crore saved by buying at the right time. Manage risk: in the back-test only 3 of 495 positions lost money. And the expected outcome, a decision-support platform with a maximum budget as input, is exactly what the prototype is.

## Slide 7 · accuracy

Every model was scored on the last three months of data, which it never saw in training. Weekly demand forecasts are 87.5% accurate, against 81.3% for simply repeating last year, and the best possible on this data is about 90%. Every other model beats its baseline: sold-out demand recovery cuts error from 36% to 9%, and supplier rates are predicted within 1.8%. We split by time, not at random, and the models only use data TBO would really have.

## Slide 8 · backtest

Accuracy is one thing; the real question is whether the plan makes money. So we went back to 11 August, retrained everything using only the data available that day, made the plan, and replayed it against what really happened over the next 12 weeks. It made 11.74 crore of realised profit, within 3% of what it predicted, and 61% more than copying last year's mix, which had 95 losing positions. The greedy baseline earned a little more, 11.98 crore, but needed 2.6 crore more capital, so our return per rupee is higher. This is on our synthetic dataset, so it shows the method works; it is not a claim about actual TBO profit.

## Slide 9 · product

This is the working prototype. Enter a budget on the left and the whole plan re-solves live: profit tiles, how three strategies compare, the profit distribution across a thousand futures, and where the money goes by destination and week. Click any position and it explains why. There's also a forecast explorer and a risk and budget strategy view. It's live at the link on screen, and the code is in our repository.

## Slide 10 · impact

For TBO, this means 28.5% more expected profit than last year's mix on the same budget, 7.6 crore saved by buying at the right time, and over 44,000 rooms and seats secured where supply usually runs out. One honest note: the challenge had no dataset, so we built a realistic synthetic one; the next step is plugging in TBO's real data through the data contract we built, and connecting live feeds to the automated re-planner. Thank you.
