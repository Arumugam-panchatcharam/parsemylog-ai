FROM python:3.11-slim
MAINTAINER p.arumugam@telekom-digital.com

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

VOLUME ["/app"]

EXPOSE 40901