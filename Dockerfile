FROM python:3.10-slim-bullseye

RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \          
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt main.py ./

RUN pip install --no-cache-dir -r requirements.txt

ENV WHISPER_MODEL=small \
    HEALTH_SERVER_PORT=8080 \
    PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["python", "main.py"]
