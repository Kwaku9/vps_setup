#!/usr/bin/env python3
"""ATLAS Exhaustion Confluence Strategy v2B — Bidirectional.

Same logic as V2 (regime-filtered exhaustion confluence) with the addition
of mirror-image LONG signals for capitulation exhaustion.  All parameters,
thresholds, and scoring are identical to V2.  The only new logic is the
symmetric detection of bearish extension candles, lower-low volume divergence,
large lower wicks, and a bullish regime gate.
"""

import backtrader as bt
import numpy as np
from collections import defaultdict


class ExhaustionConfluenceV2B(bt.Strategy):
    params = (
        # Pattern detection
        ('body_lookback', 10),
        ('extension_mult', 2.0),
        ('wick_body_ratio', 2.0),
        ('trend_lookback', 5),
        ('vol_div_lookback', 3),

        # Volume profile — tighter than v1
        ('vp_lookback', 200),
        ('vp_bins', 50),
        ('vp_node_percentile', 90),

        # Moving averages
        ('ma_periods', [20, 50, 100, 200]),
        ('ma_proximity_pct', 0.5),

        # Round numbers
        ('round_interval', 10),
        ('round_proximity_pct', 0.3),

        # Regime filters
        ('regime_sma', 50),
        ('rsi_period', 14),
        ('rsi_overbought', 70),
        ('rsi_oversold', 30),
        ('atr_period', 14),
        ('atr_stop_mult', 2.0),

        # Confluence & entry
        ('min_confluence', 3),
        ('confirmation_bars', 1),
        ('max_confirmation_wait', 5),

        # Risk management
        ('risk_pct', 0.02),
        ('reward_ratio', 2.5),
        ('max_hold_bars', 20),
        ('trail_after_1r', True),
        ('cooldown_bars', 3),
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
        self.last_exit_bar = -999
        self.trade_direction = None  # 'long' or 'short'

        # Indicators
        self.mas = {}
        for p in self.p.ma_periods:
            self.mas[p] = bt.indicators.SMA(self.data.close, period=p)

        self.regime_sma = bt.indicators.SMA(self.data.close, period=self.p.regime_sma)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)

    def log(self, txt):
        dt = self.data.datetime.datetime(0)
        print(f'{dt.strftime("%Y-%m-%d")} | {txt}')

    # ── Pattern Detection ─────────────────────────────────────────────

    def _body_size(self, ago=0):
        return abs(self.data.close[ago] - self.data.open[ago])

    def _upper_wick(self, ago=0):
        return self.data.high[ago] - max(self.data.open[ago], self.data.close[ago])

    def _lower_wick(self, ago=0):
        return min(self.data.open[ago], self.data.close[ago]) - self.data.low[ago]

    def _is_bullish(self, ago=0):
        return self.data.close[ago] > self.data.open[ago]

    def _is_bearish(self, ago=0):
        return self.data.close[ago] < self.data.open[ago]

    def _avg_body(self):
        bodies = []
        for i in range(-self.p.body_lookback, 0):
            try:
                bodies.append(self._body_size(i))
            except IndexError:
                pass
        return np.mean(bodies) if bodies else 0

    def _check_extension_candle(self, direction):
        """Check for extension candle in given direction.

        SHORT: large bullish body after uptrend.
        LONG:  large bearish body after downtrend.
        """
        avg_body = self._avg_body()
        if avg_body <= 0:
            return False, 0
        current_body = self._body_size(0)
        ratio = current_body / avg_body

        if ratio < self.p.extension_mult:
            return False, 0

        if direction == 'short':
            if not self._is_bullish(0):
                return False, 0
            # Uptrend: higher closes
            higher_closes = sum(
                1 for i in range(-self.p.trend_lookback, 0)
                if self.data.close[i] > self.data.close[i - 1]
            )
            if higher_closes >= self.p.trend_lookback - 1:
                return True, ratio
        else:  # long
            if not self._is_bearish(0):
                return False, 0
            # Downtrend: lower closes
            lower_closes = sum(
                1 for i in range(-self.p.trend_lookback, 0)
                if self.data.close[i] < self.data.close[i - 1]
            )
            if lower_closes >= self.p.trend_lookback - 1:
                return True, ratio

        return False, 0

    def _check_volume_exhaustion(self, direction):
        """Check for volume exhaustion divergence.

        SHORT: higher highs + lower volume.
        LONG:  lower lows + lower volume.
        """
        try:
            price_trend = 0
            lower_volume = 0
            for i in range(-self.p.vol_div_lookback, 0):
                if direction == 'short':
                    if self.data.high[i + 1] > self.data.high[i]:
                        price_trend += 1
                else:  # long
                    if self.data.low[i + 1] < self.data.low[i]:
                        price_trend += 1
                if self.data.volume[i + 1] < self.data.volume[i]:
                    lower_volume += 1

            # Check current bar
            if direction == 'short':
                if (self.data.high[0] > self.data.high[-1] and
                        self.data.volume[0] < self.data.volume[-1]):
                    price_trend += 1
                    lower_volume += 1
            else:  # long
                if (self.data.low[0] < self.data.low[-1] and
                        self.data.volume[0] < self.data.volume[-1]):
                    price_trend += 1
                    lower_volume += 1

            total_checks = self.p.vol_div_lookback
            if price_trend >= total_checks and lower_volume >= total_checks:
                return True, lower_volume
        except IndexError:
            pass
        return False, 0

    def _check_large_wick(self, direction):
        """Check for large wick rejection.

        SHORT: large upper wick (buying exhaustion).
        LONG:  large lower wick (selling exhaustion).
        """
        body = self._body_size(0)
        if body <= 0:
            body = 0.01

        if direction == 'short':
            wick = self._upper_wick(0)
        else:  # long
            wick = self._lower_wick(0)

        ratio = wick / body
        if ratio >= self.p.wick_body_ratio and wick > 0:
            return True, ratio
        return False, 0

    # ── Confluence Filters ─────────────────────────────────────────────

    def _check_near_ma(self):
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
        price = self.data.close[0]
        interval = self.p.round_interval
        nearest_round = round(price / interval) * interval
        distance_pct = abs(price - nearest_round) / price * 100
        return distance_pct <= self.p.round_proximity_pct, nearest_round

    def _compute_volume_profile(self):
        lookback = min(self.p.vp_lookback, len(self.data))
        if lookback < 20:
            return False, []

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

        price_min = min(p[0] for p in prices)
        price_max = max(p[1] for p in prices)
        if price_max <= price_min:
            return False, []

        bin_size = (price_max - price_min) / self.p.vp_bins
        if bin_size <= 0:
            return False, []

        vol_by_bin = defaultdict(float)
        for (low, high), vol in zip(prices, volumes):
            low_bin = max(0, min(int((low - price_min) / bin_size), self.p.vp_bins - 1))
            high_bin = max(0, min(int((high - price_min) / bin_size), self.p.vp_bins - 1))
            bins_spanned = max(1, high_bin - low_bin + 1)
            vol_per_bin = vol / bins_spanned
            for b in range(low_bin, high_bin + 1):
                vol_by_bin[b] += vol_per_bin

        if not vol_by_bin:
            return False, []

        all_vols = list(vol_by_bin.values())
        threshold = np.percentile(all_vols, self.p.vp_node_percentile)

        hvn_levels = []
        for b, v in vol_by_bin.items():
            if v >= threshold:
                level = price_min + (b + 0.5) * bin_size
                hvn_levels.append(level)

        current_price = self.data.close[0]
        at_hvn = any(abs(current_price - level) <= bin_size for level in hvn_levels)

        return at_hvn, sorted(hvn_levels)

    # ── Regime Filters ────────────────────────────────────────────────

    def _is_bearish_regime(self):
        """Allow shorts only when regime supports it.

        Conditions (any one):
        - Price below SMA(50) -- downtrend
        - RSI > 70 -- overbought even in uptrend
        - Price dropped below SMA(50) within last 5 bars -- trend weakening
        """
        price = self.data.close[0]
        sma_val = self.regime_sma[0]
        rsi_val = self.rsi[0]

        if price < sma_val:
            return True, "below_sma50"
        if rsi_val > self.p.rsi_overbought:
            return True, "rsi_overbought"

        # Check if price recently crossed below SMA
        for i in range(-5, 0):
            try:
                if self.data.close[i] > self.regime_sma[i] and self.data.close[i + 1] < self.regime_sma[i + 1]:
                    return True, "sma50_cross_down"
            except IndexError:
                pass

        return False, "bullish_regime"

    def _is_bullish_regime(self):
        """Allow longs only when regime supports it.

        Conditions (any one):
        - Price above SMA(50) -- uptrend
        - RSI < 30 -- oversold even in downtrend
        - Price rose above SMA(50) within last 5 bars -- trend strengthening
        """
        price = self.data.close[0]
        sma_val = self.regime_sma[0]
        rsi_val = self.rsi[0]

        if price > sma_val:
            return True, "above_sma50"
        if rsi_val < self.p.rsi_oversold:
            return True, "rsi_oversold"

        # Check if price recently crossed above SMA
        for i in range(-5, 0):
            try:
                if self.data.close[i] < self.regime_sma[i] and self.data.close[i + 1] > self.regime_sma[i + 1]:
                    return True, "sma50_cross_up"
            except IndexError:
                pass

        return False, "bearish_regime"

    # ── Score & Signal ─────────────────────────────────────────────────

    def _score_direction(self, direction):
        """Score a single direction's signal. Returns (score, details)."""
        score = 0
        details = {
            'triggers': [],
            'filters': [],
            'direction': direction,
        }

        if direction == 'short':
            details['pattern_high'] = self.data.high[0]
        else:
            details['pattern_low'] = self.data.low[0]

        # Check triggers
        trigger_count = 0
        ext_hit, ext_ratio = self._check_extension_candle(direction)
        if ext_hit:
            details['triggers'].append(f'Extension({ext_ratio:.1f}x)')
            trigger_count += 1

        vol_hit, vol_count = self._check_volume_exhaustion(direction)
        if vol_hit:
            details['triggers'].append(f'VolExhaust({vol_count})')
            trigger_count += 1

        wick_hit, wick_ratio = self._check_large_wick(direction)
        if wick_hit:
            details['triggers'].append(f'LargeWick({wick_ratio:.1f}x)')
            trigger_count += 1

        if trigger_count == 0:
            return 0, details

        # Pattern score: 1 point base, +1 if multiple triggers
        score = 1
        if trigger_count >= 2:
            score += 1
            details['filters'].append(f'MultiTrigger({trigger_count})')

        # Confluence filters (direction-agnostic)
        ma_hit, ma_details = self._check_near_ma()
        if ma_hit:
            periods = [str(h[0]) for h in ma_details]
            details['filters'].append(f'NearMA({",".join(periods)})')
            score += 1

        round_hit, round_level = self._check_round_number()
        if round_hit:
            details['filters'].append(f'Round(${round_level:.0f})')
            score += 1

        hvn_hit, hvn_levels = self._compute_volume_profile()
        if hvn_hit:
            details['filters'].append('VolNode')
            score += 1
            current = self.data.close[0]
            if direction == 'short':
                below = [l for l in hvn_levels if l < current]
                if below:
                    details['nearest_hvn_below'] = max(below)
            else:
                above = [l for l in hvn_levels if l > current]
                if above:
                    details['nearest_hvn_above'] = min(above)

        # Regime bonus
        if direction == 'short':
            regime_pass, regime_reason = self._is_bearish_regime()
        else:
            regime_pass, regime_reason = self._is_bullish_regime()

        if regime_pass:
            details['filters'].append(f'Regime({regime_reason})')
            score += 1

        details['total_score'] = score
        details['trigger_count'] = trigger_count
        details['regime_pass'] = regime_pass
        return score, details

    def _evaluate_signal(self):
        """Evaluate both short and long signals. Return the stronger one."""
        short_score, short_details = self._score_direction('short')
        long_score, long_details = self._score_direction('long')

        # Pick the higher-scoring direction; tie goes to short (original V2 bias)
        if short_score >= long_score:
            return short_score, short_details
        else:
            return long_score, long_details

    # ── Position Sizing (ATR-based) ────────────────────────────────────

    def _calc_position_size(self, entry_price, stop_price):
        risk_per_share = abs(entry_price - stop_price)
        if risk_per_share <= 0:
            return 0

        equity = self.broker.getvalue()
        risk_dollars = equity * self.p.risk_pct
        shares = int(risk_dollars / risk_per_share)
        max_shares = int(equity * 0.95 / entry_price)
        return max(min(shares, max_shares), 0)

    # ── Order Management ───────────────────────────────────────────────

    def notify_order(self, order):
        if order.status in [order.Completed]:
            if self.trade_direction == 'short':
                if order.issell() and self.entry_price is None:
                    # Short entry
                    self.entry_price = order.executed.price
                    self.entry_bar = len(self)
                    self.bars_since_entry = 0
                    self.one_r_reached = False
                    self.log(f'SHORT @ ${order.executed.price:.2f} | '
                             f'Size={order.executed.size} | '
                             f'Stop=${self.stop_price:.2f} | '
                             f'Target=${self.target_price:.2f} | '
                             f'Score={self.signal_score}')
                elif order.isbuy():
                    # Short cover
                    pnl = (self.entry_price - order.executed.price) * abs(order.executed.size) if self.entry_price else 0
                    self.log(f'COVER @ ${order.executed.price:.2f} | PnL=${pnl:.2f}')
                    self._reset_position_state()
            elif self.trade_direction == 'long':
                if order.isbuy() and self.entry_price is None:
                    # Long entry
                    self.entry_price = order.executed.price
                    self.entry_bar = len(self)
                    self.bars_since_entry = 0
                    self.one_r_reached = False
                    self.log(f'LONG @ ${order.executed.price:.2f} | '
                             f'Size={order.executed.size} | '
                             f'Stop=${self.stop_price:.2f} | '
                             f'Target=${self.target_price:.2f} | '
                             f'Score={self.signal_score}')
                elif order.issell():
                    # Long exit
                    pnl = (order.executed.price - self.entry_price) * abs(order.executed.size) if self.entry_price else 0
                    self.log(f'SELL @ ${order.executed.price:.2f} | PnL=${pnl:.2f}')
                    self._reset_position_state()
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'Order {order.Status[order.status]}')
        self.order = None

    def _reset_position_state(self):
        self.entry_price = None
        self.stop_price = None
        self.target_price = None
        self.trade_direction = None
        self.last_exit_bar = len(self)

    def notify_trade(self, trade):
        if trade.isclosed:
            self.log(f'CLOSED | Gross={trade.pnl:.2f} | Net={trade.pnlcomm:.2f}')

    # ── Core Logic ─────────────────────────────────────────────────────

    def next(self):
        if self.order:
            return

        min_bars = max(max(self.p.ma_periods), self.p.vp_lookback, self.p.atr_period + 1)
        if len(self.data) < min_bars:
            return

        if not self.position:
            # Cooldown check
            if len(self) - self.last_exit_bar < self.p.cooldown_bars:
                return

            score, details = self._evaluate_signal()
            direction = details.get('direction', 'short')

            if score >= self.p.min_confluence:
                # Regime gate
                if not details.get('regime_pass', False):
                    return

                if self.p.confirmation_bars > 0 and self.signal_bar < 0:
                    self.signal_bar = len(self)
                    self.signal_score = score
                    self.signal_details = details
                    self.log(f'SIGNAL {direction.upper()} (score={score}) — confirming...')
                    self.log(f'  Triggers: {", ".join(details["triggers"])}')
                    self.log(f'  Filters:  {", ".join(details["filters"])}')
                    return

                if self.signal_bar > 0:
                    bars_waited = len(self) - self.signal_bar
                    if bars_waited < self.p.confirmation_bars:
                        return

                    # Expire stale signals
                    if bars_waited > self.p.max_confirmation_wait:
                        self.log('SIGNAL EXPIRED — waited too long')
                        self.signal_bar = -1
                        return

                    # Use stored direction from signal bar
                    direction = self.signal_details.get('direction', 'short')

                    # Signal invalidation
                    if direction == 'short':
                        if self.data.high[0] > self.signal_details['pattern_high']:
                            self.log('SIGNAL INVALIDATED — new high')
                            self.signal_bar = -1
                            return
                    else:  # long
                        if self.data.low[0] < self.signal_details['pattern_low']:
                            self.log('SIGNAL INVALIDATED — new low')
                            self.signal_bar = -1
                            return

                    score = self.signal_score
                    details = self.signal_details

                # ATR-based stop and target
                atr_val = self.atr[0]
                entry = self.data.close[0]

                if direction == 'short':
                    pattern_high = details.get('pattern_high', self.data.high[0])
                    stop = max(pattern_high + atr_val * self.p.atr_stop_mult,
                               entry + atr_val * 1.5)
                    risk = stop - entry

                    # Target: HVN below or reward_ratio * risk
                    hvn_below = details.get('nearest_hvn_below')
                    if hvn_below and (entry - hvn_below) > risk * 1.5:
                        target = hvn_below
                    else:
                        target = entry - (risk * self.p.reward_ratio)
                else:  # long
                    pattern_low = details.get('pattern_low', self.data.low[0])
                    stop = min(pattern_low - atr_val * self.p.atr_stop_mult,
                               entry - atr_val * 1.5)
                    risk = entry - stop

                    # Target: HVN above or reward_ratio * risk
                    hvn_above = details.get('nearest_hvn_above')
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
                self.trade_direction = direction
                self.signal_bar = -1

                if direction == 'short':
                    self.order = self.sell(size=size)
                else:
                    self.order = self.buy(size=size)

        else:
            # ── MANAGE POSITION ──
            self.bars_since_entry += 1

            if self.trade_direction == 'short':
                # Stop: high breaches stop (price moved against)
                if self.data.high[0] >= self.stop_price:
                    self.log(f'STOP @ ${self.stop_price:.2f}')
                    self.order = self.close()
                    return

                # Target: low breaches target (price moved in favor)
                if self.data.low[0] <= self.target_price:
                    self.log(f'TARGET @ ${self.target_price:.2f}')
                    self.order = self.close()
                    return

                # Trail stop down after 1R
                if self.p.trail_after_1r and self.entry_price:
                    risk = self.stop_price - self.entry_price
                    current_profit = self.entry_price - self.data.close[0]
                    if current_profit >= abs(risk) and not self.one_r_reached:
                        self.one_r_reached = True
                        self.stop_price = self.entry_price
                        self.log(f'1R — stop to BE ${self.entry_price:.2f}')
                    elif self.one_r_reached:
                        new_stop = self.data.close[0] + abs(risk) * 0.5
                        if new_stop < self.stop_price:
                            self.stop_price = new_stop

            elif self.trade_direction == 'long':
                # Stop: low breaches stop (price moved against)
                if self.data.low[0] <= self.stop_price:
                    self.log(f'STOP @ ${self.stop_price:.2f}')
                    self.order = self.close()
                    return

                # Target: high breaches target (price moved in favor)
                if self.data.high[0] >= self.target_price:
                    self.log(f'TARGET @ ${self.target_price:.2f}')
                    self.order = self.close()
                    return

                # Trail stop up after 1R
                if self.p.trail_after_1r and self.entry_price:
                    risk = self.entry_price - self.stop_price
                    current_profit = self.data.close[0] - self.entry_price
                    if current_profit >= abs(risk) and not self.one_r_reached:
                        self.one_r_reached = True
                        self.stop_price = self.entry_price
                        self.log(f'1R — stop to BE ${self.entry_price:.2f}')
                    elif self.one_r_reached:
                        new_stop = self.data.close[0] - abs(risk) * 0.5
                        if new_stop > self.stop_price:
                            self.stop_price = new_stop

            # Time exit (both directions)
            if self.bars_since_entry >= self.p.max_hold_bars:
                self.log(f'TIME EXIT ({self.bars_since_entry} bars)')
                self.order = self.close()
