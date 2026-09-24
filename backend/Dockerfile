FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
# --proxy-headers: адрес посетителя берётся из X-Forwarded-For, который выставляют HTTPS-прокси и nginx (сервис web),
# иначе ограничение частоты запросов считало бы всех пользователей одним адресом. Порт API открыт только на самом сервере
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
