FROM python:3.11-slim

# Build llama-cpp-python with AVX-512 + AVX2 optimisations for Intel Xeon
ENV CMAKE_ARGS="-DGGML_AVX512=ON -DGGML_AVX2=ON -DGGML_NATIVE=OFF"

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential cmake curl && \
    pip install --no-cache-dir \
        llama-cpp-python[server] \
        huggingface-hub && \
    apt-get purge -y build-essential cmake && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY download-model.sh /app/download-model.sh
RUN chmod +x /app/download-model.sh

EXPOSE 8000
