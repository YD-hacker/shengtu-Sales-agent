"""个性化触达模块

用户画像标签体系 + 话术矩阵 + 动态话术拼接。
根据用户画像（年龄、学历、痛点、决策风格）选择最合适的话术风格。
"""
import re
from loguru import logger


# ---- 用户画像标签 ----

def build_user_profile(state: dict) -> dict:
    """构建用户画像标签"""
    profile = {}

    # 年龄段
    try:
        age = int(state.get("age", 0))
    except (ValueError, TypeError):
        age = 0
    if age > 0:
        if age <= 25:
            profile["age_group"] = "young"
        elif age <= 29:
            profile["age_group"] = "mid"
        else:
            profile["age_group"] = "senior"
    else:
        profile["age_group"] = "unknown"

    # 学历层
    edu = state.get("education", "")
    if "本科" in edu:
        profile["edu_level"] = "bachelor"
    elif "大专" in edu:
        profile["edu_level"] = "college"
    else:
        profile["edu_level"] = "other"

    # 经济压力
    if state.get("_objection_price_count", 0) > 0 or state.get("_asked_fee", False):
        profile["economic_pressure"] = "high"
    else:
        profile["economic_pressure"] = "normal"

    # 决策风格
    confirm_count = state.get("_confirm_count", 0)
    objection_count = state.get("_objection_total", 0)
    if confirm_count >= 2 and objection_count == 0:
        profile["decision_style"] = "decisive"
    elif objection_count >= 2:
        profile["decision_style"] = "hesitant"
    else:
        profile["decision_style"] = "analytical"

    # 痛点类型
    pain_points = state.get("pain_points", [])
    if pain_points:
        profile["pain_type"] = pain_points[-1]
    else:
        profile["pain_type"] = "none"

    # 信息渠道（目前默认，后续可从来源追踪）
    profile["source"] = state.get("source", "unknown")

    return profile


# ---- 话术矩阵 ----

# 共情开头
EMPATHY_OPENERS = {
    "age_group": {
        "young": "你现在这个年纪转行，时间站在你这边。",
        "mid": "现在转行正是时候，经验够了年龄也不大。",
        "senior": "我理解你的顾虑，但年龄真不是问题。",
    },
    "pain_type": {
        "factory_worker": "在厂里干久了确实看不到头，我能理解。",
        "low_end_job": "送外卖跑滴滴辛苦还不稳定，换谁都想改变。",
        "layoff": "被裁确实难受，但这也许是个机会。",
        "no_future": "看不到希望的时候最难受，但你愿意了解说明还没放弃。",
        "fear_change": "怕学不会很正常，谁第一次接触新东西不害怕。",
        "unwilling": "不甘心就对了——说明你还有追求。",
        "age_too_old": "年纪大不是问题，我见过35岁转行成功的。",
    },
}

# 核心卖点
CORE_SELLING_POINTS = {
    "economic_pressure": {
        "high": "钱的事你不用担心，入职了才收费，零风险。还有分期方案，前两个月每月1毛钱。",
        "normal": "我们的模式是先就业后付费，不就业不收费，合同白纸黑字。",
    },
    "edu_level": {
        "bachelor": "你本科的学历走保障班完全没问题，最低薪资协议写在合同里。",
        "college": "大专学历可以走网安方向，毕业满两年走保障班。",
        "other": "非统招学历可以走非保障技能班，费用更低，学完也能帮你推岗位。",
    },
}

# 行动号召
ACTION_CALLS = {
    "decision_style": {
        "decisive": "这周二新班开课，你过来直接跟课试听，定吗？",
        "hesitant": "你先来试听一天，住宿我安排，听完再决定，不急。",
        "analytical": "你来校区看看，我给你看合同和学员案例，你自己判断。",
    },
}


def get_personalized_empathy(state: dict) -> str:
    """获取个性化共情开头"""
    profile = build_user_profile(state)

    # 优先使用痛点共情
    pain = profile.get("pain_type", "none")
    if pain != "none" and pain in EMPATHY_OPENERS.get("pain_type", {}):
        return EMPATHY_OPENERS["pain_type"][pain]

    # 其次使用年龄段共情
    age_group = profile.get("age_group", "unknown")
    if age_group in EMPATHY_OPENERS.get("age_group", {}):
        return EMPATHY_OPENERS["age_group"][age_group]

    return "我理解你的顾虑。"


