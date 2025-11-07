FROM python:3.11-slim

WORKDIR /app
COPY log_pipeline/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY log_pipeline /app/log_pipeline

# Default: run parser once; override CMD for daemon mode or streamlit
CMD ["python", "log_pipeline/parser.py", "--config", "log_pipeline/config.yml", "--once"]
