"""人工协作模块

三级协作模型、上下文传递、销售话术建议、人工介入感知。
AI和真人销售无缝配合。
"""
from loguru import logger


# ---- 协作级别 ----
HANDOFF_LEVELS = {
    1: "observe",      # AI继续，人工旁观
    2: "co_pilot",     # AI辅助，人工主导
    3: "full_handoff", # 完全人工接管
}

# ---- 人工跟进中的用户 ----
_human_active_users = {}  # user_id -> {"sales_id": str, "started_at": str, "level": int}


def build_handoff_context(state: dict, lead_score: int) -> dict:
    """构建转人工时的上下文信息"""
    # 基本信息
    basic_info = {}
    for key, label in [
        ("name", "姓名"), ("phone", "电话"), ("education", "学历"),
        ("age", "年龄"), ("city", "城市"), ("direction", "方向"),
        ("graduated_year", "毕业年份"), ("major", "专业"),
    ]:
        if state.get(key):
            basic_info[label] = state[key]

    # 对话状态
    current_node = state.get("current_node", "icebreak")
    trust = state.get("trust_level", 50)

    # 异议历史
    objection_history = []
    for key in ["objection_consider", "objection_learn", "objection_time",
                 "objection_distance", "objection_institution", "objection_price"]:
        count = state.get(f"_{key}_count", 0)
        if count > 0:
            objection_history.append({"type": key, "count": count})

    # 痛点
    pain_points = state.get("pain_points", [])

    # 生成建议动作
    suggestion = _generate_action_suggestion(state, lead_score, current_node, objection_history)

    return {
        "basic_info": basic_info,
        "current_stage": current_node,
        "lead_score": lead_score,
        "trust": trust,
        "objection_history": objection_history,
        "pain_points": pain_points,
        "suggestion": suggestion,
    }


def _generate_action_suggestion(state: dict, lead_score: int, current_node: str, objections: list) -> str:
    """根据对话状态生成建议动作"""
    suggestions = []

    if current_node == "show_fee":
        suggestions.append("用户在费用展示阶段")
        if any(o["type"] == "objection_price" for o in objections):
            suggestions.append("已表达价格顾虑，建议重点解释分期方案和零风险承诺")
        suggestions.append("建议确认试听时间")

    elif current_node == "invite":
        suggestions.append("用户在邀约阶段")
        suggestions.append("建议锁定具体到场时间")
        if lead_score >= 70:
            suggestions.append("高价值线索，可提供车费报销")

    elif current_node == "report_info":
        suggestions.append("用户同意试听，正在收集报备信息")
        missing = []
        if not state.get("name"):
            missing.append("姓名")
        if not state.get("phone"):
            missing.append("电话")
        if missing:
            suggestions.append(f"还缺{'、'.join(missing)}，需要补全")

    elif current_node == "qualify":
        suggestions.append("用户在资质筛查阶段")
        missing = []
        for key, label in [("education", "学历"), ("age", "年龄"),
                            ("graduated_year", "毕业年份"), ("city", "城市"),
                            ("direction", "方向")]:
            if not state.get(key):
                missing.append(label)
        if missing:
            suggestions.append(f"还缺{'、'.join(missing[:2])}")

    if objections:
        types = [o["type"].replace("objection_", "") for o in objections]
        suggestions.append(f"已处理异议：{'、'.join(types)}")

    if pain_points := state.get("pain_points", []):
        suggestions.append(f"用户痛点：{'、'.join(pain_points)}")

    return "；".join(suggestions) if suggestions else "无特殊建议"


def format_handoff_message(context: dict) -> str:
    """格式化转人工时推送给销售的消息"""
    lines = ["### AI转人工 - 客户信息"]

    # 基本信息
    info = context.get("basic_info", {})
    for label, value in info.items():
        lines.append(f"- **{label}**：{value}")

    # 当前状态
    lines.append(f"- **当前阶段**：{context.get('current_stage', '未知')}")
    lines.append(f"- **线索分**：{context.get('lead_score', 0)}")
    lines.append(f"- **信任分**：{context.get('trust', 50)}")

    # 痛点
    pains = context.get("pain_points", [])
    if pains:
        lines.append(f"- **痛点**：{'、'.join(pains)}")

    # 异议历史
    objections = context.get("objection_history", [])
    if objections:
        obj_str = "、".join(f"{o['type'].replace('objection_', '')}({o['count']}次)" for o in objections)
        lines.append(f"- **已处理异议**：{obj_str}")

    # 建议动作
    suggestion = context.get("suggestion", "")
    if suggestion:
        lines.append(f"\n### 建议动作\n{suggestion}")

    return "\n".join(lines)


def should_send_observe_alert(state: dict, lead_score: int, intent: str) -> bool:
    """判断是否需要发送旁观提醒（级别1）"""
    # S级用户在关键节点
    if lead_score >= 80 and state.get("current_node") in ("show_fee", "invite", "report_info"):
        return True
    # 用户主动问费用
    if intent == "fee_intent" and lead_score >= 60:
        return True
    return False


def mark_user_human_active(user_id: str, sales_id: str, level: int):
    """标记用户为人工跟进中"""
    from code.time_utils import get_beijing_time
    _human_active_users[user_id] = {
        "sales_id": sales_id,
        "started_at": get_beijing_time().isoformat(),
        "level": level,
    }
    logger.info(f"用户 {user_id} 标记为人工跟进 (level={level}, sales={sales_id})")


def is_user_human_active(user_id: str) -> bool:
    """检查用户是否在人工跟进中"""
    return user_id in _human_active_users


def get_human_active_info(user_id: str) -> dict:
    """获取人工跟进信息"""
    return _human_active_users.get(user_id, {})


def mark_user_ai_resumed(user_id: str):
    """标记用户恢复AI跟进"""
    if user_id in _human_active_users:
        del _human_active_users[user_id]
        logger.info(f"用户 {user_id} 恢复AI跟进")


def check_stale_human_followup(timeout_hours: int = 48) -> list:
    """检查超时的人工跟进，应该恢复AI跟进"""
    from code.time_utils import get_beijing_time
    from datetime import datetime, timedelta

    stale = []
    now = get_beijing_time()

    for user_id, info in _human_active_users.items():
        try:
            started = datetime.fromisoformat(info["started_at"])
            if (now - started).total_seconds() > timeout_hours * 3600:
                stale.append(user_id)
        except Exception:
            stale.append(user_id)

    return stale


def generate_sales_suggestion(state: dict, lead_score: int, user_msg: str, intent: str) -> str:
    """为销售生成实时话术建议"""
    current_node = state.get("current_node", "icebreak")

    # 价格异议
    if intent == "objection_price":
        if lead_score >= 70:
            return "推荐：强调零风险，先工作后付费。备选：提供车费报销增加诚意。"
        return "推荐：解释分期方案（前两月1毛/月）。备选：邀请来校区看合同。"

    # 犹豫
    if intent == "objection_consider":
        return "推荐：用相似背景案例打消顾虑。备选：提出试听一天不急决定。"

    # 学不会
    if intent == "objection_learn":
        return "推荐：强调零基础从打字教起。备选：提到学不会不收钱。"

    # 费用意图
    if intent == "fee_intent":
        if current_node in ("icebreak", "qualify"):
            return "注意：用户提前问费用，可能在网上看到过价格。建议先了解情况再报价。"
        return "推荐：透明化费用，强调入职才付费。"

    # 高价值用户确认
    if intent == "confirm" and lead_score >= 70:
        return "高价值用户确认！建议立即锁定到场时间，提供住宿安排。"

    return ""
