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
from datetime import datetime
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
    防刷机制: 每日加分上限 15 分，单动作类型每日上限 10 分
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

    DAILY_POSITIVE_CAP = 15
    PER_ACTION_CAP = 10  # 单动作类型每日上限
    if delta > 0:
        today = get_beijing_time().strftime("%Y-%m-%d")
        last_date = state.get("last_positive_date", "")
        if last_date != today:
            state["daily_positive_total"] = 0
            state["_daily_action_totals"] = {}
            state["last_positive_date"] = today
        current_positive = state.get("daily_positive_total", 0)

        # 单动作类型防刷检查
        action_totals = state.get("_daily_action_totals", {})
        action_total = action_totals.get(action, 0)
        if action_total >= PER_ACTION_CAP:
            logger.info(f"信任单动作加分达上限({PER_ACTION_CAP}): {action}")
            return old
        if current_positive >= DAILY_POSITIVE_CAP:
            logger.info(f"信任加分达上限({DAILY_POSITIVE_CAP})，跳过: {action}")
            return old
        remaining = DAILY_POSITIVE_CAP - current_positive
        if delta > remaining:
            delta = remaining
        state["daily_positive_total"] = current_positive + delta
        # 更新单动作计数
        action_totals[action] = action_totals.get(action, 0) + delta
        state["_daily_action_totals"] = action_totals

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
    """检查信任值是否允许进入目标状态

    P1优化: 增加24小时通过缓存（hysteresis），防止信任值在阈值附近波动导致体验断崖
    - 如果用户在最近24小时内曾通过某个门禁，即使当前信任值略低于阈值也允许通过
    - 缓存阈值：低于阈值5分以内时，24小时内仍可通行
    """
    trust = state.get("trust_level", TRUST_INITIAL)
    HYSTERESIS_GRACE = 5  # 24小时内的宽限分数

    # 确定目标阈值
    if target_node in ("icebreak", "qualify", "match_campus", "reject_qualify"):
        threshold = TRUST_THRESHOLD_QUALIFY
    elif target_node in ("show_fee", "invite"):
        threshold = TRUST_THRESHOLD_SHOW_FEE
    elif target_node in ("report_info", "completed"):
        threshold = TRUST_THRESHOLD_REPORT
    else:
        return True

    # 直接通过
    if trust >= threshold:
        # 记录通过时间到缓存
        _record_gate_pass(state, target_node)
        return True

    # P1: hysteresis检查 - 24小时内曾通过且当前差距在宽限范围内
    if trust >= threshold - HYSTERESIS_GRACE:
        if _check_recent_gate_pass(state, target_node, hours=24):
            logger.info(f"信任门禁hysteresis: trust={trust} 略低于阈值{threshold}，但24小时内曾通过，允许通行")
            return True

    return False


def _record_gate_pass(state, target_node: str):
    """记录门禁通过时间"""
    from code.time_utils import get_beijing_time
    gate_cache = state.get("_trust_gate_cache", {})
    gate_cache[target_node] = get_beijing_time().isoformat()
    # 只保留最近10条
    if len(gate_cache) > 10:
        oldest_keys = sorted(gate_cache.keys(), key=lambda k: gate_cache[k])[:len(gate_cache) - 10]
        for k in oldest_keys:
            del gate_cache[k]
    state["_trust_gate_cache"] = gate_cache


def _check_recent_gate_pass(state, target_node: str, hours: int = 24) -> bool:
    """检查最近N小时内是否曾通过指定门禁"""
    from code.time_utils import get_beijing_time
    gate_cache = state.get("_trust_gate_cache", {})
    pass_time_str = gate_cache.get(target_node)
    if not pass_time_str:
        return False
    try:
        pass_time = datetime.fromisoformat(pass_time_str)
        if pass_time.tzinfo is None:
            from code.time_utils import BEIJING_TZ
            pass_time = pass_time.replace(tzinfo=BEIJING_TZ)
        elapsed = (get_beijing_time() - pass_time).total_seconds()
        return elapsed < hours * 3600
    except Exception:
        return False


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


def handle_silent_return(state, days_threshold=14):
    """沉默用户回归信任重置

    P1优化: 沉默超14天后用户主动回归，信任重置为 min(50, decayed_value)
    主动回归 = 有兴趣，不应被过低的信任值阻拦
    """
    from code.time_utils import get_beijing_time

    last_active = state.get("_last_active", "")
    if not last_active:
        return state

    try:
        last_time = datetime.fromisoformat(last_active)
        if last_time.tzinfo is None:
            from code.time_utils import BEIJING_TZ
            last_time = last_time.replace(tzinfo=BEIJING_TZ)
        days_silent = (get_beijing_time() - last_time).days

        if days_silent >= days_threshold:
            old_trust = state.get("trust_level", TRUST_INITIAL)
            # 回归用户信任重置：取当前值和50的较大值
            new_trust = max(old_trust, TRUST_INITIAL)
            if new_trust != old_trust:
                state["trust_level"] = new_trust
                logger.info(f"沉默用户回归信任重置: {old_trust}->{new_trust} (沉默{days_silent}天)")
    except Exception:
        pass

    return state
