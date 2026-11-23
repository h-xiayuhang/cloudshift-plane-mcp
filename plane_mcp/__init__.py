"""Plane MCP Server - A Model Context Protocol server for Plane integration."""

from dotenv import find_dotenv, load_dotenv

# 先于任何子模块读取环境变量：从当前工作目录向上查找 .env（systemd 要设置 WorkingDirectory）。
# 已存在的系统环境变量优先，不被覆盖。
load_dotenv(find_dotenv(usecwd=True))
