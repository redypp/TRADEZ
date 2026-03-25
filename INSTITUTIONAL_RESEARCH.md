# Institutional & Professional Algorithmic Trading Research
## Compiled Insights from JPMorgan, Renaissance Technologies, Two Sigma, AQR, Man AHL, Lopez de Prado, Ernest Chan, Goldman Sachs, CFA Institute, and QuantConnect

> Compiled: March 2026 | Updated: March 24, 2026 | Relevance: MES BRT strategy on TRADEZ

---

## Overview

This document synthesizes the most important institutional research on systematic trading from the world's leading quantitative firms and practitioners. Each section maps directly to challenges and decisions facing the TRADEZ BRT strategy: validation, risk, sizing, drawdown, execution, and what makes strategies survive contact with live markets.

---

## Part 1: Strategy Validation — What the Institutions Know

### The Overfitting Problem (Lopez de Prado / AFML)

Marcos Lopez de Prado's foundational contribution to systematic trading is his quantification of backtest overfitting. His central argument: **most firms fail because backtesting while researching is like drunk driving** — you are selecting for strategies with the highest positive estimation error, not the best true edge.

Key concepts from *Advances in Financial Machine Learning*:

**Probability of Backtest Overfitting (PBO)**
- The PBO can be calculated numerically. If you test N parameter combinations and pick the best, the expected maximum performance across all trials grows with N — you are systematically selecting for noise.
- The PBO framework, using Combinatorially Symmetric Cross-Validation (CSCV), produces an actual probability that a given backtest is overfit.

**Purged K-Fold Cross-Validation**
- Standard K-Fold CV is wrong for financial time series because training and test sets share information through overlapping labels.
- Purged CV removes training observations whose labels overlap in time with test labels, then adds an **embargo period** after each test fold.
- This prevents look-ahead bias at the fold boundary — a bias invisible to most backtesting frameworks.

**Combinatorial Purged Cross-Validation (CPCV)**
- CPCV goes further: instead of a single walk-forward path, it constructs C(N,k) train-test splits across N ordered groups with k test groups.
- Result: a **distribution** of out-of-sample performance estimates, not a single number.
- Key benefit: reduces dependence on any single market regime. A strategy that looks good in CPCV has been stress-tested across multiple historical scenarios.
- The Deflated Sharpe Ratio (DSR) corrects the reported Sharpe for the number of trials — penalizing strategies found through extensive parameter search.

**"Backtesting is not a research tool. Feature importance is."**
- Lopez de Prado's most provocative claim: the right way to validate a model is to measure which features actually drive predictions (Mean Decrease Impurity, Mean Decrease Accuracy), not to optimize parameters against historical P&L.
- If a model's top predictive features make economic sense, the model is more likely to survive out-of-sample.

**Hierarchical Risk Parity (HRP)**
- Traditional Markowitz optimization requires an invertible covariance matrix and is known to produce unstable, concentrated portfolios.
- HRP uses hierarchical clustering on the correlation matrix to group similar assets, then allocates risk inversely within and between clusters.
- Monte Carlo experiments show HRP produces **lower out-of-sample variance than minimum-variance MVO**, even though minimizing variance is MVO's explicit objective.
- For multi-strategy or multi-instrument portfolios, HRP is more robust than equal-weight or traditional risk-parity.

---

### Ernest Chan's Validation Checklist

From *Quantitative Trading* and *Algorithmic Trading* (Ernest Chan, 2nd ed.):

**The questions to ask before trading any strategy:**
1. Does the data suffer from survivorship bias? (Delisted stocks, failed contracts excluded from history)
2. Does the strategy suffer from data-snooping bias? (Were parameters chosen by testing many combinations on the same dataset?)
3. How did performance change over the years? (Did the edge decay after discovery?)
4. How does it compare to a benchmark and how consistent are returns?
5. How deep and how long are the drawdowns?
6. How will transaction costs and slippage affect the strategy?

**Key mistakes Chan documents:**
- **Survivorship bias**: Using only currently-traded instruments in backtests. Stocks that were delisted, merged, or went bankrupt are excluded, making historical performance look better than it was.
- **Look-ahead bias**: Using closing prices to generate signals that would have required future information in real-time.
- **Ignoring market impact**: Backtests assume you can buy/sell at the close. Intraday strategies using mid-prices without spread modeling are especially vulnerable.
- **Capacity blindness**: A strategy generating 3.0 Sharpe on $50k may be impossible to scale — the edge lives in microstructure and disappears with size. Chan notes it is genuinely easier to generate high Sharpe ratios as an independent trader than at a hedge fund.
- **Static Kelly**: Using a fixed historical win rate and R-ratio in the Kelly formula ignores regime changes. Chan advocates using a **trailing mean return** for Kelly inputs — adaptive rather than static.
- **In-sample/out-of-sample discipline**: A minimum of 1/3 of the sample period should be reserved as out-of-sample. Many traders backtest on all available data and call it validation.

---

### QuantConnect Community Standards

From QuantConnect's Research Guide and platform documentation:

- **Limit the number of backtests per idea.** Every backtest moves an idea closer to overfitting. QuantConnect recommends no more than ~16 hours of total work per experiment.
- **Start from a hypothesis, not from parameters.** The research guide explicitly states: if you find yourself deviating from your core thesis to introduce code that isn't based on it, stop and return to thesis development.
- **Stress-test across market cycles.** A minimum backtest of 10 years should cover at least one major bear market and one bull market. A strategy that only works in one regime is not robust.
- **Point-in-time data.** Use data exactly as it appeared at that moment — no look-ahead from revisions, splits, or corporate actions. QuantConnect includes delisted stocks to avoid survivorship bias.
- **Realistic transaction costs are non-negotiable.** Profitable-looking strategies in frictionless backtests frequently fail live. Model commissions, slippage, and market impact explicitly.
- **Walk-forward optimization only.** Adding or fine-tuning parameters should only be done via walk-forward — never by optimizing parameters on the full sample and calling it a backtest.

---

### JPMorgan: Point-In-Time Data as a Prerequisite

From the JPMaQS (J.P. Morgan Macrosynergy Quantamental System):

JPMorgan's systematic research team emphasizes that backtesting with revised macroeconomic data **defeats the whole purpose of backtesting a systematic strategy**. Their JPMaQS system tracks macro variables (growth, inflation, external balances) across dozens of currency zones with deep history, providing true point-in-time indicators free from revisions.

The lesson for any systematic strategy: the data pipeline itself must preserve the information state that existed at each historical timestamp. Any revision, adjustment, or look-forward contamination invalidates the backtest.

---

## Part 2: Risk Management — Institutional Frameworks

### The Universal Risk Rules

Across JPMorgan, Man AHL, Two Sigma, and CFA Institute frameworks, several risk management principles are universal:

**1. Risk per trade: 1–2% of capital maximum**
The CFA Institute standard is to risk no more than 2% of total capital on any single trade. This "2% rule" prevents hitting the "Point of Ruin" — the mathematical state where the capital base shrinks so fast that geometric recovery becomes nearly impossible (a 50% drawdown requires a 100% gain to recover).

TRADEZ current setting: `RISK_PER_TRADE = 0.01` (1%) — this is at the conservative end of institutional standards and is correct for a strategy still accumulating live track record.

