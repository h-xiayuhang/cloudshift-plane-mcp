ARG BASE_IMAGE
FROM ${BASE_IMAGE}

# 依赖已预装在基础镜像中，日常构建只复制业务代码（PYTHONPATH=/app）。
COPY plane_mcp/ ./plane_mcp/
COPY cloudshift/ ./cloudshift/

RUN useradd --create-home --uid 10001 mcp
USER mcp

ENV MCP_HOST=0.0.0.0 \
    MCP_PORT=8211

EXPOSE 8211

# 仅 docker/compose 使用（K8s 用 tcpSocket 探针）；用 python 检测端口，免装 curl。
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,socket;socket.create_connection(('127.0.0.1',int(os.environ['MCP_PORT'])),3)" || exit 1

ENTRYPOINT ["python", "-m", "plane_mcp"]
CMD ["http"]
