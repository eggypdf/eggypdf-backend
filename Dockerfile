FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ghostscript \
    libreoffice-writer \
    libreoffice-calc \
    libreoffice-impress \
    poppler-utils \
    fonts-liberation \
    fonts-dejavu-core \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the existing PDF backend plus the isolated Career Pro modules.
COPY app.py career_engine.py career_routes.py wsgi.py ./

ENV PORT=10000
ENV PYTHONUNBUFFERED=1
EXPOSE 10000

# wsgi.py registers the Career Pro blueprint on the existing Flask app.
CMD gunicorn wsgi:app --bind 0.0.0.0:$PORT --timeout 300 --workers 1 --preload
