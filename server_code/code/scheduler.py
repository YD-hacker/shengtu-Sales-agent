"""定时任务调度 - 优化版

新增:
1. 长期关系管理：成交后感谢/回访/行业资讯
2. 信任日衰减任务
3. 周五问候任务
4. 修复 trial_check_job 线程安全
"""
import asyncio
import yaml
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from code.memory_manager import get_inactive_users, load_state, save_state, get_all_user_ids
from code.wake_up import wake_up_user, WAKE_CFG
from code.time_utils import get_beijing_time, BEIJING_TZ
from code.trust_engine import apply_daily_decay, TRUST_INITIAL
from loguru import logger
from code import TRIAL_CFG_FILE, KB

scheduler = BackgroundScheduler()
_main_loop = None

with open(TRIAL_CFG_FILE, encoding="utf-8") as f:
    TRIAL_CFG = yaml.safe_load(f)["trial_follow_up"]


def get_or_create_loop():
    global _main_loop
    if _main_loop is None or _main_loop.is_closed():
        _main_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_main_loop)
    return _main_loop


async def send_to_channel(user_id, message):
    """发送消息到渠道"""
    logger.info(f"【发送消息】{user_id}: {message[:50]}")
    from code.channel_pusher import send_trial_reminder
    return send_trial_reminder(user_id, message)


# ============ 沉睡用户唤醒 ============

def wake_job():
    if not WAKE_CFG.get("enabled", False):
        return
    logger.info("======= 开始执行沉睡用户唤醒任务 =======")
    inactive_ids = get_inactive_users(WAKE_CFG["inactive_days"])
    logger.info(f"找到沉睡用户 {len(inactive_ids)} 人")

    loop = get_or_create_loop()
    for uid in inactive_ids:
        try:
            msg = loop.run_until_complete(wake_up_user(uid))
            if msg:
                success = loop.run_until_complete(send_to_channel(uid, msg))
                if not success:
                    st = load_state(uid)
                    if isinstance(st, dict):
                        st["send_failure"] = True
                        save_state(uid, st)
        except Exception as e:
            logger.error(f"唤醒用户 {uid} 失败: {e}")


# ============ 试听跟进 ============

def trial_check_job():
    from code.channel_pusher import send_trial_reminder
    now = get_beijing_time()

    user_ids = get_all_user_ids()

    for uid in user_ids:
        st = load_state(uid)
        if not isinstance(st, dict):
            logger.warning(f"用户 {uid} state 异常（非dict），跳过试听跟进")
            continue
        if st.get("current_node") not in ("completed", "report_info"):
            continue
        if not st.get("visit_time"):
            continue

        try:
            visit_time = datetime.fromisoformat(st["visit_time"])
            if visit_time.tzinfo is None:
                visit_time = visit_time.replace(tzinfo=BEIJING_TZ)
        except Exception:
            continue

        diff = now - visit_time

        if diff >= timedelta(days=3):
            if not st.get("second_invite_sent"):
                st["second_invite_sent"] = True
                save_state(uid, st)
                send_trial_reminder(uid, TRIAL_CFG.get("no_show_follow_up",
                    "没看到你来，时间不方便可以改到周末哈。"))
            elif diff >= timedelta(days=6) and st.get("lead_status") != "lost":
                st["lead_status"] = "lost"
                save_state(uid, st)
                logger.info(f"用户 {uid} 标记为流失")

        elif diff >= timedelta(hours=1) and not st.get("questionnaire_sent"):
            if now.hour >= 18:
                st["questionnaire_sent"] = True
                save_state(uid, st)
                send_trial_reminder(uid, TRIAL_CFG.get("questionnaire",
                    "今天试听感觉咋样？"))


# ============ 长期关系管理 ============

