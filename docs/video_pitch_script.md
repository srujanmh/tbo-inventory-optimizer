# Video pitch script — TBO Inventory Intelligence (about 3 minutes)

Record the screen with the live demo open:
https://claude.ai/artifact/XM6d4qBCJyEeFcAQNUKR3n

Speak at a calm pace. The **[on screen]** lines tell you what to show.

---

## 1. Hook (0:00–0:20)

**[on screen]** Landing page, "How it works" tab.

> "Hi, we are Team Void. TBO can pre-buy hotel rooms and flight seats cheaper than spot rates, and secure inventory when the market sells out. But every pre-buy is a bet. Buy too little and you lose bookings. Buy too much and unsold rooms become losses. Our prototype, TBO Inventory Intelligence, makes that bet with data."

## 2. The problem (0:20–0:45)

**[on screen]** Scroll to the three problem cards.

> "Three things make it hard. On 27% of days inventory is sold out, so bookings hide real demand. 585 hotel-weeks and route-weeks compete for one budget. And only 15 to 60% of unsold stock is refundable, while bookings cancel. The brief asks: what should TBO buy, how much, when, and at what price, within a given budget?"

## 3. How it works (0:45–1:15)

**[on screen]** The five-step "How it works" cards.

> "We answer in five steps. First, we recover true demand on sold-out days from search data. Then gradient-boosted models forecast demand with uncertainty ranges. They also predict prices, cancellations and supplier costs. Next, we simulate a thousand possible futures. Finally, an optimizer splits the budget to maximise profit while protecting the worst case."

## 4. Live demo (1:15–2:15)

**[on screen]** Budget Optimizer tab.

> "Here's the optimizer with a 75 crore budget. It expects about 13.9 crore profit, 27% more than repeating last year's mix, and saves 6.6 crore by buying at the right time."

**[on screen]** Drag the budget to 200 Cr.

> "If I push the budget to 200 crore, last year's mix turns red: it would lose money. Our plan stays profitable, and stops spending once nothing is worth the risk."

**[on screen]** Reset, then move the risk slider to "Protect downside".

> "The risk slider trades expected profit for a safer worst case, live."

**[on screen]** Click the top row of the buy plan.

> "Every position explains itself: how many seats, buy by when, at what price, and the demand drivers behind it."

## 5. Proof (2:15–2:45)

**[on screen]** Demand & Opportunities tab: back-test card, then the scorecard.

> "Does it work? We went back to 11 August, retrained using only the data available that day, and replayed the plan against what really happened. It made 11.97 crore of real profit, within 3% of its prediction, and 42% more than last year's mix. Weekly demand forecasts are 87.5% accurate on data the model never saw."

## 6. Close (2:45–3:00)

**[on screen]** Landing page.

> "TBO Inventory Intelligence: the right inventory, at the right time, within the right budget. The challenge had no dataset, so we built a realistic synthetic one. TBO's real data drops straight in with the same columns. Thank you."

---

## Recording tips

- **Before you record:** use a 1920×1080 browser window and the light theme.
- **During the take:** do the demo clicks slowly and pause about a second after each one so the numbers can animate.
- **Fallback:** if the live demo misbehaves, the same numbers are on slides 7–10 of the deck.
