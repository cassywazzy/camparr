FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY camparr/ camparr/

RUN mkdir -p /config /downloads

ENV PYTHONUNBUFFERED=1
ENV CAMPARR_CONFIG=/config/config.yml
ENV CAMPARR_DB=/config/camparr.db

EXPOSE 8585

ENTRYPOINT ["tini", "--"]
CMD ["python", "-m", "camparr"]