**2. Daily loss limits with hard kill switches**
Every serious systematic trading operation implements a daily loss limit that automatically halts trading. This is not optional — it is the primary protection against runaway losses from model failures, data errors, or adverse regime shifts.

Man AHL's CIO Russell Korgaonkar: "By adjusting position sizes, traders can stay in the game during stressful markets and maximize their chances of optimizing returns."

TRADEZ current setting: `MAX_DAILY_DRAWDOWN = 0.03` (3%) — this is consistent with institutional standards for a small intraday futures system.

**3. Correlation awareness across positions**
Being long ES, NQ, and YM simultaneously is not three diversified trades — it is one leveraged bet on the U.S. economy. Correlation monitoring at the portfolio level is required before scaling multi-instrument systems. Man AHL addresses this through explicit diversification research and cross-asset correlation tracking.

**4. Notional value vs. margin confusion**
Futures traders must size positions relative to notional contract value, not margin requirements. Sizing to the margin minimum means unknowing leverage of 5–20x. A 5% adverse move in a margin-sized position can liquidate the account.

**5. Regime-conditional position reduction**
JPMorgan, Man AHL, and Two Sigma all use regime detection to reduce position sizes during elevated volatility. Man AHL explicitly reduces exposure when their regime models identify unfavorable conditions. This is not optional — it is core to survival.

---

### Man AHL's 30-Year Risk Philosophy

Man AHL (founded 1987, ~$100B+ AUM) has survived through every major market disruption since the late 1980s. Their published risk framework:

- Risk management is built into all models, enhanced by an independent Risk team.
- Knowing **what not to trade** is as important as knowing what to trade.
- During the 2009–2013 trend-following drought (SG Trend index: -1.8% over 4 years), investors who stayed the course saw +19.7% in 2014.
- The lesson: drawdowns are expected features, not bugs. The worst outcome is abandoning a sound strategy at the trough.
- Man AHL models tail scenarios explicitly, not just expected outcomes.
- "The richest vein of research in trend following is new markets" — diversification across instruments is more durable alpha than model complexity.

---

### Two Sigma's Risk Infrastructure

Two Sigma employs sophisticated risk models across market risk, credit risk, and liquidity risk. Key public insights:

- They run 48,000+ simulations daily to test portfolio robustness.
- Risk models assess correlation as a **variable quantity**, not a static input — they account for correlation breakdowns under stress.
- Their research shows that systematic and discretionary macro strategies have similar risk-adjusted returns on average, but a blend of the two historically produced higher Sharpe than either alone. This diversification across strategy types is itself a risk management tool.

---

### The Kelly Criterion — Institutional Application

From AQR, Chan, and academic research:

**Full Kelly formula:** `f* = (bp - q) / b`
where b = odds, p = win probability, q = loss probability

**Trading simplification:** `Kelly % = W - [(1-W) / R]`
where W = win rate, R = win/loss ratio

**Why most institutions use Fractional Kelly (Half or Quarter):**
- Full Kelly maximizes long-term geometric growth but produces maximum short-term volatility.
- A single bad estimate of win rate or R causes catastrophic leverage errors.
- Half-Kelly produces ~75% of the long-term growth of Full Kelly with approximately half the variance.
- Quarter-Kelly is common in live trading for new strategies without sufficient statistical sample.

**Chan's adaptive Kelly recommendation:**
Use a trailing mean return (not full-history mean) for Kelly inputs. As market regimes shift, the trailing estimate adapts, automatically reducing size in deteriorating conditions.

**Recent research (2024, arXiv): Kelly vs. VIX Hybrid**
A hybrid method combining Kelly criterion sizing with VIX-regime scaling has been shown to consistently balance return generation with robust drawdown control, particularly under low-volatility conditions. The VIX-adaptive component prevents over-sizing during apparent low-volatility periods that may precede sudden regime shifts.

This maps directly to TRADEZ's regime.py engine: the VIX-based regime already implements something close to a VIX-hybrid Kelly in spirit.

---

## Part 3: Position Sizing — The Mechanics

### ATR-Based Volatility-Adjusted Sizing

The standard institutional approach for futures position sizing:

```
Dollar Risk = Account Size × Risk_Per_Trade
Stop Distance = |Entry - Stop| in points
Contract Value per Point = $5 (MES)
Contracts = Dollar Risk / (Stop Distance × Contract Value per Point)
```

Static lot sizing is categorically wrong for volatility-adaptive strategies. A 3-contract position in a quiet market (ATR = 8 pts) represents completely different risk than 3 contracts in a high-volatility market (ATR = 20 pts).

**ATR sizing rule:**
- During high-volatility periods (increasing ATR): wider stops are needed to avoid noise, so position size must decrease to keep dollar risk constant.
- During low-volatility periods (decreasing ATR): tighter stops are possible, allowing larger position size at the same dollar risk.

TRADEZ's current implementation correctly computes SL from ATR and derives contracts from the dollar risk formula — this is the right approach.

---

### The Math of Drawdown Asymmetry

The most underappreciated concept in risk management, cited by both the CFA Institute and quant practitioners:

| Drawdown | Required recovery gain |
|----------|----------------------|
| 10%      | 11.1%                |
| 20%      | 25%                  |
| 30%      | 42.9%                |
| 40%      | 66.7%                |
| 50%      | 100%                 |
| 60%      | 150%                 |

Every incremental drawdown past 20% becomes geometrically harder to recover from. This is why institutions cap daily drawdowns, have strategy-level drawdown limits, and sometimes pause systems for weeks after large drawdowns — not because they lost confidence in the model, but because **the math of geometric returns demands capital preservation**.

TRADEZ's 26.2% max drawdown in backtest is significant. Institutional standards for micro-futures intraday systems typically target max drawdown under 20%. This should be a near-term improvement priority.

---

## Part 4: Execution — Slippage, Market Impact, and TCA

### The True Cost of Execution

From Goldman Sachs, AQR "Trading Costs" paper (Frazzini, Israel, Moskowitz), and Quantitative Brokers:

The AQR Trading Costs paper is definitive on this: **commissions and bid-ask spreads are small by comparison to price impact at scale**. For retail/small-fund intraday traders, the dominant costs are:

1. **Slippage** = difference between the price at signal generation and the actual fill price
2. **Market impact** = the price move caused by your own order
3. **Opportunity cost** = trades that couldn't be filled at acceptable prices

**Slippage varies by strategy type:**
- Momentum strategies suffer more slippage because they buy instruments already moving in the forecast direction — you are competing with momentum.
- Mean-reversion strategies suffer less slippage because you are trading against the current direction, providing liquidity rather than consuming it.

Break & Retest (BRT) is a **momentum-entry, mean-reversion-confirmation** hybrid: the break is momentum, the retest is mean-reversion entry. This should produce moderate slippage — better than pure momentum, not as favorable as pure mean-reversion.

**TRADEZ current slippage assumption:** `BRT_COST_PER_RT = 2.94` ($2.94 per round trip) — this covers Tradovate commissions and a small slippage allowance. For MES at ~$5/point, $2.94 represents approximately 0.59 points of slippage/commission combined. This is reasonable for a liquid CME micro-futures contract.

**Goldman Sachs on execution benchmarks:**
Goldman's AXIS algorithm benchmarks against **Arrival Price** (the market price at the moment an order is submitted). Implementation Shortfall — the difference between theoretical returns and realized returns including execution costs — is the metric that matters. Tracking implementation shortfall across all live trades identifies whether the strategy's edge is being eroded at execution.

