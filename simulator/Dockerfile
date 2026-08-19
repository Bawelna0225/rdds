FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN groupadd --system --gid 10002 rdds-sim \
    && useradd --system --uid 10002 --gid rdds-sim --home-dir /nonexistent rdds-sim

COPY --chown=rdds-sim:rdds-sim main.py ./main.py

USER rdds-sim:rdds-sim

CMD ["python", "main.py"]
