# Сборка из корня проекта (docker-compose: context: ., dockerfile: crawler/Dockerfile): нужен общий пакет pkdb
FROM python:3.12-slim
WORKDIR /crawler
# scrapy-playwright из requirements.txt ставится отдельно, только для сайтов с JavaScript
RUN pip install --no-cache-dir scrapy pyyaml "psycopg[binary]"
COPY crawler/ .
COPY pkdb/ pkdb/
CMD ["scrapy", "crawl", "company_sites"]
