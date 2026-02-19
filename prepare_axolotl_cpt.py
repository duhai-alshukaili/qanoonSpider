#!/usr/bin/env python3
import argparse
import json
import os
import random
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# -----------------------
# Defaults you can edit
# -----------------------
DEFAULT_CATEGORY_LABELS: Dict[str, str] = {
    "AD": "قرار إداري",
    "RD": "مرسوم سلطاني",
    "FATWA": "فتوى",
    # You can add others if you later include them
    "RO": "أمر سامٍ",
    "TA": "اتفاقية دولية",
}

DEFAULT_EXTS = [".txt", ".text"]

# -----------------------
# Text helpers
# -----------------------
def normalize_newlines(text: str) -> str:
    text = text.replace("\ufeff", "")  # BOM
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u200f", "").replace("\u200e", "")
    # collapse excessive whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def has_useful_content(text: str, min_chars: int) -> bool:
    # Count non-whitespace characters
    return len(re.sub(r"\s+", "", text)) >= min_chars

def split_by_articles(text: str) -> Optional[List[str]]:
    """
    Split by Arabic article markers like: 'المادة (1)' or 'مادة 1'
    Returns None if no meaningful split detected.
    """
    # Split while preserving the marker with the following text.
    # We'll split on lines that begin with المادة/مادة and a number.
    pattern = r"(?m)^(?=\s*(?:المادة|مادة)\s+\(?\d+\)?)"
    parts = re.split(pattern, text)
    parts = [p.strip() for p in parts if p and p.strip()]
    return parts if len(parts) > 1 else None

def chunk_text_paragraphwise(text: str, max_chars: int, overlap_chars: int) -> List[str]:
    """
    Paragraph-aware chunking with overlap (character-based).
    """
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: List[str] = []
    buf = ""

    for p in paras:
        if not buf:
            buf = p
            continue

        if len(buf) + len(p) + 2 <= max_chars:
            buf = buf + "\n\n" + p
        else:
            chunks.append(buf.strip())
            tail = buf[-overlap_chars:] if overlap_chars > 0 else ""
            buf = (tail + "\n\n" + p).strip()

    if buf:
        chunks.append(buf.strip())

    # If the document is a single massive paragraph, the above may create huge chunks.
    # Fallback: hard split by chars (rare, but safe).
    hardened: List[str] = []
    for c in chunks:
        if len(c) <= max_chars:
            hardened.append(c)
        else:
            start = 0
            while start < len(c):
                end = min(start + max_chars, len(c))
                hardened.append(c[start:end].strip())
                if end >= len(c):
                    break
                start = max(0, end - overlap_chars)

    return [c for c in hardened if c]

def chunk_document(text: str,
                   max_chars: int,
                   overlap_chars: int,
                   use_article_split: bool) -> List[str]:
    """
    Preferred: split by articles if present; fallback to paragraph chunking.
    """
    if use_article_split:
        parts = split_by_articles(text)
        if parts:
            # Articles can still be long; run paragraph chunking per part
            out: List[str] = []
            for part in parts:
                if len(part) <= max_chars:
                    out.append(part)
                else:
                    out.extend(chunk_text_paragraphwise(part, max_chars, overlap_chars))
            return out

    return chunk_text_paragraphwise(text, max_chars, overlap_chars)

# -----------------------
# Traversal + dataset build
# -----------------------
def infer_category(input_root: Path, file_path: Path) -> str:
    rel = file_path.relative_to(input_root)
    return rel.parts[0] if rel.parts else "UNKNOWN"

def iter_text_files(root: Path, exts: List[str]) -> List[Path]:
    files: List[Path] = []
    for ext in exts:
        files.extend(root.rglob(f"*{ext}"))
    return sorted([p for p in files if p.is_file()])

def choose_min_chars(category: str, default_min: int, overrides: Dict[str, int]) -> int:
    return overrides.get(category, default_min)

