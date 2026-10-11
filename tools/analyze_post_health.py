"""Extended blog post health scan (images, links, covers)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
POSTS = ROOT / "source" / "_posts"
SOURCE = ROOT / "source"
PUBLIC = ROOT / "public"

img_md = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
link_md = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
cover_re = re.compile(r"^cover:\s*(.+)$", re.M)
code_fence = re.compile(r"```[\s\S]*?```|`[^`]+`")


def strip_code(text: str) -> str:
    return code_fence.sub("", text)


def is_external(url: str) -> bool:
    return url.startswith(("http://", "https://", "//"))


def resolve_local(url: str) -> bool:
    url = url.split("?")[0].split("#")[0]
    if is_external(url):
        return True
    if url.startswith("/"):
        rel = url.lstrip("/")
        return (SOURCE / rel).exists() or (PUBLIC / rel).exists()
    return False


def main() -> None:
    issues = {
        "broken_images_outside_code": [],
        "schemeless_urls": [],
        "broken_covers": [],
        "external_images": [],
        "demo_placeholder_images": [],
        "posts_with_issues": set(),
    }

    for md in POSTS.rglob("*.md"):
        rel = str(md.relative_to(ROOT)).replace("\\", "/")
        text = md.read_text(encoding="utf-8", errors="replace")
        body = strip_code(text)

        for alt, url in img_md.findall(body):
            url = url.strip()
            if url in ("图片地址",):
                issues["demo_placeholder_images"].append({"file": rel, "url": url})
                continue
            if not url.startswith(("http://", "https://", "//", "/")):
                if "xssl.online/" in url:
                    issues["schemeless_urls"].append({"file": rel, "url": url})
                    issues["posts_with_issues"].add(rel)
                elif not resolve_local(url):
                    issues["broken_images_outside_code"].append(
                        {"file": rel, "url": url, "alt": alt}
                    )
                    issues["posts_with_issues"].add(rel)
            elif is_external(url):
                issues["external_images"].append({"file": rel, "url": url})
            elif url.startswith("/") and not resolve_local(url):
                issues["broken_images_outside_code"].append(
                    {"file": rel, "url": url, "alt": alt}
                )
                issues["posts_with_issues"].add(rel)

        m = cover_re.search(text)
        if m:
            cover = m.group(1).strip().strip("'\"")
            if cover and cover.startswith("/") and not resolve_local(cover):
                issues["broken_covers"].append({"file": rel, "cover": cover})
                issues["posts_with_issues"].add(rel)

    # public HTML: img src with ? or # that exist when stripped
    html_query_suffix = []
    img_html = re.compile(r"""<img[^>]+src=["']([^"']+)["']""", re.I)
    for html in PUBLIC.rglob("index.html"):
        rel_page = "/" + str(html.parent.relative_to(PUBLIC)).replace("\\", "/") + "/"
        if rel_page.count("/") < 3:
            continue
        text = html.read_text(encoding="utf-8", errors="replace")
        for src in img_html.findall(text):
            if "?" in src or "#" in src:
                clean = src.split("?")[0].split("#")[0]
                if clean.startswith("/") and (PUBLIC / clean.lstrip("/")).exists():
                    if src != clean:
                        html_query_suffix.append(
                            {"page": rel_page, "src": src, "clean": clean}
                        )

    report = {
        "summary": {
            "posts": len(list(POSTS.rglob("*.md"))),
            "broken_images_outside_code": len(issues["broken_images_outside_code"]),
            "schemeless_urls": len(issues["schemeless_urls"]),
            "broken_covers": len(issues["broken_covers"]),
            "external_images": len(issues["external_images"]),
            "demo_placeholder_in_body": len(issues["demo_placeholder_images"]),
            "html_imgs_with_query_or_hash": len(html_query_suffix),
            "posts_with_real_issues": len(issues["posts_with_issues"]),
        },
        **{k: (list(v) if isinstance(v, set) else v) for k, v in issues.items()},
        "html_query_suffix_sample": html_query_suffix[:30],
    }

    out = ROOT / "stat_server" / "post_health_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== EXTENDED HEALTH SCAN ===")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    if issues["broken_images_outside_code"]:
        print("\n-- broken images (outside code blocks) --")
        for x in issues["broken_images_outside_code"]:
            print(f"{x['file']} -> {x['url']}")
    if issues["schemeless_urls"]:
        print("\n-- schemeless image URLs --")
        for x in issues["schemeless_urls"]:
            print(f"{x['file']} -> {x['url']}")
    if issues["broken_covers"]:
        print("\n-- broken covers --")
        for x in issues["broken_covers"]:
            print(f"{x['file']} -> {x['cover']}")
    if issues["external_images"]:
        print(f"\n-- external images: {len(issues['external_images'])} (depend on third-party) --")
        hosts = {}
        for x in issues["external_images"]:
            h = urlparse(x["url"]).netloc
            hosts[h] = hosts.get(h, 0) + 1
        for h, c in sorted(hosts.items(), key=lambda kv: -kv[1]):
            print(f"  {c:3d}  {h}")
    if html_query_suffix:
        pages = sorted(set(x["page"] for x in html_query_suffix))
        print(f"\n-- HTML img src with ?/# (files exist, optional cleanup): {len(pages)} pages --")
        for p in pages:
            print(f"  {p}")
    print(f"\nfull report: {out}")


if __name__ == "__main__":
    main()
