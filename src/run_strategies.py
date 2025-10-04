# src/run_strategies.py
import importlib
import os
from glob import glob

STRAT_PATH = "strategies"

def load_strategy_modules():
    """Load all strategy modules dynamically."""
    mods = []
    files = glob(os.path.join(STRAT_PATH, "*.py"))
    for f in files:
        name = os.path.splitext(os.path.basename(f))[0]
        if name.startswith("_"):
            continue
        mod = importlib.import_module(f"{STRAT_PATH}.{name}")
        if hasattr(mod, "generate_signal"):
            mods.append((name, mod))
    return mods

def get_required_indicators(strategies):
    """Collect unique indicators required by all loaded strategies."""
    indicators = set()
    for name, mod in strategies:
        if hasattr(mod, "REQUIRED_INDICATORS"):
            indicators.update(mod.REQUIRED_INDICATORS)
    return list(indicators)

def evaluate_for_ticker(ticker, multi_df, confidence_threshold=0.6):
    """Run all strategies for a single ticker and return valid signals."""
    signals = []
    for name, mod in load_strategy_modules():
        try:
            sig = mod.generate_signal(ticker, multi_df)
            if sig:
                sig["Strategy"] = sig.get("Strategy", name)
                if sig.get("Confidence", 0) >= confidence_threshold:
                    signals.append(sig)
        except Exception:
            continue
    return signals
if __name__ == "__main__":
    mods = load_strategy_modules()
    print("Loaded strategies:", [name for name, _ in mods])
