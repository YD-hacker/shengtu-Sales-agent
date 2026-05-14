"""深度用户画像模块

功能：
1. 多维度用户画像构建
2. 行为分析和预测
3. 决策风格识别
4. 经济压力评估
5. 沟通风格分析
"""
import re
from loguru import logger


def build_deep_profile(state, history=None, intent_log=None):
    """构建深度用户画像"""
    history = history or []
    intent_log = intent_log or []

    profile = {
        # 基础画像
        "age_group": _get_age_group(state.get("age")),
        "edu_level": _get_edu_level(state.get("education")),
        "city_tier": _get_city_tier(state.get("city")),

        # 行为画像
        "response_speed": _analyze_response_speed(history),
        "engagement_level": _analyze_engagement(history),
        "information_seeking": _analyze_info_seeking(intent_log),

        # 心理画像
        "decision_style": _analyze_decision_style(state, intent_log),
        "economic_pressure": _analyze_economic_pressure(state, history),
        "urgency_level": _analyze_urgency(state, history),

        # 沟通风格
        "communication_style": _analyze_communication_style(history),
        "question_frequency": _analyze_question_frequency(history),
        "emotional_state": _analyze_emotional_state(history, intent_log),

        # 意向强度
        "intent_strength": _analyze_intent_strength(state, intent_log),
        "conversion_probability": _estimate_conversion_probability(state),
    }

    return profile


def _get_age_group(age_str):
    """年龄段分组"""
    try:
        age = int(age_str) if age_str else 0
    except (ValueError, TypeError):
        return "unknown"

    if age == 0:
        return "unknown"
    elif age <= 25:
        return "young"
    elif age <= 29:
        return "mid"
    elif age <= 35:
        return "senior"
    else:
        return "mature"


def _get_edu_level(edu_str):
    """学历层级"""
    if not edu_str:
        return "unknown"
    if "硕士" in edu_str or "研究生" in edu_str:
        return "master"
    elif "本科" in edu_str:
        if "统招" in edu_str:
            return "bachelor_regular"
        return "bachelor"
    elif "大专" in edu_str:
        if "统招" in edu_str:
            return "college_regular"
        return "college"
    else:
        return "other"


def _get_city_tier(city_str):
    """城市层级"""
    if not city_str:
        return "unknown"

    tier1 = ["广州", "深圳", "杭州", "上海", "北京"]
    tier2 = ["成都", "武汉", "南京", "长沙", "重庆", "西安", "郑州"]

    if any(c in city_str for c in tier1):
        return "tier1"
    elif any(c in city_str for c in tier2):
        return "tier2"
    else:
        return "tier3"


def _analyze_response_speed(history):
    """分析回复速度（基于消息长度和频率）"""
    if not history:
        return "unknown"

    avg_length = sum(len(h.get("user", "")) for h in history) / len(history)

    if avg_length > 50:
        return "detailed"  # 详细型
    elif avg_length > 20:
        return "normal"  # 正常型
    else:
        return "brief"  # 简洁型


def _analyze_engagement(history):
    """分析参与度"""
    if not history:
        return "low"

    # 基于对话轮次判断
    rounds = len(history)
    if rounds >= 5:
        return "high"
    elif rounds >= 3:
        return "medium"
    else:
        return "low"


def _analyze_info_seeking(intent_log):
    """分析信息获取倾向"""
    question_intents = ["normal", "fee_intent", "objection_institution"]
    question_count = sum(1 for i in intent_log if i in question_intents)

    if question_count >= 3:
        return "high"
    elif question_count >= 1:
        return "medium"
    else:
        return "low"


def _analyze_decision_style(state, intent_log):
    """分析决策风格"""
    confirm_count = sum(1 for i in intent_log if i == "confirm")
    objection_count = sum(1 for i in intent_log if i.startswith("objection_"))
    question_count = sum(1 for i in intent_log if i == "normal")

    if confirm_count >= 2 and objection_count == 0:
        return "decisive"  # 果断型
    elif objection_count >= 3:
        return "hesitant"  # 犹豫型
    elif question_count >= 3:
        return "analytical"  # 分析型
    elif objection_count >= 1:
        return "cautious"  # 谨慎型
    else:
        return "exploratory"  # 探索型


def _analyze_economic_pressure(state, history):
    """分析经济压力"""
    pressure_signals = 0

    # 问价格
    if state.get("_asked_fee"):
        pressure_signals += 2

    # 价格异议
    if state.get("_objection_price_count", 0) > 0:
        pressure_signals += 3

    # 提到钱相关词
    for h in history[-5:]:
        msg = h.get("user", "")
        if any(w in msg for w in ["没钱", "贷款", "分期", "压力大", "月光", "负债", "信用卡", "花呗"]):
            pressure_signals += 2

    if pressure_signals >= 4:
        return "high"
    elif pressure_signals >= 2:
        return "medium"
    else:
        return "low"


