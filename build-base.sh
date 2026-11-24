#!/usr/bin/env bash
# 构建（并推送）依赖基础镜像；依赖（pyproject.toml / uv.lock）变化时才需要重跑。
# 用法：./build-base.sh        NO_PUSH=1 ./build-base.sh 只构建
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] && { set -a; . ./.env; set +a; }
# 兼容 HARBORUSER/HARBORPASSWD 的写法
HARBOR_USER=${HARBOR_USER:-${HARBORUSER:-}}; HARBOR_PASSWD=${HARBOR_PASSWD:-${HARBORPASSWD:-}}

IMAGE=${IMAGE:-registry.voyah.cn/docker.io/bot-lite/plane-mcp}
BASE_TAG=${BASE_TAG:-base}
PYTHON_BASE=${PYTHON_BASE:-registry.voyah.cn/docker.io/python:3.11.13-slim}

if command -v docker &>/dev/null; then DOCKER=(docker)
elif command -v nerdctl &>/dev/null; then DOCKER=(sudo nerdctl)
else echo "错误：未找到 docker 或 nerdctl" >&2; exit 1; fi

uv_path=$(command -v uv || true)
[ -n "$uv_path" ] || { echo "错误：构建机未找到 uv" >&2; exit 1; }
# 把构建机的 uv 放进构建上下文，结束后删除
cp "$uv_path" ./uv
trap 'rm -f ./uv' EXIT

if [ -z "${NO_PUSH:-}" ] && [ -n "${HARBOR_USER:-}" ]; then
  printf '%s' "${HARBOR_PASSWD:?设置了 HARBOR_USER 还需要 HARBOR_PASSWD}" \
    | "${DOCKER[@]}" login "${IMAGE%%/*}" -u "$HARBOR_USER" --password-stdin
fi

echo "==> 构建基础镜像 $IMAGE:$BASE_TAG"
"${DOCKER[@]}" build --build-arg "PYTHON_BASE=$PYTHON_BASE" -t "$IMAGE:$BASE_TAG" -f Dockerfile.base .
[ -n "${NO_PUSH:-}" ] || "${DOCKER[@]}" push "$IMAGE:$BASE_TAG"
echo "完成：$IMAGE:$BASE_TAG"
