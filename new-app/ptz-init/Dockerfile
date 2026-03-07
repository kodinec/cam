FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir pyserial==3.5

COPY ptz_init.py /app/ptz_init.py

ENTRYPOINT ["python", "/app/ptz_init.py"]
