def generate_signal(ticker, multi_df):
    return {
        "Stock": ticker,
        "Side": "BUY",
        "Entry": 100,
        "Target": 105,
        "StopLoss": 98,
        "Confidence": 0.95,
        "Strategy": "test_strategy",
        "StrategyType": "intraday",
    }