**Pre-trade vs. post-trade TCA:**
Institutions use pre-trade TCA to estimate likely slippage before placing an order (choosing TWAP vs. VWAP vs. aggressive fill based on conditions), and post-trade TCA to measure actual versus benchmark. For a retail algorithmic system, the minimum viable equivalent is: log entry price vs. signal price for every trade and track the distribution over time.

---

### JPMorgan's Execution Algorithm Insights

JPMorgan's $29.8B markets operation uses deep reinforcement learning for child order execution, trained on billions of simulated trades. Their key findings applicable to smaller systems:

- **Volume profile prediction** matters: execution quality improves significantly when the algorithm anticipates how liquidity will evolve through the session.
- **Randomization of order timing** within an interval reduces market impact and detection by other algorithms.
- For liquid instruments like MES, **limit order execution at retest** (rather than market orders) meaningfully reduces slippage. The BRT retest entry is ideally suited to limit orders since you know approximately where price should return.

---

## Part 5: What Separates Strategies That Work

### The Backtest-to-Live Decay Problem

Research across QuantConnect, academic literature, and practitioner experience identifies a consistent pattern: most strategies underperform their backtests in live trading. The causes, ranked by frequency:

**1. Overfitting (most common)**
The backtest Sharpe was achieved by finding the best-performing parameter set in-sample. Live trading, by definition, is out-of-sample. The more parameters optimized, the larger the performance gap.

Deflated Sharpe Ratio check: a raw Sharpe of 3.70 (TRADEZ backtest) sounds excellent, but the DSR adjustment must account for how many parameter combinations were tested to achieve it. If dozens of parameter sets were tried before settling on the current config, the DSR may be significantly lower.

**2. Market regime shift**
A strategy calibrated in one regime (e.g., trending 2020–2021) may encounter different conditions live. TRADEZ's regime-adaptive engine explicitly addresses this by adjusting parameters based on VIX — this is a genuine institutional-grade feature.

**3. Transaction cost underestimation**
The difference between modeled and actual execution costs compounds quickly in high-frequency strategies. For 21 trades over 6 months (TRADEZ backtest), cost underestimation of $5/trade = $105 total — manageable. At 2 trades/day live, a $5 underestimate = $2,600/year drag.

**4. Data quality inconsistencies**
yfinance data for backtesting may produce different candle timestamps, adjusted vs. unadjusted prices, or missing data points compared to what Tradovate delivers live. This is a systematic risk for TRADEZ: the backtest engine should be validated against Tradovate market data before trusting backtest numbers.

**5. Emotional interference**
Systematic strategies fail when traders override signals. The solution is not willpower — it is architecture: the bot runs, the human monitors the dashboard and only intervenes for system failures, not for "I don't like this trade."

---

### Renaissance Technologies: The 50.75% Principle

The Medallion Fund's most important public lesson: **you do not need to be right most of the time. You need a consistent, small edge applied thousands of times.**

Robert Mercer revealed the Medallion Fund was right only ~50.75% of the time. The fund's extraordinary returns came from:
1. Being right slightly more than half the time
2. Applying that edge across 150,000–300,000 automated trades per day
3. Eliminating emotional interference through full automation
4. Using leverage precisely (12.5x average, based on data confidence)

For TRADEZ with ~21 trades over 6 months at 47.6% win rate with 2.0R target: the math suggests the edge exists but needs more sample size. The institutional standard for a new systematic strategy is a minimum of 100–300 live trades before drawing statistically significant conclusions about live performance.

**Key lesson from Renaissance:** When their models failed catastrophically in August 2007 (losing $1B = 20% in three days), they let the automated systems run rather than intervening. By year-end 2007, the fund returned +85.9%. The lesson is not that you should never stop a losing strategy — it is that **abandoning a well-validated strategy at the trough is one of the most costly mistakes in systematic trading**.

---

### AQR: Why Factors and Strategies Have Dark Times

AQR's factor research establishes that every systematic strategy has extended periods of underperformance:
- Momentum strategies had their worst drawdown in March 2009 (sharp reversal from crisis momentum).
- Value strategies underperformed for years through 2018–2020 ("quant winter").
- Trend-following CTAs produced flat-to-negative returns from 2009–2013.

AQR's conclusion: "Every factor has its dark times. The question is whether you understand why the strategy should work and have the conviction to hold through drawdowns."

This applies directly to Break & Retest: there will be periods where the market structure does not produce clean breaks and retests, where every setup fails, and where the strategy enters an extended drawdown. The regime engine and daily loss limits are the institutional answer to this — they reduce exposure during unfavorable periods without abandoning the strategy.

---

### Two Sigma: Hypothesis Before Data

Two Sigma's research process: "We aim to formulate ideas that make intuitive, economic, and financial sense, then source, clean, and analyze vast amounts of data to test and refine those ideas."

This is the opposite of data mining. The break-and-retest strategy has a clear economic hypothesis:
- Institutional participants initiate positions at key price levels (VWAP, PDH/PDL, opening range).
- A break of these levels signals a change in order flow.
- The retest provides late-to-position participants an entry, and the failed retest confirms the original break was genuine.
- ADX, volume, and candle body filters confirm that the move has institutional momentum behind it, not random noise.

This hypothesis-first construction is exactly what Two Sigma, Lopez de Prado, and Chan all recommend. It means the strategy parameters should be **interpretable in the context of the hypothesis** — not found by optimization.

---

### Man AHL: The Three Reasons Trend Following Works

Man AHL's published research identifies three structural reasons trend-following (and by extension, break-continuation) strategies have persistent edges:

1. **Information diffusion**: Not all market participants receive or process information simultaneously. Early movers cause price trends; late movers continue them.
2. **Autocorrelation in the drivers of market returns**: Macro fundamentals (earnings growth, monetary policy) persist over time, creating sustained directional pressure.
3. **Human behavior**: Anchoring, herding, and slow reaction to new information create systematic patterns in price.

All three apply to the BRT strategy's break-continuation phase: institutional order flow (information diffusion), intraday momentum (autocorrelation), and retail participation at obvious levels (behavioral).

---

## Part 6: Specific Institutional Insights by Firm

### JPMorgan Summary
- Machine learning execution trained on billions of simulated trades — key insight: RL-optimized execution minimizes market impact
- QIS trend-following on equity factors shows diversification value beyond price trend following alone
- JPMaQS: point-in-time data is a non-negotiable prerequisite for valid backtesting
- LLM use in trading requires caution: "the antithesis of systematic strategies, which are designed to be repetitive, rules-based and replicable"
- AXIS algorithm: proprietary signals embedded in execution logic consistently outperform legacy products on implementation shortfall

### Renaissance Technologies Summary
- 66%+ annual returns before fees from 1994–2014
- Edge was 50.75% win rate at scale, not prediction accuracy
- Full automation eliminates emotional interference — the core structural advantage
- Data obsession: cleaned and collected pricing data across all asset classes before "big data" existed
- Leverage used precisely, data-driven: 12.5x average, up to 20x when data confidence is high
- Never interfere with running models during drawdowns (the 2007 lesson)

