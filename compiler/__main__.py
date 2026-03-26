"""TTDoom Compiler CLI.

Usage:
    python -m compiler source.doom -o output.ttf
    python -m compiler source.doom          # outputs to source.ttf
    python -m compiler source.doom --bars 32
"""

from __future__ import annotations

import argparse
import sys

from compiler.pipeline import compile_doom


def main() -> None:
    """Entry point for the TTDoom compiler CLI."""
    parser = argparse.ArgumentParser(
        prog="python -m compiler",
        description="TTDoom Compiler -- compiles .doom DSL to .ttf font",
    )
    parser.add_argument(
        "source",
        help="Path to .doom source file",
    )
    parser.add_argument(
        "-o", "--output",
        help="Output .ttf path (default: same stem as source)",
    )
    parser.add_argument(
        "--bars",
        type=int,
        default=64,
        help="Number of bar columns in the display glyph (default: 64)",
    )
    parser.add_argument(
        "--axes",
        type=int,
        default=5,
        help="Number of variation axes (default: 5)",
    )
    args = parser.parse_args()

    if args.output is None:
        args.output = args.source.rsplit(".", 1)[0] + ".ttf"

    try:
        with open(args.source, "r") as f:
            source = f.read()
    except FileNotFoundError:
        print(f"Error: source file not found: {args.source}", file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        print(f"Error reading source file: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        result = compile_doom(
            source,
            args.output,
            num_bars=args.bars,
            num_axes=args.axes,
        )
        print(f"Compiled to {result}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
