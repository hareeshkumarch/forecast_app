FROM python:3.11

WORKDIR /app

# System dependencies needed for building C++ extensions (Prophet/Stan)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .

# Install cmdstanpy first and pre-install CmdStan so Prophet can find its backend
RUN pip install --no-cache-dir cmdstanpy==1.2.4 && \
    python -c "import cmdstanpy; cmdstanpy.install_cmdstan(progress=False)"

# Set the CMDSTAN env var so Prophet always finds it
ENV CMDSTAN=/root/.cmdstan/cmdstan-2.35.0
ENV STAN_BACKEND=CMDSTANPY

# Now install the rest of the dependencies (including prophet)
RUN pip install --no-cache-dir -r requirements.txt

# Copy ML engine source
COPY . .

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
