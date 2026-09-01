FROM python:3.12-slim@sha256:7a8b475003c4fe15a2cd4e55e5cfc2f3560bdc9333d624f24cdd6d4340fd7a17
RUN groupadd --gid 10001 agent \
    && useradd --uid 10001 --gid 10001 --create-home --shell /bin/bash agent \
    && install -d -o agent -g agent -m 0755 /workspace \
    && install -d -o root -g root -m 0755 /opt/dealbench
COPY tools.json /opt/dealbench/
COPY tool /usr/local/bin/tool
RUN chmod 0755 /usr/local/bin/tool && chmod 0444 /opt/dealbench/tools.json
WORKDIR /workspace
ENV DEALBENCH_ROOT=/opt/dealbench PYTHONUNBUFFERED=1
CMD ["sh", "-c", "sleep infinity"]
