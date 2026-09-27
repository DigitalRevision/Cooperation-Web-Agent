# Сборка из корня проекта (docker-compose: context: ., dockerfile: crawler/Dockerfile): нужен общий пакет pkdb
FROM python:3.12-slim
WORKDIR /crawler
# scrapy-playwright из requirements.txt ставится отдельно, только для сайтов с JavaScript
RUN pip install --no-cache-dir scrapy pyyaml "psycopg[binary]"
COPY crawler/ .
COPY pkdb/ pkdb/
# постоянный процесс: обход после каждого сбора из реестров и задания из админ-панели (daemon.py); разовый обход — scrapy crawl company_sites
CMD ["python", "-u", "daemon.py"]
