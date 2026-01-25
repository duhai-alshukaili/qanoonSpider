import os
import re
import csv
import math
import json
import argparse
from pathlib import Path
from statistics import median

ARABIC_LETTERS_RE = re.compile(r"[\u0600-\u06FF]")
ARABIC_DIACRITICS_RE = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")

def normalize_text(s: str) -> str:
    # remove invisible marks / BOM
    s = s.replace("\ufeff", "").replace("\u200f", "").replace("\u200e", "")
    # normalize whitespace
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def estimate_tokens(text: str) -> tuple[int, int]:
    """
    Token estimation without a tokenizer.
    For Arabic, tokens are often ~3.5–5 chars/token depending on punctuation and spacing.
    We'll output two estimates (low/high) to get a range.
    """
    n = len(text)
    est_low = math.ceil(n / 5.0)   # fewer tokens
    est_high = math.ceil(n / 3.5)  # more tokens
    return est_low, est_high

def count_words(text: str) -> int:
    # crude word count: split on whitespace
    parts = re.split(r"\s+", text.strip())
    return len([p for p in parts if p])

def detect_article_markers(text: str) -> int:
    # count occurrences of المادة/مادة headings
    return len(re.findall(r"(?:\n|^)\s*(?:المادة|مادة)\s+\(?\d+\)?", text))

def count_arabic_ratio(text: str) -> float:
    if not text:
        return 0.0
    arabic = len(ARABIC_LETTERS_RE.findall(text))
    return arabic / max(1, len(text))

def count_diacritics(text: str) -> int:
    return len(ARABIC_DIACRITICS_RE.findall(text))

def percentile(sorted_vals, p) -> float:
    if not sorted_vals:
        raise ValueError("Cannot calculate percentile of empty sequence")
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    d0 = sorted_vals[f] * (c - k)
    d1 = sorted_vals[c] * (k - f)
    return d0 + d1

def infer_category(root: Path, file_path: Path) -> str:
    rel = file_path.relative_to(root)
    # category = first folder name under root (common pattern)
    return rel.parts[0] if len(rel.parts) > 0 else "UNKNOWN"

def iter_files(root: Path, exts):
    for ext in exts:
        yield from root.rglob(f"*{ext}")

def main():
    ap = argparse.ArgumentParser(description="Scan qanoon text corpus and compute file/category statistics.")
    ap.add_argument("--root", required=True, help="Root directory containing categorized text files.")
    ap.add_argument("--ext", default=".txt,.text", help="Comma-separated list of file extensions to include.")
    ap.add_argument("--encoding", default="utf-8", help="Text encoding to try first.")
    ap.add_argument("--no-normalize", action="store_true", help="Do not normalize whitespace/BOM before stats.")
    ap.add_argument("--outdir", default="./corpus_stats", help="Directory to write CSV outputs.")
    ap.add_argument("--sample-n", type=int, default=0, help="If >0, print N sample longest files per category.")
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    exts = [e.strip() for e in args.ext.split(",") if e.strip()]
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    file_rows = []
    cat_map = {}  # category -> list of char lengths

    total_files = 0
    unreadable = 0

    for fp in iter_files(root, exts):
        total_files += 1
        try:
            raw = fp.read_text(encoding=args.encoding, errors="ignore")
        except Exception:
            unreadable += 1
            continue

        text = raw if args.no_normalize else normalize_text(raw)

        category = infer_category(root, fp)
        rel_path = fp.relative_to(root).as_posix()

        n_chars = len(text)
        n_lines = text.count("\n") + (1 if text else 0)
        n_words = count_words(text)
        tok_low, tok_high = estimate_tokens(text) # type: ignore
        arabic_ratio = count_arabic_ratio(text)
        diacritics = count_diacritics(text)
        article_markers = detect_article_markers(text)

        file_rows.append({
            "category": category,
            "rel_path": rel_path,
            "chars": n_chars,
            "words": n_words,
            "lines": n_lines,
            "tok_est_low": tok_low,
            "tok_est_high": tok_high,
            "arabic_ratio": round(arabic_ratio, 4),
            "diacritics_count": diacritics,
            "article_markers": article_markers,
        })

        cat_map.setdefault(category, []).append(n_chars)

    # Write per-file CSV
    files_csv = outdir / "files.csv"
    with files_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(file_rows[0].keys()) if file_rows else [
            "category","rel_path","chars","words","lines","tok_est_low","tok_est_high","arabic_ratio","diacritics_count","article_markers"
        ])
        w.writeheader()
        for r in file_rows:
            w.writerow(r)

    # Per-category summary
    cat_rows = []
    for cat, lens in sorted(cat_map.items(), key=lambda x: x[0].lower()):
        lens_sorted = sorted(lens)
        cat_rows.append({
            "category": cat,
            "files": len(lens_sorted),
            "total_chars": sum(lens_sorted),
            "min_chars": lens_sorted[0],
            "median_chars": int(median(lens_sorted)),
            "p90_chars": int(percentile(lens_sorted, 90)),
            "p95_chars": int(percentile(lens_sorted, 95)),
            "max_chars": lens_sorted[-1],
        })

    cats_csv = outdir / "categories.csv"
    with cats_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "category","files","total_chars","min_chars","median_chars","p90_chars","p95_chars","max_chars"
        ])
        w.writeheader()
        for r in cat_rows:
            w.writerow(r)

    # Console summary
    print("\n=== Corpus Scan Summary ===")
    print(f"Root: {root}")
    print(f"Extensions: {exts}")
    print(f"Total files matched: {total_files}")
    print(f"Readable records written: {len(file_rows)}")
    print(f"Unreadable (skipped): {unreadable}")
    print(f"Unique categories: {len(cat_rows)}")
    print(f"Per-file CSV: {files_csv}")
    print(f"Per-category CSV: {cats_csv}")

    # Optional: show top longest files per category
    if args.sample_n and args.sample_n > 0 and file_rows:
        print("\n=== Longest file samples per category ===")
        by_cat = {}
        for r in file_rows:
            by_cat.setdefault(r["category"], []).append(r)
        for cat in sorted(by_cat.keys(), key=lambda x: x.lower()):
            rows = sorted(by_cat[cat], key=lambda r: r["chars"], reverse=True)[:args.sample_n]
            print(f"\n[{cat}] top {len(rows)} longest")
            for rr in rows:
                print(f"  chars={rr['chars']:>8}  tok~{rr['tok_est_low']}-{rr['tok_est_high']:<7}  articles={rr['article_markers']:<4}  {rr['rel_path']}")

if __name__ == "__main__":
    main()
