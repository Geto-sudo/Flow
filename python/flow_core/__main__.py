"""CLI entry point: py -m flow_core <video_path> [options]"""
import sys
import argparse
import os

# Make sure local install works
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from .video_parser import process_video, process_folder, build_graph_smart


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="flow",
        description="Flow: observe a video and produce a ProjectGraph.",
    )
    parser.add_argument(
        "input", help="Path to a video file, or a folder of videos."
    )
    parser.add_argument(
        "-o", "--output-dir", default=None,
        help="Where to write .flow.json + .flow.txt. Defaults to the input folder."
    )
    parser.add_argument(
        "-d", "--depth", default=None,
        choices=["fast", "speech", "vision", "full"],
        help="Override auto-picked depth. Default: smart based on video length."
    )
    parser.add_argument(
        "--no-json", action="store_true", help="Skip writing .flow.json"
    )
    parser.add_argument(
        "--no-summary", action="store_true", help="Skip writing .flow.txt"
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="Suppress progress output"
    )

    args = parser.parse_args(argv)

    if os.path.isdir(args.input):
        process_folder(
            args.input,
            force_depth=args.depth,
            save_json=not args.no_json,
            save_summary=not args.no_summary,
            verbose=not args.quiet,
        )
    else:
        if not os.path.exists(args.input):
            print(f"Error: file not found: {args.input}", file=sys.stderr)
            return 1
        g = process_video(
            args.input,
            output_dir=args.output_dir,
            force_depth=args.depth,
            save_json=not args.no_json,
            save_summary=not args.no_summary,
            verbose=not args.quiet,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
