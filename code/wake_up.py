"""唤醒策略 - 修复版

主要修复:
1. 使用原子写入保存 wake_log
2. 修复双重 load_state 调用
3. 使用动态路径
4. 唤醒后标记用户状态
"""
import yaml
import json
import os
from datetime import datetime, timedelta
from code.memory_manager import load_state, save_state, atomic_save
from code.time_utils import get_beijing_time
from loguru import logger
from code import WAKE_CFG_FILE, WAKE_LOG_FILE

with open(WAKE_CFG_FILE, encoding="utf-8") as f:
    WAKE_CFG = yaml.safe_load(f)["wake_up"]

WAKE_LOG = {}


def load_wake_log():
    global WAKE_LOG
    if os.path.exists(WAKE_LOG_FILE):
        try:
            with open(WAKE_LOG_FILE, "r", encoding="utf-8") as f:
                WAKE_LOG = json.load(f)
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"唤醒日志读取失败: {e}")
            WAKE_LOG = {}


def save_wake_log():
    """修复: 使用原子写入"""
    atomic_save(WAKE_LOG_FILE, WAKE_LOG)


load_wake_log()


def get_wake_count(user_id):
    return WAKE_LOG.get(user_id, {}).get("count", 0)


def can_wake(user_id, interval):
    """检查是否满足唤醒间隔"""
    log = WAKE_LOG.get(user_id, {"count": 0, "last_wake": ""})
    if log.get("last_wake"):
        try:
            last = datetime.fromisoformat(log["last_wake"])
            if (get_beijing_time() - last) < timedelta(days=interval):
                return False
        except Exception as e:
            logger.warning(f"唤醒时间解析失败: {e}")
    return True


def record_wake(user_id):
    """记录唤醒"""
    log = WAKE_LOG.get(user_id, {"count": 0, "last_wake": ""})
    log["count"] = log.get("count", 0) + 1
    log["last_wake"] = get_beijing_time().isoformat()
    WAKE_LOG[user_id] = log
    save_wake_log()


async def wake_up_user(user_id):
    """唤醒用户"""
    if not WAKE_CFG.get("enabled", False):
        return None

    st = load_state(user_id)

    if st.get("send_failure", False):
        return None

    if st.get("rejected", False):
        if not can_wake(user_id, WAKE_CFG["reject_weekly_interval"]):
            return None
    else:
        count = get_wake_count(user_id)
        if count < WAKE_CFG["phase_threshold"]:
            interval = WAKE_CFG["min_interval_days_first_phase"]
        else:
            interval = WAKE_CFG["min_interval_days_later_phase"]
        if not can_wake(user_id, interval):
            return None

    # UP-115: 幂等性检查 - 如果用户最近有对话活动，跳过唤醒
    from code.memory_manager import LAST_ACTIVE
    last_active_str = LAST_ACTIVE.get(user_id, "")
    if last_active_str:
        try:
            last_active = datetime.fromisoformat(last_active_str)
            if (get_beijing_time() - last_active).total_seconds() < 3600:
                logger.info(f"[{user_id}] 唤醒跳过：用户最近1小时内有活动")
                return None
        except Exception:
            pass

    node = st.get("current_node", "default")
    templates = WAKE_CFG.get("templates", {})
    template = templates.get(node, templates.get("default", ""))

    record_wake(user_id)
    logger.info(f"唤醒用户 {user_id}: {template[:50]}")
    return template
