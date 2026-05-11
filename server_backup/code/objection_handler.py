"""动态异议处理模块

功能：
1. LLM动态生成异议回应
2. 案例智能匹配
3. 多轮异议策略
4. 异议根因分析
"""
import json
from loguru import logger
from code.model_router import stream_llm
from code.content_generator import match_case, format_case_for_prompt


# 异议类型标签映射
OBJECTION_LABELS = {
    "objection_consider": "犹豫/再想想",
    "objection_learn": "担心学不会",
    "objection_time": "没时间/太忙",
    "objection_distance": "太远/不方便",
    "objection_institution": "不信任机构",
    "objection_price": "觉得贵",
}

# 异议根因分析
OBJECTION_ROOT_CAUSES = {
    "objection_consider": [
        "担心学完找不到工作",
        "担心自己坚持不下来",
        "对行业前景不确定",
        "需要家人支持",
        "在等其他机会"
    ],
    "objection_learn": [
        "零基础怕跟不上",
        "年龄大怕学不会",
        "时间不够怕学不完",
        "听别人说很难"
    ],
    "objection_time": [
        "工作太忙走不开",
        "家里事情多",
        "在职状态不方便请假",
        "时间安排不开"
    ],
    "objection_distance": [
        "外地不方便过来",
        "本地没有校区",
        "搬家成本高"
    ],
    "objection_institution": [
        "担心被骗",
        "网上看到负面评价",
        "不了解公司背景",
        "需要更多证明"
    ],
    "objection_price": [
        "经济压力大",
        "觉得性价比不高",
        "想对比其他机构",
        "想等降价或优惠"
    ]
}


async def generate_objection_response(intent, user_msg, state, history=None):
    """让LLM动态生成异议回应，融合用户画像"""
    history = history or []

    pain_points = state.get("pain_points", [])
    lead_score = state.get("lead_score", 50)
    trust = state.get("trust_level", 50)

    # 获取最匹配的案例
    case = match_case(state)
    case_text = format_case_for_prompt(case)

    # 分析可能的根因
    possible_causes = OBJECTION_ROOT_CAUSES.get(intent, ["未知顾虑"])
    causes_text = "、".join(possible_causes[:3])

    # 获取用户基础信息
    age = state.get("age", "未知")
    education = state.get("education", "未知")
    city = state.get("city", "未知")
    direction = state.get("direction", "网安")

    # 获取深度用户画像
    profile_context = ""
    try:
        from code.user_profiler import build_deep_profile, get_personalized_strategy
        profile = build_deep_profile(state, history)
        strategies = get_personalized_strategy(profile)
        parts = []
        if strategies.get("decision_style"):
            style_map = {"decisive": "果断型，直接给方案", "hesitant": "犹豫型，多给案例降低风险",
                         "analytical": "分析型，给数据和细节", "exploratory": "探索型，多引导"}
            parts.append(f"决策风格: {style_map.get(strategies['decision_style'], strategies['decision_style'])}")
        if strategies.get("economic_pressure"):
            pressure_map = {"high": "经济压力大，强调零风险和分期", "medium": "有一定压力，强调性价比", "low": "压力小，可以推标准方案"}
            parts.append(f"经济压力: {pressure_map.get(strategies['economic_pressure'], strategies['economic_pressure'])}")
        if strategies.get("communication_style"):
            comm_map = {"verbose": "话多型，回复可以简洁些", "concise": "简洁型，不要啰嗦", "normal": "正常沟通"}
            parts.append(f"沟通风格: {comm_map.get(strategies['communication_style'], strategies['communication_style'])}")
        if parts:
            profile_context = "\n- " + "\n- ".join(parts)
    except Exception as e:
        logger.debug(f"异议处理获取用户画像失败: {e}")

    prompt = f"""你是小范，26岁的IT人才服务顾问。用户表达了顾虑：
"{user_msg}"

用户背景：
- 年龄：{age}
- 学历：{education}
- 城市：{city}
- 方向：{direction}
- 痛点：{'、'.join(pain_points) if pain_points else '无'}
- 线索等级：{lead_score}
- 信任度：{trust}
- 可能的顾虑原因：{causes_text}
{profile_context}

相似案例：
{case_text}

【异议处理5步法】
1. 共情：先理解用户的顾虑，不要否定
2. 探因：询问具体原因，了解真实想法
3. 举证：用案例或数据证明，让用户信服
4. 重构：重新定义问题，换个角度思考
5. 行动：给出明确下一步，降低决策门槛

要求：
1. 真诚自然，像朋友聊天，不要模板化
2. 针对用户的具体情况回应，不要泛泛而谈
3. 引用案例时要自然融入对话，不要生硬
4. 控制在120字以内，口语化表达
5. 不要出现"培训""学费""保证""一定"等词
6. 可以适当使用表情符号增加亲和力
7. 先输出共情，再给方案，不要一上来就推销
8. 根据用户画像调整沟通风格（果断型给方案、犹豫型给案例、分析型给数据）

直接输出回复："""

    reply = ""
    try:
        async for token in stream_llm(prompt, 0.7, "main"):
            if token:
                reply += token
    except Exception as e:
        logger.warning(f"异议回应生成失败: {e}")
        return ""

    return reply.strip()


async def analyze_objection_root_cause(intent, user_msg, state):
    """分析异议根因"""
    prompt = f"""分析用户的真实顾虑原因。

用户说："{user_msg}"
异议类型：{OBJECTION_LABELS.get(intent, intent)}

用户背景：
- 年龄：{state.get('age', '未知')}
- 学历：{state.get('education', '未知')}
- 城市：{state.get('city', '未知')}

请分析用户最可能的真实顾虑原因，只输出一个最可能的原因，不要解释。"""

    try:
        result = ""
        async for token in stream_llm(prompt, 0.3, "main"):
            if token:
                result += token
        return result.strip()
    except Exception as e:
        logger.warning(f"根因分析失败: {e}")
        return "未知"


def get_objection_strategy(intent, state, lead_score):
    """获取异议处理策略"""
    objection_key = f"_{intent}_count"
    count = state.get(objection_key, 0)

    # 根据线索等级获取最大异议轮数
    if lead_score >= 80:
        max_rounds = 5
    elif lead_score >= 60:
        max_rounds = 4
    elif lead_score >= 40:
        max_rounds = 3
    else:
        max_rounds = 2

    # 更新异议计数
    state[objection_key] = count + 1

    if count == 0:
        # 第一次出现：标准5步法 + LLM生成
        strategy = {
            "mode": "standard_5step",
            "use_llm": True,
            "escalate": False,
        }
    elif count == 1:
        # 第二次出现：换一种话术 + LLM生成
        strategy = {
            "mode": "alternative_script",
            "use_llm": True,
            "escalate": False,
        }
    elif count < max_rounds:
        # 第三次出现：真诚模式 + LLM生成
        strategy = {
            "mode": "direct_mode",
            "use_llm": True,
            "escalate": False,
        }
    else:
        # 超过最大轮数：考虑转人工
        strategy = {
            "mode": "escalate",
            "use_llm": False,
            "escalate": True,
        }

    strategy["round"] = count + 1
    strategy["max_rounds"] = max_rounds
    return strategy
