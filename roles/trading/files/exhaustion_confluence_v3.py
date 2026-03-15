#!/usr/bin/env python3
"""ATLAS Exhaustion Confluence Strategy v3 — Bidirectional Regime-Adaptive.

IMPROVEMENTS OVER V2 (based on 18-year backtest 2008-2026):
  v2 failures: 33 trades (need 200+), short-only (-3.5% over 18yr),
  patterns don't scale to intraday, zero signals in fast crashes.

  v3 redesign:
    1. BIDIRECTIONAL: Both long (capitulation) and short (blow-off) exhaustion
    2. REGIME-ADAPTIVE: Three-speed regime detection (fast/medium/slow)
    3. ATR-NORMALIZED thresholds: Scale with volatility instead of fixed multiples
    4. RELAXED CONFLUENCE: Min score 2 (was 3) to generate enough trades
    5. MOMENTUM FOLLOW-THROUGH: After deep pullbacks in trends, take continuation entries
    6. VOLATILITY EXPANSION filter: Enter when ATR is expanding (move has energy)
    7. TARGET: 10-15 trades/year on daily for statistical validity
"""

import backtrader as bt
import numpy as np
from collections import defaultdict


class ExhaustionConfluenceV3(bt.Strategy):
    params = (
        # Pattern detection — ATR-normalized
        ('body_lookback', 14),
        ('extension_mult', 1.5),       # Lowered from 2.0 — ATR-normalized now
        ('wick_body_ratio', 1.5),      # Lowered from 2.0
        ('trend_lookback', 3),         # Shortened from 5 — catches shorter exhaustion
        ('vol_div_lookback', 2),       # Shortened from 3

        # Volume profile
        ('vp_lookback', 150),
        ('vp_bins', 50),
        ('vp_node_percentile', 85),    # Relaxed from 90

        # Moving averages
        ('ma_periods', [20, 50, 100, 200]),
        ('ma_proximity_pct', 0.8),     # Widened from 0.5%

        # Round numbers
        ('round_interval', 10),
        ('round_proximity_pct', 0.5),  # Widened from 0.3%

        # Regime detection — three speeds
        ('fast_ema', 10),
        ('medium_ema', 21),
        ('slow_sma', 50),
        ('trend_sma', 200),
        ('rsi_period', 14),
        ('rsi_overbought', 65),        # Relaxed from 70
        ('rsi_oversold', 35),          # Added for long side

        # Volatility
        ('atr_period', 14),
        ('atr_stop_mult', 2.0),
        ('atr_expansion_lookback', 5), # ATR must be rising for entry
        ('atr_expansion_ratio', 1.1),  # Current ATR > 1.1x avg ATR

        # Confluence & entry
        ('min_confluence', 2),         # Lowered from 3 — more trades
        ('confirmation_bars', 1),
        ('max_confirmation_wait', 3),  # Tightened from 5

        # Risk management
        ('risk_pct', 0.02),
        ('reward_ratio', 2.0),         # Lowered from 2.5 — more achievable
        ('max_hold_bars', 15),         # Shortened from 20
        ('trail_after_1r', True),
        ('cooldown_bars', 2),          # Shortened from 3

        # Momentum continuation
        ('pullback_pct', 0.03),        # 3% pullback in trend = continuation entry
        ('pullback_lookback', 10),     # Look back N bars for swing high/low
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
        self.signal_direction = None   # 'long' or 'short'
        self.bars_since_entry = 0
        self.one_r_reached = False
        self.last_exit_bar = -999
        self.trade_direction = None    # Track current position direction

        # Indicators
        self.mas = {}
        for p in self.p.ma_periods:
            self.mas[p] = bt.indicators.SMA(self.data.close, period=p)

        self.fast_ema = bt.indicators.EMA(self.data.close, period=self.p.fast_ema)
        self.medium_ema = bt.indicators.EMA(self.data.close, period=self.p.medium_ema)
        self.slow_sma = bt.indicators.SMA(self.data.close, period=self.p.slow_sma)
        self.trend_sma = bt.indicators.SMA(self.data.close, period=self.p.trend_sma)

        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)

    def log(self, txt):
        dt = self.data.datetime.datetime(0)
        print(f'{dt.strftime("%Y-%m-%d")} | {txt}')

    # ── Regime Detection ─────────────────────────────────────────────

    def _get_regime(self):
        """Three-speed regime detection.

        Returns: ('bullish'|'bearish'|'neutral', strength 0-3, details)
        """
        price = self.data.close[0]
        signals = []

        # Fast: EMA(10) vs EMA(21)
        try:
            fast_bull = self.fast_ema[0] > self.medium_ema[0]
            signals.append(1 if fast_bull else -1)
        except IndexError:
            pass

        # Medium: Price vs SMA(50)
        try:
            med_bull = price > self.slow_sma[0]
            signals.append(1 if med_bull else -1)
        except IndexError:
            pass

        # Slow: SMA(50) vs SMA(200)
        try:
            slow_bull = self.slow_sma[0] > self.trend_sma[0]
            signals.append(1 if slow_bull else -1)
        except IndexError:
            pass

        if not signals:
            return 'neutral', 0, []

        score = sum(signals)
        if score >= 2:
            return 'bullish', score, signals
        elif score <= -2:
            return 'bearish', abs(score), signals
        else:
            return 'neutral', abs(score), signals

    def _is_vol_expanding(self):
        """Check if volatility is expanding (move has energy)."""
        try:
            avg_atr = np.mean([self.atr[-i] for i in range(self.p.atr_expansion_lookback)])
            return self.atr[0] > avg_atr * self.p.atr_expansion_ratio, self.atr[0] / avg_atr if avg_atr > 0 else 1
        except (IndexError, ZeroDivisionError):
            return False, 1.0

    # ── Pattern Detection (ATR-normalized, bidirectional) ────────────

    def _body_size(self, ago=0):
        return abs(self.data.close[ago] - self.data.open[ago])

    def _upper_wick(self, ago=0):
        return self.data.high[ago] - max(self.data.open[ago], self.data.close[ago])

    def _lower_wick(self, ago=0):
        return min(self.data.open[ago], self.data.close[ago]) - self.data.low[ago]

    def _is_bullish_candle(self, ago=0):
        return self.data.close[ago] > self.data.open[ago]

    def _avg_body(self):
        bodies = []
        for i in range(-self.p.body_lookback, 0):
            try:
                bodies.append(self._body_size(i))
            except IndexError:
                pass
        return np.mean(bodies) if bodies else 0

    def _check_short_extension(self):
        """Bullish extension candle (blow-off top) → short signal."""
        avg_body = self._avg_body()
        atr = self.atr[0] if self.atr[0] > 0 else 1
        if avg_body <= 0:
            return False, 0

        current_body = self._body_size(0)
        # ATR-normalized: body must be significant relative to volatility
        ratio = current_body / avg_body
        atr_ratio = current_body / atr

        if ratio >= self.p.extension_mult and atr_ratio > 0.8 and self._is_bullish_candle(0):
            higher_closes = sum(
                1 for i in range(-self.p.trend_lookback, 0)
                if self.data.close[i] > self.data.close[i - 1]
            )
            if higher_closes >= self.p.trend_lookback - 1:
                return True, ratio
        return False, 0

    def _check_long_extension(self):
        """Bearish extension candle (capitulation) → long signal."""
        avg_body = self._avg_body()
        atr = self.atr[0] if self.atr[0] > 0 else 1
        if avg_body <= 0:
            return False, 0

        current_body = self._body_size(0)
        ratio = current_body / avg_body
        atr_ratio = current_body / atr

        if ratio >= self.p.extension_mult and atr_ratio > 0.8 and not self._is_bullish_candle(0):
            lower_closes = sum(
                1 for i in range(-self.p.trend_lookback, 0)
                if self.data.close[i] < self.data.close[i - 1]
            )
            if lower_closes >= self.p.trend_lookback - 1:
                return True, ratio
        return False, 0

    def _check_short_volume_exhaustion(self):
        """Higher highs + declining volume → bearish divergence."""
        try:
            hh = 0
            lv = 0
            for i in range(-self.p.vol_div_lookback, 0):
                if self.data.high[i + 1] > self.data.high[i]:
                    hh += 1
                if self.data.volume[i + 1] < self.data.volume[i]:
                    lv += 1
            if (self.data.high[0] > self.data.high[-1] and
                    self.data.volume[0] < self.data.volume[-1]):
                hh += 1
                lv += 1
            if hh >= self.p.vol_div_lookback and lv >= self.p.vol_div_lookback:
                return True, lv
        except IndexError:
            pass
        return False, 0

    def _check_long_volume_exhaustion(self):
        """Lower lows + declining volume → bullish divergence."""
        try:
            ll = 0
            lv = 0
            for i in range(-self.p.vol_div_lookback, 0):
                if self.data.low[i + 1] < self.data.low[i]:
                    ll += 1
                if self.data.volume[i + 1] < self.data.volume[i]:
                    lv += 1
            if (self.data.low[0] < self.data.low[-1] and
                    self.data.volume[0] < self.data.volume[-1]):
                ll += 1
                lv += 1
            if ll >= self.p.vol_div_lookback and lv >= self.p.vol_div_lookback:
                return True, lv
        except IndexError:
            pass
        return False, 0

    def _check_short_wick(self):
        """Large upper wick → rejection at highs."""
        body = max(self._body_size(0), 0.01)
        wick = self._upper_wick(0)
        ratio = wick / body
        if ratio >= self.p.wick_body_ratio and wick > 0:
            return True, ratio
        return False, 0

    def _check_long_wick(self):
        """Large lower wick (hammer) → rejection at lows."""
        body = max(self._body_size(0), 0.01)
        wick = self._lower_wick(0)
        ratio = wick / body
        if ratio >= self.p.wick_body_ratio and wick > 0:
            return True, ratio
        return False, 0

    # ── Momentum Continuation ────────────────────────────────────────

    def _check_pullback_long(self):
        """Bullish trend + pullback from recent high → continuation long."""
        regime, strength, _ = self._get_regime()
        if regime != 'bullish' or strength < 2:
            return False, 0

        try:
            recent_high = max(self.data.high[-i] for i in range(1, self.p.pullback_lookback + 1))
            pullback = (recent_high - self.data.close[0]) / recent_high
            if pullback >= self.p.pullback_pct and self.rsi[0] < 45:
                return True, pullback
        except (IndexError, ZeroDivisionError):
            pass
        return False, 0

    def _check_pullback_short(self):
        """Bearish trend + rally from recent low → continuation short."""
        regime, strength, _ = self._get_regime()
        if regime != 'bearish' or strength < 2:
            return False, 0

        try:
            recent_low = min(self.data.low[-i] for i in range(1, self.p.pullback_lookback + 1))
            rally = (self.data.close[0] - recent_low) / recent_low if recent_low > 0 else 0
            if rally >= self.p.pullback_pct and self.rsi[0] > 55:
                return True, rally
        except (IndexError, ZeroDivisionError):
            pass
        return False, 0

    # ── Confluence Filters ───────────────────────────────────────────

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
            return False, [], None

        prices = []
        volumes = []
        for i in range(-lookback, 1):
            try:
                prices.append((self.data.low[i], self.data.high[i]))
                volumes.append(self.data.volume[i] if self.data.volume[i] > 0 else 1)
            except IndexError:
                pass

        if not prices:
            return False, [], None

        price_min = min(p[0] for p in prices)
        price_max = max(p[1] for p in prices)
        if price_max <= price_min:
            return False, [], None

        bin_size = (price_max - price_min) / self.p.vp_bins
        if bin_size <= 0:
            return False, [], None

        vol_by_bin = defaultdict(float)
        for (low, high), vol in zip(prices, volumes):
            low_bin = max(0, min(int((low - price_min) / bin_size), self.p.vp_bins - 1))
            high_bin = max(0, min(int((high - price_min) / bin_size), self.p.vp_bins - 1))
            bins_spanned = max(1, high_bin - low_bin + 1)
            vol_per_bin = vol / bins_spanned
            for b in range(low_bin, high_bin + 1):
                vol_by_bin[b] += vol_per_bin

        if not vol_by_bin:
            return False, [], None

        all_vols = list(vol_by_bin.values())
        threshold = np.percentile(all_vols, self.p.vp_node_percentile)

        hvn_levels = []
        for b, v in vol_by_bin.items():
            if v >= threshold:
                level = price_min + (b + 0.5) * bin_size
                hvn_levels.append(level)

        current_price = self.data.close[0]
        at_hvn = any(abs(current_price - level) <= bin_size for level in hvn_levels)

        # Find nearest HVN above and below
        below = [l for l in hvn_levels if l < current_price]
        above = [l for l in hvn_levels if l > current_price]
        nearest_below = max(below) if below else None
        nearest_above = min(above) if above else None

        return at_hvn, sorted(hvn_levels), {'below': nearest_below, 'above': nearest_above}

    # ── Signal Evaluation ────────────────────────────────────────────

    def _evaluate_signals(self):
        """Evaluate both long and short signals. Returns best signal."""
        best_score = 0
        best_direction = None
        best_details = None

        for direction in ['long', 'short']:
            score, details = self._evaluate_direction(direction)
            if score > best_score:
                best_score = score
                best_direction = direction
                best_details = details

        return best_score, best_direction, best_details

    def _evaluate_direction(self, direction):
        score = 0
        details = {
            'triggers': [],
            'filters': [],
            'direction': direction,
            'pattern_high': self.data.high[0],
            'pattern_low': self.data.low[0],
        }

        # Check triggers for this direction
        trigger_count = 0
        if direction == 'short':
            ext_hit, ext_r = self._check_short_extension()
            vol_hit, vol_c = self._check_short_volume_exhaustion()
            wick_hit, wick_r = self._check_short_wick()
            pb_hit, pb_r = self._check_pullback_short()
        else:
            ext_hit, ext_r = self._check_long_extension()
            vol_hit, vol_c = self._check_long_volume_exhaustion()
            wick_hit, wick_r = self._check_long_wick()
            pb_hit, pb_r = self._check_pullback_long()

        if ext_hit:
            details['triggers'].append(f'Extension({ext_r:.1f}x)')
            trigger_count += 1
        if vol_hit:
            details['triggers'].append(f'VolExhaust({vol_c})')
            trigger_count += 1
        if wick_hit:
            details['triggers'].append(f'Wick({wick_r:.1f}x)')
            trigger_count += 1
        if pb_hit:
            details['triggers'].append(f'Pullback({pb_r:.1%})')
            trigger_count += 1

        if trigger_count == 0:
            return 0, details

        # Base score from triggers
        score = 1
        if trigger_count >= 2:
            score += 1
            details['filters'].append(f'MultiTrigger({trigger_count})')

        # Confluence filters
        ma_hit, ma_details = self._check_near_ma()
        if ma_hit:
            periods = [str(h[0]) for h in ma_details]
            details['filters'].append(f'NearMA({",".join(periods)})')
            score += 1

        round_hit, round_level = self._check_round_number()
        if round_hit:
            details['filters'].append(f'Round(${round_level:.0f})')
            score += 1

        hvn_hit, hvn_levels, hvn_targets = self._compute_volume_profile()
        if hvn_hit:
            details['filters'].append('VolNode')
            score += 1
            details['hvn_targets'] = hvn_targets

        # Regime alignment bonus
        regime, r_strength, _ = self._get_regime()
        if direction == 'short' and regime == 'bearish':
            details['filters'].append(f'BearRegime({r_strength})')
            score += 1
        elif direction == 'long' and regime == 'bullish':
            details['filters'].append(f'BullRegime({r_strength})')
            score += 1
        elif direction == 'short' and regime == 'bullish' and r_strength >= 2:
            # Shorting in strong bull = penalty
            score -= 1
            details['filters'].append('ContraRegime(-1)')
        elif direction == 'long' and regime == 'bearish' and r_strength >= 2:
            score -= 1
            details['filters'].append('ContraRegime(-1)')

        # RSI extremes bonus
        rsi_val = self.rsi[0]
        if direction == 'short' and rsi_val > self.p.rsi_overbought:
            details['filters'].append(f'RSI_OB({rsi_val:.0f})')
            score += 1
        elif direction == 'long' and rsi_val < self.p.rsi_oversold:
            details['filters'].append(f'RSI_OS({rsi_val:.0f})')
            score += 1

        # Volatility expansion bonus
        vol_exp, vol_ratio = self._is_vol_expanding()
        if vol_exp:
            details['filters'].append(f'VolExp({vol_ratio:.1f}x)')
            score += 1

        details['total_score'] = score
        details['trigger_count'] = trigger_count
        details['regime'] = regime
        return score, details

    # ── Position Sizing ──────────────────────────────────────────────

    def _calc_position_size(self, entry_price, stop_price):
        risk_per_share = abs(entry_price - stop_price)
        if risk_per_share <= 0:
            return 0
        equity = self.broker.getvalue()
        risk_dollars = equity * self.p.risk_pct
        shares = int(risk_dollars / risk_per_share)
        max_shares = int(equity * 0.95 / entry_price)
        return max(min(shares, max_shares), 0)

    # ── Order Management ─────────────────────────────────────────────

    def notify_order(self, order):
        if order.status in [order.Completed]:
            if self.trade_direction == 'short' and order.issell():
                self.entry_price = order.executed.price
                self.entry_bar = len(self)
                self.bars_since_entry = 0
                self.one_r_reached = False
                self.log(f'SHORT @ ${order.executed.price:.2f} | '
                         f'Size={order.executed.size} | '
                         f'Stop=${self.stop_price:.2f} | '
                         f'Target=${self.target_price:.2f} | '
                         f'Score={self.signal_score}')
            elif self.trade_direction == 'long' and order.isbuy():
                self.entry_price = order.executed.price
                self.entry_bar = len(self)
                self.bars_since_entry = 0
                self.one_r_reached = False
                self.log(f'LONG @ ${order.executed.price:.2f} | '
                         f'Size={order.executed.size} | '
                         f'Stop=${self.stop_price:.2f} | '
                         f'Target=${self.target_price:.2f} | '
                         f'Score={self.signal_score}')
            elif (self.trade_direction == 'short' and order.isbuy()) or \
                 (self.trade_direction == 'long' and order.issell()):
                if self.entry_price:
                    if self.trade_direction == 'short':
                        pnl = (self.entry_price - order.executed.price) * abs(order.executed.size)
                    else:
                        pnl = (order.executed.price - self.entry_price) * abs(order.executed.size)
                    self.log(f'EXIT @ ${order.executed.price:.2f} | PnL=${pnl:.2f}')
                self.entry_price = None
                self.stop_price = None
                self.target_price = None
                self.last_exit_bar = len(self)
                self.trade_direction = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'Order {order.Status[order.status]}')
            self.trade_direction = None
        self.order = None

    def notify_trade(self, trade):
        if trade.isclosed:
            self.log(f'CLOSED | Gross={trade.pnl:.2f} | Net={trade.pnlcomm:.2f}')

    # ── Core Logic ───────────────────────────────────────────────────

    def next(self):
        if self.order:
            return

        min_bars = max(max(self.p.ma_periods), self.p.vp_lookback, self.p.atr_period + 1)
        if len(self.data) < min_bars:
            return

        if not self.position:
            # Cooldown
            if len(self) - self.last_exit_bar < self.p.cooldown_bars:
                return

            score, direction, details = self._evaluate_signals()

            if score >= self.p.min_confluence and direction:
                # Confirmation flow
                if self.p.confirmation_bars > 0 and self.signal_bar < 0:
                    self.signal_bar = len(self)
                    self.signal_score = score
                    self.signal_details = details
                    self.signal_direction = direction
                    self.log(f'{direction.upper()} SIGNAL (score={score}) — confirming...')
                    self.log(f'  Triggers: {", ".join(details["triggers"])}')
                    self.log(f'  Filters:  {", ".join(details["filters"])}')
                    return

                if self.signal_bar > 0:
                    bars_waited = len(self) - self.signal_bar
                    if bars_waited < self.p.confirmation_bars:
                        return
                    if bars_waited > self.p.max_confirmation_wait:
                        self.log('SIGNAL EXPIRED')
                        self.signal_bar = -1
                        return

                    # Invalidation check
                    if self.signal_direction == 'short' and self.data.high[0] > self.signal_details['pattern_high']:
                        self.log('SHORT SIGNAL INVALIDATED — new high')
                        self.signal_bar = -1
                        return
                    elif self.signal_direction == 'long' and self.data.low[0] < self.signal_details['pattern_low']:
                        self.log('LONG SIGNAL INVALIDATED — new low')
                        self.signal_bar = -1
                        return

                    score = self.signal_score
                    direction = self.signal_direction
                    details = self.signal_details

                # Calculate stops and targets
                atr_val = self.atr[0]
                entry = self.data.close[0]
                hvn_targets = details.get('hvn_targets') or {}

                if direction == 'short':
                    pattern_high = details.get('pattern_high', self.data.high[0])
                    stop = max(pattern_high + atr_val * self.p.atr_stop_mult,
                               entry + atr_val * 1.5)
                    risk = stop - entry

                    hvn_below = hvn_targets.get('below')
                    if hvn_below and (entry - hvn_below) > risk * 1.5:
                        target = hvn_below
                    else:
                        target = entry - (risk * self.p.reward_ratio)

                    size = self._calc_position_size(entry, stop)
                    if size <= 0:
                        self.signal_bar = -1
                        return

                    self.stop_price = stop
                    self.target_price = target
                    self.signal_score = score
                    self.trade_direction = 'short'
                    self.order = self.sell(size=size)

                else:  # long
                    pattern_low = details.get('pattern_low', self.data.low[0])
                    stop = min(pattern_low - atr_val * self.p.atr_stop_mult,
                               entry - atr_val * 1.5)
                    risk = entry - stop

                    hvn_above = hvn_targets.get('above')
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
                    self.trade_direction = 'long'
                    self.order = self.buy(size=size)

                self.signal_bar = -1

        else:
            # ── MANAGE POSITION ──
            self.bars_since_entry += 1

            if self.trade_direction == 'short':
                # Stop
                if self.data.high[0] >= self.stop_price:
                    self.log(f'STOP @ ${self.stop_price:.2f}')
                    self.order = self.close()
                    return
                # Target
                if self.data.low[0] <= self.target_price:
                    self.log(f'TARGET @ ${self.target_price:.2f}')
                    self.order = self.close()
                    return
                # Trail
                if self.p.trail_after_1r and self.entry_price:
                    risk = self.stop_price - self.entry_price
                    profit = self.entry_price - self.data.close[0]
                    if profit >= abs(risk) and not self.one_r_reached:
                        self.one_r_reached = True
                        self.stop_price = self.entry_price
                        self.log(f'1R — stop to BE ${self.entry_price:.2f}')
                    elif self.one_r_reached:
                        new_stop = self.data.close[0] + abs(risk) * 0.5
                        if new_stop < self.stop_price:
                            self.stop_price = new_stop

            elif self.trade_direction == 'long':
                # Stop
                if self.data.low[0] <= self.stop_price:
                    self.log(f'STOP @ ${self.stop_price:.2f}')
                    self.order = self.close()
                    return
                # Target
                if self.data.high[0] >= self.target_price:
                    self.log(f'TARGET @ ${self.target_price:.2f}')
                    self.order = self.close()
                    return
                # Trail
                if self.p.trail_after_1r and self.entry_price:
                    risk = self.entry_price - self.stop_price
                    profit = self.data.close[0] - self.entry_price
                    if profit >= abs(risk) and not self.one_r_reached:
                        self.one_r_reached = True
                        self.stop_price = self.entry_price
                        self.log(f'1R — stop to BE ${self.entry_price:.2f}')
                    elif self.one_r_reached:
                        new_stop = self.data.close[0] - abs(risk) * 0.5
                        if new_stop > self.stop_price:
                            self.stop_price = new_stop

            # Time exit
            if self.bars_since_entry >= self.p.max_hold_bars:
                self.log(f'TIME EXIT ({self.bars_since_entry} bars)')
                self.order = self.close()
