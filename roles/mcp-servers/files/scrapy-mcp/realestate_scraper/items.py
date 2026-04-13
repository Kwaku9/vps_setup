import scrapy

class RealestateScraperItem(scrapy.Item):
    title = scrapy.Field()
    link = scrapy.Field()
    price = scrapy.Field()
    category = scrapy.Field()
    location = scrapy.Field()
    bedrooms = scrapy.Field()
    bathrooms = scrapy.Field()
    phone = scrapy.Field()
    property_details = scrapy.Field()