def relationship_job():
    """
    长期关系管理任务
    - 成交后24h：感谢信息 + 服务流程说明
    - 第7天：主动回访
    - 每14天：行业资讯（不发"考虑得怎么样了"）
    """
    from code.channel_pusher import send_trial_reminder

    now = get_beijing_time()

    user_ids = get_all_user_ids()

    for uid in user_ids:
        st = load_state(uid)

        if not isinstance(st, dict):
            logger.warning(f"用户 {uid} state 异常（非dict），跳过关系管理")
            continue

        # 仅处理已完成的用户
        if st.get("current_node") != "completed":
            continue

        sale_completed_at = st.get("sale_completed_at")
        if not sale_completed_at:
            # 首次进入 completed 状态，记录时间
            st["sale_completed_at"] = now.isoformat()
            save_state(uid, st)
            continue

        try:
            completed_time = datetime.fromisoformat(sale_completed_at)
            if completed_time.tzinfo is None:
                completed_time = completed_time.replace(tzinfo=BEIJING_TZ)
        except Exception:
            continue

        diff_days = (now - completed_time).days

        # 成交后24h感谢
        if diff_days >= 1 and not st.get("post_sale_thankyou_sent"):
            thankyou = KB.get("post_sale_thankyou",
                ["欢迎加入！你的实训安排我会全程跟进，有问题随时找我，小苏一直都在。"])[0]
            send_trial_reminder(uid, thankyou)
            st["post_sale_thankyou_sent"] = True
            save_state(uid, st)
            logger.info(f"用户 {uid} 发送成交感谢")

        # 第7天回访
        elif diff_days >= 7 and not st.get("post_sale_checkin_sent"):
            checkin = KB.get("post_sale_checkin",
                ["实训一周了，感觉怎么样？有什么不适应的跟我说，我帮你协调。"])[0]
            send_trial_reminder(uid, checkin)
            st["post_sale_checkin_sent"] = True
            save_state(uid, st)
            logger.info(f"用户 {uid} 发送7天回访")

        # 每14天发行业资讯（非推销内容，提供价值）
        elif diff_days >= 14:
            last_info = st.get("last_info_sent_date", "")
            today = now.strftime("%Y-%m-%d")
            if last_info != today and (now.weekday() < 5):  # 工作日发
                # 每14天检查一次（简化：每天检查，但只在间隔14天后发）
                try:
                    last_info_date = datetime.strptime(last_info, "%Y-%m-%d")
                    if (now.date() - last_info_date.date()).days >= 14:
                        info = KB.get("weekly_info",
                            ["分享个行业资讯——最近网安岗位需求又涨了15%，你有兴趣可以了解下。"])[0]
                        send_trial_reminder(uid, info)
                        st["last_info_sent_date"] = today
                        save_state(uid, st)
                        logger.info(f"用户 {uid} 发送行业资讯")
                except Exception:
                    pass


# ============ 信任日衰减 ============

def trust_decay_job():
    """每日信任衰减（每天执行一次）"""
    user_ids = get_all_user_ids()

    for uid in user_ids:
        st = load_state(uid)
        if not isinstance(st, dict):
            logger.warning(f"用户 {uid} state 异常（非dict），跳过信任衰减")
            continue
        apply_daily_decay(st)
        save_state(uid, st)


# ============ 周五问候 ============

def friday_greeting_job():
    """每周五下午发问候"""
    from code.channel_pusher import send_trial_reminder
    now = get_beijing_time()

    if now.weekday() != 4:  # 不是周五
        return

    friday_msg = KB.get("friday_greeting", ["周末愉快！下周有什么计划可以跟我说。"])[0]

    user_ids = get_all_user_ids()

    for uid in user_ids:
        st = load_state(uid)
        if not isinstance(st, dict):
            continue
        # 只给活跃用户发（当前在对话流程中）
        if st.get("current_node") in ("invite", "show_fee", "match_campus", "qualify"):
            send_trial_reminder(uid, friday_msg)
            logger.info(f"用户 {uid} 发送周五问候")


# ============ 启动调度器 ============

def start_scheduler():
    """启动所有定时任务"""
    # 唤醒任务
    cron_expr = WAKE_CFG.get("cron", "0 10 * * *")
    parts = cron_expr.strip().split()
    if len(parts) == 5:
        scheduler.add_job(
            wake_job, 'cron',
            minute=parts[0], hour=parts[1],
            day=parts[2], month=parts[3], day_of_week=parts[4],
            id='wake_up', replace_existing=True
        )
    else:
        scheduler.add_job(wake_job, 'cron', minute="0", hour="10",
                          id='wake_up', replace_existing=True)

    # 试听跟进（每10分钟）
    scheduler.add_job(
        trial_check_job, 'interval', minutes=10,
        id='trial_follow_up', replace_existing=True
    )

    # 长期关系管理（每天10:30）
    scheduler.add_job(
        relationship_job, 'cron', minute="30", hour="10",
        id='relationship_mgmt', replace_existing=True
    )

    # 信任衰减（每天凌晨2点）
    scheduler.add_job(
        trust_decay_job, 'cron', minute="0", hour="2",
        id='trust_decay', replace_existing=True
    )

    # 周五问候（每周五17:00）
    scheduler.add_job(
        friday_greeting_job, 'cron', minute="0", hour="17", day_of_week="fri",
        id='friday_greeting', replace_existing=True
    )

    scheduler.start()

    # 恢复未执行的挽回任务
    try:
        from code.recovery_engine import restore_pending_recoveries
        restore_pending_recoveries()
    except Exception as e:
        logger.warning(f"恢复挽回任务失败: {e}")

    logger.info("调度器已启动（唤醒+试听跟进+关系管理+信任衰减+周五问候）")
