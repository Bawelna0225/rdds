FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN groupadd --system --gid 10004 skyspy-emulator \
    && useradd --system --uid 10004 --gid skyspy-emulator \
        --home-dir /nonexistent skyspy-emulator

COPY --chown=skyspy-emulator:skyspy-emulator main.py ./main.py

USER skyspy-emulator:skyspy-emulator

CMD ["python", "main.py"]
