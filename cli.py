"""
YTD Texture Extractor CLI

Batch-extracts diffuse textures from GTA V .ytd files (RSC7 format),
converts them to .webp previews, and generates a catalog.json
for a web-based clothing shop UI.

Usage:
    python cli.py [OPTIONS]

Options:
    --input PATH         Root stream/ directory (default: ./stream)
    --output PATH        Output directory (default: ./output)
    --workers INT        Parallel workers (default: 0 = all CPU cores)
    --dry-run            Scan and report counts only
    --force              Re-process even if .webp exists
    --verbose            Per-file progress output
    --single FILE        Process a single .ytd file (for debugging)
    --render-3d          Use Blender 3D rendering (default: enabled)
    --no-render-3d       Disable 3D rendering
    --blender-path       Path to Blender executable (default: auto-detect)
    --base-game PATH     Path to base game directory
    --json-progress      Emit JSON lines to stdout for GUI progress
    --scan-only          Discover DLCs + item counts, output JSON, exit
    --dlcs LIST          Comma-separated DLC folder names to process
    --taa-samples INT    TAA render samples (default: preset)
    --render-size INT    Blender render resolution in px (default: preset)
    --supersampling N    Supersampling multiplier: 1, 2, or 4
    --output-size INT    Final output image size in px (default: 512)
    --webp-quality INT   WebP compression quality 1-100 (default: 100)
    --no-green-fix       Disable green hair tint replacement
"""

import argparse
import logging
import os
import sys

# Ensure the project root is on sys.path so `src.*` imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.scanner import scan_and_process, process_single_ytd


def _handle_single(ytd_path: str, output_dir: str) -> None:
    """Process a single .ytd file for debugging."""
    from src.filename_parser import parse_ytd_filename

    info = parse_ytd_filename(ytd_path)
    if info is None:
        print(f"WARNING: Filename does not match expected pattern: {os.path.basename(ytd_path)}")
        print("Processing anyway (output to debug.webp)...")
        output_webp = os.path.join(output_dir, "debug.webp")
    else:
        output_webp = os.path.join(
            output_dir, "textures",
            info.dlc_name, info.gender, info.category,
            f"{info.drawable_id:03d}.webp",
        )
        print(f"Parsed: dlc={info.dlc_name} gender={info.gender} "
              f"category={info.category} drawable={info.drawable_id}")

    print(f"Input:  {ytd_path}")
    print(f"Output: {output_webp}")
    print()

    try:
        result = process_single_ytd(ytd_path, output_webp)
        size = os.path.getsize(output_webp)
        print(f"OK: {result['original_width']}x{result['original_height']} "
              f"{result['format']} -> {size} bytes WebP")
    except Exception as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract diffuse textures from GTA V .ytd files to .webp previews.",
    )
    parser.add_argument(
        "--input", default="./stream",
        help="Root stream/ directory (default: ./stream)",
    )
    parser.add_argument(
        "--output", default="./output",
        help="Output directory (default: ./output)",
    )
    parser.add_argument(
        "--workers", type=int, default=0,
        help="Number of parallel workers (default: 0 = all CPU cores)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Scan and report counts only, don't process files",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-process even if .webp output already exists",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Print per-file progress",
    )
    parser.add_argument(
        "--single",
        help="Process a single .ytd file (for debugging)",
    )
    parser.add_argument(
        "--render-3d", action="store_true", default=True,
        help="Use Blender 3D rendering (default: enabled)",
    )
    parser.add_argument(
        "--no-render-3d", action="store_false", dest="render_3d",
        help="Disable 3D rendering, use flat textures only",
    )
    parser.add_argument(
        "--blender-path",
        help="Path to Blender executable (default: auto-detect)",
    )
    parser.add_argument(
        "--batch-size", type=int, default=50,
        help="(Deprecated — ignored. Blender now uses persistent worker pool.)",
    )
    parser.add_argument(
        "--base-game",
        help="Path to base game directory (e.g. ./base_game)",
    )
    parser.add_argument(
        "--data", default="./data",
        help="Path to data directory with clothing.json/props.json for collection name casing (default: ./data)",
    )
    parser.add_argument(
        "--log-level", default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Set logging level (default: WARNING)",
    )
    parser.add_argument(
        "--json-progress", action="store_true",
        help="Emit JSON lines to stdout for GUI progress tracking",
    )
    parser.add_argument(
        "--scan-only", action="store_true",
        help="Output JSON list of discovered DLCs + item counts, then exit",
    )
    parser.add_argument(
        "--dlcs",
        help="Comma-separated DLC folder names to process (default: all)",
    )
    parser.add_argument(
        "--taa-samples", type=int, default=0,
        help="TAA render samples (default: 0 = use preset)",
    )
    parser.add_argument(
        "--render-size", type=int, default=0,
        help="Blender render resolution in px (default: 0 = use preset)",
    )
    parser.add_argument(
        "--supersampling", type=int, default=0, choices=[0, 1, 2, 4],
        help="Supersampling multiplier: 1, 2, or 4 (default: 0 = use preset)",
    )
    parser.add_argument(
        "--output-size", type=int, default=0,
        help="Final output image size in px (default: 0 = 512)",
    )
    parser.add_argument(
        "--webp-quality", type=int, default=0,
        help="WebP compression quality 1-100 (default: 0 = 100)",
    )
    parser.add_argument(
        "--no-green-fix", action="store_true",
        help="Disable green hair tint replacement",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(levelname)s [%(name)s] %(message)s",
    )

    if args.single:
        _handle_single(args.single, args.output)
        return

    dlcs_list = [d.strip() for d in args.dlcs.split(",")] if args.dlcs else None

    scan_and_process(
        input_dir=args.input,
        output_dir=args.output,
        workers=args.workers,
        dry_run=args.dry_run,
        force=args.force,
        verbose=args.verbose,
        render_3d=args.render_3d,
        blender_path=args.blender_path,
        batch_size=args.batch_size,
        base_game_dir=args.base_game,
        data_dir=args.data,
        json_progress=args.json_progress,
        scan_only=args.scan_only,
        dlcs=dlcs_list,
        taa_samples=args.taa_samples,
        render_size=args.render_size,
        supersampling=args.supersampling,
        output_size=args.output_size,
        webp_quality=args.webp_quality,
        green_hair_fix=not args.no_green_fix,
    )


if __name__ == "__main__":
    main()
