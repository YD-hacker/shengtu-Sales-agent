"""错误监控与告警模块

企业级交付版新增:
1. LLM熔断告警
2. 合规拦截告警
3. 状态异常告警
4. 未捕获异常告警
5. 告警聚合（同一类告警5分钟内不重复推送）
6. 通过企微Webhook推送
"""
import time
import traceback
from loguru import logger

# 告警冷却：同一类告警5分钟内不重复推送
_alert_cooldown = {}  # alert_key -> last_alert_time
_ALERT_COOLDOWN_SECONDS = 300  # 5分钟


def _should_alert(alert_key: str) -> bool:
    """检查是否应该推送告警（防重复刷屏）"""
    now = time.time()
    last_time = _alert_cooldown.get(alert_key, 0)
    if now - last_time > _ALERT_COOLDOWN_SECONDS:
        _alert_cooldown[alert_key] = now
        return True
    return False


def _send_alert(title: str, content: str, level: str = "warning"):
    """发送告警到企微"""
    if not _should_alert(f"{title}:{level}"):
        logger.debug(f"告警冷却中，跳过: {title}")
        return

    try:
        from code.channel_pusher import _do_post
        level_icon = {"warning": "⚠️", "error": "🔴", "critical": "🚨"}.get(level, "⚠️")
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": f"{level_icon} **{title}**\n\n{content}\n\n> 时间: {time.strftime('%Y-%m-%d %H:%M:%S')}"
            }
        }
        _do_post(payload)
        logger.info(f"告警已推送: {title}")
    except Exception as e:
        logger.error(f"告警推送失败: {e}")


def alert_llm_fuse(fail_count: int):
    """LLM熔断告警"""
    _send_alert(
        "LLM熔断告警",
        f"LLM连续失败{fail_count}次，已触发熔断机制，系统切换为纯模板模式。\n"
        f"影响：用户回复将使用原始模板，不会经过LLM改写。\n"
        f"自动恢复：60秒后自动检测LLM健康状态。",
        level="error"
    )


def alert_compliance_block(user_id: str, node: str, text_preview: str):
    """合规拦截告警"""
    _send_alert(
        "合规拦截告警",
        f"用户: {user_id}\n状态: {node}\n"
        f"被拦截内容: {text_preview}...\n"
        f"已替换为合规话术。",
        level="warning"
    )


def alert_unexpected_error(user_id: str, error_msg: str):
    """未捕获异常告警"""
    _send_alert(
        "系统异常告警",
        f"用户: {user_id}\n异常: {error_msg}\n"
        f"堆栈: {traceback.format_exc()[:200]}",
        level="error"
    )


def alert_state_anomaly(user_id: str, from_state: str, to_state: str, detail: str = ""):
    """状态异常告警"""
    _send_alert(
        "状态异常告警",
        f"用户: {user_id}\n异常跳转: {from_state} -> {to_state}\n{detail}",
        level="warning"
    )


def alert_health_check_failed(component: str, detail: str):
    """健康检查失败告警"""
    _send_alert(
        "健康检查告警",
        f"组件: {component}\n详情: {detail}",
        level="critical"
    )
