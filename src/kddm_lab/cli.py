import argparse
from pathlib import Path

from kddm_lab.warehouse import build_warehouse, export_analysis


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kddm-lab",
        description="Build and analyze the Olist DuckDB warehouse.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="Build the DuckDB star-schema warehouse.")
    build.add_argument("--data-dir", type=Path, default=Path("data/raw"))
    build.add_argument("--db", type=Path, default=Path("data/olist.duckdb"))

    analyze = commands.add_parser("analyze", help="Export OLAP summaries and ML features.")
    analyze.add_argument("--db", type=Path, default=Path("data/olist.duckdb"))
    analyze.add_argument("--output-dir", type=Path, default=Path("data/processed"))
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "build":
        counts = build_warehouse(args.data_dir, args.db)
        print(f"Warehouse built: {args.db}")
        for table, count in counts.items():
            print(f"{table}: {count:,} rows")
    else:
        for path in export_analysis(args.db, args.output_dir):
            print(f"Created {path}")


if __name__ == "__main__":
    main()
