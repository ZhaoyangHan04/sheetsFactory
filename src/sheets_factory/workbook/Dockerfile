FROM ubuntu:24.04@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852
ENV DEBIAN_FRONTEND=noninteractive TZ=UTC LANG=C.UTF-8
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-calc=4:24.2.7-0ubuntu0.24.04.7 \
    python3-uno=4:24.2.7-0ubuntu0.24.04.7 python3-openpyxl fonts-liberation fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
RUN /usr/bin/python3 -c 'import hashlib,io,urllib.request,zipfile; payload=urllib.request.urlopen("https://files.pythonhosted.org/packages/c0/da/977ded879c29cbd04de313843e76868e6e13408a94ed6b987245dc7c8506/openpyxl-3.1.5-py2.py3-none-any.whl",timeout=90).read(); assert hashlib.sha256(payload).hexdigest()=="5282c12b107bffeef825f4617dc029afaf41d0ea60823bbb665ef3079dc79de2"; zipfile.ZipFile(io.BytesIO(payload)).extractall("/usr/local/lib/python3.12/dist-packages")' \
    && /usr/bin/python3 -c 'import openpyxl; assert openpyxl.__version__=="3.1.5"'
RUN useradd --uid 10001 --create-home worker \
    && mkdir -p /work && chown worker:worker /work
COPY uno_recalculate.py /opt/uno_recalculate.py
RUN chmod 0755 / /home /opt && chmod 0644 /opt/uno_recalculate.py
USER worker
WORKDIR /work
ENTRYPOINT ["/usr/bin/python3", "/opt/uno_recalculate.py"]
