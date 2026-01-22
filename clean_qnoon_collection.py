import argparse
import csv
import re
from pathlib import Path
from typing import Dict, Tuple, List

# -----------------------------
# Configurable category mapping
# -----------------------------
# If your top-level folder names differ, change this dictionary.
# Keys: folder names under the input root
# Values: friendly names (only used in reporting; folder name still used for mirroring)
CATEGORY_FOLDERS: Dict[str, str] = {
    "RD": "Royal Decrees",
    "FATWA": "Fatwas",
    "AD": "Administrative Decisions",
    "RO": "Royal Orders",
    "TA": "International Agreements",
}

# File extensions to process
EXTS = {".txt", ".text"}

# -----------------------------
# Cleaning rules
# -----------------------------
# We remove ONLY the unwanted "download links" lines if they appear at the START.
# Cases described:
# 1) "تحميل" (alone)
# 2) "تحميل" + "English"
# 3) "تحميل" + "تحميل"
#
# We do it as a loop: keep stripping these leading lines until they stop appearing.
#
# Notes:
# - Arabic "تحميل" can appear with stray spaces; we strip whitespace on each line.
# - "English" case-insensitive matching.
# - We do not remove these tokens if they appear later in the document; only at start.
DOWNLOAD_AR = "تحميل"

def normalize_newlines(text: str) -> str:
    text = text.replace("\ufeff", "")  # BOM
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # remove invisible RTL marks sometimes present from copy/paste
    text = text.replace("\u200f", "").replace("\u200e", "")
    return text

def strip_leading_download_lines(text: str) -> Tuple[str, int]:
    """
    Remove leading lines that are exactly:
      - 'تحميل'
      - 'English' (only when it follows the above patterns; but safe to strip at start)
    Also handles:
      - 'تحميل' then 'English'
      - 'تحميل' then 'تحميل'
      - repeated occurrences
    Returns (cleaned_text, removed_line_count).
    """
    removed = 0
    lines = text.split("\n")

    # Remove leading empty lines first
    while lines and lines[0].strip() == "":
        lines.pop(0)
        removed += 1

    # Now repeatedly remove the specified tokens at the start
    def is_english_line(s: str) -> bool:
        return s.strip().lower() == "english"

    def is_download_line(s: str) -> bool:
        return s.strip() == DOWNLOAD_AR

    changed = True
    while changed:
        changed = False

        # Trim leading empties
        while lines and lines[0].strip() == "":
            lines.pop(0)
            removed += 1
            changed = True

        if not lines:
            break

        # Case: first line is "تحميل"
        if lines and is_download_line(lines[0]):
            lines.pop(0)
            removed += 1
            changed = True

            # After popping "تحميل", also remove a following "English" OR another "تحميل" if present
            while lines and lines[0].strip() == "":
                lines.pop(0)
                removed += 1

            if lines and (is_english_line(lines[0]) or is_download_line(lines[0])):
                lines.pop(0)
                removed += 1

            continue

        # (Rare) If file starts with "English" alone, remove it too
        if lines and is_english_line(lines[0]):
            lines.pop(0)
            removed += 1
            changed = True
            continue

    cleaned = "\n".join(lines).strip()
    return cleaned, removed

def has_useful_content(text: str, min_chars: int) -> bool:
    # After stripping whitespace, must meet minimum threshold
    return len(re.sub(r"\s+", "", text)) >= min_chars

# -----------------------------
# Path helpers
# -----------------------------
def infer_category_folder(input_root: Path, file_path: Path) -> str:
    rel = file_path.relative_to(input_root)
    return rel.parts[0] if rel.parts else "UNKNOWN"

def within_configured_categories(category: str) -> bool:
    return category in CATEGORY_FOLDERS

def ensure_parent(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)

# -----------------------------
# Main
# -----------------------------
def main():

    # Minimum non-whitespace characters required after cleaning to keep the file
    MIN_CONTENT_CHARS = 50

    ap = argparse.ArgumentParser(description="Clean qanoon text collection: remove leading 'تحميل/English' lines, discard empty files, mirror output structure, and produce CSV stats.")
    ap.add_argument("--input_root", required=True, help="Path to the root collection directory (contains category subfolders).")
    ap.add_argument("--output_root", default="./output_cleaning", help="Output root containing 'cleaned' and 'discarded' folders.")
    ap.add_argument("--min_chars", type=int, default=MIN_CONTENT_CHARS, help="Minimum non-whitespace characters required to keep a file.")
    ap.add_argument("--include_uncategorized", action="store_true", help="If set, process files even if top-level folder isn't in CATEGORY_FOLDERS.")
    ap.add_argument("--report_csv", default="cleaning_report.csv", help="CSV filename for per-category stats (written inside output_root).")
    args = ap.parse_args()

    input_root = Path(args.input_root).expanduser().resolve()
    output_root = Path(args.output_root).expanduser().resolve()

    cleaned_root = output_root / "cleaned"
    discarded_root = output_root / "discarded"
    cleaned_root.mkdir(parents=True, exist_ok=True)
    discarded_root.mkdir(parents=True, exist_ok=True)

    # Stats per category
    stats = {}  # cat -> dict

    def bump(cat: str, key: str, n: int = 1):
        stats.setdefault(cat, {"processed": 0, "cleaned": 0, "discarded": 0, "removed_lines_total": 0})
        stats[cat][key] += n

    processed_files = 0

    for fp in input_root.rglob("*"):
        if not fp.is_file():
            continue
        if fp.suffix.lower() not in EXTS:
            continue

        cat = infer_category_folder(input_root, fp)
        if not args.include_uncategorized and not within_configured_categories(cat):
            continue

        bump(cat, "processed", 1)
        processed_files += 1

        raw = fp.read_text(encoding="utf-8", errors="ignore")
        raw = normalize_newlines(raw)

        cleaned_text, removed_lines = strip_leading_download_lines(raw)
        bump(cat, "removed_lines_total", removed_lines)

        rel = fp.relative_to(input_root)

        if has_useful_content(cleaned_text, args.min_chars):
            out_path = cleaned_root / rel
            ensure_parent(out_path)
            out_path.write_text(cleaned_text + "\n", encoding="utf-8")
            bump(cat, "cleaned", 1)
        else:
            out_path = discarded_root / rel
            ensure_parent(out_path)
            # Save the original raw for audit, not the cleaned empty text
            out_path.write_text(raw.strip() + "\n", encoding="utf-8")
            bump(cat, "discarded", 1)

    # Write CSV report
    report_path = output_root / args.report_csv
    with report_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["category_folder", "category_name", "processed", "cleaned", "discarded", "removed_lines_total"])
        for cat in sorted(stats.keys(), key=lambda x: x.lower()):
            w.writerow([
                cat,
                CATEGORY_FOLDERS.get(cat, cat),
                stats[cat]["processed"],
                stats[cat]["cleaned"],
                stats[cat]["discarded"],
                stats[cat]["removed_lines_total"],
            ])

    print("\n=== Cleaning completed ===")
    print(f"Input root:      {input_root}")
    print(f"Output root:     {output_root}")
    print(f"Cleaned folder:  {cleaned_root}")
    print(f"Discarded folder:{discarded_root}")
    print(f"Report CSV:      {report_path}")
    print(f"Total processed files: {processed_files}")

    # Console summary
    for cat in sorted(stats.keys(), key=lambda x: x.lower()):
        s = stats[cat]
        print(f"- {cat}: processed={s['processed']} cleaned={s['cleaned']} discarded={s['discarded']} removed_lines_total={s['removed_lines_total']}")

if __name__ == "__main__":
    main()
