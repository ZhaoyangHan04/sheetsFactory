ARG BASE_IMAGE=sheetsfactory-lo:24.2-iterative-v1
FROM ${BASE_IMAGE}
USER root
COPY openpyxl-3.1.5-py2.py3-none-any.whl /tmp/openpyxl-3.1.5.whl
RUN --network=none /usr/bin/python3 -c "import zipfile; zipfile.ZipFile('/tmp/openpyxl-3.1.5.whl').extractall('/usr/local/lib/python3.12/dist-packages')" \
    && rm /tmp/openpyxl-3.1.5.whl \
    && /usr/bin/python3 -c "import openpyxl; assert openpyxl.__version__ == '3.1.5'"
USER worker
