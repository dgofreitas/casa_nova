FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CASA_NOVA_DADOS=/dados \
    CASA_NOVA_MAX_FOTOS=80

WORKDIR /app
COPY crawler/requirements.txt .
RUN pip install -r requirements.txt
COPY crawler/ .
# o que o crawler já acompanhava no GitHub Actions, usado só na primeira vez
COPY data/casas.json semente-casas.json

# o volume de dados é de quem roda o site também
RUN useradd --uid 1000 --create-home casa && mkdir -p /dados && chown casa /dados
USER casa

CMD ["python", "servidor.py"]
