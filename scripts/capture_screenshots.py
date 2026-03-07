#!/usr/bin/env python3
"""Capture screenshots by checking out git commits and screenshotting a running dev server.

This is "Path B" — git-reconstructed screenshots. Only runs when the user
chooses "Capture from git history" or "Both" in the scoping dialog.

Usage:
    python3 scripts/capture_screenshots.py \
      --walkthrough out/walkthrough.json \
      --repo-root /path/to/project \
      --dev-cmd "npm run dev" \
      --url http://localhost:3000 \
      --routes "/,/login,/dashboard" \
      --output-dir out/captures/

Dependencies: playwright (pip install playwright && playwright install chromium)
"""

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def check_playwright():
    """Check if Playwright is available."""
    try:
        from playwright.sync_api import sync_playwright
        return True
    except ImportError:
        print(
            "Error: Playwright is not installed.\n"
            "Install with:\n"
            "  pip install playwright\n"
            "  playwright install chromium\n",
            file=sys.stderr,
        )
        return False


def detect_install_cmd(worktree_path: str) -> list[str] | None:
    """Auto-detect dependency install command from lock files."""
    p = Path(worktree_path)
    if (p / "package-lock.json").exists():
        return ["npm", "install", "--no-audit", "--no-fund"]
    if (p / "yarn.lock").exists():
        return ["yarn", "install", "--frozen-lockfile"]
    if (p / "pnpm-lock.yaml").exists():
        return ["pnpm", "install", "--frozen-lockfile"]
    if (p / "bun.lockb").exists() or (p / "bun.lock").exists():
        return ["bun", "install"]
    if (p / "requirements.txt").exists():
        return ["pip", "install", "-r", "requirements.txt"]
    if (p / "Pipfile.lock").exists():
        return ["pipenv", "install"]
    return None


def wait_for_server(url: str, timeout: int = 30) -> bool:
    """Poll URL with exponential backoff until it responds."""
    import urllib.request
    import urllib.error

    delay = 0.5
    elapsed = 0
    while elapsed < timeout:
        try:
            req = urllib.request.Request(url, method="GET")
            resp = urllib.request.urlopen(req, timeout=5)
            resp.read(1)
            resp.close()
            return True
        except urllib.error.HTTPError:
            # Any HTTP status means the server is reachable (even 4xx/5xx).
            return True
        except (urllib.error.URLError, OSError):
            time.sleep(delay)
            elapsed += delay
            delay = min(delay * 1.5, 5)
    return False


def extract_key_commits(walkthrough: dict) -> list[str]:
    """Extract commit SHAs from walkthrough evidence."""
    commits = []
    seen = set()

    for step in walkthrough.get("steps", []):
        evidence = step.get("evidence", {})
        for cmd in evidence.get("commands", []):
            cmd_str = cmd.get("cmd", "") if isinstance(cmd, dict) else str(cmd)
            cmd_summary = cmd.get("summary", "") if isinstance(cmd, dict) else ""
            search_blob = f"{cmd_str}\n{cmd_summary}"
            # Look for git commit references
            if "git" in search_blob or "commit" in search_blob:
                # Extract SHA-like strings
                import re
                for match in re.finditer(r'\b([0-9a-f]{7,40})\b', search_blob):
                    sha = match.group(1)
                    if sha not in seen:
                        seen.add(sha)
                        commits.append(sha)

    return commits


def should_skip_capture(status: int | None, content_type: str | None, body_text: str) -> tuple[bool, str]:
    """Return whether a capture should be skipped due to error-like response/page."""
    ct = (content_type or "").lower()
    text = (body_text or "").strip()
    compact = re.sub(r"\s+", "", text[:2000])

    if status is not None and status >= 400:
        return True, f"http_status_{status}"

    if "application/json" in ct:
        return True, "json_response"

    # Common app error payload shown as raw JSON in the browser.
    if compact.startswith("{") and '"status":500' in compact and '"unhandled":true' in compact:
        return True, "error_payload"

    return False, ""


def capture_routes(playwright_mod, url: str, routes: list[str],
                   output_prefix: str, label: str) -> tuple[list[dict], list[dict]]:
    """Capture screenshots of routes using Playwright."""
    from playwright.sync_api import sync_playwright

    captures = []
    skipped = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})

        for route in routes:
            route = route.strip()
            if not route:
                continue

            full_url = url.rstrip("/") + "/" + route.lstrip("/")
            safe_route = route.replace("/", "_").strip("_") or "index"
            filename = f"{output_prefix}-{safe_route}-{label}.png"

            try:
                response = page.goto(full_url, wait_until="networkidle", timeout=15000)
                status = response.status if response else None
                content_type = response.header_value("content-type") if response else ""
                try:
                    body_text = page.locator("body").inner_text(timeout=2000)
                except Exception:
                    body_text = ""

                skip, reason = should_skip_capture(status, content_type, body_text)
                if skip:
                    skipped.append({
                        "route": route,
                        "label": label,
                        "url": full_url,
                        "reason": reason,
                        "status": status,
                    })
                    print(
                        f"  Skipped {full_url} ({reason})",
                        file=sys.stderr,
                    )
                    continue

                page.screenshot(path=filename, full_page=False)
                captures.append({
                    "route": route,
                    "path": filename,
                    "label": label,
                    "url": full_url,
                    "status": status,
                })
                print(f"  Captured {full_url} -> {filename}", file=sys.stderr)
            except Exception as e:
                print(f"  Warning: Failed to capture {full_url}: {e}", file=sys.stderr)

        browser.close()

    return captures, skipped


