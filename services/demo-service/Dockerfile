FROM python:3.12-slim
RUN useradd --system --uid 10002 demo
WORKDIR /app
COPY app.py /app/app.py
USER 10002
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=3s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=2)"
CMD ["python", "-u", "/app/app.py"]
