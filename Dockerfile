# Étape de construction
FROM python:3.10-slim-bullseye as builder

# Installer les dépendances système minimales
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

ARG WHISPER_MODEL=small
RUN python -c "import whisper; whisper.load_model('$WHISPER_MODEL')"

FROM python:3.10-slim-bullseye

RUN apt-get update && apt-get install -y \
    ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /root/.local /root/.local
COPY --from=builder /root/.cache/whisper /root/.cache/whisper
WORKDIR /app
COPY bot.py .

ENV WHISPER_MODEL=$WHISPER_MODEL \
    HEALTH_SERVER_PORT=8080 \
    PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["python", "main.py"]