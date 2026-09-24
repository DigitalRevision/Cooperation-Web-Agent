FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
WORKDIR /crawler
COPY requirements.txt .
RUN pip install --no-cache-dir scrapy pyyaml
COPY . .
CMD ["scrapy", "crawl", "company_sites", "-s", "PK_DATA_DIR=/data"]
