# ══════════════════════════════════════════════════════════════════════════════
# Monitor do Diário Oficial de Mossoró — Dockerfile
#
# Este container executa APENAS o script Python.
# O Chrome roda em um container separado (selenium/standalone-chrome)
# definido no docker-compose.yml.
#
# Construir:  docker build -t monitor-dom .
# Executar:   use docker-compose up (recomendado)
# ══════════════════════════════════════════════════════════════════════════════

FROM python:3.12-slim

# ── Metadados ─────────────────────────────────────────────────────────────────
LABEL maintainer="Monitor DOM Mossoró"
LABEL description="Monitora o Diário Oficial de Mossoró e envia alertas via WhatsApp Web"

# ── Fuso horário do Brasil (Nordeste) ─────────────────────────────────────────
ENV TZ=America/Fortaleza
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata curl \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo "$TZ" > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# ── Diretório de trabalho ──────────────────────────────────────────────────────
WORKDIR /app

# ── Dependências Python (camada separada para cache de build) ─────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Código fonte ───────────────────────────────────────────────────────────────
COPY monitor_diario_oficial.py .

# ── Diretórios de dados (montados como volumes pelo docker-compose) ────────────
RUN mkdir -p /app/logs

# ── Usuário não-root (boa prática de segurança) ───────────────────────────────
RUN useradd -m -u 1000 monitor \
    && chown -R monitor:monitor /app
USER monitor

# ── Saída de log sem buffer (garante que print/logging apareçam em tempo real) ─
ENV PYTHONUNBUFFERED=1

# ── Comando padrão: execução agendada diária ──────────────────────────────────
# Passa --agendar para o script entrar no loop de agendamento interno.
# O horário é configurado via HORARIO_EXECUCAO no docker-compose.yml / .env
CMD ["python", "-u", "monitor_diario_oficial.py", "--agendar"]
