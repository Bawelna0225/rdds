FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN groupadd --system --gid 10003 rdds-agent \
    && useradd --system --uid 10003 --gid rdds-agent --groups dialout \
        --home-dir /nonexistent rdds-agent \
    && install -d -o rdds-agent -g rdds-agent /var/lib/rdds-agent

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=rdds-agent:rdds-agent rdds_agent.py ./rdds_agent.py

USER rdds-agent:rdds-agent

CMD ["python", "rdds_agent.py"]
