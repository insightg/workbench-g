FROM ubuntu:22.04

# Build arg to determine deployment mode
ARG DEPLOYMENT_MODE=local

# Evita prompt interattivi durante l'installazione
ENV DEBIAN_FRONTEND=noninteractive

# Installa le dipendenze di sistema base incluso ttyd
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    tmux \
    libpam0g-dev \
    gcc \
    python3-dev \
    git \
    cmake \
    build-essential \
    libjson-c-dev \
    libwebsockets-dev \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Install nginx and supervisor only for remote mode
RUN if [ "$DEPLOYMENT_MODE" = "remote" ]; then \
        apt-get update && apt-get install -y nginx supervisor && rm -rf /var/lib/apt/lists/*; \
    fi

# Installa ttyd da source
RUN git clone https://github.com/tsl0922/ttyd.git /tmp/ttyd && \
    cd /tmp/ttyd && \
    mkdir build && cd build && \
    cmake .. && \
    make && make install && \
    cd / && rm -rf /tmp/ttyd

# Crea la directory dell'applicazione
WORKDIR /app

# Copia i file dei requirements
COPY requirements.txt .

# Installa le dipendenze Python
RUN pip3 install --no-cache-dir -r requirements.txt

# Copia il resto dell'applicazione
COPY app.py .
COPY templates templates/
COPY static static/

# Create necessary directories
RUN mkdir -p /var/log/flask

# Copy nginx and supervisor configs (will only be used in remote mode)
COPY nginx.conf /tmp/nginx.conf.template
COPY supervisord.conf /tmp/supervisord.conf.template

# Configure nginx and supervisor only for remote mode
RUN if [ "$DEPLOYMENT_MODE" = "remote" ]; then \
        cp /tmp/nginx.conf.template /etc/nginx/nginx.conf && \
        cp /tmp/supervisord.conf.template /etc/supervisor/conf.d/supervisord.conf && \
        mkdir -p /var/log/nginx /var/log/supervisor /etc/nginx/terminals && \
        rm -f /etc/nginx/sites-enabled/default; \
    fi

# Set environment variable for runtime
ENV DEPLOYMENT_MODE=${DEPLOYMENT_MODE}

# Expose ports
EXPOSE 7777
EXPOSE 5000

# Conditional CMD based on deployment mode
CMD if [ "$DEPLOYMENT_MODE" = "remote" ]; then \
        /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf; \
    else \
        python3 /app/app.py; \
    fi
