"""Run the committed Lacuna signal benchmark suite."""

from __future__ import annotations

import argparse

from lacuna.benchmark import benchmark_config_for_tier, run_benchmarks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", choices=("smoke", "small", "medium"), default="smoke")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no-native", action="store_true")
    arguments = parser.parse_args()
    config = benchmark_config_for_tier(
        arguments.tier,
        repetitions=arguments.repetitions,
        warmups=arguments.warmups,
        seed=arguments.seed,
    )
    print(run_benchmarks(config, use_native=not arguments.no_native).to_json())


if __name__ == "__main__":
    main()
