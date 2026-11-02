FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    TZ=Asia/Kolkata \
    JOBS_DATA_DIR=/data

RUN apt-get update && apt-get install -y --no-install-recommends tzdata ca-certificates && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY jobs_worker ./jobs_worker

VOLUME ["/data"]

# Long-running scheduler by default; override with `run` for one-shot cron usage.
ENTRYPOINT ["python", "-m", "jobs_worker"]
CMD ["serve"]
