---
name: memwatch
description: "Investigate RAM and GPU VRAM pressure on the Fedora laptop: what is consuming memory, how much tmpfs and zram are hiding, which GPU tenants hold VRAM, and what the OOM killer has recently killed. Use when available memory is low, something was OOM-killed, push-to-talk stops transcribing, the machine feels starved, or the user asks what is eating memory. Trigger: /memwatch"
---

# /memwatch

A one-shot memory and VRAM investigator for this 15.2 GB laptop with a contended
6 GB RTX 3050. It exists because the default tools miss the two things that
actually cause OOM kills here.

## Usage

```bash
~/.claude/skills/memwatch/scripts/memwatch              # one snapshot
~/.claude/skills/memwatch/scripts/memwatch --no-podman  # skip container stats (~1s faster)
~/.claude/skills/memwatch/scripts/memwatch -w           # refresh every 2s
```

Prefer the one-shot form. `-w` occupies a terminal, and the user would rather
have btop there.

## Reach for btop first

btop is configured for this machine already (`~/.config/btop/btop.conf`) and the
user likes it. It shows GPU and VRAM via the `gpu0` box and, critically,
`only_physical = False` so **tmpfs mounts are visible** rather than hidden.

**Height trap:** the real terminal is **144x28**. A layout with both the `cpu`
box and a separate `gpu0` box needs **36 rows**, and btop then refuses to start
with "Terminal size too small" rather than degrading. Default is now
`mem proc gpu0` (fits 28), with the classic `cpu mem net proc` on preset 2 via
`p` / `shift+p`. `show_gpu_info` alone does NOT put GPU stats in the cpu box
here; it only adds a `gpu-totals` toggle label, so a visible GPU needs `gpu0`.
Verify any layout change in a pty before claiming it works.

Use this skill when btop is not enough, specifically for:

- **tmpfs totals per mount.** `/tmp` is RAM-backed on this box. 3.3 GB has sat
  there unnoticed. It is attributed to no process, so a per-process hunt finds
  nothing.
- **zram.** Swap is compressed RAM here, so a full swap is pressure, not relief.
- **GPU tenants named.** Resolves each VRAM holder to its service or container
  rather than a bare pid.
- **OOM-kill history,** last 24h, flagging whisper as the deliberate canary.
- **PTT canary state** plus how many recordings are sitting in the spool.

## Reading the output

- `available` is the number that predicts an OOM kill, not `used`.
- A `whisper-gpu / python3` OOM kill is **expected and informative**: PTT is the
  user's deliberate canary, so it means go look at memory, not go protect
  whisper. Never add `OOMScoreAdjust` or `MemoryMin` to it.
- The usual heavy tenants are `llama-embed-gpu` (~2.2 GB, must stay resident,
  it is the LiteLLM primary for four VPS services) and `/tmp`. `rerank-gpu` is
  socket-activated since 2026-10-05 and should normally be absent.
- Recordings in the spool are recovered with `voice-hotkey-drain`.

## Planned upgrade, not yet done

The user's verdict on 2026-10-05: **"what you created looks nothing like btop"**,
and running it meant losing btop from the screen. Both fair. When this is next
revisited, the direction is:

1. **Look and feel like btop**, because that is the interface the user already
   reads fluently: boxed panels with rounded borders, braille or block meter
   bars, the same colour language (green through yellow to red by severity), a
   header line, and box titles. Right now it is flat uncoloured text.
2. **Do not replace btop, complement it.** Either render in a small fixed region
   that can sit beside btop, or better, feed btop instead of competing with it
   and keep this for the panels btop structurally cannot show (tmpfs breakdown,
   OOM history, GPU tenants by unit, PTT canary).
3. **Consider a real TUI** rather than reprinting: a curses or textual layout
   with stable panel geometry, so `-w` does not flicker and redraw the screen.
4. **Keep the one-shot path fast and plain** for piping into a report.

Do not start this rewrite unprompted. It is queued for when the user next asks
to take a closer look at memory.
