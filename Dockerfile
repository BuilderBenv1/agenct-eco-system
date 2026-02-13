FROM python:3.12-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl && \
    rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY . .

# SERVICE env var selects which agent to run (set per Railway service)
# Options: convergence, tipster, whale, narrative, auditor, liquidation, yield_oracle, bot, gateway
ENV SERVICE=gateway

CMD python -m scripts.start_service
