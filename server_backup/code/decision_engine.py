"""自主决策引擎

动态流程控制、动态异议策略、动态信任门禁、对话终止判断。
根据线索等级、对话轮次、行为信号动态调整销售策略。
"""
from loguru import logger
from code.time_utils import get_beijing_time


# ---- 动态流程控制 ----

def should_skip_steps(state: dict, lead_score: int, intent: str) -> str:
    """判断是否可以跳过中间步骤，返回目标状态或None"""
    current = state.get("current_node", "icebreak")
    rounds = state.get("_conversation_rounds", 0)

    # 高意向用户：跳过校区匹配，直接报价
    if (lead_score >= 80
            and current == "qualify"
            and state.get("_asked_fee", False)
            and state.get("education", "")):
        logger.info(f"决策引擎: 高意向用户(lead={lead_score})跳过match_campus到show_fee")
        return "show_fee"

    # 极高意向用户：跳到邀约
    if (lead_score >= 90
            and current in ("qualify", "match_campus")
            and intent == "fee_intent"):
        logger.info(f"决策引擎: 极高意向用户(lead={lead_score})跳到invite")
        return "invite"

    # 用户明确表示明天就想来
    if current in ("show_fee", "match_campus") and intent == "confirm":
        if state.get("_urgency_detected", False):
            logger.info("决策引擎: 用户表达紧迫感，跳到report_info")
            return "report_info"

    return None


# ---- 动态异议策略 ----

def get_objection_strategy(intent: str, state: dict, lead_score: int) -> dict:
    """根据异议历史和线索等级选择处理策略"""
    objection_key = f"_{intent}_count"
    count = state.get(objection_key, 0)

    # 更新异议计数
    state[objection_key] = count + 1
    # Only track per-type, not total (different objections shouldn't compound)
    state["_objection_total"] = state.get("_objection_total", 0)  # keep for analytics

    # 根据线索等级获取最大异议轮数
    if lead_score >= 80:
        max_rounds = 5
    elif lead_score >= 60:
        max_rounds = 4
    elif lead_score >= 40:
        max_rounds = 3
    else:
        max_rounds = 3

    if count == 0:
        # 第一次出现：标准5步法
        strategy = {
            "mode": "standard_5step",
            "use_llm": lead_score >= 60,
            "escalate": False,
        }
    elif count == 1:
        # 第二次出现：换一种话术
        strategy = {
            "mode": "alternative_script",
            "use_llm": lead_score >= 70,
            "escalate": False,
        }
    elif count < max_rounds:
        # 第三次出现：真诚模式
        strategy = {
            "mode": "direct_mode",
            "use_llm": True,
            "escalate": False,
        }
    else:
        # 超过最大轮数：考虑转人工或放弃
        strategy = {
            "mode": "escalate",
            "use_llm": False,
            "escalate": True,
        }

    strategy["round"] = count + 1
    strategy["max_rounds"] = max_rounds
    return strategy


# ---- 动态信任门禁 ----

def get_dynamic_threshold(target_node: str, lead_score: int) -> int:
    """根据线索等级动态调整信任门禁阈值"""
    base_thresholds = {
        "qualify": 30,
        "match_campus": 30,
        "reject_qualify": 30,
        "show_fee": 50,
        "invite": 50,
        "report_info": 70,
        "completed": 70,
    }

    base = base_thresholds.get(target_node, 0)

    # S级用户降低门槛
    if lead_score >= 80:
        return max(0, base - 15)
    # A级用户小幅降低
    elif lead_score >= 60:
        return max(0, base - 5)
    # C级用户提高门槛
    elif lead_score < 40:
        return min(100, base + 10)

    return base


def can_advance_dynamic(state: dict, target_node: str, lead_score: int) -> bool:
    """动态信任门禁检查"""
    trust = state.get("trust_level", 50)
    threshold = get_dynamic_threshold(target_node, lead_score)
    can = trust >= threshold
    if not can:
        logger.info(f"动态门禁: trust={trust} < threshold={threshold} (target={target_node}, lead={lead_score})")
    return can


