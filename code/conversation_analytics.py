"""对话智能分析模块

结构化事件埋点 + 转化漏斗统计 + 话术效果归因 + 对话质量评分。

事件类型：
  conversation_start: 对话开始
  intent_detected: 意图识别结果
  slot_update: 槽位更新
  state_transition: 状态跳转
  objection_handled: 异议处理
  pain_detected: 痛点检测
  trust_changed: 信任变化
  compliance_block: 合规拦截
  conversation_end: 对话结束
"""
import os
import json
import time
import threading
from datetime import datetime
from loguru import logger
from code import DATA_DIR
from code.time_utils import get_beijing_time


# ---- 事件存储 ----
ANALYTICS_DIR = os.path.join(DATA_DIR, "analytics")
os.makedirs(ANALYTICS_DIR, exist_ok=True)

_events_buffer = []
_buffer_lock = threading.Lock()
_FLUSH_INTERVAL = 60  # 60秒刷盘一次
_last_flush = time.time()

# ---- 漏斗阶段定义 ----
FUNNEL_STAGES = [
    "icebreak",
    "qualify",
    "match_campus",
    "show_fee",
    "invite",
    "report_info",
    "completed",
]


def _get_event_file_path() -> str:
    """获取当天的事件文件路径"""
    date_str = get_beijing_time().strftime("%Y-%m-%d")
    return os.path.join(ANALYTICS_DIR, f"events_{date_str}.jsonl")


def record_event(user_id: str, event_type: str, data: dict, session_id: str = ""):
    """记录一个结构化事件"""
    event = {
        "timestamp": get_beijing_time().isoformat(),
        "user_id": user_id,
        "event_type": event_type,
        "session_id": session_id or user_id,
        "data": data,
    }
    with _buffer_lock:
        _events_buffer.append(event)
        # 超过100条或超过刷新间隔，刷盘
        if len(_events_buffer) >= 100:
            _flush_events()


def _flush_events():
    """将缓冲区事件写入文件"""
    global _last_flush
    if not _events_buffer:
        return
    try:
        path = _get_event_file_path()
        with open(path, "a", encoding="utf-8") as f:
            for event in _events_buffer:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        _events_buffer.clear()
        _last_flush = time.time()
    except Exception as e:
        logger.error(f"事件刷盘失败: {e}")


def force_flush():
    """UP-011: 强制刷盘（优雅关闭时调用），确保事件不丢失"""
    with _buffer_lock:
        if _events_buffer:
            logger.info(f"优雅关闭：强制刷盘 {len(_events_buffer)} 条事件")
            _flush_events()


def flush_if_needed():
    """检查是否需要刷盘"""
    global _last_flush
    if time.time() - _last_flush > _FLUSH_INTERVAL:
        with _buffer_lock:
            _flush_events()


# UP-011: 注册优雅关闭处理
import atexit
atexit.register(force_flush)


# ---- 事件记录便捷函数 ----

def log_conversation_start(user_id: str, source: str = "wechat"):
    record_event(user_id, "conversation_start", {"source": source})


def log_intent_detected(user_id: str, intent: str, confidence: float, msg_preview: str):
    record_event(user_id, "intent_detected", {
        "intent": intent,
        "confidence": confidence,
        "msg_preview": msg_preview[:100],
    })


def log_slot_update(user_id: str, slot_name: str, old_value: str, new_value: str):
    record_event(user_id, "slot_update", {
        "slot": slot_name,
        "old": old_value,
        "new": new_value,
    })


def log_state_transition(user_id: str, old_state: str, new_state: str, intent: str, trust: int, lead_score: int):
    record_event(user_id, "state_transition", {
        "old_state": old_state,
        "new_state": new_state,
        "trigger_intent": intent,
        "trust": trust,
        "lead_score": lead_score,
    })


def log_objection_handled(user_id: str, objection_type: str, template_id: str, round_num: int, result: str):
    record_event(user_id, "objection_handled", {
        "objection_type": objection_type,
        "template_id": template_id,
        "round": round_num,
        "result": result,  # "resolved" / "continued" / "escalated"
    })


def log_pain_detected(user_id: str, pain_tags: list, intensity: int):
    record_event(user_id, "pain_detected", {
        "pain_tags": pain_tags,
        "intensity": intensity,
    })


