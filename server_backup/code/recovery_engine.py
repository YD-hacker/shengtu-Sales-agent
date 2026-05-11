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
    reason = analyze_rejection_reason(history, state)
    strategy = RECOVERY_STRATEGIES.get(reason, RECOVERY_STRATEGIES["unknown"])

    if recovery_attempt >= strategy["max_attempts"]:
        return {"should_recover": False, "reason": "超过该原因最大挽回次数"}

    return {
        "should_recover": True,
        "reason": reason,
        "strategy": strategy,
        "recovery_attempt": recovery_attempt + 1
    }


def analyze_rejection_reason(history, state=None):
    """分析拒绝原因，融合用户画像"""
    # 关键词匹配
    keyword_result = "unknown"
    if history:
        recent_msgs = [h.get("user", "") for h in history[-5:]]
        for msg in recent_msgs:
            msg_lower = msg.lower()
            if any(w in msg_lower for w in ["贵", "没钱", "付不起", "太贵", "价格", "费用高"]):
                keyword_result = "price"
                break
            elif any(w in msg_lower for w in ["远", "不方便", "外地", "距离"]):
                keyword_result = "distance"
                break
            elif any(w in msg_lower for w in ["没时间", "忙", "走不开", "加班", "请假"]):
                keyword_result = "time"
                break
            elif any(w in msg_lower for w in ["考虑", "想想", "再看看", "犹豫", "不急"]):
                keyword_result = "hesitation"
                break
            elif any(w in msg_lower for w in ["骗", "不信任", "不靠谱", "怀疑", "假的"]):
                keyword_result = "trust"
                break

    # 如果关键词没匹配到，用画像辅助判断
    if keyword_result == "unknown" and state:
        try:
            from code.user_profiler import build_deep_profile
            profile = build_deep_profile(state, history or [])
            if profile.get("economic_pressure") == "high":
                keyword_result = "price"
            elif profile.get("decision_style") == "hesitant":
                keyword_result = "hesitation"
            elif profile.get("emotional_state") == "frustrated":
                keyword_result = "trust"
        except Exception:
            pass

    return keyword_result


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
    """调度挽回任务，支持持久化（重启后恢复）"""
    try:
        from code.scheduler import scheduler
        from code.memory_manager import load_state, save_state

        delay_hours = get_recovery_delay(reason)
        hook = get_recovery_hook(reason, state)
        run_time = get_beijing_time() + timedelta(hours=delay_hours)

        # 持久化挽回任务信息到用户状态（用于重启后恢复）
        state["_pending_recovery"] = {
            "reason": reason,
            "hook": hook,
            "run_time": run_time.isoformat(),
            "scheduled_at": get_beijing_time().isoformat()
        }
        save_state(user_id, state)

        def recovery_task():
            try:
                current_state = load_state(user_id)

                # 检查是否已经恢复对话或已完成
                if current_state.get("current_node") == "completed":
                    logger.info(f"[{user_id}] 挽回取消：用户已完成")
                    current_state.pop("_pending_recovery", None)
                    save_state(user_id, current_state)
                    return

                # 检查是否已有新对话
                last_active = current_state.get("_last_active", "")
                if last_active:
                    try:
                        last_time = datetime.fromisoformat(last_active)
                        if (get_beijing_time() - last_time).total_seconds() < 3600:
                            logger.info(f"[{user_id}] 挽回取消：用户最近活跃")
                            current_state.pop("_pending_recovery", None)
                            save_state(user_id, current_state)
                            return
                    except Exception:
                        pass

                # 记录挽回尝试
                current_state["_recovery_attempt"] = current_state.get("_recovery_attempt", 0) + 1
                current_state["_last_recovery_time"] = get_beijing_time().isoformat()
                current_state["_recovery_reason"] = reason
                current_state.pop("_pending_recovery", None)
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


def restore_pending_recoveries():
    """启动时恢复未执行的挽回任务（含去重检查）"""
    try:
        from code.memory_manager import get_all_user_ids, load_state, save_state
        user_ids = get_all_user_ids()
        restored = 0
        for uid in user_ids:
            st = load_state(uid)
            if not isinstance(st, dict):
                continue
            pending = st.get("_pending_recovery")
            if not pending:
                continue
            run_time_str = pending.get("run_time")
            if not run_time_str:
                continue
            try:
                run_time = datetime.fromisoformat(run_time_str)
                now = get_beijing_time()

                # 去重：如果用户已完成或最近活跃，跳过
                if st.get("current_node") == "completed":
                    st.pop("_pending_recovery", None)
                    save_state(uid, st)
                    continue

                if run_time > now:
                    # 任务还未到执行时间，重新调度
                    reason = pending.get("reason", "unknown")
                    schedule_recovery(uid, reason, st)
                    restored += 1
                else:
                    # 任务已过期，清除
                    st.pop("_pending_recovery", None)
                    save_state(uid, st)
            except Exception:
                pass
        if restored > 0:
            logger.info(f"恢复了{restored}个未执行的挽回任务")
    except Exception as e:
        logger.error(f"恢复挽回任务失败: {e}")


def get_recovery_stats(state):
    """获取挽回统计"""
    return {
        "recovery_attempt": state.get("_recovery_attempt", 0),
        "last_recovery_time": state.get("_last_recovery_time"),
        "recovery_reason": state.get("_recovery_reason"),
        "reject_count": state.get("_reject_count", 0)
    }
