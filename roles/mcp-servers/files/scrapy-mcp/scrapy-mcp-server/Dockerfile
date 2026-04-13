FROM python:3.11-slim

# Install Docker CLI (needed to communicate with Docker socket)
RUN apt-get update && \
    apt-get install -y \
    curl \
    ca-certificates \
    gnupg \
    lsb-release && \
    mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg && \
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
      $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null && \
    apt-get update && \
    apt-get install -y docker-ce-cli && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy MCP server code
COPY scrapy_mcp_server.py .

# Expose port
EXPOSE 8888

# Set environment variables
ENV PORT=8888
ENV SCRAPY_PROJECT_PATH=/workspace
ENV SCRAPY_IMAGE=realestate-scraper:latest

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD curl -f --max-time 2 http://localhost:8888/sse || exit 1

# Run the server
CMD ["python", "scrapy_mcp_server.py"]
