# qanoonSpider

Scrapy crawler for collecting legal texts from [qanoon.om](https://qanoon.om).

Spider implementation: `qanoonSpider/spiders/qanoon_spider.py`  
Spider name: `qanoonSpider`

## Prerequisites

- Python 3.10+ (recommended)
- `pip`

## Setup

From the project root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run the crawler

From the project root (same folder as `scrapy.cfg`):

```bash
scrapy crawl qanoonSpider
```

Useful variants:

```bash
# show informative logs
scrapy crawl qanoonSpider -s LOG_LEVEL=INFO

# test run with a page limit
scrapy crawl qanoonSpider -s CLOSESPIDER_PAGECOUNT=50
```

## Crawl output

The configured pipelines save results to:

- Text files: `qanoonSpider/downloads/<CONTENT_TYPE>/<page_id>.txt`
- SQLite metadata DB: `qanoonSpider/laws.db`
- SQLite table: `laws(page_id, url, content_type, file_path)`

Content types used by the spider:

- `RD`
- `AD`
- `RO`
- `TA`
- `FATWA`

## Quick validation

```bash
# check extracted text files
find qanoonSpider/downloads -type f | head

# inspect saved metadata
sqlite3 qanoonSpider/laws.db "SELECT content_type, COUNT(*) FROM laws GROUP BY content_type;"
```
