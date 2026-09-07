FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 bot
WORKDIR /app
COPY requirements.txt .
RUN python -m pip install -r requirements.txt
COPY --chown=1000:1000 . .
RUN mkdir -p /app/data && chown -R 1000:1000 /app
USER 1000
EXPOSE 7860
CMD ["python", "main.py"]
