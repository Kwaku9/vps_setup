BOT_NAME = "realestate_scraper"

SPIDER_MODULES = ["realestate_scraper.spiders"]
NEWSPIDER_MODULE = "realestate_scraper.spiders"

# Obey robots.txt rules - Set to False for this exercise, but be a good citizen on real projects
ROBOTSTXT_OBEY = False

# Configure a delay for requests for the same website (default: 0)
DOWNLOAD_DELAY = 2

# Set a custom user-agent
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'

# Activate the pipeline
ITEM_PIPELINES = {
   "realestate_scraper.pipelines.RealestateScraperPipeline": 300,
}

# Configure Feeds to export to JSON and CSV
FEEDS = {
    'properties.json': {
        'format': 'json',
        'encoding': 'utf8',
        'store_empty': False,
        'fields': None,
        'indent': 4,
    },
    'properties.csv': {
        'format': 'csv',
        'fields': None,
    },
}