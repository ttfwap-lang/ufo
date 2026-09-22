FROM python:3.12-slim

LABEL org.opencontainers.image.title="ufo-gx10-tg-runner"
LABEL org.opencontainers.image.description="24/7 Telegram-bot-driven task runner for DGX Spark (gx10)"

# python:3.12-slim has no gcc; urllib-based, zero requirements
RUN useradd -m -u 1001 runner
WORKDIR /app

COPY telegram_runner.py /app/telegram_runner.py
RUN chmod +x /app/telegram_runner.py

USER runner
ENV PYTHONUNBUFFERED=1

CMD ["python3", "-u", "/app/telegram_runner.py"]
