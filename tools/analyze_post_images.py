import json
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

root = Path(r"e:\myblog\blog")
posts = root / "source" / "_posts"
source = root / "source"
public = root / "public"

img_md = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
img_html = re.compile(r"""<img[^>]+src=["']([^"']+)["']""", re.I)
img_ref = re.compile(r"^\s*\[([^\]]+)\]:\s*(\S+)", re.M)

stats = {
    "posts": 0,
    "images_total": 0,
    "relative": 0,
    "absolute_ok": 0,
    "absolute_missing": 0,
    "external": 0,
    "data_uri": 0,
    "empty": 0,
}

relative_examples = []
missing_abs = []
external_hosts = {}


def is_external(url: str) -> bool:
    return url.startswith("http://") or url.startswith("https://") or url.startswith("//")


def resolve_local(url: str, md_path: Path):
    url = unquote(url.split("?")[0].split("#")[0])
    if url.startswith("/"):
        rel = url.lstrip("/")
        return [source / rel, public / rel, root / rel]
    return [md_path.parent / url, md_path.parent / md_path.stem / url]


for md in posts.rglob("*.md"):
    stats["posts"] += 1
    text = md.read_text(encoding="utf-8", errors="replace")
    urls = []
    urls += [u for _alt, u in img_md.findall(text)]
    urls += img_html.findall(text)
    for _id, u in img_ref.findall(text):
        low = u.lower()
        if any(
            low.endswith(ext)
            for ext in (
                ".png",
                ".jpg",
                ".jpeg",
                ".gif",
                ".webp",
                ".svg",
                ".bmp",
                ".dib",
            )
        ) or "/picture/" in u or "http" in u:
            urls.append(u)

    for url in urls:
        url = url.strip().strip("<>")
        if not url:
            stats["empty"] += 1
            continue
        stats["images_total"] += 1
        if url.startswith("data:"):
            stats["data_uri"] += 1
            continue
        if is_external(url):
            stats["external"] += 1
            host = urlparse("http:" + url if url.startswith("//") else url).netloc
            external_hosts[host] = external_hosts.get(host, 0) + 1
            continue
        rel_file = str(md.relative_to(root)).replace("\\", "/")
        if url.startswith("/"):
            cands = resolve_local(url, md)
            exists = any(p.exists() for p in cands)
            if exists:
                stats["absolute_ok"] += 1
            else:
                stats["absolute_missing"] += 1
                missing_abs.append({"file": rel_file, "url": url})
        else:
            stats["relative"] += 1
            cands = resolve_local(url, md)
            exists = any(p.exists() for p in cands)
            relative_examples.append(
                {
                    "file": rel_file,
                    "url": url,
                    "exists_nearby": exists,
                    "nearby": [
                        str(p.relative_to(root)).replace("\\", "/")
                        for p in cands
                        if p.exists()
                    ][:2],
                }
            )

print("=== SUMMARY ===")
print(json.dumps(stats, ensure_ascii=False, indent=2))

ex_ok = [x for x in relative_examples if x["exists_nearby"]]
ex_bad = [x for x in relative_examples if not x["exists_nearby"]]
print("\n=== RELATIVE IMAGES ===")
print(f"count={len(relative_examples)}")
print(f"  nearby file exists: {len(ex_ok)}")
print(f"  nearby file missing: {len(ex_bad)}")
print("\n-- relative missing --")
for x in ex_bad[:50]:
    print(f"{x['file']}  ->  {x['url']}")
if len(ex_bad) > 50:
    print(f"... and {len(ex_bad) - 50} more")
print("\n-- relative but nearby exists (likely not published to URL) --")
for x in ex_ok[:50]:
    print(f"{x['file']}  ->  {x['url']}  found:{x['nearby']}")
if len(ex_ok) > 50:
    print(f"... and {len(ex_ok) - 50} more")

print("\n=== ABSOLUTE PATH MISSING LOCALLY ===")
print(f"count={len(missing_abs)}")
for x in missing_abs[:50]:
    print(f"{x['file']}  ->  {x['url']}")
if len(missing_abs) > 50:
    print(f"... and {len(missing_abs) - 50} more")

print("\n=== EXTERNAL HOSTS ===")
for h, c in sorted(external_hosts.items(), key=lambda kv: -kv[1])[:20]:
    print(f"{c:4d}  {h}")

# posts with issues
problem_posts = sorted(
    {
        x["file"]
        for x in relative_examples + missing_abs
    }
)
print(f"\n=== POSTS WITH IMAGE ISSUES: {len(problem_posts)} ===")
for f in problem_posts[:80]:
    print(f)
if len(problem_posts) > 80:
    print(f"... and {len(problem_posts) - 80} more")

out = root / "stat_server" / "post_image_report.json"
out.write_text(
    json.dumps(
        {
            "stats": stats,
            "relative": relative_examples,
            "absolute_missing": missing_abs,
            "external_hosts": external_hosts,
            "problem_posts": problem_posts,
        },
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)
print(f"\nfull report: {out}")
