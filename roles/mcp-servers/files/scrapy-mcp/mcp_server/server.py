#!/usr/bin/env python3
"""
Clasificado Real Estate MCP Server

This MCP server exposes the real estate scraper from ScrapyExtractor
as an MCP tool that can be called by Claude Code and n8n.
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from mcp.server.models import InitializationOptions
from mcp.server import NotificationOptions, Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Add parent directory to path so we can import the spider
sys.path.insert(0, str(Path(__file__).parent.parent))

from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings
from realestate_scraper.spiders.real_estate_spider import RealEstateSpider


# Initialize the MCP server
server = Server("clasificado-scraper")


def run_spider(output_format: str = "json") -> dict[str, Any]:
    """
    Run the real estate spider and return results.

    Args:
        output_format: Format for output (json, csv, or both)

    Returns:
        dict with status and results
    """
    try:
        # Get scrapy settings
        settings = get_project_settings()
        settings.set('FEEDS', {
            'properties.json': {
                'format': 'json',
                'encoding': 'utf8',
                'store_empty': False,
                'indent': 4,
            },
            'properties.csv': {
                'format': 'csv',
            },
        })

        # Create and configure the crawler
        process = CrawlerProcess(settings)
        process.crawl(RealEstateSpider)
        process.start()  # This blocks until crawling is finished

        # Read the results
        results = {
            "status": "success",
            "message": "Scraping completed successfully"
        }

        # Read JSON results if requested
        if output_format in ["json", "both"]:
            json_path = Path(__file__).parent.parent / "properties.json"
            if json_path.exists():
                with open(json_path, 'r', encoding='utf-8') as f:
                    results["data"] = json.load(f)
                results["json_file"] = str(json_path)

        # Add CSV path if requested
        if output_format in ["csv", "both"]:
            csv_path = Path(__file__).parent.parent / "properties.csv"
            results["csv_file"] = str(csv_path)

        # Add database path
        db_path = Path(__file__).parent.parent / "properties.db"
        results["database"] = str(db_path)

        return results

    except Exception as e:
        return {
            "status": "error",
            "message": f"Scraping failed: {str(e)}"
        }


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """
    List available tools.
    """
    return [
        Tool(
            name="scrape_clasificado",
            description=(
                "Scrapes real estate rental listings from clasificadosonline.com. "
                "Extracts property details including title, price, location, bedrooms, "
                "bathrooms, phone numbers, and property descriptions. "
                "Returns data in JSON format and also saves to CSV and SQLite database. "
                "Default search: Houses for rent between $1599-$3000."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "output_format": {
                        "type": "string",
                        "description": "Output format preference: 'json', 'csv', or 'both'",
                        "enum": ["json", "csv", "both"],
                        "default": "json"
                    }
                },
                "required": []
            },
        )
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None) -> list[TextContent]:
    """
    Handle tool execution requests.
    """
    if name != "scrape_clasificado":
        raise ValueError(f"Unknown tool: {name}")

    if not arguments:
        arguments = {}

    output_format = arguments.get("output_format", "json")

    # Run the spider in a separate thread to avoid blocking
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, run_spider, output_format)

    return [
        TextContent(
            type="text",
            text=json.dumps(result, indent=2, ensure_ascii=False)
        )
    ]


async def main():
    """Main entry point for the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="clasificado-scraper",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
