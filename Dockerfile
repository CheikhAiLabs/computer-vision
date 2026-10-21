FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl iproute2 iputils-ping netcat-openbsd dnsutils && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --create-home --uid 10001 lab && mkdir /certs && chown lab:lab /certs
COPY common /app/common
COPY services /app/services
COPY tools /tools
USER lab
CMD ["python", "-m", "services.opcua_sim.main"]
