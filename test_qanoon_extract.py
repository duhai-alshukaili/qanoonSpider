#!/usr/bin/env python3
"""
test_qanoon_extract.py
──────────────────────
Fetches a Qanoon page and prints the plain‑text that lives inside
<div class="entry-content"> … </div>.

Usage
-----
    python test_qanoon_extract.py URL [URL …]

Example
-------
    python test_qanoon_extract.py \
        https://qanoon.om/p/2024/rd2024041/ \
        https://qanoon.om/p/2025/mjla20250070/ \
        https://qanoon.om/p/2025/ro20250002/ \
        https://qanoon.om/p/2022/t2022029a/ \
        https://qanoon.om/p/2023/fatwa202334/
"""

import sys
import textwrap
import requests
from parsel import Selector          # pip install parsel

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; QanoonTest/1.0)"
}


def extract_entry_content(url: str) -> str:
    """Return the cleaned text found inside <div class="entry-content">."""
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    sel = Selector(resp.text)
    text_parts = sel.css("div.entry-content ::text").getall()
    return "\n".join(t.strip() for t in text_parts if t.strip())


def main(urls):
    for url in urls:
        print("=" * 80)
        print(f"URL: {url}")
        try:
            body = extract_entry_content(url)
            preview = textwrap.shorten(body, width=250, placeholder=" …")
            print(f"✓ Extracted {len(body):,} characters")
            print("Preview:")
            print(preview)
        except Exception as err:
            print(f"✗ Failed: {err}")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        print(__doc__)
        sys.exit(0)

    main(sys.argv[1:])
