FROM ubuntu:22.04
MAINTAINER p.arumugam@telekom-digital.com

# Install dependencies
RUN apt-get update && apt-get install -y \
    curl ca-certificates python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install Ollama
RUN curl -fsSL https://ollama.com/install.sh | bash

# Python setup
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .

# Set environment vars
ENV OLLAMA_MODEL=llama3
ENV PATH="/root/bin:${PATH}"

# Run Ollama serve on 41030, then pull model, then start FastAPI
CMD bash -c "\
    ollama serve & \
    sleep 8 && \
    ollama pull ${OLLAMA_MODEL} && \
    uvicorn app:app --host 0.0.0.0 --port 8000"