def _analyze_urgency(state, history):
    """分析紧迫度"""
    urgency_signals = 0

    # 时间相关异议
    if state.get("_objection_time_count", 0) > 0:
        urgency_signals += 2

    # 提到时间相关词
    for h in history[-3:]:
        msg = h.get("user", "")
        if any(w in msg for w in ["尽快", "马上", "急", "赶紧", "这周", "下周"]):
            urgency_signals += 2

    # 确认意向
    if state.get("_confirm_count", 0) > 0:
        urgency_signals += 1

    if urgency_signals >= 3:
        return "high"
    elif urgency_signals >= 1:
        return "medium"
    else:
        return "low"


def _analyze_communication_style(history):
    """分析沟通风格"""
    if not history:
        return "unknown"

    avg_length = sum(len(h.get("user", "")) for h in history) / len(history)

    if avg_length > 50:
        return "verbose"  # 话多型
    elif avg_length < 10:
        return "concise"  # 简洁型
    else:
        return "normal"  # 正常型


def _analyze_question_frequency(history):
    """分析提问频率"""
    if not history:
        return "low"

    question_marks = sum(h.get("user", "").count("?") + h.get("user", "").count("？") for h in history)

    if question_marks >= 5:
        return "high"
    elif question_marks >= 2:
        return "medium"
    else:
        return "low"


def _analyze_emotional_state(history, intent_log):
    """分析情绪状态"""
    frustration_count = sum(1 for i in intent_log if i == "user_frustration")
    pain_count = sum(1 for i in intent_log if i == "express_pain")
    reject_count = sum(1 for i in intent_log if i == "reject")

    if frustration_count >= 2:
        return "frustrated"
    elif pain_count >= 1:
        return "pained"
    elif reject_count >= 2:
        return "resistant"
    else:
        return "neutral"


def _analyze_intent_strength(state, intent_log):
    """分析意向强度"""
    score = 0

    # 确认意向
    if state.get("_expressed_intent"):
        score += 20

    # 费用意向
    if state.get("_asked_fee"):
        score += 15

    # 确认次数
    confirm_count = state.get("_confirm_count", 0)
    score += min(confirm_count * 10, 30)

    # 紧迫感
    if state.get("_urgency_detected"):
        score += 15

    # 拒绝扣分
    reject_count = state.get("_reject_count", 0)
    score -= reject_count * 10

    return max(0, min(100, score))


def _estimate_conversion_probability(state):
    """估算转化概率"""
    lead_score = state.get("lead_score", 50)
    trust = state.get("trust_level", 50)
    current_node = state.get("current_node", "icebreak")

    # 基础概率
    base_prob = 0.1

    # 线索分加成
    if lead_score >= 80:
        base_prob += 0.3
    elif lead_score >= 60:
        base_prob += 0.2
    elif lead_score >= 40:
        base_prob += 0.1

    # 信任度加成
    if trust >= 70:
        base_prob += 0.2
    elif trust >= 50:
        base_prob += 0.1

    # 阶段加成
    stage_bonus = {
        "icebreak": 0,
        "qualify": 0.05,
        "match_campus": 0.1,
        "show_fee": 0.15,
        "invite": 0.2,
        "report_info": 0.3,
        "completed": 1.0
    }
    base_prob += stage_bonus.get(current_node, 0)

    return min(1.0, base_prob)


def get_personalized_strategy(profile):
    """根据画像获取个性化策略"""
    strategies = {
        "communication_style": {
            "verbose": "用户话多，可以多聊细节，但要注意引导主线",
            "concise": "用户简洁，回复也要精炼，不要啰嗦",
            "normal": "正常沟通节奏"
        },
        "decision_style": {
            "decisive": "果断型用户，直接给选择，不要犹豫",
            "hesitant": "犹豫型用户，多给案例，降低风险感知",
            "analytical": "分析型用户，给数据，给细节",
            "cautious": "谨慎型用户，多用合同和保障说话",
            "exploratory": "探索型用户，多给信息，引导方向"
        },
        "economic_pressure": {
            "high": "经济压力大，强调分期方案和零风险",
            "medium": "中等经济压力，正常报价",
            "low": "经济压力小，可以推荐高端方案"
        },
        "urgency_level": {
            "high": "紧迫度高，强调名额有限，快速推进",
            "medium": "中等紧迫度，正常节奏",
            "low": "紧迫度低，需要培养紧迫感"
        }
    }

    result = {}
    for key, options in strategies.items():
        value = profile.get(key, "")
        if value in options:
            result[key] = options[value]

    return result
