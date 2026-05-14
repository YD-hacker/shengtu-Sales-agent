"""数据分析仪表盘

功能：
1. 转化漏斗可视化
2. 意图分布统计
3. 异议处理效果分析
4. 用户画像分布
5. 实时运营数据
"""
import os
import json
from datetime import datetime, timedelta
from loguru import logger
from code import DATA_DIR


def get_dashboard_data():
    """获取仪表盘完整数据"""
    events = _load_events()

    return {
        "funnel": _build_funnel(events),
        "conversion_rates": _calc_conversion_rates(events),
        "intent_distribution": _calc_intent_distribution(events),
        "objection_stats": _calc_objection_stats(events),
        "trust_distribution": _calc_trust_distribution(),
        "lead_grade_distribution": _calc_lead_grade_distribution(),
        "today_summary": _get_today_summary(events),
        "timestamp": datetime.now().isoformat()
    }


def get_funnel_data():
    """获取转化漏斗数据"""
    events = _load_events()
    funnel = _build_funnel(events)
    rates = _calc_conversion_rates(events)
    return {"funnel": funnel, "conversion_rates": rates}


def _load_events():
    """加载事件日志"""
    events = []
    analytics_dir = os.path.join(DATA_DIR, "analytics")
    if not os.path.exists(analytics_dir):
        return events

    today = datetime.now().strftime("%Y%m%d")
    for filename in os.listdir(analytics_dir):
        if filename.endswith(".json") and today in filename:
            filepath = os.path.join(analytics_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        events.extend(data)
                    elif isinstance(data, dict) and "events" in data:
                        events.extend(data["events"])
            except Exception as e:
                logger.debug(f"加载事件文件失败 {filename}: {e}")

    return events


def _build_funnel(events):
    """构建转化漏斗"""
    funnel = {
        "icebreak": 0,
        "qualify": 0,
        "match_campus": 0,
        "show_fee": 0,
        "invite": 0,
        "report_info": 0,
        "completed": 0
    }

    for event in events:
        if event.get("event_type") == "state_transition":
            new_state = event.get("data", {}).get("new_state", "")
            if new_state in funnel:
                funnel[new_state] += 1

    return funnel


def _calc_conversion_rates(events):
    """计算转化率"""
    funnel = _build_funnel(events)
    stages = list(funnel.keys())
    rates = {}

    for i in range(len(stages) - 1):
        from_stage = stages[i]
        to_stage = stages[i + 1]
        if funnel[from_stage] > 0:
            rate = round(funnel[to_stage] / funnel[from_stage] * 100, 1)
            rates[f"{from_stage}_to_{to_stage}"] = rate
        else:
            rates[f"{from_stage}_to_{to_stage}"] = 0.0

    # 整体转化率
    if funnel["icebreak"] > 0:
        rates["overall"] = round(funnel["completed"] / funnel["icebreak"] * 100, 1)
    else:
        rates["overall"] = 0.0

    return rates


def _calc_intent_distribution(events):
    """计算意图分布"""
    distribution = {}
    for event in events:
        if event.get("event_type") == "intent_detected":
            intent = event.get("data", {}).get("intent", "unknown")
            distribution[intent] = distribution.get(intent, 0) + 1

    # 按数量排序
    return dict(sorted(distribution.items(), key=lambda x: x[1], reverse=True))


def _calc_objection_stats(events):
    """计算异议处理效果"""
    stats = {}
    for event in events:
        if event.get("event_type") == "objection_handled":
            data = event.get("data", {})
            obj_type = data.get("intent", "unknown")
            outcome = data.get("outcome", "unknown")

            if obj_type not in stats:
                stats[obj_type] = {"total": 0, "resolved": 0, "escalated": 0}

            stats[obj_type]["total"] += 1
            if outcome == "resolved":
                stats[obj_type]["resolved"] += 1
            elif outcome == "escalated":
                stats[obj_type]["escalated"] += 1

    # 计算解决率
    for obj_type in stats:
        total = stats[obj_type]["total"]
        if total > 0:
            stats[obj_type]["resolution_rate"] = round(
                stats[obj_type]["resolved"] / total * 100, 1
            )
        else:
            stats[obj_type]["resolution_rate"] = 0.0

    return stats


def _calc_trust_distribution():
    """计算信任度分布"""
    users_dir = os.path.join(DATA_DIR, "users")
    if not os.path.exists(users_dir):
        return {}

    distribution = {"low_0_30": 0, "medium_30_50": 0, "high_50_70": 0, "very_high_70_100": 0}

    for filename in os.listdir(users_dir):
        if filename.endswith(".json") and not filename.endswith("_history.json"):
            try:
                filepath = os.path.join(users_dir, filename)
                with open(filepath, "r", encoding="utf-8") as f:
                    state = json.load(f)
                    trust = state.get("trust_level", 50)
                    if trust < 30:
                        distribution["low_0_30"] += 1
                    elif trust < 50:
                        distribution["medium_30_50"] += 1
                    elif trust < 70:
                        distribution["high_50_70"] += 1
                    else:
                        distribution["very_high_70_100"] += 1
            except Exception:
                pass

    return distribution


def _calc_lead_grade_distribution():
    """计算线索等级分布"""
    users_dir = os.path.join(DATA_DIR, "users")
    if not os.path.exists(users_dir):
        return {}

    distribution = {"S": 0, "A": 0, "B": 0, "C": 0}

    for filename in os.listdir(users_dir):
        if filename.endswith(".json") and not filename.endswith("_history.json"):
            try:
                filepath = os.path.join(users_dir, filename)
                with open(filepath, "r", encoding="utf-8") as f:
                    state = json.load(f)
                    score = state.get("lead_score", 0)
                    if score >= 80:
                        distribution["S"] += 1
                    elif score >= 60:
                        distribution["A"] += 1
                    elif score >= 40:
                        distribution["B"] += 1
                    else:
                        distribution["C"] += 1
            except Exception:
                pass

    return distribution


def _get_today_summary(events):
    """获取今日摘要"""
    unique_users = set()
    total_messages = 0
    total_intents = 0

    for event in events:
        user_id = event.get("user_id", "")
        if user_id:
            unique_users.add(user_id)
        if event.get("event_type") == "intent_detected":
            total_intents += 1
        if event.get("event_type") in ("conversation_start", "state_transition"):
            total_messages += 1

    return {
        "active_users": len(unique_users),
        "total_messages": total_messages,
        "total_intents": total_intents,
        "avg_messages_per_user": round(total_messages / max(len(unique_users), 1), 1)
    }
