FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    portaudio19-dev \
    espeak \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p data workspace

EXPOSE 8000

CMD ["python", "web/server.py"]
