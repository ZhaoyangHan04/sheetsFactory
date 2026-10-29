FROM ubuntu:24.04@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852
ENV DEBIAN_FRONTEND=noninteractive TZ=UTC LANG=C.UTF-8
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-calc=4:24.2.7-0ubuntu0.24.04.7 \
    python3-uno=4:24.2.7-0ubuntu0.24.04.7 python3-openpyxl fonts-liberation fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --uid 10001 --create-home worker \
    && mkdir -p /work && chown worker:worker /work
COPY uno_recalculate.py /opt/uno_recalculate.py
RUN chmod 0755 / /home /opt && chmod 0644 /opt/uno_recalculate.py
USER worker
WORKDIR /work
ENTRYPOINT ["/usr/bin/python3", "/opt/uno_recalculate.py"]
