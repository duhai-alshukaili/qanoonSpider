import re
from urllib.parse import urlparse
from scrapy.spiders import CrawlSpider, Rule # type: ignore
from scrapy.linkextractors import LinkExtractor # type: ignore
from qanoonSpider.items import LawItem

# Regex rules per section (compiled once for speed)
RULES = {
    "RD":     re.compile(r"/p/\d{4}/rd\d{5,10}/?$"),
    "FATWA":  re.compile(r"/p/\d{4}/fatwa\d{5,10}/?$"),
    "RO":     re.compile(r"/p/\d{4}/ro\d{5,10}/?$"),
    "TA":     re.compile(r"/p/\d{4}/t\d{5,10}a/?$"),
    "AD":     re.compile(r"/p/\d{4}/[a-zA-Z]{2,6}\d{5,10}/?$"), 
}

START_URLS = {
    "RD":    "https://qanoon.om/p/category/%d9%85%d8%b1%d8%b3%d9%88%d9%85-%d8%b3%d9%84%d8%b7%d8%a7%d9%86%d9%8a/",
    "AD":    "https://qanoon.om/p/category/%d9%82%d8%b1%d8%a7%d8%b1-%d9%88%d8%b2%d8%a7%d8%b1%d9%8a/",
    "RO":    "https://qanoon.om/p/category/%d8%a3%d9%85%d8%b1-%d8%b3%d8%a7%d9%85%d9%8a/",
    "TA":    "https://qanoon.om/p/category/%d8%a7%d8%aa%d9%81%d8%a7%d9%82%d9%8a%d8%a9-%d8%af%d9%88%d9%84%d9%8a%d8%a9/",
    "FATWA": "https://qanoon.om/p/category/%d9%81%d8%aa%d8%a7%d9%88%d9%89-%d9%82%d8%a7%d9%86%d9%88%d9%86%d9%8a%d8%a9/",
}

def which_section(url_path: str):
    """Return RD|AD|RO|TA|FATWA or None."""
    for key, pat in RULES.items():
        if pat.search(url_path):
            return key
    return None


class QanoonSpider(CrawlSpider):
    name = "qnoonSpider"

    # build one Rule per pattern so CrawlSpider keeps following pagination links
    rules = [
        Rule(LinkExtractor(allow=[pat.pattern]), callback="parse_detail", follow=False)
        for pat in RULES.values()
    ] + [
        # also follow everything inside the category pages (pagination, etc.)
        Rule(LinkExtractor(allow=[r"/p/category/"]), follow=True),
    ]

    start_urls = list(START_URLS.values())

    custom_settings = {
        "DOWNLOAD_DELAY": 1.0,
        "AUTOTHROTTLE_ENABLED": True,
        "USER_AGENT": "Mozilla/5.0 (compatible; OmaniLawBot/1.0)"
    }

    def parse_detail(self, response):
        # identify content type from the path
        path       = urlparse(response.url).path
        ctype      = which_section(path)
        page_id    = path.rstrip("/").split("/")[-1]        # rd2024041, etc.

        # Extract text inside div.entry-content
        text_parts = response.css("div.entry-content ::text").getall()
        content    = "\n".join(p.strip() for p in text_parts if p.strip())

        item = LawItem(
            page_id      = page_id,
            url          = response.url,
            content_type = ctype,
            file_path    = content      # provisional: pipelines overwrite with actual path
        )
        # store content so FilePipeline can save it
        item["raw_content"] = content
        yield item

    def closed(self, reason):
        """Called when the spider is closed."""
        self.logger.info(f"Spider closed cleanly: {reason}")
