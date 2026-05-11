"""内容生成模块

LLM个性化共情生成、案例匹配库、分级内容策略。
根据用户画像和痛点生成针对性的内容，而不是所有人看到一样的话。
"""
import os
import yaml
from loguru import logger
from code import CONFIG_FILE


# ---- 案例库 ----
CASES = [
    {
        "id": "case_001",
        "age": 32, "gender": "男", "previous_job": "工厂工人",
        "education": "统招大专", "city": "广州", "direction": "网安",
        "current_job": "安全运维", "salary": 9500, "duration": "4个月",
        "pain_type": "factory_worker",
        "quote": "在厂里干了8年，出来学了4个月，现在坐办公室比以前轻松多了",
    },
    {
        "id": "case_002",
        "age": 25, "gender": "女", "previous_job": "收银员",
        "education": "统招本科", "city": "杭州", "direction": "大数据",
        "current_job": "数据分析师", "salary": 11000, "duration": "5个月",
        "pain_type": "low_end_job",
        "quote": "以前觉得数据分析很高大上，学了才发现零基础也能上手",
    },
    {
        "id": "case_003",
        "age": 29, "gender": "男", "previous_job": "外卖骑手",
        "education": "统招大专", "city": "广州", "direction": "网安",
        "current_job": "渗透测试", "salary": 12000, "duration": "4个月",
        "pain_type": "low_end_job",
        "quote": "送了两年外卖，风里来雨里去，现在做安全测试，再也不用看天吃饭了",
    },
    {
        "id": "case_004",
        "age": 35, "gender": "男", "previous_job": "电子厂工人",
        "education": "统招大专", "city": "深圳", "direction": "网安",
        "current_job": "安全工程师", "salary": 15000, "duration": "5个月",
        "pain_type": "factory_worker",
        "quote": "35岁被厂里裁了，以为这辈子完了，没想到学了网安反而工资翻倍",
    },
    {
        "id": "case_005",
        "age": 23, "gender": "女", "previous_job": "应届毕业生",
        "education": "统招本科", "city": "广州", "direction": "大数据",
        "current_job": "大数据开发", "salary": 13000, "duration": "5个月",
        "pain_type": "no_future",
        "quote": "毕业即失业，在家蹲了半年，来学了5个月大数据，现在月薪13000",
    },
    {
        "id": "case_006",
        "age": 31, "gender": "男", "previous_job": "被裁员",
        "education": "统招本科", "city": "杭州", "direction": "网安",
        "current_job": "安全运维", "salary": 10000, "duration": "4个月",
        "pain_type": "layoff",
        "quote": "被裁后焦虑了两个月，来学了4个月网安，现在比以前还稳定",
    },
    {
        "id": "case_007",
        "age": 27, "gender": "男", "previous_job": "保安",
        "education": "统招大专", "city": "广州", "direction": "网安",
        "current_job": "安全服务", "salary": 8500, "duration": "4个月",
        "pain_type": "low_end_job",
        "quote": "以前站岗一个月4000，现在做安全服务8500，还不用风吹日晒",
    },
    {
        "id": "case_008",
        "age": 26, "gender": "女", "previous_job": "客服",
        "education": "统招大专", "city": "杭州", "direction": "大数据",
        "current_job": "数据运营", "salary": 9000, "duration": "4个月",
        "pain_type": "unwilling",
        "quote": "做了三年客服，不甘心一辈子这样，学了数据分析现在终于有技术傍身了",
    },
]


def match_case(state: dict) -> dict:
    """根据用户画像匹配最相关的案例"""
    pain_points = state.get("pain_points", [])
    try:
        age = int(state.get("age", 0))
    except (ValueError, TypeError):
        age = 0
    education = state.get("education", "")
    city = state.get("city", "")
    direction = state.get("direction", "")

    scored_cases = []
    for case in CASES:
        score = 0

        # 痛点匹配（最高权重）
        if pain_points and case["pain_type"] in pain_points:
            score += 30

        # 年龄接近
        if age > 0 and abs(case["age"] - age) <= 3:
            score += 15
        elif age > 0 and abs(case["age"] - age) <= 5:
            score += 8

        # 学历匹配
        if education and case["education"] in education:
            score += 10

        # 城市匹配
        if city and case["city"] == city:
            score += 8

        # 方向匹配
        if direction and case["direction"] == direction:
            score += 10

        scored_cases.append((score, case))

    if not scored_cases:
        return CASES[0]

    scored_cases.sort(key=lambda x: x[0], reverse=True)
    return scored_cases[0][1]


