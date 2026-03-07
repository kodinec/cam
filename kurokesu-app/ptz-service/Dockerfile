FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir pyserial==3.5

WORKDIR /app
COPY server.py /app/server.py

EXPOSE 8081
ENTRYPOINT ["python3", "/app/server.py"]
