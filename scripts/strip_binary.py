#!/usr/bin/env python3
"""Remove base64/binary content from JSONL files to prevent context window blowouts."""

import argparse
import json
import re
import sys

BASE64_RE = re.compile(r"^[A-Za-z0-9+/=\n\r]+$")
BASE64_MIN_LENGTH = 1000


def strip_strings(obj, source_path: str, line_no: int, max_field_bytes: int):
    """Recursively walk a JSON object and replace base64/oversized strings."""
    if isinstance(obj, str):
        # Base64 detection: strings > 1000 chars matching base64 alphabet
        if len(obj) > BASE64_MIN_LENGTH and BASE64_RE.match(obj):
            return f"[BASE64: {len(obj)} bytes, source: {source_path}:{line_no}]"
        # Field size cap
        if len(obj) > max_field_bytes:
            return obj[:max_field_bytes] + f"... [TRUNCATED at {len(obj)} bytes, source: {source_path}:{line_no}]"
        return obj
    elif isinstance(obj, dict):
        return {k: strip_strings(v, source_path, line_no, max_field_bytes) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [strip_strings(item, source_path, line_no, max_field_bytes) for item in obj]
    else:
        return obj


def strip_strings_media_aware(obj, source_path: str, line_no: int, max_field_bytes: int):
    """Like strip_strings, but preserves base64 data inside image content blocks.

    An image content block is a dict with "type": "image" and a "source" key
    whose "media_type" starts with "image/". Such dicts are returned as-is,
    keeping the base64 "data" field intact for downstream screenshot extraction.

    OpenCode exports image attachments as {"type": "file", "mime": "image/...",
    "url": "data:image/...;base64,..."}. Those dicts are also preserved.
    """
    if isinstance(obj, dict):
        # Preserve image content blocks wholesale
        if (obj.get("type") == "image"
                and isinstance(obj.get("source"), dict)
                and str(obj["source"].get("media_type", "")).startswith("image/")):
            return obj
        if (obj.get("type") == "file"
                and str(obj.get("mime", "")).startswith("image/")
                and str(obj.get("url", "")).startswith("data:image/")):
            return obj
        return {k: strip_strings_media_aware(v, source_path, line_no, max_field_bytes)
                for k, v in obj.items()}
    elif isinstance(obj, list):
        return [strip_strings_media_aware(item, source_path, line_no, max_field_bytes)
                for item in obj]
    elif isinstance(obj, str):
        # Delegate scalar string handling to the original function
        return strip_strings(obj, source_path, line_no, max_field_bytes)
    else:
        return obj


def main():
    parser = argparse.ArgumentParser(description="Strip base64/binary content from JSONL files")
    parser.add_argument("--input", required=True, help="Input JSONL file")
    parser.add_argument("--output", required=True, help="Output cleaned JSONL file")
    parser.add_argument(
        "--max-field-bytes",
        type=int,
        default=100000,
        help="Maximum bytes for any string field (default: 100000)",
    )
    parser.add_argument(
        "--preserve-screenshots",
        action="store_true",
        help="Preserve base64 data inside image content blocks (for screenshot extraction)",
    )
    args = parser.parse_args()

    strip_fn = strip_strings_media_aware if args.preserve_screenshots else strip_strings

    with open(args.input) as fin, open(args.output, "w") as fout:
        for line_no, line in enumerate(fin, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                cleaned = strip_fn(obj, args.input, line_no, args.max_field_bytes)
                fout.write(json.dumps(cleaned, ensure_ascii=False) + "\n")
            except json.JSONDecodeError:
                # Pass through non-JSON lines as-is
                fout.write(line + "\n")


if __name__ == "__main__":
    main()
