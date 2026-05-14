"""异议处理Skill独立封装 - UP-206

将 objection_handler.py 增强为独立Skill，融合面试官话术的异议化解模式。
支持6大类异议的5步法处理 + 新增3类扩展异议（负评/骗局质疑/竞品对比）。
"""
import json
from loguru import logger
from code.model_router import stream_llm
from code.content_generator import match_case, format_case_for_prompt

# 异议类型标签
OBJECTION_LABELS = {
    "objection_consider": "犹豫/再想想",
    "objection_learn": "担心学不会",
    "objection_time": "没时间/太忙",
    "objection_distance": "太远/不方便",
    "objection_institution": "不信任机构",
    "objection_price": "觉得贵",
    "objection_negative_reviews": "网上有差评",
    "objection_is_scam": "质疑是套路/骗子",
    "objection_competitor": "竞品对比",
}

# 异议根因分析（扩展版）
OBJECTION_ROOT_CAUSES = {
    "objection_consider": [
        "担心学完找不到工作", "担心自己坚持不下来",
        "对行业前景不确定", "需要家人支持", "在等其他机会",
    ],
    "objection_learn": [
        "零基础怕跟不上", "年龄大怕学不会",
        "时间不够怕学不完", "听别人说很难", "之前学习经历有挫败感",
    ],
    "objection_time": [
        "工作太忙走不开", "家里事情多",
        "在职状态不方便请假", "时间安排不开",
    ],
    "objection_distance": [
        "外地不方便过来", "本地没有校区",
        "搬家成本高", "家人不同意远行",
    ],
    "objection_institution": [
        "不信任陌生机构", "之前被培训坑过",
        "网上查到负面信息", "朋友/家人反对",
    ],
    "objection_price": [
        "觉得费用太高", "经济压力大",
        "担心付了钱没效果", "对比其他机构价格",
        "觉得不值这个价",
    ],
    "objection_negative_reviews": [
        "网上看到差评", "知乎/小红书有负面",
        "朋友说这家不好",
    ],
    "objection_is_scam": [
        "担心是骗局", "怕被套路",
        "怀疑虚假宣传",
    ],
    "objection_competitor": [
        "在对比其他机构", "朋友推荐了别的",
        "想货比三家",
    ],
}


def classify_objection_root_cause(objection_type: str, user_msg: str) -> str:
    """根据用户消息推断异议根因"""
    if objection_type not in OBJECTION_ROOT_CAUSES:
        return "未明确"

    causes = OBJECTION_ROOT_CAUSES[objection_type]
    for cause in causes:
        # 简单关键词匹配
        keywords = cause.replace("担心", "").replace("不", "").replace("怕", "")
        if any(kw in user_msg for kw in [cause[:4], keywords[:4]] if len(kw) >= 2):
            return cause
    return causes[0]  # 默认返回第一个


def get_objection_script_from_kb(objection_type: str) -> dict:
    """从KB获取异议处理话术模板"""
    try:
        import yaml
        from code import KB_FILE
        with open(KB_FILE, encoding="utf-8") as f:
            KB = yaml.safe_load(f)["scripts"]
        script = KB.get(objection_type)
        if script and isinstance(script, list):
            return {"template": script[0], "source": "kb"}
    except Exception as e:
        logger.warning(f"KB读取失败: {e}")
    return {}


