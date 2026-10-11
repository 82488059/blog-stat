"""Find broken reference-style images using /assets/images/post/ paths."""

import re
from collections import Counter
from pathlib import Path

root = Path(__file__).resolve().parent.parent
posts = root / "source" / "_posts"
source = root / "source"
public = root / "public"

ref_use = re.compile(r"!\[[^\]]*\]\[([^\]]+)\]")
ref_def = re.compile(r"^\s*\[([^\]]+)\]:\s*(\S+)", re.M)

broken = []
ok = 0
for md in posts.rglob("*.md"):
    text = md.read_text(encoding="utf-8", errors="replace")
    defs = {k: v for k, v in ref_def.findall(text)}
    for rid in set(ref_use.findall(text)):
        if rid not in defs:
            broken.append(
                {
                    "file": str(md.relative_to(root)).replace("\\", "/"),
                    "ref": rid,
                    "issue": "undefined_ref",
                }
            )
            continue
        url = defs[rid].strip("<>").split('"')[0]
        clean = url.split("?")[0].split("#")[0]
        if clean.startswith("http"):
            ok += 1
            continue
        if clean.startswith("/"):
            exists = (source / clean.lstrip("/")).exists() or (
                public / clean.lstrip("/")
            ).exists()
        else:
            exists = (md.parent / clean).exists()
        if exists:
            ok += 1
        else:
            # try picture/src/old equivalent
            alt = None
            if "/assets/images/post/old/" in clean:
                alt = clean.replace(
                    "/assets/images/post/old/", "/picture/src/old/"
                )
            elif "/assets/images/post/" in clean:
                alt = clean.replace("/assets/images/post/", "/picture/src/old/")
            alt_ok = alt and (
                (source / alt.lstrip("/")).exists()
                or (public / alt.lstrip("/")).exists()
            )
            broken.append(
                {
                    "file": str(md.relative_to(root)).replace("\\", "/"),
                    "ref": rid,
                    "url": clean,
                    "alt_exists_at": alt if alt_ok else None,
                }
            )

print("ref ok:", ok)
print("ref broken:", len(broken))
paths = Counter(x.get("url", x.get("issue", "")) for x in broken)
for p, n in paths.most_common(20):
    print(n, p)
print("\n-- fixable via /picture/src/old --")
fixable = [x for x in broken if x.get("alt_exists_at")]
print(len(fixable))
for x in fixable[:25]:
    print(x["file"], "->", x["url"], "=>", x["alt_exists_at"])
print("\n-- truly missing --")
missing = [x for x in broken if not x.get("alt_exists_at")]
print(len(missing))
for x in missing[:25]:
    print(x)
