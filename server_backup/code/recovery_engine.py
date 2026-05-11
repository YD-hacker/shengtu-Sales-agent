"""对话挽回引擎

功能：
1. 智能判断是否应该挽回
2. 分析拒绝原因
3. 生成挽回策略
4. 调度挽回任务
"""
import json
from datetime import datetime, timedelta
from loguru import logger
from code.time_utils import get_beijing_time


# 挽回策略配置
RECOVERY_STRATEGIES = {
    "price": {
        "approach": "强调零风险，先工作后付费",
        "hooks": [
            "费用的事我给你算笔账——前两月每月才1毛钱，入职后才开始付，你零风险。",
            "我发你一份费用明细，你看看分期方案，不影响征信的那种。",
        ],
        "delay_hours": 24,
        "max_attempts": 2
    },
    "distance": {
        "approach": "强调住宿免费，安排最近校区",
        "hooks": [
            "你告诉我你在哪，我帮你算下最近的校区，住宿我全包，拎包入住。",
            "高铁票我都能报销，你先来看一眼，不满意随时走。",
        ],
        "delay_hours": 48,
        "max_attempts": 2
    },
    "time": {
        "approach": "提供灵活方案",
        "hooks": [
            "我们有晚班和周末班，我发你课程表，你看看哪个时间段能配合。",
            "忙说明你在努力生活，但忙一阵子换以后轻松，值得考虑下。",
        ],
        "delay_hours": 72,
        "max_attempts": 2
    },
    "hesitation": {
        "approach": "用案例打消顾虑",
        "hooks": [
            "我发你几个跟情况差不多的学员案例，你看完再决定，不急。",
            "犹豫很正常，我发你一份零风险方案，你看完心里就有数了。",
        ],
        "delay_hours": 48,
        "max_attempts": 3
    },
    "trust": {
        "approach": "提供证明材料",
        "hooks": [
            "我发你我们的企业资质和学员合同模板，白纸黑字最靠谱。",
            "你可以来校区跟在学的学员聊几句，眼见为实。",
        ],
        "delay_hours": 24,
        "max_attempts": 2
    },
    "unknown": {
        "approach": "轻触问候",
        "hooks": [
            "最近忙吗？有什么想了解的随时找我。",
            "之前聊的你考虑得怎么样了？有新想法随时说。",
        ],
        "delay_hours": 72,
        "max_attempts": 1
    }
}


def should_attempt_recovery(state, intent, history):
    """判断是否应该尝试挽回"""
    reject_count = state.get("_reject_count", 0)
    lead_score = state.get("lead_score", 50)
    recovery_attempt = state.get("_recovery_attempt", 0)

    # 高价值用户：更多挽回机会
    if lead_score >= 80:
        max_rejects = 5
    elif lead_score >= 60:
        max_rejects = 4
    elif lead_score >= 40:
        max_rejects = 3
    else:
        max_rejects = 2

    if reject_count >= max_rejects:
        return {"should_recover": False, "reason": "超过最大拒绝次数"}

    # 检查挽回尝试次数
    reason = analyze_rejection_reason(history)
    strategy = RECOVERY_STRATEGIES.get(reason, RECOVERY_STRATEGIES["unknown"])

    if recovery_attempt >= strategy["max_attempts"]:
        return {"should_recover": False, "reason": "超过该原因最大挽回次数"}

    return {
        "should_recover": True,
        "reason": reason,
        "strategy": strategy,
        "recovery_attempt": recovery_attempt + 1
    }


def analyze_rejection_reason(history):
    """分析拒绝原因"""
    if not history:
        return "unknown"

    recent_msgs = [h.get("user", "") for h in history[-5:]]

    for msg in recent_msgs:
        msg_lower = msg.lower()
        if any(w in msg_lower for w in ["贵", "没钱", "付不起", "太贵", "价格", "费用高"]):
            return "price"
        elif any(w in msg_lower for w in ["远", "不方便", "外地", "距离"]):
            return "distance"
        elif any(w in msg_lower for w in ["没时间", "忙", "走不开", "加班", "请假"]):
            return "time"
        elif any(w in msg_lower for w in ["考虑", "想想", "再看看", "犹豫", "不急"]):
            return "hesitation"
        elif any(w in msg_lower for w in ["骗", "不信任", "不靠谱", "怀疑", "假的"]):
            return "trust"

    return "unknown"


def get_recovery_hook(reason, state=None):
    """获取挽回话术"""
    strategy = RECOVERY_STRATEGIES.get(reason, RECOVERY_STRATEGIES["unknown"])
    hooks = strategy["hooks"]

    # 根据用户状态选择话术
    if state and state.get("lead_score", 0) >= 80:
        # 高价值用户：更个性化
        return hooks[0] if hooks else "有什么想了解的随时找我。"
    else:
        # 普通用户：标准话术
        return hooks[-1] if hooks else "有什么想了解的随时找我。"


def get_recovery_delay(reason):
    """获取挽回延迟时间（小时）"""
    strategy = RECOVERY_STRATEGIES.get(reason, RECOVERY_STRATEGIES["unknown"])
    return strategy["delay_hours"]


def schedule_recovery(user_id, reason, state):
    """调度挽回任务"""
    try:
        from code.scheduler import scheduler
        from code.memory_manager import load_state, save_state

        delay_hours = get_recovery_delay(reason)
        hook = get_recovery_hook(reason, state)

        def recovery_task():
            try:
                current_state = load_state(user_id)

                # 检查是否已经恢复对话或已完成
                if current_state.get("current_node") == "completed":
                    logger.info(f"[{user_id}] 挽回取消：用户已完成")
                    return

                # 检查是否已有新对话
                last_active = current_state.get("_last_active", "")
                if last_active:
                    try:
                        last_time = datetime.fromisoformat(last_active)
                        if (get_beijing_time() - last_time).total_seconds() < 3600:
                            logger.info(f"[{user_id}] 挽回取消：用户最近活跃")
                            return
                    except Exception:
                        pass

                # 记录挽回尝试
                current_state["_recovery_attempt"] = current_state.get("_recovery_attempt", 0) + 1
                current_state["_last_recovery_time"] = get_beijing_time().isoformat()
                current_state["_recovery_reason"] = reason
                save_state(user_id, current_state)

                # 推送挽回消息（通过企微通道）
                try:
                    from code.channel_pusher import push_message
                    push_message(user_id, hook)
                    logger.info(f"[{user_id}] 挽回消息已发送: {reason}")
                except Exception as e:
                    logger.warning(f"[{user_id}] 挽回消息发送失败: {e}")

            except Exception as e:
                logger.error(f"挽回任务执行失败: {e}")

        # 调度延迟任务
        run_time = get_beijing_time() + timedelta(hours=delay_hours)
        scheduler.add_job(
            recovery_task,
            'date',
            run_date=run_time,
            id=f"recovery_{user_id}_{int(run_time.timestamp())}",
            replace_existing=True
        )

        logger.info(f"[{user_id}] 挽回任务已调度: {reason}, {delay_hours}小时后执行")
        return True

    except Exception as e:
        logger.error(f"调度挽回任务失败: {e}")
        return False


def get_recovery_stats(state):
    """获取挽回统计"""
    return {
        "recovery_attempt": state.get("_recovery_attempt", 0),
        "last_recovery_time": state.get("_last_recovery_time"),
        "recovery_reason": state.get("_recovery_reason"),
        "reject_count": state.get("_reject_count", 0)
    }
