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
    "httpx>=0.28" \
    "pandas>=2.2,<3" \
    "pyarrow>=18,<24"

COPY apps/api /app
COPY packages /opt/packages
ENV PYTHONPATH=/app:/opt
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