# ---- 对话终止判断 ----

def should_end_conversation(state: dict, lead_score: int, conversation_rounds: int) -> tuple:
    """判断是否应该终止对话，返回 (should_end, reason)"""

    # 10轮对话后没有任何槽位更新
    slot_updates = state.get("_slot_update_count", 0)
    if conversation_rounds >= 10 and slot_updates == 0:
        return True, "无信息输出"

    # 连续3次拒绝
    reject_count = state.get("_reject_count", 0)
    if reject_count >= 3:
        return True, "连续拒绝"

    # C级用户 + 低信任 + 5轮以上
    if lead_score < 40 and state.get("trust_level", 50) < 30 and conversation_rounds >= 5:
        return True, "低价值低信任"

    # 用户明确表示不感兴趣
    if state.get("rejected", False):
        last_reject = state.get("last_rejected_time")
        if last_reject:
            try:
                from datetime import datetime
                reject_time = datetime.fromisoformat(last_reject)
                now = get_beijing_time()
                if (now - reject_time).total_seconds() > 3600:  # 1小时前拒绝的
                    return True, "明确拒绝超时"
            except Exception:
                pass

    return False, ""


# ---- 沉默用户唤醒策略 ----

def get_wake_up_strategy(state: dict, lead_score: int, inactive_days: int) -> dict:
    """根据用户特征选择唤醒策略"""
    grade = "S" if lead_score >= 80 else "A" if lead_score >= 60 else "B" if lead_score >= 40 else "C"

    if lead_score >= 70 and inactive_days <= 3:
        return {
            "style": "urgency",
            "priority": "high",
            "message_type": "名额紧张",
        }
    elif lead_score >= 50 and inactive_days <= 7:
        return {
            "style": "value",
            "priority": "medium",
            "message_type": "案例分享",
        }
    elif inactive_days > 7:
        return {
            "style": "light",
            "priority": "low",
            "message_type": "轻触问候",
        }
    else:
        return {
            "style": "standard",
            "priority": "normal",
            "message_type": "标准唤醒",
        }


# ---- 对话节奏控制 ----

def get_conversation_pace(state: dict, lead_score: int) -> dict:
    """根据对话状态调整节奏"""
    rounds = state.get("_conversation_rounds", 0)
    current = state.get("current_node", "icebreak")

    # 快节奏：高意向用户
    if lead_score >= 80:
        return {
            "pace": "fast",
            "max_questions_per_turn": 1,
            "allow_skip": True,
            "direct_style": True,
        }

    # 中等节奏：普通用户
    if lead_score >= 50:
        return {
            "pace": "normal",
            "max_questions_per_turn": 2,
            "allow_skip": False,
            "direct_style": False,
        }

    # 慢节奏：低意向用户，不要逼太紧
    return {
        "pace": "slow",
        "max_questions_per_turn": 1,
        "allow_skip": False,
        "direct_style": False,
    }


# ---- 人工协作判断 ----

def should_handoff_to_human(state: dict, lead_score: int, intent: str) -> tuple:
    """判断是否需要转人工，返回 (should_handoff, level, reason)"""
    # 用户主动要求
    if intent == "request_human":
        return True, 3, "用户主动要求转人工"

    # 高价值线索在关键节点
    if lead_score >= 80 and state.get("current_node") in ("show_fee", "invite"):
        return True, 1, "高价值线索在关键节点"

    # 同类型异议超3次无法化解
    if intent.startswith("objection_"):
        obj_count = state.get(f"_{intent}_count", 0)
        if obj_count >= 3:
            return True, 2, f"同类型异议无法化解: {intent}"

    # 2次情绪挫败
    frustration_count = state.get("_frustration_count", 0)
    if frustration_count >= 2:
        return True, 2, "用户情绪挫败"

    return False, 0, ""
