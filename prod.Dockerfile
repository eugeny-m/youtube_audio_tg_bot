FROM python:3.12

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip --no-cache-dir \
    && pip install --no-cache-dir -r requirements.txt

COPY bot/ /app/bot/
COPY core/ /app/core/
COPY services/ /app/services/
COPY storage/ /app/storage/
COPY main.py /app/main.py

RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

CMD ["python", "main.py"]