### Two Sigma Summary
- 250+ PhDs among 1,700+ employees — the firm is literally a scientific institution
- 48,000+ simulations run daily — strategy robustness is continuously stress-tested
- Combine systematic and discretionary macro for higher Sharpe than either alone
- Factor Lens identifies two main factor types: macroeconomic (cross-asset) and style (within-asset)
- Trend following is a confirmed style factor in their Factor Lens — Sharpe ~0.84 for factor momentum

### AQR Summary
- "Value and Momentum Everywhere" — momentum works across all major asset classes and geographies
- "Factor Momentum Everywhere" — factor timing based on own recent performance yields Sharpe 0.84
- Momentum suffers periodic severe drawdowns but recovers — persistence requires conviction
- AQR momentum indices: top 33% of stocks by 12-month return (excl. last month), reconstituted quarterly
- Diversification across factors (Value + Momentum + Quality) is more robust than single-factor

### Man AHL Summary
- Founded 1987, evolved from pure trend following to multi-strategy quant
- Markets exhibiting persistent anomalies (trends, mean-reversion, carry) are exploitable via statistical analysis
- MACs + breakouts are different and complementary signals — combining improves risk-adjusted returns
- 600+ markets traded including OTC — "richest vein of research is new markets, not new models"
- Oxford-Man Institute partnership: ML research applied systematically to trading
- Drawdown resilience: investors who stayed through 2009–2013 CTA drought were rewarded in 2014

### Goldman Sachs Summary
- GSAT algorithms: VWAP, TWAP, POV, Implementation Shortfall with quantitative volume profile models
- AXIS: proprietary signal-embedded execution consistently outperforms legacy products vs. arrival price
- Atlas platform: lower latency, higher capacity, modular — designed for signal-driven intraday execution
- AI-powered desks: 27% increase in intraday trade profitability vs. human-only
- Algorithmic trading market share in futures continues to rise — liquidity microstructure is increasingly algo-driven
- HFT growth may increase liquidity fragility — not all participants can access HFT-provided liquidity

### Lopez de Prado (AFML) Summary
- Backtesting while researching = "drunk driving" — you select for noise, not signal
- CPCV: multiple historical paths, not one — produces a distribution of performance estimates
- Purged K-Fold: eliminate look-ahead bias at fold boundaries with purging + embargo
- PBO + DSR: quantify how likely a backtest is overfit, penalize strategies found through extensive search
- Feature importance (MDI, MDA) is the correct research tool — not parameter optimization
- HRP: ML-based portfolio construction outperforms Markowitz on out-of-sample variance
- "Backtesting is not a research tool. Feature importance is."

### Ernest Chan Summary
- Survivorship bias, look-ahead bias, data-snooping bias: the three execution sins
- In-sample/out-of-sample split: minimum 1/3 out-of-sample, non-negotiable
- Trailing Kelly inputs: adaptive, not static
- Capacity limits are real: edge disappears with scale; independent traders have genuine advantages vs. hedge funds
- Transaction costs + slippage: the gap between modeled and actual execution compounds over time
- Structural breaks: strategies must be re-evaluated when market microstructure changes

### CFA Institute Summary
- Maximum drawdown (MDD) is the most practically important risk metric for systematic strategies — clients and managers care about it more than Sharpe
- MDD alone is insufficient — use with drawdown distribution, Calmar ratio (annualized return / MDD), and up/down capture
- Risk management is "as much the art of managing people, processes, and institutions as it is the science of measuring risk"
- Monte Carlo simulation for long-horizon risk: simulates 5, 10, 20-year capital trajectories across correlated asset classes
- Multi-factor model construction: high correlation between factors creates redundancy and reduces efficiency — factor independence matters

---

## Part 7: The 12 Rules That Survive Contact With Markets

Synthesized from all sources above — these are the principles every institutional systematic trader agrees on:

**Rule 1: Your hypothesis must have an economic reason to work.**
Not "this pattern worked in backtest." What market inefficiency, behavioral bias, or structural friction does this strategy exploit? BRT exploits: institutional level-based order flow and the break-continuation dynamic. This is a valid hypothesis.

**Rule 2: Data quality is the foundation, not a detail.**
Point-in-time data, no survivorship bias, adjusted prices, correct timestamps. One contaminated data feed invalidates every backtest run against it. Validate yfinance data against Tradovate before trusting backtest numbers.

**Rule 3: Fewer parameters, stronger claims.**
Every additional parameter is a probability of false discovery. The current BRT strategy has many parameters (ADX min, SL buffer, TP ratio, retest bars, volume threshold, break buffer, break body minimum, RSI range). Each one was likely calibrated to historical data. CPCV across all parameter combinations would show whether the edge is genuine or fitted.

**Rule 4: The Deflated Sharpe Ratio is the honest Sharpe.**
A backtest Sharpe of 3.70 is impressive — but if it was achieved after testing multiple parameter combinations, the DSR may be materially lower. Document every parameter combination tested and apply the DSR correction.

**Rule 5: Out-of-sample performance is the only performance that matters.**
In-sample optimization is not validation. The only valid test is a strict time-blocked hold-out period that was never used during development, or better, forward paper trading.

**Rule 6: Transaction costs must be modeled at pessimistic estimates.**
Model commissions + slippage at 1.5–2x your current estimate during strategy development. If a strategy fails with conservative cost assumptions, it will fail live. If it passes conservative assumptions, live performance may be better than modeled.

**Rule 7: Position sizing must be volatility-adjusted.**
Fixed lot sizes are wrong. ATR-based sizing that keeps dollar risk constant across all market conditions is the minimum. Regime-adaptive sizing (reducing to Half or Minimum during elevated VIX) is the institutional standard.

**Rule 8: Daily loss limits are not suggestions.**
Hard kill switches at 3–5% daily loss are required. The mathematical asymmetry of drawdown recovery means that protecting against catastrophic days is worth more than capturing additional upside on any single day.

**Rule 9: 100+ live trades before drawing conclusions.**
21 trades is not a statistical sample. 47.6% win rate on 21 trades has enormous confidence intervals — the true win rate could be anywhere from 25% to 70% at 95% confidence. Target 50–100 paper trades, then 100+ live trades, before evaluating strategy performance.

**Rule 10: Drawdowns are features, not failures — but manage them actively.**
Every valid strategy has extended drawdown periods. The institutional answer is regime detection + position sizing reduction, not strategy abandonment. But also not denial — a 26.2% max drawdown is at the edge of acceptable for a small intraday system.

**Rule 11: Automation requires discipline in non-interference.**
Renaissance's most important insight: do not override the model during drawdowns based on discretionary judgment. The model ran when it lost $1B in 3 days and made +85.9% by year-end. Human interference at drawdown troughs is consistently value-destroying.

**Rule 12: Monitor execution quality continuously.**
Log entry price vs. signal price for every trade. Track slippage distribution over time. If live slippage exceeds modeled slippage by more than 50%, the backtest is no longer predictive and the live edge may be negative.

---

## Part 8: Direct Application to TRADEZ BRT Strategy

### Strengths (Confirmed by Institutional Research)
- Hypothesis-first design with clear economic logic (level-based institutional order flow)
- Regime-adaptive parameters (VIX-based, exactly what Man AHL and JPMorgan do)
- ATR-based SL/TP sizing (correct volatility-adjusted approach)
- 1% risk per trade with 3% daily drawdown limit (within institutional standards)
- Multiple confirmation filters (ADX, RSI, volume, candle body) reduce false signals
- NO_TRADE regime at VIX > 40 (correct — even Man AHL reduces exposure in extreme volatility)
- Out-of-sample Sharpe ≥ in-sample Sharpe (no decay observed — a positive signal)

