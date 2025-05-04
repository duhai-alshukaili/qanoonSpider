import os
import sqlite3
from pathlib import Path
from scrapy.exceptions import DropItem

PROJECT_ROOT = Path(__file__).resolve().parent
FILES_DIR    = PROJECT_ROOT / "downloads"         # downloads/RD/, downloads/AD/, ...


class LawFilesPipeline:
    """
    Saves each item's raw_content into a text file.
    Folder name == content_type (RD, AD, ...).
    Adds the absolute path into item['file_path'].
    """

    def open_spider(self, spider):
        FILES_DIR.mkdir(exist_ok=True)

    def process_item(self, item, spider):
        ctype = item.get("content_type")
        if not ctype:
            raise DropItem("Unknown content type")

        folder = FILES_DIR / ctype
        folder.mkdir(exist_ok=True)

        filename = f"{item['page_id']}.txt"
        path     = folder / filename
        path.write_text(item["raw_content"], encoding="utf-8")

        item["file_path"] = str(path)
        # raw_content no longer needed downstream
        item.pop("raw_content", None)
        return item


class SQLitePipeline:
    """
    Persists page_id, url, content_type, file_path into SQLite.
    """

    DB_FILE = PROJECT_ROOT / "laws.db"

    def open_spider(self, spider):
        self.conn = sqlite3.connect(self.DB_FILE)
        self.cur  = self.conn.cursor()
        self.cur.execute(
            """CREATE TABLE IF NOT EXISTS laws (
                   page_id      TEXT PRIMARY KEY,
                   url          TEXT,
                   content_type TEXT,
                   file_path    TEXT
               )"""
        )
        self.conn.commit()

    def close_spider(self, spider):
        self.conn.commit()
        self.conn.close()

    def process_item(self, item, spider):
        self.cur.execute(
            "INSERT OR REPLACE INTO laws VALUES (?, ?, ?, ?)",
            (item["page_id"], item["url"], item["content_type"], item["file_path"]),
        )
        return item

