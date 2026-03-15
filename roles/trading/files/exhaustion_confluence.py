#!/usr/bin/env python3
"""ATLAS Exhaustion Confluence Strategy — Backtrader Implementation.

Combines three exhaustion pattern triggers with four confluence filters
into a scored reversal trading system for SPY on daily timeframe.

TRIGGERS (any one fires = candidate signal):
  1. Extension Candle: Body > 2x avg(body, lookback) after uptrend
  2. Volume Exhaustion: Higher high + lower volume (bearish divergence)
  3. Large Wick: Upper wick > 2x body size

CONFLUENCE FILTERS (each adds +1 to score):
  1. Candlestick pattern fired (the trigger itself)
  2. Price near a Moving Average (SMA 20/50/100/200)
  3. Price near a Round Number ($10 increments)
  4. Volume Profile Node (high-volume price cluster in lookback)

ENTRY: Score >= min_confluence (default 3) triggers SHORT entry.
EXIT:  Stop above pattern high, target at nearest volume node below or 2:1 R:R.
POSITION SIZING: Fixed fractional risk (default 2% of equity).
"""

import backtrader as bt
import numpy as np
from collections import defaultdict


class ExhaustionConfluence(bt.Strategy):
    params = (
        # Pattern detection
        ('body_lookback', 10),          # Bars for avg body size
        ('extension_mult', 2.0),        # Body must be > mult * avg
        ('wick_body_ratio', 2.0),       # Upper wick must be > ratio * body
        ('trend_lookback', 5),          # Bars to confirm prior uptrend
        ('vol_div_lookback', 3),        # Bars to check volume divergence

        # Volume profile
        ('vp_lookback', 100),           # Bars for volume profile calculation
        ('vp_bins', 50),                # Price bins for volume profile
        ('vp_node_percentile', 80),     # Percentile threshold for "high volume node"

        # Moving averages
        ('ma_periods', [20, 50, 100, 200]),  # MA periods to check
        ('ma_proximity_pct', 0.5),      # Within X% of MA counts as "at MA"

        # Round numbers
        ('round_interval', 10),         # Check multiples of this ($10, $50, etc.)
        ('round_proximity_pct', 0.3),   # Within X% of round number

        # Confluence & entry
        ('min_confluence', 3),          # Minimum score to enter (1-4 scale)
        ('confirmation_bars', 1),       # Wait N bars after signal for confirmation

        # Risk management
        ('risk_pct', 0.02),             # Risk per trade as fraction of equity
        ('reward_ratio', 2.0),          # Reward:risk ratio for take profit
        ('max_hold_bars', 15),          # Maximum bars to hold a position
        ('trail_after_1r', True),       # Trail stop after 1R profit reached

        # Account
        ('account_size', 25000),        # Reference account size
    )

    def __init__(self):
        self.order = None
        self.entry_price = None
        self.stop_price = None
        self.target_price = None
        self.entry_bar = 0
        self.signal_bar = -1
        self.signal_score = 0
        self.signal_details = {}
        self.bars_since_entry = 0
        self.one_r_reached = False

        # Pre-compute MAs
        self.mas = {}
        for p in self.p.ma_periods:
            if p <= len(self.data):
                self.mas[p] = bt.indicators.SMA(self.data.close, period=p)

        # Track trade log for analysis
        self.trade_log = []

    def log(self, txt):
        dt = self.data.datetime.datetime(0)
        print(f'{dt.strftime("%Y-%m-%d")} | {txt}')

    # ── Pattern Detection ──────────────────────────────────────────────

    def _body_size(self, ago=0):
        return abs(self.data.close[ago] - self.data.open[ago])

    def _upper_wick(self, ago=0):
        return self.data.high[ago] - max(self.data.open[ago], self.data.close[ago])

    def _lower_wick(self, ago=0):
        return min(self.data.open[ago], self.data.close[ago]) - self.data.low[ago]

    def _is_bullish(self, ago=0):
        return self.data.close[ago] > self.data.open[ago]

    def _avg_body(self):
        """Average body size over lookback period."""
        bodies = []
        for i in range(-self.p.body_lookback, 0):
            try:
                bodies.append(self._body_size(i))
            except IndexError:
                pass
        return np.mean(bodies) if bodies else 0

    def _is_uptrend(self):
        """Check if price has been trending up over trend_lookback bars."""
        try:
            for i in range(-self.p.trend_lookback, 0):
                if self.data.close[i] <= self.data.close[i - 1]:
                    return False
            return True
        except IndexError:
            return False

    def _check_extension_candle(self):
        """Trigger 1: Current candle body > extension_mult * avg body, after uptrend."""
        avg_body = self._avg_body()
        if avg_body <= 0:
            return False, 0

        current_body = self._body_size(0)
        ratio = current_body / avg_body

        # Must be bullish extension after uptrend (blow-off top)
        if ratio >= self.p.extension_mult and self._is_bullish(0):
            # Check for prior uptrend (at least trend_lookback higher closes)
            higher_closes = sum(
                1 for i in range(-self.p.trend_lookback, 0)
                if self.data.close[i] > self.data.close[i - 1]
            )
            if higher_closes >= self.p.trend_lookback - 1:
                return True, ratio
        return False, 0

    def _check_volume_exhaustion(self):
        """Trigger 2: Price making higher highs but volume declining."""
        try:
            higher_highs = 0
            lower_volume = 0
            for i in range(-self.p.vol_div_lookback, 0):
                if self.data.high[i + 1] > self.data.high[i]:
                    higher_highs += 1
                if self.data.volume[i + 1] < self.data.volume[i]:
                    lower_volume += 1

            # Current bar also higher high + lower volume
            if (self.data.high[0] > self.data.high[-1] and
                    self.data.volume[0] < self.data.volume[-1]):
                higher_highs += 1
                lower_volume += 1

            # Need consistent divergence
            total_checks = self.p.vol_div_lookback
            if higher_highs >= total_checks and lower_volume >= total_checks:
                return True, lower_volume
        except IndexError:
            pass
        return False, 0

    def _check_large_wick(self):
        """Trigger 3: Upper wick > wick_body_ratio * body size."""
        body = self._body_size(0)
        upper_wick = self._upper_wick(0)

        if body <= 0:
            # Doji — treat entire range as wick
            body = 0.01  # Avoid division by zero

        ratio = upper_wick / body
        if ratio >= self.p.wick_body_ratio and upper_wick > 0:
            return True, ratio
        return False, 0

    # ── Confluence Filters ─────────────────────────────────────────────

    def _check_near_ma(self):
        """Filter: Price within ma_proximity_pct of any SMA."""
        price = self.data.close[0]
        hits = []
        for period, ma in self.mas.items():
            try:
                ma_val = ma[0]
                if ma_val > 0:
                    distance_pct = abs(price - ma_val) / ma_val * 100
                    if distance_pct <= self.p.ma_proximity_pct:
                        hits.append((period, ma_val, distance_pct))
            except IndexError:
                pass
        return len(hits) > 0, hits

    def _check_round_number(self):
        """Filter: Price within round_proximity_pct of a round number."""
        price = self.data.close[0]
        interval = self.p.round_interval
        nearest_round = round(price / interval) * interval
        distance_pct = abs(price - nearest_round) / price * 100
        return distance_pct <= self.p.round_proximity_pct, nearest_round

    def _compute_volume_profile(self):
        """Filter: Check if price is at a High Volume Node.

        Builds a volume-by-price histogram over vp_lookback bars,
        identifies High Volume Nodes (bins above the vp_node_percentile),
        and checks if current price is in one of those bins.

        Returns:
            (bool, list): Whether at HVN, and list of all HVN price levels
        """
        lookback = min(self.p.vp_lookback, len(self.data))
        if lookback < 20:
            return False, []

        # Collect all price ranges and volumes
        prices = []
        volumes = []
        for i in range(-lookback, 1):
            try:
                prices.append((self.data.low[i], self.data.high[i]))
                volumes.append(self.data.volume[i] if self.data.volume[i] > 0 else 1)
            except IndexError:
                pass

        if not prices:
            return False, []

        # Build histogram
        price_min = min(p[0] for p in prices)
        price_max = max(p[1] for p in prices)
        if price_max <= price_min:
            return False, []

        bin_size = (price_max - price_min) / self.p.vp_bins
        if bin_size <= 0:
            return False, []

        vol_by_bin = defaultdict(float)
        for (low, high), vol in zip(prices, volumes):
            # Distribute volume across bins the bar spans
            low_bin = int((low - price_min) / bin_size)
            high_bin = int((high - price_min) / bin_size)
            low_bin = max(0, min(low_bin, self.p.vp_bins - 1))
            high_bin = max(0, min(high_bin, self.p.vp_bins - 1))
            bins_spanned = max(1, high_bin - low_bin + 1)
            vol_per_bin = vol / bins_spanned
            for b in range(low_bin, high_bin + 1):
                vol_by_bin[b] += vol_per_bin

        if not vol_by_bin:
            return False, []

        # Find HVN threshold
        all_vols = list(vol_by_bin.values())
        threshold = np.percentile(all_vols, self.p.vp_node_percentile)

        # Get HVN price levels
        hvn_levels = []
        for b, v in vol_by_bin.items():
            if v >= threshold:
                level = price_min + (b + 0.5) * bin_size
                hvn_levels.append(level)

        # Check if current price is at an HVN
        current_price = self.data.close[0]
        at_hvn = False
        for level in hvn_levels:
            if abs(current_price - level) <= bin_size:
                at_hvn = True
                break

        return at_hvn, sorted(hvn_levels)

    # ── Score & Signal ─────────────────────────────────────────────────

    def _evaluate_signal(self):
        """Compute confluence score. Returns (score, details_dict)."""
        score = 0
        details = {
            'triggers': [],
            'filters': [],
            'pattern_high': self.data.high[0],
        }

        # Check triggers (any trigger = +1 point)
        ext_hit, ext_ratio = self._check_extension_candle()
        if ext_hit:
            details['triggers'].append(f'Extension({ext_ratio:.1f}x avg)')
            score += 1

        vol_hit, vol_count = self._check_volume_exhaustion()
        if vol_hit:
            details['triggers'].append(f'VolExhaustion({vol_count} bars)')
            score += 1

        wick_hit, wick_ratio = self._check_large_wick()
        if wick_hit:
            details['triggers'].append(f'LargeWick({wick_ratio:.1f}x body)')
            score += 1

        # No trigger fired = no signal
        if score == 0:
            return 0, details

        # Cap trigger contribution to 1 point (pattern category)
        # Multiple triggers = stronger but still 1 point for "pattern"
        pattern_score = 1
        score = pattern_score

        # Check filters
        ma_hit, ma_details = self._check_near_ma()
        if ma_hit:
            periods = [str(h[0]) for h in ma_details]
            details['filters'].append(f'NearMA({",".join(periods)})')
            score += 1

        round_hit, round_level = self._check_round_number()
        if round_hit:
            details['filters'].append(f'RoundNum(${round_level:.0f})')
            score += 1

        hvn_hit, hvn_levels = self._compute_volume_profile()
        if hvn_hit:
            details['filters'].append(f'VolNode')
            score += 1
            # Store HVN levels below price for target calculation
            current = self.data.close[0]
            below = [l for l in hvn_levels if l < current]
            if below:
                details['nearest_hvn_below'] = max(below)

        details['total_score'] = score
        details['trigger_count'] = len(details['triggers'])
        return score, details

    # ── Position Sizing ────────────────────────────────────────────────

    def _calc_position_size(self, entry_price, stop_price):
        """Fixed fractional position sizing based on risk per trade."""
        risk_per_share = abs(entry_price - stop_price)
        if risk_per_share <= 0:
            return 0

        equity = self.broker.getvalue()
        risk_dollars = equity * self.p.risk_pct
        shares = int(risk_dollars / risk_per_share)

        # Ensure we can afford the position
        max_shares = int(equity * 0.95 / entry_price)  # Use max 95% of equity
        shares = min(shares, max_shares)

        return max(shares, 0)

    # ── Order Management ───────────────────────────────────────────────

    def notify_order(self, order):
        if order.status in [order.Completed]:
            if order.issell():
                self.entry_price = order.executed.price
                self.entry_bar = len(self)
                self.bars_since_entry = 0
                self.one_r_reached = False
                self.log(f'SHORT ENTRY @ ${order.executed.price:.2f} | '
                         f'Size={order.executed.size} | '
                         f'Stop=${self.stop_price:.2f} | '
                         f'Target=${self.target_price:.2f} | '
                         f'Score={self.signal_score}')
            elif order.isbuy():
                self.log(f'COVER @ ${order.executed.price:.2f} | '
                         f'PnL=${(self.entry_price - order.executed.price) * abs(order.executed.size):.2f}')
                self.entry_price = None
                self.stop_price = None
                self.target_price = None

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'Order {order.Status[order.status]}')

        self.order = None

    def notify_trade(self, trade):
        if trade.isclosed:
            self.log(f'TRADE CLOSED | Gross={trade.pnl:.2f} | Net={trade.pnlcomm:.2f}')

    # ── Core Logic ─────────────────────────────────────────────────────

    def next(self):
        if self.order:
            return

        # Need enough bars for longest MA
        max_ma = max(self.p.ma_periods) if self.p.ma_periods else 200
        if len(self.data) < max(max_ma, self.p.vp_lookback):
            return

        if not self.position:
            # ── LOOK FOR ENTRY ──
            score, details = self._evaluate_signal()

            if score >= self.p.min_confluence:
                if self.p.confirmation_bars > 0 and self.signal_bar < 0:
                    # First signal — wait for confirmation
                    self.signal_bar = len(self)
                    self.signal_score = score
                    self.signal_details = details
                    self.log(f'SIGNAL DETECTED (score={score}) — waiting {self.p.confirmation_bars} bar(s) confirmation')
                    self.log(f'  Triggers: {", ".join(details["triggers"])}')
                    self.log(f'  Filters:  {", ".join(details["filters"])}')
                    return

                if self.signal_bar > 0:
                    bars_waited = len(self) - self.signal_bar
                    if bars_waited < self.p.confirmation_bars:
                        return  # Still waiting

                    # Confirmation: next bar must not make new high
                    if self.data.high[0] > self.signal_details['pattern_high']:
                        self.log('SIGNAL INVALIDATED — new high made')
                        self.signal_bar = -1
                        return

                    # Use stored signal details
                    score = self.signal_score
                    details = self.signal_details

                # Calculate stops and targets
                pattern_high = details.get('pattern_high', self.data.high[0])
                stop_buffer = pattern_high * 0.002  # 0.2% above pattern high
                stop = pattern_high + stop_buffer
                entry = self.data.close[0]
                risk = stop - entry

                # Target: nearest HVN below, or reward_ratio * risk
                hvn_below = details.get('nearest_hvn_below')
                if hvn_below and (entry - hvn_below) > risk * 1.5:
                    target = hvn_below
                else:
                    target = entry - (risk * self.p.reward_ratio)

                size = self._calc_position_size(entry, stop)
                if size <= 0:
                    self.log('SKIP — position size too small')
                    self.signal_bar = -1
                    return

                self.stop_price = stop
                self.target_price = target
                self.signal_score = score
                self.order = self.sell(size=size)
                self.signal_bar = -1

        else:
            # ── MANAGE POSITION ──
            self.bars_since_entry += 1

            # Stop loss
            if self.data.high[0] >= self.stop_price:
                self.log(f'STOP HIT @ ${self.stop_price:.2f}')
                self.order = self.close()
                return

            # Take profit
            if self.data.low[0] <= self.target_price:
                self.log(f'TARGET HIT @ ${self.target_price:.2f}')
                self.order = self.close()
                return

            # Check 1R profit for trailing stop
            if self.p.trail_after_1r and self.entry_price:
                risk = self.stop_price - self.entry_price
                current_profit = self.entry_price - self.data.close[0]
                if current_profit >= risk and not self.one_r_reached:
                    self.one_r_reached = True
                    self.stop_price = self.entry_price  # Move to breakeven
                    self.log(f'1R REACHED — stop moved to breakeven ${self.entry_price:.2f}')
                elif self.one_r_reached:
                    # Trail: move stop to lock in profit
                    new_stop = self.data.close[0] + risk * 0.5
                    if new_stop < self.stop_price:
                        self.stop_price = new_stop

            # Time exit
            if self.bars_since_entry >= self.p.max_hold_bars:
                self.log(f'TIME EXIT after {self.bars_since_entry} bars')
                self.order = self.close()
                return


