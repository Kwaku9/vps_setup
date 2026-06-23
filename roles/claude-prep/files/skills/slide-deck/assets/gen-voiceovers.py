#!/usr/bin/env python3
"""Generate per-slide voiceovers for a reveal.js deck using the local Voicebox
TTS server with the Qwen "Him-Mentor" cloned profile.

Each top-level <section>'s <aside class="notes"> is the narration for that slide.
Output: <deck-dir>/voiceovers/slide-<i>.wav  (i = reveal horizontal index, 0-based),
which the deck plays on slide change when narration is toggled on.

Usage:
  python3 gen-voiceovers.py bruce-deck.html
  python3 gen-voiceovers.py bruce-deck.html --profile <id> --voicebox http://localhost:17493
Requires the Voicebox server running (./serve note in voicebox/). Stdlib only.
"""
import argparse
import html
import json
import os
import re
import sys
import urllib.request

DEFAULT_PROFILE = "7f5a70c8-4ec9-4be1-9a38-cc15568f03f1"  # Qwen "Him-Mentor"
DEFAULT_VOICEBOX = "http://localhost:17493"


# TTS pronunciation fixes — applied to the narration text right BEFORE synthesis, so the
# on-screen speaker notes and the narration.md companion stay clean/readable while the audio
# says it right. Qwen3-TTS otherwise says "LiveKit" with a short-i ("livkit") and stumbles on
# "widget". Add (word -> respelling) pairs here as new mispronunciations turn up.
def apply_pronunciations(text: str) -> str:
    text = re.sub(r"\bLiveKit\b", "LyveKit", text, flags=re.I)     # long-i: "Lyve-Kit" (also catches livekit-agent)
    def _widget(m):
        w = m.group(0)
        base = "Wid-git" if w[0].isupper() else "wid-git"
        return base + ("s" if w.lower().endswith("s") else "")
    text = re.sub(r"\bwidgets?\b", _widget, text, flags=re.I)      # "wid-git"
    def _gemini(m):
        return "Geminye" if m.group(0)[0].isupper() else "geminye"
    text = re.sub(r"\bgemini\b", _gemini, text, flags=re.I)        # "gem-in-eye"
    text = re.sub(r"\blitellm\b", "light LLM", text, flags=re.I)   # "light-L-L-M"
    text = re.sub(r"\bLive[ -]?Avatar\b", "Lyve Avatar", text, flags=re.I)   # "Lyve Avatar" (also live-avatar / LiveAvatar)
    text = re.sub(r"vision_io\.py", "vizion I O dot pie", text, flags=re.I)  # bruce file: "vizion-I-O-dot-pie"
    text = re.sub(r"vision_io", "vizion I O", text, flags=re.I)              # bare vision_io (no .py)
    text = re.sub(r"\bvps_setup\b", "V P S setup", text, flags=re.I)         # repo name
    text = re.sub(r"\bvps\b", "V P S", text, flags=re.I)                     # acronym: spell it out
    def _pg(m):
        return "Post-gress" if m.group(0)[0].isupper() else "post-gress"
    text = re.sub(r"\bpostgres\b", _pg, text, flags=re.I)                    # "Post-gress"
    return text


def slides_notes(deck_html: str):
    """Return [(index, narration_text)] for each top-level <section> with notes."""
    sections = re.findall(r"<section\b[^>]*>(.*?)</section>", deck_html, re.S | re.I)
    out = []
    for i, body in enumerate(sections):
        m = re.search(r'<aside\s+class="notes">(.*?)</aside>', body, re.S | re.I)
        if not m:
            continue
        text = re.sub(r"<[^>]+>", " ", m.group(1))      # strip tags
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            out.append((i, text))
    return out


def synth(text, out_path, voicebox, profile, model_size="0.6B"):
    payload = json.dumps({
        "profile_id": profile, "text": text,
        "engine": "qwen", "model_size": model_size,
        "language": "en", "normalize": True,
    }).encode()
    req = urllib.request.Request(
        f"{voicebox}/generate/stream", data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=900) as resp:
        data = resp.read()
    with open(out_path, "wb") as f:
        f.write(data)
    return len(data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("deck")
    ap.add_argument("--profile", default=os.environ.get("VOICEBOX_PROFILE_ID", DEFAULT_PROFILE))
    ap.add_argument("--voicebox", default=os.environ.get("VOICEBOX_API", DEFAULT_VOICEBOX))
    ap.add_argument("--model-size", dest="model_size",
                    default=os.environ.get("VOICEBOX_MODEL_SIZE", "0.6B"), choices=["0.6B", "1.7B"],
                    help="Qwen3-TTS backbone: 0.6B (fits 6GB GPU, default) or 1.7B (higher quality, more VRAM/time)")
    ap.add_argument("--out-dir", dest="out_dir", default="voiceovers",
                    help="output dir name under the deck dir (e.g. vo-bruce). Default: voiceovers")
    ap.add_argument("--only", default=None,
                    help="comma-separated slide indices to (re)record, e.g. 1,2,5 (default: all slides)")
    args = ap.parse_args()

    deck_path = os.path.abspath(args.deck)
    deck_dir = os.path.dirname(deck_path)
    vo_dir = os.path.join(deck_dir, args.out_dir)
    os.makedirs(vo_dir, exist_ok=True)

    # health check + confirm the profile exists / its name
    try:
        with urllib.request.urlopen(f"{args.voicebox}/health", timeout=5) as r:
            r.read()
    except Exception as e:
        sys.exit(f"Voicebox not reachable at {args.voicebox} ({e}).\n"
                 f"Start it:  cd ~/Projects/VScdeProjects/voicebox && podman-compose up -d")
    try:
        with urllib.request.urlopen(f"{args.voicebox}/profiles", timeout=5) as r:
            profs = json.load(r)
        name = next((p.get("name") for p in profs if p.get("id") == args.profile), None)
        print(f"profile {args.profile} -> {name or '(name unknown — proceeding)'}")
    except Exception:
        print(f"(could not list profiles; using {args.profile})")

    notes = slides_notes(open(deck_path, encoding="utf-8").read())
    if not notes:
        sys.exit("no <aside class='notes'> slides found")
    if args.only:
        want = {int(x) for x in args.only.split(",") if x.strip() != ""}
        notes = [(i, t) for (i, t) in notes if i in want]
        if not notes:
            sys.exit(f"--only {args.only}: no slides with notes match those indices")
    print(f"{len(notes)} slide(s) to narrate (Qwen3-TTS-12Hz-{args.model_size}-Base) -> {vo_dir}/")
    for idx, text in notes:
        spoken = apply_pronunciations(text)       # phonetic fixes (LiveKit->LyveKit, widget->wid-git)
        if spoken != text:
            print(f"  slide {idx}: applied pronunciation fix")
        out = os.path.join(vo_dir, f"slide-{idx}.wav")
        print(f"  slide {idx}: {len(spoken)} chars … ", end="", flush=True)
        try:
            n = synth(spoken, out, args.voicebox, args.profile, args.model_size)
            print(f"{n//1024} KB wav")
        except Exception as e:
            print(f"FAILED ({e})")
    print("done. Toggle 🔊 Narration in the deck to hear them.")


if __name__ == "__main__":
    main()
