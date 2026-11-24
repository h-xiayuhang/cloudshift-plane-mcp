#!/usr/bin/env bash
# 构建（并推送）镜像到 registry.voyah.cn/docker.io/bot-lite/plane-mcp。
# 用法：./build.sh                 构建并推送
#       NO_PUSH=1 ./build.sh       只构建不推送
# 推送需登录：HARBOR_USER / HARBOR_PASSWD 环境变量（可写在 .env），不设则沿用已有登录态。
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] && { set -a; . ./.env; set +a; }
# 兼容 HARBORUSER/HARBORPASSWD 的写法
HARBOR_USER=${HARBOR_USER:-${HARBORUSER:-}}; HARBOR_PASSWD=${HARBOR_PASSWD:-${HARBORPASSWD:-}}

IMAGE=${IMAGE:-registry.voyah.cn/docker.io/bot-lite/plane-mcp}

# 容器 CLI：优先 docker，未安装则回退到 nerdctl
if command -v docker &>/dev/null; then DOCKER=(docker)
elif command -v nerdctl &>/dev/null; then DOCKER=(sudo nerdctl)
else echo "错误：未找到 docker 或 nerdctl" >&2; exit 1; fi

git rev-parse --is-inside-work-tree &>/dev/null || { echo "错误：当前目录不是 Git 仓库" >&2; exit 1; }
TAG="$(git rev-parse --short=6 HEAD)-$(date +%Y%m%d%H%M)"

if [ -z "${NO_PUSH:-}" ] && [ -n "${HARBOR_USER:-}" ]; then
  echo "登录 ${IMAGE%%/*} ..."
  printf '%s' "${HARBOR_PASSWD:?设置了 HARBOR_USER 还需要 HARBOR_PASSWD}" \
    | "${DOCKER[@]}" login "${IMAGE%%/*}" -u "$HARBOR_USER" --password-stdin
fi

BASE_IMAGE="$IMAGE:${BASE_TAG:-base}"
# 基础镜像不在本地/仓库时提示先跑 build-base.sh
"${DOCKER[@]}" image inspect "$BASE_IMAGE" &>/dev/null || "${DOCKER[@]}" pull "$BASE_IMAGE" || { echo "错误：基础镜像不存在，请先执行 ./build-base.sh" >&2; exit 1; }

echo "==> 构建 $IMAGE:$TAG"
"${DOCKER[@]}" build --build-arg "BASE_IMAGE=$BASE_IMAGE" -t "$IMAGE:$TAG" -t "$IMAGE:latest" .
if [ -z "${NO_PUSH:-}" ]; then
  "${DOCKER[@]}" push "$IMAGE:$TAG"
  "${DOCKER[@]}" push "$IMAGE:latest"
fi

echo "完成：$IMAGE tag=$TAG"
echo "部署：helm upgrade --install plane-mcp deploy/helm/plane-mcp --set image.tag=$TAG"
