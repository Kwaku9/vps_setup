#!/usr/bin/env python3
"""Replace the ' (Open WebUI)' suffix Open WebUI appends to a custom WEBUI_NAME.
Run inside the open-webui container; takes effect on the next process start.

Prints exactly one of APPLIED / UNCHANGED and exits 0, or prints ANCHOR_NOT_FOUND
and exits 1. The old sed matched double quotes, upstream moved to single quotes, and
sed exits 0 on no match, so the step reported success for months while doing nothing.

Licensing: this edits an Open WebUI branding surface. LICENSE clause 4 permits that
only for deployments with <= 50 end users per rolling 30 days, written permission, or
an enterprise license. Re-check the user count before this runs on a larger instance.
"""
import re
import sys

f = "/app/backend/open_webui/env.py"
SUFFIX = " - Your AI Brain in the Cloud"
with open(f) as fh:
    code = fh.read()

pattern = re.compile(r"""(WEBUI_NAME \+= )(['"]) \(Open WebUI\)\2""")

if SUFFIX in code:
    print("UNCHANGED")
elif len(pattern.findall(code)) == 1:
    patched = pattern.sub(lambda m: m.group(1) + repr(SUFFIX), code)
    compile(patched, f, "exec")
    with open(f, "w") as fh:
        fh.write(patched)
    print("APPLIED")
else:
    print("ANCHOR_NOT_FOUND: env.py WEBUI_NAME suffix line changed upstream; update the pattern")
    sys.exit(1)
