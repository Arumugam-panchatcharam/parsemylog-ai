FROM python:3.11-slim
MAINTAINER p.arumugam@telekom-digital.com

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

VOLUME ["/app"]

EXPOSE 40901

# Gunicorn: 4 workers, binds to 0.0.0.0:40901
#CMD ["gunicorn", "-w", "8", "-b", "0.0.0.0:40901", "--timeout", "360", "logai_wsgi:server"]