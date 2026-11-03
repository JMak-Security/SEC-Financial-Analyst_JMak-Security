"""Measure Monte Carlo throughput on this host; no latency guarantee is implied."""

from __future__ import annotations

import argparse
import platform
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portfolio_risk.engine import RiskEngine


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paths", type=int, default=1_000_000)
    parser.add_argument("--assets", type=int, default=8)
    parser.add_argument("--horizon-days", type=int, default=1)
    parser.add_argument("--backend", choices=("local", "dask"), default="dask")
    parser.add_argument("--chunk-size", type=int, default=25_000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.assets < 1:
        parser.error("--assets must be positive.")
    generator = np.random.default_rng(args.seed)
    returns = pd.DataFrame(
        generator.normal(0.0002, 0.015, size=(1000, args.assets)),
        columns=[f"ASSET_{index:02d}" for index in range(args.assets)],
    )
    weights = {asset: 1.0 / args.assets for asset in returns.columns}
    engine = RiskEngine(returns, weights)
    started = time.perf_counter()
    report = engine.simulate_monte_carlo(
        portfolio_value=1_000_000,
        confidence=0.99,
        horizon_days=args.horizon_days,
        simulations=args.paths,
        seed=args.seed,
        backend=args.backend,
        chunk_size=args.chunk_size,
    )
    elapsed = time.perf_counter() - started
    print(
        {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "backend": args.backend,
            "paths": report.simulations,
            "assets": args.assets,
            "horizon_days": args.horizon_days,
            "chunk_size": args.chunk_size,
            "elapsed_seconds": round(elapsed, 3),
            "paths_per_second": round(report.simulations / elapsed),
            "var": round(report.var, 2),
            "cvar": round(report.cvar, 2),
            "target_seconds": 5,
            "target_met": elapsed < 5,
        }
    )


if __name__ == "__main__":
    main()
