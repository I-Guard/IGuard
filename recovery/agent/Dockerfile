FROM python:3.12-slim
RUN pip install --no-cache-dir PyYAML==6.0.3 && useradd --system --uid 10001 agent
WORKDIR /app
COPY agent.py /app/agent.py
USER 10001
EXPOSE 8088
HEALTHCHECK --interval=15s --timeout=3s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8088/healthz',timeout=2)"
CMD ["python", "/app/agent.py"]
