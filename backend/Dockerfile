# syntax=docker/dockerfile:1
FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src
COPY pyproject.toml ./
COPY app ./app
RUN pip install --prefix=/install .

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 IGUARD_ENV=production
RUN useradd --system --uid 10001 --home /app iguard
WORKDIR /app
COPY --from=build /install /usr/local
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod 0555 /usr/local/bin/docker-entrypoint.sh && chown -R iguard /app
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=4s --start-period=40s --retries=5 \
  CMD python -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health',timeout=3).status==200 else 1)"
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header", "--proxy-headers", "--forwarded-allow-ips", "*", "--timeout-graceful-shutdown", "20"]
