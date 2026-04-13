#!/usr/bin/env python3
"""
Scrapy MCP Server - Provides MCP tools for running Scrapy spiders in Docker
"""
import asyncio
import os
import sqlite3
import json
import csv
from typing import Optional, Dict, Any
from datetime import datetime
from pathlib import Path

import docker
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.responses import Response

# Configuration
SCRAPY_PROJECT_PATH = os.environ.get('SCRAPY_PROJECT_PATH', '/workspace')
SCRAPY_PROJECT_HOST_PATH = os.environ.get('SCRAPY_PROJECT_HOST_PATH', SCRAPY_PROJECT_PATH)
SCRAPY_IMAGE = os.environ.get('SCRAPY_IMAGE', 'realestate-scraper:latest')
DB_PATH = os.path.join(SCRAPY_PROJECT_PATH, 'properties.db')

# Initialize MCP Server
server = Server("scrapy-mcp-server")
docker_client = None

# Container tracking
running_containers = {}


def get_docker_client():
    """Get or create Docker client"""
    global docker_client
    if docker_client is None:
        docker_client = docker.from_env()
    return docker_client


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available MCP tools"""
    return [
        Tool(
            name="scrapy_run_spider",
            description="Run the Scrapy spider to scrape real estate listings. Optionally limit pages for testing.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit_pages": {
                        "type": "integer",
                        "description": "Limit scraping to N pages (optional, for testing)",
                    }
                },
            },
        ),
        Tool(
            name="scrapy_check_status",
            description="Check if a Scrapy spider is currently running",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="scrapy_get_results",
            description="Query the SQLite database and return scraped property listings",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default: 100)",
                    }
                },
            },
        ),
        Tool(
            name="scrapy_get_stats",
            description="Get statistics about scraped properties",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="scrapy_export_csv",
            description="Export all properties to CSV format",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="scrapy_export_json",
            description="Export all properties to JSON format",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls"""

    if name == "scrapy_run_spider":
        return await run_spider(arguments.get("limit_pages"))

    elif name == "scrapy_check_status":
        return await check_status()

    elif name == "scrapy_get_results":
        limit = arguments.get("limit", 100)
        return await get_results(limit)

    elif name == "scrapy_get_stats":
        return await get_stats()

    elif name == "scrapy_export_csv":
        return await export_csv()

    elif name == "scrapy_export_json":
        return await export_json()

    else:
        return [TextContent(
            type="text",
            text=f"Unknown tool: {name}"
        )]


async def run_spider(limit_pages: Optional[int] = None) -> list[TextContent]:
    """Run Scrapy spider in Docker container - ASYNC mode (returns immediately)"""
    try:
        client = get_docker_client()

        # Build command
        cmd = ["scrapy", "crawl", "realestate"]
        if limit_pages:
            cmd.extend(["-s", f"CLOSESPIDER_PAGECOUNT={limit_pages}"])

        # Run container in detached mode
        container = client.containers.run(
            SCRAPY_IMAGE,
            command=cmd,
            volumes={
                SCRAPY_PROJECT_HOST_PATH: {  # Use host path, not container path
                    'bind': '/usr/src/app',
                    'mode': 'rw'
                }
            },
            working_dir='/usr/src/app',  # Set working directory to Scrapy project
            detach=True,
            remove=True,  # Auto-remove when finished
            name=f"scrapy-spider-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        )

        # Store container reference
        container_id = container.id
        running_containers[container_id] = {
            'started_at': datetime.now().isoformat(),
            'limit_pages': limit_pages,
            'container': container
        }

        # Return immediately - don't wait for completion
        return [TextContent(
            type="text",
            text=json.dumps({
                "success": True,
                "message": f"Scrapy spider started successfully{' (limited to ' + str(limit_pages) + ' pages)' if limit_pages else ' (scraping all pages)'}",
                "container_id": container_id,
                "status": "running",
                "started_at": running_containers[container_id]['started_at'],
                "note": "Use scrapy_check_status to monitor progress. This may take several minutes."
            }, indent=2)
        )]

    except Exception as e:
        return [TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": str(e)
            }, indent=2)
        )]


async def check_status() -> list[TextContent]:
    """Check if spider is currently running"""
    try:
        client = get_docker_client()

        # Check for running containers with our naming pattern
        containers = client.containers.list(filters={"name": "scrapy-spider-"})

        if containers:
            running_info = []
            for container in containers:
                info = running_containers.get(container.id, {})
                running_info.append({
                    "container_id": container.id,
                    "name": container.name,
                    "status": container.status,
                    "started_at": info.get('started_at', 'unknown'),
                    "limit_pages": info.get('limit_pages')
                })

            return [TextContent(
                type="text",
                text=json.dumps({
                    "running": True,
                    "count": len(containers),
                    "containers": running_info
                }, indent=2)
            )]
        else:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "running": False,
                    "message": "No Scrapy spiders currently running"
                }, indent=2)
            )]

    except Exception as e:
        return [TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": str(e)
            }, indent=2)
        )]


