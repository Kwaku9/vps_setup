#!/usr/bin/env python3
"""Teach OpenWebUI to honour pre-chunked documents. Runs INSIDE the container.

Why
---
OpenWebUI re-chunks every uploaded file with its own splitter, so a producer that
has already decided its chunk boundaries cannot get them into the vector store.
Measured on the DSM-5-TR corpus: the chunker emitted 7,013 chunks, OWUI stored
6,132 of its own. Diagnostic criteria sets were being cut mid-definition as a
result, and no CHUNK_SIZE value fixes it - the corpus has deliberately variable
chunk sizes (criteria up to ~10k chars, narrative ~735 median), so a small size
splits the criteria and a large one merges unrelated chunks together.

What this patch does
--------------------
Before OWUI's splitter runs, any document whose text contains the sentinel
delimiter is split on that delimiter ALONE - never on size - and handed straight
to the embedder. Everything else follows the existing code path untouched.

That last property is the point of this design. `TEXT_SPLITTER`, `CHUNK_SIZE`
and `CHUNK_OVERLAP` are GLOBAL config in OpenWebUI, so changing them to suit one
knowledge base silently changes ingest for every other one. Detecting a sentinel
in the content instead makes the behaviour opt-in per document: a file that does
not contain it is chunked exactly as before, and no other collection is affected.

The patch is additive (two inserted blocks, nothing rewritten), marker-guarded so
re-running is a no-op, and reversible with --revert.

Usage (inside the container):
    python3 owui_prechunk_patch.py [--verify | --revert]

The delimiter defaults to "\\n<!--owui-chunk-->\\n" and can be overridden with the
RAG_CHUNK_DELIMITER environment variable on the container.
"""
import os
import sys

TARGET = "/app/backend/open_webui/routers/retrieval.py"
MARK = "ANSIBLE-PATCH:owui-prechunk"
MARK2 = "ANSIBLE-PATCH:owui-prechunk-presplit"

ANCHOR_SPLIT = "    if split:\n"
ANCHOR_MERGE = "    if len(docs) == 0:\n"

BLOCK_SPLIT = '''    # ANSIBLE-PATCH:owui-prechunk BEGIN - honour producer-defined chunk boundaries.
    # A document containing the sentinel has already been chunked upstream; split
    # it on the sentinel only and keep it away from every size-based splitter.
    # Documents without the sentinel fall through completely unchanged, so no
    # other knowledge base is affected by this patch.
    _owui_delim = os.environ.get("RAG_CHUNK_DELIMITER", "\\n<!--owui-chunk-->\\n")
    _owui_predocs = []
    if split and _owui_delim:
        _owui_rest = []
        for _owui_doc in docs:
            if _owui_delim in _owui_doc.page_content:
                for _owui_piece in _owui_doc.page_content.split(_owui_delim):
                    _owui_piece = _owui_piece.strip()
                    if _owui_piece:
                        _owui_predocs.append(
                            Document(
                                page_content=_owui_piece,
                                metadata={**_owui_doc.metadata},
                            )
                        )
            else:
                _owui_rest.append(_owui_doc)
        docs = _owui_rest
    # ANSIBLE-PATCH:owui-prechunk END
'''

# --- part 2: do not re-split chunks that are already chunks -----------------
# /knowledge/{id}/file/add does NOT use the stored file content. It reads the
# rows back out of the per-file `file-{id}` collection, which are ALREADY split,
# and hands them to save_docs_to_vector_db with split defaulting to True. Each
# stored chunk is then split again by CHUNK_SIZE.
#
# For stock OpenWebUI that is invisible: chunks are already <= CHUNK_SIZE, so
# re-splitting is a no-op. For any producer-defined chunking it is destructive -
# it silently undid part 1 of this patch, turning 4,414 correct chunks into
# 6,257 re-cut ones, with every criteria set chopped back to 1,000 chars.
#
# The flag records "these docs came from the per-file collection", and the
# save call then passes split=False for exactly that case. The other branch
# (per-file collection empty -> full stored content) still splits normally.
ANCHOR_INIT = "            if form_data.content:\n"
BLOCK_INIT = '''            # ANSIBLE-PATCH:owui-prechunk-presplit BEGIN
            _owui_presplit = False
            # ANSIBLE-PATCH:owui-prechunk-presplit END
'''

ANCHOR_SETFLAG = ("                if result is not None and len(result.ids[0]) > 0:\n"
                  "                    docs = [\n")
BLOCK_SETFLAG = ('''                if result is not None and len(result.ids[0]) > 0:
                    _owui_presplit = True   # ANSIBLE-PATCH:owui-prechunk-presplit
                    docs = [
''')

ANCHOR_USEFLAG = ("                        add=(True if form_data.collection_name else False),\n"
                  "                        user=user,\n"
                  "                    )\n")
BLOCK_USEFLAG = ('''                        add=(True if form_data.collection_name else False),
                        split=not _owui_presplit,   # ANSIBLE-PATCH:owui-prechunk-presplit
                        user=user,
                    )
''')

