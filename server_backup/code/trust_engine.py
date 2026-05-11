"""信任计算引擎 - 企业级交付版

核心思路:
- 初始信任 50（满分100）
- 信任低于阈值时，禁止进入 show_fee 及以后的状态
- 信任随时间自然衰减（每天-2），但每次有效互动恢复
- 信任变化有日志记录，便于复盘
- 信任修复话术从KB配置读取

门禁:
  trust < 30: 只能在 icebreak/qualify 徘徊
  trust < 50: 可以到 match_campus，不能 show_fee
  trust >= 50: 可以 show_fee/invite
  trust >= 70: 可以进入 report_info/completed
"""
import yaml
from loguru import logger
from code import KB_FILE

# 加载KB
try:
    with open(KB_FILE, encoding="utf-8") as f:
        KB = yaml.safe_load(f)["scripts"]
except Exception:
    KB = {}

# ---- 信任阈值 ----
TRUST_THRESHOLD_QUALIFY = 30
TRUST_THRESHOLD_SHOW_FEE = 50
TRUST_THRESHOLD_REPORT = 70
TRUST_INITIAL = 50
TRUST_MAX = 100
TRUST_MIN = 0

# ---- 每日衰减量 ----
TRUST_DAILY_DECAY = 2


def init_trust(state):
    """初始化信任字段"""
    if "trust_level" not in state:
        state["trust_level"] = TRUST_INITIAL
    if "trust_log" not in state:
        state["trust_log"] = []
    if "daily_positive_total" not in state:
        state["daily_positive_total"] = 0
    if "last_positive_date" not in state:
        state["last_positive_date"] = ""
    return state


def adjust_trust(state, action: str, reason: str = "") -> int:
    """
    调整信任值
    防刷机制: 每日加分上限 20 分
    """
    from code.time_utils import get_beijing_time

    trust_score_map = {
        "empathy_confirm": 2,
        "disclose_risk": 5,
        "provide_value": 3,
        "user_shares_info": 5,
        "user_confirms": 2,
        "irrelevant_reply": -5,
        "pushy_sales": -5,
        "ignore_emotion": -3,
        "repeated_question": -2,
    }

    delta = trust_score_map.get(action, 0)
    old = state.get("trust_level", TRUST_INITIAL)

    DAILY_POSITIVE_CAP = 20
    if delta > 0:
        today = get_beijing_time().strftime("%Y-%m-%d")
        last_date = state.get("last_positive_date", "")
        if last_date != today:
            state["daily_positive_total"] = 0
            state["last_positive_date"] = today
        current_positive = state.get("daily_positive_total", 0)
        if current_positive >= DAILY_POSITIVE_CAP:
            logger.info(f"信任加分达上限({DAILY_POSITIVE_CAP})，跳过: {action}")
            return old
        remaining = DAILY_POSITIVE_CAP - current_positive
        if delta > remaining:
            delta = remaining
        state["daily_positive_total"] = current_positive + delta

    new = max(TRUST_MIN, min(TRUST_MAX, old + delta))
    state["trust_level"] = new

    log_entry = {
        "time": get_beijing_time().isoformat(),
        "action": action,
        "delta": delta,
        "old": old,
        "new": new,
        "reason": reason
    }
    trust_log = state.get("trust_log", [])
    trust_log.append(log_entry)
    state["trust_log"] = trust_log[-20:]

    if delta != 0:
        logger.info(f"信任变化: {action} -> {delta:+d} ({old}->{new}) {reason}")

    return new


def can_advance_to(state, target_node: str) -> bool:
    """检查信任值是否允许进入目标状态"""
    trust = state.get("trust_level", TRUST_INITIAL)

    if target_node in ("icebreak", "qualify"):
        return trust >= TRUST_THRESHOLD_QUALIFY
    elif target_node in ("match_campus", "reject_qualify"):
        return trust >= TRUST_THRESHOLD_QUALIFY
    elif target_node in ("show_fee", "invite"):
        return trust >= TRUST_THRESHOLD_SHOW_FEE
    elif target_node in ("report_info", "completed"):
        return trust >= TRUST_THRESHOLD_REPORT

    return True


def get_trust_gate_message(state, target_node: str) -> str:
    """
    信任不足时，返回建信任的话术
    话术从KB读取
    """
    trust = state.get("trust_level", TRUST_INITIAL)

    if target_node in ("show_fee", "invite") and trust < TRUST_THRESHOLD_SHOW_FEE:
        # 从KB读取
        msg = KB.get("trust_repair_show_fee",
            "不跟你扯虚的，这个班不是所有人都适合——我先帮你看看条件过不过关，再聊后面的事，行吧？")
        if isinstance(msg, list):
            msg = msg[0]
        return msg

    if target_node in ("report_info", "completed") and trust < TRUST_THRESHOLD_REPORT:
        msg = KB.get("trust_repair_report",
            "咱聊到这一步了，我再多说一句：过来试听一天，住宿我安排，你亲眼看了再决定，比我在这里说一百句都强。")
        if isinstance(msg, list):
            msg = msg[0]
        return msg

    return ""


def apply_daily_decay(state):
    """每日信任衰减"""
    from code.time_utils import get_beijing_time

    last_decay = state.get("last_trust_decay_date", "")
    today = get_beijing_time().strftime("%Y-%m-%d")

    if last_decay == today:
        return state

    old = state.get("trust_level", TRUST_INITIAL)
    new = max(TRUST_MIN, old - TRUST_DAILY_DECAY)
    state["trust_level"] = new
    state["last_trust_decay_date"] = today

    logger.info(f"信任日衰减: {old}->{new}")
    return state