def build_header(category_code: str,
                 category_labels: Dict[str, str],
                 rel_path: str,
                 chunk_index: int,
                 chunk_total: int,
                 include_header: bool) -> str:
    if not include_header:
        return ""
    label = category_labels.get(category_code, category_code)
    return (
        f"[نوع_المستند]: {label}\n"
        f"[المصدر]: qanoon.om\n"
        f"[المسار]: {rel_path}\n"
        f"[الجزء]: {chunk_index}/{chunk_total}\n"
        "النص:\n"
    )

def maybe_cap_chunks(chunks: List[str], cap: int, rng: random.Random) -> List[str]:
    if cap <= 0 or len(chunks) <= cap:
        return chunks
    # sample uniformly to avoid dominance by mega-docs
    idxs = sorted(rng.sample(range(len(chunks)), cap))
    return [chunks[i] for i in idxs]

def write_jsonl(records: List[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

def parse_overrides(s: str) -> Dict[str, int]:
    """
    Parse "AD=300,RD=200,FATWA=500" into dict.
    """
    out: Dict[str, int] = {}
    if not s.strip():
        return out
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError(f"Bad override '{part}'. Use CAT=NUM, e.g., AD=300")
        k, v = part.split("=", 1)
        out[k.strip()] = int(v.strip())
    return out

def main():
    ap = argparse.ArgumentParser(
        description="Prepare Axolotl CPT JSONL (train/val) from cleaned qanoon text corpus."
    )
    ap.add_argument("--input_root", required=True,
                    help="Root folder of CLEANED corpus (contains category subfolders).")
    ap.add_argument("--output_dir", default="./cpt_data",
                    help="Directory to write train.jsonl and val.jsonl.")
    ap.add_argument("--train_name", default="train.jsonl")
    ap.add_argument("--val_name", default="val.jsonl")

    # Category selection
    ap.add_argument("--keep_categories", default="FATWA,RD,AD",
                    help="Comma-separated top-level folders to include, e.g., FATWA,RD,AD")
    ap.add_argument("--category_labels", default="",
                    help="Optional mapping overrides like AD=قرار إداري,RD=مرسوم سلطاني,FATWA=فتوى")

    # Chunking controls
    ap.add_argument("--max_chars", type=int, default=6500,
                    help="Maximum characters per chunk (recommended 6000–7000).")
    ap.add_argument("--overlap_chars", type=int, default=500,
                    help="Overlap characters between chunks (recommended 400–600).")
    ap.add_argument("--use_article_split", action="store_true",
                    help="If set, try splitting by 'المادة/مادة' headings first (recommended for RD).")

    # Filtering
    ap.add_argument("--min_chars_default", type=int, default=250,
                    help="Discard file if remaining content has fewer non-whitespace chars than this.")
    ap.add_argument("--min_chars_overrides", default="AD=300,RD=200,FATWA=500",
                    help="Per-category min chars override, e.g., AD=300,RD=200,FATWA=500")
    ap.add_argument("--extensions", default=",".join(DEFAULT_EXTS),
                    help="Comma-separated extensions to process, default: .txt,.text")

    # Split / sampling / caps
    ap.add_argument("--val_ratio", type=float, default=0.01,
                    help="Fraction of chunks for validation (e.g., 0.01 = 1%%).")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max_chunks_per_doc", type=int, default=50,
                    help="Cap chunks per document to avoid mega-doc dominance; 0 disables cap.")

    # Metadata + reporting
    ap.add_argument("--include_header", action="store_true",
                    help="Include metadata header lines in each chunk.")
    ap.add_argument("--stats_csv", default="prep_stats.csv",
                    help="Write a CSV summary of files/chunks kept per category.")
    ap.add_argument("--dry_run", action="store_true",
                    help="Compute stats only; do not write JSONL outputs.")

    args = ap.parse_args()

    input_root = Path(args.input_root).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    exts = [e.strip() for e in args.extensions.split(",") if e.strip()]

    keep_cats = [c.strip() for c in args.keep_categories.split(",") if c.strip()]
    keep_set = set(keep_cats)

    # category label overrides
    labels = dict(DEFAULT_CATEGORY_LABELS)
    if args.category_labels.strip():
        # parse "AD=...,RD=...,FATWA=..."
        for part in args.category_labels.split(","):
            k, v = part.split("=", 1)
            labels[k.strip()] = v.strip()

    overrides = parse_overrides(args.min_chars_overrides)

    rng = random.Random(args.seed)

    # Stats containers
    stats = {c: {"files_seen": 0, "files_kept": 0, "files_discarded": 0,
                 "chunks_written": 0, "chunks_capped_away": 0} for c in keep_set}
    total_files_seen = 0

    all_records: List[dict] = []

    files = iter_text_files(input_root, exts)

    for fp in files:
        cat = infer_category(input_root, fp)
        if cat not in keep_set:
            continue

        total_files_seen += 1
        stats[cat]["files_seen"] += 1

        raw = fp.read_text(encoding="utf-8", errors="ignore")
        text = normalize_newlines(raw)

        min_chars = choose_min_chars(cat, args.min_chars_default, overrides)
        if not has_useful_content(text, min_chars=min_chars):
            stats[cat]["files_discarded"] += 1
            continue

        stats[cat]["files_kept"] += 1

        rel_path = fp.relative_to(input_root).as_posix()
        chunks = chunk_document(
            text=text,
            max_chars=args.max_chars,
            overlap_chars=args.overlap_chars,
            use_article_split=args.use_article_split and (cat == "RD" or cat == "FATWA" or cat == "AD"),
        )

        # cap chunks per doc (avoid mega docs)
        before = len(chunks)
        chunks = maybe_cap_chunks(chunks, args.max_chunks_per_doc, rng)
        after = len(chunks)
        if after < before:
            stats[cat]["chunks_capped_away"] += (before - after)

        # build records
        for i, ch in enumerate(chunks, start=1):
            header = build_header(cat, labels, rel_path, i, len(chunks), args.include_header)
            all_records.append({"text": header + ch})

        stats[cat]["chunks_written"] += len(chunks)

    # Shuffle records to mix categories
    rng.shuffle(all_records)

    # Split train/val by chunks (simple, effective for CPT)
    val_size = max(1, int(len(all_records) * args.val_ratio)) if all_records else 0
    val_records = all_records[:val_size]
    train_records = all_records[val_size:]

    # Reporting
    stats_path = output_dir / args.stats_csv
    output_dir.mkdir(parents=True, exist_ok=True)
    with stats_path.open("w", encoding="utf-8", newline="") as f:
        f.write("category,files_seen,files_kept,files_discarded,chunks_written,chunks_capped_away\n")
        for cat in keep_cats:
            s = stats.get(cat, None)
            if not s:
                continue
            f.write(f"{cat},{s['files_seen']},{s['files_kept']},{s['files_discarded']},"
                    f"{s['chunks_written']},{s['chunks_capped_away']}\n")

    print("\n=== CPT Prep Summary ===")
    print(f"Input root: {input_root}")
    print(f"Keep categories: {', '.join(keep_cats)}")
    print(f"max_chars={args.max_chars}, overlap_chars={args.overlap_chars}, use_article_split={args.use_article_split}")
    print(f"Records (chunks): total={len(all_records)} train={len(train_records)} val={len(val_records)}")
    print(f"Stats CSV: {stats_path}")

    for cat in keep_cats:
        s = stats.get(cat)
        if s:
            print(f"- {cat}: files_seen={s['files_seen']} kept={s['files_kept']} discarded={s['files_discarded']} "
                  f"chunks={s['chunks_written']} capped_away={s['chunks_capped_away']}")

    if args.dry_run:
        print("\nDry-run mode: JSONL files were NOT written.")
        return

    train_path = output_dir / args.train_name
    val_path = output_dir / args.val_name
    write_jsonl(train_records, train_path)
    write_jsonl(val_records, val_path)

    print(f"Train JSONL: {train_path}")
    print(f"Val JSONL:   {val_path}")

if __name__ == "__main__":
    main()
