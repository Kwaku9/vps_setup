import scrapy
import re
from realestate_scraper.items import RealestateScraperItem

class RealEstateSpider(scrapy.Spider):
    name = 'realestate'
    start_urls = ['https://www.clasificadosonline.com/UDRentalsListingAdv.asp?RentalsPueblos=%25&Category=Casa&Bedrooms=%25&LowPrice=1599&HighPrice=3000&Area=&IncPrecio=1&redirecturl=%2FUDRentalsListingAdvMap.asp&BtnSearchListing=Listado&categoryID=3']

    def parse(self, response):
        # This is the main container for each listing, identified from the HTML you provided.
        listings = response.xpath('//div[contains(@class, "dv-classified-row-v2")]')

        for listing in listings:
            item = RealestateScraperItem()

            # --- Extract data from the main listing page using the new, reliable selectors --- #
            item['title'] = listing.xpath('.//span[contains(@class, "link-blue-color")]/text()').get()
            item['price'] = listing.xpath('.//font[contains(text(), "$")]/text()').get()
            
            # Get the parent span that contains both price and category, then parse the text
            price_cat_span_text = listing.xpath('string(.//span[span[@class="Tahoma16BrownNound"]])').get()
            if ',' in price_cat_span_text:
                # The category is the text after the comma
                category_text = price_cat_span_text.split(',')[-1]
                item['category'] = category_text.strip()
            else:
                item['category'] = None

            location_parts = listing.xpath('.//a[contains(@href, "UDREntalslistingBarrio.asp")]/span/text() | .//a[contains(@href, "RentalsPueblos")]/span/text()').getall()
            item['location'] = ' '.join(part.strip() for part in location_parts)

            # Get all text within the span that holds bed/bath icons and numbers
            bed_bath_text = ' '.join(listing.xpath('.//span[img[contains(@src, "icon_cuartos.png")]]//text()').getall())
            bed_bath_text = bed_bath_text.strip()

            # Use regex to find numbers associated with bed/bath icons
            bedrooms_match = re.search(r'(\d+)\s*Cuartos', bed_bath_text, re.IGNORECASE)
            if not bedrooms_match:
                 bedrooms_match = re.search(r'(\d+)\s*Habitaciones', bed_bath_text, re.IGNORECASE)
            
            bathrooms_match = re.search(r'(\d+(\s*1/2)?)\s*Baños', bed_bath_text, re.IGNORECASE)
            if not bathrooms_match:
                bathrooms_match = re.search(r'(\d+(\s*1/2)?)\s*Banos', bed_bath_text, re.IGNORECASE)

            # The previous selectors were looking for text nodes that were siblings of the images.
            # A more robust way is to get all text within the parent span and parse it.
            all_text_in_span = listing.xpath('string(.//span[img[contains(@src, "icon_cuartos.png")]])').get()
            
            item['bedrooms'] = all_text_in_span.split()[0] if all_text_in_span.split() else None
            item['bathrooms'] = all_text_in_span.split()[1] if len(all_text_in_span.split()) > 1 else None

            detail_page_url = listing.xpath('.//a[contains(@href, "UDRentalsDetail.asp")]/@href').get()

            if detail_page_url:
                item['link'] = response.urljoin(detail_page_url)
                yield response.follow(detail_page_url, self.parse_property_details, meta={'item': item})
            else:
                item['link'] = None
                item['phone'] = None
                yield item

        # --- Pagination --- #
        next_page = response.xpath('//a[img[contains(@src, "1proximos.gif")]]/@href').get()
        if next_page is not None:
            yield response.follow(next_page, callback=self.parse)

    def parse_property_details(self, response):
        item = response.meta['item']
        
        # --- Extract phone number from the detail page --- #
        # This selector is now correct based on the HTML you provided for the detail page.
        item['phone'] = response.xpath('//a[contains(@href, "tel:")]/text()').get()

        # Extract the full description text, cleaning up whitespace
        description_text = response.xpath('string(//span[contains(@class, "comment more")])').get()
        item['property_details'] = ' '.join(description_text.split())

        yield item