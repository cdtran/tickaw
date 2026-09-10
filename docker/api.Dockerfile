FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    "fastapi>=0.115" \
    "uvicorn[standard]>=0.30" \
    "pydantic-settings>=2.5" \
    "sqlalchemy>=2.0" \
    "psycopg[binary]>=3.2" \
    "alembic>=1.13" \
    "boto3>=1.36" \
    "httpx>=0.28"

COPY apps/api /app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
