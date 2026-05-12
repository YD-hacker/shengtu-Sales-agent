import os
import yaml

# ---------- 基础路径配置（通过环境变量覆盖，默认 /opt/ai-agent） ----------
BASE_DIR = os.getenv("AGENT_BASE_DIR", "/opt/ai-agent")

# ---------- 日志配置 ----------
LOG_DIR = os.path.join(BASE_DIR, "data", "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# ---------- 数据目录 ----------
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# ---------- 文件仓库 ----------
FILE_REPO_DIR = os.path.join(BASE_DIR, "file_repo")

# ---------- 配置文件路径 ----------
CONFIG_DIR = os.path.join(BASE_DIR, "config")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.yaml")
KB_FILE = os.path.join(CONFIG_DIR, "knowledge_base.yaml")
WAKE_CFG_FILE = os.path.join(CONFIG_DIR, "wake_up_config.yaml")
TRIAL_CFG_FILE = os.path.join(CONFIG_DIR, "trial_follow_up_config.yaml")
REPORT_TEMPLATE_FILE = os.path.join(CONFIG_DIR, "report_template.yaml")

# ---------- 知识库加载 ----------
with open(KB_FILE, encoding="utf-8") as _f:
    KB = yaml.safe_load(_f)["scripts"]

# ---------- 数据文件路径 ----------
STATE_FILE = os.path.join(DATA_DIR, "user_state.json")
LAST_ACTIVE_FILE = os.path.join(DATA_DIR, "last_active.json")
WAKE_LOG_FILE = os.path.join(DATA_DIR, "wake_log.json")
