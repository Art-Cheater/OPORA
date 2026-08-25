FROM python:3.12-slim

WORKDIR /app

ARG WITH_LIBREOFFICE=0

# LibreOffice — конвертация .doc/.rtf в .docx (редко).
# Tesseract — OCR сканов PDF (личные договоры без текстового слоя).
# LibreOffice по умолчанию выкл.: docker compose build --build-arg WITH_LIBREOFFICE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq-dev \
        tesseract-ocr \
        tesseract-ocr-rus \
    && if [ "$WITH_LIBREOFFICE" = "1" ]; then \
        apt-get install -y --no-install-recommends libreoffice-writer fonts-liberation; \
    fi \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV FLASK_APP=run.py
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 5000

COPY docker/entrypoint.sh /entrypoint.sh
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:5000 --worker-class gthread --workers ${WEB_CONCURRENCY:-3} --threads ${GUNICORN_THREADS:-8} --timeout ${GUNICORN_TIMEOUT:-120} --graceful-timeout 30 --keep-alive 5 wsgi:app"]
