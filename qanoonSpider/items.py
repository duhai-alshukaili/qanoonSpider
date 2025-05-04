# Define here the models for your scraped items
#
# See documentation in:
# https://docs.scrapy.org/en/latest/topics/items.html

import scrapy


class LawItem(scrapy.Item):
    page_id      = scrapy.Field()
    url          = scrapy.Field()
    content_type = scrapy.Field()        # RD | AD | RO | TA | FATWA
    file_path    = scrapy.Field()        # filled by pipeline
    raw_content  = scrapy.Field()      # ← NEW: temporary text buffer