### Risks to Investigate (Based on Institutional Research)
- **26.2% max drawdown** — above the ~20% target for professional intraday systems. Investigate whether tighter daily stops or regime-based position halts can bring this below 20%.
- **21 trades is insufficient sample** — 47.6% win rate and 1.63 profit factor are directionally positive but statistically inconclusive. The confidence intervals are wide.
- **yfinance vs. Tradovate data gap** — backtest data source (yfinance) and live execution data source (Tradovate) may differ. Validate price history and timestamp alignment before trusting backtest-to-live comparisons.
- **Sharpe of 3.70 needs DSR adjustment** — document how many parameter combinations were evaluated during development and apply the Deflated Sharpe Ratio correction to get an honest performance estimate.
- **High parameter count** — BRT has ~12+ configurable parameters. Lopez de Prado's framework suggests using CPCV across parameter variations to validate that the edge is parameter-robust.
- **Limit order vs. market order at retest entry** — if using market orders at retest, slippage may be higher than modeled. Limit orders at the retest level (with a small buffer) would reduce execution cost and improve the backtest-to-live transition.

### Immediate Priorities (Based on Institutional Consensus)
1. Forward paper trade 50–100 trades before going live — no institution would trade a 21-trade backtest
2. Log entry price vs. signal price in every paper trade to measure actual slippage
3. Validate yfinance historical data against Tradovate market data for timestamp and price consistency
4. Investigate reducing max drawdown from 26.2% → target < 20% via more aggressive intraday halt rules
5. Apply DSR correction to the 3.70 Sharpe to get an honest risk-adjusted estimate

---

---

## Part 9: Extended Source Detail — New Research (March 2026 Update)

This section captures additional research gathered in the March 2026 update, filling in gaps from sources referenced in earlier passes.

---

### Goldman Sachs — QIS, Alpha Enhanced, and Execution Infrastructure (Extended)

Goldman Sachs operates one of the most sophisticated systematic trading operations on Wall Street, with its QIS team celebrating 35+ years of investing backed by 80+ practitioners, 90+ engineers, and 100+ proprietary datasets.

**The "Alpha Enhanced" approach:**
Goldman's core thesis for institutional equity portfolios is placing data-driven, systematic stock selection — the "Alpha Enhanced" strategy — at the center, not the periphery. Key principles:
- Use diversified return and risk drivers, not single-factor bets, to pursue idiosyncratic excess return.
- Systematically remain independent of any specific factor or style — alpha is pursued structurally, not through factor concentration.
- Exploit alternative data to target alpha structurally different from standard factor premia — preserving diversification.
- In European equities specifically: markets' slower EPS revision reaction creates exploitable temporal inefficiencies that quantitative strategies consistently extract.

**GS Quant / Marquee platform:**
Goldman's internal trading infrastructure is now available externally as GS Quant, trusted daily by 1,000+ Goldman quant developers. Critical features for any serious systematic trader:
- Access to intraday and end-of-day datasets across all asset classes
- Path-dependent strategy backtesting with complex transaction models
- Time series analytics in native Python — no proprietary language overhead
- The same infrastructure Goldman uses internally to manage $1T+ in capital

**Generative AI in systematic investing:**
Goldman's research documents that LLMs open new avenues for signal extraction from unstructured data — earnings call transcripts, financial news sentiment, regulatory filings. The key institutional insight: AI tools are being used to generate and refine signals, not to replace the underlying systematic risk management framework. The framework remains rules-based; the signal inputs become richer.

---

### QuantConnect — Realistic Expectations and Platform Standards (Extended)

QuantConnect's community and documentation represent one of the richest public databases of what works and fails in systematic retail algorithmic trading.

**The core expectation-setting framework:**
- Frame goals as risk-adjusted return targets (Sharpe ratio), not raw percentage returns. A 1% annual strategy with 0.1% volatility is genuinely superior to a 10% strategy with 30% volatility on any rational metric.
- The development difficulty vs. profitability trade-off is real: simpler strategies are easier to code but often harder to make profitable in practice. Complexity adds overfitting risk but may capture more nuanced inefficiencies.
- There is no free lunch in systematic trading — strategies that appear to work easily in backtests are the most likely candidates for overfitting.

**QuantConnect platform institutional-grade features:**
- 300,000+ users worldwide; $45B+ notional volume monthly
- LEAN engine: open-source, event-driven, simulates T+3 settlement, brokerage fees, slippage, spread adjustments
- Minute-resolution US equity data from 1998, delisted stocks included (no survivorship bias)
- The Strategy Development Framework (SDF) modularizes Alpha Creation, Universe Selection, and Portfolio Construction
- Alpha Streams marketplace: quants can lease algorithms to institutional funds — one of the few public bridges between retail research and institutional capital

**The QuantConnect "Realistic Expectations" thread** (community consensus):
1. Your first goal should be not losing money, not making money.
2. A strategy should be profitable on a risk-adjusted basis before adding leverage.
3. If a strategy's parameters need extensive optimization to become profitable, the strategy probably doesn't have an edge.
4. Paper trading for at minimum 3 months before committing real capital is the community standard.
5. Focus on strategies with an identifiable reason to work (hypothesis-first), not on strategies that happen to have worked in backtest.

---

### CFA Institute — Electronic Trading Risks and Governance (Extended)

The CFA Institute provides the most complete formal framework for electronic and algorithmic trading governance.

**The five execution algorithm types and their appropriate use cases:**

| Algorithm Type | Use Case | Risk Profile |
|---|---|---|
| VWAP (Scheduled) | Large orders requiring minimal information leakage | Low urgency; predictable execution |
| TWAP (Scheduled) | Equal time-slice execution when VWAP profile uncertain | Low urgency; consistent execution |
| Arrival Price (IS) | Small-to-medium orders in liquid markets | Higher aggression; appropriate when directional risk high |
| Dark Aggregators | Large orders in illiquid markets | Minimal market impact; uncertain fill timing |
| Smart Order Routers | Small orders across multiple venues | Best price across fragmented liquidity |

**Electronic trading-specific risks the CFA formally identifies:**
1. **Runaway algorithms**: Programming errors producing unintended order streams. Defense: pre-trade size and rate checks, kill switches.
2. **Overlarge orders**: Demanding more liquidity than the market can supply. The 2010 Flash Crash is the canonical example.
3. **Malicious order streams**: Disgruntled employees or external attackers injecting harmful orders.
4. **Cascading systemic events**: Correlated algorithm responses to the same trigger causing synchronized mass selling.
5. **Execution risk vs. market impact trade-off**: Fundamental tension — slowing execution reduces market impact but increases directional exposure.

**Governance requirements per CFA standards:**
- Formal trade policy document covering all trading strategies and escalation procedures
- Automated Order Management System (OMS) with pre-trade manipulation checks
- Real-time cross-platform surveillance for wash trading, layering, spoofing
- Post-trade Transaction Cost Analysis (TCA) against multiple benchmarks
- Human oversight protocols for monitoring and intervening when algorithms behave unexpectedly

