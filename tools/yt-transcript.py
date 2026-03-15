#!/usr/bin/env python3
"""Extract YouTube video transcript as plain text.

Usage:
    yt-transcript.py <url-or-video-id> [--timestamps]

Primary: yt-dlp with cookies (same method as Fabric AI).
Fallback: CF Worker proxy, then youtube-transcript-api.
"""

import sys
import re
import os
import glob
import argparse
import subprocess
import tempfile
import urllib.request
import urllib.error

COOKIES_PATH = "/root/cookies.txt"
WORKER_URL = "https://yt-transcript.aicortex.workers.dev"


def extract_video_id(url_or_id: str) -> str:
    """Extract video ID from various YouTube URL formats or bare ID."""
    patterns = [
        r'(?:youtu\.be/)([a-zA-Z0-9_-]{11})',
        r'(?:youtube\.com/watch\?.*v=)([a-zA-Z0-9_-]{11})',
        r'(?:youtube\.com/embed/)([a-zA-Z0-9_-]{11})',
        r'(?:youtube\.com/shorts/)([a-zA-Z0-9_-]{11})',
        r'(?:youtube\.com/live/)([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)
    if re.match(r'^[a-zA-Z0-9_-]{11}$', url_or_id):
        return url_or_id
    print(f"Error: Could not extract video ID from: {url_or_id}", file=sys.stderr)
    sys.exit(1)


def make_video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def parse_vtt(vtt_path: str, with_timestamps: bool = False) -> str:
    """Parse VTT subtitle file into clean text (same logic as Fabric AI)."""
    with open(vtt_path, 'r', encoding='utf-8') as f:
        content = f.read()

    lines = content.split('\n')
    text_lines = []
    seen = set()

    for line in lines:
        line = line.strip()
        # Skip VTT headers, timestamps, empty lines, metadata
        if not line:
            continue
        if line == 'WEBVTT':
            continue
        if line.startswith('Kind:') or line.startswith('Language:'):
            continue
        if line.startswith('NOTE') or line.startswith('STYLE'):
            continue
        # Skip timestamp lines (e.g., "00:00:01.234 --> 00:00:03.456")
        if '-->' in line:
            if with_timestamps:
                # Extract start timestamp for the next text line
                ts_match = re.match(r'(\d{2}):(\d{2}):(\d{2})', line)
                if ts_match:
                    current_ts = f"[{ts_match.group(1)}:{ts_match.group(2)}:{ts_match.group(3)}]"
                else:
                    current_ts = None
            continue
        # Skip numeric cue identifiers
        if re.match(r'^\d+$', line):
            continue
        # Strip VTT formatting tags
        clean = re.sub(r'<[^>]*>', '', line)
        clean = clean.strip()
        if not clean:
            continue

        if with_timestamps:
            ts = locals().get('current_ts', '')
            if ts:
                text_lines.append(f"{ts} {clean}")
                current_ts = None
            else:
                text_lines.append(clean)
        else:
            # Deduplicate (Fabric behavior)
            if clean not in seen:
                seen.add(clean)
                text_lines.append(clean)

    return '\n'.join(text_lines)


def get_transcript_ytdlp(video_id: str, with_timestamps: bool = False) -> str:
    """Fetch transcript using yt-dlp with cookies (same as Fabric AI)."""
    if not os.path.exists(COOKIES_PATH):
        raise FileNotFoundError(f"Cookies file not found at {COOKIES_PATH}")

    tmpdir = tempfile.mkdtemp(prefix=f"yt-transcript-{video_id}-")
    output_template = os.path.join(tmpdir, "%(title)s.%(ext)s")

    args = [
        "yt-dlp",
        "--cookies", COOKIES_PATH,
        "--write-auto-subs",
        "--skip-download",
        "--sub-format", "vtt",
        "--sub-langs", "en,en.*",
        "-o", output_template,
        make_video_url(video_id),
    ]

    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=60)

        if result.returncode != 0:
            # Check for known errors
            output = result.stderr + result.stdout
            if "Sign in to confirm" in output or "bot" in output.lower():
                raise Exception("YouTube bot detection — cookies may be expired")
            if "429" in output or "Too Many Requests" in output:
                raise Exception("YouTube rate limit exceeded")
            raise Exception(f"yt-dlp failed: {output[:300]}")

        # Find VTT files
        vtt_files = glob.glob(os.path.join(tmpdir, "*.vtt"))
        if not vtt_files:
            raise Exception("No subtitle files downloaded")

        # Prefer English, fall back to first available
        en_files = [f for f in vtt_files if '.en.' in f or '.en-' in f]
        vtt_file = en_files[0] if en_files else vtt_files[0]

        return parse_vtt(vtt_file, with_timestamps)

    finally:
        # Cleanup
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


