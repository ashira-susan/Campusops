FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . /srv/backend
RUN useradd --create-home --uid 10001 app && mkdir -p /data && chown app /data
USER app
ENV CAMPUSOPS_DB=/data/campusops.db PORT=5000
WORKDIR /srv/backend
EXPOSE 5000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:5000/api/health')"
CMD ["sh", "-c", "python seed.py && python run.py"]