class ExhaustionConfluenceLong(ExhaustionConfluence):
    """Mirror strategy for exhaustion at bottoms (LONG entries).

    Same logic inverted:
    - Extension candle: large bearish candle after downtrend
    - Volume exhaustion: lower lows + declining volume
    - Large wick: lower wick > 2x body (hammer pattern)
    """

    def _check_extension_candle(self):
        avg_body = self._avg_body()
        if avg_body <= 0:
            return False, 0

        current_body = self._body_size(0)
        ratio = current_body / avg_body

        # Must be bearish extension after downtrend (capitulation)
        if ratio >= self.p.extension_mult and not self._is_bullish(0):
            lower_closes = sum(
                1 for i in range(-self.p.trend_lookback, 0)
                if self.data.close[i] < self.data.close[i - 1]
            )
            if lower_closes >= self.p.trend_lookback - 1:
                return True, ratio
        return False, 0

    def _check_volume_exhaustion(self):
        try:
            lower_lows = 0
            lower_volume = 0
            for i in range(-self.p.vol_div_lookback, 0):
                if self.data.low[i + 1] < self.data.low[i]:
                    lower_lows += 1
                if self.data.volume[i + 1] < self.data.volume[i]:
                    lower_volume += 1

            if (self.data.low[0] < self.data.low[-1] and
                    self.data.volume[0] < self.data.volume[-1]):
                lower_lows += 1
                lower_volume += 1

            total_checks = self.p.vol_div_lookback
            if lower_lows >= total_checks and lower_volume >= total_checks:
                return True, lower_volume
        except IndexError:
            pass
        return False, 0

    def _check_large_wick(self):
        body = self._body_size(0)
        lower_wick = self._lower_wick(0)

        if body <= 0:
            body = 0.01

        ratio = lower_wick / body
        if ratio >= self.p.wick_body_ratio and lower_wick > 0:
            return True, ratio
        return False, 0

    def _evaluate_signal(self):
        score, details = super()._evaluate_signal()
        details['pattern_low'] = self.data.low[0]
        return score, details

    def next(self):
        if self.order:
            return

        max_ma = max(self.p.ma_periods) if self.p.ma_periods else 200
        if len(self.data) < max(max_ma, self.p.vp_lookback):
            return

        if not self.position:
            score, details = self._evaluate_signal()

            if score >= self.p.min_confluence:
                if self.p.confirmation_bars > 0 and self.signal_bar < 0:
                    self.signal_bar = len(self)
                    self.signal_score = score
                    self.signal_details = details
                    return

                if self.signal_bar > 0:
                    bars_waited = len(self) - self.signal_bar
                    if bars_waited < self.p.confirmation_bars:
                        return

                    if self.data.low[0] < self.signal_details.get('pattern_low', self.data.low[0]):
                        self.signal_bar = -1
                        return

                    score = self.signal_score
                    details = self.signal_details

                pattern_low = details.get('pattern_low', self.data.low[0])
                stop_buffer = pattern_low * 0.002
                stop = pattern_low - stop_buffer
                entry = self.data.close[0]
                risk = entry - stop

                hvn_above = None
                _, hvn_levels = self._compute_volume_profile()
                above = [l for l in hvn_levels if l > entry]
                if above:
                    hvn_above = min(above)

                if hvn_above and (hvn_above - entry) > risk * 1.5:
                    target = hvn_above
                else:
                    target = entry + (risk * self.p.reward_ratio)

                size = self._calc_position_size(entry, stop)
                if size <= 0:
                    self.signal_bar = -1
                    return

                self.stop_price = stop
                self.target_price = target
                self.signal_score = score
                self.order = self.buy(size=size)
                self.signal_bar = -1

        else:
            self.bars_since_entry += 1

            if self.data.low[0] <= self.stop_price:
                self.order = self.close()
                return

            if self.data.high[0] >= self.target_price:
                self.order = self.close()
                return

            if self.p.trail_after_1r and self.entry_price:
                risk = self.entry_price - self.stop_price
                current_profit = self.data.close[0] - self.entry_price
                if current_profit >= risk and not self.one_r_reached:
                    self.one_r_reached = True
                    self.stop_price = self.entry_price
                elif self.one_r_reached:
                    new_stop = self.data.close[0] - risk * 0.5
                    if new_stop > self.stop_price:
                        self.stop_price = new_stop

            if self.bars_since_entry >= self.p.max_hold_bars:
                self.order = self.close()
                return

    def notify_order(self, order):
        if order.status in [order.Completed]:
            if order.isbuy() and not self.entry_price:
                self.entry_price = order.executed.price
                self.entry_bar = len(self)
                self.bars_since_entry = 0
                self.one_r_reached = False
                self.log(f'LONG ENTRY @ ${order.executed.price:.2f} | '
                         f'Size={order.executed.size} | '
                         f'Stop=${self.stop_price:.2f} | '
                         f'Target=${self.target_price:.2f} | '
                         f'Score={self.signal_score}')
            elif order.issell():
                self.log(f'EXIT @ ${order.executed.price:.2f} | '
                         f'PnL=${(order.executed.price - self.entry_price) * abs(order.executed.size):.2f}')
                self.entry_price = None
                self.stop_price = None
                self.target_price = None

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'Order {order.Status[order.status]}')

        self.order = None