ESSENTIAL_COOKIES = {
    'SID', 'HSID', 'SSID', 'APISID', 'SAPISID',
    '__Secure-1PSID', '__Secure-3PSID',
    '__Secure-1PAPISID', '__Secure-3PAPISID',
    '__Secure-1PSIDTS', '__Secure-3PSIDTS',
    'LOGIN_INFO', 'PREF', 'YSC', 'VISITOR_INFO1_LIVE',
}


def load_cookies_as_header(cookies_path: str) -> str:
    """Convert Netscape cookies.txt to a Cookie header with essential YouTube cookies only."""
    if not os.path.exists(cookies_path):
        return ""
    cookie_pairs = []
    with open(cookies_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split('\t')
            if len(parts) >= 7:
                name = parts[5]
                value = parts[6]
                if name in ESSENTIAL_COOKIES:
                    cookie_pairs.append(f"{name}={value}")
    return '; '.join(cookie_pairs)


def get_transcript_worker(video_id: str, with_timestamps: bool = False,
                          cookies: str = None) -> str:
    """Fetch transcript via Cloudflare Worker proxy.

    If cookies are provided, sends a POST with cookies for login-required videos.
    Otherwise sends a simple GET for public videos.
    """
    import json as _json

    if cookies:
        url = f"{WORKER_URL}/transcript"
        payload = _json.dumps({
            "v": video_id,
            "timestamps": with_timestamps,
            "cookies": cookies,
        }).encode('utf-8')
        req = urllib.request.Request(url, data=payload, method='POST')
        req.add_header('Content-Type', 'application/json')
    else:
        url = f"{WORKER_URL}/transcript?v={video_id}"
        if with_timestamps:
            url += "&timestamps=true"
        req = urllib.request.Request(url)

    req.add_header('User-Agent', 'yt-transcript/1.0')

    with urllib.request.urlopen(req, timeout=60) as resp:
        text = resp.read().decode('utf-8')
        if text.startswith('Error:'):
            raise Exception(text)
        return text


def main():
    parser = argparse.ArgumentParser(description="Extract YouTube transcript")
    parser.add_argument("url", help="YouTube URL or video ID")
    parser.add_argument("--timestamps", action="store_true",
                        help="Include timestamps in output")
    args = parser.parse_args()

    video_id = extract_video_id(args.url)
    errors = []

    # Method 1: CF Worker (runs on Cloudflare edge — bypasses VPS IP blocks)
    # Worker has internal retries across multiple Innertube clients.
    # We also retry from our side since edge node assignment varies.
    import time as _time
    for attempt in range(3):
        try:
            text = get_transcript_worker(video_id, args.timestamps)
            print(text)
            return
        except Exception as e:
            errors.append(f"worker(attempt {attempt+1}): {e}")
            print(f"CF Worker attempt {attempt+1} failed: {e}", file=sys.stderr)
            if attempt < 2:
                _time.sleep(1)

    # Method 2: CF Worker with cookies (for login-required videos)
    cookies_header = load_cookies_as_header(COOKIES_PATH)
    if cookies_header:
        try:
            text = get_transcript_worker(video_id, args.timestamps, cookies=cookies_header)
            print(text)
            return
        except Exception as e:
            errors.append(f"worker+cookies: {e}")
            print(f"CF Worker (with cookies) failed: {e}", file=sys.stderr)

    # Method 3: yt-dlp with cookies (last resort — VPS IP may be blocked)
    try:
        text = get_transcript_ytdlp(video_id, args.timestamps)
        print(text)
        return
    except Exception as e:
        errors.append(f"yt-dlp: {e}")
        print(f"yt-dlp failed: {e}", file=sys.stderr)

    # All methods failed
    print("Error: All transcript methods failed:", file=sys.stderr)
    for err in errors:
        print(f"  - {err}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