---

### Strategy Decay Detection — Formal Framework (Extended)

Research published in *Quantitative Finance* (2022) and practitioner sources provide a formal framework for detecting when a systematic strategy stops working.

**The two root causes of decay (Quantitative Finance, 2022):**
1. **Arbitrage crowding**: Successful strategies attract capital. As more money chases the same trades, the price impact of early entries increases, reducing the edge for late entrants. Publication year of a strategy alone explains 30% of variance in Sharpe ratio decay. Newly published factors lose 5 percentage points of Sharpe annually in the years after publication.
2. **In-sample overfitting**: Strategies found through extensive parameter search are fragile — they worked historically because the parameters were selected for that specific historical period, not because the underlying signal is robust.

**Warning signs of decay to monitor on every live strategy:**
- Win rate dropping below the lower bound of backtest confidence interval
- Average trade duration increasing without corresponding increase in average trade return
- Slippage increasing (other participants racing ahead of the same signals)
- Worsening payoff-to-risk ratio (average win / average loss shrinking)
- Drawdown behavior changing character (longer, deeper than historical profile)
- Strategy returns becoming correlated with a known factor it previously avoided

**Formal statistical tests for decay:**
- **CUSUM (Cumulative Sum)**: Detects persistent shifts in the mean return — effective for gradual decay
- **Kolmogorov-Smirnov Test**: Detects changes in the distribution of returns, not just the mean
- **Wasserstein Distance**: Measures the magnitude of distribution shifts over rolling windows
- **DTW (Dynamic Time Warping)**: Recognizes similar pattern formations across different time scales

**The health score framework (practitioner approach):**
Combine short-run performance metrics (14–21 day rolling Sharpe, win rate, average trade duration) with long-run baselines (full history) to produce a composite health score ranging from -1 (sick) to +2 (healthy):
- Score +2: strategy performing as expected — full size
- Score +1: mildly underperforming — maintain but monitor
- Score 0: borderline — reduce to half size and investigate
- Score -1: clearly broken — suspend trading, diagnose

