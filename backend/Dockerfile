# Образ платформы: API, сбор из реестров (sync) и миграции баз (pkdb). Сборка из корня проекта:
#   docker build -f backend/Dockerfile .      (docker compose делает это сам)
FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY pkdb pkdb
COPY backend/app app
COPY sync sync
COPY tools tools
# --proxy-headers: адрес посетителя берётся из X-Forwarded-For, который выставляют HTTPS-прокси и nginx (сервис web),
# иначе ограничение частоты запросов считало бы всех пользователей одним адресом. Порт API открыт только на самом сервере
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