async def get_results(limit: int = 100) -> list[TextContent]:
    """Query database and return results"""
    try:
        if not os.path.exists(DB_PATH):
            return [TextContent(
                type="text",
                text=json.dumps({
                    "success": False,
                    "error": f"Database not found at {DB_PATH}. Run spider first."
                }, indent=2)
            )]

        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        cur.execute(f'SELECT * FROM properties ORDER BY last_updated_date DESC LIMIT {limit}')
        rows = cur.fetchall()
        con.close()

        properties = [dict(row) for row in rows]

        return [TextContent(
            type="text",
            text=json.dumps({
                "success": True,
                "count": len(properties),
                "properties": properties
            }, indent=2)
        )]

    except Exception as e:
        return [TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": str(e)
            }, indent=2)
        )]


async def get_stats() -> list[TextContent]:
    """Get statistics about scraped properties"""
    try:
        if not os.path.exists(DB_PATH):
            return [TextContent(
                type="text",
                text=json.dumps({
                    "success": False,
                    "error": f"Database not found at {DB_PATH}"
                }, indent=2)
            )]

        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()

        # Total count
        cur.execute('SELECT COUNT(*) FROM properties')
        total = cur.fetchone()[0]

        # Count by category
        cur.execute('SELECT category, COUNT(*) as count FROM properties GROUP BY category')
        by_category = {row[0]: row[1] for row in cur.fetchall()}

        # Count by location
        cur.execute('SELECT location, COUNT(*) as count FROM properties GROUP BY location ORDER BY count DESC LIMIT 10')
        by_location = {row[0]: row[1] for row in cur.fetchall()}

        # Recent additions
        cur.execute('SELECT COUNT(*) FROM properties WHERE date(first_seen_date) = date("now")')
        added_today = cur.fetchone()[0]

        con.close()

        return [TextContent(
            type="text",
            text=json.dumps({
                "success": True,
                "total_properties": total,
                "added_today": added_today,
                "by_category": by_category,
                "top_10_locations": by_location
            }, indent=2)
        )]

    except Exception as e:
        return [TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": str(e)
            }, indent=2)
        )]


async def export_csv() -> list[TextContent]:
    """Export properties to CSV"""
    try:
        if not os.path.exists(DB_PATH):
            return [TextContent(
                type="text",
                text=json.dumps({
                    "success": False,
                    "error": f"Database not found at {DB_PATH}"
                }, indent=2)
            )]

        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        cur.execute('SELECT * FROM properties ORDER BY last_updated_date DESC')
        rows = cur.fetchall()
        con.close()

        if not rows:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "success": False,
                    "error": "No properties found in database"
                }, indent=2)
            )]

        # Generate CSV
        output_path = os.path.join(SCRAPY_PROJECT_PATH, f'properties_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv')

        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            fieldnames = rows[0].keys()
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows([dict(row) for row in rows])

        return [TextContent(
            type="text",
            text=json.dumps({
                "success": True,
                "message": f"CSV exported successfully",
                "file_path": output_path,
                "row_count": len(rows)
            }, indent=2)
        )]

    except Exception as e:
        return [TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": str(e)
            }, indent=2)
        )]


async def export_json() -> list[TextContent]:
    """Export properties to JSON"""
    try:
        if not os.path.exists(DB_PATH):
            return [TextContent(
                type="text",
                text=json.dumps({
                    "success": False,
                    "error": f"Database not found at {DB_PATH}"
                }, indent=2)
            )]

        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        cur.execute('SELECT * FROM properties ORDER BY last_updated_date DESC')
        rows = cur.fetchall()
        con.close()

        if not rows:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "success": False,
                    "error": "No properties found in database"
                }, indent=2)
            )]

        # Generate JSON
        output_path = os.path.join(SCRAPY_PROJECT_PATH, f'properties_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json')

        properties = [dict(row) for row in rows]

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(properties, f, indent=2, ensure_ascii=False)

        return [TextContent(
            type="text",
            text=json.dumps({
                "success": True,
                "message": f"JSON exported successfully",
                "file_path": output_path,
                "row_count": len(rows)
            }, indent=2)
        )]

    except Exception as e:
        return [TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": str(e)
            }, indent=2)
        )]


# Create SSE transport
sse = SseServerTransport("/messages")


async def handle_sse(request):
    """Handle SSE connections for MCP"""
    async with sse.connect_sse(
        request.scope, request.receive, request._send
    ) as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )
    return Response()  # CRITICAL: Must return Response to avoid TypeError


async def handle_direct_run_spider(request):
    """Direct HTTP endpoint to start scraper (for scheduled workflows)"""
    try:
        # Call the existing run_spider function
        result = await run_spider(limit_pages=None)

        # Return JSON response
        return Response(
            content=result[0].text,
            media_type="application/json"
        )
    except Exception as e:
        return Response(
            content=json.dumps({"success": False, "error": str(e)}),
            media_type="application/json",
            status_code=500
        )


# Create Starlette app
app = Starlette(
    routes=[
        Route("/sse", endpoint=handle_sse, methods=["GET"]),
        Route("/direct/run-spider", endpoint=handle_direct_run_spider, methods=["POST"]),
        Mount("/messages", app=sse.handle_post_message),
    ]
)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8888))

    print(f"🚀 Scrapy MCP Server starting on port {port}")
    print(f"📂 Scrapy project path: {SCRAPY_PROJECT_PATH}")
    print(f"🐳 Docker image: {SCRAPY_IMAGE}")
    print(f"💾 Database path: {DB_PATH}")

    uvicorn.run(app, host="0.0.0.0", port=port)
# Build timestamp: Sat, Nov  8, 2025  9:01:08 PM
