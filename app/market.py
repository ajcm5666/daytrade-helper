from __future__ import annotations

from dataclasses import dataclass

import yfinance as yf


@dataclass
class Quote:
    symbol: str
    price: float
    prev_close: float
    volume: float
    avg_volume: float

    @property
    def pct_change(self) -> float:
        if not self.prev_close:
            return 0.0
        return ((self.price - self.prev_close) / self.prev_close) * 100.0

    @property
    def volume_ratio(self) -> float:
        if not self.avg_volume:
            return 0.0
        return self.volume / self.avg_volume


def get_quote(symbol: str) -> Quote | None:
    symbol = symbol.strip().upper()
    if not symbol:
        return None
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="5d", interval="1d")
        if hist.empty:
            return None
        last = hist.iloc[-1]
        prev = hist.iloc[-2] if len(hist) > 1 else last
        info = {}
        try:
            info = ticker.fast_info or {}
        except Exception:
            info = {}
        price = float(info.get("lastPrice") or last["Close"])
        prev_close = float(info.get("previousClose") or prev["Close"])
        volume = float(info.get("lastVolume") or last["Volume"])
        avg_volume = float(
            info.get("threeMonthAverageVolume")
            or hist["Volume"].mean()
            or volume
        )
        return Quote(
            symbol=symbol,
            price=price,
            prev_close=prev_close,
            volume=volume,
            avg_volume=avg_volume,
        )
    except Exception:
        return None


def get_quotes(symbols: list[str]) -> dict[str, Quote]:
    out: dict[str, Quote] = {}
    for symbol in symbols:
        quote = get_quote(symbol)
        if quote:
            out[symbol.upper()] = quote
    return out