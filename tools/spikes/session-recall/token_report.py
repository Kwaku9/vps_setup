#!/usr/bin/env python3
"""Token-length report for session transcripts using the Nomic tokenizer.

Run inside the spike-tools container on enterprise_network (DB + nomic-embed
are only reachable there):

    ./run.sh token_report.py                      # user+assistant, http tokenizer
    ./run.sh token_report.py --dataset useronly   # just user turns
    ./run.sh token_report.py --chunk-size 2048    # model the n_ctx_train cap

Backends:
  http (default) -- POST to the live nomic-embed llama.cpp /tokenize endpoint;
                    uses the exact GGUF WordPiece vocab the embedder runs on.
                    No extra deps (only `requests`, already in the image).
  hf             -- transformers AutoTokenizer for nomic-ai/nomic-embed-text-v1.5
                    (same vocab); needs `pip install transformers`.

Transcripts are built exactly like the real pipeline (datasets.build_transcript)
but are measured UN-truncated, so the distribution shows what the current
6000-char truncation in datasets.iter_nomic_docs actually drops.
"""
import argparse
import math
import statistics
from collections import Counter

import requests

import db
from config import NOMIC_BASE
from datasets import build_transcript

TOKENIZE_URL = NOMIC_BASE.rstrip("/").removesuffix("/v1") + "/tokenize"
HF_NAME = "nomic-ai/nomic-embed-text-v1.5"  # BERT WordPiece, 768-dim model
TRUNC_CHARS = 6000  # current cap in datasets.iter_nomic_docs (what prod drops today)


# ---- tokenizer backends -----------------------------------------------------

def http_tokenizer():
    """Return count(text) using the live nomic-embed /tokenize endpoint."""
    sess = requests.Session()

    def count(text):
        r = sess.post(TOKENIZE_URL, json={"content": text}, timeout=120)
        r.raise_for_status()
        return len(r.json().get("tokens", []))

    return count


def hf_tokenizer():
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(HF_NAME)

    def count(text):
        return len(tok(text, add_special_tokens=True, truncation=False)["input_ids"])

    return count


# ---- data -------------------------------------------------------------------

def iter_full_transcripts(conn, dataset):
    """Yield (session_uuid, full transcript) — mirrors datasets.iter_nomic_docs
    but WITHOUT the 6000-char truncation, one row per session."""
    sql = """
        SELECT s.session_uuid,
               array_agg(m.type ORDER BY m.sequence_num) AS types,
               array_agg(m.content_text ORDER BY m.sequence_num) AS texts
        FROM sessions.sessions s
        JOIN sessions.messages m ON m.session_id = s.id
        WHERE m.content_text IS NOT NULL AND length(trim(m.content_text)) > 0
        GROUP BY s.session_uuid
    """
    cur = conn.cursor(name="token_report")  # server-side: stream, don't buffer all
    cur.itersize = 200
    cur.execute(sql)
    for uuid, types, texts in cur:
        transcript = build_transcript(list(zip(types, texts)), dataset)
        if transcript:
            yield uuid, transcript
    cur.close()


# ---- reporting --------------------------------------------------------------

def histogram(counts, edges):
    buckets = [0] * (len(edges) + 1)
    for c in counts:
        for i, e in enumerate(edges):
            if c < e:
                buckets[i] += 1
                break
        else:
            buckets[-1] += 1
    labels, prev = [], 0
    for e in edges:
        labels.append(f"{prev}-{e}")
        prev = e
    labels.append(f"{edges[-1]}+")
    return list(zip(labels, buckets))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", choices=["useronly", "userasst"], default="userasst",
                    help="which turns to include (default: userasst = user+assistant)")
    ap.add_argument("--backend", choices=["http", "hf"], default="http",
                    help="tokenizer backend (default: http = live nomic /tokenize)")
    ap.add_argument("--chunk-size", type=int, default=8192,
                    help="tokens per chunk (default 8192 = live nomic-embed --ctx-size)")
    args = ap.parse_args()

    count = hf_tokenizer() if args.backend == "hf" else http_tokenizer()
    src = HF_NAME + " (transformers)" if args.backend == "hf" else TOKENIZE_URL
    print(f"Tokenizing dataset={args.dataset} via {src} ...")

    conn = db.connect()
    token_counts, trunc_chars = [], []
    n = 0
    for _uuid, transcript in iter_full_transcripts(conn, args.dataset):
        token_counts.append(count(transcript))
        trunc_chars.append(len(transcript))
        n += 1
        if n % 100 == 0:
            print(f"  ...{n} sessions")
    conn.close()

    if not token_counts:
        print("No sessions found.")
        return

    cs = args.chunk_size
    chunk_counts = [max(1, math.ceil(t / cs)) for t in token_counts]
    over_cap = sum(1 for t in token_counts if t > cs)
    trunc_hit = sum(1 for ch in trunc_chars if ch > TRUNC_CHARS)
    total = len(token_counts)
    qs = statistics.quantiles(token_counts, n=100)

    print("\n================ TOKEN-LENGTH SUMMARY ================")
    print(f"dataset               : {args.dataset}")
    print(f"sessions analysed     : {total}")
    print(f"avg tokens / session  : {statistics.mean(token_counts):.1f}")
    print(f"median tokens         : {statistics.median(token_counts):.0f}")
    print(f"min / max tokens      : {min(token_counts)} / {max(token_counts)}")
    print(f"p90 / p95 / p99       : {qs[89]:.0f} / {qs[94]:.0f} / {qs[98]:.0f}")
    print(f"total tokens (corpus) : {sum(token_counts):,}")

    print("\n--- token-length distribution (sessions per bucket) ---")
    for label, cnt in histogram(token_counts, [256, 512, 1024, 2048, 4096, 8192, 16384]):
        bar = "#" * (cnt * 40 // total)
        print(f"  {label:>13} tok : {cnt:5d}  {bar}")

    print(f"\n--- chunks required @ {cs} tokens/chunk ---")
    dist = Counter(chunk_counts)
    for k in sorted(dist):
        print(f"  {k:2d} chunk(s) : {dist[k]:5d} session(s)")
    print(f"\ntotal chunks needed   : {sum(chunk_counts):,}")
    print(f"avg chunks / session  : {statistics.mean(chunk_counts):.2f}")
    print(f"sessions > {cs} tok    : {over_cap} ({100 * over_cap / total:.1f}%)")
    print(f"\ncurrent prod truncation = {TRUNC_CHARS} chars (single vector per session)")
    print(f"sessions exceeding it : {trunc_hit} ({100 * trunc_hit / total:.1f}%) "
          f"-> tail dropped today")


if __name__ == "__main__":
    main()
