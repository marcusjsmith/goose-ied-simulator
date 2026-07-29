FROM python:3.12-slim-bookworm

LABEL org.opencontainers.image.title="IEC 61850 GOOSE IED Simulator"
LABEL org.opencontainers.image.description="Simulates an IED publishing GOOSE multicast messages with web UI"

RUN apt-get update && apt-get install -y --no-install-recommends \
    iproute2 \
    tcpdump \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

ENV GOOSE_INTERFACE=eth0
ENV GOOSE_APP_ID=0x0001
ENV GOOSE_SIMULATION_MODE=false
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

# Raw sockets require CAP_NET_RAW; use host networking for multicast
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