def format_case_for_prompt(case: dict) -> str:
    """将案例格式化为对话中可用的文本"""
    quote = case['quote']
    return (
        f"上个月有个{case['age']}岁的学员，之前{case['previous_job']}，"
        f"学了{case['duration']}{case['direction']}，"
        f"现在做{case['current_job']}，月薪{case['salary']}。"
        f"他跟我说：“{quote}”"
    )


async def generate_personalized_empathy(state: dict, user_msg: str, pain_tag: str) -> str:
    """用LLM生成个性化共情回应"""
    try:
        from code.model_router import stream_llm
        from code.personalization import build_user_profile

        profile = build_user_profile(state)
        case = match_case(state)
        case_text = format_case_for_prompt(case)

        collected = []
        for k, label in [("education", "学历"), ("age", "年龄"),
                          ("city", "城市"), ("direction", "方向")]:
            if state.get(k):
                collected.append(f"{label}: {state[k]}")
        info_str = "、".join(collected) if collected else "暂无"

        system_prompt = f"""你是小苏，28岁的IT人才服务顾问。用户表达了以下困境：
"{user_msg}"

用户背景：{info_str}
痛点类型：{pain_tag}

相似案例：
{case_text}

要求：
1. 用2-3句话真诚共情，不要模板化，要像朋友聊天
2. 自然地引用上面的案例（不要生硬，融入对话）
3. 自然过渡到"先来试听看看"
4. 不要出现"培训""学费""保证""一定"等词
5. 控制在100字以内
6. 用口语化表达，可以说"讲真的""你想想看"

直接输出共情话术，不要加任何解释。"""

        reply = ""
        async for token in stream_llm(system_prompt, 0.7, "main"):
            if token:
                reply += token

        if reply.strip():
            logger.info(f"LLM生成共情: {reply[:50]}...")
            return reply.strip()

    except Exception as e:
        logger.warning(f"LLM共情生成失败: {e}")

    # 降级到模板
    from code.personalization import get_personalized_empathy
    return get_personalized_empathy(state)


async def generate_personalized_objection_response(
    state: dict, objection_type: str, user_msg: str
) -> str:
    """用LLM生成个性化异议回应"""
    try:
        from code.model_router import stream_llm
        from code.personalization import build_user_profile

        profile = build_user_profile(state)
        case = match_case(state)
        case_text = format_case_for_prompt(case)

        collected = []
        for k, label in [("education", "学历"), ("age", "年龄"),
                          ("city", "城市"), ("direction", "方向")]:
            if state.get(k):
                collected.append(f"{label}: {state[k]}")
        info_str = "、".join(collected) if collected else "暂无"

        objection_labels = {
            "objection_consider": "犹豫/再想想",
            "objection_learn": "担心学不会",
            "objection_time": "没时间/太忙",
            "objection_distance": "太远/不方便",
            "objection_institution": "不信任机构",
            "objection_price": "觉得贵",
        }
        obj_label = objection_labels.get(objection_type, "顾虑")

        system_prompt = f"""你是小苏，28岁的IT人才服务顾问。用户表达了{obj_label}的顾虑：
"{user_msg}"

用户背景：{info_str}
决策风格：{profile.get('decision_style', '未知')}
经济压力：{profile.get('economic_pressure', '未知')}

相似案例：
{case_text}

要求：
1. 先共情（1句话），不要说"我理解"这种模板
2. 直接回应用户的核心顾虑，用案例或事实
3. 给出一个明确的行动建议（来试听/看合同/了解详情）
4. 不要出现"培训""学费""保证""一定"等词
5. 控制在80字以内
6. 用口语化表达

直接输出回应话术，不要加任何解释。"""

        reply = ""
        async for token in stream_llm(system_prompt, 0.7, "main"):
            if token:
                reply += token

        if reply.strip():
            logger.info(f"LLM生成异议回应: {reply[:50]}...")
            return reply.strip()

    except Exception as e:
        logger.warning(f"LLM异议回应生成失败: {e}")

    return ""  # 返回空，让调用方使用默认模板


def get_case_for_state(state: dict) -> str:
    """获取当前状态最合适的案例文本"""
    case = match_case(state)
    return format_case_for_prompt(case)
