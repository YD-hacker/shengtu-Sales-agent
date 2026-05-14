"""Gunicorn 配置文件 - 生产部署

启动命令:
  gunicorn -c gunicorn_config.py app:app

或使用 start.sh:
  bash start.sh prod
"""
import os
import multiprocessing

# 服务器绑定
bind = "0.0.0.0:8080"
backlog = 512

# Worker 配置
workers = multiprocessing.cpu_count() * 2 + 1  # 推荐公式
workers = min(workers, 4)  # 单机最多4个worker，避免LLM并发过高
worker_class = "gthread"  # 使用线程worker（兼容Flask的同步代码）
threads = 2
worker_connections = 1000
timeout = 120  # LLM响应可能较慢
keepalive = 5
graceful_timeout = 30
max_requests = 1000  # 每个worker处理1000请求后重启（防内存泄漏）
max_requests_jitter = 50

# 日志
accesslog = "/opt/ai-agent/logs/access.log"
errorlog = "/opt/ai-agent/logs/error.log"
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s %(D)s'

# 进程命名
proc_name = "ai-agent"

# 预加载应用（节省内存，但不支持热更新worker）
preload_app = False

# Daemon 模式（生产环境用systemd管理，不用daemon）
daemon = False
pidfile = "/opt/ai-agent/ai-agent.pid"

# 临时目录
worker_tmp_dir = "/dev/shm" if os.path.exists("/dev/shm") else None
