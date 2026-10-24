FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

RUN useradd --create-home --uid 10001 app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
USER app

EXPOSE 8000
# O worker usa a mesma imagem com outro comando (ver docker-compose.yml)
# Em produção, aplica as migrações do banco antes de subir (mesmo sem o docker-compose.prod.yml).
CMD ["sh", "-c", "if [ \"$ENVIRONMENT\" = production ]; then alembic upgrade head; fi && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips '*'"]
