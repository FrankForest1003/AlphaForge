from AlgorithmImports import *
from alphaforge_base import AlphaForgeBaseAlgorithm


class UserStrategy(AlphaForgeBaseAlgorithm):
    """Regression fixture for the META 2024-02-02 overnight gap."""

    def initialize_strategy(self):
        self.set_start_date(2024, 1, 29)
        self.set_end_date(2024, 2, 9)
        self.set_cash(100_000)
        self.symbols = {}
        for ticker in ("AAPL", "MSFT", "GOOGL", "META", "NVDA", "AMZN"):
            security = self.add_equity(ticker, Resolution.DAILY)
            self.af_configure_security(
                security,
                fee_bps=10,
                slippage_bps=5,
                leverage=1,
            )
            self.symbols[ticker] = self.af_track_symbol(security.symbol)

        self.af_use_security_benchmark(self.symbols["AAPL"])
        anchor = self.symbols["AAPL"]
        self.schedule.on(
            self.date_rules.on(2024, 1, 31),
            self.time_rules.before_market_open(anchor, 5),
            self.enter_old_portfolio,
        )
        self.schedule.on(
            self.date_rules.on(2024, 2, 2),
            self.time_rules.before_market_open(anchor, 5),
            self.rotate_into_gap_portfolio,
        )

    def enter_old_portfolio(self):
        weight = 0.95 / 3
        self.af_rebalance_to_weights(
            {
                self.symbols["AAPL"]: weight,
                self.symbols["MSFT"]: weight,
                self.symbols["GOOGL"]: weight,
            },
            "regression initial portfolio",
        )

    def rotate_into_gap_portfolio(self):
        weight = 0.95 / 3
        self.af_rebalance_to_weights(
            {
                self.symbols["META"]: weight,
                self.symbols["NVDA"]: weight,
                self.symbols["AMZN"]: weight,
            },
            "regression META gap rotation",
        )

    def on_alpha_end(self):
        self.debug("ALPHAFORGE_USER_STRATEGY_COMPLETED")