**Adjusting vs. abandoning:**
The most common mistake is abandoning strategies at their trough (AQR's documented "dark times" for every factor). The correct response to deterioration is to reduce exposure first, not to replace the strategy. Only abandon when: the theoretical hypothesis no longer applies (market structure has permanently changed), or performance has deteriorated across all time horizons for an extended period that exceeds normal drawdown expectations.

---

### Walk-Forward and Validation Pipeline — Extended Detail

Research from a 2024 ScienceDirect study on backtest overfitting confirmed that **95% of backtested strategies fail in live markets**. The causes, in order of frequency:
1. Optimization on the full in-sample dataset (the single most common cause)
2. Look-ahead bias at fold boundaries in cross-validation
3. Inadequate holdout period (using validation data repeatedly for hyperparameter tuning)
4. Regime mismatch (calibrated in one market regime, deployed in another)

**The three-dataset minimum for ML-based strategies:**
- Training Set: fit model parameters (60% of data, earliest period)
- Validation Set: tune hyperparameters (20% of data, middle period)
- Blind Test Set: final evaluation used only once before deployment (20% of data, most recent period)

Reusing the test set — even once — converts it into effectively training data. The only clean evaluation is one that has never been seen.

**Walk-Forward Optimization (WFO) mechanics:**
Standard implementation: 2-year in-sample optimization window, 6-month out-of-sample test window, anchored (not rolling) in-sample period to preserve maximum data for the most recent optimization. Advance by 6 months and repeat.

The WFO "profit plateau" test: a robust strategy should show good performance across a range of nearby parameters, not just at a single optimal point. A single-parameter peak almost always indicates noise-fitting, not a genuine edge.

**CPCV's unique advantage:**
CPCV produces a distribution of backtest performance, not a single Sharpe ratio. This distribution allows computing:
- Expected out-of-sample Sharpe (not just the single-path estimate)
- Probability that the strategy underperforms a random benchmark (PBO)
- The Deflated Sharpe Ratio incorporating the number of trials conducted

A strategy with PBO < 5% and DSR > 1.0 has passed institutional-level validation standards.

---

### Lopez de Prado — "10 Reasons Most Machine Learning Funds Fail" (2018) — Key Points

Published in *Journal of Portfolio Management*, Special Issue dedicated to Stephen A. Ross, 2018, 44(6):120–133. Available free: [SSRN 3104816](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3104816).

**The 10 pitfalls and their solutions (structure from the paper):**

1. **The Sisyphus Paradigm** → Every researcher independently tries to discover the full strategy rather than contributing specialized components. Solution: The Meta-Strategy Paradigm — divide tasks into an assembly line of specialized subtasks, measure quality independently at each stage.

2. **Research Through Backtesting** → Using backtests as the primary research tool selects for noise. Solution: Feature Importance Analysis — use MDI (Mean Decrease Impurity) and MDA (Mean Decrease Accuracy) to validate that model predictions are driven by economically meaningful features.

3. **Chronological Sampling** → Using time-based bars creates uneven information density. Solution: The Volume Clock — use volume, dollar, or tick bars that sample markets at information-consistent intervals.

4. **Integer Differentiation** → Making series stationary by taking first differences destroys memory. Solution: Fractional Differentiation — remove only enough non-stationarity to achieve statistical stationarity while preserving as much memory (predictive information) as possible.

5. **Cross-Validation Leakage** → Standard CV leaks information across temporally correlated samples. Solution: Purged K-Fold + Embargo.

6. **Walking Blindly** → Walk-forward produces a single performance path. Solution: CPCV produces a distribution.

7. **Backtest Overfitting** → Multiple testing inflates performance estimates. Solution: Deflated Sharpe Ratio (DSR).

8. **Live Trading Shock** → Live performance consistently worse than backtest due to market impact and costs. Solution: Build realistic transaction cost models before a single live trade.

9. **Research Isolation** → Individual researchers each develop full strategies independently, wasting effort and increasing overfitting. Solution: Collaborative assembly-line research with clear specialization.

10. **Algorithm Aversion** → Abandoning systematic models during drawdowns in favor of discretionary overrides. Solution: Maintain model discipline; reduce size, but do not abandon a theoretically sound strategy at drawdown troughs.

**The meta-strategy paradigm's core insight:**
"Every successful quantitative firm applies the meta-strategy paradigm. Tasks of the assembly line are clearly divided into subtasks. Quality is independently measured and monitored for each subtask. The role of each quant is to specialize in a particular task... Teamwork yields discoveries at a predictable rate, with no reliance on lucky strikes."

This has direct implications for solo operators: the hardest part of systematic trading alone is that you are simultaneously the quant researcher, developer, risk manager, and trader. Each role has different objectives, and their conflicts must be managed explicitly — not by switching hats.

---

### Position Sizing — Full Institutional Framework

The institutional consensus on position sizing synthesizes Kelly Criterion theory, volatility targeting, and regime-adaptive scaling:

**The Kelly-Sharpe relationship:**
Full Kelly fraction: `f* = (μ - r) / σ²`
This can be rewritten as: `f* = SR / σ` where SR is the Sharpe ratio.
A Sharpe of 2.0 (exceptional, rare) implies a Kelly fraction of 2.0/σ — still heavily dependent on volatility.

**Why institutions use Half-Kelly, not Full Kelly:**
- Full Kelly maximizes long-term geometric growth but requires perfectly estimated parameters
- Backtest parameters are systematically overestimated by 30–50% due to data-snooping bias
- Half-Kelly provides ~75% of Full Kelly's long-term growth with approximately 50% of the variance
- Under Half-Kelly, the probability of ruin drops from manageable to near-zero for well-constructed strategies
- AQR and Chan both recommend: "Always halve the expected return estimated from backtests when calculating Kelly fraction"

**Volatility targeting (the institutional standard):**
Rather than computing Kelly directly, most institutional systematic strategies use **volatility targeting**:
1. Set a target annualized portfolio volatility (e.g., 10% or 15%)
2. Scale position size so that the expected contribution to portfolio volatility equals the target
3. As realized volatility increases, automatically reduce position size to maintain the target

This produces the same regime-adaptive sizing that Kelly theoretically recommends, but with more stable and interpretable behavior.

**TRADEZ application:**
The current ATR-based sizing is functionally equivalent to volatility targeting at the individual trade level — it keeps dollar risk per trade constant while allowing ATR to expand and contract. The combination of:
- ATR-based SL (adapts to volatility)
- Fixed 1% risk per trade (dollar risk anchor)
- VIX regime scaling (reduces size in high-VIX regimes)

...is a three-layer volatility-adaptive system that approximates institutional best practice.

---

## Sources

- [JPMorgan Algorithmic Trading Guide (Europe)](https://privatebank.jpmorgan.com/content/dam/jpm-wm-aem/documents/en/other/multi-family-offices/EQ-ETS-Algorithmic-Trading-Guide-(Europe-Markets).pdf)
- [JPMorgan QIS — Trading Insights Podcast](https://www.jpmorgan.com/insights/podcast-hub/market-matters/equities-quantitative-investment-strategies)
- [JPMorgan Macrosynergy Quantamental System (JPMaQS)](https://www.jpmorgan.com/markets/jpmaqs)
- [Lopez de Prado — Probability of Backtest Overfitting (SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253)
- [Lopez de Prado — Building Diversified Portfolios (HRP) (SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2708678)
- [Lopez de Prado — Advances in Financial Machine Learning Notes](https://reasonabledeviations.com/notes/adv_fin_ml/)
- [Purged Cross-Validation — Wikipedia](https://en.wikipedia.org/wiki/Purged_cross-validation)
- [Combinatorial Purged CV — QuantBeckman](https://www.quantbeckman.com/p/with-code-combinatorial-purged-cross)
- [Hierarchical Risk Parity — Wikipedia](https://en.wikipedia.org/wiki/Hierarchical_Risk_Parity)
- [AQR — Value and Momentum Everywhere Dataset](https://www.aqr.com/Insights/Datasets/Value-and-Momentum-Everywhere-Factors-Monthly)
- [AQR — Factor Momentum Everywhere](https://www.aqr.com/Insights/Research/Working-Paper/Factor-Momentum-Everywhere)
- [AQR — Fact, Fiction, and Momentum Investing](https://www.aqr.com/-/media/AQR/Documents/Journal-Articles/JPM-Fact-Fiction-and-Momentum-Investing.pdf)
- [AQR — The Case for Momentum Investing](https://www.aqr.com/-/media/AQR/Documents/Insights/White-Papers/The-Case-for-Momentum-Investing.pdf)
- [AQR — Putting an Academic Factor Into Practice: Momentum](https://spinup-000d1a-wp-offload-media.s3.amazonaws.com/faculty/wp-content/uploads/sites/3/2021/08/Putting-and-Academic-Factor-Into-Practice.pdf)
- [AQR — Trading Costs (Frazzini, Israel, Moskowitz)](https://spinup-000d1a-wp-offload-media.s3.amazonaws.com/faculty/wp-content/uploads/sites/3/2021/08/Trading-Cost.pdf)
- [Man AHL — Trend Following and Drawdowns (Man Group)](https://www.man.com/insights/is-this-time-different)
- [Man AHL — 30 Years (Hedge Fund Journal)](https://thehedgefundjournal.com/man-ahl-marks-30-years/)
- [Man AHL — AHL Evolution (Hedge Fund Journal)](https://thehedgefundjournal.com/ahl-evolution/)
- [Two Sigma — Introducing the Factor Lens](https://www.twosigma.com/wp-content/uploads/Introducing-the-Two-Sigma-Factor-Lens.10.18.pdf)
- [Two Sigma — Investment Management](https://www.twosigma.com/businesses/investment-management/)
- [Two Sigma — Factor Investing & Analysis Guide (Venn)](https://www.venn.twosigma.com/resources/factor-investing-analysis)
- [Former Two Sigma Quant on AI and Alpha (MenthorQ)](https://menthorq.com/guide/a-former-two-sigma-quant-on-ai-and-alpha/)
- [Goldman Sachs Electronic Trading (GSET)](https://www.goldmansachs.com/what-we-do/ficc-and-equities/gset-equities)
- [Goldman Sachs Launches AXIS on Atlas Platform](https://www.thetradenews.com/goldman-sachs-launches-first-algorithm-axis-on-new-atlas-trading-platform/)
- [Goldman Sachs — Liquidity, Volatility, Fragility (GSAM)](https://www.gsam.com/content/dam/gsam/pdfs/sg/en/commentary/GS_Top%20of%20Mind_June.pdf)
- [Renaissance Technologies — Wikipedia](https://en.wikipedia.org/wiki/Renaissance_Technologies)
- [Jim Simons' Trading Strategies — QuantifiedStrategies](https://www.quantifiedstrategies.com/jim-simons/)
- [Renaissance Technologies Breakdown — Daniel Scrivner](https://www.danielscrivner.com/renaissance-technologies-business-breakdown/)
- [Ernest Chan — Quantitative Trading (2nd Ed.) on O'Reilly](https://www.oreilly.com/library/view/quantitative-trading-2nd/9781119800064/)
- [QuantConnect — Research Guide Documentation](https://www.quantconnect.com/docs/v2/cloud-platform/backtesting/research-guide)
- [QuantConnect — Backtesting Documentation](https://www.quantconnect.com/docs/v2/cloud-platform/backtesting)
- [CFA Institute — Introduction to Risk Management (2025)](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2025/introduction-risk-management)
- [CFA Institute — Maximum Drawdown and Portfolio Strategy](https://blogs.cfainstitute.org/investor/2013/02/12/sculpting-investment-portfolios-maximum-drawdown-and-optimal-portfolio-strategy/)
- [CFA Institute — Practical Guide to Risk Management](https://rpc.cfainstitute.org/sites/default/files/-/media/documents/book/rf-publication/2011/rf-v2011-n3-1-pdf.pdf)
- [FIA — Automated Trading Risk Controls Best Practices (2024)](https://www.fia.org/sites/default/files/2024-07/FIA_WP_AUTOMATED%20TRADING%20RISK%20CONTROLS_FINAL_0.pdf)
- [Kelly Criterion — Sizing the Risk: Kelly, VIX, and Hybrid (arXiv 2025)](https://arxiv.org/html/2508.16598v1)
- [Quantitative Brokers — Transaction Cost Analytics](https://www.quantitativebrokers.com/transaction-cost-analytics)
- [Systematic Strategies & Quant Trading 2025 (Gresham)](https://www.greshamllc.com/media/kycp0t30/systematic-report_0525_v1b.pdf)
- [Backtest Overfitting in the ML Era (ScienceDirect 2024)](https://www.sciencedirect.com/science/article/abs/pii/S0950705124011110)
- [Why Live Trading Underperforms Backtests — Quant Nomad](https://quantnomad.com/why-your-live-trading-is-so-much-worse-than-your-backtests/)
- [Futures Risk Management: 6 Tactical Rules (Insignia Futures)](https://insigniafutures.com/futures-risk-management-6-tactical-rules/)
- [BIS — FX Execution Algorithms and Market Functioning](https://www.bis.org/publ/mktc13.pdf)
- [Lopez de Prado — 10 Reasons Most Machine Learning Funds Fail (SSRN 3104816)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3104816)
- [Lopez de Prado — 10 Reasons Most ML Funds Fail (GARP White Paper)](https://www.garp.org/hubfs/Whitepapers/a1Z1W0000054x6lUAA.pdf)
- [Purged Cross-Validation — Wikipedia](https://en.wikipedia.org/wiki/Purged_cross-validation)
- [Deflated Sharpe Ratio: Correcting for Selection Bias (SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551)
- [Probability of Backtest Overfitting (SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253)
- [AQR — Fact, Fiction, and Momentum Investing (2014)](https://www.aqr.com/-/media/AQR/Documents/Journal-Articles/JPM-Fact-Fiction-and-Momentum-Investing.pdf)
- [AQR — Fact, Fiction, and Factor Investing (2023)](https://www.aqr.com/-/media/AQR/Documents/Journal-Articles/AQRJPMQuant23FactFictionandFactorInvesting.pdf)
- [AQR — Value and Momentum Everywhere Factors Dataset](https://www.aqr.com/Insights/Datasets/Value-and-Momentum-Everywhere-Factors-Monthly)
- [Man AHL — Trend Following and Drawdowns: Is This Time Different?](https://www.man.com/insights/is-this-time-different)
- [Man AHL — Trend Following Research Hub](https://www.man.com/trend-following)
- [Man AHL — 30 Years (Hedge Fund Journal)](https://thehedgefundjournal.com/man-ahl-marks-30-years/)
- [Man AHL — Need for Speed in Trend-Following (HedgeNordic)](https://hedgenordic.com/2023/03/the-need-for-speed-in-trend-following-strategies/)
- [Goldman Sachs — Systematic Trading Strategies](https://www.goldmansachs.com/what-we-do/ficc-and-equities/systematic-trading-strategies)
- [Goldman Sachs — How Quant Strategies Drive Alpha Enhanced Approach](https://am.gs.com/en-cz/institutions/insights/article/2025/how-quant-strategies-drive-the-alpha-enhanced-approach-to-equity-investing)
- [Goldman Sachs — How Generative AI is Changing Systematic Investing](https://www.goldmansachs.com/insights/articles/how-generative-ai-tools-are-changing-systematic-investing)
- [Goldman Sachs — GS Quant Platform](https://marquee.gs.com/welcome/our-platform/gs-quant)
- [Renaissance Technologies — Wikipedia](https://en.wikipedia.org/wiki/Renaissance_Technologies)
- [Renaissance Technologies — Why the Medallion Fund is the Greatest Money-Making Machine](https://ofdollarsanddata.com/medallion-fund/)
- [Renaissance Technologies — Business Breakdown (Daniel Scrivner)](https://www.danielscrivner.com/renaissance-technologies-business-breakdown/)
- [Renaissance Technologies — Statistical Arbitrage ($100B) Analysis](https://navnoorbawa.substack.com/p/renaissance-technologies-the-100)
- [Two Sigma — Former Quant on AI and Alpha (MenthorQ)](https://menthorq.com/guide/a-former-two-sigma-quant-on-ai-and-alpha/)
- [Two Sigma — Inside Two Sigma (Institutional Investor)](https://www.institutionalinvestor.com/article/2bsw4ehe37jv5y886qtxc/corner-office/inside-the-geeky-quirky-and-wildly-successful-world-of-quant-shop-two-sigma)
- [CFA Institute — Trade Strategy and Execution (2025)](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2025/trade-strategy-execution)
- [CFA Institute — Electronic Trading Risks (AnalystPrep)](https://analystprep.com/study-notes/cfa-level-iii/electronic-trading-risks/)
- [QuantConnect — Realistic Expectations in Algo Trading (Community)](https://www.quantconnect.com/forum/discussion/5720/realistic-expectations-in-algo-trading/)
- [QuantConnect Review — LuxAlgo](https://www.luxalgo.com/blog/quantconnect-review-best-platform-for-algo-trading-2/)
- [When Do Systematic Strategies Decay? (Quantitative Finance, 2022)](https://www.tandfonline.com/doi/full/10.1080/14697688.2022.2098810)
- [When Trading Systems Break Down — Harbourfronts](https://blog.harbourfronts.com/2025/09/22/when-trading-systems-break-down-causes-of-decay-and-stop-criteria/)
- [Alpha Decay: What Does It Look Like? (Maven Securities)](https://www.mavensecurities.com/alpha-decay-what-does-it-look-like-and-what-does-it-mean-for-systematic-traders/)
- [Walk-Forward Optimization vs. Traditional Backtesting (QuantStrategy.io)](https://quantstrategy.io/blog/walk-forward-optimization-vs-traditional-backtesting-which/)
- [Walk-Forward Analysis: Three Validation Approaches (Medium)](https://medium.com/@NFS303/walk-forward-analysis-a-production-ready-comparison-of-three-validation-approaches-69cd25fc9fc7)
- [Backtest Overfitting in the ML Era (ScienceDirect, 2024)](https://www.sciencedirect.com/science/article/abs/pii/S0950705124011110)
- [Kelly Criterion — QuantStart](https://www.quantstart.com/articles/Money-Management-via-the-Kelly-Criterion/)
- [Kelly Criterion Applications (QuantConnect Research)](https://www.quantconnect.com/research/18312/kelly-criterion-applications-in-trading-systems/)
- [Sizing the Risk: Kelly, VIX, and Hybrid Approaches (arXiv 2025)](https://arxiv.org/pdf/2508.16598)
- [Cliff Asness — Factor Investing and History of Financial Economics (Hoover Institution)](https://www.hoover.org/research/cliff-asness-factor-investing-and-history-financial-economics)
- [JPMorgan — Machine Learning Execution and Dark Pool Economics (Medium)](https://medium.com/@navnoorbawa/jpmorgans-29-8b-trading-operation-machine-learning-execution-c6527a679518)
- [Man AHL — Inside the $168B Systematic Fund (Substack)](https://navnoorbawa.substack.com/p/inside-the-168b-systematic-fund-making)
- [JPMorgan — Systematic Strategies Across Asset Classes (CME, 2013)](https://www.cmegroup.com/education/files/jpm-systematic-strategies-2013-12-11-1277971.pdf)
- [Quant Fund Strategies Explained (Aurum)](https://www.aurum.com/insight/thought-piece/quant-hedge-fund-strategies-explained/)
- [Simple vs. Advanced Systematic Trading Strategies (QuantStart)](https://www.quantstart.com/articles/simple-versus-advanced-systematic-trading-strategies-which-is-better/)
