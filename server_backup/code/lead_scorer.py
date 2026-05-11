"""线索评分引擎

根据用户画像、行为信号、意向强度计算线索分（0-100），支持S/A/B/C分级。
线索分与信任分并行运作：信任分反映对话互动质量，线索分反映商业价值。

评分维度：
  基础画像分（0-40）：学历、年龄、方向、城市
  行为信号分（0-30）：信息提供、主动询问、回复速度
  意向强度分（0-30）：明确意向词、紧迫感、确认行为
"""
from loguru import logger


# ---- 基础画像评分规则 ----
EDUCATION_SCORES = {
    "统招本科": 20,
    "本科": 18,
    "统招大专": 15,
    "大专": 13,
    "硕士": 22,
    "非统招本科": 8,
    "非统招大专": 6,
    "高中/中专": 2,
    "高中": 2,
    "中专": 2,
}

DIRECTION_SCORES = {
    "网安": 5,
    "大数据": 5,
}


def _score_education(state: dict) -> int:
    edu = state.get("education", "")
    if not edu:
        return 0
    for key, score in EDUCATION_SCORES.items():
        if key in edu:
            return score
    return 3


def _score_age(state: dict) -> int:
    try:
        age = int(state.get("age", 0))
    except (ValueError, TypeError):
        return 0
    if age == 0:
        return 0
    if 25 <= age <= 28:
        return 10
    if 22 <= age <= 24 or 29 <= age <= 32:
        return 7
    if 18 <= age <= 21 or 33 <= age <= 35:
        return 4
    return 2


def _score_direction(state: dict) -> int:
    return DIRECTION_SCORES.get(state.get("direction", ""), 0)


def _score_city(state: dict) -> int:
    city = state.get("city", "")
    if not city:
        return 0
    high_value = {"广州", "深圳", "杭州"}
    mid_value = {"上海", "北京", "成都", "武汉", "南京", "长沙"}
    if city in high_value:
        return 5
    if city in mid_value:
        return 3
    return 2


def _score_profile(state: dict) -> int:
    return (
        _score_education(state)
        + _score_age(state)
        + _score_direction(state)
        + _score_city(state)
    )


# ---- 行为信号评分 ----
def _score_behavior(state: dict) -> int:
    score = 0
    # 主动提供信息
    slot_count = state.get("_slot_update_count", 0)
    score += min(slot_count * 3, 15)
    # 主动问费用
    if state.get("_asked_fee", False):
        score += 10
    # 主动问时间/地点
    if state.get("_asked_time_or_location", False):
        score += 5
    return min(score, 30)


# ---- 意向强度评分 ----
def _score_intent_strength(state: dict) -> int:
    score = 0
    # 明确意向
    if state.get("_expressed_intent", False):
        score += 10
    # 紧迫感
    if state.get("_urgency_detected", False):
        score += 5
    # 确认行为
    confirm_count = state.get("_confirm_count", 0)
    score += min(confirm_count * 3, 10)
    # 主动确认时间
    if state.get("_confirmed_time", False):
        score += 5
    return min(score, 30)


def calculate_lead_score(state: dict) -> int:
    """计算线索分（0-100）"""
    profile = _score_profile(state)
    behavior = _score_behavior(state)
    intent = _score_intent_strength(state)
    total = min(100, max(0, profile + behavior + intent))
    state["lead_score"] = total
    return total


def get_lead_grade(lead_score: int) -> str:
    """根据线索分返回等级"""
    if lead_score >= 80:
        return "S"
    if lead_score >= 60:
        return "A"
    if lead_score >= 40:
        return "B"
    return "C"


def get_lead_priority(lead_score: int) -> str:
    """根据线索等级返回处理优先级"""
    grade = get_lead_grade(lead_score)
    return {"S": "critical", "A": "high", "B": "normal", "C": "low"}[grade]


def update_behavior_signals(state: dict, intent: str, msg: str, slot_updated: bool = False):
    """根据用户行为更新信号标记"""
    # 槽位更新计数
    if slot_updated:
        state["_slot_update_count"] = state.get("_slot_update_count", 0) + 1

    # 费用意图
    if intent == "fee_intent":
        state["_asked_fee"] = True

    # 时间/地点询问
    import re
    if re.search(r"(什么时候|几点|哪天|地址|在哪|怎么过去|过来|去哪)", msg):
        state["_asked_time_or_location"] = True

    # 确认计数
    if intent == "confirm":
        state["_confirm_count"] = state.get("_confirm_count", 0) + 1

    # 明确意向
    if re.search(r"(想学|想转行|想报|想来|想试试|现在就想)", msg):
        state["_expressed_intent"] = True

    # 紧迫感
    if re.search(r"(最近|马上|尽快|这周|今天|现在|立刻)", msg):
        state["_urgency_detected"] = True

    # 时间确认
    if intent == "confirm" and state.get("current_node") in ("invite", "show_fee"):
        state["_confirmed_time"] = True


def get_lead_strategy(lead_score: int) -> dict:
    """根据线索分返回处理策略"""
    grade = get_lead_grade(lead_score)
    strategies = {
        "S": {
            "objection_mode": "personalized",
            "wake_up_interval_days": 1,
            "wake_up_style": "urgency",
            "offer_reimbursement": True,
            "human_handoff_threshold": 60,
            "max_objection_rounds": 5,
        },
        "A": {
            "objection_mode": "standard_plus",
            "wake_up_interval_days": 2,
            "wake_up_style": "value",
            "offer_reimbursement": False,
            "human_handoff_threshold": 70,
            "max_objection_rounds": 4,
        },
        "B": {
            "objection_mode": "standard",
            "wake_up_interval_days": 3,
            "wake_up_style": "standard",
            "offer_reimbursement": False,
            "human_handoff_threshold": 75,
            "max_objection_rounds": 3,
        },
        "C": {
            "objection_mode": "template",
            "wake_up_interval_days": 5,
            "wake_up_style": "light",
            "offer_reimbursement": False,
            "human_handoff_threshold": 80,
            "max_objection_rounds": 2,
        },
    }
    return strategies[grade]


def log_lead_score_change(state: dict, old_score: int, new_score: int, reason: str):
    """记录线索分变化日志"""
    old_grade = get_lead_grade(old_score)
    new_grade = get_lead_grade(new_score)
    if old_grade != new_grade:
        logger.info(f"线索等级变化: {old_grade}({old_score}) -> {new_grade}({new_score}) 原因: {reason}")
    elif abs(new_score - old_score) >= 5:
        logger.info(f"线索分变化: {old_score} -> {new_score} ({reason})")
