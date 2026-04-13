#!/usr/bin/env python3
"""
Test suite to verify the Real Estate Scraper setup
"""
import sqlite3
import os
import subprocess
import sys
from datetime import datetime

def print_test(test_name, passed, details=""):
    """Print test results with color"""
    status = "[PASS]" if passed else "[FAIL]"
    print(f"{status} - {test_name}")
    if details:
        print(f"    {details}")
    print()

def test_1_check_files_exist():
    """Test 1: Verify all required files exist"""
    print("=" * 60)
    print("TEST 1: Checking Required Files")
    print("=" * 60)

    required_files = [
        'Dockerfile',
        'docker-compose.yml',
        'requirements.txt',
        'scrapy.cfg',
        'realestate_scraper/spiders/real_estate_spider.py',
        'realestate_scraper/pipelines.py',
        'realestate_scraper/settings.py',
    ]

    all_exist = True
    for file_path in required_files:
        exists = os.path.exists(file_path)
        print_test(f"File exists: {file_path}", exists)
        if not exists:
            all_exist = False

    return all_exist

def test_2_check_database_schema():
    """Test 2: Verify database schema is correct"""
    print("=" * 60)
    print("TEST 2: Checking Database Schema")
    print("=" * 60)

    db_path = 'properties.db'

    if not os.path.exists(db_path):
        print_test("Database exists", False, "Database file not found. Run scraper first.")
        return False

    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()

        # Get table schema
        cur.execute("PRAGMA table_info(properties)")
        columns = cur.fetchall()

        expected_columns = {
            'title', 'link', 'price', 'category', 'location',
            'bedrooms', 'bathrooms', 'phone', 'property_details',
            'first_seen_date', 'last_seen_date', 'last_updated_date'
        }

        actual_columns = {col[1] for col in columns}

        # Check if all expected columns exist
        missing = expected_columns - actual_columns
        extra = actual_columns - expected_columns

        has_all_columns = len(missing) == 0
        print_test("All required columns exist", has_all_columns,
                   f"Missing: {missing}" if missing else "All columns present")

        if extra:
            print_test("No extra columns", False, f"Extra: {extra}")

        # Check primary key
        cur.execute("PRAGMA table_info(properties)")
        pk_columns = [col[1] for col in cur.fetchall() if col[5] > 0]
        has_pk = 'link' in pk_columns
        print_test("Primary key on 'link' column", has_pk)

        con.close()
        return has_all_columns and has_pk

    except Exception as e:
        print_test("Database schema check", False, f"Error: {e}")
        return False

def test_3_check_timestamp_functionality():
    """Test 3: Verify timestamp fields work correctly"""
    print("=" * 60)
    print("TEST 3: Checking Timestamp Functionality")
    print("=" * 60)

    db_path = 'properties.db'

    if not os.path.exists(db_path):
        print_test("Timestamp test", False, "Database not found")
        return False

    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()

        # Check if there are any records
        cur.execute("SELECT COUNT(*) FROM properties")
        count = cur.fetchone()[0]

        print_test(f"Database has records", count > 0, f"Found {count} properties")

        if count > 0:
            # Check if timestamp fields are populated
            cur.execute("""
                SELECT
                    COUNT(*) as total,
                    COUNT(first_seen_date) as has_first_seen,
                    COUNT(last_seen_date) as has_last_seen,
                    COUNT(last_updated_date) as has_last_updated
                FROM properties
            """)
            stats = cur.fetchone()

            all_have_timestamps = (
                stats[1] == stats[0] and
                stats[2] == stats[0] and
                stats[3] == stats[0]
            )

            print_test("All properties have timestamps", all_have_timestamps,
                      f"{stats[1]}/{stats[0]} have first_seen_date, "
                      f"{stats[2]}/{stats[0]} have last_seen_date, "
                      f"{stats[3]}/{stats[0]} have last_updated_date")

            # Check timestamp format (should be ISO format)
            cur.execute("SELECT first_seen_date FROM properties WHERE first_seen_date IS NOT NULL LIMIT 1")
            sample = cur.fetchone()
            if sample:
                try:
                    datetime.fromisoformat(sample[0])
                    print_test("Timestamps are in ISO format", True, f"Example: {sample[0]}")
                except ValueError:
                    print_test("Timestamps are in ISO format", False, f"Invalid format: {sample[0]}")

        con.close()
        return True

    except Exception as e:
        print_test("Timestamp functionality check", False, f"Error: {e}")
        return False

