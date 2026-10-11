"""Strip CSDN pic_center anchors and x-oss-process query params from markdown image URLs."""

import re
from pathlib import Path

POSTS = Path(__file__).resolve().parent.parent / "source" / "_posts"

# ![alt](/path.png?x-oss...#pic_center) or reference defs
img_paren = re.compile(
    r"(!\[[^\]]*\]\()([^)\s]+(?:\?[^)\s#]*)?(?:#[^)\s]*)?)(\s*(?:\"[^\"]*\")?\s*\))"
)
ref_line = re.compile(r"^(\s*\[[^\]]+\]:\s*)(\S+)", re.M)


def clean_url(url: str) -> str:
    # Only normalize local site images; leave external demo URLs unchanged.
    if not url.startswith("/"):
        return url
    return url.split("#")[0].split("?")[0]


def process_text(text: str) -> tuple[str, int]:
    changes = 0

    def repl_img(m: re.Match) -> str:
        nonlocal changes
        prefix, url, suffix = m.group(1), m.group(2), m.group(3)
        new_url = clean_url(url)
        if new_url != url:
            changes += 1
        return prefix + new_url + suffix

    text = img_paren.sub(repl_img, text)

    def repl_ref(m: re.Match) -> str:
        nonlocal changes
        prefix, url = m.group(1), m.group(2)
        new_url = clean_url(url)
        if new_url != url:
            changes += 1
        return prefix + new_url

    text = ref_line.sub(repl_ref, text)
    return text, changes


def main() -> None:
    total = 0
    files = 0
    for md in POSTS.rglob("*.md"):
        original = md.read_text(encoding="utf-8")
        updated, n = process_text(original)
        if n:
            md.write_text(updated, encoding="utf-8")
            print(f"{n:3d}  {md.relative_to(POSTS.parent.parent)}")
            total += n
            files += 1
    print(f"\nupdated {files} files, {total} URLs cleaned")


if __name__ == "__main__":
    main()
