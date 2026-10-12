#!/usr/bin/env python3
"""Fold doc-audit results (audit/<slug>.json, SCHEMA.md contract) into audit.json.

The audit files describe projects by absolute path. This maps each one onto the
CodeProject / Doc keys the indexer produced (out/code-<root>.json), so
load-audit.cypher can attach class, summary, deployment links and every doc
claim to the right nodes. Audits for paths the indexer does not cover (third-
party clones, external services) are kept as standalone AuditedProject facts.

Audit files hold security findings and never go into the public repo; they live
in /opt/compose/code-graph/audit/ (covered by the nightly backup).

Usage: load_audit.py <audit_dir> <index_out_dir> <output.json>
"""
import glob
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone


def resolve_doc_path(p, project_path):
    """Audit doc paths are relative to the component OR to the repo root, and
    sometimes carry an annotation: "roles/x/defaults/main.yml (header) + ...".
    Strip the annotation, then try the component dir and each ancestor up to /,
    returning the first candidate that exists (else the component-relative guess)."""
    p = re.split(r"\s+[(+]", p.strip(), maxsplit=1)[0].strip()
    if p.startswith("~/"):
        p = "/root/" + p[2:]
    if p.startswith("/"):
        return os.path.normpath(p)
    base = project_path
    while base and base != "/":
        cand = os.path.normpath(os.path.join(base, p))
        if os.path.exists(cand):
            return cand
        base = os.path.dirname(base)
    return os.path.normpath(os.path.join(project_path, p))


def main(audit_dir, out_dir, dest):
    projects, docs_by_abs = {}, {}
    for f in glob.glob(os.path.join(out_dir, "code-*.json")):
        d = json.load(open(f))
        for p in d["projects"]:
            projects[p["path"].rstrip("/")] = p["key"]
        for doc in d["docs"]:
            docs_by_abs[doc["path"]] = doc["key"]

    res = {"run": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "projects": [], "deployed": [], "docs": [], "claims": [], "unmatched_docs": 0}
    for f in sorted(glob.glob(os.path.join(audit_dir, "*.json"))):
        if "frag" in os.path.basename(f):
            continue
        try:
            a = json.load(open(f))
        except Exception:
            continue
        audited_at = datetime.fromtimestamp(os.path.getmtime(f), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        path = (a.get("path") or "").rstrip("/")
        key = projects.get(path)
        slug = os.path.splitext(os.path.basename(f))[0]
        res["projects"].append({"key": key, "slug": slug, "name": a.get("project") or slug, "path": path,
                                "class": a.get("class"), "class_evidence": a.get("class_evidence"),
                                "summary": a.get("summary"), "missing_docs": a.get("missing_docs") or [],
                                "audited_at": audited_at})
        for dep in a.get("deployed_as") or []:
            c = dep.get("container")
            if c:
                res["deployed"].append({"key": key, "slug": slug, "container": c,
                                        "evidence": (dep.get("evidence") or "")[:300]})
        for doc in a.get("docs") or []:
            absp = resolve_doc_path(doc.get("path") or "", path)
            dkey = docs_by_abs.get(absp)
            if not dkey:
                res["unmatched_docs"] += 1
            claims = doc.get("claims") or []
            n = {s: sum(1 for c in claims if c.get("status") == s) for s in ("verified", "contradicted", "unverifiable")}
            res["docs"].append({"key": dkey, "path": absp, "project_key": key, "slug": slug,
                                "status": doc.get("status"), "kind": doc.get("kind"),
                                "audited_at": audited_at, **{f"n_{k}": v for k, v in n.items()}})
            for c in claims:
                text = c.get("text") or ""
                ckey = hashlib.sha1(f"{absp}|{text}".encode()).hexdigest()[:16]
                res["claims"].append({"key": ckey, "doc_key": dkey, "doc_path": absp, "text": text[:300],
                                      "kind": c.get("kind"), "status": c.get("status"),
                                      "evidence": (c.get("evidence") or "")[:400], "audited_at": audited_at})
    with open(dest + ".tmp", "w") as fh:
        json.dump(res, fh)
    os.replace(dest + ".tmp", dest)
    print(json.dumps({"projects": len(res["projects"]), "matched": sum(1 for p in res["projects"] if p["key"]),
                      "docs": len(res["docs"]), "unmatched_docs": res["unmatched_docs"],
                      "claims": len(res["claims"]), "deployed": len(res["deployed"])}))


if __name__ == "__main__":
    main(*sys.argv[1:4])
