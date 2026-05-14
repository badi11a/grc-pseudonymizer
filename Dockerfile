FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
COPY pseudonymize/ pseudonymize/

RUN pip install --no-cache-dir \
        fastfpe \
        faker \
        sqlalchemy \
        psycopg2-binary \
        scipy \
        xgboost \
        copulas \
    && pip install --no-cache-dir .

# Output directory — mount here to retrieve informe_trazabilidad.json
WORKDIR /output

ENTRYPOINT ["pseudonymize"]
CMD ["--help"]