def log_trust_changed(user_id: str, action: str, delta: int, old_val: int, new_val: int):
    record_event(user_id, "trust_changed", {
        "action": action,
        "delta": delta,
        "old": old_val,
        "new": new_val,
    })


def log_compliance_block(user_id: str, state: str, blocked_text: str, reason: str):
    record_event(user_id, "compliance_block", {
        "state": state,
        "blocked_text": blocked_text[:100],
        "reason": reason,
    })


def log_conversation_end(user_id: str, final_state: str, total_rounds: int, duration_seconds: float, slots_filled: int):
    record_event(user_id, "conversation_end", {
        "final_state": final_state,
        "total_rounds": total_rounds,
        "duration_seconds": duration_seconds,
        "slots_filled": slots_filled,
    })


def log_token_usage(user_id: str, model: str, prompt_tokens: int, completion_tokens: int, cost: float, latency_ms: float):
    """UP-110: Token消耗记录"""
    record_event(user_id, "token_usage", {
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "estimated_cost_usd": round(cost, 6),
        "latency_ms": round(latency_ms, 1),
    })


def log_llm_call(user_id: str, model: str, success: bool, latency_ms: float, fallback: bool):
    record_event(user_id, "llm_call", {
        "model": model,
        "success": success,
        "latency_ms": latency_ms,
        "fallback": fallback,
    })


def log_human_handoff(user_id: str, reason: str, level: int, context: dict):
    record_event(user_id, "human_handoff", {
        "reason": reason,
        "level": level,
        "context": context,
    })


def log_experiment_exposure(user_id: str, experiment_name: str, variant: str):
    record_event(user_id, "experiment_exposure", {
        "experiment": experiment_name,
        "variant": variant,
    })


# ---- 转化漏斗分析 ----

def get_funnel_stats(date_str: str = None) -> dict:
    """获取转化漏斗统计数据"""
    if date_str is None:
        date_str = get_beijing_time().strftime("%Y-%m-%d")

    event_file = os.path.join(ANALYTICS_DIR, f"events_{date_str}.jsonl")
    if not os.path.exists(event_file):
        return {"error": f"No data for {date_str}"}

    # 统计每个阶段的用户数
    stage_users = {stage: set() for stage in FUNNEL_STAGES}

    with open(event_file, "r", encoding="utf-8") as f:
        for line in f:
            try:
                event = json.loads(line.strip())
                if event["event_type"] == "state_transition":
                    new_state = event["data"]["new_state"]
                    user_id = event["user_id"]
                    if new_state in stage_users:
                        stage_users[new_state].add(user_id)
            except (json.JSONDecodeError, KeyError):
                continue

    # 计算漏斗
    total_users = set()
    for users in stage_users.values():
        total_users.update(users)

    funnel = []
    for stage in FUNNEL_STAGES:
        count = len(stage_users[stage])
        rate = (count / len(total_users) * 100) if total_users else 0
        funnel.append({
            "stage": stage,
            "users": count,
            "rate": round(rate, 1),
        })

    return {
        "date": date_str,
        "total_users": len(total_users),
        "funnel": funnel,
    }


# ---- 话术效果归因 ----

def get_objection_stats(date_str: str = None) -> dict:
    """获取异议处理效果统计"""
    if date_str is None:
        date_str = get_beijing_time().strftime("%Y-%m-%d")

    event_file = os.path.join(ANALYTICS_DIR, f"events_{date_str}.jsonl")
    if not os.path.exists(event_file):
        return {}

    objection_data = {}

    with open(event_file, "r", encoding="utf-8") as f:
        for line in f:
            try:
                event = json.loads(line.strip())
                if event["event_type"] == "objection_handled":
                    data = event["data"]
                    key = data["objection_type"]
                    if key not in objection_data:
                        objection_data[key] = {"total": 0, "resolved": 0}
                    objection_data[key]["total"] += 1
                    if data.get("result") == "resolved":
                        objection_data[key]["resolved"] += 1
            except (json.JSONDecodeError, KeyError):
                continue

    stats = {}
    for key, val in objection_data.items():
        stats[key] = {
            "total": val["total"],
            "resolved": val["resolved"],
            "resolution_rate": round(val["resolved"] / val["total"] * 100, 1) if val["total"] > 0 else 0,
        }

    return stats


