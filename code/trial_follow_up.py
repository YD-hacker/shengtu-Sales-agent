"""试听跟进调度 - 修复版

主要修复:
1. 移除对 app 模块的循环导入，直接使用 code.scheduler
2. 修复 datetime.now() 未使用北京时间
3. 移除对 dateutil 的依赖
4. 增加 visit_time 持久化
"""
import yaml
from datetime import datetime, timedelta
from loguru import logger
from code.channel_pusher import send_trial_reminder
from code.memory_manager import load_state, save_state
from code.time_utils import get_beijing_time, BEIJING_TZ
from code import TRIAL_CFG_FILE

with open(TRIAL_CFG_FILE, encoding="utf-8") as f:
    CFG = yaml.safe_load(f)["trial_follow_up"]


def schedule_trial_follow_up(scheduler_instance, user_id, appointment_time):
    """安排试听跟进任务"""
    if appointment_time.tzinfo is not None:
        appt_local = appointment_time.astimezone(BEIJING_TZ).replace(tzinfo=None)
    else:
        appt_local = appointment_time

    # 保存 visit_time 到用户状态
    state = load_state(user_id)
    state["visit_time"] = appt_local.isoformat()
    save_state(user_id, state)

    # 1. 到访当天18:30发回访问卷
    follow_up_time = appt_local.replace(hour=18, minute=30, second=0, microsecond=0)
    now = get_beijing_time().replace(tzinfo=None)
    if follow_up_time <= now:
        follow_up_time = now.replace(hour=18, minute=30, second=0, microsecond=0) + timedelta(days=1)

    scheduler_instance.add_job(
        func=send_trial_questionnaire,
        trigger='date',
        run_date=follow_up_time,
        args=[user_id],
        id=f'trial_q_{user_id}',
        replace_existing=True
    )
    logger.info(f"已安排回访问卷: user={user_id}, time={follow_up_time}")

    # 2. 3天后检查是否到访
    check_time = appt_local + timedelta(days=3)
    scheduler_instance.add_job(
        func=check_attendance_and_follow,
        trigger='date',
        run_date=check_time,
        args=[user_id, appt_local],
        id=f'trial_chk_{user_id}',
        replace_existing=True
    )
    logger.info(f"已安排到访检查: user={user_id}, time={check_time}")


def send_trial_questionnaire(user_id):
    """发送试听回访问卷"""
    send_trial_reminder(user_id, CFG.get("questionnaire", "今天试听感觉咋样？"))
    state = load_state(user_id)
    state["questionnaire_sent"] = True
    save_state(user_id, state)


def check_attendance_and_follow(user_id, appt_local):
    """检查到访情况并跟进"""
    state = load_state(user_id)
    visited = state.get("visit_status") == "visited"

    if not visited:
        send_trial_reminder(user_id, CFG.get("no_show_follow_up", "兄弟，今天没看到你过来，时间不方便可以改到周末。"))
        state["second_invite_sent"] = True
        save_state(user_id, state)

        lost_time = get_beijing_time().replace(tzinfo=None) + timedelta(days=3)
        try:
            from code.scheduler import scheduler
            scheduler.add_job(
                func=mark_as_lost,
                trigger='date',
                run_date=lost_time,
                args=[user_id],
                id=f'trial_lost_{user_id}',
                replace_existing=True
            )
        except Exception as e:
            logger.error(f"无法安排流失标记: {e}")


def mark_as_lost(user_id):
    """标记用户为流失"""
    state = load_state(user_id)
    state["lead_status"] = "lost"
    save_state(user_id, state)
    logger.info(f"用户 {user_id} 标记为流失")