def test_4_check_docker_image():
    """Test 4: Verify Docker image exists and is runnable"""
    print("=" * 60)
    print("TEST 4: Checking Docker Image")
    print("=" * 60)

    try:
        # Check if Docker is installed
        result = subprocess.run(['docker', '--version'],
                              capture_output=True, text=True, timeout=5)
        docker_installed = result.returncode == 0
        print_test("Docker is installed", docker_installed, result.stdout.strip())

        if not docker_installed:
            return False

        # Check if our image exists
        result = subprocess.run(['docker', 'images', 'realestate-scraper', '--format', '{{.Repository}}:{{.Tag}}'],
                              capture_output=True, text=True, timeout=5)

        image_exists = 'realestate-scraper:latest' in result.stdout
        print_test("Docker image 'realestate-scraper:latest' exists", image_exists)

        return image_exists

    except subprocess.TimeoutExpired:
        print_test("Docker check", False, "Command timed out")
        return False
    except FileNotFoundError:
        print_test("Docker is installed", False, "Docker command not found")
        return False
    except Exception as e:
        print_test("Docker check", False, f"Error: {e}")
        return False

def test_5_check_pipeline_configuration():
    """Test 5: Verify Scrapy pipeline is properly configured"""
    print("=" * 60)
    print("TEST 5: Checking Pipeline Configuration")
    print("=" * 60)

    try:
        # Import settings to check configuration
        sys.path.insert(0, os.getcwd())
        from realestate_scraper import settings

        # Check if pipeline is enabled
        pipelines = getattr(settings, 'ITEM_PIPELINES', {})
        pipeline_enabled = 'realestate_scraper.pipelines.RealestateScraperPipeline' in pipelines
        print_test("Pipeline is enabled in settings", pipeline_enabled)

        # Check download delay (should be > 0 to be polite)
        delay = getattr(settings, 'DOWNLOAD_DELAY', 0)
        has_delay = delay > 0
        print_test("Download delay is configured", has_delay, f"Delay: {delay} seconds")

        # Check user agent is set
        user_agent = getattr(settings, 'USER_AGENT', '')
        has_user_agent = len(user_agent) > 0 and user_agent != 'Scrapy'
        print_test("Custom User-Agent is set", has_user_agent)

        return pipeline_enabled and has_delay and has_user_agent

    except Exception as e:
        print_test("Pipeline configuration check", False, f"Error: {e}")
        return False

def test_6_run_quick_scrape():
    """Test 6: Run a quick scrape test (1 page only)"""
    print("=" * 60)
    print("TEST 6: Running Quick Scrape Test")
    print("=" * 60)

    try:
        print("Running Docker container with page limit...")
        result = subprocess.run([
            'docker', 'run', '--rm',
            '-v', f'{os.getcwd()}:/usr/src/app',
            'realestate-scraper:latest',
            'scrapy', 'crawl', 'realestate',
            '-s', 'CLOSESPIDER_PAGECOUNT=1'
        ], capture_output=True, text=True, timeout=120)

        success = result.returncode == 0
        print_test("Docker scraper executed successfully", success)

        if success:
            # Check if database was updated
            if os.path.exists('properties.db'):
                con = sqlite3.connect('properties.db')
                cur = con.cursor()
                cur.execute("SELECT COUNT(*) FROM properties")
                count = cur.fetchone()[0]
                con.close()

                print_test("Properties were scraped", count > 0, f"Found {count} properties in database")
                return True
            else:
                print_test("Database was created", False)
                return False
        else:
            print(f"Error output:\n{result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        print_test("Scrape test", False, "Scraper timed out after 120 seconds")
        return False
    except Exception as e:
        print_test("Scrape test", False, f"Error: {e}")
        return False

def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("REAL ESTATE SCRAPER - SETUP VERIFICATION")
    print("=" * 60 + "\n")

    results = {}

    # Run all tests
    results['files'] = test_1_check_files_exist()
    results['schema'] = test_2_check_database_schema()
    results['timestamps'] = test_3_check_timestamp_functionality()
    results['docker'] = test_4_check_docker_image()
    results['pipeline'] = test_5_check_pipeline_configuration()

    # Only run scrape test if all other tests pass
    if all([results['files'], results['docker'], results['pipeline']]):
        print("\n*** Running live scrape test (this will take ~30 seconds)...")
        print("=" * 60)
        results['scrape'] = test_6_run_quick_scrape()
    else:
        print("\n*** WARNING: Skipping scrape test due to previous failures")
        results['scrape'] = False

    # Print summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    total = len(results)
    passed = sum(1 for v in results.values() if v)

    for test_name, result in results.items():
        status = "[PASS]" if result else "[FAIL]"
        print(f"{status} - {test_name}")

    print()
    print(f"Results: {passed}/{total} tests passed")

    if passed == total:
        print("\n*** All tests passed! Your setup is ready to go! ***")
        return 0
    else:
        print(f"\n*** WARNING: {total - passed} test(s) failed. Please review the output above. ***")
        return 1

if __name__ == "__main__":
    sys.exit(main())
