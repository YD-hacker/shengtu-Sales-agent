"""pytest 配置文件 — 加载环境变量 + 通用fixture"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# 加载 .env 文件中的环境变量
try:
    from dotenv import load_dotenv
    # 尝试多个路径
    for env_path in [
        os.path.join(os.path.dirname(__file__), "..", ".env"),
        "/opt/ai-agent/.env",
    ]:
        if os.path.exists(env_path):
            load_dotenv(env_path)
            break
except ImportError:
    pass
