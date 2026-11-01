FROM sheetsfactory-lo:24.2-iterative-openpyxl315-v1
ENV MAX_CONCURRENCY=2
USER root
ENTRYPOINT []
WORKDIR /app
COPY input.xlsx /app/input.xlsx
COPY resource_runner.py runtime_profile.json /opt/sheetsfactory/
COPY --chmod=755 recalculate /usr/local/bin/recalculate
RUN --network=none chmod 0755 /usr/local/bin/recalculate
