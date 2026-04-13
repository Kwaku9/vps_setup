import sqlite3
from itemadapter import ItemAdapter
from datetime import datetime

class RealestateScraperPipeline:
    def __init__(self):
        self.con = sqlite3.connect('properties.db')
        self.cur = self.con.cursor()
        self.create_table()

    def create_table(self):
        self.cur.execute("""CREATE TABLE IF NOT EXISTS properties(
            title TEXT,
            link TEXT PRIMARY KEY,
            price REAL,
            category TEXT,
            location TEXT,
            bedrooms TEXT,
            bathrooms TEXT,
            phone TEXT,
            property_details TEXT,
            first_seen_date TEXT,
            last_seen_date TEXT,
            last_updated_date TEXT
        )""")

    def process_item(self, item, spider):
        adapter = ItemAdapter(item)

        # --- Data Cleaning ---
        for field_name in adapter.field_names():
            value = adapter.get(field_name)
            if isinstance(value, str):
                adapter[field_name] = value.strip()

        price = adapter.get('price')
        if price:
            cleaned_price = str(price).replace('$', '').replace(',', '').strip()
            try:
                adapter['price'] = float(cleaned_price)
            except (ValueError, TypeError):
                adapter['price'] = None
        else:
            adapter['price'] = None

        # --- Database Upsert with Timestamps ---
        current_time = datetime.now().isoformat()
        link = adapter.get('link')

        # Check if property already exists
        self.cur.execute("SELECT link, first_seen_date FROM properties WHERE link = ?", (link,))
        existing = self.cur.fetchone()

        if existing:
            # Update existing property (keep first_seen_date, update last_seen_date and last_updated_date)
            self.cur.execute("""
                UPDATE properties SET
                    title = ?, price = ?, category = ?, location = ?, bedrooms = ?,
                    bathrooms = ?, phone = ?, property_details = ?,
                    last_seen_date = ?, last_updated_date = ?
                WHERE link = ?
            """, (
                adapter.get('title'),
                adapter.get('price'),
                adapter.get('category'),
                adapter.get('location'),
                adapter.get('bedrooms'),
                adapter.get('bathrooms'),
                adapter.get('phone'),
                adapter.get('property_details'),
                current_time,
                current_time,
                link
            ))
        else:
            # Insert new property with all three timestamps set to current time
            self.cur.execute("""
                INSERT INTO properties (title, link, price, category, location, bedrooms, bathrooms, phone, property_details, first_seen_date, last_seen_date, last_updated_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                adapter.get('title'),
                link,
                adapter.get('price'),
                adapter.get('category'),
                adapter.get('location'),
                adapter.get('bedrooms'),
                adapter.get('bathrooms'),
                adapter.get('phone'),
                adapter.get('property_details'),
                current_time,
                current_time,
                current_time
            ))

        self.con.commit()
        return item

    def close_spider(self, spider):
        self.con.close()
