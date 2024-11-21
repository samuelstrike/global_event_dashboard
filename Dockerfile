FROM python:3.11-slim

# Add labels for better maintainability
LABEL maintainer="Your Name"
LABEL version="1.0"

WORKDIR /app

# Group ENV commands to reduce layers
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_APP=app.py

COPY requirements.txt .

# Combine pip commands and clean cache in same layer
RUN pip config set global.timeout 1000 && \
    pip install --no-cache-dir --timeout 1000 -r requirements.txt && \
    rm -rf /root/.cache/pip

COPY . .

EXPOSE 5000

# Add healthcheck
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5000/ || exit 1

CMD ["flask", "run", "--host=0.0.0.0"]