def main():
    parser = argparse.ArgumentParser(
        description="Capture screenshots by checking out git commits and screenshotting"
    )
    parser.add_argument(
        "--walkthrough", required=True,
        help="Path to walkthrough.json",
    )
    parser.add_argument(
        "--repo-root", required=True,
        help="Path to the git repository root",
    )
    parser.add_argument(
        "--dev-cmd", required=True,
        help="Command to start the dev server (e.g., 'npm run dev')",
    )
    parser.add_argument(
        "--url", required=True,
        help="URL to check for server readiness (e.g., http://localhost:3000)",
    )
    parser.add_argument(
        "--routes", default="/",
        help="Comma-separated routes to capture (e.g., '/,/login,/dashboard')",
    )
    parser.add_argument(
        "--output-dir", default="out/captures",
        help="Directory for output screenshots",
    )
    parser.add_argument(
        "--commits", default="",
        help="Comma-separated commit SHAs to capture (overrides auto-detection)",
    )
    parser.add_argument(
        "--server-timeout", type=int, default=30,
        help="Seconds to wait for dev server to start (default: 30)",
    )
    args = parser.parse_args()

    if not check_playwright():
        sys.exit(1)

    # Load walkthrough
    with open(args.walkthrough) as f:
        walkthrough = json.load(f)

    # Parse routes
    routes = [r.strip() for r in args.routes.split(",") if r.strip()]

    # Determine commits
    if args.commits:
        commits = [c.strip() for c in args.commits.split(",") if c.strip()]
    else:
        commits = extract_key_commits(walkthrough)

    if not commits:
        print("No commits found to capture. Use --commits to specify manually.", file=sys.stderr)
        sys.exit(1)

    print(f"Will capture {len(routes)} route(s) at {len(commits)} commit(s)", file=sys.stderr)

    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    repo_root = Path(args.repo_root).resolve()
    all_captures = []
    manifest_entries = {}
    skipped_entries = {}

    for i, sha in enumerate(commits):
        worktree_path = tempfile.mkdtemp(prefix=f"wt-capture-{sha[:8]}-")
        print(f"\n[{i+1}/{len(commits)}] Processing commit {sha[:8]}...", file=sys.stderr)
        server_proc = None

        try:
            # Create worktree
            subprocess.run(
                ["git", "worktree", "add", worktree_path, sha],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            print(f"  Warning: Failed to create worktree for {sha}: {e.stderr}", file=sys.stderr)
            continue

        try:
            # Install dependencies
            install_cmd = detect_install_cmd(worktree_path)
            if install_cmd:
                print(f"  Installing deps: {' '.join(install_cmd)}", file=sys.stderr)
                result = subprocess.run(
                    install_cmd,
                    cwd=worktree_path,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if result.returncode != 0:
                    print(f"  Warning: Dependency install failed: {result.stderr[:200]}", file=sys.stderr)
                    continue

            # Start dev server
            print(f"  Starting dev server: {args.dev_cmd}", file=sys.stderr)
            server_proc = subprocess.Popen(
                args.dev_cmd,
                shell=True,
                cwd=worktree_path,
                # Avoid deadlocks from unconsumed child output buffers.
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=os.setsid,
            )

            # Wait for server
            if not wait_for_server(args.url, timeout=args.server_timeout):
                print(f"  Warning: Server failed to start within {args.server_timeout}s", file=sys.stderr)
                continue

            # Capture screenshots
            step_id = f"commit-{sha[:8]}"
            output_prefix = str(output_dir / step_id)
            captures, skipped = capture_routes(
                None, args.url, routes, output_prefix, f"commit-{sha[:8]}"
            )
            for item in captures:
                item["commit_sha"] = sha
                item["commit_short"] = sha[:8]
                item["commit_key"] = step_id
            all_captures.extend(captures)

            if step_id not in manifest_entries:
                manifest_entries[step_id] = []
            manifest_entries[step_id].extend(captures)

            if step_id not in skipped_entries:
                skipped_entries[step_id] = []
            skipped_entries[step_id].extend(skipped)

        except Exception as e:
            print(f"  Warning: Error processing {sha}: {e}", file=sys.stderr)

        finally:
            # Kill dev server
            try:
                if server_proc and server_proc.poll() is None:
                    os.killpg(os.getpgid(server_proc.pid), signal.SIGTERM)
                    server_proc.wait(timeout=5)
            except Exception:
                try:
                    if server_proc and server_proc.poll() is None:
                        os.killpg(os.getpgid(server_proc.pid), signal.SIGKILL)
                except Exception:
                    pass

            # Remove worktree
            try:
                subprocess.run(
                    ["git", "worktree", "remove", "--force", worktree_path],
                    cwd=str(repo_root),
                    capture_output=True,
                    text=True,
                )
            except Exception:
                # Fallback: manual cleanup
                shutil.rmtree(worktree_path, ignore_errors=True)
                try:
                    subprocess.run(
                        ["git", "worktree", "prune"],
                        cwd=str(repo_root),
                        capture_output=True,
                    )
                except Exception:
                    pass

    # Write manifest
    manifest = {
        "captures": manifest_entries,
        "skipped": skipped_entries,
        "commit_order": [f"commit-{sha[:8]}" for sha in commits],
        "routes": routes,
        "total_screenshots": len(all_captures),
    }
    manifest_path = output_dir / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(
        f"\nDone: {len(all_captures)} screenshots captured, "
        f"manifest at {manifest_path}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
