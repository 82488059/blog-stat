import re
from pathlib import Path

root = Path(r"e:/myblog/blog")
posts = root / "source" / "_posts"
source = root / "source"
public = root / "public"

ref_use = re.compile(r"!\[[^\]]*\]\[([^\]]+)\]")
ref_def = re.compile(r"^\s*\[([^\]]+)\]:\s*(\S+)", re.M)

broken_refs = []
ok_refs = 0
for md in posts.rglob("*.md"):
    text = md.read_text(encoding="utf-8", errors="replace")
    defs = {k: v for k, v in ref_def.findall(text)}
    for rid in ref_use.findall(text):
        if rid not in defs:
            broken_refs.append(
                {
                    "file": str(md.relative_to(root)).replace("\\", "/"),
                    "ref": rid,
                    "issue": "undefined",
                }
            )
            continue
        url = defs[rid].strip("<>").split('"')[0]
        clean = url.split("?")[0].split("#")[0]
        if clean.startswith("http"):
            ok_refs += 1
            continue
        if clean.startswith("/"):
            ok = (source / clean.lstrip("/")).exists() or (
                public / clean.lstrip("/")
            ).exists()
        else:
            ok = (md.parent / clean).exists()
        if ok:
            ok_refs += 1
        else:
            broken_refs.append(
                {
                    "file": str(md.relative_to(root)).replace("\\", "/"),
                    "ref": rid,
                    "url": url,
                }
            )

bad_md = []
for md in posts.rglob("*.md"):
    for i, line in enumerate(
        md.read_text(encoding="utf-8", errors="replace").splitlines(), 1
    ):
        s = line.strip()
        if "![\\[" in s or "![charts]" in s:
            bad_md.append((str(md.relative_to(root)).replace("\\", "/"), i, s[:120]))

print("ref-style images ok:", ok_refs)
print("ref-style broken:", len(broken_refs))
for x in broken_refs:
    print(x)
print("\nmalformed image markdown:", len(bad_md))
for x in bad_md:
    print(x[0], "L" + str(x[1]), x[2])