BLOCK_MERGE = '''    # ANSIBLE-PATCH:owui-prechunk-merge BEGIN
    if _owui_predocs:
        log.info(
            f"owui-prechunk: {len(_owui_predocs)} pre-chunked docs embedded "
            f"as-is; {len(docs)} docs went through the normal splitter"
        )
        docs = _owui_predocs + list(docs)
    # ANSIBLE-PATCH:owui-prechunk-merge END
'''


def read():
    with open(TARGET) as f:
        return f.read()


def write(src):
    with open(TARGET, "w") as f:
        f.write(src)


def verify(src):
    """Both blocks present, in the right order, and the file still compiles."""
    ok = True
    if src.count(BLOCK_SPLIT) != 1:
        print("  FAIL: split block not present exactly once")
        ok = False
    if src.count(BLOCK_MERGE) != 1:
        print("  FAIL: merge block not present exactly once")
        ok = False
    for label, blk in (("init", BLOCK_INIT), ("setflag", BLOCK_SETFLAG),
                       ("useflag", BLOCK_USEFLAG)):
        if src.count(blk) != 1:
            print(f"  FAIL: presplit {label} block not present exactly once")
            ok = False
    if ok and src.index(BLOCK_SPLIT) > src.index(BLOCK_MERGE):
        print("  FAIL: blocks are in the wrong order")
        ok = False
    try:
        compile(src, TARGET, "exec")
    except SyntaxError as e:
        print(f"  FAIL: patched file does not compile: {e}")
        ok = False
    return ok


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--apply"
    src = read()

    if mode == "--verify":
        if MARK not in src or MARK2 not in src:
            print("NOT-PATCHED")
            sys.exit(1)
        print("PATCHED" if verify(src) else "PATCHED-BUT-INVALID")
        sys.exit(0 if verify(src) else 1)

    if mode == "--revert":
        if MARK not in src:
            print("unchanged: not patched")
            sys.exit(0)
        src = (src.replace(BLOCK_SPLIT, "").replace(BLOCK_MERGE, "")
                  .replace(BLOCK_INIT, "")
                  .replace(BLOCK_SETFLAG, ANCHOR_SETFLAG)
                  .replace(BLOCK_USEFLAG, ANCHOR_USEFLAG))
        compile(src, TARGET, "exec")
        write(src)
        print("reverted")
        sys.exit(0)

    # ---- apply ----
    if MARK in src and MARK2 in src:
        print("unchanged: already patched")
        sys.exit(0)
    if MARK in src and MARK2 not in src:
        # part 1 installed by an earlier version; add part 2 only
        for name, anchor, want in (("init", ANCHOR_INIT, 1),
                                   ("setflag", ANCHOR_SETFLAG, 1),
                                   ("useflag", ANCHOR_USEFLAG, 1)):
            if src.count(anchor) != want:
                sys.exit(f"ABORT: presplit anchor {name!r} found {src.count(anchor)}x")
        src = src.replace(ANCHOR_INIT, BLOCK_INIT + ANCHOR_INIT, 1)
        src = src.replace(ANCHOR_SETFLAG, BLOCK_SETFLAG, 1)
        src = src.replace(ANCHOR_USEFLAG, BLOCK_USEFLAG, 1)
        if not verify(src):
            sys.exit("ABORT: refusing to write an invalid patch")
        write(src)
        print("patched")
        sys.exit(0)

    # Anchor on unique lines. If upstream refactors this function these counts
    # change, and we fail loudly rather than patching the wrong place.
    for name, anchor, want in (("split", ANCHOR_SPLIT, 1),
                               ("merge", ANCHOR_MERGE, 1),
                               ("init", ANCHOR_INIT, 1),
                               ("setflag", ANCHOR_SETFLAG, 1),
                               ("useflag", ANCHOR_USEFLAG, 1)):
        got = src.count(anchor)
        if got != want:
            print(f"ABORT: anchor {name!r} found {got}x, expected {want}x - "
                  f"OpenWebUI's retrieval.py has changed shape. Re-check the "
                  f"patch against the new source before forcing it.")
            sys.exit(2)

    src = src.replace(ANCHOR_SPLIT, BLOCK_SPLIT + ANCHOR_SPLIT, 1)
    src = src.replace(ANCHOR_MERGE, BLOCK_MERGE + ANCHOR_MERGE, 1)
    src = src.replace(ANCHOR_INIT, BLOCK_INIT + ANCHOR_INIT, 1)
    src = src.replace(ANCHOR_SETFLAG, BLOCK_SETFLAG, 1)
    src = src.replace(ANCHOR_USEFLAG, BLOCK_USEFLAG, 1)

    if not verify(src):
        print("ABORT: refusing to write an invalid patch")
        sys.exit(3)

    write(src)
    print("patched")


if __name__ == "__main__":
    main()