# ---- 对话质量评分 ----

def calculate_conversation_quality(user_id: str, state: dict, history: list) -> dict:
    """计算对话质量评分"""
    scores = {}

    # 1. 意图识别准确率（基于用户纠正次数）
    correction_count = state.get("_correction_count", 0)
    total_rounds = len(history)
    if total_rounds > 0:
        accuracy = max(0, 100 - (correction_count / total_rounds * 100))
    else:
        accuracy = 100
    scores["intent_accuracy"] = round(accuracy, 1)

    # 2. 信息收集完整度
    required_slots = ["education", "age", "graduated_year", "city", "direction"]
    filled = sum(1 for s in required_slots if state.get(s))
    scores["slot_completeness"] = round(filled / len(required_slots) * 100, 1)

    # 3. 异议处理成功率
    objection_attempts = state.get("_objection_total", 0)
    objection_resolved = state.get("_objection_resolved", 0)
    if objection_attempts > 0:
        scores["objection_success_rate"] = round(objection_resolved / objection_attempts * 100, 1)
    else:
        scores["objection_success_rate"] = 100.0

    # 4. 对话效率（轮次vs进展）
    current_node = state.get("current_node", "icebreak")
    try:
        stage_index = FUNNEL_STAGES.index(current_node)
    except ValueError:
        stage_index = 0
    if total_rounds > 0:
        efficiency = min(100, round((stage_index + 1) / total_rounds * 100 * 2, 1))
    else:
        efficiency = 0
    scores["efficiency"] = efficiency

    # 综合分
    scores["overall"] = round(
        scores["intent_accuracy"] * 0.3
        + scores["slot_completeness"] * 0.3
        + scores["objection_success_rate"] * 0.2
        + scores["efficiency"] * 0.2,
        1,
    )

    return scores


# ---- UP-113: 异常对话实时检测 ----

def detect_abnormal_conversation(user_id: str, state: dict, history: list, current_reply: str) -> list:
    """检测异常对话模式，返回告警列表"""
    alerts = []

    # 1. 循环对话检测：用户同样问题出现3次以上
    if history and len(history) >= 4:
        recent_user_msgs = [h.get("user", "") for h in history[-4:]]
        from collections import Counter
        msg_counts = Counter(recent_user_msgs)
        for msg, count in msg_counts.items():
            if count >= 3 and len(msg) > 3:
                alerts.append({
                    "type": "loop_conversation",
                    "severity": "warning",
                    "detail": f"用户重复相同问题{count}次: {msg[:50]}"
                })
                logger.warning(f"[{user_id}] 循环对话检测: {msg[:50]} 出现{count}次")

    # 2. 对话溢出检测：AI回复长度超过500字
    if current_reply and len(current_reply) > 500:
        alerts.append({
            "type": "response_overflow",
            "severity": "warning",
            "detail": f"AI回复过长: {len(current_reply)}字符"
        })
        logger.warning(f"[{user_id}] 对话溢出检测: 回复{len(current_reply)}字符")

    # 3. 转化倒退检测
    current_node = state.get("current_node", "")
    prev_node = state.get("_prev_node", "")
    forward_path = ["icebreak", "qualify", "match_campus", "show_fee", "invite", "report_info", "completed"]
    if prev_node and current_node:
        try:
            prev_idx = forward_path.index(prev_node)
            curr_idx = forward_path.index(current_node)
            if curr_idx < prev_idx:
                alerts.append({
                    "type": "conversion_regression",
                    "severity": "info",
                    "detail": f"转化倒退: {prev_node} -> {current_node}"
                })
                logger.info(f"[{user_id}] 转化倒退: {prev_node} -> {current_node}")
        except ValueError:
            pass

    # 发送告警（如有）
    if alerts:
        try:
            from code.error_monitor import _send_alert
            for alert in alerts:
                if alert["severity"] == "warning":
                    _send_alert(f"异常对话: {alert['type']}", str(alert), alert["severity"])
        except Exception:
            pass

    return alerts


# ---- 仪表盘数据 ----

def get_dashboard_data(date_str: str = None) -> dict:
    """获取仪表盘所需的所有统计数据"""
    return {
        "funnel": get_funnel_stats(date_str),
        "objections": get_objection_stats(date_str),
        "timestamp": get_beijing_time().isoformat(),
    }
