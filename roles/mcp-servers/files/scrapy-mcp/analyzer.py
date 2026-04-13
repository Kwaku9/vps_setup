import sqlite3
import json
import csv
from googletrans import Translator

# --- CONFIGURATION ---
DB_FILE = 'properties.db'
PREFERENCES_FILE = 'preferences.json'
OUTPUT_FILE = 'furnished_list.csv'

def load_preferences():
    """Loads the user's preferences from the JSON file."""
    print(f"Loading preferences from {PREFERENCES_FILE}...")
    with open(PREFERENCES_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def get_properties_from_db():
    """Connects to the SQLite database and fetches all properties."""
    print(f"Connecting to database '{DB_FILE}' and fetching properties...")
    try:
        con = sqlite3.connect(DB_FILE)
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute("SELECT * FROM properties")
        rows = cur.fetchall()
        con.close()
        print(f"Found {len(rows)} properties in the database.")
        return [dict(row) for row in rows]
    except sqlite3.OperationalError:
        print(f"Error: Database file '{DB_FILE}' not found. Please run the scraper first to create it.")
        return []

def find_furnished_properties(properties, keywords):
    """Scans for properties matching keywords in title or details."""
    print("Scanning for furnished properties...")
    furnished_list = []
    for prop in properties:
        title_text = (prop.get('title') or "").lower()
        details_text = (prop.get('property_details') or "").lower()
        
        if any(keyword in title_text or keyword in details_text for keyword in keywords):
            print(f"  + Found furnished property: '{prop.get('title')}'")
            furnished_list.append(prop)
    
    print(f"Found {len(furnished_list)} potential furnished properties.")
    return furnished_list

def translate_furnished_list(furnished_list):
    """Translates the details for the furnished properties."""
    if not furnished_list:
        return []
        
    print(f"Translating details for {len(furnished_list)} furnished properties...")
    translator = Translator()
    
    for prop in furnished_list:
        original_details = prop.get('property_details', '')
        if original_details:
            try:
                translated = translator.translate(original_details, src='es', dest='en')
                prop['details_english'] = translated.text
            except Exception as e:
                print(f"  [Warning] Could not translate details for '{prop.get('title')}'. Error: {e}")
                prop['details_english'] = "Translation Failed"
        else:
            prop['details_english'] = ""
    return furnished_list

def write_furnished_list_to_csv(furnished_properties):
    """Writes the final ranked list to a CSV file."""
    if not furnished_properties:
        print("No properties were furnished to write to CSV.")
        return

    print(f"Writing {len(furnished_properties)} furnished properties to {OUTPUT_FILE}...")
    
    headers = list(furnished_properties[0].keys())
    if 'details_english' not in headers:
         headers.append('details_english')

    with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(furnished_properties)

if __name__ == "__main__":
    preferences = load_preferences()
    spanish_keywords = preferences.get("primary_keywords_spanish", [])
    
    all_properties = get_properties_from_db()
    
    if all_properties and spanish_keywords:
        furnished_properties = find_furnished_properties(all_properties, spanish_keywords)
        translated_furnished_list = translate_furnished_list(furnished_properties)
        write_furnished_list_to_csv(translated_furnished_list)
        print(f"\nAnalysis complete. Your furnished list has been saved to '{OUTPUT_FILE}'.")
    elif not spanish_keywords:
        print("No keywords found in preferences.json. Cannot generate furnished list.")
    else:
        print("No properties found in the database to analyze. Please run the Scrapy spider first.")