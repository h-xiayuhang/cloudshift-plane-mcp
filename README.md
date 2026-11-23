# CloudShift Plane MCP

面向 [Plane](https://plane.so) 的 [Model Context Protocol](https://modelcontextprotocol.io) 服务，支持**自建 Plane 社区版（CE）**，通过**纯 API Key 的 HTTP 方式**连接，并提供**确定性的团队报告**（日报、个人、项目、模块、迭代、工作区）。

本项目基于官方 [`makeplane/plane-mcp-server`](https://github.com/makeplane/plane-mcp-server)（MIT）构建，保留上游全部工具，并增加：

- **每人一个 Key。** HTTP 模式下每个请求使用调用者自己的 Plane API Key（`Authorization: Bearer <key>` 或 `x-api-key`），服务端不保存任何 Key，调用者只能看到自己的 Key 有权限访问的数据。
- **每次调用指定 workspace。** 所有工具都带必填参数 `workspace_slug`，同一个 Key 可以在多个 workspace 之间切换，不需要在服务端或连接配置里写死 workspace。
- **只读标注。** 上游工具没有只读标注，本项目按工具名前缀（`list_` / `retrieve_` / `get_` / `search_` / `resolve_`）和全部报告工具补上 `readOnlyHint`，便于调用方区分只读与写操作。
- **Plane CE 兼容。** 报告使用旧版 CE 提供的 `/issues/` 接口，并对自建 Plane 反向代理后常见的 429/502/503 做重试和退避。
- **纯 API Key 的 HTTP 模式。** 设置 `PLANE_MCP_DISABLE_OAUTH=true` 即可，不需要配置 Plane 的 OAuth 应用。
- **团队报告。** 7 个 `cloudshift_plane_*` 工具在代码中计算进度、阻塞、逾期、即将到期、陈旧、未分配的数量，而不是由模型计算，因此数字可复现。
- **读取 `.env`。** 启动时自动读取当前工作目录（或其上级目录）的 `.env`，系统环境变量优先。

> 本项目与 Plane Software, Inc. 无关联，也未获其认可。"Plane" 是其所有者的商标。

## 目录

- [快速开始](#快速开始)
- [部署方式](#部署方式)
- [连接客户端](#连接客户端)
- [配置](#配置)
- [工具](#工具)
- [开发](#开发)
- [文档](#文档)
- [许可证与致谢](#许可证与致谢)

## 快速开始

**前置条件：** 一个可访问的 Plane 实例，以及 Plane 个人 API Token（Plane → 个人设置 → API 令牌）。

以下是最短路径：用 Docker 在本机跑起来并验证（本地运行和 systemd 见[部署方式](#部署方式)）。

```bash
git clone https://github.com/h-xiayuhang/cloudshift-plane-mcp.git
cd cloudshift-plane-mcp
cp .env.example .env      # 至少修改 PLANE_BASE_URL
docker build -t cloudshift-plane-mcp .
docker run -d --name plane-mcp --env-file .env \
  -p 127.0.0.1:8211:8211 --read-only --tmpfs /tmp cloudshift-plane-mcp
```

验证服务可用（`tools/list` 返回 200 表示服务正常且 Key 有效；Key 无效返回 401）：

```bash
curl -s -X POST http://127.0.0.1:8211/http/api-key/mcp \
  -H "Authorization: Bearer <你的Plane-API-Key>" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | head -c 300
```

> 用浏览器直接打开这个地址会看到 `405`，这是正常的：MCP 请求只接受 `POST`。

## 部署方式

所有方式都通过环境变量或 `.env` 配置。HTTP 模式下，**服务端不需要配置任何 Plane Key 或 workspace**，最少只需要：

```bash
PLANE_BASE_URL=https://plane.example.com   # 你的 Plane 地址，不带 /api
PLANE_MCP_DISABLE_OAUTH=true               # 只提供 API Key 路由，不需要 OAuth 应用
```

| 方式 | 适用场景 | 说明 |
|---|---|---|
| [Docker](#方式一docker) | 有容器环境，希望隔离、易迁移 | 非 root、只读文件系统、带健康检查 |
| [本地运行](#方式二本地运行不使用-docker) | 本机开发、测试，或没有 Docker 的服务器 | 只需 Python 和 uv |
| [systemd](#方式三systemd长期运行) | Linux 服务器长期运行 | 开机自启、崩溃重启 |
| [部署脚本](#方式四部署脚本) | 服务器上拉取新版本、重启并做健康检查 | `deploy/deploy.sh` |
| [反向代理（TLS）](#反向代理与-tls) | 跨机器访问 | Key 在请求头里传输，**跨机器请务必使用 HTTPS** |

### 方式一：Docker

镜像基于 `python:3.11-slim`，以非 root 用户 `mcp` 运行，默认监听容器内 `0.0.0.0:8211`，内置健康检查。`.env` 不会被打进镜像，通过 `--env-file` 在运行时注入。

**Docker Compose（推荐）：**

```bash
cp .env.example .env      # 按需修改
docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml logs -f
```

默认只发布到宿主机的 `127.0.0.1:8211`。需要让其他机器访问时，在前面放一个 TLS 反向代理（见[反向代理与 TLS](#反向代理与-tls)），不要直接改成对外开放明文端口。

**单独使用 Docker：**

```bash
docker build -t cloudshift-plane-mcp .
docker run -d --name plane-mcp --restart unless-stopped \
  --env-file .env \
  -p 127.0.0.1:8211:8211 \
  --read-only --tmpfs /tmp \
  cloudshift-plane-mcp
```

常用操作：

```bash
docker ps --filter name=plane-mcp        # 状态应为 healthy
docker logs -f plane-mcp                 # 查看日志
docker restart plane-mcp                 # 修改 .env 后需要重启（或重建容器）才会生效
```

> **Windows 的 Git Bash：** `--tmpfs /tmp` 会被误转换成 Windows 路径，导致 `invalid mount path`。命令前加 `MSYS_NO_PATHCONV=1`，或改用 PowerShell。

如果 Plane 与本服务在同一台宿主机上，容器内访问宿主机请用 `host.docker.internal`（Docker Desktop）或宿主机的内网 IP，不要写 `127.0.0.1`，那指向容器自己。

### 方式二：本地运行（不使用 Docker）

**前置条件：** Python 3.10+ 和 [uv](https://docs.astral.sh/uv/)。

```bash
git clone https://github.com/h-xiayuhang/cloudshift-plane-mcp.git
cd cloudshift-plane-mcp
uv sync                   # 安装依赖，创建 .venv
cp .env.example .env      # 按需修改
uv run plane-mcp-server http
```

看到 `Starting HTTP server on 0.0.0.0:8211` 即启动成功。

要点：

- **`.env` 从当前工作目录（及其上级目录）读取**，不是从代码所在目录读取。请在放有 `.env` 的目录里启动；已经设置的系统环境变量优先于 `.env`。
- 只想本机访问时，在 `.env` 里设置 `MCP_HOST=127.0.0.1`。
- 换端口用 `MCP_PORT`；命令行不支持 `--host` / `--port`。
- 不用 `.env` 时，也可以直接设置环境变量：

  ```powershell
  # Windows PowerShell
  $env:PLANE_BASE_URL="https://plane.example.com"
  $env:PLANE_MCP_DISABLE_OAUTH="true"
  uv run plane-mcp-server http
  ```

  ```bash
  # Linux / macOS / Git Bash
  PLANE_BASE_URL=https://plane.example.com PLANE_MCP_DISABLE_OAUTH=true uv run plane-mcp-server http
  ```

**stdio 模式**（给 Cursor、Claude Desktop 等本机客户端，由客户端启动进程）：

```bash
uv run plane-mcp-server stdio
```

stdio 没有"每个请求一个 Key"的概念，所以必须通过环境变量提供 `PLANE_API_KEY` 和 `PLANE_WORKSPACE_SLUG`，配置示例见[连接客户端](#连接客户端)。

### 方式三：systemd（长期运行）

```bash
sudo useradd --system --create-home --home-dir /var/lib/plane-mcp --shell /usr/sbin/nologin plane-mcp
sudo install -d -o plane-mcp -g plane-mcp /opt/cloudshift-plane-mcp
sudo -u plane-mcp git clone https://github.com/h-xiayuhang/cloudshift-plane-mcp.git /opt/cloudshift-plane-mcp
cd /opt/cloudshift-plane-mcp
sudo -u plane-mcp -H bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
sudo -u plane-mcp -H /var/lib/plane-mcp/.local/bin/uv sync --frozen --no-dev
sudo -u plane-mcp cp .env.example .env && sudo -u plane-mcp chmod 600 .env   # 然后编辑 .env

sudo cp deploy/systemd/plane-mcp.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now plane-mcp
journalctl -u plane-mcp -f
```

单元文件假定安装在 `/opt/cloudshift-plane-mcp`，运行用户为 `plane-mcp`。`WorkingDirectory` 必须是放有 `.env` 的目录；需要调整路径或用户时用 `sudo systemctl edit plane-mcp`。

### 方式四：部署脚本

`deploy/deploy.sh` 用于已经按方式三部署、之后需要更新版本的服务器：拉取代码（`git pull --ff-only`）、以应用用户身份执行 `uv sync --frozen --no-dev`、重启 systemd 服务（没有 unit 时用 `nohup` 启动）、最后做健康检查。

```bash
deploy/deploy.sh
# 或：APP_DIR=/opt/cloudshift-plane-mcp SERVICE_NAME=plane-mcp sudo -E deploy/deploy.sh
```

脚本只检查服务是否启动：不带凭据请求 `/http/api-key/mcp`，返回 `401` 即视为健康（服务端不持有任何 Plane Key，无法替你验证 Key）。要验证真实 Key，用[快速开始](#快速开始)里带 `Authorization` 的 `curl`。

### 反向代理与 TLS

用户的 Plane Key 放在请求头里，**跨机器访问时必须使用 HTTPS**，否则 Key 会以明文在网络中传输。

- 让服务只监听本机（`MCP_HOST=127.0.0.1`，或 Compose 的端口绑定），由代理终止 TLS。
- [`deploy/caddy/Caddyfile.example`](deploy/caddy/Caddyfile.example) 是已开启流式传输的 Caddy 配置。
- nginx 需要关闭缓冲：

  ```nginx
  location / {
      proxy_pass http://127.0.0.1:8211;
      proxy_http_version 1.1;
      proxy_buffering off;
      proxy_read_timeout 300s;
      proxy_set_header Host $host;
      proxy_set_header X-Forwarded-Proto $scheme;
  }
  ```

- 部署在子路径（如 `/plane/`）时，设置 `MCP_PATH_PREFIX=/plane`，代理时原样转发该路径。

### 上线检查清单

- [ ] 跨机器访问走 HTTPS，8211 端口没有对公网开放；防火墙只对需要的客户端开放。
- [ ] `PLANE_MCP_ALLOW_URL_ONLY_AUTH` 保持 `false`（默认）。开启后，任何能访问 `/http/api-key/w/<slug>/mcp` 的人都会以服务端的 `PLANE_API_KEY` 身份操作。
- [ ] **不要在服务端配置 `PLANE_API_KEY`。** 它只用于 stdio 和 URL-only 认证；配置后，在 Plane 暂时不可用时，带有相同 Key 的请求会被放行。
- [ ] `.env` 只有服务用户可读（`chmod 600`），并且没有被提交到仓库。
- [ ] `LOG_USER_INFO` 保持 `false`，除非确实需要在日志里记录显示名。

## 连接客户端

### HTTP（每人一个 Key）

客户端请求地址为 `/http/api-key/mcp`，请求头带用户自己的 Key。**不需要**再传 workspace：workspace 由每次工具调用的 `workspace_slug` 参数决定。

```json
{
  "mcpServers": {
    "plane": {
      "url": "https://mcp.example.com/http/api-key/mcp",
      "headers": {
        "Authorization": "Bearer <你的Plane-API-Key>"
      }
    }
  }
}
```

`workspace_slug` 是 Plane 链接第一段路径，例如 `https://plane.example.com/acme/browse/PROJ-1/` 中的 `acme`。模型可以从你在对话中贴出的 Plane 链接里取得它，也可以直接告诉模型。

### stdio（本机单用户）

stdio 无法区分请求，所以仍然需要在客户端配置里提供 Key 和默认 workspace：

```json
{
  "mcpServers": {
    "plane": {
      "command": "uv",
      "args": ["--directory", "/path/to/cloudshift-plane-mcp", "run", "plane-mcp-server", "stdio"],
      "env": {
        "PLANE_BASE_URL": "https://plane.example.com",
        "PLANE_API_KEY": "<你的Plane-API-Key>",
        "PLANE_WORKSPACE_SLUG": "<你的workspace>"
      }
    }
  }
}
```

> stdio 与 HTTP 在 `workspace_slug` 上的行为不同：HTTP 模式的中间件要求每次调用必填 `workspace_slug`；stdio 模式没有注册这个中间件，仍使用环境变量里的 workspace。

Cursor、VS Code、Claude Code、Claude Desktop、Claude.ai 的具体配置见 [docs/clients.md](docs/clients.md)。该文档目前仍是英文，并且其中的 `x-workspace-slug` 请求头、`PLANE_API_KEY` 示例对应的是旧的"一个服务一个 workspace"用法，使用前请先对照本节。

## 配置

所有设置都是环境变量，也可以写在 `.env` 里（模板见 [`.env.example`](.env.example)）。

| 变量 | 是否必填 | 说明 |
|---|---|---|
| `PLANE_BASE_URL` | 是 | Plane 地址，不带 `/api`（默认 `https://api.plane.so`） |
| `PLANE_MCP_DISABLE_OAUTH` | HTTP 模式推荐设为 `true` | 只提供 API Key 路由，不需要 OAuth 应用 |
| `MCP_HOST` / `MCP_PORT` | 否 | HTTP 监听地址（默认 `0.0.0.0:8211`） |
| `MCP_PATH_PREFIX` | 否 | 所有路由的前缀，用于子路径反向代理 |
| `PLANE_API_KEY` | 仅 stdio / URL-only 认证 | **HTTP 每人一个 Key 的用法下不要配置**（见上线检查清单） |
| `PLANE_WORKSPACE_SLUG` | 仅 stdio | HTTP 模式下由每次调用的 `workspace_slug` 决定 |
| `PLANE_INTERNAL_BASE_URL` | 否 | 服务端访问 Plane 的内部地址（如内网域名），默认等于 `PLANE_BASE_URL` |
| `PLANE_MCP_ALLOW_URL_ONLY_AUTH` | 否 | 默认 `false`，开启前请阅读[配置文档中的警告](docs/configuration.md#url-only-auth) |
| `CLOUDSHIFT_TIMEZONE` | 否 | 报告日期使用的 IANA 时区（默认 `UTC`） |
| `LOG_USER_INFO` | 否 | `true` 时日志包含显示名（个人信息），默认 `false` |

完整的变量说明（含 OAuth、Redis、报告阈值）见 [docs/configuration.md](docs/configuration.md)（英文）。

**存储：** API Key 模式下服务**不创建任何数据库，也不写文件**，每个请求用请求头里的 Key 现场向 Plane 校验，用完即丢。只有启用 OAuth 时才会缓存令牌（内存，或配置 `REDIS_HOST` 后用 Redis）。

## 工具

共 **184 个工具**：

| 分组 | 数量 | 示例 |
|---|---:|---|
| 工作项、评论、链接、关系、活动、附件、工时 | 40 | `list_work_items`、`retrieve_work_item_by_identifier`、`create_work_item`、`search_work_items` |
| 项目、成员、估算 | 18 | `list_projects`、`get_project_members` |
| 迭代、模块、里程碑 | 25 | `list_cycles`、`list_module_work_items`、`transfer_cycle_work_items` |
| 状态、标签、类型、自定义属性 | 31 | `list_states`、`resolve_work_item_type` |
| 工作区、用户、页面、PQL | 11 | `get_workspace_members`、`get_pql_reference` |
| 迭代计划、收件箱、发布、客户、角色 | 52 | 多为 Plane 商业版 / 云版功能 |
| **CloudShift 报告与诊断** | 7 | `cloudshift_plane_daily_report`、`cloudshift_plane_workspace_report` |

HTTP 模式下，每个工具都带必填参数 `workspace_slug`。

**报告工具**读取的是**调用者自己的 Key** 和本次调用的 `workspace_slug`，调用者只能看到自己权限范围内的数据；所有数字由代码计算。报告全部只读。详情见 [docs/reports.md](docs/reports.md)。

完整列表见 [docs/tools.md](docs/tools.md)。

在自建社区版上，部分上游工具会返回 404：对应接口是商业版专有，或旧版 CE 没有（页面最常见）。详见 [docs/self-hosted-ce.md](docs/self-hosted-ce.md)。其中 `list_projects` 调用的是较新的 `projects-lite` 接口，**是否可用取决于你的 Plane 版本**；不可用时，可以用 `cloudshift_plane_capability_report` 查看实例支持情况，或改用报告工具。

## 开发

```bash
uv sync --extra dev
uv run pytest                        # 单元测试；没有真实凭据时，联调测试会跳过
uv run ruff check .
uv run ruff format .
```

对真实 Plane 做联调测试：把 `.env.test` 复制为 `.env.test.local`，填好后运行 `pytest tests/test_integration.py`。代码结构和请求流程见 [docs/architecture.md](docs/architecture.md)。欢迎贡献，见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 文档

以下文档为英文，其中部分内容尚未与"每人一个 Key、每次调用指定 workspace"的现状完全同步，以本 README 为准：

| 文档 | 内容 |
|---|---|
| [docs/configuration.md](docs/configuration.md) | 全部环境变量 |
| [docs/clients.md](docs/clients.md) | Cursor、Claude Desktop、Claude.ai、VS Code 的配置 |
| [docs/tools.md](docs/tools.md) | 全部 184 个工具 |
| [docs/reports.md](docs/reports.md) | 报告工具、指标定义、错误码 |
| [docs/self-hosted-ce.md](docs/self-hosted-ce.md) | 社区版兼容性与排错 |
| [docs/deployment.md](docs/deployment.md) | Docker、systemd、反向代理、加固 |
| [docs/architecture.md](docs/architecture.md) | 代码结构与请求流程 |

## 许可证与致谢

[MIT](LICENSE)。基于 Plane MCP Server 贡献者的 [makeplane/plane-mcp-server](https://github.com/makeplane/plane-mcp-server)，保留其版权声明。CloudShift 的新增内容主要在 [`cloudshift/`](cloudshift)、[`plane_mcp/claude_workspace.py`](plane_mcp/claude_workspace.py)、[`plane_mcp/middleware.py`](plane_mcp/middleware.py) 和 header 认证提供者中。