def get_personalized_selling_point(state: dict) -> str:
    """获取个性化核心卖点"""
    profile = build_user_profile(state)

    # 经济压力优先
    pressure = profile.get("economic_pressure", "normal")
    if pressure in CORE_SELLING_POINTS.get("economic_pressure", {}):
        return CORE_SELLING_POINTS["economic_pressure"][pressure]

    # 学历层
    edu = profile.get("edu_level", "other")
    if edu in CORE_SELLING_POINTS.get("edu_level", {}):
        return CORE_SELLING_POINTS["edu_level"][edu]

    return ""


def get_personalized_action_call(state: dict) -> str:
    """获取个性化行动号召"""
    profile = build_user_profile(state)
    style = profile.get("decision_style", "analytical")
    return ACTION_CALLS.get("decision_style", {}).get(
        style,
        "你先来试听一天，住宿我安排，听完再决定。",
    )


def get_personalized_objection_response(state: dict, objection_type: str) -> str:
    """获取个性化异议回应"""
    profile = build_user_profile(state)

    # 根据线索等级选择回应模式
    lead_score = state.get("lead_score", 50)
    if lead_score >= 80:
        mode = "personalized"
    elif lead_score >= 60:
        mode = "standard_plus"
    elif lead_score >= 40:
        mode = "standard"
    else:
        mode = "template"

    if mode == "personalized":
        # 高价值用户：用LLM生成个性化回应
        return ""  # 返回空，让调用方知道需要LLM生成
    elif mode == "standard_plus":
        # 中高价值用户：模板 + 个性化片段
        return _get_standard_plus_response(objection_type, profile)
    else:
        # 其他用户：标准模板
        return ""  # 返回空，使用默认模板


def _get_standard_plus_response(objection_type: str, profile: dict) -> str:
    """标准+模式的异议回应"""
    responses = {
        "objection_consider": {
            "age_group": {
                "young": "你现在考虑的时间成本最低，试错代价也最小。",
                "mid": "犹豫一年，年龄大一岁，机会少一分。",
                "senior": "与其一直考虑，不如来试听一天，亲眼看看再决定。",
            },
        },
        "objection_price": {
            "economic_pressure": {
                "high": "你想想，不是你先掏钱，是你先有工作再付钱。哪个风险大？",
                "normal": "这笔钱是就业服务费，不是学费。入职了才收，不就业不收。",
            },
        },
        "objection_learn": {
            "pain_type": {
                "fear_change": "我理解你的担心。但咱这边零基础从打字开始教，一步一步来。",
            },
        },
    }

    type_responses = responses.get(objection_type, {})
    for dimension, options in type_responses.items():
        value = profile.get(dimension, "")
        if value in options:
            return options[value]

    return ""


def get_personalized_wake_up_message(state: dict) -> str:
    """获取个性化唤醒消息"""
    profile = build_user_profile(state)
    pain = profile.get("pain_type", "none")
    lead_score = state.get("lead_score", 50)

    if lead_score >= 70:
        # 高价值用户：紧迫感唤醒
        messages = [
            "你上次说考虑的，最近名额快满了，我帮你留着呢。",
            "上周有个跟你情况差不多的来了，试听完当场报名了。",
        ]
    elif pain in ("factory_worker", "low_end_job", "layoff"):
        # 有痛点的用户：案例唤醒
        messages = [
            "最近有个从工厂出来的学员入职了，现在坐办公室月薪9000多。",
            "上个月有个送外卖的哥们来试听，现在转行做网安了。",
        ]
    else:
        # 其他用户：轻触唤醒
        messages = [
            "最近忙吗？有什么想了解的随时找我。",
            "最近网安岗位需求又涨了，你有兴趣可以了解下。",
        ]

    # 根据用户ID哈希选择消息（保证同一用户每次不同）
    user_id = state.get("user_id", "")
    idx = hash(user_id) % len(messages)
    return messages[idx]