async def generate_objection_response(
    state: dict, objection_type: str, user_msg: str, strategy: str = "standard"
) -> str:
    """
    生成异议回应

    Args:
        state: 用户状态
        objection_type: 异议类型
        user_msg: 用户原始消息
        strategy: 策略模式 — 'standard'(标准5步法) | 'alternative'(备选话术) | 'direct'(真诚直接)

    Returns:
        回应文本
    """
    # 先尝试从KB获取模板
    kb_result = get_objection_script_from_kb(objection_type)
    if kb_result and strategy == "standard":
        logger.info(f"使用KB模板: {objection_type}")
        return kb_result["template"]

    # LLM生成个性化回应
    try:
        case = match_case(state)
        case_text = format_case_for_prompt(case) if case else ""

        obj_label = OBJECTION_LABELS.get(objection_type, "顾虑")
        root_cause = classify_objection_root_cause(objection_type, user_msg)

        collected = []
        for k, label in [("education", "学历"), ("age", "年龄"),
                          ("city", "城市"), ("direction", "方向")]:
            if state.get(k):
                collected.append(f"{label}: {state[k]}")
        info_str = "、".join(collected) if collected else "暂无"

        strategy_instructions = {
            "standard": "用5步法：先共情（1句）→ 探因（1个问题）→ 举证（引用案例或数据）→ 重构（换个角度看问题）→ 行动（明确邀约试听）。控制在120字以内。",
            "alternative": "换一个角度回应，不要重复之前的说法。用新的案例或新的论据。控制在100字以内。",
            "direct": "真诚直接，不绕弯子。简短有力地回应核心顾虑，给出行动建议。控制在80字以内。",
        }
        strategy_prompt = strategy_instructions.get(strategy, strategy_instructions["standard"])

        system_prompt = f"""你是小范，26岁的IT人才服务顾问。用户表达了「{obj_label}」的顾虑：
"{user_msg}"

用户背景：{info_str}
异议根因：{root_cause}

相似案例：
{case_text}

回应策略：
{strategy_prompt}

关键约束：
- 实训周期是一个半月（35-50天），不要说"几个月"或"4个月"
- 网安最低薪资保障9000元/月，大数据最低10000元/月
- 住宿免费，餐饮自理
- 费用叫"就业服务费"，不叫"培训费""学费"
- 不就业不收费，就业后才付费
- 不出现"包就业""保就业""100%"等绝对承诺词
- 用口语化表达，可以带"讲真的""你想想看"

直接输出回应话术，不要加任何解释。"""

        reply = ""
        async for token in stream_llm(system_prompt, 0.7, "main"):
            if token:
                reply += token

        if reply.strip():
            logger.info(f"LLM生成异议回应({obj_label}): {reply[:50]}...")
            return reply.strip()

    except Exception as e:
        logger.warning(f"LLM异议回应生成失败: {e}")

    # 最终降级
    return "我理解你的顾虑。这样，你来校区实地看一下，跟在学的学员聊聊，比我在线上说一百句都强。周末方便吗？"


def execute(params: dict, context: dict = None) -> dict:
    """
    异议处理Skill入口

    params:
        state: dict — 用户状态
        objection_type: str — 异议类型
        user_msg: str — 用户消息
        strategy: str — 策略模式（可选，默认standard）

    returns:
        dict: {"reply": str, "objection_type": str, "root_cause": str}
    """
    import asyncio

    state = params.get("state", {})
    objection_type = params.get("objection_type", "objection_consider")
    user_msg = params.get("user_msg", "")
    strategy = params.get("strategy", "standard")

    root_cause = classify_objection_root_cause(objection_type, user_msg)

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            reply = user_msg  # fallback in async context
        else:
            reply = loop.run_until_complete(
                generate_objection_response(state, objection_type, user_msg, strategy)
            )
    except Exception:
        kb_result = get_objection_script_from_kb(objection_type)
        reply = kb_result.get("template", "我理解你的顾虑。周末来校区看看，跟学员聊聊就清楚了。")

    return {
        "reply": reply,
        "objection_type": objection_type,
        "root_cause": root_cause,
    }


def get_skill_meta():
    """返回Skill元信息"""
    from code.skill_registry import SkillMeta
    return SkillMeta(
        name="objection_handler",
        description="异议处理：6+3类异议的5步法回应，支持标准/备选/直接三种策略模式",
        version="2.0",
        category="sales",
        applicable_stages=[
            "match_campus", "show_fee", "invite",
            "pre_assessment", "reject_qualify",
        ],
        timeout_seconds=10,
        max_retries=1,
    )
