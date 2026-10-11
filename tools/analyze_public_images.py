import json
import re
from collections import defaultdict
from pathlib import Path

root = Path(r"e:\myblog\blog")
public = root / "public"

img_re = re.compile(r"""<img[^>]+src=["']([^"']+)["']""", re.I)

stats = defaultdict(int)
broken_relative = []  # src without / or http
missing_absolute = []
by_page = defaultdict(list)

skip_prefixes = (
    "/picture/",
    "/img/",
    "/css/",
    "/js/",
    "data:",
    "http://",
    "https://",
    "//",
)

for html in public.rglob("index.html"):
    # only post-like paths: YYYYMMDD/... or skip tags/categories/archives/page
    rel = html.relative_to(public).as_posix()
    if rel in {"index.html", "404/index.html"}:
        continue
    parts = rel.split("/")
    if parts[0] in {"tags", "categories", "archives", "page", "link", "tools", "assets"}:
        continue

    text = html.read_text(encoding="utf-8", errors="replace")
    for src in img_re.findall(text):
        src = src.strip()
        stats["images"] += 1
        if src.startswith(("http://", "https://", "//", "data:")):
            stats["external_or_data"] += 1
            continue
        if not src.startswith("/"):
            stats["relative"] += 1
            # resolve against page dir
            page_dir = html.parent
            candidate = (page_dir / src).resolve()
            exists = candidate.exists()
            item = {
                "page": "/" + str(html.parent.relative_to(public)).replace("\\", "/") + "/",
                "src": src,
                "exists_in_public": exists,
            }
            broken_relative.append(item)
            by_page[item["page"]].append(item)
            continue
        # absolute site path
        if any(src.startswith(p) for p in ("/picture/", "/img/", "/css/", "/js/")) or src.endswith(
            (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".bmp", ".dib")
        ):
            local = public / src.lstrip("/")
            # also under source
            source_local = root / "source" / src.lstrip("/")
            exists = local.exists() or source_local.exists()
            if not exists:
                # ignore theme onerror fallbacks friend_404 if present
                stats["abs_missing"] += 1
                missing_absolute.append(
                    {
                        "page": "/" + str(html.parent.relative_to(public)).replace("\\", "/") + "/",
                        "src": src,
                    }
                )
                by_page["/" + str(html.parent.relative_to(public)).replace("\\", "/") + "/"].append(
                    {"src": src, "type": "abs_missing"}
                )
            else:
                stats["abs_ok"] += 1
        else:
            stats["other_abs"] += 1

print("=== PUBLIC HTML IMAGE SCAN ===")
print(json.dumps(dict(stats), ensure_ascii=False, indent=2))
print(f"\nrelative img tags: {len(broken_relative)}")
print(f"pages with relative imgs: {len({x['page'] for x in broken_relative})}")
print("\n-- all relative (likely 404 online) --")
for x in broken_relative:
    flag = "OK-local" if x["exists_in_public"] else "MISSING"
    print(f"[{flag}] {x['page']}  src={x['src']}")

print(f"\nabsolute missing: {len(missing_absolute)}")
for x in missing_absolute[:40]:
    print(f"{x['page']}  src={x['src']}")
if len(missing_absolute) > 40:
    print(f"... and {len(missing_absolute)-40} more")

# unique problem pages
prob_pages = sorted(set([x["page"] for x in broken_relative] + [x["page"] for x in missing_absolute]))
print(f"\n=== PROBLEM PAGES: {len(prob_pages)} ===")
for p in prob_pages:
    print(p)

out = root / "stat_server" / "public_image_report.json"
out.write_text(
    json.dumps(
        {
            "stats": dict(stats),
            "relative": broken_relative,
            "absolute_missing": missing_absolute,
            "problem_pages": prob_pages,
        },
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)
print(f"\nreport: {out}")
